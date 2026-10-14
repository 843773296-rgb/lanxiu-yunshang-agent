#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具的 **Python 签名**和挂给模型的 **MCP schema** 必须对得上。

## 为什么要有这条

2026-10-14 给 `close_bad_rating` 加了个 `amount` 参数(退了多少钱)。
Python 签名改了、写口改了、口径改了、判据 61 条全过 ——
**而 MCP schema 里没加**,于是**模型根本看不到这个参数**。

后果不是报错:模型关「部分退款」的差评时填不了金额,
被同一笔里新加的那道闸拒掉 —— **功能直接坏了,而所有判据都是绿的**。

> 一个「模型可以填这个参数」和一个「函数签名有它但模型看不到」,
> **在 Python 代码上长得一模一样。**

这个仓库有 93 个业务工具,每个都是**两份**:一个 Python 函数 + 一段 schema。
两份就会漂,而漂的方向只有一种后果 —— 模型拿不到那个能力,
或者填了一个函数不认的参数(那会 TypeError,在模型眼里是工具坏了)。

## 这条验什么

逐个工具比两边的参数名:

  schema 有而函数没有  → 模型会填一个函数不认的参数 → **TypeError**
  函数有而 schema 没有 → 模型**看不到**这个参数(本次那个形状)
  schema 的 required 里有函数没有默认值之外的东西 → 对不上

⚠️ **不比类型、不比描述** —— 那两样会有大量正当的差异
(比如函数收 str 而 schema 写 number)。只比**名字对不对得上**:
这是「漂没漂」最硬的那一层,而且不会误报。
"""
import inspect, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("给某个工具的 Python 函数加一个参数而 schema 里不加(本次 close_bad_rating 那个形状)",
     "函数有而 schema 里没有"),
    ("往某个 schema 里加一个函数不认的参数名",
     "schema 有而函数没有"),
]


# ── 欠着的:函数收这个参数,而挂给模型的说明里没有它 ──────────────────────
#
# 照 `tools/insert_shape_check.py` 那个欠债表的模式:**不拦现状,只许少不许多**。
# 2026-10-14 这条判据第一次跑就扫出 13 处,**都不是这一笔造成的** ——
# 而我**判不准其中大多数该不该暴露**,所以不猜:分成「明确刻意」和「待判定」两类,
# 待判定的照样登记在这儿,等人去看。
#
# > 一条「我判断它不该暴露」和一条「我没看懂所以没动」,
# > **在那个豁免名单上长得一模一样** —— 所以这儿要写清是哪一种。
欠着 = {
    # ① 明确刻意:`today` 是给**判据**控制时间用的注入口,不该给模型。
    #    项目的规矩是「谁负责判定,谁就不该同时负责取时间」(第 9 节①),
    #    而让模型传「今天」比这更糟:它传错了,整条推算都错,而看不出来。
    "recovery_queue.today": "刻意 —— 判据注入时间用,不给模型(让模型传今天=让它决定现在几点)",
    "plan_for_event.today": "刻意 —— 同上。场景倒推全靠这个日子,模型传错了整条推算都错",

    # ② 待判定:看着像**真缺口**,但我没查实,所以不改也不声称它没问题。
    #    时间范围这一组最可疑:用户问「上个月的评价概况」,模型现在**没法表达那个范围**。
    "rating_overview.start": "待判定 —— 时间范围。模型现在没法问「上个月的评价概况」",
    "rating_overview.end": "待判定 —— 同上",
    "monthly_review.start": "待判定 —— 时间范围",
    "monthly_review.end": "待判定 —— 时间范围",
    "weekly_revenue.start": "待判定 —— 时间范围",
    "weekly_revenue.end": "待判定 —— 时间范围",
    # ③ **假缺口**:这三个是中文别名,英文那一半早就暴露着。
    #    `orders_by_date(…, 月份=None, 起=None, 止=None, month=None, start=None, end=None)`
    #    —— 成对声明的别名,而 schema 用的是 `month`/`start`/`end`。
    #    ⚠️ **这条判据在这里报对了事实、报错了意思**:它只比名字,
    #    看到「函数有 `起` 而 schema 没有」就报漏,而那个能力并没有缺。
    #    > 一个「这个能力模型拿不到」和一个「这个能力有两个名字、
    #    > 而 schema 用的是另一个」,**在这个比较上长得一模一样。**
    #    补别名是**纯噪音**:给模型两个名字填同一件事,只会让它犹豫该填哪个。
    "orders_by_date.起": "假缺口 —— `start` 的中文别名,英文那一半已暴露",
    "orders_by_date.止": "假缺口 —— `end` 的中文别名,英文那一半已暴露",
    "orders_by_date.月份": "假缺口 —— `month` 的中文别名,英文那一半已暴露",
    "kb_fit.wearer": "待判定 —— 着装人。一个客户可能有好几个着装人(妈妈给两个孩子做),"
                     "而模型现在指不定是哪一个",
    "list_tasks.status": "待判定 —— 有默认值「待处理」,所以模型**只看得到待处理的**,"
                         "问「已关闭的人工任务」问不出来",
}


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


def main():
    import api
    print("工具签名 vs MCP schema · 两份会漂,而漂了模型就拿不到那个能力")
    表 = []
    for 名 in ("SHOP_SCHEMAS", "KB_SCHEMAS", "SCHEMAS"):
        表 += list(getattr(api, 名, []) or [])
    ck(f"样本量:扫到 {len(表)} 段 schema(0 段的话下面全是空集合上的真)",
       len(表) >= 50, f"只扫到 {len(表)} 段 —— 是没扫到,不是都通过")

    缺函数, 多参, 少参 = [], [], []
    for t in 表:
        工 = t.get("name")
        fn = getattr(api, 工, None)
        if not callable(fn):
            # schema 挂着一个 api 里没有的函数 —— 模型会调一个不存在的东西
            缺函数.append(工)
            continue
        形 = inspect.signature(fn).parameters
        函参 = {k for k, v in 形.items()
               if v.kind in (v.POSITIONAL_OR_KEYWORD, v.KEYWORD_ONLY)}
        架参 = set((t.get("input_schema") or {}).get("properties") or {})
        for x in sorted(架参 - 函参):
            多参.append(f"{工}.{x}")
        for x in sorted(函参 - 架参):
            少参.append(f"{工}.{x}")

    ck("每段 schema 都对着一个真的函数", not 缺函数,
       f"这些 schema 的名字在 api 里找不到函数:{缺函数} —— "
       f"模型会去调一个不存在的东西")
    ck("**schema 有而函数没有**(模型会填一个函数不认的参数 → TypeError)", not 多参,
       f"{多参} —— schema 里挂着函数不认的参数名")
    新漏 = [x for x in 少参 if x not in 欠着]
    ck("**没有新增「函数有而 schema 里没有」的**(模型看不到这个参数)", not 新漏,
       f"{新漏} —— 函数收这个参数,而挂给模型的说明里没有它。"
       f"后果不是报错:模型**不知道可以填**,于是该填的不填,"
       f"被别处的闸拒掉,而那看起来像模型不会用工具。"
       f"(2026-10-14 `close_bad_rating.amount` 就是这么漏的)"
       f"要么往 schema 里加它,要么登记进这个文件的 `欠着` 并写清是「刻意」还是「待判定」")
    陈 = [x for x in 欠着 if x not in 少参]
    ck(f"欠债表里没有过期的(补上了就从表里删掉)", not 陈,
       f"{陈} —— 这几条已经不漏了(schema 补上了),把它从 `欠着` 里删掉。"
       f"**留着过期的豁免,下一次真漏了就被它放过去**")
    假 = [k for k, v in 欠着.items() if v.startswith("假缺口")]
    if 假:
        print(f"\n  {Y}ℹ 其中 {len(假)} 处是**假缺口**(中英文别名,另一半已暴露)—— "
              f"这条判据只比名字,所以它报对了事实、报错了意思{D}")
        print(f"     {Y}  {假}{D}")
        print(f"     {Y}  ⚠️ **别给它们补 schema**:给模型两个名字填同一件事,"
              f"只会让它犹豫该填哪个{D}")
    待 = [k for k, v in 欠着.items() if v.startswith("待判定")]
    print(f"\n  {Y}ℹ 欠着 {len(欠着)} 处(不拦门禁,**只许少不许多**):"
          f"其中「刻意」{len(欠着)-len(待)} 处、**「待判定」{len(待)} 处**{D}")
    print(f"     {Y}  待判定的那些**没人判过**,不是判过没问题 —— "
          f"最可疑的是时间范围那一组:用户问「上个月的评价概况」,"
          f"模型现在没法表达那个范围{D}")

    print(f"\n📌 **只比参数名对不对得上**,不比类型和描述 —— "
          f"那两样有大量正当差异,比了会变成噪音。")
    if bad:
        print(f"\n{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
        for b in bad:
            print(f"   · {b}")
        return 1
    print(f"\n{G}✅ 93 个业务工具的签名和 schema 对得上(验了 {n} 条,"
          f"扫了 {len(表)} 段 schema){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
