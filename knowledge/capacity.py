#!/usr/bin/env python3
"""产能排期 —— 工期算的是「要多少天」,这里算「什么时候能排上」。

工期推算一直有个最乐观的假设:**师傅立刻有空**。
而定制业最常见的延期原因恰恰是**排不上**,不是做得慢。

三条建模规则,都不是管理选择,是物理限制:

1. **工种不是通用劳动力。** 绣工不会织缂丝,织工也不裁衣服。
   找人得按「会不会这个工艺」找,不是按「有没有空」找。
2. **织造类一人一机,在制上限只能是 1。** 加人没用,加机器要先有机器和会用的人。
3. **同时接多件会摊薄日产能。** 一个绣工手上三件活,每件的进度都只有三分之一 ——
   在制上限不是「最多接几件」,是「接到第几件之后每件都变慢」。
"""
import datetime as dt, math, os, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「一人一机就加不了人」的判定去掉(缂丝被当成可以加人)',
     '缂丝只有一位织工,必须标为加不了人'),
]

def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c


def _d(x, default=None):
    try: return dt.date.fromisoformat(str(x)[:10])
    except Exception: return default


def artisans(craft=None):
    """会做这个工艺的在职师傅。不传就是全部。"""
    with _c() as c:
        rs = [dict(r) for r in c.execute("SELECT * FROM artisan WHERE status='在职' ORDER BY no")]
    if craft:
        rs = [r for r in rs if craft in (r["skills"] or "").split(",")]
    return rs


def load(from_date=None):
    """每位师傅当前压着多少活、最早什么时候能接新的。"""
    d0 = _d(from_date) or dt.date.today()
    out = {}
    with _c() as c:
        for r in c.execute("SELECT artisan,workdays,due_date FROM workorder WHERE status='在制'"):
            o = out.setdefault(r["artisan"], {"件数": 0, "工日": 0.0, "最早腾出": d0})
            o["件数"] += 1
            o["工日"] += r["workdays"] or 0
            due = _d(r["due_date"], d0)
            # 「最早腾出」= 手上最早做完的那一件的交期 —— 满负荷时要等它
            if o["件数"] == 1 or due < o["最早腾出"]: o["最早腾出"] = max(due, d0)
    return out


def when_free(craft, workdays, from_date=None):
    """这个工艺,最早什么时候能开工、谁来做、要做到几号。

    在制件数没到上限 → 现在就能开工,但**日产能按在制件数+1 摊薄**;
    到了上限 → 要等手上最早一件做完。
    """
    d0 = _d(from_date) or dt.date.today()
    who = artisans(craft)
    if not who:
        return {"error": f"没有师傅会做 {craft} —— **这不是排期问题,是产能缺口**,"
                         "要么外发,要么这个工艺接不了单"}
    ld, cand = load(from_date), []
    for a in who:
        cur = ld.get(a["no"], {"件数": 0, "工日": 0.0, "最早腾出": d0})
        wip, limit = cur["件数"], a["wip_limit"] or 1
        if wip < limit:
            start = d0
            rate = (a["day_rate"] or 1.0) / (wip + 1)      # 手上活越多,每件越慢
            how = f"在制 {wip}/{limit} 件,可插空开工,日产能摊薄到 {rate:.2f}"
        else:
            start = cur["最早腾出"]
            rate = (a["day_rate"] or 1.0) / limit
            how = f"在制 {wip}/{limit} **已满**,要等最早一件({cur['最早腾出']})做完"
        need = math.ceil((workdays or 0) / rate) if rate > 0 else 999
        cand.append(dict(师傅=a["name"], 编号=a["no"], 工种=a["trade"], 工坊=a["workshop"],
                         在制件数=wip, 在制工日=round(cur["工日"], 1),
                         可开工日=start.isoformat(), 需要天数=need,
                         预计完成=(start + dt.timedelta(days=need)).isoformat(),
                         说明=how, 备注=a["note"]))
    cand.sort(key=lambda x: (x["预计完成"], x["可开工日"]))
    best = cand[0]
    wait = (_d(best["可开工日"]) - d0).days
    return dict(工艺=craft, 需要工日=workdays, 起算日=d0.isoformat(),
                最早可开工=best["可开工日"], 排队等待天数=wait,
                建议师傅=best["师傅"], 预计完成=best["预计完成"],
                可选师傅=cand,
                不可加人=(len(who) == 1 or all((a["wip_limit"] or 1) == 1 for a in who)),
                note=("**只有一位师傅会这个工艺**,他排满了就只能等 —— 加钱也没用"
                      if len(who) == 1 else
                      f"{len(who)} 位师傅会这个工艺,可以挑最早的那位"))


def overview(from_date=None):
    """全工坊负载概览 —— 瓶颈在哪个工种。"""
    d0 = _d(from_date) or dt.date.today()
    ld = load(from_date)
    by = {}
    for a in artisans():
        t = by.setdefault(a["trade"], {"工种": a["trade"], "人数": 0, "在制件数": 0,
                                       "在制工日": 0.0, "总日产能": 0.0, "空闲人数": 0})
        cur = ld.get(a["no"], {"件数": 0, "工日": 0.0})
        t["人数"] += 1; t["在制件数"] += cur["件数"]; t["在制工日"] += cur["工日"]
        t["总日产能"] += a["day_rate"] or 1.0
        if cur["件数"] == 0: t["空闲人数"] += 1
    rows = []
    for t in by.values():
        t["在制工日"] = round(t["在制工日"], 1)
        t["消化天数"] = round(t["在制工日"] / t["总日产能"], 1) if t["总日产能"] else None
        rows.append(t)
    rows.sort(key=lambda x: -(x["消化天数"] or 0))
    return dict(起算日=d0.isoformat(), 按工种=rows, 瓶颈工种=rows[0]["工种"] if rows else None,
                note="「消化天数」= 手上的活按当前产能要做多久。"
                     "**这个数是新单排队的底** —— 它比工期本身更能解释为什么交期长。")


if __name__ == "__main__":
    import json
    print("产能排期 · 自测\n" + "=" * 78)
    A = artisans()
    print(f"在职师傅 {len(A)} 位")
    ov = overview("2026-09-04")
    print(f"  瓶颈工种:{ov['瓶颈工种']}")
    for t in ov["按工种"]:
        print(f"    {t['工种']}  {t['人数']} 人(空闲 {t['空闲人数']})· "
              f"在制 {t['在制件数']} 件 / {t['在制工日']} 工日 · 消化要 {t['消化天数']} 天")
    assert len(A) >= 20 and ov["瓶颈工种"]

    with _c() as c:
        NM = {r["code"]: r["name"] for r in c.execute("SELECT code,name FROM craft")}
    print("\n几个工艺现在排得上吗(需要 10 工日):")
    for k in ("KF11", "KF03", "KF01", "KF37"):
        r = when_free(k, 10, "2026-09-04")
        print(f"  {NM[k]:10s} 等 {r['排队等待天数']:>2} 天 → {r['最早可开工']} 开工,"
              f"{r['建议师傅']} 做,{r['预计完成']} 完成 · "
              f"{'**加不了人**' if r['不可加人'] else f'{len(r[chr(21487)+chr(36873)+chr(24072)+chr(20613)])} 人可选'}")

    print("\n没人会的工艺是产能缺口,不是排期问题:")
    with _c() as c:
        have = set()
        for r in c.execute("SELECT skills FROM artisan WHERE status='在职'"):
            have |= set((r["skills"] or "").split(","))
        allk = {r["code"] for r in c.execute("SELECT code FROM craft WHERE cat='工艺'")}
    gap = sorted(allk - have)
    print(f"  没有师傅会的工艺:{[NM[g] for g in gap] or '无'}")
    if gap:
        r = when_free(gap[0], 5, "2026-09-04")
        print(f"  查 {NM[gap[0]]} → {r['error'][:60]}")
        assert "产能缺口" in r["error"]

    print("\n一人一机的验证(缂丝):")
    r = when_free("KF01", 20, "2026-09-04")
    assert r["不可加人"], "缂丝只有一位织工,必须标为加不了人"
    print(f"  {r['note']}")
    print(f"  {r['可选师傅'][0]['说明']}")

    print("\n✅ 产能排期自测通过")
