#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""孤儿运行(W06):后台任务全结束、没待办、没待回执,而运行还停在 running → incomplete / orphaned。

判据在 `runtime/卡住判定.判孤儿`(纯函数,只看事实不碰库);这里只做三件事:取数、调判据、照状态机落终态。

两个调用方,**取数 SQL 和落库只写这一份**:
  · `tools/stale_sweep.py` —— 人跑,默认只报,加 `--做` 才改(它还管另外两档 72 小时的)
  · `workers/worker.py` —— 11-16 起每 60 秒自己扫一遍(`扫孤儿`),监测页「在跑」不再挂着假数等人来清

> 一条「还在跑」的运行,和一条「后台任务都结束了、没人会再推」的运行,**在监测页上长得一模一样** ——
> 11-12 体检那批 122 条「正在跑」就是这么攒出来的。

⚠️ 终态走 `contract/states.能不能走()`,不直接 UPDATE(理由见 stale_sweep 文件头)。
⚠️ `扫孤儿` 出错只回话、不抛 —— 扫挂了不许把 worker 一起带走(和 `扫定时` 同一条规矩)。
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "runtime"), os.path.join(HERE, "contract")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from sqlalchemy import text  # noqa: E402
import 卡住判定 as SJ  # noqa: E402
import states as ST  # noqa: E402


def 找孤儿(c, 现在, 项目=None):
    """→ (看了几条 running, 要改 [(run_id, project_id, organization_id, 为什么)], 判不了 [(run_id, 说)])。
    「看了 0 条」= 现在没有在跑的运行,不是没扫 —— 调用方要把这个数印出来。"""
    条件 = " and r.project_id=:proj" if 项目 else ""
    rows = c.execute(text(f"""
        select r.id, r.status, r.project_id, r.organization_id,
               array_remove(array_agg(j.status), null) 任务状态们,
               max(coalesce(j.updated_at, j.created_at)) 最后任务结束,
               exists(select 1 from human_requests h where h.project_id=r.project_id
                      and h.execution_run_id=r.id and h.status='pending') 有待人工,
               exists(select 1 from bridge_calls b where b.project_id=r.project_id
                      and b.execution_run_id=r.id and b.status='待执行') 有待桥
          from execution_runs r
          left join jobs j on j.project_id=r.project_id and j.target_ref->>'run_id'=r.id
         where r.status='running'{条件}
         group by r.id, r.status, r.project_id, r.organization_id"""),
                    {"proj": 项目} if 项目 else {}).mappings().all()
    要改, 判不了 = [], []
    for r in rows:
        try:
            档, 为 = SJ.判孤儿(状态=r["status"], 任务状态们=list(r["任务状态们"] or []), 最后任务结束=r["最后任务结束"],
                             有待人工=r["有待人工"], 有待桥=r["有待桥"], 现在=现在)
        except SJ.判不了 as e:
            判不了.append((r["id"], str(e)))
            continue
        if 档 == SJ.可标incomplete:
            要改.append((r["id"], r["project_id"], r["organization_id"], 为))
    return len(rows), 要改, 判不了


def 推孤儿(c, 条, 我是谁):
    """一条 running → incomplete(completion_reason=orphaned),走状态机校验,并记一条 run.orphaned 事件。
    → 改了几行(0 = 状态机不给这条路,或这一瞬间已经被别人改走了)。"""
    rid, proj, org, 为 = 条
    if not ST.能不能走("execution_run", "running", "incomplete"):
        return 0
    n = c.execute(text("""update execution_runs
                             set status='incomplete', completion_reason='orphaned', ended_at=now(),
                                 updated_at=now(), revision=revision+1
                           where project_id=:p and id=:i and status='running'"""), {"p": proj, "i": rid}).rowcount
    if n:
        seq = c.execute(text("select coalesce(max(seq), 1) + 1 from run_events where project_id=:p and execution_run_id=:r"),
                        {"p": proj, "r": rid}).scalar()
        c.execute(text("""insert into run_events (id, organization_id, project_id, execution_run_id, seq,
                              event_type, payload, occurred_at, created_at, created_by)
                          values (:i, :o, :p, :r, :s, 'run.orphaned', cast(:pl as jsonb), now(), now(), :u)"""),
                  {"i": "re_" + uuid.uuid4().hex[:16], "o": org, "p": proj, "r": rid, "s": seq, "u": 我是谁,
                   "pl": json.dumps({"为什么": 为,
                                    "说明": "后台任务都结束了,没有待办也没有待回执 —— 没人会再推这次运行,标成未完成;要补就重新发起"},
                                   ensure_ascii=False)})
    return n


def 扫孤儿(现在=None, 我是谁="worker", 项目=None):
    """worker 每 60 秒调一次 → 这一遍做了什么(给日志;空 = 没动)。出错只回话、不抛。"""
    try:
        from db import 事务
        现在 = 现在 or datetime.now(timezone.utc)
        with 事务() as c:
            看了, 要改, 判不了 = 找孤儿(c, 现在, 项目)
            改了 = [x[0] for x in 要改 if 推孤儿(c, x, 我是谁)]
        话 = [f"{rid} 标成未完成(orphaned):后台任务全结束、没人会再推" for rid in 改了]
        话 += [f"⚠️ {rid} 判不了:{说[:120]}" for rid, 说 in 判不了]
        return 话
    except Exception as e:      # noqa: BLE001 —— 扫挂了不许把 worker 一起带走
        return [f"⚠️ 这一遍扫孤儿运行出错了,下一分钟再扫:{type(e).__name__}: {str(e)[:200]}"]
