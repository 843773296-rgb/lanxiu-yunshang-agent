#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判运行记录(研判队列未做项第 2 项 · 用户 2026-10-18 拍:在智能运维平台自建、单条超时 2 分钟)。

原来研判在一次网页请求里同步逐条跑完才返回:没有运行号、没有进度,刷新就丢;
同一条在两个窗口各点一次会跑两遍、生成两条草稿、花两份钱(只拦了「已结束」,没拦「正在跑」)。

现在:
  · 提交 → 当场拿到批次号,每条一个运行号;**同一工单已有进行中的运行,就返回那一个**(库里唯一索引兜底,
    两个窗口同时点也只会有一条在跑);
  · 智能运维平台(8770)的执行线程逐条领、写阶段(排队 → 取数 → 调模型 → 落库 → 完成 / 失败 / 超时);
  · 页面按批次号轮询,看得到「前面还有几条」,刷新后凭批次号找回;
  · 单条调模型超过 2 分钟 → 记「超时」并给原因,页面给「转人工」—— 转人工的不再被自动挑去跑;
  · 执行线程每 5 秒报一次心跳。**跑到一半的,心跳断了就标「中断」,不会永远「进行中」**;
    还在排队的不动 —— 执行线程重新起来接着领,这就是「可恢复」。

⚠️ 这里的时间用**机器时钟**,不用 `ops.now()`(世界时间):心跳和超时量的是这台机器上的进程活没活着,
和演示数据的业务日期无关。两者混用的话,世界平移一次,所有心跳都会被判成「几天前」。
"""
import datetime as dt
import os
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

单条超时秒 = 120          # 用户 10-18 拍:平时约 30 秒,2 分钟没出结果算失败
心跳间隔秒 = 5
心跳断了秒 = 30           # 执行线程超过这么久没报心跳 → 认为它不在了
在跑 = ("排队", "取数", "调模型", "落库")
跑到一半 = ("取数", "调模型", "落库")
结束 = ("完成", "失败", "超时", "中断", "转人工")
可转人工 = ("失败", "超时", "中断")


def _库(db=None):
    import ops
    return db or ops.DB


def _现在():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")   # 真实时钟:心跳 / 超时量的是进程活没活着,和世界日期无关


def 确保表(c):
    c.execute("""CREATE TABLE IF NOT EXISTS triage_run(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch TEXT NOT NULL,          -- 一次提交一个批次号;页面凭它找回
        task_id TEXT NOT NULL,
        status TEXT NOT NULL,         -- 排队 / 取数 / 调模型 / 落库 / 完成 / 失败 / 超时 / 中断 / 转人工
        created TEXT, started TEXT, finished TEXT, stage_at TEXT,
        triage_id INTEGER, cost REAL, error TEXT,
        by_no TEXT, by_name TEXT, handoff_no TEXT)""")
    # 同一工单同时只许有一条在跑 —— 两个窗口同时点,第二个 INSERT 撞上这里,改成返回第一条
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_triage_run_active ON triage_run(task_id) "
              "WHERE status IN ('排队','取数','调模型','落库')")
    c.execute("CREATE INDEX IF NOT EXISTS ix_triage_run_batch ON triage_run(batch)")
    # 只有一行(id=1),靠写入那一处 `ON CONFLICT(id)` 保证 —— **不加 CHECK(id=1)**:
    # 假数据工厂会反射全库往每张表里灌造的行,CHECK 让它的自测当场崩(10-19 门禁抓到)
    c.execute("CREATE TABLE IF NOT EXISTS triage_worker(id INTEGER PRIMARY KEY, pid INT, beat TEXT)")


def _连(db=None):
    c = sqlite3.connect(_库(db), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def 提交(task_ids, me=None, db=None):
    """→ {batch, runs:[{task_id, run_id, 复用}]}。复用 = 这条已经在跑,没另起一份。"""
    import uuid
    批 = dt.datetime.now().strftime("%m%d%H%M%S-") + uuid.uuid4().hex[:6]   # 真实时钟:批次号只求不重,不是业务日期
    me = me or {}
    出 = []
    with closing(_连(db)) as c, c:
        确保表(c)
        for tid in dict.fromkeys(t for t in task_ids if t):       # 去重,保序
            旧 = c.execute("SELECT id FROM triage_run WHERE task_id=? AND status IN ('排队','取数','调模型','落库')",
                          (tid,)).fetchone()
            if 旧:
                出.append(dict(task_id=tid, run_id=旧["id"], 复用=True)); continue
            try:
                rid = c.execute("INSERT INTO triage_run(batch,task_id,status,created,stage_at,by_no,by_name) "
                                "VALUES(?,?,'排队',?,?,?,?)",
                                (批, tid, _现在(), _现在(), me.get("no"), me.get("name"))).lastrowid
                出.append(dict(task_id=tid, run_id=rid, 复用=False))
            except sqlite3.IntegrityError:                       # 另一个窗口刚好抢先插了
                旧 = c.execute("SELECT id FROM triage_run WHERE task_id=? AND status IN ('排队','取数','调模型','落库')",
                              (tid,)).fetchone()
                出.append(dict(task_id=tid, run_id=旧["id"] if 旧 else None, 复用=True))
    return dict(batch=批, runs=出)


def 心跳(pid, db=None):
    with closing(_连(db)) as c, c:
        确保表(c)
        c.execute("INSERT INTO triage_worker(id,pid,beat) VALUES(1,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET pid=excluded.pid, beat=excluded.beat", (pid, _现在()))


def 执行线程在吗(c, 当下=None):
    r = c.execute("SELECT beat FROM triage_worker WHERE id=1").fetchone()
    if not r or not r[0]:          # 按位置取:调用方的连接不一定设了 row_factory
        return False
    当下 = 当下 or dt.datetime.now()   # 真实时钟:和 _现在() 写进 beat 的是同一种钟,混用世界时间会把心跳判成几天前
    return (当下 - dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")).total_seconds() <= 心跳断了秒


def 收中断(当下=None, db=None, 原因=None):
    """跑到一半、而执行线程已经不在了的 → 标「中断」。排队的不动(执行线程回来接着领)。→ 标了几条。

    `原因` 给了就无条件收(执行线程刚起来时用:上一个进程跑到一半的那几条肯定没人管了)。"""
    with closing(_连(db)) as c, c:
        确保表(c)
        if 原因 is None:
            if 执行线程在吗(c, 当下):
                return 0
            原因 = "执行线程没在跑(服务重启或崩了)—— 这一条跑到一半断了,没有结果"
        ph = ",".join("?" * len(跑到一半))
        return c.execute(f"UPDATE triage_run SET status='中断', finished=?, error=? WHERE status IN ({ph})",
                         (_现在(), 原因, *跑到一半)).rowcount


def 领一条(db=None):
    """执行线程用:领最早排队的一条,标成「取数」。→ {run_id, task_id} 或 None。"""
    with closing(_连(db)) as c, c:
        确保表(c)
        while True:
            r = c.execute("SELECT id, task_id FROM triage_run WHERE status='排队' ORDER BY id LIMIT 1").fetchone()
            if not r:
                return None
            if c.execute("UPDATE triage_run SET status='取数', started=?, stage_at=? WHERE id=? AND status='排队'",
                         (_现在(), _现在(), r["id"])).rowcount:
                return dict(run_id=r["id"], task_id=r["task_id"])


def 标阶段(run_id, 阶段, db=None):
    assert 阶段 in 跑到一半, 阶段
    with closing(_连(db)) as c, c:
        c.execute(f"UPDATE triage_run SET status=?, stage_at=? WHERE id=? AND status IN ({','.join('?' * len(跑到一半))})",
                  (阶段, _现在(), run_id, *跑到一半))


def 收尾(run_id, 结果, triage_id=None, cost=None, error=None, db=None):
    """完成 / 失败 / 超时。只收还在跑的那条 —— 已经被标成中断的不覆盖(那时结果已经没人等了)。"""
    assert 结果 in ("完成", "失败", "超时"), 结果
    with closing(_连(db)) as c, c:
        return c.execute(f"UPDATE triage_run SET status=?, finished=?, triage_id=?, cost=?, error=? "
                         f"WHERE id=? AND status IN ({','.join('?' * len(在跑))})",
                         (结果, _现在(), triage_id, cost, (error or None) and str(error)[:300], run_id, *在跑)).rowcount


def 转人工(run_id, me, db=None):
    """失败 / 超时 / 中断的 → 转人工:记下谁转的;这条工单此后不再被自动挑去跑(单独点仍可以)。"""
    me = me or {}
    if not me.get("no"):
        raise PermissionError("没有身份 —— 要登录")
    with closing(_连(db)) as c, c:
        确保表(c)
        r = c.execute("SELECT status FROM triage_run WHERE id=?", (run_id,)).fetchone()
        if not r:
            raise ValueError(f"没有运行#{run_id}")
        if r["status"] not in 可转人工:
            return dict(ok=False, reason=f"这一条现在是「{r['status']}」—— 只有失败 / 超时 / 中断的才转人工")
        c.execute("UPDATE triage_run SET status='转人工', handoff_no=? WHERE id=?", (me["no"], run_id))
    return dict(ok=True, reason="转人工了 —— 这条不会再被「研判 N 条」自动挑去跑,请直接人工处理")


def 转人工的工单(db=None):
    """→ 最近一次运行是「转人工」的工单号集合。自动挑单要跳过它们。"""
    with closing(_连(db)) as c:
        确保表(c)
        return {r[0] for r in c.execute(
            "SELECT task_id FROM triage_run t WHERE status='转人工' "
            "AND id=(SELECT MAX(id) FROM triage_run WHERE task_id=t.task_id)")}


def 查(batch, db=None):
    """→ {batch, runs:[…每条带 前面还有几条], 执行线程在吗, 完了吗, 汇总}。读之前先收一遍中断。"""
    收中断(db=db)
    with closing(_连(db)) as c:
        确保表(c)
        在 = 执行线程在吗(c)
        行 = [dict(r) for r in c.execute("SELECT * FROM triage_run WHERE batch=? ORDER BY id", (batch,))]
        for r in 行:
            r["前面还有几条"] = (c.execute("SELECT COUNT(*) FROM triage_run WHERE status IN ('排队','取数','调模型','落库') "
                                           "AND id<?", (r["id"],)).fetchone()[0] if r["status"] == "排队" else 0)
    from collections import Counter
    数 = Counter(r["status"] for r in 行)
    return dict(batch=batch, runs=行, 执行线程在吗=在, 完了吗=bool(行) and not any(r["status"] in 在跑 for r in 行),
                汇总=dict(数), cost=round(sum(r.get("cost") or 0 for r in 行), 4))


def 查运行(run_ids, db=None):
    """按运行号查(提交时复用了别的批次那条,页面拿的是运行号)。→ {runs, 执行线程在吗}"""
    收中断(db=db)
    ids = [int(x) for x in run_ids if str(x).isdigit()]
    with closing(_连(db)) as c:
        确保表(c)
        行 = [dict(r) for r in c.execute(
            f"SELECT * FROM triage_run WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", ids)] if ids else []
        for r in 行:
            r["前面还有几条"] = (c.execute("SELECT COUNT(*) FROM triage_run WHERE status IN ('排队','取数','调模型','落库') "
                                           "AND id<?", (r["id"],)).fetchone()[0] if r["status"] == "排队" else 0)
        return dict(runs=行, 执行线程在吗=执行线程在吗(c))
