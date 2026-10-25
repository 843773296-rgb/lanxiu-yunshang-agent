#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""差评返修 · 端到端(2026-10-25,六条第四条;判责复用现成的返修判定表;用户拍「超店长权限的停下报总部,不写」)。

真服务 + 真 Worker + 真库,模型是 mock;澜绣那一侧测试自己扮演(超权限不写的判定在澜绣那边,桥检查验它)。
  ① 已经处理过的差评 → 不研判、不让店长判、不办
  ② 店长选了处置 → 处置那一步拿到的是**店长定的整包**(选填没填的也不让运行失败)→ 输出是澜绣回的
  ③ 澜绣回「超过店长权限,要报总部」→ 运行照样成功,输出写明没建单(不是出错)
  ④ 店长通过但没选处置 → 只出研判不办   ⑤ 退回 → 不办
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



subprocess.run([PY, os.path.join(根, "tools", "seed_bridge_tools.py"), "--项目", 项目],
               capture_output=True, text=True, timeout=120, cwd=根, check=True)

def 建图(模板):
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e {模板} {uuid.uuid4().hex[:6]}", "模板": 模板})
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
    if s:
        打("POST", P + f"/bridge-calls/{s[0]['id']}/ack", "U004", 体={"结果": "已执行", "输出": 输出})
    return s[0] if s else None


def 几张(rid, 工具):
    return len([x for s in ("待执行", "已执行") for x in 单(rid, s) if x["工具"] == 工具])


def 出(rr):
    return json.dumps((rr or {}).get("输出"), ensure_ascii=False)


def 模板卡(名):
    c, t = 打("GET", P + "/workflow-templates")
    卡 = [x for x in (t or {}).get("items") or [] if x["名"] == 名]
    ck(f"模板卡片有「{名}」,资源齐了 → 能直接跑", bool(卡) and 卡[0]["能直接跑吗"] is True, 卡)
    wid = 建图(名)
    c, v = 打("POST", P + f"/workflows/{wid}/validate")
    ck("补上模型后校验通过", c == 200 and v.get("通过") is True, v)
    return wid

包 = "P0-E2E-RATING-1"


def 研判(已处理=False):
    return {"数据": {"差评": {"包裹": 包, "星": 1, "顾客说": "领口开线了"}, "已处理": 已处理,
                     "判责建议": {"归类": "工艺瑕疵", "责任": "我方", "判得出": True}, "说明": "判定表能判"},
            "指纹": "fp-1", "结果": f"差评 {包}(1 星):判定表能判"}


def 走到判定(wid_, 已处理=False):
    c, r = 发起(wid_, {"pkg": 包}); rid_ = r["resource_id"]
    等到(rid_, ("waiting_external",)); 回执(rid_, "差评研判", 研判(已处理))
    return rid_


print("▸ ⓪ 模板")
wid = 模板卡("差评返修")

print("\n▸ ① 已处理过 → 不办")
rid = 走到判定(wid, True)
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_approval"))
ck("**已经不是待处理 → 直接结束,不研判、不让店长判、不办**", st == "succeeded" and not 待办(rid)
   and 几张(rid, "差评处置") == 0 and "没再办" in 出(rr), (st, 出(rr)))

print("\n▸ ② 店长选了返修 → 处置拿到店长定的整包")
rid = 走到判定(wid)
ck("写完四段后停在店长判定", 等到(rid, ("waiting_approval", "failed"))[0] == "waiting_approval")
c, det = 打("GET", P + f"/human-requests/{待办(rid)[0]['id']}", "U006")
ck("店长能填处置 / 责任方 / 预估费用 / 关闭方式 / 说明 / 顾客同意凭据",
   sorted(det.get("允许编辑的字段") or []) == sorted(["处置", "责任方", "预估费用", "关闭方式", "说明", "顾客同意凭据"]),
   det.get("允许编辑的字段"))
决定(待办(rid)[0]["id"], "approved", edits={"处置": "返修", "责任方": "企业", "预估费用": "300"})
等到(rid, ("waiting_external", "failed"))
办 = [x for x in 单(rid) if x["工具"] == "差评处置"]
参 = (办[0]["参数"] if 办 else {}) or {}
定 = 参.get("店长定的") or {}
ck("**处置的参数:这条差评 + 店长定的整包**(只填了三样也不失败)",
   参.get("pkg") == 包 and 定.get("处置") == "返修" and 定.get("责任方") == "企业" and 定.get("预估费用") == "300"
   and "关闭方式" not in 定, 参)
回执(rid, "差评处置", {"数据": {"返修单": "MW9"}, "结果": "建了返修单 MW9,判给企业"})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("运行成功,输出是澜绣回的", st == "succeeded" and "MW9" in 出(rr), (st, 出(rr)))

print("\n▸ ③ 超过店长权限 → 停下报总部,运行照样成功")
rid = 走到判定(wid)
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "approved", edits={"处置": "返修", "责任方": "企业", "预估费用": "2000"})
等到(rid, ("waiting_external",))
回执(rid, "差评处置", {"数据": {"写了": False, "停在": "OVER_AUTHORITY"},
                      "结果": "我方出 ¥2000,超过店长权限 —— 流程到这里停下,没建返修单、没关差评;请报总部在澜绣里办"})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("**超权限 → 运行成功(不是出错),输出写明没建单、要报总部**", st == "succeeded" and "报总部" in 出(rr)
   and "没建返修单" in 出(rr), (st, 出(rr)))

print("\n▸ ④ 通过但没选处置 → 只出研判")
rid = 走到判定(wid)
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "approved", edits={})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_external"))
ck("没选处置 → 不办,说研判归档", st == "succeeded" and 几张(rid, "差评处置") == 0 and "没选处置" in 出(rr), (st, 出(rr)))

print("\n▸ ⑤ 退回")
rid = 走到判定(wid)
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "rejected", reason="顾客已经在门店当面处理了")
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("退回 → 不办,输出是理由", st == "succeeded" and 几张(rid, "差评处置") == 0 and "当面处理" in 出(rr), (st, 出(rr)))

print()
if 挂:
    print(f"❌ 差评返修:{len(挂)} 条不过(验了 {len(过) + len(挂)} 条)")
    sys.exit(1)
print(f"✅ 差评返修:已处理不办 / 店长定的整包传给处置 / 超权限停下报总部不算出错 / 没选不办 / 退回不办(验了 {len(过)} 条)")
