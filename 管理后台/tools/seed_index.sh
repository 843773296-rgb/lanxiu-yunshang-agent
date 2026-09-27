#!/usr/bin/env bash
# 给一个知识库建一次真模型索引(给测试和本地调试用)。
#
# ⚠️ **为什么要有这个脚本**
#
# `tests/integration/test_index_build.py` 跑完会把向量清干净
# (它的洁净度检查要求开跑前 `embeddings` 是空的 —— 在脏状态上跑出来的结论不可信)。
# 而 `tests/e2e/test_knowledge_flow.py` 需要一个**已就绪的索引**。
#
# 两份测试谁先跑都行,靠的就是后者在缺索引时调这个脚本自己建一个。
# 没有它的话,`make test` 之后 `make test-e2e` 必然失败,
# **而那个失败看起来像「接口坏了」**。
set -uo pipefail
cd "$(dirname "$0")/.."
DB="${DATABASE_URL:-postgresql+psycopg://$USER@localhost:5432/aimc_dev}"

./.venv/bin/python - <<'PY'
import os, sys, uuid, json
sys.path.insert(0, os.path.join(os.getcwd(), "services/api/app"))
from sqlalchemy import create_engine, text
eng = create_engine(os.environ.get("DATABASE_URL")
                    or "postgresql+psycopg://" + os.environ["USER"]
                       + "@localhost:5432/aimc_dev")
新 = lambda p: f"{p}_{uuid.uuid4().hex[:10]}"
with eng.begin() as c:
    r = c.execute(text("""select organization_id, id from projects
                          where archived_at is null order by created_at limit 1""")).first()
    if not r:
        sys.exit("库里没有项目 —— 先 make seed-demo")
    org, proj = r
    kb = c.execute(text("""select id from knowledge_bases
                           where project_id=:p and archived_at is null
                           order by created_at limit 1"""), {"p": proj}).scalar()
    if not kb:
        sys.exit("没有知识库 —— 先 python tools/ingest_lanxiu.py")
    rc, ib, jid = 新("rc"), 新("ib"), 新("job")
    c.execute(text("""insert into retrieval_config_versions
        (id, organization_id, project_id, recall_modes, candidate_k,
         context_budget_tokens, final_chunk_limit, content_hash, revision,
         created_at, created_by)
        values (:i,:o,:p, cast(:rm as jsonb), 20, 4000, 8, :h, 1, now(), 'seed')"""),
              {"i": rc, "o": org, "p": proj, "rm": json.dumps(["vector"]),
               "h": "cfg-seed-" + uuid.uuid4().hex[:6]})
    c.execute(text("""insert into index_builds
        (id, organization_id, project_id, knowledge_base_id,
         retrieval_config_version_id, embedding_model_id, embedding_dim, status,
         created_at, created_by, revision)
        values (:i,:o,:p,:k,:r,'bge-small-zh-v1.5',512,'排队中', now(), 'seed', 1)"""),
              {"i": ib, "o": org, "p": proj, "k": kb, "r": rc})
    c.execute(text("""insert into jobs
        (id, organization_id, project_id, type, target_ref, status, attempts,
         max_attempts, idempotency_key, created_at, created_by, updated_at, revision)
        values (:i,:o,:p,'index_build', cast(:t as jsonb),'排队中',0,3,:k,
                now(),'seed', now(),1)"""),
              {"i": jid, "o": org, "p": proj,
               "t": json.dumps({"index_build_id": ib}), "k": uuid.uuid4().hex})
print(f"派了构建 {ib}")
PY
[ $? -ne 0 ] && exit 1

DATABASE_URL="$DB" ./.venv/bin/python workers/worker.py --一轮 --type index_build 2>&1 | tail -1
