#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成本口径对账 —— **项目算出来的钱,要和官方计费规则算出来的一样。**

    python3 agentsite/cost_check.py

## 这条是怎么来的

2026-09-22 重算 V3 的实测用量时发现:`agentsite/sdk.py` 的 `cost_of()`
**少算了约三成**(Haiku 那一轮 29%、Sonnet 5 网站 32%)。两处和官方规则对不上:
官方的 `input_tokens` 已经不含缓存命中和写入,它又减了一次缓存命中;缓存写入整个没算。

它能错这么久,是因为**没有任何一条检查验过它** —— 成本只是打出来给人看的一个数,
错了不会让任何东西变红。而记录仪自己那套算法一直是对的,
V3 却为了「成本口径只有一处」拿这个错的数去覆盖了它。

## ⚠️ 期望值为什么手抄,不从项目价目表取

从 `agent/v1.py` 的价目表现算期望值,就是**同源谬误**:价目表错了,期望值跟着一起错,
这条检查照样绿。所以下面的单价是 **2026-09-22 从官方定价页手抄的常数**,
和项目价目表是两条独立的来源 —— 两边对不上,正说明有一边错了。
官方调价时这里要跟着改,并在日期上写清楚。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 官方单价(美元/百万 token),查于 2026-09-22:输入、5 分钟缓存写入、缓存命中、输出
官方 = {"claude-haiku-4-5": (1.00, 1.25, 0.10, 5.00),
        "claude-sonnet-5":  (2.00, 2.50, 0.20, 10.00),
        "claude-opus-5":    (5.00, 6.25, 0.50, 25.00),
        # DeepSeek 官方页只有「命中 / 未命中」两档,写入按未命中价(平峰)
        "deepseek-v4-pro":  (0.66, 0.66, 0.022, 1.98)}

# 用例:取自记录仪里真实的用量画像(附录 D.6)—— 缓存命中远大于未命中,正是原来那个 bug 的形状
用例 = [("claude-haiku-4-5", dict(input_tokens=21, cache_creation_input_tokens=9339,
                                  cache_read_input_tokens=170115, output_tokens=2315)),
        ("claude-sonnet-5",  dict(input_tokens=5, cache_creation_input_tokens=7476,
                                  cache_read_input_tokens=151577, output_tokens=977)),
        ("claude-opus-5",    dict(input_tokens=1200, cache_creation_input_tokens=0,
                                  cache_read_input_tokens=0, output_tokens=300)),
        ("deepseek-v4-pro",  dict(input_tokens=35055, cache_creation_input_tokens=0,
                                  cache_read_input_tokens=43834, output_tokens=1458))]

咬合 = [("把 cost_of 改回「输入减缓存命中、不算缓存写入」", "按官方规则对得上"),
        ("长提示不分档(单次超过 10 万 token 仍按便宜档算)", "Haiku 5.5 单次提示超过 10 万 token → 整次按贵档"),
        ("按整轮总量分档(三次各 6 万被当成一次 18 万)", "Haiku 5.5 三次调用各 6 万 → 仍是便宜档")]


def 应为(m, u):
    a, b, c, d = 官方[m]
    return (u["input_tokens"] * a + u["cache_creation_input_tokens"] * b
            + u["cache_read_input_tokens"] * c + u["output_tokens"] * d) / 1e6


def main():
    import sdk
    坏 = []
    print("成本口径对账")
    print(f"  ✅ 样本量:{len(用例)} 条(含缓存命中远大于未命中的真实画像)")
    for m, u in 用例:
        # DeepSeek 有高峰翻倍 —— 固定一个平峰时刻(2026-09-20 是周日,整天平峰),
        # 免得这条检查随跑的钟点变红变绿
        import calendar
        实 = sdk.cost_of(u, m, ts=calendar.timegm((2026, 9, 20, 12, 0, 0)))
        期 = 应为(m, u)
        ok = 实 is not None and abs(实 - 期) < 1e-6
        print(f"  {'✅' if ok else '❌'} {m}:项目算 {实} · 官方规则 {期:.6f}")
        if not ok:
            坏.append(m)
    print("\033[31m❌ 按官方规则对得上 —— %s 对不上\033[0m" % "、".join(坏) if 坏
          else "\033[32m✅ 按官方规则对得上\033[0m")
    长提示(坏)
    return 1 if 坏 else 0


# ── 长提示分档(11-12,执行手册 W04)──────────────────────────────────────
# Haiku 5.5 官方价(查于 2026-10-25,Claude API 资料 Current Models 表):单次提示 ≤10 万 token
# 输入 $0.10 / 输出 $0.50;超过 10 万这一次整个按 $0.50 / $2.50。缓存命中按输入 0.1 倍、写入 1.25 倍。
# 手抄常数,不从 v1.LONG_PRICE 现算(同源谬误,见文件头)。
H55_短 = (0.10, 0.125, 0.010, 0.50)
H55_长 = (0.50, 0.625, 0.050, 2.50)


def _按档(u, 价):
    a, b, c, d = 价
    return (u["input_tokens"] * a + u["cache_creation_input_tokens"] * b
            + u["cache_read_input_tokens"] * c + u["output_tokens"] * d) / 1e6


def 长提示(坏):
    import sdk
    零出 = lambda u: dict(u, output_tokens=0)
    # ① 顾问助手实测画像:单次 13.9 万(体检 B 报告 spans 实测),一次调用、输出 1000
    u = dict(input_tokens=20, cache_creation_input_tokens=9000, cache_read_input_tokens=130000, output_tokens=1000)
    实, 期 = sdk.cost_of(u, "claude-haiku-5-5", 每次调用=[零出(u)]), _按档(u, H55_长)
    ok = 实 is not None and abs(实 - 期) < 1e-6
    print(f"  {'✅' if ok else '❌'} Haiku 5.5 单次提示超过 10 万 token → 整次按贵档:项目算 {实} · 官方 {期:.6f}")
    if not ok: 坏.append("长提示贵档")
    # ② 三次调用各 6 万:每次都在便宜档,合起来 18 万也不该按贵档
    c = dict(input_tokens=10, cache_creation_input_tokens=5000, cache_read_input_tokens=55000, output_tokens=0)
    合 = {k: c[k] * 3 for k in c}; 合["output_tokens"] = 900
    实2, 期2 = sdk.cost_of(合, "claude-haiku-5-5", 每次调用=[c, c, c]), _按档(合, H55_短)
    ok2 = 实2 is not None and abs(实2 - 期2) < 1e-6
    print(f"  {'✅' if ok2 else '❌'} Haiku 5.5 三次调用各 6 万 → 仍是便宜档:项目算 {实2} · 官方 {期2:.6f}")
    if not ok2: 坏.append("按次分档")
    # ③ 给不了每次调用的用量 → 不猜(返回 None,页面显示「—」)
    ok3 = sdk.cost_of(u, "claude-haiku-5-5") is None
    print(f"  {'✅' if ok3 else '❌'} 有贵档的模型、没给每次调用的用量 → 不猜(None)")
    if not ok3: 坏.append("不猜")


if __name__ == "__main__":
    sys.exit(main())
