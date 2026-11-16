#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并行与汇总(11-16 三期 3-2 一期:语义先立住、串行实现;规格 §6.1 / §6.3「并行」)。

## 判据(期望的结果和次数都是手写的;模型调用次数由 mock 那一侧数,不由执行器自报)

  ① 正常:两条支路各调一次模型,结果按支路键存({"结果": {查库存: …, 查物流: …}, "状态": 两个 succeeded, "失败支路": []});
     结束从并行的「结果」里取;串行(第二条开始前第一条已经做完);每条支路的步骤都记在运行记录里;并行自己记一步,输入里列着支路
  ② 必需支路失败(默认 all_required):第一条失败 → 第二条不做(模型只 1 次),并行这一步记 PARALLEL_BRANCH_FAILED、错误里点名那条支路;
     接了并行的「失败时」出口就走那条线
  ③ 允许部分结果(allow_partial):第一条失败 → 第二条照做,整步成功,结果里失败那条是 null、状态 failed、失败支路记着哪一步为什么
  ④ 非必需支路失败 + all_required:不拦,整步成功、状态 failed
  ⑤ 停在支路里等人核对:检查点记着第几条支路和已收的结果;恢复后接着做,最后两条结果都在
  ⑥ 检查配置:支路没名字 / 重名 / 全不必需 / 并发上限不是 1 / 等待策略不认识 / 支路没连线 / 连线的支路配置里没有 /
     支路连到并行外面 / 一个步骤同时连在两条支路后面 / 跨支路取结果 / 并行套循环 / 循环套并行;正常那张图没有阻断(正向对照)
  ⑦ 下游能按声明的类型选并行的 结果(object)/ 状态(object)/ 失败支路(array)
"""
import copy
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402
import validator as V  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:260] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


def 引(n, p):
    return {"source": "node", "node_id": n, "pointer": p}


输 = lambda p: {"source": "input", "pointer": p}
文本 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
出 = {"type": "object", "properties": {"汇": {"type": "object"}, "态": {"type": "object"}}, "required": ["汇"], "additionalProperties": False}


def 图(*, 等待="all_required", 必需=(True, True), 接失败=False, 等人=False):
    """开始(sku)→ 并行 PA { 支路 查库存: llm a ; 支路 查物流: llm b (→ 人工核对 review) } → 结束(汇 = 并行.结果, 态 = 并行.状态)。"""
    nodes = [
        {"id": "start", "type": "start", "config": {"input_schema": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}}},
        {"id": "PA", "type": "parallel", "config": {"branches": [{"key": "查库存", "required": 必需[0]}, {"key": "查物流", "required": 必需[1]}],
                                                    "max_concurrency": 1, "wait_policy": 等待}},
        {"id": "a", "type": "llm", "container": "PA", "config": {"connection_version_id": "cv1", "prompt_version_id": "p1", "output_schema": 文本,
                                                                  "bindings": {"问": 输("/sku"), "哪条": {"source": "constant", "value": "库存"}}}},
        {"id": "b", "type": "llm", "container": "PA", "config": {"connection_version_id": "cv1", "prompt_version_id": "p1", "output_schema": 文本,
                                                                  "bindings": {"问": 输("/sku"), "哪条": {"source": "constant", "value": "物流"}}}},
        {"id": "end", "type": "end", "config": {"output_schema": 出, "bindings": {"汇": 引("PA", "/结果"), "态": 引("PA", "/状态")}}},
    ]
    edges = [
        {"source": "start", "target": "PA", "port": "success"},
        {"source": "PA", "target": "a", "port": "parallel", "branch_key": "查库存"},
        {"source": "PA", "target": "b", "port": "parallel", "branch_key": "查物流"},
        {"source": "PA", "target": "end", "port": "success"},
    ]
    if 等人:
        nodes.insert(4, {"id": "review", "type": "human", "container": "PA", "config": {
            "request_kind": "核对", "candidate_roles": ["审核人"], "expires_at_policy": {"小时": 48, "到期": "fail"},
            "payload_binding": {"稿": 引("b", "/text")}}})
        edges.append({"source": "b", "target": "review", "port": "success"})
    if 接失败:
        nodes[1]["config"]["failure_policy"] = "branch"
        nodes.append({"id": "人工", "type": "answer", "config": {"template": "交人工处理"}})
        edges.append({"source": "PA", "target": "人工", "port": "error"})
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出, "nodes": nodes, "edges": edges}


def 跑(g, *, 坏哪条=None, 恢复决定=()):
    计 = {"n": 0, "收到": []}

    def 模型(cfg, 实参):
        计["n"] += 1
        计["收到"].append(实参["哪条"])
        if 实参["哪条"] == 坏哪条:
            raise RN.节点失败("MODEL_BROKE", "模型这次坏了", "再试")
        return {"text": f"{实参['哪条']}:{实参['问']}"}
    计划 = CP.编译(g, 依赖存在=lambda 种类, i: True)
    r = RN.跑一张图(计划, {"sku": "A1"}, 适配器={"llm": 模型}, run_id="r")
    步们, 停时 = list(r["步骤"]), []
    for 决 in 恢复决定:
        if not r.get("检查点"):
            break
        帧 = (r["检查点"].get("循环帧") or [{}])[-1]
        停时.append((帧.get("第几轮"), dict(帧.get("结果") or {})))
        r = RN.跑一张图(计划, {"sku": "A1"}, 适配器={"llm": 模型}, run_id="r", 恢复=dict(r["检查点"], 结果={"决定": 决, "定稿": "x"}))
        步们 += r["步骤"]
    return r, 计, 步们, 停时


PA步 = lambda 步们: [s for s in 步们 if s["node_id"] == "PA"]

print("▸ ① 正常:两条支路各跑一次,结果按支路键存")
r, 计, 步们, _ = 跑(图())
汇 = (r.get("输出") or {}).get("汇") or {}
ck("成功;结束拿到按支路键存的结果和状态", r["执行状态"] == "succeeded" and 汇 == {"查库存": {"text": "库存:A1"}, "查物流": {"text": "物流:A1"}}
   and (r.get("输出") or {}).get("态") == {"查库存": "succeeded", "查物流": "succeeded"}, 1, (r["执行状态"], r.get("输出")))
ck("模型正好 2 次,先库存再物流(串行、按支路顺序)", 计["n"] == 2 and 计["收到"] == ["库存", "物流"], 计["n"], 计)
ck("并行自己记一步:成功、输入里列着两条支路、输出里失败支路为空",
   len(PA步(步们)) == 1 and PA步(步们)[0]["status"] == "succeeded" and PA步(步们)[0].get("input", {}).get("支路") == ["查库存", "查物流"]
   and PA步(步们)[0].get("output", {}).get("失败支路") == [], len(PA步(步们)), PA步(步们))
顺序 = [s["node_id"] for s in 步们]
ck("串行:a 做完才做 b,并行最后才记成功", 顺序.index("a") < 顺序.index("b") < 顺序.index("PA"), len(顺序), 顺序)

print("\n▸ ② 必需支路失败(默认等全部必需):整步失败、第二条不做")
r, 计, 步们, _ = 跑(图(), 坏哪条="库存")
ck("整次失败、完成原因 PARALLEL_BRANCH_FAILED,模型只 1 次(第二条没做)",
   r["执行状态"] == "failed" and r.get("完成原因") == "PARALLEL_BRANCH_FAILED" and 计["n"] == 1, 1, (r["执行状态"], r.get("完成原因"), 计["n"]))
fs = [s for s in PA步(步们) if s["status"] == "failed"]
ck("并行这一步记失败,错误里点名「查库存」和原来的原因", fs and "查库存" in fs[0]["error_detail"]["消息"] and "模型这次坏了" in fs[0]["error_detail"]["消息"], len(fs), fs)
r, 计, 步们, _ = 跑(图(接失败=True), 坏哪条="库存")
ck("接了并行的「失败时」出口 → 走那条线(人工那一步跑了),并行这一步记失败、不是整次直接失败",
   "人工" in r["走过的路径"] and [s["status"] for s in PA步(步们)] == ["failed"] and r["执行状态"] != "failed", 1, (r["走过的路径"], r["执行状态"]))

print("\n▸ ③ 允许部分结果:失败的支路留空、状态记 failed,其余照做")
r, 计, 步们, _ = 跑(图(等待="allow_partial"), 坏哪条="库存")
汇 = (r.get("输出") or {}).get("汇") or {}
ck("整步成功、模型 2 次;结果里库存是空(null)、物流在;状态 failed / succeeded",
   r["执行状态"] == "succeeded" and 计["n"] == 2 and 汇.get("查库存") is None and 汇.get("查物流") == {"text": "物流:A1"}
   and (r.get("输出") or {}).get("态") == {"查库存": "failed", "查物流": "succeeded"}, 1, (r["执行状态"], 计["n"], r.get("输出")))
ck("失败支路记着:哪条、哪一步、原因码", PA步(步们) and PA步(步们)[-1]["output"]["失败支路"] == [{"支路": "查库存", "步骤": "a", "code": "MODEL_BROKE", "消息": "模型这次坏了"}],
   1, PA步(步们) and PA步(步们)[-1]["output"])

print("\n▸ ④ 非必需支路失败 + 等全部必需:不拦")
r, 计, 步们, _ = 跑(图(必需=(False, True)), 坏哪条="库存")
ck("可选支路失败不拖垮整步:成功、状态里它是 failed", r["执行状态"] == "succeeded" and (r.get("输出") or {}).get("态") == {"查库存": "failed", "查物流": "succeeded"}, 1, r.get("输出"))

print("\n▸ ⑤ 停在支路里等人核对,恢复后接着做")
r, 计, 步们, 停时 = 跑(图(等人=True), 恢复决定=("approve",))
ck("第一次跑停在人工核对(第二条支路里),检查点里第一条支路的结果已经收了", 停时 and 停时[0][0] == 2 and 停时[0][1].get("查库存") == {"text": "库存:A1"}, len(停时), 停时)
ck("恢复后整次成功、两条结果都在(第二条支路最后一步是人工核对,交出的就是核对结论)、模型总共 2 次(没重跑第一条)",
   r["执行状态"] == "succeeded" and (r.get("输出") or {}).get("汇", {}).get("查物流", {}).get("决定") == "approve"
   and (r.get("输出") or {}).get("汇", {}).get("查库存") == {"text": "库存:A1"} and 计["n"] == 2, 1, (r["执行状态"], 计["n"], r.get("输出")))

print("\n▸ ⑥ 检查配置")
好 = 图()
阻 = lambda g: sorted({p["code"] for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断})
ck("正常那张图没有阻断(正向对照)", 阻(好) == [], 1, 阻(好))


def 改(fn):
    g = copy.deepcopy(好)
    fn(g)
    return 阻(g)


def 配(g):
    return g["nodes"][1]["config"]


坏们 = {
    "支路没名字": 改(lambda g: 配(g)["branches"].append({"required": True})),
    "重名": 改(lambda g: 配(g)["branches"].append({"key": "查库存"})),
    "全不必需": 改(lambda g: [b.update(required=False) for b in 配(g)["branches"]]),
    "并发不是 1": 改(lambda g: 配(g).update(max_concurrency=4)),
    "等待策略不认识": 改(lambda g: 配(g).update(wait_policy="first")),
    "支路没连线": 改(lambda g: g["edges"].pop(2)),
    "连线的支路配置里没有": 改(lambda g: g["edges"].append({"source": "PA", "target": "b", "port": "parallel", "branch_key": "查天气"})),
    "支路连到外面": 改(lambda g: g["nodes"][3].pop("container")),
    "一个步骤两条支路都连": 改(lambda g: g["edges"].append({"source": "a", "target": "b", "port": "success"})),
    "跨支路取结果": 改(lambda g: g["nodes"][3]["config"]["bindings"].update(别人=引("a", "/text"))),
    "并行里套迭代": 改(lambda g: g["nodes"].insert(4, {"id": "fe", "type": "foreach", "container": "PA", "config": {"bindings": {}, "item_failure_policy": "fail", "max_items": 2}})),
    "并行放进循环里": 改(lambda g: (g["nodes"].append({"id": "lp", "type": "loop", "config": {"max_iterations": 2, "condition": {"op": "equals", "left": {"source": "constant", "value": True}, "right": {"source": "constant", "value": True}}, "loop_state": {}}}),
                                   g["nodes"][1].update(container="lp"), g["edges"].insert(1, {"source": "lp", "target": "PA", "port": "loop_body"}),
                                   g["edges"].__setitem__(0, {"source": "start", "target": "lp", "port": "success"}))),
}
期望 = {
    "支路没名字": "PARALLEL_BRANCH_NO_KEY", "重名": "PARALLEL_BRANCH_DUP", "全不必需": "PARALLEL_NO_REQUIRED",
    "并发不是 1": "PARALLEL_CONCURRENCY_UNSUPPORTED", "等待策略不认识": "PARALLEL_BAD_WAIT_POLICY",
    "支路没连线": "PARALLEL_BRANCH_NO_EDGE", "连线的支路配置里没有": "PARALLEL_EDGE_NO_BRANCH",
    "支路连到外面": "PARALLEL_BRANCH_NOT_INSIDE", "一个步骤两条支路都连": "PARALLEL_BRANCH_SHARED",
    "跨支路取结果": "PARALLEL_CROSS_BRANCH", "并行里套迭代": "PARALLEL_NESTED", "并行放进循环里": "PARALLEL_NESTED",
}
漏 = {k: (期望[k], v) for k, v in 坏们.items() if 期望[k] not in v}
ck("十二种配坏法各自报出指定的阻断码", not 漏, len(坏们), 漏)

print("\n▸ ⑦ 下游按声明的类型取")
ck("并行的 结果 / 状态 声明成对象、失败支路 声明成列表(下游「列表迭代」选它时能判对不对)",
   V._声明类型(引("PA", "/失败支路"), {n["id"]: n for n in 好["nodes"]}) == "array" and V._声明类型(引("PA", "/结果"), {n["id"]: n for n in 好["nodes"]}) == "object", 2)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
