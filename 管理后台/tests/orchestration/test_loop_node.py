#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""有界循环(10-27;用户拍经营报告「核对不过 → AI 重写 → 店长再核,最多重写 3 次」)。

## 判据(轮数、调用次数、走到哪是手写的,模型调用次数由 mock 那一侧数)

  ① 第一轮就通过 → 1 轮、模型 1 次、成功
  ② 退回两次再通过 → 3 轮、模型 3 次;每一轮的执行键不一样(/loop[1] /loop[2] /loop[3]),不互相覆盖;
     循环状态里留着**最后一次**退回的理由(下一轮写的时候能看见)
  ③ 一直退回 → 跑满上限就停,**受限停止(incomplete, max_iterations)**,不是成功;模型次数 = 上限,不多跑一轮
  ④ 先判断后执行:一开始条件就不满足 → 零轮、模型 0 次
  ⑤ 停在循环里等人核对:检查点里记着第几轮;恢复后接着是同一轮,**轮数不清零**
  ⑥ 检查配置:上限超出 1–10 拦;循环套循环拦;循环体引用循环外面的输入不误报「可能取不到」
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
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:200] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


def 引(n, p):
    return {"source": "node", "node_id": n, "pointer": p}


常 = lambda v: {"source": "constant", "value": v}
文本 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
出 = {"type": "object", "properties": {"轮数": {"type": "integer"}}, "required": ["轮数"], "additionalProperties": False}


def 图(上限=3, 一开始要写=True):
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出,
            "nodes": [
                {"id": "start", "type": "start", "config": {"input_schema": {
                    "type": "object", "properties": {"主题": {"type": "string"}}, "required": ["主题"]}}},
                # 循环外面先取一份材料,循环体每一轮都引用它 —— 验校验器不把「循环外面的一步」误报成「可能取不到」
                {"id": "fetch", "type": "transform", "config": {"operations": [
                    {"op": "to_string", "from": {"source": "input", "pointer": "/主题"}, "into": "材料"}],
                    "output_schema": {"type": "object"}}},
                {"id": "L", "type": "loop", "config": {
                    "max_iterations": 上限,
                    "condition": {"op": "equals", "left": {"source": "scope", "pointer": "/还要写"}, "right": 常(True)},
                    "loop_state": {"还要写": {"initial": 一开始要写, "update": 引("本轮", "/还要写")},
                                   "意见": {"initial": "", "update": 引("again", "/意见")}}}},
                {"id": "write", "type": "llm", "container": "L", "config": {
                    "connection_version_id": "cv1", "prompt_version_id": "p1", "output_schema": 文本,
                    "bindings": {"主题": {"source": "input", "pointer": "/主题"},
                                 "材料": 引("fetch", "/材料"),
                                 "意见": {"source": "scope", "pointer": "/意见"}}}},
                {"id": "review", "type": "human", "container": "L", "config": {
                    "request_kind": "核对", "candidate_roles": ["审核人"], "expires_at_policy": {"小时": 48, "到期": "fail"},
                    "payload_binding": {"摘要": 引("write", "/text")}}},
                {"id": "ok", "type": "condition", "container": "L", "config": {"branches": [
                    {"key": "approve", "when": {"op": "equals", "left": 引("review", "/决定"), "right": 常("approve")}}],
                    "else_policy": "fail"}},
                {"id": "done", "type": "transform", "container": "L", "config": {"operations": [
                    {"op": "default", "from": 常(False), "value": False, "into": "还要写"}],
                    "output_schema": {"type": "object"}}},
                {"id": "again", "type": "transform", "container": "L", "config": {"operations": [
                    {"op": "default", "from": 常(True), "value": True, "into": "还要写"},
                    {"op": "to_string", "from": 引("review", "/理由"), "into": "意见"}], "output_schema": {"type": "object"}}},
                {"id": "本轮", "type": "merge", "container": "L", "config": {
                    "candidates": [引("done", "/还要写"), 引("again", "/还要写")], "output_field": "还要写"}},
                {"id": "end", "type": "end", "config": {"output_schema": 出, "bindings": {"轮数": 引("L", "/轮数")}}},
            ],
            "edges": [
                {"source": "start", "target": "fetch", "port": "success"},
                {"source": "fetch", "target": "L", "port": "success"},
                {"source": "L", "target": "write", "port": "loop_body"},
                {"source": "write", "target": "review", "port": "success"},
                {"source": "review", "target": "ok", "port": "success"},
                {"source": "ok", "target": "done", "port": "branch", "branch_key": "approve"},
                {"source": "ok", "target": "again", "port": "branch", "branch_key": "else"},
                {"source": "done", "target": "本轮", "port": "success"},
                {"source": "again", "target": "本轮", "port": "success"},
                {"source": "L", "target": "end", "port": "loop_exit"},
            ]}


def 跑到底(g, 决定们):
    """一路跑:每停在人工核对就按 决定们 依次给结果。返回 (最后结果, 模型调用次数, 所有步骤, 每次停下时的第几轮)。"""
    计 = {"n": 0, "意见们": []}

    def 模型(cfg, 实参):
        计["n"] += 1
        计["意见们"].append(实参.get("意见"))
        return {"text": f"第{计['n']}稿"}
    计划 = CP.编译(g, 依赖存在=lambda 种类, i: True)
    r = RN.跑一张图(计划, {"主题": "周报"}, 适配器={"llm": 模型}, run_id="r")
    步们, 停时轮 = list(r["步骤"]), []
    for 决 in 决定们:
        if not r.get("检查点"):
            break
        停时轮.append([f["第几轮"] for f in r["检查点"].get("循环帧") or []])
        结 = {"决定": 决, "理由": f"第{len(停时轮)}次退回的理由" if 决 != "approve" else None, "定稿": "x"}
        r = RN.跑一张图(计划, {"主题": "周报"}, 适配器={"llm": 模型}, run_id="r", 恢复=dict(r["检查点"], 结果=结))
        步们 += r["步骤"]
    return r, 计, 步们, 停时轮


print("▸ ① 第一轮就通过")
r, 计, 步们, _ = 跑到底(图(), ["approve"])
ck("1 轮、模型 1 次、成功、输出轮数 1", r["执行状态"] == "succeeded" and 计["n"] == 1 and r["输出"] == {"轮数": 1}, 1,
   (r["执行状态"], 计["n"], r["输出"]))

print("▸ ② 退回两次再通过")
r, 计, 步们, 停时轮 = 跑到底(图(), ["reject", "reject", "approve"])
写键 = sorted({s["execution_key"] for s in 步们 if s["node_id"] == "write" and s["status"] == "succeeded"})
ck("3 轮、模型 3 次、成功、输出轮数 3", r["执行状态"] == "succeeded" and 计["n"] == 3 and r["输出"] == {"轮数": 3}, 1,
   (r["执行状态"], 计["n"], r["输出"]))
ck("每一轮「写」的执行键不一样(/L[1] /L[2] /L[3]),不互相覆盖",
   写键 == ["r:write:/L[1]:1", "r:write:/L[2]:1", "r:write:/L[3]:1"], 3, 写键)
ck("每一轮写的时候看得见上一轮退回的理由(第一轮是空的)",
   计["意见们"] == ["", "第1次退回的理由", "第2次退回的理由"], 3, 计["意见们"])
ck("⑤ 停在核对时检查点记着第几轮:依次是 1、2、3", 停时轮 == [[1], [2], [3]], 3, 停时轮)

print("▸ ③ 一直退回 → 跑满上限受限停止")
r, 计, 步们, _ = 跑到底(图(上限=3), ["reject"] * 5)
ck("incomplete / max_iterations,模型正好 3 次(不多跑一轮),不是成功",
   r["执行状态"] == "incomplete" and r["完成原因"] == "max_iterations" and 计["n"] == 3, 1,
   (r["执行状态"], r["完成原因"], 计["n"]))

print("▸ ④ 先判断后执行")
r, 计, 步们, _ = 跑到底(图(一开始要写=False), [])
ck("一开始条件就不满足 → 零轮、模型 0 次、成功、输出轮数 0",
   r["执行状态"] == "succeeded" and 计["n"] == 0 and r["输出"] == {"轮数": 0}, 1, (r["执行状态"], 计["n"], r["输出"]))

print("▸ ⑥ 检查配置")
码 = lambda g: sorted(p["code"] for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断)
ck("正常那张图:没有阻断(循环体引用循环外面的输入,不误报「可能取不到」)", 码(图()) == [], 1, 码(图()))
g = 图(上限=11)
ck("上限 11 → 只报 LOOP_MAX_RANGE", 码(g) == ["LOOP_MAX_RANGE"], 1, 码(g))
g = 图()
g["nodes"].append({"id": "L2", "type": "loop", "container": "L", "config": {"max_iterations": 2,
                   "condition": {"op": "exists", "left": {"source": "scope", "pointer": "/还要写"}}}})
ck("循环里面又放一个循环 → 报 LOOP_NESTED", "LOOP_NESTED" in 码(g), 1, 码(g))

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
