#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库有多大 —— **现算,不许手抄一个数在文档里。**

`intent/kb-e-staff-training.md` 要把库扩到 20 万 token。
而「多大」这个数**如果手写在文档里,它第二天就开始漂** ——
这个项目已经为「手写的清单会过期,而过期时不报错」栽过好几次。

## ⚠️ 它把「给人读的」和「机器生成的表格」分开数

版型库(1237 条尺码)和物料 BOM(135 种物料)是**从数据推出来的**,
占了全库 46%。**它们是给工具查的,不是给店内人员读的。**

「离 20 万还差多少」原来有两个答案,取决于那部分算不算 —— 业务 2026-09-25 定了**不算**,
现在只报给人读的那个数。`--实测` 用 Claude 命令行逐篇测真实 token(慢,但不是估)。

用法:python3 tools/kb_size.py [--实测]
"""
import glob, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 机器从数据推出来的那几篇 —— **不是讲解材料**
生成的 = ("10-版型库.md", "11-物料与BOM.md")
目标 = 200_000

# 每字符多少 token —— **2026-10-02 实测**(Claude 命令行回包的 usage,同一目录下「全文 + 一句话」减「只那一句话」):
#     05-颜色 0.997 · 13-销售话术 0.956 · 03-工艺 0.870(表格和英文字段多的篇更低)
# ⚠️ 原来写的是 1.3–1.6(「粗估」,没测过),**高估了三到六成** ——
# 按旧系数,给人读的 8.5 万字符被估成 11–13 万 token、「翻一倍就够」;实测只有 8 万上下,要翻到 2.5 倍左右。
# 一个估出来的系数和一个测出来的,在报告里长得一模一样 —— 所以 `--实测` 能随时重测。
#     扩容两轮后整库实测(2026-10-02 晚):给人读的 221,325 字符 → 228,425 token ≈ 1.03 —— 纯中文讲解比表格多的篇更高
每字符token = (0.87, 1.05)

# 业务 2026-09-25 定:机器生成的表格**不算**,只数给人读的(intent kb-e-staff-training)
只数给人读的 = True


def 实测(path):
    """用 Claude 命令行测一篇的真实 token 数(月租登录,不额外计费)。测不了返回 None。"""
    import json, subprocess
    def 量(文本):
        r = subprocess.run(["claude", "-p", "--output-format", "json", "--model", "claude-haiku-4-5"],
                           input=文本, capture_output=True, text=True, cwd=ROOT, timeout=300)
        try:
            u = json.loads(r.stdout)["usage"]
        except Exception:
            return None
        return u["input_tokens"] + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    基 = 量("只回复 OK")
    全 = 量(open(path, encoding="utf-8").read() + "\n只回复 OK")
    return (全 - 基) if (基 and 全) else None


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
    中 = sum(每字符token) / 2
    if "--实测" in sys.argv:
        测 = 0
        for 名, _ in 人读:
            t = 实测(os.path.join(ROOT, "knowledge", 名))
            print(f"  实测 {名:24s} {t if t is not None else '测不了':>7} token")
            测 += t or 0
        print(f"  **给人读的实测合计 {测:,} token**(测不了的按 0 计)")
        现 = 测
    else:
        现 = int(a * 中)
    print(f"  按业务 09-25 的口径(表格不算):给人读的约 **{现:,} token**,目标 {目标:,} —— "
          + ("✅ 达标" if 现 >= 目标 else f"还差约 {目标 - 现:,} token(≈ {int((目标 - 现) / 中):,} 字符,"
                                          f"要到现在的 {目标 / max(现, 1):.1f} 倍)"))
    print("  ⚠️ token 数是个**只看长度不看内容**的指标 —— "
          "一篇注了水的和一篇扎实的,在这张表上长得一模一样。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
