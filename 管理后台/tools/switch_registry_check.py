#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开关登记 · 改了线上行为的设置,改的地方必须留一条**登记过的**审计(用户 2026-10-28 拍「开关监督」)。

工作台「开关」那块(GET /switches)只看得见 `workflows_api.开关们` 里登记过的审计动作。
所以一处新写开关的代码,要么没写审计、要么写了个没登记的动作名 —— 两种都是**开关变了、工作台上一片安静**,
而那正是并行会话三个技能两天没挂上的形状。

## 判据(按代码结构,不按字面猜)

  正向:每一处**写开关**的 SQL(写聊天接管 / 定时开关 / 环境指针)所在的那个函数里,
        必须调 `_审计(c, me, "<动作>", …)`,而且 <动作> 在 `开关们` 里
  反向:`开关们` 里登记的每个动作,代码里都真有一处 `_审计` 在写 —— 登记了没人写,工作台那一类永远是空的,
        而「这几天没人动过」和「改了根本不记」长得一样
  样本量:一处写开关的 SQL 都没扫到 → 红(多半是扫的目录或写法变了,不是「都合规」)

跑:`python3 tools/switch_registry_check.py [源码目录]`(不给就扫 services/api/app)
"""
import ast
import os
import re
import sys

这 = os.path.dirname(os.path.abspath(__file__))
默认目录 = os.path.join(os.path.dirname(这), "services", "api", "app")
# 写开关的 SQL 长什么样:对列 / 表的**写**,读不算
写开关 = re.compile(r"(chat_takeover_enabled\s*=|schedule_enabled\s*=|insert\s+into\s+(environment_bindings|workflow_schedules)"
                   r"|update\s+environment_bindings|production_version_no\s*=)", re.I)
G, R, D = "\033[32m", "\033[31m", "\033[0m"


def 登记的动作(目录):
    """从 workflows_api.py 里读 `开关们 = {…}` 的键 —— 读源码不 import(import 要连库)。"""
    树 = ast.parse(open(os.path.join(目录, "workflows_api.py"), encoding="utf-8").read())
    for n in 树.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "开关们" for t in n.targets):
            return {k.value for k in n.value.keys if isinstance(k, ast.Constant)}
    return None


def 扫(目录):
    """→ [(文件, 行, 函数名, {这个函数里 _审计 写的动作})] 每一处写开关的 SQL 一条;以及全部 _审计 动作。"""
    写们, 全部动作 = [], set()
    for 名 in sorted(os.listdir(目录)):
        if not 名.endswith(".py"):
            continue
        树 = ast.parse(open(os.path.join(目录, 名), encoding="utf-8").read())
        for f in ast.walk(树):
            if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            动作 = {c.args[2].value for c in ast.walk(f)
                    if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "_审计"
                    and len(c.args) >= 3 and isinstance(c.args[2], ast.Constant)}
            全部动作 |= 动作
            # 只认**直接**在这个函数里的 SQL(嵌套函数自己算一个)
            for s in ast.walk(f):
                if isinstance(s, ast.Constant) and isinstance(s.value, str) and 写开关.search(s.value):
                    内层 = [g for g in ast.walk(f) if g is not f and isinstance(g, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and any(x is s for x in ast.walk(g))]
                    if not 内层:
                        写们.append((名, s.lineno, f.name, 动作))
    return 写们, 全部动作


def main(目录=默认目录):
    print("▸ 开关登记:写开关的地方必须留一条登记过的审计(工作台「开关」那块才看得见)")
    登记 = 登记的动作(目录)
    if not 登记:
        print(f"  {R}❌ workflows_api.py 里没找到 `开关们` —— 读不到登记表不是通过{D}")
        return 1
    写们, 全部动作 = 扫(目录)
    print(f"  扫到 {len(写们)} 处写开关的 SQL · 登记的动作 {len(登记)} 个")
    挂 = []
    if not 写们:
        挂.append("一处写开关的 SQL 都没扫到 —— 多半是目录或写法变了,不是「都合规」")
    for 文件, 行, 函数, 动作 in 写们:
        if not (动作 & 登记):
            挂.append(f"{文件}:{行} {函数}() 写了开关,而这个函数里 "
                      + (f"审计动作 {sorted(动作)} 都没登记在 开关们 里" if 动作 else "没调 _审计")
                      + " —— 改了工作台上看不见")
    for a in sorted(登记 - 全部动作):
        挂.append(f"`开关们` 登记了「{a}」,而代码里没有一处 _审计 在写它 —— 工作台那一类会永远是空的")
    if 挂:
        for x in 挂:
            print(f"  {R}❌ {x}{D}")
        return 1
    print(f"  {G}✅ {len(写们)} 处写开关的地方都留了登记过的审计;登记的 {len(登记)} 个动作都有人在写{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 默认目录))
