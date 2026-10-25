#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订单上冗余一列「这个客户现在归谁」—— 加列 + 建触发器 + 回填。

## 为什么要这一列

`api._订单范围()` 给顾问那一支的条件是:

    AND (o.advisor_no=? OR cu.advisor_no=?)
        ↑ 这一单是谁做的     ↑ 这个客户现在归谁

这个 `OR` **跨了两张表**,SQLite 只能全表扫 `ordr`(2.6 万行)。
**加索引修不了** —— 2026-10-24 那轮建的 `ix_ordr_adv_cov` / `ix_cust_adv_cov`
对这条查询一点用都没有,因为 OR 的两边在不同的表上。

2026-10-25 在**真库副本**上量了三个方案:

    现有(OR 跨两表)         19–20 ms   `SCAN o`
    拆成 UNION 再去重        16.17 ms   **1.2 倍 —— 否决**
    冗余一列(OR 落同一表)    8.22 ms   **2.3 倍**,`MULTI-INDEX OR` 两个索引取并集

拆 UNION 那个方案**实测没用**:索引省下的扫表时间,被 `UNION USING TEMP B-TREE`
(5172 行去重)和第二支的回表查找吃掉了大半。和这个项目记过的另一次同一个结局 ——
导购业绩页那 9 次循环改成两条 `GROUP BY`,35.0 → 31.1 ms,
**改代码的风险换 11%,而加一条索引换 12.7 倍**。

用户 2026-10-25 拍「加冗余列」。

## 为什么用触发器,而不在写口里加 UPDATE

这一列最大的风险不是慢,是**漂**:客户换了顾问而订单上这一列没跟着改,
顾问的订单清单就少几条,**而且不报错**。两种做法:

    写口同步   在每一处改派写口后面加一句 UPDATE   —— **靠记得**,是「约定」
    触发器     数据库层保证                        —— **做不到漏**,是「结构」

项目的价值观明写着「结构 > 约定」(CLAUDE.md 第 6 节:新加一处对外保证,
必须说清它靠**结构**(做不到)还是**约定**(不该做))。
而 2026-10-25 早上刚栽过一次「靠记得」:每日平移那条路径漏了回填门店码,
**缺口当天隐形、第二天早上才红**,而那时看起来像有人改坏了数据。

量过的代价(真库副本):开单 **+0.0032 ms/条**(从零重建 2.6 万单多花 0.1 秒)、
改派一个有 801 单的客户 **0.865 ms**、查询不受影响。

## 三个触发器,覆盖三条会让它失准的路

    ① AFTER INSERT ON ordr                     新开一单 → 填上客户当前的顾问号
    ② AFTER UPDATE OF advisor_no ON customer   客户换顾问 → 他名下**全部**订单跟着改
    ③ AFTER UPDATE OF customer_id ON ordr      订单换客户 → 重算(削峰 / 造数会这么干)

⚠️ **②是全量同步,不是部分同步。** `server.py` 两处改派写口里,
`appointment` 用的是 `AND status='已预约'`(只动还没发生的预约)——
**那是对的,但照抄过来就是错的**:`cu.advisor_no=?` 问的是
「客户**现在**归谁」、不分订单状态。只同步未完成的订单,查询就不等价了,
**而不等价不报错,只会让顾问的订单清单少几条**。
> 隔壁那张表的写法是对的,照抄过来就是错的 —— 而两段代码长得几乎一样。

⚠️ **客户合并不走这里。** 合并只在 `customer` 上记 `merged_into`(副档记并入谁),
**不改 `ordr.customer_id`**,所以那一列照旧跟着副档的顾问走 —— 这是既有口径,
这一列只是把它存了下来,没有改变它。

## 两个口

    python3 tools/add_cust_advisor.py --建列   加列 + 建三个触发器 + 回填已有行
    python3 tools/add_cust_advisor.py --校验   再回填一次,**而填了任何一行就报警**

⚠️ **第二个口不是「再修一次」,它是触发器的体检。**
触发器在工作的话,这一步应该**一行都不用填**。填了就说明有写口绕过了触发器
(`INSERT OR REPLACE`、ATTACH 另一个库写、或者触发器被谁删了),
那是要去查的事,**不是静默修好就算了**。
> 一个「触发器在工作」,和一个「触发器没了但每天有人回填」,
> **在那一列的数据上长得一模一样。**
"""
import argparse, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "backend", "lanxiu.db")
G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

列 = "cust_advisor_no"
触发器 = {
    "trg_ordr_cust_adv_fill": f"""CREATE TRIGGER trg_ordr_cust_adv_fill
AFTER INSERT ON ordr
BEGIN
  UPDATE ordr SET {列} = (SELECT advisor_no FROM customer WHERE id = NEW.customer_id)
   WHERE id = NEW.id;
END""",
    "trg_cust_adv_sync": f"""CREATE TRIGGER trg_cust_adv_sync
AFTER UPDATE OF advisor_no ON customer
BEGIN
  UPDATE ordr SET {列} = NEW.advisor_no WHERE customer_id = NEW.id;
END""",
    "trg_ordr_recustomer": f"""CREATE TRIGGER trg_ordr_recustomer
AFTER UPDATE OF customer_id ON ordr
BEGIN
  UPDATE ordr SET {列} = (SELECT advisor_no FROM customer WHERE id = NEW.customer_id)
   WHERE id = NEW.id;
END""",
}

回填SQL = (f"UPDATE ordr SET {列} = (SELECT advisor_no FROM customer WHERE id = ordr.customer_id) "
           f"WHERE customer_id IS NOT NULL AND ("
           f"  {列} IS NOT (SELECT advisor_no FROM customer WHERE id = ordr.customer_id))")


def 有列(c):
    return 列 in {r[1] for r in c.execute("PRAGMA table_info(ordr)")}


def 已有的触发器(c):
    return {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'")}


def 要回填几行(c):
    """**只算 customer 还在的那些行。** 客户不存在的单另算 —— 那是另一件事,
    混进来会让「触发器漏了」和「数据里有孤儿单」长得一样。"""
    return c.execute(
        f"SELECT COUNT(*) FROM ordr o JOIN customer cu ON cu.id=o.customer_id "
        f"WHERE o.{列} IS NOT cu.advisor_no").fetchone()[0]


def 孤儿单(c):
    return c.execute(
        "SELECT COUNT(*) FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id "
        "WHERE o.customer_id IS NOT NULL AND cu.id IS NULL").fetchone()[0]


def main():
    ap = argparse.ArgumentParser(description="订单上冗余「客户现在归谁」这一列")
    ap.add_argument("--建列", action="store_true", dest="建列",
                    help="加列 + 建三个触发器 + 回填已有行(给重建流水线的前段)")
    ap.add_argument("--校验", action="store_true", dest="校验",
                    help="触发器的体检:再回填一次,**填了任何一行就报警**")
    a = ap.parse_args()
    if not (a.建列 or a.校验):
        ap.print_help()
        return 2

    print("订单上的「客户现在归谁」· 冗余列")
    print("=" * 78)
    print(f"库:{DB}")
    c = sqlite3.connect(DB)

    if a.建列:
        if 有列(c):
            print(f"  {Y}列 `{列}` 已经在了 —— 不重复加(幂等){D}")
        else:
            c.execute(f"ALTER TABLE ordr ADD COLUMN {列} TEXT")
            print(f"  {G}✅ 加上了列 `{列}`{D}")
        有 = 已有的触发器(c)
        for 名, ddl in 触发器.items():
            if 名 in 有:
                print(f"  {Y}触发器 `{名}` 已经在了 —— 不重复建{D}")
            else:
                c.executescript(ddl + ";")
                print(f"  {G}✅ 建上了触发器 `{名}`{D}")
        n = 要回填几行(c)
        if n:
            c.execute(回填SQL)
            print(f"  {G}✅ 回填了 {n} 行{D}(seed 在加列之前就插进来的那些)")
        else:
            print("  一行都不用回填")
        c.commit()

    if a.校验:
        if not 有列(c):
            print(f"  {Rd}❌ 列 `{列}` 不在 —— 先跑 `--建列`{D}")
            c.close()
            return 1
        缺 = [名 for 名 in 触发器 if 名 not in 已有的触发器(c)]
        n = 要回填几行(c)
        孤 = 孤儿单(c)
        if 缺:
            print(f"  {Rd}❌ 这几个触发器不在:{缺}{D}")
            print(f"     **触发器活在库里,而库不进版本库** —— 从零重建一次它就没了,"
                  f"而那时数据开始漂、没有任何东西会红。跑 `--建列` 补上。")
        if n:
            c.execute(回填SQL)
            c.commit()
            print(f"  {Rd}❌ 有 {n} 行要回填 —— 已经填上了,**但这件事本身是个信号**{D}")
            print(f"     触发器在工作的话这一步应该**一行都不用填**。"
                  f"填了就说明有写口绕过了它(`INSERT OR REPLACE`、ATTACH 另一个库写、"
                  f"或者触发器被谁删了)—— **去查那个写口,别当成修好了**。")
        if 孤:
            print(f"  {Y}⚠️ 另有 {孤} 单的 customer_id 指向不存在的客户 —— "
                  f"那是另一件事(孤儿单),不在这一列的职责里,但值得看一眼{D}")
        if not 缺 and not n:
            print(f"  {G}✅ 三个触发器都在,而且一行都不用回填 —— 它们真的在工作{D}")
        c.close()
        return 1 if (缺 or n) else 0

    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
