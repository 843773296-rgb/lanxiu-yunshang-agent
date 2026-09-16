#!/usr/bin/env python3
"""售后判责 · 对账与覆盖检查

## 对什么账

`truth` 表里 BP-03 的标注,是**种子里显式写出来的一套判断**;
`knowledge/liability.py` 是**从 09-养护与售后.md 第五节独立解析出来的另一套**。
两条实现,同一份文档 —— **对不上就说明有一边错了**。

这不是多此一举。如果真值是拿 liability.py 算出来的,那么用 liability.py 去评测
永远 100%,而这个 100% 什么也证明不了 —— 这叫**同源谬误**,
本项目已经为它单独建过一个 pinned_check.py。

## 还查一件容易被忽略的事:每条规则有没有用例

返修判定表有 7 行,但如果某一行**一条工单都没命中**,
那条规则在评测里等于不存在 —— 它可以是错的,而且永远不会被发现。

造数据时要盯的不是「分布均不均匀」,是「**每条规则有没有至少一个用例**」。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge"),
                os.path.join(os.path.dirname(HERE), "agent")]
import api, liability
# 答案表走**评测侧自己的只读连接**,不借工具层 ——
# 工具层已经把 truth 运行时拦死了,而这条边界正是这么被逼出来的。
import truthdb


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把判定表里「脱线」那一行的责任方从我方改成客方(标注还停在我方)',
     '两条实现来自同一份文档'),
]

def facts(mid):
    """判责要用的现场。和 get_maintain 走同一批表,但这里只取判据。

    ⚠️ **白坯试衣这一项是 2026-09-15 加的,而且必须加。**
    不加的话,`judge()` 拿不到试衣状态,新的两行判据在这套对账里
    **永远走不到** —— 而那正是这个文件第 14 行在防的事。
    """
    m = api._rows("SELECT * FROM maintain WHERE id=?", mid)
    if not m: return None
    m = m[0]
    notified = bool(api._rows("SELECT 1 FROM delivery_notice WHERE order_id=?", m["order_id"]))
    ms = api._rows("SELECT method FROM measure_rec WHERE customer_id=?", m["customer_id"])
    # 白坯试衣状态 —— 走工具层同一个算法,**不在这儿另判一遍**。
    # (这里是真值对账,「故意的第二套实现」指的是 md → liability.py 这条推导链,
    #  不是让每个取数的地方都各写一套 —— 那只会漂。)
    o = api._rows("SELECT status FROM ordr WHERE id=?", m["order_id"])
    f = api._白坯试衣(m["order_id"], m["item"], o[0]["status"] if o else None)
    return dict(issue=m["issue"],
                notified=notified,
                measure_full=(len(ms) >= 4),
                measure_remote=any(x["method"] == "远程" for x in ms),
                试衣状态=f.get("归到哪一档"))


# 人工标注用的那套话术 → liability.py 的 (责任, 处理关键词)
EXPECT = {
    "工艺瑕疵 · 我方免费返修":            ("我方", "免费返修"),
    # ── 2026-09-15 新加的两行(09 第五节)────────────────────────────
    # ⚠️ **这两条现在一条在办工单都没命中**,所以下面 ② 会报 ⚠️。
    # 那个 ⚠️ 是**故意留着**的:一条没有用例的规则可以是错的,
    # 而且永远不会被发现 —— 把它藏起来比让它显眼危险得多。
    #
    # 要让它们有用例,得新建一条维修工单**并给它写真值**。
    # 而真值是**故意的第二套实现**,我写等于和自己对账 ——
    # 所以这一步留给业务,已登记在 `intent/muslin-fitting.md`。
    "尺寸偏差 · 试衣已签字 · 客方收费改":  ("客方", "收费改"),
    "尺寸偏差 · 该试没试 · 我方免费改":    ("我方", "免费改"),
    "尺寸偏差 · 记录完整 · 客方收费改":    ("客方", "收费改"),
    "尺寸偏差 · 记录不全 · 我方免费改":    ("我方", "免费改"),
    "远程量体偏差 · 按合同分担":           ("按合同分担", ""),
    "特性类已告知 · 无责解释":             ("无责", "解释"),
    "特性类未告知 · 我方让步":             ("我方", "让步"),
}


def run(verbose=True):
    bad, rows = [], []
    tasks = api._rows("SELECT id, ref_id, summary FROM task WHERE type='售后判责' ORDER BY id")
    for t in tasks:
        tr = truthdb.rows("SELECT root_cause FROM truth WHERE case_id=? "
                          "AND breakpoint='BP-03'", t["ref_id"])
        f = facts(t["ref_id"])
        if not tr or not f:
            bad.append((t["id"], "查不到真值或现场")); continue
        rc = tr[0]["root_cause"]
        got = liability.judge(**f)
        want = EXPECT.get(rc)
        if not want:
            bad.append((t["id"], f"真值「{rc}」不在已知的六种判责结论里")); continue
        if not got["判得出"]:
            bad.append((t["id"], f"真值说「{rc}」,而规则判不出来({got['依据']})")); continue
        ok = (got["责任"] == want[0]) and (not want[1] or want[1] in (got["处理"] or ""))
        if not ok:
            bad.append((t["id"], f"标注「{rc}」 vs 规则「{got['责任']} / {got['处理']}」"))
        rows.append((t["id"], t["summary"], rc, got["责任"], got["处理"], ok))

    # 覆盖:七行规则里,哪几行一条用例都没有
    used = {r[2] for r in rows}
    missing = [k for k in EXPECT if k not in used]

    if verbose:
        print("售后判责 · 对账与覆盖\n" + "=" * 96)
        print(f"  研判工单 {len(tasks)} 条 · 判定表 {len(liability.table())} 行\n")
        print("  ① 人工标注 vs 从 md 独立推导")
        for tid, sm, rc, li, act, ok in rows:
            print(f"    {'✅' if ok else '❌'} {tid:12s} {(sm or '')[:24]:26s} "
                  f"标注「{rc}」 / 规则「{li} · {act}」")
        print(f"\n  ② 每条规则有没有用例({len(EXPECT)} 种判责结论)")
        for k in EXPECT:
            n = sum(1 for r in rows if r[2] == k)
            print(f"    {'✅' if n else '⚠️ '} {k:32s} {n} 条")
        if missing:
            print(f"\n  ⚠️ 上面 {len(missing)} 条规则**没有任何在办工单命中** ——")
            print("     它们只被 knowledge/liability.py 的单元自测覆盖,没有端到端用例。")
            print("     **没有用例的规则可以是错的,而且永远不会被发现。**")
    return bad, rows, missing


if __name__ == "__main__":
    bad, rows, missing = run()
    print("\n" + "=" * 96)
    if bad:
        print(f"❌ {len(bad)} 条对不上 —— **两条实现来自同一份文档,对不上就有一边错了**:")
        for t, w in bad: print(f"   · {t}:{w}")
        print("   不要直接把真值改成规则算出来的 —— 那等于把这个检查关掉。")
        sys.exit(1)
    print(f"✅ {len(rows)} 条判责标注与规则推导一致"
          f"{f';{len(missing)} 条规则暂无在办用例(已列出)' if missing else ''}")
