#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门禁外的检查,多久没跑了 —— **「没人跑」和「跑过没事」必须分得开。**

    python3 tools/runlog_check.py            # 报状态(不拦门禁)
    python3 tools/runlog_check.py --记 <脚本>  # 记一次成功运行

## 这条是怎么来的

2026-09-21:`tools/determinism_check.py --真建两次` **从来没成功跑起来过**。
那一段用的 `quote(t.*)` 不是合法 SQLite 语法,一跑就抛异常。
它是「重建可复现」最深的那道网,注释写了二十行,标着
「改完造数据的脚本要手动跑一次」—— 于是没人跑,于是:

> **它既没红过,也没绿过。它只是静静地抛异常。**

而它要是能跑,同一天查出来的那个 `abs(hash(sku编码))`
(每重建一次 659 个 SKU 的供应商编码全换一批)**早就被抓到了**。

## 为什么不是「都塞进门禁」

这几个脚本待在门禁外都有正当理由,而且每条都不一样:

    要联网          verify_sources.py —— 放进门禁会变成随机拦路
    要花钱          评测那几个 —— 要凭据、结果有波动
    要几分钟        determinism_check --真建两次、bench.py
    要人手起服务    pg_e2e.py / mysql_e2e.py / multistore_e2e.py

强行塞进去的下场是门禁变慢变脆,然后有人把它整个关掉 —— **那才是最糟的**。

## 判据:不拦门禁,只是不让它隐形

每次跑成功,往 `.fakedata/运行史.json` 记一条。这个检查只做三件事:

  · 把「上次成功跑是什么时候」摆出来,**从没跑过的单独标红字**
  · 超过 30 天没跑的提醒一句
  · **记录里有、而脚本已经不在了的,要报出来** —— 否则记录会替一个
    早就删掉的脚本一直说「30 天前跑过」

⚠️ 它本身**不报失败**(`rc` 永远是 0)。一个会因为「你最近没手动跑」
而拦住提交的门禁,会在第三天被人绕过去。它要的是**看得见**,不是拦住。
"""
import datetime, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ⚠️ **不能放 `.fakedata/`** —— 那是输出目录(gitignore,随时清掉)。
# 运行史是**跨时间的事实**:谁在什么时候跑成功过。清掉之后每个新克隆都显示
# 「从没跑过」,而那和真的从没跑过长得一模一样 —— 这个检查存在的理由就没了。
# (同一个坑今天在锚定那边踩过一次,钉子表当时也放错了目录。)
记录 = os.path.join(ROOT, "tools", "运行史.json")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

咬合 = [
    ("把某个门禁外脚本的运行记录删掉(它该显示「从没跑过」)", "从没成功跑过的"),
    ("往记录里加一个已经不存在的脚本", "记录里的脚本都还在"),
]

# 这些**不算**门禁外的检查 —— 它们是被别人调用的库,或者就是这个检查自己
不算 = {"generalize.py", "stability.py", "runlog_check.py"}

# ⚠️ **在门禁里、但有一条支路不在的**,要单独列出来。
# 这正是 `determinism_check.py` 的形状:秒级那半进了门禁(天天跑、天天绿),
# 而 `--真建两次` 那半要两分钟、只能手动跑 —— 于是它**看起来是被门禁管着的**,
# 实际上最深的那道网一次都没跑起来过。
# 「这个脚本在门禁里」和「这个脚本的每一条支路都在门禁里」是两回事。
支路 = {
    "tools/determinism_check.py --真建两次":
        "真的建两次库逐行比(约 4 分钟)。门禁里跑的是扫写法那半 —— "
        "扫写法只抓得到你已经知道的那几种写法,漏掉的只有真建两次看得见",
}


def 门禁外的检查():
    """扫出「明说不进门禁 / 要手动跑」的脚本。

    **从代码里现读,不在这儿手抄一份。** 手抄的话,别人新写一个手动脚本,
    这份清单不会跟着变 —— 于是新加的那个不受这条管,而检查照样报绿。
    """
    在门禁里 = set()
    sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    for m in re.findall(r"run .*?([\w/]+\.py)", sh):
        在门禁里.add(os.path.basename(m))
    出 = []
    for d in ("tools", "fakedata", "backend", "agent"):
        p = os.path.join(ROOT, d)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            if not f.endswith(".py") or f in 在门禁里 or f in 不算:
                continue
            t = open(os.path.join(p, f), encoding="utf-8").read()
            if re.search(r"不进 check\.sh|不进门禁|手动跑|人手动|由人手动", t):
                出.append(f"{d}/{f}")
    return 出


def 读():
    if not os.path.isfile(记录):
        return {}
    return json.load(open(记录, encoding="utf-8")).get("跑过", {})


def 记(脚本):
    os.makedirs(os.path.dirname(记录), exist_ok=True)
    d = {"说明": "门禁外的检查每次成功跑完记一条。**这个文件不拦任何东西**,"
                 "它只是让「没人跑」和「跑过没事」分得开。",
         "跑过": 读()}
    # 真实时钟:记的就是「人什么时候跑的它」,这个值本来就该是真实时间
    d["跑过"][脚本] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    json.dump(d, open(记录, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 记下:{脚本} 于 {d['跑过'][脚本]}")
    return 0


def main():
    if "--记" in sys.argv:
        return 记(sys.argv[sys.argv.index("--记") + 1])
    外 = 门禁外的检查() + sorted(支路)
    史 = 读()
    今 = datetime.date.today()          # 真实时钟:算「多久没跑了」本来就要拿今天比
    print("门禁外的检查,多久没跑了")
    print(f"  扫到 {len(外)} 个(从代码里现读,不手抄)\n")
    没跑过, 旧了 = [], []
    for s in 外:
        t = 史.get(s)
        if s in 支路:
            print(f"     ↳ {支路[s]}")
        if not t:
            没跑过.append(s)
            print(f"  {R}⬜ 从没跑过{D}  {s}")
            continue
        天 = (今 - datetime.date.fromisoformat(t[:10])).days
        if 天 > 30:
            旧了.append(s)
            print(f"  {Y}🕐 {天} 天前{D}   {s}  ({t})")
        else:
            print(f"  {G}✅ {天} 天前{D}   {s}  ({t})")

    僵 = [s for s in 史 if s not in 外]
    print()
    if 没跑过:
        print(f"  ⚠️ **{len(没跑过)} 个从没成功跑过** —— 「没人跑」和「跑过没事」"
              f"在任何地方都看不出区别。`determinism_check --真建两次` 就是这么"
              f"**既没红过也没绿过**地躺了很久,而它能抓的那个 bug 一直在库里")
    if 旧了:
        print(f"  🕐 {len(旧了)} 个超过 30 天没跑")
    if 僵:
        print(f"  ⚠️ 记录里有、而脚本已经不在了:{'、'.join(僵)} —— "
              f"**它会替一个删掉的脚本一直说「跑过」**,该清掉")
    print(f"\n  ℹ️ 这个检查**永远不报失败** —— 一个会因为「你最近没手动跑」"
          f"而拦住提交的门禁,第三天就会被人绕过去。它要的是看得见,不是拦住。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
