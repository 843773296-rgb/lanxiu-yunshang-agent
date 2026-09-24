# -*- coding: utf-8 -*-
"""工厂回传的接收写口 —— **生产和发货只认工厂回传,门店不推。** 口径在 knowledge/factory_feed.py。

业务 2026-09-22 / 09-23:「已生产」「发货」是工厂回传的数据,走供应链系统;
**可以分批发货**(每个包裹独立),工厂**可以撤回 / 更正**(必须留日志),**整批延期**要提醒顾问通知顾客,
**不许转厂**;发错件 / 到店发现要返工由**店长**人工回退。

现在没接真系统,假数据工厂里的模拟工厂(fakedata/factory_sim.py)扮演它,
**两边只隔着「一条消息」**:将来接真系统,拿掉模拟工厂,这一份不改。

## 做什么

  收(消息)       一条回传进来:整条落进收件箱(收不收都留底)→ 按口径判 → 照「效果」落库
  人工回退()     店长:发错件 / 到店返工,订单退一档,**作废相关回传**(不作废的话工厂重报会被当重复拦掉)
  该催清单()     生产中的单:工厂没回接单、或过了(最新的)承诺完工日还没完工
  待通知清单()   工厂延期了、顾问还没通知顾客的单;通知完调 标记已通知()
  订单日志()     这张单从开单到现在发生过什么 —— 状态变化、每一条回传、回退、延期,按时间排

## 为什么收件箱不管收不收都留底

拒掉的、挂异常的那一条,正是要人去跟工厂对的东西。只留收下的,出了事查不到工厂到底发过什么。

**订单状态机上另有一道闸**(fsm 的 FACTORY_GATE):定制单「生产中→已生产→待发货→已发货」
只认**各件进度汇总出来的结果** —— 后台手动改状态绕不过,回退也只能走 人工回退()。
"""
import os, sys, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
from oplog import log_op

DDL = """
CREATE TABLE IF NOT EXISTS factory_msg(
  -- 工厂回传收件箱。**每一条都留底**,收不收都在这里 —— 拒掉的正是要跟工厂对的东西。
  msg_id TEXT PRIMARY KEY,
  order_id TEXT, event TEXT,         -- 接单/完工/质检通过/发出/撤回/更正/延期
  at TEXT,                           -- 工厂报的发生时间(不是我们收到的时间)
  tracking_no TEXT, promise_date TEXT, factory TEXT, ref_msg TEXT, note TEXT,
  -- 更正要改成的新值。**单独两列** —— 挤在 at / tracking_no 上的话,
  -- 「这条更正消息自己的时间」和「要改成的时间」就是同一个格子(第一次造数当场撞上:
  -- 更正被判成「回传时间晚于今天」)。
  new_at TEXT, new_tracking TEXT,
  received_at TEXT,
  result TEXT,                       -- 收下 / 暂存 / 重复 / 拒收 / 挂异常
  reason TEXT,
  void_at TEXT, void_by TEXT);       -- 作废(被工厂撤回,或被人工回退连带作废)
CREATE INDEX IF NOT EXISTS ix_factory_msg_order ON factory_msg(order_id);
CREATE TABLE IF NOT EXISTS factory_msg_item(
  -- 一条回传报的是哪几件。**分批发货靠它** —— 不带件清单的老式回传补成「整单所有件」。
  msg_id TEXT, item_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_factory_msg_item ON factory_msg_item(msg_id);
CREATE TABLE IF NOT EXISTS pkg(
  -- **包裹**:工厂一次发出的一批件。业务 09-23:分批发货,每个包裹独立(件清单、快递单号、各自签收)。
  -- ⚠️ 这张表只放**工厂侧**的列。取件方式、试穿签收、码、完成确认在签收那一侧(pickup/fit_code),按包裹号绑。
  pkg_id TEXT PRIMARY KEY, order_id TEXT, tracking_no TEXT,
  shipped_at TEXT,                   -- 工厂发出时间(工厂报的)
  arrived_at TEXT,                   -- 到店时间(签收侧登记到店代收时写)
  status TEXT,                       -- 在途 / 到店 / 已签收(签收侧改)
  void_at TEXT, void_reason TEXT,    -- 发错件回退时作废这个包裹
  msg_id TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS ix_pkg_order ON pkg(order_id);
CREATE TABLE IF NOT EXISTS pkg_item(
  pkg_id TEXT, item_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_pkg_item ON pkg_item(pkg_id);
CREATE TABLE IF NOT EXISTS factory_delay(
  -- 工厂延期通知。**原承诺日留痕**,不然工厂可以靠不断延期把逾期永远清零(业务 09-23)。
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, msg_id TEXT,
  old_promise TEXT, new_promise TEXT, reason TEXT, at TEXT,
  told_at TEXT, told_by TEXT);       -- 顾问通知顾客之后点「已通知」
CREATE INDEX IF NOT EXISTS ix_delay_order ON factory_delay(order_id);
CREATE TABLE IF NOT EXISTS order_rollback(
  -- 人工回退(业务 09-23):发错件 / 到店返工。**一直留着,页面和订单日志都看得到**。
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, at TEXT, by_no TEXT,
  cause TEXT, note TEXT, frm TEXT, too TEXT, freight TEXT);
CREATE INDEX IF NOT EXISTS ix_rollback_order ON order_rollback(order_id);
CREATE TABLE IF NOT EXISTS order_event(
  -- **订单日志里那些没有自己的表的事件**(业务 09-23:每个订单一条独立日志)。
  -- 签收那一侧(包裹到店、取件方式、某件签收合身 / 不合身、顾客确认完成)往这里写,调 记事件()。
  -- 状态变化、工厂回传、人工回退、延期各有自己的表,**不往这儿抄第二份** —— 抄了就会两份不一致。
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, at TEXT,
  pkg_id TEXT, item_id INTEGER, action TEXT, by_no TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS ix_order_event ON order_event(order_id);
"""


def _c(db=None):
    c = sqlite3.connect(db or DB); c.row_factory = sqlite3.Row
    return c


def ensure(c=None, db=None):
    own = c is None
    c = c or sqlite3.connect(db or DB)
    c.executescript(DDL)
    if own: c.commit(); c.close()


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def 件进度(c, oid):
    """这张单每一件走到哪了 —— 从**没作废的、收下的**回传现算,不单独存一份。"""
    出 = {}
    for r in c.execute("""SELECT i.item_id, m.event FROM factory_msg m JOIN factory_msg_item i ON i.msg_id=m.msg_id
                          WHERE m.order_id=? AND m.result='收下' AND m.void_at IS NULL
                          ORDER BY m.at""", (oid,)):
        import factory_feed as K
        到 = K.事件.get(r["event"], (None,))[0]
        if not 到:
            continue
        k = str(r["item_id"])
        if k not in 出 or K.件进度档.index(到) > K.件进度档.index(出[k]):
            出[k] = 到
    return 出


def _全部件(c, oid):
    return [str(r[0]) for r in c.execute("SELECT id FROM ordr_item WHERE order_id=? ORDER BY id", (oid,))]


def _订单(c, oid):
    o = c.execute("SELECT id, kind, status, cut_at, audit_at, produced_at FROM ordr WHERE id=?", (oid,)).fetchone()
    if not o:
        return None
    上 = c.execute("""SELECT MAX(at) FROM factory_msg WHERE order_id=? AND result='收下' AND void_at IS NULL
                      AND event IN ('完工','质检通过')""", (oid,)).fetchone()[0]
    return dict(类型=o["kind"], 状态=o["status"], 上一步时间=上 or o["cut_at"] or o["audit_at"])


def 收(消息, 今天, actor="工厂回传"):
    """收一条回传。**今天由调用方给**(演示世界的今天)。返回 {结论, 理由, 效果}。"""
    c = _c(); ensure(c)
    号 = str(消息.get("消息号") or "").strip()
    if not 号:
        c.close(); return dict(结论="拒收", 理由="回传没带消息号 —— 没法去重,不收", 效果=None)
    if c.execute("SELECT 1 FROM factory_msg WHERE msg_id=?", (号,)).fetchone():
        c.close(); return dict(结论="重复", 理由=f"消息 {号} 已经收过 —— 只记一次", 效果=None)
    oid = str(消息.get("订单号") or "").strip()
    c.execute("""INSERT INTO factory_msg(msg_id,order_id,event,at,tracking_no,promise_date,factory,ref_msg,note,
                 new_at,new_tracking,received_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (号, oid, 消息.get("事件"), 消息.get("时间"), 消息.get("物流单号"), 消息.get("承诺完工日"),
               消息.get("工厂"), 消息.get("原消息号"), 消息.get("原因"),
               消息.get("新时间"), 消息.get("新物流单号"), _now()))
    for x in (消息.get("件") or []):
        c.execute("INSERT INTO factory_msg_item(msg_id,item_id) VALUES(?,?)", (号, int(x)))
    c.commit()
    r = _判并落(c, 号, 今天, actor)
    if r["结论"] == "收下":
        _放行暂存(c, oid, 今天, actor)
    c.close()
    return r


def _判并落(c, 号, 今天, actor):
    import factory_feed as K
    m = c.execute("SELECT * FROM factory_msg WHERE msg_id=?", (号,)).fetchone()
    oid = m["order_id"]
    件 = [r[0] for r in c.execute("SELECT item_id FROM factory_msg_item WHERE msg_id=?", (号,))]
    消息 = dict(消息号=m["msg_id"], 订单号=oid, 事件=m["event"], 时间=m["at"], 工厂=m["factory"],
              物流单号=m["tracking_no"], 承诺完工日=m["promise_date"], 原消息号=m["ref_msg"],
              原因=m["note"], 件=件)
    if m["event"] == "更正":
        消息["新时间"], 消息["新物流单号"] = m["new_at"], m["new_tracking"]
    收过号 = {r[0] for r in c.execute(
        "SELECT msg_id FROM factory_msg WHERE msg_id!=? AND result IS NOT NULL AND result!='暂存'", (号,))}
    接 = c.execute("SELECT factory FROM factory_msg WHERE order_id=? AND event='接单' AND result='收下' "
                  "AND void_at IS NULL AND msg_id!=? ORDER BY at LIMIT 1", (oid, 号)).fetchone()
    try:
        在制 = bool(c.execute("SELECT 1 FROM workorder WHERE ref=? AND status='在制'", (oid,)).fetchone())
    except sqlite3.OperationalError:
        在制 = False
    原 = None
    if m["ref_msg"]:
        r0 = c.execute("SELECT event, at, factory, result FROM factory_msg WHERE msg_id=?", (m["ref_msg"],)).fetchone()
        if r0:
            原 = dict(回传=r0["event"], 时间=r0["at"], 工厂=r0["factory"], 处理=r0["result"])
    结论, 理由, 效果 = K.判一条(消息, _订单(c, oid), 收过号, set(), 今天, 接单方=接[0] if 接 else None,
                              车间在制=在制, 全部件=_全部件(c, oid), 件进度=件进度(c, oid), 原消息=原)
    if 结论 == "收下":
        c.execute("UPDATE factory_msg SET result='收下', reason=? WHERE msg_id=?", (理由, 号)); c.commit()
        if not 件 and (效果 or {}).get("件"):          # 老式整单回传:把补出来的件清单落下来
            for x in 效果["件"]:
                c.execute("INSERT INTO factory_msg_item(msg_id,item_id) VALUES(?,?)", (号, int(x)))
            c.commit()
        ok, 话 = _落效果(c, m, 效果, 今天, actor)
        if not ok:
            结论, 理由 = "挂异常", 话
    c.execute("UPDATE factory_msg SET result=?, reason=? WHERE msg_id=?", (结论, 理由, 号))
    c.commit()
    return dict(结论=结论, 理由=理由, 效果=效果)


def _落效果(c, m, 效果, 今天, actor):
    """照口径给出的「效果」落库。返回 (成没成, 话)。"""
    import factory_feed as K
    oid = m["order_id"]
    if not 效果:
        return True, ""
    if "作废" in 效果:                                  # 撤回
        c.execute("UPDATE factory_msg SET void_at=?, void_by=? WHERE msg_id=?",
                  (_now(), m["factory"] or "工厂", 效果["作废"]))
        c.execute("UPDATE pkg SET void_at=?, void_reason='工厂撤回了这条发出回传' WHERE msg_id=?",
                  (_now(), 效果["作废"]))
        c.commit()
        log_op(m["factory"] or "工厂回传", "ordr", oid, "—", "—", True, "FACTORY_VOID",
               f"工厂撤回回传 {效果['作废']};订单状态不自动退,等店长定", {"role": "工厂"})
        return True, ""
    if "改" in 效果:                                    # 更正
        改 = 效果["改"]
        if "时间" in 改:
            c.execute("UPDATE factory_msg SET at=? WHERE msg_id=?", (改["时间"], 效果["原消息号"]))
        if "物流单号" in 改:
            c.execute("UPDATE factory_msg SET tracking_no=? WHERE msg_id=?", (改["物流单号"], 效果["原消息号"]))
            c.execute("UPDATE pkg SET tracking_no=? WHERE msg_id=?", (改["物流单号"], 效果["原消息号"]))
        c.commit()
        log_op(m["factory"] or "工厂回传", "ordr", oid, "—", "—", True, "FACTORY_FIX",
               f"工厂更正回传 {效果['原消息号']}:" + "、".join(f"{k}→{v}" for k, v in 改.items()), {"role": "工厂"})
        return True, ""
    if "新承诺完工日" in 效果:                          # 延期
        旧 = c.execute("SELECT promise_date FROM factory_msg WHERE order_id=? AND event='接单' AND result='收下' "
                      "AND void_at IS NULL ORDER BY at DESC LIMIT 1", (oid,)).fetchone()
        c.execute("""INSERT INTO factory_delay(order_id,msg_id,old_promise,new_promise,reason,at)
                     VALUES(?,?,?,?,?,?)""",
                  (oid, m["msg_id"], 旧[0] if 旧 else None, 效果["新承诺完工日"], m["note"], m["at"]))
        c.commit()
        log_op(m["factory"] or "工厂回传", "ordr", oid, "—", "—", True, "FACTORY_DELAY",
               f"工厂延期:{(旧[0] if 旧 else '原无')} → {效果['新承诺完工日']};要提醒顾问通知顾客", {"role": "工厂"})
        return True, ""
    if "件" in 效果:                                    # 完工 / 质检 / 发出
        if 效果["到"] == "已发出":                      # 发出 = 一个包裹
            n = c.execute("SELECT COUNT(*) FROM pkg").fetchone()[0] + 1
            pid = f"P{int(oid[-6:]) if oid[-6:].isdigit() else 0:06d}-{n:06d}"
            c.execute("""INSERT INTO pkg(pkg_id,order_id,tracking_no,shipped_at,status,msg_id,created)
                         VALUES(?,?,?,?,'在途',?,?)""",
                      (pid, oid, m["tracking_no"], m["at"], m["msg_id"], _now()))
            for x in 效果["件"]:
                c.execute("INSERT INTO pkg_item(pkg_id,item_id) VALUES(?,?)", (pid, int(x)))
            c.commit()
        现 = (_订单(c, oid) or {}).get("状态")
        目标 = K.订单该到哪一档(件进度(c, oid), _全部件(c, oid), 现)
        if 目标:
            # **一档一档走,不跳档。** 分批发货时第一个包裹发出:单子可能还在「已生产」,
            # 而目标是「已发货」—— 中间还隔着「待发货」。状态机不许跳档(跳过的档在库里看不出来),
            # 所以这里照 档序 依次推过去,每一步都过闸。
            import server
            路 = K.档序[K.档序.index(现) + 1: K.档序.index(目标) + 1] if 现 in K.档序 else [目标]
            for 下一档 in 路:
                rr = server.transit("bk-order", oid, 下一档, {"by": "工厂回传", "工厂消息号": m["msg_id"]},
                                    actor=actor)
                if not rr.get("ok"):
                    return False, f"口径判收下,状态机没让过({现}→{下一档}):{rr.get('reason')}"
                col = {"已生产": "produced_at", "已发货": "shipped_at"}.get(下一档)
                if col:
                    c.execute(f"UPDATE ordr SET {col}=? WHERE id=?", (m["at"], oid)); c.commit()
        return True, ""
    return True, ""


def _放行暂存(c, oid, 今天, actor):
    while True:
        放了 = False
        for m in c.execute("SELECT msg_id FROM factory_msg WHERE order_id=? AND result='暂存' ORDER BY at",
                           (oid,)).fetchall():
            if _判并落(c, m[0], 今天, actor)["结论"] != "暂存":
                放了 = True
        if not 放了:
            return


def 状态撑得住吗(order_id, 到, db=None):
    """状态机那道闸用:推到「到」这一档,各件的进度撑不撑得住。

    **不是「正好等于目标」,是「不超过目标」** —— 分批发货时目标可能是「已发货」,
    而中间要先过「待发货」;只认相等的话,中间那一步会被自己的闸拦下。
    """
    import factory_feed as K
    c = _c(db); ensure(c)
    目标 = K.订单该到哪一档(件进度(c, order_id), _全部件(c, order_id),
                          (_订单(c, order_id) or {}).get("状态"))
    c.close()
    if not 目标 or 到 not in K.档序 or 目标 not in K.档序:
        return False
    return K.档序.index(到) <= K.档序.index(目标)


def 人工回退(order_id, 原因, 理由, me, db=None):
    """店长:发错件 / 到店发现要返工 → 订单退一档(业务 2026-09-23)。

    **连带作废相关回传** —— 不作废的话工厂重新报完工会被判成「这几件收过了」,单子会卡死在那儿。
    """
    import factory_feed as K
    if not me:
        return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    c = _c(db); ensure(c)
    o = c.execute("SELECT id, status, shop, kind FROM ordr WHERE id=?", ((order_id or "").strip(),)).fetchone()
    if not o:
        c.close(); return dict(ok=False, code="NO_ORDER", reason=f"没有订单 {order_id}")
    if o["kind"] != "定制品订单":
        c.close(); return dict(ok=False, code="NOT_CUSTOM", reason="标品不走工厂回传,也没有这个回退")
    if o["shop"] != me.get("shop"):
        c.close(); return dict(ok=False, code="OTHER_SHOP", reason=f"这张单是「{o['shop']}」的,只能退本店订单")
    能, 话, 目标 = K.能不能回退(o["status"], me.get("role"), 原因, 理由)
    if not 能:
        c.close()
        log_op(me.get("name") or "未登录", "ordr", order_id, o["status"], "—", False, "ROLLBACK_DENY", 话[:120],
               {"role": me.get("role")})
        return dict(ok=False, code="ROLLBACK_DENY", reason=话)
    # 作废「退回之后要重来」的那几步:退到待发货 → 作废发出;退到生产中 → 连完工、质检一起作废
    要作废 = ["发出"] if 目标 == "待发货" else ["发出", "质检通过", "完工"]
    ids = [r[0] for r in c.execute(
        "SELECT msg_id FROM factory_msg WHERE order_id=? AND result='收下' AND void_at IS NULL "
        f"AND event IN ({','.join('?' * len(要作废))})", (order_id, *要作废))]
    for i in ids:
        c.execute("UPDATE factory_msg SET void_at=?, void_by=? WHERE msg_id=?", (_now(), me.get("no"), i))
    c.execute("UPDATE pkg SET void_at=?, void_reason=? WHERE order_id=? AND void_at IS NULL",
              (_now(), f"人工回退:{原因}", order_id))
    c.commit()
    import server
    if db: server.DB = db          # 副本上跑时,状态机也要走同一个库
    rr = server.transit("bk-order", order_id, 目标,
                        {"by": "人工回退", "人工回退": me.get("role"), "回退原因": 原因}, actor=me.get("name"))
    if not rr.get("ok"):
        c.close(); return dict(ok=False, code="BAD_STATE", reason=f"状态机没让过:{rr.get('reason')}")
    c.execute("""INSERT INTO order_rollback(order_id,at,by_no,cause,note,frm,too,freight)
                 VALUES(?,?,?,?,?,?,?,'公司承担')""",
              (order_id, _now(), me.get("no"), 原因, 理由, o["status"], 目标))
    c.commit(); c.close()
    log_op(me.get("name"), "ordr", order_id, o["status"], 目标, True, "ROLLBACK",
           f"{me.get('name')} 人工回退({原因}):{理由};作废 {len(ids)} 条回传,运费公司承担", {"role": me.get("role")})
    return dict(ok=True, code="ROLLBACK", 订单=order_id, 从=o["status"], 到=目标,
                作废回传=len(ids), reason=话 + f";已作废 {len(ids)} 条回传,工厂要重新报")


def 该催清单(今天, shop=None, db=None):
    """生产中的单里该去催工厂的。承诺完工日按**最新的**(延期后的)算。"""
    import factory_feed as K
    c = _c(db); ensure(c)
    out = []
    for o in c.execute("SELECT id, shop, advisor_no, cut_at, audit_at FROM ordr WHERE kind='定制品订单' "
                       "AND status='生产中'" + (" AND shop=?" if shop else ""), ((shop,) if shop else ())):
        承诺, 延 = _最新承诺(c, o["id"])
        接 = c.execute("SELECT 1 FROM factory_msg WHERE order_id=? AND event='接单' AND result='收下' "
                      "AND void_at IS NULL LIMIT 1", (o["id"],)).fetchone()
        要, 话 = K.该催("生产中", 承诺, bool(接), o["cut_at"] or o["audit_at"], 今天)
        if 要:
            out.append(dict(订单=o["id"], 门店=o["shop"], 顾问=o["advisor_no"], 为什么=话,
                            延期过=延, 承诺完工日=承诺))
    c.close()
    return out


def _最新承诺(c, oid):
    """(最新承诺完工日, 延期过几次)。延期后按新日子判超期,**但延了几次要看得见**(业务 09-23)。"""
    d = c.execute("SELECT new_promise, COUNT(*) FROM factory_delay WHERE order_id=? "
                  "GROUP BY order_id ORDER BY id DESC", (oid,)).fetchone()
    if d:
        新 = c.execute("SELECT new_promise FROM factory_delay WHERE order_id=? ORDER BY id DESC LIMIT 1",
                      (oid,)).fetchone()
        return 新[0], d[1]
    接 = c.execute("SELECT promise_date FROM factory_msg WHERE order_id=? AND event='接单' AND result='收下' "
                  "AND void_at IS NULL ORDER BY at DESC LIMIT 1", (oid,)).fetchone()
    return (接[0] if 接 else None), 0


def 待通知清单(shop=None, db=None):
    """工厂延期了、顾问还没告诉顾客的单。**提醒到顾问为止** —— 联系顾客是对外动作,由人做。"""
    c = _c(db); ensure(c)
    q = """SELECT d.id, d.order_id, d.old_promise, d.new_promise, d.reason, d.at, o.shop, o.advisor_no
           FROM factory_delay d JOIN ordr o ON o.id=d.order_id
           WHERE d.told_at IS NULL AND o.status NOT IN ('取消','完成')"""
    rs = [dict(r) for r in c.execute(q + (" AND o.shop=?" if shop else "") + " ORDER BY d.at DESC",
                                     ((shop,) if shop else ()))]
    c.close()
    return rs


def 标记已通知(delay_id, me, db=None):
    """顾问通知完顾客,点一下。**不点的话这份清单只进不出,两天后就没人看了。**"""
    if not me:
        return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    c = _c(db); ensure(c)
    d = c.execute("SELECT d.id, d.order_id, d.told_at, o.shop FROM factory_delay d "
                  "JOIN ordr o ON o.id=d.order_id WHERE d.id=?", (delay_id,)).fetchone()
    if not d:
        c.close(); return dict(ok=False, code="NO_DELAY", reason=f"没有这条延期记录 {delay_id}")
    if d["shop"] != me.get("shop"):
        c.close(); return dict(ok=False, code="OTHER_SHOP", reason="只能标本店的单")
    if d["told_at"]:
        c.close(); return dict(ok=False, code="DONE", reason=f"这条已经在 {d['told_at']} 标过了")
    c.execute("UPDATE factory_delay SET told_at=?, told_by=? WHERE id=?", (_now(), me.get("no"), delay_id))
    c.commit(); c.close()
    log_op(me.get("name"), "ordr", d["order_id"], "—", "—", True, "DELAY_TOLD",
           f"{me.get('name')} 已把延期告诉顾客", {"role": me.get("role")})
    return dict(ok=True, code="TOLD", 订单=d["order_id"], reason="已记下:你已经把延期告诉顾客了")


def 记事件(order_id, 动作, 时间=None, 包裹=None, 订单行=None, 经手人=None, 一句话="", db=None):
    """往订单日志里记一条**没有自己的表**的事件(签收那一侧用)。

    动作举例:包裹到店代收 / 取件方式 / 某件签收合身 / 某件不合身 / 顾客确认完成 / 顾问追认。
    时间不给就用现在;**时间由调用方给**才对得上演示世界的日子。
    """
    c = _c(db); ensure(c)
    c.execute("""INSERT INTO order_event(order_id,at,pkg_id,item_id,action,by_no,note)
                 VALUES(?,?,?,?,?,?,?)""",
              (order_id, 时间 or _now(), 包裹, int(订单行) if 订单行 else None, 动作, 经手人, 一句话))
    c.commit(); c.close()
    return dict(ok=True)


def 回传记录(order_id, db=None):
    c = _c(db); ensure(c)
    rs = [dict(r) for r in c.execute(
        "SELECT event 回传, at 工厂报的时间, factory 生产方, tracking_no 物流单号, promise_date 承诺完工日, "
        "result 处理, reason 为什么, void_at 作废时间 FROM factory_msg WHERE order_id=? ORDER BY at", (order_id,))]
    c.close()
    return rs


def 包裹们(order_id, db=None):
    c = _c(db); ensure(c)
    out = []
    for p in c.execute("SELECT * FROM pkg WHERE order_id=? ORDER BY created", (order_id,)):
        件 = [dict(r) for r in c.execute(
            "SELECT i.id 订单行, i.name 商品 FROM pkg_item p JOIN ordr_item i ON i.id=p.item_id WHERE p.pkg_id=?",
            (p["pkg_id"],))]
        out.append(dict(包裹=p["pkg_id"], 快递单号=p["tracking_no"], 发出=p["shipped_at"], 到店=p["arrived_at"],
                        状态=("已作废" if p["void_at"] else p["status"]), 件=件))
    c.close()
    return out


def 订单日志(order_id, db=None):
    """这张单发生过什么 —— 状态变化、工厂回传(含拒收和作废)、人工回退、延期,按时间排成一条。

    业务 09-23:「每个订单都会有独立日志」。**拒掉的、作废的也要在里面** ——
    只留成功的,出了事查不出「工厂当时到底报了什么」。
    """
    c = _c(db); ensure(c)
    行 = []
    for r in c.execute("SELECT ts, actor, frm, too, allowed, code, reason FROM op_log "
                       "WHERE machine='ordr' AND target=? ORDER BY ts", (order_id,)):
        行.append(dict(时间=r["ts"], 谁=r["actor"], 什么=("状态:" + (r["frm"] or "—") + "→" + (r["too"] or "—"))
                       if r["frm"] or r["too"] else r["code"], 说明=r["reason"],
                       允许=bool(r["allowed"])))
    for r in c.execute("SELECT at, event, factory, result, reason, void_at FROM factory_msg WHERE order_id=? "
                       "ORDER BY at", (order_id,)):
        行.append(dict(时间=r["at"], 谁=r["factory"] or "工厂", 什么="工厂回传:" + r["event"],
                       说明=f"{r['result']}:{r['reason'] or ''}" + ("(已作废)" if r["void_at"] else ""),
                       允许=r["result"] == "收下"))
    for r in c.execute("SELECT at, by_no, cause, note, frm, too FROM order_rollback WHERE order_id=? ORDER BY at",
                       (order_id,)):
        行.append(dict(时间=r["at"], 谁=r["by_no"], 什么=f"人工回退({r['cause']}):{r['frm']}→{r['too']}",
                       说明=r["note"], 允许=True))
    for r in c.execute("SELECT at, pkg_id, item_id, action, by_no, note FROM order_event WHERE order_id=? "
                       "ORDER BY at", (order_id,)):
        行.append(dict(时间=r["at"], 谁=r["by_no"] or "—", 什么=r["action"]
                       + (f"(包裹 {r['pkg_id']})" if r["pkg_id"] else "")
                       + (f"(第 {r['item_id']} 行)" if r["item_id"] else ""),
                       说明=r["note"], 允许=True))
    for r in c.execute("SELECT at, old_promise, new_promise, reason, told_at, told_by FROM factory_delay "
                       "WHERE order_id=? ORDER BY at", (order_id,)):
        行.append(dict(时间=r["at"], 谁="工厂", 什么="延期通知",
                       说明=f"{r['old_promise'] or '原无'} → {r['new_promise']}"
                            + (f";原因 {r['reason']}" if r["reason"] else "")
                            + (f";{r['told_at']} 已通知顾客" if r["told_at"] else ";**还没通知顾客**"),
                       允许=True))
    c.close()
    return sorted(行, key=lambda x: str(x["时间"] or ""))
