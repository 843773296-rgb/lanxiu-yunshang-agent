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

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

import adapters as AD
import index_plan as IP
import retrieval as RT
import reranker as RR
from db import 连接
from deps import 身份, 要权限, _错

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
