#!/usr/bin/env python3
"""**拆开的 api 还是一个 api** —— 守 2026-11-16 那次拆分(门面 api.py + 子模块)留下的三条约定。

为什么要守:拆完之后这几种错**都不报错、照样能跑**,坏的是别的检查:
  ① 子模块里直接写 `DB` / `_rows(` / `whoami()`(没走 `api.`)—— 运行完全正常,
     但检查里 `api.DB = 副本`、`api.whoami = lambda…` **打不到这一处**:那个检查会在真库上跑,或者判据静默失效。
     > 一处「走 api.」的调用和一处「直接用」的调用,**在功能上长得一模一样**,只在被替换的那一刻分岔。
  ② 新加了 `backend/api_xxx.py` 却没登记进门面的 `子模块们` —— `api_src.全部源码()` 读不到它,
     按文本扫 api 源码的十几个检查对它**扫了个空、判成没问题**。
  ③ 登记了却没在门面 `from api_xxx import *` —— 工具表里那些函数名在加载时就 NameError(这一条会响,但先在这里说清楚)。

    python3 backend/api_split_check.py
"""
import ast
import builtins
import glob
import os
import symtable
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api_src  # noqa: E402

咬合 = [
    ("把子模块里一处 `api.whoami()` 改回 `whoami()`", "子模块里指向门面的名字都走 api.(检查替换 api.X 才打得到)"),
    ("从门面的 `子模块们` 里删掉一个", "backend/api_*.py 都登记在门面的 子模块们 里(api_src 才读得到)"),
]

坏 = []


def ck(名, ok, n, 附=""):
    print(f"  {'✅' if ok else '❌'} {名}(验了 {n} 个){'  ' + 附 if 附 else ''}")
    if not ok:
        坏.append(名)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        坏.append(名 + "(样本量 0)")


def 模块级名字(树):
    名 = set()
    for n in 树.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            名.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            名 |= {(a.asname or a.name).split(".")[0] for a in n.names}
        else:
            for x in ast.walk(n):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                    名.add(x.id)
    return 名


def main():
    登记 = api_src.子模块名()
    实有 = sorted(os.path.basename(f)[:-3] for f in glob.glob(os.path.join(HERE, "api_*.py"))
                if os.path.basename(f) not in ("api_src.py", "api_split_check.py"))
    print(f"api 拆分 · 门面登记 {len(登记)} 个子模块,目录里有 {len(实有)} 个 api_*.py")
    漏登 = sorted(set(实有) - set(登记))
    空登 = sorted(set(登记) - set(实有))
    ck("backend/api_*.py 都登记在门面的 子模块们 里(api_src 才读得到)", not 漏登 and not 空登, len(实有),
       (f"没登记:{漏登}" if 漏登 else "") + (f" 登记了却没有文件:{空登}" if 空登 else ""))

    门面树 = ast.parse(open(api_src.门面, encoding="utf-8").read())
    星号 = {n.module for n in 门面树.body if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)}
    ck("登记的子模块,门面都 from … import * 了", all(m in 星号 for m in 登记), len(登记),
       f"没导:{sorted(set(登记) - 星号)}")

    门面名 = 模块级名字(门面树) - set(登记)
    内置 = set(dir(builtins))
    直接用 = []
    扫过 = 0
    for m in 登记:
        p = os.path.join(HERE, m + ".py")
        if not os.path.exists(p):
            continue
        源 = open(p, encoding="utf-8").read()
        自 = 模块级名字(ast.parse(源))
        扫过 += 1

        def 扫(表):
            for s in 表.get_symbols():
                if not s.is_referenced():
                    continue
                全局 = 表.get_type() == "module" or (s.is_global() and not s.is_local())
                n = s.get_name()
                if 全局 and n in 门面名 and n not in 自 and n not in 内置:
                    直接用.append(f"{m}.{表.get_name()} 里直接用了门面的 {n}")
            for c in 表.get_children():
                扫(c)
        扫(symtable.symtable(源, p, "exec"))
    ck("子模块里指向门面的名字都走 api.(检查替换 api.X 才打得到)", not 直接用, 扫过,
       "；".join(直接用[:4]) + (f" …还有 {len(直接用) - 4} 处" if len(直接用) > 4 else ""))

    if 坏:
        print(f"\n\033[31m❌ api 拆分约定 {len(坏)} 处不符合\033[0m")
        sys.exit(1)
    print("\n\033[32m✅ 拆开的 api 还是一个 api\033[0m")


if __name__ == "__main__":
    main()
