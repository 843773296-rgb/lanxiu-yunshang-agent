#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞品与行业资料的口径 —— **每条都有日期,过期了自己说出来。**

`16-竞品与行业.md` 收的是别人家的价位、行业的规模和惯例。这类数据**会过期,而过期不报错**:
一条两年前的「汉服客单价 300 元」,和一条上个月的,在文档里长得一模一样。
所以每条必须带**抓取日期**,超过 `过期月数` 的,读它的工具要**当场说出来**。

口径模块不取当前日期 —— 「今天」由调用方传进来(`api.kb_read` 传世界今天)。
"""
import datetime as dt, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(HERE, "16-竞品与行业.md")

过期月数 = 6          # 业务 2026-09-29 定:超过 6 个月没更新的条目要自己说出来
必填 = ("要点", "来源类型", "发布日期", "抓取日期", "出处")


def 条目(text=None):
    """md 里每个 `### 标题` 一条 → [{标题, 要点, 来源类型, 发布日期, 抓取日期, 出处}]。"""
    t = text if text is not None else open(MD, encoding="utf-8").read()
    out, cur = [], None
    for l in t.split("\n"):
        if l.startswith("### "):
            cur = {"标题": l[4:].strip()}
            out.append(cur)
        elif l.startswith("## "):
            cur = None
        elif cur is not None:
            m = re.match(r"^-\s*(?:\*\*)?(要点|来源类型|发布日期|抓取日期|出处)(?:\*\*)?\s*[::]\s*(.+)$", l.strip())
            if m:
                cur[m.group(1)] = m.group(2).strip()
    return out


def _加月(d, n):
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    import calendar
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def 过期了吗(抓取日期, 今天):
    """抓取日期 + 过期月数 < 今天 → True;日期认不出 → None(**认不出不等于没过期**)。"""
    try:
        d = dt.date.fromisoformat(str(抓取日期).strip()[:10])
    except ValueError:
        return None
    return _加月(d, 过期月数) < 今天


def 过期提示(今天, text=None):
    """读这一篇时要一起给出去的那句话;没有过期也没有认不出日期的,返回 None。"""
    过, 认不出 = [], []
    for e in 条目(text):
        v = 过期了吗(e.get("抓取日期", ""), 今天)
        (认不出 if v is None else 过 if v else []).append(e["标题"])
    if not 过 and not 认不出:
        return None
    话 = []
    if 过:
        话.append(f"**{len(过)} 条超过 {过期月数} 个月没更新**(业务 09-29 定的线),"
                  f"对客户引用前要重新核:{'、'.join(过[:5])}")
    if 认不出:
        话.append(f"{len(认不出)} 条抓取日期认不出 —— **认不出不等于没过期**:{'、'.join(认不出[:5])}")
    return ";".join(话)
