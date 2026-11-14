#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写死的模型 id · 判据 —— **一条写对了的注释和一条已经漂了的注释,在源码上长得一模一样。**

## 这条判据是怎么来的(2026-11-10)

`管理后台/.../runtime/意图.py` 写死 `分类模型 = "claude-haiku-5-5"`,
注释说「**聊天站默认也是它**」。并行会话查实:聊天站最近 2473 次调用
**全是 `claude-haiku-4-5`**,而这台机器的登录额度下整代 5.5 立刻 `rate_limit_error`。
照那个样子挂生产,**每句话分类都失败**,而转人工开着 —— 等于全转人工。

> 那条注释写下来的那天也许是对的。它不是写错了,是**没人回来看它** ——
> 而没人回来看的时候,它和一条守得住的声称长得一模一样。

## 断言的是什么(这一条想清楚过)

**不是**「分类模型 == 聊天站的答话模型」—— 用户拍的是「**最便宜那档**」,
它本来就该和答话模型不同,断言相等会把一个正确的决定判成错。

**是**:项目里每一个写死的模型 id,都必须是**记录仪里真成功调用过**的那几个之一。
这条性质更弱,但它正是会出事的那条 —— 出事的从来不是「版本号不一样」,
是「**这个模型在这个账号下压根调不通**」。而且它对「要最便宜那档」这个决定完全中立。

## 环境相关那一半,单独拆开(CLAUDE.md 第 8 节)

记录仪 `.feynman/llm-trace.jsonl` **不进版本库**,所以 CI 上没有它。
一条「红不红取决于环境里碰巧有什么」的判据不是在验代码。所以拆成两件:

    代码对不对  → 比对函数**自己造样本**去验(两个环境都真验得到)
    这台机器上实际在用什么 → 真读记录仪;**读不到就明说「不适用,不是通过」**

⚠️ 「不适用」和「通过」必须分开印。少了这一步,CI 上这条就变成一句绿字,
而它什么都没验。
"""
import ast
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
记录仪 = os.path.join(ROOT, ".feynman", "llm-trace.jsonl")


def _主检出():
    """worktree 的主检出根目录(拿 git 的公共目录推);本身就是主检出 / 不是 git 仓库 → None。"""
    import subprocess
    try:
        g = subprocess.run(["git", "-C", ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return None
    根 = os.path.dirname(g) if g else ""
    return 根 if 根 and os.path.realpath(根) != os.path.realpath(ROOT) else None


# ⚠️ 2026-11-14:存量 7 处是照**主检出**的记录仪登的(aimc 跑在主检出,真调用都记在那边),
#    而 worktree 自己那份只有在这个检出里跑评测时才写 —— 旧副本只见过两种模型,
#    于是存量里的老行被算成「新增 31 处」,主干代码一样红。这台机器的证据 = 两份合起来。
记录仪们 = [记录仪] + ([os.path.join(_主检出(), ".feynman", "llm-trace.jsonl")] if _主检出() else [])
样本下限 = 50          # 地板:记录仪里至少这么多条才拿它当「实际在用什么」的证据
基线文件 = os.path.join(HERE, "模型写死基线.json")

# ── 咬合记录 ────────────────────────────────────────────────────────────
# ⚠️ 第一条是这一组里最要紧的,它守的是**这条判据自己会不会变成摆设**:
#    第一版的跳过名单里有 `.claude`,而**这个检出自己就在 `.claude/worktrees/工`
#    里面** —— 第一个目录就把整棵树剪掉,判据印「全项目 0 处写死的模型」然后全绿。
#    救回来的是那句「样本量 0 —— 这不叫通过,这叫没扫到东西」。
咬合 = [
    # ⚠️ 破坏点打在**后果**上(让 `该跳过()` 连根目录也跳 → 整棵树扫不到),
    #    不打在那个真实根因上(「跳过名单拿绝对路径做子串匹配」)——
    #    因为 `bite_run` 在**工作区副本**上重放,而**副本的路径不在 `.claude` 底下**,
    #    那个根因在副本里压根不成立,咬合会报「改坏了却没红」。
    ("让 `该跳过()` 连根目录也跳(整棵树一个文件都扫不到)",
     "没有**新**写死一个这台机器调不通的模型"),
    ("让「没数据」和「对得上」合并(记录仪是空的时候报「调得通」)",
     "比对函数三种结果分得开"),
    ("把「模型」字段那条判据的范围放回全部 json(把数据字段也判红)",
     "叫「模型」的字段里装的是模型 id,不是一句说明"),
]
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
FAIL, N = [], 0

# 模型 id 的形状:供应商前缀可有可无,后面是 `厂-档-代` 那种
_模型形 = re.compile(r"^(?:[a-z]+:)?claude-[a-z0-9]+(?:-[0-9]+)*(?:-[0-9]{8})?$")


def ck(名, 过, n, 说=""):
    """⚠️ **样本量 0 时这一行印 ❌,不印 ✅。**

    2026-11-10 栽过:原来 `n == 0` 时它照旧印 `✅ {名}`,另起一行印
    `⚠️ 样本量 0`,只把失败记进 `FAIL`。于是**在行级别上**
    「这条通过了」和「这条什么都没验」长得一模一样 ——
    带 ❌ 的只有末尾那句笼统的「N 处不符合预期」,它不说是哪一条。
    后果:咬合第三关(「红的必须是点名那一条」)认不出来,报
    「红了但红的不是那一条」—— **那不是咬合的问题,是这一行输出的问题**。
    """
    global N
    N += 1
    空 = (n == 0)
    print(f"  {'✅' if (过 and not 空) else '❌'} {名}(验了 {n} 个)"
          f"{'  ' + 说 if 说 else ''}")
    if not 过:
        FAIL.append(名)
    if 空:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(名 + "(样本量 0)")


# ── 比对函数:三种结果必须分得开 ────────────────────────────────────────
def 对不对(写死的, 实际用过的):
    """→ (结论, 一句话)。结论 ∈ 对得上 / 对不上 / 没数据。

    ⚠️ **「没数据」不许和「对得上」合并。** 记录仪是空的时候,
    「这个模型调得通」和「我不知道它调不调得通」在一个布尔值上长得一模一样,
    而前者可以上线、后者必须先去问一句。
    """
    if not 实际用过的:
        return "没数据", "记录仪里一条成功调用都没有 —— **不知道它调不调得通**,不是「调得通」"
    裸 = (写死的 or "").split(":")[-1]
    if 裸 in {str(x).split(":")[-1] for x in 实际用过的}:
        return "对得上", f"`{写死的}` 在这台机器上真调通过"
    return "对不上", (f"写死的是 `{写死的}`,而记录仪里**从没成功调用过它**;"
                      f"真在用的是 {sorted({str(x).split(':')[-1] for x in 实际用过的})[:4]}")


def 实际用过的():
    """记录仪里**成功**调用过的模型。读不到返回 `None`(不是空集合)。

    ⚠️ `None` 和 `set()` 要分开:前者是「这台检出没有记录仪」,
    后者是「有记录仪但一条成功的都没有」—— 后者该让人去查认证 / 额度。
    """
    在的 = [f for f in 记录仪们 if os.path.isfile(f)]
    if not 在的:
        return None
    出, 条 = set(), 0
    for l in (x for f in 在的 for x in io.open(f, encoding="utf-8", errors="replace")):
        l = l.strip()
        if not l:
            continue
        try:
            d = json.loads(l)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        条 += 1
        # 失败的调用不算「调得通」—— 那正是 5.5 那次的样子(立刻 rate_limit)
        if d.get("成功") is False or d.get("ok") is False:
            continue
        m = d.get("模型") or d.get("model")
        if m:
            出.add(str(m))
    return 出 if 条 >= 样本下限 else None


def 写死的模型们():
    """全项目写死的模型 id → `{文件:行 → 模型}`。

    ⚠️ **扫 AST 的字符串常量,不是正则扫源码**:正则会把注释里、
    文档里、以及判据自己举的例子都算进来 —— 这个项目为「被扫描的文件里
    写出了真实匹配串」连踩过四次(密钥扫描三次 + 交接必填段一次)。
    """
    出 = {}
    # ⚠️⚠️ **跳过要按「相对 ROOT 的路径」判,不许拿绝对路径做子串匹配。**
    # 2026-11-10 栽过:名单里有 `/.claude`(本意是排除别人的 worktree),
    # 而**这个检出自己就在 `/.claude/worktrees/工` 里面** ——
    # 于是第一个目录(根目录本身)就匹配上,`ds[:] = []` 把整棵树剪掉,
    # **一个文件都没走**,判据印出「全项目 0 处写死的模型」然后全绿。
    # 救回来的是那句「样本量 0 —— 这不叫通过,这叫没扫到东西」。
    # > 一条「排除生效了」和一条「排除把自己也排掉了」,
    # > **都只在样本量那个数字上看得出来。**
    # (同一个形状的另一半:并行会话 11-09 修过我写的
    #  `not d.startswith(".worktrees")` —— 真实目录叫 `.claude/worktrees`,
    #  那个排除**从写下那天起一次没生效过**。)
    跳过 = (".git", ".venv", "node_modules", ".worktrees", ".claude",
            "onetime-deepseek")

    def 该跳过(绝对路径):
        rel = os.path.relpath(绝对路径, ROOT)
        if rel == ".":
            return False                      # 根目录自己永远不跳
        return any(x in rel.split(os.sep) for x in 跳过)
    # 判据自己、以及专门造假模型名的自测,不算
    自己 = {os.path.basename(__file__), "eval_provenance_check.py"}
    for d, ds, fs in os.walk(ROOT):
        if 该跳过(d):
            ds[:] = []
            continue
        for f in fs:
            if f in 自己 or f.endswith("-results.jsonl"):
                continue
            p = os.path.join(d, f)
            rel = os.path.relpath(p, ROOT)
            if f.endswith(".py"):
                try:
                    t = ast.parse(io.open(p, encoding="utf-8", errors="replace").read(), p)
                except (SyntaxError, ValueError):
                    continue
                for x in ast.walk(t):
                    if (isinstance(x, ast.Constant) and isinstance(x.value, str)
                            and _模型形.match(x.value)):
                        出[f"{rel}:{getattr(x, 'lineno', 0)}"] = x.value
            elif f.endswith(".json") and "seed_data" in rel.replace(os.sep, "/"):
                try:
                    j = json.load(io.open(p, encoding="utf-8", errors="replace"))
                except Exception:
                    continue
                def 走(o, 路):
                    if isinstance(o, dict):
                        for k, v in o.items():
                            走(v, f"{路}.{k}")
                    elif isinstance(o, list):
                        for i, v in enumerate(o):
                            走(v, f"{路}[{i}]")
                    elif isinstance(o, str) and _模型形.match(o):
                        出[f"{rel}{路}"] = o
                走(j, "")
    return 出


def main():
    print("写死的模型 id · 判据")
    print("=" * 92)

    # ── ① 比对函数自己:三种结果分得开(自造样本,两个环境都真验得到)────────
    三 = [
        (对不对("claude-haiku-4-5", {"claude-haiku-4-5", "claude-sonnet-5"})[0], "对得上"),
        (对不对("claude-haiku-5-5", {"claude-haiku-4-5"})[0], "对不上"),
        (对不对("claude-haiku-4-5", set())[0], "没数据"),
        (对不对("claude-haiku-4-5", None)[0], "没数据"),
        # 带供应商前缀的要和裸名字对得上(后台配置里写的是 `claude:claude-haiku-5-5`)
        (对不对("claude:claude-haiku-4-5", {"claude-haiku-4-5"})[0], "对得上"),
    ]
    ck("比对函数三种结果分得开(对得上 / 对不上 / **没数据**)—— "
       "「没数据」不许当成「对得上」",
       all(a == b for a, b in 三), len(三),
       "；".join(f"{a}≠{b}" for a, b in 三 if a != b) or "五种情形都对")

    写死 = 写死的模型们()
    print(f"\n  ℹ 全项目写死的模型 id:**{len(写死)} 处**(AST 扫字符串常量,不是正则扫源码)")
    计 = {}
    for k, v in 写死.items():
        计.setdefault(v, []).append(k)
    for v, ks in sorted(计.items(), key=lambda kv: -len(kv[1])):
        print(f"     {v:<34} {len(ks)} 处" + (f"  ← {ks[0]}" if len(ks) == 1 else ""))

    # ── ② 任何给模型读的「模型」字段,不许装一句说明 ────────────────────
    # 这条守的是我自己 2026-11-10 埋的那颗地雷:`agent/intent_config.json` 里
    # `"模型": "最便宜那档(用户 11-08 拍)"` —— 我当说明写,而 `意图.分类` 把它
    # 当模型 id 读过去调,**必挂**。
    # > 一个字段装模型 id、一个字段装对模型的说明,**在 JSON 里长得一模一样** ——
    # > 而读它的那一方只认前一种。
    坏字段, 意图配置数 = [], 0

    def 该跳过2(绝对路径):
        rel = os.path.relpath(绝对路径, ROOT)
        if rel == ".":
            return False
        return any(x in rel.split(os.sep)
                   for x in (".git", ".venv", "node_modules", ".worktrees", ".claude"))

    for d, ds, fs in os.walk(ROOT):
        if 该跳过2(d):          # 同一个坑,同一个修法(见 `写死的模型们` 的注释)
            ds[:] = []
            continue
        for f in fs:
            if not f.endswith(".json"):
                continue
            p = os.path.join(d, f)
            try:
                j = json.load(io.open(p, encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if not isinstance(j, dict):
                continue
            # ⚠️ **收窄到真会被当模型 id 读的那类配置。** 第一版扫了所有 json,
            # 于是 `fakedata/transcripts.json` 里一个叫「模型」、值是「(默认)」的
            # 数据字段也被判红 —— 那个字段压根没人当模型 id 读。
            # > 一条「守住了该守的」和一条「顺手把不相干的也判红了」,
            # > 在「它红了」上长得一模一样 —— 而后者会被豁免成摆设。
            # 判据:`意图.分类` 读的是**意图配置**里的 `模型`,所以只认那种形状
            # (顶层有 `意图` 列表的)。
            if not isinstance(j.get("意图"), list):
                continue
            意图配置数 += 1
            v = j.get("模型")
            if isinstance(v, str) and v and not _模型形.match(v):
                坏字段.append((os.path.relpath(p, ROOT), v[:28]))
    ck("叫「模型」的字段里装的是模型 id,不是一句说明"
       "(**要写说明就叫「模型说明」** —— 读它的那一方只认模型 id)",
       not 坏字段, max(1, 意图配置数),
       f"{坏字段[:3]} —— 它会被当成模型 id 去调,必挂" if 坏字段
       else "没有一个「模型」字段装着说明文字")

    # ── ③ 真读记录仪:写死的那些,在这台机器上调得通吗 ────────────────────
    用过 = 实际用过的()
    if 用过 is None:
        # ⚠️ **「不适用」和「通过」分开印。** 少了这一句,CI 上这条就是一句绿字
        print(f"\n  {Y}⏸ **不适用,不是通过**:这台检出没有记录仪(或样本不到 {样本下限} 条)"
              f"—— 「写死的模型调不调得通」这一条**没验**。"
              f"\n     记录仪 `.feynman/llm-trace.jsonl` 不进版本库,所以 CI 上永远走这一支;"
              f"\n     **本机跑一次 `./check.sh` 才验得到这一条**{D}")
    else:
        对不上的 = {}
        for 位置, 名 in sorted(写死.items()):
            结论, 说 = 对不对(名, 用过)
            if 结论 == "对不上":
                对不上的[位置] = 说
        # ── 棘轮:存量登记,**只许少不许多** ────────────────────────────
        #
        # ⚠️ 第一版断言「每一个写死的模型都必须调通过」,一下红了 **35 处**,
        # 而其中大半是**合法**的:价目表里的选项、路由表的备选、
        # `claude-oauth`(那是凭据路径不是模型)、reranker 的名字。
        # > 一条红在 35 件既存事实上的判据守不住 —— 它会被豁免成摆设,
        # > 而一个被豁免成摆设的判据,和一个守得住的判据,在绿勾上长得一模一样。
        # 所以照项目里现成的办法(bite_check 的欠债表、selftest_registry 的豁免)
        # 改成棘轮:**存量登记,新增当场红**。
        # 这样它仍然抓得住原本那个 bug —— 有人新写死一个这台机器调不通的模型。
        旧 = {}
        if os.path.isfile(基线文件):
            try:
                旧 = json.load(io.open(基线文件, encoding="utf-8"))
            except Exception as e:
                print(f"  {Y}⚠️ 基线读不了({e})—— 当成第一次登记{D}")
        存量 = set(旧.get("存量", []))
        新增 = sorted(set(对不上的) - 存量)
        好了 = sorted(存量 - set(对不上的))
        ck(f"没有**新**写死一个这台机器调不通的模型(存量 {len(存量)} 处,只许少不许多)",
           not 新增, len(写死),
           f"{len(新增)} 处新增:" + "；".join(
               f"{k} —— {对不上的[k]}" for k in 新增[:3]) if 新增
           else f"{len(对不上的)} 处对不上,全在存量里;记录仪为证的是 {sorted(用过)[:4]}")
        if 好了:
            # ⚠️ 推它的那只手,而且**印在通过路径上** —— 这个项目踩过
            # 「提示被门禁的 tail -3 截掉」,所以装了提示还要问一句:看得见吗
            print(f"     {Y}ℹ️ {len(好了)} 处已经不对不上了(多半是那个模型终于调通过了)"
                  f"—— 跑 `python3 tools/model_align_check.py --登记` 把存量降下来:"
                  f"{好了[:3]}{D}")

    if FAIL:
        print(f"\n{R}❌ 写死的模型 {len(FAIL)} 处不符合预期{D}")
        for x in FAIL:
            print(f"   · {x}")
        return 1
    print(f"\n{G}✅ 写死的模型 id:比对函数三种结果分得开、"
          f"「模型」字段里装的是 id 不是说明{D}")
    return 0


def 登记():
    """把现在对不上的那些登记成存量 —— **只许降,不许涨**。

    ⚠️ 方向和 `eval_tier_check` 的 `--登记` **相反**(那边是题数、只许涨),
    和 `bite_check` 的同向(欠债、只许降)。方向写反了,这道闸就变成「随便重设」,
    而它看起来照旧是一道闸。
    """
    用过 = 实际用过的()
    if 用过 is None:
        print(f"{R}❌ 不登记:这台检出读不到记录仪(或样本不到 {样本下限} 条)——"
              f"**没有证据时登记出来的存量是假的**{D}")
        return 1
    现 = sorted(k for k, v in 写死的模型们().items()
                if 对不对(v, 用过)[0] == "对不上")
    旧 = []
    if os.path.isfile(基线文件):
        try:
            旧 = json.load(io.open(基线文件, encoding="utf-8")).get("存量", [])
        except Exception:
            旧 = []
    if 旧 and len(现) > len(旧):
        print(f"{R}❌ 不登记:现在 {len(现)} 处 > 基线 {len(旧)} 处 —— "
              f"这道闸**只许降**。新增的是:{sorted(set(现) - set(旧))[:5]}{D}")
        return 1
    io.open(基线文件, "w", encoding="utf-8").write(json.dumps(
        {"存量": 现, "更新于": __import__("datetime").date.today().isoformat(),
         "这是什么": "写死了、而这台机器的记录仪里从没成功调用过的模型 id。"
                     "大半是合法的(价目表选项、路由备选、凭据路径),"
                     "所以不拦门禁 —— 但**只许少不许多**:新写死一个调不通的会当场红。"},
        ensure_ascii=False, indent=1) + "\n")
    print(f"{G}✅ 已登记 {len(现)} 处存量(旧 {len(旧)} 处){D}")
    return 0


if __name__ == "__main__":
    sys.exit(登记() if "--登记" in sys.argv else main())
