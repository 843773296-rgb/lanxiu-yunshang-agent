#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报价写口的检查 —— 在库的**临时副本**上跑,真库一行都不碰。

钉的几件事(口径在 `knowledge/quote.py`,业务 2026-09-27 拍了两条):
    权限     顾问 / 店长能报;版师、工匠不能;没登录不能
    齐不齐   五样(物料成本 / 工期 / 可行性 / 尺码 / 现货)缺一样都不许落库
    事件     **一次报价一行,永不覆盖** —— 报两次就是两行,作数的是最新那条
    作废     要写原因;**不许重复作废**;作废的不算数、也不参与算涨幅
    失效方案 不许再报价(它上面的报价一律不作数)
    时间     用**世界时钟**,而且两列都登记进了 worldclock.已发生的时间列
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("让 落一次报价() 不查五样齐不齐", "缺一样 → 不许落库"),
    ("让 落一次报价() 覆盖上一条而不是新插一行", "报两次 = 两行,不覆盖"),
    ("让 作废一条报价() 不要求写原因", "作废不写原因 → 拒"),
    ("让 落一次报价() 给已失效的方案也能报", "已失效的方案 → 不许再报价"),
    ("让 落一次报价() 用机器时钟写 quoted_at", "报价时间用的是世界时钟"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:150]) if extra else ''}")
    if not ok: FAIL.append(name)


def main():
    print("报价写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 86)
    tmp = tempfile.mkdtemp(prefix="quotew-")
    T = os.path.join(tmp, "lanxiu.db")
    src = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); dst = sqlite3.connect(T)
    src.backup(dst); src.close(); dst.close()
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 报价写口 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 报价写口 {N[0]} 条全过\033[0m")


def run(T):
    import oplog, quote_write as qw, seed_quote, worldclock
    import quote as Q
    for m in (oplog, qw): m.DB = T
    seed_quote.建表(T)
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row

    列 = [r["name"] for r in c.execute("PRAGMA table_info(quote)")]
    ck("库里有报价表", bool(列))
    ck("不存最终售价(skill 说系数由财务和店长定)",
       not any(k in 列 for k in ("price", "sale_price", "final_price", "售价")),
       "存了就等于系统给出一个它无权给的数")
    ck("两个时间列都登记进了 worldclock.已发生的时间列(C4 和平移闸共用那份清单)",
       {("quote", "quoted_at"), ("quote", "voided_at")}
       <= {(t, col) for t, col, _, _ in worldclock.已发生的时间列})

    人 = lambda role: (lambda x: dict(x) if x else None)(c.execute(
        "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1",
        (role,)).fetchone())
    顾问, 店长, 版师 = 人("顾问"), 人("店长"), 人("版师")
    s = c.execute("SELECT id,customer_id,status FROM scheme WHERE status<>'已失效' "
                  "ORDER BY id LIMIT 1").fetchone()
    死 = c.execute("SELECT id FROM scheme WHERE status='已失效' ORDER BY id LIMIT 1").fetchone()
    ck("有人也有方案当夹具", bool(顾问 and 店长 and 版师 and s))
    if not (顾问 and 店长 and 版师 and s): return
    齐 = dict(scheme_id=s["id"], 物料成本=4956.0, 工期区间="28~35 天",
              可行性="可", 尺码="M", 现货="有")

    # ── 权限 ──
    ck("没登录 → 拒", qw.落一次报价(齐, None)["code"] == "NO_LOGIN")
    ck("版师 → 拒", qw.落一次报价(齐, 版师)["code"] == "ROLE")
    ck("方案不存在 → 拒", qw.落一次报价({**齐, "scheme_id": "SCH-XXX"}, 顾问)["code"] == "NO_SCHEME")

    # ── 齐不齐 ──
    基线 = c.execute("SELECT COUNT(*) FROM quote").fetchone()[0]
    没多 = lambda: c.execute("SELECT COUNT(*) FROM quote").fetchone()[0] == 基线
    for 少 in ("物料成本", "工期区间", "可行性", "尺码", "现货"):
        r = qw.落一次报价({k: v for k, v in 齐.items() if k != 少}, 顾问)
        ck(f"缺一样 → 不许落库(少了{少})", r["code"] == "NOT_READY" and 没多(), r.get("reason"))
    ck("物料成本是 0 照样能报(全用库存尾料是真事)",
       qw.落一次报价({**齐, "物料成本": 0}, 顾问)["ok"])
    c2 = sqlite3.connect(T)
    c2.execute("DELETE FROM quote"); c2.commit(); c2.close()   # 清掉上面那条,后面从零数

    ck("可行性「不可」→ 不出报价单",
       qw.落一次报价({**齐, "可行性": "不可"}, 顾问)["code"] == "NOT_READY")
    r = qw.落一次报价({**齐, "可行性": "需评估"}, 顾问)
    ck("可行性「需评估」→ 能报,但话里有「不构成承诺」",
       r["ok"] and "不构成承诺" in r["reason"], r.get("reason"))
    if 死:
        ck("已失效的方案 → 不许再报价",
           qw.落一次报价({**齐, "scheme_id": 死["id"]}, 顾问)["code"] == "SCHEME_DEAD")

    # ── 事件:报两次 = 两行 ──
    c2 = sqlite3.connect(T); c2.execute("DELETE FROM quote"); c2.commit(); c2.close()
    a = qw.落一次报价(齐, 顾问)
    ck("顾问能报价", a["ok"], a.get("reason"))
    行 = c.execute("SELECT * FROM quote WHERE scheme_id=?", (s["id"],)).fetchone()
    ck("经手人记的是登录的人(工号,不是名字)", 行["advisor_no"] == 顾问["no"])
    ck("报价时间用的是世界时钟",
       str(行["quoted_at"])[:10] == worldclock.今天().isoformat(),
       f"写出来 {行['quoted_at']},世界的今天 {worldclock.今天()}")
    b = qw.落一次报价({**齐, "物料成本": 5310.0}, 店长)
    ck("报两次 = 两行,不覆盖",
       c.execute("SELECT COUNT(*) FROM quote WHERE scheme_id=?", (s["id"],)).fetchone()[0] == 2)
    ck("第二次的返回里带上「和上次比」(顾问要能回答为什么和上次不一样)",
       bool(b.get("和上次比")), b.get("和上次比"))
    ck("返回里说清这份方案报过几次", "报过 2 次" in (b.get("这份方案的报价情况") or ""),
       b.get("这份方案的报价情况"))
    ck("作数的是最新那条",
       Q.作数的那条(qw.这个方案的报价(s["id"]), s["status"])[0]["物料成本"] == 5310.0)

    # ── 作废 ──
    ck("作废不写原因 → 拒",
       qw.作废一条报价({"报价号": a["报价号"], "原因": ""}, 顾问)["code"] == "CANNOT_VOID")
    ck("原因太短 → 拒",
       qw.作废一条报价({"报价号": a["报价号"], "原因": "错了"}, 顾问)["code"] == "CANNOT_VOID")
    ck("版师作废 → 拒",
       qw.作废一条报价({"报价号": a["报价号"], "原因": "幅宽算错了"}, 版师)["code"] == "ROLE")
    ck("报价号不存在 → 拒",
       qw.作废一条报价({"报价号": "Q-XXX", "原因": "幅宽算错了"}, 顾问)["code"] == "NO_QUOTE")
    v = qw.作废一条报价({"报价号": a["报价号"], "原因": "幅宽算错了,按整幅算了"}, 顾问)
    ck("写清楚了能作废", v["ok"], v.get("reason"))
    ck("作废的话里提醒「客户手里那份不会消失」",
       "客户手里那份不会因此消失" in v["reason"])
    ck("作废是**留痕不删** —— 那一行还在,只是多了作废时间和原因",
       (lambda x: x and x["voided_at"] and x["void_reason"] and x["voided_by"] == 顾问["no"])(
           c.execute("SELECT * FROM quote WHERE id=?", (a["报价号"],)).fetchone()))
    ck("行数没变(作废不是删)",
       c.execute("SELECT COUNT(*) FROM quote WHERE scheme_id=?", (s["id"],)).fetchone()[0] == 2)
    ck("不许重复作废(会覆盖第一次那个原因)",
       qw.作废一条报价({"报价号": a["报价号"], "原因": "再作废一次试试"}, 顾问)["code"]
       == "CANNOT_VOID")
    ck("作废的不参与算涨幅(不然算出来的涨幅是假的)",
       Q.价变了多少(qw.这个方案的报价(s["id"])) == [])
    # 把剩下那条也作废 → 没有作数的报价
    qw.作废一条报价({"报价号": b["报价号"], "原因": "客户改了面料,重新报"}, 店长)
    条, 话 = Q.作数的那条(qw.这个方案的报价(s["id"]), s["status"])
    ck("全作废了 → 没有作数的报价,而且明说「全都作废了」",
       条 is None and "全都作废了" in 话, 话)


if __name__ == "__main__":
    main()
