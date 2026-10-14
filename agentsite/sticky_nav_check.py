#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""挂了全站导航的页面,自己的吸顶条不许也吸在 top:0 —— 静态扫,不用起服务。

    python3 agentsite/sticky_nav_check.py

2026-10-14 用户截图:面料学堂往下一滚,页面自己的标题栏和最上面那条全站导航**叠在一起**。
全站导航(`nav.py` 的 `.sitenav`)高 52px、吸在 top:0;页面里只要再有一条也吸在 top:0,滚动时就压在它上面。
查下来**三页都是**(面料学堂 / 经营报告 / 任务)—— 每页各自写的样式,谁都没想到上面还有一条。
> 一条「吸在顶上」的标题栏,在没挂导航的页面上是对的,挂了导航就是错的 —— 而两种页面的样式写法一模一样。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [("把经营报告的标题栏改回吸在 top:0", "挂了全站导航的页面,没有别的条也吸在 top:0")]


def 扫(目录=WEB):
    """→ (挂导航的页面数, [(页面, 选择器)] 违规的)"""
    挂, 坏 = 0, []
    for f in sorted(os.listdir(目录)):
        if not f.endswith(".html"):
            continue
        s = open(os.path.join(目录, f), encoding="utf-8").read()
        if "<!--NAV-->" not in s:
            continue
        挂 += 1
        for m in re.finditer(r"([^{}\n]+)\{([^}]*)\}", s):
            体 = m.group(2).replace(" ", "")
            if "position:sticky" in 体 and re.search(r"(^|;)top:0(px)?(;|$)", 体):
                坏.append((f, m.group(1).strip()[-40:]))
    return 挂, 坏


if __name__ == "__main__":
    挂, 坏 = 扫()
    ok_n = 挂 >= 3
    print(f"  {'✅' if ok_n else '❌'} 扫到挂全站导航的页面 {挂} 个(少于 3 个多半是导航占位符改名了,不是都通过)")
    print(f"  {'✅' if not 坏 else '❌'} 挂了全站导航的页面,没有别的条也吸在 top:0"
          + (f"  {坏} —— 改成 top:52px(导航高 52px)" if 坏 else ""))
    if 坏 or not ok_n:
        print(f"{R}❌ 吸顶条会和全站导航叠在一起{D}")
        sys.exit(1)
    print(f"{G}✅ 吸顶条都让开了全站导航(扫了 {挂} 页){D}")
