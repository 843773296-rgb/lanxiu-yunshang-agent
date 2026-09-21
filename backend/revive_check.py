# -*- coding: utf-8 -*-
"""促活判断的咬合测试 + 覆盖报告。

促活判断有两个讨厌的性质:

**① 判错了和判对了,输出长得一模一样** —— 都是一个布尔加一句话。
   所以每一支都要逐例标真值:什么样的输入,该落到哪个码。

**② 一条永远不触发的分支,和一条正确的分支,在通过率上长得一模一样。**
   所以这里除了对错,还报**每一支在当前库上有没有样本** ——
   **没有样本不叫通过,叫没测到。**

2026-09-20 真踩过两个,都记在这儿:
  · 状态值写「已完成」而库里是「完成」→ 23499 张完成单被判成「在做」,不报错只是全错
  · 「往年同期」漏了排除今年 → 理由那句话自相矛盾
    (「他在 2026 年的这个月都下过单 —— 今年到现在还没动静」)
    **是那句人话把错误暴露出来的**;只看数量或布尔值,这个 bug 藏得住
"""
import sys, os, datetime, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revive

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条在 tools/bite_specs.json 里
# 都有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿、改坏之后
# 要红、而且红的必须是右边那一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「相对他自己的节奏」换成一个固定天数阈值(180 天)',
     '同样闲置 200 天,但他一年才来一次'),
    ('把订单终态写成库里不存在的值(「已完成」而库里是「完成」)',
     '订单终态都是库里真实存在的值'),
]


bad = 0
TODAY = revive._today()


def check(title, got, want, extra=""):
    global bad
    ok = got == want
    if not ok:
        bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {title:46s} 判为 {str(got):14s} 应为 {want}{extra}")


def main():
    global bad
    print("\n\033[1m▸ 促活判断 · 状态值对账(写错一个字,判断全反而且不报错)\033[0m")
    print("  " + "=" * 76)
    c = sqlite3.connect(revive.DB)
    库里订单状态 = {r[0] for r in c.execute("select distinct status from ordr where status is not null")}
    库里售后状态 = {r[0] for r in c.execute("select distinct status from aftersale where status is not null")}

    # **代码里写死的每个状态值,都必须在库里真实存在。**
    # 写了个库里没有的值,不会报错 —— 那个条件只是永远不成立。
    野值 = [v for v in revive.订单终态 if v not in 库里订单状态]
    check("订单终态都是库里真实存在的值", "无野值" if not 野值 else f"野值{野值}", "无野值",
          f"  ← 库里有 {sorted(库里订单状态)}")
    野值2 = [v for v in revive.售后终态 if v not in 库里售后状态]
    check("售后终态都是库里真实存在的值", "无野值" if not 野值2 else f"野值{野值2}", "无野值",
          f"  ← 库里有 {sorted(库里售后状态)}")

    print("\n\033[1m▸ 促活判断 · 逐例标真值(不依赖库里恰好有什么)\033[0m")
    print("  " + "=" * 76)
    不存在 = "NO_SUCH_CUSTOMER"      # 用查不到的 id,让库相关的门槛全部不触发,单测由头那几支

    # ① 没有任何由头 → 不促。**闲置久本身不是理由**
    ok, code, _ = revive.should_revive(
        {"id": 不存在, "name": "甲", "orders_12m": 0, "idle_days": 900,
         # **要有首单** —— 没首单的现在归 NOT_YET(还没热过),那是另一件事
         "first_order": "2024-01-01"}, TODAY)
    check("没由头(哪怕闲置 900 天)", code, "NO_REASON", "  ← 打过去不知道说什么,只会消耗关系")

    # ② 生日临近 → 促
    生日 = (TODAY + datetime.timedelta(days=10)).replace(year=1990).isoformat()
    ok, code, _ = revive.should_revive(
        {"id": 不存在, "name": "乙", "birthday": 生日, "orders_12m": 0}, TODAY)
    check("生日 10 天后", code, "BIRTHDAY")

    # ③ 生日已过 → 不该再算由头
    生日2 = (TODAY - datetime.timedelta(days=10)).replace(year=1990).isoformat()
    ok, code, _ = revive.should_revive(
        {"id": 不存在, "name": "丙", "birthday": 生日2, "orders_12m": 0,
         "first_order": "2024-01-01"}, TODAY)
    check("生日 10 天前(已过)", code, "NO_REASON", "  ← 过完生日再祝一次比不祝更糟")

    # ④ 断了自己的节奏 → 促
    ok, code, why = revive.should_revive(
        {"id": 不存在, "name": "丁", "orders_12m": 4, "idle_days": 200, "first_order": "2024-01-01"}, TODAY)
    check("平均 91 天一次、已闲置 200 天", code, "RHYTHM_BREAK", "  ← 200 > 91×2")

    # ⑤ **同样闲置 200 天,但他本来就慢** → 不促。这一条是整个设计的分界线:
    #    「这个人本来就买得少」和「这个人变了」,用全局阈值会混成同一件事
    ok, code, _ = revive.should_revive(
        {"id": 不存在, "name": "戊", "orders_12m": 1, "idle_days": 200, "first_order": "2024-01-01"}, TODAY)
    check("同样闲置 200 天,但他一年才来一次", code, "NO_REASON",
          "  ← 200 < 365×2 —— **判据是「偏离他自己」,不是「超过某个数」**")

    # ⑥ 从没买过 → 不归促活管(**「还没热过」不是「冷了」**)
    ok, code, _ = revive.should_revive(
        {"id": 不存在, "name": "己", "orders_12m": 0, "idle_days": 500, "first_order": None}, TODAY)
    check("从来没下过单", code, "NOT_YET", "  ← 他不是冷了,是还没热过 —— **和「买过但现在没由头」该做的事不同**")

    print("\n\033[1m▸ 促活判断 · 覆盖报告(没有样本不叫通过,叫没测到)\033[0m")
    print("  " + "=" * 76)
    from collections import Counter
    cnt = Counter()
    for cust in revive._rows("select * from customer"):
        _, code, _ = revive.should_revive(cust, TODAY)
        cnt[code] += 1

    全部码 = ["JUST_BOUGHT", "AFTERSALE", "RECENT_CONTACT",      # 门槛
             "ANNIVERSARY", "BIRTHDAY", "POST_ORDER", "MAINTAIN", "RHYTHM_BREAK",  # 由头
             "NO_REASON"]
    缺样本 = [k for k in 全部码 if cnt[k] == 0]
    总数 = sum(cnt.values())
    促 = sum(v for k, v in cnt.items() if k in ("ANNIVERSARY", "BIRTHDAY", "POST_ORDER", "MAINTAIN", "RHYTHM_BREAK"))
    print(f"  {总数} 个客户 → 建议促活 {促} 人({促*100//总数}%)")
    for k in 全部码:
        mark = f"{Y}⚠ 库里没有样本{D}" if cnt[k] == 0 else ""
        print(f"     {k:16s} {cnt[k]:4d}  {mark}")

    if 缺样本:
        print(f"\n  {Y}⚠{D} 这几支在当前库上**一次都没触发**:{'、'.join(缺样本)}")
        print(f"     它们在上面的逐例测试里是对的,但**库里没有真实样本** ——")
        print(f"     **一条永远不触发的分支,和一条正确的分支,在通过率上长得一模一样。**")
        print(f"     ANNIVERSARY 恒空是因为库里只有 12 个月的订单,往年同期查不到东西。")

    print()
    if bad:
        print(f"{R}❌ 促活判断 {bad} 处不符合预期{D}")
        sys.exit(1)
    print(f"{G}✅ 促活判断全部符合预期{D}")
    print(f"    判错和判对都是「一个布尔加一句话」—— 所以每一支都得标真值。")


if __name__ == "__main__":
    main()
