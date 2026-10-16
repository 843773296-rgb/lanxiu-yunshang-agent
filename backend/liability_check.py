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
    # 2026-10-16 并行会话从「改判下拉框」那边发现的:truth 表自己的两列对不上 ——
    # 根因写「超出公差 · **我方免费返修**」而动作写「**收费改**,出示量体记录」。
    # 那个框直接把 truth 的根因列给人选,于是一条自相矛盾的真值
    # 会被人当成标准答案点下去,而**此前没有任何东西盯着这件事**。
    ('把一条 BP-03 真值的 expected_action 改成和它根因相反的处理方式'
     '(根因说我方免费,动作写收费改)',
     '**truth 自己矛盾**'),
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
    # ── 2026-09-24 加的两个事实:实测尺寸差、什么时候签收的 ─────────────────
    # 不取这两个的话,新加的三行判据(超公差 / 公差内 / 证据不全+6 个月内)
    # **在这套对账里永远走不到** —— 同 2026-09-15 白坯试衣那次,这个文件开头就在防这件事。
    import json as _json
    尺寸差 = None
    if m.get("尺寸差"):
        try:
            尺寸差 = _json.loads(m["尺寸差"])
        except (ValueError, TypeError):
            尺寸差 = None
    签于 = api._rows("SELECT MAX(fit_at) t FROM pickup_item WHERE order_id=? AND fit_result='合身'",
                     m["order_id"])
    签于 = (签于[0]["t"] if 签于 else None) or (
        (api._rows("SELECT fit_at FROM pickup WHERE order_id=?", m["order_id"]) or [{}])[0].get("fit_at"))
    from seed import TODAY as _今天
    return dict(issue=m["issue"],
                notified=notified,
                measure_full=(len(ms) >= 4),
                试衣状态=f.get("归到哪一档"),
                尺寸差=尺寸差, 签收于=签于, 今天=_今天)


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
    # ── 2026-09-24 业务拍板加的三行(09 md 五之二:公差、举证时间窗)──────────
    # ⚠️ 同上:**现在一条在办工单都没命中**,所以下面会把它们列进「没有用例」那一栏。
    # 列出来是有意的 —— 一条新加的规则如果连出现在这张表里都不出现,
    # 它错了也永远不会被发现(比藏起来更危险的是:看起来这张表全绿)。
    "尺寸偏差 · 超出公差 · 我方免费返修":  ("我方", "免费返修"),
    "尺寸偏差 · 公差内 · 客方收费改":      ("客方", "收费改"),
    "特性类已告知 · 无责解释":             ("无责", "解释"),
    "特性类未告知 · 我方让步":             ("我方", "让步"),
}


def run(verbose=True):
    bad, rows, 没出过题 = [], [], []
    tasks = api._rows("SELECT id, ref_id, summary FROM task WHERE type='售后判责' ORDER BY id")
    for t in tasks:
        tr = truthdb.rows("SELECT root_cause FROM truth WHERE case_id=? "
                          "AND breakpoint='BP-03'", t["ref_id"])
        f = facts(t["ref_id"])
        # ⚠️ **「没出过评测题」和「真值丢了」要分开**(2026-10-15)。
        # 这条检查的职责是**拿 truth 和 knowledge/liability.py 的规则对账** ——
        # 它只管「出过题的那些，两份实现对不对得上」。
        # 2026-10-15 往队列里造了几条「AI 跑得动的未研判工单」给用户点,
        # 那几条**刻意不写 truth**(truth 是评测答案,编一份等于往评测里塞一道自己出的题) ——
        # 于是它们在这里被报成「查不到真值或现场」而整条红,**而没有一条是谁做错了**。
        #
        # 但也不能见到没真值就跳过:**真值丢了**也长这样。
        # 两者的区别在**现场**:现场(facts)查不到才是数据坏了。
        # > 一个「这条没出过评测题」和一个「这条的真值丢了」,
        # > **在「查不到真值」这句话上长得一模一样** —— 而只有后者该红。
        if not f:
            bad.append((t["id"], "查不到现场(维保单不在了?)—— 这是数据坏了")); continue
        if not tr:
            没出过题.append(t["id"]); continue
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
        # ⚠️ **只报不拦,但一定要报。** 这几条是给用户点的演示工单(没出过评测题),
        # 不在对账范围 —— 可它们**也不该静默消失**:数字对不上的时候,
        # 「有 3 条没参与对账」和「对账覆盖了全部」在上面那张表上长得一模一样。
        if 没出过题:
            print(f"\n  📖 另有 {len(没出过题)} 条**没出过评测题**(truth 里没有它),不参与对账:")
            print(f"     {没出过题}")
            print("     这些多半是 `tools/seed_triage_tasks.py` 造给用户点的演示工单 ——"
                  "**刻意不写 truth**(编一份真值等于往评测里塞一道自己出的题)。")
    # ── truth 自己不许自相矛盾(2026-10-16)──────────────────────────────
    #
    # 上面那几条对的是「真值 vs 口径规则」,而 **truth 表自己有两列**:
    # `root_cause` 和 `expected_action` —— 它们也会对不上,而**没有任何东西盯着**。
    #
    # 真事:库里那条「尺寸偏差 · **超出公差 · 我方免费返修**」的 expected_action
    # 写着「**收费改**,出示量体记录」。根因说我方免费、动作说收费。
    # 来路是 `backend/seed_repair.py` 那条 UPDATE **只改了根因没改动作**,
    # 而那几条记录原本是 seed.py 标注的「记录完整 · 客方收费改」。
    # 🔺 同一段造的另一条「公差内 · 客方收费改」**没暴露问题,只因为动作恰好仍然对** ——
    # 那比错的那条更危险:它让这个 bug 看起来只影响一条。
    #
    # 并行会话是从「改判下拉框」那边发现的 —— 那个框直接把 truth 的根因列给人选,
    # 于是一条自相矛盾的真值会**被人当成标准答案点下去**。
    # 用上面那份 EXPECT 逐条核,不另写一份「根因该配什么动作」。
    for r in truthdb.rows("SELECT case_id, root_cause, expected_action FROM truth "
                          "WHERE breakpoint='BP-03' ORDER BY case_id"):
        rc, act = r["root_cause"], r["expected_action"] or ""
        if rc not in EXPECT:
            continue                 # 不在已知六种里 —— 上面那条已经报过了
        _, 动作词 = EXPECT[rc]
        if 动作词 not in act:
            bad.append((r["case_id"],
                        f"**truth 自己矛盾**:根因「{rc}」要的是「{动作词}」,"
                        f"而 expected_action 写着「{act}」 —— "
                        f"改判下拉框会把这条当标准答案给人选"))

    return bad, rows, missing


if __name__ == "__main__":
    bad, rows, missing = run()
    print("\n" + "=" * 96)
    # 两类问题要**分开报**,别混进同一句汇总里:
    # ① 真值自己的两列对不上 → 去改那条真值(根因和处理方式必须一致)
    # ② 真值和口径规则对不上 → 两边有一边错了,要人看是哪一边
    # 混着报的后果不只是读起来累 —— 咬合**分不出红的是哪一条**
    # (2026-10-16 实测:新加的咬合「改坏真值的处理方式」红了,
    #  而红的那句汇总写的是「两条实现来自同一份文档」,于是它被判成
    #  「红了,但红的不是那一条」)。
    矛盾 = [(t, w) for t, w in bad if "truth 自己矛盾" in w]
    对账 = [(t, w) for t, w in bad if (t, w) not in 矛盾]
    if 矛盾:
        print(f"❌ {len(矛盾)} 条**truth 自己矛盾** —— 根因和 expected_action 对不上,"
              f"而改判下拉框会把这条当标准答案给人选:")
        for t, w in 矛盾: print(f"   · {t}:{w}")
        print("   去改那条真值(根因和处理方式必须一致);造数那头的来路见 "
              "backend/seed_repair.py 那条 UPDATE。")
    if 对账:
        print(f"❌ {len(对账)} 条对不上 —— **两条实现来自同一份文档,对不上就有一边错了**:")
        for t, w in 对账: print(f"   · {t}:{w}")
        print("   不要直接把真值改成规则算出来的 —— 那等于把这个检查关掉。")
    if bad:
        sys.exit(1)
    print(f"✅ {len(rows)} 条判责标注与规则推导一致"
          f"{f';{len(missing)} 条规则暂无在办用例(已列出)' if missing else ''}")
