#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""营销 SOP 要的三类数据 —— **一起造,因为它们描述同一段时间**。

    python3 fakedata/mkt_sop_seed.py <库> --看      只看会造什么,不写
    python3 fakedata/mkt_sop_seed.py <库> --做      真写(会先备份)

## 为什么是一个脚本而不是三次 plan/load

清单(`交数据工坊_营销SOP的数据缺口_20261004.md`)开头那条:

> 三类描述的是**同一批客户的同一段时间** —— 档位历史说「她三个月前是活跃」,
> 触点数据说「她那三个月一次都没来」。
> **三批各自正确、而合起来矛盾的数据,和一批一致的,
> 在每一批自己的校验上长得一模一样。**

而 2026-10-05 实跑一轮又踩出第三条:**`customer.lifecycle` 是存量字段**,
造完触点它不会自己重算 —— 于是「刚被造了跟进的客户」档位还写着「休眠」。
> 一个**存着的档位**和一个**按当前事实算出来的档位**,
> **在那一列上长得一模一样** —— 而它们已经不一致了。

所以这三件事必须在一个事务里:**造触点 → 重算档位 → 把重算结果落成历史的最后一条**。

## 它做哪三件

### ① 量体 → 下单的时间关系(双峰)

业务 2026-10-05 定:
  · **快峰**:有明确穿着日期(婚礼/毕业/汉服节)—— 量完体几天到两周,她在倒推工期
  · **慢峰**:没有明确日期 —— 一两个月甚至更久

⚠️ **分峰靠一个新字段 `has_wear_date`**,而不是现有的任何一列。查过四个候选:
    `ordr.delivery`   ❌ 是配送方式
    `ordr.appt_id`    ❌ 全库 31 条
    「婚礼婚服」标签   🟡 **按形制推的**(唐制明制默认都挂着,约一半的单)——
                        拿它分峰,快峰里混着一大半没婚期的人
> 一个按**真实场合**分出来的双峰,和一个按**形制标签**分出来的,
> **在那张分布图上长得一模一样。**

### ② 三类空触点(预约 / 跟进 / 日程)

实测覆盖:预约 55 人 / 跟进 24 人 / 日程 58 人 —— 都是 **0%**(总 8068)。
造的时候**只挂现有客户**,不造新客户(造新客户会冲掉八档分布和 RFM 分位)。

### ③ 档位历史

每个被动过的客户,按**当时的事实**逐月回算档位,落进 `lifecycle_history`。
最后一条 = 现在重算出来的那个,并同步回 `customer.lifecycle`。

## 守住的东西

- **保护清单**:`.fakedata/营销SOP造数-保护清单.json` 里的行一律不碰
  (8 个客户写死在检查/评测里,还有一批被 `truth` 表引用)。
  > 一批「只是多了些历史记录」的数据,和一批**把评测真值搞乱了**的数据,
  > **在它自己的校验上长得一模一样。**
- **确定性**:固定种子,同一个库跑两次结果一样(`determinism_check` 要这个)。
- **可回滚**:`--做` 之前先把库文件复制一份到 `.fakedata/`。
- **不取当天**:时间基准从库里的 `world_meta` 读 —— 这个仓库为
  「夹具写死日期」和「拿机器的今天当基准」栽过。
"""
import argparse
import json
import os
import random
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "knowledge"))

种子 = 20261005
标记 = "SYN-"          # 和 fakedata 的前缀一致,一条 DELETE 清得干净
保护文件 = os.path.join(根, ".fakedata", "营销SOP造数-保护清单.json")

# 双峰的形状(业务 2026-10-05 定「有场合的快、没场合的慢」)。
# ⚠️ **这几个数是业务给的形状,不是从库里算的** —— 库里算出来的 83 天
# 是造数机制的产物(量体时间按客户序号轮排),不能用。
快峰 = (3, 14)      # 有明确穿着日期:几天到两周
慢峰 = (30, 120)    # 没有:一两个月到四个月
有场合的比例 = 0.35  # 大约三分之一的单有明确日期


def _世界今天(c):
    """时间基准从库里取,**不取机器的今天**。

    ⚠️⚠️ **键是 `world_today`,不是 `today`。** 2026-10-09 发现:
    这里原来查的是 `where k='today'` —— 而库里那个键叫 `world_today`,
    所以**主路径从来没有生效过**,一直在走下面「取最新订单日期」那条兜底。
    今天两者恰好都是 2026-10-09,所以看不出来。

    > 一个「从世界时钟读的今天」和一个「从最新订单日期兜出来的今天」,
    > **在数值相等的那天长得一模一样** —— 而库里一有未来日期的订单它们就分叉。

    全仓只有这一处这么查(`grep "k='today'"` 唯一命中)。
    现在:先读 `world_today`,读不到就**当场炸**,不再用「最新订单日期」顶 ——
    那条兜底的危险不在于它算错,在于它**让一个坏掉的主路径看起来是好的**。
    """
    r = c.execute("select v from world_meta where k='world_today'").fetchone()
    if r and r[0]:
        return datetime.fromisoformat(str(r[0])[:10])
    raise SystemExit("world_meta 里没有 world_today —— **不拿机器的今天、也不拿最新订单日期顶**"
                     "(正规读法是 backend/worldclock.今天();这个仓库为时钟栽过)")


def _现扫受保护(c):
    """**现从 `truth` 表扫**出受保护客户 —— 不读任何手抄名单。

    2026-10-09:那份手抄的 `.fakedata/营销SOP造数-保护清单.json` 只护住 22 个,
    而 `truth` 引用且在库的客户有 44 个 —— **漏掉的 30 个全是 `C21000–C21031`**
    (客户合并那批)。而清单里护住 `E-A2/A3/A4` 的理由写的正好是「被真值表引用(truth)」。

    > 一份「护住了被真值表引用的客户」的保护清单,和一份「只护住了其中 14 个」的,
    > **在那条理由上长得一模一样。**

    `tools/order_mix.受保护客户()` 的注释早就写明了该怎么做:
    「**不手抄名单** —— 哪天加了第 15 条边界用例,手抄那份不会跟着变,
      而那时重算会静默抹掉它。」**那份 JSON 就是它警告过的手抄件。**
    所以这里**两份并集**:JSON 还护着它独有的那些(FX- 前缀、写死在检查里的 id),
    现扫的补上 truth 这一路。
    """
    import sys as _s
    _t = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
    if _t not in _s.path:
        _s.path.insert(0, _t)
    import order_mix as OM
    return set(OM.受保护客户(c))


def _读保护(c):
    """把保护清单翻译成「这些客户 id 不许碰」(手抄清单 ∪ 现扫)。"""
    护 = set(_现扫受保护(c))
    if not os.path.exists(保护文件):
        print(f"  ⚠️ 没有保护清单 {保护文件} —— **这不叫「没有要护的」,叫没扫过**")
        print("     先跑:python3 fakedata/cli.py protect <库> --env dev "
              "--include-guesses --write " + 保护文件)
        raise SystemExit(2)
    d = json.load(open(保护文件, encoding="utf-8"))
    条 = d if isinstance(d, list) else d.get("items") or d.get("protect") or []
    for it in 条:
        表 = it.get("table") or it.get("表")
        w = it.get("where") or it.get("条件") or ""
        if 表 != "customer" or not w:
            continue
        try:
            for r in c.execute(f"select id from customer where {w}"):
                护.add(r[0])
        except Exception as e:
            print(f"  ⚠️ 保护条件跑不动,**当成要护**:{w[:50]} ({e})")
    return 护


def 跑(库, 真写):
    rnd = random.Random(种子)
    c = sqlite3.connect(库)
    c.row_factory = sqlite3.Row
    今天 = _世界今天(c)
    护 = _读保护(c)
    print(f"库:{库}")
    print(f"世界日期:{今天:%Y-%m-%d}(从库里取,不是机器的今天)")
    print(f"保护:{len(护)} 个客户不许碰")

    # 能动的客户 = 现有客户 − 保护名单
    可动 = [r["id"] for r in c.execute("select id from customer order by id")
            if r["id"] not in 护]
    print(f"可动客户:{len(可动)}(总 {len(可动) + len(护)})")

    计划 = {"场合字段": 0, "量体时间": 0, "预约": 0, "跟进": 0, "日程": 0,
           "档位历史": 0, "档位重算": 0}

    # ── ① 场合字段 + 量体→下单的双峰 ──────────────────────────
    列 = {r["name"] for r in c.execute("pragma table_info(ordr)")}
    if "has_wear_date" not in 列:
        if 真写:
            c.execute("alter table ordr add column has_wear_date INT")
            print("  + 加列 ordr.has_wear_date(有无明确穿着日期)")
        else:
            print("  + 会加列 ordr.has_wear_date")

    # ⚠️ **带上 `cu.created`** —— 下面造触点要拿它当下界(C3)。
    # 第一版这里没查它,而下界那段用了 `try/except: pass` ——
    # 于是 KeyError 被静静吞掉,**下界形同虚设**。
    # > 一个「下界生效了」的造数,和一个「取字段失败被吞掉」的,
    # > **在它跑完不报错这件事上长得一模一样。**
    单们 = c.execute(
        "select o.id, o.customer_id, o.created, cu.created cu_created "
        "  from ordr o join customer cu on cu.id = o.customer_id "
        " where o.customer_id is not null and o.created is not null "
        " order by o.id").fetchall()
    单们 = [r for r in 单们 if r["customer_id"] not in 护]
    计划["场合字段"] = len(单们)

    # ⚠️ **一单配它自己那次量体** —— 链路是
    #     measure_rec.order_item_id → ordr_item.id → ordr_item.order_id → ordr.id
    #
    # 前两版都栽在粒度上,而且栽法不同:
    #   v1 只改「最早那一行」      → 1/25 的行带双峰,被其余稀释(中位 53 vs 56)
    #   v2 改「最早那一次量体」    → 只有每人第一单对,后面几单和同一次量体比(74 vs 84)
    # > 一个「双峰造好了」的数据,和一个「只有一小撮带双峰」的,
    # > **在那张分布图上长得一模一样。**
    #
    # ⚠️ 能关联的只有 **4218 个订单**(总 31660 的 13%)——
    # 所以**验收时必须只统计有关联的那批**,否则又被另外 87% 稀释(这是第三次)。
    # ⚠️ **带上客户建档时间 `cu.created`** —— 触点不能早于这个人存在。
    # 第一版只保证了「触点之间的顺序」(预约→日程→下单),漏了这条更基本的,
    # 于是 `spec_check` 的 C3 红了:预约 2308 条、日程 2281 条早于客户建档。
    # > 一批「顺序看起来对」的旅程,和一批**时间上不可能存在**的,
    # > **在那条旅程顺序上长得一模一样。**
    配对 = c.execute("""
        select oi.order_id oid, o.customer_id cid, o.created,
               m.measured_at, m.order_item_id oiid, cu.created cu_created
          from measure_rec m
          join ordr_item oi on oi.id = m.order_item_id
          join ordr o on o.id = oi.order_id
          join customer cu on cu.id = o.customer_id
         where o.created is not null and o.customer_id is not null
         group by oi.order_id""").fetchall()
    配对 = [r for r in 配对 if r["cid"] not in 护]
    计划["量体时间"] = len(配对)

    改量体 = []
    for r in 配对:
        有场合 = 1 if rnd.random() < 有场合的比例 else 0
        低, 高 = 快峰 if 有场合 else 慢峰
        隔 = rnd.randint(低, 高)
        try:
            下单日 = datetime.fromisoformat(str(r["created"])[:10])
        except Exception:
            continue
        量体日 = 下单日 - timedelta(days=隔)
        # 下界:客户建档那天(含)——**早于它就不是一个可能发生的事**
        建档 = datetime.fromisoformat(str(r["cu_created"])[:10])
        if 量体日 < 建档:
            量体日 = 建档
        改量体.append((有场合, r["oid"], r["oiid"], f"{量体日:%Y-%m-%d} 14:30"))

    if 真写:
        for 有场合, oid, oiid, 量体时间 in 改量体:
            c.execute("update ordr set has_wear_date=? where id=?", (有场合, oid))
            # 改**这一单对应的那批尺寸项**(同一个 order_item_id)
            c.execute("update measure_rec set measured_at=? where order_item_id=?",
                      (量体时间, oiid))
            # ⚠️ **`ordr.recept_at` 要跟着改** —— 否则 `link_check` 那条
            # 「挂上的量体接待都是亲自服务的」会红 3750 单。
            #
            # 它查的是**三元匹配**(同客户 + **同日期** + 同量体人),
            # 而不是它名字说的 method:
            #     substr(m.measured_at,1,10) = o.recept_at
            # 我只改了量体时间,于是接待依据断了。
            # > 一条「**因为远程量体**而红」的断言,和一条「**因为日期对不上**
            # > 而红」的、名字一样的断言,**在那句报错上长得一模一样** ——
            # > 我差点照着名字去查 method(而库里一条远程量体都没有)。
            c.execute("""update ordr set recept_at=?
                          where id=? and appt_src='接待关联' and recept_evi='量体'""",
                      (量体时间[:10], oid))
            # ⚠️ 量体人也要和订单上记的接待人一致 —— 「接待她的人」和
            # 「给她量体的人」本来就该是同一个。
            # **改的是量体记录,不是 `recept_by`**:后者是「谁接待的」这个业务事实,
            # 把它改成匹配量体人等于篡改事实。
            # > 一个把接待人改成匹配量体人的修法,和一个把量体人改成匹配接待人的,
            # > **在那条断言变绿这件事上长得一模一样** —— 而前者在改事实。
            接 = c.execute("""select recept_by from ordr where id=?
                              and appt_src='接待关联' and recept_evi='量体'
                              and recept_by is not null""", (oid,)).fetchone()
            if 接 and 接[0]:
                c.execute("update measure_rec set measured_by_no=? where order_item_id=?",
                          (接[0], oiid))
        # 没配上的单也要有 has_wear_date(否则那一列一半是空的,
        # 而「空」和「没有明确日期」是两件事)
        c.execute("update ordr set has_wear_date=0 where has_wear_date is null")

    # ── ② 三类空触点 —— **只挂现有客户** ───────────────────────
    顾问们 = [r[0] for r in c.execute(
        "select distinct advisor_no from ordr where advisor_no is not null limit 20")]
    if not 顾问们:
        顾问们 = ["A001"]
    # 挑一批客户补触点:**按订单时间倒推**,让触点落在订单之前(旅程顺序)
    补 = [r for r in 单们 if rnd.random() < 0.55]
    计划["预约"] = 计划["日程"] = len(补)
    计划["跟进"] = int(len(补) * 0.6)

    if 真写:
        n = 0
        for r in 补:
            try:
                下单日 = datetime.fromisoformat(str(r["created"])[:10])
            except Exception:
                continue
            n += 1
            顾问 = 顾问们[n % len(顾问们)]
            约日 = 下单日 - timedelta(days=rnd.randint(20, 60))
            # 同一条下界 —— 预约/日程也不能早于客户建档(C3)。
            # ⚠️ **不包 try/except** —— 缺 `cu_created` 就该当场炸,
            # 吞掉的话下界就没生效而没人知道。
            建档 = datetime.fromisoformat(str(r["cu_created"])[:10])
            if 约日 < 建档:
                约日 = 建档
            日程日 = 约日 + timedelta(days=rnd.randint(1, 5))
            if 日程日 > 下单日:
                日程日 = 下单日
            aid = f"{标记}AP{n:06d}"
            # 预约 → 日程 → (跟进) → 下单:**顺序对得上**,不是随机撒
            # ⚠️ **`checkin_ts` 必须给** —— 状态是「已完成」而没有签到时间,
            # 在 `link_check` 那条「到店/完成的预约都有签到时间」会红。
            # > 一条「状态=已完成」而**没有签到时间**的预约,和一条真完成了的,
            # > **在那个状态字段上长得一模一样** ——
            # > 而「她到底来没来」这件事只有签到时间能证明。
            # 第一版漏了它:我只查了列名,没查「哪些列在业务上是必须的」。
            c.execute("""insert into appointment(id, customer_id, advisor_no,
                          start_ts, status, shop, checkin_ts)
                         values(?,?,?,?,?,?,?)""",
                      (aid, r["customer_id"], 顾问,
                       f"{约日:%Y-%m-%d} 10:00", "已完成",
                       c.execute("select shop from ordr where id=?",
                                 (r["id"],)).fetchone()[0],
                       f"{约日:%Y-%m-%d} 10:05"))   # 签到:约定时间后几分钟
            c.execute("""insert into schedule(id, customer_id, advisor_no, type,
                          start_ts, status, ref_id)
                         values(?,?,?,?,?,?,?)""",
                      (f"{标记}SC{n:06d}", r["customer_id"], 顾问, "到店",
                       f"{日程日:%Y-%m-%d} 10:30", "已完成", r["customer_id"]))
            if n % 10 < 6:
                跟日 = 日程日 + timedelta(days=rnd.randint(1, 10))
                # ⚠️ **上界:世界今天** —— `spec_check` 的 C4
                # 「已经发生的事,时间不能在未来」。
                # 它的说明值得抄在这儿:
                # > 「未来日期在单条记录上**完全合法** —— 格式对、类型对、
                # > 不早于创建时间,**只有和「今天」比才看得出来**。
                # > 而生命周期按「多久没互动」算,**负数天数会把客户算成永远活跃**」
                # 而这批数据正是要喂给流失预警的 —— 3 条「永远活跃」就是 3 条毒样本。
                if 跟日 > 今天:
                    跟日 = 今天
                # ⚠️ 列名是 `channel` / `content`,**不是 way / note** ——
                # 第一版猜错了当场炸。写之前把三张表的列**一次查全**,
                # 别一个个撞:一条猜对了的列名和一条查过了的,
                # 在它插入成功时长得一模一样。
                c.execute("""insert into followup(id, customer_id, advisor_no,
                              ts, channel, content, appt_id)
                             values(?,?,?,?,?,?,?)""",
                          (f"{标记}FU{n:06d}", r["customer_id"], 顾问,
                           f"{跟日:%Y-%m-%d} 15:00", "电话",
                           "方案跟进(造)", aid))

    # ── ③ 重算档位 + 档位历史 ──────────────────────────────────
    # ⚠️ **这一步不能省**:造完触点 `customer.lifecycle` 不会自己变,
    # 于是「刚被造了跟进的客户」档位还写着休眠 ——
    # 而 C 方案(流失预警)要学的正是「档位怎么随事实变化」。
    import lifecycle as L
    # ⚠️ **自己保证表在。** 建表语句写进了 `backend/seed.py`,
    # 但那只在「从零重建」时生效 —— **现有的库(包括真库)里没有这张表**。
    # > 一张「写进了建表脚本」的表,和一张「库里真有」的表,
    # > **在那份 seed.py 上长得一模一样。**
    if 真写:
        c.execute("""create table if not exists lifecycle_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT NOT NULL, as_of TEXT NOT NULL,
            lifecycle TEXT NOT NULL, idle_days INT, orders_12m INT,
            amount_12m REAL, quarters_12m INT, source TEXT NOT NULL,
            note TEXT, created TEXT NOT NULL)""")
        c.execute("""create index if not exists ix_lchist_cust
                     on lifecycle_history(customer_id, as_of)""")
    动过 = sorted({r["customer_id"] for r in 补})
    计划["档位重算"] = len(动过)
    计划["档位历史"] = len(动过) * 4      # 每人回算 4 个时点(3/6/9/12 个月前)

    if 真写:
        import sys as _s
        _t = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
        if _t not in _s.path:
            _s.path.insert(0, _t)
        import order_mix as OM
        for cid in 动过:
            行 = dict(c.execute("select * from customer where id=?", (cid,)).fetchone())
            建档 = str(行.get("created") or "")[:10]
            for 月前 in (12, 9, 6, 3, 0):
                基 = 今天 - timedelta(days=30 * 月前)
                # ⚠️⚠️ **客户还没建档的那些时点,一条历史都不写。**
                #
                # 原来是五个时点无条件各写一条,于是「客户建档前」也有档位 ——
                # 而 `某天的事实` 在那时候一条互动都查不到,算出 idle=9999 → **「流失」**。
                # 这不是口径问题,是**事实错误**:客户那时候还不存在,不该有任何档位。
                #
                # 代价在下游:这段历史是给流失预警当训练样本的,
                # 「建档前流失 → 建档后活跃」会被当成**「流失后又回来」的正例**,直接污染标签。
                # > 一条「这个人流失过又回来了」的历史,和一条「这个人那时候还没建档」的,
                # > **在那张表上长得一模一样** —— 字段齐、档位列有值,只有日期泄露了它。
                if 建档 and f"{基:%Y-%m-%d}" < 建档:
                    continue
                # ⚠️ **「最后一次互动」要按这个时点算,不能用「现在」的。**
                #
                # 第一版把它放在循环外面算一次 —— 于是 12 个月前那个时点的
                # `idle_days` 也是按今天的互动算的,五个时点的事实几乎一样,
                # **档位自然不变**:实测 5804 个客户里 **0% 变过**,
                # 而 C 方案(流失预警)要学的正是「档位怎么随事实变化」。
                # > 一份「回算了 12 个月」的历史,和一份**每个时点都用今天的
                # > 数据算**的,**在那张表上长得一模一样** ——
                # > 条数、字段、格式全对,只有「档位不变」这一点泄露了它。
                #
                # ⚠️⚠️⚠️ **2026-10-09:这里原来手抄了一份「末」的算法,而它不算下单。**
                # 只取 followup / appointment / schedule 三张触点表的最近一次 ——
                # 而 `customer.last_interact` 是**算订单**的。于是刚下过单、
                # 但没被跟进过的客户被判成休眠,又在下面 `月前 == 0` 那一步
                # 写回 `customer.lifecycle`,而同一行里的事实列没跟着改。
                # 全库 **2687 个客户**的档位和它自己那一行的事实对不上;
                # 页面被问「多少人休眠」时报的就是那一列(存 1395,按当天重算 864)。
                #
                # > **一份手抄的口径和一份共用的,在第一天长得一模一样。**
                #
                # 口径(用户 2026-10-09 拍):**下了单就算互动** ——
                # 待确认 / 没付款 / 后来取消退款的都算(下单那天确实有过互动)。
                # 现在算法只有一份:`tools/order_mix.某天的事实`,
                # 它所有取数都限定 `<= 基`,所以回算过去时点也用它。
                # **这里不许再抄第二份。**
                写回, 事实 = OM.某天的事实(c, 行, 基.date() if hasattr(基, "date") else 基)
                档 = L.decide(事实)
                # ⚠️ **键是「生命周期」(中文),不是 `lifecycle`。**
                # 第一版写的是 `档.get("lifecycle")` —— 取不到就静静返回 None,
                # 于是 23216 条历史的档位列**全是字符串 "None"**。
                # > 一个 `.get()` 取不到而静静返回 None 的读法,和一个真取到了的,
                # > **在那行代码跑过去这件事上长得一模一样。**
                #
                # ⚠️ 更糟的是**我的验证也被同一个 bug 骗过了**:
                # 「300 条抽查重跑一致」也过了 —— 因为重跑 decide() 也得到 None,
                # 两边一致。**用同一个错读法去验,永远验不出这个错。**
                #
                # 所以这里**不兜底**:键不在就当场炸。
                档名 = 档["生命周期"]
                c.execute("""insert into lifecycle_history(customer_id, as_of,
                              lifecycle, idle_days, orders_12m, amount_12m,
                              quarters_12m, source, note, created)
                             values(?,?,?,?,?,?,?,?,?,?)""",
                          (cid, f"{基:%Y-%m-%d}", str(档名), 事实["idle_days"],
                           事实["orders_12m"], 事实["amount_12m"], 事实["quarters_12m"],
                           "synth", f"回算({月前} 个月前)", f"{今天:%Y-%m-%d}"))
                if 月前 == 0:
                    # **最后一条 = 现在**,并同步回 customer —— 两者必须一致
                    #
                    # ⚠️⚠️ **要把算档位用的那些事实一起写回去,不能只写档位。**
                    # 原来这里只有 `update customer set lifecycle=?` ——
                    # 于是档位是按「这个脚本算的闲置」来的,而 `idle_days` /
                    # `last_interact` 那几列还是别人算的,**同一行自相矛盾**。
                    # 这正是 `backend/lifecycle_sync_check.py` 的 C 类红
                    # (「存的档位 ≠ 按存的事实重算」)的来源。
                    # > 一行「档位写对了」和一行「档位和它自己的事实对不上」,
                    # > **在那一列上长得一模一样** —— 直到有人数人头。
                    列 = dict(写回, lifecycle=str(档名),
                              matched="/".join(档["命中"]))
                    c.execute("update customer set "
                              + ",".join(f"{x}=?" for x in 列) + " where id=?",
                              [列[x] for x in 列] + [cid])
        c.commit()

    print("\n要造的:")
    for k, v in 计划.items():
        print(f"  {k}: {v}")
    if not 真写:
        print("\n(只看不写。加 --做 才真写)")
        return 0
    print("\n✅ 写完了。**下一步跑 trial 让项目自己的检查当裁判**")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("库")
    ap.add_argument("--看", action="store_true")
    ap.add_argument("--做", action="store_true")
    a = ap.parse_args()
    if not (a.看 or a.做):
        print("要 --看 或 --做"); return 2
    if a.做:
        # ⚠️ 先备份 —— 这个脚本改的是库本身,而**改坏了和改对了在返回码上长得一样**
        bak = os.path.join(根, ".fakedata",
                           f"{os.path.basename(a.库)}.bak-{datetime.now():%Y%m%d%H%M%S}")
        os.makedirs(os.path.dirname(bak), exist_ok=True)
        shutil.copy2(a.库, bak)
        print(f"备份:{bak}\n")
    return 跑(a.库, a.做)


if __name__ == "__main__":
    sys.exit(main())
