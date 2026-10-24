#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""挂起的运行 → 重新排队接着跑(2026-10-24,音频整理那条流程)。

两个地方会叫它:人工核对有了决定(human_api)、澜绣回执了一张桥请求(bridge_api)。
**只有一个排法**,两边都调这里 —— 两份排队代码迟早分叉,而分叉时两边各自都是绿的。

## 三条在这里成立的规矩

① **只认挂起态**:运行必须正停在 waiting_approval / waiting_external。
   已经排上、已经跑完、被取消了 —— 一律不排,返回 None 并说为什么。
   重复回执、两个人前后点批准,都会走到这儿第二次,**第二次不能再排一个任务**。
② **Job + Outbox 同一个事务**(和发起运行同一条理由):写库成功但没发出去,
   这次运行就永远挂在「排队中」,而库里看起来一切正常。
③ **恢复任务的幂等键是 (运行, 停着的那一步, 第几次挂起)** —— 同一次挂起只排一个恢复。
"""
import json
import uuid

from sqlalchemy import text

import outbox as OB

挂起态 = ("waiting_approval", "waiting_external")


def _新id(前缀名):
    return f"{前缀名}_{uuid.uuid4().hex[:12]}"


def 排恢复(c, *, project_id, run_id, 为什么, 谁):
    """在调用方的事务里把一次挂起的运行排回队列。返回 job_id;不该排时返回 (None, 理由)。"""
    r = c.execute(text("""select organization_id, status, resume_snapshot, checkpoint_seq
                            from execution_runs where project_id=:p and id=:i for update"""),
                  {"p": project_id, "i": run_id}).mappings().first()
    if not r:
        return None, "没有这次运行"
    if r["status"] not in 挂起态:
        return None, f"这次运行现在是「{r['status']}」,不在挂起中 —— 不重复排"
    快照 = r["resume_snapshot"] or {}
    停在 = 快照.get("从")
    if not 停在:
        return None, "这次运行没有检查点 —— 不知道从哪一步接着跑,不猜"
    第几次 = int(r["checkpoint_seq"] or 0)
    键 = f"resume:{run_id}:{停在}:{第几次}"
    老 = c.execute(text("select id from jobs where project_id=:p and idempotency_key=:k"),
                   {"p": project_id, "k": 键}).scalar()
    if 老:
        return 老, "这次挂起已经排过恢复了"
    job = _新id("job")
    org = r["organization_id"]
    c.execute(text("""update execution_runs set status='queued', updated_at=now(),
                             revision=revision+1
                       where project_id=:p and id=:i"""), {"p": project_id, "i": run_id})
    c.execute(text("""
        insert into jobs (id, organization_id, project_id, type, target_ref, status,
            attempts, max_attempts, snapshot_hash, idempotency_key,
            created_at, created_by, updated_at, revision)
        values (:i,:o,:p,'workflow_run',:t,'排队中',0,3,:sh,:k, now(), :u, now(), 1)
    """), {"i": job, "o": org, "p": project_id,
           "t": json.dumps({"run_id": run_id, "恢复": True, "停在": 停在}, ensure_ascii=False),
           "sh": 快照.get("逻辑哈希"), "k": 键, "u": 谁})
    c.execute(text("""
        insert into job_events (id, organization_id, project_id, job_id, seq, kind,
            payload, at, created_at, created_by)
        values (:i,:o,:p,:j,1,'已受理',:pl, now(), now(), :u)
    """), {"i": _新id("je"), "o": org, "p": project_id, "j": job,
           "pl": json.dumps({"阶段": "排队", "说明": f"恢复:{为什么}"}, ensure_ascii=False),
           "u": 谁})
    OB.入箱(c, org=org, 项目=project_id, job_id=job, topic="workflow_run",
           payload={"run_id": run_id}, 新id=_新id("ob"))
    return job, f"已排恢复(从 {停在} 接着跑)"
