#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一个**默认不写东西**的 seed 脚本,被调用时必须带上那个开关。

## 为什么需要它

这个形状栽过两次,**而且第二次是我「修好」它的第二天**:

- 10-01:CI 里 `seed_evals.py` 少了 `--做` —— 那一步「成功」而**什么都没灌**。
  我修了那一行,并在 workflow 注释里写下了这条规矩。
- 10-02:同一个 job 又红了两份测试,真因是 `seed_pricing.py` 和
  `seed_human_requests.py` **也是这个形状的**,也都少了 `--做`。
  而它们报出来的样子完全不像「没灌数据」:
    · `test_usage_flow` 说「没有 deepseek/deepseek-v4-pro 的价目表快照」
      —— 看起来像模型名写错了,其实整张 `pricing_versions` 是空的
    · `test_handover_flow` 说「库里没有 pending 的待办」
      —— 我把它误诊成「从零建库时没有 execution_run」,查错了方向

> **单点修复和规则修复的差别,就在「还有哪几份是这个形状的」这一问上。**
> 而一个默认不写、而且**退出 0** 的脚本,和一个写成功的脚本,
> 在 CI 日志的绿勾上长得一模一样。

## 这条判据怎么判

1. 扫 `tools/` 和 `services/api/app/` 下所有 `seed_*.py`,
   看它有没有 `add_argument("--做")` —— 有的就是「默认不写」那一类。
2. 扫 `.github/workflows/check.yml` 里**真正的命令行**(不是注释),
   找所有调用 `seed_*.py` 的行。
3. 调用了一个「默认不写」的脚本而**没带 `--做`** → 红。

三种红法:
  · **少带开关**:红。那一步会绿着什么都不干。
  · **一个 seed 脚本都没扫到** / **一条调用行都没扫到**:红
    (**扫不到不是通过** —— 多半是目录结构或 workflow 写法变了)。

## ⚠️ 为什么要先剔掉注释行

`nav_smoke_check` 第一版按字面量搜索,**命中了描述它自己的那句注释**。
而我刚在这个 workflow 的注释里写下了 `seed_pricing` 这些名字 ——
照着搜就会把注释当成调用行,于是「注释里提过」被当成「调用时带了」。
所以这里**先按行剔掉 `#` 开头的,再归属**。

## 已知盲区(写下来,才和「忘了」分得开)

- **只认 `--做` 这一个开关名。** 哪天有脚本改用 `--dry-run` 默认开、
  或者 `--apply`,这条判据看不见它。
  (而那也是一种「默认不写」—— 加了新开关名就要加进 `开关们`。)
- **只扫 workflow,不扫 Makefile 和文档里的调用。** 门禁只在 CI 上
  替人跑 seed;本地是人自己敲的,敲错了当场就看见空列表。
- **不验「灌完真有数据」。** 那一半归各自的端到端测试 ——
  它们本来就在断「库里有没有那条」,这次就是它们抓出来的。
"""
import os
import re
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
仓 = os.path.dirname(根)

# 认得的「默认不写」开关名。**加了新的就加进来** —— 见上面的盲区。
开关们 = ("--做",)


def 找seed脚本():
    """返回 {脚本文件名: 它要不要开关}。"""
    出 = {}
    for d in ("tools", os.path.join("services", "api", "app")):
        目录 = os.path.join(根, d)
        if not os.path.isdir(目录):
            continue
        for 名 in sorted(os.listdir(目录)):
            # ⚠️ **排掉 `*_check.py`** —— 它们是判据,不是 seed 脚本。
            # 第一版没排,于是这个文件**把自己算成了一份被测脚本**
            # (名字以 `seed_` 开头,而正文里那个正则字符串里就有
            # `add_argument("--做")`)。`seed_rerun_check.py` 同理。
            # 而它表现为「多算一份、仍然绿」—— **所以不会有人发现**。
            # 这是 `nav_smoke_check` 那个坑的第三次变体:
            # 第一次是命中描述自己的注释,这次是把自己算进被测对象。
            if not (名.startswith("seed_") and 名.endswith(".py")):
                continue
            if 名.endswith("_check.py"):
                continue
            源 = open(os.path.join(目录, 名), encoding="utf-8").read()
            要开关 = next(
                (k for k in 开关们
                 if re.search(r'add_argument\(\s*["\']' + re.escape(k), 源)),
                None)
            出[名] = 要开关
    return 出


def main():
    print(f"\n\033[1m▸ 默认不写的 seed 脚本,CI 调它时带开关了吗{D}")
    print("  ⚠️ 这条判据看的是**「调用行带没带开关」** —— "
          "它不验「灌完真有数据」(那是各自端到端测试的事)")

    wf = os.path.join(仓, ".github", "workflows", "check.yml")
    if not os.path.isfile(wf):
        print(f"  {R}❌ 找不到 {wf}{D}")
        return 1

    脚本们 = 找seed脚本()
    if not 脚本们:
        # ⚠️ 空集合上所有性质都成立。
        print(f"  {R}❌ 一个 seed 脚本都没扫到 —— **扫不到东西不是通过**{D}")
        return 1
    要开关的 = {k: v for k, v in 脚本们.items() if v}
    print(f"  seed 脚本 {len(脚本们)} 份,其中**默认不写**的 "
          f"{len(要开关的)} 份:{', '.join(sorted(要开关的))}")

    # ⚠️ **先剔掉注释行。** 见上面「为什么要先剔掉注释行」——
    # 这个 workflow 的注释里就写着这几个脚本名。
    调用行 = []
    for 行 in open(wf, encoding="utf-8").read().splitlines():
        裸 = 行.strip()
        if not 裸 or 裸.startswith("#"):
            continue
        if re.search(r"seed_[\w]*\.py", 裸):
            调用行.append(裸)
    if not 调用行:
        print(f"  {R}❌ workflow 里一条 seed 调用行都没扫到 —— "
              f"**扫不到不是通过**(多半是调用写法变了){D}")
        return 1
    print(f"  workflow 里的 seed 调用行:{len(调用行)} 条")

    漏 = []
    for 裸 in 调用行:
        m = re.search(r"(seed_[\w]*\.py)", 裸)
        名 = m.group(1)
        要 = 脚本们.get(名)
        if 名 not in 脚本们:
            # 调了一个不存在的脚本 —— 那一步会直接红,不是这条判据的事。
            continue
        if 要 and 要 not in 裸:
            漏.append((名, 要, 裸))

    if 漏:
        print(f"\n  {R}❌ 这 {len(漏)} 条调用**少了开关** —— "
              f"它们会绿着什么都不灌:{D}")
        for 名, 要, 裸 in 漏:
            print(f"     · {名} 少了 `{要}`")
            print(f"       {裸[:96]}")
        print(f"\n     {Y}一个默认不写、而且退出 0 的脚本,和一个写成功的脚本,"
              f"**在 CI 日志的绿勾上长得一模一样**。{D}")
        print(f"     而下游报出来的样子完全不像「没灌数据」—— 10-02 那次,"
              f"价目表空了报的是「没有某个模型的快照」(像模型名写错)。")
        return 1

    print(f"\n  {G}✅ {len(调用行)} 条调用都带齐了开关{D}")
    print(f"  ⚠️ 盲区:只认 {开关们} 这个开关名 —— "
          f"哪天有脚本改用别的名字(`--dry-run` / `--apply`),这条看不见它")
    return 0


if __name__ == "__main__":
    sys.exit(main())
