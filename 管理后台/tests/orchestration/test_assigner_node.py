#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变量赋值(用户 10-27 拍要做;例:经营报告每重写一次「第几稿」加一)。

## 判据(期望值是手写的)

  ① 循环里每轮「第几稿 加上 1」→ 跑 3 轮,结束时第几稿 = 3;「历次意见 追加」→ 按轮次顺序的列表
  ② 改完马上生效:同一轮后面的步骤读得到新值(模型第 n 轮看到的第几稿 = n)
  ③ 停在循环里等人核对 → 检查点里带着改过的值;恢复后接着加,不清零
  ④ 覆盖 / 清空 两种改法各自对
  ⑤ 检查配置:不在循环里 / 改的不是这个循环的状态 / 没选改法 / 加的不是数字 / 和「每一轮结束取自」抢着写 —— 各报各的码
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
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:200] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


常 = lambda v: {"source": "constant", "value": v}
引 = lambda n, p: {"source": "node", "node_id": n, "pointer": p}
文本 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
出 = {"type": "object", "properties": {"第几稿": {"type": "integer"}, "历次意见": {"type": "array"}},
      "required": ["第几稿"], "additionalProperties": False}


def 图(赋值们=None, 带人工=False):
    赋值们 = 赋值们 if 赋值们 is not None else [
        {"variable": "第几稿", "op": "add", "value": 常(1)},
        {"variable": "历次意见", "op": "append", "value": 引("write", "/text")}]
    nodes = [
        {"id": "start", "type": "start", "config": {"input_schema": {"type": "object", "properties": {}}}},
        {"id": "L", "type": "loop", "config": {
            "max_iterations": 3,
            "condition": {"op": "lt", "left": {"source": "scope", "pointer": "/第几稿"}, "right": 常(3)},
            "loop_state": {"第几稿": {"initial": 0}, "历次意见": {"initial": []}, "备注": {"initial": "旧备注"}}}},
        {"id": "write", "type": "llm", "container": "L", "config": {
            "connection_version_id": "cv1", "prompt_version_id": "p1", "output_schema": 文本,
            "bindings": {"第几稿": {"source": "scope", "pointer": "/第几稿"}}}},
        {"id": "数稿", "type": "assigner", "container": "L", "config": {"assignments": 赋值们}},
        {"id": "看", "type": "llm", "container": "L", "config": {
            "connection_version_id": "cv1", "prompt_version_id": "p2", "output_schema": 文本,
            "bindings": {"改完的第几稿": {"source": "scope", "pointer": "/第几稿"}}}},
        {"id": "end", "type": "end", "config": {"output_schema": 出, "bindings": {
            "第几稿": 引("L", "/第几稿"), "历次意见": 引("L", "/历次意见")}}}]
    edges = [{"source": "start", "target": "L", "port": "success"},
             {"source": "L", "target": "write", "port": "loop_body"},
             {"source": "write", "target": "数稿", "port": "success"},
             {"source": "数稿", "target": "看", "port": "success"},
             {"source": "L", "target": "end", "port": "loop_exit"}]
    if 带人工:
        nodes.append({"id": "核", "type": "human", "container": "L", "config": {
            "request_kind": "核对", "candidate_roles": ["审核人"], "expires_at_policy": {"小时": 48, "到期": "fail"},
            "payload_binding": {"摘要": 引("write", "/text")}}})
        edges.append({"source": "看", "target": "核", "port": "success"})
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出, "nodes": nodes, "edges": edges}


def 跑(g, 人工次数=0):
    看见 = []

    def 模型(cfg, 实参):
        看见.append((cfg["prompt_version_id"], dict(实参)))
        return {"text": f"第{len([x for x in 看见 if x[0] == 'p1'])}稿"}
    计划 = CP.编译(g, 依赖存在=lambda 种类, i: True)
    r = RN.跑一张图(计划, {}, 适配器={"llm": 模型}, run_id="r")
    停时 = []
    for _ in range(人工次数):
        if not r.get("检查点"):
            break
        停时.append(copy.deepcopy([f["状态"]["第几稿"] for f in r["检查点"]["循环帧"]]))
        r = RN.跑一张图(计划, {}, 适配器={"llm": 模型}, run_id="r", 恢复=dict(r["检查点"], 结果={"决定": "approve"}))
    return r, 看见, 停时


print("▸ ① 每轮加一、每轮追加")
r, 看见, _ = 跑(图())
ck("跑 3 轮,结束时第几稿 = 3,历次意见按轮次排", r["执行状态"] == "succeeded"
   and r["输出"] == {"第几稿": 3, "历次意见": ["第1稿", "第2稿", "第3稿"]}, 1, r.get("输出"))

print("▸ ② 改完马上生效")
写时 = [a["第几稿"] for p, a in 看见 if p == "p1"]
看时 = [a["改完的第几稿"] for p, a in 看见 if p == "p2"]
ck("同一轮里:写之前看到 0/1/2,赋值之后那一步看到 1/2/3", 写时 == [0, 1, 2] and 看时 == [1, 2, 3], 6, (写时, 看时))
步 = [s for s in r["步骤"] if s["node_id"] == "数稿"]
ck("这一步记下改了什么、原来是多少", 步 and 步[0]["input"][0] == {"改": "第几稿", "怎么改": "加上", "原来": 0}
   and 步[0]["output"]["第几稿"] == 1, 1, 步[:1])

print("▸ ③ 停在循环里等人,恢复不清零")
r, _, 停时 = 跑(图(带人工=True), 人工次数=5)
ck("每次停下检查点里的第几稿依次是 1、2、3,恢复后跑完 = 3", 停时 == [[1], [2], [3]] and r["输出"].get("第几稿") == 3, 3, (停时, r.get("输出")))

print("▸ ④ 覆盖 / 清空")
r, _, _ = 跑(图([{"variable": "第几稿", "op": "add", "value": 常(1)},
                 {"variable": "备注", "op": "set", "value": 引("write", "/text")}]))
循环出 = [x for x in r["步骤"] if x["node_id"] == "L" and x["status"] == "succeeded"]
ck("覆盖:循环结束时备注 = 最后一轮写的「第3稿」(原来是「旧备注」)",
   r["执行状态"] == "succeeded" and 循环出 and 循环出[-1]["output"].get("备注") == "第3稿", 1, 循环出[-1:])
g = 图([{"variable": "第几稿", "op": "add", "value": 常(1)}, {"variable": "历次意见", "op": "clear"}])
r, _, _ = 跑(g)
ck("清空:列表清成 []", r["输出"] == {"第几稿": 3, "历次意见": []}, 1, r.get("输出"))

print("▸ ⑤ 检查配置")
码 = lambda g: sorted(p["code"] for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断)
ck("正常那张图:没有阻断", 码(图()) == [], 1, 码(图()))
g = 图(); del g["nodes"][3]["container"]
ck("不在循环里 → 报 ASSIGN_NOT_IN_LOOP", "ASSIGN_NOT_IN_LOOP" in 码(g), 1, 码(g))
g = 图([{"variable": "店长", "op": "set", "value": 常("x")}])
ck("改的不是这个循环的状态 → 报 ASSIGN_UNKNOWN_VAR", "ASSIGN_UNKNOWN_VAR" in 码(g), 1, 码(g))
g = 图([{"variable": "第几稿"}])
ck("没选改法 → 报 ASSIGN_BAD_OP", "ASSIGN_BAD_OP" in 码(g), 1, 码(g))
g = 图([{"variable": "第几稿", "op": "add", "value": 常("一")}])
ck("加的不是数字 → 报 ASSIGN_ADD_NOT_NUMBER", "ASSIGN_ADD_NOT_NUMBER" in 码(g), 1, 码(g))
g = 图([{"variable": "备注", "op": "set"}])
ck("覆盖没选值 → 报 ASSIGN_NO_VALUE", "ASSIGN_NO_VALUE" in 码(g), 1, 码(g))
g = 图(); g["nodes"][1]["config"]["loop_state"]["第几稿"]["update"] = 引("write", "/text")
ck("和「每一轮结束取自」抢着写 → 只报 ASSIGN_CONFLICT_UPDATE", 码(g) == ["ASSIGN_CONFLICT_UPDATE"], 1, 码(g))

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
