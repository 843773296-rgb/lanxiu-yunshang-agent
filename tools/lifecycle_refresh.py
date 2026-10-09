#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把客户汇总(含生命周期档位)按**世界的今天**重算一遍。

    python3 tools/lifecycle_refresh.py          # 只看会改多少,不写
    python3 tools/lifecycle_refresh.py --做     # 真写(order_mix 的台账会记原值,可回滚)

## 为什么需要一个单独的入口

`customer.lifecycle` 是**存量字段** —— 页面和模型报「多少人休眠」读的就是它。
而算它要的事实(最近互动 / 闲置天数 / 12 个月单数金额)**每天都在变**,
所以它每天都要重算一次。2026-10-09 用户在页面上撞到的就是这件事:
库里存着 1395 个休眠,而按当天重算只有 871。

⚠️⚠️ **不能直接调 `order_mix.重算(c, 排除, log)`** —— 它的 `基准` 默认是
**建库基准日 2026-08-31**(order_mix 建世界时用的那一天),比世界的今天差 39 天。

> 一个「按今天重算过了」和一个「按建库那天重算过了」,
> **在「重算了 N 个」这句话上长得一模一样。**

所以这里显式传 `backend/worldclock.今天()`。判定口径和算法**一份都不另写**:
事实走 `order_mix.某天的事实`,档位走 `knowledge/lifecycle.decide`。

## 跳过谁

`order_mix.受保护客户()` 扫出来的那些(E- 边界夹具 + `truth` 点名的客户)。
它**现从 truth 表扫**,不读任何手抄名单 ——
手抄那份不会跟着真值表长,而那时重算会**静默抹掉**新加的反例。

## 怎么回滚

`order_mix.重算` 每改一行都往 `order_mix_batch` 台账里记一条原值
(`what='重算:customer'`),照着它写回去就能复原。本脚本不另存一份。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]

import order_mix as OM          # noqa: E402  (它自己会把 backend/knowledge 挂上 sys.path)
import worldclock as W          # noqa: E402

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def 对齐历史(c, 今):
    """重算改了档位,就要往 `lifecycle_history` 落一条今天的,否则**历史和现状对不上**。

    ⚠️⚠️ 2026-10-09 这一步是**补上来的,而且是被一次崩溃逼出来的**:
    第一版 `lifecycle_refresh` 只改 `customer`,不碰历史。重算完 3492 行之后,
    **2732 个客户的「历史最后一条」≠「现在的档位」**。
    而 `backend/slipping_check.py` 正好有一条判据盯这件事 —— 它当场崩了
    (它那一行 `r["customer_id"]` 从写下那天起就没跑过:查询以前返回 0 行,
     错的下标永远不会被求值)。
    > 一条「历史和现状一致」的不变量,和一条「这个查询从来没返回过行」的,
    > **在那条判据一直是绿的这件事上长得一模一样。**

    所以这里只给**对不上的那些人**补今天这一条(现在 2732 条,以后每天趋近 0):
      · `source='recalc'` —— 和回算出来的合成历史(`synth`)分得开,看得出是谁写的
      · 同一天同一人只留一条(先删再插;表上**没有**唯一约束,靠这里保证)
      · 事实列直接取 `customer` 那一行 —— 重算之后它和档位是自洽的,
        **不在这里第二次算**(算两遍就会有两份口径)
    """
    不符 = [r[0] for r in c.execute(
        """SELECT h.customer_id FROM lifecycle_history h
             JOIN customer cu ON cu.id = h.customer_id
            WHERE h.as_of = (SELECT max(as_of) FROM lifecycle_history
                              WHERE customer_id = h.customer_id)
              AND h.lifecycle <> cu.lifecycle""")]
    print(f"  历史最后一条 ≠ 现在的档位:{len(不符)} 个 —— 给它们补一条今天的")
    日 = 今.isoformat()
    for cid in 不符:
        k = c.execute("SELECT lifecycle, idle_days, orders_12m, amount_12m, quarters_12m"
                      " FROM customer WHERE id=?", (cid,)).fetchone()
        c.execute("DELETE FROM lifecycle_history WHERE customer_id=? AND as_of=?", (cid, 日))
        c.execute("""INSERT INTO lifecycle_history(customer_id, as_of, lifecycle, idle_days,
                       orders_12m, amount_12m, quarters_12m, source, note, created)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (cid, 日, k[0], k[1], k[2], k[3], k[4], "recalc", "每日重算", 日))
    # 当场复查:不变量真的立起来了吗
    剩 = c.execute(
        """SELECT count(*) FROM lifecycle_history h JOIN customer cu ON cu.id = h.customer_id
            WHERE h.as_of = (SELECT max(as_of) FROM lifecycle_history
                              WHERE customer_id = h.customer_id)
              AND h.lifecycle <> cu.lifecycle""").fetchone()[0]
    print(f"  {'✅' if not 剩 else '❌'} 复查:还对不上的 {剩} 个")
    return 剩


def main():
    真做 = "--做" in sys.argv
    今 = W.今天()
    c = OM.conn()
    c.row_factory = __import__("sqlite3").Row
    护 = OM.受保护客户(c)
    # ⚠️ **样本量判据**:扫不到夹具时「全都重算了」也成立,
    # 而那一轮会把反例一起抹平 —— 而且抹平之后评测照样绿。
    if len(护) < 14:
        print(f"{R}❌{D} 受保护客户只扫出 {len(护)} 个 —— **扫挂了,不是「没有夹具」**,不重算")
        return 1
    print(f"按世界的今天重算:{今}(受保护 {len(护)} 个跳过)")

    if not 真做:
        # 只看:数一下有多少行会变,不写库
        改 = 0
        for k in [dict(r) for r in c.execute("SELECT * FROM customer")]:
            if k["id"] in 护:
                continue
            new, row = OM.某天的事实(c, k, 今)
            import lifecycle as LC, member as MB
            C = [dict(r) for r in c.execute(
                "SELECT code,name,amount,orders,sort FROM level_cfg WHERE status='启用'")]
            d = LC.decide(row)
            new.update(lifecycle=d["生命周期"], matched="/".join(d["命中"]),
                       level=MB.判档(new["amount_12m"], new["orders_12m"], C))
            if {kk: k[kk] for kk in new} != new:
                改 += 1
        print(f"  会改 {改} 行。{Y}只看不做{D} —— 真写加 --做")
        return 0

    OM._manifest(c)              # 台账表要先在(回滚靠它)
    OM.重算(c, set(护), print, 基准=今)
    c.commit()
    对齐历史(c, 今)
    c.commit()
    print(f"  {G}✅{D} 写完。回滚:order_mix_batch 里 what='重算:customer' 存着每一行的原值")
    print(f"  下一步:python3 backend/lifecycle_sync_check.py(A/B/C 三类都该是 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
