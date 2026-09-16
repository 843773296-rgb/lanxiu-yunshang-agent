#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测结果落盘 —— **每条记录都得说清是谁跑出来的。**

2026-09-15 加。当天撞上的事:用 DeepSeek 跑了一轮完整评测,
六套的结果**直接覆盖了 Claude 的那份基线**,而两者在文件里长得一模一样 ——
没有任何字段记着这条是哪家模型答出来的。

评测结果是进版本库的(`CLAUDE.md` 第 8 节:「它是这个版本在这套题上考了多少分
的历史,是可比对的度量」)。**一份分不清供应商的历史,不是历史,是一堆数。**

这和这个项目反复撞的是同一件事:

    估算 / 复核 / 版师 / BOM  —— 四种可信度,不许长得一样
    快照 / 现算               —— 成交价不许从配置表现算
    占位符 / 真出处           —— 「演示数据」不是出处
    **这一次:哪家模型跑的**

所以每条记录多三个字段:`供应商`、`模型`、`跑于`。
`tools/eval_provenance_check.py` 强制它们在,并且**一份文件里不许混两家** ——
混了的话「这一版考了多少分」这句话就没有主语了。
"""
import datetime, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def 供应商():
    return (os.environ.get("LANXIU_PROVIDER", "") or "claude").lower()


def 代码():
    """跑这一轮时的提交号。

    ⚠️ **同一天 ≠ 同一份代码。** `tools/eval_compare.py` 原来只比日期,
    于是两轮之间改过判据也照样说「可以当结论」——
    它防住了「差两天」,却放过了「差三次提交」。
    而这个漏洞**只在结论那一行显形**:表照样出,只是那句话变成了假话。

    脏工作区标 `+dirty` —— **改了没提交,那这一轮的代码谁也复现不了。**
    """
    import subprocess
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE,
                           capture_output=True, text=True, timeout=5).stdout.strip()
        d = subprocess.run(["git", "status", "--porcelain"], cwd=HERE,
                           capture_output=True, text=True, timeout=5).stdout.strip()
        return (h or "?") + ("+dirty" if d else "")
    except Exception:
        return "?"


def 模型():
    p = 供应商()
    if p == "deepseek":
        return os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    return os.environ.get("ANTHROPIC_MODEL", "claude(CLI 登录态)")


def dump(path, recs):
    """把一轮结果写进 jsonl,**每条都盖上是谁跑的**。

    盖在每一条上而不是文件头:文件头会被下一次覆盖写掉,
    而**部分覆盖**(跑了一半停掉)的时候,文件头说的和内容里的就对不上了 ——
    这一天正好就是跑到一半被停的。
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    p, m, c = 供应商(), 模型(), 代码()
    with open(path, "w", encoding="utf-8") as fh:
        for r in recs:
            r = dict(r); r.update(供应商=p, 模型=m, 跑于=now)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


# ── 一张评测分数表**能读出什么、读不出什么** ────────────────────────────
#
# 上面那几个函数管的是「**这条结果是谁跑的**」。这一段管的是接下来那一步:
# **拿到两个数,能不能说「这一版比上一版好」。**
#
# 两条口径原来分散在两处 —— 一条在 `tools/eval_compare.py`、一条在
# `agent/gen_compare.py`,各自管各自那张表。**散着的口径必然漂**,
# 而这两条恰好是同一件事的两面:
#
#     同一条件下也会晃   同一提交、同一模型跑两次,分数就不一样
#     条件变了看不出来   换了模型 / 换了提交,两张表并排看不出差别
#
# ⚠️ **合起来才完整**:一张分数表既可能被**噪音**骗,也可能被**换了的条件**骗,
# **而两种情况下它长得都一样** —— 都是「27/31」这样一个数。


# ① 同一条件下的波动 —— 实测,不是估的
同版波动_下限 = 2
同版波动_实测 = (
    "2026-09-16 实测:**同一提交、同一家模型**跑两次 `ops_eval`,"
    "**29/31 → 27/31,而且红的两批完全不重叠**"
    "(第二轮红的 W03/W04/D4 一个字都没碰过)。"
    "这条路径(SDK → Claude Code CLI → 模型)**不暴露 temperature / top_p / seed**"
    "(见 `agentsite/sdk.py`),**波动消不掉,只能承认**。")
同版波动_怎么用 = (
    "⚠️ **这个 2 不是阈值,是只跑两次量到的下限** —— 真实波动只会更大。"
    "**不许拿它当「2 分以内就没问题」的通行证**;它的用途只有一句:"
    "**2 分以内的差别,不许当成结论说出去。**"
    "要把它变成一个真数,得同一版连跑若干次 —— 那是还没做的事。")

# ② 条件变没变 —— 三样任意一样变了,两张表就不可比
可比的三样 = {
    "供应商": "哪家模型跑的。DeepSeek 那一轮六套的数**直接覆盖过 Claude 的基线**,"
              "而两者在文件里长得一模一样",
    "模型": "**同一家也分型号。** 2026-09-07 那张三代基线表是 **haiku-4.5** 跑的,"
            "而走 Claude 时不设 `ANTHROPIC_MODEL` 默认是 **opus-5** —— "
            "**成本能差一个量级,而表格上看不出来**:它只写「判对 6/6、$0.0129」,"
            "不写那是谁算出来的",
    "代码": "提交号。**同一天 ≠ 同一份代码** —— 中间只要动过工具、规矩、判据,"
            "差出来的就是那些改动,不是模型的差别。**一次动了多维就归不了因**",
}


def 能不能当结论(a, b, 分差=None):
    """两轮结果能不能并排读。a / b 是两份记录的来路 dict(供应商 / 模型 / 代码)。

    返回 (能不能, 为什么)。**「不能」的时候照样要出表** ——
    不出表的话人会去手抄,**手抄比不可比更糟**。
    """
    变 = [k for k in ("供应商", "模型", "代码")
          if (a or {}).get(k) != (b or {}).get(k)]
    if 变:
        return False, ("**不可比**:" + "、".join(
            f"{k} 不同({(a or {}).get(k)} vs {(b or {}).get(k)})—— {可比的三样[k]}"
            for k in 变))
    if 分差 is not None and abs(分差) <= 同版波动_下限:
        return False, (f"条件一样,但**差 {abs(分差)} 分读不出东西** —— "
                       f"{同版波动_实测} {同版波动_怎么用}")
    return True, ("条件一样(同供应商 / 同模型 / 同提交)"
                  + (f",差 {abs(分差)} 分**超过了实测波动下限 "
                     f"{同版波动_下限}**" if 分差 is not None else "")
                  + " —— 可以当结论读,但仍要带上「题数小、各跑一遍」这两条限定。")
