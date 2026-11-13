#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""术语配置 / 语义层的接口(2026-11-06;用户拍「术语配置,做语义层」+ 选型卡四件,见 runtime/术语.py 文件头)。

和 Prompt 同一个形状:草稿可改(If-Match)、正式版本不可变(触发器);工作流 / Agent 引用确切版本。
冻结前三道:格式阻断(runtime/术语.格式问题)/ 内容一字没改 / **取数口指向的工具不存在或停用**(用户拍「算法以代码为准,
术语是说明」—— 说明里写「调某个工具」,那个工具就得真在;不然模型照着说明去调一个没有的工具)。
「试一下」:给一段话 + 一个版本 → 命中了哪些术语、模型会收到的那一段(和运行时同一个函数,不另写一份)。
"""
import hashlib
import json
import os
import sys
import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime"))
import 术语 as T  # noqa: E402

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _哈希(d):
    return "sha256:" + hashlib.sha256(json.dumps(d, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:32]


def _审计(c, me, action, target):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action, target_ref, environment, at, result,
            created_at, created_by)
        values (:i,:o,:p,:a,:ac,:t,:e, now(), 'ok', now(), :a)"""),
              {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id, "ac": action,
               "t": json.dumps(target, ensure_ascii=False), "e": os.environ.get("APP_ENV", "development")})


def 可选术语版本(c, project_id):
    """编辑页「选一版术语」的下拉框用(工作流开始节点 / 智能体 / 聊天助手三处共用,11-06 深夜补):
    这个项目里**冻结了的**版本,**最新冻结的在前**。只给冻结的 —— 草稿会变,选了草稿等于没定。
    ⚠️ 11-13 改排序:原来按名字字母排再取前 200,演示项目攒到 238 个之后,刚冻结的那一版排在 200 名外、
    下拉框里**悄悄没有** —— 而用户刚冻完最想选的就是它。现在按冻结时间倒排,截断只截最老的。"""
    return [{"id": r["id"], "名称": r["key"], "版本": f"v{r['version_no']}", "条数": r["n"],
             "冻结于": r["created_at"].isoformat() if r["created_at"] else None}
            for r in c.execute(text("""select id, key, version_no, created_at, jsonb_array_length(entries) n
                                         from glossary_versions where project_id=:p and archived_at is null
                                        order by created_at desc nulls last, key, version_no desc limit 200"""),
                                    {"p": project_id}).mappings()]


def 取数口问题(c, project_id, 术语们):
    """取数口写的工具,在这个项目里要存在、而且启用(用户拍「算法以代码为准,术语是说明」)。→ 问题清单。"""
    要 = sorted({(t.get("取数口") or {}).get("工具") for t in 术语们 or [] if (t.get("取数口") or {}).get("工具")})
    if not 要:
        return []
    在 = {r["name"]: r["status"] for r in c.execute(text("""select name, status from tool_definitions
                                                           where project_id=:p and name = any(:n)"""),
                                                      {"p": project_id, "n": 要}).mappings()}
    return [f"「{n}」:取数口写的工具在这个项目里{'不存在' if n not in 在 else '已停用'} —— 模型会照着说明去调一个调不了的工具"
            for n in 要 if 在.get(n) != "active"]


def _详情(c, project_id, gid):
    d = c.execute(text("select * from glossary_drafts where project_id=:p and id=:i"), {"p": project_id, "i": gid}).mappings().first()
    if not d:
        raise _错(404, "NOT_FOUND", "没有这张术语表", "回列表重新进入")
    vs = c.execute(text("""select id, version_no, content_hash, created_at, created_by, jsonb_array_length(entries) n
                             from glossary_versions where project_id=:p and key=:k order by version_no desc"""),
                   {"p": project_id, "k": d["key"]}).mappings().all()
    阻, 醒 = T.格式问题(d["entries"] or [])
    return {"id": d["id"], "key": d["key"], "revision": d["revision"], "术语": d["entries"] or [],
            "检查": {"阻断": 阻 + 取数口问题(c, project_id, d["entries"] or []), "提醒": 醒},
            "版本": [{"id": v["id"], "版本": f"v{v['version_no']}", "内容哈希": v["content_hash"], "条数": v["n"],
                    "冻结于": v["created_at"].isoformat() if v["created_at"] else None, "冻结人": v["created_by"]} for v in vs],
            "note": "草稿可以随便改,**不影响任何在跑的东西**;工作流 / Agent 引用的是冻结版本,改了要冻一版新的才生效"}


@router.get(前缀 + "/glossaries")
def 术语表列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        rs = c.execute(text("""select d.id, d.key, d.revision, jsonb_array_length(d.entries) n, d.updated_at,
                                      (select max(v.version_no) from glossary_versions v where v.project_id=d.project_id and v.key=d.key) 最新
                                 from glossary_drafts d where d.project_id=:p and d.archived_at is null order by d.updated_at desc"""),
                       {"p": project_id}).mappings().all()
    return {"items": [{"id": r["id"], "key": r["key"], "条数": r["n"], "revision": r["revision"],
                       "最新冻结版本": f"v{r['最新']}" if r["最新"] else None,
                       "更新时间": r["updated_at"].isoformat() if r["updated_at"] else None} for r in rs]}


@router.post(前缀 + "/glossaries", status_code=201)
async def 建术语表(project_id: str, request: Request, me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    体 = await request.json()
    key = str((体 or {}).get("key") or "").strip()
    if not key:
        raise _错(422, "VALIDATION", "要给术语表起一个 key", "比如 store-terms", field_errors={"key": "必填"})
    with 事务() as c:
        if c.execute(text("select 1 from glossary_drafts where project_id=:p and key=:k"), {"p": project_id, "k": key}).first():
            raise _错(409, "DUPLICATE", f"key「{key}」已经有了", "换一个 key,或者打开那张改")
        gid = _新id("gl")
        c.execute(text("""insert into glossary_drafts (id, organization_id, project_id, key, entries, created_at, created_by,
                              updated_at, revision)
                          values (:i,:o,:p,:k, cast(:e as jsonb), now(), :u, now(), 1)"""),
                  {"i": gid, "o": me.org_id, "p": project_id, "k": key,
                   "e": json.dumps((体 or {}).get("术语") or [], ensure_ascii=False), "u": me.user_id})
        _审计(c, me, "glossary.create", {"glossary": gid, "key": key})
    return {"id": gid, "key": key, "revision": 1}


@router.get(前缀 + "/glossaries/{gid}")
def 术语表详情(project_id: str, gid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        return _详情(c, project_id, gid)


@router.patch(前缀 + "/glossaries/{gid}/draft")
async def 改术语草稿(project_id: str, gid: str, request: Request,
                if_match: str = Header(default=None, alias="If-Match"),
                me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """**保存草稿不改任何在跑的东西**。If-Match 必填(和 Prompt 草稿同一条:不然「最后写的人赢」,输的那个人看不到自己被覆盖了)。"""
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把详情里的 revision 放进 If-Match 头再提交")
    体 = await request.json()
    if not isinstance((体 or {}).get("术语"), list):
        raise _错(422, "VALIDATION", "「术语」要是一个列表", "每条:标准词 / 叫法 / 定义 / 类别(+ 指标的口径和取数口)")
    with 事务() as c:
        d = c.execute(text("select revision from glossary_drafts where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": gid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这张术语表", "回列表重新进入")
        if str(d["revision"]) != str(if_match):
            raise _错(409, "REVISION_CONFLICT", f"这张草稿已经被改过(你拿的是 {if_match},现在是 {d['revision']})",
                      "刷新看一眼别人改了什么再合并;**不要直接覆盖**")
        c.execute(text("""update glossary_drafts set entries=cast(:e as jsonb), revision=revision+1, updated_at=now()
                           where project_id=:p and id=:i"""),
                  {"e": json.dumps(体["术语"], ensure_ascii=False), "p": project_id, "i": gid})
        return dict(_详情(c, project_id, gid), note="草稿已保存。**这不影响任何已冻结版本,也不影响在跑的工作流 / Agent。**")


@router.post(前缀 + "/glossaries/{gid}/versions", status_code=201)
def 冻术语版本(project_id: str, gid: str, me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    with 事务() as c:
        d = c.execute(text("select * from glossary_drafts where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": gid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这张术语表", "回列表重新进入")
        条 = d["entries"] or []
        阻, _ = T.格式问题(条)
        阻 += 取数口问题(c, project_id, 条)
        if not 条:
            阻.append("一条术语都没有")
        if 阻:
            raise _错(422, "NOT_READY", f"还有 {len(阻)} 处要改才能冻结", "；".join(阻[:3]), field_errors={"阻断": 阻})
        h = _哈希(条)
        同 = c.execute(text("select version_no from glossary_versions where project_id=:p and key=:k and content_hash=:h"),
                       {"p": project_id, "k": d["key"], "h": h}).first()
        if 同:
            raise _错(409, "NO_CHANGE", f"内容和 v{同[0]} 一模一样", "先改点东西再冻;只是看看的话不用冻")
        号 = c.execute(text("select coalesce(max(version_no), 0) + 1 from glossary_versions where project_id=:p and key=:k"),
                       {"p": project_id, "k": d["key"]}).scalar()
        vid = _新id("glv")
        c.execute(text("""insert into glossary_versions (id, organization_id, project_id, key, version_no, entries, content_hash,
                              created_at, created_by, updated_at, revision)
                          values (:i,:o,:p,:k,:n, cast(:e as jsonb), :h, now(), :u, now(), 1)"""),
                  {"i": vid, "o": me.org_id, "p": project_id, "k": d["key"], "n": 号,
                   "e": json.dumps(条, ensure_ascii=False), "h": h, "u": me.user_id})
        _审计(c, me, "glossary.version.create", {"glossary": gid, "key": d["key"], "version": 号, "content_hash": h})
    return {"id": vid, "版本": f"v{号}", "内容哈希": h,
            "note": "版本已冻结,**内容不再原地修改**。工作流 / Agent 要用它,得在配置里选这一版。"}


@router.get(前缀 + "/glossary-versions/{vid}")
def 术语版本(project_id: str, vid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """一个冻结版本**一次给全**(聊天站本地缓存用,11-06 和并行会话对过):项目 / key / 版本号 / 冻结时间 / 内容哈希 / 全部术语。
    权限和聊天站现在调的 /chat-assistants/by-role/{role}/production 同一个(服务账号工号)。
    这一版没有术语 → 200 + 术语=[](业务状态);拿不到 200 是环境问题 —— 两件事,不把错误包成空列表。"""
    with 连接() as c:
        v = c.execute(text("""select id, project_id, key, version_no, entries, content_hash, created_at, created_by
                                from glossary_versions where project_id=:p and id=:i"""), {"p": project_id, "i": vid}).mappings().first()
    if not v:
        raise _错(404, "NOT_FOUND", "没有这个术语版本", "回术语表详情选一个版本")
    return {"id": v["id"], "项目": v["project_id"], "key": v["key"], "版本": f"v{v['version_no']}", "version_no": v["version_no"],
            "冻结于": v["created_at"].isoformat() if v["created_at"] else None, "冻结人": v["created_by"],
            "内容哈希": v["content_hash"], "术语": v["entries"] or []}


@router.post(前缀 + "/glossary-versions/{vid}/preview")
async def 试一下(project_id: str, vid: str, request: Request, me: 身份 = Depends(要权限("查看有权配置"))):
    """给一段话 → 命中了哪些术语、模型会收到的那一段。**和运行时同一个函数**(runtime/术语.匹配 / 上下文段)。"""
    体 = await request.json()
    with 连接() as c:
        条 = c.execute(text("select entries from glossary_versions where project_id=:p and id=:i"),
                       {"p": project_id, "i": vid}).scalar()
    if 条 is None:
        raise _错(404, "NOT_FOUND", "没有这个术语版本", "回术语表详情选一个版本")
    命 = T.匹配((体 or {}).get("文本") or "", 条)
    return {"命中": 命, "模型会收到": T.上下文段(命, 条),
            "note": "只带这次提到的那几条(用户 11-06 拍);一条都没提到时模型什么都不收到"}
