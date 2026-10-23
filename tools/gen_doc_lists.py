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

# ⚠️⚠️ **这张分组表 2026-10-23 补齐过一次,而它漏的不是零碎,是整族能力。**
#
# 当时的账:分组覆盖 41 个、库里真有 79 个,**漏 38 个** ——
# 报修五个、签收四个、下单两个、经营报告五个、差评四个、工厂回传四个全不在。
# 而产品说明里那张表只列了 48 个,**紧跟在「shop 工具 79 个」这个标题下面**:
# > 标题说 79、表里 48,中间差 31 个,**而没有任何东西报出来** ——
# > 「79」那个数是对账过的(`doc_numbers_check` 盯着),那张表没人对账。
# 读的人只会相信表,于是一份漏掉整个报修族的清单,会让人以为系统不能报修。
# **比没有清单更糟。**
#
# 现在这张表的对账进了门禁(`--check`),所以它不会再悄悄漂。
# 📌 **分组按「业务动作」分,不按数据表分** —— 读这份文档的人问的是
# 「这个岗位能干什么」,不是「这个工具读哪张表」。
咬合 = [
    ("把分组表里「报修」那一族整个去掉(四个工具谁也不属于任何一组)", "对账不过"),
    ("把产品说明那张表里「报修」的小标题删掉", "产品说明里那张工具表和代码对不上"),
]

分组 = {
    "任务与派工": ["get_tasks", "task_types",
                "assign_task", "dispatch_task", "reassign_task", "finish_task",
                "assign_batch", "dispatch_batch"],
    "排班与复盘": ["week_grid", "monthly_review", "appt_funnel", "on_shift"],
    "会员与审批": ["get_member", "points_ledger", "approval_queue",
                "apply_adjust", "decide_approval"],
    "客户与方案": ["get_scheme", "get_order", "can_order", "get_wearer",
                "customer_history", "deal_credit"],
    "客户经营与挽回": ["recovery_queue", "revive_list", "churn_watch",
                     "call_opportunity", "ownerless_list", "conversion_rate"],
    "下单 · 量体 · 签收": ["open_order", "confirm_order", "record_measure",
                          "record_pickup", "verify_fit_code", "ratify_complete"],
    "订单流水与取消": ["orders_by_date", "order_log", "cancel_fee"],
    "库存与产能": ["get_stock", "stock_alert", "get_capacity", "get_workorder",
                "my_workorders"],
    # 版师:核占比 / 推档 / 开裁,加上受欢迎与易损(2026-10-22 接上入口)
    "版师相关":   ["pattern_queue", "grading_audit", "set_piece_ratio", "start_cutting",
                "summarize_products", "product_ranking", "wear_risk"],
    "白坯试衣与工厂催单": ["fitting_queue", "factory_chase"],
    "工厂回传与报工": ["delay_pending", "mark_delay_told", "rollback_order",
                     "report_production"],
    "报修": ["create_repair", "decide_repair", "advance_repair", "verify_repair_return"],
    "售后与维保": ["get_aftersale", "get_maintain", "get_review_queue", "record_fitting"],
    "评价与差评": ["bad_ratings", "rating_overview", "close_bad_rating", "service_records"],
    "经营报告": ["store_report", "weekly_revenue", "sales_rank",
               "save_report", "confirm_report", "list_reports"],
    "渠道与活动": ["activity_roi", "channel_compare"],
    "推算与校验": ["plan_for_event", "forecast_growth", "check_write"],
}

全部 = [t["name"] for t in api.SHOP_SCHEMAS]
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
