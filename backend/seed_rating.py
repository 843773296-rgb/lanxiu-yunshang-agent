#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评价表 —— **这一版只建表,不铺数据**(业务 2026-09-27:造数先别铺)。

口径在 `knowledge/rating.py`。

## 为什么不另起一张「待处理清单」

差评要「自动进待处理清单」(业务 2026-09-27)。库里**已经有那份清单** ——
`task` 表,现在装着售后判责、客户合并确认、财务人工任务三类,它们的共同点正是
「**系统发现了事,等人来处理**」。差评是同一回事,所以加一个 `type='评价差评'`,
**不新建第二张清单表**。

⚠️ 和 `tasks.py` / `tasktypes.py` 那一套**不是一回事**,别混:
那一套是**店长派给顾问的活**(派单、agent 建议谁去)。差评没有人派 ——
它是系统写出来的,而且业务定了「只给店长看,不进顾问考核」。

已有先例可抄:售后判责的**工单**在 `task`,**研判详情**在 `triage` 表。
同一个分法:**状态归工单,内容归自己那张表。**

## 状态只存一处

`rating` 表**故意没有 status 列** —— 差评处理到哪一步只看 `task.status`。
两处都存的话,「工单关了但评价那行还是待处理」这种漂**不会报错**,
它只是让两个页面显示不同的东西。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")

DDL = """
CREATE TABLE IF NOT EXISTS rating(
  -- 签收后顾客在小程序给的评价。**一个包裹一次**(签收落到包裹,所以评价也落到包裹)。
  pkg_id TEXT PRIMARY KEY,
  order_id TEXT, customer_id INTEGER,
  star INTEGER,                             -- 1-5,整数。**不收半星、不夹范围**(超了是提交端的 bug)
  note TEXT, rated_at TEXT,
  src TEXT,                                 -- 来源,只认「顾客小程序」—— 顾问不能替顾客评
  -- 经手顾问**工号**:记下来但不进考核(业务 2026-09-27)。记的原因是店长要能查是谁经手的;
  -- 一旦要进考核,必须同时做防刷 —— 见 knowledge/rating.进考核前要做什么()
  --
  -- ⚠️ 列名是 `advisor_no` 不是 `advisor`。第一版叫 `advisor`,CI 当场红 ——
  -- 这个库里 `advisor` 是**名字列**的名字,而名字列 2026-09-16 已全库删除
  -- (`backend/advisor_write_check.py` 反着守它:谁在 INSERT 里写回 advisor 谁红)。
  -- 我往一个按约定表示「名字」的列名里塞了**工号**,检查抓得对:
  -- **列名说的是一件事,里面装的是另一件事** —— 而这在页面上看不出来,
  -- 直到有人按名字去 JOIN 员工表,一行都对不上。
  advisor_no TEXT,
  edit_cnt INTEGER DEFAULT 0, edited_at TEXT, star_before INTEGER,
  -- 差评挂的工单号(task 表里那一行)。**status 不在这儿** —— 只看 task.status
  task_id TEXT,
  handled_at TEXT, handled_by TEXT, handle_note TEXT,
  -- ── 2026-09-29 按业内补的几样(口径在 knowledge/rating.py,**全是交付体验的一部分**)──
  -- 分项:准时 / 合身 / 导购 / 包装,1-5 选填。**没评是 NULL,不是 0 星**。
  -- 这四项是 `这个星级能说明什么()` 早就承诺了的,原来表里只有一个总分给不出来。
  star_ontime INTEGER, star_fit INTEGER, star_service INTEGER, star_package INTEGER,
  tags TEXT,                                -- 快捷标签,顿号分隔。只收 rating.快捷标签 词表里的
  media TEXT,                               -- 图片/视频,JSON 数组 [{类型,地址}]
  anonymous INTEGER DEFAULT 0,              -- 1 = **只对外匿名**;店长照样看得到是谁(差评要跟进)
  -- 追评:**穿过之后**的那句话。不带星,不改 star,不进差评清单 ——
  -- 星级衡量交付那一刻,「穿了两周起球了」是另一件事,放这里而不是混进星级
  followup_note TEXT, followup_at TEXT);
CREATE INDEX IF NOT EXISTS ix_rating_order ON rating(order_id);
CREATE INDEX IF NOT EXISTS ix_rating_star  ON rating(star);
CREATE INDEX IF NOT EXISTS ix_rating_task  ON rating(task_id);
"""


def 建表(c=None):
    """建表(已经在了就什么都不做)。

    `c` 可以是**连接**也可以是**库路径**:`tools/ensure_tables.py` 按它自己的约定
    传连接进来(它要在同一个事务里建好几个模块的表),而检查脚本传的是库副本的路径。
    两种都收,省掉一个「为了迁就调用方而存在的第二个函数」。
    """
    if c is None or isinstance(c, str):
        with sqlite3.connect(c or DB) as cx:
            _建(cx)
    else:
        _建(c)


def _建(c):
    # ⚠️ **先建表、再补列、最后建索引。** 一次 executescript(DDL) 的话,
    # 老库缺的列要是被索引引用,会在补列之前就崩(`no such column`)——
    # 写 rating_write_check 那条「老表补列」时当场撞到的。
    表, 索引 = DDL.split("\nCREATE INDEX", 1)
    c.executescript(表)
    _补列(c)
    c.executescript("CREATE INDEX" + 索引)


# 2026-09-29 补的列。`CREATE TABLE IF NOT EXISTS` 在**已有的库**上什么都不做 ——
# 新列只会出现在从零重建的库里,而本地库和 CI 库从此长得不一样(eb3af41 那次就是反过来栽的)。
# 所以已有的表要逐列补。**列清单从 DDL 里现取**,不另抄一份 —— 抄一份就会有一天漏一列。
def _补列(c):
    import re
    有 = {r[1] for r in c.execute("PRAGMA table_info(rating)")}
    体 = re.search(r"CREATE TABLE IF NOT EXISTS rating\((.*?)\);", re.sub(r"--[^\n]*", "", DDL), re.S).group(1)
    for 段 in 体.split(","):
        字 = 段.split()
        if len(字) >= 2 and 字[0] not in 有:
            c.execute(f"ALTER TABLE rating ADD COLUMN {' '.join(字)}")


def main():
    建表()
    with sqlite3.connect(DB) as c:
        n = c.execute("SELECT COUNT(*) FROM rating").fetchone()[0]
    print(f"✅ 评价表就位(rating,现在 {n} 条)")
    print("   ⚠️ **这一版只建表,不铺数据** —— 业务 2026-09-27:造数先别铺,")
    print("      等口径 / 表 / 写口三件立住再铺,否则又是一批「先造数据、口径后补」的东西。")
    print("   差评的待处理清单**用已有的 task 表**(type='评价差评'),没有新建第二张。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
