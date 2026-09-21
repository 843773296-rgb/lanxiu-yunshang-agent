#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行级稳定 —— **一行的值只由它自己的业务键决定,不由它排第几决定。**

    python3 fakedata/stable.py            # 拿自测用的已知库量一遍

## 这条防的是什么

工厂原来有三条性质:同种子两次一致 / 换种子换数据 / **增删表不影响其它表**。
第三条做的是**列级隔离**(`rng_for(种子,表,列)`),而每一列内部仍然是
`for i, row in enumerate(rows)` 顺着抽 —— 于是:

  **增删「表」不影响其它表** ✅ 已经有了
  **增删「行」不影响其它行** ❌ 一条都没有

这个缺口在澜绣云裳真的炸了。商品图的颜色按 `插入序号 * 3 + hash(款号)` 取,
改了两行造数据的代码,**38 款里 22 款换了颜色 —— 其中 6 款的图已经交付出去了**。
图在外面已经是事实,数据却自己动了。是用户发现的:「其他的为什么会变色???」

> 假数据的全部价值是「昨天复现 bug 的那批数据,今天还是那批」。
> 一个按行序取值的生成器,**在你往中间插一行的那一刻就把这个价值作废了** ——
> 而它不报错,数据看着一样多、一样像真的。

## 判据:同一批键换个顺序,按键对齐,值必须一样

**不能用「多造一行」来测。** 追加在末尾时,原来那些行的流位置一点没变,
按下标取值的列照样对得上 —— 测了个寂寞。要让**同一个键落到不同的行位**,
所以这里把主键序列整个倒过来再造一遍(`plan["__键序"]="逆"`)。

这正是那起事故的形状:款号还是那些款号,只是在列表里换了位置。

## 批级的列不算漂 —— 但必须**事先登记**

有些列按设计就要看整批行:外键的引用密度形状(哪个父亲带几个孩子)
得把 n 个孩子分完才知道。这类列写在 `gen.批级的` 里。

**登记表是显式的,不是扫出来的。** 扫出来的登记表会把新冒出来的漂移
当成现状接受 —— 和 `backend/samekey_check.py` 是同一个道理。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("把 gen.py 里标量列的 `行rng(seed, 表, 列, 键)` 改回顺着抽的 `r`",
     "每一行的值只由它自己的键决定"),
    ("把 `_边界_按键` 改回按下标洗牌选",
     "每一行的值只由它自己的键决定"),
    ("在「批级的」登记表里加一条本来稳定的列(登记了却没漂)",
     "登记的批级列确实是批级的"),
]


def 比(plan, conn=None, edge_rate=0.05):
    """造两遍(第二遍把键的顺序倒过来),按键对齐逐列比。

    返回 `{表名: {列名: 漂了几行}}`,只收漂了的列。
    """
    import gen as GEN
    正, _ = GEN.generate(plan, conn, edge_rate=edge_rate)
    p2 = dict(plan); p2["__键序"] = "逆"
    逆, _ = GEN.generate(p2, conn, edge_rate=edge_rate)

    漂 = {}
    比过 = 0
    for t, rows in 正.items():
        tp = plan["tables"][t]
        if tp.get("skip") or not rows or not tp.get("pk"):
            continue
        pk = tp["pk"][0]
        b = {r[pk]: r for r in 逆.get(t, [])}
        cols = [c for c in rows[0] if c != pk]
        比过 += len(cols)
        for c in cols:
            n = sum(1 for r in rows
                    if r[pk] in b and b[r[pk]].get(c) != r.get(c))
            if n:
                漂.setdefault(t, {})[c] = n
    return 漂, 比过, 正


def 判(plan, 漂):
    """把漂了的列分成两堆:**登记过的批级列**(正常)和**不该漂的**(红)。"""
    import gen as GEN
    该漂, 不该漂 = [], []
    for t, cs in 漂.items():
        for c, n in cs.items():
            g = plan["tables"][t]["columns"].get(c, {})
            (该漂 if g.get("gen") in GEN.批级的 else 不该漂).append((t, c, n, g.get("gen")))
    return 该漂, 不该漂


def 查(plan, conn=None, 报=print):
    失败 = []

    def ck(ok, 名, 说明=""):
        报(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
        if not ok:
            失败.append(名)

    漂, 比过, 正 = 比(plan, conn)
    该漂, 不该漂 = 判(plan, 漂)

    # **先报样本量。** 空集合上所有性质都成立 ——
    # 「每一列都稳」和「一列都没比到」在输出上长得一模一样。
    ck(比过 >= 10, "样本量:比对的列数", f"{比过} 列 / {len(正)} 张表")

    ck(not 不该漂, "每一行的值只由它自己的键决定",
       "；".join(f"{t}.{c} 漂了 {n} 行(gen={gg})" for t, c, n, gg in 不该漂[:4])
       + " —— **同一批键换个顺序,值就变了**:这一列是按行序取值的"
       if 不该漂 else f"{比过} 列里 {比过 - len(该漂)} 列逐键一致")

    # 反向那一半:登记成批级的,得**真的**是批级的。
    # 只查「漂的有没有登记」是不够的 —— 登记表会慢慢囤积一堆其实早就稳了的豁免,
    # 而囤积的豁免看起来和真豁免一模一样。
    import gen as GEN
    漂过的 = {(t, c) for t, cs in 漂.items() for c in cs}
    有这种列 = {}
    for t, tp in plan["tables"].items():
        if tp.get("skip"):
            continue
        for c, g in tp["columns"].items():
            if g.get("gen") in GEN.批级的:
                有这种列.setdefault(g["gen"], []).append((t, c))
    空登记 = [k for k in GEN.批级的
              if 有这种列.get(k) and not any(x in 漂过的 for x in 有这种列[k])]
    ck(not 空登记, "登记的批级列确实是批级的",
       "、".join(空登记) + " —— **登记了却没漂**:要么它已经稳了(该从登记表里删掉),"
       "要么这次没测到它。豁免囤积起来的样子和真豁免一模一样"
       if 空登记 else
       (f"{len(该漂)} 处按设计看整批({'、'.join(sorted(GEN.批级的))})"
        if 该漂 else "本方案里没有这种列"))

    for t, c, n, gg in 该漂[:3]:
        报(f"     ℹ️ {t}.{c} 漂了 {n} 行 —— 登记在案:{GEN.批级的[gg]}")
    return 失败


def main():
    sys.path.insert(0, HERE)
    import tempfile
    import selftest as ST, schema as S, discover as DI, plan as P

    print("行级稳定 · 同一批键换个顺序,值必须一样")
    db = os.path.join(tempfile.mkdtemp(), "known.db")
    ST.build_known_db(db)
    conn = S.connect(db)
    facts = DI.discover(conn, conn.reflect())
    pl = P.build(facts, scale=1.0)
    失败 = 查(pl, conn)
    print((f"{R}❌ 行级稳定 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 行级稳定{D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
