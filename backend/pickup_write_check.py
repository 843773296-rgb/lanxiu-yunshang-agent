#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付签收写口的检查 —— 在库的**临时副本**上跑,真库一行都不碰(同 fitting_write_check)。

钉的几件事(业务 2026-09-22):
    权限     顾问 / 店长能做;版师、工匠不能;别店的单不能;没登录不能
    到店     只认「已发货」的定制单;标品不走这一套
    转寄     没有物流单号不许转寄
    码       顾客手机后四位对不上拿不到码;输错记次数、5 次作废;对的码 → 签收、订单进待完成
    不合身   不算签收,订单状态不动,给判责建议
    完成     顾客确认;顾问追认要满 15 天、要写理由
    不变量   「待完成」「完成」的定制单,每一单都有一条试穿合身的签收记录
"""
import os, sys, shutil, sqlite3, tempfile, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("让 verify() 在码不对时也放行", "错的码 → 不签收"),
    ("让 not_fit() 把订单推进待完成", "不合身 → 订单状态不动"),
    ("让 ratify() 不查签收满没满 15 天", "签收不满 15 天 → 不许追认"),
    ("让 get_order 的金额自检不算定制加价", "定制单查订单不报假的金额异常"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:140]) if extra else ''}")
    if not ok: FAIL.append(name)


def main():
    print("交付签收写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="pickw-")
    T = os.path.join(tmp, "lanxiu.db")
    src = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); dst = sqlite3.connect(T)
    src.backup(dst); src.close(); dst.close()
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 交付签收写口 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 交付签收写口 {N[0]} 条全过\033[0m")


def run(T):
    import oplog, pickup_write as pw
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row
    有表 = c.execute("SELECT 1 FROM sqlite_master WHERE name='pickup'").fetchone()
    ck("库里有交付签收那张表(重建跑过 seed_pickup)", bool(有表))
    if not 有表: return
    # ── 不变量:过了签收的定制单,每一单都有一条试穿合身的记录 ──
    缺 = c.execute("""SELECT COUNT(*) FROM ordr o WHERE o.kind='定制品订单' AND o.status IN ('待完成','完成')
                      AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id AND p.fit_result='合身')""").fetchone()[0]
    ck("「待完成」「完成」的定制单都签收过(有试穿合身的记录)", 缺 == 0, f"缺 {缺} 单")
    晚 = c.execute("""SELECT COUNT(*) FROM pickup p JOIN ordr o ON o.id=p.order_id
                      WHERE p.fit_at > COALESCE(o.finished_at, '9999') OR p.arrived_at < o.shipped_at""").fetchone()[0]
    ck("签收不晚于完成、到店不早于发货", 晚 == 0, f"{晚} 单时间倒了")

    for m in (oplog, pw): m.DB = T
    # ── 查订单不许报假的金额异常 ──
    # 2026-09-22 签收评测:get_order 的金额自检没算定制加价,3542 张定制单张张报「勾稽异常」,
    # 模型读到就停下来让店长先核金额 —— 到店代收、转寄一件都做不下去。签收流程第一步就是查单。
    import api
    api.DB = T
    样 = [r[0] for r in c.execute("""SELECT o.id FROM ordr o JOIN ordr_item i ON i.order_id=o.id
                                    WHERE o.kind='定制品订单' AND i.custom_amount>0 GROUP BY o.id LIMIT 30""")]
    假 = [x for x in 样 if api.get_order(x).get("勾稽异常")]
    ck("定制单查订单不报假的金额异常(定制加价算进订单额)", 样 and not 假, f"抽 {len(样)} 单,报异常 {len(假)} 单")
    # ── 闸在状态机上:没带核验结果 / 没有确认完成的人,一律拒(后台改状态也走这里)──
    import fsm
    ck("状态机:已发货 → 待完成 没带核验结果 → 拒", fsm.check("bk-order", "已发货", "待完成",
       {"kind": "定制品订单"})[1] == "FIT_GATE")
    ck("状态机:调用方自称「已核验」以外的值 → 拒", fsm.check("bk-order", "已发货", "待完成",
       {"kind": "定制品订单", "试穿合身": "客户说挺好"})[1] == "FIT_GATE")
    ck("状态机:待完成 → 完成 没有顾客确认也没有追认 → 拒", fsm.check("bk-order", "待完成", "完成",
       {"kind": "定制品订单"})[1] == "COMPLETE_GATE")
    ck("状态机:标品不走这两道闸", fsm.check("bk-order", "已发货", "待完成", {"kind": "标品订单"})[0])
    # **按性质挑,不钉死编号**:一张已发货、还没登记到店的定制单
    o = c.execute("""SELECT o.id, o.shop, o.customer_id, k.phone_tail FROM ordr o JOIN customer k ON k.id=o.customer_id
                     WHERE o.kind='定制品订单' AND o.status='已发货'
                       AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id) ORDER BY o.id LIMIT 1""").fetchone()
    ck("有一张已发货、还没到店的定制单", bool(o))
    if not o: return
    人 = lambda role, 店: (lambda x: dict(x) if x else None)(c.execute(
        "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' AND shop=? ORDER BY no LIMIT 1",
        (role, 店)).fetchone())
    顾问 = 人("顾问", o["shop"])
    别店 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop<>? LIMIT 1",
                     (o["shop"],)).fetchone()
    版师 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='版师' AND status='启用' LIMIT 1").fetchone()
    状态 = lambda oid: c.execute("SELECT status FROM ordr WHERE id=?", (oid,)).fetchone()[0]
    oid, 尾 = o["id"], o["phone_tail"]

    # ── 权限 ──
    ck("没登录 → 拒", pw.arrive({"order_id": oid}, None)["code"] == "NO_LOGIN")
    ck("版师 → 拒", pw.arrive({"order_id": oid}, dict(版师))["code"] == "ROLE")
    ck("别店顾问 → 拒", pw.arrive({"order_id": oid}, dict(别店))["code"] == "OTHER_SHOP")
    标品 = c.execute("SELECT id FROM ordr WHERE kind<>'定制品订单' AND shop=? LIMIT 1", (o["shop"],)).fetchone()
    if 标品:
        ck("标品 → 不走这一套", pw.arrive({"order_id": 标品[0]}, 顾问)["code"] == "NOT_CUSTOM")
    # ── 到店、取件方式 ──
    ck("还没到店就要码 → 顾客拿不到", pw.customer_issue_code(oid, 尾)["code"] == "NOT_READY")
    r = pw.arrive({"order_id": oid}, 顾问)
    ck("已发货的定制单 → 登记到店代收", r["ok"], r.get("reason"))
    ck("代收人记的是登录的人", c.execute("SELECT received_by FROM pickup WHERE order_id=?", (oid,)).fetchone()[0] == 顾问["no"])
    ck("转寄不写物流单号 → 拒", pw.set_mode({"order_id": oid, "mode": "转寄"}, 顾问)["code"] == "NO_TRACKING")
    ck("转寄写了单号 → 行", pw.set_mode({"order_id": oid, "mode": "转寄", "tracking_no": "SF123"}, 顾问)["ok"])
    # ── 码 ──
    ck("手机后四位对不上 → 拿不到码", pw.customer_issue_code(oid, "0000" if 尾 != "0000" else "1111")["code"] == "NOT_YOURS")
    r = pw.customer_issue_code(oid, 尾)
    码 = r.get("试穿合身码")
    ck("顾客点试穿合身 → 拿到 6 位码", bool(码) and len(码) == 6, r.get("reason"))
    ck("库里只存哈希,不存明文", not c.execute("SELECT 1 FROM fit_code WHERE code_hash LIKE ?", (f"%{码}%",)).fetchone()
       and not c.execute("SELECT 1 FROM op_log WHERE reason LIKE ? OR ctx LIKE ?", (f"%{码}%", f"%{码}%")).fetchone())
    错 = "000000" if 码 != "000000" else "111111"
    r = pw.verify({"order_id": oid, "code": 错}, 顾问)
    ck("错的码 → 不签收", not r["ok"] and 状态(oid) == "已发货", r.get("reason"))
    ck("输错一次记下来", c.execute("SELECT tries FROM fit_code WHERE order_id=? ORDER BY rowid DESC", (oid,)).fetchone()[0] == 1)
    # ── 不合身:不算签收 ──
    r = pw.not_fit({"order_id": oid, "issue": "腰围紧 2cm", "matches_record": True, "other_defect": False}, 顾问)
    ck("不合身 → 订单状态不动", r["ok"] and 状态(oid) == "已发货", r.get("reason"))
    ck("不合身 → 给判责建议(数据对得上、没别的瑕疵 → 顾客)", r.get("判责建议") == "顾客")
    ck("不合身不写说明 → 拒", pw.not_fit({"order_id": oid}, 顾问)["code"] == "NO_ISSUE")
    # 改完再试:顾客重新拿码
    码 = pw.customer_issue_code(oid, 尾)["试穿合身码"]
    r = pw.verify({"order_id": oid, "code": 码[:3] + " " + 码[3:]}, 顾问)
    ck("对的码 → 签收,订单进待完成", r["ok"] and 状态(oid) == "待完成", r.get("reason"))
    p = dict(c.execute("SELECT * FROM pickup WHERE order_id=?", (oid,)).fetchone())
    ck("签收记下核验人和时间,结果是合身", p["fit_result"] == "合身" and p["fit_verified_by"] == 顾问["no"] and p["fit_at"])
    ck("同一个码不能再用", not pw.verify({"order_id": oid, "code": 码}, 顾问)["ok"])
    # ── 完成 ──
    r = pw.ratify({"order_id": oid, "reason": "打过电话"}, 顾问)
    ck("签收不满 15 天 → 不许追认", not r["ok"] and 状态(oid) == "待完成", r.get("reason"))
    r = pw.customer_complete(oid, 尾)
    ck("顾客确认完成 → 完成", r["ok"] and 状态(oid) == "完成", r.get("reason"))
    ck("完成人记的是顾客", c.execute("SELECT complete_by FROM pickup WHERE order_id=?", (oid,)).fetchone()[0] == "顾客")
    # 追认:挑一张签收满 15 天的待完成单
    q = c.execute("""SELECT o.id, o.shop FROM ordr o JOIN pickup p ON p.order_id=o.id
                     WHERE o.kind='定制品订单' AND o.status='待完成' AND p.fit_at <= ? ORDER BY o.id LIMIT 1""",
                  ((datetime.datetime.now() - datetime.timedelta(days=16)).strftime("%Y-%m-%d %H:%M"),)).fetchone()
    ck("有一张签收满 15 天还没完成的单", bool(q))
    if q:
        店顾问 = 人("顾问", q["shop"])
        ck("追认不写理由 → 拒", pw.ratify({"order_id": q["id"], "reason": " "}, 店顾问)["code"] == "NO_RATIFY")
        r = pw.ratify({"order_id": q["id"], "reason": "已电话联系,顾客表示没问题"}, 店顾问)
        ck("满 15 天、写了理由 → 追认完成", r["ok"] and 状态(q["id"]) == "完成", r.get("reason"))
        ck("追认记下理由和「顾问追认」", c.execute("SELECT complete_by, ratify_note FROM pickup WHERE order_id=?",
                                                    (q["id"],)).fetchone()[0] == "顾问追认")


if __name__ == "__main__":
    main()
