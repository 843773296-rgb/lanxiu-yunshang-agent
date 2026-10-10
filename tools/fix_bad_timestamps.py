#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修库里 **SQLite 的 `date()` 解析不出来** 的时间戳。

    python3 tools/fix_bad_timestamps.py          # 只看会改什么
    python3 tools/fix_bad_timestamps.py --做

## 为什么这件事要紧:它让一条**完全无关**的检查静默报 0

`backend/link_check.py` 判「有没有半年内入职的顾问」,门槛是

    date((select max(created) from ordr), '-180 day')

而 `max(ordr.created)` 一度是 **`2026-10-10 20:68`** —— 68 分钟。
**SQLite 的 `date()` 遇到解析不了的值返回 NULL**,于是 `hired_at >= NULL`
永不为真 → 报「0 人」。而库里明明有新人(工号 60000015,世界今天前 60 天)。

> 一句「这个库里没有新人样本」和一句「最后一张订单的时间戳是非法的」,
> **在那条检查的输出上长得一模一样** —— 而它说的是第一句。

**而且它是间歇的**:`max(ordr.created)` 随每日上新变,最大那行哪天恰好非法就红 ——
所以**同一份代码 8416e14 绿、4609198 红**,中间没人碰过入职日期。

## 两类坏值(2026-10-10 实测 330 行),源头都已经修掉

  ① **时/分数值越界** 34 行 —— `tools/daily_fresh.py` 的分钟十位能抽到 6,
     生成 60~69 分。污染了 `ordr` 的 created / updated / paid_at / shipped_at /
     finished_at 五列和 `stock_log.ts`。
  ② **单位数没补零** 296 行(全在 `edit_log.ts`)—— `backend/seed.py` 写
     `{9 + _k2}` 没补零,`_k2=0` 时写出 `9:16`。
     这一类**还有第二个毛病**:按字符串排序时 `9:16` 排在 `10:00` **后面**。

⚠️ `tools/shift_world.py` 的挪法**仍然保留原样式**(自测里验着「单位数小时的格式没被改写」)——
那条是对的:**挪法不该改写它看到的东西**。该改的是**写它的那两个口**,
和已经写坏的这 330 行。两件事别混。

## 怎么修:交给 `datetime` 算,不手写折算

`20:68` 不是「把 68 改成 59」,是 **20 点过 68 分 = 21:08**。
手写折算会在 `23:70` 这种值上把日期算错,而错一天在订单上完全看不出来。
所以一律 `date + timedelta(hours=…, minutes=…, seconds=…)`,进位交给库。
**认不出形状的一个都不碰**(`不猜`),逐条报出来。
"""
import os, re, sqlite3, sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend")]
DB = os.path.join(ROOT, "backend", "lanxiu.db")
for _i, _a in enumerate(sys.argv):
    if _a == "--db" and _i + 1 < len(sys.argv):
        DB = sys.argv[_i + 1]

import shift_world as SW      # noqa: E402  —— 整列日期列的清单从它现扫,不手抄

形 = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$")


def 修一个(v):
    """返回 (新值, 哪一类) 或 (None, 原因)。**认不出的不猜。**"""
    m = 形.match(str(v).strip())
    if not m:
        return None, "形状不认识"
    y, mo, d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    try:
        t = datetime(y, mo, d) + timedelta(hours=h, minutes=mi, seconds=se)
    except ValueError as e:
        return None, f"连日期都不合法({e})"
    带秒 = m.group(6) is not None
    新 = t.strftime("%Y-%m-%d %H:%M:%S" if 带秒 else "%Y-%m-%d %H:%M")
    类 = "时/分越界(进位)" if (h > 23 or mi > 59 or se > 59) else "补零"
    return 新, 类


def 扫(c):
    纯, _ = SW.扫列(c)
    出 = []
    for 名 in 纯:
        t, col = 名.split(".", 1)
        try:
            rows = c.execute(f'SELECT rowid, "{col}" FROM "{t}" '
                             f'WHERE "{col}" IS NOT NULL AND date("{col}") IS NULL').fetchall()
        except sqlite3.Error:
            continue
        for rid, v in rows:
            出.append((t, col, rid, v))
    return 出


def main():
    做 = "--做" in sys.argv
    c = sqlite3.connect(DB)
    坏 = 扫(c)
    print(f"扫了 {len(SW.扫列(c)[0])} 个整列日期列,找到 {len(坏)} 个 date() 解析不出来的值")
    if not 坏:
        print("\033[32m✅ 没有要修的\033[0m")
        c.close()
        return 0
    类计, 不碰, 改 = {}, [], []
    for t, col, rid, v in 坏:
        新, 类 = 修一个(v)
        if 新 is None:
            不碰.append(f"{t}.{col} rowid={rid}:{v} —— {类}")
            continue
        类计[类] = 类计.get(类, 0) + 1
        改.append((t, col, rid, v, 新))
    for k, n in sorted(类计.items()):
        例 = next(x for x in 改 if 修一个(x[3])[1] == k)
        print(f"  · {k}:{n} 个(例:{例[0]}.{例[1]} {例[3]} → {例[4]})")
    if 不碰:
        print(f"\033[31m❌ {len(不碰)} 个形状认不出来 —— **不猜**,逐条列出来:\033[0m")
        for x in 不碰[:10]:
            print(f"     {x}")
        c.close()
        return 1
    if not 做:
        print("\n(只看,没写。真要改加 --做)")
        c.close()
        return 0
    with c:
        for t, col, rid, 旧, 新 in 改:
            c.execute(f'UPDATE "{t}" SET "{col}"=? WHERE rowid=?', (新, rid))
    # ── 自己证明干了活 ──────────────────────────────────────────
    余 = 扫(c)
    c.close()
    print(f"  改了 {len(改)} 个值")
    if 余:
        print(f"\033[31m❌ 还剩 {len(余)} 个解析不出来 —— 改了但没改干净\033[0m")
        return 1
    print("\033[32m✅ 整列日期列里,SQLite 的 date() 现在全都解析得出来\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
