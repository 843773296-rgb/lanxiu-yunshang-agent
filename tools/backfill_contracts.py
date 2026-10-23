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


def 重渲染(库, 真写):
    """把**已有**确认书的正文按库里现在的数据重拼一遍 —— 只改 `body` 一列。

    为什么要这个档:每日平移把正文里的「条款版本 2026-10-10.2」**当成日期挪了**
    (10-23 已经漂到 `2026-10-18.2`)。同一行的 `terms_ver` 列登记在
    「文字里不挪」所以是对的 ——
    > **查库的人看到的是对的,拿着那份文件的顾客看到的是一个从来没发布过的版本。**
    平移那一头 2026-10-23 已经修了(`shift_world` 认得出「日期后面紧跟 `.数字`
    是版本号」),但**已经写进去的 56 份正文不会自愈**。

    ⚠️⚠️ **硬拒一种情况:这一行的 `terms_ver` 和代码里当前的条款版本不一致。**
    `contract_terms.拼正文()` 用的是**代码当前**那个版本常量 ——
    条款哪天升到 `.3`,再跑这个档就会把老确认书的版本**悄悄改成新版**,
    那是在**改写顾客当初同意的内容**,而且看起来像在修 bug。
    > 一次「把被平移挤歪的版本号修回去」,和一次「把老约定改成新条款」,
    > **在 body 这一列的 diff 上长得几乎一样** —— 都是版本号变了。
    分开它们的只有 `terms_ver`:它没被挪过,它说的是这份约定**当初**是哪一版。

    ⚠️ **只改 `body`,不动 `snapshot` / `created_at` / 勾选记录** ——
    那几样没有被平移弄坏,碰它们就是扩大不可逆的改动面。
    """
    import order_contract as OC
    import contract_terms as _K
    c = sqlite3.connect(库)
    行 = [dict(order_id=r[0], terms_ver=r[1], body=r[2], created_at=r[3],
               no7_ack_at=r[4], no7_ack_by=r[5]) for r in c.execute(
        "SELECT order_id, terms_ver, body, created_at, no7_ack_at, no7_ack_by"
        " FROM order_contract ORDER BY order_id")]
    print(f"库:{库}")
    print(f"已有确认书 **{len(行)} 份**;代码里当前的条款版本 `{_K.版本}`")
    if not 行:
        print(f"  {Y}一份都没有 —— 这不叫失败,是没什么可重渲染的{D}")
        c.close()
        return 0, 0
    版本不一致 = [x for x in 行 if (x["terms_ver"] or "") != _K.版本]
    if 版本不一致:
        print(f"  {R}✗ 有 {len(版本不一致)} 份的 terms_ver 不是 `{_K.版本}`,**整个档拒跑**{D}")
        print(f"    重渲染会把它们的正文写成代码当前那一版 —— 那是改写顾客当初同意的内容,"
              f"不是修 bug。先搞清楚这几份该怎么办:")
        for x in 版本不一致[:5]:
            print(f"      {x['order_id']}  terms_ver={x['terms_ver']}")
        c.close()
        return 0, len(版本不一致)
    变了, 坏 = [], []
    for x in 行:
        try:
            新文, _, _ = OC.拼这一单(
                c, x["order_id"], (x["created_at"] or "")[:10],
                七天确认=dict(时间=x["no7_ack_at"], 账号=x["no7_ack_by"]))
        except Exception as e:
            坏.append((x["order_id"], f"{type(e).__name__}: {e}"))
            continue
        if 新文 != (x["body"] or ""):
            变了.append((x["order_id"], x["body"] or "", 新文))
    print(f"  重拼成功 {len(行) - len(坏)} 份;拼不出来 {len(坏)} 份;"
          f"**正文有变化的 {len(变了)} 份**")
    for oid, why in 坏[:5]:
        print(f"    {R}✗{D} {oid}  {why}")
    if 变了:
        # **逐行摆出到底改了哪几行** —— 不可逆的改动不许只报一个条数
        import difflib
        oid, 旧文, 新文 = 变了[0]
        print(f"\n  第一份({oid})改了哪几行 —— 其余 {len(变了)-1} 份同形状:")
        for l in difflib.unified_diff(旧文.split("\n"), 新文.split("\n"),
                                      "库里现在", "重拼之后", lineterm="", n=0):
            if l.startswith(("---", "+++", "@@")):
                continue
            print(f"    {R if l[:1] == '-' else G}{l}{D}")
        形状 = {}
        for oid, 旧文, 新文 in 变了:
            k = tuple(sorted(set(旧文.split("\n")) ^ set(新文.split("\n"))))
            形状.setdefault(len(k), 0)
            形状[len(k)] += 1
        print(f"  改动行数的分布:{dict(sorted(形状.items()))} —— "
              f"**全是同一个形状才敢批量写**,出现别的形状先停下来看")
    if 真写:
        for oid, _, 新文 in 变了:
            c.execute("UPDATE order_contract SET body=? WHERE order_id=?", (新文, oid))
        c.commit()
        print(f"  {G}已写入 {len(变了)} 份正文(只改 body 一列){D}")
    else:
        c.rollback()
        print(f"  {Y}(试跑,一个字都没写){D}")
    c.close()
    return len(变了), len(坏)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--库", default=os.path.join(根, "backend", "lanxiu.db"))
    ap.add_argument("--写", action="store_true", help="真写进去;不加就是试跑(写完回滚)")
    ap.add_argument("--重渲染", action="store_true",
                    help="不补新的,把**已有**确认书的正文按现在的数据重拼一遍(只改 body)")
    a = ap.parse_args()
    if a.重渲染:
        print("重渲染已有确认书的正文 —— 走 `order_contract.拼这一单()`,和正门同一份实现")
        print("=" * 72)
        好, 坏 = 重渲染(a.库, a.写)
    else:
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
