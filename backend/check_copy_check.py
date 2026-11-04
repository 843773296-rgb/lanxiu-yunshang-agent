#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库副本切干净了没有 —— 判据落在**连接**上,不落在模块变量上。

`backend/check_copy.py` 是这个项目唯一的切库口(23 条检查走它)。它守的事:
拷一份真库,把指着真库的库路径一次全改到副本上,**换完断言切干净了**。

## 为什么判据必须问连接

`tools/db_switchable_check.py` 扫的是**源码形状**(库路径别当默认参数值),
它自己写明了「不验运行时真的连上了哪个文件 —— 那要在连库那一刻取 PRAGMA database_list」。
这一份补的就是那一半。

而它**不是**「每个写口自己加一句断言」:那会变成一个每次都要记得加的参数,
**而一个每次都要加的安全参数等于没有这道防护**。断言装在那个唯一的切库口里,
每条检查免费拿到,没有谁需要记得。

## 这条判据逼出来的那次翻车(拿它当试纸)

2026-11-03 共享库 `rating` 1319 → 1264,**55 条评价没了**,而且丢的那一刻
另一个会话正在跑全量门禁,那一轮整个作废。病理是一行 Python 语义:
`def 铺(db=DB)` 的默认值在 **def 执行的那一刻**就算定了,之后 `模块.DB = 副本`
改不动它。**切库扫模块变量的那把扫帚看不见它。**

试纸在 ⑩:只换模块变量时,那个烤死的默认参数必须**仍然被报出来**。
扫不到它,就是判据的视野漏了 —— 不是「全都对」。
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import types
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_copy  # noqa: E402
from check_copy import (  # noqa: E402
    连错库, 规范, 实际连的是, 确认连的是, 确认是另一份,
    换模块变量, 换默认参数, 还指着真库的, 用副本, 真库, _本项目的模块,
)


# ── 自测 ──────────────────────────────────────────────────────────────
# ⚠️ 大半是**合成**的:造一个假模块 + 一个临时库,不碰共享真库。
#    只有最后一条走真 `用副本()`,而真库不在时它报「不适用」—— **不是通过**。

def main():
    G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
    过, 挂, 没验 = 0, [], []

    def ck(编, 行不行, 说, 详=""):
        nonlocal 过
        if 行不行:
            过 += 1
            print(f"  {G}✅{D} {编} {说}")
        else:
            挂.append(f"{编} {说}")
            print(f"  {R}❌{D} {编} {说}" + (f"\n        {详}" if 详 else ""))

    def 抛吗(f):
        try:
            f()
            return None
        except 连错库 as e:
            return str(e)

    目 = tempfile.mkdtemp(prefix="cc-self-")
    try:
        甲 = os.path.join(目, "甲.db")
        乙 = os.path.join(目, "乙.db")
        for p in (甲, 乙):
            with closing(sqlite3.connect(p)) as c:
                c.execute("create table t(a)")
                c.commit()
        链 = os.path.join(目, "看着像副本.db")
        os.symlink(甲, 链)
        # ⚠️ 和 甲 **同名、不同目录** —— 真实情况正是这样:副本也叫 lanxiu.db。
        #    少了它,「把判据改成比 basename」这个破坏点**不可观测**
        #    (合成用例本来是 甲.db / 乙.db,basename 天然不同)。
        同名目 = os.path.join(目, "另一处")
        os.makedirs(同名目)
        同名 = os.path.join(同名目, os.path.basename(甲))
        with closing(sqlite3.connect(同名)) as c:
            c.execute("create table t(a)")
            c.commit()

        print("\n  库副本:切库切干净了没有 · 断言落在连接上(合成用例,不碰共享真库)")

        # ① 规范:内存库的三种写法归成一个
        ck("①", all(规范(x) == ":memory:" for x in (None, "", ":memory:")),
           "内存库的三种写法都归成 ':memory:'")

        # ② 钉住 macOS 那个坑:PRAGMA 报的是 realpath,不是传进去那个串
        with closing(sqlite3.connect(甲)) as c:
            报 = 实际连的是(c)
        ck("②", 报 == os.path.realpath(甲),
           "连接报的是 realpath 之后的路径(macOS 上 /var 自己是软链,"
           "所以期望那边也得 realpath)", f"报的 {报}")

        # ③ 内存库
        with closing(sqlite3.connect(":memory:")) as c:
            ck("③", 实际连的是(c) == ":memory:", "内存库报 ':memory:'")

        # ④ 连对了不许抛
        with closing(sqlite3.connect(甲)) as c:
            ck("④", 抛吗(lambda: 确认连的是(c, 甲)) is None, "连的就是以为的那个 → 不抛")

        # ⑤ 反向:连接落在**别的**库上 → 抛(这是默认参数烤死 / 老句柄那两种)
        with closing(sqlite3.connect(甲)) as c:
            说 = 抛吗(lambda: 确认连的是(c, 乙, "咬一口"))
            ck("⑤", 说 is not None and os.path.realpath(甲) in 说,
               "**反向**:连接落在别的库上 → 抛,而且说清**实际**落在哪",
               f"抛的是 {说!r}")

        # ⑤b 反向(cp -R 那个坑):一条解回真库的软链冒充副本
        ck("⑤b", 抛吗(lambda: 确认是另一份(链, 甲, "咬一口")) is not None,
           "**反向**:软链冒充副本(解回去就是那个库)→ `确认是另一份` 抛")

        # ⑤c ⚠️ 钉住一条**构造性验不了**的事:同一个坑用 `确认连的是` 永远通过
        #     第一版 `用副本` 里写的就是那条。这条用例的作用是防它被改回去。
        with closing(sqlite3.connect(链)) as c:
            ck("⑤c", 抛吗(lambda: 确认连的是(c, 链)) is None,
               "⚠️ `确认连的是(conn, 软链)` **永远通过**(两边 realpath 本来就相等)—— "
               "所以 `用副本` 里拦软链那个坑必须用 `确认是另一份`,不是它")

        # ⑥ 反向:期望内存库而实际是文件
        with closing(sqlite3.connect(甲)) as c:
            ck("⑥", 抛吗(lambda: 确认连的是(c, ":memory:")) is not None,
               "**反向**:以为是内存库、实际是文件 → 抛")

        # ⑦ 反向:连接没有 main 库(pragma 返空)也要抛,不许崩在 IndexError 上
        class _空:
            def execute(self, _):
                return []
        ck("⑦", 抛吗(lambda: 实际连的是(_空())) is not None,
           "**反向**:pragma 一行都没返 → 抛连错库(不是崩在别的异常上)")

        # ── 下面造一个假写口模块,复刻那次翻车的形状 ──
        根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        m = types.ModuleType("_假写口")
        m.__file__ = os.path.join(根, "_假写口.py")
        m.DB = 甲

        def 记一笔(db=甲, 说=None):          # ← 默认值在 def 这一刻就烤死了
            return db

        def 另一个(路=乙):                   # ← 指着别的库,不许动它
            return 路

        def 同名的(db=同名):                 # ← 同名不同目录,也不许动它
            return db

        def 关键字的(*, db=甲):
            return db

        class 一个类:
            @staticmethod
            def 静的(db=甲):
                return db

            @classmethod
            def 类的(cls, db=甲):
                return db

            def 普通的(self, db=甲):
                return db

        m.记一笔, m.另一个, m.关键字的, m.一个类 = 记一笔, 另一个, 关键字的, 一个类
        m.同名的 = 同名的
        sys.modules["_假写口"] = m
        try:
            ck("⑧", m in list(_本项目的模块()),
               "假写口被认成「本项目的模块」(认不出来下面全是空集合上的真空判定)")

            旧真 = check_copy.真库
            try:
                check_copy.真库 = os.path.join(目, "完全不相干的树", "lanxiu.db")
                ck("⑧b", m in list(_本项目的模块()),
                   "**反向** · 「本项目」的根从**本文件**算,不从 `真库` 算 —— "
                   "把 `真库` 指到别的树上,假写口照样认得出。"
                   "(真库是条软链、指向主检出:拿它算根会扫出 0 个模块,"
                   "而那时「切干净了」那条断言**自动成立**)")
            finally:
                check_copy.真库 = 旧真

            # ⑨⑩ 试纸:只换模块变量,那个烤死的默认参数纹丝不动
            改变量 = 换模块变量(甲, 乙)
            变量们, 默认们 = 还指着真库的(甲)
            ck("⑨", 改变量 >= 1 and not 变量们,
               f"换模块变量:改得动({改变量} 处),改完模块变量里一处不剩")
            ck("⑩", any("记一笔" in x for x in 默认们),
               "**试纸** · 只换模块变量时,`记一笔(db=…)` 那个烤死的默认参数**仍指着老库** —— "
               "这正是丢 55 条评价的那个形状,而扫模块变量的那把扫帚看不见它",
               f"当时还指着老库的:{默认们}")

            # ⑪ 补上的那一支:默认参数也换得动,换完两张清单都空
            改默认 = 换默认参数(甲, 乙)
            变量们2, 默认们2 = 还指着真库的(甲)
            ck("⑪", 改默认 >= 5 and not 变量们2 and not 默认们2,
               f"换函数默认参数:顶层 / 关键字 / static / class / 普通方法都换到了"
               f"({改默认} 处),换完两类都不剩",
               f"改了 {改默认} 处;仍指着老库:变量 {变量们2} 默认 {默认们2}")

            # ⑫ 反向:指着别的库的默认参数不许被顺手改掉
            ck("⑫", m.另一个() == 乙,
               "**反向**:默认参数指着**别的**库 → 不许动它(不是无脑全替)")

            ck("⑫b", m.同名的() == 同名,
               "**反向** · 同名不同目录是**两份**库(副本也叫 lanxiu.db,和真库同名)—— "
               "判据比的是整条解开的路径,不是 basename",
               f"拿到的是 {m.同名的()}")

            # ⑬ 换完之后真调那个函数,拿到的是新库
            ck("⑬", m.记一笔() == 乙 and m.一个类.静的() == 乙 and m.一个类.类的() == 乙,
               "换完真调一遍:拿到的是新库,不是 def 时捏住的那个")
        finally:
            sys.modules.pop("_假写口", None)

        # ⑭ 真路径:真库不在就明说不适用 —— **不是通过**
        if not os.path.exists(真库):
            没验.append("⑭ 真 `用副本()`(这台机器上没有那个库)")
            print(f"  {Y}⏸{D} ⑭ 这台机器上没有 {os.path.relpath(真库, 根)}"
                  f"(新克隆跑 seed.py 之前都这样)—— 真 `用副本()` 这一条"
                  f"**没东西可验,不是验过了**")
        else:
            # ⚠️ 先 import 那四个**真有**烤死默认参数的写口 —— 不 import 的话
            #    这条只在两三个模块上跑,是空集合上的真空判定(实测补这一支之前
            #    它们 22 个函数的默认参数都还指着真库,其中两个叫 `记一笔`)。
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import credit, ownership, roster, touchpoint  # noqa: F401
            前变量, 前默认 = 还指着真库的()
            ck("⑭a", len(前默认) >= 20,
               f"切之前:四个真写口里有 {len(前默认)} 个函数的默认参数指着真库 "
               f"(样本量 —— 为 0 就说明这条在空集合上跑)",
               f"只扫到 {len(前默认)} 个:{前默认[:6]}")
            副 = 用副本("cc-self-真-")
            变量们3, 默认们3 = 还指着真库的()
            with closing(sqlite3.connect(副)) as c:
                落在副本上 = 实际连的是(c) == os.path.realpath(副)
            ck("⑭", 落在副本上 and not 变量们3 and not 默认们3,
               "真 `用副本()`:拷出来的是一份真库(不是指回真库的链),而且两类都切干净了",
               f"仍指着真库:变量 {变量们3[:4]} 默认 {默认们3[:4]}")
    finally:
        shutil.rmtree(目, ignore_errors=True)

    # ⚠️ 「几条没验」要印在**汇总行里**,不能只印在上面那条 ⏸ 上 ——
    #    门禁对每条检查只留 tail -3,那一行会被截掉,于是「15 条过」
    #    会被读成「全验过了」。今天刚吃过这个(写口冒烟那条提示躺了两个月)。
    print(f"\n  {'❌' if 挂 else '✅'} 库副本自测 {过} 条过"
          + (f",{len(挂)} 条没过:{挂[:4]}" if 挂 else "")
          + (f";⏸ **{len(没验)} 条没东西可验,不是验过了**:{'、'.join(没验)}"
             if 没验 else ""))
    return 1 if 挂 else 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
# ⚠️ 「预期红」写的是**源码里真有的那句话**,不带圈号 —— 圈号和文案是 `ck()` 的
#    两个不同参数,拼起来的串在源码里不存在,咬合对账会报「记录本身不对」。
# 2026-11-04 实测过三关:① 对照先绿(退出码 0、红 0 条)② 改坏后红
# ③ **红的正是点名那一条**。可重放规格在 tools/bite_specs.json。
# ⚠️ 破坏点一律打在**那一支逻辑**上,不打在判据引用的字符串上 ——
#    打字符串的话判据跟着一起变,两边永远对得上,咬合静默失效。
咬合 = [
    # ⚠️ 必须是**二元组** —— `tools/bite_check.py` 只认两个元素的,
    #    多一个元素它会一声不响丢掉(2026-11-04 当场撞到并把那个窟窿堵了)。
    #    「连带红」因此写在行尾注释里:它不是毛病(一处真坏了本来就会牵动几条),
    #    记下来是为了下次重放时分得清「多红了一条」和「红错了」。
    ("把 `换默认参数` 里换位置参数默认值那一支关掉(`if ds:` → `if False and ds:`)—— "
     "模块变量照旧换得动,`用副本()` 看起来一切正常",
     "换函数默认参数:顶层 / 关键字"),   # 连带红 ⑬
    ("把 `_是这个库` 改成比 basename（于是「副本也叫 lanxiu.db」就被当成真库）",
     "同名不同目录是**两份**库"),       # 只红这一条
    ("把「本项目的根」改回从 `真库` 算 —— 真库是条软链、指向主检出,"
     "于是这个 worktree 里一个模块都扫不到,而「切干净了」那条断言自动成立",
     "「本项目」的根从**本文件**算"),   # 只红这一条
    ("去掉 `换模块变量` 里的 `realpath(真)`(macOS 上 /var 解成 /private/var,"
     "于是一处都匹配不上,而匹配 0 处时「切干净了」自动成立)",
     "换模块变量:改得动"),             # 连带红 ⑪
]
# ⚠️ 自测 ② 是一根**钉子**不是一条判据:它断言「SQLite 报的是 realpath」——
#    那是环境行为,改这个项目任何一行都不会让它红,所以它**没有咬合**。
#    留着是为了哪天 Python / SQLite 改了行为能当场知道。把它当判据写进咬合记录,
#    就是记一条验不了的东西。

if __name__ == "__main__":
    sys.exit(main())
