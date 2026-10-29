#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连库必须显式关 —— 常驻服务不许漏文件描述符。

## 这条判据是补票买的(2026-10-29)

用户撞到的现象:**页面打得开,登录进不去**,浏览器里是「框架有、数据没有」。
一路查下来**和数据库有没有起没关系**(PG 带 KeepAlive,一直在跑):
API 服务自己把文件描述符用光了 ——

    OSError: [Errno 24] Too many open files: backend/web/index.html

那一刻它开着 **250 个没关的 `lanxiu.db` 句柄**,而 launchd 给的 `maxfiles` 是 **256**
(plist 没覆盖)。顶满之后**每个请求都挂**,门禁的页面冒烟同时报
「用演示账号(店长)登录失败:HTTP 502」。

## 为什么会漏:那个写法**看起来**就是「用完自动关」

连库那一步原来 139 处都写成「`with` + 连库 + `as c`」。
这是 Python 里最像「自动关闭」的写法,**而 sqlite3 连接的上下文管理器只管
事务提交 / 回滚,不关连接** —— 实测:出了 `with` 块,句柄还开着 1 个,
只有显式 `close()` 才降到 0。

> 一个「用完就关了」和一个「只是提交了事务、连接还开着」,
> **在那行代码上长得一模一样。**

而它为什么能活这么久:**一次性脚本漏了看不出来**(进程退出,内核全还),
只有常驻服务会攒。于是「本地跑一百遍都对」和「线上第 250 个请求起全挂」
是同一份代码。

要求:连库那一步必须被 `closing(...)` 包着,并保留原来的事务语义 ——

    with closing(连库(DB)) as c, c:      # closing 负责关,`, c` 负责提交

## 为什么按 AST 查,不按文本行查

第一版按文本行扫,**当场栽了一次**(2026-10-29,同一天):
`agent/triage_shadow.py` 里有一段三引号字符串,装的是影子跑**子进程脚本**的模板。
批量替换把字符串里那一行也改成了 `closing(...)`,而 `closing` 没进那份子进程的
import —— 子进程一跑就 `NameError`。

> 一个「改对了的代码」和一个「改到字符串里去了的代码」,
> **在 `git diff` 上长得一模一样** —— 两边都是一行变一行。

逮到它的是**别人三周前登记的一条咬合规格**(它的破坏点正好指着那一行,
`bite_check` 当场报「破坏点过期了」)。所以:

· 判据改成走 `ast`,只看真正的 `with` 语句节点 —— **字符串常量天然不在视野里**;
· 子进程模板里那种写法**照旧允许**:那段代码跑完就退出,句柄全还,
  而让这条判据去管一段不是本文件在执行的代码,只会逼人把它改坏。

## 这条判据**不**验什么(说清楚比假装覆盖好)

· 不验 `c = 连库(...)` 这种裸赋值 —— 那要靠 `try/finally`,静态判不准;
· 不验运行中的进程开着多少句柄 —— 那要 `lsof -p <pid>`,不是扫源码扫得出来的。
"""
import ast
import glob
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

G, R, D = "\033[32m", "\033[31m", "\033[0m"

# 连库那个调用长什么样 —— 拆成模块名 + 函数名两段,**不写成完整的匹配串**
# (这个文件自己会被扫,写全了它就命中自己;`backend/staff_cred_check.py`
#  的注释里栽过一次,被它自己逮住。)
_模块, _函数 = "sqlite3", "connect"
_包 = "closing"

扫哪些 = ("backend/*.py", "agentsite/*.py", "knowledge/*.py", "tools/*.py", "agent/*.py")


def 是连库(n):
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == _函数 and isinstance(n.func.value, ast.Name)
            and n.func.value.id == _模块)


def 是包好的(n):
    """`closing(连库(...))` —— 包一层才算关。"""
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == _包 and len(n.args) == 1 and 是连库(n.args[0]))


def main():
    文件们 = []
    for p in 扫哪些:
        文件们 += sorted(glob.glob(os.path.join(ROOT, p)))

    漏的, 连库处数, 包好处数, 扫过, 解析不了 = [], 0, 0, 0, []
    for f in 文件们:
        try:
            树 = ast.parse(io.open(f, encoding="utf-8").read())
        except (OSError, SyntaxError) as e:
            解析不了.append(f"{os.path.relpath(f, ROOT)}:{type(e).__name__}")
            continue
        扫过 += 1
        for n in ast.walk(树):
            if 是连库(n):
                连库处数 += 1
            if not isinstance(n, ast.With):
                continue
            for it in n.items:
                e = it.context_expr
                if 是包好的(e):
                    包好处数 += 1
                elif 是连库(e):
                    漏的.append((os.path.relpath(f, ROOT), n.lineno))

    print(f"\n  连库必须显式关 · 扫了 {扫过} 个源文件,"
          f"找到 {连库处数} 处连库(其中 {包好处数} 处在 with 里包好了)")
    # ⚠️ 解析不了的要报出来 —— 「跳过了」和「扫过并且干净」在那个 ✅ 上长得一模一样
    if 解析不了:
        print(f"  {R}⚠️{D} 有 {len(解析不了)} 个文件没解析成,**没扫到**:{解析不了[:5]}")

    坏 = []

    # ① 反向:一处都没扫到 = 判据坏了,不是「全都对」
    if 连库处数 == 0:
        print(f"  {R}❌{D} 判据自检:一处连库都没扫到 —— "
              f"**这是判据坏了,不是「全都对」**(匹配的名字漂了 / AST 形状变了)")
        坏.append("判据自检")
    else:
        print(f"  {G}✅{D} 判据自检:扫到了 {连库处数} 处连库,"
              f"所以「0 处漏」这个结论是有分母的")

    # ② 正向:with 里的连库,一处都不许不包
    if 漏的:
        print(f"  {R}❌{D} with 里的连库都被 {_包}(...) 包着 —— 有 {len(漏的)} 处没包:")
        for f, ln in 漏的[:12]:
            print(f"        · {f}:{ln}")
        if len(漏的) > 12:
            print(f"        …… 还有 {len(漏的) - 12} 处(这儿只印了 12 处)")
        print(f"        改法:`with {_包}(连库(X)) as c, c:` —— "
              f"前者负责关,后面那个 `, c` 保留原来的事务语义")
        坏.append("有没包的")
    else:
        print(f"  {G}✅{D} with 里的连库都被 {_包}(...) 包着({包好处数} 处逐个看过)")

    if 坏:
        print(f"\n{R}❌ 连库没显式关 —— 常驻服务会攒文件描述符,"
              f"攒满 launchd 那 256 个之后**每个请求都挂**{D}")
        print(f"   而那时的表现是「页面打得开、登录 502」,"
              f"**看起来像数据库没起** —— 2026-10-29 查了一轮才定位到这里")
        return 1
    print(f"\n{G}✅ with 里的连库都会关(扫了 {扫过} 个源文件 / {连库处数} 处连库){D}")
    print(f"   ⚠️ 它**不验**裸赋值的连接(要靠 try/finally),"
          f"也**不验**运行中的进程开着多少句柄(那要 lsof -p)")
    return 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」;可重放的规格在 tools/bite_specs.json。
咬合 = [
    ("把 backend/api.py 里某一处 closing(...) 去掉(回到那个只提交、不关连接的写法)",
     "with 里的连库都被"),
    ("把要匹配的函数名改掉(于是一处连库都扫不到,而输出会变成「全都对」)",
     "判据自检:一处连库都没扫到"),
]

if __name__ == "__main__":
    sys.exit(main())
