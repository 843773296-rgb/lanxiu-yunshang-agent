#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把造数造出来的**重复渠道流水号**改成绑押金号的那一版。

来路:只读审计 2026-10-23 第 1 条。默认**只报不改**,要真改加 `--做`。

## 它修什么、不修什么

**只修造数造的那几行** —— `deposit_id` 以 `DQ` 开头、`id` 恰好是 `PF{押金号}{I|O}` 的。
那是 `tools/seed_triage_tasks.造财务()` 的产物,形状完全确定。

**不碰别的任何流水。** 真实(模拟)流水的号是 12 位随机数(`WX548899456486` 那种),
而**真实世界里同一个渠道单号可能合法地出现两次**(重试 / 对账补录 / 部分退款分笔)——
那取决于渠道的事件语义,不是这个脚本能替业务定的。审计原话:
「真实支付流水的唯一约束应依据渠道事件语义确定,**不能直接按当前猜测加索引或删除重复行**。」

**而且它改号,不删行。** 那四行押金流水是真有业务含义的(收款 / 退款各一条),
删掉会让押金对不上账;错的只是那个号。
> **一次「删掉了一条假数据」和一次「删掉了一条真流水」,在行数变少这件事上长得一模一样。**

## ⚠️ 号怎么算 —— 调造数那个函数,不抄

`seed_triage_tasks.渠道流水号(did, 方向)` 是**唯一实现**。
各写一份的话,哪天改了算号方式,**这个脚本会把对的数据改成错的** ——
而它不报错,它只是按另一份算法算出了另一个号。
(同 CLAUDE.md §7-2 同源谬误那一族:让那段逻辑只剩一份,别人真调它。)

## 为什么要人跑一次,而不是等重建

库不会自动重建(`seed.py` 要人跑),所以那两条重复会一直在,
而新加的判据 `backend/payment_serial_check.py` 会一直红。
跑一次就对了,之后造数自己绑押金号,不会再造出重复。
"""
import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE]

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
DB = os.path.join(ROOT, "backend", "lanxiu.db")

import seed_triage_tasks as _S          # ← 号的唯一实现在这儿


def 要改的(c):
    """返回 [(流水 id, 押金号, 方向, 现在的号, 该是的号)] —— 只含造数那几行、且号不对的。"""
    出 = []
    for fid, did, di, se in c.execute(
            "SELECT id, deposit_id, direction, channel_serial FROM payment_flow "
            "WHERE deposit_id LIKE 'DQ%' ORDER BY deposit_id, direction"):
        # **形状必须完全对上**才认它是造数的产物 —— 对不上的一律不碰
        if fid != f"PF{did}{'I' if di == 'in' else 'O'}":
            continue
        该 = _S.渠道流水号(did, di)
        if se != 该:
            出.append((fid, did, di, se, 该))
    return 出


def 重复的(c):
    out = []
    for ch, se, di, cnt in c.execute(
            "SELECT channel, channel_serial, direction, COUNT(*) FROM payment_flow "
            "WHERE channel_serial IS NOT NULL AND TRIM(channel_serial) <> '' "
            "GROUP BY channel, channel_serial, direction HAVING COUNT(*) > 1"):
        out.append((ch, se, di, cnt))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--做", action="store_true", help="真改;不加就是试跑(只报不改)")
    a, 野 = ap.parse_known_args()
    if 野:
        print(f"{Rd}❌ 不认识这些参数:{野} —— **不认识就不跑**{D}")
        return 2
    if not os.path.exists(a.db):
        print(f"{Y}库不在:{a.db}{D}")
        return 1

    print("造数的渠道流水号 · 改成绑押金号(不绑循环下标)")
    print("=" * 78)
    print(f"库:{a.db}")
    with sqlite3.connect(f"file:{a.db}?mode=ro", uri=True) as ro:
        重前 = 重复的(ro)
        改 = 要改的(ro)
    print(f"造数流水里号不对的 **{len(改)} 行**;全库重复的「渠道+号+方向」**{len(重前)} 组**")
    for fid, did, di, se, 该 in 改:
        print(f"  {fid}  [{did} {di}]  {se}  →  {该}")
    for ch, se, di, cnt in 重前:
        print(f"  {Y}重复:{ch} / {se} / {di} —— {cnt} 条{D}")
    if not 改:
        print(f"  {G}一行都不用改 —— 这不叫没查,是查过了{D}")
        return 0 if not 重前 else 1
    if not a.做:
        print(f"  {Y}(试跑,一个字都没改。确认之后加 `--做`){D}")
        return 0

    c = sqlite3.connect(a.db)
    with c:
        for fid, did, di, se, 该 in 改:
            # ⚠️ **按流水 id 改,一行一行改。** 不按「号等于那个坏值」批量改 ——
            # 那个坏值可能被别的、不是造数造的行用着,而那些行**不该被碰**。
            c.execute("UPDATE payment_flow SET channel_serial=? WHERE id=?", (该, fid))
    c.close()
    with sqlite3.connect(f"file:{a.db}?mode=ro", uri=True) as ro:
        重后 = 重复的(ro)
        剩 = 要改的(ro)
    print(f"  {G}改了 {len(改)} 行{D}")
    print(f"  重复的组数:{len(重前)} → {len(重后)} · 造数里号还不对的:{len(剩)}")
    if 重后 or 剩:
        print(f"  {Rd}❌ 没改干净:还重复 {重后} · 还不对 {剩}{D}")
        return 1
    print(f"  {G}✅ 造数流水号现在都绑押金号了,全库没有「同渠道+同号+同方向」的重复{D}")
    print(f"      ⚠️ 这个脚本**只改号、不删行** —— 那几行押金流水是真有业务含义的"
          f"(收款 / 退款各一条),删掉会让押金对不上账;错的只是那个号。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
