#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定义编译器 —— **把版本化定义编译成可执行图**(规格 §16.1)。

## 边界:不把用户文本当代码

规格 §16.1 给这个组件写的边界是:「**不把用户文本当 Python/JS eval**;
模型不生成可执行后端代码」;§17.4 再说一次:「编排 DSL、条件表达式和转换函数
使用**受限 AST/白名单**,不允许 eval 任意代码」。

所以这里没有 `eval`、没有 `exec`、没有 `__import__`。转换操作是一张
**白名单表**,表里没有的操作在编译期就报错 —— 不是运行时。

> 一个能 eval 的字段就是一条远程代码执行通道,而它在界面上只是个文本框。

## 编译期做什么、运行期做什么

编译期:**所有和输入无关的事**。查节点类型、解析绑定引用的形状、算拓扑序、
把条件分支的顺序固定下来。这些都只依赖定义,所以可以一次算好、连同定义一起冻结。

运行期只剩「按当前状态取值、调外部、写结果」。这样分的好处很实际:
**编译失败在冻结版本的时候就发生**,不是在试运行第 7 个节点的时候。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "contract"))
import dsl as DS  # noqa: E402
import validator as V  # noqa: E402


class 编译失败(Exception):
    def __init__(self, 问题们):
        self.问题们 = 问题们
        阻 = [p for p in 问题们 if p["级别"] == V.阻断]
        super().__init__(f"{len(阻)} 条阻断:" +
                         "; ".join(f"{p['code']}@{p['node_id']}" for p in 阻[:4]))


# ── 转换操作白名单(§6.1 字段转换:「白名单转换」)──────────────────
#
# 每条操作声明:要几个操作数、干什么。**表里没有的操作编译期就报错。**
# 这张表短是有意的:它长起来的那一天,说明有人在往里塞一门语言。
转换操作 = {
    "pick":        "从对象里挑几个字段(不改值)",
    "concat":      "把几个字符串按顺序拼起来(**不做隐式类型转换**)",
    "to_number":   "文本 → 数字;转不了就是节点失败,不是静默给 0",
    "to_string":   "数字 → 文本",
    "join":        "列表 → 字符串(要给分隔符)",
    "length":      "列表/字符串/对象的长度",
    "default":     "值缺失时用一个**常量**兜底(不是用别的字段兜底)",
    "merge_objects": "把几个对象合成一个(键冲突时**报错**,不静默后盖前)",
}


def 编译(定义, *, 依赖存在=None, 父额度=None):
    """返回可执行计划。**先跑校验** —— 有阻断就不编译。

    这条顺序是故意的:一张不合法的图编译出来的「计划」是什么,没人说得清。
    """
    问题们 = V.校验(定义, 依赖存在=依赖存在, 父额度=父额度)
    if V.有阻断(问题们):
        raise 编译失败(问题们)

    按id = {n["id"]: n for n in 定义["nodes"]}
    入口 = next(n["id"] for n in 定义["nodes"] if n["type"] == "start")

    # 后继表按端口分开存 —— 运行期要按「这一步该走哪个端口」查下一步,
    # 而不是拿到一串邻居再去猜。
    后继 = {i: {} for i in 按id}
    for e in 定义.get("edges", []):
        口 = e["port"]
        键 = (口, e.get("branch_key")) if 口 == DS.分支 else (口, None)
        后继[e["source"]].setdefault(键, []).append(e["target"])

    # 转换操作白名单在编译期查
    for n in 定义["nodes"]:
        if n["type"] != "transform":
            continue
        for op in (n.get("config") or {}).get("operations") or []:
            名 = op.get("op") if isinstance(op, dict) else None
            if 名 not in 转换操作:
                raise 编译失败([V.问(
                    V.阻断, "TRANSFORM_UNKNOWN_OP",
                    f"字段转换用了不在白名单里的操作 {名!r}",
                    f"白名单里有:{sorted(转换操作)} —— "
                    f"**不允许把任意表达式放进来执行**(§17.4)",
                    node_id=n["id"], field_path="config.operations")])

    return dict(
        定义=定义,
        逻辑哈希=DS.逻辑哈希(定义),
        入口=入口,
        节点=按id,
        后继=后继,
        输出Schema=定义.get("output_schema") or {},
        编译警告=[p for p in 问题们 if p["级别"] == V.警告],
    )
