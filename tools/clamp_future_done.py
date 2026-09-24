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
    ("只把 finished_at 改小,不动同一单的其它时间点(会造出「发货晚于完成」)",
     "先后关系全保住"),
    ("改回整体平移(不按比例压缩)——第一条回传会跑到下单之前",
     "条回传早于下单"),
]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
DB = os.path.join(ROOT, "backend", "lanxiu.db")

# ⚠️ **只挪生产交付这一段,不碰下单之前的那几列。**
# `created / recept_at / paid_at / audit_at` 往回挪的话,「下单量体必须在下单之前」
# 这条硬规矩当场破:2026-09-24 从零重建时两张单变成「下单之前没有任何量体记录」。
# 生产段整体往回挪不会破坏内部先后(它们之间隔着 8~10 天,而挪动量最多 15 天),
# 也不会跑到 created 之前(created 到 produced 隔着 30~40 天)。
列 = {"ordr": (["updated", "produced_at", "shipped_at", "finished_at", "cut_at"], "id"),
      "factory_msg": (["at", "received_at", "promise_date"], "order_id"),
      "pkg": (["shipped_at", "arrived_at", "created"], "order_id"),
      "pickup": (["arrived_at", "forwarded_at", "fit_at", "complete_at"], "order_id"),
      "order_event": (["at"], "order_id"),
      # fitting 是**开裁之前**的事,跟着生产段往回挪会跑到下单之前 —— 不动
      }

# ⚠️ **接待日不能单独钉住,也不能单独挪。**
# 「这一单挂的是哪次接待」是按**同一天 + 同一个人**认的(backend/link_check.py)。
# 2026-09-24 我第一版只挪订单不挪量体,6 张单的接待当场挂到了远程量体上 ——
# 而清单上看不出来:那一栏照样有值。挪完这两样,还要把归属和影响力重算一遍
# (见 tools/shift_world.py 的「平移后重算」)。


def 修(db=DB, 说=print):
    """把这几张单的时间线**按比例压进「下单 → 昨天」**。

    ⚠️ **为什么是压缩不是平移。**
    第一版是整体往回挪 N 天。挪完之后 7 张单的第一条工厂回传全都跑到了下单**之前**
    (最多早 14 天)—— 因为接单紧跟着开裁、离下单很近,而挪动量比那个间隔还大。
    换句话说:**这几张单的时间线本来就长到装不进「今天之前」**,平移必然顶穿开头。

    所以改成把 [下单, 原完成] 这一段线性压进 [下单, 昨天]:
      · 先后关系全保住(单调映射)
      · 一个时间点都不会跑到下单之前
      · 代价是**这几单的各阶段时长会被压短** —— 7 张演示单,说清楚就好,
        不能为了保住时长去破坏「不早于下单」这条硬规矩。
    """
    from seed import TODAY
    今 = dt.date.fromisoformat(TODAY)
    c = sqlite3.connect(db)
    坏 = [(r[0], r[1], r[2]) for r in c.execute(
        "select id, finished_at, created from ordr where finished_at is not null "
        "and substr(finished_at,1,10)>?", (TODAY,))]
    if not 坏:
        说("  没有「完成日在今天之后」的单,不动。"); c.close(); return 0
    n = 0
    for oid, fin, 下单 in 坏:
        起 = dt.date.fromisoformat((下单 or fin)[:10])
        原 = (dt.date.fromisoformat(fin[:10]) - 起).days
        目标 = (今 - dt.timedelta(days=1) - 起).days
        if 原 <= 0 or 目标 <= 0: continue
        比 = 目标 / 原
        for t, (cols, 键) in 列.items():
            try: have = [d[1] for d in c.execute(f'pragma table_info("{t}")')]
            except sqlite3.Error: continue
            use = [x for x in cols if x in have]
            if not use or 键 not in have: continue
            rows = c.execute(f'select rowid, {",".join(chr(34)+x+chr(34) for x in use)} '
                             f'from "{t}" where "{键}"=?', (oid,)).fetchall()
            for r in rows:
                上 = {}
                for k, v in zip(use, r[1:]):
                    if not v: continue
                    try: d0 = dt.date.fromisoformat(str(v)[:10])
                    except ValueError: continue
                    新日 = 起 + dt.timedelta(days=round((d0 - 起).days * 比))
                    上[k] = 新日.isoformat() + str(v)[10:]
                if 上:
                    c.execute(f'update "{t}" set ' + ",".join(f'"{k}"=?' for k in 上)
                              + " where rowid=?", (*上.values(), r[0]))
                    n += 1
    c.commit()
    剩 = c.execute("select count(*) from ordr where finished_at is not null "
                   "and substr(finished_at,1,10)>?", (TODAY,)).fetchone()[0]
    早 = c.execute("select count(*) from factory_msg f join ordr o on o.id=f.order_id "
                   "where f.received_at < o.created").fetchone()[0]
    c.close()
    说(f"  {len(坏)} 张单的时间线压进「下单 → 昨天」(共 {n} 行);"
       f"还剩 {剩} 张完成日在未来、{早} 条回传早于下单")
    return 剩 + 早


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

