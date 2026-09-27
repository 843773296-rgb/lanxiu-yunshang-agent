#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编排端到端 —— **把「我手敲 curl 验过」变成可重跑的断言**。

## 为什么非写这一份

`docs/实现进度.md`(运行时记账生成的)第一次跑出来就抓到:
工作流和智能体那 12 条接口里,**只有 2 条被自动化测试打过**。

其余 10 条我确实验过 —— **但是手敲 curl 验的**。那种验证:
· 不留痕(下一个人看不到它被验过)
· 不可重跑(改坏了没人会发现)
· 换台机器就没了

而我在提交信息里写过「整条链在真库上走通」——那句话是真的,
**但没人能再跑一遍它**。规格 §20 分「已实现且验证 / 已实现未验证」正是为了这个,
而我一直把自己手工跑过的算成了「验过」。

> **一次没留下可重跑证据的验证,和没验证之间的差别,只存在于验的人脑子里。**

## 这一份和 test_api_flow 的分工

`test_api_flow.py` 测的是主规格那一层(Prompt / 任务 / 脱敏 / 跨项目)。
这一份专测编排:建图 → 校验 → 冻结 → 试运行 → Worker,以及 Agent 那一条。
**每一步都断言「服务端说了什么」,不只断言 HTTP 200。**
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(根, ".venv", "bin", "python")

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None, 头=None):
    req = urllib.request.Request(基址 + 路, method=方法,
                                data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 跑worker():
    """跑一轮 = **处理一个任务**(worker.py --一轮 的语义)。"""
    subprocess.run([PY, os.path.join(根, "workers", "worker.py"), "--一轮"],
                   capture_output=True, text=True, timeout=180, cwd=根)


def 等到终态(rid, 谁="U004", 最多=8):
    """反复跑 worker 直到这个 Run 进终态。**不用 sleep 猜。**

    ⚠️ 两次栽在这儿,两次的表现都是「看到『排队中』,以为 Worker 没接」:
      ① 第一次用 `sleep 5` —— 而 Agent 要两个模型回合 + 一次工具调用,5 秒不够;
      ② 第二次改成跑一轮 worker —— 而 `--一轮` 是**处理一个任务**,
         队列里有两个(工作流 + Agent)时它只吃掉第一个。
    **靠「等一会儿」或「跑一次」的测试,会在时序变一点的那天变红,
    而报的理由完全指错方向**(它说「功能没做完」,真相是「还没跑」)。

    所以判据换成「**跑到这个 Run 自己说它是终态**」——
    和队列里有几个任务、每个跑多久都无关。
    """
    for _ in range(最多):
        c, r = 打("GET", P + f"/execution-runs/{rid}", 谁)
        if c == 200 and r.get("是终态吗"):
            return r
        跑worker()
    c, r = 打("GET", P + f"/execution-runs/{rid}", 谁)
    return r


print("▸ 工作流:建 → 校验 → 补引用 → 再校验 → 冻结 → 试运行 → Worker → 详情")
c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 编排 {uuid.uuid4().hex[:6]}",
                                     "模板": "文本处理"})
ck("**建工作流**返回 201 和 id,而且明说「和生产没有任何关系」",
   c == 201 and w.get("id") and "生产" in (w.get("note") or ""), f"{c} {w.get('id')}")
wid = w["id"]

c, b = 打("POST", P + f"/workflows/{wid}/validate")
阻 = [p for p in (b or {}).get("问题", []) if p["级别"] == "blocking"]
ck("**模板刚建出来是过不了校验的**(模板只预填草稿,不替你选连接和 Prompt 版本)",
   c == 200 and not b["通过"] and {p["code"] for p in 阻} == {"NODE_MISSING_CONFIG"},
   f"{c} 阻断 {[p['field_path'] for p in 阻]}")
ck("而且每条阻断都带 node_id 和 field_path(点着能定位,§17.1)",
   all(p["node_id"] and p["field_path"] for p in 阻), 阻[:1])

c, d = 打("GET", P + f"/workflows/{wid}")
ck("**详情给出节点库,并标出哪些节点不可用**(未实现的不摆空按钮)",
   c == 200 and any(not n["可用"] for n in d["节点库"])
   and {n["中文"] for n in d["节点库"] if not n["可用"]}
       == {"并行与汇总", "有界循环", "列表迭代", "子工作流"},
   [n["中文"] for n in d["节点库"] if not n["可用"]])
rev = d["草稿"]["revision"]
定义 = d["草稿"]["定义"]
for n in 定义["nodes"]:
    if n["type"] == "llm":
        n["config"]["connection_version_id"] = "cv_mock_" + 项目
        n["config"]["prompt_version_id"] = "pv_seed_article_summary"

c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义},
         头={"If-Match": "999"})
ck("**拿错 revision 改草稿 → 409,而且告诉你别直接覆盖**",
   c == 409 and "不要直接覆盖" in ((b or {}).get("advice") or ""),
   f"{c} {(b or {}).get('code')}")

c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义},
         头={"If-Match": str(rev)})
ck("改草稿成功,revision 前进一格,并且校验状态被作废",
   c == 200 and b["revision"] == rev + 1 and "没再校验" in b["校验状态"],
   f"r{rev} → r{b.get('revision')} · {b.get('校验状态')}")

c, b = 打("POST", P + f"/workflows/{wid}/validate")
ck("补上连接和 Prompt 版本之后 → **校验通过**", c == 200 and b["通过"],
   f"{c} 阻断 {b.get('阻断数')}")
ck("而且报告里写明「过了也只说明定义合法」(附录 A-1 的局限)",
   "定义" in b["说明"] and ("模型" in b["说明"] or "外部" in b["说明"]))

c, b = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": ""})
ck("**变更说明空着 → 422**(它是版本对比时唯一能说清意图的东西)",
   c == 422 and (b or {}).get("code") == "CHANGE_NOTE_REQUIRED", c)

c, v = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": "e2e 第一版"})
ck("**冻结 v1**,带逻辑哈希和确切依赖清单",
   c == 201 and v["版本"] == "v1" and v["逻辑哈希"].startswith("sha256:")
   and len(v["依赖"]) == 2, f"{c} {v.get('版本')} 依赖 {len(v.get('依赖') or [])}")
ck("冻结的响应明说**没发布**(生产指针没变)", "没发布" in (v.get("note") or ""))

c, b = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": "一字没改再冻一次"})
ck("**内容一字没改再冻 → 409 NO_SEMANTIC_CHANGE**"
   "(两个逻辑相同的版本会让「生产引用哪一版」失去意义)",
   c == 409 and (b or {}).get("code") == "NO_SEMANTIC_CHANGE", c)

c, d2 = 打("GET", P + f"/workflows/{wid}")
布局 = dict(d2["草稿"]["布局"])
布局[list(布局)[0]] = {"x": 999, "y": 7}
c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"布局": 布局},
         头={"If-Match": str(d2["草稿"]["revision"])})
ck("**只挪坐标 → 响应明说不影响执行语义**(附录 A-9:坐标不进逻辑哈希)",
   c == 200 and "不影响执行语义" in (b.get("note") or ""), b.get("note", "")[:40])

c, b = 打("POST", P + "/execution-runs",
         体={"workflow_id": wid, "输入": {"article": "e2e 用的一段正文"}})
ck("**试运行没带幂等键 → 409**(超时重发一次就是跑第二遍)",
   c == 409 and (b or {}).get("code") == "IDEMPOTENCY_KEY_REQUIRED", c)

键 = str(uuid.uuid4())
c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": 键},
         体={"workflow_id": wid, "输入": {"article": "e2e 用的一段正文"}})
ck("**试运行返回 202 排队中,一个模型都还没调**",
   c == 202 and r["status"] == "排队中" and r["trace_id"] is None, f"{c} {r.get('status')}")
rid = r["resource_id"]
c, r2 = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": 键},
          体={"workflow_id": wid, "输入": {"article": "e2e 用的一段正文"}})
ck("**同一个幂等键再打一次 → 返回原任务,不新建**",
   r2.get("resource_id") == rid, f"{r2.get('resource_id')} vs {rid}")

c, b = 打("POST", P + "/execution-runs", "U003", 头={"Idempotency-Key": str(uuid.uuid4())},
         体={"workflow_id": wid, "输入": {"article": "x"}})
ck("**查看者(U003)试运行 → 403**(调试也花钱,要过额度那条权限)",
   c == 403 and (b or {}).get("code") == "FORBIDDEN", c)

run = 等到终态(rid)
ck("Worker 跑完 → **已完成,而且是终态**",
   run["执行状态"] == "succeeded" and run["是终态吗"],
   f"{run.get('执行状态')} 终态={run.get('是终态吗')}")
ck("**执行状态和任务达标分两栏**,达标默认「未评」"
   "(succeeded 不代表里面的事实对)",
   run["任务达标"] == "未评" and "不等于" in (run.get("达标说明") or ""))
ck("每一步都带**执行键**(Run/node/循环路径/尝试次数)",
   all(s["执行键"] and s["执行键"].startswith(rid) for s in run["步骤"]),
   [s["执行键"] for s in run["步骤"]][:1])
ck("事件按 seq 连续没断号(SSE 续传靠它)",
   [e["seq"] for e in run["事件"]] == list(range(1, len(run["事件"]) + 1)),
   [e["seq"] for e in run["事件"]])

c, 脱 = 打("GET", P + f"/execution-runs/{rid}", "U002")
ck("**U002 看不到输出原文(脱敏),U004 有专项授权看得到**",
   "***" in str(脱["输出"]) and "***" not in str(run["输出"]),
   f"U002:{str(脱['输出'])[:24]} / U004:{str(run['输出'])[:24]}")

c, b = 打("GET", P + f"/execution-runs/{rid}", "U005")
ck("**拿 A 项目的 Run ID 用 B 项目的人去读 → 404**(不确认它存在)", c == 404, c)

c, 列 = 打("GET", P + "/execution-runs")
ck("运行列表把**执行状态和任务达标分成两列**",
   c == 200 and all("执行状态" in x and "任务达标" in x for x in 列["items"]),
   len(列.get("items") or []))

print("\n▸ 智能体:建 → 校验 → 换成不支持工具调用的连接 → 被挡 → 换回 → 冻结 → 跑")
c, a = 打("POST", P + "/agents", 体={"名称": f"e2e Agent {uuid.uuid4().hex[:6]}"})
ck("**建 Agent** 返回 201(模板预填,不调模型不绑生产)",
   c == 201 and a.get("id") and "没关系" in (a.get("note") or ""), c)
aid = a["id"]

c, b = 打("POST", P + f"/agents/{aid}/validate")
ck("模板预填的配置**校验通过**(它挑了一条声明支持原生工具调用的连接)",
   c == 200 and b["通过"], f"{c} {[p['code'] for p in b.get('问题', [])]}")

c, d = 打("GET", P + f"/agents/{aid}")
ck("**详情把每条运行限制的「强制执行位置」和「落地了吗」都给出来**"
   "(只存在于表单里的上限等于没有这条限制)",
   c == 200 and len(d["运行限制说明"]) == 10
   and all("强制执行位置" in l and "已落地" in l for l in d["运行限制说明"]),
   len(d.get("运行限制说明") or []))
ck("**可选连接那一栏给的是探测回来的能力**,不是模型名字(附录 D.2)",
   all("原生工具调用" in x for x in d["可选连接"])
   and any(not x["原生工具调用"] for x in d["可选连接"]),
   [(x["名称"], x["原生工具调用"]) for x in d["可选连接"]])
# ⚠️ 这一条第一版查错了地方:「不是能力强弱分」那句写在**列表**响应的
# `工具数说明` 上,不在详情里。断言查错了对象,报出来的是「功能没做」——
# 而功能是做了的。**一条查错对象的断言,和一条真的失败,在输出上一模一样。**
c, 列 = 打("GET", P + "/agents")
ck("**列表里工具数旁边写明它不是能力分**(§9.1)",
   c == 200 and 列["items"] and "能力强弱" in (列["items"][0].get("工具数说明") or ""),
   (列.get("items") or [{}])[0].get("工具数说明", "")[:50])

cfg = dict(d["草稿"]["配置"])
不支持 = [x for x in d["可选连接"] if not x["原生工具调用"]][0]
cfg["connection_version_id"] = 不支持["id"]
c, b = 打("PATCH", P + f"/agents/{aid}/draft", 体={"配置": cfg},
         头={"If-Match": str(d["草稿"]["revision"])})
ck("改 Agent 草稿成功", c == 200, c)
c, b = 打("POST", P + f"/agents/{aid}/validate")
码 = {p["code"] for p in b["问题"] if p["级别"] == "blocking"}
ck("**换成没声明原生工具调用的连接 → 校验当场挡住**"
   "(§9.3 能力检查;附录 D.2 不按模型家族名字推断兼容)",
   not b["通过"] and "MODEL_NO_TOOL_CALLING" in 码, 码)
ck("而且建议里点明「capabilities 要靠探测填,不是靠猜」",
   any("探测" in p["建议"] for p in b["问题"] if p["code"] == "MODEL_NO_TOOL_CALLING"))

c, b = 打("POST", P + f"/agents/{aid}/versions", 体={"变更说明": "带着阻断硬冻"})
ck("**有阻断时冻结被拒**,而且 field_errors 指到具体字段",
   c == 422 and (b or {}).get("field_errors"), f"{c} {list((b or {}).get('field_errors') or {})}")

c, d = 打("GET", P + f"/agents/{aid}")
cfg = dict(d["草稿"]["配置"])
cfg["connection_version_id"] = [x for x in d["可选连接"] if x["原生工具调用"]][0]["id"]
打("PATCH", P + f"/agents/{aid}/draft", 体={"配置": cfg},
  头={"If-Match": str(d["草稿"]["revision"])})
c, b = 打("POST", P + f"/agents/{aid}/validate")
ck("换回支持的连接 → 通过(**对照:这道闸不是一律拒绝**)", b["通过"], b.get("阻断数"))

c, v = 打("POST", P + f"/agents/{aid}/versions", 体={"变更说明": "e2e 第一版"})
ck("**冻结 Agent v1**,工具和策略固定成确切版本",
   c == 201 and v["版本"] == "v1" and v["内容哈希"].startswith("sha256:"), c)

键 = str(uuid.uuid4())
c, r = 打("POST", P + "/agent-runs", 头={"Idempotency-Key": 键},
         体={"agent_id": aid, "输入": {"products": ["甲", "乙"]}})
ck("**跑 Agent 返回 202 排队中**", c == 202 and r["status"] == "排队中", c)
arid = r["resource_id"]

c, b = 打("POST", P + "/agent-runs", 头={"Idempotency-Key": str(uuid.uuid4())},
         体={"agent_id": aid, "输入": {"products": []}})
ck("**输入不合规 → 调用前 422 拦住**(§C.2「信息缺失」:询问或拦截,不猜输入)",
   c == 422 and (b or {}).get("code") == "VALIDATION", f"{c} {(b or {}).get('message','')[:40]}")

ar = 等到终态(arid)
ck("Agent 跑完 → **已完成**", ar["执行状态"] == "succeeded",
   ar.get("执行状态"))
ck("用量里**模型回合和工具尝试分开数**(回合含修复请求,§9.6)",
   ar["用量"].get("模型回合") == 2 and ar["用量"].get("工具尝试") == 1, ar.get("用量"))
类 = [e["类型"] for e in ar["事件"]]
ck("事件链完整:受理 → 适配器清单 → 回合 → 模型响应 → 工具 → finish",
   类[:2] == ["run.accepted", "agent.adapters"]
   and "tool.succeeded" in 类 and "agent.finish_claimed" in 类, 类)
适 = [e["载荷"] for e in ar["事件"] if e["类型"] == "agent.adapters"][0]
ck("**适配器清单说清「接了哪些、没接哪些、为什么」**"
   "(写工具默认不接 mock,§14.1 要显示替换清单)",
   适.get("接了") and 适.get("没接") and "ADAPTER_MISSING" in (适.get("为什么") or ""),
   f"接了 {适.get('接了')} / 没接 {适.get('没接')}")
ck("任务达标仍然是「未评」(程序核过的只是可观察条件,§10.2)",
   ar["任务达标"] == "未评", ar.get("任务达标"))

print("\n▸ 工具目录")
c, t = 打("GET", P + "/tools")
ck("工具列表给出读写类型,而且**有一个不可逆写入的**(确认闸要有活用例)",
   c == 200 and any(x["读写类型"] == "不可逆写入" for x in t["items"]),
   [(x["名称"], x["读写类型"]) for x in t.get("items", [])])
c, b = 打("POST", P + "/tools", 体={"名称": "x", "读写类型": "乱写的", "接入方式": "A"})
ck("**注册工具时读写类型认不出 → 422**(没标级别的工具会被网关一律挡住)",
   c == 422 and "认不出" in ((b or {}).get("message") or ""), c)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
