#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存着的档位 = 按今天重算的档位(2026-10-09 用户在页面上撞到「休眠 1395」而按今天算只有 871)。

`customer.lifecycle` 是**存量字段**,谁写库谁负责重算;而页面和模型报人数读的就是它。
2026-10-09 查出 2731 个对不上,根因在造数脚本(fakedata/mkt_sop_seed.py):
它算「多久没互动」只看跟进 / 预约 / 日程,**不算下单** —— 刚下过单的人被判成休眠写回档案,
`matched` 列却没跟着改,于是同一行里 matched 写「活跃/高价值」、lifecycle 写「休眠」。

> 一个存着的档位和一个按当前事实算出来的档位,在那一列上长得一模一样 —— 直到有人数人头。

判定口径**只调** knowledge/lifecycle.decide()(人工调档的保护期也由它判),这里不另写一份。
「今天」用业务世界的今天(seed.TODAY)。
"""
import os, sys, sqlite3, datetime as dt, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge")]
import lifecycle as L
from seed import TODAY

G, R, D = "\033[32m", "\033[31m", "\033[0m"
T = dt.date.fromisoformat(TODAY)


def ago(s):
    return (T - dt.date.fromisoformat(str(s)[:10])).days if s else None


c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
c.row_factory = sqlite3.Row
总, 错, 样 = 0, collections.Counter(), []
for r in c.execute("SELECT * FROM customer"):
    d = dict(r)
    总 += 1
    v = L.decide(dict(d, days_since_first_order=ago(d["first_order"]),
                      days_since_manual=ago(d["manual_at"])))["生命周期"]
    if d["lifecycle"] != v:
        错[(d["lifecycle"], v)] += 1
        if len(样) < 3:
            样.append(f'{d["id"]} 存「{d["lifecycle"]}」/ 算「{v}」(最后互动 {d["last_interact"]})')

print(f"存着的档位 vs 按 {TODAY} 重算")
if 总 == 0:
    print(f"  {R}❌{D} 客户表是空的 —— 空集合上什么都成立,这不算过"); sys.exit(1)
if 错:
    n = sum(错.values())
    print(f"  {R}❌{D} {n}/{总} 个客户存的档位和重算对不上")
    for (存, 算), k in 错.most_common(6):
        print(f"      存「{存}」→ 算「{算}」 {k} 个")
    for s in 样:
        print(f"      例:{s}")
    sys.exit(1)
print(f"  {G}✅{D} {总} 个客户全部对得上")
