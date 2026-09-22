# -*- coding: utf-8 -*-
"""下单写口 —— **开单 / 确认下单。** 口径在 knowledge/order_place.py(业务 2026-09-22)。

业务定的顺序:**先开单(订单里有这一件)→ 再量 → 量完绑到这一件 → 确认下单**。
付款默认在确认下单时已经完成:定制单确认后**跳过「待付款」,直接进「待审核」**。
开单后、确认前停在新状态「待确认」(不进业绩、不催付款、可直接取消)。

原来系统里**没有任何入口能下一张单** —— 库里的订单全是造数据直插的。
「每一件都要有绑定的下单量体」这条硬规矩,没有下单入口就无处可守。

这一份被两个入口共用(页面 / 智能体工具),和 tasks.py 同一个理由。

## 谁能做什么

  开单      顾问 / 店长,只给**本店**客户开;每一件定制款都要指明给谁做(着装人)——
            下单量体量的必须是穿这件的人,不知道是谁就没法量
  确认下单  顾问 / 店长;**逐件过闸**(order_place.逐件判),有一件不过整单不许确认;
            闸同时挂在订单状态机的「待确认 → 待审核」上,后台改状态也绕不过(同开裁那道闸)
"""
import os, sys, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
from oplog import log_op

下单角色 = ("顾问", "店长")


def rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def _deny(me, code, reason, key="—"):
    log_op((me or {}).get("name") or "未登录", "ordr", key, "—", "—", False, code,
           reason[:120], {"role": (me or {}).get("role")})
    return dict(ok=False, code=code, reason=reason)


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def 需要的项(pattern_code):
    """这个版型下单量体要量哪几项 —— **尺码表里真要比对的部位**对应的量体项。
    认不出版型 / 没有尺码表 → None(判不了,不许当成「不缺」)。"""
    import fitting
    if not pattern_code:
        return None
    p = rows("SELECT code, xz FROM pattern WHERE code=?", pattern_code)
    parts = {r["item"] for r in rows("SELECT DISTINCT item FROM size_spec WHERE pattern=?", pattern_code)}
    if not p or not parts:
        return None
    E = fitting.ease()
    out = set()
    for part in parts:
        t = E.get(part)
        if not t or t[0] is None:
            continue                                  # 不比对的部位(马面宽 / 上襦衣长)
        item = "胸上围" if (part == "裙腰围" and p[0]["xz"] == "XZ01") else t[2]
        out.add(item)
    return sorted(out) or None


def 过闸(order_id):
    """这张单能不能确认下单。返回 (结论, 理由, 逐件明细)。**不写库**,确认和状态机共用这一个判断。"""
    import measure, order_place
    o = rows("SELECT id, status, kind, created FROM ordr WHERE id=?", (order_id or "").strip())
    if not o:
        return "判不了", f"没有订单 {order_id}", []
    o = o[0]
    明细, 各件 = [], []
    for it in rows("SELECT i.id, i.name, i.wearer_id, p.pattern, p.kind pkind FROM ordr_item i "
                   "LEFT JOIN product p ON p.spu=i.spu WHERE i.order_id=? ORDER BY i.id", o["id"]):
        记 = [dict(着装人=r["wearer_id"], 时间=r["measured_at"], 量体人=r["measured_by_no"], 方式=r["method"],
                  项=r["name"], 值=r["value"], 订单行=r["order_item_id"])
             for r in rows("SELECT m.*, mi.name FROM measure_rec m JOIN measure_item mi ON mi.code=m.item "
                           "WHERE m.wearer_id=?", it["wearer_id"])] if it["wearer_id"] else []
        类型 = "定制品" if (o["kind"] == "定制品订单") else "标品"
        g, w = order_place.逐件判(类型, it["wearer_id"], o["created"], measure.场次(记), it["id"],
                                 需要的项(it["pattern"]))
        各件.append((g, f"「{it['name']}」{w}"))
        明细.append({"订单行": it["id"], "商品": it["name"], "着装人": it["wearer_id"], "能不能确认": g, "为什么": w})
    结论, 话 = order_place.整单(各件)
    return 结论, 话, 明细


def open_order(d, me):
    """开一张定制单,停在「待确认」。d: customer_id, items=[{spu 或 sku, wearer_id, qty}]"""
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 下单角色:
        return _deny(me, "ROLE", f"开单须由顾问或店长操作,你是「{me.get('role')}」")
    cid = (d.get("customer_id") or "").strip()
    cu = rows("SELECT id, shop FROM customer WHERE id=?", cid)
    if not cu:
        return dict(ok=False, code="NO_CUSTOMER", reason=f"没有客户 {cid}")
    if cu[0]["shop"] != me.get("shop"):
        return _deny(me, "OTHER_SHOP", f"这位客户在「{cu[0]['shop']}」,只能给本店客户开单", cid)
    items = d.get("items") or []
    if not items:
        return dict(ok=False, code="NO_ITEM", reason="一件商品都没有")
    行们 = []
    for x in items:
        key = str(x.get("sku") or x.get("spu") or "").strip()
        s = rows("SELECT s.code sku, s.spu, s.price, p.name, p.kind, p.pattern FROM sku s JOIN product p ON p.spu=s.spu "
                 "WHERE s.code=? OR s.spu=? ORDER BY s.code LIMIT 1", key, key)
        if not s:
            return dict(ok=False, code="NO_SKU", reason=f"没有商品「{key}」")
        s = s[0]
        if s["kind"] != "定制品":
            return dict(ok=False, code="NOT_CUSTOM", reason=f"「{s['name']}」是标品 —— 这个入口只开定制单,标品流程不变")
        wid = (x.get("wearer_id") or "").strip()
        if not wid:
            return dict(ok=False, code="NEED_WEARER",
                        reason=f"「{s['name']}」要指明给谁做(着装人)—— 下单量体量的必须是穿这件的人")
        w = rows("SELECT id FROM wearer WHERE id=? AND customer_id=?", wid, cid)
        if not w:
            return dict(ok=False, code="BAD_WEARER", reason=f"着装人 {wid} 不是客户 {cid} 名下的")
        qty = int(x.get("qty") or 1)
        行们.append((s, wid, qty))
    mx = rows("SELECT MAX(CAST(id AS INTEGER)) m FROM ordr")[0]["m"] or 0
    oid, now = str(int(mx) + 1), _now()
    amt = round(sum((s["price"] or 0) * q for s, _, q in 行们), 2)
    import fsm
    with sqlite3.connect(DB) as c:
        c.execute("""INSERT INTO ordr(id,customer_id,kind,status,advisor_no,shop,source,delivery,amount,payable,
                     created,updated,prd_status,goods_amount,freight,received,refund_status,appt_src)
                     VALUES(?,?,'定制品订单','待确认',?,?,'门店 Pad','配送到店',?,?,?,?,?,?,0,0,'未退款','未接入')""",
                  (oid, cid, me["no"], me.get("shop"), amt, amt, now, now,
                   fsm.ORDER_PRD.get("待确认", "待付款"), amt))
        # **版型版本在开单这一刻记下快照**(grading_check 查)—— 现算给的是今天那一版,
        # 版型改过之后就对不上当初量的、裁的是哪一版
        for s, wid, q in 行们:
            pv = c.execute("SELECT version FROM pattern WHERE code=?", (s["pattern"],)).fetchone() \
                if s["pattern"] else None
            c.execute("""INSERT INTO ordr_item(order_id,sku,name,tag,price,qty,spu,base_amount,custom_amount,total,
                         wearer_id,pattern_version,pattern_version_src) VALUES(?,?,?,'定制品',?,?,?,?,0,?,?,?,?)""",
                      (oid, s["sku"], s["name"], s["price"], q, s["spu"], (s["price"] or 0) * q,
                       (s["price"] or 0) * q, wid, pv[0] if pv else None, "开单时记的" if pv else None))
    log_op(me["name"], "ordr", oid, "—", "待确认", True, "OPEN",
           f"{me['name']} 给 {cid} 开定制单 {oid},{len(行们)} 件,停在待确认", {"role": me["role"]})
    明 = rows("SELECT id, name, wearer_id FROM ordr_item WHERE order_id=? ORDER BY id", oid)
    return dict(ok=True, code="OPEN", 订单=oid, 状态="待确认", 件=明,
                reason=f"已开单 {oid},停在「待确认」。**下一步:给每一件量下单量体并绑到这一件**"
                       f"(record_measure 带 order_id + item),量完再确认下单")


def confirm_order(d, me):
    """确认下单:待确认 → 待审核(定制单确认即已付款)。**逐件过闸,有一件不过整单拒绝。**"""
    import fsm
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 下单角色:
        return _deny(me, "ROLE", f"确认下单须由顾问或店长操作,你是「{me.get('role')}」")
    oid = (d.get("order_id") or "").strip()
    o = rows("SELECT id, status, shop, amount FROM ordr WHERE id=?", oid)
    if not o: return dict(ok=False, code="NO_ORDER", reason=f"没有订单 {oid}")
    o = o[0]
    if o["shop"] != me.get("shop"):
        return _deny(me, "OTHER_SHOP", f"这张单是「{o['shop']}」的,只能确认本店订单", oid)
    结论, 话, 明细 = 过闸(oid)
    ok, code, why = fsm.check("bk-order", o["status"], "待审核",
                              {"kind": "定制品订单", "下单过闸": 结论, "下单过闸_为什么": 话})
    if not ok and code != "ORDER_GATE":
        return dict(ok=False, code="BAD_STATE", reason=f"这张单现在是「{o['status']}」,不能确认下单:{why}")
    if not ok:
        _deny(me, "ORDER_GATE", 话, oid)
        return dict(ok=False, code="ORDER_GATE", reason=话, 逐件=明细,
                    能做什么="给缺下单量体的那几件量体并绑上(record_measure 带 order_id + item),或先定着装人")
    now = _now()
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE ordr SET status='待审核', prd_status=?, paid_at=?, received=amount, updated=? "
                  "WHERE id=? AND status='待确认'", (fsm.ORDER_PRD["待审核"], now, now, oid))
    log_op(me["name"], "ordr", oid, "待确认", "待审核", True, "CONFIRM",
           f"{me['name']} 确认下单 {oid}:{话}(付款在确认时已完成)", {"role": me["role"]})
    return dict(ok=True, code="CONFIRM", 订单=oid, 从="待确认", 到="待审核", 逐件=明细,
                reason=f"已确认下单:{话}。付款在确认时已完成,订单进「待审核」")
