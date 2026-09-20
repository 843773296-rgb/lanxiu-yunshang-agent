#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造成交归因样本。

⚠️ **两种分成都要有样本,而且要有「总和超过 100%」的那种** ——
否则「影响力分成可以超 100」这条规则永远测不到,
而一个把它当成「必须等于 100」的实现会全绿通过。

确定性:按订单序号分配,不用随机。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")
from seed import TODAY
import credit as C

来源 = "规则算"


def main():
    c = sqlite3.connect(DB)
    C.建表(c)
    c.execute("delete from deal_credit where source=?", (来源,))

    顾问 = [r[0] for r in c.execute(
        "select no from staff where role='顾问' and status='启用' order by no")]
    if len(顾问) < 3:
        sys.exit("❌ 在职顾问不足 3 人,造不出协作样本")

    # 取 60 张已完成的定制单 —— 定制才有「首次接待/量体/方案确认/成交」这条链
    单 = [r[0] for r in c.execute(
        """select id from ordr where status='完成' and kind='定制'
           order by id limit 60""")] or [r[0] for r in c.execute(
        "select id from ordr where status='完成' order by id limit 60")]

    单人, 协作 = 0, 0
    for i, oid in enumerate(单):
        主 = 顾问[i % len(顾问)]
        if i % 3 == 0:
            # ── 协作单:两个人 ────────────────────────────────
            副 = 顾问[(i + 1) % len(顾问)]
            # 收入分成:**加起来正好 100**(分钱)
            C.记一笔(oid, 主, C.收入分成, "成交", 70, 来源, basis="主接待", ts=TODAY, conn=c)
            C.记一笔(oid, 副, C.收入分成, "首次接待", 30, 来源, basis="代接", ts=TODAY, conn=c)
            # 影响力分成:**加起来 200,故意超过 100**(记贡献,不是零和)
            C.记一笔(oid, 主, C.影响力分成, "成交", 100, 来源, basis="谈成的是他", ts=TODAY, conn=c)
            C.记一笔(oid, 副, C.影响力分成, "首次接待", 60, 来源, basis="第一次是他接的", ts=TODAY, conn=c)
            C.记一笔(oid, 副, C.影响力分成, "量体", 40, 来源, basis="量体是他做的", ts=TODAY, conn=c)
            协作 += 1
        else:
            # ── 单人单 ───────────────────────────────────────
            C.记一笔(oid, 主, C.收入分成, "成交", 100, 来源, basis="全程一人", ts=TODAY, conn=c)
            C.记一笔(oid, 主, C.影响力分成, "成交", 100, 来源, basis="全程一人", ts=TODAY, conn=c)
            单人 += 1
    c.commit()

    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    收 = q("select count(*) from deal_credit where kind=?", C.收入分成)
    影 = q("select count(*) from deal_credit where kind=?", C.影响力分成)
    超100 = q(f"""select count(*) from (select order_id, sum(pct) s from deal_credit
                  where kind=? group by order_id having s>100)""", C.影响力分成)
    坏 = C.收入分成对不对(DB)

    if 坏:
        sys.exit(f"❌ {len(坏)} 单的收入分成加起来不是 100:{坏[:3]} —— 那是分钱,不能多也不能少")
    if 超100 == 0:
        sys.exit("❌ 没有一单的影响力分成超过 100% —— "
                 "**那条规则就永远测不到,而把它当成「必须=100」的实现会全绿通过**")

    print(f"  归因样本:{len(单)} 单(单人 {单人} · 协作 {协作});"
          f"收入分成 {收} 条、影响力分成 {影} 条")
    print(f"  其中 **{超100} 单的影响力分成超过 100%** —— 它不是零和的,这一点要有样本才测得到")
    c.close()


if __name__ == "__main__":
    main()
