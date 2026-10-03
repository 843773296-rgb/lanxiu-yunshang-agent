#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「这条不一致是别人正在改,还是我忘了重导」—— **这个判断的唯一实现**。

## 为什么要单独一个文件

2026-10-03 的 `make test` 同时红在两处:铁律同步(`prompts.py` 的 TL31)和
知识库同步(10 份 md)。两处要问的是**同一个问题**:

> 一条「文件改了没重导」的红,和一条「别人的改动还没提交」的红,
> **在判据的输出上长得一模一样** —— 而第一种该导,第二种绝不能导
> (那是把半成品灌进后台,还给它发一个正式版本号)。

这个仓库常有并行会话,规矩是「**只提自己的路径,绝不替别人提交半成品**」——
**导入也一样**。

而写两份实现的下场这个仓库记着:「同一类判断在两处用两套算法,
用户会看到两个页面给出矛盾的结论」。所以只有这一份。

## 两个粒度

- `脏文件们(目录)` —— 哪些文件有未提交的改动(知识库那条用:一个文件一份语料)
- `改动碰到的段(文件, 起点们)` —— 改动落在哪几个「段」上
  (铁律那条用:一个文件里有 79 条规矩,要分到条)

## ⚠️ 查不出来时返回「查不出来」,不返回空

空集合会让调用方判成「没有一条落在未提交改动里」→ 全部报红,
而那恰好是错的那一边。**查不出来就该说「分不清」,不该假装自己分清了。**
(这个仓库记着:`.get(k, 默认)` 把「没配」和「配的就是默认」写成了同一件事。)

## ⚠️ 行号只在这一刻有效

`改动碰到的段` 靠行号把改动映射到段。行号随编辑而漂,所以它**只给提示用**,
不当对外的引用 —— 和 `parser.py` 里「起始行只给检查用」是同一条规矩。
"""
import os
import re
import subprocess


def _跑git(仓库, *参):
    try:
        r = subprocess.run(["git", *参], cwd=仓库, capture_output=True,
                           text=True, timeout=10)
        return (r.returncode == 0), r.stdout
    except Exception:
        return False, ""


def 脏文件们(仓库, 路径):
    """`路径`(目录或文件)下有未提交改动的文件名集合。

    返回 (查得出来吗, {相对仓库根的路径})。
    """
    好, 出 = _跑git(仓库, "status", "--porcelain", "--", 路径)
    if not 好:
        return False, set()
    名 = set()
    for ln in 出.splitlines():
        if len(ln) > 3:
            # `XY 路径` / 改名是 `XY 旧 -> 新`,取后面那个
            p = ln[3:].strip().strip('"')
            名.add(p.split(" -> ")[-1])
    return True, 名


def 改动碰到的段(仓库, 文件, 段起点们):
    """`文件` 里未提交的改动,落在哪几个段上。

    `段起点们`:[(起始行号, 段名)],按行号升序。一个改动行属于
    **它上面最近的那个段起点**。

    返回 (查得出来吗, {段名}, 改了几行)。
    """
    好, 出 = _跑git(仓库, "diff", "-U0", "--", 文件)
    if not 好:
        return False, set(), 0
    if not 出.strip():
        return True, set(), 0            # 干净 —— 查得出来,而且一条都没有
    改行 = []
    for h in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", 出, re.M):
        起 = int(h.group(1))
        数 = int(h.group(2) or 1)
        改行 += list(range(起, 起 + max(数, 1)))
    碰到 = set()
    for L in 改行:
        前 = [(n, k) for n, k in 段起点们 if n <= L]
        if 前:
            碰到.add(前[-1][1])
    return True, 碰到, len(改行)


def python里的Rule起点(文件路径, 正则=r'\s*Rule\("([A-Z]+\d+)"'):
    """扫出 `Rule("TLxx"` 这种段起点。给 `改动碰到的段` 喂。"""
    try:
        文 = open(文件路径, encoding="utf-8").read().splitlines()
    except OSError:
        return []
    出 = []
    for i, ln in enumerate(文):
        m = re.match(正则, ln)
        if m:
            出.append((i + 1, m.group(1)))
    return 出
