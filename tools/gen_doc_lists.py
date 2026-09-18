#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成产品说明里的 MCP / Hook / Skill 三张清单。

⚠️ 分组是手写的,所以**必须对账**:每个工具恰好属于一组,没有漏掉的、没有编出来的。
手写清单会悄悄丢工具,而丢了之后文档看起来完全正常 —— 这正是这个项目反复栽的那类。
"""
import pathlib, re, sys
sys.path.insert(0, str(pathlib.Path.home() / "Desktop/澜绣云裳agent/backend"))
import api

写 = set(api.WRITE_TOOLS)

分组 = {
    "任务与派工": ["my_tasks", "task_types", "get_task", "dispatch_pool", "team_tasks",
                "assign_task", "dispatch_task", "reassign_task", "finish_task",
                "assign_batch", "dispatch_batch"],
    "排班与复盘": ["week_grid", "monthly_review", "appt_funnel"],
    "会员与审批": ["member_level", "points_ledger", "approval_queue",
                "apply_adjust", "decide_approval", "get_lifecycle", "get_member_priority"],
    "客户与订单": ["get_order", "can_order", "get_wearer", "recovery_queue", "activity_roi",
                "channel_compare"],
    "库存与产能": ["get_stock", "stock_alert", "get_capacity", "get_workorder", "my_workorders"],
    "版师相关":   ["pattern_queue", "grading_audit", "piece_ratios", "set_piece_ratio"],
    "定制与售后": ["fitting_queue", "get_aftersale", "get_maintain", "get_review_queue"],
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
out.append("### 4.3 MCP:三个服务,59 个工具\n")
out.append("**为什么分三个而不是一个:** 给一个角色多余的工具,代价不是浪费,"
           "是**它会去用**。工匠不需要看到客户资产,顾问不需要看到工单调度。"
           "分服务之后,挂哪几个是一次配置,不是每次提醒模型「别用那个」。\n")
out.append("✍️ 标记的是**写工具**(共 9 个),要过白名单 + 预演 + 四道闸,见 4.6。\n")

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

pathlib.Path("/tmp/mcp_list.md").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out)[:400])
