#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**为真实查询加的索引** —— 登记在一处,由建库流水线建出来,由判据守住。

来路:只读审计 2026-10-23 第 4 条,用户 2026-10-24 拍「现在就加」。

## ⚠️ 加哪几条是**量出来的**,不是照审计抄的

审计给的建议是「按 EXPLAIN 验再加索引」。照那条做会加错 ——
因为 **EXPLAIN 从 `SCAN` 变成 `SEARCH`,和「真的变快了」是两件事**。
2026-10-24 在库副本上逐条量过(`.backup` 出来的副本,不是 `cp`):

    索引                      EXPLAIN        实测
    customer(advisor_no)      SCAN → SEARCH  0.927 → 0.781 ms   **1.2x**
    ordr(advisor_no)          SCAN → SEARCH  3.681 → 3.152 ms   **1.2x**

两条都「生效了」,而一条都没变快。原因是**选择性**:全库 9 个顾问,
`advisor_no=?` 一筛还剩九分之一(客户约 800~1700 行、订单约 2500~5600 行)——
索引只是换了条路去读差不多多的行,而且每行还要**回表**取数据。

> **一条白加的索引和一条真有用的索引,在 EXPLAIN 上长得一模一样。**
> 分开它们的只有耗时,而耗时 EXPLAIN 不会告诉你。

真正把它们救回来的是**覆盖索引** —— 把查询要用的列全带进索引里,
SQLite 就一次都不用回表:

    customer(advisor_no, merged_into)            1.179 → 0.033 ms   **35.5x**
    ordr(advisor_no, prd_status, received)        4.342 → 0.245 ms   **17.7x**
    导购业绩整页(9 个顾问 × 2 条查询)            35.0  → 2.8   ms   **12.7x**

**差别只是在索引里多带一两列。** 所以这里登记的不只是「哪张表哪一列」,
还有**「这条必须是覆盖索引」** —— 判据会去验计划里有没有 `COVERING`:
少带一列,它仍然是 `SEARCH`、仍然「用上了」,而收益从 35 倍掉回 1.2 倍,
**没有任何地方会报错**。

## ⚠️ 顺带否决掉的一条:把那个页面改成一条 GROUP BY

导购业绩页现在是**循环 9 个顾问、每人查两次**。直觉上该改成两条
`GROUP BY advisor_no`。实测:35.0 → **31.1 ms** —— 几乎没用,
因为不加覆盖索引它照样得把整张表读一遍。
**这条改代码的风险换 11%,而加一条索引换 12.7 倍。** 所以不改。

## 代价(也量了)

    改一条订单实收   0.0030 → 0.0039 ms   (+28%,绝对值 **0.9 微秒**)
    插一条有效日程   0.0054 → 0.0057 ms   (+6%)
    三条索引占空间   0.91 MB / 81.7 MB    (1.11%)

`ordr` 那条覆盖索引带了 `received`(钱,每次收款都会变),所以写会变慢 ——
百分比看着吓人,**绝对值是微秒**。日程那条是**部分索引**
(`WHERE status='有效'`):全库 14737 条日程里只有 34 条有效,
所以索引只装 34 行,表长到一百万行它还是几十行,
**而已完成的日程怎么插都不碰它**。

## 为什么要在这里登记一份,而不是直接写在 seed.py 里

`seed.py` 只在**从零建库**时跑。写在那儿的索引,**在任何一个已经存在的库上都不存在** ——
而缺了索引**不报错,只是慢**。于是「代码里写了索引」和「这个库上有索引」
可以长期不一致,谁都不会发现。

所以这里是唯一的登记处,三个地方来取:
  · `seed.py` 从零建库时建一遍
  · `tools/ensure_tables.py` 重建流水线里再兜一次
  · 这个文件自己的 `--做` 给**已经存在的库**补上

而 `backend/query_index_check.py` 守住三件事:库里真有、DDL 和登记一致、
**计划里真的用上了(要求覆盖的必须是覆盖)**,外加「建库路径上真的有人调它」——
> **「我登记了一条索引」和「有人会去建它」是两件事。**
"""
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(HERE, "lanxiu.db")

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def _一个有效日程的人(c):
    r = c.execute("SELECT assignee_no FROM schedule WHERE status='有效' "
                  "AND assignee_no IS NOT NULL ORDER BY id LIMIT 1").fetchone()
    return r[0] if r else None


def _一个顾问(c):
    """⚠️ 取**名下客户最多**的那个顾问 —— 不是随便一个。
    选择性最差的那个人才是这条索引要证明自己的地方:名下只有 3 个客户的顾问
    上面「加了索引快很多」是必然的,证明不了什么。"""
    r = c.execute("SELECT advisor_no FROM customer WHERE advisor_no IS NOT NULL "
                  "GROUP BY advisor_no ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    return r[0] if r else None


# ⚠️ **`锚` 是这张表里最容易被忽略的一列。**
# 它是「我登记的这条查询,现在还在代码里」的凭据 —— 一段**从那个文件里原样抄来**的片段。
# 没有它的话,这张表就是那条 SQL 的**第二份手抄件**:哪天 tasks.py 把查询改了,
# 这里留在原地,判据照着旧 SQL 跑 EXPLAIN、照样绿,
# **而真正在跑的那条查询已经用不上这个索引了**。(CLAUDE.md §7-2 同源谬误那一族。)
索引 = [
    dict(
        名="ix_sched_busy",
        表="schedule",
        本体="CREATE INDEX ix_sched_busy ON schedule(assignee_no, start_ts, end_ts) "
             "WHERE status='有效'",
        要求="用上",          # 不是覆盖(要回表取 id),但只在 34 行里回
        为什么="批量排班的冲突检查:每一条都要问「这个人那个时段有没有别的事」,"
               "一批 20 条就把整张 schedule 扫 20 遍。",
        锚=("backend/tasks.py", "FROM schedule WHERE assignee_no=? AND status='有效'"),
        查询="SELECT id FROM schedule WHERE assignee_no=? AND status='有效' "
             "AND start_ts < ? AND end_ts > ?",
        取参=lambda c: (_一个有效日程的人(c), "2026-11-01 12:00", "2026-11-01 10:00"),
        实测="0.535 → 0.006 ms(89.9x);部分索引,只装 34 行",
    ),
    dict(
        名="ix_cust_adv_cov",
        表="customer",
        本体="CREATE INDEX ix_cust_adv_cov ON customer(advisor_no, merged_into)",
        要求="覆盖",          # ← 少了 merged_into 就从 35x 掉回 1.2x,而且不报错
        为什么="导购业绩页按顾问数客户人头,9 个顾问各数一次。"
               "带上 merged_into 才覆盖得住(人头口径要它),否则每行都回表。",
        锚=("backend/server.py", "FROM customer WHERE advisor_no=? AND {_人头()}"),
        查询="SELECT COUNT(*) FROM customer WHERE advisor_no=? "
             "AND (merged_into IS NULL OR merged_into='')",
        取参=lambda c: (_一个顾问(c),),
        实测="1.179 → 0.033 ms(35.5x)",
    ),
    dict(
        名="ix_ordr_adv_cov",
        表="ordr",
        本体="CREATE INDEX ix_ordr_adv_cov ON ordr(advisor_no, prd_status, received)",
        要求="覆盖",
        为什么="导购业绩页按顾问加总实收和完成单数,9 个顾问各查两次。"
               "带上 prd_status 和 received 才不用回表。",
        锚=("backend/server.py", "WHERE advisor_no=? AND prd_status NOT IN ('待付款','已关闭')"),
        查询="SELECT COUNT(*), COALESCE(SUM(received),0) FROM ordr "
             "WHERE advisor_no=? AND prd_status NOT IN ('待付款','已关闭')",
        取参=lambda c: (_一个顾问(c),),
        实测="4.342 → 0.245 ms(17.7x)",
    ),
]

# 建库路径上必须有人调 `建索引()`。判据按这张表逐个去文本里找 ——
# ⚠️ **这不是形式主义**:删掉一处调用,本地那个库里索引还在、一路绿,
# 只有 CI 从零重建才会红。那正是「本地绿 ≠ CI 绿」的第三种机制(库的新旧)。
建库路径 = [
    ("backend/seed.py", "从零建库"),
    ("tools/ensure_tables.py", "重建流水线兜一次"),
]


def 建索引(conn, 说=False):
    """在 conn 上把登记的索引全建出来(已经有的不动)。返回这次真建了几条。"""
    有 = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    新 = 0
    for ix in 索引:
        if ix["名"] in 有:
            continue
        # ⚠️ 存进 sqlite_master 的 SQL 里**不含 `IF NOT EXISTS`**(SQLite 自己剥掉),
        # 所以登记的是**本体**,建的时候才补上这个词 —— 否则判据比 DDL 永远对不上。
        conn.execute(ix["本体"].replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1))
        新 += 1
        if 说:
            print(f"  + {ix['名']}  —— {ix['实测']}")
    return 新


def 归一(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def main():
    做 = "--做" in sys.argv[1:]
    野 = [a for a in sys.argv[1:] if a not in ("--做",)]
    if 野:
        print(f"{Rd}❌ 不认识这些参数:{野} —— **不认识就不跑**{D}")
        return 2
    库 = DB
    if not os.path.exists(库):
        print(f"{Y}库不在:{库}{D}")
        return 1
    print("为真实查询登记的索引")
    print("=" * 78)
    print(f"库:{库}")
    with sqlite3.connect(f"file:{库}?mode=ro", uri=True) as ro:
        有 = {r[0]: r[1] for r in ro.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index'")}
    缺 = [ix for ix in 索引 if ix["名"] not in 有]
    歪 = [ix for ix in 索引 if ix["名"] in 有 and 归一(有[ix["名"]]) != 归一(ix["本体"])]
    for ix in 索引:
        态 = "缺" if ix["名"] in [x["名"] for x in 缺] else (
            "和登记不一致" if ix["名"] in [x["名"] for x in 歪] else "在")
        print(f"  [{态}] {ix['名']}  ({ix['要求']})  {ix['实测']}")
    if 歪:
        print(f"  {Rd}❌ 这几条库里有、但 DDL 和登记不一样:{[x['名'] for x in 歪]}{D}")
        print(f"      **不自动改** —— 索引定义变了意味着收益也变了,"
              f"得先重新量一次再决定(要换就自己 DROP 再跑这个)。")
        return 1
    if not 缺:
        print(f"  {G}三条都在,一条都不用建 —— 这不叫没查,是查过了{D}")
        return 0
    if not 做:
        print(f"  {Y}(试跑,一个字都没改。确认之后加 `--做`){D}")
        return 0
    c = sqlite3.connect(库)
    with c:
        n = 建索引(c, 说=True)
    c.close()
    print(f"  {G}建了 {n} 条{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
