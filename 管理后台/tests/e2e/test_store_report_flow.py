#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经营报告 · 端到端(2026-10-24,六条业务工作流第一条;用户拍「比对指纹,变了就重写」)。

真服务 + 真 Worker + 真库,模型是 mock。澜绣那一侧**测试自己扮演**:回执取数(带指纹)和存报告。
澜绣存报告时会**重新取数**并冻结那一份 —— 正文要是照旧数写的,正文和冻结的取数包就对不上,而且不报错。

  ① 数据没变:取数 → 写 → 店长批准 → 再取(指纹一样)→ 存,存的正文是**店长改过的定稿**
  ② 数据变了:再取指纹不同 → 不存,拿**新数**重写 → 店长再核 → 第三次取一样 → 存第二轮的定稿
  ③ 两轮都在变:第三次又不同 → 不存、说明「数据又变了」,桥上一张存报告的单都没有
  ④ 店长退回:不再取数、不存,输出是退回理由
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
            # 只补模型 —— 处理要求模板已经默认选上了「客户需求提取」(用户 10-24 拍)
            n["config"]["connection_version_id"] = "cv_mock_" + 项目
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



subprocess.run([PY, os.path.join(根, "tools", "seed_bridge_tools.py"), "--项目", 项目],
               capture_output=True, text=True, timeout=120, cwd=根, check=True)


def 建报告图():
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 经营报告 {uuid.uuid4().hex[:6]}", "模板": "经营报告"})
    assert c == 201, (c, w)
    c, d = 打("GET", P + f"/workflows/{w['id']}")
    定义 = d["草稿"]["定义"]
    for n in 定义["nodes"]:
        if n["type"] == "llm":
            n["config"]["connection_version_id"] = "cv_mock_" + 项目
    c, b = 打("PATCH", P + f"/workflows/{w['id']}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    assert c == 200, (c, b)
    return w["id"]


def 回执(rid, 工具, 输出):
    s = [x for x in 单(rid) if x["工具"] == 工具]
    if not s:
        return None, s
    c, b = 打("POST", P + f"/bridge-calls/{s[0]['id']}/ack", "U004", 体={"结果": "已执行", "输出": 输出})
    return c, s[0]


def 取数(指纹, 营收):
    return {"数据": {"种类": "周", "期内": {"营收": 营收}}, "指纹": 指纹, "结果": "已执行「store_report」"}


def 批(rid, 定稿):
    hs = 待办(rid)
    return 决定(hs[0]["id"], "approved", edits={"定稿": 定稿}) if hs else (0, None)


def 存了几张(rid):
    return len([x for x in 单(rid, "待执行") + 单(rid, "已执行") if x["工具"] == "save_report"])


print("▸ ⓪ 模板")
c, t = 打("GET", P + "/workflow-templates")
卡 = [x for x in (t or {}).get("items") or [] if x["名"] == "经营报告"]
ck("模板卡片有「经营报告」,资源齐了 → 能直接跑", bool(卡) and 卡[0]["能直接跑吗"] is True, 卡)
wid = 建报告图()
c, v = 打("POST", P + f"/workflows/{wid}/validate")
ck("补上模型后校验通过", c == 200 and v.get("通过") is True, v)

print("\n▸ ① 数据没变 → 存店长的定稿")
c, r = 发起(wid, {"kind": "周"}); rid = r["resource_id"]
ck("停在取数等澜绣", 等到(rid, ("waiting_external", "failed"))[0] == "waiting_external")
回执(rid, "store_report", 取数("fp-A", 100))
ck("取回来写好正文 → 停在店长核对", 等到(rid, ("waiting_approval", "failed"))[0] == "waiting_approval")
批(rid, "定稿一:营收 100")
ck("批准后先再取一次数(不直接存)", 等到(rid, ("waiting_external", "failed"))[0] == "waiting_external"
   and [x["工具"] for x in 单(rid)] == ["store_report"], [x["工具"] for x in 单(rid)])
回执(rid, "store_report", 取数("fp-A", 100))
ck("指纹一样 → 停在存报告", 等到(rid, ("waiting_external", "failed"))[0] == "waiting_external"
   and [x["工具"] for x in 单(rid)] == ["save_report"], [x["工具"] for x in 单(rid)])
存单 = [x for x in 单(rid) if x["工具"] == "save_report"]
ck("**存的正文是店长改过的定稿**,报告种类照发起时的", 存单 and 存单[0]["参数"].get("body") == "定稿一:营收 100"
   and 存单[0]["参数"].get("kind") == "周", 存单 and 存单[0]["参数"])
回执(rid, "save_report", {"数据": {"ok": True, "id": "RPT-E2E-1"}, "结果": "已执行「save_report」"})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("运行成功", st == "succeeded", (st, (rr or {}).get("停止原因")))

print("\n▸ ② 数据变了 → 拿新数重写、店长再核、再比一次才存")
c, r = 发起(wid, {"kind": "周"}); rid2 = r["resource_id"]
等到(rid2, ("waiting_external",)); 回执(rid2, "store_report", 取数("fp-A", 100))
等到(rid2, ("waiting_approval",)); 批(rid2, "定稿一:营收 100")
等到(rid2, ("waiting_external",)); 回执(rid2, "store_report", 取数("fp-B", 120))
st, _ = 等到(rid2, ("waiting_approval", "waiting_external", "failed"))
ck("**指纹不同 → 不存,重写后再请店长核对**", st == "waiting_approval" and 存了几张(rid2) == 0, (st, 存了几张(rid2)))
批(rid2, "定稿二:营收 120")
等到(rid2, ("waiting_external",)); 回执(rid2, "store_report", 取数("fp-B", 120))
st, _ = 等到(rid2, ("waiting_external", "failed"))
存单 = [x for x in 单(rid2) if x["工具"] == "save_report"]
ck("第三次取和第二次一样 → 存的是**第二轮**的定稿", 存单 and 存单[0]["参数"].get("body") == "定稿二:营收 120",
   存单 and 存单[0]["参数"])
回执(rid2, "save_report", {"数据": {"ok": True, "id": "RPT-E2E-2"}, "结果": "已执行「save_report」"})
ck("运行成功", 等到(rid2, ("succeeded", "failed", "incomplete"))[0] == "succeeded")

print("\n▸ ③ 两轮都在变 → 停下不存")
c, r = 发起(wid, {"kind": "周"}); rid3 = r["resource_id"]
等到(rid3, ("waiting_external",)); 回执(rid3, "store_report", 取数("fp-A", 100))
等到(rid3, ("waiting_approval",)); 批(rid3, "定稿一")
等到(rid3, ("waiting_external",)); 回执(rid3, "store_report", 取数("fp-B", 120))
等到(rid3, ("waiting_approval",)); 批(rid3, "定稿二")
等到(rid3, ("waiting_external",)); 回执(rid3, "store_report", 取数("fp-C", 130))
st, rr = 等到(rid3, ("succeeded", "failed", "incomplete"))
ck("**第三次又变 → 不存**,桥上一张存报告的单都没有,输出说明数据又变了",
   st == "succeeded" and 存了几张(rid3) == 0 and "又变" in json.dumps((rr or {}).get("输出"), ensure_ascii=False),
   (st, 存了几张(rid3), (rr or {}).get("输出")))

print("\n▸ ④ 店长退回")
c, r = 发起(wid, {"kind": "周"}); rid4 = r["resource_id"]
等到(rid4, ("waiting_external",)); 回执(rid4, "store_report", 取数("fp-A", 100))
等到(rid4, ("waiting_approval",))
hs = 待办(rid4); 决定(hs[0]["id"], "rejected", reason="营收口径不对,先别存")
st, rr = 等到(rid4, ("succeeded", "failed", "incomplete"))
ck("退回 → 不再取数、不存,输出是退回理由",
   st == "succeeded" and 存了几张(rid4) == 0 and len([x for x in 单(rid4, "已执行") if x["工具"] == "store_report"]) == 1
   and "口径" in json.dumps((rr or {}).get("输出"), ensure_ascii=False), (st, (rr or {}).get("输出")))

print()
if 挂:
    print(f"❌ 经营报告:{len(挂)} 条不过(验了 {len(过) + len(挂)} 条)")
    sys.exit(1)
print(f"✅ 经营报告:没变就存 / 变了重写再核 / 两轮都变不存 / 退回不存(验了 {len(过)} 条)")
