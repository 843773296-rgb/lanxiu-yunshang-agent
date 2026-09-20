# -*- coding: utf-8 -*-
"""成交归因的逐例真值。

这张表最容易出的错,是**把两种分成当成一种** ——
它们在库里长得一模一样(都是「某人 + 某个百分比」),而校验规则**相反**:

    收入分成   加起来**必须** 100  —— 分钱,零和
    影响力分成 加起来**可以超过** 100 —— 记贡献,不是零和

把影响力也按 100 校验,会把「一单三个人各有贡献」判成数据错误;
反过来,不校验收入分成,提成就会算错而没人发现。
"""
import os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import credit as C

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad = 0

# 这套检查依赖的夹具前提(由 tools/backfill_fixtures.py 造)
前提 = [
    ("deal_credit", "source", "「人工填」「规则算」「算法算」三种都要有",
     "三种来源算出来都是一个百分比,**长得一模一样** —— 不分开,换了算法就说不清哪条是哪种"),
    ("deal_credit", "影响力分成的每单总和", "至少有一单超过 100%",
     "**没有这种样本,一个把它当成「必须=100」的实现会全绿通过**"),
]

咬合 = [
    ('把影响力分成也按「总和必须 100」校验(两种分成合成一种)',
     '影响力分成可以超过 100%'),
]


def ck(t, got, want, extra=""):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {t:44s} 判为 {str(got):12s} 应为 {want}{extra}")


def main():
    global bad
    c = sqlite3.connect(C.DB)
    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    print("\n\033[1m▸ 成交归因 · 两种分成规则相反(在库里长得一样)\033[0m")
    print("  " + "=" * 80)

    n = q("select count(*) from deal_credit")
    if n == 0:
        print(f"  {R}❌{D} 一条归因记录都没有 —— **空集合上什么都成立**")
        return 1

    # ① 收入分成:每单必须正好 100
    坏 = C.收入分成对不对(C.DB)
    ck("收入分成每单加起来正好 100", "是" if not 坏 else f"{len(坏)} 单不对", "是",
       "  ← 那是分钱,多一分少一分都是错")

    # ② 影响力分成:**允许超过 100**,而且库里必须真有这样的样本
    超 = q(f"""select count(*) from (select order_id, sum(pct) s from deal_credit
               where kind=? group by order_id having s>100)""", C.影响力分成)
    ck("影响力分成可以超过 100%", "有样本" if 超 else "没有样本", "有样本",
       f"  ← {超} 单。**没有这种样本,「按 100 校验」的实现会全绿通过**")

    # ③ 两种分成都有样本 —— 否则测不出它们的区别
    for k in (C.收入分成, C.影响力分成):
        v = q("select count(*) from deal_credit where kind=?", k)
        ck(f"「{k}」有样本", v > 0, True, f"  ← {v} 条")

    # ④ kind 写错要当场拒绝
    try:
        C.记一笔("X", "Y", "随便一种", "成交", 50, "人工填")
        ck("kind 写错要拒绝", "放行了", "拒绝")
    except ValueError:
        ck("kind 写错要拒绝", "拒绝", "拒绝", "  ← 两种规则相反,混了就全错")

    # ⑤ 算法算的必须写明是哪个算法 —— **换算法之后老数据新数据就分不开了**
    try:
        C.记一笔("X", "Y", C.影响力分成, "成交", 50, "算法算")
        ck("算法算的必须写明算法名", "放行了", "拒绝")
    except ValueError:
        ck("算法算的必须写明算法名", "拒绝", "拒绝",
           "  ← 末次/W型/Shapley 算出来都是一个百分比,长得一模一样")

    # ⑥ 来源都要能分开
    src = dict(c.execute("select source, count(*) from deal_credit group by source").fetchall())
    缺 = [k for k in ("人工填", "规则算", "算法算") if k not in src]
    ck("三种来源都有样本", "都有" if not 缺 else f"缺 {'、'.join(缺)}", "都有",
       f"  ← {src}。缺的话跑 tools/backfill_fixtures.py")

    print()
    if bad:
        print(f"{R}❌ 成交归因 {bad} 处不符合预期{D}")
        return 1
    print(f"{G}✅ 成交归因全部符合预期{D}")
    print(f"    **这一版只记录,不算成交率** —— 算率要先有「订单追得到接待」(P18,断着)")
    print(f"    和触点数据(现在几乎没有)。结构先立住,W 型和 Shapley 都在它上面算。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
