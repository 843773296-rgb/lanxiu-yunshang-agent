#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态机登记表 —— **状态流转的唯一来源**。

## 为什么状态机要单独登记

规格 §11.5 画了训练任务的状态图,还附了两句很重的话:

  · 「**状态待核实**是同步不确定标记,**不代表任务已结束**」
  · 「取消请求与自然完成并发时,**保留真实最终状态及取消未生效原因**;
     UI 不强行覆盖为「已取消」」

这两句说的是同一件事:**「我不知道」必须是一个能表达出来的状态**,
不能被塞进「失败」,也不能被塞进「已取消」。

> 一个把「查不到供应商状态」显示成「已失败」的系统,会让人去重跑一次 ——
> 而那次重跑可能是在原任务还在烧 GPU 的时候。

所以这里每条状态机都要求:**终态要标出来**,而且**「不确定」不算终态**。
"""


def S(名, 中文, 状态, 起点, 终态, 流转, 备注=(), 中文状态=None):
    """`中文状态` 只给显示用。

    ⚠️ **状态 ID 用规格给的那个词**:编排域(执行运行 / 步骤 / 工具调用)的状态在
    Workflow/Agent 规格 §16.4 里是英文标识(`queued` / `reconciling` / `incomplete`),
    而且它们会**原样出现在 API 的 execution_status 字段里**。
    翻译成中文再存,就等于在契约和接口之间插了一张对照表 ——
    而那张表哪天漏一行,漏掉的那个状态会变成一个谁也认不出的字符串。
    老的那几条状态机(训练 / 索引 / 发布)保持中文,它们的状态没有出现在规格的字段里。
    """
    未标 = [x for x in 状态 if 中文状态 and x not in 中文状态]
    if 中文状态 and 未标:
        raise ValueError(f"{名} 给了中文状态表但漏了 {未标} —— 漏掉的会在界面上显示成英文 ID")
    return dict(名=名, 中文=中文, 状态=list(状态), 起点=起点, 终态=list(终态),
                流转={k: list(v) for k, v in 流转.items()}, 备注=list(备注),
                中文状态=dict(中文状态 or {}))


状态机表 = [
    # ── 训练任务(规格 §11.5 那张图)────────────────────────────────
    S("training_job", "训练任务",
      ["草稿", "校验中", "排队中", "启动中", "训练中", "产物校验中",
       "已完成", "失败", "取消请求中", "已取消", "状态待核实"],
      起点="草稿",
      终态=["已完成", "失败", "已取消"],
      流转={
          "草稿": ["校验中"],
          "校验中": ["排队中", "失败"],
          "排队中": ["启动中", "取消请求中", "失败"],
          "启动中": ["训练中", "取消请求中", "失败", "状态待核实"],
          "训练中": ["产物校验中", "取消请求中", "失败", "状态待核实"],
          "产物校验中": ["已完成", "失败"],
          # ⚠️ 取消请求中**可以走回真实终态** —— 取消和自然完成会并发,
          # 那时候真实结果是「已完成」,不是「已取消」(§11.5)
          "取消请求中": ["已取消", "已完成", "失败", "状态待核实"],
          # 「状态待核实」**不是终态**:要靠外部 ID / 幂等键查回真实状态
          "状态待核实": ["训练中", "产物校验中", "已完成", "失败", "已取消"],
          "已完成": [], "失败": [], "已取消": [],
      },
      备注=["「状态待核实」不代表结束 —— 供应商超时后先按外部 ID 查,避免重复训练",
            "取消未生效时要留下原因,UI 不许显示成「已取消」",
            "**训练完成只代表得到产物** —— 还要登记、兼容检查、评测、部署、发布"]),

    # ── 后台任务通用(入库 / 评测 / 导出 / 部署)────────────────────
    S("job", "后台任务",
      ["排队中", "执行中", "已完成", "失败", "取消请求中", "已取消", "状态待核实"],
      起点="排队中",
      终态=["已完成", "失败", "已取消"],
      流转={
          "排队中": ["执行中", "取消请求中", "失败"],
          # 执行中 → 排队中 是**重试**:租约到期被别人接走,不算失败
          "执行中": ["已完成", "失败", "排队中", "取消请求中", "状态待核实"],
          "取消请求中": ["已取消", "已完成", "失败"],
          "状态待核实": ["执行中", "已完成", "失败", "已取消"],
          "已完成": [], "失败": [], "已取消": [],
      },
      备注=["**重复投递是正常故障场景**,worker 必须幂等(§17.1)",
            "关闭页面不会终止任务(§4)"]),

    # ── 索引构建 ────────────────────────────────────────────────
    S("index_build", "索引构建",
      ["排队中", "解析中", "切片中", "向量化中", "写索引中", "已就绪",
       "失败", "已取消"],
      起点="排队中",
      终态=["已就绪", "失败", "已取消"],
      流转={
          "排队中": ["解析中", "已取消", "失败"],
          "解析中": ["切片中", "失败", "已取消"],
          "切片中": ["向量化中", "失败", "已取消"],
          "向量化中": ["写索引中", "失败", "已取消"],
          "写索引中": ["已就绪", "失败"],
          "已就绪": [], "失败": [], "已取消": [],
      },
      备注=["**换了 Embedding 模型要先校验维度兼容**,不能混进旧索引",
            "失败要说清卡在哪一步 —— 「入库失败」这四个字不够人去修"]),

    # ── 数据集版本 ──────────────────────────────────────────────
    S("dataset_version", "数据集版本",
      ["编辑中", "审核中", "已冻结", "已弃用"],
      起点="编辑中",
      终态=["已弃用"],
      流转={
          "编辑中": ["审核中", "已弃用"],
          "审核中": ["编辑中", "已冻结", "已弃用"],
          # ⚠️ 已冻结**不能回到编辑中**:冻结版本不能被样本后续编辑改变(§18)
          "已冻结": ["已弃用"],
          "已弃用": [],
      },
      备注=["**已冻结不可回退到编辑** —— 能改的冻结不是冻结",
            "分集在冻结时定,group_id 不许跨分集"]),

    # ── 发布 ────────────────────────────────────────────────────
    S("release", "发布清单",
      ["候选", "测试部署中", "待审核", "已审核", "已发布", "已回滚", "已驳回"],
      起点="候选",
      终态=["已回滚", "已驳回"],
      流转={
          "候选": ["测试部署中", "已驳回"],
          "测试部署中": ["待审核", "候选", "已驳回"],
          "待审核": ["已审核", "已驳回"],
          "已审核": ["已发布", "已驳回"],
          # 已发布可以被下一次发布顶替,也可以回滚
          "已发布": ["已回滚"],
          "已回滚": [], "已驳回": [],
      },
      备注=["**依赖冻结 → 测试部署 → 审核 → 环境指针切换 → 回滚**(§17.4-9)",
            "**禁止 API 参数任意指定生产外的未审版本**",
            "生产指针切换要原子"]),

    # ── 样本审核 ────────────────────────────────────────────────
    S("sample_review", "样本审核",
      ["待审", "通过", "打回", "弃用"],
      起点="待审",
      终态=["弃用"],
      流转={"待审": ["通过", "打回", "弃用"],
            "打回": ["待审", "弃用"],
            "通过": ["待审", "弃用"],      # 发现问题可以退回重审
            "弃用": []},
      备注=["通过之后还能退回重审 —— 但退回要留痕(审计)"]),

    # ═══ Workflow 与 Agent 后台规格 §16.4 的增量 ═════════════════════
    #
    # ## 这条状态机里有四个「看起来能合并、但合并就出事」的区分
    #
    # ① **`succeeded` ≠ 任务达标。** `succeeded` 只表示「定义要求的执行和
    #    确定性输出检查过了」。里面的事实对不对,另存 quality_evaluation_status。
    #    合并的后果:一份 JSON Schema 合法但数字全是编的报告,状态是「成功」。
    #
    # ② **`incomplete` 不是 `failed`。** 允许部分结果、达到回合上限、预算用完 ——
    #    这些都是「跑完了但没达标」,和「炸了」不是一回事,处置也不同
    #    (前者看 completion_reason 决定要不要放宽上限,后者去查错误)。
    #
    # ③ **`cancel_requested` 不是 `cancelled`。** 规格 §12.3:
    #    「停止新调度并尝试取消在途请求;**等待执行器核实,不能承诺撤销已发生动作**」。
    #    点了取消就直接显示「已取消」的系统,会让人以为那次转账没发出去。
    #
    # ④ **`reconciling` 不是终态。** 外部动作状态不明时,**不许用 expired/cancelled
    #    把不确定性藏起来**(§16.4)。它要停在这儿显示「已停止新动作,外部结果待核实」。
    #
    # 前三条合并了会**谎报**,第四条合并了会**让人去重跑一个还在花钱的任务**。
    S("execution_run", "执行运行",
      ["queued", "running", "pause_requested", "paused", "waiting_input",
       "waiting_approval", "reconciling", "cancel_requested",
       "succeeded", "incomplete", "failed", "cancelled", "expired"],
      起点="queued",
      终态=["succeeded", "incomplete", "failed", "cancelled", "expired"],
      流转={
          "queued": ["running", "cancelled", "expired"],
          "running": ["succeeded", "incomplete", "failed", "waiting_input",
                      "waiting_approval", "pause_requested", "cancel_requested",
                      "reconciling", "expired"],
          # 暂停请求中:在途调用未必立即停 —— 它可能直接走到真实终态,
          # 也可能要先核实。**保留「暂停请求」这件事发生过**(§16.4)
          "pause_requested": ["paused", "reconciling", "succeeded", "incomplete",
                              "failed", "waiting_input", "waiting_approval",
                              "cancelled", "expired"],
          "paused": ["queued", "cancelled", "expired"],
          "waiting_input": ["queued", "cancelled", "expired"],
          "waiting_approval": ["queued", "cancelled", "expired"],
          # 核实完了回到运行/等待/暂停,或者查清了就是真实终态。**禁止盲重试**
          "reconciling": ["running", "waiting_input", "waiting_approval", "paused",
                          "succeeded", "incomplete", "failed", "cancelled", "expired"],
          # ⚠️ 取消请求中**能走到 succeeded/failed** —— 取消和自然完成会并发,
          # 「不能仅因点击就终态」(§16.4)
          "cancel_requested": ["cancelled", "succeeded", "incomplete", "failed",
                               "reconciling", "expired"],
          "succeeded": [], "incomplete": [], "failed": [], "cancelled": [],
          "expired": [],
      },
      中文状态={"queued": "排队中", "running": "运行中", "pause_requested": "暂停请求中",
               "paused": "已暂停", "waiting_input": "等待人工输入",
               "waiting_approval": "等待审批", "reconciling": "核实外部状态中",
               "cancel_requested": "取消请求中", "succeeded": "已完成",
               "incomplete": "未完整完成", "failed": "失败", "cancelled": "已取消",
               "expired": "已过期"},
      备注=["**原 Run 不直接改回运行**(§16.4):要继续就是新 Run,保留 parent_run_id",
            "**发布切换只影响新 Run**;但动态撤权、停用和强制停止**即时生效**(§15.6)",
            "继续执行**不把暂停期间更新的 Prompt 静默装入旧 Run**(§12.3)"]),

    # ── 运行步骤(§8:skipped 和 failed 不是一回事)────────────────────
    S("run_step", "运行步骤",
      ["pending", "running", "succeeded", "failed", "skipped", "reconciling",
       "waiting_human", "cancelled"],
      起点="pending",
      终态=["succeeded", "failed", "skipped", "cancelled"],
      流转={
          "pending": ["running", "skipped", "cancelled"],
          "running": ["succeeded", "failed", "waiting_human", "reconciling",
                      "cancelled"],
          "waiting_human": ["running", "failed", "cancelled"],
          "reconciling": ["succeeded", "failed", "cancelled"],
          "succeeded": [], "failed": [], "skipped": [], "cancelled": [],
      },
      中文状态={"pending": "待执行", "running": "执行中", "succeeded": "成功",
               "failed": "失败", "skipped": "未激活(跳过)",
               "reconciling": "核实中", "waiting_human": "等待人工",
               "cancelled": "已取消"},
      备注=["**`skipped` 和 `failed` 不同**(§8):未激活的支路不阻塞条件汇合,"
            "**也不能作为「完成了的工作」计入** —— 把跳过算成成功,"
            "「这次跑过了 8 个节点」这句话就没有意义了",
            "**每次 attempt 是新的一行**,不覆盖旧结果",
            "同一 Run 中已执行节点的输入输出**不可改写**;人工新输入只作为新事件"]),

    # ── 工具调用(§17.3 的「先登记 intent,再调外部,收到响应再登记结果」)──
    #
    # 这条状态机的形状就是那三步。**中间那一步是会死人的地方**:
    # 进程在「已提交」和「已响应」之间崩溃,外部系统可能已经做了那件事。
    # 这时候唯一正确的动作是**去查**(needs_verification),不是重发。
    S("tool_invocation", "工具调用",
      ["intent_registered", "submitted", "succeeded", "failed", "rejected",
       "needs_verification", "cancelled"],
      起点="intent_registered",
      终态=["succeeded", "failed", "rejected", "cancelled"],
      流转={
          # 还没提交就被拒(Schema / 授权 / 缺确认)—— 外部什么都没发生
          "intent_registered": ["submitted", "rejected", "cancelled"],
          "submitted": ["succeeded", "failed", "needs_verification"],
          # 查清了就落到真实结果;查不出来**停在这儿**,不许自动重发
          "needs_verification": ["succeeded", "failed", "cancelled"],
          "succeeded": [], "failed": [], "rejected": [], "cancelled": [],
      },
      中文状态={"intent_registered": "已登记意图", "submitted": "已提交外部",
               "succeeded": "成功", "failed": "失败", "rejected": "被拒绝",
               "needs_verification": "待核实", "cancelled": "已取消"},
      备注=["**拒绝执行要返回安全的拒绝原因,不能伪造成功结果**(§10.3)",
            "**`rejected` 和 `failed` 分开**:前者是我们没让它做,"
            "后者是做了没成 —— 对 Agent 来说这两件事该有不同的下一步",
            "**needs_verification 不是终态**:没有外部幂等或查询能力时,"
            "承诺不了 exactly-once,那就停在待核实,**禁止自动重复不可逆动作**"]),

    # ── 人工请求(§12.2)────────────────────────────────────────────
    S("human_request", "人工请求",
      ["pending", "approved", "rejected", "info_requested", "expired", "cancelled"],
      起点="pending",
      终态=["approved", "rejected", "expired", "cancelled"],
      流转={
          "pending": ["approved", "rejected", "info_requested", "expired",
                      "cancelled"],
          # 「要求补充」之后 revision 前进,再回到待处理 —— 旧批准对新参数无效
          "info_requested": ["pending", "expired", "cancelled"],
          "approved": [], "rejected": [], "expired": [], "cancelled": [],
      },
      中文状态={"pending": "待处理", "approved": "已批准", "rejected": "已驳回",
               "info_requested": "要求补充", "expired": "已过期",
               "cancelled": "已取消"},
      备注=["**一次请求只能被处理一次**:唯一约束落在 (request_id, request_revision) 上 ——"
            "两个审批者同时点批准,第二个撞唯一键,返回冲突和最新状态(§12.2)",
            "**`approved` 是终态,但它不等于「已执行」**:真正执行时还要再查一遍"
            "权限和工具当前可用性。权限撤回之后,老批准记录**不能**恢复写操作(§12.3)",
            "**过期的批准不许生效**(附录 C.2「审批超时」):"
            "点批准的那一刻要拿 expires_at 和当前时间比,不是建请求的时候比"]),
]

_按名 = {s["名"]: s for s in 状态机表}

# 「我不知道」类状态:**不是终态**,必须能查回真实状态。
#
# ⚠️ 这张清单**必须跟着新状态机一起长**。它是「不确定不许当终态」那条检查的输入 ——
# 漏登记一个,那条检查就不看它了,而检查照样是绿的。
# 加一条编排状态机而忘了往这儿加一个词,后果是:一个把「外部结果查不到」
# 当成终态的 Run 能安静地通过所有检查。
不确定状态 = [
    "状态待核实",          # 训练 / 后台任务:供应商超时后按外部 ID 查
    "reconciling",         # 执行运行:已停止新动作,外部结果待核实(§16.4)
    "needs_verification",  # 工具调用:提交了但没收到响应,去查,**不重发**
]

# 「跑完了但没达标」的原因(§16.4)。**和 failed 分开** ——
# 一个因为预算用完而停下的任务,处置是「要不要加预算」;
# 一个因为缺证据而停下的任务,处置是「检索配错了还是资料真没有」。
# 压成一个 failed,这两件事就都变成「去看日志」。
完成原因 = {
    "budget_exceeded": "预算用完(**未知计价的部分单列,不按 0 算**)",
    "max_turns": "达到模型回合上限 —— **达到上限停止 ≠ 完成任务**(§10.2)",
    "max_tool_attempts": "达到工具调用上限",
    "deadline": "超过总执行期限(墙钟)",
    "missing_evidence": "必要证据不足,按输出契约不能算完成",
    "partial_allowed": "配置显式允许返回部分结果",
    "user_cancelled": "人取消的",
    "permission_revoked": "运行中权限被撤回 —— 剩下的动作不许做",
    "tool_unavailable": "必需的工具不可用",
    "no_progress": "重复无进展(**要写清依据**,不能只凭「调用了两次」)",
}


def 找(名):
    if 名 not in _按名:
        raise KeyError(f"没有这个状态机:{名} —— 现有 {list(_按名)}")
    return _按名[名]


def 能不能走(名, 从, 到):
    """能不能从一个状态走到另一个。**认不出的状态当场抛**,不返回 False ——
    返回 False 的话,拼错一个状态名就等于「这条路不通」,而那是另一回事。"""
    m = 找(名)
    for x in (从, 到):
        if x not in m["状态"]:
            raise ValueError(f"{名} 没有这个状态:{x!r} —— 现有 {m['状态']}")
    return 到 in m["流转"].get(从, [])
