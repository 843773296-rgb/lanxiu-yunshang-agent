#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""色系:把商品的传统色名,映射到客户会说的那几个颜色词。

## 为什么要这一层

库里 SKU 的色名是**传统色名**:茜色、绛、胭脂、妃色、竹青、藏青、月白、玄色……
而客户说的是**「我想要红色的」**。

> **两套词汇对不上 —— 客户说「红色」,匹配不到任何一个商品。**

商机判断的第一个条件就是「客户表达过未满足的偏好」,
而业务举的原例正是「某个客户说想要红色的衣服,最后买了蓝色」。
没有这一层,那个例子在系统里根本查不出来。

## 三个设计决定

**① 目标词表用「客户会说的词」,不是传统色系。**
分到「青」这一档对客户没用 —— 他不会说「我要青色的」,他说蓝或绿。

**② 每条映射都标来源,不合并。**
    已核    业务确认过
    推导    按传统色名的通行释义推的 —— **没人确认过,但图上画的是真色**
    不适用  这个色名压根不是颜色(见下)

**「业务确认的红」和「我按释义推的红」如果都标成已核,
错了也没人知道是谁错的。** 这条是并行会话在纹样那边踩出来的:
146 个定制品里商品名真正点明纹样的只有 14 个,其余全是推的,
三态设计下那 132 款会被标成「已核」—— 那比没有标记更糟。

**③ 「不适用」和「还没标」必须分得开。**
`定制`(146 个 SKU)不是颜色 —— 定制品的颜色由客户在下单时定;
`素`(33 个)是本色未染。两者都**没有色系,而这是正确状态**。
表达方式:在映射表里有一行、`family` 为空、`source='不适用'`;
**而「还没标」是映射表里根本没有这一行** —— 自检会把它抓出来。

## ⚠️ 六条我拿不准的,已标成待业务核

中文的「青」本身就横跨蓝绿黑,这几个色名的归属**不是查字典能定的**,
要看店里实际卖的那批货是什么样:黛 / 赭 / 秋香 / 藕荷 / 点翠 / 竹青。
它们现在按通行释义推了一个值,**并且在 note 里写明了另一种可能**。

技术约束(tools/determinism_check.py):不用 SQL RANDOM、不用 random、
时间取 seed.py 的 TODAY(不是机器的今天)。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")
from seed import TODAY

CATEGORY = "色系"

# 客户会说的颜色词。顺序即 sort。
# 没有「青」这一档 —— 客户不会说「我要青色的」,他说蓝或绿。
色系 = [("SC-CLR-01", "红"), ("SC-CLR-02", "橙"), ("SC-CLR-03", "黄"),
        ("SC-CLR-04", "绿"), ("SC-CLR-05", "蓝"), ("SC-CLR-06", "紫"),
        ("SC-CLR-07", "粉"), ("SC-CLR-08", "黑"), ("SC-CLR-09", "白"),
        ("SC-CLR-10", "灰"), ("SC-CLR-11", "棕"), ("SC-CLR-12", "金银")]

# (色名, 色系, 来源, 备注)  —— family 为 None 表示不适用
映射 = [
    # ── 明确的,按传统色名通行释义 ──────────────────────────
    ("茜色",  "红", "推导", "茜草染的红,偏正红"),
    ("绛",    "红", "推导", "深红"),
    ("胭脂",  "红", "推导", "胭脂虫/红花染的红,偏深"),
    ("妃色",  "红", "推导", "又名杨妃色,淡红"),
    ("缃色",  "黄", "推导", "浅黄"),
    ("玄色",  "黑", "推导", "玄即黑,古代最正式的礼服色"),
    ("月白",  "白", "推导", "极浅的蓝白,归白 —— 客户说「月白」时指的是浅色不是蓝"),
    ("玉白",  "白", "推导", "玉色白"),
    ("藏青",  "蓝", "推导", "深蓝偏黑"),
    ("靛青",  "蓝", "推导", "靛蓝染,正蓝"),
    ("天青",  "蓝", "推导", "雨过天青,浅蓝"),
    ("青碧",  "绿", "推导", "碧色偏绿"),
    ("紫檀",  "紫", "推导", "紫檀木色,深紫偏褐"),
    ("金",    "金银", "推导", "金线/金箔"),
    ("银",    "金银", "推导", "银线"),

    # ── ⚠️ 六条拿不准的,已推一个值但要业务核 ──────────────
    ("黛",    "黑", "待核", "黛是青黑色 —— **归黑还是归蓝,要看店里那批货实际什么样**"),
    ("赭",    "棕", "待核", "赭石是红褐色 —— **归棕还是归红,两说**"),
    ("秋香",  "黄", "待核", "秋香色是偏黄的绿 —— **归黄还是归绿,两说**"),
    ("藕荷",  "紫", "待核", "藕荷是浅紫带粉 —— **归紫还是归粉,两说**"),
    ("点翠",  "蓝", "待核", "点翠是翠鸟羽毛的蓝 —— **归蓝还是归绿,两说**"),
    ("竹青",  "绿", "待核", "竹青偏青绿 —— **归绿还是归蓝,两说**"),

    # ── 不是颜色 ────────────────────────────────────────
    ("定制",  None, "不适用", "定制品的颜色由客户下单时定,**没有固定颜色不是没标注**"),
    ("素",    None, "不适用", "本色未染"),
]


def main():
    c = sqlite3.connect(DB)

    # ── 1. 色系词表进 sys_code ────────────────────────────────
    for i, (code, name) in enumerate(色系, 1):
        c.execute("""insert into sys_code(code,category,name,val,sort,status,note)
                     values(?,?,?,?,?,?,?)
                     on conflict(code) do update set
                       name=excluded.name, sort=excluded.sort, status=excluded.status""",
                  (code, CATEGORY, name, code.lower().replace("sc-clr-", "clr"), i, "启用",
                   "客户会说的颜色词;商品的传统色名经 color_family 映射过来"))

    # ── 2. 色名 → 色系 ────────────────────────────────────────
    # family 可以为空(不适用);**而「还没标」是这张表里根本没有那一行**
    c.execute("""create table if not exists color_family(
                   color   TEXT primary key,
                   family  TEXT,
                   source  TEXT not null,      -- 已核 / 推导 / 待核 / 不适用
                   note    TEXT,
                   updated TEXT not null)""")
    c.execute("delete from color_family")
    for 色名, 系, 来源, 备注 in 映射:
        c.execute("insert into color_family(color,family,source,note,updated) values(?,?,?,?,?)",
                  (色名, 系, 来源, 备注, TODAY))
    c.commit()

    # ── 3. 自己证明干了活 ─────────────────────────────────────
    q = lambda s, *a: c.execute(s, a).fetchone()[0]

    # 这道自检是这个脚本存在的理由:**每个 SKU 用到的色名都必须有归属**。
    # 漏一个,那些货在「客户想要红色」的查询里就是隐形的 —— 而查询不会报错。
    漏 = [r[0] for r in c.execute(
        "select distinct color from sku where color not in (select color from color_family)")]
    if 漏:
        sys.exit(f"❌ 这些色名没有归属:{漏} —— 用这些色的货在按颜色找时是隐形的")

    词表 = q("select count(*) from sys_code where category=?", CATEGORY)
    野 = [r[0] for r in c.execute(
        """select distinct family from color_family where family is not null
           and family not in (select name from sys_code where category=?)""", (CATEGORY,))]
    if 野:
        sys.exit(f"❌ 映射到了词表里没有的色系:{野}")

    有系 = q("select count(*) from color_family where family is not null")
    待核 = q("select count(*) from color_family where source='待核'")
    不适用 = q("select count(*) from color_family where source='不适用'")
    覆盖 = q("""select count(*) from sku s join color_family f on s.color=f.color
                where f.family is not null""")
    总sku = q("select count(*) from sku")
    print(f"  色系词表 {词表} 个;色名映射 {有系} 条有色系(其中 {待核} 条待业务核)、{不适用} 条不适用")
    print(f"  {覆盖}/{总sku} 个 SKU 能按颜色找到(其余 {总sku-覆盖} 个是定制/素色,**不是漏标**)")
    c.close()


if __name__ == "__main__":
    main()
