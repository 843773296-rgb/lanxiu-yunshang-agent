#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记录仪:每一次真正调模型的地方都要经过这里。

## 为什么管理后台需要自己的一份

澜绣那边有 `agent/trace.py` + `agent/trace_check.py`,后者断言
**「每一个真正调模型的地方,都接了记录仪」**。它的理由写在那个文件里:

> **可观测性不会自动跟着架构走。换一代架构,记录仪要重新接一次。**
> 而这件事没人会提醒你,因为漏了它的表现是「一切正常」。

2026-09-27 我在管理后台加了 `reranker.py`(直接打 Anthropic API),
**用量哪儿都没记** —— 而那条检查当场把它抓出来了(CI 红)。
我原来的想法是「调用方自己去记」,而那等于没人记。

管理后台不 import 澜绣的记录仪(两个独立项目、独立 venv),所以自己有一份。
**不是为了过检查,是因为它确实需要一个记模型调用的地方。**

## ⚠️ 为什么叫 `llmtrace` 不叫 `trace`

**Python 标准库里有一个 `trace` 模块**(跟踪代码执行的那个)。
叫 `trace` 的话,标准库那个先被 import 就会占住 `sys.modules["trace"]`,
于是 `trace.record(...)` 变成 AttributeError ——
**而且只在某些 import 顺序下发生**,那是最难查的一类失败。

第一版就叫 `trace`,撞上了按路径重新加载(修补)。并行会话指出一个缝:
那只修了调用方模块里的名字,`sys.modules["trace"]` 还是标准库那个 ——
下一个在这儿写调模型代码的人照样撞。

> **绕过一个不该存在的冲突,和让冲突不存在,是两件事。**

改名之后冲突不可能发生,也就不需要「撞上了怎么办」那段代码。

## 记录仪 ≠ 计费账本

这两件事分开:

    记录仪(这个文件)     「发生了什么」—— 模型、耗时、用量、成功没成功。
                        写 JSONL,**可观测性的最低保证**
    `usage_ledger` 表    「算多少钱」—— 由调用方在事务里写,有幂等键防重复计费

混成一件的后果:一次失败的调用要么进不了账本(于是看不见它花的时间),
要么进了账本(于是账上多一笔没产出的钱)。

## ⚠️ `record()` 不抛

记录仪坏了不该让被记录的功能坏掉 —— 写日志失败只是丢了一条观测,
而抛出去会让一次**成功的**模型调用变成失败。
但**失败要留痕**:写不进去时往 stderr 打一行,不静默。
"""
import json
import os
import sys
import time

日志路径 = os.environ.get("AIMC_TRACE_LOG") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))),
    ".trace", "llm-trace.jsonl")


def record(*, 用途, 模型, 用量=None, 耗时毫秒=None, 成功=True, 是mock=False,
           细节=None, 提供方="anthropic"):
    """记一次模型调用。**不抛** —— 见文件头。

    `用途` 是必填的:一条不知道自己在干什么的记录,事后没法归因
    (「这 3000 个 token 花在哪了」是这份日志的主要问题)。
    """
    行 = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), 用途=用途, 模型=模型,
              提供方=提供方, 用量=用量 or {}, 耗时毫秒=耗时毫秒,
              成功=bool(成功), 是mock=bool(是mock), 细节=细节 or {})
    try:
        os.makedirs(os.path.dirname(日志路径), exist_ok=True)
        with open(日志路径, "a", encoding="utf-8") as f:
            f.write(json.dumps(行, ensure_ascii=False) + "\n")
    except Exception as e:
        # ⚠️ **不静默。** 写不进去是观测丢了,而丢了观测要有人知道。
        print(f"⚠️ 记录仪写不进去({type(e).__name__}: {e})—— "
              f"这次调用的花费和耗时是黑的:{行['用途']} / {行['模型']}",
              file=sys.stderr)
    return 行


def 读回(限=None):
    """把日志读回来。给检查和「用量与成本」页面用。"""
    if not os.path.exists(日志路径):
        return []
    出 = []
    with open(日志路径, encoding="utf-8") as f:
        for line in f:
            try:
                出.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # 半截行(进程被 kill)跳过,不让它毒死整份日志
    return 出[-限:] if 限 else 出
