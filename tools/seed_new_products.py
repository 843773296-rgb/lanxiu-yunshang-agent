#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造 50 款新商品,全部存成「待上架」,按每周 2 件排开计划上新日(用户 2026-10-10)。

    python3 tools/seed_new_products.py --试跑    # 在真库的副本上整套跑一遍,不动真库
    python3 tools/seed_new_products.py --做
    python3 tools/seed_new_products.py --回滚
    python3 tools/seed_new_products.py --复查

## 用户拍过的三条

1. **按现有比例分**:296 款的 (品类 × 定制/标品) 构成是什么样,这 50 件就照着分
   (实测:定制品 146 / 标品 150;`C01 女装` 188 款 = 63.5%)。
   ⚠️ **按子类等比取,别去解释「汉服形制 2/3」那句话** —— 等比取出来自动就是现有比例;
   自己拍一个「2/3 指哪些品类」的定义,**错了也不报错**,50 款的结构悄悄偏掉而报表正常。
2. **先全部「待上架」**,顾客看不到;由每日上新每周放 2 件,约半年放完(50 ÷ 2 = 25 周)。
3. **出图照现成流程**:造完跑 `tools/export_image_prompts.py --重导`。全量出,不缩减。

## 一个字段都不编:每一款都从「兄弟款」派生

挑一个**同品类、同 kind** 的现有款当模板,照抄它的 `unit` / `commission_type` /
`commission_val` / `cover`(系列名)/ 号型 / 颜色;只改该改的(spu、名字、版型、价、
status、created、plan_on_shelf、图)。**猜一个单位或号型的代价**是报价和下单当场出错,
而它看起来完全正常。

## 命名:`「主料」+ 形制名`,两条约束一次满足

现有款就是这么起的名(`「香云纱」宋制上襦` / `「苎麻」明制方领对襟短衫`),而它同时满足:

  · **标品的名字里必须含 `material.cat='主料'` 的真实名字** ——
    `export_image_prompts.py` 对标品是**从商品名里认面料 / 工艺**的。
    2026-10-10 在库副本上实测:认不出来**丢两段**(「面料」和「**纹样**"),
    而「纹样」那段的原文是「素面,整件没有任何花纹…**不要自行加花**」——
    少了它生图会**自己加花纹**,而这款其实是素面的。
    > **图和商品不一致,而清单、页面、库里全都正常。**
  · **朝代 / 形制的说法必须和版型一致**。同一次实测里我借了别人的版型、自己起名
    「宋制上襦」,结果提示词里「商品名」写宋制而「形制」写唐制交领襦裙 ——
    自相矛盾,**生图照哪个都不算错**。
    所以**先挑版型,再按版型的形制起名**,不是反过来。

## 「待上架」为什么安全(用户 2026-10-10 选的方案)

按 `product.status` 过滤的地方,白名单 `='上架'` 是多数,加个新值天然安全。
真正的洞在**下单口**:`backend/order_write.py` 开单时 join 了 product **却不看 status**。
**列表有 149 处、下单口只有 1 处** —— 所以闸装在写口(另一笔改,见 HANDOFF)。
这个脚本只负责:造出来的款**全是待上架**,一件都不许是上架。

## `plan_on_shelf` 为什么登记成「整列日期不挪」

**跟着平移那一天永远不会到来。** 平移每天把世界和计划**一起**往后推一天,
`计划 − 今天` 恒定不变,「每周放 2 件」永远不会发生,**而且没有任何报错**。
(活证明:整库挪 200 天,19 条逾期任务一条不增不减。)
登记成不挪之后,放出规则是**纯日期驱动**的 ——
`status='待上架' AND plan_on_shelf <= 世界今天`,脚本不用记「放到第几件」那种状态,
**数据本身就是排期表**。

⚠️ 而且**绝不能**把它加进 `backend/worldclock.py` 的 `已发生的时间列`:
那份清单是平移前置闸的判据,任何落在世界今天之后的行都让平移**当场拒跑** ——
计划日期按定义在未来,登记进去的后果是**每日 05:10 的平移天天失败**,
而报错会说「已经发生的事落在未来」,**指向一个不存在的 bug**。

## 放出走正门,不许只改 status

`backend/arrival_card.上新(spus, 今天, db)`(并行会话 10-10 写的)依次做:
挂上架 + 写上架日 → `opportunity_store.回捞` 绑商机、派「商机提醒」→ 写建议。
只改 status 的后果是**新款上去了、等它的客户没人去叫,而页面上什么都不缺**。
"""
import argparse
import datetime as dt
import json
import os
import random
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend")]

DB = os.path.join(ROOT, "backend", "lanxiu.db")
真库 = DB
批次前缀 = "seed_new_products/"
台账 = "daily_fresh_batch"          # 复用,不新建表

要造 = 50
每周几件 = 2
SPU步长 = 7919                      # 现有 296 款是 lxys_{100000000 + 7919×i},别另起格式
吊牌倍数 = 1.12                     # 实测:tag_price / base_price 恒等于 1.12
积分倍数 = 100                      # 实测:points = base_price × 100

咬合 = [
    ('把造出来的款改成 status=上架',
     '造出来的 50 款全是「待上架」'),
    ('给定制品的可选项塞一对 craft_combo 判「不可」的面料×工艺',
     '定制品没有提供「不可」组合'),
    ('把标品的名字换成认不出主料的词(如「清风朗月」)',
     '标品的名字里认得出主料(出图提示词要靠它)'),
    ('挑一个没有 BOM 的版型',
     '每款的版型都有 BOM(否则报价和排产有空洞)'),
    ('把 plan_on_shelf 排成同一天',
     '计划上新日按每周 2 件排开'),
]


def 不成(r):
    return (not isinstance(r, dict)) or bool(r.get("error")) or r.get("ok") is False


def 世界今天(c):
    return c.execute("SELECT v FROM world_meta WHERE k='world_today'").fetchone()[0]


def 保证有列(c, 说=print):
    """`plan_on_shelf` 不在就加上。**幂等** —— 从零建库时 seed.py 的建表里已经有它,
    这里就是空操作;只有「早就存在的那个库」要补。照 backend/fix_product_pattern.py 的先例。"""
    列 = {r[1] for r in c.execute("PRAGMA table_info(product)")}
    if "plan_on_shelf" not in 列:
        c.execute("ALTER TABLE product ADD COLUMN plan_on_shelf TEXT")
        c.commit()
        说("  + product.plan_on_shelf(这个库里原来没有,已加上)")
        return True
    return False


def 记(c, 批, 表, 主键, 动作, 原值=None):
    c.execute(f"INSERT INTO {台账}(batch,表,主键,动作,原值) VALUES(?,?,?,?,?)",
              (批, 表, str(主键), 动作, json.dumps(原值, ensure_ascii=False) if 原值 else None))
    c.commit()


def 干净主料(c):
    """名字里不带 `·` `/` `(` 的主料 —— **只筛不改**:出图脚本是拿**完整名字**
    在商品名里做子串匹配的,改一个字就认不出来了。"""
    out = [r[0] for r in c.execute("SELECT name FROM material WHERE cat='主料' ORDER BY name")]
    return [x for x in out if not any(ch in x for ch in "·/()（） ")]


def 料价成对(c, 料们):
    """从现有款里取 **(主料, 价) 的真实组合**,按 kind 归好。

    ⚠️ **料和价不许分开取。** 第一版是「主料轮选 + 价从同品类同 kind 的分布里随机取」,
    两头各自都对,**合起来荒谬**:造出了「高支纯棉」魏晋杂裾垂髾 25640 元、
    「亚麻」宋制褙子 50310 元。

    > 一个「按现有价格分布取的价」和一个「这件衣服该卖多少钱」,
    > **在价格区间这张表上长得一模一样** —— 只有把料和价放在一起看才露出来。

    真实数据是绑着的:最贵的那件标品(34540)用的是「云锦 · 库缎」。
    所以这里只取**库里真出现过的那些组合**,一个都不编。
    """
    出 = {}
    for kind, nm, 价 in c.execute(
            "SELECT kind, name, base_price FROM product WHERE base_price>0"):
        命 = [m for m in 料们 if m in (nm or "")]
        if 命:
            # 名字里命中多个时取**最长**那个(「真丝素罗」而不是「纱」)
            出.setdefault(kind, []).append((max(命, key=len), 价))
    return 出


def 配额(c):
    """把 50 件分到各个 (品类, kind) 格子里。

    ⚠️ **用户那两句话管的是两个不同维度,不能混成一个联合分配**:
        「品类**按现有比例**分」      → 品类维度照现有构成等比取
        「定制品和标品**各一半**」    → kind 维度**就是 25 / 25**,不照现有比例
    第一版混成一个联合最大余数,算出来是**定制 28 / 标品 22**(因为带 BOM 版型的
    那批品类里定制品偏多)—— 两句话各满足了一半,而**结果看起来很正常**。
    现在按 kind 分两次,每次在该 kind 的品类分布上等比取。

    只分给「这个品类确实有**带 BOM 的版型**可用」的格子 —— 否则造出来的款
    报价和排产有空洞,而 catalog_check 不查这一条。
    """
    出 = []
    种 = [r[0] for r in c.execute("SELECT DISTINCT kind FROM product ORDER BY kind")]
    种 = [k for k in 种 if k]
    份 = {k: 要造 // len(种) for k in 种}
    for i, k in enumerate(种[:要造 - sum(份.values())]):
        份[k] += 1                      # 除不尽时前几个各多一件
    for kind in 种:
        行 = c.execute("""
            SELECT p.category, COUNT(*) n FROM product p
            WHERE p.kind=? AND p.category IS NOT NULL AND EXISTS(
              SELECT 1 FROM product q JOIN pattern_bom b ON b.pattern=q.pattern
              WHERE q.category=p.category AND q.pattern IS NOT NULL)
            GROUP BY p.category ORDER BY n DESC, p.category""", (kind,)).fetchall()
        总 = sum(r[1] for r in 行)
        if not 总:
            continue
        粗 = [(r[0], 份[kind] * r[1] / 总) for r in 行]
        定 = [[a, int(x)] for a, x in 粗]
        剩 = 份[kind] - sum(x[1] for x in 定)
        序 = sorted(range(len(粗)), key=lambda i: -(粗[i][1] - int(粗[i][1])))
        for i in 序[:剩]:
            定[i][1] += 1
        出 += [(a, kind, n) for a, n in 定 if n > 0]
    return 出


def 可用版型(c, category):
    """这个品类**现有款用过**、而且**有 BOM** 的版型。

    ⚠️ 映射从现有数据派生,**不按形制名猜**:猜错的代价是用料 / 工期 / 量体模板
    全跟着错,而报表上完全正常(`product.pattern` 那条注释记着:补这条边之前,
    86 个有版型的定制品里 66 个的量体模板和版型对不上 —— 长衫按裙子的口径量)。
    """
    # ⚠️ `template` 存的是**完整标签**(`LT01 唐装模版`),不是 `LT01`。
    # 判据在 backend/product_pattern_check.py:76 —— 期望值是
    # `pattern.tpl || ' ' || measure_tpl.name`,所以这里把 measure_tpl 一起连上。
    #
    # > **这一列存编码还是存标签,每一列都不一样。**
    # > 我「从兄弟款抄」的字段(单位 / 系列 / 佣金 / 号型 / 颜色)全对,
    # > 「从上游表取」的两个(`pattern.xz` → 该存名字、`pattern.tpl` → 该存标签)**全错**。
    # > 2026-10-10 为这一类栽了三次,红在三条不同的检查上。
    return c.execute("""
        SELECT DISTINCT pt.code, pt.name, pt.xz, pt.gender,
               pt.tpl || ' ' || m.name AS 量体模版, xz.name
        FROM product pr JOIN pattern pt ON pt.code=pr.pattern
        LEFT JOIN xingzhi xz ON xz.code=pt.xz
        JOIN measure_tpl m ON m.code=pt.tpl
        WHERE pr.category=? AND EXISTS(SELECT 1 FROM pattern_bom b WHERE b.pattern=pt.code)
        ORDER BY pt.code""", (category,)).fetchall()


def 相容的可选项(c, rng, 必含料):
    """挑一组 (面料们, 工艺们),**第一个面料必须是 `必含料`**,而且两两都判「可」。

    ⚠️⚠️ **`mt_opts[0]` 必须就是商品名里那个料。** 第一版是「名字的料」和
    「可选面料」各自独立挑的,结果 25 个定制品**全部错配**:
    一款叫「杭罗」唐制齐胸襦裙,而出图提示词里的面料写着「真丝绉缎」——
    因为 `export_image_prompts.py` 对**定制品**是取 `product_custom.mt_opts` 的
    **第一项(默认款)**,不看名字。

    > 一个「名字和默认面料一致的款」和一个「名字说杭罗、配置页默认真丝绉缎的款」,
    > **在商品表和清单上都长得一模一样** —— 而生图**照哪个都不算错**。
    > (和「商品名写宋制、形制写唐制」同形,那次也是我自己栽的。)

    `catalog_check` 只拦「不可」,但「需评估」在配置页上会多一道人工 ——
    演示时看起来像卡住了,所以这里只取「可」。
    键是 craft 表的编码:面料名也在 craft 里(cat='材质'),和 material 那张表同名
    (实测 31 个干净主料**一个不缺**)。
    """
    码 = {r[1]: r[0] for r in c.execute("SELECT code, name FROM craft")}
    判 = {(r[0], r[1]): r[2] for r in c.execute("SELECT craft, material, verdict FROM craft_combo")}
    材 = [r[0] for r in c.execute("SELECT name FROM craft WHERE cat='材质' ORDER BY name")]
    艺 = [r[0] for r in c.execute("SELECT name FROM craft WHERE cat='工艺' ORDER BY name")]
    材 = [x for x in 材 if not any(ch in x for ch in "·/()（） ") and x != 必含料]
    # 先挑和**这个料**判「可」的工艺 —— 挑不到就返回 None,**不换料**
    可艺 = [k for k in 艺 if 判.get((码.get(k), 码.get(必含料))) == "可"]
    if not 可艺:
        return None, None
    ks = rng.sample(可艺, min(len(可艺), rng.choice((1, 2))))
    # 再加 0~2 个「和这几门工艺都判可」的额外面料
    可材 = [m for m in 材 if all(判.get((码.get(k), 码.get(m))) == "可" for k in ks)]
    rng.shuffle(可材)
    return [必含料] + 可材[:rng.choice((0, 1, 2))], ks


def 按版型定单位(c, 版型, 名字):
    """`unit` 要从**版型的裁片**派生,不是抄兄弟款。

    ⚠️ 三处必须对齐(判据在 backend/product_pattern_check.py:189/193):
        名字里有多件词(襦裙…) → `unit='套'` → 版型裁片**必须覆盖下装**
    我第一版 `unit` 抄兄弟款、版型另外挑 —— 于是「宋制抹胸」拿到了 `unit='套'`,
    而 PT17 的裁片只有上装(前片 / 系带),当场红。
    **又是「同一个事实两个来源」**:unit 说一套、裁片说一件,而两边各自看都正常。

    词表从 `backend/fix_product_pattern.py` **转发,不抄一份** ——
    抄一份的后果是改一处漏一处,而两份不一致时数据照样造得出来。
    """
    import fix_product_pattern as FPP
    片 = [x[0] for x in c.execute("SELECT name FROM pattern_piece WHERE pattern=?", (版型,))]
    有下装 = any(any(k in x for k in FPP.下装裁片词) for x in 片)
    多件 = any(w in 名字 for w in FPP.多件词)
    if 多件 and not 有下装:
        return None          # 名字说多件、裁片只有上装 —— **上游不自洽,不往下传**
    return "套" if 有下装 else "件"


def 兄弟款(c, category, kind):
    """同品类同 kind 的现有款 —— 单位 / 佣金 / 系列名 / 号型 / 颜色都照它。"""
    r = c.execute("""SELECT spu, unit, commission_type, commission_val, cover, gender,
                            base_price, template
                     FROM product WHERE category=? AND kind=? ORDER BY spu LIMIT 1""",
                  (category, kind)).fetchone()
    return r


def 跑(说=print):
    rng = random.Random(20261010)
    c = sqlite3.connect(DB)
    今 = 世界今天(c)
    零 = dt.date.fromisoformat(今)
    批 = 批次前缀 + 今
    if c.execute(f"SELECT 1 FROM {台账} WHERE batch=?", (批,)).fetchone():
        说(f"❌ 今天这一批({批})已经造过了 —— 先 `--回滚` 再重造")
        return 1
    保证有列(c, 说)
    额 = 配额(c)
    if not 额:
        说("❌ 取数取空了:一个 (品类, kind) 格子都没分到 —— **这不叫没什么可造**。"
          "先看 product.category 和 pattern_bom 对不对得上")
        return 1
    主料们 = 干净主料(c)
    if len(主料们) < 8:
        说(f"❌ 干净主料只有 {len(主料们)} 个 —— 名字会大量重复。先看 material 表的 cat='主料'")
        return 1
    成对 = 料价成对(c, 主料们)
    if min((len(v) for v in 成对.values()), default=0) < 10:
        说(f"❌ (主料, 价) 的真实组合太少:{ {k: len(v) for k, v in 成对.items()} } —— "
          f"**这不叫没什么可造**:多半是现有款的名字里认不出主料了,去看 material 的 cat='主料'")
        return 1
    现有名 = {r[0] for r in c.execute("SELECT name FROM product")}
    # 规格码的格式是 **`GG` + 3 位商品序号 + 2 位 SKU 序号**(GG00101 / GG29501),
    # 现有 296 个商品把 001–296 占满了。第一版我写成 `{spu}-SP1` —— **格式不对**,
    # 而 catalog_check 只查「非空」,所以**不会报错**,只是和全库 812 条对不上。
    起规格 = (c.execute("SELECT MAX(CAST(substr(spec_code,3,3) AS INTEGER)) FROM sku "
                        "WHERE spec_code LIKE 'GG%'").fetchone()[0] or 0)
    起号 = (c.execute("SELECT MAX(CAST(substr(spu,6) AS INTEGER)) FROM product "
                      "WHERE spu LIKE 'lxys_%'").fetchone()[0] or 100000000)
    序 = 0
    成, 败 = [], []
    for category, kind, n in 额:
        版型们 = 可用版型(c, category)
        兄 = 兄弟款(c, category, kind)
        if not 版型们 or not 兄:
            败.append(f"{category}/{kind}:可用版型 {len(版型们)} 个、兄弟款 {'有' if 兄 else '没有'} —— 跳过,不硬造")
            continue
        池 = list(成对.get(kind) or [])
        rng.shuffle(池)
        for j in range(n):
            pt = 版型们[(序 + j) % len(版型们)]
            版型, 版名, xz, 版性别, 版模板, 形制名 = pt
            # **先挑版型,再按版型的形制起名** —— 反过来会让商品名和形制自相矛盾
            名基 = 形制名 or 版名
            名, 基价 = None, None
            for k in range(len(池)):
                料, 价 = 池[(序 * 7 + k) % len(池)]
                候 = f"「{料}」{名基}"
                if 候 not in 现有名:
                    名, 基价 = 候, 价
                    break
            if not 名:
                败.append(f"{category}/{kind}:(主料, 价) 组合全撞上了({名基})—— 跳过")
                continue
            单位 = 按版型定单位(c, 版型, 名)
            if 单位 is None:
                败.append(f"{名}:名字说多件而版型 {版型} 的裁片只有上装 —— "
                          f"**上游不自洽,跳过不硬造**")
                continue
            现有名.add(名)
            序 += 1
            起号 += SPU步长
            spu = f"lxys_{起号}"
            基价 = round(基价, 2)
            吊牌 = round(基价 * 吊牌倍数, 2)
            # 每周 每周几件 件:第 1、2 件在下周,第 3、4 件在下下周 ……
            排期 = 零 + dt.timedelta(days=7 * (((序 - 1) // 每周几件) + 1))
            c.execute("""INSERT INTO product(spu,name,category,kind,status,base_price,template,
                         created,updated,cover,tag_price,unit,gender,points,commission_type,
                         commission_val,on_shelf_at,remark,img_main,img_detail,img_intro,pattern,
                         plan_on_shelf)
                         VALUES(?,?,?,?,'待上架',?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?)""",
                      (spu, 名, category, kind, 基价,
                       (版模板 if kind == "定制品" else None),
                       今, 今, 兄[4], 吊牌, 单位, (版性别 or 兄[5]),
                       int(基价 * 积分倍数), 兄[2], 兄[3],
                       # ⚠️ **备注里不写日期。** 写了的话这一列就变成「混着日期却没登记」,
                       # `平移()` 当场拒跑(门禁的「世界日期」那条直接红)。
                       # 这条教训 tools/simulate_sales.py:660 早就记着:
                       # 「哪天定的」是函数注释该说的,**不是每行记录该说的**;
                       # 而计划日期已经在 `plan_on_shelf` 那个结构化字段里了 ——
                       # 再抄进备注就是**同一个事实两个来源,必然漂**。
                       "待上架新款,等排期放出(计划日期见 plan_on_shelf 列)",
                       f"/img/{spu}-main.svg",
                       json.dumps({"小程序": [f"/img/{spu}-d{i}.svg" for i in (1, 2, 3)],
                                   "ipad": [f"/img/{spu}-d1.svg"]}, ensure_ascii=False),
                       json.dumps([{"组名": "商品信息", "图": [f"/img/{spu}-intro.svg"]},
                                   {"组名": "保养", "图": [f"/img/{spu}-d2.svg"]},
                                   {"组名": "送货与退货", "图": [f"/img/{spu}-d3.svg"]}],
                                  ensure_ascii=False),
                       版型, 排期.isoformat()))
            记(c, 批, "product", spu, "新增")
            if kind == "定制品":
                ms, ks = 相容的可选项(c, rng, 料)
                if not ms:
                    败.append(f"{spu}:「{料}」没有任何判「可」的工艺 —— **不换料**"
                              f"(换了名字就和默认面料对不上)")
                    ms, ks = [], []
                # ⚠️ `xz` 存的是形制**名字**,不是编码。第一版存了 `pt.xz`(XZ02 这种),
                # 于是这一列**混用**:我的 25 行是编码、现有 146 行是名字 ——
                # 正是这个项目最恨的「同一列两种写法」。
                # `catalog_check` **不查这条**,是「同名字段」那条按
                # 「登记的钥匙 vs 实际的值」比出来的;而 product_pattern_check.py:107
                # 明写着「`product_custom.xz` 存的是形制『名字』,必须解析得出来」。
                c.execute("INSERT INTO product_custom(spu,xz,mt_opts,kf_opts,lead_days,note) "
                          "VALUES(?,?,?,?,?,?)",
                          (spu, 名基, ",".join(ms), ",".join(ks), "45–60 天", "待上架新款"))
                记(c, 批, "product_custom", spu, "新增")
                # ⚠️ **定制品也要有一条 SKU。** 第一版只给标品造了 ——
                # 而现有 **146 个定制品全都有**一条 `{spu}-01`
                # (`spec='定制/定制'`、`color/size='定制'`、`stock=0`:按单做,不备货)。
                # 漏了的表现**不是报错**:下单口是 `sku JOIN product`,
                # 于是这款在那儿变成「**没有商品**」,而不是「待上架不能下单」——
                # 两种拒绝在「下不成单」这件事上长得一样,**但一个是闸、一个是查不到**,
                # 查不到会让下一个人去怀疑商品号写错了。(order_write_check 当场抓到。)
                code = f"{spu}-01"
                c.execute("""INSERT INTO sku(code,spu,spec,color,size,price,stock,locked,status,
                             spec_code,points,img)
                             VALUES(?,?,'定制/定制','定制','定制',?,0,0,'启用',?,?,?)""",
                          (code, spu, 基价, f"GG{起规格 + 序:03d}01",
                           int(基价 * 积分倍数), f"/img/{spu}-sku1.svg"))
                记(c, 批, "sku", code, "新增")
            else:
                # 号型和颜色**照兄弟款抄** —— 猜一个号型的代价是下单当场出错
                # ⚠️ **`supplier_code` 也要抄。** 规矩是「**标品有供应商、定制品没有**」
                # (定制品不是进的货,是自己做的)—— 漏了的话「商品表单」和「供应商」
                # 两条检查都红:`标品缺 50 个`。而我的定制品 SKU 不填它正好是对的。
                兄sku = c.execute("SELECT spec,color,size,collar,size_no,weight_kg,volume_m3,"
                                  "supplier_code "
                                  "FROM sku WHERE spu=? ORDER BY code LIMIT 2", (兄[0],)).fetchall()
                if not 兄sku:
                    兄sku = [("默认", "月白", "M", None, None, None, None, None)]
                for si, s in enumerate(兄sku, 1):
                    code = f"{spu}-{si}"
                    c.execute("""INSERT INTO sku(code,spu,spec,color,size,price,stock,locked,status,
                                 collar,size_no,spec_code,weight_kg,volume_m3,points,img,
                                 supplier_code)
                                 VALUES(?,?,?,?,?,?,?,0,'启用',?,?,?,?,?,?,?,?)""",
                              (code, spu, s[0], s[1], s[2], 基价, rng.randint(6, 30),
                               s[3], s[4], f"GG{起规格 + 序:03d}{si:02d}", s[5], s[6],
                               int(基价 * 积分倍数), f"/img/{spu}-sku{si}.svg", s[7]))
                    记(c, 批, "sku", code, "新增")
            成.append(spu)
    说(f"  造了 {len(成)} 款,全部「待上架」;计划从 {零 + dt.timedelta(days=7)} 起,"
      f"每周 {每周几件} 件,排到 {零 + dt.timedelta(days=7 * -(-len(成) // 每周几件))}")
    if 败:
        说(f"  ⚠ {len(败)} 处没成(逐条列出来):")
        for x in 败[:10]:
            说(f"    ✗ {x}")
    c.close()
    return 1 if (败 or len(成) != 要造) else 0


def 回滚(说=print):
    c = sqlite3.connect(DB)
    今 = 世界今天(c)
    批 = 批次前缀 + 今
    行 = list(c.execute(f"SELECT 表,主键 FROM {台账} WHERE batch=? ORDER BY id DESC", (批,)))
    if not 行:
        说(f"  这一批({批})没有台账 —— 没造过,或者已经回滚过")
        c.close()
        return 0
    with c:
        for 表, 主键 in 行:
            c.execute(f"DELETE FROM {表} WHERE "
                      + ("code=?" if 表 == "sku" else "spu=?"), (主键,))
        c.execute(f"DELETE FROM {台账} WHERE batch=?", (批,))
    # ⚠️ **plan_on_shelf 这一列不删** —— 列是结构,不是这一批的数据;
    # 删了的话并行会话的日历会从「还没有排期」变成报错。
    说(f"  回滚了 {len(行)} 条(product / product_custom / sku);plan_on_shelf 这一列留着")
    c.close()
    return 0


def 复查(说=print):
    c = sqlite3.connect(DB)
    今 = 世界今天(c)
    挂 = []

    def ck(名, 真, n, 补=""):
        说(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){('  ' + str(补)[:160]) if 补 else ''}")
        if not 真:
            挂.append(名)
        if n == 0:
            说("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
            挂.append(名 + "(样本量 0)")

    列 = {r[1] for r in c.execute("PRAGMA table_info(product)")}
    if "plan_on_shelf" not in 列:
        说("  ❌ product 没有 plan_on_shelf 列 —— 后面几条没法验")
        c.close()
        return 1
    新 = [dict(spu=r[0], name=r[1], kind=r[2], cat=r[3], pat=r[4], plan=r[5], tpl=r[6])
          for r in c.execute("SELECT spu,name,kind,category,pattern,plan_on_shelf,template "
                             "FROM product WHERE status='待上架' ORDER BY spu")]
    ck("造出来的款全是「待上架」", len(新) == 要造, len(新), f"{len(新)} 款")
    from collections import Counter as _C
    按kind = _C(x["kind"] for x in 新)
    ck("定制品和标品各一半(用户口径)", len(set(按kind.values())) == 1 and len(按kind) >= 2,
       len(新), f"{dict(按kind)}")
    上架了 = c.execute("SELECT COUNT(*) FROM product WHERE plan_on_shelf IS NOT NULL "
                       "AND status='上架'").fetchone()[0]
    ck("一件都没有提前上架", 上架了 == 0, len(新), f"{上架了} 件已上架")

    # 每款都要有带 BOM 的版型 —— catalog_check **不查这一条**
    无bom = [x["spu"] for x in 新 if not c.execute(
        "SELECT 1 FROM pattern_bom WHERE pattern=?", (x["pat"] or "",)).fetchone()]
    ck("每款的版型都有 BOM(否则报价和排产有空洞)", not 无bom, len(新), f"{len(无bom)} 款没有")

    # 标品的名字要能认出主料 —— 出图提示词靠它(实测:认不出会丢「面料」和「纹样」两段)
    料 = [r[0] for r in c.execute("SELECT name FROM material WHERE cat='主料'")]
    标 = [x for x in 新 if x["kind"] == "标品"]
    认不出 = [x["name"] for x in 标 if not any(m in x["name"] for m in 料)]
    ck("标品的名字里认得出主料(出图提示词要靠它)", not 认不出, len(标),
       f"{len(认不出)} 个认不出:{认不出[:3]}")

    # 商品名里的朝代/形制说法要和版型一致
    错制 = []
    for x in 新:
        r = c.execute("SELECT xz.name FROM pattern pt LEFT JOIN xingzhi xz ON xz.code=pt.xz "
                      "WHERE pt.code=?", (x["pat"] or "",)).fetchone()
        if r and r[0] and r[0] not in x["name"]:
            错制.append(f"{x['name']} / 版型形制 {r[0]}")
    ck("商品名里的形制说法和版型一致(不然提示词自相矛盾)", not 错制, len(新),
       f"{len(错制)} 个对不上:{错制[:2]}")

    # 定制品不许提供 craft_combo 判「不可」的组合(和 catalog_check 同口径)
    码 = {r[1]: r[0] for r in c.execute("SELECT code, name FROM craft")}
    判 = {(r[0], r[1]): r[2] for r in c.execute("SELECT craft, material, verdict FROM craft_combo")}
    定 = [x for x in 新 if x["kind"] == "定制品"]
    坏组 = []
    for x in 定:
        r = c.execute("SELECT mt_opts, kf_opts FROM product_custom WHERE spu=?", (x["spu"],)).fetchone()
        if not r:
            坏组.append(f"{x['name']} 没有 product_custom")
            continue
        ms = [y for y in (r[0] or "").split(",") if y]
        ks = [y for y in (r[1] or "").split(",") if y]
        if not ms:
            坏组.append(f"{x['name']} 一个可选面料都没有")
        for k in ks:
            for m in ms:
                if 判.get((码.get(k), 码.get(m))) == "不可":
                    坏组.append(f"{x['name']}:{k} × {m}")
    ck("定制品没有提供「不可」组合,也都有可选面料", not 坏组, len(定), f"{len(坏组)} 处:{坏组[:3]}")
    # ⚠️ 这一条防的就是上面那次:名字的料和出图取的默认面料必须是同一个
    错料 = []
    for x in 定:
        r = c.execute("SELECT mt_opts FROM product_custom WHERE spu=?", (x["spu"],)).fetchone()
        默认 = ((r[0] or "").split(",") or [""])[0] if r else ""
        if 默认 and f"「{默认}」" not in x["name"]:
            错料.append(f"{x['name']} / 默认面料 {默认}")
    ck("定制品名字里的料 = 出图取的默认面料(mt_opts 第一项)", not 错料, len(定),
       f"{len(错料)} 个对不上:{错料[:2]}")
    ck("定制品都有量体模版", all(x["tpl"] for x in 定), len(定),
       f"{sum(1 for x in 定 if not x['tpl'])} 个没有")

    # 这一条防的就是上面那次:同一列两种写法(我存编码、现有存名字)
    形制们 = {r[0] for r in c.execute("SELECT name FROM xingzhi")}
    怪xz = [r[0] for r in c.execute(
        "SELECT pc.spu || ':' || COALESCE(pc.xz,'(空)') FROM product_custom pc "
        "JOIN product p ON p.spu=pc.spu WHERE p.status='待上架'")
        if r[0].split(":", 1)[1] not in 形制们]
    ck("product_custom.xz 存的是形制**名字**(和现有 146 行同一种写法)", not 怪xz, len(定),
       f"{len(怪xz)} 条不是名字:{怪xz[:3]}")
    import fix_product_pattern as FPP
    单位不齐 = []
    for r in c.execute("SELECT name, unit, pattern FROM product WHERE status='待上架'"):
        片 = [x[0] for x in c.execute("SELECT name FROM pattern_piece WHERE pattern=?", (r[2],))]
        有下装 = any(any(k in x for k in FPP.下装裁片词) for x in 片)
        多件 = any(w in r[0] for w in FPP.多件词)
        if 多件 and r[1] != "套":
            单位不齐.append(f"{r[0]}:名字说多件而 unit={r[1]}")
        if r[1] == "套" and not 有下装:
            单位不齐.append(f"{r[0]}:unit=套 而版型 {r[2]} 裁片只有上装")
    ck("名字 / unit / 版型裁片三处对齐(套 ⇔ 裁片覆盖下装)", not 单位不齐, len(新),
       f"{len(单位不齐)} 处:{单位不齐[:2]}")
    错模版 = [f"{r[0]}:{r[1]} 应为 {r[2]}" for r in c.execute(
        "SELECT p.spu, p.template, pt.tpl||' '||m.name FROM product p "
        "JOIN pattern pt ON pt.code=p.pattern JOIN measure_tpl m ON m.code=pt.tpl "
        "WHERE p.status='待上架' AND p.kind='定制品' "
        "AND p.template <> pt.tpl||' '||m.name")]
    ck("定制品的量体模板 = 版型的完整标签(和 product_pattern_check 同口径)",
       not 错模版, len(定), f"{len(错模版)} 个对不上:{错模版[:2]}")
    供 = c.execute("SELECT SUM(p.kind='标品' AND (s.supplier_code IS NULL OR s.supplier_code='')), "
                   "SUM(p.kind='定制品' AND s.supplier_code IS NOT NULL AND s.supplier_code<>'') "
                   "FROM sku s JOIN product p ON p.spu=s.spu WHERE p.status='待上架'").fetchone()
    ck("标品 SKU 有供应商、定制品 SKU 没有(定制品不是进的货,是自己做的)",
       (供[0] or 0) == 0 and (供[1] or 0) == 0,
       c.execute("SELECT COUNT(*) FROM sku s JOIN product p ON p.spu=s.spu "
                 "WHERE p.status='待上架'").fetchone()[0],
       f"标品缺 {供[0]} / 定制品多 {供[1]}")
    带日期 = [r[0] for r in c.execute(
        "SELECT name FROM product WHERE status='待上架' AND remark GLOB "
        "'*[12][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'")]
    ck("备注里不写日期(写了 shift_world 当场拒跑)", not 带日期, len(新),
       f"{len(带日期)} 条带日期:{带日期[:2]}")
    无sku = [x["spu"] for x in 新 if not c.execute(
        "SELECT 1 FROM sku WHERE spu=?", (x["spu"],)).fetchone()]
    ck("每款都有 SKU(定制品也要,不然下单口会说「没有商品」而不是「不能下单」)",
       not 无sku, len(新), f"{len(无sku)} 款没有")
    怪码 = [r[0] for r in c.execute(
        "SELECT s.code FROM sku s JOIN product p ON p.spu=s.spu "
        "WHERE p.status='待上架' AND (s.spec_code IS NULL OR s.spec_code NOT GLOB "
        "'GG[0-9][0-9][0-9][0-9][0-9]')")]
    ck("规格码照房内格式(GG+3 位商品号+2 位 SKU 号)", not 怪码,
       c.execute("SELECT COUNT(*) FROM sku s JOIN product p ON p.spu=s.spu "
                 "WHERE p.status='待上架'").fetchone()[0],
       f"{len(怪码)} 条不对:{怪码[:3]}")

    # 计划上新日:都在未来、按每周 N 件排开
    日 = [x["plan"] for x in 新]
    过去 = [d for d in 日 if d and d <= 今]
    ck("计划上新日都在世界今天之后", not 过去, len(新), f"{len(过去)} 个已经过期")
    from collections import Counter
    每周 = Counter(日)
    超 = {k: v for k, v in 每周.items() if v > 每周几件}
    ck(f"计划上新日按每周 {每周几件} 件排开", not 超 and len(每周) >= 要造 // 每周几件,
       len(每周), f"{len(每周)} 个日期;超出的:{list(超.items())[:3]}")

    # 设计稿的必填项(和 catalog_check 的 NEED 同口径)
    缺 = []
    for r in c.execute("SELECT name,tag_price,unit,gender,points,commission_type,img_main "
                       "FROM product WHERE status='待上架'"):
        for i, 标签 in enumerate(("吊牌价", "计量单位", "性别", "兑换积分", "佣金方式", "主图"), 1):
            if r[i] in (None, "", 0) and 标签 != "兑换积分":
                缺.append(f"{r[0]} 缺{标签}")
    ck("设计稿要求的必填项都填了", not 缺, len(新), f"{len(缺)} 处:{缺[:3]}")
    c.close()
    说(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ 全过'}")
    return 1 if 挂 else 0


def 试跑(说=print):
    """在真库的**副本**上整套跑:造数 → 复查 → 回滚 → 比对还原。真库一个字不动。"""
    import shutil, tempfile
    global DB
    工 = tempfile.mkdtemp(prefix="seed_new_products_")
    副 = os.path.join(工, "lanxiu.db")
    assert os.path.realpath(副) != os.path.realpath(真库)
    shutil.copy2(真库, 副)
    DB = 副

    def 快照():
        cc = sqlite3.connect(f"file:{副}?mode=ro", uri=True)
        out = dict(商品=cc.execute("SELECT COUNT(*) FROM product").fetchone()[0],
                   SKU=cc.execute("SELECT COUNT(*) FROM sku").fetchone()[0],
                   定制扩展=cc.execute("SELECT COUNT(*) FROM product_custom").fetchone()[0],
                   台账=cc.execute(f"SELECT COUNT(*) FROM {台账}").fetchone()[0],
                   按状态=dict(cc.execute("SELECT status, COUNT(*) FROM product GROUP BY status")))
        cc.close()
        return out

    try:
        说(f"  副本:{副}")
        前 = 快照()
        说("\n  ① 造数"); rc1 = 跑(说)
        说("\n  ② 复查"); rc2 = 复查(说)
        中 = 快照()
        说("\n  ③ 回滚"); rc3 = 回滚(说)
        后 = 快照()
        说("\n  ④ 回滚还原得回来吗(**真库上不敢验的那一步**)")
        挂 = [k for k in 前 if 前[k] != 后[k]]
        for k in 前:
            说(f"    {'✅' if 前[k] == 后[k] else '❌'} {k}:{前[k]} → {中[k]} → {后[k]}")
        return 1 if (rc1 or rc2 or rc3 or 挂) else 0
    finally:
        shutil.rmtree(工, ignore_errors=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--做", action="store_true")
    p.add_argument("--回滚", action="store_true")
    p.add_argument("--复查", action="store_true")
    p.add_argument("--试跑", action="store_true")
    a = p.parse_args()
    print(f"新品 · 造 {要造} 款「待上架」,每周 {每周几件} 件排开")
    print("=" * 72)
    rc = 0
    if getattr(a, "试跑"):
        rc = 试跑()
    elif getattr(a, "回滚"):
        rc = 回滚()
    elif getattr(a, "做"):
        rc = 跑()
        print("\n复查:")
        rc = 复查() or rc
    elif getattr(a, "复查"):
        rc = 复查()
    else:
        print("  先 --试跑(副本上整套验,不动真库);要动手加 --做;撤回加 --回滚")
    sys.exit(rc)
