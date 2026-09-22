#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**指代推进**评测 —— 顾问说「就按那个下单」时,agent 取到的是哪一条方案。

## 为什么这套要单独做

这是「方案 = 一件事」这个功能**唯一真正要证明的事**。

功能本身很小(一个读工具 + 一条规矩),但它要解决的问题不小:
顾问刚问完报价,接着说「那就按这个下单吧」——**agent 不知道「这个」指的是哪一份**。
原来它只能从对话文本里猜,而猜错和猜对**在答复里长得一模一样**,
直到按错误的配置下了单。

## 判的是「取到的号对不对」,不是「答得好不好」

这条是刻意的,而且是这套评测最要紧的设计:

    ✅ 可判定   答复里点名的方案号 == 该场景下正确的那一个
    ❌ 不判定   答复读起来顺不顺、语气好不好

**不可由程序判定的指标进不了自动化校验,长期一定失效。**

## 四类场景,每一类防一种具体的错

| 场景 | 正确做法 | 防的是 |
|---|---|---|
| 客户只有一条在推进 | 直接点名那一条 | 明明没歧义却反复追问,变成话痨 |
| **多条同时已锁定** | **必须回问是哪一条,不许挑** | 拿「锁定那条」当唯一标识 |
| 指到已失效的方案 | 指出已失效,不推进 | 把去年没成的单又推一遍 |
| 指到草稿 | 说明还没定稿 | 拿一份没拍板的配置去下单 |

第二类是重点。业务 2026-09-18 明确**一个客户可以多条方案同时处于已锁定**
(婚服、敬酒服、伴娘服各锁各的),所以「锁定那条」**不是一个能消歧的说法** ——
消歧只能靠方案号。我原来假定锁定唯一,顺理成章会想「指代不明就取已锁定那条」,
业务一否掉,这条捷径就没了。**这套评测就是钉死这一点的。**

## 用例不绑具体方案号

`judge()` 是**纯函数**,场景数据由调用方给。对照自测喂人造场景(离线、一分钱不花),
真跑时才从库里按**性质**挑(「找一个有两条已锁定的客户」),不写死 SC2601 ——
这个项目为「夹具写死会漂的东西」栽过:写死的 id 会被一次合理的数据变更打断,
而打断的时候判分器不会说「夹具过期了」,只会说「模型答错了」。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "backend")]
import textmatch as tm

方案号式样 = re.compile(r"\bSC\d{4,}\b")

# 「我得先问清楚是哪一条」的说法。**不枚举中文短语去判有没有问** ——
# 这个项目为枚举栽过七次。这里只用来做**正向线索**,真正的判据是下面的结构:
# 答复里点了几个方案号、点的是不是正确的那个。
追问线索 = ("哪一", "哪条", "哪一条", "哪个", "确认一下", "是指", "请问",
           "需要您确认", "不确定", "有两条", "有多条", "分别是")


def 提号(text):
    """答复里点名了哪些方案号。去重但保序。"""
    出 = []
    for m in 方案号式样.findall(text or ""):
        if m not in 出:
            出.append(m)
    return 出


def judge(case, text, traj):
    """判一次指代推进。**纯函数**,不碰库、不调模型,离线可测。

    case 需要四个字段:
      kind      "单条" / "歧义" / "已失效" / "草稿"
      正确号     这一场景下应当点名的方案号(歧义场景为 None —— 正确做法是不点)
      候选号     该客户名下全部方案号(用来判「编了一个不存在的号」)
      失效号     已失效 / 草稿那一条的号(对应场景用)
    """
    t = text or ""
    bad = []
    names = " ".join(x.split("__")[-1] for x in (traj or []))
    点到 = 提号(t)

    # ── 轨迹轴:必须真去查过 ─────────────────────────────────────────
    # **不查而答对,也算错。** 这一轮碰巧猜中,下一轮就猜不中,
    # 而两次的答复长得一模一样 —— 「凭印象答」是这个项目专门要抓的一类。
    if "get_scheme" not in names:
        bad.append("轨迹:没查方案(get_scheme)—— 指代只能靠查,不能靠对话里的印象")

    # ── 编号轴:不许说一个库里没有的号 ───────────────────────────────
    编的 = [x for x in 点到 if x not in (case.get("候选号") or [])]
    if 编的:
        bad.append(f"内容:**编了不存在的方案号 {编的}** —— 这个客户名下没有这几条")

    kind = case["kind"]

    if kind == "歧义":
        # 多条同时已锁定。**正确做法是回问,不是挑一个。**
        真号 = [x for x in 点到 if x in (case.get("候选号") or [])]
        # 点名两条以上并列着问,是**对的**(把候选摆出来让人选);
        # 只点一条并往下推进,是错的。判的是「有没有落到单一一条上就往下走」。
        if len(真号) == 1:
            bad.append(f"内容:**多条同时已锁定,却挑了 {真号[0]} 就往下做** —— "
                       f"「锁定那条」不是唯一标识,消歧只能靠方案号")
        elif len(真号) == 0:
            # 对照自测抓到的:「您有多条方案都锁定了,请确认一下要哪个」——
            # 这句读起来很负责,**但一个号都没给**,顾问还得自己回去翻。
            # 判分器原来放它过了:我只判了「有没有挑一条」和「有没有回问」,
            # 漏了「**回问得让人答得上来**」。
            # 把候选摆出来才算把歧义交还给人,只说「有歧义」是把活推回去。
            bad.append("内容:回问了,但**一个候选方案号都没列出来** —— "
                       "顾问还得自己回去翻,歧义没有真的交还给他")
        if not tm.mentions(t, 追问线索):
            bad.append("内容:指代不明时没有回问是哪一条")
    elif kind in ("已失效", "草稿"):
        标 = "已失效" if kind == "已失效" else "草稿"
        if not tm.mentions(t, (标,)):
            bad.append(f"内容:没指出这条方案是**{标}**,直接往下推进了")
        # 已失效/草稿都不该被推进成订单
        if tm.says(t, ("可以下单", "帮您下单", "这就下单", "马上安排生产")):
            bad.append(f"内容:{标}的方案被推进了 —— {标}不是可下单状态")
    else:  # 单条
        对 = case.get("正确号")
        if not 点到:
            bad.append(f"内容:没点名方案号(应为 {对})—— "
                       f"**说「那套」而不说号,等于把歧义留给了下一个人**")
        elif 对 not in 点到:
            bad.append(f"内容:点名的是 {点到},而正确的是 {对}")
        elif len(点到) > 1:
            bad.append(f"内容:只有一条在推进,却同时点了 {点到} —— 反而制造了歧义")

    return (not bad), bad


def 从库里挑场景(conn):
    """真跑时用:按**性质**从库里挑场景,不写死方案号。

    返回 (场景列表, 缺口说明)。缺口要报出来 —— **「库里没有这种样本」和
    「这种场景全过」必须能分开**,静默少测一类是这套评测最容易出的事故。
    """
    行 = conn.execute("SELECT id,customer_id,status FROM scheme").fetchall()
    按客户 = {}
    for sid, cid, st in 行:
        按客户.setdefault(cid, []).append((sid, st))

    场景, 缺 = [], []

    多锁 = [(c, v) for c, v in 按客户.items()
           if len([x for x in v if x[1] == "已锁定"]) >= 2]
    if 多锁:
        c, v = 多锁[0]
        场景.append(dict(kind="歧义", 正确号=None, 候选号=[x[0] for x in v],
                       客户=c, 失效号=None))
    else:
        缺.append("歧义场景:库里没有「同一客户两条以上已锁定」的样本 —— "
                  "而那是这套评测最要紧的一类")

    单锁 = [(c, v) for c, v in 按客户.items()
           if len([x for x in v if x[1] == "已锁定"]) == 1]
    if 单锁:
        c, v = 单锁[0]
        锁 = [x[0] for x in v if x[1] == "已锁定"][0]
        场景.append(dict(kind="单条", 正确号=锁, 候选号=[x[0] for x in v],
                       客户=c, 失效号=None))
    else:
        缺.append("单条场景:库里没有「同一客户恰好一条已锁定」的样本")

    for st, k in (("已失效", "已失效"), ("草稿", "草稿")):
        命中 = [(c, v, x[0]) for c, v in 按客户.items() for x in v if x[1] == st]
        if 命中:
            c, v, sid = 命中[0]
            场景.append(dict(kind=k, 正确号=sid, 候选号=[x[0] for x in v],
                           客户=c, 失效号=sid))
        else:
            缺.append(f"{k}场景:库里没有状态为「{st}」的方案")

    return 场景, 缺


咬合 = [
    ('把「没查方案就答」那一轴关掉(不调 get_scheme 也算过)',
     '没查方案'),
    ('把歧义场景的判据放松成「点一条也算对」',
     '却挑了'),
    ('让「编了不存在的方案号」不再判错',
     '编了不存在的方案号'),
]

# ── 题面:四类场景,每类一句顾问会真说的话 ──────────────────────────
# **题面里不写方案号** —— 写了就等于把答案给它了,而这套评测要测的
# 恰恰是「它自己能不能找对那一条」。
问法 = {
    "单条": "刚才那位客户的方案我们再确认一下,就按那个下单吧。",
    "歧义": "客户说就按锁定的那个下单,你帮我确认一下是哪一份。",
    "已失效": "客户提到去年那套没成的方案,说想按那个再做一次,可以吗?",
    "草稿": "客户问她之前存的那套方案现在能不能直接下单?",
}


def 造题(场景):
    """把场景变成一句话。**带上客户号,不带方案号** ——
    顾问在真实场景里知道自己在跟谁说话,但不会背方案编号。"""
    return (f"客户 {场景['客户']}。{问法[场景['kind']]}")


if __name__ == "__main__":
    # **两件事,两个入口。**
    #
    #   不带参数   只查「库里挑不挑得出四类场景」—— 纯读库,系统 python 就能跑,进门禁
    #   --run     真跑模型 —— 要 venv、要花钱、结果有波动,**不进门禁**
    #
    # ⚠️ 这个拆分是被门禁逼出来的:第一版把真跑写在 `__main__` 顶上,
    # 于是一个**只想数样本**的步骤死在「没有 .venv」上 ——
    # 而那看起来像环境坏了,不像是我把两件事混进了一个入口。
    #
    # 真跑:
    #   ANTHROPIC_MODEL=claude-haiku-4-5 LANXIU_PROVIDER=claude \
    #     ./agentsite/.venv/bin/python agent/scheme_eval.py --run
    import sqlite3
    c = sqlite3.connect(os.path.join(HERE, "..", "backend", "lanxiu.db"))
    场景, 缺 = 从库里挑场景(c)
    c.close()

    if "--run" not in sys.argv:
        print(f"库里挑得出 {len(场景)} 类场景:{[s['kind'] for s in 场景]}")
        for g in 缺:
            print(f"  ⚠️ {g}")
        print("  (真跑模型请加 --run,并用 ./agentsite/.venv/bin/python)")
        sys.exit(1 if 缺 else 0)

    import asyncio
    import time
    sys.path.insert(0, os.path.join(HERE, "..", "agentsite"))
    import sdk

    for g in 缺:
        print(f"⚠️ {g}")

    model = os.environ.get("ANTHROPIC_MODEL")
    if not model:
        # CLAUDE.md 第 4 节:**不指定模型直接拒跑** ——
        # 默认模型取决于用哪种凭证,同一条命令在另一台机器上跑的是另一个模型,
        # 而表格上完全看不出来。
        print("❌ 必须显式指定 ANTHROPIC_MODEL —— 不指定时默认模型取决于凭证种类,"
              "换台机器跑的就是另一个模型,而结果表上看不出来")
        sys.exit(2)

    print(f"指代推进评测 · {len(场景)} 题(四类场景)· 模型 {model}")
    print("=" * 104)
    def 跑一轮():
        rows = []
        for 场 in 场景:
            题 = 造题(场)
            t0 = time.time()
            try:
                r = asyncio.run(sdk.run("kb", 题, max_turns=10))
            except Exception as ex:
                rows.append(dict(kind=场["kind"], 题=题, passed=False,
                                 why=[f"跑挂了:{type(ex).__name__}: {ex}"],
                                 tools="", cost=0, text=""))
                print(f"  ❌ {场['kind']:5s} 跑挂了:{type(ex).__name__}")
                continue
            names = [x["tool"] for x in r["trajectory"]]
            ok, why = judge(场, r["text"], names)
            rows.append(dict(kind=场["kind"], 题=题, 正确号=场.get("正确号"),
                             候选号=场.get("候选号"), passed=ok, why=why,
                             tools=",".join(n.split("__")[-1] for n in names),
                             cost=r.get("cost_usd") or 0, text=r["text"]))
            print(f"  {'✅' if ok else '❌'} {场['kind']:5s} {len(names)}调 "
                  f"{time.time()-t0:5.1f}s ${r.get('cost_usd') or 0:.4f}"
                  f"  {'' if ok else why[0][:52]}")
            for w in (why[1:] if not ok else []):
                print(f"        {w[:92]}")
        return rows

    # 原来这里印一句「⚠️ 一轮不作数,跑第二轮」—— **知道,但没做成结构**,
    # 于是每次跑都只跑一轮,再印一遍那句提醒。提醒会被忽略,而忽略了看不出来。
    # 现在走 rounds.跑并收尾:两轮、判基线来路、部分不写。
    #
    # ⚠️ 这一套的「全集」是**四类场景**,不是 `len(场景)` ——
    # 场景是从库里现挑的,挑不齐时 `场景` 会少一类。拿「挑到几类」当全集,
    # 缺了一类的那次跑照样会**把四类的基线冲成三类**,而文件上看不出来。
    import rounds
    rows, _ = rounds.跑并收尾(跑一轮, 名="指代推进", 键="kind",
                              结果文件=os.path.join(HERE, "scheme-eval-results.jsonl"),
                              全集数=len(场景) + len(缺), 本轮数=len(场景))
    ok_n = sum(1 for r in rows if r["passed"])
    print("=" * 104)
    print(f"最后一轮 通过 {ok_n}/{len(场景)}  |  花费 ${sum(r.get('cost') or 0 for r in rows):.4f}")
    sys.exit(0 if ok_n == len(场景) else 1)
