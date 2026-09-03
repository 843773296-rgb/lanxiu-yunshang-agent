#!/usr/bin/env python3
"""遮蔽检查 —— 路由函数里不许出现与模块级函数同名的局部变量。

为什么需要:`do_GET` 里写了一行 `rows=[...]`,Python 就把整个函数里的 `rows`
都当成局部变量,模块级的 `rows()` 查询函数被整段遮蔽。
自己那行能跑,但**后来加的任何路由一用 rows() 就 UnboundLocalError**,
而且表现是**连接重置(HTTP 000)不是 500** —— 页面只是静静地空着,什么都不报。
"""
import ast, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "server.py")
tree = ast.parse(open(SRC, encoding="utf-8").read())
mod_funcs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
bad = []
for node in ast.walk(tree):
    if not isinstance(node, ast.FunctionDef): continue
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for t in sub.targets:
                if isinstance(t, ast.Name) and t.id in mod_funcs:
                    bad.append((node.name, t.id, sub.lineno))
print("遮蔽检查 · server.py\n" + "=" * 62)
print(f"模块级函数 {len(mod_funcs)} 个")
if bad:
    for fn, name, ln in bad:
        print(f"  ❌ {fn}() 第 {ln} 行把模块级函数 `{name}` 当局部变量赋值了")
    print(f"\n❌ {len(bad)} 处遮蔽 —— 换个变量名(加下划线前缀即可)")
    sys.exit(1)
print("✅ 没有函数名被局部变量遮蔽")
