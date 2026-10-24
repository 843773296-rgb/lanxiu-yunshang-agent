#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""澜绣桥能做的事 —— **唯一一份名单**(2026-10-24,六条业务工作流要的能力)。

谁读它:
  · models.py 的 bridge_calls CHECK —— 库里只收这些名字(名单外的单根本记不进去)
  · runtime/桥闸.py —— 只读的放行;要批准的必须这次运行里有人工节点批过;**名单外的一律拒**
  · workers/worker.py —— 工作流里选的澜绣工具,在名单里才走桥
澜绣那一侧也有一份执行表(backend/workflow_bridge.py),两边对不对得上由 tools/bridge_tools_check.py 盯着。

为什么分两组而不是「要批准的列一份、其余放行」:那样新加一个写动作只要忘了登进去,
就会**不经核对直接写进澜绣**,而且不报错。现在反过来 —— 不在「只读」里的,要么要批准,要么不认。

名字就是澜绣 api.py 里的工具名;中文名的几个(取转写 / 写跟进 / 订单交付风险 / 召回名单 / 派回访任务)是桥专门做的。
"""

只读 = (
    "取转写",
    # 经营报告
    "store_report", "list_reports",
    # 录音商机 / 客户
    "call_opportunity", "get_customer", "customer_history", "get_stock",
    # 订单交付风险
    "get_order", "order_log", "get_workorder", "factory_chase", "delay_pending",
    "订单交付风险",          # 桥专门做的:这一单的交付风险,规则分档(用户 10-25 拍「全用规则分档」)
    # 差评返修
    "bad_ratings", "service_records", "get_aftersale", "get_maintain",
    # 老客召回
    "revive_list", "churn_watch",
    "召回名单",              # 桥专门做的:促活 × 流失逐人交叉(复用「客户召回」技能第二步的口径)
    # 库存补货
    "stock_alert",
)

要批准 = (
    "写跟进",
    "save_report", "confirm_report",          # 经营报告:存一版 / 店长确认
    "assign_task",                            # 回电 / 处理 / 回访 / 补货跟进,都是派一条任务
    "create_repair", "decide_repair",         # 差评返修:建返修单 / 店长判责(判给顾客要录费用)
    "close_bad_rating",                       # 关差评(没有重新打开的工具)
    "派回访任务",                              # 老客召回:店长勾了的人各派一条电话回电给归属顾问(桥专门做的)
)

全部 = 只读 + 要批准


def 种类(名):
    """'只读' / '要批准' / None(不认)。"""
    if 名 in 只读:
        return "只读"
    if 名 in 要批准:
        return "要批准"
    return None
