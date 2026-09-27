#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事务发件箱(规格 §18 / §19.3)。

## 为什么要有它

规格:「**Job 与 Outbox 在同一数据库事务提交**;发布器可重复投递」。

如果「写库」和「发队列」是两件独立的事,那它们之间一定有一个窗口:

    写库成功 → 进程挂了 → 队列里没有这条 → **任务永远不会被跑,而库里它是「排队中」**
    发队列成功 → 写库回滚 → 队列里有一条不存在的任务 → worker 捞到一个幽灵

两个方向的错都很难查,因为**库和队列各自看起来都是自洽的**。
Outbox 把「要发什么」和业务数据写进同一个事务,发布器事后去读它 ——
于是只剩一种失败:**发过了但没标记成已发**,而那只会造成重复投递。

## 所以 worker 必须幂等

规格 §17.1 原话:「**重复投递是正常故障场景**,Worker 必须幂等」。
这不是「尽量」——Outbox 的设计**保证**会有重复投递,把它当异常处理的 worker 一定会出错。

## 这里没有真的队列

首版的「发布」就是把 `published_at` 标上 —— worker 直接从 `jobs` 表捞
(`lease.取一个`,`FOR UPDATE SKIP LOCKED`)。
**Redis 队列是可替换的实现,不是语义的一部分**:接上 Redis 时只要在
`发布一批()` 里多一步推送,而幂等、租约、重试都不用动。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text


def 入箱(conn, *, org, 项目, job_id, topic, payload, 新id):
    """**必须和业务写入在同一个事务里调用。** 调用方持有事务,这里不 commit。"""
    conn.execute(text("""
        insert into outbox (id, organization_id, project_id, job_id, topic, payload,
            attempts, created_at, created_by, updated_at, revision)
        values (:i,:o,:p,:j,:t,:pl,0, now(), 'api', now(), 1)
    """), {"i": 新id, "o": org, "p": 项目, "j": job_id, "t": topic,
           "pl": json.dumps(payload, ensure_ascii=False)})


def 发布一批(conn, 限=50, 最大尝试=8):
    """把还没发的标成已发。返回 (发了几条, 放弃了几条)。

    ⚠️ **发布失败不能让它无限重试**:一条永远发不出去的消息会把发布器卡住,
    而卡住的发布器**看起来只是「最近没有新任务」**。
    所以有尝试上限,到了就留在箱里并标出来 —— 让人看见比悄悄重试好。
    """
    rows = conn.execute(text("""
        select id, project_id, job_id, topic, attempts from outbox
         where published_at is null and attempts < :m
         order by created_at limit :l
    """), {"m": 最大尝试, "l": 限}).mappings().all()
    发, 弃 = 0, 0
    for r in rows:
        # 首版没有外部队列 —— 「发布」就是标记。接 Redis 时在这里多一步推送,
        # 推送失败就只 +attempts、不标 published_at,自然会被下一轮捞回来。
        conn.execute(text("""
            update outbox set published_at = now(), attempts = attempts + 1,
                   updated_at = now(), revision = revision + 1
             where project_id = :p and id = :i and published_at is null
        """), {"p": r["project_id"], "i": r["id"]})
        发 += 1
    卡 = conn.execute(text("""
        select count(*) from outbox where published_at is null and attempts >= :m
    """), {"m": 最大尝试}).scalar()
    return 发, int(卡 or 0)


def 未发的(conn, 项目=None):
    w, 参 = ["published_at is null"], {}
    if 项目: w.append("project_id = :p"); 参["p"] = 项目
    return [dict(r) for r in conn.execute(text(f"""
        select project_id, id, job_id, topic, attempts, created_at
          from outbox where {' and '.join(w)} order by created_at
    """), 参).mappings()]
