#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**这次运行真正生效的上限是哪几个数,每个数从哪来** —— 零 IO。

两个地方在说同一件事:**执行策略**(组织护栏)和 **Agent 自己的 `limits`**。
`agent_loop.py` 现在只读后者,所以策略里的数一个都没落到执行上。

## 这一组每一条都对着一种**悄悄放宽**的方式

   ① 「策略说了算」→ 一个填得更严的 Agent 被放宽
   ② 「Agent 说了算」→ 填个 999 就退出护栏
   ③ 只报数值不报来源 → 分不出护栏有没有在工作
   ④ `limits.get(k) or 默认` → **把 0 读成「没填」**
   ⑤ 两边都没有时兜一个默认 → 把上游所有努力静默抵消
   ⑥ 布尔当数字 → `True == 1`,看起来像「上限 1 次」
   ⑦ 新口径照旧合并 → 一个计数器冒充两个(规格 §5.2)
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))

import 有效上限 as E
import 兜底上限 as B
import 策略冻结 as F

G, R, D = "\033[32m", "\033[31m", "\033[0m"
过, 挂 = 0, 0


def ck(说, ok, 附=""):
    global 过, 挂
    if ok:
        过 += 1
        print(f"  {G}✅{D} {说}  {附}")
    else:
        挂 += 1
        print(f"  {R}❌{D} {说}  {附}")


def 策(**limits):
    """一份策略的最小形状。口径默认旧的 —— `兜底上限` 给的就是旧口径。"""
    return {"limits": dict(limits), "counter_schema_version": F.旧口径,
            "来源": "测试用"}


print("▸ ① 键名对账 —— **两边的名字都点名,不许猜**")
for 名, 元 in E.执行点.items():
    for k in 元["策略键"]:
        ck(f"`{名}` 对应的策略键 `{k}` 在冻结的白名单里",
           k in F.认得的limits键)
# 执行点的名字必须是 agent_loop 真读的那两个 —— 改了名字这条会红
ck("执行点就是 agent_loop 真读的那两个",
   sorted(E.执行点) == ["max_model_turns", "max_tool_attempts"], sorted(E.执行点))

print("\n▸ ② 🔑 两边都有时取**更严**的那个 —— 两个方向都要验")
# ⚠️ **这两条必须一起看。** 只验一个方向的话:
# > 一个「总是用策略」的实现,和一个「取更严」的,
# > **在「Agent 填 999 被压回去」那一条上长得一模一样。**
严配置 = E.定(策略=策(model_request_cap=8), agent配置={"max_model_turns": 3,
                                                 "max_tool_attempts": 5})
ck("Agent 填得更严 → 用 Agent 的(3,不是 8)",
   严配置["max_model_turns"]["值"] == 3, 严配置["max_model_turns"]["值"])
ck("而来源要说清是 Agent 更严",
   严配置["max_model_turns"]["来源"] == E.配置更严,
   严配置["max_model_turns"]["来源"])
松配置 = E.定(策略=策(model_request_cap=8), agent配置={"max_model_turns": 999,
                                                 "max_tool_attempts": 999})
ck("🔑 Agent 填 999 → 被策略压回 8(**填个大数退不出护栏**)",
   松配置["max_model_turns"]["值"] == 8, 松配置["max_model_turns"]["值"])
ck("而来源要说清是策略更严",
   松配置["max_model_turns"]["来源"] == E.策略更严,
   松配置["max_model_turns"]["来源"])
一样 = E.定(策略=策(model_request_cap=8), agent配置={"max_model_turns": 8,
                                                "max_tool_attempts": 8})
ck("两边一样 → 单独一个来源(不许随便挑一边说)",
   一样["max_model_turns"]["来源"] == E.两边一样, 一样["max_model_turns"]["来源"])

print("\n▸ ③ 🔑 **来源必须报出来** —— 不然分不出护栏有没有在工作")
# > 一个「被组织策略拦住」的运行,和一个「Agent 自己配得严才没跑飞」的,
# > **在那次停下来上长得一模一样。**
ck("每个执行点都带来源", all(d.get("来源") in E.来源们
                        for d in 松配置.values()),
   [d.get("来源") for d in 松配置.values()])
ck("来源五种两两不同 —— **下一步不同的,就得分开**",
   len(set(E.来源们)) == 5, E.来源们)
ck("`说清()` 那一行里带着来源",
   all("更严" in l or "两边一样" in l or "只有" in l for l in E.说清(松配置)),
   E.说清(松配置))
ck("`说清()` 还带着口径(同名字段在两套口径下数的不是一件事)",
   all("口径" in l for l in E.说清(松配置)))
ck("策略从哪来也跟着走(兜底 / 已发布 / 回退)",
   松配置["max_model_turns"]["策略从哪来"] == "测试用")

print("\n▸ ④ 🔑 **0 不是「无限制」**")
零 = E.定(策略=策(model_request_cap=0, tool_attempt_cap=0), agent配置={})
ck("策略里的 0 被当成有效值(一次都不许)", 零["max_model_turns"]["值"] == 0,
   零["max_model_turns"]["值"])
ck("理由里明说「0 的意思是一次都不许」",
   "一次都不许" in 零["max_model_turns"]["为什么"])
零配 = E.定(策略=策(model_request_cap=8, tool_attempt_cap=8),
           agent配置={"max_model_turns": 0})
ck("🔑 Agent 填 0 也是有效值,而且它更严 → 取 0",
   零配["max_model_turns"]["值"] == 0 and 零配["max_model_turns"]["来源"] == E.配置更严,
   (零配["max_model_turns"]["值"], 零配["max_model_turns"]["来源"]))

print("\n▸ ⑤ 两边都没有 → **抛**,不兜底")
try:
    E.定(策略=策(model_request_cap=8), agent配置={})
    ck("`max_tool_attempts` 两边都没有 → 抛", False, "它没抛")
except E.定不了 as e:
    ck("`max_tool_attempts` 两边都没有 → **抛**", "不叫「不限制」" in str(e))
    ck("理由里点名两边各该有什么", "兜底上限" in str(e), str(e)[:60])
try:
    E.定(策略={"limits": {}, "counter_schema_version": F.旧口径})
    ck("策略里一个 limits 都没有 → 抛", False, "它没抛")
except E.定不了 as e:
    ck("策略里一个 limits 都没有 → **抛**(不是「不限制」)",
       "没给策略" in str(e))

print("\n▸ ⑥ 布尔当数字 → 抛(**布尔判在整数之前**)")
for 坏, 哪儿 in ((策(model_request_cap=True), "策略"),
               (策(model_request_cap=8, tool_attempt_cap=8), "配置")):
    try:
        if 哪儿 == "策略":
            E.定(策略=坏, agent配置={"max_tool_attempts": 8})
        else:
            E.定(策略=坏, agent配置={"max_model_turns": True})
        ck(f"{哪儿}里的布尔 → 抛", False, "它没抛")
    except E.定不了 as e:
        ck(f"{哪儿}里的布尔 → **抛**(`True == 1`,会变成「上限 1 次」)",
           "布尔" in str(e))
try:
    E.定(策略=策(model_request_cap=-1, tool_attempt_cap=8))
    ck("负数 → 抛", False, "它没抛")
except E.定不了 as e:
    ck("负数 → **抛**(负数不是「不限制」)", "负数" in str(e))

print("\n▸ ⑦ 新口径 → **抛**,不拿一个计数器冒充两个(规格 §5.2)")
新 = {"limits": {"model_request_cap": 8, "tool_attempt_cap": 12},
      "counter_schema_version": F.新口径}
try:
    E.定(策略=新)
    ck("新口径 → 抛", False, "它没抛")
except E.定不了 as e:
    ck("新口径 → **抛**,并点名要先把计数器分开",
       "冒充" in str(e) and "待建" in str(e), str(e)[:70])
try:
    E.定(策略={"limits": {"model_request_cap": 8}, "counter_schema_version": "v9"})
    ck("认不出的口径 → 抛", False, "它没抛")
except E.定不了 as e:
    ck("认不出的口径 → **抛**(不知道是哪套尺子就没法合并)", "认不出" in str(e))

print("\n▸ ⑧ 工具那一条:旧口径下一个数兜两个键,取更严 + **说明这是近似**")
俩 = E.定(策略=策(model_request_cap=8, tool_request_cap=20, tool_attempt_cap=12))
ck("`tool_request_cap=20` / `tool_attempt_cap=12` → 取 12(更严)",
   俩["max_tool_attempts"]["值"] == 12, 俩["max_tool_attempts"]["值"])
ck("记下实际用了哪个键",
   俩["max_tool_attempts"]["策略用的那个键"] == "tool_attempt_cap",
   俩["max_tool_attempts"]["策略用的那个键"])
ck("🔑 理由里**明说这是近似**(它在网关之前自增,数的是请求不是尝试)",
   "近似" in 俩["max_tool_attempts"]["为什么"]
   and "请求" in 俩["max_tool_attempts"]["为什么"])
反 = E.定(策略=策(model_request_cap=8, tool_request_cap=5, tool_attempt_cap=12))
ck("反过来 `tool_request_cap=5` 更严 → 取 5(两个方向都验)",
   反["max_tool_attempts"]["值"] == 5
   and 反["max_tool_attempts"]["策略用的那个键"] == "tool_request_cap",
   (反["max_tool_attempts"]["值"], 反["max_tool_attempts"]["策略用的那个键"]))

print("\n▸ ⑨ 🔑 接上 `兜底上限` —— **那两个内联默认值能删掉吗**")
# `agent_loop.py:120/:229` 现在写的是 `限.get("max_model_turns", 8)`。
# > 一处写在 `.get(..., 8)` 里的兜底,和一处写在策略模块里的,
# > **在那个 8 上长得一模一样** —— 而同一个事实两个来源,必然漂。
# 所以这里验:**Agent 配置为空时,兜底也给得出数**,于是那两行默认值可以删。
兜 = B.兜底(入口=F.后台编排)
空 = E.定(策略=兜, agent配置=None)
ck("Agent 没配 limits 时,两个执行点**都有数**(所以内联默认值可以删)",
   空["max_model_turns"]["值"] is not None
   and 空["max_tool_attempts"]["值"] is not None,
   {k: v["值"] for k, v in 空.items()})
ck("而且那两个数就是规格 §5.3 的 8 / 12",
   (空["max_model_turns"]["值"], 空["max_tool_attempts"]["值"]) == (8, 12),
   (空["max_model_turns"]["值"], 空["max_tool_attempts"]["值"]))
ck("来源点名是「只有执行策略有」,而策略从哪来是「内置兜底」",
   空["max_model_turns"]["来源"] == E.只有策略
   and "内置兜底" in 空["max_model_turns"]["策略从哪来"],
   (空["max_model_turns"]["来源"], 空["max_model_turns"]["策略从哪来"]))
# ⚠️ 对照组:兜底给的数**和 agent_loop 内联的那两个一样**,所以「接上去
# 不会改变现在的行为」—— 这一条让接线那一步可以单独验「只换了来源,没换数」。
ck("🔑 兜底的数和 agent_loop 内联默认值一致 → 接线那一步**不该改变行为**",
   (空["max_model_turns"]["值"], 空["max_tool_attempts"]["值"]) == (8, 12))

print("\n" + "=" * 92)
if 挂:
    print(f"{R}❌ 过 {过} / 挂 {挂}{D}")
    sys.exit(1)
print(f"{G}✅ 过 {过} / 挂 {挂}{D}")
