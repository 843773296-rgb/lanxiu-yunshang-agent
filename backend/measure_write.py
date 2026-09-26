# -*- coding: utf-8 -*-
"""量体录入写口 —— **顾问量完,有地方录了。**

原来库里所有量体都是造数据时直插的:规则(亲自服务、超期复量、推荐尺码、判全定制、
白坯必试)一样不缺,**顾问量完却没地方录** —— 没有入口的能力等于没做。

口径在 `knowledge/measure.py`(业务 2026-09-22):按次登记;订单以绑定到订单行的
下单量体为准,没有就不许下单;只看人时取最近一整次亲自量的,缺项不拼。

这一份被两个入口共用(页面 / 智能体工具),和 `tasks.py` 同一个理由。

## 谁能录、录什么

  · 顾问 / 店长,**只能录本店客户的着装人**;量体人就是登录的人,**不收工号参数** ——
    收了参数就能替别人登一次自己没量的尺寸,而返修判责时「谁量的」是要追的
  · **身体数据先要有同意**:着装人要有有效的「身体数据」授权,未满 14 岁还要「未成年人」授权
    (和推算、看着装人档案走的是同一道门)
  · 方式 / 三个条件 / 合理范围 → `measure.校验一次`,**不改数、不猜单位**
  · 可以绑一件订单行(下单量体):那一件必须是**给这个着装人做的**
"""
import os, sys, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
from oplog import log_op

录入角色 = ("顾问", "店长")


def rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def _deny(me, code, reason, key="—"):
    log_op((me or {}).get("name") or "未登录", "measure_rec", key, "—", "—", False, code,
           reason[:120], {"role": (me or {}).get("role")})
    return dict(ok=False, code=code, reason=reason)


def _now():
    """**世界的当下**,不是机器的当下。

    ⚠️ 2026-09-26:`backend/booking.py` 的同名函数用的是机器时钟,写出来的
    `schedule.assigned_at` 落在机器的今天、而世界停在别的日子,然后每日平移
    把它**又往后挪一天** —— 这个 bug **不会自愈**,平移每跑一次就多推一天。
    `backend/worldclock_check.py` 扫出这个文件是同一个形状,一起修。
    判据:那一列会不会被 shift_world 平移;会的话就必须用世界时钟写。
    """
    import worldclock
    return worldclock.当下().strftime("%Y-%m-%d %H:%M")


def _周岁(birthday, on):
    try:
        b = str(birthday)[:10]; o = str(on)[:10]
        return int(o[:4]) - int(b[:4]) - (1 if o[5:] < b[5:] else 0)
    except Exception:
        return None


def record(d, me):
    """登记一次量体。d: wearer_id, values{量体项名:值}, method, inner, shoe, breath,
    可选 order_id + item(订单行号或商品名)—— 给了就是这一件的**下单量体**。"""
    import measure
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 录入角色:
        return _deny(me, "ROLE", f"量体录入须由顾问或店长操作,你是「{me.get('role')}」")
    wid = (d.get("wearer_id") or "").strip()
    w = rows("SELECT w.*, c.shop cshop FROM wearer w LEFT JOIN customer c ON c.id=w.customer_id "
             "WHERE w.id=?", wid)
    if not w:
        return dict(ok=False, code="NO_WEARER", reason=f"没有着装人「{wid}」—— 先查这个人的着装人编号(W 开头),"
                                                      "客户号(C 开头)不是着装人")
    w = w[0]
    if w["cshop"] != me.get("shop"):
        return _deny(me, "OTHER_SHOP", f"这位着装人的档案在「{w['cshop']}」,只能录本店客户", wid)
    # 身体数据的同意 —— 和推算、看档案同一道门
    ok = rows("SELECT 1 FROM consent WHERE wearer_id=? AND scope='身体数据' AND revoked_at IS NULL", wid)
    if not ok:
        return dict(ok=False, code="NO_CONSENT",
                    reason="这位着装人**没有有效的身体数据同意** —— 先让本人(或监护人)签同意,再量再录")
    now = _now()
    岁 = _周岁(w["birthday"], now)
    if 岁 is not None and 岁 < 14 and not rows(
            "SELECT 1 FROM consent WHERE wearer_id=? AND scope='未成年人' AND revoked_at IS NULL", wid):
        return dict(ok=False, code="NO_GUARDIAN",
                    reason="不满十四周岁,**缺监护人的未成年人同意** —— 先签,再量再录")
    值们 = d.get("values") or {}
    条件 = {"内搭": d.get("inner"), "鞋": d.get("shoe"), "呼吸": d.get("breath")}
    坏 = measure.校验一次(d.get("method"), 条件, 值们)
    if 坏:
        return dict(ok=False, code="BAD_MEASURE", reason="这次量体登不了:" + ";".join(坏), 问题=坏)
    # 绑订单行(下单量体)
    行 = None
    if d.get("order_id") or d.get("item"):
        oid = (d.get("order_id") or "").strip()
        its = rows("SELECT i.id, i.name, i.wearer_id, o.kind, o.shop FROM ordr_item i "
                   "JOIN ordr o ON o.id=i.order_id WHERE o.id=?", oid)
        if not its:
            return dict(ok=False, code="NO_ORDER", reason=f"没有订单 {oid}")
        s = str(d.get("item") or "").strip()
        hit = [r for r in its if str(r["id"]) == s] or [r for r in its if r["name"] == s] \
            or [r for r in its if s and s in (r["name"] or "")]
        if len(hit) != 1:
            return dict(ok=False, code="NO_ITEM",
                        reason=(f"这张单里没有「{s}」" if not hit else f"这张单里有 {len(hit)} 件对得上「{s}」,请给订单行号")
                               + ";这张单的商品:" + ";".join(f"{r['id']} {r['name']}" for r in its))
        行 = hit[0]
        if 行["kind"] != "定制品订单":
            return dict(ok=False, code="NOT_CUSTOM", reason="标品按尺码卖,不需要下单量体")
        if 行["wearer_id"] != wid:
            return dict(ok=False, code="WRONG_WEARER",
                        reason=f"这一件是给「{行['wearer_id'] or '(还没定给谁)'}」做的,不是 {wid} —— "
                               "**下单量体量的必须是穿这件的人**;还没定给谁的先定着装人")
    code = {r["name"]: r["code"] for r in rows("SELECT code, name FROM measure_item")}
    with sqlite3.connect(DB) as c:
        for 名, v in 值们.items():
            c.execute("INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by_no,measured_at,method,"
                      "wearer_id,order_item_id,cond_inner,cond_shoe,cond_breath) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (w["customer_id"], "现场录入", code[名], round(float(v), 1), me["no"], now,
                       d.get("method"), wid, 行["id"] if 行 else None,
                       条件["内搭"], 条件["鞋"], 条件["呼吸"]))
    log_op(me["name"], "measure_rec", wid, "—", "下单量体" if 行 else "量体", True, "MEASURE",
           f"{me['name']} {d.get('method')}量 {wid} 共 {len(值们)} 项"
           + (f",绑订单 {d.get('order_id')} 第 {行['id']} 行「{行['name']}」" if 行 else ""),
           {"role": me["role"]})
    return dict(ok=True, code="MEASURE", 着装人=wid, 时间=now, 量体人=me["no"], 方式=d.get("method"),
                项数=len(值们), 绑定订单行=(行["id"] if 行 else None),
                reason=(f"已登记一次量体({len(值们)} 项)"
                        + (f",作为订单 {d.get('order_id')}「{行['name']}」的**下单量体** —— 这一件以它为准"
                           if 行 else "")))
