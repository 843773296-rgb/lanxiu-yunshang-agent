#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""筛选策略:**指定怎么选工具,而不是替谁授权**。

    GET   /tool-selection-policies                列表
    POST  /tool-selection-policies                建策略
    GET   /tool-selection-policies/{id}           详情
    PATCH /tool-selection-policies/{id}/draft     改草稿
    POST  /tool-selection-policies/{id}/validate  服务端校验(**不落版本**)
    POST  /tool-selection-policies/{id}/versions  冻结(**不改变生产引用**)

## ⚠️ 这是第四阶段的**配置面**,检索算法还没做

规格 §16 第四阶段是「关键词筛选」:目录索引 / 任务查询 / 候选 / 预算 /
运行内补搜。这个文件只做**策略配置**那一半 —— 它不碰 `agent_loop`。

**为什么分开做**:检索算法要先摆选型卡(召回口径、排序融合、预算贪心),
而且要改运行时。
> 一个半做的筛选器会让 Agent 看不到某些工具 ——
> **而那表现成「它换了个办法做事」,不报错。**

所以:策略能配、能校验、能冻结;**而没有任何东西在消费它**。
这件事写在返回里(`⚠️还没生效`)——
> 一个配得出来而没人消费的策略,和一个生效了的策略,
> **在界面上长得一模一样。**

## ⚠️ 身份、授权、密钥、对象范围**不进策略**

规格 §14.3 最后一句:「用户/项目身份、真实授权、密钥、对象允许范围
由服务端绑定,**不放进模型可填写的筛选参数**」。

所以这里**明确拒收**那几类键 —— 收下来的话,
一个能改策略的人就能通过策略影响授权,而
**规格 §3 明写「筛选得分高不授予权限」**。
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

# ── 词表:**首版支持哪两种,扩展是哪两种**(规格 §4.2 那张表的「本文安排」)──
模式表 = {
    "fixed_group": ("固定工具组", "首版支持"),
    "keyword_search": ("关键词检索", "首版支持"),
    "hybrid": ("混合检索", "扩展 —— 要向量构建和排序融合,**按同题结果再启用**"),
    "vendor_native": ("供应商原生工具搜索",
                      "扩展 —— **要连接实际支持该协议**,不做默认假设"),
}
首版支持的 = [k for k, v in 模式表.items() if v[1] == "首版支持"]
空结果动作 = {
    "rediscover_then_stop": "补搜一次,还没有就停",
    "stop": "直接停",
}
目录出错动作 = {
    "use_compatible_fixed_group_or_stop": "退回兼容的固定工具组,没有就停",
    "stop": "直接停",
}
加载方式 = {"append_within_run": "运行内追加"}
# ⚠️ **服务端绑定的东西不许进策略**(规格 §14.3)。
# 收下来的话,一个能改策略的人就能通过策略影响授权。
不许进策略的 = ("user", "身份", "principal", "authz", "授权", "scope", "范围",
            "secret", "凭据", "token", "key", "密钥", "project", "org")


def _新id(p):
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _审计(c, me, action, target, result="ok", reason=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, reason, created_at, created_by)
        values (:i,:o,:p,:a,:ac,cast(:t as jsonb),:e, now(), :r, :rs, now(), :a)"""),
              {"i": _新id("ae"), "o": me.org_id, "p": me.project_id,
               "a": me.user_id, "ac": action,
               "t": _json.dumps(target, ensure_ascii=False),
               "e": "development", "r": result, "rs": reason})


def 校验策略(c, project_id, 配):
    """返回 (问题清单, 归一后的配置)。**问题清单空 = 可以冻结。**"""
    问 = []
    模式 = (配.get("模式") or 配.get("mode") or "").strip()
    if 模式 not in 模式表:
        问.append(f"认不出的模式 {模式!r} —— 认得的是 {sorted(模式表)}")
    elif 模式 not in 首版支持的:
        # ⚠️ **不静默接受扩展模式。** 接受了它会配得出来、冻得进去,
        # 而运行时压根不认 —— 于是「配了混合检索」和「在跑混合检索」
        # 长得一模一样。规格 §4.2 明写它们要「按同题结果再启用」。
        问.append(f"**{模式表[模式][0]} 是扩展模式,首版不支持** —— "
                  f"{模式表[模式][1]}。"
                  f"接受它的话:配得出来、冻得进去,**而运行时压根不认** —— "
                  f"于是「配了它」和「在跑它」长得一模一样")
    限 = 配.get("限额") or 配.get("limits") or {}
    if not isinstance(限, dict):
        问.append("`限额` 要是个对象")
        限 = {}
    # ⚠️ 这几个数的初值在规格 §14.3,**是设计初值不是实测出来的**。
    for 键, 中, 下限 in (("initial_candidates", "初次候选数", 1),
                      ("new_definition_tokens", "单次新增定义额度", 1),
                      ("active_definition_tokens", "活动定义总额度", 1),
                      ("max_rediscovery", "最多补搜几次", 0),
                      ("selection_timeout_ms", "筛选超时(毫秒)", 1)):
        v = 限.get(键)
        if v is None:
            问.append(f"`限额.{键}`({中})没给 —— "
                      f"**不给默认值**:一个猜出来的预算会在它不够用那天"
                      f"表现成「模型没看到那个工具」,而不报错")
        elif not isinstance(v, int) or isinstance(v, bool) or v < 下限:
            问.append(f"`限额.{键}`({中})要是 ≥ {下限} 的整数,拿到 {v!r}")
    if (isinstance(限.get("new_definition_tokens"), int)
            and isinstance(限.get("active_definition_tokens"), int)
            and 限["new_definition_tokens"] > 限["active_definition_tokens"]):
        # ⚠️ 单次新增比活动总额还大 —— 那个单次上限永远碰不到,
        # 于是它看起来在限制什么,实际上不限制任何东西。
        问.append("`new_definition_tokens` 比 `active_definition_tokens` 还大 —— "
                  "**那个单次上限永远碰不到**,它看起来在限制什么,"
                  "实际上不限制任何东西")
    空 = (配.get("没结果怎么办") or 配.get("empty_result_action") or "").strip()
    if 空 not in 空结果动作:
        问.append(f"认不出的 `没结果怎么办`:{空!r} —— 认得的是 {sorted(空结果动作)}")
    错 = (配.get("目录出错怎么办") or 配.get("catalog_error_action") or "").strip()
    if 错 not in 目录出错动作:
        问.append(f"认不出的 `目录出错怎么办`:{错!r} —— "
                  f"认得的是 {sorted(目录出错动作)}")
    # ⚠️⚠️ **这两个必须分开,而且不许相同地对待。**
    # 「目录里没有合适的工具」和「目录本身取不到」下一步完全不同:
    # 前者该补搜或停止,后者该退回固定组。合成一个的话,
    # **一次索引故障会被当成「这个任务没有可用工具」**。
    载 = (配.get("加载方式") or 配.get("loading") or "append_within_run").strip()
    if 载 not in 加载方式:
        问.append(f"认不出的 `加载方式`:{载!r} —— 认得的是 {sorted(加载方式)}")
    缓存 = bool(配.get("开候选缓存") or 配.get("candidate_cache_enabled"))
    if 缓存:
        # ⚠️ A-7:**首版关闭候选缓存**。
        问.append("**首版不许开候选缓存**(A-7:为减少复杂度)—— "
                  "而且开了之后命中也只能复用候选 ID,"
                  "**权限、启停和版本仍要实时复核**;"
                  "少复核一样,一条被撤回的授权就会靠缓存继续生效")
    路由 = bool(配.get("开独立路由") or 配.get("independent_router_enabled"))
    # 目录快照:给了就要存在而且就绪(规格 §14.4「只有就绪快照可绑定」)
    快照 = (配.get("目录快照") or 配.get("catalog_snapshot_ref") or "").strip() or None
    if 快照:
        r = c.execute(text("""select status from tool_catalog_snapshots
                            where project_id=:p and id=:i
                              and archived_at is null"""),
                      {"p": project_id, "i": 快照}).scalar()
        if r is None:
            问.append(f"目录快照 {快照} 不存在(或已归档)")
        elif r != "已就绪":
            问.append(f"目录快照 {快照} 现在是「{r}」—— "
                      f"**只有「已就绪」的快照能被绑定**(规格 §14.4):"
                      f"半建好的索引绑上去,表现是「某些工具搜不到」而不是报错")
    elif 模式 == "keyword_search":
        问.append("关键词检索模式**必须绑一个目录快照** —— "
                  "不绑的话它拿什么去检索?"
                  "(而「没绑」和「绑了个空的」在配置上长得一样)")
    组版本 = (配.get("默认工具组版本") or 配.get("default_group_version_ref")
            or "").strip() or None
    if 组版本:
        r = c.execute(text("""select 1 from tool_group_versions
                            where project_id=:p and id=:i
                              and archived_at is null"""),
                      {"p": project_id, "i": 组版本}).first()
        if not r:
            问.append(f"默认工具组版本 {组版本} 不存在(或已归档)")
    elif 模式 == "fixed_group":
        问.append("固定工具组模式**必须绑一个组版本** —— 不绑的话它给模型什么?")
    # ⚠️ 服务端绑定的东西不许进策略
    脏 = sorted(k for k in 配
                if any(w in str(k).lower() for w in 不许进策略的))
    if 脏:
        问.append(f"这些键**不许进策略**:{脏} —— "
                  f"身份 / 授权 / 密钥 / 对象范围由服务端绑定(规格 §14.3)。"
                  f"收下来的话,一个能改策略的人就能通过策略影响授权,"
                  f"**而规格 §3 明写「筛选得分高不授予权限」**")
    归一 = {
        "selection_mode": 模式, "limits": 限, "loading_type": 载,
        "empty_result_action": 空, "catalog_error_action": 错,
        "independent_router_enabled": 路由,
        "candidate_cache_enabled": 缓存,
        "catalog_snapshot_ref": 快照,
        "default_group_version_ref": 组版本,
        "release_criteria": 配.get("发布门槛") or 配.get("release_criteria") or {},
    }
    return 问, 归一


def _还没生效():
    return ("**这条策略还没有任何东西在消费它。** 规格 §16 第四阶段的"
            "检索实现(目录索引 / 候选 / 预算 / 运行内补搜)还没做 —— "
            "这一块只做配置面,不碰 `agent_loop`。"
            "> 一个配得出来而没人消费的策略,和一个生效了的策略,"
            "**在界面上长得一模一样** —— 所以这句话必须在")


@router.get(前缀 + "/tool-selection-policies")
def 策略列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        行 = c.execute(text("""select p.*,
                   (select count(*) from tool_selection_policy_versions v
                     where v.project_id=p.project_id
                       and v.tool_selection_policy_id=p.id) as 版本数
              from tool_selection_policies p
             where p.project_id=:p and p.archived_at is null
             order by p.updated_at desc"""),
                      {"p": project_id}).mappings().all()
    return {
        "items": [{
            "id": r["id"], "名称": r.get("name"), "用途": r.get("purpose"),
            "负责人": r.get("owner"), "状态": r.get("status"),
            "版本数": r["版本数"],
            "draft_revision": r.get("draft_revision") or 0,
        } for r in 行],
        "total": len(行),
        "可选模式": [{"值": k, "中文": v[0], "首版支持吗": v[1] == "首版支持",
                  "说明": v[1]} for k, v in 模式表.items()],
        "可选的没结果怎么办": [{"值": k, "中文": v} for k, v in 空结果动作.items()],
        "可选的目录出错怎么办": [{"值": k, "中文": v}
                        for k, v in 目录出错动作.items()],
        "⚠️两个动作别混": ("「目录里没有合适的工具」和「目录本身取不到」"
                    "下一步完全不同 —— 前者该补搜或停止,后者该退回固定组。"
                    "合成一个的话,**一次索引故障会被当成"
                    "「这个任务没有可用工具」**"),
        "⚠️还没生效": _还没生效(),
        "note": ("策略指定**怎么选工具**,不替谁授权 —— "
                 "规格 §3:「筛选得分高不授予权限」"),
    }


@router.post(前缀 + "/tool-selection-policies", status_code=201)
async def 建策略(project_id: str, request: Request,
             me: 身份 = Depends(要权限("改筛选策略"))):
    体 = await request.json()
    名 = (体.get("名称") or 体.get("name") or "").strip()
    用途 = (体.get("用途") or 体.get("purpose") or "").strip()
    坏 = {k: ["必填"] for k, v in (("名称", 名), ("用途", 用途)) if not v}
    if 坏:
        raise _错(422, "VALIDATION_FAILED", "名称和用途都要给",
                 "一个说不出用途的策略,下次没人知道它为什么长这样",
                 field_errors=坏)
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        if not org:
            raise _错(404, "NOT_FOUND", f"没有项目 {project_id}", "换一个项目")
        pid = _新id("tsp")
        c.execute(text("""insert into tool_selection_policies
            (id, organization_id, project_id, name, purpose, owner, status,
             draft_revision, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n,:u,:ow,'draft', 1, now(), :by, now(), 1)"""),
                  {"i": pid, "o": org, "p": project_id, "n": 名, "u": 用途,
                   "ow": me.user_id, "by": me.user_id})
        _审计(c, me, "selection_policy.create", {"policy_id": pid, "name": 名})
    return {"id": pid, "名称": 名, "用途": 用途, "draft_revision": 1,
            "⚠️还没生效": _还没生效(),
            "note": "**还没有版本** —— 没有版本的策略绑不上去"}


@router.get(前缀 + "/tool-selection-policies/{pid}")
def 策略详情(project_id: str, pid: str,
         me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        p = c.execute(text("""select * from tool_selection_policies
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": pid}).mappings().first()
        if not p:
            raise _错(404, "NOT_FOUND", f"没有策略 {pid}", "回策略列表看有哪些")
        版本们 = [dict(r) for r in c.execute(text("""
            select version_no, selection_mode, catalog_snapshot_ref,
                   default_group_version_ref, limits, loading_type,
                   empty_result_action, catalog_error_action,
                   independent_router_enabled, candidate_cache_enabled,
                   release_criteria, content_hash, change_note,
                   created_at, created_by
              from tool_selection_policy_versions
             where project_id=:p and tool_selection_policy_id=:i
             order by version_no desc"""),
            {"p": project_id, "i": pid}).mappings()]
    return {
        "id": p["id"], "名称": p.get("name"), "状态": p.get("status"),
        "draft_revision": p.get("draft_revision") or 0,
        "revision": p.get("revision"),
        "草稿": {"用途": p.get("purpose"), "负责人": p.get("owner"),
               "revision": p.get("draft_revision") or 0},
        "版本历史": [{
            "版本": f"v{v['version_no']}", "version_no": v["version_no"],
            "模式": v.get("selection_mode"),
            "模式中文": (模式表.get(v.get("selection_mode")) or ("?",))[0],
            "目录快照": v.get("catalog_snapshot_ref"),
            "默认工具组版本": v.get("default_group_version_ref"),
            "限额": v.get("limits"),
            "加载方式": v.get("loading_type"),
            "没结果怎么办": v.get("empty_result_action"),
            "目录出错怎么办": v.get("catalog_error_action"),
            "开了独立路由吗": v.get("independent_router_enabled"),
            "开了候选缓存吗": v.get("candidate_cache_enabled"),
            "发布门槛": v.get("release_criteria"),
            "内容哈希": v.get("content_hash"),
            "变更说明": v.get("change_note"),
            "冻结时间": v["created_at"].isoformat() if v.get("created_at") else None,
            "冻结的人": v.get("created_by"),
        } for v in 版本们],
        "⚠️还没生效": _还没生效(),
        "note": "**改草稿的 `If-Match` 认 `draft_revision`**",
    }


@router.patch(前缀 + "/tool-selection-policies/{pid}/draft")
async def 改策略草稿(project_id: str, pid: str, request: Request,
               me: 身份 = Depends(要权限("改筛选策略"))):
    体 = await request.json()
    头 = request.headers.get("If-Match")
    if not 头:
        raise _错(409, "IF_MATCH_REQUIRED", "改草稿要带 If-Match",
                 "把策略详情里的 `draft_revision` 放进 If-Match 头")
    with 事务() as c:
        p = c.execute(text("""select * from tool_selection_policies
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": pid}).mappings().first()
        if not p:
            raise _错(404, "NOT_FOUND", f"没有策略 {pid}", "回列表看有哪些")
        现 = p.get("draft_revision") or 0
        if str(现) != str(头).strip('"'):
            raise _错(409, "REVISION_CONFLICT",
                     f"这份草稿已经被改过(现在是 {现},你带的是 {头})",
                     "重新读一遍详情,拿新的 draft_revision 再提交")
        改 = {}
        for 中, 英 in (("名称", "name"), ("用途", "purpose"), ("负责人", "owner")):
            v = 体.get(中) if 体.get(中) is not None else 体.get(英)
            if v is not None:
                改[英] = str(v).strip()
        if not 改:
            raise _错(422, "VALIDATION_FAILED", "没给要改的东西",
                     "能改的是 `名称` / `用途` / `负责人`")
        套 = ", ".join(f"{k}=:{k}" for k in 改)
        c.execute(text(f"""update tool_selection_policies set {套},
            draft_revision=coalesce(draft_revision,0)+1,
            updated_at=now(), revision=coalesce(revision,0)+1
            where project_id=:p and id=:i"""),
                  {**改, "p": project_id, "i": pid})
        _审计(c, me, "selection_policy.draft.update",
              {"policy_id": pid, "字段": sorted(改)})
        新 = c.execute(text("""select draft_revision from tool_selection_policies
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": pid}).scalar()
    return {"id": pid, "draft_revision": 新,
            "note": "草稿改了 —— **已经冻结的版本一个字没动**"}


@router.post(前缀 + "/tool-selection-policies/{pid}/validate")
async def 校验策略草稿(project_id: str, pid: str, request: Request,
                me: 身份 = Depends(要权限("改筛选策略"))):
    """只校验,**不落版本**。错误带 `field_path`(规格 §14.2)。"""
    体 = await request.json()
    with 连接() as c:
        p = c.execute(text("""select 1 from tool_selection_policies
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": pid}).first()
        if not p:
            raise _错(404, "NOT_FOUND", f"没有策略 {pid}", "回列表看有哪些")
        问, 归一 = 校验策略(c, project_id, 体)
    return {
        "过了吗": not 问, "问题": 问, "归一后的配置": 归一,
        # ⚠️ **「校验过了」不等于「冻结会成功」。**
        # 中间可能有人把那个快照归档了 —— 冻结时还会再校一遍。
        "⚠️校验过了不等于冻得进去": ("这一步只在**这一刻**成立 —— "
                          "冻结时还会再校一遍(比如中间有人把那个快照归档了)。"
                          "**不要拿这一步的结果当通行证**"),
        "⚠️还没生效": _还没生效(),
    }


@router.post(前缀 + "/tool-selection-policies/{pid}/versions", status_code=201)
async def 冻结策略版本(project_id: str, pid: str, request: Request,
                me: 身份 = Depends(要权限("改筛选策略"))):
    体 = await request.json()
    说明 = (体.get("变更说明") or 体.get("change_note") or "").strip()
    with 事务() as c:
        p = c.execute(text("""select * from tool_selection_policies
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": pid}).mappings().first()
        if not p:
            raise _错(404, "NOT_FOUND", f"没有策略 {pid}", "回列表看有哪些")
        问, 归一 = 校验策略(c, project_id, 体)
        if 问:
            _审计(c, me, "selection_policy.version.blocked",
                  {"policy_id": pid}, result="blocked",
                  reason="; ".join(问)[:400])
            raise _错(422, "VALIDATION_FAILED", "这份策略冻不进去",
                     "挨个看下面那几条",
                     field_errors={"闸": 问})
        上 = c.execute(text("""select version_no
                            from tool_selection_policy_versions
                            where project_id=:p and tool_selection_policy_id=:i
                            order by version_no desc limit 1"""),
                      {"p": project_id, "i": pid}).scalar()
        号 = (上 or 0) + 1
        import capabilities as CAP
        哈 = CAP.内容哈希(归一)
        vid = _新id("tspv")
        c.execute(text("""insert into tool_selection_policy_versions
            (id, organization_id, project_id, tool_selection_policy_id,
             version_no, selection_mode, catalog_snapshot_ref,
             default_group_version_ref, limits, loading_type,
             empty_result_action, catalog_error_action,
             independent_router_enabled, candidate_cache_enabled,
             release_criteria, content_hash, change_note,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:g,:n,:sm,:cs,:dg, cast(:lm as jsonb),:lt,
                    :ea,:ce,:ir,:cc, cast(:rc as jsonb), :h,:cn,
                    now(), :by, now(), 1)"""),
                  {"i": vid, "o": p["organization_id"], "p": project_id,
                   "g": pid, "n": 号,
                   "sm": 归一["selection_mode"],
                   "cs": 归一["catalog_snapshot_ref"],
                   "dg": 归一["default_group_version_ref"],
                   "lm": _json.dumps(归一["limits"], ensure_ascii=False),
                   "lt": 归一["loading_type"],
                   "ea": 归一["empty_result_action"],
                   "ce": 归一["catalog_error_action"],
                   "ir": 归一["independent_router_enabled"],
                   "cc": 归一["candidate_cache_enabled"],
                   "rc": _json.dumps(归一["release_criteria"],
                                     ensure_ascii=False),
                   "h": 哈, "cn": 说明 or None, "by": me.user_id})
        _审计(c, me, "selection_policy.version.create",
              {"policy_id": pid, "version_no": 号,
               "mode": 归一["selection_mode"]})
    return {"id": vid, "版本": f"v{号}", "version_no": 号,
            "模式": 归一["selection_mode"], "内容哈希": 哈,
            # ⚠️ 规格 §14.2:「冻结策略 | **不改变生产引用**」
            "⚠️冻结不改变生产引用": ("冻结只是把这一版固定下来 —— "
                          "**让它生效要走发布那条链**。"
                          "> 「我能改它」和「我能让它生效」是两件事"),
            "⚠️还没生效": _还没生效()}
