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
# 一个「2758 个存错」其实是三个病加起来(数据工厂 2026-10-09 拆出来的)——
# 只报一个总数的话,修掉其中一个,剩下的仍红在同一条判据上,看着像「没修好」。所以分开报:
#   B  最后互动日比名下最新一张单还早 —— 这一列自己过期了(口径:下了单就算互动,
#      待确认 / 没付款 / 后来取消的都算 —— 用户 2026-10-09 拍的)
#   A  存的档位要有完成单才可能命中,而名下一张完成单都没有 —— 存的值是旧的
#   C  其余:存的档位 ≠ 按存的事实重算(10-09 那次的主体:造数脚本算闲置不算下单)
要单的档 = {"新客", "忠诚", "高价值"}
最新单 = dict(c.execute("SELECT customer_id, max(substr(created,1,10)) FROM ordr GROUP BY 1").fetchall())
有完成单 = {r[0] for r in c.execute("SELECT DISTINCT customer_id FROM ordr WHERE status='完成'")}
总, 类, 样 = 0, {"B": collections.Counter(), "A": collections.Counter(), "C": collections.Counter()}, {}
for r in c.execute("SELECT * FROM customer"):
    d = dict(r)
    总 += 1
    新 = 最新单.get(d["id"])
    if 新 and (d["last_interact"] or "")[:10] < 新:
        k = "B"; 说 = f'最后互动 {d["last_interact"]} < 最新单 {新}'
        类[k][("最后互动早于最新单",)] += 1
    else:
        v = L.decide(dict(d, days_since_first_order=ago(d["first_order"]),
                          days_since_manual=ago(d["manual_at"])))["生命周期"]
        if d["lifecycle"] == v:
            continue
        k = "A" if d["lifecycle"] in 要单的档 and d["id"] not in 有完成单 else "C"
        类[k][(d["lifecycle"], v)] += 1
        说 = f'存「{d["lifecycle"]}」/ 算「{v}」(最后互动 {d["last_interact"]})'
    样.setdefault(k, f'{d["id"]} {说}')

名 = {"B": "最后互动日比名下最新订单还早", "A": "存的档位要有完成单,而名下一张都没有",
     "C": "存的档位 ≠ 按存的事实重算"}
print(f"存着的档位 vs 按 {TODAY} 重算(验了 {总} 个客户)")
if 总 == 0:
    print(f"  {R}❌{D} 客户表是空的 —— 空集合上什么都成立,这不算过"); sys.exit(1)
坏 = 0
for k in ("B", "A", "C"):
    n = sum(类[k].values())
    坏 += n
    if not n:
        print(f"  {G}✅{D} {k} · {名[k]}:0 个"); continue
    print(f"  {R}❌{D} {k} · {名[k]}:{n} 个")
    for kk, m in 类[k].most_common(4):
        print(f"      {' → '.join(kk)} {m} 个")
    print(f"      例:{样[k]}")
sys.exit(1 if 坏 else 0)
