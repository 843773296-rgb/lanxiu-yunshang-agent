#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单步测试拼小图(10-26)—— 只跑草稿里的某一步。

判据的两头:
  · 「能跑」靠**真校验 + 真编译 + 真执行器**跑一遍拼出来的小图(不是看小图长得对不对);
    模型收到了什么,取**脚本模型自己记下的入参**,不取执行器自报
  · 「不能跑」的每一类都要拦,**写入类业务动作拦的理由要连着说清**(拦了但说不清为什么,人会去找别的办法绕过去)
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402
import validator as V  # noqa: E402
import 单步测试 as ST1  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:190] if 补 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        挂.append(名 + "(样本量 0)")


# 一张手写的草稿:取录音 → 提取需求(模型,读取录音的结果 + 一个固定值)→ 写跟进 → 核对 …
草稿 = {
    "definition_schema_version": "1", "kind": "workflow",
    "input_schema": {"type": "object", "properties": {"call_id": {"type": "string"}}, "required": ["call_id"]},
    "output_schema": {"type": "object", "properties": {}, "required": []},
    "nodes": [
        {"id": "s", "type": "start", "config": {"input_schema": {"type": "object",
            "properties": {"call_id": {"type": "string"}}, "required": ["call_id"]}}},
        {"id": "fetch", "type": "tool", "name": "取转写", "config": {"tool_version_id": "tv_read",
            "bindings": {"call_id": {"source": "input", "pointer": "/call_id"}}}},
        {"id": "extract", "type": "llm", "name": "提取需求", "config": {
            "connection_version_id": "cv", "prompt_version_id": "pv",
            "output_schema": {"type": "object", "properties": {"需求": {"type": "string"}}, "required": ["需求"]},
            "bindings": {"原文": {"source": "node", "node_id": "fetch", "pointer": "/text"},
                         "语气": {"source": "constant", "value": "简洁"}}}},
        {"id": "save", "type": "tool", "name": "写跟进", "config": {"tool_version_id": "tv_write",
            "bindings": {"内容": {"source": "node", "node_id": "extract", "pointer": "/需求"}}}},
        {"id": "review", "type": "human", "config": {"request_kind": "核对", "candidate_roles": ["审核人"],
            "expires_at_policy": {"小时": 48, "到期": "fail"}}},
        {"id": "e", "type": "end", "config": {"output_schema": {"type": "object"}}},
    ],
    "edges": [],
}
读写 = {"tv_read": "read_only", "tv_write": "write"}.get

print("▸ 能单测的那一步:拼出来的小图**真过校验、真编译、真跑通**")
小图, 要填 = ST1.拼小图(草稿, "extract", 工具读写=读写)
ck("要填的只有「来自前面步骤 / 使用者输入」的那几项;固定值照旧,不让人填", 要填 == ["原文"], 1, 要填)
阻 = [p for p in V.校验(小图, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断]
ck("小图过服务端校验(一条阻断都没有)", not 阻, 1, [(p["code"], p["消息"]) for p in 阻])
计划 = CP.编译(小图, 依赖存在=lambda 种类, i: True)
收到 = []


def 模型(cfg, 实参):
    收到.append(实参)
    return {"需求": "宋制褙子,预算三千", "execution_mode": "mock"}


r = RN.跑一张图(计划, {"原文": "顾客想做一套宋制褙子"}, 适配器={"llm": 模型}, run_id="st")
ck("跑完是成功(结束不映射字段,所以不会因为「取不到结果」怪到这一步头上)", r["执行状态"] == "succeeded", 1, r["执行状态"])
ck("**模型实际收到的 = 填的那一项 + 原来的固定值**(取模型那一侧的记录)",
   收到 == [{"原文": "顾客想做一套宋制褙子", "语气": "简洁"}], len(收到), 收到)
步 = [s for s in r["步骤"] if s["kind"] == "llm"]
ck("这一步的 id 没变(运行详情、步骤标记、「上次试运行」才认得它)",
   [s["node_id"] for s in 步] == ["extract"], len(步), [s["node_id"] for s in 步])
ck("这一步的输出照常记下(单测的结果就看它)", 步 and 步[0].get("output", {}).get("需求") == "宋制褙子,预算三千", len(步))
ck("只跑了这一步:前面的「取转写」、后面的「写跟进」都不在这次运行里",
   not {"fetch", "save", "review"} & {s["node_id"] for s in r["步骤"]}, len(r["步骤"]),
   [s["node_id"] for s in r["步骤"]])
ck("原草稿没被改动(拼小图是在副本上改绑定)",
   草稿["nodes"][2]["config"]["bindings"]["原文"]["source"] == "node", 1)

print("\n▸ 只读的业务动作能单测")
小2, 要填2 = ST1.拼小图(草稿, "fetch", 工具读写=读写)
ck("只读动作拼得出来,要填的是它的入参", 要填2 == ["call_id"], 1, 要填2)

print("\n▸ 不能单测的,拦住并说清为什么")
拦 = {}
for nid, 读法 in (("save", 读写), ("fetch", lambda tv: None), ("review", 读写), ("s", 读写), ("e", 读写),
                 ("不存在", 读写)):
    try:
        ST1.拼小图(草稿, nid, 工具读写=读法)
        拦[nid] = None
    except ST1.不能单测 as e:
        拦[nid] = e
ck("写入类业务动作、读写不明的动作、人工核对、开始、结束、不存在的步骤 —— 全部拦住",
   all(拦.values()), len(拦), [k for k, v in 拦.items() if v is None])
ck("**写入类拦的理由说清了后果**(会跳过人工核对、写出没人核对过的真实记录)",
   拦["save"] and "人工核对" in 拦["save"].消息 and "真实记录" in 拦["save"].消息, 1, 拦["save"] and 拦["save"].消息)
ck("读写不明的按写入处理(偏错的代价朝「少测一次」,不朝「多写一条真记录」),**并照实说是「不知道」**,不冒充「会写数据」",
   拦["fetch"] is not None and "不知道" in 拦["fetch"].消息, 1, 拦["fetch"] and 拦["fetch"].消息)
ck("每条拦截都带「那该怎么办」", all(e and e.建议.strip() for e in 拦.values()), len(拦))

print("\n▸ 连接测试跑法下(10-26):写入类动作只演练、不发给澜绣 —— 那时候单测它不会写出真记录,放行")
try:
    小3, 要填3 = ST1.拼小图(草稿, "save", 工具读写=读写, 写入只演练=True)
    放了 = 小3 and 要填3 == ["内容"]
except ST1.不能单测 as e:
    放了 = False
ck("写入类动作 + 连接测试 → 拼得出来(要填的是它的入参)", 放了, 1)
ck("**同一个动作不带连接测试 → 照旧拦**(放行只跟着跑法走,不是把闸拆了)", 拦["save"] is not None, 1)
try:
    ST1.拼小图(草稿, "review", 工具读写=读写, 写入只演练=True)
    人工放了 = True
except ST1.不能单测:
    人工放了 = False
ck("连接测试也不放人工核对(会派真待办,和写不写澜绣无关)", not 人工放了, 1)

print("\n▸ 连接测试替身:写入类动作不发给澜绣时这一步交出什么")
import 执行模式 as EM  # noqa: E402
替 = EM.连接测试替身("写跟进", {"内容": "宋制褙子"}, {"properties": {"跟进单号": {"type": "string"}, "件数": {"type": "integer"}}})
ck("工具声明过的每一项输出都在(下游从这一步取值不会因为缺键而失败,锅不会甩到下游)",
   {"跟进单号", "件数"} <= set(替), 1, sorted(替))
ck("填的字样明说「没真写」,不冒充真结果;数字类给空,不编一个数",
   "没有真的写" in str(替["跟进单号"]) and 替["件数"] is None, 1, 替)
ck("记下了本来会写什么(动作名 + 参数原样),并标成未执行",
   替.get("未执行") is True and 替.get("本来会写") == {"业务动作": "写跟进", "参数": {"内容": "宋制褙子"}}
   and 替.get("execution_mode") == "dry_run", 1, 替)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
