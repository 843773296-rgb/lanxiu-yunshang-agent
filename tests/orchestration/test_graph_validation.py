#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图校验测试 —— **每张图的期望阻断码是手写的,判据是集合相等**。

## 为什么判据是「集合相等」而不是「至少报了这一条」

「至少报了一条」放过的是**多报**:一个把合法图也拦住的校验器,在这种判据下
每一条都是绿的。而多报的代价不比少报小 —— 人会去修一个没坏的地方,
改完还是红,然后开始怀疑校验器,最后学会忽略它。

> **一个会误报的校验器,会训练人跳过校验。**

所以夹具里前两个 case 是**正向对照**(期望阻断 = 空):没有它们,
下面每一条「非法图被拦住」都可能只是证明了「这个校验器什么都拦」。

## 阻断和警告分开比

`CHECK_SKIPPED` 这类警告不进比较 —— 它说的是「这一类我没查」,
是**诚实**而不是问题。但它必须出现:附录 C.4「跳过的检查不能写成通过」。
"""
import json
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
import validator as V  # noqa: E402

夹具路径 = os.path.join(根, "fixtures", "orchestration", "图校验夹具.json")
过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:200] if 补 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        挂.append(名 + "(样本量 0)")


文 = json.load(open(夹具路径, encoding="utf-8"))
夹具 = 文["夹具"]

print("▸ 图校验:**期望阻断码手写在夹具里**(fixtures/orchestration/图校验夹具.json)")
坏 = []
for 名, c in 夹具.items():
    问题 = V.校验(c["图"])
    实际 = sorted({p["code"] for p in 问题 if p["级别"] == V.阻断})
    期望 = sorted(set(c["期望阻断"]))
    if 实际 != 期望:
        多 = sorted(set(实际) - set(期望))
        少 = sorted(set(期望) - set(实际))
        坏.append(f"{名}:多报 {多} / 漏报 {少}"
                  f"  ← {c['为什么'][:60]}")
ck("每张图报出来的阻断码和手写的期望**集合相等**(多报也算错)",
   not 坏, len(夹具), 坏[:3])

合法 = [名 for 名, c in 夹具.items() if not c["期望阻断"]]
ck("夹具里有正向对照(全是非法图的话,只能证明『校验器什么都拦』)",
   len(合法) >= 2, len(合法), 合法)
ck("夹具里每个 case 都写了**为什么**(一条说不出理由的用例,改坏了也没人拦)",
   all((c.get("为什么") or "").strip() for c in 夹具.values()), len(夹具),
   [名 for 名, c in 夹具.items() if not (c.get("为什么") or "").strip()])

# ── 报告结构:规格 §17.1 要求带 node_id / field_path / 阻断级别 ──────
print("\n▸ 报告结构(§17.1:报告要能点着定位到节点和字段)")
问题们 = V.校验(夹具["非法_跨分支直接取值"]["图"])
那条 = [p for p in 问题们 if p["code"] == "BIND_MAYBE_MISSING"]
ck("每条阻断都带 node_id(点击能定位到画布上那个节点)",
   all(p["node_id"] for p in 问题们 if p["级别"] == V.阻断),
   sum(1 for p in 问题们 if p["级别"] == V.阻断),
   [p["code"] for p in 问题们 if p["级别"] == V.阻断 and not p["node_id"]])
ck("变量类的问题带 field_path(定位到右侧面板那一行,不是整个节点)",
   那条 and 那条[0]["field_path"] == "config.bindings.t", 1,
   那条[0]["field_path"] if 那条 else "没报这条")
ck("**每条都写了「怎么改」**(建议必填,和 contract/errors.py 同一条规矩)",
   all((p["建议"] or "").strip() for p in 问题们), len(问题们))
ck("那条跨分支报错的建议里点名了**分支汇合**这个解法(§7.2 说的正是它)",
   那条 and "汇合" in 那条[0]["建议"], 1)
r = V.报告(问题们)
ck("报告信封齐(通过 / 阻断数 / 警告数 / 问题 / 说明)",
   set(r) == {"通过", "阻断数", "警告数", "问题", "说明"} and r["通过"] is False, 5)
ck("报告里写明「服务端校验过了也只说明定义合法」(附录 A-1 的局限)",
   "定义" in r["说明"] and ("模型" in r["说明"] or "外部" in r["说明"]), 1)

# ── 没给依赖查询能力时,**要说自己跳过了** ─────────────────────────
print("\n▸ 跳过的检查要说出来(附录 C.4:跳过不能写成通过)")
干净 = V.校验(夹具["合法_最小链"]["图"])
ck("没给查询能力 → 报一条「这一类没查」的警告,而不是安静放过",
   any(p["code"] == "CHECK_SKIPPED" for p in 干净), len(干净),
   [p["code"] for p in 干净])
ck("而它是**警告不是阻断**(定义本身合法,只是有一类没查)",
   not V.有阻断(干净), 1, [p["code"] for p in 干净 if p["级别"] == V.阻断])
带查 = V.校验(夹具["合法_最小链"]["图"], 依赖存在=lambda 种类, i: True)
ck("给了查询能力 → 那条警告消失,图彻底干净", 带查 == [], len(带查) or 1,
   [p["code"] for p in 带查])
假查 = V.校验(夹具["合法_最小链"]["图"], 依赖存在=lambda 种类, i: False)
ck("查询说「引用不存在」→ 报 REF_NOT_FOUND 并挡住",
   any(p["code"] == "REF_NOT_FOUND" for p in 假查) and V.有阻断(假查),
   len(假查), [p["code"] for p in 假查])

# ── 子额度不许超父额度(§13.2)─────────────────────────────────────
print("\n▸ 子任务额度不许超过父流程(§13.2:嵌套不能重新拿一份完整预算)")
_子图 = json.loads(json.dumps(夹具["合法_最小链"]["图"]))
_子图["nodes"].append({"id": "ag", "type": "agent", "config": {
    "agent_version_id": "av1",
    "task_binding": {"source": "input", "pointer": "/article"},
    "sub_limits": {"max_model_turns": 50, "budget_amount": 3}}})
_子图["edges"].append({"source": "sum", "target": "ag", "port": "success"})
超 = V.校验(_子图, 父额度={"max_model_turns": 8, "budget_amount": 10})
ck("子额度 50 > 父额度 8 → 挡住",
   any(p["code"] == "SUB_LIMIT_EXCEEDS_PARENT" for p in 超), 1,
   [p["code"] for p in 超])
ck("**同一张图里没超的那一项不报**(对照:不是一律拦)",
   sum(1 for p in 超 if p["code"] == "SUB_LIMIT_EXCEEDS_PARENT") == 1, 1,
   [p["field_path"] for p in 超 if p["code"] == "SUB_LIMIT_EXCEEDS_PARENT"])

# ── 支配关系本身:一个不依赖夹具的对照 ──────────────────────────────
print("\n▸ 支配关系(附录 A-1 那条数据流分析的地基)")
后继 = {"s": ["a", "b"], "a": ["m"], "b": ["m"], "m": ["e"], "e": []}
可达 = {"s", "a", "b", "m", "e"}
d = V.支配集("s", 后继, 可达)
ck("汇合点被自己和入口支配,**但不被任一分支支配**",
   d["m"] == {"s", "m"}, 1, sorted(d["m"]))
ck("汇合之后的节点被汇合点支配(所以经汇合取值是安全的)",
   "m" in d["e"] and "a" not in d["e"], 2, sorted(d["e"]))
环后继 = {"s": ["a"], "a": ["b"], "b": ["a", "e"], "e": []}
d2 = V.支配集("s", 环后继, {"s", "a", "b", "e"})
ck("**有环的图也收敛**(循环体内部的子图要用同一个算法)",
   d2["e"] == {"s", "a", "b", "e"}, 1, sorted(d2["e"]))

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
