#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频整理全流程 · 端到端(2026-10-24,用户拍「页面结构加上音频整理全流程全部做完」+「核对即定稿,直接写跟进」)。

真服务 + 真 Worker + 真库,模型是 mock(不花钱;mock 也按结果字段出形状,值里带 [mock])。
澜绣那一侧用**测试自己扮演**:拉待执行的桥请求、回执 —— 真的 supervise_sync 那半有自己的检查。

  ① 建「音频整理」模板 → 补模型和处理要求 → 校验通过
  ② 试运行 → 停在「取转写」等澜绣回执(waiting_external),桥上有一张待执行的单
  ③ 回执转写 → 运行接着走,停在「人工核对」(waiting_approval),待办里看得到摘要和原文
  ④ 批准(改了定稿)→ 停在「写跟进」等回执,单上的内容是**人改过的定稿**
  ⑤ 回执写好了 → 运行成功,输出是写跟进的结果;前面的步骤没重跑(取转写那张单仍只有一张)
  ⑥ 另一条:退回 → 写跟进一张单都没有,输出是退回理由
  ⑦ 一张把写跟进直接接在模型后面的图(没经过核对)→ 运行失败 WRITE_NEEDS_REVIEW,桥上不出写跟进的单
  ⑧ 重复回执同一张单 → 409,不排第二次恢复
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
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if 补 and not 真 else ''}")
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
    subprocess.run([PY, os.path.join(根, "workers", "worker.py"), "--一轮"],
                   capture_output=True, text=True, timeout=180, cwd=根)


def 等到(rid, 想要, 最多=8):
    """跑 worker 直到运行进入 想要 里的某个状态(**不用 sleep 猜**)。"""
    for _ in range(最多):
        c, r = 打("GET", P + f"/execution-runs/{rid}", "U004")
        st = (r or {}).get("执行状态")
        if st in 想要:
            return st, r
        跑worker()
    c, r = 打("GET", P + f"/execution-runs/{rid}", "U004")
    return (r or {}).get("执行状态"), r


def 单(rid, 状态="待执行"):
    from urllib.parse import quote
    c, b = 打("GET", P + f"/bridge-calls?{quote('状态')}={quote(状态)}&execution_run_id={rid}", "U004")
    return (b or {}).get("items") or []


def 建图(名, 改=None):
    c, w = 打("POST", P + "/workflows", 体={"名称": f"{名} {uuid.uuid4().hex[:6]}", "模板": "音频整理"})
    assert c == 201, (c, w)
    c, d = 打("GET", P + f"/workflows/{w['id']}")
    定义 = d["草稿"]["定义"]
    for n in 定义["nodes"]:
        if n["type"] == "llm":
            n["config"]["connection_version_id"] = "cv_mock_" + 项目
            n["config"]["prompt_version_id"] = "pv_seed_article_summary"
    if 改:
        改(定义)
    c, b = 打("PATCH", P + f"/workflows/{w['id']}/draft", 体={"定义": 定义},
             头={"If-Match": str(d["草稿"]["revision"])})
    assert c == 200, (c, b)
    return w["id"], 定义


def 发起(wid, 输入):
    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())},
             体={"workflow_id": wid, "输入": 输入})
    return c, r


def 待办(rid):
    c, b = 打("GET", P + "/human-requests?status=pending&limit=200", "U006")
    return [x for x in (b or {}).get("items") or [] if x.get("execution_run_id") == rid]


def 决定(hid, decision, **kw):
    c, d = 打("GET", P + f"/human-requests/{hid}", "U006")
    rev = d["请求"]["revision"]
    return 打("POST", P + f"/human-requests/{hid}/decisions", "U006",
             体={"decision": decision, "request_revision": rev, **kw},
             头={"Idempotency-Key": str(uuid.uuid4())})


print("▸ ① 建模板 → 补模型 → 校验")
wid, 定义 = 建图("e2e 音频整理")
ck("模板预填了取转写 / 写跟进两个澜绣桥工具(项目里登记过的那两个)",
   all(n["config"].get("tool_version_id") for n in 定义["nodes"] if n["type"] == "tool"),
   [n["config"].get("tool_version_id") for n in 定义["nodes"] if n["type"] == "tool"])
c, b = 打("POST", P + f"/workflows/{wid}/validate")
ck("补上模型和处理要求后校验通过", c == 200 and b.get("通过"), b)

print("\n▸ ② 试运行 → 停在取转写等回执")
c, r = 发起(wid, {"call_id": "TS-001", "customer_id": "C10001"})
ck("受理 202", c == 202, (c, r))
rid = r["resource_id"]
st, _ = 等到(rid, ("waiting_external", "failed", "succeeded"))
ck("停在 waiting_external(等澜绣回执)", st == "waiting_external", st)
s1 = 单(rid)
ck("桥上有一张「取转写」待执行单,参数是通话号", len(s1) == 1 and s1[0]["工具"] == "取转写"
   and s1[0]["参数"] == {"call_id": "TS-001"}, s1)

print("\n▸ ③ 回执转写 → 停在人工核对")
原文 = ("顾问:您好。顾客:我想做一套宋制褙子,秋天穿,预算三千左右,十一月中要。"
        "我电话 13800138000,面料想看看真丝和棉麻,颜色偏素一点,领口要交领,袖子别太宽,"
        "腰身收一点显瘦,下摆到脚踝,配一条百迭裙,里衬要透气,夏末也能穿。")   # 超过 160 字,带手机号
c, b = 打("POST", P + f"/bridge-calls/{s1[0]['id']}/ack", "U004",
         体={"结果": "已执行", "输出": {"text": 原文, "call_id": "TS-001", "customer_id": "C10001"}})
ck("回执成功,而且排上了恢复任务", c == 200 and b.get("恢复任务"), (c, b))
st, _ = 等到(rid, ("waiting_approval", "failed", "succeeded"))
ck("停在 waiting_approval(等人工核对)", st == "waiting_approval", st)
hs = 待办(rid)
ck("待办里有一条这次运行的核对", len(hs) == 1, hs)
c, d = 打("GET", P + f"/human-requests/{hs[0]['id']}", "U006") if hs else (0, {})
参 = (d or {}).get("核对材料") or {}
ck("待办详情看得到摘要、待确认项和原文(原文是回执带回来的那份)",
   {"摘要", "待确认项", "原文"} <= set(参) and "宋制褙子" in str(参.get("原文")), 参)
ck("**原文是全文**(核对就是对着原文看;不是「N 字 · 开头……」的形状),手机号打了码",
   参.get("原文") == 原文.replace("13800138000", "138****8000"), 参.get("原文"))
ck("允许编辑的字段只有「定稿」", (d or {}).get("允许编辑的字段") == ["定稿"], (d or {}).get("允许编辑的字段"))

print("\n▸ ④ 批准(改了定稿)→ 停在写跟进")
定稿 = "顾客要宋制褙子,秋款,预算约 3000,11 月中交;面料待确认。"
c, b = 决定(hs[0]["id"], "approved", edits={"定稿": 定稿})
ck("批准记下,并排上了恢复", c == 201 and (b.get("运行") or {}).get("恢复任务"), (c, b))
st, _ = 等到(rid, ("waiting_external", "failed", "succeeded"))
ck("停在 waiting_external(等写跟进回执)", st == "waiting_external", st)
s2 = 单(rid)
ck("桥上出了一张「写跟进」单,内容是**人改过的定稿**,客户号对",
   len(s2) == 1 and s2[0]["工具"] == "写跟进" and s2[0]["参数"].get("内容") == 定稿
   and s2[0]["参数"].get("customer_id") == "C10001", s2)

print("\n▸ ⑤ 回执写好了 → 成功")
c, b = 打("POST", P + f"/bridge-calls/{s2[0]['id']}/ack", "U004",
         体={"结果": "已执行", "输出": {"跟进号": "FU-E2E-1", "customer_id": "C10001",
                                       "是新写的": True, "结果": "已写跟进 FU-E2E-1"}})
st, r5 = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("运行成功", st == "succeeded", (st, r5))
c, r = 打("GET", P + f"/execution-runs/{rid}", "U004")
ck("输出是写跟进的结果", "FU-E2E-1" in json.dumps(r, ensure_ascii=False), str(r)[:300])
ck("**取转写只有一张单**(恢复时前面的步骤没重跑)",
   [x["工具"] for x in 单(rid, "已执行")].count("取转写") == 1, 单(rid, "已执行"))
c, b = 打("POST", P + f"/bridge-calls/{s2[0]['id']}/ack", "U004",
         体={"结果": "已执行", "输出": {"跟进号": "FU-E2E-2", "结果": "x"}})
ck("⑧ 同一张单再回执一次 → 409(不排第二次恢复)", c == 409, (c, b))

print("\n▸ ⑥ 退回那一路")
c, r = 发起(wid, {"call_id": "TS-002", "customer_id": "C10002"})
rid2 = r["resource_id"]
等到(rid2, ("waiting_external",))
打("POST", P + f"/bridge-calls/{单(rid2)[0]['id']}/ack", "U004",
  体={"结果": "已执行", "输出": {"text": "顾客问价,没说要什么。", "call_id": "TS-002"}})
等到(rid2, ("waiting_approval",))
c, b = 决定(待办(rid2)[0]["id"], "rejected", reason="录音里没有需求,不写跟进")
st, _ = 等到(rid2, ("succeeded", "failed", "incomplete"))
ck("退回之后跑完了(退回是一种结果,不是故障)", st == "succeeded", st)
ck("**写跟进一张单都没有**", not [x for s in ("待执行", "已执行", "执行失败") for x in 单(rid2, s)
                              if x["工具"] == "写跟进"])
c, r = 打("GET", P + f"/execution-runs/{rid2}", "U004")
ck("输出是退回理由", "录音里没有需求" in json.dumps(r, ensure_ascii=False))

print("\n▸ ⑦ 没经过核对就写跟进 → 拒")
def 绕过核对(d):
    d["nodes"] = [n for n in d["nodes"] if n["id"] not in ("review", "decide", "rejected", "merge")]
    for n in d["nodes"]:
        if n["id"] == "save":
            n["config"]["bindings"]["内容"] = {"source": "node", "node_id": "extract", "pointer": "/跟进草稿"}
        if n["id"] == "finish":
            n["config"]["bindings"] = {"结果": {"source": "node", "node_id": "save", "pointer": "/结果"}}
    d["edges"] = [{"source": a, "target": b, "port": "success"} for a, b in
                  (("start", "fetch"), ("fetch", "extract"), ("extract", "save"), ("save", "finish"))]
wid3, _ = 建图("e2e 绕过核对", 绕过核对)
c, b = 打("POST", P + f"/workflows/{wid3}/validate")
ck("(这张图校验是能过的 —— 所以拦截必须落在执行那一侧)", c == 200 and b.get("通过"), b)
c, r = 发起(wid3, {"call_id": "TS-003", "customer_id": "C10003"})
rid3 = r["resource_id"]
等到(rid3, ("waiting_external",))
打("POST", P + f"/bridge-calls/{单(rid3)[0]['id']}/ack", "U004",
  体={"结果": "已执行", "输出": {"text": "随便一段", "call_id": "TS-003"}})
st, r = 等到(rid3, ("failed", "succeeded", "waiting_external"))
c, r = 打("GET", P + f"/execution-runs/{rid3}", "U004")
ck("运行失败,原因 WRITE_NEEDS_REVIEW", st == "failed" and "WRITE_NEEDS_REVIEW" in json.dumps(r, ensure_ascii=False),
   (st, str(r)[:300]))
ck("**桥上没有写跟进的单**", not [x for s in ("待执行", "已执行") for x in 单(rid3, s) if x["工具"] == "写跟进"])

print()
if 挂:
    print(f"❌ {len(挂)} 条不过(验了 {len(过) + len(挂)} 条):{挂}")
    sys.exit(1)
print(f"✅ 音频整理全流程:取转写 → 提取 → 人工核对 → 写跟进,挂起 / 恢复 / 退回 / 绕过核对都对(验了 {len(过)} 条)")
