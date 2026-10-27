#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模板转换(10-27,照 Dify 一期;录音跟进里「记下 X」「只写跟进(没填 X)」这类拼一句话的步骤)。

## 判据(期望的文字是手写的,不由执行器生成)

  ① {{名字}} 换成「用到的数据」里同名那一项;数字 / 列表照 JSON 写;结果在「文本」里,下游能取
  ② 模板里有、绑定里没有的名字 → 检查配置当场拦(TEMPLATE_PLACEHOLDER_UNBOUND,不是直接回复那个码)
  ③ 运行时取不到值 → 这一步失败(TEMPLATE_VALUE_MISSING),下游不拿半截文字往下走
  ④ 只做替换:模板里写 Jinja 的 {% if %} / {{ a + b }} 原样留着,**不执行**
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


文 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}


def 图(模板, 绑=None):
    绑 = {"客户": {"source": "input", "pointer": "/客户"}, "预算": {"source": "input", "pointer": "/预算"}} if 绑 is None else 绑
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文, "nodes": [
        {"id": "start", "type": "start", "config": {"input_schema": {"type": "object", "properties": {
            "客户": {"type": "string"}, "预算": {"type": "integer"}, "备注": {"type": "string"}}, "required": ["客户", "预算"]}}},
        {"id": "tpl", "type": "template", "config": {"template": 模板, "bindings": 绑}},
        {"id": "end", "type": "end", "config": {"output_schema": 文, "bindings": {"text": {"source": "node", "node_id": "tpl", "pointer": "/文本"}}}}],
        "edges": [{"source": "start", "target": "tpl", "port": "success"}, {"source": "tpl", "target": "end", "port": "success"}]}


def 跑(g, 输入):
    return RN.跑一张图(CP.编译(g, 依赖存在=lambda 种类, i: True), 输入, 适配器={}, run_id="r")


码 = lambda g: sorted(p["code"] for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断)

print("▸ ① 替换")
r = 跑(图("{{客户}} 想做马面裙,预算 {{预算}} 元"), {"客户": "王女士", "预算": 3000})
ck("名字换成值、数字照写、下游取到「文本」", r["执行状态"] == "succeeded" and r["输出"] == {"text": "王女士 想做马面裙,预算 3000 元"}, 1, r)
ck("没调模型(这一步不花钱)", r["用量"]["模型调用"] == 0, 1, r["用量"])

print("▸ ② 检查配置")
ck("正常那张图:没有阻断", 码(图("{{客户}} 预算 {{预算}}")) == [], 1, 码(图("{{客户}} 预算 {{预算}}")))
g = 图("{{客户}} 下次跟进 {{日期}}")
ck("模板写了「日期」但没选来源 → 只报 TEMPLATE_PLACEHOLDER_UNBOUND", 码(g) == ["TEMPLATE_PLACEHOLDER_UNBOUND"], 1, 码(g))
g = 图("")
ck("模板空着 → 报必填缺失", any("MISSING" in c or "REQUIRED" in c for c in 码(g)), 1, 码(g))

print("▸ ③ 运行时取不到值")
g = 图("{{客户}} 备注 {{备注}}", {"客户": {"source": "input", "pointer": "/客户"}, "备注": {"source": "input", "pointer": "/备注"}})
r = 跑(g, {"客户": "王女士", "预算": 1})
步 = {s["node_id"]: s for s in r["步骤"]}
ck("这一步失败、整条失败、结束没跑(不拿半截文字往下走)",
   r["执行状态"] == "failed" and 步["tpl"].get("error_code") == "TEMPLATE_VALUE_MISSING" and 步["end"]["status"] == "skipped", 1,
   (r["执行状态"], {k: (v["status"], v.get("error_code")) for k, v in 步.items()}))

print("▸ ④ 只做替换,不执行")
r = 跑(图("{% if 预算 %}有预算{% endif %} {{ 预算 + 1 }} {{客户}}"), {"客户": "王", "预算": 2})
ck("Jinja 的判断和表达式原样留着,只换了「客户」", r["输出"] == {"text": "{% if 预算 %}有预算{% endif %} {{ 预算 + 1 }} 王"}, 1, r["输出"])

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
