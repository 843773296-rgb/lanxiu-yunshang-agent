# -*- coding: utf-8 -*-
"""定制品交付签收的写口 —— 到店代收、取件方式、试穿合身核验、不合身、完成、顾问追认。

口径在 `knowledge/pickup.py`(业务 2026-09-22 逐条拍板)。这一份被页面和智能体工具共用,
和 `fitting_write.py` / `tasks.py` 同一个理由:抄两份的后果是其中一处的权限先被改松。

## 谁能做什么

  导购端(顾问 / 店长,**只能动本店的单**;经手人就是登录的人,不收工号参数)
    到店代收      工厂发到店,这一单到了 —— 只认「已发货」的定制单
    取件方式      到店取 / 转寄(转寄要物流单号)
    核验签收      输入顾客给的 6 位码 → 通过就签收,订单「已发货 → 待完成」
    登记不合身    顾客试了不合身 → **不算签收**,订单不动,给一个判责建议,转返修
    顾问追认      签收满 15 天顾客还没确认完成 → 写理由追认,「待完成 → 完成」

  顾客端(演示用:凭订单号 + 手机后四位。**真正的顾客端以后另做**)
    点「试穿合身」 → 拿到 6 位码(明文只给顾客,库里只存哈希)
    确认完成      → 「待完成 → 完成」

## 为什么签收之后订单才动,不合身时订单不动

签收是**责任转移点**。「已发货 → 待完成」这一步只能由核验通过的码推动 ——
页面上、智能体里、后台改状态,**都不许绕过它**(状态机上的闸在 fsm.py,和开裁那道同一个做法)。
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
    """拒绝也记台账 —— 出事之后要查的是「谁反复试着做不该做的事」。"""
    log_op((me or {}).get("name") or "未登录", "pickup", key, "—", "—", False, code,
           reason[:120], {"role": (me or {}).get("role")})
    return dict(ok=False, code=code, reason=reason)


def _单(order_id):
    o = rows("SELECT id,status,kind,shop,customer_id FROM ordr WHERE id=?", (order_id or "").strip())
    return o[0] if o else None


def _导购的单(d, me):
    """导购端共用的前置:登录、角色、单存在、定制单、本店。返回 (单, 错误)。"""
    if not me: return None, dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 导购角色:
        return None, _deny(me, "ROLE", f"交付签收须由顾问或店长操作,你是「{me.get('role')}」")
    o = _单(d.get("order_id"))
    if not o: return None, dict(ok=False, code="NO_ORDER", reason=f"没有订单 {d.get('order_id')}")
    if o["kind"] != "定制品订单":
        return None, dict(ok=False, code="NOT_CUSTOM", reason="标品不走试穿合身这一步 —— 这里只管定制品")
    if o["shop"] != me.get("shop"):
        return None, _deny(me, "OTHER_SHOP", f"这一单是「{o['shop']}」的,只能动本店的单", o["id"])
    return o, None


def _到了(oid):
    p = rows("SELECT * FROM pickup WHERE order_id=?", oid)
    return p[0] if p else None


def _转(o, to, me_name, code, why, **ctx):
    """走订单状态机。**闸在状态机上**,这里不自己判能不能流转。"""
    import fsm
    ok, c, reason = fsm.check("bk-order", o["status"], to, {"kind": o["kind"], **ctx})
    if not ok:
        return False, c, reason
    with sqlite3.connect(DB) as cx:
        n = cx.execute("UPDATE ordr SET status=?, prd_status=? WHERE id=? AND status=?",
                       (to, fsm.ORDER_PRD[to], o["id"], o["status"])).rowcount
    if n != 1:
        return False, "RACE", f"这一单的状态刚被别人改了(不再是「{o['status']}」),请刷新再看"
    log_op(me_name, "ordr", o["id"], o["status"], to, True, code, why, {})
    return True, code, why


def _完成(o, 谁, actor, code, why, note=None):
    """「待完成 → 完成」。**先记下是谁确认的,再走状态机** —— 状态机上的闸看的就是这一栏
    (后台改状态那条路也读它),所以先写、流转不成再撤回。"""
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE pickup SET complete_at=?, complete_by=?, ratify_note=? WHERE order_id=?",
                  (_now(), 谁, note, o["id"]))
    ok, c2, reason = _转(o, "完成", actor, code, why, 完成确认=谁)
    if not ok:
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE pickup SET complete_at=NULL, complete_by=NULL, ratify_note=NULL WHERE order_id=?",
                      (o["id"],))
    return ok, c2, reason


# ── 导购端 ────────────────────────────────────────────────────────────
def arrive(d, me):
    """工厂发到店,顾问代收。"""
    o, err = _导购的单(d, me)
    if err: return err
    if o["status"] != "已发货":
        return dict(ok=False, code="BAD_STATE", reason=f"这一单现在是「{o['status']}」—— 只有工厂已发货的单才谈得上到店代收")
    if _到了(o["id"]):
        return dict(ok=False, code="ALREADY", reason="这一单已经登记过到店代收了")
    now = _now()
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO pickup(order_id,arrived_at,received_by) VALUES(?,?,?)", (o["id"], now, me["no"]))
    log_op(me["name"], "pickup", o["id"], "—", "到店", True, "ARRIVE", f"{me['name']} 代收订单 {o['id']}", {"role": me["role"]})
    return dict(ok=True, code="ARRIVE", 订单=o["id"], 到店时间=now, 代收人=me["no"],
                reason="已登记到店代收。下一步:约顾客到店取;实在来不了再转寄")


def set_mode(d, me):
    """取件方式:到店取 / 转寄(转寄要物流单号)。"""
    import pickup
    o, err = _导购的单(d, me)
    if err: return err
    p = _到了(o["id"])
    if not p:
        return dict(ok=False, code="NOT_ARRIVED", reason="还没登记到店代收 —— 货到了店才谈得上怎么取")
    if p.get("fit_result") == "合身":
        return dict(ok=False, code="SIGNED", reason="这一单已经签收了,取件方式不再改")
    mode = (d.get("mode") or "").strip()
    if mode not in pickup.取件方式:
        return dict(ok=False, code="BAD_MODE", reason=f"取件方式只认 {' / '.join(pickup.取件方式)}")
    tn = (d.get("tracking_no") or "").strip()
    if mode == "转寄" and not tn:
        return dict(ok=False, code="NO_TRACKING", reason="转寄要写物流单号 —— 没有单号,寄丢了查不到")
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE pickup SET mode=?, forwarded_at=?, tracking_no=? WHERE order_id=?",
                  (mode, _now() if mode == "转寄" else None, tn or None, o["id"]))
    log_op(me["name"], "pickup", o["id"], p.get("mode") or "—", mode, True, "MODE",
           f"{me['name']} 定订单 {o['id']} 取件方式:{mode}" + (f"(单号 {tn})" if tn else ""), {"role": me["role"]})
    return dict(ok=True, code="MODE", 订单=o["id"], 取件方式=mode, 物流单号=tn or None,
                reason=("已定为到店取。顾客试穿合身后,请他在手机上点「试穿合身」,把 6 位码告诉你" if mode == "到店取"
                        else "已定为转寄。顾客收到试穿合身后,在手机上点「试穿合身」,把 6 位码发给你再核验"))


def verify(d, me):
    """输入顾客给的 6 位码。通过 → 签收,订单「已发货 → 待完成」。"""
    import pickup
    o, err = _导购的单(d, me)
    if err: return err
    p = _到了(o["id"])
    if not p:
        return dict(ok=False, code="NOT_ARRIVED", reason="还没登记到店代收")
    码 = rows("SELECT rowid rid, * FROM fit_code WHERE order_id=? ORDER BY rowid DESC LIMIT 1", o["id"])
    now = _now()
    结, 话, 改 = pickup.核验(码[0] if 码 else None, o["id"], d.get("code"), now)
    if 改.get("tries") is not None:
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE fit_code SET tries=? WHERE rowid=?", (改["tries"], 码[0]["rid"]))
    if 结 != "通过":
        return _deny(me, "FIT_CODE", 话, o["id"]) if 结 in ("不对", "作废") else \
            dict(ok=False, code="FIT_CODE", reason=话)
    ok, code, why = _转(o, "待完成", me["name"], "SIGN",
                        f"{me['name']} 核验试穿合身码,订单 {o['id']} 签收", 试穿合身="已核验")
    if not ok:
        return dict(ok=False, code=code, reason=why)
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE fit_code SET used_at=? WHERE rowid=?", (改["used_at"], 码[0]["rid"]))
        c.execute("UPDATE pickup SET fit_result='合身', fit_at=?, fit_verified_by=? WHERE order_id=?",
                  (now, me["no"], o["id"]))
    return dict(ok=True, code="SIGN", 订单=o["id"], 从="已发货", 到="待完成", 签收时间=now,
                reason="核验通过,已签收。订单进「待完成」—— **完成要顾客自己确认**,"
                       f"满 {pickup.追认等几天} 天没确认,顾问可以写理由追认")


def not_fit(d, me):
    """顾客试了不合身 → **不算签收**,订单不动;给判责建议,转返修。"""
    import pickup
    o, err = _导购的单(d, me)
    if err: return err
    p = _到了(o["id"])
    if not p:
        return dict(ok=False, code="NOT_ARRIVED", reason="还没登记到店代收")
    if p.get("fit_result") == "合身":
        return dict(ok=False, code="SIGNED", reason="这一单已经签收(试穿合身核验过)—— 签收后的问题走售后报修")
    说明 = (d.get("issue") or "").strip()
    if not 说明:
        return dict(ok=False, code="NO_ISSUE", reason="写清哪里不合身(比如「腰围紧 2cm」)—— 返修和判责都要看这一句")
    谁, 怎么办, 话 = pickup.不合身判责(d.get("matches_record"), d.get("other_defect"), d.get("our_fault"))
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE pickup SET fit_result='不合身' WHERE order_id=?", (o["id"],))
    log_op(me["name"], "pickup", o["id"], "—", "不合身", True, "NOT_FIT",
           f"{me['name']} 登记订单 {o['id']} 试穿不合身:{说明[:60]};判责建议 {谁}", {"role": me["role"]})
    # 业务 09-22:不合身直接转返修 —— 自动建一张返修单(来源「签收不合身」),等店长判责
    import repair_write as _rw
    _单件 = rows("SELECT id FROM ordr_item WHERE order_id=? ORDER BY id", o["id"])
    返修 = _rw.create(dict(order_id=o["id"], item=d.get("item") or (str(_单件[0]["id"]) if len(_单件) == 1 else None),
                          issue=说明, 不合身事实=dict(matches_record=d.get("matches_record"),
                                                  other_defect=d.get("other_defect"), our_fault=d.get("our_fault"))),
                     me, 来源="签收不合身")
    return dict(ok=True, code="NOT_FIT", 订单=o["id"], 不合身=说明, 判责建议=谁, 处理建议=怎么办,
                返修单=返修.get("返修单"), 返修单没建成=(None if 返修.get("ok") else 返修.get("reason")),
                reason=f"已登记试穿不合身,**不算签收**,订单状态不动。判责建议:{话}。**建议不是结论,由售后负责人确认。**"
                       "下一步转返修(报修新建)")


def ratify(d, me):
    """签收满 15 天顾客还没确认完成,顾问写理由追认。"""
    import pickup
    o, err = _导购的单(d, me)
    if err: return err
    if o["status"] != "待完成":
        return dict(ok=False, code="BAD_STATE", reason=f"这一单现在是「{o['status']}」—— 只有签收后「待完成」的单才谈得上追认完成")
    p = _到了(o["id"]) or {}
    能, 话 = pickup.能不能追认(p.get("fit_at"), _now(), d.get("reason"))
    if not 能:
        return dict(ok=False, code="NO_RATIFY", reason=话)
    ok, code, why = _完成(o, "顾问追认", me["name"], "RATIFY",
                          f"{me['name']} 追认订单 {o['id']} 完成:{d.get('reason')[:60]}", d.get("reason").strip())
    if not ok:
        return dict(ok=False, code=code, reason=why)
    return dict(ok=True, code="RATIFY", 订单=o["id"], 到="完成", reason=f"{话};理由已记下")


# ── 顾客端(演示用)────────────────────────────────────────────────────
def _顾客的单(order_id, phone_tail):
    o = _单(order_id)
    if not o: return None, dict(ok=False, code="NO_ORDER", reason="没有这一单")
    k = rows("SELECT phone_tail FROM customer WHERE id=?", o["customer_id"])
    if not k or str(k[0]["phone_tail"] or "") != str(phone_tail or "").strip():
        return None, dict(ok=False, code="NOT_YOURS", reason="订单号和手机后四位对不上")
    return o, None


def customer_issue_code(order_id, phone_tail):
    """顾客点「试穿合身」→ 拿到 6 位码。**明文只在这里出现一次**,库里只存哈希。"""
    import pickup
    o, err = _顾客的单(order_id, phone_tail)
    if err: return err
    if o["kind"] != "定制品订单" or o["status"] != "已发货" or not _到了(o["id"]):
        return dict(ok=False, code="NOT_READY", reason="这一单还没到可以签收的时候(要定制单、已发货、到店代收过)")
    码, 行 = pickup.出码(o["id"], _now())
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO fit_code(order_id,code_hash,issued_at,expires_at,used_at,tries) VALUES(?,?,?,?,?,?)",
                  (行["order_id"], 行["code_hash"], 行["issued_at"], 行["expires_at"], None, 0))
    log_op("顾客", "fit_code", o["id"], "—", "出码", True, "FIT_CODE_ISSUED", "顾客点了试穿合身(码不入台账)", {})
    return dict(ok=True, code="FIT_CODE_ISSUED", 订单=o["id"], 试穿合身码=码, 有效到=行["expires_at"],
                reason=f"把这 6 位码告诉导购,{pickup.码有效小时} 小时内有效,只能用一次")


def customer_complete(order_id, phone_tail):
    """顾客确认完成:「待完成 → 完成」。"""
    o, err = _顾客的单(order_id, phone_tail)
    if err: return err
    if o["status"] != "待完成":
        return dict(ok=False, code="BAD_STATE", reason=f"这一单现在是「{o['status']}」—— 签收之后才能确认完成")
    ok, code, why = _完成(o, "顾客", "顾客", "COMPLETE", f"顾客确认订单 {o['id']} 完成")
    if not ok:
        return dict(ok=False, code=code, reason=why)
    return dict(ok=True, code="COMPLETE", 订单=o["id"], 到="完成", reason="已确认完成,谢谢")
