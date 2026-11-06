#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示项目的一张演示术语表(2026-11-06,术语配置 / 语义层)。**可重复执行**:已有同 key 的就跳过,不覆盖。

为什么要它:tools/ifmatch_reachable_check(在 page-smoke 里,CI 里排在 e2e 之前)要从术语表列表里取一张样例,
验「界面拿得到改草稿要带的 revision」—— CI 是新库,没有这张表它就拿不到样例、判红(而那条红的理由「什么都没验到」是对的)。
只放草稿、不冻版本:冻结 / 取数口的检查由 tests/e2e/test_glossary_flow 自己造数据验。
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "api", "app"))
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402

项目, KEY = "project_demo_a", "demo-terms"
术语 = [
    {"标准词": "到店率", "叫法": ["到店转化", "预约到店比"], "类别": "指标", "定义": "预约了的顾客里真到店的比例",
     "口径": {"分子": "到店的预约数", "分母": "预约数(不含已取消)", "时间": "按预约日期"}},
    {"标准词": "褙子", "叫法": ["褙", "长褙"], "类别": "名词", "定义": "宋制对襟长衣"},
]


def main():
    with 事务() as c:
        if c.execute(text("select 1 from glossary_drafts where project_id=:p and key=:k"), {"p": 项目, "k": KEY}).first():
            print(f"已有 {KEY},跳过")
            return 0
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()
        c.execute(text("""insert into glossary_drafts (id, organization_id, project_id, key, entries, created_at, created_by,
                              updated_at, revision)
                          values (:i, :o, :p, :k, cast(:e as jsonb), now(), 'seed-glossary', now(), 1)"""),
                  {"i": "gl_" + uuid.uuid4().hex[:12], "o": org, "p": 项目, "k": KEY,
                   "e": json.dumps(术语, ensure_ascii=False)})
    print(f"建了 {KEY}({len(术语)} 条)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
