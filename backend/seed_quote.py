#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报价表 —— **报价是事件,一次报价一行,永不覆盖**(业务 2026-09-27 拍)。

口径在 `knowledge/quote.py`。

## 为什么不是往 `scheme` 上加几列

摆给业务的三个方向里,选的是「另建一张表、每次报价一行」。理由业务自己说得最清楚:
**客户说「你们上次说 8600」时,系统要查得出来是哪一次、谁报的、当时依据是什么。**

往方案上加列的话只留得住最后一次 —— 而报价单是**会被截图转发**的东西
(`quote` skill 的文件头就是这么开头的):顾客手里那份是上周那个价,
系统里已经是新的,**而不一致时不报错**。两份都合法、都能打开,
只有把它们放在一起看才矛盾。

## 算错了怎么办:**作废,不是改**

业务 2026-09-27 第二次拍板:允许作废那一条(要写原因),**不许改、不许删**。
⚠️ 用户明确知情的代价:**客户手里那份不会因为系统标了作废就消失** ——
作废只对内,对外还是得跟客户说。

所以这张表里 `作废于 / 作废原因` 两列的意义是「这一份不作数」,
不是「这一份没发生过」——**后者做不到,而假装做得到比不做更危险**。

## 不存最终售价

`quote` skill 里写着:「助手不给最终售价,物料成本 × 系数才是售价,
系数由财务和店长定」。这张表**也不存** —— 存了就等于系统给出了一个它无权给的数。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")

DDL = """
CREATE TABLE IF NOT EXISTS quote(
  -- 一次报价一行。**永不覆盖** —— 改错了走作废(要写原因),不改这一行。
  id TEXT PRIMARY KEY,
  scheme_id TEXT,                    -- 挂在方案上。**方案是「一件事」的单位**
  customer_id TEXT,                  -- 冗余一列方便查,但**方案上那个才是准的**
  quoted_at TEXT,                    -- 报于哪天(世界时钟,会被 shift_world 平移)
  advisor_no TEXT,                   -- 谁报的(**工号**,不是名字 —— 名字列 2026-09-16 已全库删除)
  -- `quote` skill 第一步列的五样,一样都不能省。缺了不许拿默认值糊过去:
  -- **一个缺项被填成 0 的报价,比一个明说「工期没查」的报价危险得多。**
  material_cost REAL,                -- 物料成本(kb_bom 算的)。**不是售价**
  lead_time TEXT,                    -- 工期区间(kb_lead 给的),对外按最慢那个数
  feasible TEXT,                      -- 可 / 需评估 / 不可(kb_combo 判的)
  size_no TEXT,                       -- 客户穿哪个码(kb_fit 或问顾问)
  stock TEXT,                         -- 面料有没有现货(get_stock)
  note TEXT,                          -- 原文摘要:发出去那份的要点,便于对「客户手里是哪一份」
  -- 作废(业务 2026-09-27):留痕,不删不改
  voided_at TEXT, void_reason TEXT, voided_by TEXT);
CREATE INDEX IF NOT EXISTS ix_quote_scheme ON quote(scheme_id);
CREATE INDEX IF NOT EXISTS ix_quote_customer ON quote(customer_id);
CREATE INDEX IF NOT EXISTS ix_quote_at ON quote(quoted_at);
"""


def 建表(c=None):
    """建表(已经在了就什么都不做)。`c` 可以是连接也可以是库路径 —— 同 seed_rating.建表。"""
    if c is None or isinstance(c, str):
        with sqlite3.connect(c or DB) as cx:
            cx.executescript(DDL)
    else:
        c.executescript(DDL)


def main():
    建表()
    with sqlite3.connect(DB) as c:
        n = c.execute("SELECT COUNT(*) FROM quote").fetchone()[0]
    print(f"✅ 报价表就位(quote,现在 {n} 条)")
    print("   ⚠️ **这一版只建表,不铺数据** —— 报价是 `quote` skill 真跑出来的东西,")
    print("      造一批假报价等于给评测喂一批没人报过的价。等写口和工具立住再说。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
