#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小程序浏览数据 · 铺得对不对、和订单对不对得上、查询收不收范围

    python3 backend/browse_check.py

## 为什么要有这个
用户 2026-11-28 拍:虚拟数据加「小程序浏览情况」(一个动作一行、和已有订单对得上、口径拟一份、
造数据 + 给助手加查询)。造数在 `tools/backfill_browse.py`,口径在 `knowledge/browse.py`,
查询在 `backend/browse_query.py`(挂到助手上那一步等工具说明区的维护方回来)。

**「对得上订单」是这块数据唯一值钱的地方** —— 对不上的话,拿它算「浏览 → 加购 → 下单」得出的是假结论。
所以这条检查最硬的一段是逐笔对订单。

## 查什么(三层)
1. **口径**:`knowledge/browse.漏斗` 在手算答案的小样本上算得对(按人数、停留取中位、浏览 0 人的不出现)
2. **真库**:
   · 样本量先报,不到下限就红(「没铺」≠「都对」)
   · 事件名只有口径里那六个;停留秒只在「离开详情」、且在上下限之内;订单号只在「下单」
   · 每次进小程序里,同一件商品「进入详情」和「离开详情」次数相等
   · **每一笔小程序订单都有「下单」行,时刻 = 订单时刻,人对得上**;别的渠道的单没有「下单」行;「下单」指的单都在
   · 没有一行落到世界明天及以后
   · 形状(相对指标,验性质不逐例):随便看看的标品停留中位数贴着口径;看了没买占大头
3. **接线**:重建流程里有这一步;查询真调得通、而且**别店店长看不了这个客户**(范围闸真在)

形状那两条是**性质**不是逐例真值 —— 参数是拟的、会改,逐例钉死会在改参数那天过期且只会开始误报。
"""
import datetime as dt
import os
import sqlite3
import sys
from statistics import median

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
import browse as K   # noqa: E402

G, R, D = "\033[32m", "\033[31m", "\033[0m"
行数下限, 会话下限, 小程序单下限 = 1000, 100, 50
表 = "mp_event"


# ── 1. 口径(手算答案)──────────────────────────────────────────────────
def 口径样本():
    行 = [
        # A 看了 P1 两次、加购两次(按人只算 1)、停 10 / 30 秒;B 看了 P1 一次、停 20 秒、下单
        dict(customer_id="A", event=K.进入详情, spu="P1"), dict(customer_id="A", event=K.加购, spu="P1"),
        dict(customer_id="A", event=K.离开详情, spu="P1", dwell_s=10),
        dict(customer_id="A", event=K.进入详情, spu="P1"), dict(customer_id="A", event=K.加购, spu="P1"),
        dict(customer_id="A", event=K.离开详情, spu="P1", dwell_s=30),
        dict(customer_id="B", event=K.进入详情, spu="P1"), dict(customer_id="B", event=K.离开详情, spu="P1", dwell_s=20),
        dict(customer_id="B", event=K.下单, spu="P1", order_id="O1"),
        # P2 只有一行「分享」、没人进过详情 → 浏览 0 人,不出现
        dict(customer_id="C", event=K.分享, spu="P2"),
        # 进入列表那一行没有 spu,不算任何商品
        dict(customer_id="A", event=K.进入列表, spu=None),
    ]
    答 = {"P1": {"浏览次数": 3, "浏览人数": 2, "停留中位秒": 20, "加购人数": 1, "分享人数": 0, "下单人数": 1,
                 "加购率": 0.5, "分享率": 0.0, "转化率": 0.5}}
    return 行, 答


def 查口径():
    行, 答 = 口径样本()
    得 = K.漏斗(行)
    bad = []
    if set(得) != set(答):
        bad.append(f"口径:出现的商品是 {sorted(得)},应为 {sorted(答)}(浏览 0 人的不该出现)")
    for s, 应 in 答.items():
        for k, v in 应.items():
            if 得.get(s, {}).get(k) != v:
                bad.append(f"口径:{s} 的「{k}」算成 {得.get(s, {}).get(k)},应为 {v}")
    return bad


# ── 2. 真库 ──────────────────────────────────────────────────────────
def _今(db):
    from contextlib import closing
    with closing(sqlite3.connect(db)) as c:
        r = c.execute("SELECT v FROM world_meta WHERE k='world_today'").fetchone()
    return dt.date.fromisoformat(r[0]) if r else dt.date.today()


def 查真库(db):
    """→ (bad, 样本说明, 没东西可验?)"""
    bad = []
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (表,)).fetchone():
            return [], f"库里没有 {表} 表", True
        n, n会 = c.execute(f"SELECT COUNT(*), COUNT(DISTINCT session_id) FROM {表}").fetchone()
        小单 = [r for r in c.execute(
            "SELECT o.id, o.customer_id, o.created FROM ordr o WHERE o.source='微信小程序' "
            "AND EXISTS (SELECT 1 FROM ordr_item i JOIN product p ON p.spu=i.spu WHERE i.order_id=o.id) ORDER BY o.id")]
        说 = f"{n} 行 / {n会} 次进小程序 / 小程序订单 {len(小单)} 笔"
        if n < 行数下限 or n会 < 会话下限 or len(小单) < 小程序单下限:
            return [], 说 + f"(下限 {行数下限} 行 / {会话下限} 次 / {小程序单下限} 笔)", True

        # 字段形状
        怪名 = c.execute(f"SELECT event, COUNT(*) FROM {表} WHERE event NOT IN ({','.join('?' * len(K.事件们))}) "
                         "GROUP BY event", K.事件们).fetchall()
        if 怪名:
            bad.append(f"事件名不在口径里:{怪名[:5]}")
        x = c.execute(f"SELECT COUNT(*) FROM {表} WHERE (event=? AND (dwell_s IS NULL OR dwell_s<? OR dwell_s>?)) "
                      "OR (event<>? AND dwell_s IS NOT NULL)",
                      (K.离开详情, K.停留下限秒, K.停留上限秒, K.离开详情)).fetchone()[0]
        if x:
            bad.append(f"停留秒有 {x} 行不对(只该在「离开详情」、且在 {K.停留下限秒}–{K.停留上限秒} 秒)")
        x = c.execute(f"SELECT COUNT(*) FROM {表} WHERE (event=? AND order_id IS NULL) OR (event<>? AND order_id IS NOT NULL)",
                      (K.下单, K.下单)).fetchone()[0]
        if x:
            bad.append(f"订单号有 {x} 行不对(只该在「下单」那一行、且必填)")
        x = c.execute(f"""SELECT COUNT(*) FROM (SELECT session_id, spu,
                              SUM(event=?) a, SUM(event=?) b FROM {表} WHERE spu IS NOT NULL
                              GROUP BY session_id, spu HAVING a<>b)""", (K.进入详情, K.离开详情)).fetchone()[0]
        if x:
            bad.append(f"{x} 处同一次里同一件「进入详情」和「离开详情」次数对不上")

        # 对订单
        下 = {}
        for oid, cid, ts in c.execute(f"SELECT order_id, customer_id, MIN(ts) FROM {表} WHERE event=? GROUP BY order_id, customer_id",
                                      (K.下单,)):
            下.setdefault(oid, []).append((str(cid), ts))
        主 = dict(c.execute("SELECT id, merged_into FROM customer WHERE merged_into IS NOT NULL").fetchall())
        def 同人(a, b):
            a, b = str(a), str(b)
            return a == b or 主.get(a) == b or 主.get(b) == a or (主.get(a) and 主.get(a) == 主.get(b))
        缺, 时错, 人错 = [], [], []
        for oid, cid, cr in 小单:
            if oid not in 下:
                缺.append(oid); continue
            应时 = (str(cr) + ":00")[:19] if len(str(cr)) == 16 else str(cr)[:19]
            if not any(ts == 应时 for _, ts in 下[oid]):
                时错.append(f"{oid}({下[oid][0][1]} ≠ {应时})")
            if not any(同人(x, cid) for x, _ in 下[oid]):
                人错.append(oid)
        for 名, xs in (("没有「下单」行", 缺), ("「下单」时刻 ≠ 订单时刻", 时错), ("「下单」的人和订单的人对不上", 人错)):
            if xs:
                bad.append(f"小程序订单 {len(xs)} 笔{名}:{', '.join(xs[:5])}" + (f" …还有 {len(xs) - 5} 笔" if len(xs) > 5 else ""))
        小单号 = {r[0] for r in 小单}
        别渠道 = [o for o in 下 if o not in 小单号]
        if 别渠道:
            在 = {r[0] for r in c.execute(f"SELECT id FROM ordr WHERE id IN ({','.join('?' * len(别渠道))})", 别渠道)}
            悬 = [o for o in 别渠道 if o not in 在]
            非小 = [o for o in 别渠道 if o in 在]
            if 悬:
                bad.append(f"「下单」行指的订单 {len(悬)} 笔不存在:{', '.join(悬[:5])}")
            if 非小:
                bad.append(f"别的渠道下的单 {len(非小)} 笔在小程序里有「下单」行:{', '.join(非小[:5])}")

        # 人人都有(11-28 用户补「给所有顾客都模拟上」):世界今天之前建档的、没并入别人的,至少有一次
        今s = _今(db).isoformat()
        没有 = [r[0] for r in c.execute(
            f"SELECT id FROM customer cu WHERE merged_into IS NULL AND substr(created,1,10) < ? "
            f"AND NOT EXISTS (SELECT 1 FROM {表} e WHERE e.customer_id=cu.id) ORDER BY id", (今s,))]
        if 没有 and K.每人至少进来一次:
            bad.append(f"人人都有:{len(没有)} 个客户一次小程序都没进过:{', '.join(map(str, 没有[:5]))}"
                       + (f" …还有 {len(没有) - 5} 个" if len(没有) > 5 else ""))
        # 不落到世界明天
        明 = (_今(db) + dt.timedelta(days=1)).isoformat()
        x = c.execute(f"SELECT COUNT(*), MAX(ts) FROM {表} WHERE ts>=?", (明,)).fetchone()
        if x[0]:
            bad.append(f"{x[0]} 行落到了世界明天及以后(最晚 {x[1]})")

        # 形状(性质)
        随看 = [r[0] for r in c.execute(f"""
            SELECT e.dwell_s FROM {表} e JOIN product p ON p.spu=e.spu
            WHERE e.event=? AND p.kind='标品' AND e.session_id NOT IN
                  (SELECT session_id FROM {表} WHERE event=?)
            LIMIT 20000""", (K.离开详情, K.下单))]
        if len(随看) >= 200:
            m, 应 = median(随看), K.停留中位秒["标品"]
            if not (应 * 0.6 <= m <= 应 * 1.8):     # 混着「下单前回来看」(有意向、停得久)那几次,中位会偏上
                bad.append(f"形状:标品详情停留中位 {m} 秒,口径中位 {应} 秒 —— 偏得太远,造数没按口径走")
        看人, 买人 = c.execute(f"SELECT COUNT(DISTINCT customer_id||'|'||spu) FROM {表} WHERE event=?", (K.进入详情,)).fetchone()[0], \
                    c.execute(f"SELECT COUNT(DISTINCT customer_id||'|'||spu) FROM {表} WHERE event=?", (K.下单,)).fetchone()[0]
        if not 买人 or 买人 / max(1, 看人) > 0.5:
            bad.append(f"形状:看过的「人 × 商品」{看人} 对里下单的 {买人} 对 —— 「看了没买」该占大头")
        说 += f";逐笔对了 {len(小单)} 笔小程序订单"
        return bad, 说, False
    finally:
        c.close()


# ── 3. 接线 ──────────────────────────────────────────────────────────
def 查接线(db):
    bad = []
    src = open(os.path.join(ROOT, "tools", "rebuild.sh"), encoding="utf-8").read()
    if '"tools/backfill_browse.py"' not in src:
        bad.append("接线:tools/rebuild.sh 的步骤里没有 tools/backfill_browse.py —— 从零建库(CI)就没有浏览数据")
    import api, browse_query as api_browse
    旧 = api.DB
    api.DB = db
    try:
        q = lambda s, *a: api._rows(s, *a)
        cs = q(f"SELECT e.customer_id id FROM {表} e GROUP BY e.customer_id ORDER BY COUNT(*) DESC LIMIT 1")
        hq = q("SELECT no, role, name, shop FROM staff WHERE role='总部运营' AND status='启用' LIMIT 1")
        if not cs or not hq:
            return bad + ["接线:取不到一个有浏览的客户 / 一个总部运营 —— 夹具没立起来"]
        cid = cs[0]["id"]
        店 = q("SELECT shop FROM customer WHERE id=?", cid)[0]["shop"]
        别店长 = q("SELECT no, role, name, shop FROM staff WHERE role='店长' AND status='启用' AND shop<>? LIMIT 1", 店)
        with api.as_user(dict(hq[0])):
            h = api_browse.browse_history(cid, 730)
            f = api_browse.browse_funnel(730, limit=3)
        if "error" in h or not h.get("看过的商品"):
            bad.append(f"接线:总部运营查 {cid} 的浏览没查到东西:{str(h)[:120]}")
        if "error" in f or not f.get("列出"):
            bad.append(f"接线:总部运营查漏斗没查到东西:{str(f)[:120]}")
        if 别店长:
            with api.as_user(dict(别店长[0])):
                h2 = api_browse.browse_history(cid, 730)
            if "error" not in h2:
                bad.append(f"范围:别店店长看到了 {cid} 的浏览 —— 范围闸没生效")
        else:
            bad.append("接线:找不到一个别店的店长 —— 范围闸这一条没验到")
    finally:
        api.DB = 旧
    return bad


咬合 = [
    ("漏斗按次数数加购(不按人)", "」算成 "),
    ("查询去掉范围闸", "范围:别店店长看到了"),
    ("重建流程里删掉造浏览那一步", "接线:tools/rebuild.sh 的步骤里没有"),
]


def main():
    print("小程序浏览数据 · 铺得对、对得上订单、查询收范围\n" + "=" * 72)
    b = 查口径()
    if b:
        for x in b: print(f"  {R}❌ {x}{D}")
        print(f"{R}❌ 口径没过 —— 真库那层不算数{D}"); return 1
    print("  ✅ 口径:手算样本 1 件商品、9 个数全对")
    from dbpath import 路径
    db = 路径()
    bad, 说, 空 = 查真库(db)
    print(f"  真库:{说}")
    if 空:
        print(f"{R}❌ 没东西可验 —— 不是「都对」,是没铺(跑 python3 tools/backfill_browse.py){D}"); return 1
    bad += 查接线(db)
    for x in bad: print(f"  {R}❌ {x}{D}")
    if bad:
        print(f"{R}❌ {len(bad)} 处不对{D}"); return 1
    print(f"{G}✅ 小程序浏览数据:结构对、每笔小程序订单都对得上、不落未来、形状贴口径、查询收范围{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
