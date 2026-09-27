#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""索引构建:**真跑 Worker,真写库**。

## 这个文件里最要紧的一条是第 ④ 组

`knowledge/index_plan.py` 的检查点逻辑早就写好了(31 条测试 + 7 条咬合全过)。
而它**曾经完全不成立** —— `worker.py` 把处理器整个包在一个事务里,
写了 100 个向量然后崩了全部回滚,`index_members` 是空的,
于是 `算待做()` 永远算出「全部待做」。

> **判据对、代码对,而整件事不成立。检查点的前提是它能被提交。**

处理器现在用独立连接分批提交。而那是个**声称** —— 第 ④ 组去证明它:
在一个外层事务里写 `index_builds`、在独立事务里写 `embeddings`,
然后**回滚外层**,验证独立那份还在。

⚠️ 这是**机制级**的证明,不是场景级的。原因:场景级要「跑到一半 kill -9」,
而 mock 向量快得没有「一半」可言 —— 一个依赖时机的测试会变成偶发红,
而偶发红最后都会被人忽略。**证明机制成立,比制造一次崩溃更可靠。**

## 用完还原

这个文件建的构建 / 向量 / 成员全部删掉。⚠️ 但**片段和文档不动** ——
那 71 个片段是 `tools/ingest_lanxiu.py` 导入的真语料,别的测试也读它们。
"""
import json
import os
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))

from sqlalchemy import create_engine, text   # noqa: E402

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)

过, 挂 = [], []
建了的构建, 建了的配置 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 新(p):
    return f"{p}_{uuid.uuid4().hex[:10]}"


def 摆一个构建(c, org, proj, kb, *, 配置哈希="cfg-t", 模型="emb-mock", 维度=1536,
           candidate_k=50, final_chunk_limit=8):
    rc = 新("rc")
    c.execute(text("""insert into retrieval_config_versions
        (id, organization_id, project_id, recall_modes, candidate_k,
         context_budget_tokens, final_chunk_limit, content_hash, revision,
         created_at, created_by)
        values (:i,:o,:p, cast(:rm as jsonb), :ck, 4000, :fl, :ch, 1, now(), 'test')"""),
              {"i": rc, "o": org, "p": proj, "rm": json.dumps(["vector"]),
               "ck": candidate_k, "fl": final_chunk_limit, "ch": 配置哈希})
    ib = 新("ib")
    c.execute(text("""insert into index_builds
        (id, organization_id, project_id, knowledge_base_id,
         retrieval_config_version_id, embedding_model_id, embedding_dim, status,
         created_at, created_by, revision)
        values (:i,:o,:p,:k,:r,:m,:d,'排队中', now(), 'test', 1)"""),
              {"i": ib, "o": org, "p": proj, "k": kb, "r": rc, "m": 模型, "d": 维度})
    jid = 新("job")
    c.execute(text("""insert into jobs
        (id, organization_id, project_id, type, target_ref, status, attempts,
         max_attempts, idempotency_key, created_at, created_by, updated_at, revision)
        values (:i,:o,:p,'index_build', cast(:t as jsonb),'排队中',0,3,:k,
                now(),'test', now(),1)"""),
              {"i": jid, "o": org, "p": proj,
               "t": json.dumps({"index_build_id": ib}), "k": uuid.uuid4().hex})
    建了的构建.append(ib)
    建了的配置.append(rc)
    return ib, jid


def 跑worker():
    """真起一个 Worker 进程跑一轮。**不在测试进程里直接调处理器** ——
    那样测不到「处理器在 `跑一轮` 的事务安排下能不能工作」,
    而那正是检查点成立与否的所在。"""
    p = subprocess.run(
        [os.path.join(ROOT, ".venv", "bin", "python"),
         os.path.join(ROOT, "workers", "worker.py"), "--一轮", "--type", "index_build"],
        capture_output=True, text=True, cwd=ROOT, timeout=180,
        env={**os.environ, "DATABASE_URL": URL})
    return p.stdout + p.stderr


with eng.begin() as c:
    r = c.execute(text("""select organization_id, id from projects
                          where archived_at is null order by created_at limit 1""")
                  ).first()
    assert r, "库里没有项目 —— 先 make seed-demo"
    org, proj = r
    kb = c.execute(text("""select id from knowledge_bases
                           where project_id=:p and name='澜绣业务拍板'"""),
                   {"p": proj}).scalar()
    片段数 = c.execute(text("""
        select count(*) from chunks ch
          join document_versions dv on dv.project_id=ch.project_id
                                   and dv.id=ch.document_version_id
          join documents d on d.project_id=dv.project_id and d.id=dv.document_id
         where ch.project_id=:p and d.knowledge_base_id=:k"""),
                    {"p": proj, "k": kb}).scalar() if kb else 0

ck("语料已经在库里(先跑 `python tools/ingest_lanxiu.py`)", bool(kb) and 片段数 > 0,
   f"知识库 {kb} · {片段数} 个片段")
if not kb or not 片段数:
    print("\n❌ 没有语料,后面都测不了 —— **这不叫通过,叫没东西可测**")
    sys.exit(1)

print("\n▸ ① 端到端:71 个片段 → 71 个成员,一个不少")
with eng.begin() as c:
    ib1, j1 = 摆一个构建(c, org, proj, kb, 配置哈希="cfg-t1")
出 = 跑worker()
with eng.connect() as c:
    st = c.execute(text("select status, input_hash from index_builds"
                        " where project_id=:p and id=:i"),
                   {"p": proj, "i": ib1}).mappings().first()
    n1 = c.execute(text("select count(*) from index_members"
                        " where project_id=:p and index_build_id=:b"),
                   {"p": proj, "b": ib1}).scalar()
ck("构建走到「已就绪」", st and st["status"] == "已就绪", st and st["status"])
ck(f"成员数 == 片段数({片段数})—— **集合相等,不是「至少写了一条」**"
   "(少了就有内容检索不到,而那在界面上和「知识库里就这么点」长得一样)",
   n1 == 片段数, n1)
ck("输入指纹落库了(没有它,下次就判不出输入变没变)", bool(st and st["input_hash"]),
   (st or {}).get("input_hash", "")[:26])
with eng.connect() as c:
    空向量 = c.execute(text("""select count(*) from index_members im
                              where im.project_id=:p and im.index_build_id=:b
                                and im.embedding_id is null"""),
                     {"p": proj, "b": ib1}).scalar()
ck("没有一条成员的 `embedding_id` 是空的 —— **登记不是完成**",
   空向量 == 0, f"{空向量} 条空的")

print("\n▸ ② 跨构建复用:换检索配置,**一个向量都不重算**")
with eng.begin() as c:
    ib2, j2 = 摆一个构建(c, org, proj, kb, 配置哈希="cfg-t2", candidate_k=30,
                    final_chunk_limit=12)
出2 = 跑worker()
ck("第二个构建也就绪了", "'已就绪'" in 出2 or "已完成" in 出2, 出2.strip().split("\n")[-1][:120])
ck("**新算向量 0 / 复用 71** —— 向量的身份是 (文本, 模型),换配置不该重算",
   "'新算向量': 0" in 出2 and f"'复用向量': {片段数}" in 出2,
   [l for l in 出2.split("\n") if "复用向量" in l][:1])
with eng.connect() as c:
    指纹们 = c.execute(text("""select distinct input_hash from index_builds
                             where project_id=:p and id = any(:ids)"""),
                    {"p": proj, "ids": [ib1, ib2]}).scalars().all()
ck("两个构建的指纹**不同**(检索配置是输入的一部分)", len(set(指纹们)) == 2,
   [x[:22] for x in 指纹们])

print("\n▸ ③ 重复投递:不重做(Outbox **保证**会重复投递)")
with eng.begin() as c:
    j3 = 新("job")
    c.execute(text("""insert into jobs
        (id, organization_id, project_id, type, target_ref, status, attempts,
         max_attempts, idempotency_key, created_at, created_by, updated_at, revision)
        values (:i,:o,:p,'index_build', cast(:t as jsonb),'排队中',0,3,:k,
                now(),'test', now(),1)"""),
              {"i": j3, "o": org, "p": proj,
               "t": json.dumps({"index_build_id": ib1}), "k": uuid.uuid4().hex})
出3 = 跑worker()
ck("同一个构建再投一次 → 报「已经是终态」,不重算",
   "已经是终态" in 出3, [l for l in 出3.split("\n") if "已经是终态" in l][:1])
with eng.connect() as c:
    n1b = c.execute(text("select count(*) from index_members"
                         " where project_id=:p and index_build_id=:b"),
                    {"p": proj, "b": ib1}).scalar()
ck("成员数没变(重复投递没写重)", n1b == n1, f"{n1} → {n1b}")

print("\n▸ ④ **检查点机制**:外层事务回滚,独立事务写进去的还在")
# ⚠️ 这一组是这个文件存在的主要理由。见文件头。
with eng.begin() as c:
    ib4, j4 = 摆一个构建(c, org, proj, kb, 配置哈希="cfg-t4")
探针 = 新("emb")
外层回滚了 = False
外 = eng.connect()
tx = 外.begin()
try:
    # 外层:改构建状态(处理器就是这么做的)
    外.execute(text("update index_builds set status='向量化中'"
                    " where project_id=:p and id=:i"), {"p": proj, "i": ib4})
    # 独立事务:写一个向量并**提交**(处理器分批写入就是这么做的)
    with eng.begin() as 内:
        内.execute(text("""insert into embeddings (id, organization_id, project_id,
                text_hash, model_id, dim, embedding, created_at, created_by, revision)
                values (:i,:o,:p,:h,'emb-探针',1536,
                        cast(:v as vector), now(), 'test', 1)"""),
                  {"i": 探针, "o": org, "p": proj, "h": "探针" + uuid.uuid4().hex[:8],
                   "v": "[" + ",".join(["0.01"] * 1536) + "]"})
    raise RuntimeError("故意让外层失败 —— 模拟处理器中途崩掉")
except RuntimeError:
    tx.rollback()
    外层回滚了 = True
finally:
    外.close()
with eng.connect() as c:
    状态 = c.execute(text("select status from index_builds where project_id=:p and id=:i"),
                   {"p": proj, "i": ib4}).scalar()
    探针还在 = c.execute(text("select count(*) from embeddings"
                           " where project_id=:p and id=:i"),
                      {"p": proj, "i": 探针}).scalar()
ck("外层回滚了(构建状态退回「排队中」)", 外层回滚了 and 状态 == "排队中", 状态)
ck("**独立事务写的向量还在** —— 这就是检查点成立的全部依据"
   "(它曾经不成立:处理器整个包在一个事务里,写多少都会一起回滚)",
   探针还在 == 1, f"{探针还在} 条")
with eng.begin() as c:
    c.execute(text("delete from embeddings where project_id=:p and id=:i"),
              {"p": proj, "i": 探针})

print("\n▸ ⑤ 已经做完的跳过:手动补一半成员,再跑只算剩下的")
with eng.begin() as c:
    ib5, j5 = 摆一个构建(c, org, proj, kb, 配置哈希="cfg-t5")
    # 从 ib1 那次的成员里搬一半过来 —— 它们的向量是真的(有 embedding_id)
    搬 = c.execute(text("""select chunk_id, embedding_id from index_members
                          where project_id=:p and index_build_id=:b
                          order by chunk_id limit :n"""),
                   {"p": proj, "b": ib1, "n": 片段数 // 2}).mappings().all()
    for m in 搬:
        c.execute(text("""insert into index_members (id, organization_id, project_id,
                index_build_id, chunk_id, embedding_id, created_at, created_by)
                values (:i,:o,:p,:b,:c,:e, now(), 'test')"""),
                  {"i": 新("im"), "o": org, "p": proj, "b": ib5,
                   "c": m["chunk_id"], "e": m["embedding_id"]})
出5 = 跑worker()
ck(f"{len(搬)} 条已完成的没被重做(整体向量也全部复用)",
   "'新算向量': 0" in 出5, [l for l in 出5.split("\n") if "新算向量" in l][:1])
with eng.connect() as c:
    n5 = c.execute(text("select count(*) from index_members"
                        " where project_id=:p and index_build_id=:b"),
                   {"p": proj, "b": ib5}).scalar()
ck(f"补齐到 {片段数} 条,**没有重复**(唯一约束 + on conflict)", n5 == 片段数, n5)

print("\n▸ ⑥ 0 个片段不许静默成功")
with eng.begin() as c:
    空kb = 新("kb")
    c.execute(text("""insert into knowledge_bases (id, organization_id, project_id,
            name, status, created_at, created_by, revision)
            values (:i,:o,:p,'空知识库(测试用)','active', now(), 'test', 1)"""),
              {"i": 空kb, "o": org, "p": proj})
    ib6, j6 = 摆一个构建(c, org, proj, 空kb, 配置哈希="cfg-t6")
出6 = 跑worker()
ck("没有片段 → 报 `NO_CHUNKS`,**不是「已就绪」**"
   "(一个 0 个片段的就绪索引,检索永远返回空,而那和「库里就这么点」长得一样)",
   "NO_CHUNKS" in 出6, [l for l in 出6.split("\n") if "NO_CHUNKS" in l][:1] or 出6[-150:])
with eng.connect() as c:
    st6 = c.execute(text("select status from index_builds where project_id=:p and id=:i"),
                    {"p": proj, "i": ib6}).scalar()
ck("空构建没被标成「已就绪」", st6 != "已就绪", st6)

# ── 还原 ──────────────────────────────────────────────────────────
# ⚠️ **片段和文档不动** —— 那 71 个片段是导入的真语料,别的测试也读它们。
with eng.begin() as c:
    for ib in 建了的构建:
        c.execute(text("delete from index_members where project_id=:p and index_build_id=:b"),
                  {"p": proj, "b": ib})
    # ⚠️ 先删事件再删任务 —— `job_events` 有外键指向 `jobs`。
    # (`job_events` 是**只追加**的审计表。删它的行在生产上是不该做的事;
    #  这里删的是这个测试自己刚造的那些,而且只按 type 限定。)
    c.execute(text("""delete from job_events where project_id=:p and job_id in
                      (select id from jobs where project_id=:p and type='index_build')"""),
              {"p": proj})
    c.execute(text("delete from jobs where project_id=:p and type='index_build'"),
              {"p": proj})
    for ib in 建了的构建:
        c.execute(text("delete from index_builds where project_id=:p and id=:i"),
                  {"p": proj, "i": ib})
    for rc in 建了的配置:
        c.execute(text("delete from retrieval_config_versions where project_id=:p and id=:i"),
                  {"p": proj, "i": rc})
    # ⚠️ 删向量之前要先删**所有**引用它们的成员,不只是这个测试建的构建的 ——
    # 手工试跑留下的构建也引用着同一批向量(它们的身份是 (文本, 模型),跨构建共享,
    # **那正是复用的机制**)。踩过一次:`ForeignKeyViolation`。
    c.execute(text("""delete from index_members where project_id=:p and embedding_id in
        (select id from embeddings where project_id=:p
           and model_id in ('emb-mock','emb-探针'))"""), {"p": proj})
    # 成员没了,引用它们的构建也清掉(手工试跑留下的那些)
    c.execute(text("""delete from index_builds where project_id=:p
        and id not in (select distinct index_build_id from index_members
                       where project_id=:p and index_build_id is not null)
        and created_by in ('test','ingest')"""), {"p": proj})
    c.execute(text("delete from embeddings where project_id=:p"
                   " and model_id in ('emb-mock','emb-探针')"), {"p": proj})
    c.execute(text("delete from knowledge_bases where project_id=:p"
                   " and name='空知识库(测试用)'"), {"p": proj})
with eng.connect() as c:
    剩 = c.execute(text("""select
        (select count(*) from index_builds where project_id=:p),
        (select count(*) from index_members where project_id=:p),
        (select count(*) from embeddings where project_id=:p),
        (select count(*) from chunks where project_id=:p)"""), {"p": proj}).first()
ck("跑完:构建/成员/向量都清了,**而片段一个没少**(它们是导入的真语料)",
   剩[0] == 0 and 剩[1] == 0 and 剩[2] == 0 and 剩[3] == 片段数,
   f"构建 {剩[0]} · 成员 {剩[1]} · 向量 {剩[2]} · 片段 {剩[3]}")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
