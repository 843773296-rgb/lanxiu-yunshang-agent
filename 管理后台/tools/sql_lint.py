#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""SQL 字符串体检:**注释里的绑定参数**。我自己踩过,而且踩过不止一次。

## 为什么要有这个文件(而不是「记在交接里」)

这个坑已经写在 `HANDOFF.md` 里了。而 2026-09-27 我在**同一条 SQL 语句里
连踩两个** —— 其中一个是在写「防第一个坑」的注释时踩的。

> **「写在交接里」对当下的我不起作用。起作用的是检查。**

交接告诉接手的人「这里有个坑」;检查在有人掉进去的**那一刻**拦住他。
前者需要「正好想起来」,后者不需要。

## 这个坑长什么样

`text()` 里的 `--` 注释**对 SQLAlchemy 不透明** —— 它只做词法扫描,
不解析 SQL 语法。所以注释里一个 `:w`,会变成一个**缺失的绑定参数**,
运行时报 `A value is required for bind parameter`。

坑在症状:错误信息指向那个词,而那个词**在注释里** ——
看起来像「SQLAlchemy 疯了」。

## ⚠️ 判据不自己实现词法,**问 SQLAlchemy**

第一版我自己写了个 `:(\w+)` 的正则,报出 17 处,**其中 15 处是假的**。
真正的规则是 `(?<![:\w\x5c]):(\w+)(?!:)` —— **冒号前面不能是单词字符**:

    那次红是好的:它逼着这个调用点跟着改      ← 冒号前是「的」,不匹配,不是问题
    -- :那份报告不问                        ← 冒号前是空格,匹配,这才是当初炸的形状

我那版漏了前置条件,于是把一堆正常注释报成硬错。

> **一条重新实现别人词法规则的检查,必然会和那个规则漂开。**

所以现在的做法是:把字符串交给 `text()`,**问它认出了哪些参数**,
再看这些参数里哪些落在 `--` 之后。判据从此不会漂 ——
SQLAlchemy 改了规则,这个检查跟着改。

## 中文绑定参数是**合法的**

这个项目用中文命名,`lease.py` 的 `收尾(…, 到, …)` 就对应 SQL 里的 `:到`。
第一版我判「中文绑定名一律非法」—— 那条对这个项目是错的,已删。
"""
import ast
import os
import re
import sys

这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(这)
扫的目录 = ["services/api/app", "workers", "tools"]

try:
    from sqlalchemy import text as _text
except ImportError:
    print("❌ 要 sqlalchemy —— 这个检查**故意**依赖它:"
          "判据是「问 SQLAlchemy 认出了哪些参数」,不是自己写正则")
    sys.exit(1)

硬错, 提醒 = [], []


def _text调用们(路):
    """找出所有 `text("…")` 调用里的那个字符串字面量。

    ⚠️ 只看 `text()` 的参数,不扫所有字符串:
    第一版扫「看起来像 SQL 的字符串」,于是把**模块文档字符串**也算进去了
    (它们里面有 select / update 这些词)。
    """
    try:
        树 = ast.parse(open(路, encoding="utf-8").read(), filename=路)
    except SyntaxError as e:
        硬错.append((路, 0, f"这个文件语法都不对:{e}"))
        return
    for n in ast.walk(树):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        名 = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        if 名 not in ("text",) or not n.args:
            continue
        a = n.args[0]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            yield a.lineno, a.value


def _括号内(s, 开括号位置):
    """返回 `(` 到配平的 `)` 之间那段(不含括号本身)。

    没配平(SQL 被截断、或者括号在字符串字面量里)时返回到结尾 ——
    **偏宽而不是偏窄**:这里多报的代价是有人加了个无用的 cast,
    漏报的代价是一条一走到就炸的 SQL。
    """
    assert s[开括号位置] == "(", f"不是左括号:{s[开括号位置]!r}"
    深 = 0
    for i in range(开括号位置, len(s)):
        if s[i] == "(":
            深 += 1
        elif s[i] == ")":
            深 -= 1
            if 深 == 0:
                return s[开括号位置 + 1:i]
    return s[开括号位置 + 1:]


def 查一个文件(路):
    for 行号, sql in _text调用们(路):
        # **问 SQLAlchemy**:它认出了哪些绑定参数
        try:
            认出的 = set(_text(sql)._bindparams.keys())
        except Exception as e:
            硬错.append((路, 行号, f"这条 SQL 连 text() 都过不了:{type(e).__name__}: {e}"))
            continue
        if not 认出的:
            continue
        # 逐行看:注释里出现的,是不是它认出来的那些
        for i, 行 in enumerate(sql.split("\n")):
            if "--" not in 行:
                continue
            注释 = 行.split("--", 1)[1]
            # 用同一条规则在注释上再问一次 —— 交给 text() 而不是自己写正则
            try:
                注释里的 = set(_text(注释)._bindparams.keys())
            except Exception:
                注释里的 = set()
            撞 = sorted(注释里的 & 认出的)
            if 撞:
                硬错.append((
                    路, 行号 + i,
                    f"SQL 注释里的 {['`:' + x + '`' for x in 撞]} **被当成绑定参数了** —— "
                    f"`text()` 对 `--` 不透明。说明写到 Python 注释里去"))

        # ── 缺 cast 的位置。**硬错,不是提醒** ──────────────────────
        # 第一版列成「可能误报的提醒」,于是 CI 不会因它变红 ——
        # 而它第一次跑就抓到 `lease.py` 里一个**会导致重复计费**的真 bug。
        #
        # 重新算代价方向:
        #   · 误报的代价 = 有人加了一个无用的 `cast(… as text)` ≈ **0**
        #   · 漏报的代价 = 罕见分支里的必炸 → 已完成的任务被重跑 → **重复计费**
        # 两边差几个数量级。**当一侧代价接近零时,「可能误报」不是留作提醒的理由。**
        #
        # ⚠️ 只要求「有 cast」,不管 cast 成什么 —— 参数是 jsonb 的时候
        # 强制 `as text` 会是错的。
        for m in re.finditer(r":([A-Za-z_一-龥][\w一-龥]*)\s+is\s+null", sql, re.I):
            if f"cast(:{m.group(1)}" not in sql:
                硬错.append((路, 行号,
                            f"`:{m.group(1)} is null` —— 只和 NULL 比,没有类型线索,"
                            f"PostgreSQL 会报 could not determine data type。"
                            f"加 `cast(:{m.group(1)} as …)`"))
        # ⚠️ **参数范围靠配平括号定,不靠距离。** 这里连错两版:
        #   ① `jsonb_build_object\s*\(.{0,200}?:(\w+)` —— 非贪婪在**第一个**冒号
        #      就停了,于是 `jsonb_build_object(k, cast(:a as text), :r)` 里
        #      只看到有 cast 的 `:a`,真正缺 cast 的 `:r` **根本没被看**(该报没报)
        #   ② 改成「取之后 200 字符」—— 把 `where project_id=:p and id=:i`
        #      也算进了函数参数(不该报却报了)
        # 两次都是拿**距离**近似**结构**。而「宽到把明显无关的东西也报进来」
        # 比漏报更糟:它会让人开始整体忽略这条检查。
        for m in re.finditer(r"jsonb_build_object\s*\(", sql, re.I):
            段 = _括号内(sql, m.end() - 1)
            for 名 in re.findall(r":([A-Za-z_一-龥][\w一-龥]*)", 段):
                if f"cast(:{名}" not in sql:
                    硬错.append((路, 行号,
                                f"`jsonb_build_object(… :{名} …)` —— 这个函数收 `any`,"
                                f"给不出类型约束,**一走到就炸**。加 `cast(:{名} as …)`"))


def main():
    n = 0
    for d in 扫的目录:
        full = os.path.join(根, d)
        if not os.path.isdir(full):
            continue
        for dp, dn, fn in os.walk(full):
            dn[:] = [x for x in dn if x not in (".venv", "__pycache__", "node_modules")]
            for f in fn:
                if f.endswith(".py"):
                    n += 1
                    查一个文件(os.path.join(dp, f))
    if n == 0:
        print("❌ 一个 .py 都没扫到 —— **这不叫通过,叫没找到文件**")
        return 1

    print(f"▸ SQL 字符串体检:扫了 {n} 个 .py 里的 `text()` 调用")
    if 提醒:
        print(f"  ℹ️ {len(提醒)} 处提醒(**会误报**):")
        for 路, 行, 说 in 提醒[:6]:
            print(f"     {os.path.relpath(路, 根)}:{行}  {说}")
    if 硬错:
        print(f"\n  ❌ {len(硬错)} 处**硬错**(运行时一定炸):")
        for 路, 行, 说 in 硬错:
            print(f"     {os.path.relpath(路, 根)}:{行}  {说}")
        return 1

    # ── 咬合:**这个检查自己要能被证伪** ──────────────────────────
    # 一条从没抓到过东西的检查,和一条恒为真的检查,在输出上一模一样。
    坏 = 'select 1 from t where a = :x\n-- 那份报告不问 :x 的事\n'
    try:
        认 = set(_text(坏)._bindparams.keys())
        注 = set(_text(坏.split("--", 1)[1])._bindparams.keys())
        咬住 = bool(注 & 认)
    except Exception:
        咬住 = False
    # 对照:冒号前面是单词字符的那种**不许报**(第一版在这儿误报了 15 处)
    好 = 'select 1 from t where a = :x\n-- 那次红是好的:它逼着调用点跟着改\n'
    try:
        认2 = set(_text(好)._bindparams.keys())
        注2 = set(_text(好.split("--", 1)[1])._bindparams.keys())
        不误报 = not (注2 & 认2)
    except Exception:
        不误报 = False
    # 咬合 ②:缺 cast 的 jsonb_build_object 要被抓到
    _存 = list(硬错)
    硬错.clear()
    import tempfile
    _d = tempfile.mkdtemp()
    _f = os.path.join(_d, "坏.py")
    open(_f, "w", encoding="utf-8").write(
        "from sqlalchemy import text\n"
        "x = text('update t set d = jsonb_build_object(k, cast(:a as text), :r) where id=:i')\n")
    查一个文件(_f)
    咬住cast = any("jsonb_build_object" in 说 for _, _, 说 in 硬错)
    硬错.clear()
    硬错.extend(_存)
    print(f"  {'✅' if 咬住 else '❌'} 咬合①:注释里 `-- … :x …` 会被抓到")
    print(f"  {'✅' if 咬住cast else '❌'} 咬合②:`jsonb_build_object(… :r)` 缺 cast 会被抓到"
          f"(这一条第一次跑就抓到 lease.py 里一个会导致重复计费的真 bug)")
    if not 咬住cast:
        return 1
    print(f"  {'✅' if 不误报 else '❌'} 对照:`的:它逼着` 这种**不报**"
          f"(冒号前是单词字符,SQLAlchemy 不认它 —— 第一版在这儿误报 15 处)")
    if not (咬住 and 不误报):
        print("  ❌ **这个检查自己不成立** —— 判据要么抓不到,要么会误报")
        return 1
    print("  ✅ 没有「注释里的绑定参数」这类硬错")
    return 0


if __name__ == "__main__":
    sys.exit(main())
