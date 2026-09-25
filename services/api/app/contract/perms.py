#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""权限矩阵 —— **授权判定的唯一来源**(规格 §15.3)。

## 三档,不是两档

规格那张表里有三种格子:**是 / 否 / 可授权**(还有「默认否」「有额度时」「分别授权」)。
把「可授权」压成「是」或「否」都会错:

  · 压成「是」→ 默认给出了不该默认给的权限
  · 压成「否」→ 管理员没法按需授权,于是有人去改代码绕过

所以这里保留三档,并且**「可授权」默认关闭**,要有一条显式的专项授权记录才打开。

## 一条硬规矩:不能通过邀请获得自己没有的权限

规格 §15.3 最后一句。落点在 `可以授予吗()` —— 授予集合必须是授予人权限的子集。
**这条不做成结构就只是一句话**,而一句话拦不住任何人。
"""

是 = "allow"            # 默认有
否 = "deny"             # 不给,管理员也不能通过角色给(要改角色定义)
可授权 = "grantable"     # **默认关闭**,要专项授权才开
有额度 = "quota"         # 有权限,但受配额/预算闸限制

角色表 = [
    ("viewer", "查看者"),
    ("editor", "编辑 / 知识运营"),
    ("annotator", "标注 / 测试"),
    ("trainer", "训练操作员"),
    ("approver", "审核发布者"),
    ("admin", "管理员"),
]
角色们 = [r for r, _ in 角色表]
角色中文 = dict(角色表)

# 能力 → {角色: 档位}。**对齐规格 §15.3 那张表,一行都不许省。**
矩阵 = {
    "查看有权配置":
        dict(viewer=是, editor=是, annotator=是, trainer=是, approver=是, admin=是),
    "改 Prompt/知识候选":
        dict(viewer=否, editor=是, annotator=可授权, trainer=否, approver=可授权, admin=是),
    "改训练样本":
        dict(viewer=否, editor=可授权, annotator=是, trainer=可授权, approver=否, admin=是),
    "运行评测":
        dict(viewer=否, editor=有额度, annotator=是, trainer=是, approver=是, admin=是),
    "提交真实训练":
        dict(viewer=否, editor=否, annotator=否, trainer=有额度, approver=否, admin=可授权),
    "生产审核/发布/回滚":
        dict(viewer=否, editor=否, annotator=否, trainer=否, approver=可授权, admin=是),
    # ⚠️ 这一条连管理员都是「可授权」而不是「是」:
    # 规格原文写的是「**仍需专项权限**」—— 独立测试集的答案一旦被人看到,
    # 那套题就再也不能当独立验收用了(见 agent-eval-sets 的隔离纪律)。
    "查看敏感输入/独立测试答案":
        dict(viewer=否, editor=否, annotator=可授权, trainer=否, approver=否, admin=可授权),
    "配置密钥与预算":
        dict(viewer=否, editor=否, annotator=否, trainer=否, approver=否, admin=是),
    "查看审计":
        dict(viewer=否, editor=否, annotator=可授权, trainer=否, approver=是, admin=是),
}

能力们 = list(矩阵)


def 判(能力, 角色, 专项=()):
    """返回 (能不能, 为什么)。**专项授权只能打开「可授权」的格子** ——
    打不开「否」,否则专项授权就变成了万能钥匙。"""
    if 能力 not in 矩阵:
        raise KeyError(f"没有这条能力:{能力} —— 现有 {能力们}")
    if 角色 not in 角色们:
        raise KeyError(f"没有这个角色:{角色} —— 现有 {角色们}")
    档 = 矩阵[能力][角色]
    if 档 == 是:
        return True, "角色默认有"
    if 档 == 有额度:
        return True, "角色有,但受配额/预算闸限制 —— 调用方必须再过一道额度检查"
    if 档 == 可授权:
        有 = 能力 in set(专项 or ())
        return 有, ("有专项授权" if 有 else
                   "这一格是「可授权」,**默认关闭** —— 要一条显式的专项授权记录")
    return False, "这个角色不给这条能力(要给就得改角色定义,不是发专项授权)"


def 可以授予吗(授予人角色, 授予人专项, 要给的角色, 要给的专项):
    """**不能通过邀请获得自己没有的权限**(§15.3)。

    判据:要给的那套权限,在**每一条能力**上都不能超过授予人自己有的。
    返回 (行不行, [超出的能力])。
    """
    超 = []
    for 能力 in 能力们:
        他行, _ = 判(能力, 要给的角色, 要给的专项)
        我行, _ = 判(能力, 授予人角色, 授予人专项)
        if 他行 and not 我行:
            超.append(能力)
    return (not 超), 超
