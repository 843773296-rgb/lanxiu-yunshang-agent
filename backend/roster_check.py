# -*- coding: utf-8 -*-
"""排班的逐例真值 + 五种状态覆盖。

排班有个讨厌的性质:**「没排班」和「排了休息」都表现为「这个人那天不上班」** ——
而对 agent 来说含义相反:前者要说「排班还没出来」,后者才是「他没空」。

做错的后果很具体:**店长还没排下周的班,agent 照样给出推荐,
依据是「所有人下周都有空」** —— 而这个结论看起来完全正常。
"""
import os, sqlite3, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import roster as R

G, R_, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad = 0

# ── 咬合记录 ──────────────────────────────────────────────────────────
咬合 = [
    ('把「没有排班记录」也当成休息(和已发布的休息合并成一种)',
     '没排班 ≠ 没空'),
    ('让排班权限也认顾问(业务定的是只给店长)',
     '顾问不能排班'),
]


def ck(title, got, want, extra=""):
    global bad
    ok = got == want
    if not ok:
        bad += 1
    print(f"  {G+'✅'+D if ok else R_+'❌'+D} {title:44s} 判为 {str(got):14s} 应为 {want}{extra}")


def main():
    global bad
    from seed import TODAY
    c = sqlite3.connect(R.DB); c.row_factory = sqlite3.Row
    today = datetime.date.fromisoformat(TODAY)
    globals()["TODAY_d"] = today
    本周一 = today - datetime.timedelta(days=today.weekday())

    print("\n\033[1m▸ 排班 · 五种状态逐例标真值(没排和休息长得一样)\033[0m")
    print("  " + "=" * 80)

    人 = c.execute("select staff_no from roster where status=? limit 1", (R.已发布,)).fetchone()
    if not 人:
        print(f"  {R_}❌{D} 一条排班都没有 —— **空集合上什么都成立,这不叫通过**")
        return 1
    no = 人["staff_no"]

    # ① 已发布-上班
    上班日 = c.execute("""select d from roster where staff_no=? and status=? and shift<>'S0'
                          order by d limit 1""", (no, R.已发布)).fetchone()["d"]
    ok, 码, _ = R.在班吗(no, 上班日)
    ck("已发布-上班", 码, "ON")

    # ② 已发布-休息
    休日 = c.execute("""select d from roster where staff_no=? and status=? and shift='S0'
                        order by d limit 1""", (no, R.已发布)).fetchone()
    if 休日:
        ok, 码, _ = R.在班吗(no, 休日["d"])
        ck("已发布-休息", 码, "OFF")

    # ③ 草稿 —— **排了,但店长随时会改**
    草日 = c.execute("select d from roster where staff_no=? and status=? order by d limit 1",
                     (no, R.草稿)).fetchone()
    if 草日:
        ok, 码, _ = R.在班吗(no, 草日["d"])
        ck("草稿(排了但没发布)", 码, "DRAFT", "  ← 拿草稿派单,店长一改那些单全挂错人")

    # ④ **未排 —— 这一条是命根子**
    远 = (本周一 + datetime.timedelta(weeks=6)).isoformat()
    ok, 码, why = R.在班吗(no, 远)
    ck("没排班 ≠ 没空", 码, "UNSCHEDULED",
       "  ← **「排班还没出来」和「他没空」是两回事**")

    # ⑤ 请假 —— 盖掉已发布的班
    假 = c.execute("select * from leave_req where status='已批准' limit 1").fetchone()
    if 假:
        ok, 码, _ = R.在班吗(假["staff_no"], 假["d_from"])
        ck("请假盖掉排班", 码, "LEAVE", "  ← 已派的单要重新分配")
        # 请假**不改排班表** —— 那天的排班记录应该还在
        仍在 = c.execute("select count(*) from roster where staff_no=? and d=?",
                         (假["staff_no"], 假["d_from"])).fetchone()[0]
        ck("  └ 而且没有改掉那天的排班", "在" if 仍在 else "被改了", "在",
           "  ← 改排班会把「排了班但请假」和「本来就休息」抹成一件事")

    # ⑥ 在班 ≠ 那个点有空
    r = c.execute("select * from roster where staff_no=? and d=? ", (no, 上班日)).fetchone()
    名, a, b = R.班次表[r["shift"]]
    if a and a > "08:00":
        早 = f"{上班日} 08:00"
        ok, 码, _ = R.时段在班(no, 早, f"{上班日} 09:00")
        ck("在班 ≠ 那个点有空", 码, "OUT_OF_SHIFT", f"  ← 他是{名}({a}–{b}),预约在 08:00")

    print("\n\033[1m▸ 排班权限(P5)+ 档期预留(P3)\033[0m")
    print("  " + "=" * 80)
    # P5:排班权给店长,值班经理本期不做
    店长 = c.execute("select no from staff where role='店长' and status='启用' limit 1").fetchone()
    顾问1 = c.execute("select no from staff where role='顾问' and status='启用' limit 1").fetchone()
    if 店长:
        ok, _ = R.能排班吗(店长["no"]); ck("店长能排班", ok, True)
    if 顾问1:
        ok, _ = R.能排班吗(顾问1["no"]); ck("顾问不能排班", ok, False,
                                          "  ← 业务 2026-09-20:排班权给店长,值班经理本期不做")
    ok, why = R.能排班吗("99999999")
    ck("查不到的工号:说的是「数据问题」不是「没权限」", "数据问题" in why, True,
       "  ← 两者都派不了,但**下一步动作不同**:一个修数据,一个找有权限的人")

    # P3 第③步:预留 —— **和「已预约」必须分开**
    R.建预留表(c)
    c.execute("delete from slot_hold where reason like '自测%'")
    if 顾问1:
        日 = (TODAY_d + datetime.timedelta(days=3)).isoformat()
        起, 止 = f"{日} 11:00", f"{日} 12:00"
        R.预留(顾问1["no"], 起, 止, reason="自测:客户点名改约下次", 有效天数=14, conn=c)
        c.commit()
        有, 话 = R.时段被预留了吗(顾问1["no"], 起, 止)
        ck("预留之后那个时段查得出来", 有, True, "  ← 否则「留了」等于没留")
        # 过期的不算 —— **一个不会过期的预留,和一条被占死的档期,长得一模一样**
        c.execute("update slot_hold set expires_at=? where reason like '自测%'",
                  ((TODAY_d - datetime.timedelta(days=1)).isoformat(),))
        c.commit()
        有2, _ = R.时段被预留了吗(顾问1["no"], 起, 止)
        ck("过期的预留不算占用", 有2, False,
           "  ← **不会过期的预留 = 被占死的档期**,而看板上「排满了」长得一样")
        c.execute("delete from slot_hold where reason like '自测%'"); c.commit()

    print("\n\033[1m▸ 排班 · 覆盖(没有样本不叫通过)\033[0m")
    print("  " + "=" * 80)
    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    统 = {"已发布-上班": q("select count(*) from roster where status=? and shift<>'S0'", R.已发布),
          "已发布-休息": q("select count(*) from roster where status=? and shift='S0'", R.已发布),
          "草稿": q("select count(*) from roster where status=?", R.草稿),
          "请假": q("select count(*) from leave_req where status='已批准'")}
    for k, v in 统.items():
        mark = f"  {Y}⚠ 没有样本{D}" if v == 0 else ""
        print(f"     {k:12s} {v:4d}{mark}")
        if v == 0:
            bad += 1
    print(f"     {'未排':12s}    — (未来第 6 周查不到行,就是它)")

    # **一人一天只有一个班次** —— 这条约束不在数据库里(见 roster.py 的说明),
    # 所以必须在这儿验。**库不挡的东西,检查就得挡,否则它只是一句注释。**
    重 = q("""select count(*) from (select staff_no, d from roster
                                    group by staff_no, d having count(*)>1)""")
    ck("一人一天只有一个班次", "是" if 重 == 0 else f"{重} 个人天重复", "是",
       "  ← 数据库不挡这个(工厂造不出复合唯一约束的表),**靠这条检查挡**")

    # 合规:每人每周至少休 N 天 —— N 从口径模块取(业务 2026-09-22 确认 N=1),
    # 逐个人周交给 `R.这一周合规吗()` 判,**不在检查里另写一遍规则**
    import sqlite3 as _sq
    _c = _sq.connect(R.DB)
    周们 = {}
    for 工号, w, 班 in _c.execute("""select staff_no, strftime('%W', d), shift from roster
                                      where status=?""", (R.已发布,)):
        周们.setdefault((工号, w), []).append(班)
    _c.close()
    坏 = [k for k, v in 周们.items() if not R.这一周合规吗(v)[0]]
    ck(f"每人每周至少休 {R.每周至少休几天} 天(验了 {len(周们)} 个人周)",
       "是" if (周们 and not 坏) else (f"{len(坏)} 个人周不合规" if 坏 else "没有已发布的班 —— 没东西可验"),
       "是")

    print()
    if bad:
        print(f"{R_}❌ 排班 {bad} 处不符合预期{D}")
        return 1
    print(f"{G}✅ 排班全部符合预期{D}")
    print(f"    **「没排班」「草稿」「休息」「请假」都表现为「他那天不上班」** ——")
    print(f"    而四种的下一步动作两两不同,所以四种都得分开。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
