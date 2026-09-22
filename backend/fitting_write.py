# -*- coding: utf-8 -*-
"""白坯试衣的两个写口:**登记试衣 / 开裁** —— 开裁那道闸从这里开始真的会拦。

业务 2026-09-22 拍板三条:
  ① 必试范围:重工、全定制、婚服三类,命中任一即必试(口径在 `knowledge/muslin.py`)
  ② 客户签字就行,不要录音
  ③ **试了没签字不许开裁**

原来这道闸**没有东西可拦**:系统里没有任何写口会把订单推进裁剪,
订单状态是种子数据直接写的 —— `muslin.能不能开裁()` 只是一个能跑的判断函数,
看板上报出来的「该试没试却已开裁」没有任何东西挡得住。
**「有一道闸」和「有一个会拦的闸」是两件事**,这个文件补的是后一半。

这一份被两个入口共用(页面 / 智能体工具),和 `tasks.py` 同一个理由:
抄两份的后果是其中一处的权限先被改松,而松掉的那份不会报错。

## 谁能做什么

  登记试衣  顾问 / 店长,**只能登记本店订单**。陪同人就是登录的人,不收工号参数 ——
            收了参数就能替别人登记一次自己没陪的试衣。
  开裁      版师(版型定了才裁)。**整单过闸**:单里每一件该试的都试过而且签了字,
            才许从「待生产」进「生产中」。一家人各做一件时,只要有一件没过,整单不许裁 ——
            裁剪是按单排的,裁一半留一半等于把没过闸那件也推上了裁床。
"""
import os, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
from oplog import log_op

登记角色 = ("顾问", "店长")
开裁角色 = ("版师",)


def rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def _deny(me, code, reason, key="—"):
    """拒绝也记台账 —— 出事之后要查的是「谁反复试着做不该做的事」。"""
    log_op((me or {}).get("name") or "未登录", "fitting", key, "—", "—", False, code,
           reason[:120], {"role": (me or {}).get("role")})
    return dict(ok=False, code=code, reason=reason)


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _找行(order_id, item):
    """订单行:item 给行号或商品名。**同名多件认不出就报错,不挑一件。**"""
    its = rows("SELECT i.id,i.name,i.wearer_id,o.id oid,o.status,o.shop,o.kind "
               "FROM ordr_item i JOIN ordr o ON o.id=i.order_id WHERE o.id=?",
               (order_id or "").strip())
    if not its:
        return None, f"没有订单 {order_id}"
    s = str(item or "").strip()
    hit = [r for r in its if str(r["id"]) == s] or [r for r in its if r["name"] == s] \
        or [r for r in its if s and s in (r["name"] or "")]
    if len(hit) != 1:
        return None, ((f"这张单里没有「{s}」" if not hit else f"这张单里有 {len(hit)} 件对得上「{s}」,请给订单行号")
                      + ";这张单的商品:" + ";".join(f"{r['id']} {r['name']}" for r in its))
    return hit[0], None


def record(d, me):
    """登记一轮白坯试衣。`round` 不给就是新的一轮;给已有的轮次且 signed=True 是**补签**。

    ⚠️ **只许从「没签」补成「签了」,不许撤销签字。** 签字是责任转移点 ——
    能撤的签字等于没签,而撤销在库里看起来只是一次普通的更新。
    """
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 登记角色:
        return _deny(me, "ROLE", f"登记白坯试衣须由顾问或店长操作,你是「{me.get('role')}」")
    it, why = _找行(d.get("order_id"), d.get("item"))
    if not it: return dict(ok=False, code="NO_ITEM", reason=why)
    if it["kind"] != "定制品订单":
        return dict(ok=False, code="NOT_CUSTOM", reason="标品不做白坯试衣 —— 白坯是给定制款试版型的")
    if it["shop"] != me.get("shop"):
        return _deny(me, "OTHER_SHOP", f"这张单是「{it['shop']}」的,只能登记本店订单", it["oid"])
    signed = bool(d.get("signed"))
    adjust = (d.get("adjust") or "").strip()
    note = (d.get("note") or "").strip()
    now = _now()
    recs = rows("SELECT * FROM fitting WHERE item_id=? ORDER BY round", it["id"])
    rnd = d.get("round")
    if rnd not in (None, ""):
        try: rnd = int(rnd)
        except (TypeError, ValueError): return dict(ok=False, code="BAD_ROUND", reason=f"轮次「{rnd}」不是数字")
        old = [r for r in recs if r["round"] == rnd]
        if not old:
            return dict(ok=False, code="NO_ROUND", reason=f"这件还没有第 {rnd} 轮试衣记录;新登记一轮不要给轮次")
        old = old[0]
        if not signed:
            return dict(ok=False, code="NO_UNSIGN",
                        reason="**签字不能撤销** —— 签字是责任转移点,能撤的签字等于没签。"
                               "给已有轮次只能用来补签(signed=true)")
        if old["signed"]:
            return dict(ok=False, code="ALREADY", reason=f"第 {rnd} 轮已经签过字了({old['signed_at']})")
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE fitting SET signed=1, signed_at=?, note=COALESCE(note,'')||? WHERE id=?",
                      (now, (";补签:" + note) if note else ";补签", old["id"]))
        log_op(me["name"], "fitting", str(old["id"]), "未签", "已签", True, "FIT_SIGN",
               f"{me['name']} 登记订单 {it['oid']} 第 {it['id']} 行「{it['name']}」第 {rnd} 轮试衣客户补签",
               {"role": me["role"]})
        return dict(ok=True, code="FIT_SIGN", 订单=it["oid"], 订单行=it["id"], 第几轮=rnd, 签了吗=True,
                    reason=f"已登记:第 {rnd} 轮试衣客户补签")
    if not adjust:
        return dict(ok=False, code="NEED_ADJUST",
                    reason="要写这一轮改了哪几处(没改就写「无需调整」)—— "
                           "只写「试了」的记录,出尺寸争议时说不清客户认可的是哪一版")
    rnd = (max((r["round"] for r in recs), default=0) or 0) + 1
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO fitting(item_id,order_id,wearer_id,round,ts,advisor_no,shop,adjust,"
                  "signed,signed_at,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (it["id"], it["oid"], it["wearer_id"], rnd, now, me["no"], it["shop"], adjust,
                   1 if signed else 0, now if signed else None, note or None))
    log_op(me["name"], "fitting", f"{it['oid']}#{it['id']}", "—", "已签" if signed else "未签", True, "FIT_ADD",
           f"{me['name']} 登记订单 {it['oid']} 第 {it['id']} 行「{it['name']}」第 {rnd} 轮试衣:"
           f"{adjust[:30]};{'客户已签字' if signed else '客户未签字'}", {"role": me["role"]})
    return dict(ok=True, code="FIT_ADD", 订单=it["oid"], 订单行=it["id"], 商品=it["name"], 第几轮=rnd,
                签了吗=signed, 陪同工号=me["no"],
                reason=f"已登记第 {rnd} 轮试衣" + ("(客户已签字)" if signed else
                        "。⚠️ **客户还没签字 —— 这一件签字之前,整张单不许开裁**(业务 09-22 定)"))


def 过闸(order_id):
    """这张单能不能开裁。返回 (结论, 理由, 逐件明细)。**不写库**,开裁和看板共用这一个判断。"""
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
    import muslin, api
    o = rows("SELECT id,status,kind FROM ordr WHERE id=?", (order_id or "").strip())
    if not o: return "判不了", f"没有订单 {order_id}", []
    o = o[0]
    明细, 拦 = [], []
    for it in rows("SELECT id,name FROM ordr_item WHERE order_id=? ORDER BY id", o["id"]):
        f = api._白坯试衣(o["id"], it["name"], o["status"], item_id=it["id"], 假设未开裁=True)
        结论, 话 = muslin.能不能开裁(f.get("该不该做白坯试衣"), bool(f.get("有几条试衣记录")),
                                   bool(f.get("客户签字了吗")))
        明细.append({"订单行": it["id"], "商品": it["name"], "能不能开裁": 结论, "为什么": 话,
                     "属于哪几类": f.get("属于哪几类"), "凭什么": f.get("凭什么")})
        if 结论 != "可以": 拦.append(明细[-1])
    if not 明细: return "判不了", "这张单没有订单行", []
    if not 拦: return "可以", "单里每一件都过了白坯试衣这道闸", 明细
    最重 = "判不了" if all(x["能不能开裁"] == "判不了" for x in 拦) else "不可以"
    return 最重, (f"有 {len(拦)} 件没过白坯试衣这道闸:"
                  + ";".join(f"「{x['商品']}」{x['为什么'][:40]}" for x in 拦)
                  + " —— **整单不许开裁**(裁剪按单排,裁一半等于把没过闸那件也推上裁床)"), 明细


def start_cutting(d, me):
    """把一张定制单从「待生产」推进到「生产中」(开裁)。**过不了白坯试衣那道闸就拒绝。**"""
    import fsm
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in 开裁角色:
        return _deny(me, "ROLE", f"开裁须由版师操作(版型定了才能裁),你是「{me.get('role')}」")
    oid = (d.get("order_id") or "").strip()
    o = rows("SELECT id,status,kind FROM ordr WHERE id=?", oid)
    if not o: return dict(ok=False, code="NO_ORDER", reason=f"没有订单 {oid}")
    o = o[0]
    if o["kind"] != "定制品订单":
        return dict(ok=False, code="NOT_CUSTOM", reason="标品不经过裁剪这一步")
    结论, 话, 明细 = 过闸(oid)
    ok, code, why = fsm.check("bk-order", o["status"], "生产中",
                              {"kind": o["kind"], "白坯过闸": 结论, "白坯过闸_为什么": 话})
    if not ok and code != "MUSLIN_GATE":
        return dict(ok=False, code="BAD_STATE", reason=f"这张单现在是「{o['status']}」,不能开裁:{why}")
    if not ok:
        _deny(me, "MUSLIN_GATE", 话, oid)
        return dict(ok=False, code="MUSLIN_GATE", reason=话, 逐件=明细,
                    能做什么="约客户来试白坯并签字(顾问登记试衣),或补齐判不了的那一项(比如亲自量体)")
    now = _now()
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE ordr SET status='生产中', prd_status=?, cut_at=?, cut_by=? WHERE id=? AND status=?",
                  (fsm.ORDER_PRD["生产中"], now, me["no"], oid, o["status"]))
    log_op(me["name"], "ordr", oid, o["status"], "生产中", True, "CUT",
           f"{me['name']} 开裁订单 {oid}:{话}", {"role": me["role"]})
    return dict(ok=True, code="CUT", 订单=oid, 从=o["status"], 到="生产中", 开裁时间=now, 逐件=明细,
                reason=f"已开裁:{话}")
