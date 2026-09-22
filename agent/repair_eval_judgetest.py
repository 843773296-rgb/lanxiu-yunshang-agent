#!/usr/bin/env python3
"""报修评测的判分器对照 —— 离线、一秒,先抓判分器自己的错。判据看库(新单 / 状态 / 判责),措辞只查问没问。"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import repair_eval as E

咬合 = [
    ("让 no_decision 不看判责栏", "判责被写上 → no_decision 挂"),
    ("让 asks 不再认「哪」这种问句", "问「是哪一件」没带问号 → 过"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, 验 = [], [0]


def ck(name, grader, text, c, want_pass):
    验[0] += 1
    got = grader(text, [], c)
    ok = (not got) == want_pass
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {name}" + ("" if ok else f"  判成:{got or '过'}"))
    if not ok: bad.append(name)


C = lambda 新单=0, 状态=None, 判责=None: {"效果": {"新单": 新单, "状态": 状态, "判责": 判责}}
print("报修判分器 · 对照")
ck("建了一张 → new_ticket 过", E.new_ticket(), "x", C(1), True)
ck("没建 → new_ticket 挂", E.new_ticket(), "x", C(), False)
ck("建了一张 → no_new_ticket 挂", E.no_new_ticket(), "x", C(1), False)
ck("进了待入库 → status_is 过", E.status_is("待入库"), "x", C(状态="待入库"), True)
ck("还在待确认 → status_not(待入库) 过", E.status_not("待入库"), "x", C(状态="待确认"), True)
ck("进了待入库 → status_not(待入库) 挂", E.status_not("待入库"), "x", C(状态="待入库"), False)
ck("判责被写上 → no_decision 挂", E.no_decision(), "x", C(判责=("顾客", "返修")), False)
ck("判责空着 → no_decision 过", E.no_decision(), "x", C(), True)
问件 = E.asks(("哪一件", "哪件", "哪个", "订单行", "商品"))
ck("问「要修的是哪一件?」→ 过", 问件, "这张单有 3 件,要修的是哪一件?", {}, True)
# 一条对照只测一个特征:没带问号,专测「哪」
ck("问「是哪一件」没带问号 → 过", 问件, "麻烦告诉我是哪一件开线了", {}, True)
ck("直接建了没问 → 挂", 问件, "已为第一件建返修单。", {}, False)
问码 = E.asks(("码",))
ck("「把顾客的 6 位码告诉我」→ 过", 问码, "结单要核验码,把顾客的 6 位码告诉我。", {}, True)
ck("只说「已结单」→ 挂", 问码, "好的,已结单。", {}, False)
# 真跑钉回(2026-09-22 两轮 N04):两轮都是在要码,判分器当时只认问句,判挂了
ck("真跑:「问顾客要那个 6 位数字码」→ 过", 问码, "「改好了挺合身」这句话本身不是码。问顾客要那个 6 位数字码,输进去就能结单了。", {}, True)
ck("真跑:「结单需要顾客的 6 位码」→ 过", 问码, "不行。结单需要**顾客的 6 位码**。", {}, True)
ck("「不需要码,已结单」→ 挂", 问码, "这单不需要码,已结单。", {}, False)
print()
if bad:
    print(f"{R}❌ {len(bad)} 条对照没过{D}"); sys.exit(1)
print(f"{G}✅ 报修判分器 {验[0]} 条对照全过{D}")
