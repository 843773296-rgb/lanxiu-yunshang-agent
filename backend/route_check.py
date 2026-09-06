#!/usr/bin/env python3
"""路由 handler 必须真的存在。

## 为什么补这一条

`backend/server.py` 有四个路由调用了**整个仓库都不存在的函数**:
`/api/customer-create` → create_customer、`/api/appt-create` → create_appointment、
`/api/followup-create` → create_followup、`/api/export/<kind>` → export_csv。

实证:`GET /api/export/customers` → **HTTP 000** —— handler 抛 NameError,
连响应都没发出去,连接直接断。而同一个服务 `/api/shops` 是 200。

**这类洞不在任何已有检查的视野里**:
· `ui_audit` 查的是页面控件有没有绑定,不解析 POST handler 里的名字
· 页面上按钮好好的,后端一调就断
· Python 是运行期解析名字的,**不跑到那一行就不报错**,而这几条路径平时没人走

发现方式是 AST:把 do_POST / do_GET 里被调用的裸函数名,和模块里定义过的名字对一遍。
这个检查就是把那次一次性的排查固化下来。

## 只查裸函数名

`self.xxx()`、`obj.method()` 这些带点的不查 —— 属性要到运行时才知道有没有,
静态判会误报。**宁可少查一类,不要报一堆假的** —— 检查天天红,人就不看了。
"""
import ast, builtins, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = ["backend/server.py", "agentsite/app.py"]

bad = []
for rel in TARGETS:
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path): continue
    tree = ast.parse(open(path, encoding="utf-8").read())
    defined = set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names: defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.arg): defined.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store): defined.add(n.id)
        elif isinstance(n, (ast.ExceptHandler,)) and n.name: defined.add(n.name)
    miss = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id not in defined:
            miss.setdefault(n.func.id, []).append(n.lineno)
    print(f"  {'✅' if not miss else '❌'} {rel}"
          + ("" if not miss else f"  —— {len(miss)} 个函数调了但没定义"))
    for k, v in sorted(miss.items()):
        print(f"        · {k}()  第 {', '.join(map(str, v))} 行")
        bad.append((rel, k, v))

print("=" * 84)
if bad:
    print(f"❌ {len(bad)} 个 handler 不存在 —— 这几条路由一被调用就是 NameError,"
          "**连响应都发不出去,客户端看到的是连接断开**")
    print("   Python 到那一行才解析名字,平时没人走的路径不会报错 —— 所以要静态查。")
    sys.exit(1)
print("✅ 路由调用的函数全部存在(只查裸函数名,带点的属性调用不在范围内)")
