"""交付告知 · 记「已告知」(写)—— 用户 2026-11-15 拍:「发」= 记一笔已告知,文字给顾问复制去发。

只记**告知过**,不记**签收**(signed_at 不动,判责读签收)。只记本人看得到的单(范围同 api._订单范围),
只记标品订单,只记已经交到顾客手上那一段(已发货 / 待完成 / 完成),同一单记过一次就不再覆盖。
告知了哪几条**由起草现算**(knowledge/delivery_notice.py),不收调用方给的条目 —— 免得记下的和发出去的不是同一份。
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
from oplog import log_op  # noqa: E402

DB = os.path.join(HERE, "lanxiu.db")
渠道们 = ("微信", "电话", "短信", "当面", "小程序")
交付之后 = ("已发货", "待完成", "完成")


def _c(db=None):
    c = sqlite3.connect(db or DB)
    c.row_factory = sqlite3.Row
    return c


def 记已告知(order_id, channel, me, 范围where="", 范围args=(), db=None):
    """→ dict(ok, code, reason, …)。范围where / 范围args 由 api 层按身份给(同 _订单范围),这里不重算身份口径。"""
    import delivery_notice as _dn
    import worldclock
    if not me:
        return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    ch = (channel or "").strip()
    if ch not in 渠道们:
        return dict(ok=False, code="BAD_CHANNEL", reason=f"渠道只认 {' / '.join(渠道们)},你给的是「{channel}」—— 问清用什么发的再记")
    c = _c(db)
    有 = {r[1] for r in c.execute("PRAGMA table_info(delivery_notice)")}
    if "notified_at" not in 有:
        c.close()
        return dict(ok=False, code="NO_COLUMN", reason="这个库还没做到第 2 条迁移(交付告知没有「已告知」那几列)—— 跑 python3 backend/migrate.py")
    o = c.execute("SELECT o.id, o.kind, o.status FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id WHERE o.id=?"
                  + 范围where, (order_id, *范围args)).fetchone()
    if not o:
        在 = c.execute("SELECT 1 FROM ordr WHERE id=?", (order_id,)).fetchone()
        c.close()
        return dict(ok=False, code="OUT_OF_SCOPE" if 在 else "NO_ORDER",
                    reason=(f"订单 {order_id} 不在你能看的范围里" if 在 else f"没有订单 {order_id}"))
    if o["kind"] != "标品订单":
        c.close()
        return dict(ok=False, code="NOT_STANDARD", reason="定制单的交付告知走交付卡签收(signed_at),这个口只记标品的「已告知」")
    if o["status"] not in 交付之后:
        c.close()
        return dict(ok=False, code="NOT_DELIVERED", reason=f"这单现在是「{o['status']}」,还没交到顾客手上 —— 交付之后再告知")
    旧 = c.execute("SELECT notified_at, notified_by FROM delivery_notice WHERE order_id=?", (order_id,)).fetchone()
    if 旧 and 旧["notified_at"]:
        c.close()
        return dict(ok=False, code="DONE", reason=f"这单已经在 {旧['notified_at']} 由 {旧['notified_by']} 记过已告知了,不覆盖")
    名们 = [dict(名=r["name"]) for r in c.execute("SELECT name FROM ordr_item WHERE order_id=? ORDER BY id", (order_id,))]
    稿 = _dn.起草(名们)
    if not 稿["适用"]:
        c.close()
        return dict(ok=False, code="NOTHING_TO_NOTIFY", reason="这单的商品都没有对得上的告知项 —— 不用记,也别硬凑一条")
    号 = [x["编号"] for x in 稿["适用"]]
    时 = worldclock.当下().strftime("%Y-%m-%d %H:%M")
    if 旧:
        c.execute("UPDATE delivery_notice SET notified_at=?, notified_by=?, notified_channel=?, notified_items=? WHERE order_id=?",
                  (时, me.get("no"), ch, json.dumps(号), order_id))
    else:
        c.execute("INSERT INTO delivery_notice(order_id, notified_at, notified_by, notified_channel, notified_items) VALUES(?,?,?,?,?)",
                  (order_id, 时, me.get("no"), ch, json.dumps(号)))
    c.commit(); c.close()
    log_op(me.get("name"), "ordr", order_id, "—", "已告知", True, "DELIVERY_NOTIFIED",
           f"{me.get('name')} 经{ch}告知了第 {'、'.join(map(str, 号))} 条", {"role": me.get("role")}, db=db)
    return dict(ok=True, code="NOTIFIED", 订单=order_id, 告知了=号, 渠道=ch, 时间=时,
                reason="已记下:交付告知已发给顾客(**这不是顾客签收** —— 签收另记)")
