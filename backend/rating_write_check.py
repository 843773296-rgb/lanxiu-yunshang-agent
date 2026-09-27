#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评价写口的检查 —— 在库的**临时副本**上跑,真库一行都不碰(同 pickup_write_check)。

钉的几件事(口径在 `knowledge/rating.py`,业务 2026-09-24 / 09-27):
    闸       **没签收不许评**;而且判据是签收记录本身,不是订单状态
    一次     一个包裹一次;手机后四位对不上不许评
    星级     1-5 整数,6 星不夹成 5 星
    差评     ≤3 星**自动进已有的 task 清单**(type='评价差评'),不新建第二张表
    改       24 小时内一次;好评改差评进清单,**差评改好评不撤出**
    处理     只有店长能关,**必须写处理记录**
    不变量   rating 表**没有 status 列**(状态只存 task 上);时间用世界时钟

## 夹具是**跑出来的,不是插进去的**

签收那一步走 `pickup_write` 的真实流程(到店 → 顾客出码 → 导购核验),
不直接 `INSERT pickup_item`。**自己插一条签收记录来测闸,测的就不是闸** ——
插的时候想当然填上的那几列,正好是闸要读的那几列。
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("让 customer_rate() 不问签收就收下评价", "没签收 → 不许评"),
    ("把 差评线 从 3 改成 2(3 星就不建工单了)", "3 星是差评 → 自动进 task 清单"),
    ("让 close_bad_rating() 不要求处理记录", "关差评不写处理记录 → 拒"),
    ("让 close_bad_rating() 放开角色(顾问也能关)", "顾问关差评 → 拒"),
    ("让 customer_edit_rating() 在差评改好评时把工单关掉", "差评改好评 → 工单不撤,还在待处理"),
    ("在 seed_rating 的建表里加一句 ALTER,给 rating 加个 status 列",
     "rating 表没有 status 列(状态只存 task 上)"),
    ("把 worldclock.已发生的时间列 里 rating 那三行去掉",
     "三列都登记进了 worldclock.已发生的时间列"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:150]) if extra else ''}")
    if not ok: FAIL.append(name)


def main():
    print("评价写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 88)
    tmp = tempfile.mkdtemp(prefix="ratew-")
    T = os.path.join(tmp, "lanxiu.db")
    src = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); dst = sqlite3.connect(T)
    src.backup(dst); src.close(); dst.close()
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 评价写口 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 评价写口 {N[0]} 条全过\033[0m")


def run(T):
    import oplog, pickup_write as pw, rating_write as rt, repair_write as rw, seed_rating
    import rating as R, worldclock
    for m in (oplog, pw, rt, rw): m.DB = T
    seed_rating.建表(T)
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row

    # ── 不变量:状态只存一处 ──────────────────────────────────────────
    列 = [r["name"] for r in c.execute("PRAGMA table_info(rating)")]
    ck("库里有评价表", bool(列))
    ck("rating 表没有 status 列(状态只存 task 上)", "status" not in 列,
       "两处都存的话,「工单关了但评价那行还是待处理」这种漂**不会报错**,只会让两个页面显示不同的东西")
    ck("三列都登记进了 worldclock.已发生的时间列(C4 和平移闸都读它)",
       {("rating", "rated_at"), ("rating", "edited_at"), ("rating", "handled_at")}
       <= {(t, col) for t, col, _, _ in worldclock.已发生的时间列},
       "不登记就是两道闸同时的盲区 —— pkg.created 上次就是这么漏的")

    # ── 夹具:**把签收真的跑出来**,不插 pickup_item ────────────────────
    o = c.execute("""SELECT o.id, o.shop, o.customer_id, k.phone_tail FROM ordr o
                       JOIN customer k ON k.id=o.customer_id
                      WHERE o.kind='定制品订单' AND o.status='已发货'
                        AND (SELECT COUNT(*) FROM pkg g WHERE g.order_id=o.id AND g.void_at IS NULL)=1
                        AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id)
                      ORDER BY o.id LIMIT 1""").fetchone()
    ck("有一张已发货、一个包裹、还没到店的定制单当夹具", bool(o))
    if not o: return
    oid, 尾 = o["id"], o["phone_tail"]
    人 = lambda role, 店: (lambda x: dict(x) if x else None)(c.execute(
        "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' AND shop=? ORDER BY no LIMIT 1",
        (role, 店)).fetchone())
    顾问, 店长 = 人("顾问", o["shop"]), 人("店长", o["shop"])
    ck("本店有顾问也有店长", bool(顾问) and bool(店长))
    if not (顾问 and 店长): return

    # ── 闸:**签收之前**一律不许评 ────────────────────────────────────
    包 = c.execute("SELECT pkg_id FROM pkg WHERE order_id=? AND void_at IS NULL", (oid,)).fetchone()["pkg_id"]
    r = rt.customer_rate(oid, 尾, 5, "很好", pkg=包)
    ck("没签收 → 不许评", not r["ok"] and r["code"] == "CANNOT_RATE", r.get("reason"))
    ck("被拒的时候一行都没写进去", c.execute("SELECT COUNT(*) FROM rating").fetchone()[0] == 0)

    # 走真实签收流程:到店 → 顾客出码 → 导购核验
    pw.arrive({"order_id": oid}, 顾问)
    码 = pw.customer_issue_code(oid, 尾).get("试穿合身码")
    v = pw.verify({"order_id": oid, "code": 码}, 顾问)
    ck("签收流程跑通了(到店 → 出码 → 核验)", v.get("ok"), v.get("reason"))
    ck("签收留下了「件」上的记录(闸读的就是它)",
       c.execute("SELECT COUNT(*) FROM pickup_item WHERE pkg_id=? AND fit_result='合身' AND fit_at IS NOT NULL",
                 (包,)).fetchone()[0] > 0)

    # ── 签收之后:能评 ────────────────────────────────────────────────
    ck("手机后四位对不上 → 不许评",
       rt.customer_rate(oid, "0000" if 尾 != "0000" else "1111", 5)["code"] == "NOT_YOURS")
    ck("6 星 → 拒,而且不夹成 5 星", rt.customer_rate(oid, 尾, 6)["code"] == "BAD_STAR")
    ck("0 星 → 拒", rt.customer_rate(oid, 尾, 0)["code"] == "BAD_STAR")
    ck("半星 → 拒", rt.customer_rate(oid, 尾, 4.5)["code"] == "BAD_STAR")
    ck("还是一行都没写进去(被拒的都没落库)", c.execute("SELECT COUNT(*) FROM rating").fetchone()[0] == 0)
    r = rt.customer_rate(oid, 尾, 5, "导购很细心")
    ck("签收之后 5 星 → 收下", r["ok"], r.get("reason"))
    行 = c.execute("SELECT * FROM rating WHERE pkg_id=?", (包,)).fetchone()
    ck("评价落在包裹上,带着单号和客户", 行 and 行["order_id"] == oid and 行["customer_id"] == o["customer_id"])
    ck("来源记的是顾客小程序(顾问不能替顾客评)", 行["src"] == rt.来源_顾客)
    ck("经手顾问记下来了(店长要能查是谁经手的,但不进考核)", 行["advisor_no"] == 顾问["no"])
    ck("评价时间用的是**世界时钟**,不是机器时钟",
       str(行["rated_at"])[:10] == worldclock.今天().isoformat(),
       f"写出来是 {行['rated_at']},世界的今天是 {worldclock.今天()}")
    ck("5 星不建工单", 行["task_id"] is None
       and c.execute("SELECT COUNT(*) FROM task WHERE ref_id=?", (包,)).fetchone()[0] == 0)
    ck("同一个包裹再评 → 拒(一个包裹一次)", rt.customer_rate(oid, 尾, 4)["code"] == "CANNOT_RATE")

    # ── 改:好评 → 差评,进清单 ────────────────────────────────────────
    r = rt.customer_edit_rating(oid, 尾, 3, "回家发现袖口线头很多")
    ck("24 小时内能改一次", r["ok"], r.get("reason"))
    ck("好评改差评 → 进清单", r.get("清单") == "进清单", r.get("reason"))
    # ⚠️ 这里故意用 **3 星**:业务 2026-09-27 定的是「≤3 算差评」,不是常见的 ≤2。
    # 第一版这条名字写着「3 星」、改的却是 2 星 —— **名字和它真正测的不是一回事**,
    # 那样把 差评线 从 3 改成 2 也不会红(2 星在两种线下都是差评)。这个坑记在 B-85,这是第三次。
    t = c.execute("SELECT * FROM task WHERE ref_id=?", (包,)).fetchone()
    ck("3 星是差评 → 自动进 task 清单", bool(t) and t["type"] == rt.工单类型 and t["status"] == "待处理",
       dict(t) if t else "没建工单")
    ck("工单进的是**已有的** task 表,没有新建第二张清单表",
       not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name LIKE '%rating%todo%'").fetchone())
    ck("工单号是定的(TR+包裹号,重跑不会重复建)", t["id"] == f"TR{包}")
    ck("再改一次 → 拒(最多改一次)", not rt.customer_edit_rating(oid, 尾, 5)["ok"])

    # ── 店长处理 ─────────────────────────────────────────────────────
    ck("顾问关差评 → 拒", rt.close_bad_rating({"pkg": 包, "note": "已联系顾客并补送"}, 顾问)["code"] == "ROLE")
    ck("没登录 → 拒", rt.close_bad_rating({"pkg": 包, "note": "x" * 10}, None)["code"] == "NO_LOGIN")
    ck("关差评不写处理记录 → 拒", rt.close_bad_rating({"pkg": 包, "note": ""}, 店长)["code"] == "NEED_NOTE")
    ck("「看过了」太短,不算处理完", rt.close_bad_rating({"pkg": 包, "note": "看过了"}, 店长)["code"] == "NEED_NOTE")
    ck("被拒之后工单还在待处理",
       c.execute("SELECT status FROM task WHERE id=?", (t["id"],)).fetchone()[0] == "待处理")
    r = rt.close_bad_rating({"pkg": 包, "note": "已电话联系顾客,约了周六回店修线头,顾客接受"}, 店长)
    ck("店长写了处理记录 → 关得掉", r["ok"], r.get("reason"))
    ck("工单状态变成已关闭",
       c.execute("SELECT status FROM task WHERE id=?", (t["id"],)).fetchone()[0] == "已关闭")
    ck("处理记录和处理人落在评价那行上",
       (lambda x: x["handle_note"] and x["handled_by"] == 店长["no"] and x["handled_at"])(
           c.execute("SELECT * FROM rating WHERE pkg_id=?", (包,)).fetchone()))
    ck("已关闭的工单不能再关一次", rt.close_bad_rating({"pkg": 包, "note": "再关一次试试看"}, 店长)
       ["code"] == "ALREADY_CLOSED")

    # ── 差评改好评:**工单不撤** ───────────────────────────────────────
    # 另找一个包裹从头走一遍 —— 上面那个已经改过一次了。
    o2 = c.execute("""SELECT o.id, k.phone_tail, o.shop FROM ordr o JOIN customer k ON k.id=o.customer_id
                       WHERE o.kind='定制品订单' AND o.status='已发货' AND o.shop=?
                         AND (SELECT COUNT(*) FROM pkg g WHERE g.order_id=o.id AND g.void_at IS NULL)=1
                         AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id)
                       ORDER BY o.id LIMIT 1""", (o["shop"],)).fetchone()
    ck("有第二张单当夹具", bool(o2))
    if o2:
        oid2, 尾2 = o2["id"], o2["phone_tail"]
        pw.arrive({"order_id": oid2}, 顾问)
        码2 = pw.customer_issue_code(oid2, 尾2).get("试穿合身码")
        pw.verify({"order_id": oid2, "code": 码2}, 顾问)
        包2 = c.execute("SELECT pkg_id FROM pkg WHERE order_id=? AND void_at IS NULL", (oid2,)).fetchone()["pkg_id"]
        r = rt.customer_rate(oid2, 尾2, 2, "等太久了")
        ck("一上来就 2 星 → 收下并当场进清单", r["ok"] and r.get("差评") and r.get("工单") == f"TR{包2}",
           r.get("reason"))
        r = rt.customer_edit_rating(oid2, 尾2, 5, "店长处理得很好,改成 5 星")
        ck("差评改好评 → 工单不撤,还在待处理",
           r["ok"] and r.get("清单") == "留在清单里"
           and c.execute("SELECT status FROM task WHERE id=?", (f"TR{包2}",)).fetchone()[0] == "待处理",
           r.get("reason"))
        ck("工单上标了「顾客后来改成 5 星」",
           "改成 5 星" in (c.execute("SELECT summary FROM task WHERE id=?", (f"TR{包2}",)).fetchone()[0] or ""))
        ck("评价行上留着原来的星级(看得出改过)",
           (lambda x: x["star"] == 5 and x["star_before"] == 2 and x["edit_cnt"] == 1)(
               c.execute("SELECT * FROM rating WHERE pkg_id=?", (包2,)).fetchone()))

    # ── 闸的要害:**判据取签收记录,不取订单状态** ─────────────────────
    # ⚠️ 第一版这一条是假绿的:它没说是哪个包裹,于是拦住它的是 `_挑包裹`
    # (「这一单 2 个包裹,没有能评的」)—— **闸压根没被碰到**,
    # 断言却写着「这一条证明闸读的是签收记录」。
    # 和咬合第三关一模一样的失效:**红了,但红的不是那一条**。
    # 所以现在**点名包裹**,并且要求错误码正好是闸给的那个。
    o3 = c.execute("""SELECT g.pkg_id, o.id oid, o.customer_id FROM ordr o
                        JOIN pkg g ON g.order_id=o.id AND g.void_at IS NULL
                       WHERE o.kind='定制品订单'
                         AND NOT EXISTS(SELECT 1 FROM pickup_item t
                                         WHERE t.pkg_id=g.pkg_id AND t.fit_result='合身')
                       LIMIT 1""").fetchone()
    ck("有一个「没签收过」的包裹当夹具", bool(o3))
    if o3:
        with sqlite3.connect(T) as cx:      # 把订单状态改成「待完成」—— 模拟状态被别的路写过
            cx.execute("UPDATE ordr SET status='待完成' WHERE id=?", (o3["oid"],))
        尾3 = c.execute("SELECT phone_tail FROM customer WHERE id=?", (o3["customer_id"],)).fetchone()[0]
        r = rt.customer_rate(o3["oid"], 尾3, 5, pkg=o3["pkg_id"])
        ck("订单状态是「待完成」但这个包裹没签收记录 → **闸拒**(而且是闸拒的,不是别的条件)",
           r["code"] == "CANNOT_RATE" and "没签收" in r["reason"],
           f"{r.get('code')}:{r.get('reason')}")
        ck("这一条证明闸读的是签收记录,不是订单状态",
           c.execute("SELECT COUNT(*) FROM rating WHERE pkg_id=?", (o3["pkg_id"],)).fetchone()[0] == 0)


if __name__ == "__main__":
    main()
