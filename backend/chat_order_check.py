# -*- coding: utf-8 -*-
"""聊天里「按时间段查订单」那套的**权限对账** —— 卡片和弹窗两头都要拦。

业务 2026-10-06 定的三档:

    总部运营   全部门店
    店长       本店
    顾问       **他名下客户的单 ∪ 他经手下的单**(并集)

## ⚠️ 这份检查存在的全部理由:**弹窗是按订单号取数的**

卡片由工具按身份取数,前端只显示自己范围内那些。而点开弹窗要按订单号拿详情 ——
> 一个「前端只显示自己范围内的卡片」的实现,和一个「服务端也拦住了」的,
> **在界面上长得一模一样** —— 直到有人直接改 URL。

所以这里**真的拿另一个人的订单号去请求**,看服务端拦不拦。

## ⚠️ 「看不到」和「不存在」对外必须同形

一个「订单不存在」回 404、「存在但你看不到」回 403 的接口,
**本身就是一个「这单存不存在」的探测器**。
所以两种都回同一个 `看不到` 形状,而**理由里分开说**。
(和 `auth.login` 那条「不区分查无此人和密码错」同一个道理。)

## ⚠️ 顾问那一档要**两个方向都验**

> 一个「只按订单上的顾问判」的实现,和一个真做了并集的,
> **在「他经手的那些单他看得到」这条上长得一模一样** ——
> 差别只在他名下客户、同事帮下的那批(全库 12393 单,占 39%)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datetime as _dt

import auth
import server

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
坏 = []
过 = [0]


# ── 咬合记录 ──────────────────────────────────────────────────────────
咬合 = [
    ("把弹窗的权限判断删掉(只靠前端只显示自己的卡片)",
     "拿别人的订单号去请求 → 看不到"),
    ("让「订单不存在」和「不在你范围内」回不同的形状(成了存在性探测器)",
     "不存在的订单号也走同一个「看不到」形状"),
    ("顾问那一档只按订单上的顾问判(丢掉「名下客户」那一半)",
     "他名下客户、**同事经手**的单 → 看得到(这一半最容易丢)"),
    ("手机号原样返回",
     "客户手机号是脱敏的"),
    ("把卡片那头的 SQL 范围改松(和纯判定对不上)",
     "SQL 选出的和纯判定说能看的**一模一样**"),
    ("把卡片那头的范围话和口径那边改得不一致",
     "`范围话` 两头一致"),
    ("图不标出处(一张 AI 效果图当实物图给客户看)",
     "🔑 图带上了**出处**(生成图 / 示意图)"),
    ("定制内容压成一句话(出色差纠纷时答不出袖子选的是哪个色)",
     "定制内容是**逐部件**的,不是一句话"),
    ("只报一个定制加价(另一个对不上也看不见)",
     "🔑 **两个加价都报了**(选项标的 / 订单行上的)"),
]


def ck(说, ok, 附=""):
    if ok:
        过[0] += 1
        print(f"  {G}✅{D} {说}  {附}")
    else:
        坏.append(说)
        print(f"  {R}❌{D} {说}  {附}")


class _假handler:
    """只提供 cookie —— 身份仍由 `auth.who(token)` 换,**不绕过那一步**。"""
    def __init__(self, tok):
        self.headers = {"cookie": f"lx_token={tok}"}


def _发个token(who):
    tok = f"test-{who['no']}-{id(who)}"
    with auth._LOCK:
        auth._SESS[tok] = dict(who, at=_dt.datetime.now())
    return tok


def main():
    print("聊天查订单 · 权限对账")
    print("=" * 92)
    q = server.rows

    顾们 = q("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用'")
    店们 = q("SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用'")
    运们 = q("SELECT no,name,role,shop FROM staff WHERE role='总部运营' AND status='启用'")
    if len(顾们) < 2 or not 店们 or not 运们:
        print(f"  {Y}⏸{D} 库里人不够(顾问 {len(顾们)} / 店长 {len(店们)} / "
              f"运营 {len(运们)})—— **不适用,不是通过**")
        return 0
    甲, 乙 = dict(顾们[0]), dict(顾们[1])
    运 = dict(运们[0])

    # ── 找三种样本单 ────────────────────────────────────────────
    # ① 甲经手的  ② 甲名下客户而**别人经手**的  ③ 和甲完全无关的
    经手 = q("""SELECT o.id, o.shop FROM ordr o WHERE o.advisor_no=? LIMIT 1""", 甲["no"])
    名下 = q("""SELECT o.id, o.shop FROM ordr o JOIN customer cu ON cu.id=o.customer_id
                WHERE cu.advisor_no=? AND o.advisor_no<>? LIMIT 1""", 甲["no"], 甲["no"])
    无关 = q("""SELECT o.id, o.shop FROM ordr o JOIN customer cu ON cu.id=o.customer_id
                WHERE o.advisor_no<>? AND (cu.advisor_no IS NULL OR cu.advisor_no<>?)
                LIMIT 1""", 甲["no"], 甲["no"])
    for 名, 样 in (("甲经手的", 经手), ("甲名下客户而别人经手的", 名下), ("和甲无关的", 无关)):
        if not 样:
            print(f"  {Y}⏸{D} 库里找不到「{名}」的样本 —— **不适用,不是通过**")
            return 0

    甲tok, 乙tok, 运tok = _发个token(甲), _发个token(乙), _发个token(运)

    def 拿(tok, oid):
        return server.chat_order_detail(oid, _假handler(tok))

    print("\n▸ ① 顾问那一档是**并集** —— 两个方向都验")
    d1 = 拿(甲tok, 经手[0]["id"])
    ck("他经手的单 → 看得到", not d1.get("看不到"), d1.get("为什么", ""))
    ck("而且标上有「我下的单」", "我下的单" in (d1.get("我的标") or []), d1.get("我的标"))
    d2 = 拿(甲tok, 名下[0]["id"])
    ck("🔑 他名下客户、**同事经手**的单 → 看得到(这一半最容易丢)",
       not d2.get("看不到"), d2.get("为什么", ""))
    ck("而且标上有「我的客户」而没有「我下的单」",
       (d2.get("我的标") or []) == ["我的客户"], d2.get("我的标"))

    print("\n▸ ② 🔑 **拿别人的订单号去请求** —— 服务端要拦")
    d3 = 拿(甲tok, 无关[0]["id"])
    ck("拿别人的订单号去请求 → 看不到", bool(d3.get("看不到")), d3.get("为什么", ""))
    ck("理由说清是「既不是你经手的,客户也不在你名下」",
       "不在你名下" in str(d3.get("为什么")), d3.get("为什么"))
    ck("而且**一个字段都不给** —— 不是给了个空壳",
       "订单" not in d3 and "客户" not in d3 and "明细" not in d3, sorted(d3))

    print("\n▸ ③ 「看不到」和「不存在」**对外同形**(否则成了存在性探测器)")
    d4 = 拿(甲tok, "这个订单号根本不存在")
    ck("不存在的订单号也走同一个「看不到」形状", bool(d4.get("看不到")), d4.get("为什么", ""))
    ck("两种情况的键集一模一样(外人分不出哪种)",
       sorted(d3) == sorted(d4), (sorted(d3), sorted(d4)))

    print("\n▸ ④ 没登录 → 看不到(**不默认成最低权限然后给点东西**)")
    d5 = 拿("压根不存在的token", 经手[0]["id"])
    ck("没登录 → 看不到", bool(d5.get("看不到")), d5.get("为什么", ""))
    ck("理由说的是「不知道你是谁」", "不知道你是谁" in str(d5.get("为什么")))

    print("\n▸ ⑤ 店长看本店,**异店要拦**")
    本店单 = q("SELECT id FROM ordr WHERE shop=? LIMIT 1", 店们[0]["shop"])
    异店单 = q("SELECT id FROM ordr WHERE shop<>? AND shop IS NOT NULL LIMIT 1",
              店们[0]["shop"])
    长tok = _发个token(dict(店们[0]))
    if 本店单:
        ck("店长看本店的单 → 看得到", not 拿(长tok, 本店单[0]["id"]).get("看不到"))
    if 异店单:
        d6 = 拿(长tok, 异店单[0]["id"])
        ck("🔑 店长看别店的单 → 看不到", bool(d6.get("看不到")), d6.get("为什么", ""))
        ck("理由说的是「不在你的门店」", "不在你的门店" in str(d6.get("为什么")))
    ck("店长那一档**不带标**(标只对顾问有意义,不编一个出来)",
       (拿(长tok, 本店单[0]["id"]).get("我的标") or []) == [] if 本店单 else True)

    print("\n▸ ⑥ 总部运营看全部")
    d7 = 拿(运tok, 无关[0]["id"])
    ck("运营看任意一单 → 看得到", not d7.get("看不到"), d7.get("为什么", ""))
    ck("范围那一栏写的是「全部门店」", d7.get("看的范围") == "全部门店", d7.get("看的范围"))

    print("\n▸ ⑦ 手机号脱敏(和别处同一条规矩)")
    客 = (d7.get("客户") or {})
    真 = q("SELECT phone FROM customer WHERE id=?",
          (d7.get("订单") or {}).get("customer_id"))
    if 真 and (真[0]["phone"] or ""):
        ck("客户手机号是脱敏的",
           客.get("phone") != 真[0]["phone"] and "****" in str(客.get("phone")),
           客.get("phone"))
    else:
        print(f"  {Y}⏸{D} 这个客户没手机号 —— 换不出样本,**不适用**")

    print("\n▸ ⑧ 弹窗给的东西够不够(客户 / 明细 / 订单本身)")
    for k in ("订单", "客户", "明细", "看的范围"):
        ck(f"返回里有「{k}」", k in d7)
    ck("明细是一行行的件(不是一个总额)", isinstance(d7.get("明细"), list))

    print("\n▸ ⑨ 🔑 **两种表示要给出同一份名单** —— SQL 过滤 vs 纯判定")
    # 卡片那头不可能把 31660 单全捞出来逐条判,所以它写 SQL;
    # 弹窗那头按订单号判一单,所以它调纯判定。**同一套口径,两种表示。**
    # > 一份 SQL 过滤和一份纯判定,**在各自的测试里都绿** ——
    # > 而它们可以给出不同的名单。两种表示必须拿真数据对账,
    # > 否则漂了的那天表现是「卡片列着而点开说看不到」。
    import sys as _s2, os as _o2
    _s2.path.insert(0, os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), "knowledge"))
    _s2.path.insert(0, os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))), "backend"))
    import order_scope as 范
    import api as _api

    样本 = q("""SELECT o.id, o.shop, o.advisor_no, cu.advisor_no gui
                  FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id
                 ORDER BY o.created DESC LIMIT 400""")
    ck("对账样本不是空的(**空集合上两边永远一致**)", len(样本) >= 50, len(样本))

    for 谁 in (甲, dict(店们[0]), 运):
        条, 参, 话, 顾号 = _api._订单范围(谁)
        ids = {r["id"] for r in q(
            f"""SELECT o.id FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id
                 WHERE o.id IN ({','.join('?' * len(样本))}){条}""",
            *[r["id"] for r in 样本], *参)}
        纯 = {r["id"] for r in 样本
             if 范.看得到吗(角色=谁.get("role"), 工号=谁.get("no"),
                        门店=谁.get("shop"), 单的门店=r["shop"],
                        单的顾问=r["advisor_no"], 客户归属顾问=r["gui"])[0]}
        多 = sorted(ids - 纯)[:3]
        少 = sorted(纯 - ids)[:3]
        ck(f"{谁['role']}:SQL 选出的和纯判定说能看的**一模一样**"
           f"(SQL {len(ids)} / 判定 {len(纯)})",
           ids == 纯, f"SQL 多给 {多} · SQL 少给 {少}")
        # ⚠️ 两个方向都要报:**SQL 多给是洞,SQL 少给是功能缺** —— 下一步完全不同
        if ids != 纯:
            坏.append(f"{谁['role']} 两种表示对不上")
        ck(f"{谁['role']}:`范围话` 两头一致",
           话 == 范.范围话(角色=谁.get("role"), 门店=谁.get("shop")), 话)

    # 🔑 对照组:**这个对账真的能抓到错吗** —— 拿一个故意错的范围过一遍。
    # > 一条「两边恰好都对」的对账,和一条「它压根比不出差别」的,
    # > **在那个 ✅ 上长得一模一样。**
    假顾问 = dict(甲, no="压根不存在的工号")
    条2, 参2, _, _ = _api._订单范围(假顾问)
    ids2 = {r["id"] for r in q(
        f"""SELECT o.id FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id
             WHERE o.id IN ({','.join('?' * len(样本))}){条2}""",
        *[r["id"] for r in 样本], *参2)}
    纯甲 = {r["id"] for r in 样本
          if 范.看得到吗(角色=甲.get("role"), 工号=甲.get("no"), 门店=甲.get("shop"),
                     单的门店=r["shop"], 单的顾问=r["advisor_no"],
                     客户归属顾问=r["gui"])[0]}
    ck("🔑 换一个工号之后两边**确实不一样**了(说明这条对账比得出差别)",
       ids2 != 纯甲, f"换工号后 SQL 给 {len(ids2)} 条,甲的判定给 {len(纯甲)} 条")

    print("\n▸ ⑩ 弹窗里的商品信息 / 图 / 定制内容(业务 2026-10-06 追加的)")
    定 = q("SELECT id FROM ordr WHERE kind='定制品订单' LIMIT 1")
    标 = q("SELECT id FROM ordr WHERE kind='标品订单' LIMIT 1")
    if not 定 or not 标:
        print(f"  {Y}⏸{D} 库里缺定制单或标品单样本 —— **不适用,不是通过**")
    else:
        dz = 拿(运tok, 定[0]["id"])
        bz = 拿(运tok, 标[0]["id"])
        件 = (dz.get("明细") or [{}])[0]
        ck("定制件带上了商品信息", bool((件.get("商品") or {}).get("name")),
           (件.get("商品") or {}).get("name"))
        ck("带上了类目全路径(不是一个 category 编码)",
           "-" in str(件.get("类目全路径") or ""), 件.get("类目全路径"))
        ck("带上了商品介绍", (件.get("商品") or {}).get("介绍") is not None)

        # ── 🔑 图必须带出处 ────────────────────────────────────
        # 库里**没有「实物照片」这一档** —— 只有 AI 生成图和现画剪影。
        # > 一张现画的剪影,和一张 AI 效果图,**在那个图片框里长得一模一样** ——
        # > 而顾问可能拿它给客户看,客户会以为那就是实物。
        图 = 件.get("图") or {}
        ck("图带上了主图", bool(图.get("主图")), 图.get("主图"))
        ck("🔑 图带上了**出处**(生成图 / 示意图)",
           图.get("出处") in ("生成图", "示意图"), 图.get("出处"))
        ck("🔑 而且明说**两种都不是实物照片**",
           "不是实物照片" in str(图.get("⚠️")), str(图.get("⚠️"))[:40])
        # 反向:`图来源` 只认栅格图,所以这两种**必须都出现过**才算验到。
        # > 一个「只跑过生成图那一支」的检查,和一个两支都跑过的,
        # > **在那个 ✅ 上长得一模一样。**
        出处们 = {(_件.get("图") or {}).get("出处")
                for _oid in [r["id"] for r in q(
                    "SELECT id FROM ordr ORDER BY created DESC LIMIT 25")]
                for _件 in (拿(运tok, _oid).get("明细") or [])}
        出处们.discard(None)
        ck("最近 25 单里图的出处取值都在那两种之内", 出处们 <= {"生成图", "示意图"}, 出处们)
        if len(出处们) < 2:
            print(f"     {Y}⚠{D} 只见到 {出处们} 这一种 —— "
                  f"**另一支没在真数据上跑过**(全库的图都出齐了,或者都没出)")

        # ── 🔑 定制内容逐部件,而且两个加价都报 ────────────────
        cz = 件.get("定制内容") or {}
        ck("🔑 定制件有「定制内容」", bool(cz), sorted(cz)[:4])
        ck("定制内容是**逐部件**的,不是一句话",
           isinstance(cz.get("逐部件"), list) and len(cz["逐部件"]) >= 1,
           len(cz.get("逐部件") or []))
        ck("每一条都说得出部件和种类",
           all(x.get("part") and x.get("kind") for x in (cz.get("逐部件") or [])),
           [(x.get("part"), x.get("kind")) for x in (cz.get("逐部件") or [])][:3])
        ck("🔑 **两个加价都报了**(选项标的 / 订单行上的)",
           cz.get("选项标的加价合计") is not None
           and cz.get("订单行上的加价") is None  # 键名别写错
           and cz.get("订单行上的定制加价") is not None,
           (cz.get("选项标的加价合计"), cz.get("订单行上的定制加价")))
        # 对不上时要标出来,对得上时**不许有那条警告**
        差 = abs(float(cz.get("选项标的加价合计") or 0)
                - float(cz.get("订单行上的定制加价") or 0))
        if 差 > 0.01:
            ck("两个加价对不上 → 标出来了", "⚠️ 两个加价对不上" in cz)
        else:
            ck("两个加价对得上 → **不该有那条警告**(不乱报)",
               "⚠️ 两个加价对不上" not in cz)
        ck("带上了这一款的可选范围(形制/面料/工艺/工期)",
           bool(cz.get("这一款的可选范围")), sorted(cz.get("这一款的可选范围") or {}))

        # ── 标品单:**不该有定制内容**,而且不是空壳 ──────────
        # > 一件「标品」和一件「定制而明细丢了」的,
        # > **在「没有定制内容」这件事上长得一模一样** ——
        # > 所以收了定制加价却没明细要单独报(上面那条路)。
        标件 = (bz.get("明细") or [{}])[0]
        ck("标品件**没有**「定制内容」那一段", "定制内容" not in 标件,
           sorted(标件)[:6])
        ck("而标品件照样带商品信息和图",
           bool((标件.get("商品") or {}).get("name")) and bool(标件.get("图")))

    print("\n" + "=" * 92)
    if 坏:
        print(f"{R}❌ 聊天查订单权限 {len(坏)} 条不过(过 {过[0]}){D}")
        for b in 坏:
            print("    ❌", b)
        return 1
    print(f"{G}✅ 聊天查订单权限 {过[0]} 条全过{D}")
    print("    ⚠️ 这份只验**弹窗那一头**(按订单号取数)。"
          "卡片那一头在 `tools/chat_order_cards_check.py`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
