#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同名字段必须同义 —— **一个列名在几张表里,存的得是同一种东西**。

    python3 backend/samekey_check.py

## 这条防的是什么

`pattern.xz` 存的是形制**编码**(XZ01),`product_custom.xz` 存的是形制**名称**(唐制齐胸襦裙)。
同一个列名,两张表存的是两种东西,而**两边都是 TEXT,查出来完全看不出差别**。

负责商机那条线的会话今天踩了:写场合推导时用 `coalesce(t.xz, pc.xz)`,
255 个商品取出来全是编码,一个都匹配不上「唐制 / 宋制 / 明制」——
**推导恒出 0 条,而脚本照样报成功**。

> 「推导没匹配上」和「本来就没有可推的」,在结果上长得一模一样,都是 0。

## 为什么不是「扫所有同名列」

全库 72 张表、89 个列名出现在多张表里,**其中 19 个取值形状不同** ——
而绝大多数是对的:`id` 在每张表里本来就该是不同形状,`note` 是自由文本。
照着扫会报 19 条,**而真问题只有一条**。

> **一个会误报的检查,比没有这个检查更糟** —— 它会让人去改本来就对的东西。
> (这句话是那个会话今天用两次误报换来的。)

所以这里只盯**指向同一个域的列**:`xz` 指向形制、`pattern` 指向版型、`spu` 指向商品……
每个域有一张权威表和两把钥匙(编码 / 名称),规则是:

  **每张表用哪把钥匙,必须在下面的登记表里写明,而且和库里的实情一致。**

新表用了这个列名却没登记 → 红。登记写的是编码而库里存的是名称 → 红。
**登记表是显式的,不是扫出来的** —— 扫出来的登记表会把新冒出来的错当成现状接受。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("把登记表里 product_custom.xz 的钥匙改成「编码」(和库里存的名称对不上)",
     "每张表用的钥匙和登记的一致"),
    ("在登记表里删掉 pattern.xz 这一行(有表用了这个列名却没登记)",
     "用到这些列名的表都登记了"),
]

# 域 → (权威表, 编码列, 名称列, 别名列)
域 = {
    "xz": ("xingzhi", "code", "name", "alias"),
    "pattern": ("pattern", "code", "name", None),
}

# **登记表**:哪张表的这个列用哪把钥匙。写明白,别让人去猜。
# ⚠️ `product_custom.xz` 用的是**名称**,和 `pattern.xz` 的编码不是一把钥匙 ——
# 这是历史事实,不是笔误:定制品的形制是人按名字一条条填的(见 fix_product_pattern.py)。
# 留着它、但**把它登记出来**,比改名动十六个文件的读法安全;
# 代价是 join 这两张表时必须先转换,所以这里把代价写在表上,让下一个人看得见。
登记 = {
    ("pattern", "xz"): "编码",
    ("product_custom", "xz"): "名称",         # ← 和上面那行不是一把钥匙,join 前先转
    ("product", "pattern"): "编码",
    ("size_spec", "pattern"): "编码",
    ("pattern_piece", "pattern"): "编码",
    ("pattern_bom", "pattern"): "编码",
    ("pattern_rev", "pattern"): "编码",
    ("scheme", "pattern"): "编码",
    ("scheme", "xz"): "编码",                 # 方案表用编码,和 product_custom 的名称不是一把
}

失败 = []


def 报(名, ok, 说明=""):
    print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
    if not ok:
        失败.append(名)


def 判钥匙(c, t, col, 域名):
    """这张表这一列,实际存的是编码还是名称?**不够一致就明说混用。**"""
    权威, 编码列, 名称列, 别名列 = 域[域名]
    codes = {r[0] for r in c.execute(f"SELECT {编码列} FROM {权威}")}
    names = {r[0] for r in c.execute(f"SELECT {名称列} FROM {权威}")}
    if 别名列:
        for r in c.execute(f"SELECT {别名列} FROM {权威} WHERE {别名列} IS NOT NULL AND {别名列}<>''"):
            names |= {x.strip() for x in str(r[0]).replace("、", ",").split(",") if x.strip()}
    vs = [r[0] for r in c.execute(f"SELECT {col} FROM {t} WHERE {col} IS NOT NULL AND {col}<>''")]
    if not vs:
        return None, 0
    n编码 = sum(1 for v in vs if v in codes)
    n名称 = sum(1 for v in vs if v in names)
    if n编码 == len(vs):
        return "编码", len(vs)
    if n名称 == len(vs):
        return "名称", len(vs)
    return f"混用(编码 {n编码} / 名称 {n名称} / 共 {len(vs)})", len(vs)


def main():
    c = sqlite3.connect(DB)
    print("同名字段必须同义")
    表 = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    用到 = []
    for t in 表:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
        for col in 域:
            if col in cols:
                用到.append((t, col))
    报("样本量:用到这些列名的表", len(用到) >= 5, f"{len(用到)} 处")

    漏登记 = [f"{t}.{col}" for t, col in 用到 if (t, col) not in 登记]
    报("用到这些列名的表都登记了", not 漏登记,
       "、".join(漏登记[:4]) + " —— **新表用了这个列名就得登记用哪把钥匙**"
       if 漏登记 else f"{len(用到)} 处都在登记表里")

    不符, 明细 = [], []
    for (t, col), 应 in 登记.items():
        if (t, col) not in 用到:
            不符.append(f"{t}.{col} 登记了但表里没这一列")
            continue
        实, n = 判钥匙(c, t, col, col)
        明细.append(f"{t}.{col}={实}({n})")
        if 实 and 实 != 应:
            不符.append(f"{t}.{col}:登记 {应},实际 {实}")
    报("每张表用的钥匙和登记的一致", not 不符, "；".join(不符[:3]) or " · ".join(明细))

    # 同一个域里出现了两把钥匙 → 不是错,但**必须是被登记过的**,
    # 因为 join 的时候一边是 XZ01 一边是「唐制齐胸襦裙」,**join 不出错,只出空**
    for 域名 in 域:
        钥 = {应 for (t, col), 应 in 登记.items() if col == 域名}
        if len(钥) > 1:
            print(f"     ℹ️ 「{域名}」域里有两把钥匙({'/'.join(sorted(钥))})—— "
                  f"join 之前必须转换,**join 不会报错,只会返回空**")

    print((f"{R}❌ 同名字段 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 同名字段都同义(或登记在案){D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
