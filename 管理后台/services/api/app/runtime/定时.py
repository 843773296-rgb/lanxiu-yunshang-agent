#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时触发的时间口径(2026-10-26,方案 §8.5;用户拍「照你的建议走」—— 方案开头那张表第 6—9 件)。

纯逻辑:不碰库、不取当前时间(「现在」由调用方给)—— 同一条规则在不同时刻算出不同结果,
真值对账就没法复现(CLAUDE.md 第 9 节 ①「口径模块不许自己取当前日期」)。

## 用户拍的口径

| 周期 | 什么时候跑(北京时间,默认 8:00) | 统计哪一段 |
| --- | --- | --- |
| 日 | 每天 | 前一天 0:00—24:00 |
| 周 | 每周一 | 上一个自然周(周一至周日)—— **不是「过去 7 天」** |
| 月 | 每月 1 号 | 上一个自然月 |

- 「执行日期」和「统计哪一段」分开记:周一早上跑的周报,统计的是上周一到上周日。
- **同一条流程的同一个统计区间只发起一次**:期键 = 流程 + 周期 + 统计起始日,当幂等键用 —— 重启、重发都不多跑。
- 机器关机错过了 → **只补最近一期**,更早的列出来让人决定(一口气补十几期会一下子花很多钱)。
- 到点时上一次还没跑完 → 这次跳过(这一条要查库,不在这里判;这里只算「该不该是这一期」)。
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

周期们 = {"日": "每天", "周": "每周一", "月": "每月 1 号"}
默认时刻 = "08:00"
默认时区 = "Asia/Shanghai"


class 规则不对(ValueError):
    pass


def 校验规则(规则):
    """→ 规范化后的规则 dict;不合法抛 规则不对(带人话)。"""
    r = dict(规则 or {})
    if r.get("周期") not in 周期们:
        raise 规则不对("周期只能是 日 / 周 / 月")
    时刻 = str(r.get("时刻") or 默认时刻)
    try:
        h, m = (int(x) for x in 时刻.split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except (ValueError, AssertionError):
        raise 规则不对("时刻要写成 时:分,比如 08:00")
    时区 = str(r.get("时区") or 默认时区)
    try:
        ZoneInfo(时区)
    except Exception:
        raise 规则不对(f"认不出的时区 {时区}")
    return {"周期": r["周期"], "时刻": f"{h:02d}:{m:02d}", "时区": 时区}


def _本地(规则, 时刻utc):
    return 时刻utc.astimezone(ZoneInfo(规则["时区"]))


def 执行时刻(规则, 某天):
    """某一天(本地日期)那次执行的时刻(带时区)—— 不管那天该不该跑。"""
    h, m = (int(x) for x in 规则["时刻"].split(":"))
    return datetime.combine(某天, time(h, m), tzinfo=ZoneInfo(规则["时区"]))


def 是执行日(规则, 某天):
    return {"日": True, "周": 某天.weekday() == 0, "月": 某天.day == 1}[规则["周期"]]


def 统计区间(规则, 执行日):
    """那一天执行的那次,统计的是哪一段 → (起, 止),都是本地日期,**两头都含**。"""
    p = 规则["周期"]
    if p == "日":
        d = 执行日 - timedelta(days=1)
        return d, d
    if p == "周":
        本周一 = 执行日 - timedelta(days=执行日.weekday())
        return 本周一 - timedelta(days=7), 本周一 - timedelta(days=1)
    上月末 = 执行日.replace(day=1) - timedelta(days=1)
    return 上月末.replace(day=1), 上月末


def 期键(流程id, 规则, 起):
    """同一条流程的同一个统计区间只发起一次 —— 拿它当幂等键。"""
    return f"定时:{流程id}:{规则['周期']}:{起.isoformat()}"


def 下次执行(规则, 现在):
    """`现在` 之后(不含)最近的一次执行 → (执行时刻, 统计起, 统计止)。"""
    天 = _本地(规则, 现在).date()
    for i in range(0, 40):
        d = 天 + timedelta(days=i)
        if 是执行日(规则, d) and 执行时刻(规则, d) > 现在:
            起, 止 = 统计区间(规则, d)
            return 执行时刻(规则, d), 起, 止
    raise RuntimeError("40 天里找不到下一次执行 —— 规则有问题")


def 最近该跑的(规则, 现在):
    """`现在` 之前(含)最近该跑的那一次 → (执行时刻, 统计起, 统计止);一次都还没到就 None。"""
    天 = _本地(规则, 现在).date()
    for i in range(0, 40):
        d = 天 - timedelta(days=i)
        if 是执行日(规则, d) and 执行时刻(规则, d) <= 现在:
            起, 止 = 统计区间(规则, d)
            return 执行时刻(规则, d), 起, 止
    return None


def 该发起吗(规则, 现在, 上次统计起=None, 设定于=None):
    """到点了吗、该发起哪一期、有没有错过的更早的期。

    `上次统计起`:这条流程上一次**定时发起过**的那一期的统计起始日(没有就 None)。
    `设定于`:定时是什么时候设的 —— 设定之前的期不算「错过」(不然一设好就要补一堆)。
    → {"发起": (执行时刻, 起, 止) 或 None, "错过": [(起, 止), …](不自动补,列出来让人决定)}
    """
    最近 = 最近该跑的(规则, 现在)
    if not 最近:
        return {"发起": None, "错过": []}
    执行, 起, 止 = 最近
    if 设定于 and 执行 < 设定于:
        return {"发起": None, "错过": []}
    if 上次统计起 is not None and 上次统计起 >= 起:
        return {"发起": None, "错过": []}               # 最近这一期已经发起过
    # 从「上次之后」到「最近这一期之前」之间漏掉的期 —— 只列,不补(用户拍:只补最近一期)
    错过 = []
    d = 执行.date() - timedelta(days=1)
    下限 = 设定于.astimezone(ZoneInfo(规则["时区"])).date() if 设定于 else d - timedelta(days=400)
    while d >= 下限 and len(错过) < 60:
        if 是执行日(规则, d) and (not 设定于 or 执行时刻(规则, d) >= 设定于):
            o, z = 统计区间(规则, d)
            if 上次统计起 is not None and o <= 上次统计起:
                break
            错过.append((o, z))
        d -= timedelta(days=1)
    return {"发起": 最近, "错过": 错过}
