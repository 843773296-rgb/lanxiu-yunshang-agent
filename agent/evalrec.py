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
    p, m = 供应商(), 模型()
    with open(path, "w", encoding="utf-8") as fh:
        for r in recs:
            r = dict(r); r.update(供应商=p, 模型=m, 跑于=now)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path
