"""**api 的源码** = 门面 `api.py` + 它登记的子模块(`api.子模块们`)。

2026-11-16 拆 api.py(8800 行 → 门面 + 11 个按业务分的子模块)之后,**凡是按文本读 api 源码的地方都走这里**,
不各自拼 `os.path.join(..., "api.py")` —— 拼路径的那种在拆完之后**只读到门面**,
找不到搬走的函数就会报「找不到 store_report」,或者更糟:**扫了个空、判成没问题**。

    import api_src
    api_src.全部源码()     # 门面 + 子模块拼成一份(每份都是合法模块,拼起来照样 ast.parse 得了)
    api_src.文件们()       # [门面路径, 子模块路径…]
    api_src.指纹()         # 所有文件的 (mtime_ns, size) —— 按源码缓存的地方用它当键,改任何一份都失效

子模块清单**从门面源码里读字面量**(不 import api):有的调用方在 import api 之前就要源码,
而 import api 会连库。
"""
import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
门面 = os.path.join(HERE, "api.py")


def 子模块名():
    """门面里 `子模块们 = (...)` 那个字面量。没有就是还没拆(或者被人删了)→ 只有门面一份。"""
    树 = ast.parse(open(门面, encoding="utf-8").read())
    for n in 树.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "子模块们" for t in n.targets):
            return tuple(ast.literal_eval(n.value))
    return ()


def 文件们():
    return [门面] + [os.path.join(HERE, m + ".py") for m in 子模块名()]


def 全部源码():
    return "\n".join(open(f, encoding="utf-8").read() for f in 文件们())


def 指纹():
    return tuple((f, os.stat(f).st_mtime_ns, os.stat(f).st_size) for f in 文件们())
