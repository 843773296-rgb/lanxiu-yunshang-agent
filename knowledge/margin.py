# -*- coding: utf-8 -*-
"""毛利口径 —— 一单赚了多少,以及**这个数是基于几单算的**。

**业务定的**(`业务决策/业务拍板-20260924.md` 第 5 条;2026-09-28 用户说「按业内算」,
和这条是同一个口径,不用重拍):

    毛利 = 实收 −(面料辅料成本 + 工艺工日 × 工时单价)

    普通工序           300 元/工日
    非遗级(缂丝/妆花/苏绣这类)  800 元/工日

    收入用**实收**(折扣已经扣过);**不摊门店房租人力**

## ⚠️ 毛利率必须和覆盖率绑在一起报

「基于 53 单的毛利率」和「基于 4222 单的毛利率」是两回事,**而报表上长得一模一样** ——
都是一个百分数。所以 `汇总()` 不单独返回毛利率:它返回的那句话里一定带着
「基于 n / 共 N 单」,算不出的那些**不是毛利为 0,是不知道**。

而且算得出的那部分**不是随机抽的**。工单只记了在制的那几十单,
它们的毛利率不能读成全体定制单的毛利率。

2026-09-29 量的(`python3 knowledge/margin.py` 每次现量,别照抄这几个数):

    成交的定制单 3883 张(定制 4222,扣掉已关闭 / 待付款)
    工时:workorder 只有 53 行、50 张单 —— **覆盖 1.3%**
    物料:能连到「版型 + 面料」的只有走方案的 84 张 —— 算物料成本的**上限** 2.2%
    ⚠️ 原来说「craft_bom 覆盖 42/168,物料只算得出四分之一」—— **分母错了**。
       168 是整张 craft 表(含形制 / 材质 / 配饰,它们本来就不挂 BOM),
       工艺类是 42/45。卡物料的不是 BOM,是**订单连不到版型和面料**。
    两样都有、毛利**真能算出来的:1 张**(0.03%)—— 工单那 50 张和走方案那 84 张几乎不重叠。
    所以现在这条口径**能写对,但还算不出有意义的数**。下一步不是改口径,是补数据链路。

## ⚠️ 「活动折扣冲减收入」这条,在现在的数据上是**空跑的**

`amount ≠ payable` 的单:**0 条**。库里根本没有折扣。
所以「收入用实收(折扣已扣过)」这一半,现在**会是一行绿的而什么也没管** ——
不是验过了没问题,是**没有东西可验**。`折扣这条管着东西吗()` 把这件事说出来,
而不是让它安静地通过。

## 非遗级怎么认

**认结构,不认名字。** `knowledge/03-工艺.md` 里带「非遗」字段的工艺条目
(每条都写着国家级名录出处)= 非遗级。业务点名的缂丝、妆花、苏绣都在里面。
⚠️ 这么认会把**扎染、蓝印花布、蓝夹缬、晒莨**这类印染也算进 800 元一档 ——
它们确实在名录里,但「这类」是不是也包括它们,**业务没逐条说**,用到时要说出去。

`非遗关联`(杭罗这类「属于某项非遗的组成部分」)不算 —— 那是面料的出处,不是工序。

## 算不出就是算不出

缺实收、缺物料成本、缺工时,**任何一项缺了,这一单的毛利就是 None**,不是按 0 算。
按 0 算的话,缺物料的单毛利会虚高到接近 100%,而它在表上和一张真的高毛利单长得一样。

**标品不在这条口径里** —— 拍板说的是面料辅料和工艺工日,标品没有进货成本数据。
"""
import os, re

普通 = "普通"
非遗级 = "非遗级"
工时单价 = {普通: 300, 非遗级: 800}          # 元/工日 —— 业务 2026-09-24 拍板
摊门店费用 = False                           # 业务 2026-09-24:不摊房租人力
没成交 = ("已关闭", "待付款")                  # 这两种状态的实收是 0 或没付完,不算收入

_HERE = os.path.dirname(os.path.abspath(__file__))


def 非遗工艺(md=None):
    """`03-工艺.md` 里带「非遗」字段的工艺编码。**只认这个字段,不认名字。**"""
    txt = md if md is not None else open(os.path.join(_HERE, "03-工艺.md"), encoding="utf-8").read()
    出, 当前 = set(), None
    for 行 in txt.splitlines():
        m = re.match(r"###\s+(KF\d+)\s", 行)
        if m:
            当前 = m.group(1); continue
        if 行.startswith("#"):
            当前 = None; continue
        if 当前 and re.match(r"\s*-\s*\*\*非遗\*\*\s*[::]", 行):
            出.add(当前)
    return 出


def 档(工艺, 非遗集):
    return 非遗级 if 工艺 in 非遗集 else 普通


def 工时成本(工日们, 非遗集):
    """工日们 = [(工艺编码, 工日), ...]。

    None → None(**没有工时记录 ≠ 没有工时**);[] → 0(明确没有工艺工序)。
    任何一条工日是 None → 整单 None,不拿能算的那几条凑一个偏低的数。
    """
    if 工日们 is None:
        return None
    合 = 0.0
    for 工艺, 天 in 工日们:
        if 天 is None or 天 < 0:
            return None
        合 += 天 * 工时单价[档(工艺, 非遗集)]
    return round(合, 2)


def 一单(实收, 物料成本, 工日们, 非遗集, 状态=None, 类型="定制品订单"):
    """返回 dict(毛利, 实收, 物料, 工时, 缺)。缺了任何一项 → 毛利 None,缺里写着缺什么。"""
    缺 = []
    if 类型 != "定制品订单":
        缺.append("标品不在这条口径里(没有进货成本数据)")
    if 状态 in 没成交:
        缺.append(f"「{状态}」不算收入")
    if 实收 is None:
        缺.append("实收")
    if 物料成本 is None:
        缺.append("物料成本")
    工时 = 工时成本(工日们, 非遗集)
    if 工时 is None:
        缺.append("工时")
    毛利 = None if 缺 else round(实收 - (物料成本 + 工时), 2)
    return dict(毛利=毛利, 实收=实收, 物料=物料成本, 工时=工时, 缺=缺)


def 汇总(结果们, 总单数):
    """毛利率 **和** 它是基于几单算的,一起返回。

    总单数是**该算的**单数(成交的定制单),不是算得出的单数 ——
    分母用错,覆盖率就是 100%,而那正是这个函数要防的事。
    """
    可 = [r for r in 结果们 if r["毛利"] is not None]
    n, N = len(可), int(总单数 or 0)
    收 = sum(r["实收"] for r in 可)
    率 = round(sum(r["毛利"] for r in 可) / 收, 4) if 收 else None
    覆 = round(n / N, 4) if N else None
    if N == 0:
        话 = "没有该算的单 —— 不是毛利为 0,是没有东西可算"
    elif n == 0:
        话 = f"共 {N} 单,**一单都算不出** —— 不是毛利为 0,是不知道"
    else:
        话 = f"毛利率 {率 * 100:.1f}%(**基于 {n} / 共 {N} 单**,覆盖 {覆 * 100:.1f}%)"
        if n < N:
            话 += (f";其余 {N - n} 单算不出,不是毛利为 0。"
                  "算得出的那部分**不是随机抽的**,这个率不能读成全体的毛利率")
    return dict(毛利率=率, 算得出=n, 共=N, 覆盖率=覆, 一句话=话)


def 折扣这条管着东西吗(有折扣的单数):
    """「收入用实收(折扣已扣过)」在这批数据上有没有东西可管。返回 (管着吗, 一句话)。"""
    if not 有折扣的单数:
        return False, ("库里 amount ≠ payable 的单是 0 条 —— 「折扣冲减收入」这条**空跑**:"
                       "它是绿的,但什么也没管。不是验过了,是没有东西可验")
    return True, f"{有折扣的单数} 单有折扣,实收已经扣过"



# ══ 2026-09-29 用户拍板:工时、缝制、面料、定价、标品代工 ════════════════════════
#
#   工日来源       有工单用实记;其余按 07 工时表(`leadtime.craft_days`)估**区间**,标「估算」
#   印染晾晒类     单位是日历天 → **不计工日**,标「不含印染人工」(晾晒那些天不是人手在做)
#   同种工艺       **一件衣服算一次**(07 表的「局部」是一件衣服的一档,整幅 = 局部 × 4)
#   缝制           复用工期推算 A-26 的缝制公式,天数当工日,按普通工序 300
#   面料           复用 A-19 裁片占比,按部位拆:该部位选的料 × 这个部位吃多少米
#   定制品定价     **按款**:标准配置成本(人工取**上限**)× 2.5,目标毛利 60%(**没有行业出处**,用户知情)
#   标品           进货单价 = 物料 + **按件代工费**(按品类,demo 拍脑袋)
#
# ⚠️ 一件的成本里面料**含损耗**(`material.loss_rate`),而分部位报价(server.py)不含 ——
# 报价那边算的是「给客户看的料费」,这里算的是「真花出去的钱」,裁剪损耗是真花的。
定价系数 = 2.5          # 业务 2026-09-29:售价 = 成本 × 2.5(目标毛利 60%)
缝制单价档 = 普通
代工费_每件 = {"裙": 80, "上衣": 120, "套装": 200}     # ⚠️ demo:拍脑袋,有真实代工报价时整表替换
代工费_来源 = "demo"
_品类到代工档 = {"C0102": "裙", "C0101": "上衣", "C0103": "上衣", "C0201": "上衣", "C0301": "套装"}


def 代工档(品类码):
    """标品的品类码 → 代工费那一档。按二级类目认(裙装 / 上装 / 外套 / 男装上装 / 童装成套)。认不出返回 None,不猜。"""
    return _品类到代工档.get((品类码 or "")[:5])


def 代工费(品类码):
    档 = 代工档(品类码)
    return 代工费_每件.get(档) if 档 else None


def _工时表():
    import leadtime
    return leadtime.craft_days()


def 缝制工日(裁片数, 难度):
    """(最少, 最多) —— 复用 A-26 的缝制公式,不另抄常数:抄一份,两边迟早对不上。"""
    import leadtime as L
    lo = L.SEW_BASE + 裁片数 * L.SEW_PER_PIECE + L.SEW_HARD.get(难度, 1)
    return round(lo, 2), round(lo * 1.5, 2)


def 工艺人工(工艺们, 非遗集, 版型码=None, 工时表=None):
    """一件衣服的工艺人工(元)。工艺们 = 这件用到的工艺编码(**同种只算一次**,传重复的也去重)。

    返回 (最少, 最多, 未含)。未含 = 单位不是工日、所以没算人工的那些(印染晾晒类)。
    """
    import leadtime as L
    D = 工时表 or _工时表()
    lo = hi = 0.0
    未含 = []
    for k in sorted(set(x for x in 工艺们 if x)):
        d = D.get(k)
        if not d:
            未含.append(f"{k}(工时表里没有)")
            continue
        a, b, 单位 = d[0], d[1], d[2]
        if 单位 != "工日":
            未含.append(k)
            continue
        if k == "KF20" and 版型码:                     # 盘扣按对数计,和工期推算同一个口径
            n = L._pan_pairs(版型码) or 4
            a, b = a * n, b * n
        价 = 工时单价[档(k, 非遗集)]
        lo += a * 价
        hi += b * 价
    return round(lo, 2), round(hi, 2), 未含


def 一件的成本(conn, 版型码, 部位面料, 工艺们, 非遗集=None):
    """一件定制衣服真花出去的钱:物料(按部位的面料 + 辅料 + 工艺辅料 + 包装)+ 人工区间。

    部位面料 = {部位: 面料名};工艺们 = 工艺编码。返回 dict(物料, 人工=(最少, 最多), 未含, 缺)。
    **缺**不为空时物料是 None —— 缺价的料不按 0 算。
    """
    import part as _part
    import derive_pattern as dp
    遗 = 非遗集 if 非遗集 is not None else 非遗工艺()
    料 = {r[0]: r[1:] for r in conn.execute(
        "SELECT name, price, loss_rate, cat, code FROM material")}
    码料 = {v[3]: (k,) + v for k, v in 料.items()}
    缺, 物料 = [], 0.0
    for 部位, 名 in (部位面料 or {}).items():
        米, _ = _part.部位用料(conn, 版型码, 部位)
        if 名 not in 料:
            缺.append(f"{部位}「{名}」没有单价")
            continue
        价, 损 = 料[名][0], 料[名][1] or 0
        物料 += (米 or 0) * (1 + 损) * 价
    已按部位 = {c for 部位 in (部位面料 or {}) for c in _part.部位可选料类(部位)}
    for mc, q in conn.execute("SELECT material, qty_base FROM pattern_bom WHERE pattern=?", (版型码,)):
        m = 码料.get(mc)
        if m and m[3] not in 已按部位:                  # 主料 / 里料已经按部位算过了
            物料 += (q or 0) * (1 + (m[2] or 0)) * m[1]
    for k in sorted(set(x for x in 工艺们 if x)):
        for mc, q in conn.execute("SELECT material, qty FROM craft_bom WHERE craft=?", (k,)):
            m = 码料.get(mc)
            if m:
                物料 += (q or 0) * (1 + (m[2] or 0)) * m[1]
    for mc in dp.PACKAGING:
        m = 码料.get(mc)
        if m:
            物料 += m[1]
    p = conn.execute("SELECT pieces, difficulty FROM pattern WHERE code=?", (版型码,)).fetchone()
    if not p:
        return dict(物料=None, 人工=(None, None), 未含=[], 缺=[f"没有版型 {版型码}"])
    a, b, 未含 = 工艺人工(工艺们, 遗, 版型码)
    s1, s2 = 缝制工日(p[0] or 0, p[1])
    r = 工时单价[缝制单价档]
    return dict(物料=None if 缺 else round(物料, 2),
                人工=(round(a + s1 * r, 2), round(b + s2 * r, 2)),
                未含=未含, 缺=缺)


def 款式价(物料, 人工上限):
    """按款定价:标准配置成本(人工取上限)× 定价系数,取整到十元。"""
    if 物料 is None or 人工上限 is None:
        return None
    return int(round((物料 + 人工上限) * 定价系数, -1))


def 工艺编码表(conn):
    """工艺名 → 编码。「抽纱 / 雕绣」这种合称,拆开的两个名字也认。"""
    出 = {}
    for k, n in conn.execute("SELECT code, name FROM craft WHERE cat='工艺'"):
        出[n.strip()] = k
        for x in n.split("/"):
            出.setdefault(x.strip(), k)
    return 出


def 标准配置(conn, spu):
    """这一款的标准配置:每个部位取**不加价**的那个面料(款式本身用的料,`addon`=0);
    工艺取这款挂的全部工艺(同种一次)。

    ⚠️ 不能按名字排序取第一个 —— 那会挑中一种要加价的料,款式价就按「升级配置」定了。
    """
    码 = 工艺编码表(conn)
    面, 艺 = {}, set()
    for 部位, 类, 名 in conn.execute(
            "SELECT part, kind, material FROM part_option WHERE spu=? "
            "ORDER BY sort, COALESCE(addon, 0), material", (spu,)):
        if 类 == "面料":
            面.setdefault(部位, 名)
        elif 类 == "工艺" and 名 in 码:
            艺.add(码[名])
    return 面, sorted(艺)


def 一单_从库(conn, 订单, 非遗集=None, 工时表=None, 编码表=None):
    """从库里算一单的毛利区间。返回 dict(毛利=(按人工上限, 按人工下限), 实收, 成本, 人工来源, 未含, 缺)。

    · 定制单:每件按**它自己选的**部位面料和工艺算(`item_part_choice`),同种工艺整件一次;
      这一单有工单的,**工艺**人工用工单实记的工日(缝制仍按公式估,工单只记工艺)
    · 标品单:Σ 数量 × `sku.cost_price`;有一件进价是空的 → 整单算不出
    · 缺任何一项 → 毛利 None,缺里写缺什么。**不按 0 算**
    """
    遗 = 非遗集 if 非遗集 is not None else 非遗工艺()
    D = 工时表 or _工时表()
    码 = 编码表 or 工艺编码表(conn)
    o = conn.execute("SELECT kind, prd_status, received FROM ordr WHERE id=?", (订单,)).fetchone()
    if not o:
        return dict(毛利=(None, None), 缺=["没有这张单"])
    类型, 状态, 实收 = o
    缺, 未含 = [], []
    if 状态 in 没成交:
        缺.append(f"「{状态}」不算收入")
    if 实收 is None:
        缺.append("实收")
    if 类型 == "标品订单":
        成本 = 0.0
        for sku, qty, cp in conn.execute(
                "SELECT i.sku, i.qty, s.cost_price FROM ordr_item i LEFT JOIN sku s ON s.code=i.sku "
                "WHERE i.order_id=?", (订单,)):
            if cp is None:
                缺.append(f"{sku} 没有进货单价")
            else:
                成本 += (qty or 1) * cp
        毛 = None if 缺 else round(实收 - 成本, 2)
        return dict(毛利=(毛, 毛), 实收=实收, 成本=(成本, 成本), 人工来源="进价", 未含=[], 缺=缺)
    实记 = {}
    for k, w in conn.execute("SELECT craft, workdays FROM workorder WHERE ref=?", (订单,)):
        实记[k] = 实记.get(k, 0) + (w or 0)
    lo = hi = 0.0
    件数 = 0
    for iid, spu, qty in conn.execute(
            "SELECT id, spu, qty FROM ordr_item WHERE order_id=?", (订单,)).fetchall():
        pc = (conn.execute("SELECT pattern FROM product WHERE spu=?", (spu,)).fetchone() or [None])[0]
        if not pc:
            缺.append(f"{spu} 没挂版型")
            continue
        面, 艺 = {}, set()
        for 类, 部位, 名 in conn.execute(
                "SELECT kind, part, material FROM item_part_choice WHERE item_id=?", (iid,)):
            if 类 == "面料":
                面[部位] = 名
            elif 类 == "工艺":
                if 名 in 码:
                    艺.add(码[名])
                else:
                    缺.append(f"工艺「{名}」认不出")
        if not 面:
            缺.append(f"{spu} 没有部位选料")
            continue
        r = 一件的成本(conn, pc, 面, sorted(艺), 遗)
        缺 += r["缺"]
        未含 += r["未含"]
        a, b = r["人工"]
        if 实记:                      # 工艺人工换成实记:先扣掉估的工艺人工,再加实记
            ea, eb, _ = 工艺人工(艺, 遗, pc, D)
            真 = sum(w * 工时单价[档(k, 遗)] for k, w in 实记.items())
            a, b = a - ea + 真, b - eb + 真
        n = qty or 1
        lo += n * ((r["物料"] or 0) + a)
        hi += n * ((r["物料"] or 0) + b)
        件数 += 1
    if not 件数 and not 缺:
        缺.append("没有订单行")
    if 缺:
        return dict(毛利=(None, None), 实收=实收, 成本=(None, None), 人工来源=None, 未含=未含, 缺=缺)
    return dict(毛利=(round(实收 - hi, 2), round(实收 - lo, 2)), 实收=实收,
                成本=(round(lo, 2), round(hi, 2)), 人工来源="实记" if 实记 else "估算",
                未含=sorted(set(未含)), 缺=[])

咬合 = [
    ("让 一单() 缺物料成本时按 0 算", "缺物料成本 → 毛利算不出,不按 0 算"),
    ("把 汇总() 那句话里的「基于 n / 共 N 单」删掉", "毛利率的那句话里带着基于几单"),
    ("把 非遗工艺() 的判据改成认「非遗关联」也算", "「非遗关联」不算非遗级"),
    ("让 折扣这条管着东西吗(0) 返回 True", "0 条折扣 → 说出来是空跑"),
    ("让 工艺人工() 不去重(同种工艺按出现次数算)", "同种工艺整件算一次(传两遍平绣,人工不翻倍)"),
    ("让 工艺人工() 把日历天也按工日算", "印染晾晒类不计工日,报在「未含」里"),
]


def _实测():
    """从库里现量:毛利走整条链,**定制和标品分开、实记和估算分开**。只打印,不判红 ——
    毛利高低是数据的现状,不是口径的错。"""
    import sqlite3, statistics as st
    db = os.path.join(os.path.dirname(_HERE), "backend", "lanxiu.db")
    if not os.path.exists(db):
        print("  ⚠️ 没有库,毛利没量 —— 不是毛利为 0"); return
    c = sqlite3.connect(db)
    有进价列 = any(r[1] == "cost_price" for r in c.execute("PRAGMA table_info(sku)"))
    遗, D, 码 = 非遗工艺(), _工时表(), 工艺编码表(c)
    ph = ",".join("'%s'" % x for x in 没成交)
    for 类型 in ("定制品订单", "标品订单"):
        if 类型 == "标品订单" and not 有进价列:
            print("  ⚠️ 标品:库里还没有 sku.cost_price 列(旧库)—— 重建之后才量得出,**不是毛利为 0**")
            continue
        ids = [r[0] for r in c.execute(
            f"SELECT id FROM ordr WHERE kind=? AND prd_status NOT IN ({ph})", (类型,))]
        rs = [一单_从库(c, i, 遗, D, 码) for i in ids]
        可 = [r for r in rs if r["毛利"][0] is not None]
        for 界, j in (("人工按上限", 0), ("人工按下限", 1)):
            汇 = 汇总([dict(毛利=r["毛利"][j], 实收=r["实收"]) for r in 可], len(ids))
            print(f"  {类型}({界}):{汇['一句话']}")
        if 可:
            print(f"     人工来源:" + "、".join(f"{k} {v}" for k, v in
                  sorted(__import__('collections').Counter(r['人工来源'] for r in 可).items())))
            率 = sorted(r["毛利"][0] / r["实收"] for r in 可 if r["实收"])
            if 率:
                print(f"     单单毛利率(人工按上限)分布:10% 分位 {率[len(率)//10]:.0%} · 中位 {st.median(率):.0%} · "
                      f"90% 分位 {率[len(率)*9//10]:.0%} · 负毛利 {sum(x < 0 for x in 率)} 单")
        缺 = __import__('collections').Counter((r["缺"] or ["?"])[0].split(" ")[-1] for r in rs if r["毛利"][0] is None)
        if 缺:
            print(f"     算不出的 {len(rs) - len(可)} 单,按原因:" + "、".join(f"{k} {v}" for k, v in 缺.most_common(4)))
    旧价 = c.execute(f"""SELECT COUNT(DISTINCT i.order_id) FROM ordr_item i JOIN ordr o ON o.id=i.order_id
                        JOIN product p ON p.spu=i.spu WHERE o.kind='定制品订单'
                        AND o.prd_status NOT IN ({ph}) AND i.base_amount != p.base_price""").fetchone()[0]
    print(f"  ℹ️ 定制单里款式价 ≠ 现款式价的 {旧价} 单 —— seed 自带的夹具单保持原价(那是别人的真值),它们的毛利会难看")
    折 = c.execute("SELECT COUNT(*) FROM ordr WHERE amount != payable").fetchone()[0]
    print(f"  {'✅' if 折 else '⚠️'} {折扣这条管着东西吗(折)[1]}")


if __name__ == "__main__":
    import sys
    bad = []

    def ck(名, 取):
        try:
            ok, 说 = bool(取()), ""
        except Exception as e:
            ok, 说 = False, f"  ← **崩了**:{type(e).__name__}: {e}"
        print(f"  {'✅' if ok else '❌'} {名}{说}")
        if not ok: bad.append(名)

    print("毛利口径 · 自测\n" + "=" * 74)
    遗 = 非遗工艺()
    ck("业务点名的缂丝 / 妆花 / 苏绣都认成非遗级", lambda: {"KF01", "KF02", "KF03"} <= 遗)
    ck("普通工序(手工锁边 KF18、盘扣 KF20)不是非遗级", lambda: not ({"KF18", "KF20"} & 遗))
    ck("「非遗关联」不算非遗级",
       lambda: 非遗工艺("### KF99 杭罗\n- **非遗关联**:属蚕桑丝织技艺\n") == set())
    ck("非遗级认得出十条以上(认结构,不是只认点名的三个)", lambda: len(遗) >= 10)
    ck("缂丝 20 工日 × 800 = 16000(拍板原文的例子)", lambda: 工时成本([("KF01", 20)], 遗) == 16000)
    ck("普通 3 工日 × 300 = 900", lambda: 工时成本([("KF18", 3)], 遗) == 900)
    ck("没有工时记录 → None,不是 0", lambda: 工时成本(None, 遗) is None)
    ck("明确没有工艺工序 → 0", lambda: 工时成本([], 遗) == 0)
    ck("有一条工日缺 → 整单工时 None,不拿能算的凑", lambda: 工时成本([("KF18", 3), ("KF01", None)], 遗) is None)

    r = 一单(20000, 3000, [("KF01", 10)], 遗)
    ck("毛利 = 实收 −(物料 + 工日 × 单价)", lambda: r["毛利"] == 20000 - (3000 + 8000) and not r["缺"])
    ck("缺物料成本 → 毛利算不出,不按 0 算", lambda: 一单(20000, None, [], 遗)["毛利"] is None
       and "物料成本" in 一单(20000, None, [], 遗)["缺"])
    ck("缺工时 → 毛利算不出", lambda: 一单(20000, 3000, None, 遗)["毛利"] is None)
    ck("物料 0 元是真的 0(全用库存尾料),能算", lambda: 一单(5000, 0, [], 遗)["毛利"] == 5000)
    ck("已关闭的单不算收入", lambda: 一单(0, 100, [], 遗, 状态="已关闭")["毛利"] is None)
    ck("标品不在这条口径里", lambda: 一单(500, 100, [], 遗, 类型="标品订单")["毛利"] is None)
    ck("不摊门店费用(业务拍板)", lambda: 摊门店费用 is False)

    s = 汇总([一单(10000, 2000, [], 遗), 一单(10000, None, [], 遗)], 4)
    ck("毛利率只算算得出的那几单", lambda: s["毛利率"] == 0.8 and s["算得出"] == 1)
    ck("覆盖率的分母是该算的单数,不是算得出的", lambda: s["覆盖率"] == 0.25)
    ck("毛利率的那句话里带着基于几单", lambda: "基于 1 / 共 4 单" in s["一句话"])
    ck("没全覆盖时说出来「不是随机抽的」", lambda: "不是随机抽的" in s["一句话"])
    ck("一单都算不出 → 毛利率 None,说「不是毛利为 0」",
       lambda: 汇总([一单(1, None, [], 遗)], 3)["毛利率"] is None and "不是毛利为 0" in 汇总([], 3)["一句话"])
    ck("没有该算的单 → 说没有东西可算", lambda: "没有东西可算" in 汇总([], 0)["一句话"])
    ck("0 条折扣 → 说出来是空跑", lambda: 折扣这条管着东西吗(0)[0] is False and "空跑" in 折扣这条管着东西吗(0)[1])
    ck("有折扣 → 管着东西", lambda: 折扣这条管着东西吗(3)[0])

    # ── 09-29 拍板的那几条 ──
    ck("代工档:裙装 → 裙 80", lambda: 代工档("C010201") == "裙" and 代工费("C010201") == 80)
    ck("代工档:外套和男装袍子 → 上衣 120", lambda: 代工费("C010302") == 120 and 代工费("C020101") == 120)
    ck("代工档:童装成套 → 套装 200", lambda: 代工费("C030101") == 200)
    ck("代工档认不出(配饰)→ None,不猜", lambda: 代工费("C040301") is None)
    import leadtime as _L
    ck("缝制工日复用工期公式(不另抄常数)",
       lambda: 缝制工日(10, "中")[0] == round(_L.SEW_BASE + 10 * _L.SEW_PER_PIECE + _L.SEW_HARD["中"], 2))
    ck("缝制最慢 = 最快 × 1.5(和工期推算同一口径)", lambda: 缝制工日(10, "中")[1] == round(缝制工日(10, "中")[0] * 1.5, 2))
    ck("同种工艺整件算一次(传两遍平绣,人工不翻倍)",
       lambda: 工艺人工(["KF11", "KF11"], 遗)[:2] == 工艺人工(["KF11"], 遗)[:2])
    ck("印染晾晒类不计工日,报在「未含」里", lambda: 工艺人工(["KF14"], 遗) == (0.0, 0.0, ["KF14"]))
    ck("苏绣按非遗 800:8–20 工日 → 6400–16000", lambda: 工艺人工(["KF03"], 遗)[:2] == (6400.0, 16000.0))
    ck("款式价 = (物料 + 人工上限) × 2.5,取整到十元", lambda: 款式价(1000, 7000) == 20000)
    ck("款式价缺物料 → None,不按 0 算", lambda: 款式价(None, 7000) is None)

    print("\n覆盖率 · 从库里现量(只报不判)")
    _实测()
    print("=" * 74)
    print(f"❌ {len(bad)} 条不过" if bad else "✅ 毛利口径自测全过")
    sys.exit(1 if bad else 0)
