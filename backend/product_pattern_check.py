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


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ("把「圆领袍」加回 XZ09 明制圆领袍的别名(它是通称,同时也是童款圆领袍、"
     "唐制圆领襕袍的说法)", "通称不许当某一个形制的独占别名"),
    ('把一个商品连到一个不存在的版型上',
     '商品连的版型都真实存在'),
]

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

    # ⑤·前 **`product_custom.xz` 存的是形制「名字」,必须解析得出来。**
    #    这条是补上去的,补的原因是我自己差点栽:把 XZ09 从「圆领袍」改名成
    #    「明制圆领袍」之后,`product_custom` 里 7 个商品那一格还写着「圆领袍」——
    #    **而 check.sh 全绿**。没断裂纯属运气:我顺手给 XZ09 留了别名「圆领袍」,
    #    正好接上了。要是没留,那 7 个商品的形制就指向空处,
    #    而它们在报表上照样是「配置齐全」。
    #
    #    存名字不存编码本来就危险(改名即断链),但这一列是给人看和给模型读的,
    #    改成编码会让配置页变成一串 XZ 码。**那就至少把它钉住** ——
    #    「删不掉的副本要变成被钉住的缓存」。
    野xz = []
    _名 = {}
    for _c, _n, _a in c.execute("SELECT code,name,alias FROM xingzhi"):
        _名[_n] = _c
        for _x in (_a or "").split("、"):
            if _x.strip(): _名[_x.strip()] = _c
    for _spu, _pn, _xz in c.execute(
            "SELECT pc.spu,p.name,pc.xz FROM product_custom pc "
            "JOIN product p ON p.spu=pc.spu WHERE pc.xz IS NOT NULL AND pc.xz!=''"):
        if _xz not in _名:
            野xz.append(f"{_pn}:「{_xz}」在形制表里查不到")
    # ⑤·前之二 **一个通称,不许被登记成某一个形制的独占别名。**
    #    上面那条注释写着「圆领袍」这个别名是怎么来的:当年 XZ09 改名之后
    #    留着它接住断链。接住了,**也顺带把歧义消掉了** —— 而那是副作用,
    #    没有人是冲着消歧去的。
    #
    #    代价 2026-09-21 才显形:「圆领袍」同时是明制圆领袍、童款圆领袍的通称,
    #    也是唐制圆领襕袍的口语说法。定制表里谁写通称,谁就被**悄悄判成明制**。
    #    真撞上了一款:「女式圆领」唐制袍挂着唐制圆领襕袍的版,
    #    而唐制膝部有横襕、明制没有,**版不一样,做出来是另一件衣服**。
    #
    #    > 一个通称被独占给某一个朝代,消掉的不是歧义,
    #    > 是**「这里有歧义」这件事本身** —— 从此没有任何信号提示人去问。
    #
    #    判据不看词,看结构:**这个别名如果同时是两个以上形制名称的一部分,
    #    它就是通称。** 43 个形制实测只命中这一条,零误报。
    通称 = []
    _全名 = [r[0] for r in c.execute("SELECT name FROM xingzhi")]
    for _c2, _n2, _a2 in c.execute(
            "SELECT code,name,alias FROM xingzhi WHERE alias IS NOT NULL AND alias!=''"):
        for _al in [x.strip() for x in _a2.replace("、", ",").split(",") if x.strip()]:
            命中 = [m for m in _全名 if _al in m]
            if len(命中) >= 2:
                通称.append(f"{_c2} {_n2} 的别名「{_al}」同时是 {len(命中)} 个形制的一部分"
                            f"({'、'.join(命中[:3])})")
    ck("通称不许当某一个形制的独占别名", not 通称,
       c.execute("SELECT COUNT(*) FROM xingzhi WHERE alias IS NOT NULL AND alias!=''")
        .fetchone()[0],
       ("；".join(通称[:2]) + " —— **写通称的人会被悄悄判成其中一个**,"
        "而解析成功和解析正确长得一模一样。别名只收真正的一对一别称,"
        "通称要让它报「对应多条」" if 通称 else
        "别名都是一对一的别称,没有通称混进来"))

    ck("product_custom.xz 都能解析到形制", not 野xz,
       c.execute("SELECT COUNT(*) FROM product_custom WHERE xz IS NOT NULL AND xz!=''")
        .fetchone()[0],
       ("；".join(野xz[:2]) if 野xz else
        "存的是名字不是编码 —— **改一次形制名就可能断链**,而断了不会报错"))

    # ⑥ **名字、`unit`、裁片三者必须说同一件事。**
    #    「多件」这件事库里有三处在讲:商品名(套装 / 亲子 / 两件)、
    #    `product.unit`(件 / 套)、版型的裁片(有没有下装片)。三处一不齐就出错:
    #
    #      名字说多件而 unit='件'  → 一个版型看起来刚好够,没人觉得缺
    #      unit='套' 而裁片只有上装 → 车间照版型下料,**裙子不会被裁出来**
    #
    #    ⚠️ 我第一版把这件事诊断成「`product.pattern` 是单值,装不下多件」——
    #    **错了**。单值装得下:PT01 齐胸襦裙·标准的裁片里上襦和裙片都有,
    #    7 个 unit='套' 的襦裙商品全是这么挂的。
    #    **问题从来不是模型装不下,是三处没对齐。**
    import fix_product_pattern as _FPP
    名不齐, 片不齐 = [], []
    for _spu, _pn, _u, _pt in c.execute(
            "SELECT spu,name,unit,pattern FROM product"):
        _多 = any(w in _pn for w in _FPP.多件词)
        if _多 and _u != "套":
            名不齐.append(f"{_pn}(名字说多件,unit='{_u}')")
        if _u == "套" and _pt:
            _ps = [x[0] for x in c.execute(
                "SELECT name FROM pattern_piece WHERE pattern=?", (_pt,))]
            if not any(any(k in x for k in _FPP.下装裁片词) for x in _ps):
                片不齐.append(f"{_pn} → {_pt} 裁片只有上装({'/'.join(_ps) or '空'})")
    ck("名字说多件的商品,unit 必须是「套」", not 名不齐,
       c.execute("SELECT COUNT(*) FROM product").fetchone()[0],
       ("；".join(名不齐[:3]) if 名不齐 else
        "`unit` 这一列早就在承载「一件还是一套」—— 字段在那儿,就得和名字对齐"))
    ck("unit='套' 的商品,版型裁片必须覆盖下装", not 片不齐,
       c.execute("SELECT COUNT(*) FROM product WHERE unit='套'").fetchone()[0],
       ("；".join(片不齐[:2]) if 片不齐 else
        "车间照版型下料 —— 裁片里没有裙片,裙子就不会被裁出来"))

    # ⑦ **人工裁定表里的东西必须真实存在。**
    #    这张表是业务拍板的落点(`fix_product_pattern.人工裁定`),
    #    键是**商品名**、值是版型编码 —— **两头都会因为改名而断**,
    #    而断了不报错:link() 查不到就默默走名字匹配,那个商品悄悄退回「待定」。
    #    和 `product_custom.xz` 是同一个病,所以用同一种办法钉住。
    野裁 = []
    for _nm, (_pt, _why) in _FPP.人工裁定.items():
        if not c.execute("SELECT 1 FROM product WHERE name=?", (_nm,)).fetchone():
            野裁.append(f"「{_nm}」这个商品不存在(改名了?)")
        elif not c.execute("SELECT 1 FROM pattern WHERE code=?", (_pt,)).fetchone():
            野裁.append(f"「{_nm}」指的版型 {_pt} 不存在")
    ck("人工裁定表两头都存在", not 野裁, len(_FPP.人工裁定),
       ("；".join(野裁[:2]) if 野裁 else
        "拍板结论也是主数据 —— **只落在库里,下次重建就悄悄退回「待定」**"))

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
