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
# ── 自测:**合成夹具**,不跑在真库上 ────────────────────────────────────
#
# 为什么必须有这一半:2026-09-27 给下面两条新行为写咬合,**攻击一次都没红** ——
# 因为咬合跑在**已经修好的库**上,那 19 个「签收在未来」的包裹早被挪回去了,
# **攻击没有对象**。而「攻击没有对象」和「攻击被拦住了」在输出上一模一样
# (这个项目栽过一次:攻击自己跑不起来,于是任何异常都被读成「被拦下」)。
#
# 所以造四张单,每张只坏一件事,把「会失败的那个状态」构造出来。
def _自测():
    import tempfile
    挂 = []

    def ck(名, 真, 补=""):
        print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:120]) if 补 else ''}")
        if not 真: 挂.append(名)

    今 = dt.date(2026, 9, 27)
    昨 = 今 - dt.timedelta(days=1)
    p = os.path.join(tempfile.mkdtemp(prefix="clamp-"), "t.db")
    c = sqlite3.connect(p)
    c.executescript("""
      create table ordr(id text primary key, created text, status text, finished_at text,
                        updated text, produced_at text, shipped_at text, cut_at text,
                        paid_at text);
      create table factory_msg(order_id text, at text, received_at text, promise_date text);
      create table pkg(pkg_id text, order_id text, shipped_at text, arrived_at text, created text);
      create table pickup(order_id text, arrived_at text, forwarded_at text, fit_at text,
                          complete_at text);
      create table pickup_item(order_item_id integer primary key, order_id text, pkg_id text,
                               fit_result text, fit_at text);
      create table pkg_pickup(pkg_id text primary key, order_id text, arrived_at text,
                              forwarded_at text);
      create table delivery_notice(order_id text primary key, signed_at text);
      create table order_event(order_id text, at text);
      create table scheme(id text, name text, created text);
    """)
    # ① 老场景:完工日在未来
    c.execute("insert into ordr values('A','2026-08-01 10:00','完成','2026-10-05 10:00',"
              "'2026-10-05 10:00','2026-09-20 10:00','2026-09-28 10:00','2026-09-10 10:00',"
              "'2026-08-02 10:00')")
    # ② **第二种未来**:完工日不在未来,**签收在未来** —— 修之前一张也选不到
    c.execute("insert into ordr values('B','2026-08-01 10:00','完成','2026-09-20 10:00',"
              "'2026-09-20 10:00','2026-09-10 10:00','2026-09-15 10:00','2026-09-05 10:00',"
              "'2026-08-02 10:00')")
    c.execute("insert into pickup_item values(1,'B','PB','合身','2026-10-07 15:00')")
    c.execute("insert into pickup values('B','2026-10-06 09:00',null,'2026-10-07 15:00',null)")
    # ③ **分钟粒度**:回传时刻(09:05)早于下单时刻(09:25),按天挪会落到下单之前
    c.execute("insert into ordr values('C','2026-09-23 09:25','完成','2026-09-30 12:00',"
              "null,null,null,null,'2026-09-23 10:00')")
    c.execute("insert into factory_msg values('C','2026-09-24 09:05','2026-09-24 09:05',null)")
    # ④ **还在办**的单:finished_at 是 NULL、签收也不在未来,只有别的已发生列在未来
    c.execute("insert into ordr values('D','2026-09-23 09:25','待发货',null,"
              "'2026-10-20 18:20',null,null,null,'2026-09-23 10:00')")
    # ⚠️ 这条回传**故意放在下单之后三天**(不是同一天)。第一版放在同一天,
    # 于是「让在办的单也被压缩」这个攻击**改坏了却看不出来** ——
    # 同一天的值压缩后 round() 回到原地,断言照样过,咬合只好红在另一条上。
    # **夹具要让破坏看得见**,否则证明不了那道守卫在承重。
    c.execute("insert into factory_msg values('D','2026-09-26 15:05','2026-09-26 15:05',null)")
    c.commit()

    说过 = []
    import types
    _seed = types.ModuleType("seed"); _seed.TODAY = 今.isoformat()
    sys.modules.setdefault("seed", _seed); sys.modules["seed"].TODAY = 今.isoformat()
    修(db=p, 说=说过.append)
    q = lambda sql, *a: c.execute(sql, a).fetchone()

    ck("① 完工日在未来的单,挪到了昨天之前",
       q("select substr(finished_at,1,10) from ordr where id='A'")[0] <= 昨.isoformat(),
       q("select finished_at from ordr where id='A'")[0])
    ck("② **签收在未来**也要挪(完工日不在未来,修之前一张也选不到)",
       q("select substr(fit_at,1,10) from pickup_item where order_id='B'")[0] <= 昨.isoformat(),
       q("select fit_at from pickup_item where order_id='B'")[0])
    ck("② 按包裹那张表跟着一起挪(三张表是同一个「签收时间」)",
       q("select substr(fit_at,1,10) from pickup where order_id='B'")[0] <= 昨.isoformat(),
       q("select fit_at from pickup where order_id='B'")[0])
    ck("③ **分钟粒度**:回传不许早于下单那一刻(同一天、时刻更早的那种)",
       q("select received_at from factory_msg where order_id='C'")[0]
       >= q("select created from ordr where id='C'")[0][:16],
       f"回传 {q('select received_at from factory_msg where order_id=\'C\'')[0]} "
       f"vs 下单 {q('select created from ordr where id=\'C\'')[0]}")
    ck("④ **还在办**的单不动它(时间线没结束,压缩它没有意义)",
       q("select received_at from factory_msg where order_id='D'")[0] == "2026-09-26 15:05",
       q("select received_at from factory_msg where order_id='D'")[0])
    ck("④ 而且要**说出来**(不动不等于没事 —— 那是某个写口用了机器时钟)",
       any("还在办" in x for x in 说过),
       [x for x in 说过 if "还在办" in x][:1])
    ck("先后关系全保住(下单 ≤ 开裁 ≤ 完工)",
       all(q(f"select (created<=coalesce(cut_at,created)) and "
             f"(coalesce(cut_at,created)<=coalesce(finished_at,cut_at,created)) "
             f"from ordr where id='{x}'")[0] for x in "AB"))
    n = q("select count(*) from factory_msg f join ordr o on o.id=f.order_id "
          "where f.received_at < o.created")[0]
    ck("一条回传早于下单都没有", n == 0, f"{n} 条")
    c.close()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不符合预期:{挂}"); return 1
    print("✅ clamp 自测全过(合成夹具:四张单,每张只坏一件事)")
    return 0


咬合 = [
    ("只把 finished_at 改小,不动同一单的其它时间点(会造出「发货晚于完成」)",
     "先后关系全保住"),
    ("改回整体平移(不按比例压缩)——第一条回传会跑到下单之前",
     "条回传早于下单"),
    # 2026-09-27 加的两条 —— 都是「造评价数据之前先量底数」才露出来的,没有哪道检查报过
    ("把选单条件改回只认 finished_at 在未来(19 个「签收在未来」的包裹一个也选不到)",
     "条回传早于下单"),
    ("去掉分钟粒度那道底线(按天挪、保留原时刻,回传会落在同一天但时刻早于下单)",
     "条回传早于下单"),
]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
import worldclock
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
      # ⚠️ **按包裹 / 按件那两张表是 2026-09-27 补的。**
      # `pickup` 是整单那一行,而分批发货之后签收落到了**包裹**和**件**
      # (业务 2026-09-23)—— 于是同一件事有了三张表,而这里只挪了第一张。
      # 表现:`pickup.fit_at` 10 行在未来、`pickup_item.fit_at` **22 行**在未来 ——
      # **挪了一张、漏了两张,而三张表在页面上是同一个「签收时间」。**
      "pickup_item": (["fit_at"], "order_id"),
      "pkg_pickup": (["arrived_at", "forwarded_at"], "order_id"),
      "delivery_notice": (["signed_at"], "order_id"),
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
    # ⚠️ **「完工在未来」和「签收在未来」是两种不同的未来。**
    # 2026-09-27 量到:19 个包裹签收在 09-28 ~ 10-07,而它们的 `finished_at`
    # **一个都不在未来** —— 所以这里原来那个 `finished_at > 今天` 一张也选不到。
    # 而同时:C4 看不见(`pickup_item.fit_at` 当时没登记进 worldclock 的清单)、
    # 平移前置闸看不见(读同一份清单)、这个脚本修不到(只认 finished_at)——
    # **三道闸同时的盲区**,比 `pkg.created` 那次多了一道。
    #
    # 所以判据改成:**这一单有没有任何「已经发生的事」落在今天之后**。
    # 取的是 `worldclock.已发生的时间列` 里挂在 ordr / 签收那几张表上的列,
    # **不在这儿另抄一份清单** —— 抄一份就会和 C4 各自漂,而漂的表现是
    # 「C4 红着但 clamp 说没事」,两种都看不出是清单不同步。
    def _未来的单(只看=None):
        出 = {}
        for t, col, _说, _pk in worldclock.已发生的时间列:
            if 只看 is not None and t not in 只看:
                continue
            if t not in 列 and t != "ordr":
                continue
            键 = "id" if t == "ordr" else 列.get(t, (None, "order_id"))[1]
            try:
                rows = c.execute(f'select "{键}", substr("{col}",1,10) d from "{t}" '
                                 f'where "{col}" is not null and substr("{col}",1,10)>?',
                                 (TODAY,)).fetchall()
            except sqlite3.Error:
                continue
            for oid, d in rows:
                if oid and (oid not in 出 or d > 出[oid]):
                    出[oid] = d
        return 出

    未来 = _未来的单()
    签收未来 = _未来的单(只看=("pickup", "pickup_item", "pkg_pickup", "delivery_notice"))
    坏, 不该我管 = [], []
    for r in c.execute("select id, finished_at, created from ordr"):
        oid, fin, 下单 = r
        最晚 = 未来.get(oid)
        if fin and str(fin)[:10] > TODAY:
            最晚 = max(最晚 or "", str(fin)[:10])
        if not 最晚:
            continue
        # ⚠️ **只挪「时间线已经走到交付」的单。**
        # 2026-09-27 踩到:一张 `待发货`、`finished_at` 是 NULL 的单因为别的已发生列
        # 在未来被选中,整条时间线一压,它的工厂回传跑到了下单之前。
        # **在办的单的时间线本来就没结束,压缩它没有意义** —— 压到哪儿算「完」?
        # 这种单的未来值是**别的写口用了机器时钟**,该去修那个写口,不是在这儿挪数据。
        # 所以报出来,不动它。
        if not fin and oid not in 签收未来:
            不该我管.append((oid, 最晚)); continue
        坏.append((oid, (最晚 + " 23:59") if not (fin and str(fin)[:10] == 最晚) else fin, 下单))
    if 不该我管:
        说(f"  ℹ {len(不该我管)} 张**还在办**的单有「已发生的事」落在未来"
          f"(例:{不该我管[:2]})—— **这个脚本不动它们**:"
          f"在办的时间线没结束,压缩它没有意义。那是某个写口用了机器时钟,去修那个写口。")
    if not 坏:
        说("  没有「已经交付、而且有已发生的事落在今天之后」的单,不动。"); c.close(); return 0
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
                    新 = 新日.isoformat() + str(v)[10:]
                    # ⚠️ **分钟粒度的底线。** 这个脚本的文档写着「一个时间点都不会跑到
                    # 下单之前」—— 而那句话**只在「天」这个粒度上成立**:
                    # 2026-09-27 踩到,一条 09-24 **09:05** 的回传被挪到 09-23 09:05,
                    # 而下单是 09-23 **09:25** —— 同一天,时刻更早。
                    # 按天算日期却**保留原来的时刻**,就会漏这一种。
                    if 下单 and 新 < str(下单)[:16]:
                        新 = str(下单)[:16]
                    上[k] = 新
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
    if "--selftest" in sys.argv:
        print("clamp 自测 · 合成夹具(不碰真库)")
        print("=" * 66)
        sys.exit(_自测())
    print("把「已经发生的事落在未来」的单挪回来")
    print("=" * 66)
    剩 = 修()
    名字里的年月()
    sys.exit(1 if 剩 else 0)

