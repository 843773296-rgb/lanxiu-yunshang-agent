#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具与能力(规格 §11、§16.3):工具草稿/版本、工具连接、Skill 指南、规则策略。

    PATCH /tools/{id}/draft          改工具草稿(乐观锁)
    POST  /tools/{id}/versions       冻结工具版本(**风险变大必须出新版本**)
    GET   /capability-connections    工具连接列表(**密钥不回显**)
    POST  /capability-connections    建工具连接
    GET   /skills                    Skill 指南列表
    POST  /skills                    建 Skill 指南(**只收 Markdown 和只读参考**)
    POST  /skills/{name}/versions    冻结指南版本
    GET   /policies                  规则策略列表
    POST  /policies                  建规则策略(**白名单模板 + 参数,不开放任意代码**)

## 这一组的四句话

**① 风险变大必须出新版本**(§16.3)。原话值得一字不改地抄:
> 一个工具从只读变成会写东西,而引用它的 Agent 还指着老的说明 ——
> **那份说明现在是错的**。

**② 密钥只收引用、不回显**(§11.2)。和 `connections_api` 同一条:
列表只给形状,**不做截断** —— 截到前几个字符,那几个字符仍然是原文。

**③ 指南不授予权限**(§11.3)。「启用了指南」被读成「给了脚本权限」
是这一块最容易出的误解。所以这条链上**根本没有写权限的字段** ——
不是靠判据拦住,是没地方写。

**④ 白名单,不是黑名单。** 指南的文件、规则的模板都是白名单。
黑名单在这里必输:「哪些后缀算可执行」是个**无限集合**,
而这个仓库为「枚举必输」栽过七次。

## ⚠️ 「Skill」和「工具」为什么用不同的身份

工具有 `tool_definitions` 作父、`tool_versions` 作版本。
而 Skill 和规则**只有版本表**(`skill_versions` / `policy_versions`)——
契约里登记的就是这两张。所以这里拿 **`name` 当身份**:
一份指南 = 同名的一串版本。

⚠️ 这不是将就:指南的身份本来就是**它叫什么**(模型按名字请求加载),
而不是某个库里的 id。用 id 当身份反而要多维护一张表。
"""
import json as _json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import capabilities as CAP
# ⚠️ `dsl` 在 `contract/` 下,靠 sys.path 找到 —— 和 `agents_api.py` 同一条。
# 补这一行是因为我从那边抄了 `DS.副作用表` 而没抄导入:
# **抄一行用法不抄它的前提,表现是一个 NameError,而它只在走到那条路径时才炸。**
import dsl as DS
import connections as CN          # 复用 `_定位符` 那套密钥引用判据

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


def _引用形状(secret_ref):
    """**只给形状,不给内容**,而且不做截断。和 `connections_api` 同一条。"""
    s = (secret_ref or "").strip()
    if not s:
        return {"配了吗": False}
    协议 = s.split("://", 1)[0] if "://" in s else (s.split(":", 1)[0] if ":" in s else "?")
    return {"配了吗": True, "存在哪": 协议, "长度": len(s)}


# ── 工具草稿与版本 ──────────────────────────────────────────────
# ⚠️ **这份清单只能有一份** —— 从网关那边取,不在这里抄。
# 抄一份的话它迟早和校验器真支持的那份漂开,而漂开的表现是:
# 界面放过去了、冻结接受了,**调用那一刻才拒绝**。
from runtime.tool_gateway import _支持的关键字 as _网关支持的关键字


@router.get(前缀 + "/tools/{tid}")
def 工具详情(project_id: str, tid: str,
         me: 身份 = Depends(要权限("查看有权配置"))):
    """一个工具:草稿(**带 `draft_revision`**)+ 已冻结的版本历史。

    ⚠️ **这条接口是 2026-09-29 补的,补的是一个洞而不是一个需求。**
    `PATCH /tools/{id}/draft` 的错误提示写着
    「把**工具详情**里的 `draft_revision` 放进 If-Match 头再提交」——
    而**「工具详情」这个接口当时不存在**,`GET /tools` 也不给 revision。

    > 一句指着不存在的页面的错误提示,比不给提示更糟:
    > 它让人去做一件做不到的事,而那句话本身读起来完全合理。

    于是「改工具草稿」在界面上**做不起来** —— 不是前端没写,
    是它拿不到必须带的那个值。同一天同一个洞在发布链和运行控制上各有一处,
    所以补了判据 `tools/ifmatch_reachable_check.py` 盯这一整类。

    ⚠️ 顺带把 **`风险变大了吗`** 也算在这儿,和改草稿那条一致 ——
    让界面自己去比两个副作用等级的话,那条规矩就变成每个前端各实现一遍,
    而**它们会在某一天不一致,且不一致的表现是界面上少一句警告**。
    """
    with 连接() as c:
        d = c.execute(text("""select * from tool_definitions
                             where project_id=:p and id=:i and archived_at is null"""),
                      {"p": project_id, "i": tid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", f"没有工具 {tid}", "回工具目录重新进入")
        d = dict(d)
        # ⚠️ **列名查过再写。** 第一版我写的是 `contract_hash` 和
        # `requires_confirmation` —— 两个都不存在(真实列是 `content_hash`
        # 和 `confirmation_policy`),于是这条接口 **500**。
        # 「没查表结构就写」这一族今天第 10 次;而它只在走到这条路径时才炸,
        # 别的路径全绿。
        # ⚠️⚠️ **逐列点名,绝不 `select *`。**
        # `tool_versions` 上有 **`secret_ref`** —— 凭据引用。
        # > **凭据绝不写进任何返回值或异常。**
        # `select *` 会在「有人往这张表加一列」的那天把它带出去,
        # 而那天**没有任何东西会红**。逐列点名让「多返回一列」
        # 变成一个要有人写下来的动作。
        #
        # 下面这批是 2026-10-02 为规格 §8.2 的「输入与输出」和
        # 「执行与权限」两个页签加的 —— 原来只给 7 列,
        # 而那两页要的「参数表 / 对象范围 / 幂等 / 超时 / 脱敏」一个都没有。
        版本们 = [dict(r) for r in c.execute(text("""
            select version_no, side_effect_type, content_hash, confirmation_policy,
                   pollable, created_at, created_by,
                   model_description, input_schema, output_schema,
                   allowed_scopes, idempotency_strategy, timeout_seconds,
                   redaction, server_bound_arguments, external_status_lookup,
                   connection_id, retry_policy,
                   -- ⚠️ **只报「配了没配」,不给值。** 见上面那段红线。
                   (secret_ref is not null) as 配了凭据吗
              from tool_versions
             where project_id=:p and tool_definition_id=:i
             order by version_no desc"""), {"p": project_id, "i": tid}).mappings()]
    级中文 = {x["名"]: x["中文"] for x in DS.副作用表}
    上一版 = 版本们[0] if 版本们 else None
    风险变大 = bool(上一版) and CAP.风险变大了吗(
        上一版["side_effect_type"], d.get("side_effect_type"))
    return {
        "id": d["id"], "名称": d.get("name"), "状态": d.get("status"),
        # ⚠️ **`draft_revision` 是改草稿的 If-Match,`revision` 不是。**
        # 两个数都在这一行上,是为了让拿错的人一眼看见还有另一个 ——
        # 只给一个的话,界面会把手边那个塞进 If-Match,换来一个
        # 409「这份草稿已经被改过」,而它读起来像「别人改过了」。
        "draft_revision": d.get("draft_revision") or 0,
        "revision": d.get("revision"),
        "草稿": {
            "用途": d.get("purpose"), "读写类型": d.get("side_effect_type"),
            "读写类型中文": 级中文.get(d.get("side_effect_type"),
                                d.get("side_effect_type")),
            "接入方式": d.get("adapter"), "负责人": d.get("owner"),
            # ⚠️ `tool_definitions` 上**没有**「要确认吗」和凭据这两样 ——
            # 它们在**版本**上(`confirmation_policy` / `secret_ref`)。
            # 我照着模型连接那张表想当然写了,500 才发现。
            # 这件事本身有意义:**确认策略和凭据是跟着冻结版本走的**,
            # 而不是跟着草稿走 —— 改草稿改不动一个已经冻结的版本要不要确认。
            "revision": d.get("draft_revision") or 0,
        },
        "版本历史": [{
            "版本": f"v{v['version_no']}", "version_no": v["version_no"],
            "读写类型": 级中文.get(v["side_effect_type"], v["side_effect_type"]),
            "内容哈希": v.get("content_hash"),
            "确认策略": v.get("confirmation_policy"),
            "能轮询吗": v.get("pollable"),
            "冻结时间": v["created_at"].isoformat() if v.get("created_at") else None,
            "冻结的人": v.get("created_by"),
            # ── 规格 §8.2「输入与输出」那一页要的 ──────────────────
            "给模型的说明": v.get("model_description"),
            "入参": v.get("input_schema"),
            "出参": v.get("output_schema"),
            # ⚠️ **服务端绑定参数单独一栏**(规格 §8.2:「服务端绑定另区展示」)。
            # 它和「模型能填的参数」混在一张表里是危险的:
            # 模型看不到也改不了这些,而界面上并排摆着会让人以为它们一样 ——
            # 于是有人把一个该服务端绑的字段写进 `input_schema`,
            # **那一刻模型就能覆盖它了**。
            "服务端绑定的参数": v.get("server_bound_arguments"),
            # ── 规格 §8.2「执行与权限」那一页要的 ────────────────
            "对象范围": v.get("allowed_scopes"),
            "幂等策略": v.get("idempotency_strategy"),
            "超时秒": v.get("timeout_seconds"),
            "脱敏": v.get("redaction"),
            "查外部状态": v.get("external_status_lookup"),
            "连接": v.get("connection_id"),
            "重试策略": v.get("retry_policy"),
            # ⚠️ **只说配了没配,不给凭据引用本身。**
            # 规格 §11.2 / 这个仓库的红线:**凭据绝不经返回值出去**。
            "配了凭据吗": bool(v.get("配了凭据吗")),
        } for v in 版本们],
        "⚠️凭据不出返回值": "版本上有 `secret_ref`,这条接口**只报配了没配** —— "
                        "凭据(以及它的引用)不经任何返回值出去。"
                        "查询也是逐列点名的:`select *` 会在有人加一列的那天"
                        "把它带出去,**而那天没有任何东西会红**",
        "风险变大了吗": 风险变大,
        # ⚠️ **把校验器真支持的关键字给出来,让界面不硬编**(2026-10-02 加)。
        #
        # 第三份规格 §8.3 最后一句:「首版不能默认任意 JSON Schema 都被支持;
        # **界面必须用真实能力清单校验,不能静默忽略约束**」。
        #
        # 为什么从接口给、不让前端写死一份:前端硬编的那份**会和后端漂** ——
        # 这个仓库在同一个形状上栽过(部署环境硬编在页面里、冒烟名单抄了第二份)。
        # 而漂开的表现很隐蔽:界面说「这个关键字不行」而后端其实支持了,
        # 或者反过来 —— 界面放它过去,**到模型第一次真的调用那一刻才失败**。
        "可用的Schema关键字": sorted(_网关支持的关键字),
        "⚠️Schema别硬编": "这份清单是**校验器真支持的那些**,从接口取,"
                        "别在前端写死 —— 写死的那份会和后端漂,"
                        "而漂开时界面放过去的 Schema 会在**模型第一次真的调用**"
                        "那一刻才失败,报出来是「工具调用失败」",
        "note": ("**改草稿的 `If-Match` 认 `draft_revision`**,不是 `revision` —— "
                 "两个数都在这儿,是为了让拿错的人一眼看见还有另一个。"
                 + ("　⚠️ **草稿比最新冻结版风险更大** —— 冻结时必须出新版本:"
                    "引用它的 Agent 还指着老说明,而那份说明现在是错的"
                    if 风险变大 else "")),
    }


@router.patch(前缀 + "/tools/{tid}/draft")
async def 改工具草稿(project_id: str, tid: str, request: Request,
               if_match: str = Header(default=None, alias="If-Match"),
               me: 身份 = Depends(要权限("改编排草稿"))):
    """改工具草稿。**要 If-Match**(`draft_revision`)。

    ⚠️ 草稿里**改副作用类型是允许的** —— 拦在冻结那一步,不拦在这里。
    在草稿上拦住的话,人连「我想把它改成会写」都表达不出来,
    而那正是需要走版本的那种改动。
    """
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match",
                  "把工具详情里的 `draft_revision` 放进 If-Match 头再提交")
    体 = await request.json()
    # ⚠️ **中文键和英文键都收 —— 2026-10-01 补的,补的是一处分叉。**
    #
    # `POST /tools`(建工具)收的是**中文**键(名称 / 读写类型 / 接入方式),
    # 而这条改草稿原来**只收英文列名** —— 同一组接口里一半中文一半英文,
    # 而**没有任何东西拦着这种分叉**(这条当天就记在交接的「已知未修」里)。
    #
    # 代价不是难看:界面得**记住哪条用哪套**,而记错的表现是
    # 422「没有要改的字段 · 不认识的键:['用途']」——
    # 那句话读起来像「这个字段不能改」,而真相是「这条接口要英文名」。
    # 2026-10-01 页面接线测试第一次跑就撞到这儿。
    #
    # 为什么**不是**改成只收中文:英文列名是现有调用方(端到端测试、
    # 可能的脚本)在用的,单方面换掉会把它们一起弄坏 ——
    # **收两种是兼容,收一种是迁移**,而迁移要先知道谁在调。
    中文别名 = {"名称": "name", "用途": "purpose",
              "读写类型": "side_effect_type", "接入方式": "adapter",
              "负责人": "owner"}
    可改 = {"name", "purpose", "side_effect_type", "adapter", "owner"}
    改 = {}
    for k, v in 体.items():
        键 = 中文别名.get(k, k)
        if 键 in 可改:
            改[键] = v
    野 = sorted(k for k in 体 if 中文别名.get(k, k) not in 可改)
    if not 改:
        raise _错(422, "VALIDATION", "没有要改的字段",
                  f"可改的是 {sorted(可改)}(中文名也收:"
                  f"{sorted(中文别名)})",
                  field_errors={"不认识的键": 野} if 野 else None)
    with 事务() as c:
        d = c.execute(text("""select * from tool_definitions
                             where project_id=:p and id=:i for update"""),
                      {"p": project_id, "i": tid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", f"没有工具 {tid}", "回工具目录重新进入")
        d = dict(d)
        老rev = d.get("draft_revision") or 0
        if str(老rev) != str(if_match):
            raise _错(409, "REVISION_CONFLICT",
                      f"这份草稿已经被改过(你拿的是 {if_match},现在是 {老rev})",
                      "刷新看一眼别人改了什么再合并;**不要直接覆盖**")
        套 = ", ".join(f"{k}=:{k}" for k in 改)
        c.execute(text(f"""update tool_definitions set {套},
                              draft_revision=:_r, revision=revision+1, updated_at=now()
                            where project_id=:_p and id=:_i"""),
                  {**改, "_r": 老rev + 1, "_p": project_id, "_i": tid})
        上一版 = c.execute(text("""select side_effect_type, version_no
                                from tool_versions
                               where project_id=:p and tool_definition_id=:i
                               order by version_no desc limit 1"""),
                        {"p": project_id, "i": tid}).mappings().first()
    新副作用 = 改.get("side_effect_type", d.get("side_effect_type"))
    风险变大 = bool(上一版) and CAP.风险变大了吗(上一版["side_effect_type"], 新副作用)
    return {"id": tid, "draft_revision": 老rev + 1, "改了": sorted(改),
            "不认识的键": 野 or None,
            "风险变大了吗": 风险变大,
            "note": (("⚠️ **风险变大了** —— 冻结时**必须出新版本**:"
                      "引用它的 Agent 还指着老说明,而那份说明现在是错的"
                      if 风险变大 else
                      "改草稿不影响已经冻结的版本 —— 引用旧版本的 Agent 照旧"))}


@router.post(前缀 + "/tools/{tid}/versions", status_code=201)
async def 冻结工具版本(project_id: str, tid: str, request: Request,
                me: 身份 = Depends(要权限("改编排草稿"))):
    """把工具草稿冻成一个版本。

    ⚠️ **接口不收任意执行代码**(§17.1)—— 这里登记的是
    「它是什么、怎么调、风险多大」,行为由适配器实现。
    """
    体 = await request.json()
    with 事务() as c:
        d = c.execute(text("""select * from tool_definitions
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": tid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", f"没有工具 {tid}", "回工具目录重新进入")
        d = dict(d)
        上一版 = c.execute(text("""select * from tool_versions
                                where project_id=:p and tool_definition_id=:i
                                order by version_no desc limit 1"""),
                        {"p": project_id, "i": tid}).mappings().first()
        上一版 = dict(上一版) if 上一版 else None
        草稿 = {
            "model_description": (体.get("给模型的说明")
                                  or 体.get("model_description") or "").strip(),
            "input_schema": 体.get("入参") or 体.get("input_schema"),
            "output_schema": 体.get("出参") or 体.get("output_schema"),
            "side_effect_type": d.get("side_effect_type"),
            "idempotency_strategy": (体.get("幂等策略")
                                     or 体.get("idempotency_strategy") or "").strip(),
            "allowed_scopes": 体.get("允许的范围") or 体.get("allowed_scopes"),
            "confirmation_policy": 体.get("确认策略") or 体.get("confirmation_policy"),
            "timeout_seconds": 体.get("超时秒") or 体.get("timeout_seconds"),
            "secret_ref": (体.get("secret_ref") or "").strip() or None,
        }
        问 = CAP.可以冻结工具吗(定义=d, 草稿=草稿, 上一版=上一版)
        if 草稿["secret_ref"]:
            坏 = CN.检查密钥引用(草稿["secret_ref"])
            if 坏:
                问.append(坏)
        if 问:
            _审计(c, me, "tool.version.blocked", {"tool_id": tid},
                  result="blocked", reason="; ".join(问)[:400])
            拦了 = 问
        else:
            拦了 = None
            风险变大 = bool(上一版) and CAP.风险变大了吗(
                上一版.get("side_effect_type"), 草稿["side_effect_type"])
            新号 = (上一版["version_no"] + 1) if 上一版 else 1
            哈 = CAP.内容哈希({k: 草稿[k] for k in sorted(草稿)})
            vid = _新id("tv")
            c.execute(text("""insert into tool_versions
                (id, organization_id, project_id, tool_definition_id, version_no,
                 model_description, input_schema, output_schema, side_effect_type,
                 allowed_scopes, confirmation_policy, idempotency_strategy,
                 timeout_seconds, secret_ref, content_hash,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:t,:n,:md, cast(:isc as jsonb), cast(:osc as jsonb),
                        :se, cast(:sc as jsonb), cast(:cp as jsonb),
                        cast(:idem as jsonb), :to, :sr,
                        :h, now(), :by, now(), 1)"""),
                      {"i": vid, "o": d["organization_id"], "p": project_id, "t": tid,
                       "n": 新号, "md": 草稿["model_description"],
                       "isc": _json.dumps(草稿["input_schema"], ensure_ascii=False),
                       "osc": _json.dumps(草稿["output_schema"], ensure_ascii=False),
                       "se": 草稿["side_effect_type"],
                       "sc": _json.dumps(草稿["allowed_scopes"], ensure_ascii=False),
                       "cp": _json.dumps(草稿["confirmation_policy"], ensure_ascii=False),
                       # ⚠️ `idempotency_strategy` 是 **JSONB**,不是 TEXT ——
                       # 塞裸串当场 `invalid input syntax for type json`。
                       # **今天第七次「JSONB 塞裸串」**。
                       # 收字符串是为了好用,存的时候包成对象。
                       "idem": (_json.dumps({"说明": 草稿["idempotency_strategy"]},
                                            ensure_ascii=False)
                                if 草稿["idempotency_strategy"] else None),
                       "to": 草稿["timeout_seconds"], "sr": 草稿["secret_ref"],
                       "h": 哈, "by": me.user_id})
            _审计(c, me, "tool.version.create",
                  {"tool_id": tid, "tool_version_id": vid, "version_no": 新号,
                   "side_effect_type": 草稿["side_effect_type"],
                   "风险变大": 风险变大})
    if 拦了:
        raise _错(422, "CANNOT_FREEZE_TOOL", "这个工具还不能冻版本",
                  "按下面每一条补齐。**被拦这件事已经记进审计**",
                  field_errors={"闸": 拦了})
    return {"id": vid, "version_no": 新号, "内容哈希": 哈,
            "副作用": CAP.风险中文.get(草稿["side_effect_type"]),
            "风险比上一版大吗": 风险变大,
            "note": (("⚠️ **风险比上一版大** —— 这正是必须出新版本的理由:"
                      "引用老版本的 Agent 拿到的说明,现在是错的。"
                      "去把它们指到这一版上。"
                      if 风险变大 else
                      "**写下就不许改** —— 之后改草稿不会动到这一版"))}


# ── 工具连接 ────────────────────────────────────────────────────
@router.get(前缀 + "/capability-connections")
def 工具连接列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """**密钥不返回、不在前端回显**(§11.2)—— 只给形状。"""
    with 连接() as c:
        行 = [dict(r) for r in c.execute(text("""
            select id, name, adapter, allowed_endpoints, secret_ref,
                   capability_snapshot, status, owner, last_health_at, health_detail,
                   revision
              from capability_connections
             where project_id=:p and archived_at is null
             order by created_at"""), {"p": project_id}).mappings()]
    return {"条数": len(行),
            "连接": [{"id": r["id"], "名字": r["name"], "适配器": r["adapter"],
                    "允许的端点": r["allowed_endpoints"],
                    "密钥": _引用形状(r["secret_ref"]),
                    "发现到的能力": r["capability_snapshot"],
                    "状态": r["status"], "负责人": r["owner"],
                    "上次健康检查": r["last_health_at"], "revision": r["revision"]}
                   for r in 行],
            "note": ("⚠️ **连接发现的新工具不自动增加生产 Agent 的权限**(§11.2)—— "
                     "MCP 发现回来的说明和返回值仍然是**外部输入**,要先审。"
                     "⚠️ **停用即时生效**:正在跑的 Run 也要被拦 —— "
                     "「停用」如果只对新 Run 生效,那它不叫停用")}


@router.post(前缀 + "/capability-connections", status_code=201)
async def 建工具连接(project_id: str, request: Request,
              me: 身份 = Depends(要权限("配置密钥与预算"))):
    """建一条工具连接。**密钥只收引用。**"""
    体 = await request.json()
    名字 = (体.get("名字") or 体.get("name") or "").strip()
    适配器 = (体.get("适配器") or 体.get("adapter") or "").strip()
    端点 = 体.get("允许的端点") or 体.get("allowed_endpoints") or []
    引用 = (体.get("secret_ref") or "").strip()
    问 = []
    明文 = CN.像明文密钥吗(体)
    if 明文:
        问.append(f"请求体里有**名字像凭据、而且给了值**的字段:{明文} —— "
                  f"这里**只收引用**")
    if not 名字: 问.append("名字必填")
    if not 适配器: 问.append("适配器必填")
    if not isinstance(端点, list) or not 端点:
        问.append("**允许的端点必填,而且是一张白名单** —— "
                  "不给的话这条连接能打到哪儿是不确定的,"
                  "而「它到底访问了什么」要等出事才知道")
    坏 = CN.检查密钥引用(引用)
    if 坏: 问.append(坏)
    if 问:
        raise _错(422, "VALIDATION", "这条工具连接建不了",
                  "按下面每一条改", field_errors={"闸": 问})
    cid = _新id("cc")
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        c.execute(text("""insert into capability_connections
            (id, organization_id, project_id, name, adapter, allowed_endpoints,
             secret_ref, status, owner, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n,:ad, cast(:ep as jsonb), :sr, 'active', :ow,
                    now(), :by, now(), 1)"""),
                  {"i": cid, "o": org, "p": project_id, "n": 名字, "ad": 适配器,
                   "ep": _json.dumps(端点, ensure_ascii=False), "sr": 引用,
                   "ow": me.user_id, "by": me.user_id})
        # ⚠️ 审计里只记**形状**,不记引用本身 —— 审计表是「事后查得到」的地方,
        # 也就是「事后读得到」的地方。
        _审计(c, me, "capability_connection.create",
              {"connection_id": cid, "name": 名字, "adapter": 适配器,
               "allowed_endpoints": 端点, "密钥形状": _引用形状(引用)})
    return {"id": cid, "名字": 名字, "密钥": _引用形状(引用),
            "允许的端点": 端点,
            "note": ("**密钥不回显**,这里给的是形状。"
                     "⚠️ 建完之后**连接发现的新工具不会自动给生产 Agent 权限** —— "
                     "发现回来的说明是外部输入,要先审再挂")}


# ── Skill 指南 ──────────────────────────────────────────────────
@router.get(前缀 + "/skills")
def 指南列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """一份指南 = 同名的一串版本。**身份是名字** —— 模型按名字请求加载。"""
    with 连接() as c:
        行 = [dict(r) for r in c.execute(text("""
            select id, name, purpose, version_no, review_status, load_mode,
                   file_manifest, content_hash, created_at
              from skill_versions
             where project_id=:p and archived_at is null
             order by name, version_no"""), {"p": project_id}).mappings()]
    按名 = {}
    for r in 行:
        d = 按名.setdefault(r["name"], {"名字": r["name"], "用途": r["purpose"],
                                      "版本": []})
        d["用途"] = r["purpose"] or d["用途"]
        d["版本"].append({"id": r["id"], "版本号": r["version_no"],
                        "复核状态": r["review_status"], "加载方式": r["load_mode"],
                        "参考文件": r["file_manifest"], "内容哈希": r["content_hash"]})
    return {"条数": len(按名), "指南": list(按名.values()),
            "note": ("⚠️ **指南不授予权限**(§11.3)—— 「启用了指南」被读成"
                     "「给了脚本权限」是这一块最容易出的误解。"
                     "这条链上**根本没有写权限的字段**,不是靠判据拦住的。"
                     "⚠️ Skill **不是微调,也不保证模型一定遵循**")}


@router.post(前缀 + "/skills", status_code=201)
async def 建指南(project_id: str, request: Request,
           me: 身份 = Depends(要权限("改编排草稿"))):
    """建一份新指南(出第 1 版)。入参 `{名字, 用途?, 正文, 参考文件?}`。"""
    体 = await request.json()
    return await _出指南版本(project_id, 体, me, 指定名字=None)


@router.post(前缀 + "/skills/{name}/versions", status_code=201)
async def 冻结指南版本(project_id: str, name: str, request: Request,
                me: 身份 = Depends(要权限("改编排草稿"))):
    """给一份已有的指南出新版本。**写下就不许改。**"""
    体 = await request.json()
    return await _出指南版本(project_id, 体, me, 指定名字=name)


async def _出指南版本(project_id, 体, me, *, 指定名字):
    名字 = 指定名字 or (体.get("名字") or 体.get("name") or "").strip()
    用途 = (体.get("用途") or 体.get("purpose") or "").strip() or None
    正文 = (体.get("正文") or 体.get("instructions") or "").strip()
    文件 = 体.get("参考文件") or 体.get("file_manifest") or []
    加载 = (体.get("加载方式") or 体.get("load_mode") or "按需").strip()
    问 = CAP.可以建指南吗(名字=名字, 指令=正文, 文件清单=文件)
    if 问:
        raise _错(422, "VALIDATION", "这份指南建不了",
                  "按下面每一条改。**首版只收 Markdown 指南和只读参考文件**",
                  field_errors={"闸": 问})
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        上一版 = c.execute(text("""select version_no from skill_versions
                                where project_id=:p and name=:n
                                order by version_no desc limit 1"""),
                        {"p": project_id, "n": 名字}).scalar()
        if 指定名字 is None and 上一版:
            raise _错(409, "SKILL_EXISTS", f"已经有一份叫「{名字}」的指南",
                      f"要出新版本用 `POST /skills/{名字}/versions` —— "
                      f"**同名两份指南,模型按名字加载时不知道该拿哪一份**")
        if 指定名字 is not None and not 上一版:
            raise _错(404, "NOT_FOUND", f"没有叫「{名字}」的指南",
                      "先用 `POST /skills` 建第一版")
        新号 = (上一版 or 0) + 1
        哈 = CAP.内容哈希({"名字": 名字, "正文": 正文, "参考文件": 文件})
        sid = _新id("sk")
        c.execute(text("""insert into skill_versions
            (id, organization_id, project_id, name, purpose, version_no,
             instructions, file_manifest, review_status, load_mode, content_hash,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n,:pu,:v,:ins, cast(:fm as jsonb), '待复核', :lm, :h,
                    now(), :by, now(), 1)"""),
                  {"i": sid, "o": org, "p": project_id, "n": 名字, "pu": 用途,
                   "v": 新号, "ins": 正文,
                   "fm": _json.dumps(文件, ensure_ascii=False), "lm": 加载,
                   "h": 哈, "by": me.user_id})
        _审计(c, me, "skill.version.create",
              {"skill_name": 名字, "skill_version_id": sid, "version_no": 新号})
    return {"id": sid, "名字": 名字, "版本号": 新号, "内容哈希": 哈,
            "复核状态": "待复核",
            "note": ("**复核状态从「待复核」起** —— 一份没人看过的指南和一份审过的,"
                     "在界面上都显示「已挂载」。"
                     "⚠️ **指南不授予权限**:挂上它不会让模型多拿到任何工具")}


# ── 规则策略 ────────────────────────────────────────────────────
@router.get(前缀 + "/policies")
def 规则列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        行 = [dict(r) for r in c.execute(text("""
            select id, name, purpose, version_no, rule_template, params,
                   trigger_point, failure_strategy, content_hash, created_at
              from policy_versions
             where project_id=:p and archived_at is null
             order by name, version_no"""), {"p": project_id}).mappings()]
    return {"条数": len(行),
            "策略": [{"id": r["id"], "名字": r["name"], "用途": r["purpose"],
                    "版本号": r["version_no"], "模板": r["rule_template"],
                    "模板是什么": CAP.规则模板.get(r["rule_template"], "(不在白名单里)"),
                    "参数": r["params"], "触发点": r["trigger_point"],
                    "命中之后": ((r["failure_strategy"] or {}).get("怎么办")
                              if isinstance(r["failure_strategy"], dict)
                              else r["failure_strategy"])} for r in 行],
            "可用的模板": CAP.规则模板,
            "note": ("⚠️ **「指令约定」和「程序强制」是两回事**:"
                     "提示词里写「不要删文件」是**约定**,规则拦住 delete 才是**强制**。"
                     "这一组建的全是强制。"
                     "⚠️ **只开白名单模板 + 配置参数,不开放任意代码**(§11.4)")}


@router.post(前缀 + "/policies", status_code=201)
async def 建规则(project_id: str, request: Request,
           me: 身份 = Depends(要权限("配置密钥与预算"))):
    体 = await request.json()
    名字 = (体.get("名字") or 体.get("name") or "").strip()
    用途 = (体.get("用途") or 体.get("purpose") or "").strip() or None
    模板 = (体.get("模板") or 体.get("rule_template") or "").strip()
    参数 = 体.get("参数") if "参数" in 体 else (体.get("params") or {})
    触发 = (体.get("触发点") or 体.get("trigger_point") or "").strip()
    失败时 = (体.get("命中之后") or 体.get("failure_strategy") or "").strip()
    问 = CAP.可以建规则吗(名字=名字, 模板=模板, 参数=参数, 触发=触发, 失败时=失败时)
    if 问:
        raise _错(422, "VALIDATION", "这条规则建不了",
                  "按下面每一条改。**只开白名单模板 + 配置参数**",
                  field_errors={"闸": 问, "可用的模板": list(CAP.规则模板)})
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        上一版 = c.execute(text("""select version_no from policy_versions
                                where project_id=:p and name=:n
                                order by version_no desc limit 1"""),
                        {"p": project_id, "n": 名字}).scalar()
        新号 = (上一版 or 0) + 1
        哈 = CAP.内容哈希({"名字": 名字, "模板": 模板, "参数": 参数,
                       "触发点": 触发, "命中之后": 失败时})
        pid = _新id("pol")
        c.execute(text("""insert into policy_versions
            (id, organization_id, project_id, name, purpose, version_no,
             rule_template, params, trigger_point, failure_strategy, content_hash,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:n,:pu,:v,:rt, cast(:pa as jsonb), :tp,
                    cast(:fs as jsonb), :h, now(), :by, now(), 1)"""),
                  {"i": pid, "o": org, "p": project_id, "n": 名字, "pu": 用途,
                   "v": 新号, "rt": 模板,
                   "pa": _json.dumps(参数, ensure_ascii=False), "tp": 触发,
                   # ⚠️ `failure_strategy` 也是 **JSONB** —— **今天第八次**。
                   "fs": _json.dumps({"怎么办": 失败时}, ensure_ascii=False),
                   "h": 哈, "by": me.user_id})
        _审计(c, me, "policy.version.create",
              {"policy_name": 名字, "policy_version_id": pid, "version_no": 新号,
               "rule_template": 模板, "trigger_point": 触发})
    return {"id": pid, "名字": 名字, "版本号": 新号, "模板": 模板,
            "模板是什么": CAP.规则模板[模板], "触发点": 触发, "命中之后": 失败时,
            "note": ("这是**程序强制**,不是提示词里的约定 —— "
                     "提示词里写「不要删文件」是约定,这条规则拦住才是强制")}
