# -*- coding: utf-8 -*-
"""流失预警取数 —— **这里一条判定都没有**,判定在 `knowledge/churn.py`。

和 `revive.py` 同一个分层:那边是「该不该联系」,这边是「她在不在往下走」。
⚠️ 两份名单**不是一回事**,合并会让「闲置久」重新变成联系的理由
(`knowledge/reactivate.py` 开头花一整段在拦这件事)。

## ⚠️ 文件名为什么不叫 churn.py

和 `revive.py` 避开 `reactivate` 同一个理由:这个文件要 `import churn`,
**它和口径模块同名的话会先找到它自己** ——
> 「导入成功了」和「导入对了」长得一模一样。

## ⚠️ 它只读 `lifecycle_history`,不自己重算档位

档位历史是**只追加的事件日志**,每条带着当天的四个判定依据。
拿当前 `customer` 表现算的话,算出来的只有「她今天是哪一档」——
**而这个模块整件事就是「她在不在动」,一个时间点答不了。**
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
import churn as _口径

# 这几个全部**转发,不抄** —— 抄一份的后果是改一处漏一处,
# 而两份不一致时名单照样跑得出来,看起来完全正常。
活跃度轴 = _口径.活跃度轴
价值标签 = _口径.价值标签
严重 = _口径.严重
下一步 = _口径.下一步

# 口径吃的键**逐字就是表的列名** —— 这里只负责把它们原样端过去。
# 2026-10-05 栽过:读成了另一个键名,静静返回 None,
# 23216 条历史的档位全成了字符串 "None",而所有检查都是绿的。
列 = ("id", "customer_id", "as_of", "lifecycle", "idle_days",
      "orders_12m", "amount_12m", "quarters_12m")


def _只读():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def 查历史(customer_ids=None, con=None):
    """取档位历史,按客户归好。**不判定、不排序、不过滤。**

    `customer_ids` 给 None 就是全部。返回 {客户号: [行, ...]}。
    """
    自带 = con is None
    con = con or _只读()
    try:
        sql = f"SELECT {','.join(列)} FROM lifecycle_history"
        args = []
        if customer_ids is not None:
            ids = list(customer_ids)
            if not ids:
                return {}
            sql += f" WHERE customer_id IN ({','.join('?' * len(ids))})"
            args = ids
        sql += " ORDER BY customer_id, as_of, id"
        出 = {}
        for r in con.execute(sql, args):
            出.setdefault(r["customer_id"], []).append(dict(r))
        return 出
    finally:
        if 自带:
            con.close()


def 一批人的判断(customer_ids=None, con=None):
    """返回 {客户号: `churn.判()` 的结果}。

    ⚠️ **查不到历史的客户不在返回值里** —— 而「查不到」和「没在流失」
    是两件事(`churn.判()` 的 NO_HISTORY 说的就是这个)。
    调用方要自己说清这个范围里有几个人**根本没有历史**,
    否则「预警 0 个」会被读成「没人在流失」。
    """
    return {cid: _口径.判(hs) for cid, hs in 查历史(customer_ids, con).items()}


def 一个人的判断(customer_id, con=None):
    hs = 查历史([customer_id], con).get(customer_id)
    return _口径.判(hs or [])
