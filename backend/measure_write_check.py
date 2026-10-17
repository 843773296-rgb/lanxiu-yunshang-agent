#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量体录入写口的检查 —— 在库的**临时副本**上跑,真库一行都不碰(同 fitting_write_check)。

钉的几件事:
    权限     顾问 / 店长能录;版师、工匠不能;别店客户不能;没登录不能
    同意     没有身体数据同意不能录;未满 14 岁缺监护人同意不能录
    校验     远程不算数;三个条件缺一件拒;胸围 8.6 拒(不替人改)
    绑定     下单量体绑到那一件;那一件不是给这个人做的 → 拒;标品 → 拒
    记账     量体人记的是登录的人;以哪次为准能读到这次
"""
import os, sys, shutil, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("把量体录入的身体数据同意那道门去掉", "没有身体数据同意 → 拒"),
    ("让绑订单行时不查「这一件是不是给这个人做的」", "那一件不是给这个人做的 → 拒"),
    # 2026-10-18:这条判据从「总数 ≤ 上限」换成「每一件都说得出来历 + 三类各自只许降」,
    # 预期红跟着换。⚠️ **同一条咬合的预期红有两份** —— 这里一份(给人读)、
    # `tools/bite_specs.json` 一份(给执行器跑)。我这次只改了后者,
    # 门禁里 `bite_check` 当场逮到这边指着一句不存在的话:
    # **靠「特意记得同步两处」维持的一致性,迟早会漏一次,而这次就是那一次。**
    ("删掉一件定制单的下单量体(造数步骤漏补)",
     "没有下单量体的定制单都说得出来历"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:140]) if extra else ''}")
    if not ok: FAIL.append(name)


def main():
    print("量体录入写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="measw-")
    T = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.path.join(HERE, "lanxiu.db"), T)
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 量体录入写口 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 量体录入写口 {N[0]} 条全过\033[0m")


# **没有下单量体的定制单件数上限** —— 业务 09-22:「每一个订单都需要有绑定的下单量体数据」。
#
# ⚠️ **2026-10-17 从 11 降到 4。** 全量咬合重放逮到这条是假绿:那条咬合
# (删掉一件定制单的下单量体)删完变 5 件,**离上限 11 还差 6 格,当然不红** ——
# 棘轮松了 7 格,等于那段时间可以凭空造出 7 件没量体的定制单而门禁全绿。
# > 一道「钉着的闸」和一道「松了 7 格的闸」,在那个绿勾上长得一模一样。
#
# 降之前先量了会不会漂(这个数要是随世界日期整批换,钉死任何值都会让 CI 随机变红 ——
# 「没走正门关的」那个数就是这么坑过一轮的):并行会话在同一个提交上、
# 把世界日期分别钉在 10-16 / 10-17 各从零重建一次,**两次都是 4 件**,不漂。
#
# 现在这 4 件:着装人没定的 1 件(不猜给谁量)+ 有着装人却没量的 3 件
# (待付款 1 / 生产中 1 / 完成 1 —— 这 3 件是真缺口,要造数补,不是判据该放过的)。
# 只许降不许涨:哪个造数步骤又造出没绑下单量体的定制单,这里当场红。
# **「待确认」的单不算**:开了单还没确认下单,还没量是正常的 —— 那正是确认下单那道闸要拦的
# (重建第 20 步故意造了几张「没量」的待确认单做活用例)。
# ⚠️ **2026-10-18 从「一个总数」换成「三类各自钉死」。**
#
# 换掉的理由不是那个数字太小,是**它量错了东西**:并行会话钉同一个提交、
# 7 个世界日期各从零重建一次,**7 次都是 5 件、而且是同一批号** ——
# 也就是说「总数 ≤ 4」这道闸在 CI 上一直红着(本机 4 件刚好等于上限,所以本机一直绿,
# 这是「本地绿、CI 红」的又一例,而成因是**本机这个库太老**:
# 手术过、`run_journey` 追加过,缺的那一批根本不是同一批号)。
#
# 而查下去发现更要紧的一件:**这几件一件都不是造数漏补,全是故意留的夹具。**
# `tools/backfill_order_measure.py` 有三条带着原因的跳过:
#   · 着装人没定 —— **不猜给谁量**;
#   · 着装人在 `夹具着装人集` 里 —— 王清和那件「量体过期 199 天还下了单」,
#     供「超期量体不许下单」和边界审计用;
#   · 那位客户的量体记录不全 —— 王雨桐,`seed` 故意删到 3 项,
#     供「量体记录不全 → 我方免费改」的判责规则用。
# 所以 10-17 我写在这儿的那句「**这 3 件是真缺口,要造数补**」**是错的** ——
# 补上去会把后两条判责规则的用例一起消掉(09-22 重建当场撞过一次)。
#
# 📌 **换法照 `queue_closed_check` 那次**:它原来是「没走正门关的总数 ≤ 166」,
#    随世界日期整批漂;换成「**每一条都说得出是谁关的**,说不出的 = 0」之后
#    既更严又不漂,注释里还留了禁区「别把基线抬成 167」——
#    而我差点在这条上正好去抬那个基线。
#    > 一道「总数没超」的闸和一道「每一件都说得出来历」的闸,
#    > 在今天这个库上长得一模一样;换一天、或者换一台机器,就分出来了。
#
# ⚠️ **诚实记一笔:三类上限加起来(1+3+2=6)比原来那个 4 大。**
#    但原来那个 4 **在 CI 上拦住的是正常状态**(从零建就是 5 件),它不是一道有效的闸;
#    而「落不进三类的 = 0」是**从无到有**的新硬闸。所以这不是放宽一道有效的闸,
#    是把一道拦不住的换成四道拦得住的。每一类都**只许降**。
#
# 这三个数取的是「本机和从零建两边都过得去的最严上界」:
#   着装人没定   本机 1 / 从零 1 → 1
#   超期量体夹具 本机 1 / 从零 3 → 3   ⚠️ 从零建时王清和身上挂了 3 张,见下面那条待做的
#   记录不全夹具 本机 2 / 从零 1 → 2
着装人没定的上限 = 1
超期量体夹具的上限 = 3
记录不全夹具的上限 = 2

# ⚠️ **一件待做的(不在这条判据里修)**:按名单判之后,夹具那两类的**件数还会长** ——
# 造数(`run_journey` / 推进存量)会继续往王清和身上挂新的定制单,每一张都没量体。
# 治根是「造数挑人时跳过夹具着装人」,但那动的是造数挑人:会让整批 rng / 下标平移
# (10-17 刚踩过一次,4 个「名字就是判据」的夹具全改了名),那几张单会挂到别人头上,
# 销量 / 客单 / RFM 分档 / 排行榜窗口全动,得配一次全量门禁 + 全量咬合重放才敢推。
# 而且它和「挑合并用例按编号前缀认」是同一块地方,该一起改一起验。
# **现在钉 3 不是放水,是给治根留的台阶** —— 治根做完那一类自然降到 1 件,而闸只许降。


def run(T):
    import api, oplog, measure_write as mw, measure
    _c0 = sqlite3.connect(T)
    # ⚠️ 取号不只取数:**涨了的时候得说得出是哪几件**,否则下一个人只能自己写 SQL 去找。
    _缺行 = _c0.execute("""SELECT i.id, o.status, i.wearer_id FROM ordr_item i
                             JOIN ordr o ON o.id=i.order_id
                           WHERE o.kind='定制品订单' AND o.status!='待确认'
                             AND NOT EXISTS(SELECT 1 FROM measure_rec m WHERE m.order_item_id=i.id)
                           ORDER BY i.id""").fetchall()
    _c0.close()
    缺 = len(_缺行)
    # 按「**为什么**没有」分类。三类都是有意的,落不进三类的才是真缺口。
    # 名单从 `fix_order_measure` 取,**不另抄** —— 它是那两个夹具的单一真相源。
    import fix_order_measure as _FX
    _超期名单, _不全名单 = set(_FX.夹具着装人集), set(_FX.记录不全的夹具着装人)
    _没定 = [r for r in _缺行 if not r[2]]
    _超期 = [r for r in _缺行 if r[2] in _超期名单]
    _不全 = [r for r in _缺行 if r[2] in _不全名单]
    _说不出 = [r for r in _缺行 if r[2] and r[2] not in _超期名单 and r[2] not in _不全名单]

    def _号(行s):
        return ("、".join(f"#{r[0]}({r[1]}/{r[2] or '着装人没定'})" for r in 行s[:8])
                + (" …" if len(行s) > 8 else ""))

    # 总件数**只打印不判红** —— 它按设计随库的年龄和世界日期走(本机 4 / 从零建 5),
    # 判红就是在量「这个库上碰巧有几件」。这是这个项目反复用的那个拆法:
    # 「代码对不对」判红,「这个库上碰巧有几件」只报数。
    print(f"     ℹ️ 没有下单量体的定制单现在 {缺} 件(**只打印不判红**,分类上限在下面逐条判):"
          f"着装人没定 {len(_没定)} · 超期量体夹具 {len(_超期)} · 记录不全夹具 {len(_不全)}"
          f" · **说不出来历 {len(_说不出)}**")
    ck("每一件没有下单量体的定制单都说得出来历(业务 09-22:每一个订单都要有)",
       not _说不出,
       # ⚠️ 只在**真有**说不出来历的时候才说这句 —— 绿着还印「是真缺口」,
       # 读日志的人会以为出事了。(这个文件的 ck 不管绿红都打印附注。)
       (_号(_说不出) + " —— 这几件落不进三类有意跳过里,**是真缺口**:"
        "要么某个造数步骤漏补了下单量体,要么它是个新的夹具而没人点名")
       if _说不出 else "")
    ck(f"「着装人没定」这一类 ≤ {着装人没定的上限} 件(只许降)",
       len(_没定) <= 着装人没定的上限, _号(_没定))
    ck(f"「超期量体夹具」这一类 ≤ {超期量体夹具的上限} 件,而且着装人都在点名名单里(只许降)",
       len(_超期) <= 超期量体夹具的上限, _号(_超期) + f" —— 名单:{sorted(_超期名单)}")
    ck(f"「记录不全夹具」这一类 ≤ {记录不全夹具的上限} 件,而且着装人都在点名名单里(只许降)",
       len(_不全) <= 记录不全夹具的上限, _号(_不全) + f" —— 名单:{sorted(_不全名单)}")
    for m in (api, oplog, mw): m.DB = T
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row
    # **按性质挑人,不钉死编号**:一个有身体数据同意的成年着装人,名下有一件定制单是给他做的
    r = c.execute("""SELECT w.id wid, c.shop, i.id iid, i.order_id oid FROM wearer w
                     JOIN customer c ON c.id=w.customer_id
                     JOIN ordr_item i ON i.wearer_id=w.id JOIN ordr o ON o.id=i.order_id
                     WHERE o.kind='定制品订单' AND w.birthday <= '2000-01-01'
                       AND EXISTS(SELECT 1 FROM consent k WHERE k.wearer_id=w.id AND k.scope='身体数据'
                                  AND k.revoked_at IS NULL)
                     ORDER BY w.id LIMIT 1""").fetchone()
    ck("有一个带同意、名下有定制单的成年着装人", bool(r))
    if not r: return
    wid, shop, iid, oid = r["wid"], r["shop"], r["iid"], r["oid"]
    人 = lambda role, 店=None, 别=None: (lambda x: dict(x) if x else None)(c.execute(
        "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用'"
        + (" AND shop=?" if 店 else "") + (" AND shop!=?" if 别 else "") + " ORDER BY no LIMIT 1",
        [role] + ([店] if 店 else []) + ([别] if 别 else [])).fetchone())
    顾问, 版师, 别店 = 人("顾问", shop), 人("版师"), 人("顾问", 别=shop)
    ck("本店顾问、版师、别店顾问都找得到", bool(顾问 and 版师 and 别店))
    if not (顾问 and 版师 and 别店): return
    好 = dict(wearer_id=wid, values={"胸围": 86, "腰围": 68, "衣长": 110}, method="到店",
              inner="薄", shoe="赤足", breath="平静呼气")

    with api.as_user(版师): x = api.record_measure(**好)
    ck("版师不能录", x.get("code") == "ROLE", x.get("reason"))
    with api.as_user(别店): x = api.record_measure(**好)
    ck("别店顾问不能录本店客户", x.get("code") == "OTHER_SHOP", x.get("reason"))
    ck("没登录不能录", bool(api.record_measure(**好).get("error")))
    with api.as_user(顾问): x = api.record_measure(**{**好, "method": "远程"})
    ck("远程 → 不算数", x.get("code") == "BAD_MEASURE" and "远程" in x.get("reason", ""), x.get("reason"))
    with api.as_user(顾问): x = api.record_measure(**{**好, "shoe": ""})
    ck("缺「鞋」→ 拒", x.get("code") == "BAD_MEASURE", x.get("reason"))
    with api.as_user(顾问): x = api.record_measure(**{**好, "values": {"胸围": 8.6}})
    ck("胸围 8.6 → 拒(不替人改)", x.get("code") == "BAD_MEASURE", x.get("reason"))

    # 同意
    c.execute("UPDATE consent SET revoked_at='2026-01-01' WHERE wearer_id=? AND scope='身体数据'", (wid,)); c.commit()
    with api.as_user(顾问): x = api.record_measure(**好)
    ck("没有身体数据同意 → 拒", x.get("code") == "NO_CONSENT", x.get("reason"))
    c.execute("UPDATE consent SET revoked_at=NULL WHERE wearer_id=? AND scope='身体数据'", (wid,)); c.commit()

    # 14—18 周岁(业务 10-10 晚,knowledge/consent_age.py):本人为准,家长付款的家长也签 —— 在副本上真去撤
    import worldclock
    世界 = worldclock.今天().isoformat()
    少 = c.execute("""SELECT w.id FROM wearer w JOIN customer cu ON cu.id=w.customer_id
                      WHERE cu.shop=? AND w.relation!='本人' AND date(w.birthday,'+14 years')<=? AND date(w.birthday,'+18 years')>?
                        AND EXISTS(SELECT 1 FROM consent k WHERE k.wearer_id=w.id AND k.scope='身体数据' AND k.relation='本人'
                                   AND k.revoked_at IS NULL)
                        AND EXISTS(SELECT 1 FROM consent k WHERE k.wearer_id=w.id AND k.scope='身体数据' AND k.relation LIKE '监护人%'
                                   AND k.revoked_at IS NULL)
                      ORDER BY w.id LIMIT 1""", (shop, 世界, 世界)).fetchone()
    ck("有一位本店、家长付款、两签都齐的 14—18 周岁着装人(空集合上什么都成立)", bool(少))
    if 少:
        少好 = {**好, "wearer_id": 少[0]}
        c.execute("UPDATE consent SET revoked_at='2026-01-01' WHERE wearer_id=? AND scope='身体数据' AND relation='本人'", (少[0],)); c.commit()
        with api.as_user(顾问): x = api.record_measure(**少好)
        ck("14—18 周岁只有家长签 → 拒(本人为准)", x.get("code") == "NO_SELF_CONSENT", x.get("reason"))
        c.execute("UPDATE consent SET revoked_at=NULL WHERE wearer_id=? AND relation='本人'", (少[0],))
        c.execute("UPDATE consent SET revoked_at='2026-01-01' WHERE wearer_id=? AND scope='身体数据' AND relation LIKE '监护人%'", (少[0],)); c.commit()
        with api.as_user(顾问): x = api.record_measure(**少好)
        ck("家长付款的 14—18 周岁只有本人签 → 拒(身体数据要家长也确认)", x.get("code") == "NO_PARENT_COSIGN", x.get("reason"))
        c.execute("UPDATE consent SET revoked_at=NULL WHERE wearer_id=? AND scope='身体数据'", (少[0],)); c.commit()

    # 平时的量体
    前 = c.execute("SELECT COUNT(*) FROM measure_rec").fetchone()[0]
    with api.as_user(顾问): x = api.record_measure(**好)
    ck("登记一次平时的量体", bool(x.get("ok")) and x.get("绑定订单行") is None, x.get("reason"))
    ck("写进去的行数 = 项数", c.execute("SELECT COUNT(*) FROM measure_rec").fetchone()[0] - 前 == 3)
    ck("量体人记的是登录的人", c.execute("SELECT DISTINCT measured_by_no FROM measure_rec WHERE measured_at=? "
                                        "AND wearer_id=?", (x["时间"], wid)).fetchone()[0] == 顾问["no"])

    # 下单量体
    with api.as_user(顾问): x = api.record_measure(**{**好, "values": {"腰围": 69, "衣长": 118},
                                                     "order_id": oid, "item": str(iid)})
    ck("登记这一件的下单量体", bool(x.get("ok")) and x.get("绑定订单行") == iid, x.get("reason"))
    记 = [dict(着装人=q["wearer_id"], 时间=q["measured_at"], 量体人=q["measured_by_no"], 方式=q["method"],
              项=q["name"], 值=q["value"], 订单行=q["order_item_id"])
         for q in c.execute("SELECT r.*, i.name FROM measure_rec r JOIN measure_item i ON i.code=r.item "
                            "WHERE r.wearer_id=?", (wid,))]
    s, _ = measure.以哪次为准(measure.场次(记), 订单行=iid)
    ck("以哪次为准读到的就是这次下单量体(衣长 118)", bool(s) and s["值们"].get("衣长") == 118)
    别人 = c.execute("SELECT i.id FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                    "WHERE o.id=? AND COALESCE(i.wearer_id,'')!=?", (oid, wid)).fetchone() or \
          c.execute("SELECT i.id, i.order_id FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                    "WHERE o.kind='定制品订单' AND COALESCE(i.wearer_id,'')!=? AND o.shop=? LIMIT 1",
                    (wid, shop)).fetchone()
    if 别人:
        _oid = 别人["order_id"] if "order_id" in 别人.keys() else oid
        with api.as_user(顾问): x = api.record_measure(**{**好, "order_id": _oid, "item": str(别人["id"])})
        ck("那一件不是给这个人做的 → 拒", x.get("code") == "WRONG_WEARER", x.get("reason"))
    标 = c.execute("SELECT i.id, o.id oid FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                  "WHERE o.kind='标品订单' LIMIT 1").fetchone()
    if 标:
        with api.as_user(顾问): x = api.record_measure(**{**好, "order_id": 标["oid"], "item": str(标["id"])})
        ck("标品不做下单量体 → 拒", x.get("code") == "NOT_CUSTOM", x.get("reason"))


if __name__ == "__main__":
    main()
