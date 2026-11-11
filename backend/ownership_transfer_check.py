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
]
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def main():
    print("\n\033[1m▸ 客户归属保护期 · 跨店成交转不转\033[0m")
    基 = _dt.date(2026, 1, 1); 天 = lambda n: 基 + _dt.timedelta(days=n)
    ck("第 180 天成交:还在保护期,不转", OP.该转吗("A", "B", "x", "y", 基, 天(180))["转"] is False)
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
        单 = None
        for (oid,) in c.execute("SELECT o.id FROM ordr o JOIN customer cu ON cu.id=o.customer_id WHERE o.shop<>cu.shop "
                                "AND o.paid_at IS NOT NULL AND o.advisor_no IS NOT NULL ORDER BY o.paid_at DESC").fetchall():
            r, _ = OT.判定(c, oid, "2026-11-11")
            if r["转"]:
                单 = oid; break
        ck("夹具:库里找得到一张「跨店、过了保护期」的已付款单", bool(单))
        if 单:
            n0 = c.execute("SELECT COUNT(*) FROM schedule WHERE type='归属转移'").fetchone()[0]
            with c:
                出 = OT.成交后(c, 单, "2026-11-11", "检查")
            现 = c.execute("SELECT shop, advisor_no FROM customer WHERE id=?", (出["客户"],)).fetchone()
            ck("转了:整户改到成交店 + 接待导购", 出["转了吗"] and 现 == (出["成交店"], 出["接待导购"]), (出.get("理由"), 现))
            n1 = c.execute("SELECT COUNT(*) FROM schedule WHERE type='归属转移'").fetchone()[0]
            ck("派了知会:原导购 + 原店店长 + 新店店长(在职的都派)", n1 - n0 == len(出.get("知会任务") or []) >= 2, (n0, n1, 出.get("知会任务")))
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
