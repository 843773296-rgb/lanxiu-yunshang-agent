#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日平移那个定时任务**还在不在跑**。

    python3 tools/cron_health_check.py

## 为什么要单独一条

`shift_world.py --check` 判的是「**数据**落后了没有」,而且要落后 **14 天**才判红。
也就是说定时任务挂了之后,**两周内没有任何信号** ——
而这两周里,每个人都以为世界在跟着真实日期走。

> **一个静默失败的定时任务,比没有定时任务更糟。**
> 没有的时候人知道要手动跑;装了之后人以为它在跑。

所以这条判的是**任务本身**,不是数据。

## ⚠️ 四档,不是两档

    plist 不在 + 没标记          → **不算红**:这台机器没装(CI、别人的机器)
    plist 在 + 没标记 + 刚装上    → **不算红**:装了还没到点
    plist 在 + 没标记 + 装了很久  → **红**:装了却从来没跑过
    「尝试过」也旧了              → **红**:任务在跑过,现在不跑了
    「尝试过」新、「成功过」旧     → **红**:任务在跑,但每次都失败

⚠️ 中间那两档是装完当场发现要分的:装上之后到第一次 05:10 之间有个窗口,
而这个窗口里「装了还没到点」和「根本没装」**在标记上长得一模一样** ——
第一版就把刚装好的任务报成了「这台机器没装」。
分开靠的是 plist 的 mtime(装了多久),那是现成的、不用新存一个字段。

第一档为什么不能算红:**CI 和别人的机器上本来就没有这个任务** ——
把「没装」判成红,这条检查会在每一次 CI 上红,
而**一条永远红的检查,和一条永远绿的检查一样没用**(人会学会忽略它)。

后两档为什么要分开:它们下一步完全不同 ——
一个去修任务(launchd 没装上 / 被卸了 / 机器一直关机),
一个去看日志(库被锁、上一次被中断留了标记)。
只记一个时间戳的话,这两种在那个数上长得一模一样。
"""
import os
import sys
from datetime import datetime

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
态 = os.path.join(根, ".feynman")
尝试 = os.path.join(态, "world-shift-tried")
成功 = os.path.join(态, "world-shift-ok")
日志 = os.path.join(态, "daily-shift.log")
# 「装了多久」用 plist 的 mtime 答 —— 装上之后到第一次跑之间有个窗口,
# 而这个窗口里「装了还没到点」和「根本没装」在标记上长得一模一样。
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.lanxiu.worldshift.plist")

# 每天跑一次的任务,容两天 —— 一天是「今天还没到点」,两天才说明真不对。
# ⚠️ 这个数是**拍脑袋的**,写明了:没有数据支撑,只是「一天太紧、三天太松」。
容忍天数 = 2

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


# ── 咬合记录 ────────────────────────────────────────────────────────
# 左边「改坏什么」,右边「预期红的那一条」。
# ⚠️ **手工验过不算** —— 我装完当场把三档都试了一遍,而那件事只存在于我的记忆里,
# 而记忆不进仓库。`tools/bite_check.py` 钉的正是「有没有登记」,不是「我记不记得做过」。
咬合 = [
    ("把 .feynman/world-shift-ok 的时间戳改成 5 天前(装着、在跑、但没成功过)",
     "任务在跑,但没有成功过"),
    ("把 .feynman/world-shift-tried 也改成 5 天前(任务不跑了)",
     "任务装了却没在跑"),
    ("删掉 ~/Library/LaunchAgents/com.lanxiu.worldshift.plist 的同时留下旧标记",
     "任务装了却没在跑"),
]


def 读(路):
    try:
        return datetime.fromisoformat(open(路, encoding="utf-8").read().strip())
    except Exception:
        return None


def main():
    print("\n\033[1m▸ 每日平移的定时任务还在不在跑\033[0m")
    t, o = 读(尝试), 读(成功)

    装了吗 = os.path.exists(PLIST)
    if t is None and o is None:
        if not 装了吗:
            # 第一档:**不算红** —— CI 和别人的机器上本来就没有。
            print(f"  {Y}⚠ 这台机器没装每日平移的定时任务{D}"
                  f"(没有 plist,也没有 {os.path.basename(尝试)})")
            print(f"     装法:`bash tools/install_world_cron.sh`;"
                  f"CI 和别人的机器上没有是正常的,**所以这不算错**")
            print(f"\n  {G}✅ 跳过(没装){D}")
            return 0
        装了几天 = (datetime.now()
                - datetime.fromtimestamp(os.path.getmtime(PLIST))).days
        if 装了几天 <= 容忍天数:
            # 第二档:**不算红** —— 装完到第一次 05:10 之间的窗口。
            print(f"  {Y}⚠ 装了({装了几天} 天前),但**还没跑过一次**{D} —— "
                  f"到点(05:10)才会跑;想立刻验一次:`bash tools/daily_shift.sh`")
            print(f"\n  {G}✅ 跳过(刚装上,还没到点){D}")
            return 0
        # 第三档:**红** —— 装了这么久一次都没跑过,那就是没在跑。
        print(f"  {R}❌ plist 装了 {装了几天} 天,**一次都没跑过**{D} —— "
              f"看 `launchctl list | grep lanxiu`;"
              f"机器一直关机、或者 plist 有错都会这样")
        print(f"\n❌ 1 条不对")
        return 1

    坏 = []
    现在 = datetime.now()
    差尝试 = (现在 - t).days if t else None
    差成功 = (现在 - o).days if o else None

    if 差尝试 is None or 差尝试 > 容忍天数:
        坏.append(f"**任务装了却没在跑** —— 上一次尝试是 "
                  f"{t.isoformat(' ', 'minutes') if t else '(从来没有)'}"
                  f"{f',{差尝试} 天前' if 差尝试 is not None else ''}。"
                  f"看 `launchctl list | grep lanxiu`;机器一直关机也会这样")
    else:
        print(f"  {G}✅ 任务在跑{D}  上一次尝试:{t.isoformat(' ', 'minutes')}")

    if 差成功 is None or 差成功 > 容忍天数:
        坏.append(f"**任务在跑,但没有成功过** —— 上一次成功是 "
                  f"{o.isoformat(' ', 'minutes') if o else '(从来没有)'}"
                  f"{f',{差成功} 天前' if 差成功 is not None else ''}。"
                  f"看日志:{os.path.relpath(日志, 根)}")
    else:
        print(f"  {G}✅ 最近成功过{D}  上一次成功:{o.isoformat(' ', 'minutes')}")

    for x in 坏:
        print(f"  {R}❌ {x}{D}")
    print(f"\n{'✅ 定时任务健康' if not 坏 else f'❌ {len(坏)} 条不对'}")
    return 1 if 坏 else 0


if __name__ == "__main__":
    sys.exit(main())
