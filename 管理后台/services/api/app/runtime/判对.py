#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测里「答得对不对」怎么判(DF-05 后续,用户 2026-11-05 拍:**C 两种结合 + 两轮都对才算对**)。

## 用户选的规则

- 一道题**能写成字段判据**的,按字段比 —— 不花钱、讲得清是哪一项错了
- **写不成的**(比如「这段跟进写得对不对」)才交给模型评审(Claude,CLAUDE.md §4 评测一律 Claude),
  结果上标明「模型判的」,可以抽查
- 一道题算对:**两轮都对才算对**;两轮不一致的另列(同一版本连跑两轮会各掉一道不同的题,项目实测过)

## 字段判据长什么样(题的 content 里)

    "判据": [
      {"项": "/品类",       "方式": "等于",     "值": "褙子"},
      {"项": "/预算",       "方式": "在范围内", "值": [2800, 3200]},
      {"项": "/客户号",     "方式": "有这一项"},
      {"项": "/工期档",     "方式": "是其中之一", "值": ["常规", "加急"]}
    ],
    "期望说明": "写跟进时要提到顾客想看真丝和棉麻两种面料"      ← 只有这个、没有判据 → 交给模型评审

⚠️ **只比结构化字段,不拿关键词去匹配成段的话。** 这个项目为「拿一串中文词判模型说了什么」栽过七次
(「不能 / 不可」差一个字就判错)—— 所以没有「包含某个词」这种方式;成段的话一律交给模型评审。

这个模块**不碰数据库、不调模型**:收结果的那一步(eval_dispatch)拿它判字段;模型评审另走一步。
"""

方式们 = ("等于", "在范围内", "有这一项", "是其中之一")
_没有 = object()


def _取(输出, 指针):
    """JSON Pointer 风格(/a/b/0)。取不到 → _没有(和「取到了 None」分开)。"""
    当前 = 输出
    for 段 in [x.replace("~1", "/").replace("~0", "~") for x in str(指针 or "").lstrip("/").split("/") if x != ""]:
        if isinstance(当前, dict) and 段 in 当前:
            当前 = 当前[段]
        elif isinstance(当前, list) and 段.isdigit() and int(段) < len(当前):
            当前 = 当前[int(段)]
        else:
            return _没有
    return 当前


def 判据格式问题(判据们):
    """→ 问题清单(空 = 格式对)。建评测 / 派发前就查,别等跑完才发现一条判据写错了。"""
    问 = []
    if not isinstance(判据们, list) or not 判据们:
        return ["判据要是一个非空列表"]
    for i, j in enumerate(判据们):
        if not isinstance(j, dict) or not str(j.get("项") or "").startswith("/"):
            问.append(f"第 {i + 1} 条:要写「项」(以 / 开头的字段位置,比如 /品类)")
            continue
        式 = j.get("方式")
        if 式 not in 方式们:
            问.append(f"第 {i + 1} 条:方式只收 {'、'.join(方式们)}(没有「包含某个词」—— 成段的话写进「期望说明」交给模型评审)")
        elif 式 == "在范围内" and not (isinstance(j.get("值"), list) and len(j["值"]) == 2
                                     and all(isinstance(x, (int, float)) for x in j["值"]) and j["值"][0] <= j["值"][1]):
            问.append(f"第 {i + 1} 条:在范围内要给 [下限, 上限] 两个数")
        elif 式 == "是其中之一" and not (isinstance(j.get("值"), list) and j["值"]):
            问.append(f"第 {i + 1} 条:是其中之一要给一个非空列表")
        elif 式 == "等于" and "值" not in j:
            问.append(f"第 {i + 1} 条:等于要给「值」")
    return 问


def 判法(题内容):
    """→ "字段" / "模型" / None(这道题既没判据也没期望说明 —— 只报跑通,不判对错)。"""
    c = 题内容 or {}
    if c.get("判据"):
        return "字段"
    if str(c.get("期望说明") or "").strip():
        return "模型"
    return None


def 按字段判(输出, 判据们):
    """→ (对不对, 逐条理由)。**每一条都要过才算对**;理由写清是哪一项、期望什么、实际是什么。"""
    理由, 全过 = [], True
    for j in 判据们:
        实 = _取(输出, j["项"])
        式, 值 = j["方式"], j.get("值")
        if 式 == "有这一项":
            过 = 实 is not _没有 and 实 not in (None, "", [], {})
        elif 实 is _没有:
            过 = False
        elif 式 == "等于":
            过 = 实 == 值
        elif 式 == "在范围内":
            过 = isinstance(实, (int, float)) and not isinstance(实, bool) and 值[0] <= 实 <= 值[1]
        else:  # 是其中之一
            过 = 实 in 值
        全过 = 全过 and 过
        实说 = "没有这一项" if 实 is _没有 else repr(实)[:60]
        理由.append(f"{'✓' if 过 else '✗'} {j['项']} {式}{'' if 式 == '有这一项' else ' ' + repr(值)[:40]}(实际:{实说})")
    return 全过, 理由


def 两轮合起来(各轮):
    """各轮 = {轮次: True / False / None(没判出来)}。→ (结论, 说法)。

    用户拍:**两轮都对才算对**。有一轮没判出来(模型评审还没出结果 / 演示模型判的不算)→ 结论 None(不当成错)。
    两轮一对一错 → 错,另标「两轮不一致」。"""
    值们 = list(各轮.values())
    if not 值们 or any(v is None for v in 值们):
        return None, "还有一轮没判出来"
    if all(值们):
        return True, "两轮都对"
    if any(值们):
        return False, "两轮不一致(一轮对一轮错)—— 按「两轮都对才算对」判错"
    return False, "两轮都错"


# ── 模型评审(写不成字段判据的题)──────────────────────────────────────────
评审系统提示 = ("你是一名严格的评测员。只根据「期望说明」判断「实际输出」是否满足要求,不要根据你自己的偏好加分或扣分。"
          "期望说明里没提到的方面不考虑。只输出一个 JSON 对象,不要别的文字:"
          "{\"对\": true 或 false, \"理由\": \"一两句话,说清满足了哪一条或缺了哪一条,引用原话用「」\"}")


def 评审用户消息(题内容, 输出):
    import json as _j
    return ("期望说明:\n" + str((题内容 or {}).get("期望说明") or "").strip()
            + "\n\n这道题的输入:\n" + _j.dumps((题内容 or {}).get("输入"), ensure_ascii=False, default=str)[:4000]
            + "\n\n实际输出:\n" + _j.dumps(输出, ensure_ascii=False, default=str)[:8000])


def 解析评审(文本):
    """模型评审的回答 → (对 True/False/None, 理由)。看不懂就 None(**不当成错,也不当成对**),理由里带原文开头。"""
    import json as _j
    import re as _re
    s = str(文本 or "")
    m = _re.search(r"\{.*\}", s, _re.S)
    try:
        d = _j.loads(m.group(0)) if m else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("对"), bool):
        return None, "评审的回答看不懂(不是带「对」字段的 JSON):" + s[:120]
    return d["对"], str(d.get("理由") or "")[:400]
