#!/usr/bin/env python3
"""业务后台的请求处理函数里,局部变量不许和模块级名字同名(2026-11-11 夜,我把线上后台弄挂了约 10 分钟)。

那次:在 do_GET 里加排班接口,写了一句 `_u = _me(self)`。而 do_GET 第一行是 `p=_u(unquote(...))` ——
`_u` 是模块级的路径解析函数。Python 只要看见函数里**任何地方**给 `_u` 赋值,就把整个函数里的 `_u`
都当成局部变量,于是第一行就 UnboundLocalError —— **每一个 GET 请求都挂**,包括首页。
语法检查过、import 过、我的排班检查 33 条全绿 —— 它们都不发请求。

> 一个「加了一个新接口」的改动,和一个「让所有接口都挂掉」的改动,在 py_compile 上长得一模一样。

判据落结构(symtable),不枚举名字:H 类的每个方法里,**被赋值的局部名**如果同时是**模块级名字**
就红 —— 不管它此刻有没有在赋值之前被用到(今天没用到,明天有人在上面加一行就用到了)。
"""
import os
import sys
import symtable

HERE = os.path.dirname(os.path.abspath(__file__))
G, R, D = "\033[32m", "\033[31m", "\033[0m"


def 撞名(源码, 文件名="server.py", 类名="H"):
    """→ [(方法, 名字)]:类里方法的局部变量和模块级名字同名的。"""
    top = symtable.symtable(源码, 文件名, "exec")
    模块级 = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()}
    出 = []
    for t in top.get_children():
        if t.get_type() != "class" or t.get_name() != 类名:
            continue
        for m in t.get_children():
            for s in m.get_symbols():
                if s.is_local() and s.is_assigned() and not s.is_parameter() and s.get_name() in 模块级:
                    出.append((m.get_name(), s.get_name()))
    return 出


def 自测():
    坏 = []
    样 = "def _u(x): return x\nclass H:\n    def do_GET(self):\n        p = _u(1)\n        if p:\n            _u = 2\n"
    if 撞名(样) != [("do_GET", "_u")]:
        坏.append(f"试纸(11-11 夜那次的形状)没认出来:{撞名(样)}")
    好 = "def _u(x): return x\nclass H:\n    def do_GET(self):\n        p = _u(1)\n        _排班人 = 2\n"
    if 撞名(好):
        坏.append(f"改名之后还报:{撞名(好)}")
    return 坏


# ── 咬合记录 ──────────────────────────────────────────────────────
咬合 = [
    ("在 do_GET 里把局部变量起名成 `_u`(和路径解析函数同名)", "请求处理函数里没有局部变量和模块级名字同名"),
]


def main():
    print("业务后台请求处理函数 · 局部变量不许和模块级名字同名\n" + "=" * 84)
    坏 = 自测()
    for b in 坏:
        print(f"  ❌ 自测:{b}")
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    撞 = 撞名(src)
    方法数 = 0
    for t in symtable.symtable(src, "server.py", "exec").get_children():
        if t.get_type() == "class" and t.get_name() == "H":
            方法数 = len(t.get_children())
    if 方法数 == 0:
        print(f"  ❌ 没找到 H 类的方法 —— **这不叫通过,这叫没验到**(类改名了?)")
        坏.append("没验到")
    ok = not 撞
    print(f"  {'✅' if ok else '❌'} 请求处理函数里没有局部变量和模块级名字同名(验了 H 类 {方法数} 个方法)"
          + ("" if ok else f"   ← {撞}:同名的话 Python 把整个函数里的它当局部变量,赋值之前那几行就 UnboundLocalError"))
    if not ok:
        坏.append("撞名")
    print("=" * 84)
    if 坏:
        print(f"{R}❌ 后台请求处理函数 {len(坏)} 处不符合预期{D}")
        return 1
    print(f"{G}✅ 后台请求处理函数没有撞名{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
