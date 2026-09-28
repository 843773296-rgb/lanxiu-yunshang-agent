#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微调训练链(规格 §17.4):训练任务 / 模型产物 / 部署。

    GET  /training-jobs              训练任务列表
    POST /training-jobs              提交训练(**幂等键是硬要求**)
    GET  /training-jobs/{id}         训练详情
    POST /training-jobs/{id}/cancel  **请求取消**,不是取消
    GET  /model-artifacts            产物列表
    POST /model-artifacts            登记产物(**校验后才能标可用**)
    POST /deployments                部署产物

## 这一整块的骨架是规格开篇第 4 条

> **训练完成仅代表得到产物;须经过登记、兼容检查、评测、部署与发布才能服务用户。**

所以这条链上有**四个各不相同的状态**:

    训练完成  →  有产物  →  产物可用(校验过)  →  在服务用户(部署了)

**把任意两个合成一个,就是这个模块最容易出的错** ——
而合并之后界面上看起来一切正常:一个没校验过的产物会显示成「可以用了」。

## ⚠️ 没有 GPU 不是删掉这一块的理由

规格第 6 条明写:「功能逐阶段交付,但整份规格都保留。
**不能因为没有 GPU,就从需求中删除微调模块**。」

所以适配器是 `TRAINING_ADAPTER=mock`,而**铁律**是:
**mock 的产物不许计入真实评测或发布**。这条不靠记 ——
`training.可以部署吗()` 把它做成了闸,而且是**三值**的:
True 拒、None(说不清)**也拒**。**未知不是「不是」。**

## ⚠️ 幂等键为什么是硬要求

契约原话:「**超时重发一次 = 再烧一遍 GPU**」。
这和别处的幂等不是一个量级 —— 别处重发一次多一条记录,这里重发一次多一笔钱。
库里还配了唯一约束兜底(`uq_deployments_project_id_idempotency_key`)——
**能用约束表达的不要用判据表达**。

## ⚠️ 格式错不建行,语义闸没过要建行

两种「提交失败」在这里含义完全不同:

  · **格式错**(训练目标拼错)→ 422,**不建行**。一个没成形的请求不是一个训练任务。
  · **语义闸没过**(分集泄漏 / 版本没固化)→ **建行并记「失败」**,再返回 422。

第二种要留痕,因为它说明**有人试图拿这批数据去训练** ——
而这件事在一个会烧钱、会产出模型的模块里,本身就是要记的。
只报错不留痕的话,「为什么这批数据一直没训成」下次还得重新查一遍。
"""
import json as _json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import runtime_cfg as CFG
import states as ST
import training

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
_机 = ST.找("training_job")


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _审计(c, me, action, target, result="ok", reason=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, reason, created_at, created_by)
        values (:i,:o,:p,:a,:ac,cast(:t as jsonb),:e, now(), :r, :rs, now(), :a)
    """), {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id,
           "ac": action, "t": _json.dumps(target, ensure_ascii=False),
           "e": os.environ.get("APP_ENV", "development"), "r": result, "rs": reason})


def _是mock(任务行):
    """这次训练是不是 mock 跑的。**三值** —— True / False / None(说不清)。

    ⚠️ **从训练任务推,不当参数收。** 允许登记产物时自己声明「我不是 mock」,
    等于把铁律交给调用方自觉,而一份 mock 产物在数据形状上和真的一模一样。

    ⚠️ 没有任务可推的产物(外部训练导进来的)→ **None,不是 False**。
    """
    if not 任务行:
        return None
    cfg = 任务行.get("config_snapshot") or {}
    if isinstance(cfg, str):
        try: cfg = _json.loads(cfg)
        except Exception: cfg = {}
    v = cfg.get("训练适配器")
    if v is None:
        return None
    return str(v).lower() == "mock"


# ── 训练任务 ────────────────────────────────────────────────────
@router.get(前缀 + "/training-jobs")
def 训练任务列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
           状态: str = Query(None, description="只看某个状态")):
    with 连接() as c:
        行 = [dict(r) for r in c.execute(text("""
            select id, status, base_model, objective, param_update_method,
                   dataset_version_id, external_id, config_snapshot,
                   cancel_requested, created_at, created_by, revision
              from training_jobs
             where project_id=:p and archived_at is null
               and (cast(:st as text) is null or status = cast(:st as text))
             order by created_at desc limit 200"""),
            {"p": project_id, "st": 状态}).mappings()]
    出 = []
    for r in 行:
        出.append({
            "id": r["id"], "status": r["status"],
            "基座模型": r["base_model"],
            # ⚠️ **两个维度分开显示**,不合成一个 ——
            # 合成之后「选了 LoRA 的那些任务是 SFT 还是 DPO」答不出来。
            "训练目标": r["objective"],
            "参数更新方式": r["param_update_method"],
            "数据集版本": r["dataset_version_id"],
            "外部任务号": r["external_id"],
            "是mock跑的": _是mock(r),
            "请求取消了吗": bool(r["cancel_requested"]),
            "revision": r["revision"],
        })
    return {"条数": len(出), "任务": 出,
            "note": ("`是mock跑的` 为 **null 表示说不清**,不是「不是」—— "
                     "而说不清的产物**不许部署**(铁律:mock 产物不许计入真实发布)")}


@router.post(前缀 + "/training-jobs", status_code=202)
async def 提交训练(project_id: str, request: Request,
             idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
             me: 身份 = Depends(要权限("提交真实训练"))):
    """提交一个训练任务。入参 `{基座模型, 训练目标, 参数更新方式, 数据集版本}`。

    ⚠️ **幂等键是硬要求** —— 契约原话:「超时重发一次 = 再烧一遍 GPU」。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "**超时重发一次 = 再烧一遍 GPU** —— 这里的幂等和别处不是一个量级")
    体 = await request.json()
    基座 = (体.get("基座模型") or 体.get("base_model") or "").strip()
    目标 = (体.get("训练目标") or 体.get("objective") or "").strip()
    方式 = (体.get("参数更新方式") or 体.get("param_update_method") or "").strip()
    版本id = (体.get("数据集版本") or 体.get("dataset_version_id") or "").strip()

    # ── 第一类:格式错 → 422,**不建行**(没成形的请求不是一个训练任务)
    坏 = {}
    if not 基座:
        坏["基座模型"] = "必填"
    if 目标 not in training.训练目标:
        坏["训练目标"] = (f"只收 {list(training.训练目标)} —— "
                      f"**它和参数更新方式是两个维度**,不是三选一")
    if 方式 not in training.参数更新方式:
        坏["参数更新方式"] = (f"只收 {list(training.参数更新方式)} —— "
                        f"**它和训练目标是两个维度**,不是三选一")
    if 坏:
        raise _错(422, "VALIDATION", "提交的字段不合格",
                  "SFT/DPO 是训练目标,LoRA/全量是参数更新方式,**分别选**",
                  field_errors=坏)

    是mock = CFG.TRAINING_ADAPTER == "mock"
    with 事务() as c:
        老 = c.execute(text("""select id, status from training_jobs
                             where project_id=:p and idempotency_key=:k"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            return {"id": 老["id"], "status": 老["status"], "新建了吗": False,
                    "note": "**同一个幂等键 → 返回原任务,没有再烧一遍 GPU**"}
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        版本 = c.execute(text("""select id, frozen_samples, sample_count, dataset_id
                              from dataset_versions
                             where project_id=:p and id=:i"""),
                        {"p": project_id, "i": 版本id}).mappings().first()
        版本 = dict(版本) if 版本 else None
        样本们 = []
        if 版本 and 版本.get("frozen_samples"):
            固 = 版本["frozen_samples"]
            if isinstance(固, str):
                try: 固 = _json.loads(固)
                except Exception: 固 = []
            样本们 = [{"id": x.get("id"), "split": x.get("split"),
                     "group_id": x.get("group_id")} for x in (固 or [])]

        问 = training.可以提交训练吗(目标=目标, 更新方式=方式, 版本=版本,
                              样本们=样本们, 是mock=是mock)
        jid = _新id("tj")
        快照 = {"训练适配器": CFG.TRAINING_ADAPTER, "基座模型": 基座,
              "训练目标": 目标, "参数更新方式": 方式,
              "数据集版本": 版本id or None, "提交人": me.user_id}
        # ── 第二类:语义闸没过 → **建行并记「失败」**,再报 422。
        # 它说明有人试图拿这批数据去训练,而那件事在一个会烧钱、
        # 会产出模型的模块里本身就该留痕。
        状态 = "失败" if 问 else "排队中"
        c.execute(text("""insert into training_jobs
            (id, organization_id, project_id, config_snapshot, dataset_version_id,
             base_model, objective, param_update_method, status, idempotency_key,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p, cast(:cs as jsonb), :dv, :bm, :ob, :pu, :st, :k,
                    now(), :by, now(), 1)"""),
                  {"i": jid, "o": org, "p": project_id,
                   "cs": _json.dumps(快照, ensure_ascii=False),
                   "dv": (版本id or None), "bm": 基座, "ob": 目标, "pu": 方式,
                   "st": 状态, "k": idempotency_key, "by": me.user_id})
        _审计(c, me, "training_job.submit",
              {"training_job_id": jid, "dataset_version_id": 版本id or None,
               "训练适配器": CFG.TRAINING_ADAPTER},
              result=("失败" if 问 else "ok"),
              reason=("; ".join(问)[:400] if 问 else None))
    if 问:
        raise _错(422, "CANNOT_TRAIN", "这批数据还不能拿去训练",
                  f"按下面每一条改完再提交。**这次尝试已经记在 {jid} 上**("
                  f"状态「失败」)—— 一个会烧钱的模块,试过什么要留痕",
                  field_errors={"闸": 问, "training_job_id": jid})
    return {"id": jid, "status": 状态, "新建了吗": True,
            "是mock跑的": 是mock,
            "note": (("⚠️ **这是 mock 适配器跑的** —— 它的产物"
                      "**不许计入真实评测或发布**(规格 §17.4 铁律),"
                      "部署那一道闸会拦住它。")
                     if 是mock else
                     "真实适配器。**训练完成只代表得到产物** —— "
                     "还要登记、校验、评测、部署才谈得上服务用户")}


@router.get(前缀 + "/training-jobs/{jid}")
def 训练详情(project_id: str, jid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        r = c.execute(text("""select * from training_jobs
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": jid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", f"没有训练任务 {jid}", "回列表重新进入")
        产物 = [dict(x) for x in c.execute(text("""
            select id, kind, usable, verified_at, content_hash
              from model_artifacts
             where project_id=:p and training_job_id=:i order by created_at"""),
            {"p": project_id, "i": jid}).mappings()]
    r = dict(r)
    return {
        "任务": {k: r[k] for k in ("id", "status", "base_model", "objective",
                                 "param_update_method", "dataset_version_id",
                                 "external_id", "image_digest", "revision")},
        "配置快照": r.get("config_snapshot"),
        "是mock跑的": _是mock(r),
        "请求取消了吗": bool(r.get("cancel_requested")),
        "产物": [{"id": a["id"], "种类": a["kind"], "标了可用吗": bool(a["usable"]),
                "校验于": a["verified_at"], "内容哈希": a["content_hash"]}
               for a in 产物],
        "下一步": ST.找("training_job")["流转"].get(r["status"], []),
        "note": ("**「已完成」只代表得到产物** —— 产物要先登记、校验、标可用,"
                 "才谈得上部署。这四件是四个状态,不是一个"),
    }


@router.post(前缀 + "/training-jobs/{jid}/cancel", status_code=202)
async def 请求取消训练(project_id: str, jid: str,
                idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
                me: 身份 = Depends(要权限("提交真实训练"))):
    """**是「请求取消」,不是「取消」。**

    契约原话:「取消和自然完成会并发,最终状态由后台确认,
    **UI 不许直接显示成已取消**」。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "取消也是异步动作,超时重发是常态")
    with 事务() as c:
        r = c.execute(text("""select id, status, revision, cancel_requested
                             from training_jobs
                            where project_id=:p and id=:i for update"""),
                      {"p": project_id, "i": jid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", f"没有训练任务 {jid}", "回列表重新进入")
        if r["status"] in _机["终态"]:
            # ⚠️ **保留真实终态,不谎报成已取消。**
            # 一次已经跑完的训练被标成「已取消」,会让人以为它的产物不存在。
            return {"id": jid, "status": r["status"], "改了吗": False,
                    "note": (f"这个任务已经结束了(「{r['status']}」)—— "
                             f"**保留真实终态,不谎报成已取消**。"
                             f"它的产物(如果有)是真的")}
        if r["status"] == "取消请求中":
            # ⚠️ **已经在「取消请求中」了,不许再往前推一步。**
            #
            # 这里栽过一次:`直接取消` 原来写成「状态机允许走到『已取消』就走」——
            # 而「取消请求中 → 已取消」那条边**只该由后台确认的时候走**。
            # 于是**连点两次取消,系统就自己宣布「已取消」** ——
            # 正是契约明令禁止的那件事(「最终状态由后台确认,
            # **UI 不许直接显示成已取消**」)。
            #
            # ⚠️ 同一条判断我在 `runctl.py` 里写过(两次提交之前),换到这个模块又漏了。
            # **教训不会自动跟着代码走** —— 它只跟着「被写成判据的地方」走。
            return {"id": jid, "status": r["status"], "改了吗": False,
                    "note": ("已经在「取消请求中」了。**再点一次不会让它变成已取消** —— "
                             "取消和自然完成会并发,最终状态由后台确认")}
        直接取消 = "已取消" in _机["流转"].get(r["status"], [])
        目标 = "已取消" if 直接取消 else "取消请求中"
        if not ST.能不能走("training_job", r["status"], 目标):
            raise _错(409, "BAD_TRANSITION",
                      f"「{r['status']}」走不到「{目标}」",
                      f"这个状态能走的是 {_机['流转'].get(r['status'], [])}")
        c.execute(text("""update training_jobs
                             set status=:st, cancel_requested=true,
                                 revision=revision+1, updated_at=now()
                           where project_id=:p and id=:i"""),
                  {"st": 目标, "p": project_id, "i": jid})
        _审计(c, me, "training_job.cancel", {"training_job_id": jid, "到": 目标})
    return {"id": jid, "status": 目标, "改了吗": True,
            "note": (("这个任务还没开跑,**没有在途的 GPU 要掐**,所以直接取消了"
                      if 直接取消 else
                      "**这是「请求取消」,不是「已取消」。** 取消和自然完成会并发 —— "
                      "最终状态由后台确认,**界面上不许直接显示成已取消**"))}


# ── 模型产物 ────────────────────────────────────────────────────
@router.get(前缀 + "/model-artifacts")
def 产物列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        行 = [dict(r) for r in c.execute(text("""
            select a.id, a.kind, a.base_model, a.usable, a.verified_at,
                   a.content_hash, a.file_manifest, a.training_job_id,
                   a.created_at, j.config_snapshot
              from model_artifacts a
              left join training_jobs j
                on j.project_id = a.project_id and j.id = a.training_job_id
             where a.project_id=:p and a.archived_at is null
             order by a.created_at desc limit 200"""),
            {"p": project_id}).mappings()]
    出 = []
    for r in 行:
        m = _是mock({"config_snapshot": r["config_snapshot"]}) if r["training_job_id"] else None
        问 = training.可以标可用吗(r)
        出.append({
            "id": r["id"], "种类": r["kind"], "基座模型": r["base_model"],
            "标了可用吗": bool(r["usable"]), "校验于": r["verified_at"],
            "训练任务": r["training_job_id"],
            "是mock训练的": m,
            "能标可用吗": not 问, "还差什么": 问 or None,
        })
    return {"条数": len(出), "产物": 出,
            "note": ("`是mock训练的` 为 **null 表示说不清**(没有对应训练任务)—— "
                     "**未知不是「不是」**,说不清的产物不许部署")}


@router.post(前缀 + "/model-artifacts", status_code=201)
async def 登记产物(project_id: str, request: Request,
             me: 身份 = Depends(要权限("提交真实训练"))):
    """登记一个产物。**`usable` 一律从 false 起**。

    规格:「**校验后才能标可用** —— 训练完成只代表得到产物。」
    所以这里**不收 `usable` 参数** —— 收了就等于让调用方自己说「我校验过了」。
    """
    体 = await request.json()
    jid = (体.get("训练任务") or 体.get("training_job_id") or "").strip() or None
    种类 = (体.get("种类") or 体.get("kind") or "").strip()
    基座 = (体.get("基座模型") or 体.get("base_model") or "").strip()
    清单 = 体.get("文件清单") or 体.get("file_manifest")
    哈希 = (体.get("内容哈希") or 体.get("content_hash") or "").strip() or None
    坏 = {}
    if not 种类: 坏["种类"] = "必填(例:adapter / full)"
    if not 基座: 坏["基座模型"] = "必填"
    if not isinstance(清单, (list, dict)) or not 清单:
        坏["文件清单"] = "必填 —— 少一个文件的产物**装载时才会报错**,而那时候它已经被标成可用了"
    if 坏:
        raise _错(422, "VALIDATION", "登记的字段不合格", "补齐必填项", field_errors=坏)
    aid = _新id("ma")
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        if jid:
            有 = c.execute(text("select 1 from training_jobs where project_id=:p and id=:i"),
                           {"p": project_id, "i": jid}).first()
            if not 有:
                # **不静默改成 NULL 收下** —— 收下之后这个产物看起来来自
                # 某次训练,而那次训练不存在,于是「它是不是 mock 训练的」
                # 会从「说不清」变成「查不到」,而这两种在界面上长得一样。
                raise _错(422, "TRAINING_JOB_NOT_FOUND", f"没有训练任务 {jid}",
                          "确认任务号;外部训练导进来的产物就**不要填这一项**,"
                          "它会被记成「说不清是不是 mock」并在部署那道闸被拦住")
        c.execute(text("""insert into model_artifacts
            (id, organization_id, project_id, training_job_id, kind, base_model,
             file_manifest, content_hash, usable, created_at, created_by,
             updated_at, revision)
            values (:i,:o,:p,:j,:k,:bm, cast(:fm as jsonb), :h, false,
                    now(), :by, now(), 1)"""),
                  {"i": aid, "o": org, "p": project_id, "j": jid, "k": 种类,
                   "bm": 基座, "fm": _json.dumps(清单, ensure_ascii=False),
                   "h": 哈希, "by": me.user_id})
        _审计(c, me, "model_artifact.register",
              {"model_artifact_id": aid, "training_job_id": jid})
    return {"id": aid, "标了可用吗": False,
            "note": ("**`usable` 一律从 false 起,而且这个接口不收这个参数** —— "
                     "收了就等于让调用方自己说「我校验过了」。"
                     "「有产物」和「产物可用」是两个状态")}


# ── 部署 ────────────────────────────────────────────────────────
@router.post(前缀 + "/deployments", status_code=202)
async def 部署产物(project_id: str, request: Request,
             idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
             me: 身份 = Depends(要权限("生产审核/发布/回滚"))):
    """把一个产物部署到某个环境。**三道闸,见 `training.可以部署吗`。**"""
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "部署是异步 + 对外的动作,超时重发是常态;库里还有唯一约束兜底")
    体 = await request.json()
    aid = (体.get("产物") or 体.get("model_artifact_id") or "").strip()
    环境 = (体.get("环境") or 体.get("environment") or "").strip()
    with 事务() as c:
        老 = c.execute(text("""select id, status, environment from deployments
                             where project_id=:p and idempotency_key=:k"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            return {"id": 老["id"], "status": 老["status"], "新建了吗": False,
                    "note": "**同一个幂等键 → 返回原部署,没有部署两次**"}
        a = c.execute(text("""select a.*, j.config_snapshot
                            from model_artifacts a
                            left join training_jobs j
                              on j.project_id=a.project_id and j.id=a.training_job_id
                           where a.project_id=:p and a.id=:i"""),
                      {"p": project_id, "i": aid}).mappings().first()
        a = dict(a) if a else None
        是mock = _是mock({"config_snapshot": a["config_snapshot"]}) if (a and a.get("training_job_id")) else None
        问 = training.可以部署吗(a, 环境=环境, 训练是mock=是mock)
        if 问:
            # ⚠️ **留痕先落库,抛错留到事务外面。**
            #
            # 第一版在这里 `_审计(...)` 之后当场 `raise` —— 而那个异常
            # **把同一个事务里的审计行一起回滚了**。
            # 两件事各自都对(审计写成了、错也抛对了),凑在一起的结果是**审计消失**。
            # 端到端第一次跑就抓到:三条「被拦进了审计」全挂。
            #
            # > **拒绝的记录,不能由拒绝本身回滚掉。**
            #
            # (提交训练那条恰好躲过了 —— 因为它的 `raise` 写在事务块外面,
            #  而那不是设计,是巧合。现在两处都是显式的。)
            _审计(c, me, "deployment.blocked",
                  {"model_artifact_id": aid, "environment": 环境},
                  result="blocked", reason="; ".join(问)[:400])
            拦了 = 问
        else:
            拦了 = None
        if 拦了:
            pass          # 真正的抛错在事务提交之后
        else:
            did = _新id("dep")
            证据 = {"产物": aid, "环境": 环境, "是mock训练的": 是mock,
                  "产物校验于": str(a.get("verified_at")),
                  "内容哈希": a.get("content_hash"), "放行人": me.user_id}
            c.execute(text("""insert into deployments
                (id, organization_id, project_id, model_artifact_id, environment,
                 status, idempotency_key, gate_evidence, created_at, created_by,
                 updated_at, revision)
                values (:i,:o,:p,:a,:e,'部署请求中',:k, cast(:g as jsonb),
                        now(), :by, now(), 1)"""),
                      {"i": did, "o": a["organization_id"], "p": project_id,
                       "a": aid, "e": 环境, "k": idempotency_key,
                       "g": _json.dumps(证据, ensure_ascii=False), "by": me.user_id})
            _审计(c, me, "deployment.create",
                  {"deployment_id": did, "model_artifact_id": aid, "environment": 环境})
    # ⚠️ 事务已经提交,**审计行落住了**,现在才抛。
    if 拦了:
        raise _错(422, "CANNOT_DEPLOY", "这个产物现在不能部署",
                  "按下面每一条处理。**被拦这件事已经记进审计** —— "
                  "「谁在哪天想把什么放上去、被什么拦住了」是事后唯一查得到的地方",
                  field_errors={"闸": 拦了})
    return {"id": did, "status": "部署请求中", "环境": 环境,
            "note": ("**「部署请求中」不是「在服务用户」** —— 和取消那边同一个道理:"
                     "写下请求之后,真实状态由后台确认。"
                     "放行时依据的那几条已经记在 `gate_evidence` 里,"
                     "**不能只留在某个人的记忆里**")}
