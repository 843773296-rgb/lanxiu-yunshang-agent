#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给带门店键的那 11 处加一列 `shop_code`,并按 `shop` 串回填。

来路:只读审计第 3 条,用户 2026-10-24 拍「根治:加 shop_code 列,读写都改成按编码」。
口径的唯一来源是 `backend/shop_key.py` —— **这个脚本不自己判什么算门店**。

默认**只报不改**,要真改加 `--做`。**幂等**:加过的列不再加,对了的行不再写。

## 为什么是流水线的一步,而不是写在 seed.py 的建表语句里

写在建表语句里只管「从零建库」那一次。而这个项目有两个检出共用一个库,
库是 2026 年一路长出来的 —— **写在 SCHEMA 里的列,在任何已经存在的库上都不存在**,
而缺一列不报错,只会让按它筛的查询返回零行。
(同 `tools/ensure_tables.py` 那一步存在的理由,它文件头里写着。)

所以这一步:`ALTER TABLE … ADD COLUMN`(缺了才加)+ 回填(不对才写),
挂在 `rebuild.sh` 的**最后一批**(所有铺数据的步骤之后),
两种库上跑出来都是同一个结果。

## ⚠️ 它不删也不改 `shop` 那一列

`shop` 继续装显示串,给人看;`shop_code` 只管关联。
**两列并存期**里「谁是真相」必须只有一个答案 —— 答案是 `shop_code`,
而 `backend/shop_key_check.py` 守着它们俩别打架。
> 一列「还没回填」和一列「回填错了」,在页面上长得一模一样(都只是少几行)。
"""
import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend")]

import shop_key as SK

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def 表在吗(c, 表):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (表,)).fetchone())


def 要加列的(c):
    """只算**表已经存在**的那几处。表还没建出来的单独报,不混进来。"""
    return [(t, col) for t, col in SK.带门店键的
            if 表在吗(c, t) and not SK.有列(c, t)]


def 表还没建的(c):
    return [t for t, _ in SK.带门店键的 if not 表在吗(c, t)]


def 要回填的(c, 门店):
    """→ [(表, 列, [(rowid, 现在的码, 该填的码)])] —— 只含不对的行。"""
    出 = []
    for 表, 列 in SK.带门店键的:
        if not SK.有列(c, 表):
            continue
        坏 = []
        for rid, 串, 码 in c.execute(f"SELECT rowid, {列}, shop_code FROM {表}"):
            该 = SK.该填的码(串, 门店)
            if 码 != 该:
                坏.append((rid, 码, 该))
        if 坏:
            出.append((表, 列, 坏))
    return 出


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=SK.DB)
    ap.add_argument("--做", action="store_true", dest="做", help="真改;不加就是试跑")
    ap.add_argument("--建列", action="store_true", dest="建列",
                    help="**只加列、不回填**,给重建流水线的前段用(见下面那段注释)")
    a, 野 = ap.parse_known_args()
    if 野:
        print(f"{Rd}❌ 不认识这些参数:{野} —— **不认识就不跑**{D}")
        return 2
    if not os.path.exists(a.db):
        print(f"{Y}库不在:{a.db}{D}")
        return 1

    print("门店键 · 加 shop_code 列并按 shop 串回填")
    print("=" * 78)
    print(f"库:{a.db}")
    c = sqlite3.connect(a.db)
    门店 = SK.门店表(c)
    if not 门店:
        print(f"  {Rd}❌ shop 表是空的 —— **这不是「没什么要回填的」,是没有口径可用**{D}")
        c.close()
        return 1
    print(f"门店表:{len(门店)} 家 —— {sorted(门店.values())}")

    缺列 = 要加列的(c)
    没建 = 表还没建的(c)
    print(f"\n要加列的 {len(缺列)} 处:{[t for t, _ in 缺列] or '一处都不缺'}")
    if 没建:
        print(f"  {Y}这几张表还没建出来,这一轮跳过:{没建}{D}")

    # ── `--建列`:只加列,给重建流水线的**前段**用 ─────────────────────
    #
    # ⚠️ 2026-10-24 CI 红在这件事上,而**本地怎么跑都是绿的**:
    # `opportunity_store` 往 `schedule` 写 `shop_code`,它在重建流水线第 15 步跑;
    # 而加列那一步原来挂在**第 41 步**(所有铺数据的步骤之后,为了回填能覆盖全)。
    # 于是从零重建时写口跑在加列之前,当场
    # `OperationalError: table schedule has no column named shop_code`。
    #
    # > 在一个已经存在的库上,那一列**永远都在** —— 所以本地看不见这件事。
    # > 只有「从零」才会让写口跑在加列之前。
    #
    # 修法是把两件事分开,各放在该放的位置:
    #   **加列**要在**第一个写口之前**(所以挂在 seed.py 之后、ensure_tables 之后各一次,
    #            后者是因为 roster / store_report_doc 是 ensure_tables 才建的);
    #   **回填**要在**所有造数之后**(所以仍然留在最后那一批)。
    # 两件都幂等,多跑一次只是多读一遍。
    if a.建列:
        if 缺列:
            with c:
                for 表, _ in 缺列:
                    c.execute(f"ALTER TABLE {表} ADD COLUMN shop_code TEXT")
                    print(f"  + {表}.shop_code")
        print(f"  {G}加列完毕(这一轮只加列、不回填;回填在流水线最后那一批){D}")
        c.close()
        return 0

    # 到这儿就是**回填那一轮** —— 它要求 11 张表一张不少。
    # ⚠️ 表还没建出来就红:**「表不在」和「这一处不用管」长得一模一样**,
    # 而前者意味着回填漏了一整张表,后者才是真的没事。
    if 没建:
        print(f"  {Rd}❌ 回填这一轮要求 11 张表都在,而这几张不在:{没建}{D}")
        print(f"      这一步在流水线里排得太早了,或者那张表的建表步骤没跑。")
        c.close()
        return 1

    if 缺列 and not a.做:
        print(f"  {Y}(试跑:列还没加,所以回填也没法算。确认之后加 `--做`){D}")
        c.close()
        return 0

    if a.做:
        with c:
            for 表, _ in 缺列:
                c.execute(f"ALTER TABLE {表} ADD COLUMN shop_code TEXT")
                print(f"  + {表}.shop_code")

    回填 = 要回填的(c, 门店)
    总 = sum(len(x[2]) for x in 回填)
    print(f"\n要回填的 **{总} 行**,分布在 {len(回填)} 处:")
    for 表, 列, 坏 in 回填:
        分 = {}
        for _, 现, 该 in 坏:
            分[(现, 该)] = 分.get((现, 该), 0) + 1
        说 = " · ".join(f"{现!r}→{该!r}:{n}" for (现, 该), n in
                        sorted(分.items(), key=lambda x: -x[1])[:4])
        print(f"  {表}.{列:12} {len(坏):>6} 行   {说}")

    # **分类报出来** —— 不是门店的那些行,留空是对的,不该混进「要回填」里看
    统 = {}
    for 表, 列 in SK.带门店键的:
        for (v,) in c.execute(f"SELECT {列} FROM {表}"):
            类, _ = SK.认得出(v, 门店)
            统[类] = 统.get(类, 0) + 1
    print(f"\n全库这一列的分类:{统}")
    不认识 = 统.get("不认识", 0)
    if 不认识:
        print(f"  {Rd}❌ 有 {不认识} 行的值既不是门店、也不在「不是门店的」名单里{D}")
        print(f"      **一个新开的工坊和一个打错的字,在这件事上长得一模一样** ——")
        print(f"      前者该去 `backend/shop_key.py` 登记一行,后者该改数据。先看清是哪个。")
        c.close()
        return 1

    if not 总:
        print(f"  {G}一行都不用回填 —— 这不叫没查,是查过了{D}")
        c.close()
        return 0
    if not a.做:
        print(f"  {Y}(试跑,一个字都没改。确认之后加 `--做`){D}")
        c.close()
        return 0

    with c:
        for 表, 列, 坏 in 回填:
            for rid, _, 该 in 坏:
                c.execute(f"UPDATE {表} SET shop_code=? WHERE rowid=?", (该, rid))
    剩 = 要回填的(c, 门店)
    c.close()
    print(f"  {G}回填了 {总} 行{D}")
    if 剩:
        print(f"  {Rd}❌ 没填干净,还剩 {sum(len(x[2]) for x in 剩)} 行{D}")
        return 1
    print(f"  {G}✅ 11 处的 shop_code 都和 shop 串对上了{D}")
    print(f"      ⚠️ `shop` 那一列**没动** —— 它继续装显示串给人看,"
          f"`shop_code` 只管关联。两列并存,真相是 shop_code。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
