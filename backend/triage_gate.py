#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判队列上线门槛 · 四个 0(研判队列主方案判据 ⑦;原方案 C.3「已知严重越权、重复业务执行、失败假成功和无依据办结缺陷为 0」)。

在**真实的操作日志 + 研判记录**上把这四个数量出来 —— 各类分项检查都在,
而「拿真实数据算一遍,这四个数现在是几」原来没有任何一处在做(10-20 核方案时逮到)。

  越权         成功的动作,按现在的规则这个角色不该能做(能销吗 / 退款只认财务 / 两段确认得是两个人)
  重复业务执行  同一件事成功执行了两次(同一条研判办结两次、同一张押金登记已退两次、一个流水号证明两笔退款)
  失败假成功    记着失败,而东西照样变了(最后一条成功记录解释不了现在的状态)
  无依据办结    有回执(已办结),却没有一条成功的办结记录,或回执类型不是这类事认的那种

规则一律调现成的(ops.能销吗 / ops.两段 / ops.回执对照 / refund_write.财务),不另抄一份 ——
抄一份的话,规则改了这里跟着错,量出来的 0 是假的。

只读。→ 量(db) 返回 dict(四类各一个列表 + 样本数 + 只打印的旁注)。
"""
import json
import os
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

四类 = ("越权", "重复业务执行", "失败假成功", "无依据办结")


def _角色(ctx):
    try:
        return (json.loads(ctx or "{}") or {}).get("role"), (json.loads(ctx or "{}") or {}).get("no")
    except ValueError:
        return None, None


def 量(db=None):
    import ops
    import refund_write as rw
    出 = {k: [] for k in 四类}
    with closing(sqlite3.connect(db or ops.DB)) as c:
        c.row_factory = sqlite3.Row
        表 = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"op_log", "triage", "task"} <= 表:
            return dict(**出, 样本=dict(研判日志=0, 押金日志=0), 旁注=["库里缺 op_log / triage / task,什么都没量"])
        日志 = [dict(r) for r in c.execute(
            "SELECT * FROM op_log WHERE machine IN ('triage','bk-deposit') ORDER BY id")]
        研判 = {r["id"]: dict(r) for r in c.execute(
            "SELECT tr.*, t.type 类型 FROM triage tr LEFT JOIN task t ON t.id=tr.task_id")}
        押金 = ({r["id"]: r["status"] for r in c.execute("SELECT id, status FROM deposit")}
                if "deposit" in 表 else {})
        流水 = ([r[0] for r in c.execute("SELECT refund_no FROM refund_trace WHERE refund_no IS NOT NULL")]
                if "refund_trace" in 表 and "refund_no" in {x[1] for x in c.execute("PRAGMA table_info(refund_trace)")}
                else [])

    def 研判号(target):
        try:
            return int(str(target).split("#", 1)[1])
        except (IndexError, ValueError):
            return None

    按件 = {}
    for g in 日志:
        按件.setdefault((g["machine"], g["target"]), []).append(g)

    # ── 越权 ───────────────────────────────────────────────────────────
    for g in 日志:
        if not g["allowed"]:
            continue
        角色, 工号 = _角色(g["ctx"])
        if g["machine"] == "bk-deposit":
            if g["code"] == "REFUND_DONE" and 角色 != rw.财务:
                出["越权"].append(f"op_log#{g['id']} {g['target']} 登记已退的是「{角色}」(只认{rw.财务})")
            continue
        if g["code"] not in ("RESOLVE", "CLOSE") or (g["reason"] or "").startswith("[升级#"):
            continue     # 升级接手人的处理按升级单定的去向判,归 escalation 那份检查;系统动作没有角色
        t = 研判.get(研判号(g["target"]))
        if not t:
            continue
        段 = "办结" if g["code"] == "CLOSE" else "复核"
        行, 为什么 = ops.能销吗(t["类型"], 角色, 段=段)
        if not 行:
            出["越权"].append(f"op_log#{g['id']} {g['target']} {段}:{为什么}")
        if 段 == "办结" and t["类型"] in ops.两段:
            复核者 = [_角色(x["ctx"])[1] for x in 按件.get(("triage", g["target"]), [])
                      if x["allowed"] and x["code"] == "RESOLVE" and x["id"] < g["id"]]
            if 复核者 and 工号 and 复核者[-1] == 工号:
                出["越权"].append(f"op_log#{g['id']} {g['target']} 两段确认是同一个人({工号})从头点到尾")

    # ── 重复业务执行 ────────────────────────────────────────────────────
    for (机, 件), gs in 按件.items():
        码 = "CLOSE" if 机 == "triage" else "REFUND_DONE"
        成 = [g["id"] for g in gs if g["allowed"] and g["code"] == 码]
        if len(成) > 1:
            出["重复业务执行"].append(f"{件} 成功{'办结' if 机 == 'triage' else '登记已退'} {len(成)} 次(op_log#{成})")
    for no in sorted({x for x in 流水 if 流水.count(x) > 1}):
        出["重复业务执行"].append(f"退款流水号 {no} 证明了 {流水.count(no)} 笔退款")

    # ── 失败假成功:记着失败,而东西照样变了 ─────────────────────────────────
    # 只看**有日志**的件 —— 没有任何日志的旧记录量不了「失败后变了没有」,单独数进旁注
    for (机, 件), gs in 按件.items():
        if not any(not g["allowed"] for g in gs):
            continue
        成 = [g for g in gs if g["allowed"] and g["too"] not in ("—", "", None)]
        if 机 == "triage":
            t = 研判.get(研判号(件))
            if not t:
                continue
            改状态 = [g for g in 成 if g["too"] != "已办结"]
            应 = 改状态[-1]["too"] if 改状态 else "待复核"
            if t["status"] != 应:
                出["失败假成功"].append(f"{件} 现在是「{t['status']}」,而最后一条成功记录说的是「{应}」(中间有失败记录)")
            if t.get("receipt") and not any(g["too"] == "已办结" for g in 成):
                出["失败假成功"].append(f"{件} 办结失败过,而回执 {t['receipt']} 照样写上了")
        else:
            现 = 押金.get(件)
            if 现 == "已退" and not any(g["too"] == "已退" for g in 成):
                出["失败假成功"].append(f"押金 {件} 现在是「已退」,而登记已退只有失败记录")

    # ── 无依据办结 ─────────────────────────────────────────────────────
    for tid, t in 研判.items():
        if not t.get("receipt"):
            continue
        gs = 按件.get(("triage", f"triage#{tid}"), [])
        if not any(g["allowed"] and g["code"] == "CLOSE" for g in gs):
            出["无依据办结"].append(f"triage#{tid} 有回执 {t['receipt']},而没有一条成功的办结记录")
        认 = ops.回执对照.get(t["类型"])
        if 认 != t.get("receipt_kind"):
            出["无依据办结"].append(f"triage#{tid}「{t['类型']}」认的回执是「{认}」,记的是「{t.get('receipt_kind')}」")

    # ── 只打印的旁注(不是判据)────────────────────────────────────────────
    有日志 = {研判号(件) for (机, 件) in 按件 if 机 == "triage"}
    没日志 = {}
    for tid, t in 研判.items():
        if t["status"] != "待复核" and tid not in 有日志:
            没日志[t.get("handler") or "?"] = 没日志.get(t.get("handler") or "?", 0) + 1
    旁注 = []
    if 没日志:
        旁注.append(f"有 {sum(没日志.values())} 条研判状态变了、却没有任何操作日志(按处理人:{没日志})—— "
                    "研判写审计是 10-12 才加的,这些多是造数 / 清理脚本留下的;量不了它们失败后变没变,不算进上面四类")
    return dict(**出, 样本=dict(研判日志=sum(1 for g in 日志 if g["machine"] == "triage"),
                               押金日志=sum(1 for g in 日志 if g["machine"] == "bk-deposit"),
                               研判=len(研判)), 旁注=旁注)


if __name__ == "__main__":
    r = 量()
    for k in 四类:
        print(f"{k}:{len(r[k])}")
        for x in r[k][:10]:
            print("   ", x)
    print("样本:", r["样本"])
    for x in r["旁注"]:
        print("ℹ️", x)
