# -*- coding: utf-8 -*-
"""报修的写口 —— 新建返修单、店长判责、推进、修好回店的签收。

口径在 `knowledge/repair.py`(业务 2026-09-22 逐条拍板)。页面和智能体工具共用这一份。

## 谁能做什么

  新建      顾问 / 店长,本店的单。**要说清是哪一件** —— 一张单有好几件而没说哪件,返回「哪一件?」,不挑第一件
            (交付签收登记「不合身」时自动建一张,来源「签收不合身」)
  判责      **只有店长**:谁承担、返修还是重做、判给顾客的要录预估费用并记下顾客同意(同意要写凭据)
            判完了才从「待确认」进「待入库」
  推进      顾问 / 店长:待入库 → 待处理(衣服收回来了)→ 处理中(送修)→ 待签收(修好回店)
  签收      修好回店后顾客在手机上点「试穿合身」领 6 位码,导购核验 → 已完成(和交付签收同一套码)

## 判责看哪一次量体

**只认这一件订单行上绑定的下单量体**(`measure.以哪次为准(场次, 订单行=…)`)。
没绑 → 「这一件没有下单量体,核对不了留存数据」—— **不退回去用最近一次**:
判责取决于「成衣和留存数据对不对得上」,拿错一次量体就是收错了人的钱。
量体按**着装人**取,不按客户号取(一家人的尺寸不许混,同 kb_fit 那次)。
"""
import os, sys, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
from oplog import log_op

导购角色 = ("顾问", "店长")


def rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _deny(me, code, reason, key="—"):
    log_op((me or {}).get("name") or "未登录", "maintain", key, "—", "—", False, code,
           reason[:120], {"role": (me or {}).get("role")})
    return dict(ok=False, code=code, reason=reason)


def 下单量体(order_item_id):
    """这一件的下单量体。返回 (场次 | None, 一句人话)。**按着装人取,只认绑在这一行上的。**"""
    import measure
    it = rows("SELECT wearer_id FROM ordr_item WHERE id=?", order_item_id)
    if not it or not it[0]["wearer_id"]:
        return None, "这一件**没定给谁做**(没有着装人)—— 核对不了留存数据"
    记 = [dict(着装人=r["wearer_id"], 时间=r["measured_at"], 量体人=r["measured_by_no"], 方式=r["method"],
              项=r["name"], 值=r["value"], 订单行=r["order_item_id"])
         for r in rows("SELECT m.*, mi.name FROM measure_rec m JOIN measure_item mi ON mi.code=m.item "
                       "WHERE m.wearer_id=?", it[0]["wearer_id"])]
    s, 话 = measure.以哪次为准(measure.场次(记), 订单行=order_item_id)
    return s, (话 if s else "这一件**没有下单量体** —— 核对不了留存数据,判责判不了(不拿别的量体顶)")


def _找件(order_id, item):
    its = rows("SELECT i.id, i.name, i.wearer_id, o.shop, o.customer_id, o.kind, o.status FROM ordr_item i "
               "JOIN ordr o ON o.id=i.order_id WHERE o.id=? ORDER BY i.id", (order_id or "").strip())
    if not its:
        return None, dict(ok=False, code="NO_ORDER", reason=f"没有订单 {order_id}")
    s = str(item or "").strip()
    if not s:
        if len(its) == 1:
            return its[0], None
        return None, dict(ok=False, code="WHICH_ITEM",
                          reason=f"这张单有 {len(its)} 件,要修的是哪一件?—— 不替你挑:"
                                 + ";".join(f"{r['id']} {r['name']}" for r in its))
    hit = [r for r in its if str(r["id"]) == s] or [r for r in its if r["name"] == s] \
        or [r for r in its if s in (r["name"] or "")]
    if len(hit) != 1:
        return None, dict(ok=False, code="WHICH_ITEM",
                          reason=(f"这张单里没有「{s}」" if not hit else f"有 {len(hit)} 件对得上「{s}」,请给订单行号")
                                 + ";这张单的商品:" + ";".join(f"{r['id']} {r['name']}" for r in its))
    return hit[0], None


def 判责建议(来源, issue, order_item_id, 不合身事实=None):
    """给店长看的**建议**,不是结论。返回 dict。"""
    import liability, pickup
    量, 量话 = 下单量体(order_item_id)
    if 来源 == "签收不合身":
        f = 不合身事实 or {}
        谁, 怎么办, 话 = pickup.不合身判责(f.get("matches_record") if 量 else None,
                                        f.get("other_defect"), f.get("our_fault"))
        return dict(建议责任方=谁, 建议处理=怎么办, 为什么=话, 下单量体=量话)
    # 售后:走返修判定表。尺寸类的「量体记录完整」只认这一件的下单量体 —— 没有就判不了,不拿别的顶
    # 签收时顾客确认过试穿合身 → 之后的尺寸问题顾客承担(业务 09-22;工艺瑕疵不在此列,判定表里排在前面)
    oid = (rows("SELECT order_id FROM ordr_item WHERE id=?", order_item_id) or [{}])[0].get("order_id")
    签 = rows("SELECT fit_result FROM pickup WHERE order_id=?", oid) if oid else []
    # 没有下单量体 = 记录缺失(我方没按规矩量),不是「拿别的量体顶」;连给谁做都不知道才判不了
    有人 = bool((rows("SELECT wearer_id FROM ordr_item WHERE id=?", order_item_id) or [{}])[0].get("wearer_id"))
    j = liability.judge(issue, measure_full=(True if 量 else (False if 有人 else None)),
                        签收合身=bool(签 and 签[0]["fit_result"] == "合身"))
    谁 = {"我方": "企业", "客方": "顾客"}.get(j.get("责任"), "判不了")
    return dict(建议责任方=谁, 建议处理=j.get("处理") or "转人工", 为什么=j.get("依据") or "",
                归类=j.get("归类"), 下单量体=量话)


def create(d, me, 来源="售后"):
    """新建一张返修单,停在「待确认」等店长判责。"""
    import repair
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 导购角色:
        return _deny(me, "ROLE", f"新建返修单须由顾问或店长操作,你是「{me.get('role')}」")
    it, err = _找件(d.get("order_id"), d.get("item"))
    if err: return err
    if it["shop"] != me.get("shop"):
        return _deny(me, "OTHER_SHOP", f"这一单是「{it['shop']}」的,只能给本店的单报修", d.get("order_id"))
    issue = (d.get("issue") or "").strip()
    if not issue:
        return dict(ok=False, code="NO_ISSUE", reason="写清哪里要修(比如「下摆开线」「腰围紧 2cm」)")
    if 来源 not in repair.来源:
        return dict(ok=False, code="BAD_SOURCE", reason=f"来源只认 {' / '.join(repair.来源)}")
    mid = "MX" + datetime.datetime.now().strftime("%m%d%H%M%S%f")[:14]
    now = _now()
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO maintain(id,order_id,customer_id,item,status,issue,shop,advisor_no,created,updated,"
                  "ext_system,order_item_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (mid, d.get("order_id"), it["customer_id"], it["name"], "待确认", issue, it["shop"],
                   me["no"], now, now, "澜绣", it["id"]))
        c.execute("INSERT INTO maintain_decision(maintain_id, source) VALUES(?,?)", (mid, 来源))
    建议 = 判责建议(来源, issue, it["id"], d.get("不合身事实"))
    log_op(me["name"], "maintain", mid, "—", "待确认", True, "REPAIR_NEW",
           f"{me['name']} 新建返修单 {mid}({来源}):订单 {d.get('order_id')}「{it['name']}」{issue[:40]}",
           {"role": me["role"]})
    return dict(ok=True, code="REPAIR_NEW", 返修单=mid, 状态="待确认", 件=it["name"], 来源=来源, 判责建议=建议,
                reason="已建返修单,**等店长判责**(谁承担、返修还是重做;判给顾客的要录预估费用、记下顾客同意)。"
                       "判责建议不是结论")


def decide(d, me):
    """店长判责。判完了(企业承担,或顾客承担且录了费用、记了同意)就从「待确认」进「待入库」。"""
    import repair
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") != "店长":
        return _deny(me, "ROLE", f"判责和收费由店长确认(业务 09-22),你是「{me.get('role')}」")
    m = rows("SELECT * FROM maintain WHERE id=?", (d.get("maintain_id") or "").strip())
    if not m: return dict(ok=False, code="NO_REPAIR", reason=f"没有返修单 {d.get('maintain_id')}")
    m = m[0]
    if m["shop"] != me.get("shop"):
        return _deny(me, "OTHER_SHOP", f"这张返修单是「{m['shop']}」的", m["id"])
    if m["status"] != "待确认":
        return dict(ok=False, code="BAD_STATE", reason=f"这张返修单现在是「{m['status']}」,已经判过了")
    同意 = bool(d.get("customer_agreed"))
    凭据 = (d.get("agree_note") or "").strip()
    if 同意 and not 凭据:
        return dict(ok=False, code="NO_AGREE_NOTE", reason="记「顾客同意付费」要写凭据(比如「顾客电话同意 300 元」)—— 没有凭据的同意等于没问")
    记录 = dict(判责人=me["no"], 责任方=d.get("liable"), 处理=d.get("plan"),
               预估费用=d.get("fee_est"), 顾客同意于=_now() if 同意 else None)
    能, 话 = repair.判完了没有(记录)
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE maintain_decision SET liable=?, plan=?, fee_est=?, customer_agreed_at=?, agree_note=?, "
                  "decided_by=?, decided_at=? WHERE maintain_id=?",
                  (d.get("liable"), d.get("plan"), d.get("fee_est"), 记录["顾客同意于"], 凭据 or None,
                   me["no"], _now(), m["id"]))
    if not 能:
        log_op(me["name"], "maintain", m["id"], "待确认", "待确认", True, "REPAIR_DECIDE_PART", 话[:120], {})
        return dict(ok=True, code="REPAIR_DECIDE_PART", 返修单=m["id"], 状态="待确认",
                    reason=f"判责先记下了,**还不能开工**:{话}")
    return _推(m, "待入库", me, "REPAIR_DECIDE", f"{me['name']} 判责:{话}")


def _推(m, to, me, code, why):
    """走维保状态机。闸在状态机上(fsm 的 bk-maintain),这里不自己判能不能流转。"""
    import fsm, repair
    dec = (rows("SELECT * FROM maintain_decision WHERE maintain_id=?", m["id"]) or [{}])[0]
    能, _ = repair.判完了没有(dict(判责人=dec.get("decided_by"), 责任方=dec.get("liable"), 处理=dec.get("plan"),
                                 预估费用=dec.get("fee_est"), 顾客同意于=dec.get("customer_agreed_at")))
    ok, c, reason = fsm.check("bk-maintain", m["status"], to,
                              {"判完了": 能, "签收核验": "已核验" if dec.get("return_fit_at") else None})
    if not ok:
        return dict(ok=False, code=c, reason=reason)
    with sqlite3.connect(DB) as cx:
        n = cx.execute("UPDATE maintain SET status=?, updated=? WHERE id=? AND status=?",
                       (to, _now(), m["id"], m["status"])).rowcount
    if n != 1:
        return dict(ok=False, code="RACE", reason="这张返修单的状态刚被别人改了,请刷新再看")
    log_op(me["name"] if me else "顾客", "maintain", m["id"], m["status"], to, True, code, why[:120], {})
    return dict(ok=True, code=code, 返修单=m["id"], 从=m["status"], 到=to, reason=why)


def advance(d, me):
    """推进一档:待入库 → 待处理 → 处理中 → 待签收。**待签收 → 已完成只能走顾客的码**,这里不给。"""
    import repair
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 导购角色:
        return _deny(me, "ROLE", f"推进返修单须由顾问或店长操作,你是「{me.get('role')}」")
    m = rows("SELECT * FROM maintain WHERE id=?", (d.get("maintain_id") or "").strip())
    if not m: return dict(ok=False, code="NO_REPAIR", reason=f"没有返修单 {d.get('maintain_id')}")
    m = m[0]
    if m["shop"] != me.get("shop"):
        return _deny(me, "OTHER_SHOP", f"这张返修单是「{m['shop']}」的", m["id"])
    to = repair.下一档(m["status"])
    if m["status"] == "待确认":
        return dict(ok=False, code="NEED_DECIDE", reason="还在等店长判责 —— 判完了才进「待入库」")
    if not to or to == "已完成":
        return dict(ok=False, code="BAD_STATE", reason=f"这张返修单现在是「{m['status']}」—— 修好回店后要顾客试穿、输码核验才算完成")
    return _推(m, to, me, "REPAIR_STEP", f"{me['name']} 推进返修单 {m['id']}:{m['status']} → {to}")


# ── 修好回店的签收(和交付签收同一套 6 位码)────────────────────────────
def customer_issue_code(maintain_id, phone_tail):
    """顾客试穿返修件合身,点「试穿合身」领码(演示用:返修单号 + 手机后四位)。"""
    import pickup, repair
    m = rows("SELECT m.*, k.phone_tail FROM maintain m JOIN customer k ON k.id=m.customer_id WHERE m.id=?", maintain_id)
    if not m or str(m[0]["phone_tail"] or "") != str(phone_tail or "").strip():
        return dict(ok=False, code="NOT_YOURS", reason="返修单号和手机后四位对不上")
    if m[0]["status"] != "待签收":
        return dict(ok=False, code="NOT_READY", reason=f"这张返修单现在是「{m[0]['status']}」,还没修好回店")
    码, 行 = pickup.出码(repair.码前缀 + maintain_id, _now())
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO fit_code(order_id,code_hash,issued_at,expires_at,used_at,tries) VALUES(?,?,?,?,?,?)",
                  (行["order_id"], 行["code_hash"], 行["issued_at"], 行["expires_at"], None, 0))
    return dict(ok=True, code="FIT_CODE_ISSUED", 返修单=maintain_id, 试穿合身码=码, 有效到=行["expires_at"],
                reason=f"把这 6 位码告诉导购,{pickup.码有效小时} 小时内有效,只能用一次")


def verify_return(d, me):
    """修好回店,导购输入顾客给的码 → 已完成。"""
    import pickup, repair
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 导购角色:
        return _deny(me, "ROLE", f"返修件签收须由顾问或店长操作,你是「{me.get('role')}」")
    m = rows("SELECT * FROM maintain WHERE id=?", (d.get("maintain_id") or "").strip())
    if not m: return dict(ok=False, code="NO_REPAIR", reason=f"没有返修单 {d.get('maintain_id')}")
    m = m[0]
    if m["shop"] != me.get("shop"):
        return _deny(me, "OTHER_SHOP", f"这张返修单是「{m['shop']}」的", m["id"])
    key = repair.码前缀 + m["id"]
    码 = rows("SELECT rowid rid, * FROM fit_code WHERE order_id=? ORDER BY rowid DESC LIMIT 1", key)
    now = _now()
    结, 话, 改 = pickup.核验(码[0] if 码 else None, key, d.get("code"), now)
    if 改.get("tries") is not None:
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE fit_code SET tries=? WHERE rowid=?", (改["tries"], 码[0]["rid"]))
    if 结 != "通过":
        return dict(ok=False, code="FIT_CODE", reason=话)
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE fit_code SET used_at=? WHERE rowid=?", (改["used_at"], 码[0]["rid"]))
        c.execute("UPDATE maintain_decision SET return_fit_at=?, return_verified_by=? WHERE maintain_id=?",
                  (now, me["no"], m["id"]))
    r = _推(m, "已完成", me, "REPAIR_DONE", f"{me['name']} 核验返修件试穿合身码,返修单 {m['id']} 完成")
    if not r.get("ok"):
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE maintain_decision SET return_fit_at=NULL, return_verified_by=NULL WHERE maintain_id=?",
                      (m["id"],))
    return r
