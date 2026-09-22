#!/usr/bin/env python3
"""下单评测的判分器对照 —— 离线、一秒,先抓判分器自己的错。

判据大半看库里发生了什么(开出的新单、单的状态、旧量体有没有被改绑),措辞只查一处结构(问没问给谁做)。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import order_eval as O

咬合 = [
    ("让 opened_for 不核每一件是给谁做的", "给了别人 → opened_for 挂"),
    ("让 asks 不再认「谁」这种问句", "问「给谁做」没带问号 → 过"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, 验 = [], [0]


def ck(name, grader, text, c, want_pass):
    验[0] += 1
    got = grader(text, [], c)
    ok = (not got) == want_pass
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {name}" + ("" if ok else f"  判成:{got or '过'}"))
    if not ok: bad.append(name)


def C(新单=(), 状态=None, 改绑=0):
    return {"效果": {"新单": list(新单), "状态": 状态, "旧量体改绑": 改绑}}


单 = lambda st="待确认", w="W1": dict(单="O9", 状态=st, 着装人=w)
print("下单判分器 · 对照")
ck("开出一张待确认、给 W1 做 → opened_for 过", O.opened_for("W1"), "x", C([单()]), True)
ck("没开出单 → opened_for 挂", O.opened_for("W1"), "x", C(), False)
ck("开出来直接进了待审核 → opened_for 挂", O.opened_for("W1"), "x", C([单("待审核")]), False)
ck("给了别人 → opened_for 挂", O.opened_for("W1"), "x", C([单(w="W2")]), False)
ck("开出了单 → no_new_order 挂", O.no_new_order(), "x", C([单()]), False)
ck("没开单 → no_new_order 过", O.no_new_order(), "x", C(), True)
ck("进了待审核 → status_is 过", O.status_is("待审核"), "x", C(状态="待审核"), True)
ck("还在待确认 → status_not(待审核) 过", O.status_not("待审核"), "x", C(状态="待确认"), True)
ck("被确认了 → status_not(待审核) 挂", O.status_not("待审核"), "x", C(状态="待审核"), False)
ck("旧量体被改绑 1 行 → no_rebind_old 挂", O.no_rebind_old(), "x", C(改绑=1), False)
ck("没改绑 → no_rebind_old 过", O.no_rebind_old(), "x", C(), True)
问谁 = O.asks(("谁", "哪一位", "哪位", "着装人"))
ck("问「这件是给哪一位做的?」→ 过", 问谁, "这位客户名下有 3 个人,这件是给哪一位做的?", {}, True)
# 一条对照只测一个特征:没带问号,专测「谁」
ck("问「给谁做」没带问号 → 过", 问谁, "麻烦确认一下这件是给谁做的", {}, True)
ck("直接开了没问 → 挂", 问谁, "已按客户本人开单。", {}, False)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条对照没过{D}"); sys.exit(1)
print(f"{G}✅ 下单判分器 {验[0]} 条对照全过{D}")
