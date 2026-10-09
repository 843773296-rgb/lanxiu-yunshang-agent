#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把落在 E- 边界夹具上的那条「量体→下单→归因」链删掉(2026-10-09 一次性修复,可回滚)。

## 为什么要删

`E-*` 是手工摆在门槛上的反例:「互动第 90 天 / 第 91 天」「实付 14999 / 15000」。
它们的闲置天数是**直接写进列里**的,靠的是「名下 0 单」这个约定(`seed.py` 明写)。

2026-10-09 发现 5 张「待确认」单落在 5 个夹具上。口径是「**下了单就算互动**,
待确认 / 没付款 / 后来取消的都算」(用户 2026-10-09 拍)—— 所以**算法没错**,
错在**订单表没护住**:`customer` 行护住了,而夹具是从另一张表被打穿的。
一张 10-07 的待确认单,把「互动第 91 天」那个夹具的最近互动拉到了 2 天前。

> 夹具坏了的时候,评测照样是绿的 —— 那是它最贵的地方。

## 删什么、不删什么(每一条都有理由)

**删**(都是那一次脚本带进来的):
  · `ordr` 那 5 张单
  · `ordr_item` 挂在它们下面的 6 行
  · `deal_credit` 挂在它们上面的分成记录(影响力归因)
  · `measure_rec` 里 `order_item_id` 指向那 6 行的量体记录

**不删**,各有原因:
  · `op_log` —— 它是**唯一能回答「是谁干的」的证据**。
    删掉它等于把线索一起删了,而造这 5 张单的那个脚本**还没找到**。
    (op_log 显示 5 张单在同一秒被开出来、三个不同顾问 → 是脚本,不是人点的;
     而它的 `ts` 是 `2026-11-09`,比世界今天晚整整一个月 —— 另一个待查的坑。)
  · `wearer` 那 5 行着装人 —— 它们**不是这次带进来的**:
    名字是从夹具客户名的第一个字拼的(「互动第 91 天…」→「互女士」),
    而夹具**原有的 18 行种子量体记录**也指着它们。删了会把种子数据一起打断。
  · 每个夹具原有的 **18 行量体记录**(id 197–341,日期 6–9 月各一天)——
    种子造的,不是污染。只有 id 157515–157529 那 15 行是。
    ⚠️ **「高号 id」不是判据,`order_item_id` 才是** —— 判据要贴着
    「它是不是挂在这次要删的订单上」,不是贴着「它看起来比较新」。

## 回滚

库先备份到 `.fakedata/lanxiu.db.bak-夹具修复-*`;删掉的每一行**原样**写进
`.fakedata/夹具修复-删掉的行-*.json`(表名 → 行列表),照着 insert 回去就能复原。
"""
import datetime as dt
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "backend", "lanxiu.db")
存档目录 = os.path.join(ROOT, ".fakedata")

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

夹具订单 = ("6488012800001526555", "6488012800001526556", "6488012800001526557",
            "6488012800001526558", "6488012800001526559")


def 要删的(c):
    """按**关联关系**找,不按 id 大小找。返回 {表: [整行 dict]}。"""
    q = ",".join("?" * len(夹具订单))
    单 = [dict(r) for r in c.execute(
        f"SELECT * FROM ordr WHERE id IN ({q})", 夹具订单)]
    行ids = [r[0] for r in c.execute(
        f"SELECT id FROM ordr_item WHERE order_id IN ({q})", 夹具订单)]
    qi = ",".join("?" * len(行ids)) if 行ids else "NULL"
    行 = [dict(r) for r in c.execute(
        f"SELECT * FROM ordr_item WHERE id IN ({qi})", 行ids)] if 行ids else []
    分成 = [dict(r) for r in c.execute(
        f"SELECT * FROM deal_credit WHERE order_id IN ({q})", 夹具订单)]
    量 = [dict(r) for r in c.execute(
        f"SELECT * FROM measure_rec WHERE order_item_id IN ({qi})", 行ids)] if 行ids else []
    return {"ordr": 单, "ordr_item": 行, "deal_credit": 分成, "measure_rec": 量}


def main():
    真做 = "--做" in sys.argv
    if not os.path.exists(DB):
        print(f"{R}❌{D} 没有库 {DB}")
        return 1
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    包 = 要删的(c)

    print("要删的行(按关联关系找出来的):")
    for 表, 行 in 包.items():
        print(f"  {表}: {len(行)} 行")
    # ⚠️ **样本量判据**:一行都没有时,这个脚本「成功」了,
    # 而「已经修过了」和「我根本没找到」在那句成功上长得一模一样。
    总 = sum(len(v) for v in 包.values())
    if 总 == 0:
        print(f"  {Y}·{D} 一行都没找到 —— 要么已经修过了,要么这几个单号不对。**没有动库。**")
        return 0
    # 删之前先确认:这几张单真的都在 E- 夹具名下(别删到普通客户的单)
    谁 = sorted({r["customer_id"] for r in 包["ordr"]})
    if any(not x.startswith("E-") for x in 谁):
        print(f"  {R}❌{D} 这些单不全在 E- 夹具名下:{谁} —— **不删**,先查清楚")
        return 1
    print(f"  客户都是 E- 夹具:{谁}")

    if not 真做:
        print(f"\n{Y}只看不做{D}。真删加 --做(会先存一份可回滚的 json)")
        return 0

    os.makedirs(存档目录, exist_ok=True)
    戳 = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    存 = os.path.join(存档目录, f"夹具修复-删掉的行-{戳}.json")
    with open(存, "w", encoding="utf-8") as f:
        json.dump(包, f, ensure_ascii=False, indent=1, default=str)
    print(f"\n删掉的行原样存到:{存}")

    q = ",".join("?" * len(夹具订单))
    行ids = [r["id"] for r in 包["ordr_item"]]
    qi = ",".join("?" * len(行ids)) if 行ids else "NULL"
    # 顺序:先删引用方,再删被引用方
    n4 = c.execute(f"DELETE FROM measure_rec WHERE order_item_id IN ({qi})", 行ids).rowcount
    n3 = c.execute(f"DELETE FROM deal_credit WHERE order_id IN ({q})", 夹具订单).rowcount
    n2 = c.execute(f"DELETE FROM ordr_item WHERE id IN ({qi})", 行ids).rowcount
    n1 = c.execute(f"DELETE FROM ordr WHERE id IN ({q})", 夹具订单).rowcount
    c.commit()
    print(f"删了:measure_rec {n4} · deal_credit {n3} · ordr_item {n2} · ordr {n1}")

    # 删完**当场复查**:还剩一行就说明判据没覆盖全
    剩 = 要删的(c)
    if sum(len(v) for v in 剩.values()):
        print(f"  {R}❌{D} 删完还剩:{ {k: len(v) for k, v in 剩.items()} }")
        return 1
    print(f"  {G}✅{D} 复查:一行不剩")
    print(f"\n{Y}下一步{D}:跑 python3 backend/fixture_intact_check.py 看①那一条有没有转绿。"
          f"\n       op_log 没动 —— 造这 5 张单的脚本还没找到,线索不能删。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
