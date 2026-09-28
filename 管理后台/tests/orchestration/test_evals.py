#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测判断的纯逻辑 —— **零 IO,跑在 CI 里**。

## 这一组守住的四件,每一件的坏法都不报错

    ① **防泄漏**:同一组样本不许跨分集 —— 泄漏之后分数虚高,而每一步看起来都正常
    ② **可比性**:换了题或换了判据的两轮不可比 —— 而两个数并排时读的人会算差值
    ③ **「没打分」不参与平均** —— 当 0 平均进去会让只评了一半的实验分数腰斩
    ④ **被取代的评分不算** —— 人工改判是新增一条,原始结果永远还在
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))

import evals as E

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


print("▸ ① 防泄漏:同一组不许跨分集")
干净 = [dict(id="a", group_id="g1", split="独立测试"),
      dict(id="b", group_id="g1", split="独立测试"),
      dict(id="c", group_id="g2", split="训练")]
ck("同组同集 → 不报", E.查分集泄漏(干净) == [], E.查分集泄漏(干净))
泄 = [dict(x) for x in 干净]
泄[1]["split"] = "训练"
ck("**改写版挪去训练集 → 抓到**(这是分数虚高的典型来源)",
   E.查分集泄漏(泄) == ["g1"], E.查分集泄漏(泄))
无组 = [dict(id="a", group_id=None, split="训练"),
      dict(id="b", group_id=None, split="独立测试"),
      dict(id="c", group_id="", split="训练")]
ck("**没标组的各算一组,不是都算同一组** —— "
   "都算一组的话一批没标组的样本会被判成全冲突(假警报)",
   E.查分集泄漏(无组) == [], E.查分集泄漏(无组))

print("▸ ② 可以冻结吗")
ck("空数据集 → 拦住", bool(E.可以冻结吗([])), E.可以冻结吗([])[:1])
ck("理由说清「0 题全对和没测分不出来」",
   "分不出" in E.可以冻结吗([])[0], E.可以冻结吗([])[0][:70])
ck("干净的一批 → 可以冻", E.可以冻结吗(干净) == [], E.可以冻结吗(干净))
没集 = [dict(id="a", group_id="g", split=None)]
ck("有样本没分集 → 拦住(**冻结时定,之后不许重分**)",
   any("没有分集" in x for x in E.可以冻结吗(没集)), E.可以冻结吗(没集))
怪集 = [dict(id="a", group_id="g", split="随便编的")]
ck("分集认不出 → 拦住", any("认不出" in x for x in E.可以冻结吗(怪集)))
ck("泄漏的一批 → 拦住,而且理由点名「分数会虚高」",
   any("虚高" in x for x in E.可以冻结吗(泄)), E.可以冻结吗(泄))

print("▸ ③ 可比吗:四个东西要同时在场")
基 = {"dataset_version_id": "dv1", "scorer_version": "s1"}
ck("同题同判据 → 可比", E.可比吗(基, dict(基))[0])
ck("换了题 → 不可比",
   not E.可比吗(基, {**基, "dataset_version_id": "dv2"})[0])
ck("理由说「跑的不是同一套题」",
   "同一套题" in E.可比吗(基, {**基, "dataset_version_id": "dv2"})[1])
ck("换了判据 → 不可比", not E.可比吗(基, {**基, "scorer_version": "s2"})[0])
ck("理由说「差别可能全来自评分方式」",
   "评分方式" in E.可比吗(基, {**基, "scorer_version": "s2"})[1])
for 缺, 说 in (("dataset_version_id", "没有数据集版本"), ("scorer_version", "没有判据版本")):
    少 = {k: v for k, v in 基.items() if k != 缺}
    ck(f"缺 {缺} → 不可比", not E.可比吗(少, 基)[0], E.可比吗(少, 基)[1][:60])
ck("缺哪个由谁缺说清(甲/乙分得开)", "甲" in E.可比吗({}, 基)[1])

print("▸ ④ 汇总分数:**「没打分」不参与平均**")
分 = [{"dimension": "准确", "value": 1.0, "value_known": True},
     {"dimension": "准确", "value": 1.0, "value_known": True},
     {"dimension": "准确", "value": None, "value_known": False}]
r = E.汇总分数(分)["准确"]
ck("均分 = 1.0(不是 0.667)", r["均分"] == 1.0, r)
ck("报了「没打分几条」", r["没打分几条"] == 1)
ck("**当 0 平均进去会是 0.667** —— 看起来像退步 33%,而真相是那条没测",
   round(2.0 / 3, 3) == 0.667)
全没打 = E.汇总分数([{"dimension": "准确", "value": None, "value_known": False}])["准确"]
ck("一条都没打 → 均分是 **None 不是 0**(0 会被读成「全错」)",
   全没打["均分"] is None and 全没打["均分是未知吗"], 全没打)
ck("没标维度的也有归宿(不静默丢)",
   "(没标维度)" in E.汇总分数([{"value": 1, "value_known": True}]))

print("▸ ⑤ 有效分数:被取代的不算")
分2 = [{"id": "s1", "value": 0.2}, {"id": "s2", "value": 0.9,
                                  "supersedes_score_id": "s1"}]
ck("改判后只剩新那条", [x["id"] for x in E.有效分数(分2)] == ["s2"])
ck("**原始那条还在列表里**(只是不算) —— 「原始结果永远还在」",
   any(x["id"] == "s1" for x in 分2))
ck("没有改判时全都算", len(E.有效分数([{"id": "a"}, {"id": "b"}])) == 2)
链 = [{"id": "s1"}, {"id": "s2", "supersedes_score_id": "s1"},
     {"id": "s3", "supersedes_score_id": "s2"}]
ck("改判两次 → 只剩最后一条", [x["id"] for x in E.有效分数(链)] == ["s3"],
   [x["id"] for x in E.有效分数(链)])
# ⚠️ 这里原来有一条 `... or True` 的断言 —— **那等于没断言,它永远为真**,
# 而它混在 29 条绿里谁也看不出来。删掉比留着强:留着会让人以为这件事被看住了。
#
# 改成真的能咬的:**打乱顺序,结果必须不变**。
# 靠时间戳/顺序取最后一条的实现,在这里会给出不同的答案。
乱 = [{"id": "s3", "supersedes_score_id": "s2"}, {"id": "s1"},
     {"id": "s2", "supersedes_score_id": "s1"}]
ck("**打乱输入顺序,结果不变** —— 靠顺序取「最后一条」的实现在这里会变",
   [x["id"] for x in E.有效分数(乱)] == ["s3"], [x["id"] for x in E.有效分数(乱)])
倒 = list(reversed(链))
ck("倒序输入也一样", [x["id"] for x in E.有效分数(倒)] == ["s3"],
   [x["id"] for x in E.有效分数(倒)])

print("▸ ⑥ 常量和契约对齐")
ck("判据来源三档和契约一致",
   set(E.判据来源) == {"确定性规则", "模型评分", "人工"}, E.判据来源)
ck("分集三档和契约一致", set(E.分集) == {"训练", "验证", "独立测试"}, E.分集)

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
