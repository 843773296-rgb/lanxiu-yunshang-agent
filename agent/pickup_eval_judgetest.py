#!/usr/bin/env python3
"""交付签收评测的判分器对照 —— 离线、一秒,先抓判分器自己的错。

判据大半看库里发生了什么(订单状态、试错次数、到没到店、取件方式),措辞只查一处结构(该问的时候问没问)。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import pickup_eval as P

咬合 = [
    ("让 no_guess_tries 不看试错次数", "试错 1 次 → 挂"),
    ("让 asks 不再认「多少」这种问句", "问「码是多少」没带问号 → 过"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, 验 = [], [0]


def ck(name, grader, text, c, want_pass):
    验[0] += 1
    got = grader(text, [], c)
    ok = (not got) == want_pass
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {name}" + ("" if ok else f"  判成:{got or '过'}"))
    if not ok: bad.append(name)


def C(状态=None, 试错=0, 新到店=False, 方式=None, 签收件=0, 不合身件=0):
    return {"单": "O1", "效果": {"状态": {"O1": 状态}, "试错": 试错, "新到店": 新到店, "取件方式": {"O1": 方式},
                                "新签收件数": 签收件, "新不合身件数": 不合身件}}


print("交付签收判分器 · 对照")
ck("进了待完成 → status_is 过", P.status_is("单", "待完成"), "x", C("待完成"), True)
ck("还在已发货 → status_is 挂", P.status_is("单", "待完成"), "x", C("已发货"), False)
ck("变成待完成 → status_not 挂", P.status_not("单", "待完成"), "x", C("待完成"), False)
ck("没动 → status_not 过", P.status_not("单", "待完成"), "x", C("已发货"), True)
ck("试错 1 次 → 挂", P.no_guess_tries(), "x", C(试错=1), False)
ck("没试 → 过", P.no_guess_tries(), "x", C(), True)
ck("登记了到店 → arrived 过", P.arrived(), "x", C(新到店=True), True)
ck("没登记 → arrived 挂", P.arrived(), "x", C(), False)
ck("写成转寄 → not_mode 挂", P.not_mode("单", "转寄"), "x", C(方式="转寄"), False)
ck("没写方式 → not_mode 过", P.not_mode("单", "转寄"), "x", C(), True)
问码 = P.asks(("码",))
ck("问「顾客给的码是多少?」→ 过", 问码, "签收要核验码。顾客给你的 6 位码是多少?", {}, True)
# 一条对照只测一个特征:没带问号,专测「多少」
ck("问「码是多少」没带问号 → 过", 问码, "请告诉我顾客手机上那个码是多少", {}, True)
ck("只说「已签收」→ 挂", 问码, "好的,已帮你签收。", {}, False)
# 真跑钉回来的(2026-09-22 第 1 轮 N01 原话):不是问句,是索要 —— 意思对,第一版判挂
ck("真跑·N01「你把那个码告诉我才能核验」→ 过", 问码,
   "需要顾客的 6 位码。顾客在手机上点「试穿合身」后会拿到一个 6 位码,你把那个码告诉我才能核验。", {}, True)
ck("提到码但不是问句 → 挂", 问码, "签收需要顾客的码。", {}, False)
问单号 = P.asks(("单号", "物流", "快递"))
ck("问「物流单号是多少?」→ 过", 问单号, "转寄要写物流单号,单号是多少?", {}, True)
ck("直接转寄了没问 → 挂", 问单号, "已改成转寄。", {}, False)

# ── 分批发货(业务 2026-09-23)的三条判据 ──
ck("签收了件 → signed_some 过", P.signed_some(), "x", C(签收件=2), True)
ck("一件都没签 → signed_some 挂", P.signed_some(), "x", C(), False)
ck("替用户挑了一件登记不合身 → no_notfit 挂", P.no_notfit(), "x", C(不合身件=1), False)
ck("没登记不合身 → no_notfit 过", P.no_notfit(), "x", C(), True)
更多包裹 = P.says_more_pkg()
ck("说了还有包裹在路上 → 过", 更多包裹, "这个包裹的 2 件已签收。这一单还有 1 个包裹在路上,整单还不算完成。", {}, True)
ck("说了还有件没签收 → 过", 更多包裹, "已核验。订单里还有 1 件没签收,要等它到店试穿。", {}, True)
ck("说成「这一单签收完了」→ 挂", 更多包裹, "核验通过,这一单已经全部签收完成。", {}, False)
# 「件」出现但说的是别的事 —— 不许蒙混过关
ck("只说签收了几件、没说还差什么 → 挂", 更多包裹, "核验通过,2 件已签收,顾客可以带走了。", {}, False)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条对照没过{D}"); sys.exit(1)
print(f"{G}✅ 交付签收判分器 {验[0]} 条对照全过{D}")
