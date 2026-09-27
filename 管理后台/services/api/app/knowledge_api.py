#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识与 RAG 接口(规格 §17.1 的知识库那一组)。

## 为什么先做这三条

九条接口里,真正**能让人看见 RAG** 的是「检索实验室跑一次」——
规格 §9.5 要求它「必须看到**整条链路**:原问、改写、候选、融合分、选片、证据、Trace」。

而 `POST /uploads` 那两条要新建 `uploads` 实体(契约登记表里没有)+ 一次迁移,
**它们不阻塞检索实验室**。先做能让界面跑起来的最小集合,
把要动契约的留到后面 —— 否则得等一条 CRUD 链做完才看得到 RAG。

## 一条判断都不自己写

照 `workflows_api.py` 的形状:
  · 检索的判断全在 `knowledge/retrieval.py`(它也不自己开连接)
  · 检索配置校验在 `knowledge/index_plan.py`
  · 权限从 `contract/perms.py` 判,状态问 `contract/states.py`

## ⚠️ 检索是**同步**的,而它真的调模型

和 `POST /workflows/{id}/runs` 不一样(那个返回 202、Worker 捞到才跑) ——
检索实验室是人坐在那儿等结果的,异步反而更难用。

代价写清:**一次检索会真调一次 Claude 精排**(几百毫秒到两秒),
而它的用量记在 `knowledge/llmtrace.py` 的日志里。
要它不调模型就传 `要精排=false`,返回里会说清「只走向量的排序不可靠」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge"))

import json as _json
import uuid as _uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

import adapters as AD
import index_plan as IP
import ingest as IN
import parser as PS
import retrieval as RT
import reranker as RR
import storage as OS_
from db import 连接, 事务
from deps import 身份, 要权限, _错


def _新id(前缀):
    return f"{前缀}_{_uuid.uuid4().hex[:12]}"

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


@router.get(前缀 + "/knowledge-bases")
def 知识库列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
           limit: int = Query(20, ge=1, le=100)):
    """知识库列表。**片段数和「索引到哪一版」要同时给。**

    只给片段数的话,「资料进来了」和「索引建好了」会被当成同一件事 ——
    而一个有 71 个片段、0 个索引的知识库,检索时返回的是空。
    """
    with 连接() as c:
        rs = c.execute(text("""
            select kb.id, kb.name, kb.status, kb.updated_at,
                   (select count(*) from documents d
                     where d.project_id=kb.project_id and d.knowledge_base_id=kb.id
                       and d.archived_at is null) 文档数,
                   (select count(*) from chunks ch
                      join document_versions dv
                        on dv.project_id=ch.project_id and dv.id=ch.document_version_id
                      join documents d
                        on d.project_id=dv.project_id and d.id=dv.document_id
                     where ch.project_id=kb.project_id
                       and d.knowledge_base_id=kb.id) 片段数,
                   (select count(*) from index_builds ib
                     where ib.project_id=kb.project_id and ib.knowledge_base_id=kb.id
                       and ib.status='已就绪') 就绪索引数,
                   (select ib.embedding_model_id from index_builds ib
                     where ib.project_id=kb.project_id and ib.knowledge_base_id=kb.id
                       and ib.status='已就绪'
                     order by ib.updated_at desc limit 1) 最新索引模型
              from knowledge_bases kb
             where kb.project_id=:p and kb.archived_at is null
             order by kb.updated_at desc nulls last
             limit :n
        """), {"p": project_id, "n": limit}).mappings().all()
    出 = []
    for r in rs:
        d = dict(r)
        模型 = d.pop("最新索引模型", None)
        # ⚠️ **「能不能检索」要显式说,不让人从 0 里猜。**
        # 一个有片段但没就绪索引的知识库,检索时返回空 ——
        # 而那和「知识库里就这么点东西」在界面上长得一样。
        d["能检索吗"] = bool(d["就绪索引数"])
        d["为什么不能检索"] = (
            None if d["就绪索引数"] else
            ("还没有片段 —— 先导入文档" if not d["片段数"]
             else "有片段但**没有已就绪的索引** —— 先建一次索引"))
        d["索引模型"] = 模型
        # 用的是真向量还是 mock。**这个标记要一路传到界面上** ——
        # mock 向量算出的相似度是个看起来很正常的数字,人会拿它当效果读。
        d["索引是mock吗"] = (None if not 模型 else not AD.是真的吗(模型))
        出.append(d)
    return {"items": 出, "total": len(出)}


@router.get(前缀 + "/knowledge-bases/{kb_id}/index-builds")
def 索引构建列表(project_id: str, kb_id: str,
             me: 身份 = Depends(要权限("查看有权配置")),
             limit: int = Query(20, ge=1, le=100)):
    """某个知识库的索引构建。**状态、模型、成员数、输入指纹都要给。**

    ⚠️ `成员数` 和知识库的 `片段数` 对不上就说明这个索引不完整 ——
    而一个不完整的索引检索时只是「少返回几条」,不报错。
    """
    with 连接() as c:
        kb = c.execute(text("""select id, name from knowledge_bases
                              where project_id=:p and id=:i and archived_at is null"""),
                       {"p": project_id, "i": kb_id}).mappings().first()
        if not kb:
            # 404 而不是 403:**不泄露「这个 ID 在别的项目里存在」**
            raise _错(404, "NOT_FOUND", "没有这个知识库", "回知识库列表重新进入")
        rs = c.execute(text("""
            select ib.id, ib.status, ib.embedding_model_id, ib.embedding_dim,
                   ib.input_hash, ib.job_id, ib.created_at, ib.updated_at,
                   ib.retrieval_config_version_id,
                   (select count(*) from index_members im
                     where im.project_id=ib.project_id and im.index_build_id=ib.id) 成员数
              from index_builds ib
             where ib.project_id=:p and ib.knowledge_base_id=:k
               and ib.archived_at is null
             order by ib.created_at desc
             limit :n
        """), {"p": project_id, "k": kb_id, "n": limit}).mappings().all()
    出 = []
    for r in rs:
        d = dict(r)
        d["是mock吗"] = (None if not d["embedding_model_id"]
                       else not AD.是真的吗(d["embedding_model_id"]))
        d["输入指纹短"] = (d["input_hash"] or "")[:26] or None
        出.append(d)
    return {"知识库": dict(kb), "items": 出, "total": len(出)}


@router.post(前缀 + "/retrieval-tests")
async def 检索实验室(project_id: str, request: Request,
               me: 身份 = Depends(要权限("运行评测"))):
    """跑一次检索,返回**整条链路**(§9.5)。

    入参:`{索引构建id, 问题, 要精排?}`

    ⚠️ **同步** —— 人坐在那儿等结果,异步反而更难用。
    代价:一次调用会**真调一次 Claude 精排**(几百毫秒到两秒),
    用量记在记录仪日志里。传 `要精排=false` 就只走向量,
    而返回里会说清「只走向量的排序不可靠」。
    """
    体 = await request.json()
    构建id = (体.get("索引构建id") or "").strip()
    问题 = (体.get("问题") or "").strip()
    要精排 = 体.get("要精排")
    要精排 = True if 要精排 is None else bool(要精排)
    if not 构建id:
        raise _错(422, "VALIDATION", "没给索引构建 id",
                  "先在知识库页面选一个「已就绪」的索引",
                  field_errors={"索引构建id": "必填"})
    if not 问题:
        raise _错(422, "VALIDATION", "问题是空的",
                  "空查询的向量会返回一批「离原点最近」的片段,看起来像正常结果 —— "
                  "所以这里不放行",
                  field_errors={"问题": "必填"})

    with 连接() as c:
        try:
            链 = RT.检索(c, 项目=project_id, 构建id=构建id, 问题=问题, 要精排=要精排)
        except RT.检索不了 as e:
            # ⚠️ 这些是**配置/前提不满足**,不是服务问题 —— 422 而不是 500。
            # 而且 `retrieval.py` 的每条异常都带「怎么办」,原样传给调用方
            # (规格 §19.1:失败必须带**可执行建议**)。
            raise _错(422, "RETRIEVAL_PRECONDITION", str(e).split("\n")[0][:300],
                      str(e)[:600])
        except AD.认不出这个模型 as e:
            raise _错(422, "EMBEDDER_UNAVAILABLE", str(e).split("\n")[0][:200],
                      "这个索引用的 Embedding 模型没登记 —— "
                      "见 knowledge/adapters.py 的 `登记`")
        except RR.没有凭据 as e:
            raise _错(422, "NO_MODEL_CREDENTIAL", str(e)[:200],
                      "精排要调 Claude,而本机拿不到凭据。"
                      "要先看检索效果可以传 `要精排=false` —— "
                      "但**只走向量的排序不可靠**(实测一个表格头排到过第 1 名)")
        except RR.精排失败 as e:
            # **不降级成「按原顺序」。** 那会让「精排坏了」和
            # 「精排认为原顺序就是对的」长得一模一样。
            raise _错(422, "RERANK_FAILED", str(e).split("\n")[0][:300],
                      "精排返回的东西不合契约(编号对不上 / 引文是编的)。"
                      "**没有降级成按原顺序** —— 那会让故障和结论长得一样。"
                      "可以传 `要精排=false` 先看召回")
    return 链


# ══════════════════════════════════════════════════════════════════════
# M2:把已校验的上传变成知识库里的资料 + 建索引
#
# ⚠️ 这一组要守住一句话:**这里的每一步都不会让资料「立刻能检索」。**
# 规格里那句「不立即生产生效 —— 要等索引构建 + 发布」不是流程上的客套,
# 它是因为**片段进库和索引建好是两件事**,而一个有片段、没索引的知识库
# 检索时返回空 —— 那和「知识库里就这么点东西」在界面上长得一样。
# 所以每条接口的返回里都显式说「下一步还要做什么」。
# ══════════════════════════════════════════════════════════════════════


@router.post(前缀 + "/knowledge-bases", status_code=201)
async def 建知识库(project_id: str, request: Request,
              me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """建一个知识库。入参 `{name, acl?}`。

    ⚠️ **`acl` 是上限,不是默认值**(§18「文档父级权限可收紧」)——
    文档可以再收紧但不能放宽。所以这里不给它一个「宽松的默认」:
    一个默认放开的知识库,它下面每一篇文档都继承了那个放开,
    而**没有任何地方会提醒**。
    """
    体 = await request.json()
    名 = (体.get("name") or "").strip()
    if not 名:
        raise _错(422, "VALIDATION", "知识库要有名字",
                  "名字是人在界面上认它的唯一凭据 —— 一个叫 `kb_a1b2c3` 的知识库"
                  "半个月后没人知道里面是什么",
                  field_errors={"name": "必填"})
    if len(名) > 120:
        raise _错(422, "VALIDATION", "名字太长(超过 120 字)",
                  "长名字在列表里会被截断,而被截断的名字认不出来",
                  field_errors={"name": "最多 120 字"})
    acl = 体.get("acl")
    with 事务() as c:
        重 = c.execute(text("""select id from knowledge_bases
                             where project_id=:p and name=:n and archived_at is null"""),
                      {"p": project_id, "n": 名}).scalar()
        if 重:
            # 409 而不是默默建第二个:**两个同名知识库在界面上分不开**,
            # 而人会往其中一个加资料、在另一个里找不到,然后以为资料丢了。
            raise _错(409, "NAME_TAKEN", f"这个项目里已经有叫「{名}」的知识库",
                      f"换个名字,或者直接往那个里加资料(id {重})")
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        kb = _新id("kb")
        c.execute(text("""insert into knowledge_bases
            (id, organization_id, project_id, name, acl, status,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n, cast(:a as jsonb), :st, now(), :by, now(), 1)"""),
                  {"i": kb, "o": org, "p": project_id, "n": 名,
                   "a": _json.dumps(acl, ensure_ascii=False) if acl is not None else None,
                   "st": "启用", "by": me.user_id})
    return {"id": kb, "name": 名, "状态": "启用", "文档数": 0, "片段数": 0,
            "能检索吗": False,
            "note": ("建好了,而**它现在检索不了** —— 里面一篇资料都没有。"
                     "下一步:加资料 → 建索引"),
            "acl说明": ("`acl` 是**上限**:文档可以再收紧但不能放宽(§18)。"
                      "没给就是继承项目默认" if acl is None else "按给的 acl 设了上限")}


@router.post(前缀 + "/knowledge-bases/{kb_id}/documents", status_code=201)
async def 加资料(project_id: str, kb_id: str, request: Request,
             me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """把一个**已校验的上传**收成知识库里的一篇资料。入参 `{upload_id, name?}`。

    ⚠️ **只收 `已校验` 的上传。** 收 `已上传` 的等于把规格 §17.1
    那句话作废 —— 而它作废之后,坏文件不会在这里被拦,会在**建索引时**炸,
    那时错误指向解析器。

    ⚠️ **不立即生产生效**(§17.1)—— 片段进库了,但索引没有它。
    """
    体 = await request.json()
    上传id = (体.get("upload_id") or "").strip()
    名字 = (体.get("name") or "").strip() or None
    if not 上传id:
        raise _错(422, "VALIDATION", "没给 upload_id",
                  "先走一遍上传(要地址 → 传字节 → 完成校验),"
                  "拿到一条「已校验」的上传再来这里",
                  field_errors={"upload_id": "必填"})
    with 事务() as c:
        kb = c.execute(text("""select id, name from knowledge_bases
                             where project_id=:p and id=:i and archived_at is null"""),
                       {"p": project_id, "i": kb_id}).mappings().first()
        if not kb:
            raise _错(404, "NOT_FOUND", "没有这个知识库", "回知识库列表重新进入")
        u = c.execute(text("""select * from uploads
                            where project_id=:p and id=:i and archived_at is null"""),
                      {"p": project_id, "i": 上传id}).mappings().first()
        行, 为什么 = IN.检查上传可用(dict(u) if u else None)
        if not 行:
            # 422 而不是 404/409:这是**输入不满足前提**,而 `为什么` 里
            # 已经写清了下一步 —— 原样传给调用方(§19.1 要求可执行建议)
            raise _错(422, "UPLOAD_NOT_USABLE", 为什么.split("——")[0].strip()[:200],
                      为什么[:600], field_errors={"upload_id": "这条上传还不能当资料用"})
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        try:
            结 = IN.收一份资料(c, 组织=org, 项目=project_id, 知识库id=kb_id,
                          上传=dict(u), 谁=me.user_id, 名字=名字)
        except IN.键的含义不明 as e:
            raise _错(500, "OBJECT_KEY_AMBIGUOUS", str(e).split("——")[0][:200], str(e)[:600])
        except OS_.存不了 as e:
            raise _错(500, "OBJECT_MISSING", str(e)[:300],
                      "库里记着这个对象键而存储里读不到 —— 服务端不一致,不是文件的问题")
        except PS.解析不了 as e:
            # ⚠️ 走到这里说明**校验和解析不一致** —— 校验通过了而解析炸了。
            # 校验那一步就是调解析器,所以这在正常情况下不可能。
            # 报出来点名这件事,别让它看起来像普通的「格式不支持」。
            raise _错(500, "VERIFY_PARSE_MISMATCH", str(e).split("\n")[0][:200],
                      "**这条上传校验通过了,而现在解析炸了** —— 校验那一步调的就是"
                      "同一个解析器,所以这不该发生。可能是解析器版本变了"
                      "(校验详情里记着当时那个版本)。这要人看,不是用户的问题")
    return {"知识库": dict(kb), **结,
            "note": ("**片段进库了,而索引里还没有它**(§17.1「不立即生产生效」)—— "
                     "下一步建一次索引。现在去检索这篇资料会**找不到**,"
                     "而那和「知识库里就这么点东西」在界面上长得一样")}


@router.post(前缀 + "/documents/{doc_id}/versions", status_code=201)
async def 发文档新版本(project_id: str, doc_id: str, request: Request,
                me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """给一篇已有资料发一个新版本。入参 `{upload_id}`。

    ⚠️ **幂等靠内容哈希** —— 同一份内容重复提交不新建版本。
    靠文件名的坏法:同名不同内容被当成「没变」,新内容永远进不去索引。

    ⚠️ **旧版本不动。** 片段绑的是**文档版本**不是文档 ——
    否则一改文档,历史证据链就指向了新内容(而引文还是旧的那句话)。
    """
    体 = await request.json()
    上传id = (体.get("upload_id") or "").strip()
    if not 上传id:
        raise _错(422, "VALIDATION", "没给 upload_id",
                  "先走一遍上传拿到一条「已校验」的上传",
                  field_errors={"upload_id": "必填"})
    with 事务() as c:
        d = c.execute(text("""select id, knowledge_base_id from documents
                            where project_id=:p and id=:i and archived_at is null"""),
                      {"p": project_id, "i": doc_id}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这篇资料", "回知识库看资料列表")
        u = c.execute(text("""select * from uploads
                            where project_id=:p and id=:i and archived_at is null"""),
                      {"p": project_id, "i": 上传id}).mappings().first()
        行, 为什么 = IN.检查上传可用(dict(u) if u else None)
        if not 行:
            raise _错(422, "UPLOAD_NOT_USABLE", 为什么.split("——")[0].strip()[:200],
                      为什么[:600], field_errors={"upload_id": "这条上传还不能当资料用"})
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        try:
            结 = IN.收一份资料(c, 组织=org, 项目=project_id,
                          知识库id=d["knowledge_base_id"], 上传=dict(u),
                          谁=me.user_id, 文档id=doc_id)
        except IN.键的含义不明 as e:
            raise _错(500, "OBJECT_KEY_AMBIGUOUS", str(e).split("——")[0][:200], str(e)[:600])
        except PS.解析不了 as e:
            raise _错(500, "VERIFY_PARSE_MISMATCH", str(e).split("\n")[0][:200],
                      "校验通过而解析炸了 —— 这要人看,不是用户的问题")
    return {**结,
            "note": ("**旧版本没动** —— 片段绑的是文档版本,不是文档"
                     "(否则一改文档,历史证据链就指向新内容)。"
                     "新版本要生效得**再建一次索引**")}


@router.post(前缀 + "/knowledge-bases/{kb_id}/index-builds", status_code=202)
async def 建索引(project_id: str, kb_id: str, request: Request,
             idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
             me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """派一次索引构建。**202 + job_id,一个向量都还没算**(§19.1)。

    入参:`{检索配置版本id?, embedding模型id?}`,都不给就用这个项目最新的那套。

    ## 为什么要 Idempotency-Key

    构建要跑真 Embedding —— 71 个片段就是 71 次前向。网络超时重发一次的代价
    是白算一遍。而**白算不报错**,它只是慢一倍、并且在用量报表上翻倍。

    ## 输入指纹在**派任务之前**算

    §19.3:「输入版本变化则创建新构建,而不是复用错误结果」。
    所以这里先算指纹、再问 `index_plan.该新建还是续做`。
    把这一步推到 Worker 里的坏法:调用方拿到 202 之后**以为要新建**,
    而 Worker 决定续做 —— 于是界面上显示的构建 id 和实际在动的不是一个。

    ## ⚠️ 维度不兼容当场拒,不派任务

    换了 Embedding 模型而维度不同,旧向量混进来算出的相似度**没有意义** ——
    而它不报错,只是排序变得莫名其妙。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "前端为这一次点击生成一个 UUID 放进 Idempotency-Key 头 —— "
                  "构建要跑真 Embedding,超时重发一次就白算一遍,"
                  "而**白算不报错**,只是慢一倍并且在用量报表上翻倍")
    体 = await request.json() if await request.body() else {}
    cfg版本id = (体.get("检索配置版本id") or "").strip() or None
    模型id = (体.get("embedding模型id") or "").strip() or None

    with 事务() as c:
        老 = c.execute(text("""select id, status, target_ref from jobs
                             where project_id=:p and idempotency_key=:k"""),
                      {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            return {"job_id": 老["id"], "status": 老["status"],
                    "resource_id": (老["target_ref"] or {}).get("index_build_id"),
                    "status_url": f"{前缀.format(project_id=project_id)}/jobs/{老['id']}",
                    "trace_id": None,
                    "note": "同一个幂等键 → **返回原任务,不新建**(没有白算一遍)"}

        kb = c.execute(text("""select id, name from knowledge_bases
                             where project_id=:p and id=:i and archived_at is null"""),
                       {"p": project_id, "i": kb_id}).mappings().first()
        if not kb:
            raise _错(404, "NOT_FOUND", "没有这个知识库", "回知识库列表重新进入")

        # ── 目标:这个知识库下**每篇文档的最新版本** ──────────────────
        # ⚠️ 只取最新版本,不取全部 —— 把历史版本一起索引进去的坏法:
        # 检索会同时命中「旧说法」和「新说法」,而**两条都带着像样的证据链**。
        版本们 = c.execute(text("""
            select dv.id, dv.document_id, dv.revision
              from document_versions dv
              join documents d on d.project_id=dv.project_id and d.id=dv.document_id
             where dv.project_id=:p and d.knowledge_base_id=:k
               and d.archived_at is null and dv.archived_at is null
               and d.disabled_at is null
               and dv.revision = (select max(dv2.revision) from document_versions dv2
                                   where dv2.project_id=dv.project_id
                                     and dv2.document_id=dv.document_id
                                     and dv2.archived_at is null)
             order by dv.document_id
        """), {"p": project_id, "k": kb_id}).mappings().all()
        if not 版本们:
            raise _错(422, "NOTHING_TO_INDEX", "这个知识库里没有可索引的资料",
                      "先加资料。**空索引不是「建好了的索引」** —— "
                      "它检索时返回空,而那和「没建索引」在界面上长得一样")

        版本id们 = [r["id"] for r in 版本们]
        片段们 = c.execute(text("""
            select id, document_version_id, chunker_version, parser_version
              from chunks
             where project_id=:p and document_version_id = any(:vs)
        """), {"p": project_id, "vs": 版本id们}).mappings().all()
        if not 片段们:
            raise _错(422, "NOTHING_TO_INDEX",
                      "这些资料一个片段都没有 —— **有版本没片段**",
                      "这是服务端不一致(版本和片段是同一个事务写的)。请报给运维")

        # ⚠️ **切片器/解析器版本从行上读,不从代码常量读。**
        # 从常量读会隐含「库里的片段是当前版本切的」,而它失效时不报错。
        切版本 = sorted({r["chunker_version"] for r in 片段们})
        解版本 = sorted({r["parser_version"] for r in 片段们})
        if len(切版本) > 1 or len(解版本) > 1:
            raise _错(422, "MIXED_CHUNKER_VERSIONS",
                      f"这些片段是不同版本切出来的(切片器 {切版本}、解析器 {解版本})",
                      "**一个混血索引不会报错,只会答得怪** —— "
                      "一半旧边界一半新边界。先把受影响的文档重新发一版")

        # ── 检索配置 ────────────────────────────────────────────────
        if cfg版本id:
            cfg = c.execute(text("""select * from retrieval_config_versions
                                  where project_id=:p and id=:i"""),
                            {"p": project_id, "i": cfg版本id}).mappings().first()
            if not cfg:
                raise _错(404, "NOT_FOUND", "没有这个检索配置版本", "回配置页选一个")
        else:
            cfg = c.execute(text("""select * from retrieval_config_versions
                                  where project_id=:p
                                  order by created_at desc limit 1"""),
                            {"p": project_id}).mappings().first()
            if not cfg:
                raise _错(422, "NO_RETRIEVAL_CONFIG", "这个项目还没有检索配置版本",
                          "检索配置决定召回方式、候选数、上下文预算 —— "
                          "**没有它就没有「这次构建是按什么口径建的」**,"
                          "两次构建的结果也就不可比。先建一个配置版本")
        问 = IP.校验检索配置(dict(cfg))
        if 问:
            raise _错(422, "BAD_RETRIEVAL_CONFIG", 问[0][:200],
                      "这个检索配置本身有问题,按它建出来的索引检索时"
                      "**不报错但答不对**:\n· " + "\n· ".join(问[:4]))

        # ── Embedding 模型与维度 ────────────────────────────────────
        # ⚠️ **没有默认模型 —— 两个来源都没有就当场拒。**
        # 「默认用哪个 Embedding」不该由代码猜:登记表里有 mock,
        # 而猜中 mock 的代价是**一个看起来完全正常的假索引**
        # (mock 向量的相似度在数据形状上和真的一模一样)。
        # 让人选一次是廉价的;一个建错模型的索引要重算全部向量才能纠正。
        模型id = 模型id or 上一次的模型(c, project_id, kb_id)
        if not 模型id:
            raise _错(422, "EMBEDDING_MODEL_REQUIRED",
                      "要指定 embedding模型id —— 这个知识库还没建过索引",
                      "没有「默认模型」是有意的:登记表里有 mock,而**猜中 mock 会建出"
                      "一个看起来完全正常的假索引**。产真向量的有:"
                      + "、".join(AD.有哪些真的()),
                      field_errors={"embedding模型id": "第一次建索引必须显式给"})
        try:
            期望维度 = AD.维度(模型id)
        except AD.认不出这个模型 as e:
            raise _错(422, "EMBEDDER_UNAVAILABLE", str(e).split("\n")[0][:200],
                      "这个 Embedding 模型没登记 —— 见 knowledge/adapters.py 的 `登记`。"
                      "**认不出的不退回 mock**:退回 mock 会把「模型没配好」"
                      "翻译成「效果不好」")
        混 = c.execute(text("""select distinct dim from embeddings
                            where project_id=:p and model_id=:m"""),
                      {"p": project_id, "m": 模型id}).scalars().all()
        坏维 = [d for d in 混 if d != 期望维度]
        if 坏维:
            raise _错(422, "DIM_MISMATCH",
                      f"库里这个模型已有 {坏维} 维的向量,而现在的适配器给 {期望维度} 维",
                      "**混进旧索引的向量算出来的相似度没有意义** —— 而它不报错,"
                      "只是排序变得莫名其妙。要换维度就换一个 model_id")

        指纹 = IP.输入指纹(**{
            "知识库id": kb_id, "文档版本id们": 版本id们,
            "检索配置版本id": cfg["id"], "embedding模型id": 模型id,
            "embedding维度": 期望维度,
            "切片器版本": 切版本[0], "解析器版本": 解版本[0],
        })
        上次 = c.execute(text("""select id, status, input_hash as 输入指纹
                              from index_builds
                             where project_id=:p and knowledge_base_id=:k
                               and archived_at is null
                             order by created_at desc limit 1"""),
                        {"p": project_id, "k": kb_id}).mappings().first()
        怎么办, 为什么 = IP.该新建还是续做(构建=dict(上次) if 上次 else None,
                                  现在的指纹=指纹)
        if 怎么办 == "续做":
            # ⚠️ **不新建。** 续做一个输入没变的构建,已完成的片段会被跳过 ——
            # 而新建一个等于把那些向量重算一遍(白花钱,且不报错)。
            构建id = 上次["id"]
        else:
            构建id = _新id("ib")
            org = c.execute(text("select organization_id from projects where id=:p"),
                            {"p": project_id}).scalar()
            c.execute(text("""insert into index_builds
                (id, organization_id, project_id, knowledge_base_id,
                 retrieval_config_version_id, embedding_model_id, embedding_dim,
                 status, input_hash, created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:k,:r,:m,:d,:st,:h, now(), :by, now(), 1)"""),
                      {"i": 构建id, "o": org, "p": project_id, "k": kb_id,
                       "r": cfg["id"], "m": 模型id, "d": 期望维度,
                       "st": "排队中", "h": 指纹, "by": me.user_id})

        # Job 和构建行在**同一个事务**里(照 workflows_api 的形状)——
        # 分成两件独立的事,它们之间一定有窗口:写库成功但没派任务 →
        # 任务永远不跑而库里它是「排队中」;派了但写库回滚 → Worker 捞到幽灵。
        org = org if 怎么办 != "续做" else c.execute(
            text("select organization_id from projects where id=:p"),
            {"p": project_id}).scalar()
        job = _新id("job")
        c.execute(text("""insert into jobs
            (id, organization_id, project_id, type, target_ref, status, attempts,
             max_attempts, idempotency_key, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'index_build', cast(:t as jsonb),'排队中',0,3,:k,
                    now(), :by, now(), 1)"""),
                  {"i": job, "o": org, "p": project_id,
                   "t": _json.dumps({"index_build_id": 构建id}),
                   "k": idempotency_key, "by": me.user_id})

    return {"job_id": job, "status": "排队中", "resource_id": 构建id,
            "status_url": f"{前缀.format(project_id=project_id)}/jobs/{job}",
            "trace_id": None,
            "怎么办": 怎么办, "为什么": 为什么,
            "输入指纹": 指纹, "embedding模型id": 模型id, "embedding维度": 期望维度,
            "片段数": len(片段们), "文档版本数": len(版本id们),
            "note": ("**202 —— 一个向量都还没算。** 去 status_url 看进度。"
                     "建完之后这个知识库的「能检索吗」才会变成「能」")}


def 上一次的模型(c, 项目, 知识库id):
    """这个知识库上一次用的 Embedding 模型。**没有就返回 None,不猜一个。**

    为什么优先用上一次的:换模型是**显式决定**(旧向量不能混用)。
    默认跟着上一次走,可以让「重建一次」不至于顺手把模型也换了 ——
    而换了模型的重建会把全部向量重算一遍,且**不报错**。
    """
    return c.execute(text("""select embedding_model_id from index_builds
                          where project_id=:p and knowledge_base_id=:k
                            and embedding_model_id is not null
                            and archived_at is null
                          order by created_at desc limit 1"""),
                     {"p": 项目, "k": 知识库id}).scalar()
