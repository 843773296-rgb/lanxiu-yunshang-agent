#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询改写(§9.5 的「改写」)—— **业务 2026-10-08 拍的:调模型改写。**

顾问问「云锦一匹料要织多久」,而语料里写的是「妆花缎 · 门幅 · 工期」——
向量检索靠语义相似度,**用词差太远时召回不到**。改写在算向量之前,
把口语问法变成更贴语料的说法。

## ⚠️ 拍板时我提的那个缺点,这里用结构拦住

> 调模型改写**结果不稳定** —— 同一个问题两次改出不同说法,
> 而那让「检索结果为什么变了」变得难查。

所以:

  **① `temperature=0`** —— 同一个问题尽量给同一个改写。
     (它**不保证**完全确定,所以还有 ②。)
  **② 改写结果进链路、进记录仪** —— 返回的 `改写` 不再是 None,
     而是模型真给出的那句话。
     > 一次「召回变了是因为语料变了」和一次「召回变了是因为改写变了」,
     > **在那份结果上长得一模一样** —— 除非把改写那句话留下来。
  **③ 原问一直带着** —— 返回里 `原问` 和 `改写` 并列,谁都能对照着看。

## ⚠️ 改写失败**降级成原问,但要说出来**

和精排不同:精排失败时排序不可靠,所以 `reranker` 选择**抛**;
而改写失败时用原问**仍然检索得到**(只是可能召回差一点)。
所以这里降级 —— **但 `改写说明` 里写清它失败了、为什么**。
> 一次「改写认为原问就是最好的」和一次「改写根本没跑成」,
> **在 `改写 is None` 上长得一模一样** —— 所以这两种要用不同的说明文字。

## ⚠️ 它不做什么

- **不改写成多个查询**(多查询 / HyDE)—— 那会改变召回条数的含义,
  而 `candidate_k` 的语义现在是「一次向量检索取几条」。
- **不自己判断「要不要改写」** —— 每次都改。省掉一次模型调用的代价是
  多一个判断,而那个判断本身也会错,且更难查。
"""
import json
import os
import subprocess
import sys
import time

_这 = os.path.dirname(os.path.abspath(__file__))
if _这 not in sys.path:
    sys.path.insert(0, _这)

import llmtrace as trace          # noqa: E402  (名字见 reranker 文件头那段)
import reranker as RR             # noqa: E402  复用凭据与模型选择,不另起一套

改写器版本 = "rewrite-1"
默认模型 = "claude-haiku-4-5"

_提示 = """你在帮一个汉服定制工坊的知识库做**检索查询改写**。

顾问的问法是口语,而语料是业务拍板记录和领域知识,用词很专
(形制、色系、工艺名、门幅、工期这类)。

把下面这句问话改写成**更接近语料用词**的检索查询。要求:
1. 只输出改写后的查询,不要解释;
2. **不要添加原问里没有的限定**(别自己加时间、数量、人名);
3. 保留原问的意图;拿不准就尽量贴近原话。

原问:{问题}"""

_工具 = {
    "name": "rewrite_query",
    "description": "给出改写后的检索查询",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "改写后的查询"},
            "why": {"type": "string", "description": "一句话说明改了什么"},
        },
        "required": ["query"],
    },
}


class 改写失败(Exception):
    """调用层面的失败。**调用方应当降级成原问,并把这句话写进链路。**"""


def 改写(问题, *, 模型=None):
    """返回 `(改写后的查询, 说明)`。失败抛 `改写失败` —— 由调用方决定降级。

    ⚠️ `temperature=0`:见模块头 ①。
    """
    模型 = 模型 or os.environ.get("REWRITE_MODEL") or 默认模型
    体 = {
        "model": 模型, "max_tokens": 300, "temperature": 0,
        "tools": [_工具],
        "tool_choice": {"type": "tool", "name": "rewrite_query"},
        "messages": [{"role": "user",
                      "content": _提示.format(问题=问题)}],
    }
    参 = ["curl", "-sS", "-m", "30", "https://api.anthropic.com/v1/messages",
          "-H", "content-type: application/json"]
    for h in RR._凭据():
        参 += ["-H", h]
    参 += ["-d", json.dumps(体, ensure_ascii=False)]
    _t0 = time.time()
    r = subprocess.run(参, capture_output=True, text=True)
    耗时 = int((time.time() - _t0) * 1000)

    def _记(成功, 用量=None, 细节=None):
        # ⚠️ **每一条出口都要记**(和 reranker 同一条规矩)——
        # 失败的那些才是以后要查的。
        try:
            trace.record(用途="查询改写", 模型=模型, 成功=成功,
                         耗时毫秒=耗时, 用量=用量 or {},
                         细节={"改写器版本": 改写器版本, **(细节 or {})})
        except Exception:
            pass

    if r.returncode != 0:
        _记(False, 细节={"curl": r.returncode, "stderr": r.stderr[:200]})
        raise 改写失败(f"调用失败(curl {r.returncode}):{r.stderr[:160]}")
    try:
        d = json.loads(r.stdout)
    except Exception as e:
        _记(False, 细节={"解析": str(e)[:120]})
        raise 改写失败(f"返回不是 JSON:{r.stdout[:160]}")
    if d.get("type") == "error":
        _记(False, 细节={"api": str(d.get("error"))[:200]})
        raise 改写失败(f"接口报错:{str(d.get('error'))[:200]}")
    for blk in d.get("content") or []:
        if blk.get("type") == "tool_use":
            q = (blk.get("input") or {}).get("query") or ""
            why = (blk.get("input") or {}).get("why") or ""
            if not q.strip():
                _记(False, 用量=d.get("usage") or {}, 细节={"空": True})
                raise 改写失败("模型给了空的改写 —— **不拿空串当改写结果**")
            _记(True, 用量=d.get("usage") or {},
                细节={"原问": 问题[:80], "改写": q[:80]})
            return q.strip(), (why.strip() or "(模型没说改了什么)")
    _记(False, 用量=d.get("usage") or {}, 细节={"没有tool_use": True})
    raise 改写失败("返回里没有 tool_use —— 模型没按工具格式回")


# ── 这几条改坏了,哪一节会红 ────────────────────────────────────────
# 判据在 `tests/orchestration/test_rewriter.py`:
#   temperature 不是 0            → ② 稳定性那一条
#   空改写被当成结果放行           → ③ 不拿空串当改写
#   失败时不抛、返回原问            → ④ 降级要由调用方做,这里不替它决定
#   去掉 trace.record              → ⑤ 每条出口都要记
