#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同类还有几处 —— **修一处和修一类,差的就是这一问。**

    python3 fakedata/samekind.py 代码 backend/seed.py:3178      # 这一行的写法,别处还有几处
    python3 fakedata/samekind.py 数据 account.pwd_salt --db <库>  # 这一列的角色,别的表还有几处
    python3 fakedata/samekind.py 自测

## 为什么要有这个

2026-09-21 一天里,**同一个形状咬了三次**:

| 时候 | 找到的那一处 | 同类还有 |
|---|---|---|
| 修商品颜色 | 颜色按 `hash(款号)` 取 | **2 处**(供应商编码、面料库存)—— 当时没问,安静留了一天 |
| 补密码盐豁免 | `account.pwd_salt` 每次重建都变 | **1 处**(`staff.pwd_salt`)—— 第二次比对才冒出来 |
| 提稳定哈希 | 它只是 `run()` 里的局部闭包 `_色hue` | 别人看不见它,于是各写各的 |

三次都不是「没发现 bug」,是**发现了 bug、修掉了、而没有问「这个形状在别处还有几个」**。

> 一个 bug 修好了和一类 bug 修好了,**在检查的输出上长得一模一样** ——
> 都是绿的。区别要等到下一次它从另一处冒出来才看得见。

## 两条轴,以及**它看不见的那一类**

  **代码轴**  这一行调的是哪个东西,全仓还有谁在调。
              用语法树,不用 grep —— grep 会把注释、文档字符串、
              还有「不许用 hash()」这句话本身一起算进去
              (`determinism_check` 当初就是被自己的注释骗过)。

  **数据轴**  这一列在别的表里还有没有。`account.pwd_salt` 的同类是
              `staff.pwd_salt` —— **它根本不在代码里**,grep 够不着。

  ⚠️ **它看不见第三类**:「本该共享的东西被写成了私有的」。
  `_色hue` 那次就是 —— 稳定哈希写成 `run()` 里的局部闭包,
  别的地方想用也看不见它,于是各写各的。
  这一类没有可扫的特征(一个私有函数和一个该私有的函数长得一样),
  **只能靠人看**。写在这儿是为了让人知道这个工具的边界在哪 ——
  一个不说清自己看不见什么的工具,会让人以为扫过了就没有了。
"""
import argparse, ast, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

咬合 = [
    ("把代码轴改成按文本找(不走语法树)", "注释和字符串里的不算"),
    ("把数据轴的同名列查询限定成只看本表", "同名列在别的表里也找得出来"),
]

跳过目录 = {".git", "__pycache__", ".venv", "node_modules", ".fakedata", "static"}


def 仓里的py(根=None):
    出 = []
    for d, ds, fs in os.walk(根 or ROOT):
        ds[:] = [x for x in ds if x not in 跳过目录 and not x.startswith(".")]
        for f in fs:
            if f.endswith(".py"):
                出.append(os.path.join(d, f))
    return sorted(出)


# ── 代码轴 ──────────────────────────────────────────────────────────
def _点名(node):
    """把被调用的东西写成一个点号串:`hash` / `datetime.date.today` / `r.randint`。

    只认名字和属性链 —— `f()()` 这种返回值再调用的,认不出来就明说认不出来,
    不硬猜一个。**猜出来的种类会让人去看一堆不相干的地方。**
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        前 = _点名(node.value)
        return f"{前}.{node.attr}" if 前 else None
    return None


def 这一行是什么(路径, 行号):
    """返回 (种类描述, 说明)。认不出来返回 (None, 为什么)。"""
    try:
        树 = ast.parse(open(路径, encoding="utf-8").read())
    except (OSError, SyntaxError) as e:
        return None, f"读不了或语法不对:{e}"
    命中 = []
    for n in ast.walk(树):
        if isinstance(n, ast.Call) and n.lineno == 行号:
            名 = _点名(n.func)
            if 名:
                命中.append(名)
    if not 命中:
        return None, (f"{os.path.relpath(路径, ROOT)}:{行号} 这一行没有函数调用 —— "
                      f"代码轴只认「调了什么」。别的写法(比如一个赋值、一个下标)"
                      f"**它看不出种类**,别拿它当扫过了")
    # 一行里有几个调用时,取最里层那个(最具体的)
    return 命中[-1], f"这一行调的是 `{命中[-1]}()`"


def 代码里的同类(种类, 文件们):
    """全仓还有谁在调它。**走语法树,不看注释和字符串。**"""
    出 = []
    for p in 文件们:
        try:
            树 = ast.parse(open(p, encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue
        for n in ast.walk(树):
            if isinstance(n, ast.Call) and _点名(n.func) == 种类:
                出.append((os.path.relpath(p, ROOT), n.lineno))
    return sorted(set(出))


# ── 数据轴 ──────────────────────────────────────────────────────────
def 数据里的同类(conn, 列名):
    """哪些表也有这个列名。

    **不做近义匹配**(`pwd_salt` 和 `salt` 不算同类)——
    近义会带来误报,而 `samekey_check` 用两次误报换来一条教训:
    **一个会误报的检查,比没有这个检查更糟**,它会让人去改本来就对的东西。
    """
    出 = []
    for (t,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if any(r[1] == 列名 for r in conn.execute(f"PRAGMA table_info({t})")):
            出.append(t)
    return sorted(出)


# ── 命令 ────────────────────────────────────────────────────────────
def 代码(a):
    if ":" not in a.位置:
        raise SystemExit("用法:samekind.py 代码 <文件>:<行号>")
    f, _, ln = a.位置.rpartition(":")
    路径 = f if os.path.isabs(f) else os.path.join(ROOT, f)
    种类, 说明 = 这一行是什么(路径, int(ln))
    print(f"同类还有几处 · 代码轴\n  看的是:{a.位置}")
    if not 种类:
        print(f"  ⚠️ {说明}")
        return 0
    print(f"  {说明}")
    同 = 代码里的同类(种类, 仓里的py(a.在 and os.path.join(ROOT, a.在)))
    别处 = [x for x in 同 if not (x[0] == os.path.relpath(路径, ROOT) and x[1] == int(ln))]
    print(f"\n  全仓调 `{种类}()` 的共 {len(同)} 处,**除这一处外还有 {len(别处)} 处**:")
    for p, l in 别处[:20]:
        print(f"     {p}:{l}")
    if len(别处) > 20:
        print(f"     …… 还有 {len(别处) - 20} 处")
    if not 别处:
        print("     (没有别处 —— 这一处是独苗)")
    print(f"\n  ℹ️ 走的是语法树:**注释、文档字符串、写在字符串里的同名文本都不算**。")
    print(f"  ⚠️ 它看不见「换个写法做同一件事」的那些 —— "
          f"比如 `getattr(x, 'to'+'day')()`。扫过了不等于没有了。")
    return 0


def 数据(a):
    if "." not in a.位置:
        raise SystemExit("用法:samekind.py 数据 <表>.<列> --db <库>")
    表, _, 列 = a.位置.rpartition(".")
    conn = sqlite3.connect(a.db)
    同 = 数据里的同类(conn, 列)
    别处 = [t for t in 同 if t != 表]
    print(f"同类还有几处 · 数据轴\n  看的是:{表}.{列}")
    print(f"\n  有这个列名的表共 {len(同)} 张,**除这张外还有 {len(别处)} 张**:")
    for t in 别处:
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"     {t}.{列}({n} 行)")
    if not 别处:
        print("     (没有别处)")
    print(f"\n  ℹ️ 只按**列名完全相同**算,不做近义匹配 —— "
          f"近义会误报,而会误报的检查比没有更糟。")
    return 0


def 自测(a):
    """咬合:两条轴各自都要能被改坏一次,而且红的是对应那一条。"""
    import io, contextlib, tempfile, textwrap
    d = tempfile.mkdtemp()
    坏 = []

    # ① 代码轴:注释和字符串里的同名文本**不许算**
    src = textwrap.dedent('''\
        """文档字符串里写着 hash(x) 这个反面教材"""
        # 注释里也写着 hash(x)
        s = "字符串里还有一个 hash(x)"
        def f(k):
            return hash(k) % 7            # ← 第 5 行,真的调用
        def g(k):
            return hash(k) + 1            # ← 第 7 行,另一处真的调用
        ''')
    p = os.path.join(d, "样本.py")
    open(p, "w", encoding="utf-8").write(src)
    种类, _ = 这一行是什么(p, 5)
    if 种类 != "hash":
        坏.append(f"代码轴:第 5 行该认出 hash,实得 {种类!r}")
    同 = 代码里的同类("hash", [p])
    if 同 != [(os.path.relpath(p, ROOT), 5), (os.path.relpath(p, ROOT), 7)]:
        坏.append(f"注释和字符串里的不算:该只找到第 5、7 行,实得 {同}")
    else:
        print("  ✓ 注释和字符串里的不算 —— 4 处同名文本里只认出 2 处真调用")

    # 咬合:按文本找会多出 3 处(文档字符串 / 注释 / 字符串)
    文本命中 = [i + 1 for i, l in enumerate(src.splitlines()) if "hash(" in l]
    if len(文本命中) <= 2:
        坏.append("咬合本身没咬到:这个样本按文本找也只有 2 处,测不出差别")
    else:
        print(f"  ✓ 咬合:同一份代码按文本找会命中 {len(文本命中)} 处"
              f"(多出的 {len(文本命中) - 2} 处是注释 / 文档字符串 / 字符串)")

    # ② 数据轴:同名列在别的表里也找得出来
    db = os.path.join(d, "t.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE account(id TEXT, pwd_salt TEXT)")
    c.execute("CREATE TABLE staff(no TEXT, pwd_salt TEXT)")
    c.execute("CREATE TABLE shop(code TEXT, name TEXT)")
    c.commit()
    同表 = 数据里的同类(c, "pwd_salt")
    if 同表 != ["account", "staff"]:
        坏.append(f"同名列在别的表里也找得出来:该是 [account, staff],实得 {同表}")
    else:
        print("  ✓ 同名列在别的表里也找得出来 —— account 之外还有 staff")
    if "shop" in 同表:
        坏.append("数据轴把没有这一列的表也算进来了")

    # ③ 认不出种类时要**明说**,不许静默返回空
    种类2, 说明2 = 这一行是什么(p, 3)      # 第 3 行是个赋值,没有调用
    if 种类2 is not None or "没有函数调用" not in 说明2:
        坏.append("认不出种类的行该明说「这一行没有函数调用」,不许静默当成 0 处")
    else:
        print("  ✓ 认不出种类时明说 —— 不把「看不出来」报成「没有别处」")

    print("同类还有几处 · 咬合")
    for x in 坏:
        print(f"  ✗ {x}")
    print((f"{R}❌ 同类咬合 {len(坏)} 条不过{D}") if 坏 else f"{G}✅ 同类咬合:两条轴都咬得动{D}")
    return 1 if 坏 else 0


def main():
    p = argparse.ArgumentParser(description="同类还有几处:修一处和修一类,差的就是这一问")
    sub = p.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("代码"); a1.set_defaults(fn=代码)
    a1.add_argument("位置", help="<文件>:<行号>")
    a1.add_argument("--在", help="只扫这个子目录(默认全仓)")
    a2 = sub.add_parser("数据"); a2.set_defaults(fn=数据)
    a2.add_argument("位置", help="<表>.<列>")
    a2.add_argument("--db", required=True)
    a3 = sub.add_parser("自测"); a3.set_defaults(fn=自测)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
