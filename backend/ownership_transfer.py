# -*- coding: utf-8 -*-
"""跨店成交后判归属转不转、转了就派知会(用户 2026-11-11 拍)。判定口径在 knowledge/ownership_protection.py,这里只取数和落地。

在哪调:**付款那一刻**(成交 = 付款)——
  · 定制单:order_write.确认下单 成功之后(定制单确认即付款,业务 09-22)
  · 标品 / 其它:server.transition 把订单从「待付款」流转出去之后
两处都在原事务**之外**调:判转移出错不能让已付款的那一单回滚,但不静默(写操作日志、返回里带出错)。
**历史不管**(用户原话「历史的先不管,继续原本导购维护」):只有新的付款会走到这里,不扫存量。

转了:整户改导购走 account_owner.改导购(唯一一份;连同户档案、未完成预约一起迁),
再给原导购、原店店长、新店店长各派一条「归属转移」知会任务(点「知道了」就完成),写操作日志。
有异议 → 走现有「客户转移」审批转回(不在这里做)。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
import ownership_protection as OP     # noqa: E402


def _日们(c, sql, *a):
    return [r[0] for r in c.execute(sql, a).fetchall() if r[0]]


def _店长(c, 店):
    import shop_key as SK
    片, 参 = SK.门店条件(c, 店)
    r = c.execute(f"SELECT no FROM staff WHERE role='店长' AND status='启用' AND {片} ORDER BY no LIMIT 1", 参).fetchone()
    return r[0] if r else None


def _派知会(c, 给谁, 客户, 店, 说明, 今天):
    """派一条「归属转移」知会任务 → 任务号。给谁为空(那家店没有在职店长)就不派。"""
    if not 给谁:
        return None
    import shop_key as SK
    n = c.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
    sid = f"SC{9000 + n + 1}"
    while c.execute("SELECT 1 FROM schedule WHERE id=?", (sid,)).fetchone():
        n += 1; sid = f"SC{9000 + n + 1}"
    c.execute("INSERT INTO schedule(id, type, advisor_no, customer_id, start_ts, end_ts, status, shop, shop_code, "
              "assignee_no, assigned_by, assigned_at, note, ref_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (sid, "归属转移", 给谁, 客户, f"{今天} 09:00", f"{今天} 18:00", "有效", 店, SK.码(c, 店),
               给谁, "SYS", f"{今天} 09:00", 说明, 客户))
    return sid


def 判定(c, oid, 今天=None):
    """→ (判定结果 dict, 上下文 dict)。只读。订单没记付款时间(标品「待付款 → 待发货」那条路不打 paid_at)就用今天当成交日。"""
    o = c.execute("SELECT id, customer_id, shop, advisor_no, paid_at FROM ordr WHERE id=?", (oid,)).fetchone()
    if not o:
        return dict(转=False, 要指定导购=False, 理由=f"没有订单 {oid}", 已过天数=None), {}
    _, cid, 成交店, 接待, 付款 = o
    cu = c.execute("SELECT shop, advisor_no, created FROM customer WHERE id=?", (cid,)).fetchone()
    if not cu:
        return dict(转=False, 要指定导购=False, 理由=f"没有客户 {cid}", 已过天数=None), {}
    档案店, 原导购, 建档 = cu
    import account_owner as AO
    同户 = AO.同户档案(c, [cid]) or [cid]
    q = ",".join("?" * len(同户))
    付款日们 = _日们(c, f"SELECT paid_at FROM ordr WHERE customer_id IN ({q}) AND shop=? AND id<>? AND paid_at IS NOT NULL",
                  *同户, 档案店, oid)
    跟进日们 = _日们(c, f"SELECT COALESCE(end_ts, start_ts) FROM schedule WHERE customer_id IN ({q}) AND advisor_no=? "
                      f"AND status IN ('完结','已完成')", *同户, 原导购) if 原导购 else []
    到店日们 = _日们(c, f"SELECT start_ts FROM appointment WHERE customer_id IN ({q}) AND shop=? AND status IN ('已到店','已完成')",
                  *同户, 档案店)
    维, 来自 = OP.最后维护日(付款日们, 跟进日们, 到店日们, 建档)
    付款 = 付款 or 今天
    结果 = OP.该转吗(档案店, 成交店, 原导购, 接待, 维, 付款)
    return 结果, dict(订单=oid, 客户=cid, 同户=同户, 档案店=档案店, 成交店=成交店, 原导购=原导购, 接待导购=接待,
                      最后维护=str(维) if 维 else None, 维护来自=来自, 成交日=str(付款)[:10] if 付款 else None)


def 成交后(c, oid, 今天, 操作人="系统"):
    """付款后调一次 → dict(转了吗, 理由, 改了的客户, 知会任务…)。在调用方给的连接 / 事务里写。"""
    结果, 上 = 判定(c, oid, 今天)
    出 = dict(转了吗=False, 理由=结果["理由"], **上)
    if 结果.get("要指定导购"):
        店长 = _店长(c, 上["成交店"])
        出["指定导购任务"] = _派知会(c, 店长, 上["客户"], 上["成交店"],
                               f"【指定导购】客户 {上['客户']} 已过归属保护期并在本店成交({oid}),但这一单没有接待导购 —— "
                               f"请指定一位导购,指定后整户转过来。", 今天)
        return 出
    if not 结果["转"]:
        return 出
    import account_owner as AO
    import shop_key as SK
    改了 = AO.改导购(c, [上["客户"]], 上["接待导购"], shop=上["成交店"], shop_code=SK.码(c, 上["成交店"]))
    说明 = (f"【归属转移】客户 {上['客户']}(同户 {len(改了)} 条档案)从 {上['档案店']} 导购 {上['原导购']} "
            f"转给 {上['成交店']} 导购 {上['接待导购']}。依据:最后一次维护 {上['最后维护']}({上['维护来自']}),"
            f"到这一单付款({oid},{上['成交日']})已过 180 天保护期。有异议请走「客户转移」审批转回。点「知道了」即完成。")
    知会 = [_派知会(c, 谁, 上["客户"], 店, 说明, 今天) for 谁, 店 in
          ((上["原导购"], 上["档案店"]), (_店长(c, 上["档案店"]), 上["档案店"]), (_店长(c, 上["成交店"]), 上["成交店"]))]
    # 操作日志由调用方在**事务提交之后**记(记日志另开连接,在这个写事务里记会互相锁住)—— 见 记日志()
    出.update(转了吗=True, 改了的客户=改了, 知会任务=[x for x in 知会 if x], 说明=说明)
    return 出


def 记日志(出, 操作人="系统"):
    """成交后() 的返回 → 转了就写一条操作日志。调用方在事务提交之后调。"""
    if not (出 or {}).get("转了吗"):
        return
    from oplog import log_op
    log_op(操作人, "customer", 出["客户"], f"{出['档案店']}/{出['原导购']}", f"{出['成交店']}/{出['接待导购']}", True,
           "OWNER_TRANSFER", 出["说明"], {"order": 出["订单"]})
