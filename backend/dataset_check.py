# -*- coding: utf-8 -*-
"""演示数据集的**形状** —— 业务 2026-09-18 定过的样子,不许被一次重建悄悄改掉。

规格在 `intent/order-aftersale-dataset.md`,生成在 `tools/order_mix.py` / `grow_customers.py`。

## 为什么要有它

这批数据的好几条性质,**只是造的时候做对了**,没有任何东西守着:

    · 订单上写着「已退款」的标品单,就有一张对应的退货单
    · 定制品、退货、换货、维保的占比,在业务拍过板的比例附近
    · 维保率在不同面料上**有高有低** —— 版师「哪种面料容易坏」的分析就靠它
    · 客户的单数 / 实付 / 等级和他名下的订单对得上(业务定了按订单重算)
    · 数量不是整数(用户原话:「数量别是 5000、100 这种,要有随机性」)
    · 车间工单挂的订单状态对得上(在制的挂在生产中的单上)

下次有人调一个模拟参数、重建一遍,这几条可能就不成立了 ——
**而门禁照样全绿**,因为别的检查验的是规则,不是形状。

## 期望值是**照拍板手抄的**,不从生成器里 import

从 `order_mix` 读比率再拿来验 `order_mix` 造的数据,那是同源谬误:
生成器的比率改错了,期望跟着错,检查什么都看不见。下面的区间是照
业务拍过板的那一版(3903 单:定制 520 / 退货 40 / 换货 15 / 维保 定制 40 + 标品 15)
手算出来、再放宽的。改口径应该是一件要动手的事。
"""
import math
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FAIL, DONE = [], []

# ── 照拍板手抄的比率区间(放宽过,只拦「形状变了」,不拦正常波动)──────────
定制品下限 = 500                       # 业务原话:「依旧需要保证定制品、标品数量」
定制品占比 = (0.09, 0.18)              # 拍板那版 13%
退货率 = (0.006, 0.02)                 # 占标品;拍板那版 1.2%
换货率 = (0.002, 0.008)                # 占标品;拍板那版 0.44%
定制维保率 = (0.04, 0.12)              # 占定制;拍板那版 7.7%


def ck(name, ok, n, msg="", 下限=1):
    DONE.append(name)
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n < 下限:
        print(f"     ⚠️ 样本量 {n} < {下限} —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量不足)")


def 受保护客户(c):
    """汇总是手工摆的那些客户:E- 前缀、truth 里点名的、评测里写死的。
    ⚠️ 这一份**独立写**,不调 order_mix.受保护客户 —— 调它就是拿生成器验生成器。"""
    ids = {r[0] for r in c.execute("SELECT id FROM customer")}
    out = {i for i in ids if i.startswith("E-")}
    for row in c.execute("SELECT case_id, expected_evidence, note FROM truth"):
        out |= {x for x in re.findall(r"\b(C\d{5}|E-[A-Z]\d-\d{2})\b",
                                      " ".join(str(v or "") for v in row)) if x in ids}
        if row[0] in ids:
            out.add(row[0])
    # 评测 / 检查脚本里写死的客户号(它们的题目前提读的是汇总字段)
    for d in ("agent", "backend", "tools"):
        for fn in os.listdir(os.path.join(ROOT, d)):
            if fn.endswith(".py") and re.search(r"eval|check|fixture", fn) and fn != os.path.basename(__file__):
                src = open(os.path.join(ROOT, d, fn), encoding="utf-8", errors="ignore").read()
                out |= {x for x in re.findall(r"['\"](C1\d{4})['\"]", src) if x in ids}
    return out


def main():
    print("演示数据集 · 形状(业务拍过板的样子)")
    print("=" * 80)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row
    n_all = c.execute("SELECT COUNT(*) FROM ordr").fetchone()[0]
    n_cus = c.execute("SELECT COUNT(*) FROM ordr WHERE kind='定制品订单'").fetchone()[0]
    n_std = c.execute("SELECT COUNT(*) FROM ordr WHERE kind='标品订单'").fetchone()[0]

    # ── ① 退款状态和售后单对得上 ────────────────────────────────────
    #   标品:退款中 / 已退款 ⇔ 有一张没被拒的「退货退款」
    #   定制:退款中 / 已退款 ⇔ 有一张「仅退款」(定制品没有退货,钱只能从这儿退)
    #   两个方向都要验:只验一边的话,把售后单整批删掉,「有退款状态的都有单」会空着成立
    bad1 = []
    for r in c.execute("""SELECT o.id, o.kind, o.refund_status,
            (SELECT COUNT(*) FROM aftersale a WHERE a.order_id=o.id AND a.kind='退货退款'
               AND a.status<>'审批拒绝') ret,
            (SELECT COUNT(*) FROM aftersale a WHERE a.order_id=o.id AND a.kind='仅退款') ref
            FROM ordr o"""):
        退了 = r["refund_status"] in ("退款中", "已退款")
        有单 = r["ret"] > 0 if r["kind"] == "标品订单" else r["ref"] > 0
        if 退了 != 有单:
            bad1.append(f"{r['id'][-6:]}({r['kind'][:2]}·{r['refund_status']}·"
                        f"{'有' if 有单 else '没有'}单)")
    n1 = c.execute("SELECT COUNT(*) FROM ordr WHERE refund_status IN ('退款中','已退款')").fetchone()[0]
    ck("① 订单的退款状态和售后单对得上(两个方向)", not bad1, n1,
       f"对不上 {len(bad1)} 张:{bad1[:4]}" if bad1 else
       "订单说退了钱,就有一张退钱的单;有退钱的单,订单就说退了", 下限=20)

    # ── ② 占比在拍板的区间里,而且三类的大小关系对 ─────────────────────
    #   业务原话:「退货可以」「换货可以少点」「维保这类的可以多一些」
    ret = c.execute("SELECT COUNT(*) FROM aftersale a JOIN ordr o ON o.id=a.order_id "
                    "WHERE a.kind='退货退款' AND o.kind='标品订单'").fetchone()[0]
    exc = c.execute("SELECT COUNT(*) FROM aftersale a JOIN ordr o ON o.id=a.order_id "
                    "WHERE a.kind='换货' AND o.kind='标品订单'").fetchone()[0]
    mc = c.execute("SELECT COUNT(*) FROM maintain m JOIN ordr o ON o.id=m.order_id "
                   "WHERE o.kind='定制品订单'").fetchone()[0]
    mall = c.execute("SELECT COUNT(*) FROM maintain").fetchone()[0]
    r2 = dict(定制占比=n_cus / max(n_all, 1), 退货率=ret / max(n_std, 1),
              换货率=exc / max(n_std, 1), 定制维保率=mc / max(n_cus, 1))
    区间 = dict(定制占比=定制品占比, 退货率=退货率, 换货率=换货率, 定制维保率=定制维保率)
    越界 = [f"{k} {v:.2%} 不在 {区间[k][0]:.1%}–{区间[k][1]:.1%}" for k, v in r2.items()
            if not (区间[k][0] <= v <= 区间[k][1])]
    if n_cus < 定制品下限:
        越界.append(f"定制品 {n_cus} 张 < 下限 {定制品下限}")
    if not (exc < ret < mall):
        越界.append(f"大小关系应是 换货 < 退货 < 维保,现在 {exc} / {ret} / {mall}")
    ck("② 占比在拍板的区间里,换货 < 退货 < 维保", not 越界, n_all,
       "；".join(越界) if 越界 else
       " · ".join(f"{k} {v:.2%}" for k, v in r2.items()), 下限=1000)

    # ── ③ 维保率在面料上有差异(版师分析的前提)──────────────────────
    #   判据不照抄生成器的分档 —— 那是同源。**按面料本身**分组,看有没有哪一种
    #   偏离整体维保率超过两倍二项噪声。一种都没有,「哪种面料容易坏」就只剩噪声。
    #   只看定制品:它的面料记在分部位选料里,是结构化的;标品的面料只在品名里
    sold, hit = {}, {}
    for r in c.execute("""
            SELECT (SELECT p.material FROM item_part_choice p WHERE p.item_id=i.id AND p.kind='面料'
                    ORDER BY (p.part IN ('主身','整件')) DESC, p.id LIMIT 1) mat,
                   EXISTS(SELECT 1 FROM maintain m WHERE m.order_item_id=i.id) hit
            FROM ordr o JOIN ordr_item i ON i.order_id=o.id
            WHERE o.kind='定制品订单' AND o.status='完成'
              AND i.id=(SELECT MIN(id) FROM ordr_item x WHERE x.order_id=o.id)"""):
        if r["mat"]:
            sold[r["mat"]] = sold.get(r["mat"], 0) + 1
            hit[r["mat"]] = hit.get(r["mat"], 0) + r["hit"]
    N, H = sum(sold.values()), sum(hit.values())
    p = H / max(N, 1)
    够 = {m: n for m, n in sold.items() if n >= 50}
    显著 = sorted(((hit[m] / n - p) / math.sqrt(max(p * (1 - p), 1e-9) / n), m)
                  for m, n in 够.items())
    偏 = [(z, m) for z, m in 显著 if abs(z) > 2]
    ck("③ 维保率在面料上有显著差异(不是按销量比例撒的)", bool(偏), len(够),
       (f"整体 {p:.1%};偏离超过两倍噪声的 {len(偏)} 种,例:"
        + "、".join(f"{m} {hit[m] / sold[m]:.1%}" for _, m in (偏[:2] + 偏[-2:])))
       if 偏 else f"{len(够)} 种面料全在整体 {p:.1%} 的噪声范围里 —— 排出来的名次什么都没说",
       下限=5)

    # ── ④ 客户汇总和名下订单对得上(夹具除外)──────────────────────────
    #   业务定了按订单重算。口径:算数的单 = 付了款、没取消、没退完款;
    #   单数只数「完成」的(等级表写的是「完成订单 ≥ N 单」)。**独立用 SQL 现算**
    保护 = 受保护客户(c)
    bad4, n4 = [], 0
    for r in c.execute("""
            SELECT k.id, k.order_cnt, k.paid_amount,
              (SELECT COUNT(*) FROM ordr o WHERE o.customer_id=k.id AND o.status='完成'
                 AND o.paid_at IS NOT NULL AND o.refund_status<>'已退款') cnt,
              (SELECT COALESCE(SUM(o.received),0) FROM ordr o WHERE o.customer_id=k.id
                 AND o.paid_at IS NOT NULL AND o.status<>'取消' AND o.refund_status<>'已退款') amt
            FROM customer k"""):
        if r["id"] in 保护:
            continue
        n4 += 1
        if r["order_cnt"] != r["cnt"] or abs((r["paid_amount"] or 0) - r["amt"]) > 0.01:
            bad4.append(f"{r['id']}(存 {r['order_cnt']} 单/¥{r['paid_amount']},"
                        f"订单算出 {r['cnt']} 单/¥{r['amt']:.2f})")
    ck("④ 客户的单数和实付和名下订单对得上(手工摆的夹具除外)", not bad4, n4,
       f"对不上 {len(bad4)} 个:{bad4[:3]}" if bad4 else
       f"跳过 {len(保护)} 个夹具(E- 前缀 / truth 点名 / 评测写死)", 下限=500)

    # ── ⑤ 数量不是整数 ──────────────────────────────────────────────
    #   用户原话:「数量别是 5000、100 这种,我希望数量能有随机性,这样看起来真实」
    n_c = c.execute("SELECT COUNT(*) FROM customer").fetchone()[0]
    整 = [f"{k} {v}" for k, v in (("客户", n_c), ("订单", n_all), ("定制品", n_cus),
                                 ("标品", n_std)) if v % 100 == 0]
    ck("⑤ 客户数和订单数不是整百(看起来像真的,不像摆的)", not 整, 4,
       f"整百的:{整}" if 整 else f"客户 {n_c} · 订单 {n_all} · 定制 {n_cus} · 标品 {n_std}")
    # ── ⑥ 车间工单和订单状态对得上 ─────────────────────────────────
    #   在制的工单,订单得在「生产中」;做完了的工单,订单不能还没开工或已经取消。
    #   种子里原来 18 张在制工单挂在**已完成**的订单上、还有工单挂在**没付款**的订单上
    #   —— 订单做完了工单还在做,钱都没付就开工了。期望集合照「两套状态」手抄。
    错6 = [f"{r['id']}({r['status']}→订单{r['ost']})" for r in c.execute(
        """SELECT w.id, w.status, o.status ost FROM workorder w JOIN ordr o ON o.id=w.ref""")
        if (r["status"] == "在制" and r["ost"] != "生产中")
        or (r["status"] == "已完成" and r["ost"] in ("待付款", "待审核", "待生产", "取消"))]
    n6 = c.execute("SELECT COUNT(*) FROM workorder").fetchone()[0]
    ck("⑥ 车间工单和它挂的订单状态对得上", not 错6, n6,
       f"对不上 {len(错6)} 张:{错6[:4]}" if 错6 else
       "在制 → 订单在生产中;已完成 → 订单已经过了生产", 下限=20)
    c.close()

    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print(f"✅ 数据集形状 {len(DONE)} 条全过")
    return 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
咬合 = [
    ('给一张没有退货单的标品订单标上「已退款」', '① 订单的退款状态和售后单对得上'),
    ('把换货单整批删掉(换货率掉到 0)', '② 占比在拍板的区间里'),
    ('把所有定制单的面料都改成同一种(差异被抹平)', '③ 维保率在面料上有显著差异'),
    ('给一个普通客户的完成单数 +1', '④ 客户的单数和实付和名下订单对得上'),
    ('删掉几个客户让客户数正好整百', '⑤ 客户数和订单数不是整百'),
    ('把一张在制工单挂回一张已完成的订单', '⑥ 车间工单和它挂的订单状态对得上'),
]

if __name__ == "__main__":
    sys.exit(main())
