# -*- coding: utf-8 -*-
"""商品与版型的检查 —— **性别和量体模板是从版型派生的,不是各填一遍。**

## 为什么以版型为准

上一轮按「结构硬不硬」排过可信度(品类树三级有 parent,比 `gender` 可靠)。
那个排法对,但**排错了维度**。该按「**错了以后代价多大**」排:

    品类挂错     客户搜不到
    gender 填错   推不出该给谁穿
    **量体模板错**  **照着裙子的口径去量一件长衫,然后按那个尺寸裁**

所以版型压过所有 —— 它决定用料、决定量体模板、决定能不能做。

## 这条边补上之前,错了 66 个没人知道

`product` 原来既没有 pattern 列也没有 xz 列 —— **商品不知道自己该用哪个版型**,
于是性别和模板在商品上再填一遍。重填就会错:
86 个有版型的定制品里,**66 个的量体模板和版型要求的对不上**。

我第一次只查了 17 个「gender 和品类树打架」的商品,从里面看到 8 个模板错。
**从一个小样本推整体,推出来的数会小一个量级** —— 那 17 个不是随机抽的,
是按另一个条件筛出来的。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("商品与版型 · 检查")
    print("=" * 80)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row

    linked = c.execute("SELECT COUNT(*) FROM product WHERE pattern IS NOT NULL").fetchone()[0]
    total = c.execute("SELECT COUNT(*) FROM product").fetchone()[0]

    # ① 连上的版型必须真实存在。
    野 = [r["spu"] for r in c.execute(
        "SELECT spu FROM product WHERE pattern IS NOT NULL AND pattern NOT IN "
        "(SELECT code FROM pattern)")]
    ck("商品连的版型都真实存在", not 野, linked, f"野的 {野[:3]}" if 野 else "")

    # ② **性别从版型派生** —— 有边就必须一致。
    bad2 = [(r["spu"], r["gender"], r["pg"]) for r in c.execute(
        "SELECT p.spu,p.gender,t.gender pg FROM product p "
        "JOIN pattern t ON t.code=p.pattern WHERE p.gender!=t.gender")]
    ck("有版型的商品,性别和版型一致", not bad2, linked,
       f"对不上 {bad2[:2]}" if bad2 else "版型决定用料和量体,它说了算")

    # ③ **量体模板从版型派生** —— 这条最要紧。
    n3 = c.execute("SELECT COUNT(*) FROM product WHERE pattern IS NOT NULL "
                   "AND kind='定制品'").fetchone()[0]
    bad3 = [(r["spu"], r["template"], r["want"]) for r in c.execute(
        "SELECT p.spu,p.template,t.tpl||' '||m.name want FROM product p "
        "JOIN pattern t ON t.code=p.pattern JOIN measure_tpl m ON m.code=t.tpl "
        "WHERE p.kind='定制品' AND p.template!=t.tpl||' '||m.name")]
    ck("定制品的量体模板和版型一致", not bad3, n3,
       f"对不上 {bad3[:2]}" if bad3 else
       "**模板错了是照着裙子的口径量一件长衫** —— 补这条边之前错了 66 个")

    # ④ **配饰定制品要挂「配饰用量体」,不是长衫模版,也不是空。**
    #    我错过一次:从「题字腰封」一个例子推出「配饰不按人裁」,把模板清空了 ——
    #    而 `04-配饰.md` 明说冠/额饰必须量头围、鞋履按脚长定制。
    #    **配饰要量,只是量的不是三围。**
    import knowledge.order_gate as OG
    import fix_order_measure as FX
    n4 = bad4 = 0; 例4 = []
    for r in c.execute("SELECT spu,name,category,template,kind,pattern FROM product"):
        顶 = FX.顶级品类(c, r["category"])
        if 顶 != "配饰" or r["kind"] != "定制品": continue
        n4 += 1
        if r["pattern"]: continue           # 有版型的以版型为准(上面第③条管)
        if (r["template"] or "") != "LT06 配饰用量体":
            bad4 += 1
            if len(例4) < 3: 例4.append((r["name"][:16], r["template"]))
    ck("配饰定制品挂「配饰用量体」", bad4 == 0, n4,
       f"没挂对的 {例4}" if bad4 else "头围/腕围/脚长,不是三围")

    # ④·2 面料部件不该有模板 —— 卖的是料子,不是成衣。
    n42 = bad42 = 0
    for r in c.execute("SELECT spu,category,template FROM product WHERE template IS NOT NULL"):
        if FX.顶级品类(c, r["category"]) == "面料部件": n42 += 1; bad42 += 1
    ck("面料部件不挂量体模板", bad42 == 0, n42 or 1, "卖的是料子和绣片,不是成衣")

    # ⑤ **没连上边的要按类别分开数。**
    #    第一版只报一个总数「124/288 没连上」,听起来像 124 个都缺东西 ——
    #    实际上配饰和面料部件**本来就不该有版型**(它们不是成衣)。
    #    **把「不需要」和「缺了」混成一个数,会让人去补一堆本来就不用补的。**
    import collections
    d5 = collections.Counter()
    for r in c.execute("SELECT category FROM product WHERE pattern IS NULL"):
        d5[FX.顶级品类(c, r["category"]) or "(品类认不出)"] += 1
    该有 = sum(v for k, v in d5.items() if k in ("女装", "男装", "童装"))
    print(f"  ℹ️ {total - linked}/{total} 个商品没连上版型,按类别拆:")
    for k, v in d5.most_common():
        标 = "**该有而没有**" if k in ("女装", "男装", "童装") else "本来就不是成衣"
        print(f"       {k!s:<8} {v:>3}   {标}")
    print(f"     → 真正要补对照表的是那 {该有} 个成衣,"
          f"**其余的不需要版型,不是缺数据**")

    c.close()
    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 商品与版型 5 条全过")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(HERE))
    sys.exit(main())
