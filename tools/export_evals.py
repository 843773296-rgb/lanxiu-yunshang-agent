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
        "funnel": "漏斗", "skill_usage": "技能用量", "opportunity": "商机判断"}


def 说明(名):
    """这套题的**业务场景和出题思路** —— 取评测脚本开头那段 docstring。

    **不另写一份**:出题的时候那段就是照着业务写的,抄第二份迟早和脚本漂开,
    而漂了之后读的人不知道该信哪份。
    """
    for 候 in (f"{名}_eval.py", f"{名.replace('-', '_')}_eval.py"):
        fp = os.path.join(ROOT, "agent", 候)
        if os.path.exists(fp):
            src = open(fp, encoding="utf-8").read()
            m = re.search(r'"""(.+?)"""', src, re.S)
            if m:
                t = m.group(1).strip()
                # 去掉「用法」这类只对开发有用的段
                t = re.split(r"\n##\s*(?:用法|怎么跑|运行)", t)[0].strip()
                return t
    return ""


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
    见 = {(x["套"], x["题"], x["跑于"], x.get("模型")) for x in 旧}
    新 = []
    for s in 套们:
        for k, r in s["题"].items():
            键 = (s["名"], str(k), s["跑于"], s["模型"])
            if 键 in 见 or not s["跑于"]:
                continue
            新.append(dict(套=s["名"], 题=str(k), 跑于=s["跑于"], 模型=s["模型"],
                           过=bool(r.get("passed"))))
    if 新:
        with open(H, "a", encoding="utf-8") as fh:
            for x in 新: fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    全 = 旧 + 新
    按题, 按套 = collections.defaultdict(list), collections.defaultdict(list)
    for x in 全:
        按题[(x["套"], x["题"])].append(x)
        按套[(x["套"], x["跑于"])].append(x)
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
    题 = {}
    for r in rs:                       # 同一题保留最后一次(题面会随数据现挑而变)
        题[r.get("id") or r.get("case") or len(题)] = r
    过 = sum(1 for r in 题.values() if r.get("passed"))
    模 = collections.Counter(r.get("模型") or r.get("model") or "?" for r in 题.values()).most_common(1)
    跑于 = max((str(r.get("跑于") or r.get("ts") or "") for r in 题.values()), default="")
    return dict(名=名, 中文=名字.get(名, 名), 题=题, 过=过, 模型=模[0][0] if 模 else "?", 跑于=跑于[:10])


def main():
    套 = [x for x in (一套(f) for f in sorted(glob.glob(os.path.join(ROOT, "agent", "*results.jsonl")))) if x]
    脚本 = {os.path.basename(p).replace("_eval.py", "")
            for p in glob.glob(os.path.join(ROOT, "agent", "*_eval.py"))}
    没跑 = sorted(脚本 - {s["名"].replace("-", "_") for s in 套} - {"eval"})
    L = [f"# 澜绣云裳agent · 评测题集", "",
         f"> 由 `tools/export_evals.py` 从**跑出来的结果文件**导出 —— 题面是现挑的,",
         f"> 脚本里存的是模板,这里是**模型当时真正看到的那句话**。",
         f"> 共 {len(套)} 套、{sum(len(s['题']) for s in 套)} 道题。", ""]
    L += ["## 一眼看全", "", "| 评测 | 题数 | 正向 / 负向 | 最近一次 | 跑于 | 模型 |", "|---|---|---|---|---|---|"]
    for s in 套:
        正 = sum(1 for r in s["题"].values() if (r.get("kind") or "") == "正向")
        L.append(f"| **{s['中文']}** | {len(s['题'])} | {正} / {len(s['题']) - 正} | "
                 f"{s['过']}/{len(s['题'])} | {s['跑于'] or '—'} | {s['模型']} |")
    L += ["", "**负向题占大头是有意的** —— 正向测「答得对不对」,负向测「顺着错误前提往下滑会怎样」:",
          "用户带着错的前提来问(加钱能不能催织造、能不能先确认下单回头补量体、帮我编个物流单号),",
          "看它顶不顶得住。", ""]
    按题, 按套 = 历次(套)
    缺答案 = []
    for s in 套:
        有答案 = sum(1 for r in s["题"].values() if r.get("期望"))
        if 有答案 < len(s["题"]):
            缺答案.append((s["中文"], len(s["题"]) - 有答案))
        L += ["---", "", f"## {s['中文']}", "",
              f"最近一次 **{s['过']}/{len(s['题'])}**(准确率 {s['过'] * 100 // max(len(s['题']), 1)}%)"
              f" · {s['跑于'] or '没记日期'} · {s['模型']}", ""]
        说 = 说明(s["名"])
        if 说:
            L += ["<details><summary><b>这块业务是什么、这套题为什么这么出</b>(点开)</summary>", "",
                  说, "", "</details>", ""]
        # 历次准确率
        轮 = sorted({k[1] for k in 按套 if k[0] == s["名"]})
        if 轮:
            L += ["**历次准确率**(从 2026-09-24 开始逐题攒;更早的只留了当轮总分,逐题对错没存):", "",
                  "| 跑于 | 准确率 |", "|---|---|"]
            for d in 轮:
                xs = 按套[(s["名"], d)]
                L.append(f"| {d} | {sum(1 for x in xs if x['过'])}/{len(xs)} "
                         f"({sum(1 for x in xs if x['过']) * 100 // max(len(xs), 1)}%) |")
            L.append("")
        L += ["| 题号 | 正/负 | 题目(用户会怎么说这句话) | 标准答案:它该答出什么 | 最近一次 | 历次 | 没过的话是为什么 |",
              "|---|---|---|---|---|---|---|"]
        for k, r in s["题"].items():
            q = re.sub(r"\s+", " ", str(r.get("q") or r.get("prompt") or ""))[:170]
            ans = re.sub(r"\s+", " ", str(r.get("期望") or "")) or "*(还没写标准答案)*"
            why = "、".join(str(x) for x in (r.get("why") or []))[:110] if not r.get("passed") else ""
            h = 按题.get((s["名"], str(k)), [])
            历 = f"{sum(1 for x in h if x['过'])}/{len(h)}" if h else "—"
            L.append(f"| {k} | {'正' if (r.get('kind') or '') == '正向' else '负'} | {q} | {ans} | "
                     f"{'✅' if r.get('passed') else '❌'} | {历} | {why} |")
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
          "- **单轮结果不算结论**:每套都跑两轮,两轮不一致的题会单独列出来 ——",
          "  轮间抖动经常比版本差异还大。",
          "- **题面里的客户、订单、日期都是现挑的**:写死的夹具会被一次合理的数据变更打断,",
          "  而打断时它只会说「参数不存在」,不会说「这道题已经不成立了」。", ""]
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print(f"  ✅ {len(套)} 套、{sum(len(s['题']) for s in 套)} 道题 → {os.path.basename(OUT)}"
          + (f";有脚本没跑过的 {len(没跑)} 套" if 没跑 else ""))


if __name__ == "__main__":
    main()
