#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给历史上没有工单的定制订单补工单(执行手册 W43 ①,2026-11-17)。

    python3 tools/backfill_workorders.py --干跑      # 只列:哪些单、各补几条,不写
    python3 tools/backfill_workorders.py            # 真写(共享库:先拿锁、先告诉并行会话)
    python3 tools/backfill_workorders.py --库 路径   # 指到别的库(检查在副本上用)

补的是 `待生产` / `生产中` 两档里一条工单都没有的定制品订单,规则和运行时同一个函数(backend/workorder_auto.生成):
每道工艺一条、artisan 留空、状态「待派」—— **不替排产决定派给谁**。note 写「补录」,和运行时自动生成的分得开。
造数(seed.py)已经建了的 53 条不碰。
"""
import os, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import workorder_auto as W  # noqa: E402


def main():
    a = sys.argv[1:]
    干跑 = "--干跑" in a
    库 = a[a.index("--库") + 1] if "--库" in a else os.path.join(ROOT, "backend", "lanxiu.db")
    c = sqlite3.connect(库)
    缺 = W.缺工单的(c)
    print(f"{'(干跑)' if 干跑 else ''}定制品订单在 待生产 / 生产中 而一条工单都没有的:{len(缺)} 张"
          f"(待生产 {sum(1 for _, s in 缺 if s == '待生产')} / 生产中 {sum(1 for _, s in 缺 if s == '生产中')})")
    建了, 没工艺 = 0, []
    if 干跑:
        for oid, s in 缺[:8]:
            print(f"  · {oid} {s}:{[名 for 名, _ in W.该建哪些(c, oid)] or '(订单行里没有定制品工艺,补不出)'}")
        if len(缺) > 8: print(f"  · … 还有 {len(缺) - 8} 张")
        return 0
    with c:
        for oid, s in 缺:
            新 = W.生成(c, oid, 备注=f"补录(原状态 {s})")
            建了 += len(新)
            if not 新: 没工艺.append(oid)
    print(f"  建了 {建了} 条工单;{len(没工艺)} 张单订单行里没有定制品工艺、补不出:{没工艺[:5]}{'…' if len(没工艺) > 5 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
