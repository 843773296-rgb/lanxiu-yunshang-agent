# -*- coding: utf-8 -*-
"""工厂回传的接收写口 —— **生产和发货只认工厂回传,门店不推。** 口径在 knowledge/factory_feed.py。

业务 2026-09-22:「已生产」「发货」是工厂回传的数据,走供应链系统。
现在没接真系统,假数据工厂里的模拟工厂(fakedata/factory_sim.py)扮演它,
**两边只隔着「一条消息」**:将来接真系统,拿掉模拟工厂,这一份不改。

## 做什么

  收(消息)     一条回传进来:先整条落进收件箱(不管收不收,都留底),再按口径判:
               收下 → 走订单状态机推到下一档,生产 / 发货时间记**工厂报的时间**(不是收到的时间)
               暂存 → 来早了,留在收件箱;这张单每收下一条,就回头把暂存的再判一遍
               重复 / 拒收 / 挂异常 → 订单不动,收件箱里写清为什么
  该催清单()   生产中的单:工厂没回接单、或过了承诺完工日还没完工 → 提醒顾问去催

## 为什么收件箱不管收不收都留底

拒掉的、挂异常的那一条,正是要人去跟工厂对的东西。只留收下的,出了事查不到工厂到底发过什么。

**订单状态机上另有一道闸**(fsm 的 FACTORY_GATE):定制单「生产中→已生产→待发货→已发货」
只认收件箱里**收下了**的那条回传 —— 后台手动改状态也绕不过,和开裁、下单那几道闸同一个做法。
"""
import os, sys, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))

DDL = """
CREATE TABLE IF NOT EXISTS factory_msg(
  -- 工厂回传收件箱。**每一条都留底**,收不收都在这里 —— 拒掉的正是要跟工厂对的东西。
  msg_id TEXT PRIMARY KEY,           -- 工厂那边的消息号
  order_id TEXT, event TEXT,         -- 接单 / 完工 / 质检通过 / 发出
  at TEXT,                           -- 工厂报的发生时间(不是我们收到的时间)
  tracking_no TEXT, promise_date TEXT, factory TEXT,
  received_at TEXT,                  -- 我们收到的时间
  result TEXT,                       -- 收下 / 暂存 / 重复 / 拒收 / 挂异常
  reason TEXT);
CREATE INDEX IF NOT EXISTS ix_factory_msg_order ON factory_msg(order_id);
"""


def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    return c


def ensure(c=None):
    own = c is None
    c = c or sqlite3.connect(DB)
    c.executescript(DDL)
    if own: c.commit(); c.close()


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _订单(c, oid):
    """口径要的那几样:类型、状态、上一步时间(开裁没有就用审核;完工;质检通过的回传时间)。"""
    o = c.execute("SELECT id, kind, status, cut_at, audit_at, produced_at FROM ordr WHERE id=?", (oid,)).fetchone()
    if not o:
        return None
    质检 = c.execute("SELECT MAX(at) FROM factory_msg WHERE order_id=? AND event='质检通过' AND result='收下'",
                    (oid,)).fetchone()[0]
    上 = {"待发货": 质检 or o["produced_at"], "已生产": o["produced_at"]}.get(o["status"]) \
        or o["cut_at"] or o["audit_at"]
    return dict(类型=o["kind"], 状态=o["status"], 上一步时间=上)


def 收(消息, 今天, actor="工厂回传"):
    """收一条回传。消息: {消息号, 订单号, 事件, 时间, 物流单号?, 承诺完工日?, 工厂?}。
    返回 {结论, 理由, 推到}。**今天由调用方给**(演示世界的今天,不是机器时钟)。"""
    import factory_feed as K
    c = _c(); ensure(c)
    号 = str(消息.get("消息号") or "").strip()
    if not 号:
        return dict(结论="拒收", 理由="回传没带消息号 —— 没法去重,不收", 推到=None)
    if c.execute("SELECT 1 FROM factory_msg WHERE msg_id=?", (号,)).fetchone():
        return dict(结论="重复", 理由=f"消息 {号} 已经收过 —— 只记一次", 推到=None)
    oid = str(消息.get("订单号") or "").strip()
    c.execute("""INSERT INTO factory_msg(msg_id,order_id,event,at,tracking_no,promise_date,factory,received_at)
                 VALUES(?,?,?,?,?,?,?,?)""",
              (号, oid, 消息.get("事件"), 消息.get("时间"), 消息.get("物流单号"), 消息.get("承诺完工日"),
               消息.get("工厂"), _now()))
    c.commit()
    r = _判并落(c, 号, 今天, actor)
    if r["结论"] == "收下":
        _放行暂存(c, oid, 今天, actor)
    c.close()
    return r


def _判并落(c, 号, 今天, actor):
    import factory_feed as K
    m = c.execute("SELECT * FROM factory_msg WHERE msg_id=?", (号,)).fetchone()
    消息 = dict(消息号=m["msg_id"], 订单号=m["order_id"], 事件=m["event"], 时间=m["at"],
              物流单号=m["tracking_no"], 承诺完工日=m["promise_date"])
    收过号 = {r[0] for r in c.execute(
        "SELECT msg_id FROM factory_msg WHERE msg_id!=? AND result IS NOT NULL AND result!='暂存'", (号,))}
    收过步 = {r[0] for r in c.execute(
        "SELECT event FROM factory_msg WHERE order_id=? AND result='收下' AND msg_id!=?", (m["order_id"], 号))}
    接 = c.execute("SELECT factory FROM factory_msg WHERE order_id=? AND event='接单' AND result='收下' "
                  "AND msg_id!=? ORDER BY at LIMIT 1", (m["order_id"], 号)).fetchone()
    try:
        在制 = bool(c.execute("SELECT 1 FROM workorder WHERE ref=? AND status='在制'", (m["order_id"],)).fetchone())
    except sqlite3.OperationalError:                   # 没有车间工单表的库(检查用的小库)
        在制 = False
    结论, 理由, 推到 = K.判一条(dict(消息, 工厂=m["factory"]), _订单(c, m["order_id"]), 收过号, 收过步, 今天,
                             接单方=接[0] if 接 else None, 车间在制=在制)
    if 结论 == "收下" and 推到:
        # 先记成收下,状态机那道闸才查得到它;推不动再改回异常
        c.execute("UPDATE factory_msg SET result='收下', reason=? WHERE msg_id=?", (理由, 号)); c.commit()
        import server
        rr = server.transit("bk-order", m["order_id"], 推到, {"by": "工厂回传", "工厂消息号": 号}, actor=actor)
        if not rr.get("ok"):
            结论, 理由, 推到 = "挂异常", f"口径判收下,状态机没让过:{rr.get('reason')}", None
        else:
            # 生产 / 发货时间记**工厂报的时间** —— transit 落的是收到那一刻
            col = {"已生产": "produced_at", "已发货": "shipped_at"}.get(推到)
            if col:
                c.execute(f"UPDATE ordr SET {col}=? WHERE id=?", (m["at"], m["order_id"]))
    c.execute("UPDATE factory_msg SET result=?, reason=? WHERE msg_id=?", (结论, 理由, 号))
    c.commit()
    return dict(结论=结论, 理由=理由, 推到=推到)


def _放行暂存(c, oid, 今天, actor):
    """这张单刚收下一条 —— 回头把它暂存的回传按时间再判一遍,能放的放。"""
    while True:
        放了 = False
        for m in c.execute("SELECT msg_id FROM factory_msg WHERE order_id=? AND result='暂存' ORDER BY at",
                           (oid,)).fetchall():
            if _判并落(c, m[0], 今天, actor)["结论"] != "暂存":
                放了 = True
        if not 放了:
            return


def 有收下的回传(order_id, 到, db=None):
    """状态机那道闸用:推到「到」这一档,有没有收下的工厂回传撑着。
    db:调用方(server.transit)自己的库路径 —— 检查在副本上跑时,闸要查同一个库。"""
    import factory_feed as K
    事 = [k for k, (_, 后, _) in K.事件.items() if 后 == 到]
    if not 事:
        return False
    c = sqlite3.connect(db or DB); ensure(c)
    ok = bool(c.execute("SELECT 1 FROM factory_msg WHERE order_id=? AND event=? AND result='收下'",
                        (order_id, 事[0])).fetchone())
    c.close()
    return ok


def 该催清单(今天, shop=None):
    """生产中的单里该去催工厂的。返回 [{订单, 门店, 顾问, 为什么}]。"""
    import factory_feed as K
    c = _c(); ensure(c)
    out = []
    for o in c.execute("SELECT id, shop, advisor_no, cut_at, audit_at FROM ordr WHERE kind='定制品订单' "
                       "AND status='生产中'" + (" AND shop=?" if shop else ""), ((shop,) if shop else ())):
        接 = c.execute("SELECT promise_date FROM factory_msg WHERE order_id=? AND event='接单' AND result='收下' "
                      "ORDER BY at DESC LIMIT 1", (o["id"],)).fetchone()
        要, 话 = K.该催("生产中", 接[0] if 接 else None, bool(接), o["cut_at"] or o["audit_at"], 今天)
        if 要:
            out.append(dict(订单=o["id"], 门店=o["shop"], 顾问=o["advisor_no"], 为什么=话))
    c.close()
    return out


def 回传记录(order_id, db=None):
    """查订单时带出来:工厂回传了什么、收没收。db:调用方自己的库路径(同 有收下的回传)。"""
    c = sqlite3.connect(db or DB); c.row_factory = sqlite3.Row; ensure(c)
    rs = [dict(r) for r in c.execute(
        "SELECT event 回传, at 工厂报的时间, tracking_no 物流单号, promise_date 承诺完工日, result 处理, reason 为什么 "
        "FROM factory_msg WHERE order_id=? ORDER BY at", (order_id,))]
    c.close()
    return rs
