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


def 要加列的(c):
    return [(t, col) for t, col in SK.带门店键的 if not SK.有列(c, t)]


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
    print(f"\n要加列的 {len(缺列)} 处:{[t for t, _ in 缺列] or '一处都不缺'}")

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
