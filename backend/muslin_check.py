#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""白坯试衣的检查 —— **「没走流程」和「走了没拿到确认」不许混成一个。**

这套检查钉的是三件事,每一件都是「两样东西长得一模一样而含义完全不同」:

    **没记录 vs 没签字**   一个判我方(流程没走)、一个回落到量体记录 —— **方向相反**
    **没试 vs 还没到试**   开裁之后没试才是问题;开裁之前没试是**时候没到**
    **不知道 vs 不必试**   算不出的不许归成「不必试」—— 那是把问题盖住

## 为什么「算不出」要专门查

`muslin.归档()` 在「不知道开没开裁」时返回 `None`。两个默认值都是错的:

    默认「还没开裁」 → 把一单**该试没试**悄悄判成不判责(**盖住问题**)
    默认「开裁了」   → 把一单**还没到时候**判成我方(**冤枉自己**)

这和 `grading.序号()` 认不出返回 `None` 不返回 `0` 是同一条:
**一个默认值会把「不知道」变成一个看起来很确定的结论。**

## 新加的两行判据现在没有用例,这件事是**明账**

`liability_check` ② 会报 ⚠️:「尺寸偏差 · 试衣已签字」和「尺寸偏差 · 该试没试」
**一条在办工单都没命中**。要让它们有用例得新建维修工单**并给它写真值** ——
而真值是**故意的第二套实现**,自己写等于和自己对账。所以留给业务,
这里只钉住「**欠的用例数只许降不许涨**」。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge"),
                os.path.join(ROOT, "agent")]

# ── 咬合记录 ────────────────────────────────────────────────────────────
咬合 = [
    ("让 归档() 在「不知道开没开裁」时默认成「还没开裁」",
     "不知道开没开裁时,归档要返回算不出"),
    ("把「已试未签」也归成「该试没试」(拿查不到记录当没签字)",
     "试了没签不许归成该试没试"),
    ("把 该试衣() 的门槛依据那句「业务没确认过」删掉",
     "该试的结论要带着「这条线业务没确认过」"),
    ("让 judge() 在试衣已签时仍按量体记录判",
     "试衣已签压过量体记录"),
    ("让 judge() 在该试没试时仍按量体记录判",
     "该试没试压过量体记录"),
    ("把 seed_fitting 里「该试没试」那条也建上记录(四种状态少一种)",
     "四种试衣状态每种都要有活用例"),
    ("把 TL30 里「不许拿查不到记录当没签字」那句删掉",
     "TL30 说清「没记录」和「没签字」不是一回事"),
    ("拆掉「不给下单日就判不了」那道拦截(又回到替调用方取今天)",
     "不给下单日就说判不了"),
    ("按配置判() 不把下单日传给工期推算(排队退回按今天算)",
     "同一件衣服按下单日算"),
    ("让 能不能开裁() 在「判不了该不该试」时放行",
     "判不了该不该试的,不许放行开裁"),
    ("把看板上「开裁这道闸」那段说明删掉",
     "看板要说清开裁这道闸会拦"),
    ("把旅程在开裁前真登记的试衣记录删掉(造样本脚本整表清空时就是这样)",
     "经系统开裁的单,每一件都过了闸(已试已签或不必试)"),
]

# **欠的端到端用例数上限** —— 新加的两行判据现在一条在办工单都没命中。
# 只许降不许涨:业务补了用例就把这个数改小,**别把检查改掉**。
没用例的判据上限 = 2

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("白坯试衣 · 检查")
    print("=" * 84)
    import muslin as M, liability as L, api, prompts, seed_fitting as SF
    import liability_check as LC

    # ── ① 归档:不知道就说不知道 ──────────────────────────────────────
    ck("不知道开没开裁时,归档要返回算不出",
       M.归档(True, None, False, False) is None, 1,
       "**两个默认值都是错的**:默认没开裁会盖住「该试没试」,"
       "默认开裁了会把「还没到时候」冤枉成我方")
    ck("开了裁没试 → 该试没试", M.归档(True, True, False, False) == "该试没试", 1)
    ck("没开裁没试 → 还没到时候", M.归档(True, False, False, False) == "还没到时候", 1,
       "**没试不是问题,时候没到** —— 白坯排在裁剪之前")
    ck("试了没签不许归成该试没试",
       M.归档(True, None, True, False) == "已试未签", 1,
       "前者流程没走(**我方**),后者流程走了确认没拿到(回落到量体记录)—— "
       "**方向相反**")
    ck("不必试的不看开没开裁", M.归档(False, None, None, None) == "不必试", 1)

    # ── ② 该不该试:结论要带着「业务没确认过」─────────────────────────
    a, w = M.该试衣(30, ())
    ck("该试的结论要带着「这条线业务没确认过」", a and "没确认过" in (w or ""), 1,
       "这条线**一直在影响客户看到的交期**,而没有人确认过")
    ck("门槛依据说清了 md 里只有一句话没有数",
       "没有给数" in M.门槛_依据 or "没有数" in M.门槛_依据, 1)

    # **口径只有一个来源** —— leadtime 不许自己再判一遍
    src = open(os.path.join(ROOT, "knowledge", "leadtime.py"), encoding="utf-8").read()
    ck("工期推算改调口径模块,不自己判一遍",
       "muslin" in src and "该试衣" in src, 1,
       "它原来是 estimate() 里一个叫 heavy 的局部变量 —— "
       "**没有名字的判断,别处要用只能抄一份**")
    e = None
    import leadtime
    e = leadtime.estimate(pattern="PT06", size="M", material="MT02",
                          crafts=["KF05", "KF04", "KF09"], scope="整幅",
                          craft_names={})
    ck("工期推算把这个判断露出来了", e.get("要白坯试衣") is True, 1,
       "露出来之前,谁想知道「这单该不该试衣」只能去匹配一个段名")

    # ── ③ 判责:试衣压过量体记录 ──────────────────────────────────────
    j1 = L.judge("尺寸需调整", measure_full=False, 试衣状态="已试已签")
    ck("试衣已签压过量体记录", j1["责任"] == "客方", 1,
       "量体记录不全本该判我方 —— 而**他本人穿过并且认可了**")
    j2 = L.judge("尺寸需调整", measure_full=True, 试衣状态="该试没试")
    ck("该试没试压过量体记录", j2["责任"] == "我方", 1,
       "**这一行是往我方判的,故意的** —— 一条只往有利方向走的判据,业务不会信")
    j3 = L.judge("尺寸需调整", measure_full=True, measure_remote=True, 试衣状态="已试已签")
    ck("试衣已签也压过「远程量体」", j3["责任"] == "客方", 1,
       "远程量体讲的是**量的方式**,而他已经亲自试穿过 —— 方式不再是争点")
    j4 = L.judge("尺寸需调整", measure_full=True)
    ck("没查试衣记录时要把这个缺口说出来",
       "没查白坯试衣记录" in (j4["依据"] or ""), 1,
       "一个「该试没试」的重工单量体记录完整时会被判成客方 —— "
       "**不改结论(那会把老用例judge反),而是把缺口说出来**")

    # ── ④ 数据:该试的是算出来的,四种状态都有活用例 ────────────────────
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row
    该, 不必, 判不了 = SF.该试的行(c)
    ck("该试衣的行是按真规则算出来的,不是挑的", len(该) > 0, len(该) + len(不必) + len(判不了),
       f"该试 {len(该)} / 不必 {len(不必)} / 判不了 {len(判不了)} —— "
       f"**判不了的留着不猜**(那 {len(判不了)} 行的商品没挂版型)")

    # ── ④·2 **按下单那天算,不随「今天」变**(用户 2026-09-19 定)────────────
    #   原来不传日期,工期推算自己取今天 —— 判责现场里的「装饰工序最慢 N 天」一天少一天,
    #   跌破 25 天那天「该试」就翻成「不必试」,没有任何人动过数据。
    #   验法:同一批真实订单行,把「今天」换成相隔两个月的两天,判断和理由必须一字不差。
    ck("不给下单日就说判不了(不替调用方取今天)",
       M.按配置判("PT06", "MT02", ["KF02"], on=None)[0] is None, 1)
    import datetime as _real, types as _ty, capacity as _cap, leadtime as _lt
    def _钉今天(d):
        class _FD(_real.date):
            @classmethod
            def today(cls): return d
        m = _ty.ModuleType("dt"); m.__dict__.update(_real.__dict__); m.date = _FD
        _cap.dt = m; _lt.dt = m
    mt = {r["name"]: r["code"] for r in c.execute("SELECT code,name FROM material WHERE width_cm IS NOT NULL")}
    kfm = {r["name"]: r["code"] for r in c.execute("SELECT code,name FROM craft")}
    names = {r["code"]: r["name"] for r in c.execute("SELECT code,name FROM craft")}
    样 = []
    for r in list(c.execute("""SELECT i.id, i.name, p.pattern, o.created FROM ordr_item i
            JOIN ordr o ON o.id=i.order_id JOIN product p ON p.spu=i.spu
            WHERE o.kind='定制品订单' AND p.pattern IS NOT NULL ORDER BY i.id LIMIT 40""")):
        ch = list(c.execute("SELECT kind,material,part FROM item_part_choice WHERE item_id=?", (r["id"],)))
        fab = [x for x in ch if x["kind"] == "面料" and x["material"] in mt]
        if fab:
            样.append((r["pattern"], mt[fab[0]["material"]],
                       sorted({kfm[x["material"]] for x in ch if x["kind"] == "工艺" and x["material"] in kfm}),
                       "整幅" if any(w in r["name"] for w in ("重工", "婚服", "满工")) else "局部",
                       r["created"]))
    def _判一遍(d):
        _钉今天(d)
        return [M.按配置判(p, m, k, s, None, names, on=o) for p, m, k, s, o in 样]
    try:
        甲, 乙 = _判一遍(_real.date(2026, 9, 18)), _判一遍(_real.date(2026, 11, 15))
    finally:
        _cap.dt = _real; _lt.dt = _real
    变 = [i for i, (x, y) in enumerate(zip(甲, 乙)) if x != y]
    ck("同一件衣服按下单日算,「今天」换成两个月后判断和理由一字不差", not 变, len(样),
       f"变了 {len(变)} 件,例:{甲[变[0]][1][:40]} → {乙[变[0]][1][:40]}" if 变 else
       "**试不试是接单时定的** —— 随日历翻页而变的判断,会让判责结论自己变")

    q = api.fitting_queue()
    有 = {k for k in q if k in M.状态 or k == "**算不出**"}
    ck("四种试衣状态每种都要有活用例",
       {"该试没试", "已试未签", "已试已签", "还没到时候"} <= 有, len(有),
       f"看板上有 {sorted(有)} —— **一条永远命中不了的判据和没有这条判据一样**,"
       f"而且它看起来是有的(seed.py 第 2117 行那笔账)")

    # 「没记录」和「没签字」在库里真的是两种行
    没签 = c.execute("SELECT COUNT(*) n FROM fitting WHERE signed=0").fetchone()["n"]
    ck("库里真的有「有记录但没签字」的行", 没签 > 0, 没签,
       "**没有这种行的话,「拿查不到记录当没签字」这个错永远测不出来**")

    # ── ④b 开裁那道闸 ────────────────────────────────────────────────
    # ⚠️ 这道闸现在**没有东西可拦**:`api.WRITE_TOOLS` 里没有任何
    # 「推进订单状态」的写口,订单状态是种子数据直接写的。
    # **「有一道闸」和「有一个会拦的闸」是两件事**,而它们在代码里
    # 长得一模一样:一个能跑的判断函数。所以下面第二条专门查那句话在不在。
    ck("该试没试的不许开裁", M.能不能开裁(True, False, False)[0] == "不可以", 1,
       "白坯排在裁剪之前 —— **裁下去就没有回头路**")
    ck("判不了该不该试的,不许放行开裁",
       M.能不能开裁(None, None, None)[0] == "判不了", 1,
       "**判不了不等于可以** —— 和 order_gate.能不能下单 同一条")
    ck("试了没签字也不许开裁(业务 09-22)",
       M.能不能开裁(True, True, False)[0] == "不可以"
       and "没签字" in M.能不能开裁(True, True, False)[1], 1,
       "签字是责任转移点 —— **没签就裁,尺寸争议只能门店自己担**,而裁下去没有回头路")
    ck("必试范围是业务定的三类,判不了不当不必",
       M.新规范围 == ("重工", "全定制", "婚服") and M.必试(False, None, False)[0] is None, 1,
       "不知道体型标不标准,和体型标准是两件事")
    # 原来这里钉的是「看板要说清这道闸现在拦不住任何东西」—— 那时没有写口推进裁剪。
    # 09-22 起开裁有了写口、闸挂在订单状态机上,**那句话变成了假话**,就得跟着翻过来:
    # 一句写着「拦不住」的看板会让人去绕一道其实在拦的闸,反过来也一样。
    # 真拦不拦得住由 fitting_write_check 在库副本上实测,这里只钉看板说的是不是这回事。
    ck("看板要说清开裁这道闸会拦",
       "会拦" in str(q.get("开裁这道闸") or "") and not any("拦不住" in str(k) for k in q), 1,
       "**说拦不住而其实在拦,和说在拦而其实拦不住,一样误导人**")
    待 = q.get("待开裁的单") or {}
    ck("看板列出了待生产的单能不能开裁", any(k in 待 for k in ("可以", "不可以", "判不了")),
       sum((待.get(k) or {}).get("单数", 0) for k in ("可以", "不可以", "判不了")),
       "店长要知道哪几单卡在试衣上、卡在哪一件")
    # ── 不变量:**经系统开裁的单,每一件都过了闸** ────────────────────────
    # 闸挂在订单状态机上,所以有开裁记录(cut_at)的单,每一件只可能是「已试已签」或「不必试」。
    # 出现别的档 = 要么闸被绕过了,要么有东西在开裁之后删了试衣记录 ——
    # 09-22 就撞上后一种:造试衣样本的脚本整表清空,把旅程真登记的记录一起删了,
    # 于是 20 件「经系统开裁却查不到试衣」,**而它们在看板上和真的违规长得一模一样**。
    _裁 = c.execute("SELECT o.id, o.status, i.id iid FROM ordr o JOIN ordr_item i ON i.order_id=o.id "
                   "WHERE o.cut_at IS NOT NULL AND o.kind='定制品订单'").fetchall()
    _坏 = [(r["id"], r["iid"], st) for r in _裁
           for st in [api._白坯试衣(r["id"], None, r["status"], item_id=r["iid"]).get("归到哪一档")]
           if st not in ("已试已签", "不必试")]
    ck("经系统开裁的单,每一件都过了闸(已试已签或不必试)", not _坏, len(_裁),
       f"{len(_坏)} 件不是:{_坏[:3]} —— **闸被绕过了,或开裁之后有东西删了试衣记录**" if _坏 else
       "闸挂在状态机上,有开裁记录就只可能是这两档")
    越 = q.get("⚠️ 已经越过这道线的") or {}
    ck("已经越过线的要单独点出来", bool(越.get("件数")), 越.get("件数") or 0,
       f"{越.get('件数')} 单已经开裁而没试衣 —— **不是待办,是已经发生的违规**;"
       f"能做的不是补试衣(已经裁了),是知道出争议时责任在我方")

    # ── ⑤ 规矩说到了,而且和工具在同一个角色身上 ────────────────────────
    tl30 = [x for x in prompts.TASK_RULES if x.id == "TL30"]
    ck("TL30 和 fitting_queue 在同一个角色身上",
       bool(tl30) and "fitting_queue" in (tl30[0].needs if tl30 else ()),
       len(prompts.TASK_RULES),
       "**「工具给了,规矩没给」比「工具没给」更危险**")
    文 = tl30[0].text if tl30 else ""
    ck("TL30 说清「没记录」和「没签字」不是一回事",
       "查不到记录" in 文 and "没签字" in 文, 1)
    for 词, 为什么 in (("责任转移", "签字是责任转移点"),
                      ("三类", "必试范围是业务 09-22 定的三类"),
                      ("推导", "重工那条的门槛数仍是推导的"),
                      ("对外动作", "约试衣、催签字是人的动作")):
        ck(f"TL30 里说到「{词}」", 词 in 文, 1, 为什么)

    d = [x for x in api.SHOP_SCHEMAS if x["name"] == "fitting_queue"][0]["description"]
    for 词 in ("该试没试", "责任转移", "三类", "会拦"):
        ck(f"工具描述里说到「{词}」", 词 in d, 1)

    # ── ⑥ 新加的两行判据欠着用例,这件事是明账 ──────────────────────────
    _bad, _rows, missing = LC.run(verbose=False)
    ck("欠端到端用例的判据不超过上限", len(missing) <= 没用例的判据上限,
       len(LC.EXPECT),
       f"{len(missing)} 条没有在办用例(上限 {没用例的判据上限})—— "
       f"**只许降不许涨**。补用例要新建工单**并写真值**,"
       f"而真值是故意的第二套实现,自己写等于和自己对账,所以留给业务")

    print()
    if FAIL:
        print(f"\033[31m❌ 白坯试衣 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print("\033[32m✅ 白坯试衣全部符合预期\033[0m")
    print(f"    该试衣 {len(该)} 行(算出来的,不是挑的),四种状态都有活用例;"
          f"新加的两行判据还欠 {len(missing)} 条端到端用例 —— **记成明账**。")


if __name__ == "__main__":
    main()
