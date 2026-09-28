#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""供应商的检查(业务 2026-09-24 拍「有,分两类」;09-28 落地 10 家)。

## 这张表补的是一个**指向空处的引用**

2026-09-28 之前:`sku.supplier_code` 有 659 个值,**659 个 SKU 对应 659 个不同的码**,
而且**没有供应商表**。字段长得像外键,它指向的东西不存在 ——
采购、比价、供应商评估三块都做不起来,而**没有任何东西会报错**。

> 数据看着丰富,信息量是零。**一个 SKU 一个供应商,那不是供应链,那是噪声。**

## ⚠️ 这里最容易写错的一条判据:「不该挂的没挂」

168 个工艺里**只有缂丝 / 妆花 / 苏绣真外发**,其余自己做。
所以 `craft.supplier_code` **空是正常的,而且是多数**。

判据要是写成「这一列不许为空」,它会逼着人给「缝制」也挂一个供应商 ——
那是**判据在制造假数据**。所以这里判两头:该挂的挂了、**不该挂的没挂**。

同一个形状:`sku.supplier_code` **定制品本来就不该有**(它不是进的货,是自己做的)。
「没有供应商编码」和「还没填供应商编码」是两回事,而前者是正常的。

## 两类跟的指标**不合成一个分**

面料跟**批次色差**(color_var),外发跟**返工率**(defect_rate)。
合成一个「综合评分」会把「料到得慢」和「绣错了」压成同一个数 ——
而这两件事的下一步完全不同(换供应商 vs 把绣样口径画清楚)。
所以判据要求:**每一家只填自己那一类的指标,另一类必须为空。**
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
外发的工艺 = ("KF01", "KF02", "KF03")        # 缂丝 / 妆花 / 苏绣 —— 只有这三个真外发
FAIL, N = [], [0]


def ck(名, 取, 验了, 说=""):
    N[0] += 1
    try:
        ok = bool(取())
    except Exception as e:
        ok, 说 = False, f"{说}  ← **崩了**:{type(e).__name__}: {e}"
    print(f"  {'✅' if ok else '❌'} {名}(验了 {验了}){('  ' + str(说)[:170]) if 说 else ''}")
    if not ok: FAIL.append(名)


def main():
    print("供应商 · 检查")
    print("=" * 92)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='supplier'").fetchone():
        print("\033[31m❌ 没有 supplier 表 —— 后面一条都没验\033[0m"); sys.exit(1)

    sup = {r["code"]: dict(r) for r in c.execute("SELECT * FROM supplier")}
    ck("样本量:供应商表不是空的(**扫不到 ≠ 都对**)", lambda: len(sup) >= 2, f"{len(sup)} 家")
    两类 = {r["kind"] for r in sup.values()}
    ck("只有业务定的那两类(面料 / 外发),没有第三类混进来",
       lambda: 两类 <= {"面料", "外发"}, f"{len(sup)} 家", f"实际:{sorted(两类)}")
    ck("两类都有人(**只有一类的话,「分两类」这件事在数据上没有对象**)",
       lambda: 两类 == {"面料", "外发"}, f"{len(sup)} 家",
       "、".join(f"{k} {sum(1 for x in sup.values() if x['kind']==k)} 家" for k in sorted(两类)))

    # ── 两类的质量指标不许串 ────────────────────────────────────────
    串 = [x["code"] for x in sup.values()
          if (x["kind"] == "面料" and x["defect_rate"] is not None)
          or (x["kind"] == "外发" and x["color_var"] is not None)]
    ck("面料只填色差、外发只填返工率(**两类的质量不合成一个分**)",
       lambda: not 串, f"{len(sup)} 家",
       f"这几家串了:{串}" if 串 else
       "合成一个「综合评分」会把「料到得慢」和「绣错了」压成同一个数,而下一步完全不同")
    缺 = [x["code"] for x in sup.values()
          if (x["kind"] == "面料" and x["color_var"] is None)
          or (x["kind"] == "外发" and x["defect_rate"] is None)]
    ck("每一家都填了**自己那一类**的质量指标", lambda: not 缺, f"{len(sup)} 家", 缺 or "")
    ck("每一家都有工期(**不是承诺,是历史均值**)",
       lambda: not [x for x in sup.values() if not x["lead_days"]], f"{len(sup)} 家", "")

    # ── 引用完整性:挂出去的码都得指向真的那一家 ──────────────────────
    for 表, 列 in (("material", "supplier_code"), ("craft", "supplier_code"),
                   ("sku", "supplier_code")):
        野 = [r[0] for r in c.execute(
            f"SELECT DISTINCT {列} FROM {表} WHERE {列} IS NOT NULL AND {列} NOT IN "
            f"(SELECT code FROM supplier)")]
        ck(f"`{表}.{列}` 指向的都是真的那几家(**不是一个指向空处的引用**)",
           lambda 野=野: not 野, 表,
           f"这些码在 supplier 表里没有:{野[:4]}"
           f"{f' ……还有 {len(野)-4} 个(共 {len(野)})' if len(野) > 4 else ''}"
           if 野 else "")

    # ── ⚠️ 两头都要判:该挂的挂了、**不该挂的没挂** ─────────────────
    该挂没挂 = [r[0] for r in c.execute(
        f"SELECT code FROM craft WHERE code IN ({','.join('?'*len(外发的工艺))}) "
        f"AND supplier_code IS NULL", 外发的工艺)]
    不该挂却挂了 = [r[0] for r in c.execute(
        f"SELECT code FROM craft WHERE code NOT IN ({','.join('?'*len(外发的工艺))}) "
        f"AND supplier_code IS NOT NULL", 外发的工艺)]
    n工艺 = c.execute("SELECT COUNT(*) FROM craft").fetchone()[0]
    ck("真外发的那几个工艺都挂上了工坊", lambda: not 该挂没挂, f"{len(外发的工艺)} 个",
       该挂没挂 or "缂丝 / 妆花 / 苏绣")
    ck("**自己做的工艺没被挂上供应商**(判据不许逼出假数据)",
       lambda: not 不该挂却挂了, f"{n工艺 - len(外发的工艺)} 个",
       f"这些不该挂:{不该挂却挂了[:5]}" if 不该挂却挂了 else
       "168 个工艺里只有 3 个真外发 —— **空是正常的,而且是多数**")

    # ── 标品 / 定制品:同一个形状 ───────────────────────────────────
    标缺 = c.execute("SELECT COUNT(*) FROM sku s JOIN product p ON p.spu=s.spu "
                    "WHERE p.kind='标品' AND (s.supplier_code IS NULL OR s.supplier_code='')"
                    ).fetchone()[0]
    定多 = c.execute("SELECT COUNT(*) FROM sku s JOIN product p ON p.spu=s.spu "
                    "WHERE p.kind='定制品' AND s.supplier_code IS NOT NULL").fetchone()[0]
    ck("标品有供应商、定制品没有(**定制品不是进的货,是自己做的**)",
       lambda: 标缺 == 0 and 定多 == 0,
       c.execute("SELECT COUNT(*) FROM sku").fetchone()[0],
       f"标品缺 {标缺} / 定制品多 {定多}" if (标缺 or 定多) else "")

    # ── ⚠️ 原来那个毛病别回来:一个 SKU 一个供应商 ──────────────────
    n码 = c.execute("SELECT COUNT(DISTINCT supplier_code) FROM sku "
                   "WHERE supplier_code IS NOT NULL").fetchone()[0]
    n标 = c.execute("SELECT COUNT(*) FROM sku WHERE supplier_code IS NOT NULL").fetchone()[0]
    ck("标品的供应商是**少数几家**,不是一个 SKU 一家",
       lambda: n码 <= max(3, len(sup)), f"{n标} 个标品 SKU",
       f"{n标} 个 SKU 只用了 {n码} 个供应商码 —— "
       f"**2026-09-28 之前是 659 个 SKU 对应 659 个码**,那是假数据的痕迹"
       if n码 <= max(3, len(sup)) else
       f"{n标} 个 SKU 用了 {n码} 个码 —— 又变回「一个 SKU 一个供应商」了")

    # ── 面料按类目分,不是随机分 ────────────────────────────────────
    # 分错了的表现是「里料从主料商进」—— 在数据上完全合法,只有懂业务的人看得出来。
    # 所以判据钉的是「**同一个类目的面料,供应商必须一致**」:随机分一定会打破它。
    乱 = [r["cat"] for r in c.execute(
        "SELECT cat, COUNT(DISTINCT supplier_code) n FROM material "
        "WHERE supplier_code IS NOT NULL GROUP BY cat HAVING n > 1")]
    n料 = c.execute("SELECT COUNT(*) FROM material WHERE supplier_code IS NOT NULL").fetchone()[0]
    ck("面料是**按类目**分给供应商的,不是随机撒的",
       lambda: not 乱, f"{n料} 种面料",
       f"这几个类目的面料来自多家:{乱} —— 随机分一定打破这条" if 乱 else
       "同一类目一家供 —— **「里料从主料商进」在数据上完全合法,只有人看得出来**")

    print("=" * 92)
    if FAIL:
        print(f"\033[31m❌ 供应商 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 供应商 {N[0]} 条全过({len(sup)} 家:"
          f"面料 {sum(1 for x in sup.values() if x['kind']=='面料')} · "
          f"外发 {sum(1 for x in sup.values() if x['kind']=='外发')})\033[0m")


咬合 = [
    ("把一家面料商的 defect_rate 填上(两类的质量指标串了)",
     "面料只填色差、外发只填返工率"),
    ("给一个自己做的工艺(缝制)挂上供应商", "自己做的工艺没被挂上供应商"),
    ("把某个面料的 supplier_code 改成一个 supplier 表里没有的码",
     "指向的都是真的那几家"),
    ("把标品 SKU 的供应商码改回一个 SKU 一个(恢复 659 那个形状)",
     "标品的供应商是**少数几家**"),
    ("把某个里料改挂到主料商(同一类目来自多家)", "面料是**按类目**分给供应商的"),
]

if __name__ == "__main__":
    main()
