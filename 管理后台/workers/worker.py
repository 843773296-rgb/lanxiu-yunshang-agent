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


# 一批多少个片段。**不是随便定的**:批是检查点的粒度 ——
# 批大一点省往返,批小一点崩溃时少重算。20 个片段(真语料一批约 1.2 万字)
# 在 mock 下毫秒级,接真 Embedding API 时也在单次请求的常见上限内。
索引批大小 = 20


@处理("index_build")
def _建一次索引(c, job, 打点):
    """建一次向量索引(规格 §19.3)。

    ## ⚠️⚠️ 这个处理器和别的三个不一样:**片段的写入走独立事务**

    `跑一轮()` 把处理器整个包在**一个** `with 事务() as c:` 里。
    对秒级的任务(prompt_run / workflow_run / agent_run)那样正好;
    但对这个任务,那意味着 **写了 100 个向量然后崩了,全部回滚** ——
    `index_members` 在崩溃后是空的,于是 `index_plan.算待做()`
    永远算出「全部待做」。

    > **判据对、代码对,而整件事不成立。检查点的前提是它能被提交。**

    所以向量和成员用 `事务()` 开**独立连接**,每批提交一次。
    代价必须先说清:

      · **「job 失败」和「库里没东西」不再等价** —— 一个失败的构建会留下
        已经算好的向量。**那正是检查点**,不是垃圾。任何清理逻辑、
        任何「重跑前先清干净」的假设都得知道这件事。
      · 独立事务**只碰 `embeddings` 和 `index_members`,绝不碰 `index_builds`** ——
        外层事务对 `index_builds` 那一行持有 `for update` 锁,
        独立连接去改它会死锁。构建状态一律走外层的 `c`。

    ## 检查点是 `index_members` 本身,不是计数器

    没有「已完成片段数」这种列。计数器和产物会漂(写了 100 条成员而计数停在 80),
    **而漂了不报错**。`index_members` 里的行就是真相。

    ## 跨构建复用向量

    向量的身份是 `(project_id, text_hash, model_id)`(唯一约束钉着)。
    所以「检索配置改了 → 新建构建」那次新建**一个向量都不用重算** ——
    这里在 Embedding 之前先按 text_hash 查一次。
    """
    import sys as _s
    _kn = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "services", "api", "app", "knowledge")
    if _kn not in _s.path:
        _s.path.insert(0, _kn)
    import index_plan as IP
    import embedder as EMB

    t = job["target_ref"] or {}
    build_id = t.get("index_build_id")
    # ⚠️⚠️ **这里不能加 `for update`。** 踩过,而且表现是**永久挂起而不是报错**:
    #
    # 外层事务对 `index_builds` 那一行加排他锁之后,下面分批写入用的独立事务
    # 插 `index_members` 时,**外键检查要对父行加 `FOR KEY SHARE` 锁** ——
    # 于是它被**我自己的外层事务**阻塞,谁也动不了。
    #
    # 我在这个函数的文档里写了「独立事务绝不碰 `index_builds`」,以为够了 ——
    # **但外键让它间接碰了。**「不碰那张表」和「不碰那一行」是两件事,
    # 而外键把后者变成了前者管不住的。
    #
    # 而 `for update` 在这里本来就是多余的:同一个构建不会被两个 Worker
    # 同时处理 —— **那个保护由 job 租约提供**(`lease.取一个` 的
    # `for update skip locked` + `lease_owner` 条件更新)。
    # (`_跑一张工作流` 也用了 `for update`,那条留着:它不开独立事务,
    #  不会有这个交互。改它没有收益,而无谓的改动会带来无谓的风险。)
    b = c.execute(text("""select * from index_builds
                          where project_id=:p and id=:i"""),
                  {"p": job["project_id"], "i": build_id}).mappings().first()
    if not b:
        raise 干不了("NOT_FOUND", {"index_build_id": build_id})
    if b["status"] in ("已就绪", "失败", "已取消"):
        # **已经跑完了** —— 重复投递是正常故障场景,不重做
        return {"index_build_id": build_id, "已经是终态": b["status"]}

    模型 = b["embedding_model_id"] or "emb-mock"
    维度 = b["embedding_dim"] or EMB.维度

    # ── ① 输入:知识库下**每篇文档的最新版本**的片段 ────────────────────
    # 为什么是最新版本:旧版本的片段留着做历史证据链(片段绑文档版本),
    # 但索引只索引当前内容 —— 否则同一段话的两个版本会在检索里各占一个名额。
    片段们 = c.execute(text("""
        with latest as (
            select dv.document_id as doc, max(dv.revision) as rev
              from document_versions dv
              join documents d on d.project_id = dv.project_id
                              and d.id = dv.document_id
             where dv.project_id = :p and d.knowledge_base_id = :kb
               and d.disabled_at is null
             group by dv.document_id
        )
        select ch.id, ch.text, ch.text_hash, ch.section_path, ch.ordinal,
               ch.document_version_id, ch.chunker_version, ch.parser_version
          from chunks ch
          join document_versions dv on dv.project_id = ch.project_id
                                   and dv.id = ch.document_version_id
          join latest l on l.doc = dv.document_id and l.rev = dv.revision
         where ch.project_id = :p
         order by ch.document_version_id, ch.ordinal
    """), {"p": job["project_id"], "kb": b["knowledge_base_id"]}).mappings().all()
    if not 片段们:
        # **不静默成功。** 一个 0 个片段的「已就绪」索引,检索时永远返回空,
        # 而界面上它和「知识库里就这么点东西」长得一模一样。
        raise 干不了("NO_CHUNKS",
                      {"knowledge_base_id": b["knowledge_base_id"],
                       "怎么办": "先导入文档并切片(tools/ingest_lanxiu.py),"
                                "再发起构建 —— **0 个片段的索引不算建成了**"})
    打点("取到输入", {"阶段": "collect", "片段数": len(片段们)})

    # ── ② 版本一致性:**混着切的片段不许进同一个索引** ──────────────────
    # 片段记着切它的版本(`chunks.chunker_version`)。一批 seg-1 一批 seg-2
    # 混在一个索引里,边界不一样 —— 检索照样跑,只是答得怪,**而且不报错**。
    切版本 = {x["chunker_version"] for x in 片段们}
    解版本 = {x["parser_version"] for x in 片段们}
    if len(切版本) > 1 or len(解版本) > 1:
        raise 干不了("MIXED_CHUNKER_VERSION",
                      {"切片器版本": sorted(map(str, 切版本)),
                       "解析器版本": sorted(map(str, 解版本)),
                       "怎么办": "把这些文档版本重新切一遍(同一个版本),再建索引 —— "
                                "**边界不一样的片段混在一个索引里,检索答得怪而不报错**"})
    if None in 切版本 or None in 解版本:
        # 空不等于「和当前一样」。见 chunks 的契约注释:填错的版本号比空的更糟,
        # 而空的这里要当场拦住,不猜一个。
        raise 干不了("CHUNKER_VERSION_MISSING",
                      {"怎么办": "这些片段没记下切它的版本 —— **不猜一个当前值**:"
                                "猜错会让指纹说「输入没变」而实际边界已经不同。"
                                "重新切一遍(导入脚本现在会记)"})

    # ── ③ 输入指纹 → 续做还是新建(§19.3)────────────────────────────
    指纹 = IP.输入指纹(
        知识库id=b["knowledge_base_id"],
        文档版本id们=sorted({x["document_version_id"] for x in 片段们}),
        检索配置版本id=b["retrieval_config_version_id"],
        embedding模型id=模型, embedding维度=维度,
        # **从片段实际记的版本读**,不从代码常量读 —— 后者隐含
        # 「库里的片段是当前版本切的」这个假设,而它失效时不报错。
        切片器版本=切版本.pop(), 解析器版本=解版本.pop())
    动作, 为什么 = IP.该新建还是续做(
        构建=dict(输入指纹=b["input_hash"], status=b["status"]),
        现在的指纹=指纹)
    打点("续做判定", {"阶段": "fingerprint", "动作": 动作, "为什么": 为什么})
    if 动作 == "新建" and b["input_hash"]:
        # 指纹变过 = 输入在排队期间被改过。**不静默跑新的那一份** ——
        # 那会让这个构建的结果和它记的指纹对不上,而对不上的那一刻
        # 没有任何地方说过为什么(和 workflow 那条 DEFINITION_CHANGED 同一道理)。
        raise 干不了("INPUT_CHANGED_WHILE_QUEUED",
                      {"受理时": (b["input_hash"] or "")[:26], "现在": 指纹[:26],
                       "为什么": 为什么,
                       "怎么办": "发起一次新的构建 —— 旧的这次保留,它记的是受理时那一版"})
    if not b["input_hash"]:
        c.execute(text("""update index_builds set input_hash=:h, updated_at=now(),
                          revision=coalesce(revision,0)+1
                          where project_id=:p and id=:i"""),
                  {"h": 指纹, "p": job["project_id"], "i": build_id})

    # ── ④ 已经做完的跳过(检查点)────────────────────────────────────
    成员行 = c.execute(text("""
        select im.chunk_id, im.embedding_id, e.dim as 维
          from index_members im
          left join embeddings e on e.project_id = im.project_id
                                and e.id = im.embedding_id
         where im.project_id = :p and im.index_build_id = :b
    """), {"p": job["project_id"], "b": build_id}).mappings().all()
    计划 = IP.算待做(
        目标片段们=[dict(id=x["id"], text_hash=x["text_hash"]) for x in 片段们],
        成员们=[dict(chunk_id=m["chunk_id"], embedding_id=m["embedding_id"],
                    **{"embedding维度": m["维"]}) for m in 成员行],
        期望维度=维度)
    打点("算出待做", {"阶段": "plan", "待做": len(计划["待做"]),
                   "已完成": len(计划["已完成"]), "要重做": len(计划["要重做"]),
                   "指纹体检": 计划["指纹体检"]})
    if 计划["陈旧成员"]:
        # 指纹自己的体检红了 —— **不继续**。索引里有不属于这一版输入的片段,
        # 说明指纹漏了一项真实输入,而那正是混血索引的入口。
        raise 干不了("FINGERPRINT_INCOMPLETE",
                      {"陈旧片段": 计划["陈旧成员"][:5],
                       "说明": 计划["指纹体检"]})

    文本表 = {x["id"]: x["text"] for x in 片段们}
    哈希表 = {x["id"]: x["text_hash"] for x in 片段们}
    待做 = 计划["待做"]
    c.execute(text("""update index_builds set status='向量化中', updated_at=now(),
                      revision=coalesce(revision,0)+1
                      where project_id=:p and id=:i"""),
              {"p": job["project_id"], "i": build_id})

    # ── ⑤ 分批:算向量 → **独立事务写入并提交** → 打点 ──────────────────
    写了, 复用了 = 0, 0
    for 起 in range(0, len(待做), 索引批大小):
        批 = 待做[起:起 + 索引批大小]
        if 打点.取消了:
            # 已经提交的那些批**留着** —— 那是检查点,不是垃圾。
            raise 取消了()
        向量们 = EMB.算([文本表[x["id"]] for x in 批], 模型id=模型, 期望维度=维度)
        with 事务() as c2:          # ← 独立连接,提交后就是检查点
            for 片, v in zip(批, 向量们):
                # 跨构建复用:同一段文本 + 同一个模型只算一次
                eid = c2.execute(text("""select id from embeddings
                                         where project_id=:p and text_hash=:h
                                           and model_id=:m"""),
                                 {"p": job["project_id"], "h": v["text_hash"],
                                  "m": 模型}).scalar()
                if eid:
                    复用了 += 1
                else:
                    eid = _新("emb")
                    c2.execute(text("""
                        insert into embeddings (id, organization_id, project_id,
                            text_hash, model_id, dim, embedding,
                            created_at, created_by, revision)
                        values (:i,:o,:p,:h,:m,:d, cast(:v as vector), now(), :u, 1)
                        on conflict (project_id, text_hash, model_id) do nothing
                    """), {"i": eid, "o": job["organization_id"],
                           "p": job["project_id"], "h": v["text_hash"], "m": 模型,
                           "d": v["维度"], "v": EMB.成SQL文本(v["向量"]), "u": 我是谁})
                    # on conflict 命中时上面那条什么都没插 —— 把真正在库里的那个 id 读回来。
                    # (并发的另一个 Worker 可能刚插了同一段文本。)
                    eid = c2.execute(text("""select id from embeddings
                                             where project_id=:p and text_hash=:h
                                               and model_id=:m"""),
                                     {"p": job["project_id"], "h": v["text_hash"],
                                      "m": 模型}).scalar()
                    写了 += 1
                c2.execute(text("""
                    insert into index_members (id, organization_id, project_id,
                        index_build_id, chunk_id, embedding_id, created_at, created_by)
                    values (:i,:o,:p,:b,:c,:e, now(), :u)
                    on conflict (project_id, index_build_id, chunk_id) do nothing
                """), {"i": _新("im"), "o": job["organization_id"],
                       "p": job["project_id"], "b": build_id, "c": 片["id"],
                       "e": eid, "u": 我是谁})
        # 打点在批**提交之后** —— 报的是已经落地的数,不是打算做的数
        打点("一批写完", {"阶段": "embed", "这批": len(批),
                       "累计新算": 写了, "累计复用": 复用了})

    # ── ⑥ 收尾:成员数要和目标片段数一致 ─────────────────────────────
    c.execute(text("""update index_builds set status='写索引中', updated_at=now(),
                      revision=coalesce(revision,0)+1
                      where project_id=:p and id=:i"""),
              {"p": job["project_id"], "i": build_id})
    最终 = c.execute(text("""select count(*) from index_members
                            where project_id=:p and index_build_id=:b"""),
                    {"p": job["project_id"], "b": build_id}).scalar()
    if 最终 != len(片段们):
        # **集合相等判据,不是「至少写了一条」。** 少了就是有片段检索不到,
        # 多了说明写重了(而唯一约束应该已经拦住)—— 两种都不该报成功。
        raise 干不了("INDEX_INCOMPLETE",
                      {"片段数": len(片段们), "成员数": 最终,
                       "说明": "成员数和片段数不一致 —— **少了就有内容检索不到**,"
                              "而那在界面上和「知识库里就这么点」长得一样"})
    c.execute(text("""update index_builds set status='已就绪', updated_at=now(),
                      revision=coalesce(revision,0)+1
                      where project_id=:p and id=:i"""),
              {"p": job["project_id"], "i": build_id})
    return {"index_build_id": build_id, "片段数": len(片段们), "成员数": 最终,
            "新算向量": 写了, "复用向量": 复用了, "输入指纹": 指纹[:26],
            "是mock": True}


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
