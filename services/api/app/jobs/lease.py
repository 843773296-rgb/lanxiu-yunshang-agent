#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务租约与状态流转(规格 §19.3)。

## 租约和心跳是**两件事**

    租约(lease_until / lease_owner)   管「**谁有权改它**」
    心跳(heartbeat_at)                管「**它还活着吗**」

只有租约的话:一个卡死但租约没到期的 worker 会让任务看起来正常 ——
而「正在跑」和「卡住了」在状态上长得一模一样。
只有心跳的话:两个 worker 能同时改同一条,而它们各写各的,最后谁赢看时序。

## 取租约用**条件更新**,不是「先查再写」

    UPDATE jobs SET lease_owner=:我 ... WHERE id=:i AND (租约空了 或 已过期)

「先 SELECT 看看有没有人占,再 UPDATE 占上」中间有窗口,两个 worker 会同时通过检查。
条件更新把检查和占用放进**同一条语句**,由数据库保证只有一个 rowcount=1。

**这条必须被攻击过。** 见 `tests/integration/test_worker_lease.py`:
两个 worker 抢同一条,断言恰好一个拿到 —— 不是读代码觉得对。

## 完成也用条件更新

    UPDATE ... WHERE id=:i AND lease_owner=:我 AND status='执行中'

租约过期之后**我就不该再写结果了** —— 那时候可能已经有别人在跑。
一个「我跑完了所以我写结果」的 worker 会覆盖接手者的进度,
而两份结果里哪一份对,事后看不出来。
"""
import datetime as dt
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "contract"))
from sqlalchemy import text
import states as ST

租约秒 = int(os.environ.get("JOB_LEASE_SECONDS", "60"))
心跳秒 = int(os.environ.get("JOB_HEARTBEAT_SECONDS", "15"))


# ── 错误分类:**哪些不许盲重试**(§19.3)──────────────────────────────
#
# 规格原话:「格式错误、权限不足、预算禁止**不盲重试**」。
# 为什么要写成一张表而不是 try/except 里就地判断:
# **「该不该重试」是个会被反复用到的判断**(worker 里、任务详情页上、
# 「基于此配置重试」那个按钮上),散在三处就会有三种说法。
不许重试 = {
    "VALIDATION":  "输入不合格 —— 重试同一份输入必然同样失败,只是在烧钱和占位",
    "FORBIDDEN":   "权限不足 —— 权限不会因为多试一次而变",
    "BUDGET":      "预算禁止 —— 重试只会把额度耗在同一个拒绝上",
    "NOT_FOUND":   "引用的对象不存在 —— 它不会自己出现",
    "INCOMPATIBLE": "模型/适配器组合不兼容 —— 那是配置问题,不是瞬时故障",
}
可以重试 = {
    "TIMEOUT":     "超时 —— 但**如果对方可能已经成功且不可查**,走「待人工核实」而不是重试",
    "RATE_LIMIT":  "被限流 —— 退避之后可以再来",
    "UPSTREAM_5XX": "上游服务端错误",
    "TRANSIENT":   "瞬时故障(连接重置、DNS 抖动)",
}


def 该重试吗(error_code, attempts, max_attempts):
    """返回 (要不要重试, 一句人话)。**认不出的错误码不重试** ——
    未知不等于瞬时故障,而把未知当瞬时故障会让一个必然失败的任务重复烧钱。"""
    if error_code in 不许重试:
        return False, f"不重试:{不许重试[error_code]}"
    if attempts >= max_attempts:
        return False, (f"已经试了 {attempts} 次,到上限 {max_attempts} —— 停下,"
                       f"**让人看一眼比再试一次有用**")
    if error_code in 可以重试:
        return True, f"可以重试:{可以重试[error_code]}"
    return False, (f"错误码 {error_code!r} 没登记过 —— **认不出就不重试**。"
                   f"未知不等于瞬时故障,而把未知当瞬时故障会让必然失败的任务反复烧钱。"
                   f"要重试就先把它登记进 lease.可以重试 / 不许重试")


def 退避秒(attempts, 基=2.0, 上限=300.0):
    """指数退避 + **抖动**(§19.3)。

    ⚠️ 抖动不是锦上添花:没有抖动的话,同一批一起失败的任务会在同一时刻
    一起重试 —— **它们本来就是被同一个故障打倒的,于是又一起打过去**。
    """
    基础 = min(上限, 基 ** min(attempts, 10))
    return 基础 * (0.5 + random.random())          # 全抖动:落在 [0.5, 1.5) 倍


# ── 租约 ────────────────────────────────────────────────────────────
def 取一个(conn, 我是谁, 类型=None, 项目=None):
    """抢一条可跑的任务。**一条 UPDATE 完成「挑 + 占」**。

    `FOR UPDATE SKIP LOCKED` 让并发的 worker 各挑不同的行,而不是排队等同一行。
    """
    条件 = ["status in ('排队中','执行中')",
            "(lease_until is null or lease_until < now())",
            "(next_retry_at is null or next_retry_at <= now())",
            "cancel_requested is not true",
            "needs_human_check is not true"]
    参 = {"me": 我是谁, "lease": 租约秒}
    if 类型: 条件.append("type = :t"); 参["t"] = 类型
    if 项目: 条件.append("project_id = :p"); 参["p"] = 项目
    r = conn.execute(text(f"""
        with 候选 as (
            select organization_id, project_id, id from jobs
             where {' and '.join(条件)}
             order by created_at
             limit 1
             for update skip locked
        )
        update jobs j
           set lease_owner = :me,
               lease_until = now() + (:lease || ' seconds')::interval,
               heartbeat_at = now(),
               status = '执行中',
               attempts = j.attempts + 1,
               updated_at = now(),
               revision = j.revision + 1
          from 候选 c
         where j.project_id = c.project_id and j.id = c.id
        returning j.id, j.project_id, j.organization_id, j.type, j.target_ref,
                  j.attempts, j.max_attempts, j.snapshot_hash, j.stage
    """), 参).mappings().first()
    return dict(r) if r else None


def 续租(conn, 项目, job_id, 我是谁, 阶段=None, 已处理=None):
    """心跳 + 续租。**只有还持着租约的人才续得上** ——
    租约过期之后别人可能已经接手,这时候续租成功会变成两个人同时持有。

    返回 (续上了吗, 有人请求取消吗)。**取消请求顺便一起读回来** ——
    分两次查的话,worker 要么多一次往返,要么就干脆不查了。
    """
    r = conn.execute(text("""
        update jobs
           set lease_until = now() + (:lease || ' seconds')::interval,
               heartbeat_at = now(),
               stage = coalesce(:st, stage),
               processed_count = coalesce(:pc, processed_count),
               updated_at = now(), revision = revision + 1
         where project_id = :p and id = :i
           and lease_owner = :me and status = '执行中'
        returning cancel_requested
    """), {"lease": 租约秒, "p": 项目, "i": job_id, "me": 我是谁,
           "st": 阶段, "pc": 已处理}).first()
    if r is None:
        return False, False
    return True, bool(r[0])


def 收尾(conn, 项目, job_id, 我是谁, 到, *, error_code=None, error_detail=None,
        external_id=None, 待人工核实=False, 取消未生效原因=None):
    """把任务推到终态(或退回排队等重试)。**条件更新:只有持租约的人能写。**

    ⚠️ 状态流转问 `contract/states.py`,**这里不重写第二套** ——
    两套流转规则迟早有一处漏,而漏掉的那处在界面上看不出异常。
    """
    from_row = conn.execute(text(
        "select status, cancel_requested from jobs where project_id=:p and id=:i"),
        {"p": 项目, "i": job_id}).first()
    if from_row is None:
        return False, "没有这个任务"
    现 = from_row[0]
    if not ST.能不能走("job", 现, 到):
        return False, (f"不许从「{现}」走到「{到}」—— 状态机(contract/states.py)"
                       f"允许的是 {ST.找('job')['流转'].get(现, [])}")
    r = conn.execute(text("""
        update jobs
           set status = :到,
               error_code = :ec, error_detail = :ed,
               external_id = coalesce(:xid, external_id),
               needs_human_check = :hc,
               lease_owner = null, lease_until = null,
               updated_at = now(), revision = revision + 1
         where project_id = :p and id = :i and lease_owner = :me
        returning id
    """), {"到": 到, "ec": error_code,
           "ed": json.dumps(error_detail, ensure_ascii=False) if error_detail else None,
           "xid": external_id, "hc": bool(待人工核实),
           "p": 项目, "i": job_id, "me": 我是谁}).first()
    if r is None:
        # 租约已经不是我的了 —— **不覆盖**。规格 §11.5 的同一条道理:
        # 「我跑完了所以我写结果」会盖掉接手者的进度,而两份结果哪份对事后看不出来。
        return False, "租约已经不在你手上(过期或被接手)—— **不许覆盖别人的结果**"
    if 取消未生效原因:
        # 取消请求和自然完成并发:**保留真实终态,并记下取消为什么没生效**(§11.5)
        conn.execute(text("""
            update jobs set error_detail = coalesce(error_detail,'{}'::jsonb)
                   || jsonb_build_object('取消未生效原因', :r)
             where project_id=:p and id=:i"""),
            {"r": 取消未生效原因, "p": 项目, "i": job_id})
    return True, "好了"


def 退回重试(conn, 项目, job_id, 我是谁, error_code, error_detail=None):
    """失败且可重试:退回排队 + 排一个退避后的时间。"""
    row = conn.execute(text(
        "select attempts, max_attempts from jobs where project_id=:p and id=:i"),
        {"p": 项目, "i": job_id}).first()
    if row is None: return False, "没有这个任务"
    要, 话 = 该重试吗(error_code, row[0], row[1] or 3)
    if not 要:
        ok, 说 = 收尾(conn, 项目, job_id, 我是谁, "失败",
                     error_code=error_code, error_detail=error_detail)
        return ok, f"不重试了 → 失败。{话}"
    等 = 退避秒(row[0])
    r = conn.execute(text("""
        update jobs
           set status='排队中', stage=null,
               error_code=:ec, error_detail=:ed,
               next_retry_at = now() + (:s || ' seconds')::interval,
               lease_owner=null, lease_until=null,
               updated_at=now(), revision=revision+1
         where project_id=:p and id=:i and lease_owner=:me
        returning id"""),
        {"ec": error_code,
         "ed": json.dumps(error_detail, ensure_ascii=False) if error_detail else None,
         "s": 等, "p": 项目, "i": job_id, "me": 我是谁}).first()
    if r is None:
        return False, "租约已经不在你手上 —— 不许覆盖"
    return True, f"{话};{round(等,1)} 秒后再来(退避带抖动)"


def 捞回卡住的(conn, 项目=None, 心跳超时秒=None):
    """租约还没到期、但**心跳早停了**的任务 —— 这是「卡住」和「正在跑」的分界。

    ⚠️ 这个函数只**报**,不自动抢:抢过来可能和一个还活着但网络卡住的 worker 撞。
    规格 §19.3:「强制杀进程不能保证外部任务/费用立即停止」。
    """
    超 = 心跳超时秒 or (心跳秒 * 4)
    参 = {"s": 超}
    w = ["status='执行中'", "heartbeat_at < now() - (:s || ' seconds')::interval"]
    if 项目: w.append("project_id=:p"); 参["p"] = 项目
    return [dict(r) for r in conn.execute(text(f"""
        select project_id, id, type, lease_owner, heartbeat_at, lease_until,
               attempts, stage
          from jobs where {' and '.join(w)} order by heartbeat_at
    """), 参).mappings()]
