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
# ⚠️ `语料可见` 在 runtime/ —— **显式加进来,不靠 `import retrieval` 顺带**。
# 那样会让 import 顺序变成隐含依赖:把这一行挪到 retrieval 前面就 ImportError,
# 而「为什么挪一下 import 就炸」读起来跟这个模块毫无关系。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime"))

import json as _json
import os as _os
import uuid as _uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

import adapters as AD
import perms as PM          # 角色词表 —— 语料 ACL 用的就是这一套
import index_plan as IP
import ingest as IN
import parser as PS
import 语料可见 as KV
import upload_rules as UR
import 拆文档 as SP
import retrieval as RT
import reranker as RR
import storage as OS_
import usage as UG
from db import 连接, 事务
from deps import 身份, 要权限, _错


def _新id(前缀):
    return f"{前缀}_{_uuid.uuid4().hex[:12]}"

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _直调默认(值, 兜底):
    """FastAPI 的 `Query(x)` 默认值在**直接调用**这个函数时不是 `x`。

    它是 `fastapi.params.Query` 的实例,而且 **truthy** —— 于是
    `if 某参数:` 为真、`limit` 变成一个对象,绑进 SQL 就报
    `cannot adapt type 'Query'`。

    > 一个默认值是 `None` 的参数,和一个默认值是 `Query(None)` 的,
    > **在函数签名上长得几乎一样** —— 前者直接调用能用,后者当场炸。

    ⚠️ 判的是**它是不是 Query 对象**,不是「它是不是我期望的类型」——
    后者会把一个合法但意外的值悄悄换成兜底,而那是另一种错(更难查)。

    为什么要支持直接调用:`tests/integration/test_chunk_browse.py`
    **刻意不起服务**(起服务的测试要外部状态,进门禁会变成随机拦路),
    所以它直接调端点函数。那是合理用法,归一化就该在这儿。
    """
    from fastapi.params import Query as _Q
    return 兜底 if isinstance(值, _Q) else 值


@router.get(前缀 + "/knowledge-bases")
def 知识库列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
           limit: int = Query(20, ge=1, le=100)):
    """知识库列表。**片段数和「索引到哪一版」要同时给。**

    只给片段数的话,「资料进来了」和「索引建好了」会被当成同一件事 ——
    而一个有 71 个片段、0 个索引的知识库,检索时返回的是空。
    """
    # 口径唯一源头 —— 和检索那条 where 片段是同一个函数
    权限, 权限参 = KV.where片段(这个人的角色们=[me.role], 知识库别名="kb")
    with 连接() as c:
        rs = c.execute(text(f"""
            select kb.id, kb.name, kb.status, kb.updated_at,
                   (select count(*) from documents d
                     where d.project_id=kb.project_id and d.knowledge_base_id=kb.id
                       and d.archived_at is null) 文档数,
                   -- ⚠️ **这个数要按权限过滤。** 2026-10-07 补:
                   -- > 一个「片段数 71」和一个「你能看到的片段数 71」,
                   -- > 在那个数字上长得一模一样 —— 而 ACL 一旦填上,
                   -- > 它就在泄露他看不到的文档有多少内容。
                   -- 补这一条的时机是**现在** —— 两级 ACL 今天全空,
                   -- 所以加过滤数字不变;等填了再改就得解释「为什么变小了」。
                   (select count(*) from chunks ch
                      join document_versions dv
                        on dv.project_id=ch.project_id and dv.id=ch.document_version_id
                      join documents d
                        on d.project_id=dv.project_id and d.id=dv.document_id
                     where ch.project_id=kb.project_id
                       and d.knowledge_base_id=kb.id
                       and {权限}) 片段数,
                   -- ⚠️⚠️ **再给一个「最新版的片段数」(2026-10-08 补)。**
                   --
                   -- 上面那个 `片段数` 数的是**全部版本**,而索引只收
                   -- `max(revision)` 那一版(`index_plan` 的口径,切片栏目也一样)。
                   -- 于是一篇文档改过第二版之后,这两个数就**永远对不上**:
                   -- 实测 project_demo_a 的「澜绣业务拍板」= 97 / 89。
                   --
                   -- > 一个「这个库有 97 个片段」和一个「这个库有 89 个片段
                   -- > 检索得到」,**在那个 97 上长得一模一样** ——
                   -- > 而人看到 97、检索却只能命中 89,会去查检索。
                   --
                   -- 这个数**不改 `片段数` 的含义**(那样会悄悄改掉界面上一个
                   -- 已经在用的数,而且改完也看不出来);它是**多给一个**。
                   (select count(*) from chunks ch
                      join document_versions dv
                        on dv.project_id=ch.project_id and dv.id=ch.document_version_id
                      join documents d
                        on d.project_id=dv.project_id and d.id=dv.document_id
                     where ch.project_id=kb.project_id
                       and d.knowledge_base_id=kb.id
                       and dv.revision = (select max(dv2.revision)
                                            from document_versions dv2
                                           where dv2.project_id=d.project_id
                                             and dv2.document_id=d.id)
                       and {权限}) 最新版片段数,
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
        """), {"p": project_id, "n": limit, **权限参}).mappings().all()
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
        # ⚠️ 旧版本那几条**说出来**:它们在库里、不在索引里,
        # 而「有 8 条检索不到」静默发生的话,表现是「这个 RAG 漏东西」。
        d["旧版本的片段数"] = d["片段数"] - d["最新版片段数"]
        d["片段数怎么读"] = (
            None if not d["旧版本的片段数"] else
            f"这个库一共 {d['片段数']} 个片段,而**索引只收最新版的 "
            f"{d['最新版片段数']} 个** —— 另外 {d['旧版本的片段数']} 条属于"
            f"文档的旧版本,留着是为了能翻回历史,**但它们检索不到**。"
            f"这不是索引不完整")
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

    ⚠️ `成员数` 要和知识库的 **`最新版片段数`** 对,不是和 `片段数` 对 ——
    索引只收 `max(revision)` 那一版。2026-10-08 修:
    > 一次「索引不完整」和一次「那几条属于文档的旧版本」,
    > **在「成员数 < 片段数」这件事上长得一模一样** ——
    > 而前者要去查谁写坏了数据,后者完全正常。
    而一个真不完整的索引检索时只是「少返回几条」,不报错。
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


@router.get(前缀 + "/knowledge-bases/{kb_id}/chunks")
def 切片列表(project_id: str, kb_id: str,
         me: 身份 = Depends(要权限("查看有权配置")),
         document_id: str = Query(None),
         limit: int = Query(30, ge=1, le=200),
         offset: int = Query(0, ge=0)):
    """这个知识库的切片 —— **列表**。只读。

    业务 2026-10-07 要的「切片栏目」。切片级**权限**那一拍是不做
    (要收紧就拆成独立文档,见 `runtime/拆文档.py`),但**看得见**是要做的:
    一个人要能回答「我导进去的那段话到底被切成了什么样」。

    ## ⚠️ 这个接口最容易变成一个绕开检索权限的后门

    > 一个「检索过滤了」的系统,和一个「检索过滤了而切片列表没过滤」的,
    > **在那次检索上长得一模一样** —— 而那个人不检索、直接翻列表,
    > 就看到了全部语料。
    所以这里用的是**和检索同一个** `语料可见.where片段()`,不是另写一套。

    ## ⚠️ 只给**最新那一版**的片段

    `chunks` 绑的是 `document_version_id`,而一篇文档有多版。
    > 一份「18 篇文档的片段」和一份「18 篇文档所有历史版本的片段」,
    > **在那个列表上长得一模一样**(都是一堆片段)—— 而后者含着
    > 已经被改掉的内容,数量还是前者的几倍。
    索引取的也是 `max(revision)`,**列表跟索引一致**才有参考价值。

    ## ⚠️ 「在不在役索引里」必须显式说

    > 一个「在役索引里的片段」和一个「切出来了但没进任何索引」的,
    > **在那个列表上长得一模一样** —— 而后者检索不到,
    > 看起来却像语料里有。这一列正是在回答「我明明导入了为什么搜不到」。
    """
    # 见 `_直调默认` —— 直接调用时这几个默认值是 Query 对象,不是 None/30/0
    document_id = _直调默认(document_id, None)
    limit = _直调默认(limit, 30)
    offset = _直调默认(offset, 0)
    权限, 权限参 = KV.where片段(这个人的角色们=[me.role], 知识库别名="kb")
    条件 = "and d.id = :doc" if document_id else ""
    参 = {"p": project_id, "k": kb_id, "n": limit, "off": offset, **权限参}
    if document_id:
        参["doc"] = document_id
    with 连接() as c:
        if not c.execute(text("""select 1 from knowledge_bases
                                 where project_id=:p and id=:k
                                   and archived_at is null"""),
                         {"p": project_id, "k": kb_id}).first():
            raise _错(404, "NOT_FOUND", "没有这个知识库", "核对一下 id")
        # ⚠️ **顺序必须确定**,否则翻页会重复或漏 ——
        # 而「翻页漏了一条」和「那一条不存在」在界面上长得一模一样。
        基 = f"""
              from chunks ch
              join document_versions dv on dv.project_id=ch.project_id
                                       and dv.id=ch.document_version_id
              join documents d on d.project_id=dv.project_id and d.id=dv.document_id
              join knowledge_bases kb on kb.project_id=d.project_id
                                     and kb.id=d.knowledge_base_id
             where ch.project_id=:p and d.knowledge_base_id=:k
               and d.archived_at is null and dv.archived_at is null
               and d.disabled_at is null
               and dv.revision = (select max(dv2.revision) from document_versions dv2
                                   where dv2.project_id=dv.project_id
                                     and dv2.document_id=dv.document_id
                                     and dv2.archived_at is null)
               and {权限}
               {条件}
        """
        总 = c.execute(text(f"select count(*) {基}"), 参).scalar()
        # 见详情里那段:库级和片段级要分得开,否则每一行的「检索不到」
        # 看起来都像这一段自己的问题
        库索引数 = c.execute(text("""
            select count(*) from index_builds
             where project_id=:p and knowledge_base_id=:k
               and status='已就绪' and archived_at is null
        """), {"p": project_id, "k": kb_id}).scalar()
        rs = c.execute(text(f"""
            select ch.id, ch.document_version_id, d.id 文档id, dv.revision 版次,
                   dv.object_key, ch.ordinal, ch.section_path, ch.section_titles,
                   ch.token_count, ch.text_hash,
                   ch.chunker_version, ch.parser_version,
                   left(ch.text, 120) 正文预览, length(ch.text) 正文长度,
                   (select count(*) from index_members im
                      join index_builds ib on ib.project_id=im.project_id
                                          and ib.id=im.index_build_id
                     where im.project_id=ch.project_id and im.chunk_id=ch.id
                       and ib.status='已就绪' and ib.archived_at is null) 在役索引数
            {基}
             order by d.id, ch.ordinal, ch.id
             limit :n offset :off
        """), 参).mappings().all()
        # ── 混版本告警:**整库一起看,不受 document_id 筛选影响** ───────────
        # ⚠️ 第一版我拿上面那个带 `document_id` 条件的 `基` 来查,于是:
        # > 一个「这个库没有混版本」的告警,和一个「筛选后这一篇没有混版本」的,
        # > **在那个 `混着切的吗: false` 上长得一模一样** ——
        # > 而前者能建索引,后者不能。**筛选会让一条真告警消失。**
        # 索引构建那道闸(`MIXED_CHUNKER_VERSION`)是按 `knowledge_base_id`
        # 整库查的,所以这条告警也必须整库查 —— 判据要贴着它的含义。
        版本行 = c.execute(text(f"""
            select distinct ch.chunker_version 切, ch.parser_version 解
              from chunks ch
              join document_versions dv on dv.project_id=ch.project_id
                                       and dv.id=ch.document_version_id
              join documents d on d.project_id=dv.project_id and d.id=dv.document_id
              join knowledge_bases kb on kb.project_id=d.project_id
                                     and kb.id=d.knowledge_base_id
             where ch.project_id=:p and d.knowledge_base_id=:k
               and d.archived_at is null and dv.archived_at is null
               and d.disabled_at is null
               and dv.revision = (select max(dv2.revision) from document_versions dv2
                                   where dv2.project_id=dv.project_id
                                     and dv2.document_id=dv.document_id
                                     and dv2.archived_at is null)
               and {权限}
        """), {"p": project_id, "k": kb_id, **权限参}).mappings().all()
    切 = sorted({(r["切"] or "(空)") for r in 版本行})
    解 = sorted({(r["解"] or "(空)") for r in 版本行})
    混了 = len(切) > 1 or len(解) > 1
    return {
        "items": [dict(r) for r in rs],
        "total": 总,
        "limit": limit, "offset": offset,
        "切片器版本们": 切, "解析器版本们": 解,
        # ⚠️ **这条告警要放在顶部,不只是每行标个版本号。**
        # 混着切的片段进不了同一个索引(`MIXED_CHUNKER_VERSION`,而那道闸是
        # **整个知识库一起查**的)—— 也就是说这个库从此一个索引都建不出来。
        # 每行标版本号的话,人要自己把一屏行的版本号比一遍才看得出来;
        # 而那正是「看起来正常」的样子。
        "这个知识库有索引吗": bool(库索引数),
        "没索引会怎样": (None if 库索引数 else
                    f"**这个知识库一个索引都没建过** —— 下面这 {总} 段"
                    f"**全都检索不到**。每一行标的「检索不到」是这个原因,"
                    f"不是那一段自己的问题"),
        "混着切的吗": 混了,
        "混了会怎样": (None if not 混了 else
                   "这个知识库**建不出索引** —— 索引构建那一步会报 "
                   "MIXED_CHUNKER_VERSION,而它是整库一起查的。"
                   "先把这些文档版本重新切成同一个版本再建"),
    }


@router.get(前缀 + "/chunks/{chunk_id}")
def 切片详情(project_id: str, chunk_id: str,
         me: 身份 = Depends(要权限("查看有权配置"))):
    """一个切片的**详情**(全文 + 它的来路 + 它在哪些索引里)。只读。

    ## ⚠️ 「看不到」和「不存在」对外**同形**

    两者都回 404。否则这个接口就成了一个**存在性探测器**:
    拿 id 枚举一遍就能知道哪些 id 存在,而那本身是信息。
    理由里分开说(服务端日志看得到),对外一句话。
    """
    权限, 权限参 = KV.where片段(这个人的角色们=[me.role], 知识库别名="kb")
    with 连接() as c:
        r = c.execute(text(f"""
            select ch.id, ch.text, ch.section_path, ch.section_titles, ch.ordinal,
                   ch.token_count, ch.text_hash,
                   ch.chunker_version, ch.parser_version,
                   ch.document_version_id, dv.revision 版次, dv.object_key,
                   dv.content_hash, dv.source_info,
                   d.id 文档id, d.knowledge_base_id, d.acl_override,
                   kb.name 知识库名, kb.acl 知识库acl,
                   (dv.revision = (select max(dv2.revision) from document_versions dv2
                                    where dv2.project_id=dv.project_id
                                      and dv2.document_id=dv.document_id
                                      and dv2.archived_at is null)) 是最新版吗
              from chunks ch
              join document_versions dv on dv.project_id=ch.project_id
                                       and dv.id=ch.document_version_id
              join documents d on d.project_id=dv.project_id and d.id=dv.document_id
              join knowledge_bases kb on kb.project_id=d.project_id
                                     and kb.id=d.knowledge_base_id
             where ch.project_id=:p and ch.id=:i and {权限}
        """), {"p": project_id, "i": chunk_id, **权限参}).mappings().first()
        if not r:
            # ⚠️ 不区分「没这条」和「没权限」—— 见上面那段。
            raise _错(404, "NOT_FOUND", "没有这个切片",
                      "核对一下 id;**也可能是你的角色看不到它所属的那篇文档**")
        索引们 = c.execute(text("""
            select ib.id, ib.status, ib.embedding_model_id, ib.created_at
              from index_members im
              join index_builds ib on ib.project_id=im.project_id
                                  and ib.id=im.index_build_id
             where im.project_id=:p and im.chunk_id=:i and ib.archived_at is null
             order by ib.created_at desc
        """), {"p": project_id, "i": chunk_id}).mappings().all()
        # ⚠️ **库级和片段级要分得开。** 2026-10-07 在浏览器里看到这一页才发现:
        # 那个库一个索引都没建过,于是**每一条**详情都显示「这一段检索不到」——
        # > 一个「这一段没进索引」的告警,和一个「整个知识库从没建过索引」的,
        # > **在那个红框上长得一模一样** —— 前者让人去查这一段出了什么事,
        # > 后者只需要建一次索引。
        # 实测当时:两个库 0 个已就绪索引、1745 个片段**全部**检索不到。
        库索引数 = c.execute(text("""
            select count(*) from index_builds
             where project_id=:p and knowledge_base_id=:k
               and status='已就绪' and archived_at is null
        """), {"p": project_id, "k": r["knowledge_base_id"]}).scalar()
    d = dict(r)
    kacl, dacl = d.pop("知识库acl", None), d.pop("acl_override", None)
    可见, 为什么 = KV.定(知识库acl=kacl, 文档acl=dacl)
    d["谁看得到"] = sorted(可见)
    d["为什么是这些人"] = 为什么
    # ⚠️ 切片级权限**不做** —— 这里要说清,否则界面上看到「谁看得到」
    # 会被当成「可以在这里改」。
    d["能单独设这一段的权限吗"] = False
    d["为什么不能"] = (
        "切片是**派生物** —— 重建索引时整批重切,绑在它上面的权限会静默失效。"
        "要给某几段单独设权限,**把它们拆成独立文档**(业务 2026-10-07 拍的,"
        "业界也停在文档级)")
    d["在哪些索引里"] = [dict(x) for x in 索引们]
    d["在役索引数"] = sum(1 for x in 索引们 if x["status"] == "已就绪")
    # ⚠️ 这两条合起来回答「我明明导入了为什么搜不到」。
    d["检索得到吗"] = bool(d["在役索引数"]) and bool(d["是最新版吗"])
    d["这个知识库有索引吗"] = bool(库索引数)
    d["为什么检索不到"] = (
        None if d["检索得到吗"] else
        # ⚠️ **先说库级那一种** —— 它一真,片段级那两句就全是噪音
        ("**这个知识库一个索引都没建过** —— 它的片段**全都**检索不到,"
         "不是这一段的问题。去知识库页建一次索引"
         if not 库索引数 else
         ("它属于**旧版本**的文档 —— 索引只取每篇文档最新那一版"
          if not d["是最新版吗"] else
          "它**不在任何已就绪的索引里** —— 切出来了但没建索引,或者建完又归档了")))
    return d


@router.post(前缀 + "/documents/{doc_id}/split", status_code=201)
async def 拆成独立文档(project_id: str, doc_id: str, request: Request,
                 idempotency_key: str = Header(default=None,
                                               alias="Idempotency-Key"),
                 me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """把几个切片**拆成一篇独立文档**。入参
    `{要拆走的切片ids, 新文档acl, 目标知识库id?}`。

    这是业务 2026-10-07 那一拍的落点:**切片级权限不做**,要给某几段单独设
    权限就拆成独立文档。判定全在 `runtime/拆文档.py`(纯逻辑、零 IO),
    这里只负责取数、执行计划、算哈希。

    ## ⚠️ 返回的是**计划 + 欠账**,不是「成功」

    在役索引是快照(`index_members` 固定了一批 chunk_id),检索只认
    `index_build_id`:
    > 一次「权限已经收紧了」的拆分,和一次「拆了而在役索引还是旧快照」的,
    > **在那张 documents 表上长得一模一样** —— 那个人照旧检索得到这几段,
    > **直到重建索引完成并切换**。
    所以返回体里没有任何能当「做完了」用的键,`欠账` 永远非空。

    ## ⚠️ 原切片一条都不动

    `chunks` 不可变、而且绑的是**文档版本**。拆 = 新文档 + 新版本 +
    **复制**正文;原文档也新建一版(只含剩下的片段)。旧版的片段留着 ——
    索引只取 `max(revision)`,所以旧版自动退出召回,而证据链完好。

    ## ⚠️ 幂等:必须带 `Idempotency-Key`

    重复提交**天然会被挡住**(那些切片已经不在原文档最新版里,
    `拆文档.定()` 会抛「不在这篇文档最新那一版里」)—— 但那句话读起来像
    「我填错了」,而实际是「你已经拆过了」。
    > 一次「参数错了」和一次「这个请求已经成功过一次」,
    > **在那个 422 上长得一模一样**。
    所以 key 记进新文档的 `source_info`,重复提交直接回上次的结果。
    """
    体 = await request.json()
    ids = 体.get("要拆走的切片ids") or 体.get("要拆走的id们") or []
    新acl = 体.get("新文档acl")
    目标kb = (体.get("目标知识库id") or "").strip() or None
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "拆分会新建文档和版本 —— **重试必须能被认出来**,"
                  "否则一次网络超时后的重试会拆出第二篇文档")
    if not isinstance(ids, list) or not ids:
        raise _错(422, "VALIDATION", "没说要拆走哪几个切片",
                  "传 `要拆走的切片ids`。**不兜底成「全拆」或「不拆」** —— "
                  "一次「什么都没选」和一次「拆了个空文档」在那次调用上长得一样",
                  field_errors={"要拆走的切片ids": "必填,至少一个"})

    with 连接() as c:
        # ── 幂等:这个 key 拆过了吗 ────────────────────────────────────
        旧 = c.execute(text("""
            select id, knowledge_base_id, source_info from documents
             where project_id=:p and source_info->>'幂等键'=:k"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 旧:
            return {"已经拆过了": True,
                    "新文档id": 旧["id"],
                    "新文档所在知识库": 旧["knowledge_base_id"],
                    "说明": "这个 Idempotency-Key 已经成功拆过一次 —— "
                           "**原样返回上次的结果,没有再拆一遍**",
                    "欠账": ["拆完**还没生效**:在役索引是快照,"
                            "那个人照旧检索得到这几段,直到重建索引完成并切换"]}
        d = c.execute(text("""
            select d.id, d.organization_id, d.knowledge_base_id, d.acl_override,
                   kb.acl 知识库acl
              from documents d
              join knowledge_bases kb on kb.project_id=d.project_id
                                     and kb.id=d.knowledge_base_id
             where d.project_id=:p and d.id=:i and d.archived_at is null"""),
                      {"p": project_id, "i": doc_id}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这篇文档", "核对一下 id")
        # 最新那一版 + 它的全部片段(拆文档的判定要整份清单)
        版 = c.execute(text("""
            select id, revision, object_key, source_info from document_versions
             where project_id=:p and document_id=:i and archived_at is null
             order by revision desc limit 1"""),
                       {"p": project_id, "i": doc_id}).mappings().first()
        if not 版:
            raise _错(422, "NO_VERSION", "这篇文档还没有任何版本",
                      "先给它发一个版本(POST /documents/{id}/versions)")
        片段们 = [dict(x) for x in c.execute(text("""
            select id, ordinal, text, text_hash, token_count,
                   section_path, section_titles, chunker_version, parser_version
              from chunks where project_id=:p and document_version_id=:v
             order by ordinal"""), {"p": project_id, "v": 版["id"]}).mappings()]
        目标kb = 目标kb or d["knowledge_base_id"]
        目标acl = c.execute(text("""select acl from knowledge_bases
                                 where project_id=:p and id=:k
                                   and archived_at is null"""),
                           {"p": project_id, "k": 目标kb}).scalar_one_or_none() \
            if 目标kb != d["knowledge_base_id"] else d["知识库acl"]
        if 目标kb != d["knowledge_base_id"]:
            if not c.execute(text("""select 1 from knowledge_bases
                                     where project_id=:p and id=:k
                                       and archived_at is null"""),
                             {"p": project_id, "k": 目标kb}).first():
                raise _错(404, "NOT_FOUND", "没有这个目标知识库", "核对一下 id")

    # ── 判定:全在纯逻辑里 ──────────────────────────────────────────
    try:
        计划 = SP.定(源文档片段=片段们, 要拆走的id们=ids,
                  源知识库acl=d["知识库acl"], 源文档acl=d["acl_override"],
                  目标知识库acl=目标acl, 新文档acl=新acl,
                  目标知识库id=目标kb, 源知识库id=d["knowledge_base_id"])
    except SP.判不了 as e:
        # ⚠️ `拆不了` 继承 `语料可见.判不了`,所以这一个 except 兜住两边。
        # **不降级、不猜** —— 把它那句带「怎么办」的话原样传出去(§19.1)。
        raise _错(422, "SPLIT_REFUSED", str(e).split("\n")[0][:300], str(e)[:900])

    # ── 执行:一个事务 ─────────────────────────────────────────────
    新文档id, 新版本id = _新id("doc"), _新id("dv")
    原新版本id = _新id("dv")
    def _哈(片们):
        # ⚠️ **从剩下/搬走的那些片段正文算**,不照抄上一版的 content_hash ——
        # `object_key` 指向的原文件没变(它还含着拆走的那几段),
        # 而「这份资料变没变」全靠那一列。照抄就让那一列从此骗人。
        文 = "\n\n".join(x["text"] for x in 片们)
        return UR.内容哈希(文.encode("utf-8"))
    按id = {x["id"]: x for x in 片段们}
    搬 = [按id[x["源片段id"]] for x in 计划["搬过去的片段"]]
    剩 = [按id[x["源片段id"]] for x in 计划["原文档留下的片段"]]
    with 事务() as c:
        c.execute(text("""insert into documents
            (id, organization_id, project_id, knowledge_base_id, acl_override,
             source_info, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:k, cast(:acl as jsonb), cast(:si as jsonb),
                    now(), :by, now(), 1)"""),
                  {"i": 新文档id, "o": d["organization_id"], "p": project_id,
                   "k": 目标kb,
                   "acl": _json.dumps(计划["新文档"]["acl_override"],
                                      ensure_ascii=False),
                   "si": _json.dumps({**计划["新文档"]["source_info"],
                                      "幂等键": idempotency_key,
                                      "拆自文档": doc_id,
                                      "拆自版本": 版["id"]}, ensure_ascii=False),
                   "by": me.user_id})
        for 版id, 文档, 片们, 说 in ((新版本id, 新文档id, 搬, "拆出来的"),
                                 (原新版本id, doc_id, 剩, "原文档剩下的")):
            c.execute(text("""insert into document_versions
                (id, organization_id, project_id, document_id, object_key,
                 content_hash, effective_at, revision, source_info,
                 created_at, created_by, updated_at)
                values (:i,:o,:p,:d,:ok,:h, now(), :rev, cast(:si as jsonb),
                        now(), :by, now())"""),
                      {"i": 版id, "o": d["organization_id"], "p": project_id,
                       "d": 文档,
                       # 原文档照抄上一版的键(原文件没变);新文档没有原文件
                       "ok": (版["object_key"] if 文档 == doc_id else None),
                       "h": _哈(片们),
                       "rev": (版["revision"] + 1 if 文档 == doc_id else 1),
                       "si": _json.dumps(
                           {"存储": SP.派生自拆分, "这一版是": 说,
                            "拆自版本": 版["id"], "幂等键": idempotency_key},
                           ensure_ascii=False),
                       "by": me.user_id})
            for n, s in enumerate(片们):
                c.execute(text("""insert into chunks
                    (id, organization_id, project_id, document_version_id,
                     section_path, section_titles, ordinal, text, text_hash,
                     token_count, chunker_version, parser_version,
                     created_at, created_by, revision)
                    values (:i,:o,:p,:v,:sp, cast(:st as jsonb),
                            :ord,:t,:th,:tk,:cv,:pv, now(), :by, 1)"""),
                          {"i": _新id("ch"), "o": d["organization_id"],
                           "p": project_id, "v": 版id,
                           "sp": s["section_path"],
                           "st": _json.dumps(s["section_titles"] or [],
                                             ensure_ascii=False),
                           # 两边都**重排成 0..n-1 连续**(计划里算好的那一份)
                           "ord": n, "t": s["text"], "th": s["text_hash"],
                           "tk": s["token_count"],
                           # ⚠️ **沿用源片段记的版本,不读当前常量。**
                           # MIXED_CHUNKER_VERSION 是整个知识库一起查的 ——
                           # 重切一遍这个库从此一个索引都建不出来,
                           # 而那要到下一次重建才炸。
                           "cv": s["chunker_version"],
                           "pv": s["parser_version"], "by": me.user_id})
    return {
        "新文档id": 新文档id, "新文档所在知识库": 目标kb,
        "新文档版本id": 新版本id, "搬过去几段": len(搬),
        "原文档新版本id": 原新版本id, "原文档新版次": 版["revision"] + 1,
        "原文档还剩几段": len(剩),
        "权限": 计划["权限"], "版本": 计划["版本"],
        # ⚠️ **没有「成功」这个键。** 见函数文档:在役索引是快照。
        "欠账": 计划["欠账"],
        "下一步": "重建这个知识库的索引并切换 —— **在那之前权限没有生效**,"
                "原来能看到这几段的人照旧检索得到",
    }


@router.post(前缀 + "/retrieval-tests")
async def 检索实验室(project_id: str, request: Request,
               me: 身份 = Depends(要权限("运行评测"))):
    """跑一次检索,返回**整条链路**(§9.5)。

    入参:`{索引构建id, 问题, 要精排?, 要生成?}`

    ⚠️ **同步** —— 人坐在那儿等结果,异步反而更难用。
    代价:一次调用会**真调一次 Claude 精排**(几百毫秒到两秒),
    用量记在记录仪日志里。传 `要精排=false` 就只走向量,
    而返回里会说清「只走向量的排序不可靠」。

    ⚠️ `要生成=true` 会**再**调一次模型(照着选中的证据生成答案)。
    **默认关着** —— 而「这次没要」和「这一版没做」在空答案上长得一样,
    所以 `链["生成"]["为什么"]` 会说是哪一种。
    """
    体 = await request.json()
    构建id = (体.get("索引构建id") or "").strip()
    问题 = (体.get("问题") or "").strip()
    要精排 = 体.get("要精排")
    要精排 = True if 要精排 is None else bool(要精排)
    # ⚠️ 生成**默认不做**(多一次模型调用)。而「这次没要」和「这一版没做」
    # 在那个空答案上长得一样 —— 所以 `retrieval` 会把哪一种写进 `链["生成"]`。
    要生成 = bool(体.get("要生成"))
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
            # ⚠️ 传的是**角色**,不是 `me.grants`(专项授权)。
            # `perms.判(能力, 角色, 专项)` 里专项是**能力级**授权 ——
            # 混进来就让它成了绕过语料 ACL 的万能钥匙
            # (`perms.判` 自己写着「否则专项授权就变成万能钥匙」)。
            # 而身份模型今天是一人一角色,所以这里是单元素清单。
            链 = RT.检索(c, 项目=project_id, 构建id=构建id, 问题=问题,
                       这个人的角色们=[me.role], 要精排=要精排,
                       要生成=要生成)
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

    # ── 记账:**真花过钱的那次,要在库里留下一行** ────────────────────
    # ⚠️ 这一步失败**不许把检索结果吞掉** —— 人已经等到答案了,
    # 而记账是我们内部的事。但也**不许静默**:记不上账的调用是黑的。
    # (和澜绣那条 A2「上报失败不影响业务但必须留痕」同一个形状。)
    链["记账"] = 记这次检索的账(project_id, me, 链)
    # ── 存档(业务 2026-10-08 要的那个栏目)────────────────────────────
    # ⚠️ 顺序:**记账在前,存档在后** —— 存档要把 trace_id 一起存下来,
    # 而那是记账那一步才有的。反过来写的话,`trace_id` 永远是空的,
    # 而那一列空着**不报错**:表现是「这条试跑查不到它花了多少钱」。
    链["存档"] = 记一次试跑(project_id, me, 链, 构建id=构建id)
    return 链


def 记这次检索的账(project_id, me, 链):
    """把这一次**真花过钱的每一步**写进 `usage_ledger`。返回一段能显示的说明。

    ⚠️ 2026-10-08 起这一次检索可能调**两次**模型(精排 + 生成),外加
    改写那一次。原来这个函数叫「记一次精排的账」,只记精排 ——
    > 一笔「没花钱」和一笔「花了而没记上」,**在账本的总额上长得一模一样**,
    > 而后者要等账单来了才发现,那时候已经追不回是哪一次调用了。
    所以这里按**步骤**逐条记,每一步一个 `event_key`(防重复计费靠它)。

    ⚠️ **改写那一次没记在这儿** —— 它在 `rewriter` 里只进了记录仪,
    没进账本。这是个已知的缺口,写在这儿而不是等人发现:
    改写用量在 `llmtrace` 日志里查得到,而**账本里看不到它**。
    补它要先决定「改写算哪个 resource」(它不是 rerank 也不是 generate),
    那是业务口径,不自己拍。

    ## 为什么写在这里而不是 reranker 里

    `reranker.py` 不开连接、不碰库 —— 它是纯调用 + 纯判据。
    账本要在**事务**里写(契约:用量账目只追加、靠 event_key 防重复计费),
    而事务是接口层的事。

    ## trace 和账本一起写

    `usage_ledger.trace_id` 2026-09-28 补了真外键,所以这里必须先有 trace ——
    **一笔查不到出处的钱,在总额里和真的一样**。
    """
    精 = (链 or {}).get("精排") or {}
    生 = (链 or {}).get("生成") or {}
    # 哪些步骤**真调了模型**。`阶段` 进 `spans.stage`,`资源` 进 `usage_ledger`。
    # ⚠️ 这张表就是「这次检索花了几笔钱」的唯一来源 —— 新加一步调模型的,
    # **加在这里**,否则它的花销在账本里是黑的(而总额看起来完全正常)。
    步骤 = []
    if 精.get("做了"):
        步骤.append(dict(步="精排", 阶段="rerank", 资源=UG.精排, 数据=精,
                       细=dict(模型=精.get("模型"), 精排了几条=精.get("精排了几条"),
                              精排器版本=精.get("精排器版本"))))
    if 生.get("做了"):
        步骤.append(dict(步="生成", 阶段="generate", 资源=UG.生成, 数据=生,
                       细=dict(模型=生.get("模型"), 生成器版本=生.get("生成器版本"),
                              够不够答=生.get("够不够答"),
                              引用没通过校验的=生.get("引用没通过校验的"))))
    if not 步骤:
        return {"记了吗": False,
                "为什么": "这次一步模型都没调(要精排=false 且没要生成),"
                        "没有花销可记"}
    # mock 也记 —— 但 source='mock',界面上要能一眼看出这笔不是真的
    各步, 行数, token数 = [], 0, 0
    try:
        with 事务() as c:
            org = c.execute(text("select organization_id from projects where id=:p"),
                            {"p": project_id}).scalar()
            tid = _新id("tr")
            c.execute(text("""
                insert into traces (id, organization_id, project_id, request_id,
                    environment, started_at, ended_at, end_reason, created_at, created_by)
                values (:i,:o,:p,:rq,:e, now(), now(), 'completed', now(), :u)"""),
                      {"i": tid, "o": org, "p": project_id, "rq": tid,
                       "e": _os.environ.get("APP_ENV", "development"), "u": me.user_id})
            for 步 in 步骤:
                c.execute(text("""
                    insert into spans (id, organization_id, project_id, trace_id,
                        stage, output_ref, started_at, ended_at, created_at, created_by)
                    values (:i,:o,:p,:t,:st, cast(:orf as jsonb),
                            now(), now(), now(), :u)"""),
                          {"i": _新id("sp"), "o": org, "p": project_id, "t": tid,
                           "st": 步["阶段"],
                           "orf": _json.dumps(步["细"], ensure_ascii=False),
                           "u": me.user_id})
                # ⚠️ 写库走 `usage.写进库` —— **只有那一处**。
                # A1 上报接口是第二个写入方,而两个写入方迟早分叉
                # (分叉的表现真发生过一次:两批账用了不同的 `source` 含义)。
                # ⚠️ `事件键` 带上**步骤名**:同一个 trace 里两笔账,
                # 键一样的话第二笔会被当成重复上报**静默丢掉** ——
                # 而那正好是「花了钱而账本上没有」。
                折 = UG.写进库(c, 组织=org, 项目=project_id, 谁=me.user_id,
                            用量=步["数据"].get("用量"), 模型=步["数据"].get("模型"),
                            提供方="anthropic", 资源=步["资源"],
                            事件键=f"{tid}:{步['阶段']}", trace_id=tid,
                            是mock=bool(步["数据"].get("是mock")),
                            调用方="检索实验室", _新id=_新id)
                # ⚠️ `资源` 和 `事件键` 带出来 —— 不是为了好看:
                # 防重复计费靠 `(project_id, event_key)` 唯一约束,
                # 两步的键**必须不同**,否则第二笔被 `do nothing` 静默丢掉。
                # 而「丢掉了」和「没花钱」在账本总额上长得一模一样,
                # 所以那条性质要能在外面被断言(e2e 第 ④.5 组)。
                各步.append({"步": 步["步"], "资源": 步["资源"],
                           "事件键": f"{tid}:{步['阶段']}", **折})
                行数 += int(折.get("写了几行") or 0)
                token数 += int(折.get("token合计") or 0)
    except UG.用量不对 as e:
        # **不吞** —— 但也不让它把检索结果一起毁掉
        return {"记了吗": False, "为什么": f"用量不合格,没记账:{str(e)[:200]}"}
    except Exception as e:
        return {"记了吗": False,
                "为什么": f"记账失败({type(e).__name__}: {str(e)[:160]})—— "
                        f"**检索结果是好的,但这次调用的花销在库里是黑的**。要人看"}
    return {"记了吗": 行数 > 0, "trace_id": tid, "各步": 各步,
            "写了几行": 行数, "token合计": token数,
            # ⚠️ 行数为 0 要说清**为什么**:`写进库` 对「用量里一个 token 都没有」
            # 的调用不写账(0 不是一笔花销)。不说的话,「没花钱」和
            # 「花了而没记上」在这个返回里长得一模一样。
            "为什么": (None if 行数 > 0 else
                    f"调了 {len(步骤)} 步模型,但用量里没有可计费的 token —— "
                    f"**没写账**(0 不是一笔花销)。要查这几次调用本身,"
                    f"看记录仪日志")}


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


# ══════════════════════════════════════════════════════════════════════
# M3:用量与成本(§17.1「用量与成本」那一组)
#
# ⚠️ 工作台上早就有「已知费用」和「费用未覆盖数量」两张卡,而且设计是对的
# (未覆盖的那些明说「钱是未知,不是 0」)。这条接口要答的是**那两张卡答不了**的:
#
#     这笔钱是**谁花的**、花在**哪一次调用**上。
#
# 只有总额的话,「门店助手今天花了多少」这个问题答不出来 ——
# 而那正是并行会话 A1 上报字段里「**调用方不能省**」的同一件事。
# ══════════════════════════════════════════════════════════════════════


@router.get(前缀 + "/usage")
def 用量与成本(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
          小时: int = Query(24, ge=1, le=24 * 90),
          limit: int = Query(50, ge=1, le=200)):
    """用量账目。**按「谁花的」分组,不是只给一个总额。**

    ⚠️ **未知要显示「未知」,不许显示 0**(契约:`amount_known=False`)。
    0 和未知在报表上差别巨大:0 意味着「跑了但不花钱」,
    未知意味着「花了多少还不知道」。
    """
    with 连接() as c:
        总 = c.execute(text("""
            select count(*) 行数,
                   coalesce(sum(quantity), 0) token数,
                   coalesce(sum(amount) filter (where amount_known), 0) 已知金额,
                   count(*) filter (where not amount_known) 金额未知的行数,
                   count(distinct trace_id) 调用次数
              from usage_ledger
             where project_id=:p and created_at > now() - (:h || ' hours')::interval
        """), {"p": project_id, "h": 小时}).mappings().first()
        # ⚠️ **按 resource + source 分组** —— `resource` 是花在什么上
        # (rerank / embed / generate),`source` 是谁提供的(anthropic / mock)。
        # 两者都要:一份 mock 的用量和真的在数据形状上一模一样,
        # 不分开的话「这个月花了多少」里混着一堆根本没花钱的 mock 调用。
        分组 = c.execute(text("""
            select resource, source, provider,
                   count(*) 行数, sum(quantity) token数,
                   count(distinct trace_id) 调用次数,
                   coalesce(sum(amount) filter (where amount_known), 0) 已知金额,
                   count(*) filter (where not amount_known) 金额未知的行数
              from usage_ledger
             where project_id=:p and created_at > now() - (:h || ' hours')::interval
             group by resource, source, provider
             order by sum(quantity) desc
        """), {"p": project_id, "h": 小时}).mappings().all()
        # ⚠️ **按调用方分组 —— 这是 A1 存在的全部理由。**
        # 只有「按用途」的话,「门店助手今天花了多少」答不出来:
        # 门店助手和管理后台自己的调用混在同一个 resource 里。
        按调用方 = c.execute(text("""
            select coalesce(caller, '(没标调用方)') 调用方, source, provider,
                   count(distinct trace_id) 调用次数, sum(quantity) token数,
                   count(*) filter (where not amount_known) 金额未知的行数,
                   coalesce(sum(amount) filter (where amount_known), 0) 已知金额
              from usage_ledger
             where project_id=:p and created_at > now() - (:h || ' hours')::interval
             group by 1, 2, 3
             order by sum(quantity) desc
        """), {"p": project_id, "h": 小时}).mappings().all()
        明细 = c.execute(text("""
            select u.id, u.created_at, u.resource, u.source, u.quantity, u.unit,
                   u.amount, u.amount_known, u.currency, u.trace_id, u.event_key,
                   -- ⚠️ 这三列是 2026-09-28 加的,而这条 SELECT 是加之前写的 ——
                   -- 于是 `caller` 在库里好好存着,**接口一个字都没传出去**。
                   -- 「一个标记了却传不出去的判据,等于没有判据」的又一例:
                   -- 写库那一侧全对,而看的人什么也看不到。
                   u.provider, u.caller, u.world_date,
                   s.stage, cast(s.output_ref as text) 产出
              from usage_ledger u
              left join spans s
                on s.project_id = u.project_id and s.trace_id = u.trace_id
             where u.project_id=:p
               and u.created_at > now() - (:h || ' hours')::interval
             order by u.created_at desc
             limit :n
        """), {"p": project_id, "h": 小时, "n": limit}).mappings().all()

    def _对外(r):
        d = dict(r)
        # ⚠️ **`金额` 这一项:未知就是 None,前端负责显示「未知」。**
        # 在这里填 0 的话,前端无论怎么写都救不回来了 ——
        # **一个被压成 0 的未知,在下游任何一层都分不出来。**
        d["参考价"] = float(d["amount"]) if d["amount_known"] and d["amount"] is not None else None
        d["参考价算不出吗"] = not d["amount_known"]
        d["是mock吗"] = (d["source"] == "mock")
        d["档"] = (d["event_key"] or "").rsplit(":", 1)[-1] or None
        return d

    真花钱的 = [g for g in 分组 if g["source"] != "mock"]
    return {
        "时间范围": f"最近 {小时} 小时",
        "合计": {
            "调用次数": 总["调用次数"] or 0,
            "token数": int(总["token数"] or 0),
            # ⚠️ **叫「参考价」不叫「费用」。** 计量按 token 算,价格只给参考 ——
            # 真账单还受批量折扣、协议价、账单延迟、DeepSeek 时段浮动影响。
            # > 一个被当成账单用的估算,比没有估算糟。
            "参考价": float(总["已知金额"] or 0),
            "算不出参考价的行数": 总["金额未知的行数"] or 0,
        },
        # ⚠️ 这一句是这条接口的**重点**:总额里有多少是「不知道」。
        # 不说的话,「已知金额 0.00」会被读成「这段时间没花钱」。
        # ⚠️ 这一句是这条接口的**重点**:参考价有多接近真账单。
        "参考价怎么读": (
            "**这是按标价估的参考价,不是账单。** 计量的硬事实是 token 数;"
            "钱是估的 —— 真账单还受批量折扣、企业协议价、外部账单延迟、"
            "DeepSeek 的时段浮动(同样的 token 差一倍)影响,这里一概不管。"
            + (f" ⚠️ 而且 {总['金额未知的行数']} 行**连参考价都算不出**"
               f"(那些模型没有价目表快照),所以 {float(总['已知金额'] or 0)} "
               f"连「全部的参考价」都不是"
               if (总["金额未知的行数"] or 0) else
               " 这段时间每一行都算得出参考价")),
        "为什么有算不出的": ("" if not (总["金额未知的行数"] or 0) else
                    "这些模型在 `pricing_versions` 里没有价目表快照 —— "
                    "**token 数是已知的,补一份快照就能重算**。"
                    "⚠️ 不编一个单价填进去:一个自信的错数比「算不出」糟得多"),
        "按用途": [dict(g) for g in 分组],
        "按调用方": [dict(g) for g in 按调用方],
        "真花过钱的用途数": len(真花钱的),
        "items": [_对外(r) for r in 明细],
        "next_cursor": None,
        "total": 总["行数"] or 0,
    }


# ══════════════════════════════════════════════════════════════════════
# A1 接收端:门店助手(应用层)上报一次模型调用
#
# ⚠️ **方向是单向的:澜绣推,管理后台收。** 管理后台绝不反过来查澜绣的库 ——
# 那会让两个台互相依赖,而「谁先起来」这种问题会在部署时才暴露。
#
# ⚠️ **这条接口不在规格 §17.1 的表里**,是 2026-09-28 按交割文档 A1 加的。
# 登记进契约表而不是偷偷加:没登记的接口不会出现在任何清单里。
# ══════════════════════════════════════════════════════════════════════

# 允许上报的资源类型。**白名单,不是随便什么字符串都收** ——
# 收了之后它会出现在「按用途」的报表里,而一个拼错的类型看起来像一种新用途。
_可上报的资源 = {UG.精排, UG.向量化, UG.生成}


@router.post(前缀 + "/model-calls", status_code=201)
async def 上报一次模型调用(project_id: str, request: Request,
                 idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
                 me: 身份 = Depends(要权限("运行评测"))):
    """应用层上报一次模型调用(A1)。

    入参:
        {调用方, 模型, 供应商, 资源?, 用量{input_tokens,...},
         耗时毫秒?, 成功?, 是mock?, 世界日期?, 外部trace?}

    ## ⚠️ 要 Idempotency-Key,而且它就是账本的事件键

    上报链的第一条规矩是**上报失败不能影响业务**(A2)——
    于是上报方会重试。重试必须不重复计费,所以幂等键是必须的。

    **它由上报方给**,因为只有上报方知道「这两次上报是不是同一次调用」。
    服务端生成的话,每次重试都是一个新事件,账上就多一笔。

    ## 「调用方」不能省

    没有它,管理后台收到一堆调用记录而分不清哪些是门店助手的、
    哪些是它自己的 —— **「门店助手今天花了多少」这个问题答不出来**,
    只答得出「一共花了多少」。

    ## 「世界日期」为什么要

    门店助手跑在**演示世界**里(世界停在某一天),而这条记录的时间戳是
    **真实时间**。两个时钟混在一张表里,**而且不报错** ——
    看到「这条调用发生在 09-28」时,答不出它指的是哪个 09-28。

    ⚠️ 不给就是 None,**服务端不拿今天顶上** —— 猜一个日期比没有日期糟:
    没有日期时人知道自己不知道,猜出来的日期看起来像真的。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "它就是账本的事件键,**由上报方给** —— 只有你知道"
                  "「这两次上报是不是同一次调用」。服务端生成的话,"
                  "每次重试都会变成一笔新账")
    体 = await request.json()
    调用方 = (体.get("调用方") or "").strip()
    模型 = (体.get("模型") or "").strip()
    供应商 = (体.get("供应商") or "").strip() or None
    资源 = (体.get("资源") or UG.生成).strip()
    用量 = 体.get("用量") or {}
    是mock = bool(体.get("是mock"))
    成功 = 体.get("成功")
    成功 = True if 成功 is None else bool(成功)
    世界日期 = (体.get("世界日期") or "").strip() or None
    耗时毫秒 = 体.get("耗时毫秒")
    外部trace = (体.get("外部trace") or "").strip() or None

    坏 = {}
    if not 调用方:
        坏["调用方"] = ("必填 —— 没有它,「门店助手今天花了多少」答不出来,"
                     "只答得出「一共花了多少」")
    if not 模型:
        坏["模型"] = "必填 —— 不同模型的单价差一个数量级"
    if not 是mock and not 供应商:
        坏["供应商"] = ("真跑的调用必须给供应商 —— **成本要按供应商算**。"
                     "实测跨供应商用错价目表会差 24 倍以上,而它不报错")
    if 资源 not in _可上报的资源:
        坏["资源"] = (f"只收 {sorted(_可上报的资源)} —— **不收任意字符串**:"
                   f"一个拼错的类型会在报表里看起来像一种新用途")
    if 世界日期:
        import re as _re
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", 世界日期):
            坏["世界日期"] = "要 YYYY-MM-DD(它是演示世界的**日历日**,不是时刻)"
    if 坏:
        raise _错(422, "VALIDATION", "上报的字段不合格",
                  "按 `澜绣云裳agent-两个台的功能交割.md` 里 A1 那一节的字段清单发",
                  field_errors=坏)

    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        # 幂等:同一个键已经上报过 → **返回原来那条,不新建 trace**。
        # ⚠️ 只查账本不够 —— 一次失败的调用没有账目(没有 token),
        # 但它照样该是幂等的。所以查的是 `traces.request_id`。
        老 = c.execute(text("""select id from traces
                             where project_id=:p and request_id=:k
                             order by created_at limit 1"""),
                       {"p": project_id, "k": idempotency_key}).scalar()
        if 老:
            return {"trace_id": 老, "记了吗": False,
                    "note": ("**同一个幂等键 → 返回原记录,没有重复计费。**"
                             "如果你以为这是第一次上报,那说明上一次其实成功了")}
        tid = _新id("tr")
        c.execute(text("""
            insert into traces (id, organization_id, project_id, request_id,
                environment, started_at, ended_at, end_reason, created_at, created_by)
            values (:i,:o,:p,:rq,:e, now(), now(), :er, now(), :u)"""),
                  {"i": tid, "o": org, "p": project_id, "rq": idempotency_key,
                   "e": _os.environ.get("APP_ENV", "development"),
                   # ⚠️ 失败的调用也要记 —— 只记成功的会让「失败花掉的时间」
                   # 变成黑的,而那正是排查「为什么这么慢」时最需要的数。
                   "er": ("completed" if 成功 else "failed"), "u": me.user_id})
        c.execute(text("""
            insert into spans (id, organization_id, project_id, trace_id, stage,
                input_ref, output_ref, started_at, ended_at, created_at, created_by, error)
            values (:i,:o,:p,:t,:st, cast(:ir as jsonb), cast(:orf as jsonb),
                    now(), now(), now(), :u, cast(:err as jsonb))"""),
                  {"i": _新id("sp"), "o": org, "p": project_id, "t": tid,
                   "st": 资源,
                   "ir": _json.dumps({"调用方": 调用方, "世界日期": 世界日期,
                                      "外部trace": 外部trace}, ensure_ascii=False),
                   "orf": _json.dumps({"模型": 模型, "供应商": 供应商,
                                       "耗时毫秒": 耗时毫秒, "是mock": 是mock},
                                      ensure_ascii=False),
                   "u": me.user_id,
                   # ⚠️ `spans.error` 是 **JSONB 列**,不是 TEXT。
                   # 第一版塞了个裸字符串,PostgreSQL 报
                   # `invalid input syntax for type json` —— 而它**只在失败路径上炸**:
                   # 成功的调用 error=None 一路绿。
                   #
                   # 这个错要是没被测到,表现会是:门店助手上报失败调用时收到 500,
                   # 于是按 A2 的规矩不影响业务、静默重试、永远失败 ——
                   # **失败调用的记录一条都不会有,而所有人都以为这条链是通的。**
                   # (同一族第三次:罕见分支里的必炸。)
                   "err": (None if 成功 else _json.dumps(
                       {"为什么": "上报方标记这次调用失败",
                        "谁说的": "应用层上报(A1)——**不是管理后台判的**"},
                       ensure_ascii=False))})
        记账 = None
        try:
            记账 = UG.写进库(c, 组织=org, 项目=project_id, 谁=me.user_id,
                          用量=用量, 模型=模型, 提供方=供应商, 资源=资源,
                          事件键=idempotency_key, trace_id=tid, 是mock=是mock,
                          调用方=调用方, 世界日期=世界日期, _新id=_新id)
        except UG.用量不对 as e:
            # ⚠️ **没有用量不算上报失败。** 一次失败的调用本来就没有 token,
            # 而它的「发生过、失败了、花了多少时间」仍然值得记 ——
            # trace 和 span 已经写进去了。
            记账 = {"记了吗": False, "为什么": str(e)[:220]}
    出 = {"trace_id": tid, "记了吗": bool(记账 and 记账.get("写了几行")),
          "记账": 记账, "调用方": 调用方, "世界日期": 世界日期}
    if not 成功:
        出["note"] = ("**这次调用标了失败,而记录照样留下了** —— "
                      "只记成功的调用会让「失败花掉的时间」变成黑的")
    if 世界日期 is None:
        出["提醒"] = ("没给世界日期 —— 这条记录只有真实时间戳。"
                    "**服务端不拿今天顶上**:猜一个日期看起来像真的,"
                    "而没有日期时人知道自己不知道")
    return 出


# ══════════════════════════════════════════════════════════════════════
# 检索试跑记录(业务 2026-10-08 要的那个栏目)
#
# ## 为什么要存
#
# 检索实验室跑一次,结果在页面上,**刷新就没了**。而「这一版检索好不好用」
# 要靠**攒下来的试跑**回答 —— 一次试跑是个印象,二十次才是个判断。
#
# ## ⚠️ 业务要的是「记录 chat 里的 RAG 检索」,而 chat 现在不走这条链
#
# chat 走的是澜绣那边的 V1/V2/V3,它们自己查知识(`mcp/kb`),
# **不经过这里的 `retrieval.检索()`**。所以这张表第一批数据全是实验室自己的试跑。
# > 一个「记录 chat 检索」的栏目,和一个**永远是空的**栏目,
# > **在那个页面上长得一模一样** —— 所以 `source` 这一列从第一天就在,
# > 列表上也写着现在有没有 chat 的记录(不写的话,空着看起来像「还没人用」)。
#
# ## 评价是 5 档,而「还没评」不是 0 分
#
# `rating` 可空,库里有 CHECK(1-5)。档位的中文名在下面 `评价档位` 里 ——
# 只给数字的话,「3 分」是什么意思每个人心里一套,而那让分数不可比。
# ══════════════════════════════════════════════════════════════════════

# ⚠️ **档位要有名字,不能只有数字。** 一个只有 1-5 的量表上,
# 「3」在不同人心里差别很大 —— 而平均分会把这种差别算进来,
# 算出一个看起来精确的数。名字把它钉住。
评价档位 = {
    1: "完全答错 / 帮不上",
    2: "找得不对,得自己重查",
    3: "勉强能用,还要补",
    4: "基本对,小改就能用",
    5: "正好是我要的",
}


def _答案档(链):
    """四档:答了 / 证据不够 / 这次没要 / 跑不成。

    ⚠️ **后两档都让答案是空的,而一个是选择、一个是故障。**
    合成一句「没有答案」的话,界面上那两种长得一模一样。
    库里有 CHECK 钉着这四个值。
    """
    生 = (链 or {}).get("生成") or {}
    if 生.get("做了"):
        return "答了" if 生.get("够不够答") else "证据不够"
    return "这次没要" if 生.get("哪一种") == "这次没要" else "跑不成"


def 记一次试跑(project_id, me, 链, *, 构建id, 来源="检索实验室"):
    """把这一次试跑存进 `retrieval_runs`。返回一段能显示的说明。

    ⚠️ **存不下来不许把检索结果吞掉**(和 `记这次检索的账` 同一个形状):
    人已经等到结果了,存档是我们内部的事。但也**不许静默** ——
    一次没存上的试跑,和一次没跑过的,在那个列表上长得一模一样。
    """
    try:
        生 = (链 or {}).get("生成") or {}
        with 事务() as c:
            r = c.execute(text("""select ib.knowledge_base_id, p.organization_id
                                   from index_builds ib
                                   join projects p on p.id = ib.project_id
                                  where ib.project_id=:p and ib.id=:i"""),
                          {"p": project_id, "i": 构建id}).mappings().first()
            if not r:
                return {"存了吗": False,
                        "为什么": f"查不到索引构建 {构建id} —— 没存这次试跑"}
            rid = _新id("rr")
            c.execute(text("""
                insert into retrieval_runs (id, organization_id, project_id,
                    index_build_id, knowledge_base_id, source, user_query,
                    rewritten_query, chain_snapshot, recall_count, selected_count,
                    context_token_count, answer_status, answer_output, trace_id,
                    created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:ib,:kb,:src,:q,:rq, cast(:chain as jsonb),
                        :rc,:sc,:tc,:ast, cast(:aout as jsonb), :tr,
                        now(), :u, now(), 1)"""),
                      {"i": rid, "o": r["organization_id"], "p": project_id,
                       "ib": 构建id, "kb": r["knowledge_base_id"], "src": 来源,
                       "q": 链.get("原问"), "rq": 链.get("改写"),
                       # ⚠️ 整条链原样存 —— **快照,不是引用**。
                       # 索引会被重建、文档会出新版本,而「当时它找到了哪几段」
                       # 是这条记录的全部价值(存引用的话,重建一次索引,
                       # 全部历史试跑的证据就指向了新内容)。
                       "chain": _json.dumps(链, ensure_ascii=False, default=str),
                       "rc": 链.get("召回数"), "sc": 链.get("选了几片"),
                       "tc": 链.get("用了多少token"), "ast": _答案档(链),
                       "aout": _json.dumps(
                           {"答案": 生.get("答案"), "够不够答": 生.get("够不够答"),
                            "缺什么": 生.get("缺什么"), "模型": 生.get("模型"),
                            "引用们": 生.get("引用们"),
                            "引用没通过校验的": 生.get("引用没通过校验的"),
                            "为什么没答": (None if 生.get("做了") else 生.get("为什么"))},
                           ensure_ascii=False, default=str),
                       "tr": ((链.get("记账") or {}).get("trace_id")), "u": me.user_id})
    except Exception as e:
        return {"存了吗": False,
                "为什么": f"存档失败({type(e).__name__}: {str(e)[:160]})—— "
                        f"**检索结果是好的,但这次试跑没进记录**。"
                        f"一次没存上的试跑,和一次没跑过的,在那个列表上长得一样"}
    return {"存了吗": True, "试跑id": rid,
            "下一步": "去「检索试跑」栏目给它打个分(5 档)—— "
                    "分数是这一版检索好不好用的唯一可比数据"}


@router.get(前缀 + "/retrieval-runs")
def 试跑列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
          limit: int = Query(50, ge=1, le=200),
          source: str = Query(None), 只看没评的: bool = Query(False)):
    """检索试跑列表。**分数、来源、答案那一档都要在列表上看得见。**

    ⚠️ 这一页回答的是「**这一版检索好不好用**」—— 不是「跑过几次」。
    所以汇总里是分档分布 + 平均分 + **还没评的有几条**,
    而平均分**带样本量**:3 条试跑算出的 4.3 和 30 条算出的 4.3 不是一回事。
    """
    limit = _直调默认(limit, 50)
    source = _直调默认(source, None)
    只看没评的 = bool(_直调默认(只看没评的, False))
    条件, 参 = ["rr.project_id = :p"], {"p": project_id, "n": limit}
    if source:
        条件.append("rr.source = :src")
        参["src"] = source
    if 只看没评的:
        条件.append("rr.rating is null")
    with 连接() as c:
        rs = c.execute(text(f"""
            select rr.id, rr.created_at, rr.created_by, rr.source, rr.user_query,
                   rr.rewritten_query, rr.recall_count, rr.selected_count,
                   rr.context_token_count, rr.answer_status, rr.answer_output,
                   rr.rating, rr.rating_reason, rr.rated_by, rr.rated_at,
                   rr.revision, rr.index_build_id, rr.knowledge_base_id,
                   kb.name kb_name
              from retrieval_runs rr
              left join knowledge_bases kb on kb.project_id = rr.project_id
                                          and kb.id = rr.knowledge_base_id
             where {' and '.join(条件)}
             order by rr.created_at desc
             limit :n
        """), 参).mappings().all()
        # ⚠️ 汇总**另算一次,不筛**:筛着看的时候那个平均分只代表筛出来的那几条,
        # 而人读到的是「这一版检索的平均分」。
        # (这个坑今天在切片栏目上踩过一次:混版本告警拿带筛选的查询算,
        #  于是一条真告警在筛选状态下消失。)
        总 = c.execute(text("""
            select count(*) 条数, count(rating) 评过的,
                   avg(rating)::numeric(10,2) 平均分,
                   count(*) filter (where source = 'chat') chat的
              from retrieval_runs where project_id = :p
        """), {"p": project_id}).mappings().first()
        分布 = {int(r["rating"]): r["几条"] for r in c.execute(text("""
            select rating, count(*) 几条 from retrieval_runs
             where project_id = :p and rating is not null
             group by rating order by rating"""), {"p": project_id}).mappings()}
    出 = []
    for r in rs:
        d = dict(r)
        出力 = d.pop("answer_output", None) or {}
        出.append({
            "id": d["id"], "什么时候": d["created_at"], "谁跑的": d["created_by"],
            "来源": d["source"], "问题": d["user_query"],
            "改写": d["rewritten_query"],
            "知识库": d["kb_name"] or d["knowledge_base_id"],
            "召回数": d["recall_count"], "选了几片": d["selected_count"],
            "用了多少token": d["context_token_count"],
            "答案那一档": d["answer_status"],
            # 列表上给**一句**答案就够;全文在详情里。
            "答案摘要": ((出力.get("答案") or "")[:80] or None),
            "评分": d["rating"],
            # ⚠️ 没评过给 **None,不是 0** ——「还没人评」和「评了最低档」
            # 在一个 0 上长得一模一样。
            "评分档位": (评价档位.get(d["rating"]) if d["rating"] else None),
            "评语": d["rating_reason"], "谁评的": d["rated_by"],
            "什么时候评的": d["rated_at"], "revision": d["revision"],
        })
    平均 = (float(总["平均分"]) if 总["平均分"] is not None else None)
    return {
        "items": 出, "total": len(出),
        "汇总": {
            "一共几条": 总["条数"], "评过的": 总["评过的"],
            "还没评的": (总["条数"] or 0) - (总["评过的"] or 0),
            "平均分": 平均,
            # ⚠️ **平均分要带样本量,而且样本太少要说出来。**
            # 3 条算出的 4.3 和 30 条算出的 4.3 在那个数字上长得一模一样。
            "平均分怎么读": (
                "还没有人评过 —— **这不是 0 分**,是没有数据" if not 总["评过的"]
                else f"{总['评过的']} 条评价算出来的"
                     + ("。**样本太少,别拿它下结论**(少于 10 条)"
                        if (总["评过的"] or 0) < 10 else "")),
            "各档分布": {f"{k} · {评价档位[k]}": v for k, v in 分布.items()},
            "chat 的有几条": 总["chat的"],
            # ⚠️ 这一句是这个栏目最要紧的一句话。见模块头那段。
            "note": (
                "**chat 现在不走这条检索链** —— 它走澜绣那边的 V1/V2/V3,"
                "自己查知识(mcp/kb)。所以这里现在全是检索实验室的试跑。"
                if not 总["chat的"] else
                f"其中 {总['chat的']} 条来自 chat"),
        },
    }


@router.get(前缀 + "/retrieval-runs/{rid}")
def 试跑详情(project_id: str, rid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """一次试跑的**整条链路**(内容同检索实验室)+ 评价。

    ## ⚠️ 快照里有片段原文 —— 读的时候**按读者的角色重过一遍 ACL**

    快照是「**当时那个人**看到的」,不是「谁都能看的」。
    直接把它原样吐出来,这个栏目就成了一条**绕开语料权限的后门**:
    > 一个「他有权限看的片段」和一个「别人当时看到、而他没权限看的片段」,
    > **在这条快照上长得一模一样**。

    所以这里拿快照里的片段 id 重查一遍可见性,看不到的**把正文隐去**
    (保留证据串和分数 —— 否则他连「有几片被隐去了」都不知道,
    而那会让他以为这次检索只找到那么几片)。
    """
    with 连接() as c:
        r = c.execute(text("""select rr.*, kb.name kb_name
                               from retrieval_runs rr
                               left join knowledge_bases kb
                                 on kb.project_id = rr.project_id
                                and kb.id = rr.knowledge_base_id
                              where rr.project_id=:p and rr.id=:i"""),
                      {"p": project_id, "i": rid}).mappings().first()
        if not r:
            # 404 而不是 403:**不泄露「这个 id 在别的项目里存在」**
            raise _错(404, "NOT_FOUND", "没有这条试跑记录", "回「检索试跑」列表")
        链 = dict(r["chain_snapshot"] or {})
        # ── 按**读者**的角色重过一遍可见性 ─────────────────────────
        片段ids = [x.get("id") for x in (链.get("选片") or []) if x.get("id")]
        候选ids = [x.get("id") for x in (链.get("候选") or []) if x.get("id")]
        要查 = sorted(set(片段ids) | set(候选ids))
        可见 = set()
        if 要查:
            片, 参 = KV.where片段(这个人的角色们=[me.role])
            可见 = {x[0] for x in c.execute(text(f"""
                select ch.id
                  from chunks ch
                  join document_versions dv on dv.project_id=ch.project_id
                                           and dv.id=ch.document_version_id
                  join documents d on d.project_id=dv.project_id
                                  and d.id=dv.document_id
                  join knowledge_bases kb on kb.project_id=d.project_id
                                         and kb.id=d.knowledge_base_id
                 where ch.project_id=:p and ch.id = any(:ids) and {片}
            """), {"p": project_id, "ids": 要查, **参}).all()}
    隐了 = 0
    for 组 in ("选片", "候选"):
        for x in (链.get(组) or []):
            if x.get("id") and x["id"] not in 可见:
                x["文"] = None
                x["正文被隐去了"] = True
                隐了 += 1
    出力 = dict(r["answer_output"] or {})
    return {
        "id": r["id"], "什么时候": r["created_at"], "谁跑的": r["created_by"],
        "来源": r["source"], "问题": r["user_query"], "改写": r["rewritten_query"],
        "知识库": r["kb_name"] or r["knowledge_base_id"],
        "索引构建id": r["index_build_id"], "trace_id": r["trace_id"],
        # 整条链路 —— **和检索实验室同一份形状**,前端复用同一个渲染函数。
        "链路": 链,
        "答案那一档": r["answer_status"], "答案": 出力,
        "评价": {
            "评分": r["rating"],
            "评分档位": (评价档位.get(r["rating"]) if r["rating"] else None),
            "评语": r["rating_reason"], "谁评的": r["rated_by"],
            "什么时候评的": r["rated_at"],
            "还没评" : r["rating"] is None,
            "档位表": {str(k): v for k, v in 评价档位.items()},
        },
        # ⚠️ 改评价要带它做 If-Match(两个人同时评,后到的不许静默覆盖)
        "revision": r["revision"],
        "隐去了几片正文": 隐了,
        "为什么隐去": (None if not 隐了 else
                  f"这条快照里有 {隐了} 片**你的角色({me.role})看不到**的语料 —— "
                  f"正文隐去了,证据串和分数留着(不留的话你连「有几片被隐去」"
                  f"都不知道,而那会让你以为这次检索只找到剩下那几片)。"
                  f"快照是「当时那个人看到的」,不是「谁都能看的」"),
        "note": "这是一次试跑的**快照** —— 索引后来可能被重建、文档可能出了新版本,"
                "而这里存的是**当时**它找到了哪几段。"
                "所以拿它和今天跑一次的结果对比是有意义的",
    }


@router.patch(前缀 + "/retrieval-runs/{rid}/rating")
async def 给试跑打分(project_id: str, rid: str, request: Request,
                if_match: str = Header(default=None, alias="If-Match"),
                me: 身份 = Depends(要权限("运行评测"))):
    """给一次试跑打分(**5 档**)。入参 `{评分: 1-5, 评语?}`

    ## ⚠️ 要 `If-Match`,而且这不是形式

    两个人同时评同一条,后到的那个会**静默覆盖**前一个 ——
    > 一条「只有一个人评过」的记录,和一条「两个人评过而第一个被盖掉」的,
    > **在那个分数上长得一模一样**。
    revision 从试跑详情里拿(`GET /retrieval-runs/{id}` 的 `revision`)。

    ## 覆盖了也要留痕

    改评价会**真的覆盖**上一个分数(这张表只存当前评价,不存历史)。
    所以每次打分都写一条审计:谁、什么时候、从几分改成几分。
    > **一个能被悄悄改掉的分数,在报表里和一个没被改过的长得一样。**
    """
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match",
                  "把试跑详情里的 revision 放进 If-Match 头再提交 —— "
                  "两个人同时评的话,后到的会静默覆盖前一个")
    体 = await request.json()
    分 = 体.get("评分")
    if not isinstance(分, int) or isinstance(分, bool) or not (1 <= 分 <= 5):
        raise _错(422, "VALIDATION", f"评分要是 1-5 的整数,给的是 {分!r}",
                  "5 档:" + " / ".join(f"{k}={v}" for k, v in 评价档位.items()),
                  field_errors={"评分": "1-5 的整数"})
    评语 = (体.get("评语") or "").strip() or None
    with 事务() as c:
        r = c.execute(text("""select rating, revision from retrieval_runs
                             where project_id=:p and id=:i for update"""),
                      {"p": project_id, "i": rid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这条试跑记录", "回「检索试跑」列表")
        if str(r["revision"]) != str(if_match):
            raise _错(409, "REVISION_CONFLICT",
                      f"这条已经被改过(你拿的是 {if_match},现在是 {r['revision']})",
                      "刷新看一眼别人评了什么再决定;**不要直接覆盖**",
                      field_errors={"revision": f"当前 {r['revision']}"})
        新版 = int(r["revision"]) + 1
        c.execute(text("""update retrieval_runs
                             set rating=:g, rating_reason=:why, rated_by=:u,
                                 rated_at=now(), revision=:r, updated_at=now()
                           where project_id=:p and id=:i"""),
                  {"g": 分, "why": 评语, "u": me.user_id, "r": 新版,
                   "p": project_id, "i": rid})
        # ⚠️ **覆盖要留痕。** 这张表只存当前评价 ——
        # 不记审计的话,「从 5 分被改成 2 分」在报表里查不出来。
        c.execute(text("""
            insert into audit_events (id, organization_id, project_id, actor, action,
                target_ref, environment, at, result, reason, created_at, created_by)
            values (:i,:o,:p,:a,'评价检索试跑', cast(:t as jsonb),:e, now(),
                    'ok', :rs, now(), :a)"""),
                  {"i": _新id("aud"), "o": me.org_id, "p": project_id,
                   "a": me.user_id,
                   "t": _json.dumps({"试跑id": rid, "原来几分": r["rating"],
                                     "现在几分": 分, "档位": 评价档位[分]},
                                    ensure_ascii=False),
                   "e": _os.environ.get("APP_ENV", "development"),
                   "rs": (评语 or "")[:200] or None})
    return {"id": rid, "评分": 分, "评分档位": 评价档位[分], "评语": 评语,
            "revision": 新版,
            "note": ("打分覆盖的是**当前**评价(这张表只存当前值),"
                     f"而{'从 ' + str(r['rating']) + ' 分改成 ' if r['rating'] else ''}"
                     f"这次改动写进了审计 —— "
                     "一个能被悄悄改掉的分数,在报表里和没被改过的长得一样")}


# ══════════════════════════════════════════════════════════════════════
# A3:给 **chat** 用的检索入口(业务 2026-10-08 拍的第 ④ 步,管理后台这一半)
#
# ⚠️ **方向和 A1 一样是单向的:澜绣调,管理后台答。**
# 管理后台绝不反过来去查澜绣的库 —— 那会让两个台互相依赖,
# 而「谁先起来」这种问题会在部署那天才暴露(A1 那段注释写的就是这件事)。
#
# ## 业务拍的两条,落点在这儿
#
#   **① 管理后台挂了 → 这条路断,不退回澜绣自己的 `mcp/kb`。**
#      所以这个函数里**一个退路分支都没有** —— 前提不满足就抛明确错误。
#      > 一次「查不到原文」和一次「它根本没查」,
#      > **在顾问看到的那段回答上长得一模一样** —— 而前者该说出来。
#      判据:`tests/orchestration/test_chat_rag_entry.py` 第 ① 节
#      (它查的是「源码里没有退路」,而不是「我记得没写」)。
#
#   **② 每次都查,不自己判断「要不要查」。**
#      所以这里**没有**「要不要检索」这个参数,也没有那个分支。
#      省掉一次检索的代价是多一个判断,而那个判断本身也会错,且更难查
#      (和 `rewriter` 不自己判断「要不要改写」同一条理由)。
#
# ## ⚠️⚠️ 这条接口上最锋利的一个接缝:**两套角色词表对不上**
#
# 语料 ACL 是用**管理后台的角色词表**写的(viewer / editor / annotator /
# trainer / approver / admin),而 chat 那边的身份是**岗位**
# (门店顾问 / 工坊排产 / 后台运营)。两套名字不是一套。
#
# 而今天两级 ACL **全是空的** → `coalesce` 之后是 null → **谁都看得见**。
# 于是 chat 传任何角色名都「能用」:
# > 一个「权限接对了」的接口,和一个「两套角色词表碰巧都没生效」的,
# > **在今天的检索结果上长得一模一样** ——
# > 而等 ACL 真填上,chat 传的那些名字一个都匹配不到,
# > 表现是「顾问突然什么都检索不到」,而接口、Worker、索引全是绿的。
#
# 所以这里**当场拒掉词表外的角色名**,并在错误里说清要先拍那个映射。
# 把它放过去才是危险的:它会在今天显得正常。
# ══════════════════════════════════════════════════════════════════════


@router.post(前缀 + "/knowledge-queries")
async def chat问一次知识库(project_id: str, request: Request,
                   me: 身份 = Depends(要权限("运行评测"))):
    """chat 问一次知识库,拿回**答案 + 出处**。

    入参:`{调用方, 问题, 这个人的角色们, 知识库id?, 要生成?}`

    ⚠️ `调用方` 不能省(和 A1 同一条理由):没有它只答得出
    「一共查了多少次」,答不出「谁在查」—— 而那正是接上 chat 之后
    第一个要回答的问题。

    返回里**一定有 `试跑id`** —— 顾问评价那一下要用它
    (评价走 `PATCH /retrieval-runs/{id}/rating`,和实验室同一条路)。
    """
    体 = await request.json()
    调用方 = (体.get("调用方") or "").strip()
    问题 = (体.get("问题") or "").strip()
    角色们 = 体.get("这个人的角色们")
    库id = (体.get("知识库id") or "").strip() or None
    # ⚠️ 默认**要答案**:chat 要的是一段能说给顾问听的话,不是四段原文。
    要生成 = True if 体.get("要生成") is None else bool(体.get("要生成"))
    if not 调用方:
        raise _错(422, "VALIDATION", "`调用方` 不能省",
                  "填调用它的那个东西(比如 `门店助手`)—— "
                  "没有它只答得出「一共查了多少次」,答不出「谁在查」",
                  field_errors={"调用方": "必填"})
    if not 问题:
        raise _错(422, "VALIDATION", "问题是空的",
                  "空查询的向量会返回一批「离原点最近」的片段,看起来像正常结果",
                  field_errors={"问题": "必填"})
    # ── 角色:**白名单,而且不给默认值** ────────────────────────────
    # 给默认值(比如「没传就不过滤」)等于留一条静默放开语料的路 ——
    # 而那条路一旦存在,漏传的那个调用方会把全部语料交给一个没权限的人。
    if not isinstance(角色们, list) or not 角色们:
        raise _错(422, "VALIDATION", "`这个人的角色们` 必填,而且是个非空清单",
                  "传**顾问在管理后台这边对应的角色**(语料 ACL 是用这套词表写的:"
                  + " / ".join(PM.角色们) + ")。"
                  "⚠️ chat 那边的岗位名(门店顾问 / 工坊排产 / 后台运营)"
                  "**不是这套词表** —— 岗位到角色的映射是业务决定,要先拍",
                  field_errors={"这个人的角色们": "必填,非空清单"})
    不认的 = [r for r in 角色们 if r not in PM.角色们]
    if 不认的:
        # ⚠️ **拒掉,不放过去。** 放过去的话:今天 ACL 是空的 → 谁都看得见 →
        # 看起来一切正常;而 ACL 真填上那天,这些名字一个都匹配不到,
        # 表现是「顾问突然什么都检索不到」。
        raise _错(422, "UNKNOWN_ROLE", f"不认识这几个角色:{不认的}",
                  "语料 ACL 用的是管理后台的角色词表(" + " / ".join(PM.角色们) + ")。"
                  "⚠️ 今天两级 ACL 全是空的,所以**传错角色名也会「看起来能用」**"
                  "(什么都过滤不掉)—— 而 ACL 真填上那天它会变成"
                  "「顾问什么都检索不到」。所以这里当场拒,不放过去。"
                  "岗位→角色的映射要业务先拍",
                  field_errors={"这个人的角色们": f"不在词表里:{不认的}"})

    with 连接() as c:
        # ── 挑索引:**要「已就绪」的那一个,挑不到就抛** ──────────────
        # ⚠️ 这里是业务拍的第 ① 条的落点之一:**没有退路。**
        # 挑不到就明确报错,不静默返回「没找到相关内容」——
        # 后者和「知识库里真的没有」长得一模一样。
        # ⚠️ 点名了知识库的话,**先确认它存在** ——
        # 不先查的话,「没有这个知识库」会被报成「这个库没有已就绪的索引」,
        # > 而那两件事的下一步完全不同:前者是**库 id 传错了**,
        # > 后者是**去建一次索引** —— 报错把人引向后者,他会去建一个
        # > 不存在的库的索引,然后发现界面上找不到那个库。
        if 库id:
            有这个库 = c.execute(text("""select 1 from knowledge_bases
                                      where project_id=:p and id=:k
                                        and archived_at is null"""),
                              {"p": project_id, "k": 库id}).first()
            if not 有这个库:
                raise _错(404, "NOT_FOUND", f"没有这个知识库:{库id}",
                          "核一下 `知识库id`(或者不传它 —— "
                          "不传就用这个项目最近就绪的那个索引)。"
                          "⚠️ 这和「有这个库但它没索引」是两件事,"
                          "后者报 `NO_READY_INDEX`")
        q = """select ib.id, ib.knowledge_base_id, kb.name
                 from index_builds ib
                 join knowledge_bases kb on kb.project_id = ib.project_id
                                        and kb.id = ib.knowledge_base_id
                where ib.project_id = :p and ib.status = '已就绪'
                  and kb.archived_at is null"""
        参 = {"p": project_id}
        if 库id:
            q += " and ib.knowledge_base_id = :k"
            参["k"] = 库id
        q += " order by ib.updated_at desc nulls last limit 1"
        索引 = c.execute(text(q), 参).mappings().first()
        if not 索引:
            raise _错(422, "NO_READY_INDEX",
                      ("这个知识库没有「已就绪」的索引" if 库id
                       else "这个项目一个「已就绪」的索引都没有"),
                      "先建一次索引(知识库页「建索引」)。"
                      "**这里不退回「没找到相关内容」** —— 业务 2026-10-08 拍的:"
                      "管理后台这条路断了就要说出来,"
                      "一次「查不到原文」和一次「它根本没查」在顾问看到的话上长得一样")
        try:
            链 = RT.检索(c, 项目=project_id, 构建id=索引["id"], 问题=问题,
                       这个人的角色们=list(角色们), 要精排=True, 要生成=要生成)
        except RT.检索不了 as e:
            raise _错(422, "RETRIEVAL_PRECONDITION", str(e).split("\n")[0][:300],
                      str(e)[:600])
        except RR.没有凭据 as e:
            # ⚠️ **不降级成「只走向量」。** 那个排序不可靠(实测一个表格头
            # 排到过第 1 名),而拿不可靠的排序去答,错得看不出来。
            raise _错(503, "NO_MODEL_CREDENTIAL", str(e)[:200],
                      "精排要调模型,而本机拿不到凭据 —— "
                      "**这条路断了,不降级**:只走向量的排序不可靠")
        except RR.精排失败 as e:
            raise _错(503, "RERANK_FAILED", str(e).split("\n")[0][:300],
                      "精排返回的东西不合契约 —— **没有降级成按原顺序**")

    链["记账"] = 记这次检索的账(project_id, me, 链)
    链["存档"] = 记一次试跑(project_id, me, 链, 构建id=索引["id"], 来源="chat")
    生 = 链.get("生成") or {}
    # ⚠️ **生成跑不成也不编一段话。** 业务拍的第 ① 条在这里也要兑现:
    # 返回里 `答案` 是 None,而 `为什么没有答案` 说清是哪一种。
    return {
        "试跑id": (链["存档"] or {}).get("试跑id"),
        "答案": (生.get("答案") if 生.get("做了") else None),
        "够不够答": 生.get("够不够答"),
        "缺什么": 生.get("缺什么"),
        "为什么没有答案": (None if 生.get("做了") else 生.get("为什么")),
        "出处们": [
            {"证据": x["证据"], "原话": x.get("原话"),
             "原话可信": x.get("原话可信")}
            for x in (生.get("引用们") or [])],
        # 选片也给出去:chat 那边可能要把原文贴给顾问看
        "选片": [{"证据": x["证据"], "文": x["文"], "分数": x["分数"]}
               for x in 链["选片"]],
        "知识库": 索引["name"], "索引构建id": 索引["id"],
        "原问": 链["原问"], "改写": 链["改写"],
        "花了多少": (链["记账"] or {}).get("token合计"),
        "怎么评价这一次": (
            f"PATCH {前缀.format(project_id=project_id)}/retrieval-runs/"
            f"{(链['存档'] or {}).get('试跑id')}/rating,带 `If-Match`(先 GET 详情拿 revision)"
            " —— 5 档,分数进同一个栏目"),
        "note": "⚠️ 这条路**不降级**(业务 2026-10-08 拍):前提不满足就报错,"
                "不返回「没找到相关内容」—— 后者和「知识库里真的没有」长得一样。"
                "而**每次都查**,这里不自己判断「这个问题要不要查知识库」",
    }
