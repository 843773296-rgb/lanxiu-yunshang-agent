#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库路径单源(执行手册 W02 第一步,2026-11-17)。

## 为什么
11-17 盘点:**133 个模块各自拼** `DB = os.path.join(HERE, "lanxiu.db")`,71 处直接 `sqlite3.connect(…lanxiu.db)`,
57 个检查用 82 处 `m.DB = 副本` 把它们一个个指到库副本上 —— 漏指一个,检查就写进真库(11-04 栽过:
「检查切库前先 import 写口」那条教训就是这么来的)。

## 怎么用
新模块一律:

    from dbpath import 路径
    DB = 路径()

检查想切副本,设环境变量 `LANXIU_DB` 再 import(或照旧 `m.DB = 副本`,两种都认)。
老模块不在这一步改(133 个文件一起动是一轮全量门禁,还会撞一批咬合锚);`tools/dbpath_check.py` 把存量登记成欠债,
**只许少不许多** —— 新代码再自己拼路径就红。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def 路径():
    """业务后台 sqlite 的路径:环境变量 LANXIU_DB 优先(检查切副本用),否则 backend/lanxiu.db。"""
    return os.environ.get("LANXIU_DB") or os.path.join(HERE, "lanxiu.db")
