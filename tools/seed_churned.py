#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造「真正流失过的老客户」—— 让流失预警里长期没样本的那几支有真实样本。

    python3 tools/seed_churned.py          # 只看
    python3 tools/seed_churned.py --做     # 真写
    python3 tools/seed_churned.py --回滚   # 按前缀删掉(C5 / U5 / W5 / CH)

## 为什么要造

`backend/slipping_check.py` 的覆盖报告长期报:
    GONE 0 个样本 · IMPROVING 0 个样本
而 **GONE 是「已经走完了,这不是预警是复盘」** —— 流失预警里最该有样本的一类。

**根因查实(2026-10-09)**:库里唯一两个「流失」客户是 `E-A3-06` / `E-A2-02`,
**都是边界夹具** —— 它们 `order_cnt` 列写着 3 和 8,而**名下一张真实订单都没有**
(手写进列里的夹具值),也没有档位历史(受保护 + 无订单,两头都排除)。
而夹具**不能**给历史 —— 那就是「硬塞夹具」。再往根上一层:

> **库里最老的订单是 364 天前,而「流失」= 无互动超过 365 天 —— 差一天。**
> 所以不造「超过一年的老订单」,这一支永远是空的。

## 两种人,轨迹是算出来的不是试出来的

档位历史回算 12/9/6/3/0 五个时点(`tools/lifecycle_history_seed.py`),
所以只要把订单日期摆对,档位序列就是确定的:

**A 组 → GONE**(建档 今−560d,唯一一单在 今−450d,之后无互动):
    五个时点 idle = 90 / 180 / 270 / 360 / 450
    → `活跃 → 休眠 → 潜在流失 → 潜在流失 → 流失`,当前 = 流失 → **GONE**
  这是一条**真实的衰退故事**:买过一次,再也没回来。

**B 组 → IMPROVING**(建档 今−760d,两单在 今−730 和 今−20):
    五个时点 idle = 370 / 460 / 550 / 640 / 20
    → `流失 → 流失 → 流失 → 流失 → 活跃`,最后一步在变好 → **IMPROVING**
  故事:**两年前买过一次,消失了,上个月回来了。**

**C 组 → SLIPPING,而且进「曾经是但现在没了」那个计数器**
(建档 今−760d,一笔**大单**在 今−400d、一笔小单在 今−200d):
    五个时点 idle = 40 / 130 / 20 / 110 / 200
    → `高价值 → 休眠 → 高价值 → 休眠 → 潜在流失`,当前 = 潜在流失 → **SLIPPING**
  故事:**买过一大笔,断断续续来过,然后半年多没动静。**

  ⚠️ **这一支原本指望 A 组的大单覆盖,2026-10-09 真库上验出来:指望不上。**
  A 组前 2 个客户的数据是**完全正确**的 —— 实测 C50000 / C50001:
      曾经是=['高价值'] · 现在还是=[] · `高价值→休眠→潜在流失→潜在流失→流失`
  但它们的码是 **GONE**,而 `churn.判` 给 GONE 的 `要不要预警` 是 **False**
  (那一支按设计是「超过一年,这不是预警是复盘」);
  `slipping_check` 统计「有多可惜」那三支时外面套着 `if w["要不要预警"]` ——
  **于是两个正确的样本被口径筛掉,那一支始终是 0。**

  > 一个「库里有了曾经是高价值而现在不是的客户」,
  > 和一个「覆盖报告里那一支不再缺样本」,**长得一模一样** ——
  > 中间隔着「要不要预警」这道筛子,而原来那段注释推到前者就停了。

  所以 C 组的末态**必须**停在「潜在流失」(181–365 天):
  早一天到 366 就成「流失」→ GONE → 不预警 → 又白造一批。
  参数的巧处是**一笔大单同时控两件事**:它让早先的时点命中「高价值」,
  又因为落在 400 天前而必然掉出最后一个时点的 365 天窗口 ——
  **金额的衰减不是另外造的,是窗口滚过去的自然结果**。
  (`backend/slipping_check.py` 里量过:全库「末值低于自己峰值」的人原来是 **0 个**。)

## ⚠️ 这批样本会不会过期 —— **我先写错过一次,记下来免得再错**

**第一版我写的是「会随世界时钟过期」:日期是「距今天几天」,而 `daily_shift.sh`
每天挪世界却不跑本脚本,所以 C 组再过 165 天就滑成流失。这是错的。**
并行会话当场指出来,核完确实是我错了:`shift_world` 把**所有登记过的日期列
整体往后挪**,世界的今天也跟着挪 —— **「距今天几天」是守恒的**,闲置天数不会每天 +1。

核的三条(都是实测,不是看列名猜的):

1. 现扫 `shift_world.扫列()` 的 128 个「整列日期」列,这批人判档要用的九列
   全在里面:`ordr.created / paid_at / finished_at` · `customer.created / last_interact`
   · `lifecycle_history.as_of / created` · `account.created` · `wearer.created`
2. 把 `lifecycle_history.as_of` 整体 +200 天再喂 `churn.判`,三支码一个没变
   (GONE / IMPROVING / SLIPPING)。因为判码用的 `idle_days / orders_12m /
   amount_12m / quarters_12m / lifecycle` **都是存下来的数**,平移只改 as_of 的文本,
   而 as_of 在那里只用来排序和取「最好那天」—— 整体平移不改次序。
3. 重算那条链(`lifecycle_refresh` → `某天的事实`)现算 idle,平移保留日期差。

> 一个「日期写死了所以会过期」的样本,和一个「日期跟着世界一起走」的,
> **在「脚本里写的是距今天几天」这句话上长得一模一样** ——
> 而我只看到前半句就下了结论,还把它写进了文件头和交接。

**端到端那一步没做**:`shift_world` 没有 `--db`,整库挪 200 天要另搭一套临时目录。
上面三条是独立的证据,但**不等于**端到端跑过一次。

## 真正会让它失效的是另一条路:每日上新抽到了这批人

`tools/daily_fresh.py` 从「**有过订单、不在受保护名单里**的客户」里抽人造新单,
而 **C5* 不在受保护名单**(那张名单是边界夹具 + 营销 SOP 保护清单)。
抽中一个 C 组客户 → 他有了新单 → 闲置天数变小 → 末态从「潜在流失」变「活跃」
→ 码不再是 SLIPPING → 那一支又缺样本。**这不是 bug**:一个老客户又来买了,
业务上完全合理;但它会把「为覆盖某支码而存在的样本」消耗掉。

概率:每天造 10–20 单、客户池 7000 多,C 组 3 个人每天被动到的概率约 0.6%,
**百来天就有一半的机会**。

**两个选项,没拍(2026-10-09 记)**:

    ① 把 C5* 加进受保护名单(`order_mix.受保护客户()`)—— 它们存在的目的就是
       「保持那几支码有样本」,被动了就失去意义,和边界夹具同一性质。
       代价:要动口径的单一源头,而别的地方也在用那张名单;
       而且 `lifecycle_refresh` 也跳过受保护客户(平移守恒,档位本来也不必重算)。
    ② 不动,等覆盖报告报「那一支没有样本」时重跑 `--做`。
       代价:中间那段时间覆盖报告是红的,而红的原因**看起来**像判定坏了。

**怎么发现**:`backend/slipping_check.py` 的覆盖报告报那一支「库里没有样本」。
**怎么修**:重跑 `--做` → 再跑 `lifecycle_history_seed.py --做`,**顺序不能颠倒**
(回滚会把这批人的档位历史一起删)。


## 今天踩过的坑,这里都带上了

  · `ordr.appt_src` **必须显式写「无预约」** —— 那一列有 `DEFAULT '未接入'`,
    不填 ≠ 空(业务硬规则:定制品必须有预约,标品全部不用)
  · 订单行要记 `pattern_version`(挂着版型的行不记会红)
  · **不写库存流水、不动 `sku`** —— 这些是**老日期**的单,而 `stock_check` 取链尾
    用的是 `MAX(ts)`,插一条老时间的流水会把链尾落到别人那行上
    (实测库里 91 张待付款单一张占用流水都没有,所以不是硬性要求)
  · 名字和手机号**不许和现有的重** —— 同名会进「疑似重复客户」队列,那是客户合并用例的地盘

## 验收不是「造了几个客户」

要跑 `knowledge/churn.判()`,**确认 GONE 和 IMPROVING 真的出现在码分布里**。
> 一个「造了 12 个流失客户」和一个「GONE 那一支真的触发了」,
> **在条数上长得一模一样。**
这个脚本自己在 `--做` 之后就跑这一条复查,不过它要先有档位历史,
所以完整顺序是:本脚本 → `lifecycle_history_seed --做` → `lifecycle_refresh --做`。
"""
import argparse
import datetime as dt
import os
import random
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
                os.path.join(ROOT, "fakedata")]

import lifecycle as LC        # noqa: E402
import order_mix as OM        # noqa: E402
import worldclock as W        # noqa: E402

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
DB = os.path.join(ROOT, "backend", "lanxiu.db")
for _i, _a in enumerate(sys.argv):
    if _a == "--db" and _i + 1 < len(sys.argv):
        DB = sys.argv[_i + 1]

SEED = 20261009
# 前缀就是来路,回滚按前缀删,不另建表(多一张表就要改文档里写着的数据表数)
前缀 = {"customer": "C5", "account": "U5", "wearer": "W5", "ordr": "CH"}
# A 组:买过一次再没回来 → GONE;B 组:沉默很久又回来了,而且越来越勤 → IMPROVING
A组, B组, C组 = 8, 4, 3
# ⚠️⚠️ **A 组前 2 个大单原本是为了覆盖第三支,2026-10-09 真库上验出来:它拿不到。**
#
# 那两个客户的数据是**完全正确**的 —— 真库实测 C50000 / C50001:
#     曾经是=['高价值'] · 现在还是=[] · 轨迹 高价值→休眠→潜在流失→潜在流失→流失
# 但它们的码是 **GONE**,而 `churn.判` 给 GONE 的 `要不要预警` 是 **False**
# (那一支按设计是「超过一年,这不是预警是复盘」)。
# `slipping_check` 统计「有多可惜」那三支时,外面套着 `if w["要不要预警"]` ——
# **于是这两个正确的样本被口径筛掉了,那一支还是 0。**
#
# > 一个「库里有了曾经是高价值而现在不是的客户」,
# > 和一个「覆盖报告里那一支不再缺样本」,**长得一模一样** ——
# > 中间隔着「要不要预警」这道筛子,而原来的注释推到前者就停了。
#
# 所以才有 C 组:末态必须停在「潜在流失」(181–365 天)让码变成 SLIPPING,
# 它才进得去那个计数器。A 组的大单保留不动 —— 它仍然是「买过一大笔再没回来」
# 这类客户的真实样本,只是**不负责**第三支的覆盖。
贵的几个 = 2
大单门槛 = 15500          # 高价值是「近 12 个月实付满 15000」,这里过一点
A单 = [450]                                  # 距今天几天
B单 = [730, 20]
# C 组:**用同一笔大单同时控两件事** —— 它让早先的时点命中「高价值」,
# 又因为落在 400 天前而必然掉出最后一个时点的 365 天窗口。
# 金额的衰减不是另外造的,是**窗口滚过去的自然结果**。
# 小单定在 200 天前:把末态的闲置天数压在 181–365 这个区间里 ——
# 早于 366 就成「流失」→ GONE → 不预警 → 又白造(见上面那段)。
C单 = [400, 200]
姓 = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许"


def 取名(rng, 用过):
    库 = ["承砚", "樟宁", "禾川", "岚屿", "砚之", "川禾", "屿宁", "宁砚", "砚川", "禾宁",
          "屿川", "岚砚", "之宁", "川屿", "宁禾", "砚屿", "岚川", "禾屿", "之砚", "宁屿"]
    for _ in range(400):
        n = rng.choice(姓) + rng.choice(库)
        if n not in 用过:
            用过.add(n)
            return n
    raise SystemExit("❌ 名字池取不完 —— 扩池,别兜底成重名(同名会进客户合并队列)")


def 取号(rng, 用过):
    for _ in range(4000):
        p = "15" + "".join(str(rng.randint(0, 9)) for _ in range(9))
        if p not in 用过:
            用过.add(p)
            return p
    raise SystemExit("❌ 手机号池取不完")


def 回滚(c, 说=print):
    """按前缀把这批人整条链删掉 —— **连他们的档位历史一起**。

    ⚠️ **档位历史必须跟着一起删,2026-10-09 差点栽在这上面。**
    第一版只删客户/账户/着装人/订单,留下 `lifecycle_history` 里那 60 条。
    那次之所以没出错,纯属**同种子重造把同样的 id 又造了回来**,历史正好对得上。
    可只要改一次参数(比如挪动 C 单的日期),客户就是新的、历史还是旧的 ——

    > 一份「刚算出来的历史」和一份「上一批留下的历史」,
    > **在复查读到的那几行上长得一模一样** ——
    > 而复查会拿**作废的**历史给新客户判码,然后告诉你验收通过。

    所以这里按 `customer_id` 前缀删。客户都删了,他的历史没有保留价值;
    不限定 `source`,因为 `lifecycle_refresh` 也会给他们落 `source='recalc'` 的行,
    那同样是这批人的。
    """
    n = 0
    n += c.execute("DELETE FROM lifecycle_history WHERE customer_id LIKE ?",
                   (前缀["customer"] + "%",)).rowcount
    for 表, p in (("ordr_item", None), ("ordr", 前缀["ordr"]),
                  ("wearer", 前缀["wearer"]), ("account", 前缀["account"]),
                  ("customer", 前缀["customer"])):
        if 表 == "ordr_item":
            n += c.execute("DELETE FROM ordr_item WHERE order_id LIKE ?",
                           (前缀["ordr"] + "%",)).rowcount
            continue
        n += c.execute(f"DELETE FROM {表} WHERE id LIKE ?", (p + "%",)).rowcount
    if n:
        说(f"  回滚:删掉 {n} 行(按前缀 {sorted(set(前缀.values()))} + 他们的档位历史)")
    return n


def 跑(c, 今, rng, 说=print):
    护 = OM.受保护客户(c)
    if len(护) < 14:
        说(f"❌ 受保护客户只扫出 {len(护)} 个 —— **扫挂了**,不造")
        return None
    店 = [r[0] for r in c.execute("SELECT DISTINCT shop FROM ordr WHERE shop IS NOT NULL ORDER BY 1")]
    顾问 = {s: [r[0] for r in c.execute(
        "SELECT no FROM staff WHERE role='顾问' AND status='启用' AND shop=? ORDER BY no", (s,))]
        for s in 店}
    店 = [s for s in 店 if 顾问.get(s)]
    skus = [dict(r) for r in c.execute(
        """SELECT s.code, s.spu, p.name, s.price, p.pattern, t.version pv
             FROM sku s JOIN product p ON p.spu=s.spu
             LEFT JOIN pattern t ON t.code=p.pattern
            WHERE s.status='启用' AND p.status='上架' AND p.kind='标品'
              AND s.price BETWEEN 600 AND 1600 ORDER BY s.code""")]
    if len(skus) < 10 or not 店:
        说(f"❌ 候选不够:SKU {len(skus)} / 店 {len(店)} —— **取数取空了,不是「没什么可造」**")
        return None
    用名 = {r[0] for r in c.execute("SELECT name FROM customer")}
    用号 = ({r[0] for r in c.execute("SELECT phone FROM customer")}
            | {r[0] for r in c.execute("SELECT phone FROM account")})
    计 = {"客户": 0, "账户": 0, "着装人": 0, "订单": 0, "订单行": 0}

    for i in range(A组 + B组 + C组):
        是A = i < A组
        是C = i >= A组 + B组
        建档 = 今 - dt.timedelta(days=560 if 是A else 760)
        单们 = A单 if 是A else (C单 if 是C else B单)
        cid = f"{前缀['customer']}{i:04d}"
        aid = f"{前缀['account']}{i:04d}"
        wid = f"{前缀['wearer']}{i:04d}-0"
        nm, ph = 取名(rng, 用名), 取号(rng, 用号)
        sh = rng.choice(店)
        adv = rng.choice(顾问[sh])
        生 = f"19{rng.randint(70, 92)}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}"
        性 = rng.choice(["女", "女", "男"])
        addr = f"上海市{rng.choice(['静安','徐汇','黄浦','长宁'])}区{rng.randint(1,999)}号"
        c.execute("""INSERT INTO account(id,phone,status,created,display_name,contact_pref,
                       default_addr,home_shop,self_wearer_id,tos_version,privacy_version)
                     VALUES(?,?,'正常',?,?,'短信',?,?,?,'v2.3','v1.4')""",
                  (aid, ph, 建档.isoformat(), nm, addr, sh, wid))
        计["账户"] += 1
        c.execute("""INSERT INTO customer(id,name,phone,phone_tail,shop,advisor_no,level,
                       created,addr,birthday,gender,province,city,district,account_id,
                       email,wechat,archived)
                     VALUES(?,?,?,?,?,?,'普通',?,?,?,?,'上海市','上海市',?,?,?,?,0)""",
                  (cid, nm, ph, ph[-4:], sh, adv, 建档.isoformat(), addr, 生, 性,
                   addr[3:6], aid, f"{cid.lower()}@163.com", f"wx_{cid.lower()}"))
        计["客户"] += 1
        c.execute("""INSERT INTO wearer(id,customer_id,account_id,name,gender,birthday,
                       relation,phone,height,status,created)
                     VALUES(?,?,?,?,?,?,'本人',?,?,'在用',?)""",
                  (wid, cid, aid, nm, 性, 生, ph,
                   round(rng.uniform(155, 178), 1), 建档.isoformat()))
        计["着装人"] += 1
        for j, 距 in enumerate(单们):
            d = 今 - dt.timedelta(days=距)
            s = rng.choice(skus)
            时 = f"{d.isoformat()} {rng.randint(10,19):02d}:{rng.randint(10,59)}"
            oid = f"{前缀['ordr']}{i:03d}{j}"
            件 = 1
            if (是A and i < 贵的几个) or (是C and j == 0):
                # 件数算出来,**不写死金额** —— 写死的那天 SKU 价格一变就对不上了
                件 = int(大单门槛 // float(s["price"])) + 1
            金 = round(float(s["price"]) * 件, 2)
            # ⚠️ `appt_src` 必须显式写「无预约」—— 那一列有 DEFAULT '未接入'(今天栽过)
            c.execute("""INSERT INTO ordr(id,customer_id,kind,status,shop,source,delivery,
                          amount,payable,created,updated,prd_status,goods_amount,freight,
                          received,refund_status,paid_at,shipped_at,finished_at,advisor_no,appt_src)
                         VALUES(?,?,'标品订单','完成',?,'门店 Pad','配送到店',?,?,?,?,'已完成',
                                ?,0,?,'未退款',?,?,?,?,'无预约')""",
                      (oid, cid, sh, 金, 金, 时, 时, 金, 金, 时, 时, 时, adv))
            计["订单"] += 1
            c.execute("""INSERT INTO ordr_item(order_id,sku,name,tag,price,qty,spu,
                           base_amount,custom_amount,total,pattern_version,pattern_version_src)
                         VALUES(?,?,?,'标品',?,?,?,?,0,?,?,?)""",
                      (oid, s["code"], s["name"], float(s["price"]), 件, s["spu"], 金, 金, s["pv"],
                       f"造流失老客户:取下单那一刻版型的当前版本" if s["pv"] is not None else None))
            计["订单行"] += 1
        # 汇总字段按**同一套算法**算,不手填 —— 手填的和算出来的在那一行上长得一样
        行 = dict(c.execute("SELECT * FROM customer WHERE id=?", (cid,)).fetchone())
        写回, 事实 = OM.某天的事实(c, 行, 今)
        d = LC.decide(事实)
        列 = dict(写回, lifecycle=d["生命周期"], matched="/".join(d["命中"]))
        c.execute("UPDATE customer SET " + ",".join(f"{k}=?" for k in 列) + " WHERE id=?",
                  [列[k] for k in 列] + [cid])
    return 计


def 复查(c, 今, 说=print):
    """**验收按码分布看,不按客户个数。**"""
    import churn as CH
    坏 = 0
    档 = dict(c.execute("SELECT lifecycle, count(*) FROM customer WHERE id LIKE ? GROUP BY 1",
                        (前缀["customer"] + "%",)).fetchall())
    说(f"  造出来的 {sum(档.values())} 个客户当前档位:{档}")
    流 = 档.get("流失", 0)
    说(f"  {'✅' if 流 else '❌'} 其中「流失」{流} 个(A 组该全是流失,要 ≥1)")
    坏 += (not 流)
    有史 = c.execute("""SELECT count(DISTINCT customer_id) FROM lifecycle_history
                         WHERE customer_id LIKE ?""", (前缀["customer"] + "%",)).fetchone()[0]
    # ⚠️ **判的是「是不是都有」,不是「有没有任何一个」。**
    # 第一版写的是 `if not 有史`,于是 12 个人有历史、新加的 3 个没有时,
    # 它**不走**这条提示,而是拿不完整的历史算了码分布 —— 报「SLIPPING 0 个」。
    # > 一批「人人都有历史」和一批「只有一部分有」,
    # > **在「有史 > 0」这个判据上长得一模一样** —— 而后者算出来的码分布是假的。
    应有 = sum(档.values())
    if 有史 < 应有:
        说(f"  {Y}·{D} 有档位历史的只有 {有史}/{应有} 个 —— "
           f"先跑 tools/lifecycle_history_seed.py --做,再回来跑本脚本的复查"
           f"(码分布要**人人都有**历史才算得准;只有一部分时算出来的是假的)")
        return 坏
    码, 可惜 = {}, 0
    for cid, in c.execute("SELECT DISTINCT customer_id FROM lifecycle_history WHERE customer_id LIKE ?",
                          (前缀["customer"] + "%",)):
        行 = [dict(r) for r in c.execute(
            "SELECT * FROM lifecycle_history WHERE customer_id=? ORDER BY as_of", (cid,))]
        w = CH.判(行)
        码[w["码"]] = 码.get(w["码"], 0) + 1
        # ⚠️ **这一条必须带上 `要不要预警`,否则复查会绿而覆盖报告仍然缺样本。**
        # 见文件头:A 组那两个大单客户 曾经是=['高价值'] / 现在还是=[] 是**对的**,
        # 可它们的码是 GONE(不预警),`slipping_check` 统计那三支时外面套着
        # `if w["要不要预警"]` —— 于是正确的样本被口径筛掉了。
        # 这里照抄它的口径,**连那道筛子一起抄**,才是真的在验同一件事。
        if w["要不要预警"] and w["曾经是"] and not w["现在还是"]:
            可惜 += 1
    说(f"  这批客户的码分布:{码}")
    for 要 in ("GONE", "IMPROVING", "SLIPPING"):
        有 = 码.get(要, 0)
        说(f"  {'✅' if 有 else '❌'} {要}:{有} 个")
        坏 += (not 有)
    说(f"  {'✅' if 可惜 else '❌'} 真进了「曾经是但现在没了」那个计数器的:{可惜} 个"
       f"(C 组 {C组} 个该全在里面)")
    坏 += (not 可惜)
    说(f"      ← **验收按码分布看,不按客户个数** ——"
       f"「造了 12 个流失客户」和「GONE 真的触发了」在条数上长得一模一样;"
       f"最后那一条还要再过一道「要不要预警」,见上面的注释")
    return 坏


def main():
    ap = argparse.ArgumentParser(description="造真正流失过的老客户(可按前缀回滚)")
    ap.add_argument("--做", action="store_true", dest="做")
    ap.add_argument("--回滚", action="store_true", dest="回滚")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    if not os.path.exists(DB):
        print(f"❌ 没有库 {DB}")
        return 1
    今 = W.今天()
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    print(f"世界的今天 {今} · 要造 A 组(→GONE) {A组} 个 · "
          f"B 组(→IMPROVING) {B组} 个 · C 组(→SLIPPING,曾经是高价值) {C组} 个")
    if a.回滚:
        with c:
            n = 回滚(c)
        print("✅ 回滚完成" if n else f"{Y}·{D} 本来就没有")
        return 0
    已有 = c.execute("SELECT count(*) FROM customer WHERE id LIKE ?",
                     (前缀["customer"] + "%",)).fetchone()[0]
    if not a.做:
        print(f"  库里已有 {已有} 个 {前缀['customer']}* 客户 —— 真跑会**先回滚再重造**(同种子)")
        print(f"{Y}只看不做{D}。真写加 --做")
        return 0
    with c:
        回滚(c)                    # 幂等:先撤再造,不是「有了就跳过」
        计 = 跑(c, 今, random.Random(SEED))
        if 计 is None:
            c.rollback()
            return 1
    print("  造了:" + " · ".join(f"{k} {v}" for k, v in 计.items()))
    坏 = 复查(c, 今)
    if 坏:
        print(f"{R}❌ 复查 {坏} 处不对{D}")
        return 1
    print(f"{G}✅ 老客户造好了{D}")
    print(f"{Y}下一步{D}:tools/lifecycle_history_seed.py --做 → tools/lifecycle_refresh.py --做")
    return 0


if __name__ == "__main__":
    sys.exit(main())
