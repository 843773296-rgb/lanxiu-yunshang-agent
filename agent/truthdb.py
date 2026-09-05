#!/usr/bin/env python3
"""评测答案表的读取口 —— **只给评测用,不在 agent 那一侧**。

## 为什么单独有这个文件

`backend/api.py` 开篇写着一句铁律:「truth 表绝不通过任何接口暴露,
评测比对在 agent 之外做。」但在这次边界审计之前,那句话只是**约定** ——
评测代码图省事,一直借着工具层的 `api._rows` 去读答案表。

工具层加上运行时拦截之后,这条借道立刻断了。**这是对的**:
断掉之后,「工具层」和「评测层」才真的分开 ——
现在就算有人给工具层加一个新工具,他也不可能顺手把答案表带出去,
因为那条路根本不通。

**锁的价值不只是挡住攻击者,还在于逼出本该有的分层。**
"""
import os, sqlite3

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "backend", "lanxiu.db")


def rows(sql="SELECT * FROM truth", *a):
    """评测侧的只读连接。**不经 api._rows。**"""
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, a)]
    finally:
        c.close()


def by_case():
    return {r["case_id"]: r for r in rows()}
