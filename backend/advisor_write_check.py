#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写入侧的检查 —— **写了顾问名字,就必须一起写工号。**

## 这条检查是怎么冒出来的

`intent/advisor-columns.md` 要删掉那几张表的 `advisor` 名字列。
做之前扫了一遍写入侧,发现**这次迁移只做了一半**:

    引用建好了(`fix_advisor_ref.py` 回填了 5848 行)
    **而写的一侧还在只写名字** —— `booking.py` / `seed.py` /
    `fix_order_measure.py` 三处 INSERT **从不写工号**

而 `advisor_ref_check` 查的是**已有的行**。门禁跑的是静态种子数据,
**这几条写路径根本没被走过** —— 所以它一直绿着,
而每建一条预约就产出一行**有名字、没工号**的记录。

> **「数据是对的」和「产生数据的路径是对的」是两件事。**
> 前者今天成立,后者明天就把它推翻,而中间不会有任何提示。

删名字列的话,那几行就**彻底没有顾问了** —— 而页面上只是一栏空白。

## 查法:扫源码里的 INSERT,不扫数据

数据检查看到的是**过去**,源码检查看到的是**将来会写成什么样**。
这一条要防的是后者,所以它扫 `INSERT INTO 表(列,列,…)`:
**列清单里出现了名字列,就必须也出现工号列。**

⚠️ **只查 INSERT 的列清单,不查 UPDATE。**
UPDATE 的形状太多(`SET a=?, b=?`、`SET a=COALESCE(?,a)`、拼出来的),
静态判会误报 —— 而**检查天天红,人就不看了**。
少查一类是漏报,误报会让人去改本来正确的代码。**误报比漏报贵。**
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]

咬合 = [
    ("把 booking.py 那两条 INSERT 里的 advisor_no 去掉",
     "写了名字列的 INSERT,都一起写了工号列"),
    ("把扫描范围改成只扫一个文件",
     "扫到的文件数不少于下限"),
]

# 名字列 → 它的工号列。**和 `fix_advisor_ref.映射` 同一套口径**,
# 但这里只需要列名对应关系,不需要表名 —— INSERT 里表名已经写着了。
名号 = {"advisor": "advisor_no", "measured_by": "measured_by_no"}

# 扫哪些文件。**现算,不写死一张清单** —— 写死的话新加一个写入脚本
# 不会有人记得回来加,而那时候它漏了的表现是「没被扫到」,
# 和「扫过了没问题」长得一模一样。
扫 = ["backend", "tools", "fakedata"]

# 扫到的文件数下限 —— 少于这个数说明扫描范围被改窄了(而不是问题变少了)
文件数下限 = 40

FAIL = []
# `INSERT INTO 表(列, 列, …)` —— 只要列清单,值那部分不管
INS = re.compile(r'INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)',
                 re.I | re.S)


def _净(段):
    """把源码里的字符串拼接抹平:去掉引号和换行,只留列名和逗号。"""
    return re.sub(r'["\'\s\\]+', "", 段)


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("顾问写入 · 检查")
    print("=" * 84)
    档 = []
    for d in 扫:
        for root, _dd, fs in os.walk(os.path.join(ROOT, d)):
            if ".venv" in root or "__pycache__" in root: continue
            档 += [os.path.join(root, f) for f in fs if f.endswith(".py")]
    ck("扫到的文件数不少于下限", len(档) >= 文件数下限, len(档),
       f"{len(档)} 个 .py(下限 {文件数下限})—— "
       f"**扫描范围被改窄和问题变少长得一模一样**")

    坏, 总 = [], 0
    for f in 档:
        if os.path.basename(f) in ("advisor_write_check.py", "fix_advisor_ref.py"):
            continue          # 迁移脚本和本文件自己,不在范围内
        src = open(f, encoding="utf-8", errors="ignore").read()
        for m in INS.finditer(src):
            # ⚠️ **列清单要先把源码里的字符串拼接抹掉。**
            # 这些 SQL 常常跨行拼:`"…,measured_by," "measured_by_no,…"` ——
            # 按逗号切开之后,`measured_by_no` 前面粘着引号和换行,匹配不上,
            # 于是这条检查把一处**已经改好的**代码报成没改。
            #
            # **一个会误报的检查,会让人去改本来正确的代码** —— 而且第一次
            # 报出来时看起来完全可信(它指着真实的行号)。
            表 = m.group(1)
            列 = [x.strip().strip('"').strip("'").strip()
                  for x in _净(m.group(2)).split(",")]
            for 名, 号 in 名号.items():
                if 名 in 列:
                    总 += 1
                    if 号 not in 列:
                        行 = src[:m.start()].count("\n") + 1
                        坏.append(f"{os.path.relpath(f, ROOT)}:{行} "
                                  f"INSERT INTO {表} 写了 {名} 没写 {号}")

    ck("写了名字列的 INSERT,都一起写了工号列", not 坏, 总,
       f"{len(坏)} 处:\n       " + "\n       ".join(坏[:6]) if 坏 else
       f"{总} 条 INSERT 写了顾问名字,**每一条都带着工号** —— "
       f"名字是 staff 的副本,工号才是引用")

    print()
    if FAIL:
        print(f"\033[31m❌ 顾问写入 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        print("\n   **「数据是对的」和「产生数据的路径是对的」是两件事** —— "
              "前者今天成立,后者明天就把它推翻,而中间不会有任何提示。")
        sys.exit(1)
    print("\033[32m✅ 顾问写入全部符合预期\033[0m")
    print(f"    扫了 {len(档)} 个文件、{总} 条写顾问名字的 INSERT。"
          f"**数据检查看到的是过去,源码检查看到的是将来会写成什么样。**")


if __name__ == "__main__":
    main()
