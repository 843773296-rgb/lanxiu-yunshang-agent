#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent 运行时 —— **模型提出行动,程序校验、执行、记录和限制**
(规格 §10、§9.5、§9.6、附录 A-4)。

## 这个文件在守的那条线

规格 §2 最后两段说得最清楚:

> 模型输出「调用工具」是**请求**;**真正执行接口、写文件或创建记录的是服务端运行时**。
> 模型输出「完成」是**候选结论**,程序还需核验格式、文件或业务结果。

所以这个循环里有两个地方**绝不能省**:

① 模型说要调工具 → 交给 **`tool_gateway.执行()`**,不自己发请求。
   网关是唯一的门(§16.1),绕过它就等于「这个 Agent 能做什么」没有任何地方说得清。

② 模型说做完了 → 过 **`_核验完成()`**,不直接返回。
   §10.2 那五条区分在这儿落地,其中最贵的一条是:
   「模型输出『我已保存报告』,**必须核对合法 artifact_ref、对象存储记录与文件访问**;
   **缺证据不能标成功**」。

> **一个把「模型说完成了」当成完成的系统,它的成功率数字没有任何含义。**

## 计数为什么要含修复请求

§9.6:「最大模型回合数:**一次模型请求算一回合,包括修复与 fallback 请求**」。
只数「正常」请求的话,一个反复修 JSON 格式的 Agent 可以无限跑 ——
而账单上那些调用是真的。

## 为什么「拒绝」是正常结果

网关拒绝之后,结果**回传给模型**,让它在剩余合法范围内改方案(§12.2)。
但有一条硬规矩:**默认禁止它对同一个被拒绝的副作用不断换说法重复申请**(§12.2)。
这里落成:同一个 (工具名, 参数摘要) 被拒之后再申请一次就停,并写明依据。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "contract"))
import dsl as DS  # noqa: E402
import tool_gateway as G  # noqa: E402

# 模型响应的动作类型。**按提供商的正式动作类型解析,不解析自由文本**(附录 A-4)。
# §10.1:「模型给出普通文字计划,只能显示为计划;
# 没有合法工具请求时**不能自作主张执行文案中的命令**。」
要调工具 = "tool_use"
要问人 = "clarify"
说完成了 = "finish"
只是说话 = "text"


def _动作(响应):
    """认出模型这次要干什么。**认不出的当「只是说话」** ——
    而「只是说话」不会触发任何执行,所以这个兜底方向是安全的。

    ⚠️ 反过来(认不出就猜成工具调用)会让一段恰好长得像命令的文字被执行。
    """
    if not isinstance(响应, dict):
        return 只是说话
    if 响应.get("tool_calls"):
        return 要调工具
    if 响应.get("clarification"):
        return 要问人
    if 响应.get("finish"):
        return 说完成了
    return 只是说话


def _核验完成(候选, 输出Schema, 必要证据, *, 产物在吗, 账本, 必须做的动作=()):
    """模型说完成了 —— **程序来核**。返回 (行不行, [问题])。

    §10.2 那五条区分在这里落地。顺序是从便宜到贵:先查结构,再查证据,最后查外部。
    """
    坏 = []
    # ① 结构:符合 Schema ≠ 事实正确,但**不符合 Schema 连候选都不算**
    错 = G.校验Schema(候选, 输出Schema or {})
    if 错:
        坏.append(f"输出不符合契约:{'; '.join(错[:3])}")
    # ② 必要字段里的证据引用不能空 —— 一个 evidence_refs=[] 的报告
    #    在 Schema 上完全合法
    for 键 in 必要证据 or []:
        v = (候选 or {}).get(键)
        if not v:
            坏.append(f"{键} 是空的 —— **「有出处」不能只是一句话**"
                      f"(§9.4:默认返回带来源的检索结果)")
    # ③ **模型说它保存了文件 → 去看文件在不在**(§10.2 最贵的那一条)
    for ref in (候选 or {}).get("artifacts") or []:
        if not 产物在吗(ref):
            坏.append(f"声明的产物 {ref!r} **实际不存在或读不到** —— "
                      f"「我已保存报告」不算证据(§10.2)")
    # ④ **必须做的动作真的做了吗** —— 判据落在账本上,不听模型说
    for 动作 in 必须做的动作 or []:
        做过 = any(e["工具"] == 动作 and e["状态"] == "succeeded"
                  for e in (账本.条目.values() if 账本 else []))
        if not 做过:
            坏.append(f"任务要求必须执行 {动作},而账本里没有一条成功记录 —— "
                      f"**判据在账本上,不在模型的话里**")
    return (not 坏), 坏


def 跑一个agent(配置, 输入, *, 适配器, 工具目录, 有效范围, 账本=None,
              记事=None, 产物在吗=None, 批准查询=None, run_id="run",
              系统=None):
    """跑一个 Agent 到终止。返回规格 §10.2 点名要保留的那一套。

    `配置` = agent_versions 上那份(task_template / tools / limits / output_schema /
             completion_criteria / incomplete_strategy)。
    `适配器` = {"model": fn(消息们, 工具定义们) -> 响应, <工具适配器名>: fn(参数) -> 结果}
    `产物在吗(ref) -> bool` 由调用方给 —— **运行时不自己判文件在不在**
             (它拿不到对象存储的权限上下文)。
    """
    记事 = 记事 or (lambda 种类, 载荷: None)
    产物在吗 = 产物在吗 or (lambda ref: False)   # **默认「不在」** —— 未知不等于有
    账本 = 账本 if 账本 is not None else G.内存账本()
    限 = dict(配置.get("limits") or {})
    最大回合 = 限.get("max_model_turns", 8)
    最大工具 = 限.get("max_tool_attempts", 12)

    # ── 两套键:配置引用**确切版本**,模型看到的是**名字** ──────────────
    #
    # 规格 §16.3 要求 Agent 版本引用工具的**确切版本**,所以 `配置["tools"]` 里是
    # 版本 ID;而模型按 `name` 发工具请求,所以网关的目录必须按名字建键。
    # **这两套键必须在一个地方显式换算** —— 分散在调用方各自换,
    # 就会出现「worker 按名字建目录、配置按版本引用」这种对不上(栽过一次:
    # 表现是 Agent 一个工具都不用,而人会去改提示词、换模型、调温度)。
    #
    # 约定:`工具目录` 的键和 `配置["tools"]` 里的元素**是同一套**
    # (测试里都是名字,Worker 里都是版本 ID)。这里只负责把它翻成名字键。
    工具定义们, 网关目录 = [], {}
    撞名 = []
    for 引用 in 配置.get("tools") or []:
        键 = 引用.get("tool_version_id") if isinstance(引用, dict) else 引用
        契 = (工具目录 or {}).get(键)
        if 契 is None:
            # **配置里点了一个目录里没有的工具** —— 这在冻结版本时本该被拦住。
            # 能走到这里说明有东西绕过了校验:**报出来,不静默少给一个工具**。
            # 静默少给的表现是「Agent 不会用那个工具」,而人会去改提示词。
            # ⚠️ 上面那个键换算的 bug 正是被这条事件抓到的。
            记事("agent.tool_missing", {"引用": 键,
                                      "目录里有的": sorted(工具目录 or {})[:8]})
            continue
        名 = 契.get("name") or 键
        if 名 in 网关目录:
            撞名.append(名)
        网关目录[名] = 契
        工具定义们.append({"name": 名,
                        "description": 契.get("model_description"),
                        "input_schema": 契.get("input_schema"),
                        # **模型看不见服务端绑定参数**(§9.4)
                        "side_effect_type": 契.get("side_effect_type")})
    if 撞名:
        # 模型按名字调工具 —— 两个版本同名,**它调到哪个取决于字典顺序**。
        记事("agent.tool_name_clash", {"撞了": sorted(set(撞名))})
        return dict(execution_status="failed", completion_reason="tool_unavailable",
                    output=None, artifacts=[], evidence_refs=[],
                    validation_results=[f"授权的工具里有同名的:{sorted(set(撞名))} —— "
                                        f"模型按名字调,调到哪个取决于字典顺序"],
                    usage={"模型回合": 0, "工具尝试": 0}, unknown_items=[],
                    quality_evaluation_status="未评", 账本条目=[])

    消息们 = [{"role": "system", "content": 配置.get("instructions") or ""},
             {"role": "user", "content": {"任务": 配置.get("task_template"),
                                          "输入": 输入}}]
    回合 = 0
    工具尝试 = 0
    被拒过 = set()          # (工具名, 参数摘要) —— 换说法重复申请的判据
    结果 = None
    执行状态, 完成原因, 问题们 = "incomplete", "max_turns", []

    while True:
        if 回合 >= 最大回合:
            # ⚠️ **回合用完不许盖掉真实的停止原因。**
            # 一个 finish 反复过不了核验的 Agent,原来报的是 max_turns ——
            # 而人拿到 max_turns 会去**调大上限**,那改不了任何事。
            # 真实原因是「输出核验没过」,它就在 问题们 里。
            执行状态 = "incomplete"
            完成原因 = "missing_evidence" if 问题们 else "max_turns"
            记事("agent.stopped", {
                "为什么": "回合上限",
                "停止原因": 完成原因,
                "核验没过的问题": 问题们[:3],
                "注意": "**达到上限停止 ≠ 完成任务**(§10.2);"
                       "而且**回合用完不等于「原因是回合用完」** —— "
                       "如果核验一直没过,那才是真原因"})
            break
        回合 += 1
        记事("agent.turn", {"回合": 回合, "上限": 最大回合,
                          # 修复/fallback 请求也算一回合(§9.6)
                          "口径": "一次模型请求算一回合,含修复与 fallback"})
        响应 = 适配器["model"](消息们, 工具定义们)
        动 = _动作(响应)
        记事("model.response", {"回合": 回合, "动作类型": 动,
                             "用量": (响应 or {}).get("usage")})

        if 动 == 只是说话:
            # §10.1:「模型给出普通文字计划,**只能显示为计划**」
            记事("model.plan_only", {
                "文字": str((响应 or {}).get("text"))[:200],
                "为什么没执行": "没有合法的工具请求 —— "
                              "**不自作主张执行文案里的命令**(§10.1)"})
            消息们.append({"role": "assistant", "content": 响应.get("text")})
            消息们.append({"role": "user", "content":
                          "这只是一段文字,没有被执行。要动手请发出正式的工具请求。"})
            continue

        if 动 == 要问人:
            执行状态, 完成原因 = "incomplete", "missing_evidence"
            记事("agent.clarification_requested",
                 {"问": 响应["clarification"],
                  "注意": "**人工等待要持久化检查点并释放 Worker**(§10.1)—— "
                         "这一版还没有检查点,所以直接停在这儿"})
            问题们.append("Agent 请求人工澄清,而人工等待还没实现(检查点缺)")
            break

        if 动 == 要调工具:
            # §10.3:「首版**每次串行**处理请求;模型一次提出多个请求时**保存顺序**,
            # 确认风险和依赖后逐项执行。」
            回传 = []
            for 调 in 响应["tool_calls"]:
                if 工具尝试 >= 最大工具:
                    执行状态, 完成原因 = "incomplete", "max_tool_attempts"
                    记事("agent.stopped", {"为什么": "工具调用上限"})
                    回传 = None
                    break
                工具尝试 += 1
                # ⚠️ **摘要走网关那个唯一出口**(`G.执行参数摘要`)。
                # 自己 `G.参数摘要(调["arguments"])` 算一遍的话,算出来的是
                # 「模型给的那份」,而网关比的是「实参」(含服务端绑定参数)——
                # 于是合法批准永远匹配不上。栽过一次。
                契 = 网关目录.get(调.get("name")) or {}
                摘 = G.执行参数摘要(契, 调.get("arguments") or {})
                键 = (调.get("name"), 摘)
                if 键 in 被拒过:
                    # **默认禁止对同一个被拒绝的副作用换说法重复申请**(§12.2)
                    执行状态, 完成原因 = "incomplete", "no_progress"
                    记事("agent.stopped", {
                        "为什么": "同一个被拒绝的动作又申请了一次",
                        "依据": f"工具 {调.get('name')} 参数摘要 {摘[:19]}… "
                               f"已经被拒过 —— **这是有依据的停止,"
                               f"不是「调用了两次」一刀切**(§10.3)"})
                    回传 = None
                    break
                try:
                    r = G.执行(调, 工具目录=网关目录, 有效范围=有效范围,
                             批准=(批准查询(调, 摘) if 批准查询 else None),
                             账本=账本, 适配器=适配器, 记事=记事,
                             逻辑动作id=f"{run_id}:{调.get('name')}:{摘[:16]}",
                             幂等键=f"{run_id}:{工具尝试}")
                    回传.append({"tool_call_id": 调.get("id"),
                                "name": 调.get("name"),
                                "result": r["结果"], "复用了吗": r["复用了吗"]})
                except G.拒绝 as e:
                    被拒过.add(键)
                    # **拒绝也回传,而且是安全的拒绝原因,不伪造成功**(§10.3)
                    回传.append({"tool_call_id": 调.get("id"),
                                "name": 调.get("name"),
                                "rejected": {"code": e.code,
                                             "reason": e.给模型看的}})
            if 回传 is None:
                break
            消息们.append({"role": "assistant", "content": 响应})
            消息们.append({"role": "tool", "content": 回传})
            continue

        # 动 == 说完成了
        候选 = 响应["finish"]
        行, 坏 = _核验完成(候选, 配置.get("output_schema"),
                        (配置.get("completion_criteria") or {}).get("必要证据"),
                        产物在吗=产物在吗, 账本=账本,
                        必须做的动作=(配置.get("completion_criteria") or {})
                                    .get("必须做的动作"))
        记事("agent.finish_claimed", {"通过核验吗": 行, "问题": 坏[:3],
                                   "注意": "模型说完成只是**候选结论**(§2)"})
        if 行:
            结果, 执行状态, 完成原因 = 候选, "succeeded", None
            break
        问题们 = 坏
        # **有限修复**:把问题回传,让它改一次。修复请求照样算回合、照样花钱(§6.2)
        剩 = 最大回合 - 回合
        if 剩 <= 0:
            执行状态, 完成原因 = "incomplete", "missing_evidence"
            break
        消息们.append({"role": "assistant", "content": 候选})
        消息们.append({"role": "user",
                      "content": {"没通过核验": 坏,
                                  "说明": "这些是程序核过的**可观察条件**,不是口味问题"}})

    return dict(
        execution_status=执行状态,
        completion_reason=完成原因,
        output=结果,
        artifacts=[r for r in ((结果 or {}).get("artifacts") or [])],
        evidence_refs=(结果 or {}).get("evidence_refs") or [],
        validation_results=问题们,
        usage={"模型回合": 回合, "工具尝试": 工具尝试},
        unknown_items=(结果 or {}).get("unknown_items") or [],
        # **另存一栏**:程序核过的只是可观察条件(§10.2 结尾)
        quality_evaluation_status="未评",
        账本条目=[dict(账本.条目[k], logical_action_id=k) for k in 账本.顺序],
    )
