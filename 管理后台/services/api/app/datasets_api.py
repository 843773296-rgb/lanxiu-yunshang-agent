#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据集与训练样本(规格 §17.4 微调链的前半段)。

    GET    /datasets                              列表(**只给计数,不给内容**)
    POST   /datasets                              建
    PATCH  /datasets/{id}/samples/{sample_id}     改样本(乐观锁)
    POST   /datasets/{id}/versions                冻结(**固化内容**)
    GET    /datasets/{id}/export                  导出训练数据(**七道闸**)

## 为什么这一组现在做

① `evals.可以冻结吗()` 2026-09-28 早些时候就写好了,**而没有任何接口调用它** ——
   而「判据写好了却没被调用,和没写是一样的」这条,这个仓库今天已经栽过一次。
② 并行会话删澜绣那六页时发现 `/ai/export-finetune`(导出微调训练数据)
   **两张交割表都不认领它** —— 它是活的、有 URL 能打开、没有闸。
   按归属判据,训练数据的**闸**属于控制面(改一次以后谁都按新的来),
   所以这一组里多接了一条契约里原本没有的 `GET /datasets/{id}/export`。

## ⚠️ 导出这条不是「读一下数据」

它交出去的是**真实客户对话内容**。所以除了基础权限(`改训练样本`),
还额外要那条字段级授权(`查看敏感输入/独立测试答案`)——
基础权限管的是「能不能改这个数据集」,而导出交出去的是**内容本身**。
两者不是一回事,而只判前者的话,一个能改样本的人就能把全部原文带走。

## ⚠️ 脱敏器还没选型 —— 所以这一版**不假装自己在脱**

正则 / 白名单 / 模型三条路差别很大,是个要拍板的选择(仓库规矩:算法先选型再写)。
而**一个声称脱过而实际没脱的接口,比明说「没脱」危险得多**:
调用方看到 `x-redacted` 头就以为安全了。

所以这一版:
  · `datasets.redaction_policy` 是空的           → 拒(**没人声明过怎么脱**)
  · 声明成 `无需脱敏:<理由>`                      → 放行,**一个字都不改**,头上写明 0 处
  · 声明成别的(= 确实需要脱)                     → **501**,说明脱敏器还没选型

第三种返回 501 而不是「先给你不脱的版本」—— 那正是这条闸存在的理由。
"""
import hashlib
import json as _json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import evals
import training

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

# 一次最多导多少条。**写死是故意的**:一个没有上限的导出接口,
# 内存和「一次带走多少」都没有边。
导出上限 = 5000


def _新id(前缀字):
    import uuid
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _哈希(x):
    return hashlib.sha256(_json.dumps(x, ensure_ascii=False, sort_keys=True)
                          .encode()).hexdigest()[:32]


def _审计(c, me, action, target, result="ok", reason=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, reason, created_at, created_by)
        values (:i,:o,:p,:a,:ac,cast(:t as jsonb),:e, now(), :r, :rs, now(), :a)
    """), {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id,
           "ac": action, "t": _json.dumps(target, ensure_ascii=False),
           "e": os.environ.get("APP_ENV", "development"), "r": result, "rs": reason})


def _取样本(c, project_id, dsid):
    """样本的**形状**(不含内容)—— 闸只需要形状。

    ⚠️ 判据用不到 `content`,所以这里就不 SELECT 它:
    取回来再不用,只是给自己留一个把原文写进日志的机会。
    """
    return [dict(r) for r in c.execute(text("""
        select id, split, review_status, group_id, source, revision
          from samples
         where project_id=:p and dataset_id=:d and archived_at is null
         order by id"""), {"p": project_id, "d": dsid}).mappings()]


@router.get(前缀 + "/datasets")
def 数据集列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """列表。**只给计数,不给内容**(契约:独立测试的样本内容要额外授权)。

    每一行都顺手把「**现在能不能导出**」算出来 ——
    不算的话,人得点进导出才知道这个数据集卡在哪一道闸上,
    而那时候他已经在试着导了。
    """
    with 连接() as c:
        ds = [dict(r) for r in c.execute(text("""
            select id, name, format, purpose, redaction_policy, revision, created_at
              from datasets where project_id=:p and archived_at is null
             order by created_at"""), {"p": project_id}).mappings()]
        出 = []
        for d in ds:
            样 = _取样本(c, project_id, d["id"])
            能, 拒, 账 = training.能导出吗(样, 脱敏策略=d["redaction_policy"])
            版 = c.execute(text("""select count(*) from dataset_versions
                                 where project_id=:p and dataset_id=:d"""),
                           {"p": project_id, "d": d["id"]}).scalar()
            出.append({
                "id": d["id"], "名字": d["name"], "格式": d["format"],
                "用途": d["purpose"], "revision": d["revision"],
                "冻结过几版": 版,
                "脱敏策略": d["redaction_policy"] or None,
                "样本数": 账["总数"], "分档": 账["分档"],
                "能导出吗": not 拒,
                "卡在哪": 拒 or None,
            })
    return {"条数": len(出), "数据集": 出,
            "note": ("**列表不给样本内容** —— 独立测试档的内容要那条专项授权。"
                     "「能导出吗」是现算的,不是存的字段:存的会漂")}


@router.post(前缀 + "/datasets", status_code=201)
async def 建数据集(project_id: str, request: Request,
             me: 身份 = Depends(要权限("改训练样本"))):
    """建一个数据集。

    ⚠️ **`脱敏策略` 可以不给** —— 但不给它就导不出来,而且返回里会写明这件事。
    不在这里强制必填,因为「先建起来再补声明」是正常顺序;
    真正不能含糊的是**导出那一刻**。
    """
    体 = await request.json()
    名 = (体.get("名字") or 体.get("name") or "").strip()
    格式 = (体.get("格式") or 体.get("format") or "").strip()
    用途 = (体.get("用途") or 体.get("purpose") or "").strip() or None
    策略 = (体.get("脱敏策略") or 体.get("redaction_policy") or "").strip() or None
    坏 = {}
    if not 名: 坏["名字"] = "必填"
    if not 格式: 坏["格式"] = "必填(现有的一份是 `qa`)"
    if 坏:
        raise _错(422, "VALIDATION", "字段不合格", "名字和格式都要给", field_errors=坏)
    dsid = _新id("ds")
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        c.execute(text("""insert into datasets (id, organization_id, project_id, name,
                              format, purpose, redaction_policy, created_at, created_by,
                              updated_at, revision)
                         values (:i,:o,:p,:n,:f,:u,:r, now(), :by, now(), 1)"""),
                  {"i": dsid, "o": org, "p": project_id, "n": 名, "f": 格式,
                   "u": 用途, "r": 策略, "by": me.user_id})
        _审计(c, me, "dataset.create", {"dataset_id": dsid, "name": 名})
    return {"id": dsid, "名字": 名,
            "note": ("这个数据集现在**导不出来**:还没有样本。"
                     if 策略 else
                     "⚠️ **没声明脱敏策略** —— 这个数据集导出时会被拦在那道闸上。"
                     "声明的写法:`无需脱敏:<理由>`,或者描述它需要脱什么")}


@router.patch(前缀 + "/datasets/{dsid}/samples/{sid}")
async def 改样本(project_id: str, dsid: str, sid: str, request: Request,
            if_match: str = Header(default=None, alias="If-Match"),
            me: 身份 = Depends(要权限("改训练样本"))):
    """改一条样本。**要 If-Match**(乐观锁)。

    ⚠️ **改一条已经被冻结版本引用过的样本是允许的** —— 而且不会动那个版本,
    因为冻结**固化了内容**(`dataset_versions.frozen_samples`)。
    这正是「冻结不是存个指针」那条的兑现:
    如果冻结只存指针,这里每改一次都会**悄悄改掉历史上那一版评测用的题**,
    于是「同一批题、换个配置、分数变没变」这个问题问不成 ——
    而那个变化不会报错,只会让两次的分数不可比而看起来可比。
    """
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match",
                  "把样本详情里的 revision 放进 If-Match 头再提交")
    体 = await request.json()
    with 事务() as c:
        s = c.execute(text("""select * from samples
                             where project_id=:p and dataset_id=:d and id=:i
                             for update"""),
                      {"p": project_id, "d": dsid, "i": sid}).mappings().first()
        if not s:
            raise _错(404, "NOT_FOUND", f"没有样本 {sid}", "回列表重新进入")
        if str(s["revision"]) != str(if_match):
            raise _错(409, "REVISION_CONFLICT",
                      f"这条样本已经被改过(你拿的是 {if_match},现在是 {s['revision']})",
                      "刷新看一眼别人改了什么再合并;**不要直接覆盖**",
                      field_errors={"revision": f"当前 {s['revision']}"})
        改 = {}
        if "内容" in 体 or "content" in 体:
            c2 = 体.get("内容", 体.get("content"))
            if not isinstance(c2, (dict, list)):
                raise _错(422, "VALIDATION", "内容要是一个对象或数组",
                          "检查提交的 JSON 形状")
            改["content"] = _json.dumps(c2, ensure_ascii=False)
            改["content_hash"] = _哈希(c2)
        for 中, 英, 白 in (("分集", "split", evals.分集),
                          ("复核状态", "review_status", None),
                          ("组", "group_id", None)):
            if 中 in 体 or 英 in 体:
                v = 体.get(中, 体.get(英))
                v = (str(v).strip() or None) if v is not None else None
                if 白 and v is not None and v not in 白:
                    raise _错(422, "VALIDATION", f"{中}认不出:{v!r}",
                              f"只收 {list(白)}", field_errors={中: f"只收 {list(白)}"})
                改[英] = v
        if not 改:
            raise _错(422, "VALIDATION", "没有要改的字段",
                      "可改:内容 / 分集 / 复核状态 / 组")
        新版 = int(s["revision"]) + 1
        套 = ", ".join(f"{k}=" + (f"cast(:{k} as jsonb)" if k == "content" else f":{k}")
                      for k in 改)
        c.execute(text(f"""update samples set {套}, revision=:_rev, updated_at=now()
                          where project_id=:_p and id=:_i"""),
                  {**改, "_rev": 新版, "_p": project_id, "_i": sid})
        # 改了分集就可能制造跨档泄漏 —— **当场算一遍报给他**,
        # 而不是等到导出或冻结那一刻才说。
        漏 = evals.查分集泄漏(_取样本(c, project_id, dsid))
    return {"id": sid, "revision": 新版, "改了": sorted(改),
            "跨分集的组": 漏 or None,
            "note": ("**改这条不会动已经冻结的版本** —— 冻结固化了内容,不是存指针"
                     + ("。⚠️ 现在有组跨了分集,导出和冻结都会被拦" if 漏 else ""))}


@router.post(前缀 + "/datasets/{dsid}/versions", status_code=201)
async def 冻结数据集(project_id: str, dsid: str, request: Request, response: Response,
              me: 身份 = Depends(要权限("改训练样本"))):
    """冻一个版本。**固化内容**,不是存个指针(契约里原话)。

    ⚠️ 这条接口终于把 `evals.可以冻结吗()` 用上了 ——
    那个判据 09-28 早些时候就写好了,在这之前**没有任何接口调用它**,
    而「判据写好了却没被调用,和没写是一样的」。
    """
    with 事务() as c:
        d = c.execute(text("""select * from datasets
                             where project_id=:p and id=:i and archived_at is null"""),
                      {"p": project_id, "i": dsid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", f"没有数据集 {dsid}", "回列表重新进入")
        形 = _取样本(c, project_id, dsid)
        问 = evals.可以冻结吗(形)
        if 问:
            raise _错(422, "CANNOT_FREEZE", "这批样本还不能冻结",
                      "按下面每一条改完再来", field_errors={"样本": 问})
        # 固化:**这一步才 SELECT content** —— 前面的判据都只要形状。
        全 = [dict(r) for r in c.execute(text("""
            select id, content, split, review_status, group_id, source, content_hash
              from samples
             where project_id=:p and dataset_id=:d and archived_at is null
             order by id"""), {"p": project_id, "d": dsid}).mappings()]
        分集映射 = {}
        for s in 全:
            分集映射.setdefault(s["split"] or "(没标分集)", []).append(s["id"])
        哈 = _哈希(全)
        # ⚠️ **内容一模一样就不新建。** 库里有 `UNIQUE (project_id, dataset_id,
        # content_hash)` —— 不先查的话这里当场 IntegrityError → 500。
        # (今天第四次被唯一约束接住:**能用约束表达的不要用判据表达**,
        #  约束在每次 INSERT 上生效,判据只在有人调用时生效。)
        #
        # 而**约束本身是对的,不该放宽**:同样的字节冻出两个版本号之后,
        # 「那次评测用的是哪一版」就有了两个同样成立的答案 ——
        # 而这个问题必须只有一个答案。
        老 = c.execute(text("""select id, sample_count from dataset_versions
                             where project_id=:p and dataset_id=:d and content_hash=:h"""),
                       {"p": project_id, "d": dsid, "h": 哈}).mappings().first()
        if 老:
            response.status_code = 200
            return {"id": 老["id"], "样本数": 老["sample_count"],
                    "新建了吗": False,
                    "分集": {k: len(v) for k, v in 分集映射.items()},
                    "note": ("**内容和这一版一模一样,所以没有新建** —— "
                             "同样的字节冻出两个版本号之后,「那次评测用的是哪一版」"
                             "就有了两个同样成立的答案。上次冻结之后样本没变过")}
        vid = _新id("dsv")
        c.execute(text("""insert into dataset_versions (id, organization_id, project_id,
                              dataset_id, split_map, content_hash, sample_count,
                              frozen_samples, created_at, created_by, updated_at, revision)
                         values (:i,:o,:p,:d, cast(:sm as jsonb), :h, :n,
                                 cast(:fs as jsonb), now(), :by, now(), 1)"""),
                  {"i": vid, "o": d["organization_id"], "p": project_id, "d": dsid,
                   "sm": _json.dumps(分集映射, ensure_ascii=False),
                   "h": 哈, "n": len(全),
                   "fs": _json.dumps(全, ensure_ascii=False, default=str),
                   "by": me.user_id})
        _审计(c, me, "dataset.freeze",
              {"dataset_id": dsid, "version_id": vid, "sample_count": len(全)})
    return {"id": vid, "样本数": len(全), "新建了吗": True,
            "分集": {k: len(v) for k, v in 分集映射.items()},
            "note": ("**内容已固化在这一版里** —— 之后改样本不会改到这一版。"
                     "只存哈希的话,样本改了只能发现「变了」,"
                     "拿不回原来那批题去重跑,而评测要问的正是那件事")}


@router.get(前缀 + "/datasets/{dsid}/export")
def 导出训练数据(project_id: str, dsid: str,
           要mock: int = Query(0, ge=0, le=1,
                              description="显式要 mock 样本。默认 0 —— mock 的产物不许计入真实训练"),
           me: 身份 = Depends(要权限("改训练样本"))):
    """导出训练数据。**七道闸,见 `training.py`。**

    ⚠️ 额外要那条字段级授权 —— 交出去的是**真实客户对话内容**,
    而基础权限管的只是「能不能改这个数据集」。
    """
    if not me.看得到原文吗():
        raise _错(403, "NEED_CONTENT_GRANT",
                  "导出交出去的是真实对话内容,要那条专项授权",
                  "找有权的人给「查看敏感输入/独立测试答案」这条授权;"
                  "**能改样本不等于能把全部原文带走**")
    with 连接() as c:
        d = c.execute(text("""select * from datasets
                             where project_id=:p and id=:i and archived_at is null"""),
                      {"p": project_id, "i": dsid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", f"没有数据集 {dsid}", "回列表重新进入")
        形 = _取样本(c, project_id, dsid)
        能, 拒, 账 = training.能导出吗(形, 脱敏策略=d["redaction_policy"],
                                  要mock=bool(要mock))
    策略 = (d["redaction_policy"] or "").strip()
    if 拒:
        # ⚠️ **422 而不是 200 + 空文件。** 空的 .jsonl 看起来是完全成功的,
        # 而下游会拿它去训练。账一起给 —— 「我没有什么」要配上「我有什么」。
        #
        # ⚠️ `_错()` **只收 field_errors,不收任意关键字** —— 第一版传了 `账=账`,
        # 于是**每一条拒都变成 500,而顺路那条是 200**。
        # 「顺路能走通」把六条拒全遮住了,而我先测的正是顺路那条。
        # 同一族今天第六次(前五次都是没查表结构就写 SQL),这次查的是**函数签名**。
        #
        # ⚠️ **不是 501。** 契约把状态码限成 7 个(401/403/404/409/422/429/500),
        # 501 不在里面,传进去当场 ValueError → 500。那个白名单是故意的:
        # 状态码一多,调用方就得按 `code` 而不是按状态码分支 —— 而那本来就是对的做法。
        #
        # ⚠️ **`code` 和「全部理由」分开:** `code` 指那个**要人来决定**的卡点
        # (脱敏器选型),`field_errors.闸` 仍然列全部 —— 一次报全,不让人修一条试一次。
        # 两者不冲突:一个回答「该找谁」,一个回答「还差什么」。
        还没选 = training.脱敏还没选型(策略)
        raise _错(422,
                  "REDACTOR_NOT_CHOSEN" if 还没选 else "CANNOT_EXPORT",
                  ("这个数据集声明了需要脱敏,而脱敏器还没选型"
                   if 还没选 else "这个数据集现在不能导出"),
                  ("三条路(正则 / 白名单 / 模型)差别很大,要先拍板;在那之前这里"
                   "**不给不脱的版本** —— 一个声称脱过而实际没脱的接口,比明说「没脱」危险得多"
                   if 还没选 else
                   "按 `field_errors.闸` 每一条处理 —— 「账」那一行说的是里面到底有什么"),
                  field_errors={"闸": 拒,
                                "账": "、".join(f"{k} {v}" for k, v in 账.items())})
    with 连接() as c:
        行们 = [dict(r) for r in c.execute(text("""
            select id, content, source from samples
             where project_id=:p and dataset_id=:d and id = any(:ids)
             order by id limit :lim"""),
            {"p": project_id, "d": dsid, "ids": [s["id"] for s in 能],
             "lim": 导出上限}).mappings()]
    体 = "\n".join(_json.dumps(
        {"id": r["id"], "content": r["content"]}, ensure_ascii=False)
        for r in 行们)
    有mock = any((r.get("source") or "").lower() == "mock" for r in 行们)
    with 事务() as c:
        _审计(c, me, "dataset.export",
              {"dataset_id": dsid, "条数": len(行们), "含mock": 有mock,
               "脱敏策略": 策略[:120]},
              reason=("显式要了 mock" if 有mock else None))
    头 = {
        "content-disposition":
            f'attachment; filename="{dsid}{"-MOCK" if 有mock else ""}.jsonl"',
        # ⚠️ 这两个头的值都是 ASCII —— HTTP 头只能 latin-1,
        # 而这个仓库今天已经为「协议边界上的中文」付过四次代价。
        "x-redacted": "0 (policy=no-redaction-needed)",
        "x-sample-count": str(len(行们)),
        "x-contains-mock": "yes" if 有mock else "no",
    }
    return Response(content=体, media_type="application/x-ndjson; charset=utf-8",
                    headers=头)
