#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给已确认的定制单补**订单确认书** —— 走正门那个生成函数,不手写 INSERT。

业务 2026-10-10 拍:收预付款要有书面约定,所以 `confirm_order` 里
**在同一个事务里**生成确认书(`backend/order_write.py` 那段:写不进去就整个确认回滚,
不存在「已付全款、确认书稍后补」这种中间状态)。

而这条规矩是 10-10 才有的,**它之前确认的单没有确认书** ——
实测库里 `order_contract` **一条都没有**,而 10-10 之后已确认的定制单有 56 张。
冒烟里 `contract.html` 一直红,红的就是这个:页面没东西可展。

用户 2026-10-15 拍:补,**走「确认下单 → 生成确认书」的正门生成**,
范围是 10-10 之后已确认的订单。

────────────────────────────────────────────────────────────────────
**三条设计,每一条都对应这个仓库踩过的坑:**

① **不手写 INSERT,调 `order_contract.生成()`。**
   手写的话,确认书的条款版本、正文排版、快照结构就成了**第二份实现** ——
   而它和正门那份一旦漂了,表现是「补出来的确认书和新签的长得不一样」,
   两边分别看都正常。这正是这个仓库今天反复撞到的那个形状。

② **时间用订单当时的 `paid_at`,不是「现在」。**
   `backend/factory_inbox.py` 记过同一个病:重建时真实时间 20:55 →
   `created 20:55` 晚于同一条包裹的 `arrived_at 15:00`,于是
   「包裹建档晚于包裹到店」,而前三条判据全都放行。
   > 同一天之内,这两种时刻没有可比的先后。
   补出来的确认书如果盖今天的日期,就会出现「确认书晚于订单确认」。

③ **幂等:已有确认书的跳过。** 跑两遍不会多出一份 ——
   而「跑了两遍」和「跑了一遍」在条数上看得出来,在**内容**上看不出来。

默认**只报不写**,要真写加 `--写`。
"""
import argparse
import os
import sqlite3
import sys

这里 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(这里)
sys.path[:0] = [os.path.join(根, "backend"), os.path.join(根, "knowledge"), 根]

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

import contract_terms as _K
起点 = _K.生效日       # 业务拍板那天 —— **从条款那边现取,不手抄第二份**


def 要补的(c):
    """10-10 之后已确认、而且还没有确认书的定制单。"""
    return [dict(id=r[0], shop=r[1], advisor_no=r[2], paid_at=r[3]) for r in c.execute(
        """SELECT o.id, o.shop, o.advisor_no, o.paid_at FROM ordr o
           WHERE o.kind='定制品订单' AND o.paid_at IS NOT NULL AND o.paid_at >= ?
             AND NOT EXISTS(SELECT 1 FROM order_contract k WHERE k.order_id = o.id)
           ORDER BY o.paid_at""", (起点,))]


def 经办人(c, 工号):
    """谁签的这张单 —— 取订单上的顾问。**查不到就用工号本身**,不编一个名字。"""
    r = c.execute("SELECT no, name, role FROM staff WHERE no=?", (工号,)).fetchone()
    return dict(no=r[0], name=r[1], role=r[2]) if r else dict(no=工号, name=工号 or "—", role="顾问")


def 跑(库, 真写):
    import order_contract as OC
    c = sqlite3.connect(库)
    OC.建表(c)
    单 = 要补的(c)
    已有 = c.execute("SELECT count(*) FROM order_contract").fetchone()[0]
    print(f"库:{库}")
    print(f"已有确认书 {已有} 份;{起点} 之后已确认、还缺确认书的定制单 **{len(单)} 张**")
    if not 单:
        print(f"  {Y}没有要补的 —— 这不叫失败,是已经补齐了(或者范围内一张单都没有){D}")
        c.close()
        return 0, 0
    好, 坏 = 0, []
    for o in 单:
        me = 经办人(c, o["advisor_no"])
        当时 = o["paid_at"]                      # ← ②:用订单当时的时刻,不是「现在」
        try:
            if 真写:
                OC.生成(c, o["id"], me, 当时[:10],
                        七天确认=dict(时间=当时, 账号=me["no"] or me["name"]))
            else:
                # 试跑:只验「它生成得出来吗」,写完当场回滚
                OC.生成(c, o["id"], me, 当时[:10],
                        七天确认=dict(时间=当时, 账号=me["no"] or me["name"]))
                c.rollback()
            好 += 1
        except Exception as e:
            坏.append((o["id"], f"{type(e).__name__}: {e}"))
    if 真写:
        c.commit()
    else:
        c.rollback()
    剩 = c.execute("SELECT count(*) FROM order_contract").fetchone()[0]
    c.close()
    print(f"  生成成功 {好} 张;失败 {len(坏)} 张")
    for i, (oid, why) in enumerate(坏[:5]):
        print(f"    {R}✗{D} {oid}  {why}")
    if len(坏) > 5:
        print(f"    …… 还有 {len(坏)-5} 张,没全印出来")
    print(f"  库里现在 {剩} 份确认书" + ("" if 真写 else f"  {Y}(试跑,已回滚){D}"))
    return 好, len(坏)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--库", default=os.path.join(根, "backend", "lanxiu.db"))
    ap.add_argument("--写", action="store_true", help="真写进去;不加就是试跑(写完回滚)")
    a = ap.parse_args()
    print("补订单确认书 —— 走 `order_contract.生成()` 这个正门,不手写 INSERT")
    print("=" * 72)
    好, 坏 = 跑(a.库, a.写)
    print()
    if 坏:
        print(f"{R}❌ 有 {坏} 张没生成出来 —— 先查清楚再写{D}")
        raise SystemExit(1)
    if not a.写:
        print(f"{Y}📌 这是试跑,一个字都没写进去。确认没问题后加 `--写`。{D}")
    print(f"{G}✅ {好} 张{'已写入' if a.写 else '试跑通过'}{D}")
