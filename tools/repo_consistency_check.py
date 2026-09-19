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

    # ⚠️ **读 HEAD 里的那份规格,不读工作区的那份。**
    #
    # 第一版读工作区,当场误伤:另一个会话正在写一条新规格 + 它要改的新代码,
    # **两样都还没提交** —— 那是完全正常的在途状态,而我的检查把它判成了
    # 「仓库不自洽」,门禁红了,所有人一起卡住。
    #
    # 要验的命题是「**仓库里那一版自不自洽**」,那就该两边都取 HEAD。
    # 拿工作区的规格去比 HEAD 的代码,比的是两个时刻 —— 那个命题没人关心,
    # 而且它**每个人写新东西的时候都会红**。
    #
    # > 一道会在正常工作中误拦的闸,迟早会被关掉。
    # > 这个项目里那句「误报比漏报贵」,说的就是这个。
    r = subprocess.run(["git", "show", "HEAD:tools/bite_specs.json"],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        print("  ❌ HEAD 里没有 tools/bite_specs.json")
        return 1
    规格 = json.loads(r.stdout)

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

    # ── 我们自己的技能,必须都进了版本库 ──────────────────────────
    #    2026-09-19 漏过一次:技能写好了、登记了、形状检查也绿,
    #    但 `.gitignore` 里那份**手写白名单**没加 —— 于是它在本地完全正常,
    #    而仓库里一个字都没有。**「装了」和「提交了」长得一模一样**,
    #    直到别人克隆下来发现技能不见了。
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "skills_own", os.path.join(ROOT, "agentsite", "skills_own.py"))
    so = importlib.util.module_from_spec(spec); spec.loader.exec_module(so)
    跟踪 = subprocess.run(["git", "ls-files", "agentsite/.claude/skills"],
                        capture_output=True, text=True, cwd=ROOT).stdout
    漏 = [n for n in so.OURS if f"agentsite/.claude/skills/{n}/" not in 跟踪]
    ck("自己写的技能都进了版本库", not 漏, len(so.OURS),
       f"没被 git 跟踪:{漏} —— 多半是 .gitignore 那份手写白名单漏了一行"
       if 漏 else "**「装了」和「提交了」长得一模一样**,所以要单独验")

    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print(f"✅ 仓库自洽 {len(DONE)} 条全过")
    return 0


咬合 = [
    ('**提交**一条指着未提交代码的规格(改工作区不触发 —— 见下)',
     '可执行的咬合规格,指的代码都已经在仓库里'),
    ('**提交**一行 check.sh 的 run,点名一个没提交的脚本',
     '门禁点名的脚本,仓库里都有'),
]
# ⚠️ 两条都**不进 `tools/bite_specs.json`**,原因有两层:
#
#   ① 可执行咬合跑在没有 `.git` 的副本里,这个脚本在那里直接退 3(不适用)
#   ② **破坏点必须是「提交」这个动作本身** —— 改工作区不会让它红,
#      因为它两边都取 HEAD(那是 2026-09-19 修的:读工作区会在
#      每个人写新东西的时候误红)
#
# 所以手工验法是:`git stash` 干净之后,**真提交一条坏规格**,跑一次看红,
# 再 `git reset --hard HEAD~1`。**验过一次的,是第一版(读工作区那版);
# 改成读 HEAD 之后重验过 —— 见提交记录。**

if __name__ == "__main__":
    sys.exit(main())
