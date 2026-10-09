#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把操作台账里落在「世界未来」的那些行拉回来(2026-10-09 一次性修复,可回滚)。

    python3 tools/oplog_unshift.py          # 只看
    python3 tools/oplog_unshift.py --做     # 真改(先备份 + 原样存档)

## 怎么来的

`backend/oplog.py` 写 `op_log.ts` 用的是**机器时钟**,而且那是**故意的**
(它的注释:台账记「谁在什么时候真的点了这一下」—— 运维痕迹,不是演示世界里的事)。
而 `tools/shift_world.py` **从格式上分不出**这两种日期,把它当普通日期列跟着挪了。

**后果比「日期偏了」更隐蔽**:平移在把这一列 +1 的同时也把 `world_today` +1,
所以「机器时钟 − 世界日期」这个差值**被永久冻住、永不衰减**:

    583 行 @ +31 天   ← 重建刚把世界设回基准(2026-08-31)那会儿写的
    230 行 @ +1 天    ← 当天平移之前写的
   3571 行 @  0 天    ← 平移之后写的

> 一列「故意用真实时钟」的时间,和一列「该跟着世界挪」的日期,
> **在格式上长得一模一样** —— 于是一次性的时钟差被变成了永久偏移。

同一天 `shift_world` 里加了「整列日期但不挪」登记,`op_log.ts` 已经不再被挪
(咬合验过:挪一天之后 `world_today` 和 `ordr.created` 都 +1,而 `op_log.ts` 一动没动)。
**所以偏移从此会自己衰减** —— 世界每天往前走一天,偏移就少一天。
这个脚本只做一件事:**不等那 31 天**,现在就把未来那些行拉回来。

## 诚实说明:这不是「恢复真实时间」

`op_log` 里**所有**行的绝对时间本来就已经不可信了 —— 平移对每一行都保留
「ts − world_today」,所以写了很久的行也一路漂到了「今天」。
现在能信的只有**相对世界今天的偏移**。

所以这里做的是:把偏移 > 0 的行**按它自己的偏移量**拉回到偏移 0(时分秒原样保留),
让它和其余 3571 行在同一套口径上。
**它不比表里现有的时间更假,但也不更真** —— 要的只是「运维台账里不该有未来」。

> 如果你要的是「真实的操作时间」,那在这张表上已经拿不到了;
> 从今天起不再漂,**以后新写的行才是真的**。
"""
import datetime as dt
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend")]

import worldclock as W        # noqa: E402

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
DB = os.path.join(ROOT, "backend", "lanxiu.db")
存档目录 = os.path.join(ROOT, ".fakedata")
for _i, _a in enumerate(sys.argv):
    if _a == "--db" and _i + 1 < len(sys.argv):
        DB = sys.argv[_i + 1]


def 要改的(c, 今):
    """落在世界今天之后的行,连它的偏移天数一起算出来。"""
    出 = []
    for r in c.execute("SELECT id, ts FROM op_log WHERE substr(ts,1,10)>? ORDER BY id", (今,)):
        try:
            日 = dt.date.fromisoformat(str(r[1])[:10])
        except ValueError:
            continue                      # 格式不认的不碰(**不猜**)
        偏 = (日 - dt.date.fromisoformat(今)).days
        if 偏 > 0:
            出.append({"id": r[0], "ts": r[1], "偏移": 偏,
                       "新ts": 今 + str(r[1])[10:]})
    return 出


def main():
    真做 = "--做" in sys.argv
    if not os.path.exists(DB):
        print(f"{R}❌{D} 没有库 {DB}")
        return 1
    今 = W.今天().isoformat()
    c = sqlite3.connect(DB)
    行 = 要改的(c, 今)
    总 = c.execute("SELECT count(*) FROM op_log").fetchone()[0]
    print(f"世界的今天 {今} · op_log 共 {总} 行,其中落在未来的 {len(行)} 行")
    if not 行:
        print(f"  {Y}·{D} 一行都没有 —— 要么已经改过了,要么登记生效后已经自己衰减完了。"
              f"**没有动库。**")
        return 0
    分布 = {}
    for x in 行:
        分布[x["偏移"]] = 分布.get(x["偏移"], 0) + 1
    print(f"  偏移天数分布:{ {f'+{k} 天': v for k, v in sorted(分布.items())} }")

    if not 真做:
        print(f"\n{Y}只看不做{D}。真改加 --做(会先备份库 + 原样存档这些行)")
        return 0

    os.makedirs(存档目录, exist_ok=True)
    戳 = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    备 = os.path.join(存档目录, f"lanxiu.db.bak-台账拉回-{戳}")
    with open(DB, "rb") as a, open(备, "wb") as b:
        b.write(a.read())
    存 = os.path.join(存档目录, f"台账拉回-改之前-{戳}.json")
    with open(存, "w", encoding="utf-8") as f:
        json.dump(行, f, ensure_ascii=False, indent=1, default=str)
    print(f"\n库备份:{备}\n改之前的原值:{存}")

    for x in 行:
        c.execute("UPDATE op_log SET ts=? WHERE id=?", (x["新ts"], x["id"]))
    c.commit()
    print(f"拉回了 {len(行)} 行")
    剩 = 要改的(c, 今)
    if 剩:
        print(f"  {R}❌{D} 改完还剩 {len(剩)} 行在未来 —— 判据没覆盖全")
        return 1
    print(f"  {G}✅{D} 复查:一行不剩")
    print(f"  {Y}注{D}:这不是「恢复真实时间」(见脚本头)——"
          f"台账的绝对时间本来就已经漂过了。**从今天起它不再漂。**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
