#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据点名的工具,必须在架上 —— **否则那道题永远过不了,而它看起来只像「模型没调对」。**

    python3 tools/judge_tool_names_check.py          # 扫一遍
    python3 tools/judge_tool_names_check.py --自测    # 跑咬合

## 这条检查是从哪来的

工具会合并、会下架:`piece_ratios` 并进了 `pattern_queue(pattern=...)`,
`member_level` 并进了 `get_member`。下架的意思是**模型看不见它了**
(不在 SHOP_SCHEMAS / KB_SCHEMAS / SCHEMAS 里),实现函数还留在 TOOLS 给别处调。

而判据还点名旧名字。2026-09-22 两轮评测:

    版师 P01   模型调了 pattern_queue,答了米数和来源 —— 判「没调 piece_ratios」,挂
    会员 M01   模型调了 get_member,答了滚动 12 个月 —— 两轮都判「没调 member_level」,挂

**模型做对了,判据判它挂,而且永远会这么判。** 报告上它只是「一道没过的题」,
和真的答错长得一模一样。运维侧那套早就踩过一次、在题旁写了注释 ——
**注释防不住下一次,检查才防得住。**

> 一条永远红的题比一条失败的题更糟 —— 它教人忽略红色。(ops_eval L01 的注释)

## 判什么

  need_tool(a, b)      点名的**每一个**都必须在架上                    → 不在就红
  need_any_tool(a, b)  **至少一个**在架上(一个都不在就永远过不了)     → 红
                       有下架的备选但还有在架的 → 只提示,不红(兼容旧轨迹是合法写法)
  判分器对照里的轨迹 `mcp__<组>__<名>`:必须在架上 ——
                       拿一条模型不可能走出来的轨迹去验判分器,验的是一件不会发生的事

## 两条容易漏的

**① 架子是空的,所有名字都「不在架上」;扫到零处点名,所有点名都「在架上」。**
两种都会让检查安静地变成空转。所以架子少于 20 个工具、或一处点名都没扫到,都是红。

**② 只扫评测和判分器对照,不扫 agentsite/gate_test.py。** 那是写闸的前置条件测试,
它点名的是 guards.py 里的规矩 —— 那边的旧名字是 guards.py 自己的病(另一个会话在修),
不是判据的病。混在一起报,修的人会找错文件。
"""
import ast, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

扫哪些 = ("agent/*eval*.py",)          # 含 *_judgetest.py

# ── 咬合记录 ────────────────────────────────────────────────────────
# 每一条都在 `--自测` 里真跑(往干净底子里放一处坏的,看红的是不是那一条)。
# 2026-09-22 首次真咬:把版师 P01 的判据改回 piece_ratios → 红在 pattern_eval.py 那一行。
咬合 = [
    ("判据 need_tool 点名一个已下架的工具(piece_ratios)", "不在架上 —— 模型看不见它"),
    ("need_any_tool 的备选全换成已下架的", "一个都不在架上"),
    ("判分器对照的轨迹里写一个已下架的工具", "模型走不出这条轨迹"),
    ("登记册读空(架上 0 个工具)", "登记册没读到"),
    ("扫描规则失效(一处点名都没扫到)", "扫描规则失效"),
]
轨迹式 = re.compile(r"mcp__[a-z]+__([a-z_]+)")


def 架上():
    """模型看得见的工具名。**从产品自己的登记册取,不手抄**(手抄的清单会和架子一起过期)。"""
    sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
    import api
    return {s["name"] for 组 in (api.SHOP_SCHEMAS, api.KB_SCHEMAS, api.SCHEMAS) for s in 组}


def 扫(源, 文件名):
    """返回 [(行号, 种类, [名字…])]。种类:need_tool / need_any_tool / 轨迹。"""
    出 = []
    for n in ast.walk(ast.parse(源)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id in ("need_tool", "need_any_tool"):
            名 = [a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if 名:
                出.append((n.lineno, n.func.id, 名))
    for i, 行 in enumerate(源.splitlines(), 1):
        for m in 轨迹式.finditer(行):
            出.append((i, "轨迹", [m.group(1)]))
    return 出


def 判(点名, 架):
    """返回 (红 [(文件, 行, 说明)], 黄 [...])。"""
    红, 黄 = [], []
    for 文件, 行, 种, 名 in 点名:
        不在 = [x for x in 名 if x not in 架]
        if not 不在:
            continue
        if 种 == "need_any_tool" and len(不在) < len(名):
            黄.append((文件, 行, f"备选里有下架的 {不在}(还有在架的,能过)"))
        elif 种 == "need_any_tool":
            红.append((文件, 行, f"need_any_tool 的备选 {名} **一个都不在架上** —— 永远过不了"))
        elif 种 == "need_tool":
            红.append((文件, 行, f"need_tool 点名的 {不在} 不在架上 —— 模型看不见它,这道题永远过不了"))
        else:
            红.append((文件, 行, f"对照轨迹里的 `{不在[0]}` 不在架上 —— 模型走不出这条轨迹"))
    return 红, 黄


def 收集():
    点名 = []
    for pat in 扫哪些:
        for f in sorted(glob.glob(os.path.join(ROOT, pat))):
            rel = os.path.relpath(f, ROOT)
            for 行, 种, 名 in 扫(open(f, encoding="utf-8").read(), rel):
                点名.append((rel, 行, 种, 名))
    return 点名


def 查(架, 点名, 报=print):
    坏 = []
    if len(架) < 20:
        坏.append(("—", 0, f"架上只有 {len(架)} 个工具 —— 登记册没读到,所有名字都会被判「不在架上」"))
    if not 点名:
        坏.append(("—", 0, "一处点名都没扫到 —— 扫描规则失效,所有判据都会被判「在架上」"))
    红, 黄 = 判(点名, 架)
    坏 += 红
    for f, l, s in 黄:
        报(f"  {Y}提示{D} {f}:{l}  {s}")
    for f, l, s in 坏:
        报(f"  {R}❌{D} {f}:{l}  {s}")
    报(f"  架上 {len(架)} 个工具 · 扫到 {len(点名)} 处点名 · 红 {len(坏)} · 提示 {len(黄)}")
    return not 坏


def 自测():
    架 = 架上()
    # 咬合不许依赖「仓库此刻是绿的」—— 否则仓库一红,咬合跟着全乱,分不清是谁坏了。
    # 用真扫出来的点名,只留全在架上的那部分当干净底子,再往里放一处坏的。
    点名 = [x for x in 收集() if all(n in 架 for n in x[3])]
    静 = lambda *_: None
    ok = True

    def ck(名, 该过, 实过):
        nonlocal ok
        good = 该过 == 实过
        ok &= good
        print(f"  {'✅' if good else '❌'} {名}")

    ck("干净底子:全绿", True, 查(架, 点名, 静))
    ck("need_tool 点名一个下架的工具 → 红", False,
       查(架, 点名 + [("假.py", 1, "need_tool", ["piece_ratios"])], 静))
    ck("need_any_tool 备选全下架 → 红", False,
       查(架, 点名 + [("假.py", 1, "need_any_tool", ["member_level", "get_lifecycle"])], 静))
    ck("need_any_tool 有一个在架 → 不红(兼容旧轨迹是合法的)", True,
       查(架, 点名 + [("假.py", 1, "need_any_tool", ["get_member", "get_lifecycle"])], 静))
    ck("对照轨迹里写了下架的工具 → 红", False,
       查(架, 点名 + [("假.py", 1, "轨迹", ["member_level"])], 静))
    ck("**架子读空了 → 红,不许空转**", False, 查(set(), 点名, 静))
    ck("**一处点名都没扫到 → 红,不许空转**", False, 查(架, [], 静))
    # 扫描器本身:真源码里的写法都认得出来
    源 = 'x = all_of(need_tool("a", "b"), says("c"))\ny = need_any_tool("d")\nT = ["mcp__shop__e"]\n'
    ck("扫描器认得出三种写法", True,
       sorted(n for _, _, 名 in 扫(源, "假") for n in 名) == ["a", "b", "d", "e"])
    print(f"\n{'✅ 咬合全部符合预期' if ok else '❌ 咬合有不符合预期的'}")
    return ok


if __name__ == "__main__":
    if "--自测" in sys.argv:
        sys.exit(0 if 自测() else 1)
    ok = 查(架上(), 收集())
    print(f"{G}✅ 判据点名的工具都在架上{D}" if ok else f"{R}❌ 有判据点名了下架的工具{D}")
    sys.exit(0 if ok else 1)
