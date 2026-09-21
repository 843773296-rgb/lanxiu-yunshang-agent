#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把追得到接待的那几张定制单接上 —— **只接有证据的,一张不多接**。

## 为什么这个脚本几乎什么都不做

业务要的是**成交率**,而算率的前提是「这一单追得到是哪次接待促成的」。
2026-09-21 查库:

    定制单标「未接入」            3511 张
    下单前有过**到店接待**记录的     14 张
    全库「已到店 / 已完成」的预约      7 条
    581 个客户下过定制单,有预约记录的   55 个

所以这个脚本最多能接上 **14 张(0.4%)**。

**剩下的 3497 张不是「没接上」,是「接待没记」。**
这两件事下一步完全相反:前者是写代码,后者是业务改流程。
把它们硬接上去,**算出来的成交率看起来完全正常** —— 那是这个项目最怕的错。

## ⚠️ 接上的那批标「推断关联」,不是「已关联」

    已关联    系统里本来就记着这一单来自哪次预约(31 张)
    推断关联  按「下单前恰好一次到店接待」猜出来的

两者都能让成交率算出一个数,**而可信度完全不同**。
将来真实数据补上,可以把推断的那批重新核 —— 前提是现在就分开。

判定口径在 `knowledge/linkage.py`,这里只取数和写库。
"""
import os, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "knowledge"))
import linkage as _口径

DB = os.path.join(ROOT, "backend", "lanxiu.db")


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    单 = [dict(r) for r in c.execute(
        "SELECT id, customer_id, created FROM ordr WHERE appt_src='未接入'")]
    # 一次把所有候选预约读进来 —— **不要逐单查**。
    # 逐单查是 3511 次查询,这个项目为「逐客户循环」把门禁拖到超时过一次。
    候选 = {}
    for r in c.execute("SELECT id, customer_id, start_ts, status FROM appointment"):
        候选.setdefault(r["customer_id"], []).append(dict(r))

    按码, 要写 = {}, []
    for o in 单:
        前 = [a for a in 候选.get(o["customer_id"], [])
              if (a.get("start_ts") or "") < (o.get("created") or "")]
        来路, 码, _, aid = _口径.判(前)
        按码[码] = 按码.get(码, 0) + 1
        if aid:
            要写.append((aid, 来路, o["id"]))

    c.executemany("UPDATE ordr SET appt_id=?, appt_src=? WHERE id=?", 要写)
    c.commit()

    # ── 自检:写进去的条数要和判出来的条数对得上 ────────────────
    # **「一条都没写」和「写完了」在这个脚本的输出上长得一样** —— 所以核一遍。
    实 = c.execute("SELECT count(*) FROM ordr WHERE appt_src='推断关联'").fetchone()[0]
    c.close()
    if 实 != len(要写):
        sys.exit(f"❌ 判出来 {len(要写)} 张该接,库里却是 {实} 张 —— 写库没生效")

    print(f"  定制单 {len(单)} 张标着「未接入」,按证据分:")
    for 码 in sorted(按码, key=lambda k: -按码[k]):
        print(f"     {码:14s} {按码[码]:5d} 张   {_口径.下一步.get(码,'')[:52]}")
    print(f"  ✅ 接上了 {实} 张(标「推断关联」,**不是「已关联」**)")
    print(f"  ⚠️ **剩下的不是「没接上」,是「接待没记」** —— "
          f"那要业务改流程,不是改代码。")


if __name__ == "__main__":
    main()
