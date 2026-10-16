#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""往研判队列里造几条**AI 真跑得动**的未研判工单。

    python3 tools/seed_triage_tasks.py          # 试跑:只报会造什么,一个字不写
    python3 tools/seed_triage_tasks.py --写     # 真写
    python3 tools/seed_triage_tasks.py --撤     # 撤掉这个脚本造过的(按 id 前缀)

## 为什么要有这一步

用户 2026-10-15 的原话:「**给我做几个能跑的呀,不能跑的放在研判队列干啥?**」

实测当时:未研判 171 条**全是评价差评**(AI 辅助按业务 2026-10-10 默认关闭),
而 AI 真跑得动的三类(财务人工任务 24 / 客户合并确认 16 / 售后判责 12)
**全部已经研判过了** —— 队列里一条能点的都没有。
> 一个「队列里有 171 条待办」和一个「一条都点不动」,
> **在那个数字上长得一模一样。**

## 三条设计

① **不手造研判结果。** 这个脚本只造**工单和它背后的业务事实**,
   `triage` 表一个字不碰 —— 四段(根因/建议动作/证据/置信度)要模型真跑出来。
   (同 `tools/seed_triage_samples.py` 开头那段:直接 INSERT 一条「置信度=高」,
   等于把看板的分子分母一起编掉。)

② **不写 `truth`。** `truth` 是评测答案表。给新造的单编一份真值,
   等于往评测里塞一道我自己出的题 —— 而我编的「正确答案」不可靠。
   ⚠️ 代价是这些单**没有真值**,所以 `agent/eval.py` 的取样
   2026-10-15 同步加了「补足也只补有真值的」:
   > 一个「这道题模型答错了」和一个「这道题根本没有标准答案」,
   > **在成绩单上长得一模一样。**

③ **能不造新数据就不造。** 客户合并那三条**用库里现成的疑似重复对**
   (`C21xxx` 段本来就是 seed 为这件事造的,其中 6 对还没建过工单)——
   客户表上挂着 RFM、生命周期、门店归属一堆判据,凭空造客户的影响面远大于收益。
   财务和售后要造业务事实(押金单 / 返修单),因为没有现成的「还没人处理」的。

## id 前缀

`DQ`(押金)/ `MQ`(返修),工单号是 `T` + 它。**带 Q 是为了一眼认出来是这个脚本造的**,
也是 `--撤` 的依据。合并那三条用 `TMQ-M01..03`。
"""
import argparse
import os
import sqlite3
import sys

这里 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(这里)
sys.path[:0] = [os.path.join(根, "backend"), os.path.join(根, "knowledge"), 根]

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

import refund_replay as _RR          # 回测口径:出事时的样子(状态只有那儿一份)

# 退款失败的真因 —— 照 `backend/seed.py` 里那六种的形状,取其中三种。
# 每一种的 resp_code 不同,模型查 get_refund_trace 才有得分辨。
退款真因 = [
    ("渠道超时但实际已退", [("TIMEOUT", "渠道响应超时")] * 3, True),
    ("原支付渠道已注销", [("ACCOUNT_CLOSED", "收款账户已注销")] * 3, False),
    ("商户账户余额不足", [("INSUFFICIENT_BALANCE", "商户账户余额不足")] * 3, False),
]
# 返修问题 —— 用库里已有的 issue 取值,别自造新词(知识库的判定表按这些词查)
返修问题 = [("盘扣脱线", "处理中"), ("面料起球", "待处理"), ("尺寸需调整", "待处理")]


def 今(c):
    """世界的当下 —— **不是机器此刻**。造出来的单要和这个世界在同一条时间线上。"""
    import worldclock as W
    return W.当下().strftime("%Y-%m-%d %H:%M")


def 下一个号(c, 表, 前缀):
    """`DQ9001` 之后是 `DQ9002` —— **从库里现扫,不写死**。

    ⚠️ 原来三个造数函数把序号写死成 `900{i+1}`,一次只能造那固定三条。
    2026-10-15 接上每日造数(「不够 3 条就补到 3 条」)之后,
    写死的号第二天就会撞上昨天造的那条 —— 而撞号的表现是
    「INSERT 失败」或者更糟:**跳过了,于是今天一条都没补上,而日志说补了**。
    """
    r = c.execute(f"SELECT id FROM {表} WHERE id LIKE ? ORDER BY id DESC LIMIT 1",
                  (f"{前缀}9%",)).fetchone()
    n = int(r[0][len(前缀):]) if r else 9000
    return f"{前缀}{n + 1}"


def 还剩几条能跑的(c):
    """队列里「非差评 · 待处理 · 还没研判过」的工单 —— 用户真正点得动的那些。"""
    return c.execute("""SELECT count(*) FROM task t WHERE t.status='待处理'
                        AND t.type <> '评价差评'
                        AND NOT EXISTS(SELECT 1 FROM triage r WHERE r.task_id=t.id)"""
                     ).fetchone()[0]


def 已经有的(c):
    return {r[0] for r in c.execute(
        "SELECT id FROM task WHERE id LIKE 'TDQ%' OR id LIKE 'TMQ%'")}


def 造财务(c, 现在, 真写, 要几条=3):
    """押金退款失败 → 财务人工任务。业务事实:押金单 + 收款流水 + 三次失败轨迹。"""
    出 = []
    cust = [r[0] for r in c.execute(
        "SELECT id FROM customer WHERE archived=0 ORDER BY id LIMIT 3")]
    for i, (因, traces, 已退) in enumerate(退款真因[:要几条]):
        did = 下一个号(c, "deposit", "DQ"); tid = f"T{did}"
        cid = cust[i % len(cust)]
        amt = [1200.0, 800.0, 2000.0][i]
        if 真写:
            # 状态**从回测口径那边取**(`knowledge/refund_replay.出事时押金状态`)——
            # 评测要把这笔单还原成「出事时的样子」,而「出事时是什么状态」只能有一份。
            # 两边各写一份 '退款失败' 的话,哪天造数改了状态,还原出来的就是**另一个场景**,
            # 而它不报错:题照样出得来,只是不再是出事时那道题。
            c.execute("INSERT INTO deposit(id,customer_id,appt_id,amount,status,idem_key,created,updated)"
                      " VALUES(?,?,?,?,?,?,?,?)",
                      (did, cid, None, amt, _RR.出事时押金状态, f"IDEM-{did}", 现在[:10], 现在[:10]))
            c.execute("INSERT INTO payment_flow(id,deposit_id,direction,amount,channel,channel_serial,status,ts)"
                      " VALUES(?,?,'in',?,'微信支付',?,'success',?)",
                      (f"PF{did}I", did, amt, f"WX{9000000000 + i}", 现在))
            if 已退:   # 「渠道超时但实际已退」:正向查询显示已退,所以真有一条出账流水
                c.execute("INSERT INTO payment_flow(id,deposit_id,direction,amount,channel,channel_serial,status,ts)"
                          " VALUES(?,?,'out',?,'微信支付',?,'success',?)",
                          (f"PF{did}O", did, amt, f"WX{9100000000 + i}", 现在))
            for a, (code, msg) in enumerate(traces, 1):
                c.execute("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key)"
                          " VALUES(?,?,?,'微信支付',?,?,?,?)",
                          (did, a, 现在, amt, code, msg, f"IDEM-{did}"))
            # 工单状态和「出事时」那份口径同一个来源(见上面押金状态那段的理由):
            # 评测要把工单行还原成出事时的样子,而闭环会把它改成「已处理」
            # 并且**把 AI 那段错判原文写进 summary** —— 那正是这道题的错答案。
            c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
                      (tid, _RR.工单类型, did, _RR.出事时工单状态, 现在, None))
        出.append((tid, f"押金 {did} · {因} · {amt} 元 · 客户 {cid}"))
    return 出


def 造合并(c, 现在, 真写, 要几条=3):
    """疑似同一人 → 客户合并确认。**不造新客户**,用库里还没建过工单的重复对。"""
    出 = []
    对 = c.execute("""SELECT a.id, b.id, a.name FROM customer a
                      JOIN customer b ON a.name=b.name AND a.birthday=b.birthday AND a.id<b.id
                      WHERE a.birthday IS NOT NULL AND a.archived=0 AND b.archived=0
                        AND NOT EXISTS(SELECT 1 FROM task t WHERE t.type='客户合并确认'
                                       AND t.ref_id = a.id || '|' || b.id)
                      ORDER BY a.id, b.id LIMIT ?""", (要几条,)).fetchall()
    if not 对:
        出.append(("—", f"{Y}库里没有「还没建过工单」的疑似重复对 —— 这不叫失败,是已经都建过了{D}"))
    _m = c.execute("SELECT id FROM task WHERE id LIKE 'TMQ-M%' ORDER BY id DESC LIMIT 1").fetchone()
    _起 = int(_m[0].split("M")[-1]) if _m else 0
    for i, (aid, bid, name) in enumerate(对):
        tid = f"TMQ-M{_起 + i + 1:02d}"
        if 真写:
            c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,'待处理',?,?)",
                      (tid, "客户合并确认", f"{aid}|{bid}", 现在, f"疑似同一人:{name}"))
        出.append((tid, f"{aid} ↔ {bid} · {name}"))
    return 出


def 造售后(c, 现在, 真写, 要几条=3):
    """客户报修 → 售后判责。业务事实:返修单(挂在真实订单的真实行上)。"""
    出 = []
    单 = c.execute("""SELECT o.id, o.customer_id, o.shop, o.advisor_no, i.id, i.name
                      FROM ordr o JOIN ordr_item i ON i.order_id=o.id
                      -- ⚠️ **只认「完成」且完成于今天之前的单**(业务规则 R5:
                      --    维保只能发生在订单完成之后,`backend/aftersale_rule_check.py` 盯着)。
                      --    踩过两次:① 第一版写 `IN ('完成','待完成','已发货')` —— 状态就不对;
                      --    ② 第二版只加了 `status='完成'`,仍然红,理由变成
                      --    「MQ9001 申请于今天 12:45,而订单今天 19:57 才完成」——
                      --    我拿「世界当下」(世界日期 + **机器时刻**)当报修时间,而演示世界的
                      --    今天是**一整天已经过完的**,订单完成时刻铺在 19:57。
                      --    > 同一天之内,这两种时刻没有可比的先后(见 factory_inbox.py 那条)。
                      --    避开今天完成的单,报修时间就必然晚于订单完成。
                      WHERE o.kind='定制品订单' AND o.status='完成'
                        AND o.finished_at IS NOT NULL AND substr(o.finished_at,1,10) < ?
                        AND NOT EXISTS(SELECT 1 FROM maintain m2 WHERE m2.order_id=o.id AND m2.id LIKE 'MQ%')
                      ORDER BY o.id DESC LIMIT ?""", (现在[:10], 要几条)).fetchall()
    for i, (oid, cid, shop, adv, item_id, item_name) in enumerate(单):
        mid = 下一个号(c, "maintain", "MQ"); tid = f"T{mid}"
        issue, st = 返修问题[i % len(返修问题)]
        if 真写:
            c.execute("""INSERT INTO maintain(id,order_id,customer_id,item,status,issue,shop,advisor_no,
                                              created,updated,ext_system,synced_at,order_item_id)
                         VALUES(?,?,?,?,?,?,?,?,?,?,'售后/维保系统',?,?)""",
                      (mid, oid, cid, item_name, st, issue, shop, adv, 现在, 现在, 现在, item_id))
            c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,'待处理',?,?)",
                      (tid, "售后判责", mid, 现在, f"{item_name} · {issue}"))
        出.append((tid, f"返修 {mid} · {issue} · 订单 {oid}"))
    return 出


def 补足(c, 现在, 目标=3, 真写=True, 记=None):
    """**不够就补到目标数** —— 给每日造数用(用户 2026-10-15 拍)。

    队列里能点的工单会被用户一条条跑掉;跑完就又只剩评价差评(AI 默认不跑它)。
    固定每天造 N 条的话**会堆积** —— 没人研判时一周就是 21 条演示单,
    反而把真实业务淹掉。所以先数再补:数一下还剩几条能跑的,不足才补。

    ⚠️ **每日造数调它时刻意不传 `记`**(台账回调),所以 `daily_fresh --回滚` 撤不掉这几条。
    那是想清楚的:回滚撤的是「今天造的业务数据」,而这几条的目的是
    **让队列始终有能点的** —— 它和哪天造的没关系。
    记进台账的话回滚之后队列又空了,那个目的也跟着没了。
    而且台账按 (表, 键值) 撤,撤得掉工单和押金单,**撤不掉 `refund_trace`**
    (它没有稳定 id)—— 实测回滚后留下 3 条「退款失败却没有工单」的孤儿押金单。
    要撤用 `--撤 --写`,它按 id 前缀连业务事实一起清,实测零残留。
    """
    剩 = 还剩几条能跑的(c)
    缺 = max(0, 目标 - 剩)
    if not 缺:
        return 剩, []
    出 = []
    # 三类轮着补,优先补「业务事实不用新造」的合并类
    for f, n in ((造合并, min(缺, 1)), (造财务, min(max(0, 缺 - 1), 1)),
                 (造售后, max(0, 缺 - 2))):
        if n > 0:
            出 += [x for x in f(c, 现在, 真写, 要几条=n) if "跳过" not in x[1]]
    if 记:
        for tid, _ in 出:
            记(tid)
    return 剩, 出


def 撤(c, 真写):
    """撤掉这个脚本造过的 —— 按 id 前缀,不碰别人的。"""
    ts = [r[0] for r in c.execute(
        "SELECT id FROM task WHERE id LIKE 'TDQ%' OR id LIKE 'TMQ%'")]
    if not 真写:
        print(f"  会撤掉 {len(ts)} 条工单及其业务事实:{ts}")
        return len(ts)
    for t in ts:
        c.execute("DELETE FROM triage WHERE task_id=?", (t,))   # 研判过的也一起撤
    c.execute("DELETE FROM task WHERE id LIKE 'TDQ%' OR id LIKE 'TMQ%'")
    for tb, 列, 前缀 in (("refund_trace", "deposit_id", "DQ"), ("payment_flow", "deposit_id", "DQ"),
                       ("deposit", "id", "DQ"), ("maintain", "id", "MQ")):
        c.execute(f"DELETE FROM {tb} WHERE {列} LIKE '{前缀}%'")
    c.commit()
    print(f"  撤掉了 {len(ts)} 条工单及其业务事实")
    return len(ts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--库", default=os.path.join(根, "backend", "lanxiu.db"))
    ap.add_argument("--写", action="store_true")
    ap.add_argument("--撤", action="store_true")
    a = ap.parse_args()
    print("往研判队列造几条 AI 跑得动的未研判工单")
    print("=" * 72)
    c = sqlite3.connect(a.库)
    现在 = 今(c)
    print(f"库:{a.库}\n世界的当下:{现在}")
    if a.撤:
        撤(c, a.写); c.close()
        print(f"\n{Y}📌 试跑,没动{D}" if not a.写 else f"\n{G}✅ 撤完了{D}")
        raise SystemExit(0)
    print(f"已有这个脚本造的:{len(已经有的(c))} 条\n")
    总 = []
    for 名, f in (("财务人工任务", 造财务), ("客户合并确认", 造合并), ("售后判责", 造售后)):
        出 = f(c, 现在, a.写)
        print(f"  {名}({len(出)} 条)")
        for tid, 说 in 出:
            print(f"    · {tid}  {说}")
        总 += 出
    if a.写:
        c.commit()
    n = c.execute("""SELECT count(*) FROM task t WHERE t.status='待处理'
                     AND t.type <> '评价差评'
                     AND NOT EXISTS(SELECT 1 FROM triage r WHERE r.task_id=t.id)""").fetchone()[0]
    c.close()
    print()
    print(f"  库里现在「非差评 · 待处理 · 没研判过」的工单:{n} 条")
    if not a.写:
        print(f"\n{Y}📌 这是试跑,一个字都没写进去。确认后加 `--写`;造错了用 `--撤 --写`。{D}")
    if a.写:
        # ⚠️ **造完一定要跑一轮全量。** 2026-10-15 这个脚本第一版造出来的数据
        # 连着两次违反业务规则,而**脚本自己全程是绿的**:
        #   ① 维保单挂在「已发货」的订单上 → R5「维保只能发生在订单完成之后」红
        #   ② 改成只挂「完成」的之后还是红:我拿「世界当下」(世界日期 + 机器时刻)
        #      当报修时间,而演示世界的今天是一整天已经过完的,订单 19:57 才完成,
        #      于是「客户报修」早于「订单完成」6 小时。
        # > 一个「造出来的数据合规」和一个「我没去跑那条判据」,
        # > **在这个脚本的输出上长得一模一样。**
        print(f"\n{Y}📌 造完请跑一轮 `./check.sh` —— 造出来的数据要守业务规则,"
              f"而这个脚本自己验不了那些(R5 维保时间、R2 退款链路…都在门禁里){D}")
    print(f"\n{G}✅ {len([x for x in 总 if '跳过' not in x[1]])} 条"
          f"{'已写入' if a.写 else '试跑通过'}{D}")
