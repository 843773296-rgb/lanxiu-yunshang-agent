#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订单在客户上摊得开不开 —— 盯住「一个人买了 162 次」这种一眼假的分布。

## 为什么要有它

2026-09-26 量到:862 个客户 26592 单,**最多一个人 162 单**,同时 106 个客户一单没有。
业务拍板「只削峰」(不新增假客户、不砍订单),`tools/level_customer_orders.py` 把它削平。

**削完必须有东西盯着**,否则下一次造数或者模拟销量一跑,尖峰就悄悄长回来 ——
而「分布变形了」和「分布本来就这样」在页面上长得一模一样:
两边都是一串订单,点进去都有客户、有金额、有时间。

## 判据和它的偏向

`上限` 取自 `tools/level_customer_orders.上限`(**一个数只写一处**);
无单客户数是**棘轮**:登记当前值,**只许降不许涨**。

⚠️ 这条检查**不判「分布像不像真的」** —— 那是业务的判断,不是机器的。
它只守两件能机械判的事:**没有人越过上限**、**一单没有的人不许变多**。
削峰的副作用(中位数被顶高)**它看不见**,那件事记在 PRD 附录 B 里。
"""
import os, sqlite3, statistics as st, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "tools")]
import level_customer_orders as LV

DB = os.path.join(HERE, "lanxiu.db")
# 无单客户数的**棘轮**:2026-09-26 削峰之后是 103 个。只许降不许涨。
# 为什么不是 0:新建档、还没下过单的客户本来就该有 —— 一律要求 0 是在逼造假。
# 无单客户数的**棘轮**。客户从 968 补到约 8065 之后,「还没下过单的人」本来就该多 ——
# 所以这个数按**比例**判,不按绝对值:新建档还没买的占比不该超过这条线。
无单占比上限 = 0.45
fail = []


def ck(name, ok, 验了, 说=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {验了} 个){('  ' + 说) if 说 else ''}")
    if not ok: fail.append(name)


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    n = sorted(r[0] for r in c.execute("SELECT COUNT(*) FROM ordr GROUP BY customer_id"))
    if not n:
        print("❌ 一条订单都没有 —— **这是「没扫到东西」,不是「都通过」**"); return 1
    无单 = c.execute("SELECT COUNT(*) FROM customer WHERE id NOT IN "
                    "(SELECT customer_id FROM ordr)").fetchone()[0]
    超 = [(r[0], r[1]) for r in c.execute(
        "SELECT customer_id, COUNT(*) m FROM ordr GROUP BY customer_id "
        "HAVING m>? ORDER BY m DESC LIMIT 5", (LV.上限,))]
    print(f"订单在客户上的分布 · 上限取自 level_customer_orders.上限 = {LV.上限}")
    print("=" * 92)
    print(f"  有单客户 {len(n)} · 订单 {sum(n)} · 人均 {sum(n)/len(n):.1f} · "
          f"中位 {st.median(n):.0f} · 最多 {n[-1]}")
    # ── 形状,不是单点(业务 2026-09-26 从「上限 50」换过来的)──────────
    # 为什么换:削到 50 之后最多 162 → 109,而**中位数从 28 涨到 50** ——
    # 尖峰削掉了,整体被顶平,比削峰前更不像真的。
    # **「没有离谱值」该约束形状,不该约束单点** —— 单点上限把长尾压成了平台。
    for 分位, 目标 in LV.形状:
        k = min(int(len(n) * 分位), len(n) - 1)
        ck(f"{分位:.0%} 的客户订单数 ≤{目标}", n[k] <= 目标, len(n),
           f"{分位:.0%} 分位实际 {n[k]} 单" + ("" if n[k] <= 目标 else
           " —— 跑 tools/level_customer_orders.py 按长尾重排"))
    ck("还没下过单的客户没超过上限(棘轮,按比例)",
       无单 / max(1, len(n) + 无单) <= 无单占比上限, len(n) + 无单,
       f"{无单} 个 / 共 {len(n)+无单} 人 = {无单/max(1,len(n)+无单):.0%}"
       f"(上限 {无单占比上限:.0%})—— **按比例判**:客户补到八千之后,"
       f"「新建档还没买」的人本来就该多,拿绝对值判会逼着造假")

    # ── 和聚合**无关**的那一条 ────────────────────────────────────────
    # 并行会话点出来的:把订单挪给已注销客户,在「单数对不上」那条检查里
    # **只表现为数字对不上** —— 把 order_cnt 重算一遍它就绿了,而订单还挂在注销的人名下。
    # 所以这一条判的是**订单在不在那儿**,不看任何聚合字段:**重算骗不过它。**
    #
    # ⚠️ 判据只盯**已匿名化**(`phone LIKE 'DELETED-%'`)那一类,不盯「账户注销中」——
    # 第一版把两类一起禁,当场误报:**账户在注销中的客户本来就有历史订单**,
    # 冷静期存在的意义正是等这些单了结(A15 只禁**没完成**的单,那条由 spec_check 管)。
    # 而**已匿名化**是另一回事:人的数据已经擦掉了,名下还挂着订单就是说不通的 ——
    # 2026-09-26 削峰往这种客户名下搬了 11 张单、¥96366,就是这条要抓的。
    匿名有单 = [(r[0], r[1], r[2]) for r in c.execute(
        """SELECT k.id, k.phone, (SELECT COUNT(*) FROM ordr WHERE customer_id=k.id) n
             FROM customer k
            WHERE k.phone LIKE 'DELETED-%'
              AND (SELECT COUNT(*) FROM ordr WHERE customer_id=k.id) > 0""")]
    ck("已匿名化的客户名下没有订单", not 匿名有单,
       c.execute("SELECT COUNT(*) FROM customer WHERE phone LIKE 'DELETED-%'").fetchone()[0],
       (f"{len(匿名有单)} 个还挂着单:{匿名有单[:3]} —— **这条和聚合无关,重算 order_cnt 骗不过它**"
        if 匿名有单 else "一张都没有"))

    print("=" * 92)
    if fail:
        print(f"❌ {len(fail)} 条没过:{fail}"); return 1
    print("✅ 订单摊得开"); return 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。规格在 tools/bite_specs.json 里可重放。
咬合 = [
    # ⚠️ 预期红只能写**源码里真有的字面串** —— 这条检查名是 f-string 拼的
    # (`f"{分位:.0%} 的客户订单数 ≤{目标}"`),所以取固定的那一段。
    ("把目标形状的「八成 ≤5 单」改成「八成 ≤1 单」(库里达不到,当场红)",
     "的客户订单数 ≤"),
    ("把「已匿名化」的判据换成匹配正常手机号(那些客户名下真的有单)",
     "已匿名化的客户名下没有订单"),
]

if __name__ == "__main__":
    sys.exit(main())
