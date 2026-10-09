#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造「派出去的任务」—— 让派单看板和按周统计有真实样本。

    python3 tools/seed_dispatch.py          # 只看
    python3 tools/seed_dispatch.py --做     # 真写
    python3 tools/seed_dispatch.py --回滚   # 按台账撤掉(不是按 id 前缀)

## 为什么要造

`schedule` 表有 17467 行,但**按类型拆开只有 93 行是派单任务**:

    type='到店'   17374 行  ← **接待记录**(客户来过店的流水),`end_ts` 全是 NULL
    其余           93 行  ← 真正派给人的任务(有 `end_ts`、有 `assignee_no`)

> 一张表里住着两种东西:接待记录和派出去的任务。
> **它们在「schedule 有多少行」这个数上长得一模一样** ——
> 所以按周统计派单量不加 `type<>'到店'`,数字会被 17374 条接待记录淹没。

93 条还撑不起「这周派了多少、谁手上压着几条、有没有逾期」这些问题。

## 四个「先去看一眼,别设计绕法」的发现(2026-10-09)

交接里这件事曾经卡在两个「未知」上,挖完发现**两个都有正门**:

**① 操作身份:`api.as_user(me)`,不用伪造凭据**

    with api.as_user(店长):
        api.assign_task(type=..., assignee=..., note=..., end=..., start=...)

身份走 `ContextVar("lanxiu_me")`,工具函数签名里**没有**「我是谁」——
这是有意的:模型没法把身份当参数传错或伪造,只能由调用层注入。
所以造数走正门,`只有店长及以上能派`、`只能派给本店在职顾问`
这些判断**照常生效**,`op_log` 里留下的「谁干的」也是对的。

**② 时间:直接给 `start` / `end` 参数,不用拨世界时钟**

`backend/tasks.py` 的校验**只有三条**:`end` 必填、格式能 parse、`end > start`。
**没有**「不许落在过去」这类限制;`start` 不填才回落到世界此刻。
想让 `end_ts` 落在哪天,就把两个时间都显式写成那天 —— 都是普通参数。

**③ 「逾期」是算出来的,不是一个状态**

`tasks.py:544`:`status == '有效'` 且 `end_ts[:10] < 世界今天`
(今天到期的不算逾期,业务 2026-09-22 确认,和月度复盘同一个口径)。

> 所以**不能去写一个「逾期」状态** —— 那会造出一批
> **永远不会被认成逾期**的任务:`status` 里多个没人认的值,
> 而统计照 `status=='有效'` 过滤,**两边都不报错**。
> 逾期要靠「`status='有效'` + `end_ts` 落在今天之前」造出来。

派生状态不入库,还有一层理由:世界每天往前走一天,写死的「逾期」会漂,
而它看起来仍然很正常。

**④ 走正门就不能指定 id,所以回滚不能按前缀**

写口自己生成 `sid = f"SC{7000+n+1}"`,和现有任务同构 ——
`tools/seed_churned.py` 那套「按 C5/CH 前缀回滚」在这儿用不了。

解法是**记台账**,复用现成的 `daily_fresh_batch(batch, 表, 主键, 动作, 原值)`:
那几列是纯通用的,`batch` 本来就是用来区分批次的。
**不另建表** —— 多一张表就要改文档里写着的数据表数(今天刚为 103→104 红过 9 处)。
写口返回 `id=sid`,记下来,回滚按 `batch` 删 ——
不需要 id 带前缀,也**不用往 `note` 里掺标记污染演示文本**。

⚠️ 别把日期写进台账的 `原值`:`shift_world` 把 `daily_fresh_batch.原值` 登记成
「文字里也挪」,写进去的日期会跟着世界一起挪。回滚只用主键,不受影响。
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

import api                       # noqa: E402
import worldclock as W           # noqa: E402

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
DB = os.path.join(ROOT, "backend", "lanxiu.db")
for _i, _a in enumerate(sys.argv):
    if _a == "--db" and _i + 1 < len(sys.argv):
        DB = sys.argv[_i + 1]

SEED = 20261009
批次前缀 = "seed_dispatch/"
台账 = "daily_fresh_batch"       # 复用,见模块头 ④

# 口径(早就定了):按 `schedule.end_ts` 归周、`type<>'到店'`、状态含逾期、按天分散。
# 造的量按「每周每店几条」给,不写死总数 —— 店的数量一变,总数该跟着变。
每店每周 = 6
周数 = 4                          # 往前铺 4 周 + 本周
# ⚠️⚠️ **选类型要同时看两维:要不要 `ref_id`,和要不要现场照。**
# 第一版只看了前一维,挑了「团建培训 / 日常运维」—— 它们不用挂东西,
# **但两个都要现场照**(`tasktypes.needs_photo`),于是能派进去、**永远结不掉**:
#     ❌ NEED_PHOTO:「团建培训」完成时要传现场照
# 而 `api.finish_task` 的文档自己写着「要先在页面上传照片,**这里传不了图**」——
# 工具层**故意**不收附件。
#
# > 一个「能派也能结」的类型,和一个「能派但结不掉」的类型,
# > **在「派单成功了 82 条」这件事上长得一模一样** —— 错误只在后半步暴露。
#
# **不伪造附件绕过校验**(那和「谁做的谁点完成」一样是业务规则,该顺着走)。
# 运营类里唯一不要照片的是「订单跟踪」,代价是要挂订单号 —— 库里有现成的。
#
#     团建培训 / 日常运维 / 维保任务 / 售后任务   要照片 → 结不掉,不用
#     订单跟踪                                  不要照片,要 ref_id=订单号 ✓
类型 = ["订单跟踪"]
内容 = {
    "订单跟踪": ["盯一下面料到没到", "催一下工坊排产", "确认客户改的尺寸已同步",
                 "核对交期有没有变", "问一下物流到哪了"],
}


def 不成(r):
    """写口到底成没成。**两种失败返回都要认。**

    ⚠️ 2026-10-09 栽过:只看了 `r.get("error")`,而 `backend/tasks.py` 的写口用的是
    `dict(ok=False, code=..., reason=...)` 风格 —— 于是 **54 次失败被当成了成功**,
    脚本打印「结了 54」,而库里那 82 条一条都没变成「完结」。

    > 两种失败返回,**在「没有 error 这个键」这件事上长得一模一样。**

    这和「写口返回了东西」≠「写口干成了事」是同一个形状 ——
    所以除了这里,造完还要**当场回查库**(见 `跑` 里那条 SELECT 守卫)。
    """
    return (not isinstance(r, dict)) or bool(r.get("error")) or r.get("ok") is False


def _批次(今):
    return f"{批次前缀}{今.isoformat()}"


def 记(c, 批, 表, 主键, 动作):
    """记台账,**写完立刻 commit**。不写日期进 `原值` —— 见模块头 ④ 那条警告。

    ⚠️ **为什么不能攒在一个大事务里**(2026-10-09 栽过,`database is locked`):
    走写口正门时,`tasks.assign_task` 用的是**它自己的连接**。
    如果本脚本把整批包在 `with c:` 里,那本脚本的连接在回滚那一步就拿到了写锁,
    写口的连接**永远等不到** —— 报的是 `database is locked`,
    而那句话看起来像「有别人在写库」。

    > 一句「并行会话正在写库」和一句「我把写口的调用包进了自己的事务」,
    > **在 `database is locked` 这条报错上长得一模一样** ——
    > 判法:`BEGIN IMMEDIATE` 试一下,能拿到锁就说明外面没人,是自己嵌套了。

    代价是失去「整批全成或全不成」的原子性。换来的保证是:
    **台账逐条落地**,中途失败时 `--回滚` 能把已经造的那些精确撤掉。
    """
    c.execute(f"INSERT INTO {台账}(batch,表,主键,动作,原值) VALUES(?,?,?,?,?)",
              (批, 表, str(主键), 动作, None))
    c.commit()


def 回滚(c, 说=print):
    """按台账撤 —— **不是按 id 前缀**(走正门拿不到 id,见模块头 ④)。"""
    行 = c.execute(f"SELECT 表, 主键 FROM {台账} WHERE batch LIKE ?",
                   (批次前缀 + "%",)).fetchall()
    if not 行:
        return 0
    n = 0
    for 表, 主键 in 行:
        if 表 != "schedule":
            # **不猜**:台账里出现没登记过的表就停,别「尽力删一删」
            raise SystemExit(f"❌ 台账里有没登记过的表 {表!r} —— 不猜,先去看为什么")
        n += c.execute("DELETE FROM schedule WHERE id=?", (主键,)).rowcount
    c.execute(f"DELETE FROM {台账} WHERE batch LIKE ?", (批次前缀 + "%",))
    说(f"  回滚:删掉 {n} 条任务(按台账 {批次前缀}*,共 {len(行)} 条记录)")
    return n


def 店长们(c):
    """每个店挑一个店长 —— 派单要店长身份(MANAGER_ROLES),这是正门不是绕法。

    ⚠️ `staff.status` 的值是 **`启用` / `停用`**,不是「在职」。
    第一版照字面写了 `status='在职'`,扫出来 0 个店长、0 个店。
    **没有静默造 0 条** —— 样本量判据当场报了「这不叫『没什么可造』,叫取数取空了」。

    > 一句「这个店没有店长」和一句「我把状态值写错了」,
    > **在「扫出来 0 个」这件事上长得一模一样** —— 所以那句话要把两种都点出来。
    """
    out = {}
    for r in c.execute("""SELECT no, name, shop, role FROM staff
                           WHERE role='店长' AND status='启用' ORDER BY no"""):
        out.setdefault(r[2], dict(no=r[0], name=r[1], shop=r[2], role=r[3]))
    return out


def 顾问们(c):
    """本店在职顾问 —— 派单只能派给这些人(写口自己也会判,这里先挑对)。"""
    out = {}
    for r in c.execute("""SELECT no, name, shop FROM staff
                           WHERE role='顾问' AND status='启用' ORDER BY no"""):
        out.setdefault(r[2], []).append(dict(no=r[0], name=r[1]))
    return out


def 订单们(c, shop, 不晚于):
    """这个店在 `不晚于` 那天**之前就已经存在**的订单号。

    **挑的是真有的订单**,不编号:编出来的号写进去,页面上点开就是空的。

    ⚠️ **必须按任务日期筛,不能从全店随机挑**(2026-10-09 栽过,门禁 C3 逮住 72 条):
    规范 C3 是「任何记录的时间不得早于它所属对象的创建时间」。
    第一版把两件事分开随机 —— 任务日期按周铺开、订单从全店随机挑 ——
    于是「盯一张 9 月才下的单」的任务落到了 8 月,**时间倒流**。

    > 修法不是「把订单挑新一点」把概率压低,
    > 而是**让挑订单这一步依赖任务日期** —— 倒流在结构上就不可能。
    """
    return [r[0] for r in c.execute(
        "SELECT id FROM ordr WHERE shop=? AND substr(created,1,10)<=? "
        "ORDER BY created DESC LIMIT 300", (shop, 不晚于))]


def 排(今, rng, 店数):
    """排出「哪天、谁、什么类型、要不要逾期」—— 先排好再写,方便只看不做。

    逾期怎么来:`status='有效'` + `end_ts` 落在**今天之前**(见模块头 ③)。
    所以往前那几周的任务里留一部分不结,它们自然就是逾期的。
    """
    计划 = []
    for 周 in range(周数, -1, -1):          # 周数 周前 → 本周
        周一 = 今 - dt.timedelta(days=今.weekday() + 7 * 周)
        for i in range(每店每周):
            # 按天分散:在这一周里摊开,不要全堆在同一天
            日 = 周一 + dt.timedelta(days=rng.randrange(0, 6))
            if 日 > 今:
                continue                    # 不造未来的(本周后半段还没到)
            k = rng.choice(类型)
            # 逾期该是**少数**(真实门店一成左右)。第一版对往前每一周都用同一个
            # 35% 不结率,**累积下来逾期过半** —— 周报一上来就是「本周逾期 94 条、
            # 压在 8 个人手上」,读起来像门店管理失控。并行会话指出来的,是对的。
            # 按到期日分:**越老的越该已经完结**(该办的早办了),
            # 只有最近一两周才合理地留一些在手上。
            不结率 = 0.08 if 周 >= 2 else (0.25 if 周 == 1 else 0.0)
            计划.append(dict(日=日, 类型=k, 内容=rng.choice(内容[k]),
                             结=(rng.random() > 不结率)))
    return 计划


def 跑(c, 今, rng, 真写, 说=print):
    批 = _批次(今)
    长 = 店长们(c)
    顾 = 顾问们(c)
    店 = [s for s in sorted(长) if 顾.get(s)]
    if not 店:
        说(f"{R}❌{D} 一个「有店长又有在职顾问」的店都没扫到 —— "
           f"**这不叫「没什么可造」,叫取数取空了**(店长 {len(长)} / 有顾问的店 {len(顾)})")
        return None
    计 = {"派了": 0, "结了": 0, "留着逾期": 0}
    for s in 店:
        计划 = 排(今, rng, len(店))
        for it in 计划:
            # 按**这条任务的日期**取候选订单,不是全店随机(见 `订单们` 的注释)
            单 = 订单们(c, s, it["日"].isoformat())
            if not 单:
                说(f"{R}❌{D} {s} 在 {it['日']} 之前一张订单都没有 —— "
                   f"「订单跟踪」要挂一张**那时候已经存在**的订单;"
                   f"**这不叫「这个店没单」,是往前铺的周数超过了这个店的开单历史**")
                return None
            adv = rng.choice(顾[s])
            st = f"{it['日'].isoformat()} {rng.randrange(9, 16):02d}:00"
            en = f"{it['日'].isoformat()} {rng.randrange(17, 20):02d}:00"
            if not 真写:
                计["派了"] += 1
                计["结了" if it["结"] else "留着逾期"] += 1
                continue
            # ① 走正门:以店长身份派(见模块头 ①)
            with api.as_user(长[s]):
                r = api.assign_task(type=it["类型"], assignee=adv["no"],
                                    note=it["内容"], start=st, end=en,
                                    ref_id=rng.choice(单))
            if 不成(r) or not r.get("id"):
                说(f"{R}❌{D} 派单没成:{r} —— **不兜底**,先去看为什么")
                return None
            sid = r["id"]
            记(c, 批, "schedule", sid, "ASSIGN")
            # ② 结构守卫:当场验这条真的找得回来(照 daily_fresh 的 `_记` 那条)
            if not c.execute("SELECT 1 FROM schedule WHERE id=?", (sid,)).fetchone():
                说(f"{R}❌{D} 记了台账却查不到 schedule {sid} —— 主键对不上")
                return None
            计["派了"] += 1
            if it["结"]:
                # ⚠️ **结单必须以「被派到的那个顾问」的身份**,店长代点不行:
                # 写口明写「只能完成派给自己的任务 —— 谁做的谁点完成,
                # 别人代点等于台账上写了一件没发生的事」(`tasks.py` 的 NOT_MINE)。
                # 第一版用店长身份结,54 次全被拒,而我的守卫只看 `error` 键没看
                # `ok=False`,于是**全当成了成功** —— 库里那 82 条一条都没结。
                # 业务规则是对的,顺着它走:换身份,不绕。
                with api.as_user(dict(adv, shop=s, role="顾问")):
                    f = api.finish_task(task_id=sid, summary=it["内容"] + " —— 已完成")
                if 不成(f):
                    说(f"{R}❌{D} 结单没成:{f}")
                    return None
                计["结了"] += 1
            else:
                计["留着逾期"] += 1
    return 计


def 复查(c, 今, 说=print):
    """**验收按口径看,不按行数看。** 口径:`type<>'到店'`、按 end_ts 归周、逾期算出来。"""
    坏 = 0
    任务 = c.execute("SELECT count(*) FROM schedule WHERE type<>'到店'").fetchone()[0]
    说(f"  派单任务(type<>'到店'):{任务} 条")
    说(f"  {'✅' if 任务 >= 93 else '❌'} 比原来的 93 条多了(要 ≥93)")
    坏 += (任务 < 93)

    # 逾期:status='有效' 且 end_ts 的日子早于世界今天(今天到期的不算)
    逾 = c.execute("""SELECT count(*) FROM schedule WHERE type<>'到店'
                       AND status='有效' AND end_ts IS NOT NULL
                       AND substr(end_ts,1,10) < ?""", (今.isoformat(),)).fetchone()[0]
    说(f"  {'✅' if 逾 else '❌'} 算出来是逾期的:{逾} 条(要 ≥1)")
    # ⚠️ **只验下界分不出「全都没结」和「结得正好」** —— 第一版就这么过的:
    # 82 条一条没结、逾期 94 条,照样满足「≥1」。所以这里还要验**上界**和**真的结了**。
    我的 = f"id IN (SELECT 主键 FROM {台账} WHERE batch LIKE '{批次前缀}%')"
    结了 = c.execute(f"SELECT count(*) FROM schedule WHERE {我的} AND status='完结'").fetchone()[0]
    我共 = c.execute(f"SELECT count(*) FROM schedule WHERE {我的}").fetchone()[0]
    说(f"  {'✅' if 结了 else '❌'} 这批里真的变成「完结」的:{结了}/{我共} 条(要 ≥1)")
    说(f"      ← 写口返回了东西 ≠ 写口干成了事:店长**代点不了**顾问的完成,"
       f"第一版 54 次被拒而守卫没认出来,库里一条都没结")
    坏 += (not 结了)
    占 = 逾 * 100 // max(任务, 1)
    说(f"  {'✅' if 占 <= 25 else '❌'} 逾期占派单任务的 {占}%(要 ≤25% —— "
       f"真实门店逾期是少数,过半会让周报读起来像管理失控)")
    坏 += (占 > 25)
    说(f"      ← **逾期不是一个 status 值**,是 `status='有效'` + `end_ts` 早于今天算出来的;"
       f"要是去写一个「逾期」状态,会造出一批**永远不会被认成逾期**的任务")
    坏 += (not 逾)

    # 按周归:至少铺开几周,不能全堆在一周
    周 = c.execute("""SELECT count(DISTINCT strftime('%Y-%W', end_ts)) FROM schedule
                       WHERE type<>'到店' AND end_ts IS NOT NULL""").fetchone()[0]
    说(f"  {'✅' if 周 >= 3 else '❌'} end_ts 落在 {周} 个不同的周里(要 ≥3)")
    坏 += (周 < 3)

    # C3:任务的时间不得早于它挂的那张订单的创建时间(门禁里那条规范,自己先验)
    倒 = c.execute(f"""SELECT count(*) FROM schedule s JOIN ordr o ON o.id=s.ref_id
         WHERE s.id IN (SELECT 主键 FROM {台账} WHERE batch LIKE '{批次前缀}%')
           AND substr(s.start_ts,1,10) < substr(o.created,1,10)""").fetchone()[0]
    说(f"  {'✅' if not 倒 else '❌'} 任务早于它挂的订单的:{倒} 条(要 0)")
    说(f"      ← 规范 C3。**挑订单必须依赖任务日期**,"
       f"两件事分开随机会撞出时间倒流(第一版 72 条)")
    坏 += bool(倒)

    # 有没有人手上压着 —— 看板要回答「谁忙」
    人 = c.execute("""SELECT count(DISTINCT assignee_no) FROM schedule
                       WHERE type<>'到店' AND status='有效' AND assignee_no IS NOT NULL""").fetchone()[0]
    说(f"  {'✅' if 人 >= 2 else '❌'} 手上还压着任务的人:{人} 个(要 ≥2)")
    坏 += (人 < 2)
    return 坏


def main():
    ap = argparse.ArgumentParser(description="造派出去的任务(按台账回滚)")
    ap.add_argument("--做", action="store_true", dest="做")
    ap.add_argument("--回滚", action="store_true", dest="回滚")
    ap.add_argument("--db", default=None)
    a, _ = ap.parse_known_args()
    if not os.path.exists(DB):
        print(f"{R}❌{D} 没有库 {DB}")
        return 1
    api.DB = DB                   # 让工具层也走同一个库
    今 = W.今天()
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    print(f"世界的今天 {今} · 每店每周 {每店每周} 条 × 往前 {周数} 周 + 本周")

    if a.回滚:
        n = 回滚(c)
        c.commit()
        print(f"{G}✅ 回滚完成{D}" if n else f"{Y}·{D} 台账里本来就没有")
        return 0

    已有 = c.execute(f"SELECT count(*) FROM {台账} WHERE batch LIKE ?",
                     (批次前缀 + "%",)).fetchone()[0]
    if not a.做:
        print(f"  台账里已有 {已有} 条本脚本的记录 —— 真跑会**先按台账回滚再重造**")
        计 = 跑(c, 今, random.Random(SEED), False)
        if 计 is None:
            return 1
        print("  打算造:" + " · ".join(f"{k} {v}" for k, v in 计.items()))
        print(f"{Y}只看不做{D}。真写加 --做")
        return 0

    # ⚠️ **不要 `with c:` 包住整批** —— 写口用的是它自己的连接,
    # 本脚本持着写锁的话它会一直等,报出来是 `database is locked`(见 `记` 的注释)。
    回滚(c)                       # 幂等:先撤自己那批再重造,不是「有了就跳过」
    c.commit()                    # 放掉写锁,下面要让写口自己写
    计 = 跑(c, 今, random.Random(SEED), True)
    if 计 is None:
        # 不回滚整批:写口已经自己提交了。台账逐条落着,照它撤才撤得干净。
        print(f"{Y}中途失败{D} —— 已经造出来的那些在台账里,"
              f"跑 `--回滚` 可以精确撤掉(**别手删 schedule**)")
        return 1
    print("  造了:" + " · ".join(f"{k} {v}" for k, v in 计.items()))
    坏 = 复查(c, 今)
    if 坏:
        print(f"{R}❌ 复查 {坏} 处不对{D}")
        return 1
    print(f"{G}✅ 派单任务造好了{D}")
    print(f"{Y}注{D}:走的是写口正门(api.as_user + assign_task/finish_task),"
          f"所以权限判断照常生效、op_log 里有「谁干的」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
