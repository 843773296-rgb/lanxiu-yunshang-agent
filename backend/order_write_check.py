#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下单写口的检查 —— 在库的**临时副本**上跑,真库一行都不碰(同 fitting_write_check)。

按业务 09-22 定的真顺序走一遍:**开单 → 没量就确认(拒)→ 后台改状态绕(拒)→
量下单量体绑到这一件 → 确认(过,进待审核、落付款)**;再钉几种该拒的:
开单前量的体顶上、没说给谁做、别店、标品;没定的单能直接取消。
"""
import os, sys, shutil, sqlite3, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("把订单状态机上的下单量体闸去掉(待确认→待审核不再看过闸结果)", "后台改状态同样被拦(不能绕)"),
    ("让开单不要求每一件指明给谁做", "没说给谁做 → 拒"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:140]) if extra else ''}")
    if not ok: FAIL.append(name)


def main():
    print("下单写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="ordw-")
    T = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.path.join(HERE, "lanxiu.db"), T)
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 下单写口 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 下单写口 {N[0]} 条全过\033[0m —— 没量不许确认、后台绕不过、确认即付款进待审核")


def run(T):
    import api, oplog, order_write as ow, measure_write as mw, server, body_gen as B
    for m in (api, oplog, ow, mw, server): m.DB = T
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row
    # 按性质挑:一个本店有顾问、有身体数据同意的成年着装人;一件挂了版型、有尺码表的启用定制款
    w = c.execute("""SELECT w.id wid, w.customer_id cid, w.gender, w.birthday, w.height, cu.shop
                     FROM wearer w JOIN customer cu ON cu.id=w.customer_id
                     WHERE w.birthday <= '2000-01-01'
                       AND EXISTS(SELECT 1 FROM consent k WHERE k.wearer_id=w.id AND k.scope='身体数据'
                                  AND k.revoked_at IS NULL)
                       AND EXISTS(SELECT 1 FROM staff s WHERE s.role='顾问' AND s.status='启用' AND s.shop=cu.shop)
                     ORDER BY w.id LIMIT 1""").fetchone()
    p = c.execute("""SELECT p.spu, p.pattern FROM product p JOIN sku s ON s.spu=p.spu
                     WHERE p.kind='定制品' AND p.pattern IS NOT NULL
                       AND EXISTS(SELECT 1 FROM size_spec z WHERE z.pattern=p.pattern)
                     ORDER BY p.spu LIMIT 1""").fetchone()
    标 = c.execute("SELECT spu FROM product WHERE kind!='定制品' ORDER BY spu LIMIT 1").fetchone()
    ck("有合适的着装人和定制款", bool(w and p))
    if not (w and p): return
    顾问 = dict(c.execute("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop=? "
                         "ORDER BY no LIMIT 1", (w["shop"],)).fetchone())
    别店 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop!=? "
                    "ORDER BY no LIMIT 1", (w["shop"],)).fetchone()
    别店 = dict(别店) if 别店 else None

    with api.as_user(顾问): r = api.open_order(w["cid"], [{"spu": p["spu"]}])
    ck("没说给谁做 → 拒", r.get("code") == "NEED_WEARER", r.get("reason"))
    if 别店:
        with api.as_user(别店): r = api.open_order(w["cid"], [{"spu": p["spu"], "wearer_id": w["wid"]}])
        ck("别店顾问不能给本店客户开单", r.get("code") == "OTHER_SHOP", r.get("reason"))
    if 标:
        with api.as_user(顾问): r = api.open_order(w["cid"], [{"spu": 标["spu"], "wearer_id": w["wid"]}])
        ck("标品不走这个入口", r.get("code") == "NOT_CUSTOM", r.get("reason"))

    # 开单前先录一次量体 —— 拿来顶「下单量体」应当被拒
    需要 = ow.需要的项(p["pattern"])
    ck("这件的版型推得出要量哪几项", bool(需要), 需要)
    体, _ = B.造尺寸(w["gender"], B.周岁(w["birthday"], "2026-08-31"), w["height"], w["wid"])
    值 = {k: 体[k] for k in (需要 or []) if k in 体}
    with api.as_user(顾问): r = api.open_order(w["cid"], [{"spu": p["spu"], "wearer_id": w["wid"]}])
    ck("开单 → 停在待确认", r.get("ok") and r.get("状态") == "待确认", r.get("reason"))
    oid = r.get("订单"); 行 = (r.get("件") or [{}])[0].get("id")
    ck("待确认的单不进 PRD 已付口径(映射到待付款)",
       c.execute("SELECT prd_status FROM ordr WHERE id=?", (oid,)).fetchone()[0] == "待付款")

    with api.as_user(顾问): r = api.confirm_order(oid)
    ck("没量下单量体就确认 → 拒", r.get("code") == "ORDER_GATE", r.get("reason"))
    r = server.transit("bk-order", oid, "待审核", {}, actor="检查")
    ck("后台改状态同样被拦(不能绕)", r.get("code") == "ORDER_GATE", r.get("reason"))
    ck("被拦后订单还在待确认", c.execute("SELECT status FROM ordr WHERE id=?", (oid,)).fetchone()[0] == "待确认")

    # 把开单时间往后挪,让刚才那种「开单前量的」成立,再绑一次早于开单的量体
    with api.as_user(顾问): r = api.record_measure(w["wid"], 值, "到店", "薄", "赤足", "平静呼气",
                                                  order_id=oid, item=str(行))
    ck("录下单量体并绑到这一件", bool(r.get("ok")), r.get("reason"))
    c.execute("UPDATE ordr SET created='2999-01-01 00:00' WHERE id=?", (oid,)); c.commit()
    with api.as_user(顾问): r = api.confirm_order(oid)
    ck("下单量体早于开单(拿旧量体顶上)→ 拒", r.get("code") == "ORDER_GATE" and "早于开单" in r.get("reason", ""),
       r.get("reason"))
    c.execute("UPDATE ordr SET created='2000-01-01 00:00' WHERE id=?", (oid,)); c.commit()

    with api.as_user(顾问): r = api.confirm_order(oid)
    ck("每件都有为它量的下单量体 → 确认成功", bool(r.get("ok")), r.get("reason"))
    o = dict(c.execute("SELECT status, prd_status, paid_at, received, amount FROM ordr WHERE id=?", (oid,)).fetchone())
    ck("确认后直接进待审核(不走待付款)、落付款", o["status"] == "待审核" and o["prd_status"] == "方案确认中"
       and o["paid_at"] and o["received"] == o["amount"], o)
    with api.as_user(顾问): r = api.confirm_order(oid)
    ck("已确认的单再确认 → 拒", r.get("code") == "BAD_STATE", r.get("reason"))

    with api.as_user(顾问): r = api.open_order(w["cid"], [{"spu": p["spu"], "wearer_id": w["wid"]}])
    r2 = server.transit("bk-order", r.get("订单"), "取消", {"reason": "客户没定"}, actor="检查")
    ck("没定的待确认单能直接取消", bool(r2.get("ok")), r2.get("reason"))


if __name__ == "__main__":
    main()
