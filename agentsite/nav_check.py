#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导航检查 —— **有页面没入口,不会报错,只会没人点得到。**

## 为什么有这条

2026-09-25 用户报「很多功能还缺入口」。查下来:17 个页面里只有 7 个带统一顶栏,
面板 / 任务 / 着装人 / AI 调控中心 / 调试后台 / 实验对比都有页面、导航上没有;
而导航第一项写着「值班台」,点进去却是**智能助手对话页** —— 名字和目标不是一回事。

根因:导航原来是**手写在 _shell.txt 里的一段 HTML**,而且 chat / scheme / workbench /
acceptance **各自又抄了一份**(四份都是 7 项的旧版)。加页面的人不会想起来去改它们,
**而漏改不报错**。

所以这条检查断言三件事:

  ① `PAGES` 里每一条路径,要么挂在顶栏上,要么在「不挂」里**写明为什么**
  ② 顶栏和「不挂」里的路径,都得真的是 `PAGES` 里有的(别囤积死链)
  ③ 导航**只有一个来源**:页面里不许再出现手写的 `<a ... data-p=` 导航项

⚠️ 第 ③ 条是这次的关键。前两条防的是「忘了加入口」,第三条防的是
**「加了入口但加在了第五份拷贝上」** —— 而那种错在本地点一点是发现不了的:
你点的那一页正好是你改过的那一份。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

咬合 = [
    ("在 PAGES 里加一个页面但不登记进 nav", "每个页面要么挂顶栏、要么写明为什么不挂"),
    ("在某个页面里手写一份导航项(data-p)", "导航只有一个来源"),
    ("给一个已经有顶栏的页面再加一条 <nav class=\"sitenav\">", "每个页面最多一条顶栏"),
    ("在「不挂」里留一条 PAGES 里已经没有的路径", "登记表里没有死链"),
]

FAIL, N = [], [0]


def ck(名, 真, 补=""):
    N[0] += 1
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if 补 else ''}")
    if not 真: FAIL.append(名)


def 页面路径(src=None):
    s = src if src is not None else open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    出 = set(re.findall(r'"(/[a-z]*)":\s*"[\w./]+\.html"', s))
    # /ai/<模块> 那一批由一行 update 生成 —— 它们共用 ai.html,不是独立入口
    return {p for p in 出 if p}


def 导航条数(目录=None):
    """每个页面**恰好一条**顶栏。

    ⚠️ 2026-09-25 用户截图发现:面板页上叠了两条横栏 —— 我上一轮给它盲加了
    `<!--NAV-->`,而它**自带一条**(类名不同、用 `data-s=` 切页内视图),
    所以「手写导航」那条检查没抓到。**检查抓不到它没见过的形状。**
    数「有几条 sitenav」是形状无关的:不管那条是谁加的、长什么样,两条就是两条。
    """
    import os as _o
    d = 目录 or _o.path.join(HERE, "web")
    出 = {}
    for f in sorted(_o.listdir(d)):
        if not f.endswith(".html"): continue
        n = open(_o.path.join(d, f), encoding="utf-8").read().count('class="sitenav"')
        if n > 1: 出[f] = n
    return 出


def 手写导航的页面(目录=None):
    d = 目录 or os.path.join(HERE, "web")
    出 = {}
    for f in sorted(os.listdir(d)):
        if not f.endswith(".html"): continue
        t = open(os.path.join(d, f), encoding="utf-8").read()
        n = len(re.findall(r'<a\s[^>]*data-p=', t))
        if n: 出[f] = n
    return 出


def 跑(src=None, 目录=None):
    import nav
    页 = 页面路径(src)
    ck("扫到了页面清单", len(页) >= 10, f"{len(页)} 个:{' '.join(sorted(页))}")
    漏 = sorted(页 - nav.全部登记的())
    ck("每个页面要么挂顶栏、要么写明为什么不挂", not 漏,
       f"没登记的:{漏} —— **有页面没入口不会报错,只会没人点得到**" if 漏 else
       f"顶栏 {len(nav.顶栏)} 项、明确不挂 {len(nav.不挂)} 项")
    死 = sorted(nav.全部登记的() - 页)
    ck("登记表里没有死链", not 死, f"登记了但 PAGES 里没有:{死}" if 死 else "")
    # 顶栏项的名字不许和它指的页面对不上 —— 这次那个 bug 就是「值班台」指向对话页
    对 = dict((a, b) for a, b, _ in nav.顶栏)
    ck("顶栏第一项是对话页(而不是别的页顶着「值班台」的名字)",
       对.get("/") == "对话", 对.get("/"))
    多 = 导航条数(目录)
    ck("每个页面最多一条顶栏(别叠两条)", not 多,
       f"叠了两条的:{多} —— 用户 2026-09-25 截图发现的,而「手写导航」那条检查抓不到它"
       if 多 else "没有页面叠两条")
    手 = 手写导航的页面(目录)
    ck("导航只有一个来源(页面里没有手写的导航项)", not 手,
       f"这些页面里还有手写导航:{手} —— **加了入口却加在第五份拷贝上,本地点一点发现不了**"
       if 手 else "16 个页面共用 nav.py 那一份")
    for k in nav.不挂:
        if not (nav.不挂[k] or "").strip():
            ck(f"「不挂」{k} 写了理由", False, "不挂是决定,不是遗漏 —— 写下来才分得开")


def _自测():
    print("\n咬合:改坏了要红\n" + "-" * 80)
    import tempfile, nav
    过 = []
    def 咬(名, 跑法, 应红):
        FAIL.clear(); N[0] = 0
        跑法()
        中 = any(应红 in f for f in FAIL)
        过.append(中)
        print(f"  {'✅' if 中 else '❌'} 咬合「{名}」→ {FAIL or '全绿'}")

    # ① 多一个没登记的页面
    咬("PAGES 里多一个没登记的页面",
       lambda: 跑(src='PAGES = {"/": "station.html", "/zzz": "zzz.html"}\n' * 1 + 'x="/duty": "duty.html"'),
       "每个页面要么挂顶栏、要么写明为什么不挂")
    # ② 某个页面里手写导航
    d = tempfile.mkdtemp()
    open(os.path.join(d, "x.html"), "w", encoding="utf-8").write('<a href="/duty" data-p="/duty">值班台</a>')
    咬("某个页面里手写一份导航项", lambda: 跑(目录=d), "导航只有一个来源")
    FAIL.clear()
    print(f"\n{'✅' if all(过) else '❌'} 咬合 {sum(过)}/{len(过)} 条如预期")
    return 0 if all(过) else 1


if __name__ == "__main__":
    print("导航 · 每个页面都有入口,而且入口只有一个来源")
    print("=" * 84)
    跑()
    坏 = list(FAIL)
    rc = _自测()
    print()
    if 坏 or rc:
        print(f"\033[31m❌ 导航 {len(坏)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in 坏: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 导航全过\033[0m —— 页面都有入口,入口只有一份")
