#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参数提取器(10-27,照 Dify 一期;录音跟进「提取客户需求」本质就是它)。

## 判据(期望值是手写的,模型答什么由 mock 那一侧给)

  ① 模型给齐了 → 每项按名字放进结果,下游能取;交给模型的有每项的名字 / 类型 / 说明 / 必填,和「没提到写 null」
  ② 原文没提到的选填项 → 结果里是空(null),**不是「没提到」这样一个看起来像值的字**
  ③ 必填的没抽到 → 这一步失败(EXTRACT_REQUIRED_MISSING),不把半套参数交给后面;连了「失败」出口就走那条
  ④ 类型不对(要整数给了「三千」;要整数给了 true)→ 失败(EXTRACT_TYPE)
  ⑤ 检查配置:没起名 / 重名 / 类型不认得 各报各的码;密钥不许绑进来;正常那张图没有阻断
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


出 = {"type": "object", "properties": {"预算": {"type": "integer"}, "款式": {"type": "string"}, "到店": {"type": "string"}},
      "required": ["预算"], "additionalProperties": False}
参们 = [{"name": "预算", "type": "integer", "description": "单位元,只写数字", "required": True},
        {"name": "款式", "type": "string", "description": "马面裙 / 袄裙这类"},
        {"name": "到店", "type": "string", "description": "约的到店日期"}]


def 图(参=None, 接失败=False):
    参 = 参们 if 参 is None else 参
    nodes = [{"id": "start", "type": "start", "config": {"input_schema": {
                 "type": "object", "properties": {"转写": {"type": "string"}}, "required": ["转写"]}}},
             {"id": "ex", "type": "extractor", "config": {
                 "connection_version_id": "cv1", "parameters": 参, "instruction": "金额按客户最后说的那个",
                 "bindings": {"录音转写": {"source": "input", "pointer": "/转写"}},
                 **({"failure_policy": "branch"} if 接失败 else {})}},
             {"id": "end", "type": "end", "config": {"output_schema": 出, "bindings": {
                 k: {"source": "node", "node_id": "ex", "pointer": f"/{k}"} for k in ("预算", "款式", "到店")}}}]
    edges = [{"source": "start", "target": "ex", "port": "success"}, {"source": "ex", "target": "end", "port": "success"}]
    if 接失败:
        # 整条流程要求返回「预算」—— 交人那条路给一个占位 0(测试只看走没走这条路)
        nodes.append({"id": "人工", "type": "end", "config": {"output_schema": 出, "bindings": {"预算": {"source": "constant", "value": 0}}}})
        edges.append({"source": "ex", "target": "人工", "port": "error"})
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出, "nodes": nodes, "edges": edges}


def 跑(g, 答):
    看见 = []

    def 模型(cfg, 实参):
        看见.append((cfg, 实参))
        return {**答, "execution_mode": "mock"}
    r = RN.跑一张图(CP.编译(g, 依赖存在=lambda 种类, i: True), {"转写": "预算三千左右,想做马面裙"}, 适配器={"llm": 模型}, run_id="r")
    return r, 看见


print("▸ ① 给齐了")
r, 看见 = 跑(图(), {"预算": 3000, "款式": "马面裙", "到店": "下周六"})
ck("每项按名字进结果、下游取到、模型调用 1 次",
   r["执行状态"] == "succeeded" and r["输出"] == {"预算": 3000, "款式": "马面裙", "到店": "下周六"} and r["用量"]["模型调用"] == 1, 1, r)
cfg, 实参 = 看见[0]
清单 = 实参.get("要提取的参数", "")
ck("交给模型的:每项名字 / 类型 / 说明 / 必填都在,还有「没提到写 null」和那句要注意的话、原文",
   all(p["name"] in 清单 and p["description"] in 清单 for p in 参们) and "整数" in 清单 and "必填" in 清单
   and "null" in 实参.get("规矩", "") and 实参.get("提取时还要注意") == "金额按客户最后说的那个" and 实参.get("录音转写"), 4, 实参)
ck("结果形状按参数现拼(预算是整数)", cfg["output_schema"]["properties"]["预算"] == {"type": "integer"}, 1, cfg["output_schema"])

print("▸ ② 选填没提到")
for 答 in ({"预算": 3000, "款式": "马面裙"}, {"预算": 3000, "款式": "马面裙", "到店": "没提到"}):
    r, _ = 跑(图(), 答)
    ck(f"「到店」{'没给' if '到店' not in 答 else '给了「没提到」'} → 结果里是 null,不是一个看起来像值的字",
       r["执行状态"] == "succeeded" and r["输出"].get("到店", "缺") is None, 1, r["输出"])

print("▸ ③ 必填没抽到")
r, _ = 跑(图(), {"款式": "马面裙", "预算": None})
步 = {s["node_id"]: s for s in r["步骤"]}
ck("这一步失败、整条失败、结束没跑", r["执行状态"] == "failed" and 步["ex"].get("error_code") == "EXTRACT_REQUIRED_MISSING"
   and 步["end"]["status"] == "skipped", 1, (r["执行状态"], {k: (v["status"], v.get("error_code")) for k, v in 步.items()}))
r, _ = 跑(图(接失败=True), {"款式": "马面裙"})
ck("接了失败出口:走去人工", r["执行状态"] == "succeeded" and any(s["node_id"] == "人工" and s["status"] == "succeeded" for s in r["步骤"]), 1,
   [(s["node_id"], s["status"]) for s in r["步骤"]])

print("▸ ④ 类型不对")
for 坏 in ("三千", True, 3000.5):
    r, _ = 跑(图(), {"预算": 坏, "款式": "马面裙"})
    步 = {s["node_id"]: s for s in r["步骤"]}
    ck(f"要整数给了 {坏!r} → EXTRACT_TYPE", r["执行状态"] == "failed" and 步["ex"].get("error_code") == "EXTRACT_TYPE", 1,
       (r["执行状态"], 步["ex"].get("error_code")))

print("▸ ⑤ 检查配置")
码 = lambda g: sorted(p["code"] for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断)
ck("正常那张图:没有阻断", 码(图()) == [], 1, 码(图()))
g = 图([{"name": "预算", "type": "integer"}, {"name": "", "type": "string"}])
ck("没起名 → 报 EXTRACT_NO_NAME", "EXTRACT_NO_NAME" in 码(g), 1, 码(g))
g = 图([{"name": "预算", "type": "integer"}, {"name": "预算", "type": "string"}])
ck("重名 → 只报 EXTRACT_DUP", 码(g) == ["EXTRACT_DUP"], 1, 码(g))
g = 图([{"name": "预算", "type": "money"}])
ck("类型不认得 → 只报 EXTRACT_BAD_TYPE", 码(g) == ["EXTRACT_BAD_TYPE"], 1, 码(g))
g = 图(); g["nodes"][1]["config"]["bindings"]["钥"] = {"source": "secret", "name": "k"}
ck("密钥绑进提取器 → 报 BIND_SECRET_INTO_MODEL", "BIND_SECRET_INTO_MODEL" in 码(g), 1, 码(g))

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
