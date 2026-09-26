#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端:跑关键页面闭环**和禁止行为**(规格 §17.5 `test-e2e`)。

## 为什么「禁止行为」和「能用」一样重要

一套只测「点了能成」的端到端,证明的是**功能存在**,不是**边界存在**。
而这个后台的价值几乎全在边界上:草稿不影响生产、没权限不能改、
跨项目看不见、超时重发不会重复扣费、异步不许谎报完成。

所以下面每一组都是**一条正向 + 一条该被拒**。少了正向那半,
「全被拒」可能只说明服务挂了;少了负向那半,那条边界根本没被测过。
"""
import json, os, sys, urllib.request, urllib.error, uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
A, B = "project_demo_a", "project_demo_b"

过, 挂 = [], []
def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:130]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路径, 用户=None, 体=None, 头=None):
    """返回 (状态码, 响应体)。**不抛异常** —— 4xx 是这套测试的主角。"""
    url = 基址 + 路径
    data = json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None
    req = urllib.request.Request(url, data=data, method=方法)
    if data is not None: req.add_header("content-type", "application/json")
    if 用户: req.add_header("X-Dev-User", 用户)
    for k, v in (头 or {}).items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw or b"{}")
        except Exception: return e.code, {"_raw": raw.decode(errors="replace")[:200]}


P = f"/api/v1/projects/{A}"

# ── 0. 服务活着,而且**演示模式醒目** ──────────────────────────────
c, h = 打("GET", "/api/healthz")
ck("服务活着", c == 200, h)
ck("**演示模式有醒目标记**(看不出自己在演示模式的界面,会让人拿编的结果当真的)",
   h.get("演示模式") is True and h.get("演示说明"), h.get("演示说明", "")[:60])

# ── 1. 身份 ───────────────────────────────────────────────────────
c, b = 打("GET", "/api/v1/projects")
ck("没身份 → 401", c == 401 and b.get("code") == "NO_IDENTITY", c)
ck("**错误体是平的,顶层就有 advice**(不是 FastAPI 默认的 {detail:…})",
   "advice" in b and "detail" not in b, list(b))
c, b = 打("GET", "/api/v1/projects", "U002")
ck("有身份 → 只看到有权的项目", c == 200 and [x["id"] for x in b["items"]] == [A],
   [x["id"] for x in b["items"]])

# ── 2. 跨项目:改 URL 里的项目号绕不过去(§19.1)───────────────────
c, b = 打("GET", f"/api/v1/projects/{A}/prompts", "U005")     # U005 只在 B
ck("**U005 只在 B 项目,访问 A 项目 → 404**(不确认「存在但你没权限」)",
   c == 404 and b.get("code") == "NO_MEMBERSHIP", f"{c} {b.get('code')}")
c, b = 打("GET", f"/api/v1/projects/{B}/prompts", "U005")
ck("U005 访问自己的 B 项目 → 200(否则上一条只证明了服务挂了)", c == 200,
   c)

# ── 3. 权限矩阵真的在执行 ─────────────────────────────────────────
c, b = 打("POST", P + "/prompts", "U003", {"key": "viewer_should_fail"})
ck("**viewer 建 Prompt → 403**,而且说清怎么拿到权限",
   c == 403 and "管理员" in (b.get("advice") or ""), f"{c} {(b.get('advice') or '')[:50]}")
c, b = 打("GET", P + "/prompts", "U003")
ck("viewer 看列表 → 200(「不能改」不等于「不能看」)", c == 200, c)

# ── 4. Prompt 列表:最新版本 / 生产版本 并排(§8.1)─────────────────
c, b = 打("GET", P + "/prompts", "U002")
项 = {x["key"]: x for x in b["items"]}
ck("列表同时给「最新保存版本」和「生产引用版本」(避免以为保存就上线)",
   all("最新版本" in x and "生产版本显示" in x for x in b["items"]),
   list(项))
ck("**没评测时显示「尚未评测」,不显示 0**",
   all(x["评测状态"] == "尚未评测" for x in b["items"]))
ck("**total 未知时是 null,不是 0**(0 会被读成「一条都没有」)",
   b["total"] is None, b["total"])

# ── 5. 草稿:乐观锁 ────────────────────────────────────────────────
pid = 项["article_summary"]["id"]
c, d = 打("GET", P + f"/prompts/{pid}", "U002")
rev = d["草稿"]["revision"]
c, b = 打("PATCH", P + f"/prompts/{pid}/draft", "U002", {"变更说明": "改一句"})
ck("PATCH **不带 If-Match → 被拒**(否则就是「最后写的人赢」)",
   c in (409, 428) and b.get("code") == "IF_MATCH_REQUIRED", f"{c} {b.get('code')}")
# ⚠️ 变更说明**每次跑都不一样**。写死一句话的话,第二次跑时草稿内容和上一版
# 完全相同,服务端会正确地返回 409「一字没改」—— 而那个红看起来和真的坏了一样。
# 顺带这也更像真实用法:变更说明本来每次都不同。
本轮说明 = f"把待核实事项单独成段(e2e {uuid.uuid4().hex[:8]})"
c, b = 打("PATCH", P + f"/prompts/{pid}/draft", "U002",
          {"变更说明": 本轮说明}, 头={"If-Match": str(rev)})
ck("带对的 If-Match → 存上,revision 前进", c == 200 and b["revision"] == rev + 1,
   b.get("revision"))
ck("响应明说**草稿不影响生产**", "不影响" in (b.get("note") or ""), b.get("note", "")[:40])
c, b = 打("PATCH", P + f"/prompts/{pid}/draft", "U002", {"变更说明": "并发写"},
          头={"If-Match": str(rev)})          # 拿旧 revision 再写一次
ck("**拿旧 revision 再写 → 409,而且告诉你别直接覆盖**",
   c == 409 and "不要直接覆盖" in (b.get("advice") or ""), f"{c} {(b.get('advice') or '')[:40]}")

# ── 6. 存正式版本:前置校验 + 不可变 + 同内容不给新版本 ─────────────
c, b = 打("POST", P + f"/prompts/{项['draft_with_gap']['id']}/versions", "U002")
ck("**模板里有没定义的变量 → 拦住,不许存版本**",
   c == 422 and b.get("code") == "NOT_READY", f"{c} {(b.get('advice') or '')[:60]}")
# ⚠️ **这套测试必须能重跑。** 第一版断言「存出 v1」,于是第二次跑就红了 ——
# 因为内容没变、服务端正确地返回 409 NO_CHANGE。
# 而「第二次跑的红」和「真的坏了」在输出上长得一模一样,
# 这会让人开始无视这套测试。所以:先看现在最大版本号是几,断言它**前进了一格**。
c, d0 = 打("GET", P + f"/prompts/{pid}", "U002")
原有版本数 = len(d0["版本历史"])
c, b = 打("POST", P + f"/prompts/{pid}/versions", "U002")
ck(f"校验通过 → 存出 v{原有版本数 + 1}(版本号前进一格,而不是写死 v1)",
   c == 201 and b["version_no"] == 原有版本数 + 1, f"{c} {b}")
一版哈希 = b.get("content_hash")
c, b2 = 打("POST", P + f"/prompts/{pid}/versions", "U002")
ck("**一字没改再存一次 → 409**(一串内容相同的版本号会让「版本变了」失去含义)",
   c == 409 and b2.get("code") == "NO_CHANGE", f"{c} {b2.get('code')}")
c, d2 = 打("GET", P + f"/prompts/{pid}", "U002")
ck("详情里能看到版本历史(多了一条)", len(d2["版本历史"]) == 原有版本数 + 1,
   len(d2["版本历史"]))

# ── 7. 调试运行:异步 + 幂等 + 缺变量前置拦截(§8.4)────────────────
c, b = 打("POST", P + "/prompt-runs", "U002", {"prompt_id": pid, "变量": {}})
ck("**不带 Idempotency-Key → 被拒**(超时重发会多花一次钱)",
   c == 409 and b.get("code") == "IDEMPOTENCY_KEY_REQUIRED", f"{c} {b.get('code')}")
键 = uuid.uuid4().hex
c, b = 打("POST", P + "/prompt-runs", "U002", {"prompt_id": pid, "变量": {}},
          头={"Idempotency-Key": 键})
ck("**缺必填变量 → 调用前就拦住**(不是跑完再说)",
   c == 422 and b.get("code") == "MISSING_VARIABLES", f"{c} {b.get('field_errors')}")
键2 = uuid.uuid4().hex
体 = {"prompt_id": pid, "变量": {"article": "这是一篇测试文章。", "audience": "工程师"}}
c, r1 = 打("POST", P + "/prompt-runs", "U002", 体, 头={"Idempotency-Key": 键2})
ck("**跑一次 → 202 + 任务信封**(不是直接返回答案)", c == 202 and r1.get("job_id"), c)
ck("信封字段齐(job_id/status/resource_id/status_url/trace_id)",
   all(k in r1 for k in ("job_id", "status", "resource_id", "status_url", "trace_id")),
   list(r1))
c, r2 = 打("POST", P + "/prompt-runs", "U002", 体, 头={"Idempotency-Key": 键2})
ck("**同一个幂等键再打一次 → 返回同一个任务,不新建**",
   r2.get("job_id") == r1.get("job_id"), f"{r1.get('job_id')} vs {r2.get('job_id')}")

# ── 8. 任务详情:脱敏 + 字段级权限 + 未知费用 ──────────────────────
c, j = 打("GET", P + f"/jobs/{r1['job_id']}", "U002")
ck("任务详情拿得到", c == 200 and j["status"], j.get("status"))
ck("**终态要明确标出来**(「不确定」不能被当成结束)", j.get("是终态吗") is True)
段 = (j.get("结果") or {}).get("阶段") or []
ck("U002 没有专项授权 → **实际发送内容是脱敏的**",
   段 and "已脱敏" in json.dumps(段[0]["实际发送"], ensure_ascii=False),
   json.dumps(段[0]["实际发送"], ensure_ascii=False)[:60] if 段 else "没有阶段")
c, j4 = 打("GET", P + f"/jobs/{r1['job_id']}", "U004")     # U004 有专项授权
段4 = (j4.get("结果") or {}).get("阶段") or []
ck("U004 有「查看敏感输入」专项授权 → **看得到原文**",
   段4 and "展开后模板" in json.dumps(段4[0]["实际发送"], ensure_ascii=False),
   json.dumps(段4[0]["实际发送"], ensure_ascii=False)[:60] if 段4 else "没有阶段")
用量 = (j.get("结果") or {}).get("用量") or []
ck("**mock 跑的费用记成「未知」,不是 0**",
   用量 and 用量[0]["amount_known"] is False and 用量[0]["amount"] is None,
   用量[0] if 用量 else "没有用量")

# ── 9. 工作台(§6)────────────────────────────────────────────────
c, w = 打("GET", P + "/workbench", "U002")
ck("工作台拿得到", c == 200 and w.get("卡片"), c)
卡 = {x["名"]: x for x in w["卡片"]}
ck("每张卡都带时间范围/环境/数据来源/更新时间",
   all(all(k in x for k in ("时间范围", "环境", "数据来源", "更新时间"))
       for x in w["卡片"]))
ck("**业务质量分数显示「未知」而不是 0 分**(0 会被读成「质量很差」)",
   卡["业务质量分数"]["未知"] is True and 卡["业务质量分数"]["值"] is None,
   卡["业务质量分数"])
ck("**成功率那张卡明说它不代表回答对不对**",
   "不代表回答对不对" in 卡["请求成功返回率"]["说明"])
ck("费用未覆盖数量单独一张卡(未知不混进已知费用里)",
   "费用未覆盖数量" in 卡)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
if 挂:
    for x in 挂: print("   ·", x)
sys.exit(1 if 挂 else 0)
