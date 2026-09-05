#!/usr/bin/env python3
"""遮蔽检查 —— 两类「同名把同名盖掉」的错,它们都**不报错、不警告**。

## 第一类:局部变量遮蔽模块级函数(server.py)

`do_GET` 里写了一行 `rows=[...]`,Python 就把整个函数里的 `rows` 都当局部变量,
模块级的 `rows()` 查询函数被整段遮蔽。
自己那行能跑,但**后来加的任何路由一用 rows() 就 UnboundLocalError**,
而且表现是**连接重置(HTTP 000)不是 500** —— 页面只是静静地空着,什么都不报。

## 第二类:模块级常量被重复定义(guards.py 等)

给新体检项定义了一个 `HEDGE`,而上面 g2 早就有一个 `HEDGE`(装的是免责词)。
后定义的把前面的覆盖掉,于是 **g2 悄悄换了行为**,开始误伤正确答案。

这一类比第一类更阴:第一类至少会在运行时炸,
**第二类连炸都不炸,只是判断变了** —— 靠人 review 是看不出来的,
因为两处定义可能隔着三百行。
"""
import ast, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
bad = []

# ── 第一类:server.py 的局部变量遮蔽模块级函数 ──────────────────────────
SRC = os.path.join(HERE, "server.py")
tree = ast.parse(open(SRC, encoding="utf-8").read())
mod_funcs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for node in ast.walk(tree):
    if not isinstance(node, ast.FunctionDef): continue
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for t in sub.targets:
                if isinstance(t, ast.Name) and t.id in mod_funcs:
                    bad.append(f"server.py {node.name}() 第 {sub.lineno} 行"
                               f"把模块级函数 `{t.id}` 当局部变量赋值了")

# ── 第二类:模块级常量/函数被重复定义 ──────────────────────────────────
# 只查**大写常量和函数名**:小写变量在模块级被复用(计数器、临时量)是常态,
# 全查会天天误报,而**天天误报的检查等于没有检查**。
WATCH = ["agentsite/guards.py", "agentsite/sdk.py", "backend/api.py",
         "backend/ops.py", "agent/textmatch.py", "agent/eval.py",
         "knowledge/liability.py", "knowledge/growth.py"]
dupes = 0
for rel in WATCH:
    f = os.path.join(ROOT, rel)
    if not os.path.exists(f): continue
    t2 = ast.parse(open(f, encoding="utf-8").read())
    seen = {}
    for n in t2.body:
        names = []
        if isinstance(n, ast.Assign):
            names = [x.id for x in n.targets
                     if isinstance(x, ast.Name) and x.id.isupper() and len(x.id) > 2]
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [n.name]
        for nm in names:
            if nm in seen:
                bad.append(f"{rel} 第 {n.lineno} 行重复定义了 `{nm}`"
                           f"(前一处在第 {seen[nm]} 行)—— **后面的会把前面的盖掉,"
                           f"而用前一个定义的函数会悄悄换行为**")
                dupes += 1
            seen[nm] = n.lineno

print("遮蔽检查 · 局部遮蔽 + 重复定义\n" + "=" * 72)
print(f"  server.py 模块级函数 {len(mod_funcs)} 个 · 另扫 {len(WATCH)} 个文件的重复定义")
if bad:
    for b in bad: print(f"  ❌ {b}")
    print(f"\n❌ {len(bad)} 处 —— 换个名字(加下划线前缀或改成更具体的名字)")
    sys.exit(1)
print("✅ 没有函数名被局部变量遮蔽,也没有模块级常量被重复定义")
