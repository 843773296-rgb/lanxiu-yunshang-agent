#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调试那几条(规格 §5.3、§12.3、§14.1、§17.1/§17.2)。

    GET  /runs/{id}                        看一次运行(**原文按字段授权**)
    POST /node-tests                       从选中节点测试(**不计为端到端通过**)
    POST /execution-runs/{id}/fork-test    从历史点另开调试(**新 Run**)
    GET  /execution-runs/{id}/events       运行事件(SSE,按 after_seq 补拉)

## 这四条共同守一句话:**调试出来的结果不许冒充正式结果**

四种冒充,四条对策:

| 冒充 | 对策 |
|---|---|
| 从中间节点测一段,报成「端到端通过了」 | `不计为端到端通过`,而且**标明上游是模拟还是历史输入** |
| 调试时真的把东西写出去 | **写工具默认替换成模拟适配器**,并且**显示替换清单** |
| 从历史点重开,原地改旧的那次运行 | **新建 Run + `parent_run_id`**,旧的一个字不动 |
| 外部还没回来就先报 `tool.succeeded` | 事件流**不许**在外部返回成功之前发那条 |

第三条的原话是「**不原地改旧目标冒充同一个任务**」——
原地改的后果很具体:「那次到底跑了什么」永远答不出来了,
因为回答这个问题的那行数据已经被改成了这次的样子。

## ⚠️ SSE 那条:**每轮重新鉴权**

§17.1 明写。一条长连接建立时有权限,不代表十分钟后还有 ——
权限被撤了而流还在推,那条流就成了一个绕过权限的通道。
所以每一轮补拉都重新走一遍 `要权限`,而不是在建立连接时查一次。
"""
import json as _json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import states as ST

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _审计(c, me, action, target):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, created_at, created_by)
        values (:i,:o,:p,:a,:ac,cast(:t as jsonb),:e, now(), 'ok', now(), :a)
    """), {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id,
           "ac": action, "t": _json.dumps(target, ensure_ascii=False),
           "e": os.environ.get("APP_ENV", "development")})


def _脱敏(值):
    """**给形状,不是截断** —— 截到前几个字,那几个字仍然是原文。

    和 `runs_api.脱敏()` 同一条;那边守的是 trace 原文,这边守的是调试输入输出。
    """
    if 值 is None:
        return None
    if isinstance(值, dict):
        return {k: (f"<{type(v).__name__} · {len(str(v))} 字>"
                    if not isinstance(v, (int, float, bool)) and v is not None
                    else v) for k, v in 值.items()}
    return f"<{type(值).__name__} · {len(str(值))} 字>"


# ── 看一次运行 ──────────────────────────────────────────────────
@router.get(前缀 + "/runs/{rid}")
def 看一次运行(project_id: str, rid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """看一次 Prompt 调试运行。

    ⚠️ **调试的输入输出可能带真实业务内容,原文同样按字段授权。**
    没有那条专项授权时只给形状 —— 而「看得到这次运行」和「看得到它的原文」
    是两件事,合成一件的话,一个只该看得到「跑过了」的人会拿到客户对话。
    """
    看得到原文 = me.看得到原文吗()
    with 连接() as c:
        r = c.execute(text("""select id, status, kind, environment, input_snapshot,
                                   output_ref, usage_snapshot, started_at, ended_at,
                                   trace_id, parent_run_id, completion_reason
                              from execution_runs
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": rid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", f"没有这次运行 {rid}", "回运行列表重新进入")
        r = dict(r)
        事件数 = c.execute(text("""select count(*) from run_events
                                where project_id=:p and execution_run_id=:i"""),
                        {"p": project_id, "i": rid}).scalar()
    return {
        "id": r["id"], "status": r["status"], "kind": r["kind"],
        "环境": r["environment"], "开始": r["started_at"], "结束": r["ended_at"],
        "trace_id": r["trace_id"],
        "从哪次 fork 来的": r["parent_run_id"],
        "结束原因": r["completion_reason"],
        "事件条数": 事件数,
        "输入": r["input_snapshot"] if 看得到原文 else _脱敏(r["input_snapshot"]),
        "输出": r["output_ref"] if 看得到原文 else _脱敏(r["output_ref"]),
        "用量": r["usage_snapshot"],
        "看得到原文吗": 看得到原文,
        "note": (("看得到原文 —— 这条来自「查看敏感输入/独立测试答案」那条专项授权"
                  if 看得到原文 else
                  "**没有那条专项授权,所以输入输出只给形状**(键名 + 多长)—— "
                  "不是截断:截到前几个字,那几个字仍然是原文。"
                  "「看得到这次运行」和「看得到它的原文」是两件事")
                 + ("。⚠️ `从哪次 fork 来的` 不为空 = **这是一次调试分叉**,"
                    "它的结果不代表那次原始运行" if r["parent_run_id"] else ""))}


# ── 从选中节点测试 ──────────────────────────────────────────────
@router.post(前缀 + "/node-tests", status_code=202)
async def 从节点测试(project_id: str, request: Request,
              idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
              me: 身份 = Depends(要权限("运行编排测试"))):
    """从选中的节点往下测一段。入参 `{运行, 节点, 上游来源}`。

    ⚠️ **不计为端到端通过**(§5.3)。从中间节点起跑,上游要么是模拟数据、
    要么是历史输入 —— 两种都不是「这条链真的从头走通了」。
    所以这里**强制要求说明上游是哪一种**,而且结果上标着 `算端到端通过吗=false`。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "节点测试是异步动作,超时重发是常态")
    体 = await request.json()
    源运行 = (体.get("运行") or 体.get("execution_run_id") or "").strip()
    节点 = (体.get("节点") or 体.get("node_id") or "").strip()
    上游 = (体.get("上游来源") or 体.get("upstream") or "").strip()
    上游们 = ("模拟数据", "历史输入")
    坏 = {}
    if not 节点: 坏["节点"] = "必填"
    if 上游 not in 上游们:
        坏["上游来源"] = (f"只收 {list(上游们)} —— **必须说清**:"
                     f"从中间起跑的那一段,上游是编的还是当时真发生过的,"
                     f"读结果的人要知道")
    if 坏:
        raise _错(422, "VALIDATION", "节点测试的参数不合格",
                  "上游来源不能省 —— 它决定这次结果能说明什么", field_errors=坏)
    with 事务() as c:
        老 = c.execute(text("""select id, status from execution_runs
                             where project_id=:p and idempotency_key=:k"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            return {"id": 老["id"], "status": 老["status"], "新建了吗": False,
                    "note": "**同一个幂等键 → 返回原运行,没有再跑一次**"}
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        父 = None
        if 源运行:
            父 = c.execute(text("""select id from execution_runs
                                 where project_id=:p and id=:i"""),
                           {"p": project_id, "i": 源运行}).scalar()
            if not 父:
                raise _错(422, "RUN_NOT_FOUND", f"没有运行 {源运行}",
                          "确认运行号;**不静默当成从头跑** —— "
                          "那样结果会看起来像一次完整运行")
        rid = _新id("run")
        起点 = ST.找("execution_run")["起点"]
        # ⚠️ **写工具默认替换成模拟适配器**(§14.1),而且要给出替换清单。
        替换 = _写工具替换清单(c, project_id)
        快照 = {"从哪个节点起": 节点, "上游来源": 上游,
              "算端到端通过吗": False,
              "写工具替换清单": 替换,
              "父运行": 父}
        c.execute(text("""insert into execution_runs
            (id, organization_id, project_id, kind, input_snapshot, status,
             principal, parent_run_id, execution_mode, idempotency_key,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'node_test', cast(:inp as jsonb), :st, :who, :par,
                    'mock', :k, now(), :who, now(), 1)"""),
                  {"i": rid, "o": org, "p": project_id,
                   "inp": _json.dumps(快照, ensure_ascii=False), "st": 起点,
                   "who": me.user_id, "par": 父, "k": idempotency_key})
        _审计(c, me, "node_test.create",
              {"run_id": rid, "node_id": 节点, "upstream": 上游,
               "parent_run_id": 父})
    return {"id": rid, "status": 起点, "新建了吗": True,
            "算端到端通过吗": False,
            "上游来源": 上游,
            "写工具替换清单": 替换,
            "note": ("⚠️ **这一次不计为端到端通过**(§5.3)—— 从中间节点起跑,"
                     f"上游是「{上游}」,而两种都不是「这条链真的从头走通了」。"
                     "⚠️ **写工具已经默认换成模拟适配器**(§14.1),清单在上面 —— "
                     "不给清单的话,「它到底写没写出去」要等出事才知道")}


def _写工具替换清单(c, project_id):
    """调试时被换成模拟的那些写工具。**要显示出来**(§14.1)。

    ⚠️ 只给清单,不给「已替换=true」一个布尔 —— 一个布尔答不出
    「到底哪几个被换了」,而那正是人要确认的事。
    """
    行 = c.execute(text("""select id, name, side_effect_type from tool_definitions
                         where project_id=:p and side_effect_type <> 'read_only'
                           and archived_at is null order by id"""),
                   {"p": project_id}).mappings().all()
    return [{"工具": r["name"], "原本是": r["side_effect_type"], "换成": "模拟适配器"}
            for r in 行]


# ── 从历史点另开调试 ────────────────────────────────────────────
@router.post(前缀 + "/execution-runs/{rid}/fork-test", status_code=202)
async def 从历史点另开(project_id: str, rid: str, request: Request,
               idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
               me: 身份 = Depends(要权限("运行编排测试"))):
    """从一次历史运行的某个点另开一次调试。

    ⚠️ **新 Run,引用 `parent_run_id`,写操作默认模拟**(§12.3)——
    原话:「**不原地改旧目标冒充同一个任务**」。
    原地改的后果很具体:「那次到底跑了什么」永远答不出来了,
    因为回答这个问题的那行数据已经被改成了这次的样子。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "分叉调试是异步动作,超时重发是常态")
    体 = await request.json()
    从第几步 = 体.get("从第几步") if "从第几步" in 体 else 体.get("from_seq")
    with 事务() as c:
        老 = c.execute(text("""select id, status from execution_runs
                             where project_id=:p and idempotency_key=:k"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            return {"id": 老["id"], "status": 老["status"], "新建了吗": False,
                    "note": "**同一个幂等键 → 返回原分叉,没有再开一次**"}
        父 = c.execute(text("""select * from execution_runs
                             where project_id=:p and id=:i"""),
                       {"p": project_id, "i": rid}).mappings().first()
        if not 父:
            raise _错(404, "NOT_FOUND", f"没有这次运行 {rid}", "回运行列表重新进入")
        父 = dict(父)
        新id = _新id("run")
        起点 = ST.找("execution_run")["起点"]
        替换 = _写工具替换清单(c, project_id)
        快照 = {"从哪次分叉": rid, "从第几步": 从第几步,
              "算端到端通过吗": False, "写工具替换清单": 替换,
              "父运行当时的状态": 父["status"]}
        c.execute(text("""insert into execution_runs
            (id, organization_id, project_id, kind, input_snapshot, status,
             principal, parent_run_id, release_ref, environment, execution_mode,
             idempotency_key, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'fork_test', cast(:inp as jsonb), :st, :who, :par,
                    cast(:rel as jsonb), :env, 'mock', :k,
                    now(), :who, now(), 1)"""),
                  {"i": 新id, "o": 父["organization_id"], "p": project_id,
                   "inp": _json.dumps(快照, ensure_ascii=False), "st": 起点,
                   "who": me.user_id, "par": rid,
                   # ⚠️ **沿用父运行钉的那一版**,不重新解析环境指针 ——
                   # 重新解析的话,分叉出来的这次跑的可能是**另一版**,
                   # 而人看到的是「从那次分叉出来的」,会以为是同一版。
                   "rel": _json.dumps(父.get("release_ref"), ensure_ascii=False),
                   "env": 父.get("environment"), "k": idempotency_key})
        _审计(c, me, "fork_test.create",
              {"run_id": 新id, "parent_run_id": rid, "from_seq": 从第几步})
    return {"id": 新id, "status": 起点, "新建了吗": True,
            "从哪次分叉": rid, "算端到端通过吗": False,
            "写工具替换清单": 替换,
            "note": ("**这是一次新的运行,旧的那次一个字没动**(§12.3)—— "
                     "原地改旧目标的话,「那次到底跑了什么」永远答不出来了。"
                     "⚠️ 沿用父运行钉的那一版,**不重新解析环境指针** —— "
                     "重新解析的话分叉出来的可能是另一版,而人会以为是同一版。"
                     "⚠️ 写操作默认模拟,清单在上面")}


# ── 运行事件(SSE)────────────────────────────────────────────────
@router.get(前缀 + "/execution-runs/{rid}/events")
def 运行事件(project_id: str, rid: str,
         me: 身份 = Depends(要权限("查看有权配置")),
         after_seq: int = Query(0, ge=0, description="从这一条之后开始补拉"),
         limit: int = Query(200, ge=1, le=1000)):
    """运行事件。**按 `after_seq` 补拉**(§17.1)。

    ⚠️ **每轮重新鉴权。** 这里做成「一轮一请求」的补拉,而不是一条长连接 ——
    长连接建立时有权限,不代表十分钟后还有;**权限被撤了而流还在推,
    那条流就成了一个绕过权限的通道**。
    做成补拉之后,每一轮都要重新过 `要权限`,这件事由框架保证,不靠我记得。

    ⚠️ **不能在外部返回成功之前先发 `tool.succeeded`**(§17.2)——
    这条的落点不在这里(这里只读),在写事件那一侧;
    但读这一侧要能**看出**顺序不对,所以带上每条的 `occurred_at` 和 `seq`。
    """
    with 连接() as c:
        有 = c.execute(text("select 1 from execution_runs where project_id=:p and id=:i"),
                       {"p": project_id, "i": rid}).first()
        if not 有:
            raise _错(404, "NOT_FOUND", f"没有这次运行 {rid}", "回运行列表重新进入")
        行 = [dict(r) for r in c.execute(text("""
            select seq, event_type, step_id, payload, occurred_at
              from run_events
             where project_id=:p and execution_run_id=:i and seq > :a
             order by seq limit :lim"""),
            {"p": project_id, "i": rid, "a": after_seq, "lim": limit}).mappings()]
        最大 = c.execute(text("""select coalesce(max(seq),0) from run_events
                              where project_id=:p and execution_run_id=:i"""),
                       {"p": project_id, "i": rid}).scalar()
    return {"条数": len(行), "after_seq": after_seq,
            "最新的 seq": 最大,
            "还有吗": bool(行) and 行[-1]["seq"] < 最大,
            "下一次从这儿拉": (行[-1]["seq"] if 行 else after_seq),
            "事件": [{"seq": r["seq"], "类型": r["event_type"], "步骤": r["step_id"],
                    "发生于": r["occurred_at"], "内容": r["payload"]} for r in 行],
            "note": ("**按 `after_seq` 补拉,每一轮都重新鉴权**(§17.1)—— "
                     "做成长连接的话,建立时有权限不代表十分钟后还有,"
                     "而权限被撤了流还在推,那条流就成了绕过权限的通道。"
                     + ("⚠️ **一条事件都没有** —— 可能是这次运行还没开始产出事件,"
                        "也可能是 `after_seq` 给大了(最新的是 "
                        f"{最大})。两种下一步不同,所以这里把最大 seq 一起给出来。"
                        if not 行 else ""))}
