#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测的判断那一半 —— **纯逻辑,零 IO**(所以每条都能单测)。

## 「回归验收」不是「跑一遍看分数」

规格 §18 把它拆成四个必须同时在场的东西:

    候选 + 基线          没有基线的分数**不能当结论**
    冻结的数据版本        样本还能改的话,两轮跑的不是同一套题
    记录在案的判据版本    换了判据的两轮**不可比**

缺任何一个,跑出来的数**看起来仍然是个分数** —— 这是这一组的核心危险:
不可比的两个数放在一起,读的人会当成「涨了 / 跌了」。

## ⚠️ 防泄漏:`group_id` 不许跨分集

同一组的样本不许同时出现在训练集和测试集(改写、同源、同客户都算一组)。
泄漏之后分数会**虚高**,而每一步看起来都正常:
一道题的改写版在训练集、原版在测试集,模型当然答得对。

> 这是评测里最容易出错、而且**错了不报错**的地方。

## ⚠️ `value_known` 区分「没打分」和「打了 0 分」

用 0 表示没测过,会让人以为测过了。
(同一条规矩在 `usage_ledger.amount_known` 上也有 —— 未知不是 0。)
"""

判据来源 = ("确定性规则", "模型评分", "人工")
分集 = ("训练", "验证", "独立测试")


class 不可比(Exception):
    """两轮评测不能放在一起比。**当场抛,不给一个「大概能比」的结论。**"""


class 会泄漏(Exception):
    """分集划分让同一组样本跨了集。**当场抛,不静默修正。**

    静默修正的坏法:它会悄悄改变数据集的构成,
    而下一轮和上一轮就**不是同一套题**了 —— 又回到不可比。
    """


def 查分集泄漏(样本们):
    """返回跨了分集的 group_id 清单(空 = 干净)。

    `样本们` 是 [{id, group_id, split}]。
    ⚠️ **`group_id` 为空的每条各算一组** —— 不是「都算同一组」。
    都算一组的话,一批没标组的样本会被判成全部冲突,而那是假警报;
    各算一组则是「没有声明关系就当没关系」,那是这个字段的本意。
    """
    组到集 = {}
    for s in 样本们:
        g = s.get("group_id")
        if not g:
            continue                      # 没标组 = 没声明关系
        组到集.setdefault(g, set()).add(s.get("split"))
    return sorted(g for g, 集 in 组到集.items() if len(集) > 1)


def 可以冻结吗(样本们):
    """能不能把这批样本冻成一个数据集版本。返回问题清单(空 = 可以)。"""
    问 = []
    if not 样本们:
        问.append("一个样本都没有 —— **空数据集冻出来的版本,"
                  "跑出来的分数是「0 题全对」还是「没测」分不出来**")
        return 问
    坏集 = sorted({s.get("split") for s in 样本们} - set(分集) - {None})
    if 坏集:
        问.append(f"有样本的分集认不出:{坏集} —— 只收 {list(分集)}")
    没分集 = sum(1 for s in 样本们 if not s.get("split"))
    if 没分集:
        问.append(f"{没分集} 条样本没有分集 —— **冻结时定,之后不许重分**(§18),"
                  f"所以现在必须都有")
    漏 = 查分集泄漏(样本们)
    if 漏:
        问.append(f"**分集泄漏**:{漏[:5]} 这些 group_id 跨了分集。"
                  f"同一组的样本(改写 / 同源 / 同客户)不许分到不同集 —— "
                  f"泄漏之后分数会虚高,**而每一步看起来都正常**")
    return 问


def 可比吗(甲, 乙):
    """两轮评测能不能放在一起比。返回 (能不能, 为什么)。

    `甲`/`乙` 是 {dataset_version_id, scorer_version}。
    """
    for 名, e in (("甲", 甲), ("乙", 乙)):
        if not (e or {}).get("dataset_version_id"):
            return False, f"{名}没有数据集版本 —— 样本还能改的话,两轮跑的不是同一套题"
        if not (e or {}).get("scorer_version"):
            return False, f"{名}没有判据版本 —— **换了判据的两轮不可比**"
    if 甲["dataset_version_id"] != 乙["dataset_version_id"]:
        return False, (f"两轮用的数据集版本不同"
                       f"({甲['dataset_version_id']} vs {乙['dataset_version_id']})—— "
                       f"**跑的不是同一套题**,分数的差别可能全来自题目")
    if 甲["scorer_version"] != 乙["scorer_version"]:
        return False, (f"两轮用的判据版本不同"
                       f"({甲['scorer_version']} vs {乙['scorer_version']})—— "
                       f"**换了判据的两轮不可比**,差别可能全来自评分方式")
    return True, "同一套题、同一份判据"


def 汇总分数(分数们):
    """把一堆评分折成一个结论。**「没打分」不参与平均。**

    `分数们` 是 [{dimension, value, value_known}]。
    返回 {维度: {已知几条, 没打分几条, 均分}} —— 均分在一条都没打时是 **None**。

    ⚠️ 把「没打分」当 0 平均进去,会让一个只评了一半的实验
    看起来分数腰斩 —— 而真相是另一半没测。
    """
    出 = {}
    for s in 分数们:
        d = 出.setdefault(s.get("dimension") or "(没标维度)",
                          {"已知几条": 0, "没打分几条": 0, "_和": 0.0})
        if s.get("value_known") and s.get("value") is not None:
            d["已知几条"] += 1
            d["_和"] += float(s["value"])
        else:
            d["没打分几条"] += 1
    for k, d in 出.items():
        # **一条都没打时是 None,不是 0** —— 0 会被读成「全错」
        d["均分"] = (round(d["_和"] / d["已知几条"], 4) if d["已知几条"] else None)
        d["均分是未知吗"] = (d["已知几条"] == 0)
        d.pop("_和")
    return 出


def 有效分数(分数们):
    """一条题的**当前分数**:被 supersedes 指过的那些不算。

    人工改判是**新增一条并指向被取代的那条**,不是改旧那条 ——
    所以原始结果永远还在,而「现在算几分」要把被取代的排掉。

    ⚠️ 不看 `at` 排序取最后一条:两条时间戳相同(同一秒里两次改判)时
    「最后一条」是不确定的,而 supersedes 是**显式声明的**。
    """
    被取代 = {s.get("supersedes_score_id") for s in 分数们
             if s.get("supersedes_score_id")}
    return [s for s in 分数们 if s.get("id") not in 被取代]
