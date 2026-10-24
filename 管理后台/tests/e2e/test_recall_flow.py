#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""老客召回 · 端到端(2026-10-25,六条第五条;交叉规则复用澜绣「客户召回」技能第二步)。

真服务 + 真 Worker + 真库,模型是 mock。澜绣那一侧测试自己扮演(名单由澜绣桥逐人交叉,这里回执给定的名单)。

  ① 名单 0 人 → 不写话术、不让店长勾、不派
  ② 有名单 → 写话术 → 停在店长勾选(左边是人能读的名单)→ 勾了人、填了截止 → 派回访任务,
     参数是店长勾的客户号 + 截止 + **召回名单那一步的原名单**(澜绣那边只认名单里的人)+ 模型逐人的话术
  ③ 店长通过但没勾人 → 名单归档、不派
  ④ 勾了人没填截止 → 不派
  ⑤ 店长退回 → 不派,输出是理由
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


def 建召回图():
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 老客召回 {uuid.uuid4().hex[:6]}", "模板": "老客召回"})
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


人们 = [{"客户号": "C90001", "客户": "甲", "由头": "BIRTHDAY", "为什么是现在": "19 天后生日",
         "同时在流失预警里": True, "流失严重程度": "高", "归属顾问工号": "60000002", "归属顾问": "林岚",
         "归属顾问在职": True, "已有未完成回访任务": []},
        {"客户号": "C90002", "客户": "乙", "由头": "RHYTHM_BREAK", "为什么是现在": "平均 60 天来一次,这次 180 天",
         "同时在流失预警里": False, "流失严重程度": None, "归属顾问工号": "60000003", "归属顾问": "周叙",
         "归属顾问在职": True, "已有未完成回访任务": []}]


def 名单(n=2):
    们 = 人们[:n]
    return {"数据": {"看的范围": "SH001 静安旗舰店(你的门店)", "列出": len(们), "名单": 们,
                     "名单文字": "\n".join(f"{p['客户号']} {p['客户']} · 由头 {p['由头']}" for p in 们),
                     "在流失、等由头": []},
            "指纹": "fp-1", "结果": f"该联系 {len(们)} 个,列出 {len(们)} 个"}


def 派了几张(rid):
    return len([x for s in ("待执行", "已执行") for x in 单(rid, s) if x["工具"] == "派回访任务"])


def 走到勾选(wid_, n=2):
    c, r = 发起(wid_, {}); rid_ = r["resource_id"]
    等到(rid_, ("waiting_external",)); 回执(rid_, "召回名单", 名单(n))
    return rid_


def 出(rr):
    return json.dumps((rr or {}).get("输出"), ensure_ascii=False)


print("▸ ⓪ 模板")
c, t = 打("GET", P + "/workflow-templates")
卡 = [x for x in (t or {}).get("items") or [] if x["名"] == "老客召回"]
ck("模板卡片有「老客召回」,资源齐了 → 能直接跑", bool(卡) and 卡[0]["能直接跑吗"] is True, 卡)
wid = 建召回图()
c, v = 打("POST", P + f"/workflows/{wid}/validate")
ck("补上模型后校验通过", c == 200 and v.get("通过") is True, v)
print("\n▸ ① 名单 0 人 → 不派")
rid = 走到勾选(wid, 0)
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_approval"))
ck("**0 人 → 直接结束,不写话术、不让店长勾、不派**,说清不硬凑", st == "succeeded" and not 待办(rid)
   and 派了几张(rid) == 0 and "不硬凑" in 出(rr), (st, 出(rr)))

print("\n▸ ② 有名单 → 店长勾了人、填了截止 → 派回访任务")
rid = 走到勾选(wid)
ck("写完话术后停在店长勾选", 等到(rid, ("waiting_approval", "failed"))[0] == "waiting_approval")
c, det = 打("GET", P + f"/human-requests/{待办(rid)[0]['id']}", "U006")
材 = det.get("核对材料") or {}
ck("店长看到的左边是**人能读的名单**(客户号、由头)", "C90001" in str(材.get("原文")) and "BIRTHDAY" in str(材.get("原文")), 材)
ck("店长能填的只有「要派的客户号 / 回访截止」", sorted(det.get("允许编辑的字段") or []) == ["回访截止", "要派的客户号"],
   det.get("允许编辑的字段"))
决定(待办(rid)[0]["id"], "approved", edits={"要派的客户号": "C90001", "回访截止": "2026-12-31 18:00"})
等到(rid, ("waiting_external", "failed"))
派 = [x for x in 单(rid) if x["工具"] == "派回访任务"]
参 = (派[0]["参数"] if 派 else {}) or {}
ck("**派的参数:店长勾的客户号 + 截止 + 召回那一步的原名单**(澜绣只认名单里的人)",
   参.get("客户号们") == "C90001" and 参.get("截止") == "2026-12-31 18:00" and 参.get("名单") == 人们, 参)
ck("模型逐人写的话术一起带过去(派任务时写进任务描述)", isinstance(参.get("话术"), list), 参.get("话术"))
回执(rid, "派回访任务", {"数据": {"派了": ["C90001:派给 林岚"], "跳过": []}, "结果": "派了 1 条回访"})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("运行成功,输出就是澜绣回的「派了几条、跳过谁」", st == "succeeded" and "派了 1 条回访" in 出(rr), (st, 出(rr)))

print("\n▸ ③ 通过但没勾人 → 只出名单不派")
rid = 走到勾选(wid)
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "approved", edits={})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_external"))
ck("没勾要派的人 → 不派,说名单归档", st == "succeeded" and 派了几张(rid) == 0 and "没勾" in 出(rr), (st, 出(rr)))

print("\n▸ ④ 勾了人没填截止 → 不派")
rid = 走到勾选(wid)
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "approved", edits={"要派的客户号": "C90001,C90002"})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_external"))
ck("没填回访截止 → 不派,说明为什么", st == "succeeded" and 派了几张(rid) == 0 and "没填回访截止" in 出(rr), (st, 出(rr)))

print("\n▸ ⑤ 店长退回")
rid = 走到勾选(wid)
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "rejected", reason="这批上周刚打过,先不打")
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("退回 → 不派,输出是理由", st == "succeeded" and 派了几张(rid) == 0 and "上周刚打过" in 出(rr), (st, 出(rr)))

print()
if 挂:
    print(f"❌ 老客召回:{len(挂)} 条不过(验了 {len(过) + len(挂)} 条)")
    sys.exit(1)
print(f"✅ 老客召回:0 人不派 / 勾了人填了截止才派、带原名单 / 没勾不派 / 没截止不派 / 退回不派(验了 {len(过)} 条)")
