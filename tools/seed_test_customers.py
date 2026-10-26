#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造集成验证用的专用测试客户:每家店一个(用户 2026-10-26 拍)。认法在 backend/it_customer.py。

## 为什么放在重建流程的最后一批(门店码回填之前)

账户是「所有不重复手机号排序后依次编号」建的,前面造数里多一个号,后面账户编号整体后挪,
着装人 / 量体跟着错位(10-26 改合并题时在「定制单工期不到 20 天」那条断言上炸过)。
放到最后:前面所有造数都看不到它们;账户号用 UIT- 开头,不占顺序编号。

## 档案「正常」指什么

有姓名、手机号、门店(含门店码)、本店一位在职顾问、按口径现算的等级、一个自己的账户 ——
集成验证里派任务、写跟进要用到的字段都齐。**不造订单、不造互动**:它只用来接集成验证的写入。

    python3 tools/seed_test_customers.py          # 幂等:先删同前缀的再造
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "backend"), os.path.join(HERE, ".."), os.path.join(HERE, "..", "knowledge")]
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")
from seed import TODAY  # noqa: E402
import it_customer as TC  # noqa: E402


def main():
    c = sqlite3.connect(DB)
    import shop_key as _SK
    import knowledge.member as mb
    档位表 = [dict(zip(("code", "name", "amount", "orders", "sort", "need_points"), r))
              for r in c.execute("select code,name,amount,orders,sort,need_points from level_cfg where status='启用'")]
    档 = mb.判档(0, 0, 档位表)
    c.execute(f"delete from wearer where customer_id like '{TC.前缀}%'")
    c.execute(f"delete from customer where id like '{TC.前缀}%'")
    c.execute("delete from account where id like 'UIT-%'")
    店们 = [r[0] for r in c.execute("select distinct shop from customer where shop is not null and shop<>'' order by shop")]
    造了 = []
    for i, 店 in enumerate(店们, 1):
        码 = _SK.码(c, 店)
        顾问 = c.execute("""select no from staff where role='顾问' and coalesce(status,'启用')='启用'
                           and shop=? order by no limit 1""", (店,)).fetchone()
        if not 顾问:
            sys.exit(f"❌ {店} 没有在职顾问 —— 测试客户挂不上归属,集成验证派任务会落空")
        cid, aid, 号 = f"{TC.前缀}{码}-01", f"UIT-{码}", f"199{i:08d}"
        名 = f"测试·集成验证({店.split(' ', 1)[-1]})"
        c.execute("""insert into account(id, phone, status, created, display_name, home_shop)
                     values(?,?,?,?,?,?)""", (aid, 号, "正常", TODAY, 名, 店))
        c.execute("""insert into customer(id,name,phone,shop,shop_code,advisor_no,lifecycle,level,
                                          created,archived,order_cnt,orders_12m,amount_12m,idle_days,account_id)
                     values(?,?,?,?,?,?,?,?,?,0,0,0,0,0,?)""",
                  (cid, 名, 号, 店, 码, 顾问[0], "潜在", 档, TODAY, aid))
        # 档位按口径现算(lifecycle_sync_check 也调这一个)—— 手写「潜在」会和重算对不上
        import lifecycle as _L
        行 = dict(zip([x[0] for x in c.execute("select * from customer where id=?", (cid,)).description],
                     c.execute("select * from customer where id=?", (cid,)).fetchone()))
        档位 = _L.decide(dict(行, days_since_first_order=None, days_since_manual=None))["生命周期"]
        c.execute("update customer set lifecycle=? where id=?", (档位, cid))
        # 每个账户有且只有一个「本人」着装人(账户规范 A3 / A8)
        wid = f"W-{cid}"
        c.execute("delete from wearer where id=?", (wid,))
        c.execute("""insert into wearer(id,customer_id,account_id,name,gender,birthday,relation,phone,status,created)
                     values(?,?,?,?,?,?,?,?,?,?)""", (wid, cid, aid, 名, "女", "1990-01-01", "本人", 号, "在用", TODAY))
        c.execute("update account set self_wearer_id=? where id=?", (wid, aid))
        造了.append(cid)
    c.commit()
    if not 造了:
        sys.exit("❌ 一个门店都没有 —— 没造出测试客户(这不叫通过)")
    print(f"✅ 造了 {len(造了)} 个集成验证测试客户(每家店一个):{造了}")


if __name__ == "__main__":
    main()
