#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户业务摘要 —— 接手一位老客户时,打电话前要知道的五件事(复审第 4 节 A,用户 10-23 拍)。

场景:顾问休假 / 离职 / 换店,另一个人接手。这些信息原来散在商机、方案、订单、日程四处,
客户详情页一样都没显示 —— 接手人翻漏了,就会重复问客户、或者忘了之前答应过的事。

**只读、不写库、不建表。** 只把库里已有的东西拼起来:

    需求原话   商机里逐字抄下的客户原话(opportunity_need.quote),连同那条商机现在的状态
    方案和订单 这位客户名下的方案,以及按方案号连得上的订单(ordr.scheme_id)
    负责人     客户档案上的顾问;**换过几手**看 cust_owner_log —— 没有记录就明说「不知道」,不推
    下一步     三个来源**都列、每条标来源、按到期排**(用户 10-23 拍):
                 商机的下一步  opportunity.next_step,商机没到终态的;**商机表没有到期日列**,所以这一类没有到期日
                 日程          schedule 挂着这位客户、还「有效」(没完结 / 没取消)的
                 商机任务      opportunity_task 那几条日程(**它们也在 schedule 里** —— 归到这一类,不在「日程」里重复列)
               到期日:日程类取结束时间,没有就取开始时间;没有到期日的排在最后(不是丢掉)
    承诺       **没有结构化记录** —— 全库没有一处记过答应了客户什么。
               ⚠️ 不许用模型(或者任何关键词)从聊天 / 跟进 / 通话里抽「承诺」:
               抽出来的是没人确认过的承诺,比空着更危险 —— 接手人会照着去兑现一件客户没要过的事,
               或者以为清单是全的、漏掉真答应过的那件

「日程还开着」的口径沿用 tasks.py:只有状态「有效」的日程能改派 / 完结,其余(完结 / 已完成 / 取消 / 无效)都是收了尾的。
商机「没到终态」的口径沿用 knowledge/oppo_obj.py 的「终态」—— **不在这里另写一份**。

本模块**不取当前日期** —— 「已过到期日」要的「今天」由调用方传进来(服务端传世界的今天)。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_KN = os.path.join(os.path.dirname(_HERE), "knowledge")
if _KN not in sys.path:
    sys.path.insert(0, _KN)
import oppo_obj      # noqa: E402  商机终态的唯一源头
import scheme_ref    # noqa: E402  方案编码翻中文的唯一源头

日程开着 = "有效"          # tasks.py:只有「有效」的能改派 / 完结
来源 = ("商机的下一步", "日程", "商机任务")
承诺说明 = ("没有结构化记录 —— 系统里没有一处记过答应了客户什么。"
           "要知道之前答应过什么,只能翻跟进记录和通话、或者问原来的顾问;这里不替你从聊天里推。")

咬合 = []


def _q(conn, sql, *a):
    cur = conn.execute(sql, a)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _有表(conn, 名):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (名,)).fetchone())


def _名册(conn):
    try:
        return {r["no"]: r["name"] for r in _q(conn, "SELECT no, name FROM staff")}
    except Exception:
        return {}


def 下一步(conn, cid, 今天=None):
    """三个来源的未完成下一步,每条带 `来源`,按到期日升序;没有到期日的排最后。"""
    名册 = _名册(conn)
    out = []
    # ① 商机的下一步 —— 没到终态、写了下一步的
    for o in _q(conn, "SELECT id, status, next_step, advisor_no, updated FROM opportunity "
                      "WHERE customer_id=? ORDER BY id", cid):
        if o["status"] in oppo_obj.终态 or not (o["next_step"] or "").strip():
            continue
        out.append(dict(来源="商机的下一步", 内容=o["next_step"].strip(), 到期=None,
                        关联=o["id"], 状态=o["status"],
                        负责人=名册.get(o["advisor_no"]) or o["advisor_no"] or None))
    # ③ 商机任务 —— 先取,好让 ② 把它们排除掉(同一条日程不列两遍)
    商机任务号 = set()
    if _有表(conn, "opportunity_task"):
        for t in _q(conn, """SELECT t.schedule_id, t.opp_id, t.kind, s.status, s.start_ts, s.end_ts,
                                    s.note, s.summary, s.assignee_no, s.advisor_no
                             FROM opportunity_task t JOIN schedule s ON s.id=t.schedule_id
                             JOIN opportunity o ON o.id=t.opp_id
                             WHERE o.customer_id=? OR s.customer_id=? ORDER BY t.schedule_id""", cid, cid):
            商机任务号.add(t["schedule_id"])
            if t["status"] != 日程开着:
                continue
            out.append(dict(来源="商机任务", 内容=(t["note"] or t["kind"] or "").strip() or t["kind"],
                            到期=(t["end_ts"] or t["start_ts"] or None), 关联=t["schedule_id"],
                            商机=t["opp_id"], 类型=t["kind"], 状态=t["status"],
                            负责人=名册.get(t["assignee_no"] or t["advisor_no"]) or t["assignee_no"] or None))
    # ② 日程里没做完的
    for s in _q(conn, "SELECT id, type, status, start_ts, end_ts, note, assignee_no, advisor_no "
                      "FROM schedule WHERE customer_id=? AND status=? ORDER BY id", cid, 日程开着):
        if s["id"] in 商机任务号:
            continue
        out.append(dict(来源="日程", 内容=(s["note"] or s["type"] or "").strip() or s["type"],
                        到期=(s["end_ts"] or s["start_ts"] or None), 关联=s["id"], 类型=s["type"],
                        状态=s["status"],
                        负责人=名册.get(s["assignee_no"] or s["advisor_no"]) or s["assignee_no"] or None))
    out.sort(key=lambda x: (x["到期"] is None, x["到期"] or "", 来源.index(x["来源"]), str(x["关联"])))
    for x in out:
        x["已过到期日"] = bool(今天 and x["到期"] and x["到期"][:10] < 今天)
    return out


def 摘要(conn, cid, 今天=None):
    """一位客户的只读业务摘要。客户不存在返回 None。`今天` 由调用方给(本模块不取当前日期)。"""
    cu = _q(conn, "SELECT id, advisor_no FROM customer WHERE id=?", cid)
    if not cu:
        return None
    名册 = _名册(conn)

    # 需求原话 —— 每条都指得回逐字稿里那一句
    需求 = []
    if _有表(conn, "opportunity_need"):
        需求 = _q(conn, """SELECT n.opp_id 商机, o.status 商机状态, n.dim 维度, n.val 值, n.quote 原话, n.call_id 通话
                           FROM opportunity_need n JOIN opportunity o ON o.id=n.opp_id
                           WHERE o.customer_id=? ORDER BY n.opp_id, n.rowid""", cid)

    # 方案和订单
    方案 = []
    for s in _q(conn, "SELECT * FROM scheme WHERE customer_id=? ORDER BY updated DESC, id", cid):
        try:
            x = scheme_ref.展开(conn, s)
        except Exception:      # 主数据表不在(老库)也给得出方案号和名字
            x = {"方案号": s["id"], "名称": s.get("name"), "状态": s.get("status")}
        x["来自商机"] = s.get("opportunity_id")
        x["订单"] = _q(conn, "SELECT id, status, amount, created FROM ordr WHERE scheme_id=? ORDER BY created, id",
                     s["id"])
        方案.append(x)

    # 负责人 —— 现任看档案;换手看变更表,没有就明说不知道
    no = cu[0]["advisor_no"]
    换手 = _q(conn, "SELECT frm, too, action, basis, actor, ts FROM cust_owner_log "
                  "WHERE customer_id=? ORDER BY ts, id", cid) if _有表(conn, "cust_owner_log") else []
    负责人 = dict(工号=no, 名字=(名册.get(no) if no else None),
               换手记录=换手,
               换手说明=(f"负责人变更记录 {len(换手)} 条" if 换手 else
                     "没有负责人变更记录 —— 只知道现在是谁,之前换没换过、换过几手,系统里查不到"))

    return dict(客户=cid, 需求原话=需求, 方案=方案, 负责人=负责人,
                下一步=下一步(conn, cid, 今天),
                承诺=dict(有结构化记录=False, 条目=[], 说明=承诺说明))
