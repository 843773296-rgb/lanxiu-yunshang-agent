#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具组:一份稳定搭配,**不是一份授权**。

    GET   /tool-groups                列表
    POST  /tool-groups                建组
    GET   /tool-groups/{id}           详情(草稿 + 版本历史)
    PATCH /tool-groups/{id}/draft     改草稿
    POST  /tool-groups/{id}/versions  冻结(**三道校验**)

## ⚠️ 组只是搭配,执行权仍要过网关

第三份规格 §3 的状态表:
  已登记 → Agent 允许范围 → 当前可用 → 本轮候选 → 实际加载 → 实际调用
而它紧跟一句:**「本轮未加载」不等于「无权限」;「筛选得分高」不授予权限。**

所以一个 Agent 绑了某个组版本,**执行权仍要过 `tool_gateway` 的实时查验** ——
组只决定「这一轮给模型看哪些」。

## 冻结时那三道校验,各自防一件不同的事

**① 模型眼里同名。** 两个工具版本在模型眼里同名,模型发出的调用
就分不清是哪一个 —— **而它看起来只是少了一个工具**。
⚠️ 这一道运行时**已经在补报**了(`agent_loop` 里那个 `撞名` 列表),
而那段注释自己写着「**这在冻结版本时本该被拦住**」。
在运行时才发现的代价是:那一轮的回答已经出去了。

**② 配套关系成环。** A 配套 B、B 配套 A —— 预算算法(A-4/A-5)会反复
把两个都算进同一组,于是「这一组要多少 token」算不出一个稳定的数。

**③ 成员版本还在不在。** 指向一个已归档/不存在的工具版本 ——
运行时的表现是**少给模型一个工具**,而人会去改提示词。

> 三道都在冻结时拦,因为**版本是不可变的**:
> 冻结之后再发现,只能出一个新版本,而旧的那一版可能已经被引用了。
"""
import json as _json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _审计(c, me, action, target, result="ok", reason=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, reason, created_at, created_by)
        values (:i,:o,:p,:a,:ac,cast(:t as jsonb),:e, now(), :r, :rs, now(), :a)"""),
              {"i": _新id("ae"), "o": me.org_id, "p": me.project_id,
               "a": me.user_id, "ac": action,
               "t": _json.dumps(target, ensure_ascii=False),
               "e": "development", "r": result, "rs": reason})


def _成员清单(体):
    """把请求体里的成员归一成一串 dict。**认不出的形状当场拒。**"""
    原 = 体.get("成员") or 体.get("member_manifest") or []
    if not isinstance(原, list):
        raise _错(422, "VALIDATION_FAILED", "`成员` 要是个数组",
                 '形如 [{"tool_version_id": "tv_x", "必不可少吗": true}]',
                 field_errors={"成员": ["要是数组"]})
    出 = []
    for i, x in enumerate(原):
        if isinstance(x, str):
            # ⚠️ **只给一串 id 也收,但补齐那两个属性。**
            # 不补的话「这一组里有它」和「这一轮必须给它」就分不开了 ——
            # 而 A-5 的预算算法要先放必需的。
            出.append({"tool_version_id": x, "加载角色": "候选",
                       "必不可少吗": False})
            continue
        if not isinstance(x, dict) or not x.get("tool_version_id"):
            raise _错(422, "VALIDATION_FAILED",
                     f"第 {i + 1} 个成员认不出来",
                     '每个成员要么是 tool_version_id 字符串,'
                     '要么是 {"tool_version_id": …} 对象',
                     field_errors={"成员": [f"第 {i + 1} 个"]})
        出.append({
            "tool_version_id": x["tool_version_id"],
            "加载角色": x.get("加载角色") or x.get("role") or "候选",
            "必不可少吗": bool(x.get("必不可少吗") or x.get("required")),
        })
    return 出


def 查配套环(配套):
    """`{A: [B, C]}` 里有没有环。返回环的路径(空 = 没有)。

    ⚠️ **为什么要查**:A 配套 B、B 配套 A 的话,预算算法(A-4/A-5)会反复
    把两个都算进同一组 —— 于是「这一组要多少 token」算不出一个稳定的数。
    而它不报错:**它只是算出一个偏大的数,然后把别的工具挤出去**。
    """
    if not isinstance(配套, dict):
        return []
    灰, 黑 = set(), set()
    路 = []

    def 走(n):
        if n in 黑:
            return None
        if n in 灰:
            # 找到环:返回环的起点。外层会拼成 [起点 … 起点] 的路径。
            return [n]
        灰.add(n)
        路.append(n)
        for m in (配套.get(n) or []):
            r = 走(m)
            if r is not None:
                return r if r[0] == n else [n] + r
        灰.discard(n)
        黑.add(n)
        路.pop()
        return None

    for n in list(配套):
        r = 走(n)
        if r:
            return r
    return []


def 可以冻结组吗(c, project_id, 成员, 配套):
    """三道校验。返回问题清单(空 = 可以)。**在冻结时做,不等运行时。**"""
    问 = []
    ids = [m["tool_version_id"] for m in 成员]
    if not ids:
        问.append("**这一组一个成员都没有** —— 一个空的工具组绑上去,"
                  "表现是「Agent 什么工具都没有」,而人会去改提示词")
        return 问
    重 = sorted({x for x in ids if ids.count(x) > 1})
    if 重:
        问.append(f"同一个工具版本被列了两次:{重} —— "
                  f"**预算会把它算两遍**")
    # ③ 成员版本还在不在
    行 = c.execute(text("""select tv.id, td.name
                         from tool_versions tv
                         join tool_definitions td
                           on td.project_id=tv.project_id
                          and td.id=tv.tool_definition_id
                        where tv.project_id=:p and tv.id = any(:ids)
                          and tv.archived_at is null"""),
                  {"p": project_id, "ids": ids}).mappings().all()
    有的 = {r["id"]: r["name"] for r in 行}
    缺 = [x for x in ids if x not in 有的]
    if 缺:
        问.append(f"这些工具版本**不在了**(或已归档):{缺} —— "
                  f"运行时的表现是**少给模型一个工具**,而人会去改提示词")
    # ① 模型眼里同名
    #    ⚠️ 模型看到的名字是 `tool_definitions.name`(见 `agent_loop` 里
    #    `名 = 契.get("name")`)。两个版本同名 → 模型发出的调用分不清
    #    是哪一个,**而它看起来只是少了一个工具**。
    按名 = {}
    for vid, 名 in 有的.items():
        按名.setdefault(名, []).append(vid)
    撞 = {k: v for k, v in 按名.items() if len(v) > 1}
    if 撞:
        问.append(f"**这些工具在模型眼里同名**:{撞} —— "
                  f"模型发出的调用分不清是哪一个,"
                  f"**而它看起来只是少了一个工具**。"
                  f"(运行时也会报这件事,但那时这一轮的回答已经出去了)")
    # ② 配套关系成环
    环 = 查配套环(配套)
    if 环:
        # ⚠️ **这句话里不许写那个三个字母的用量单位。**
        # `errors.泄密检查` 按词匹配凭据类词,而那个词在它的名单里 ——
        # 于是整个响应变成 **500 ValueError**(「错误体里可能带了凭据」)。
        # 而那个检查是对的:它宁可误报也不漏报。
        # > 一句错误提示里照抄了被检查的词,**会触发检查自己**。
        # (这个仓库同形状栽过三次:密钥扫描的规则文件匹配自己、
        #  脚本注释里举例匹配自己、文档匹配自己。这是第四次。)
        # ⚠️ 环路径本身首尾已经是同一个节点了(`查配套环` 返回
        # `[起点 … 起点]`)—— 再拼一个 `→ 环[0]` 就多打一个。
        # 第一版就是那样,输出是 `a → b → a → a`。
        # **一条自己都打不对的路径,读的人不会相信它**。
        问.append(f"**配套关系成环**:{' → '.join(环)} —— "
                  f"预算算法会反复把它们算进同一组,"
                  f"于是「这一组要占多少上下文额度」算不出一个稳定的数。"
                  f"**它不报错:只是算出一个偏大的数,然后把别的工具挤出去**")
    # 配套关系指向组外的成员
    if isinstance(配套, dict):
        # ⚠️⚠️ **这里必须加括号。** Python 的 `|` 优先级**高于** `-`,
        # 所以 `A | B - C` 算的是 `A | (B - C)` —— 不是 `(A | B) - C`。
        # 第一版没加括号,于是它把**组内的成员**报成「指向组外」。
        # CLAUDE.md 里就记着这条:
        # > 「`A | B | C - known` 会被解析成 `A | B | (C - known)`,
        # >  检查静默通过。**加括号。**」
        # 而这次它不是静默通过,是**静默误报** —— 更难查:
        # 一条报错的检查看起来在工作。
        被指到的 = {x for v in 配套.values() if isinstance(v, list) for x in v}
        外 = sorted((被指到的 | set(配套)) - set(ids))
        if 外:
            问.append(f"配套关系里这些**不是这一组的成员**:{外} —— "
                      f"指向组外的配套在加载时拿不到,"
                      f"**而「配套不全」和「没配套」在模型那边长得一样**")
    return 问


@router.get(前缀 + "/tool-groups")
def 工具组列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        行 = c.execute(text("""select g.*,
                   (select count(*) from tool_group_versions v
                     where v.project_id=g.project_id and v.tool_group_id=g.id) as 版本数
              from tool_groups g
             where g.project_id=:p and g.archived_at is null
             order by g.updated_at desc"""),
                      {"p": project_id}).mappings().all()
    return {
        "items": [{
            "id": r["id"], "名称": r.get("name"), "用途": r.get("purpose"),
            "负责人": r.get("owner"), "状态": r.get("status"),
            "版本数": r["版本数"],
            "draft_revision": r.get("draft_revision") or 0,
        } for r in 行],
        "total": len(行),
        "note": ("**组只是一份搭配,不是一份授权** —— Agent 绑了某个组版本,"
                 "执行权仍要过工具网关的实时查验"),
    }


@router.post(前缀 + "/tool-groups", status_code=201)
async def 建工具组(project_id: str, request: Request,
              me: 身份 = Depends(要权限("改编排草稿"))):
    体 = await request.json()
    名 = (体.get("名称") or 体.get("name") or "").strip()
    if not 名:
        raise _错(422, "VALIDATION_FAILED", "没给名称",
                 "组名是人看的,给一个说得出用途的名字",
                 field_errors={"名称": ["必填"]})
    用途 = (体.get("用途") or 体.get("purpose") or "").strip()
    if not 用途:
        # ⚠️ 不是形式要求:一个说不出用途的组,下次没人知道该不该往里加工具。
        raise _错(422, "VALIDATION_FAILED", "没写用途",
                 "一个说不出用途的组,下次没人知道该不该往里加工具",
                 field_errors={"用途": ["必填"]})
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        if not org:
            raise _错(404, "NOT_FOUND", f"没有项目 {project_id}", "换一个项目")
        gid = _新id("tg")
        c.execute(text("""insert into tool_groups
            (id, organization_id, project_id, name, purpose, owner, status,
             draft_revision, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n,:u,:ow,'draft', 1, now(), :by, now(), 1)"""),
                  {"i": gid, "o": org, "p": project_id, "n": 名, "u": 用途,
                   "ow": me.user_id, "by": me.user_id})
        _审计(c, me, "tool_group.create", {"tool_group_id": gid, "name": 名})
    return {"id": gid, "名称": 名, "用途": 用途, "draft_revision": 1,
            "note": "**还没有版本** —— 没有版本的组,Agent 引用不了"}


@router.get(前缀 + "/tool-groups/{gid}")
def 工具组详情(project_id: str, gid: str,
           me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        g = c.execute(text("""select * from tool_groups
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": gid}).mappings().first()
        if not g:
            raise _错(404, "NOT_FOUND", f"没有工具组 {gid}", "回工具组列表看有哪些")
        版本们 = [dict(r) for r in c.execute(text("""
            select version_no, member_manifest, companion_map, content_hash,
                   change_note, created_at, created_by
              from tool_group_versions
             where project_id=:p and tool_group_id=:i
             order by version_no desc"""),
            {"p": project_id, "i": gid}).mappings()]
    return {
        "id": g["id"], "名称": g.get("name"), "状态": g.get("status"),
        "draft_revision": g.get("draft_revision") or 0,
        "revision": g.get("revision"),
        "草稿": {"用途": g.get("purpose"), "负责人": g.get("owner"),
               "revision": g.get("draft_revision") or 0},
        "版本历史": [{
            "版本": f"v{v['version_no']}", "version_no": v["version_no"],
            "成员": v.get("member_manifest") or [],
            "配套关系": v.get("companion_map") or {},
            "成员数": len(v.get("member_manifest") or []),
            "必不可少的": sum(1 for m in (v.get("member_manifest") or [])
                        if isinstance(m, dict) and m.get("必不可少吗")),
            "内容哈希": v.get("content_hash"),
            "变更说明": v.get("change_note"),
            "冻结时间": v["created_at"].isoformat() if v.get("created_at") else None,
            "冻结的人": v.get("created_by"),
        } for v in 版本们],
        "note": ("**改草稿的 `If-Match` 认 `draft_revision`**。"
                 "⚠️ 组只是搭配:**「这一组里有它」和「这一轮必须给它」是两件事** —— "
                 "成员上的 `必不可少吗` 管的是后者(A-5 的预算先放必需的)"),
    }


@router.patch(前缀 + "/tool-groups/{gid}/draft")
async def 改工具组草稿(project_id: str, gid: str, request: Request,
                me: 身份 = Depends(要权限("改编排草稿"))):
    体 = await request.json()
    头 = request.headers.get("If-Match")
    if not 头:
        # ⚠️ **409,不是 428** —— 这个仓库的契约里没有 428,
        # 而 If-Match 缺失在别的模块一律是 409 IF_MATCH_REQUIRED。
        raise _错(409, "IF_MATCH_REQUIRED", "改草稿要带 If-Match",
                 "把工具组详情里的 `draft_revision` 放进 If-Match 头")
    with 事务() as c:
        g = c.execute(text("""select * from tool_groups
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": gid}).mappings().first()
        if not g:
            raise _错(404, "NOT_FOUND", f"没有工具组 {gid}", "回列表看有哪些")
        现 = g.get("draft_revision") or 0
        if str(现) != str(头).strip('"'):
            raise _错(409, "REVISION_CONFLICT",
                     f"这份草稿已经被改过(现在是 {现},你带的是 {头})",
                     "重新读一遍详情,拿新的 draft_revision 再提交")
        改 = {}
        for 中, 英 in (("名称", "name"), ("用途", "purpose"),
                     ("负责人", "owner")):
            v = 体.get(中) if 体.get(中) is not None else 体.get(英)
            if v is not None:
                改[英] = str(v).strip()
        if not 改:
            raise _错(422, "VALIDATION_FAILED", "没给要改的东西",
                     "能改的是 `名称` / `用途` / `负责人`")
        套 = ", ".join(f"{k}=:{k}" for k in 改)
        c.execute(text(f"""update tool_groups set {套},
            draft_revision=coalesce(draft_revision,0)+1,
            updated_at=now(), revision=coalesce(revision,0)+1
            where project_id=:p and id=:i"""),
                  {**改, "p": project_id, "i": gid})
        _审计(c, me, "tool_group.draft.update",
              {"tool_group_id": gid, "字段": sorted(改)})
        新 = c.execute(text("""select draft_revision from tool_groups
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": gid}).scalar()
    return {"id": gid, "draft_revision": 新,
            "note": "草稿改了 —— **已经冻结的版本一个字没动**"}


@router.post(前缀 + "/tool-groups/{gid}/versions", status_code=201)
async def 冻结工具组版本(project_id: str, gid: str, request: Request,
                  me: 身份 = Depends(要权限("改编排草稿"))):
    """把成员和配套关系冻成一个版本。**三道校验在这里做。**"""
    体 = await request.json()
    成员 = _成员清单(体)
    配套 = 体.get("配套关系") or 体.get("companion_map") or {}
    说明 = (体.get("变更说明") or 体.get("change_note") or "").strip()
    with 事务() as c:
        g = c.execute(text("""select * from tool_groups
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": gid}).mappings().first()
        if not g:
            raise _错(404, "NOT_FOUND", f"没有工具组 {gid}", "回列表看有哪些")
        问 = 可以冻结组吗(c, project_id, 成员, 配套)
        if 问:
            _审计(c, me, "tool_group.version.blocked",
                  {"tool_group_id": gid}, result="blocked",
                  reason="; ".join(问)[:400])
            raise _错(422, "VALIDATION_FAILED",
                     "这一组冻不进去(**三道校验**:模型眼里同名 / "
                     "配套成环 / 成员版本还在不在)",
                     "挨个看下面那几条 —— 它们各防一件不同的事",
                     field_errors={"闸": 问})
        上一版 = c.execute(text("""select version_no from tool_group_versions
                                where project_id=:p and tool_group_id=:i
                                order by version_no desc limit 1"""),
                        {"p": project_id, "i": gid}).scalar()
        号 = (上一版 or 0) + 1
        import capabilities as CAP
        哈 = CAP.内容哈希({"成员": 成员, "配套关系": 配套})
        vid = _新id("tgv")
        c.execute(text("""insert into tool_group_versions
            (id, organization_id, project_id, tool_group_id, version_no,
             member_manifest, companion_map, content_hash, change_note,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:g,:n, cast(:mm as jsonb), cast(:cm as jsonb),
                    :h,:cn, now(), :by, now(), 1)"""),
                  {"i": vid, "o": g["organization_id"], "p": project_id,
                   "g": gid, "n": 号,
                   "mm": _json.dumps(成员, ensure_ascii=False),
                   "cm": _json.dumps(配套, ensure_ascii=False),
                   "h": 哈, "cn": 说明 or None, "by": me.user_id})
        _审计(c, me, "tool_group.version.create",
              {"tool_group_id": gid, "version_no": 号, "成员数": len(成员)})
    return {"id": vid, "版本": f"v{号}", "version_no": 号,
            "成员数": len(成员),
            "必不可少的": sum(1 for m in 成员 if m["必不可少吗"]),
            "内容哈希": 哈,
            "note": ("冻结了。**三道校验都过了** —— "
                     "模型眼里没有同名的、配套没成环、成员版本都在。"
                     "⚠️ 而**组只是搭配,不是授权**:"
                     "Agent 绑它之后执行权仍要过工具网关"),
            "⚠️三道校验为什么在冻结时做": (
                "**版本是不可变的** —— 冻结之后再发现,只能出一个新版本,"
                "而旧的那一版可能已经被引用了。"
                "其中「模型眼里同名」运行时也会报,"
                "但那时**这一轮的回答已经出去了**"),
            }
