#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定制订单进「待生产」要自动建工单 —— 在库的临时副本上真走一遍状态机(执行手册 W43 ①,2026-11-17)。

## 为什么

工单只在造数时生成过,运行时没有写口:11-17 现查生产中 354 张定制单只有 40 张有工单、待生产 33 张一张都没有。
排产和「做到哪了」全从工单算,没有工单的单在工坊那边不存在。现在 `server.transit` 落「待生产」时调
`workorder_auto.生成`。这条检查钉三件事:

    ① 走后台改状态进待生产 → 每道工艺一条工单、状态「待派」、不派人(artisan 空)—— **不替排产决定**
    ② 再生成一次不多建(幂等)
    ③ 真库里:上线之后进过待生产的定制单(op_log 里有那一步)都有工单;没有这种单就明说「没东西可验」

## 为什么在副本上

要真改订单状态、真写工单。真库一行不碰(项目在「检查污染数据」上栽过,piece_ratio_check 那次)。
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]
上线日 = "2026-11-17"

# ── 咬合记录(规格在 tools/bite_specs.json)────────────────────────────────
咬合 = [
    ("把 server.transit 里落「待生产」时调 workorder_auto.生成 那一句去掉",
     "进待生产自动建工单(每道工艺一条、待派、不派人)"),
    ("把 workorder_auto.生成 里「同一道工艺已有就跳过」那一句去掉",
     "再生成一次不多建(幂等)"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:160]) if extra else ''}")
    if not ok: FAIL.append(name)


def 副本上(T):
    import api, oplog, tasks, server, workorder_auto as W
    for m in (api, oplog, tasks, server): m.DB = T
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row
    if not {r["name"] for r in c.execute("PRAGMA table_info(workorder)")}:
        ck("库里有 workorder 表", False, "没有 —— 要先 ./tools/rebuild.sh"); return
    # 挑一张「待审核、订单行里有定制品工艺」的单 —— 按性质挑,不钉单号
    挑 = None
    for o in c.execute("SELECT id FROM ordr WHERE kind='定制品订单' AND status='待审核' ORDER BY id"):
        if W.该建哪些(c, o["id"]):
            挑 = o["id"]; break
    ck("有一张待审核、带定制品工艺的定制单可以推进", bool(挑), 挑 or "没有 —— 放行那一半测不到")
    if not 挑: return
    该 = W.该建哪些(c, 挑)
    前 = c.execute("SELECT COUNT(*) FROM workorder WHERE ref=?", (挑,)).fetchone()[0]
    总部 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='总部运营' AND status='启用' LIMIT 1").fetchone()
    r = server.transit("bk-order", 挑, "待生产", {}, 总部["name"], me=dict(总部))
    ck("后台能把这张单从待审核推到待生产(前提)", r.get("ok"), r.get("reason") or r.get("error"))
    if not r.get("ok"): return
    行 = c.execute("SELECT craft, artisan, status, note FROM workorder WHERE ref=? ORDER BY id", (挑,)).fetchall()
    ck("进待生产自动建工单(每道工艺一条、待派、不派人)",
       len(行) - 前 == len(该) and all(x["status"] == W.待派 and x["artisan"] is None for x in 行[前:]),
       f"该建 {len(该)} 条({[n for n, _ in 该]}),实际新建 {len(行) - 前} 条,状态 {[x['status'] for x in 行[前:]]}")
    有码 = [x for x in 行[前:] if x["craft"]]
    ck("对得上 craft 表的工艺写了编码,对不上的留空并在 note 里说明",
       all(("没有这道工艺的编码" in (x["note"] or "")) == (x["craft"] is None) for x in 行[前:]),
       f"有编码 {len(有码)} / 新建 {len(行) - 前}")
    with c:
        又 = W.生成(c, 挑)
    后 = c.execute("SELECT COUNT(*) FROM workorder WHERE ref=?", (挑,)).fetchone()[0]
    ck("再生成一次不多建(幂等)", not 又 and 后 == len(行), f"第二次回 {又},总数 {后}")
    # 标品订单:没有定制品行 → 什么都不建、也不报错
    标 = c.execute("SELECT id FROM ordr WHERE kind!='定制品订单' LIMIT 1").fetchone()
    if 标:
        with c:
            x = W.生成(c, 标["id"])
        ck("非定制品订单不建工单也不报错", x == [], x)
    # 产能计算只数「在制」:待派的不占师傅的队
    import capacity
    capacity.DB = T if hasattr(capacity, "DB") else None
    ck("「待派」不进产能的在制队(capacity._load 只数在制)",
       "status='在制'" in open(os.path.join(ROOT, "knowledge", "capacity.py"), encoding="utf-8").read())


def 真库上():
    """只读:上线之后经状态机进过待生产的定制单,现在还在待生产 / 生产中的,都该有工单。"""
    c = sqlite3.connect(f"file:{os.path.join(HERE, 'lanxiu.db')}?mode=ro", uri=True)
    try:
        单 = [r[0] for r in c.execute(
            "SELECT DISTINCT o.id FROM op_log l JOIN ordr o ON o.id=l.target WHERE l.machine='bk-order' AND l.too='待生产' "
            "AND l.allowed=1 AND l.ts>=? AND o.kind='定制品订单' AND o.status IN ('待生产','生产中')", (上线日,))]
        if not 单:
            print(f"  ℹ 真库里 {上线日} 之后还没有经状态机进待生产的定制单 —— 这一条没东西可验,不是通过(副本那半已验)")
            return
        缺 = [o for o in 单 if not c.execute("SELECT 1 FROM workorder WHERE ref=?", (o,)).fetchone()]
        ck(f"真库:上线后进过待生产的 {len(单)} 张定制单都有工单", not 缺, f"缺 {缺[:5]}")
    finally:
        c.close()


def main():
    print("工单自动生成 · 检查(在库的临时副本上跑,真库只读)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="wo-")
    T = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.path.join(HERE, "lanxiu.db"), T)
    try:
        副本上(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    真库上()
    print()
    if FAIL:
        print(f"\033[31m❌ 工单自动生成 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        return 1
    print(f"\033[32m✅ 工单自动生成 {N[0]} 条全过\033[0m —— 进待生产就有工单、每道工艺一条、待派不派人、幂等")
    return 0


if __name__ == "__main__":
    sys.exit(main())
