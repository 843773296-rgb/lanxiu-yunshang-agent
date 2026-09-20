#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「用到时才建」的表,在重建流水线里显式建出来。

## 为什么需要这一步 —— 今天踩了两次

有些模块的表是在第一次调用时建的(`create table if not exists`)。
在开发机上这没问题:跑过一次,表就一直在。

**但 CI 每次从零建库 —— 那些表根本不存在。**

    2026-09-20 第一次:call_audio / call_transcript(ASR 的两张)
    2026-09-20 第二次:cust_owner_log(客户归属的那张)

两次都是同一个形状,而且**两次都是文档表数对账抓到的**(本地 76、CI 75)。

> **「表存在」和「表被建过」不是一回事** —— 本地建过就一直在,CI 每次从零。

第一次我把建表挂到了 `backfill_transcript` 上(它顺带建),
**那是打补丁** —— 下一个只查不改的模块还会再犯。所以这次集中到这一步。

## 什么表该登记在这里

**只查不改的模块的表** —— 它们没有对应的 backfill 脚本,
所以没有任何一步会建它们。有 backfill 的表不必登记(那一步自己会建)。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")

# (模块, 建表函数名, 这个模块建的表)  —— **表名列出来是为了能自检**
登记 = [
    ("ownership", "建表", ["cust_owner_log"]),
    ("asr", "建表", ["call_audio", "call_transcript"]),
    ("credit", "建表", ["deal_credit"]),
    ("roster", "建表", ["shift_tpl", "roster", "leave_req"]),
]


def main():
    c = sqlite3.connect(DB)
    建了 = []
    for 模块名, 函数名, 表们 in 登记:
        m = __import__(模块名)
        getattr(m, 函数名)(c)
        建了 += 表们
    c.commit()

    # 自检:登记的表**真的存在**。
    # 光调建表函数不够 —— 函数名写错、表名改过,都会静默什么都不做。
    有 = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    缺 = [t for t in 建了 if t not in 有]
    if 缺:
        sys.exit(f"❌ 登记了但没建出来:{缺} —— 多半是建表函数改了名或表名改了")

    print(f"  确保 {len(建了)} 张「用到时才建」的表存在:{'、'.join(建了)}")
    print(f"  ⚠️ 这一步存在的理由:**本地建过就一直在,CI 每次从零** —— 今天为这个红过两次")
    c.close()


if __name__ == "__main__":
    main()
