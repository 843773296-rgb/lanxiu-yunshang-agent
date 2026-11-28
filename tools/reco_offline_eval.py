#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推荐算法离线对比 —— 只读库,不写

    python3 tools/reco_offline_eval.py [--种子数 300] [--窗口 60]

## 比什么(用户 2026-11-28:相似人群「比重量了再定」;协同过滤和矩阵分解「都做」)

把时间切在 T0 = 世界今天 − 窗口天:T0 之前的浏览和订单当「已知」,T0 之后的订单当「后来真买了什么」。

**一、找像 A 的人(相似人群扩展)** —— 每个种子客户 A(T0 前买过东西的人里按客户号均匀抽):
   找最像 A 的 50 人,看这 50 人里有几个在 T0 之后**真买了 A 在 T0 前买过、他自己 T0 前没买过**的东西。
   比:只行为 / 行为 7 画像 3 / 五五开 / 只画像 / 随便挑 50 人(基准线)。
**二、给这位客户推什么(前 10 件)** —— 对 T0 之后真买了东西的人,看前 10 推荐里有没有中:
   商品对商品协同过滤 / 矩阵分解 / 她品类的热销(基准线)。

## ⚠️ 读数之前先读这一段

数据是造的:浏览按拟定参数铺、画像和买什么无关(见 knowledge/lookalike.py 顶上)。
所以这张表**只能比相对高低、看算法行为**,不能读成「上线后命中率会是多少」。
画像比重越高越差,在这套数据上是**预期之内**的 —— 它说明的是「造数时画像是随机的」,不是「画像没用」。
"""
import datetime as dt
import os
import random
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import browse as B          # noqa: E402
import lookalike as L       # noqa: E402
import reco as R            # noqa: E402
from dbpath import 路径 as _库路径   # noqa: E402

比重档 = (("只看行为", 1.0), ("行为 7 画像 3", 0.7), ("五五开", 0.5), ("只看画像", 0.0))


def 取数(db):
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as c:
        c.row_factory = sqlite3.Row
        今 = dt.date.fromisoformat(c.execute("SELECT v FROM world_meta WHERE k='world_today'").fetchone()[0])
        浏览 = [dict(r) for r in c.execute("SELECT customer_id, ts, event, spu, dwell_s FROM mp_event")]
        订单 = [dict(r) for r in c.execute(
            "SELECT o.customer_id, o.created, i.spu, o.amount FROM ordr o JOIN ordr_item i ON i.order_id=o.id "
            "WHERE o.customer_id IS NOT NULL AND i.spu IS NOT NULL AND o.status NOT IN ('已取消','待付款')")]
        客 = [dict(r) for r in c.execute("SELECT * FROM customer WHERE merged_into IS NULL")]
        孩子们 = {str(r[0]) for r in c.execute(
            "SELECT DISTINCT customer_id FROM wearer WHERE relation IN (%s)" % ",".join("?" * len(L.孩子关系)),
            sorted(L.孩子关系))}
        品 = {r["spu"]: dict(r) for r in c.execute("SELECT spu, category, status FROM product")}
    return 今, 浏览, 订单, 客, 孩子们, 品


def 跑(db, 种子数=300, 窗口=60, 说=print):
    今, 浏览, 订单, 客, 孩子们, 品 = 取数(db)
    T0 = 今 - dt.timedelta(days=窗口)
    T0s = T0.isoformat()
    浏前 = [r for r in 浏览 if r["ts"] < T0s]
    单前 = [r for r in 订单 if str(r["created"]) < T0s]
    单后 = [r for r in 订单 if str(r["created"]) >= T0s]
    可推 = {s for s, p in 品.items() if p["status"] == "上架"}
    买前, 买后 = {}, {}
    for r in 单前:
        买前.setdefault(str(r["customer_id"]), set()).add(r["spu"])
    for r in 单后:
        买后.setdefault(str(r["customer_id"]), set()).add(r["spu"])
    # 消费档:T0 前的消费额五分位(不用 customer.amount_12m —— 那一列含 T0 之后,会泄题)
    花 = {}
    for r in 单前:
        花[str(r["customer_id"])] = 花.get(str(r["customer_id"]), 0.0) + float(r["amount"] or 0)
    排 = sorted(花, key=lambda u: (花[u], u))
    消费档之 = {u: min(4, i * 5 // max(1, len(排))) for i, u in enumerate(排)}
    画像之 = {str(k["id"]): L.画像(k, 孩子们, 消费档之, T0) for k in 客}
    人们 = sorted(画像之)
    M = L.行为向量(浏前, 单前, T0)
    W, 模 = L.逆人数加权(M)
    说(f"切在 {T0}(世界今天 {今} 往前 {窗口} 天):T0 前浏览 {len(浏前)} 行 / 订单行 {len(单前)};"
       f"T0 后订单行 {len(单后)}、{len(买后)} 人;客户 {len(人们)}")

    # ── 一、找像 A 的人 ──
    种子池 = sorted(u for u in 买前 if u in 画像之)
    rng = random.Random(20261128)
    种子们 = sorted(rng.sample(种子池, min(种子数, len(种子池))))
    def 中几个(A, 名单):
        a = 买前.get(A, set())
        return sum(1 for u in 名单 if (买后.get(u, set()) - 买前.get(u, set())) & a)
    结果 = {}
    for 名, 比 in 比重档:
        中 = 0
        for A in 种子们:
            像 = L.找像的人(A, 人们, W, 模, 画像之, 比重=比, k=L.相似人数)
            中 += 中几个(A, [p["客户"] for p in 像])
        结果[名] = 中
    中 = 0
    for A in 种子们:
        中 += 中几个(A, rng.sample([u for u in 人们 if u != A], L.相似人数))
    结果["随便挑 50 人(基准线)"] = 中
    总 = len(种子们) * L.相似人数
    说(f"\n一、找像 A 的人:{len(种子们)} 个种子 × 每人 {L.相似人数} 个像的人 = {总} 人次;"
       "「中」= 这个人 T0 后真买了 A 在 T0 前买过、他自己没买过的东西")
    基 = 结果["随便挑 50 人(基准线)"] or 1
    for 名, 中 in 结果.items():
        说(f"   {名:14s} 中 {中:5d}  ({中 / 总:.2%})  是基准线的 {中 / 基:.1f} 倍")

    # ── 二、给这位客户推什么 ──
    有后 = {u: 买后[u] - 买前.get(u, set()) for u in 买后 if u in M}
    有后 = {u: v for u, v in 有后.items() if v}
    相 = R.商品相似(R.交互(浏前, T0))   # 商品相似只用浏览(订单进来会让「买了 A 的都买了 B」被下单那次浏览重复算)
    U, V = R.矩阵分解(M)
    销量 = {}
    for r in 单前:
        销量[r["spu"]] = 销量.get(r["spu"], 0) + 1
    推_协, 推_分, 推_热 = {}, {}, {}
    for u in 有后:
        bought = 买前.get(u, set())
        推_协[u] = [x["商品"] for x in R.给人推荐_协同(M[u], 相, 可推, bought, 销量=销量)]
        推_分[u] = [x["商品"] for x in R.给人推荐_分解(U.get(u), V, 可推, bought)]
        推_热[u] = R.热销兜底({s: p["category"] for s, p in 品.items()}, 销量, 可推, bought,
                           {品[s]["category"] for s in bought if s in 品})
    说(f"\n二、给这位客户推什么(前 {R.推荐几件} 件):T0 后买了新东西的 {len(有后)} 人,前 10 里有她后来真买的就算中")
    for 名, 推 in (("商品对商品协同过滤", 推_协), ("矩阵分解", 推_分), ("她品类的热销(基准线)", 推_热)):
        中, n, 率 = R.命中率(推, 有后)
        说(f"   {名:14s} 中 {中:5d} / {n}  ({率:.2%})")
    说("\n⚠️ 数据是造的:只比相对高低;画像比重越高越差在这套数据上是预期之内(造数时画像随机)")
    return 结果


if __name__ == "__main__":
    a = sys.argv[1:]
    n = int(a[a.index("--种子数") + 1]) if "--种子数" in a else 300
    w = int(a[a.index("--窗口") + 1]) if "--窗口" in a else 60
    跑(_库路径(), n, w)
