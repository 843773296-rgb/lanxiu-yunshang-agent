#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品推荐 · 协同过滤(商品对商品,归一化)+ 矩阵分解(隐式反馈 ALS)—— 口径 + 纯函数

## 用户怎么拍的(2026-11-28,一张卡四题)

  ① 算法:**商品对商品的协同过滤(归一化)和矩阵分解都做**(用户答「1 3 都做」)。
     实测:不归一化时,所有商品的前 5 推荐里 65% 是全店前 10 爆款;归一化(余弦)后 18%。
  ② 动作加权(推荐项):看过 1;停留超过 1 分钟再 +1;加购 3;分享 3;下单 5;按时间打折,90 天减半。
     **这组数是拍脑袋的**,参考的是业界「隐式反馈加权」的常见做法(看 < 加购 < 买),不是这家店量出来的。
  ③ 闸与兜底(推荐项):她买过的不推;只推在售的;两件至少 5 个人一起看过才算相关(拍脑袋;
     11-28 有 2.1 万对过线);推不出来退到「她买过的品类里的热销」并标明是兜底;
     拿去联系客户时同既有推荐,不同意营销的不推(那一道闸在用的地方加,不在这里)。
  ④ 范围:连带接进召回名单(挂到助手的那一步仍等工具说明区的维护方回来)。

## ⚠️ 数据是造的

浏览数据是 `tools/backfill_browse.py` 按拟定参数造的 —— 协同过滤「学到」的,本质上就是造数规则
(看自己买过的品类、热门的被看得多)。在这上面只能验**算法行为对不对**(归一化压得住爆款、闸都生效、
同一份输入结果一样),**推得好不好要等接了真埋点才说得清**。离线对比的命中率同理,只能比相对高低。

## 为什么矩阵分解是纯 Python

项目约定纯标准库(只有 agentsite 例外),机器上也没装科学计算包。292 件商品、几千人,
小规模的隐式 ALS 纯 Python 跑得动(维度和迭代次数取小值,见下面常量)。

口径模块不取当前日期:时间(今)由调用方传进来。
"""
import math
import random

import browse as _B

# ── ② 动作权重(用户 11-28 拍「加权」;数是拍脑袋的)────────────────────────
权重 = {_B.进入详情: 1.0, _B.加购: 3.0, _B.分享: 3.0, _B.下单: 5.0}
久看秒, 久看加分 = 60, 1.0          # 「离开详情」那一行停留超过 60 秒,再 +1
半衰期天 = 90                      # 90 天前的动作算一半

# ── ③ 闸 ───────────────────────────────────────────────────────────────
最少共同人数 = 5                   # 两件至少这么多人一起有过动作,才算相关(拍脑袋;11-28 有 2.1 万对过线)
推荐几件 = 10
# 给人推荐的爆款降权:分数 ÷ (销量 + 1) ^ 热门降权。用户 2026-11-28 拍「轻度降权」——
# 离线对比(虚拟数据):不降 推中 36.6% · 前 3 里全店前 10 爆款占 75%;0.1 → 31.5% · 45%;0.2 → 19% · 7%;
# 按相似度加权平均 15.6% · 18%。商品对商品那一层的余弦压住了单件的爆款,可落到「给人推」时,
# 她看过的每一件都和爆款沾边、一加就加回来了 —— 所以这一层要再降一次。力度是参数,接真数据后重跑对比再调
热门降权 = 0.1

# ── 矩阵分解(隐式 ALS,Hu / Koren / Volinsky 2008)的技术参数 —— 只报不问 ──────
MF维度, MF正则, MF置信系数, MF迭代, MF种子 = 10, 0.1, 2.0, 8, 20261128


def _天(ts):
    return ts[:10]


def 交互(行们, 今):
    """事件行 → {客户: {商品: 分}}。行要有 customer_id / ts / event / spu / dwell_s。今 = date。"""
    import datetime as dt
    m = {}
    for r in 行们:
        s, ev = r.get("spu"), r.get("event")
        if not s:
            continue
        w = 权重.get(ev, 0.0)
        if ev == _B.离开详情 and (r.get("dwell_s") or 0) > 久看秒:
            w = 久看加分
        if not w:
            continue
        龄 = (今 - dt.date.fromisoformat(_天(r["ts"]))).days
        w *= 0.5 ** (max(0, 龄) / 半衰期天)
        d = m.setdefault(str(r["customer_id"]), {})
        d[s] = d.get(s, 0.0) + w
    return m


# ── ① 商品对商品协同过滤(余弦归一化)─────────────────────────────────────
def 商品相似(矩阵, 最少人数=最少共同人数):
    """→ {商品: [(相关商品, 相似度, 共同人数)] 按相似度降序}。相似度 = 两件的加权向量余弦。
    热门商品和谁都「一起被看」,不归一化的话推荐被爆款占满 —— 余弦把「单纯热门」除掉。"""
    模 = {}
    点积, 共同 = {}, {}
    for 人, 物 in 矩阵.items():
        项 = sorted(物.items())
        for a, wa in 项:
            模[a] = 模.get(a, 0.0) + wa * wa
        for i in range(len(项)):
            a, wa = 项[i]
            for j in range(i + 1, len(项)):
                b, wb = 项[j]
                k = (a, b)
                点积[k] = 点积.get(k, 0.0) + wa * wb
                共同[k] = 共同.get(k, 0) + 1
    相 = {}
    for (a, b), p in 点积.items():
        n = 共同[(a, b)]
        if n < 最少人数:
            continue
        s = p / math.sqrt(模[a] * 模[b])
        相.setdefault(a, []).append((b, s, n))
        相.setdefault(b, []).append((a, s, n))
    for a in 相:
        相[a].sort(key=lambda x: (-x[1], x[0]))
    return 相


def 看了还看(相, spu, 可推, k=推荐几件):
    """「看了这件的人还看了」→ [(商品, 相似度, 共同人数)]。可推 = 在售商品集合。"""
    return [x for x in 相.get(spu, []) if x[0] in 可推 and x[0] != spu][:k]


def 给人推荐_协同(她, 相, 可推, 买过, k=推荐几件, 销量=None, 降权=热门降权):
    """她 = {商品: 分}。分数 = Σ 她对 X 的分 × X 和候选的相似度 ÷ (销量 + 1)^降权;理由 = 贡献最大的那件。
    销量 = {商品: 件数};不给就不降权(手算样本里用)。"""
    分, 因 = {}, {}
    for x, w in 她.items():
        for y, s, n in 相.get(x, []):
            if y in 买过 or y not in 可推:     # 看过没买的照样推(那正是她犹豫过的)
                continue
            v = w * s
            分[y] = 分.get(y, 0.0) + v
            if v > 因.get(y, (None, 0, 0))[1]:
                因[y] = (x, v, n)
    if 销量 is not None and 降权:
        分 = {y: v / (销量.get(y, 0) + 1) ** 降权 for y, v in 分.items()}
    排 = sorted(分, key=lambda y: (-分[y], y))[:k]
    return [{"商品": y, "分": round(分[y], 4), "因为看过": 因[y][0], "共同人数": 因[y][2]} for y in 排]


# ── 兜底:她买过的品类里的热销 ─────────────────────────────────────────────
def 热销兜底(品类之, 销量, 可推, 买过, 她的品类, k=推荐几件):
    """品类之 = {商品: 品类};销量 = {商品: 件数}。她没有品类(没买过)时退到全店热销。"""
    池 = [s for s in 可推 if s not in 买过 and (not 她的品类 or 品类之.get(s) in 她的品类)]
    if not 池:
        池 = [s for s in 可推 if s not in 买过]
    return sorted(池, key=lambda s: (-销量.get(s, 0), s))[:k]


# ── ① 矩阵分解(隐式反馈 ALS)────────────────────────────────────────────
def _解(A, b):
    """高斯消元解 A x = b(A 对称正定,维度 10 上下)。"""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        for r in range(c + 1, n):
            f = M[r][c] / piv
            if f:
                Mr, Mc = M[r], M[c]
                for j in range(c, n + 1):
                    Mr[j] -= f * Mc[j]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][j] * x[j] for j in range(r + 1, n))) / M[r][r]
    return x


def _格拉姆(F, k):
    G = [[0.0] * k for _ in range(k)]
    for v in F.values():
        for i in range(k):
            vi = v[i]
            Gi = G[i]
            for j in range(k):
                Gi[j] += vi * v[j]
    return G


def _半步(交, 对方, k, 正则, 置信):
    """固定对方的向量,逐个解这一边。交 = {这一边: {对方: 分}}。"""
    G = _格拉姆(对方, k)
    out = {}
    for u, items in 交.items():
        A = [row[:] for row in G]
        for i in range(k):
            A[i][i] += 正则
        b = [0.0] * k
        for it, w in items.items():
            y = 对方[it]
            c = 1.0 + 置信 * w
            for i in range(k):
                yi = y[i]
                b[i] += c * yi
                Ai = A[i]
                for j in range(k):
                    Ai[j] += (c - 1.0) * yi * y[j]
        out[u] = _解(A, b)
    return out


def 矩阵分解(矩阵, k=MF维度, 正则=MF正则, 置信=MF置信系数, 迭代=MF迭代, 种子=MF种子):
    """→ (人向量, 商品向量)。同一份输入、同一个种子,结果一样(按键排序初始化)。"""
    rng = random.Random(种子)
    物们 = sorted({s for d in 矩阵.values() for s in d})
    V = {s: [rng.gauss(0, 0.1) for _ in range(k)] for s in 物们}
    人交 = {u: 矩阵[u] for u in sorted(矩阵)}
    物交 = {}
    for u, d in 人交.items():
        for s, w in d.items():
            物交.setdefault(s, {})[u] = w
    物交 = {s: 物交[s] for s in sorted(物交)}
    U = {}
    for _ in range(迭代):
        U = _半步(人交, V, k, 正则, 置信)
        V = _半步(物交, U, k, 正则, 置信)
    return U, V


def 给人推荐_分解(人向量, 物向量, 可推, 买过, k=推荐几件):
    if 人向量 is None:
        return []
    分 = {s: sum(a * b for a, b in zip(人向量, v)) for s, v in 物向量.items() if s in 可推 and s not in 买过}
    排 = sorted(分, key=lambda s: (-分[s], s))[:k]
    return [{"商品": s, "分": round(分[s], 4)} for s in 排]


# ── 离线对比:训练截在 T0,看 T0 之后 30 天里她真买的东西有没有在前 10 里 ────────
def 命中率(推荐们, 真买):
    """推荐们 = {人: [商品…]};真买 = {人: {商品…}} → (命中人数, 有真买的人数, 命中率)。"""
    人们 = [u for u in 真买 if 真买[u]]
    中 = sum(1 for u in 人们 if set(推荐们.get(u, [])) & 真买[u])
    return 中, len(人们), (round(中 / len(人们), 4) if 人们 else None)
