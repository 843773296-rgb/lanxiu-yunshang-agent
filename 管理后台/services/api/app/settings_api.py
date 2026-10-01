#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置组(规格 §15.3 / §15.4):成员与权限 / 预算 / 审计记录。

    GET  /audit-events    审计记录(**前面每一块都在等这一条**)
    GET  /memberships     成员与权限(给的是「他实际能做什么」,不只是角色名)
    POST /memberships     加成员 / 改权限(**落点是 `perms.可以授予吗()`**)
    GET  /budgets         预算
    POST /budgets         设预算

## 为什么这一组是最后一块,却是前面每一块都在依赖的那一块

从 09-28 起我在每个模块都写审计:

    dataset.export / dataset.freeze / deployment.blocked / deployment.create
    release.create / release.review / release.deploy / release.rollback
    training_job.submit / training_job.cancel / model_artifact.register
    model_connection.create / model_connection.probe / application.run …

**而到现在没有任何接口能把它们读出来。**

> **一条写得下却读不出的审计,在出事的那天和没有审计是一回事。**

所以 `GET /audit-events` 不是「补最后一个页面」,是**把前面十几处的留痕接通**。

## ⚠️ 两条这一组特有的判据

**① 不能通过邀请获得自己没有的权限**(§15.3 最后一句)。
落点 `perms.可以授予吗()` —— 它**早就写好了**,而在这之前没有任何接口调用它。

**② 不许把最后一个能管权限的人去掉。**
这条不在规格里,是推出来的:能改角色就能把自己降成 viewer,
而**一个没有任何人能管权限的项目,从接口这一侧永远救不回来**(只能去改库)。
它和别的闸不一样 —— **别的闸拦的是「做错了」,这道拦的是「做完之后没法回头」**。

## ⚠️ 审计是只追加的,所以这里**只有 GET**

没有 `DELETE /audit-events/{id}`,也没有 PATCH。
规格 §15.4:「追加写入,普通编辑不许删」。
一个能删审计的接口,会让审计在最需要它的那一刻正好是空的。
"""
import json as _json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import perms as PM
import settings as ST

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _审计(c, me, action, target, result="ok", reason=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, reason, created_at, created_by)
        values (:i,:o,:p,:a,:ac,cast(:t as jsonb),:e, now(), :r, :rs, now(), :a)
    """), {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id,
           "ac": action, "t": _json.dumps(target, ensure_ascii=False),
           "e": os.environ.get("APP_ENV", "development"), "r": result, "rs": reason})


# ── 审计记录 ────────────────────────────────────────────────────
@router.get(前缀 + "/audit-events")
# ⚠️ **查询参数名一律 ASCII。** 这个仓库为「协议边界上的中文」付过四次代价
# (HTTP 头的幂等键、bash 变量名、Anthropic 工具名、查询参数名),
# 而 `GET /evaluations/compare` 当初正是因为这个把「甲/乙」改成了 `a`/`b`:
# **中文参数名能用,但每个调用方都得记得编码它,而忘了的表现是
# 「接口没返回」/400,不是一条说得清的错。**
# 我这一版第一次写又用了中文名,当场 400 —— 同一族第五次。
# (中文留在**响应**里:响应是给人读的,不过协议边界。)
def 审计记录(project_id: str, me: 身份 = Depends(要权限("查看审计")),
         action: str = Query(None, description="按动作过滤,如 deployment.create"),
         actor: str = Query(None, description="按操作人过滤"),
         result: str = Query(None, description="ok / blocked / 失败 …"),
         days: int = Query(30, ge=1, le=365),
         limit: int = Query(200, ge=1, le=1000)):
    """审计记录。**只有 GET** —— 没有删、没有改(§15.4:追加写入,普通编辑不许删)。

    ⚠️ **空结果要说清是「本来就没有」还是「被筛掉了」。**
    两者下一步完全不同:一个是去看为什么没人做过这件事,
    一个是去改筛选条件。而它们在一张空表上长得一模一样。
    """
    with 连接() as c:
        行 = [dict(r) for r in c.execute(text("""
            select id, actor, action, target_ref, environment, at, result, reason,
                   request_id
              from audit_events
             where project_id=:p
               and at >= now() - (:d || ' days')::interval
               and (cast(:ac as text) is null or action = cast(:ac as text))
               and (cast(:who as text) is null or actor = cast(:who as text))
               and (cast(:rs as text) is null or result = cast(:rs as text))
             order by at desc, id desc
             limit :lim"""),
            {"p": project_id, "d": days, "ac": action, "who": actor, "rs": result,
             "lim": limit}).mappings()]
        # 「这个范围里一共有多少种动作」—— 筛空的时候,这个数回答
        # 「是不是我筛错了」。不给它的话,人只能一个个猜动作名。
        全部动作 = [dict(r) for r in c.execute(text("""
            select action, count(*) n from audit_events
             where project_id=:p and at >= now() - (:d || ' days')::interval
             group by action order by n desc"""),
            {"p": project_id, "d": days}).mappings()]
    筛了 = any(x is not None for x in (action, actor, result))
    note = ("**只追加,所以这一组只有 GET** —— 没有删也没有改(§15.4)。"
            "一个能删审计的接口,会让审计在最需要它的那一刻正好是空的")
    if not 行:
        note = (("这个范围里**一条都没有**,而**筛选条件是空的** —— "
                 "那就是真的没人做过这些事(不是被筛掉了)。"
                 if not 筛了 else
                 f"**筛出来是空的,但这个范围里有 {sum(x['n'] for x in 全部动作)} 条** —— "
                 f"很可能是筛选条件不对。这个范围里有这些动作:"
                 f"{[x['action'] for x in 全部动作][:12]}")
                + " ⚠️ 「本来就没有」和「被筛掉了」下一步完全不同,所以这里分开说")
    return {"条数": len(行), "时间范围": f"最近 {days} 天",
            "筛了吗": 筛了,
            "这个范围里的动作分布": [{"动作": x["action"], "次数": x["n"]}
                            for x in 全部动作],
            "记录": [{"id": r["id"], "谁": r["actor"], "做了什么": r["action"],
                    "对象": r["target_ref"], "环境": r["environment"],
                    "什么时候": r["at"], "结果": r["result"], "为什么": r["reason"]}
                   for r in 行],
            "note": note}


# ── 成员与权限 ──────────────────────────────────────────────────
@router.get(前缀 + "/memberships")
def 成员列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """成员与权限。

    ⚠️ **给的是「他实际能做什么」,不只是角色名。**
    光看角色名答不出「他能不能批准」——「可授权」那一档**默认是关闭的**,
    而角色名上看不出关没关。
    """
    with 连接() as c:
        行 = [dict(r) for r in c.execute(text("""
            select id, user_id, role, special_grants, status, created_at
              from memberships where project_id=:p
             order by user_id"""), {"p": project_id}).mappings()]
    出 = []
    for m in 行:
        专 = m["special_grants"] or []
        if isinstance(专, str):
            try: 专 = _json.loads(专)
            except Exception: 专 = []
        能 = sorted(k for k in PM.能力们 if PM.判(k, m["role"], 专)[0])
        出.append({
            "工号": m["user_id"], "角色": m["role"],
            "角色中文": PM.角色中文.get(m["role"], "?"),
            "状态": m["status"],
            "专项授权": 专 or None,
            "实际能做的": 能,
            # ⚠️ **「有这个角色」不等于「这条能生效」** —— 状态不是 active 的成员
            # 在 `deps.取身份()` 那一步就查不到,而他在这张表里看着完全正常。
            "这条生效吗": m["status"] == "active",
        })
    能管的 = ST.谁能管权限([{"user_id": x["工号"], "role": x["角色"],
                       "special_grants": x["专项授权"] or []}
                      for x in 出 if x["这条生效吗"]])
    # ── 改权限的表单要填什么,**由接口给** ──────────────────────────────
    # ⚠️ 这一族今天第五处(模型连接的用途 / 样本的复核状态 / 工具的读写类型 /
    # 产物的部署环境)。前端硬编一份的代价不是难看,是**它和权限矩阵会漂** ——
    # 漂的表现是界面上少一个能选的角色、或者多一个会被 422 拒的,**都不报错**。
    #
    # ⚠️ **「可授权」那一档要单独给。** 专项授权只能给矩阵里标着
    # `grantable` 的那几条能力 —— 而「这个角色默认有」和「这个角色可以被授权」
    # 在角色名上**完全看不出来**。不给这一栏的话,界面只能把 12 条能力全列出来,
    # 而其中大部分填了会被闸拒。
    # ⚠️ **按角色给,不能拉平成一张清单。** 2026-10-01 第一版就是拉平的,
    # 页面接线测试当场证明那是错的:给一个 `viewer` 加 `审批工具动作`,
    # 接口**收下了(201,`专项授权` 里存着它)**,而 `实际能做的` 里没有 ——
    # 因为那条能力对 viewer 是 `deny`,只对 admin 是 `grantable`。
    # 于是界面会给 viewer 摆一个**勾了没用的框**。
    # > **一个存下来却不生效的授权,比没存更坏** ——
    # > 界面上它看着是给了的。
    # (`viewer` 一条可授权的都没有:拉平的清单会给它列出 8 条。)
    可授权的 = {r: sorted(能力 for 能力, 行 in PM.矩阵.items()
                      if 行.get(r) == PM.可授权)
             for r in PM.角色们}
    return {"条数": len(出), "成员": 出,
            "能改权限的": 能管的,
            "可选角色": [{"值": r, "中文": PM.角色中文.get(r, r)}
                     for r in PM.角色们],
            # 形状:{角色: [这个角色能被授权的那几条]}。
            # 有的角色是**空的**(viewer 就是)—— 那本身是个答案,
            # 而把它和「还没查」画成同一个(都给空数组)是另一回事:
            # 这里每个角色都有一项,所以「空」只能读成「这个角色一条都不能授权」。
            "可授权的能力": 可授权的,
            "⚠️可授权是默认关的": ("`可授权` 那一档**默认是关闭的** —— "
                           "一个角色「可以被授权某条能力」和「默认就有它」"
                           "是两件事,而**角色名上完全看不出来**。"
                           "`可授权的能力` 是**按角色**给的:"
                           "给一个角色加它不能被授权的能力,"
                           "**存得下但不生效** —— 而那比没存更坏。"
                           "所以 `实际能做的` 一律按角色 + 专项授权**现算**"),
            "note": ("`实际能做的` 是按角色 + 专项授权**现算**的,不是存的字段 —— "
                     "存的会漂。⚠️ `这条生效吗=false` 的成员在登录那一步就查不到,"
                     "而他在这张表里看着完全正常"
                     + (f" · ⚠️ **只剩 {len(能管的)} 个人能改权限**"
                        if len(能管的) <= 1 else ""))}


@router.post(前缀 + "/memberships", status_code=201)
async def 加成员或改权限(project_id: str, request: Request,
                 me: 身份 = Depends(要权限("配置密钥与预算"))):
    """加成员 / 改权限。入参 `{工号, 角色, 专项授权?}`。

    ⚠️ **两道闸**:
      ① 不能授予自己没有的权限(§15.3,落点 `perms.可以授予吗()`)
      ② 不许把最后一个能管权限的人去掉(**做完没法回头**的那一类)
    """
    体 = await request.json()
    工号 = (体.get("工号") or 体.get("user_id") or "").strip()
    角色 = (体.get("角色") or 体.get("role") or "").strip()
    专项 = 体.get("专项授权") if "专项授权" in 体 else 体.get("special_grants")
    专项 = list(专项 or [])
    if not 工号:
        raise _错(422, "VALIDATION", "工号必填", "给一个工号",
                  field_errors={"工号": "必填"})
    with 事务() as c:
        现有 = [dict(r) for r in c.execute(text("""
            select user_id, role, special_grants, status from memberships
             where project_id=:p and status='active'"""),
            {"p": project_id}).mappings()]
        for m in 现有:
            if isinstance(m["special_grants"], str):
                try: m["special_grants"] = _json.loads(m["special_grants"])
                except Exception: m["special_grants"] = []
        问 = ST.可以改成员吗(我角色=me.role, 我专项=me.grants, 目标工号=工号,
                       要给的角色=角色, 要给的专项=专项, 现有成员们=现有)
        if 问:
            _审计(c, me, "membership.blocked", {"user_id": 工号, "role": 角色},
                  result="blocked", reason="; ".join(问)[:400])
            拦了 = 问
        else:
            拦了 = None
            org = c.execute(text("select organization_id from projects where id=:p"),
                            {"p": project_id}).scalar()
            老 = c.execute(text("""select id, role from memberships
                                 where project_id=:p and user_id=:u"""),
                           {"p": project_id, "u": 工号}).mappings().first()
            if 老:
                c.execute(text("""update memberships
                                     set role=:r, special_grants=cast(:g as jsonb),
                                         status='active', revision=revision+1,
                                         updated_at=now()
                                   where project_id=:p and id=:i"""),
                          {"r": 角色, "g": _json.dumps(专项, ensure_ascii=False),
                           "p": project_id, "i": 老["id"]})
                动作, 从 = "membership.update", 老["role"]
            else:
                # ⚠️ **`status='active'` 不能省。** `deps.取身份()` 的查询带着
                # `m.status = 'active'`,不给的话这一行**在表里看着好好的,
                # 每条读路径都捞不到** —— 报出来的是另一个地方的 404。
                # (09-29 铺 trainer 的时候栽过一次,那次是「INSERT 成功 ≠ 这一行有用」。)
                c.execute(text("""insert into memberships
                    (id, user_id, organization_id, project_id, role, status,
                     special_grants, created_at, created_by, updated_at, revision)
                    values (:i,:u,:o,:p,:r,'active', cast(:g as jsonb),
                            now(), :by, now(), 1)"""),
                          {"i": _新id("mem"), "u": 工号, "o": org, "p": project_id,
                           "r": 角色, "g": _json.dumps(专项, ensure_ascii=False),
                           "by": me.user_id})
                动作, 从 = "membership.create", None
            _审计(c, me, 动作,
                  {"user_id": 工号, "role": 角色, "从": 从, "专项授权": 专项})
    if 拦了:
        raise _错(422, "CANNOT_GRANT", "这套权限给不了",
                  "按下面每一条处理。**被拦这件事已经记进审计**",
                  field_errors={"闸": 拦了})
    能 = sorted(k for k in PM.能力们 if PM.判(k, 角色, 专项)[0])
    return {"工号": 工号, "角色": 角色, "专项授权": 专项 or None,
            "实际能做的": 能,
            "note": ("**`status` 设成了 active** —— 不设的话这一行在表里看着好好的,"
                     "而登录那一步查不到它(那条查询带着 `status='active'`)。"
                     "⚠️ `实际能做的` 里没有的能力,不是「忘了给」——"
                     "「可授权」那一档**默认关闭**,要单独写进专项授权")}


# ── 预算 ────────────────────────────────────────────────────────
@router.get(前缀 + "/budgets")
def 预算列表(project_id: str, me: 身份 = Depends(要权限("配置密钥与预算"))):
    with 连接() as c:
        行 = [dict(r) for r in c.execute(text("""
            select id, scope, period, limit_amount, reserved_amount, currency,
                   revision, created_at
              from budgets where project_id=:p and archived_at is null
             order by created_at"""), {"p": project_id}).mappings()]
    return {"条数": len(行),
            "预算": [{"id": r["id"], "范围": r["scope"], "周期": r["period"],
                    "币种": r["currency"], **ST.还能花多少(r)} for r in 行],
            "note": ("**没有某个范围的那一行 = 没设上限**,不是「上限 0」—— "
                     "`0` 的意思是一分都不许花。两者混成一个数的后果很具体:"
                     "有人把预算清成 0 想临时停掉,而系统当成「不限」,"
                     "然后账单继续涨、界面上显示预算是 0")}


@router.post(前缀 + "/budgets", status_code=201)
async def 设预算(project_id: str, request: Request,
           me: 身份 = Depends(要权限("配置密钥与预算"))):
    """设预算。入参 `{范围, 周期, 上限, 币种}`。

    ⚠️ **上限必填,而且「不限」用「不建这一行」表达**,不用 0 表达。
    """
    体 = await request.json()
    范围 = (体.get("范围") or 体.get("scope") or "").strip()
    周期 = (体.get("周期") or 体.get("period") or "").strip()
    上限 = 体.get("上限") if "上限" in 体 else 体.get("limit_amount")
    币种 = (体.get("币种") or 体.get("currency") or "").strip()
    问 = ST.可以设预算吗(范围=范围, 周期=周期, 上限=上限, 币种=币种)
    if 问:
        raise _错(422, "VALIDATION", "这个预算设不了",
                  "按下面每一条改", field_errors={"闸": 问})
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        老 = c.execute(text("""select id from budgets
                             where project_id=:p and scope=:s and period=:pd
                               and archived_at is null"""),
                       {"p": project_id, "s": 范围, "pd": 周期}).scalar()
        if 老:
            c.execute(text("""update budgets set limit_amount=:l, currency=:cur,
                                 revision=revision+1, updated_at=now()
                               where project_id=:p and id=:i"""),
                      {"l": 上限, "cur": 币种, "p": project_id, "i": 老})
            bid, 新建 = 老, False
        else:
            bid, 新建 = _新id("bdg"), True
            c.execute(text("""insert into budgets
                (id, organization_id, project_id, scope, period, limit_amount,
                 reserved_amount, currency, created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:s,:pd,:l, 0, :cur, now(), :by, now(), 1)"""),
                      {"i": bid, "o": org, "p": project_id, "s": 范围, "pd": 周期,
                       "l": 上限, "cur": 币种, "by": me.user_id})
        _审计(c, me, "budget.set",
              {"budget_id": bid, "scope": 范围, "period": 周期,
               "limit_amount": 上限, "currency": 币种})
        行 = c.execute(text("select * from budgets where project_id=:p and id=:i"),
                       {"p": project_id, "i": bid}).mappings().first()
        行 = dict(行) if 行 else None
    return {"id": bid, "新建了吗": 新建, "范围": 范围, "周期": 周期, "币种": 币种,
            **ST.还能花多少(行)}
