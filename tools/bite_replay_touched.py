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

用法:

    python3 tools/bite_replay_touched.py                  # 看 HEAD 那次提交
    python3 tools/bite_replay_touched.py --提交 11cfb2d
    python3 tools/bite_replay_touched.py --只看            # 只算完备集,不重放
"""
import argparse
import json
import os
import subprocess
import sys

这里 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(这里)
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def 改过的文件(提交):
    """那次提交动过哪些文件。合并提交取第一父。

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
    r = subprocess.run(["git", "-c", "core.quotepath=false",
                        "diff", "--name-only", f"{提交}~1", 提交],
                       cwd=根, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{R}git diff 失败:{r.stderr.strip()[:200]}{D}")
    return {l.strip() for l in r.stdout.split("\n") if l.strip()}


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


def main():
    ap = argparse.ArgumentParser()
    # ⚠️ **可以给好几个提交,取并集。** 一次重构往往不是一个提交:
    # 2026-10-23 那次是 `11cfb2d`(拆 8 个领域)+ `d263f0b`(修它带出来的四处红,
    # 又动了旧三服务的文件头)。**只算主提交会漏掉补刀那次改的文件。**
    ap.add_argument("--提交", default=["HEAD"], nargs="+",
                    help="要看哪几次提交(可给多个,取并集;默认 HEAD)")
    ap.add_argument("--只看", action="store_true", help="只算完备集,不重放")
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
        这次 = 改过的文件(c)
        print(f"看的是:{标题}  —— 改过 {len(这次)} 个文件")
        S |= 这次
    组, 总 = 要重放的(S)
    条数 = sum(len(v) for v in 组.values())
    print(f"这 {len(a.提交)} 次提交一共改过 **{len(S)} 个文件**(并集);全库 {总} 条规格里,"
          f"**{条数} 条钉在这些文件上**,分属 **{len(组)} 个脚本**")
    if not 组:
        print(f"  {Y}一条都没撞上 —— 这不叫通过,是这次改动没碰到任何被咬合钉住的文件。"
              f"**要先确认这件事本身对不对**(该钉的地方没人钉,也是个缺陷){D}")
        return 0
    for 脚本, 条 in sorted(组.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  {脚本}  —— {len(条)} 条撞上")
        for i, 文件, 红 in 条[:4]:
            print(f"    #{i} 钉在 {文件} · 预期红「{红}」")
        if len(条) > 4:
            print(f"    …… 还有 {len(条) - 4} 条")
    print(f"\n⚠️ **重放的粒度是脚本**:`--only <脚本>` 会把那个脚本的规格全跑一遍,"
          f"这是故意要的超集 —— 同一个脚本的其他规格也钉在同一批代码上。")
    if a.只看:
        print(f"\n{Y}📌 `--只看`,没有重放。去掉它就逐个跑。{D}")
        return 0

    坏 = []
    for n, 脚本 in enumerate(sorted(组), 1):
        print(f"\n{'─' * 96}\n[{n}/{len(组)}] 重放 {脚本}", flush=True)
        r = subprocess.run([sys.executable, os.path.join(这里, "bite_run.py"),
                            "--only", 脚本], cwd=根, capture_output=True, text=True)
        尾 = [l for l in r.stdout.split("\n") if l.strip()][-3:]
        for l in 尾:
            print(f"   {l}")
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
    print(f"{G}✅ {len(组)} 个脚本、{条数} 条撞上的规格,重放全过三关"
          f"(对照绿 → 改坏 → 红的是点名那一条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
