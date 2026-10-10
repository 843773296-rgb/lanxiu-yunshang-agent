#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每天让演示世界**真的长出一点新东西**(2026-10-09 业务要的)。

    python3 tools/daily_fresh.py          # 只看会造什么,不写
    python3 tools/daily_fresh.py --做     # 真写
    python3 tools/daily_fresh.py --回滚   # 回滚「今天」那一批

## 为什么需要它

`tools/daily_shift.sh` 每天 05:10 跑 `shift_world`,把**整个世界的日期往前挪一天**。
它天天在跑、世界也天天自洽 —— 但**一条新记录都没有**:
> 用户 2026-10-09 的原话:「数据这几天没上新」「每天看到的是同一个世界,只是日期变了」。

⚠️⚠️ **先量过再定量,不要照「日均 89 单」去造。** 第一版的选型卡写的是
「按真实日均造(约 89 单/天),否则报表会出现断层」—— 那张卡的**前提是错的**:
平移之后**每一天本来就是满的**(实测 10-07 是 107 单、10-08 是 115 单,
最近 90 天日均 **108.8**;那个 89 是全年均值 32499/365,不是近期日均)。
照日均再造一遍,等于**把今天的密度翻一倍**。

> 一个「每天上新一百多单」和一个「把今天的密度翻一倍」,
> **在「上新了」这件事上长得一模一样** —— 而后者会让报表的日均凭空涨一倍。

业务 2026-10-09 重新拍的是:**小批新增 + 推进存量**。
所以这里造的量是「近期日均的一小部分」(现算,**不写死**),
外加让已有的单往前走一步 —— 后者**不增加任何记录**,只改状态。

## 它造什么

**新增**(都带 `daily_fresh/<日期>` 批次标记,可整批回滚):
  · 标品订单:`近 90 天日均 × 12%`,夹在 10–20 单之间(现算,不写死)
  · 订单行、库存占用流水(走 `fakedata/ledger` 那本台账,**不自己拼 before/after**)
  · 跟进 / 预约 / 评价(评价里按真实分布带少量差评)

**推进存量**(不新增记录,只改状态):
  · 几张「已发货」的标品单推到「完成」——
    每一步都先过 `backend/fsm.check`,**它说不行就不推**

## 它**不**造什么(明写出来,不是忘了)

  · **定制品订单** —— 要量体 / 方案 / 白坯试衣 / 签收码那一整条闸
    (`fsm.check` 的 MUSLIN_GATE / FIT_GATE / COMPLETE_GATE)。
    凭空插一张定制单会造出「闸没过却在生产中」的脏数据,
    而**那种脏数据在页面上看起来完全正常**。要做得走写口,是另一件事。
  · **受保护客户** —— `tools/order_mix.受保护客户()` 现扫出来的那些(边界夹具 +
    真值表点名的客户)。2026-10-09 就是因为 `seed_pending_orders` 没排到它们,
    5 张单落在夹具上,把「互动第 91 天」那个边界拉成了第 2 天。
  · **档位重算** —— 归 `tools/lifecycle_refresh.py`。
    造完要跑它一次(`daily_shift.sh` 里排在本脚本之后),
    否则新单改了事实而档位没跟着变,`lifecycle_sync_check` 的 C 类会红。

## 幂等

同一天重复跑**不会翻倍**:开跑先把「今天」那一批回滚掉,再按同一个种子重新生成
(种子 = 日期,所以同一天两次跑出来的是同一批)。这和 `simulate_sales` 的做法一致。
⚠️ **不是「已经有了就跳过」** —— 那样改完代码再跑一次拿不到新结果,
而「跳过了」和「跑过了」在输出上长得一模一样。
"""
import argparse
import datetime as dt
import json
import os
import random
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
                os.path.join(ROOT, "fakedata")]

import ledger as LG            # noqa: E402  台账链:after = before + 增减,而且接得上上一行
import worldclock as W         # noqa: E402
import fsm                     # noqa: E402
# ⚠️ 别起名 `R` —— 下面几行 `G, R, Y, D = ...` 里的 `R` 是红色转义码,会把它盖掉。
# > 一个 `import rating as R` 和一个 `R = "\033[31m"`,**在模块顶部长得一模一样**。
import rating as RT            # noqa: E402  差评口径(差评线 / 自动落待办)只有这一份
import order_mix as OM         # noqa: E402  只用它的「受保护客户」现扫

DB = os.path.join(ROOT, "backend", "lanxiu.db")
# ⚠️ 可以指定库(`--db 某个副本`)—— 造数脚本的试跑一律在副本上做,别拿真库当试验台
for _i, _a in enumerate(sys.argv):
    if _a == "--db" and _i + 1 < len(sys.argv):
        DB = sys.argv[_i + 1]
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

占比 = 0.12            # 新增单量 = 近 90 天日均 × 这个;下面再夹到 [下限, 上限]
下限, 上限 = 10, 20


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def 批次(日):
    return f"daily_fresh/{日}"


# ⚠️⚠️ **主键列名按表定,不许一律当成 `id`。**
# 2026-10-09 第一版只特判了 `rating`(pkg_id),漏了 `sku`(code)——
# 于是回滚当场 `no such column: id`。而**这个炸法伪装成了「幂等通过」**:
# 第二次 `--做` 开头也要先回滚,它同样炸 → 整个事务回滚 → 一行都没写 →
# 两次跑完的行数当然一样。
# > 一次「幂等:第二次跑出来一样」和一次「第二次直接炸了、什么都没写」,
# > **在那两行一模一样的数字上长得一模一样。**
# 更糟的是我当时**把输出丢进了 /dev/null**,所以崩溃看起来像成功 ——
# 验幂等要看**退出码**,不是看两个数字相等。
主键 = {"ordr": "id", "ordr_item": "id", "stock_log": "id", "followup": "id",
        "appointment": "id", "rating": "pkg_id", "sku": "code", "task": "id"}


def _主键(表):
    if 表 not in 主键:
        # 不猜。猜错的那一下会把回滚变成「什么都没撤掉而且不报错」
        raise SystemExit(f"❌ 表 {表} 没登记主键列 —— 往 daily_fresh.主键 里加一行")
    return 主键[表]


def _建表(c):
    c.execute("""CREATE TABLE IF NOT EXISTS daily_fresh_batch(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   batch TEXT NOT NULL, 表 TEXT NOT NULL, 主键 TEXT NOT NULL,
                   动作 TEXT NOT NULL, 原值 TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_dfb ON daily_fresh_batch(batch)")


def 回滚(c, 日, 说=print):
    """把那一天造的东西撤掉。**新增的删掉,改过的按原值写回。**"""
    b = 批次(日)
    行 = [dict(r) for r in c.execute(
        "SELECT * FROM daily_fresh_batch WHERE batch=? ORDER BY id DESC", (b,))]
    if not 行:
        return 0
    n = 0
    for r in 行:
        if r["动作"] == "新增":
            # 主键列名按表定,别一律当成 id
            c.execute(f"DELETE FROM {r['表']} WHERE {_主键(r['表'])}=?", (r["主键"],))
            n += 1
        elif r["动作"] == "改过":
            旧 = json.loads(r["原值"])
            c.execute(f"UPDATE {r['表']} SET " + ",".join(f"{k}=?" for k in 旧)
                      + f" WHERE {_主键(r['表'])}=?", [旧[k] for k in 旧] + [r["主键"]])
            n += 1
    c.execute("DELETE FROM daily_fresh_batch WHERE batch=?", (b,))
    说(f"  回滚 {b}:撤掉 {n} 条")
    return n


def _记(c, 日, 表, 键值, 动作, 原值=None):
    """往回滚台账记一笔。

    ⚠️⚠️ **当场验这个主键找得回那一行。** 2026-10-09 栽过:`followup.id` 是 TEXT,
    而我按自增整数的写法用了 `cur.lastrowid` —— 台账记了一个找不回去的主键,
    于是回滚**「撤掉 0 条」而且一个字都不报**。
    > 一次「回滚干净了」和一次「回滚按一个找不到的主键删了 0 行」,
    > **在那句「回滚完成」上长得一模一样。**
    一行一次 SELECT(每天约 80 行,可以忽略),换来的是这类错**不可能静默通过**。
    """
    if c.execute(f"SELECT 1 FROM {表} WHERE {_主键(表)}=? LIMIT 1",
                 (键值,)).fetchone() is None:
        raise SystemExit(f"❌ 记台账时按 {_主键(表)}={键值!r} 在 {表} 里找不到那一行 —— "
                         f"**这个主键回滚时也找不到**,先把它记对再说(见 daily_fresh.主键)")
    c.execute("INSERT INTO daily_fresh_batch(batch,表,主键,动作,原值) VALUES(?,?,?,?,?)",
              (批次(日), 表, str(键值), 动作,
               json.dumps(原值, ensure_ascii=False, default=str) if 原值 else None))


def 现算日均(c, 今):
    """**现算,不写死。** 写死的数字会过期,而过期时它读着仍然很顺。"""
    w0 = (今 - dt.timedelta(days=90)).isoformat()
    n = c.execute("SELECT count(*) FROM ordr WHERE substr(created,1,10)>=? "
                  "AND substr(created,1,10)<?", (w0, 今.isoformat())).fetchone()[0]
    return n / 90.0


def 候选客户(c, 护):
    """有过订单、不在受保护名单里的客户。按 id 排序后由种子抽 —— 不用随机序,重跑一致。"""
    return [r[0] for r in c.execute(
        "SELECT DISTINCT customer_id FROM ordr ORDER BY customer_id")
        if r[0] not in 护]


def 候选sku(c, 今):
    """按**近 90 天实际销量**加权的在售 SKU,以及它当下的「可用」。

    ⚠️ 加权用的是**库里真实卖出去的量**,不是另写一套需求模型 ——
    今天一整天都在修「同一套口径被手抄成两份」的后果,这里不再开第三份。
    它抽的就是主生成器的产物,所以**不可能和主生成器分叉**。
    """
    w0 = (今 - dt.timedelta(days=90)).isoformat()
    卖 = dict(c.execute(
        """SELECT i.sku, sum(i.qty) FROM ordr_item i JOIN ordr o ON o.id=i.order_id
            WHERE substr(o.created,1,10)>=? AND o.status<>'取消' GROUP BY 1""", (w0,)).fetchall())
    出 = []
    # ⚠️ 商品名在 `product.name` 上,**`sku` 表没有 `name` 列**(第一版就这么写的,当场炸)。
    # 顺带只取在售的:`sku.status='启用'` + `product.status='上架'` ——
    # 给一个已下架的商品造今天的新单,是**在页面上看起来正常**的那种脏数据。
    # ⚠️ 带上版型的**当前版本**:挂着版型的订单行必须记下「下单那一刻是哪一版」。
    # 第一版没记 —— `backend/pattern_check` 的判据当场红(缺 12 条)。
    # 这不是补一列的事:**版型会改版,而订单行记的必须是当时那一版** ——
    # 不记的话,哪天版型改了,这一单看起来就像是按新版做的。
    # > 一行「按当时那一版做的」和一行「没记版本」,
    # > **在版型没改过的那段时间里长得一模一样。**
    for r in c.execute("""SELECT s.code, s.spu, p.name, s.price, s.stock, s.locked,
                                 p.pattern, t.version pv
                            FROM sku s JOIN product p ON p.spu=s.spu
                            LEFT JOIN pattern t ON t.code=p.pattern
                           WHERE s.status='启用' AND p.status='上架' AND p.kind='标品'
                           ORDER BY s.code"""):
        可用 = (r["stock"] or 0) - (r["locked"] or 0)
        w = 卖.get(r["code"], 0)
        if w > 0 and 可用 > 0:
            出.append({"code": r["code"], "spu": r["spu"], "name": r["name"],
                       "price": r["price"] or 0, "可用": 可用, "w": w,
                       "pattern": r["pattern"], "pv": r["pv"]})
    return 出


def _流水时刻(c, 已发过, code, 想要的):
    """给这条流水一个**严格晚于该 SKU 现有最大时刻**的时间戳。

    ⚠️⚠️ `backend/stock_check.py` 取「链尾」用的是 **`MAX(ts)`**,不是 `MAX(id)`。
    而演示世界的「今天」是**已经过完的**(平移把全年数据整体挪过来,
    今天的流水最晚到 23:44),所以我插一条白天的时间:
    **按 id 它在末尾,按 ts 它不是最后一条** —— 链尾就落到了别人那一行上,
    `after_n` 自然对不上「可用」。
    > 一个「链尾按 id 取」和一个「按 ts 取」,
    > **在流水严格按时间插入的库里长得一模一样。**
    现有数据是分钟精度,所以这里补到秒级来保证严格大于(字符串比较也成立)。
    """
    m = 已发过.get(code)
    if m is None:
        r = c.execute("SELECT max(ts) FROM stock_log WHERE sku=?", (code,)).fetchone()
        m = r[0] if r and r[0] else None
    if m and m >= 想要的:
        秒 = 59 if len(m) <= 16 else min(59, int(m[17:19]) + 1)
        出 = f"{m[:16]}:{秒:02d}"
    else:
        出 = 想要的
    已发过[code] = 出
    return 出


def 台账起点(c, code, 可用):
    """那个 SKU 的流水链尾 —— **接得上上一行**,而不是从「可用」重新起头。

    没有流水的 SKU 才用「可用」当起始(库里大多数 SKU 根本没有流水)。
    """
    # ⚠️ 按 **ts** 取链尾,和 `stock_check` 同一个口径(它用 MAX(ts),不是 MAX(id))
    r = c.execute("SELECT after_n FROM stock_log WHERE sku=? "
                  "ORDER BY ts DESC, id DESC LIMIT 1", (code,)).fetchone()
    return LG.台账(code, 起始=(r[0] if r and r[0] is not None else 可用))


def 生成(c, 今, rng, 护, 说=print):
    日 = 今.isoformat()
    日均 = 现算日均(c, 今)
    要几单 = max(下限, min(上限, round(日均 * 占比)))
    说(f"近 90 天日均 {日均:.1f} 单 → 今天新增 {要几单} 单(日均×{占比:.0%},夹在 {下限}–{上限})")

    客 = 候选客户(c, 护)
    skus = 候选sku(c, 今)
    if len(客) < 100 or len(skus) < 20:
        说(f"  {R}❌{D} 候选不够:客户 {len(客)} / SKU {len(skus)} —— "
           f"**这不叫「今天没什么可造」,叫取数取空了**")
        return None
    店们 = [r[0] for r in c.execute("SELECT DISTINCT shop FROM ordr WHERE shop IS NOT NULL ORDER BY 1")]
    顾问 = {s: [r[0] for r in c.execute(
        "SELECT no FROM staff WHERE role='顾问' AND status='启用' AND shop=? ORDER BY no", (s,))]
        for s in 店们}
    店们 = [s for s in 店们 if 顾问.get(s)]

    台账, 流水钟 = {}, {}
    计 = {"订单": 0, "订单行": 0, "流水": 0, "跟进": 0, "预约": 0, "评价": 0, "推进": 0}
    # ── ① 新增标品订单 ──────────────────────────────────────────────
    for k in range(要几单):
        cid = rng.choice(客)
        店 = rng.choice(店们)
        adv = rng.choice(顾问[店])
        # ⚠️ 十位只能是 0–5。原来写的是 `'0123456'` —— 抽到 6 就生成 **60~69 分**,
        # 而那是个**非法时间戳**:SQLite 的 `date()` 解析不了就返回 NULL。
        # 后果出现在一条**完全无关**的检查上:`link_check` 的门槛是
        # `date(max(ordr.created), '-180 day')`,最大那行一旦非法,门槛变 NULL,
        # `hired_at >= NULL` 永不为真 → 报「半年内入职的顾问 0 人」。
        # 而库里明明有新人(工号 60000015,世界今天前 60 天)。
        # **而且它是间歇的**:max(created) 随每日上新变,所以同一份代码今天绿明天红。
        时 = f"{日} {rng.randint(10, 20):02d}:{rng.choice('012345')}{rng.randint(0,9)}"
        oid = f"DF{今.strftime('%y%m%d')}{k:03d}"
        行们 = []
        for _ in range(rng.choice([1, 1, 1, 2])):
            s = rng.choices(skus, weights=[x["w"] for x in skus], k=1)[0]
            台 = 台账.setdefault(s["code"], 台账起点(c, s["code"], s["可用"]))
            qty = 1
            if not 台.够吗(qty):
                continue
            行们.append((s, qty, 台))
        if not 行们:
            continue
        金 = round(sum(s["price"] * q for s, q, _ in 行们), 2)
        # 状态按库里标品的真实分布来:绝大多数是完成,少量在途
        态 = rng.choices(["完成", "已发货", "待付款"], weights=[88, 8, 4], k=1)[0]
        prd = {"完成": "已完成", "已发货": "待收货", "待付款": "待付款"}[态]
        付 = None if 态 == "待付款" else 时
        发 = 时 if 态 in ("完成", "已发货") else None
        完 = 时 if 态 == "完成" else None
        # ⚠️⚠️ **`appt_src` 必须显式写「无预约」。** 这一列上有默认值 `'未接入'`,
        # 所以不填 ≠ 空 —— 它会填成 `未接入`,而业务硬规则(2026-09-20)是
        # 「**定制品必须有预约才能做,标品全部不用**」,
        # `backend/link_check.py` 的判据要的是字面的 `无预约`。
        # 第一版漏了它,13 张新单全被判成「标品却有预约来源」。
        # > 一个「我没填这一列」和一个「我填了『未接入』」,
        # > **在 INSERT 语句里长得一模一样** —— 因为列上有默认值。
        # (查过:`ordr` 上带默认值而这里没填的,只有这一列。)
        c.execute("""INSERT INTO ordr(id,customer_id,kind,status,shop,source,delivery,
                      amount,payable,created,updated,prd_status,goods_amount,freight,received,
                      refund_status,paid_at,shipped_at,finished_at,advisor_no,appt_src)
                     VALUES(?,?,'标品订单',?,?,'门店 Pad','配送到店',?,?,?,?,?,?,0,?,'未退款',?,?,?,?,'无预约')""",
                  (oid, cid, 态, 店, 金, 金, 时, 时, prd, 金,
                   0 if 态 == "待付款" else 金, 付, 发, 完, adv))
        _记(c, 日, "ordr", oid, "新增")
        计["订单"] += 1
        for s, qty, 台 in 行们:
            cur = c.execute("""INSERT INTO ordr_item(order_id,sku,name,tag,price,qty,spu,
                                 base_amount,custom_amount,total,
                                 pattern_version,pattern_version_src)
                               VALUES(?,?,?,'标品',?,?,?,?,0,?,?,?)""",
                            (oid, s["code"], s["name"], s["price"], qty, s["spu"],
                             s["price"] * qty, s["price"] * qty, s["pv"],
                             f"每日上新({批次(日)}):取下单那一刻版型的当前版本"
                             if s["pv"] is not None else None))
            _记(c, 日, "ordr_item", cur.lastrowid, "新增")
            计["订单行"] += 1
            if 态 == "待付款":
                continue                     # 没付款不占库(和库里的口径一致)
            L = 台.记(_流水时刻(c, 流水钟, s["code"], 时), "订单占用", -qty,
                      凭据=oid, 备注=f"每日上新 {日}")
            cur = c.execute("""INSERT INTO stock_log(sku,spu,kind,delta,before_n,after_n,
                                 ref,operator,ts,note)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (L["键"], s["spu"], L["类型"], L["增减"], L["前"], L["后"],
                             L["凭据"], adv, L["时间"], L["备注"]))
            _记(c, 日, "stock_log", cur.lastrowid, "新增")
            计["流水"] += 1
            # 发货:在手和占用各减一样多 → 可用不变 → **不写流水**(口径在 knowledge/stockalert)
            # 到这里的一定是「完成」或「已发货」(待付款在上面 continue 掉了)——
            # 两者都已经发出去了,而**发货让在手和占用各减一样多、可用不变**,
            # 所以净效果是:在手 −qty、占用不动。口径在 knowledge/stockalert.py。
            老 = dict(c.execute("SELECT stock, locked FROM sku WHERE code=?",
                                (s["code"],)).fetchone())
            _记(c, 日, "sku", s["code"], "改过", 老)
            c.execute("UPDATE sku SET stock=? WHERE code=?",
                      ((老["stock"] or 0) - qty, s["code"]))

    # ── ② 跟进 / 预约 / 评价 ────────────────────────────────────────
    for k in range(rng.randint(3, 6)):
        cid = rng.choice(客)
        店 = rng.choice(店们)
        # ⚠️ `followup.id` 是 **TEXT**(库里是 `FAP3000` 这种),不是自增整数。
        # 第一版没给 id —— 存进去是 NULL,而 `cur.lastrowid` 返回的是 rowid,
        # 于是台账记了一个找不回那一行的主键,**回滚时「撤掉 0 条」而且不报错**。
        # > 一行「主键是自增整数」和一行「主键是文本而我没给值」,
        # > **在 `lastrowid` 返回一个数字这件事上长得一模一样。**
        fid = f"DFF{今.strftime('%y%m%d')}{k:02d}"
        c.execute("""INSERT INTO followup(id,customer_id,ts,channel,content,advisor_no)
                           VALUES(?,?,?,?,?,?)""",
                        (fid, cid, f"{日} {rng.randint(9,19):02d}:{rng.randint(10,59)}",
                         rng.choices(["电话", "微信", "到店"], weights=[80, 15, 5], k=1)[0],
                         rng.choice(["回访穿着体验", "确认交期", "邀约到店试衣",
                                     "介绍新到面料", "节前保养提醒"]),
                         rng.choice(顾问[店])))
        _记(c, 日, "followup", fid, "新增")
        计["跟进"] += 1
    for k in range(rng.randint(2, 4)):
        cid = rng.choice(客)
        店 = rng.choice(店们)
        h = rng.randint(10, 18)
        aid = f"DFA{今.strftime('%y%m%d')}{k:02d}"
        c.execute("""INSERT INTO appointment(id,customer_id,shop,advisor_no,start_ts,end_ts,status)
                     VALUES(?,?,?,?,?,?,'已预约')""",
                  (aid, cid, 店, rng.choice(顾问[店]),
                   f"{日} {h:02d}:00", f"{日} {h+1:02d}:00"))
        _记(c, 日, "appointment", aid, "新增")
        计["预约"] += 1
    # ── 评价 ────────────────────────────────────────────────────────
    # ⚠️⚠️ **评价挂的是「包裹」,不是订单,而且必须晚于那个包裹的「签收合身」那一刻。**
    # 第一版我凭空造了个 `pkg_id`、`src` 写「每日上新」,`backend/rating_check.py` 两条当场红:
    #     「没签收就评了」—— 那个 pkg_id 在 `pickup_item` 里没有 `fit_result='合身'` 的记录
    #     「来源不对」—— `src` 只认 `顾客小程序`
    # 判据在 rating_check:`rated_at >= max(fit_at where fit_result='合身')`。
    #
    # 所以这里只从**已签收合身、而且还没评过**的包裹里抽(库里有 1686 个)——
    # 这不是将就,这就是真事:**顾客签收之后隔几天才评**。
    # 而且只取 `fit_at` 在**今天之前**的,免得撞上「今天 23:44 才签收」却被评在上午。
    可评 = [dict(r) for r in c.execute(
        """SELECT t.pkg_id, t.order_id, max(t.fit_at) fit_at, o.customer_id, o.advisor_no
             FROM pickup_item t JOIN ordr o ON o.id=t.order_id
            WHERE t.fit_result='合身' AND substr(t.fit_at,1,10)<?
              AND t.pkg_id NOT IN (SELECT pkg_id FROM rating)
            GROUP BY t.pkg_id ORDER BY t.pkg_id LIMIT 600""", (日,))]
    rng.shuffle(可评)
    for k, o in enumerate(可评[:rng.randint(2, 5)]):
        # 星级按库里的真实分布抽(1★30 / 2★55 / 3★126 / 4★254 / 5★1168)——
        # 所以差评是**偶尔**出现,不是每天都有。业务要的「含少量差评」就是这个意思。
        # (期望:每天 2–5 条 × ≤2★ 占 5.2% → **平均 5–6 天才出一条差评**。
        #  想更频繁地看到「低于 3 分进要分析」那条链,得调高概率,**那会偏离真实分布**。)
        星 = rng.choices([1, 2, 3, 4, 5], weights=[30, 55, 126, 254, 1168], k=1)[0]
        评语 = {1: "很不满意,衣服不合身", 2: "交期拖了,沟通也慢",
                3: "还行,细节一般", 4: "挺满意", 5: "非常满意,下次还来"}[星]
        评于 = f"{日} {rng.randint(9,21):02d}:{rng.randint(10,59)}"
        # ⚠️⚠️ **≤3 星要当场落一张待处理工单。** 业务 2026-09-27:差评**自动进**清单,
        # 不是躺在表里等人捞。`backend/rating_check.py` 两个方向都查:
        #     「差评没进清单」(≤差评线 而没有工单)
        #     「好评却挂了工单」(>差评线 却有工单)—— **只查一个方向会漏掉另一半**,
        #       而「差评都进了清单」和「清单里全是差评」是两件事。
        # 差评线和那一行待办的内容都走 `knowledge/rating.py`,**这里不另写一份判定**。
        tid = None
        if RT.是差评(星):
            tid = f"TR{o['pkg_id']}"
            待 = RT.差评待办(星, 评语, o["order_id"], o["pkg_id"], 评于, o["advisor_no"])
            c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) "
                      "VALUES(?,?,?,?,?,?)",
                      (tid, 待["kind"], o["pkg_id"], 待["status"], 评于,
                       f"{星} 星差评:{评语}"))
            _记(c, 日, "task", tid, "新增")
        c.execute("""INSERT INTO rating(pkg_id,order_id,customer_id,star,note,rated_at,src,
                       advisor_no,edit_cnt,anonymous,task_id)
                     VALUES(?,?,?,?,?,?,'顾客小程序',?,0,0,?)""",
                  (o["pkg_id"], o["order_id"], o["customer_id"], 星, 评语,
                   评于, o["advisor_no"], tid))
        _记(c, 日, "rating", o["pkg_id"], "新增")
        计["评价"] += 1

    # ── ③ 推进存量(不新增记录,只改状态) ───────────────────────────────
    #
    # ⚠️⚠️ **只推那些不需要凭据的边。** 第一版我写的是「已发货 → 完成」,
    # 而 `fsm.check` 三连拒:
    #     已发货 → 完成    SKIP            跳过了「待完成」的校验与记账
    #     已发货 → 待完成  FIT_GATE        要顾客在手机上点「试穿合身」拿到的 6 位码
    #     待完成 → 完成    COMPLETE_GATE   要顾客自己确认,或签收满 15 天由顾问写理由追认
    #     待发货 → 已发货  FACTORY_GATE    只认工厂回传 —— 生产和发货是工厂报的事实
    # 这四条是这个项目**最硬的那层保证**。要推它们得走写口把真凭据带上,
    # **绝不在这里伪造凭据直接 UPDATE** —— 那正是这个脚本注释里警告的
    # 「闸没过却状态变了」的脏数据,而它**在页面上看起来完全正常**。
    #
    # 所以这里只推两条实测放行的(`fsm.check` 返回 OK):
    #     bk-order  待付款 → 待发货
    #     bk-appt   已预约 → 已到店 → 已完成
    # 「昨天约的客户今天到店」正好是**每天都该变一次**的那种事。
    def _推(机, 表, 行id, frm, to, 列, 老):
        ok, code, why = fsm.check(机, frm, to)
        if not ok:
            说(f"    ↳ 状态机不让推({frm}→{to}):{code} {(why or '')[:46]} —— 跳过")
            return False
        _记(c, 日, 表, 行id, "改过", 老)
        c.execute(f"UPDATE {表} SET " + ",".join(f"{k}=?" for k in 列)
                  + f" WHERE {_主键(表)}=?", [列[k] for k in 列] + [行id])
        计["推进"] += 1
        return True

    # 预约:开始时间已经过去了的「已预约」→ 已到店;昨天到店的 → 已完成
    约 = [dict(r) for r in c.execute(
        """SELECT id, status, start_ts, checkin_ts FROM appointment
            WHERE status='已预约' AND substr(start_ts,1,10)<=? ORDER BY id LIMIT 40""", (日,))]
    rng.shuffle(约)
    for r in 约[:rng.randint(1, 3)]:
        # ⚠️⚠️ **签到时间要紧跟那个预约的开始时间,不能另取一个随机小时。**
        # 第一版写的是 `f"{日} {rng.randint(10,18)}:05"` —— `backend/booking_check.py`
        # 当场红:「签到晚于预约两小时以上,多半是日期整体挪动时漏挪了这一列」。
        # 注意它那句提示指的是**另一种**病因(漏挪),而我的是第三种(凭空取时间)——
        # > 一条「漏挪了这一列」的红和一条「我另取了一个时间」的红,
        # > **在那条判据上长得一模一样**,而提示会把人带去查平移。
        到 = f"{str(r['start_ts'])[:16].rstrip()}"
        到 = 到[:11] + 到[11:16]           # 'YYYY-MM-DD HH:MM'
        try:
            时分 = 到[11:16].split(":")
            分 = int(时分[1]) + rng.randint(2, 20)
            小 = int(时分[0]) + 分 // 60
            到 = f"{到[:11]}{小:02d}:{分 % 60:02d}"
        except Exception:
            到 = f"{日} 10:05"
        _推("bk-appt", "appointment", r["id"], "已预约", "已到店",
            {"status": "已到店", "checkin_ts": 到},
            {"status": r["status"], "checkin_ts": r["checkin_ts"]})
    到 = [dict(r) for r in c.execute(
        """SELECT id, status FROM appointment
            WHERE status='已到店' AND substr(start_ts,1,10)<? ORDER BY id LIMIT 40""", (日,))]
    rng.shuffle(到)
    for r in 到[:rng.randint(1, 3)]:
        _推("bk-appt", "appointment", r["id"], "已到店", "已完成",
            {"status": "已完成"}, {"status": r["status"]})
    # 标品单:待付款 → 待发货(付款这件事本身不需要闸的凭据)
    待付 = [dict(r) for r in c.execute(
        """SELECT id, status, prd_status, paid_at, received, payable, updated FROM ordr
            WHERE kind='标品订单' AND status='待付款' ORDER BY id LIMIT 60""")]
    rng.shuffle(待付)
    for o in 待付[:rng.randint(1, 4)]:
        时 = f"{日} {rng.randint(10,19):02d}:{rng.randint(10,59)}"
        # ⚠️⚠️ **付款之后要占库,这一笔不能漏。**
        # 实测:库里 91 张「待付款」标品单**一张都没有订单占用流水**(0/91)——
        # 所以「未付款不占库」是真实口径,那么推到「待发货」的那一刻就该占上。
        # 第一版只改了状态没写占用,`backend/stock_check.py` 当场红:
        #     「流水链尾对不上可用的」3/650(上限 0,只许降不许涨)
        # > 一次「把单推进了一步」和一次「把单推进了一步而库存没跟着动」,
        # > **在那张单的状态上长得一模一样** —— 只有流水链尾泄露了它。
        占 = [dict(r) for r in c.execute(
            """SELECT i.sku, i.qty, i.spu, s.stock, s.locked FROM ordr_item i
                 JOIN sku s ON s.code=i.sku WHERE i.order_id=?""", (o["id"],))]
        if any(not 台账.setdefault(x["sku"], 台账起点(c, x["sku"], (x["stock"] or 0) - (x["locked"] or 0))
                                  ).够吗(x["qty"]) for x in 占):
            说(f"    ↳ {o['id']} 有件数不够的 SKU,不推(付款了却占不上库,比不推更糟)")
            continue
        if not _推("bk-order", "ordr", o["id"], "待付款", "待发货",
                   {"status": "待发货", "prd_status": "待发货", "paid_at": 时,
                    "received": o["payable"], "updated": 时},
            # ⚠️ 原值里的 `updated` 必须是**库里原来那个**,不是刚算出来的 `时`。
            # 第一版两边都写了 `时` —— 回滚时会把它写成一个从没存在过的值,
            # 而**那一行看起来完全正常**,只有「它和回滚前不一样」这一点泄露了它。
                   {"status": o["status"], "prd_status": o["prd_status"],
                    "paid_at": o["paid_at"], "received": o["received"],
                    "updated": o["updated"]}):
            continue
        for x in 占:
            L = 台账[x["sku"]].记(_流水时刻(c, 流水钟, x["sku"], 时), "订单占用", -x["qty"],
                                 凭据=o["id"], 备注=f"每日上新·付款占库 {日}")
            cur = c.execute("""INSERT INTO stock_log(sku,spu,kind,delta,before_n,after_n,
                                 ref,operator,ts,note)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (L["键"], x["spu"], L["类型"], L["增减"], L["前"], L["后"],
                             L["凭据"], "SYS", L["时间"], L["备注"]))
            _记(c, 日, "stock_log", cur.lastrowid, "新增")
            计["流水"] += 1
            老 = dict(c.execute("SELECT stock, locked FROM sku WHERE code=?",
                                (x["sku"],)).fetchone())
            _记(c, 日, "sku", x["sku"], "改过", 老)
            # 待发货 = 已付款未发货 → **占用 +qty,在手不动**(可用 = 在手 − 占用,所以可用 −qty)
            c.execute("UPDATE sku SET locked=? WHERE code=?",
                      ((老["locked"] or 0) + x["qty"], x["sku"]))
    return 计


def main():
    ap = argparse.ArgumentParser(description="每天让演示世界长出一点新东西")
    ap.add_argument("--做", action="store_true", dest="做")
    ap.add_argument("--回滚", action="store_true", dest="回滚")
    ap.add_argument("--db", default=None)      # 上面已经读过了,这里只为让 argparse 认它
    a = ap.parse_args()
    今 = W.今天()
    c = conn()
    _建表(c)
    print(f"世界的今天:{今}(从库里读,不碰机器时钟)· 批次 {批次(今.isoformat())}")

    if a.回滚:
        with c:
            n = 回滚(c, 今.isoformat())
        print(f"{G}✅{D} 回滚完成" if n else f"{Y}·{D} 今天这一批本来就不在")
        return 0

    护 = OM.受保护客户(c)
    # ⚠️ **样本量判据**:扫不到夹具时「都排除了」也成立,而那一轮会把反例一起写坏。
    if len(护) < 14:
        print(f"{R}❌{D} 受保护客户只扫出 {len(护)} 个 —— **扫挂了,不是「没有夹具」**,不造")
        return 1
    print(f"受保护客户 {len(护)} 个不碰")

    if not a.做:
        日均 = 现算日均(c, 今)
        n = max(下限, min(上限, round(日均 * 占比)))
        已有 = c.execute("SELECT count(*) FROM daily_fresh_batch WHERE batch=?",
                         (批次(今.isoformat()),)).fetchone()[0]
        print(f"近 90 天日均 {日均:.1f} 单 → 会新增 {n} 单(+跟进/预约/评价,再推进几单)")
        print(f"今天这一批现在有 {已有} 条记录 —— 真跑会**先回滚它再重造**(同种子,同结果)")
        print(f"{Y}只看不做{D}。真写加 --做")
        return 0

    with c:
        回滚(c, 今.isoformat())            # 幂等:先撤再造,不是「有了就跳过」
        rng = random.Random(int(今.strftime("%Y%m%d")))   # 种子=日期,同一天重跑一致
        计 = 生成(c, 今, rng, set(护), 说=print)
        if 计 is None:
            c.rollback()
            return 1
    print("  造了:" + " · ".join(f"{k} {v}" for k, v in 计.items()))
    print(f"  {G}✅{D} 写完。回滚:python3 tools/daily_fresh.py --回滚")
    print(f"  {Y}下一步{D}:跑 python3 tools/lifecycle_refresh.py --做 "
          f"—— 新单改了事实,档位要跟着重算(否则 lifecycle_sync_check 的 C 类会红)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
