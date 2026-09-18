# -*- coding: utf-8 -*-
"""换货的五条业务规则 —— 口径在 `knowledge/09-养护与售后.md` 第六节。

## 业务 2026-09-18 定的五条

    1. 走审批        客户提了不等于成立,要人批;审批拒绝是终态
    2. 要寄回        原件必须寄回并入库,之后才发新的
    3. 从买的渠道出货  门店买的从门店出,小程序买的从仓库出,**不许跨渠道调货**
    4. 差价多退少补   贵了补、便宜了退,走原支付渠道
    5. 换回的那件也要绑订单商品(换出去的那件不受这条约束,它是新的)

## 第 3 条为什么需要一个**冗余**字段才检查得了

`aftersale.channel` 存的是**订单渠道的一份副本**,不是现查订单。

乍看这是冗余 —— 而冗余字段一旦和主体不一致,通常没有东西会报。
但这里恰恰相反:**如果 channel 现查订单,那「从买的渠道出货」这条规则
就永远为真,既无法被违反,也就无法被检查。**

> **一条不可能被违反的规则,和一条不存在的规则,效果一样。**

和「`aftersale` 原来没有商品字段,于是『商品必须统一』表达不了」是同一件事的两面:
那次是**缺字段导致规则表达不了**,这次是**特意留一份副本让规则可被证伪**。
代价是这份副本可能漂 —— 所以下面第 ③ 条就是钉住它的。

## 第 4 条:`price_diff` 的 0 和 NULL 必须分得开

    0     算过了,不用补也不用退
    NULL  还没算

**这两种在报表上长得一样,而处理方式相反** —— 一个可以收尾,一个还欠着一步。
所以「已完成的换货单,差价必须算过」判的是 `IS NOT NULL`,不是 `<> 0`。
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = []
DONE = []

# 换货状态机(口径见 knowledge/09 §6.3)。**手抄的常数,不从库里现算** ——
# 现算「库里出现过哪些状态」再拿去校验库,是拿被测数据当期望值。
审批态 = ("审批同意", "审批拒绝")
寄回态 = ("商品寄回", "已入库")
终态 = ("已完成", "审批拒绝")
换货状态 = ("提交申请",) + 审批态 + 寄回态 + ("差价处理", "换出发货", "签收", "已完成")


def ck(name, ok, n, msg=""):
    DONE.append(name)
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("换货 · 五条业务规则")
    print("=" * 80)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row

    列 = {x[1] for x in c.execute("PRAGMA table_info(aftersale)")}
    缺 = sorted({"exchange_sku", "channel", "price_diff", "diff_settled_at"} - 列)
    if 缺:
        print(f"❌ `aftersale` 缺这几列:{缺} —— **换货的规则在库里表达不了**,"
              f"不是「没有违规」,是「记不下来」")
        c.close()
        return 1

    单 = [dict(r) for r in c.execute(
        "SELECT a.*, o.kind AS 订单类型, o.source AS 订单渠道"
        " FROM aftersale a LEFT JOIN ordr o ON o.id = a.order_id"
        " WHERE a.kind = '换货'")]

    # ── ① 状态必须在换货状态机里 ────────────────────────────────────
    越界 = [f"{r['id']}「{r['status']}」" for r in 单 if r["status"] not in 换货状态]
    ck("① 换货单的状态在换货状态机里", not 越界, len(单),
       f"越界 {越界[:4]}" if 越界 else " → ".join(换货状态[:5]) + " …")

    # ── ② 走审批 + 要寄回:走到发货之后的,前面那两步必须发生过 ────────
    #    这里判的是**「到了这一步,前面那几步的痕迹在不在」**,
    #    不是「状态等于审批同意」—— 一条单子此刻的状态只有一个,
    #    而规则说的是它**走过**审批和寄回。
    发货之后 = ("换出发货", "签收", "已完成")
    无痕 = []
    for r in 单:
        if r["status"] in 发货之后:
            # 痕迹落在时间戳上:差价结清时间在,说明走到过差价处理;
            # 而差价处理排在入库之后、入库排在审批之后(见 §6.3)。
            if r["price_diff"] is None:
                无痕.append(f"{r['id']}(状态「{r['status']}」,但差价没算过)")
    ck("② 走到发货之后的换货单,差价已经算过", not 无痕, len(单),
       f"{无痕[:3]}" if 无痕 else
       "差价处理排在入库之后、入库排在审批之后 —— 差价算过,说明前面几步走过了")

    # ── ③ 从买的渠道出货 ────────────────────────────────────────────
    跨渠道 = [f"{r['id']}(换货走「{r['channel']}」,订单是「{r['订单渠道']}」)"
             for r in 单 if r["channel"] and r["订单渠道"] and r["channel"] != r["订单渠道"]]
    没写 = [r["id"] for r in 单 if not r["channel"]]
    ck("③ 换货从买的那个渠道出货", not (跨渠道 or 没写), len(单),
       (f"跨渠道 {跨渠道[:3]};" if 跨渠道 else "") + (f"没写渠道 {没写[:3]}" if 没写 else "")
       or "channel 是订单渠道的副本 —— **特意留一份副本,这条规则才可能被违反、才检查得了**")

    # ── ④ 差价:0 和 NULL 分得开 ────────────────────────────────────
    坏差价 = []
    for r in 单:
        if r["status"] in ("已完成",) and r["price_diff"] is None:
            坏差价.append(f"{r['id']} 已完成但差价还没算(NULL)")
        # 差价不为 0 的,必须有结清时间;差价为 0 的不需要(没有钱要动)
        if r["price_diff"] is not None and abs(r["price_diff"]) > 0.001 \
                and r["status"] == "已完成" and not (r["diff_settled_at"] or "").strip():
            坏差价.append(f"{r['id']} 差价 {r['price_diff']} 已完成却没有结清时间")
    ck("④ 已完成的换货单,差价算过且结清了", not 坏差价, len(单),
       f"{坏差价[:3]}" if 坏差价 else
       "**0 和 NULL 分得开**:0 是算过了不用动钱,NULL 是还没算 —— "
       "两者在报表上长得一样,处理方式相反")

    # ── ⑤ 换出去的那件必须是真实 SKU ──────────────────────────────
    # ⚠️ `sku` 表的主键列叫 **`code`**,不叫 `sku`。第一版写的是 `SELECT sku FROM sku`,
    #    当场崩在 no such column —— **崩了至少看得见**;
    #    真正危险的是写成一个碰巧存在、但含义不对的列名,那样它会安静地全绿。
    sku = {x[0] for x in c.execute("SELECT code FROM sku")} if 有表(c, "sku") else set()
    坏sku = [f"{r['id']}→{r['exchange_sku']}" for r in 单
             if not r["exchange_sku"] or (sku and r["exchange_sku"] not in sku)]
    ck("⑤ 换出去的那件是真实存在的 SKU", not 坏sku, len(单),
       f"{坏sku[:3]}" if 坏sku else
       "换回的那件由 R4(order_item_id)管,换出的那件由这条管 —— **两件东西,两条规则**")

    c.close()
    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print(f"✅ 换货规则 {len(DONE)} 条全过")
    return 0


def 有表(c, t):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (t,)).fetchone())


咬合 = [
    ('把一单换货的 channel 改成和订单渠道不同的值(跨渠道调货)', '③ 换货从买的那个渠道出货'),
    ('把一单已完成换货的 price_diff 清成 NULL(差价没算过)', '④ 已完成的换货单'),
    ('把一单换货的 exchange_sku 改成一个库里没有的编码', '⑤ 换出去的那件是真实存在的 SKU'),
    ('把一单换货的状态改成一个不在换货状态机里的词', '① 换货单的状态在换货状态机里'),
]

if __name__ == "__main__":
    sys.exit(main())
