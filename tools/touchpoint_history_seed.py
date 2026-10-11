#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造三类接待触点(预约 / 到店流水 / 跟进)—— **幂等,分批写**。

    python3 tools/touchpoint_history_seed.py          # 只看
    python3 tools/touchpoint_history_seed.py --做     # 真写

## 为什么要单独成一步

这三张表里的历史原来**只由 `fakedata/mkt_sop_seed.py` 顺带造**,而那个脚本
**不在 `tools/rebuild.sh` 的配方里**。不在的理由写在隔壁
(`tools/lifecycle_history_seed.py` 模块头):

> `mkt_sop_seed` 没法直接进配方:它不幂等(重跑撞 `appointment.id` 唯一约束)。

后果 2026-10-10 当场验到了:库从零重建一次之后

    appointment  17456 → 79      schedule  17587 → 220      followup  10461 → 30

剩下的全是夹具。周报的「进店客流」从 70 掉到 0 ——
**而重建脚本 37 步一步没少、`./check.sh` 全绿**。

> 一个「这个功能取数都对」的绿勾,和一个「库里这个功能的数据根本不存在」的,
> **长得一模一样。**

这和 `lifecycle_history` 当初是同一道题,所以用同一个解法:
**把那一段抽出来、做成幂等的、放进配方**,而不是把整个造数脚本塞进去。

## 照搬的三件事 —— **它们看起来像错,其实是功能**

**① `schedule.type='到店'`,一个不在 `tasktypes` 目录里的值。**
`tasktypes.info('到店')` 返回 `None`,而 `seed.py` 还 assert 过
「种子不许用 tasktypes 里没有的类型」。看着像写错了。但配方里有三个脚本
**靠它当排除标记**(`tools/seed_dispatch.py` 把理由写在明处):

    type='到店'  17374 行 ← **接待记录**(客户来过店的流水),end_ts 全是 NULL
    其余          93 行 ← 真正派给人的任务(有 end_ts、有 assignee_no)
    → 按周统计派单量不加 `type<>'到店'`,数字会被 17374 条接待记录淹没

`tools/seed_customer_tasks.py`、`tools/shift_e2e.py` 也都在 `where type<>'到店'`。
**把它"修"成 `预约到店`,等于把 17374 条接待流水灌进派单统计** ——
而那种错不会让任何检查变红,只会让看板上的数字变错。

**② `status='已完成'`**,也不在日程状态机(有效/完结/取消/无效)里。同①:
它是接待流水的状态,不是任务的状态。

**③ `schedule.end_ts` 空着。** 接待不是一段要排的工时,没有「排到几点」。

> 区分「刻意的怪值」和「真的写错了」,**只能去看谁在消费这个字段** ——
> 看字段本身像不像对,看不出来。

## 修掉的一件事:接待顾问跨店

旧数据的顾问是「全库前 20 个顾问轮流发牌」,而门店跟着订单走,两者毫无关系。
结果 **17374 条里 10039 条(58%)的接待顾问属于另一家店**(82 条夹具预约:0 条)。
`backend/ownership.py` 把「门店」和「接待人」并排报出来,于是它会显示成
「客户在静安旗舰店接待,接待人是徐汇店的顾问」。

现在顾问直接取**这一单自己的** `ordr.advisor_no` —— 实测 31708 单里
顾问为空 0 条、顾问跨店 0 条,所以这样取天然一致,顺带还换来了真实的忙闲差别
(轮流发牌造出的是每人精确 1930 条)。

## 时间的上下界

    下界:客户建档日   —— 触点不能早于这个人存在(spec_check C3)
    上界:世界的今天   —— 已经发生的事不许落在未来(spec_check C4)

C4 那条的代价值得抄在这儿:生命周期按「多久没互动」算,
**负数天数会把客户算成永远活跃** —— 而这批数据正是喂流失预警的。

## 为什么分批写(用户 2026-10-11 定)

`backend/lanxiu.db` 是**共享库**:同一台机器上有同步循环(每 30 秒写一次)、
后端 `server.py`、站点 `app.py` 同时连着,而库是 `journal_mode=delete` ——
写的时候整库加锁,连读也要等,各连接默认只等 5 秒。
一个大事务一口气写两万多行会把库锁住几秒到几十秒,
**登录、页面、同步循环在这期间全报 `database is locked`**。

所以:每 500 条 commit 一次、`busy_timeout=30000`、某一批撞锁就重试那一批。
**不切 WAL** —— 那是对库文件的永久改动,没评估过,用户没批。

## 幂等是「先删自己那批再重算」,不是「有了就跳过」

独占 `SYN-` 前缀(沿用 `mkt_sop_seed` 的那个标记:同一批数据、同一个清理把手,
两个前缀会变成两批互相清不掉的数据)。跳过的话改完代码再跑拿不到新结果,
而**「跳过了」和「跑过了」在输出上长得一模一样**。

插入用 `INSERT OR IGNORE`:上一轮写到一半被锁断掉,下一轮接着写而不是撞主键。
id 是确定性的(序号),所以「接着写」和「重新写」结果一致。
"""
import argparse
import datetime as dt
import os
import random
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]

import order_mix as OM        # noqa: E402  受保护客户只有这一份口径
import worldclock as W        # noqa: E402  世界的今天只有这一份来源

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
DB = os.path.join(ROOT, "backend", "lanxiu.db")
for _i, _a in enumerate(sys.argv):
    if _a == "--db" and _i + 1 < len(sys.argv):
        DB = sys.argv[_i + 1]

种子 = 20261011
标记 = "SYN-"            # 本脚本独占;幂等靠它
批大小 = 500             # 共享库,别一个大事务锁住所有人
等锁毫秒 = 30000
重试上限 = 6
挑中比例 = 0.55          # 和原来一致:约一半的单前面补一段接待
跟进每十条 = 6           # 十条里六条带跟进(原来的 n % 10 < 6)
# 样本量下限。**不是「大概这么多」,是「少于这个数就说明取数取空了」** ——
# 实测 31708 单 × 0.55 ≈ 17400,掉到四位数以下只可能是 join 断了或名单滤过头。
最少要补 = 5000


def _连(库):
    """连库。**`timeout` 要在这里给** —— 给晚了第一条语句就已经按 5 秒超时了。"""
    c = sqlite3.connect(库, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute(f"PRAGMA busy_timeout={等锁毫秒}")
    return c


def _世界今天(c):
    """世界的日期。走 `worldclock`,并**和自己这条连接读到的值对一遍**。

    ⚠️ 两者不等就当场炸:`worldclock` 读的是默认库,而 `--db` 可以指到别处 ——
    那时候「按哪个世界的今天截断」会静静地用错一个世界。
    """
    今 = W.今天()
    r = c.execute("select v from world_meta where k='world_today'").fetchone()
    if not r:
        raise SystemExit(f"{R}❌{D} 库里没有 world_meta.world_today —— 先跑 tools/shift_world.py")
    库里 = dt.date.fromisoformat(str(r[0])[:10])
    if 库里 != 今:
        raise SystemExit(f"{R}❌{D} worldclock 说今天是 {今},而这个库里写的是 {库里} —— "
                         f"**两个世界**,不猜哪个对")
    return 今


def 要补的单(c, rnd, 说=print):
    """挑出要在前面补一段接待的订单。

    ⚠️ **带上 `cu.created`(客户建档时间)** —— 它是触点的下界。原版第一版没查它,
    下界那段又包了 `try/except: pass`,于是 KeyError 被静静吞掉、
    **下界形同虚设**,`spec_check` C3 红了预约 2308 条、日程 2281 条早于客户建档。
    > 一个「下界生效了」的造数,和一个「取字段失败被吞掉」的,
    > **在它跑完不报错这件事上长得一模一样。**
    """
    护 = OM.受保护客户(c)
    # ⚠️ 受保护客户**整批排掉,覆盖样本也排掉**。他们的互动历史本身就是夹具:
    # 给一个「摆在那里当流失靶子」的客户补上跟进,夹具就不再是靶子了 ——
    # 而这种破法不会让检查变红,只会让它再也测不到东西。
    # (`lifecycle_history_seed` 反过来要把覆盖样本捞回来,因为它算的是档位历史,
    #  不是造新互动 —— 同一份名单,两个用法,别抄错方向。)
    if len(护) < 14:
        说(f"{R}❌{D} 受保护客户只扫出 {len(护)} 个 —— **扫挂了,不是「没有夹具」**,不算")
        return None, None
    单们 = c.execute(
        "select o.id, o.customer_id, o.created, o.shop, o.advisor_no, "
        "       cu.created cu_created "
        "  from ordr o join customer cu on cu.id = o.customer_id "
        " where o.customer_id is not null and o.created is not null "
        "   and o.advisor_no is not null and o.shop is not null "
        " order by o.id").fetchall()
    单们 = [r for r in 单们 if r["customer_id"] not in 护]
    # 取数顺序固定(order by o.id),所以同一个种子挑中的是同一批
    补 = [r for r in 单们 if rnd.random() < 挑中比例]
    说(f"可用订单 {len(单们)} 单(受保护 {len(护)} 个客户不碰)· 挑中 {len(补)} 单")
    return 补, 护


def 生成(补, 今, rnd):
    """**纯算,不碰库。** 产出三张表要插的行。

    预约 → 到店流水 → (跟进) → 下单:顺序对得上,不是随机撒。
    """
    预约, 日程, 跟进 = [], [], []
    for n, r in enumerate(补, start=1):
        下单日 = dt.date.fromisoformat(str(r["created"])[:10])
        # ⚠️ **不包 try/except** —— 缺 cu_created 就该当场炸(见 要补的单 的注释)
        建档 = dt.date.fromisoformat(str(r["cu_created"])[:10])
        约日 = 下单日 - dt.timedelta(days=rnd.randint(20, 60))
        if 约日 < 建档:
            约日 = 建档
        if 约日 > 今:
            约日 = 今
        日程日 = 约日 + dt.timedelta(days=rnd.randint(1, 5))
        if 日程日 > 下单日:
            日程日 = 下单日
        if 日程日 > 今:
            日程日 = 今
        aid = f"{标记}AP{n:06d}"
        顾问 = r["advisor_no"]      # 这一单自己的顾问 —— 和 o.shop 天然同店
        门店 = r["shop"]
        # ⚠️ **`checkin_ts` 必须给。** 状态是「已完成」而没有签到时间,
        # `link_check` 那条「到店/完成的预约都有签到时间」会红。
        # > 一条「状态=已完成」而没有签到时间的预约,和一条真完成了的,
        # > **在那个状态字段上长得一模一样** —— 而「她到底来没来」只有签到时间能证明。
        预约.append((aid, r["customer_id"], 门店, 顾问,
                     f"{约日:%Y-%m-%d} 10:00", "已完成", f"{约日:%Y-%m-%d} 10:05"))
        # 到店流水:type/status/end_ts 照搬,理由见模块头「照搬的三件事」
        日程.append((f"{标记}SC{n:06d}", "到店", 顾问, r["customer_id"],
                     f"{日程日:%Y-%m-%d} 10:30", "已完成", r["customer_id"]))
        if n % 10 < 跟进每十条:
            跟日 = 日程日 + dt.timedelta(days=rnd.randint(1, 10))
            if 跟日 > 今:
                跟日 = 今
            跟进.append((f"{标记}FU{n:06d}", r["customer_id"], aid,
                         f"{跟日:%Y-%m-%d} 15:00", "电话", "方案跟进(造)", 顾问))
    return 预约, 日程, 跟进


def _批写(c, sql, 行们, 名, 说=print):
    """分批 commit + 撞锁重试。返回 (写了, 撞锁次数, 重试次数)。

    ⚠️ **`INSERT OR IGNORE`**:上一轮写到一半被锁断掉,下一轮接着写而不是撞主键。
    id 确定性,所以「接着写」和「重新写」结果一致。
    """
    撞, 重 = 0, 0
    for i in range(0, len(行们), 批大小):
        批 = 行们[i:i + 批大小]
        for 次 in range(重试上限):
            try:
                c.executemany(sql, 批)
                c.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" not in str(e) and "busy" not in str(e):
                    raise
                c.rollback()
                撞 += 1
                重 += 1
                等 = 1.5 * (次 + 1)
                说(f"  {Y}·{D} {名} 第 {i // 批大小 + 1} 批撞锁,等 {等:.1f}s 再来(第 {次 + 1} 次)")
                time.sleep(等)
        else:
            raise SystemExit(f"{R}❌{D} {名} 有一批重试 {重试上限} 次还在撞锁 —— "
                             f"**不往下写**。已写进去的是完整的批,再跑一次会接着写")
    return len(行们), 撞, 重


def 删自己那批(c, 说=print):
    """幂等的那一半:**先删自己那批**。也分批删 —— 一条 DELETE 删两万行同样锁库。"""
    总 = 0
    for 表, 前缀 in (("followup", f"{标记}FU%"), ("appointment", f"{标记}AP%"),
                    ("schedule", f"{标记}SC%")):
        # ⚠️ followup 先删:它的 appt_id 指着 appointment。虽然没有外键约束,
        # 但中途断掉时「跟进挂着一个已经不在的预约」比反过来更难看出来。
        n = c.execute(f"select count(*) from {表} where id like ?", (前缀,)).fetchone()[0]
        while True:
            cur = c.execute(
                f"delete from {表} where rowid in "
                f"(select rowid from {表} where id like ? limit {批大小})", (前缀,))
            c.commit()
            if not cur.rowcount:
                break
        说(f"  删掉旧的 {表} {n} 条")
        总 += n
    return 总


def 复查(c, 今, 说=print):
    """写完当场自己核 —— **「写进去了」和「写对了」是两件事。**"""
    坏 = 0

    def ck(名, 实, 应, 补=""):
        nonlocal 坏
        行 = 实 == 应
        说(f"  {'✅' if 行 else '❌'} {名}:{实}(应为 {应})")
        if 补 and not 行:
            说(f"      {补}")
        坏 += (not 行)

    q = lambda s, *a: c.execute(s, a).fetchone()[0]       # noqa: E731
    ck("接待顾问属于另一家店的预约",
       q("""select count(*) from appointment a join staff s on s.no=a.advisor_no
             where a.id like ? and s.shop <> a.shop""", f"{标记}AP%"), 0,
       "← ownership 会把「门店」和「接待人」并排报出来,跨店会显示成一句胡话")
    ck("早于客户建档的预约",
       q("""select count(*) from appointment a join customer cu on cu.id=a.customer_id
             where a.id like ? and substr(a.start_ts,1,10) < substr(cu.created,1,10)""",
         f"{标记}AP%"), 0, "← spec_check C3:那时候这个人还不存在")
    ck("落在世界今天之后的预约",
       q("select count(*) from appointment where id like ? and substr(start_ts,1,10) > ?",
         f"{标记}AP%", 今.isoformat()), 0,
       "← spec_check C4:已经发生的事不许在未来,负数天数会把客户算成永远活跃")
    ck("状态已完成而没有签到时间的预约",
       q("""select count(*) from appointment where id like ?
             and status='已完成' and (checkin_ts is null or checkin_ts='')""",
         f"{标记}AP%"), 0, "← link_check:「她到底来没来」只有签到时间能证明")
    ck("跟进挂着一个不存在的预约",
       q("""select count(*) from followup f where f.id like ?
             and f.appt_id is not null
             and not exists(select 1 from appointment a where a.id=f.appt_id)""",
         f"{标记}FU%"), 0)
    ck("到店流水被写成了别的类型",
       q("select count(*) from schedule where id like ? and type<>'到店'", f"{标记}SC%"), 0,
       "← 配方里三个脚本靠 type='到店' 把接待流水从派单统计里排除掉")

    预 = q("select count(*) from appointment where id like ?", f"{标记}AP%")
    日 = q("select count(*) from schedule where id like ?", f"{标记}SC%")
    跟 = q("select count(*) from followup where id like ?", f"{标记}FU%")
    人 = q("select count(distinct customer_id) from appointment where id like ?", f"{标记}AP%")
    说(f"  本批:预约 {预} · 到店流水 {日} · 跟进 {跟} · 覆盖 {人} 个客户")
    # **样本量判据**:0 条也能让上面每一项都 ✅ —— 那正是这一步存在要防的事。
    够 = 预 >= 最少要补
    说(f"  {'✅' if 够 else '❌'} 样本量:预约 {预} 条(要 ≥ {最少要补})")
    说(f"      ← **样本量 0 的时候上面每一项都是 ✅** —— 一张空表没有任何不一致")
    坏 += (not 够)
    # 漏斗的「到店」那一环是按状态数的,顺手把它现算一遍给人看
    到 = q("select count(*) from appointment where status in ('已到店','已完成') "
           "and substr(start_ts,1,10) <= ?", 今.isoformat())
    说(f"  漏斗「到店」那一环现在能数到 {到} 人次(重建后只剩夹具时是 70 掉到 0 的那个数)")
    return 坏


def main():
    ap = argparse.ArgumentParser(description="造三类接待触点历史(幂等,分批写)")
    ap.add_argument("--做", action="store_true", dest="做")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    if not os.path.exists(DB):
        print(f"{R}❌{D} 没有库 {DB}")
        return 1
    rnd = random.Random(种子)
    c = _连(DB)
    今 = _世界今天(c)
    print(f"库:{DB}")
    print(f"世界的今天 {今}(从库里读,不碰机器时钟)")
    补, 护 = 要补的单(c, rnd)
    if 补 is None:
        return 1
    if len(补) < 最少要补:
        print(f"{R}❌{D} 只挑中 {len(补)} 单 —— **这不叫「没什么可补」,叫取数取空了**"
              f"(要 ≥ {最少要补})")
        return 1
    预约, 日程, 跟进 = 生成(补, 今, rnd)
    print(f"会造:预约 {len(预约)} · 到店流水 {len(日程)} · 跟进 {len(跟进)}")
    if not a.做:
        旧 = {t: c.execute(f"select count(*) from {t} where id like ?",
                          (f"{标记}{p}%",)).fetchone()[0]
             for t, p in (("appointment", "AP"), ("schedule", "SC"), ("followup", "FU"))}
        print(f"  库里现有本脚本的旧数据:{旧} —— 真跑会**先删掉再重造**(幂等)")
        print(f"{Y}只看不做{D}。真写加 --做")
        return 0

    删 = 删自己那批(c)
    撞总, 重总 = 0, 0
    for sql, 行们, 名 in (
        ("insert or ignore into appointment(id,customer_id,shop,advisor_no,"
         "start_ts,status,checkin_ts) values(?,?,?,?,?,?,?)", 预约, "预约"),
        ("insert or ignore into schedule(id,type,advisor_no,customer_id,"
         "start_ts,status,ref_id) values(?,?,?,?,?,?,?)", 日程, "到店流水"),
        ("insert or ignore into followup(id,customer_id,appt_id,ts,channel,"
         "content,advisor_no) values(?,?,?,?,?,?,?)", 跟进, "跟进"),
    ):
        n, 撞, 重 = _批写(c, sql, 行们, 名)
        撞总 += 撞
        重总 += 重
        print(f"  写了 {名} {n} 条(每 {批大小} 条一提交)")
    print(f"  删掉旧的 {删} 条 · 撞锁 {撞总} 次 · 重试 {重总} 次")
    坏 = 复查(c, 今)
    if 坏:
        print(f"{R}❌ 复查 {坏} 处不对{D}")
        return 1
    print(f"{G}✅ 接待触点历史造好了{D}")
    print(f"{Y}下一步{D}:tools/lifecycle_history_seed.py --做 —— 它按这三张表算"
          f"「最近一次互动」,所以必须排在本脚本之后")
    return 0


if __name__ == "__main__":
    sys.exit(main())
