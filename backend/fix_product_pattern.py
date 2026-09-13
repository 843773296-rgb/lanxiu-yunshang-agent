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


# ── 业务拍板过的商品 → 版型 ──────────────────────────────────────────
# 名字推不出来、而业务看过实物给了结论的,写在这儿。
#
# **为什么要有这张表**:拍板的结论如果只落在库里(改一条 `product.pattern`),
# 下一次重建数据就退回「待定」,而且**退得悄无声息** ——
# 看的人只会以为「这个还没定」,不会知道「定过又丢了」。
# 拍板结果和形制、版型一样是主数据,**要落在源头**。
#
# ⚠️ 这张表只放**业务真的拍过**的。名字能推出来的不许往这儿写 ——
# 写了就等于给那个商品的名字**开了一个永久豁免**:
# 以后名字改错了、形制改名了,它照样指着旧版型,而检查看不出来。
# (`product_pattern_check` 会验这里的商品名和版型都真实存在。)
人工裁定 = {
    # 2026-09-13 业务确认实物是对襟。sku 记着领型=方领,门襟没记 ——
    # 而 XZ22 是库里唯一的方领形制,只有一个版型。
    "「棉麻」明制方领短衫(基础)": ("PT26", "2026-09-13 业务确认实物是对襟"),
    # 2026-09-13 业务确认是**唐制·襕袍**(膝部横襕),不是缺胯袍(两侧开裾)。
    # 按名字推不出来:「女式圆领唐制袍」只对得上「圆领」两个字,
    # 而缺胯 / 襕是这一族的区分项,名字里一个都没有。
    # 配置表那格写的是旧泛称「圆领袍」——**比名字还模糊**,更定不了。
    "「女式圆领」唐制袍": ("PT86", "2026-09-13 业务确认是襕袍(膝部横襕),新建女款版型"),
}


def link(conn, verbose=True):
    """补 `product.pattern` 这条边。返回 (连上几个, 留空几个)。"""
    conn.row_factory = sqlite3.Row
    c = conn
    if "pattern" not in [x[1] for x in c.execute("PRAGMA table_info(product)")]:
        c.execute("ALTER TABLE product ADD COLUMN pattern TEXT")
    pats = [dict(r) for r in c.execute("SELECT code,name,gender,tpl,xz FROM pattern")]
    xzs = [dict(r) for r in c.execute("SELECT code,name,alias FROM xingzhi")]
    # 分档要 key_sizes(它要判「关键尺寸是不是空的」),比上面那份多一列
    xzs全 = [dict(r) for r in c.execute(
        "SELECT code,name,alias,key_sizes FROM xingzhi")]
    连 = 空 = 0
    for r in c.execute("SELECT spu,name FROM product").fetchall():
        # **业务拍过的优先** —— 人看过实物,比任何名字匹配都准。
        裁 = 人工裁定.get(r["name"])
        if 裁:
            c.execute("UPDATE product SET pattern=? WHERE spu=?", (裁[0], r["spu"]))
            连 += 1
            continue
        p, _ = 匹配版型(c, r["name"], pats)
        if not p:
            # **退一步走形制表。** 按版型全名匹配只连上 164/288 ——
            # 「宋制**对襟**褙子」对不上「宋制褙子·标准」,差的就是中间那两个字。
            #
            # ⚠️ **这里原来直接调 `匹配形制`(严格连续子串),于是和
            # `拍板分档()` 成了同一个判定的两套实现。** 我这一整轮
            # 把子序列匹配、别名、`product_custom.xz`、`sku.collar` 全加进了分档,
            # **一条都没进这里** —— 结果待定清单说「库里已记 XZ04,不用拍」,
            # 而 link 说「形制表里也认不出」,版型照样是空的。
            # **清单自己和自己打架**,而且 8 个商品一直挂在那儿。
            #
            # 这和「`enforce` 用日期比、检查用时间戳,差了『当天』那一档」
            # 是同一个病:**两套实现一定会在某一档上分家**。
            # 改成:**link 用分档的结论**,自己不再推一遍。
            g = c.execute("SELECT gender,category FROM product WHERE spu=?",
                          (r["spu"],)).fetchone()
            # **从 fix_order_measure 引,这个模块里没有这个函数。**
            # 我改的时候直接写了裸名字 —— 当场 NameError,
            # 而它是在 seed 半路崩的,**留下一个建了一半的库**。
            import fix_order_measure as _fx2
            顶 = _fx2.顶级品类(c, g["category"]) if g else None
            d = 拍板分档(c, r["name"], 顶, xzs全, spu=r["spu"])
            # **只认「不用拍」那两档。** 要选一个 / 省了区分项 / 表里没有
            # 都是**人该看一眼**的,自动挂上去等于替人拍板 ——
            # 而「猜对了没奖励,猜错了用料工期量体全错,报表上完全正常」。
            if d["档位"] in ("库里已记", "确定") and len(d["候选"]) == 1:
                p, _ = 按形制选版型(c, r["name"], g["gender"] if g else None,
                                    d["候选"][0], pats, 顶)
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
# 女装那边缺「圆领袍」—— `XZ09 明制圆领袍` 下本来就有男款 PT11 和女款 PT35,
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


# ── 拍板要分档 ──────────────────────────────────────────────────────
# 第一版工具把 22 个待定商品**全部归成「认不出」**,于是给出的结论只有一句
# 「这些形制我们做不做」。那句话本身没错,但它**把四种完全不同的决定压成了一种**,
# 看的人无从下手 —— 这和「分母为零不给比率」是同一类毛病:
# **一个笼统的答案看起来像个答案,其实什么都没说。**
#
# 分档之后才看得出:22 个里只有一部分真的要业务拍,其余是数据维护。

档位 = ("库里已记", "不该有版型", "确定", "要选一个", "省了区分项", "表里没有")

# 商品名里常见的**品类词 / 场合词**,它们不是形制。
# 「宋制夏衫」的「夏衫」说的是季节,「粤绣重工婚服」的「婚服」说的是场合 ——
# 两者都不能推出裁片和量体项,而形制能。
# 名字里只有这类词的商品,**问题不在匹配器,在商品命名**。
品类词 = ("夏衫", "外罩", "套装", "婚服", "上襦", "常服", "礼服", "正装",
          "加长款", "基础", "入门", "长版", "重工")

# 一个商品要做**两件以上**(套装、亲子、两件、三件套)。
#
# ⚠️ **我第一版的诊断是错的**,写的是「`product.pattern` 是单值,装不下多件」——
# 不对。单值完全装得下:PT01 齐胸襦裙·标准的裁片是
# 「上襦前片×2、上襦后片×1、袖片×2、**裙片×3、裙头×1**」—— 上襦和裙在同一个版型里。
# 7 个 `unit=套` 的襦裙商品全是这么挂的,一个都没问题。
#
# 真正的问题是**名字、`unit`、裁片三者不一致**:
#   · 名字说多件而 `unit='件'` —— 4 个商品(抹胸套装 / 亲子襦裙 / 唐制套装 / 袄裙两件)
#   · 「明制袄裙·袄」PT12、PT36 的裁片**只有袄**(袄前片/后片/袖片/立领/袖缘/大襟贴边),
#     没有裙片 —— 而商品叫「明制袄裙**两件**」,挂的就是它
#
# **`unit` 这一列早就在承载「一件还是一套」** —— 又一次:
# 字段在那儿,而没人让它和名字对齐。
# 检查在 `product_pattern_check` 的 ⑥。
多件词 = ("套装", "亲子", "一套", "两件", "三件套", "两件套")

# ── 领型/门襟:**区分项本身** ────────────────────────────────────────
# `sku.collar` 这一列记着领型(交领 / 立领 / 方领 / 圆领 / 直领 / 对襟…),
# 而「省了区分项」省掉的往往就是它。**第四次撞见「答案早在库里」** ——
# 前三次是 `product_custom.xz`、`unit`、关键尺寸的两个来源。
#
# ⚠️ **只用来排除,不用来新增候选。**
# 排除是安全的(证据说它不是那个);新增要从领型反推形制,那是猜。
# 例:「秋暝」明制交领短袄 的 collar='交领',而 XZ32 是**立领斜襟**短袄 ——
# 排掉它之后这条变成「表里没有」,那才是真的:**明制交领短袄库里确实没有**。
# 原来它被判成「省了区分项 → XZ32」,等于把两件不同的衣服说成一件。
# ⚠️ **这些是三个轴,不是一个表。**
# 第一版我把它们塞进同一个元组,于是 collar='直领' 会把
# 「宋制**对襟**短衫」排掉(「对襟≠直领」)—— 而 PT49 的裁片注释白纸黑字写着
# 「**直领对襟**」:那是**一件衣服的两个属性**,不是两个候选。
# 一列承载两件事,比较时必然有一件被误当成另一件
# (这一轮第二次,上次是「童款」被塞进朝代前缀表)。
# 只在**同一个轴**里比。
款式轴 = {
    "领型": ("交领", "立领", "竖领", "方领", "圆领", "直领", "坦领", "盘领"),
    "门襟": ("对襟", "大襟", "斜襟"),
    "腰线": ("齐胸", "齐腰"),
}
领型词 = tuple(w for ws in 款式轴.values() for w in ws)
# 立领和竖领是同一个东西的两种叫法(XZ04 叫立领长衫、XZ33 叫竖领大襟长袄)
领型同义 = {"立领": "竖领", "竖领": "立领"}

# 下装类裁片的名字。`unit='套'` 的商品,它的版型必须同时有上装和下装裁片 ——
# 只有上装就是「说了一套只做了一件」,而车间照版型下料,**裙子不会被裁出来**。
下装裁片词 = ("裙片", "裙头", "裤片", "裤腰", "马面", "褶")


def _子序列(小, 大):
    """小的每个字**按顺序**出现在大里(允许中间插字)。

    为什么不用连续子串:商品名会把修饰语插进形制词中间。
    「百迭长版」宋制裙 —— 形制是 XZ07 百迭裙,而「百迭裙」不是它的连续子串
    (「长版」插在中间),于是第一版漏掉了这个**其实完全确定**的商品,
    还把它算进了「这些形制我们做不做」那一堆里。
    """
    i = 0
    for ch in 大:
        if i < len(小) and ch == 小[i]:
            i += 1
    return i == len(小)


def _裸名(s):
    """去掉花名括号和尺码括号,但**不去掉「」里的内容** ——
    形制信息经常就写在花名里(「百迭长版」宋制裙)。第一版把「」剥掉才漏了它。
    """
    import re as _re
    return _re.sub(r"[「」]|\(.*?\)|\(.*?\)", "", s or "")


def 已记的形制(conn, spu, xzs):
    """**先查库里有没有记着。** `product_custom.xz` 存的是形制名(或别名)。

    这一步是补上去的,补之前整件事是反的:我照着商品名写了一整套匹配器,
    而**定制品的形制早就一条一条填在 `product_custom.xz` 里** ——
    19 个待定成衣里 11 个有这一行,而我的匹配器**猜错了 7 个**:

        「凤仪锦瑟」粤绣重工婚服  库里:明制立领长衫  我猜:推不出形制
        「织金妆花」宋制大袖      库里:宋制褙子      我猜:大袖衫
        「同心」亲子唐制襦裙      库里:唐制齐胸襦裙  我猜:童款襦裙

    「一份没有被引用的主数据,和一份不存在的主数据,效果一样」——
    这条是它的**镜像**:有人已经写了,我没去查,于是造了个东西去猜它。
    **推出来的会错,记着的不会。**
    """
    if not spu:
        return None
    r = conn.execute("SELECT xz FROM product_custom WHERE spu=?", (spu,)).fetchone()
    nm = (r[0] if r else None) or ""
    if not nm:
        return None
    for z in xzs:
        if nm == z["name"]:
            return dict(z, 靠别名=False, 配置原文=nm)
    for z in xzs:
        别 = [a.strip() for a in (z["alias"] or "").split("、") if a.strip()]
        if nm in 别:
            # **靠别名接上的,不算「配置表说得更具体」。**
            # 「女式圆领」唐制袍 的配置表写的是「圆领袍」—— 那是 XZ09 改名前的
            # 旧名字,现在只是别名。名字说**唐制**,配置表只说「圆领袍」(泛称),
            # **配置表在这一条上比名字还模糊**。
            # 要是照「以配置表为准」办,会把一件唐制的衣服改成明制。
            return dict(z, 靠别名=True, 配置原文=nm)
    return None                  # 指向空处 —— `product_pattern_check` 会红


def 品类能定的形制(conn, 品类码, xzs):
    """商品挂在哪个**叶子品类**上 —— 那一列也在说这是什么衣服。

    **第六次「答案早就在库里」。** 前五次是 `product_custom.xz`、
    关键尺寸的两个来源、`unit`、`sku.collar`、`pattern_piece`。
    而品类树在这个项目里本来就是权威的 ——
    「商品性别按品类树判,不按 `gender` 字段」那条早就定了,
    **我却一直没想到它也在说形制**。

    叶子品类比形制**粗一档**(「袄」对着 4 个形制),所以它
    **能排除、有时能定**:「蜡染冰纹」男装道袍挂在 C020102「道袍」上,
    而库里只有一个道袍形制 —— 它的配置表那格写的「圆领袍」是填错的旧泛称。

    返回这个叶子品类对得上的形制码集合;对不上任何形制就返回空集
    (「襦 / 衫」「长衫 / 长袄」这种合并档就是空的)。
    """
    if not 品类码:
        return set()
    r = conn.execute("SELECT name FROM category WHERE code=?", (品类码,)).fetchone()
    if not r:
        return set()
    叶 = r[0]
    if conn.execute("SELECT 1 FROM category WHERE parent=? LIMIT 1", (品类码,)).fetchone():
        return set()                      # 不是叶子,不据此收窄
    out = set()
    for z in xzs:
        核 = _拆朝代(z["name"])[1]
        if 叶 == 核 or 核.endswith(叶) or 叶 == z["name"]:
            out.add(z["code"])
    return out


def 商品领型(conn, spu):
    """这个商品的 sku 说领型是什么。多个 sku 说法不一时返回 None ——
    **不一致本身就是「说不清」,不该拿来排除别人。**"""
    if not spu:
        return None
    got = {r[0] for r in conn.execute(
        "SELECT DISTINCT collar FROM sku WHERE spu=? AND collar IS NOT NULL "
        "AND collar!=''", (spu,))}
    return got.pop() if len(got) == 1 else None


def _领型打架(形制名, 领):
    """形制名在**同一个轴上**写了别的值 —— **那就不是这个形制**。

    两条纪律:
      · **只比同一个轴。** collar='直领'(领型轴)不去和「对襟」(门襟轴)比 ——
        「直领对襟」是一件衣服的两个属性。
      · **形制名里没写那个轴的,不算打架。** 说不出 ≠ 说错了 ——
        「分不清的两种状态,合并之后一定按更糟的那个被理解」。
    """
    if not 领:
        return False
    轴 = next((k for k, ws in 款式轴.items() if 领 in ws), None)
    if 轴 is None:
        return False                      # collar 里是个我们不认识的词,不据此排除
    写的 = [w for w in 款式轴[轴] if w in 形制名]
    if not 写的:
        return False                      # 这个形制没在这个轴上表态
    同 = {领, 领型同义.get(领, 领)}
    return not any(w in 同 for w in 写的)


def 拍板分档(conn, 商品名, 顶级品类, xzs=None, spu=None):
    """把一个待定版型的商品归到**一种决定**上。

    返回 dict(档位, 候选=[形制…], 提示, 多件=bool, 尺寸空=[形制码…])。
    """
    import re as _re
    if xzs is None:
        conn.row_factory = sqlite3.Row
        xzs = [dict(r) for r in conn.execute(
            "SELECT code,name,alias,key_sizes FROM xingzhi")]
    名 = _裸名(商品名)
    多件 = any(w in 名 for w in 多件词)

    if 顶级品类 not in ("女装", "男装", "童装"):
        return dict(档位="不该有版型", 候选=[], 多件=多件, 尺寸空=[],
                    提示="不是成衣,本来就不该有版型")

    # **品类树能定的形制**,提前算 —— 下面「靠别名」那条分支会提前 return,
    # 放在后面它就跑不到(第一版就是这么漏的:道袍走别名分支,品类收窄没生效)。
    品类码 = conn.execute("SELECT category FROM product WHERE spu=?",
                          (spu,)).fetchone() if spu else None
    可由品类定 = 品类能定的形制(conn, 品类码[0] if 品类码 else None, xzs)

    记 = 已记的形制(conn, spu, xzs)
    if 记:
        # 名字推出来的和记着的不一样,**要说出来** —— 那是商品命名和配置表打架,
        # 一个卖场页面按名字理解、一个车间按配置表下料,**两边看的不是同一件衣服**。
        try:
            猜 = 拍板分档(conn, 商品名, 顶级品类, xzs)      # 不传 spu,纯按名字
            打架 = 猜["候选"] and 记["code"] not in {z["code"] for z in 猜["候选"]}
        except RecursionError:                              # 防御,正常走不到
            打架 = False
        if 打架 and 记.get("靠别名"):
            # 配置表用的是别名(更松的旧标签),名字反而更具体 ——
            # **这种不许说「以配置表为准」**,两边都摆出来让人看。
            全 = 猜["候选"] + [记]
            # **品类树先收一道。** 「蜡染冰纹」男装道袍挂在 C020102「道袍」上,
            # 而配置表那格写的「圆领袍」是填错的旧泛称 ——
            # 品类树把 XZ09 排掉之后只剩 XZ20,就不用人拍了。
            交 = [z for z in 全 if z["code"] in 可由品类定] if 可由品类定 else []
            if len(交) == 1:
                叶名 = conn.execute("SELECT name FROM category WHERE code=?",
                                    (品类码[0],)).fetchone()[0]
                return dict(档位="确定", 候选=交, 多件=多件,
                            尺寸空=[z["code"] for z in 交
                                   if not (z["key_sizes"] or "").strip()],
                            提示=f"配置表写的是「{记['配置原文']}」(别名,更松的旧标签),"
                                 f"而**品类树挂在「{叶名}」上** —— "
                                 f"品类树把别的候选排掉了,不用拍")
            return dict(档位="要选一个", 候选=全, 多件=多件,
                        尺寸空=[z["code"] for z in 全
                               if not (z["key_sizes"] or "").strip()],
                        提示=f"配置表只写了「{记['配置原文']}」—— 那是 "
                             f"{记['code']} {记['name']} 的**别名**(更松的旧标签),"
                             f"而商品名写了朝代。"
                             f"**配置表在这一条上比商品名还模糊**,不能以它为准,"
                             f"要看实物定")
        return dict(档位="库里已记", 候选=[记], 多件=多件,
                    尺寸空=[记["code"]] if not (记["key_sizes"] or "").strip() else [],
                    提示=("**配置表里已经记着**,不是猜的" if not 打架 else
                          f"**配置表记的是 {记['code']} {记['name']},"
                          f"而商品名听起来像 "
                          f"{'/'.join(z['name'] for z in 猜['候选'])}** —— "
                          f"以配置表为准(车间按它下料),但这个名字该改"))

    朝代 = next((p for p in 朝代前缀 if p in 名), "")

    def 可用(z):
        """朝代和年龄段**分两个轴判**。

        第一版把「童款」塞进了朝代前缀表,于是「亲子**唐制**襦裙」和
        XZ39「**童款**襦裙」被判成「朝代打架」互相排除 ——
        童款说的是年龄段,唐制说的是形制年代,**两个维度挤进一列就一定互斥**。
        """
        zp = _拆朝代(z["name"])[0]
        童 = z["name"].startswith("童款")
        if 童 != (顶级品类 == "童装"):
            return False          # 童款形制只配童装,反之也一样
        # **「改良」是款式修饰,不是朝代** —— 第三次犯同一个错
        # (前两次:「童款」塞进朝代前缀表、领型/门襟/腰线塞进一个词表)。
        # XZ38「改良马面裙(通勤)」和 XZ03「明制马面裙」核都是「马面裙」,
        # 于是「金襕」织金缎马面裙(现货)两个都撞上、判成「要选一个」——
        # **而商品名一个「改良」都没写**。改良款是要写出来的。
        if z["name"].startswith("改良") and not any(
                w in 名 for w in ("改良", "通勤", "汉元素")):
            return False
        # **形制名自己声明了性别的,要认。**
        # XZ31「宋制直领长衫**(男)**」不该出现在女装商品的候选或线索里。
        # 只在形制**自己写了**的时候才据此排除 —— 大多数形制是男女通穿的
        # (XZ09 明制圆领袍的结构里明写「男女皆可」),**没写不等于限男或限女**。
        for _g in ("男", "女"):
            if any(b1 + _g + b2 in z["name"]
                   for b1, b2 in (("(", ")"), ("\uff08", "\uff09"))):
                if 顶级品类 in ("男装", "女装") and 顶级品类 != f"{_g}装":
                    return False
        if zp and zp != "童款" and 朝代 and zp != 朝代:
            return False          # 朝代明确打架
        return True

    宽, 窄 = [], []      # 宽=商品名⊇形制名(确定);窄=只对上开头几个字(要拍)
    for z in xzs:
        if not 可用(z):
            continue
        zk = _re.sub(r"\(.*?\)|\(.*?\)", "", _拆朝代(z["name"])[1])
        # **别名要一起试。** 第一版只试形制全名,于是三个「明制立领长袄」
        # (¥2280/¥2880/¥6800)全掉进「表里没有」—— 而 XZ04 的别名
        # **正是「立领袄」**,本来就对得上。别名列不查,等于那一列白填。
        名单 = [zk] + [a.strip() for a in (z["alias"] or "").split("、") if a.strip()]
        # **记下「有多具体」**:连续子串比只对上字序更具体,长的比短的更具体。
        # 不记的话,「大袖衫」会同时撞上 XZ05 大袖衫 和 XZ36 明制**大衫**
        # ——「大衫」是「大袖衫」的子序列,可它明显不是同一件衣服。
        # 子序列那一层是为「百迭**长版**裙」这种中间插字留的,
        # **不能让它把更短的名字也捞进来当平级候选**。
        命中 = [(2 if n in 名 else 1, len(n)) for n in 名单
                if n and _子序列(n, 名)]
        if 命中:
            z = dict(z, 具体度=max(命中))
            宽.append(z)
        elif len(zk) > 2 and (zk[:2] in 名 or zk[-2:] in 名):
            # 形制核的**头两字或尾两字**出现了,但整个名字对不上 ——
            # **商品名省掉的正好是区分项**。区分项在哪一头都有:
            #   尾部对上 → 区分项在前面。「唐制**襦裙**」对上三个
            #              (齐胸/交领/齐腰襦裙),省掉的是**腰线位置**
            #   头部对上 → 区分项在后面。「明制**方领**衫」对上
            #              「方领对襟短衫」,省掉的是**门襟结构**
            # 第一版只查头两字,于是「扎染晕色」唐制襦裙(¥3600)被判成
            # 「表里没有」—— 而表里明明有三个唐制襦裙,只是区分项写在前面。
            窄.append(z)

    # **泛称会吞掉细分。** 泛称的字更少,所以商品名一定先包含泛称,
    # 于是被判成「确定」——**看着定了,其实定到了一个说不清哪种的形制上**。
    #
    # 这一段是被 XZ09 逼出来的:它原来叫「圆领袍」,没有朝代前缀,
    # 把 XZ13 唐制圆领缺胯袍、XZ28 唐制圆领襕袍两个细分挡在后面,
    # 而它自己的关键尺寸还是空的 —— 挂上去量体项为空。
    # **后来查 md 发现它就写在 `## 明制` 那一节下面**,文档里还写着
    # 「补子是最重的工艺落点」,而补子正是明代官服的标志。
    # 所以它不是泛称,是个漏写了朝代前缀的明制形制:改名「明制圆领袍」就解了,
    # 而且挂在它下面的 7 个商品一个都不用动(删掉重建要动 9 个,其中 1 个下过单)。
    #
    # 这段代码**留着**:泛称字少一定先被撞上,是一整类错,不是 XZ09 一个案子。
    # 真数据里现在没有泛称了,所以 `pattern_grade_check` 给它配了**人造形制表** ——
    # 没红过的检查等于没有。
    # 有细分在,这就不是「确定」,是「要选一个」。
    if len(宽) == 1 and not _拆朝代(宽[0]["name"])[0]:
        泛 = 宽[0]
        核 = _re.sub(r"\(.*?\)|\(.*?\)", "", 泛["name"])
        # 细分必须**头两字对上、而且末字也对上**。
        # 只看头两字的话,「圆领袍」的细分里会混进「圆领襕**衫**」——
        # 衫和袍是两种东西(长度、下摆、有没有开裾),量体项都不一样。
        细 = [w for w in xzs
              if w["code"] != 泛["code"] and 可用(w)
              and _拆朝代(w["name"])[1].startswith(核[:2])
              and _拆朝代(w["name"])[1].endswith(核[-1])
              and len(_拆朝代(w["name"])[1]) > len(核)]
        if 细:
            全 = 宽 + 细
            return dict(档位="要选一个", 候选=全, 多件=多件,
                        尺寸空=[z["code"] for z in 全
                               if not (z["key_sizes"] or "").strip()],
                        提示=f"{泛['code']} {泛['name']} 是**泛称**,"
                             f"下面还有 {len(细)} 个细分 —— 挂泛称等于没定")

    # **领型排除** —— 见 `_领型打架`。放在这里(挑完候选、分档之前),
    # 因为它排的是候选,不是改分档规则。
    领 = 商品领型(conn, spu)
    if 领:
        宽 = [z for z in 宽 if not _领型打架(z["name"], 领)]
        窄 = [z for z in 窄 if not _领型打架(z["name"], 领)]

    # **品类树收窄** —— 见 `品类能定的形制`。
    # ⚠️ **只在有交集时收窄,交集为空就不动。** 叶子品类可能是合并档、
    # 也可能挂错了,而**「品类说不出来」不等于「名字说错了」** ——
    # 强行按空集收窄会把本来定得下来的商品全判成认不出。
    if 可由品类定:
        交 = [z for z in 宽 if z["code"] in 可由品类定]
        if 交:
            宽 = 交

    # **更具体的赢。** 只有并列最具体的才算「分不出」——
    # 这和泛称那一段是同一条:**「圆领袍」和「唐制圆领缺胯袍」不是两个平级候选**。
    if len(宽) > 1:
        顶级 = max(z.get("具体度", (0, 0)) for z in 宽)
        最具体 = [z for z in 宽 if z.get("具体度", (0, 0)) == 顶级]
        if len(最具体) == 1:
            宽 = 最具体

    空 = [z["code"] for z in (宽 or 窄) if not (z["key_sizes"] or "").strip()]
    if len(宽) == 1:
        return dict(档位="确定", 候选=宽, 多件=多件, 尺寸空=空,
                    提示="商品名完整包含这个形制名,不用拍")
    if len(宽) > 1:
        return dict(档位="要选一个", 候选=宽, 多件=多件, 尺寸空=空,
                    提示="几个形制都对得上,要看实物定")
    if 窄:
        return dict(档位="省了区分项", 候选=窄, 多件=多件, 尺寸空=空,
                    提示="形制名比商品名长 —— **商品名省掉的正好是区分项**")
    只有品类词 = [w for w in 品类词 if w in 名]
    # **认不出的时候给线索,不给候选。**
    # 线索 = 同朝代 + 同末字(衫/袄/袍/裙)+ 领型轴不打架的形制。
    # 它和候选的区别不是松紧,是**性质**:候选是「系统认为就是它」,
    # 线索是「你去看实物时先看这几个」。
    # 把两者混成一栏,人会照着线索直接挂 —— 而线索本来就没打算承担那个重量。
    末 = 名[-1] if 名 else ""
    线索形制 = []
    if 朝代 and 末 in ("衫", "袄", "袍", "裙", "裤", "衣"):
        for z in xzs:
            zp, zk = _拆朝代(z["name"])
            if zp != 朝代 or not zk or not 可用(z):
                continue                 # 只给同朝代、且性别/年龄段过得去的
            if _re.sub(r"\(.*?\)|\(.*?\)", "", zk)[-1:] != 末:
                continue
            if _领型打架(z["name"], 领):
                continue
            线索形制.append(z)
    尾 = ""
    if 领:
        尾 += f"(sku 记着领型是**{领}**"
        if 线索形制:
            尾 += ";同朝代同类里领型对得上的有 " + \
                  "、".join(f"{z['code']} {z['name']}" for z in 线索形制[:4]) + \
                  " —— **这是线索不是候选**,要看实物"
        尾 += ")"
    elif 线索形制:
        尾 = ("(同朝代同类的有 " +
              "、".join(f"{z['code']} {z['name']}" for z in 线索形制[:4]) +
              " —— **这是线索不是候选**)")
    return dict(档位="表里没有", 候选=[], 多件=多件, 尺寸空=[],
                提示=((f"名字里只有品类/场合词({'、'.join(只有品类词)}),推不出形制 —— "
                       f"**问题在商品命名,不在形制表**" if 只有品类词
                       else "形制表里真的没有这个形制") + 尾))


# ⚠️ 「童款」留在这张表里**只为了拆名字**(XZ39「童款襦裙」→ 核是「襦裙」),
# **判冲突时它不算朝代** —— 见 `拍板分档` 里的 `可用()`。
# 年龄段和朝代是两个轴,挤进一列就会互相排除。
朝代前缀 = ("唐制", "宋制", "明制", "晋制", "魏晋", "改良汉元素", "改良", "童款")


def _拆朝代(n):
    for p in 朝代前缀:
        if n.startswith(p):
            return p, n[len(p):]
    return "", n
