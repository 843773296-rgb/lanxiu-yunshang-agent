#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直接回复节点(用户 2026-10-27 拍「要做,直接接聊天技能;要呈现出来,不然测试时不好看结果」)。

## 判据(期望的回复文字是手写的,不由执行器生成)

  ① 模板里的 {{名字}} 换成「用到的数据」里同名那一项;数字 / 列表照 JSON 写出来
  ② 模板里有、绑定里没有的名字 → **检查配置当场拦**(ANSWER_PLACEHOLDER_UNBOUND),不等运行时发出花括号
  ③ 运行时取不到值 → 这一步失败(ANSWER_VALUE_MISSING),**不回半句**
  ④ 回复在人工核对**之前**的话,挂起时它已经在步骤里了 —— 聊天站发起后等一会儿,拿得到这一句
  ⑤ 回复文字**不进事件载荷**(事件不按授权打码),只在这一步的输出里
  ⑥ 样例预览照常跑它(它不花钱、不写入)
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
import dsl as DS  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:190] if 补 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


def 引(n, p):
    return {"source": "node", "node_id": n, "pointer": p}


文本 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
        "additionalProperties": False}
出 = {"type": "object", "properties": {"结果": {"type": "string"}}, "required": ["结果"],
      "additionalProperties": False}


def 图(模板, 绑定, 带人工=False):
    节点 = [
        {"id": "start", "type": "start", "config": {"input_schema": {
            "type": "object", "properties": {"客户": {"type": "string"}, "件数": {"type": "integer"}},
            "required": ["客户", "件数"]}}},
        {"id": "extract", "type": "llm", "config": {"connection_version_id": "cv1",
            "prompt_version_id": "p1", "output_schema": 文本, "bindings": {"客户": {"source": "input", "pointer": "/客户"}}}},
        {"id": "say", "type": "answer", "config": {"template": 模板, "bindings": 绑定}},
    ]
    边 = [{"source": "start", "target": "extract", "port": "success"},
          {"source": "extract", "target": "say", "port": "success"}]
    尾 = "say"
    if 带人工:
        节点.append({"id": "review", "type": "human", "config": {"request_kind": "核对", "candidate_roles": ["审核人"],
                     "expires_at_policy": {"小时": 48, "到期": "fail"}, "payload_binding": {"摘要": 引("extract", "/text")}}})
        边.append({"source": "say", "target": "review", "port": "success"})
        尾 = "review"
    节点.append({"id": "end", "type": "end", "config": {"output_schema": 出, "bindings": {"结果": 引("extract", "/text")}}})
    边.append({"source": 尾, "target": "end", "port": "success"})
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出, "nodes": 节点, "edges": 边}


调了 = {"模型": 0}


def 模型(cfg, 实参):
    调了["模型"] += 1
    return {"text": "要两件马面裙"}


print("▸ ① 模板替换(期望文字手写)")
g = 图("{{客户}}您好,记下了:{{ 需求 }},共 {{件数}} 件。",
      {"客户": {"source": "input", "pointer": "/客户"}, "需求": 引("extract", "/text"),
       "件数": {"source": "input", "pointer": "/件数"}})
计划 = CP.编译(g, 依赖存在=lambda 种类, i: True)
事件 = []
r = RN.跑一张图(计划, {"客户": "王女士", "件数": 2}, 适配器={"llm": 模型}, run_id="a1",
              记事=lambda 种, 载: 事件.append((种, 载)))
步 = {s["node_id"]: s for s in r["步骤"]}
ck("回复是手写期望的那一句(带空格的 {{ 名字 }} 也认,数字照原样写)",
   (步.get("say") or {}).get("output") == {"回复": "王女士您好,记下了:要两件马面裙,共 2 件。"}, 1, 步.get("say"))
ck("整次运行成功", r["执行状态"] == "succeeded", 1, r["执行状态"])
ck("⑤ 回复文字不在任何事件载荷里(事件不打码)",
   not any("马面裙" in str(载) for _, 载 in 事件), len(事件))

print("▸ ② 模板里有、绑定里没有 → 检查配置拦")
g2 = 图("您好 {{客户}},{{单号}} 已登记", {"客户": {"source": "input", "pointer": "/客户"}})
问题 = V.校验(g2, 依赖存在=lambda 种类, i: True)
码 = [(p["code"], p.get("field_path")) for p in 问题 if p["级别"] == V.阻断]
ck("报且只报一条 ANSWER_PLACEHOLDER_UNBOUND,点名「单号」、指向 config.template",
   码 == [("ANSWER_PLACEHOLDER_UNBOUND", "config.template")]
   and "单号" in next(p["消息"] for p in 问题 if p["code"] == "ANSWER_PLACEHOLDER_UNBOUND"), 1, 码)
g2b = 图("", {})
码b = [p["code"] for p in V.校验(g2b, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断]
ck("模板空着 → 报缺必填配置", 码b == ["NODE_MISSING_CONFIG"], 1, 码b)

print("▸ ③ 运行时取不到值 → 这一步失败,不回半句")
g3 = 图("结果:{{需求}}", {"需求": 引("extract", "/没有这一项")})
r3 = RN.跑一张图(CP.编译(g3, 依赖存在=lambda 种类, i: True), {"客户": "王女士", "件数": 1},
               适配器={"llm": 模型}, run_id="a3")
s3 = {s["node_id"]: s for s in r3["步骤"]}.get("say") or {}
ck("失败码 ANSWER_VALUE_MISSING、没有输出", s3.get("status") == "failed"
   and s3.get("error_code") == "ANSWER_VALUE_MISSING" and "output" not in s3, 1, s3)

print("▸ ④ 回复在人工核对之前:挂起时这一句已经在步骤里")
调了["模型"] = 0
g4 = 图("收到,{{客户}},店长核对后就写进系统", {"客户": {"source": "input", "pointer": "/客户"}}, 带人工=True)
r4 = RN.跑一张图(CP.编译(g4, 依赖存在=lambda 种类, i: True), {"客户": "李先生", "件数": 1},
               适配器={"llm": 模型}, run_id="a4")
s4 = {s["node_id"]: s for s in r4["步骤"]}
ck("运行停在人工核对(waiting_approval),回复那一步已成功并带着文字",
   r4["执行状态"] == "waiting_approval" and (s4.get("say") or {}).get("output") == {"回复": "收到,李先生,店长核对后就写进系统"},
   1, (r4["执行状态"], s4.get("say")))

print("▸ ⑥ 样例预览:模型不真调,回复照常拼")
调了["模型"] = 0
r6 = RN.跑一张图(计划, {"客户": "王女士", "件数": 3}, 适配器={"llm": 模型}, run_id="a6",
               样例={"extract": {"text": "上次的需求"}})
s6 = {s["node_id"]: s for s in r6["步骤"]}.get("say") or {}
ck("模型 0 次,回复用了样例里的结果",
   调了["模型"] == 0 and s6.get("output") == {"回复": "王女士您好,记下了:上次的需求,共 3 件。"}, 1, (调了, s6))

print("▸ 模板认法只有一份(校验器和执行器都调 dsl 里那一个)")
ck("占位名去重且按出现顺序", DS.回复占位名("{{a}}{{ b }}{{a}}") == ["a", "b"], 1)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
