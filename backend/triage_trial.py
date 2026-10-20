#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离试运行 + 版本对比(研判队列未做项第 6 项后两块 · 用户 2026-10-19 拍:副本遮掉顾客信息)。

换一版研判提示词之前,先拿一批真实工单在**遮蔽过的库副本**上让 AI 跑一遍:
  · 结果只进 `triage_trial` 这张表、只在对比页上看 —— **不写真实研判、不动工单状态**;
  · 工具服务整个改读副本(mcp/protocol.指到副本),副本里顾客的姓名 / 手机 / 地址 / 微信 / 邮箱换成代号;
  · 和现在产线那一版的草稿、人工结论并排,能对上评测标准答案的,用评测的同一个判分函数(agent/eval.hit)算谁答对了。

遮蔽(用户拍的「客户合并只留一致 / 不一致」):**同一个值永远换成同一个代号**(取哈希前几位)——
两条档案名字一样,遮完代号也一样;不一样就不一样。合并要比的那件事没丢,原文看不到。
"""
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 哪些列算顾客信息 —— 表 → [(列, 代号前缀)]
遮的列 = {
    "customer": [("name", "姓名"), ("phone", "手机"), ("phone_tail", "尾号"), ("addr", "地址"),
                 ("wechat", "微信"), ("email", "邮箱")],
    "wearer":   [("name", "姓名"), ("phone", "手机")],
}


def 代号(前缀, 值):
    if 值 is None or str(值).strip() == "":
        return 值
    return f"{前缀}#{hashlib.sha256(str(值).encode('utf-8')).hexdigest()[:6]}"


def 遮蔽副本(源=None):
    """拷一份库、把顾客信息换成代号。→ 副本路径(调用方用完删它所在的目录)。"""
    import ops
    目录 = tempfile.mkdtemp(prefix="trial-")
    副 = os.path.join(目录, "lanxiu.db")
    shutil.copy(源 or ops.DB, 副)
    with closing(sqlite3.connect(副)) as c, c:
        for 表, 列们 in 遮的列.items():
            有 = {r[1] for r in c.execute(f"PRAGMA table_info({表})")}
            for 列, 前 in 列们:
                if 列 not in 有:
                    continue
                for rid, v in c.execute(f"SELECT rowid, {列} FROM {表}").fetchall():
                    c.execute(f"UPDATE {表} SET {列}=? WHERE rowid=?", (代号(前, v), rid))
    return 副


# ── 结果表 ────────────────────────────────────────────────────────────────
def 确保表(c):
    c.execute("""CREATE TABLE IF NOT EXISTS triage_trial(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch TEXT NOT NULL,           -- 一次试跑一个批次号
        task_id TEXT NOT NULL,
        prompt_ver TEXT,               -- 这次试的那一版(研判:…·系统:…)
        ai_root_cause TEXT, ai_text TEXT, ai_confidence TEXT,
        tools TEXT, cost REAL, error TEXT,
        ran_at TEXT,                   -- 真实时钟:试跑是运维动作,不是演示世界里的事
        by_who TEXT)""")


def _连(db=None):
    import ops
    c = sqlite3.connect(db or ops.DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def 存(batch, task_id, prompt_ver, text, tools, cost, by_who, error=None, db=None):
    import ops, datetime as dt
    p = ops.parse_draft(text or "") if text else {}
    with closing(_连(db)) as c, c:
        确保表(c)
        c.execute("INSERT INTO triage_trial(batch,task_id,prompt_ver,ai_root_cause,ai_text,ai_confidence,tools,cost,"
                  "error,ran_at,by_who) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (batch, task_id, prompt_ver, (p or {}).get("ai_root_cause") or None, text, None,
                   ",".join(tools or []), cost, error,
                   dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),   # 真实时钟:见表上那列的注释
                   by_who))


def 批次们(db=None):
    with closing(_连(db)) as c:
        确保表(c)
        return [dict(r) for r in c.execute(
            # 一批里三类工单各用各的那一版 —— 列出这一批实际用到的**全部**版本,不挑一个代表
            "SELECT batch, GROUP_CONCAT(DISTINCT prompt_ver) prompt_ver, COUNT(*) n, SUM(error IS NOT NULL) 跑挂, "
            "MIN(ran_at) 开始, by_who "
            "FROM triage_trial GROUP BY batch ORDER BY MIN(id) DESC")]


def 对比(batch, db=None):
    """一个试跑批次 vs 这些工单现在的那条研判。→ {批次, 试的版本, 行:[…], 汇总}。

    「答对」只对**能对上评测标准答案**的工单算(case_id 在 truth 里),用评测同一个判分函数,不另写一套;
    对不上的照样并排列出来,只是不算分。跑挂了的单独数,**不算答错**(和夜跑那条同一个理由)。"""
    sys.path.insert(0, os.path.join(ROOT, "agent"))
    import eval as _ev
    with closing(_连(db)) as c:
        确保表(c)
        试 = [dict(r) for r in c.execute("SELECT * FROM triage_trial WHERE batch=? ORDER BY id", (batch,))]
        现 = {}
        for r in c.execute("SELECT * FROM triage ORDER BY id"):
            现[r["task_id"]] = dict(r)                    # 每张工单最近一次研判
        真 = {r["case_id"]: r["root_cause"] for r in c.execute("SELECT case_id, root_cause FROM truth")}
    行, 计 = [], dict(可比=0, 现版对=0, 试版对=0, 跑挂=0, 只并排=0)
    for t in 试:
        cur = 现.get(t["task_id"]) or {}
        标 = 真.get(cur.get("case_id"))
        现对 = 试对 = None
        if t["error"]:
            计["跑挂"] += 1
        elif 标:
            计["可比"] += 1
            现对 = bool(cur.get("ai_text")) and _ev.hit(cur["ai_text"], 标, cur.get("case_id"))[0]
            试对 = _ev.hit(t["ai_text"] or "", 标, cur.get("case_id"))[0]
            计["现版对"] += bool(现对); 计["试版对"] += bool(试对)
        else:
            计["只并排"] += 1
        行.append(dict(task_id=t["task_id"], 标准答案=标, 人工结论=cur.get("status"),
                       人工根因=cur.get("human_root_cause"),
                       现版=dict(版本=cur.get("prompt_ver"), 根因=cur.get("ai_root_cause"), 对=现对),
                       试版=dict(版本=t["prompt_ver"], 根因=t["ai_root_cause"], 对=试对, 跑挂=t["error"])))
    return dict(批次=batch, 试的版本=sorted({t["prompt_ver"] for t in 试 if t["prompt_ver"]}), 行=行, 汇总=计,
                说明="「对不对」只算能对上评测标准答案的工单,用评测同一个判分函数;跑挂了的不算答错;"
                     "两版都是单轮,差一两条可能只是抖动 —— 要下结论就多试几批")
