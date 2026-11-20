#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Webhook 当开始方式(11-20,工作流二期 2-2;规格 11-15 已拍)—— 校验器那一半。

## 为什么要这份
Webhook 开头的流程是外部系统按一把密钥叫起来的,没有人在场。规划拍的规矩:
**写数据的业务动作前面必须有人工介入** —— 否则等于把写口交给了密钥持有方。
「前面有」按支配集判:从开始到它的**每一条**路都要经过一个人工介入,只在一条分支上有人不算。

## 判据(全部打真校验器)
  ① 开始方式认得「Webhook」(不报 START_MODE_UNKNOWN);认不出的值照旧阻断
  ② Webhook 开头 + 写入工具直连 → 阻断 WEBHOOK_WRITE_NEEDS_HUMAN;不可逆 / 查不到读写登记也挡
  ③ 前面有人工介入 → 放行;只读工具 → 放行
  ④ 只有一条分支上有人工(另一条直达写入)→ 照样阻断(这是选支配集而不是「可达」的原因)
  ⑤ 写入工具在循环里、循环前面有人 → 放行;循环里外都没人 → 阻断
  ⑥ 用户输入开头的同一张图 → 不报这一条(规矩只管 Webhook)
  ⑦ 没给读写查询能力 → 记成「没查」,不算通过
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


码 = "WEBHOOK_WRITE_NEEDS_HUMAN"
读写表 = {"tv_写": "write", "tv_读": "read_only", "tv_不可逆": "irreversible"}
入参 = {"type": "object", "properties": {"单号": {"type": "string"}}, "required": ["单号"]}
文 = {"type": "object", "properties": {"text": {"type": "string"}}}


def 查询(表=读写表):
    def 存在(种类, i):
        return True
    if 表 is not None:
        存在.工具读写 = lambda tv: 表.get(tv)
    return 存在


def 开始(方式="Webhook"):
    return {"id": "start", "type": "start", "config": {"start_mode": 方式, "input_schema": 入参}}


def 工具(i, tv, **额外):
    return {"id": i, "type": "tool", **额外,
            "config": {"tool_version_id": tv, "arguments": {"单号": {"source": "input", "pointer": "/单号"}}}}


def 人(i="核", **额外):
    return {"id": i, "type": "human", **额外, "config": {
        "request_kind": "核对", "candidate_roles": ["店长"], "expires_at_policy": {"小时": 24, "到期": "fail"}}}


结束 = {"id": "end", "type": "end", "config": {"output_schema": 文, "bindings": {}}}


def 图(节点, 边):
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文, "nodes": 节点 + [结束],
            "edges": [{"source": a, "target": b, "port": p} for a, b, p in 边]}


def 直连(tv="tv_写", 方式="Webhook"):
    return 图([开始(方式), 工具("写", tv)], [("start", "写", "success"), ("写", "end", "success")])


def 码们(问题们, 级=None):
    return [p["code"] for p in 问题们 if 级 is None or p["级别"] == 级]


def 校(g, 表=读写表):
    return V.校验(g, 依赖存在=查询(表))


print("▸ ① 开始方式认得 Webhook")
问 = 校(直连("tv_读"))
ck("Webhook 不报 START_MODE_UNKNOWN", "START_MODE_UNKNOWN" not in 码们(问), 1, 码们(问))
问 = 校(直连("tv_读", 方式="邮件"))
ck("认不出的方式照旧阻断", "START_MODE_UNKNOWN" in 码们(问, V.阻断), 1, 码们(问))

print("▸ ② 写入工具直连 → 阻断")
for tv, 名 in (("tv_写", "写入"), ("tv_不可逆", "不可逆"), ("tv_谁", "查不到读写登记")):
    问 = 校(直连(tv))
    ck(f"{名} → 阻断 {码}", 码 in 码们(问, V.阻断), 1, 码们(问))
阻 = [p for p in 校(直连()) if p["code"] == 码]
ck("报在那个写入步骤上", len(阻) == 1 and 阻[0].get("node_id") == "写", len(阻), 阻)

print("▸ ③ 前面有人 / 只读 → 放行")
g有人 = 图([开始(), 人(), 工具("写", "tv_写")],
         [("start", "核", "success"), ("核", "写", "success"), ("写", "end", "success")])
问 = 校(g有人)
ck("夹具自检:写入步骤走得到", not {"NODE_UNREACHABLE", "EDGE_UNKNOWN_PORT"} & set(码们(问)), 1, 码们(问))
ck("人工介入在前 → 不报", 码 not in 码们(问), 1, 码们(问))
问 = 校(直连("tv_读"))
ck("只读工具 → 不报", 码 not in 码们(问), 1, 码们(问))

print("▸ ④ 只有一条分支上有人 → 照样阻断(支配集,不是可达)")
g半 = 图([开始(), {"id": "分", "type": "if_else", "config": {"cases": [
            {"case_id": "甲", "logical_operator": "and", "conditions": [
                {"variable": {"source": "input", "pointer": "/单号"}, "operator": "is_not_empty"}]}]}},
          人(), 工具("写", "tv_写")],
         [("start", "分", "success"), ("分", "核", "甲"), ("分", "写", "else"),
          ("核", "写", "success"), ("写", "end", "success")])
问 = 校(g半)
ck("else 那条直达写入 → 阻断", 码 in 码们(问, V.阻断), 1, 码们(问))

print("▸ ⑤ 循环里的写入")
def 循环图(前面有人):
    节点 = [开始()] + ([人()] if 前面有人 else []) + [
        {"id": "L", "type": "loop", "config": {"max_iterations": 3}},
        工具("写", "tv_写", container="L")]
    边 = ([("start", "核", "success"), ("核", "L", "success")] if 前面有人 else [("start", "L", "success")]) + [
        ("L", "写", "loop_body"), ("L", "end", "loop_exit")]
    return 图(节点, 边)
问 = 校(循环图(True))
# 先验图搭对了:循环里的写入步骤走得到 —— 走不到时规矩直接跳过,「放行」会是假绿(第一版夹具就栽在这)
ck("夹具自检:循环有入口、写入步骤走得到", not {"SCOPE_NO_ENTRY", "NODE_UNREACHABLE", "EDGE_UNKNOWN_PORT"} & set(码们(问)), 1, 码们(问))
ck("循环前面有人 → 循环里的写入放行", 码 not in 码们(问), 1, 码们(问))
问 = 校(循环图(False))
ck("循环里外都没人 → 阻断", 码 in 码们(问, V.阻断), 1, 码们(问))

print("▸ ⑥ 用户输入开头 → 这条规矩不管")
问 = 校(直连(方式="用户输入"))
ck("用户输入开头 + 写入直连 → 不报", 码 not in 码们(问), 1, 码们(问))

print("▸ ⑦ 没给读写查询能力 → 记成「没查」")
问 = 校(直连(), 表=None)
跳 = [p for p in 问 if p["code"] == "CHECK_SKIPPED" and "Webhook" in p["消息"]]
ck("出现在「有一类没检查」里,且没有冒充通过", len(跳) == 1 and 码 not in 码们(问), len(跳), 码们(问))

print()
if 挂:
    print(f"❌ {len(挂)} 条没过:{挂}")
    sys.exit(1)
print(f"✅ {len(过)} 条全过")
