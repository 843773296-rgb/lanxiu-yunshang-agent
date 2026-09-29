#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用与发布(规格 §17.4-9;实施必须遵守第 1、2 条)。

    GET   /applications                  应用列表(**带各环境现在指着哪一版**)
    POST  /applications                  建应用
    PATCH /applications/{id}/draft       改候选配置(乐观锁)
    POST  /applications/{id}/releases    出发布候选(**冻结依赖**)
    POST  /releases/{id}/reviews         审核发布
    POST  /releases/{id}/deploy          发布(**切环境指针**)
    POST  /applications/{id}/rollbacks   回滚到历史清单
    POST  /applications/{id}/runs        按环境绑定执行

## 这一块回答的是整条链上最后一个问题:**现在给用户用的到底是哪一版**

前面几块回答的是「有哪些版本」(Prompt 版本、索引构建、模型产物……),
而它们合起来才是一次真实调用的行为。**发布清单就是那个「合起来」**,
环境指针则回答「哪一份清单正在服务」。

没有这一块,前面所有版本管理都停在「我们存了很多版本」,
而**「上周二在跑哪一版」答不出来** —— 那正是出事时唯一要问的问题。

## ⚠️ 四条硬规矩,以及它们各自靠什么成立

| 规矩 | 靠什么 |
|---|---|
| 清单里全是确切版本,不许「用最新的那个」 | **表结构**:每项依赖都是一列版本 id,`latest` 没地方放 |
| 生产只认审核过的清单 | 判据 `release.可以发布吗`,而且判的是「审的是不是**这一份**」 |
| 指针变更原子 | **事务 + 乐观锁**,不是判据 |
| 回滚是一次新的部署动作 | 只动指针 + 新记一行,**历史清单一个字不改** |

第一条最值得说:它**已经在表结构上保证了**,所以判据只需要管「这一项填没填」。
**能用约束表达的不要用判据表达** —— 判据只在有人调用它时生效,
而一个放不下「最新」的列,任何时候都放不下。

## ⚠️ 「审过」不是一个布尔

它得说得出**谁审的、审的是哪一份**。审完之后清单再变过,那次审核就作废 ——
和人工审批那边「批准之后内容有没有再变过」是同一条判据。
只存一个 `approved=true` 的话,**改完再发**这条路就是通的,而且不报错。
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
import release as RL
import states as ST

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _哈希(d):
    return hashlib.sha256(_json.dumps(d, ensure_ascii=False, sort_keys=True)
                          .encode()).hexdigest()[:32]


def _审计(c, me, action, target, result="ok", reason=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, reason, created_at, created_by)
        values (:i,:o,:p,:a,:ac,cast(:t as jsonb),:e, now(), :r, :rs, now(), :a)
    """), {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id,
           "ac": action, "t": _json.dumps(target, ensure_ascii=False),
           "e": os.environ.get("APP_ENV", "development"), "r": result, "rs": reason})


def _取草稿(c, project_id, aid):
    r = c.execute(text("""select id, definition, revision from application_drafts
                         where project_id=:p and application_id=:a"""),
                  {"p": project_id, "a": aid}).mappings().first()
    return dict(r) if r else None


def _指针们(c, project_id, aid):
    return {r["environment"]: dict(r) for r in c.execute(text("""
        select environment, release_manifest_id, revision
          from environment_bindings
         where project_id=:p and application_id=:a"""),
        {"p": project_id, "a": aid}).mappings()}


# ── 应用 ────────────────────────────────────────────────────────
@router.get(前缀 + "/applications")
def 应用列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """列表。**每一行都带上各环境现在指着哪一份清单** ——

    「有哪些应用」这个问题本身没什么用,**有用的是「哪一版在给用户跑」**。
    """
    with 连接() as c:
        apps = [dict(r) for r in c.execute(text("""
            select id, name, pipeline_type, revision, created_at
              from applications where project_id=:p and archived_at is null
             order by created_at"""), {"p": project_id}).mappings()]
        出 = []
        for a in apps:
            指 = _指针们(c, project_id, a["id"])
            草 = _取草稿(c, project_id, a["id"])
            问 = RL.可以出候选吗(流水线=a["pipeline_type"],
                            草稿=(草 or {}).get("definition") or {})
            出.append({
                "id": a["id"], "名字": a["name"], "流水线": a["pipeline_type"],
                "revision": a["revision"],
                "各环境指着哪一版": {e: v["release_manifest_id"] for e, v in 指.items()} or None,
                "候选能出清单吗": not 问,
                "候选还差什么": 问 or None,
            })
    return {"条数": len(出), "应用": 出,
            "note": ("`各环境指着哪一版` 为空 = **这个应用还没有任何一版在跑** —— "
                     "和「跑的是最新的那一版」完全不是一回事")}


@router.post(前缀 + "/applications", status_code=201)
async def 建应用(project_id: str, request: Request,
           me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    体 = await request.json()
    名 = (体.get("名字") or 体.get("name") or "").strip()
    流水线 = (体.get("流水线") or 体.get("pipeline_type") or "").strip()
    坏 = {}
    if not 名: 坏["名字"] = "必填"
    if 流水线 not in RL.流水线们:
        坏["流水线"] = f"只收 {list(RL.流水线们)}(首版只有这两种)"
    if 坏:
        raise _错(422, "VALIDATION", "字段不合格", "名字和流水线都要给", field_errors=坏)
    aid = _新id("app")
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        c.execute(text("""insert into applications
            (id, organization_id, project_id, name, pipeline_type,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n,:t, now(), :by, now(), 1)"""),
                  {"i": aid, "o": org, "p": project_id, "n": 名, "t": 流水线,
                   "by": me.user_id})
        # 顺手建一份空候选 —— 没有它的话 PATCH 要先处理「草稿不存在」,
        # 而一个应用天然就该有一份候选(哪怕是空的)。
        c.execute(text("""insert into application_drafts
            (id, organization_id, project_id, application_id, definition,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:a, cast('{}' as jsonb), now(), :by, now(), 1)"""),
                  {"i": _新id("appd"), "o": org, "p": project_id, "a": aid,
                   "by": me.user_id})
        _审计(c, me, "application.create", {"application_id": aid, "name": 名})
    return {"id": aid, "名字": 名, "流水线": 流水线,
            "note": (f"候选配置已经建好(空的)。这条流水线**少不了**这几项:"
                     f"{[dict(RL.依赖项)[k] for k in RL.流水线必填[流水线]]}")}


@router.patch(前缀 + "/applications/{aid}/draft")
async def 改候选配置(project_id: str, aid: str, request: Request,
               if_match: str = Header(default=None, alias="If-Match"),
               me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """改候选里挑的依赖版本。**要 If-Match**。

    ⚠️ **只收 `依赖项` 里登记过的键。** 收任意键的话,
    候选里会长出一些发布清单根本不认识的字段 ——
    而它们在候选上看着像配置,到出清单那一刻**一声不响地消失**。
    """
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match",
                  "把候选的 revision 放进 If-Match 头再提交")
    体 = await request.json()
    合法 = {k for k, _ in RL.依赖项}
    改 = {k: v for k, v in 体.items() if k in 合法}
    野 = sorted(set(体) - 合法)
    if not 改:
        raise _错(422, "VALIDATION", "没有要改的依赖项",
                  f"可改的是 {sorted(合法)}",
                  field_errors={"不认识的键": 野} if 野 else None)
    with 事务() as c:
        d = c.execute(text("""select id, definition, revision from application_drafts
                             where project_id=:p and application_id=:a for update"""),
                      {"p": project_id, "a": aid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", f"没有应用 {aid} 的候选", "回列表重新进入")
        if str(d["revision"]) != str(if_match):
            raise _错(409, "REVISION_CONFLICT",
                      f"这份候选已经被改过(你拿的是 {if_match},现在是 {d['revision']})",
                      "刷新看一眼别人改了什么再合并;**不要直接覆盖**")
        新定义 = dict(d["definition"] or {})
        新定义.update({k: (str(v).strip() or None) for k, v in 改.items()})
        新rev = int(d["revision"]) + 1
        c.execute(text("""update application_drafts
                             set definition=cast(:d as jsonb), revision=:r,
                                 updated_at=now()
                           where project_id=:p and id=:i"""),
                  {"d": _json.dumps(新定义, ensure_ascii=False), "r": 新rev,
                   "p": project_id, "i": d["id"]})
        流水线 = c.execute(text("select pipeline_type from applications "
                             "where project_id=:p and id=:i"),
                        {"p": project_id, "i": aid}).scalar()
    问 = RL.可以出候选吗(流水线=流水线, 草稿=新定义)
    return {"application_id": aid, "revision": 新rev, "改了": sorted(改),
            "不认识的键": 野 or None,
            "现在能出清单吗": not 问, "还差什么": 问 or None,
            "note": ("**改候选不影响正在跑的那一版** —— 候选和发布清单是两张表,"
                     "要切生产得出清单、审核、再发布")}


# ── 发布清单 ────────────────────────────────────────────────────
@router.post(前缀 + "/applications/{aid}/releases", status_code=201)
async def 出发布候选(project_id: str, aid: str,
              me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """把候选**冻结**成一份发布清单。

    ⚠️ 冻结的意思是:清单里每一项都是**确切版本**,而且**写下就不许改**。
    之后改候选不会动到这一份 —— 这正是「上周二在跑哪一版」答得出来的原因。
    """
    with 事务() as c:
        app = c.execute(text("""select id, pipeline_type, organization_id
                              from applications
                             where project_id=:p and id=:i and archived_at is null"""),
                        {"p": project_id, "i": aid}).mappings().first()
        if not app:
            raise _错(404, "NOT_FOUND", f"没有应用 {aid}", "回列表重新进入")
        草 = _取草稿(c, project_id, aid)
        定义 = (草 or {}).get("definition") or {}
        问 = RL.可以出候选吗(流水线=app["pipeline_type"], 草稿=定义)
        if 问:
            raise _错(422, "CANNOT_RELEASE", "这份候选还不能出清单",
                      "按下面每一条补齐再来", field_errors={"闸": 问})
        内容 = {k: (定义.get(k) or None) for k, _ in RL.依赖项}
        哈 = _哈希({"应用": aid, "流水线": app["pipeline_type"], **内容})
        老 = c.execute(text("""select id from release_manifests
                             where project_id=:p and application_id=:a
                               and content_hash=:h"""),
                       {"p": project_id, "a": aid, "h": 哈}).scalar()
        if 老:
            # ⚠️ 同样的依赖组合冻两次 → **同一份清单**,不新建。
            # 两个 id 指着同一组版本之后,「那次发布用的是哪一份」
            # 就有了两个同样成立的答案。
            return {"id": 老, "新建了吗": False,
                    "note": "**依赖组合和这一份完全一样,所以没有新建** —— "
                            "同样的内容两个清单号,「发布的是哪一份」就有两个答案"}
        rid = _新id("rel")
        c.execute(text("""insert into release_manifests
            (id, organization_id, project_id, application_id, prompt_version_id,
             connection_version_id, index_build_id, retrieval_config_version_id,
             model_artifact_id, evaluation_id, content_hash,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:a,:pv,:cv,:ib,:rc,:ma,:ev,:h, now(), :by, now(), 1)"""),
                  {"i": rid, "o": app["organization_id"], "p": project_id, "a": aid,
                   "pv": 内容["prompt_version_id"], "cv": 内容["connection_version_id"],
                   "ib": 内容["index_build_id"],
                   "rc": 内容["retrieval_config_version_id"],
                   "ma": 内容["model_artifact_id"], "ev": 内容["evaluation_id"],
                   "h": 哈, "by": me.user_id})
        _审计(c, me, "release.create", {"release_id": rid, "application_id": aid})
    return {"id": rid, "新建了吗": True, "内容哈希": 哈, "清单": 内容,
            "note": ("**写下就不许改** —— 之后改候选不会动到这一份。"
                     "要发到生产还得先审核,而审核认的是这个内容哈希")}


@router.post(前缀 + "/releases/{rid}/reviews", status_code=201)
async def 审核发布(project_id: str, rid: str, request: Request,
             me: 身份 = Depends(要权限("生产审核/发布/回滚"))):
    """审核一份发布清单。入参 `{结论: 通过/驳回, 理由?}`。

    ⚠️ **审核记的是「审的哪一份内容」,不是一个布尔。**
    存成 `approved=true` 的话,「改完再发」这条路就是通的,而且不报错。
    """
    体 = await request.json()
    结论 = (体.get("结论") or 体.get("verdict") or "").strip()
    理由 = (体.get("理由") or 体.get("reason") or "").strip() or None
    if 结论 not in ("通过", "驳回"):
        raise _错(422, "VALIDATION", "结论只收「通过」或「驳回」",
                  "**不收任意字符串**:一个拼错的结论会自成一档",
                  field_errors={"结论": "通过 / 驳回"})
    with 事务() as c:
        r = c.execute(text("""select id, content_hash, application_id
                             from release_manifests
                            where project_id=:p and id=:i for update"""),
                      {"p": project_id, "i": rid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", f"没有发布清单 {rid}", "回应用详情重新进入")
        审核 = {"审核人": me.user_id, "结论": 结论, "理由": 理由,
              "审的哈希": r["content_hash"]}
        c.execute(text("""update release_manifests
                             set approval=cast(:a as jsonb), updated_at=now()
                           where project_id=:p and id=:i"""),
                  {"a": _json.dumps(审核, ensure_ascii=False),
                   "p": project_id, "i": rid})
        _审计(c, me, "release.review", {"release_id": rid, "结论": 结论}, reason=理由)
    return {"id": rid, "结论": 结论, "审的哈希": r["content_hash"],
            "note": ("**记的是「审的哪一份内容」** —— 这份清单是不可变的,"
                     "所以这次审核对它永远算数;而如果有人另出一份新清单,"
                     "那一份要重新审")}


@router.post(前缀 + "/releases/{rid}/deploy", status_code=202)
async def 发布(project_id: str, rid: str, request: Request,
           idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
           if_match: str = Header(default=None, alias="If-Match"),
           me: 身份 = Depends(要权限("生产审核/发布/回滚"))):
    """把环境指针切到这份清单。**指针变更原子**。

    ⚠️ 切生产要 `If-Match`(当前指针的 revision)——
    两个人同时发布不同版本时,后到的那个会**悄悄覆盖**先到的,
    而两边都收到「成功」。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "发布是异步 + 对外的动作,超时重发是常态")
    体 = await request.json()
    环境 = (体.get("环境") or 体.get("environment") or "").strip()
    with 事务() as c:
        r = c.execute(text("""select * from release_manifests
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": rid}).mappings().first()
        r = dict(r) if r else None
        审核 = (r or {}).get("approval")
        if isinstance(审核, str):
            try: 审核 = _json.loads(审核)
            except Exception: 审核 = None
        # 这份清单钉的那个连接配置版本,探过 capabilities 没有。
        # ⚠️ **三值**:查不到那一行 → None(不判这一条),而不是 False ——
        # 「没有这个版本」和「有但没探过」下一步不同。
        探过 = None
        if r and r.get("connection_version_id"):
            cv = c.execute(text("""select capabilities from connection_versions
                                 where project_id=:p and id=:i"""),
                           {"p": project_id,
                            "i": r["connection_version_id"]}).mappings().first()
            if cv:
                import connections as _CN
                探过 = _CN.探过吗(dict(cv))
        问 = RL.可以发布吗(环境=环境, 清单=r, 审核=审核, 连接探过吗=探过)
        if 问:
            _审计(c, me, "release.deploy.blocked",
                  {"release_id": rid, "environment": 环境},
                  result="blocked", reason="; ".join(问)[:400])
            拦了 = 问
        else:
            拦了 = None
            老 = c.execute(text("""select id, release_manifest_id, revision
                                 from environment_bindings
                                where project_id=:p and application_id=:a
                                  and environment=:e for update"""),
                           {"p": project_id, "a": r["application_id"],
                            "e": 环境}).mappings().first()
            if 老:
                if if_match and str(老["revision"]) != str(if_match):
                    raise _错(409, "REVISION_CONFLICT",
                              f"这个环境的指针已经被切过了"
                              f"(你拿的是 {if_match},现在是 {老['revision']})",
                              "刷新看一眼现在指着哪一版;**不要直接覆盖**")
                c.execute(text("""update environment_bindings
                                     set release_manifest_id=:r, revision=revision+1,
                                         updated_at=now()
                                   where project_id=:p and id=:i"""),
                          {"r": rid, "p": project_id, "i": 老["id"]})
                从 = 老["release_manifest_id"]
            else:
                c.execute(text("""insert into environment_bindings
                    (id, organization_id, project_id, application_id, environment,
                     release_manifest_id, created_at, created_by, updated_at, revision)
                    values (:i,:o,:p,:a,:e,:r, now(), :by, now(), 1)"""),
                          {"i": _新id("envb"), "o": r["organization_id"],
                           "p": project_id, "a": r["application_id"], "e": 环境,
                           "r": rid, "by": me.user_id})
                从 = None
            _审计(c, me, "release.deploy",
                  {"release_id": rid, "environment": 环境, "从": 从})
    if 拦了:
        raise _错(422, "CANNOT_DEPLOY", "这份清单不能发到这个环境",
                  "按下面每一条处理。**被拦这件事已经记进审计**",
                  field_errors={"闸": 拦了})
    return {"release_id": rid, "环境": 环境, "从": 从, "到": rid,
            "note": ("**指针切换在一个事务里完成** —— 半切的后果是"
                     "一部分流量拿到新版、一部分拿到旧版,而两边都不报错")}


# ── 回滚 ────────────────────────────────────────────────────────
@router.post(前缀 + "/applications/{aid}/rollbacks", status_code=202)
async def 回滚(project_id: str, aid: str, request: Request,
           idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
           me: 身份 = Depends(要权限("生产审核/发布/回滚"))):
    """回滚到一份历史清单。

    ⚠️ **回滚是一次新的部署动作,不是把历史改回去。**
    改历史的后果很具体:「上周二在跑哪一版」会变成**现在这一版** ——
    而那正是回滚之后最需要问的问题。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "回滚是异步 + 对外的动作")
    体 = await request.json()
    目标 = (体.get("回到哪一版") or 体.get("release_manifest_id") or "").strip()
    环境 = (体.get("环境") or 体.get("environment") or "").strip()
    with 事务() as c:
        r = c.execute(text("""select id, application_id, organization_id
                             from release_manifests
                            where project_id=:p and id=:i and application_id=:a"""),
                      {"p": project_id, "i": 目标, "a": aid}).mappings().first()
        r = dict(r) if r else None
        指 = _指针们(c, project_id, aid).get(环境)
        问 = RL.可以回滚吗(目标清单=r, 当前指针=指)
        if 环境 not in RL.环境们:
            问 = [f"环境只收 {list(RL.环境们)},拿到 {环境!r}"] + 问
        if 问:
            raise _错(422, "CANNOT_ROLLBACK", "回滚不了",
                      "按下面每一条处理", field_errors={"闸": 问})
        从 = (指 or {}).get("release_manifest_id")
        if 指:
            c.execute(text("""update environment_bindings
                                 set release_manifest_id=:r, revision=revision+1,
                                     updated_at=now()
                               where project_id=:p and application_id=:a
                                 and environment=:e"""),
                      {"r": 目标, "p": project_id, "a": aid, "e": 环境})
        else:
            c.execute(text("""insert into environment_bindings
                (id, organization_id, project_id, application_id, environment,
                 release_manifest_id, created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:a,:e,:r, now(), :by, now(), 1)"""),
                      {"i": _新id("envb"), "o": r["organization_id"], "p": project_id,
                       "a": aid, "e": 环境, "r": 目标, "by": me.user_id})
        # **新记一行审计** —— 历史清单一个字都没动。
        _审计(c, me, "release.rollback",
              {"application_id": aid, "environment": 环境, "从": 从, "到": 目标})
    return {"application_id": aid, "环境": 环境, "从": 从, "到": 目标,
            "note": ("**这是一次新的部署动作,历史清单一个字都没改** —— "
                     "改历史的话,「上周二在跑哪一版」会变成现在这一版,"
                     "而那正是回滚之后最需要问的问题")}


# ── 按环境绑定执行 ──────────────────────────────────────────────
@router.post(前缀 + "/applications/{aid}/runs", status_code=202)
async def 按环境执行(project_id: str, aid: str, request: Request,
              idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
              me: 身份 = Depends(要权限("查看有权配置"))):
    """按**环境指针**跑一次。入参 `{环境, 输入}`。

    ⚠️ **版本由环境指针解析,不收调用方传的版本号。**
    允许调用方指定版本的话,「这次跑用的是哪一版」就变成了调用方说了算,
    而线上出问题时**查到的那一版可能根本不是当时跑的那一版**。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "执行是异步动作,超时重发是常态")
    体 = await request.json()
    环境 = (体.get("环境") or 体.get("environment") or "").strip()
    输入 = 体.get("输入") if "输入" in 体 else 体.get("input")
    野 = sorted(set(体) & {"release_manifest_id", "版本", "prompt_version_id"})
    if 野:
        raise _错(422, "VERSION_NOT_ACCEPTED",
                  f"这个接口**不收版本号**({野})",
                  "版本由环境指针解析 —— 允许调用方指定的话,"
                  "「这次跑用的是哪一版」就成了调用方说了算,"
                  "而线上出问题时查到的那一版可能不是当时跑的那一版",
                  field_errors={"不收的键": 野})
    if 环境 not in RL.环境们:
        raise _错(422, "VALIDATION", f"环境只收 {list(RL.环境们)}",
                  "**不给默认值**", field_errors={"环境": f"{list(RL.环境们)}"})
    with 事务() as c:
        老 = c.execute(text("""select id, status from execution_runs
                             where project_id=:p and idempotency_key=:k"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            return {"id": 老["id"], "status": 老["status"], "新建了吗": False,
                    "note": "**同一个幂等键 → 返回原运行,没有跑第二次**"}
        指 = _指针们(c, project_id, aid).get(环境)
        if not 指 or not 指.get("release_manifest_id"):
            # ⚠️ **不回落到「最新的那一版」。** 那正是规格第 2 条禁止的事:
            # 「不把任意模块的最新版本静默用于生产」。
            raise _错(422, "NO_BINDING",
                      f"应用 {aid} 在「{环境}」上**还没有任何一版在跑**",
                      "先发布一份清单到这个环境。"
                      "⚠️ **不会自动用最新的那一版** —— 静默用最新是规格明令禁止的:"
                      "那样「跑的是哪一版」取决于谁最后发了个新版本",
                      field_errors={"环境": 环境})
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        起点 = ST.找("execution_run")["起点"]
        rid = _新id("run")
        c.execute(text("""insert into execution_runs
            (id, organization_id, project_id, kind, release_ref, environment,
             input_snapshot, status, principal, idempotency_key,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'application', cast(:rel as jsonb), :env,
                    cast(:inp as jsonb), :st, :who, :k, now(), :who, now(), 1)"""),
                  {"i": rid, "o": org, "p": project_id,
                   # ⚠️ `release_ref` 是 **JSONB**,不是 TEXT。
                   # 后缀约定 `_ref → TEXT` 在这里被**显式覆盖**成 JSONB
                   # (`fieldtypes.显式类型` 里点着名),而我没查就塞了裸串 ——
                   # **今天第六次「JSONB 塞裸串」**,而且只在这一条路径上炸。
                   # 形状跟着别处走:`workflows_api` 读的是 `definition_ref->>'id'`。
                   "rel": _json.dumps({"id": 指["release_manifest_id"],
                                       "kind": "release_manifest"},
                                      ensure_ascii=False),
                   "env": 环境,
                   "inp": _json.dumps({"输入": 输入}, ensure_ascii=False),
                   "st": 起点, "who": me.user_id, "k": idempotency_key})
        _审计(c, me, "application.run",
              {"application_id": aid, "environment": 环境,
               "release_id": 指["release_manifest_id"], "run_id": rid})
    return {"id": rid, "status": 起点, "新建了吗": True,
            "环境": 环境, "用的哪一版": 指["release_manifest_id"],
            "note": ("**用的哪一版记在这次运行上了**(`release_ref`)—— "
                     "之后指针再切,这次运行仍然说得出它当时跑的是哪一份")}
