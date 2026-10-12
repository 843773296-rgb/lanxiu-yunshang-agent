#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品销量排行(sales_rank)—— 2026-10-09 用户在 chat 里问「九月销量最好的商品」,模型答「查不了」。

期望值**另用一句 SQL 独立算**,不调被测函数、也不调它用的 stockalert.卖掉了() ——
「哪些算卖掉了」在这里照业务口径**手抄成 SQL 条件**:取消 / 待付款 / 待确认 / 已退款不算
(同源谬误,CLAUDE.md 第 7 节第 2 条:用被测那一套算期望值,它错了期望值跟着错)。
不碰真库(只读)。
"""
import os, re, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]
import api

咬合 = [
    ("销量不过滤状态(取消 / 退款的行也算进去)", "合计件数和独立 SQL 对得上"),
    ("店长不再限本店(_订单范围 那一层没接)", "店长只看本店:合计 = 本店独立 SQL"),
    ("排序丢了次序键(同件数时顺序不确定)", "同一个问题问两次,榜单一模一样"),
    ("「各排法的第一」从件数榜里挑金额最大的(10-09 真跑时模型的错法)", "按金额的第一和独立 SQL 是同一个商品"),
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
算 = ("o.status NOT IN ('取消','待付款','待确认') AND COALESCE(o.refund_status,'')<>'已退款'")
区 = "o.created >= '2026-09-01' AND o.created <= '2026-09-30 23:59:59'"


def sql(where_extra="", args=()):
    return c.execute(f"SELECT i.spu, SUM(i.qty) q FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                     f"WHERE {区} AND {算}{where_extra} GROUP BY i.spu ORDER BY q DESC, i.spu", args).fetchall()


print("商品销量排行 · 对独立 SQL")
总部 = dict(no="HQ0001", name="总部", role="总部运营", shop=None)
店 = c.execute("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
店长 = dict(no="SM-CHECK", name="店长", role="店长", shop=店)

期望 = sql()
with api.as_user(总部):
    r = api.sales_rank(month="2026-09", limit=5)
    r_again = api.sales_rank(month="2026-09", limit=50)
    r_again2 = api.sales_rank(month="2026-09", limit=50)
    r_ab = api.sales_rank(start="2026-09-01", end="2026-09-30", limit=5)
    r_amt = api.sales_rank(month="2026-09", metric="金额", limit=3)
    错1 = api.sales_rank(month="九月")
    错2 = api.sales_rank(start="2026-09-01")
    错3 = api.sales_rank(month="2026-09", by="颜色")
    空 = api.sales_rank(month="2001-01")
ck("九月有样本(空集合上什么都成立)", len(期望) >= 10, f"只有 {len(期望)} 个商品")
ck("合计件数和独立 SQL 对得上", r["合计"]["件数"] == sum(q for _, q in 期望),
   f"工具 {r['合计']['件数']} / SQL {sum(q for _, q in 期望)}")
ck("第一名和独立 SQL 是同一个商品、同样件数", (r["榜单"][0]["编码"], r["榜单"][0]["件数"]) == tuple(期望[0]),
   f"工具 {(r['榜单'][0]['编码'], r['榜单'][0]['件数'])} / SQL {期望[0]}")
ck("前五的件数逐个对得上", [x["件数"] for x in r["榜单"]] == [q for _, q in 期望[:5]],
   f"{[x['件数'] for x in r['榜单']]} / {[q for _, q in 期望[:5]]}")
ck("month 和 start+end 是同一批", r_ab["榜单"] == r["榜单"] and r_ab["合计"] == r["合计"])
ck("同一个问题问两次,榜单一模一样", [x["编码"] for x in r_again["榜单"]] == [x["编码"] for x in r_again2["榜单"]]
   and [x["编码"] for x in r_again["榜单"]] == sorted(
       [x["编码"] for x in r_again["榜单"]],
       key=lambda k: (-next(x for x in r_again["榜单"] if x["编码"] == k)["件数"],
                      -next(x for x in r_again["榜单"] if x["编码"] == k)["金额"],
                      -next(x for x in r_again["榜单"] if x["编码"] == k)["单数"], k)))
金额序 = [x["金额"] for x in r_amt["榜单"]]
ck("按金额排时金额单调不增", 金额序 == sorted(金额序, reverse=True), str(金额序))
期望金额 = c.execute(f"SELECT i.spu FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                     f"WHERE {区} AND {算} GROUP BY i.spu ORDER BY SUM(i.total) DESC, i.spu LIMIT 1").fetchone()[0]
ck("按金额的第一和独立 SQL 是同一个商品", (r.get("各排法的第一") or {}).get("金额", {}).get("编码") == 期望金额,
   f"工具 {(r.get('各排法的第一') or {}).get('金额')} / SQL {期望金额}")
# ⚠️ **这一条原来钉死在九月,而它靠的是一个巧合 —— 2026-10-11 那个巧合没了。**
#
# 它要的形状是「金额第一**不在**件数前五」:只有这样,才验得到
# 「按件数查的时候,工具也照样把金额第一给出来」这件事。原来写的是
# `期望金额 not in r["榜单"]`,九月不满足就直接红。
#
# 从零建库之后**库里 16 个月没有一个月满足** —— 有一个两头都第一的爆款
# (157 件 / ¥272 万)在每个月都既是金额第一、又在件数前五。
# 而它以前绿**不是因为被保证了,是因为那一次抽样恰好让某个月错开**:
# 种子里加了一行员工、随机流整体挪位,它就翻面(真因见 `backend/seed_rng_check.py`)。
# > **一条「被保证成立」的判据和一条「碰巧成立」的判据,在绿勾上长得一模一样。**
#
# 改成**去找一个真能分辨的窗口**(滑动 7 天 —— 工具本来就支持起止日,
# 而上面那条「month 和 start+end 是同一批」已经验过两种给法同源)。
# 找得到就在那个窗口上验;**一个都找不到才红**,而那时候红的是一笔**数据欠账**:
# 这个库里「各排法的第一」永远分辨不出来,这个功能等于空跑。
def 找分辨窗口():
    """返回一个「金额第一不在件数前五」的 7 天窗口,找不到返回 None。

    ⚠️ **一次查完在内存里滑窗,不要每个窗口发一轮 SQL。** 第一版就是每天两条
    `GROUP BY`(`substr(created,1,10)` 用不上索引),两年的日子扫下来 **46 秒** ——
    而门禁有二十多项,一项占掉 46 秒就会让人开始跳着跑。
    """
    import collections, datetime as _dt
    行 = c.execute(f"SELECT substr(o.created,1,10), i.spu, i.qty, i.total "
                   f"FROM ordr_item i JOIN ordr o ON o.id=i.order_id WHERE {算}").fetchall()
    if not 行:
        return None
    按天 = collections.defaultdict(list)
    for 日, spu, 件, 钱 in 行:
        按天[日].append((spu, 件 or 0, 钱 or 0))
    d, 末 = _dt.date.fromisoformat(min(按天)), _dt.date.fromisoformat(max(按天))
    while d <= 末:
        窗 = [d + _dt.timedelta(days=i) for i in range(7)]
        聚 = collections.defaultdict(lambda: [0, 0])
        for 日 in 窗:
            for spu, 件, 钱 in 按天.get(str(日), ()):
                聚[spu][0] += 件
                聚[spu][1] += 钱
        if len(聚) >= 5:     # 不够 5 个商品时「前五」装得下全部,两种排法必然重叠 —— 不算分辨得出来
            件五 = [k for k, _ in sorted(聚.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:5]]
            钱一 = sorted(聚.items(), key=lambda kv: (-kv[1][1], kv[0]))[0][0]
            if 钱一 not in 件五:
                return str(d), str(d + _dt.timedelta(days=6)), 钱一, 件五
        d += _dt.timedelta(days=1)
    return None


窗 = 找分辨窗口()
if 窗 is None:
    ck("库里有一个窗口能让两种排法指向不同商品(没有就验不到「各排法的第一」)", False,
       "16 个月、每一个 7 天窗口都找不到 —— **造数没造出『贵而卖得少』和『便宜而卖得多』错开的形状**,"
       "「各排法的第一」这个功能在这个库里永远分辨不出来(空跑)")
else:
    _起, _止, _钱一, _件五 = 窗
    with api.as_user(总部):
        r_窗 = api.sales_rank(start=_起, end=_止, limit=5)
    ck("按件数查时,金额第一不在件数前五里也照样给出"
       f"(窗口 {_起}~{_止},这个窗口是**挑来专门分辨这件事的**)",
       (r_窗.get("各排法的第一") or {}).get("金额", {}).get("编码") == _钱一
       and _钱一 not in [x["编码"] for x in r_窗["榜单"]],
       f"工具 {(r_窗.get('各排法的第一') or {}).get('金额')} / SQL 金额第一 {_钱一} / "
       f"件数前五 {_件五}")
ck("没算进销量的行要说出来(九月有取消单)", "取消" in (r.get("没算进销量的订单行") or {}))

期望店 = sql(" AND o.shop=?", (店,))
with api.as_user(店长):
    rs = api.sales_rank(month="2026-09", limit=3)
ck("店长只看本店:合计 = 本店独立 SQL", rs["合计"]["件数"] == sum(q for _, q in 期望店),
   f"工具 {rs['合计']['件数']} / SQL {sum(q for _, q in 期望店)}")
ck("店长看到的比总部少(范围真的收窄了)", rs["合计"]["件数"] < r["合计"]["件数"])

ck("「九月」不替人猜 → 要 YYYY-MM", "YYYY-MM" in (错1.get("error") or ""))
ck("只给 start 不给 end → 报错", bool(错2.get("error")))
ck("by 写错 → 报错", bool(错3.get("error")))
ck("没有销量的月份 → 说是「没有」,不是空着", 空.get("合计", {}).get("件数") == 0 and "没有" in (空.get("note") or ""))
ck("没登录 → 不给数", bool(api.sales_rank(month="2026-09").get("error")))

sc = next(t for t in api.SHOP_SCHEMAS if t["name"] == "sales_rank")
键 = list(sc["input_schema"]["properties"])
ck("工具参数名都是 ASCII", all(re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", k) for k in 键), str(键))
import prompts
ck("挂了工具就有管它的规矩(TL65)", any("sales_rank" in r_.needs for r_ in prompts.ALL_RULES))

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 销量排行和独立 SQL 对上了(验了 {n} 条){D}")
