#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原来只能按月 / 最近 N 天的三项,补上「按业务周」之后对账(周报用,用户 2026-10-09 拍:四类都要)。

    评价概况      rating_overview(week=)
    进入某一档    get_member(lifecycle=, entered_week=)
    任务复盘      monthly_review(week=)

期望值**另用 SQL 独立算**,周的起止在这里**手算**(不调 knowledge/weekly)——
用被测那一套算期望值,它错了期望值跟着错(CLAUDE.md 第 7 节第 2 条)。只读真库。
"""
import datetime as dt, os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]
import api
from seed import TODAY

咬合 = [
    ("评价按周时只卡了起点、没卡终点(和「最近 N 天」一样往后漏)", "评价:上周条数和独立 SQL 对得上"),
    ("任务按周时还是按月筛", "任务:每一周的到期数和独立 SQL 对得上"),
    ("滚动窗口少算了一周(21 天而不是 28 天)", "成交率:窗口是截到报告周周日的最近 28 天"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
今 = dt.date.fromisoformat(TODAY)
一 = 今 - dt.timedelta(days=今.weekday() + 7)          # 上周一,手算
日 = 一 + dt.timedelta(days=6)
起, 止 = 一.isoformat(), 日.isoformat()
总部 = dict(no="HQ0001", name="总部", role="总部运营", shop=None)
print(f"按周补上的三项 · 对独立 SQL(上周 = {起} ~ {止})")

# ── 评价
with api.as_user(总部):
    r = api.rating_overview(week=起)
期 = c.execute("SELECT COUNT(*), SUM(star<=3) FROM rating WHERE star IS NOT NULL "
              "AND substr(rated_at,1,10) BETWEEN ? AND ?", (起, 止)).fetchone()
ck("评价:上周有样本", (期[0] or 0) > 0, "上周一条评价都没有 —— 是没验到")
ck("评价:上周条数和独立 SQL 对得上", r.get("条数") == 期[0], f"工具 {r.get('条数')} / SQL {期[0]}")
ck("评价:上周差评条数(≤3 星)对得上", r.get("差评几条") == 期[1], f"工具 {r.get('差评几条')} / SQL {期[1]}")
ck("评价:窗口写的是业务周,不是「最近 N 天」", "业务周" in str(r.get("窗口")), str(r.get("窗口")))

# ── 进入休眠:进入日 = 最后互动 + 91 天,落在上周、且不晚于今天
r = api.get_member(lifecycle="休眠", entered_week=起)
期 = c.execute("SELECT COUNT(*) FROM customer WHERE last_interact IS NOT NULL "
              "AND date(last_interact, '+91 day') BETWEEN ? AND ?", (起, min(止, TODAY))).fetchone()[0]
ck("进入休眠:上周有样本", 期 > 0)
ck("进入休眠:上周人数和独立 SQL 对得上", r.get("人数") == 期, f"工具 {r.get('人数')} / SQL {期}")
ck("进入休眠:给周里任意一天都是同一周", api.get_member(lifecycle="休眠", entered_week=止).get("人数") == r.get("人数"))

# ── 任务复盘:按截止日(end_ts)归周,逐周对 —— 任务少,单看一周容易恰好是 0,所以连看 6 周
对不上, 有样本 = [], 0
with api.as_user(总部):
    for k in range(6):
        w一 = 一 - dt.timedelta(days=7 * k)
        w日 = w一 + dt.timedelta(days=6)
        期 = c.execute("SELECT COUNT(*) FROM schedule WHERE substr(end_ts,1,10) BETWEEN ? AND ?",
                      (w一.isoformat(), w日.isoformat())).fetchone()[0]
        有样本 += 期 > 0
        got = (api.monthly_review(week=w一.isoformat()).get("任务") or {}).get("总数")
        if got != 期:
            对不上.append(f"{w一}: 工具 {got} / SQL {期}")
ck("任务:近 6 周里至少有一周有任务(否则验不到)", 有样本 > 0)
ck("任务:每一周的到期数和独立 SQL 对得上", not 对不上, f"共 {len(对不上)} 周对不上:" + "; ".join(对不上[:3]) + (f" ……还有 {len(对不上) - 3} 周" if len(对不上) > 3 else ""))
with api.as_user(总部):
    ck("任务:按周时返回写「区间」不写「月份」", "区间" in api.monthly_review(week=起))
    ck("任务:week 写错 → 报错", bool(api.monthly_review(week="上周").get("error")))

# ── 成交率「最近 4 周滚动」(用户 10-09 选)—— 接待来自五张表,独立 SQL 复算不现实,
# 所以这里验**性质**;算法本身的逐例真值在 knowledge/attribution.py 自测(区间 = 整月时和按月同期一模一样)
with api.as_user(总部):
    cr = api.conversion_rate(week=起)
窗 = f"{(一 - dt.timedelta(days=21)).isoformat()} ~ {止}"
ck("成交率:窗口是截到报告周周日的最近 28 天", 窗 in str(cr.get("口径")), str(cr.get("口径"))[:60])
a_, b_ = (int(x) for x in str(cr.get("门店怎么算的", "0 ÷ 0")).split(" ÷ "))
ck("成交率:分母有样本、成交 ≤ 分母", b_ > 0 and 0 <= a_ <= b_, f"{a_} ÷ {b_}")
排 = [x["归因成交份额"] for x in cr.get("顾问成交率(按归因成交排)") or []]
ck("成交率:顾问按归因成交份额从高到低排", 排 == sorted(排, reverse=True) and len(排) > 0, str(排))
ck("成交率:每个顾问的份额 ≤ 他的分母客户数(率不超过 100%)",
   all(x["归因成交份额"] <= x["分母客户"] for x in cr.get("顾问成交率(按归因成交排)") or []))
with api.as_user(dict(no="SM-CHECK", name="店长", role="店长",
                      shop=c.execute("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop "
                                     "ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0])):
    cs = api.conversion_rate(week=起)
ck("成交率:店长的分母比总部小(范围真的收窄了)",
   int(str(cs.get("门店怎么算的", "0 ÷ 0")).split(" ÷ ")[1]) < b_, f"{cs.get('门店怎么算的')} / {cr.get('门店怎么算的')}")
ck("成交率:写明已知偏低", "已知偏低" in "".join(cr.keys()))

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 按周补上的三项都和独立 SQL 对上了(验了 {n} 条){D}")
