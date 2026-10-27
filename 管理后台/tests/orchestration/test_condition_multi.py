#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""条件分支一路几条条件,用「且 / 或」连(10-27 照 Dify;用户拍把一串「填了负责人吗 → 填了截止吗」合成一个节点)。

## 判据(走哪一路是手写的,不由执行器生成)

  ① 且:都满足才走这一路;或:有一条满足就走
  ② 短路:「且」第一条不满足就定了 —— 第二条要用的数据**没有**也不报错(它没被取值);「或」反过来
  ③ 缺值按**每条自己**声明的策略:声明「缺值按不满足」的那条当 false,没声明的照旧停下(COND_VAR_MISSING)
  ④ 老写法(一路一条 `when`)和新写法(`conditions` 只有一条)走出来一模一样 —— 已有的流程意思不变
  ⑤ 一条条件都没有的一路 → 检查配置拦(COND_EMPTY);条件没选「取哪个值」→ 拦(COND_INCOMPLETE)
  ⑥ 运行记录里每条条件各记一行(第几条、且 / 或、左右两边)—— 「为什么走了这一路」看得见
"""
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
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:190] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


def 入(k):
    return {"source": "input", "pointer": "/" + k}


def 有(k, 缺值=None):
    c = {"op": "exists", "left": 入(k)}
    if 缺值:
        c["on_missing"] = 缺值
    return c


def 等(k, v):
    return {"op": "equals", "left": 入(k), "right": {"source": "constant", "value": v}}


出 = {"type": "object", "properties": {}, "required": []}


def 图(一路):
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出,
            "nodes": [
                {"id": "start", "type": "start", "config": {"input_schema": {"type": "object", "properties": {
                    k: {"type": "string"} for k in ("负责人", "截止", "意向")}, "required": []}}},
                {"id": "判", "type": "condition", "config": {"branches": [dict(一路, key="派")], "else_policy": "end"}},
                {"id": "派", "type": "end", "config": {"output_schema": 出, "bindings": {}}},
            ],
            "edges": [{"source": "start", "target": "判", "port": "success"},
                      {"source": "判", "target": "派", "port": "branch", "branch_key": "派"}]}


def 跑(一路, 输入):
    r = RN.跑一张图(CP.编译(图(一路), 依赖存在=lambda 种类, i: True), 输入, 适配器={}, run_id="c")
    s = {x["node_id"]: x for x in r["步骤"]}["判"]
    return s.get("branch_key"), s


print("▸ ① 且 / 或(期望手写)")
且 = {"logic": "and", "conditions": [有("负责人"), 有("截止")]}
或 = {"logic": "or", "conditions": [等("意向", "有"), 等("意向", "说不清")]}
用例 = [(且, {"负责人": "林岚", "截止": "10-30"}, "派"), (且, {"负责人": "林岚"}, "else"), (且, {}, "else"),
        (或, {"意向": "说不清"}, "派"), (或, {"意向": "没有"}, "else")]
坏 = [(i, 期, 跑(路, 入参)[0]) for i, (路, 入参, 期) in enumerate(用例) if 跑(路, 入参)[0] != 期]
ck("每个用例走的那一路和手写期望一致", not 坏, len(用例), 坏)

print("▸ ② 短路:后面那条要的数据没有,也不报错")
短且 = {"logic": "and", "conditions": [等("意向", "有"), 有("负责人")]}       # 第二条没声明缺值策略
k, s = 跑(短且, {"意向": "没有"})
ck("「且」第一条不满足 → 走「都不满足」,第二条没被取值(没报缺值)", k == "else" and len(s["input"]) == 1, 1, s)
短或 = {"logic": "or", "conditions": [等("意向", "有"), 有("负责人")]}
k, s = 跑(短或, {"意向": "有"})
ck("「或」第一条满足 → 走这一路,第二条没被取值", k == "派" and len(s["input"]) == 1, 1, s)

print("▸ ③ 缺值按每条自己的声明")
k, s = 跑({"logic": "and", "conditions": [有("负责人"), 等("截止", "x") | {"on_missing": "false"}]}, {"负责人": "林岚"})
ck("声明「缺值按不满足」的那条当 false → 走「都不满足」", k == "else", 1, s)
k, s = 跑({"logic": "and", "conditions": [有("负责人"), 等("截止", "x")]}, {"负责人": "林岚"})
ck("没声明的那条缺值 → 这一步失败 COND_VAR_MISSING,不默默当不满足",
   s.get("status") == "failed" and s.get("error_code") == "COND_VAR_MISSING", 1, s)

print("▸ ④ 老写法和新写法一样")
老 = [跑({"when": 有("负责人")}, x)[0] for x in ({"负责人": "a"}, {})]
新 = [跑({"conditions": [有("负责人")]}, x)[0] for x in ({"负责人": "a"}, {})]
ck("一路一条 `when` 和 `conditions` 只有一条,走出来一模一样", 老 == 新 == ["派", "else"], 2, (老, 新))

print("▸ ⑤ 检查配置拦空条件 / 没填完的条件")
码 = lambda 一路: sorted(p["code"] for p in V.校验(图(一路), 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断)
ck("一条条件都没有 → 只报 COND_EMPTY", 码({"logic": "and", "conditions": []}) == ["COND_EMPTY"], 1,
   码({"logic": "and", "conditions": []}))
ck("有一条没选「取哪个值」→ 只报 COND_INCOMPLETE",
   码({"conditions": [有("负责人"), {"op": "exists"}]}) == ["COND_INCOMPLETE"], 1,
   码({"conditions": [有("负责人"), {"op": "exists"}]}))

print("▸ ⑥ 运行记录每条一行")
k, s = 跑(且, {"负责人": "林岚", "截止": "10-30"})
ck("两条各记一行:第几条、连接「且」、左边的值",
   [(x.get("第几条"), x.get("连接"), x.get("左边")) for x in s["input"]] == [(1, "且", "林岚"), (2, "且", "10-30")], 1, s["input"])

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
