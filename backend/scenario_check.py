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
# 场景三的两条咬合在 tools/bite_specs.json(「经营改进不核报告确认没有」「下期报告不回看上期行动」)


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
import tasks as TK, report_doc as RD, tasktypes   # noqa: E401 —— 场景三;同样要在用副本之前加载
import repair_write as rw, ops   # noqa: E401 —— 场景二要用;**必须在用副本之前加载**,否则它们的 DB 还指着真库
                                 # (10-21 第一版就是在用副本之后才 import,两张测试维修单写进了真库,已删)
import check_copy
db = check_copy.用副本("scenario-")
_没切 = [m.__name__ for m in (api, ow, mw, SV, rw, ops, TK, RD) if getattr(m, "DB", db) != db]
if _没切:
    print(f"{R}❌ 这几个写口没指到副本,拒绝往下跑(会写进真库):{_没切}{D}"); sys.exit(1)
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

# ══ 场景二:交付出问题到实际解决(外部复审第 7 节场景二)═══════════════════════════════
# 顾客报问题 → 顾问开返修单 → 研判(售后判责)由售后复核 → 店长判责 → 推进 → 顾客凭码回店签收 → 研判凭这张维保单办结
# 要对得上:返修单挂着原订单和原客户;「已判责」和「已执行」分得开(判完只到待入库,签收才完成);
#          返修没完成时研判办结不了,完成之后凭它办结,回执就是这张维保单
print("\n  ── 场景二 · 交付出问题到实际解决 ──")
单2 = 店2 = None
for 店名 in [r[0] for r in c.execute("SELECT DISTINCT shop FROM staff WHERE role='店长' AND status='启用'")]:
    单2 = c.execute("""SELECT o.id, o.customer_id FROM ordr o WHERE o.shop=? AND o.kind='定制品订单' AND o.status='完成'
                      AND (SELECT COUNT(*) FROM ordr_item i WHERE i.order_id=o.id)=1 ORDER BY o.id LIMIT 1""", (店名,)).fetchone()
    if 单2 and c.execute("SELECT 1 FROM staff WHERE role='顾问' AND status='启用' AND shop=?", (店名,)).fetchone():
        店2 = 店名; break
售后 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='售后' AND status='启用' ORDER BY no LIMIT 1").fetchone()
if not (单2 and 店2 and 售后):
    ck("夹具:有一张一件的完成单(同店有店长、顾问)、有在职售后 —— 挑不到就没验,不算通过", False,
       dict(单=bool(单2), 店=店2, 售后=bool(售后)))
else:
    人2 = lambda role: dict(c.execute("SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' AND shop=? "
                                      "ORDER BY no LIMIT 1", (role, 店2)).fetchone())
    顾问2, 店长2, 售后 = 人2("顾问"), 人2("店长"), dict(售后)
    状 = lambda mid: c.execute("SELECT status FROM maintain WHERE id=?", (mid,)).fetchone()[0]
    r = rw.create({"order_id": 单2["id"], "issue": "下摆开线"}, 顾问2)
    修 = r.get("返修单")
    维 = dict(c.execute("SELECT * FROM maintain WHERE id=?", (修,)).fetchone() or {}) if 修 else {}
    ck("① 返修单开出来了,挂着原订单和原客户", r.get("ok") and 维.get("order_id") == 单2["id"]
       and 维.get("customer_id") == 单2["customer_id"], (r.get("reason"), 维.get("order_id"), 维.get("customer_id")))
    # 研判这件事:售后判责,挂这张维保单;售后复核采纳
    c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES('T-场景2','售后判责',?,'待处理',?,'场景回归')",
              (修, ops._now() if hasattr(ops, "_now") else "2026-01-01 10:00:00")); c.commit()
    tid = ops.save_triage("T-场景2", "BP-03", 修, "根因:下摆开线\n建议动作:返修\n证据:维保单", [])
    ops.resolve(tid, "已采纳", 售后, 来源="场景回归")
    早 = ops.办结(tid, 修, 售后, 来源="场景回归")
    ck("② 返修还没做完时,研判办结不了(回执要那张维保单真完成)", 早.get("code") == "NO_RECEIPT", 早)
    r = rw.decide({"maintain_id": 修, "liable": "企业", "plan": "返修"}, 店长2)
    ck("③ 店长判责之后只到待入库 —— 「判了」不等于「做了」", r.get("ok") and 状(修) == "待入库", (r.get("reason"), 状(修)))
    for _ in range(3):
        rw.advance({"maintain_id": 修}, 顾问2)
    尾 = c.execute("SELECT phone_tail FROM customer WHERE id=?", (单2["customer_id"],)).fetchone()[0]
    码 = rw.customer_issue_code(修, 尾).get("试穿合身码")
    r = rw.verify_return({"maintain_id": 修, "code": 码}, 顾问2)
    ck("④ 推进到待签收、顾客凭码回店签收 → 已完成", r.get("ok") and 状(修) == "已完成", (r.get("reason"), 状(修)))
    r = ops.办结(tid, 修, 售后, 来源="场景回归")
    回 = c.execute("SELECT receipt, receipt_kind FROM triage WHERE id=?", (tid,)).fetchone()
    ck("⑤ 返修完成之后,研判凭这张维保单办结,回执就是它", r.get("ok") and tuple(回 or ()) == (修, "维保单"), (r, 回))

# ══ 场景三:经营复盘到下期结果(复审第 7 节;用户 10-21 拍「补最小闭环」)══════════════════════
#   店长取上期周报的数 → 存草稿 → 照草稿定行动 → 拒(数还会改)→ 确认 → 定一条「经营改进」、点名盯「订单」
#   → 顾问做完 → 下一期周报回看:谁负责、做完没有、盯的那一项上期 / 这期各多少,**两期的数都对得上各自的取数**
#   而且**不给「起没起作用」的结论**(相关不是因果)
print("\n业务场景回归 · 经营复盘到下期结果(定的行动下一期回看得到)")
print("=" * 80)
店3 = c.execute("""SELECT s.shop FROM staff s WHERE s.role='店长' AND s.status='启用'
                   AND EXISTS(SELECT 1 FROM staff x WHERE x.role='顾问' AND x.status='启用' AND x.shop=s.shop)
                   ORDER BY s.shop LIMIT 1""").fetchone()
店长3 = dict(c.execute("SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用' AND shop=? ORDER BY no LIMIT 1",
                      (店3[0],)).fetchone()) if 店3 else None
顾问3 = dict(c.execute("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop=? ORDER BY no LIMIT 1",
                      (店3[0],)).fetchone()) if 店3 else None
if not (店长3 and 顾问3):
    ck("夹具:有一家店同时有在职店长和顾问 —— 挑不到就没验,不算通过", False)
else:
    import datetime as _dt3
    with api.as_user(店长3):
        本包 = api.store_report(kind="周")                         # 本期 = 上一个完整周
        本起 = _dt3.date.fromisoformat(本包["区间"][:10])
        上包 = api.store_report(kind="周", date=(本起 - _dt3.timedelta(days=7)).isoformat())
    存 = RD.保存(店长3, 上包, f"场景回归 · {上包['区间']} 周报", db=db)
    rid = 存.get("报告号")
    派 = lambda **k: TK.assign_task(dict(dict(type="经营改进", assignee_no=顾问3["no"], ref_id=rid,
                                              note="场景回归:下周把待付款的单逐个电话催一遍", end="2099-01-01 18:00"), **k), 店长3)
    r = 派(metric="订单")
    ck("① 照**草稿**定行动 → 拒(草稿里的数还会改,下一期回看会对着一个没定稿的数)",
       not r.get("ok") and r.get("code") == "BAD_REF" and "还没确认" in (r.get("reason") or ""), r)
    确 = RD.确认(店长3, rid, db=db)
    r0 = 派()
    ck("② 报告确认后,不点名盯哪一项 → 拒,并列出这份报告里有数的项",
       确.get("ok") and r0.get("code") == "NEED_METRIC" and "订单" in (r0.get("reason") or ""), (确.get("reason"), r0))
    r1 = 派(metric="10 月底前把订单提上去")
    ck("②b 盯的那一项写成自由文本 → 拒(只收报告里的指标名;这张表不进每日平移登记,靠的就是这一列写不进日期)",
       r1.get("code") == "NEED_METRIC", r1)
    r = 派(metric="订单")
    sid = r.get("id")
    挂 = c.execute("SELECT report_id, metric FROM report_action WHERE schedule_id=?", (sid,)).fetchone() if sid else None
    ck("③ 定下一条「经营改进」:挂着这份报告、盯「订单」", r.get("ok") and tuple(挂 or ()) == (rid, "订单"), (r, 挂))

    def 回看():
        with api.as_user(店长3):
            行 = (api.store_report(kind="周").get("上期定的行动") or {}).get("行动") or []
        return next((x for x in 行 if x.get("任务") == sid), None), 行
    看, _ = 回看()
    ck("④ 下一期周报回看得到它:负责人、还没做完", bool(看) and 看["负责人"] == 顾问3["name"] and 看["做完了"] is False, 看)
    r = TK.finish_task(dict(id=sid, summary="场景回归:待付款的单都打过电话了"), 顾问3)
    看, 全 = 回看()
    ck("⑤ 顾问做完之后,回看里显示做完了", r.get("ok") and bool(看) and 看["做完了"] is True, (r.get("reason"), 看))
    ck("⑥ 盯的那一项:上期的数 = 上期报告冻结的数,这期的数 = 这期现取的数",
       bool(看) and 看["上期的数"] == 上包["期内"]["订单"]["值"] and 看["这期的数"] == 本包["期内"]["订单"]["值"]
       and 看["上期的数"] is not None, 看)
    ck("⑦ 不给「起没起作用」的结论(做完了 + 数变了 ≠ 这条行动的功劳)",
       bool(看) and not any(k for k in 看 if any(w in k for w in ("有效", "作用", "功劳", "结论"))), list(看 or {}))
c.close()

print()
if 坏:
    print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 场景一 · 接待到下单 / 场景二 · 交付出问题到解决 / 场景三 · 经营复盘到下期结果:一路对得上(验了 {n} 条){D}")
