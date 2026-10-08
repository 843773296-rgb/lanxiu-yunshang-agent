#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按月查的两件事(业务 2026-10-08,用户在页面上撞到「查不了」):

① 「九月 / 本月进入休眠的客户有多少」—— get_member(lifecycle, entered_month)
② 「九月有哪些订单已完成」—— orders_by_date(month / start+end)

期望值**另用一句 SQL 独立算**(julianday 现算闲置天数 / 直接数订单日期列),不调被测的口径函数 ——
用被测系统算期望值,实现错了期望值跟着错(CLAUDE.md 第 7 节第 2 条,同源谬误)。
顺带钉住同一天挖出来的那个洞:get_member 按档位列人时 **hit 原来被 LIMIT 40 截住**,
模型照着报「休眠 40 个」而实际 1395 —— 「截断了」和「一共就这么多」在返回里长得一模一样。
"""
import os, re, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge")]
import api
from seed import TODAY

咬合 = [
    ("进入日按 90 天算(和判档的含端边界错一天)", "进入休眠人数和独立 SQL 对得上"),
    ("get_member 的 hit 退回 len(rows)(被 LIMIT 40 截住)", "按档位列人,hit 是总数不是 LIMIT"),
    ("orders_by_date 不认 month(对外参数名没接上)", "month=YYYY-MM 和独立 SQL 对得上"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0
DB = os.path.join(HERE, "lanxiu.db")


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


def sql(q, *a):
    c = sqlite3.connect(DB)
    try:
        return c.execute(q, a).fetchone()[0]
    finally:
        c.close()


print("按月查 · 进入休眠的客户 / 某月的订单")

# ① 进入休眠:进入日 = 最后互动 + 91 天,落在这个月、且不晚于业务今天
月 = "2026-09"
期望 = sql("SELECT COUNT(*) FROM customer WHERE last_interact IS NOT NULL "
          "AND date(last_interact, '+91 day') BETWEEN '2026-09-01' AND min('2026-09-30', ?)", TODAY)
r = api.get_member(lifecycle="休眠", entered_month=月)
ck("进入休眠人数和独立 SQL 对得上", r.get("人数") == 期望, f"工具 {r.get('人数')} / SQL {期望}")
ck("进入休眠:样本不为空(空集合上什么都成立)", (期望 or 0) > 0, "九月一个进入休眠的都没有 —— 是没验到,不是对了")
ck("每一行的进入日都落在这个月", all("2026-09-01" <= x["进入日"] <= "2026-09-30" for x in r.get("rows") or []),
   str([x["进入日"] for x in (r.get("rows") or [])][:3]))
ck("返回里说清是推算、回来过的人不在里面", "推算" in (r.get("note") or "") and "回去" in (r.get("note") or ""),
   (r.get("note") or "")[:60])
本月 = TODAY[:7]
r2 = api.get_member(lifecycle="休眠", entered_month=本月)
ck("本月只算到业务今天", TODAY in (r2.get("算到哪天") or ""), str(r2.get("算到哪天")))
ck("还没到的月份 → 明说没到,不给 0", "还没到" in (api.get_member(lifecycle="休眠", entered_month="2099-01").get("error") or ""))
ck("推不出进入日的档(高价值)→ 明说查不了", "推不出" in (api.get_member(lifecycle="高价值", entered_month=月).get("error") or ""))
ck("月份写成自然语言(九月)→ 不替他解析", "YYYY-MM" in (api.get_member(lifecycle="休眠", entered_month="九月").get("error") or ""))

# 顺带:按档位列人,hit 是总数不是 LIMIT
总 = sql("SELECT COUNT(*) FROM customer WHERE lifecycle='休眠'")
r3 = api.get_member(lifecycle="休眠")
ck("按档位列人,hit 是总数不是 LIMIT", r3.get("hit") == 总 and (总 <= 40 or r3.get("截断")),
   f"hit {r3.get('hit')} / 库里 {总}")

# ② 订单按月:month 和 start+end 两条路,对独立 SQL
店长 = dict(no="60000001", name="张静静", role="店长", shop="SH001 静安旗舰店")
期望单 = sql("SELECT COUNT(*) FROM ordr WHERE shop='SH001 静安旗舰店' AND produced_at IS NOT NULL "
            "AND produced_at >= '2026-09-01' AND produced_at <= '2026-09-30 23:59:59'")
with api.as_user(店长):
    a = api.orders_by_date(field="完工", month="2026-09", limit=1)
    b = api.orders_by_date(field="完工", start="2026-09-01", end="2026-09-30", limit=1)
ck("month=YYYY-MM 和独立 SQL 对得上", a.get("总数") == 期望单, f"工具 {a.get('总数')} / SQL {期望单}")
ck("start+end 和 month 是同一批", b.get("总数") == a.get("总数"), f"{b.get('总数')} / {a.get('总数')}")
ck("订单按月:样本不为空", (期望单 or 0) > 0)

# 两个工具对外的参数名必须是 ASCII(API 校验,中文名进不了 schema —— 这就是按月查一直没接上的原因)
for 名 in ("get_member", "orders_by_date"):
    sc = next(t for t in api.SHOP_SCHEMAS if t["name"] == 名)
    键 = list(sc["input_schema"]["properties"])
    ck(f"{名} 的参数名都是 ASCII", all(re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", k) for k in 键), str(键))
ck("orders_by_date 的说明里写了 month / start / end",
   all(k in next(t for t in api.SHOP_SCHEMAS if t["name"] == "orders_by_date")["input_schema"]["properties"]
       for k in ("month", "start", "end")))
ck("get_member 的说明里写了 entered_month",
   "entered_month" in next(t for t in api.SHOP_SCHEMAS if t["name"] == "get_member")["input_schema"]["properties"])

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 按月查两件事都对上了(验了 {n} 条){D}")
