#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时触发的时间口径(2026-10-26,方案 §8.5;用户拍「照你的建议走」—— 方案开头那张表第 6—9 件)。

纯逻辑:不碰库、不取当前时间(「现在」由调用方给)—— 同一条规则在不同时刻算出不同结果,
真值对账就没法复现(CLAUDE.md 第 9 节 ①「口径模块不许自己取当前日期」)。

## 用户拍的口径

| 周期 | 什么时候跑(北京时间,默认 8:00) | 统计哪一段 |
| --- | --- | --- |
| 日 | 每天 | 前一天 0:00—24:00 |
| 周 | 每周几(默认周一;可多选) | **上一次该跑到这一次该跑之间**:只选周一时 = 上一个自然周(周一至周日)—— **不是「过去 7 天」** |
| 月 | 每月几号(默认 1 号;可多选,可选「末」= 最后一天) | 同上:只选 1 号时 = 上一个自然月 |
| 时 | 每小时(分钟照「时刻」里的分钟) | 上一个整点小时 |

- 「执行日期」和「统计哪一段」分开记:周一早上跑的周报,统计的是上周一到上周日。
- **统计区间 = 上一次该跑的时刻 → 这一次该跑的时刻**(11-16 用户拍,台账第七十三条;数据管道调度的通用口径):
  日 / 周 / 月算到**日**(两头都含,止于执行日前一天),时算到**分**(起 = 上一个整点那次,止 = 这次前一分钟)。
  对原来的三种(每天 / 每周一 / 每月 1 号)算出来的区间**和 10-26 那版逐字一样** —— 对照用例钉着。
- 「每月 31 号」碰上 30 天的月、29 / 30 / 31 碰上 2 月:**落到那个月最后一天跑**,不跳过(第七十四条;cron 的惯例是跳过)。
- 「每小时」先不限营业时间,全天每小时(第七十五条)。
- **同一条流程的同一个统计区间只发起一次**:期键 = 流程 + 周期 + 统计起始,当幂等键用 —— 重启、重发都不多跑。
- 机器关机错过了 → **只补最近一期**,更早的列出来让人决定(一口气补十几期会一下子花很多钱)。
- 到点时上一次还没跑完 → 这次跳过(这一条要查库,不在这里判;这里只算「该不该是这一期」)。
"""
import calendar
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

周期们 = {"日": "每天", "周": "每周几", "月": "每月几号", "时": "每小时"}
周几名 = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
月末 = "末"
默认时刻 = "08:00"
默认时区 = "Asia/Shanghai"


class 规则不对(ValueError):
    pass


def _整数们(值, 名, 下, 上, 另许=()):
    """「周几」「几号」这类列表:整数(或字符串形式的整数)在 [下, 上] 内;另许 里的字面值(如「末」)也认。→ 去重排好序。"""
    if 值 is None:
        return None
    if not isinstance(值, (list, tuple)):
        值 = [值]
    出 = []
    for v in 值:
        if isinstance(v, str) and v.strip() in 另许:
            出.append(v.strip()); continue
        try:
            n = int(str(v).strip())
        except ValueError:
            raise 规则不对(f"{名}里认不出「{v}」")
        if not 下 <= n <= 上:
            raise 规则不对(f"{名}只能在 {下} 到 {上} 之间" + (f",或写「{'」「'.join(另许)}」" if 另许 else ""))
        出.append(n)
    if not 出:
        raise 规则不对(f"{名}至少选一个")
    数 = sorted({x for x in 出 if isinstance(x, int)})
    return 数 + [x for x in 另许 if x in 出]


def 校验规则(规则):
    """→ 规范化后的规则 dict;不合法抛 规则不对(带人话)。
    周 → 带「周几」(0 = 周一 … 6 = 周日,默认 [0]);月 → 带「几号」(1–31 或「末」,默认 [1]);日 / 时不带。"""
    r = dict(规则 or {})
    if r.get("周期") not in 周期们:
        raise 规则不对("周期只能是 日 / 周 / 月 / 时")
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
    出 = {"周期": r["周期"], "时刻": f"{h:02d}:{m:02d}", "时区": 时区}
    if r["周期"] == "周":
        出["周几"] = _整数们(r.get("周几"), "周几", 0, 6) or [0]
    if r["周期"] == "月":
        出["几号"] = _整数们(r.get("几号"), "几号", 1, 31, 另许=(月末,)) or [1]
    return 出


def 说法(规则):
    """给人看的一句:「每周三、周五 08:00」「每月 15 号、最后一天 08:00」「每小时的第 05 分」「每天 08:00」。"""
    p, t = 规则["周期"], 规则["时刻"]
    if p == "日":
        return f"每天 {t}"
    if p == "时":
        return f"每小时的第 {t.split(':')[1]} 分"
    if p == "周":
        return "每" + "、".join(周几名[d] for d in 规则.get("周几") or [0]) + f" {t}"
    号 = ["最后一天" if d == 月末 else f"{d} 号" for d in 规则.get("几号") or [1]]
    return "每月 " + "、".join(号) + f" {t}"


def _本地(规则, 时刻utc):
    return 时刻utc.astimezone(ZoneInfo(规则["时区"]))


def 执行时刻们(规则, 某天):
    """某一天(本地日期)里**所有**该执行的时刻(带时区)—— 不管那天该不该跑。日 / 周 / 月各一次;时 24 次。"""
    h, m = (int(x) for x in 规则["时刻"].split(":"))
    tz = ZoneInfo(规则["时区"])
    if 规则["周期"] == "时":
        return [datetime.combine(某天, time(hh, m), tzinfo=tz) for hh in range(24)]
    return [datetime.combine(某天, time(h, m), tzinfo=tz)]


def 执行时刻(规则, 某天):
    """某一天那次执行的时刻(带时区);每小时的规则给的是那天第一次(00:MM)。"""
    return 执行时刻们(规则, 某天)[0]


def 是执行日(规则, 某天):
    p = 规则["周期"]
    if p in ("日", "时"):
        return True
    if p == "周":
        return 某天.weekday() in (规则.get("周几") or [0])
    几号 = 规则.get("几号") or [1]
    月天数 = calendar.monthrange(某天.year, 某天.month)[1]
    if 某天.day in 几号:
        return True
    # 「末」= 最后一天;选了 29 / 30 / 31 而这个月没有那天 → 落到最后一天跑,不跳过(第七十四条)
    return 某天.day == 月天数 and (月末 in 几号 or any(isinstance(n, int) and n > 月天数 for n in 几号))


def _上一次(规则, 这次):
    """`这次` 之前(不含)最近一次该执行的时刻。往回最多看 400 天(「每月 29 号」在平年二月前后最远隔 13 个月都用不着)。"""
    天 = 这次.date()
    for i in range(0, 400):
        d = 天 - timedelta(days=i)
        if not 是执行日(规则, d):
            continue
        们 = [t for t in 执行时刻们(规则, d) if t < 这次]
        if 们:
            return 们[-1]
    raise RuntimeError("400 天里找不到上一次执行 —— 规则有问题")


def 统计区间(规则, 执行):
    """那一次执行统计的是哪一段 → (起, 止)。
    `执行` 给执行日(date)或执行时刻(datetime,每小时的规则必须给时刻)。
    日 / 周 / 月:两头都是本地日期、**两头都含**(起 = 上一次该跑那天,止 = 这次前一天);
    时:两头都是带时区的时刻、两头都含(起 = 上一个整点那次,止 = 这次前一分钟)。"""
    if not isinstance(执行, datetime):
        if 规则["周期"] == "时":
            raise ValueError("每小时的规则要给执行时刻,不是执行日")
        执行 = 执行时刻(规则, 执行)
    上 = _上一次(规则, 执行)
    if 规则["周期"] == "时":
        return 上, 执行 - timedelta(minutes=1)
    return 上.date(), 执行.date() - timedelta(days=1)


def 期键(流程id, 规则, 起):
    """同一条流程的同一个统计区间只发起一次 —— 拿它当幂等键。"""
    return f"定时:{流程id}:{规则['周期']}:{起.isoformat()}"


def 下次执行(规则, 现在):
    """`现在` 之后(不含)最近的一次执行 → (执行时刻, 统计起, 统计止)。"""
    天 = _本地(规则, 现在).date()
    for i in range(0, 40):
        d = 天 + timedelta(days=i)
        if not 是执行日(规则, d):
            continue
        for t in 执行时刻们(规则, d):
            if t > 现在:
                起, 止 = 统计区间(规则, t)
                return t, 起, 止
    raise RuntimeError("40 天里找不到下一次执行 —— 规则有问题")


def 接下来几次(规则, 现在, n=5):
    """`现在` 之后的接下来 n 次执行 → [(执行时刻, 统计起, 统计止)](11-15,照 Dify 面板「接下来 5 次执行时间」)。
    一次一次往后推,每次都用 下次执行 —— 不另写一套日期算法(两套迟早对不上)。"""
    出, t = [], 现在
    for _ in range(max(0, int(n))):
        x = 下次执行(规则, t)
        出.append(x)
        t = x[0]
    return 出


def 最近该跑的(规则, 现在):
    """`现在` 之前(含)最近该跑的那一次 → (执行时刻, 统计起, 统计止);一次都还没到就 None。"""
    天 = _本地(规则, 现在).date()
    for i in range(0, 40):
        d = 天 - timedelta(days=i)
        if not 是执行日(规则, d):
            continue
        们 = [t for t in 执行时刻们(规则, d) if t <= 现在]
        if 们:
            起, 止 = 统计区间(规则, 们[-1])
            return 们[-1], 起, 止
    return None


def _同类(规则, 上次统计起):
    """库里的 last_period_start 是带时区的时刻(11-16 起;原来是日期)。按规则换成和「起」同一种类型再比:
    日 / 周 / 月比本地日期;时比时刻(存成日期的老值当那天 0 点)。"""
    if 上次统计起 is None:
        return None
    tz = ZoneInfo(规则["时区"])
    if 规则["周期"] == "时":
        if isinstance(上次统计起, datetime):
            return 上次统计起 if 上次统计起.tzinfo else 上次统计起.replace(tzinfo=tz)
        return datetime.combine(上次统计起, time(0, 0), tzinfo=tz)
    if isinstance(上次统计起, datetime):
        return (上次统计起.astimezone(tz) if 上次统计起.tzinfo else 上次统计起).date()
    return 上次统计起


def 该发起吗(规则, 现在, 上次统计起=None, 设定于=None):
    """到点了吗、该发起哪一期、有没有错过的更早的期。

    `上次统计起`:这条流程上一次**定时发起过**的那一期的统计起始(没有就 None)。
    `设定于`:定时是什么时候设的 —— 设定之前的期不算「错过」(不然一设好就要补一堆)。
    → {"发起": (执行时刻, 起, 止) 或 None, "错过": [(起, 止), …](不自动补,列出来让人决定)}
    """
    最近 = 最近该跑的(规则, 现在)
    if not 最近:
        return {"发起": None, "错过": []}
    执行, 起, 止 = 最近
    if 设定于 and 执行 < 设定于:
        return {"发起": None, "错过": []}
    上次统计起 = _同类(规则, 上次统计起)
    if 上次统计起 is not None and 上次统计起 >= 起:
        return {"发起": None, "错过": []}               # 最近这一期已经发起过
    # 从「上次之后」到「最近这一期之前」之间漏掉的期 —— 只列,不补(用户拍:只补最近一期)
    错过 = []
    t = 执行
    下限 = 设定于 if 设定于 else 执行 - timedelta(days=400)
    while len(错过) < 60:
        try:
            t = _上一次(规则, t)
        except RuntimeError:
            break
        if t < 下限:
            break
        o, z = 统计区间(规则, t)
        if 上次统计起 is not None and o <= 上次统计起:
            break
        错过.append((o, z))
    return {"发起": 最近, "错过": 错过}
