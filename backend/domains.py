# -*- coding: utf-8 -*-
"""MCP 工具按业务领域归属 —— **唯一来源**(用户 2026-10-23 拍「全部拆」,intent/mcp-domains.md)。

原来 93+ 个工具挤在 kb / task / shop 三个服务里,shop 一个就 79 个;task 名不副实
(真正派单、完成任务在 shop)。看到 `mcp__shop__xxx` 说明不了它是哪个岗位、什么风险的动作。

这里只定**归属**,不改任何工具的行为或权限:八个服务都复用 `api.py` 同一份实现和写入判定。
服务入口(mcp/domain_server.py)、sdk 的角色名单、提示词规矩都从这里取前缀 ——
**同一个工具在两处各写一个前缀,迟早对不上**。

归属的依据(外部《MCP 与 Skill 现状核查及建设方案》第 3 节,按本系统实际工具落地):
  · 看「这个动作是谁的岗位、动的是哪类事实」,不看它读了哪几张表
  · 版师的裁片比例归知识与工艺(核查 3.1:和普通知识查询分开授权 —— 授权仍在写入判定里,不在前缀上)
  · `kb_fit` 拿**具体着装人**的量体去比尺码 —— 归客户(核查 3.1:别让通用知识口扩大客户数据访问)
  · 扣多少退多少(cancel_fee)归财务;业绩归因(deal_credit)归经营分析
"""

领域 = {
    "knowledge": (   # 知识与工艺:制度、工艺、面料、版型、BOM、工期;版师核数
        "kb_lookup", "kb_detail", "kb_combo", "kb_rag", "kb_read", "kb_tables",
        "kb_pattern", "kb_size", "kb_lead", "kb_bom", "get_review_queue",
        "pattern_queue", "grading_audit", "set_piece_ratio",
        "set_grade_diff",
        # 纹样核定(2026-10-27):纹样是**面料和商品知识**,归这个领域。
        # 写口要总部运营 —— 商品是全店共享的,单店改了别的店看不到。
        "motif_todo", "review_motif",
    ),
    "customer": (    # 客户与会员:档案、着装人、量体、会员、商机、生命周期、挽回
        "get_customer", "get_member", "get_wearer", "customer_history", "kb_fit",
        "record_measure", "forecast_growth", "revive_list", "churn_watch",
        "call_opportunity", "ownerless_list", "recovery_queue", "points_ledger",
        "approval_queue", "apply_adjust", "decide_approval",
    ),
    "commerce": (    # 商品与交易:商品、库存、方案、下单、订单
        "get_scheme", "get_order", "get_stock", "stock_alert", "can_order",
        "open_order", "confirm_order", "orders_by_date", "order_log",
        "summarize_products", "plan_for_event",
    ),
    "fulfillment": ( # 生产与交付:产能、工单、报工、工厂回传、延期、白坯、开裁、签收
        "get_capacity", "get_workorder", "my_workorders", "report_production",
        "factory_chase", "delay_pending", "mark_delay_told", "rollback_order",
        "fitting_queue", "record_fitting", "start_cutting", "record_pickup",
        "verify_fit_code", "ratify_complete",
    ),
    "finance": (     # 财务与退款:押金、支付流水、退款轨迹、退订扣费
        "get_deposit", "get_refund_trace", "get_payment_flow", "cancel_fee",
    ),
    "service": (     # 售后与服务:售后事实、差评、维修判责与进度
        "get_aftersale", "get_maintain", "bad_ratings", "service_records",
        "close_bad_rating", "create_repair", "decide_repair", "advance_repair",
        "verify_repair_return",
    ),
    "work": (        # 任务与研判:派单、转派、完成、排班格子、写入规则自检
        "list_tasks", "get_tasks", "task_types", "week_grid", "on_shift",
        "assign_task", "assign_batch", "dispatch_task", "dispatch_batch",
        "reassign_task", "finish_task", "check_write", "monthly_review",
        "start_workflow",   # 发起被接管的工作流(10-24):派活的一种,归任务
        "workflow_replies", # 查那条工作流说了什么、跑到哪了(10-27):和发起配对,归同一处
    ),
    "analytics": (   # 经营分析与报告:统一口径的统计、报告取数 / 保存 / 确认
        "store_report", "save_report", "confirm_report", "list_reports",
        "weekly_revenue", "sales_rank", "conversion_rate", "deal_credit",
        "appt_funnel", "activity_roi", "channel_compare", "rating_overview",
        "product_ranking", "wear_risk",
    ),
}

领域说明 = {
    "knowledge": "知识与工艺", "customer": "客户与会员", "commerce": "商品与交易",
    "fulfillment": "生产与交付", "finance": "财务与退款", "service": "售后与服务",
    "work": "任务与研判", "analytics": "经营分析与报告",
}

# 工具 → 领域(反查表)。一个工具只许出现一次 —— domains_check 验
归属 = {t: d for d, ts in 领域.items() for t in ts}

# ── 旧名兼容 ─────────────────────────────────────────────────────────
# 历史日志、评测结果、记录仪里存的是 `mcp__kb|task|shop__xxx`。**它们不改写**(那是历史),
# 读的时候过一下 `新名()` 就能和现在的名字对上。改写历史的话,「当时调的是哪个」就查不回来了。
旧服务 = ("kb", "task", "shop")


def 短名(全名):
    """`mcp__任何服务__xxx` / `xxx` → `xxx`。"""
    s = str(全名 or "")
    return s.split("__", 2)[2] if s.startswith("mcp__") and s.count("__") >= 2 else s


def 全名(短):
    """`xxx` → `mcp__<领域>__xxx`;不认识的工具原样返回(交给调用方报错,不在这里猜)。"""
    d = 归属.get(短)
    return f"mcp__{d}__{短}" if d else 短


def 新名(名):
    """旧名、新名、短名都认,一律给出现在的全名。历史记录对账用。"""
    return 全名(短名(名))
