#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W 型归因全量回填:给每一张追得到接待的定制单算影响力分成。

## 为什么要这一步

成交率有两个数(见 knowledge/linkage.py):
    ① 按接待人算  —— 业务明说不对(「不能因为某一次就算在某人身上」)
    ② 按归因算    —— **业务要的**,而之前只有 60 张单有影响力分成,**而且那 60 张
                     是规则造的样本,W 型从来没对真单子跑过一遍**

算法有了(knowledge/attribution.W型分配)、触点有了,缺的只是跑一遍。纯计算。

## ⚠️ 三件事

- **远程量体不进归因。** 业务 09-22:不准远程量体,必须顾问亲自服务。
  和接待口径保持一致 —— 不一致的话,「算不算接待」和「算不算贡献」会给出两个答案。
- **写的是影响力分成,不是收入分成。** W 型给的是贡献(可以不等于 100 地分给多人),
  不是提成。**别拿它去分钱。**
- **method 写「W型归因 v1·全量」**,和 fixture 里那条「W型归因 v1」分开 ——
  **重跑时只删自己写的**,不碰别人的样本。30/30/30/10 是惯例不是算出来的,换参数就换版本。
"""
import os, sqlite3, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "backend")]
import attribution as _归因, journey as _旅程, linkage as _链

DB = os.path.join(ROOT, "backend", "lanxiu.db")
METHOD = "W型归因 v1·全量"
角色映射 = {"首次接待": "首次接待", "量体": "量体", "成交": "成交",
            "成交(无量体节点)": "成交"}


def 全部触点(c):
    """客户 → 触点列表(未去重)。**一次读完**,不逐单查 ——
    逐单是 3403×5 次查询,这个项目为逐客户循环把门禁拖到超时过。"""
    出 = {}
    def 收(cid, **kw):
        出.setdefault(cid, []).append(kw)
    for r in c.execute("select customer_id, start_ts, advisor_no from appointment"):
        收(r[0], 类型="预约", 时间=r[1], 经手人=r[2])
    for r in c.execute("select customer_id, ts, advisor_no from followup"):
        收(r[0], 类型="跟进", 时间=r[1], 经手人=r[2])
    for r in c.execute("select customer_id, start_ts, coalesce(assignee_no, advisor_no) from schedule"):
        收(r[0], 类型="日程", 时间=r[1], 经手人=r[2])
    ph = ",".join("?" * len(_链.亲自服务的量体方式))
    for r in c.execute(f"select customer_id, measured_at, measured_by_no from measure_rec "
                       f"where method in ({ph})", _链.亲自服务的量体方式):
        收(r[0], 类型="量体", 时间=r[1], 经手人=r[2])
    for r in c.execute("select customer_id, created, advisor_no from ordr"):
        收(r[0], 类型="下单", 时间=r[1], 经手人=r[2])
    return 出


def main():
    t0 = time.time()
    c = sqlite3.connect(DB)
    c.execute("delete from deal_credit where method=?", (METHOD,))
    单 = list(c.execute("""select id, customer_id, created from ordr
                           where kind='定制品订单' and appt_src='接待关联'"""))
    点 = 全部触点(c)
    # **世界的今天,不是机器的今天** —— 否则同一份代码今天和明天造出不同的数据,
    # 重建就不可复现(determinism_check 当场抓到了第一版)。
    from seed import TODAY as 今
    行, 空 = [], 0
    for oid, cid, created in 单:
        前 = [x for x in 点.get(cid, []) if (x["时间"] or "") < (created or "")]
        分 = _归因.W型分配(_旅程.归一(前))
        if not 分:
            空 += 1; continue
        for who, pct, roles in 分:
            主 = next((角色映射[r] for r in roles.split("/") if r in 角色映射), "跟进")
            坏 = _归因.校验一笔(_归因.影响力分成, 主, "算法算", pct, METHOD)
            if 坏:
                sys.exit(f"❌ {oid} 的一笔过不了校验:{坏}")
            行.append((oid, who, _归因.影响力分成, 主, pct, "算法算", METHOD, roles, 今))
    c.executemany("""insert into deal_credit
                     (order_id,staff_no,kind,role,pct,source,method,basis,created)
                     values(?,?,?,?,?,?,?,?,?)""", 行)
    c.commit()
    覆盖 = c.execute("select count(distinct order_id) from deal_credit where method=?",
                     (METHOD,)).fetchone()[0]
    c.close()
    # **自检:写进去的单数要和算出来的对得上** —— 一条都没写和写完了,输出上长得一样
    if 覆盖 != len(单) - 空:
        sys.exit(f"❌ 算出 {len(单)-空} 单,库里只有 {覆盖} 单 —— 写库没生效")
    print(f"  定制单(已挂接待)  {len(单)} 张 · 算出影响力 {覆盖} 张 · 算不出 {空} 张"
          f" · {len(行)} 条记录 · {time.time()-t0:.1f}s")
    print(f"  ⚠️ 写的是**影响力分成**(记贡献),不是收入分成 —— 别拿它分钱")


if __name__ == "__main__":
    main()
