# -*- coding: utf-8 -*-
"""这一轮的技能:能用 / 请求了 / 加载了 / 被拦或失败(证据中心 P1「Skill 三态」,需求文档 3.2)。

**只看当时留下的记录**(根上的 lanxiu.skills.available、每次 Skill 调用的 span),不拿现在的策略重判历史 ——
技能后来改了状态、改了内容,这一轮当时发生了什么照旧是什么(版本哈希是请求那一刻的)。
「业务执行完成」不在这里判:加载成功不等于照着做了、更不等于业务做成了,要看下游动作和回执,照实标「未单独判定」。
"""


def 分类(rows):
    """一轮的 spans → {可用:[...], 请求:[{技能, 状态, 版本, 理由}], 没用上的:[...], 说明}。纯函数。"""
    根 = next((s for s in rows if not s.get("parent_span_id")), {}) or {}
    可用 = list((根.get("attr") or {}).get("lanxiu.skills.available") or [])
    请求 = []
    for s in rows:
        a = s.get("attr") or {}
        if a.get("gen_ai.operation.name") != "execute_tool" or a.get("gen_ai.tool.name") != "Skill":
            continue
        名 = a.get("lanxiu.skill.name") or _参数里的名(a.get("gen_ai.tool.call.arguments"))
        回 = str(a.get("gen_ai.tool.call.result") or "")
        if s.get("status") == "error" or "拦" in 回 or "没有放行" in 回:
            状 = "被拦" if ("拦" in 回 or "没有放行" in 回 or "接管" in 回) else "加载失败"
        elif 回.startswith("Launching skill"):
            状 = "已加载"
        elif "gen_ai.tool.call.result" not in a:
            状 = "没有回执"
        else:
            状 = "加载失败"
        请求.append({"技能": 名, "状态": 状, "版本": a.get("lanxiu.skill.sha256"), "理由": 回[:200] if 状 != "已加载" else None})
    用过 = {x["技能"] for x in 请求}
    return {"可用": 可用, "请求": 请求, "没用上的": [x for x in 可用 if x not in 用过],
            "说明": ("可用 ≠ 请求 ≠ 加载;**加载了不等于照着做了,更不等于业务做成了** —— 业务完成看下游动作和回执,这里不单独判定"
                     + ("" if 可用 else "。这一轮没记「可用技能清单」(10-25 之前的记录)"))}


def _参数里的名(x):
    import json
    try:
        return str((json.loads(x) if isinstance(x, str) else (x or {})).get("skill") or "?").lstrip("/")
    except Exception:
        return "?"
