#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把澜绣桥的两个工具(取转写 / 写跟进)登记进后台工具目录(2026-10-24,音频整理流程)。

    ./.venv/bin/python tools/seed_bridge_tools.py                   # 默认 project_lanxiu
    ./.venv/bin/python tools/seed_bridge_tools.py --项目 project_demo_a

**重复跑不增加对象**:同名工具已在就不新建;契约(说明 / 入参 / 出参)变了才出新版本。

## 这两个工具后台**不执行**

`adapter = lanxiu_bridge`:工作流跑到它们时只在 `bridge_calls` 记一张单,运行挂起;
澜绣的 supervise_sync 拉回去用它自己的函数执行、回执(见 `services/api/app/bridge_api.py`)。
它们在这里登记,是为了工作流的工具步骤能选到一个**真实存在的工具版本** ——
选不到就只能手抄一个 id,而那正是改版要去掉的东西。
"""
import argparse
import hashlib
import json
import os
import sys
import uuid

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(根, "services", "api", "app"),
                os.path.join(根, "services", "api", "app", "contract")]

工具们 = [
    dict(name="取转写", side="read_only",
         purpose="按通话号取一通录音的转写原文(澜绣 call_transcript;人工改过的以改过的为准)",
         input_schema={"type": "object", "properties": {"call_id": {"type": "string", "description": "通话号,如 TS-001"}},
                       "required": ["call_id"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "text": {"type": "string"}, "call_id": {"type": "string"},
             "customer_id": {"type": "string"}, "顾问": {"type": "string"},
             "时长秒": {"type": "number"}, "人工改过": {"type": "boolean"}},
             "required": ["text", "call_id"]}),
    dict(name="写跟进", side="irreversible",
         purpose="把人工核对过的定稿写成澜绣客户档案里的一条正式跟进(只追加;按幂等键去重,重试不写第二条)",
         input_schema={"type": "object", "properties": {
             "customer_id": {"type": "string"}, "内容": {"type": "string"},
             "call_id": {"type": "string"}},
             "required": ["customer_id", "内容"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "跟进号": {"type": "string"}, "customer_id": {"type": "string"},
             "是新写的": {"type": "boolean"}, "结果": {"type": "string"}},
             "required": ["跟进号", "结果"]}),
]


def _哈希(t):
    return "sha256:" + hashlib.sha256(json.dumps(t, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--项目", default="project_lanxiu")
    a = ap.parse_args()
    from sqlalchemy import text
    from db import 事务
    出 = []
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": a.项目}).scalar()
        if not org:
            print(f"❌ 没有项目 {a.项目}"); return 1
        for t in 工具们:
            旧 = c.execute(text("""select id from tool_definitions where project_id=:p and name=:n
                                   and archived_at is null"""), {"p": a.项目, "n": t["name"]}).scalar()
            if 旧:
                did = 旧
            else:
                did = "td_" + uuid.uuid4().hex[:16]
                c.execute(text("""insert into tool_definitions (id, organization_id, project_id, name,
                    purpose, side_effect_type, adapter, owner, draft_revision, status,
                    created_at, created_by, updated_at, revision)
                    values (:i,:o,:p,:n,:pu,:se,'lanxiu_bridge','lanxiu-bridge',0,'active',
                            now(),'seed-bridge', now(), 1)"""),
                          {"i": did, "o": org, "p": a.项目, "n": t["name"], "pu": t["purpose"],
                           "se": t["side"]})
            h = _哈希(t)
            末 = c.execute(text("""select id, version_no, content_hash from tool_versions
                                  where project_id=:p and tool_definition_id=:d
                                  order by version_no desc limit 1"""),
                           {"p": a.项目, "d": did}).mappings().first()
            if 末 and 末["content_hash"] == h:
                出.append((t["name"], 末["id"], "没动")); continue
            vid = "tv_" + uuid.uuid4().hex[:16]
            c.execute(text("""insert into tool_versions (id, organization_id, project_id,
                tool_definition_id, version_no, model_description, input_schema, output_schema,
                side_effect_type, allowed_scopes, idempotency_strategy, timeout_seconds,
                retry_policy, redaction, server_bound_arguments, pollable, content_hash,
                created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:d,:v,:md, cast(:ins as jsonb), cast(:outs as jsonb), :se,
                        cast('[]' as jsonb), cast(:idem as jsonb), 600, cast(:rp as jsonb),
                        cast('{}' as jsonb), cast('{}' as jsonb), false, :h,
                        now(),'seed-bridge', now(), 1)"""),
                      {"i": vid, "o": org, "p": a.项目, "d": did, "v": (末["version_no"] if 末 else 0) + 1,
                       "md": t["purpose"], "ins": json.dumps(t["input_schema"], ensure_ascii=False),
                       "outs": json.dumps(t["output_schema"], ensure_ascii=False), "se": t["side"],
                       "idem": json.dumps({"键": "(运行, 步骤, 第几次挂起)", "谁去重": "澜绣写跟进那一侧"},
                                          ensure_ascii=False),
                       "rp": json.dumps({"重试": "不重试 —— 等回执,不重发"}, ensure_ascii=False), "h": h})
            出.append((t["name"], vid, "新版本" if 末 else "新建"))
    for n, v, how in 出:
        print(f"  {n:4s} {v}  {how}")
    print(f"✅ 澜绣桥工具登记好了({a.项目},{len(出)} 个)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
