# -*- coding: utf-8 -*-
"""条款接受记录 —— 「哪个账户、什么时候、接受了哪份条款的哪一版」。口径在 `knowledge/recording_terms.py`。

**只追加,没有撤回这一列**(业务 D9:录音同意不能撤回)。条款改版后客户重新确认,是**新加一行**,
不改旧行 —— 「客户当时接受的是哪一版」要查得回来。

为什么不放进 `consent`:那张表是可撤回的授权(身体数据 / 未成年人 / 营销触达,都带 revoked_at),
录音同意是条款接受。放进去会多一档 revoked_at 永远为 NULL 的记录,和别的几档长得一样、语义相反(D9-b)。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
import recording_terms as K

DDL = """
CREATE TABLE IF NOT EXISTS terms_accept(
  account_id  TEXT NOT NULL,
  doc         TEXT NOT NULL,           -- 服务条款 / 隐私政策
  version     TEXT NOT NULL,
  accepted_at TEXT NOT NULL,
  via         TEXT,                    -- 在哪儿接受的:小程序注册 / 小程序重新确认 / 演示数据推的
  UNIQUE(account_id, doc, version));
"""


def 建表(c):
    c.executescript(DDL)
    列 = {r[1] for r in c.execute("PRAGMA table_info(call_audio)")}
    if 列 and "consent_basis" not in 列:
        # 这一通录音的同意依据:条款接受 / 默认同意 + 一句人话。**上传那一刻定下来**,
        # 之后条款再改版也不回头改 —— 录的时候依据是什么,就是什么
        c.execute("ALTER TABLE call_audio ADD COLUMN consent_basis TEXT")


def 最近接受(c, customer_id):
    """这位客户(经账户)最近一次接受的服务条款:(版本, 时间) 或 None。"""
    r = c.execute("SELECT t.version, t.accepted_at FROM customer cu JOIN terms_accept t ON t.account_id=cu.account_id "
                  "WHERE cu.id=? AND t.doc=? ORDER BY t.accepted_at DESC LIMIT 1", (customer_id, K.条款文档)).fetchone()
    return tuple(r) if r else None


def 依据(c, customer_id):
    类, 话 = K.依据(最近接受(c, customer_id))
    return f"{类}:{话}"
