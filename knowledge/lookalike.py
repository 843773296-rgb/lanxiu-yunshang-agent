#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找「跟 A 像的人」,把 A 买过的推给他们 —— 相似人群扩展(look-alike)· 口径 + 纯函数

## 用户怎么拍的(2026-11-28)

用户原话:「我们要知道跟 A 客户的人,都买了啥,看了啥,用这个标签去套跟 A 相似的客户,
向他们推荐 A 客户买过的东西。人物模型越具体,成功率越高。」随后一张卡四题:
  ① 相似 = **行为 + 画像混合**(行为:买过 / 看过 / 加购的重合;画像:下面四组特征)
  ② 两者比重 **量了再定** —— 离线跑「只行为 / 7:3 / 5:5 / 只画像」,结果给用户拍(`行为比重` 先放 0.7 占位)
  ③ 画像四组全要:性别 / 年龄段 / 城市;收入档 / 职业 / 有没有车;家里有没有孩子(着装人);会员等级 / 消费档位
  ④ 推法照建议:最像 A 的前 50 人;推 A 买过、他们没买过、还在售的;不同意营销的不推;同一人 90 天内不重复推同一件
     (那两道闸在用的地方加 —— 这里只出名单和理由)

## ⚠️ 数据是造的,画像和买什么在这套数据里无关

造数时职业 / 收入 / 城市是独立随机的(每种职业约 560 人、每档收入约 1350 人),和买了什么没有关系。
所以在这套数据上「画像比重越高越准」**不会成立** —— 那不说明「人物模型越具体越好」是错的,
说明要在真数据上验。人物模型越具体还有一个代价:**越具体,找得到的「像的人」越少**。

## 怎么算(给工程看;卡上不出现公式)

  · 行为向量:浏览动作按 `reco.权重` 加权 + 90 天半衰(不含小程序的「下单」行,订单单独算),
    订单(全渠道)每件按「下单」的权重算;每件商品再乘「逆人数权重」log(总人数 / 有过动作的人数)——
    人人都看的爆款,两个人都看过说明不了他们像(Breese 等 1998 的 inverse user frequency)
  · 行为相似 = 两人行为向量的余弦(0–1)
  · 画像相似 = 各特征得分的平均(只平均两人都填了的特征;「不愿透露」算没填)
  · 总相似 = 行为比重 × 行为相似 + (1 − 行为比重) × 画像相似

口径模块不取当前日期:今由调用方传。
"""
import math

import browse as _B
import reco as _R

行为比重 = 0.7          # ⚠️ 占位:用户拍「量了再定」,离线对比后由用户定(tools/reco_offline_eval.py)
相似人数 = 50           # 拍脑袋(用户 11-28 照建议)
重复推冷却天 = 90       # 同 A-266 的冷却

收入档序 = ["10w 以下", "10w-20w", "20w-30w", "30w-50w", "50w 以上"]
等级序 = ["普通", "银卡", "金卡", "黑金"]
孩子关系 = frozenset({"子", "女"})
特征组 = {
    "性别、年龄段、城市": ("性别", "年龄", "城市"),
    "收入档、职业、有没有车": ("收入", "职业", "有车"),
    "家里有没有孩子": ("有孩子",),
    "会员等级、消费档位": ("等级", "消费档"),
}


# ── 画像 ─────────────────────────────────────────────────────────────────
def 画像(客, 孩子们, 消费档之, 今):
    """客 = customer 行(dict);孩子们 = 有孩子着装人的客户号集合;消费档之 = {客户: 0–4 五分位}。
    车那一列有的填了车牌 —— **只取有 / 没有,不碰车牌**。"""
    def 空(v):
        return v is None or str(v).strip() in ("", "不愿透露")
    年龄 = None
    if not 空(客.get("birthday")):
        try:
            y, m, d = (int(x) for x in str(客["birthday"])[:10].split("-"))
            年龄 = 今.year - y - ((今.month, 今.day) < (m, d))
        except ValueError:
            年龄 = None
    车 = 客.get("car")
    有车 = None if 空(车) else (False if str(车).strip() == "无" else True)
    收入 = None if 空(客.get("income")) else 客["income"]
    return {
        "性别": None if 空(客.get("gender")) else 客["gender"],
        "年龄": 年龄,
        "城市": None if 空(客.get("city")) else 客["city"],
        "省": None if 空(客.get("province")) else 客["province"],
        "收入": 收入 if 收入 in 收入档序 else None,
        "职业": None if 空(客.get("occupation")) else 客["occupation"],
        "有车": 有车,
        "有孩子": str(客["id"]) in 孩子们,
        "等级": 客.get("level") if 客.get("level") in 等级序 else None,
        "消费档": 消费档之.get(str(客["id"])),
    }


def _序近(a, b, 序):
    if a is None or b is None:
        return None
    d = abs(序.index(a) - 序.index(b))
    return 1.0 if d == 0 else (0.5 if d == 1 else 0.0)


def 特征得分(a, b, 用的特征):
    """→ {特征: 0–1 或 None(有一方没填)}"""
    s = {}
    for f in 用的特征:
        if f == "年龄":
            s[f] = None if a["年龄"] is None or b["年龄"] is None else (
                1.0 if abs(a["年龄"] - b["年龄"]) <= 5 else 0.5 if abs(a["年龄"] - b["年龄"]) <= 10 else 0.0)
        elif f == "城市":
            s[f] = None if not a["城市"] or not b["城市"] else (
                1.0 if a["城市"] == b["城市"] else 0.5 if a["省"] and a["省"] == b["省"] else 0.0)
        elif f == "收入":
            s[f] = _序近(a["收入"], b["收入"], 收入档序)
        elif f == "等级":
            s[f] = _序近(a["等级"], b["等级"], 等级序)
        elif f == "消费档":
            s[f] = None if a["消费档"] is None or b["消费档"] is None else (
                1.0 if a["消费档"] == b["消费档"] else 0.5 if abs(a["消费档"] - b["消费档"]) == 1 else 0.0)
        else:
            s[f] = None if a[f] is None or b[f] is None else (1.0 if a[f] == b[f] else 0.0)
    return s


def 画像相似(a, b, 用的特征):
    s = [v for v in 特征得分(a, b, 用的特征).values() if v is not None]
    return sum(s) / len(s) if s else 0.0


def 全部特征():
    return tuple(f for fs in 特征组.values() for f in fs)


# ── 行为 ─────────────────────────────────────────────────────────────────
def 行为向量(浏览行们, 订单行们, 今):
    """→ {客户: {商品: 分}}。订单行要有 customer_id / created / spu。小程序的「下单」行不算(订单单独算,免得算两遍)。"""
    m = _R.交互([r for r in 浏览行们 if r.get("event") != _B.下单], 今)
    for r in 订单行们:
        x = _R.交互([{"customer_id": r["customer_id"], "ts": str(r["created"]), "event": _B.下单, "spu": r["spu"]}], 今)
        for u, d in x.items():
            dd = m.setdefault(u, {})
            for s, w in d.items():
                dd[s] = dd.get(s, 0.0) + w
    return m


def 逆人数加权(矩阵):
    """每件商品乘 log(总人数 / 有过动作的人数),并预先算好每人的模长。→ (加权后矩阵, 模长)"""
    N = len(矩阵) or 1
    df = {}
    for d in 矩阵.values():
        for s in d:
            df[s] = df.get(s, 0) + 1
    idf = {s: math.log(N / n) for s, n in df.items()}
    W = {u: {s: w * idf[s] for s, w in d.items() if idf[s] > 0} for u, d in 矩阵.items()}
    模 = {u: math.sqrt(sum(v * v for v in d.values())) for u, d in W.items()}
    return W, 模


def 行为相似(W, 模, a, b):
    da, db = W.get(a), W.get(b)
    if not da or not db or not 模.get(a) or not 模.get(b):
        return 0.0, []
    if len(da) > len(db):
        da, db = db, da
    共 = [s for s in da if s in db]
    p = sum(da[s] * db[s] for s in 共)
    return p / (模[a] * 模[b]), 共


# ── 找像 A 的人 ─────────────────────────────────────────────────────────
def 找像的人(A, 候选们, W, 模, 画像之, 比重=行为比重, 用的特征=None, k=相似人数):
    """→ [{客户, 相似, 行为相似, 画像相似, 一样的地方}] 按相似降序,不含 A 自己。"""
    用的特征 = tuple(用的特征 or 全部特征())
    pa = 画像之.get(A)
    out = []
    for u in 候选们:
        if u == A:
            continue
        bs, 共 = 行为相似(W, 模, A, u) if 比重 > 0 else (0.0, [])
        ps = 画像相似(pa, 画像之[u], 用的特征) if (比重 < 1 and pa and u in 画像之) else 0.0
        s = 比重 * bs + (1 - 比重) * ps
        if s <= 0:
            continue
        out.append((s, u, bs, ps, 共))
    out.sort(key=lambda x: (-x[0], x[1]))
    res = []
    for s, u, bs, ps, 共 in out[:k]:
        一样 = sorted(共, key=lambda x: -W[A][x] * W[u][x])[:3]
        特 = [f for f, v in 特征得分(pa, 画像之[u], 用的特征).items() if v == 1.0] if pa and u in 画像之 else []
        res.append({"客户": u, "相似": round(s, 4), "行为相似": round(bs, 4), "画像相似": round(ps, 4),
                    "都有过动作的商品": 一样, "画像一样的": 特})
    return res


每人最多推 = 5          # 拍脑袋:A 买过 30 多件时一股脑全推,顾问读不完、客户也不会看

def 推A买过的(A买过, 像的人们, 各人买过, 可推, 最近推过=frozenset(), A的分=None):
    """→ [{客户, 推, 理由}]。推 A 买过、他没买过、还在售、90 天内没推过给他的(最近推过 = {(客户, 商品)})。
    排序按 A 自己对这件的分量(买过 + 反复看的在前;A的分 = A 的行为向量),每人最多 `每人最多推` 件。
    不同意营销的那道闸在用的地方加(要读 consent 表,口径模块不碰库)。"""
    A的分 = A的分 or {}
    序 = sorted(A买过, key=lambda s: (-A的分.get(s, 0.0), s))
    out = []
    for p in 像的人们:
        u = p["客户"]
        推 = [s for s in 序 if s in 可推 and s not in 各人买过.get(u, ()) and (u, s) not in 最近推过][:每人最多推]
        if 推:
            out.append({"客户": u, "推": 推, "相似": p["相似"],
                        "理由": {"都有过动作的商品": p["都有过动作的商品"], "画像一样的": p["画像一样的"]}})
    return out
