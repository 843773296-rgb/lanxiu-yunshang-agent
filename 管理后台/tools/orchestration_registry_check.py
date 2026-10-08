#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`tests/orchestration/` 和 `tests/integration/` 下的自测,
**每一份都得有入口能跑**。

⚠️ 2026-10-08 把 `tests/integration/` 也收进来了(原来只管编排层)。
起因:加 `tests/orchestration/test_answerer.py` 的时候我顺手又写了一条
同样的判据塞进 `test_registry_check.py` —— **而这一条已经存在**。
> 同一条性质有两个判据,它们迟早分叉,**而分叉的时候两边各自都是绿的**。
所以那半撤了,只把**真没人盯的那一层**(集成层,9 份)补进这里。

**文件名没改**(还叫 `orchestration_`):它被 Makefile 和交接文档引用着,
改名要同步三处,而收益只是名字更准。**这一行就是那个名字的解释。**

## 为什么需要它

这个仓库已经有两个同形状的判据:
`tools/test_registry_check.py` 盯端到端那一组、澜绣侧 `tools/selftest_registry_check.py`
盯它自己的自测。**而 `tests/orchestration/` 这一组没人盯。**

2026-10-04 数的时候是 16 份文件、Makefile 里挂了 16 份 —— 齐的。
**而它齐,正是靠人手挂齐的**:下一份忘了挂,门禁照旧绿。

> **一份没进门禁的自测,和一份不存在的自测,在绿勾上长得一模一样。**
> 而 16/16 这个数字现在对,恰恰让「没人在盯」看不出来。

这个项目在这个形状上栽过:2026-10-03 发现**三份自测从写好那天起没进过门禁**,
其中一份 37 条,而门禁一直绿。

## 判据

扫 `tests/orchestration/test_*.py`,每一份都要在 `Makefile` 里被引用到。
没被引用、又没写在 `明写不挂` 里 → **红**。

⚠️ **「被 Makefile 引用」不等于「那条 make 目标有人跑」。** 这一条的盲区写在输出里:
它证明的是「有入口」,不是「那个入口在 CI 里跑」。
(e2e 那一组之所以能证明后者,是因为 CI 直接跑 `test-e2e-ci`。)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# ⚠️ 两层各自的**样本量下限**。空集合上「每一份都挂了」恒为真 ——
# 而「一份都没扫到」和「全挂齐了」在那句话上长得一模一样。
两层 = (("orchestration", 5), ("integration", 5))
MAKEFILE = os.path.join(ROOT, "Makefile")

# ── 明写不挂 —— **排掉一份是个决定,漏掉一份是个事故** ────────────────
#
# ⚠️ 每一条都要写清**为什么**,而且理由要是「它不该进这一组」,
# 不是「它让门禁红了」。后一种理由等于把判据改松。
明写不挂 = {}


def 挂了哪些(层):
    with open(MAKEFILE, encoding="utf-8") as f:
        mk = f.read()
    # ⚠️ **不能写成 `test_[A-Za-z0-9_]+\.py`** —— 那只认 ASCII 文件名,
    # 而这个仓库到处是中文文件名。咬合时实测:把一份改名成
    # `test_根本没有这份.py`,这个正则**根本看不见它**,
    # 于是「Makefile 引用了一份不存在的文件」那条分支永远走不到;
    # 反过来,将来真有人加一份 `test_缓存键.py`,它会被报成「没入口」——
    # **一份已经挂好的测试被报成漏挂**,害人去查一个不存在的问题。
    # > 判据按自己的写法定,别人换个写法就漏了(`trace_check` 的老教训)。
    # 所以这里按「不是空白、不是 Make 语法分隔符」收,不枚举字符集。
    return set(re.findall(
        rf"tests/{层}/(test_[^\s\"':;()|&]+\.py)", mk))


def main():
    print("自测清单对账 · tests/orchestration/ + tests/integration/")
    print("=" * 76)
    坏 = 0
    for 层, 下限 in 两层:
        坏 |= 一层(层, 下限)
    return 1 if 坏 else 0


def 一层(层, 下限):
    组目录 = os.path.join(ROOT, "tests", 层)
    print(f"\n▸ tests/{层}/")
    if not os.path.isdir(组目录):
        print(f"  ❌ 找不到 {组目录} —— **这不叫「没有自测」,叫路径写错了**")
        return 1
    文件们 = sorted(f for f in os.listdir(组目录)
                 if f.startswith("test_") and f.endswith(".py"))
    # ⚠️ **样本量下限。** 空集合上「每一份都挂了」恒为真 ——
    # 而「一份都没扫到」和「全挂齐了」在那句话上长得一模一样。
    if len(文件们) < 下限:
        print(f"  ❌ 只扫到 {len(文件们)} 份自测({组目录},下限 {下限})—— "
              f"**这不叫「都挂齐了」,叫没扫到文件**")
        return 1
    挂 = 挂了哪些(层)
    print(f"  {组目录.replace(ROOT + os.sep, '')} 下有 {len(文件们)} 份;"
          f"Makefile 里引用了 {len(挂)} 份")

    漏 = [f for f in 文件们 if f not in 挂 and f not in 明写不挂]
    例外 = [f for f in 文件们 if f in 明写不挂]
    野 = sorted(挂 - set(文件们))

    for f in 例外:
        print(f"  ⏸ {f} —— **明写不挂**:{明写不挂[f]}")
    if 野:
        # Makefile 引用了一份不存在的文件 —— 那条 make 目标会当场崩,
        # 而**崩和「检查不过」不是一回事**(崩的那条一条都没验)。
        print(f"  ❌ Makefile 引用了 {len(野)} 份**不存在**的自测:{野}")
        print(f"     那条 make 目标会崩 —— 而崩掉的检查**一条都没验过**,"
              f"它和「验了不合格」要分开看")
        return 1
    if 漏:
        print(f"\n  ❌ 这 {len(漏)} 份**没有任何入口能跑**:{漏}")
        print(f"     挂进 Makefile 的 "
              f"`{'test-orchestration' if 层 == 'orchestration' else 'test'}`,"
              f"或者写进这个脚本的 `明写不挂` 并**说清为什么**。")
        print(f"     ⚠️ **排掉一份是个决定,漏掉一份是个事故** —— "
              f"而它们在目录里长得一样:文件在、看起来有覆盖,而没人跑它。")
        return 1

    print(f"  ✅ {len(文件们)} 份自测都有入口能跑")
    print(f"  ⚠️ 盲区:这一条证明的是「**有入口**」,不是「那个入口在 CI 里跑」。")
    print(f"     要证后者得看 CI 真跑了哪条 make 目标 —— "
          f"而「挂在一个没人跑的目标里」和「没挂」的后果是一样的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
