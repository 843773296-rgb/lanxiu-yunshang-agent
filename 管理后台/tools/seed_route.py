#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示项目的一份演示查询路由(2026-11-08 第二期)。**可重复执行**:已有同 key 的就跳过,不覆盖。

为什么要它:和 seed_glossary 同一个理由 —— tools/ifmatch_reachable_check / 详情页冒烟要从查询路由列表里取一份样例,
CI 是新库,没有它就拿不到样例、判红(而那条红的理由「什么都没验到」是对的)。
只放草稿、不冻版本:冻结 / 试一句 / 聊天助手引用由 tests/e2e/test_route_flow 自己造数据验。
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "api", "app"))
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402

项目, KEY = "project_demo_a", "demo-routes"
配置 = {"规则": [{"名称": "客户名先查档案", "条件": {"种类": "实体", "值": "客户"}, "去向": "提示一句", "提示": "「{片段}」是客户"}]}


def main():
    with 事务() as c:
        if c.execute(text("select 1 from route_drafts where project_id=:p and key=:k"), {"p": 项目, "k": KEY}).first():
            print(f"已有 {KEY},跳过")
            return 0
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()
        c.execute(text("""insert into route_drafts (id, organization_id, project_id, key, entries, created_at, created_by,
                              updated_at, revision)
                          values (:i, :o, :p, :k, cast(:e as jsonb), now(), 'seed-route', now(), 1)"""),
                  {"i": "rt_" + uuid.uuid4().hex[:12], "o": org, "p": 项目, "k": KEY,
                   "e": json.dumps(配置, ensure_ascii=False)})
    print(f"建了 {KEY}({len(配置['规则'])} 条规则)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
