#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订单分型 + 售后维保重建 + 客户汇总重算 —— **业务 2026-09-18 定的数据集**。

规格在 `intent/order-aftersale-dataset.md`,口径在 `knowledge/09-养护与售后.md` 第六节。
这份脚本只管「数据长成那个样子」,不定义那个样子。

## 为什么不走假数据工厂的通用流水线

通用流水线从**统计规律**一列一列造(这列像枚举、那两列有外键),
而这里要守的全是**业务规则**:两套状态机按订单类型分开走、定制品不许退换、
换货同渠道出货、差价多退少补、定制单要落到具体着装人而且量体在有效期内。
通用流水线只会造出「库允许、业务不允许」的数据。所以是专用生成器,
用的是工厂的零件:状态由「先排完整时间线、再按截止时刻切」推出来(不先抽状态再补时间),
流水走 `fakedata/ledger.py` 的台账规矩(每行 after = before + 增减,且接得上上一行)。

## 做什么

    ① 分型   从模拟销量里挑一批标品单**改造成定制单**,定制品补到 ≥ 500 张。
             订单总数不变(业务:「不需要建立 1000 个订单了,只需要 3826 个销量各自有订单内容」)
    ② 售后   退货退款 40 / 换货 15(只挂标品)· 维保 55(定制 40 / 标品 15,含判责那 12 张)
    ③ 汇总   客户的单数 / 实付 / 12 个月 / 等级 / 生命周期**按订单重算**(业务 2026-09-18 定)

## 不碰什么(每一类都是从库里现查的,不手抄名单)

    · **边界夹具**:truth 里 case_id 就是客户号的那些(生命周期 14 个)。
      它们名下 0 单,实付却摆在 14999 / 15000 上 —— **那正是它们存在的理由**。
      全量重算会把这一对双双归零,14 条边界用例同时失效。
    · **客户合并用例**:truth 的描述里点名的客户(C21* 那 16 对)。
    · **评测里写死的客户**:`fakedata/protect.猜夹具` 的「证据」级(检查/评测脚本里写死的 id)。
      例:C10008 的题目前提是「他是黑金」,C10001 的题目前提是「只完成了 1 单」。
    · **判责那 12 张维保单**原样不动;它们的客户**不加维保单**
      (判责会数「这个客户的历史维修次数」)。
    · 以上几类不挂新订单、不重算汇总。

## 为什么改造而不是新建

业务明说订单总数不变。改造一张模拟单 = 换客户、换商品、按定制品的工期重排时间线,
**并把它在库存流水里留下的占用 / 释放 / 退货入库一并撤掉** —— 定制品不走现货库存。
撤掉之后整条流水重新接一遍链,在手 / 占用按剩下的标品单重新推。

## 用法

    python3 tools/order_mix.py            在 simulate_sales 之后跑(rebuild.sh 里排好了)
    python3 tools/order_mix.py --report   从库里现算:分布、口径、对不上的清单

**不能单独重跑**:改造过的订单回不到原样。要重来就整批重建
(`simulate_sales.py` 会先调这里的 `回滚()` 把本批的东西撤干净,再重造)。
"""
import os, sys, json, math, random, sqlite3, argparse, re, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
          os.path.join(ROOT, "fakedata")):
    if p not in sys.path:
        sys.path.insert(0, p)
DB = os.path.join(ROOT, "backend", "lanxiu.db")

SEED = 20260918
BATCH = "order_mix/v1"
CUT = dt.datetime(2026, 9, 15, 20, 0)      # 和 simulate_sales 同一个截止时刻
T = dt.date(2026, 8, 31)                   # 建库基准日:生命周期 / 闲置天数都按它算
成年判定日 = dt.date(2026, 9, 12)           # 和 order_gate_check 的「今天」一致

定制品目标 = 520            # ≥ 500,留一点余量(改造失败的会少几张)
退货目标, 拒绝的退货 = 40, 5  # 40 张里 5 张是审批拒绝(订单没退款)
换货目标 = 15
维保目标_定制, 维保目标_标品 = 40, 15

生产三档 = ("待生产", "生产中", "已生产")
ST2PRD = {"待付款": "待付款", "待审核": "方案确认中", "待生产": "方案确认中", "生产中": "方案确认中",
          "已生产": "待发货", "待发货": "待发货", "已发货": "待收货", "待完成": "待收货",
          "完成": "已完成", "取消": "已关闭"}
# 维保问题只从种子那张词表里取,**不新造词** —— 判责口径按这张表归类
ISSUES = ["盘扣脱线", "下摆开线", "面料起球", "刺绣局部脱落", "拉链损坏", "染色不均", "尺寸需调整"]
MT_ST = ["待确认", "取消", "待入库", "待处理", "处理中", "待签收", "已完成"]
换货链 = ["提交申请", "审批同意", "商品寄回", "已入库", "差价处理", "换出发货", "签收", "已完成"]


def conn(path=DB):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def ts(t):
    return t.strftime("%Y-%m-%d %H:%M")


def P(s):
    return dt.datetime.strptime(s[:16], "%Y-%m-%d %H:%M")


def days(rng, a, b):
    return dt.timedelta(days=rng.uniform(a, b))


# ── 不碰的客户:一律从库里现查 ─────────────────────────────────────────
def 受保护客户(c):
    """返回 {客户号: 为什么}。**不手抄名单** —— 哪天加了第 15 条边界用例,
    手抄那份不会跟着变,而那时重算会静默抹掉它。"""
    ids = {r[0] for r in c.execute("SELECT id FROM customer")}
    out = {}
    # E- 前缀 = 手工摆在门槛上的夹具(种子约定,run_journey.pick_customers 同一条)。
    # 大部分同时在 truth 里,但**等级口径那个边界夹具不在** —— 它的「答案」是 level 列本身
    for cid in ids:
        if cid.startswith("E-"):
            out[cid] = "E- 前缀:手工摆在门槛上的边界夹具,名下 0 单是故意的"
    for cid, bp in c.execute("SELECT case_id, breakpoint FROM truth"):
        if cid in ids:
            out[cid] = f"truth {bp} 的 case_id 就是这个客户(边界夹具)"
    for row in c.execute("SELECT case_id, breakpoint, expected_evidence, note FROM truth"):
        for cid in re.findall(r"\b(C\d{5}|E-A\d-\d{2})\b", " ".join(str(x or "") for x in row)):
            if cid in ids:
                out.setdefault(cid, f"truth {row[1]} 的描述里点名了它")
    import protect, schema
    sc = schema.connect(DB).reflect()
    for g in protect.猜夹具(schema.connect(DB), sc):   # 用的是 --db 指的那个库
        if g.get("表") == "customer" and g.get("证据等级") == "证据":
            for cid in re.findall(r"'([^']+)'", g["条件"]):
                out.setdefault(cid, "检查/评测脚本里写死了这个客户号")
    return out


def 判责客户(c):
    return {r[0] for r in c.execute(
        "SELECT customer_id FROM maintain WHERE id IN "
        "(SELECT ref_id FROM task WHERE type='售后判责')")}


# ── 着装人:和 order_gate_check ⑧ 同一套判据 ─────────────────────────
def _成年(b):
    return bool(b) and (成年判定日 - dt.date.fromisoformat(b)).days / 365.25 >= 18


def 可下定制单的人(c, 排除):
    """{客户: {品类顶级名: (着装人行, [量体时间...])}} —— 只收「唯一对得上」的那个人。

    唯一才定:名下两个成年女性时女装就定不了,那一类就不给这个客户下。
    **判不了不许挑一个顶上**(order_gate.定位着装人 的规矩)。
    """
    out = {}
    custs = [dict(r) for r in c.execute(
        """SELECT k.id, k.created, k.shop, k.advisor_no, k.addr FROM customer k
           LEFT JOIN account a ON a.id=k.account_id
           WHERE k.archived=0 AND (a.id IS NULL OR a.status='正常')""")]
    for k in custs:
        if k["id"] in 排除:
            continue
        ws = [dict(r) for r in c.execute(
            "SELECT id,name,gender,birthday FROM wearer WHERE customer_id=? AND status='在用'",
            (k["id"],))]
        组 = {"女装": [w for w in ws if _成年(w["birthday"]) and w["gender"] == "女"],
              "男装": [w for w in ws if _成年(w["birthday"]) and w["gender"] == "男"],
              "童装": [w for w in ws if w["birthday"] and not _成年(w["birthday"])]}
        for 顶, cand in 组.items():
            if len(cand) != 1:
                continue
            w = cand[0]
            ms = sorted({r[0] for r in c.execute(
                "SELECT measured_at FROM measure_rec WHERE wearer_id=?", (w["id"],))})
            if ms and w["gender"] and w["birthday"]:
                out.setdefault(k["id"], {"客户": k})[顶] = (w, ms)
    return out


def 量体有效(w, ms, when):
    """下单那一刻,这个人有没有**有效**的量体。和 order_gate_check 同一个判法:
    取下单前最近一次,按下单那天的年龄算复量周期。**有记录 ≠ 有效。**"""
    import growth
    s = ts(when)
    prev = [m for m in ms if m <= s]
    if not prev:
        return False
    return not growth.measure_expired(w["gender"], w["birthday"], prev[-1][:10], s[:10])["过期"]


# ── 定制品的时间线:先排全,再按截止时刻切 ─────────────────────────────
def 定制时间线(rng, t):
    """返回 (状态, {时间戳字段: 值})。状态是**推出来的**,不是先抽再补时间。"""
    if rng.random() < 0.08:                         # 下单后没付款就取消(规格:取消 5–10%)
        tc = t + days(rng, 0.1, 3)
        return ("取消", {"cancelled_at": tc}) if tc <= CUT else ("待付款", {})
    paid = t + days(rng, 0.02, 1.5)
    audit = paid + days(rng, 0.2, 2)
    start = audit + days(rng, 1, 6)                  # 排上产能、开裁
    produced = start + days(rng, 20, 40)
    ready = produced + days(rng, 0.5, 2)             # 质检完,等发货
    shipped = ready + days(rng, 0.5, 2)
    signed = shipped + days(rng, 2, 4)
    finished = shipped + days(rng, 7, 14)
    st = {}
    if paid > CUT:
        return "待付款", st
    st["paid_at"] = paid
    if audit > CUT:
        return "待审核", st
    st["audit_at"] = audit
    if start > CUT:
        return "待生产", st
    if produced > CUT:
        return "生产中", st
    st["produced_at"] = produced
    if ready > CUT:
        return "已生产", st
    if shipped > CUT:
        return "待发货", st
    st["shipped_at"] = shipped
    if signed > CUT:
        return "已发货", st
    st["signed"] = signed                              # 不落库,维保/换货要用
    if finished > CUT:
        return "待完成", st
    st["finished_at"] = finished
    return "完成", st


# ── 分部位选料:和 seed.py 同一个规矩(加价之和 = custom_amount)──────────
def 选料(c, rng, spu, custom_amount):
    opts = [dict(r) for r in c.execute(
        "SELECT part, material, colors FROM part_option WHERE spu=? AND kind='面料' "
        "ORDER BY sort, material", (spu,))]
    kfopt = [r[0] for r in c.execute(
        "SELECT DISTINCT material FROM part_option WHERE spu=? AND kind='工艺' ORDER BY material",
        (spu,))]
    by = {}
    for o in opts:
        by.setdefault(o["part"], []).append(o)
    chosen = []
    for b, lst in sorted(by.items()):
        o = rng.choice(lst)
        cs = [x for x in (o["colors"] or "").split("、") if x]
        chosen.append((b, o["material"], rng.choice(cs) if cs else None))
    rows = []
    tot = round(float(custom_amount), 2)
    each = round(tot / len(chosen), 2)
    for k, (b, m, col) in enumerate(chosen):
        amt = each if k < len(chosen) - 1 else round(tot - each * (len(chosen) - 1), 2)
        desc = (c.execute("SELECT brief FROM craft WHERE name=? AND cat='材质'", (m,)).fetchone()
                or [None])[0]
        rows.append(("面料", b, m, col, amt, desc))
        # 同一个部位的工艺必须和面料相容;挑不出相容的就不给这个部位配工艺 ——
        # 塞一个做不出来的组合,车间会拿着它去开工
        ok = []
        for kf in kfopt:
            v = c.execute(
                "SELECT verdict FROM craft_combo WHERE craft=(SELECT code FROM craft WHERE name=? "
                "AND cat='工艺') AND material=(SELECT code FROM craft WHERE name=? AND cat='材质')",
                (kf, m)).fetchone()
            if v and v[0] != "不可":
                ok.append(kf)
        if ok:
            kf = rng.choice(ok)
            kd = (c.execute("SELECT brief FROM craft WHERE name=? AND cat='工艺'", (kf,)).fetchone()
                  or [None])[0]
            rows.append(("工艺", b, kf, None, 0.0, kd))
    return rows


def _manifest(c):
    c.execute("""CREATE TABLE IF NOT EXISTS order_mix_batch(
                 what TEXT, key TEXT, payload TEXT, batch TEXT NOT NULL)""")


def _记(c, what, key, payload=None):
    c.execute("INSERT INTO order_mix_batch VALUES(?,?,?,?)",
              (what, str(key), json.dumps(payload, ensure_ascii=False) if payload is not None
               else None, BATCH))


def 回滚(c, quiet=False):
    """撤掉本批做过的**非模拟单**那部分:删掉的种子售后/维保行放回去、客户汇总恢复。

    模拟单本身(含改造过的)由 simulate_sales 的回滚整批删 —— 所以这里必须**先于**它跑。
    """
    have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "order_mix_batch" not in have:
        return 0
    n = 0
    rows = list(c.execute("SELECT what,key,payload FROM order_mix_batch ORDER BY rowid"))
    # **先删新增的,再放回删掉的** —— 反过来的话,一个单号要是被新旧两行用过,
    # 放回去的旧行会被紧接着的「删新增」一起删掉
    rows.sort(key=lambda r: 0 if r[0].startswith("新增") else 1)
    for what, key, payload in rows:
        if what in ("新增:aftersale", "新增:maintain", "新增:item_part_choice"):
            c.execute(f"DELETE FROM {what.split(':')[1]} WHERE id=?", (key,))
        elif what in ("删除:aftersale", "删除:maintain"):
            row = json.loads(payload)
            cols = list(row)
            c.execute(f"INSERT OR REPLACE INTO {what.split(':')[1]}({','.join(cols)}) "
                      f"VALUES({','.join('?' * len(cols))})", [row[k] for k in cols])
        elif what == "重算:customer":
            row = json.loads(payload)
            c.execute("UPDATE customer SET " + ",".join(f"{k}=?" for k in row) + " WHERE id=?",
                      [row[k] for k in row] + [key])
        n += 1
    c.execute("DROP TABLE order_mix_batch")
    if not quiet:
        print(f"order_mix 已回滚 {n} 条记录")
    return n


# ── ① 分型 ──────────────────────────────────────────────────────────
def 分型(c, rng, 排除, log):
    import fix_order_measure as FX
    已有定制 = c.execute("SELECT COUNT(*) FROM ordr WHERE kind='定制品订单'").fetchone()[0]
    要改 = max(0, 定制品目标 - 已有定制)
    人 = 可下定制单的人(c, 排除)
    ver = {r["code"]: r["version"] for r in c.execute("SELECT code, version FROM pattern")}
    prods = {}
    for r in c.execute(
            """SELECT p.spu, p.name, p.category, p.created, p.on_shelf_at, p.base_price, p.pattern
               FROM product p WHERE p.kind='定制品' AND p.status='上架'
                 AND EXISTS(SELECT 1 FROM part_option o WHERE o.spu=p.spu AND o.kind='面料')
                 AND EXISTS(SELECT 1 FROM sku s WHERE s.code=p.spu||'-01')"""):
        顶 = FX.顶级品类(c, r["category"])
        if 顶 in ("女装", "男装", "童装"):
            prods.setdefault(顶, []).append(dict(r))

    # 候选:模拟标品单。**多退了的那部分优先改** —— 退货目标只要 35 张真退款的,
    # 模拟时按 2.5% 退出来的比这多;改成定制之后它们的退货入库一并撤掉。
    sims = [dict(r) for r in c.execute(
        """SELECT o.id, o.created, o.refund_status FROM ordr o
           WHERE o.id IN (SELECT order_id FROM sim_batch) AND o.kind='标品订单' ORDER BY o.id""")]
    退款中的标品 = c.execute("SELECT COUNT(*) FROM ordr WHERE kind='标品订单' "
                         "AND refund_status<>'未退款'").fetchone()[0]
    多退 = max(0, 退款中的标品 - (退货目标 - 拒绝的退货))
    退了 = [s for s in sims if s["refund_status"] != "未退款"]
    rng.shuffle(退了)
    其余 = [s for s in sims if s["refund_status"] == "未退款"]
    rng.shuffle(其余)
    # 越早下的单越可能已经做完 —— 定制品工期一个多月,九月下的单大多还在生产。
    # 按下单月份给接受概率,让「完成」占到六成以上(规格 1.2b)
    def 接受(s):
        m = int(s["created"][5:7])
        return rng.random() < {3: 1, 4: 1, 5: 0.9, 6: 0.75, 7: 0.35, 8: 0.1, 9: 0.05}.get(m, 0.5)

    计数 = {cid: 0 for cid in 人}
    改了, 失败 = [], 0

    def 试(s):
        t = P(s["created"])
        cands = []
        for cid, d in 人.items():
            if (d["客户"]["created"] or "")[:10] > s["created"][:10]:
                continue
            for 顶, v in d.items():
                if 顶 == "客户":
                    continue
                w, ms = v
                if not 量体有效(w, ms, t):
                    continue
                ok = [p for p in prods.get(顶, [])
                      if (p["created"] or "")[:10] <= s["created"][:10]
                      and (p["on_shelf_at"] or "")[:10] <= s["created"][:10]]
                if ok:
                    cands.append((cid, 顶, w, ok))
        if not cands:
            return None
        # 铺开:名下单子越少越容易被挑中(人均 5–9 张,不是一个人几十张)
        wts = [1.0 / (1 + 计数[x[0]]) ** 2 for x in cands]
        cid, 顶, w, ok = rng.choices(cands, weights=wts)[0]
        return cid, 顶, w, rng.choice(ok)

    改了的退款单 = 0
    for s in 退了 + [x for x in 其余 if 接受(x)]:
        if len(改了) >= 要改:
            break
        if s["refund_status"] != "未退款" and 改了的退款单 >= 多退:
            continue
        got = 试(s)
        if not got:
            失败 += 1
            continue
        cid, 顶, w, p = got
        计数[cid] += 1
        改了的退款单 += s["refund_status"] != "未退款"
        改了.append((s, cid, w, p))
    if len(改了) < 要改:
        raise SystemExit(f"❌ 只改出 {len(改了)} 张定制单(要 {要改})—— "
                         f"能下定制单的人 × 有效量体窗口不够,**不许放宽量体有效期来凑**")

    refs = set()
    for s, cid, w, p in 改了:
        k = 人[cid]["客户"]
        t = P(s["created"])
        st, stamp = 定制时间线(rng, t)
        base = float(p["base_price"])
        custom = round(base * rng.uniform(0.10, 0.30), 2)
        goods = round(base, 2)
        freight = 0.0 if goods >= 2000 else 28.0
        amount = round(goods + custom + freight, 2)
        paid = "paid_at" in stamp
        # 定制品是**线下下单**(设计稿:流程=线下下单(定制品))—— 渠道只取门店和客服代下单
        src = "门店 Pad" if rng.random() < 0.7 else "客服代下单"
        allst = [t] + [v for kk, v in stamp.items() if kk != "signed"]
        c.execute("""UPDATE ordr SET customer_id=?, kind='定制品订单', status=?, prd_status=?,
                     advisor_no=?, shop=?, source=?, activity=NULL, delivery=?, wearer_id=?,
                     amount=?, payable=?, goods_amount=?, freight=?, received=?,
                     refund_status='未退款', addr=?, paid_at=?, audit_at=?, produced_at=?,
                     shipped_at=?, finished_at=?, cancelled_at=?, updated=?, remark=NULL
                     WHERE id=?""",
                  (cid, st, ST2PRD[st], k["advisor_no"], k["shop"], src,
                   "配送到店" if rng.random() < 0.6 else "配送到客户", w["id"],
                   amount, amount, goods, freight, amount if paid else 0.0, k["addr"],
                   *(ts(stamp[f]) if f in stamp else None for f in
                     ("paid_at", "audit_at", "produced_at", "shipped_at", "finished_at",
                      "cancelled_at")),
                   ts(max(allst)), s["id"]))
        c.execute("DELETE FROM ordr_item WHERE order_id=?", (s["id"],))
        pv = ver.get(p["pattern"]) if p["pattern"] else None
        c.execute("""INSERT INTO ordr_item(order_id,sku,name,tag,price,qty,spu,base_amount,
                     custom_amount,total,wearer_id,pattern_version,pattern_version_src)
                     VALUES(?,?,?,'定制品',?,1,?,?,?,?,?,?,?)""",
                  (s["id"], f"{p['spu']}-01", p["name"], base, p["spu"], base, custom,
                   round(base + custom, 2), w["id"], pv,
                   f"订单分型({BATCH}):取生成时版型的当前版本" if pv is not None else None))
        iid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for kd, b, m, col, amt, note in 选料(c, rng, p["spu"], custom):
            c.execute("INSERT INTO item_part_choice(item_id,kind,part,material,color,amount,note)"
                      " VALUES(?,?,?,?,?,?,?)", (iid, kd, b, m, col, amt, note))
            _记(c, "新增:item_part_choice", c.execute("SELECT last_insert_rowid()").fetchone()[0])
        _记(c, "转定制", s["id"])
        refs |= {f"SIM-{s['id']}", f"SIM-AS{s['id'][-10:]}"}
    log(f"  ① 分型:改了 {len(改了)} 张(其中 {改了的退款单} 张是多退了的),"
        f"没找到有效着装人的跳过 {失败} 张 · 挂到 {sum(1 for v in 计数.values() if v)} 个客户")
    return refs, len(改了)


# ── 库存流水:撤掉改造单的占用,加上换货的进出,再整条重新接链 ─────────────
def 重接流水(c, 撤掉, 加上):
    """模拟批次的流水**整批重写**:撤掉 refs 里的、加上换货的进出,按时间重排后重算
    before/after。撤掉占用只会让余额变大,所以不会接出负数;加上的出库要逐条验。"""
    import ledger as LG
    rows = [dict(r) for r in c.execute(
        "SELECT sku,spu,kind,delta,ref,operator,ts,note FROM stock_log "
        "WHERE ref LIKE 'SIM-%' ORDER BY id")]
    keep = [r for r in rows if r["ref"] not in 撤掉] + 加上
    keep.sort(key=lambda r: (r["ts"], 0 if r["delta"] > 0 else 1))
    帐, out = {}, []
    for r in keep:
        a = 帐.setdefault(r["sku"], LG.台账(r["sku"], 起始=0))
        行 = a.记(r["ts"], r["kind"], r["delta"], r["ref"], r["note"])
        if 行 is None:
            return None, r                            # 余额不够 —— 调用方换一件
        out.append(dict(r, before_n=行["前"], after_n=行["后"]))
    return out, 帐


def 写流水(c, out, 帐):
    c.execute("DELETE FROM stock_log WHERE ref LIKE 'SIM-%'")
    c.executemany("""INSERT INTO stock_log(sku,spu,kind,delta,before_n,after_n,ref,operator,ts,note)
                     VALUES(:sku,:spu,:kind,:delta,:before_n,:after_n,:ref,:operator,:ts,:note)""",
                  out)
    # 在手 / 占用按剩下的标品单重新推:占用 = 还没发货的,在手 = 可用 + 占用
    hold = {r[0]: r[1] for r in c.execute(
        """SELECT i.sku, SUM(i.qty) FROM ordr_item i JOIN ordr o ON o.id=i.order_id
           WHERE o.id IN (SELECT order_id FROM sim_batch) AND o.kind='标品订单'
             AND o.status IN ('待付款','待发货') GROUP BY i.sku""")}
    for code in [r[0] for r in c.execute("SELECT sku FROM sim_batch_sku")]:
        a = 帐.get(code)
        avail = a.余额 if a else 0
        c.execute("UPDATE sku SET stock=?, locked=? WHERE code=?",
                  (avail + hold.get(code, 0), hold.get(code, 0), code))


# ── ② 售后 ──────────────────────────────────────────────────────────
def 售后(c, rng, 排除, 判责, log):
    # 旧的一律作废(业务:「之前有错误的数据,直接作废,清空」)。删掉的行存进清单,回滚放回去
    for r in [dict(x) for x in c.execute("SELECT * FROM aftersale")]:
        _记(c, "删除:aftersale", r["id"], r)
    c.execute("DELETE FROM aftersale")
    # 维保:判责那 12 张原样不动,其余作废重造
    for r in [dict(x) for x in c.execute(
            "SELECT * FROM maintain WHERE id NOT IN "
            "(SELECT ref_id FROM task WHERE type='售后判责')")]:
        _记(c, "删除:maintain", r["id"], r)
    c.execute("DELETE FROM maintain WHERE id NOT IN (SELECT ref_id FROM task WHERE type='售后判责')")

    asn = [64881000]

    def 新单号():
        asn[0] += 1
        return f"AS{asn[0]}"

    def 插售后(**kw):
        cols = list(kw)
        c.execute(f"INSERT INTO aftersale({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                  [kw[k] for k in cols])
        _记(c, "新增:aftersale", kw["id"])

    def 首行(oid):
        return c.execute("SELECT id, sku, spu, name, price, qty, total FROM ordr_item "
                         "WHERE order_id=? ORDER BY id LIMIT 1", (oid,)).fetchone()

    REASONS_RET = ["多拍/拍错/不想要", "尺寸不合适", "面料与描述不符", "质量问题"]
    # ── 退货退款:订单上已经退了 / 正在退的标品单,一张一单(退款状态和售后单对得上)
    # 受保护的客户也照挂:售后单不改他们身上任何被评测读的事实(汇总、量体、维修次数)
    retd = [dict(r) for r in c.execute(
        """SELECT * FROM ordr WHERE kind='标品订单' AND refund_status<>'未退款' ORDER BY id""")]
    n_ret = 0
    for o in retd:
        it = 首行(o["id"])
        base = P(o["shipped_at"] or o["paid_at"] or o["created"])
        t0 = base + days(rng, 3, 7)
        if o["refund_status"] == "已退款":
            st, t1 = "已完成", t0 + days(rng, 4, 9)
        else:
            st = rng.choice(["提交申请", "审批同意", "商品寄回"])
            t1 = t0 + days(rng, 0.2, 2)
        t0, t1 = min(t0, CUT), min(t1, CUT)
        插售后(id=新单号(), kind="退货退款", order_id=o["id"], customer_id=o["customer_id"],
             status=st, reason=rng.choice(REASONS_RET),
             amount=round((it["price"] or 0) * (it["qty"] or 1), 2), shop=o["shop"],
             advisor_no=o["advisor_no"], created=ts(t0), updated=ts(t1),
             ext_system="售后/维保系统", synced_at=ts(t1 + dt.timedelta(minutes=30)),
             order_item_id=it["id"], channel=o["source"])
        n_ret += 1
    # 审批拒绝的:订单没退款,售后单停在终态
    pool = [dict(r) for r in c.execute(
        """SELECT * FROM ordr WHERE kind='标品订单' AND status IN ('待完成','完成')
           AND refund_status='未退款' AND id IN (SELECT order_id FROM sim_batch)
           AND id NOT IN (SELECT order_id FROM aftersale) ORDER BY id""")]
    rng.shuffle(pool)
    for o in pool[:max(0, 退货目标 - n_ret)]:
        it = 首行(o["id"])
        t0 = min(P(o["shipped_at"]) + days(rng, 3, 7), CUT)
        t1 = min(t0 + days(rng, 0.3, 2), CUT)
        插售后(id=新单号(), kind="退货退款", order_id=o["id"], customer_id=o["customer_id"],
             status="审批拒绝", reason=rng.choice(["多拍/拍错/不想要", "尺寸不合适"]),
             amount=round((it["price"] or 0) * (it["qty"] or 1), 2), shop=o["shop"],
             advisor_no=o["advisor_no"], created=ts(t0), updated=ts(t1),
             ext_system="售后/维保系统", synced_at=ts(t1 + dt.timedelta(minutes=30)),
             order_item_id=it["id"], channel=o["source"])
        n_ret += 1

    # ── 仅退款:订单上挂着退款状态的定制单(定制品的钱退出口)
    n_ref = 0
    for o in [dict(r) for r in c.execute(
            "SELECT * FROM ordr WHERE kind='定制品订单' AND refund_status<>'未退款' ORDER BY id")]:
        it = 首行(o["id"])
        t0 = P(o["paid_at"] or o["created"]) + days(rng, 2, 6)
        st = "已完成" if o["refund_status"] == "已退款" else ("退款失败" if n_ref % 2 == 0 else "待结算")
        t1 = t0 + days(rng, 1, 5)
        插售后(id=新单号(), kind="仅退款", order_id=o["id"], customer_id=o["customer_id"],
             status=st, reason=rng.choice(["交期延误", "工艺瑕疵"]),
             amount=round((o["received"] or 0) * rng.uniform(0.1, 0.3), 2), shop=o["shop"],
             advisor_no=o["advisor_no"], created=ts(t0), updated=ts(t1),
             ext_system="售后/维保系统", synced_at=ts(t1 + dt.timedelta(minutes=30)),
             order_item_id=it["id"], channel=o["source"])
        n_ref += 1
    if not c.execute("SELECT 1 FROM aftersale WHERE status='退款失败'").fetchone():
        raise SystemExit("❌ 一张「退款失败」都没有 —— 退款失败那两道评测题的前提就没了")

    # ── 换货:已签收的单件标品单,同 SPU 换码为主、少数换款(有差价)
    cand = [dict(r) for r in c.execute(
        """SELECT o.* FROM ordr o WHERE o.kind='标品订单' AND o.status IN ('待完成','完成')
           AND o.refund_status='未退款' AND o.id IN (SELECT order_id FROM sim_batch)
           AND o.id NOT IN (SELECT order_id FROM aftersale)
           AND (SELECT COUNT(*) FROM ordr_item i WHERE i.order_id=o.id)=1
           AND (SELECT qty FROM ordr_item i WHERE i.order_id=o.id)=1
           AND o.shipped_at <= ? ORDER BY o.id""", (ts(CUT - dt.timedelta(days=4)),))]
    rng.shuffle(cand)
    sim_sku = {r[0] for r in c.execute("SELECT sku FROM sim_batch_sku")}
    # 这里只排**候选**,不落库:换出去那件在那一刻得有货,而这要接完整条流水才知道。
    # 候选多排几倍,由 run() 逐条试接,接不上的(那一刻没货)跳过 —— **不许让库存变负数来凑**
    换 = []
    for o in cand:
        if len(换) >= 换货目标 * 4:
            break
        it = 首行(o["id"])
        if it["sku"] not in sim_sku:
            continue
        换款 = rng.random() < 0.5      # 换款才有差价;同款换码差价是 0 —— 两种都要有
        if 换款:
            cat = c.execute("SELECT category FROM product WHERE spu=?", (it["spu"],)).fetchone()[0]
            opts = [dict(r) for r in c.execute(
                """SELECT s.code, s.price, s.spu FROM sku s JOIN product p ON p.spu=s.spu
                   WHERE p.kind='标品' AND p.category=? AND s.spu<>? AND s.status<>'停用'
                     AND s.price<>?""", (cat, it["spu"], it["price"]))]
        else:
            opts = [dict(r) for r in c.execute(
                "SELECT code, price, spu FROM sku WHERE spu=? AND code<>? AND status<>'停用'",
                (it["spu"], it["sku"]))]
        opts = [x for x in opts if x["code"] in sim_sku]
        if not opts:
            continue
        ex = rng.choice(opts)
        # 时间线先排全:申请 → 审批 → 寄回 → 入库 → 差价 → 换出 → 签收 → 完成
        t = P(o["shipped_at"]) + days(rng, 3, 6)
        steps = [t]
        for a, b in ((0.2, 1.5), (1, 3), (2, 4), (0.1, 1), (0.3, 1.5), (2, 4), (1, 3)):
            steps.append(steps[-1] + days(rng, a, b))
        拒 = rng.random() < 0.13
        if t > CUT:
            continue                   # 截止时刻还没提申请 —— 这张单此刻没有换货
        if 拒:
            if steps[1] > CUT:
                continue
            st, upd = "审批拒绝", steps[1]
        else:
            k = max(i for i, x in enumerate(steps) if x <= CUT)
            st, upd = 换货链[k], steps[k]
        diff = round((ex["price"] or 0) - (it["price"] or 0), 2)
        到了差价 = (not 拒) and 换货链.index(st) >= 换货链.index("差价处理")
        结清 = (not 拒) and 换货链.index(st) >= 换货链.index("换出发货")
        rows = []
        # 库存:入库那一刻原件回库,换出那一刻新件出库 —— 都在同一个仓(模拟批次的 SKU)
        if not 拒 and 换货链.index(st) >= 换货链.index("已入库"):
            rows.append(dict(sku=it["sku"], spu=it["spu"], kind="退货入库", delta=1,
                             ref=f"SIM-EXI{o['id'][-10:]}", operator="系统", ts=ts(steps[3]),
                             note="换货:原件寄回入库"))
        if 结清:
            rows.append(dict(sku=ex["code"], spu=ex["spu"], kind="订单占用", delta=-1,
                             ref=f"SIM-EXO{o['id'][-10:]}", operator="系统", ts=ts(steps[5]),
                             note="换货:从原渠道换出新件"))
        换.append(dict(o=o, it=it, ex=ex, st=st, t=t, upd=upd, rows=rows,
                      diff=diff if 到了差价 else None, settled=steps[5] if 结清 else None,
                      reason=rng.choice(["尺寸不合适", "面料与描述不符", "质量问题"])))
    log(f"  ② 售后:退货退款 {n_ret} · 仅退款 {n_ref} · 换货候选 {len(换)}")
    return 换, 插售后, 新单号


def 写换货(c, 换, 插售后, 新单号):
    for r in 换:
        o, it = r["o"], r["it"]
        插售后(id=新单号(), kind="换货", order_id=o["id"], customer_id=o["customer_id"],
             status=r["st"], reason=r["reason"], amount=None, shop=o["shop"],
             advisor_no=o["advisor_no"], created=ts(r["t"]), updated=ts(r["upd"]),
             ext_system="售后/维保系统", synced_at=ts(r["upd"] + dt.timedelta(minutes=30)),
             order_item_id=it["id"], exchange_sku=r["ex"]["code"], channel=o["source"],
             price_diff=r["diff"], diff_settled_at=ts(r["settled"]) if r["settled"] else None)


def 维保(c, rng, 排除, 判责, 改了的单, log):
    """维保只挂**已经完成**的单,报修在完成之后。
    业务 2026-09-18:「维保申请还必须在用户订单完成之后,完成后才能有维保」。
    (第一版挂的是「已签收」—— 待完成 / 完成 —— 那比业务说的松一档。)
    判责客户不加 —— 判责会数「这个客户的历史维修次数」。"""
    def issue_of(nm, kind):
        if kind == "标品订单":
            if "袄" in nm or "立领" in nm: return "盘扣脱线"
            if "裙" in nm: return "面料起球" if ("锦" in nm or "缎" in nm) else "染色不均"
            return "下摆开线"
        ok = ["下摆开线", "面料起球", "染色不均", "尺寸需调整"]
        if any(w in nm for w in ("袄", "立领", "褙子", "比甲", "袍")): ok.append("盘扣脱线")
        if "绣" in nm: ok.append("刺绣局部脱落")
        return rng.choice(ok)

    # 新单号从 MW73100 起,**不复用刚作废的号** —— 同一个号先后指两张单,
    # 回滚和对账都会认错人
    mw = [max([73099] + [int(r[0][2:]) for r in c.execute("SELECT id FROM maintain")])]
    # 一个客户最多两张 —— 标品单只摊在二十几个客户身上,一人一张凑不够;
    # 再多就是「这家人的衣服总坏」,判责时历史维修次数会把这个人画成难缠的客户
    from collections import Counter
    已有 = Counter(r[0] for r in c.execute("SELECT customer_id FROM maintain"))
    n = {"定制品订单": 0, "标品订单": 0}
    for kind, 目标 in (("定制品订单", 维保目标_定制), ("标品订单", 维保目标_标品)):
        目标 -= c.execute("SELECT COUNT(*) FROM maintain m JOIN ordr o ON o.id=m.order_id "
                        "WHERE o.kind=?", (kind,)).fetchone()[0]
        pool = [dict(r) for r in c.execute(
            f"""SELECT o.id, o.customer_id, o.shop, o.advisor_no, o.finished_at FROM ordr o
                WHERE o.kind=? AND o.status='完成'
                  AND o.id IN (SELECT order_id FROM sim_batch)
                  AND o.finished_at <= ? ORDER BY o.id""",
            (kind, ts(CUT - dt.timedelta(days=12))))]
        if kind == "标品订单":   # 只挑成衣 —— 配饰配上「拉链损坏」就是假现场
            pool = [o for o in pool if (c.execute(
                "SELECT substr(p.category,1,3) FROM ordr_item i JOIN product p ON p.spu=i.spu "
                "WHERE i.order_id=? ORDER BY i.id LIMIT 1", (o["id"],)).fetchone() or [""])[0]
                in ("C01", "C02", "C03")]
        rng.shuffle(pool)
        for o in pool:
            if 目标 <= 0:
                break
            if o["customer_id"] in 排除 or o["customer_id"] in 判责 or 已有[o["customer_id"]] >= 2:
                continue
            it = c.execute("SELECT id, name FROM ordr_item WHERE order_id=? ORDER BY id LIMIT 1",
                           (o["id"],)).fetchone()
            t0 = P(o["finished_at"]) + days(rng, 3, 80)
            if t0 > CUT:
                t0 = CUT - days(rng, 0, 3)
            if t0 < P(o["finished_at"]) + dt.timedelta(days=1):
                continue
            # 越早报修的越可能已经走完;状态和问题**各自独立**抽(E2:两者不许完全相关)
            老 = (CUT - t0).days > 20
            st = rng.choice(["已完成", "已完成", "待签收", "取消"] if 老 else
                            ["待确认", "待入库", "待处理", "处理中", "待签收"])
            mw[0] += 1
            iss = issue_of(it["name"], kind)
            assert iss in ISSUES, iss
            c.execute("""INSERT INTO maintain(id,order_id,customer_id,item,status,issue,shop,
                         advisor_no,created,updated,ext_system,synced_at,order_item_id)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (f"MW{mw[0]}", o["id"], o["customer_id"], it["name"], st, iss, o["shop"],
                       o["advisor_no"], ts(t0), ts(min(t0 + days(rng, 1, 12), CUT)),
                       "售后/维保系统", ts(min(t0 + days(rng, 1, 12), CUT)), it["id"]))
            _记(c, "新增:maintain", f"MW{mw[0]}")
            已有[o["customer_id"]] += 1
            n[kind] += 1
            目标 -= 1
        if 目标 > 0:
            raise SystemExit(f"❌ {kind}维保差 {目标} 张 —— 签收过的单不够")
    log(f"  ② 维保:新造 定制 {n['定制品订单']} · 标品 {n['标品订单']}(判责那 12 张原样)")


# ── ③ 客户汇总重算 ────────────────────────────────────────────────────
def 重算(c, 排除, log):
    """单数 / 实付 / 12 个月 / 季度 / 首单 / 最近互动 / 闲置 / 等级 / 生命周期,全部从订单推。

    口径:
      算数的单 = 已付款、没取消、没退完款的
      单数(order_cnt / orders_12m)= **完成**的单(等级表写的是「完成订单 ≥ N 单」,
                                     生命周期「潜在 = 无完成订单」)
      实付(paid_amount / amount_12m)= 算数的单的实收
      12 个月 = 截至建库基准日往前 365 天
      最近互动 = 原来记的互动和最近一单取晚的(下单本身就是一次互动)
    """
    import lifecycle as LC, member as MB
    C = [dict(r) for r in c.execute("SELECT code,name,amount,orders,sort FROM level_cfg "
                                   "WHERE status='启用'")]
    win0 = (T - dt.timedelta(days=365)).isoformat()
    n = 0
    for k in [dict(r) for r in c.execute("SELECT * FROM customer")]:
        if k["id"] in 排除:
            continue
        os_ = [dict(r) for r in c.execute(
            """SELECT created, status, received, refund_status, finished_at FROM ordr
               WHERE customer_id=? AND paid_at IS NOT NULL AND status<>'取消'
                 AND refund_status<>'已退款'""", (k["id"],))]
        done = [o for o in os_ if o["status"] == "完成"]
        d12 = [o for o in done if o["created"][:10] >= win0]
        a12 = [o for o in os_ if o["created"][:10] >= win0]
        allo = [r[0] for r in c.execute("SELECT created FROM ordr WHERE customer_id=?", (k["id"],))]
        last = max([k["last_interact"] or ""] + [x[:10] for x in allo]) or None
        idle = max(0, (T - dt.date.fromisoformat(last[:10])).days) if last else k["idle_days"]
        first = min(o["created"] for o in os_)[:10] if os_ else None
        new = dict(order_cnt=len(done), paid_amount=round(sum(o["received"] or 0 for o in os_), 2),
                   orders_12m=len(d12), amount_12m=round(sum(o["received"] or 0 for o in a12), 2),
                   quarters_12m=len({(o["created"][:4], (int(o["created"][5:7]) - 1) // 3)
                                     for o in d12}),
                   first_order=first, last_interact=last, idle_days=idle)
        row = dict(new, days_since_first_order=((T - dt.date.fromisoformat(first)).days
                                                if first else None),
                   manual_lc=k["manual_lc"],
                   days_since_manual=((T - dt.date.fromisoformat(k["manual_at"][:10])).days
                                      if k["manual_at"] else None))
        d = LC.decide(row)
        new.update(lifecycle=d["生命周期"], matched="/".join(d["命中"]),
                   level=MB.判档(new["amount_12m"], new["orders_12m"], C))
        old = {kk: k[kk] for kk in new}
        if old != new:
            _记(c, "重算:customer", k["id"], old)
            c.execute("UPDATE customer SET " + ",".join(f"{kk}=?" for kk in new) + " WHERE id=?",
                      [new[kk] for kk in new] + [k["id"]])
            n += 1
    log(f"  ③ 客户汇总:重算 {n} 个(跳过受保护的 {len(排除)} 个)")


def run(c, log=print):
    have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "sim_batch" not in have:
        raise SystemExit("❌ 没有模拟销量这一批 —— 先跑 tools/simulate_sales.py")
    if "order_mix_batch" in have:
        raise SystemExit("❌ 这一批已经分过型了。改造过的订单回不到原样,要重来就整批重建:"
                         "python3 tools/simulate_sales.py && python3 tools/order_mix.py")
    rng = random.Random(SEED)
    _manifest(c)
    保护 = 受保护客户(c)
    判责 = 判责客户(c)
    log(f"受保护的客户 {len(保护)} 个(不挂新单、不重算)· 判责客户 {len(判责)} 个(不加维保)")
    撤掉, _n = 分型(c, rng, set(保护), log)
    候选, 插售后, 新单号 = 售后(c, rng, set(保护), 判责, log)
    # 换货逐条试接:换出去那件在那一刻有没有货,要接完整条流水才知道
    收, 加上 = [], []
    out, 帐 = 重接流水(c, 撤掉, [])
    if out is None:
        raise SystemExit(f"❌ 只撤掉改造单的占用,流水就接不上了:{帐}")
    for r in 候选:
        if len(收) >= 换货目标:
            break
        o2, a2 = 重接流水(c, 撤掉, 加上 + r["rows"])
        if o2 is None:
            continue
        收.append(r); 加上 += r["rows"]; out, 帐 = o2, a2
    if len(收) < 换货目标:
        raise SystemExit(f"❌ 换货只凑出 {len(收)} 张 —— 候选里那一刻有货的不够")
    写流水(c, out, 帐)
    写换货(c, 收, 插售后, 新单号)
    log(f"  ② 换货:{len(收)} 张(候选 {len(候选)},那一刻没货的跳过)")
    维保(c, rng, set(保护), 判责, None, log)
    重算(c, set(保护), log)


# ── 报告:一律从库里现算 ──────────────────────────────────────────────
def report(c):
    bad = []
    print("订单分型与售后 · 现算")
    tot = c.execute("SELECT COUNT(*) FROM ordr").fetchone()[0]
    for kind in ("定制品订单", "标品订单"):
        n = c.execute("SELECT COUNT(*) FROM ordr WHERE kind=?", (kind,)).fetchone()[0]
        st = dict(c.execute("SELECT status, COUNT(*) FROM ordr WHERE kind=? GROUP BY 1 "
                            "ORDER BY 2 DESC", (kind,)).fetchall())
        完 = st.get("完成", 0) / max(n, 1)
        消 = st.get("取消", 0) / max(n, 1)
        print(f"  {kind} {n} 张 · 完成 {完:.0%} · 取消 {消:.1%} · {st}")
        if kind == "定制品订单" and n < 500:
            bad.append("定制品不足 500")
    print(f"  订单合计 {tot}")
    nc = c.execute("SELECT COUNT(DISTINCT customer_id) FROM ordr WHERE kind='定制品订单'").fetchone()[0]
    mx = c.execute("SELECT customer_id, COUNT(*) n FROM ordr WHERE kind='定制品订单' "
                   "GROUP BY 1 ORDER BY 2 DESC LIMIT 1").fetchone()
    print(f"  定制单挂在 {nc} 个客户名下 · 最多的 {mx[0]} {mx[1]} 张")
    for k, n in c.execute("""SELECT a.kind || '·' || o.kind, COUNT(*) FROM aftersale a
                             JOIN ordr o ON o.id=a.order_id GROUP BY 1"""):
        print(f"  售后 {k}: {n}")
    for k, n in c.execute("""SELECT o.kind, COUNT(*) FROM maintain m
                             JOIN ordr o ON o.id=m.order_id GROUP BY 1"""):
        print(f"  维保 {k}: {n}")
    ex = [dict(r) for r in c.execute(
        "SELECT a.*, o.source FROM aftersale a JOIN ordr o ON o.id=a.order_id WHERE a.kind='换货'")]
    跨渠道 = [e["id"] for e in ex if e["channel"] != e["source"]]
    print(f"  换货 {len(ex)} 张 · 差价 0 的 {sum(1 for e in ex if e['price_diff'] == 0)} · "
          f"有差价的 {sum(1 for e in ex if e['price_diff'] not in (None, 0))} · "
          f"还没算(NULL)的 {sum(1 for e in ex if e['price_diff'] is None)} · 跨渠道 {len(跨渠道)}")
    if 跨渠道:
        bad.append("换货跨渠道")
    return 1 if bad else 0


def main():
    global DB
    ap = argparse.ArgumentParser(description="订单分型 + 售后维保重建 + 客户汇总重算")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--db", default=DB, help="默认 backend/lanxiu.db;调试时指向副本")
    a = ap.parse_args()
    DB = a.db
    c = conn(DB)
    if a.report:
        sys.exit(report(c))
    with c:
        run(c)
    sys.exit(report(conn(DB)))


if __name__ == "__main__":
    main()
