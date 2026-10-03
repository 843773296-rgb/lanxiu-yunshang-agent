# -*- coding: utf-8 -*-
"""商机对象的存取 —— 建表、从一次通话建商机、改状态、转方案。口径在 `knowledge/oppo_obj.py`。

`backend/opportunity.py` 只回答「这通电话里**有没有**商机」;判断成立之后,
商机要成为一个**有生命周期的对象**(intent `opportunity-and-call-notes` 判据 ①):
来源、预估(客户原话里的预算,可空 —— **不给成单概率**)、下一步、关闭原因、搁置等什么。

两张表:

    opportunity        一条商机。沟通发现的必须指回触发它的那次通话(call_id)
    opportunity_need   一条结构化诉求(维度 + 值),**必须带原话**(quote)和出自哪次通话

方案表加一列 `opportunity_id`:转方案时**两头都记**,和「转过单的方案必须指得回订单」同一个形状。
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
import oppo_obj as K

DDL = """
CREATE TABLE IF NOT EXISTS opportunity(
  id          TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  source      TEXT NOT NULL,          -- 沟通发现 / 历史诉求
  call_id     TEXT,                   -- 触发它的那次通话(call_audio.id);沟通发现的必填
  status      TEXT NOT NULL,          -- 见 oppo_obj.状态
  budget      TEXT,                   -- 客户原话里提到的预算,可空;**不给成单概率**
  next_step   TEXT,
  close_reason TEXT,                  -- 已关闭时:客户为什么不要
  wait_for    TEXT,                   -- 搁置等供给时:等什么,JSON {维度: 值}
  scheme_id   TEXT,                   -- 已转方案时:转成的方案
  advisor_no  TEXT,
  confirmed_by TEXT, confirmed_at TEXT,   -- 顾问点头(业务 D5:模型给判断,人点头才算)
  created     TEXT NOT NULL,
  updated     TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunity_need(
  opp_id  TEXT NOT NULL,
  dim     TEXT NOT NULL,              -- 见 oppo_obj.诉求维度
  val     TEXT NOT NULL,
  quote   TEXT NOT NULL,              -- 原话:逐字稿里客户说的那一句
  call_id TEXT NOT NULL);
"""


def 建表(c):
    c.executescript(DDL)
    列 = {r[1] for r in c.execute("PRAGMA table_info(scheme)")}
    if 列 and "opportunity_id" not in 列:
        c.execute("ALTER TABLE scheme ADD COLUMN opportunity_id TEXT")


def 从通话建(c, call_id, 客户, 顾问, 诉求, 时间, 下一步=None, 预算=None):
    """诉求 = [(维度, 值, 原话)]。原话为空的诉求**不收** —— 指不回原话就不进库。返回商机号。"""
    oid = f"OP-{call_id}"
    c.execute("INSERT INTO opportunity(id, customer_id, source, call_id, status, budget, next_step,"
              " advisor_no, created, updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (oid, 客户, "沟通发现", call_id, K.起始状态, 预算, 下一步, 顾问, 时间, 时间))
    for 维, 值, 原 in 诉求:
        if 原:
            c.execute("INSERT INTO opportunity_need(opp_id, dim, val, quote, call_id) VALUES(?,?,?,?,?)",
                      (oid, 维, 值, 原, call_id))
    return oid


def 改状态(c, oid, 到, 时间, 经手人=None, 关闭原因=None, 等什么=None, 方案=None):
    """按口径转状态。返回 (成没成, 一句人话)。**不合口径的不写**。"""
    r = c.execute("SELECT status FROM opportunity WHERE id=?", (oid,)).fetchone()
    if not r:
        return False, f"没有商机 {oid}"
    能, 话 = K.能转吗(r[0], 到)
    if not 能:
        return False, 话
    if 到 == "搁置等供给":
        能, 话 = K.搁置理由合格吗(等什么)
        if not 能:
            return False, 话
    if 到 == "已关闭" and not 关闭原因:
        return False, "关掉商机要写为什么(看了不喜欢 / 嫌贵 / 不需要)—— 不然和「当时没货」分不开"
    if 到 == "已转方案" and not 方案:
        return False, "转方案要指明是哪个方案"
    c.execute("UPDATE opportunity SET status=?, updated=?,"
              " close_reason=COALESCE(?, close_reason), wait_for=COALESCE(?, wait_for),"
              " scheme_id=COALESCE(?, scheme_id),"
              " confirmed_by=CASE WHEN ?='跟进中' AND confirmed_by IS NULL THEN ? ELSE confirmed_by END,"
              " confirmed_at=CASE WHEN ?='跟进中' AND confirmed_at IS NULL THEN ? ELSE confirmed_at END"
              " WHERE id=?",
              (到, 时间, 关闭原因, json.dumps(等什么, ensure_ascii=False) if 等什么 else None, 方案,
               到, 经手人, 到, 时间, oid))
    if 方案:
        c.execute("UPDATE scheme SET opportunity_id=? WHERE id=?", (oid, 方案))
    return True, f"{oid} → {到}"
