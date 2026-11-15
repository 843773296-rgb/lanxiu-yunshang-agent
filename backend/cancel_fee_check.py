#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完工前不做了扣多少(cancel_fee 工具)· 检查 —— 只读,真库上跑(工具本身只读,不写一行)。

期望值**不用被测模块算**(同源谬误):工钱用一段独立 SQL 现算 ——
非遗级按 `craft.detail` 里写着「非遗:」认(被测模块认的是 03-工艺.md 的「非遗」字段,两个来源),
天数用 SQLite 的 julianday 相减。两套对上才算对。

样本量要声明:库里「生产中、有工单」的定制单一张都没有时红 —— 空集合上什么都成立。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]
import api, worldclock

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


咬合 = [
    ("工钱和独立 SQL 现算的对不上", "折钱算法和独立 SQL 逐张一致"),
    ("别店也能看", "别店的单看不到"),
]

print("完工前不做了扣多少 · 检查(只读)")
print("=" * 80)
c = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
今天 = worldclock.今天().isoformat()
样本 = [r[0] for r in c.execute(
    "SELECT o.id FROM ordr o WHERE o.kind='定制品订单' AND o.status='生产中' "
    "AND EXISTS(SELECT 1 FROM workorder w WHERE w.ref=o.id AND w.workdays IS NOT NULL AND w.start_date IS NOT NULL) "
    "ORDER BY o.id LIMIT 30")]
ck("有生产中、带工单的定制单可验(空集合上什么都成立)", len(样本) >= 3, f"{len(样本)} 张")


def 期望工钱(oid):
    """独立 SQL:已完成 工日×价;在制 min(max(今天−开工,0), 工日)×价;非遗按 craft.detail 认。"""
    v = c.execute("""
        SELECT SUM(CASE WHEN w.status='已完成' THEN w.workdays
                        ELSE MIN(MAX(julianday(?) - julianday(substr(w.start_date,1,10)), 0), w.workdays) END
                   * CASE WHEN cr.detail LIKE '%非遗:%' THEN 800 ELSE 300 END)
        FROM workorder w LEFT JOIN craft cr ON cr.code=w.craft WHERE w.ref=?""", (今天, oid)).fetchone()[0]
    return round(v or 0, 2)


店长们 = {r[0]: dict(no=r[1], name=r[2], role="店长", shop=r[0]) for r in c.execute(
    "SELECT shop, no, name FROM staff WHERE role='店长' AND status='启用' GROUP BY shop")}
对不上, 验了, 非零 = [], 0, 0
for oid in 样本:
    店 = c.execute("SELECT shop FROM ordr WHERE id=?", (oid,)).fetchone()[0]
    me = 店长们.get(店)
    if not me:
        continue
    with api.as_user(me):
        r = api.cancel_fee(oid)
    if r.get("判不了"):
        continue
    验了 += 1
    非零 += 期望工钱(oid) > 0
    if r.get("工钱") != 期望工钱(oid):
        对不上.append((oid, r.get("工钱"), 期望工钱(oid)))
ck(f"工钱和独立 SQL 现算的一致(验了 {验了} 张)", not 对不上 and 验了 >= 3, 对不上[:3] or f"只验了 {验了} 张")
# 真库上「生产中」的单有几张已经开工,取决于每日平移把开工日挪到了哪 —— **那是数据分布,不是代码**
# (11-16 早上 30 张在制单的开工日全在今天之后,工钱全 0,这条红了而代码一行没动)。
# 所以真库上的非零张数**只打印不判红**;「算出了钱而且算对了」由下面库副本上自造的那张单来判。
print(f"     ℹ️ 真库上这 {验了} 张里工钱不为 0 的 {非零} 张(只打印,不是判据 —— 取决于平移后开工日落在哪)")

import cancel_fee as CF  # noqa: E402  —— 切库前先 import,之后才 import 的模块不会被改到
import check_copy  # noqa: E402
副本 = check_copy.用副本("cancel-fee-")
ck("工具层已指向库副本(下面要改开工日)", os.path.realpath(api.DB) != os.path.realpath(check_copy.真库), api.DB)
造 = 样本[-1] if 样本 else None
if 造:
    w = sqlite3.connect(api.DB)
    check_copy.确认连的是(w, api.DB, "cancel_fee_check 自造在制单")
    开工 = (worldclock.今天() - __import__("datetime").timedelta(days=3)).isoformat()
    w.execute("UPDATE workorder SET start_date=? WHERE ref=? AND status!='已完成'", (开工, 造))
    w.commit()
    v = w.execute("""
        SELECT SUM(CASE WHEN w.status='已完成' THEN w.workdays
                        ELSE MIN(MAX(julianday(?) - julianday(substr(w.start_date,1,10)), 0), w.workdays) END
                   * CASE WHEN cr.detail LIKE '%非遗:%' THEN 800 ELSE 300 END)
        FROM workorder w LEFT JOIN craft cr ON cr.code=w.craft WHERE w.ref=?""", (今天, 造)).fetchone()[0]
    期望 = round(v or 0, 2)
    店_ = w.execute("SELECT shop FROM ordr WHERE id=?", (造,)).fetchone()[0]
    w.close()
    with api.as_user(店长们[店_]):
        r_ = api.cancel_fee(造)
    ck(f"自造一张三天前开工的在制单:工钱不为 0 且和独立 SQL 一致({造})", 期望 > 0 and r_.get("工钱") == 期望,
       (r_.get("工钱"), 期望))
else:
    ck("自造在制单(没有样本可改)", False)

# 算法层:直接拿**所有带工单的单**对账(生产中的单多半还没开工,工具层只有一两张算出钱;
# 已完工的单在工具层直接回「全额」,这里绕过状态闸,只验折钱那一步算得对不对)
全部 = [r[0] for r in c.execute("SELECT DISTINCT ref FROM workorder WHERE ref IS NOT NULL")]
算错, 有钱 = [], 0
for oid_ in 全部:
    x = CF.从库(c, oid_, 今天)
    if x.get("error") or x.get("判不了"):
        continue
    有钱 += 期望工钱(oid_) > 0
    if x["工钱"] != 期望工钱(oid_):
        算错.append((oid_, x["工钱"], 期望工钱(oid_)))
ck(f"折钱算法和独立 SQL 逐张一致(带工单的 {len(全部)} 张,算出钱的 {有钱} 张)", not 算错 and 有钱 >= 5,
   算错[:3] or f"算出钱的只有 {有钱} 张,样本太少")

oid = 样本[0] if 样本 else None
if oid:
    店 = c.execute("SELECT shop, received, amount FROM ordr WHERE id=?", (oid,)).fetchone()
    me = 店长们[店[0]]
    已付 = 店[1] if 店[1] is not None else 店[2]
    with api.as_user(me):
        r = api.cancel_fee(oid)
        ck("逐道列明细,每道写清怎么算", r.get("明细") and all(x.get("怎么算") for x in r["明细"]), r)
        ck("没给料费时说清「料费没算」", "料费没算" in r.get("料费说明", ""), r.get("料费说明"))
        r2 = api.cancel_fee(oid, material_cost=10 ** 9)
        ck("扣的总额不超过已付(料费给得再大也封顶)", r2.get("合计") == round(float(已付), 2) and r2.get("退") == 0, r2)
        ck("料费不是数 → 拒", "error" in api.cancel_fee(oid, material_cost="一千"))
        ck("料费负数 → 拒", "error" in api.cancel_fee(oid, material_cost=-1))
    别店 = next((v for k, v in 店长们.items() if k != 店[0]), None)
    with api.as_user(别店):
        ck("别店的单看不到", "error" in api.cancel_fee(oid))
    with api.as_user(dict(no="HQ", name="总部", role="总部运营", shop=None)):
        ck("总部看得到", "明细" in api.cancel_fee(oid))
    ck("没登录不给", "error" in api.cancel_fee(oid))

for 状态, 要 in (("待确认", "不扣钱"), ("完成", "已经完工")):
    x = c.execute("SELECT id, shop FROM ordr WHERE kind='定制品订单' AND status=? LIMIT 1", (状态,)).fetchone()
    if x and 店长们.get(x[1]):
        with api.as_user(店长们[x[1]]):
            ck(f"「{状态}」的单照实说{要},不算工钱", 要 in (api.cancel_fee(x[0]).get("结论") or ""))
标 = c.execute("SELECT id, shop FROM ordr WHERE kind!='定制品订单' LIMIT 1").fetchone()
if 标 and 店长们.get(标[1]):
    with api.as_user(店长们[标[1]]):
        ck("标品单不算(标品走退换货规则)", "error" in api.cancel_fee(标[0]))

import prompts
sys.path.insert(0, os.path.join(ROOT, "agentsite"))
src = open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
ck("工具有管它的规矩(TL72),顾问和店长都挂上了",
   any("cancel_fee" in r_.needs for r_ in prompts.ALL_RULES) and '"mcp__finance__cancel_fee"' in src)
ck("工具不在写工具清单里(只算不退)", "cancel_fee" not in api.WRITE_TOOLS)
c.close()

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 完工前不做了扣多少都对(验了 {n} 条){D}")
