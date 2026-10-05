#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""营销 SOP 要的那几类数据,**现在够不够** —— 现查,不写死。

    python3 tools/mkt_data_health.py

## 为什么数字不写进 SOP 里

2026-10-05 CI 红过一次:`knowledge/15-营销SOP.md` 里写着
「预约覆盖 5817 个客户(72%)」,而 CI 从零建库算出来是 0% ——

> 一份「按本机库生成」的 SOP,和一份「按 CI 从零建的库生成」的,
> **在那份 md 上长得一模一样** —— 而那几个数不同。

而更根本的是**那个数本来就不该在那儿**:顾问检索到「预约覆盖 72%」,
那是**演示库**的数字,不是真实业务的。放进 RAG 语料会误导。

所以:SOP 里只说「这一类数据够不够,现查」,数字在这儿看。

## 判据

对营销 SOP 用到的五类触点,报**覆盖了多少客户**,并分三档:

    够      ≥ 50%  —— 规则跑得起来
    偏低    10–50% —— 规则会触发,但覆盖面有限
    撑不住  < 10%  —— **规则写了也几乎不会触发**,而
                      「规则没触发」和「规则写对了但没人符合」
                      在报表上长得一模一样

⚠️ **它只报状态,不拦门禁。** 数据够不够是业务进度,不是代码错误 ——
一条会因为「演示库还没造数据」而拦住提交的检查,第三天就会被绕过去。
"""
import os
import sqlite3
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
库 = os.path.join(根, "backend", "lanxiu.db")

# (中文名, 表, 这一类是干什么的)
类别 = [
    ("下单", "ordr", "旅程的终点 —— 几乎所有客户都有"),
    ("量体", "measure_rec", "定制业务的关键节点(归因的 `关键节点类型` 就是它)"),
    ("预约", "appointment", "到店前的触点 —— MKT-09-03"),
    ("日程", "schedule", "到店/上门/试衣 —— MKT-09-05"),
    ("跟进", "followup", "**唯一能看出「她当时怎么想」**的那一类点 —— MKT-09-02"),
    ("评价", "rating", "交付之后"),
    ("售后", "aftersale", "交付之后"),
]


def main():
    print("营销 SOP 的数据体检 —— 这几类触点现在够不够")
    print("=" * 84)
    if not os.path.exists(库):
        print(f"  ⏸ 没有 {库} —— **不适用,不是通过**(先跑 backend/seed.py)")
        return 0
    c = sqlite3.connect(库)
    总 = c.execute("select count(*) from customer").fetchone()[0]
    if not 总:
        print("  ❌ 客户表是空的 —— 不叫「覆盖率 0」,叫没数据")
        return 1
    print(f"  客户总数 {总}\n")
    撑不住 = []
    for 名, 表, 说明 in 类别:
        try:
            n = c.execute(f"select count(distinct customer_id) from {表} "
                          f"where customer_id is not null").fetchone()[0]
        except Exception as e:
            print(f"  ⏸ {名}:查不到({表})—— {str(e)[:40]}")
            continue
        p = n * 100 // 总
        档 = "✅ 够" if p >= 50 else ("🟡 偏低" if p >= 10 else "❌ 撑不住")
        print(f"  {档}  {名:4} {n:>6} 人({p:>2}%)  {说明}")
        if p < 10:
            撑不住.append(名)

    # 档位历史:C 方案(流失预警)的前提
    print()
    try:
        h = c.execute("select count(*) from lifecycle_history").fetchone()[0]
        人 = c.execute("select count(distinct customer_id) "
                      "from lifecycle_history").fetchone()[0]
        变 = c.execute("""select count(*) from (
                 select customer_id from lifecycle_history
                  group by customer_id having count(distinct lifecycle)>1)"""
                      ).fetchone()[0]
        if not h:
            print("  ❌ 档位历史 0 条 —— **C 方案(流失预警)没有信号可学**")
        else:
            # ⚠️ **「有多少条」不是判据,「档位变过没有」才是。**
            # 2026-10-05 真栽过:23216 条历史,而档位变过的 0% ——
            # 因为读错了一个 dict 的键,档位全是字符串 "None"。
            # > 一份「条数正确、格式漂亮」的历史,和一份有信号的,
            # > **在那个条数上长得一模一样。**
            p2 = 变 * 100 // max(人, 1)
            档 = "✅" if p2 >= 30 else "❌"
            print(f"  {档} 档位历史 {h} 条 / {人} 人,"
                  f"**档位变过的 {变} 人({p2}%)**")
            print(f"     ⚠️ 看的是「**变过没有**」不是「有多少条」—— "
                  f"没有变化的历史,流失预警学不到任何东西")
    except Exception:
        print("  ⏸ 没有 lifecycle_history 表 —— C 方案的前提还不在")

    if 撑不住:
        print(f"\n  ⚠️ {len(撑不住)} 类撑不住({'、'.join(撑不住)})——")
        print("     规则写了也几乎不会触发,而「规则没触发」和"
              "「规则写对了但没人符合」**在报表上长得一模一样**。")
        print("     要补:看 fakedata/交数据工坊_营销SOP的数据缺口_20261004.md")
    print("\n  ⚠️ 这条**只报状态,不拦门禁** —— "
          "数据够不够是业务进度,不是代码错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
