#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""侧栏上**能点开**的每一页,都要在页面冒烟的名单里。

## 为什么需要它

2026-10-01 查出来:冒烟名单里**少了七页** ——
`apps` / `conns` / `members` / `datasets` / `training` / `artifacts` / `audit`,
也就是 09-29 新建的那一批。**它们在门禁里从来没被冒烟打过。**

我手动打过每一页(当时都通了),而**手动打过不算** ——
下一次有人改动它们,没有任何东西会红。

而这件事在所有现有判据上都是绿的:
  · `nav_check` 看「侧栏登记的页是不是都能点开」
  · `test_registry_check` 看「端到端测试在两个目标里都登记了吗」
  · **没有一条看「能点开的页,冒烟打过吗」**

> **一个新页面默认是不被冒烟盖住的** —— 而「忘了加」和「故意不加」
> 在 Makefile 上长得一模一样。

## 这条判据怎么判

`apps/web/app.js` 里那张 `导航` 表,第三项是「能点开吗」。
能点开的(`true`)、而且不是分组标题(`grp`)的,hash 必须出现在
`Makefile` 的冒烟循环里。

三种红法:
  · **能点开但不在冒烟名单**:红。新加一页必须同时回答「冒烟打不打它」。
  · **在冒烟名单里但侧栏没登记**:红(名单过期 —— 一条指向不存在页面的
    冒烟会在有人重用这个 hash 那天悄悄放行它)。
  · **一页都没扫到**:红(**扫不到不是通过**)。

## 已知盲区(写下来,才和「忘了」分得开)

- **只看「打没打」,不看「打得够不够」。** 一页在冒烟里过了,
  只说明加载路径跑通 + 行级对账(如果 `page_smoke.js` 的对账表里声明了)。
  渲染对不对那一半仍然只有真浏览器那一份。
- **详情页不在这张表里**(`#/app/{id}` 这种)。侧栏上没有它们的入口,
  所以这条判据管不到 —— 它们靠各自的驱动测试和手动冒烟。
"""
import os
import re
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 例外:**点名 + 写理由** ────────────────────────────────────────────
# 说不清为什么不该被冒烟打的,就不是例外,是漏登记。
例外 = {
    # (暂时没有。有了就写在这里,并说清为什么)
}


def main():
    print(f"\n\033[1m▸ 侧栏能点开的页,冒烟打过吗{D}")
    print("  ⚠️ 这条判据看的是**「能点开的页,冒烟打过吗」** —— "
          "`nav_check` 看能不能点开,`test_registry_check` 看测试登记,"
          "**都不看这个**")

    js = os.path.join(根, "apps", "web", "app.js")
    mk = os.path.join(根, "Makefile")
    for 路 in (js, mk):
        if not os.path.isfile(路):
            print(f"  {R}❌ 找不到 {路}{D}")
            return 1

    源 = open(js, encoding="utf-8").read()
    # 导航表:`["#/xxx", "中文", true, ...]` / `["grp", "分组名"]`
    m = re.search(r"const 导航 = \[(.*?)\n\];", 源, re.S)
    if not m:
        print(f"  {R}❌ 在 app.js 里找不到 `导航` 表 —— "
              f"**这条判据靠它定位,定位不到不是通过**{D}")
        return 1
    能点开的 = []
    for 行 in m.group(1).splitlines():
        g = re.match(r'\s*\["(#/[\w-]+)",\s*"[^"]*",\s*(true|false)', 行.strip())
        if g and g.group(2) == "true":
            能点开的.append(g.group(1))
    if not 能点开的:
        # ⚠️ 空集合上所有性质都成立。扫到 0 页就是正则过期了。
        print(f"  {R}❌ 一页都没扫到 —— **扫不到东西不是通过**"
              f"(多半是 `导航` 表的写法变了,正则该跟着改){D}")
        return 1
    print(f"  侧栏上能点开的页:{len(能点开的)} 个")

    正文 = open(mk, encoding="utf-8").read()
    # 冒烟循环里出现过的 hash(整个 Makefile 里搜 '#/xxx' 字面量就够 ——
    # 只在冒烟那一段搜要先切段,而切段按函数名/目标名找边界很脆:
    # 这一天被切错边界咬过三次)。
    在冒烟里 = set(re.findall(r"'(#/[\w-]+)'", 正文))

    漏 = [h for h in 能点开的 if h not in 在冒烟里 and h not in 例外]
    幽灵 = [h for h in 在冒烟里 if h not in 能点开的]

    if 例外:
        print(f"  {Y}⚠️ 明写的例外 {len(例外)} 个(**点名跳过,不是没看见**):{D}")
        for h, 为什么 in 例外.items():
            print(f"     · {h} —— {为什么}")

    if 幽灵:
        print(f"  {R}❌ 冒烟名单里这几个 hash,侧栏上没有(或者点不开):{幽灵}{D}")
        print(f"     一条指向不存在页面的冒烟,会在有人重用这个 hash 那天"
              f"**悄悄放行它** —— 那时它看起来一直是绿的。")
        return 1

    if 漏:
        print(f"\n  {R}❌ 这 {len(漏)} 页能点开,**而冒烟没打过**:{D}")
        for h in 漏:
            print(f"     {h}")
        print(f"\n     加进 `Makefile` 的冒烟循环,或者写进这个脚本的 `例外`"
              f"并**说清为什么**。")
        print(f"     ⚠️ 「忘了加」和「故意不加」在 Makefile 上长得一模一样 ——")
        print(f"     而一个没被冒烟盖住的页面,下次有人改动它时**没有任何东西会红**。")
        return 1

    print(f"\n  {G}✅ {len(能点开的)} 页都在冒烟名单里{D}")
    print(f"  ⚠️ 盲区:只看「打没打」,不看「打得够不够」——"
          f"渲染对不对那一半仍然只有真浏览器那一份")
    return 0


if __name__ == "__main__":
    sys.exit(main())
