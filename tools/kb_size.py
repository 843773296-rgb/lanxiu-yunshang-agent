#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库有多大 —— **现算,不许手抄一个数在文档里。**

`intent/kb-e-staff-training.md` 要把库扩到 20 万 token。
而「多大」这个数**如果手写在文档里,它第二天就开始漂** ——
这个项目已经为「手写的清单会过期,而过期时不报错」栽过好几次。

## ⚠️ 它把「给人读的」和「机器生成的表格」分开数

版型库(1237 条尺码)和物料 BOM(135 种物料)是**从数据推出来的**,
占了全库 46%。**它们是给工具查的,不是给店内人员读的。**

所以「离 20 万还差多少」有两个答案,取决于那部分算不算 ——
**这道题是业务的,脚本只把两个数都摆出来,不替它挑一个。**

用法:python3 tools/kb_size.py
"""
import glob, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 机器从数据推出来的那几篇 —— **不是讲解材料**
生成的 = ("10-版型库.md", "11-物料与BOM.md")
目标 = 200_000

# 中文 token 粗估系数。⚠️ **这是估,不是测** ——
# 真实 token 数要用分词器算,而这里只是给一个量级。
# 写下来是因为:**一个估出来的数和一个测出来的数,在报告里长得一模一样。**
每字符token = (1.3, 1.6)


def main():
    人读, 机器 = [], []
    for f in sorted(glob.glob(os.path.join(ROOT, "knowledge", "*.md"))):
        n = len(open(f, encoding="utf-8").read())
        (机器 if os.path.basename(f) in 生成的 else 人读).append(
            (os.path.basename(f), n))
    print("知识库有多大(**现算**)")
    print("=" * 66)
    for 名, n in 人读 + 机器:
        标 = "  (机器生成的表格)" if 名 in 生成的 else ""
        print(f"  {名:24s} {n:>7,} 字符{标}")
    a = sum(n for _, n in 人读)
    b = sum(n for _, n in 机器)
    print("=" * 66)
    for 标, v in (("给人读的", a), ("机器生成的表格", b), ("合计", a + b)):
        lo, hi = int(v * 每字符token[0]), int(v * 每字符token[1])
        print(f"  {标:16s} {v:>7,} 字符 ≈ {lo:>7,} – {hi:>7,} token")
    print()
    print(f"  ⚠️ **离 {目标:,} token 还差多少,有两个答案** —— "
          f"取决于那 {b:,} 字符的表格算不算:")
    for 标, v in (("算(全库)", a + b), ("不算(只数给人读的)", a)):
        中 = v * sum(每字符token) / 2
        print(f"     {标:22s} 约 {目标 / 中:.1f} 倍  "
              f"(还要补 ≈ {max(0, int((目标 - 中) / (sum(每字符token)/2))):,} 字符)")
    print()
    print("  **这道题是业务的,脚本不替它挑一个。**")
    print("  ⚠️ 而 token 数是个**只看长度不看内容**的指标 —— "
          "一篇注了水的和一篇扎实的,在这张表上长得一模一样。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
