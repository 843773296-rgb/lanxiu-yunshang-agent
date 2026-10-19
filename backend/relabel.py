#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改判先审核,再进评测集(研判队列未做项第 4 项 · 用户 2026-10-19 拍:总部运营审)。

原来:店长改判一条研判,只要那一单没有建库标注,**当场写进 `truth`(评测答案)**并标「人工改判」——
一个人的判断直接变成以后考 AI 的标准答案,判错了就是一道假题,而且事后几乎查不出来。
页面那句「回归时会单独统计通过率」也不成立:评测读答案时不分来源。

现在三步,每一步换一个人或换一个时机:
  ① 改判(店长,`ops.resolve`)→ 这条研判记成「待审核」的候选,**不碰 truth**;
  ② 审核(总部运营,且**不能是改判人自己**)→ 采用 / 驳回(驳回要写理由);
  ③ 并入(维护者,`tools/merge_relabels.py`)→ 把「已采用」的一批写进 truth。
     **和题集重冻一起做**:truth 一变,`example_pool_check` 的「冻结切分 = 按规则现切」就红,
     逼着重切 —— 也就是开一个新分界点(换了考卷,分数不能和以前直接比)。这是故意借那道闸。

状态存在 `triage` 的三列上(候选的根因 / 处理就是 human_root_cause / human_action,不另抄一份)。
"""
import os
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

审核人角色 = ("总部运营",)
状态们 = ("待审核", "已采用", "已驳回", "已并入")


def 确保列(c):
    有 = {r[1] for r in c.execute("PRAGMA table_info(triage)")}
    for col in ("relabel_review", "relabel_by_no", "relabel_reviewer", "relabel_reviewed_at", "relabel_note"):
        if col not in 有:
            c.execute(f"ALTER TABLE triage ADD COLUMN {col} TEXT")


def _连(db=None):
    import ops
    c = sqlite3.connect(db or ops.DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def 审核(triage_id, me, 采用, 理由=None, db=None, 来源="页面"):
    """总部运营审一条改判候选。→ {ok, reason}。改判人自己审不了;驳回要写理由。成功 / 被拒都写 op_log。"""
    import ops
    from oplog import log_op as _log
    me = me or {}
    动作 = "采用" if 采用 else "驳回"
    def _记(ok, code, 话):
        _log(f"{me.get('name') or '?'}({me.get('no') or '?'})", "triage", f"triage#{triage_id}", "待审核",
             ("已采用" if 采用 else "已驳回") if ok else "—", ok, code, f"[{来源}] 改判审核:{话}"[:200],
             {"role": me.get("role"), "no": me.get("no")})
    if not (me.get("no") and me.get("role")):
        _记(False, "NO_IDENTITY", "没有身份")
        raise PermissionError("没有身份 —— 要登录")
    if me.get("role") not in 审核人角色:
        话 = f"改判审核只能由 {' / '.join(审核人角色)} 做,你是「{me.get('role')}」"
        _记(False, "ROLE", 话)
        raise PermissionError(话)
    if not 采用 and not (理由 or "").strip():
        _记(False, "NO_REASON", "驳回没写理由")
        raise ValueError("驳回要写理由 —— 改判的人要知道为什么不算数")
    ts = ops.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(_连(db)) as c, c:
        确保列(c)
        t = c.execute("SELECT status, relabel_review, relabel_by_no FROM triage WHERE id=?", (triage_id,)).fetchone()
        if not t:
            raise ValueError(f"没有 triage#{triage_id}")
        if t["relabel_by_no"] and t["relabel_by_no"] == me["no"]:
            话 = "改判人不能审自己的改判 —— 要第二个人把关"
            _记(False, "SELF_REVIEW", 话)
            raise PermissionError(话)
        改 = c.execute("UPDATE triage SET relabel_review=?, relabel_reviewer=?, relabel_reviewed_at=?, relabel_note=? "
                       "WHERE id=? AND relabel_review='待审核'",
                       ("已采用" if 采用 else "已驳回", f"{me.get('name')}({me['no']})", ts,
                        (理由 or "").strip() or None, triage_id)).rowcount
    if not 改:
        话 = f"这条不是待审核的改判(现在是「{t['relabel_review'] or '不是改判候选'}」)"
        _记(False, "BAD_STATE", 话)
        return dict(ok=False, reason=话)
    _记(True, "RELABEL_" + ("ACCEPT" if 采用 else "REJECT"), 动作 + (f":{理由.strip()}" if 理由 else ""))
    return dict(ok=True, reason=("采用了 —— 下次换考卷时并入评测集(不是现在)" if 采用
                                 else "驳回了 —— 这条改判只作用在这张工单上,不进评测集"))


def 并入(db=None, 演练=True):
    """把「已采用」的改判写进 truth。→ {条数, 冲突:[…]}。演练=True 只报不写。

    写进去之前再对一次建库标注:审核期间那一单有了建库标注、且不一致的,**不覆盖**,列出来给人裁。"""
    import ops
    出, 冲突 = [], []
    with closing(_连(db)) as c, c:
        确保列(c)
        for t in c.execute("SELECT id, case_id, breakpoint, human_root_cause, human_action, human_note, handler, "
                           "relabel_reviewer FROM triage WHERE relabel_review='已采用' ORDER BY id").fetchall():
            old = c.execute("SELECT root_cause, src FROM truth WHERE case_id=?", (t["case_id"],)).fetchone()
            if old and old["src"] != "人工改判" and old["root_cause"] != t["human_root_cause"]:
                冲突.append(dict(triage_id=t["id"], case_id=t["case_id"], 已有=old["root_cause"], 改判=t["human_root_cause"]))
                continue
            出.append(t["id"])
            if not 演练:
                c.execute("INSERT OR REPLACE INTO truth(case_id,breakpoint,root_cause,expected_action,expected_evidence,"
                          "note,src) VALUES(?,?,?,?,?,?,'人工改判')",
                          (t["case_id"], t["breakpoint"], t["human_root_cause"], t["human_action"] or "",
                           t["human_note"] or "", f"{t['handler']} 改判 · {t['relabel_reviewer']} 审核采用"))
                c.execute("UPDATE triage SET relabel_review='已并入', into_eval=1 WHERE id=?", (t["id"],))
    return dict(条数=len(出), triage_ids=出, 冲突=冲突, 演练=演练)


def 待审(db=None):
    """→ 待审核的改判候选(给页面 / 值班台数)。"""
    with closing(_连(db)) as c:
        确保列(c)
        return [dict(r) for r in c.execute(
            "SELECT id, task_id, case_id, breakpoint, ai_root_cause, human_root_cause, handler, handled_at "
            "FROM triage WHERE relabel_review='待审核' ORDER BY id")]
