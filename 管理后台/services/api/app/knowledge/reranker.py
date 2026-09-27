#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精排:让 Claude 读候选片段,判哪些真的回答了问题。

## 为什么必须有这一层(不是「让结果更好一点」)

真向量检索在真语料上实测过一次,问「客户给了差评要怎么处理」,
排**第一**的是这个:

    | # | 要做的 | 判据 / 验法 |
    |---|---|---|

**一个表格头**(相似度 0.6849)。真正的答案「≤3 星算差评;
差评自动进待处理清单」排第二(0.6329)。

这是 embedding 的已知病:**短的、抽象的文本在语义空间里占据「中心位置」**,
而中心位置对任何查询都有中等相似度 ——「要做的」「判据」这种词对什么问题都不远。

而这个缺陷**不报错**:检索永远返回 N 条,看起来一切正常。

## ⚠️ 让 LLM 做精排,最大的风险不是排错,是**编**

三种编法,每一种都有判据挡着:

  ① **编出不存在的候选编号** → 返回的编号集合必须**精确等于**给出的那些
     (集合相等,不是「至少返回了一条」)
  ② **漏掉一部分候选** → 同一条判据挡住(集合相等是双向的)
  ③ **编一个听起来合理的理由** → 理由必须**引用片段里的原话**,
     而代码去验那句话真的在那个片段里

第 ③ 条把「理由可信」从一个感觉变成一个**可执行的判据**。

## ⚠️ 失败时**不退回原顺序**

那会让「精排坏了」和「精排认为原顺序就是对的」**长得一模一样** ——
而前者是故障、后者是结论。调用方拿到的必须是一个明确的失败。

## 凭据与计费

走 CLI 登录态(钥匙串里的 OAuth token)—— **月租,不额外花钱**
(用户的规矩:开发验证一律用 Claude)。默认 `claude-haiku-4-5`:
精排任务简单、要快,而且**用的是哪个模型会跟着结果返回**,不写死在文档里。

⚠️ 用 curl 发请求,不用 Python 的 urllib —— 这台机器有 TLS 拦截,
urllib 会证书校验失败(项目里所有 HTTP 都走 curl)。
"""
import json
import os
import subprocess
import time

# 管理后台自己的记录仪 —— 见 knowledge/trace.py 的文件头。
#
# ⚠️⚠️ **Python 标准库里也有一个 `trace` 模块**(跟踪代码执行的那个)。
# 如果它先被 import,`sys.modules["trace"]` 就是标准库那个,
# 于是下面的 `trace.record(...)` 变成 **AttributeError** ——
# 而且**只在某些 import 顺序下发生**,那是最难查的一类失败。
#
# 不改名是有意的:`agent/trace_check.py` 按 `import trace` / `from trace import`
# 认「接了记录仪」,而那条检查是对的(它抓到了这个文件没接记录仪)。
# 所以保留 `import trace`,**撞车时按路径重新加载我们那个**。
#
# ⚠️ 澜绣的 `agent/trace.py` 有完全一样的风险,只是还没撞上过 —— 已告知那条线。
import trace

if not hasattr(trace, "record"):
    import importlib.util as _ilu
    _记录仪路径 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace.py")
    _spec = _ilu.spec_from_file_location("aimc_trace", _记录仪路径)
    trace = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(trace)
    assert hasattr(trace, "record"), (
        f"{_记录仪路径} 里没有 record() —— 记录仪坏了,"
        f"而没有记录仪的模型调用**花费和耗时是黑的**")

精排器版本 = "claude-rerank-1"
默认模型 = "claude-haiku-4-5"
分数上限 = 10


class 没有凭据(Exception):
    """拿不到 Claude 凭据。**当场抛,不退回原顺序。**"""


class 精排失败(Exception):
    """模型返回的东西不符合契约(编了编号 / 漏了候选 / 理由是编的)。

    ⚠️ **不降级成「按原顺序」** —— 见文件头。
    """


def _凭据():
    """从钥匙串取 OAuth token。⚠️ **绝不把 token 写进任何返回值或异常。**"""
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k:
        return ["x-api-key: " + k, "anthropic-version: 2023-06-01"]
    r = subprocess.run(
        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise 没有凭据(
            "钥匙串里没有 Claude 凭据,也没有 ANTHROPIC_API_KEY —— "
            "**不退回原顺序**:那会让「精排坏了」和「精排认为原顺序对」长得一样")
    try:
        tok = json.loads(r.stdout).get("claudeAiOauth", {}).get("accessToken")
    except json.JSONDecodeError:
        raise 没有凭据("钥匙串里那条读不出 JSON")
    if not tok:
        raise 没有凭据("钥匙串里没有 accessToken")
    return ["authorization: Bearer " + tok, "anthropic-version: 2023-06-01",
            "anthropic-beta: oauth-2025-04-20"]


# ⚠️ **工具名和 schema 的属性名都必须是 ASCII。**
#   工具名:   `^[a-zA-Z0-9_-]{1,128}$`
#   属性名:   `^[a-zA-Z0-9_.-]{1,64}$`
#
# 这是今天第三次踩「中文标识符」——① bash 变量名 ② SQL 注释里的 `:中文`
# ③ 这里。三个约束来自三个不同的层。
#
# ⚠️ 而且我在这儿**先说错了一次**:改工具名的时候我判断「schema 的属性名
# 算内容不算标识符」,下一次调用就被 API 证伪了。
# **正确的边界是:任何会被外部系统当成标识符解析的位置都要 ASCII** ——
# property key 要被 schema 校验器当键匹配,它就是标识符。
# (提示词里的中文、下面 description 里的中文,那些才是内容。)
_打分工具 = {
    "name": "score_candidates",
    "description": "对每一条候选片段,判它在多大程度上回答了用户的问题。",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer",
                                  "description": "候选的编号,必须是给出的那些之一"},
                        "score": {"type": "integer", "minimum": 0,
                                  "maximum": 分数上限,
                                  "description": f"0 到 {分数上限}。"
                                                 f"0 = 完全没回答这个问题"},
                        "quote": {"type": "string",
                                  "description": "从这条片段里**原样抄**一个短语"
                                                 "(5-20 字),说明你为什么这么打分。"
                                                 "**必须是片段里真有的字**,不许改写"},
                    },
                    "required": ["index", "score", "quote"],
                },
            },
        },
        "required": ["results"],
    },
}

_提示 = """你在给一个知识库的检索结果做精排。

用户的问题:
{问题}

候选片段(每条带编号):
{候选}

给**每一条**候选打分(0-{上限}):它在多大程度上**直接回答了**这个问题。

判分要点:
- **表格头、目录、分隔行这类没有内容的片段给 0** —— 它们对任何问题都不回答
- 提到了相关的词但没回答问题的,给低分(1-3)
- 回答了问题的一部分,给中分(4-6)
- 直接、完整地回答了问题,给高分(7-{上限})

每一条都要有「引文」:从那条片段里**原样抄**一个短语(5-20 字)。
**必须是片段里真有的字,不许改写、不许翻译、不许总结。**
**宁可引短一点,也不要补标点或闭合括号** —— 引一段连续的原文就行。

必须对**全部 {条数} 条**都打分,一条不漏、不多。"""


# Markdown 的格式标记。**剥掉它们再比引文** —— 模型抄原话时会顺手清理格式,
# 而那不是「编」。
# `|` 也在里面:它是 Markdown 表格的格式标记(而表格头恰好是最常见的噪声片段)。
# ⚠️ 括号也在里面,起因是一个**真实案例**:
#   原文:返修判定表「尺寸偏差」那一支(现在没有数值,这一支实际判不了)
#   引文:返修判定表「尺寸偏差」那一支(现在没有数值)
#                                              ↑ 引了前半截,自己**闭合了括号**
# 每个字都在原文里,只是补了一个 `)`。剥掉括号之后就对上了,
# 而剥括号**不改变字的顺序和内容** —— 所以「重写一句话」仍然过不了。
_格式标记 = ("**", "__", "~~", "`", "#", "*", "_", ">", "|",
           "(", ")", "(", ")", "[", "]", "【", "】")


def _剥格式(t):
    """去掉 Markdown 标记和多余空白,用来比对引文。

    ## 为什么不要求逐字节相同

    实测第一版要求逐字节,**三条引文全被判成「编的」**,而看内容它们是原话:

        片段:  **≤3 星算差评**;差评**自动进待处理清单**(有人负责跟)
        引文:    ≤3 星算差评;差评自动进待处理清单        ← 只是剥掉了 **

    ## 为什么不放得更宽(比如只比字符集合)

    **判据太严和太松的代价方向不同,而且不对称:**
      · 太松 → 编的理由过关,**而且没人会发现**
      · 太严 → 真实引用被拒,**功能完全不可用**(吵闹,一跑就撞上)

    剥格式之后比子串,正好卡在中间:**抄原话(哪怕清理了格式)能过,
    重写一句话过不了** —— 重写会动到字,而剥格式不动字。
    """
    for m in _格式标记:
        t = t.replace(m, "")
    return "".join(t.split())


def 校验打分(打分们, 编号到候选, *, 上限=分数上限):
    """校验模型返回的打分。**纯函数** —— 不发请求,所以判据能零依赖测。

    返回排好序的清单;不合契约就抛 `精排失败`。

    ## 为什么提成纯函数

    这里的判据(编号集合相等、引文真的在片段里、0 分免引文)是这个模块
    **最要紧的部分** —— 它们挡的是 LLM 的三种编法。
    而 CI 里**没有 Claude 凭据**(admin job 只装 sqlalchemy,也没有钥匙串),
    所以判据必须能在不发请求的情况下被测:否则这些防护只在有人手工跑的时候才验过。

    > **一条只在手工跑时被验过的防护,和没有防护的差别只在验的人脑子里。**
    """
    if not isinstance(打分们, list):
        raise 精排失败(f"`results` 不是清单,是 {type(打分们).__name__}")
    给了 = set(编号到候选)
    回了 = [x.get("index") for x in 打分们]
    if len(回了) != len(set(回了)):
        重 = sorted({i for i in 回了 if 回了.count(i) > 1})
        raise 精排失败(f"同一个编号打了两次:{重}")
    if set(回了) != 给了:
        多 = sorted(x for x in set(回了) - 给了 if x is not None)
        少 = sorted(给了 - set(回了))
        raise 精排失败(
            f"编号对不上 —— 编出来的 {多}、漏掉的 {少}。"
            f"**集合相等判据,不是「至少返回了一条」**:"
            f"漏掉的那些会静默消失在结果里,而编出来的指向不存在的片段")

    出, 编的 = [], []
    for x in 打分们:
        i = x["index"]
        c = 编号到候选[i]
        引 = (x.get("quote") or "").strip()
        分 = x.get("score")
        if not isinstance(分, int) or isinstance(分, bool) or not (0 <= 分 <= 上限):
            raise 精排失败(f"编号 {i} 的分数不合格:{分!r}(要 0-{上限} 的整数)")
        if 分 == 0:
            # ⚠️ **0 分免于引文校验,而且这不是放松。**
            #
            # 引文的作用是支撑「为什么这段相关」,而 0 分的意思正是「不相关」——
            # 要求一个 0 分的候选给出引文,等于**逼模型为一个不存在的关联编一个证据**。
            # 实测撞到过:表格头片段(`| # | 要做的 | 判据 / 验法 |`)拿了 0 分,
            # 而它的「引文」只能是表格里那几个词,怎么抄都像编的。
            #
            # **判据不该逼被测对象造假。**
            pass
        elif not 引:
            编的.append((i, f"给了 {分} 分但引文是空的 —— "
                           f"非 0 分意味着「这段回答了问题」,那就该指出是哪一句"))
        elif _剥格式(引) not in _剥格式(c["text"]):
            # **这条判据把「理由可信」变成可执行的。** 编的理由当场被抓到。
            # ⚠️ 比的是**剥掉 Markdown 标记之后**的子串关系(见 `_剥格式`)——
            # 逐字节比会把「抄原话但清理了格式」判成编的,而那让功能完全不可用。
            编的.append((i, f"引文不在片段里:{引[:24]!r}"))
        出.append(dict(id=c["id"], 分数=分, 引文=引, 原序=i,
                      text=c["text"], **{k: v for k, v in c.items()
                                         if k not in ("id", "text")}))
    # ── 引文对不上时:**单条是噪声,大面积是故障** ──────────────────
    #
    # ⚠️ 上一版是「有一条对不上就整个失败」,而在 12 个候选上**总会有一条** ——
    # 一条引文的小瑕疵让整条检索不可用,那个代价不对。
    #
    # 但也不能静默放过:**放过多少条、是哪几条,必须报出来**。
    # 所以少数几条标记成 `引文可信=False` 并带原因,
    # 超过 1/3 才判失败(那时候模型是在乱来,不是引用瑕疵)。
    if 编的:
        坏号 = {i for i, _ in 编的}
        for x in 出:
            if x["原序"] in 坏号:
                x["引文可信"] = False
                x["引文问题"] = next(r for i, r in 编的 if i == x["原序"])
        阈值 = max(1, len(编号到候选) // 3)
        if len(编的) > 阈值:
            raise 精排失败(
                f"{len(编的)}/{len(编号到候选)} 条的引文对不上(超过 1/3 的阈值 {阈值})"
                f":{编的[:3]} —— **理由能被验证,才算理由**。"
                f"大面积对不上说明打分不是从片段内容来的")
    for x in 出:
        x.setdefault("引文可信", True)
    出.sort(key=lambda x: (-x["分数"], x["原序"]))
    return 出


def 精排(问题, 候选们, *, 模型=None, 上限=None):
    """让 Claude 给候选打分。

    `候选们`:[{"id": …, "text": …}],至少一条。
    返回 {排好的, 用量, 模型, 精排器版本, 是mock=False}
    —— `排好的` 按分数从高到低,每项带 {id, 分数, 引文, 原序}。

    ⚠️ 一条都不许漏、不许多、引文必须真的在片段里 —— 见文件头。
    """
    if not 候选们:
        raise 精排失败("候选是空的 —— 精排不该在没有候选的时候被调用,"
                     "「没召回到」和「排完是空的」是两件事")
    模型 = 模型 or os.environ.get("RERANK_MODEL") or 默认模型
    上限 = 上限 or 分数上限

    编号到候选 = {i + 1: c for i, c in enumerate(候选们)}
    候选文 = "\n\n".join(
        f"[{i}] {c['text'][:600]}" for i, c in 编号到候选.items())
    体 = {
        "model": 模型, "max_tokens": 2000,
        "tools": [{**_打分工具, "input_schema": {
            **_打分工具["input_schema"]}}],
        "tool_choice": {"type": "tool", "name": "score_candidates"},
        "messages": [{"role": "user", "content": _提示.format(
            问题=问题, 候选=候选文, 上限=上限, 条数=len(候选们))}],
    }
    参 = ["curl", "-sS", "-m", "120", "https://api.anthropic.com/v1/messages",
          "-H", "content-type: application/json"]
    for h in _凭据():
        参 += ["-H", h]
    参 += ["-d", json.dumps(体, ensure_ascii=False)]
    _t0 = time.time()
    r = subprocess.run(参, capture_output=True, text=True)
    _耗时 = int((time.time() - _t0) * 1000)

    def _记(成功, 用量=None, 细节=None):
        # ⚠️ **每一条出口都要记**,包括失败的那些 ——
        # 只记成功的调用会让「失败花掉的时间」变成黑的,
        # 而那正是排查「为什么这么慢」时最需要的数。
        trace.record(用途="知识检索精排", 模型=模型, 用量=用量,
                     耗时毫秒=_耗时, 成功=成功, 是mock=False, 细节=细节)

    if r.returncode != 0:
        _记(False, 细节={"curl退出码": r.returncode})
        # ⚠️ 只报 curl 的退出码和 stderr,**不回显请求体**(它带着 header)
        raise 精排失败(f"curl 失败(退出码 {r.returncode}):{r.stderr.strip()[:200]}")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        _记(False, 细节={"为什么": "返回的不是 JSON"})
        raise 精排失败(f"返回的不是 JSON:{r.stdout[:200]}")
    if "error" in d:
        _记(False, 细节={"API报错": str(d["error"].get("message"))[:120]})
        raise 精排失败(f"API 报错:{str(d['error'].get('message'))[:200]}")
    _记(True, 用量=d.get("usage") or {}, 细节={"候选数": len(候选们)})

    块们 = [b for b in d.get("content", []) if b.get("type") == "tool_use"]
    if not 块们:
        # 模型没调工具 —— **不去解析它的自由文本**。
        # 那会让「它没按契约来」变成「我猜它想说什么」。
        文 = " ".join(b.get("text", "") for b in d.get("content", []))
        raise 精排失败(f"模型没调 score_candidates(stop_reason={d.get('stop_reason')})"
                     f",说的是:{文[:150]} —— **不去解析自由文本**")
    打分们 = 块们[0].get("input", {}).get("results") or []

    出 = 校验打分(打分们, 编号到候选, 上限=上限)
    return dict(排好的=出, 用量=d.get("usage") or {},
                模型=d.get("model") or 模型, 精排器版本=精排器版本, 是mock=False)
