# -*- coding: utf-8 -*-
"""要模型交一个 JSON 对象的那几步:解析、解析不了重问一次、两次的用量加在一起(用户 2026-11-02 拍「三步都做」)。

## 为什么有这一份

录音跟进的连接测试里,「提取客户需求」那一步 9 次坏了 2 次(OUTPUT_NOT_JSON),落在不同的录音上;
一坏整条运行就失败、跟进写不进去。而原来失败时**模型原文不落库**,报错的建议却写着「看这一步的原文」——
照着去看是看不到的,于是连病根都查不了。

## 做什么

  · 解析不了 → **重问一次**(同样的问题,末尾加一句「上次不是合法 JSON」)。第二次还不行才算失败
  · **两次的用量加在一起**交回去 —— 不然重问花的钱从账上消失,而那正是「出错的代价」
  · 还失败 → 抛 `节点失败`,并把**两次原文**挂在 `.出` 上:runner 拿它和成功输出走同一条存储、同一套遮挡

截断(finish_reason = max_tokens)不重问:截断是上限的问题,重问一遍还是截在同一个地方,只会多花一次钱。
那一支由调用方在调这里之前先判(见 workers/worker.py)。

真调模型的那个函数由调用方传进来(`重问`),这里不 import 真模型 —— 好让测试用假的回答直接跑这一段。
"""
import json
import re

import runner as RN


def 解析(文):
    """→ dict 或 None。取回答里第一个 `{` 到最后一个 `}` 那一段;不是对象也算解析不了。"""
    m = re.search(r"\{.*\}", (文 or "").strip(), re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except ValueError:
        d = None
    return d if isinstance(d, dict) else None


def 加用量(a, b):
    """两次调用的用量按键相加;非数字的(比如模型名)取后一次的。"""
    a, b = a or {}, b or {}
    out = {}
    for k in set(a) | set(b):
        x, y = a.get(k), b.get(k)
        数 = (int, float)
        if (x is None or isinstance(x, 数)) and (y is None or isinstance(y, 数)) and not isinstance(x, bool):
            out[k] = (x or 0) + (y or 0)
        else:
            out[k] = y if y is not None else x
    return out


def 要JSON(首, 重问):
    """首 = 第一次调用的结果(含 text / usage / finish_reason / actual_model);重问 = 无参函数,再调一次、返回同样形状。
    → (解析出的 dict, 最后一次的结果, 合计用量, 重问过吗)。两次都解析不了 → 抛 RN.节点失败,`.出` 里是两次原文。"""
    解 = 解析(首.get("text"))
    if 解 is not None:
        return 解, 首, 首.get("usage") or {}, False
    次 = 重问()
    用 = 加用量(首.get("usage"), 次.get("usage"))
    解 = 解析(次.get("text"))
    if 解 is not None:
        return 解, 次, 用, True
    e = RN.节点失败("OUTPUT_NOT_JSON", "模型没按要求输出 JSON 对象(重问了一次也不行)",
                   "看这一步的输出:两次的原文都存着;常见原因是处理要求里没说清输出格式")
    e.出 = {"第一次原文": 首.get("text"), "第二次原文": 次.get("text"), "usage": 用}
    raise e
