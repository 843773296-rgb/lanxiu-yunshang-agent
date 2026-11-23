#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""员工定时 agent 任务 · 端到端(11-22,台账第九十条)。真服务(8801 + worker)+ 真库;聊天站那一侧:提醒类不经过它,「跑」类用一个不在职的工号,
聊天站会回 403 NO_STAFF —— 真走一遍 /internal/chat 的 任务id 分支,**不调模型、不花钱**。
  ① 模板:三个,频率说法对
  ② 建(提醒 / 每天):201 启用、频率说明、接下来三次;列表按 staff_code 只见自己的
  ③ 改:不带 If-Match 409;别人的工号 404;停用后接下来几次为空;再启用
  ④ 立即跑一次(提醒):202 → 再点 409 BUSY → worker 一分钟内执行成 提醒 → 收件箱未读 1、正文「到点了」→ 标已读 → 未读 0
     + 飞书送达(11-23):这一条用默认策略真发(本机配了接收方 → 已发;CI 没配 → 未配置);GET /chat-task-feishu 给工作台看;其余几条策略关掉飞书 → 策略不发
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
# 飞书送达(11-23):这条任务用默认策略(飞书开着)→ 本机配了接收方就真发一条(已发);GitHub CI 没配 → 未配置。「失败」算红 —— 它说的是发了没出去
# ⚠️ 结果和 feishu_detail 是**两个事务**写的(发飞书在事务外、要几秒),上面那个 等 看到 status 变了就返回,这时 feishu_detail 多半还是空 —— 第二轮 e2e 就红在这;再等它出现
好 = 等(lambda: next((x for x in 跑们(tid) if x["id"] == rid and x.get("feishu_detail")), None), 40) or 好
飞细 = (好 or {}).get("feishu_detail") or {}
ck("飞书送达落在 feishu_detail.状态(配了接收方 → 已发 + feishu_at;没配 → 未配置)", 飞细.get("状态") in ("已发", "未配置")
   and (飞细["状态"] != "已发" or (好.get("feishu_at") and 飞细.get("message_id"))), (好 or {}).get("feishu_detail"))
c, 飞 = 打("GET", P + "/chat-task-feishu?limit=5")
ck("GET /chat-task-feishu → 200:配置了(布尔)/ 按状态 / items 里有这条、不吐 open_id", c == 200 and isinstance((飞 or {}).get("配置了"), bool) and "按状态" in (飞 or {})
   and any(x["id"] == rid for x in (飞 or {}).get("items") or []) and "open_id" not in json.dumps(飞, ensure_ascii=False), (c, 飞))
c, ib = 打("GET", P + f"/chat-task-inbox?staff_code={工}")
ck("收件箱未读 1,带任务名", c == 200 and ib.get("未读") == 1 and ib["items"][0]["title"] == "e2e 提醒(改)", (c, ib))
c, _ = 打("POST", P + f"/chat-task-runs/{rid}/read?staff_code={工}")
c2, ib = 打("GET", P + f"/chat-task-inbox?staff_code={工}")
c3, _ = 打("POST", P + f"/chat-task-runs/{rid}/read?staff_code={别人}")
ck("标已读 → 未读 0;别人标不了(404)", c == 200 and ib.get("未读") == 0 and c3 == 404, (c, ib.get("未读"), c3))

print("\n▸ ⑤ 到点调度")
现在 = datetime.now(ZoneInfo("Asia/Shanghai"))
到点 = (现在 + timedelta(minutes=1)).strftime("%H:%M")
c, t2 = 打("POST", P + "/chat-tasks", 体={"staff_code": 工, "title": "e2e 到点", "instruction": "到点提醒", "task_mode": "提醒", "规则": {"周期": "日", "时刻": 到点},
                                        "deliver_policy": {"站内": True, "飞书": False}})   # 这条不要飞书:验「策略不发」,也别每跑一次 e2e 就给人发好几条
tid2 = (t2 or {}).get("id"); 建的.append(tid2)
ck(f"建一条每天 {到点} 的(策略不开飞书)", c == 201 and tid2 and (t2 or {}).get("deliver_policy", {}).get("飞书") is False, (c, t2))
定 = 等(lambda: [x for x in 跑们(tid2) if x["kind"] == "定时" and x["status"] not in ("排队", "进行中")] or None, 200, 10)
ck("约两分钟内 worker 排了一条 定时 运行并执行成 提醒", 定 and 定[0]["status"] == "提醒" and 定[0]["period_key"].startswith("定时:"), 跑们(tid2))
ck("策略没开飞书 → feishu_detail.状态 策略不发(不去发、feishu_at 空)", bool(定) and (定[0].get("feishu_detail") or {}).get("状态") == "策略不发" and not 定[0].get("feishu_at"),
   定 and 定[0].get("feishu_detail"))
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
败 = 等(lambda: next((x for x in 跑们(tid3) if x["id"] == rid3 and x.get("feishu_detail")), None), 40) or 败   # feishu_detail 是第二个事务写的,再等一拍
ck("失败的运行不推飞书 → feishu_detail.状态 策略不发,为什么说明", bool(败) and (败.get("feishu_detail") or {}).get("状态") == "策略不发" and "失败" in str((败.get("feishu_detail") or {}).get("为什么")),
   败 and 败.get("feishu_detail"))


def _聊天站在吗():
    """GitHub CI 只起 8801 + worker,**不起聊天站**;本地两个都在。聊天站不在时 NO_STAFF 那条路验不到,要明说「不适用」而不是红、也不是绿。"""
    try:
        urllib.request.urlopen(os.environ.get("LANXIU_AGENTSITE_URL", "http://127.0.0.1:8770") + "/", timeout=3)
        return True
    except urllib.error.HTTPError:
        return True          # 回了 HTTP(哪怕 4xx)就是在
    except Exception:
        return False


if _聊天站在吗():
    ck("worker 调了聊天站,运行 失败,error_detail 带 http 403 / NO_STAFF", 败 and 败["status"] == "失败" and str((败.get("error_detail") or {}).get("http")) == "403"
       and ((败.get("error_detail") or {}).get("回") or {}).get("code") == "NO_STAFF", 败)
    c, d3 = 打("GET", P + "/chat-tasks?staff_code=E2ECTNOBODY")
    行 = next((x for x in (d3 or {}).get("items") or [] if x["id"] == tid3), {})
    ck("任务自动停用,note 说这个工号不在职", 行.get("status") == "停用" and "不在职" in (行.get("note") or ""), 行)
    ck("收件箱多一条系统说明(已自动停用)", any(x["kind"] == "系统" and "自动停用" in (x.get("answer_text") or "") for x in 跑们(tid3)), [(x["kind"], x["status"]) for x in 跑们(tid3)])
else:
    # 11-24:11-19 起 GitHub CI 这份一直红在上面三条、没人看见 —— 那里没有聊天站,worker 只会记「连不上聊天站」
    ck("(没有聊天站)worker 调不到聊天站 → 运行 失败,error_detail 记了连不上", bool(败) and 败["status"] == "失败" and "聊天站" in json.dumps(败.get("error_detail") or {}, ensure_ascii=False), 败)
    print("  ⚠️ 不适用 ×2:『任务自动停用(不在职)』『收件箱系统说明』要聊天站回 NO_STAFF 才验得到 —— 这里没有聊天站,**不是通过**,本地 e2e-ci 验")

print("\n▸ ⑥b 一次性任务(店长派任务的提醒走这条:用户拍 ⑥)")
过去 = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(minutes=1)).isoformat()
c, t一 = 打("POST", P + "/chat-tasks", 体={"staff_code": 工, "title": "e2e 一次性", "instruction": "截止前提醒", "task_mode": "提醒", "规则": {"周期": "一次", "时刻": 过去}, "source_ref": "task:E2ESC1",
                                        "deliver_policy": {"站内": True, "飞书": False}})
tid一 = (t一 or {}).get("id"); 建的.append(tid一)
ck("建一次性(时刻已到)→ 201,频率说明「一次:…」", c == 201 and tid一 and str((t一 or {}).get("频率说明", "")).startswith("一次:"), (c, t一))
c, 再 = 打("POST", P + "/chat-tasks", 体={"staff_code": 工, "title": "e2e 一次性(重放)", "instruction": "x", "task_mode": "提醒", "规则": {"周期": "一次", "时刻": 过去}, "source_ref": "task:E2ESC1"})
ck("同一来源再建 → 回已有那条(澜绣同步每 30 秒重放,不许重建)", c == 201 and (再 or {}).get("id") == tid一 and (再 or {}).get("已有") is True, (c, 再))
一 = 等(lambda: [x for x in 跑们(tid一) if x["kind"] == "定时" and x["status"] not in ("排队", "进行中")] or None, 150, 10)
ck("worker 到点排了一条并执行成 提醒,期键 once:", 一 and 一[0]["status"] == "提醒" and 一[0]["period_key"] == f"once:{tid一}", 跑们(tid一))
c, d一 = 打("GET", P + f"/chat-tasks?staff_code={工}")
行 = next((x for x in (d一 or {}).get("items") or [] if x["id"] == tid一), {})
ck("一次性到点后任务自动停用,note 说明", 行.get("status") == "停用" and "一次性" in (行.get("note") or ""), 行)
c, r = 打("POST", P + "/chat-tasks", 体={"staff_code": 工, "title": "x", "instruction": "y", "task_mode": "提醒", "规则": {"周期": "一次", "时刻": "明天下午"}})
ck("一次性时刻认不出 → 422", c == 422 and (r or {}).get("code") == "SCHEDULE_RULE_INVALID", (c, r))

print("\n▸ ⑦ 归档")
c, l = 打("GET", P + f"/chat-tasks?staff_code={工}")
rev = next((x["revision"] for x in (l or {}).get("items") or [] if x["id"] == tid), None)
c, r = 打("POST", P + f"/chat-tasks/{tid}/archive?staff_code={工}", 头={"If-Match": str(rev)})
c2, l = 打("GET", P + f"/chat-tasks?staff_code={工}")
c3, r3 = 打("POST", P + f"/chat-tasks/{tid}/run-now?staff_code={工}")
ck("归档 → 200;列表没了;run-now 404", c == 200 and not [x for x in (l or {}).get("items") or [] if x["id"] == tid] and c3 == 404, (c, c3))

print("\n▸ 收尾:归档剩下的,只留一条(停用)当样例")
# 11-23:page-smoke 里 ifmatch_reachable_check 要从 GET /chat-tasks 列表拿一个 revision 当样例,归档的列表里不出现,
# 全归档它就「列表空 = 什么都没验到」红 → 这次建的里还在列表上的第一条改成停用留着(⑦ 已把 tid 归档了,所以不是它);
# 上次跑剩的 E2ECT 工号任务顺手归档,库里始终只留一条。
c, l = 打("GET", P + "/chat-tasks?limit=200")
留 = None
for y in (l or {}).get("items") or []:
    if y["id"] in 建的 and 留 is None:
        留 = y
    elif y["id"] in 建的 or str(y.get("staff_code") or "").startswith("E2ECT"):
        打("POST", P + f"/chat-tasks/{y['id']}/archive", 头={"If-Match": str(y["revision"])})
c1, r1 = 打("PATCH", P + f"/chat-tasks/{留['id']}", 体={"status": "停用"}, 头={"If-Match": str(留["revision"])}) if 留 else (None, None)
ck("留一条停用的当样例 → 200(给 ifmatch_reachable_check)", c1 == 200 and (r1 or {}).get("status") == "停用", (c1, r1))

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ 员工定时任务 e2e {len(过)} 条全过")
