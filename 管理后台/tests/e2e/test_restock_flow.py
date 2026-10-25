#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库存补货 · 端到端(2026-10-25,六条第六条;档和防重复派用澜绣现成的库存预警 / 预警派单)。

真服务 + 真 Worker + 真库,模型是 mock;澜绣那一侧测试自己扮演。
  ① 不用派(压货 / 够 / 已有人在跟)→ 不写建议、不让人确认、不派
  ② 要派 → 写建议 → 停在确认 → 填了负责人和截止 → 派补货跟进,参数是这个 SKU + 填的人和截止 + 模型的建议
  ③ 没填负责人 → 不派   ④ 退回 → 不派
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

SKU = "lxys_e2e-01"


def 预警(要派, 说明="可以派补货跟进"):
    return {"数据": {"SKU": SKU, "档": "快没了" if 要派 else "卖不动", "要派吗": 要派, "说明": 说明},
            "指纹": "fp-1", "结果": f"{SKU}:{'快没了' if 要派 else '卖不动'} —— {说明}"}


def 走到确认(wid_, 要派=True, 说明="可以派补货跟进"):
    c, r = 发起(wid_, {"sku": SKU}); rid_ = r["resource_id"]
    等到(rid_, ("waiting_external",)); 回执(rid_, "补货预警", 预警(要派, 说明))
    return rid_


print("▸ ⓪ 模板")
wid = 模板卡("库存补货")

print("\n▸ ① 不用派 → 直接结束")
rid = 走到确认(wid, False, "压货:只出处理建议(调拨 / 活动),不派补货")
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_approval"))
ck("**压货 → 直接结束,不写建议、不让人确认、不派**,输出说为什么", st == "succeeded" and not 待办(rid)
   and 几张(rid, "派补货跟进") == 0 and "压货" in 出(rr), (st, 出(rr)))

print("\n▸ ② 要派 → 填了负责人和截止 → 派补货跟进")
rid = 走到确认(wid)
ck("写完建议后停在确认", 等到(rid, ("waiting_approval", "failed"))[0] == "waiting_approval")
c, det = 打("GET", P + f"/human-requests/{待办(rid)[0]['id']}", "U006")
ck("能填的只有「补货负责人 / 补货截止」", sorted(det.get("允许编辑的字段") or []) == ["补货截止", "补货负责人"],
   det.get("允许编辑的字段"))
决定(待办(rid)[0]["id"], "approved", edits={"补货负责人": "60000001", "补货截止": "2026-12-31 18:00"})
等到(rid, ("waiting_external", "failed"))
派 = [x for x in 单(rid) if x["工具"] == "派补货跟进"]
参 = (派[0]["参数"] if 派 else {}) or {}
ck("**派的参数:这个 SKU + 填的负责人和截止 + 模型的建议**",
   参.get("sku") == SKU and 参.get("负责人") == "60000001" and 参.get("截止") == "2026-12-31 18:00"
   and isinstance(参.get("note"), str), 参)
回执(rid, "派补货跟进", {"数据": {"ok": True}, "结果": "已派补货跟进:SC9"})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("运行成功,输出是澜绣回的", st == "succeeded" and "已派补货跟进" in 出(rr), (st, 出(rr)))

print("\n▸ ③ 没填负责人 → 不派")
rid = 走到确认(wid)
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "approved", edits={"补货截止": "2026-12-31 18:00"})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_external"))
ck("没填补货负责人 → 不派", st == "succeeded" and 几张(rid, "派补货跟进") == 0 and "没填补货负责人" in 出(rr), (st, 出(rr)))

print("\n▸ ④ 退回")
rid = 走到确认(wid)
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "rejected", reason="这个款下个月就下架,不补")
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("退回 → 不派,输出是理由", st == "succeeded" and 几张(rid, "派补货跟进") == 0 and "下架" in 出(rr), (st, 出(rr)))

print()
if 挂:
    print(f"❌ 库存补货:{len(挂)} 条不过(验了 {len(过) + len(挂)} 条)")
    sys.exit(1)
print(f"✅ 库存补货:不用派直接结束 / 填齐了才派、带 SKU 和建议 / 没填不派 / 退回不派(验了 {len(过)} 条)")
