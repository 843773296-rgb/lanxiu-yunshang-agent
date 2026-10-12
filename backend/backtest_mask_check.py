#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回测那 201 条已处理的差评时,**不许让模型看见人工是怎么处置的**。

    python3 backend/backtest_mask_check.py

只读,真库一行不碰。

## 为什么要有这条

方案 V2.0 闸四是**影子回测**:拿已处理的 201 条差评跑一遍 AI,和人工的处置比。
而那两个材料工具会把**人工的处置记录**一起吐出来 ——
那是**开卷考**,而开卷考出来的分数**照样是一个漂亮的分数**:

> **一个开卷考的 85 分和一个闭卷考的 85 分,在成绩单上长得一模一样。**
> 而这个项目栽过的那次更狠:「不符合预期的数会被查,符合预期的数会被信」——
> 回测分数高本来就是预期,**没有任何信号提示人去怀疑它**。

这和 `truth` 表那条红线是同一个形状(评测答案不许经工具暴露),
差别是这次答案藏在一个**正当的材料字段**里 ——
`service_records` 给「这个客户历史上的差评」是闸一明定的第三类材料。

## 这条判据验什么、不验什么

**验**:两个工具吐出来的键名里,凡是带处置痕迹的(按 `knowledge/rating.处置痕迹的标记`
认,不枚举键名),**必须在 `回测要遮的字段` 里登记过**。
以后给工具加一列 `处理人`,清单不跟着加,这条当场红。

⚠️ **不验「回测真的遮住了」** —— 差评的 AI 辅助**默认关闭**(业务 2026-10-10),
回测那条路还没建。所以这条判据管的是**清单不过期**,不是**遮的动作已经发生**。
> 「有清单」和「遮住了」是两件事,而这条只管前者。
真遮的那一步要在回测脚本里做,等它建起来再加判据 —— **已登记**。

## ⚠️ 遮的粒度:被判那一条自己,不是这个客户的全部历史

「这位客户上次怎么处理的」是**刻意给的**(分得清第一次和第三次)。
一刀切遮四个字段会把那类材料一起遮掉,**而遮完回测分数照样出得来**。
口径写在 `knowledge/rating.回测遮的粒度`,这儿不抄一份。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]
import api
import rating as R

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("给 bad_ratings 的 SELECT 加一列 `r.handled_by 处理人`(清单没跟着加)",
     "带处置痕迹的键名,都在「回测要遮的字段」里登记过"),
    ("往 knowledge/rating.回测要遮的字段 里加一个没有工具会吐的「处理门店」(清单留死条目)",
     "清单里没有死条目"),
]


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else Rd + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


def 扒键(x, 出=None):
    出 = [] if 出 is None else 出
    if isinstance(x, dict):
        for k, v in x.items():
            出.append(str(k)); 扒键(v, 出)
    elif isinstance(x, (list, tuple)):
        for v in x:
            扒键(v, 出)
    return 出


print("回测不许开卷:两个材料工具吐的处置痕迹都登记过吗 · 只读")
c = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
一 = c.execute("""SELECT r.pkg_id, o.shop FROM rating r
                  LEFT JOIN ordr o ON o.id=r.order_id
                  WHERE r.star<=? AND o.shop IS NOT NULL LIMIT 1""", (R.差评线,)).fetchone()
店长 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='店长' AND shop=? LIMIT 1",
                 (一["shop"],)).fetchone() if 一 else None
ck("库里有差评样本可验(没有就不叫通过)", bool(一) and bool(店长),
   f"差评 {bool(一)} / 店长 {bool(店长)}")

if 一 and 店长:
    with api.as_user(dict(店长)):
        键 = 扒键(api.bad_ratings(status="全部")) + 扒键(api.service_records(pkg=一["pkg_id"]))
    痕迹 = sorted({k for k in 键 if R.回测要遮吗(k)})
    漏登记 = [k for k in 痕迹 if k not in R.回测要遮的字段]
    ck(f"两个工具一共吐了 {len(set(键))} 个键名,其中 {len(痕迹)} 个带处置痕迹", len(set(键)) >= 20,
       f"只扒到 {len(set(键))} 个 —— **是没扒到东西,不是都通过**")
    # ⚠️ **判据名写成「成立的那个性质」,不是「失败的那个条件」。**
    # 第一版写的是「这些键名在泄露人工处置,却没在清单里登记」——
    # 它红的时候读得通,**绿的时候读起来是反的**(「✅ …却没登记」)。
    # 而人扫门禁输出时是按行读的,一行读反就会去查一个不存在的问题。
    ck("带处置痕迹的键名,都在「回测要遮的字段」里登记过", not 漏登记,
       f"{漏登记} —— 加了一列就要在 `knowledge/rating.回测要遮的字段` 里登记一条,"
       f"**不然清单会悄悄过期,而回测仍然显示很漂亮**")
    # 清单里不许留死条目:登记了却没有任何工具会吐,那是一条看起来管好了的空账
    死条目 = [x for x in R.回测要遮的字段 if x not in 痕迹]
    ck("清单里没有死条目(登记了却没有工具会吐)", not 死条目,
       f"{死条目} —— 一条没人会吐的字段,**看起来像「这个洞堵上了」**,而它根本不在场")
    ck("「这个客户历史上的差评」那一类照样给(闸一第三类材料没被一起遮掉)",
       any("历史上的差评" in k for k in 键),
       "service_records 不再给客户历史 —— 那会把该给的材料一起遮掉")

c.close()
print()
if bad:
    print(f"{Rd}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    for b in bad:
        print(f"    {Rd}❌{D} {b}")
    sys.exit(1)
print(f"{G}✅ 处置痕迹都登记过(验了 {n} 条){D}")
print(f"    {Y}⚠️ 它只管**清单不过期**,不管「回测真的遮住了」 —— "
      f"差评的 AI 辅助默认关闭,回测那条路还没建(已登记){D}")
