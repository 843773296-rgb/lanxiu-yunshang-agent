#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造「客户档位历史」——  按当时的事实回算 12/9/6/3/0 个月前五个时点。

    python3 tools/lifecycle_history_seed.py          # 只看
    python3 tools/lifecycle_history_seed.py --做     # 真写(先删掉自己那一批再重算)

## 为什么要单独成一步

`lifecycle_history` 是**流失预警**的训练样本(「档位怎么随事实变化」)。
它原来只由 `fakedata/mkt_sop_seed.py` 顺带造 —— 而那个脚本**不在
`tools/rebuild.sh` 的配方里**(2026-10-09 并行会话 grep 核过)。后果:

> **CI 的库里这张表永远是空的,依赖它的判据在 CI 上一个字都没验,
> 而绿勾看起来完全正常。**
> 一个「这个功能的取数都对」的绿勾,和一个「CI 上这个功能的数据根本不存在」的,
> **长得一模一样。**

而 `mkt_sop_seed` **没法直接进配方**:它不幂等(重跑撞 `appointment.id`
唯一约束)。所以把「回算历史」这一段抽出来独立成步,并且**做成幂等的**。

## 口径:一份都不另写

  · 事实(最近互动 / 闲置 / 12 个月单数金额)→ `tools/order_mix.某天的事实`
  · 档位判定 → `knowledge/lifecycle.decide`
  · 受保护客户 → `tools/order_mix.受保护客户`(现从 truth 表扫)
今天一整天都在修「同一套口径被手抄成两份」的后果,**这里不开第三份**。

## 两条刻意的设计

**① 客户建档之前的时点,一条都不写。**
`某天的事实` 在建档前查不到任何互动 → `idle_days=9999` → 判成「流失」。
那不是口径问题,是**事实错误**:客户那时候还不存在。
代价在下游:「建档前流失 → 建档后活跃」会被流失预警当成
**「流失后又回来」的正例**,直接污染标签。
2026-10-09 实测:库里 29020 条里有 **9342 条(32%)** 是这种,而且**全部**是「流失」。
> 一条「这个人流失过又回来了」的历史,和一条「这个人那时候还没建档」的,
> **在那张表上长得一模一样** —— 字段齐、档位列有值,只有日期泄露了它。

**② 幂等是「先删自己那批再重算」,不是「有了就跳过」。**
它独占 `source='synth'`。跳过的话,改完代码再跑一次拿不到新结果,
而**「跳过了」和「跑过了」在输出上长得一模一样**。

## 它不做什么

**不写 `customer.lifecycle`** —— 那是 `tools/lifecycle_refresh.py` 的事,
而它在配方里排在本脚本之后。两件事混在一个脚本里,
坏了的时候分不清是「历史算错」还是「现状没刷」。
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
                os.path.join(ROOT, "fakedata")]

import lifecycle as LC        # noqa: E402  档位判定只有这一份
import order_mix as OM        # noqa: E402  事实 + 受保护客户
import worldclock as W        # noqa: E402

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
DB = os.path.join(ROOT, "backend", "lanxiu.db")
for _i, _a in enumerate(sys.argv):
    if _a == "--db" and _i + 1 < len(sys.argv):
        DB = sys.argv[_i + 1]

时点 = (12, 9, 6, 3, 0)          # 个月前。和 mkt_sop_seed 原来那套一致
来源 = "synth"                   # 本脚本独占这个来源值(幂等靠它)


def _建表(c):
    c.execute("""CREATE TABLE IF NOT EXISTS lifecycle_history(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   customer_id TEXT NOT NULL, as_of TEXT NOT NULL,
                   lifecycle TEXT NOT NULL, idle_days INT, orders_12m INT,
                   amount_12m REAL, quarters_12m INT, source TEXT NOT NULL,
                   note TEXT, created TEXT NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_lchist_cust "
              "ON lifecycle_history(customer_id, as_of)")


def 要算的客户(c, 护):
    """**有过订单**的客户,排掉受保护的。

    为什么是「有过订单」:这张表要学的是「档位怎么随**下单和互动**变化」。
    一个一单都没有的客户,五个时点算出来是同一个档,那一行对训练毫无信息,
    只是把表撑大。
    """
    return [r[0] for r in c.execute(
        "SELECT DISTINCT customer_id FROM ordr ORDER BY customer_id")
        if r[0] not in 护]


def 跑(c, 今, 真写, 说=print):
    护 = OM.受保护客户(c)
    # ⚠️ **「不要碰他」要说清是哪一种不要碰。**
    # 覆盖样本(`tools/seed_churned.py` 造的那批)在名单里,是为了不让 `daily_fresh`
    # 给他们造新单 —— **但他们有真实订单,必须有档位历史才能判码**。
    # 跟着夹具一起排掉,那几支码会立刻回到 0:它们保护的东西正是被它们弄没的。
    护 = OM.去掉覆盖样本(c, 护)
    # ⚠️ **样本量判据**:扫不到夹具时「都排除了」也成立,而那一轮会把反例一起算进去。
    if len(护) < 14:
        说(f"{R}❌{D} 受保护客户只扫出 {len(护)} 个 —— **扫挂了,不是「没有夹具」**,不算")
        return None
    客 = 要算的客户(c, set(护))
    if len(客) < 100:
        说(f"{R}❌{D} 只有 {len(客)} 个客户要算 —— **这不叫「没什么可算」,叫取数取空了**")
        return None
    说(f"世界的今天 {今} · 要算 {len(客)} 个客户 × 最多 {len(时点)} 个时点"
       f"(受保护 {len(护)} 个不算)")

    旧 = c.execute("SELECT count(*) FROM lifecycle_history WHERE source=?", (来源,)).fetchone()[0]
    if not 真写:
        说(f"  库里现有 {旧} 条 `{来源}` 历史 —— 真跑会**先删掉它们再重算**(同一套口径,确定性)")
        说(f"{Y}只看不做{D}。真写加 --做")
        return {"现有": 旧}

    c.execute("DELETE FROM lifecycle_history WHERE source=?", (来源,))
    说(f"  删掉旧的 {旧} 条(幂等:先删自己那批再重算,不是「有了就跳过」)")
    计 = {"写了": 0, "跳过·建档前": 0, "跳过·那时还没互动过": 0}
    批 = []
    for cid in 客:
        行 = c.execute("SELECT * FROM customer WHERE id=?", (cid,)).fetchone()
        if 行 is None:
            continue
        行 = dict(行)
        建档 = str(行.get("created") or "")[:10]
        for 月前 in 时点:
            基 = 今 - dt.timedelta(days=30 * 月前)
            日 = 基.isoformat()
            # ① 客户建档之前的时点,一条都不写(见模块头)
            if 建档 and 日 < 建档:
                计["跳过·建档前"] += 1
                continue
            写回, 事实 = OM.某天的事实(c, 行, 基)
            # ② **那时候一次互动都还没有的时点,也一条都不写。**
            #
            # `idle_days` 这一列把「距上次互动多久」和「**从没互动过**」压成了同一个数
            # (后者是 9999),而 `decide` 的规则表达不了后者:
            # 「流失 = 无互动超过 365 天」,于是 9999 必然命中流失、而且它优先级最高。
            # 实测:第一版造出来的 4422 条「流失」里,**4422 条全是 idle=9999** ——
            # 一条真的流失过的都没有。
            # 举例 C10002:建档 2025-10-11、首单 2026-09-20,中间四个时点全被标成
            # 「流失」,最后一个时点变成「新客」。
            #
            # > 一条「他那时候真的流失了」和一条「他那时候刚建档、还没互动过」,
            # > **在 `流失` 这个档位上长得一模一样** ——
            # > 而流失预警会把「流失 → 新客」学成**「流失后又回来」**。
            #
            # 这和上面 ① 是同一个病,只是更隐蔽一层。
            # **不在这里另造一套判定**(比如硬写成「潜在」)—— 那就是「口径手抄第二份」,
            # 今天修了一整天。档位历史从这个客户**第一次互动那天**开始才有意义。
            # 判据贴着结构(`last_interact is None`),不贴那个 9999 魔数。
            # ⚠️ 这个洞在口径层:要不要给「建档了但从没互动过」一个档位,是业务的事,
            #    已经报上去了。
            if 写回["last_interact"] is None:
                计["跳过·那时还没互动过"] += 1
                continue
            # ⚠️ 键是「生命周期」(中文)。`.get("lifecycle")` 取不到会**静静返回 None**,
            # 而 mkt_sop_seed 为这个栽过:23216 条历史的档位列全是字符串 "None",
            # 连「抽查重跑一致」都过了 —— **用同一个错读法去验,永远验不出这个错**。
            # 所以这里不兜底:键不在就当场炸。
            批.append((cid, 日, 事实["idle_days"] if 事实["idle_days"] is not None else 9999,
                       事实["orders_12m"], 事实["amount_12m"], 事实["quarters_12m"],
                       LC.decide(事实)["生命周期"], 来源,
                       f"回算({月前} 个月前)", 今.isoformat()))
            计["写了"] += 1
        if len(批) >= 5000:
            c.executemany("""INSERT INTO lifecycle_history(customer_id,as_of,idle_days,
                               orders_12m,amount_12m,quarters_12m,lifecycle,source,note,created)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""", 批)
            批 = []
    if 批:
        c.executemany("""INSERT INTO lifecycle_history(customer_id,as_of,idle_days,
                           orders_12m,amount_12m,quarters_12m,lifecycle,source,note,created)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""", 批)
    return 计


def 复查(c, 今, 说=print):
    """写完当场自己核三样 —— **「写进去了」和「写对了」是两件事。**"""
    坏 = 0
    建档前 = c.execute(
        """SELECT count(*) FROM lifecycle_history h JOIN customer cu ON cu.id=h.customer_id
            WHERE h.source=? AND cu.created IS NOT NULL
              AND h.as_of < substr(cu.created,1,10)""", (来源,)).fetchone()[0]
    print(f"  {'✅' if not 建档前 else '❌'} 建档之前的行:{建档前} 条(应为 0)")
    坏 += bool(建档前)
    重 = c.execute(f"""SELECT count(*) FROM (SELECT customer_id, as_of FROM lifecycle_history
                        WHERE source='{来源}' GROUP BY 1,2 HAVING count(*)>1)""").fetchone()[0]
    print(f"  {'✅' if not 重 else '❌'} 同一个人同一天写了多条:{重} 处(应为 0)")
    坏 += bool(重)
    空 = c.execute("SELECT count(*) FROM lifecycle_history WHERE source=? AND "
                   "(lifecycle IS NULL OR lifecycle='' OR lifecycle='None')",
                   (来源,)).fetchone()[0]
    # ⚠️ 这条专抓 mkt_sop_seed 栽过的那个坑:档位列全是字符串 "None"
    print(f"  {'✅' if not 空 else '❌'} 档位列是空或字符串 \"None\" 的:{空} 条(应为 0)")
    坏 += bool(空)
    n = c.execute("SELECT count(*) FROM lifecycle_history WHERE source=?", (来源,)).fetchone()[0]
    人 = c.execute("SELECT count(DISTINCT customer_id) FROM lifecycle_history WHERE source=?",
                   (来源,)).fetchone()[0]
    档 = dict(c.execute("SELECT lifecycle, count(*) FROM lifecycle_history "
                        "WHERE source=? GROUP BY 1 ORDER BY 2 DESC", (来源,)).fetchall())
    print(f"  共 {n} 条 / {人} 个客户 · 档位分布 {档}")
    # ⚠️ **档位必须有变化**,否则这份历史对流失预警毫无用处 ——
    # 而「回算了五个时点」和「五个时点都一样」在条数上长得一模一样
    # (mkt_sop_seed 原注释:实测 5804 个客户里 0% 变过,因为「末」算在循环外面)。
    变过 = c.execute(f"""SELECT count(*) FROM (SELECT customer_id FROM lifecycle_history
                          WHERE source='{来源}' GROUP BY 1
                          HAVING count(DISTINCT lifecycle)>1)""").fetchone()[0]
    比 = 100.0 * 变过 / max(1, 人)
    行了 = 比 >= 10
    print(f"  {'✅' if 行了 else '❌'} 档位在时点之间**变过**的客户:{变过} 个({比:.0f}%,要 ≥10%)")
    print(f"      ← 一份「回算了五个时点」的历史和一份「五个时点都一样」的,"
          f"**在条数上长得一模一样**,而后者对流失预警毫无用处")
    坏 += (not 行了)
    return 坏


def main():
    ap = argparse.ArgumentParser(description="造客户档位历史(幂等)")
    ap.add_argument("--做", action="store_true", dest="做")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    if not os.path.exists(DB):
        print(f"{R}❌{D} 没有库 {DB}")
        return 1
    今 = W.今天()
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    _建表(c)
    计 = 跑(c, 今, a.做)
    if 计 is None:
        c.rollback()
        return 1
    if not a.做:
        return 0
    c.commit()
    print(f"  写了 {计['写了']} 条 · 跳过:建档之前 {计['跳过·建档前']} 个 · "
          f"那时还没互动过 {计['跳过·那时还没互动过']} 个")
    坏 = 复查(c, 今)
    if 坏:
        print(f"{R}❌ 复查 {坏} 处不对{D}")
        return 1
    print(f"{G}✅ 档位历史造好了{D}")
    print(f"{Y}下一步{D}:tools/lifecycle_refresh.py --做(本脚本不写 customer.lifecycle)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
