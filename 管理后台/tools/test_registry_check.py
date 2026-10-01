#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端测试清单对账:**每一份都要在 `test-e2e` 和 `progress` 两处都登记**。

## 为什么需要它

`Makefile` 里有**两份**端到端测试清单,各自手写:

  · `test-e2e`  —— 人跑门禁时跑的那些
  · `progress`  —— 生成 `docs/实现进度.md` 时跑的那些(带路由记账)

只加一处的后果**不对称**,而且更坏的那一边是静默的:

| 漏在哪 | 后果 | 看起来怎样 |
|---|---|---|
| 漏在 `test-e2e` | 门禁不跑它 | 门禁绿,而那几条边界其实没测 |
| 漏在 `progress` | 它打过的路由**不进账本** | **接口被记成「已实现未验」** |

第二种已经真发生过一次:那一轮「验过」**少算 5 条**,
而**报告自己看起来完全正常** —— 一张 95 行的清单上,
「未验」和「验过」都只是一行接口名,少算的那几条看不出来。

> **一条只写在一个写入口上的规矩,拦不住第二个写入口。**
> 这里的「写入口」是两份手写清单,而它们会漂。

## 这条判据守的性质

`tests/e2e/` 下每一个 `test_*.py`,在 Makefile 里**两处都出现**。

⚠️ 故意**不做**的事:不去解析 Makefile 的目标结构、不判断它在哪个目标里。
那样要写一个 Makefile 解析器,而解析器本身会成为新的盲区来源。
改成一个更粗但咬得住的判据:**数出现次数**。
一份测试在 Makefile 里至少要出现两次(两份清单各一次)。
粗判据的代价是它认不出「同一个清单里写了两遍」——
所以下面额外把**每个目标段各自数一遍**,两边都要 ≥1。

⚠️ **例外要点名写下来,不许静默跳过。**
一个「有就判、没有就跳过」的名单,在下一个人加文件那天会安静地变成空跑。
"""
import os
import re
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 例外:**点名 + 写理由**,不许只写名字 ────────────────────────────────
# 每一条都要说清「为什么它不该进那两份清单」。说不清的就不是例外,是漏登记。
例外 = {
    "test_upload_page_firefox.py":
        "要可见的 Firefox 窗口 + selenium(**故意不进 requirements.lock**)—— "
        "放进门禁会变成随机拦路(和 js_smoke 同一个理由)。"
        "**它有自己的入口:`make test-browser`** —— "
        "2026-09-29 补的:在那之前文件头写着「单独 make test-browser」"
        "而那个目标并不存在,于是这份测试没有任何入口能跑它,"
        "**那和没有这份测试是一回事**,只是它躺在目录里看起来像有覆盖",
}


def main():
    print(f"\n\033[1m▸ 端到端测试清单对账 · 两份手写清单会漂{D}")

    e2e目录 = os.path.join(根, "tests", "e2e")
    if not os.path.isdir(e2e目录):
        print(f"  {R}❌ 找不到 {e2e目录} —— **路径不对不是通过**{D}")
        return 1

    # ⚠️ **`.js` 也要算。** 第一版只扫 `.py`,而 `tests/e2e/` 下有 JS 测试
    # (页面接线那一份就是)—— 于是这条判据**盖不住它**:
    # 一份只挂在 `test-e2e` 里的 JS 测试,路由不进 progress 的账本,
    # 而那正是这条判据存在的理由。
    # > 一条按扩展名选目标的判据,漏掉一种扩展名就等于漏掉那一整类。
    文件们 = sorted(f for f in os.listdir(e2e目录)
                  if f.startswith("test_") and (f.endswith(".py")
                                                or f.endswith(".js")))
    if not 文件们:
        # ⚠️ 空集合上所有性质都成立。扫到 0 份就是路径错了,而那会让这条判据全过。
        print(f"  {R}❌ 一份端到端测试都没扫到 —— **扫不到东西不是通过**{D}")
        return 1
    print(f"  tests/e2e/ 下有 {len(文件们)} 份端到端测试")

    mk = os.path.join(根, "Makefile")
    if not os.path.isfile(mk):
        print(f"  {R}❌ 找不到 Makefile{D}")
        return 1
    正文 = open(mk, encoding="utf-8").read()

    # 把每个目标的 recipe 切出来。
    #
    # ⚠️ **第一版用正则切,当场被自己咬了。** 写的是
    #     rf"^{目标}:.*?$(.*?)(?=^\S.*?:|\Z)"
    # 意思是「切到下一个行首非空白且带冒号的行」。而 Makefile 里的**注释行**
    # 也是行首非空白、也带冒号(比如 `# ... 日志:/tmp/aimc-worker.log`),
    # 于是 `progress` 那一段在第一条注释处就被截断了 ——
    # 判据报「16 份测试都漏在 progress」,**而它们一份不少都在里面**。
    #
    # 一条会报一堆假阳性的判据,下一个人会学会忽略它,于是它连真的那次也拦不住。
    # 改成按行归属:Make 的规矩本身就很硬 —— recipe 行以 TAB 开头,
    # 目标行在第 0 列。照这个规矩走,不需要解析器。
    段 = {"test-e2e": [], "progress": []}
    当前 = None
    for 行 in 正文.splitlines():
        if 行.startswith("\t"):                     # recipe 行:归给当前目标
            if 当前 in 段:
                段[当前].append(行)
            continue
        if 行[:1] in ("#", "", " "):                 # 注释/空行/续行:不改变归属
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", 行)
        if m:
            名 = m.group(1)
            # `.PHONY:` 这种伪目标不是我们要的段
            当前 = 名 if not 名.startswith(".") else None
    for 名 in ("test-e2e", "progress"):
        if not 段[名]:
            print(f"  {R}❌ Makefile 里 `{名}` 这个目标是空的或找不到 —— "
                  f"这条判据靠它定位,**定位不到不是通过**{D}")
            return 1
        段[名] = "\n".join(段[名])

    # ── 还要验第三件:**CI 版那个名单也不许漏人** ──────────────────────
    #
    # ⚠️ 2026-10-01 加的。`test-e2e-ci` 只跑「不花钱、不要本地模型」的那些,
    # 而排掉哪几份是写在 `Makefile` 的 `E2E_CI` / `E2E_CI_JS` 里的 ——
    # **一个新测试会从两个名单之间漏掉**:
    # 加进了 `test-e2e`(所以本地跑得到)、没加进 `E2E_CI`(所以 CI 不跑它),
    # 而**两边都是绿的**。
    # > 排掉一份是个决定,**漏掉一份是个事故** —— 而它们在 Makefile 上长得一样。
    #
    # 所以:每一份要么在 `E2E_CI`/`E2E_CI_JS` 里,要么在下面这张
    # **写明理由**的 CI 跳过表里。
    CI跳过 = {
        "test_knowledge_flow.py":
            "第 ④ 组**会真调一次 Claude 精排**(月租额度)—— CI 里没凭据,"
            "而「CI 只跑不花钱的」是这个项目的规矩",
        "test_knowledge_write_flow.py":
            "第 ⑥ 条同上(真调 Claude 精排)",
        "test_upload_page_firefox.py":
            "要可见的 Firefox 窗口 + selenium —— 本地 `make test-browser`",
    }
    CI名单 = ""
    for 变量 in ("E2E_CI", "E2E_CI_JS"):
        m2 = re.search(rf"^{变量} :?=(.*?)(?=\n[A-Za-z#]|\n\n)", 正文, re.M | re.S)
        if not m2:
            print(f"  {R}❌ Makefile 里找不到 `{变量}` —— "
                  f"**定位不到不是通过**{D}")
            return 1
        CI名单 += m2.group(1)

    漏 = []
    跳 = []
    CI漏 = []
    for f in 文件们:
        if f in 例外:
            跳.append((f, 例外[f]))
            continue
        缺 = [名 for 名, t in 段.items() if f not in t]
        if 缺:
            漏.append((f, 缺))
        if f not in CI名单 and f not in CI跳过:
            CI漏.append(f)

    幽灵CI = [f for f in CI跳过 if f not in 文件们]
    if 幽灵CI:
        print(f"  {R}❌ CI 跳过表里这几个文件不存在了:{幽灵CI}{D}")
        return 1
    if CI跳过:
        print(f"  {Y}⚠️ CI 里**明说不跑**的 {len(CI跳过)} 份"
              f"(**点名跳过,不是没看见**):{D}")
        for f, 为什么 in CI跳过.items():
            print(f"     · {f} —— {为什么}")
    if CI漏:
        print(f"\n  {R}❌ 这 {len(CI漏)} 份**既不在 CI 名单里,也没写明为什么不跑**:{D}")
        for f in CI漏:
            print(f"     {f}")
        print(f"     加进 Makefile 的 `E2E_CI`/`E2E_CI_JS`,"
              f"或者写进这个脚本的 `CI跳过` 并**说清为什么**。")
        print(f"     ⚠️ **排掉一份是个决定,漏掉一份是个事故** ——"
              f"而它们在 Makefile 上长得一样:")
        print(f"     加进了 `test-e2e`(本地跑得到)、没加进 `E2E_CI`(CI 不跑它),"
              f"**两边都是绿的**。")
        return 1

    # ⚠️ 例外一律**打印出来**。一个静悄悄的例外名单,和没有判据差不多。
    if 跳:
        print(f"  {Y}⚠️ 明写的例外 {len(跳)} 份(**点名跳过,不是没看见**):{D}")
        for f, 为什么 in 跳:
            print(f"     · {f} —— {为什么}")
    # 例外名单里写了、而文件已经没了 → 名单本身过期了,也要报。
    幽灵 = [f for f in 例外 if f not in 文件们]
    if 幽灵:
        print(f"  {R}❌ 例外名单里这几个文件已经不存在了:{幽灵}{D}")
        print(f"     一个指向不存在文件的例外,会在下一个人重用这个名字那天悄悄放行它。")
        return 1

    if 漏:
        print(f"\n  {R}❌ {len(漏)} 份测试没在两处都登记{D}")
        for f, 缺 in 漏:
            print(f"     {f}  缺:{', '.join(缺)}")
        print(f"\n     · 漏在 `test-e2e` → 门禁根本不跑它,而门禁是绿的")
        print(f"     · 漏在 `progress` → 它打过的路由**不进账本**,"
              f"于是那几条接口被记成「已实现未验」")
        print(f"       (这件事真发生过一次:「验过」少算 5 条,"
              f"**而报告自己看起来完全正常**)")
        print(f"     真不该进清单的,写进这个脚本的 `例外` 并**说清为什么**。")
        return 1

    print(f"\n  {G}✅ {len(文件们) - len(跳)} 份测试在 `test-e2e` 和 `progress` "
          f"两处都登记了{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
