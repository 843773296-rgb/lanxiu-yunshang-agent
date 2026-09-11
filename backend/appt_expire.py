#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预约自动过期 —— 把状态机上写着、却从来没人跑过的那条规则补上。

状态机 `bk-appt` 的 `auto` 里白纸黑字写着:

    预约结束 2 小时后未处理自动过期

而库里 4 条「已预约」全部已经过了预约时间、状态一个都没变 ——
**规则写在说明书里,没有任何东西去执行它。**
这类缺口最难发现:文档是对的、代码没报错、数据看着也正常,
只是那条规则**从来没生效过**。

## 三条约束

**① 只动状态机认的状态。**
库里还有 46 条「待确认」,它**不在 `bk-appt` 的状态列表里**。
这一条挂着没解决(是说明书漏了一档,还是数据脏了,要业务拍板),
所以这里**一条都不碰**,只把它数出来报给人看。
**不许因为「反正都过期了」就顺手一起改** ——
那等于替一个没定义的状态定义了行为。

**② 流转走 `fsm.check`,不自己判。**
「已预约 → 已过期」是不是合法,状态机说了算。这里再判一遍就是第二个来源。

**③ 每一条都进台账,而且标明是系统做的。**
自动跑的东西**最需要留痕** —— 人做的事有人记得,系统做的事只有日志记得。
出事时要查得出「这条是谁改的」,答案是「系统,在某时某刻,按某条规则」。

默认 dry-run,`--go` 才真改。
"""
import os, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sqlite3
import fsm
from oplog import log_op

DB = os.path.join(HERE, "lanxiu.db")
宽限小时 = 2          # 状态机 auto 里写的那个 2 小时
可过期的 = "已预约"    # **只动这一个状态**;「待确认」不在状态机里,不碰


def 到点了(end_ts, now, 宽限=宽限小时):
    """预约结束时间 + 宽限 < 现在。**now 从外面传** —— 同 knowledge 里那条纪律:
    取当前时间的人和做判定的人不该是同一个,否则结果没法复现。"""
    if not end_ts:
        return False          # 没有结束时间就判不了,**不许猜成「过期了」**
    try:
        t = datetime.datetime.fromisoformat(str(end_ts)[:19].replace("T", " "))
    except ValueError:
        return False
    return t + datetime.timedelta(hours=宽限) < now


def scan(now=None):
    """返回 (该过期的, 状态机外的)。不改任何东西。"""
    now = now or datetime.datetime.now()
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    认的 = set(fsm.SM["bk-appt"]["states"])
    该过期, 野 = [], []
    for r in c.execute("SELECT id,customer_id,shop,advisor,start_ts,end_ts,status "
                       "FROM appointment"):
        if r["status"] not in 认的:
            野.append(dict(r)); continue
        if r["status"] == 可过期的 and 到点了(r["end_ts"], now):
            该过期.append(dict(r))
    c.close()
    return 该过期, 野


def run(go=False, now=None):
    now = now or datetime.datetime.now()
    该过期, 野 = scan(now)
    print(f"预约自动过期 · {'真跑' if go else 'dry-run(加 --go 才真改)'} · "
          f"基准时间 {now:%Y-%m-%d %H:%M}")
    print(f"  规则:{可过期的} 且 结束时间 + {宽限小时} 小时 < 现在  →  已过期")
    print(f"  该过期的 {len(该过期)} 条")
    for r in 该过期[:10]:
        print(f"    {r['id']}  {r['customer_id']}  {r['shop']}  "
              f"{r['start_ts']}~{r['end_ts']}  [{r['status']}]")
    if 野:
        import collections
        d = collections.Counter(r["status"] for r in 野)
        print(f"  ⚠️ **状态机外的 {len(野)} 条,一条都不碰**:{dict(d)}")
        print(f"     它们不在 bk-appt 的状态列表里 —— 是说明书漏了一档还是数据脏了,"
              f"要业务拍板。**不许因为「反正都过期了」就顺手一起改**")

    if not go or not 该过期:
        return 0

    # **一条一提交,不攒着。** 攒着提交的话,这个连接会从第一次 UPDATE
    # 一直持有写锁,而 `log_op` 另开一个连接也要写 —— 直接 database is locked。
    # 一条一提交还有个好处:中途挂了,已经改的那几条**都有对应的台账**,
    # 不会出现「数据改了但没记」。
    c = sqlite3.connect(DB, timeout=10)
    done = 0
    for r in 该过期:
        ok, code, why = fsm.check("bk-appt", r["status"], "已过期", {})
        if not ok:
            # 状态机说不行就不行。**这里不许有「但是」** ——
            # 自动任务绕过状态机,是最难查的那种数据损坏。
            print(f"    跳过 {r['id']}:{code} {why}")
            log_op("系统", "appt-expire", r["id"], r["status"], "已过期", False, code,
                   why[:120], {"auto": True})
            continue
        c.execute("UPDATE appointment SET status='已过期' WHERE id=?", (r["id"],))
        c.commit()
        log_op("系统", "appt-expire", r["id"], r["status"], "已过期", True, "AUTO_EXPIRE",
               f"结束时间 {r['end_ts']} 已过 {宽限小时} 小时,按状态机自动过期"[:120],
               {"auto": True, "rule": "预约结束 2 小时后未处理自动过期"})
        done += 1
    c.close()
    print(f"  已改 {done} 条,每条都进了台账(actor=系统)")
    return 0


if __name__ == "__main__":
    sys.exit(run("--go" in sys.argv))
