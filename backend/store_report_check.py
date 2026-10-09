#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门店经营报告取数包(store_report)—— 日报 / 周报 / 月报共用(用户 2026-10-09)。

验三件事:
  ① 报告期切得对(日 = 昨天、周 = 上一个完整周一到周日、月 = 上个自然月)—— 期望值在这里**手算**
  ② 期内的几个关键数和**独立 SQL** 对得上(下单数、营收)—— 不调被测函数算期望值(同源谬误)
  ③ 结构:期内 / 存量分两栏、每项都有出处、日报不报成交率、周报成交率是 4 周滚动、只给店长 / 总部
只读真库。
"""
import datetime as dt, os, re, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]
import api
from seed import TODAY

咬合 = [
    ("月报默认取了本月而不是上个完整月", "月报默认 = 上个自然月"),
    ("存量混进期内(两栏不分)", "期内和存量分两栏,存量不出现在期内"),
    ("进入休眠不按门店筛(门店报告报了全公司的数)", "进入休眠只算本店"),
    ("周报环比的上一期错位(拿了上上周)", "周报环比:上期下单数和独立 SQL 对得上"),
    ("本期没过完也照样比", "本期还没过完 → 不比(避免假的下跌)"),
    ("没有预约的那一天把到店算成「取不到」(10-09 CI 红法)", "没有预约的那一天:进店客流记 0,不算取不到"),
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
店 = c.execute("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
店长 = dict(no="SM-CHECK", name="店长", role="店长", shop=店)
print(f"门店经营报告取数包 · 报告期 / 对独立 SQL / 结构(门店 {店})")

# ① 报告期 —— 手算
昨 = 今 - dt.timedelta(days=1)
周一 = 今 - dt.timedelta(days=今.weekday() + 7)
上月末 = 今.replace(day=1) - dt.timedelta(days=1)
期望 = {"日": (昨, 昨), "周": (周一, 周一 + dt.timedelta(days=6)), "月": (上月末.replace(day=1), 上月末)}
包 = {}
with api.as_user(店长):
    for k in ("日", "周", "月"):
        包[k] = api.store_report(kind=k)
        a, b = 期望[k]
        ck(f"{k}报默认 = " + {"日": "昨天", "周": "上一个完整周", "月": "上个自然月"}[k],
           包[k].get("区间", "").startswith(f"{a} ~ {b}"), f"{包[k].get('区间')} / 应为 {a} ~ {b}")
ck("月报默认 = 上个自然月", 包["月"].get("区间", "").startswith(f"{期望['月'][0]} ~ {期望['月'][1]}"))

# ② 期内关键数对独立 SQL
for k in ("日", "周", "月"):
    a, b = (x.isoformat() for x in 期望[k])
    下单 = c.execute("SELECT COUNT(*) FROM ordr WHERE shop=? AND created >= ? AND created <= ?",
                    (店, a, b + " 23:59:59")).fetchone()[0]
    收 = c.execute("SELECT COALESCE(SUM(received),0) FROM ordr WHERE shop=? AND paid_at >= ? AND paid_at <= ?",
                  (店, a, b + " 23:59:59")).fetchone()[0]
    退 = c.execute("SELECT COALESCE(SUM(a.amount),0) FROM aftersale a JOIN ordr o ON o.id=a.order_id "
                  "WHERE o.shop=? AND a.kind IN ('退货退款','仅退款') AND a.status='已完成' "
                  "AND a.updated >= ? AND a.updated <= ?", (店, a, b + " 23:59:59")).fetchone()[0]
    期内 = 包[k].get("期内") or {}
    ck(f"{k}报:下单数和独立 SQL 对得上", (期内.get("订单") or {}).get("值", {}).get("下单") == 下单,
       f"工具 {(期内.get('订单') or {}).get('值')} / SQL {下单}")
    ck(f"{k}报:营收 = 实收 − 退款,和独立 SQL 对得上",
       (期内.get("营收") or {}).get("值", {}).get("营收") == round(收 - 退, 2),
       f"工具 {(期内.get('营收') or {}).get('值')} / SQL {round(收 - 退, 2)}")
ck("周报有下单样本(空集合上什么都成立)", ((包["周"].get("期内") or {}).get("订单") or {}).get("值", {}).get("下单", 0) > 0)

# 进入休眠只算本店:独立 SQL
a, b = (x.isoformat() for x in 期望["周"])
期休 = c.execute("SELECT COUNT(*) FROM customer WHERE shop=? AND last_interact IS NOT NULL "
                "AND date(last_interact,'+91 day') BETWEEN ? AND ?", (店, a, min(b, TODAY))).fetchone()[0]
ck("进入休眠只算本店", ((包["周"].get("期内") or {}).get("进入休眠") or {}).get("值", {}).get("休眠") == 期休,
   f"工具 {((包['周'].get('期内') or {}).get('进入休眠') or {}).get('值')} / SQL {期休}")

# ③ 结构
存键 = set((包["周"].get("存量(截至今天)") or {}).keys())
ck("期内和存量分两栏,存量不出现在期内", 存键 and not (存键 & set((包["周"].get("期内") or {}).keys())), str(存键))
ck("每一项都写了出处", all("出处" in v for k in ("日", "周", "月")
                       for 栏 in ("期内", "存量(截至今天)") for v in (包[k].get(栏) or {}).values()))
ck("日报不报成交率(值为空且写明为什么)", ((包["日"]["期内"].get("成交率") or {}).get("值") is None
                                  and "样本" in str(包["日"]["期内"]["成交率"].get("口径"))))
ck("周报成交率是最近 4 周滚动", "4 周滚动" in str(包["周"]["期内"]["成交率"].get("口径")))
ck("进店客流是实际预约到店", "预约到店" in str(包["周"]["期内"]["进店客流"].get("口径")))
ck("三种报告都没有取不到的项", all(not 包[k].get("取不到的") for k in 包), str({k: 包[k].get("取不到的") for k in 包}))
with api.as_user(dict(no="60000014", name="程萦", role="顾问", shop=店)):
    ck("顾问拿不到门店报告", bool(api.store_report().get("error")))
with api.as_user(店长):
    ck("kind 写错 → 报错", bool(api.store_report(kind="季").get("error")))
    ck("还没到的那一期 → 明说", "还没到" in str(api.store_report(kind="周", date=(今 + dt.timedelta(days=14)).isoformat()).get("error")))

# ④ 环比(用户 10-09:周报、月报比销量和订单量,日报不比)—— 上一期的下单数对独立 SQL
for k, 上 in (("周", (期望["周"][0] - dt.timedelta(days=7), 期望["周"][1] - dt.timedelta(days=7))),
              ("月", ((期望["月"][0] - dt.timedelta(days=1)).replace(day=1), 期望["月"][0] - dt.timedelta(days=1)))):
    上单 = c.execute("SELECT COUNT(*) FROM ordr WHERE shop=? AND created >= ? AND created <= ?",
                    (店, 上[0].isoformat(), 上[1].isoformat() + " 23:59:59")).fetchone()[0]
    环 = 包[k].get("环比") or {}
    ck(f"{k}报环比:上一期是 {上[0]} ~ {上[1]}", 环.get("上一期") == f"{上[0]} ~ {上[1]}", str(环.get("上一期")))
    # 名字写成字面量 —— 咬合规格按字面在脚本里找「预期红」那一条,f-string 拼出来的找不到(bite_check 10-09 抓到)
    ck({"周": "周报环比:上期下单数和独立 SQL 对得上", "月": "月报环比:上期下单数和独立 SQL 对得上"}[k],
       (环.get("订单量(下单数)") or {}).get("上期") == 上单,
       f"工具 {(环.get('订单量(下单数)') or {}).get('上期')} / SQL {上单}")
    本, 上值 = (环.get("订单量(下单数)") or {}).get("本期"), (环.get("订单量(下单数)") or {}).get("上期")
    if 本 is not None and 上值:
        ck(f"{k}报环比:比例是程序算好的 (本 − 上) ÷ 上",
           (环["订单量(下单数)"].get("环比") or "") == f"{(本 - 上值) / 上值 * 100:+.1f}%", str(环["订单量(下单数)"]))
    ck(f"{k}报环比里有销量(卖掉的件数)", "销量(卖掉的件数)" in 环)
ck("日报不做环比", "环比" not in 包["日"])
with api.as_user(店长):
    本月 = api.store_report(kind="月", date=TODAY)
ck("本期还没过完 → 不比(避免假的下跌)", "没过完" in str((本月.get("环比") or {}).get("说明")), str(本月.get("环比"))[:80])

# ⑤ 必选 / 可选(用户 10-09:下单数和营收必选,其余可选、默认全选)
ck("必选指标是下单数(订单)和营收", 包["周"].get("必选指标") == ["订单", "营收"], str(包["周"].get("必选指标")))
ck("每一项都标了必选 / 可选,且可选的默认都在(默认全选)",
   all("必选" in v for v in 包["周"]["期内"].values())
   and {"销量", "进店客流", "评价", "进入休眠", "任务", "成交率"} <= set(包["周"]["期内"]))
ck("必选都取到了 → 能确认", 包["周"].get("能不能确认") is True and 包["周"].get("必选缺了的") == [])
ck("写明时区(中国时间)", "中国时间" in str(包["周"].get("时区")))

# ⑥ 一条预约都没有的那一天:到店记 0,不算「取不到」(10-09 CI 从零建库撞到的)—— 找一天真的没预约
# 本地库近一年天天有预约,所以往数据开始之前找;先**确认那天店里真的没有预约**,再拿它测
最早 = c.execute("SELECT MIN(substr(start_ts,1,10)) FROM appointment").fetchone()[0] or TODAY
候选 = (dt.date.fromisoformat(最早) - dt.timedelta(days=3)).isoformat()
空日 = (候选,) if c.execute("SELECT COUNT(*) FROM appointment WHERE shop=? AND substr(start_ts,1,10)=?",
                           (店, 候选)).fetchone()[0] == 0 else None
with api.as_user(店长):
    if 空日:
        空 = api.store_report(kind="日", date=空日[0])
        ck("没有预约的那一天:进店客流记 0,不算取不到",
           (空.get("期内") or {}).get("进店客流", {}).get("值") == 0 and not any("进店客流" in x for x in 空.get("取不到的") or []),
           f"{空日[0]}: {(空.get('期内') or {}).get('进店客流', {}).get('值')} / {空.get('取不到的')}")
    else:
        ck("没有预约的那一天:进店客流记 0,不算取不到", False, "近 400 天天天都有预约 —— 找不到样本,这条没验到")

sc = next(t for t in api.SHOP_SCHEMAS if t["name"] == "store_report")
ck("工具参数名都是 ASCII", all(re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", k) for k in sc["input_schema"]["properties"]))
import prompts
ck("挂了工具就有管它的规矩(TL67)", any("store_report" in r_.needs for r_ in prompts.ALL_RULES))

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 报告取数包对上了(验了 {n} 条){D}")
