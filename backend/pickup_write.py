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


def _记事(oid, 动作, 时间, pkg_id=None, item_id=None, me=None, 一句话=""):
    """写进订单日志(工厂侧 factory_inbox.记事件,对方 0dff04b 提供)。

    **时间一定要给**(演示世界的日子),不给就落机器时间。状态变化和工厂回传各有自己的表,
    这里只记签收侧自己的事,不抄第二份。
    """
    try:
        import factory_inbox as _fi
        # db=DB:检查在库副本上跑时,日志也要落到同一个副本(pickup_write_check 只改得到本模块的 DB)
        _fi.记事件(oid, 动作, 时间=时间, 包裹=pkg_id, 订单行=item_id,
                  经手人=(me or {}).get("no"), 一句话=一句话, db=DB)
    except Exception:
        pass          # 日志记不上不该挡住业务动作 —— 它是旁路


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


# ── 分批发货(业务 2026-09-23):包裹 / 件 ────────────────────────────────
def _包们(oid):
    """这一单**没作废**的包裹。作废的(工厂撤回、店长回退)不算数,闸也不看它。"""
    return rows("""SELECT k.*, (SELECT COUNT(*) FROM pkg_item i WHERE i.pkg_id=k.pkg_id) 件数
                   FROM pkg k WHERE k.order_id=? AND k.void_at IS NULL ORDER BY k.shipped_at, k.pkg_id""", oid)


def _挑包裹(d, o):
    """用户可以不说包裹号 —— 一单只有一个包裹时不该逼他说。返回 (包裹, 错误)。"""
    包 = _包们(o["id"])
    if not 包:
        return None, dict(ok=False, code="NO_PKG", reason="这一单还没有任何包裹(工厂还没发出),谈不上到店和签收")
    pid = (d.get("pkg") or d.get("pkg_id") or "").strip()
    if pid:
        hit = [k for k in 包 if k["pkg_id"] == pid]
        if not hit:
            return None, dict(ok=False, code="NO_SUCH_PKG",
                              reason=f"这一单没有包裹 {pid}(有的是:{'、'.join(k['pkg_id'] for k in 包)})")
        return hit[0], None
    if len(包) > 1:
        # **分批发的单不许替用户挑一个** —— 挑错了就是让顾客替还没到的衣服确认合身
        详 = "、".join(f"{k['pkg_id']}({k['status']},{k['件数']} 件)" for k in 包)
        return None, dict(ok=False, code="WHICH_PKG", reason=f"这一单分了 {len(包)} 个包裹,说清是哪一个:{详}")
    return 包[0], None


def _件们(oid):
    """这一单**未作废包裹**里的所有件,带上各自的签收结果。"""
    return rows("""SELECT i.item_id, i.pkg_id, t.fit_result, t.fit_at, t.issue, t.maintain_id,
                          m.spu, m.name 商品名
                   FROM pkg k JOIN pkg_item i ON i.pkg_id=k.pkg_id
                   LEFT JOIN pickup_item t ON t.order_item_id=i.item_id
                   LEFT JOIN ordr_item m ON m.id=i.item_id
                   WHERE k.order_id=? AND k.void_at IS NULL ORDER BY i.item_id""", oid)


def _包里的件(pkg_id):
    return rows("""SELECT i.item_id, t.fit_result, m.name 商品名 FROM pkg_item i
                   LEFT JOIN pickup_item t ON t.order_item_id=i.item_id
                   LEFT JOIN ordr_item m ON m.id=i.item_id
                   WHERE i.pkg_id=? ORDER BY i.item_id""", pkg_id)


def _确保有单行(oid):
    """完成确认仍然是**整单一次**,记在 pickup 那一行上 —— 先保证它在。"""
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR IGNORE INTO pickup(order_id) VALUES(?)", (oid,))


def _推整单(o, me_name):
    """所有未作废包裹的件都签收合身了 → 订单「已发货 → 待完成」(业务 2026-09-23)。
    差一件都不推 —— 差的那件要么还没试,要么在返修。"""
    import pickup
    if o["status"] != "已发货":
        return False, None
    齐, 话 = pickup.整单签收完了吗([dict(item_id=x["item_id"], pkg_id=x["pkg_id"], fit_result=x["fit_result"])
                                  for x in _件们(o["id"])])
    if not 齐:
        return False, 话
    ok, _c, why = _转(o, "待完成", me_name, "SIGN", f"{me_name} 核验试穿合身码,订单 {o['id']} 全部签收", 试穿合身="已核验")
    return ok, (why if ok else why)


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
    if ok:
        _记事(o["id"], "顾客确认完成" if 谁 == "顾客" else "顾问追认完成", _now(), me=None, 一句话=why)
    if not ok:
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE pickup SET complete_at=NULL, complete_by=NULL, ratify_note=NULL WHERE order_id=?",
                      (o["id"],))
    return ok, c2, reason


# ── 导购端 ────────────────────────────────────────────────────────────
def arrive(d, me):
    """工厂发到店,顾问代收。**按包裹登记**(业务 2026-09-23:分批发货,各包裹各自到店)。"""
    o, err = _导购的单(d, me)
    if err: return err
    if o["status"] != "已发货":
        return dict(ok=False, code="BAD_STATE", reason=f"这一单现在是「{o['status']}」—— 只有工厂已发货的单才谈得上到店代收")
    k, err = _挑包裹(d, o)
    if err: return err
    if rows("SELECT 1 FROM pkg_pickup WHERE pkg_id=?", k["pkg_id"]):
        return dict(ok=False, code="ALREADY", reason=f"包裹 {k['pkg_id']} 已经登记过到店代收了")
    now = _now()
    _确保有单行(o["id"])
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO pkg_pickup(pkg_id,order_id,arrived_at,received_by) VALUES(?,?,?,?)",
                  (k["pkg_id"], o["id"], now, me["no"]))
        c.execute("UPDATE pkg SET arrived_at=?, status='到店' WHERE pkg_id=?", (now, k["pkg_id"]))
        # 老单是一单一个包裹,订单级那一行也跟着记 —— 页面和判责还在读它
        c.execute("UPDATE pickup SET arrived_at=COALESCE(arrived_at,?), received_by=COALESCE(received_by,?) "
                  "WHERE order_id=?", (now, me["no"], o["id"]))
    _记事(o["id"], "包裹到店代收", now, k["pkg_id"], None, me, f"{me['name']} 代收包裹 {k['pkg_id']}({k['件数']} 件)")
    log_op(me["name"], "pickup", k["pkg_id"], "—", "到店", True, "ARRIVE",
           f"{me['name']} 代收订单 {o['id']} 的包裹 {k['pkg_id']}", {"role": me["role"]})
    剩 = [x for x in _包们(o["id"]) if x["pkg_id"] != k["pkg_id"] and x["status"] == "在途"]
    return dict(ok=True, code="ARRIVE", 订单=o["id"], 包裹=k["pkg_id"], 这个包裹几件=k["件数"],
                到店时间=now, 代收人=me["no"], 还在路上的包裹=[x["pkg_id"] for x in 剩] or None,
                reason="已登记到店代收。下一步:约顾客到店取;实在来不了再转寄"
                       + (f"。⚠️ 这一单还有 {len(剩)} 个包裹在路上,**整单要每一件都签收合身才算完**" if 剩 else ""))


def set_mode(d, me):
    """取件方式:到店取 / 转寄(转寄要物流单号)。**一个包裹一种**。"""
    import pickup
    o, err = _导购的单(d, me)
    if err: return err
    k, err = _挑包裹(d, o)
    if err: return err
    p = rows("SELECT * FROM pkg_pickup WHERE pkg_id=?", k["pkg_id"])
    if not p:
        return dict(ok=False, code="NOT_ARRIVED", reason=f"包裹 {k['pkg_id']} 还没登记到店代收 —— 货到了店才谈得上怎么取")
    if all(x["fit_result"] == "合身" for x in _包里的件(k["pkg_id"])):
        return dict(ok=False, code="SIGNED", reason=f"包裹 {k['pkg_id']} 已经全部签收了,取件方式不再改")
    mode = (d.get("mode") or "").strip()
    if mode not in pickup.取件方式:
        return dict(ok=False, code="BAD_MODE", reason=f"取件方式只认 {' / '.join(pickup.取件方式)}")
    tn = (d.get("tracking_no") or "").strip()
    if mode == "转寄" and not tn:
        return dict(ok=False, code="NO_TRACKING", reason="转寄要写物流单号 —— 没有单号,寄丢了查不到")
    now = _now()
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE pkg_pickup SET mode=?, forwarded_at=?, tracking_no=? WHERE pkg_id=?",
                  (mode, now if mode == "转寄" else None, tn or None, k["pkg_id"]))
        c.execute("UPDATE pickup SET mode=?, forwarded_at=?, tracking_no=? WHERE order_id=?",
                  (mode, now if mode == "转寄" else None, tn or None, o["id"]))
    _记事(o["id"], "包裹取件方式", now, k["pkg_id"], None, me,
          f"{me['name']} 定包裹 {k['pkg_id']} 取件方式:{mode}" + (f"(单号 {tn})" if tn else ""))
    log_op(me["name"], "pickup", k["pkg_id"], (p[0].get("mode") or "—"), mode, True, "MODE",
           f"{me['name']} 定包裹 {k['pkg_id']} 取件方式:{mode}" + (f"(单号 {tn})" if tn else ""), {"role": me["role"]})
    return dict(ok=True, code="MODE", 订单=o["id"], 包裹=k["pkg_id"], 取件方式=mode, 物流单号=tn or None,
                reason=("已定为到店取。顾客试穿合身后,请他在手机上点「试穿合身」,把这个包裹的 6 位码告诉你" if mode == "到店取"
                        else "已定为转寄。顾客收到试穿合身后,在手机上点「试穿合身」,把这个包裹的 6 位码发给你再核验"))


def verify(d, me):
    """输入顾客给的 6 位码 —— **一个包裹一个码**。通过 → 这个包裹里**还没登记不合身**的件全部签收;
    整单所有未作废包裹的件都签收合身了,订单才「已发货 → 待完成」。"""
    import pickup
    o, err = _导购的单(d, me)
    if err: return err
    k, err = _挑包裹(d, o)
    if err: return err
    if not rows("SELECT 1 FROM pkg_pickup WHERE pkg_id=?", k["pkg_id"]):
        return dict(ok=False, code="NOT_ARRIVED", reason=f"包裹 {k['pkg_id']} 还没登记到店代收")
    键 = pickup.码键(k["pkg_id"])
    码 = rows("SELECT rowid rid, * FROM fit_code WHERE order_id=? ORDER BY rowid DESC LIMIT 1", 键)
    now = _now()
    结, 话, 改 = pickup.核验(码[0] if 码 else None, 键, d.get("code"), now)
    if 改.get("tries") is not None:
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE fit_code SET tries=? WHERE rowid=?", (改["tries"], 码[0]["rid"]))
    if 结 != "通过":
        return _deny(me, "FIT_CODE", 话, k["pkg_id"]) if 结 in ("不对", "作废") else \
            dict(ok=False, code="FIT_CODE", reason=话)
    待签 = [x for x in _包里的件(k["pkg_id"]) if x["fit_result"] != "不合身"]
    if not 待签:
        return dict(ok=False, code="ALL_NOT_FIT",
                    reason=f"包裹 {k['pkg_id']} 里的件都登记成不合身了,没有可签收的件 —— 它们在返修")
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE fit_code SET used_at=? WHERE rowid=?", (改["used_at"], 码[0]["rid"]))
        for x in 待签:
            c.execute("""INSERT INTO pickup_item(order_item_id,order_id,pkg_id,fit_result,fit_at,fit_verified_by)
                         VALUES(?,?,?,'合身',?,?)
                         ON CONFLICT(order_item_id) DO UPDATE SET fit_result='合身', fit_at=excluded.fit_at,
                                                                 fit_verified_by=excluded.fit_verified_by""",
                      (x["item_id"], o["id"], k["pkg_id"], now, me["no"]))
        # 订单级那一行留着给判责和老页面读:**最后一件签收的时间**就是整单的签收时间
        c.execute("UPDATE pickup SET fit_result='合身', fit_at=?, fit_verified_by=? WHERE order_id=?",
                  (now, me["no"], o["id"]))
        if all(x["fit_result"] == "合身" or x in 待签 for x in _包里的件(k["pkg_id"])):
            c.execute("UPDATE pkg SET status='已签收' WHERE pkg_id=?", (k["pkg_id"],))
    for x in 待签:
        _记事(o["id"], "某件签收合身", now, k["pkg_id"], x["item_id"], me,
              f"{me['name']} 核验码,{x['商品名'] or x['item_id']} 顾客签收")
    log_op(me["name"], "pickup", k["pkg_id"], "—", "签收", True, "SIGN",
           f"{me['name']} 核验包裹 {k['pkg_id']} 的码,{len(待签)} 件签收", {"role": me["role"]})
    推了, 话2 = _推整单(o, me["name"])
    return dict(ok=True, code="SIGN", 订单=o["id"], 包裹=k["pkg_id"], 这次签收几件=len(待签), 签收时间=now,
                订单到="待完成" if 推了 else o["status"], 还差什么=None if 推了 else 话2,
                reason=(f"核验通过,这个包裹的 {len(待签)} 件已签收。整单全部签收,订单进「待完成」—— "
                        f"**完成要顾客自己确认**,满 {pickup.追认等几天} 天没确认,顾问可以写理由追认"
                        if 推了 else
                        f"核验通过,这个包裹的 {len(待签)} 件已签收,顾客可以拿走。{话2},订单状态暂时不动"))


def not_fit(d, me):
    """顾客试了某一件不合身 → **那一件不算签收**,留店转返修;同包裹里合身的件照常签收拿走
    (业务 2026-09-23)。订单状态不动。"""
    import pickup
    o, err = _导购的单(d, me)
    if err: return err
    k, err = _挑包裹(d, o)
    if err: return err
    if not rows("SELECT 1 FROM pkg_pickup WHERE pkg_id=?", k["pkg_id"]):
        return dict(ok=False, code="NOT_ARRIVED", reason=f"包裹 {k['pkg_id']} 还没登记到店代收")
    件们 = _包里的件(k["pkg_id"])
    说明 = (d.get("issue") or "").strip()
    if not 说明:
        return dict(ok=False, code="NO_ISSUE", reason="写清哪里不合身(比如「腰围紧 2cm」)—— 返修和判责都要看这一句")
    指 = str(d.get("item") or "").strip()
    if 指:
        hit = [x for x in 件们 if str(x["item_id"]) == 指]
        if not hit:
            return dict(ok=False, code="NO_SUCH_ITEM",
                        reason=f"包裹 {k['pkg_id']} 里没有这一件({指})。里面是:"
                               + "、".join(f"{x['item_id']} {x['商品名']}" for x in 件们))
        件 = hit[0]
    elif len(件们) > 1:
        # **一个包裹好几件时不许替用户挑** —— 挑错了会把好的那件送去返修
        return dict(ok=False, code="WHICH_ITEM", reason=f"包裹 {k['pkg_id']} 里有 {len(件们)} 件,说清是哪一件不合身:"
                                                        + "、".join(f"{x['item_id']} {x['商品名']}" for x in 件们))
    else:
        件 = 件们[0]
    if 件["fit_result"] == "合身":
        return dict(ok=False, code="SIGNED", reason=f"这一件({件['商品名']})已经签收了 —— 签收后的问题走售后报修")
    谁, 怎么办, 话 = pickup.不合身判责(d.get("matches_record"), d.get("other_defect"), d.get("our_fault"))
    now = _now()
    with sqlite3.connect(DB) as c:
        c.execute("""INSERT INTO pickup_item(order_item_id,order_id,pkg_id,fit_result,issue) VALUES(?,?,?,'不合身',?)
                     ON CONFLICT(order_item_id) DO UPDATE SET fit_result='不合身', issue=excluded.issue""",
                  (件["item_id"], o["id"], k["pkg_id"], 说明))
        c.execute("UPDATE pickup SET fit_result=COALESCE(NULLIF(fit_result,'合身'),'不合身') WHERE order_id=?", (o["id"],))
    log_op(me["name"], "pickup", str(件["item_id"]), "—", "不合身", True, "NOT_FIT",
           f"{me['name']} 登记订单 {o['id']} 的 {件['商品名']} 试穿不合身:{说明[:60]};判责建议 {谁}", {"role": me["role"]})
    # 业务 09-22:不合身直接转返修 —— 自动建一张返修单(来源「签收不合身」),等店长判责
    import repair_write as _rw
    返修 = _rw.create(dict(order_id=o["id"], item=str(件["item_id"]),
                          issue=说明, 不合身事实=dict(matches_record=d.get("matches_record"),
                                                  other_defect=d.get("other_defect"), our_fault=d.get("our_fault"))),
                     me, 来源="签收不合身")
    if 返修.get("返修单"):
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE pickup_item SET maintain_id=? WHERE order_item_id=?", (返修["返修单"], 件["item_id"]))
    _记事(o["id"], "某件不合身", now, k["pkg_id"], 件["item_id"], me,
          f"{件['商品名']} 试穿不合身:{说明[:40]}" + (f",转返修单 {返修.get('返修单')}" if 返修.get("返修单") else ""))
    其余 = [x for x in 件们 if x["item_id"] != 件["item_id"] and x["fit_result"] != "不合身"]
    return dict(ok=True, code="NOT_FIT", 订单=o["id"], 包裹=k["pkg_id"], 哪一件=件["商品名"], 订单行=件["item_id"],
                不合身=说明, 判责建议=谁, 处理建议=怎么办,
                返修单=返修.get("返修单"), 返修单没建成=(None if 返修.get("ok") else 返修.get("reason")),
                同包裹其余件=[x["商品名"] for x in 其余] or None,
                reason=f"已登记**这一件**试穿不合身,留店转返修,订单状态不动。判责建议:{话}。"
                       "**建议不是结论,由售后负责人确认。**"
                       + (f"同一个包裹里另外 {len(其余)} 件,顾客试穿合身的话照常核验码签收拿走" if 其余 else ""))


def ratify(d, me):
    """签收满 15 天顾客还没确认完成,顾问写理由追认。"""
    import pickup
    o, err = _导购的单(d, me)
    if err: return err
    if o["status"] != "待完成":
        return dict(ok=False, code="BAD_STATE", reason=f"这一单现在是「{o['status']}」—— 只有签收后「待完成」的单才谈得上追认完成")
    # 分批发货之后,「签收满 15 天」从**最后一件签收**那天起算(业务 2026-09-23 顺推:
    # 整单要全部签收完才进待完成,那一刻才是顾客该确认的起点)
    末 = rows("SELECT MAX(fit_at) t FROM pickup_item WHERE order_id=? AND fit_result='合身'", o["id"])
    签于 = (末[0]["t"] if 末 else None) or (_到了(o["id"]) or {}).get("fit_at")
    能, 话 = pickup.能不能追认(签于, _now(), d.get("reason"))
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


def customer_issue_code(order_id, phone_tail, pkg=None):
    """顾客点「试穿合身」→ 拿到 6 位码。**明文只在这里出现一次**,库里只存哈希。

    **一个包裹一个码**(业务 2026-09-23):顾客分两次来取,不能让他替还没到的衣服确认合身。
    """
    import pickup
    o, err = _顾客的单(order_id, phone_tail)
    if err: return err
    if o["kind"] != "定制品订单" or o["status"] != "已发货":
        return dict(ok=False, code="NOT_READY", reason="这一单还没到可以签收的时候(要定制单、已发货)")
    可签 = [k for k in _包们(o["id"])
           if rows("SELECT 1 FROM pkg_pickup WHERE pkg_id=?", k["pkg_id"])
           and any(x["fit_result"] != "合身" for x in _包里的件(k["pkg_id"]))]
    if not 可签:
        return dict(ok=False, code="NOT_READY", reason="没有到了店、还没签收的包裹 —— 货到店、导购登记代收之后才能点")
    pid = str(pkg or "").strip()
    if pid:
        hit = [k for k in 可签 if k["pkg_id"] == pid]
        if not hit:
            return dict(ok=False, code="NO_SUCH_PKG", reason=f"没有这个包裹或它已经签收完了(可签收的:"
                                                             + "、".join(k["pkg_id"] for k in 可签) + ")")
        k = hit[0]
    elif len(可签) > 1:
        return dict(ok=False, code="WHICH_PKG", reason="这一单到店的包裹不止一个,请选一个:"
                                                       + "、".join(f"{x['pkg_id']}({x['件数']} 件)" for x in 可签))
    else:
        k = 可签[0]
    键 = pickup.码键(k["pkg_id"])
    码, 行 = pickup.出码(键, _now())
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO fit_code(order_id,code_hash,issued_at,expires_at,used_at,tries) VALUES(?,?,?,?,?,?)",
                  (行["order_id"], 行["code_hash"], 行["issued_at"], 行["expires_at"], None, 0))
    log_op("顾客", "fit_code", k["pkg_id"], "—", "出码", True, "FIT_CODE_ISSUED", "顾客点了试穿合身(码不入台账)", {})
    return dict(ok=True, code="FIT_CODE_ISSUED", 订单=o["id"], 包裹=k["pkg_id"], 这个包裹几件=k["件数"],
                试穿合身码=码, 有效到=行["expires_at"],
                reason=f"把这 6 位码告诉导购,{pickup.码有效小时} 小时内有效,只能用一次;"
                       "这个码只管这个包裹里的衣服,别的包裹到了再点一次")


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
