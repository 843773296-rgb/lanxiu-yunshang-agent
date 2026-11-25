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

# 咬合(每条在 tools/bite_specs.json 里有可重放的规格:改坏什么 → 该红的是哪一条)
咬合 = [
    ("带 任务id 的那一轮不再记门店用量 —— 用户拍「不限条数,靠门店月上限兜」,不记账上限就兜不住定时任务", "带 任务id 的那一轮记门店用量(_su.记)"),
]
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
ck("顾问不是店长:改 / 归档 的查询串**不带** store_id", not any("store_id=" in p for m, p, b, h in 调用 if m in ("PATCH",) or "archive" in p))

print("\n▸ ②b 店长视角(用户拍 ⑦)")
店长 = {"no": "60000003", "name": "店长", "role": "店长", "shop": "SH001 静安旗舰店"}
ck("门店编号从登录身份的 shop 文字取第一段(SH001 静安旗舰店 → SH001);有 shop_code 优先;认不出 → None",
   C._门店码(店长) == "SH001" and C._门店码({"shop_code": "sh002"}) == "SH002" and C._门店码({"shop": "静安旗舰店"}) is None and C._门店码({}) is None)
调用.clear()
with mock.patch.object(C, "_调", 假调):
    码本店, d本店 = C.列表(店长, "本店"); C.列表(me, "本店"); C.改(店长, {"id": "ct_9", "revision": 1, "status": "停用"}); C.归档(店长, {"id": "ct_9", "revision": 1})
ck("店长看「本店」→ 查询串按 store_id=SH001,不按工号;返回标 是店长 / 范围 本店", "store_id=SH001" in 调用[0][1] and "staff_code" not in 调用[0][1] and d本店["是店长"] and d本店["范围"] == "本店 SH001", 调用[0][1])
ck("顾问传「本店」也只回自己的(按 staff_code)", "staff_code=60000011" in 调用[1][1] and "store_id" not in 调用[1][1], 调用[1][1])
ck("店长改 / 归档 带本人工号 + 本店编号(服务端:是他的或在他店里才认)", all("staff_code=60000003" in p and "store_id=SH001" in p for m, p, b, h in 调用[2:4]), [p for m, p, b, h in 调用[2:4]])

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
# ⚠️ 不用 re.S 的 .*?:它会跨到后面别的 _su.记,把 任务id 块里那一处删了也照样绿(11-22 配咬合时抓到)
ck("带 任务id 的那一轮记门店用量(_su.记)", re.search(r"if 任务id:\n(?:[^\n]*\n){1,5}\s*_su\.记\(r\.get\(\"trace_id\"\)", ap) is not None)
GET = ap.find('"/api/chat-tasks", "/api/chat-task-templates"'); 转 = ap.find('if p.startswith("/api/") or p.startswith("/img/")')
POST = ap.find('"/api/chat-task", "/api/chat-task/update"'); 决 = ap.find('if p == "/api/human-request/decide"')
ck("GET 四条写在「转发给后台」之前;POST 五条写在人工待办决定之前(都在 answer-feedback 之前)", 0 < GET < 转 and 0 < POST < 决, (GET, 转, POST, 决))

print("\n▸ ⑥ station.html")
st = open(os.path.join(这, "web", "station.html"), encoding="utf-8").read()
ck("按钮 / 面板 / 结果 / 角标 四样都在", all(s in st for s in ('id="ctbtn"', "async function 开我的定时", "async function 开定时结果", "async function 刷定时角标")))
ck("周几 0 = 周一(和 runtime/定时.py 一致),规则读写走同一对函数", 'const _ct周几名 = ["一", "二"' in st and "function _ct规则读" in st and "function _ct规则控件" in st)

print("\n▸ ⑦ 失败提示(11-25 用户拍「全站统一」):跑挂的那一期给店员看「一句人话 + 编号 + 能做什么」,程序原文折叠 —— node 真调 失败人话")
import re as _re, json as _json, subprocess as _sp
_m = _re.search(r"function 失败人话\(err\)\{.*?\n\}", st, _re.S)
ck("station.html 里找得到 失败人话(找不到下面几条就是没验)", bool(_m))
def _人话(err):
    js = (_m.group(0) if _m else "") + f"\nconsole.log(JSON.stringify(失败人话({_json.dumps(err, ensure_ascii=False)})));"
    r = _sp.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    return _json.loads(r.stdout) if r.returncode == 0 else {"node": r.stderr[-200:]}
x = _人话({"http": "500", "回": {"code": "INTERNAL", "error": "聊天站这一步出错了", "trace_id": "tr-9", "advice": "再跑一次"}})
ck("后台给了人话 / 编号 / 建议 → 原样用:话里带编号、办照 advice、原文折叠着还在", x["话"] == "聊天站这一步出错了(编号 tr-9)" and x["办"] == "再跑一次" and "INTERNAL" in x["原"], x)
x = _人话({"http": "500", "回": {"error": "TypeError: 'NoneType' object"}})
ck("后台只给了原文 → 原样当话(这是后台该修的,页面不替它编);没编号就不写编号", x["话"] == "TypeError: 'NoneType' object" and "编号" not in x["话"], x)
x = _人话({"http": 0, "回": {}})
ck("连不上(http 0)→ 「到点时连不上聊天站,这一期没跑」+ 默认怎么办(跑一次 / 三期停用)", "连不上" in x["话"] and "跑一次" in x["办"], x)
x = _人话({"http": "403", "回": {"code": "NO_STAFF"}})
ck("403 → 说工号不认(可能已不在职),不是「服务端出错」", "工号" in x["话"], x)
ck("没有 error_detail → 不编原文", _人话(None)["原"] == "" and _人话({})["原"] == "")
ck("接线:结果页签和执行记录都用 画失败 画失败的那一期,不再把 JSON 原文直接贴给店员", st.count("画失败(r.error_detail)") == 2 and "JSON.stringify(r.error_detail).slice(0, 300)" not in st)

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ 聊天站我的定时 {len(过)} 条全过")
