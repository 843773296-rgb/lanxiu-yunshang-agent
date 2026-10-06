#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行策略:**冻结一版、实例回报加载、查谁采用了** —— 规格 §10.3。

    POST  /execution-policy-versions     冻结一版(**冻结 ≠ 发布**)
    GET   /execution-policy-versions     列表(带**实例回执覆盖数**)
    POST  /policy-instance-receipts       实例回报它加载了哪一版

## ⚠️ 和 `selection_api.py` 开头那段话同一个处境,照抄它的诚实

> 「策略能配、能校验、能冻结;**而没有任何东西在消费它**。
> 这件事写在返回里(`⚠️还没生效`)——
> 一个配得出来而没人消费的策略,和一个生效了的策略,
> **在界面上长得一模一样。**」

这里完全一样,只是又往前走了一步:现在**回执也能收了**,
所以规格 §4.2 的四个状态里前三个有落点了 ——

    ① 草稿已保存     (复用现有草稿接口,规格 §4.1 不要求新建)
    ② 版本已发布     冻结在这儿;**发布引用由 `release_manifests` 管**
    ③ 实例已加载     回执在这儿
    ④ 本次运行已采用  **通了**(2026-10-06)—— 两处写:受理时冻进
                     `execution_runs.policy_snapshot`、Run 真开始时写
                     `adopted_policy_snapshot`,**两份不一致就停**。
                     ⚠️ 那条入口(后台 Agent)仍然**写死跑 mock** ——
                     所以「采用记下来了」和「上限真的拦住了什么」
                     **是两件事**,别混着读

所以每个返回里都明说「到这一步为止,下一步还缺什么」。

## 判定逻辑**全在 `runtime/` 那四个纯逻辑模块里**,这儿只做 IO

    策略冻结.冻()       算哈希、校验形状(拼错的键、布尔当数字)
    回执核验.核()       哈希对不上是**冲突**、loaded_at 服务端盖、能力三态
    策略解析.这次用哪一版() 起任务时用(**这儿不用**)—— 四态:采用/回退/内置兜底/拒绝启动
    采用快照.装()       Run 开始时用(**这儿不用**)
    采用快照.判两份()   受理时那份 vs Run 开始那份,**不一致就停**(**这儿不用**)
    兜底上限.兜底()     一版都没发布过时用哪套数(**这儿不用**)

⚠️ **这儿不重写任何一条判据。** 两份判定迟早分叉,而分叉时两边各自都是绿的
—— 这件事今天刚栽过一次(`回执核验` 和 `策略解析` 的陈旧判定写了两份)。

## 权限:回执这条**点得不对,而它点不对是有原因的**

调用方是一个**执行实例**(进程),而权限表里 13 条能力全是给人的角色。
点「改编排草稿」→ 一个能改草稿的人就能伪造回执;点管理员更糟。
真正的解法是**实例凭据**(让 `instance_ref` 从凭据推导而不是从 body 读),
本期规格没要求 —— 所以是**范围之外,不是漏做**,
已登记在 `tools/exec_limits_report.py` 的 ⏸ 档(每次门禁都印出来)。
> 「范围之外」和「已经安全」在那张接口表上长得一模一样。
"""
import json as _json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "contract"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "runtime"))

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错

import 策略冻结 as _FR
import 回执核验 as _RV

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

# 回执多久算陈旧 —— **和 `策略解析` 的默认值同一个数**。
# ⚠️ 两处各写一个数字迟早分叉,而分叉时两边各自都是绿的:
# 页面说「已加载」而起任务时说「陈旧」,**而两边都没报错**。
回执最长年龄秒 = 900


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


@router.post(前缀 + "/execution-policy-versions", status_code=201)
async def 冻一版(project_id: str, request: Request,
             me: 身份 = Depends(要权限("改编排草稿"))):
    """冻结一版执行策略。**判定全在 `策略冻结.冻()` 里,这儿只写库。**

    请求体就是草稿内容:`application_id` / `entry_kind` / `scope` /
    `limits` / `counter_schema_version` / `support_conditions`。
    """
    体 = await request.json()
    with 事务() as c:
        # 版本号由服务端算 —— **客户端不许指定**:
        # 「版本号唯一且密集」是页面「上一版」、差异对比和回滚都在隐含依赖的
        # 不变量,交给客户端等于把那个不变量交给了调用顺序。
        if "version_no" in 体:
            raise _错(422, "VALIDATION", "`version_no` 不收 —— 服务端算",
                      "版本号要唯一且密集,交给客户端等于把这个不变量交给调用顺序")
        上一版 = c.execute(text("""
            select version_no, content_hash from execution_policy_versions
             where project_id=:p and application_id=:a and entry_kind=:k
             order by version_no desc limit 1"""),
            {"p": project_id, "a": 体.get("application_id"),
             "k": 体.get("entry_kind")}).mappings().first()
        号 = (上一版["version_no"] + 1) if 上一版 else 1

        try:
            行 = _FR.冻(草稿=体, 版本号=号,
                     上一版号=(上一版["version_no"] if 上一版 else None))
        except _FR.冻不了 as e:
            # 原位报错(规格 §9.3:越界/不支持字段**原位报错**)。
            raise _错(422, "VALIDATION", "这份草稿冻不了", str(e))
        except KeyError as e:
            raise _错(422, "VALIDATION", f"缺字段:{e}", "按请求体字段表填")

        # ⚠️ **内容没变就不出新版本**(规格:改备注不该冒一个新版本)。
        # > 一个因为改了备注而冒出来的新版本,和一个真的改了限制的,
        # > **在版本列表上长得一模一样**,而回滚的人分不出该回到哪一版。
        if 上一版 and 行["content_hash"] == 上一版["content_hash"]:
            return {"id": None, "版本": f"v{上一版['version_no']}",
                    "内容哈希": 上一版["content_hash"],
                    "note": "**内容和上一版一样,没出新版本。** "
                            "改备注/负责人不进内容哈希 —— 否则版本列表里会堆满"
                            "行为完全相同的版本,而回滚的人分不出该回到哪一版"}

        vid = _新id("epv")
        c.execute(text("""
            insert into execution_policy_versions
                (id, organization_id, project_id, application_id, entry_kind,
                 scope, limits, counter_schema_version, support_conditions,
                 version_no, content_hash, created_at, created_by)
            values (:i,:o,:p,:a,:k,:sc,:lm,:cs,:su,:vn,:ch, now(), :u)"""),
            {"i": vid, "o": me.org_id, "p": project_id,
             "a": 行["application_id"], "k": 行["entry_kind"],
             "sc": _json.dumps(行["scope"], ensure_ascii=False),
             "lm": _json.dumps(行["limits"], ensure_ascii=False),
             "cs": 行["counter_schema_version"],
             "su": _json.dumps(行["support_conditions"], ensure_ascii=False),
             "vn": 行["version_no"], "ch": 行["content_hash"],
             "u": me.user_id})
    return {
        "id": vid, "版本": f"v{行['version_no']}",
        "内容哈希": 行["content_hash"],
        "要求入口支持": 行["support_conditions"],
        # ⚠️ **三件事分开说** —— 调接口的人看到 201 会以为生效了。
        "note": "**冻结了,但没发布,更没有任何实例加载。**",
        "⚠️还没生效": {
            "版本已发布": "**没有** —— 发布引用由 `release_manifests` 管"
                      "(规格 §4.1:优先扩展现有发布对象)",
            "实例已加载": "**没有** —— 要实例 POST /policy-instance-receipts;"
                      "在那之前页面要显示「尚未确认加载」(规格 §9.2),"
                      "而不是「已生效」",
            "本次运行已采用": "**链路通了**(2026-10-06)—— 受理时冻进 "
                        "`execution_runs.policy_snapshot`,Run 真开始时"
                        "(`workers/worker.py` 的 `_跑一个agent`)重新解析一次写进 "
                        "`adopted_policy_snapshot`,**两份不一致就停下让人看**"
                        "(业务拍的);判定在 `runtime/采用快照.判两份`。"
                        "⚠️ 而这一版**还没发布**,所以那些运行用的是"
                        "**内置兜底**(`runtime/兜底上限.py`)——"
                        "系统里不存在「无限制」这个档,但兜底**不是业务配的**",
            "怎么读": "规格 §4.2 把这四件事列成四行,并写明每一行"
                   "「**页面不能暗示什么**」—— 混成一个「已配置」的话,"
                   "页面上没有任何地方能看出配置没生效",
        },
    }


@router.get(前缀 + "/execution-policy-versions")
def 版本列表(project_id: str, limit: int = Query(50, ge=1, le=200),
          me: 身份 = Depends(要权限("查看有权配置"))):
    """列表。**每一版带实例回执覆盖数和最近一次采用时间**(规格 §9.2)。"""
    with 连接() as c:
        vs = c.execute(text("""
            select id, application_id, entry_kind, version_no, content_hash,
                   counter_schema_version, support_conditions, limits, created_at
              from execution_policy_versions
             where project_id=:p order by created_at desc limit :n"""),
            {"p": project_id, "n": limit}).mappings().all()
        出 = []
        for v in vs:
            # 回执:**按实例取最近一条**,然后算它新不新。
            # ⚠️ 不是「数一共有几条回执」—— 那个数会随时间只涨不跌,
            # 于是一台三天前下线的实例会永远算在覆盖数里。
            # > 一个数累计回执条数的覆盖数,和一个数「现在还在用」的,
            # > **在那个数字上长得一模一样**,而前者永远不下降。
            rs = c.execute(text("""
                select distinct on (instance_ref)
                       instance_ref, policy_hash, loaded_at, runner_version
                  from policy_instance_receipts
                 where project_id=:p and execution_policy_version_id=:v
                 order by instance_ref, loaded_at desc"""),
                {"p": project_id, "v": v["id"]}).mappings().all()
            import datetime as _dt
            现在 = _dt.datetime.now(_dt.timezone.utc)
            新鲜, 陈旧 = [], []
            for r in rs:
                够新, _原因, _话 = _RV.回执够新吗(
                    回执的loaded_at=r["loaded_at"].timestamp(),
                    现在=现在.timestamp(), 最长年龄秒=回执最长年龄秒)
                (新鲜 if 够新 else 陈旧).append(r["instance_ref"])
            # 最近一次**实际采用**:从 traces 的快照里找这一版。
            采 = c.execute(text("""
                select max(started_at) as t from traces
                 where project_id=:p
                   and execution_policy_version_id=:v"""),
                {"p": project_id, "v": v["id"]}).mappings().first()
            出.append({
                "id": v["id"], "应用": v["application_id"],
                "入口": v["entry_kind"], "版本": f"v{v['version_no']}",
                "内容哈希": v["content_hash"],
                "计数口径": v["counter_schema_version"],
                "要求入口支持": v["support_conditions"],
                "实例回执覆盖数": len(新鲜),
                "回执陈旧的实例数": len(陈旧),
                "回执陈旧的实例": 陈旧[:5],
                "最近一次实际采用": (采 or {}).get("t"),
                "加载确认了吗": ("确认了" if 新鲜 else
                           "**尚未确认加载**(规格 §9.2)—— "
                           "一条发了而没人加载的策略,和一条真在执行的,"
                           "在那个「已发布」上长得一模一样"),
                "⚠️": ("**覆盖数只数「现在还在用」的实例** —— "
                      "按 instance_ref 取最近一条回执再算年龄"
                      f"(超过 {回执最长年龄秒} 秒算陈旧);"
                      "数累计条数的话,一台三天前下线的实例会永远算在里面"),
            })
    return {"items": 出, "next_cursor": None, "total": None,
            "note": "`total` 是 **null 不是 0** —— 没数就明说没数(规格 §19.1)"}


@router.post(前缀 + "/policy-instance-receipts", status_code=201)
async def 收回执(project_id: str, request: Request,
             me: 身份 = Depends(要权限("改编排草稿"))):
    """实例回报它加载了哪一版。**判定全在 `回执核验.核()` 里。**

    ⚠️ **只追加,没有幂等键** —— 规格 §10.2「同一实例定期更新」:
    同一个实例反复回执同一个哈希,是「它**还在**用这一版」被确认了很多次。
    加幂等键的话那件事只会被记一次,而**第二天它还在不在用,表上看不出来**。
    """
    体 = await request.json()
    vid = 体.get("execution_policy_version_id")
    if not vid:
        raise _错(422, "VALIDATION", "要给 `execution_policy_version_id`",
                  "回执必须点名是哪一版 —— 「有回执」证明不了「加载了哪一版」")
    with 事务() as c:
        v = c.execute(text("""
            select id, project_id, content_hash, entry_kind, support_conditions
              from execution_policy_versions
             where project_id=:p and id=:i"""),
            {"p": project_id, "i": vid}).mappings().first()
        if not v:
            raise _错(404, "NOT_FOUND", "没有这一版执行策略",
                      "先 POST /execution-policy-versions 冻一版")
        import datetime as _dt
        现在 = _dt.datetime.now(_dt.timezone.utc)
        try:
            行 = _RV.核(这一版=dict(v), 实例报的=体,
                     服务端的project_id=project_id, 现在=现在)
        except _RV.回执不可信 as e:
            # ⚠️ **409 不是 422** —— 哈希对不上是**冲突**(两边都言之成理而
            # 事实只有一个),不是「你的参数格式不对」。
            # 报成 422 的话,实例那边会去改请求体,而该做的是去查它加载了什么。
            raise _错(409, "RECEIPT_CONFLICT", "这条回执不可信", str(e))

        rid = _新id("pir")
        c.execute(text("""
            insert into policy_instance_receipts
                (id, organization_id, project_id, instance_ref,
                 execution_policy_version_id, policy_hash, runner_version,
                 sdk_version, capability_map, loaded_at, created_at, created_by)
            values (:i,:o,:p,:ir,:v,:ph,:rv,:sv,:cm,:la, now(), :u)"""),
            {"i": rid, "o": me.org_id, "p": project_id,
             "ir": 行["instance_ref"], "v": 行["execution_policy_version_id"],
             "ph": 行["policy_hash"], "rv": 行["runner_version"],
             "sv": 行["sdk_version"],
             "cm": _json.dumps(行["capability_map"], ensure_ascii=False),
             "la": 行["loaded_at"], "u": me.user_id})
    核 = 行["_核出来的"]
    return {
        "id": rid, "实例": 行["instance_ref"],
        "这一版": 行["execution_policy_version_id"],
        "硬限制核对": {"支持": 核["支持"], "不支持": 核["不支持"],
                 "没核查过": 核["没核查过"]},
        "note": "**回执收下了。** 这不等于这台实例跑得了这一版 —— "
                "能不能跑由起任务时的 `策略解析` 判",
        "⚠️怎么读": {
            "为什么不在这儿拒绝能力不够的": 核["怎么读"],
            "下一步": "起任务时 `策略解析.这次用哪一版()` 会拿这条回执核年龄"
                   f"(超过 {回执最长年龄秒} 秒算陈旧)和硬限制支持情况",
            "实例身份": "⚠️ `instance_ref` 是**请求体给的** —— "
                    "本期没有实例凭据机制,有这条权限的调用方能以任何实例的"
                    "名义回执。规格 §10.3 只要求核验 project_id 和动作标识,"
                    "**范围之外,不是漏做**;已登记在 exec_limits_report 的 ⏸ 档",
        },
    }
