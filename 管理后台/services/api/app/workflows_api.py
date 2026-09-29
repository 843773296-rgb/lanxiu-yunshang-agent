#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Workflow 编排接口(规格 §17.1 的 `/workflows` 和 `/execution-runs`)。

## 为什么单独一个文件

`main.py` 已经七百行。**一个越长的 handler 文件越容易长出第二套规矩** ——
而这个项目的纪律是「权限从 contract/perms.py 判、状态问 contract/states.py」。
所以这里也一样:一条判断都不自己写。

## 这个文件里最要紧的三件事

① **校验和冻结是同一个校验器。** `POST /validate` 和 `POST /versions` 都调
   `runtime/validator.校验()`。分成两套的话,一定会出现「校验说没问题但冻结被拒」
   或者更糟的「校验拦住了但冻结放过了」。

② **`依赖存在` 由这一层提供,而且按项目范围查。** 校验器自己不碰数据库(它要能在
   没有库的情况下跑夹具),所以「这个 Prompt 版本在不在、是不是这个项目的」
   由这里查。⚠️ 查询**必须带 project_id** —— 拿另一个项目的版本 ID 去引用,
   在这里就要不成立。

③ **试运行返回 202,一个模型都还没调。** Job + Outbox 同事务,worker 捞到才真跑。
   规格 §17.1:「POST 异步创建返回 202/Run ID 或 Job ID,**不能宣称已执行完成**」。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs"))

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

import dsl as DS
import states as ST
import validator as V
import compiler as CP
import outbox as OB
from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

# 引用字段 → (表名, 说明)。**每一条都按 project_id 过滤。**
_引用表 = {
    "connection_version_id": ("connection_versions", "连接版本"),
    "prompt_version_id": ("prompt_versions", "Prompt 版本"),
    "tool_version_id": ("tool_versions", "工具版本"),
    "agent_version_id": ("agent_versions", "Agent 版本"),
    "knowledge_base_id": ("knowledge_bases", "知识库"),
    "index_build_id": ("index_builds", "索引构建"),
    "retrieval_config_version_id": ("retrieval_config_versions", "检索配置版本"),
    "workflow_version_id": ("workflow_versions", "工作流版本"),
}


def _依赖查询(c, project_id):
    """给校验器用的 `依赖存在()`。**按项目范围查** —— 这是跨项目引用的第一道闸,
    第二道是数据库的复合外键(那道不靠任何人记得检查)。"""
    def 存在(字段, 值):
        if 字段 not in _引用表:
            # 认不出的引用字段**当场当成不存在**,不放行。
            # 未知不等于安全:一个我不知道怎么查的引用,最可能的情况是它指向了
            # 一个我也不知道怎么授权的东西。
            return False
        表, _ = _引用表[字段]
        r = c.execute(text(f"select 1 from {表} where project_id=:p and id=:i"
                           f"{' and archived_at is null' if 表 not in ('connection_versions',) else ''}"),
                      {"p": project_id, "i": 值}).first()
        return r is not None
    return 存在


def _新id(前缀):
    import uuid
    return f"{前缀}_{uuid.uuid4().hex[:12]}"


# ── 模板(§4.2:模板仅预填草稿)─────────────────────────────────────
def _模板(名):
    """**模板只预填草稿**,不调模型、不绑生产环境(§4.2)。"""
    开始 = {"id": "start", "type": "start", "layout": {"x": 40, "y": 120},
            "config": {"input_schema": {"type": "object",
                                        "properties": {"article": {"type": "string",
                                                                   "minLength": 1}},
                                        "required": ["article"],
                                        "additionalProperties": False}}}
    结束 = {"id": "finish", "type": "end", "layout": {"x": 620, "y": 120},
            "config": {"output_schema": {"type": "object",
                                         "properties": {"summary": {"type": "string"}},
                                         "required": ["summary"],
                                         "additionalProperties": False},
                       "bindings": {}}}
    if 名 == "文本处理":
        中 = {"id": "summarize", "type": "llm", "name": "总结",
              "layout": {"x": 330, "y": 120},
              "config": {"output_schema": {"type": "object",
                                           "properties": {"text": {"type": "string"}},
                                           "required": ["text"],
                                           "additionalProperties": False},
                         "bindings": {"article": {"source": "input",
                                                  "pointer": "/article"}}}}
        结束["config"]["bindings"] = {"summary": {"source": "node",
                                                "node_id": "summarize",
                                                "pointer": "/text"}}
        节点 = [开始, 中, 结束]
        边 = [{"source": "start", "target": "summarize", "port": "success"},
              {"source": "summarize", "target": "finish", "port": "success"}]
    else:                                    # 空白
        节点, 边 = [开始, 结束], []
    return {"definition_schema_version": "1", "kind": "workflow",
            "input_schema": 开始["config"]["input_schema"],
            "output_schema": 结束["config"]["output_schema"],
            "nodes": 节点, "edges": 边}


# ── 列表 ───────────────────────────────────────────────────────────
@router.get(前缀 + "/workflows")
def 工作流列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
            limit: int = Query(20, ge=1, le=100)):
    """**最新冻结版本和生产引用版本要同时给**(§4.1)。

    只显示一个的话,「我改完了」和「线上在跑的是这个」会被当成同一件事 ——
    而那正是这个后台要解决的痛点之一。
    """
    with 连接() as c:
        rs = c.execute(text("""
            select w.id, w.name, w.purpose, w.owner, w.tags, w.draft_revision,
                   w.validation_status, w.updated_at,
                   (select max(version_no) from workflow_versions v
                     where v.project_id=w.project_id and v.workflow_id=w.id) 最新冻结,
                   (select count(*) from workflow_versions v
                     where v.project_id=w.project_id and v.workflow_id=w.id) 版本数
              from workflows w
             where w.project_id=:p and w.archived_at is null
             order by w.updated_at desc limit :n
        """), {"p": project_id, "n": limit}).mappings().all()
        总 = c.execute(text("""select count(*) from workflows
                             where project_id=:p and archived_at is null"""),
                       {"p": project_id}).scalar()
    出 = []
    for r in rs:
        出.append({
            "id": r["id"], "名称": r["name"], "用途": r["purpose"],
            "负责人": r["owner"], "标签": r["tags"] or [],
            "草稿 revision": r["draft_revision"],
            "最新冻结版本": (f"v{r['最新冻结']}" if r["最新冻结"] else None),
            "版本数": r["版本数"],
            # ⚠️ **发布链还没接**(landing.py 里 Evaluation Adapter / 发布扩展未落地),
            # 所以这里是**「还没接」而不是「没有引用」**。
            # 给 null + 一句说明,不给「—」:一个「—」会被读成「线上没在用」。
            "生产引用版本": None,
            "生产引用说明": "发布清单还没扩展到 Workflow(规格 §15.3)—— "
                            "**这是「还没接」,不是「线上没在用」**",
            "校验状态": r["validation_status"] or "没校验过",
            "更新时间": r["updated_at"].isoformat() if r["updated_at"] else None,
        })
    return {"items": 出, "next_cursor": None, "total": 总}


@router.post(前缀 + "/workflows", status_code=201)
async def 建工作流(project_id: str, request: Request,
               me: 身份 = Depends(要权限("改编排草稿"))):
    """**创建不调用模型,不绑定生产环境**(§4.2)。"""
    体 = await request.json()
    名 = (体.get("名称") or "").strip()
    if not 名:
        raise _错(422, "VALIDATION", "名称不能空", "给这条流程起个名字",
                  field_errors={"名称": "必填"})
    模板名 = 体.get("模板") or "空白"
    if 模板名 not in ("空白", "文本处理"):
        raise _错(422, "VALIDATION", f"没有这个模板:{模板名}",
                  "现在只有「空白」和「文本处理」两个模板。"
                  "**规格 §4.2 还列了「RAG 问答」和「受控调研」,那两个还没做** —— "
                  "不摆一个选了没反应的选项")
    wid, did = _新id("wf"), _新id("gd")
    定义 = _模板(模板名)
    with 事务() as c:
        c.execute(text("""
            insert into workflows (id, organization_id, project_id, name, purpose,
                owner, tags, draft_revision, validation_status, status,
                created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n,:pu,:ow,:tg,1,'没校验过','草稿', now(), :u, now(), 1)
        """), {"i": wid, "o": me.org_id, "p": project_id, "n": 名,
               "pu": 体.get("用途"), "ow": 体.get("负责人") or me.user_id,
               "tg": json.dumps(体.get("标签") or [], ensure_ascii=False),
               "u": me.user_id})
        c.execute(text("""
            insert into graph_drafts (id, organization_id, project_id, workflow_id,
                definition, layout, validation_report, created_at, created_by,
                updated_at, revision)
            values (:i,:o,:p,:w,:d,:l,null, now(), :u, now(), 1)
        """), {"i": did, "o": me.org_id, "p": project_id, "w": wid,
               "d": json.dumps(定义, ensure_ascii=False),
               "l": json.dumps({n["id"]: n.get("layout", {"x": 0, "y": 0})
                                for n in 定义["nodes"]}, ensure_ascii=False),
               "u": me.user_id})
    return {"id": wid, "revision": 1, "模板": 模板名,
            "note": "草稿建好了。**还没校验、没冻结版本、和生产没有任何关系。**"}


@router.get(前缀 + "/workflows/{wid}")
def 工作流详情(project_id: str, wid: str,
            me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        w = c.execute(text("select * from workflows where project_id=:p and id=:i"),
                      {"p": project_id, "i": wid}).mappings().first()
        if not w:
            # 404 而不是 403:**不泄露「这个 ID 在别的项目里存在」**(§17.4)
            raise _错(404, "NOT_FOUND", "没有这条工作流", "回列表重新进入")
        d = c.execute(text("""select * from graph_drafts
                             where project_id=:p and workflow_id=:i"""),
                      {"p": project_id, "i": wid}).mappings().first()
        vs = c.execute(text("""
            select id, version_no, logical_hash, change_note, created_at, created_by
              from workflow_versions where project_id=:p and workflow_id=:i
             order by version_no desc limit 20
        """), {"p": project_id, "i": wid}).mappings().all()
    return {
        "id": w["id"], "名称": w["name"], "用途": w["purpose"], "负责人": w["owner"],
        "标签": w["tags"] or [], "校验状态": w["validation_status"],
        "草稿": {
            "revision": d["revision"] if d else None,
            "定义": d["definition"] if d else None,
            "布局": d["layout"] if d else {},
            "上次校验报告": d["validation_report"] if d else None,
        },
        "版本们": [{"id": v["id"], "版本": f"v{v['version_no']}",
                  "逻辑哈希": (v["logical_hash"] or "")[:19] + "…",
                  "变更说明": v["change_note"],
                  "冻结于": v["created_at"].isoformat() if v["created_at"] else None,
                  "冻结人": v["created_by"]} for v in vs],
        "节点库": [{"名": n["名"], "中文": n["中文"], "可用": n["实现"] == DS.已实现,
                  "端口": n["端口"], "必填": n["必填"], "说明": n["说明"][:180],
                  "不适用": n["不适用"]} for n in DS.节点表],
        "note": "**查看历史版本时画布只读**(§4.3);要改就「基于此版创建草稿」",
    }


@router.patch(前缀 + "/workflows/{wid}/draft")
async def 改图草稿(project_id: str, wid: str, request: Request,
               if_match: str = Header(default=None, alias="If-Match"),
               me: 身份 = Depends(要权限("改编排草稿"))):
    """**允许保存不完整草稿**(§5.3)。If-Match 必填。

    配一张图是个过程。逼人一次配对才能存,会让人把半成品留在浏览器里 —— 然后丢掉。
    所以这里不校验完整性,只校验并发。**校验是另一个按钮。**
    """
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match",
                  "把详情里草稿的 revision 放进 If-Match 头再提交")
    体 = await request.json()
    with 事务() as c:
        d = c.execute(text("""select * from graph_drafts
                             where project_id=:p and workflow_id=:i for update"""),
                      {"p": project_id, "i": wid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这条工作流的草稿", "回列表重新进入")
        if str(d["revision"]) != str(if_match):
            raise _错(409, "REVISION_CONFLICT",
                      f"这张图已经被改过(你拿的是 {if_match},现在是 {d['revision']})",
                      "刷新看一眼别人改了什么再合并;**不要直接覆盖** —— "
                      "覆盖之后对方看不到自己的改动没了",
                      field_errors={"revision": f"当前 {d['revision']}"})
        定义 = 体.get("定义")
        if 定义 is not None and not isinstance(定义, dict):
            raise _错(422, "VALIDATION", "定义要是一个对象", "检查提交的 JSON 形状")
        # **布局单独存**(§15.1:画布坐标单独记录,不改变执行语义)
        布局 = 体.get("布局")
        新版 = int(d["revision"]) + 1
        c.execute(text("""
            update graph_drafts
               set definition=coalesce(:d, definition),
                   layout=coalesce(:l, layout),
                   revision=:r, updated_at=now()
             where project_id=:p and workflow_id=:i
        """), {"d": json.dumps(定义, ensure_ascii=False) if 定义 is not None else None,
               "l": json.dumps(布局, ensure_ascii=False) if 布局 is not None else None,
               "r": 新版, "p": project_id, "i": wid})
        c.execute(text("""update workflows set draft_revision=:r, updated_at=now(),
                              validation_status='改过之后没再校验'
                          where project_id=:p and id=:i"""),
                  {"r": 新版, "p": project_id, "i": wid})
    只改了布局 = 定义 is None and 布局 is not None
    return {"revision": 新版,
            "note": ("只动了坐标 —— **不影响执行语义,逻辑哈希不变**(附录 A-9)"
                     if 只改了布局 else
                     "草稿已保存。**这不影响任何已冻结版本,也不影响生产。**"),
            "校验状态": "改过之后没再校验"}


@router.post(前缀 + "/workflows/{wid}/validate")
def 校验图(project_id: str, wid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """服务端权威校验(§5.3)。**只要查看权限** ——
    一个只能看的人应该能看出这张图哪里配坏了。校验不改东西,也不花钱。"""
    with 事务() as c:
        d = c.execute(text("""select * from graph_drafts
                             where project_id=:p and workflow_id=:i"""),
                      {"p": project_id, "i": wid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这条工作流的草稿", "回列表重新进入")
        问题们 = V.校验(d["definition"] or {}, 依赖存在=_依赖查询(c, project_id))
        报告 = V.报告(问题们)
        c.execute(text("""update graph_drafts set validation_report=:r, updated_at=now()
                          where project_id=:p and workflow_id=:i"""),
                  {"r": json.dumps(报告, ensure_ascii=False, default=str),
                   "p": project_id, "i": wid})
        c.execute(text("""update workflows set validation_status=:s, updated_at=now()
                          where project_id=:p and id=:i"""),
                  {"s": "通过" if 报告["通过"] else f"{报告['阻断数']} 条阻断",
                   "p": project_id, "i": wid})
    return 报告


@router.post(前缀 + "/workflows/{wid}/versions", status_code=201)
async def 冻结版本(project_id: str, wid: str, request: Request,
               me: 身份 = Depends(要权限("改编排草稿"))):
    """固定逻辑图和确切依赖(§5.3)。**所有阻断校验必须过,变更说明必填。**

    ⚠️ 这里调的是**同一个**校验器。分成两套的话一定会出现
    「校验说没问题但冻结被拒」,或者更糟的「校验拦住了但冻结放过了」。
    """
    体 = await request.json()
    说明 = (体.get("变更说明") or "").strip()
    if not 说明:
        raise _错(422, "CHANGE_NOTE_REQUIRED", "变更说明必填",
                  "写一句「这一版改了什么、为什么」—— 它是版本对比时唯一"
                  "能说清意图的东西(哈希只能说明「变了」)",
                  field_errors={"变更说明": "必填"})
    with 事务() as c:
        d = c.execute(text("""select * from graph_drafts
                             where project_id=:p and workflow_id=:i for update"""),
                      {"p": project_id, "i": wid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这条工作流的草稿", "回列表重新进入")
        定义 = d["definition"] or {}
        问题们 = V.校验(定义, 依赖存在=_依赖查询(c, project_id))
        if V.有阻断(问题们):
            raise _错(422, "VALIDATION", f"还有 {sum(1 for p in 问题们 if p['级别'] == V.阻断)} 条阻断,不能冻结",
                      "先按校验报告改完 —— **一张有阻断的图冻结出来的版本,"
                      "发布清单指着它却跑不起来**",
                      field_errors={(p["node_id"] or "图") + "." + (p["field_path"] or ""):
                                    p["消息"] for p in 问题们 if p["级别"] == V.阻断})
        计划 = CP.编译(定义, 依赖存在=_依赖查询(c, project_id))
        哈希 = 计划["逻辑哈希"]
        上一版 = c.execute(text("""
            select version_no, logical_hash from workflow_versions
             where project_id=:p and workflow_id=:i
             order by version_no desc limit 1"""),
                        {"p": project_id, "i": wid}).mappings().first()
        if 上一版 and 上一版["logical_hash"] == 哈希:
            # **同一份语义内容不再开一个版本号。** 这不是省事:
            # 两个逻辑上一模一样的版本会让「生产引用的是哪一版」变成一个
            # 没有意义的问题,而版本对比上什么都看不出来。
            raise _错(409, "NO_SEMANTIC_CHANGE",
                      f"和 v{上一版['version_no']} 的逻辑完全一样(同一个哈希)",
                      "只挪了位置或改了显示名的话,**不需要新版本** —— "
                      "坐标不进逻辑哈希(附录 A-9)。真要改行为就改条件/绑定/依赖版本",
                      field_errors={"logical_hash": 哈希[:26] + "…"})
        版本号 = (上一版["version_no"] + 1) if 上一版 else 1
        vid = _新id("wfv")
        依赖 = sorted({f"{f}:{(n.get('config') or {}).get(f)}"
                      for n in 定义["nodes"] for f in _引用表
                      if (n.get("config") or {}).get(f)})
        c.execute(text("""
            insert into workflow_versions (id, organization_id, project_id, workflow_id,
                version_no, definition_schema_version, nodes, edges, logical_hash,
                dependencies, layout, input_schema, output_schema, change_note,
                created_at, created_by)
            values (:i,:o,:p,:w,:vn,:dsv,:nd,:ed,:lh,:dep,:ly,:isc,:osc,:cn, now(), :u)
        """), {"i": vid, "o": me.org_id, "p": project_id, "w": wid, "vn": 版本号,
               "dsv": 定义.get("definition_schema_version") or "1",
               "nd": json.dumps(定义["nodes"], ensure_ascii=False),
               "ed": json.dumps(定义.get("edges") or [], ensure_ascii=False),
               "lh": 哈希,
               "dep": json.dumps(依赖, ensure_ascii=False),
               # 坐标存在版本上(否则看历史版本只能看到一团重叠的节点),
               # 但它**不进 logical_hash** —— 两件事分开。
               "ly": json.dumps(d["layout"] or {}, ensure_ascii=False),
               "isc": json.dumps(定义.get("input_schema") or {}, ensure_ascii=False),
               "osc": json.dumps(定义.get("output_schema") or {}, ensure_ascii=False),
               "cn": 说明, "u": me.user_id})
        c.execute(text("""update workflows set validation_status='通过', updated_at=now()
                          where project_id=:p and id=:i"""),
                  {"p": project_id, "i": wid})
    return {"id": vid, "版本": f"v{版本号}", "逻辑哈希": 哈希,
            "依赖": 依赖, "变更说明": 说明,
            "note": "**冻结了,但没发布。**生产指针没有任何变化(§15.6)"}


# ── 试运行 ─────────────────────────────────────────────────────────
@router.post(前缀 + "/execution-runs", status_code=202)
async def 发起运行(project_id: str, request: Request,
               idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
               me: 身份 = Depends(要权限("运行编排测试"))):
    """**202 + Run ID,一个模型都还没调**(§17.1)。

    Job + Outbox 在同一个事务里 —— 「写库」和「发队列」分成两件独立的事的话,
    它们之间一定有窗口:写库成功但没发出去 → 任务永远不被跑而库里它是「排队中」;
    发出去但写库回滚 → worker 捞到一个幽灵。**两个方向都难查,因为各自看起来都自洽。**
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "前端为这一次点击生成一个 UUID 放进 Idempotency-Key 头 —— "
                  "网络超时重发时它保证不会跑第二遍(也不会多花一次钱)")
    体 = await request.json()
    wid = 体.get("workflow_id")
    版本id = 体.get("workflow_version_id")          # 给了就跑冻结版本,否则跑草稿快照
    输入 = 体.get("输入") or {}
    模式 = 体.get("模式") or "mock"
    if 模式 != "mock":
        raise _错(422, "LIVE_NOT_CONFIGURED", "真实模式还没接",
                  "现在只有 mock 适配器(没有真实模型连接和凭证)。"
                  "**缺资源要明确报出来,不能算通过**(§18)")
    with 事务() as c:
        老 = c.execute(text("""select id, status, target_ref from jobs
                             where project_id=:p and idempotency_key=:k"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            return {"job_id": 老["id"], "status": 老["status"],
                    "resource_id": (老["target_ref"] or {}).get("run_id"),
                    "status_url": f"{前缀.format(project_id=project_id)}/jobs/{老['id']}",
                    "trace_id": None,
                    "note": "同一个幂等键 → **返回原任务,不新建**"}
        # 取定义:冻结版本优先(生产必须用版本;草稿只给调试)
        if 版本id:
            v = c.execute(text("""select * from workflow_versions
                                 where project_id=:p and id=:i"""),
                          {"p": project_id, "i": 版本id}).mappings().first()
            if not v:
                raise _错(404, "NOT_FOUND", "没有这个工作流版本", "回详情页选一个")
            定义 = {"definition_schema_version": v["definition_schema_version"],
                    "kind": "workflow", "nodes": v["nodes"], "edges": v["edges"],
                    "input_schema": v["input_schema"],
                    "output_schema": v["output_schema"]}
            来源 = {"kind": "workflow_version", "id": v["workflow_id"],
                    "version_id": 版本id, "version_no": v["version_no"]}
        else:
            d = c.execute(text("""select * from graph_drafts
                                 where project_id=:p and workflow_id=:i"""),
                          {"p": project_id, "i": wid}).mappings().first()
            if not d:
                raise _错(404, "NOT_FOUND", "没有这条工作流的草稿", "回列表重新进入")
            定义 = d["definition"] or {}
            来源 = {"kind": "graph_draft", "id": wid, "draft_revision": d["revision"]}
        # **编译在这里做,不留到 worker**:配置错了要当场知道,
        # 而不是排队等一会儿再看到一条「失败」。
        try:
            计划 = CP.编译(定义, 依赖存在=_依赖查询(c, project_id))
        except CP.编译失败 as e:
            阻 = [p for p in e.问题们 if p["级别"] == V.阻断]
            raise _错(422, "VALIDATION", f"这张图有 {len(阻)} 条阻断,跑不了",
                      "先点「校验」按报告改完 —— **一个模型都没调,这次不花钱**",
                      field_errors={(p["node_id"] or "图") + "." + (p["field_path"] or ""):
                                    p["消息"] for p in 阻})
        job, run, trace = _新id("job"), _新id("xr"), _新id("tr")
        # trace 先建:execution_runs 有一条指向 traces 的复合外键
        c.execute(text("""
            insert into traces (id, organization_id, project_id, session_id, request_id,
                environment, started_at, created_at, created_by)
            values (:i,:o,:p,:s,:rq,:e, now(), now(), :u)
        """), {"i": trace, "o": me.org_id, "p": project_id, "s": run, "rq": job,
               "e": os.environ.get("APP_ENV", "development"), "u": me.user_id})
        c.execute(text("""
            insert into execution_runs (id, organization_id, project_id, kind,
                definition_ref, input_snapshot, definition_hash, principal, status,
                limits, environment, execution_mode, quality_evaluation_status,
                started_at, trace_id, idempotency_key,
                created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'workflow',:dr,:isn,:dh,:pr,'queued',:lm,:env,'mock',
                    '未评', null, :t, :k, now(), :u, now(), 1)
        """), {"i": run, "o": me.org_id, "p": project_id,
               "dr": json.dumps(来源, ensure_ascii=False),
               "isn": json.dumps(输入, ensure_ascii=False),
               "dh": 计划["逻辑哈希"], "pr": me.user_id,
               "lm": json.dumps(体.get("上限") or {"max_model_turns": 8},
                                ensure_ascii=False),
               "env": os.environ.get("APP_ENV", "development"),
               "t": trace, "k": idempotency_key, "u": me.user_id})
        c.execute(text("""
            insert into jobs (id, organization_id, project_id, type, target_ref, status,
                attempts, max_attempts, snapshot_hash, idempotency_key,
                created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'workflow_run',:t,'排队中',0,3,:sh,:k, now(), :u, now(), 1)
        """), {"i": job, "o": me.org_id, "p": project_id,
               "t": json.dumps({"run_id": run}, ensure_ascii=False),
               "sh": 计划["逻辑哈希"], "k": idempotency_key, "u": me.user_id})
        c.execute(text("""
            insert into job_events (id, organization_id, project_id, job_id, seq, kind,
                payload, at, created_at, created_by)
            values (:i,:o,:p,:j,1,'已受理',:pl, now(), now(), :u)
        """), {"i": _新id("je"), "o": me.org_id, "p": project_id, "j": job,
               # 「已受理」不是「开始」—— 到这一刻一个模型都还没调。
               # 写「开始」会让事件流上出现两个开始,读的人分不清真起点。
               "pl": json.dumps({"阶段": "排队", "说明": "已受理,等 worker 捞"},
                                ensure_ascii=False), "u": me.user_id})
        c.execute(text("""
            insert into run_events (id, organization_id, project_id, execution_run_id,
                seq, event_type, payload, occurred_at, created_at, created_by)
            values (:i,:o,:p,:r,1,'run.accepted',:pl, now(), now(), :u)
        """), {"i": _新id("re"), "o": me.org_id, "p": project_id, "r": run,
               "pl": json.dumps({"来源": 来源, "模式": "mock"}, ensure_ascii=False),
               "u": me.user_id})
        OB.入箱(c, org=me.org_id, 项目=project_id, job_id=job, topic="workflow_run",
               payload={"run_id": run}, 新id=_新id("ob"))
    return {"job_id": job, "status": "排队中", "resource_id": run,
            "status_url": f"/api/v1/projects/{project_id}/jobs/{job}",
            "trace_id": None,
            "note": "**排队中,一个模型都还没调** —— 这正是 202 的含义。"
                    "Worker 捞到之后才真的跑(`make dev` 会把 worker 一起起来)"}


@router.get(前缀 + "/execution-runs")
def 运行列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
           workflow_id: str = Query(default=None), limit: int = Query(20, ge=1, le=100)):
    """运行列表。

    ## 两个坑记在这儿(都不能写进下面那段 SQL 里)

    ⚠️ **① `:w` 必须显式 `cast(... as text)`。** 不转的话 PostgreSQL 推断不出它的类型
    (两次出现都在定不了类型的位置:`is null`,以及和 JSONB 取出来的 text 比较),
    直接 500 `AmbiguousParameter`。

    这条 bug 活下来的原因值得记:我手敲 curl 验的时候**只测了详情,没测不带参数的
    列表** —— 列表是最容易被认为「不用测」的那种接口,它看起来只是把详情少显示
    几个字段。抓到它的是 `docs/实现进度.md`:那份报告不问「你觉得验过了吗」,
    它问「测试**打过**这条路由吗」,而 10 条没打过的里第一条就藏着这个 500。

    ⚠️ **② 上面这段说明不能写成 SQL 注释。** 第一版我把它写进 `text()` 里的
    `--` 注释,而注释里有个中文冒号 —— **SQLAlchemy 把 `:那份报告不问` 当成了
    绑定参数名**,于是报「A value is required for bind parameter '那份报告不问'」。
    `text()` 里的 `--` 对 SQLAlchemy **不透明**,它只认 `:name` 这个词法。
    **SQL 字符串里不许出现 `:` 开头的自然语言。**
    """
    with 连接() as c:
        rs = c.execute(text("""
            select id, kind, definition_ref, status, completion_reason,
                   quality_evaluation_status, execution_mode, principal,
                   started_at, ended_at, trace_id
              from execution_runs
             where project_id=:p
               and (cast(:w as text) is null
                    or definition_ref->>'id' = cast(:w as text))
             order by started_at desc limit :n
        """), {"p": project_id, "w": workflow_id, "n": limit}).mappings().all()
        总 = c.execute(text("select count(*) from execution_runs where project_id=:p"),
                       {"p": project_id}).scalar()
    出 = []
    for r in rs:
        出.append({
            "id": r["id"], "类型": r["kind"],
            "对象": (r["definition_ref"] or {}).get("id"),
            "版本": (r["definition_ref"] or {}).get("version_no")
                    or f"草稿 r{(r['definition_ref'] or {}).get('draft_revision')}",
            # **执行状态和任务达标状态分两列**(§14.2)——
            # 合成一列就没法回答「跑完了但没做成」这种最常见的情况
            "执行状态": r["status"],
            "执行状态中文": ST.找("execution_run")["中文状态"].get(r["status"], r["status"]),
            "停止原因": r["completion_reason"],
            "任务达标": r["quality_evaluation_status"],
            "模式": r["execution_mode"], "请求人": r["principal"],
            "开始": r["started_at"].isoformat() if r["started_at"] else None,
            "结束": r["ended_at"].isoformat() if r["ended_at"] else None,
        })
    return {"items": 出, "next_cursor": None, "total": 总}


# 控制动作 → 它要把状态推到哪。**从状态机现读,不手抄一张表。**
_控制动作表 = (
    ("pause", "请求暂停", "pause_requested"),
    ("resume", "继续", "queued"),
    ("cancel", "请求取消", "cancel_requested"),
)


def _控制动作们(当前):
    """现在这个状态上,哪几个控制动作是合法的。

    ⚠️ **`cancel` 有两条路**:有些状态直接走到 `cancelled`(还没开跑,
    没有在途调用要掐),有些走到 `cancel_requested`。两条都算「能取消」——
    `runctl.py` 里那段逻辑就是这么判的,这里跟它一致。
    少判一条的表现是:界面藏掉一个其实能用的「取消」按钮,而没人知道为什么。
    """
    机 = ST.找("execution_run")
    去的地方 = set(机["流转"].get(当前) or [])
    出 = []
    for 名, 中文, 目标 in _控制动作表:
        能 = 目标 in 去的地方
        if 名 == "cancel" and not 能:
            能 = "cancelled" in 去的地方
        出.append({"动作": 名, "中文": 中文, "现在能吗": 能,
                   "为什么不能": (None if 能 else
                              f"状态机里「{当前}」走不到「{目标}」—— "
                              f"它现在能去的是 {sorted(去的地方) or '哪儿都去不了(终态)'}")})
    # ⚠️ `reconcile` 单独列:它**不改状态**(只去问一次外部系统),
    # 所以只要不是终态就能做 —— 和上面三个的判据不是一回事。
    出.append({"动作": "reconcile", "中文": "核实外部状态",
               "现在能吗": 当前 not in 机["终态"],
               "为什么不能": (None if 当前 not in 机["终态"]
                          else "已经是终态了,没有外部状态要核实")})
    return 出


@router.get(前缀 + "/execution-runs/{rid}")
def 运行详情(project_id: str, rid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    看原文, _ = me.能("查看敏感输入/独立测试答案")
    with 连接() as c:
        r = c.execute(text("select * from execution_runs where project_id=:p and id=:i"),
                      {"p": project_id, "i": rid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这次运行", "回运行列表")
        steps = c.execute(text("""
            select node_id, kind, status, attempt, execution_key, branch_key,
                   skipped_reason, error_code, error_detail, output_ref, started_at
              from run_steps where project_id=:p and execution_run_id=:i
             order by started_at nulls last, node_id
        """), {"p": project_id, "i": rid}).mappings().all()
        evs = c.execute(text("""
            select seq, event_type, payload, occurred_at from run_events
             where project_id=:p and execution_run_id=:i order by seq
        """), {"p": project_id, "i": rid}).mappings().all()
    def _脱(v):
        if 看原文:
            return v
        return "***(要「查看敏感输入/独立测试答案」专项授权)" if v else v
    return {
        "id": r["id"], "执行状态": r["status"],
        # ⚠️ **revision 必须给出来。** 暂停 / 继续 / 取消三条接口都要拿它做
        # `If-Match`(见 `runctl.py::_要键和锁`),而在这之前**任何读接口都不给** ——
        # 于是那三个动作在界面上**做不起来**:不是前端没写,是它拿不到必须带的值。
        # 2026-09-29 补的;同一天同一个洞在发布链和工具草稿上各有一处。
        # 判据 `tools/ifmatch_reachable_check.py` 现在盯着这件事。
        "revision": r["revision"],
        # ⚠️ **哪几个控制动作现在合法,由接口算,不让界面自己推。**
        #
        # 2026-09-29:页面控制按钮第一版**四个一起摆**,而 `queued` 的运行
        # 点「请求暂停」会回 `BAD_TRANSITION`(状态机只允许从 `running` 走)。
        # 那正是我在按钮那段注释里写的毛病:
        # > **「点了没用」比「没有这个按钮」更费时间** ——
        # > 它让人以为还能操作,然后花时间去找为什么没反应。
        #
        # 为什么不让前端按状态自己判:那等于把状态机在前端**再抄一遍**,
        # 而抄件会漂 —— 漂的表现是界面上摆着一个不合法的按钮,
        # 或者藏掉一个其实能用的,**两者都不报错**。
        # 所以这里从 `states.py` 现读,前端只管照着摆。
        "可执行的控制动作": _控制动作们(r["status"]),
        "执行状态中文": ST.找("execution_run")["中文状态"].get(r["status"], r["status"]),
        "是终态吗": r["status"] in ST.找("execution_run")["终态"],
        "停止原因": r["completion_reason"],
        # **两栏分开**(§16.4):succeeded 只说流程按定义跑完了、
        # 确定性输出检查过了,**不说明里面的事实都对**
        "任务达标": r["quality_evaluation_status"],
        "达标说明": "**`succeeded` 不等于任务达标**(§16.4)—— "
                    "里面的事实对不对要靠评测或人工,这一栏默认是「未评」",
        "模式": r["execution_mode"], "定义来源": r["definition_ref"],
        "逻辑哈希": r["definition_hash"], "请求人": r["principal"],
        "输入快照": _脱(r["input_snapshot"]),
        "输出": _脱(r["output_ref"]),
        "上限": r["limits"], "用量": r["usage_snapshot"],
        "trace_id": r["trace_id"],
        "步骤": [{"节点": s["node_id"], "类型": s["kind"], "状态": s["status"],
                "尝试": s["attempt"], "执行键": s["execution_key"],
                "走的分支": s["branch_key"], "为什么跳过": s["skipped_reason"],
                "错误码": s["error_code"], "错误细节": s["error_detail"]}
               for s in steps],
        "事件": [{"seq": e["seq"], "类型": e["event_type"], "载荷": e["payload"],
                "时间": e["occurred_at"].isoformat() if e["occurred_at"] else None}
               for e in evs],
    }
