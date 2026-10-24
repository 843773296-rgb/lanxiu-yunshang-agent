#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订单风险 · 端到端(2026-10-25,六条第三条;用户拍「全用规则分档,模型只写建议」)。

真服务 + 真 Worker + 真库,模型是 mock。澜绣那一侧测试自己扮演(档由澜绣的规则判,这里回执给定的档)。

  ① 不用跟踪的档(暂无已识别风险)→ 不建议、不核对、不派
  ② 要跟踪 → 店长填了负责人和截止 → 派之前再取一次(没变)→ 派「订单跟踪」,参数是店长填的和这一单
  ③ 要跟踪 → 店长核对期间这一单变了(指纹不同)→ 不派,说明请重新发起
  ④ 店长没填负责人 → 不派
  ⑤ 店长退回(误报)→ 不再取、不派,输出是理由
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
订单 = "6488012800009990001"


def 建风险图():
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 订单风险 {uuid.uuid4().hex[:6]}", "模板": "订单风险"})
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


def 风险(档, 指纹="fp-1"):
    return {"数据": {"订单号": 订单, "风险": {"档": 档, "依据": ["e2e"], "缺": []},
                     "要跟踪吗": 档 in ("已延期", "需关注")}, "指纹": 指纹, "结果": f"{订单}:{档}"}


def 派了几张(rid):
    return len([x for s in ("待执行", "已执行") for x in 单(rid, s) if x["工具"] == "assign_task"])


def 走到核对(wid_, 档="已延期"):
    c, r = 发起(wid_, {"order_id": 订单}); rid_ = r["resource_id"]
    等到(rid_, ("waiting_external",)); 回执(rid_, "订单交付风险", 风险(档))
    return rid_


print("▸ ⓪ 模板")
c, t = 打("GET", P + "/workflow-templates")
卡 = [x for x in (t or {}).get("items") or [] if x["名"] == "订单风险"]
ck("模板卡片有「订单风险」,资源齐了 → 能直接跑", bool(卡) and 卡[0]["能直接跑吗"] is True, 卡)
wid = 建风险图()
c, v = 打("POST", P + f"/workflows/{wid}/validate")
ck("补上模型后校验通过", c == 200 and v.get("通过") is True, v)

print("\n▸ ① 不用跟踪的档 → 不派")
rid = 走到核对(wid, "暂无已识别风险")
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_approval"))
ck("**暂无已识别风险 → 直接结束,不核对、不派**", st == "succeeded" and not 待办(rid) and 派了几张(rid) == 0
   and "不派跟踪" in json.dumps((rr or {}).get("输出"), ensure_ascii=False), (st, (rr or {}).get("输出")))

print("\n▸ ② 要跟踪 + 填了负责人和截止 + 没变 → 派订单跟踪")
rid = 走到核对(wid, "已延期")
ck("要跟踪的档 → 写建议后停在店长决定", 等到(rid, ("waiting_approval", "failed"))[0] == "waiting_approval")
c, det = 打("GET", P + f"/human-requests/{待办(rid)[0]['id']}", "U006")
ck("店长看到的核对材料里有规则判的风险档", ((det.get("核对材料") or {}).get("风险") or {}).get("档") == "已延期",
   det.get("核对材料"))
决定(待办(rid)[0]["id"], "approved", edits={"定稿": "去问工厂哪天能发", "跟踪负责人": "60000003",
                                         "跟踪截止": "2026-12-31 18:00"})
等到(rid, ("waiting_external",))
ck("店长确认后**先再取一次**(不直接派)", [x["工具"] for x in 单(rid)] == ["订单交付风险"], [x["工具"] for x in 单(rid)])
回执(rid, "订单交付风险", 风险("已延期"))
等到(rid, ("waiting_external", "failed"))
派 = [x for x in 单(rid) if x["工具"] == "assign_task"]
ck("**派的是「订单跟踪」,挂这一单,负责人 / 截止 / 内容都是店长填的**",
   派 and 派[0]["参数"] == {"type": "订单跟踪", "ref_id": 订单, "assignee": "60000003",
                            "end": "2026-12-31 18:00", "note": "去问工厂哪天能发"}, 派 and 派[0]["参数"])
回执(rid, "assign_task", {"数据": {"ok": True}, "结果": "已派"})
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("运行成功,输出说派了", st == "succeeded" and "已派订单跟踪" in json.dumps((rr or {}).get("输出"), ensure_ascii=False),
   (st, (rr or {}).get("输出")))

print("\n▸ ③ 核对期间这一单变了 → 不派")
rid = 走到核对(wid, "需关注")
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "approved", edits={"跟踪负责人": "60000003", "跟踪截止": "2026-12-31 18:00"})
等到(rid, ("waiting_external",)); 回执(rid, "订单交付风险", 风险("已延期", "fp-2"))
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_external"))
ck("**指纹不同 → 不派**,说明请重新发起", st == "succeeded" and 派了几张(rid) == 0
   and "重新发起" in json.dumps((rr or {}).get("输出"), ensure_ascii=False), (st, (rr or {}).get("输出")))

print("\n▸ ④ 没填负责人 → 不派")
rid = 走到核对(wid, "已延期")
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "approved", edits={"跟踪截止": "2026-12-31 18:00"})
等到(rid, ("waiting_external",)); 回执(rid, "订单交付风险", 风险("已延期"))
st, rr = 等到(rid, ("succeeded", "failed", "incomplete", "waiting_external"))
ck("没填跟踪负责人 → 不派,说明为什么", st == "succeeded" and 派了几张(rid) == 0
   and "没填跟踪负责人" in json.dumps((rr or {}).get("输出"), ensure_ascii=False), (st, (rr or {}).get("输出")))

print("\n▸ ⑤ 店长退回(误报)")
rid = 走到核对(wid, "需关注")
等到(rid, ("waiting_approval",))
决定(待办(rid)[0]["id"], "rejected", reason="工厂昨天已经回过日期,误报")
st, rr = 等到(rid, ("succeeded", "failed", "incomplete"))
ck("退回 → 不再取、不派,输出是理由", st == "succeeded" and 派了几张(rid) == 0
   and len([x for x in 单(rid, "已执行") if x["工具"] == "订单交付风险"]) == 1
   and "误报" in json.dumps((rr or {}).get("输出"), ensure_ascii=False), (st, (rr or {}).get("输出")))

print()
if 挂:
    print(f"❌ 订单风险:{len(挂)} 条不过(验了 {len(过) + len(挂)} 条)")
    sys.exit(1)
print(f"✅ 订单风险:不用跟踪不派 / 填齐了再核一次才派 / 变了不派 / 没填不派 / 退回不派(验了 {len(过)} 条)")
