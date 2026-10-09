#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按周营收(weekly_revenue)对账 —— 周报用,用户 2026-10-09 拍的口径:
业务周 = 周一到周日;营收 = 实收减退款,**按付款日 / 退款日归周**。

期望值**另用 SQL 独立算**:周的起止在这里**手算**(不调 knowledge/weekly.周起止),
退款条件手抄成 SQL(不读 weekly.退款类)—— 用被测那一套算期望值,它错了期望值跟着错
(CLAUDE.md 第 7 节第 2 条)。只读真库。
"""
import datetime as dt, os, re, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]
import api
from seed import TODAY

咬合 = [
    ("实收按下单日归周(而不是付款日)", "上周实收和独立 SQL 对得上"),
    ("退款没减(营收 = 实收)", "营收 = 实收 − 退款,且和独立 SQL 对得上"),
    ("店长不再限本店", "店长只看本店:实收 = 本店独立 SQL"),
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
# 上一个完整的周一到周日 —— 手算
上周一 = 今 - dt.timedelta(days=今.weekday() + 7)
上周日 = 上周一 + dt.timedelta(days=6)
起, 止 = 上周一.isoformat(), 上周日.isoformat() + " 23:59:59"


def sql收(extra="", a=()):
    return round(c.execute("SELECT COALESCE(SUM(received),0) FROM ordr o WHERE paid_at >= ? AND paid_at <= ?" + extra,
                           (起, 止, *a)).fetchone()[0], 2)


def sql退(extra="", a=()):
    return round(c.execute("SELECT COALESCE(SUM(a.amount),0) FROM aftersale a JOIN ordr o ON o.id=a.order_id "
                           "WHERE a.kind IN ('退货退款','仅退款') AND a.status='已完成' "
                           "AND a.updated >= ? AND a.updated <= ?" + extra, (起, 止, *a)).fetchone()[0], 2)


print(f"按周营收 · 对独立 SQL(上周 = {上周一} ~ {上周日})")
总部 = dict(no="HQ0001", name="总部", role="总部运营", shop=None)
with api.as_user(总部):
    r = api.weekly_revenue()
    r2 = api.weekly_revenue(week=上周日.isoformat())
    本周 = api.weekly_revenue(week=TODAY)
    未来 = api.weekly_revenue(week=(今 + dt.timedelta(days=14)).isoformat())
    错 = api.weekly_revenue(week="上周")
期收, 期退 = sql收(), sql退()
ck("上周有收款样本(空集合上什么都成立)", 期收 > 0, "上周一笔收款都没有 —— 是没验到,不是对了")
ck("业务周是上一个完整的周一到周日", r.get("业务周", "").startswith(f"{上周一} ~ {上周日}"), r.get("业务周"))
ck("上周实收和独立 SQL 对得上", r.get("实收") == 期收, f"工具 {r.get('实收')} / SQL {期收}")
ck("上周退款和独立 SQL 对得上", r.get("退款") == 期退, f"工具 {r.get('退款')} / SQL {期退}")
ck("营收 = 实收 − 退款,且和独立 SQL 对得上", r.get("营收") == round(期收 - 期退, 2),
   f"工具 {r.get('营收')} / SQL {round(期收 - 期退, 2)}")
ck("给那周的周日,和不给是同一周(周日属于本周)", r2.get("营收") == r.get("营收"), f"{r2.get('业务周')}")
ck("本周还没过完要明说", "⚠️ 这一周还没过完" in 本周)
ck("还没到的周 → 明说,不给 0", "还没到" in (未来.get("error") or ""))
ck("week 写成「上周」→ 要日期,不替人解析", "YYYY-MM-DD" in (错.get("error") or ""))
ck("返回里写明退款日是近似", "近似" in "".join(r.keys()) + str(r.get("⚠️ 近似")))

店 = c.execute("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
with api.as_user(dict(no="SM-CHECK", name="店长", role="店长", shop=店)):
    rs = api.weekly_revenue()
ck("店长只看本店:实收 = 本店独立 SQL", rs.get("实收") == sql收(" AND o.shop=?", (店,)),
   f"工具 {rs.get('实收')} / SQL {sql收(' AND o.shop=?', (店,))}")
ck("店长看到的比总部少(范围真的收窄了)", (rs.get("实收") or 0) < (r.get("实收") or 0))
ck("没登录 → 不给数", bool(api.weekly_revenue().get("error")))

sc = next(t for t in api.SHOP_SCHEMAS if t["name"] == "weekly_revenue")
ck("工具参数名都是 ASCII", all(re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", k) for k in sc["input_schema"]["properties"]))
import prompts
ck("挂了工具就有管它的规矩(TL66)", any("weekly_revenue" in r_.needs for r_ in prompts.ALL_RULES))

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 按周营收和独立 SQL 对上了(验了 {n} 条){D}")
