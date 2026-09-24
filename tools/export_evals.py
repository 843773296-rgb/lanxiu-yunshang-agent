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
    for s in 套:
        L += ["---", "", f"## {s['中文']}", "",
              f"最近一次 {s['过']}/{len(s['题'])} · {s['跑于'] or '没记日期'} · {s['模型']}", "",
              "| 题号 | 正/负 | 问的是什么 | 最近一次 | 没过的话是为什么 |", "|---|---|---|---|---|"]
        for k, r in s["题"].items():
            q = re.sub(r"\s+", " ", str(r.get("q") or r.get("prompt") or ""))[:160]
            why = "、".join(str(x) for x in (r.get("why") or []))[:120] if not r.get("passed") else ""
            L.append(f"| {k} | {'正' if (r.get('kind') or '') == '正向' else '负'} | {q} | "
                     f"{'✅' if r.get('passed') else '❌'} | {why} |")
        L.append("")
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
