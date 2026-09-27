#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务事件:**按 job 内单调递增的 seq**,SSE 断线后从 seq 续(规格 §19.2/§19.3)。

## 为什么必须有 seq,而且必须在 job 内单调

规格 §18:「事件**有序、可重放**」;§19.2:「SSE,**实时结果重新鉴权**」。

前端断线重连之后要接着看。如果没有 seq:
  · 从头重放 → 用户看到一串已经看过的进度,而且分不清哪些是新的
  · 直接跳到最新 → **中间那几条永远看不到**,而失败原因往往就在中间那一条

⚠️ 用时间戳当游标不行:同一毫秒可以有两条,而**跳过一条和没有那一条长得一样**。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text


def 记一条(conn, *, org, 项目, job_id, kind, payload, 新id):
    """seq 由数据库现算(`max+1`),**在同一个事务里**,靠 (job_id, seq) 的唯一约束兜底。

    ⚠️ 不用 Python 侧的计数器:两个 worker 同时写同一条 job 的事件时,
    Python 侧算出来的 seq 会撞 —— 而撞了之后唯一约束会报错,那是**对的**:
    报错比两条事件共用一个 seq 好,因为共用 seq 之后 SSE 续传会丢一条。
    """
    conn.execute(text("""
        insert into job_events (id, organization_id, project_id, job_id, seq, kind,
            payload, at, created_at, created_by)
        select :i, :o, :p, :j,
               coalesce((select max(seq) from job_events
                          where project_id=:p and job_id=:j), 0) + 1,
               :k, :pl, now(), now(), 'worker'
    """), {"i": 新id, "o": org, "p": 项目, "j": job_id, "k": kind,
           "pl": json.dumps(payload, ensure_ascii=False)})


def 读(conn, 项目, job_id, 从seq=0, 限=200):
    """**从某个 seq 之后**读 —— 断线重连传上次收到的最后一个 seq。"""
    return [dict(r) for r in conn.execute(text("""
        select seq, kind, payload, at from job_events
         where project_id=:p and job_id=:j and seq > :s
         order by seq limit :l
    """), {"p": 项目, "j": job_id, "s": int(从seq), "l": 限}).mappings()]


def 有没有断号(conn, 项目, job_id):
    """seq 该是 1..N 连续的。断号说明有事件没写进来 ——
    **而「少了一条事件」和「本来就没有那一步」在界面上长得一样。**"""
    rs = [r[0] for r in conn.execute(text("""
        select seq from job_events where project_id=:p and job_id=:j order by seq
    """), {"p": 项目, "j": job_id})]
    缺 = [i for i in range(1, (rs[-1] if rs else 0) + 1) if i not in set(rs)]
    return 缺
