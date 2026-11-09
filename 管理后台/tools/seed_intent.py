#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示项目的一份演示意图配置(2026-11-09 第三期)。可重复执行:已有同 key 就跳过。

ifmatch_reachable_check / 详情页冒烟要从列表里取样例,CI 是新库;只放草稿、不冻版本。
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "api", "app"))
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402

项目, KEY = "project_demo_a", "demo-intents"
配置 = {"意图": [{"名称": "报价", "说明": "要出一份报价单", "例句": ["出个报价", "这套多少钱"]}]}


def main():
    with 事务() as c:
        if c.execute(text("select 1 from intent_drafts where project_id=:p and key=:k"), {"p": 项目, "k": KEY}).first():
            print(f"已有 {KEY},跳过")
            return 0
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()
        c.execute(text("""insert into intent_drafts (id, organization_id, project_id, key, entries, created_at, created_by,
                              updated_at, revision)
                          values (:i, :o, :p, :k, cast(:e as jsonb), now(), 'seed-intent', now(), 1)"""),
                  {"i": "it_" + uuid.uuid4().hex[:12], "o": org, "p": 项目, "k": KEY,
                   "e": json.dumps(配置, ensure_ascii=False)})
    print(f"建了 {KEY}({len(配置['意图'])} 个意图)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
