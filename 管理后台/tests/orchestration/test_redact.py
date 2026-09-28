#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脱敏的纯逻辑 —— **形状不是截断**(零 IO,跑在 CI 里)。

## 为什么这一条值得单独测

契约给 `GET /traces/{id}` 登记了字段权限「查看敏感输入/独立测试答案」,
理由是 `input_ref` / `output_ref` 里是**真实业务内容**。

而最容易写错的脱敏是**截断**:截到 100 字看起来安全,
但那 100 字**仍然是原文** —— 而原文的第一句往往正是最敏感的那句
(客户姓名、订单号、手机号通常在开头)。

正确的脱敏给**形状**:有哪些键、每个多长。
形状能回答「这里有没有东西、大概多大」,而不泄露任何一个字。
"""
import json
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "contract"))

# ⚠️ 只借纯函数,不 import 整个 runs_api(它要 fastapi / db)。
# 这一条是「零依赖那组」能跑的前提。
_src = open(os.path.join(_根, "services", "api", "app", "runs_api.py"),
            encoding="utf-8").read()
_i = _src.index("def 脱敏(")
_j = _src.index("@router.get", _i)
_ns = {"_json": json}
exec(_src[_i:_j], _ns)
脱敏 = _ns["脱敏"]
最多几个span = int(_src.split("最多几个span = ")[1].split("\n")[0])

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


敏感 = json.dumps({"客户": "李明明", "手机": "13800138000",
                 "问题": "我上周下的那件云锦礼服什么时候能好"}, ensure_ascii=False)

print("▸ ① 脱敏给的是形状,**不是截断**")
r = 脱敏(敏感)
ck("键名留着(形状的一部分)", set(r) == {"客户", "手机", "问题"}, sorted(r))
原文里的字 = ["李明明", "13800138000", "云锦", "礼服", "上周"]
漏出的 = [w for w in 原文里的字 if w in json.dumps(r, ensure_ascii=False)]
ck("**一个原文的字都没漏出来**(截断式脱敏会漏掉开头那几十字)",
   not 漏出的, 漏出的)
ck("给了长度(能回答「这里有没有东西、大概多大」)",
   all("字>" in str(v) for v in r.values()), r)

print("▸ ② 各种形状都不炸,**而且都不漏内容**")
for 名, 值 in (("不是 JSON 的字符串", "李明明的订单出问题了"),
            ("列表", json.dumps(["李明明", "王芳"], ensure_ascii=False)),
            ("标量", json.dumps("李明明", ensure_ascii=False)),
            ("None", None),
            ("已经是 dict", {"客户": "李明明"}),
            ("空 dict", "{}")):
    out = 脱敏(值)
    s = json.dumps(out, ensure_ascii=False)
    ck(f"{名} → 不炸且不漏「李明明」", "李明明" not in s, s[:70])

print("▸ ③ 值为 None 的键保持 None(**「没有」和「有但看不到」要分得开**)")
r2 = 脱敏(json.dumps({"有": "x", "没有": None}, ensure_ascii=False))
ck("None 还是 None", r2["没有"] is None and r2["有"] is not None, r2)

print("▸ ④ 咬合:换成截断式脱敏,①那条必须红")
def 截断式(值, n=20):
    return None if 值 is None else str(值)[:n]
漏 = [w for w in 原文里的字 if w in str(截断式(敏感, 60))]
ck("截断到 60 字 **会漏出原文**(所以那不叫脱敏)", bool(漏), 漏)

print("▸ ⑤ span 上限是棘轮")
ck("最多几个span 是写死的数,不是算出来的", 最多几个span == 200, 最多几个span)
ck("而且不大于 500(一棵几千节点的树在界面上打不开,"
   "而「打不开」和「没有数据」长得一样)", 最多几个span <= 500)

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
