#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""子工作流(11-16 三期 3-3 一期:只引冻结版、静态禁递归、深度上限、预算随父、子流程里同步跑完;规格 §6.1 / §13.2)。

## 判据(期望的结果和次数都是手写的;模型调用次数由 mock 那一侧数,不由执行器自报)

  ① 正常:父流程一步「子工作流」引一版子流程(开始 → 模型 → 结束),交给它 sku,拿回它「最后返回什么」;
     子流程里那次模型调用**计入父流程用量**;这一步的输出带「子流程步骤」摘要;父流程的结束能取子流程返回的字段
  ② 预算随父:父流程最多 1 次模型调用、子流程要调 2 次 → 子流程受限停止 → 这一步失败 SUBWORKFLOW_FAILED(不冒充成功);
     这一步配的上限比父流程还剩的更严时,按这一步的
  ③ 子流程里一步失败 → 这一步 SUBWORKFLOW_FAILED,输出里的摘要点出哪一步、什么码
  ④ 子流程里停下等人 → 这一步 SUBWORKFLOW_WAIT_UNSUPPORTED(运行时第二道;静态第一道在 ⑥)
  ⑤ 动态深度:第 4 层拦 SUBWORKFLOW_TOO_DEEP
  ⑥ 检查配置(给校验器一个会「取版本」的依赖查询):绕回本流程 / 链上同一条流程两次 → RECURSION;套 4 层 → TOO_DEEP;
     子流程里有人工核对 / Agent / 写数据的动作 → WAIT_UNSUPPORTED;子流程要的输入没给 → INPUT_MISSING;多给的 → 警告 INPUT_UNKNOWN;
     上限形状 / 范围 / 不认识的键;这一步上限超父流程 → SUB_LIMIT_EXCEEDS_PARENT(⑦ 已有);没有「取版本」能力时报告里写「没查」;正常那张图没有阻断
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
import 子工作流 as SW  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:280] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


def 引(n, p):
    return {"source": "node", "node_id": n, "pointer": p}


输 = lambda p: {"source": "input", "pointer": p}
文本 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
子出 = {"type": "object", "properties": {"答": {"type": "string"}}, "required": ["答"], "additionalProperties": False}
子入 = {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}


def 子流程定义(*, 调几次=1, 等人=False, 写工具=False):
    """开始(sku)→ 模型 ×调几次 (→ 人工核对)→ 结束(答 = 最后一次模型的 text)。"""
    nodes = [{"id": "s", "type": "start", "config": {"input_schema": 子入}}]
    edges = []
    上 = "s"
    for k in range(调几次):
        nodes.append({"id": f"m{k}", "type": "llm", "config": {"connection_version_id": "cv1", "prompt_version_id": "p1", "output_schema": 文本,
                                                              "bindings": {"问": 输("/sku")}}})
        edges.append({"source": 上, "target": f"m{k}", "port": "success"})
        上 = f"m{k}"
    if 等人:
        nodes.append({"id": "rv", "type": "human", "config": {"request_kind": "核对", "candidate_roles": ["审核人"], "expires_at_policy": {"小时": 48, "到期": "fail"},
                                                             "payload_binding": {"稿": 引(上, "/text")}}})
        edges.append({"source": 上, "target": "rv", "port": "success"})
        上 = "rv"
    if 写工具:
        nodes.append({"id": "wr", "type": "tool", "config": {"tool_version_id": "tv_write", "bindings": {}}})
        edges.append({"source": 上, "target": "wr", "port": "success"})
        上 = "wr"
    nodes.append({"id": "e", "type": "end", "config": {"output_schema": 子出, "bindings": {"答": 引(f"m{调几次 - 1}", "/text")}}})
    edges.append({"source": 上, "target": "e", "port": "success"})
    return {"definition_schema_version": "1", "kind": "workflow", "input_schema": 子入, "output_schema": 子出, "nodes": nodes, "edges": edges}


父出 = {"type": "object", "properties": {"结论": {"type": "string"}}, "required": ["结论"], "additionalProperties": False}


def 父图(*, 版本="wv_child", 映射=None, 上限=None):
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 父出, "nodes": [
        {"id": "start", "type": "start", "config": {"input_schema": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}}},
        {"id": "sub", "type": "subworkflow", "config": {"workflow_version_id": 版本, "input_mapping": 映射 if 映射 is not None else {"sku": 输("/sku")},
                                                      **({"sub_limits": 上限} if 上限 else {})}},
        {"id": "end", "type": "end", "config": {"output_schema": 父出, "bindings": {"结论": 引("sub", "/答")}}}],
        "edges": [{"source": "start", "target": "sub", "port": "success"}, {"source": "sub", "target": "end", "port": "success"}]}


# ── 假「版本库」+ 假 worker 适配器(照 workers/worker.py 的 _subworkflow 形状:同步跑、合上限、拦等待、折摘要)───────
版本库 = {}


def 假子流程适配器(计, 适配器们):
    def fn(cfg, 包):
        深 = int(包.get("深度") or 1)
        if 深 > SW.深度上限:
            raise RN.节点失败("SUBWORKFLOW_TOO_DEEP", f"子流程套到第 {深} 层了", "少套一层")
        v = 版本库.get(cfg.get("workflow_version_id"))
        if not v:
            raise RN.节点失败("SUBWORKFLOW_VERSION_NOT_FOUND", "找不到", "重选")
        计划 = CP.编译(v["定义"], 依赖存在=lambda 种类, i: True)
        子上限 = SW.合上限(cfg.get("sub_limits"), 包.get("父流程剩余"))
        子 = RN.跑一张图(计划, 包.get("输入") or {}, 适配器=适配器们, run_id=f"r/{包.get('node_id')}", 上限=子上限,
                       系统={"子流程深度": 深})
        摘要 = SW.步骤摘要(子.get("步骤") or [])
        if 子.get("检查点"):
            e = RN.节点失败("SUBWORKFLOW_WAIT_UNSUPPORTED", "子流程要停下等", "挪出来"); e.出 = 摘要; raise e
        if 子.get("执行状态") != "succeeded":
            码 = str(子.get("完成原因") or "")
            e = RN.节点失败(码 if 码.startswith("SUBWORKFLOW_") else "SUBWORKFLOW_FAILED",     # 更深一层的原码往上传(和 worker 同一条)
                          f"子流程没跑成(停在「{码 or 子.get('执行状态')}」)", "看摘要"); e.出 = 摘要; raise e
        return {"输出": 子.get("输出") or {}, "本段用量": 子.get("用量") or {}, **摘要}
    return fn


def 跑(父, *, 上限=None, 坏第几次=None):
    计 = {"n": 0}

    def 模型(cfg, 实参):
        计["n"] += 1
        if 坏第几次 == 计["n"]:
            raise RN.节点失败("MODEL_BROKE", "模型坏了", "再试")
        return {"text": f"答{计['n']}:{实参.get('问')}"}
    适配器们 = {"llm": 模型}
    适配器们["subworkflow"] = 假子流程适配器(计, 适配器们)
    计划 = CP.编译(父, 依赖存在=lambda 种类, i: True)
    r = RN.跑一张图(计划, {"sku": "A1"}, 适配器=适配器们, run_id="r", 上限=上限)
    return r, 计


版本库["wv_child"] = {"workflow_id": "wf_child", "定义": 子流程定义()}
版本库["wv_child2"] = {"workflow_id": "wf_child", "定义": 子流程定义(调几次=2)}
版本库["wv_wait"] = {"workflow_id": "wf_wait", "定义": 子流程定义(等人=True)}

print("▸ ① 正常:子流程跑完,输出交回,用量计入父流程")
r, 计 = 跑(父图())
sub步 = [s for s in r["步骤"] if s["node_id"] == "sub"]
ck("父流程成功,结束拿到子流程返回的「答」", r["执行状态"] == "succeeded" and (r.get("输出") or {}).get("结论") == "答1:A1", 1, (r["执行状态"], r.get("输出")))
ck("子流程里那 1 次模型调用计入父流程用量", r["用量"]["模型调用"] == 1 and 计["n"] == 1, 1, r["用量"])
ck("子工作流这一步记成功,输出里带子流程步骤摘要(开始 / 模型 / 结束三步)",
   sub步 and sub步[0]["status"] == "succeeded" and sub步[0]["output"].get("子流程步数") == 3
   and [x["步骤"] for x in sub步[0]["output"]["子流程步骤"]] == ["s", "m0", "e"], len(sub步), sub步 and sub步[0].get("output"))

print("\n▸ ② 预算随父")
r, 计 = 跑(父图(版本="wv_child2"), 上限={"max_model_turns": 1})
ck("父流程只许 1 次模型、子流程要 2 次 → 子流程受限停止,这一步 SUBWORKFLOW_FAILED,整次失败、模型只调了 1 次",
   r["执行状态"] == "failed" and r.get("完成原因") == "SUBWORKFLOW_FAILED" and 计["n"] == 1, 1, (r["执行状态"], r.get("完成原因"), 计["n"]))
r, 计 = 跑(父图(版本="wv_child2", 上限={"max_model_turns": 1}), 上限={"max_model_turns": 10})
ck("这一步自己配的上限(1)比父流程还剩的(10)更严 → 按 1 算,照样拦", r["执行状态"] == "failed" and 计["n"] == 1, 1, (r["执行状态"], 计["n"]))
ck("合上限:取两者更严的;只有一边有就用那一边", SW.合上限({"max_model_turns": 3}, {"max_model_turns": 5, "max_tool_calls": 2}) == {"max_model_turns": 3, "max_tool_calls": 2}
   and SW.合上限(None, {"max_model_turns": 4}) == {"max_model_turns": 4}, 2)

print("\n▸ ③ 子流程里一步失败")
r, 计 = 跑(父图(), 坏第几次=1)
sub步 = [s for s in r["步骤"] if s["node_id"] == "sub"]
ck("这一步 SUBWORKFLOW_FAILED;输出摘要里点出子流程的 m0 失败、码 MODEL_BROKE",
   r.get("完成原因") == "SUBWORKFLOW_FAILED" and sub步 and any(x["步骤"] == "m0" and x["状态"] == "failed" and x.get("错误码") == "MODEL_BROKE"
                                                         for x in (sub步[0].get("output") or {}).get("子流程步骤", [])), 1, (r.get("完成原因"), sub步 and sub步[0].get("output")))

print("\n▸ ④ 子流程里停下等人(运行时第二道)")
r, 计 = 跑(父图(版本="wv_wait"))
ck("子流程停在人工核对 → 这一步 SUBWORKFLOW_WAIT_UNSUPPORTED,整次失败、不是挂起", r["执行状态"] == "failed" and r.get("完成原因") == "SUBWORKFLOW_WAIT_UNSUPPORTED"
   and not r.get("检查点"), 1, (r["执行状态"], r.get("完成原因")))

print("\n▸ ⑤ 动态深度(嵌套层数:子 1 / 孙 2 / 曾孙 3 可以;第 4 层拦)")
_入 = {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}


def 包一层(引谁, 取什么):
    """一版「开始 → 子工作流(引谁) → 结束(结论 = 子流程的 取什么)」的子流程,能再被别人引。"""
    g = dict(父图(版本=引谁), input_schema=_入, output_schema=父出)
    g["nodes"][2]["config"]["bindings"] = {"结论": 引("sub", 取什么)}
    return g


版本库["wv_l3"] = {"workflow_id": "wf_l3", "定义": 子流程定义()}               # 最里面:返回「答」
版本库["wv_l2"] = {"workflow_id": "wf_l2", "定义": 包一层("wv_l3", "/答")}
版本库["wv_l1"] = {"workflow_id": "wf_l1", "定义": 包一层("wv_l2", "/结论")}
版本库["wv_l0"] = {"workflow_id": "wf_l0", "定义": 包一层("wv_l1", "/结论")}
父3 = 父图(版本="wv_l1"); 父3["nodes"][2]["config"]["bindings"] = {"结论": 引("sub", "/结论")}    # 父 → l1 → l2 → l3:三层,可以
父4 = 父图(版本="wv_l0"); 父4["nodes"][2]["config"]["bindings"] = {"结论": 引("sub", "/结论")}    # 父 → l0 → l1 → l2 → l3:四层,拦
r3, _ = 跑(父3)
r4, _ = 跑(父4)
ck("三层(子 / 孙 / 曾孙)跑得通,最里面的「答」一层层交回来;第四层拦 SUBWORKFLOW_TOO_DEEP",
   r3["执行状态"] == "succeeded" and (r3.get("输出") or {}).get("结论") == "答1:A1" and r4["执行状态"] == "failed" and r4.get("完成原因") == "SUBWORKFLOW_TOO_DEEP",
   2, (r3["执行状态"], r3.get("输出"), r4["执行状态"], r4.get("完成原因")))

print("\n▸ ⑥ 检查配置")


def 依赖(本工作流="wf_parent", 工具读写=None):
    f = lambda 种类, i: True
    f.取版本 = lambda vid: ({"workflow_id": 版本库[vid]["workflow_id"], **版本库[vid]["定义"]} if vid in 版本库 else None)
    f.工具读写 = 工具读写 or (lambda tv: "write" if tv == "tv_write" else "read_only")
    f.本工作流 = 本工作流
    return f


阻 = lambda g, 依=None, 父额度=None: sorted({p["code"] for p in V.校验(g, 依赖存在=依 or 依赖(), 父额度=父额度) if p["级别"] == V.阻断})
警 = lambda g, 依=None: sorted({p["code"] for p in V.校验(g, 依赖存在=依 or 依赖()) if p["级别"] == V.警告})
ck("正常那张图没有阻断(正向对照)", 阻(父图()) == [], 1, 阻(父图()))
版本库["wv_back"] = {"workflow_id": "wf_parent", "定义": 子流程定义()}                 # 引的那一版属于本流程自己
版本库["wv_loop_a"] = {"workflow_id": "wf_a", "定义": 父图(版本="wv_loop_b")}
版本库["wv_loop_b"] = {"workflow_id": "wf_b", "定义": 父图(版本="wv_loop_a2")}
版本库["wv_loop_a2"] = {"workflow_id": "wf_a", "定义": 子流程定义()}                   # a → b → a 的另一版:链上同一条流程出现两次
版本库["wv_wr"] = {"workflow_id": "wf_wr", "定义": 子流程定义(写工具=True)}
坏们 = {
    "绕回本流程": 阻(父图(版本="wv_back")),
    "链上同一条流程两次": 阻(父图(版本="wv_loop_a")),
    "套四层": 阻(父图(版本="wv_l0")),
    "子流程里有人工核对": 阻(父图(版本="wv_wait")),
    "子流程里有写数据的动作": 阻(父图(版本="wv_wr")),
    "子流程要的输入没给": 阻(父图(映射={})),
    "上限不是整数": 阻(父图(上限={"max_model_turns": "三"})),
    "上限键不认识": 阻(父图(上限={"max_steps": 3})),
    "这一步上限超父流程": 阻(父图(上限={"max_model_turns": 9}), 父额度={"max_model_turns": 5}),
}
期望 = {"绕回本流程": "SUBWORKFLOW_RECURSION", "链上同一条流程两次": "SUBWORKFLOW_RECURSION", "套四层": "SUBWORKFLOW_TOO_DEEP",
      "子流程里有人工核对": "SUBWORKFLOW_WAIT_UNSUPPORTED", "子流程里有写数据的动作": "SUBWORKFLOW_WAIT_UNSUPPORTED",
      "子流程要的输入没给": "SUBWORKFLOW_INPUT_MISSING", "上限不是整数": "SUBWORKFLOW_LIMIT_RANGE", "上限键不认识": "SUBWORKFLOW_LIMIT_UNKNOWN",
      "这一步上限超父流程": "SUB_LIMIT_EXCEEDS_PARENT"}
漏 = {k: (期望[k], v) for k, v in 坏们.items() if 期望[k] not in v}
ck("九种配坏法各自报出指定的阻断码(递归 / 深度 / 等人 / 输入 / 上限)", not 漏, len(坏们), 漏)
ck("多给了子流程不收的输入 → 警告 SUBWORKFLOW_INPUT_UNKNOWN(不阻断)", "SUBWORKFLOW_INPUT_UNKNOWN" in 警(父图(映射={"sku": 输("/sku"), "多的": 输("/sku")}))
   and "SUBWORKFLOW_INPUT_UNKNOWN" not in 阻(父图(映射={"sku": 输("/sku"), "多的": 输("/sku")})), 1)
没查 = [p for p in V.校验(父图(), 依赖存在=lambda 种类, i: True) if p.get("code") == "CHECK_SKIPPED" and "子流程" in p.get("消息", "")]
ck("没有「取版本」能力时,报告里以 CHECK_SKIPPED 写明子流程那几条**没查**(警告级,不冒充通过)", len(没查) == 1 and 没查[0]["级别"] == V.警告, len(没查), 没查)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
