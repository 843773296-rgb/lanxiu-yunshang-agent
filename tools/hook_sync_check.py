#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库里的 hook 和**真正在跑的那份**一样吗。

## 为什么需要它

2026-10-04 栽了一次,而且栽得很像成功:

我修了 `tools/hooks/push-then-ci.mjs`(它把被新一轮取代的 `cancelled`
当成了 CI 红),补了四条自测,它自带的套件 22/22 全绿,提交推送。
**而真正在喊话的是 `~/.claude/hooks/push-then-ci.mjs` —— 9 月 17 日的一份拷贝。**

> **把「我改了」当成了「它生效了」。**

这次尤其像真的:修完之后我确实看到提示变成了「上一次是绿的」——
那只是因为那一刻最新一轮**恰好**绿了。
**一个改了而没生效的 hook,和一个生效了的,在那一句提示上长得一模一样。**

而四份 hook 里有三份现在内容一样 ——
**正因为它们一样,才看不出这个机制会漂。**

## 判据

逐个比 `tools/hooks/*.mjs` 和 `~/.claude/hooks/` 下的同名文件:
· 内容不同 → **红**(改了仓库那份而没生效,或者反过来)
· 装的那份不存在 → **「不适用」,不是通过**(比如 CI、或者另一台机器)
· 是软链而且指向仓库 → **最好的情况**,它永远不会漂

⚠️ **这一条不会自己去同步。** 写 `~/.claude/` 是改用户的运行环境,
要用户自己按一下 —— 而判据的职责是**让漂移被看见**,不是替人决定。
"""
import os
import sys


# ── 咬合记录 ──────────────────────────────────────────────────────────
#
# ⚠️ **这一条是被棘轮顶出来的,而它顶对了。**
# 我在加这条检查时写的理由是「它现在就是红的,所以不需要咬合」——
# 而那个理由只盖住了咬合的第 ② 关(改坏要红),
# 没盖住第 ① 关(**对照先绿**)和第 ③ 关(**红的必须是点名那一条**)。
# 而第三关正是 CLAUDE.md 里写着「我手工咬合过五六次,
# 每次都只验到『它红了』」的那一关。
# > **我给自己开了个例外,而那条规矩本来就是为了防这种例外。**
#
# 规格在 `tools/bite_specs.json`,`python3 tools/bite_run.py --only hook_sync_check`
# 三关都要过。
#
# 破坏点挑的是**「判据自己的路径」**而不是「某个 hook 的内容」——
# 理由:内容漂移这条路径**现在本来就是红的**(`push-then-ci.mjs` 真的漂着),
# 在一条已经红的路径上注入破坏,**红了也证明不了是注入起的作用**。
# > 「本来就红」和「因为我改坏了才红」,在那个 ❌ 上长得一模一样。
咬合 = [
    ('把 `tools/hooks` 这个路径改成一个不存在的目录'
     '(判据扫不到任何 hook,而它该报「没扫到」不是「都同步了」)',
     '一个 .mjs 都没扫到'),
]

# ⚠️ **上面那条规格在 `bite_run` 里跑不起来,而原因不在规格** ——
# `bite_run` 的第 ① 关要对照先绿,而这条检查的对照依赖本机状态,
# 本机现在真的漂着(`push-then-ci.mjs`)。它报的就是这句:
# 「**对照就是红的,这条咬合证明不了任何事**」。
#
# 所以这条检查另外给了 `AIMC_HOOKS_DIR`,让对照目录可注入,
# 四种判法在夹具上**手工验过**(2026-10-04):
#
#     ① 夹具里四份都一致            → 绿,退出码 0
#     ② 改一个字                     → 红在「**内容不同**」
#     ③ 装的那份不存在               → **⏸ 不适用,退出码 0**(不是红)
#     ④ 软链指向仓库                 → ✅「**它永远不会漂**」
#
# 四种各自报对了理由 —— 而第 ③ 条尤其要紧:
# **「没装」和「装的那份对得上」在一个绿勾上长得一模一样**,
# 所以它必须说「不适用」而不是打勾。
#
# 等 `push-then-ci.mjs` 同步之后,`bite_run --only hook_sync_check` 也会通。

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
仓库hook = os.path.join(根, "tools", "hooks")
# ⚠️ **装的那份在哪,可以用环境变量指定。** 不是为了方便 ——
# 是因为**一条没法隔离测试的检查,没法被证明**:
# 这条检查的对照依赖本机状态,而本机现在真的漂着,
# 于是 `bite_run` 报「**对照就是红的,这条咬合证明不了任何事**」。
# > 「它本来就红」和「因为我改坏了才红」,在那个 ❌ 上长得一模一样。
# 所以给它一个可注入的对照目录,三关就能在夹具上验。
#
# ⚠️ 而**它比对的是哪个目录,每次都印出来** ——
# 否则有人把它指到一个永远对得上的目录,这条检查就变成了一句好话。
装的 = os.environ.get("AIMC_HOOKS_DIR") or os.path.expanduser("~/.claude/hooks")


def main():
    print("hook 同步对账 · 仓库里的和真正在跑的那份")
    print("=" * 76)
    if not os.path.isdir(仓库hook):
        print(f"  ❌ 找不到 {仓库hook} —— **这不叫「没有 hook」,叫路径写错了**")
        return 1
    们 = sorted(f for f in os.listdir(仓库hook) if f.endswith(".mjs"))
    # ⚠️ **样本量下限**:空集合上「每一份都一样」恒为真。
    if not 们:
        print(f"  ❌ 一个 .mjs 都没扫到({仓库hook})—— 不叫「都同步了」,叫没扫到")
        return 1
    print(f"  仓库里 {len(们)} 份 hook;比对的是 `{装的}`"
          + ("  ⚠️ **这是 `AIMC_HOOKS_DIR` 指定的,不是默认位置**"
             if os.environ.get("AIMC_HOOKS_DIR") else ""))

    漂 = []
    不适用 = []
    软链 = []
    一样 = []
    for f in 们:
        仓 = os.path.join(仓库hook, f)
        装 = os.path.join(装的, f)
        if os.path.islink(装):
            指向 = os.path.realpath(装)
            if 指向 == os.path.realpath(仓):
                软链.append(f)
                continue
            漂.append((f, f"软链指向的是**另一个文件**:{指向}"))
            continue
        if not os.path.exists(装):
            不适用.append(f)
            continue
        with open(仓, "rb") as a, open(装, "rb") as b:
            if a.read() == b.read():
                一样.append(f)
            else:
                漂.append((f, "内容不同 —— **改了仓库那份,而跑的是装的那份**"))

    for f in 软链:
        print(f"  ✅ {f}  软链指向仓库 —— **它永远不会漂**")
    for f in 一样:
        print(f"  🟡 {f}  内容一样(**而它是拷贝,下次改完还会漂**)")
    for f in 不适用:
        # ⚠️ 「没装」和「装的那份对得上」要分开说。
        print(f"  ⏸ {f}  `~/.claude/hooks/` 里没有它 —— "
              f"**这不是通过,是不适用**(CI 或另一台机器上就是这样)")
    for f, 为什么 in 漂:
        print(f"  ❌ {f}  {为什么}")

    if 漂:
        print(f"\n  ❌ {len(漂)} 份漂了。**改了仓库那份不等于它生效了。**")
        print(f"     同步(要你自己按,这条判据不替你写 `~/.claude/`):")
        for f, _ in 漂:
            print(f"       cp {os.path.join('tools/hooks', f)} ~/.claude/hooks/{f}")
        print(f"     ⚠️ **更好的办法是软链**,那样它永远不会再漂:")
        for f, _ in 漂:
            print(f"       ln -sf {os.path.join(根, 'tools/hooks', f)} "
                  f"~/.claude/hooks/{f}")
        return 1

    if 一样 and not 软链:
        print(f"\n  🟡 {len(一样)} 份内容一样,**但它们都是拷贝** —— "
              f"下次改完仓库那份,跑的还是旧的。")
        print(f"     ⚠️ **三份现在一样,正因为它们一样,才看不出这个机制会漂。**")
        print(f"     这一条现在是绿的,而它绿得很脆。")
    print(f"\n  ✅ 没有漂的(一样 {len(一样)} · 软链 {len(软链)} · "
          f"不适用 {len(不适用)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
