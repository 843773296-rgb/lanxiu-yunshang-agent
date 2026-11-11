#!/usr/bin/env python3
"""店长排班写入口 —— 在**库副本**上真排、真改、真发布一遍(用户 2026-11-11 夜拍的四条)。

验的是入口真函数(backend/roster_write.py),不在夹具里重写一份:
  ① 只有店长能写;非本店的人混进一批 → 整批不写
  ② 草稿不生效:写了草稿,派单看到的还是 DRAFT;发布后才 ON
  ③ 🔑 改已发布的班:草稿另存一行,**发布前生效的仍是已发布那行**(不会因为店长在调就变成不可派)
  ④ 改班撞单:没确认 → 只回预览、一行不写;确认 → 照发 + 给店长建「待改派」任务;
     撞单只卡「要人在场」的类型(回电不算撞)
  ⑤ 合规拦发布:一周没排休息 / 跨周连上超过 6 天
  ⑦ 派单接排班:休息 / 不在时段的人不推荐;那周没发布(只有草稿 / 一格没排)不出推荐、说清原因
  ⑥ 真库一行没动(日志带 db 参数写副本;不带的话会往真库塞假痕迹 —— oplog.log_op 那段注释)
  ⑧ 口径里「要人在场的类型」和「待改派」都在 tasktypes 里有登记(名字漂了撞单会静默失效)
"""
import os
import sqlite3
from contextlib import closing
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
import shift as K            # noqa: E402
import roster                # noqa: E402
import roster_write as RW    # noqa: E402
import tasktypes             # noqa: E402

G, R_, D = "\033[32m", "\033[31m", "\033[0m"

# ── 咬合记录 ──────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」;每条在 tools/bite_specs.json 里有可执行规格。
咬合 = [
    ("查在不在班时草稿优先于已发布(店长一改草稿,人就变成不可派)", "③ 🔑 改了草稿还没发布 → 仍按已发布的早班算(在班)"),
    ("有撞单也不等确认,直接发布", "④ 有撞单、没确认 → 不写,回清单"),
    ("一批里有错的条目照样写进对的那些(写一半)", "① 混进一个别店的人 → 整批不写"),
    ("派单建议不过排班这一层(休息的人照样被推荐)", "⑦ 那天休息的那位被排除、不会被推荐"),
    ("排班没发布的周照样推荐(按「人人有空」推)", "⑦ 那周一格没排 → 不推荐(不当成「人人有空」)"),
]
坏 = []
验了 = [0]


def ck(名, 真, 补=""):
    验了[0] += 1
    print(f"  {'✅' if 真 else '❌'} {名}" + ("" if 真 else f"   ← {str(补)[:200]}"))
    if not 真:
        坏.append(名)


def main():
    print("店长排班写入口(库副本上真写)\n" + "=" * 84)
    # ⑦ 登记对得上
    名们 = {t[0] for t in tasktypes.TYPES}
    ck("「要人在场的类型」每一个都在 tasktypes 里登记了", set(K.要人在场的类型) <= 名们,
       set(K.要人在场的类型) - 名们)
    ck("「待改派」任务类型登记了", "待改派" in 名们)

    真库 = os.path.join(HERE, "lanxiu.db")
    with closing(sqlite3.connect(真库)) as c0, c0:
        真前 = (c0.execute("SELECT COUNT(*) FROM roster").fetchone()[0],
               c0.execute("SELECT COUNT(*) FROM schedule").fetchone()[0],
               c0.execute("SELECT COUNT(*) FROM op_log WHERE code='ROSTER_PUBLISH'").fetchone()[0])
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "r.db")
        src, dst = sqlite3.connect(真库), sqlite3.connect(db)
        src.backup(dst); src.close(); dst.close()
        _跑(db)      # 写口的日志带 db 参数写副本(oplog.log_op 的 db=);真库没动由 ⑥ 验
    with closing(sqlite3.connect(真库)) as c0, c0:
        真后 = (c0.execute("SELECT COUNT(*) FROM roster").fetchone()[0],
               c0.execute("SELECT COUNT(*) FROM schedule").fetchone()[0],
               c0.execute("SELECT COUNT(*) FROM op_log WHERE code='ROSTER_PUBLISH'").fetchone()[0])
    ck("⑥ 真库一行没动(排班 / 日程 / 排班发布日志行数前后一样)", 真前 == 真后, (真前, 真后))

    print("=" * 84)
    if 坏:
        print(f"{R_}❌ 排班写入口 {len(坏)} 条不过(验了 {验了[0]} 条){D}")
        return 1
    print(f"{G}✅ 排班写入口 {验了[0]} 条全过{D}")
    return 0


def _跑(db):
    店长, 顾问, 别店 = "60000001", "60000002", "60000005"     # 张静静(SH001)/ 林岚(SH001)/ 沈砚(SH002)
    今天 = "2026-11-11"
    周 = ["2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04", "2026-12-05", "2026-12-06"]
    with closing(sqlite3.connect(db)) as c, c:
        c.execute("DELETE FROM roster WHERE d >= '2026-11-30'")      # 副本上清场,别被以后铺的数据干扰
        人们 = [r[0] for r in c.execute(
            "SELECT no FROM staff WHERE role='顾问' AND status='启用' AND shop LIKE 'SH001%' ORDER BY no")]
    ck("夹具:SH001 有在职顾问可排", len(人们) >= 3, 人们)

    # ① 权限 + 整批不写
    r = RW.写草稿(顾问, [dict(工号=顾问, 日期=周[0], 班次="S1")], 今天, db)
    ck("① 顾问写排班 → 拒", not r.get("ok") and "店长" in str(r.get("error")), r)
    一周 = [dict(工号=no, 日期=d, 班次=("S0" if i == j % 7 else "S1"))
           for j, no in enumerate(人们) for i, d in enumerate(周)]
    r = RW.写草稿(店长, 一周 + [dict(工号=别店, 日期=周[0], 班次="S1")], 今天, db)
    ck("① 混进一个别店的人 → 整批不写", not r.get("ok") and r.get("不对的"), r)
    ck("①   而且确实一行没写", RW.周表(店长, 周[0], db)["没发布的改动"] == 0)
    r = RW.写草稿(店长, [dict(工号=顾问, 日期="2026-11-10", 班次="S1")], 今天, db)
    ck("① 过去的日子不改", not r.get("ok"), r)
    r = RW.写草稿(店长, [dict(name="不存在的人", date=周[0], shift="S1")], 今天, db)
    ck("① 英文字段名也认(认得出字段,才轮得到判人对不对)", not r.get("ok") and "不存在的人" in str(r.get("不对的")), r)

    # ② 草稿不生效
    r = RW.写草稿(店长, 一周, 今天, db)
    ck("② 一周草稿写进去了", r.get("ok") and r.get("写了") == 7 * len(人们), r)
    ck("② 草稿期间派单看到的是 DRAFT(不能派)", roster.在班吗(人们[1], 周[2], db)[1] == "DRAFT",
       roster.在班吗(人们[1], 周[2], db))
    预 = RW.发布预览(店长, 周[0], db)
    ck("② 每人一周排了一天休息 → 能发布、没违规", 预.get("能发布") and not 预.get("违规"), 预.get("违规"))
    r = RW.发布(店长, 周[0], 今天, db=db)
    ck("② 发布了", r.get("ok") and r.get("发布了") == 7 * len(人们), r)
    林 = 人们[0]
    ck("② 发布后在班", roster.在班吗(林, 周[2], db)[1] == "ON", roster.在班吗(林, 周[2], db))

    # ③ 改已发布的班:发布前生效的仍是已发布那行
    RW.写草稿(店长, [dict(工号=林, 日期=周[2], 班次="S2")], 今天, db)
    ck("③ 🔑 改了草稿还没发布 → 仍按已发布的早班算(在班)", roster.在班吗(林, 周[2], db)[1] == "ON",
       roster.在班吗(林, 周[2], db))
    ck("③   早班时段照样可派", roster.时段在班(林, f"{周[2]} 11:00", f"{周[2]} 12:00", db)[0])

    # ④ 改班撞单
    with closing(sqlite3.connect(db)) as c, c:
        c.execute("INSERT INTO schedule(id,type,advisor_no,start_ts,end_ts,status,shop,assignee_no,note) "
                  "VALUES('SCRWX1','预约到店',?,?,?,'有效','SH001 静安旗舰店',?,'试衣')",
                  (林, f"{周[2]} 11:00", f"{周[2]} 12:00", 林))
        c.execute("INSERT INTO schedule(id,type,advisor_no,start_ts,end_ts,status,shop,assignee_no,note) "
                  "VALUES('SCRWX2','电话回电',?,?,?,'有效','SH001 静安旗舰店',?,'回电')",
                  (林, f"{周[2]} 09:00", f"{周[2]} 18:00", 林))
    r = RW.发布(店长, 周[0], 今天, db=db)
    ck("④ 有撞单、没确认 → 不写,回清单", not r.get("ok") and r.get("需要确认"), r)
    号们 = [x["任务号"] for x in r.get("受影响") or []]
    ck("④   清单里是那张预约到店(早班改晚班,11 点那单做不了)", 号们 == ["SCRWX1"], 号们)
    ck("④   回电是当天待办,不算撞", "SCRWX2" not in 号们)
    ck("④   没确认时真的没发布(仍是早班)", roster.在班吗(林, 周[2], db)[2].find("早班") >= 0,
       roster.在班吗(林, 周[2], db))
    r = RW.发布(店长, 周[0], 今天, 确认受影响=True, db=db)
    ck("④ 确认后照发", r.get("ok") and r.get("发布了") == 1, r)
    派 = r.get("待改派任务") or []
    ck("④   给店长建了一条待改派", len(派) == 1 and 派[0]["为了"] == "SCRWX1", 派)
    with closing(sqlite3.connect(db)) as c, c:
        t = c.execute("SELECT type, assignee_no, note FROM schedule WHERE id=?", ((派 or [{}])[0].get("任务号"),)).fetchone()
        日志 = c.execute("SELECT COUNT(*) FROM op_log WHERE code='ROSTER_PUBLISH'").fetchone()[0] \
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='op_log'").fetchone() else None
    ck("④   待改派派给店长、说明里有原单号", bool(t) and t[0] == "待改派" and t[1] == 店长 and "SCRWX1" in t[2], t)
    ck("④ 发布后是晚班", "晚班" in roster.在班吗(林, 周[2], db)[2], roster.在班吗(林, 周[2], db))
    ck("④ 操作日志记在副本上(两次发布)", 日志 == 2, 日志)

    # ⑤ 合规拦发布
    下 = ["2026-12-07", "2026-12-08", "2026-12-09", "2026-12-10", "2026-12-11", "2026-12-12", "2026-12-13"]
    r = RW.写草稿(店长, [dict(工号=人们[1], 日期=d, 班次="S1") for d in 下], 今天, db)
    预 = RW.发布预览(店长, 下[0], db)
    ck("⑤ 一周七天全上班 → 违规(每周至少休一天)", any("休" in v for v in 预.get("违规", [])), 预.get("违规"))
    ck("⑤   发布被拒", not RW.发布(店长, 下[0], 今天, db=db).get("ok"))
    # 跨周连上:上周休在周一(11-30 是 人们[0]),周二起上 6 天;这周周日才休 → 12-01 到 12-12 连上 12 天
    r = RW.写草稿(店长, [dict(工号=林, 日期=d, 班次=("S0" if i == 6 else "S1")) for i, d in enumerate(下)], 今天, db)
    预 = RW.发布预览(店长, 下[0], db)
    with closing(sqlite3.connect(db)) as c, c:
        林名 = c.execute("SELECT name FROM staff WHERE no=?", (林,)).fetchone()[0]
    连 = [v for v in 预.get("违规", []) if v.startswith(林名) and "连上" in v]
    ck("⑤ 跨周连上超过 6 天 → 违规(每周休一天那条是满足的)", bool(连), 预.get("违规"))

    # ⑦ 派单接排班(用户 11-11 夜:派单要查在不在班;没发布的周不出推荐)—— 真调 booking.suggest_why
    import booking
    旧 = booking.DB
    booking.DB = db
    try:
        店 = "SH001 静安旗舰店"
        休的 = 人们[3 % len(人们)] if len(人们) > 3 else None      # 一周里 j%7==3 的那位 12-03 休息
        sg, 为什么 = booking.suggest_why(dict(shop=店, customer_id=None,
                                             start_ts="2026-12-03 11:00", end_ts="2026-12-03 12:00"))
        ck("⑦ 已发布那周、早班时段 → 提得出人选", bool(sg), 为什么)
        ck("⑦ 那天休息的那位被排除、不会被推荐", bool(sg) and 休的 and sg["no"] != 休的 and 休的 in sg.get("不在班", {}),
           (sg or {}).get("不在班"))
        sg, 为什么 = booking.suggest_why(dict(shop=店, customer_id=None,
                                             start_ts="2026-12-03 17:00", end_ts="2026-12-03 18:00"))
        ck("⑦ 那个时段全员早班已下班 → 不推荐,原因说「没有在班」", sg is None and "没有在班" in (为什么 or ""), (sg, 为什么))
        sg, 为什么 = booking.suggest_why(dict(shop=店, customer_id=None,
                                             start_ts="2026-12-09 11:00", end_ts="2026-12-09 12:00"))
        ck("⑦ 那周只有草稿(发布被拒)→ 不推荐,原因说「还没发布」", sg is None and "还没发布" in (为什么 or ""), (sg, 为什么))
        sg, 为什么 = booking.suggest_why(dict(shop=店, customer_id=None,
                                             start_ts="2026-12-16 11:00", end_ts="2026-12-16 12:00"))
        ck("⑦ 那周一格没排 → 不推荐(不当成「人人有空」)", sg is None and "还没发布" in (为什么 or ""), (sg, 为什么))
        ck("⑦ suggest() 和 suggest_why() 是同一个结果", booking.suggest(dict(shop=店, start_ts="2026-12-16 11:00")) is None)
    finally:
        booking.DB = 旧


if __name__ == "__main__":
    sys.exit(main())
