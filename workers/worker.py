#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台 Worker(规格 §19.3)。

## 它必须是幂等的,而且这不是「尽量」

Outbox 的设计**保证**会有重复投递(规格 §17.1:「重复投递是正常故障场景」)。
所以每个处理器进来第一件事是 **检查现有结果** —— 已经做完的不重做。
把重复投递当异常处理的 worker 一定会出错。

## 心跳在处理过程中打,不是跑完才打

一个只在开始和结束打心跳的 worker,中间那段时间**和卡死没有区别**。
所以处理器每推进一步就 `续租()`,顺便把「有人请求取消吗」读回来。

## 取消:令牌传给执行器,终态由后台确认

规格 §19.3:「取消令牌向执行器传递;后台确认终态。
**强制杀进程不能保证外部任务/费用立即停止**」。
所以这里的取消是**协作式**的:处理器在每个检查点看一眼令牌,自己收尾。
杀进程只会让租约过期、然后被别人接手 —— 那不是取消。

## 怎么跑

    make worker                  # 一直跑
    python3 workers/worker.py --一轮   # 只跑一轮(测试和 CI 用)
"""
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "services", "api", "app"),
                os.path.join(ROOT, "services", "api", "app", "jobs"),
                os.path.join(ROOT, "services", "api", "app", "contract")]

from sqlalchemy import text
import lease as L
import outbox as OB
import events as EV
from db import 事务, 连接

我是谁 = os.environ.get("WORKER_NAME") or f"worker-{os.getpid()}-{uuid.uuid4().hex[:4]}"


class 取消了(Exception):
    """取消令牌被置上 —— **由处理器自己抛**,不是被外面杀掉。"""


class 干不了(Exception):
    """带错误码的失败。code 决定该不该重试(见 lease.该重试吗)。"""
    def __init__(self, code, 细节=None):
        super().__init__(code)
        self.code, self.细节 = code, 细节


def _新(前缀): return f"{前缀}_{uuid.uuid4().hex[:12]}"


# ── 处理器登记表 ────────────────────────────────────────────────────
# ⚠️ **认不出的任务类型不许静默跳过。** 一个被跳过的任务会一直停在「排队中」,
# 而「没人处理」和「排在后面」在界面上长得一模一样。
处理器 = {}


def 处理(类型):
    def 包(f):
        处理器[类型] = f
        return f
    return 包


@处理("prompt_run")
def _跑一次prompt(c, job, 打点):
    """调试运行。**先看有没有做过** —— Outbox 保证会有重复投递。"""
    t = job["target_ref"] or {}
    run_id, pid = t.get("run_id"), t.get("prompt_id")
    做过 = c.execute(text("""select id from traces
                           where project_id=:p and session_id=:s limit 1"""),
                     {"p": job["project_id"], "s": run_id}).first()
    if 做过:
        # **幂等**:重复投递时不再跑一遍模型(那会多花一次钱)
        打点("跳过", {"为什么": "这个 run 已经有 trace 了 —— 重复投递,不重跑",
                     "trace_id": 做过[0]})
        return {"trace_id": 做过[0], "幂等命中": True}

    d = c.execute(text("select * from prompt_drafts where project_id=:p and id=:i"),
                  {"p": job["project_id"], "i": pid}).mappings().first()
    if not d:
        # 引用的对象不存在 —— **不重试**,它不会自己出现
        raise 干不了("NOT_FOUND", {"prompt_id": pid})

    打点("展开模板", {"阶段": "render"})
    if 打点.取消了:
        raise 取消了()

    import main as _api                       # 复用 mock 适配器,不抄第二份
    r = _api._mock生成(dict(d), t.get("变量") or {})

    打点("调模型", {"阶段": "generate", "execution_mode": r["execution_mode"]})
    if 打点.取消了:
        raise 取消了()

    trace = _新("tr")
    c.execute(text("""
        insert into traces (id, organization_id, project_id, session_id, request_id,
            environment, started_at, ended_at, end_reason, created_at, created_by)
        values (:i,:o,:p,:s,:rq,:e, now(), now(), :er, now(), :u)
    """), {"i": trace, "o": job["organization_id"], "p": job["project_id"],
           "s": run_id, "rq": job["id"], "e": os.environ.get("APP_ENV", "development"),
           "er": r["finish_reason"], "u": 我是谁})
    c.execute(text("""
        insert into spans (id, organization_id, project_id, trace_id, stage,
            input_ref, output_ref, started_at, ended_at, created_at, created_by)
        values (:i,:o,:p,:t,'generate',:ir,:orf, now(), now(), now(), :u)
    """), {"i": _新("sp"), "o": job["organization_id"], "p": job["project_id"],
           "t": trace,
           "ir": __import__("json").dumps({"展开后模板": r["展开后模板"]}, ensure_ascii=False),
           "orf": __import__("json").dumps(
               {"text": r["text"], "execution_mode": r["execution_mode"]},
               ensure_ascii=False), "u": 我是谁})
    # 费用:mock 没有真实计价 → **amount_known=false,不写 0**
    c.execute(text("""
        insert into usage_ledger (id, organization_id, project_id, event_key, trace_id,
            resource, quantity, unit, currency, amount, amount_known, source,
            created_at, created_by)
        values (:i,:o,:p,:ek,:t,'generate',:q,'token','CNY', null, false, :src,
                now(), :u)
        -- ⚠️ 冲突目标是 **(project_id, event_key)**,不是 event_key 单列。
        -- 唯一约束从单列改成带 project_id 之后,这一行 ON CONFLICT 当场编译不过
        -- (PostgreSQL 要求冲突目标**精确匹配**一个唯一约束)——
        -- 那次红是好的:它逼着这个调用点跟着改。
        -- 反过来想:要是当时**加**一条复合约束而**留着**单列那条,
        -- 这里一个字都不用改,而跨项目撞键那个漏一点没修好。
        on conflict (project_id, event_key) do nothing
    """), {"i": _新("ul"), "o": job["organization_id"], "p": job["project_id"],
           "ek": f"{job['id']}:generate", "t": trace,
           "q": r["usage"]["input_tokens"] + r["usage"]["output_tokens"],
           "src": r["execution_mode"], "u": 我是谁})
    return {"trace_id": trace, "execution_mode": r["execution_mode"]}


@处理("workflow_run")
def _跑一张工作流(c, job, 打点):
    """跑一次 Workflow。**照 `_跑一次prompt` 的形状**:
    进门第一件事查现有结果(Outbox 保证会有重复投递),每推进一步打点。

    ## 为什么这里不重新校验、不重新编译

    接口层(`workflows_api.发起运行`)已经编译过了 —— 配置错了要**当场**知道,
    而不是排队等一会儿再看到一条「失败」。这里重新编译一次是为了拿到执行计划
    (计划本身没存库),但**校验结论以接口那次为准**:
    execution_runs.definition_hash 记的是那一次的逻辑哈希,
    如果这里算出来不一样,说明**定义在排队期间被改过** —— 那要报出来,
    不能悄悄跑新的那份(§12.3:「继续执行不把暂停期间更新的 Prompt 静默装入旧 Run」,
    同一条道理)。
    """
    import json as _j
    t = job["target_ref"] or {}
    run_id = t.get("run_id")
    r = c.execute(text("""select * from execution_runs
                         where project_id=:p and id=:i for update"""),
                  {"p": job["project_id"], "i": run_id}).mappings().first()
    if not r:
        raise 干不了("RUN_NOT_FOUND", {"run_id": run_id})
    if r["status"] in ("succeeded", "incomplete", "failed", "cancelled", "expired"):
        # **已经跑完了** —— 重复投递是正常故障场景,不重做
        return {"run_id": run_id, "已经是终态": r["status"]}

    import sys as _s
    _rt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "services", "api", "app", "runtime")
    _s.path.insert(0, _rt)
    _s.path.insert(0, os.path.join(os.path.dirname(_rt), "contract"))
    import compiler as CP
    import runner as RN

    来源 = r["definition_ref"] or {}
    if 来源.get("kind") == "workflow_version":
        v = c.execute(text("""select * from workflow_versions
                             where project_id=:p and id=:i"""),
                      {"p": job["project_id"], "i": 来源["version_id"]}).mappings().first()
        定义 = {"definition_schema_version": v["definition_schema_version"],
                "kind": "workflow", "nodes": v["nodes"], "edges": v["edges"],
                "input_schema": v["input_schema"], "output_schema": v["output_schema"]}
    else:
        d = c.execute(text("""select * from graph_drafts
                             where project_id=:p and workflow_id=:i"""),
                      {"p": job["project_id"], "i": 来源["id"]}).mappings().first()
        定义 = (d["definition"] if d else None) or {}
    打点("取到定义", {"来源": 来源})

    try:
        计划 = CP.编译(定义, 依赖存在=lambda 种类, i: True)
    except CP.编译失败 as e:
        raise 干不了("COMPILE_FAILED",
                      {"阻断": [p["code"] for p in e.问题们][:6]})
    if 计划["逻辑哈希"] != r["definition_hash"]:
        # **定义在排队期间被改过。** 不静默跑新的那一份 ——
        # 那会让这次运行的结果和 execution_runs 上记的哈希对不上,
        # 而对不上的那一刻没有任何地方说过为什么。
        raise 干不了("DEFINITION_CHANGED_WHILE_QUEUED",
                      {"受理时": (r["definition_hash"] or "")[:26],
                       "现在": 计划["逻辑哈希"][:26],
                       "怎么办": "重新发起一次运行 —— 旧的这次保留,它记的是受理时那一版"})

    c.execute(text("""update execution_runs set status='running', updated_at=now()
                      where project_id=:p and id=:i"""),
              {"p": job["project_id"], "i": run_id})
    打点("开始执行", {"节点数": len(计划["节点"])})

    def _mock_llm(cfg, 实参):
        # **mock 适配器**。和真实适配器同一个契约,但 execution_mode=mock ——
        # 一份 mock 跑出来的报告和真实报告在数据形状上一模一样,
        # 唯一的区别就是这个字段(§19.4)。
        文 = f"[mock:{cfg.get('prompt_version_id')}] " + \
             " / ".join(f"{k}={str(v)[:40]}" for k, v in sorted(实参.items()))
        return {"text": 文, "lang": "zh", "execution_mode": "mock",
                "usage": {"input_tokens": 12, "output_tokens": 34},
                "finish_reason": "stop"}

    事件序号 = [1]

    def 记事(种类, 载荷):
        事件序号[0] += 1
        c.execute(text("""
            insert into run_events (id, organization_id, project_id, execution_run_id,
                seq, event_type, payload, occurred_at, created_at, created_by)
            values (:i,:o,:p,:r,:s,:k,:pl, now(), now(), :u)
        """), {"i": _新("re"), "o": job["organization_id"], "p": job["project_id"],
               "r": run_id, "s": 事件序号[0], "k": 种类,
               "pl": _j.dumps(载荷, ensure_ascii=False, default=str), "u": 我是谁})

    结果 = RN.跑一张图(计划, r["input_snapshot"] or {}, 适配器={"llm": _mock_llm},
                    记事=记事, run_id=run_id, 上限=r["limits"] or {},
                    系统={"project_id": job["project_id"]})
    打点("执行完", {"状态": 结果["执行状态"]})

    for s in 结果["步骤"]:
        c.execute(text("""
            insert into run_steps (id, organization_id, project_id, execution_run_id,
                node_id, kind, iteration_path, attempt, execution_key, status,
                branch_key, skipped_reason, error_code, error_detail, output_ref,
                started_at, ended_at, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:r,:n,:k,'/',:a,:ek,:st,:bk,:sr,:ec,:ed,null,
                    now(), now(), now(), :u, now(), 1)
            on conflict (project_id, execution_key) do nothing
        """), {"i": _新("rs"), "o": job["organization_id"], "p": job["project_id"],
               "r": run_id, "n": s["node_id"], "k": s["kind"], "a": s.get("attempt", 1),
               "ek": s["execution_key"], "st": s["status"],
               "bk": s.get("branch_key"), "sr": s.get("skipped_reason"),
               "ec": s.get("error_code"),
               "ed": _j.dumps(s.get("error_detail"), ensure_ascii=False)
                     if s.get("error_detail") else None,
               "u": 我是谁})
    c.execute(text("""
        update execution_runs
           set status=:st, completion_reason=:cr, output_ref=:out,
               usage_snapshot=:us, ended_at=now(), updated_at=now(), revision=revision+1
         where project_id=:p and id=:i
    """), {"st": 结果["执行状态"], "cr": 结果["完成原因"],
           "out": _j.dumps(结果["输出"], ensure_ascii=False),
           "us": _j.dumps(结果["用量"], ensure_ascii=False),
           "p": job["project_id"], "i": run_id})
    # 费用:mock 没有真实计价 → **amount_known=false,不写 0**
    c.execute(text("""
        insert into usage_ledger (id, organization_id, project_id, event_key, trace_id,
            resource, quantity, unit, currency, amount, amount_known, source,
            created_at, created_by)
        values (:i,:o,:p,:ek,:t,'generate',:q,'call','CNY', null, false, 'mock',
                now(), :u)
        on conflict (project_id, event_key) do nothing
    """), {"i": _新("ul"), "o": job["organization_id"], "p": job["project_id"],
           "ek": f"{run_id}:workflow", "t": r["trace_id"],
           "q": 结果["用量"]["模型调用"], "u": 我是谁})
    return {"run_id": run_id, "执行状态": 结果["执行状态"],
            "走过的路径": 结果["走过的路径"], "跳过的节点": 结果["跳过的节点"]}


@处理("agent_run")
def _跑一个agent(c, job, 打点):
    """跑一次 Agent。**照 `_跑一张工作流` 的形状** —— 进门先看是不是已经终态。

    ## 这里和 Workflow 那条最大的不同:**账本落在 tool_invocations 表上**

    §17.3 要的是「每次写动作**先登记 intent**……收到响应后登记结果」。
    执行器和网关都只认一个**很小的账本接口**(查 / 登记意图 / 标已提交 / 登记结果),
    所以这里给它一个贴着 `tool_invocations` 表的实现。
    夹具测试给的是内存版 —— **同一个接口两个实现**,而测试那一份和运行时是两份记录。
    """
    import json as _j
    t = job["target_ref"] or {}
    run_id = t.get("run_id")
    r = c.execute(text("""select * from execution_runs
                         where project_id=:p and id=:i for update"""),
                  {"p": job["project_id"], "i": run_id}).mappings().first()
    if not r:
        raise 干不了("RUN_NOT_FOUND", {"run_id": run_id})
    if r["status"] in ("succeeded", "incomplete", "failed", "cancelled", "expired"):
        return {"run_id": run_id, "已经是终态": r["status"]}

    import sys as _s
    _rt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "services", "api", "app", "runtime")
    _app = os.path.dirname(_rt)
    for _p in (_rt, os.path.join(_app, "contract"), _app,
               os.path.join(_app, "jobs")):
        _s.path.insert(0, _p)
    import agent_loop as AL
    import tool_gateway as TG
    import agents_api as AA
    import dsl as _DS

    来源 = r["definition_ref"] or {}
    if 来源.get("kind") == "agent_version":
        v = c.execute(text("""select * from agent_versions
                             where project_id=:p and id=:i"""),
                      {"p": job["project_id"], "i": 来源["version_id"]}).mappings().first()
        cfg = {k: v[k] for k in ("prompt_version_id", "connection_version_id",
                                 "task_template", "tools", "context_policy", "limits",
                                 "output_schema", "completion_criteria",
                                 "incomplete_strategy", "execution_strategy",
                                 "input_schema")}
    else:
        d = c.execute(text("""select * from graph_drafts
                             where project_id=:p and agent_id=:i"""),
                      {"p": job["project_id"], "i": 来源["id"]}).mappings().first()
        cfg = (d["definition"] if d else None) or {}
    if _DS.逻辑哈希(cfg) != r["definition_hash"]:
        # **配置在排队期间被改过** —— 不静默跑新的那一份(和 Workflow 同一条道理)
        raise 干不了("DEFINITION_CHANGED_WHILE_QUEUED",
                   {"受理时": (r["definition_hash"] or "")[:26],
                    "现在": _DS.逻辑哈希(cfg)[:26],
                    "怎么办": "重新发起一次运行 —— 旧的这次保留,它记的是受理时那一版"})

    # 指令:Agent 版本引用的是 Prompt 的**确切版本**
    pv = c.execute(text("""select messages from prompt_versions
                         where project_id=:p and id=:i"""),
                   {"p": job["project_id"], "i": cfg.get("prompt_version_id")}
                   ).mappings().first()
    cfg = dict(cfg, instructions=((pv["messages"] or {}).get("system") if pv else "")
                                 or cfg.get("instructions") or "")

    # ⚠️ 目录按**版本 ID** 建键 —— 因为 `cfg["tools"]` 里就是版本 ID(§16.3:
    # Agent 版本引用工具的**确切版本**)。「版本 ID → 名字」的换算在 agent_loop
    # 里做,那里也查同名撞车。
    # 第一版这里按名字建键,于是 agent_loop 拿版本 ID 一个都查不到 ——
    # 表现是 **Agent 一个工具都不用**,而人会去改提示词、换模型、调温度。
    # 抓到它的是 agent_loop 里那条 `agent.tool_missing` 事件(它**没有静默跳过**)。
    目录 = AA._工具目录(c, job["project_id"], cfg.get("tools") or [])
    工具名们 = sorted(契["name"] for 契 in 目录.values())

    c.execute(text("""update execution_runs set status='running', updated_at=now()
                      where project_id=:p and id=:i"""),
              {"p": job["project_id"], "i": run_id})
    打点("开始执行", {"工具": 工具名们, "上限": cfg.get("limits")})

    # ── 账本:贴着 tool_invocations 表 ─────────────────────────────
    class 表账本:
        def __init__(self):
            self.条目, self.顺序 = {}, []
            self.步骤id = _新("rs")
            c.execute(text("""
                insert into run_steps (id, organization_id, project_id,
                    execution_run_id, node_id, kind, iteration_path, attempt,
                    execution_key, status, started_at, created_at, created_by,
                    updated_at, revision)
                values (:i,:o,:p,:r,'agent','agent','/',1,:ek,'running',
                        now(), now(), :u, now(), 1)
                on conflict (project_id, execution_key) do nothing
            """), {"i": self.步骤id, "o": job["organization_id"],
                   "p": job["project_id"], "r": run_id,
                   "ek": f"{run_id}:agent:/:1", "u": 我是谁})

        def 查(self, aid):
            r2 = c.execute(text("""select * from tool_invocations
                                  where project_id=:p and logical_action_id=:a"""),
                           {"p": job["project_id"], "a": aid}).mappings().first()
            if not r2:
                return None
            return dict(状态=r2["status"], 工具=r2["outcome"],
                        参数摘要=r2["arguments_hash"], 幂等键=r2["idempotency_key"],
                        结果=r2["result_ref"] and _j.loads(r2["result_ref"]))

        def 登记意图(self, aid, *, 工具, 参数摘要, 幂等键):
            c.execute(text("""
                insert into tool_invocations (id, organization_id, project_id,
                    run_step_id, side_effect_type, arguments_hash, idempotency_key,
                    logical_action_id, outcome, status, execution_mode, intent_at,
                    created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:s,null,:h,:k,:a,:t,'intent_registered','mock',
                        now(), now(), :u, now(), 1)
                on conflict (project_id, logical_action_id) do nothing
            """), {"i": _新("ti"), "o": job["organization_id"], "p": job["project_id"],
                   "s": self.步骤id, "h": 参数摘要, "k": 幂等键, "a": aid, "t": 工具,
                   "u": 我是谁})
            self.顺序.append(aid)
            self.条目[aid] = dict(状态="intent_registered", 工具=工具,
                                参数摘要=参数摘要, 幂等键=幂等键, 结果=None)
            return True

        def 标已提交(self, aid):
            c.execute(text("""update tool_invocations set status='submitted',
                                  updated_at=now()
                              where project_id=:p and logical_action_id=:a"""),
                      {"p": job["project_id"], "a": aid})

        def 登记结果(self, aid, *, 状态, 结果=None, 错误码=None):
            c.execute(text("""
                update tool_invocations
                   set status=:st, result_ref=:rr, error_code=:ec,
                       needs_human_check=:nh, responded_at=now(), updated_at=now()
                 where project_id=:p and logical_action_id=:a
            """), {"st": 状态,
                   "rr": _j.dumps(结果, ensure_ascii=False) if 结果 else None,
                   "ec": 错误码,
                   # **待核实 ≠ 终态**:标成需要人看,但不写成失败
                   "nh": (状态 == "needs_verification"),
                   "p": job["project_id"], "a": aid})
            if aid in self.条目:
                self.条目[aid]["状态"] = 状态
                self.条目[aid]["结果"] = 结果

    账 = 表账本()
    事件序号 = [1]

    def 记事(种类, 载荷):
        事件序号[0] += 1
        c.execute(text("""
            insert into run_events (id, organization_id, project_id, execution_run_id,
                seq, event_type, payload, occurred_at, created_at, created_by)
            values (:i,:o,:p,:r,:s,:k,:pl, now(), now(), :u)
        """), {"i": _新("re"), "o": job["organization_id"], "p": job["project_id"],
               "r": run_id, "s": 事件序号[0], "k": 种类,
               "pl": _j.dumps(载荷, ensure_ascii=False, default=str), "u": 我是谁})

    # ── mock 模型:**脚本化的,而且它自己说自己是 mock** ─────────────
    轮 = [0]

    def _mock模型(消息们, 工具定义们):
        轮[0] += 1
        只读的 = [t["name"] for t in 工具定义们
                 if t.get("side_effect_type") == _DS.只读]
        if 轮[0] == 1 and 只读的:
            return {"tool_calls": [{"id": f"call_{轮[0]}", "name": 只读的[0],
                                    "arguments": {"q": "官方资料"}}],
                    "usage": {"input_tokens": 20, "output_tokens": 30}}
        return {"finish": {"report": "[mock] 这是一份合成报告,**不代表真实智能能力**",
                           "evidence_refs": ["https://example.com/official"],
                           "unknown_items": ["价格(mock 没有真实来源)"]},
                "usage": {"input_tokens": 20, "output_tokens": 40}}

    def _mock只读工具(参数):
        return {"items": [{"title": "官方页", "url": "https://example.com/official"}],
                "execution_mode": "mock"}

    适配器 = {"model": _mock模型}
    for 名, 契 in 目录.items():
        # 只给只读工具接 mock 实现;**写工具默认不接** ——
        # §14.1:「对有写能力的测试,**默认替换模拟适配器并显示替换清单**」。
        # 这里更保守:干脆不接,于是网关会报 ADAPTER_MISSING,**而那是要被看见的**。
        if 契["side_effect_type"] == _DS.只读:
            适配器[契["adapter"]] = _mock只读工具
    记事("agent.adapters", {
        "接了": [k for k in 适配器 if k != "model"],
        "没接": [契["adapter"] for 契 in 目录.values()
                if 契["side_effect_type"] != _DS.只读],
        "为什么": "**写工具默认不接 mock 实现** —— 网关会报 ADAPTER_MISSING,"
                 "而那是要被看见的(§14.1:写动作测试要显示替换清单)"})

    结果 = AL.跑一个agent(
        cfg, r["input_snapshot"] or {}, 适配器=适配器, 工具目录=目录,
        有效范围={"paths": [], "hosts": ["*.example.com"], "ids": []},
        账本=账, 记事=记事,
        # **产物在不在由调用方判** —— 这一版没有对象存储适配,所以一律「不在」。
        # 于是任何声明了 artifacts 的 finish 都会被核验挡住,**这是对的**:
        # 「我已保存报告」在没有存储的环境里本来就不可能成立。
        产物在吗=lambda ref: False,
        批准查询=None, run_id=run_id)
    打点("执行完", {"状态": 结果["execution_status"]})

    c.execute(text("""update run_steps set status=:st, ended_at=now(), updated_at=now()
                      where project_id=:p and execution_run_id=:r and node_id='agent'"""),
              {"st": ("succeeded" if 结果["execution_status"] == "succeeded"
                      else "failed"), "p": job["project_id"], "r": run_id})
    c.execute(text("""
        update execution_runs
           set status=:st, completion_reason=:cr, output_ref=:out, usage_snapshot=:us,
               ended_at=now(), updated_at=now(), revision=revision+1
         where project_id=:p and id=:i
    """), {"st": 结果["execution_status"], "cr": 结果["completion_reason"],
           "out": _j.dumps(结果["output"], ensure_ascii=False),
           "us": _j.dumps(结果["usage"], ensure_ascii=False),
           "p": job["project_id"], "i": run_id})
    c.execute(text("""
        insert into usage_ledger (id, organization_id, project_id, event_key, trace_id,
            resource, quantity, unit, currency, amount, amount_known, source,
            created_at, created_by)
        values (:i,:o,:p,:ek,:t,'generate',:q,'call','CNY', null, false, 'mock',
                now(), :u)
        on conflict (project_id, event_key) do nothing
    """), {"i": _新("ul"), "o": job["organization_id"], "p": job["project_id"],
           "ek": f"{run_id}:agent", "t": r["trace_id"],
           "q": 结果["usage"]["模型回合"], "u": 我是谁})
    return {"run_id": run_id, "执行状态": 结果["execution_status"],
            "停止原因": 结果["completion_reason"], "用量": 结果["usage"],
            "核验问题": 结果["validation_results"][:3]}


class _打点器:
    """每一步:写事件 + 续租 + 把取消令牌读回来。"""
    def __init__(self, c, job):
        self.c, self.job, self.取消了, self.n = c, job, False, 0

    def __call__(self, kind, payload=None):
        self.n += 1
        EV.记一条(self.c, org=self.job["organization_id"], 项目=self.job["project_id"],
                 job_id=self.job["id"], kind=kind, payload=payload or {},
                 新id=_新("je"))
        好, 取消 = L.续租(self.c, self.job["project_id"], self.job["id"], 我是谁,
                        阶段=(payload or {}).get("阶段"), 已处理=self.n)
        if not 好:
            # 租约不在我手上了 —— **立刻停手**,别再往下写
            raise 干不了("LEASE_LOST", {"说明": "租约过期或被接手,停手不覆盖"})
        self.取消了 = 取消


def 跑一轮(类型=None, 项目=None):
    """捞一条跑完。返回一句人话(没活干就返回 None)。"""
    with 事务() as c:
        job = L.取一个(c, 我是谁, 类型=类型, 项目=项目)
    if not job:
        return None
    名 = f"{job['type']}#{job['id'][-8:]}"
    f = 处理器.get(job["type"])
    if f is None:
        # **认不出的类型不静默跳过** —— 它会一直停在「排队中」,
        # 而「没人处理」和「排在后面」在界面上一模一样
        with 事务() as c:
            EV.记一条(c, org=job["organization_id"], 项目=job["project_id"],
                     job_id=job["id"], kind="没有处理器",
                     payload={"type": job["type"], "已登记的": sorted(处理器)},
                     新id=_新("je"))
            L.收尾(c, job["project_id"], job["id"], 我是谁, "失败",
                  error_code="INCOMPATIBLE",
                  error_detail={"说明": f"没有 {job['type']} 的处理器"})
        return f"{名}:没有处理器 → 失败(**不静默跳过**)"

    try:
        with 事务() as c:
            打点 = _打点器(c, job)
            打点("开始", {"阶段": "start", "worker": 我是谁})
            出 = f(c, job, 打点)
            打点("完成", dict(出 or {}))
            ok, 说 = L.收尾(c, job["project_id"], job["id"], 我是谁, "已完成")
            if not ok:
                raise 干不了("LEASE_LOST", {"说明": 说})
        return f"{名}:已完成 {出}"
    except 取消了:
        with 事务() as c:
            EV.记一条(c, org=job["organization_id"], 项目=job["project_id"],
                     job_id=job["id"], kind="收到取消,停手", payload={}, 新id=_新("je"))
            # 先进「取消请求中」再到「已取消」—— 状态机不许直接跳
            c.execute(text("""update jobs set status='取消请求中', updated_at=now(),
                              revision=revision+1
                              where project_id=:p and id=:i and lease_owner=:me"""),
                      {"p": job["project_id"], "i": job["id"], "me": 我是谁})
            L.收尾(c, job["project_id"], job["id"], 我是谁, "已取消")
        return f"{名}:按取消令牌停手了"
    except 干不了 as e:
        with 事务() as c:
            EV.记一条(c, org=job["organization_id"], 项目=job["project_id"],
                     job_id=job["id"], kind="失败",
                     payload={"code": e.code, "细节": e.细节}, 新id=_新("je"))
            ok, 说 = L.退回重试(c, job["project_id"], job["id"], 我是谁, e.code, e.细节)
        return f"{名}:{e.code} —— {说}"
    except Exception as e:
        # 没预料到的异常:**当成可重试的瞬时故障,但记清是什么** ——
        # 不记的话,重试三次之后只剩一个「失败」,原因追不回来
        with 事务() as c:
            EV.记一条(c, org=job["organization_id"], 项目=job["project_id"],
                     job_id=job["id"], kind="崩了",
                     payload={"异常": f"{type(e).__name__}: {e}"}, 新id=_新("je"))
            L.退回重试(c, job["project_id"], job["id"], 我是谁, "TRANSIENT",
                      {"异常": f"{type(e).__name__}: {e}"})
        return f"{名}:崩了 {type(e).__name__}: {e}"


def main():
    一轮 = "--一轮" in sys.argv
    类型 = None
    for i, a in enumerate(sys.argv):
        if a == "--type" and i + 1 < len(sys.argv): 类型 = sys.argv[i + 1]
    print(f"worker 起来了:{我是谁}" + (f"(只跑 {类型})" if 类型 else ""))
    空转 = 0
    while True:
        with 事务() as c:
            发, 卡 = OB.发布一批(c)
        if 卡:
            print(f"  ⚠️ 发件箱里有 {卡} 条到了尝试上限还没发出去 —— **人要看一眼**:"
                  f"一条永远发不出去的消息会把发布器卡住,而卡住的发布器"
                  f"看起来只是「最近没有新任务」")
        话 = 跑一轮(类型=类型)
        if 话:
            print("  " + 话); 空转 = 0
        else:
            空转 += 1
        if 一轮:
            # 一轮模式:把当前能捞到的都跑完再退,方便测试和 CI
            if 话 is None:
                break
            continue
        time.sleep(min(5.0, 0.2 * 空转) if 空转 else 0.05)


if __name__ == "__main__":
    main()
