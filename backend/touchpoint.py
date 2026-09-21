# -*- coding: utf-8 -*-
"""客户旅程:把散在五张表里的触点,连成一条按时间排的线。

## 这不是造数据,是归一

归因算法(W 型 / Shapley)要的输入是**客户旅程** —— 一个客户从第一次接触到下单,
中间经过了哪些点、每个点是谁经手的。

而这些点**库里本来就有**,只是散着:

    appointment   75 条    预约
    followup      24 条    跟进
    schedule      90 条    日程(电话回电/上门沟通/预约到店)
    measure_rec   10624 条 **量体** —— 数量最多的一类触点
    ordr          26587 条 下单

**没有一处把它们连起来**,于是「这个客户经过了什么」这个问题答不出来,
而归因算法的输入就是这个答案。

## 🔑 触点不是「记录」,是「谁在什么时候做了什么」

同一张表里的记录,**不一定都是触点**:

    量体 10624 条,但**一个客户一次量体会产生十几条记录**(每个测量项一条)——
    那是**一次**触点,不是十几次。按 (客户, 日期, 经手人) 去重。

不去重的话,量体那一类会以 100:1 的比例淹没其他触点,
**而归因算出来的「量体贡献最大」只是因为它的行数最多。**

## ⚠️ 触点齐不等于旅程真实

造数据造出来的旅程**太干净**:预约→到店→量体→下单,一步不落。
真实客户会绕弯、会中断、会问一半消失。

> **造的旅程能验证「算法跑不跑得通」,验证不了「算得准不准」。**

所以这个模块的产出只用来**跑通算法**,算出来的贡献分配**不能当成真实结论**。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
# 归一的口径(去重/排序/够不够算)在 knowledge/journey.py,这里只取数。
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
import journey as _口径

类型 = _口径.类型          # 转发,不抄


def _rows(sql, *a, db=DB):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def 客户旅程(customer_id, 截至=None, db=DB):
    """这个客户经过的触点,按时间排。

    `截至` 给了就只取那之前的 —— 归因要的是「**这一单之前**发生了什么」。
    """
    止 = 截至 or "9999"
    出 = []

    for r in _rows("""select id, start_ts ts, advisor_no who, status
                      from appointment where customer_id=? and start_ts<?""",
                   customer_id, 止, db=db):
        出.append(dict(类型="预约", 时间=r["ts"], 经手人=r["who"], 对象=r["id"], 备注=r["status"]))

    for r in _rows("""select id, ts, advisor_no who, channel
                      from followup where customer_id=? and ts<?""", customer_id, 止, db=db):
        出.append(dict(类型="跟进", 时间=r["ts"], 经手人=r["who"], 对象=r["id"], 备注=r["channel"]))

    for r in _rows("""select id, start_ts ts, coalesce(assignee_no, advisor_no) who, type
                      from schedule where customer_id=? and start_ts<?""",
                   customer_id, 止, db=db):
        出.append(dict(类型="日程", 时间=r["ts"], 经手人=r["who"], 对象=r["id"], 备注=r["type"]))

    # ⚠️ **量体一次会产生十几行**(每个测量项一条)—— 那是**一次**触点。
    # 这里取原始行,**去重的口径在 `knowledge/journey.去重`**:
    # 放在这里用 GROUP BY 也能去,但那样这条判据就只存在于一句 SQL 里,
    # **测不了,也没法和别处对账**。
    for r in _rows("""select id, measured_at ts, measured_by_no who
                      from measure_rec where customer_id=? and measured_at<?""",
                   customer_id, 止, db=db):
        出.append(dict(类型="量体", 时间=r["ts"], 经手人=r["who"], 对象=r["id"], 备注=""))

    for r in _rows("""select id, created ts, advisor_no who, kind
                      from ordr where customer_id=? and created<?""", customer_id, 止, db=db):
        出.append(dict(类型="下单", 时间=r["ts"], 经手人=r["who"], 对象=r["id"], 备注=r["kind"]))

    return _口径.归一(出)


def 这一单之前(order_id, db=DB):
    """归因的输入:这一单之前,这个客户经过了哪些触点、每个是谁经手的。"""
    r = _rows("select customer_id, created from ordr where id=?", order_id, db=db)
    if not r:
        return None, []
    return r[0]["customer_id"], 客户旅程(r[0]["customer_id"], 截至=r[0]["created"], db=db)


def 统计(db=DB):
    """**多少客户有几个触点** —— 归因算法能不能跑,看的是这个。

    ⚠️ **一条聚合查询,不要逐客户循环。**
    第一版对 965 个客户各跑 5 次查询(4825 次),把门禁从几分钟拖到超时 ——
    **一条跑得太慢的检查,最后的下场是被人从门禁里拿掉**,那就等于没有。
    """
    有旅程, 分布, 合 = 0, {}, {}
    for r in _rows("""
        select customer_id cid, count(*) n from (
            select customer_id from appointment
            union all select customer_id from followup
            union all select customer_id from schedule
            union all select customer_id from ordr
        ) where customer_id not like 'FX-%' group by 1""", db=db):
        合[r["cid"]] = r["n"]
    for r in _rows("""
        select customer_id cid, count(*) n from (
            select distinct customer_id, substr(measured_at,1,10) d, measured_by_no w
            from measure_rec) where customer_id not like 'FX-%' group by 1""", db=db):
        合[r["cid"]] = 合.get(r["cid"], 0) + r["n"]
    for n in 合.values():
        if n:
            有旅程 += 1
            桶 = "1个" if n == 1 else ("2-4个" if n <= 4 else ("5-9个" if n <= 9 else "10个以上"))
            分布[桶] = 分布.get(桶, 0) + 1
    return 有旅程, 分布


if __name__ == "__main__":
    n, d = 统计()
    print(f"有触点的客户 {n} 人;旅程长度分布 {d}")
    r = _rows("select id from ordr where kind<>'标品订单' order by id limit 1")
    if r:
        cid, 旅 = 这一单之前(r[0]["id"])
        print(f"\n举例:订单 {r[0]['id']}(客户 {cid})之前的 {len(旅)} 个触点")
        for x in 旅[-6:]:
            print(f"   {x['时间'][:16]}  {x['类型']:4s} {x['经手人'] or '?':10s} {x['备注']}")
