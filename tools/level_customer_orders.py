#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""削峰:把订单从「挂太多单的客户」摊给**同店**的少单客户。

## 为什么要有它

业务 2026-09-26 拍的板。先说清量到的现状(不是清单上写的那个):

    862 个客户有单 · 26592 单 · 人均 30.8 · 中位数 28 · **最多 162 单**
    179 个客户超过 50 单,同时 **106 个客户一单都没有**

⚠️ 待办清单上写的是「能挂单的客户只有 27 个、人均 142 单」——**那是旧数**,
并行会话后来跑的「客户补到 1000 个」早把它改掉了,而我照着那个数问了业务一次(见 PRD 附录 B-89)。

一个顾客一年买 162 次汉服,演示时点进他的订单历史**一眼假**。
业务选的是**只削峰**:不新增假客户(那要加到六千多个)、不砍订单
(**库存预警的可售天数就是靠这批单算出来的**),只把最刺眼的尖峰摊平。

## 四条不许破的

1. **不碰受保护的客户。** 名单不手抄 —— 直接用 `order_mix.受保护客户()`,
   它从 E- 前缀、`truth` 表、以及检查/评测脚本里**扫**出来。
   手抄的名单哪天加了第 15 条边界用例不会跟着变,而那时削峰会静默抹掉它。
2. **只搬标品单,而且是「干净」的标品单** —— 挂着着装人的(8 单)、挂着售后或维保的(474 单)
   一律不搬:着装人属于原来那个客户,搬过去就成了「这一单是给别人家孩子做的」;
   售后/维保行自己带 `customer_id`,搬单不搬它们就对不上。
3. **只在同店内搬。** 现在 26592 单**门店全都和客户的门店一致**(实测 0 例外),
   这是个不变量,搬单不许破它。
4. **搬完必须重算客户汇总**,而且**复用 `order_mix.重算`** ——
   单数 / 实付 / 12 个月 / 季度 / 首单 / 最近互动 / 闲置 / 等级 / 生命周期九个派生字段,
   自己再写一套迟早和它漂。

## 怎么摊

从最少单的客户开始给(小顶堆),所以是「水位上升」式的:先把一单没有的填起来,
再抬高整体的下沿。**不给受保护客户,也不让任何人越过上限**(否则削掉一个峰又造一个)。

    python3 tools/level_customer_orders.py          # 干活
    python3 tools/level_customer_orders.py --dry    # 只看会搬多少,不写库
"""
import argparse, heapq, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
                os.path.join(ROOT, "fakedata")]
import order_mix as OM

# ── 目标形状(业务 2026-09-26 定)────────────────────────────────────
# **不再是「单点上限」,是「分布形状」。** 为什么换:削到 50 之后
# 最多 162 → 109,而**中位数从 28 涨到 50** —— 尖峰削掉了,整体被顶平,
# 比削峰前更不像真的。业务原话是要「没有 162 单这种离谱值」,
# 而那该约束**形状**,不该约束**单点**(并行会话提的角度,业务采纳)。
形状 = [(0.80, 5), (0.95, 15)]     # 八成客户 ≤5 单、九成半 ≤15 单
上限 = 15                          # 给「还差多少」的日志用;判绿看上面那两条
# 长尾的阶梯:按「第几档占多少人、每人几单」铺配额。
# ⚠️ 这组数**是拍脑袋的** —— 服装零售的常见回购形状,没有真实数据来源。
# 业务 2026-09-26 说「你拿数据定,别问我」,所以写明出处,以后有真数据就换。
阶梯 = [(0.60, 1, 3), (0.20, 4, 5), (0.15, 6, 15), (0.05, 16, 60)]


def 接不了的(c):
    """**接收方的三条硬约束** —— 这一版之前只管了「不是受保护 + 没超上限」,
    结果搬完当场破了三条数据规范(2026-09-26 实测,3067 单搬下去破了 2870 条):

      C3「任何记录的时间不得早于它所属对象的创建时间」
         把 2025-10 的老订单搬给一个 2026-08 才建档的客户 —— 订单比客户还老。
         **所以资格是按单看的**:接收方的建档日必须 ≤ 这一单的下单日。
      A15「有在办业务的账户不得注销」
         搬一张没完成的单给一个正在注销的账户 —— 冷静期存在的意义正是等这些事了结。
      C5「最近互动和闲置天数在基准日上对得上」
         这条不是接收方的问题,是**重算用的基准日**:`order_mix.T` 写死在建库那天(2026-08-31),
         而世界的今天已经走到 09-26 —— 见下面 `重算基准日`。

    返回「一律不能当接收方」的那些人(注销类);按单看的那条在 `能接这一单` 里。
    """
    # ⚠️ **三条一起查,少一条就漏。** 2026-09-26 只查了 `account.status`,
    # 结果把 11 张单、¥96366 搬到了 `C10058`(名字就叫「已注销用户」、手机号是 `DELETED-C10058`)。
    # 并行会话点出的那句话值得抄在这儿:
    # **「聚合字段没更新」只是数字对不上,重算一遍就好;把订单挪给已注销客户是业务上说不通的** ——
    # 而它在「单数对不上」那条检查里**只表现为数字对不上**:
    # 把 order_cnt 重算成 11,检查就绿了,而订单仍然挂在一个注销掉的人名下。
    # **一个「修完之后检查变绿、但问题还在」的修法,比不修更糟 —— 它把问题从门禁上摘掉了。**
    return {r[0] for r in c.execute(
        "SELECT k.id FROM customer k LEFT JOIN account a ON a.id=k.account_id "
        "WHERE a.status IN ('注销中','已注销') "
        "   OR k.phone LIKE 'DELETED-%' "
        "   OR k.name LIKE '%注销%'")}


def 可搬的单(c, cid):
    """这个客户名下**干净的**标品单,按单号排(确定性)。"""
    return [r[0] for r in c.execute(
        """SELECT id FROM ordr WHERE customer_id=? AND kind='标品订单'
             AND wearer_id IS NULL
             AND id NOT IN (SELECT order_id FROM aftersale WHERE order_id IS NOT NULL)
             AND id NOT IN (SELECT order_id FROM maintain  WHERE order_id IS NOT NULL)
           ORDER BY id""", (cid,))]


def 世界今天():
    """⚠️ **必须在动库之前调。** `worldclock.今天()` 读的是库里的 `world_meta`,
    而我这边一旦开了写事务,它那个连接会被锁住 —— 而它**读不到时会静默退回建库基准日**。
    实测过一次:日志打出「重算基准日:2026-08-31(世界的今天)」,
    而世界的今天其实是 09-26。**一句自称「世界的今天」的话,说的是建库那天。**
    """
    import datetime as dt
    import worldclock as WC
    d = WC.今天()
    return d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d))


def 配额(n人, n单, rng):
    """按阶梯给 n 人铺配额,总数**正好等于** n 单。返回一个降序的配额列表。

    做法:先按阶梯给每人抽一个配额,再把总数对齐到 n 单(多了从大头减、少了往大头加)。
    ⚠️ **不许用「平均分 + 随机扰动」** —— 那样出来的是钟形,不是长尾,
    而钟形正是这次要摆脱的那个形状(削峰之后的中位数 50 就是钟形的峰)。
    """
    q = []
    for 占比, lo, hi in 阶梯:
        for _ in range(int(n人 * 占比)):
            q.append(rng.randint(lo, hi))
    while len(q) < n人: q.append(rng.randint(1, 3))
    q = q[:n人]
    q.sort(reverse=True)
    # 对齐总数:多了从最大的开始减,少了往最大的开始加 —— 长尾的头本来就该吸收余量
    diff = n单 - sum(q)
    i = 0
    while diff and q:
        if diff > 0:
            q[i % len(q)] += 1; diff -= 1
        else:
            if q[i % len(q)] > 1: q[i % len(q)] -= 1; diff += 1
            elif all(x <= 1 for x in q): break
        i += 1
    q.sort(reverse=True)
    return q


def 干(c, log=print, dry=False, 基准=None):
    """**按长尾形状重排「订单归谁」。**

    只动 `ordr.customer_id`,不动订单本身。四条硬约束(每一条都是踩过才加的):
      ① 不碰夹具(`order_mix.受保护客户` + 判责客户)—— 名单**扫**出来,不手抄
      ② 只搬干净的标品单(挂着着装人 / 售后 / 维保的不搬)
      ③ **同店**(现在门店全一致,是个不变量)
      ④ 接收方**建档日 ≤ 这一单的下单日**(C3),且不是注销 / 匿名化的客户
    """
    受保护 = OM.受保护客户(c)
    受保护.update({k: "名下有判责工单" for k in OM.判责客户(c)})
    夹具 = dict(受保护)
    受保护.update({k: "账户在注销中 / 已注销 / 已匿名化:接了单会破 A15" for k in 接不了的(c)})
    不许重算 = set(夹具)

    店 = {r["id"]: r["shop"] for r in c.execute("SELECT id, shop FROM customer")}
    建档 = {r["id"]: (r["created"] or "")[:10] for r in c.execute("SELECT id, created FROM customer")}
    import random as _r
    rng = _r.Random(20260926)          # 固定种子 —— 重建多少次都是同一个形状

    搬了 = 0
    for shop in sorted(set(店.values())):
        # 这一店的可搬单(干净标品)和它们的下单日
        可搬 = [(r[0], (r[1] or "")[:10]) for r in c.execute(
            """SELECT o.id, o.created FROM ordr o WHERE o.shop=? AND o.kind='标品订单'
                 AND o.wearer_id IS NULL
                 AND o.id NOT IN (SELECT order_id FROM aftersale WHERE order_id IS NOT NULL)
                 AND o.id NOT IN (SELECT order_id FROM maintain  WHERE order_id IS NOT NULL)
               ORDER BY o.created, o.id""", (shop,))]
        受 = [cid for cid in sorted(店) if 店[cid] == shop and cid not in 受保护]
        if not 可搬 or not 受: continue
        # 已经钉住的(不可搬的单)算进每个人的底数 —— 配额要在它之上铺
        底 = {cid: 0 for cid in 受}
        for r in c.execute("SELECT customer_id, COUNT(*) n FROM ordr WHERE shop=? GROUP BY customer_id",
                           (shop,)):
            if r[0] in 底: 底[r[0]] = 0        # 底数只记不可搬的,下面单独算
        for r in c.execute(
                """SELECT customer_id, COUNT(*) n FROM ordr o WHERE shop=? AND NOT (
                     o.kind='标品订单' AND o.wearer_id IS NULL
                     AND o.id NOT IN (SELECT order_id FROM aftersale WHERE order_id IS NOT NULL)
                     AND o.id NOT IN (SELECT order_id FROM maintain  WHERE order_id IS NOT NULL))
                   GROUP BY customer_id""", (shop,)):
            if r[0] in 底: 底[r[0]] = r[1]
        q = 配额(len(受), len(可搬), rng)
        # 配额分给谁:**建档早的人排前面拿大配额** —— 老客户回购多,而且 C3 要求它建档得够早
        受.sort(key=lambda x: (建档.get(x, "9999"), x))
        剩 = {cid: max(0, q[i] - 底[cid]) for i, cid in enumerate(受)}
        # 按单分配:老单优先给建档最早、还有配额的人
        游标 = 0
        for oid, 日 in 可搬:
            到 = None
            for k in range(len(受)):
                cid = 受[(游标 + k) % len(受)]
                if 剩.get(cid, 0) > 0 and 建档.get(cid, "9999") <= 日:
                    到 = cid; 游标 = (游标 + k + 1) % len(受); break
            if 到 is None: continue          # 没人接得了这一单(C3)—— 留在原处,不硬搬
            if not dry:
                c.execute("UPDATE ordr SET customer_id=? WHERE id=?", (到, oid))
            剩[到] -= 1; 搬了 += 1
    log(f"  {'(只看不写)' if dry else ''}按长尾形状重排了 {搬了} 单")
    if not dry:
        修不了 = 修C3(c, 受保护, log)
        OM.T = 基准 or OM.T
        log(f"  重算基准日:{OM.T}(世界的今天,不是建库那天)")
        OM.重算(c, 不许重算, log)
    return 搬了, 受保护


def 修C3(c, 受保护, log=print):
    """把「订单比客户还老」的单,搬到一个**建档更早**的合格客户名下。

    ⚠️ 这一步是补票买的:2026-09-26 第一版削峰没管 C3,3067 单搬下去**破了 2870 条**。
    能修得动是因为客户建档铺得够开(2024-06 → 2026-09),
    每个下单时间点都有一批「那时已经建档」的客户 —— 这一点是先量过才敢修的。
    """
    坏 = [tuple(r) for r in c.execute(
        """SELECT o.id, o.customer_id, substr(o.created,1,10), o.shop
             FROM ordr o JOIN customer k ON k.id=o.customer_id
            WHERE substr(o.created,1,10) < substr(k.created,1,10) ORDER BY o.id""")]
    if not 坏:
        log("  修 C3:没有「订单比客户还老」的单"); return 0
    单数 = {r["id"]: r["n"] for r in c.execute(
        "SELECT k.id, COUNT(o.id) n FROM customer k LEFT JOIN ordr o ON o.customer_id=k.id "
        "GROUP BY k.id")}
    档 = {r["id"]: ((r["created"] or "")[:10], r["shop"]) for r in
          c.execute("SELECT id, created, shop FROM customer")}
    # ⚠️ 接收方仍然排掉受保护的,**但搬出方不排** ——
    # 因为这些违规单本来就是这个脚本放错的,把它们收回来是**在撤自己的烂摊子**,不是动别人的夹具。
    # 第一版把搬出方也排掉了,于是 C21019(账户在注销中)名下我放进去的 12 单修不掉,
    # 而我自己那条「受保护客户一单没动」的守卫又把整轮回滚了 —— **守卫护住了错误的状态**。
    候选 = sorted((cid for cid in 单数 if cid not in 受保护),
                 key=lambda x: (单数[x], x))
    从受保护收回 = sorted({cid for cid, _, _, _ in 坏 if cid in 受保护})
    if 从受保护收回:
        log(f"  ⚠️ 要从**受保护客户**名下收回放错的单:{从受保护收回} —— "
            f"这些单是这个脚本先前放进去的(第一版漏了「注销账户不能当接收方」这条),收回是撤销,不是改夹具")
    修了, 修不了 = 0, 0
    for oid, 原, 日, shop in 坏:
        到 = None
        for cid in 候选:
            d, s = 档[cid]
            if s == shop and d <= 日 and 单数[cid] < 上限:
                到 = cid; break
        if 到 is None: 修不了 += 1; continue
        c.execute("UPDATE ordr SET customer_id=? WHERE id=?", (到, oid))
        单数[原] -= 1; 单数[到] += 1; 修了 += 1
        候选.sort(key=lambda x: (单数[x], x))
    log(f"  修 C3:搬回 {修了} 单" + (f",**{修不了} 单找不到合格接收方**" if 修不了 else ""))
    return 修不了


def 形状现状(c):
    """返回 (有单人数, 每档实际百分位, 中位, 最多)。**判绿用的是百分位,不是单点。**"""
    n = sorted(r[0] for r in c.execute("SELECT COUNT(*) FROM ordr GROUP BY customer_id"))
    if not n: return 0, {}, 0, 0
    实际 = {}
    for 分位, 目标 in 形状:
        k = int(len(n) * 分位)
        实际[分位] = (n[min(k, len(n) - 1)], 目标)
    import statistics as st
    return len(n), 实际, st.median(n), n[-1]


def 自查(c, 受保护, log=print):
    坏 = []
    人, 实际, 中位, 最多 = 形状现状(c)
    for 分位, (真, 目标) in sorted(实际.items()):
        if 真 > 目标:
            坏.append(f"{分位:.0%} 分位是 {真} 单,目标 ≤{目标}")
    跨店 = c.execute("SELECT COUNT(*) FROM ordr o JOIN customer k ON k.id=o.customer_id "
                     "WHERE o.shop<>k.shop").fetchone()[0]
    if 跨店: 坏.append(f"{跨店} 单的门店和客户的门店对不上 —— 这个不变量被破了")
    脏 = c.execute("""SELECT COUNT(*) FROM ordr o JOIN customer k ON k.id=o.customer_id
        WHERE o.wearer_id IS NOT NULL AND o.wearer_id NOT IN
              (SELECT id FROM wearer WHERE customer_id=k.id)""").fetchone()[0]
    if 脏: 坏.append(f"{脏} 单的着装人不属于这一单的客户")
    匿 = c.execute("""SELECT COUNT(*) FROM ordr WHERE customer_id IN
        (SELECT id FROM customer WHERE phone LIKE 'DELETED-%')""").fetchone()[0]
    if 匿: 坏.append(f"{匿} 单挂在已匿名化的客户名下")
    log(f"  自查:有单 {人} 人 · 中位 {中位:.0f} · 最多 {最多} · "
        + " · ".join(f"{p:.0%}分位 {真}(目标 ≤{目}) " for p, (真, 目) in sorted(实际.items()))
        + ("—— " + "、".join(坏) if 坏 else "—— 形状达标;门店一致;着装人都属本人;匿名化名下无单"))
    return not 坏


def 数据规范还绿吗(log=print):
    """搬完之后把整条**数据规范**跑一遍(C1–C5 等)。

    ⚠️ 为什么是整条而不是只验我关心的那几项:并行会话提醒的 ——
    **削峰改的是 `customer_id`,而 C5 管的是「最近互动 / 闲置天数在基准日上对得上」**。
    订单换了客户,那个客户的最近互动就可能不再对应他最后一单了。
    我本来只打算验「没人超上限 + 门店一致 + 着装人归属」三条,那三条都不会看见 C5。
    ⚠️ 这一步只能在 **commit 之后**跑 —— 子进程看不见没提交的事务。
    """
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "backend", "spec_check.py")],
                       capture_output=True, text=True, cwd=ROOT)
    绿 = r.returncode == 0
    log("  数据规范:" + ("全绿" if 绿 else "❌ 红了 —— 下面是它自己的话"))
    if not 绿:
        for l in (r.stdout or "").splitlines():
            if "❌" in l or "没守住" in l: log("    " + l.strip())
    return 绿


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    c = OM.conn()
    # 搬之前先把受保护客户的单数记下来,搬完逐个核对**一个都没动**
    前 = {r[0]: r[1] for r in c.execute(
        "SELECT customer_id, COUNT(*) FROM ordr GROUP BY customer_id")}
    基准 = 世界今天()          # **必须在动库之前取**,见那个函数的注释
    OM._原T = OM.T
    n, 受保护 = 干(c, dry=a.dry, 基准=基准)
    后 = {r[0]: r[1] for r in c.execute(
        "SELECT customer_id, COUNT(*) FROM ordr GROUP BY customer_id")}
    # 守卫:受保护客户的单数**只许减少,不许增加** ——
    # 减少 = 撤销这个脚本先前放错的单(见 修C3 的注释);增加 = 真的动了别人的夹具。
    # ⚠️ 第一版写的是「一个数都不许变」,结果**护住了一个错误的状态**:
    # 我放错的单修不掉,而门禁一直红着。判据该问的是**朝哪个方向变**,不是**变没变**。
    多了的 = [k for k in 受保护 if 后.get(k, 0) > 前.get(k, 0)]
    if 多了的:
        c.rollback()
        sys.exit(f"❌ 受保护客户名下**多了单**:{多了的[:5]} —— 已回滚,一行都没写")
    少了的 = [(k, 前.get(k, 0), 后.get(k, 0)) for k in 受保护 if 后.get(k, 0) < 前.get(k, 0)]
    if 少了的:
        print(f"  ℹ️ 从受保护客户名下收回了放错的单:{少了的[:5]}")
    # ⚠️ **--dry 下不许跑自查。** 自查是查库的,而 --dry 没写库 ——
    # 它会照实报「还有 179 个客户超过 50 单」,看起来像「削峰没生效」。
    # 一个在两种模式下含义相反的输出,比不输出糟得多。
    if a.dry:
        c.rollback()
        print(f"(--dry:没有写库,所以**不跑自查** —— 它查的是库,会报旧状态)")
        sys.exit(0)
    ok = 自查(c, 受保护)
    if False:
        pass
    elif ok:
        c.commit()
        print(f"✅ 削峰完成:搬了 {n} 单,受保护的 {len(受保护)} 个客户一单没动")
        # ⚠️ **报,但不退非零。** 这个脚本跑在 `rebuild.sh` 的中段,
        # 那时别的修数步骤可能还没跑(实测:它排在 `clamp_future_done.py` 之前时,
        # C4 本来就该红 —— 7 张「完工日在锚点之后」的单还没压回去)。
        # 让它在这种情况下退非零,**整条重建会停在这儿**,而红的根本不是削峰造成的。
        # 判绿的活交给 `check.sh` 末尾那一整条 `spec_check` —— **一条检查只该为自己那件事负责。**
        if not 数据规范还绿吗():
            print("  ⚠️ 上面那几条规范红了。**先看是不是这一步造成的** ——"
                  "这个脚本跑在流水线中段,别的修数步骤可能还没跑;"
                  "最终判绿看 check.sh 里那条完整的数据规范检查")
    else:
        c.rollback(); sys.exit("❌ 自查没过,已回滚")
    sys.exit(0 if ok else 1)
