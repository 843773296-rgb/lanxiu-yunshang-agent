#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写口得有门 —— **一个写入函数没有任何生产入口,和一个不存在的写入函数,效果一样**。

    python3 backend/entrypoint_check.py

## 为什么要有这条

2026-10-11 查出 `rating_write.close_bad_rating`(关差评)**从写好那天起没有任何调用方**:
不在 `api.TOOLS` 里、不在页面上、不在模型手里 —— 全仓只有**它自己的检查**调它。

代价不是「少一个功能」。那个写口里有角色闸(顾问直接拒)、有处理记录判定、
有审计日志、有 20 条回归测试 **而且全是绿的**。同时:
  · `bad_ratings` 的工具描述**一直在对模型说「关掉一条必须写处理记录」** —— 门却不存在
  · 库里 201 条「已关闭」的差评是**回填脚本直接写库**造的,处理人全是顾问工号
    —— 一个这个写口会当场拒掉的角色;`op_log` 里 `BAD_RATING_CLOSED` **0 条**

> **一个写口和一个没有入口的写口,在代码里长得一模一样** ——
> 都是一个带判定、带审计、带回归测试的函数。差别只在有没有人走得到它。
> 而**回归测试全绿这件事,不会告诉你没有人能走到这儿**。

这个形状在这个项目里是一串:`allowed_tools` 不是排他白名单 · `.pyc` 的「防止产生」≠
「防止使用」· 规矩写在提示词里 ≠ 结构上拦住 · 没进门禁的自测和不存在的自测一样 ·
**写好的写口和没有门的写口一样**。每一次都是「把声明当成了生效」。

## 怎么数

**看调用点,不看文本。** 第一版用 `grep` 数「有没有别的文件提到这个名字」——
于是 `tools/backfill_rating.py` 里**一句注释**被算成了调用方,`close_bad_rating`
当场被漏报。注释、字符串、文档里的名字都不是入口。
所以这里走 AST:一个名字只有被当成**值**用到(`Name` load 或 `Attribute`)才算,
`"close_bad_rating": close_bad_rating` 这种挂进调度表的写法也算(它正是入口)。

**哪些文件不算「生产」**:检查(`*_check.py`)、自测(`selftest*`/`*_test.py`)、
评测与判分对照(`*_eval.py`/`*_judgetest.py`)。
⚠️ 这条**必须这么划**:`customer_rate`(顾客打分)现在的唯一调用方是
`agent/rating_eval.py` —— **一个评测脚本**。把评测算成入口的话,
「只有评测走得到」会被记成「有人在用」,而真实顾客仍然没有门。

## 上限 7(只许降不许涨)

和来源欠账、咬合记录同一个办法:**把现状登记成欠债**。
2026-10-12 首次扫出来 7 个(关差评当天补上了门,所以它不在里面):

    quote_write.py   :: 这个方案的报价 / 落一次报价 / 作废一条报价   报价没有门
    rating_write.py  :: customer_rate / customer_edit_rating        顾客打分、改评价没有门
    repair_write.py  :: 下单量体 / 判责建议                          一处引用都没有

⚠️ **要求立刻全补会有一个下场:这条检查被注释掉。** 每一个都要先定「门开在哪、给谁」,
那是业务设计,不是改代码。所以**只许降**:补了门就把这个数改小,**别把检查改掉**。

## ⚠️ 明写的盲区:它验的是「有没有人调」,不是「那个调用方接到了门上」

咬合当场逼出来的,而且**连错两次**才找到对的攻击点:
  ① 「把 `close_bad_rating` 从 `api.TOOLS` 调度表里摘掉」—— **没红**:
     `api.py` 里那个包装函数自己那句 `rw.close_bad_rating(...)` 就算「有人调它」。
  ② 「让包装函数不再真的调写口」—— **还是没红**,而这一条暴露了更深的那层:
     **api 层的包装函数和写口同名**,所以任何对包装函数的引用(包括调度表里那个
     `"close_bad_rating": close_bad_rating`)都被算成对写口的引用。
     **名字一样,两个东西在这条检查眼里就是一个东西。**
也就是说「包装了但没登记进工具表」这一层,这条检查看不出来;
它看得出来的是**「一个写口全仓没有任何生产代码碰它」**(昨天关差评就是这个状态),
以及**「新写一个写口没给它门」**(棘轮在拦的那个退化,咬合打的就是这一点)。
> 如果只跑「对照是绿的」,这条检查会带着一个假承诺进门禁 ——
> 咬合三关里的第 ② 关(改坏要红)就是为这个存在的。

那一层**另有人管**,不在这儿重复:`isolation_check` 逐个走 `api.WRITE_TOOLS`、
`prompts_check` 的 P6 强制「挂了工具就有管它的规矩」、`doc_numbers_check` 对账工具数。
这条判据独有的那一份价值是 **「全仓没有任何生产代码调它」** ——
那正是 2026-10-11 关差评那个写口的状态。
"""
import ast, os, sys, warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

无主上限 = 7      # 2026-10-12 立。补了门就改小,别改检查

跳目录 = {"__pycache__", ".git", ".venv", "node_modules", "onetime-deepseek-20260915"}


def 不算生产(文件名):
    """检查 / 自测 / 评测不算入口 —— 理由写在模块头(把评测算成入口会掩盖真实缺门)。"""
    return ("_check" in 文件名 or 文件名.startswith("selftest")
            or 文件名.endswith(("_test.py", "_eval.py", "_judgetest.py")))


def 被当成值用到(路径):
    """返回这个文件里所有「被当成值读」的名字。注释和字符串里的名字不在内。"""
    用 = set()
    try:
        # ⚠️ 压掉 SyntaxWarning:库里有文件写着 `"\\)"` 这类无效转义,
        # 解析时每个都会喷一行 —— 而**那是另一条检查的活**,
        # 在这儿喷出来只会把这条检查自己的结论顶出屏幕。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            树 = ast.parse(open(路径, encoding="utf-8").read())
    except Exception:
        return 用                      # 语法坏了另有检查管,这儿不借题报错
    for n in ast.walk(树):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            用.add(n.id)
        elif isinstance(n, ast.Attribute):
            用.add(n.attr)
    return 用


def main():
    写口 = {}
    for f in sorted(os.listdir(os.path.join(ROOT, "backend"))):
        if not f.endswith("_write.py"):
            continue
        树 = ast.parse(open(os.path.join(ROOT, "backend", f), encoding="utf-8").read())
        写口[f] = [n.name for n in 树.body
                   if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]

    生产用, 只在非生产 = {}, {}
    for 根, 目, 文 in os.walk(ROOT):
        目[:] = [d for d in 目 if d not in 跳目录]
        for f in 文:
            if not f.endswith(".py"):
                continue
            路 = os.path.join(根, f)
            桶 = 只在非生产 if 不算生产(f) else 生产用
            for 名 in 被当成值用到(路):
                桶.setdefault(名, set()).add(f)

    无主 = []
    for m, 名单 in 写口.items():
        for 名 in 名单:
            外 = {x for x in 生产用.get(名, set()) if x != m}
            if not 外:
                无主.append((m, 名, sorted(只在非生产.get(名, set()))))

    扫了 = sum(len(v) for v in 写口.values())
    bad = []

    # ── ① 样本量:空集合上什么都成立 ───────────────────────────────────
    if len(写口) < 5 or 扫了 < 20:
        bad.append(f"只扫到 {len(写口)} 个写口模块 / {扫了} 个公开函数"
                   f"(应该 5 个模块、20 个函数以上)—— **是没扫到东西,不是都通过**")

    # ── ② 棘轮:没有门的写口只许降不许涨 ──────────────────────────────
    if len(无主) > 无主上限:
        bad.append(f"没有生产入口的写口 {len(无主)} 个,**涨了**(上限 {无主上限})——\n"
                   "       新写一个写口就必须同时给它一扇门:进 `api.TOOLS` / 挂上页面 / "
                   "给模型。\n       **别改这个上限来放行** ——"
                   "「写好了」和「有人走得到」是两件事,而回归测试全绿不会告诉你缺门")

    print(f"写口得有门 · 扫了 {len(写口)} 个 `*_write.py` 模块、{扫了} 个公开函数")
    for m, 名, 只被 in 无主:
        print(f"    {Y}⚠️{D} {m} :: {名}"
              + (f"   —— 只被{只被} 调到(检查/评测不算门)" if 只被 else "   —— 一处引用都没有"))

    if bad:
        print(f"{R}❌ 写口的入口有 {len(bad)} 处不对{D}")
        for b in bad:
            print(f"    {R}❌{D} {b}")
        return 1
    print(f"{G}✅ 没有门的写口 {len(无主)} 个,没涨(上限 {无主上限}){D}")
    print(f"    {Y}⚠️ 这不是「都有门」—— 是「欠的还是那几笔」。"
          f"补了门要把上限改小,那是收紧{D}")
    return 0


# 咬合记录(规格在 tools/bite_specs.json,`python3 tools/bite_run.py --only entrypoint_check` 重放)
咬合 = [
    ("往 rating_write.py 里加一个公开写口函数、不给它任何门(这正是这条棘轮在拦的退化)",
     "**涨了**(上限 "),
]

if __name__ == "__main__":
    sys.exit(main())
