#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试夹具:为了让某些分支**能被触发**而刻意造的数据。

## 为什么要单独一个脚本

检查里有些分支,在正常数据上**永远不会走到**:
「归属工号查无此人」「顾问跨店」「客户无主」……
它们在逐例测试里是对的,但**库里没有真实样本** ——

> **一条永远不触发的分支,和一条正确的分支,在通过率上长得一模一样。**

所以这里刻意造出来。集中在一个脚本里,是为了**一眼能看出这些是夹具**。

## ⚠️ 这些数据看起来像 bug,而它们是故意的

2026-09-20 真踩过:库里有 3 个客户挂在停用的顾问名下,
我把它当 bug「修」了 —— 门禁当场红「反例夹具丢了」,
因为那正是「离职顾问的单该落池」唯一的样本。

> **「数据看起来有问题」和「数据是故意这样的」长得一模一样。**

所以每条夹具都写明:**造它是为了让哪条检查有东西可测**。
依赖它们的检查要在自己的 `前提` 里声明(`tools/fixture_check.py` 会核)。

## 造新的,不改现有的

改现有客户会连带影响别的检查(它们可能正依赖那条数据的状态)。
新造三个客户,`id` 以 `FX-` 开头 —— **一眼看得出是夹具**。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")
from seed import TODAY
import credit as C

# (客户号, 姓名, advisor_no, 门店, 为了测什么)
客户夹具 = [
    ("FX-NONE-01", "夹具·无主客户", None, "SH001 静安旗舰店",
     "ownership 的 NONE 分支:归属为空 —— 本来就无主,等分配"),
    ("FX-BAD-01", "夹具·坏工号客户", "99999999", "SH001 静安旗舰店",
     "ownership 的 NO_SUCH 分支:档案写了个员工表里没有的工号 —— **数据要修**,不是业务问题"),
    ("FX-XSHOP-01", "夹具·跨店客户", None, "SH001 静安旗舰店",
     "ownership 的 CROSS_SHOP 分支:归属顾问不在客户所在门店 —— 顾问号在下面按实际门店填"),
]


def main():
    c = sqlite3.connect(DB)

    # ── 客户夹具 ─────────────────────────────────────────────
    c.execute("delete from customer where id like 'FX-%'")
    # 跨店那条要一个**真实存在但在别的店**的顾问
    别店顾问 = c.execute("""select no from staff where role='顾问' and status='启用'
                            and shop<>'SH001 静安旗舰店' limit 1""").fetchone()
    for cid, name, adv, shop, _why in 客户夹具:
        if cid == "FX-XSHOP-01":
            if not 别店顾问:
                sys.exit("❌ 没有别的门店的在职顾问 —— 跨店夹具造不出来")
            adv = 别店顾问[0]
        # ⚠️ **等级要按口径现算,不能留空。**
        # `membership_check` 逐例验「每个客户的等级都算得出来」——
        # 留空的话那条会红,而红的理由是「等级对不上」,
        # **看起来像会员逻辑坏了,实际是我的夹具少填了一列**。
        sys.path.insert(0, os.path.join(HERE, ".."))
        import knowledge.member as mb
        档位表 = [dict(zip(("code", "name", "amount", "orders", "sort", "need_points"), r))
                  for r in c.execute("select code,name,amount,orders,sort,need_points "
                                     "from level_cfg where status='启用'")]
        档 = mb.判档(0, 0, 档位表)
        c.execute("""insert into customer(id,name,phone,shop,advisor_no,lifecycle,level,
                                          created,archived,order_cnt,orders_12m,amount_12m,idle_days)
                     values(?,?,?,?,?,?,?,?,0,0,0,0,0)""",
                  (cid, name, "000" + cid[-8:].replace("-", ""), shop, adv, "潜在", 档, TODAY))

    # ── 归因来源夹具 ─────────────────────────────────────────
    # 「人工填」和「算法算」两条路径,规则算的样本覆盖不到
    c.execute("delete from deal_credit where basis like '夹具:%'")
    单 = c.execute("select id from ordr where status='完成' order by id limit 1").fetchone()
    顾问 = c.execute("""select no from staff where role='顾问' and status='启用'
                        order by no limit 2""").fetchall()
    if 单 and len(顾问) >= 2:
        C.记一笔(单[0], 顾问[0][0], C.影响力分成, "成交", 80, "人工填",
                basis="夹具:店长手工调整过的影响力", ts=TODAY, conn=c)
        C.记一笔(单[0], 顾问[1][0], C.影响力分成, "首次接待", 45, "算法算",
                method="W型归因 v1", basis="夹具:算法算出来的,要能和人工填的分开",
                ts=TODAY, conn=c)
    c.commit()

    # ── 自检:每条夹具真的造出了它要造的那个状态 ────────────────
    import ownership as O
    按码 = {}
    for _, _, 码, _ in O.实际无人管理(DB):
        按码[码] = 按码.get(码, 0) + 1
    缺 = [k for k in ("NONE", "NO_SUCH", "CROSS_SHOP", "LEFT") if not 按码.get(k)]
    if 缺:
        sys.exit(f"❌ 这几个分支还是没有样本:{缺} —— 夹具没造出预期的状态")

    来源 = dict(c.execute("select source, count(*) from deal_credit group by source").fetchall())
    缺2 = [k for k in ("人工填", "规则算", "算法算") if k not in 来源]
    if 缺2:
        sys.exit(f"❌ 归因来源还缺样本:{缺2}")

    print(f"  测试夹具:客户 {len(客户夹具)} 个(FX- 开头,**一眼看得出是夹具**)")
    print(f"  实际无人管理四种码都有样本:{按码}")
    print(f"  归因三种来源都有样本:{来源}")
    c.close()


if __name__ == "__main__":
    main()
