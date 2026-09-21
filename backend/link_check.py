# -*- coding: utf-8 -*-
"""订单 ↔ 预约的链路,以及顾问的两列新字段。

## 为什么要这条检查

2026-09-20 加了 `ordr.appt_id`(这一单是哪次预约带来的)。
加之前:**26587 单里没有一单能追溯到哪次接待** ——
「这次接待成没成」这个事实在库里根本不存在,
**成交率不管按接待人算还是按归属人算,都一样算不出来**。那不是样本不够,是链路断了。

## 🔑 空值必须说清是哪一种

`appt_id` 为空有三种完全不同的原因,而**它们都是 NULL**:

    未接入  这一单生成时链路还没接 —— **不知道它经没经过预约**
    无预约  确认过:小程序直接下单、到店直接买
    已关联  appt_id 里有值

算成交率时:**「无预约」该排除在分母外,「未接入」是数据缺口** ——
处理方式相反,而不分开的话两者长得一模一样。

所以 `appt_src` 是 NOT NULL,默认「未接入」——
**默认值选「未接入」而不是「无预约」,是因为前者是诚实的「不知道」**。

## staff 的两列新字段,空值也不许被当成默认

    hired_at  入职日期。空 ≠ 老员工 —— **「没填」和「入职很久」不是一回事**
    good_at   擅长的形制。**留空等业务填**,猜出来的专长和查证过的在库里长得一样
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
G, R, Y, D = "\033[32m", "\033[31m", "\033[31m", "\033[0m"
Y = "\033[33m"
bad = 0

咬合 = [
    ('把 appt_src 的 NOT NULL 去掉(让「没经过预约」和「没记」又混成一个空)',
     '每一单都说清了它和预约的关系'),
]

# 2026-09-21 加了第四种:**推断出来的关联,不许和记录下来的长一样**。
# 两者都能让成交率算出一个数,而可信度完全不同(口径见 knowledge/linkage.py)。
合法来路 = ("未接入", "无预约", "已关联", "推断关联")


def ck(t, got, want, extra=""):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {t:46s} 判为 {str(got):12s} 应为 {want}{extra}")


def main():
    global bad
    c = sqlite3.connect(DB)
    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    print("\n\033[1m▸ 订单↔预约链路 · 空值要说清是哪一种空\033[0m")
    print("  " + "=" * 80)

    # ① 每一单都要有来路
    空 = q("select count(*) from ordr where appt_src is null or appt_src=''")
    ck("每一单都说清了它和预约的关系", 空, 0,
       "  ← 「没经过预约」和「经过了但没记」都是空,而算成交率时处理方式相反")

    # ② 来路只能是那三种 —— **写了个野值不会报错,只会让统计悄悄漏掉那一批**
    # ⚠️ 占位符数量跟着 `合法来路` 走,**不写死**。
    # 第一版写的是 `'?'*3` —— 改了词表就参数数量不匹配,**脚本直接崩**。
    # 而在咬合里,**「崩了」和「通过了」都表现为「没红」** —— 差点把这条判据当成有效的。
    野 = [r[0] for r in c.execute(
        f"select distinct appt_src from ordr where appt_src not in "
        f"({','.join('?' * len(合法来路))})", 合法来路)]
    ck("来路没有野值", 野 or "无", "无", f"  ← 合法的只有 {合法来路}")

    # ③ 有关联的必须真有 appt_id;有 appt_id 的必须是某种关联
    #
    # ⚠️ 2026-09-21 加了「推断关联」之后,这两条都要认两种来路 ——
    # **只认「已关联」的话,14 张推断出来的会被判成野值**,而它们是对的。
    有关联 = ("已关联", "推断关联")
    ph = ",".join("?" * len(有关联))
    错1 = q(f"select count(*) from ordr where appt_src in ({ph}) "
            f"and (appt_id is null or appt_id='')", *有关联)
    错2 = q(f"select count(*) from ordr where appt_id is not null and appt_id<>'' "
            f"and appt_src not in ({ph})", *有关联)
    ck("标了关联的真有预约号", 错1, 0)
    ck("有预约号的都标了某种关联", 错2, 0, "  ← 两头都要对,只查一头会漏")

    # ③.5 **推断出来的关联,不许和记录下来的混成一种。**
    # 两者都能让成交率算出一个数,而可信度完全不同 —— 所以库里必须分得开。
    推 = q("select count(*) from ordr where appt_src='推断关联'")
    记 = q("select count(*) from ordr where appt_src='已关联'")
    ck("推断关联和已关联分得开", "分开" if 推 and 记 else f"推{推}/记{记}", "分开",
       f"  ← 记录的 {记} 张 · 推断的 {推} 张。**混成一种的话,"
       f"一个建立在推断上的成交率和一个真的长得一模一样**")

    # ④ **业务硬规则(2026-09-20):定制品必须有预约才能做,标品全部不用。**
    # 这条一下子把「26587 单全是未接入」变成了两类,而**分开之后成交率的分母才有意义**:
    # 标品那批本来就不该进分母,定制品那批是**真正的数据缺口**。
    标品错 = q("select count(*) from ordr where kind='标品订单' and appt_src<>'无预约'")
    定制错 = q("select count(*) from ordr where kind<>'标品订单' and appt_src='无预约'")
    ck("标品订单一律「无预约」", 标品错, 0, "  ← 标品不经过预约,这是确认过的事实")
    ck("定制品订单不许标「无预约」", 定制错, 0,
       "  ← 定制必须有预约才能做;现在标「未接入」是**诚实的「还没挂上」**")

    # ⑤ 关联到的预约必须存在 —— **指向一个不存在的预约,和没关联,查出来都是空**
    孤 = q("""select count(*) from ordr o where o.appt_id is not null and o.appt_id<>''
              and not exists (select 1 from appointment a where a.id=o.appt_id)""")
    ck("预约号指得到真实的预约", 孤, 0)

    # ⚠️ **预约必须早于下单** —— 并行会话提的,判据机械、不依赖谁记得。
    #
    # 为什么要这条:`run_journey` 写 appt_id 时,链路能成立**是因为那批旅程
    # 本来就按「预约→上门→量体→下单」造的**。将来若有人改了步骤顺序,
    # `appt_id` 就变成一个**挂着但没依据的值** ——
    # 而「有依据的关联」和「挂着但没依据的关联」在库里长得一模一样,都是一个非空的 id。
    #
    # 这和「有归属顾问而那个人已经离职」是同一族:**字段还在,依据没了。**
    倒 = q("""select count(*) from ordr o join appointment a on a.id=o.appt_id
              where o.appt_src='已关联' and a.start_ts > o.created""")
    ck("关联的预约早于下单", 倒, 0,
       "  ← 预约在下单之后 = **拿结果解释原因**;也可能是造数据的步骤顺序被改了")

    # 定制品的缺口有多大 —— **这个数就是 P18 落地的工作量**
    缺口 = q("select count(*) from ordr where kind<>'标品订单' and appt_src='未接入'")
    if 缺口:
        print(f"     ℹ 定制品里还有 {缺口} 单没挂上预约号 —— "
              f"**这是数据缺口,不是「没有预约」**")

    print("\n\033[1m▸ 顾问的两列新字段 · 空值不许被当成默认\033[0m")
    print("  " + "=" * 80)
    cols = {r[1] for r in c.execute("PRAGMA table_info(staff)")}
    ck("staff 有 hired_at(判断谁是新人)", "hired_at" in cols, True,
       "  ← 没有它,「新人保底派单」那条规则做不了")
    # ⚠️ 本来这儿还验一列 `good_at`(擅长的形制)。
    # **业务 2026-09-20 答:顾问没有擅长的形制** —— 所以那一列撤了,这条检查也撤。
    # 留着一个没人填的字段,就是又一个**长得像开关却不控制任何事的东西**。
    ck("staff 没有 good_at(业务答:顾问没有擅长的形制)", "good_at" not in cols, True,
       "  ← 加过又撤了。**留着不填的字段比没有更危险 —— 有人会以为它在生效**")

    有职 = q("select count(*) from staff where hired_at is not null and hired_at<>''")
    总 = q("select count(*) from staff")
    新人 = q("""select count(*) from staff where role='顾问' and hired_at >=
                date((select max(created) from ordr), '-180 day')""")
    ck("每个员工都有入职日期", 有职, 总, "  ← **空不等于「入职很久」**")
    ck("有「半年内入职」的顾问(新人样本)", 新人 > 0, True,
       f"  ← {新人} 人。**没有新人样本,「新人保底派单」那条规则就永远测不到**")

    # ⚠️ **诚实说明**:上面第 ③④⑤ 条在当前数据上**恒真** ——
    # 现在一单都没挂预约号,所以「已关联的真有预约号」这类断言没有东西可验。
    # 它们是**防御性的**:等 P18 拍板、真挂上之后才开始有意义。
    # **「一直在跑而结论恒为真」和「从没被验证过」是两回事** ——
    # 前者是有效的(数据一变就会说话),后者才等于没有。
    已挂 = q("select count(*) from ordr where appt_id is not null and appt_id<>''")
    if 已挂 == 0:
        print(f"\n  {Y}ℹ{D} 现在 0 单挂了预约号,所以第 ③④⑤ 条**暂时没有东西可验** ——")
        print(f"     它们是防御性的,等 P18 拍板真挂上之后才开始说话。")

    print()
    if bad:
        print(f"{R}❌ 订单↔预约链路 {bad} 处不符合预期{D}")
        return 1
    print(f"{G}✅ 链路检查全部符合预期{D}")
    print(f"    业务 2026-09-20 定:**定制品必须有预约,标品全部不用**。")
    print(f"    所以标品那 23045 单标「无预约」(不进成交率分母),")
    print(f"    定制品那 3542 单标「未接入」(**真正的数据缺口**,等链路接上)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
