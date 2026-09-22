#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造几张停在「待确认」的演示单 —— 让页面和智能体上看得到下单那道闸的两面。

    python3 tools/seed_pending_orders.py      # 重建第 20 步(最后一步之前)

下单是业务 09-22 定的:**先开单 → 再量 → 量完绑到这一件 → 确认下单**(口径 knowledge/order_place.py)。
库里的订单全是造数据直插的,一张「待确认」都没有 —— 页面上那一栏永远是空的,
智能体被问「这张单能不能确认」时也只能拿自己现开的单演示。

## 造哪几种(每种都是一条活用例)

  能确认        开单、每一件量完下单量体并绑上             → 确认下单会过
  没量          开单了,还没量                            → 被拦:没有下单量体
  缺项          量了,但少了这件衣服要用的一项             → 被拦:列出缺哪一项
  两件一件没量  一件量好绑上,另一件还没量                  → 被拦:整单确认不了

## 怎么造

**走真的写口**(order_write.open_order / measure_write.record),不直插 ——
造出来的数据和线上走的是同一条路,写口哪里松了,造数这一步就先撞上。
只把两个写口的时钟拨到演示世界的日期(seed.TODAY 前两天),否则会落下「未来」的开单时间。

**避开反例夹具**(同 backfill_order_measure):夹具着装人不用,量体记录不足 4 条的客户不用 ——
那些人身上挂着别的规则的反例,在他们名下开新单会改掉那些用例的样子。
按编号挑,不用随机数 —— 重建多少次都是同一批。
"""
import os, sys, sqlite3, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"), HERE, ROOT]
import order_write as ow, measure_write as mw, body_gen as B
from seed import TODAY
from fix_order_measure import 夹具着装人集

DB = os.path.join(ROOT, "backend", "lanxiu.db")
# 四种 × 各几张。能确认的给两张,被拦的三种各一张 —— 两面都有,又不至于把「待确认」一栏堆满
方案 = ["能确认", "能确认", "没量", "缺项", "两件一件没量"]


@contextlib.contextmanager
def 拨钟(t):
    a, b = ow._now, mw._now
    ow._now = mw._now = (lambda: t)
    try:
        yield
    finally:
        ow._now, mw._now = a, b


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    if c.execute("SELECT COUNT(*) FROM ordr WHERE status='待确认'").fetchone()[0]:
        print("  库里已经有待确认的单,不重复造"); return
    # 挂了版型、有尺码表的定制款,取两款(两件那张单用)
    款 = [r for r in c.execute("""SELECT p.spu, p.pattern FROM product p
                                 WHERE p.kind='定制品' AND p.pattern IS NOT NULL
                                   AND EXISTS(SELECT 1 FROM sku s WHERE s.spu=p.spu)
                                   AND EXISTS(SELECT 1 FROM size_spec z WHERE z.pattern=p.pattern)
                                 ORDER BY p.spu""") if ow.需要的项(r["pattern"])]
    人 = c.execute("""SELECT w.id wid, w.customer_id cid, w.gender, w.birthday, w.height, cu.shop,
                             (SELECT s.no FROM staff s WHERE s.role='顾问' AND s.status='启用' AND s.shop=cu.shop
                              ORDER BY s.no LIMIT 1) adv
                      FROM wearer w JOIN customer cu ON cu.id=w.customer_id
                      WHERE w.birthday <= '2000-01-01' AND w.height IS NOT NULL
                        AND EXISTS(SELECT 1 FROM consent k WHERE k.wearer_id=w.id AND k.scope='身体数据'
                                   AND k.revoked_at IS NULL)
                        AND (SELECT COUNT(*) FROM measure_rec m WHERE m.customer_id=cu.id) >= 4
                        -- 账户在注销的不开新单(A15:有在办业务的账户不得注销)
                        AND NOT EXISTS(SELECT 1 FROM account a WHERE a.id=cu.account_id
                                       AND a.status IN ('注销中','已注销'))
                      ORDER BY cu.shop, w.id""").fetchall()
    人 = [r for r in 人 if r["adv"] and r["wid"] not in 夹具着装人集]
    # 每家店轮着挑,一人一张 —— 各店的「待确认」栏里都看得到
    挑, 用过店 = [], {}
    for r in 人:
        if r["cid"] in {x["cid"] for x in 挑}: continue
        if 用过店.get(r["shop"], 0) >= 2: continue
        挑.append(r); 用过店[r["shop"]] = 用过店.get(r["shop"], 0) + 1
        if len(挑) == len(方案): break
    if len(挑) < len(方案) or len(款) < 2:
        print(f"  ❌ 人或款不够:人 {len(挑)}/{len(方案)},款 {len(款)}"); sys.exit(1)
    结果 = []
    for k, (种, r) in enumerate(zip(方案, 挑)):
        顾问 = dict(c.execute("SELECT no,name,role,shop FROM staff WHERE no=?", (r["adv"],)).fetchone())
        开 = f"{TODAY[:8]}{int(TODAY[8:]) - 2 + k % 3:02d} {10 + k}:00"
        量 = 开[:11] + f"{10 + k}:30"
        件 = [款[k % len(款)]] + ([款[(k + 1) % len(款)]] if 种 == "两件一件没量" else [])
        with 拨钟(开):
            o = ow.open_order({"customer_id": r["cid"],
                               "items": [{"spu": p["spu"], "wearer_id": r["wid"]} for p in 件]}, 顾问)
        if not o.get("ok"):
            print(f"  ❌ 开单失败:{o.get('reason')}"); sys.exit(1)
        体, _ = B.造尺寸(r["gender"], B.周岁(r["birthday"], TODAY), r["height"], r["wid"])
        要量 = [] if 种 == "没量" else o["件"][:1] if 种 == "两件一件没量" else o["件"]
        for 行, p in zip(o["件"], 件):
            if 行 not in 要量: continue
            需要 = ow.需要的项(p["pattern"])
            值 = {x: 体[x] for x in 需要 if x in 体}
            if 种 == "缺项":
                值.pop(sorted(值)[0])
            with 拨钟(量):
                m = mw.record({"wearer_id": r["wid"], "values": 值, "method": "到店", "inner": "薄",
                               "shoe": "赤足", "breath": "平静呼气", "order_id": o["订单"], "item": str(行["id"])},
                              顾问)
            if not m.get("ok"):
                print(f"  ❌ 量体失败:{m.get('reason')}"); sys.exit(1)
        g, 话, _ = ow.过闸(o["订单"])
        结果.append((种, o["订单"], g))
        print(f"  {o['订单']} {r['shop']} {种:<8} → 确认下单会{'过' if g == '可以' else '被拦'}:{话[:60]}")
    错 = [(种, oid, g) for 种, oid, g in 结果 if (g == "可以") != (种 == "能确认")]
    if 错:
        print(f"  ❌ 造出来的单和想要的不一样:{错}"); sys.exit(1)
    print(f"  造了 {len(结果)} 张待确认的单:能确认 {sum(g == '可以' for _, _, g in 结果)} 张、"
          f"被拦 {sum(g != '可以' for _, _, g in 结果)} 张")


if __name__ == "__main__":
    main()
