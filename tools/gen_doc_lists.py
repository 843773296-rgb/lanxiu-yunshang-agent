#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成产品说明里的 MCP / Hook / Skill 三张清单。

⚠️ 分组是手写的,所以**必须对账**:每个工具恰好属于一组,没有漏掉的、没有编出来的。
手写清单会悄悄丢工具,而丢了之后文档看起来完全正常 —— 这正是这个项目反复栽的那类。
"""
import argparse, io, os, pathlib, re, sys

# ⚠️ **从这个脚本自己的位置算根目录,不写死某个检出的路径。**
# 原来这一行是 `pathlib.Path.home() / "Desktop/澜绣云裳agent/backend"` ——
# 硬编码指向**主检出**。于是在另一个 worktree 里跑它,读的是别人那棵树的代码:
# > 一个「这个检出的工具清单」和一个「隔壁检出的工具清单」,
# > **在生成出来的那张表上长得一模一样。**
# 而两棵树的工具数不同时,它会安静地给出另一棵树的答案。
这里 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(这里)
sys.path[:0] = [os.path.join(根, "backend"), os.path.join(根, "knowledge"), 根]
import api

写 = set(api.WRITE_TOOLS)

# ⚠️⚠️ **归属不在这儿,在 `backend/domains.py`** —— 2026-10-23 下午改的。
#
# 上午这里还是一张**手写的**分组表,而它漂到了:覆盖 41 个、库里真有 79 个,
# 漏 38 个(报修 / 签收 / 下单 / 经营报告 / 差评 / 工厂回传整族全不在)。
# 我把它补齐成 17 组,当天下午并行会话把 MCP 按 8 个业务领域拆开 ——
# **那份归属才是唯一来源**(`domains.领域`,服务入口 / 角色名单 / 提示词前缀都从它取)。
# 于是这里不再自己分组:**手写的那张表就是会漂,上午刚证过一次。**
#
# 📌 **只留下会漂的那一半和不会漂的那一半的分界**:
#     工具**归谁** —— 会漂(每加一个工具就可能漏登记)→ 从 `domains.py` 现读
#     八个领域的**中文名** —— 不漂 → 留在这儿一张极小的映射
#   并配一条断言:`domains.领域` 里每个领域都必须有中文名 ——
#   他哪天加第九个领域会**当场红**,而不是安静地少一节。
# ⚠️ 这份清单 2026-10-23 下午**被我自己删掉过一次** —— 把分组改成读 `domains.py` 时,
#    替换的那一段正好把它一起吞了,`bite_check` 的棘轮当场红在
#    「没有咬合记录的脚本不超过 0 个」。**那条棘轮值这个钱。**
咬合 = [
    ("把 backend/domains.py 里某个工具从它的领域里去掉(它从此谁也不归)", "对账不过"),
    ("把产品说明那张表里某个领域的小标题删掉", "产品说明里那张工具表和代码对不上"),
]

import domains as _D

领域中文名 = {
    "knowledge":   "知识与工艺",
    "customer":    "客户与会员",
    "commerce":    "商品与交易",
    "fulfillment": "生产与交付",
    "finance":     "财务与结算",
    "service":     "售后与评价",
    "work":        "任务与排班",
    "analytics":   "经营分析",
}
缺名 = [d for d in _D.领域 if d not in 领域中文名]
if 缺名:
    sys.exit(f"❌ `domains.领域` 里这几个领域没有中文名:{缺名} —— "
             f"加了新领域就要在 `tools/gen_doc_lists.py` 的 `领域中文名` 里补一行,"
             f"否则产品说明里会**安静地少一节**")
多名 = [d for d in 领域中文名 if d not in _D.领域]
if 多名:
    sys.exit(f"❌ `领域中文名` 里有 `domains.领域` 没有的:{多名} —— 领域删了名字没删")

# 按领域把 shop 那一段分组:取每个领域和 SHOP_SCHEMAS 的交集,
# **顺序照 `domains.领域` 的顺序**(它是唯一来源,连次序也从它来)。
分组 = {}

全部 = [t["name"] for t in api.SHOP_SCHEMAS]
for 域, 名们 in _D.领域.items():
    这组 = [n for n in 名们 if n in set(全部)]
    if 这组:
        分组[f"{领域中文名[域]}(`{域}`)"] = 这组
在组里 = [n for g in 分组.values() for n in g]
漏 = [n for n in 全部 if n not in 在组里]
编的 = [n for n in 在组里 if n not in 全部]
重 = [n for n in set(在组里) if 在组里.count(n) > 1]
if 漏 or 编的 or 重:
    sys.exit(f"❌ 对账不过 —— 漏了 {漏} / 编出来的 {编的} / 重复 {重}")
print(f"✅ shop 对账通过:{len(全部)} 个工具,{len(分组)} 组,一个不漏不重", file=sys.stderr)


def 一行(t):
    d = " ".join((t.get("description") or "").split())
    d = re.sub(r"\*\*(.+?)\*\*", r"\1", d)
    return f"| {'✍️ ' if t['name'] in 写 else ''}`{t['name']}` | {d[:46]} |"


S = {t["name"]: t for t in api.SHOP_SCHEMAS}
out = []
out.append(f"### 4.3 MCP:三个服务,{len(全部)+len(api.KB_SCHEMAS)+len(api.SCHEMAS)} 个工具\n")
out.append("**为什么分三个而不是一个:** 给一个角色多余的工具,代价不是浪费,"
           "是**它会去用**。工匠不需要看到客户资产,顾问不需要看到工单调度。"
           "分服务之后,挂哪几个是一次配置,不是每次提醒模型「别用那个」。\n")
out.append(f"✍️ 标记的是**写工具**(共 {len(写)} 个),要过白名单 + 预演 + 四道闸,见 4.6。\n")

out.append(f"#### `kb` · 知识库({len(api.KB_SCHEMAS)} 个)—— 回答「能不能做、怎么做、多少钱、多久」\n")
out.append("| 工具 | 干什么 |\n|---|---|")
out += [一行(t) for t in api.KB_SCHEMAS]
out.append("")

out.append(f"#### `shop` · 门店业务({len(api.SHOP_SCHEMAS)} 个)\n")
for 组, names in 分组.items():
    out.append(f"**{组}**\n")
    out.append("| 工具 | 干什么 |\n|---|---|")
    out += [一行(S[n]) for n in names]
    out.append("")

out.append(f"#### `task` · 任务与财务排查({len(api.SCHEMAS)} 个)\n")
out.append("| 工具 | 干什么 |\n|---|---|")
out += [一行(t) for t in api.SCHEMAS]
out.append("")

生成的 = "\n".join(out).rstrip("\n")

# ── 把它写进 / 对账进 产品说明的 4.3 那一节 ──────────────────────────
#
# ⚠️ **原来这个脚本只写 `/tmp/mcp_list.md` 然后 print 前 400 字。**
# 也就是说:它算得出正确答案,**而把答案贴进文档这一步靠人记得**。
# 后果量过:2026-10-23 文档那张表列了 48 个、而库里 79 个,**漏 31 个**,
# 漏掉的是整族能力(报修 / 签收 / 下单 / 经营报告 / 差评 / 工厂回传)。
# 而它就贴在「shop 工具 79 个」这个**对账过的**标题下面 ——
# > 标题说 79、表里 48,**读的人只会相信表**。
# 一份漏掉整个报修族的工具清单,会让人以为系统不能报修:**比没有清单更糟**。
#
# 所以现在:**默认只对账**(`--check` 的行为,给门禁用),`--写` 才动文档。
# 「算得出」和「贴进去了」是两件事,而这个项目为这个形状栽过很多次
# (`allowed_tools` 不是白名单 · `.pyc` 的「防止产生」≠「防止使用」·
#  规矩写在提示词里 ≠ 结构上拦住 · 一份没进门禁的自测 = 一份不存在的自测)。
说明 = os.path.join(根, "澜绣云裳agent-产品说明.md")
起 = "### 4.3 MCP"
止 = "\n### 4.4"


def 取现文():
    t = io.open(说明, encoding="utf-8").read()
    i = t.index(起)
    j = t.index(止, i)
    return t, i, j, t[i:j].rstrip("\n")


ap = argparse.ArgumentParser()
ap.add_argument("--写", action="store_true", help="把 4.3 那一节覆盖成生成的内容")
a = ap.parse_args()

t, i, j, 现文 = 取现文()
if a.写:
    if 现文 == 生成的:
        print("✅ 产品说明里那一节已经和代码一致,一个字都不用改")
    else:
        io.open(说明, "w", encoding="utf-8").write(t[:i] + 生成的 + "\n" + t[j:].lstrip("\n"))
        print(f"✅ 已把产品说明 4.3 那一节覆盖成生成的内容"
              f"({len(现文.splitlines())} 行 → {len(生成的.splitlines())} 行)")
        print("📌 记得重跑 `python3 tools/make_readme.py`(README 的那一节从这里来)")
    raise SystemExit(0)

if 现文 == 生成的:
    print(f"✅ 产品说明里那张工具表和代码对得上(shop {len(全部)} 个 / {len(分组)} 组)")
    raise SystemExit(0)

import difflib
列出的 = set(re.findall(r"`([a-z_][a-z0-9_]*)`", 现文))
漏在文档里 = sorted(x for x in 全部 if x not in 列出的)
print(f"❌ 产品说明里那张工具表和代码对不上 —— 跑 `python3 tools/gen_doc_lists.py --写`")
if 漏在文档里:
    print(f"   文档那张表里**找不到的 {len(漏在文档里)} 个工具**:{漏在文档里}")
    print(f"   ⚠️ 而紧跟在它上面的「shop {len(全部)} 个」那个数是对账过的 —— "
          f"**标题说 {len(全部)}、表里少 {len(漏在文档里)} 个,而读的人只会相信表**")
差 = [l for l in difflib.unified_diff(现文.split("\n"), 生成的.split("\n"),
                                      "现文", "生成", lineterm="", n=0)
      if not l.startswith(("---", "+++", "@@"))]
print(f"   共 {len(差)} 行不一样,头几行:")
for l in 差[:6]:
    print(f"     {l[:140]}")
raise SystemExit(1)
