#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""员工定时 agent 任务 · 端到端(11-22,台账第九十条)。真服务(8801 + worker)+ 真库;聊天站那一侧:提醒类不经过它,「跑」类用一个不在职的工号,
聊天站会回 403 NO_STAFF —— 真走一遍 /internal/chat 的 任务id 分支,**不调模型、不花钱**。
  ① 模板:三个,频率说法对
  ② 建(提醒 / 每天):201 启用、频率说明、接下来三次;列表按 staff_code 只见自己的
  ③ 改:不带 If-Match 409;别人的工号 404;停用后接下来几次为空;再启用
  ④ 立即跑一次(提醒):202 → 再点 409 BUSY → worker 一分钟内执行成 提醒 → 收件箱未读 1、正文「到点了」→ 标已读 → 未读 0
  ⑤ 到点调度:建一条「每天 <下一分钟>」的任务 → 约两分钟内 worker 排一条 定时 运行并执行成 提醒;同一期只一条
  ⑥ 「跑」类 + 不在职工号:run-now → worker 调聊天站 → 403 NO_STAFF → 运行 失败 + 任务自动停用、note 说清、收件箱多一条系统说明
  ⑦ 归档:列表没了、run-now 404
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:260]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U001", 体=None, 头=None):
    req = urllib.request.Request(基址 + 路, method=方法, data=json.dumps(体).encode() if 体 is not None else None)
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


def 等(判, 最多秒, 步=5):
    截 = time.time() + 最多秒
    while time.time() < 截:
        v = 判()
        if v:
            return v
        time.sleep(步)
    return None


def 跑们(tid):
    return (打("GET", P + f"/chat-tasks/{tid}/runs")[1] or {}).get("items") or []


工 = f"E2ECT{uuid.uuid4().hex[:6].upper()}"   # 任务归这个工号;不需要是成员(任务表记的是澜绣工号)
建的 = []

print("▸ ① 模板")
c, m = 打("GET", P + "/chat-task-templates")
名们 = {x["名"]: x for x in (m or {}).get("items") or []}
ck("三个模板,库存盘点是每周一 09:00", c == 200 and set(名们) == {"商机探索", "库存盘点", "客户回访提醒"} and 名们["库存盘点"]["频率说明"] == "每周一 09:00", (c, {k: v.get("频率说明") for k, v in 名们.items()}))

print("\n▸ ② 建")
c, t1 = 打("POST", P + "/chat-tasks", 体={"staff_code": 工, "title": "e2e 提醒", "instruction": "提醒我看一眼商机", "task_mode": "提醒",
                                        "规则": {"周期": "日", "时刻": "09:00"}})
tid = (t1 or {}).get("id"); 建的.append(tid)
ck("建 → 201 启用,频率说明「每天 09:00」,接下来三次", c == 201 and tid and t1["status"] == "启用" and t1["频率说明"] == "每天 09:00" and len(t1["接下来几次"]) == 3
   and t1["revision"] == 1 and t1["staff_code"] == 工, (c, t1))
c, r = 打("POST", P + "/chat-tasks", 体={"staff_code": 工, "title": "x", "instruction": "y", "task_mode": "跑", "规则": {"周期": "周", "时刻": "25:00"}})
ck("规则不合法 → 422 SCHEDULE_RULE_INVALID", c == 422 and (r or {}).get("code") == "SCHEDULE_RULE_INVALID", (c, r))
c, r = 打("POST", P + "/chat-tasks", 体={"staff_code": 工, "title": "x", "instruction": "y", "task_mode": "闹钟", "规则": {"周期": "日", "时刻": "09:00"}})
ck("task_mode 不认识 → 422", c == 422 and "task_mode" in ((r or {}).get("field_errors") or {}), (c, r))
c, l = 打("GET", P + f"/chat-tasks?staff_code={工}")
别人 = "E2ECTOTHER"   # ⚠️ 查询串里只放 ASCII(中文工号原样进 URL 会在 urlopen 就炸;这个仓库为此栽过五六次)
c2, l2 = 打("GET", P + f"/chat-tasks?staff_code={别人}")
ck("列表按 staff_code:自己的见,别人的工号见不到这条", [x["id"] for x in (l or {}).get("items") or []] == [tid] and not [x for x in (l2 or {}).get("items") or [] if x["id"] == tid], (c, c2))

print("\n▸ ③ 改")
c, r = 打("PATCH", P + f"/chat-tasks/{tid}", 体={"title": "改名"})
ck("不带 If-Match → 409", c == 409 and (r or {}).get("code") == "IF_MATCH_REQUIRED", (c, r))
c, r = 打("PATCH", P + f"/chat-tasks/{tid}?staff_code={别人}", 体={"title": "改名"}, 头={"If-Match": "1"})
ck("带别人的工号去改 → 404(不泄露)", c == 404, (c, r))
c, r = 打("PATCH", P + f"/chat-tasks/{tid}?staff_code={工}", 体={"title": "e2e 提醒(改)", "status": "停用"}, 头={"If-Match": "1"})
ck("本人改名 + 停用 → 200,revision 2,接下来几次为空", c == 200 and r.get("revision") == 2 and r.get("title") == "e2e 提醒(改)" and r.get("status") == "停用" and r.get("接下来几次") == [], (c, r))
c, r = 打("PATCH", P + f"/chat-tasks/{tid}?staff_code={工}", 体={"status": "启用"}, 头={"If-Match": "2"})
ck("再启用 → 200,revision 3,接下来三次回来", c == 200 and r.get("revision") == 3 and len(r.get("接下来几次") or []) == 3, (c, r))
# 店长视角(用户拍 ⑦):建一条归 SH001 的任务,店长带 store_id 能停;别的店不行
c, t店 = 打("POST", P + "/chat-tasks", 体={"staff_code": "E2ECTSTAFF", "store_id": "sh001", "title": "e2e 店员的", "instruction": "x", "task_mode": "提醒", "规则": {"周期": "日", "时刻": "09:00"}})
tid店 = (t店 or {}).get("id"); 建的.append(tid店)
ck("建时 store_id 统一成大写 SH001", c == 201 and (t店 or {}).get("store_id") == "SH001", (c, t店))
c, l店 = 打("GET", P + "/chat-tasks?store_id=sh001")
ck("按门店列(不分大小写)→ 见这条", any(x["id"] == tid店 for x in (l店 or {}).get("items") or []), c)
c, r = 打("PATCH", P + f"/chat-tasks/{tid店}?staff_code=E2ECTBOSS&store_id=SH002", 体={"status": "停用"}, 头={"If-Match": "1"})
ck("别的店的店长(SH002)来停 → 404", c == 404, (c, r))
c, r = 打("PATCH", P + f"/chat-tasks/{tid店}?staff_code=E2ECTBOSS&store_id=SH001", 体={"status": "停用", "note": "店长停用"}, 头={"If-Match": "1"})
ck("本店店长(不是本人、带 store_id=SH001)来停 → 200,状态停用", c == 200 and r.get("status") == "停用" and r.get("revision") == 2, (c, r))

print("\n▸ ④ 立即跑一次(提醒)")
c, r = 打("POST", P + f"/chat-tasks/{tid}/run-now?staff_code={工}")
rid = (r or {}).get("run_id")
ck("run-now → 202 排队", c == 202 and rid and r.get("status") == "排队", (c, r))
c, r2 = 打("POST", P + f"/chat-tasks/{tid}/run-now?staff_code={工}")
ck("再点 → 409 CHAT_TASK_BUSY", c == 409 and (r2 or {}).get("code") == "CHAT_TASK_BUSY", (c, r2))
好 = 等(lambda: next((x for x in 跑们(tid) if x["id"] == rid and x["status"] not in ("排队", "进行中")), None), 150)
ck("worker 一分钟内执行成「提醒」,正文「到点了:…」,kind 手动,进了收件箱", 好 and 好["status"] == "提醒" and str(好["answer_text"]).startswith("到点了") and 好["kind"] == "手动" and 好["inbox_at"], 好)
c, ib = 打("GET", P + f"/chat-task-inbox?staff_code={工}")
ck("收件箱未读 1,带任务名", c == 200 and ib.get("未读") == 1 and ib["items"][0]["title"] == "e2e 提醒(改)", (c, ib))
c, _ = 打("POST", P + f"/chat-task-runs/{rid}/read?staff_code={工}")
c2, ib = 打("GET", P + f"/chat-task-inbox?staff_code={工}")
c3, _ = 打("POST", P + f"/chat-task-runs/{rid}/read?staff_code={别人}")
ck("标已读 → 未读 0;别人标不了(404)", c == 200 and ib.get("未读") == 0 and c3 == 404, (c, ib.get("未读"), c3))

print("\n▸ ⑤ 到点调度")
现在 = datetime.now(ZoneInfo("Asia/Shanghai"))
到点 = (现在 + timedelta(minutes=1)).strftime("%H:%M")
c, t2 = 打("POST", P + "/chat-tasks", 体={"staff_code": 工, "title": "e2e 到点", "instruction": "到点提醒", "task_mode": "提醒", "规则": {"周期": "日", "时刻": 到点}})
tid2 = (t2 or {}).get("id"); 建的.append(tid2)
ck(f"建一条每天 {到点} 的", c == 201 and tid2, (c, t2))
定 = 等(lambda: [x for x in 跑们(tid2) if x["kind"] == "定时" and x["status"] not in ("排队", "进行中")] or None, 200, 10)
ck("约两分钟内 worker 排了一条 定时 运行并执行成 提醒", 定 and 定[0]["status"] == "提醒" and 定[0]["period_key"].startswith("定时:"), 跑们(tid2))
time.sleep(65)
ck("再过一分钟:同一期只有一条(期键唯一,last_period_start 记了)", len([x for x in 跑们(tid2) if x["kind"] == "定时"]) == 1, [x["period_key"] for x in 跑们(tid2)])
c, d2 = 打("GET", P + f"/chat-tasks?staff_code={工}")
行 = next((x for x in (d2 or {}).get("items") or [] if x["id"] == tid2), {})
ck("列表里成功次数 1、上次结果 提醒", 行.get("成功次数") == 1 and 行.get("上次结果") == "提醒", 行)

print("\n▸ ⑥ 「跑」类 + 不在职工号 → 聊天站 NO_STAFF → 自动停用")
c, t3 = 打("POST", P + "/chat-tasks", 体={"staff_code": "E2ECTNOBODY", "title": "e2e 跑", "instruction": "看看商机", "task_mode": "跑", "规则": {"周期": "日", "时刻": "09:00"}})
tid3 = (t3 or {}).get("id"); 建的.append(tid3)
c, r = 打("POST", P + f"/chat-tasks/{tid3}/run-now?staff_code=E2ECTNOBODY")
rid3 = (r or {}).get("run_id")
败 = 等(lambda: next((x for x in 跑们(tid3) if x["id"] == rid3 and x["status"] not in ("排队", "进行中")), None), 150)
ck("worker 调了聊天站,运行 失败,error_detail 带 http 403 / NO_STAFF", 败 and 败["status"] == "失败" and str((败.get("error_detail") or {}).get("http")) == "403"
   and ((败.get("error_detail") or {}).get("回") or {}).get("code") == "NO_STAFF", 败)
c, d3 = 打("GET", P + "/chat-tasks?staff_code=E2ECTNOBODY")
行 = next((x for x in (d3 or {}).get("items") or [] if x["id"] == tid3), {})
ck("任务自动停用,note 说这个工号不在职", 行.get("status") == "停用" and "不在职" in (行.get("note") or ""), 行)
ck("收件箱多一条系统说明(已自动停用)", any(x["kind"] == "系统" and "自动停用" in (x.get("answer_text") or "") for x in 跑们(tid3)), [(x["kind"], x["status"]) for x in 跑们(tid3)])

print("\n▸ ⑦ 归档")
c, l = 打("GET", P + f"/chat-tasks?staff_code={工}")
rev = next((x["revision"] for x in (l or {}).get("items") or [] if x["id"] == tid), None)
c, r = 打("POST", P + f"/chat-tasks/{tid}/archive?staff_code={工}", 头={"If-Match": str(rev)})
c2, l = 打("GET", P + f"/chat-tasks?staff_code={工}")
c3, r3 = 打("POST", P + f"/chat-tasks/{tid}/run-now?staff_code={工}")
ck("归档 → 200;列表没了;run-now 404", c == 200 and not [x for x in (l or {}).get("items") or [] if x["id"] == tid] and c3 == 404, (c, c3))

print("\n▸ 收尾:归档剩下的")
for x in 建的:
    if not x:
        continue
    c, l = 打("GET", P + "/chat-tasks?limit=200")
    rev = next((y["revision"] for y in (l or {}).get("items") or [] if y["id"] == x), None)
    if rev is not None:
        打("POST", P + f"/chat-tasks/{x}/archive", 头={"If-Match": str(rev)})

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ 员工定时任务 e2e {len(过)} 条全过")
