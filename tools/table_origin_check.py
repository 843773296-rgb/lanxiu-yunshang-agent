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
import os, re, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "backend", "lanxiu.db")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

咬合 = [
    ('把某张表从 ensure_tables 的登记里删掉(它就没人建了)',
     '每张表都能从 rebuild.sh 建出来'),
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
    for mod in re.findall(r"^\s*import\s+(\w+)|^\s*from\s+(\w+)\s+import", src, re.M):
        名 = mod[0] or mod[1]
        for d in ("backend", "tools", "knowledge"):
            p = os.path.join(ROOT, d, f"{名}.py")
            if os.path.isfile(p):
                表 |= 扫建表(p, 已看, 深度 + 1)
    return 表


def main():
    if not os.path.exists(DB):
        print(f"  {Y}⏭{D} 库不在,跳过 —— **跳过不是通过**")
        return 0
    with sqlite3.connect(DB) as c:
        库 = {r[0] for r in c.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'")}

    建得出 = set()
    for f in 步骤文件():
        建得出 |= 扫建表(os.path.join(ROOT, f))

    孤儿 = sorted(t for t in 库 if t.lower() not in 建得出)

    print("\n\033[1m▸ 表的来路 · 每张表都要能从 rebuild.sh 建出来\033[0m")
    print("  " + "=" * 80)
    if 孤儿:
        print(f"  {R}❌{D} 每张表都能从 rebuild.sh 建出来 —— 这 {len(孤儿)} 张不行:")
        for t in 孤儿[:8]:
            print(f"      {t}")
        print(f"\n      它们**只在这台机器上存在**:某段代码运行时建了,而它一直留着。")
        print(f"      **CI 每次从零 —— 那些表不存在**,于是表数对不上、依赖它们的检查会炸。")
        print(f"      修法:把建表挂进 `tools/ensure_tables.py` 的登记表。")
        return 1

    print(f"  {G}✅{D} 每张表都能从 rebuild.sh 建出来(库里 {len(库)} 张)")
    print(f"      **「表存在」和「表被建过」不是一回事** —— 本地建过就一直在,CI 每次从零。")
    print(f"      今天为这个形状红过两次 CI,两次都是本地全绿。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
