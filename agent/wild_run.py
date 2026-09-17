#!/usr/bin/env python3
"""野外巡检 —— **没有真值的时候,怎么跑真实语料。**

## 和前面七套评测的根本区别

前七套都有真值:题目是我出的,答案是我标的,分数是「对了几道」。
**真实语料没有真值** —— 客户随口说的一句话,没有标准答案,
甚至常常没有唯一正确的回答。

那还能测什么?三样,而且这三样都不需要真值:

    ① 违规    体检(guards)能抓的错,不需要知道正确答案也能判 ——
              「报了数字却没调工具」「判责没写须人工确认」都是这类
    ② 行为    调不调工具、调几个、拒不拒答、反不反问 ——
              **分布本身就是信号**:一批真实提问里零次反问,几乎一定有问题
    ③ 一致    同一句话跑两遍,结论方向一样吗 ——
              不一致说明它在猜,而**猜出来的一致答案才是最危险的**

## 为什么真实语料非跑不可

前七套评测里每一道题**都是我想到的题**。
而这一版报告里已经栽过两次:成长评测出了道模型能靠反问通过的题,
识图评测设了条和自己论点矛盾的轴 —— 两次都是**我的题错了**。

**合成数据能验证逻辑,验证不了分布。** 真实语料里全是你没想到的。

## ⚠️ 这个文件现在跑的**不是**真实语料

手边没有真实客户记录。默认语料取自 `01-形制.md` 的「客户原话对照」表 ——
那 5 句是当**领域知识**写的,不是当评测题写的,所以比我出的题近一点,
**但它仍然是我写的**。

真数据到手之前,这里的数字只能当**冒烟测试**看,不能当结论。
用法:`python3 agent/wild_run.py 语料.txt`(一行一句)。
"""
import os, re, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "backend"),
                os.path.join(HERE, "..", "agentsite")]
import api
import textmatch as tm

# 拒答 / 反问 —— 在真实语料里,这两件事的**比例**比对错更能说明问题
REFUSE = ("查不到", "没有查到", "无法确定", "看不出", "不能确定", "查不了", "没有记录")
# ⚠️ 词表第一版漏了最常见的一种反问句式:**祈使式索要**。
# 实测里那条答得最好的(「不能凭『远程量』直接甩责任……给我订单号,我马上跑一遍」)
# 被判成了「没反问」——它句句都在要信息,只是一个问号都没打。
# **第六次栽在词表不全上。**
ASK = ("请问", "能否告诉", "需要确认", "想先确认", "补充", "是哪", "要不要",
       "给我", "告诉我", "提供一下", "先确认", "麻烦发", "把…发", "需要你",
       "?", "?")
NUM = re.compile(r"(?:¥|￥)\s*[\d,]|\d[\d,]*\s*(?:元|天|米)")


# ⚠️ **产品真正收到的输入不是客户原话,是顾问转述。**
# 第一次跑时我把「仙气飘飘的」直接当输入喂进去,结果 5 句零工具调用 ——
# 不是模型凭训练知识作答,是它**把这句当成了没说完的消息**,反问要上下文。
# 它没错:这个助手的服务对象是**顾问**,不是客户本人。
#
# **野外语料的第一课往往是「你喂进去的东西不是产品真正会收到的输入」。**
# 跳过转述这一层,测的就不是这条链路。
FRAME = "客户说「{q}」,我该给她推什么?"


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把结论方向的指纹改成常数(推唐制和推宋制被判成同一套方案)',
     '推唐制 vs 推宋制,判为不一致'),
]

def corpus(path=None):
    if path:
        return [l.strip() for l in open(path, encoding="utf-8") if l.strip()
                and not l.startswith("#")]
    t = api.kb_tables(topic="客户原话对照")["tables"][0]
    return [FRAME.format(q=r[0].strip("「」")) for r in t["rows"]]


def observe(text, traj, guard):
    """不判对错,只记行为。**没有真值时,行为分布就是信号。**"""
    names = [x.split("__")[-1] for x in (traj or [])]
    refuse = bool(tm.says(text, REFUSE))
    ask = bool(tm.mentions(text, ASK))
    return dict(工具=names, 工具数=len(names),
                # **零工具还硬答** —— 一个工具都没调,却既不拒答也不反问,
                # 直接给了实质结论。这是「只说知识库里查到的」那条**约定**
                # 唯一能被量出来的形式,而且**不需要真值**:
                # 不看答案对错,只看「有没有依据就下结论」。
                # 边界审计把这条归在「约定」类(没有任何东西强制),
                # 野外巡检给了它第一个实测值。
                零工具硬答=(len(names) == 0 and not refuse and not ask
                          and len(text or "") > 120),
                拒答=refuse, 反问=ask,
                给了数字=bool(NUM.search(text or "")),
                字数=len(text or ""),
                违规=[v["check"] for v in (guard or [])])


ERA = ("唐制", "宋制", "明制")


def direction(text):
    """结论方向的指纹 —— **取朝代,不取形制细项。**

    粒度要选在**决策的分叉点**上,这一条试错了两轮:

      取「提到过的全部形制」 → 两遍只差一次顺口提到的「马面裙」就判成不同(2/5)
      取「出现最多的形制」   → 齐胸 vs 披帛,而它们是同一套方案的两个部件(1/5)
      取「主推朝代」         → 4/5,而剩下那一条是**真的不一致**

    形制细项是同一套方案的组成部分(唐制齐胸襦裙 + 大袖衫 + 披帛),
    差异只是措辞;**推唐制还是推宋制,才是两个不同的答案。**

    粒度选粗了什么都一致,选细了什么都不一致 —— 两头都测不出东西。
    """
    t = text or ""
    h = [(t.count(e), e) for e in ERA if e in t]
    return (max(h)[1],) if h else ()


def _selftest():
    """指纹和行为观测的对照用例 —— 不调模型,进 check.sh。

    这条指纹试错了三轮才对(全部形制 → 最多形制 → 朝代),
    所以把三轮的教训各钉一条:**粒度选错,两头都测不出东西。**
    """
    bad = []
    def ck(name, cond, extra=""):
        print(f"  {'✅' if cond else '❌'} {name}{('  ' + extra) if extra else ''}")
        if not cond: bad.append(name)

    print("野外巡检 · 指纹与行为观测自测\n" + "=" * 76)
    a = "推荐唐制齐胸襦裙配大袖衫和披帛,唐制这一套最仙。"
    b = "唐制齐胸襦裙 + 披帛,也可以加马面裙做搭配。唐制整体更飘逸。"
    ck("同一套唐制方案,措辞不同也算一致", direction(a) == direction(b),
       f"{direction(a)} vs {direction(b)}")
    c = "宋制褙子配百迭裙,日常好穿。宋制更低调。"
    ck("推唐制 vs 推宋制,判为不一致", direction(a) != direction(c),
       f"{direction(a)} vs {direction(c)}")
    ck("顺口多提一次形制不影响指纹",
       direction("宋制褙子配百迭裙,宋制日常。也有人选马面裙。") == direction(c))
    ck("没提朝代 → 空指纹(和任何朝代都不一致)", direction("请客户补拍一张细节图。") == ())

    o = observe("查不到这个客户的记录。请问订单号是多少?", ["mcp__kb__kb_lookup"], [])
    ck("拒答识别得出", o["拒答"])
    ck("反问识别得出", o["反问"])
    ck("工具记下来了", o["工具"] == ["kb_lookup"])
    ck("没数字就是没数字", not o["给了数字"])
    ck("带钱的识别得出", observe("物料约 3800 元。", [], [])["给了数字"])
    ck("违规原样带出", observe("x", [], [{"check": "g1_no_source", "msg": "m"}])["违规"]
       == ["g1_no_source"])
    long_answer = "推荐宋制褙子配百迭裙。" * 12
    ck("零工具 + 不拒答不反问 + 长答案 → 无据下结论",
       observe(long_answer, [], [])["零工具硬答"])
    ck("零工具但反问了 → 不算无据下结论",
       not observe("先给我订单号,我查完再答。" + long_answer, [], [])["零工具硬答"])
    ck("调了工具就不算", not observe(long_answer, ["mcp__kb__kb_tables"], [])["零工具硬答"])
    ck("祈使式索要也算反问(实测里漏过)",
       observe("给我订单号,我马上跑一遍。", [], [])["反问"])
    print("\n" + "=" * 76)
    if bad:
        print(f"❌ {len(bad)} 条没过:" + " / ".join(bad)); return 1
    print("✅ 指纹粒度与行为观测全部符合预期")
    print("  粒度选粗了什么都一致,选细了什么都不一致 —— 两头都测不出东西。")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv: sys.exit(_selftest())
    import asyncio, json, time
    import sdk
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    reps = 2 if "--once" not in sys.argv else 1
    src = args[0] if args else None
    qs = corpus(src)
    print(f"野外巡检 · {len(qs)} 句 × {reps} 遍 · "
          f"{'语料 ' + src if src else '⚠️ 用的是 01-形制.md 里那 5 句(我写的,不是真实语料)'}")
    print("**没有真值。看的是违规 / 行为分布 / 两遍一致性,不是分数。**")
    print("=" * 104)
    rows, cost = [], 0.0
    for q in qs:
        runs = []
        for k in range(reps):
            t0 = time.time()
            r = asyncio.run(sdk.run("kb", q))
            cost += r.get("cost_usd") or 0
            o = observe(r["text"], [x["tool"] for x in r["trajectory"]],
                        r.get("guard_violations"))
            o.update(dir=direction(r["text"]), 秒=round(time.time() - t0, 1), text=r["text"])
            runs.append(o)
        same = len({x["dir"] for x in runs}) == 1
        a = runs[0]
        rows.append(dict(q=q, runs=runs, 一致=same))
        flag = "".join(["🛑" if a["违规"] else "", "" if same else "🔀"])
        print(f"  {flag or '  '} 「{q[:16]:18s}」 {a['工具数']}调 {a['秒']:5.1f}s "
              f"{'拒答 ' if a['拒答'] else ''}{'反问 ' if a['反问'] else ''}"
              f"{'带数字 ' if a['给了数字'] else ''}{a['字数']}字"
              f"{'  违规:' + ','.join(a['违规']) if a['违规'] else ''}"
              f"{'' if same else '  两遍结论方向不同:' + str([x['dir'] for x in runs])}")
    print("=" * 104)
    n = len(rows)
    viol = [c for r in rows for x in r["runs"] for c in x["违规"]]
    tools = collections.Counter(t for r in rows for x in r["runs"] for t in x["工具"])
    print(f"  ① 违规      {len(viol)} 次" +
          (f" —— {collections.Counter(viol).most_common()}" if viol else " ✅"))
    print(f"  ② 行为      反问率 {sum(r['runs'][0]['反问'] for r in rows)}/{n} · "
          f"拒答率 {sum(r['runs'][0]['拒答'] for r in rows)}/{n} · "
          f"平均 {sum(r['runs'][0]['工具数'] for r in rows)/n:.1f} 次工具调用")
    print(f"     工具分布 {dict(tools)}")
    hard = [r for r in rows if r["runs"][0]["零工具硬答"]]
    zero = [r for r in rows if r["runs"][0]["工具数"] == 0]
    print(f"  ④ 无据下结论 {len(hard)}/{n}"
          + (f" —— 🛑 {[r['q'][:18] for r in hard]}" if hard
             else f" ✅(零工具调用 {len(zero)} 条,全部是反问或拒答)"))
    print(f"  ③ 两遍一致  {sum(r['一致'] for r in rows)}/{n}"
          f"{' —— 不一致的说明它在猜' if sum(r['一致'] for r in rows) < n else ' ✅'}")
    print(f"\n  总花费 ${cost:.4f}")
    print("  **这三样都不需要真值。** 真实语料到手后,重点看的也是这三样 ——")
    print("  分数需要标注,而**违规、分布、一致性不需要**,所以它们才是野外能用的指标。")
    out = os.path.join(HERE, "wild-run-results.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  明细写到 {out}")
    sys.exit(1 if viol else 0)
