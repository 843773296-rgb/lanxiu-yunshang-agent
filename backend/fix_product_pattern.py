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


# 变体后缀 —— 版型名里 `·` 后面那一段。**不带后缀就是标准款**,
# 这是命名约定(变体款都带后缀),不是猜。
变体后缀 = ("标准", "加长", "改良通勤", "长款", "短款", "阔褶", "坦领",
            "六破长裙", "长衫版", "男款", "女款", "袄", "加大")


def 匹配形制(conn, 商品名, xzs=None):
    """按形制表匹配。返回 (形制 或 None, 理由)。

    三层依次试,**每层都要求唯一**:
      ① 形制全名(「宋制褙子」)
      ② 别名(XZ04 明制立领长衫 的别名是「立领袄」)
      ③ 去掉朝代前缀的器物名(「宋制褙子」→「褙子」)——
         商品名常写成「宋制**对襟**褙子」,全名对不上而器物名对得上

    两个形制的命中长度一样时返回 None:**一样长就是分不出**。
    """
    if xzs is None:
        conn.row_factory = sqlite3.Row
        xzs = [dict(r) for r in conn.execute("SELECT code,name,alias FROM xingzhi")]
    hits = []
    for z in xzs:
        names = [z["name"]] + ([a.strip() for a in (z["alias"] or "").split("、")]
                               if z["alias"] else [])
        got = None
        for n in names:
            if n and n in 商品名:
                got = len(n); break
        if got is None:
            核 = z["name"]
            for pre in ("唐制", "宋制", "明制", "改良汉元素", "改良"):
                if 核.startswith(pre):
                    核 = 核[len(pre):]; break
            if 核 and 核 in 商品名:
                got = len(核)
        if got:
            hits.append((z, got))
    if not hits:
        return (None, "形制表里也认不出")
    hits.sort(key=lambda x: -x[1])
    if len(hits) > 1 and hits[0][1] == hits[1][1]:
        return (None, f"{len(hits)} 个形制同样匹配,**分不出**")
    return (hits[0][0], f"形制 {hits[0][0]['code']} {hits[0][0]['name']}")


def 按形制选版型(conn, 商品名, 商品性别, 形制, pats=None, 顶级品类名=None):
    """形制定了之后,在它的版型里挑。返回 (版型 或 None, 理由)。

    依次收窄:**变体后缀 → 性别**,收到只剩一个才算定。
    """
    if pats is None:
        conn.row_factory = sqlite3.Row
        pats = [dict(r) for r in conn.execute(
            "SELECT code,name,gender,tpl,xz FROM pattern")]
    cand = [p for p in pats if p["xz"] == 形制["code"]]
    if not cand:
        return (None, f"形制 {形制['code']} 下没有版型")
    v = [x for x in 变体后缀 if x in 商品名]
    if v:
        c2 = [p for p in cand if any(x in p["name"] for x in v)]
        if c2: cand = c2
    else:
        # **不带变体后缀 = 标准款。** 变体款的名字都带后缀,这是命名约定。
        c2 = [p for p in cand if "标准" in p["name"] or "·" not in p["name"]]
        if c2: cand = c2
    if 商品性别 in ("男", "女", "童"):
        c3 = [p for p in cand if p["gender"] == 商品性别]
        if c3: cand = c3
    if len(cand) == 1:
        return (cand[0], f"形制 {形制['code']} + 变体 + 性别 收窄到唯一")
    # **顶级品类能排掉成人/童款的歧义。**
    # 「男装圆领常服袍」的顶级品类是男装,而 `XZ40 童款圆领袍` 的版型是童款 ——
    # 品类树已经说了这不是童装,却还把童款算进候选,那是白留着一条能用的线不用。
    if 顶级品类名 in ("女装", "男装", "童装"):
        要 = {"女装": "女", "男装": "男", "童装": "童"}[顶级品类名]
        c4 = [p for p in cand if p["gender"] == 要]
        if len(c4) == 1:
            return (c4[0], f"形制 {形制['code']} + 顶级品类「{顶级品类名}」收窄到唯一")
    return (None, f"收窄后还剩 {len(cand)} 个版型,**分不出**")


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
    xzs = [dict(r) for r in c.execute("SELECT code,name,alias FROM xingzhi")]
    连 = 空 = 0
    for r in c.execute("SELECT spu,name FROM product").fetchall():
        p, _ = 匹配版型(c, r["name"], pats)
        if not p:
            # **退一步走形制表。** 按版型全名匹配只连上 164/288 ——
            # 「宋制**对襟**褙子」对不上「宋制褙子·标准」,差的就是中间那两个字。
            # 走形制(器物名 + 别名)再按变体和性别收窄,又定下来 62 个。
            z, _ = 匹配形制(c, r["name"], xzs)
            if z:
                g = c.execute("SELECT gender,category FROM product WHERE spu=?",
                              (r["spu"],)).fetchone()
                # **从 fix_order_measure 引,这个模块里没有这个函数。**
                # 我改的时候直接写了裸名字 —— 当场 NameError,
                # 而它是在 seed 半路崩的,**留下一个建了一半的库**。
                import fix_order_measure as _fx2
                顶 = _fx2.顶级品类(c, g["category"]) if g else None
                p, _ = 按形制选版型(c, r["name"], g["gender"] if g else None, z, pats, 顶)
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
