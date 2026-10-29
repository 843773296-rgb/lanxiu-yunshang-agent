#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库里的每张表,都要能从 rebuild.sh 建出来。

## 为什么要这条 —— 今天为同一个形状红过两次 CI

    第一次  call_audio / call_transcript(ASR 的两张)   本地 72、CI 70
    第二次  cust_owner_log(客户归属那张)               本地 76、CI 75

两次都是**文档表数对账抓到的**,而本地一片绿。

根因:那些表的 `create table if not exists` **写在运行时**。
开发机上跑过一次,表就一直在;**CI 每次从零 rebuild,那段代码没被调用,表不存在**。

> **「表存在」和「表被建过」不是一回事。**
> 而在开发机上,这两件事长得一模一样。

## 这条检查和 `ensure_tables.py` 是两回事,两个都要

    ensure_tables.py  **修复** —— 把登记过的表显式建出来
    这条检查          **防线** —— 发现「库里有一张表,谁也建不出它」

只有前者不够:**登记表本身会漏**。新写一个只查不改的模块、忘了登记,
就又回到原点 —— 而它只会在下一次 CI 红的时候才暴露。

## 怎么扫

从 `rebuild.sh` 的步骤清单现读(不手抄 —— 手抄的清单不会跟着流水线变),
对每个步骤文件扫 `CREATE TABLE`,**并跟进它 import 的本地模块一层**
(`ensure_tables.py` 自己不写 SQL,它调各模块的建表函数)。
"""
from contextlib import closing   # ← 连接要显式关:sqlite3 的 with 只管事务,不关连接(2026-10-29)
import os, re, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "backend", "lanxiu.db")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

咬合 = [
    ('把某张表从 ensure_tables 的登记里删掉(它就没人建了)',
     '每张表都能从 rebuild.sh 建出来'),
    # 反方向那条(2026-10-24 补):攻击点是**往登记里加一张不存在的表**。
    # ⚠️ 注意这两条咬合攻的是**同一张登记表的两个方向** ——
    # 删一条打的是「库里有、没人建」,加一条打的是「登记了、库里没有」。
    ('往 ensure_tables 的登记里加一张库里不存在的表',
     '登记过的表,这个库里真的都有'),
]


def 步骤文件():
    sh = open(os.path.join(ROOT, "tools", "rebuild.sh"), encoding="utf-8").read()
    m = re.search(r"for STEP in (.+?); do", sh, re.S)
    if not m:
        sys.exit("❌ rebuild.sh 里找不到步骤清单 —— 格式变了,这条检查得跟着改")
    return [x.split()[0] for x in re.findall(r'"([^"]+)"', m.group(1))]


def 扫建表(路径, 已看=None, 深度=0):
    """扫一个文件里的 CREATE TABLE,并跟进它 import 的本地模块一层。"""
    已看 = 已看 if 已看 is not None else set()
    if 深度 > 1 or not os.path.isfile(路径) or 路径 in 已看:
        return set()
    已看.add(路径)
    src = open(路径, encoding="utf-8").read()
    表 = {x.lower() for x in re.findall(
        r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+[`\"\[]?(\w+)", src, re.I)}
    # 跟进本地 import(ensure_tables 自己不写 SQL,它调模块的建表函数)
    #
    # ⚠️ **一行 import 好几个模块,每一个都要跟进。**
    # 2026-09-27 踩到:这里原来是 `import\s+(\w+)`,**只认逗号列表里的第一个名字** ——
    # `import ownership, asr, credit, roster, seed_rating` 只跟进了 `ownership`。
    # 于是「由逗号 import 的第二个模块建的表」在这条检查眼里是**隐形的**。
    # 这个洞一直没露出来,因为前面那几个模块碰巧还有自己的 backfill 脚本在建同样的表 ——
    # **一个被别的路顺手盖住的盲区,和没有盲区长得一模一样。**
    # ⚠️ **`[^\S\n]` 而不是 `\s`** —— `\s` 匹配换行,会把**下一行的 import 吃掉**。
    # 2026-09-27 踩到两次,同一个正则、同一族盲区:
    #   ① 上午:`import\s+(\w+)` **只认逗号列表里的第一个**模块名;
    #   ② 下午:改成 `[\w\s,]+` 之后,`import a, b`\n`import c` 里的 c
    #      被并进上一行当成 b 的一部分丢掉了 —— 于是 `seed_quote` 建的表看起来没人建。
    # **它对「一行」的定义和 Python 对「一行」的定义不一样**,而症状是「那张表没人建」。
    # ⚠️⚠️ **2026-10-23 第三次栽在同一族上,所以改成用 `ast` 取 import,不再补正则。**
    # 这次是:`import grade_diff          # 版师核档差的登记表` —— **带行尾注释**。
    # 那个正则要求 `import` 之后到行尾只剩 `[\w\s,]` 和空白,`#` 一进来整条就断了,
    # 于是那一行**在这条检查眼里不存在**,`grade_diff_check` 变成「没人建的孤儿表」。
    # 而它只在 CI 上红:本地那个库还没重建过,**表压根不在库里,也就没什么可判成孤儿**。
    # > 一张「没人建的表」和一张「建它那行被正则漏看了的表」,
    # > **在这条检查的输出上长得一模一样** —— 它报的是第一句,而真相是第二句。
    # > 照着它报的理由去做(「把建表挂进 ensure_tables」)会发现**早就挂着了**。
    #
    # 前两次(都记在下面那段历史注释里)的修法都是**再改一次正则**,而这是打地鼠:
    # Python 对「一行 import」的定义,正则追不上(注释、续行、`as`、括号分组、
    # 相对 import……)。`ast` 用的就是 Python 自己那个定义。
    名们 = set()
    try:
        import ast as _ast
        for n in _ast.walk(_ast.parse(src)):
            if isinstance(n, _ast.Import):
                名们 |= {a.name.split(".")[0] for a in n.names}   # `import x as y` 只取 x
            elif isinstance(n, _ast.ImportFrom) and n.module and not n.level:
                名们.add(n.module.split(".")[0])
    except SyntaxError:
        # 解析不了就照实说 —— **别静默当成「这个文件没有 import」**,
        # 那会让它跟进的所有表变成孤儿,而红的理由指向完全错的地方。
        print(f"  {Y}⚠{D} {os.path.relpath(路径, ROOT)} 解析不了(语法错?)"
              f"—— **它 import 的模块建的表这一轮扫不到**,孤儿名单会虚高")
    for 名 in sorted(名们):
        for d in ("backend", "tools", "knowledge"):
            p = os.path.join(ROOT, d, f"{名}.py")
            if os.path.isfile(p):
                表 |= 扫建表(p, 已看, 深度 + 1)
    return 表


def 登记的表():
    r"""从 `ensure_tables.py` 的 `登记` 里**静态**取出表名。

    ⚠️ **用 ast,不 import** —— import 它会连带 import 二十多个 backend 模块,
    一条只读判据不该有那么大的副作用面。而**正则在这个文件上已经栽过三次**
    (逗号 import 只认第一个 / `\s` 吃掉下一行 / 行尾注释),所以不再写正则。
    ⚠️ 形状对不上就**抛**,不静默返回空集 ——
    空集上「登记的表都在库里」恒成立,而**那和真的验过了长得一模一样**。
    """
    import ast
    src = open(os.path.join(ROOT, "tools", "ensure_tables.py"), encoding="utf-8").read()
    登记 = None
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                getattr(x, "id", "") == "登记" for x in node.targets):
            登记 = node.value
    if not isinstance(登记, ast.List):
        sys.exit("❌ ensure_tables.py 里找不到 `登记 = [...]` —— 格式变了,这条检查得跟着改")
    出 = []
    for el in 登记.elts:
        if not (isinstance(el, ast.Tuple) and len(el.elts) == 3
                and isinstance(el.elts[2], ast.List)):
            sys.exit(f"❌ `登记` 里有一条形状不是 (模块, 函数名, [表名…]):"
                     f"{ast.dump(el)[:120]} —— 这条检查得跟着改")
        for x in el.elts[2].elts:
            if not (isinstance(x, ast.Constant) and isinstance(x.value, str)):
                sys.exit(f"❌ `登记` 里有个表名不是字面字符串:{ast.dump(x)[:80]} —— "
                         f"**拼出来的表名这条检查读不到**,等于那张表没被守住")
            出.append(x.value)
    return 出


def main():
    if not os.path.exists(DB):
        print(f"  {Y}⏭{D} 库不在,跳过 —— **跳过不是通过**")
        return 0
    with closing(sqlite3.connect(DB)) as c, c:
        库 = {r[0] for r in c.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'")}

    建得出 = set()
    for f in 步骤文件():
        建得出 |= 扫建表(os.path.join(ROOT, f))

    孤儿 = sorted(t for t in 库 if t.lower() not in 建得出)

    print("\n\033[1m▸ 表的来路 · 每张表都要能从 rebuild.sh 建出来\033[0m")
    print("  " + "=" * 80)
    坏 = []
    if 孤儿:
        print(f"  {R}❌{D} 每张表都能从 rebuild.sh 建出来 —— 这 {len(孤儿)} 张不行:")
        for t in 孤儿[:8]:
            print(f"      {t}")
        if len(孤儿) > 8:
            print(f"      ……还有 {len(孤儿) - 8} 张(共 {len(孤儿)})")
        print(f"\n      它们**只在这台机器上存在**:某段代码运行时建了,而它一直留着。")
        print(f"      **CI 每次从零 —— 那些表不存在**,于是表数对不上、依赖它们的检查会炸。")
        print(f"      修法:把建表挂进 `tools/ensure_tables.py` 的登记表。")
        坏.append("每张表都能从 rebuild.sh 建出来")
    else:
        print(f"  {G}✅{D} 每张表都能从 rebuild.sh 建出来(库里 {len(库)} 张)")

    # ── 反方向:**登记了,而这个库里没有** ───────────────────────────────
    #
    # 上面那条只查一个方向:库里有、rebuild 建不出(孤儿表)。
    # 反方向在本地**完全隐形**,而且隐形得更彻底 ——
    # 孤儿表好歹出现在 `sqlite_master` 里、扫得到;
    # **一张「登记了却没建」的表压根不存在,它不出现在任何扫描里**。
    # 症状是「依赖它的那条检查炸了」,而炸的地方和这件事隔着好几层。
    #
    # > 一张「还没被建出来」的表,和一张「这条检查根本没去看」的表,
    # > **在库的表清单上长得一模一样** —— 两边都是「它不在」。
    #
    # 怎么会发生:在库里手工建了表、代码里也登记了,但**这个库**是在那之前建的,
    # 而 `ensure_tables.py` 只在 `rebuild.sh` 里跑。于是本地那个库一直缺着,
    # 直到谁去重建、或者谁写了一条真去查它的判据。
    # (2026-10-23 记在交接里「仍然没人守」,10-24 补上。)
    登记表 = 登记的表()
    # **样本量** —— 空集上「登记的表都在库里」恒成立。
    # ⚠️ 下限只防「一张都没读到」(AST 取法改坏时会这样),**不是说该有多少张**:
    # 写一个贴着现状的数就是夹具写死会漂的东西(每登记一张新表它就该跟着涨)。
    if len(set(登记表)) < 10:
        print(f"  {R}❌{D} 登记过的表,这个库里真的都有 —— "
              f"只从 `登记` 里读到 {len(set(登记表))} 张,**这不是通过,是没读到东西**"
              f"(下限 10 只防空扫)")
        坏.append("登记过的表,这个库里真的都有")
    else:
        缺 = sorted(t for t in set(登记表) if t not in 库)
        if 缺:
            print(f"  {R}❌{D} 登记过的表,这个库里真的都有 —— "
                  f"这 {len(缺)} 张登记了却不在库里:")
            for t in 缺[:8]:
                print(f"      {t}")
            if len(缺) > 8:
                print(f"      ……还有 {len(缺) - 8} 张(共 {len(缺)})")
            print(f"\n      **缺一张表不报错,只会让依赖它的那条检查炸在别处。**")
            print(f"      修法:`python3 tools/ensure_tables.py`(它只建表,不铺数据)。")
            print(f"      ⚠️ 要是那张表是新登记的,记得**代码和库一起推** ——")
            print(f"      只建库不推代码,另一个检出的门禁会红在它没碰过的检查上。")
            坏.append("登记过的表,这个库里真的都有")
        else:
            print(f"  {G}✅{D} 登记过的表,这个库里真的都有"
                  f"(登记 {len(set(登记表))} 张,一张不缺)")

    print(f"      **「表存在」和「表被建过」不是一回事** —— 本地建过就一直在,CI 每次从零。")
    print(f"      今天为这个形状红过两次 CI,两次都是本地全绿。")
    if 坏:
        print(f"  {R}❌ {len(坏)} 条没过:{坏}{D}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
