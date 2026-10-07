#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**JSONB 列写裸串** —— 今天栽了八次的那一族,现在有判据了。

    python3 tools/jsonb_cast_check.py

## 为什么单独一条

`tools/sql_columns_check.py` 写的时候我自己记了一条已知盲区:
**「只查列名存不存在,不查类型对不对」**。而 2026-09-28~29 两天里,
这个盲区一共放过去 **8 次**同一个错:

    spans.error / feedback.note(反过来)/ evaluations.candidate_ref /
    execution_runs.release_ref / tool_versions.idempotency_strategy /
    policy_versions.failure_strategy …

每一次的表现都一样:`invalid input syntax for type json`,
**而且只在走到那一条 INSERT 的那条路径上炸** —— 别的路径全绿。
数据集那一组八条接口里只有一条 500、模型连接三条里只有一条 500,都是这个。

> **一个我写下来的盲区,不会因为写下来就变浅。**
> 写下来只让它和「忘了」分得开;要它变浅,得有判据。

## ⚠️ 判据第一版是错的,值得写下来

第一版判的是「**jsonb 列的绑定处有没有 `cast(... as jsonb)`**」——
跑出来报了 **9 处正在正常工作的代码**。

真因:**Postgres 能从目标列推断类型**,所以 `json.dumps(...)` 出来的字符串
不加 cast 也能进 jsonb。我那 8 次栽的从来不是「漏了 cast」,
是**塞了一个不是 JSON 的裸串**(`"按单号"`、`"rel_xxx"`)。

> **判据盯错了不变量的时候,它会非常自信地报一堆假阳性** ——
> 而一条会误报的判据,下一个人会学会忽略它,于是它连真的那次也拦不住。

所以判据改成盯**真正的不变量**:

    绑给 jsonb 列的那个值,必须是 `json.dumps(...)` 出来的
    (或者 None,或者 SQL 那边显式 cast 了)

这要看 Python 那一侧,所以用 `ast` 把同一个 `execute(text(...), {...})` 里
参数字典的**值表达式**取出来判 —— 不追跨函数的值(追不动的时候判据会开始猜),
只判「字面上写的是不是 dumps」。

## ⚠️ 已知盲区(写下来,才和「忘了」分得开)

- **只看 `text(...)` 里的字面 SQL** —— 拼出来的 SQL 看不见
  (⚠️ 这一行原来写了三引号的例子,把模块自己的 docstring 截断了 ——
   **文档里举例也会撞上语法**,和「被扫描文件里不许写真密钥」同一族)
- **只认 `:参数` 这种绑定**,`%s` 风格的不认
- `update` 里 `set` 后面跨多行的复杂表达式可能解析不全 —— 解析不了就**跳过并计数**,
  而不是当成通过(见输出里那个「没解析出来」的数)
- 只查 jsonb。别的类型不对(比如 int 列塞字符串)它看不见
"""
import os
import re
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "tools"))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
import sql_lint as SL                                    # noqa: E402
from sqlalchemy import text as _t                        # noqa: E402

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


# ── 咬合记录 ────────────────────────────────────────────────────────
# ⚠️ 这条判据**改了三版才咬得住**,三版的错各不相同,都记下来:
#   一版:判「有没有 cast」→ 报了 9 处正常代码(盯错了不变量)
#   二版:留了「SQL 那边 cast 了就放行」的口子 → **真 bug 正好从那个口子走**
#   三版:收紧成「整个表达式就是一个绑定」→ 把 cast 那种也跳过了,又漏
# 现在认两种形状(`:x` 和 `cast(:x as jsonb)`),第三种(绑定藏在函数里)不认。
咬合 = [
    ("把 tools_api 里 policy_versions.failure_strategy 的 json.dumps 去掉,只留裸串",
     "jsonb 列绑定没 cast"),
    ("把 settings_api 里 audit_events.target_ref 的 json.dumps 去掉",
     "jsonb 列绑定没 cast"),
    ("把扫描目录改成一个空目录(扫到 0 段 SQL)",
     "只扫到"),
]

_insert = re.compile(r"insert\s+into\s+([a-z_][a-z0-9_]*)\s*\(([^)]*)\)\s*values\s*\(",
                     re.I | re.S)
_update = re.compile(r"update\s+([a-z_][a-z0-9_]*)\s+set\s+(.*?)(?:\s+where\b|$)",
                     re.I | re.S)
# ⚠️ **整个值表达式就是一个绑定**才算数 —— `:x` / ` :x `。
# 第一版用的是「表达式里**出现**一个绑定」,于是
# `jsonb_build_object('path', cast(:sp as text), …)` 里那个 `:sp` 被当成了
# 直接绑给 jsonb 列的值 —— 而它落在函数里的 **text** 位置上,完全正常。
# > **判据太松和太紧都会输,而太松的那种会先把人教会忽略它。**
# 认两种形状,而且**只认这两种**:
#     :x                      裸绑定
#     cast(:x as jsonb)       包了一层 cast —— **照样要查参数**,
#                             因为 `cast('拦住' as jsonb)` 运行时一样炸
# 第三种不认:绑定藏在函数里(`jsonb_build_object('path', cast(:sp as text), …)`)——
# 那个 `:sp` 落在函数内部的 text 位置上,完全正常,查它就是误报。
# > **判据太松和太紧都会输,而太松的那种会先把人教会忽略它。**
_整个就是绑定 = re.compile(
    r"^\s*(?::([a-zA-Z_][a-zA-Z0-9_]*)"
    r"|cast\s*\(\s*:([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s+jsonb\s*\))\s*$",
    re.I)


def _绑的是谁(表达式):
    m = _整个就是绑定.match(表达式)
    return (m.group(1) or m.group(2)) if m else None
_绑定 = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")


def _jsonb列们():
    from db import 连接
    with 连接() as c:
        return {(r[0], r[1]) for r in c.execute(_t(
            "select table_name, column_name from information_schema.columns "
            "where table_schema='public' and data_type='jsonb'")).all()}


def _跳过串(s, i):
    """`s[i]` 是一个开引号。返回这个 SQL 字符串字面量结束后的下标。

    ⚠️ SQL 里 `''`(两个单引号)是**转义的一个单引号,不是结束** ——
    `'a''b'` 是字符串 `a'b`。认错这一条会把一个字面量读成两个。
    """
    i += 1
    while i < len(s):
        if s[i] == "'":
            if i + 1 < len(s) and s[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return i      # 没闭合 —— 交给调用方,它会因为片数对不上而报「说不清」


def _跳过注释(s, i):
    """`s[i:i+2] == "--"`。返回这一行注释结束后的下标(换行符本身留着)。

    ⚠️ 2026-10-07 修:这个仓库的 SQL **在 values 里写长注释**,而注释里
    有逗号(「在这个仓库犯过七次,所以这里一律」)。原来的切分不认注释,
    于是那个逗号被当成顶层分隔符 → 片数和列数对不上 → **整段计入「说不清」**。
    > 而「说不清」和「真有裸串」在那行输出上长得一模一样 ——
    > 这两段恰恰是**注释写得最认真**的两段(它们在讲「JSONB 塞裸串犯过七次」),
    > **于是它们成了唯一没被检查到的两段。**
    """
    j = s.find("\n", i)
    return len(s) if j < 0 else j


def _剥注释(sql):
    """把 `--` 行注释换成**等长的空格**,再交给后面所有匹配。

    ⚠️ **等长**是关键:`查一段` 用 `m.end()` 定位 values 段的起点,
    长度一变 offset 就全错。

    ## 为什么要在入口剥,而不是在每个分支里跳

    2026-10-07 发现一个**比「说不清」更糟**的盲区:`_insert` 正则是
    `\)\s*values\s*\(` —— 列表和 `values` 之间只允许空白。于是

        insert into T (a, b)
        -- 一句注释
        values (:x, :y)

    **正则根本不匹配** → 循环体不执行 → 既不进「坏」也不进「说不清」。
    > 一段「列表和 values 之间有注释」的 INSERT,和一段**根本不存在的** INSERT,
    > 在那份输出上长得一模一样 —— 它连「说不清」都不算,是**彻底隐形**的。
    > 「说不清」至少被计数、被钉住了;隐形的那种连个数都没有。

    剥在入口,`_insert` / `_update` / 切逗号 / 取 values 段**一次全干净**,
    而不是四个地方各写一套跳注释(两套实现迟早分叉,而分叉时两边各自都绿)。

    ⚠️ 注释里可能有单引号,所以**要先认字符串字面量再认注释** ——
    反过来会把 `'-- 不是注释'` 里的内容当注释剥掉。
    """
    出, i = [], 0
    while i < len(sql):
        if sql[i] == "'":
            j = _跳过串(sql, i)
            出.append(sql[i:j])
            i = j
            continue
        if sql[i:i + 2] == "--":
            j = _跳过注释(sql, i)
            出.append(" " * (j - i))
            i = j
            continue
        出.append(sql[i])
        i += 1
    return "".join(出)


def _切顶层逗号(s):
    """按**顶层**逗号切 —— 括号里的、**字符串字面量里的**都不算。

    ⚠️ 2026-10-07 修:原来只跟括号深度,**不认字符串字面量** —— 于是
    `'一个只读 + 一个不可逆,正好也是配套关系的落点'` 这种带逗号的文案
    被切成了两片,片数和列数对不上,**整段计入「说不清」**。
    实测 6 段说不清里有 4 段是这么来的。
    > 一段「解析器追不到」的 SQL,和一段「真有裸串」的,
    > **在「说不清」这个分类上长得一模一样** ——
    > 而前者的修法在解析器里,后者在那段 SQL 里。
    > 把上限调大只是承认盲区;修这里让盲区消失,
    > **而且对将来每一段带逗号文案的 INSERT 都有效**。
    """
    出, 深, 当前, i = [], 0, "", 0
    while i < len(s):
        ch = s[i]
        if ch == "'":
            j = _跳过串(s, i)
            当前 += s[i:j]
            i = j
            continue
        if ch == "(":
            深 += 1
        elif ch == ")":
            深 -= 1
        if ch == "," and 深 == 0:
            出.append(当前); 当前 = ""
        else:
            当前 += ch
        i += 1
    if 当前.strip():
        出.append(当前)
    return [x.strip() for x in 出]


def 查一段(sql, jsonb列):
    """返回 [(表, 列, 那一段文本, 参数名)]。"""
    # ⚠️ 先剥注释 —— 见 `_剥注释` 的文档:不剥的话「列表和 values 之间有注释」
    # 那种 INSERT **连「说不清」都不算,是彻底隐形的**。
    sql = _剥注释(sql)
    坏, 没解析 = [], 0

    for m in _insert.finditer(sql):
        表 = m.group(1).lower()
        列们 = [c.strip().lower() for c in m.group(2).split(",") if c.strip()]
        # 取 values(...) 里那一段
        i = m.end()
        深, 值 = 1, ""
        while i < len(sql) and 深 > 0:
            # ⚠️ **字符串字面量里的括号不算深度** —— 和下面切逗号同一个病:
            # 一句文案里写个「(配套)」就能让括号配对错位,而错位之后
            # 取出来的 values 段是**截断的**,片数照样对不上 → 又一段「说不清」。
            if sql[i] == "'":
                j = _跳过串(sql, i)
                值 += sql[i:j]
                i = j
                continue
            if sql[i] == "(": 深 += 1
            elif sql[i] == ")": 深 -= 1
            if 深 > 0: 值 += sql[i]
            i += 1
        片 = _切顶层逗号(值)
        if len(片) != len(列们):
            没解析 += 1
            continue
        for 列, 表达式 in zip(列们, 片):
            参名 = _绑的是谁(表达式)
            if (表, 列) in jsonb列 and 参名:
                坏.append((表, 列, 表达式.strip()[:40], 参名))

    for m in _update.finditer(sql):
        表 = m.group(1).lower()
        for 片 in _切顶层逗号(m.group(2)):
            if "=" not in 片:
                continue
            列, _, 表达式 = 片.partition("=")
            列 = 列.strip().lower()
            参名 = _绑的是谁(表达式)
            if (表, 列) in jsonb列 and 参名:
                坏.append((表, 列, 片.strip()[:40], 参名))
    return 坏, 没解析


def _execute调用们(路):
    """找 `X.execute(text("…"), {…})`,把 SQL 和**参数字典的值表达式**一起拿出来。

    值表达式只归成三类:`dumps`(是 json.dumps 调用)/ `None` / 其它(原样的短描述)。
    ⚠️ **不追跨函数的值** —— 追不动的时候判据会开始猜,而猜错的判据比没有更糟。
    追不到的(参数不是字面写在这个调用里)计入「没解析出来」,**不当成通过**。
    """
    import ast
    try:
        树 = ast.parse(open(路, encoding="utf-8").read(), filename=路)
    except SyntaxError:
        return
    for n in ast.walk(树):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "execute" and n.args):
            continue
        头 = n.args[0]
        if not (isinstance(头, ast.Call) and getattr(头.func, "id", None) == "text"
                and 头.args and isinstance(头.args[0], ast.Constant)
                and isinstance(头.args[0].value, str)):
            continue
        sql = 头.args[0].value
        参数 = {}
        for a in n.args[1:]:
            if isinstance(a, ast.Dict):
                for k, v in zip(a.keys, a.values):
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        参数[k.value] = _归类(v)
            elif isinstance(a, ast.Call) and getattr(a.func, "id", None) == "dict":
                for kw in a.keywords:
                    if kw.arg:
                        参数[kw.arg] = _归类(kw.value)
        yield n.lineno, sql, 参数


def _归类(v):
    import ast
    if isinstance(v, ast.Constant) and v.value is None:
        return "None"
    if isinstance(v, ast.Call):
        f = v.func
        名 = getattr(f, "attr", None) or getattr(f, "id", None)
        if 名 == "dumps":
            return "dumps"
    # 三元 `a if c else b`:两边都得是 dumps/None 才算数
    if isinstance(v, ast.IfExp):
        a, b = _归类(v.body), _归类(v.orelse)
        return "dumps" if {a, b} <= {"dumps", "None"} else f"{a}/{b}"
    if isinstance(v, ast.Constant) and isinstance(v.value, str):
        return f"字面串 {v.value[:16]!r}"
    return "(说不清)"


def main():
    print("\n\033[1m▸ JSONB 列写裸串 · 今天栽了八次的那一族\033[0m")
    try:
        jsonb列 = _jsonb列们()
    except Exception as e:
        print(f"  {R}❌ 问不到库(information_schema):{type(e).__name__}: {e}{D}")
        print(f"     这条判据**靠问库**,问不到就当场红 —— "
              f"不猜类型,因为猜错和猜对在建表成功那一刻长得一样")
        return 1
    print(f"  库里有 {len(jsonb列)} 个 jsonb 列")

    文件们 = []
    for d in SL.扫的目录:
        full = os.path.join(根, d)
        if not os.path.isdir(full):
            continue
        for dp, dn, fn in os.walk(full):
            dn[:] = [x for x in dn if x not in (".venv", "__pycache__", "node_modules")]
            文件们 += [os.path.join(dp, f) for f in fn if f.endswith(".py")]

    # ⚠️ **「说不清」要留位置,不只留个数。**
    # 原来只累加一个 `没解析` 计数,于是输出里那句「1 段没解析出来」
    # 谁也找不到它在哪 —— 一条读不出来的审计,和没有审计是一回事。
    坏, 查了, 说不清 = [], 0, []
    for 路 in sorted(set(文件们)):
        for 行号, sql, 参数们 in _execute调用们(路):
            查了 += 1
            这些, n = 查一段(sql, jsonb列)
            for _ in range(n):
                说不清.append((os.path.relpath(路, 根), 行号, "整段没解析出来"))
            for 表, 列, 段, 参名 in 这些:
                # ⚠️ **不能因为 SQL 那边有 cast 就放行。**
                # 第一版就是这么写的,而咬合当场证明那是个洞:
                # `cast('拦住' as jsonb)` 运行时**照样炸** ——
                # cast 不会让裸串变成合法 JSON,它只是换了个报错。
                # 而那个放行口,正好覆盖了真实缺陷的形状。
                # > **为了减少误报而留的例外,恰好放过真 bug** ——
                # > 这比漏写一条判据更糟:判据在、绿着,人以为它看着。
                值 = 参数们.get(参名)
                if 值 is None:                     # 这个参数不是字面写在同一个调用里
                    说不清.append((os.path.relpath(路, 根), 行号,
                                 f"{表}.{列} ← :{参名}(参数不在同一个调用里)"))
                    continue
                if 值 == "dumps" or 值 == "None":
                    continue
                坏.append((os.path.relpath(路, 根), 行号, 表, 列, 参名, 值))

    print(f"  扫了 {查了} 段 SQL · 其中 {len(说不清)} 段说不清(**不当成通过** —— 见下)")
    # ⚠️ 样本量下限:扫到 0 段就是路径写错了,而那会让这条判据「全过」。
    if 查了 < 50:
        print(f"  {R}❌ 只扫到 {查了} 段 SQL —— 太少了,多半是路径不对。"
              f"**扫不到东西不是通过**{D}")
        return 1
    if 坏:
        print(f"\n  {R}❌ {len(坏)} 处 jsonb 列绑定没 cast{D}")
        for 相对, 行, 表, 列, 参名, 值 in 坏[:20]:
            print(f"     {相对}:{行}  {表}.{列}  ←  :{参名} = {值}")
        print(f"\n     修法:那个参数传 `json.dumps(...)`(或 None),"
              f"不要传裸串;要么 SQL 那边 `cast(:x as jsonb)`。")
        print(f"     ⚠️ 这一族的表现是 `invalid input syntax for type json`,"
              f"**只在走到那一条 SQL 的路径上炸** —— 别的路径全绿。")
        return 1
    # ── 「说不清」不是「没问题」 ────────────────────────────────────────
    # ⚠️ **这一段是 2026-09-29 补的,补的是这个判据自己犯的错。**
    # 在这之前它打印「N 段没解析出来(**不当成通过**)」,然后 `return 0` 打绿灯 ——
    # `没解析` 这个数**从来没进过判决**。
    #   · 说明写着一件事,退出码做着另一件事,而**人看到的是绿灯**;
    #   · 这正是这个文件开头那句话的同族:「未知不是 0,说不清不是『不是』」。
    #
    # 为什么不是「有一段说不清就红」:这个盲区是**已知且有限**的
    # (参数不字面写在同一个调用里,追不到),硬红会让判据天天响,
    # 而**会误报的判据会把人教会忽略它**。
    # 所以照这个仓库已有的成语走 —— 像 `dsl.未落地限制上限` 那样**钉一个写死的数**:
    # 现状是几段就钉几段,**多一段就红**。新增的说不清必须当场被看见,
    # 而不是混进一个只会变大的计数里。
    #
    # ⚠️ 这个数必须是**手写的字面量**,不许写成 `len(说不清)` ——
    # 那样它永远等于现状,判据当场变成空跑。
    #
    # 现在这 1 段是 `services/api/app/seed_demo.py:137`:那一段的 jsonb 值
    # **全是内联的 `'...'::jsonb` 字面量,一个 jsonb 绑定参数都没有** ——
    # 所以它安全,解析器只是看不出「这里没有要检查的绑定」。
    # 查过了(2026-09-29),别再查一遍。
    # 2026-10-07:**从 1 钉到 0**。原来那 1 段(以及后来涨到的 6 段)全都不是
    # 「参数不在同一个调用里」,而是**解析器自己的词法盲区**:
    #   · 字符串字面量里的逗号(「一个只读 + 一个不可逆,正好也是配套关系的落点」)
    #   · values 里的 SQL 行注释,注释文字里的逗号
    #   · 以及 `''` 转义(`'a''b'` 是一个字面量不是两个)
    # 补上这三条词法之后 722 段**全部解析成功**。
    # > 而最后那两段恰恰是**注释写得最认真**的两段(它们在讲「JSONB 塞裸串
    # > 犯过七次」)—— 正因为注释里有逗号,**它们成了唯一没被检查到的两段。**
    # 钉 0 的意思是:**从今往后任何一段解析不出来都要当场被看见**。
    说不清上限 = 0
    # ── 咬合(2026-10-07 实跑,下面每条的「预期红」都是抄的真实输出)─────────
    #   ① 对照                                        → 绿,说不清 0/0
    #   ② 删掉 `_剥注释` 里跳注释那一支                → ❌ 说不清的段数 2 超过了钉住的 0 段
    #   ③ 删掉 `_切顶层逗号` 里跳字符串那一支          → ❌ 说不清的段数 4 超过了钉住的 0 段
    #   ④ 种一个裸串,藏在 values **内部**的注释后面    → ❌ 1 处 jsonb 列绑定没 cast
    #   ⑤ 种一个裸串,藏在「列表和 values 之间」的注释后 → ❌ 1 处 jsonb 列绑定没 cast
    #   ⑥ 把 ⑤ 那段改成 `json.dumps({})`               → 绿(对照:判的是绑定不是形状)
    #
    # ⚠️ 第 ⑤ 关最关键:**修复前那种形状是彻底隐形的** —— `_insert` 正则要求
    # `) values (` 之间只有空白,于是整段既不进「坏」也不进「说不清」。
    # 而第一次做第 ④ 关时我把注释放在了列表和 values 之间,它**没红** ——
    # 那不是检查漏了,是**我的注入没进检查的视野**(咬合的第二种失效方式,
    # CLAUDE.md 第 8 节记着)。换成 values 内部才真的验到。
    if 说不清:
        print(f"\n  ⚠️ {len(说不清)} 段**说不清**(不是通过,也不是失败 —— 追不到绑的是什么):")
        for 相对, 行, 说 in 说不清[:20]:
            print(f"     {相对}:{行}  {说}")
    if len(说不清) > 说不清上限:
        print(f"\n  {R}❌ 说不清的段数 {len(说不清)} 超过了钉住的 {说不清上限} 段{D}")
        print(f"     新增的那几段要么改成「参数字面写在同一个调用里」,"
              f"要么确认过之后把上限那个数字改大**并写清为什么**。")
        print(f"     ⚠️ 别直接调大了就走 —— 这个判据能放过的正是"
              f"「运行时才炸、别的路径全绿」那一族。")
        return 1
    print(f"\n  {G}✅ 每一处**解析出来的** jsonb 列绑定都对"
          f"(json.dumps 或显式 cast);说不清 {len(说不清)}/{说不清上限} 段{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
