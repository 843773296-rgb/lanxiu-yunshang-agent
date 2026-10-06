#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天查订单 · **卡片那一头**的对账(`orders_by_date` 工具)。

弹窗那一头在 `backend/chat_order_check.py`。**两头都要验,而且理由不同:**

    卡片那头   工具按身份取数,查的是「这一批给对了吗」
    弹窗那头   按订单号取数,查的是「服务端拦不拦越权」

## ⚠️ 这份文件为什么存在

`backend/chat_order_check.py` 每次跑完都打印一行
「卡片那一头在 `tools/chat_order_cards_check.py`」—— 而在 2026-10-06
补上这个文件之前,**它指着一个不存在的路径**。

> 一句「那一头在某个文件里」而那个文件不存在,和一句指着真文件的,
> **在那行输出上长得一模一样** —— 而读它的人会去找、找不到,
> 然后以为是自己搞错了。

(这个项目记过同一个形状:测试文件头写着「单独 `make test-browser`」
而那个 make 目标并不存在,于是**那份测试没有任何入口能跑它** ——
和没有这份测试是一回事,只是它躺在目录里看起来像有覆盖。)

## 这一组钉五件事

**① 三档范围各给对了。** 并且**不是靠「它返回了东西」判**,
   而是把返回的每一张卡片拿 `knowledge/order_scope` 逐条复核。
   > 一份「范围写对了」的清单,和一份「where 条件漏了一半」的,
   > **在「它返回了 20 张卡片」这件事上长得一模一样。**

**② 总数不是卡片数。** 一月 1854 单而卡片只给前 20 张。
   > 一份只给了前 20 张的结果,和一份「这个月就 20 单」的,
   > **在那一屏卡片上长得一模一样。**

**③ 顾问那一档两个数分开报**,而且三个数对得上
   (名下客户 + 经手的 − 重叠 = 总数)。

**④ 歧义不猜。** 「一月」要走「判不了」,**并且两种读法的单数都给出来** ——
   只回一句「说不清」等于把人空手打回。

**⑤ 绝对区间和相对天数互斥**,而且相对模式**没被改坏**。
"""
import os
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "backend"))
sys.path.insert(0, os.path.join(根, "knowledge"))

import api
import order_scope as 范

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
坏, 过 = [], [0]


# ── 咬合记录 ──────────────────────────────────────────────────────────
咬合 = [
    ("把卡片那头的 where 条件改松(顾问能看到别人的单)",
     "每张卡片都通过逐条复核"),
    ("把「总数」改成 len(卡片)(只给前 20 张却报成 20 单)",
     "总数不是卡片数"),
    ("让「一月」这类说法直接按某一种读法查(不再问)",
     "认不出的说法 → 报格式错,**不是「判不了」**"),
    ("相对天数那条歧义也一并猜掉(不给方向就默认往前)",
     "相对天数不给方向 → 仍然走「判不了」"),
    ("把绝对区间和相对天数同时给时静默挑一个",
     "绝对区间和相对天数同时给 → 报错"),
]


def ck(说, ok, 附=""):
    if ok:
        过[0] += 1
        print(f"  {G}✅{D} {说}  {附}")
    else:
        坏.append(说)
        print(f"  {R}❌{D} {说}  {附}")


def 以(人):
    api._ME.set(dict(人))


def main():
    print("聊天查订单 · 卡片那一头")
    print("=" * 92)
    顾们 = api._rows("select no,name,role,shop from staff "
                   "where role='顾问' and status='启用'")
    店们 = api._rows("select no,name,role,shop from staff "
                   "where role='店长' and status='启用'")
    运们 = api._rows("select no,name,role,shop from staff "
                   "where role='总部运营' and status='启用'")
    if not (顾们 and 店们 and 运们):
        print(f"  {Y}⏸{D} 库里人不够 —— **不适用,不是通过**")
        return 0
    甲, 长, 运 = dict(顾们[0]), dict(店们[0]), dict(运们[0])
    月 = api._rows("select substr(created,1,7) m, count(*) n from ordr "
                  "where created is not null group by m "
                  "having n > 200 order by n desc limit 1")
    if not 月:
        print(f"  {Y}⏸{D} 找不到单量够大的月份(要 >200 单才验得出"
              f"「总数 ≠ 卡片数」)—— **不适用**")
        return 0
    某月, 该月单数 = 月[0]["m"], 月[0]["n"]
    print(f"  拿 {某月} 验(全库这个月 {该月单数} 单)\n")

    # ── ① 三档范围:**逐条复核**,不靠「它返回了东西」 ──────────
    print("▸ ① 三档范围各给对了 —— 每张卡片拿口径逐条复核")
    归 = {r["id"]: r["advisor_no"] for r in
         api._rows("select id, advisor_no from customer")}
    for 人 in (甲, 长, 运):
        以(人)
        d = api.TOOLS["orders_by_date"](月份=某月, limit=200)
        卡 = d.get("卡片") or []
        ck(f"{人['role']}:拿到了卡片", bool(卡) or d.get("总数") == 0,
           f"{len(卡)} 张 / 总数 {d.get('总数')}")
        不该给 = [c["订单"] for c in 卡 if not 范.看得到吗(
            角色=人["role"], 工号=人.get("no"), 门店=人.get("shop"),
            单的门店=c.get("门店"), 单的顾问=c.get("顾问"),
            客户归属顾问=归.get(c.get("客户号")))[0]]
        ck(f"{人['role']}:每张卡片都通过逐条复核", not 不该给,
           f"不该给的 {不该给[:3]}")
        # 标签也要和口径算出来的一样
        标不符 = [c["订单"] for c in 卡 if c.get("标", []) != 范.标(
            角色=人["role"], 工号=人.get("no"), 单的顾问=c.get("顾问"),
            客户归属顾问=归.get(c.get("客户号")))]
        ck(f"{人['role']}:卡片上的标和口径算的一样", not 标不符, 标不符[:3])
        ck(f"{人['role']}:范围那一栏和口径的说法一致",
           d.get("范围") == 范.范围话(角色=人["role"], 门店=人.get("shop")),
           d.get("范围"))

    # 运营看到的就是全库这个月的数 —— 这一条顺带把「月份边界算对了」也验了
    以(运)
    全 = api.TOOLS["orders_by_date"](月份=某月, limit=1)
    ck("🔑 运营看到的总数 == 全库这个月的单数(月份边界算对了)",
       全.get("总数") == 该月单数, f"{全.get('总数')} vs {该月单数}")

    # ── ② 总数不是卡片数 ────────────────────────────────────
    print("\n▸ ② 🔑 总数不是卡片数")
    少 = api.TOOLS["orders_by_date"](月份=某月, limit=5)
    ck("总数不是卡片数", 少.get("总数") == 该月单数 and 少.get("卡片数") == 5,
       f"总数 {少.get('总数')} / 卡片数 {少.get('卡片数')}")
    ck("「还有」那一栏对得上", 少.get("还有") == 该月单数 - 5, 少.get("还有"))
    ck("🔑 没给全的时候**明说**别把卡片数当单数",
       "别把" in str(少.get("⚠️ 没给全")), str(少.get("⚠️ 没给全"))[:50])
    # 反向:给全了就**不该有**那条警告
    小月 = api._rows("select substr(created,1,7) m, count(*) n from ordr "
                   "where created is not null group by m "
                   "having n between 1 and 40 order by n limit 1")
    if 小月:
        d2 = api.TOOLS["orders_by_date"](月份=小月[0]["m"], limit=200)
        ck("给全了就**不该有**那条警告(不乱报)", "⚠️ 没给全" not in d2,
           f"{小月[0]['m']} 共 {小月[0]['n']} 单")
    else:
        print(f"     {Y}⚠{D} 找不到单量 ≤40 的月份 —— "
              f"「给全了不报警」这一支**没验到**")

    # ── ③ 顾问那两个数分开报,而且对得上 ────────────────────
    print("\n▸ ③ 顾问那一档:两个数分开报,三个数对得上")
    以(甲)
    g = api.TOOLS["orders_by_date"](月份=某月, limit=1)
    分 = g.get("两个数分开看") or {}
    ck("有「两个数分开看」", set(分) == {"我名下客户的", "我经手下的", "两者重叠"},
       sorted(分))
    ck("🔑 名下客户 + 经手的 − 重叠 == 总数",
       分.get("我名下客户的", 0) + 分.get("我经手下的", 0)
       - 分.get("两者重叠", 0) == g.get("总数"),
       f"{分} vs 总数 {g.get('总数')}")
    ck("明说为什么要分开(混成一个数业绩就说不清)",
       "说不清" in str(g.get("⚠️ 为什么分开")), str(g.get("⚠️ 为什么分开"))[:40])
    以(长)
    ck("店长那一档**没有**这一栏(标和分项只对顾问有意义)",
       "两个数分开看" not in api.TOOLS["orders_by_date"](月份=某月, limit=1))

    # ── ④ 歧义不猜 ──────────────────────────────────────────
    print("\n▸ ④ 🔑 歧义说法不猜,而且两种读法的单数都给出来")
    以(甲)
    for 说法 in ("一月", "1月", "三月份", "12"):
        d3 = api.TOOLS["orders_by_date"](月份=说法)
        ck(f"「{说法}」→ 走「判不了」", bool(d3.get("判不了")),
           str(d3.get("判不了") or d3.get("error"))[:46])
        候 = d3.get("候选") or []
        ck(f"「{说法}」→ **两种读法的单数都给出来**(不空手打回)",
           len(候) == 2 and all(c.get("有多少单") is not None for c in 候),
           [c.get("有多少单") for c in 候])
        ck(f"「{说法}」→ 候选里带着可以直接用的参数",
           all(c.get("参数") for c in 候), [c.get("参数") for c in 候])
    # 认不出的说法要报格式错,**不要也走判不了**(那会让人以为有两种读法)
    d4 = api.TOOLS["orders_by_date"](月份="上个季度吧")
    ck("认不出的说法 → 报格式错,**不是「判不了」**",
       bool(d4.get("error")) and not d4.get("判不了"), str(d4.get("error"))[:40])
    # 相对天数那条歧义也还在
    ck("相对天数不给方向 → 仍然走「判不了」",
       bool(api.TOOLS["orders_by_date"](days=7).get("判不了")))

    # ── ⑤ 互斥 + 相对模式没被改坏 ───────────────────────────
    print("\n▸ ⑤ 互斥,以及相对模式没被改坏")
    ck("绝对区间和相对天数同时给 → 报错",
       "说不清要哪个" in str(api.TOOLS["orders_by_date"](
           月份=某月, direction="往前").get("error")))
    ck("只给一头的区间 → 报错",
       bool(api.TOOLS["orders_by_date"](起="2026-01-01").get("error")))
    ck("止比起早 → 报错,**不替你调换顺序**",
       "不替你调换" in str(api.TOOLS["orders_by_date"](
           起="2026-02-01", 止="2026-01-01").get("error")))
    相 = api.TOOLS["orders_by_date"](direction="往前", days=7)
    ck("相对模式还在(有「方向」那一栏)", 相.get("方向") == "往前", 相.get("方向"))
    ck("相对模式也带总数和范围", 相.get("总数") is not None and 相.get("范围"),
       (相.get("总数"), 相.get("范围")))
    ck("四个日期列都认", all(
        "按哪一列" in api.TOOLS["orders_by_date"](月份=某月, field=f, limit=1)
        for f in ("下单", "完工", "发货", "交付")))
    ck("认不出的日期列 → 报错并列出可选",
       bool(api.TOOLS["orders_by_date"](月份=某月, field="瞎写").get("error")))

    print("\n" + "=" * 92)
    if 坏:
        print(f"{R}❌ 卡片那一头 {len(坏)} 条不过(过 {过[0]}){D}")
        for b in 坏:
            print("    ❌", b)
        return 1
    print(f"{G}✅ 卡片那一头 {过[0]} 条全过{D}")
    print("    ⚠️ 这份只验**卡片那一头**(按身份取一批)。"
          "弹窗那一头在 `backend/chat_order_check.py`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
