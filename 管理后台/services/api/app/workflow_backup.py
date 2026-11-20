#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流的导出 / 导入(四期 4-3,11-20 夜;用户 11-15 拍「导出 + 导入都做」)。

我们自己的 JSON,**不和 Dify 互导**(DSL 不通用,导进来也跑不了)。

导出 = 定义 + 布局 + **引用表**:定义里凡是指向别的资源的字段(模型连接版本 / 处理要求版本 / 业务动作版本 / Agent 版本 /
资料库 / 索引 / 检索配置 / 子流程版本 / 工具连接 / 术语版本),每一处记成「名字 + 版本号」—— id 是这个项目的,换个项目就对不上,
名字和版本号才是跨项目能认的东西。**不含任何密钥 / 凭据值**(定义里本来就没有:凭据只挂在连接上、发送那一刻才取)。

导入 = **只建草稿**,不发布、不动生产:按引用表里的(类型, 名, 版本)在目标项目里找,找到就把定义里那个 id 换成本项目的;
找不到的**保留原值**并列进「未找到」—— 校验器那条 REF_NOT_FOUND 会在图上把它标红,人去面板里重新选。
不悄悄换成「同名的最新版」:版本是人冻过的,换了语义就变了。

纯 SQL 查表,不开连接(连接由接口层给,和存草稿同一个事务)。
"""
import copy
import json
from datetime import datetime, timezone

from sqlalchemy import text

格式 = "澜绣云裳工作流备份"
格式版本 = 1

# 字段 → 中文类型(和 runtime/validator.py 的 引用字段 同一张,少一个就是导出漏记一类引用)
引用字段 = {"connection_version_id": "模型连接版本", "prompt_version_id": "处理要求版本", "tool_version_id": "业务动作版本",
        "agent_version_id": "Agent 版本", "knowledge_base_id": "资料库", "index_build_id": "索引构建",
        "retrieval_config_version_id": "检索配置版本", "workflow_version_id": "子流程版本", "connection_id": "工具连接",
        "glossary_version_id": "术语版本"}


class 备份不对(Exception):
    def __init__(self, 为什么, 怎么办="核对文件是不是从「导出」拿到的那份,没改过"):
        super().__init__(为什么)
        self.为什么, self.怎么办 = 为什么, 怎么办


def _一行(c, sql, **参):
    return c.execute(text(sql), 参).mappings().first()


def _描述(c, p, 字段, 值):
    """这个项目里 `字段=值` 指的是哪个资源 → {名, 版本, …};查不到 → None。"""
    if 字段 == "connection_version_id":
        r = _一行(c, """select m.display_name 名 from connection_versions cv
                        join model_connections m on m.project_id=cv.project_id and m.id=cv.connection_id
                       where cv.project_id=:p and cv.id=:i""", p=p, i=值)
        return {"名": r["名"], "版本": None} if r else None
    if 字段 == "prompt_version_id":
        r = _一行(c, "select key 名, version_no 版本 from prompt_versions where project_id=:p and id=:i", p=p, i=值)
        return dict(r) if r else None
    if 字段 == "tool_version_id":
        r = _一行(c, """select td.name 名, tv.version_no 版本 from tool_versions tv
                        join tool_definitions td on td.project_id=tv.project_id and td.id=tv.tool_definition_id
                       where tv.project_id=:p and tv.id=:i""", p=p, i=值)
        return dict(r) if r else None
    if 字段 == "agent_version_id":
        r = _一行(c, """select a.name 名, av.version_no 版本 from agent_versions av
                        join agents a on a.project_id=av.project_id and a.id=av.agent_id
                       where av.project_id=:p and av.id=:i""", p=p, i=值)
        return dict(r) if r else None
    if 字段 == "knowledge_base_id":
        r = _一行(c, "select name 名 from knowledge_bases where project_id=:p and id=:i", p=p, i=值)
        return {"名": r["名"], "版本": None} if r else None
    if 字段 == "index_build_id":
        r = _一行(c, """select kb.name 名 from index_builds ib join knowledge_bases kb on kb.project_id=ib.project_id and kb.id=ib.knowledge_base_id
                       where ib.project_id=:p and ib.id=:i""", p=p, i=值)
        return {"名": r["名"], "版本": None, "说明": "导入时取这个资料库最新「已就绪」的索引"} if r else None
    if 字段 == "retrieval_config_version_id":
        r = _一行(c, "select recall_modes, candidate_k, final_chunk_limit from retrieval_config_versions where project_id=:p and id=:i", p=p, i=值)
        return {"名": f"候选 {r['candidate_k']} · 最终 {r['final_chunk_limit']} · {'+'.join(r['recall_modes'] or [])}", "版本": None,
                "参数": {"candidate_k": r["candidate_k"], "final_chunk_limit": r["final_chunk_limit"], "recall_modes": list(r["recall_modes"] or [])}} if r else None
    if 字段 == "workflow_version_id":
        r = _一行(c, """select w.name 名, v.version_no 版本 from workflow_versions v join workflows w on w.project_id=v.project_id and w.id=v.workflow_id
                       where v.project_id=:p and v.id=:i""", p=p, i=值)
        return dict(r) if r else None
    if 字段 == "connection_id":
        r = _一行(c, "select name 名 from capability_connections where project_id=:p and id=:i", p=p, i=值)
        return {"名": r["名"], "版本": None} if r else None
    if 字段 == "glossary_version_id":
        r = _一行(c, "select key 名, version_no 版本 from glossary_versions where project_id=:p and id=:i", p=p, i=值)
        return dict(r) if r else None
    return None


def _找(c, p, 字段, 引):
    """目标项目里按(名, 版本)找 → id;找不到 → None。版本号要**正好**对上,不退回「同名最新版」。"""
    名, 版本 = 引.get("名"), 引.get("版本")
    if not 名:
        return None
    if 字段 == "connection_version_id":
        r = _一行(c, """select cv.id from connection_versions cv join model_connections m on m.project_id=cv.project_id and m.id=cv.connection_id
                       where cv.project_id=:p and m.display_name=:n and m.status='active' order by cv.created_at desc limit 1""", p=p, n=名)
    elif 字段 == "prompt_version_id":
        r = _一行(c, "select id from prompt_versions where project_id=:p and key=:n and version_no=:v", p=p, n=名, v=版本)
    elif 字段 == "tool_version_id":
        r = _一行(c, """select tv.id from tool_versions tv join tool_definitions td on td.project_id=tv.project_id and td.id=tv.tool_definition_id
                       where tv.project_id=:p and td.name=:n and tv.version_no=:v and td.archived_at is null""", p=p, n=名, v=版本)
    elif 字段 == "agent_version_id":
        r = _一行(c, """select av.id from agent_versions av join agents a on a.project_id=av.project_id and a.id=av.agent_id
                       where av.project_id=:p and a.name=:n and av.version_no=:v""", p=p, n=名, v=版本)
    elif 字段 == "knowledge_base_id":
        r = _一行(c, "select id from knowledge_bases where project_id=:p and name=:n and archived_at is null order by created_at desc limit 1", p=p, n=名)
    elif 字段 == "index_build_id":
        r = _一行(c, """select ib.id from index_builds ib join knowledge_bases kb on kb.project_id=ib.project_id and kb.id=ib.knowledge_base_id
                       where ib.project_id=:p and kb.name=:n and kb.archived_at is null and ib.status='已就绪'
                       order by ib.updated_at desc nulls last, ib.created_at desc limit 1""", p=p, n=名)
    elif 字段 == "retrieval_config_version_id":
        参 = 引.get("参数") or {}
        if not 参:
            return None
        r = _一行(c, """select id from retrieval_config_versions where project_id=:p and candidate_k=:k and final_chunk_limit=:f
                         and cast(recall_modes as text)=cast(cast(:m as jsonb) as text) and archived_at is null order by created_at desc limit 1""",
                 p=p, k=参.get("candidate_k"), f=参.get("final_chunk_limit"), m=json.dumps(参.get("recall_modes") or [], ensure_ascii=False))
    elif 字段 == "workflow_version_id":
        r = _一行(c, """select v.id from workflow_versions v join workflows w on w.project_id=v.project_id and w.id=v.workflow_id
                       where v.project_id=:p and w.name=:n and v.version_no=:v and w.archived_at is null order by v.created_at desc limit 1""", p=p, n=名, v=版本)
    elif 字段 == "connection_id":
        r = _一行(c, "select id from capability_connections where project_id=:p and name=:n and archived_at is null order by created_at desc limit 1", p=p, n=名)
    elif 字段 == "glossary_version_id":
        r = _一行(c, "select id from glossary_versions where project_id=:p and key=:n and version_no=:v", p=p, n=名, v=版本)
    else:
        return None
    return r["id"] if r else None


def 引用表(c, project_id, 定义):
    """定义里每一处引用 → [{节点, 字段, 类型, id, 名, 版本, …}];这个项目里查不到的标 找不到=True(导出的是草稿时可能有)。"""
    出 = []
    for n in (定义 or {}).get("nodes") or []:
        cfg = n.get("config") or {}
        for 字段, 类型 in 引用字段.items():
            值 = cfg.get(字段)
            if not 值:
                continue
            描 = _描述(c, project_id, 字段, 值)
            出.append({"节点": n.get("id"), "字段": 字段, "类型": 类型, "id": 值, **(描 or {"名": None, "版本": None, "找不到": True})})
    return 出


def 导出(c, project_id, wid, 版本id=None):
    """→ 备份 dict。版本id 给了导那一版(冻结的);不给导当前草稿。工作流不在 → None。"""
    w = _一行(c, "select id, name, purpose from workflows where project_id=:p and id=:i", p=project_id, i=wid)
    if not w:
        return None
    if 版本id:
        v = _一行(c, "select version_no, nodes, edges, layout, logical_hash from workflow_versions where project_id=:p and workflow_id=:w and id=:v",
                 p=project_id, w=wid, v=版本id)
        if not v:
            return None
        定义 = {"nodes": v["nodes"] or [], "edges": v["edges"] or []}
        布局, 版本, 哈希 = v["layout"] or {}, f"v{v['version_no']}", v["logical_hash"]
    else:
        d = _一行(c, "select definition, layout, revision from graph_drafts where project_id=:p and workflow_id=:w", p=project_id, w=wid)
        if not d:
            return None
        定义 = d["definition"] or {"nodes": [], "edges": []}
        布局, 版本, 哈希 = d["layout"] or {}, "草稿", None
        布局 = {k: v for k, v in 布局.items() if k != "$开始待配置"}
    return {"格式": 格式, "格式版本": 格式版本, "导出于": datetime.now(timezone.utc).isoformat(),
            "来源": {"项目": project_id, "工作流id": wid, "工作流": w["name"], "用途": w["purpose"], "版本": 版本, "逻辑哈希": 哈希},
            "定义": 定义, "布局": 布局, "引用": 引用表(c, project_id, 定义),
            "说明": "不含任何密钥 / 凭据值;引用的模型、处理要求、业务动作、资料库、连接只记名字和版本号,导入时在目标项目里按名字找,找不到的保留原值并标出来"}


def 解析(c, project_id, 备份):
    """→ (定义, 布局, 未找到, 改写了)。形状不对抛 备份不对。"""
    if not isinstance(备份, dict) or 备份.get("格式") != 格式:
        raise 备份不对("这不是澜绣云裳的工作流备份(缺「格式」标记)")
    if 备份.get("格式版本") != 格式版本:
        raise 备份不对(f"备份格式版本 {备份.get('格式版本')} 认不出(现在是 {格式版本})", "用现在的后台重新导出一份")
    定义 = 备份.get("定义")
    if not isinstance(定义, dict) or not isinstance(定义.get("nodes"), list):
        raise 备份不对("备份里的「定义」形状不对(要有 nodes 列表)")
    定义 = copy.deepcopy(定义)
    布局 = {k: v for k, v in (备份.get("布局") or {}).items() if k != "$开始待配置"} if isinstance(备份.get("布局"), dict) else {}
    按节点 = {n.get("id"): n for n in 定义["nodes"] if isinstance(n, dict)}
    记过 = set()
    未找到, 改写了 = [], []
    for 引 in 备份.get("引用") or []:
        n = 按节点.get(引.get("节点"))
        字段 = 引.get("字段")
        if not n or 字段 not in 引用字段:
            continue
        cfg = n.setdefault("config", {})
        记过.add((引.get("节点"), 字段))
        if cfg.get(字段) != 引.get("id"):
            continue    # 备份里的引用表和定义对不上(手改过)—— 按定义里现在的值走下面那段
        新 = _找(c, project_id, 字段, 引)
        条 = {"节点": 引.get("节点"), "字段": 字段, "类型": 引用字段[字段], "名": 引.get("名"), "版本": 引.get("版本"), "原id": 引.get("id")}
        if 新:
            if 新 != 引.get("id"):
                cfg[字段] = 新
                改写了.append({**条, "新id": 新})
        else:
            未找到.append({**条, "原因": ("备份里没记下名字" if not 引.get("名") else f"这个项目里没有叫「{引.get('名')}」" + (f" v{引.get('版本')}" if 引.get("版本") is not None else "") + f"的{引用字段[字段]}"),
                         "怎么办": "导入后到「搭建」里这一步的面板重新选一个;检查配置会把它标红"})
    # 定义里有引用、备份的引用表却没记的(老备份 / 手改):原值在这个项目里有就算了,没有就列出来
    for n in 定义["nodes"]:
        if not isinstance(n, dict):
            continue
        cfg = n.get("config") or {}
        for 字段, 类型 in 引用字段.items():
            if cfg.get(字段) and (n.get("id"), 字段) not in 记过 and _描述(c, project_id, 字段, cfg[字段]) is None:
                未找到.append({"节点": n.get("id"), "字段": 字段, "类型": 类型, "名": None, "版本": None, "原id": cfg[字段],
                             "原因": "备份里没记这处引用的名字,这个项目里也没有这个 id", "怎么办": "导入后到「搭建」里这一步的面板重新选一个"})
    return 定义, 布局, 未找到, 改写了
