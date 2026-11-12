#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给预约加「客户点名了谁」三态 + 预约渠道,给客户加来源渠道 —— 四列。

来路:执行手册 W21,用户 11-12 拍板第十二条:
「预约加客户点名了谁三态 + 预约渠道,客户加来源渠道:三列都加;走迁移加列;
  派单建议读点名;渠道先存不分析」。

    appointment.named_advisor_no  点名的那位顾问工号(staff.no)
    appointment.named_state       '点名' / '没点' / '不详' —— 带 CHECK,库自己挡非法值
    appointment.channel           预约渠道(先存不分析)
    customer.source_channel       来源渠道(先存不分析)

默认 **dry-run 只报不改**,`--go` 才真改。**幂等**:已经有的列跳过,再跑一遍什么都不做。
只加列、不回填 —— 老预约那一列是 NULL,意思是「这条是加列之前建的,当时没问」,
**不许回填成「不详」或「没点」**:那是替当时的人编一个答案。

## 为什么 `named_state` 是三态,不是「有没有工号」

    点名  客户说了要谁 —— 派单建议**同层最强**的依据(backend/booking.py suggest_why)
    没点  问过了,客户说谁都行 —— 派单照原排序
    不详  没问 / 客户没说清 —— 派单也照原排序,但**和「没点」是两件事**:
          将来要看「点名率」时,不详混进没点会把点名率算低

「工号是空的」同时可能是「没点」和「不详」,所以要单独一列把它说出来。

## 为什么 CHECK 写在列上

SQLite 3.37 起 `ALTER TABLE … ADD COLUMN` 可以带 CHECK(本机 3.50 实测)。
写入口(`booking.校验点名`)照样校验,而**库这一道挡的是绕开写入口的写**(脚本、手工 SQL)。
两道是叠加,不是二选一。

## 跟 seed.py 的关系

`backend/seed.py` 的 `CREATE TABLE appointment / customer` 同一个提交带上了这四列(CI 每天从零建库);
**这个脚本管的是已经存在的库**(共享真库)—— 写在建表语句里的列,在已经存在的库上不存在。
⚠️ 两边的列定义要一致:改一边记得改另一边(`backend/named_advisor_check.py` 在库上实测 CHECK 真的挡)。
"""
import os
import sqlite3
import sys
from contextlib import closing

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "lanxiu.db")

# (表, 列, 列定义)。**列定义和 seed.py 的建表语句逐字一致。**
列们 = [
    ("appointment", "named_advisor_no", "TEXT"),
    ("appointment", "named_state",
     "TEXT CHECK(named_state IS NULL OR named_state IN ('点名','没点','不详'))"),
    ("appointment", "channel", "TEXT"),
    ("customer", "source_channel", "TEXT"),
]


def plan(c):
    """→ [(表, 列, 定义, 已有?)]"""
    出 = []
    for 表, 列, 定义 in 列们:
        有 = {r[1] for r in c.execute(f"PRAGMA table_info({表})")}
        if not 有:
            raise SystemExit(f"❌ 库里没有 {表} 表 —— 这不是一个建好的库({os.path.realpath(DB)})")
        出.append((表, 列, 定义, 列 in 有))
    return 出


def main():
    go = "--go" in sys.argv
    print(f"{'真跑' if go else 'dry-run(加 --go 才真改)'} · 库 {os.path.realpath(DB)}")
    with closing(sqlite3.connect(DB)) as c:
        print(f"  SQLite {sqlite3.sqlite_version}")
        p = plan(c)
        要加 = [x for x in p if not x[3]]
        for 表, 列, 定义, 已有 in p:
            print(f"  {'· 已有,跳过' if 已有 else ('+ 加列' if go else '+ 将加列')}  {表}.{列}  {定义}")
        if not 要加:
            print("  四列都在 —— 什么都不用做(幂等)")
            return 0
        if not go:
            print(f"  共 {len(要加)} 列要加;只加列不回填(老行保持 NULL = 加列之前建的,当时没问)")
            return 0
        with c:
            for 表, 列, 定义, _ in 要加:
                c.execute(f"ALTER TABLE {表} ADD COLUMN {列} {定义}")
        # 加完核一遍:列真的在了
        后 = plan(c)
        缺 = [f"{t}.{k}" for t, k, _, 有 in 后 if not 有]
        if 缺:
            print(f"  ❌ 加完还缺:{缺}")
            return 1
        print(f"  ✅ 加了 {len(要加)} 列,四列都在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
