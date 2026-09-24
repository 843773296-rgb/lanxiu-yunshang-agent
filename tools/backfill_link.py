#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把每一张定制单挂到**促成它的那次接待**上。

## ⚠️ 2026-09-22 推翻了前一版

前一版把「接待」定义成 `appointment` 里状态「已到店/已完成」的那几条 ——
全库只有 **7 条**,于是这个脚本只接上 14 张(0.4%),
结论写的是「剩下 3497 张是接待没记,要业务改流程」。

**那个结论错在定义。** 业务 2026-09-22 说清楚了:

> 每次接待肯定都会有接待记录的,需要留下语音证据,如果有量体还需要留下量体数据,
> **客户的量体数据都是顾问接待留下来的数据,不以顾客自己上传的数据为准**,
> 还有**白坯试衣也是顾问接待的环节中比较靠后的环节**。

按这个定义:

    量体场次    2026 场  (到店 1740 · 远程 255 · 上门 31,**全部由员工记录**)
    试衣场次     328 场
    预约到店       7 条
    → 定制单 3542 张,**100% 在下单前都有接待记录**
    (**09-22 再定:远程量体不算** —— 排除之后是 3403/3542,139 张没有合规接待)

**「接待没记」是我用错了定义,不是业务缺流程。**
记在这儿:**一个定义错了的判断,和一个数据真的缺了的判断,在结论上长得一模一样**
—— 都是「追不到,等业务」。而两者该做的事完全相反。

## ⚠️ 挂的是「哪次接待」,不是「谁促成的」

实测 **1939/3542(55%)** 的单,最近一次量体的经手人和订单上的顾问**不是同一个人**。
**拿「最后接待人」当「促成人」会把一半以上的单算错人** ——
而算出来的成交率看起来完全正常。谁促成的要看归因(W 型)。

判定口径在 `knowledge/linkage.py`,这里只取数和写库。
"""
import os, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "knowledge"))
import linkage as _口径

DB = os.path.join(ROOT, "backend", "lanxiu.db")


def 接待场次(c):
    """(客户 → [按时间排好的接待场次]) —— **一次读完,不要逐单查**。

    接待场次 = (客户, 日期, 经手人),证据有三种。
    同一天同一个顾问量十几个尺寸是**一次**;同一天两个顾问各做一次是**两次**。
    """
    出 = {}

    def 收(cid, 日, 人, 证, 方式=None):
        if not cid or not 日:
            return
        出.setdefault(cid, {})[(日, (人 or "").strip(), 证)] = \
            {"日期": 日, "经手人": (人 or "").strip(), "证据": 证, "方式": 方式}

    # ⚠️ **只收「亲自服务」的量体** —— 业务 2026-09-22:不准远程量体,
    # 必须顾问亲自服务(到店或上门)。远程量体不算接待。
    ph2 = ",".join("?" * len(_口径.亲自服务的量体方式))
    for r in c.execute(f"""select customer_id, substr(measured_at,1,10) d,
                                  measured_by_no, method
                           from measure_rec where method in ({ph2})
                           group by 1,2,3,4""", _口径.亲自服务的量体方式):
        收(r[0], r[1], r[2], "量体", r[3])
    for r in c.execute("""select o.customer_id, substr(f.ts,1,10) d, f.advisor_no
                          from fitting f join ordr o on o.id=f.order_id group by 1,2,3"""):
        收(r[0], r[1], r[2], "白坯试衣")
    ph = ",".join("?" * len(_口径.到店状态))
    for r in c.execute(f"""select customer_id, substr(start_ts,1,10) d, advisor_no
                           from appointment where status in ({ph}) group by 1,2,3""",
                       _口径.到店状态):
        收(r[0], r[1], r[2], "预约到店")
    return {cid: sorted(v.values(), key=lambda x: x["日期"]) for cid, v in 出.items()}


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    有列 = {r[1] for r in c.execute("PRAGMA table_info(ordr)")}
    缺 = {"recept_at", "recept_by", "recept_evi"} - 有列
    if 缺:
        # **不在这儿 ALTER。** 列声明在 seed.py 的 SCHEMA 里,靠确定性重建生效 ——
        # 在这里补一张表结构,会让「重建出来的库」和「补过的库」长得不一样。
        sys.exit(f"❌ ordr 表缺列 {sorted(缺)} —— 先 ./tools/rebuild.sh 重建")

    单 = [dict(r) for r in c.execute(
        "SELECT id, customer_id, created FROM ordr WHERE kind='定制品订单'")]
    场 = 接待场次(c)

    按码, 要写, 要撤 = {}, [], []
    for o in 单:
        前 = [x for x in 场.get(o["customer_id"], [])
              if (x["日期"] or "") < (o.get("created") or "")]
        来路, 码, _, 挂 = _口径.判(前)
        按码[码] = 按码.get(码, 0) + 1
        if 挂:
            要写.append((挂["日期"], 挂["经手人"], 挂["证据"], 来路, o["id"]))
        else:
            要撤.append((来路, o["id"]))

    c.executemany("UPDATE ordr SET recept_at=?, recept_by=?, recept_evi=?, appt_src=? "
                  "WHERE id=?", 要写)
    # ── 不该挂的要**撤掉** ────────────────────────────────────────
    # ⚠️ 这个脚本原来**只会加,不会撤** —— 判出来不该挂的,它什么都不做,
    # 于是上一次挂上的那条一直留着。以前没人改过日期,所以这个缺陷一直没露;
    # 2026-09-24 世界整体平移之后,有一张单的接待日不再对得上任何一次量体,
    # 它从「该挂」变成「不该挂」,而库里那条旧的还在 —— 自检当场 3546 vs 3547。
    #
    # **「重算」如果只会往上加,它就不是重算,是追加。**
    # 两者在第一次跑的时候长得一模一样,只有在输入变了之后才分得开。
    c.executemany("UPDATE ordr SET recept_at=NULL, recept_by=NULL, recept_evi=NULL, appt_src=? "
                  "WHERE id=? AND appt_src='接待关联'", 要撤)
    c.commit()

    # ── 自检:写进去的和判出来的要对得上 ────────────────────────
    # **「一条都没写」和「写完了」在这个脚本的输出上长得一样** —— 所以核一遍。
    实 = c.execute("SELECT count(*) FROM ordr WHERE appt_src='接待关联'").fetchone()[0]
    异 = c.execute("SELECT count(*) FROM ordr WHERE appt_src='接待关联' "
                   "AND (recept_by IS NULL OR recept_by='')").fetchone()[0]
    c.close()
    if 实 != len(要写):
        sys.exit(f"❌ 判出来 {len(要写)} 张该挂,库里却是 {实} 张 —— 写库没生效")
    if 异:
        sys.exit(f"❌ 有 {异} 张标了「接待关联」却没记接待人 —— 那等于没挂")

    print(f"  定制单 {len(单)} 张,按证据分:")
    for 码 in sorted(按码, key=lambda k: -按码[k]):
        print(f"     {码:14s} {按码[码]:5d} 张   {_口径.下一步.get(码,'')[:48]}")
    print(f"  ✅ 挂上了 {实} 张")
    print(f"  ⚠️ **挂的是「哪次接待」,不是「谁促成的」** —— "
          f"实测过半的单,最后接待人和订单顾问不是同一个人。")


if __name__ == "__main__":
    main()
