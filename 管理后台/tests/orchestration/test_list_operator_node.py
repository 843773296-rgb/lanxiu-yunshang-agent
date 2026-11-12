#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列表操作(11-12,照 Dify「列表操作」;用户 10-26 拍「workflow 直接复刻 dify」)。

## 判据(期望结果是手写的,不由执行器生成)

  ① 先过滤、再排序、再取前几个;第一个 / 最后一个 / 个数对;没调模型
  ② 过滤用条件分支那套操作符:「且」短路(「字段存在 且 金额 > 100」写得出来)、「或」;列表里是一个个数字时比这一项本身
  ③ 排序稳定:一样大的保持原来先后;从大到小也稳定
  ④ 过滤完一个不剩:结果是空列表、第一个 / 最后一个是 null(不是取不到),整条照样成功
  ⑤ 运行时做不下去 → 这一步失败、码对、结束没跑;配了失败出口就走失败出口
     (不是列表 / 某一项没有那个字段 / 数字和文字混着排 / 文字和数字比大小)
  ⑥ 检查配置:缺列表、多一项绑定、空过滤、操作符不认得、比较值类型不对、一元操作符带值、排序方向没选、
     「只要前几个」不是正整数、固定值不是列表 —— 各报自己那一个码(集合相等,不多报)
  ⑦ 运行记录里看得到这一步收到的列表和规则、交出的结果
"""
import copy
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402
import validator as V  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:300] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


出S = {"type": "object", "properties": {"r": {}}, "required": ["r"], "additionalProperties": False}


def 图(规则, 绑=None, 失败出口=False, 取=("结果",)):
    绑 = {"列表": {"source": "input", "pointer": "/单"}} if 绑 is None else 绑
    节 = [
        {"id": "start", "type": "start", "config": {"input_schema": {"type": "object", "properties": {"单": {"type": "array"}}, "required": ["单"]}}},
        {"id": "lo", "type": "list_operator", "config": {"bindings": 绑, **规则, **({"failure_policy": "branch"} if 失败出口 else {})}},
        {"id": "end", "type": "end", "config": {"output_schema": 出S, "bindings": {"r": {"source": "node", "node_id": "lo", "pointer": "/" + 取[0]}}}}]
    边 = [{"source": "start", "target": "lo", "port": "success"}, {"source": "lo", "target": "end", "port": "success"}]
    if 失败出口:
        节.append({"id": "end2", "type": "end", "config": {"output_schema": 出S, "bindings": {"r": {"source": "constant", "value": "走了失败出口"}}}})
        边.append({"source": "lo", "target": "end2", "port": "error"})
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出S, "nodes": 节, "edges": 边}


def 跑(g, 单):
    return RN.跑一张图(CP.编译(g, 依赖存在=lambda 种类, i: True), {"单": 单}, 适配器={}, run_id="r")


码 = lambda g: sorted(p["code"] for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断)
步 = lambda r: {s["node_id"]: s for s in r["步骤"]}

单子 = [{"号": "A", "金额": 300, "店": "杭州"}, {"号": "B", "金额": 80, "店": "苏州"},
      {"号": "C", "金额": 500, "店": "杭州"}, {"号": "D", "金额": 300, "店": "苏州"}, {"号": "E", "金额": 120, "店": "杭州"}]

print("▸ ① 过滤 → 排序 → 取前几个")
规 = {"filter": {"conditions": [{"field": "金额", "op": "gte", "value": 100}]},
     "sort": {"field": "金额", "order": "desc"}, "limit": 3}
r = 跑(图(规), 单子)
lo = 步(r)["lo"]
ck("金额 ≥ 100、从大到小、前 3 个 → C A D(A 和 D 一样大,保持原来 A 在前)",
   r["执行状态"] == "succeeded" and [x["号"] for x in r["输出"]["r"]] == ["C", "A", "D"], 1, (r["执行状态"], r["输出"]))
出 = lo.get("output") or {}
ck("第一个 C、最后一个 D、个数 3", (出.get("第一个") or {}).get("号") == "C" and (出.get("最后一个") or {}).get("号") == "D"
   and 出.get("个数") == 3, 1, lo.get("output"))
ck("没调模型", r["用量"]["模型调用"] == 0, 1, r["用量"])
ck("⑦ 运行记录:收到的列表(5 项)和规则都在 input 里,结果在 output 里",
   len((lo.get("input") or {}).get("列表") or []) == 5 and (lo.get("input") or {}).get("规则") == 规
   and (lo.get("output") or {}).get("结果") == r["输出"]["r"], 1, lo.get("input"))
ck("给进来的列表没被改(执行器不动上游的值)", [x["号"] for x in 单子] == ["A", "B", "C", "D", "E"], 1)

print("▸ ② 过滤:且短路 / 或 / 比这一项本身")
混 = [{"号": "A", "金额": 300}, {"号": "X"}, {"号": "C", "金额": 50}]
规 = {"filter": {"conditions": [{"field": "金额", "op": "exists"}, {"field": "金额", "op": "gt", "value": 100}], "logic": "and"}}
r = 跑(图(规), 混)
ck("「字段存在 且 金额 > 100」:没有金额的 X 被第一条筛掉,不报缺字段", r["执行状态"] == "succeeded"
   and [x["号"] for x in r["输出"]["r"]] == ["A"], 1, (r["执行状态"], r["输出"], 步(r)["lo"].get("error_code")))
规 = {"filter": {"conditions": [{"field": "店", "op": "equals", "value": "苏州"}, {"field": "金额", "op": "gt", "value": 400}], "logic": "or"}}
r = 跑(图(规), 单子)
ck("「店 = 苏州 或 金额 > 400」→ B C D", [x["号"] for x in r["输出"]["r"]] == ["B", "C", "D"], 1, r["输出"])
r = 跑(图({"filter": {"conditions": [{"op": "lt", "value": 10}]}, "sort": {"order": "asc"}}), [12, 3, 9, 3.5, 40])
ck("列表里是一个个数字:不写「看哪一项」= 比这一项本身 → [3, 3.5, 9]", r["输出"]["r"] == [3, 3.5, 9], 1, r["输出"])
r = 跑(图({"filter": {"conditions": [{"op": "contains", "value": "马面"}]}}), ["马面裙", "袄裙", "织金马面"])
ck("文字列表按「包含」过滤 → 两条马面", r["输出"]["r"] == ["马面裙", "织金马面"], 1, r["输出"])

print("▸ ③ 排序稳定")
r = 跑(图({"sort": {"field": "金额", "order": "asc"}}), 单子)
ck("从小到大:B E A D C(A、D 一样大保持原顺序)", [x["号"] for x in r["输出"]["r"]] == ["B", "E", "A", "D", "C"], 1, r["输出"])
r = 跑(图({"sort": {"field": "号", "order": "desc"}}), 单子)
ck("按文字从大到小:E D C B A", [x["号"] for x in r["输出"]["r"]] == ["E", "D", "C", "B", "A"], 1, r["输出"])

print("▸ ④ 一个不剩")
r = 跑(图({"filter": {"conditions": [{"field": "金额", "op": "gt", "value": 10000}]}}, 取=("第一个",)), 单子)
lo = 步(r)["lo"]
ck("结果空列表、个数 0、第一个 / 最后一个是 null,整条成功(结束拿到的是 null 不是取不到)",
   r["执行状态"] == "succeeded" and lo.get("output") == {"结果": [], "个数": 0, "第一个": None, "最后一个": None}
   and r["输出"] == {"r": None}, 1, (r["执行状态"], lo.get("output"), r["输出"]))
r = 跑(图({"limit": 2}, 取=("最后一个",)), 单子)
ck("只取前几个、不过滤不排序:最后一个是第 2 项 B", r["输出"]["r"]["号"] == "B", 1, r["输出"])

print("▸ ⑤ 运行时做不下去")
for 名, 规, 单, 期 in [
        ("给进来的不是列表", {}, {"号": "A"}, "LIST_NOT_ARRAY"),
        ("某一项没有过滤的那个字段", {"filter": {"conditions": [{"field": "金额", "op": "gt", "value": 1}]}}, 混, "LIST_FIELD_MISSING"),
        ("数字和文字混着排", {"sort": {"order": "asc"}}, [3, "三", 1], "LIST_SORT_MIXED"),
        ("排序那一项有的没有", {"sort": {"field": "金额", "order": "asc"}}, 混, "LIST_SORT_KEY_MISSING"),
        ("文字和数字比大小(不悄悄转成数)", {"filter": {"conditions": [{"field": "金额", "op": "gt", "value": 1}]}},
         [{"金额": "300"}], "LIST_FILTER_TYPE"),
        ("看某一项,但列表里不是记录", {"filter": {"conditions": [{"field": "金额", "op": "gt", "value": 1}]}}, [1, 2], "LIST_ITEM_NOT_OBJECT"),
        ("是 / 否不能排", {"sort": {"order": "asc"}}, [True, False], "LIST_SORT_MIXED")]:
    r = 跑(图(规), 单)
    s = 步(r)
    ck(f"{名} → {期}、整条失败、结束没跑", r["执行状态"] == "failed" and s["lo"].get("error_code") == 期
       and s["end"]["status"] == "skipped", 1, (r["执行状态"], s["lo"].get("error_code"), s["lo"].get("error_detail")))
r = 跑(图({"sort": {"order": "asc"}}, 失败出口=True), [3, "三"])
s = 步(r)
ck("配了失败出口:走失败出口那个结束,原来那个结束没跑", s["lo"]["status"] == "failed" and s["end2"]["status"] == "succeeded"
   and s["end"]["status"] == "skipped" and r["输出"] == {"r": "走了失败出口"}, 1, {k: v["status"] for k, v in s.items()})
ck("失败那一步的运行记录里也有收到的列表", s["lo"].get("input", {}).get("列表") == [3, "三"], 1, s["lo"].get("input"))
g = 图({}, 绑={"列表": {"source": "input", "pointer": "/没有这项"}})
r = 跑(g, 单子)
ck("列表的来源取不到 → LIST_VALUE_MISSING", 步(r)["lo"].get("error_code") == "LIST_VALUE_MISSING", 1, 步(r)["lo"])

print("▸ ⑥ 检查配置")
ck("正常那张图:没有阻断", 码(图({"filter": {"conditions": [{"field": "金额", "op": "gt", "value": 1}]}, "sort": {"field": "金额", "order": "asc"}, "limit": 2})) == [], 1)
for 名, g, 期 in [
        ("「用到的数据」整个空着 → 必填缺失", 图({}, 绑={}), ["NODE_MISSING_CONFIG"]),
        ("绑定里没有「列表」只有别的", 图({}, 绑={"单": {"source": "input", "pointer": "/单"}}), ["LIST_EXTRA_BINDING", "LIST_NO_INPUT"]),
        ("多绑了一项", 图({}, 绑={"列表": {"source": "input", "pointer": "/单"}, "x": {"source": "input", "pointer": "/单"}}), ["LIST_EXTRA_BINDING"]),
        ("固定值不是列表", 图({}, 绑={"列表": {"source": "constant", "value": "abc"}}), ["LIST_NOT_ARRAY"]),
        ("开了过滤一条条件都没有", 图({"filter": {"conditions": []}}), ["LIST_FILTER_EMPTY"]),
        ("操作符不认得", 图({"filter": {"conditions": [{"field": "金额", "op": "大约等于", "value": 1}]}}), ["LIST_FILTER_OP"]),
        ("「大于」填了文字", 图({"filter": {"conditions": [{"field": "金额", "op": "gt", "value": "100"}]}}), ["LIST_FILTER_VALUE"]),
        ("「大于」没填值", 图({"filter": {"conditions": [{"field": "金额", "op": "gt"}]}}), ["LIST_FILTER_VALUE"]),
        ("「字段存在」带了值", 图({"filter": {"conditions": [{"field": "金额", "op": "exists", "value": 1}]}}), ["LIST_FILTER_VALUE"]),
        ("「长度等于」填了小数", 图({"filter": {"conditions": [{"field": "件", "op": "length_eq", "value": 1.5}]}}), ["LIST_FILTER_VALUE"]),
        ("「早于」填了不是日期的字", 图({"filter": {"conditions": [{"field": "日", "op": "date_before", "value": "下周"}]}}), ["LIST_FILTER_VALUE"]),
        ("「看哪一项」是空串", 图({"filter": {"conditions": [{"field": " ", "op": "exists"}]}}), ["LIST_FILTER_FIELD"]),
        ("过滤用了「且 / 或」以外的连法", 图({"filter": {"conditions": [{"op": "exists"}], "logic": "xor"}}), ["LIST_FILTER_LOGIC"]),
        ("排序方向没选", 图({"sort": {"field": "金额"}}), ["LIST_SORT_ORDER"]),
        ("「只要前几个」填 0", 图({"limit": 0}), ["LIST_LIMIT"]),
        ("「只要前几个」填 是", 图({"limit": True}), ["LIST_LIMIT"]),
        ("填了不适用的超时(这一步不调外部)", 图({"timeout_seconds": 5}), ["NODE_INAPPLICABLE_FIELD"]),
        ("配置里带一个没登记的字段", 图({"expression": "item.金额 > 100"}), ["NODE_UNKNOWN_CONFIG"])]:
    ck(f"{名} → {期}", 码(g) == 期, 1, 码(g))
g = 图({}, 绑={"列表": {"source": "node", "node_id": "end", "pointer": "/x"}})
ck("列表取的是后面那一步的结果 → 支配关系那条照样拦(BIND_MAYBE_MISSING)", "BIND_MAYBE_MISSING" in 码(g), 1, 码(g))

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
