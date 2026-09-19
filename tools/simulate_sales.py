#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟标品销量 —— 让库存预警的「可售天数」算得出来。

## 为什么要造

库存预警对每个 SKU 都说「算不出可售天数」,而那是对的:
种子库里有销量的 SKU 每个只卖过一笔、订单只跨 18 天,**一个点画不出斜率**。
缺的是销量数据,不是算法。

## 这批数据是什么、不是什么

**整个库本来就都是种子数据** —— 所以这里不说「这些是虚构的」,
那句话言下之意是「别的是真的」,而那是假的。
这批订单的标记说的是**来路**:哪一批、哪个脚本、能不能整批删掉重来。

    sim_batch       order_id → batch(`simulate_sales/v1`)
    sim_batch_sku   被这批数据重算过库存的 SKU,以及重算前的在手/占用(回滚用)
    stock_log.ref   这批写的流水一律 `SIM-` 开头

出口上「可售天数不能拿去下真实采购单」的 demo 标记由库存预警那边**无条件打**,
不依赖这张表。

## 流水记的是「可用」,不是「在手」

系统里 `sku.stock` 是在手、`sku.locked` 是已占用,**可用 = 在手 − 已占用**
(`server.py`、`api.py`、`knowledge/stockalert.py` 三处一致)。
流水的类型有「订单占用 / 订单释放」而**没有「发货出库」**,所以一条链只能记可用:

    入库 / 退货入库    +     报损     −     盘点调整   ±
    订单占用(下单)   −     订单释放(取消) +
    发货               在手和占用各减一样多 → 可用不变 → **不写流水**

于是三样都能从流水推出来:

    链尾 after_n            = 可用
    sku.locked              = 这个 SKU 上**还没发货**的占用之和(ref 连回订单状态)
    sku.stock               = 可用 + locked

⚠️ **`stock_log` 不是全库库存的唯一真相来源。** 这张表从来没定义过自己记的是哪个量:
种子那 60 条是按「在手」写的,而流水类型是按「可用」设计的 —— 两套读法在表上长得一模一样。
定义现在写在 `knowledge/stockalert.py`(流水记的是可用);种子那几十个对不上的单独挂账,
这里不改。没被模拟的 SKU 大多**根本没有流水**。
「有一条完整的流水链」和「链是全的」长得一模一样 —— `--report` 会现算出对不上的有几个。

## 只造哪些

只造**在售标品**里「**既没有种子流水、也没有种子订单行**」的 SKU ——
这样 locked 能完全由这批订单推出来,不和种子里来路不明的占用数混在一起。

每个 SPU **从自己的上架日开始卖**:
spec_check C3 要求流水时间不早于商品建档,而上架前卖货本来也说不通。
标品最早 2026-02 才上架,所以跨度到不了 12 个月 —— **这是主数据的事实,不是参数没调好**。

## 刻意不做的

- **不回写客户汇总字段**(12 个月实付/单数/闲置天数)—— 回写了,这批订单会顺着
  会员等级和生命周期流出去。代价是这些客户的汇总和名下订单对不上,`--report` 列出清单
- **activity 一律 NULL** —— 挂上活动,这批成交会进活动投入产出
- **不做定制品** —— 会连带分部位选料对账和量体超期;可售天数只对标品有意义
- **不碰夹具客户** —— 客户池直接用 `run_journey.pick_customers`,不在这儿另抄一份排除规则
- **不碰 `truth` 表和账户凭据列**
- **留着取消单和待付款单** —— 它们是库存预警「只数卖掉了的」那条过滤的活体测试数据

## 用法

    python3 tools/simulate_sales.py              先整批回滚旧的,再按固定种子造一批
    python3 tools/simulate_sales.py --dry        只算不写,看统计
    python3 tools/simulate_sales.py --report     从库里现算:覆盖、对账、客户汇总对不上的清单
    python3 tools/simulate_sales.py --rollback   整批删掉,库存恢复成造之前的数

再生顺序:`seed.py` → `run_journey.py 42` → `simulate_sales.py` → **`order_mix.py`**。

⚠️ **单独重跑这一步之后,必须接着跑 `order_mix.py`。** 业务 2026-09-18 改了口径:
这批单里有一部分要改成定制单、客户汇总要按订单重算(上面「刻意不做的」前两条被推翻了,
留着是因为它们说的是**这一步自己**不做 —— 那两件事现在由 order_mix 做)。
回滚时会先调 `order_mix.回滚()`,把叠在这批上的那一层撤干净。
"""
import os, sys, math, heapq, random, sqlite3, argparse, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "fakedata"))
import ledger as LG          # 台账链:每一行 after = before + 增减,而且接得上上一行
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "knowledge"))
DB = os.path.join(ROOT, "backend", "lanxiu.db")

BATCH = "simulate_sales/v1"
SEED = 20260915
# 截止日 = 演示世界的「今天」(seed.py 的 T)。原来是 09-15 —— 于是库里有两个今天:
# 会员 / 生命周期按 08-31 算,订单却造到了 09-15,客户档案上「最近互动 8 月 20 日」
# 而订单列表里有他 9 月 10 日的单。**一个世界只能有一个「现在」**(用户 2026-09-19 定)。
END = dt.date(2026, 8, 31)
窗口 = 365                          # 用户:「分散到过去的多个日期时间,最好是过去一年内」
CUT = dt.datetime.combine(END, dt.time(20, 0))
ORDERS_PER_DAY = 110                # 全部 SPU 都在售时的日均单量(实际随上架逐步爬升)
# 230 → 110:订单从半年摊到一年,总量仍在两万五上下(用户拍板的量)
# 原来是 35,理由是「能安全挂单的客户只有 31 个,单量越大人均越离谱」。
# 2026-09-18 用户拍板客户 1000 / 订单约 2.5 万,`grow_customers.py` 补齐了人 ——
# **先有人,再放量**:顺序反过来就是把 2.5 万单压在 31 个人头上。
ID_BASE = 6488012800000000000       # 种子和旅程用 64880127197145600xx,不重叠

# ── 季节:按品类编码给 12 个月的系数 ────────────────────────────────────
# **编码逐个点名,不按名字里的字猜** —— 「长衫 / 长袄」一个名字挂着两个编码,
# 按字猜会把冬款和夏款搅在一起。没点名的品类走平的,而且 `--dry` 会把它们列出来。
_冬 = (1.8, 1.6, 1.0, 0.6, 0.4, 0.3, 0.3, 0.4, 0.7, 1.1, 1.5, 1.9)
_夏 = (0.4, 0.5, 0.9, 1.3, 1.6, 1.8, 1.8, 1.6, 1.1, 0.7, 0.5, 0.4)
_春秋 = (0.7, 0.8, 1.3, 1.4, 1.1, 0.8, 0.7, 0.8, 1.2, 1.4, 1.1, 0.8)
SEASON = {   # 〔种下 S3〕
    "C010102": _冬, "C010302": _冬, "C020201": _冬,                  # 袄 / 长衫长袄
    "C010101": _夏, "C010104": _夏, "C020202": _夏, "C010301": _夏,  # 襦衫 / 半臂 / 大袖衫
    "C040303": _夏,                                                   # 披帛
    "C020101": _春秋, "C030102": _春秋, "C010105": _春秋,             # 圆领袍
    "C020102": _春秋, "C010103": _春秋,                               # 道袍 / 褙子
}

# ── 节日:节前一段时间需求抬高 ───────────────────────────────────────
# ⚠️ **日期是按农历推的近似值,强度是编的** —— 这是需求形状的假设,不是历史销量。
FESTIVALS = [  # (日子, 名字, 峰值倍数, 节前几天开始抬)   # 〔种下 S4〕
    (dt.date(2025, 10, 1), "国庆", 1.5, 10),
    (dt.date(2025, 10, 6), "中秋", 1.4, 12),
    (dt.date(2026, 2, 17), "春节", 2.0, 21),
    (dt.date(2026, 3, 30), "花朝(汉服出行日)", 1.5, 10),
    (dt.date(2026, 4, 19), "上巳", 1.8, 14),
    (dt.date(2026, 8, 19), "七夕", 1.8, 14),
    (dt.date(2026, 9, 25), "中秋", 1.4, 12),
    (dt.date(2026, 10, 1), "国庆", 1.5, 10),
]

# 尺码:M/L 大头。童装身高码、鞋码、均码各自在 SPU 内部平分。
SIZE_W = {"S": 0.55, "M": 1.0, "L": 0.95, "XL": 0.5, "35": 0.5}   # 〔种下 S5〕

SOURCES = (("微信小程序", 45), ("官网", 25), ("门店 Pad", 20), ("客服代下单", 10))   # 〔种下 S9〕
OPERATORS = ("60000008 魏欣新", "60000004 周恒东", "60000001 张静静")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def ts(t):
    return t.strftime("%Y-%m-%d %H:%M")


def pick(rng, pairs):
    tot = sum(w for _, w in pairs)
    x = rng.random() * tot
    for v, w in pairs:
        x -= w
        if x <= 0:
            return v
    return pairs[-1][0]


def festival(d):
    m = 1.0
    for day, _, peak, pre in FESTIVALS:
        gap = (day - d).days
        if 0 <= gap <= pre:
            m = max(m, 1 + (peak - 1) * (1 - gap / (pre + 1)))
        elif -2 <= gap < 0:            # 节后两天余温
            m = max(m, 1 + (peak - 1) * 0.3)
    return m


def poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 40:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


# ── 回滚 ────────────────────────────────────────────────────────────
def rollback(c, quiet=False):
    have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "sim_batch" not in have:
        n_log = c.execute("SELECT COUNT(*) FROM stock_log WHERE ref LIKE 'SIM-%'").fetchone()[0]
        if n_log:
            raise SystemExit(f"❌ 没有 sim_batch 表,却有 {n_log} 条 SIM- 流水 —— "
                             f"上一次造到一半断了?先人工看一眼,别自动删")
        return 0
    n = c.execute("SELECT COUNT(*) FROM sim_batch").fetchone()[0]
    # ⚠️ **订单分型(order_mix.py)是叠在这一批上的**:它把一部分模拟单改成了定制单、
    # 给它们挂了分部位选料 / 售后 / 维保,还删过种子的旧售后、重算过客户汇总。
    # 先让它把自己那一层撤干净,再删这一批 —— 反过来的话,那些行会指向不存在的订单。
    import order_mix
    order_mix.回滚(c, quiet=quiet)
    for t in ("fitting", "aftersale", "maintain"):
        if t in have:
            c.execute(f"DELETE FROM {t} WHERE order_id IN (SELECT order_id FROM sim_batch)")
    c.execute("DELETE FROM item_part_choice WHERE item_id IN (SELECT id FROM ordr_item "
              "WHERE order_id IN (SELECT order_id FROM sim_batch))")
    if "sim_batch_sku" in have:
        c.execute("""UPDATE sku SET stock=(SELECT stock_before FROM sim_batch_sku b WHERE b.sku=sku.code),
                                    locked=(SELECT locked_before FROM sim_batch_sku b WHERE b.sku=sku.code)
                     WHERE code IN (SELECT sku FROM sim_batch_sku)""")
    c.execute("DELETE FROM ordr_item WHERE order_id IN (SELECT order_id FROM sim_batch)")
    c.execute("DELETE FROM ordr WHERE id IN (SELECT order_id FROM sim_batch)")
    c.execute("DELETE FROM stock_log WHERE ref LIKE 'SIM-%'")
    c.execute("DROP TABLE IF EXISTS sim_batch_sku")
    c.execute("DROP TABLE sim_batch")
    if not quiet:
        print(f"已回滚:{n} 单,SIM- 流水全删,库存恢复成造之前的数")
    return n


# ── 取数 ────────────────────────────────────────────────────────────
def load_world(c):
    skus = [dict(r) for r in c.execute("""
        SELECT s.code, s.spu, s.size, s.price, s.stock, s.locked,
               p.name pname, p.category, p.created pcreated, p.on_shelf_at, p.pattern
        FROM sku s JOIN product p ON p.spu=s.spu
        WHERE p.kind='标品' AND p.status='上架' AND s.status<>'停用'
          AND s.code NOT IN (SELECT sku FROM stock_log WHERE sku IS NOT NULL)
          AND s.code NOT IN (SELECT sku FROM ordr_item WHERE sku IS NOT NULL)
        ORDER BY s.code""")]
    ver = {r["code"]: r["version"] for r in c.execute("SELECT code, version FROM pattern")}
    import run_journey
    ids = {r["id"] for r in run_journey.pick_customers(10 ** 6)}
    # ⚠️ **账户状态 `run_journey` 没排,这里补上。** 第一次跑就被 spec_check A15 抓到:
    # 模拟单挂到了「注销中」账户的客户身上,而「有在办业务的账户不得注销」——
    # 冷静期就是等这些事了结的。旅程造的单都走到完成所以撞不上,这批有待付款/待发货就撞上了。
    # 锁定的账户一并排掉:给一个登不上的账户挂上百单同样说不通。
    custs = [dict(r) for r in c.execute(
        """SELECT k.id, k.created, k.shop, k.advisor_no, k.addr FROM customer k
           LEFT JOIN account a ON a.id=k.account_id
           WHERE a.id IS NULL OR a.status='正常' ORDER BY k.id""")
        if r["id"] in ids]
    return skus, ver, custs


# ── 造 ──────────────────────────────────────────────────────────────
def simulate(skus, ver, custs, rng):
    from fsm import ORDER_PRD

    spus = {}
    for s in skus:
        launch = max(s["on_shelf_at"] or "9999", s["pcreated"] or "")[:10]
        s["launch"] = dt.date.fromisoformat(launch) if launch < "9999" else None
        s["w"] = SIZE_W.get(s["size"], 1.0) * math.exp(rng.gauss(0, 0.35))   # 颜色冷热
        spus.setdefault(s["spu"], []).append(s)
    live = {k: v for k, v in spus.items() if v[0]["launch"] and v[0]["launch"] <= END}
    # 长尾:SPU 热度按打乱后的名次取 1/名次
    order = sorted(live)
    rng.shuffle(order)
    heat = {spu: 1 / (i + 1) ** 0.9 for i, spu in enumerate(order)}   # 〔种下 S6〕
    K = ORDERS_PER_DAY / sum(heat.values())
    for spu, ss in live.items():
        tw = sum(s["w"] for s in ss)
        for s in ss:
            s["share"] = s["w"] / tw
            s["exp_day"] = K * heat[spu] * s["share"] * 1.18      # 期望日销件数(含多件)

    # 从一年前开始卖;更早上架的商品,首批货照样在它上架那天到(流水不早于建档)
    start = max(min(v[0]["launch"] for v in live.values()), END - dt.timedelta(days=窗口 - 1))
    # 回购倾向:对数正态。σ 原来是 1.0 —— 客户放到九百多个之后,尾巴拉出一个
    # **半年 689 单**的人(一天近 4 单)。σ=0.45 时最能买的大约是均值的四五倍,像熟客不像批发
    loyal = {c["id"]: math.exp(rng.gauss(0, 0.45)) for c in custs}   # 〔种下 S8〕
    # **每个 SKU 一本台账。** 原来是一个 dict 自己加加减减、自己拼 before/after ——
    # 那段逻辑写错了不会有任何东西报,因为每一行单看都正常。
    帐 = {s["code"]: LG.台账(s["code"], 起始=0) for ss in live.values() for s in ss}
    by_code = {s["code"]: s for ss in live.values() for s in ss}
    on_order = {k: 0 for k in 帐}
    stopped = {k for k in 帐 if rng.random() < 0.08}       # 供应商停供,卖完不补

    logs, orders, lost = [], [], 0
    ev, seq = [], 0

    def push(t, kind, **kw):
        nonlocal seq
        seq += 1
        heapq.heappush(ev, (t, seq, kind, kw))

    def log(t, code, kind, delta, ref, note=""):
        行 = 帐[code].记(ts(t), kind, delta, ref, note)
        if 行 is None:      # 余额不够 —— 台账拒绝记,不静默改数
            return None
        logs.append(dict(sku=code, spu=by_code[code]["spu"], kind=kind, delta=delta,
                         before_n=行["前"], after_n=行["后"], ref=ref,
                         operator="系统" if kind in ("订单占用", "订单释放") else rng.choice(OPERATORS),
                         ts=ts(t), note=note))
        return 行

    po = [0]

    def replenish(t, code):
        s = by_code[code]
        if code in stopped or on_order[code]:
            return
        if 帐[code].余额 > s["exp_day"] * 21 + 1:
            return
        qty = max(3, int(round(s["exp_day"] * rng.uniform(30, 50))))
        on_order[code] = qty
        arrive = t + dt.timedelta(days=rng.uniform(7, 15))
        arrive = arrive.replace(hour=10, minute=rng.randrange(0, 60))
        po[0] += 1
        push(arrive, "到货", code=code, qty=qty, ref=f"SIM-PO{arrive:%y%m%d}{po[0]:04d}")

    # 上架那天首批入库
    for ss in live.values():
        for s in ss:
            t0 = dt.datetime.combine(s["launch"], dt.time(9, rng.randrange(0, 50)))
            qty = max(3, int(round(s["exp_day"] * rng.uniform(35, 55))))
            po[0] += 1
            push(t0, "到货", code=s["code"], qty=qty, ref=f"SIM-PO{t0:%y%m%d}{po[0]:04d}")

    # 每天排好当天的下单,月初排盘点和报损
    d = start
    while d <= END:
        m = SEASON
        act = [(spu, heat[spu] * m.get(ss[0]["category"], (1,) * 12)[d.month - 1])
               for spu, ss in live.items() if ss[0]["launch"] <= d]
        if act:
            lam = K * sum(w for _, w in act) * festival(d) * (1.15 if d.weekday() >= 5 else 1.0)   # 〔种下 S7〕
            for _ in range(poisson(rng, lam)):
                t = dt.datetime.combine(d, dt.time(pick(rng, [(h, 3 if 19 <= h <= 22 else 2 if 12 <= h <= 14 else 1)
                                                              for h in range(9, 23)]),
                                                   rng.randrange(0, 60)))
                if t <= CUT:
                    push(t, "下单", spus=[pick(rng, act)] + ([pick(rng, act)] if rng.random() < 0.15 else []))
        if d.day == 1:
            for code in sorted(帐):
                if by_code[code]["launch"] < d and rng.random() < 0.03:
                    push(dt.datetime.combine(d, dt.time(17, 30)), "盘点", code=code)
                if by_code[code]["launch"] < d and rng.random() < 0.01:
                    push(dt.datetime.combine(d, dt.time(16, 0)), "报损", code=code)
        d += dt.timedelta(days=1)

    pool = sorted(custs, key=lambda c: c["created"] or "")
    oid = [ID_BASE]

    while ev:
        t, _, kind, kw = heapq.heappop(ev)
        # 截止之后的事还没发生 —— 原来补货单会一直排到截止后两周,流水里出现了「未来」的入库
        if t > CUT:
            continue
        if kind == "到货":
            code = kw["code"]
            on_order[code] = 0
            log(t, code, "入库", kw["qty"], kw["ref"])
        elif kind == "盘点":
            code = kw["code"]
            dlt = rng.choice((-2, -1, 1, 2))
            if 帐[code].够吗(-dlt if dlt < 0 else 0):
                log(t, code, "盘点调整", dlt, f"SIM-CK{t:%y%m%d}{code[-4:]}", "月度盘点差异修正")
        elif kind == "报损":
            code = kw["code"]
            if 帐[code].够吗(1):
                log(t, code, "报损", -1, f"SIM-DM{t:%y%m%d}{code[-4:]}", "运输途中破损")
                replenish(t, code)
        elif kind == "释放":
            for code, qty in kw["lines"]:
                log(t, code, "订单释放", qty, kw["ref"])
                replenish(t, code)   # 释放不会让它更缺,但顺手看一眼无害
        elif kind == "退货":
            for code, qty in kw["lines"]:
                log(t, code, "退货入库", qty, kw["ref"])
        elif kind == "下单":
            # 客户:建档早于下单的才挑得到(C3),老客更常回购
            ok = [c for c in pool if (c["created"] or "")[:10] <= t.strftime("%Y-%m-%d")]
            if not ok:
                continue
            cust = pick(rng, [(c, loyal[c["id"]]) for c in ok])
            lines = {}
            for spu in kw["spus"]:
                ss = live[spu]
                s = pick(rng, [(x, x["share"]) for x in ss])
                qty = pick(rng, ((1, 85), (2, 13), (3, 2)))
                if not 帐[s["code"]].够吗(qty):
                    lost += 1
                    replenish(t, s["code"])
                    continue
                lines[s["code"]] = lines.get(s["code"], 0) + qty
            if not lines:
                continue
            oid[0] += rng.randrange(1, 97)
            o_id = str(oid[0])
            ref = f"SIM-{o_id}"
            for code, qty in lines.items():
                log(t, code, "订单占用", -qty, ref)
                replenish(t, code)
            # 时间线先排全,再按截止时刻切出状态 —— 状态是推出来的,不是先抽再补时间
            paid = shipped = finished = cancelled = None
            refund = "未退款"
            if rng.random() < 0.05:
                tc = t + dt.timedelta(hours=rng.uniform(0.5, 30))
                if tc <= CUT:
                    status, cancelled = "取消", tc
                    push(tc, "释放", lines=list(lines.items()), ref=ref)
                else:
                    status = "待付款"
            else:
                tp = t + dt.timedelta(minutes=rng.uniform(3, 180))
                if (CUT - t).days < 3 and rng.random() < 0.35:
                    tp = CUT + dt.timedelta(days=1)          # 还没付
                if tp > CUT:
                    status = "待付款"
                else:
                    paid = tp
                    tsh = tp + dt.timedelta(days=rng.uniform(0.5, 3))
                    if tsh > CUT:
                        status = "待发货"
                    else:
                        shipped = tsh
                        tdel = tsh + dt.timedelta(days=rng.uniform(2, 4))
                        tf = tsh + dt.timedelta(days=rng.uniform(6, 12))
                        if CUT < tdel:
                            status = "已发货"
                        elif CUT < tf:
                            status = "待完成"
                            if rng.random() < 0.01:
                                refund = "退款中"
                        else:
                            status, finished = "完成", tf
                            if rng.random() < 0.025:
                                tr = tf + dt.timedelta(days=rng.uniform(1, 6))
                                if tr <= CUT:
                                    refund = "已退款"
                                    push(tr, "退货", lines=list(lines.items()),
                                         ref=f"SIM-AS{o_id[-10:]}")
                                else:
                                    refund = "退款中"
            items = []
            for code, qty in lines.items():
                s = by_code[code]
                base = round((s["price"] or 0) * qty, 2)
                pv = ver.get(s["pattern"]) if s["pattern"] else None
                items.append(dict(sku=code, spu=s["spu"], name=s["pname"], price=s["price"], qty=qty,
                                  base=base, pv=pv))
            goods = round(sum(i["base"] for i in items), 2)
            freight = 0.0 if goods >= 2000 else 28.0
            amount = round(goods + freight, 2)
            src = pick(rng, SOURCES)
            stamps = [x for x in (t, paid, shipped, finished, cancelled) if x]
            orders.append(dict(
                id=o_id, customer_id=cust["id"], status=status, prd_status=ORDER_PRD[status],
                advisor_no=cust["advisor_no"], shop=cust["shop"],
                source=src, delivery="配送到店" if (src == "门店 Pad" or rng.random() < 0.3) else "配送到客户",
                amount=amount, goods=goods, freight=freight,
                received=amount if paid else 0.0, refund=refund, addr=cust["addr"],
                created=ts(t), updated=ts(max(stamps)),
                paid_at=paid and ts(paid), shipped_at=shipped and ts(shipped),
                finished_at=finished and ts(finished), cancelled_at=cancelled and ts(cancelled),
                items=items))

    # 期末:占用 = 还没发货的;在手 = 可用 + 占用
    hold = {}
    for o in orders:
        if o["status"] in ("待付款", "待发货"):
            for i in o["items"]:
                hold[i["sku"]] = hold.get(i["sku"], 0) + i["qty"]
    # 生成时就查一遍链,不等灌完再说 —— **断链在灌完之后极难追**
    断 = [x for code in 帐 for x in LG.查链(帐[code].行, 起始=0)]
    if 断:
        raise SystemExit(f"❌ 台账链断了 {len(断)} 处,不往下走:{断[:2]}")
    final = {code: (帐[code].余额 + hold.get(code, 0), hold.get(code, 0)) for code in 帐}
    return orders, logs, final, dict(lost=lost, start=start, live_spu=len(live),
                                     live_sku=len(帐), stopped=len(stopped),
                                     flat=sorted({ss[0]["category"] for ss in live.values()
                                                  if ss[0]["category"] not in SEASON}))


def write(c, orders, logs, final, skus):
    c.execute("CREATE TABLE sim_batch(order_id TEXT PRIMARY KEY, batch TEXT NOT NULL)")
    c.execute("""CREATE TABLE sim_batch_sku(sku TEXT PRIMARY KEY, batch TEXT NOT NULL,
                 stock_before INT, locked_before INT)""")
    before = {s["code"]: (s["stock"], s["locked"]) for s in skus}
    src_note = f"模拟造数({BATCH}):取生成时版型的当前版本"
    for o in orders:
        # ⚠️ 2026-09-16:`ordr.advisor`(名字列)**已全库删除**。只去掉那一列,生成逻辑没动。
        c.execute("""INSERT INTO ordr(id,customer_id,kind,status,shop,source,activity,delivery,
                     amount,payable,created,updated,prd_status,goods_amount,freight,received,
                     refund_status,addr,paid_at,shipped_at,finished_at,cancelled_at,advisor_no)
                     VALUES(?,?,'标品订单',?,?,?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (o["id"], o["customer_id"], o["status"], o["shop"], o["source"],
                   o["delivery"], o["amount"], o["amount"], o["created"], o["updated"], o["prd_status"],
                   o["goods"], o["freight"], o["received"], o["refund"], o["addr"], o["paid_at"],
                   o["shipped_at"], o["finished_at"], o["cancelled_at"], o["advisor_no"]))
        for i in o["items"]:
            c.execute("""INSERT INTO ordr_item(order_id,sku,name,tag,price,qty,spu,base_amount,
                         custom_amount,total,pattern_version,pattern_version_src)
                         VALUES(?,?,?,'标品',?,?,?,?,0,?,?,?)""",
                      (o["id"], i["sku"], i["name"], i["price"], i["qty"], i["spu"], i["base"],
                       i["base"], i["pv"], src_note if i["pv"] is not None else None))
        c.execute("INSERT INTO sim_batch VALUES(?,?)", (o["id"], BATCH))
    logs.sort(key=lambda r: r["ts"])
    c.executemany("""INSERT INTO stock_log(sku,spu,kind,delta,before_n,after_n,ref,operator,ts,note)
                     VALUES(:sku,:spu,:kind,:delta,:before_n,:after_n,:ref,:operator,:ts,:note)""", logs)
    for code, (stock, locked) in final.items():
        b = before[code]
        c.execute("INSERT INTO sim_batch_sku VALUES(?,?,?,?)", (code, BATCH, b[0], b[1]))
        c.execute("UPDATE sku SET stock=?, locked=? WHERE code=?", (stock, locked, code))


# ── 报告:一律从库里现算,不信生成时内存里的数 ─────────────────────────
def report(c):
    import stockalert as SA
    have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "sim_batch" not in have:
        print("库里没有这一批(sim_batch 不在)")
        return 0
    bad = []
    rows = [dict(r) for r in c.execute("""
        SELECT i.sku, i.qty, o.id, o.status, o.refund_status, o.created, o.customer_id, o.received
        FROM ordr_item i JOIN ordr o ON o.id=i.order_id
        WHERE o.id IN (SELECT order_id FROM sim_batch)""")]
    n_orders = c.execute("SELECT COUNT(*) FROM sim_batch").fetchone()[0]
    st = {}
    for r in c.execute("SELECT o.status, o.refund_status, COUNT(*) n FROM ordr o "
                       "WHERE o.id IN (SELECT order_id FROM sim_batch) GROUP BY 1,2 ORDER BY 3 DESC"):
        st[f"{r['status']}" + (f"·{r['refund_status']}" if r["refund_status"] != "未退款" else "")] = r["n"]
    sold = {}
    for r in rows:
        if SA.卖掉了(r["status"], r["refund_status"])[0]:
            sold[r["sku"]] = sold.get(r["sku"], 0) + 1
    span = c.execute("SELECT MIN(created), MAX(created) FROM ordr "
                     "WHERE id IN (SELECT order_id FROM sim_batch)").fetchone()
    n_c = c.execute("SELECT COUNT(DISTINCT customer_id) FROM ordr "
                    "WHERE id IN (SELECT order_id FROM sim_batch)").fetchone()[0]
    print(f"这一批({BATCH}):{n_orders} 单 · {len(rows)} 行 · {span[0][:10]} → {span[1][:10]}")
    # 季节性覆盖要明说 —— 区间短,冬款的曲线就是看不全,这是事实不是缺陷
    d0, d1 = dt.date.fromisoformat(span[0][:10]), dt.date.fromisoformat(span[1][:10])
    节 = [f"{n}({d})" for d, n, _, _ in FESTIVALS if d0 <= d <= d1]
    冬月 = sorted({m for m in (11, 12, 1, 2, 3)
                  if any(dt.date(y, m, 1) <= d1 and dt.date(y, m, 28) >= d0 for y in (d0.year, d1.year))})
    print(f"  ⚠️ 区间只覆盖 {d0} 到 {d1}(约 {(d1 - d0).days // 30} 个月),落在里面的节日:"
          f"{'、'.join(节) or '无'};冬款只看得到 {冬月 or '无'} 月"
          f"{'' if 2 in 冬月 else ',**春节不在区间里**'} —— 季节性是弱的,而这是主数据上架日决定的")
    _mx = c.execute("SELECT MAX(n) FROM (SELECT COUNT(*) n FROM ordr WHERE id IN "
                    "(SELECT order_id FROM sim_batch) GROUP BY customer_id)").fetchone()[0] or 0
    _avg = n_orders / max(n_c, 1)
    print(f"  {'⚠️' if _avg > 40 else 'ℹ'} 挂在 {n_c} 个客户名下,人均 {_avg:.0f} 单、最多的一人 {_mx} 单"
          + (" —— **看单个客户的订单历史会很不像真的**;要像,得先有更多能安全挂单的客户"
             if _avg > 40 else ""))
    print(f"  状态:{st}")
    sims = [r[0] for r in c.execute("SELECT sku FROM sim_batch_sku ORDER BY sku")]
    ge = {k: sum(1 for s in sims if sold.get(s, 0) >= k) for k in (2, 5, 10, 30)}
    print(f"  {len(sims)} 个 SKU 被这批接管 · 卖掉了的行数 ≥2:{ge[2]}  ≥5:{ge[5]}  ≥10:{ge[10]}  ≥30:{ge[30]}")

    # ① 这批接管的 SKU:流水链必须和 sku 表严丝合缝 —— 这是这批数据自己许下的承诺
    tail = {r["sku"]: r["after_n"] for r in c.execute("""
        SELECT sku, after_n FROM stock_log WHERE ref LIKE 'SIM-%'
          AND id IN (SELECT MAX(id) FROM stock_log GROUP BY sku)""")}
    hold = {}
    for r in c.execute("""SELECT i.sku, SUM(i.qty) q FROM ordr_item i JOIN ordr o ON o.id=i.order_id
                          WHERE o.id IN (SELECT order_id FROM sim_batch)
                            AND o.status IN ('待付款','待发货') GROUP BY i.sku"""):
        hold[r["sku"]] = r["q"]
    breaks = 0
    for r in c.execute("""SELECT sku, before_n, after_n, delta,
                                 LAG(after_n) OVER (PARTITION BY sku ORDER BY id) prev
                          FROM stock_log WHERE ref LIKE 'SIM-%'"""):
        if r["after_n"] != r["before_n"] + r["delta"] or (r["prev"] is not None and r["prev"] != r["before_n"]) \
                or r["after_n"] < 0:
            breaks += 1
    mism = []
    for r in c.execute("SELECT code, stock, locked FROM sku WHERE code IN (SELECT sku FROM sim_batch_sku)"):
        want_locked = hold.get(r["code"], 0)
        want_stock = tail.get(r["code"], 0) + want_locked
        if (r["stock"], r["locked"]) != (want_stock, want_locked):
            mism.append(r["code"])
    ok1 = not breaks and not mism
    print(f"  {'✅' if ok1 else '❌'} 接管的 SKU:流水链接得上 {breaks} 处断 · "
          f"在手/占用和流水推出来的数对不上 {len(mism)} 个 {mism[:3] if mism else ''}")
    if not ok1:
        bad.append("接管的 SKU 流水对不上")

    # ② 全库:流水是不是库存的唯一真相来源 —— **不是**,把数现算出来
    any_tail = {r["sku"]: r["after_n"] for r in c.execute("""
        SELECT sku, after_n FROM stock_log WHERE id IN (SELECT MAX(id) FROM stock_log GROUP BY sku)""")}
    allsku = [dict(r) for r in c.execute("SELECT code, stock, locked FROM sku WHERE status<>'停用'")]
    tail_off = sum(1 for s in allsku if s["code"] in any_tail and s["code"] not in tail
                   and any_tail[s["code"]] != (s["stock"] or 0) - (s["locked"] or 0))
    no_chain = sum(1 for s in allsku if s["code"] not in any_tail and (s["stock"] or 0) > 0)
    上限 = getattr(SA, "流水对不上的上限", None)
    print(f"  ⚠️ **`stock_log` 不是库存的唯一真相来源** —— 链尾 `after_n` 对不上可用的有 "
          f"{tail_off} 个 SKU(种子数据),模拟批次{'自洽' if ok1 else '**不自洽**'}。"
          f"另有 {no_chain} 个 SKU 在手 > 0 却一条流水都没有。")
    if 上限 is not None and tail_off > 上限:
        print(f"  ❌ 对不上的 {tail_off} 个超过了口径里钉的上限 {上限} —— 只许降不许涨")
        bad.append("种子流水对不上的数涨了")

    # ③ 客户汇总没回写 —— 对不上的清单要列出来,不能只活在文档里
    # 2026-09-18 起汇总由 order_mix 按订单重算了;这一段要是还照旧报「没算进」,
    # 就是一份**说错了的报告** —— 比不报更糟,读的人会去修一件已经修好的事
    if "order_mix_batch" in have:
        n_re = c.execute("SELECT COUNT(*) FROM order_mix_batch WHERE what='重算:customer'").fetchone()[0]
        print(f"  ✅ 客户汇总已由 order_mix 按订单重算({n_re} 个客户变了);"
              f"边界夹具和评测写死的客户不重算,见 `python3 tools/order_mix.py --report`")
        return 1 if bad else 0
    cut = (END - dt.timedelta(days=365)).isoformat()
    per = {}
    for r in c.execute("""SELECT o.customer_id, o.status, o.refund_status, o.received, o.created
                          FROM ordr o WHERE o.id IN (SELECT order_id FROM sim_batch)"""):
        if r["created"][:10] >= cut and SA.卖掉了(r["status"], r["refund_status"])[0]:
            a = per.setdefault(r["customer_id"], [0.0, 0])
            a[0] += r["received"] or 0
            a[1] += 1
    diff = []
    for r in c.execute("SELECT id, name, amount_12m, orders_12m FROM customer"):
        if r["id"] in per:
            diff.append((r["id"], r["name"], r["amount_12m"] or 0, r["orders_12m"] or 0,
                         round(per[r["id"]][0], 2), per[r["id"]][1]))
    diff.sort(key=lambda x: -x[4])
    print(f"  ⚠️ 客户汇总没回写(拍过板的):{len(diff)} 个客户的 amount_12m / orders_12m "
          f"没算进这批订单。差得最多的:")
    for x in diff[:8]:
        print(f"     {x[0]} {x[1]}:汇总 ¥{x[2]:.0f}/{x[3]} 单,这批另有 ¥{x[4]:.0f}/{x[5]} 单")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description="模拟标品销量(可回滚)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    c = conn()
    if a.report:
        sys.exit(report(c))
    if a.rollback:
        with c:
            rollback(c)
        return
    with c:
        rollback(c, quiet=True)
        skus, ver, custs = load_world(c)
        rng = random.Random(a.seed)
        orders, logs, final, info = simulate(skus, ver, custs, rng)
        print(f"客户池 {len(custs)} · 候选 SKU {len(skus)} · 已上架可卖 {info['live_sku']} 个 SKU / "
              f"{info['live_spu']} 个 SPU · 起 {info['start']} · 停供 {info['stopped']} 个")
        print(f"造出 {len(orders)} 单 · {sum(len(o['items']) for o in orders)} 行 · 流水 {len(logs)} 条 · "
              f"缺货没卖成 {info['lost']} 次")
        if info["flat"]:
            print(f"  ℹ 这些品类没点名季节,走平的:{info['flat']}")
        if a.dry:
            c.rollback()
            print("(--dry:没写库)")
            return
        write(c, orders, logs, final, skus)
    sys.exit(report(conn()))


if __name__ == "__main__":
    main()
