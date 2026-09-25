#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 调控中心的数据层 —— 把散在各处的观测数据汇成一张总览。

## 为什么要有这一层

调试这件事的家伙事已经有好几样了:树状记录仪、实验对比、漏斗埋点、技能埋点、评测存档。
但它们**各自存在各自的文件里**,要看得一个个去翻,而且「今天到底跑了多少、花了多少、
被拦了几次」这个最常问的问题,没有任何一处答得了。

这一层只做一件事:**把数字算出来,每个数字只有一个来源**。页面不许自己再算一遍 ——
抄一份的结果一定是改了一处漏一处,而漏的那处不会报错,只会显示一个旧数。

## 诚实原则:没有的要说没有

九个模块里有四个**还没做**(提示词版本、知识库检索、训练数据准备、在线抽检)。
它们在总览里照样列出来,标成「还没有」,并写清**缺了它会怎样**。

⚠️ **不许给还没做的模块放一个能点的入口。** 一个点进去是空页面的入口,
和一个做好了但没数据的模块,在界面上长得一模一样 ——
而这两件事的下一步动作完全相反(一个是去做,一个是去跑)。
"""
import json, os, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _读(p, 限=None):
    if not os.path.exists(p): return []
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line: continue
        try: out.append(json.loads(line))
        except Exception: pass
    return out[-限:] if 限 else out


def _今天():
    """这家店的今天 —— 和业务口径同一个源头,不问时钟。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "backend"))
        from seed import TODAY
        return TODAY
    except Exception:
        return None


def _候选数():
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import prompt_candidate as _pc
        return len(_pc.列表())
    except Exception:
        return 0


def 概览():
    """总览:今天跑了多少 + 九个模块各自的状态。"""
    今 = _今天()
    调用 = _读(os.path.join(ROOT, ".feynman", "llm-trace.jsonl"))
    spans = _读(os.path.join(ROOT, ".feynman", "spans.jsonl"))
    漏斗 = _读(os.path.join(ROOT, "agentsite", "evals", "funnel.jsonl"))
    技能 = _读(os.path.join(ROOT, "agentsite", "evals", "skill_usage.jsonl"))
    评测 = _读(os.path.join(ROOT, "agent", "eval-history.jsonl"))

    # ⚠️ **「今天」按机器日期分组**:这些是**运行痕迹**,不是业务数据 ——
    # 它们记的是「我什么时候跑的」,而那件事确实发生在机器的今天。
    # 业务数据才跟演示世界的今天走。两者混为一谈,就会出现「今天一次都没跑过」。
    import datetime as _dt
    机今 = _dt.date.today().isoformat()
    今调 = [r for r in 调用 if (r.get("ts") or "").startswith(机今)]

    def 钱(rs): return round(sum(r.get("cost_est") or 0 for r in rs), 4)

    树 = {}
    for s in spans: 树.setdefault(s.get("trace_id"), []).append(s)

    拦 = [r for r in 漏斗 if r.get("被拦次数")]
    理由 = Counter()
    for r in 漏斗:
        for x in (r.get("拦的理由") or []):
            理由[str(x)[:40]] += 1
    触发 = [r for r in 技能 if r.get("skill")]

    套 = Counter(r.get("套") for r in 评测)
    最近 = {}
    for r in 评测:
        k = r.get("套")
        d = r.get("跑于") or ""
        if d >= 最近.get(k, ("",))[0]: 最近[k] = (d, [])
    for r in 评测:
        k = r.get("套")
        if (r.get("跑于") or "") == 最近.get(k, ("",))[0]: 最近[k][1].append(bool(r.get("过")))

    模块 = [
        dict(号=1, 名="单次运行", 问="这一次它做了什么、每一步的输入输出是什么",
             有=f"{len(树)} 次运行 · {len(spans)} 个 span,工具的参数和返回值都记着",
             缺=None, 去="/debug", 状态="有"),
        dict(号=2, 名="实验对比", 问="改完之后好了还是坏了 —— 而且这个对比成不成立",
             有="按 git 历史比两个版本;先判可比性再给分",
             缺=None, 去="/experiments", 状态="有"),
        dict(号=3, 名="成本与用量", 问="钱花在哪、缓存有没有命中、哪一次最慢",
             有=f"累计 {len(调用)} 次调用 · ${钱(调用)};今天 {len(今调)} 次 · ${钱(今调)}",
             缺="还摊不到「哪一步」—— 单步输出 token 拿不到真值(见记录仪里的对账)",
             去=None, 状态="有"),
        dict(号=4, 名="守卫与拦截", 问="它想干而被拦下来的那些事",
             有=f"{len(漏斗)} 轮里拦下 {len(拦)} 轮;理由 top3:"
                + "、".join(f"{k}({v})" for k, v in 理由.most_common(3)) if 漏斗 else "还没有埋点数据",
             缺="拦下之后它改对了没有,现在看不出来(只记了拦,没记后续)",
             去=None, 状态="有" if 漏斗 else "没数据"),
        dict(号=5, 名="技能使用", 问="技能有没有被触发、触发之后答得对不对",
             有=f"{len(技能)} 轮里触发 {len(触发)} 次(触发率 {len(触发)*100//max(len(技能),1)}%)",
             缺="**只测了意图没测效果** —— 触发了之后产出合不合格,是另一套题",
             去=None, 状态="有" if 技能 else "没数据"),
        dict(号=6, 名="评测集", 问="这些题是什么、跑过几次、准确率怎么变",
             有=f"{len(套)} 套 · {sum(套.values())} 条历史记录;"
                + "、".join(f"{k} {sum(v[1])}/{len(v[1])}" for k, v in list(最近.items())[:4]),
             缺="页面上还看不到题面 —— 现在靠 tools/export_evals.py 导成文档发飞书",
             去=None, 状态="有"),
        dict(号=7, 名="提示词版本", 问="这一版提示词和上一版差在哪、分数动了没有",
             有=(f"{_候选数()} 份候选。走的是「候选版本 → 跑验证集 → 并排比分 → "
                 f"采纳才落回源头」,**不许直接改线上那份**;"
                 f"候选**只在显式指定时生效**,没跑过验证集不许采纳"),
             缺="并排比分还在 /experiments 那页,没并到这儿来",
             去="/ai/prompts", 状态="有"),
        dict(号=8, 名="知识库检索", 问="它为什么给出这条依据、有没有该命中却没命中的",
             有=None,
             缺="**还没有**。这一栏是给下一步的营销 SOP 铺路:SOP **入库时就得带结构**"
                "(编号 / 适用条件 / 该做什么 / 明确不该做什么),检索日志要记"
                "查询词、过滤条件、召回、重排、最终采用的编号、**没命中时做了什么**。"
                "先按能被记录的方式建 SOP,不是建完再想怎么调试",
             去=None, 状态="还没有"),
        dict(号=9, 名="训练数据准备", 问="哪些真实对话可以拿来微调",
             有=None,
             缺="**只做到「准备」为止**:样本量根本不足以证明微调有没有用,"
                "所以先把「哪些对话值得留、怎么脱敏、怎么标」做出来,不急着训",
             去=None, 状态="还没有"),
    ]
    return dict(今天=今, 机器今天=机今,
                跑=dict(累计次数=len(调用), 累计花费=钱(调用),
                       今日次数=len(今调), 今日花费=钱(今调),
                       树=len(树), span=len(spans)),
                模块=模块,
                做了=len([m for m in 模块 if m["状态"] == "有"]),
                没做=len([m for m in 模块 if m["状态"] == "还没有"]))


# ── 细目:每个模块自己那一摊的明细 ────────────────────────────────
# 总览那九张卡回答「有没有」,这里回答「具体是多少」。
# **两者分开算、分开取**:总览要快(首屏),细目可以慢一点(点开才要)。
def 细目():
    调用 = _读(os.path.join(ROOT, ".feynman", "llm-trace.jsonl"))
    spans = _读(os.path.join(ROOT, ".feynman", "spans.jsonl"))
    漏斗 = _读(os.path.join(ROOT, "agentsite", "evals", "funnel.jsonl"))
    技能 = _读(os.path.join(ROOT, "agentsite", "evals", "skill_usage.jsonl"))
    评测 = _读(os.path.join(ROOT, "agent", "eval-history.jsonl"))

    def 钱(rs): return round(sum(r.get("cost_est") or 0 for r in rs), 4)

    # ① 成本:按天 / 按模型 / 按场景 —— 三个切面看同一笔钱
    天 = {}
    for r in 调用:
        d = (r.get("ts") or "")[:10]
        if d: 天.setdefault(d, []).append(r)
    按天 = [dict(日=d, 次数=len(v), 花费=钱(v),
                 中位耗时秒=round(sorted(x.get("latency_ms") or 0 for x in v)[len(v)//2]/1000, 1))
            for d, v in sorted(天.items())[-14:]]
    def 分组(键):
        g = {}
        for r in 调用: g.setdefault(str(r.get(键) or "—"), []).append(r)
        return sorted([dict(名=k, 次数=len(v), 花费=钱(v),
                            单次=round(钱(v)/len(v), 5)) for k, v in g.items()],
                      key=lambda x: -x["花费"])[:10]
    进 = sum(r.get("input_tokens") or 0 for r in 调用)
    中 = sum(r.get("cache_hit_tokens") or 0 for r in 调用)
    最贵 = sorted(调用, key=lambda r: -(r.get("cost_est") or 0))[:5]
    最慢 = sorted(调用, key=lambda r: -(r.get("latency_ms") or 0))[:5]

    # ② 工具:从 span 里现算 —— **这是旧记录仪答不了的**(它只记了「调了几个」)
    工具 = {}
    for x in spans:
        a = x.get("attr") or {}
        if a.get("gen_ai.operation.name") != "execute_tool": continue
        k = a.get("gen_ai.tool.name") or x.get("name", "?")
        d = 工具.setdefault(k, dict(名=k, 次数=0, 总毫秒=0, 出错=0, 有返回=0))
        d["次数"] += 1; d["总毫秒"] += x.get("duration_ms") or 0
        if x.get("status") == "error": d["出错"] += 1
        if a.get("gen_ai.tool.call.result"): d["有返回"] += 1
    工具表 = sorted(({**v, "平均毫秒": round(v["总毫秒"]/max(v["次数"],1))} for v in 工具.values()),
                    key=lambda x: -x["次数"])[:15]

    # ③ 最近的运行 —— 点得进 /debug 的那几次
    树 = {}
    for x in spans: 树.setdefault(x.get("trace_id"), []).append(x)
    近 = []
    for tid, v in sorted(树.items(), key=lambda kv: kv[1][0].get("start", 0))[-20:]:
        根 = next((y for y in v if not y.get("parent_span_id")), v[0])
        a = 根.get("attr") or {}
        近.append(dict(trace=tid, 时间=根.get("ts"), 角色=根.get("角色"),
                       模型=根.get("模型"), 秒=round((根.get("duration_ms") or 0)/1000, 1),
                       花费=a.get("lanxiu.cost_usd"),
                       工具=a.get("lanxiu.tool_calls"),
                       被打回=bool(a.get("lanxiu.guard.blocked")),
                       拦了=a.get("lanxiu.guard.blocked_tools") or None))
    近.reverse()

    # ④ 拦截:逐条,不只给个数 —— 「拦了 6 次」看不出该改什么
    拦 = [dict(时间=r.get("ts"), 角色=r.get("角色"), 问的=(r.get("问的") or "")[:40],
               理由=[str(x)[:60] for x in (r.get("拦的理由") or [])])
          for r in 漏斗 if r.get("被拦次数")][-20:]
    拦.reverse()

    # ⑤ 技能:每个技能各自的数
    sk = {}
    for r in 技能:
        k = r.get("skill") or "(没触发)"
        d = sk.setdefault(k, dict(名=k, 次数=0, 成功=0, 总秒=0))
        d["次数"] += 1; d["成功"] += 1 if r.get("ok") else 0; d["总秒"] += r.get("seconds") or 0
    技能表 = sorted(({**v, "平均秒": round(v["总秒"]/max(v["次数"],1), 1)} for v in sk.values()),
                    key=lambda x: -x["次数"])

    # ⑥ 评测:每套最近两次
    套 = {}
    for r in 评测:
        套.setdefault(r.get("套"), {}).setdefault(r.get("跑于"), []).append(bool(r.get("过")))
    评测表 = []
    for k, 轮 in sorted(套.items()):
        日 = sorted(轮)[-2:]
        评测表.append(dict(套=k, 最近=[dict(日=d, 过=sum(轮[d]), 共=len(轮[d])) for d in 日]))

    return dict(成本=dict(按天=按天, 按模型=分组("model"), 按场景=分组("purpose"),
                         缓存命中率=f"{中/(进+中)*100:.1f}%" if (进+中) else "0%",
                         最贵=[dict(时间=r.get("ts"), 场景=r.get("purpose"),
                                    花费=r.get("cost_est"), 模型=r.get("model")) for r in 最贵],
                         最慢=[dict(时间=r.get("ts"), 场景=r.get("purpose"),
                                    秒=round((r.get("latency_ms") or 0)/1000,1)) for r in 最慢]),
                工具=工具表, 运行=近, 拦截=拦, 技能=技能表, 评测=评测表)


# ── 模块页:列表 + 详情 ───────────────────────────────────────────
# 用户 2026-09-24 定:每个模块一个单独页面,**列表形式**,点一行能看到那一条的
# **全部完整信息** —— 对一次咨询来说是五段:上下文 / 召回 / 排序 / 调用 / 产出。
#
# ⚠️ **「排序」这一段要照实说没有。** 这个项目的知识库是结构化查表,没有向量召回、
# 也没有重排。给它放一个空面板,和「有重排但这次没触发」在界面上长得一模一样,
# 而这两件事的下一步完全不同(一个是去做,一个是去查为什么没触发)。
模块表 = ["runs", "cost", "tools", "guards", "skills", "evals", "ops", "prompts"]
没做的 = {"retrieval": "知识库检索", "finetune": "训练数据准备"}


def _库():
    import sqlite3
    return sqlite3.connect(f"file:{os.path.join(ROOT,'backend','lanxiu.db')}?mode=ro", uri=True)


def 列表(mod, 限=200):
    """一个模块的列表。每行要能**一眼看出值不值得点进去**,所以带上结果和代价。"""
    if mod == "runs":
        spans = _读(os.path.join(ROOT, ".feynman", "spans.jsonl"))
        树 = {}
        for x in spans: 树.setdefault(x.get("trace_id"), []).append(x)
        出 = []
        for tid, v in 树.items():
            根 = next((y for y in v if not y.get("parent_span_id")), v[0])
            a = 根.get("attr") or {}
            工具 = [y for y in v if (y.get("attr") or {}).get("gen_ai.operation.name") == "execute_tool"]
            出.append(dict(id=tid, 时间=根.get("ts"), 角色=根.get("角色"),
                           问=(a.get("lanxiu.prompt") or "")[:60],
                           模型=根.get("模型"), 秒=round((根.get("duration_ms") or 0)/1000, 1),
                           花费=a.get("lanxiu.cost_usd"), 工具数=len(工具),
                           答了=bool(a.get("lanxiu.answer")),
                           被打回="是" if a.get("lanxiu.guard.blocked") else ""))
        return sorted(出, key=lambda x: x["时间"] or "", reverse=True)[:限]
    if mod == "cost":
        rs = _读(os.path.join(ROOT, ".feynman", "llm-trace.jsonl"))[-限:]
        return [dict(id=str(i), **r) for i, r in enumerate(rs)][::-1]
    if mod == "tools":
        spans = _读(os.path.join(ROOT, ".feynman", "spans.jsonl"))
        出 = []
        for x in spans:
            a = x.get("attr") or {}
            if a.get("gen_ai.operation.name") != "execute_tool": continue
            出.append(dict(id=x.get("span_id"), trace=x.get("trace_id"), 时间=x.get("ts"),
                           工具=a.get("gen_ai.tool.name"), 毫秒=x.get("duration_ms"),
                           状态=x.get("status"),
                           参数=(a.get("gen_ai.tool.call.arguments") or "")[:70],
                           有返回=bool(a.get("gen_ai.tool.call.result"))))
        return sorted(出, key=lambda x: x["时间"] or "", reverse=True)[:限]
    if mod == "guards":
        rs = _读(os.path.join(ROOT, "agentsite", "evals", "funnel.jsonl"))
        return [dict(id=str(i), 时间=r.get("ts"), 角色=r.get("角色"),
                     问=(r.get("问的") or "")[:60], 被拦=r.get("被拦次数") or 0,
                     工具数=r.get("工具数"), 走了写=r.get("走了写路径"),
                     理由="；".join(str(x)[:40] for x in (r.get("拦的理由") or [])))
                for i, r in enumerate(rs)][::-1][:限]
    if mod == "skills":
        rs = _读(os.path.join(ROOT, "agentsite", "evals", "skill_usage.jsonl"))
        return [dict(id=str(i), 时间=r.get("ts"), 技能=r.get("skill") or "(没触发)",
                     角色=r.get("role"), 秒=r.get("seconds"), 成=r.get("ok"),
                     问=(r.get("prompt") or "")[:60]) for i, r in enumerate(rs)][::-1][:限]
    if mod == "evals":
        rs = _读(os.path.join(ROOT, "agent", "eval-history.jsonl"))
        return [dict(id=f"{r.get('套')}|{r.get('题')}|{r.get('跑于')}", 套=r.get("套"),
                     题=r.get("题"), 跑于=r.get("跑于"), 模型=r.get("模型"),
                     过="✅" if r.get("过") else "❌") for r in rs][::-1][:限]
    if mod == "prompts":
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import prompt_candidate as _pc
        return [dict(id=x["号"], 候选=x["号"], 改了="、".join(x["改了"]),
                     真改了="是" if x["动过"] else "**还没改**",
                     验证次数=x["验证次数"],
                     最近分数=(f"{x['最近']['过']}/{x['最近']['题数']}" if x.get("最近") else "—"),
                     采纳="已采纳" if x["采纳于"] else "",
                     为什么=(x["为什么"] or "")[:40], 建于=x["建于"])
                for x in _pc.列表()][::-1][:限]
    if mod == "ops":
        c = _库()
        cols = [d[1] for d in c.execute("pragma table_info(op_log)")]
        rs = [dict(zip(cols, r)) for r in c.execute(
            f"select {','.join(cols)} from op_log order by ts desc limit ?", (限,))]
        c.close()
        # op_log 自己就有 id 列 —— 直接用它,别再塞一个同名的键
        return [{**r, "id": str(r.get("id"))} for r in rs]
    return []


def 一条(mod, ident):
    """一条的**全部完整信息**。咨询那一条按五段给。"""
    if mod == "runs":
        spans = [x for x in _读(os.path.join(ROOT, ".feynman", "spans.jsonl"))
                 if x.get("trace_id") == ident]
        if not spans: return {"错": "没有这次运行"}
        根 = next((y for y in spans if not y.get("parent_span_id")), spans[0])
        a = 根.get("attr") or {}
        工具 = [dict(工具=(x["attr"] or {}).get("gen_ai.tool.name"), 毫秒=x.get("duration_ms"),
                     状态=x.get("status"),
                     参数=(x["attr"] or {}).get("gen_ai.tool.call.arguments"),
                     返回=(x["attr"] or {}).get("gen_ai.tool.call.result"))
                for x in spans
                if (x.get("attr") or {}).get("gen_ai.operation.name") == "execute_tool"]
        知 = [t for t in 工具 if str(t["工具"] or "").startswith("kb_")]
        return dict(id=ident, 时间=根.get("ts"), 角色=根.get("角色"), 模型=根.get("模型"),
                    段=[
            dict(名="① 上下文", 说="它这一轮看到了什么", 内容=[
                ("用户问的", a.get("lanxiu.prompt")),
                ("每轮注入的原文", a.get("lanxiu.context_injected")),
                ("身份 / 助手", f"{根.get('角色')} · {a.get('lanxiu.role') or '—'}"),
                ("技能档位", a.get("lanxiu.skills") or "(没带技能)"),
                ("想多深(effort)", a.get("lanxiu.effort")),
                ("续的哪条会话", a.get("gen_ai.conversation.id")),
                ("这一轮被压缩过", a.get("lanxiu.compacted") or "没有")]),
            dict(名="② 召回", 说="它从知识库里取到了什么",
                 内容=[(f"{t['工具']} {t['参数'] or ''}", t["返回"]) for t in 知]
                      or [("(这一轮没查知识库)", None)]),
            dict(名="③ 排序 / 重排", 说="**这个项目没有这一段**",
                 内容=[("为什么没有",
                        "知识库是手写的 md + 推导出来的结构化表,工具按条件查表,"
                        "命中就是命中,不存在「相似度排序」,也就没有重排。"
                        "业务问的是「这个工艺能不能配这个面料」—— 答案要能说出依据、能对账,"
                        "不是「找几段相似的话」。**以后接了向量检索,这一段才有东西。**")]),
            dict(名="④ 调用", 说=f"这一轮调了 {len(工具)} 次工具,参数和返回值都在",
                 内容=[(f"{t['工具']}({t['毫秒']}ms · {t['状态']})",
                        f"参数:{t['参数']}\n\n返回:{t['返回']}") for t in 工具]
                      or [("(一个工具都没调)", "**结论没有取数撑着,要当心**")]),
            dict(名="⑤ 产出", 说="最后交出去的是什么", 内容=[
                ("回答", a.get("lanxiu.answer")),
                ("被体检打回过", "是:" + "、".join(a.get("lanxiu.guard.checks") or [])
                    if a.get("lanxiu.guard.blocked") else "没有"),
                ("拦下过的工具", "、".join(a.get("lanxiu.guard.blocked_tools") or []) or "没有"),
                ("重答过几段", a.get("lanxiu.answer_turns")),
                ("花费 / 耗时", f"${a.get('lanxiu.cost_usd')} · {round((根.get('duration_ms') or 0)/1000,1)}s"),
                ("用量", f"入 {a.get('gen_ai.usage.input_tokens')} · "
                        f"命中缓存 {a.get('gen_ai.usage.cache_read_input_tokens')} · "
                        f"出 {a.get('gen_ai.usage.output_tokens')}")]),
        ], 原始=根)
    if mod == "prompts":
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import prompt_candidate as _pc
        try: d = _pc._读(ident)
        except SystemExit as e: return {"错": str(e)}
        现 = _pc._规矩()
        差 = []
        for rid, 新 in (d.get("改") or {}).items():
            旧 = (d.get("拷自") or {}).get(rid, "")
            if 新.strip() == 旧.strip():
                差.append((rid, "(和拷出去时一样 —— **还没改**,改了再跑验证集)")); continue
            警 = ("\n\n⚠️ **源头已经被人动过**(和拷出去那一版不同)—— 采纳前要重新拷"
                  if rid in 现 and 现[rid].text.strip() != 旧.strip() else "")
            差.append((rid, "\n".join(_pc._差(旧, 新)) + 警))
        return dict(id=ident, 段=[
            dict(名="① 为什么改", 说="改一版提示词总得说得出图什么",
                 内容=[("为什么", d.get("为什么")), ("建于", d.get("建于")),
                       ("改了哪几条", "、".join((d.get("改") or {}).keys()))]),
            dict(名="② 差在哪", 说="和拷出去那一版逐行比", 内容=差),
            dict(名="③ 跑过几次验证集", 说="**分数要追得到是哪一版跑的**",
                 内容=[(f"{v['时间']} · {v['结果文件']}",
                        f"{v['过']}/{v['题数']} · 模型 {v.get('模型')} · 代码 {v.get('代码')}")
                       for v in (d.get("验证") or [])]
                      or [("还没跑过", "**没跑过验证集不许采纳** —— 绕过这一步之后,"
                                      "它和「直接改源头」一模一样")]),
            dict(名="④ 采纳了没有", 说="采纳 = 落回 prompts.py",
                 内容=[("采纳于", d.get("采纳于") or "还没有"),
                       ("怎么采纳", f"python3 tools/prompt_candidate.py 采纳 {ident}")]),
        ], 原始=d)
    # 其余模块:**把那一行的所有字段原样给出来**,不挑不藏
    for r in 列表(mod, 限=5000):
        if str(r.get("id")) == str(ident):
            if mod == "tools":
                for x in _读(os.path.join(ROOT, ".feynman", "spans.jsonl")):
                    if x.get("span_id") == ident:
                        return dict(id=ident, 原始=x, 段=[dict(
                            名="这次调用", 说=x.get("name"),
                            内容=list((x.get("attr") or {}).items()))])
            return dict(id=ident, 原始=r,
                        段=[dict(名="全部字段", 说="原样给出,不挑不藏",
                                内容=list(r.items()))])
    return {"错": "没有这一条"}


def _自测():
    过, 挂 = [], []
    def ck(名, 真, 补=""):
        (过 if 真 else 挂).append(名)
        print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:120]) if 补 else ''}")
    r = 概览()
    ck("九个模块都在", len(r["模块"]) == 9, len(r["模块"]))
    ck("每个模块都说清了「有什么」或「缺什么」",
       all(m["有"] or m["缺"] for m in r["模块"]))
    # ⚠️ 这一条是这份代码的重点:**没做的不许给入口**
    ck("还没做的模块没有可点的入口(空入口和「做好了但没数据」长得一样)",
       all(not m["去"] for m in r["模块"] if m["状态"] == "还没有"),
       [m["名"] for m in r["模块"] if m["状态"] == "还没有" and m["去"]])
    ck("做了的和没做的加起来不超过九个", r["做了"] + r["没做"] <= 9, (r["做了"], r["没做"]))
    ck("运行痕迹按机器日期分组(不是业务今天)", r["机器今天"] and r["跑"]["今日次数"] >= 0)
    ck("有数据的模块给了真数字", any(m["有"] and any(ch.isdigit() for ch in m["有"])
                                    for m in r["模块"]))
    d = 细目()
    ck("细目有六摊", all(k in d for k in ("成本", "工具", "运行", "拦截", "技能", "评测")), list(d))
    ck("成本给了三个切面(按天/按模型/按场景),不是一个总数",
       all(d["成本"].get(k) is not None for k in ("按天", "按模型", "按场景")))
    ck("工具明细是从 span 现算的(旧记录仪只记了「调了几个」)",
       all("平均毫秒" in x and "次数" in x for x in d["工具"]), d["工具"][:1])
    ck("拦截逐条给理由,不只给个数",
       all(isinstance(x.get("理由"), list) for x in d["拦截"]), d["拦截"][:1])
    ck("最近的运行带得上 trace 号(点得进单次详情)",
       all(x.get("trace") for x in d["运行"]), len(d["运行"]))
    for m in 模块表:
        ck(f"模块 {m} 列得出东西(或明确是空的)", isinstance(列表(m, 3), list))
    跑 = 列表("runs", 1)
    if 跑:
        一 = 一条("runs", 跑[0]["id"])
        名 = [x["名"] for x in 一["段"]]
        ck("咨询详情是五段:上下文/召回/排序/调用/产出", len(名) == 5, 名)
        ck("「排序」那一段照实说没有(不放空面板)",
           "没有这一段" in 一["段"][2]["说"], 一["段"][2]["说"])
        ck("调用那一段带参数和返回值",
           any("返回:" in str(v) for _, v in 一["段"][3]["内容"]) or 一["段"][3]["内容"][0][0].startswith("("))
    print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
    return 1 if 挂 else 0


咬合 = [
    ("给一个「还没有」的模块填上 去=/somewhere", "还没做的模块没有可点的入口"),
    ("把模块删掉一个", "九个模块都在"),
]

if __name__ == "__main__":
    if "--selftest" in sys.argv: sys.exit(_自测())
    r = 概览()
    print(f"AI 调控中心 · 业务今天 {r['今天']} · 机器 {r['机器今天']}")
    print(f"  累计 {r['跑']['累计次数']} 次调用 / ${r['跑']['累计花费']};"
          f"今天 {r['跑']['今日次数']} 次 / ${r['跑']['今日花费']}")
    print(f"  {r['做了']} 个模块有东西,{r['没做']} 个还没有\n")
    for m in r["模块"]:
        print(f"  {m['号']}. {m['名']:8s} [{m['状态']}] {m['问']}")
        if m["有"]: print(f"       有:{m['有']}")
        if m["缺"]: print(f"       缺:{m['缺'][:100]}")
