#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量体录入写口的检查 —— 在库的**临时副本**上跑,真库一行都不碰(同 fitting_write_check)。

钉的几件事:
    权限     顾问 / 店长能录;版师、工匠不能;别店客户不能;没登录不能
    同意     没有身体数据同意不能录;未满 14 岁缺监护人同意不能录
    校验     远程不算数;三个条件缺一件拒;胸围 8.6 拒(不替人改)
    绑定     下单量体绑到那一件;那一件不是给这个人做的 → 拒;标品 → 拒
    记账     量体人记的是登录的人;以哪次为准能读到这次
"""
import os, sys, shutil, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("把量体录入的身体数据同意那道门去掉", "没有身体数据同意 → 拒"),
    ("让绑订单行时不查「这一件是不是给这个人做的」", "那一件不是给这个人做的 → 拒"),
    ("删掉一件定制单的下单量体(造数步骤漏补)", "没有下单量体的定制单不超过上限"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:140]) if extra else ''}")
    if not ok: FAIL.append(name)


def main():
    print("量体录入写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="measw-")
    T = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.path.join(HERE, "lanxiu.db"), T)
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 量体录入写口 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 量体录入写口 {N[0]} 条全过\033[0m")


# **没有下单量体的定制单件数上限** —— 业务 09-22:「每一个订单都需要有绑定的下单量体数据」。
# 现在 11 件:着装人没定的 3 件(不猜给谁量)+ 故意留的反例 8 件(超期量体 / 量体记录不全)。
# 只许降不许涨:哪个造数步骤又造出没绑下单量体的定制单,这里当场红。
# **「待确认」的单不算**:开了单还没确认下单,还没量是正常的 —— 那正是确认下单那道闸要拦的
# (重建第 20 步故意造了几张「没量」的待确认单做活用例)。
没下单量体上限 = 11


def run(T):
    import api, oplog, measure_write as mw, measure
    _c0 = sqlite3.connect(T)
    缺 = _c0.execute("""SELECT COUNT(*) FROM ordr_item i JOIN ordr o ON o.id=i.order_id
                        WHERE o.kind='定制品订单' AND o.status!='待确认'
                          AND NOT EXISTS(SELECT 1 FROM measure_rec m WHERE m.order_item_id=i.id)""").fetchone()[0]
    _c0.close()
    ck("没有下单量体的定制单不超过上限(业务 09-22:每一个订单都要有)", 缺 <= 没下单量体上限,
       f"{缺} 件(上限 {没下单量体上限},只许降)")
    for m in (api, oplog, mw): m.DB = T
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row
    # **按性质挑人,不钉死编号**:一个有身体数据同意的成年着装人,名下有一件定制单是给他做的
    r = c.execute("""SELECT w.id wid, c.shop, i.id iid, i.order_id oid FROM wearer w
                     JOIN customer c ON c.id=w.customer_id
                     JOIN ordr_item i ON i.wearer_id=w.id JOIN ordr o ON o.id=i.order_id
                     WHERE o.kind='定制品订单' AND w.birthday <= '2000-01-01'
                       AND EXISTS(SELECT 1 FROM consent k WHERE k.wearer_id=w.id AND k.scope='身体数据'
                                  AND k.revoked_at IS NULL)
                     ORDER BY w.id LIMIT 1""").fetchone()
    ck("有一个带同意、名下有定制单的成年着装人", bool(r))
    if not r: return
    wid, shop, iid, oid = r["wid"], r["shop"], r["iid"], r["oid"]
    人 = lambda role, 店=None, 别=None: (lambda x: dict(x) if x else None)(c.execute(
        "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用'"
        + (" AND shop=?" if 店 else "") + (" AND shop!=?" if 别 else "") + " ORDER BY no LIMIT 1",
        [role] + ([店] if 店 else []) + ([别] if 别 else [])).fetchone())
    顾问, 版师, 别店 = 人("顾问", shop), 人("版师"), 人("顾问", 别=shop)
    ck("本店顾问、版师、别店顾问都找得到", bool(顾问 and 版师 and 别店))
    if not (顾问 and 版师 and 别店): return
    好 = dict(wearer_id=wid, values={"胸围": 86, "腰围": 68, "衣长": 110}, method="到店",
              inner="薄", shoe="赤足", breath="平静呼气")

    with api.as_user(版师): x = api.record_measure(**好)
    ck("版师不能录", x.get("code") == "ROLE", x.get("reason"))
    with api.as_user(别店): x = api.record_measure(**好)
    ck("别店顾问不能录本店客户", x.get("code") == "OTHER_SHOP", x.get("reason"))
    ck("没登录不能录", bool(api.record_measure(**好).get("error")))
    with api.as_user(顾问): x = api.record_measure(**{**好, "method": "远程"})
    ck("远程 → 不算数", x.get("code") == "BAD_MEASURE" and "远程" in x.get("reason", ""), x.get("reason"))
    with api.as_user(顾问): x = api.record_measure(**{**好, "shoe": ""})
    ck("缺「鞋」→ 拒", x.get("code") == "BAD_MEASURE", x.get("reason"))
    with api.as_user(顾问): x = api.record_measure(**{**好, "values": {"胸围": 8.6}})
    ck("胸围 8.6 → 拒(不替人改)", x.get("code") == "BAD_MEASURE", x.get("reason"))

    # 同意
    c.execute("UPDATE consent SET revoked_at='2026-01-01' WHERE wearer_id=? AND scope='身体数据'", (wid,)); c.commit()
    with api.as_user(顾问): x = api.record_measure(**好)
    ck("没有身体数据同意 → 拒", x.get("code") == "NO_CONSENT", x.get("reason"))
    c.execute("UPDATE consent SET revoked_at=NULL WHERE wearer_id=? AND scope='身体数据'", (wid,)); c.commit()

    # 平时的量体
    前 = c.execute("SELECT COUNT(*) FROM measure_rec").fetchone()[0]
    with api.as_user(顾问): x = api.record_measure(**好)
    ck("登记一次平时的量体", bool(x.get("ok")) and x.get("绑定订单行") is None, x.get("reason"))
    ck("写进去的行数 = 项数", c.execute("SELECT COUNT(*) FROM measure_rec").fetchone()[0] - 前 == 3)
    ck("量体人记的是登录的人", c.execute("SELECT DISTINCT measured_by_no FROM measure_rec WHERE measured_at=? "
                                        "AND wearer_id=?", (x["时间"], wid)).fetchone()[0] == 顾问["no"])

    # 下单量体
    with api.as_user(顾问): x = api.record_measure(**{**好, "values": {"腰围": 69, "衣长": 118},
                                                     "order_id": oid, "item": str(iid)})
    ck("登记这一件的下单量体", bool(x.get("ok")) and x.get("绑定订单行") == iid, x.get("reason"))
    记 = [dict(着装人=q["wearer_id"], 时间=q["measured_at"], 量体人=q["measured_by_no"], 方式=q["method"],
              项=q["name"], 值=q["value"], 订单行=q["order_item_id"])
         for q in c.execute("SELECT r.*, i.name FROM measure_rec r JOIN measure_item i ON i.code=r.item "
                            "WHERE r.wearer_id=?", (wid,))]
    s, _ = measure.以哪次为准(measure.场次(记), 订单行=iid)
    ck("以哪次为准读到的就是这次下单量体(衣长 118)", bool(s) and s["值们"].get("衣长") == 118)
    别人 = c.execute("SELECT i.id FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                    "WHERE o.id=? AND COALESCE(i.wearer_id,'')!=?", (oid, wid)).fetchone() or \
          c.execute("SELECT i.id, i.order_id FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                    "WHERE o.kind='定制品订单' AND COALESCE(i.wearer_id,'')!=? AND o.shop=? LIMIT 1",
                    (wid, shop)).fetchone()
    if 别人:
        _oid = 别人["order_id"] if "order_id" in 别人.keys() else oid
        with api.as_user(顾问): x = api.record_measure(**{**好, "order_id": _oid, "item": str(别人["id"])})
        ck("那一件不是给这个人做的 → 拒", x.get("code") == "WRONG_WEARER", x.get("reason"))
    标 = c.execute("SELECT i.id, o.id oid FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                  "WHERE o.kind='标品订单' LIMIT 1").fetchone()
    if 标:
        with api.as_user(顾问): x = api.record_measure(**{**好, "order_id": 标["oid"], "item": str(标["id"])})
        ck("标品不做下单量体 → 拒", x.get("code") == "NOT_CUSTOM", x.get("reason"))


if __name__ == "__main__":
    main()
