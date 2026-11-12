#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户归属保护期 · 跨店成交转不转(用户 2026-11-11 拍:180 天;原店消费或原导购跟进算维护;过期转给接待导购并知会;历史不管)。

① 口径(knowledge/ownership_protection)逐例边界真值 —— 期望值手写,不拿被测代码算
② 收口(backend/ownership_transfer.成交后)在**库副本**上真跑一次转移:整户改了、三条知会派了
③ 接线:两个付款入口(定制单确认下单 / 订单从「待付款」流转出去)都调它,而且在原事务之外
"""
import datetime as _dt
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
import ownership_protection as OP      # noqa: E402

咬合 = [
    ("保护期边界改成「满 180 天就转」(第 180 天也转)", "第 180 天成交:还在保护期,不转"),
    ("定制单确认下单后不再判归属", "接线:定制单确认下单之后判归属(事务之外)"),
    ("没知会过也直接释放(上线第一天一批老客一夜被收走)", "过了 180 天但没知会过:先知会,不直接放"),
    ("已预约不算接触(客户约了下周来,这周被收走)", "公海 · 约在未来的已预约算接触:不动"),
    ("释放到公海不记归属变更日志(「凭什么不是他的了」答不上)", "公海 · 释放落地:导购置空 + 日志记「进公海」+ 给店长派「公海指派」"),
]
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def main():
    print("\n\033[1m▸ 客户归属保护期 · 跨店成交转不转\033[0m")
    基 = _dt.date(2026, 1, 1); 天 = lambda n: 基 + _dt.timedelta(days=n)
    ck("第 180 天成交:还在保护期,不转", OP.该转吗("A", "B", "x", "y", 基, 天(180))["转"] is False)
    # ── 长期没接触 → 释放到公海(台账第十四条:180 天、提前 7 天知会)—— 期望值手算 ──
    放 = lambda 维, 今, 知=None: OP.该放吗(维, 今, 知)["动作"]
    ck("最后接触后第 172 天:不动", 放("2026-05-24", "2026-11-12") == "不动")
    ck("第 173 天起:知会原导购", 放("2026-05-23", "2026-11-12") == "知会")
    ck("过了 180 天但没知会过:先知会,不直接放", 放("2026-05-01", "2026-11-12") == "知会")
    ck("知会后不满 7 天:不动", 放("2026-05-01", "2026-11-12", "2026-11-08") == "不动")
    ck("知会满 7 天、过第 180 天、其间没新接触:释放", 放("2026-05-01", "2026-11-12", "2026-11-05") == "释放")
    ck("第 180 天当天(已知会满 7 天):仍不放,第 181 天才放", 放("2026-05-16", "2026-11-12", "2026-11-01") == "不动"
       and 放("2026-05-15", "2026-11-12", "2026-11-01") == "释放")
    ck("知会之后又有了新接触(知会日早于最后接触):重新算,先知会", 放("2026-05-01", "2026-11-12", "2026-04-20") == "知会")
    ck("最后接触判不出:不放", 放(None, "2026-11-12") == "不动")
    ck("第 181 天成交:过了保护期,转给接待导购", OP.该转吗("A", "B", "x", "y", 基, 天(181))["转"] is True)
    ck("同店成交:不转(不是跨店)", OP.该转吗("A", "A", "x", "y", 基, 天(400))["转"] is False)
    ck("接待导购就是原导购:不转", OP.该转吗("A", "B", "x", "x", 基, 天(400))["转"] is False)
    ck("最后维护判不出来:不转(拿不准不动别人的客户)", OP.该转吗("A", "B", "x", "y", None, 天(400))["转"] is False)
    r = OP.该转吗("A", "B", "x", None, 基, 天(400))
    ck("过了保护期但没有接待导购:不转,要新店店长指定导购", r["转"] is False and r["要指定导购"] is True, r)
    d, 类 = OP.最后维护日(["2026-03-01"], ["2026-05-02 10:00"], ["2026-04-01"], "2025-01-01")
    ck("最后维护取三类里最晚的(原导购跟进 05-02)", d == _dt.date(2026, 5, 2) and 类 == "原导购跟进", (d, 类))
    d, 类 = OP.最后维护日([], [], [], "2025-06-01")
    ck("三类都没有 → 从建档日起算", d == _dt.date(2025, 6, 1) and 类 == "建档", (d, 类))

    # ② 库副本上真跑
    import ownership_transfer as OT
    with tempfile.TemporaryDirectory() as td:
        副本 = os.path.join(td, "o.db")
        src = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); dst = sqlite3.connect(副本)
        src.backup(dst); src.close()
        c = dst
        # ⚠️ **夹具自己造,不靠造数碰巧造出来**(11-12 改):原来在库里找「跨店、过了保护期」的已付款单,
        # 而 CI 每天从零建库、世界时钟每天挪 —— 11-12 那天一张都没挑到,CI 红在「夹具找不到」,
        # 而那不是保护期的逻辑坏了。和 alert_dispatch_check 一样:自己造一位建档一年多、一次维护都没有的老客户,
        # 让她在另一家店付款成交。
        两店 = c.execute("SELECT a.shop, a.no, b.shop, b.no FROM staff a JOIN staff b ON a.shop<>b.shop "
                        "WHERE a.role='顾问' AND a.status='启用' AND b.role='顾问' AND b.status='启用' "
                        "AND a.shop IN (SELECT shop FROM staff WHERE role='店长' AND status='启用') "
                        "AND b.shop IN (SELECT shop FROM staff WHERE role='店长' AND status='启用') LIMIT 1").fetchone()
        单 = None
        if 两店:
            原店, 原导购, 新店, 接待 = 两店
            c.execute("INSERT INTO customer(id, name, shop, advisor_no, created, phone) VALUES(?,?,?,?,?,?)",
                      ("C99000001", "保护期检查", 原店, 原导购, "2025-06-01", "19900000001"))
            c.execute("INSERT INTO ordr(id, kind, status, shop, customer_id, advisor_no, payable, paid_at, created) "
                      "VALUES(?,?,?,?,?,?,?,?,?)", ("CHKOWN1", "标品订单", "待发货", 新店, "C99000001", 接待, 500,
                                                   "2026-11-11 10:00", "2026-11-11 09:00"))
            c.commit()
            r, _ = OT.判定(c, "CHKOWN1", "2026-11-11")
            单 = "CHKOWN1" if r["转"] else None
        ck("夹具:库里找得到一张「跨店、过了保护期」的已付款单", bool(单), (两店, 单))
        if 单:
            n0 = c.execute("SELECT COUNT(*) FROM schedule WHERE type='归属转移'").fetchone()[0]
            with c:
                出 = OT.成交后(c, 单, "2026-11-11", "检查")
            现 = c.execute("SELECT shop, advisor_no FROM customer WHERE id=?", (出["客户"],)).fetchone()
            ck("转了:整户改到成交店 + 接待导购", 出["转了吗"] and 现 == (出["成交店"], 出["接待导购"]), (出.get("理由"), 现))
            n1 = c.execute("SELECT COUNT(*) FROM schedule WHERE type='归属转移'").fetchone()[0]
            ck("派了知会:原导购 + 原店店长 + 新店店长(在职的都派)", n1 - n0 == len(出.get("知会任务") or []) >= 2, (n0, n1, 出.get("知会任务")))

        # ②b 长期没接触 → 知会 → 满 7 天 → 释放(台账第十四条),同一份副本上真走一遍落地。夹具自己造。
        import ownership_release as ORL
        if 两店:
            原店, 原导购 = 两店[0], 两店[1]
            for cid, 号 in (("C99000002", "19900000002"), ("C99000003", "19900000003"), ("C99000004", "19900000004")):
                c.execute("INSERT INTO customer(id, name, shop, advisor_no, created, phone) VALUES(?,?,?,?,?,?)",
                          (cid, "公海检查", 原店, 原导购, "2025-01-01", 号))
            c.execute("INSERT INTO appointment(id, customer_id, shop, advisor_no, start_ts, status) VALUES(?,?,?,?,?,?)",
                      ("APCHKPOOL", "C99000004", 原店, 原导购, "2026-11-20 10:00", "已预约"))
            c.commit()
            d0, d3, d8 = "2026-11-12", "2026-11-15", "2026-11-20"
            r = ORL.判一户(c, "C99000002", d0)
            ck("公海 · 建档快两年、一次接触都没有:今天先知会", r["动作"] == "知会", r)
            ck("公海 · 约在未来的已预约算接触:不动", ORL.判一户(c, "C99000004", d0)["动作"] == "不动",
               ORL.判一户(c, "C99000004", d0))
            with c:
                出 = ORL.执行(c, d0, "检查", 行们=[r, ORL.判一户(c, "C99000003", d0)])
            任务 = c.execute("SELECT assignee_no, customer_id FROM schedule WHERE type='公海知会' AND customer_id IN "
                             "('C99000002','C99000003')").fetchall()
            ck("公海 · 知会落地:给原导购派了「公海知会」任务(两户各一条)",
               len(出["知会"]) == 2 and sorted(任务) == [(原导购, "C99000002"), (原导购, "C99000003")], (出, 任务))
            ck("公海 · 知会当天再扫:不动(没满 7 天)", ORL.判一户(c, "C99000002", d0)["动作"] == "不动")
            # 原导购第 3 天联系了 C99000003 并登记跟进 → 最后接触刷新 → 第 8 天不放
            c.execute("INSERT INTO followup(id, customer_id, ts, channel, content, advisor_no) VALUES(?,?,?,?,?,?)",
                      ("FUCHKPOOL", "C99000003", f"{d3} 15:00", "电话", "回访", 原导购))
            c.commit()
            ck("公海 · 知会后原导购登记了跟进:第 8 天不放", ORL.判一户(c, "C99000003", d8)["动作"] == "不动",
               ORL.判一户(c, "C99000003", d8))
            r8 = ORL.判一户(c, "C99000002", d8)
            ck("公海 · 知会满 7 天仍没接触:释放", r8["动作"] == "释放", r8)
            with c:
                出 = ORL.执行(c, d8, "检查", 行们=[r8])
            现 = c.execute("SELECT advisor_no FROM customer WHERE id='C99000002'").fetchone()[0]
            日志 = c.execute("SELECT frm, too, action, basis FROM cust_owner_log WHERE customer_id='C99000002'").fetchall()
            指派 = c.execute("SELECT COUNT(*) FROM schedule WHERE type='公海指派' AND customer_id='C99000002'").fetchone()[0]
            ck("公海 · 释放落地:导购置空 + 日志记「进公海」+ 给店长派「公海指派」",
               现 is None and 日志 == [(原导购, None, "进公海", ORL.释放依据)] and 指派 == 1 and 出["释放"] == ["C99000002"],
               (现, 日志, 指派, 出))
            import ownership
            ck("公海 · 释放依据是登记过的归属依据", ORL.释放依据 in ownership.依据)
        dst.close()

    # ③ 接线
    ow = open(os.path.join(HERE, "order_write.py"), encoding="utf-8").read()
    i确认 = ow.index("UPDATE ordr SET status='待审核'")
    ck("接线:定制单确认下单之后判归属(事务之外)", "_ot.成交后(" in ow[i确认:] and "_ot.记日志(" in ow[i确认:])
    sv = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    ck("接线:订单从「待付款」流转出去之后判归属(事务之外)",
       'if cur=="待付款" and to not in ("取消",):' in sv and "_ot.成交后(c, _付款单" in sv)
    import tasktypes
    ck("「归属转移」是登记过的任务类型", "归属转移" in tasktypes.BY_NAME)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 客户归属保护期:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
