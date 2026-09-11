#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把积分流水的**中间余额**重算对。两个来源都留着,只改内容。

## 先说清楚哪个是坏的

第一眼看到「268 条流水里 30 处对不上」,很容易以为两个来源在打架。
量准之后是另一回事:

    档案上的 points  vs  流水**最后一条**的余额   →  86/86 **全对**
    每一条「上一条余额 + 本次增减 = 本条余额」    →  30 处断

**两个来源在终点是一致的,断的只是中间。**
(第一版我把 `ORDER BY ts, rowid DESC` 写成了按 ts 升序取第一条,
量出「63 个对不上」—— 又是尺子错了,这一段里第三次。**数字反常先怀疑尺子。**)

看具体的流水就知道怎么坏的:

    2026-08-02  积分消费   -500   余额=0
    2026-08-15  账户调减   -500   余额=0      ← 应该是 -500
    2026-08-28  账户调加  +1000   余额=120    ← 应该是 1000,而 120 正是档案余额

**中间余额被 `max(0, ...)` 截断了**,最后一条被写成了档案上的真实余额。
所以 `delta` 是真的、终点是真的,**只有中间那一段是假的**。

## 修法:从终点倒推

    balance[i] = 最终余额 - (第 i+1 条之后所有 delta 之和)

这样三件事同时成立:
  · 最后一条余额 = 档案上的 points(**两个来源继续对得上,没有动它**)
  · 每一条都满足「上一条 + 增减 = 本条」
  · delta 一个都没改 —— **交易记录是原始凭证,不许为了让链条好看去改它**

## 期初为负不是错误,是事实

倒推之后有 19 个客户的期初是负数。那说明**这本流水不完整** ——
在第一条记录之前还有没入账的收支。
**这是事实,把它截断成 0 才是造假**:截断之后链条依然断,
只是断在一个看起来更体面的地方。

默认 dry-run,`--go` 才真改。
"""
import os, sqlite3, sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "lanxiu.db")


def plan():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    改, 负期初, 断点数 = [], 0, 0
    for cid, in c.execute("SELECT DISTINCT customer_id FROM points_log"):
        rows = [dict(r) for r in c.execute(
            "SELECT rowid AS rid,delta,balance FROM points_log WHERE customer_id=? "
            "ORDER BY ts,rowid", (cid,))]
        if not rows: continue
        终 = rows[-1]["balance"]
        # 从后往前倒推
        新 = [0] * len(rows)
        新[-1] = 终
        for i in range(len(rows) - 2, -1, -1):
            新[i] = 新[i + 1] - rows[i + 1]["delta"]
        断点数 += sum(1 for i in range(1, len(rows))
                     if rows[i - 1]["balance"] + rows[i]["delta"] != rows[i]["balance"])
        if 新[0] - rows[0]["delta"] < 0: 负期初 += 1
        for r, b in zip(rows, 新):
            if r["balance"] != b:
                改.append((cid, r["rid"], r["balance"], b))
    c.close()
    return 改, 负期初, 断点数


def main():
    go = "--go" in sys.argv
    改, 负期初, 断点数 = plan()
    print(f"{'真跑' if go else 'dry-run(加 --go 才真改)'}")
    print(f"  重算之前:{断点数} 处「上一条 + 增减 ≠ 本条」")
    print(f"  要改 {len(改)} 条流水的余额(**delta 一个都不动**)")
    for cid, rid, old, new in 改[:6]:
        print(f"    {cid}  rowid={rid}  余额 {old} → {new}")
    print(f"  倒推后期初为负的 {负期初} 个客户 —— "
          f"**这说明流水不完整,是事实不是错误**;截断成 0 才是造假")
    if go and 改:
        c = sqlite3.connect(DB)
        for _, rid, _, new in 改:
            c.execute("UPDATE points_log SET balance=? WHERE rowid=?", (new, rid))
        c.commit(); c.close()
        after = plan()[2]
        print(f"  已提交。重算之后:{after} 处断点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
