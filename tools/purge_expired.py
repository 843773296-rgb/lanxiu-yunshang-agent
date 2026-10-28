#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按保留期清理超期数据 —— **默认只报告,删要显式说 `--执行`**。

用户 2026-10-27 拍:**操作日志 3 年 / 附件 1 年**。
拍的时候查清了一件事:在那之前**没有任何保留期清理** ——
`account.purge_at` 是客户主动注销后的清除时间,和保留期是两回事。
所以客户注销会清,而日常的操作台账和现场照**永久留着**,没人选过那个默认。

## 两个必须先定的事,都定了

**① 按哪个时钟算。** 这个项目有演示世界时钟(每天平移)和真实时钟两套,
台账的 `ts` 记的是**演示世界时间**,所以保留期也按演示世界的今天算
(`world_meta.world_today`)。按真实时钟算的话,演示数据会整体超期或整体不超期 ——
> 一个「这条台账超过 3 年了」和一个「它的时间戳属于另一套时钟」,
> **在日期相减的结果上长得一模一样。**

**② 删是不可逆的,所以默认不删。** `--执行` 才真删,而且先打印要删多少、
最早哪一条。和「放宽守卫要用户执行」同一个道理:
**一个「清理跑过了」和一个「清理把不该删的删了」,在退出码 0 上长得一样。**

## ⚠️ 演示库里这件事验不出来

真库的 `op_log` **只有当天的数据**(每次重建都从头造),所以**永远不会有 3 年前的台账**。
也就是说这个脚本在演示库上跑,永远「没有东西要清」——
而那和「清理在工作」在输出上长得一样。
真正验它的是 `backend/retention_check.py`:**造一条超期数据当夹具**,
验清理真的删得掉。

## 附件那一半还做不了

研判队列的现场照附件**表还不存在**(库里只有 `schedule_file`,那是排班文件)——
「要现场照的类型只能走页面」那条本身还卡着。所以附件 1 年这一半等那张表出来再接。
"""
import argparse, os, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "backend", "lanxiu.db")

# 操作台账:保留 3 年。(表, 时间列)
# ⚠️ **列名写死,一张张核过的** —— 第一版我假设六张表的时间列都叫 `ts`,
# 而 `recall_advice_log` 的叫 `created`,跑起来 `no such column: ts`。
# 不改成「动态猜一个含 ts/at/date 的列」:那在表加新列时会选错列,
# **而选错列算出来的超期数看起来完全正常**。
台账 = [("op_log", "ts"), ("edit_log", "ts"), ("points_log", "ts"),
        ("stock_log", "ts"), ("cust_owner_log", "ts"), ("recall_advice_log", "created")]
台账保留年 = 3
附件保留年 = 1          # ⚠️ 附件表还不存在,这个数先放着


def 演示今天(c):
    """演示世界的今天。取不到就**抛**,不退回真实时钟 ——
    悄悄换一套时钟去算保留期,比报错糟得多。"""
    r = c.execute("SELECT v FROM world_meta WHERE k='world_today'").fetchone()
    if not r or not r[0]:
        raise SystemExit("❌ 读不到 world_meta.world_today —— **不拿真实时钟顶替**:"
                         "台账的时间戳是演示世界的,换一套时钟算出来的超期是假的")
    return r[0]


def 算(c, 今天):
    界 = f"{int(今天[:4]) - 台账保留年}{今天[4:]}"
    out = []
    for t, col in 台账:
        有 = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        if not 有:
            out.append((t, None, 0, None)); continue
        # ⚠️ **列不在就抛,不跳过。** 跳过的话这张表会静默漏掉,
        # 而「这张表没有超期数据」和「这张表根本没被查」在输出上长得一样。
        cols = [d[1] for d in c.execute(f"PRAGMA table_info({t})")]
        if col not in cols:
            raise SystemExit(f"❌ {t} 没有列 `{col}` —— 上面那张表的列名过期了。"
                             f"它现在的列:{cols[:8]}。**不猜一个像时间的列顶替**")
        n, 最早 = c.execute(f"SELECT COUNT(*), MIN({col}) FROM {t} WHERE {col} < ?", (界,)).fetchone()
        out.append((t, col, n or 0, 最早))
    return 界, out


def main():
    ap = argparse.ArgumentParser(description="按保留期清理超期数据(默认只报告)")
    ap.add_argument("--执行", action="store_true", help="真删。不给就只报告")
    ap.add_argument("--db", default=DB)
    a = ap.parse_args()

    if not os.path.exists(a.db):
        print(f"ℹ️ 库不在({a.db})—— **这一轮什么都没做**(不是「清干净了」)")
        return 0
    c = sqlite3.connect(a.db)
    try:
        今天 = 演示今天(c)
        界, 行 = 算(c, 今天)
        print(f"保留期清理 · 演示世界今天 {今天} · 台账保留 {台账保留年} 年 → 删 {界} 之前的")
        总 = 0
        for t, col, n, 最早 in 行:
            if col is None:
                print(f"  ⏸ {t}:表不在 —— **不适用,不是「清干净了」**"); continue
            总 += n
            print(f"  {'🧹' if n else '✅'} {t}:超期 {n} 条" + (f"(最早 {最早})" if n else ""))
        print(f"  ⏸ 附件:**表还不存在**(研判队列的现场照还没落地)—— 附件 {附件保留年} 年这一半等那张表")
        if 总 == 0:
            print("\nℹ️ **没有超期数据** —— 注意这不等于「清理在工作」:"
                  "演示库的台账只有当天的(每次重建从头造),所以这里永远是 0。"
                  "真正验清理逻辑的是 backend/retention_check.py(造夹具验删得掉)")
            return 0
        if not a.执行:
            print(f"\n⚠️ 只报告,**没删**。要删加 `--执行`(删不可逆,所以默认不删)")
            return 0
        for t, col, n, _ in 行:
            if col and n:
                c.execute(f"DELETE FROM {t} WHERE {col} < ?", (界,))
        c.commit()
        print(f"\n🧹 删了 {总} 条")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
