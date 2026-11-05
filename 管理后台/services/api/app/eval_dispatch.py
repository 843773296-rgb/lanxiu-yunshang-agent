#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测派发(DF-05,2026-11-05;Dify 对标 §8.2 / 验收 C17)。

在这之前,「建评测」只是登记一条「排队中」—— **没有任何执行方会去跑它**(库里攒了上百条永远排队的)。
C17 的原话:「每版两轮、回执完整、超时有终态;不把排队登记当执行完成」。

## 形状

- **派**(建评测那一刻,同一个事务):每道冻结题 × 候选 / 基线 × 每一轮,各走一次 `workflows_api._受理运行`
  —— 和「试运行」同一条受理路(编译、建 trace / run / job、入发件箱),不抄第二份。
  跑法记成「评测」:**模型真调、澜绣数据真读,写入类业务动作只演练**(和连接测试同一条,见 worker `_工具`)。
  每派一次在 evaluation_runs 记一行回执:哪道题、哪一边、第几轮、哪一版、哪次运行、哪个任务。
- **收**(worker 每 60 秒,`收一遍`):子运行到终态的,写一条逐题结果(不可变)+ 一条「跑通」分;
  然后按顺序判终态:**费用超了上限 → 超时 → 全收齐**。超了 / 超时都先把没跑完的取消掉,再落终态。
- 状态:已派发(只是排上队)→ 执行中(**至少一次子运行真的开始了**)→ 已完成 / 超时 / 超出费用上限 / 已取消。

## 为什么「跑通」是这一版唯一的分

它是事实(子运行是不是成功结束),不是判断。「答得对不对」要一套判据 —— 那是算法选型,要用户确认,
这一版**不替人编一个**;其余维度等判分器或人工复核来补(记成「没打分」,不记 0)。
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime"))

from sqlalchemy import text

边们 = ("候选", "基线")
终态们 = ("succeeded", "incomplete", "failed", "cancelled", "expired")
# 一次评测最多派多少次运行。**这是技术上限,不是产品配置**:派发在建评测那一个事务里做,
# 再大就该分批 —— 到时候改成分批,别把这个数调大了事
派发上限 = 400
评测终态们 = ("已完成", "超时", "超出费用上限", "已取消")


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _去掉说明字段(schema):
    """工作流输入 Schema 里的 title / description 是给人看的,校验器只认约束关键字。"""
    if isinstance(schema, dict):
        return {k: _去掉说明字段(v) for k, v in schema.items() if k not in ("title", "description", "default")}
    if isinstance(schema, list):
        return [_去掉说明字段(x) for x in schema]
    return schema


def 题的输入(样本):
    """冻结题 → 这道题喂给工作流的输入。只认 content.输入(一个对象);没有就是这道题不能拿来评工作流。"""
    内容 = (样本 or {}).get("content") or {}
    if isinstance(内容, str):
        try:
            内容 = json.loads(内容)
        except ValueError:
            return None
    x = 内容.get("输入") if isinstance(内容, dict) else None
    return x if isinstance(x, dict) else None


def 派发前检查(题们, 版本们, 轮数):
    """返回 field_errors(空 = 能派)。**一个模型都还没调的时候把能查的全查了** —— 派出去再红,钱已经花了。"""
    import tool_gateway as TG
    坏 = {}
    if not 题们:
        坏["数据集版本"] = "这一版冻结题集是空的 —— 空集合上「全过」恒成立,派出去什么都证明不了"
    次数 = len(题们) * len(边们) * 轮数
    if 次数 > 派发上限:
        坏["数据集版本"] = (f"要派 {len(题们)} 题 × 2 边 × {轮数} 轮 = {次数} 次运行,超过一次评测的上限 {派发上限} —— "
                        f"冻一版小一点的题集,或者分几次评")
    for 边, v in 版本们.items():
        人工 = [n.get("id") for n in (v.get("nodes") or []) if n.get("type") == "human"]
        if 人工:
            坏[边 + "版本"] = (f"这一版有人工核对步骤({'、'.join(map(str, 人工))})—— 评测**不往真人的待办里塞单**:"
                            f"一道题要跑好几遍,每遍都会在核对人那里挂一条;这一版评不了带人工核对的流程")
        sch = _去掉说明字段(v.get("input_schema") or {})
        for i, 题 in enumerate(题们):
            x = 题的输入(题)
            号 = 题.get("id") or 题.get("sample_id") or f"第{i + 1}题"
            if x is None:
                坏[f"题[{号}]"] = ("这道题没有工作流输入(content.输入)—— 冻结题集里的题要按这条工作流的输入格式写好,"
                                f"才能拿来评工作流;聊天记录形状的题是给聊天助手评的")
                continue
            错 = TG.校验Schema(x, sch)
            if 错:
                坏[f"题[{号}].{边}"] = f"这道题的输入不合{边}那一版的输入格式:{'; '.join(错)[:300]}"
    return 坏


def 派(c, me, project_id, eid, 版本们, 题们, 轮数):
    """建评测那个事务里调。版本们 = {"候选": workflow_versions 行, "基线": 行}。返回回执条数。"""
    import workflows_api as WA
    n = 0
    for 题 in 题们:
        sid = 题.get("id") or 题.get("sample_id")
        输入 = 题的输入(题)
        for 边 in 边们:
            v = 版本们[边]
            定义 = {"definition_schema_version": v["definition_schema_version"], "kind": "workflow",
                    "nodes": v["nodes"], "edges": v["edges"],
                    "input_schema": v["input_schema"], "output_schema": v["output_schema"]}
            for 轮 in range(1, 轮数 + 1):
                来源 = {"kind": "workflow_version", "id": v["workflow_id"], "version_id": v["id"],
                        "version_no": v["version_no"], "跑法": "评测",
                        "评测": {"id": eid, "题": sid, "边": 边, "轮": 轮}}
                受 = WA._受理运行(c, me, project_id, 定义, 来源, 输入, f"{eid}:{sid}:{边}:{轮}")
                c.execute(text("""insert into evaluation_runs
                    (id, organization_id, project_id, evaluation_id, sample_id, variant_code, round_no,
                     workflow_version_id, execution_run_id, job_id, created_at, created_by, updated_at, revision)
                    values (:i, :o, :p, :e, :s, :b, :r, :v, :x, :j, now(), :u, now(), 1)"""),
                          {"i": _新id("evr"), "o": me.org_id, "p": project_id, "e": eid, "s": sid, "b": 边,
                           "r": 轮, "v": v["id"], "x": 受["resource_id"], "j": 受["job_id"], "u": me.user_id})
                n += 1
    return n


def _子运行们(c, project_id, eid):
    return [dict(x) for x in c.execute(text("""
        select er.id rid, er.sample_id, er.variant_code, er.round_no, er.execution_run_id, er.job_id, er.collected_at,
               x.status, x.ended_at, x.output_ref, x.trace_id, x.completion_reason,
               -- 开始的证据取**任务**那一层:execution_runs.started_at 从来没人写(11-05 查:一天 700 多条全空)。
               -- worker 领走任务(attempts > 0)才算开始;排上队不算(C17)。执行者 = 领走它的那个 worker
               coalesce((select min(e.at) from job_events e where e.project_id=j.project_id and e.job_id=j.id and e.kind='开始'),
                        case when j.attempts > 0 then j.heartbeat_at end) started_at,
               greatest(x.updated_at, j.heartbeat_at) updated_at, j.attempts 尝试次数,
               -- 执行者:任务收尾时 lease_owner 会被清掉,所以先取「开始」那条事件里记的 worker,还在跑的才看 lease_owner
               coalesce((select e.payload->>'worker' from job_events e where e.project_id=j.project_id and e.job_id=j.id
                          and e.kind='开始' order by e.at desc limit 1), j.lease_owner) 执行者,
               (select coalesce(sum(u.amount) filter (where u.amount_known), 0) from usage_ledger u
                 where u.project_id=x.project_id and u.trace_id=x.trace_id) 费用,
               (select count(*) filter (where not u.amount_known) from usage_ledger u
                 where u.project_id=x.project_id and u.trace_id=x.trace_id) 算不出笔数
          from evaluation_runs er
          join execution_runs x on x.project_id=er.project_id and x.id=er.execution_run_id
          left join jobs j on j.project_id=er.project_id and j.id=er.job_id
         where er.project_id=:p and er.evaluation_id=:e
         order by er.sample_id, er.variant_code, er.round_no"""), {"p": project_id, "e": eid}).mappings()]


def _收一条(c, ev, 子):
    """子运行到了终态 → 逐题结果 + 「跑通」分 + 回执标已收。同一事务。"""
    输出 = 子["output_ref"]
    try:
        输出 = json.loads(输出) if isinstance(输出, str) else 输出
    except ValueError:
        pass
    iid = _新id("ei")
    c.execute(text("""insert into evaluation_items
        (id, organization_id, project_id, evaluation_id, sample_id, raw_output, trace_id, finished_at,
         variant_code, round_no, execution_run_id, created_at, created_by)
        values (:i, :o, :p, :e, :s, cast(:r as jsonb), :t, :f, :b, :n, :x, now(), 'eval-collector')"""),
              {"i": iid, "o": ev["organization_id"], "p": ev["project_id"], "e": ev["id"], "s": 子["sample_id"],
               "r": json.dumps({"运行状态": 子["status"], "完成原因": 子["completion_reason"], "输出": 输出},
                               ensure_ascii=False, default=str),
               "t": 子["trace_id"], "f": 子["ended_at"], "b": 子["variant_code"], "n": 子["round_no"],
               "x": 子["execution_run_id"]})
    c.execute(text("""insert into scores
        (id, organization_id, project_id, evaluation_item_id, dimension, value, value_known, source,
         scorer_version, rationale, by, at, created_at, created_by)
        values (:i, :o, :p, :it, '跑通', :v, true, '确定性规则', :sv, :ra, 'eval-collector', now(), now(), 'eval-collector')"""),
              {"i": _新id("sc"), "o": ev["organization_id"], "p": ev["project_id"], "it": iid,
               "v": 1 if 子["status"] == "succeeded" else 0, "sv": ev["scorer_version"],
               "ra": f"子运行终态 {子['status']}" + (f"({子['completion_reason']})" if 子["completion_reason"] else "")})
    c.execute(text("""update evaluation_runs set collected_at=now(), updated_at=now(), revision=revision+1
                       where project_id=:p and id=:i"""), {"p": ev["project_id"], "i": 子["rid"]})


def _取消没跑完的(c, ev, 子们):
    import runctl as RC
    取消了 = 0
    for 子 in 子们:
        if 子["status"] in 终态们:
            continue
        r = c.execute(text("select * from execution_runs where project_id=:p and id=:i for update"),
                      {"p": ev["project_id"], "i": 子["execution_run_id"]}).mappings().first()
        if r and r["status"] not in 终态们:
            RC.取消一次(c, ev["project_id"], r["id"], r, r["revision"], 谁="eval-collector")
            取消了 += 1
    return 取消了


def _落终态(c, ev, 状态, 原因, 细节):
    c.execute(text("""update evaluations set status=:s, end_reason_code=:r, end_detail=cast(:d as jsonb),
                             ended_at=now(), updated_at=now(), revision=revision+1
                       where project_id=:p and id=:i"""),
              {"s": 状态, "r": 原因, "d": json.dumps(细节, ensure_ascii=False, default=str),
               "p": ev["project_id"], "i": ev["id"]})


def 收一次(c, ev, 现在):
    """收一次评测。ev 是已锁住的 evaluations 行。返回一句人话(没变化返回 None)。"""
    子们 = _子运行们(c, ev["project_id"], ev["id"])
    if not 子们:
        _落终态(c, ev, "已取消", "NO_DISPATCH", {"说明": "后台派发的评测却一条回执都没有 —— 派发那一步没写进去,这是 bug"})
        return f"{ev['id']}:没有回执 → 已取消(派发漏写,要查)"
    收了 = 0
    for 子 in 子们:
        if 子["status"] in 终态们 and not 子["collected_at"]:
            _收一条(c, ev, 子)
            子["collected_at"] = 现在
            收了 += 1
    开始了 = [子["started_at"] for 子 in 子们 if 子["started_at"]]
    心跳 = max([子["updated_at"] for 子 in 子们 if 子["updated_at"]], default=None)
    if 开始了 and ev["status"] == "已派发":
        c.execute(text("""update evaluations set status='执行中', started_at=:s, updated_at=now(), revision=revision+1
                           where project_id=:p and id=:i"""), {"s": min(开始了), "p": ev["project_id"], "i": ev["id"]})
    if 心跳:
        c.execute(text("update evaluations set heartbeat_at=:h where project_id=:p and id=:i"),
                  {"h": 心跳, "p": ev["project_id"], "i": ev["id"]})
    费用 = sum(float(子["费用"] or 0) for 子 in 子们)
    算不出 = sum(int(子["算不出笔数"] or 0) for 子 in 子们)
    未完 = [子 for 子 in 子们 if 子["status"] not in 终态们]
    摘要 = {"共派": len(子们), "已收": sum(1 for 子 in 子们 if 子["collected_at"]), "没跑完": len(未完),
            "已知费用": round(费用, 6), "算不出金额的笔数": 算不出}
    if 费用 > float(ev["cost_cap_amount"]):
        摘要["取消了"] = _取消没跑完的(c, ev, 子们)
        _落终态(c, ev, "超出费用上限", "COST_CAP_EXCEEDED",
                dict(摘要, 说明=f"已知费用 {round(费用, 6)} 超过上限 {ev['cost_cap_amount']} —— 没跑完的已取消,已收的结果留着"))
        return f"{ev['id']}:超出费用上限 → 停了"
    if 未完 and 现在 >= ev["deadline_at"]:
        摘要["取消了"] = _取消没跑完的(c, ev, 子们)
        摘要["没跑完的状态"] = sorted({子["status"] for 子 in 未完})
        _落终态(c, ev, "超时", "TIMEOUT",
                dict(摘要, 说明=f"到了截止时间还有 {len(未完)} 次没跑完(状态:{'、'.join(摘要['没跑完的状态'])})—— 已取消,已收的结果留着"))
        return f"{ev['id']}:超时 → 停了"
    if not 未完:
        # 取消动作刚做完的那批,下一遍才会是终态 —— 这里只在全部终态且全收了才收尾
        _落终态(c, ev, "已完成", "ALL_COLLECTED", dict(摘要, 说明="每一次派发都收回了结果(成功或失败都算收回)"))
        return f"{ev['id']}:全部收齐 → 已完成"
    return f"{ev['id']}:收了 {收了} 条" if 收了 else None


def 收一遍(项目=None, 现在=None):
    """worker 60 秒那段调。**一条评测收挂了不拖垮别的**;两个 worker 同时扫,skip locked 保证一条只被一个收。"""
    from db import 事务
    现在 = 现在 or datetime.now(timezone.utc)
    话 = []
    with 事务() as c:
        ids = [tuple(x) for x in c.execute(text("""
            select project_id, id from evaluations
             where executor_code='后台派发' and status in ('已派发', '执行中') and archived_at is null
               and (cast(:p as text) is null or project_id=:p)
             order by dispatched_at"""), {"p": 项目})]
    for p, i in ids:
        try:
            with 事务() as c:
                ev = c.execute(text("""select * from evaluations where project_id=:p and id=:i
                                         and status in ('已派发', '执行中') for update skip locked"""),
                               {"p": p, "i": i}).mappings().first()
                if ev:
                    x = 收一次(c, dict(ev), 现在)
                    if x:
                        话.append(x)
        except Exception as e:
            话.append(f"⚠️ 收评测 {i} 出错了,下一分钟再收:{type(e).__name__}: {str(e)[:200]}")
    return 话
