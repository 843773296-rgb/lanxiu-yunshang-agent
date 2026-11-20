#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识检索节点(三期 3-5,11-20 做通)—— 校验器那一半 + 顺手修的 node_id。

## 为什么要这份
11-20 盘点发现「知识检索」能加进图、dsl 标「已实现」,但:面板里没地方选资料库 / 检索配置、worker 没有它的适配器(跑到就 ADAPTER_MISSING)。
做通之后校验器要守两条:要查什么得绑上(问题);选了资料库却没有「已就绪」的索引要拦(不在没建好的索引上检索)。
顺手修的:HTTP 请求那段把列表序号当 node_id 报(前端按 node_id 找节点标红永远找不到)—— 这里一起钉住。

## 判据(全部打真校验器)
  ① 没绑「问题」→ 阻断 RETRIEVE_QUERY_MISSING,报在那个节点上(node_id 是节点 id,不是序号)
  ② 选了资料库、没有 index_build_id → 阻断 RETRIEVE_NO_READY_INDEX;有了 → 不报
  ③ 都配齐 → 这两条都不报
  ④ 用户输入 / 别的节点不受影响(规矩只管 retrieve)
  ⑤ HTTP 请求没写路径 → HTTP_PATH_MISSING 的 node_id 是那个节点的 id(不是 0/1/2)
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
import validator as V  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:240] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


入参 = {"type": "object", "properties": {"问题": {"type": "string"}}, "required": ["问题"]}
文 = {"type": "object", "properties": {"text": {"type": "string"}}}


def 图(检索配置, 边=None):
    节点 = [{"id": "start", "type": "start", "config": {"start_mode": "用户输入", "input_schema": 入参}},
          {"id": "查", "type": "retrieve", "config": 检索配置},
          {"id": "end", "type": "end", "config": {"output_schema": 文, "bindings": {"text": {"source": "node", "node_id": "查", "pointer": "/证据"}}}}]
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文, "nodes": 节点,
            "edges": [{"source": a, "target": b, "port": p} for a, b, p in (边 or [("start", "查", "success"), ("查", "end", "success")])]}


def 校(g):
    return V.校验(g, 依赖存在=lambda 种类, i: True)


def 码们(问题们, 级=None):
    return [p["code"] for p in 问题们 if 级 is None or p["级别"] == 级]


齐 = {"knowledge_base_id": "kb1", "index_build_id": "ib1", "retrieval_config_version_id": "rc1",
     "bindings": {"问题": {"source": "input", "pointer": "/问题"}}}

print("▸ ① 没绑「问题」→ 阻断,报在那个节点上")
问 = 校(图({**齐, "bindings": {}}))
条 = [p for p in 问 if p["code"] == "RETRIEVE_QUERY_MISSING"]
ck("RETRIEVE_QUERY_MISSING 阻断", bool(条) and all(p["级别"] == V.阻断 for p in 条), len(条), 码们(问))
ck("node_id 是节点 id「查」(不是序号)", bool(条) and 条[0].get("node_id") == "查", len(条), 条)

print("▸ ② 选了资料库、没有就绪索引 → 阻断")
问 = 校(图({**齐, "index_build_id": None}))
ck("RETRIEVE_NO_READY_INDEX 阻断", "RETRIEVE_NO_READY_INDEX" in 码们(问, V.阻断), 1, 码们(问))
问 = 校(图(齐))
ck("有索引 → 不报", "RETRIEVE_NO_READY_INDEX" not in 码们(问), 1, 码们(问))

print("▸ ③ 都配齐 → 两条都不报")
问 = 校(图(齐))
ck("夹具自检:图走得通(没有 NODE_UNREACHABLE / EDGE_UNKNOWN_PORT)", not {"NODE_UNREACHABLE", "EDGE_UNKNOWN_PORT"} & set(码们(问)), 1, 码们(问))
ck("配齐 → 没有 RETRIEVE_ 开头的问题", not any(c.startswith("RETRIEVE_") for c in 码们(问)), 1, 码们(问))

print("▸ ④ 别的节点不受影响")
g = 图(齐)
g["nodes"][1] = {"id": "查", "type": "template", "config": {"template": "x", "bindings": {}}}
问 = 校(g)
ck("换成模板转换 → 没有 RETRIEVE_ 开头的问题", not any(c.startswith("RETRIEVE_") for c in 码们(问)), 1, 码们(问))

print("▸ ⑤ HTTP 请求的 node_id 顺手修对")
g = 图(齐)
g["nodes"][1] = {"id": "查", "type": "http_request", "config": {"method": "GET", "connection_id": "cc1", "query": {}, "headers": {}, "bindings": {}}}
问 = 校(g)
条 = [p for p in 问 if p["code"] == "HTTP_PATH_MISSING"]
ck("HTTP_PATH_MISSING 报在节点 id「查」上(原来是列表序号 1)", bool(条) and 条[0].get("node_id") == "查", len(条), 条)

print()
if 挂:
    print(f"❌ {len(挂)} 条没过:{挂}")
    sys.exit(1)
print(f"✅ {len(过)} 条全过")
