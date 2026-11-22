#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店长派任务 → 被派的人的一次性提醒(11-22,用户拍 ⑥)—— 不连后台、不碰真库(临时 sqlite)。
  ① 提醒体:截止前 60 分钟;那一刻已过但截止没到 → 现在 + 1 分钟;截止已过 / 没截止 / 没被派的人 → 不建;source_ref=task:<单号>、task_mode 提醒、周期 一次
  ② 推一轮:新派的有效任务 POST 一次(第二轮不重推 —— 推账记着);任务完结后下一轮归档一次(带 If-Match)
  ③ 一轮() 里接在桥之后、只连正式项目、出错不抛
"""
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

# 咬合(每条在 tools/bite_specs.json 里有可重放的规格:改坏什么 → 该红的是哪一条)
咬合 = [
    ("第二轮不再看推账、每轮都重推 —— 推账是幂等的唯一依据,去掉后同一个任务每五分钟建一条提醒", "第二轮:什么都不推(幂等)"),
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "agent"), os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import supervise_sync as S  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:220]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


现在 = datetime(2026, 11, 22, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
行 = {"id": "SC1", "type": "订单跟踪", "assignee_no": "60000011", "assigned_by": "60000003", "end_ts": "2026-11-22 18:00", "status": "有效", "shop_code": "SH001", "note": "催工厂", "ref_id": "O1"}

print("▸ ① 提醒体")
体 = S.提醒体(行, 现在)
ck("截止 18:00 → 提醒 17:00(提前 60 分);一次性;提醒模式;来源 task:SC1;归被派的人和他的店", 体 and 体["规则"] == {"周期": "一次", "时刻": "2026-11-22T17:00:00+08:00"}
   and 体["task_mode"] == "提醒" and 体["source_ref"] == "task:SC1" and 体["staff_code"] == "60000011" and 体["store_id"] == "SH001", 体)
ck("说明里有谁派的、什么任务、备注、关联单、截止、能改能关", 体 and all(s in 体["instruction"] for s in ("60000003", "订单跟踪", "催工厂", "O1", "2026-11-22 18:00", "能改能关")), 体 and 体["instruction"])
体2 = S.提醒体({**行, "end_ts": "2026-11-22 15:30"}, 现在)
ck("截止 15:30(提前点 14:30 已过、截止没到)→ 提醒 15:01(马上提醒一次)", 体2 and 体2["规则"]["时刻"] == "2026-11-22T15:01:00+08:00", 体2)
ck("截止已过 / 没截止 / 没被派的人 → 不建", S.提醒体({**行, "end_ts": "2026-11-22 14:00"}, 现在) is None and S.提醒体({**行, "end_ts": ""}, 现在) is None
   and S.提醒体({**行, "assignee_no": ""}, 现在) is None)
ck("截止格式认不出 → 不建(不编时刻)", S.提醒体({**行, "end_ts": "明天下午"}, 现在) is None)

print("\n▸ ② 推一轮(假后台 + 临时库 + 临时推账)")
d = tempfile.mkdtemp()
库 = os.path.join(d, "t.db")
with closing(sqlite3.connect(库)) as c, c:
    c.execute("CREATE TABLE schedule(id TEXT, type TEXT, assignee_no TEXT, assigned_by TEXT, end_ts TEXT, status TEXT, shop_code TEXT, note TEXT, ref_id TEXT, assigned_at TEXT)")
    for 值 in ("'SC1','订单跟踪','60000011','60000003','2099-01-01 18:00','有效','SH001','催','O1', datetime('now','localtime')",
              "'SC2','日常运维','60000012','60000003','','有效','SH001','','', datetime('now','localtime')",
              "'SC3','接待任务','60000012','60000003','2099-01-01 10:00','有效','SH001','','', datetime('now','localtime','-10 days')"):
        c.execute("INSERT INTO schedule(id, type, assignee_no, assigned_by, end_ts, status, shop_code, note, ref_id, assigned_at) VALUES(" + 值 + ")")
S._推账 = os.path.join(d, "pushes.json")
调用 = []


def 假后台(cfg, 项目, 方法, 路径, 体=None, 头=None):
    调用.append((方法, 路径, 体, 头))
    if 方法 == "POST" and 路径 == "/chat-tasks":
        return 201, {"id": "ct_" + 体["source_ref"].split(":")[1]}
    if 方法 == "GET":
        return 200, {"items": [{"id": "ct_SC1", "revision": 4}]}
    return 200, {"归档了": True}


S._后台 = 假后台
cfg = {"地址": "http://x", "项目": "p", "工号": "U001"}
新, 归, 说 = S.推派任务提醒(cfg, "project_lanxiu", db=库)
ck("第一轮:只给 SC1 建(SC2 没截止、SC3 是 10 天前派的不补)→ 新建 1、没错", 新 == 1 and 归 == 0 and not 说 and [p for m, p, b, h in 调用 if m == "POST"] == ["/chat-tasks"], (新, 归, 说, 调用))
账 = json.load(open(S._推账, encoding="utf-8"))
ck("推账记了 SC1 的后台任务号;SC2 没截止,查询那一步就没取出来(推账里没有它)", 账.get("SC1", {}).get("chat_task_id") == "ct_SC1" and "SC2" not in 账, 账)
调用.clear()
新, 归, 说 = S.推派任务提醒(cfg, "project_lanxiu", db=库)
ck("第二轮:什么都不推(幂等)", 新 == 0 and 归 == 0 and not 调用, (新, 归, 调用))
with closing(sqlite3.connect(库)) as c, c:
    c.execute("UPDATE schedule SET status='完结' WHERE id='SC1'")
调用.clear()
新, 归, 说 = S.推派任务提醒(cfg, "project_lanxiu", db=库)
ck("任务完结 → 下一轮归档那条提醒(先拉 revision,带 If-Match)", 归 == 1 and any(m == "POST" and p.startswith("/chat-tasks/ct_SC1/archive") and h == {"If-Match": "4"} for m, p, b, h in 调用), 调用)
调用.clear()
新, 归, 说 = S.推派任务提醒(cfg, "project_lanxiu", db=库)
ck("归档过的不再归档", 归 == 0 and not 调用, 调用)

print("\n▸ ③ 接线")
src = open(os.path.join(ROOT, "tools", "supervise_sync.py"), encoding="utf-8").read()
i = src.find("def 一轮("); j = src.find("推派任务提醒(cfg, 桥项目)", i)
ck("一轮() 里在桥之后调 推派任务提醒(cfg, 桥项目),只连正式项目,包了 try", 0 < src.find("n桥, 错桥 = 跑桥(", i) < j and "except Exception" in src[j:j + 400])
ck("提前量是 60 分钟(用户拍默认截止前 1 小时)", S.提前分钟 == 60)

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ 派任务提醒 {len(过)} 条全过")
