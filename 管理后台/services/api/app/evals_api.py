#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测与片段候选(规格 §18)。

    POST /evaluations                      建评测(**候选和基线都要给**)
    POST /evaluations/{id}/reviews         人工复核(**不许改原始结果**)
    POST /document-versions/{id}/revisions 改片段(出新候选)

## ⚠️ 一、没有基线的分数不能当结论

契约原话:**「候选和基线都要给 —— 没有基线的分数不能当结论」**。

一个「84 分」单独放着回答不了任何问题:它是变好了还是变差了?
而人看到一个分数,**一定会在心里跟某个东西比** ——
不给基线的话,他比的是他记忆里那个数,而那个数常常是错的。

## ⚠️ 二、复核是**新增一条**,不是改掉原来那条

§18:「**原始结果不被复核覆盖**」。所以复核写的是一条**新的分数**,
并且用 `supersedes_score_id` 指向被它取代的那条 —— 旧那条一个字不动。

覆盖的后果很具体:**「判分器当时给了多少」永远答不出来了**,
而那正是「判分器准不准」这个问题唯一的数据来源。
> 一旦把判分器的输出改成人的结论,你就再也没法评估判分器了。

`evals.有效分数()` 早就按这个口径算(被 supersedes 指过的不算,
**而且不靠时间戳排序** —— 时间戳会撞、会漂,指针不会)。

## ⚠️ 三、改片段改的是**候选**

契约原话:「**已建好的索引引用的是确切片段版本,不会被这一改动到**」。

所以这条接口出的是**新的文档版本**,旧版本原样留着 ——
索引里引用的是旧那一版,它照样能检索、照样能复现。
原地改的话,**昨天那次检索为什么召回这一条,今天就解释不了了**。
"""
import hashlib
import json as _json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import evals as EV

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _哈希(x):
    return hashlib.sha256(_json.dumps(x, ensure_ascii=False, sort_keys=True)
                          .encode()).hexdigest()[:32]


def _审计(c, me, action, target, reason=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, reason, created_at, created_by)
        values (:i,:o,:p,:a,:ac,cast(:t as jsonb),:e, now(), 'ok', :rs, now(), :a)
    """), {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id,
           "ac": action, "t": _json.dumps(target, ensure_ascii=False),
           "e": os.environ.get("APP_ENV", "development"), "rs": reason})


# ── 建评测 ──────────────────────────────────────────────────────
@router.post(前缀 + "/evaluations", status_code=202)
async def 建评测(project_id: str, request: Request,
           idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
           me: 身份 = Depends(要权限("运行评测"))):
    """建一次评测。入参 `{候选, 基线, 数据集版本, 判据版本}`。

    ⚠️ **候选和基线都要给** —— 没有基线的分数不能当结论。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "评测是异步动作,而且要花钱 —— 超时重发一次就是再跑一遍题")
    体 = await request.json()
    候选 = (体.get("候选") or 体.get("candidate_ref") or "").strip()
    基线 = (体.get("基线") or 体.get("baseline_ref") or "").strip()
    版本 = (体.get("数据集版本") or 体.get("dataset_version_id") or "").strip()
    判据 = (体.get("判据版本") or 体.get("scorer_version") or "").strip()
    坏 = {}
    if not 候选: 坏["候选"] = "必填"
    if not 基线:
        坏["基线"] = ("必填 —— **没有基线的分数不能当结论**。"
                   "一个「84 分」单独放着回答不了任何问题:它是变好了还是变差了?"
                   "而人看到一个分数一定会在心里跟某个东西比,"
                   "不给基线的话,他比的是他记忆里那个数")
    if not 版本:
        坏["数据集版本"] = ("必填,而且要是**冻结过的版本** —— "
                      "拿活数据跑出来的分数,下次跑的时候题已经变了")
    if not 判据: 坏["判据版本"] = "必填 —— 换了判据的两轮不可比"
    if 坏:
        raise _错(422, "VALIDATION", "这次评测建不了",
                  "候选、基线、数据集版本、判据版本,四个都要在场",
                  field_errors=坏)
    with 事务() as c:
        老 = c.execute(text("""select id, status from evaluations
                             where project_id=:p
                               and candidate_ref->>'幂等键' = :k limit 1"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            return {"id": 老["id"], "status": 老["status"], "新建了吗": False,
                    "note": "**同一个幂等键 → 返回原评测,没有再跑一遍题**"}
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        v = c.execute(text("""select id, frozen_samples from dataset_versions
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": 版本}).mappings().first()
        if not v:
            raise _错(422, "DATASET_VERSION_NOT_FOUND", f"没有数据集版本 {版本}",
                      "先冻一版 —— **不静默用「当前样本」**:"
                      "那样下次跑的时候题已经变了,而两次的分数看起来可比")
        eid = _新id("ev")
        # ⚠️ `candidate_ref` 是 **JSONB**(这个仓库为「JSONB 塞裸串」栽过八次),
        # 顺手把幂等键放进去 —— 这张表没有 idempotency_key 列。
        c.execute(text("""insert into evaluations
            (id, organization_id, project_id, candidate_ref, baseline_ref,
             dataset_version_id, scorer_version, status,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p, cast(:cand as jsonb), cast(:base as jsonb),
                    :dv,:sc,'排队中', now(), :by, now(), 1)"""),
                  {"i": eid, "o": org, "p": project_id,
                   "cand": _json.dumps({"ref": 候选, "幂等键": idempotency_key},
                                       ensure_ascii=False),
                   "base": _json.dumps({"ref": 基线}, ensure_ascii=False),
                   "dv": 版本, "sc": 判据, "by": me.user_id})
        _审计(c, me, "evaluation.create",
              {"evaluation_id": eid, "candidate": 候选, "baseline": 基线,
               "dataset_version_id": 版本, "scorer_version": 判据})
    return {"id": eid, "status": "排队中", "新建了吗": True,
            "候选": 候选, "基线": 基线, "数据集版本": 版本, "判据版本": 判据,
            "note": ("四个都在场了 —— **候选 + 基线 + 冻结的数据版本 + 判据版本**。"
                     "少任何一个,跑出来的分数都不能当结论。"
                     "⚠️ 跑完之后还要过 `可比吗()`:换了题或换了判据的两轮,"
                     "**并排两个不可比的数,读的人会算出一个差值**")}


# ── 人工复核 ────────────────────────────────────────────────────
@router.post(前缀 + "/evaluations/{eid}/reviews", status_code=201)
async def 人工复核(project_id: str, eid: str, request: Request,
             me: 身份 = Depends(要权限("运行评测"))):
    """人工复核一条评分。入参 `{评分项, 维度, 新分, 理由}`。

    ⚠️ **新增一条并指向被取代的那条,不改原来那条**(§18「原始结果不被复核覆盖」)。
    覆盖的后果:**「判分器当时给了多少」永远答不出来了** ——
    而那正是「判分器准不准」这个问题唯一的数据来源。
    """
    体 = await request.json()
    项 = (体.get("评分项") or 体.get("evaluation_item_id") or "").strip()
    维度 = (体.get("维度") or 体.get("dimension") or "").strip()
    新分 = 体.get("新分") if "新分" in 体 else 体.get("value")
    理由 = (体.get("理由") or 体.get("rationale") or "").strip()
    坏 = {}
    if not 项: 坏["评分项"] = "必填"
    if not 维度: 坏["维度"] = "必填 —— 一条分数不说清是哪个维度,合并的时候没法对齐"
    if 新分 is None:
        坏["新分"] = ("必填。**判不了就别写这条复核** —— "
                   "写一条 value 为空的复核,会让它在「有效分数」里占一个位置,"
                   "而那个位置本来该留给判分器那条")
    if not 理由:
        坏["理由"] = ("必填 —— 复核是**推翻机器的判断**,"
                   "而推翻的理由是下一次改判据的唯一线索")
    if 坏:
        raise _错(422, "VALIDATION", "这条复核写不了", "按每一条补齐",
                  field_errors=坏)
    with 事务() as c:
        ev = c.execute(text("""select id from evaluations
                             where project_id=:p and id=:i"""),
                       {"p": project_id, "i": eid}).scalar()
        if not ev:
            raise _错(404, "NOT_FOUND", f"没有这次评测 {eid}", "回评测列表重新进入")
        老 = c.execute(text("""select id, value, source from scores
                             where project_id=:p and evaluation_item_id=:it
                               and dimension=:d and supersedes_score_id is null
                             order by at desc limit 1"""),
                       {"p": project_id, "it": 项, "d": 维度}).mappings().first()
        if not 老:
            raise _错(422, "NO_SCORE_TO_REVIEW",
                      f"评分项 {项} 的「{维度}」维度上没有可复核的分数",
                      "确认评分项和维度;**不给一条凭空的人工分** —— "
                      "复核的意思是「推翻某一条」,没有那一条就没有可推翻的")
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        sid = _新id("sc")
        c.execute(text("""insert into scores
            (id, organization_id, project_id, evaluation_item_id, dimension,
             value, value_known, source, rationale, "by", at,
             supersedes_score_id, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:it,:d,:v, true, '人工', :r, :by, now(),
                    :sup, now(), :by, now(), 1)"""),
                  {"i": sid, "o": org, "p": project_id, "it": 项, "d": 维度,
                   "v": 新分, "r": 理由, "by": me.user_id, "sup": 老["id"]})
        _审计(c, me, "evaluation.review",
              {"evaluation_id": eid, "score_id": sid,
               "supersedes_score_id": 老["id"], "dimension": 维度},
              reason=理由[:300])
    return {"id": sid, "取代了": 老["id"], "维度": 维度, "新分": 新分,
            "原来那条还在吗": True,
            "note": ("**原来那条一个字没动**(§18:原始结果不被复核覆盖)—— "
                     "覆盖的话,「判分器当时给了多少」永远答不出来了,"
                     "而那正是「判分器准不准」唯一的数据来源。"
                     "⚠️ `evals.有效分数()` 按 `supersedes_score_id` 算,"
                     "**不靠时间戳排序** —— 时间戳会撞、会漂,指针不会")}


# ── 改片段(出新候选)──────────────────────────────────────────────
@router.post(前缀 + "/document-versions/{dvid}/revisions", status_code=201)
async def 改片段(project_id: str, dvid: str, request: Request,
           me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """基于某个文档版本出一个**新候选版本**。

    ⚠️ 改的是**候选**:已建好的索引引用的是**确切片段版本**,不会被这一改动到。
    原地改的话,**昨天那次检索为什么召回这一条,今天就解释不了了**。
    """
    体 = await request.json()
    说明 = (体.get("为什么改") or 体.get("note") or "").strip()
    新键 = (体.get("新对象键") or 体.get("object_key") or "").strip() or None
    if not 说明:
        raise _错(422, "VALIDATION", "「为什么改」必填",
                  "**出一个新候选是要花人去复核的** —— 不说为什么,复核的人只能靠猜",
                  field_errors={"为什么改": "必填"})
    with 事务() as c:
        老 = c.execute(text("""select * from document_versions
                             where project_id=:p and id=:i"""),
                       {"p": project_id, "i": dvid}).mappings().first()
        if not 老:
            raise _错(404, "NOT_FOUND", f"没有文档版本 {dvid}", "回知识库重新进入")
        老 = dict(老)
        # ⚠️ `index_members` **没有 `document_version_id`** —— 它挂的是 `chunk_id`,
        # 而「这一版被几个索引引用着」要经 `chunks` 绕一跳。
        # 第一版直接写了那个列名,当场 `UndefinedColumn`。
        # **今天「没查表结构就写 SQL」又一次** —— 而这一族今天已经有了判据
        # (`sql_columns_check` 查列名、`jsonb_cast_check` 查类型),
        # 只是它们都在**提交前**跑,拦不住我写的那一刻。
        用了几次 = c.execute(text("""select count(*) from index_members im
                                 join chunks ch on ch.project_id = im.project_id
                                              and ch.id = im.chunk_id
                                 where im.project_id=:p
                                   and ch.document_version_id=:i"""),
                          {"p": project_id, "i": dvid}).scalar() or 0
        新id = _新id("dv")
        来源 = dict(老.get("source_info") or {})
        来源.update({"从哪一版改的": dvid, "为什么改": 说明, "改的人": me.user_id})
        c.execute(text("""insert into document_versions
            (id, organization_id, project_id, document_id, object_key, content_hash,
             effective_at, source_info, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:d,:ok,:h, now(), cast(:si as jsonb),
                    now(), :by, now(), 1)"""),
                  {"i": 新id, "o": 老["organization_id"], "p": project_id,
                   "d": 老["document_id"], "ok": (新键 or 老["object_key"]),
                   "h": _哈希({"从": dvid, "说明": 说明, "键": 新键 or 老["object_key"]}),
                   "si": _json.dumps(来源, ensure_ascii=False), "by": me.user_id})
        _审计(c, me, "document_version.revise",
              {"document_id": 老["document_id"], "从": dvid, "到": 新id},
              reason=说明[:300])
    return {"id": 新id, "从哪一版改的": dvid,
            "旧那一版还被几个索引引用着": 用了几次,
            "note": ("**旧那一版一个字没动**,而且还被 "
                     f"{用了几次} 个索引成员引用着 —— 它照样能检索、照样能复现。"
                     "原地改的话,**昨天那次检索为什么召回这一条,今天就解释不了了**。"
                     "⚠️ 这是个**候选**:要让它生效,得重建索引")}
