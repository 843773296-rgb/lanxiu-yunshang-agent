#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判队列 · 升级 = 一次正式转交(用户 2026-10-17 拍,方案见 intent/澜绣云裳agent-研判队列未做项方案.md 第 1 节)。

原来点「升级给店长」只把状态改成「已升级」:没有接收人、没有原因、没有期限,
而 `ops.queue` 把「已升级」算成**已销账** —— 计时停了、从待办里消失、又办不结(库里 5 条都是这样)。
> 一条「交出去、有人接了」和一条「交出去、没人接」,在原来的队列上长得一模一样:都不见了。

用户拍的四件事:
  ① 升给谁 —— 按类型(员工表里没有「财务主管」「区域经理」,改用现有岗位):
       退款失败 → 总部运营;客户合并 → 总部运营;售后判责 → 店长,店长自己发起的 → 总部运营
  ② 接单时限 4 个**工作小时**,超时没人接 → **自动退回**原负责人(标「超时退回」)
  ③ 时限**接着算** —— 升级不重置工单的计时,客户等的是总时长
  ④ 升级必须写原因;接收人可以接单,也可以写理由退回

「工作小时」= 门店营业时间(`booking.OPEN_HOUR`,每天 10–21 点,周末照常营业)—— 只此一份,不另抄。
⚠️ 这是开发按现有口径推的定义(总部运营若按工作日坐班,周末会多给出一天),业务没单独拍过。

状态:待接单 → 已接单 → 已复核;待接单 → 已退回(接收人写理由)/ 超时退回(过了期限)。
同一条研判同一时刻只能有一条「待接单 / 已接单」(唯一索引兜底,不靠先查再写)。
"""
import datetime as dt
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ── 升给谁(用户 2026-10-17 拍)───────────────────────────────────────────
去向表 = {
    "财务人工任务": "总部运营",
    "客户合并确认": "总部运营",
    "售后判责":     "店长",
}
# 发起人自己就是那个角色时再往上一级(「店长自己发起的售后单 → 总部运营」)
再上一级 = {"店长": "总部运营"}
接单时限工作小时 = 4
OPEN = ("待接单", "已接单")

DDL = """CREATE TABLE IF NOT EXISTS escalation(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  triage_id INTEGER, task_id TEXT, task_type TEXT,
  from_no TEXT, from_name TEXT, from_role TEXT,
  to_role TEXT,                -- 接收的岗位(谁都行,先接先得)
  reason TEXT,                 -- 升级原因(发起人写,必填)
  status TEXT,                 -- 待接单 / 已接单 / 已复核 / 已退回 / 超时退回
  created TEXT, deadline TEXT, -- deadline = created + 4 个工作小时
  handled_no TEXT, handled_name TEXT, handled_at TEXT,
  return_note TEXT)"""
UNIQ = ("CREATE UNIQUE INDEX IF NOT EXISTS ux_escalation_open ON escalation(triage_id) "
        "WHERE status IN ('待接单','已接单')")



def 去向(task_type, from_role):
    """→ (接收岗位, 为什么不行)。接收岗位为 None 时第二项说清为什么。"""
    to = 去向表.get(task_type)
    if not to:
        return None, f"「{task_type}」没登记升给谁 —— 不猜,先去 escalation.去向表 登记(要业务拍)"
    if from_role == to:
        to = 再上一级.get(from_role)
        if not to:
            return None, f"你是「{from_role}」,已经是这类工单升级的最上一级,不能再升 —— 自己复核,或线下找人"
    return to, ""


def 加工作小时(起, 小时):
    """起 + N 个工作小时(营业时间之外不走表)。营业前开始的从开门算,打烊后开始的从次日开门算。"""
    import booking
    开, 关 = booking.OPEN_HOUR
    t, 剩 = 起, dt.timedelta(hours=小时)
    while True:
        当天开 = t.replace(hour=开, minute=0, second=0, microsecond=0)
        当天关 = t.replace(hour=关, minute=0, second=0, microsecond=0)
        if t < 当天开:
            t = 当天开
        if t >= 当天关:
            t = 当天开 + dt.timedelta(days=1)
            continue
        if t + 剩 <= 当天关:
            return t + 剩
        剩 -= 当天关 - t
        t = 当天开 + dt.timedelta(days=1)


def 确保表(c):
    c.execute(DDL)
    c.execute(UNIQ)


def _有表(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='escalation'").fetchone())


def 发起(c, t, task_type, me, 理由, ts):
    """在 `ops.resolve` 的同一个事务里调:登记一条待接单。→ dict(to_role, deadline)。
    去向不行 / 没写理由 → 抛 ValueError(调用方回滚整个事务:研判状态、工单状态一起不动)。"""
    to, 为什么 = 去向(task_type, me.get("role"))
    if not to:
        raise ValueError(为什么)
    if not (理由 or "").strip():
        raise ValueError("升级要写原因 —— 接收人要知道为什么交给他、卡在哪一步")
    确保表(c)
    限 = 加工作小时(dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"), 接单时限工作小时).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO escalation(triage_id,task_id,task_type,from_no,from_name,from_role,to_role,reason,"
              "status,created,deadline) VALUES(?,?,?,?,?,?,?,?,'待接单',?,?)",
              (t["id"], t["task_id"], task_type, me.get("no"), me.get("name"), me.get("role"), to,
               理由.strip(), ts, 限))
    return dict(to_role=to, deadline=限)


def 当前(triage_id, db=None):
    """这条研判最近一条升级记录(没有 → None)。只读。"""
    import ops
    c = sqlite3.connect(db or ops.DB); c.row_factory = sqlite3.Row
    try:
        if not _有表(c):
            return None
        r = c.execute("SELECT * FROM escalation WHERE triage_id=? ORDER BY id DESC LIMIT 1", (triage_id,)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def 全部开着的(db=None):
    """→ {triage_id: 那条记录},只要最近一条。给 `ops.queue` 一次读完,不逐行查。"""
    import ops
    c = sqlite3.connect(db or ops.DB); c.row_factory = sqlite3.Row
    try:
        if not _有表(c):
            return {}
        出 = {}
        for r in c.execute("SELECT * FROM escalation ORDER BY id"):
            出[r["triage_id"]] = dict(r)
        return 出
    finally:
        c.close()


def _退回研判(c, triage_id):
    """研判回到「待复核」、工单回到「待处理」—— 只动还停在「已升级」的那一条。"""
    c.execute("UPDATE triage SET status='待复核' WHERE id=? AND status='已升级'", (triage_id,))
    c.execute("UPDATE task SET status='待处理' WHERE id=(SELECT task_id FROM triage WHERE id=?) AND status='已升级'",
              (triage_id,))


def 收超时(当下=None):
    """过了接单期限还没人接的 → 超时退回。幂等;每退一条写一行 op_log。→ 退回的条数。"""
    import ops
    from oplog import log_op as _log
    当下 = 当下 or ops.now()
    s = 当下.strftime("%Y-%m-%d %H:%M:%S")
    退 = []
    with sqlite3.connect(ops.DB) as c:
        if not _有表(c):
            return 0
        for eid, tid, to, 限 in c.execute("SELECT id, triage_id, to_role, deadline FROM escalation "
                                          "WHERE status='待接单' AND deadline < ?", (s,)).fetchall():
            if c.execute("UPDATE escalation SET status='超时退回', handled_at=? WHERE id=? AND status='待接单'",
                         (s, eid)).rowcount:
                _退回研判(c, tid)
                退.append((eid, tid, to, 限))
    for eid, tid, to, 限 in 退:
        _log("系统(接单超时)", "triage", f"triage#{tid}", "已升级", "待复核", True, "ESC_TIMEOUT",
             f"升级#{eid} 交给{to},接单期限内没人接 → 退回原负责人", {})
    return len(退)


def _办(esc_id, me, 动作, 理由=None):
    import ops
    from oplog import log_op as _log
    me = me or {}
    谁 = f"{me.get('name') or '?'}({me.get('no') or '?'})"
    def _记(ok, code, 话, tid="?"):
        _log(谁, "triage", f"triage#{tid}", "已升级", 动作 if ok else "—", ok, code, f"[升级#{esc_id}] {话}"[:200],
             {"role": me.get("role"), "no": me.get("no")})
    if not (me.get("no") and me.get("role")):
        _记(False, "NO_IDENTITY", "没有身份(工号 + 角色)")
        raise PermissionError("没有身份 —— 要登录")
    收超时()                                   # 先把过期的退掉,过期了就接不了
    e = None
    with sqlite3.connect(ops.DB) as c:
        c.row_factory = sqlite3.Row
        if _有表(c):
            e = c.execute("SELECT * FROM escalation WHERE id=?", (esc_id,)).fetchone()
    if not e:
        _记(False, "NO_ESC", "没有这条升级")
        raise ValueError(f"没有升级#{esc_id}")
    if me.get("role") != e["to_role"]:
        话 = f"这条升级交给的是「{e['to_role']}」,你是「{me.get('role')}」"
        _记(False, "ROLE", 话, e["triage_id"])
        raise PermissionError(话)
    if 动作 == "退回" and not (理由 or "").strip():
        _记(False, "NO_REASON", "退回没写理由", e["triage_id"])
        raise ValueError("退回要写理由 —— 原负责人要知道为什么你不接")
    ts = ops.now().strftime("%Y-%m-%d %H:%M:%S")
    新 = "已接单" if 动作 == "接单" else "已退回"
    with sqlite3.connect(ops.DB) as c:
        改 = c.execute("UPDATE escalation SET status=?, handled_no=?, handled_name=?, handled_at=?, return_note=? "
                       "WHERE id=? AND status='待接单'",
                       (新, me["no"], me.get("name"), ts, (理由 or "").strip() or None, esc_id)).rowcount
        if 改:
            if 动作 == "接单":
                # 回到待复核,由接单人复核(`ops.resolve` 认 handled_no);工单回到待处理,计时照旧从建单算
                c.execute("UPDATE triage SET status='待复核' WHERE id=? AND status='已升级'", (e["triage_id"],))
                c.execute("UPDATE task SET status='待处理' WHERE id=? AND status='已升级'", (e["task_id"],))
            else:
                _退回研判(c, e["triage_id"])
    if not 改:
        话 = f"这条升级现在是「{e['status']}」—— 只有待接单的能{动作}" + \
             ("(过了接单期限,已自动退回原负责人)" if e["status"] == "超时退回" else "")
        _记(False, "BAD_STATE", 话, e["triage_id"])
        return dict(ok=False, code="BAD_STATE", reason=话)
    _记(True, "ESC_" + ("ACCEPT" if 动作 == "接单" else "RETURN"), f"{动作}" + (f":{理由.strip()}" if 理由 else ""),
        e["triage_id"])
    return dict(ok=True, code=新, reason=("已接单,这条回到待复核,由你复核" if 动作 == "接单"
                                          else "已退回原负责人"))


def 接单(esc_id, me):
    return _办(esc_id, me, "接单")


def 退回(esc_id, me, 理由):
    return _办(esc_id, me, "退回", 理由)


def 接单人(triage_id, db=None):
    """这条研判当前「已接单」的那位的工号(没有 → None)。`ops.resolve` 用它决定谁能复核。"""
    e = 当前(triage_id, db)
    return e["handled_no"] if e and e["status"] == "已接单" else None


def 摘要(e):
    """给队列 / 详情页看的一行。e = None 表示「已升级」却没有升级记录(10-17 之前的旧数据)。"""
    if e is None:
        return dict(状态="旧数据:没有接收人", 去向=None, 期限=None, 接单人=None, 原因=None, id=None)
    return dict(状态=e["status"], 去向=e["to_role"], 期限=e["deadline"], 原因=e["reason"],
                接单人=e.get("handled_name"), 发起人=e.get("from_name"), 退回理由=e.get("return_note"), id=e["id"])
