#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""删掉「客户建档之前」的那些合成档位历史(2026-10-09 一次性修复,可回滚)。

    python3 tools/history_prune.py          # 只看
    python3 tools/history_prune.py --做     # 真删(先备份 + 原样存档)

## 为什么是错的,而不只是口径不同

`lifecycle_history` 里 `source='synth'` 的那些行,是 `fakedata/mkt_sop_seed.py`
给每个客户按 **12 / 9 / 6 / 3 / 0 个月前**五个时点回算出来的,
用途是给**流失预警**当训练样本(「档位怎么随事实变化」)。

而它回算时**不看那个客户那时候存不存在**。客户建档之前,
`某天的事实` 一条互动都查不到 → `idle_days = 9999` → 判成 **「流失」**。

实测:五个时点共 **29020** 条,其中落在建档之前的 **9342 条(32%)**,
而这 9342 条**全部**是 `lifecycle='流失'`。

**代价在下游**:「建档前流失 → 建档后活跃」会被当成
**「流失后又回来」的正例**,直接污染标签。三分之一的训练历史是给还不存在的人编的。

> 一条「这个人流失过又回来了」的历史,和一条「这个人那时候还没建档」的,
> **在那张表上长得一模一样** —— 字段齐、档位列有值,只有日期泄露了它。

脚本那一侧同一天也修了(`mkt_sop_seed` 里加了「基准 < customer.created 就不写」),
所以下次重建不会再造出来。这个脚本只负责清掉**已经在库里的**那些。

## 判据贴着「客户那时候存不存在」

    h.as_of < substr(cu.created, 1, 10)

**不是**贴着「档位是不是流失」—— 那样会把真正的流失历史一起删掉。
而且只动 `source='synth'`:人工/系统写的历史不碰。
"""
import datetime as dt
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "backend", "lanxiu.db")
存档目录 = os.path.join(ROOT, ".fakedata")

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

条件 = ("FROM lifecycle_history h JOIN customer cu ON cu.id = h.customer_id"
        " WHERE h.source='synth' AND cu.created IS NOT NULL"
        "   AND h.as_of < substr(cu.created,1,10)")


def main():
    真做 = "--做" in sys.argv
    if not os.path.exists(DB):
        print(f"{R}❌{D} 没有库 {DB}")
        return 1
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    总 = c.execute("SELECT count(*) FROM lifecycle_history WHERE source='synth'").fetchone()[0]
    行 = [dict(r) for r in c.execute("SELECT h.* " + 条件)]
    print(f"合成历史共 {总} 条,落在客户建档之前的 {len(行)} 条"
          f"({100 * len(行) / max(1, 总):.0f}%)")
    if not 行:
        print(f"  {Y}·{D} 一条都没有 —— 要么已经清过了,要么脚本已经不造了。**没有动库。**")
        return 0
    档 = {}
    for r in 行:
        档[r["lifecycle"]] = 档.get(r["lifecycle"], 0) + 1
    print(f"  这些行的档位分布:{档}")
    # ⚠️ 它们**应该全是「流失」** —— 建档前一条互动都查不到,idle=9999。
    # 如果出现别的档位,说明我对这批行的理解不对,**先别删**。
    if set(档) - {"流失"}:
        print(f"  {R}❌{D} 出现了「流失」以外的档位 —— 和预期不符,**不删**,先查清楚")
        return 1

    if not 真做:
        print(f"\n{Y}只看不做{D}。真删加 --做(会先备份库 + 原样存档这些行)")
        return 0

    os.makedirs(存档目录, exist_ok=True)
    戳 = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    备 = os.path.join(存档目录, f"lanxiu.db.bak-清建档前历史-{戳}")
    with open(DB, "rb") as a, open(备, "wb") as b:
        b.write(a.read())
    存 = os.path.join(存档目录, f"清建档前历史-删掉的行-{戳}.json")
    with open(存, "w", encoding="utf-8") as f:
        json.dump(行, f, ensure_ascii=False, indent=1, default=str)
    print(f"\n库备份:{备}\n删掉的行:{存}")

    ids = [r["id"] for r in 行]
    n = 0
    for i in range(0, len(ids), 500):            # 分批,别拼一个几千参数的 IN
        块 = ids[i:i + 500]
        n += c.execute("DELETE FROM lifecycle_history WHERE id IN ("
                       + ",".join("?" * len(块)) + ")", 块).rowcount
    c.commit()
    print(f"删了 {n} 条")
    剩 = c.execute("SELECT count(*) " + 条件).fetchone()[0]
    if 剩:
        print(f"  {R}❌{D} 删完还剩 {剩} 条 —— 判据没覆盖全")
        return 1
    还剩 = c.execute("SELECT count(*) FROM lifecycle_history WHERE source='synth'").fetchone()[0]
    print(f"  {G}✅{D} 复查:一条不剩。合成历史还剩 {还剩} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
