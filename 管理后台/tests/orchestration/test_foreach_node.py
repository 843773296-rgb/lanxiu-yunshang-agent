#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列表迭代(11-12,照 Dify「迭代」;用户 10-26 拍「workflow 直接复刻 dify」)。

## 判据(期望的结果、次数、下标都是手写的;模型调用次数由 mock 那一侧数,不由执行器自报)

  ① 正常:三项逐项跑,结果和输入一一对应、顺序一致;里面的步骤拿得到「当前项」「下标」;
     每一项的执行键不一样(/FE[1] /FE[2] /FE[3]),每一项的输入输出都记着;串行(第 2 项开始前第 1 项已经做完)
  ② 空列表:零项、模型 0 次、成功,结果是空列表(不是取不到),里面的步骤记「跳过」
  ③ 超上限:给 3 项、最多 2 项 → 一项都不做(模型 0 次),这一步失败 FOREACH_TOO_MANY
  ④ 某一项失败:
       · 整步失败(默认):第 2 项失败 → 第 3 项不做;迭代这一步记 FOREACH_ITEM_FAILED,错误里写着「第 2 项(下标 1)」和原因;
         接了迭代的「失败时」出口就走那条线
       · 留空位接着做:结果 [A, null, C],失败项里记着下标 1、哪一步、原因码;整步成功
     · 「每一项交出什么」那一步这一项没跑到 → 也算这一项失败(不拿上一项的结果冒充)
  ⑤ 套娃被拦(检查配置):迭代里放循环、循环里放迭代、迭代里放迭代
  ⑥ 检查配置的其余几条:不是列表引用 / 里面是空的 / 里面取了迭代没给的变量 / 取了被删的步骤 / 交出的不是里面的步骤 /
     上限越界 / 策略不认识 / 取迭代自己的结果 / 变量赋值放进迭代;正常那张图没有阻断(正向对照)
  ⑦ 运行记录截断:25 项时这一步的记录列前 20 项,并写明「还有 5 项」;而每一项里面的步骤 25 条都在
  ⑧ 停在里面等人核对:检查点记着第几项和已收的结果;恢复后接着做,最后结果完整、顺序对
  ⑨ 预算:整次运行最多 2 次模型调用,3 项 → 第 3 项被拦成受限停止(和循环同一份额度,不另给)
  ⑩ 执行器第二道:绕过校验直接跑一个运行时不是列表的输入 → FOREACH_NOT_LIST,不崩
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
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:240] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


def 引(n, p):
    return {"source": "node", "node_id": n, "pointer": p}


常 = lambda v: {"source": "constant", "value": v}
域 = lambda p: {"source": "scope", "pointer": p}
文本 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
出 = {"type": "object", "properties": {"结果": {"type": "array"}, "个数": {"type": "integer"}}, "required": ["结果"],
     "additionalProperties": False}


def 图(*, 上限=10, 策略="fail", 接失败=False, 等人=False):
    """开始(给一个列表)→ 迭代 FE [ 转数字 num → AI 写 write (→ 人工核对 review) ] → 结束。"""
    nodes = [
        {"id": "start", "type": "start", "config": {"input_schema": {
            "type": "object", "properties": {"单": {"type": "array"}}, "required": ["单"]}}},
        {"id": "FE", "type": "foreach", "config": {
            "bindings": {"列表": {"source": "input", "pointer": "/单"}},
            "item_output": 引("write", "/text"), "item_failure_policy": 策略, "max_items": 上限}},
        {"id": "num", "type": "transform", "container": "FE", "config": {"operations": [
            {"op": "to_number", "from": 域("/当前项/金额"), "into": "n"}], "output_schema": {"type": "object"}}},
        {"id": "write", "type": "llm", "container": "FE", "config": {
            "connection_version_id": "cv1", "prompt_version_id": "p1", "output_schema": 文本,
            "bindings": {"名": 域("/当前项/名"), "下标": 域("/下标"), "金额": 引("num", "/n")}}},
        {"id": "end", "type": "end", "config": {"output_schema": 出, "bindings": {
            "结果": 引("FE", "/结果"), "个数": 引("FE", "/个数")}}},
    ]
    edges = [
        {"source": "start", "target": "FE", "port": "success"},
        {"source": "FE", "target": "num", "port": "loop_body"},
        {"source": "num", "target": "write", "port": "success"},
        {"source": "FE", "target": "end", "port": "loop_exit"},
    ]
    if 等人:
        nodes.insert(4, {"id": "review", "type": "human", "container": "FE", "config": {
            "request_kind": "核对", "candidate_roles": ["审核人"], "expires_at_policy": {"小时": 48, "到期": "fail"},
            "payload_binding": {"稿": 引("write", "/text")}}})
        edges.append({"source": "write", "target": "review", "port": "success"})
    if 接失败:
        nodes[1]["config"]["failure_policy"] = "branch"
        nodes.append({"id": "人工", "type": "answer", "config": {"template": "交人工处理"}})
        edges.append({"source": "FE", "target": "人工", "port": "error"})
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出, "nodes": nodes, "edges": edges}


def 跑(g, 单, *, 上限=None, 恢复决定=()):
    计 = {"n": 0, "收到": []}

    def 模型(cfg, 实参):
        计["n"] += 1
        计["收到"].append(dict(实参))
        return {"text": f"{实参['名']}#{实参['下标']}"}
    计划 = CP.编译(g, 依赖存在=lambda 种类, i: True)
    r = RN.跑一张图(计划, {"单": 单}, 适配器={"llm": 模型}, run_id="r", 上限=上限)
    步们, 停时 = list(r["步骤"]), []
    for 决 in 恢复决定:
        if not r.get("检查点"):
            break
        帧 = (r["检查点"].get("循环帧") or [{}])[-1]
        停时.append((帧.get("第几轮"), list(帧.get("结果") or [])))
        r = RN.跑一张图(计划, {"单": 单}, 适配器={"llm": 模型}, run_id="r", 上限=上限,
                      恢复=dict(r["检查点"], 结果={"决定": 决, "定稿": "x"}))
        步们 += r["步骤"]
    return r, 计, 步们, 停时


三项 = [{"名": "A", "金额": "1"}, {"名": "B", "金额": "2"}, {"名": "C", "金额": "3"}]
坏一项 = [{"名": "A", "金额": "1"}, {"名": "B", "金额": "很多"}, {"名": "C", "金额": "3"}]
FE步 = lambda 步们: [s for s in 步们 if s["node_id"] == "FE"]

print("▸ ① 正常:逐项跑、顺序一致")
r, 计, 步们, _ = 跑(图(), 三项)
ck("成功,结果 [A#0, B#1, C#2]、个数 3", r["执行状态"] == "succeeded"
   and r["输出"] == {"结果": ["A#0", "B#1", "C#2"], "个数": 3}, 1, (r["执行状态"], r["输出"]))
ck("模型正好 3 次,依次收到第 1、2、3 项(串行、按输入顺序)",
   计["n"] == 3 and [x["名"] for x in 计["收到"]] == ["A", "B", "C"], 3, 计["收到"])
ck("里面的步骤取得到「下标」(从 0 数)和「当前项」里的字段,也取得到这一项前一步的结果",
   [(x["下标"], x["金额"]) for x in 计["收到"]] == [(0, 1), (1, 2), (2, 3)], 3, 计["收到"])
写键 = [s["execution_key"] for s in 步们 if s["node_id"] == "write" and s["status"] == "succeeded"]
ck("每一项「写」的执行键不一样(/FE[1] /FE[2] /FE[3]),不互相覆盖",
   写键 == ["r:write:/FE[1]:1", "r:write:/FE[2]:1", "r:write:/FE[3]:1"], 3, 写键)
ck("每一项那一步的输入输出都记在运行记录里(第 2 项的输入是 B、输出是 B#1)",
   [s.get("input", {}).get("名") for s in 步们 if s["node_id"] == "write"] == ["A", "B", "C"]
   and [s.get("output", {}).get("text") for s in 步们 if s["node_id"] == "write"][1] == "B#1", 3)
fs = FE步(步们)
ck("迭代自己记一步:成功、执行键在顶层(/)、逐项列着输入和输出",
   len(fs) == 1 and fs[0]["status"] == "succeeded" and fs[0]["execution_key"] == "r:FE:/:1"
   and [(x["下标"], x["输入"]["名"], x["输出"]) for x in fs[0]["output"]["逐项"]] == [(0, "A", "A#0"), (1, "B", "B#1"), (2, "C", "C#2")]
   and "没列出" not in fs[0]["output"], 1, fs)
顺 = [s["node_id"] for s in 步们 if s["status"] == "succeeded"]
ck("串行:num/write 交替出现(第 1 项做完才开始第 2 项),迭代最后才记成功",
   顺 == ["start", "num", "write", "num", "write", "num", "write", "FE", "end"], 1, 顺)

print("▸ ② 空列表")
r, 计, 步们, _ = 跑(图(), [])
ck("零项:成功、模型 0 次、结果是空列表、个数 0", r["执行状态"] == "succeeded" and 计["n"] == 0
   and r["输出"] == {"结果": [], "个数": 0}, 1, (r["执行状态"], 计["n"], r["输出"]))
ck("里面的步骤一个没跑 → 记「跳过」,不是成功", {s["node_id"]: s["status"] for s in 步们 if s["node_id"] in ("num", "write")}
   == {"num": "skipped", "write": "skipped"}, 2, [(s["node_id"], s["status"]) for s in 步们])

print("▸ ③ 超上限")
r, 计, 步们, _ = 跑(图(上限=2), 三项)
ck("给 3 项、最多 2 项 → 失败 FOREACH_TOO_MANY,一项都不做(模型 0 次)",
   r["执行状态"] == "failed" and r["完成原因"] == "FOREACH_TOO_MANY" and 计["n"] == 0, 1,
   (r["执行状态"], r["完成原因"], 计["n"]))
fs = FE步(步们)
ck("错误里说清给了几项、上限几项", fs and "3 项" in fs[0]["error_detail"]["消息"] and "2 项" in fs[0]["error_detail"]["消息"],
   len(fs), fs)

print("▸ ④ 某一项失败")
r, 计, 步们, _ = 跑(图(), 坏一项)
fs = FE步(步们)
ck("整步失败(默认):整次失败、完成原因 FOREACH_ITEM_FAILED,第 3 项没做(模型只 1 次)",
   r["执行状态"] == "failed" and r["完成原因"] == "FOREACH_ITEM_FAILED" and 计["n"] == 1, 1,
   (r["执行状态"], r["完成原因"], 计["n"]))
ck("迭代这一步记失败,错误里写着「第 2 项(下标 1)」、失败在哪一步、原来的原因",
   len(fs) == 1 and fs[0]["status"] == "failed" and fs[0]["error_code"] == "FOREACH_ITEM_FAILED"
   and "第 2 项(下标 1)" in fs[0]["error_detail"]["消息"] and "num" in fs[0]["error_detail"]["消息"]
   and "很多" in fs[0]["error_detail"]["消息"], len(fs), fs)
ck("失败那一项的记录:原因码 TRANSFORM_NOT_NUMBER、做完 1 项(A#0 在记录里)",
   fs and fs[0]["output"]["失败的那一项"]["code"] == "TRANSFORM_NOT_NUMBER" and fs[0]["output"]["做完的项"] == 1
   and fs[0]["output"]["逐项"][0]["输出"] == "A#0", len(fs), fs)
ck("那一项里面失败的步骤自己也记着(执行键 /FE[2])",
   [s["execution_key"] for s in 步们 if s["node_id"] == "num" and s["status"] == "failed"] == ["r:num:/FE[2]:1"], 1)
r, 计, 步们, _ = 跑(图(接失败=True), 坏一项)
ck("迭代接了「失败时」出口 → 走那条线(人工那一步跑了),不是整次直接失败",
   "人工" in r["走过的路径"] and [s["status"] for s in FE步(步们)] == ["failed"], 1, (r["走过的路径"], r["执行状态"]))
r, 计, 步们, _ = 跑(图(策略="continue"), 坏一项)
ck("留空位接着做:成功,结果 [A#0, null, C#2](失败那一位占着、没被删),模型 2 次",
   r["执行状态"] == "succeeded" and r["输出"]["结果"] == ["A#0", None, "C#2"] and 计["n"] == 2, 1,
   (r["执行状态"], r["输出"], 计["n"]))
fs = FE步(步们)
ck("失败项里记着下标 1、失败在 num、原因码 TRANSFORM_NOT_NUMBER;逐项记录里那一位写的是失败不是输出",
   fs and [(x["下标"], x["步骤"], x["code"]) for x in fs[0]["output"]["失败项"]] == [(1, "num", "TRANSFORM_NOT_NUMBER")]
   and "失败" in fs[0]["output"]["逐项"][1] and "输出" not in fs[0]["output"]["逐项"][1], len(fs), fs)
# 「每一项交出什么」那一步这一项没跑到:write 前加一道条件,第 2 项走「都不满足」到另一步,这一项就此做完
g = 图(策略="continue")
g["nodes"].insert(3, {"id": "只要AC", "type": "condition", "container": "FE", "config": {"branches": [
    {"key": "yes", "when": {"op": "not_equals", "left": 域("/当前项/名"), "right": 常("B")}}], "else_policy": "fail"}})
g["nodes"].insert(4, {"id": "略过", "type": "transform", "container": "FE", "config": {
    "operations": [{"op": "default", "from": 常(1), "value": 1, "into": "x"}], "output_schema": {"type": "object"}}})
g["edges"] = [e for e in g["edges"] if e["source"] != "num"] + [
    {"source": "num", "target": "只要AC", "port": "success"},
    {"source": "只要AC", "target": "write", "port": "branch", "branch_key": "yes"},
    {"source": "只要AC", "target": "略过", "port": "branch", "branch_key": "else"}]
r, 计, 步们, _ = 跑(g, 三项)
ck("「每一项交出什么」那一步这一项没跑到 → 这一项算失败、留空位(不拿上一项的 A#0 冒充)",
   r["执行状态"] == "succeeded" and r["输出"]["结果"] == ["A#0", None, "C#2"]
   and [x["code"] for x in FE步(步们)[0]["output"]["失败项"]] == ["FOREACH_ITEM_NO_OUTPUT"], 1,
   (r["执行状态"], r["输出"], FE步(步们)))

print("▸ ⑤ 套娃被拦")
码 = lambda g: sorted({p["code"] for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断})
g = 图()
g["nodes"].append({"id": "L", "type": "loop", "container": "FE", "config": {"max_iterations": 2,
                   "condition": {"op": "exists", "left": 域("/当前项")}}})
g["nodes"].append({"id": "Lx", "type": "transform", "container": "L", "config": {
    "operations": [{"op": "default", "from": 常(1), "value": 1, "into": "x"}], "output_schema": {"type": "object"}}})
g["edges"].append({"source": "L", "target": "Lx", "port": "loop_body"})
ck("迭代里面放循环 → LOOP_NESTED", "LOOP_NESTED" in 码(g), 1, 码(g))
g = 图()
外 = {"id": "外", "type": "loop", "config": {"max_iterations": 2, "condition": {"op": "exists", "left": 域("/还要")},
                                            "loop_state": {"还要": {"initial": True}}}}
g["nodes"].insert(1, 外)
for n in g["nodes"]:
    if n["id"] in ("FE",):
        n["container"] = "外"
g["edges"] = [{"source": "start", "target": "外", "port": "success"}, {"source": "外", "target": "FE", "port": "loop_body"},
              {"source": "外", "target": "end", "port": "loop_exit"}] + [e for e in g["edges"] if e["source"] == "FE" and e["port"] == "loop_body" or e["source"] == "num"]
ck("循环里面放迭代 → FOREACH_NESTED", "FOREACH_NESTED" in 码(g), 1, 码(g))
g = 图()
g["nodes"].append({"id": "FE2", "type": "foreach", "container": "FE", "config": {
    "bindings": {"列表": 域("/当前项/明细")}, "item_output": 引("FE2x", "/x"), "item_failure_policy": "fail", "max_items": 5}})
g["nodes"].append({"id": "FE2x", "type": "transform", "container": "FE2", "config": {
    "operations": [{"op": "default", "from": 常(1), "value": 1, "into": "x"}], "output_schema": {"type": "object"}}})
g["edges"].append({"source": "FE2", "target": "FE2x", "port": "loop_body"})
ck("迭代里面放迭代 → FOREACH_NESTED", "FOREACH_NESTED" in 码(g), 1, 码(g))

print("▸ ⑥ 检查配置的其余几条")
ck("正常那张图(含接了失败出口、留空位、等人那几张):没有阻断",
   码(图()) == [] and 码(图(接失败=True)) == [] and 码(图(策略="continue")) == [] and 码(图(等人=True)) == [], 4,
   [码(图()), 码(图(接失败=True)), 码(图(等人=True))])


def 改(f):
    g = 图()
    f(g)
    return 码(g)


fe = lambda g: next(n for n in g["nodes"] if n["id"] == "FE")
wr = lambda g: next(n for n in g["nodes"] if n["id"] == "write")
ck("「列表」填了一个不是列表的固定值 → 只报 FOREACH_NOT_LIST",
   改(lambda g: fe(g)["config"]["bindings"].update(列表=常("abc"))) == ["FOREACH_NOT_LIST"], 1,
   改(lambda g: fe(g)["config"]["bindings"].update(列表=常("abc"))))
ck("「列表」选了一个声明成文字的输入 → 只报 FOREACH_NOT_LIST",
   改(lambda g: g["nodes"][0]["config"]["input_schema"]["properties"].update(单={"type": "string"})) == ["FOREACH_NOT_LIST"], 1,
   改(lambda g: g["nodes"][0]["config"]["input_schema"]["properties"].update(单={"type": "string"})))
ck("「列表」是手写的字符串 → 报 FOREACH_NOT_REF(和通用的「手写的」BIND_NOT_STRUCTURED)",
   改(lambda g: fe(g)["config"]["bindings"].update(列表="{{单}}")) == ["BIND_NOT_STRUCTURED", "FOREACH_NOT_REF"], 1,
   改(lambda g: fe(g)["config"]["bindings"].update(列表="{{单}}")))
ck("「列表」选了列表操作的「个数」→ FOREACH_NOT_LIST(按那一步固定的结果类型判)",
   "FOREACH_NOT_LIST" in 改(lambda g: (g["nodes"].insert(1, {"id": "lo", "type": "list_operator", "config": {
       "bindings": {"列表": {"source": "input", "pointer": "/单"}}}}),
       g["edges"].__setitem__(0, {"source": "start", "target": "lo", "port": "success"}),
       g["edges"].append({"source": "lo", "target": "FE", "port": "success"}),
       fe(g)["config"]["bindings"].update(列表=引("lo", "/个数")))), 1)


def 掏空(g):
    g["nodes"] = [n for n in g["nodes"] if n.get("container") != "FE"]
    g["edges"] = [e for e in g["edges"] if e["source"] not in ("FE", "num") or e["port"] == "loop_exit"]


ck("迭代里面一步都没有 → CONTAINER_EMPTY(交出的那一步也就不在了 → FOREACH_OUTPUT_NOT_FOUND)",
   改(掏空) == ["CONTAINER_EMPTY", "FOREACH_OUTPUT_NOT_FOUND"], 1, 改(掏空))
ck("里面取了迭代没给的变量(/当前 而不是 /当前项)→ 只报 FOREACH_SCOPE_UNKNOWN",
   改(lambda g: wr(g)["config"]["bindings"].update(名=域("/当前/名"))) == ["FOREACH_SCOPE_UNKNOWN"], 1,
   改(lambda g: wr(g)["config"]["bindings"].update(名=域("/当前/名"))))
ck("里面条件里取了迭代没给的变量 → 也报 FOREACH_SCOPE_UNKNOWN(不只查「用到的数据」)",
   "FOREACH_SCOPE_UNKNOWN" in 改(lambda g: g["nodes"].append({"id": "c", "type": "condition", "container": "FE", "config": {
       "branches": [{"key": "yes", "when": {"op": "exists", "left": 域("/项")}}], "else_policy": "end"}})), 1)
ck("里面取了被删掉的步骤 → BIND_NODE_NOT_FOUND",
   改(lambda g: wr(g)["config"]["bindings"].update(金额=引("没有这步", "/n"))) == ["BIND_NODE_NOT_FOUND"], 1,
   改(lambda g: wr(g)["config"]["bindings"].update(金额=引("没有这步", "/n"))))
ck("「每一项交出什么」选了迭代外面的步骤 → FOREACH_OUTPUT_NOT_INSIDE",
   "FOREACH_OUTPUT_NOT_INSIDE" in 改(lambda g: fe(g)["config"].update(item_output=引("start", "/单"))), 1)
ck("最多做几项 101 → 只报 FOREACH_MAX_RANGE;0 也报",
   改(lambda g: fe(g)["config"].update(max_items=101)) == ["FOREACH_MAX_RANGE"]
   and 改(lambda g: fe(g)["config"].update(max_items=0)) == ["FOREACH_MAX_RANGE"], 2)
ck("某一项失败时填了 Dify 的「去掉失败项」→ FOREACH_BAD_POLICY(规格不许删失败项)",
   改(lambda g: fe(g)["config"].update(item_failure_policy="remove")) == ["FOREACH_BAD_POLICY"], 1)
ck("里面取迭代自己的结果 → FOREACH_SELF_REF",
   "FOREACH_SELF_REF" in 改(lambda g: wr(g)["config"]["bindings"].update(全部=引("FE", "/结果"))), 1)
ck("变量赋值放进迭代 → ASSIGN_NOT_IN_LOOP(当前项 / 下标不是循环状态,不许改)",
   "ASSIGN_NOT_IN_LOOP" in 改(lambda g: g["nodes"].append({"id": "as", "type": "assigner", "container": "FE", "config": {
       "assignments": [{"variable": "当前项", "op": "clear"}]}})), 1)
ck("四项必填都没填 → 四条 NODE_MISSING_CONFIG,各指一个字段",
   sorted(p["field_path"] for p in V.校验((lambda g: (fe(g).__setitem__("config", {}), g)[1])(图()), 依赖存在=lambda 种类, i: True)
          if p["code"] == "NODE_MISSING_CONFIG") == ["config.bindings", "config.item_failure_policy", "config.item_output", "config.max_items"], 4)
ck("多带一项「用到的数据」→ FOREACH_EXTRA_BINDING",
   "FOREACH_EXTRA_BINDING" in 改(lambda g: fe(g)["config"]["bindings"].update(多余={"source": "input", "pointer": "/单"})), 1)
ck("迭代上填了「并发」→ NODE_UNKNOWN_CONFIG(一次一项,并发不是这里的设置)",
   "NODE_UNKNOWN_CONFIG" in 改(lambda g: fe(g)["config"].update(max_concurrency=4)), 1)

print("▸ ⑦ 运行记录截断")
多 = [{"名": f"X{i}", "金额": str(i)} for i in range(25)]
r, 计, 步们, _ = 跑(图(上限=30), 多)
fs = FE步(步们)
ck("25 项:这一步的记录逐项列前 20 项,并写明「还有 5 项」没列", fs and len(fs[0]["output"]["逐项"]) == 20
   and "还有 5 项" in fs[0]["output"].get("没列出", ""), 1, fs and fs[0]["output"].get("没列出"))
ck("截断的只是这一步的摘要:每一项里面「写」那一步 25 条都在,真结果 25 项一项不少",
   len([s for s in 步们 if s["node_id"] == "write"]) == 25 and len(r["输出"]["结果"]) == 25, 25)

print("▸ ⑧ 停在里面等人核对")
r, 计, 步们, 停时 = 跑(图(等人=True), 三项, 恢复决定=["approve"] * 3)
ck("停了 3 次,依次停在第 1、2、3 项,停时已收的结果依次是 []、[A#0]、[A#0, B#1]",
   停时 == [(1, []), (2, ["A#0"]), (3, ["A#0", "B#1"])], 3, 停时)
ck("恢复完:成功、结果 [A#0, B#1, C#2]、模型 3 次(恢复不重跑做完的项)",
   r["执行状态"] == "succeeded" and r["输出"]["结果"] == ["A#0", "B#1", "C#2"] and 计["n"] == 3, 1,
   (r["执行状态"], r["输出"], 计["n"]))

print("▸ ⑨ 预算")
r, 计, 步们, _ = 跑(图(), 三项, 上限={"max_model_turns": 2})
ck("整次最多 2 次模型调用,3 项 → 第 3 项被拦成受限停止 incomplete/max_turns,模型正好 2 次",
   r["执行状态"] == "incomplete" and r["完成原因"] == "max_turns" and 计["n"] == 2, 1, (r["执行状态"], r["完成原因"], 计["n"]))

print("▸ ⑩ 执行器第二道")
r, 计, 步们, _ = 跑(图(), "不是列表")
ck("运行时拿到的不是列表 → 失败 FOREACH_NOT_LIST,模型 0 次", r["执行状态"] == "failed"
   and r["完成原因"] == "FOREACH_NOT_LIST" and 计["n"] == 0, 1, (r["执行状态"], r["完成原因"]))

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
