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
import subprocess
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
    # 2026-10-14 改成比内容之后补的,**实跑验过**:
    # 拿 `AIMC_HOOKS_DIR` 指一个临时目录(不碰用户真正的 `~/.claude/hooks`),
    # 里面四份软链都指向另一个检出 → 绿;再把其中一份的内容改掉 → 必须红。
    ('软链指向另一个检出的同名 hook,而**把那边那份的内容改掉**'
     '(路径照旧不等,变的只有内容 —— 这是改成比内容之后唯一该判红的情形)',
     '而内容已经不一样了'),
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


def _自测():
    """只验那个判据函数本身。**不碰任何文件,所以能安心进门禁。**

    ⚠️ 为什么不在这里做端到端(造 AIMC_HOOKS_DIR + 给仓库那份加一行未提交改动):
       那要**在主工作区做破坏**,而并发会话可能正好读到 ——
       `intent/bite-debt.md` 那条规矩明说「不在主工作区做破坏,在副本里做」。
       端到端那一轮 2026-11-04 实跑验过(7 条,两个方向各只有它会挂),
       记录在 HANDOFF.md;这里守的是**判据的那一行逻辑**。
    """
    import tempfile
    过, 败 = 0, []

    def ck(名, 实, 期):
        nonlocal 过
        if 实 == 期:
            过 += 1
            print(f"  ✅ {名}")
        else:
            败.append(名)
            print(f"  ❌ {名}  期望[{期}] 实得[{实}]")

    print("hook 同步对账 · 判据自测")
    靶 = os.path.join("tools", "hooks", "handoff-gate.mjs")
    r = subprocess.run(["git", "-c", "core.quotepath=false", "show", f"HEAD:{靶}"],
                       cwd=根, capture_output=True, timeout=30)
    if r.returncode != 0 or not r.stdout:
        # ⚠️ **「取不到样本」必须和「验过了」分开。** 没有这一闸,浅克隆或
        #    新仓库上这几条会全部自动成立,而输出看起来一模一样。
        print("     ℹ️ 取不到 HEAD 上的 hook(浅克隆/新仓库?)—— "
              "**下面几条没东西可验,不是验过了**")
        return 0
    d = tempfile.mkdtemp(prefix="hooksync_self_")
    try:
        同 = os.path.join(d, "same")
        with open(同, "wb") as f:
            f.write(r.stdout)
        ck("① 目标内容 = 本检出 HEAD 版本 → True(差异全在未提交改动里)",
           是本检出的已提交版本(靶, 同), True)

        异 = os.path.join(d, "diff")
        with open(异, "wb") as f:
            f.write(r.stdout + "// zzz\n".encode("utf-8"))
        ck("② 目标内容 ≠ HEAD 版本 → False(可能真漂了,照旧判红)",
           是本检出的已提交版本(靶, 异), False)

        # ③ **反向,而且是这三条里最要紧的一条。**
        #    取不到 git 对象时必须回 False —— 写成 True 的话,所有「查不到」
        #    都会被当成「还没推」放过去,**那是用一个放宽换掉了整道闸**。
        ck("③ HEAD 上没有这个路径 → False(查不到要算成可能真漂了,宁可多红)",
           是本检出的已提交版本(os.path.join("tools", "hooks", "不存在的.mjs"), 同),
           False)

        # ④ 反向:目标文件根本读不到 → 也必须 False,不能抛异常
        ck("④ 目标文件读不到 → False,而且不许崩",
           是本检出的已提交版本(靶, os.path.join(d, "没有这个文件")), False)
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    if 败:
        print(f"  ❌ {len(败)} 条没过:{'、'.join(败)}")
        return 1
    print(f"  ✅ 判据自测 {过} 条全过(含两条反向:查不到 / 读不到,都必须判成「可能真漂了」)")
    return 0


def 是本检出的已提交版本(相对路径, 目标文件):
    """目标文件的内容,是不是**本检出 HEAD 上**那个版本?

    ⚠️ 这是用来把「还没推」和「真漂了」分开的判据。**不猜、不看时间戳,只比
       git 对象**:如果目标 == 本检出的 HEAD 版本,那仓库那份和它的差异就**全部
       来自未提交的改动** —— 推上去、让那个检出 pull 就一致了。
    ⚠️ 中文路径要 `core.quotepath=false`(这个仓库大半文件名是中文)。
    ⚠️ 取不到就回 False —— **「查不到」要算成「可能真漂了」**,
       宁可多红一次,也不要把一次真漂移放过去。
    """
    try:
        r = subprocess.run(
            ["git", "-c", "core.quotepath=false", "show", f"HEAD:{相对路径}"],
            cwd=根, capture_output=True, timeout=30)
        if r.returncode != 0:
            return False
        with open(目标文件, "rb") as b:
            return r.stdout == b.read()
    except Exception:
        return False
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
    别检出 = []          # 软链指向**另一个检出**的同名 hook,而内容一致
    还没推 = []          # 仓库这份改了还没推,目标 = 本检出的 HEAD 版本
    for f in 们:
        仓 = os.path.join(仓库hook, f)
        装 = os.path.join(装的, f)
        if os.path.islink(装):
            指向 = os.path.realpath(装)
            if 指向 == os.path.realpath(仓):
                软链.append(f)
                continue
            # ⚠️⚠️ 2026-10-14 改(用户拍)。原来这里**无条件判红**,
            # 而那让「在 git worktree 里干活」永远过不了门禁:
            # `~/.claude/hooks` 的软链只能指**一个**检出,从另一个检出跑必然不等。
            # 实情是四份 hook 的 md5 **完全一致** —— 它要守的东西事实上成立,
            # 红的只是路径不等。
            #
            # 而比路径不只是在 worktree 上误报,它还**漏掉一种真故障**:
            # > 一条「软链指向另一个检出但内容一致」,和一条「指向另一个检出
            # > **而且内容已经漂了**」,**在那句「软链指向的是另一个文件」上
            # > 长得一模一样。**
            #
            # 所以修法是把混在一条里的两件事拆开(和 2026-10-13 修
            # `queue_view_check`、10-14 修 `rating_rebuild_check` 同一个做法):
            #   **内容一致吗** → 判红(两个检出都验得到,不看碰巧指着谁)
            #   **指向哪个检出** → 打印,不判红
            if not os.path.exists(指向):
                漂.append((f, f"软链指向一个**不存在的文件**:{指向} —— "
                              f"hook 根本跑不起来"))
                continue
            with open(仓, "rb") as a, open(指向, "rb") as b:
                if a.read() == b.read():
                    别检出.append((f, 指向))
                # ⚠️⚠️ 2026-11-04 再拆一层(用户拍 + 用户执行)。
                #    10-14 那次把「指向哪个检出」和「内容一致吗」拆开了,
                #    而「内容不一致」里**还混着两件事**:
                #
                #      仓库这份改了**还没推**,目标是本检出的 HEAD 版本 → 推了就一致
                #      目标跟仓库**无关地漂开了**                      → 真故障
                #
                #    2026-11-04 这个结一天出现**两次**(在 worktree 里改 hook
                #    必然经过它),而它**在推之前不可能绿** —— 于是「门禁绿了
                #    才提交」在这个场景下不可满足,只能每次靠人拍一下放过。
                #    > 一个合法流程的中间状态,和一次真的漂移,
                #    > **在那句「内容已经不一样了」上长得一模一样。**
                #
                #    ⚠️ 这是**放宽**(原来红、现在只提示),所以两头都收紧了:
                #      ① 判据只比 git 对象,不看时间戳、不猜
                #      ② `是本检出的已提交版本()` 取不到就回 False → 照旧判红
                elif 是本检出的已提交版本(os.path.join("tools", "hooks", f), 指向):
                    还没推.append((f, 指向))
                else:
                    漂.append((f, f"软链指向另一个检出的那份,**而内容已经不一样了**:"
                                  f"{指向} —— 两个检出的这个文件漂开了,"
                                  f"跑的是那边那一份"))
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
    for f, 指向 in 还没推:
        print(f"  ℹ️ {f}  仓库这份**改了还没推** —— 目标正是本检出 HEAD 上那个版本,"
              f"所以差异全来自未提交的改动。**推上去、让那个检出 pull 就一致了**。")
        print(f"       指向:{指向}")
        print(f"       ⚠️ 在那之前,真正在跑的仍然是旧的那一份 —— "
              f"**改了仓库那份不等于它生效了**。")
    for f, 指向 in 别检出:
        print(f"  🟢 {f}  软链指向**另一个检出**的同名 hook,内容一致 —— "
              f"不判红(软链只能指一个检出,而这个仓库有多个)")
        print(f"       指向:{指向}")
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
    if 别检出:
        print(f"\n  📖 库况 {len(别检出)} 份软链指向的是**另一个检出** —— "
              f"**这不是判据,只是说明情况**。")
        print(f"     判红的那条是「内容一致吗」,它两个检出都验得到;"
              f"「指着谁」取决于这台机器上软链怎么建的,拿它判红的话,"
              f"红不红就和代码没关系了。")
    print(f"\n  ✅ 没有漂的(一样 {len(一样)} · 软链 {len(软链)} · "
          f"指向另一个检出但内容一致 {len(别检出)} · 不适用 {len(不适用)})")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_自测())
    sys.exit(main())
