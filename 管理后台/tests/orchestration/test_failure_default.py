#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""失败后「按默认值继续」(11-15,工作流一期第二件;照 Dify「异常处理」)。

## 为什么要这份
「失败后怎么办」原来只有两种:整次运行失败 / 走「失败时」那条线。加第三种「按默认值继续」:
这一步失败时,输出换成人填好的默认值 + 真实的 error_type / error_message,运行照常走成功线。
用户 11-15 拍:**会写数据的步骤不许这样**(发券失败却当成发了,后面会照着「券已发」去通知顾客)。

## 判据(执行器那几条打真执行器、假适配器;校验器那几条打真校验器)
  ① 只读步骤失败 + 按默认值继续 → 运行成功、下游拿到默认值、error_type 是真实失败码
  ② 那一步**仍记失败**,只补 handled=default(不把失败洗成成功)+ 一条 node.default_used 事件
  ③ 没选按默认值继续(老流程)→ 照旧整次运行失败
  ④ 校验器:写数据的业务动作选按默认值继续 → 阻断 FAILURE_DEFAULT_ON_WRITE;只读的放行;
     查不到读写登记 → 当写入挡(偏错朝「少一种走法」那边)
  ⑤ 校验器:Agent / 人工核对这类不许按默认值继续;没填默认值 / 缺下游要的项 / 自己填 error_type → 阻断
  ⑥ 校验器:选了「走失败线」却没接线 → 警告;填了默认值却没选按默认值继续 → 警告;认不出的走法 → 阻断
  ⑦ 没给读写查询能力时,写入那条记成「没查」,不算通过
  ⑧ 接线:workflows_api._依赖查询 交出的查询函数真带着「工具读写」(校验器靠它挡写入)
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402
import validator as V  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:240] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


文 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}


def llm图(**额外):
    cfg = {"connection_version_id": "cv1", "prompt_version_id": "p1", "output_schema": 文,
           "bindings": {"问": {"source": "input", "pointer": "/问"}}, **额外}
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文,
            "nodes": [{"id": "start", "type": "start", "config": {"input_schema": {
                          "type": "object", "properties": {"问": {"type": "string"}}, "required": ["问"]}}},
                      {"id": "llm", "type": "llm", "config": cfg},
                      {"id": "end", "type": "end", "config": {"output_schema": 文, "bindings": {
                          "text": {"source": "node", "node_id": "llm", "pointer": "/text"}}}}],
            "edges": [{"source": "start", "target": "llm", "port": "success"},
                      {"source": "llm", "target": "end", "port": "success"}]}


def 换节点(g, i, 新):
    g = {**g, "nodes": [新 if n["id"] == i else n for n in g["nodes"]]}
    return g


def 查询(读写表=None):
    def 存在(种类, i):
        return True
    if 读写表 is not None:
        存在.工具读写 = lambda tv: 读写表.get(tv)
    return 存在


def 码们(问题们, 级=None):
    return [p["code"] for p in 问题们 if 级 is None or p["级别"] == 级]


def 跑(g):
    事件 = []

    def 模型(cfg, 实参):
        raise RN.节点失败("RATE_LIMIT", "模型那边限流了", "等一会儿")
    r = RN.跑一张图(CP.编译(g, 依赖存在=查询({})), {"问": "你好"}, 适配器={"llm": 模型},
                  记事=lambda 名, 载: 事件.append((名, 载)), run_id="r")
    return r, 事件


默 = {"text": "暂时没法生成,请稍后再试"}

print("▸ ① 只读步骤失败 + 按默认值继续 → 运行成功,下游拿到默认值")
r, 事 = 跑(llm图(failure_policy="default", default_output=默))
ck("运行成功", r["执行状态"] == "succeeded", 1, (r["执行状态"], r.get("完成原因")))
ck("最后的输出就是默认值", (r["输出"] or {}).get("text") == 默["text"], 1, r["输出"])
步 = [s for s in r["步骤"] if s["node_id"] == "llm"]
ck("那一步的输出带真实的失败码和原因", 步 and (步[-1].get("default_output") or {}).get("error_type") == "RATE_LIMIT"
   and "限流" in (步[-1].get("default_output") or {}).get("error_message", ""), len(步), 步)

print("▸ ② 那一步仍记失败,只补 handled=default")
ck("落库那一格(错误细节)带着「按默认值继续」和顶上的值", 步 and (步[-1].get("error_detail") or {}).get("处理") == "按默认值继续"
   and ((步[-1].get("error_detail") or {}).get("默认值") or {}).get("text") == 默["text"], len(步), 步)
ck("步骤 status 仍是 failed、handled=default", 步 and 步[-1]["status"] == "failed" and 步[-1].get("handled") == "default", len(步), 步)
用 = [载 for 名, 载 in 事 if 名 == "node.default_used"]
ck("记了一条 node.default_used 事件", len(用) == 1 and 用[0].get("error_code") == "RATE_LIMIT", len(用), 用)
ck("那一步不算「走过的路径」里成功的一步", "llm" not in r["走过的路径"], 1, r["走过的路径"])

print("▸ ③ 老流程(没选按默认值继续)照旧整次失败")
r2, _ = 跑(llm图())
ck("没配 → 运行失败、原因是真实失败码", r2["执行状态"] == "failed" and r2["完成原因"] == "RATE_LIMIT", 1, (r2["执行状态"], r2["完成原因"]))
r3, _ = 跑(llm图(failure_policy="fail_run", default_output=默))
ck("填了默认值但走法是「这次运行失败」→ 照旧失败(默认值不偷偷生效)", r3["执行状态"] == "failed", 1, r3["执行状态"])

print("▸ ④ 写数据的业务动作不许按默认值继续")
工具节点 = lambda tv: {"id": "llm", "type": "tool", "config": {
    "tool_version_id": tv, "arguments": {"问": {"source": "input", "pointer": "/问"}},
    "failure_policy": "default", "default_output": 默}}
g写 = 换节点(llm图(), "llm", 工具节点("tv_写"))
问 = V.校验(g写, 依赖存在=查询({"tv_写": "write", "tv_读": "read_only", "tv_不可逆": "irreversible"}))
ck("写入工具 → 阻断 FAILURE_DEFAULT_ON_WRITE", "FAILURE_DEFAULT_ON_WRITE" in 码们(问, V.阻断), 1, 码们(问))
问 = V.校验(换节点(llm图(), "llm", 工具节点("tv_不可逆")), 依赖存在=查询({"tv_不可逆": "irreversible"}))
ck("不可逆工具 → 也阻断", "FAILURE_DEFAULT_ON_WRITE" in 码们(问, V.阻断), 1, 码们(问))
问 = V.校验(换节点(llm图(), "llm", 工具节点("tv_读")), 依赖存在=查询({"tv_读": "read_only"}))
ck("只读工具 → 不报这一条", "FAILURE_DEFAULT_ON_WRITE" not in 码们(问), 1, 码们(问))
问 = V.校验(换节点(llm图(), "llm", 工具节点("tv_谁")), 依赖存在=查询({}))
ck("查不到读写登记 → 当写入挡", "FAILURE_DEFAULT_ON_WRITE" in 码们(问, V.阻断), 1, 码们(问))
try:
    CP.编译(g写, 依赖存在=查询({"tv_写": "write"}))
    编过 = True
except CP.编译失败:
    编过 = False
ck("编译(运行 / 发布前那一道)也拦得住写入工具", not 编过, 1)

print("▸ ⑤ 不许的类型 / 默认值没填好")
人工 = {"id": "llm", "type": "human", "config": {"request_kind": "approve", "failure_policy": "default", "default_output": 默}}
问 = V.校验(换节点(llm图(), "llm", 人工), 依赖存在=查询({}))
ck("人工核对 → 阻断 FAILURE_DEFAULT_NOT_ALLOWED", "FAILURE_DEFAULT_NOT_ALLOWED" in 码们(问, V.阻断), 1, 码们(问))
问 = V.校验(llm图(failure_policy="default"), 依赖存在=查询({}))
ck("没填默认值 → 阻断 FAILURE_DEFAULT_MISSING", "FAILURE_DEFAULT_MISSING" in 码们(问, V.阻断), 1, 码们(问))
问 = V.校验(llm图(failure_policy="default", default_output={"别的": 1}), 依赖存在=查询({}))
ck("缺下游要的 text → 阻断 FAILURE_DEFAULT_INCOMPLETE", "FAILURE_DEFAULT_INCOMPLETE" in 码们(问, V.阻断), 1, 码们(问))
问 = V.校验(llm图(failure_policy="default", default_output={**默, "error_type": "假的"}), 依赖存在=查询({}))
ck("自己填 error_type → 阻断 FAILURE_DEFAULT_RESERVED", "FAILURE_DEFAULT_RESERVED" in 码们(问, V.阻断), 1, 码们(问))
问 = V.校验(llm图(failure_policy="default", default_output=默), 依赖存在=查询({}))
ck("对照:只读步骤 + 默认值填全 → 这一节一条阻断都没有",
   not [c for c in 码们(问, V.阻断) if c.startswith("FAILURE_")], 1, 码们(问))

print("▸ ⑥ 走法本身配得对不对")
问 = V.校验(llm图(failure_policy="branch"), 依赖存在=查询({}))
ck("走失败线却没接线 → 警告 FAILURE_BRANCH_NO_EDGE", "FAILURE_BRANCH_NO_EDGE" in 码们(问, V.警告), 1, 码们(问))
问 = V.校验(llm图(default_output=默), 依赖存在=查询({}))
ck("填了默认值没选这种走法 → 警告 FAILURE_DEFAULT_UNUSED", "FAILURE_DEFAULT_UNUSED" in 码们(问, V.警告), 1, 码们(问))
问 = V.校验(llm图(failure_policy="ignore"), 依赖存在=查询({}))
ck("认不出的走法 → 阻断 FAILURE_POLICY_UNKNOWN", "FAILURE_POLICY_UNKNOWN" in 码们(问, V.阻断), 1, 码们(问))

print("▸ ⑦ 没给读写查询能力 → 记成「没查」,不算通过")
问 = V.校验(换节点(llm图(), "llm", 工具节点("tv_写")), 依赖存在=查询(None))
跳 = [p for p in 问 if p["code"] == "CHECK_SKIPPED" and "只读" in p["消息"]]
ck("写入那条出现在「有一类没检查」里", len(跳) == 1, len(跳), 码们(问))

print("▸ ⑧ 接线:后台给校验器的查询函数真带着「工具读写」")
源 = open(os.path.join(根, "services", "api", "app", "workflows_api.py"), encoding="utf-8").read()
段 = 源[源.index("def _依赖查询("):源.index("def _新id(")]
ck("_依赖查询 给查询函数挂了 工具读写,并按项目查 tool_versions.side_effect_type",
   "存在.工具读写" in 段 and "side_effect_type from tool_versions" in 段 and "project_id=:p" in 段, 1)

print()
if 挂:
    print(f"❌ {len(挂)} 条没过:{挂}")
    sys.exit(1)
print(f"✅ {len(过)} 条全过")
