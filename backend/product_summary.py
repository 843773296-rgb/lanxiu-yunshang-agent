#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品归纳总结 —— 取数这一半(口径在 knowledge/traits.py,用户 2026-10-10)。

    属性表(c)                  全部商品各自的颜色 / 纹样 / 面料 / 工艺 / 形制(每个值带来源)
    归纳商品(c, spus)          给一套衣服 → 规律 / 共性 / 覆盖 / 结论(对照组 = 全部在架商品)
    归纳顾客(c, 客户, 今天)    一位顾客近 24 个月买过的 → 同上(对照组 = 全店买过的东西)

两种对照不能混:「这一套里云锦特别多」比的是**店里有什么**;「她特别爱买云锦」比的是**大家买什么** ——
店里云锦款占 8%,而大家买的东西里云锦可能只占 3%(贵),拿错对照,倍数就差一倍多。

顾客买的那一件,**颜色按她买的那个 SKU**(她买的是藏青那件,不是这款所有颜色);
其余维度按商品 —— 定制品的面料 / 工艺在下单时选过的,以后可以从 item_part_choice 补得更准(现在没做,照实说)。
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
import traits as T

DB = os.path.join(HERE, "lanxiu.db")


def 属性表(c):
    """{spu: {名称, 状态, 属性: {维度: [(值, 来源)]}}}。一次查全部 —— 商品才几百款,逐款查反而慢。"""
    import motif
    主料 = [r[0] for r in c.execute("SELECT name FROM material WHERE cat='主料'")]
    工艺 = [r[0] for r in c.execute("SELECT name FROM craft WHERE cat='工艺'")]
    色系 = dict(c.execute("SELECT color, family FROM color_family"))
    款色 = {}
    for spu, col in c.execute("SELECT spu, color FROM sku"):
        if 色系.get(col):
            款色.setdefault(spu, []).append(色系[col])
    出 = {}
    for spu, 名, 状态, xzname, pcxz, mt, kf in c.execute(
            "SELECT p.spu, p.name, p.status, xz.name, pc.xz, pc.mt_opts, pc.kf_opts FROM product p "
            "LEFT JOIN pattern pt ON pt.code=p.pattern LEFT JOIN xingzhi xz ON xz.code=pt.xz "
            "LEFT JOIN product_custom pc ON pc.spu=p.spu").fetchall():
        出[spu] = dict(名称=名, 状态=状态, 属性=T.属性(名称=名, 形制=xzname or pcxz, 色系们=款色.get(spu, ()),
                                                    定制面料=mt, 定制工艺=kf, 主料词=主料, 工艺词=工艺, 纹样推=motif.推))
    return 出


def _值们(属):
    return {d: [v for v, _ in 属.get(d, [])] for d in T.维度们}


def _占比(件们):
    """对照组:每个维度里,有这个值的件数 ÷ 认得出这个维度的件数。"""
    出 = {}
    for d in T.维度们:
        有 = [set(x.get(d) or ()) for x in 件们]
        有 = [s for s in 有 if s]
        计 = {}
        for s in 有:
            for v in s:
                计[v] = 计.get(v, 0) + 1
        出[d] = {v: k / len(有) for v, k in 计.items()} if 有 else {}
    return 出


def _包(结果, 明细, 对照名):
    结果 = dict(结果)
    结果["规律"] = [dict(x, 说法=T.一句话(x)) for x in 结果["规律"]]
    结果["共性"] = [dict(x, 说法=T.一句话(x) + " —— 但对照组里本来就常见,不算规律") for x in 结果["共性"]]
    结果["覆盖"] = {d: f"{n}/{总} 件认得出" for d, (n, 总) in 结果["覆盖"].items()}
    结果["对照组"] = 对照名
    结果["判法"] = (f"一个值要算规律:这个维度认得出的至少 {T.最少件数} 件、这个值至少 {T.该值最少件数} 件、"
                  f"占比是对照组的 {T.倍数门槛:g} 倍以上(用户 2026-10-10 定)")
    结果["明细"] = 明细
    return 结果


def 归纳商品(c, spus):
    表 = 属性表(c)
    没有 = [s for s in spus if s not in 表]
    件们 = [_值们(表[s]["属性"]) for s in spus if s in 表]
    对照 = _占比([_值们(v["属性"]) for v in 表.values() if v["状态"] == "上架"])
    r = T.归纳(件们, 对照)
    明细 = [dict(款号=s, 名称=表[s]["名称"], **{d: [f"{v}({src})" for v, src in 表[s]["属性"][d]] for d in T.维度们})
            for s in spus if s in 表]
    出 = _包(r, 明细, "全部在架商品")
    if 没有:
        出["没找到的款号"] = 没有
    return 出


def 买的那件(c, 表, 色系, item_id, spu, sku色):
    """顾客买的**那一件**的属性 —— 不是这款商品的属性:
    颜色按她买的那个 SKU;**定制品的面料 / 工艺 / 颜色按她下单时真选的**(item_part_choice,10-10 接上 ——
    原来用的是这款「可选项第一项」,而她可能选的是第三种料)。选了的维度来源标「下单时选的」,没选的退回商品属性。"""
    v = {d: [x for x, _ in 表[spu]["属性"][d]] for d in T.维度们}
    v["颜色"] = [色系[sku色]] if 色系.get(sku色) else []
    选 = c.execute("SELECT kind, part, material, color FROM item_part_choice WHERE item_id=? ORDER BY id",
                   (item_id,)).fetchall() if item_id is not None else []
    料 = [x for x in 选 if x[0] == "面料" and x[2]]
    if 料:
        主 = next((x for x in 料 if x[1] in ("主身", "整件")), 料[0])
        v["面料"] = [主[2]]
        if 色系.get(主[3]):
            v["颜色"] = [色系[主[3]]]
    艺 = sorted({x[2] for x in 选 if x[0] == "工艺" and x[2]})
    if 艺:
        v["工艺"] = 艺
    return v


def 买过的(c, 客户, 起, 止):
    """一位顾客窗口里买过的每一件(一行一件;取消 / 待付款的不算买过)。颜色按她买的那个 SKU。"""
    return c.execute("SELECT i.spu, s.color, o.id, substr(o.created,1,10), i.id FROM ordr o JOIN ordr_item i ON i.order_id=o.id "
                     "LEFT JOIN sku s ON s.code=i.sku WHERE o.customer_id=? AND substr(o.created,1,10) BETWEEN ? AND ? "
                     "AND o.status NOT IN ('取消','已取消','待付款') ORDER BY o.created, i.id", (客户, 起, 止)).fetchall()


def 全店买过的占比(c, 起, 止, 表=None):
    表 = 表 or 属性表(c)
    色系 = dict(c.execute("SELECT color, family FROM color_family"))
    件们 = []
    for spu, col in c.execute("SELECT i.spu, s.color FROM ordr o JOIN ordr_item i ON i.order_id=o.id "
                              "LEFT JOIN sku s ON s.code=i.sku WHERE substr(o.created,1,10) BETWEEN ? AND ? "
                              "AND o.status NOT IN ('取消','已取消','待付款')", (起, 止)):
        if spu in 表:
            v = _值们(表[spu]["属性"]); v["颜色"] = [色系[col]] if 色系.get(col) else []
            件们.append(v)
    return _占比(件们)


def 归纳顾客(c, 客户, 今天, 表=None, 对照=None):
    import purchase_pref as P
    表 = 表 or 属性表(c)
    起, 止 = P.窗口起点(今天).isoformat(), 今天.isoformat()
    色系 = dict(c.execute("SELECT color, family FROM color_family"))
    件们, 明细 = [], []
    for spu, col, oid, d, iid in 买过的(c, 客户, 起, 止):
        if spu not in 表:
            continue
        v = 买的那件(c, 表, 色系, iid, spu, col)
        件们.append(v)
        明细.append(dict(款号=spu, 名称=表[spu]["名称"], 订单=oid, 日期=d, **{k: x for k, x in v.items()}))
    对照 = 对照 or 全店买过的占比(c, 起, 止, 表)
    出 = _包(T.归纳(件们, 对照), 明细, f"全店近 {P.回看月数} 个月买过的东西")
    出["窗口"] = f"{起} ~ {止}"
    return 出
