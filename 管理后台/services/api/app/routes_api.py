#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询路由的接口(2026-11-08 第二期;用户拍「查询理解」下实体识别 / 查询路由 / 意图识别各自列表-详情-配置、各自冻版本、店长助手各选一版)。

和实体识别同一个形状:草稿可改(If-Match)、正式版本不可变(触发器);聊天助手引用确切版本。
一份路由配置 = 一条条规则(条件 → 去向),格式见 runtime/术语.py「查询路由」那一节;冻结前:配置阻断(含「转人工这一版先拦住」)/ 内容一字没改。
「试一句」:先用选定的实体识别版本认出名字和术语,再用这一版路由决定每段去哪、模型会收到什么 —— 和运行时同一套函数。
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
import glossaries_api as _GA
import entity_dicts_api as _ED

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


def _本数(配置):
    return len((配置 or {}).get("规则") or []) if isinstance(配置, dict) else 0


def 可选路由版本(c, project_id):
    """聊天助手编辑页「选一版路由」的下拉框用:这个项目里**冻结了的**版本,同一份新版在前。"""
    return [{"id": r["id"], "名称": r["key"], "版本": f"v{r['version_no']}", "本数": _本数(r["entries"]),
             "冻结于": r["created_at"].isoformat() if r["created_at"] else None}
            for r in c.execute(text("""select id, key, version_no, created_at, entries
                                         from route_versions where project_id=:p and archived_at is null
                                        order by created_at desc nulls last, key, version_no desc limit 200"""), {"p": project_id}).mappings()]   # 11-13:最新冻结的在前,截断只截最老的(同 glossaries_api)


def _详情(c, project_id, sid):
    d = c.execute(text("select * from route_drafts where project_id=:p and id=:i"), {"p": project_id, "i": sid}).mappings().first()
    if not d:
        raise _错(404, "NOT_FOUND", "没有这份路由", "回列表重新进入")
    vs = c.execute(text("""select id, version_no, content_hash, created_at, created_by, entries
                             from route_versions where project_id=:p and key=:k order by version_no desc"""),
                   {"p": project_id, "k": d["key"]}).mappings().all()
    配 = d["entries"] or {}
    阻, 醒 = T.路由配置问题(配)
    return {"id": d["id"], "key": d["key"], "revision": d["revision"], "配置": 配,
            "检查": {"阻断": 阻, "提醒": 醒},
            "去向们": list(T.路由去向们), "条件种类们": list(T.条件种类们), "还没接上的去向": list(T.还没接上的去向),
            "默认去向": T.默认去向,
            "可选实体识别": _ED.可选实体识别版本(c, project_id),   # 「试一句」先用哪一版认实体
            "可选术语": _GA.可选术语版本(c, project_id),   # 「试一句」时连术语一起看
            "版本": [{"id": v["id"], "版本": f"v{v['version_no']}", "内容哈希": v["content_hash"], "本数": _本数(v["entries"]),
                    "冻结于": v["created_at"].isoformat() if v["created_at"] else None, "冻结人": v["created_by"]} for v in vs],
            "note": "草稿可以随便改,**不影响任何在跑的东西**;聊天助手引用的是冻结版本,改了要冻一版新的、再在聊天助手里选它才生效"}


@router.get(前缀 + "/routes")
def 路由列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        rs = c.execute(text("""select d.id, d.key, d.revision, d.entries, d.updated_at,
                                      (select max(v.version_no) from route_versions v where v.project_id=d.project_id and v.key=d.key) 最新
                                 from route_drafts d where d.project_id=:p and d.archived_at is null order by d.updated_at desc"""),
                       {"p": project_id}).mappings().all()
    return {"items": [{"id": r["id"], "key": r["key"], "本数": _本数(r["entries"]), "revision": r["revision"],
                       "最新冻结版本": f"v{r['最新']}" if r["最新"] else None,
                       "更新时间": r["updated_at"].isoformat() if r["updated_at"] else None} for r in rs]}


@router.post(前缀 + "/routes", status_code=201)
async def 建路由(project_id: str, request: Request, me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    体 = await request.json()
    key = str((体 or {}).get("key") or "").strip()
    if not key:
        raise _错(422, "VALIDATION", "要给路由起一个 key", "比如 store-routes", field_errors={"key": "必填"})
    配 = (体 or {}).get("配置") or {"规则": []}
    if not isinstance(配, dict):
        raise _错(422, "VALIDATION", "「配置」要是一个对象", "{规则: [...]}")
    with 事务() as c:
        if c.execute(text("select 1 from route_drafts where project_id=:p and key=:k"), {"p": project_id, "k": key}).first():
            raise _错(409, "DUPLICATE", f"key「{key}」已经有了", "换一个 key,或者打开那份改")
        sid = _新id("rt")
        c.execute(text("""insert into route_drafts (id, organization_id, project_id, key, entries, created_at, created_by,
                              updated_at, revision)
                          values (:i,:o,:p,:k, cast(:e as jsonb), now(), :u, now(), 1)"""),
                  {"i": sid, "o": me.org_id, "p": project_id, "k": key, "e": json.dumps(配, ensure_ascii=False), "u": me.user_id})
        _审计(c, me, "route.create", {"split_dict": sid, "key": key})
    return {"id": sid, "key": key, "revision": 1}


@router.get(前缀 + "/routes/{sid}")
def 路由详情(project_id: str, sid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        return _详情(c, project_id, sid)


@router.patch(前缀 + "/routes/{sid}/draft")
async def 改路由草稿(project_id: str, sid: str, request: Request,
                if_match: str = Header(default=None, alias="If-Match"),
                me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """**保存草稿不改任何在跑的东西**。If-Match 必填(不然「最后写的人赢」,输的那个人看不到自己被覆盖了)。"""
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把详情里的 revision 放进 If-Match 头再提交")
    体 = await request.json()
    if not isinstance((体 or {}).get("配置"), dict):
        raise _错(422, "VALIDATION", "「配置」要是一个对象", "{规则: [...]}")
    with 事务() as c:
        d = c.execute(text("select revision from route_drafts where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": sid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这份路由", "回列表重新进入")
        if str(d["revision"]) != str(if_match):
            raise _错(409, "REVISION_CONFLICT", f"这份草稿已经被改过(你拿的是 {if_match},现在是 {d['revision']})",
                      "刷新看一眼别人改了什么再合并;**不要直接覆盖**")
        c.execute(text("""update route_drafts set entries=cast(:e as jsonb), revision=revision+1, updated_at=now()
                           where project_id=:p and id=:i"""),
                  {"e": json.dumps(体["配置"], ensure_ascii=False), "p": project_id, "i": sid})
        return dict(_详情(c, project_id, sid), note="草稿已保存。**这不影响任何已冻结版本,也不影响在跑的聊天助手。**")


@router.post(前缀 + "/routes/{sid}/versions", status_code=201)
def 冻路由版本(project_id: str, sid: str, me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    with 事务() as c:
        d = c.execute(text("select * from route_drafts where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": sid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这份路由", "回列表重新进入")
        配 = d["entries"] or {}
        阻, _ = T.路由配置问题(配)
        if 阻:
            raise _错(422, "NOT_READY", f"还有 {len(阻)} 处要改才能冻结", "；".join(阻[:3]), field_errors={"阻断": 阻})
        h = _哈希(配)
        同 = c.execute(text("select version_no from route_versions where project_id=:p and key=:k and content_hash=:h"),
                       {"p": project_id, "k": d["key"], "h": h}).first()
        if 同:
            raise _错(409, "NO_CHANGE", f"内容和 v{同[0]} 一模一样", "先改点东西再冻;只是看看的话不用冻")
        号 = c.execute(text("select coalesce(max(version_no), 0) + 1 from route_versions where project_id=:p and key=:k"),
                       {"p": project_id, "k": d["key"]}).scalar()
        vid = _新id("rtv")
        c.execute(text("""insert into route_versions (id, organization_id, project_id, key, version_no, entries, content_hash,
                              created_at, created_by, updated_at, revision)
                          values (:i,:o,:p,:k,:n, cast(:e as jsonb), :h, now(), :u, now(), 1)"""),
                  {"i": vid, "o": me.org_id, "p": project_id, "k": d["key"], "n": 号,
                   "e": json.dumps(配, ensure_ascii=False), "h": h, "u": me.user_id})
        _审计(c, me, "route.version.create", {"split_dict": sid, "key": d["key"], "version": 号, "content_hash": h})
    return {"id": vid, "版本": f"v{号}", "内容哈希": h,
            "note": "版本已冻结,**内容不再原地修改**。聊天助手要用它,得在聊天助手配置里选这一版、出版本、上生产。"}


@router.get(前缀 + "/route-versions/{vid}")
def 路由版本(project_id: str, vid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """一个冻结版本**一次给全**(聊天站本地缓存用):项目 / key / 版本号 / 冻结时间 / 内容哈希 / 整份配置。
    业务表来源这里只有表列 —— 名字由聊天站运行时自己从业务库取。"""
    with 连接() as c:
        v = c.execute(text("""select id, project_id, key, version_no, entries, content_hash, created_at, created_by
                                from route_versions where project_id=:p and id=:i"""), {"p": project_id, "i": vid}).mappings().first()
    if not v:
        raise _错(404, "NOT_FOUND", "没有这个路由版本", "回路由详情选一个版本")
    return {"id": v["id"], "项目": v["project_id"], "key": v["key"], "版本": f"v{v['version_no']}", "version_no": v["version_no"],
            "冻结于": v["created_at"].isoformat() if v["created_at"] else None, "冻结人": v["created_by"],
            "内容哈希": v["content_hash"], "配置": v["entries"] or {}}




@router.post(前缀 + "/route-versions/{vid}/preview")
async def 试一句(project_id: str, vid: str, request: Request, me: 身份 = Depends(要权限("查看有权配置"))):
    """给一句话 → 实体识别认出哪几段 → 这一版路由让每段去哪 → 模型会收到什么。**和运行时同一套函数**
    (runtime/术语.识别实体 / 应用路由 / 上下文段)。
    体:{文本, 实体识别版本?(不给 = 不认名字,只认术语), 术语版本?, 意图?(第三期前手填,看按意图的规则), 试用名单?: {词典名称: [名字…]}}。"""
    体 = await request.json() or {}
    with 连接() as c:
        路 = c.execute(text("select entries from route_versions where project_id=:p and id=:i"), {"p": project_id, "i": vid}).scalar()
        if 路 is None:
            raise _错(404, "NOT_FOUND", "没有这个路由版本", "回查询路由详情选一个版本")
        实 = None
        if 体.get("实体识别版本"):
            实 = c.execute(text("select entries from entity_dict_versions where project_id=:p and id=:i"),
                           {"p": project_id, "i": 体["实体识别版本"]}).scalar()
            if 实 is None:
                raise _错(404, "NOT_FOUND", "没有这个实体识别版本", "回实体识别选一个冻结版本")
        术语们 = []
        if 体.get("术语版本"):
            术语们 = c.execute(text("select entries from glossary_versions where project_id=:p and id=:i"),
                               {"p": project_id, "i": 体["术语版本"]}).scalar()
            if 术语们 is None:
                raise _错(404, "NOT_FOUND", "没有这个术语版本", "回术语配置选一个冻结版本")
    试 = 体.get("试用名单") or {}
    名单, 取不到 = (None, [])
    规则 = None
    if 实:
        按名 = {d.get("表列"): d.get("名称") for d in 实.get("词典") or [] if d.get("来源") == "业务表"}
        名单, 取不到 = T.按配置的名单(实, lambda 表列: 试.get(按名.get(表列)))
        规则 = 实.get("拿不准")
    识 = T.识别实体(体.get("文本") or "", 术语们, 名单, 规则)
    走 = T.应用路由(识, 路, (体.get("意图") or "").strip() or None, (规则 or {}).get("提醒"))
    return {"分段": 识, "走了": 走["走了"], "术语命中": 走["术语命中"], "技能": 走["技能"], "转人工": 走["转人工"],
            "模型会收到": T.上下文段(走["术语命中"], 术语们, 规则, 走["提示们"]),
            "没试到的词典": [{"名称": n, "说明": "业务表来源:后台连不到业务库;要试就在「试用名单」里填几个名字"} for n in 取不到],
            "note": "和运行时同一套函数;意图在第三期接上前要手填"}
