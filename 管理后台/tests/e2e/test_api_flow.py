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

# ── 怎么「等 Worker」:等到**这一条**到终态,不是等一轮 drain 返回 ────────
# ⚠️ 这一节原来写的是「`worker.py --一轮` 跑一趟,然后立刻断言『已完成』」。
# 那不是等待,那是**赌**:
#
#   `取一个()` 的 SQL 明确跳过 `lease_until > now()` 的行 ——
#   也就是**已经被别的 Worker 租走的**那些。开发机上 `make dev`
#   起了一个常驻 Worker,它可能先把这条抢走;这时候 `--一轮` 捞不到东西,
#   于是**立刻打印一行启动信息就退出**,而任务还停在「执行中」。
#
# 2026-09-29 确定性地复现过:先让另一个 owner 租走那条,再跑 `--一轮`,
# 它只输出 `worker 起来了:...` 就退,任务状态是「执行中」——
# 测试在这一刻断言「已完成」,于是红,而它报的理由是
# 「Worker 跑完 → 已完成」失败,**离真因(被别人租着)隔了好几层**。
#
# 队列空的时候常驻 Worker 毫秒级跑完,所以单独跑从来是绿的;
# 连跑 15 份、队列有积压的时候它慢,于是间歇性红 ——
# **一条会假红的判据,会把人教会忽略它**,那时它连真的那次也拦不住。
#
# 所以判据换成结构性的那个:**「我这一条到终态了吗」**。
# 两件事必须同时成立,少一件这个改动就变成了「把红改绿」:
#   ① 每轮都再踢一次 Worker —— CI 上没有常驻 Worker,光等是等不到的;
#   ② 等不到要**响亮地失败并且带上最后看到的状态** ——
#      「等到了」和「等超时了」必须长得不一样。
import subprocess as _sp
import time as _time
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PY = os.path.join(_ROOT, ".venv", "bin", "python")


def 踢一轮():
    """让 Worker 把当前能捞到的都跑完。**捞不到不代表没活** —— 见上面那段。"""
    return _sp.run([_PY, os.path.join(_ROOT, "workers", "worker.py"), "--一轮"],
                   capture_output=True, text=True, timeout=120, cwd=_ROOT)


def 等到终态(job_id, 谁="U002", 秒=60):
    """踢 Worker,**等到这一条自己说它是终态**。等不到就抛,不静默放过。

    返回任务详情。`秒` 是**上限**不是窗口:到了就抛,而且抛的时候
    把最后看到的状态和事件链一起说出来 —— 不然下一个人只看到
    「等超时了」,还得自己再查一遍它卡在哪。
    """
    起 = _time.time()
    最后 = None
    while True:
        踢一轮()
        c, j = 打("GET", P + f"/jobs/{job_id}", 谁)
        if c == 200 and j.get("是终态吗") is True:
            return j
        最后 = (c, j)
        if _time.time() - 起 > 秒:
            状 = (最后[1] or {}).get("status")
            事 = [e.get("kind") for e in ((最后[1] or {}).get("事件") or [])]
            raise AssertionError(
                f"等了 {秒} 秒 {job_id} 还没到终态:status={状!r} 事件={事}。"
                f"**这不是等待窗口不够** —— 要么 Worker 没在跑,"
                f"要么它卡在某一阶段;去看 /tmp/aimc-worker.log")
        _time.sleep(0.3)


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
# ⚠️ **这一节原来假设 API 返回时结果已经有了** —— 那是改成真异步之前的行为。
# 现在 API 只受理(202 + 排队中),**要先让 worker 跑一轮**才有 trace。
# 这一族错很典型:测试把「当前实现」当成了「该有的行为」,
# 于是实现往对的方向改了之后,测试反而红 —— 而红的理由完全指错方向
# (它报的是「脱敏没生效」,真相是「还没跑」)。
j = 等到终态(r1["job_id"])
ck("任务详情拿得到", bool(j["status"]), j.get("status"))
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

# ── ⑩ 真异步:API 只受理,Worker 才跑(§19.1 / §19.3)───────────────
键3 = uuid.uuid4().hex
c, r3 = 打("POST", P + "/prompt-runs", "U002",
          {"prompt_id": pid, "变量": {"article": "端到端异步测试", "audience": "PM"}},
          头={"Idempotency-Key": 键3})
ck("**API 只受理:返回「排队中」,resource 有了但 trace 还没有**",
   c == 202 and r3["status"] == "排队中" and r3.get("trace_id") is None, r3)
# ⚠️ 这两条原来是**对着一个瞬态**断言的:POST 完立刻 GET,要求这时候
# status 还得是「排队中」、事件表里**只有**「已受理」一条。
#
# 改掉它不是因为量到了它红,而是因为**它断言的东西本来就不由它决定**:
# 开发机上 `make dev` 起了一个常驻 Worker,任务一进队列它就可能捞走。
# 2026-09-29 量过它抢占同一条任务的延迟:**0.25 秒 / 1.5 秒 / 超过 2.75 秒**
# (`worker.py` 的 `main()` 有退避 `sleep(min(5.0, 0.2*空转))`,所以差十倍)。
# 这个延迟目前比 POST→GET 之间那几毫秒长得多,所以这两条**平时是绿的** ——
# 但绿的原因是「常驻慢了一步」,不是「这个性质成立」。
#
# ⚠️ **我试过把它压红,没压出来**(0.15 秒一条地灌队列、新旧两版各连跑 5 遍,
# 旧版也全绿)。所以别把下面的改动读成「这就是那条假红的真因」——
# **真因是另一个,已经确定性复现了,见文件顶上 `等到终态` 那一段**。
# 这里改的是同一类形状的第二处:一条断言瞬态的判据,靠的是「别人慢了一步」,
# 而那是环境给的,不是代码保证的。**加等待还会让它更容易红**(等得越久越可能已完成),
# 所以只能把判据换成任何时刻都成立的那个:
#   ① 「API 没同步跑模型」这件事,**POST 的响应自己就说清了**
#      (202 + 排队中 + 没有 trace)—— 那一条在上面已经断过,race-free。
#   ② 「已受理不是开始」要的是**起点唯一**:链的第一条永远是「已受理」,
#      而且它**只出现一次**。这个性质在任务跑完之后照样成立。
c, j3 = 打("GET", P + f"/jobs/{r3['job_id']}", "U002")
种3 = [e["kind"] for e in j3["事件"]]
ck("事件链的**第一条**是「已受理」(起点要唯一 —— 两个开始会让人分不清真起点)",
   种3[:1] == ["已受理"], 种3)
ck("「已受理」**只出现一次**(受理两次 = 同一个请求被当成两件事)",
   种3.count("已受理") == 1, 种3)

j4 = 等到终态(r3["job_id"])
ck("Worker 跑完 → 已完成,而且是终态", j4["status"] == "已完成" and j4["是终态吗"], j4["status"])
种 = [e["kind"] for e in j4["事件"]]
# ⚠️⚠️ **2026-10-03 从「完全相等」改成「这几个里程碑按序都在」。**
#
# 原来断的是 `种 == ["已受理","开始","展开模板","调模型","完成"]`。
# 当天加了一个新阶段事件(`定执行模式`:这一次跑真模型还是 mock)——
# 这条断言当场红,而**链是好的**。
#
# > 一条对任何新增阶段都会红的断言,拦不住真问题,只拦住改动 ——
# > 而「多了一个合理的新阶段」和「链断了」在那个 `==` 上长得一模一样。
#
# 现在断两件它真正要守的事:
#   ① 那几个里程碑**都在,而且顺序没乱**(中间可以有别的阶段)
#   ② **没有多余的「开始」/「完成」**(重复的终态会让人分不清哪次是真的)
# ⚠️ 不改成「只要包含就行」:那会放过「完成出现两次」这种真问题。
里程碑 = ["已受理", "开始", "展开模板", "调模型", "完成"]
位 = [种.index(x) if x in 种 else -1 for x in 里程碑]
ck(f"事件链里 {'→'.join(里程碑)} **都在、而且顺序没乱**"
   f"(中间允许有别的阶段 —— 这里现在就多一条「定执行模式」)",
   all(p >= 0 for p in 位) and 位 == sorted(位), 种)
ck("「开始」和「完成」各只出现一次(重复的终态会让人分不清哪次是真的)",
   种.count("开始") == 1 and 种.count("完成") == 1, 种)
ck("seq 连续没断号(断号 = 有事件没写进来,而界面上看不出来)",
   [e["seq"] for e in j4["事件"]] == list(range(1, len(种) + 1)),
   [e["seq"] for e in j4["事件"]])
用4 = (j4.get("结果") or {}).get("用量") or []
ck("费用仍然是「未知」而不是 0(mock 没有真实计价)",
   用4 and 用4[0]["amount_known"] is False, 用4[0] if 用4 else "没有用量")

# ── ⑪ 幂等:重复投递不重跑模型 ────────────────────────────────────
# Outbox 的设计**保证**会有重复投递(§17.1),所以这条不是「尽量」。
_前 = None
c, jb = 打("GET", P + f"/jobs/{r3['job_id']}", "U002")
_前 = (jb.get("结果") or {}).get("trace_id")
# 把任务掰回「排队中」,让 worker 再捞一次同一条
import urllib.request as _ur
_sp.run([_PY, "-c", f'''
import os, sys
sys.path.insert(0, os.path.join({_ROOT!r}, "services", "api", "app"))
from sqlalchemy import text
from db import 事务
with 事务() as c:
    c.execute(text("""update jobs set status='排队中', lease_owner=null,
        lease_until=null, next_retry_at=null where project_id=:p and id=:i"""),
        {{"p": {A!r}, "i": {r3["job_id"]!r}}})
'''], capture_output=True, text=True, timeout=60, cwd=_ROOT)
j5 = 等到终态(r3["job_id"])
后 = (j5.get("结果") or {}).get("trace_id")
ck("**重复投递 → 幂等命中,不重跑模型(trace 还是同一个)**", 后 == _前, f"{_前} vs {后}")
ck("而且事件里留了痕(「跳过」那一条说清了为什么)",
   any(e["kind"] == "跳过" for e in j5["事件"]),
   [e["kind"] for e in j5["事件"]])


# ⚠️ **汇总必须在最后。** 往 `sys.exit()` 后面追加的断言**永远不会跑**,
# 而它们不跑的时候,总数看起来只是「没变」—— 我 2026-09-26 就这么加了两节白的。
print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
if 挂:
    for x in 挂: print("   ·", x)
sys.exit(1 if 挂 else 0)
