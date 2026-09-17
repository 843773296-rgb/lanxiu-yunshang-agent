#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""详情页冒烟 —— **每个详情页函数都拿真数据真跑一遍。**

## 为什么要有这个

`route_check.py` 已经静态查过「路由指向的 handler 真的存在」。
2026-09-17 撞到的事说明那还不够:

    server.measure_of() 读 v[0]["measured_by"]，而那一列 09-16 全库删掉了。
    客户详情页一打开就是 KeyError，**门禁 99 步 + CI 全绿,没有一条检查发现**。

> **「handler 存在」和「handler 跑得起来」是两件事。**
> 静态检查看得见前者,看不见后者 —— 而它们在代码里长得一模一样。

这个项目一路上最贵的故障都是这个形状,这次只是换了个地方出现。
删一列的时候,**读的那一侧会不会炸,只有真跑一次才知道**。

## 判据

对每个 `*_detail` 函数:从库里取一个**真实存在**的 id,调它,要求

  1. 不抛异常;
  2. 返回的不是 `{"error": ...}` —— 拿真 id 还报「不存在」,说明查法和存法对不上;
  3. 返回的不是空的。

## 那张对照表是手写的,所以它自己也要被查

`取参` 是手写的映射(函数 → 去哪张表取一个真 id)。手写的东西会漂:
新加一个详情页而没往表里加一行,这道检查就**悄悄少验一个页面**,而它照样全绿。

所以下面第一条检查是「**server.py 里每个 `*_detail` 都在表里**」——
**把「漏了一行」从静默变成红的。**
"""
import os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402

DB = os.path.join(HERE, "lanxiu.db")

# 函数名 → 取一个真实 id 的 SQL。**加新详情页时这里要跟着加,漏了会红。**
取参 = {
    "task_detail":      "SELECT id FROM task LIMIT 1",
    "shop_detail":      "SELECT code FROM shop LIMIT 1",
    "product_detail":   "SELECT spu FROM product LIMIT 1",
    "activity_detail":  "SELECT code FROM activity LIMIT 1",
    "page_detail":      "SELECT code FROM page LIMIT 1",
    "aftersale_detail": "SELECT id FROM aftersale LIMIT 1",
    "maintain_detail":  "SELECT id FROM maintain LIMIT 1",
    # 这一个是这道检查的由来:量体那一段读了一个已经删掉的列
    "customer_detail":  "SELECT customer_id FROM measure_rec LIMIT 1",
    "appt_detail":      "SELECT id FROM appointment LIMIT 1",
}

咬合 = [
    ('把 measure_of 那处修复整个退回去(既不造 measured_by 字段,也不兜底)—— 这正是 2026-09-17 之前的样子',
     '每个详情页都拿真数据跑得通'),
    ('从「取参」对照表里删掉 customer_detail 那一行(某个页面从此不被验,而检查照样绿)',
     'server.py 里每个详情页函数都在对照表里'),
]

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 源码里的详情页():
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    return sorted(set(re.findall(r"^def (\w+_detail)\(", src, re.M)))


def main():
    print("详情页冒烟 · 拿真数据真跑一遍")
    print("=" * 96)

    # ── ① 对照表不许漏 ────────────────────────────────────────────────
    有 = 源码里的详情页()
    漏 = [f for f in 有 if f not in 取参]
    多 = [f for f in 取参 if f not in 有]
    ck("server.py 里每个详情页函数都在对照表里", not 漏 and not 多, len(有),
       (f"漏了 {漏} " if 漏 else "") + (f"表里多出 {多}" if 多 else "") or
       "**漏一行不会报错,只会让某个页面从此不被验** —— 所以先查这个")

    # ── ② 每个都拿真数据跑一遍 ────────────────────────────────────────
    c = sqlite3.connect(DB)
    坏 = []
    跑了 = 0
    for fn in 有:
        sql = 取参.get(fn)
        if not sql:
            continue          # ① 已经报过了,这里不重复计数
        row = c.execute(sql).fetchone()
        if not row or row[0] is None:
            坏.append(f"{fn}:库里取不到真 id(`{sql}`)—— **拿不到样本不算通过**")
            continue
        arg = row[0]
        跑了 += 1
        try:
            out = getattr(server, fn)(arg)
        except Exception as e:
            坏.append(f"{fn}({arg!r}) 抛了 {type(e).__name__}: {e}")
            continue
        if isinstance(out, dict) and out.get("error"):
            坏.append(f"{fn}({arg!r}) 拿真 id 却返回 error:{out['error']}")
        elif not out:
            坏.append(f"{fn}({arg!r}) 返回空 —— 真实存在的 id 不该查不到东西")
    c.close()

    ck("每个详情页都拿真数据跑得通", not 坏, 跑了,
       ("；".join(坏[:3]) if 坏 else
        "**页面炸了和页面空着,在静态检查眼里一模一样** —— 只有真跑一次分得开"))

    print("=" * 96)
    if FAIL:
        print(f"\033[31m❌ {len(FAIL)} 条没过:{FAIL}\033[0m")
        return 1
    print(f"\033[32m✅ {len(有)} 个详情页全部拿真数据跑通\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
