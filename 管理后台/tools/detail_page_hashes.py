#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给每个**详情页**取一个真实 id,拼成页面冒烟用的 hash。

    python3 tools/detail_page_hashes.py            # 打出 hash 清单
    python3 tools/detail_page_hashes.py --钉住 N    # 取不到的超过 N 个就退 1

## 为什么要这个脚本

2026-10-07 发现:`make page-smoke` 的冒烟名单里 **21 个全是一级页**,
`#/prompt/{id}` / `#/tool/{id}` / `#/chunk/{id}` 这 **12 个详情页一个都没有**。

而 `nav_smoke_check.py` 的判据是「侧栏**能点开**的页都要在名单里」——
详情页点不开(它要一个 id),**按设计就不在它视野里**。

> 一份「23 页都在冒烟名单里」的报告,和一份「全部详情页从来没被打过」的,
> **在那句话上长得一模一样** —— 因为那句话说的是真的,
> 只是它说的不是「全部页面」。

## ⚠️ id **从库里现取,不写死**

CLAUDE.md 第 8 节:「夹具不许写死会漂的东西 —— id 会被一次合理的数据变更打断」。
写死一个 id 的下场:哪天那条数据被清了,冒烟会报「这一页打不开」,
而根因是夹具过期 —— **那条红指向的地方是错的**。

## ⚠️ 取不到 id 要**喊出来**,不许静默跳过

> 一份「12 个详情页都冒烟过了」的报告,和一份「其中 5 个因为库里没数据
> 被跳过」的,**在那个绿勾上长得一模一样。**

所以取不到的个数**钉住**(照 `jsonb_cast_check.py` 的成语):现状几个就钉几个,
涨了就红 —— 新增一个取不到的必须当场被看见。
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))

from sqlalchemy import create_engine, text   # noqa: E402

G, Y, R, D = "\033[32m", "\033[33m", "\033[31m", "\033[0m"

# (hash 前缀, 页面函数, 取 id 的表, 额外条件)
# ⚠️ 每一条都对着 `apps/web/app.js` 路由里那一行 —— 加了新详情页要同时加这儿,
#    否则它又变成一个「没人冒烟过」的页面。`nav_smoke_check.py` 盯着这件事。
页们 = (
    ("#/prompt/",   "页_prompt详情", "prompt_drafts",    ""),
    ("#/human/",    "页_待办详情",   "human_requests",   ""),
    ("#/trace/",    "页_调用树",     "traces",           ""),
    ("#/workflow/", "页_画布",       "workflows",        ""),
    ("#/wfrun/",    "页_运行详情",   "execution_runs",   ""),
    ("#/agent/",    "页_agent配置",  "agents",           ""),
    ("#/tool/",     "页_工具详情",   "tool_definitions", ""),
    ("#/app/",      "页_应用详情",   "applications",     ""),
    ("#/samples/",  "页_样本",       "datasets",         ""),
    ("#/kb/",       "页_索引构建",   "knowledge_bases",  "and archived_at is null"),
    ("#/chunks/",   "页_切片列表",   "knowledge_bases",  "and archived_at is null"),
    ("#/chunk/",    "页_切片详情",   "chunks",           ""),
)

# 现状:取不到 id 的有几个。**多一个就红** —— 新增的「没数据所以冒烟不到」
# 必须当场被看见,而不是悄悄涨上去。
取不到上限 = 0


def 路由里的详情页():
    """从 `apps/web/app.js` 的路由里扫出所有 `#/xxx/` 形式的页。

    ⚠️ **登记和判据放在同一个文件里。** 否则:
    > 一个「12 个详情页都登记了」的表,和一个「有人加了第 13 个而没登记」的,
    > **在那张表上长得一模一样** —— 而新加的那个会悄悄变成
    > 「从没被冒烟打过」的第 13 个页面。
    """
    import re
    js = os.path.join(ROOT, "apps", "web", "app.js")
    文 = open(js, encoding="utf-8").read()
    return {m.group(1) for m in
            re.finditer(r'h\.startsWith\("(#/[a-z]+/)"\)', 文)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--项目", default="project_demo_a",
                    help="冒烟用的那个项目(默认身份 U002 看得到的)")
    ap.add_argument("--钉住", type=int, default=None)
    ap.add_argument("--只要hash", action="store_true", help="只打 hash,给 shell 循环用")
    a = ap.parse_args()

    # ── 先对一遍:路由里的详情页都登记了吗 ──────────────────────────
    路由 = 路由里的详情页()
    登记 = {x[0] for x in 页们}
    漏登记 = sorted(路由 - 登记)
    多登记 = sorted(登记 - 路由)
    if (漏登记 or 多登记) and not a.只要hash:
        print(f"\n  {R}❌ 路由和登记对不上{D}")
        if 漏登记:
            print(f"     路由里有、这儿**没登记**:{漏登记}")
            print(f"     → 它们会悄悄变成「从没被冒烟打过」的页面。加进 `页们`。")
        if 多登记:
            print(f"     这儿登记了、路由里**没有**:{多登记}")
            print(f"     → 名单过期了(那一页删了或改了 hash),"
                  f"而一条指向不存在页面的记录会让人以为它被测着。")
        return 1
    if 漏登记 or 多登记:
        return 1

    URL = os.environ.get("DATABASE_URL") or \
        "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
    eng = create_engine(URL)
    出, 取不到 = [], []
    for 前缀, 函数, 表, 条件 in 页们:
        # ⚠️ 每条用**独立连接** —— 一条查失败会让整个事务 aborted,
        # 后面全部报「current transaction is aborted」,
        # 而那读起来像「这些表都有问题」,实际只有第一个有问题。
        try:
            with eng.connect() as c:
                i = c.execute(text(
                    f"select id from {表} where project_id=:p {条件} "
                    f"order by created_at desc limit 1"), {"p": a.项目}).scalar()
        except Exception as e:
            取不到.append((前缀, 函数, 表, f"{type(e).__name__}: {str(e)[:60]}"))
            continue
        if not i:
            取不到.append((前缀, 函数, 表, f"{表} 在 {a.项目} 里一条数据都没有"))
            continue
        出.append((前缀 + i, 函数, 表))

    if a.只要hash:
        for h, _, _ in 出:
            print(h)
        return 1 if (a.钉住 is not None and len(取不到) > a.钉住) else 0

    print(f"\n\033[1m▸ 详情页的冒烟 hash(id 从库里现取,不写死)\033[0m")
    print(f"  项目 {a.项目} · 登记了 {len(页们)} 个详情页")
    for h, 函数, 表 in 出:
        print(f"  {G}✅{D} {h:46} {函数:14} ← {表}")
    if 取不到:
        print(f"\n  {Y}⚠️ {len(取不到)} 个取不到 id —— **这不是「冒烟过了」**{D}")
        for 前缀, 函数, 表, 说 in 取不到:
            print(f"     {前缀:12} {函数:14} {说}")
    钉 = 取不到上限 if a.钉住 is None else a.钉住
    if len(取不到) > 钉:
        print(f"\n  {R}❌ 取不到 id 的有 {len(取不到)} 个,超过钉住的 {钉} 个{D}")
        print(f"     要么给那个表铺一条种子数据,要么确认过之后把上限改大"
              f"**并写清为什么** —— 一个「没数据所以没冒烟」的详情页,"
              f"和一个「冒烟过了」的,在那份名单上长得一模一样。")
        return 1
    print(f"\n{G}  ✅ {len(出)}/{len(页们)} 个详情页拿得到真实 id;"
          f"取不到 {len(取不到)}/{钉}{D}")
    return 0


# ── 咬合(实跑,下面每条「预期红」都是**抄的真实输出**)──────────────────
#   ① 对照                        → ✅ 12/12 个详情页拿得到真实 id;取不到 0/0
#   ② 从 `页们` 里删掉 `#/chunk/`  → ❌ 路由和登记对不上
#                                    路由里有、这儿**没登记**:['#/chunk/']
#                                    退出码 1
#
# ⚠️ **第 ② 关我做错过一次,而错的方式值得记。**
# 第一版我用 python 字符串替换去删那一行,**缩进没对上**(原文 5 个空格、
# 我写了 4 个)—— 替换静默失败,登记表一个字没变,然后我看到「没红」,
# 差点下结论说这条检查不管用。
# > 一次「改坏了而检查没红」和一次「根本没改坏」,
# > **在那个「没红」上长得一模一样。**
# 这个项目记过咬合的两种失效(注入没进检查的视野、破坏点本身不可观测),
# 这是**第三种:注入根本没发生**。
# **修法:咬合前先确认注入生效了** —— 这里是数登记表的行数(12 → 11),
# 而更省事的办法是用会在不匹配时报错的工具做注入,别用静默替换。
if __name__ == "__main__":
    sys.exit(main())
