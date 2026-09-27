#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编排 DSL 语义测试 —— **真值来自一张手写的表,不是从实现跑出来的**。

## 这个测试和 tools/spec_coverage.py 分工不同

`spec_coverage` 问的是**「规格点名的东西登记了没有」**:节点齐不齐、端点齐不齐、
状态机齐不齐。它顺手钉了几条关键语义,但那是抽查。

这里问的是**「语义到底对不对」**,而且判据在一个**独立的夹具文件**里
(`fixtures/orchestration/条件真值表.json`)—— 规格附录 C.3 对图夹具的要求是
「真值来源:**独立人工预期,不由编译器生成**」。

> 用被测实现算出来的期望值,实现错了期望值跟着一起错 —— 那种测试永远是绿的。

夹具是手写的 JSON。**它写错了也会红** —— 而那正是它有用的地方:
红了之后要人去判「是实现错了还是我对语义的理解错了」,
而这个判断本身就是规格 §6.3 那一节该被读第二遍的时候。

## 为什么条件语义值得一整张真值表

规格 §3.3:「`0`、空字符串、`null`、字段不存在**必须区分**,不能统一用「空」
模糊处理」。这四个值在几乎每种语言里都有至少两个会被压成同一类:
Python 里 `0 == False`、`isinstance(True, int)`、`not ""` 和 `not []` 都真。
**这些不是边角情况,它们是条件分支最常见的输入。**
一条把「用户没填这个字段」和「用户填了 0」当成同一件事的条件,
会在运行时静默走错分支,而画布上什么都看不出来。
"""
import json
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
import dsl as DS  # noqa: E402

夹具路径 = os.path.join(根, "fixtures", "orchestration", "条件真值表.json")

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:160] if 补 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        # 空集合上所有性质都成立 —— 「一个都没扫到」和「全都通过」在输出上一样
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        挂.append(名 + "(样本量 0)")


def 还原(v):
    """把夹具里的标记还原成真正的值。JSON 表达不了「字段不存在」。"""
    if isinstance(v, dict) and set(v) == {"$"}:
        if v["$"] == "缺失":
            return DS.缺失
        raise ValueError(f"夹具里有个认不出的标记:{v} —— **不猜**")
    return v


def 跑一条(行):
    """返回 (实际, 期望) 两个可比的东西。异常按类名归一。"""
    左 = 还原(行["左"])
    有右 = "右" in 行
    try:
        实际 = DS.判(行["操作符"], 左, *( [还原(行["右"])] if 有右 else [] ))
    except DS.变量缺失:
        实际 = "变量缺失"
    except DS.类型不匹配:
        实际 = "类型不匹配"
    return 实际, 行["期望"]


print("▸ 条件语义:**判据是一张手写的真值表**(fixtures/orchestration/条件真值表.json)")
表 = json.load(open(夹具路径, encoding="utf-8"))
总数 = 0
for 组, 行们 in 表.items():
    if not isinstance(行们, list) or not 行们 or not isinstance(行们[0], dict):
        continue                      # 「说明」那几段
    坏 = []
    for 行 in 行们:
        实际, 期望 = 跑一条(行)
        总数 += 1
        if 实际 != 期望:
            左 = 行["左"]
            坏.append(f"{行['操作符']}({左!r}"
                      f"{', ' + repr(行['右']) if '右' in 行 else ''}) "
                      f"→ {实际!r},表上写的是 {期望!r}"
                      f"{'  ← ' + 行['为什么'] if 行.get('为什么') else ''}")
    ck(f"「{组}」和手写真值表一致", not 坏, len(行们), 坏[:2])

# 夹具本身也要被检查:一张写着 0 条的表会让上面每一组都「通过」
ck("真值表**不是空的**,而且每组都有反例(全是 true 的表证明不了区分)",
   总数 >= 50 and any(
       行.get("期望") in ("类型不匹配", "变量缺失")
       for 组 in 表.values() if isinstance(组, list)
       for 行 in 组 if isinstance(行, dict)), 总数, f"{总数} 条")

# ── 逻辑哈希:夹具驱动的两个方向 ──────────────────────────────────────
print("\n▸ 逻辑哈希:挪位置不变 / 改语义必变(附录 A-9)")
_基 = {
    "definition_schema_version": "1", "kind": "workflow", "name": "文章总结",
    "nodes": [
        {"id": "start", "type": "start", "config": {}, "layout": {"x": 0, "y": 0}},
        {"id": "summarize", "type": "llm", "name": "总结",
         "layout": {"x": 240, "y": 0},
         "config": {"prompt_version_id": "demo-summary-prompt-v1",
                    "bindings": {"article": {"source": "input", "pointer": "/article"}},
                    "retry_policy": {"max_retries": 0}}},
        {"id": "finish", "type": "end", "config": {
            "bindings": {"summary": {"source": "node", "node_id": "summarize",
                                     "pointer": "/summary"}}}},
    ],
    "edges": [{"source": "start", "target": "summarize", "port": "success"},
              {"source": "summarize", "target": "finish", "port": "success"}],
}


def 变(改):
    import copy
    d = copy.deepcopy(_基)
    改(d)
    return DS.逻辑哈希(d)


基哈希 = DS.逻辑哈希(_基)


def _挪(d):
    for n in d["nodes"]:
        n["layout"] = {"x": 999, "y": -7}
    d["nodes"].reverse()
    d["edges"].reverse()


不变的改动 = [
    ("自动布局挪了所有节点 + 换了顺序", _挪),
    ("改节点显示名", lambda d: d["nodes"][1].__setitem__("name", "换个名字")),
    ("改工作流的名字和说明", lambda d: (d.__setitem__("name", "别的名字"),
                                    d.__setitem__("description", "补了段说明"))),
    ("改边上的显示文字", lambda d: d["edges"][0].__setitem__("label", "走这条")),
]
坏1 = [名 for 名, f in 不变的改动 if 变(f) != 基哈希]
ck("**这些改动不该改哈希**(否则整理一次画布就像改了执行逻辑,人会开始忽略「版本变了」)",
   not 坏1, len(不变的改动), 坏1)

变了的改动 = [
    ("换 Prompt 版本", lambda d: d["nodes"][1]["config"].__setitem__(
        "prompt_version_id", "demo-summary-prompt-v2")),
    ("改重试次数", lambda d: d["nodes"][1]["config"]["retry_policy"].__setitem__(
        "max_retries", 3)),
    ("改输入绑定的 pointer", lambda d: d["nodes"][1]["config"]["bindings"]["article"]
        .__setitem__("pointer", "/body")),
    ("加一个节点", lambda d: d["nodes"].append(
        {"id": "extra", "type": "end", "config": {}})),
    ("改一条边的目标", lambda d: d["edges"][0].__setitem__("target", "finish")),
    ("改节点 id", lambda d: d["nodes"][1].__setitem__("id", "summarize2")),
]
坏2 = [名 for 名, f in 变了的改动 if 变(f) == 基哈希]
ck("**这些改动一定要改哈希**(否则发布清单指向的那一版和实际跑的不是一份)",
   not 坏2, len(变了的改动), 坏2)

# 一个反向对照:哈希函数不是「什么都变」—— 同一份定义算两次要一样
ck("同一份定义算两次结果一样(对照:不是随机数)", DS.逻辑哈希(_基) == 基哈希, 1)
# 键序无关:JSON 里键的先后不是内容
ck("JSON 键序不影响哈希",
   DS.逻辑哈希({"kind": "workflow", "nodes": _基["nodes"], "edges": _基["edges"],
              "definition_schema_version": "1", "name": "文章总结"}) == 基哈希, 1)

# ── 节点登记:未实现的不许被当成可用 ────────────────────────────────
print("\n▸ 节点登记:**未实现的要标出来,不摆空按钮**(§6.1)")
可用 = {n["中文"] for n in DS.可用节点()}
未实现 = {n["中文"] for n in DS.节点表 if n["实现"] == DS.未实现}
ck("可用节点和未实现节点没有交集(一个节点不能同时是两种状态)",
   not (可用 & 未实现), len(DS.节点表), sorted(可用 & 未实现))
ck("**并行/循环/列表迭代/子工作流标着未实现**(规格 §6.1 说首版做另外十个)",
   {"并行与汇总", "有界循环", "列表迭代", "子工作流"} <= 未实现,
   len(未实现), sorted(未实现))
# 每个未实现的节点都得有说明 —— 一个只写「未实现」的占位没告诉人任何事
无说明 = [n["中文"] for n in DS.节点表 if n["实现"] == DS.未实现 and not n["说明"]]
ck("未实现的节点也写清了它该干什么(否则轮到实现它时要重新读一遍规格)",
   not 无说明, len(未实现), 无说明)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
