#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造**客户族**的派单任务:接待任务(从 0 条开始)、电话回电加厚、商机提醒结掉。

## 为什么(这件事的描述原来是错的)

交接里挂着「派单任务还没造客户类」。**不对** —— 客户族早就有 79 条:
预约到店 38 · 上门沟通 31 · 电话回电 7 · 商机提醒 3。真正的缺口是另外三样:

    接待任务    0 条  ← **一整个类型零样本**
    电话回电    7 条  ← 薄到按周统计只有个别周有数
    商机提醒    3 条,全是「有效」 ← 完成那条路从没走过

## 「接待任务 0 条」为什么比「薄」严重得多

`backend/tasks.py` 的 `finish_task` 里有一段**自动收尾**:

    if tt.norm(t.get("type")) in ("上门沟通", "接待任务") and t.get("customer_id"):
        # 把那条还开着的「预约到店」一并收尾 —— 客户已经见过面了

这段代码**写着「接待任务」,而库里是 0 条** —— 所以那一支**从来没有数据走过**。
`backend/isolation_check.py` 那条判据(`type IN ('上门沟通','接待任务') AND status='完结'`)
同理:它一直只在 31 条「上门沟通」上跑,**另一半是空的**。

> 一条「写对了的分支」和一条「写错了也不会被发现的分支」,
> **在门禁的绿勾上长得一模一样** —— 因为那个类型没有一行数据。

所以这一批里专门有 3 条是**挂在还开着的那 3 条预约上**的:造完、结掉,
那 3 条预约应该被**自动**收尾。复查里直接判「真的顺带收尾了几条」
(`finish_task` 的返回里有 `顺带收尾`),不是判「有没有报错」。

## 商机提醒:它**不走 `assign_task`**

唯一写 `opportunity_task`(任务号 → 商机号)那条边的是 `opportunity_store._派提醒`,
由商机自己的生命周期触发(`满足扫描` / `回捞` / `改状态`)。

> 所以**不许**用 `assign_task` 去造「商机提醒」—— 那会造出一条
> **没有商机号的孤儿任务**,它在任务列表里和正常的长得一模一样,
> 只在完成时才暴露(`可选结论()` 返回 None,于是完成时根本不要求选结论)。

这里只做一件事:把**已经存在**的商机提醒按正门结掉,结论走
`api.finish_task(..., conclusion=...)`。`按结论处理` 会跟着改商机状态:
`回捞` 的三个结论 → 「客户想看,继续跟」=跟进中 · 「客户不要了」=已关闭 ·
「没联系上」=不改状态。

⚠️ **「没联系上」那一支故意留着不覆盖。** 三条提醒结掉两条、留一条开着:
「有效的商机提醒」是顾问待办里**唯一**的那种样本,消耗掉比覆盖一个
**只记 answer、不改任何状态**的分支更贵。这是个取舍,写在这儿免得
下一个人以为是漏了。

## 不许做的几件(每条都踩过或差点踩)

- **不写「逾期」状态**:逾期是算出来的(`status='有效'` 且 `end_ts[:10] < 世界今天`)。
  写死的话会造出一批**永远不会被认成逾期**的任务,而两边都不报错。
- **不替别人点完成**:`finish_task` 只认被派到的那个人(`NOT_MINE`)。
  店长代点等于台账上写了一件没发生的事 —— 顺着规则走,换身份。
- **不挑要照片的类型去结**:客户族里「上门沟通」要现场照,而工具层**故意**传不了图。
  它能派进去、永远结不掉。这一批只结不要照片的三种。
- **不指定 id**:走正门就是写口自己生成 `SC{...}`,所以回滚**记台账**
  (复用 `daily_fresh_batch`,不新建表 —— 新建就要改文档里的数据表数)。
- **不碰覆盖样本客户**(`C5*`):那批人是流失预警七支码的样本,离远点。
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
import order_mix as OM           # noqa: E402

DB = os.path.join(ROOT, "backend", "lanxiu.db")
真库 = DB                        # --试跑 会把 DB 换成副本,这个留着当「别动它」的锚
批次前缀 = "seed_customer_tasks/"
台账 = "daily_fresh_batch"       # 复用,不新建表

# ── 造多少、怎么分布 ──────────────────────────────────────────────
# 量定得克制:接待任务是**任务**,不是那 17374 条到店流水。
# 造成千上万条会把周报里的派单量冲掉,而那种失真看起来很正常。
靶子数 = 3          # 挂在还开着的「预约到店」上 —— 结掉它们去点亮自动收尾
接待_独立 = 12
回电_条数 = 18
商机_最多结 = 2     # 留一条开着,理由见文档字符串


def 要结几条(提醒):
    """**不写死条数,而且要按「搁置等供给的商机」算,不是按「提醒条数」算。**

    库里那几条商机提醒是 `backfill_opportunity.py` 模拟上新再回捞出来的,**条数会变**;
    写死 2 条的话,哪天只捞到 1 条就在 CI 上红,而真因在另一个脚本里。

    ⚠️⚠️ **2026-10-10 在 CI 的从零重建上栽了一次,而且本地看不见。**
    第一版是按**提醒条数**算「留一条开着」。从零建时:
        搁置等供给的商机 **2 条**,而商机提醒 **7 条**
        (多出来的 5 条是并行会话新加的「购买推断」,挂的是「待确认」商机)
    于是 `min(2, 7-1)=2` 把那 **2 条搁置商机对应的回捞提醒全结了** ——
    库里一条「搁置等供给」都不剩,`opportunity_obj_check` 的
    「搁置等供给的都写清等什么」**样本量 0**,当场红。

    > 一个「留了一条**提醒**开着」和一个「留了一条**搁置商机**」,
    > **在「我留了一条」这件事上长得一模一样** ——
    > 本地有 3 条搁置、3 条提醒、一一对应,所以这个区别在本地不存在。

    所以:**只从「kind='回捞' 且商机还是搁置等供给」这个集合里挑**(见 `可结的提醒`),
    按这个集合留一条。那个集合里每条提醒对应一条搁置商机,
    结掉 n-1 条就**一定**还剩一条搁置的。
    (顺带也不再碰并行会话的「购买偏好回捞」—— 它的可选结论是另一套,
     而且它有自己的收口路径 `opportunity_store.推断提醒收口`。)
    """
    return min(商机_最多结, max(0, len(提醒) - 1))

内容 = {
    "接待任务": ["客户到店,带看秋冬新品并记录诉求",
                 "客户到店复量,确认领型和袖长",
                 "客户带家人到店挑面料,现场比色",
                 "客户到店取件并试穿,登记修改意见"],
    "电话回电": ["回电确认到店时间",
                 "回电答复面料色差的问题",
                 "回电跟进上次留的预算区间",
                 "回电告知工期顺延的安排并致歉",
                 "回电确认是否需要上门量体"],
}
商机结论 = ["客户想看,继续跟", "客户不要了"]   # 这两个会真的改商机状态


# 咬合记录:**四条都在 2026-10-10 的库副本上真跑过**,不是推的。
咬合 = [
    ('把靶子的接待时间写死成 14:00(而预约在 16:00 / 17:00)',
     '跑() 里靶子逐条对账 → 退出码 1'),           # 实测:3 条只收尾 1 条;**而复查全绿**
    ('直接往库里插一条「完结」的接待任务、不让自动收尾跑',
     '没有「客户已接待完却还开着的预约」'),        # 实测:1 条还开着
    ('把「自动收尾跑起来过」写成只数 op_log 里 AUTO_CLOSE 的总数',
     '造数之前它就已经是绿的(31 条全是上门沟通触发的)'),   # 实测,所以改成按触发类型数
    ('把 `可结的提醒` 的筛选去掉 `o.status=\'搁置等供给\'`(退回按提醒条数算)',
     '库里还留着「搁置等供给」的商机'),       # 2026-10-10 CI 从零建实测:搁置被吃到 0
    ('跑() 里无条件 return 0',
     '打印了 ✗ 而整套退出码还是 0'),               # 实测:**打印 ❌ 和拦截是两件事**
]
# ⚠️ 第一条和第二条**各守一头,不能互相代替**(实测过):
# 接待时间写错 → 预约收不掉,而第二条的 EXISTS 要求「接待.start >= 预约.start」,
# 14:00 < 17:00 不满足,于是**那条判据照样绿**。反过来,自动收尾被改坏时
# 第一条(对账)也会红,但第二条给的是业务语言的那句话。


def 不成(r):
    """写口有**两种**失败风格,而它们在「没有 error 这个键」上长得一模一样。

    `dict(error=...)` 是工具层的;`dict(ok=False, code=...)` 是业务层的。
    只看一种的后果实测过:54 次 `NOT_MINE` 被当成成功,82 条一条都没结,
    而脚本打印着「结了 54」。
    """
    return (not isinstance(r, dict)) or bool(r.get("error")) or r.get("ok") is False


def 记(c, 批, 表, 主键, 动作, 原值=None):
    """台账逐条写、**写完立刻提交**。

    不攒大事务:第一版把写口的调用包在自己的 `with c:` 里 ——
    自己的连接拿着写锁,而写口用的是**它自己的连接**,于是
    `database is locked`,而那条报错和「并行会话正在写库」长得一模一样。
    """
    c.execute(f"INSERT INTO {台账}(batch,表,主键,动作,原值) VALUES(?,?,?,?,?)",
              (批, 表, str(主键), 动作, json.dumps(原值, ensure_ascii=False) if 原值 else None))
    c.commit()


def 世界今天(c):
    return c.execute("SELECT v FROM world_meta WHERE k='world_today'").fetchone()[0]


def 店长们(c):
    return {r[2]: dict(no=r[0], name=r[1], shop=r[2], role="店长")
            for r in c.execute("SELECT no,name,shop FROM staff "
                               "WHERE role='店长' AND status='启用'")}


def 顾问们(c):
    return [dict(no=r[0], name=r[1], shop=r[2], role="顾问")
            for r in c.execute("SELECT no,name,shop FROM staff "
                               "WHERE role='顾问' AND status='启用' ORDER BY no")]


def 开着的预约(c):
    """还是「有效」、派了人、挂了客户的「预约到店」—— 自动收尾的靶子。"""
    return [dict(id=r[0], customer=r[1], assignee=r[2], shop=r[3], start=r[4])
            for r in c.execute(
                "SELECT id, customer_id, assignee_no, shop, start_ts FROM schedule "
                "WHERE type='预约到店' AND status='有效' "
                "AND assignee_no IS NOT NULL AND customer_id IS NOT NULL "
                # ⚠️ 带上 id:只按 start_ts 排,**同一时刻的并列顺序是未定义的** ——
                # 从零重建两次可能挑到不同的靶子,而两次都「成功」。
                "ORDER BY start_ts, id")]


def 挑客户(c, adv_no, 不晚于, 用过, 护):
    """挑一个**建档时间不晚于任务开始**的客户。

    ⚠️ 顺序是故意的:**先定日子,再按日子挑人**。
    反过来(先挑人再随机日子)上一轮造出过 72 条时间倒流 ——
    规范 C3:任何记录的时间不得早于它所属对象的创建时间。
    压低概率不算修,让挑人依赖日子才算。
    """
    for (cid,) in c.execute(
            "SELECT id FROM customer WHERE advisor_no=? AND id NOT LIKE 'C5%' "
            "AND substr(created,1,10)<=? ORDER BY id", (adv_no, 不晚于)):
        if cid not in 用过 and cid not in 护:
            用过.add(cid)
            return cid
    return None


def 跑(说=print):
    rng = random.Random(20261010)
    c = sqlite3.connect(DB)
    今 = 世界今天(c)
    零 = dt.date.fromisoformat(今)
    批 = 批次前缀 + 今
    if c.execute(f"SELECT 1 FROM {台账} WHERE batch=?", (批,)).fetchone():
        说(f"❌ 今天这一批({批})已经造过了 —— 先 `--回滚` 再重造,"
          f"不然会在同一个批次里混进两代数据,而台账回滚只认批次")
        return 1
    护 = OM.受保护客户(c)
    长 = 店长们(c)
    顾 = 顾问们(c)
    if not 长 or not 顾:
        说(f"❌ 取数取空了:店长 {len(长)} 个 / 在职顾问 {len(顾)} 个 —— "
          f"**这不叫「没什么可造」**。先看 staff.status 的值对不对"
          f"(它是 `启用`/`停用`,不是「在职」—— 上一轮照字面写错过)")
        return 1
    用过 = set()
    成, 败 = 0, []

    def 派(店, 顾问, 类型, 客户, st, en, 话):
        nonlocal 成
        with api.as_user(长[店]):
            r = api.assign_task(type=类型, assignee=顾问["no"], note=话,
                                start=st, end=en, ref_id=客户)
        if 不成(r):
            败.append(f"派 {类型}/{客户}:{r}")
            return None
        记(c, 批, "schedule", r["id"], "新增")
        成 += 1
        return r["id"]

    def 结(顾问, sid, 总结, 结论=None):
        with api.as_user(顾问):
            f = api.finish_task(task_id=sid, summary=总结, conclusion=结论)
        if 不成(f):
            败.append(f"结 {sid}:{f}")
            return None
        # ⚠️ **自动收尾的登记放在这里,不放在靶子那一段。**
        # 第一版只在靶子那段记 —— 而独立那一批的「完结」也走同一个写口,
        # 挑到的客户名下只要**恰好还有开着的预约**,自动收尾就跟着触发,
        # 而台账里没有它 —— **那条预约回滚不回来**。
        # 今天跑不出来(靶子正好把 3 条开着的预约用完了),但只要有人把
        # `靶子数` 改成 0,它就会静默发生:
        # 「回滚干净了」和「回滚漏了一条被改的预约」在台账行数上长得一模一样。
        if f.get("顺带收尾"):
            记(c, 批, "schedule", f["顺带收尾"], "被自动收尾",
               {"status": "有效", "summary": None, "由": sid})
        return f

    # ── ① 靶子:挂在还开着的预约上,结掉它们 → 自动收尾该跑起来 ────────
    收尾了 = []
    靶子们 = 开着的预约(c)[:靶子数]
    靶子命中 = 0
    for ap in 靶子们:
        顾问 = next((x for x in 顾 if x["no"] == ap["assignee"]), None)
        if not 顾问 or ap["shop"] not in 长:
            败.append(f"靶子 {ap['id']}:派到的人不在职或这个店没有店长 —— 跳过,不换人顶替")
            continue
        # ⚠️ 接待时间**跟着预约走,不许写死**。第一版写死 14:00–15:30,
        # 而自动收尾的条件是 `预约.start_ts <= 接待.end_ts` ——
        # 下午 16:00 / 17:00 的预约**一条都收不掉**(副本试跑:3 条只收了 1 条)。
        # 而且 `isolation_check` 那条判据用的是 `接待.start >= 预约.start`,
        # 和写口的 `预约.start <= 接待.end` **不是同一个比较** ——
        # 接待就落在预约那一刻开始,两个条件才同时成立。
        约时 = dt.datetime.fromisoformat(ap["start"])
        st = 约时.strftime("%Y-%m-%d %H:%M")
        en = (约时 + dt.timedelta(minutes=90)).strftime("%Y-%m-%d %H:%M")
        sid = 派(ap["shop"], 顾问, "接待任务", ap["customer"], st, en,
                 f"客户到店,按预约 {ap['id']} 接待并记录诉求")
        if not sid:
            continue
        靶子命中 += 1
        f = 结(顾问, sid, "已接待,诉求记进跟进;客户现场比了三种面料")
        if f and f.get("顺带收尾"):
            收尾了.append((sid, f["顺带收尾"]))   # 台账已经在 结() 里记过了

    # ── ② 独立的接待任务 + 电话回电 ────────────────────────────────
    # 三档:结掉的(多数) / 还没到期的 / 到期了没结的(= 逾期)。
    # ⚠️ **只验下界分不出「全都没结」和「结得正好」** —— 上一轮 176 条里
    # 逾期 94 条照样满足「逾期 ≥1」。所以这里把三档的条数都写明,复查逐档判。
    def 一批(类型, 条数, 跨几周):
        for i in range(条数):
            挡 = "完结" if i % 5 < 3 else ("未到期" if i % 5 == 3 else "逾期")
            if 挡 == "未到期":
                日 = 零 + dt.timedelta(days=rng.randint(1, 6))
            else:
                日 = 零 - dt.timedelta(days=rng.randint(2, 7 * 跨几周))
            顾问 = 顾[i % len(顾)]
            if 顾问["shop"] not in 长:
                continue
            cid = 挑客户(c, 顾问["no"], str(日), 用过, 护)
            if not cid:
                败.append(f"{类型} 第 {i+1} 条:{顾问['name']} 名下没有 {日} 之前建档的客户")
                continue
            话 = rng.choice(内容[类型])
            h = 9 + (i % 8)
            sid = 派(顾问["shop"], 顾问, 类型, cid,
                     f"{日} {h:02d}:00", f"{日} {h+1:02d}:30", 话)
            if sid and 挡 == "完结":
                结(顾问, sid, 话 + " —— 已完成")

    一批("接待任务", 接待_独立, 5)
    一批("电话回电", 回电_条数, 6)

    # ── ③ 商机提醒:按正门结掉,结论会真的改商机状态 ──────────────────
    商机动了 = []
    # **只取「回捞」且商机还是「搁置等供给」的** —— 理由见 `要结几条` 的注释
    提醒 = [dict(sid=r[0], opp=r[1], kind=r[2], assignee=r[3])
            for r in c.execute(
                "SELECT s.id, ot.opp_id, ot.kind, s.assignee_no FROM schedule s "
                "JOIN opportunity_task ot ON ot.schedule_id=s.id "
                "JOIN opportunity o ON o.id=ot.opp_id "
                "WHERE s.type='商机提醒' AND s.status='有效' AND s.assignee_no IS NOT NULL "
                "AND ot.kind='回捞' AND o.status='搁置等供给' "
                "ORDER BY s.id")]
    for n, t in enumerate(提醒[:要结几条(提醒)]):
        顾问 = next((x for x in 顾 if x["no"] == t["assignee"]), None)
        if not 顾问:
            败.append(f"商机提醒 {t['sid']}:派到的人不在职 —— 不换人")
            continue
        老 = c.execute("SELECT status, close_reason, updated, confirmed_by, confirmed_at "
                       "FROM opportunity WHERE id=?", (t["opp"],)).fetchone()
        结论 = 商机结论[n % len(商机结论)]
        f = 结(顾问, t["sid"], f"回捞回访:{结论}", 结论)
        if not f:
            continue
        记(c, 批, "schedule", t["sid"], "结掉", {"status": "有效"})
        记(c, 批, "opportunity", t["opp"], "按结论改状态",
           dict(zip(("status", "close_reason", "updated", "confirmed_by", "confirmed_at"), 老)))
        记(c, 批, "opportunity_task", t["sid"], "记了结论", {"answer": None})
        商机动了.append((t["sid"], t["opp"], 结论, f.get("商机")))

    # ⚠️ **逐条对账,不验下界。** 「3 条靶子收了 1 条」和「3 条全收了」
    # 都满足「收尾 ≥ 1」—— 第一版就是这么绿着放过去的。
    if len(收尾了) != 靶子命中:
        败.append(f"靶子 {靶子命中} 条,只收尾了 {len(收尾了)} 条 —— "
                  f"自动收尾的条件是「预约.start_ts <= 接待.end_ts」,去看接待的时间")
    说(f"  派成 {成} 条;自动收尾 {len(收尾了)}/{靶子命中} 条预约;商机动了 {len(商机动了)} 条")
    for a, b in 收尾了:
        说(f"    · 结掉接待 {a} → 顺带收尾预约 {b}")
    for sid, opp, 结论, 话 in 商机动了:
        说(f"    · {sid}({opp})结论「{结论}」→ {话}")
    if 败:
        说(f"  ⚠ {len(败)} 条没成(**逐条列出来,不笼统说「部分失败」**):")
        for x in 败[:10]:
            说(f"    ✗ {x}")
    c.close()
    # ⚠️ **有败就是非零。** 第一版这里无条件 `return 0` —— 于是
    # 「靶子 3 条只收尾了 1 条」那行 ✗ 打印出来了,而整套退出码还是 0。
    # **打印 ❌ 和拦截是两件事**,这个项目为这件事栽过不止一次。
    return 1 if 败 else 0


def 回滚(说=print):
    c = sqlite3.connect(DB)
    今 = 世界今天(c)
    批 = 批次前缀 + 今
    行 = list(c.execute(f"SELECT 表,主键,动作,原值 FROM {台账} WHERE batch=? ORDER BY id DESC",
                        (批,)))
    if not 行:
        说(f"  这一批({批})没有台账 —— 没造过,或者已经回滚过")
        c.close()
        return 0
    with c:
        for 表, 主键, 动作, 原值 in 行:
            v = json.loads(原值) if 原值 else {}
            if 动作 == "新增":
                c.execute("DELETE FROM schedule WHERE id=?", (主键,))
            elif 动作 in ("被自动收尾", "结掉"):
                c.execute("UPDATE schedule SET status=?, summary=? WHERE id=?",
                          (v.get("status", "有效"), v.get("summary"), 主键))
            elif 动作 == "按结论改状态":
                c.execute("UPDATE opportunity SET status=?, close_reason=?, updated=?,"
                          " confirmed_by=?, confirmed_at=? WHERE id=?",
                          (v.get("status"), v.get("close_reason"), v.get("updated"),
                           v.get("confirmed_by"), v.get("confirmed_at"), 主键))
            elif 动作 == "记了结论":
                c.execute("UPDATE opportunity_task SET answer=NULL, answered_by=NULL,"
                          " answered_at=NULL WHERE schedule_id=?", (主键,))
        # 自动收尾/结论那几条还会在 op_log 里留痕 —— **留着,不删**:
        # 台账是「谁什么时候点了这一下」,把它删掉才是篡改。
        c.execute(f"DELETE FROM {台账} WHERE batch=?", (批,))
    说(f"  回滚了 {len(行)} 条台账记录(op_log 的痕迹按设计留着)")
    c.close()
    return 0


def 复查(说=print):
    c = sqlite3.connect(DB)
    今 = 世界今天(c)
    挂 = []

    def ck(名, 真, 补=""):
        说(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
        if not 真:
            挂.append(名)

    数 = {t: (n, 完) for t, n, 完 in c.execute(
        "SELECT type, COUNT(*), SUM(status='完结') FROM schedule "
        "WHERE type<>'到店' GROUP BY type")}
    接待 = 数.get("接待任务", (0, 0))
    回电 = 数.get("电话回电", (0, 0))
    ck("「接待任务」不再是零样本", 接待[0] >= 10, f"{接待[0]} 条")
    # 分不出「全都没结」和「结得正好」—— 所以两头都判
    ck("接待任务里真的有「完结」的", (接待[1] or 0) >= 5, f"完结 {接待[1]} / {接待[0]}")
    ck("接待任务也不是全都结了(得留着在办的)", (接待[1] or 0) < 接待[0],
       f"完结 {接待[1]} / {接待[0]}")
    ck("电话回电够按周统计", 回电[0] >= 20, f"{回电[0]} 条")

    # ⚠️ 这一条是这批数据存在的理由,而**它必须按类型数**。
    # 第一版写的是「op_log 里有 AUTO_CLOSE ≥ 1」—— 造数之前它就**已经是绿的**:
    # 31 条全是「上门沟通」触发的。那条判据分不出
    # 「接待任务真的点亮了那一支」和「上门沟通替它绿着」,
    # **而这正是这批数据要解决的问题本身**。
    # 列名是 `code` 不是 `action`(只读先跑一遍才发现;否则这行会在写完库之后才炸)。
    全收 = c.execute("SELECT COUNT(*) FROM op_log WHERE code='AUTO_CLOSE'").fetchone()[0]
    收 = c.execute(
        "SELECT COUNT(*) FROM op_log o JOIN schedule s "
        "ON s.id=json_extract(o.ctx,'$.by_task') "
        "WHERE o.code='AUTO_CLOSE' AND s.type='接待任务'").fetchone()[0]
    ck("自动收尾是**被接待任务**触发过的(不是只有上门沟通在替它绿着)", 收 >= 1,
       f"接待任务触发 {收} 条 / AUTO_CLOSE 共 {全收} 条")
    # 和 backend/isolation_check.py:248 同口径的业务不变量:客户已经见过面了,
    # 那条预约不该还躺在顾问待办里。
    #
    # ⚠️ **实测过它抓不到什么**:把接待时间写死成 14:00(而预约在 17:00)时,
    # 这一条**照样是绿的** —— 它的 EXISTS 要求 `接待.start >= 预约.start`,
    # 14:00 < 17:00 根本不满足,于是「收不掉」反而让它看不见。
    # 抓那个 bug 的是 `跑()` 里的**逐条对账**(靶子几条就该收尾几条)。
    # 这一条守的是**反方向**:接待确实在预约之后、却没把预约收掉 ——
    # 也就是写口里那段自动收尾被改坏了。两条都要,各守一头。
    开着的 = c.execute("""SELECT COUNT(*) FROM schedule s WHERE s.type='预约到店'
        AND s.status='有效' AND EXISTS(
          SELECT 1 FROM schedule v WHERE v.customer_id=s.customer_id
            AND v.type IN ('上门沟通','接待任务') AND v.status='完结'
            AND v.assignee_no=s.assignee_no AND v.start_ts>=s.start_ts)""").fetchone()[0]
    ck("没有「客户已接待完却还开着的预约」", 开着的 == 0, f"{开着的} 条还开着")
    孤 = c.execute("SELECT COUNT(*) FROM schedule s LEFT JOIN opportunity_task ot "
                   "ON ot.schedule_id=s.id WHERE s.type='商机提醒' AND ot.schedule_id IS NULL"
                   ).fetchone()[0]
    ck("没有「没挂商机的商机提醒」(孤儿任务)", 孤 == 0, f"{孤} 条孤儿")
    总提醒 = c.execute("SELECT COUNT(*) FROM schedule WHERE type='商机提醒'").fetchone()[0]
    ck("商机提醒的样本量够(至少 2 条,才能既结掉一条又留一条开着)", 总提醒 >= 2,
       f"{总提醒} 条 —— **不够不叫这个脚本的问题**:那几条是 "
       f"tools/backfill_opportunity.py 模拟上新再回捞出来的,去看那一步捞到了几条")
    答 = c.execute("SELECT COUNT(*) FROM opportunity_task WHERE answer IS NOT NULL").fetchone()[0]
    ck("商机提醒有真的选了结论的", 答 >= 1, f"{答} 条有结论")
    # ⚠️ 这一条是 2026-10-10 CI 从零建红出来的:`opportunity_obj_check` 的
    # 「搁置等供给的都写清等什么」要**至少一条搁置商机当样本**,
    # 而我结提醒会把商机推离「搁置等供给」。**造数不许把别人的样本吃掉。**
    搁 = c.execute("SELECT COUNT(*) FROM opportunity WHERE status='搁置等供给'").fetchone()[0]
    # ⚠️ 这个脚本的 ck 是 **3 参**(名, 真, 补),而 seed_new_products 的是 4 参(名, 真, n, 补)。
    # 第一版按 4 参写,**复查当场 TypeError 崩掉** —— 而我没发现,因为只跑了 跑()、没跑 复查()。
    # **新加的判据必须自己跑一次**:它崩了和它通过,在「我加了判据」这件事上长得一模一样。
    ck("库里还留着「搁置等供给」的商机(别的检查拿它当样本)", 搁 >= 1,
       f"{搁} 条 —— **一条都不剩的话 opportunity_obj_check 会样本量 0**")
    开 = c.execute("SELECT COUNT(*) FROM schedule WHERE type='商机提醒' AND status='有效'"
                   ).fetchone()[0]
    ck("而且还留着开着的商机提醒(顾问待办里那种样本)", 开 >= 1, f"{开} 条还开着")

    # 逾期:算出来的,不是状态。占比也要判 —— 真实门店逾期是少数
    总, 逾 = c.execute(
        "SELECT COUNT(*), SUM(status='有效' AND substr(end_ts,1,10)<?) FROM schedule "
        "WHERE type<>'到店'", (今,)).fetchone()
    ck("有逾期样本", (逾 or 0) >= 3, f"{逾} / {总}")
    ck("但逾期是少数(过半会让周报一上来就像管理失控)", (逾 or 0) <= 总 * 0.25,
       f"{逾} / {总} = {round(100 * (逾 or 0) / max(总, 1))}%")

    # 规范 C3:任何记录的时间不得早于它所属对象的创建时间
    倒 = c.execute("SELECT COUNT(*) FROM schedule s JOIN customer cu ON cu.id=s.customer_id "
                   "WHERE s.type<>'到店' AND substr(s.start_ts,1,10) < substr(cu.created,1,10)"
                   ).fetchone()[0]
    ck("没有任务早于客户建档(规范 C3)", 倒 == 0, f"{倒} 条时间倒流")
    c.close()
    说(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ 全过'}")
    return 1 if 挂 else 0


def 试跑(说=print):
    """在真库的**副本**上整套跑一遍:造数 → 复查 → 回滚 → 比对还原。真库一个字不动。

    为什么值得有这个档:
      · 造数脚本**只能写真库**(写口的 DB 是模块级常量),而写真库要抢窗口、
        要跟并行会话打招呼。有了副本档,改一行就能全量验一遍,不用等窗口。
      · **回滚能不能还原回去,只有在副本上才敢验。** 真库上验回滚 =
        先把真库弄坏再指望自己写的还原逻辑是对的。
      · 实测它值这个钱:2026-10-10 第一次副本试跑当场抓到三个 bug ——
        靶子接待时间写死(3 条只收掉 1 条,而判据照样绿)、
        `跑()` 无条件 return 0(打印了 ✗ 退出码还是 0)、
        「结掉 2 条」写死(提醒条数是回捞出来的、会变)。
    """
    import shutil, tempfile
    import oplog, tasks                      # noqa: E402  —— 只有这一档要猴补它们
    global DB
    工 = tempfile.mkdtemp(prefix="seed_customer_tasks_")
    副 = os.path.join(工, "lanxiu.db")
    assert os.path.realpath(副) != os.path.realpath(真库)
    shutil.copy2(真库, 副)
    # 猴补模块级 DB —— 照房内先例(backend/report_doc_check.py:48)。
    # ⚠️ **四个都要补**:少补一个的后果是「一半写副本、一半写真库」,
    # 而那种混着的结果看起来完全正常。
    api.DB = tasks.DB = oplog.DB = OM.DB = DB = 副

    def 快照():
        c = sqlite3.connect(f"file:{副}?mode=ro", uri=True)
        out = dict(
            任务=dict(c.execute("SELECT type||'/'||status, COUNT(*) FROM schedule GROUP BY 1")),
            预约=dict(c.execute("SELECT id, status||'|'||COALESCE(summary,'-') FROM schedule "
                                "WHERE type='预约到店'")),
            商机=dict(c.execute("SELECT id, status||'|'||COALESCE(close_reason,'-') FROM opportunity")),
            结论=dict(c.execute("SELECT schedule_id, COALESCE(answer,'-') FROM opportunity_task")),
            台账=c.execute(f"SELECT COUNT(*) FROM {台账}").fetchone()[0],
            客户=c.execute("SELECT COUNT(*) FROM customer").fetchone()[0])
        c.close()
        return out

    try:
        前 = 快照()
        说(f"  副本:{副}")
        说("\n  ① 造数"); rc1 = 跑(说)
        说("\n  ② 复查"); rc2 = 复查(说)
        中 = 快照()
        说("\n  ③ 回滚"); rc3 = 回滚(说)
        后 = 快照()
        说("\n  ④ 回滚还原得回来吗(**真库上不敢验的那一步**)")
        挂 = []
        for k in 前:
            同 = 前[k] == 后[k]
            if not 同:
                挂.append(k)
                差 = ({x: (前[k].get(x), 后[k].get(x)) for x in set(前[k]) | set(后[k])
                       if 前[k].get(x) != 后[k].get(x)} if isinstance(前[k], dict)
                      else f"{前[k]} → {后[k]}")
                说(f"    ❌ {k} 没还原回去:{str(差)[:150]}")
            else:
                说(f"    ✅ {k} 和造数之前一模一样")
        说(f"\n  量:{sum(前['任务'].values())} → {sum(中['任务'].values())} → "
          f"{sum(后['任务'].values())}(回滚后)")
        return 1 if (rc1 or rc2 or rc3 or 挂) else 0
    finally:
        shutil.rmtree(工, ignore_errors=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--做", action="store_true")
    p.add_argument("--回滚", action="store_true")
    p.add_argument("--复查", action="store_true")
    p.add_argument("--试跑", action="store_true", help="在真库的副本上整套跑一遍,不动真库")
    a = p.parse_args()
    print("客户族派单任务 · 接待任务 / 电话回电 / 商机提醒")
    print("=" * 72)
    rc = 0
    if getattr(a, "试跑"):
        rc = 试跑()
    elif getattr(a, "回滚"):
        rc = 回滚()
    elif getattr(a, "做"):
        rc = 跑()
        print("\n复查:")
        rc = 复查() or rc        # 两边都跑完再合并 —— 造数有败时复查的信息最有用
    elif getattr(a, "复查"):
        rc = 复查()
    else:
        print("  先 --试跑(在副本上整套验一遍,不动真库);要动手加 --做;"
              "撤回加 --回滚;只看现状加 --复查")
    sys.exit(rc)
