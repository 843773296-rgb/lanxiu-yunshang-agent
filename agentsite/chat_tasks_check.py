#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天站「我的定时」检查(11-22,台账第九十条)—— 不起服务、不连后台:
  ① 没登录一律 401(任务记在工号上,没工号就没法记)
  ② 去后台的每一条都带本人工号:建 用 me.no 当 staff_code、门店从 me.shop_code 来;改 / 归档 / 跑一次 / 结果 / 收件箱 / 已读 的查询串都带 staff_code=本人
  ③ 改 / 归档 缺 id 或 revision → 400(revision 由页面带上它看到的那一版,这里不替它重读 —— 和人工待办同一条规矩)
  ④ 人话:连不上 / 404 / 409 BUSY / 409 其他 / 422 字段级 分开说,下一步不同
  ⑤ app.py:/internal/chat 认 任务id(不要密钥)、费用到顶回 429 BUDGET_EXHAUSTED、跑完记门店用量;九条路由都在「转发给后台」那一行**之前**
  ⑥ station.html:按钮 / 面板 / 角标 都在,周几 0 = 周一
"""
import json
import os
import re
import sys
from unittest import mock

这 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 这)
import chat_tasks as C  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:220]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


me = {"no": "60000011", "name": "苏彧", "role": "顾问", "shop": "SH001 静安旗舰店", "shop_code": "SH001"}
调用 = []


def 假调(方法, 路径, 体=None, 头=None, timeout=20):
    调用.append((方法, 路径, 体, 头))
    return {"GET": 200, "POST": 201 if 路径.startswith("/chat-tasks") and "/" not in 路径[len("/chat-tasks"):] else (202 if "run-now" in 路径 else 200),
            "PATCH": 200}[方法], {"items": [], "id": "ct_x", "未读": 0}


print("▸ ① 没登录")
ck("列表 / 建 / 改 / 收件箱 没登录都 401", all(f(None, *a)[0] == 401 for f, a in ((C.列表, ()), (C.建, ({},)), (C.改, ({"id": "x", "revision": 1},)), (C.收件箱, ()), (C.跑一次, ({"id": "x"},)))))

print("\n▸ ② 每一条都带本人工号")
with mock.patch.object(C, "_调", 假调):
    C.列表(me); C.建(me, {"title": "t", "instruction": "i", "task_mode": "跑", "规则": {"周期": "日", "时刻": "09:00"}, "staff_code": "想冒充的"})
    C.改(me, {"id": "ct_1", "revision": 3, "title": "n"}); C.归档(me, {"id": "ct_1", "revision": 3}); C.跑一次(me, {"id": "ct_1"})
    C.结果(me, "ct_1"); C.收件箱(me); C.已读(me, {"run_id": "ctr_1"})
建体 = next(b for m, p, b, h in 调用 if m == "POST" and p == "/chat-tasks")
ck("建:staff_code 用登录工号(调用方塞的「想冒充的」被盖掉),门店来自 shop_code", 建体["staff_code"] == "60000011" and 建体["store_id"] == "SH001", 建体)
带 = [(m, p) for m, p, b, h in 调用 if "staff_code=60000011" in p]
ck("列表 / 改 / 归档 / 跑一次 / 结果 / 收件箱 / 已读 七条的查询串都带 staff_code=本人", len(带) == 7, [(m, p) for m, p, b, h in 调用])
改头 = next(h for m, p, b, h in 调用 if m == "PATCH")
ck("改 带 If-Match = 页面看到的 revision", 改头 == {"If-Match": "3"}, 改头)

print("\n▸ ③ 缺字段")
ck("改 / 归档 缺 id 或 revision → 400;跑一次 缺 id → 400;已读 缺 run_id → 400",
   C.改(me, {"id": "x"})[0] == 400 and C.归档(me, {"revision": 1})[0] == 400 and C.跑一次(me, {})[0] == 400 and C.已读(me, {})[0] == 400)

print("\n▸ ④ 人话")
ck("连不上 → UNREACHABLE", C.人话(0, {})["code"] == "UNREACHABLE")
ck("404 → 说「不是你的 / 没了」", "不是你的" in C.人话(404, {"code": "NOT_FOUND"})["error"])
ck("409 BUSY 和 409 其他 分开说", "排队" in C.人话(409, {"code": "CHAT_TASK_BUSY"})["error"] and "改过" in C.人话(409, {"code": "CONFLICT"})["error"])
ck("422 带字段级原因", "规则:坏" in C.人话(422, {"code": "VALIDATION", "message": "m", "field_errors": {"规则": "坏"}})["怎么办"])

print("\n▸ ⑤ app.py")
ap = open(os.path.join(这, "app.py"), encoding="utf-8").read()
ck("/internal/chat 认 任务id,不要密钥也放行", '任务id = str(body.get("任务id")' in ap and "(kid or 任务id)" in ap)
ck("费用到顶 → 429 BUDGET_EXHAUSTED(不跑)", '"code": "BUDGET_EXHAUSTED"' in ap and "code=429" in ap)
ck("带 任务id 的那一轮记门店用量(_su.记)", re.search(r"if 任务id:\s*\n.*?_su\.记\(r\.get\(\"trace_id\"\)", ap, re.S) is not None)
GET = ap.find('"/api/chat-tasks", "/api/chat-task-templates"'); 转 = ap.find('if p.startswith("/api/") or p.startswith("/img/")')
POST = ap.find('"/api/chat-task", "/api/chat-task/update"'); 决 = ap.find('if p == "/api/human-request/decide"')
ck("GET 四条写在「转发给后台」之前;POST 五条写在人工待办决定之前(都在 answer-feedback 之前)", 0 < GET < 转 and 0 < POST < 决, (GET, 转, POST, 决))

print("\n▸ ⑥ station.html")
st = open(os.path.join(这, "web", "station.html"), encoding="utf-8").read()
ck("按钮 / 面板 / 结果 / 角标 四样都在", all(s in st for s in ('id="ctbtn"', "async function 开我的定时", "async function 开定时结果", "async function 刷定时角标")))
ck("周几 0 = 周一(和 runtime/定时.py 一致),规则读写走同一对函数", 'const _ct周几名 = ["一", "二"' in st and "function _ct规则读" in st and "function _ct规则控件" in st)

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ 聊天站我的定时 {len(过)} 条全过")
