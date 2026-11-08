#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把所有评测**题集**导成一份人能读的 md —— 用户 2026-09-24 要求:飞书上留一份。

    python3 tools/export_evals.py            # 生成 澜绣云裳agent-评测题集.md

## 为什么从结果文件导,而不是从评测脚本里抄题面

题面是**现挑的**(客户、订单、日期都从库里现取,写死的夹具会被一次合理的数据变更打断),
所以脚本里存的是模板,`{单}` 那种。**跑出来的结果文件里才是真正问过的那句话** ——
导它,拿到的就是「模型当时看到的题」。

⚠️ 因此这份导出**只覆盖跑过的评测**:没跑过的那几套不会出现在里面,
而「没跑过」和「没有题」在目录里长得一样 —— 所以末尾专门列一节「有脚本但没跑过的」。
"""
import json, os, re, sys, glob, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "澜绣云裳agent-评测题集.md")

名字 = {"ops": "运维侧(工坊 / 任务 / 排班 / 商机)", "factory": "工厂回传(生产、分批、回退、延期)",
        "pickup": "交付签收(到店、试穿合身码、按件签收)", "repair": "报修与判责",
        "order": "下单(开单 → 量体 → 确认)", "measure": "量体录入", "growth": "成长推算(孩子)",
        "member": "会员与生命周期", "liability": "售后判责", "role": "角色边界",
        "pattern": "版师核料", "report": "复盘报告", "chat": "工艺问答", "negative": "负向题(早期)",
        "vision": "识图", "scheme": "方案", "tool": "工具用法", "eval": "综合", "gen-compare": "三代对比", "fitting": "白坯试衣", "skill": "技能触发",
        "funnel": "漏斗", "skill_usage": "技能用量", "opportunity": "商机判断",
        "rating": "签收后评价与差评", "workshop": "自有工坊报工", "store-report": "经营报告(Skill 出的报告对不对)",
        "wild-run": "野外巡检(真实语料,**没有真值**)", "negative": "负向题(早期)"}


def 说明(名):
    """这套题的**业务场景和出题思路** —— 取评测脚本开头那段 docstring。

    **不另写一份**:出题的时候那段就是照着业务写的,抄第二份迟早和脚本漂开,
    而漂了之后读的人不知道该信哪份。
    """
    # ⚠️ 两个目录都找:技能触发那套的脚本在 `agentsite/`(不在 `agent/`)——
    # 这正是它此前整套没进这份题集的同一个根因:**这个脚本只往 agent/ 看。**
    for 候, 目 in ((f"{名}_eval.py", "agent"), (f"{名.replace('-', '_')}_eval.py", "agent"),
                  (f"{名}_eval.py", "agentsite"), (f"{名.replace('-', '_')}_eval.py", "agentsite")):
        fp = os.path.join(ROOT, 目, 候)
        if os.path.exists(fp):
            src = open(fp, encoding="utf-8").read()
            m = re.search(r'"""(.+?)"""', src, re.S)
            if m:
                t = m.group(1).strip()
                # 去掉「用法」这类只对开发有用的段
                t = re.split(r"\n##\s*(?:用法|怎么跑|运行)", t)[0].strip()
                return t
    return ""


def 判据里的答案(名):
    """从评测脚本里**现取**每道题的标准答案 —— 判据里写着「要说到什么、不许做什么」,那就是答案。

    为什么现取而不是手抄:手抄一份会和判据漂开,而**漂了之后读的人不知道该信哪份**;
    更糟的是判据改了、答案没改,于是文档上写着的「标准答案」已经不是判分时用的那一条。
    手写的 `期望=` 优先(工厂那套是手写的,话说得更像人话)。
    """
    出 = {}
    for 候, 目 in ((f"{名}_eval.py", "agent"), (f"{名.replace('-', '_')}_eval.py", "agent"),
                  (f"{名}_eval.py", "agentsite"), (f"{名.replace('-', '_')}_eval.py", "agentsite")):
        fp = os.path.join(ROOT, 目, 候)
        if not os.path.exists(fp):
            continue
        src = open(fp, encoding="utf-8").read()
        # 按 dict(id="..." 切块,块内收集 need_tool(...) 和 why="..."
        块 = re.split(r'dict\(\s*id\s*=\s*"([^"]+)"', src)
        for i in range(1, len(块) - 1, 2):
            题号, 体 = 块[i], 块[i + 1]
            体 = 体[:体.find("\n    dict(") if "\n    dict(" in 体 else len(体)]
            工具 = re.findall(r'need_tool\(([^)]*)\)', 体)
            工具 = [x.strip('"\' ') for g in 工具 for x in g.split(",") if x.strip(' "\'')]
            要 = re.findall(r'why\s*=\s*[f]?"([^"]{4,200})"', 体)
            片 = []
            if 工具:
                片.append("要调 " + "、".join(dict.fromkeys(工具)))
            片 += [x.replace("**", "") for x in dict.fromkeys(要)]
            if 片:
                出[题号] = ";".join(片)
        break
    return 出


def 历次(套们):
    """把这一次的结果并进**历次成绩**(agent/eval-history.jsonl),再读回来。

    ⚠️ 结果文件只留最后一轮 —— 想看「这道题历史上对过几次」就必须单独攒一份。
    **从今天开始攒**:以前每一轮的逐题对错没留下来,这一点在导出里如实写明,
    不写的话读的人会以为「历史只有一条」等于「只跑过一次」。
    """
    H = os.path.join(ROOT, "agent", "eval-history.jsonl")
    旧 = []
    if os.path.exists(H):
        for l in open(H, encoding="utf-8"):
            try: 旧.append(json.loads(l))
            except Exception: pass
    # ⚠️ 键里**必须带轮号**:同一天跑三轮,`(套,题,跑于,模型)` 对三条结果是同一个键 ——
    # 于是历次里只会留下一轮,而「这天跑了三轮」和「这天跑了一轮」在历次表上一模一样。
    # 老记录没有这个字段,读的时候当第 1 轮(写的时候也从 1 起算),所以老数据不会被重记一遍。
    见 = {(x["套"], x["题"], x["跑于"], x.get("模型"), int(x.get("轮") or 1)) for x in 旧}
    新 = []
    for s in 套们:
        for k, xs in s["轮们"].items():
            for r in xs:
                轮 = int(str(r.get("轮") or 1) or 1)
                键 = (s["名"], str(k), s["跑于"], s["模型"], 轮)
                if 键 in 见 or not s["跑于"]:
                    continue
                见.add(键)
                新.append(dict(套=s["名"], 题=str(k), 跑于=s["跑于"], 模型=s["模型"],
                               轮=轮, 过=bool(r.get("passed"))))
    if 新:
        with open(H, "a", encoding="utf-8") as fh:
            for x in 新: fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    全 = 旧 + 新
    按题, 按套 = collections.defaultdict(list), collections.defaultdict(list)
    for x in 全:
        按题[(x["套"], x["题"])].append(x)
        按套[(x["套"], x["跑于"], int(x.get("轮") or 1))].append(x)
    return 按题, 按套


def 一套(f):
    名 = os.path.basename(f).replace("-eval-results.jsonl", "").replace("-results.jsonl", "")
    rs = []
    for l in open(f, encoding="utf-8"):
        try: rs.append(json.loads(l))
        except Exception: pass
    rs = [r for r in rs if r.get("q") or r.get("prompt")]
    if not rs:
        return None
    # ⚠️ 2026-11-06:原来这里是 `题[id] = r`,**同一题多轮时只留最后一轮** ——
    # 负向那套改成跑三轮之后,一道「三轮都对」的题和一道「只有最后一轮碰巧对」的题,
    # **在这份导出的 ✅ 上长得一模一样**,而它们该触发的下一步动作相反
    # (前者是能力稳,后者是要去查抖动)。所以按题把**全部轮次**收齐。
    轮们 = collections.defaultdict(list)
    for i, r in enumerate(rs):
        # 没有 id 的那几套(wild-run)用**行号**当键 —— 原来写 len(题),
        # 一题多轮时它会跟着字典长度漂,同一题的第二轮可能顶掉另一题。
        轮们[r.get("id") or r.get("case") or i].append(r)
    题 = {}
    for k, xs in 轮们.items():
        xs.sort(key=lambda r: (int(str(r.get("轮") or 1) or 1), str(r.get("跑于") or "")))
        题[k] = xs[-1]                 # 题面 / 答案照旧取最后一轮(题面是现挑的)
    # **判对的口径跟评测本身一致(判法 C,用户 2026-11-05 拍):全部轮次都对才算这道题对。**
    # 单轮的那几套 all([x]) == x,行为一个字没变。
    # ⚠️ 有的套**压根不按对错判**(野外巡检:真实语料没有真值,它量的是违规 / 一致 / 拒答)。
    # 它的结果行里没有 `passed`,而 `sum(... if x.get("passed"))` 会算出 0 ——
    # **「这套没有对错这个概念」和「这套全错了」在 0/20 上长得一模一样。** 所以这里给 None。
    有判 = any("passed" in x for xs in 轮们.values() for x in xs)
    过 = sum(1 for xs in 轮们.values() if all(x.get("passed") for x in xs)) if 有判 else None
    抖 = sorted(str(k) for k, xs in 轮们.items() if len({bool(x.get("passed")) for x in xs}) > 1)
    轮数 = max((len(xs) for xs in 轮们.values()), default=0)
    模 = collections.Counter(r.get("模型") or r.get("model") or "?" for r in 题.values()).most_common(1)
    跑于 = max((str(r.get("跑于") or r.get("ts") or "") for r in 题.values()), default="")
    return dict(名=名, 中文=名字.get(名, 名), 题=题, 轮们=轮们, 轮数=轮数, 抖=抖,
                过=过, 有判=有判, 模型=模[0][0] if 模 else "?", 跑于=跑于[:10])


def 技能那套():
    """技能触发那套题 —— 它的结果**不在** `agent/*results.jsonl`,而在
    `agentsite/evals/runs/v*.json`(格式也不同),所以单独读一份。

    ⚠️ **这套题此前整套没进过这份题集**,而上面那张名字映射表里早就有
    `"skill": "技能触发"` 这一条 ——
    > 一个「映射表里登记了这一套」和一个「这一套真的被导出过」,
    > **在那张表上长得一模一样**,而前者让读代码的人确信它在(2026-11-08 我就是这么被骗的:
    > 交接里写了「题集发飞书要等这一版跑完」,而这个脚本压根不读那个文件)。
    根因是只往 `agent/` 一个目录看 —— `说明()` / `判据里的答案()` 同一个毛病,一起改了。

    **挑哪一份:必须盖过来路章(有「跑于」),再取跑于最新的那个。**
    ⚠️ **别按版本号挑** —— `runs/` 里混着十个实验文件(`pushy` / `shaped` / `before16` …),
    其中一个叫 **`v54.json`**:它是 24 条的实验,不是「第 54 版」。
    > 一个「第 54 版基线」和一个「叫 v54 的实验文件」,**在文件名上长得一模一样。**
    「盖过章才算基线」这条和项目既有规矩一致(没来路的基线 `rounds.报()` 会拒收)。

    ⚠️ **`轮们` 故意给空。** 这套 v6 及更早只存了汇总(`hits=4, runs=5` 说「5 遍里 4 遍对」,
    **没说是哪一遍错的**)。要塞进 `历次()` 就得合成 5 条带轮号的伪记录,而
    > 一份**合成出来的**轮次顺序,和一份**真实记录的**逐轮结果,
    > 在 `agent/eval-history.jsonl` 里长得一模一样 —— 而前者是我编的。
    总分和「抖不抖」都不需要那个顺序(`hits==runs` 即全对,`0<hits<runs` 即抖),
    所以不编:这套暂不进历次成绩,下面单独印一张**带模型和题数**的历次表。
    `agentsite/skill_eval.一行()` 从 2026-11-08 起会存 `逐轮`,v7 之后这套就有真逐轮可印。
    """
    import glob as _g
    盖了章 = []
    for p in sorted(_g.glob(os.path.join(ROOT, "agentsite", "evals", "runs", "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        跑于 = str((d.get("来路") or {}).get("跑于") or "")
        if 跑于 and d.get("明细"):
            盖了章.append((跑于, p, d))
    if not 盖了章:
        return None
    盖了章.sort()
    跑于, p, d = 盖了章[-1]
    来 = d.get("来路") or {}
    题, 抖 = {}, []
    for x in d.get("明细") or []:
        k, want, 逐 = str(x.get("id")), x.get("want"), x.get("逐轮")
        if isinstance(逐, list) and 逐:
            # v7 起有真逐轮 —— **逐轮印**,不是只印一个总的:
            # 三个 ✅ 和「❌❌✅」在一个 ✅ 上分不开(这份导出早有一条判据钉着它)
            印 = "".join("✅" if g == want else "❌" for g in 逐)
        elif x.get("runs"):
            # v6 及更早只有汇总 —— 印「4/5 次对」,**并在小节里明说这一版没存逐轮**:
            # 「这一版没存逐轮」和「这一版没抖」不是一回事
            印 = f"{x.get('hits')}/{x.get('runs')} 次对"
        else:
            印 = "—"
        题[k] = dict(
            prompt=x.get("prompt") or "",
            # 这套的「负向」= 期望不触发任何技能(want 为空)
            kind="正向" if want else "负向",
            期望=(f"该触发 `{want}`" if want else "**不该触发任何技能**(照规矩原文答就行)"),
            逐轮印=印,
            why=("" if x.get("ok") is True else
                 f"实际触发 {x.get('got') or '(无)'},应为 {want or '(不触发)'}"),
            passed=(x.get("ok") is True))
        if x.get("wobbly"):
            抖.append(k)
    # 历次:每一行都带**模型和题数**。2026-11-08 查实 v4→v5 换过模型(haiku→sonnet,
    # 记录仪 2651 次 vs 4434 次)、v5→v6 题集 49→50 —— 少了这两栏,
    # **「分数涨了」会被读成「能力涨了」**,而那正是这份导出存在的理由。
    历次 = [(os.path.basename(pp)[:-5], 跑[:16], dd.get("重复遍数"),
             (dd.get("来路") or {}).get("模型") or "?",
             len(dd.get("明细") or []), dd.get("准确率") or "?")
            for 跑, pp, dd in 盖了章]
    return dict(名="skill", 中文=名字.get("skill", "技能触发"), 题=题, 轮们={},
                轮数=int(d.get("重复遍数") or 1), 抖=sorted(抖, key=lambda x: (len(x), x)),
                过=sum(1 for x in d["明细"] if x.get("ok") is True), 有判=True,
                模型=来.get("模型") or "?", 跑于=跑于[:10], 历次表=历次,
                来自=os.path.basename(p),
                有逐轮=any(isinstance(x.get("逐轮"), list) for x in d["明细"]))


def main():
    套 = [x for x in (一套(f) for f in sorted(glob.glob(os.path.join(ROOT, "agent", "*results.jsonl")))) if x]
    # 技能触发那套单独读(结果在 agentsite/evals/runs/,格式也不同)—— 见 技能那套()
    _技 = 技能那套()
    if _技:
        套.append(_技)
    else:
        # **「没东西可导」和「没有这套题」不是一回事** —— 明说,不许静默少一套
        print("  ℹ️ agentsite/evals/runs/ 里没有**盖过来路章**的基线 —— "
              "技能触发那套这次没东西可导(不是没有这套题)")
    脚本 = {os.path.basename(p).replace("_eval.py", "")
            for p in glob.glob(os.path.join(ROOT, "agent", "*_eval.py"))}
    没跑 = sorted(脚本 - {s["名"].replace("-", "_") for s in 套} - {"eval"})
    L = [f"# 澜绣云裳agent · 评测题集", "",
         f"> 由 `tools/export_evals.py` 从**跑出来的结果文件**导出 —— 题面是现挑的,",
         f"> 脚本里存的是模板,这里是**模型当时真正看到的那句话**。",
         f"> 共 {len(套)} 套、{sum(len(s['题']) for s in 套)} 道题。", ""]
    L += ["## 一眼看全", "",
          "| 评测 | 题数 | 正向 / 负向 | 跑了几轮 | 判对(**全轮都对**才算) | 轮间翻面 | 跑于 | 模型 |",
          "|---|---|---|---|---|---|---|---|"]
    for s in 套:
        正 = sum(1 for r in s["题"].values() if (r.get("kind") or "") == "正向")
        L.append(f"| **{s['中文']}** | {len(s['题'])} | {正} / {len(s['题']) - 正} | "
                 f"{s['轮数']}{'' if s['轮数'] > 1 else ' ⚠️'} | "
                 f"{str(s['过']) + '/' + str(len(s['题'])) if s['有判'] else '**不按对错判**'} | "
                 f"{(str(len(s['抖'])) + ' 道') if s['轮数'] > 1 else '—'} | {s['跑于'] or '—'} | {s['模型']} |")
    L += ["", "⚠️ **「跑了几轮 = 1」的那几套,它那一栏是一次抛硬币** —— 存下来的结果文件里只有一轮,",
          "所以「这道题它答得稳」和「这一次它碰巧答对了」在上面的数字里分不开。",
          "负向那套 2026-11-06 起跑三轮:同一个提交三轮之间差了 24 个百分点。", ""]
    L += ["", "**负向题占大头是有意的** —— 正向测「答得对不对」,负向测「顺着错误前提往下滑会怎样」:",
          "用户带着错的前提来问(加钱能不能催织造、能不能先确认下单回头补量体、帮我编个物流单号),",
          "看它顶不顶得住。", ""]
    按题, 按套 = 历次(套)
    缺答案 = []
    for s in 套:
        _判 = 判据里的答案(s["名"])
        有答案 = sum(1 for k, r in s["题"].items() if r.get("期望") or _判.get(str(k)))
        if 有答案 < len(s["题"]):
            缺答案.append((s["中文"], len(s["题"]) - 有答案))
        头 = (f"判对 **{s['过']}/{len(s['题'])}**(准确率 {s['过'] * 100 // max(len(s['题']), 1)}%,"
              f"{'跑了 ' + str(s['轮数']) + ' 轮、**全轮都对才算对**' if s['轮数'] > 1 else '**只跑了一轮**,不算结论'})"
              if s["有判"] else
              f"**这套不按对错判** —— 它的语料没有真值,量的不是「对了几道」(共 {len(s['题'])} 条)")
        L += ["---", "", f"## {s['中文']}", "",
              头 + f" · {s['跑于'] or '没记日期'} · {s['模型']}", ""]
        if s["轮数"] > 1 and s["抖"]:
            L += [f"⚠️ **{len(s['抖'])} 道题在轮次之间翻过面**:{'、'.join(s['抖'])} —— "
                  f"这几道的单轮成绩不能当能力读。", ""]
        # 有的评测**一条结果里有两个互不相干的判定**(负向那套:内容对不对 / 协议走没走)。
        # 合成一个数会把「答对了但没按协议交」和「压根答错了」压成同一个 ❌,而它们该修的地方不同。
        两数 = [(字, sum(1 for xs in s["轮们"].values() for x in xs if x.get(字) is True),
                sum(1 for xs in s["轮们"].values() for x in xs if 字 in x))
               for 字 in ("内容对", "协议走")]
        if all(总 for _, _, 总 in 两数):
            L += ["这套题**一条结果里有两个互不相干的数,不合成一个**(合成会把「答对了但没按协议交草稿」"
                  "和「压根答错了」压成同一个 ❌,而这两件事要修的地方不同):", "",
                  "| | 对了多少 | 占全部轮次 |", "|---|---|---|"]
            for 字, 对, 总 in 两数:
                L.append(f"| **{字}** | {对}/{总} | {对 * 100 // max(总, 1)}% |")
            只差协议 = sum(1 for xs in s["轮们"].values() for x in xs
                       if x.get("内容对") is True and x.get("协议走") is False)
            L += ["", f"其中 **{只差协议} 次是「内容对了、协议没走」** —— 答对了但产品侧拿不到结构化结果。", ""]
        说 = 说明(s["名"])
        if 说:
            L += ["<details><summary><b>这块业务是什么、这套题为什么这么出</b>(点开)</summary>", "",
                  说, "", "</details>", ""]
        # 历次准确率
        # 这套不进 eval-history(没有逐轮,不合成伪记录)—— 它自带一张历次表。
        # **每行都带模型和题数**:2026-11-08 查实 v4→v5 换过模型、v5→v6 题集 49→50,
        # 少了这两栏,「分数涨了」会被读成「能力涨了」。
        if s.get("历次表"):
            L += [f"**这一版来自** `agentsite/evals/runs/{s.get('来自')}`。", ""]
            if not s.get("有逐轮"):
                L += ["⚠️ **这一版只存了汇总**(「4/5 次对」),**没存是哪一遍错的** —— "
                      "所以下面「逐轮」那一栏印的是次数,不是一串 ✅❌。"
                      "**「没存逐轮」和「没抖」不是一回事。**"
                      "(存逐轮从 2026-11-08 起才有,下一版开始就能逐遍看了。)", ""]
            L += ["**历次成绩**(⚠️ **跨行不可直接比** —— 看清模型和题数那两栏:"
                  "换了模型、或者题数变了,两行的分数就不是一回事):", "",
                  "| 版本 | 跑于 | 每条跑几遍 | 模型 | 题数 | 准确率 |",
                  "|---|---|---|---|---|---|"]
            for 版, 跑, 遍, 模, 条, 准 in s["历次表"]:
                L.append(f"| `{版}` | {跑} | {遍 if 遍 else '**没记**'} | {模} | {条} | {准} |")
            L += ["", "⚠️ 「每条跑几遍」那一栏就是**判严度**:几遍全对才算这道题对,"
                  "所以遍数越多分数只会被压低。**没记**的那几版连这个都不知道,"
                  "它们的分数和后面几版不可直接比。", ""]
        日轮 = sorted({(k[1], k[2]) for k in 按套 if k[0] == s["名"]})
        if 日轮:
            L += ["**历次准确率**(从 2026-09-24 开始逐题攒;更早的只留了当轮总分,逐题对错没存。",
                  "**同一天的每一轮各占一行** —— 合成一个日均数会把轮间抖动抹掉):", "",
                  "| 跑于 | 第几轮 | 准确率 |", "|---|---|---|"]
            for d, 轮号 in 日轮:
                xs = 按套[(s["名"], d, 轮号)]
                L.append(f"| {d} | 第 {轮号} 轮 | {sum(1 for x in xs if x['过'])}/{len(xs)} "
                         f"({sum(1 for x in xs if x['过']) * 100 // max(len(xs), 1)}%) |")
            L.append("")
        判据 = _判
        L += [f"| 题号 | 正/负 | 题目(用户会怎么说这句话) | 标准答案:它该答出什么 | "
              f"{'逐轮(左起第 1 轮)' if s['轮数'] > 1 else '最近一次'} | 历次 | 没过的话是为什么 |",
              "|---|---|---|---|---|---|---|"]
        for k, r in s["题"].items():
            q = re.sub(r"\s+", " ", str(r.get("q") or r.get("prompt") or ""))[:170]
            自动 = 判据.get(str(k), "")
            ans = re.sub(r"\s+", " ", str(r.get("期望") or "")) \
                or (自动 + "  *(从判据现取)*" if 自动 else "*(还没写标准答案)*")
            # ⚠️ `轮们` 可能是空的:技能触发那套只存了汇总,没有逐轮记录
            # (故意不合成伪记录 —— 见 技能那套() 里那段)。
            xs = s["轮们"].get(k) or []
            if xs:
                why = "、".join(str(x) for x in (xs[-1].get("why") or []))[:110] \
                    if not all(x.get("passed") for x in xs) else ""
            else:
                why = str(r.get("why") or "")[:110]
            h = 按题.get((s["名"], str(k)), [])
            历 = f"{sum(1 for x in h if x['过'])}/{len(h)}" if h else "—"
            # **逐轮印**,不是只印最后一轮:三个 ✅ 和「❌❌✅」在一个 ✅ 上分不开。
            # **逐轮印**(三个 ✅ 和「❌❌✅」在一个 ✅ 上分不开);
            # 只有汇总的那套用它自己算好的那一栏(「4/5 次对」)
            本次 = ("".join("✅" if x.get("passed") else "❌" for x in xs) if xs
                   else str(r.get("逐轮印") or "—")) if s["有判"] else "—"
            L.append(f"| {k} | {'正' if (r.get('kind') or '') == '正向' else '负'} | {q} | {ans} | "
                     f"{本次} | {历} | {why} |")
        L.append("")
    if 缺答案:
        L += ["---", "", "## 还没写标准答案的", "",
              "**「标准答案」是这道题在问「它该答出什么」** —— 没有它,一道题挂了只能看判分器报的错误码,",
              "看不出「本来该怎么答」。下面这几套还欠着(工厂回传那套已经补齐,格式照它):", "",
              *[f"- {n}:{c} 道" for n, c in 缺答案], ""]
    if 没跑:
        L += ["---", "", "## 有脚本、但还没跑过的", "",
              "**「没跑过」和「没有题」在目录里长得一样** —— 所以单列出来:", "",
              *[f"- `agent/{x}_eval.py`" for x in 没跑], ""]
    L += ["---", "", "## 怎么读这份题集", "",
          "- **一道题挂了,先怀疑判分器**:这个项目实测过一次「16 条人造对照全过、真跑 12 题挂 5 条,",
          "  五条全是判分器的错」。所以每套评测都配一份**判分器对照**(`agent/*_judgetest.py`),",
          "  真跑之后还要把模型的真实说法钉回对照用例。",
          "- **单轮结果不算结论**,而**现在只有负向那套真的跑了多轮**(三轮)——",
          "  其余各套存下来的结果文件里都只有一轮,所以上面那张总表里专门有「跑了几轮」一栏:",
          "  ⚠️ 这里原先写的是「每套都跑两轮」,2026-11-06 核对结果文件发现**不是真的** ——",
          "  一句写在文档里的约定,和一件真的在做的事,**对照着它读的人分不出来**。",
          "  轮间抖动经常比版本差异还大:负向那套三轮之间差了 24 个百分点。",
          "- **题面里的客户、订单、日期都是现挑的**:写死的夹具会被一次合理的数据变更打断,",
          "  而打断时它只会说「参数不存在」,不会说「这道题已经不成立了」。", ""]
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print(f"  ✅ {len(套)} 套、{sum(len(s['题']) for s in 套)} 道题 → {os.path.basename(OUT)}"
          + (f";有脚本没跑过的 {len(没跑)} 套" if 没跑 else ""))


if __name__ == "__main__":
    main()
