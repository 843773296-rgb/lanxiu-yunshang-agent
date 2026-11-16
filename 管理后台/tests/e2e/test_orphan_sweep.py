#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""孤儿运行自动收尾 · 端到端(W06 后半,11-16):worker 每 60 秒扫一遍,
后台任务全结束、没待办、没待回执而运行还停在 running → incomplete(completion_reason=orphaned)+ 一条 run.orphaned 事件。

真库上造(跑完还原,痕迹不留):拿三条已经成功、带后台任务的运行 ——
  甲:扳回 running,任务结束时间拨到 2 小时前           → **要被标**
  乙:扳回 running,一个任务改成还在跑                   → 🔑 不许动(还有活任务)
  丙:扳回 running,任务 5 分钟前才结束(宽限 30 分钟)   → 🔑 不许动(收尾可能还没写完)
再扫一遍 → 一条都不再动(幂等)。判据本身在 test_stale_judge 里逐条验过;这里验的是**接线**:
worker 那条路真的会把甲改掉、而且只改甲,改完有事件可查。

⚠️ 没凑齐三条样本 → 红(样本量不够不叫通过)。CI 里它排在 test_audio_flow 等之后,库里一定有成功的运行。
"""
import os
import sys
from datetime import datetime, timezone

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
from sqlalchemy import text  # noqa: E402
from db import 事务  # noqa: E402
import orphan_sweep as OS_  # noqa: E402

项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 运行(c, rid):
    return c.execute(text("select status, completion_reason, ended_at, revision from execution_runs where project_id=:p and id=:r"),
                     {"p": 项目, "r": rid}).mappings().first()


with 事务() as c:
    样本 = c.execute(text("""select r.id from execution_runs r
                             where r.project_id=:p and r.status='succeeded'
                               and exists(select 1 from jobs j where j.project_id=r.project_id and j.target_ref->>'run_id'=r.id)
                               and not exists(select 1 from human_requests h where h.project_id=r.project_id and h.execution_run_id=r.id and h.status='pending')
                               and not exists(select 1 from bridge_calls b where b.project_id=r.project_id and b.execution_run_id=r.id and b.status='待执行')
                             order by r.created_at desc limit 3"""), {"p": 项目}).scalars().all()
ck(f"夹具:库里有 3 条成功的、带后台任务的运行可借用(找到 {len(样本)} 条)", len(样本) == 3, 样本)
if len(样本) < 3:
    print("❌ 样本量不够 —— 这不叫通过");
    sys.exit(1)
甲, 乙, 丙 = 样本

原 = {}
with 事务() as c:
    for rid in 样本:
        原[rid] = dict(运行(c, rid))
        原[rid]["jobs"] = [dict(x) for x in c.execute(text(
            "select id, status, updated_at from jobs where project_id=:p and target_ref->>'run_id'=:r"), {"p": 项目, "r": rid}).mappings()]
try:
    with 事务() as c:
        for rid in 样本:
            c.execute(text("update execution_runs set status='running', ended_at=null, completion_reason=null where project_id=:p and id=:r"),
                      {"p": 项目, "r": rid})
        c.execute(text("update jobs set updated_at=now() - interval '2 hours' where project_id=:p and target_ref->>'run_id'=:r"), {"p": 项目, "r": 甲})
        c.execute(text("update jobs set updated_at=now() where project_id=:p and target_ref->>'run_id'=:r"), {"p": 项目, "r": 乙})
        一个 = 原[乙]["jobs"][0]["id"]
        c.execute(text("update jobs set status='running' where project_id=:p and id=:j"), {"p": 项目, "j": 一个})
        c.execute(text("update jobs set updated_at=now() - interval '5 minutes' where project_id=:p and target_ref->>'run_id'=:r"), {"p": 项目, "r": 丙})

    话 = OS_.扫孤儿(现在=datetime.now(timezone.utc), 我是谁="e2e-orphan")
    with 事务() as c:
        a, b, d = 运行(c, 甲), 运行(c, 乙), 运行(c, 丙)
        事件 = c.execute(text("select payload from run_events where project_id=:p and execution_run_id=:r and event_type='run.orphaned'"),
                       {"p": 项目, "r": 甲}).mappings().all()
    ck("甲(任务 2 小时前全结束)→ incomplete,completion_reason=orphaned,ended_at 填上",
       a["status"] == "incomplete" and a["completion_reason"] == "orphaned" and a["ended_at"] is not None, dict(a))
    ck("甲 记了一条 run.orphaned 事件,写清为什么、要补就重新发起",
       len(事件) == 1 and "重新发起" in (事件[0]["payload"] or {}).get("说明", ""), 事件)
    ck("扫的话里点名了甲", any(甲 in x for x in 话), 话)
    ck("🔑 乙(还有一个任务在跑)不许动,仍是 running", b["status"] == "running", dict(b))
    ck("🔑 丙(任务 5 分钟前才结束,宽限 30 分钟)不许动,仍是 running", d["status"] == "running", dict(d))
    话2 = OS_.扫孤儿(现在=datetime.now(timezone.utc), 我是谁="e2e-orphan")
    with 事务() as c:
        事件2 = c.execute(text("select count(*) from run_events where project_id=:p and execution_run_id=:r and event_type='run.orphaned'"),
                        {"p": 项目, "r": 甲}).scalar()
    ck("再扫一遍:甲不再被动、事件不多记(幂等)", not any(甲 in x for x in 话2) and 事件2 == 1, (话2, 事件2))
finally:
    with 事务() as c:
        for rid, o in 原.items():
            c.execute(text("update execution_runs set status=:s, completion_reason=:cr, ended_at=:e where project_id=:p and id=:r"),
                      {"p": 项目, "r": rid, "s": o["status"], "cr": o["completion_reason"], "e": o["ended_at"]})
            for j in o["jobs"]:
                c.execute(text("update jobs set status=:s, updated_at=:u where project_id=:p and id=:j"),
                          {"p": 项目, "j": j["id"], "s": j["status"], "u": j["updated_at"]})
        c.execute(text("delete from run_events where project_id=:p and event_type='run.orphaned' and created_by='e2e-orphan'"), {"p": 项目})
    with 事务() as c:
        还原 = all(运行(c, rid)["status"] == o["status"] for rid, o in 原.items())
    ck("跑完三条运行和它们的任务都还原了(痕迹不留)", 还原)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
