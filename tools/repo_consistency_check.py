#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库自洽 —— **工作区绿,不等于仓库里那一版绿。**

## 起因:我把别人没提交的东西一起提交了

2026-09-19。`tools/bite_specs.json` 是一份**两个会话都在往里加条目**的清单,
而它是**一个文件**。我用 `git commit --only tools/bite_specs.json` 提交时,
把对方还没提交的两条规格一起带走了 ——
**`--only` 限定的是「哪些文件」,不是「文件里的哪几行」。**

后果不是文件冲突(没有冲突),而是**仓库内部不自洽**:
那两条规格要改的代码还在对方的工作区里,不在仓库里。
从那两次提交之间的任何一个点克隆下来,重放咬合会失败,
**而失败的理由看起来像「这条检查坏了」。**

> 这和「本地绿 ≠ CI 绿」是同一个形状,只是这次跨的是**人**,不是机器。
> 每个人的工作区都是绿的,合起来的那一版不是。

## 为什么它不在 `bite_check.py` 里

试过,不行:**咬合在没有 `.git` 的副本里跑**(`bite_run.py` 的黑名单
明确排掉了 `.git`,拷它又大又慢)。所以那条检查在副本里必然红,
报的是「对照就是红的」——**一条在沙箱里跑不起来的检查,
和一条不存在的检查,效果一样。**

它验的是**仓库的状态**,不是代码的逻辑,所以它该独立跑,
并且在不是 git 仓库的地方**明说自己不适用**,而不是假装通过。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []
DONE = []


def ck(name, ok, n, msg=""):
    DONE.append(name)
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 是git仓库():
    r = subprocess.run(["git", "rev-parse", "--git-dir"],
                       capture_output=True, cwd=ROOT)
    return r.returncode == 0


def main():
    print("仓库自洽 · 检查")
    print("=" * 80)

    if not 是git仓库():
        # **明说不适用,不假装通过。** 退出码 3 和重建互斥标记用的是同一个约定:
        # 「这里跑不了」和「这里跑过了都对」必须分得开。
        print("  ⏸ 这里不是 git 仓库(多半是咬合副本)—— 这条检查**不适用**,不是通过")
        return 3

    p = os.path.join(ROOT, "tools", "bite_specs.json")
    if not os.path.exists(p):
        print("  ❌ 找不到 tools/bite_specs.json")
        return 1
    规格 = json.load(open(p, encoding="utf-8"))

    # ── 每条 file 型规格要改的那段,必须在 HEAD 里找得到 ────────────
    对不上 = []
    n = 0
    for x in 规格:
        for f in x.get("file") or []:
            n += 1
            r = subprocess.run(["git", "show", f"HEAD:{f['path']}"],
                               capture_output=True, text=True, cwd=ROOT)
            if r.returncode != 0:
                对不上.append(f"{x['script']}:HEAD 里没有 {f['path']}")
            elif f.get("old") and f["old"] not in r.stdout:
                对不上.append(f"{x['script']}:要改的那段在 HEAD 的 {f['path']} 里找不到"
                            f" —— **这条规格指着还没提交的代码**")
    ck("可执行的咬合规格,指的代码都已经在仓库里", not 对不上, n,
       "；".join(对不上[:3]) if 对不上 else
       "**工作区绿不等于仓库里那一版绿** —— 规格和它要改的代码必须一起进仓库")

    # ── 顺带一条:门禁点名的脚本,仓库里都得有 ──────────────────────
    #    check.sh 里写着 `run "..." python3 某个脚本`,而那个脚本要是只在
    #    某个人的工作区里,克隆下来跑门禁会红在「文件不存在」上,
    #    而那看起来像是环境问题,不像是有人漏提交了。
    import re
    ck_sh = subprocess.run(["git", "show", "HEAD:check.sh"],
                           capture_output=True, text=True, cwd=ROOT).stdout
    缺 = []
    脚本 = re.findall(r"^run \".*?\" (?:\S*python\S*) (\S+\.py)", ck_sh, re.M)
    for s in 脚本:
        r = subprocess.run(["git", "show", f"HEAD:{s}"], capture_output=True, cwd=ROOT)
        if r.returncode != 0:
            缺.append(s)
    ck("门禁点名的脚本,仓库里都有", not 缺, len(脚本),
       f"只在某个人的工作区里:{缺[:3]}" if 缺 else
       "克隆下来就能跑 —— 漏提交一个脚本,门禁会红在「文件不存在」上,"
       "而那看起来像环境问题,不像有人漏提交了")

    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print(f"✅ 仓库自洽 {len(DONE)} 条全过")
    return 0


咬合 = [
    ('往 bite_specs.json 里加一条指着未提交代码的规格',
     '可执行的咬合规格,指的代码都已经在仓库里'),
    ('往 check.sh 里加一行 run,点名一个没提交的脚本',
     '门禁点名的脚本,仓库里都有'),
]
# ⚠️ 这两条**不进 `tools/bite_specs.json`**:可执行咬合跑在没有 `.git` 的副本里,
#    而这个脚本在那里会直接退 3(不适用)。记录留在这里说明该怎么手工验,
#    真要验就在真仓库里改坏再跑一次 —— 两条都当场验过。

if __name__ == "__main__":
    sys.exit(main())
