#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**`@echo` 里不许有反引号** —— 它在 shell 里是命令替换,会被真的执行。

2026-10-07 发现:Makefile 里有 **23 行** `@echo "...反引号包着的东西..."`,
而反引号在 shell 双引号内**仍然是命令替换**。证据是跑 `make test-orchestration`
时那行:

    /bin/bash: sql_columns_check: command not found

来自 `@echo "  `sql_columns_check` 只查列名不查类型 —— ..."`。

## 为什么这件事比「一行噪音」严重

那 23 行里被执行的东西包括:

    bash tools/fetch_model.sh              ← 会**真的下模型**(网络 + 几百 MB)
    MODEL_ADAPTER=anthropic make dev       ← 会**真的起服务**
    alembic check 2>&1 | tail -1

它们今天没造成事故,只是因为**那几行所在的目标恰好没被跑到**。

> 一行带反引号的 `@echo` 和一行普通的,**在 Makefile 源码上几乎长得一样** ——
> 而前者每次跑到都会执行一个命令,把 `command not found` 吐到 stderr,
> **然后继续往下跑**(`@echo` 的退出码是 echo 自己的,不是那次替换的)。
> 于是它既不报错、也不中断,只在一堆输出里多一行看着像警告的东西。

而我**自己当天就种了一个**:给新测试写登记说明时写了 `` `?|` ``、
`` `_规范()` `` 四处反引号。所以这条不能只写在 CLAUDE.md 里 ——
**记住的东西记不住,这就是为什么它要变成一个检查。**

## 判据

配方行(tab 开头)里的 `@echo`,**一个反引号都不许有**。
`@echo` 是纯输出,没有任何理由在里面做命令替换 —— 真要展开命令的那种行
不会写成 `@echo`。要在说明文字里引用代码,用单引号或「」。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"


def 查(路径):
    犯 = []
    for n, L in enumerate(open(路径, encoding="utf-8").read().split("\n"), 1):
        if not L.startswith("\t"):
            continue
        if "@echo" not in L:
            continue
        if "`" not in L:
            continue
        # 被执行的是成对反引号之间的东西 —— 报出来,让人看见它会跑什么
        跑的 = re.findall(r"`([^`]*)`", L)
        犯.append((n, L.strip()[:70], 跑的))
    return 犯


def main():
    总 = 0
    for 名 in ("Makefile",):
        p = os.path.join(ROOT, 名)
        if not os.path.isfile(p):
            # ⚠️ **找不到文件要喊,不许当成「没问题」。**
            # 一次「扫过了没犯规」和一次「文件没找到」,在那个 0 上长得一模一样。
            print(f"{R}❌ 找不到 {名} —— 这不是「通过」{D}")
            return 1
        犯 = 查(p)
        总 += len(犯)
        print(f"▸ {名}:扫了配方行里的 @echo,犯规 {len(犯)} 行")
        for n, 片, 跑的 in 犯:
            print(f"  {R}❌{D} 第 {n} 行会执行 {跑的}")
            print(f"      {片}")
    if 总:
        print(f"\n{R}❌ {总} 行 `@echo` 里有反引号 —— 它是 shell 的命令替换,"
              f"会被**真的执行**{D}")
        print("   改成单引号或「」。要展开命令的行不会写成 @echo。")
        return 1
    print(f"\n{G}✅ 没有 `@echo` 在偷偷执行命令{D}")
    return 0


# ── 咬合 ──────────────────────────────────────────────────────────
# 种一行 `\t@echo "x `whoami` y"` 回 Makefile → 这个脚本必须红,
# 并且报出「会执行 ['whoami']」。验过(2026-10-07)。
if __name__ == "__main__":
    sys.exit(main())
