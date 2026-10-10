#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定制订单确认书 —— 存取(条款在 knowledge/contract_terms.py,业务 2026-10-10 定)。

**在确认下单的同一个事务里生成**(order_write.confirm_order 调):确认书写不进去,确认下单就一起回滚。
> 「付了全款、却没有书面约定」正是要堵的那件事(消保法实施条例第 22 条)——
> 所以不能是「确认成功、确认书稍后补」:稍后补的那一份,在补上之前和不存在没有区别。

每份确认书冻结下单那一刻的商品、价款和**条款版本**;条款以后改了,老确认书不跟着变。
看:门店本店的顾问 / 店长,总部全部。
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
import contract_terms as K

DB = os.path.join(HERE, "lanxiu.db")

DDL = """
CREATE TABLE IF NOT EXISTS order_contract(
  order_id   TEXT PRIMARY KEY,      -- 一张单一份(确认下单只发生一次)
  terms_ver  TEXT NOT NULL,         -- 条款版本(knowledge/contract_terms.版本)
  body       TEXT NOT NULL,         -- 确认书正文(Markdown)
  snapshot   TEXT NOT NULL,         -- 下单那一刻的商品 / 价款(JSON)—— 订单以后改了,这份不跟着变
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL);        -- 谁点的确认下单(顾客当面确认,顾问 / 店长操作)
"""

全部 = "/contract"


def 链接(order_id):
    return f"{全部}?order={order_id}"


def 下载(order_id):
    return f"{全部}.pdf?order={order_id}"


def 建表(c):
    c.executescript(DDL)


def 生成(c, order_id, me, 今天):
    """在调用方的事务里写一份确认书。**出任何错都抛** —— 让确认下单一起回滚。返回链接。"""
    建表(c)
    o = c.execute("SELECT o.id, o.shop, o.amount, o.received, o.wearer_id, cu.name FROM ordr o "
                  "LEFT JOIN customer cu ON cu.id=o.customer_id WHERE o.id=?", (order_id,)).fetchone()
    if not o:
        raise ValueError(f"没有订单 {order_id}")
    明细 = [dict(名称=名, 规格=规, 数量=量 or 1, 金额=float(额 or 0)) for 名, 规, 量, 额 in c.execute(
        "SELECT i.name, s.spec, i.qty, COALESCE(i.total, i.price * COALESCE(i.qty,1), 0) FROM ordr_item i "
        "LEFT JOIN sku s ON s.code=i.sku WHERE i.order_id=? ORDER BY i.id", (order_id,))]
    if not 明细:
        raise ValueError(f"订单 {order_id} 一件商品都没有,不生成确认书")
    着装人 = None
    if o[4]:
        w = c.execute("SELECT name FROM wearer WHERE id=?", (o[4],)).fetchone() if c.execute(
            "SELECT 1 FROM sqlite_master WHERE name='wearer'").fetchone() else None
        着装人 = w[0] if w else None
    合计 = float(o[2] or sum(x["金额"] for x in 明细))
    正文 = K.拼正文(订单号=order_id, 门店=o[1], 顾客=o[5] or "—", 下单日=str(今天)[:10], 明细=明细,
                  合计=合计, 已付=float(o[3] if o[3] is not None else 合计), 着装人=着装人)
    c.execute("INSERT INTO order_contract(order_id, terms_ver, body, snapshot, created_at, created_by) VALUES(?,?,?,?,?,?)",
              (order_id, K.版本, 正文, json.dumps(dict(明细=明细, 合计=合计), ensure_ascii=False),
               str(今天)[:10], me.get("no") or me.get("name")))
    return 链接(order_id)


def _能看(me, shop):
    if not me:
        return False
    return me.get("role") == "总部运营" or me.get("shop") == shop


def 取(me, order_id, db=None):
    c = sqlite3.connect(db or DB)
    try:
        建表(c)
        r = c.execute("SELECT k.order_id, k.terms_ver, k.body, k.created_at, k.created_by, o.shop, o.status "
                      "FROM order_contract k JOIN ordr o ON o.id=k.order_id WHERE k.order_id=?", (order_id,)).fetchone()
        有单 = c.execute("SELECT shop, status, paid_at FROM ordr WHERE id=?", (order_id,)).fetchone()
    finally:
        c.close()
    if not 有单 or not _能看(me, 有单[0]):
        return dict(error=f"没有订单 {order_id},或者它不在你的范围里")
    if not r:
        return dict(error=f"订单 {order_id} 没有确认书 —— "
                          + ("它确认于订单确认书上线(2026-10-10)之前" if 有单[2] else "它还没确认下单"))
    return dict(订单号=r[0], 条款版本=r[1], body=r[2], 生成于=r[3], 经手=r[4], 门店=r[5], 订单状态=r[6],
                链接=链接(r[0]), 下载=下载(r[0]))
