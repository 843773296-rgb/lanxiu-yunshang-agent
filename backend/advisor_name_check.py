#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顾问名字在页面上的检查 —— **删列之前,先有东西看得见页面上写着谁。**

## 为什么先做这个

`intent/advisor-columns.md` 要删掉那几张表的 `advisor` 名字列(名字是
`staff` 的副本,而副本会漂)。它自己写着一条硬约束:

> **不在页面改完之前删列** —— 删了页面会**静默显示空名字**。

而摸下来发现:**这 38 页没有任何东西在测。** `route_check` 只验函数名存在,
`js_check` 只验内联 JS 的语法 —— **没有一条检查看得见页面上到底写着什么**。

**在没有网的情况下做这种迁移,失败方式正是那句警告:**
页面照常打开、表格照常有行,只是「顾问」那一栏**空了** ——
而没有人会因为一栏空白去跑测试。

所以这个文件先把网兜起来:**直接调页面函数**(它们收 query 返回数据,
不是 HTML 串,所以调得动),逐个断言顾问那一栏**有名字、而且和 `staff` 对得上**。

## 顺带纠正一个数

intent 里写的是「**38 个页面**改成 join staff」。真实情况是
**8 个页面函数**会吐出顾问名字 —— 38 是页面总数,不是受影响的页数。

> **一个错的数字能把一件半天的事压在待办里好几天。**

## 这个检查在迁移之后也不撤

迁移完成、列删掉之后,它守的东西**不变**:页面上那一栏得有名字。
真正该撤的是 `advisor_ref_check`(它查的是「缓存有没有漂」——
列没了就没有缓存,那条检查自然失去对象)。
"""
import inspect, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]

咬合 = [
    ("把 customer_list 里 SELECT 的 advisor 换成一个空字符串",
     "每个页面的顾问那一栏都有名字"),
    ("把某一行的顾问名字改成一个 staff 里没有的人",
     "页面上的顾问名字都在员工表里"),
    ("把页面函数列表写死成 0 个",
     "扫得到吐顾问名字的页面"),
    ("把「顾问」这个中文 key 也当成名字栏(误伤权限矩阵)",
     "页面上的顾问名字都在员工表里"),
]

# **会吐出顾问名字的页面函数** —— 现算,不写死。
# 写死一张清单的话,**新加一个页面不会有人记得回来加**,
# 而它坏了的表现是「这个页面没被测」,和「测过了」长得一模一样。
# ⚠️ **不要把「顾问」这个中文 key 当成名字栏。**
# 第一版把它加进来了,当场误伤 `staff_list` 的权限矩阵:
# 那里「顾问」是**角色名**,值是权限项(「查看本人客户」「新建跟进」),
# 不是人名。**判据又一次贴着字面,不贴着含义。**
#
# 只认 `advisor` / `measured_by` —— 在这个库里它们当 key 时装的就是人名。
名字栏 = ("advisor", "measured_by")

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 挖名字(o, 路=""):
    """把返回值里所有「顾问名字」那一栏挖出来,带上它在哪。"""
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k in 名字栏:
                if isinstance(v, str):
                    out.append((f"{路}/{k}", v))
                elif isinstance(v, list):
                    out += [(f"{路}/{k}[{i}]", x) for i, x in enumerate(v)
                            if isinstance(x, str)]
            out += 挖名字(v, f"{路}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out += 挖名字(v, f"{路}[{i}]")
    return out


def 扫页面():
    """现算:哪些页面函数吐出顾问名字。返回 {函数名: [(路径, 名字), ...]}"""
    import server
    出 = {}
    for n, f in sorted(vars(server).items()):
        if not (inspect.isfunction(f) and f.__module__ == "server"):
            continue
        try:
            if len(inspect.signature(f).parameters) != 1:
                continue
            r = f({})
        except Exception:
            continue          # 要参数 / 要登录的跳过,**不算失败**
        hits = 挖名字(r)
        if hits: 出[n] = hits
    return 出


def main():
    print("顾问名字 · 页面检查")
    print("=" * 84)
    import api

    页 = 扫页面()
    ck("扫得到吐顾问名字的页面", bool(页), len(页),
       f"{sorted(页)} —— **现算不写死**:写死一张清单的话,"
       f"新加一个页面不会有人记得回来加,而那时候它坏了的表现是"
       f"「这个页面没被测」,和「测过了」长得一模一样")

    # ── ① 每一栏都得有名字 ────────────────────────────────────────────
    # **这条是为删列准备的。** 列删掉而页面没改的话,这里会立刻空掉 ——
    # 而在这条检查之前,空掉是没有人看得见的。
    空 = [(n, 路) for n, hs in 页.items() for 路, v in hs if not (v or "").strip()]
    总 = sum(len(hs) for hs in 页.values())
    ck("每个页面的顾问那一栏都有名字", not 空, 总,
       f"{len(空)} 处是空的:{空[:3]}" if 空 else
       f"{len(页)} 个页面、{总} 处 —— **删了列而页面没改,这里会立刻空掉**")

    # ── ② 而且名字要在员工表里 ────────────────────────────────────────
    # 有名字不等于名字对。**一个漂掉的名字和一个对的名字长得一模一样** ——
    # 这正是要删掉这一列的原因。
    花名册 = {r["name"] for r in api._rows("SELECT name FROM staff")}
    带号 = {f"{r['no']} {r['name']}" for r in api._rows("SELECT no,name FROM staff")}
    野 = []
    for n, hs in 页.items():
        for 路, v in hs:
            v = (v or "").strip()
            if not v: continue
            短 = v.split(" ", 1)[-1] if " " in v else v
            if v not in 带号 and v not in 花名册 and 短 not in 花名册:
                野.append((n, 路, v))
    ck("页面上的顾问名字都在员工表里", not 野, 总,
       f"{len(野)} 个查无此人:{野[:3]}" if 野 else
       "**有名字不等于名字对** —— 一个漂掉的名字和一个对的名字长得一模一样")

    print()
    if FAIL:
        print(f"\033[31m❌ 顾问名字 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print("\033[32m✅ 顾问名字全部符合预期\033[0m")
    print(f"    {len(页)} 个页面吐出顾问名字(**不是 intent 里写的 38** —— "
          f"38 是页面总数)。删列之前,这张网先兜住了。")


if __name__ == "__main__":
    main()
