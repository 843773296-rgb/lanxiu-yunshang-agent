#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测夹具的检查 —— **一道测不到东西的题,和一道通过的题,长得一模一样。**

## 为什么

评测题里挑的那个客户 / 着装人 / 工单,不是随便挑的 ——
挑的是**带某个状态**的那一个:量体已过期、余额和流水对不上、
名下有多个着装人、记录不全。

**而状态会漂。** 这一天(2026-09-15)同一个形状撞到**四次**:

    member_eval    题面写死的客户号,那个客户后来**一条积分流水都没有**,
                   判据却还说「他有 2 处余额对不上」
    growth_eval    每道题都挑了带特定状态的孩子,而**一条前提断言都没有**
    liability      工单的量体记录数变了,真值和数据对不上
    source_check   写死 `MT11` 当「溯不了源」的样本,**我把它修好了,检查当场红**

坏起来有两个方向,**后者危险得多**:

    永远失败   至少会有人来查
    **静默变成永远通过**   模型不再警告过期是**正确的**,而判据要的就是那个警告 ——
               成绩单上是一个漂亮的满分

## 判据:写死了夹具,就得声明前提(或声明它不依赖状态)

和 `case_check` 是同一个形状:**它不替你决定该不该改,只要求这个决定被写下来。**

    前提 = [(对象, 属性, 该是什么, 为什么这道题需要它), …]
    前提 = []          # 明说「这套题不依赖任何对象的状态」

**「忘了声明」和「真的不依赖」在代码里长得一模一样** —— 所以后者要写出来。
"""
import ast, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
夹具 = re.compile(r'"(C1\d{4}|W1\d{4}-\d|MW7\d+|AS6\d+|PT\d{2}|LT\d{2}|MT\d{2}|KF\d{2})"')
FAIL = []

咬合 = [
    ("把 tool_eval 里的 `前提 = [...]` 整段删掉",
     "写死了夹具的,都声明了前提"),
    ("把某条前提改成一个不成立的断言(比如说某客户有多个着装人,而他只有一个)",
     "声明的前提都还成立"),
]


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 有前提声明(src):
    """模块级有没有 `前提 = [...]` —— **用 AST,不用正则**。

    正则会把文档字符串里的示例当成真声明(`bite_check` 为这个栽过一次)。
    """
    try: tree = ast.parse(src)
    except SyntaxError: return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(x, "id", None) == "前提" for x in node.targets):
            return True
    return False


def main():
    print("评测夹具 · 检查")
    print("=" * 88)
    suites = sorted(glob.glob(os.path.join(ROOT, "agent", "*_eval.py")))
    缺, 有夹具 = [], 0
    for p in suites:
        src = open(p, encoding="utf-8").read()
        ids = sorted(set(夹具.findall(src)))
        if not ids: continue
        有夹具 += 1
        if not 有前提声明(src):
            缺.append(f"{os.path.basename(p)} 写死了 {ids[:4]},却没声明前提")
    ck("写死了夹具的,都声明了前提", not 缺, 有夹具,
       "；".join(缺[:3]) if 缺 else
       "**「忘了声明」和「真的不依赖」在代码里长得一模一样** —— 所以后者也要写出来")

    # ② 声明了的,得真的成立 —— 各套自己在 import 时断言,这里只确认它们跑得起来
    活, 死 = 0, []
    sys.path[:0] = [os.path.join(ROOT, x) for x in
                    ("agent", "backend", "knowledge", "agentsite")] + [ROOT]
    import importlib
    for p in suites:
        src = open(p, encoding="utf-8").read()
        if not 夹具.findall(src) or not 有前提声明(src): continue
        name = os.path.basename(p)[:-3]
        try:
            importlib.import_module(name); 活 += 1
        except SystemExit:
            死.append(f"{name}:**前提不成立,它自己退出了**")
        except Exception as e:
            死.append(f"{name}:{type(e).__name__} {str(e)[:40]}")
    ck("声明的前提都还成立", not 死, 活 + len(死),
       "；".join(死[:2]) if 死 else
       "**静默变成永远通过**比永远失败危险得多 —— 后者至少会有人来查")

    print()
    if FAIL:
        print(f"\033[31m❌ 评测夹具 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print("\033[32m✅ 评测夹具全部符合预期\033[0m")


if __name__ == "__main__":
    main()
