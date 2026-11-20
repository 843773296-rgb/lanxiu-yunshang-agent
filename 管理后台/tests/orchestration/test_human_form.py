#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工介入表单化(四期 4-1,11-20 照 Dify)—— 校验器 + 执行器那一半,不起服务、不碰库。

规划 4-1:表单内容 Markdown + 插字段;按钮可配、**每个按钮一个出口**;超时照旧(到期运行结束不写)。

## 判据(全部打真校验器 / 真执行器)
  ① 校验:按钮 id 空 / 重复 → 阻断 HUMAN_ACTION_KEY;分支线挂在不存在的按钮上 → 阻断 HUMAN_EDGE_NO_ACTION;按钮没接线 → 警告 HUMAN_ACTION_UNWIRED;
     字段名空 / 重复 → 阻断 HUMAN_FIELD_KEY;下拉没选项 → 阻断 HUMAN_FIELD_OPTIONS;说明里 {{x}} 不在材料里 → 警告 HUMAN_FORM_REF;配对了 → 没有 HUMAN_ 开头的阻断
  ② 老写法(不配按钮 / 字段)→ 一条 HUMAN_ 问题都不报(规矩只管表单化)
  ③ 执行器挂起:载荷带 表单{说明(已渲染 {{摘要}})、字段、按钮}、allowed_fields 并进字段名、通知连接、步骤名
  ④ 恢复:决定 = 按钮 id → 走那个按钮的分支;另一个按钮 → 走另一条;字段值和 __action_id 在这一步的输出里
  ⑤ 恢复:没配按钮时 决定=approve 照旧走「完成后」
"""
import copy
import json
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
import validator as V  # noqa: E402
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:260] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


入参 = {"type": "object", "properties": {"摘要": {"type": "string"}}, "required": ["摘要"]}
文 = {"type": "object", "properties": {"text": {"type": "string"}}}


def 人(**额外):
    return {"id": "核", "type": "human", "name": "店长判责", "config": {
        "request_kind": "核对", "candidate_roles": ["admin"], "expires_at_policy": {"小时": 24, "到期": "fail"},
        "payload_binding": {"摘要": {"source": "input", "pointer": "/摘要"}}, **额外}}


def 模板(i, 字):
    return {"id": i, "type": "template", "name": i, "config": {"template": 字 + "{{谁}}", "bindings": {"谁": {"source": "node", "node_id": "核", "pointer": "/__action_id"}}}}


def 图(人节点, 边):
    节点 = [{"id": "start", "type": "start", "config": {"start_mode": "用户输入", "input_schema": 入参}}, 人节点,
          模板("甲路", "顾客:"), 模板("乙路", "门店:"),
          {"id": "end", "type": "end", "config": {"output_schema": 文, "bindings": {"text": {"source": "node", "node_id": "汇", "pointer": "/out"}}}},
          {"id": "汇", "type": "merge", "config": {"candidates": [{"source": "node", "node_id": "甲路", "pointer": "/文本"}, {"source": "node", "node_id": "乙路", "pointer": "/文本"}], "output_field": "out"}}]
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文, "nodes": 节点,
            "edges": [{"source": a, "target": b, "port": p, **({"branch_key": k} if k else {})} for a, b, p, k in 边]}


两按钮 = [{"id": "顾客责任", "文字": "顾客责任", "样式": "默认"}, {"id": "门店责任", "文字": "门店责任", "样式": "强调"}]
字段 = [{"name": "备注", "title": "备注", "type": "段落", "required": False}, {"name": "赔付", "type": "下拉", "options": ["退款", "换货"], "required": True}]
好边 = [("start", "核", "success", None), ("核", "甲路", "branch", "顾客责任"), ("核", "乙路", "branch", "门店责任"),
       ("甲路", "汇", "success", None), ("乙路", "汇", "success", None), ("汇", "end", "success", None)]
好图 = 图(人(actions=两按钮, form_fields=字段, form_markdown="客户说:{{摘要}}。请判断。"), 好边)


def 校(g):
    return V.校验(g, 依赖存在=lambda 种类, i: True)


def 码们(问题们, 级=None):
    return [p["code"] for p in 问题们 if 级 is None or p["级别"] == 级]


print("▸ ① 校验")
问 = 校(好图)
ck("夹具自检:走得通(没有 NODE_UNREACHABLE / EDGE_UNKNOWN_PORT / EDGE_DANGLING)", not {"NODE_UNREACHABLE", "EDGE_UNKNOWN_PORT", "EDGE_DANGLING"} & set(码们(问)), 1, 码们(问))
ck("配对了 → 没有 HUMAN_ 开头的阻断", not any(c.startswith("HUMAN_") for c in 码们(问, V.阻断)), 1, 码们(问))
g = copy.deepcopy(好图); g["nodes"][1]["config"]["actions"][1]["id"] = "顾客责任"
ck("两个按钮同名 → 阻断 HUMAN_ACTION_KEY", "HUMAN_ACTION_KEY" in 码们(校(g), V.阻断), 1, 码们(校(g)))
g = copy.deepcopy(好图); g["nodes"][1]["config"]["actions"][0]["id"] = ""
ck("按钮没标识 → 阻断 HUMAN_ACTION_KEY", "HUMAN_ACTION_KEY" in 码们(校(g), V.阻断), 1, 码们(校(g)))
g = copy.deepcopy(好图); g["edges"][1]["branch_key"] = "不存在的按钮"
ck("线挂在不存在的按钮上 → 阻断 HUMAN_EDGE_NO_ACTION", "HUMAN_EDGE_NO_ACTION" in 码们(校(g), V.阻断), 1, 码们(校(g)))
g = copy.deepcopy(好图); g["edges"] = [e for e in g["edges"] if e.get("branch_key") != "门店责任"]
问 = 校(g)
ck("按钮没接线 → 警告 HUMAN_ACTION_UNWIRED(不阻断)", "HUMAN_ACTION_UNWIRED" in 码们(问, V.警告) and "HUMAN_ACTION_UNWIRED" not in 码们(问, V.阻断), 1, 码们(问))
g = copy.deepcopy(好图); g["nodes"][1]["config"]["form_fields"][1]["name"] = "备注"
ck("字段重名 → 阻断 HUMAN_FIELD_KEY", "HUMAN_FIELD_KEY" in 码们(校(g), V.阻断), 1, 码们(校(g)))
g = copy.deepcopy(好图); g["nodes"][1]["config"]["form_fields"][1]["options"] = []
ck("下拉没选项 → 阻断 HUMAN_FIELD_OPTIONS", "HUMAN_FIELD_OPTIONS" in 码们(校(g), V.阻断), 1, 码们(校(g)))
g = copy.deepcopy(好图); g["nodes"][1]["config"]["form_markdown"] = "客户 {{客户名}} 说"
问 = 校(g)
ck("说明引用了材料里没有的 → 警告 HUMAN_FORM_REF", "HUMAN_FORM_REF" in 码们(问, V.警告), 1, 码们(问))

print("▸ ② 老写法不受影响")
老 = 图(人(), [("start", "核", "success", None), ("核", "甲路", "success", None), ("甲路", "汇", "success", None), ("汇", "end", "success", None)])
老["nodes"] = [n for n in 老["nodes"] if n["id"] != "乙路"]
老["nodes"][-1]["config"]["candidates"] = 老["nodes"][-1]["config"]["candidates"][:1]
for n in 老["nodes"]:
    if n["type"] == "template":
        n["config"]["bindings"]["谁"]["pointer"] = "/决定"
问 = 校(老)
ck("不配按钮 / 字段 → 一条 HUMAN_ 问题都不报", not any(c.startswith("HUMAN_") for c in 码们(问)), 1, 码们(问))

print("▸ ③ 执行器挂起:载荷带表单")
计划 = CP.编译(好图, 依赖存在=lambda 种类, i: True)
r1 = RN.跑一张图(计划, {"摘要": "袖子短了"}, 适配器={}, 记事=lambda k, v: None, run_id="hf1")
点 = r1.get("检查点") or {}
载 = ((点.get("等待") or {}).get("载荷")) or {}
ck("停在 waiting_approval,等的是 human", r1.get("执行状态") == "waiting_approval" and (点.get("等待") or {}).get("种类") == "human", 1, r1.get("执行状态"))
表 = 载.get("表单") or {}
ck("载荷.表单:说明已渲染 {{摘要}}、两个按钮、两个字段;步骤名带上", 表.get("说明") == "客户说:袖子短了。请判断。" and [a["id"] for a in 表.get("按钮", [])] == ["顾客责任", "门店责任"]
   and [f["name"] for f in 表.get("字段", [])] == ["备注", "赔付"] and 载.get("步骤名") == "店长判责", 1, 载)
ck("allowed_fields 并进了字段名(核对人填的值能走 edits 回来)", set(载.get("allowed_fields") or []) >= {"备注", "赔付"}, 1, 载.get("allowed_fields"))
ck("材料里还是原来的摘要", (载.get("材料") or {}).get("摘要") == "袖子短了", 1, 载.get("材料"))

print("▸ ④ 恢复:按钮 → 对应分支")
存 = lambda r: json.loads(json.dumps(r["检查点"], ensure_ascii=False, default=str))  # noqa: E731
r2 = RN.跑一张图(计划, {"摘要": "袖子短了"}, 适配器={}, 记事=lambda k, v: None, run_id="hf1",
               恢复={**存(r1), "结果": {"决定": "门店责任", "__action_id": "门店责任", "赔付": "退款", "备注": "", "处理人": "U1", "理由": ""}})
ck("点「门店责任」→ 走乙路,输出带 门店:门店责任", r2.get("执行状态") == "succeeded" and (r2.get("输出") or {}).get("text") == "门店:门店责任", 1, (r2.get("执行状态"), r2.get("输出"), r2.get("完成原因")))
步 = {s["node_id"]: s for s in r2.get("步骤") or []}
ck("核这一步记 branch_key=门店责任;甲路记成 skipped(没跑)", (步.get("核") or {}).get("branch_key") == "门店责任" and (步.get("甲路") or {}).get("status") == "skipped", 1, {k: (v.get("status"), v.get("branch_key")) for k, v in 步.items()})
r3 = RN.跑一张图(计划, {"摘要": "袖子短了"}, 适配器={}, 记事=lambda k, v: None, run_id="hf1",
               恢复={**存(r1), "结果": {"决定": "顾客责任", "__action_id": "顾客责任", "赔付": "换货", "处理人": "U1", "理由": ""}})
ck("点「顾客责任」→ 走甲路", r3.get("执行状态") == "succeeded" and (r3.get("输出") or {}).get("text") == "顾客:顾客责任", 1, (r3.get("执行状态"), r3.get("输出")))

print("▸ ⑤ 没配按钮:approve 照旧走「完成后」")
计划老 = CP.编译(老, 依赖存在=lambda 种类, i: True)
o1 = RN.跑一张图(计划老, {"摘要": "x"}, 适配器={}, 记事=lambda k, v: None, run_id="hf2")
ck("老写法挂起时载荷没有 表单(None)", o1.get("执行状态") == "waiting_approval" and ((o1.get("检查点") or {}).get("等待") or {}).get("载荷", {}).get("表单") is None, 1, o1.get("检查点"))
o2 = RN.跑一张图(计划老, {"摘要": "x"}, 适配器={}, 记事=lambda k, v: None, run_id="hf2",
               恢复={**存(o1), "结果": {"决定": "approve", "定稿": "x", "处理人": "U1", "理由": ""}})
ck("approve → 走成功口到甲路", o2.get("执行状态") == "succeeded" and (o2.get("输出") or {}).get("text") == "顾客:approve", 1, (o2.get("执行状态"), o2.get("输出")))

print()
if 挂:
    print(f"❌ {len(挂)} 条没过:{挂}")
    sys.exit(1)
print(f"✅ {len(过)} 条全过")
