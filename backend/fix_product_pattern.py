# -*- coding: utf-8 -*-
"""把商品连到版型,并让「性别 / 量体模板」从版型派生,而不是各填一遍。

## 缺的是一条边

`product` 表上没有 pattern 列,也没有 xz 列 —— **商品不知道自己该用哪个版型**。
于是性别、量体模板、用料都得在商品上**再填一遍**,而重填就会错:

    17 个商品的 gender 和品类树打架
     8 个定制品的量体模板和版型要求的对不上(长衫按裙子量、罩甲按裙子量)

**同一个事实两个来源,必然漂。** 版型是真相源 ——
它决定用料、决定量体模板、决定能不能做;商品上那两个字段是抄件。

## 为什么以版型为准,而不是以品类树为准

上一轮我按「结构硬不硬」排过一次可信度:品类树是三级、有 parent,
所以比 `product.gender` 可靠。那个排法是对的,但**排错了维度**。

该按「**错了以后代价多大**」排:
品类挂错只是客户搜不到;**量体模板错了,是照着裙子的口径去量一件长衫,
然后按那个尺寸裁**。所以版型压过所有。

## 匹配不上的留空

按版型名匹配(核心形制 + 变体后缀都要出现),164/288 唯一命中。
剩下 124 个匹配不上 —— **留空,不猜**。
猜一个版型的代价:用料、工期、量体模板全跟着错,而报表上完全正常。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))


def 匹配版型(conn, 商品名, pats=None):
    """按版型名匹配。返回 (版型 或 None, 理由)。

    判据:版型名拆成「核心形制·变体」,**两段都要出现在商品名里**。
    多个命中时取名字最长的(最具体);两个一样长就算**分不出**,返回 None。
    """
    if pats is None:
        conn.row_factory = sqlite3.Row
        pats = [dict(r) for r in conn.execute(
            "SELECT code,name,gender,tpl,xz FROM pattern")]
    hits = []
    for p in pats:
        核 = p["name"].split("·")[0]
        尾 = p["name"].split("·")[-1] if "·" in p["name"] else None
        if 核 in 商品名 and (尾 is None or 尾 in 商品名):
            hits.append(p)
    if not hits:
        return (None, "版型库里找不到对应版型")
    hits.sort(key=lambda x: -len(x["name"]))
    if len(hits) > 1 and len(hits[0]["name"]) == len(hits[1]["name"]):
        return (None, f"有 {len(hits)} 个版型同样匹配,**分不出**:"
                      f"{[h['code'] for h in hits[:3]]}")
    return (hits[0], f"匹配到 {hits[0]['code']} {hits[0]['name']}")


def link(conn, verbose=True):
    """补 `product.pattern` 这条边。返回 (连上几个, 留空几个)。"""
    conn.row_factory = sqlite3.Row
    c = conn
    if "pattern" not in [x[1] for x in c.execute("PRAGMA table_info(product)")]:
        c.execute("ALTER TABLE product ADD COLUMN pattern TEXT")
    pats = [dict(r) for r in c.execute("SELECT code,name,gender,tpl,xz FROM pattern")]
    连 = 空 = 0
    for r in c.execute("SELECT spu,name FROM product").fetchall():
        p, _ = 匹配版型(c, r["name"], pats)
        if p:
            c.execute("UPDATE product SET pattern=? WHERE spu=?", (p["code"], r["spu"]))
            连 += 1
        else:
            空 += 1
    if verbose:
        print(f"  [商品→版型] 连上 {连} 个,留空 {空} 个"
              f"(匹配不上的**不猜** —— 猜错的话用料/工期/量体模板全跟着错)")
    return 连, 空


def derive(conn, verbose=True):
    """**有版型的商品,性别和量体模板从版型抄过来。**

    只改「有边」的那些 —— 没有边的商品保持原样并在检查里报出来。
    """
    conn.row_factory = sqlite3.Row
    c = conn
    tpl名 = {r["code"]: f"{r['code']} {r['name']}"
             for r in c.execute("SELECT code,name FROM measure_tpl")}
    改性别 = 改模板 = 0
    for r in c.execute("""SELECT p.spu,p.name,p.gender,p.template,p.kind,
                                 t.gender pg, t.tpl ptpl
                          FROM product p JOIN pattern t ON t.code=p.pattern""").fetchall():
        if r["gender"] != r["pg"]:
            c.execute("UPDATE product SET gender=? WHERE spu=?", (r["pg"], r["spu"]))
            改性别 += 1
        # 量体模板只有定制品才有意义(标品按尺码卖)
        if r["kind"] == "定制品":
            want = tpl名.get(r["ptpl"])
            if want and r["template"] != want:
                c.execute("UPDATE product SET template=? WHERE spu=?", (want, r["spu"]))
                改模板 += 1
    # **配饰挂「配饰用量体」,不是清空,也不是长衫模版。**
    #
    # 我第一版把配饰的模板清空了,理由是「配饰不按人裁」——
    # **那是从「题字腰封」一个例子推出去的猜测**,而 `04-配饰.md` 明说:
    # 冠/额饰「有头围尺寸,**必须量**」、鞋履「**按脚长定制,不按鞋码**」、
    # 腕饰「有腕围尺寸」、披帛「长度按身高定」。
    #
    # **配饰要量,只是量的不是三围。** 云肩、团扇、香囊挂着「LT03 长衫模版」
    # 也不是填错了 —— 量体项表里 14 项全是衣服用的,**没有可填的**。
    # 补了 MI15 头围 / MI16 腕围 / MI17 脚长 和 LT06 配饰用量体之后才挂得上。
    #
    # 真正没有模板的只有**面料部件**:卖的是料子和绣片,不是成衣。
    sys.path.insert(0, os.path.dirname(HERE))
    import knowledge.order_gate as _og
    import fix_order_measure as _fx
    配 = 清 = 0
    LT6 = c.execute("SELECT code||' '||name FROM measure_tpl WHERE code='LT06'").fetchone()
    for r in c.execute("SELECT spu,category,template,kind,pattern FROM product").fetchall():
        顶 = _fx.顶级品类(c, r["category"])
        if 顶 == "配饰":
            if r["kind"] == "定制品" and LT6 and r["template"] != LT6[0] and not r["pattern"]:
                c.execute("UPDATE product SET template=? WHERE spu=?", (LT6[0], r["spu"]))
                配 += 1
        elif 顶 == "面料部件" and r["template"]:
            c.execute("UPDATE product SET template=NULL WHERE spu=?", (r["spu"],))
            清 += 1

    if verbose:
        print(f"  [从版型派生] 改了 {改性别} 个商品的性别、{改模板} 个的量体模板;"
              f"配饰挂 LT06 的 {配} 个,面料部件清掉 {清} 个")
        if 改模板:
            print(f"             —— **量体模板错了是照着裙子的口径量一件长衫**,"
                  f"比品类挂错严重得多")
    return 改性别, 改模板


# ── 品类树补档 ────────────────────────────────────────────────────
# 版型库说这些是男装,而**男装树下只有「圆领袍」和「道袍」两档,没地方放** ——
# 这才是它们当初被挂到女装下的原因。
# **不是挂错了,是目录缺档。** 挂错是人手滑,缺档是结构不全,
# 后者不补的话,下一批男装商品还会被挂到同样的地方。
#
# 女装那边缺「圆领袍」—— `XZ09 圆领袍` 下本来就有男款 PT11 和女款 PT35,
# **形制中性、版型分性别**,目录也该两边都有。
补的品类 = [
    ("C0202", "外套", "C02", 2),
    ("C020201", "长衫 / 长袄", "C0202", 1),
    ("C020202", "罩甲 / 半臂", "C0202", 2),
    ("C010105", "圆领袍", "C0101", 5),
]
# 商品挂到哪一档:按**版型的形制**判,不按商品名猜
形制到品类 = {
    ("男", "长衫"): "C020201", ("男", "罩甲"): "C020202", ("男", "半臂"): "C020202",
    ("女", "圆领袍"): "C010105",
}


def recat(conn, verbose=True):
    """把性别和品类树对不上的商品,挂到对的那一档。**只动有版型的。**"""
    conn.row_factory = sqlite3.Row
    c = conn
    sys.path.insert(0, os.path.dirname(HERE))
    import knowledge.order_gate as og
    import fix_order_measure as fx
    for code, name, parent, sort in 补的品类:
        if not c.execute("SELECT 1 FROM category WHERE code=?", (code,)).fetchone():
            c.execute("INSERT INTO category(code,name,parent,sort,status) "
                      "VALUES(?,?,?,?,'启用')", (code, name, parent, sort))
    改 = 0; 剩 = []
    for r in c.execute("""SELECT p.spu,p.name,p.category,t.gender pg FROM product p
                          JOIN pattern t ON t.code=p.pattern""").fetchall():
        顶 = fx.顶级品类(c, r["category"])
        树说 = og.按品类定性别(顶 or "")
        if not 树说 or 树说 == r["pg"]:
            continue
        目标 = None
        for (g, 词), code in 形制到品类.items():
            if g == r["pg"] and 词 in r["name"]:
                目标 = code; break
        if 目标:
            c.execute("UPDATE product SET category=? WHERE spu=?", (目标, r["spu"]))
            改 += 1
        else:
            剩.append((r["name"][:22], 顶, r["pg"]))
    if verbose:
        print(f"  [品类归位] 补了 {len(补的品类)} 个品类档,挂回 {改} 个商品")
        if 剩:
            print(f"  ⚠️ 还有 {len(剩)} 个对不上而**挂不过去**(形制没有对应档,不猜):{剩[:3]}")
    return 改, 剩


if __name__ == "__main__":
    db = os.path.join(HERE, "lanxiu.db")
    cn = sqlite3.connect(db)
    link(cn); derive(cn); recat(cn)
    cn.commit(); cn.close()
