# -*- coding: utf-8 -*-
"""门店模型费用到上限 80% → 给本月用过的门店店长各派一条「费用提醒」(用户 11-13 拍第三十八条「店长和总部都推」;
总部那头是管理后台告警规则「门店月费用」,不在这里)。

在哪调:聊天站 /run 每记完一笔门店用量账、费用闸是「提醒」或「到顶」时(agentsite/app.py)。
**每月每家店只派一次**:靠 schedule 里 (type=费用提醒, ref_id=月份, 店) 查重 —— 不靠标记文件(文件丢了就会重派,
库里那条任务本来就是「派过了」的证据)。
派给谁:本月门店用量账里出现过的工号 → 他们的店 → 那家店在职店长(没有店长的店不派,照实返回)。
"""
import os
import sqlite3
from contextlib import closing

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")
类型 = "费用提醒"


def 要派吗(状态):
    return 状态 in ("提醒", "到顶")


def 说明(月, 合计, 上限, 状态):
    if 状态 == "到顶":
        return (f"{月} 门店模型费用 {合计:.2f} 美元,到了每月上限 {上限} 美元 —— 难题已经不再换贵模型,"
                f"回答质量可能下降;要加预算找总部")
    return (f"{月} 门店模型费用 {合计:.2f} 美元,过了每月上限 {上限} 美元的 80% —— 到顶后难题不再换贵模型;"
            f"看过点知道了,要加预算找总部")


def 派(c, 月, 合计, 上限, 状态, 工号们, 今天):
    """→ [(店, 任务号 或 None, 原因)]。只在 要派吗(状态) 时派;同月同店派过就跳过。c 是 backend 库连接,调用方提交。"""
    if not 要派吗(状态) or 合计 is None:
        return []
    import shop_key as SK
    import ownership_transfer as OT
    号们 = sorted({str(x) for x in 工号们 if x})
    if not 号们:
        return []
    店们 = sorted({r[0] for r in c.execute(
        f"SELECT shop FROM staff WHERE no IN ({','.join('?' * len(号们))}) AND shop IS NOT NULL", 号们).fetchall() if r[0]})
    出 = []
    for 店 in 店们:
        if c.execute("SELECT 1 FROM schedule WHERE type=? AND ref_id=? AND shop=?", (类型, 月, 店)).fetchone():
            出.append((店, None, "这个月已经派过"))
            continue
        长 = OT._店长(c, 店)
        if not 长:
            出.append((店, None, "这家店没有在职店长"))
            continue
        n = c.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
        sid = f"SC{9000 + n + 1}"
        while c.execute("SELECT 1 FROM schedule WHERE id=?", (sid,)).fetchone():
            n += 1
            sid = f"SC{9000 + n + 1}"
        c.execute("INSERT INTO schedule(id, type, advisor_no, customer_id, start_ts, end_ts, status, shop, shop_code, "
                  "assignee_no, assigned_by, assigned_at, note, ref_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, 类型, 长, None, f"{今天} 09:00", f"{今天} 18:00", "有效", 店, SK.码(c, 店),
                   长, "SYS", f"{今天} 09:00", 说明(月, 合计, 上限, 状态), 月))
        出.append((店, sid, "已派"))
    return 出


def 推(闸结果, 月, 工号们, 上限, db=None):
    """聊天站调的入口:开库、派、提交。**出任何错都不抛**(提醒没派上不能让回答失败),返回 (派了几条, 明细或错误)。"""
    if not 要派吗(闸结果.get("状态")):
        return 0, []
    try:
        import worldclock
        今天 = worldclock.今天()
        with closing(sqlite3.connect(db or DB, timeout=10)) as c, c:
            出 = 派(c, 月, 闸结果.get("本月"), 上限, 闸结果["状态"], 工号们, 今天)
        return sum(1 for _, s, _ in 出 if s), 出
    except Exception as e:  # noqa: BLE001
        return 0, f"费用提醒没派上({type(e).__name__}: {e})"[:200]
