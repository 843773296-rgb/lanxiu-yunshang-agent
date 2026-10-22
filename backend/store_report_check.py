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
    ("到店客户数没去重(直接拿人次)", "到店客户数 = 这一期按客户去重(独立 SQL),而且不超过人次"),
    # ⚠️ 预期红是**那个挑来分辨口径的月**那一条 —— 按到店人次挑的那个窗口
    #    恰好两个口径同数(2026-10-17 实测),在它上面这个错一点痕迹都没有。
    ("售后结案按建单日算", "再对一次账"),
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

# ⚠️ **「口径对」不等于「数有量」。** 上面那条只看口径写的是不是「预约到店」——
# 2026-10-10 库从零重建了一次,预约 17456→79、到店从 70 掉到 0,**而这一条照样绿**:
# 口径没变,变的是库里再也没有「到店」这件事发生过。
# > 一份「进店客流 = 0」的周报,和一份「取数取空了」的,
# > **在那个数字上长得一模一样** —— 都是 0。
#
# 所以这里加一道量级闸。**判据贴着结构,不贴魔数**(这个仓库自己的原则,
# 见 tools/lifecycle_history_seed.py 里「不贴那个 9999 魔数」那段):
# 配方按订单数的约 0.55 造接待触点(tools/touchpoint_history_seed.py),
# 所以「到店人次 ≥ 订单数的一成」在任何订单量上都成立 ——
# 而那一步要是又掉出配方,只剩夹具那几十条,这里当场红。
# 写成「≥ 1000」那样的死数就不行:订单量一变它就过期,而过期的下限不会报错。
_单数 = c.execute("SELECT COUNT(*) FROM ordr").fetchone()[0]
_到店次 = c.execute("SELECT COUNT(*) FROM appointment "
                  "WHERE status IN ('已到店','已完成')").fetchone()[0]
_下限 = _单数 // 10
ck(f"到店人次和订单量同量级(到店 {_到店次} ≥ 订单 {_单数} 的一成 = {_下限})",
   _到店次 >= _下限,
   f"到店只有 _到店次={_到店次} 条 —— **这不叫「这一期没人来」,叫接待触点那一步没跑**;"
   f"配方里是 tools/touchpoint_history_seed.py --做")
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

# ⑦ V1.1 补的三项(10-10):到店客户数去重、售后新建 / 结案、规则版本留底
# 挑本店到店最多的那个月(重建后的库预约稀,上周可能一条到店都没有 —— 空集合上「去重对」恒成立)
月 = c.execute("SELECT substr(start_ts,1,7) m, COUNT(*) FROM appointment WHERE shop=? AND status IN ('已到店','已完成') "
               "AND substr(start_ts,1,10) < ? GROUP BY m ORDER BY 2 DESC LIMIT 1", (店, TODAY)).fetchone()
with api.as_user(店长):
    包月 = api.store_report(kind="月", date=(月[0] + "-01") if 月 else TODAY)
起, 止 = 包月["区间"][:10], 包月["区间"][13:23]
期望客 = len({r[0] for r in c.execute("SELECT customer_id FROM appointment WHERE shop=? AND status IN ('已到店','已完成') "
                                      "AND customer_id IS NOT NULL AND substr(start_ts,1,10) BETWEEN ? AND ?", (店, 起, 止))})
期望次 = c.execute("SELECT COUNT(*) FROM appointment WHERE shop=? AND status IN ('已到店','已完成') "
                   "AND substr(start_ts,1,10) BETWEEN ? AND ?", (店, 起, 止)).fetchone()[0]
客 = 包月["期内"]["到店客户数"]["值"]
ck("到店客户数 = 这一期按客户去重(独立 SQL),而且不超过人次", 期望客 > 0 and 客 == 期望客 and 客 <= 包月["期内"]["进店客流"]["值"],
   f"{起}~{止}:工具 {客} / SQL {期望客} / 人次 {包月['期内']['进店客流']['值']}(SQL 人次 {期望次})")
新, 结 = 0, 0
for kind_, st, cre, upd, ash, osh in c.execute("SELECT a.kind, a.status, a.created, a.updated, a.shop, o.shop FROM aftersale a "
                                                 "LEFT JOIN ordr o ON o.id=a.order_id"):
    if (ash or osh) != 店:
        continue
    新 += 起 <= (cre or "")[:10] <= 止
    结 += st in ("已完成", "已关闭", "已拒绝") and 起 <= (upd or "")[:10] <= 止
售 = 包月["期内"]["售后"]["值"]
ck("售后新建 / 结案各按自己的事件时间,和独立统计对得上", (售["新建"], 售["结案"]) == (新, 结) and 新 + 结 > 0,
   f"工具 {售['新建']}/{售['结案']} / 独立 {新}/{结}")

# ── 再挑一个**专门能分辨两个口径**的月复验 ──────────────────────────────
#
# ⚠️ **挑窗口要按「能不能分辨」挑,不是按「数据多不多」挑。**
# 上面那个月是按到店人次挑的(样本多、不容易空),而 2026-10-17 全量咬合重放逮到:
# 它恰好是两个口径算出**同一个数**的月份(按 updated 结案 16 · 按 created 也 16 ——
# 两个集合其实不同,大小碰巧相等),于是「售后结案按建单日算」这个错
# 在这个窗口上**一点痕迹都没有**,那条咬合「改坏了却没红」。
# 实测全库十二个月里只有 2026-08 / 2026-09 分辨不出,判据偏偏挑中了前者。
# > 一个样本很多的窗口,和一个能分辨的窗口,在「这条判据跑过了」上长得一模一样。
#
# 所以**让判据自己去找**那个能分辨的月,不靠「碰巧挑中了哪个月」。
_结案状态 = ("已完成", "已关闭", "已拒绝")
_候选 = {}
for st, cre, upd, ash, osh in c.execute(
        "SELECT a.status, a.created, a.updated, a.shop, o.shop FROM aftersale a "
        "LEFT JOIN ordr o ON o.id=a.order_id"):
    if (ash or osh) != 店 or st not in _结案状态:
        continue
    for 月_, 键_ in (((upd or "")[:7], "按结案日"), ((cre or "")[:7], "按建单日")):
        if 月_:
            _候选.setdefault(月_, {"按结案日": 0, "按建单日": 0})[键_] += 1
# 取最近的、且不是当月的(当月区间会截到今天,数还在动)
分辨月 = next((m for m in sorted(_候选, reverse=True)
               if m < TODAY[:7] and _候选[m]["按结案日"] != _候选[m]["按建单日"]), None)
ck("找得到一个能分辨两个时间口径的月(找不到的话,上面那条对账换个口径也照样过)",
   分辨月 is not None,
   f"十二个月里没有一个月的两个口径算出不同的数:{ {k: tuple(v.values()) for k, v in sorted(_候选.items())} }")
if 分辨月:
    with api.as_user(店长):
        包辨 = api.store_report(kind="月", date=分辨月 + "-01")
    起2, 止2 = 包辨["区间"][:10], 包辨["区间"][13:23]
    新2, 结2 = 0, 0
    for st, cre, upd, ash, osh in c.execute(
            "SELECT a.status, a.created, a.updated, a.shop, o.shop FROM aftersale a "
            "LEFT JOIN ordr o ON o.id=a.order_id"):
        if (ash or osh) != 店:
            continue
        新2 += 起2 <= (cre or "")[:10] <= 止2
        结2 += st in _结案状态 and 起2 <= (upd or "")[:10] <= 止2
    售2 = 包辨["期内"]["售后"]["值"]
    ck(f"换个能分辨口径的月({分辨月})再对一次账 —— 结案按**结案日**不按建单日",
       (售2["新建"], 售2["结案"]) == (新2, 结2) and 新2 + 结2 > 0,
       f"工具 {售2['新建']}/{售2['结案']} / 独立 {新2}/{结2}"
       f"(这个月两个口径:{_候选[分辨月]['按结案日']} vs {_候选[分辨月]['按建单日']})")
版 = 包月.get("规则版本") or {}
ck("规则版本留底:取数口径版本 + 写报告两条规矩的指纹", 版.get("取数口径") == api.报告口径版本
   and set((版.get("规矩指纹") or {})) == {"TL67", "TL68"} and all(len(v) == 10 for v in 版["规矩指纹"].values()), str(版))

# 规则版本冻在取数包里,而取数包登记了每日平移 —— 版本号要**挪不动**,日期要**挪得动**(10-22 加)。
# 拿平移真的挪字函数去挪这份包(不在这里照样子写一份正则);「区间真的挪了」那半句是为了
# 别让「这份包里根本没有日期」冒充「挪过了、版本没动」。
import importlib.util as _iu
_sp = _iu.spec_from_file_location("shift_world", os.path.join(ROOT, "tools", "shift_world.py"))
_sw = _iu.module_from_spec(_sp); _sp.loader.exec_module(_sw)
import json as _json
挪过 = _json.loads(_sw._挪文字(_json.dumps(包月, ensure_ascii=False), 1))
ck("每日平移挪得动取数包里的日期、挪不动规则版本(版本号别长得像日期)",
   (挪过.get("规则版本") or {}).get("取数口径") == api.报告口径版本
   and 挪过.get("区间") != 包月.get("区间"),
   f"挪前 {版.get('取数口径')} / 挪后 {(挪过.get('规则版本') or {}).get('取数口径')};"
   f"区间 {包月.get('区间')} → {挪过.get('区间')}")

# 并排读时要说清的(用户 10-12 试周报后定:做进取数包,不只写在规矩里)
周包 = 包.get("周") or {}
并 = 周包.get("并排读时要说清的") or []
ck("周报取数包带现成话:成交率是最近 4 周、和本周进店不是同一个窗口", any("最近 4 周" in x for x in 并), 并)
_单 = ((周包.get("期内", {}).get("订单") or {}).get("值") or {}).get("下单")
_销 = (((周包.get("期内", {}).get("销量") or {}).get("值") or {}).get("合计") or {}).get("单数")
ck("下单数和销量订单数对不上时,取数包带现成的解释(数对得上就不硬塞)",
   (_单 == _销) or any(f"下单 {_单} 单" in x and f"{_销} 个订单" in x for x in 并), (_单, _销, 并))
sc = next(t for t in api.SHOP_SCHEMAS if t["name"] == "store_report")
ck("工具参数名都是 ASCII", all(re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", k) for k in sc["input_schema"]["properties"]))
import prompts
ck("挂了工具就有管它的规矩(TL67)", any("store_report" in r_.needs for r_ in prompts.ALL_RULES))

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 报告取数包对上了(验了 {n} 条){D}")
