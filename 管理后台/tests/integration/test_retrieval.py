#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索链:召回 → 截断 → 证据链。**不调 Claude**(`要精排=False`)。

## 为什么这个文件不测精排效果

精排要真调 Claude:花月租额度、慢、结果有波动。
放进 `make test` 会让门禁变成随机拦路。
所以这里走 `要精排=False` 的路径 —— 它覆盖召回、配置校验、截断、证据链,
也就是这条链上**除了模型判断之外的全部**。

精排的**判据**(挡 LLM 编造)在 `tests/orchestration/test_reranker.py`,零依赖。
精排的**效果**(表格头该降到最后)在 `make test-live`。

三层拆开是有意的:**只有第三层要花钱,而前两层覆盖了绝大部分会坏的地方。**

## ⚠️ 这个文件要什么

真库 + 71 个真片段(`tools/ingest_lanxiu.py`)+ 模型文件(`tools/fetch_model.sh`)。
"""
import json
import os
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "knowledge"))

from sqlalchemy import create_engine, text   # noqa: E402
import retrieval as RT                        # noqa: E402
import embedder_bge as BGE                    # noqa: E402

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)
过, 挂, 建的 = [], [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def _抛(f, 类=RT.检索不了):
    try:
        f()
    except 类:
        return True
    except Exception as e:
        print(f"     (抛的是 {type(e).__name__}: {str(e)[:70]})")
        return False
    return False


def 新(p):
    return f"{p}_{uuid.uuid4().hex[:10]}"


if not os.path.isfile(os.path.join(BGE.模型目录(), "onnx", "model.onnx")):
    print(f"❌ 模型文件不在 —— 跑 `bash tools/fetch_model.sh`。**这不叫跳过,叫没东西可测**")
    sys.exit(1)


def 摆索引(c, org, proj, kb, *, modes=None, k=12, 预算=3000, 限片=4, 状态跑=True):
    rc, ib, jid = 新("rc"), 新("ib"), 新("job")
    c.execute(text("""insert into retrieval_config_versions
        (id, organization_id, project_id, recall_modes, candidate_k,
         context_budget_tokens, final_chunk_limit, content_hash, revision,
         created_at, created_by)
        values (:i,:o,:p, cast(:rm as jsonb), :k, :b, :f, :h, 1, now(), 'test')"""),
              {"i": rc, "o": org, "p": proj,
               "rm": json.dumps(modes or ["vector"]), "k": k, "b": 预算, "f": 限片,
               "h": "cfg-" + uuid.uuid4().hex[:6]})
    c.execute(text("""insert into index_builds
        (id, organization_id, project_id, knowledge_base_id,
         retrieval_config_version_id, embedding_model_id, embedding_dim, status,
         created_at, created_by, revision)
        values (:i,:o,:p,:k,:r,'bge-small-zh-v1.5',512,'排队中', now(), 'test', 1)"""),
              {"i": ib, "o": org, "p": proj, "k": kb, "r": rc})
    if 状态跑:
        c.execute(text("""insert into jobs
            (id, organization_id, project_id, type, target_ref, status, attempts,
             max_attempts, idempotency_key, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'index_build', cast(:t as jsonb),'排队中',0,3,:k,
                    now(),'test', now(),1)"""),
                  {"i": jid, "o": org, "p": proj,
                   "t": json.dumps({"index_build_id": ib}), "k": uuid.uuid4().hex})
    建的.append((ib, rc))
    return ib


def 跑worker(*, 允许失败码=None):
    # ⚠️ **先记下已经失败的,只报本次新增的。**
    # 查「库里所有失败的 job」太宽:上一轮留下的(比如上次在这儿红了、
    # 清理没执行)会被重复报告,而人分不清那是新的还是旧的 —— 于是开始忽略它。
    with eng.connect() as _c0:
        跑之前失败的 = {r[0] for r in _c0.execute(text(
            "select id from jobs where type='index_build' and status='失败'"))}
    p = subprocess.run([os.path.join(ROOT, ".venv", "bin", "python"),
                        os.path.join(ROOT, "workers", "worker.py"),
                        "--一轮", "--type", "index_build"],
                       capture_output=True, text=True, cwd=ROOT, timeout=300,
                       env={**os.environ, "DATABASE_URL": URL})
    # ⚠️ **检查 Worker 到底成没成。** 不检查的代价实测过:
    # Worker 崩了(`TypeError`),而测试只在后面表现为「索引还是排队中」——
    # 那条信息指向的是**索引状态**,不是「Worker 崩了」。
    # 我为此查了三轮,而答案在 `jobs.error_detail` 里躺着。
    #
    # **一个不检查被调用方是否成功的测试辅助函数,会把根因藏起来。**
    if p.returncode != 0:
        raise AssertionError(
            f"Worker 进程退出码 {p.returncode} —— **不是「索引没建好」,是 Worker 崩了**\n"
            f"       stdout: {p.stdout[-400:]}\n       stderr: {p.stderr[-400:]}")
    with eng.connect() as _c:
        # ⚠️ **不只查 status='失败'。**
        #
        # 「退回重试」把 job 设回**「排队中」**(加一个 `next_retry_at` 退避)——
        # 所以一个跑失败了的 job 看起来像「还没跑」。
        # **「排队中」有两种含义:从没跑过,和跑失败了正在等退避重试**,
        # 而它们长得一模一样。区分它们的是 `attempts > 0`。
        #
        # (踩过:测试报「索引还不是已就绪」,而 Worker 其实跑了、失败了、
        #  退回重试了 —— 那条信息指向索引状态,根因在 job_events 里。)
        坏 = [x for x in _c.execute(text(
            """select j.id, j.status, j.attempts, j.error_code, j.error_detail,
                      (select payload from job_events e
                        where e.job_id=j.id order by e.seq desc limit 1) 最后事件
                 from jobs j
                where j.type='index_build'
                  and (j.status='失败' or (j.status='排队中' and j.attempts > 0))
                order by j.updated_at desc limit 8""")).mappings().all()
              if x["id"] not in 跑之前失败的]
    # ⚠️ **调用方声明它预期哪个错误码**,而不是笼统忽略所有失败。
    # 后者会让「我故意制造的那个失败」和「一个意外的崩溃」都通过。
    意外 = [x for x in 坏 if x["error_code"] != 允许失败码]
    if 意外:
        raise AssertionError(
            f"有 index_build 任务**意外**失败了(预期的是 {允许失败码!r})"
            f" —— **这不是「索引没就绪」**:\n"
            + "\n".join(
                f"       {x['id']} [{x['status']}, 试了 {x['attempts']} 次] "
                f"{x['error_code']} {str(x['error_detail'])[:160]}\n"
                f"         最后一条事件:{str(x['最后事件'])[:200]}"
                for x in 意外))
    return p.stdout + p.stderr


with eng.begin() as c:
    org, proj = c.execute(text("""select organization_id, id from projects
                                 where archived_at is null order by created_at limit 1""")
                          ).first()
    kb = c.execute(text("""select id from knowledge_bases
                           where project_id=:p and name='澜绣业务拍板'"""),
                   {"p": proj}).scalar()
    片段数 = c.execute(text("select count(*) from chunks where project_id=:p"),
                    {"p": proj}).scalar()
ck("语料在库里", bool(kb) and 片段数 > 0, f"{片段数} 个片段")
if not kb:
    sys.exit(1)

# 洁净度:见 test_index_build.py 里那段 —— 脏状态上跑出来的结论不可信
with eng.connect() as c:
    脏 = c.execute(text("""select count(*) from jobs where project_id=:p
                          and type='index_build'
                          and status not in ('已完成','失败','已取消')"""),
                  {"p": proj}).scalar()
    脏向量 = c.execute(text("select count(*) from embeddings where project_id=:p"),
                    {"p": proj}).scalar()
ck("开跑前没有非终态的 index_build 任务", 脏 == 0, 脏)
# ⚠️ 向量也要查:手工试跑留下的构建**不在这个文件的清理清单里**,
# 它的成员会引用 embeddings,于是清理时撞 ForeignKeyViolation。
# (踩过一次。而那个报错指向「外键」,根因是「库里有别人留下的东西」。)
ck("开跑前 `embeddings` 是空的", 脏向量 == 0, 脏向量)
if 脏 or 脏向量:
    print("\n❌ 库不干净 —— **先清再跑**,不在脏状态上出结论")
    sys.exit(1)

print("\n▸ ① 正常一次:召回 → 截断 → 证据链")
with eng.begin() as c:
    ib = 摆索引(c, org, proj, kb, k=12, 预算=3000, 限片=4)
跑worker()
with eng.connect() as c:
    链 = RT.检索(c, 项目=proj, 构建id=ib, 问题="客户给了差评要怎么处理",
               要精排=False)
ck("召回了候选(candidate_k=12)", 链["召回数"] == 12, 链["召回数"])
ck("**选片受 final_chunk_limit 限制**(4)", 链["选了几片"] <= 4, 链["选了几片"])
ck("每一片都有**能翻回原文的证据串**(节路径 + 第几段)",
   all(" · 第 " in x["证据"] and x["证据"].strip() for x in 链["选片"]),
   链["选片"][0]["证据"] if 链["选片"] else "没有选片")
ck("`embedding.是mock` 是 **False**(用的是真模型)",
   链["embedding"]["是mock"] is False, 链["embedding"])
ck("**`改写` 是 None 而不是空字符串** —— "
   "「没做」和「改写结果是空」要分得开",
   链["改写"] is None and "没做" in 链["改写说明"], 链["改写说明"])
ck("`要精排=False` 时**说清为什么以及代价**(只走向量的排序不可靠)",
   链["精排"]["做了"] is False and "不可靠" in 链["精排"]["为什么"])
ck("token 数标明是**粗估**(不许拿它算钱)", 链["token是粗估"] is True)
ck("**截断说出来了**(静默截断的后果:被截掉的和没检索到长得一样)",
   bool(链["截断"]), 链["截断"])

print("\n▸ ② 两个上限**都**生效,取更严的那个")
# 只看条数会在片段特别长时爆预算;只看预算会在片段特别短时塞太多条。
#
# ⚠️ 夹具的数字是**量出来的**:真片段 token 分布是 min 15 / avg 92 / max 327。
# 第一版我写 `预算=120, 限片=10`,**被配置校验拦住了** ——
# `校验检索配置` 有一条「预算 < 限片×20 就报装不下」,而 120 < 200。
# 那条判据是对的(10 片放不进 120 token,那个 10 是句空话),
# **所以要改的是夹具,不是判据** —— 我在测一个系统本来就不该允许的配置。
# 现在 `预算=100, 限片=4`:100 ≥ 4×20 合法,而一片就约 92 token → 预算先到。
with eng.begin() as c:
    # ⚠️ **40 token,而候选里最小的片段 55 token** —— 这样才是「一片都放不下」。
    # 上一版写 100,那时代码遇到放不下的就 `break`,所以 100 也是 0 片。
    # 改成 `continue`(跳过大的继续看小的)之后 100 能放下 55 那片 ——
    # **行为改进让这个夹具过期了**,而它过期的方式是「判据不再成立」,是对的红。
    # (`限片=1, 预算=40` 仍然通过配置校验:40 ≥ 1×20。)
    ib2 = 摆索引(c, org, proj, kb, k=12, 预算=40, 限片=1)
跑worker()
with eng.connect() as c:
    # ⚠️ 100 token **连一片都放不下**(真片段 min 15 / avg 92 / max 327),
    # 而那该**当场报**而不是返回 0 片 ——
    # 「检索返回 0 片」和「知识库里没有相关内容」在界面上长得一模一样。
    # (这一条是上一版测试跑出来的:它选了 0 片而判据说「被预算卡住 ✅」,
    #  技术上没错,但那个结果对用的人是无用且误导的。)
    ck("预算连一片都放不下 → **抛,不返回空结果**"
       "(0 片和「知识库里没有」在界面上长得一样)",
       _抛(lambda: RT.检索(c, 项目=proj, 构建id=ib2, 问题="差评", 要精排=False)))

# 预算够放几片但不够放满 4 片 —— 这才是「被预算卡住」该测的场景
with eng.begin() as c:
    ib2b = 摆索引(c, org, proj, kb, k=12, 预算=200, 限片=4)
跑worker()
with eng.connect() as c:
    链2 = RT.检索(c, 项目=proj, 构建id=ib2b, 问题="差评", 要精排=False)
ck("预算 200 token / 限片 4 → **被预算卡住而不是条数**(选片 1-3 之间)",
   0 < 链2["选了几片"] < 4 and "预算" in 链2["截断"],
   f"{链2['选了几片']} 片 · {链2['用了多少token']} token · {链2['截断']}")
ck("用掉的 token 不超预算", 链2["用了多少token"] <= 200, 链2["用了多少token"])
# ⚠️ 放不下的片段是**跳过并继续**,不是遇到就停 ——
# 按相关性排序时第 1 名恰好很长是很常见的,`break` 会因为一个大片段
# 丢掉后面所有能放的(实测过:260 预算下选了 0 片,而最小候选 55 token)。
# 而跳过**必须报出来**:「最相关的那条因为太大没进去」会静默发生。
ck("**因为太大被跳过的片段报出来了**"
   "(否则「最相关的那条没进去」会静默发生,而结果看起来正常)",
   链2["因为太大跳过的"] and "跳过说明" in 链2,
   f"跳过 {len(链2['因为太大跳过的'])} 片")
ck("跳过的那些带 token 数和证据串(要能看出是哪几条、为什么)",
   all("token" in x and "证据" in x for x in 链2["因为太大跳过的"]),
   链2["因为太大跳过的"][:1])
with eng.begin() as c:
    ib3 = 摆索引(c, org, proj, kb, k=12, 预算=100000, 限片=2)  # 条数卡得死
跑worker()
with eng.connect() as c:
    链3 = RT.检索(c, 项目=proj, 构建id=ib3, 问题="差评", 要精排=False)
ck("预算很大 / 限片 2 → **被条数卡住**",
   链3["选了几片"] == 2 and "条数" in 链3["截断"],
   f"{链3['选了几片']} 片 · {链3['截断']}")

print("\n▸ ③ 不满足前提的一律**抛,不降级**")
with eng.connect() as _c:
    ck("空问题 → 抛(空查询的向量会返回一批「离原点最近」的片段,看起来像正常结果)",
       _抛(lambda: RT.检索(_c, 项目=proj, 构建id=ib, 问题="   ")))
with eng.begin() as c:
    ib4 = 摆索引(c, org, proj, kb, 状态跑=False)      # 不派 job → 停在「排队中」
with eng.connect() as c:
    ck("索引还没「已就绪」→ 抛(**不在没建好的索引上检索**:"
       "结果不完整,而那和「知识库里就这么点」长得一样)",
       _抛(lambda: RT.检索(c, 项目=proj, 构建id=ib4, 问题="差评")))
    ck("构建 id 不存在 → 抛",
       _抛(lambda: RT.检索(c, 项目=proj, 构建id="ib_根本没有", 问题="差评")))
with eng.begin() as c:
    ib5 = 摆索引(c, org, proj, kb, modes=["hybrid"])
跑worker()
with eng.connect() as c:
    ck("配置要了 `hybrid` 而只实现了 vector → **抛,不静默退化**"
       "(退化会让人以为融合在生效)",
       _抛(lambda: RT.检索(c, 项目=proj, 构建id=ib5, 问题="差评", 要精排=False)))

# ── 还原 ──────────────────────────────────────────────────────────
with eng.begin() as c:
    # ⚠️ **先删所有引用待删向量的成员,不只是这个文件建的那些构建的。**
    # 向量的身份是 (文本, 模型),**跨构建共享** —— 那正是复用的机制,
    # 所以别的构建(手工试跑留下的)也引用着同一批向量。
    # ⚠️⚠️ 这段和 `test_index_build.py` 的清理**是一样的道理,写了两份** ——
    # 我在那个文件里修好之后,在这个文件里又写了个窄版本(只删自己的),
    # 于是又撞了一次 ForeignKeyViolation。
    # **一个坑在一个文件里修好,不会自动在另一个文件里修好。**
    # 第三个文件出现时该提成共用的 helper;现在把重复写明,免得它们各自演化。
    c.execute(text("""delete from index_members where project_id=:p and embedding_id in
                      (select id from embeddings where project_id=:p)"""), {"p": proj})
    for ib_, rc_ in 建的:
        c.execute(text("delete from index_members where project_id=:p and index_build_id=:b"),
                  {"p": proj, "b": ib_})
    c.execute(text("""delete from job_events where project_id=:p and job_id in
                      (select id from jobs where project_id=:p and type='index_build')"""),
              {"p": proj})
    c.execute(text("delete from jobs where project_id=:p and type='index_build'"),
              {"p": proj})
    for ib_, rc_ in 建的:
        c.execute(text("delete from index_builds where project_id=:p and id=:i"),
                  {"p": proj, "i": ib_})
        c.execute(text("delete from retrieval_config_versions where project_id=:p and id=:i"),
                  {"p": proj, "i": rc_})
    c.execute(text("delete from embeddings where project_id=:p"), {"p": proj})
with eng.connect() as c:
    剩 = c.execute(text("""select (select count(*) from index_builds where project_id=:p),
                                 (select count(*) from embeddings where project_id=:p),
                                 (select count(*) from chunks where project_id=:p)"""),
                  {"p": proj}).first()
ck("跑完清干净,**而片段一个没少**", 剩[0] == 0 and 剩[1] == 0 and 剩[2] == 片段数,
   f"构建 {剩[0]} · 向量 {剩[1]} · 片段 {剩[2]}")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
