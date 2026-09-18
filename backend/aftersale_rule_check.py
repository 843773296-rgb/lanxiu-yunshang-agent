# -*- coding: utf-8 -*-
"""售后与维保的四条业务硬规则 —— **库允许的,不等于业务允许的。**

## 规则是业务 2026-09-18 定的

    R1  定制品**没有**退货、换货;标品有
    R2  标品和定制品**都有**维保
    R3  退货 / 换货 / 维保**都绑定订单**
    R4  售后 / 维保的商品**必须是该订单里的商品**
        ——「不能订单是条裙子,然后拿个裤子去维保」

## 为什么这四条非得有程序守着

写下这四条的时候,库里**三条是破的**:

    R1  定制品订单挂着 8 单「退货退款」
    R2  维保 21 单全是定制品,标品一单没有
    R4  `aftersale` 表**一个商品字段都没有** —— 这条规则在库里根本表达不了

而且没有任何东西会报。**R3 当时是干净的(0 违规),但那是碰巧干净**:
`maintain.item` 21 条全对得上订单,靠的是造数据时顺手写对了,
不是有什么拦着它写错。**一条从没被攻击过的规则,和一条不存在的规则没有区别。**

## R4 判的是「指得回去」,不是「名字长得像」

第一版是**按商品名**比对的 —— 维保 21/21 全过。
但那只证明**名字抄对了**:名字一改,历史引用当场断掉(和方案存形制名那次是同一个病);
同名不同 SKU 时也匹配得上,而那实际是两件东西。

2026-09-18 两张表都加了 `order_item_id`,判据跟着改成
**「这一行属不属于这张单挂的那张订单」** —— 从此判的是指针,不是字符串。

⚠️ 这中间有一小段时间,检查是绿的而规则并没有被真正守住 ——
**「验过了」和「用一把量不出这件事的尺子验过了」在输出上长得一模一样。**
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = []
DONE = []

# 定制品订单**不该**出现的售后类型。**用集合不用单个值** ——
# 「换货」现在库里还没有这个类型,但业务说标品有;等它出现时这条不必改。
定制品禁止的售后 = {"退货退款", "换货", "退货换货"}


def ck(name, ok, n, msg=""):
    DONE.append(name)
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        # **空集合上所有性质都成立。** 这个项目为这件事栽过:
        # 客户表一空,RFM 五条性质全绿,而那叫「什么都没验」。
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("售后与维保 · 业务硬规则检查")
    print("=" * 80)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row

    售后 = [dict(r) for r in c.execute(
        "SELECT a.id, a.kind, a.status, a.order_id, a.order_item_id, o.kind AS 订单类型"
        " FROM aftersale a LEFT JOIN ordr o ON o.id = a.order_id")]
    维保 = [dict(r) for r in c.execute(
        "SELECT m.id, m.item, m.order_id, m.order_item_id, o.kind AS 订单类型"
        " FROM maintain m LEFT JOIN ordr o ON o.id = m.order_id")]

    # ── R1 定制品没有退货、换货 ────────────────────────────────────
    犯 = [f"{r['id']}({r['kind']}·{r['status']})" for r in 售后
          if r["订单类型"] == "定制品订单" and r["kind"] in 定制品禁止的售后]
    ck("R1 定制品订单不出现退货/换货类售后", not 犯, len(售后),
       f"违规 {len(犯)} 单:{犯[:4]}" if 犯 else
       "定制品是按人做的,退回来卖不掉 —— 它的出口是维保或退款,不是退货")

    # ── R2 两类订单都有维保 ────────────────────────────────────────
    有维保的类型 = {r["订单类型"] for r in 维保 if r["订单类型"]}
    订单类型 = {r[0] for r in c.execute("SELECT DISTINCT kind FROM ordr")}
    缺 = sorted(订单类型 - 有维保的类型)
    ck("R2 每一类订单都有维保单", not 缺, len(维保),
       f"这些类型一单维保都没有:{缺} —— **一个从没被用过的出口,和不存在是一回事**"
       if 缺 else f"覆盖 {sorted(有维保的类型)}")

    # ── R3 售后与维保都绑定订单 ────────────────────────────────────
    孤售后 = [r["id"] for r in 售后 if not r["订单类型"]]
    孤维保 = [r["id"] for r in 维保 if not r["订单类型"]]
    ck("R3 售后与维保都挂得到订单", not (孤售后 or 孤维保), len(售后) + len(维保),
       f"挂不上的 售后{孤售后[:3]} 维保{孤维保[:3]}" if (孤售后 or 孤维保) else
       "order_id 指得到一张真实存在的订单")

    # ── R4 商品必须是该订单里的商品 ────────────────────────────────
    #    「订单是条裙子,拿个裤子去维保」—— 业务原话。
    #
    #    **按 `order_item_id` 比对,不按商品名。** 第一版是按名字比的,
    #    21/21 全过 —— 但那只证明名字抄对了。名字一改历史引用当场断掉,
    #    同名不同 SKU 也判不出。2026-09-18 两张表都加了 `order_item_id`,
    #    判据跟着改成「这一行属不属于这张单的订单」。
    行归属 = {r["id"]: r["order_id"]
             for r in c.execute("SELECT id, order_id FROM ordr_item")}

    def 查商品一致(单据, 表名, 规则名):
        错 = []
        for r in 单据:
            k = r.get("order_item_id")
            if k is None:
                错.append(f"{r['id']} 没写是这张订单里的哪一件")
                continue
            属于 = 行归属.get(k)
            if 属于 is None:
                错.append(f"{r['id']} 指向的订单行 {k} 不存在")
            elif 属于 != r["order_id"]:
                错.append(f"{r['id']} 挂在订单 {r['order_id']},"
                         f"却指向订单 {属于} 的商品 —— **裙子的单,拿裤子来了**")
        ck(规则名, not 错, len(单据),
           f"对不上的 {错[:3]}" if 错 else
           f"按 `{表名}.order_item_id` 比对 —— 判的是**指得回去**,不是名字长得像")
        return 错

    查商品一致(维保, "maintain", "R4a 维保的商品是该订单里的商品")
    查商品一致(售后, "aftersale", "R4b 售后的商品是该订单里的商品")

    c.close()
    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print(f"✅ 售后与维保硬规则 {len(DONE)} 条全过")
    return 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。可重放的规格在 tools/bite_specs.json。
# **每条的预期红互不相同** —— 都写「售后规则」的话,任一条红了全部规格都算通过,
# 那样咬合测不出是哪条规则在起作用。
咬合 = [
    ('把一单定制品订单的售后类型改成「退货退款」', 'R1 定制品订单不出现退货/换货类售后'),
    ('把标品那几单维保全删掉(只剩定制品有维保)', 'R2 每一类订单都有维保单'),
    ('把一单维保的 order_id 改成一个不存在的订单号', 'R3 售后与维保都挂得到订单'),
    ('把一单维保的 order_item_id 指到**另一张订单**的商品行(订单是裙子,维保写裤子)',
     'R4a 维保的商品是该订单里的商品'),
    ('把一单售后的 order_item_id 清空(没写退的是哪一件)',
     'R4b 售后的商品是该订单里的商品'),
]

if __name__ == "__main__":
    sys.exit(main())
