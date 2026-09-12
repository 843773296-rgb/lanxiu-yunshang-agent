# -*- coding: utf-8 -*-
"""下单前置规则的两件事:**订单填上着装人** + **量体不许超期**:定制订单下单时,着装人的量体必须在复量周期内。

一份代码,两个调用方:`seed.py` 末尾跑一遍(新库一开始就对),
`tools/migrate_order_measure.py` 对老库跑一遍。
**两条路都得对** —— 只改一边的话,下一个人 reseed 会得到一个不一样的库。

## 为什么原来会生成出违规数据

`seed.py` 里量体日期是 `f"2026-0{6+k%3}-1{k%9} 14:30"` ——
**纯按序号生成,既不看着装人年龄,也不看下单日期**。
于是出现两种坏数据:

    ① 量体比订单还晚(C10026:量体 08-18 14:30,下单同日 09:46)
       —— 这是纯粹的生成器 bug,没有业务含义
    ② 孩子的量体停在半年多以前(王清和 199 天 / 刘星野 272 天,允许 180 天)
       —— 复量周期对未成年是 180 天甚至 120 天,而生成器不知道这回事

## 但**不能全修掉**

`seed.py` 的反例夹具那段写着:
「没有用例的规则可以是错的,而且永远不会被发现 —— **反例在种子数据里是资产**。」

全修完的话,「超期量体不许下单」这条规则**一个用例都没有**,
`order_gate_check` 的锚点会失去它要钉的东西,而检查照样全绿。

所以**留一个,而且是显式留的**:刘星野(11 岁,量体过期 272 天)。
挑他不挑王清和,是因为他超期最狠 —— 边界附近的那个(199/180)
容易被一次无关的数据调整推回合规,**而夹具不该那么脆**。
"""
import os, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import knowledge.growth as G

# **故意留着不修的那些。** 改这里之前先读上面第三段。
#
# ⚠️ 第一版只留了 W10013-2,结果把 W10010-2 修好了 ——
# 而 `boundary_audit.a_expired_order` 写死用的就是 W10010-2。
# **它早就是一个夹具,只是没人声明过。**
# 一个没被声明的资产,和垃圾长得一模一样,下一个人照样会「好心把它补全」。
#
# 所以现在夹具**只有这一处声明**,`boundary_audit` 和 `order_gate_check`
# 都从这儿取 —— 谁要改夹具,改这一行,两边一起跟。
夹具着装人集 = ("W10010-2", "W10013-2")
夹具着装人 = 夹具着装人集[1]      # boundary_audit 之外的地方用它当代表
夹具说明 = ("刘星野(11 岁)过期 272 天 / 王清和(9 岁)过期 199 天 —— "
            "供「超期量体不许下单」和边界审计用")


def assign_wearers(conn, verbose=True):
    """给订单填「这一单是给谁做的」。**只填能说出理由的,定不了的留空。**

    两档能定:
      ① 客户名下**只有一个**在用着装人 —— 没有别的可能
      ② 多个候选,但**只有一个在下单前量过体** —— 定制不能凭空裁,
         家里只有一个人量过,这单就只能是给他做的

    **两个人都量过的留空**,下单校验会报「判不了」——
    **判不了不等于可以**。猜错的代价不对称:猜对了没人知道,
    猜错了这一单会拿着另一个人的尺寸去裁剪,而报表上完全正常。

    这份逻辑原来只活在迁移脚本里,于是 `seed.py` 生成的新库
    `wearer_id` 全是 NULL —— 规则一条都跑不到,而检查报的是「样本量 0」。
    **老库迁移和新库生成,两条路都要对。**
    """
    import sqlite3 as _sq
    conn.row_factory = _sq.Row
    c = conn
    定, 留空 = 0, 0
    for o in c.execute("SELECT id,customer_id,created,wearer_id FROM ordr").fetchall():
        if o["wearer_id"]:
            continue
        ws = c.execute("SELECT id,name FROM wearer WHERE customer_id=? AND status='在用' "
                       "ORDER BY id", (o["customer_id"],)).fetchall()
        pick = None
        if len(ws) == 1:
            pick = ws[0]["id"]
        elif len(ws) > 1:
            量过 = [w for w in ws if c.execute(
                "SELECT COUNT(*) FROM measure_rec WHERE wearer_id=? AND measured_at<=?",
                (w["id"], o["created"])).fetchone()[0]]
            if len(量过) == 1:
                pick = 量过[0]["id"]
        if pick:
            c.execute("UPDATE ordr SET wearer_id=? WHERE id=?", (pick, o["id"]))
            定 += 1
        else:
            留空 += 1
    if verbose:
        print(f"  [着装人] 定了 {定} 单,留空 {留空} 单"
              f"(定不了的报「判不了」,**判不了不等于可以**)")
    return 定, 留空


def enforce(conn, today=None, verbose=True):
    """把违规的量体日期挪到合规位置。**返回 (修了几条, 留着的夹具)。**

    只挪**日期**,不改测量值 —— 现实里复量拿到的数会变,
    但这里要的是「这条规则有没有在跑」,不是「尺寸准不准」。
    改值会顺带动到版型推档、成长预测那几条链,**改动面越小越好查**。
    """
    conn.row_factory = __import__("sqlite3").Row
    c = conn
    fixed, kept = [], None
    for o in c.execute("SELECT id,created,kind,wearer_id FROM ordr "
                       "WHERE wearer_id IS NOT NULL AND kind='定制品订单'").fetchall():
        w = c.execute("SELECT id,name,gender,birthday FROM wearer WHERE id=?",
                      (o["wearer_id"],)).fetchone()
        if not (w and w["birthday"] and w["gender"]):
            continue
        day = o["created"][:10]
        # ⚠️ **和 `order_gate_check` 用同一个比较** —— 取「下单时刻之前」最近的一条,
        # 按**时间戳**比,不按日期比。
        #
        # 第一版按日期写成 `measured_at[:10] < day`(严格早于下单那一天),
        # 于是把 **33 条「当天量体、当天下单」判成了违规** ——
        # 而那恰恰是最正常的流程:顾问上门量完体,客户当场就定了。
        # 一次跑下来改了 33 条日期,**每一条看起来都很有道理**。
        #
        # 教训是老的那条:**同一个判定不许有两套实现。**
        # 检查那边用 `measured_at<=created`,这边用日期比大小,
        # 两边差的就是「当天」这一档,而它正是最常见的一档。
        m = c.execute("SELECT rowid AS rid,measured_at FROM measure_rec WHERE wearer_id=? "
                      "AND measured_at<=? ORDER BY measured_at DESC LIMIT 1",
                      (w["id"], o["created"])).fetchone()
        # 这一条是不是故意留的夹具
        if w["id"] in 夹具着装人集:
            kept = (w["name"], (m["measured_at"][:10] if m else "无"), day)
            continue
        if m:
            exp = G.measure_expired(w["gender"], w["birthday"], m["measured_at"][:10], day)
            if not exp["过期"]:
                continue
        # 没有下单前的量体,或者有但超期了 —— 两种都要挪一条到合规位置。
        m = m or c.execute("SELECT rowid AS rid,measured_at FROM measure_rec "
                           "WHERE wearer_id=? ORDER BY measured_at LIMIT 1",
                           (w["id"],)).fetchone()
        if not m:
            continue
        # 挪到「下单前、周期之内」的中间位置 —— 现实里就是
        # 顾问发现超期、叫客户来复量,然后才下单。
        days, _ = G.recheck_cycle(w["gender"], G.age_at(w["birthday"], day))
        提前 = max(1, min(days - 1, days // 3))
        新 = (datetime.date.fromisoformat(day) - datetime.timedelta(days=提前)).isoformat()
        旧日 = m["measured_at"][:10]
        c.execute("UPDATE measure_rec SET measured_at=? WHERE wearer_id=?",
                  (f"{新} 14:30", w["id"]))
        # **推算留档要跟着走。** `spec_check` 的 G3 要求
        # 「推算留档能追到它依据的那次量体」—— 挪了量体日期不挪留档,
        # 那条链当场断掉,而且断在一个和这次改动**看起来毫无关系**的检查里。
        # 改数据的连带后果,往往比改动本身更难查。
        c.execute("UPDATE growth_forecast SET base_at=? WHERE wearer_id=? AND base_at=?",
                  (新, w["id"], 旧日))
        fixed.append((w["name"], m["measured_at"][:10], 新, day))
    if verbose:
        for nm, old, new, day in fixed:
            print(f"  [修] {nm}:量体 {old} → {new}(下单 {day})")
        if kept:
            print(f"  [留] {kept[0]}:量体 {kept[1]},下单 {kept[2]} —— **反例夹具**,"
                  f"{夹具说明}")
    return len(fixed), kept
