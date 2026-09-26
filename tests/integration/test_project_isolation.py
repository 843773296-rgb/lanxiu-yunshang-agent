#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨项目引用:**真的去攻击它**,不是读一遍代码说「看起来挡住了」。

规格 §18:「跨对象引用使用包含项目/组织范围的外键或等效约束;
**仅靠前端传 project_id 不够**」。§19.1:「浏览器不能通过更改 ID 绕过授权」。

这两条声称的是**结构性保证**(做不到),不是约定(不该做)。而:

> **一条从没被攻击过的「结构性保证」,实际上仍然只是约定。**

所以这个文件做五次真实攻击,每一次都必须被 PostgreSQL 拒绝。
用完就把库还原 —— 攻击测试写脏了库不还原,下一轮的结论就不可信了。
"""
import os, sys, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))

from sqlalchemy import create_engine, text, insert
from sqlalchemy.exc import IntegrityError
import models as M

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)

过, 挂 = [], []
def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:120]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 新(前缀):
    return f"{前缀}_{uuid.uuid4().hex[:8]}"


def 摆两个项目(c):
    org = 新("org")
    c.execute(insert(M.表们["organizations"]).values(
        id=org, name="测试组织", status="active", created_at=text("now()")))
    a, b = 新("projA"), 新("projB")
    for p, n in ((a, "A 项目"), (b, "B 项目")):
        c.execute(insert(M.表们["projects"]).values(
            id=p, organization_id=org, name=n, status="active",
            created_at=text("now()")))
    return org, a, b


def 拒绝吗(c, 语句, **值):
    """跑一条该被拒的写入。返回 (被拒了吗, 数据库说了什么)。"""
    sp = c.begin_nested()
    try:
        c.execute(语句, 值) if 值 else c.execute(语句)
        sp.rollback()
        return False, "**写进去了** —— 这条边界没有成立"
    except IntegrityError as e:
        sp.rollback()
        return True, str(e.orig).split("\n")[0][:110]


with eng.begin() as c:
    org, A, B = 摆两个项目(c)
    T = M.表们

    # ── 攻击 1:在 B 项目下建 trace,却引用 A 项目的应用 ────────────
    appA = 新("app")
    c.execute(insert(T["applications"]).values(
        id=appA, organization_id=org, project_id=A, name="A 的应用",
        pipeline_type="prompt", created_at=text("now()")))
    # 注意:applications 的外键是 (project_id, id) → projects,
    # 所以下面这条的 project_id=B 会让 (B, appA) 在 applications 里找不到
    行, 说 = 拒绝吗(c, insert(T["traces"]).values(
        id=新("tr"), organization_id=org, project_id=B, application_id=appA,
        environment="dev", created_at=text("now()")))
    ck("拿 A 项目的应用 ID 在 B 项目下建 trace → 被拒", 行, 说)

    # ── 攻击 2:span 挂到别的项目的 trace 上 ──────────────────────
    trA = 新("tr")
    c.execute(insert(T["traces"]).values(
        id=trA, organization_id=org, project_id=A, application_id=appA,
        environment="dev", created_at=text("now()")))
    行, 说 = 拒绝吗(c, insert(T["spans"]).values(
        id=新("sp"), organization_id=org, project_id=B, trace_id=trA,
        stage="generate", created_at=text("now()")))
    ck("span 声称自己在 B 项目、却挂 A 项目的 trace → 被拒", 行, 说)

    # ── 攻击 3:评分挂到别的项目的评测条目上(两层子对象)──────────
    evA, itA = 新("ev"), 新("it")
    c.execute(insert(T["evaluations"]).values(
        id=evA, organization_id=org, project_id=A, status="queued",
        created_at=text("now()")))
    c.execute(insert(T["evaluation_items"]).values(
        id=itA, organization_id=org, project_id=A, evaluation_id=evA,
        created_at=text("now()")))
    行, 说 = 拒绝吗(c, insert(T["scores"]).values(
        id=新("sc"), organization_id=org, project_id=B, evaluation_item_id=itA,
        dimension="正确性", value=1, value_known=True, source="确定性规则",
        created_at=text("now()")))
    ck("评分跨项目挂到别人的评测条目上 → 被拒(两层子对象也挡得住)", 行, 说)

    # ── 攻击 4:项目本身不存在 ─────────────────────────────────────
    行, 说 = 拒绝吗(c, insert(T["traces"]).values(
        id=新("tr"), organization_id=org, project_id="根本没这个项目",
        application_id=appA, environment="dev", created_at=text("now()")))
    ck("编一个不存在的 project_id → 被拒", 行, 说)

    # ── 攻击 5:同一个幂等键提交两次训练 ───────────────────────────
    dsA, dvA = 新("ds"), 新("dv")
    c.execute(insert(T["datasets"]).values(
        id=dsA, organization_id=org, project_id=A, name="集", format="sft",
        purpose="train", created_at=text("now()")))
    c.execute(insert(T["dataset_versions"]).values(
        id=dvA, organization_id=org, project_id=A, dataset_id=dsA,
        content_hash="h1", sample_count=10, created_at=text("now()")))
    键 = "同一个幂等键"
    c.execute(insert(T["training_jobs"]).values(
        id=新("tj"), organization_id=org, project_id=A, dataset_version_id=dvA,
        base_model="m", objective="sft", param_update_method="lora",
        status="草稿", idempotency_key=键, created_at=text("now()")))
    行, 说 = 拒绝吗(c, insert(T["training_jobs"]).values(
        id=新("tj"), organization_id=org, project_id=A, dataset_version_id=dvA,
        base_model="m", objective="sft", param_update_method="lora",
        status="草稿", idempotency_key=键, created_at=text("now()")))
    ck("同一个幂等键提交两次训练 → 被拒(超时重发不会再烧一遍 GPU)", 行, 说)

    # ── 正向:同项目内引用必须放行 ────────────────────────────────
    # ⚠️ **这一条是必需的**:如果上面五条全被拒只是因为「什么都写不进去」,
    # 那这套测试什么都没证明。**光有负向没有正向,红和绿分不开。**
    好 = True
    try:
        c.execute(insert(T["spans"]).values(
            id=新("sp"), organization_id=org, project_id=A, trace_id=trA,
            stage="generate", created_at=text("now()")))
    except IntegrityError as e:
        好, 说 = False, str(e.orig).split("\n")[0][:110]
    ck("同项目内正常引用 → 放行(否则上面五条只证明了「什么都写不进去」)", 好,
       "" if 好 else 说)

    # ── 还原 ────────────────────────────────────────────────────
    # 整个 with 块是一个事务,最后主动回滚 —— **攻击测试不许留下脏数据**
    c.rollback()

with eng.connect() as c:
    残 = c.execute(text("select count(*) from organizations")).scalar()
ck("跑完库里没留下测试数据(攻击测试写脏了不还原,下一轮结论就不可信)", 残 == 0, f"organizations={残}")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
sys.exit(1 if 挂 else 0)
