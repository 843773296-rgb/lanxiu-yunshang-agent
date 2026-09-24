#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报修写口的检查 —— 在库的**临时副本**上跑,真库一行都不碰(同 pickup_write_check)。

钉的几件事(业务 2026-09-22):
    哪一件   一张单好几件而没说哪件 → 反问,不挑第一件
    判责     只有店长能判;判给顾客的没录费用 / 没同意 → 停在待确认;同意要写凭据
    状态机   没判完不许进待入库;没核验顾客的码不许进已完成(后台绕不过)
    推进     一次一档;待签收不给推成已完成
    回店签收 顾客手机后四位对不上拿不到码;码对了才完成
    判责建议 签收时确认过合身 → 尺寸问题建议顾客承担;没有下单量体 → 记录缺失(我方),不拿别的量体顶
    不合身   交付签收登记不合身时,自动建一张返修单(来源:签收不合身)
"""
import os, sys, shutil, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("让 _找件() 在没说哪一件时挑第一件", "一张单好几件、没说哪件 → 反问"),
    ("把金额授权那一档去掉(谁能拍板 一律返回店长)", "我方出 1200、没总部批 → 停在待确认"),
    ("让 decide() 不查顾客同意就放进待入库", "判给顾客、没同意 → 停在待确认"),
    ("去掉状态机上的返修开工闸", "状态机:没判完 → 拒"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:140]) if extra else ''}")
    if not ok: FAIL.append(name)


def main():
    print("报修写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="repw-")
    T = os.path.join(tmp, "lanxiu.db")
    src = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); dst = sqlite3.connect(T)
    src.backup(dst); src.close(); dst.close()
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 报修写口 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 报修写口 {N[0]} 条全过\033[0m")


def run(T):
    import oplog, repair_write as rw, pickup_write as pw, fsm, seed_repair
    for m in (oplog, rw, pw): m.DB = T
    seed_repair.main(T)
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row
    状 = lambda mid: c.execute("SELECT status FROM maintain WHERE id=?", (mid,)).fetchone()[0]
    # ── 状态机的两道闸 ──
    ck("状态机:没判完 → 拒", fsm.check("bk-maintain", "待确认", "待入库", {})[1] == "REPAIR_GATE")
    ck("状态机:没核验顾客的码 → 不许完成", fsm.check("bk-maintain", "待签收", "已完成", {})[1] == "REPAIR_FIT_GATE")
    ck("状态机:判完了 → 放行", fsm.check("bk-maintain", "待确认", "待入库", {"判完了": True})[0])
    # ── 挑单:一张单一件、一张单多件,同一家店 ──
    for shop in [r[0] for r in c.execute("SELECT DISTINCT shop FROM staff WHERE role='店长' AND status='启用'")]:
        一件 = c.execute("""SELECT o.id, o.customer_id FROM ordr o WHERE o.shop=? AND o.kind='定制品订单' AND o.status='完成'
                           AND (SELECT COUNT(*) FROM ordr_item i WHERE i.order_id=o.id)=1 ORDER BY o.id LIMIT 1""", (shop,)).fetchone()
        多件 = c.execute("""SELECT o.id FROM ordr o WHERE o.shop=? AND o.kind='定制品订单'
                           AND (SELECT COUNT(*) FROM ordr_item i WHERE i.order_id=o.id)>=2 ORDER BY o.id LIMIT 1""", (shop,)).fetchone()
        if 一件 and 多件:
            break
    ck("有一张一件的完成单、一张多件的单(同一家店)", bool(一件 and 多件))
    if not (一件 and 多件): return
    人 = lambda role: dict(c.execute("SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' AND shop=? "
                                    "ORDER BY no LIMIT 1", (role, shop)).fetchone())
    顾问, 店长 = 人("顾问"), 人("店长")
    版师 = dict(c.execute("SELECT no,name,role,shop FROM staff WHERE role='版师' AND status='启用' LIMIT 1").fetchone())
    # ── 新建 ──
    ck("版师 → 不能报修", rw.create({"order_id": 一件["id"], "issue": "下摆开线"}, 版师)["code"] == "ROLE")
    r = rw.create({"order_id": 多件["id"], "issue": "下摆开线"}, 顾问)
    ck("一张单好几件、没说哪件 → 反问", r["code"] == "WHICH_ITEM", r.get("reason"))
    r = rw.create({"order_id": 一件["id"], "issue": "下摆开线"}, 顾问)
    ck("一件的单 → 建返修单,停在待确认", r["ok"] and 状(r["返修单"]) == "待确认", r.get("reason"))
    ck("工艺瑕疵 → 建议企业承担", r["判责建议"]["建议责任方"] == "企业", r["判责建议"])
    修 = r["返修单"]
    # ── 判责 ──
    ck("顾问 → 不能判责", rw.decide({"maintain_id": 修, "liable": "企业", "plan": "返修"}, 顾问)["code"] == "ROLE")
    r = rw.decide({"maintain_id": 修, "liable": "顾客", "plan": "返修"}, 店长)
    ck("判给顾客、没录费用 → 停在待确认", r["ok"] and 状(修) == "待确认", r.get("reason"))
    r = rw.decide({"maintain_id": 修, "liable": "顾客", "plan": "返修", "fee_est": 300}, 店长)
    ck("判给顾客、没同意 → 停在待确认", r["ok"] and 状(修) == "待确认", r.get("reason"))
    ck("记顾客同意不写凭据 → 拒", rw.decide({"maintain_id": 修, "liable": "顾客", "plan": "返修", "fee_est": 300,
                                             "customer_agreed": True}, 店长)["code"] == "NO_AGREE_NOTE")
    r = rw.decide({"maintain_id": 修, "liable": "顾客", "plan": "返修", "fee_est": 300,
                   "customer_agreed": True, "agree_note": "顾客电话同意 300 元"}, 店长)
    ck("判给顾客、录了费用、同意有凭据 → 进待入库", r["ok"] and 状(修) == "待入库", r.get("reason"))
    # ── 金额授权(业务 2026-09-24:管的是**我方要出的钱**)────────────────────
    # 挑另一张单来验 —— 上面那张已经判完进了待入库,授权闸只在「待确认」这一步上
    另 = c.execute("""SELECT o.id FROM ordr o WHERE o.shop=? AND o.kind='定制品订单' AND o.status='完成'
                     AND (SELECT COUNT(*) FROM ordr_item i WHERE i.order_id=o.id)=1
                     AND o.id<>? ORDER BY o.id LIMIT 1""", (shop, 一件["id"])).fetchone()
    ck("有第二张完成单(验金额授权用)", bool(另))
    if 另:
        r2 = rw.create({"order_id": 另[0], "issue": "下摆开线"}, 顾问)
        授 = r2.get("返修单")
        ck("建第二张返修单", bool(授), r2.get("reason"))
        r = rw.decide({"maintain_id": 授, "liable": "企业", "plan": "返修", "fee_est": 800}, 店长)
        ck("我方出 800(≤1000)→ 店长直接定,进待入库", r["ok"] and 状(授) == "待入库", r.get("reason"))
        r3 = rw.create({"order_id": 另[0], "issue": "袖口脱线"}, 顾问)
        授2 = r3.get("返修单")
        r = rw.decide({"maintain_id": 授2, "liable": "企业", "plan": "重做", "fee_est": 1200}, 店长)
        ck("我方出 1200、没总部批 → 停在待确认", r["ok"] and 状(授2) == "待确认", r.get("reason"))
        ck("说清了要报总部", "总部" in str(r.get("reason") or ""), r.get("reason"))
        r = rw.decide({"maintain_id": 授2, "liable": "企业", "plan": "重做", "fee_est": 1200,
                       "approved_by": 店长["no"], "approve_note": "总部批了 1200"}, 店长)
        ck("批准人就是判责的店长自己 → 拒", r.get("code") == "SELF_APPROVE", r.get("reason"))
        总部 = c.execute("SELECT no FROM staff WHERE role='总部运营' AND status='启用' LIMIT 1").fetchone()
        if 总部:
            r = rw.decide({"maintain_id": 授2, "liable": "企业", "plan": "重做", "fee_est": 1200,
                           "approved_by": 总部[0]}, 店长)
            ck("批了却没写批准说明 → 拒", r.get("code") == "NO_APPROVE_NOTE", r.get("reason"))
            r = rw.decide({"maintain_id": 授2, "liable": "企业", "plan": "重做", "fee_est": 1200,
                           "approved_by": 总部[0], "approve_note": "总部王工 09-24 批 1200"}, 店长)
            ck("总部批了、写了说明 → 进待入库", r["ok"] and 状(授2) == "待入库", r.get("reason"))
        r4 = rw.create({"order_id": 另[0], "issue": "前襟开线"}, 顾问)
        授3 = r4.get("返修单")
        r = rw.decide({"maintain_id": 授3, "liable": "企业", "plan": "重做", "fee_est": 6000,
                       "approved_by": (总部[0] if 总部 else "x"), "approve_note": "批了"}, 店长)
        ck("我方出 6000(>5000)→ 走专项,批了也不许在这儿定", r["ok"] and 状(授3) == "待确认", r.get("reason"))
        ck("说清了走专项", "专项" in str(r.get("reason") or ""), r.get("reason"))
        r = rw.decide({"maintain_id": 授3, "liable": "顾客", "plan": "返修", "fee_est": 6000,
                       "customer_agreed": True, "agree_note": "顾客同意 6000"}, 店长)
        ck("同样 6000 但判给顾客 → 不受授权档管(那是收顾客的钱)", r["ok"] and 状(授3) == "待入库", r.get("reason"))

    # ── 推进 ──
    for 到 in ("待处理", "处理中", "待签收"):
        r = rw.advance({"maintain_id": 修}, 顾问)
        ck(f"推进一档 → {到}", r["ok"] and 状(修) == 到, r.get("reason"))
    ck("待签收 → 不给推成已完成(要顾客输码)", rw.advance({"maintain_id": 修}, 顾问)["code"] == "BAD_STATE")
    # ── 回店签收 ──
    尾 = c.execute("SELECT phone_tail FROM customer WHERE id=?", (一件["customer_id"],)).fetchone()[0]
    ck("手机后四位对不上 → 拿不到码", rw.customer_issue_code(修, "0000" if 尾 != "0000" else "1111")["code"] == "NOT_YOURS")
    码 = rw.customer_issue_code(修, 尾).get("试穿合身码")
    ck("顾客领到 6 位码", bool(码) and len(码) == 6)
    ck("错的码 → 不完成", not rw.verify_return({"maintain_id": 修, "code": "000000" if 码 != "000000" else "111111"}, 顾问)["ok"]
       and 状(修) == "待签收")
    r = rw.verify_return({"maintain_id": 修, "code": 码}, 顾问)
    ck("对的码 → 已完成", r["ok"] and 状(修) == "已完成", r.get("reason"))
    # ── 判责建议 ──
    签 = c.execute("SELECT fit_result FROM pickup WHERE order_id=?", (一件["id"],)).fetchone()
    r = rw.create({"order_id": 一件["id"], "issue": "尺寸需调整"}, 顾问)
    if 签 and 签[0] == "合身":
        ck("签收时确认过合身 → 尺寸问题建议顾客承担", r["判责建议"]["建议责任方"] == "顾客", r["判责建议"])
    缺 = c.execute("""SELECT i.order_id, i.id FROM ordr_item i JOIN ordr o ON o.id=i.order_id
                     WHERE o.kind='定制品订单' AND o.shop=? AND i.wearer_id IS NOT NULL
                       AND NOT EXISTS(SELECT 1 FROM measure_rec m WHERE m.order_item_id=i.id)
                       AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id AND p.fit_result='合身')
                     LIMIT 1""", (shop,)).fetchone()
    if 缺:
        r = rw.create({"order_id": 缺[0], "item": str(缺[1]), "issue": "尺寸需调整"}, 顾问)
        ck("没有下单量体 → 记录缺失,建议企业承担(不拿别的量体顶)", r.get("判责建议", {}).get("建议责任方") == "企业",
           r.get("判责建议") or r.get("reason"))
    # ── 签收不合身 → 自动建返修单 ──
    到店 = c.execute("""SELECT o.id FROM ordr o JOIN pickup p ON p.order_id=o.id WHERE o.shop=? AND o.status='已发货'
                       AND p.fit_result IS NULL AND (SELECT COUNT(*) FROM ordr_item i WHERE i.order_id=o.id)=1
                       ORDER BY o.id LIMIT 1""", (shop,)).fetchone()
    if 到店:
        r = pw.not_fit({"order_id": 到店[0], "issue": "腰围紧 2cm"}, 顾问)
        ck("签收登记不合身 → 自动建返修单(来源:签收不合身)", bool(r.get("返修单")) and c.execute(
            "SELECT source FROM maintain_decision WHERE maintain_id=?", (r.get("返修单"),)).fetchone()[0] == "签收不合身",
           r.get("返修单没建成"))


if __name__ == "__main__":
    main()
