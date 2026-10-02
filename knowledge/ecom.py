#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""电商运营里**业务拍过板的数** —— 从 `15-电商运营.md` 第一节那张表读,不在代码里另写一份。

原来缺货容忍(0.95)和压货档写在 `stockalert.py`、定价系数(2.5)写在 `margin.py`,
各自带一行「业务 09-29 拍板」的注释。人看不到代码,而 md 里要是再抄一份,
**改一份不改另一份就开始漂,漂了不报错**。所以 md 那张表是唯一来源,代码从它读。

读不到就**抛错,不给默认值** —— 一个静默兜底的 0.95,和业务拍的 0.95 在运行时长得一模一样,
而哪天 md 被改坏了,系统会照旧跑着一个没人确认过的数。
"""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(HERE, "15-电商运营.md")


def 表():
    """第一节「我们的决定」那张表 → {键: (值原文, 依据)}。"""
    t = open(MD, encoding="utf-8").read()
    m = re.search(r"^## 一、我们的决定.*?\n(.*?)(?=^## )", t, re.S | re.M)
    if not m:
        raise RuntimeError(f"{os.path.basename(MD)} 里没有「一、我们的决定」那一节 —— 不给默认值")
    out = {}
    for l in m.group(1).split("\n"):
        c = [x.strip() for x in l.strip().strip("|").split("|")]
        if len(c) != 4 or c[0] in ("键", "") or set(c[0]) <= set("-"):
            continue
        out[c[0]] = (c[2], c[3])
    return out


def 依据(键):
    return 表()[键][1].replace("`", "")


def 数(键):
    return float(表()[键][0])


def 档(键):
    """「365:建议下架 / 180:清仓候选」→ [(365, "建议下架"), (180, "清仓候选")],按天数从大到小。"""
    out = []
    for 段 in 表()[键][0].split("/"):
        天, 名 = re.split(r"[::]", 段.strip(), 1)
        out.append((int(天), 名.strip()))
    return sorted(out, reverse=True)
