#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""角色工具名单必须是**字面量** —— 拼出来的名单,模型拿得到而判据看不见。

来路:`agentsite/sdk.py` 第 480 行那条注释(「**写在名单字面量里**,别写进 `_ROLE_TOOLS`
的 lambda:规矩检查从源码读字面量」)—— 它是**约定**,而这个项目为「把声明当成了生效」
栽过很多次,所以给它配一道结构检查。

## 这一条守的是什么

挂给模型的工具名单(`KB_TOOLS` / `SHOP_TOOLS` / …)被好几道判据**从源码读字面量**:
提示词检查 P3/P6(挂了某个工具就必须拿到管它的那条规矩)、工具收窄、边界审计。
只要有人这样加一个工具:

    SHOP_TOOLS += ["某个新工具"]        # ← 模型拿得到
                                        # ← 而读 `SHOP_TOOLS = [...]` 的判据看不见

那么:**工具给了、管它的规矩没给**。而「规矩没给」比「工具没给」更危险 ——
模型会去用它,并且没有任何一句话告诉它怎么算用错。

> **一个判据看不见的工具,和一个不存在的工具,在那道判据的绿勾上长得一模一样。**

这正是 2026 年那次咬合失效的第一型:攻击改的是 `SHOP_TOOLS += [...]`,
而检查用正则读 `SHOP_TOOLS = [...]`,**改动它根本看不见,于是「没红」被当成了「守得住」**。

## 查四件事

  ① 名单的赋值是**字面量**(list / tuple / set,元素全是字符串常量)
  ② 全文件没有对它的 `+=`(增广赋值)
  ③ 全文件没有 `.append` / `.extend` / `.insert` / `.update` 这类**改掉它**的调用
  ④ `_ROLE_TOOLS` 的 lambda 体只许由这些名单用 `+` 拼(外加 `sorted` / `set`)——
     一旦它改成调用别的函数,下面「要查哪些名单」就提取不出来了

⚠️ **要查哪些名单是从 `_ROLE_TOOLS` 自动提取的**(新加一个角色会自动纳入,覆盖面不会漏),
而提取**失效时会得到空集合,空集合上四条性质全成立** —— 所以另配一份明写的最小清单做棘轮:
提取出来的必须**覆盖**它,少一个就红。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ── 咬合记录(规格在 `tools/bite_specs.json`,`--only role_tools_literal_check` 可重放)──
# **没红过的检查等于没有。**
咬合 = [
    # 第一条就是这次事故的**原形**:检查读 `X = [...]`,而改动写成 `X += [...]`。
    ("用 `+=` 往 TAKEOVER_TOOLS 里加一个工具(名单的字面量一个字没变)",
     "没有人用 `+=` 往名单里加工具"),
    # 第二条故意选一个**语义完全不变**的改法 —— 它证明这条判据守的是
    # 「判据读不读得到」,不是「名单对不对」。
    ("把名单从字面量改成 `list([...])` 算出来(运行时一模一样)",
     "每个名单都是字面量,元素全是字符串常量"),
    # 第三条打提取本身:提取不出来的时候,**空集合上另外三条性质全部成立**,
    # 输出会是一片绿 —— 所以明写的最小清单那条棘轮必须顶着。
    ("把某个角色的工具改成调一个函数算出来(这个角色挂了什么就提取不出来了)",
     "`_ROLE_TOOLS` 的每个角色只拿名单用 `+` 拼"),
]

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
坏, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else Rd + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        坏.append(名)


# ⚠️ **明写的最小清单 —— 棘轮,只许多不许少。**
# 它不是「要查的全部」(全部是从 `_ROLE_TOOLS` 自动提取的),而是「至少得查到这些」。
# 少了它,提取一旦失效就会得到空集合,而**空集合上所有性质都成立** ——
# 那时输出是一片绿,和真的守住了长得一模一样。
# 顺带:`bite_check` 在源码里找预期红的前几个字,这份字面清单也让它找得到。
至少要查到 = ["KB_TOOLS", "SHOP_TOOLS", "TASK_TOOLS", "WORKSHOP_TOOLS",
            "FINANCE_TOOLS", "PATTERN_TOOLS", "AFTERSALE_TOOLS", "TAKEOVER_TOOLS"]
改掉它的方法 = ("append", "extend", "insert", "update", "add", "remove", "pop", "clear")
lambda里允许的函数 = ("sorted", "set", "list", "tuple")

print(f"\n  角色工具名单 · 必须是字面量")
print("  " + "=" * 80)

SDK = os.path.join(ROOT, "agentsite", "sdk.py")
树 = ast.parse(open(SDK, encoding="utf-8").read())

# ── ④ 先看 `_ROLE_TOOLS` 本身:提取得出来,才有下面三条可查 ──────────────
角色表 = next((nd.value for nd in ast.walk(树)
              if isinstance(nd, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "_ROLE_TOOLS" for t in nd.targets)), None)
ck("`_ROLE_TOOLS` 是一个字典字面量(提取不出来,下面三条就什么都没查)",
   isinstance(角色表, ast.Dict),
   "它不是字典字面量了 —— **这一条红是好事**:提取失效会让下面三条在空集合上全部变绿")

名单们, 坏lambda = set(), []
if isinstance(角色表, ast.Dict):
    for 键, 值 in zip(角色表.keys, 角色表.values):
        角色 = 键.value if isinstance(键, ast.Constant) else "?"
        if not isinstance(值, ast.Lambda):
            坏lambda.append(f"{角色}(不是 lambda)")
            continue
        for sub in ast.walk(值.body):
            if isinstance(sub, ast.Name):
                名单们.add(sub.id)
            elif isinstance(sub, ast.Call):
                f = sub.func
                if not (isinstance(f, ast.Name) and f.id in lambda里允许的函数):
                    叫 = getattr(f, "id", None) or getattr(f, "attr", "?")
                    坏lambda.append(f"{角色} 调了 {叫}()")
            elif isinstance(sub, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                坏lambda.append(f"{角色} 用了推导式")
    名单们 -= set(lambda里允许的函数)

ck(f"`_ROLE_TOOLS` 的每个角色只拿名单用 `+` 拼(允许 {'/'.join(lambda里允许的函数)})",
   not 坏lambda,
   f"这几处不是:{坏lambda} —— 一旦改成调别的函数算出来,"
   f"**判据就读不到挂了哪些工具了**,而模型照样拿得到")

缺 = [x for x in 至少要查到 if x not in 名单们]
ck(f"自动提取到的名单覆盖明写的最小清单(提取到 {len(名单们)} 个)",
   not 缺,
   f"这几个没提取到:{缺} —— **提取失效了**(或者名单改了名)。"
   f"空集合上下面三条会全部变绿,和真的守住了长得一模一样")

# ── ①②③ 逐个名单查 ───────────────────────────────────────────────────
要查 = sorted(名单们 | set(至少要查到))
赋值 = {}
增广, 改掉 = [], []
for nd in ast.walk(树):
    if isinstance(nd, ast.Assign):
        for t in nd.targets:
            if isinstance(t, ast.Name) and t.id in 要查:
                赋值.setdefault(t.id, []).append(nd.value)
    elif isinstance(nd, ast.AugAssign):
        if isinstance(nd.target, ast.Name) and nd.target.id in 要查:
            增广.append(f"{nd.target.id} 第 {nd.lineno} 行")
    elif isinstance(nd, ast.Call) and isinstance(nd.func, ast.Attribute):
        v = nd.func.value
        if isinstance(v, ast.Name) and v.id in 要查 and nd.func.attr in 改掉它的方法:
            改掉.append(f"{v.id}.{nd.func.attr}() 第 {nd.lineno} 行")

没定义 = [x for x in 要查 if x not in 赋值]
ck(f"每个名单都在 sdk.py 里定义过(查了 {len(要查)} 个)", not 没定义,
   f"这几个找不到定义:{没定义} —— 可能挪到别的文件了,那这道检查就扫不到它")

不是字面量 = []
for 名, 值们 in sorted(赋值.items()):
    for v in 值们:
        if not isinstance(v, (ast.List, ast.Tuple, ast.Set)):
            不是字面量.append(f"{名}(第 {getattr(v, 'lineno', '?')} 行是 {type(v).__name__})")
        elif not all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in v.elts):
            不是字面量.append(f"{名}(第 {getattr(v, 'lineno', '?')} 行里有不是字符串常量的元素)")
ck(f"每个名单都是字面量,元素全是字符串常量(查了 {len(赋值)} 个)",
   not 不是字面量,
   f"这几个不是:{不是字面量} —— **判据从源码读字面量**,算出来的它读不到,"
   f"于是「工具给了、管它的规矩没给」")

ck("没有人用 `+=` 往名单里加工具", not 增广,
   f"{增广} —— 这正是 2026 年那次咬合失效的形状:检查读 `X = [...]`,"
   f"而改动写成 `X += [...]`,**改了它根本看不见**")

ck(f"没有人用 .append / .extend 这类调用改名单", not 改掉,
   f"{改掉} —— 和 `+=` 同一件事:运行时名单变了,而源码里那个字面量没变")

# ── 写工具清单同样不许是算出来的 ───────────────────────────────────────
API = os.path.join(ROOT, "backend", "api.py")
api树 = ast.parse(open(API, encoding="utf-8").read())
w = next((nd.value for nd in ast.walk(api树)
          if isinstance(nd, ast.Assign)
          and any(isinstance(t, ast.Name) and t.id == "WRITE_TOOLS" for t in nd.targets)), None)
ck("`api.WRITE_TOOLS` 也是字面量(它是那 29 个写口的唯一登记处)",
   isinstance(w, (ast.List, ast.Tuple, ast.Set))
   and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in (w.elts if w else [1])),
   f"它现在是 {type(w).__name__ if w else '(找不到)'} —— 写工具清单算出来的话,"
   f"隔离检查和边界审计都读不到新加的那个写口")
w增广 = [f"第 {nd.lineno} 行" for nd in ast.walk(api树)
        if isinstance(nd, ast.AugAssign) and isinstance(nd.target, ast.Name)
        and nd.target.id == "WRITE_TOOLS"]
ck("没有人用 `+=` 往 `WRITE_TOOLS` 里加写口", not w增广, f"{w增广}")

print("  " + "=" * 80)
if 坏:
    print(f"  {Rd}❌ {len(坏)} 条没过:{坏}{D}")
    sys.exit(1)
print(f"  {G}✅ 角色工具名单都是字面量,没人绕开判据的视野(验了 {n} 条,"
      f"覆盖 {len(要查)} 个名单){D}")
sys.exit(0)
