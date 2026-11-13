#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**一次大重构之后,哪些咬合攻击需要重放** —— 算出完备集,逐个重放。

## 要解决什么

全量重放 918 条规格要约两小时,所以重构之后没人会跑;
而不跑的代价是**攻击悄悄失效**,下一次真有人改坏代码时它不会红。

2026-10-23 的真实例子:MCP 按 8 个业务领域拆开,全仓改名
(`mcp__shop__get_order` → `mcp__commerce__get_order`)。改名脚本扫全仓,
而 `tools/bite_specs.json` 里**攻击载荷本身就是代码片段** ——
它既改被攻击的代码、也改攻击里那段 `old` / `new`。于是出现一类:

> **`old` 和 `new` 一起被改,语义上变成同一件事 = 这个攻击变成了空操作。**

而它**过得了咬合的前两关**(对照先绿 ✅、要改的那段找得到 ✅),
只在第三关(改坏之后红的必须是点名那一条)露馅。
`tools/bite_check.py` 只做记账(清单 ⇔ 规格对不对得上),**它不重放** ——
所以门禁绿**不代表**那些攻击还活着。

## 完备集怎么界定(这一段是这个工具的全部价值)

当时并行会话先按「**规格自己变了**」界定:拿改名前后的 `bite_specs` 逐条比,
变了的分属 5 个脚本,把这 5 个脚本的规格全重放,11 条全过。
对没变的那些,他的理由是:`old` 里要是含旧前缀而目标文件被改名了,
`bite_check` 的「要改的那段在工作区找得到」会红;它绿,所以 `old` 都还对得上。

**那一步证明的是第二关,不是第三关** —— 而这两件会分开:

> 一条规格**自己一个字没变**、`old` 也**照旧找得到**,
> 而它**周围的代码**被改名脚本改了 —— 那个攻击可能不再破坏它原来破坏的东西。

最具体的一类:`old` 里本来就不含任何前缀(所以改名脚本没碰这条规格),
但它钉的那个文件被改过。比如「判据点名的工具必须在架上」那条 ——
拆完之后「在架的工具叫什么」整套换了,而按「规格变没变」界定根本看不到它。

所以完备集是**按文件**界定,不是按规格:

    S = 那次提交 `git diff --name-only` 改过的文件
    要重放的 = 所有 file[].path ∈ S 的规格

它是「规格自己变了」那个集合的**超集**,而且仍然远小于全库。

⚠️ **重放的粒度是「脚本」不是「规格」**:`bite_run --only <脚本>` 会把那个脚本的
规格全跑一遍。这是**故意要的超集** —— 同一个脚本的其他规格也钉在同一批代码上,
顺手一起验掉比挑着跑更省事,而且少一次「我以为挑干净了」的机会。

## ⚠️ 它报的数,必须是它**真跑的**那个数(2026-11-10 栽的)

原来总结行印「N 条撞上的规格,重放全过三关」,而那个 N 是**「钉在这些文件上的
规格」**的条数 —— 跟真跑的条数不是一回事。`bite_run --only X` 的筛法是
**子串匹配 `script` 或「改坏」那段话**(`bite_run.py:913`),所以它跑的是超集。

实测:我报「34 条全过」,真跑 **48 条**;并行会话报 28,真跑 **42 条** ——
**两边都正好差 14,而两个人都没看出来。**

> 方向是安全的(多跑了,不是少跑了),但**报出来的数不是跑出来的数** ——
> 一份「我报的就是我跑的」,和一份「我报的是另一把尺子的读数」,
> 在那行绿字上长得一模一样。

修法里有两个刻意的选择:

1. **不在这里重写一遍它的筛法**,而是开跑前问 `bite_run --list` 要
   (它不拷副本、不拿锁、不跑检查)。照抄一份规则过来就是第二份手抄件:
   哪天它改了筛法,这边的数会**安静地漂**。
2. 跑完再从它自己印的 `[i/N]` 读一次实跑条数,和开跑前那个预告**对一遍** ——
   **两个独立来源**,对不上就红。

退出码:`0` 全过 · `1` 有攻击失效了 · `2` 工作区脏拒跑 ·
**`3` 攻击都过了,但这份报数不可信**(和 `1` 分开:**红错理由比不红更费事**)。

用法:

    python3 tools/bite_replay_touched.py                  # 看 HEAD 那次提交
    python3 tools/bite_replay_touched.py --提交 11cfb2d
    python3 tools/bite_replay_touched.py --只看            # 只算完备集,不重放
"""
import argparse
import json
import os
import re
import subprocess
import sys

这里 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(这里)
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def 改过的文件(提交, 基线=None):
    """那次提交动过哪些文件。合并提交取第一父。
    给了 `基线`(比如 `origin/main`)就算 **基线...提交 之间全部**改过的文件 —— 推送前用:
    一个分支上攒了十几笔,逐笔算再合并,和一次算三点号 diff 是同一个集合,后者少十几次 git 调用。

    ⚠️⚠️ **必须 `-c core.quotepath=false`。** 这个仓库大半文件名是中文,
    而 git 默认把非 ASCII 路径转义成 `"\346\276\234..."` 输出 ——
    于是和规格里那个 `file[].path` 比**永远对不上**。
    第一版就栽在这儿:拿一次改过 `澜绣云裳agent-产品说明.md` 的提交去试,
    钉在那个文件上的规格**没被算进来**。
    > 而它的失败方式是最糟的一种:**不报错,安静地少算几条** ——
    > 「完备集算全了」和「漏了几条」在这份输出上长得一模一样。
    而这个工具存在的理由本身就是「别漏」:**一个少算了的完备集比不跑更危险**,
    因为跑完的人会以为验过了。
    """
    范围 = [f"{基线}...{提交}"] if 基线 else [f"{提交}~1", 提交]
    r = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--name-only", *范围],
                       cwd=根, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{R}git diff 失败:{r.stderr.strip()[:200]}{D}")
    return {l.strip() for l in r.stdout.split("\n") if l.strip()}


# ── 用户 2026-11-13 拍:推送前的重放**只在改动了检查本身时才跑** ──────────────────
# 实测一次分支级重放 ~70 分钟 + 门禁 15 分钟,一推一个半小时、和并行会话抢锁。
# 代价(用户知情):纯业务改动碰巧打死某条攻击,要等十天一次的全量重放才发现。
# 「检查类」按**结构**认,不按目录枚举:
#   ① 它本身是某条咬合规格的 `script`(被咬的那条检查)
#   ② 文件名形状是检查 / 判分器:`*_check.py` `*_test.py` `*_judgetest.py` `*_eval.py` `check.sh`
#   ③ 判分底座与线上守卫:`agent/textmatch.py` `agentsite/guards.py`;以及 `tools/` 下的 .py(多数是检查)
_检查类形状 = re.compile(r"(?:_check|_test|_judgetest|_eval)\.py$|(?:^|/)check\.sh$")
_检查类底座 = {"agent/textmatch.py", "agentsite/guards.py", "tools/bite_specs.json"}


def 检查类文件(S):
    specs = json.load(open(os.path.join(这里, "bite_specs.json"), encoding="utf-8"))
    规格脚本 = {x.get("script") for x in specs}
    return sorted(f for f in S if f in 规格脚本 or f in _检查类底座 or _检查类形状.search(f)
                  or (f.startswith("tools/") and f.endswith(".py")))


def 要重放的(S):
    """返回 {脚本: [(规格序号, 它钉的那些文件 ∩ S)]}。"""
    specs = json.load(open(os.path.join(这里, "bite_specs.json"), encoding="utf-8"))
    出 = {}
    for i, x in enumerate(specs, 1):
        钉的 = {f.get("path") for f in (x.get("file") or [])}
        撞上 = 钉的 & S
        if 撞上:
            出.setdefault(x.get("script"), []).append((i, sorted(撞上), x.get("预期红")))
    return 出, len(specs)


def 按脚本会跑几条(脚本):
    """问 `bite_run` 自己:`--only <脚本>` 会跑到几条。

    ⚠️⚠️ **不要在这里重写一遍它的筛法。** `--only` 是**子串匹配**,而且匹配的是
    `script` **或**「改坏」那段话(`bite_run.py:913`)—— 照抄一份规则到这里,
    就是第二份手抄件:哪天它改了筛法,这边的数会**安静地漂**。
    `--list` 不拷副本、不拿锁、不跑检查(`bite_run.py` 自己注释写明了),
    所以问它一句几乎不花钱。

    读不出来返回 `None` —— **别返回 0**:「它一条都不跑」和「我没读懂它的输出」
    是两件事,而前者该红、后者该说「读不出来」。
    """
    r = subprocess.run([sys.executable, os.path.join(这里, "bite_run.py"),
                        "--list", "--only", 脚本],
                       cwd=根, capture_output=True, text=True, errors="replace")
    m = re.search(r"共 (\d+) 条", r.stdout or "")
    return int(m.group(1)) if m else None


_条数行 = re.compile(r"\[\d+/(\d+)\]")


def 真跑了几条(出):
    """从 `bite_run` 的输出里读它**实际**跑了几条(每条规格都印一行 `[i/N]`)。

    为什么不信上面那个预告就够了:预告是开跑**之前**问的,而中间可能
    被「规格自己是坏的」「库正在重建」之类的早退路径截掉 ——
    那时它一条都没真跑,而总结行照旧会被人读成「跑过了」。
    """
    n = [int(x) for x in _条数行.findall(出 or "")]
    return max(n) if n else None


def main():
    ap = argparse.ArgumentParser()
    # ⚠️ **可以给好几个提交,取并集。** 一次重构往往不是一个提交:
    # 2026-10-23 那次是 `11cfb2d`(拆 8 个领域)+ `d263f0b`(修它带出来的四处红,
    # 又动了旧三服务的文件头)。**只算主提交会漏掉补刀那次改的文件。**
    ap.add_argument("--提交", default=["HEAD"], nargs="+",
                    help="要看哪几次提交(可给多个,取并集;默认 HEAD)")
    ap.add_argument("--基线", default=None,
                    help="给了就算 **基线...提交** 之间全部改过的文件(推送前用 `--基线 origin/main`:"
                         "一个分支攒了十几笔,一次三点号 diff 就是并集)")
    ap.add_argument("--只看", action="store_true", help="只算完备集,不重放")
    ap.add_argument("--检查类才跑", action="store_true",
                    help="改动里没有检查 / 守卫 / 判分器类文件就跳过重放(推送前用,用户 2026-11-13 拍)")
    ap.add_argument("--工作区脏也跑", action="store_true",
                    help="明知工作区有未提交改动也要跑 —— **跑出来的红要自己分辨是哪一种**")
    a = ap.parse_args()

    print("一次大重构之后,哪些咬合攻击需要重放")
    print("=" * 96)
    # ── 前置闸:工作区不干净就拒跑 ──────────────────────────────────
    #
    # ⚠️⚠️ **这道闸是 2026-10-23 第一次跑这个工具时栽出来的。**
    # `bite_run` 在**工作区副本**上重放,脏的工作区进了副本 —— 于是 21 个脚本里
    # 10 条报「**对照就是红的**」(第一关就没过)。
    # 那不是攻击失效,是我自己改了 `gen_doc_lists` 还没提交。
    # > **「攻击失效了」和「我自己的工作区脏」都显示成 ❌。**
    # 而这份假红要是发给了别人,他会去查 10 条根本没问题的规格 ——
    # **红错理由比不红更费事。**
    #
    # 所以**拒跑,不是警告** —— 一个带着警告跑出来的结果,
    # 和一个干净跑出来的结果,在那份输出上长得一模一样,
    # 而几分钟后没人记得自己跳过了一行黄字。
    脏 = subprocess.run(["git", "-c", "core.quotepath=false", "status", "--porcelain"],
                        cwd=根, capture_output=True, text=True).stdout
    改了 = [l for l in 脏.split("\n") if l.strip() and not l.startswith("??")]
    # `--只看` 只算完备集、不重放,所以它不需要干净的工作区 —— **别拦它**。
    # (一道拦得过宽的闸会被人加 `--工作区脏也跑` 绕过去,然后那个开关就一直开着。)
    if 改了 and not a.工作区脏也跑 and not a.只看:
        print(f"{R}❌ 工作区不干净({len(改了)} 个文件有未提交的改动)—— **拒跑**{D}")
        for l in 改了[:8]:
            print(f"     {l}")
        if len(改了) > 8:
            print(f"     …… 还有 {len(改了) - 8} 个")
        print(f"\n   `bite_run` 是在**工作区副本**上重放的,脏的工作区会进副本 ——"
              f"\n   跑出来的会是一堆「**对照就是红的**」,而那不是攻击失效,是你自己的改动。"
              f"\n   > **「攻击失效了」和「工作区脏」都显示成 ❌。**"
              f"\n   先提交(或者确认这些改动本来就该在副本里,加 `--工作区脏也跑`)。")
        return 2

    S = set()
    for c in a.提交:
        标题 = subprocess.run(["git", "log", "-1", "--format=%h %s", c],
                              cwd=根, capture_output=True, text=True).stdout.strip()
        这次 = 改过的文件(c, a.基线)
        print(f"看的是:{标题}  —— 改过 {len(这次)} 个文件")
        S |= 这次
    if a.检查类才跑:
        检 = 检查类文件(S)
        if not 检:
            组0, 总0 = 要重放的(S)
            print(f"{Y}⏭ 跳过重放(不适用,不是验过了):这 {len(S)} 个改动文件里**没有**检查 / 守卫 / 判分器类文件。{D}")
            print(f"   本该重放的 {sum(len(v) for v in 组0.values())} 条规格({len(组0)} 个脚本)留给十天一次的全量重放 —— 用户 2026-11-13 拍的代价。")
            return 0
        print(f"改动里有 {len(检)} 个检查类文件 → 照常重放:{'、'.join(检[:6])}{' ……' if len(检) > 6 else ''}")
    组, 总 = 要重放的(S)
    条数 = sum(len(v) for v in 组.values())
    print(f"这 {len(a.提交)} 次提交一共改过 **{len(S)} 个文件**(并集);全库 {总} 条规格里,"
          f"**{条数} 条钉在这些文件上**,分属 **{len(组)} 个脚本**")
    # ⚠️ 这两个数**必须一起印**,而且「实跑」要写在前面那个数旁边。
    # 2026-11-10 栽过:总结行只印「{条数} 条撞上的规格,重放全过三关」,
    # 于是我报了「34 条全过」而真跑的是 48 条(两个会话同时栽,都差 14)。
    # 偏在安全那一侧(多跑了),但**报出来的数不是真跑的数** ——
    # > 一份「我报的就是我跑的」和一份「我报的是另一把尺子的读数」,
    # > 在那行绿字上长得一模一样。
    预告 = {脚本: 按脚本会跑几条(脚本) for 脚本 in 组}
    读不出的 = [k for k, v in 预告.items() if v is None]
    预计 = sum(v for v in 预告.values() if v is not None)
    if 读不出的:
        print(f"  {Y}⚠️ {len(读不出的)} 个脚本问不出「会跑几条」(bite_run --list 的输出读不懂)"
              f"—— 下面那个「预计实跑」是**少算了的**,别拿它当数{D}")
    print(f"⚠️ 而**真跑的不是 {条数} 条,是预计 {预计} 条**(多 {预计 - 条数} 条)——"
          f"重放粒度是脚本,不是规格(见下面那段)。"
          f"\n   这个预计数是**问 `bite_run --list` 要的**,不是我自己照它的筛法算的;"
          f"跑完还会拿它实际印出来的条数对一遍。")
    if not 组:
        print(f"  {Y}一条都没撞上 —— 这不叫通过,是这次改动没碰到任何被咬合钉住的文件。"
              f"**要先确认这件事本身对不对**(该钉的地方没人钉,也是个缺陷){D}")
        return 0
    for 脚本, 条 in sorted(组.items(), key=lambda kv: -len(kv[1])):
        _预 = 预告.get(脚本)
        print(f"\n  {脚本}  —— {len(条)} 条撞上,"
              + (f"按脚本整套跑 **{_预} 条**" if _预 is not None else f"{Y}整套几条问不出来{D}"))
        for i, 文件, 红 in 条[:4]:
            print(f"    #{i} 钉在 {文件} · 预期红「{红}」")
        if len(条) > 4:
            print(f"    …… 还有 {len(条) - 4} 条")
    print(f"\n⚠️ **重放的粒度是脚本**:`--only <脚本>` 会把那个脚本的规格全跑一遍,"
          f"这是故意要的超集 —— 同一个脚本的其他规格也钉在同一批代码上。")
    if a.只看:
        print(f"\n{Y}📌 `--只看`,没有重放。去掉它就逐个跑 —— "
              f"真跑的是上面那 {预计} 条,不是 {条数} 条。{D}")
        return 0

    坏 = []
    实跑 = {}
    for n, 脚本 in enumerate(sorted(组), 1):
        print(f"\n{'─' * 96}\n[{n}/{len(组)}] 重放 {脚本}", flush=True)
        r = subprocess.run([sys.executable, os.path.join(这里, "bite_run.py"),
                            "--only", 脚本], cwd=根, capture_output=True, text=True,
                           errors="replace")
        尾 = [l for l in r.stdout.split("\n") if l.strip()][-3:]
        for l in 尾:
            print(f"   {l}")
        实跑[脚本] = 真跑了几条(r.stdout)
        if r.returncode != 0:
            坏.append((脚本, r.stdout))
    print("=" * 96)
    if 坏:
        print(f"{R}❌ {len(坏)}/{len(组)} 个脚本有咬合没过 —— **这些攻击已经不算数了**{D}")
        for 脚本, 出 in 坏:
            print(f"\n  {R}{脚本}{D}")
            for l in 出.split("\n"):
                if "❌" in l:
                    print(f"    {l[:200]}")
        return 1
    实跑合计 = sum(v for v in 实跑.values() if v is not None)
    print(f"{G}✅ {len(组)} 个脚本重放全过三关(对照绿 → 改坏 → 红的是点名那一条){D}")
    print(f"   **撞上这些文件的规格 {条数} 条;实跑 {实跑合计} 条** —— "
          f"重放粒度是脚本,实跑是撞上的**超集**,"
          f"多出的 {实跑合计 - 条数} 条是同脚本的其他规格(顺手一起验掉了)。"
          f"\n   报数的时候说「实跑 {实跑合计} 条」,**别说「{条数} 条全过」**。")
    # ── 两个数对不上就红 ────────────────────────────────────────────
    # 预告是开跑前问 `bite_run --list` 要的,实跑是它自己逐条印出来的 `[i/N]`。
    # **两个独立来源**:对得上才能说这份报数是实的。
    # 对不上有两种,都得红:① 它的筛法改了(预告漂了)
    # ② 它中途早退、一条没真跑(那时「全过」是空集上的真命题)。
    对不上 = [(k, 预告.get(k), 实跑.get(k)) for k in 组 if 预告.get(k) != 实跑.get(k)]
    if 对不上:
        print(f"\n{R}❌ **攻击都过了,但这份报数不可信** —— {len(对不上)} 个脚本"
              f"「开跑前说会跑几条」和「实际印出来跑了几条」对不上{D}")
        for k, 预, 实 in 对不上[:8]:
            print(f"     {k}  预告 {预} 条 · 实跑 {实} 条")
        if len(对不上) > 8:
            print(f"     …… 还有 {len(对不上) - 8} 个")
        print(f"   两种可能,**都不是「攻击失效」**:"
              f"\n   ① `bite_run --only` 的筛法改了 → 这里的预告漂了,报数要重算;"
              f"\n   ② 它中途早退、一条都没真跑(规格自己坏了 / 库在重建)→"
              f"「全过」是**空集上的真命题**。"
              f"\n   退 3(和「攻击失效」的退 1 分开:**红错理由比不红更费事**)。")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
