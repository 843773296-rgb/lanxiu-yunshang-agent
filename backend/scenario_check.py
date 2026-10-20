#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""业务场景回归 · 第一条:顾问接待到下单(10-19 外部复审第 4 节 F / 第 7 节场景一,用户 10-20 拍「做 F」)。

**单测每个写口都对,串起来可能是断的** —— 复审 3.1 就是这个形状:校验读 `pt`、入库读 `pattern`,
两段各自都「成功」,存进去的方案客户和版型是空的。这一份不再验单个写口(各有各的检查),
只验**一条完整的业务流程走完之后,几样东西互相对不对得上**:

    顾问存方案(挂客户、版型)→ 照着方案开单 → 给这一件录下单量体 → 确认下单
    → 方案的客户 = 订单的客户 / 订单挂着这套方案 / 那一件是给这位着装人做的、着装人属于这位客户
      / 量体挂在这一件上 / AI 按方案查得到这张单 / 全程署名都是这位顾问

第一次写出来就逮到一处真断链:`ordr.scheme_id` 这一列一直在、`get_scheme` 也靠它查「这套方案下了哪些单」,
**开单写口却从来不填** —— 新开的单永远挂不回方案(库里只有造数写的 70 张有),AI 查方案永远说「还没下过单」。
全在库副本上跑,身份是本店在职顾问。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("开单不填来源方案", "订单挂着这套方案,AI 按方案查得到这张单"),
    ("开单不核方案是不是这位客户的", "拿别的客户的方案开单 → 拒,而且没开出单"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


print("业务场景回归 · 顾问接待到下单(一条流程走完,几样东西互相对得上)")
print("=" * 80)
import oplog, api, order_write as ow, measure_write as mw, server as SV, scheme as SCH, body_gen as B   # noqa: E401
import order_place, fix_order_measure as FX
import check_copy
db = check_copy.用副本("scenario-")
c = sqlite3.connect(db); c.row_factory = sqlite3.Row

# ── 夹具:按性质挑(本店有顾问、签了身体数据同意的成年着装人;和他对得上、挂了版型的上架定制款)──
w = c.execute("""SELECT w.id wid, w.customer_id cid, w.gender, w.birthday, w.height, cu.shop
                 FROM wearer w JOIN customer cu ON cu.id=w.customer_id
                 WHERE w.birthday <= '2000-01-01'
                   AND EXISTS(SELECT 1 FROM consent k WHERE k.wearer_id=w.id AND k.scope='身体数据' AND k.revoked_at IS NULL)
                   AND EXISTS(SELECT 1 FROM staff s WHERE s.role='顾问' AND s.status='启用' AND s.shop=cu.shop)
                 ORDER BY w.id LIMIT 1""").fetchone()
候选 = c.execute("""SELECT DISTINCT p.spu, p.pattern, p.gender, p.category FROM product p JOIN sku s ON s.spu=p.spu
                   WHERE p.kind='定制品' AND p.pattern IS NOT NULL AND p.status='上架'
                     AND EXISTS(SELECT 1 FROM size_spec z WHERE z.pattern=p.pattern) ORDER BY p.spu""").fetchall()
p = next((x for x in 候选 if w and order_place.穿的人对不对(
    x["gender"], FX.顶级品类(c, x["category"]), w["gender"], ow._周岁(w["birthday"], ow._now()))[0] == "可以"), None)
组 = dict(xz="XZ04", mt="MT02", kf=["KF02", "KF03"], color="胭脂", ps=["云肩", "腰封"])
合法 = p and SCH.validate(**组, pattern=p["pattern"], size=None, need_date=None, scope="局部", workers=2)[0]
别客 = c.execute("SELECT id FROM customer WHERE shop=? AND id<>? ORDER BY id LIMIT 1",
                 (w["shop"], w["cid"])).fetchone() if w else None
if not (w and p and 合法 and 别客):
    ck("夹具:着装人、对得上的定制款、合法的方案组合、同店另一位客户都挑得到 —— 挑不到就没验,不算通过",
       False, dict(着装人=bool(w), 款=bool(p), 组合合法=bool(合法), 别客=bool(别客)))
else:
    顾问 = dict(c.execute("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop=? "
                         "ORDER BY no LIMIT 1", (w["shop"],)).fetchone())

    起 = c.execute("SELECT COALESCE(MAX(id),0) FROM op_log").fetchone()[0]     # 只看这一趟流程新写的日志
    # ① 存方案
    r = SV.scheme_save(dict(组, id="SC-场景1", name="场景回归", cust=w["cid"], pt=p["pattern"]), me=顾问)
    方 = dict(c.execute("SELECT * FROM scheme WHERE id='SC-场景1'").fetchone() or {})
    ck("① 方案存进去了,挂着这位客户和这个版型", r.get("ok") and 方.get("customer_id") == w["cid"]
       and 方.get("pattern") == p["pattern"], (r.get("reason"), 方.get("customer_id"), 方.get("pattern")))

    # ② 别的客户的方案拿来开单 → 拒(先试反例,免得它开出一张单污染后面的断言)
    SV.scheme_save(dict(组, id="SC-场景别人", name="别人的", cust=别客["id"], pt=p["pattern"]), me=顾问)
    前单数 = c.execute("SELECT COUNT(*) FROM ordr").fetchone()[0]
    with api.as_user(顾问):
        r = api.open_order(w["cid"], [{"spu": p["spu"], "wearer_id": w["wid"]}], scheme_id="SC-场景别人")
    ck("拿别的客户的方案开单 → 拒,而且没开出单", r.get("code") == "SCHEME_OTHER_CUSTOMER"
       and c.execute("SELECT COUNT(*) FROM ordr").fetchone()[0] == 前单数, r)

    # ③ 照着方案开单
    with api.as_user(顾问):
        r = api.open_order(w["cid"], [{"spu": p["spu"], "wearer_id": w["wid"]}], scheme_id="SC-场景1")
    oid = r.get("订单"); 行 = (r.get("件") or [{}])[0].get("id")
    单 = dict(c.execute("SELECT * FROM ordr WHERE id=?", (oid,)).fetchone() or {}) if oid else {}
    件 = dict(c.execute("SELECT * FROM ordr_item WHERE id=?", (行,)).fetchone() or {}) if 行 else {}
    ck("② 开单成功,停在待确认", r.get("ok") and 单.get("status") == "待确认", r.get("reason"))
    ck("订单的客户 = 方案的客户", 单.get("customer_id") == 方.get("customer_id"), (单.get("customer_id"), 方.get("customer_id")))
    ck("那一件是给这位着装人做的,着装人属于这位客户",
       件.get("wearer_id") == w["wid"] and c.execute("SELECT customer_id FROM wearer WHERE id=?", (w["wid"],)).fetchone()[0] == 单.get("customer_id"),
       件.get("wearer_id"))

    # ④ 给这一件录下单量体
    需要 = ow.需要的项(p["pattern"])
    体, _ = B.造尺寸(w["gender"], B.周岁(w["birthday"], "2026-08-31"), w["height"], w["wid"])
    值 = {k: 体[k] for k in (需要 or []) if k in 体}
    with api.as_user(顾问):
        r = api.record_measure(w["wid"], 值, "到店", "薄", "赤足", "平静呼气", order_id=oid, item=str(行))
    量 = c.execute("SELECT DISTINCT wearer_id, order_item_id FROM measure_rec WHERE order_item_id=?", (行,)).fetchall()
    ck("③ 下单量体录上了,挂在这一件、量的是这位着装人", r.get("ok") and [tuple(x) for x in 量] == [(w["wid"], 行)],
       (r.get("reason"), [tuple(x) for x in 量]))

    # ⑤ 确认下单
    with api.as_user(顾问):
        r = api.confirm_order(oid, no7day_ack=True)
    ck("④ 确认下单 → 待审核", r.get("ok") and c.execute("SELECT status FROM ordr WHERE id=?", (oid,)).fetchone()[0] == "待审核",
       r.get("reason"))

    # ⑥ 串起来对一遍
    ck("订单挂着这套方案,AI 按方案查得到这张单",
       c.execute("SELECT scheme_id FROM ordr WHERE id=?", (oid,)).fetchone()[0] == "SC-场景1"
       and oid in [x["id"] for x in (api.get_scheme(scheme_id="SC-场景1").get("由这条方案下的订单") or [])],
       api.get_scheme(scheme_id="SC-场景1").get("下单情况"))
    署名 = [x[0] for x in c.execute(
        "SELECT actor FROM op_log WHERE id>? AND ((machine='fe-scheme' AND target='SC-场景1') OR target=?)", (起, oid))]
    短名 = 顾问["name"].split()[-1]          # 员工表的名字带简码(「A01 林岚」),日志里记的是「林岚」
    ck("全程署名都是这位顾问(方案、开单、确认)", len(署名) >= 3 and all(短名 in a or 顾问["no"] in a for a in 署名), 署名)
c.close()

print()
if 坏:
    print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 场景一 · 顾问接待到下单:方案、订单、着装人、量体、AI 查询、署名一路对得上(验了 {n} 条){D}")
