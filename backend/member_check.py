#!/usr/bin/env python3
"""会员生命周期 · 真值对账。

`truth` 表里 BP-05 有 14 条**手工标注**的判定结果,全是边界用例:
六个时间含端点(90/91/180/181/365/366)、金额含端(15000 / 14999)、
忠诚要跨两季度、三条优先级冲突、人工调整窗内外各一条。

这里拿 `knowledge/lifecycle.py` 的实现去对这 14 条标注。

**为什么这是个有效的检查**:标注是在 seed 里**逐字写死**的字面量
(`("E-A3-03", ..., "休眠", "休眠区间上界含端")`),不是算出来的;
判定是另一套代码。两边对不上,说明有一边错了。

⚠️ **对不上时不要直接改标注。** 标注是照 PRD 6.1 一条条写的,
把它改成代码算出来的值,等于把这个检查关掉 —— 判责那边同一句话已经写过一遍。
"""
import os, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "knowledge"))
import lifecycle as _lc

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row

# 边界用例的客户号和 case_id 同名(seed 里就是这么建的)
rows = [dict(r) for r in c.execute("""
    SELECT t.case_id, t.root_cause, t.expected_evidence, t.note,
           cu.order_cnt, cu.idle_days, cu.amount_12m, cu.orders_12m, cu.quarters_12m,
           cu.first_order, cu.manual_lc, cu.manual_at, cu.lifecycle
      FROM truth t JOIN customer cu ON cu.id = t.case_id
     WHERE t.breakpoint='BP-05' ORDER BY t.case_id""")]

if not rows:
    print("❌ 一条 BP-05 用例都取不到 —— 种子数据的口径变了,先看 seed.py"); sys.exit(1)

import datetime as dt
T = dt.date(2026, 8, 31)     # 种子的基准日。**判定不取当前日期**,所以对账可复现。
# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把生命周期的优先级顺序倒过来(同时命中多档时取的不再是该取的那一档)',
     '条对不上'),
]

def ago(iso): return (T - dt.date.fromisoformat(iso)).days if iso else None

bad = []
print(f"会员生命周期 · {len(rows)} 条边界标注对账")
print("=" * 96)
for r in rows:
    v = _lc.decide(dict(r, days_since_first_order=ago(r["first_order"]),
                        days_since_manual=ago(r["manual_at"])))
    ok = v["生命周期"] == r["root_cause"]
    if not ok: bad.append((r["case_id"], r["root_cause"], v["生命周期"], r["note"]))
    print(f"  {'✅' if ok else '❌'} {r['case_id']:10s} 标注「{r['root_cause']}」"
          f" / 判定「{v['生命周期']}」   {(r['note'] or '')[:34]}")

print("=" * 96)
if bad:
    print(f"❌ {len(bad)} 条对不上:")
    for cid, want, got, note in bad:
        print(f"   · {cid}:标注「{want}」vs 判定「{got}」—— {note}")
    print("   **不要直接把标注改成判定算出来的** —— 那等于把这个检查关掉。")
    print("   标注逐条来自后台 PRD 6.1,先回去核 PRD,再决定是标注错还是实现错。")
    sys.exit(1)
print(f"✅ {len(rows)} 条边界标注全部对上"
      f"(六个时间含端点 · 金额含端 · 忠诚跨季度 · 三条优先级 · 人工窗内外)")
