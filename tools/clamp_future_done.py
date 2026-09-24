#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「状态是完成、完工日却在今天之后」的单整条时间线往回挪。

## 为什么会有这种单

旅程脚本(tools/run_journey.py)按「第 N 天」排事件,排到最后几张时 N 会越过今天,
于是库里出现 status=完成、finished_at 在下周的单。

**单条记录完全合法** —— 格式对、不早于创建时间、金额也对。只有拿「今天」去比才看得出来。
而 C4 那条检查当时用的是**机器时钟**,机器比演示世界早三周,正好把它盖住;
2026-09-24 世界改成跟着真实日期走之后,7 张当场露出来。

## 怎么修

**整条时间线一起往回挪**,不是单独把 finished_at 改小:
一单的下单/付款/审核/完工/发货/完成/开裁,以及它的工厂回传、包裹、签收、试衣,
必须保持原有先后。单独改一个字段会造出「发货晚于完成」这种新矛盾,
而那种矛盾同样是「单条看起来都对」。

挪到**昨天完成**,留一天余量。可反复跑:没有这种单时什么都不做。
"""
import datetime as dt, os, sqlite3, sys

# ── 咬合记录 ──────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。
# 这个脚本的「红」是它跑完之后 backend/spec_check.py 的 C4 还红着 ——
# 所以咬合点在:**挪的范围少一样,就会留下自相矛盾的数据**。
咬合 = [
    ("只把 finished_at 改小,不挪同一单的其它时间点(会造出「发货晚于完成」)",
     "整条时间线一起往回挪"),
    ("挪订单但不挪量体(去掉 measure_rec 那一步 —— 接待会挂到别的量体上)",
     "跟着一起挪"),
]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
DB = os.path.join(ROOT, "backend", "lanxiu.db")

列 = {"ordr": (["recept_at", "created", "updated", "paid_at", "audit_at", "produced_at",
                "shipped_at", "finished_at", "cut_at"], "id"),
      "factory_msg": (["at", "received_at", "promise_date"], "order_id"),
      "pkg": (["shipped_at", "arrived_at", "created"], "order_id"),
      "pickup": (["arrived_at", "forwarded_at", "fit_at", "complete_at"], "order_id"),
      "order_event": (["at"], "order_id"),
      "fitting": (["ts", "signed_at"], "order_id")}

# ⚠️ **接待日不能单独钉住,也不能单独挪。**
# 「这一单挂的是哪次接待」是按**同一天 + 同一个人**认的(backend/link_check.py)。
# 2026-09-24 我第一版只挪订单不挪量体,6 张单的接待当场挂到了远程量体上 ——
# 而清单上看不出来:那一栏照样有值。挪完这两样,还要把归属和影响力重算一遍
# (见 tools/shift_world.py 的「平移后重算」)。


def 修(db=DB, 说=print):
    from seed import TODAY
    今 = dt.date.fromisoformat(TODAY)
    c = sqlite3.connect(db)
    坏 = [(r[0], r[1]) for r in c.execute(
        "select id, finished_at from ordr where finished_at is not null "
        "and substr(finished_at,1,10)>?", (TODAY,))]
    if not 坏:
        说("  没有「完成日在今天之后」的单,不动。"); c.close(); return 0
    n = 0
    for oid, fin in 坏:
        天 = (dt.date.fromisoformat(fin[:10]) - 今).days + 1     # 挪到昨天完成
        for t, (cols, 键) in 列.items():
            try: have = [d[1] for d in c.execute(f'pragma table_info("{t}")')]
            except sqlite3.Error: continue
            use = [x for x in cols if x in have]
            if not use or 键 not in have: continue
            c.execute(f'update "{t}" set ' + ",".join(
                f'"{k}"=CASE WHEN "{k}" IS NULL THEN NULL ELSE date("{k}", ?)||substr("{k}",11) END'
                for k in use) + f' where "{键}"=?', (*[f"-{天} days"] * len(use), oid))
            n += 1
        # 这一单挂着的那次量体,跟着一起挪 —— 不挪的话接待就挂断了
        r0 = c.execute("select recept_at, recept_by, customer_id from ordr where id=?", (oid,)).fetchone()
        if r0 and r0[0] and r0[1]:
            c.execute("update measure_rec set measured_at=date(measured_at,?)||substr(measured_at,11) "
                      "where customer_id=? and measured_by_no=? and substr(measured_at,1,10)=?",
                      (f"-{天} days", r0[2], r0[1], r0[0][:10]))
    c.commit()
    剩 = c.execute("select count(*) from ordr where finished_at is not null "
                   "and substr(finished_at,1,10)>?", (TODAY,)).fetchone()[0]
    c.close()
    说(f"  {len(坏)} 张单整条时间线往回挪(共 {n} 次更新);还剩 {剩} 张")
    return 剩


# ── 名字里嵌着年月的,跟着 created 走 ────────────────────────────
# 方案名长这样:「明制立领长衫·妆花+苏绣·2026-08」—— 末尾那个年月是**建档那个月**。
# 平移跨过月底时,名字和 created 就对不上了(2026-09-24 实测 62 个)。
# 和工厂回传那条 reason 是**同一类错**:一段文字复述了某个字段,
# 改了字段没改文字,两者静默分家,而**错的那一半恰好是给人看的**。
def 名字里的年月(db=DB, 说=print):
    import re
    c = sqlite3.connect(db)
    n = 0
    for sid, name, created in c.execute("select id,name,created from scheme").fetchall():
        if not name or not created: continue
        新 = re.sub(r"\d{4}-\d{2}$", created[:7], name)
        if 新 != name:
            c.execute("update scheme set name=? where id=?", (新, sid)); n += 1
    c.commit(); c.close()
    说(f"  方案名里的年月对齐 created:改了 {n} 个")
    return n


if __name__ == "__main__":
    print("把「完成日在未来」的单挪回来")
    print("=" * 66)
    剩 = 修()
    名字里的年月()
    sys.exit(1 if 剩 else 0)

