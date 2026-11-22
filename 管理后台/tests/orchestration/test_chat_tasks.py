#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""员工定时 agent 任务(11-22,用户拍七条,台账第九十条)—— 纯函数 + 登记,不碰库不起服务。

  ① 模板按钮:三个,规则合法、周几 0 = 周一(「每周一」不是「每周二」—— 第一版写成 [1] 就错了)
  ② 提示词:带工号 / 任务名 / 一句话 / 现在的时间,**写明只读、不做写操作**
  ③ 规则 ↔ 库里一行 互转不丢(周几 / 几号 / 表达式 都落 cadence_detail)
  ④ 登记:endpoints 十条(权限按拍板)、开关们 chat_task.switch、main 挂路由、worker 调 员工任务扫一遍、entities 两张表、迁移文件、
     聊天站 /internal/chat 认 任务id + 费用闸 429 + 记门店用量、聊天站代理每条都带本人工号、页面按钮 / 后台页 / 冒烟名单
"""
import os
import re
import sys
from datetime import datetime, timezone

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
仓 = os.path.dirname(根)
APP = os.path.join(根, "services", "api", "app")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "runtime"))
sys.path.insert(0, os.path.join(APP, "contract"))
import chat_tasks_api as CT  # noqa: E402
import 定时 as T  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:240] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


def 读(*p):
    return open(os.path.join(仓, *p), encoding="utf-8").read()


print("▸ ① 模板按钮")
说 = {名: T.说法(T.校验规则({**t["规则"], "时区": "Asia/Shanghai"})) for 名, t in CT._模板.items()}
ck("三个模板,规则都合法", len(CT._模板) == 3 and all(t["title"] and t["instruction"] and t["role_key"] for t in CT._模板.values()), len(CT._模板), 说)
ck("商机探索每天 09:00;库存盘点 / 客户回访提醒 **每周一**(周几 0 = 周一)", 说.get("商机探索") == "每天 09:00" and 说.get("库存盘点") == "每周一 09:00"
   and 说.get("客户回访提醒") == "每周一 09:30", 3, 说)

print("\n▸ ② 提示词")
t = {"staff_code": "60000011", "title": "商机探索", "instruction": "看最近 7 天通话里的商机"}
p = CT._提示词(t, datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc))
ck("带工号 / 任务名 / 一句话 / 时间;写明只读、不做写操作", all(s in p for s in ("60000011", "商机探索", "看最近 7 天通话里的商机", "只读", "不要做任何写操作", "2026-11-22")), 1, p)

print("\n▸ ③ 规则互转")
for 规 in ({"周期": "日", "时刻": "08:00"}, {"周期": "周", "时刻": "09:00", "周几": [0, 4]}, {"周期": "月", "时刻": "07:30", "几号": [1, "末"]},
          {"周期": "cron", "表达式": "*/30 9-18 * * 1-5"}):
    规则 = T.校验规则({**规, "时区": "Asia/Shanghai"})
    行 = {"cadence": 规则["周期"], "fire_time": 规则.get("时刻") or "", "timezone": "Asia/Shanghai", "cadence_detail": CT._细节(规则)}
    回 = T.校验规则(CT._规则(行))
    ck(f"{T.说法(规则)} → 行 → 规则,说法一样", T.说法(回) == T.说法(规则), 1, (T.说法(回), T.说法(规则)))
ck("连续失败阈值是正整数且 ≥ 2(1 期失败就停会把偶发网络错当成坏任务)", isinstance(CT.失败阈值, int) and CT.失败阈值 >= 2, 1, CT.失败阈值)
行 = {"id": "ct_x", "status": "启用", "cadence": "日", "fire_time": "09:00", "timezone": "Asia/Shanghai", "cadence_detail": {}, "deliver_policy": None}
d = CT._行(行, datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc))
ck("列表行:频率说明「每天 09:00」,接下来三次是三个时刻字串(T.接下来几次 回的是三元组,只取执行时刻 —— 第十六轮 e2e 栽的)",
   d["频率说明"] == "每天 09:00" and len(d["接下来几次"]) == 3 and all(isinstance(x, str) and x.startswith("2026-11-2") for x in d["接下来几次"]), 3, d)
d2 = CT._行({**行, "status": "停用"}, datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc))
ck("停用的行:接下来几次为空、频率说明照给", d2["接下来几次"] == [] and d2["频率说明"] == "每天 09:00", 1, d2)

print("\n▸ ④ 登记")
ep = 读("管理后台", "services", "api", "app", "contract", "endpoints.py")


def 段(头):
    m = re.search(r"A\(" + re.escape(头) + r".*?(?=\n    A\(|\n\])", ep, re.S)
    return m.group(0) if m else ""


期 = [('"GET", "/chat-task-templates"', "查看有权配置"), ('"GET", "/chat-tasks"', "查看有权配置"), ('"POST", "/chat-tasks"', "运行评测"),
     ('"PATCH", "/chat-tasks/{id}"', "运行评测"), ('"POST", "/chat-tasks/{id}/archive"', "运行评测"), ('"POST", "/chat-tasks/{id}/run-now"', "运行评测"),
     ('"GET", "/chat-tasks/{id}/runs"', "查看有权配置"), ('"GET", "/chat-task-inbox"', "查看有权配置"), ('"POST", "/chat-task-runs/{id}/read"', "运行评测")]
漏 = [(h, 权) for h, 权 in 期 if 权 not in 段(h)]
ck("endpoints 九条都登记了、权限对(读 = 查看有权配置;写 = 运行评测,聊天站服务账号那档)", not 漏, len(期), 漏)
ck("PATCH / 归档 带乐观锁 + 审计;建 带审计", all("乐观锁=True" in 段(h) and "审计=True" in 段(h) for h in ('"PATCH", "/chat-tasks/{id}"', '"POST", "/chat-tasks/{id}/archive"'))
   and "审计=True" in 段('"POST", "/chat-tasks"'), 3)
wf = 读("管理后台", "services", "api", "app", "workflows_api.py")
ck("开关们 登记了 chat_task.switch", '"chat_task.switch":' in wf, 1)
ca = 读("管理后台", "services", "api", "app", "chat_tasks_api.py")
ck("写 schedule_enabled 的三处(建 / 改 / 归档)和自动停用都走 _审计 chat_task.switch", ca.count('"chat_task.switch"') >= 4, 4, ca.count('"chat_task.switch"'))
ck("main.py 挂了路由", "chat_tasks_api as _CTK" in 读("管理后台", "services", "api", "app", "main.py"), 1)
w = 读("管理后台", "workers", "worker.py")
ck("worker 的 扫定时 真调 CT.员工任务扫一遍,且和工作流定时分开 try", "CT.员工任务扫一遍(" in w and w.count("这一遍扫员工定时出错了") == 1, 1)
en = 读("管理后台", "services", "api", "app", "contract", "entities.py")
ck("entities 有 chat_tasks / chat_task_runs,runs 依赖 tasks", 'E("chat_tasks"' in en and 'E("chat_task_runs"' in en and '依赖=["chat_tasks"]' in en, 2)
迁 = [f for f in os.listdir(os.path.join(根, "services", "api", "migrations", "versions")) if f.endswith(".py") and "员工定时任务" in f]
ck("迁移建了两张表 + (chat_task_id, period_key) 唯一", 迁 and "op.create_table('chat_tasks'" in 读("管理后台", "services", "api", "migrations", "versions", 迁[0])
   and "uq_chat_task_runs_project_id_chat_task_id_period_key" in 读("管理后台", "services", "api", "migrations", "versions", 迁[0]), len(迁) or 1, 迁)
ap = 读("agentsite", "app.py")
ck("聊天站 /internal/chat 认 任务id(不要密钥)、费用到顶 429 BUDGET_EXHAUSTED、跑完记门店用量", all(s in ap for s in ('任务id = str(body.get("任务id")', '"code": "BUDGET_EXHAUSTED"', "_su.记(r.get(\"trace_id\")")), 3)
ck("聊天站路由:四条 GET + 五条 POST 都在转发之前", '"/api/chat-tasks", "/api/chat-task-templates", "/api/chat-task-runs", "/api/chat-task-inbox"' in ap
   and '"/api/chat-task", "/api/chat-task/update", "/api/chat-task/archive", "/api/chat-task/run-now", "/api/chat-task-run/read"' in ap, 2)
ct = 读("agentsite", "chat_tasks.py")
ck("聊天站代理:改 / 归档 / 跑一次 / 结果 / 收件箱 / 已读 每条都带本人工号(staff_code),建 用本人工号", ct.count('"staff_code": me["no"]') >= 6 and '体["staff_code"] = me["no"]' in ct, 7, ct.count('"staff_code": me["no"]'))
st = 读("agentsite", "web", "station.html")
ck("聊天站页面:按钮 / 开我的定时 / 收件箱角标 / 周几 0 = 周一", all(s in st for s in ('id="ctbtn"', "async function 开我的定时", "刷定时角标", 'const _ct周几名 = ["一"')), 4)
js = 读("管理后台", "apps", "web", "app.js")
ck("后台:菜单 / 路由 / 页 三处", all(s in js for s in ('["#/chat-tasks", "员工定时"', 'h === "#/chat-tasks"', "async function 页_员工定时")), 3)
ck("冒烟名单里有 #/chat-tasks 和 #/annotations", "'#/chat-tasks'" in 读("管理后台", "Makefile") and "'#/annotations'" in 读("管理后台", "Makefile"), 2)

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ 员工定时任务 {len(过)} 条全过")
