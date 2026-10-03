#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关键词筛选的**探针** —— 只为摆选型卡量一个数,**不是产品实现**。

## 为什么要有它,以及它为什么不该被当成实现

`algorithm-selection` 那条规矩说:**推荐之前先量现状数据**,
而且「**凭规则推断的误报不算数**」。

所以这一份的任务只有一个:在 `select_eval` 那 21 道题上,
量出几个候选打分法各能做到多少召回。量完它的使命就结束了 ——
**产品实现要走后台的 `selection_api`,不是这个文件**。

⚠️ 文件名叫 `probe` 不叫 `retrieval`,就是为了这一点:
> 一个被当成实现用的探针,和一个实现,在跑起来的时候长得一模一样 ——
> 而探针没有闸、没有限额、没有权限复核。

## 中文:**不分词,用字 bigram**

工具说明和任务都是中文。这个仓库在中文文本匹配上栽过七次
(「不过」不是否定、「香云纱」里有「纱」……),教训是**别自己写子串匹配**。

而这里要的不是「有没有说某个意思」,是「两段文字像不像」——
中文没有空格,标准做法是**切成相邻两字的片段(bigram)再比重叠**:
「查任务」→ 查任/任务。它不需要词典,也不会被「香云纱里有纱」那种
单字命中带偏(单字 gram 才会)。

## 三个候选,差别在「罕见词算不算更值钱」

    ① 字 bigram 重叠      问法的 bigram 有几成出现在工具说明里
    ② 加 idf 权重(BM25)  只在少数工具里出现的 bigram 更值钱
    ③ 只看工具名和首行    说明动辄几百字,**长说明会靠「碰上几个字」赢**

③ 是为了回答一个反直觉的可能:**说明越长越容易被检索到**,
而那和「它越合适」没有关系。不量一下,这条偏差看不见。
"""
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

_非中英数 = re.compile(r"[^一-鿿A-Za-z0-9]+")


def _gram(s, n=2):
    """切成字 bigram。英文和数字按整段留着(它们本来就有边界)。"""
    块 = [x for x in _非中英数.split(s or "") if x]
    出 = set()
    for b in 块:
        if re.fullmatch(r"[A-Za-z0-9_]+", b):
            出.add(b.lower()); continue
        if len(b) == 1:
            出.add(b); continue
        for i in range(len(b) - n + 1):
            出.add(b[i:i + n])
    return 出


def 工具文本():
    """{工具名: (全文, 名字+首行)} —— 两种粒度,对应候选 ① / ③。"""
    import api
    出 = {}
    for s in api.SCHEMAS + api.SHOP_SCHEMAS + api.KB_SCHEMAS:
        d = s["description"] or ""
        首 = d.strip().splitlines()[0] if d.strip() else ""
        出[s["name"]] = (f"{s['name']} {d}", f"{s['name']} {首}")
    return 出


def 造筛选器(法, k=5, 全量=None):
    """→ 一个 `(角色, 问法) -> [工具名]` 的候选集函数。

    ⚠️ `k` 就是规格 §14.3 的「候选 5」。**它是设计初值,不是实测出来的** ——
    所以这里要把 k 当变量量,不当常数。
    """
    文本 = 工具文本()
    名们 = sorted(文本)
    if 全量 is not None:
        名们 = [n for n in 名们 if n in 全量]
    粒 = 1 if 法 == "名字和首行" else 0
    文档 = {n: _gram(文本[n][粒]) for n in 名们}
    # idf:一个 bigram 出现在多少个工具里
    df = {}
    for g in 文档.values():
        for t in g: df[t] = df.get(t, 0) + 1
    N = len(名们)
    idf = {t: math.log(1 + (N - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def 打分(q):
        qg = _gram(q)
        出 = []
        for n in 名们:
            共 = qg & 文档[n]
            if 法 == "idf加权":
                s = sum(idf.get(t, 0) for t in 共)
            else:
                s = len(共)
            # ⚠️ **分母用问法的长度,不用文档长度。** 用文档长度会让
            # 短说明的工具天然占优(反过来 ③ 那个候选就是为了量这条偏差)。
            出.append((s / max(len(qg), 1), n))
        出.sort(key=lambda x: (-x[0], x[1]))
        return [n for s, n in 出[:k] if s > 0]

    return lambda 角色, q: 打分(q)


if __name__ == "__main__":
    import select_eval as SE
    坏 = SE.前提()
    if 坏:
        print("❌ 题集前提不成立,量出来的数不算数:", 坏); sys.exit(1)

    # ⚠️ 探针只在 `all` 能挂到的 77 个里挑 —— 和「全量」那一组同一个池子。
    # 不限的话它能挑到版师那 4 个(安全边界上不给全能助手的),
    # **那会让召回虚高,而虚高的理由和「筛选器更好」看起来一样**。
    import sdk
    池 = {t.rsplit("__", 1)[-1] for t in sdk._tools_for("all")}

    print("关键词筛选探针 · 在 select_eval 的 21 道题上量召回")
    print("=" * 88)
    print(f"  池子:{len(池)} 个(`all` 挂得到的那些 —— 和「全量」那一组同一个池子)")
    print(f"  {'打分法':14s} {'k':>3s}  {'召回':>8s}  {'候选均':>7s}   说明")
    print("  " + "-" * 84)
    基 = None
    for 法 in ("bigram重叠", "idf加权", "名字和首行"):
        for k in (3, 5, 10, 20):
            f = 造筛选器(法, k=k, 全量=池)
            r = SE.量一组(f, f"{法}@{k}")
            说 = ""
            if 法 == "bigram重叠" and k == 5: 基 = r["召回过"]
            print(f"  {法:14s} {k:3d}  {r['召回过']:4d}/{r['共']:<3d}  "
                  f"{r['候选均']:7.1f}   {说}")
    print("  " + "-" * 84)
    print(f"  对照:全量不筛选 = 21/21,候选 77;按角色 = 21/21,候选 52.4")
    print()
    print("⚠️ **这些数只够摆选型卡,不够下结论**:")
    print("   · 21 题,而且是**我自己造的题** —— 真值是我标的")
    print("   · 只量召回。「候选集里有」不等于「模型会调」—— 那是第二层")
    print("   · 候选上限 k 是规格 §14.3 的设计初值,**不是实测出来的**,所以这里当变量量")
