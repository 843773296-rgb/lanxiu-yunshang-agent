#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""世界时钟 —— **演示世界的「现在」只有这一份来源**。

## 为什么要单独一个文件

2026-09-26 踩到:`backend/booking.py` 的 `_now()` 是 `datetime.datetime.now()` ——
**机器时钟**。于是它写出来的 `schedule.assigned_at` 落在机器的今天,
而演示世界当时停在前一天。然后每日平移把这条记录**跟着往后挪了一天**,
它就落到了世界的未来。

> **这个 bug 不会自愈:平移每跑一次,它就往未来多推一天。**

C4(「已经发生的事,时间不能在未来」)抓到了症状,而根因是
「世界的今天」在这个仓库里有两处表示:`seed.TODAY`(库里读的)和
各个文件里的 `datetime.now()`。**一份数据两处表示,这是第八次。**

## 两个口径,别混

    今天()   世界的日期(从 world_meta 读,不从时钟读)
    当下()   世界的日期 + **机器的时刻** —— 世界按天平移,一天之内的钟点是真的

为什么当下() 用机器的时刻:世界平移的粒度是天,时刻没有被平移过。
硬造一个固定时刻(比如都当成 12:00)会让同一天内的先后顺序全错,
而那种错在单条记录上看完全正常。

⚠️ **不是所有 `datetime.now()` 都该换成这个。** 会话过期、审计时间戳、
监控指标记的是**真实世界**发生的事,它们本来就该用机器时钟。
该换的是**写演示业务数据**的地方 —— 判据是:这一列会不会被
`tools/shift_world.py` 平移。会被平移的,就必须用世界时钟写。
"""
import datetime as _dt
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)


def 今天():
    """世界的日期(date)。**从库里读,不从时钟读。**"""
    import seed
    v = seed.TODAY
    return v if isinstance(v, _dt.date) else _dt.date.fromisoformat(str(v))


def 当下():
    """世界的日期 + 机器的时刻(datetime)。"""
    now = _dt.datetime.now()
    return _dt.datetime.combine(今天(), now.time())


def 差几天(d):
    """某一天距离「世界的今天」几天(正数=过去)。"""
    d = d if isinstance(d, _dt.date) else _dt.date.fromisoformat(str(d)[:10])
    return (今天() - d).days


# ── 「已经发生的事」的时间列 —— **唯一来源** ─────────────────────────
#
# 这份清单原来只长在 `backend/spec_check.py` 的 C4 里(叫 `_FUTURE`)。
# 2026-09-26 平移要用同一份知识(平移前得知道「有没有记录已经在未来」),
# 于是挪到这里:**一份数据,两个读者**。
#
# 抄一份给平移的话,两份会各自漂 —— 而漂的表现是「C4 红着但平移放行」
# 或者反过来,两种都看不出是清单不同步。
#
# ⚠️ 只列**已经发生**的事实(互动过了、量过了、付过了、派过了)。
# **计划类字段本来就该在未来**(预约开始、任务截止、承诺交期),不在这份清单里 ——
# 把它们混进来的后果是每天的平移都会被自己拦住。
已发生的时间列 = [
    ("customer", "last_interact", "最近互动"),
    ("measure_rec", "measured_at", "量体时间"),
    ("ordr", "paid_at", "付款时间"),
    ("ordr", "finished_at", "订单完成"),
    ("schedule", "assigned_at", "派单时间"),
    ("followup", "ts", "跟进时间"),
    ("fitting", "ts", "白坯试衣时间"),
    ("fitting", "signed_at", "试衣签字时间"),
    ("ordr", "cut_at", "开裁时间"),
]


def 未来记录(conn, 基准=None, 每列上限=3):
    """哪些「已经发生的事」落在了世界的未来。返回清单(空=干净)。

    ⚠️ **查不了的列要报出来,不许 `pass`** —— 被吞掉的异常和「查过了没问题」
    在输出上完全一样。spec_check 的 C4 为这一条栽过一次
    (`followup.created` 这一列根本不存在,于是那一项从加进来那天起没查过一次)。

    ⚠️ 但**「这张表不存在」和「这一列写错了」是两回事**,要分开:
    前者是合成夹具/还没建全的库(正常),后者是清单和库对不上(该红)。
    第一版把两者混成一条,结果 shift_world 的自测(夹具只有两张表)
    被自己的闸拦住了 —— **判据把「没这张表」当成了「有未来记录」**。
    分开之后见 `分类()`。
    """
    return 分类(conn, 基准, 每列上限)["未来行"]


def 分类(conn, 基准=None, 每列上限=3):
    """返回 {未来行, 缺表, 查不了} —— 三种情况**分开报**。

      未来行  真的有「已经发生的事」落在未来 → **该拦**
      缺表    这张表不存在 → 合成夹具或还没建全的库,**不该拦**,但要说出来
      查不了  表在、查询却失败(列名写错、类型不对)→ **该拦**:
              清单和库对不上,而它的表现是「这一项从来没查过」
    """
    基准 = str(基准 or 今天())[:10]
    未来行, 缺表, 查不了 = [], [], []
    for t, col, cn in 已发生的时间列:
        try:
            for r in conn.execute(
                    f"SELECT id,{col} FROM {t} WHERE {col} IS NOT NULL "
                    f"AND substr({col},1,10) > ? LIMIT {int(每列上限)}", (基准,)):
                未来行.append(dict(表=f"{t}.{col}", 说明=cn, id=r[0], 时间=r[1]))
        except Exception as e:
            msg = str(e)
            if "no such table" in msg:
                缺表.append(dict(表=f"{t}.{col}", 说明=cn, 原因=msg))
            else:
                查不了.append(dict(表=f"{t}.{col}", 说明=cn, 原因=f"{type(e).__name__}: {msg}"))
    return dict(未来行=未来行, 缺表=缺表, 查不了=查不了)
