#!/usr/bin/env python3
"""Agent SDK 封装 —— 这个站的内核。

和后台里那个手写循环(agent/v1.py)的区别:
  · 循环、上下文、工具调度**都由 SDK 管**,这里只提供环境和工具
  · 工具通过 **MCP** 挂载(mcp/kb_server.py、mcp/task_server.py),不再进程内直连
  · 模型指向 DeepSeek:ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY
    (实测可行;CLI 会对非 Claude 模型名报 unrecognized_model 警告,但透传正常)

SDK 是拉起 Claude Code CLI 跑的,所以本机必须装 CLI。
"""
import asyncio, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KEYFILE = os.path.expanduser("~/.deepseek-key")

try:
    from claude_agent_sdk import query, ClaudeAgentOptions   # noqa: E402
except ModuleNotFoundError as _e:      # noqa: E402
    # 踩过两次(都是我自己):`python3 agent/liability_eval.py` 直接跑,
    # 报一句 "No module named 'claude_agent_sdk'",看不出该怎么办。
    # SDK 只装在 agentsite/.venv 里 —— 凡是 import sdk 的脚本都得用那个 python。
    raise ModuleNotFoundError(
        f"{_e}\n\n"
        "  claude_agent_sdk 只装在 agentsite/.venv 里。\n"
        "  凡是 import sdk 的脚本(sdk / gen_compare / liability_eval / growth_eval /\n"
        "  tool_eval / vision_eval)都要用那个解释器:\n\n"
        "      ./agentsite/.venv/bin/python <脚本>\n\n"
        "  没有 .venv 就先 ./start.sh 建一次。") from None
import guards   # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "agent"))
import trace       # noqa: E402  记录仪:**和 V1 共用同一份**,写同一个文件、同一套字段
# 两代分开记就没法横向对比了,而「一代 vs 三代到底差多少」这个问题
# 只有手上同时有两套实现的人答得了 —— 别把这个优势浪费在格式不一致上。

# 单次调用的花费上限。研判队列支持批量跑,一条失控就是真金白银 ——
# SDK 现成的参数,不设等于没有闸门。
MAX_USD = float(os.environ.get("LANXIU_MAX_USD", "0.60"))


def models():
    """能选的模型清单。**从单价表长出来,不在这里另抄一份。**

    v1.price_of 对没有单价的模型直接拒绝跑(帕鲁项目踩过:用错单价虚高 12.5 倍),
    所以「页面上能选什么」和「有没有单价」必须是同一个来源 ——
    另写一份清单,迟早出现一个选得中却算不出钱的模型。
    """
    import v1
    out = [dict(id="claude:" + m, provider="claude", model=m, label=m, note="订阅内",
                vision=sees_images("claude", m)) for m in v1.PRICE]
    out += [dict(id="deepseek:" + m, provider="deepseek", model=m, label=m, note="按量计费",
                 vision=sees_images("deepseek", m)) for m in v1.DEEPSEEK_PRICE]
    return out


def sees_images(provider, model):
    """这个模型收不收得下图。

    Claude 全系都收;DeepSeek 只有名字里带 vision 的那个实验模型收。
    **按规则判,不另列一张表** —— 单价表里加个新模型时这里自动跟上,
    另列一张表就迟早出现「清单里说能看图、实际发过去报错」。
    """
    return provider == "claude" or "vision" in (model or "")


def default_model_id():
    prov = "claude" if os.environ.get("LANXIU_PROVIDER", "").lower() == "claude" else "deepseek"
    return f"{prov}:" + (os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5") if prov == "claude"
                         else os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"))


def _env(provider=None, model=None):
    """把凭证和模型指向装进环境。SDK 会把这些透传给它拉起的 CLI。

    provider / model 是**单次调用的覆盖**(页面上换模型走这条路);
    都不给时按环境变量走 —— 命令行和评测脚本的行为一个字没变。

    **LANXIU_PROVIDER=claude 时什么都不设** —— 让 CLI 用它自己的登录态。
    这条开关是给两件事准备的:
      ① 三代横向对比要控制变量,三代必须能指定同一个模型
      ② **识图只能走 Claude**(视觉输入),顾问助手迟早要接
         「客户发张照片问这是什么形制」

    要**主动清掉**上一次设过的两个变量 —— 同一个进程里先跑 DeepSeek 再跑 Claude,
    不清就会带着 DeepSeek 的 base_url 去打 Claude。
    """
    prov = (provider or os.environ.get("LANXIU_PROVIDER", "")).lower()
    if prov == "claude":
        for v in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY"):
            os.environ.pop(v, None)
        return model or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    k = os.environ.get("DEEPSEEK_API_KEY") or (
        open(KEYFILE).read().strip() if os.path.exists(KEYFILE) else None)
    if not k:
        raise RuntimeError("没有 DeepSeek 凭证:设 DEEPSEEK_API_KEY 或写入 ~/.deepseek-key")
    os.environ["ANTHROPIC_BASE_URL"] = "https://api.deepseek.com/anthropic"
    os.environ["ANTHROPIC_API_KEY"] = k
    return model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")


def cost_of(usage, model, ts=None):
    """按 **DeepSeek 的**价目表算这次花了多少钱。

    为什么不用 SDK 自己给的 total_cost_usd:它是 CLI 按 **Claude 的**单价算的,
    而我们把 ANTHROPIC_BASE_URL 指到了 DeepSeek —— CLI 并不知道真实价格。
    实测一次 22k token 的调用,SDK 报 $0.1365,按 DeepSeek 实价是 $0.0008,**差 160 倍**。
    运维平台上挂一个错的成本数,比不挂还糟:它会让人按错的量级做决策。

    价目表不在这里重抄一份,从 agent/v1.py 取 —— 那边已经处理了 DeepSeek 的
    高峰/平峰分时定价(周一至周五 UTC 01-04 / 06-10 翻倍)。
    """
    sys.path.insert(0, os.path.join(ROOT, "agent"))
    import v1
    # 模型可能是 DeepSeek 也可能是 Claude —— 两张价目表都查,**查不到就不猜**
    pr = v1.DEEPSEEK_PRICE.get(model) or v1.PRICE.get(model)
    if not pr or not usage:
        return None            # 价目表里没有这个模型就不猜,宁可显示「—」
    if model in v1.DEEPSEEK_PRICE and v1.is_peak(ts):
        pr = {k: v * 2 for k, v in pr.items()}     # 分时定价只有 DeepSeek 有
    cache = usage.get("cache_read_input_tokens", 0) or 0
    inp = max((usage.get("input_tokens", 0) or 0) - cache, 0)   # 命中缓存的那部分单独计价
    out = usage.get("output_tokens", 0) or 0
    return round((inp * pr["inp"] + cache * pr["cache"] + out * pr["out"]) / 1e6, 6)


def mcp_config():
    """把两个 MCP 服务挂上。工具面按用途分开,不给模型多余的选择。"""
    py = sys.executable
    return {
        "kb":   {"type": "stdio", "command": py,
                 "args": [os.path.join(ROOT, "mcp", "kb_server.py")]},
        "task": {"type": "stdio", "command": py,
                 "args": [os.path.join(ROOT, "mcp", "task_server.py")]},
        # 门店业务数据:订单 / 现货 / 售后。**顾问和值班两边都挂** ——
        # 之前顾问能答「云锦配缂丝要 174 天」,却答不了「这件有没有现货」,
        # 是一个知道所有原理、却不知道今天发生了什么的助手。
        "shop": {"type": "stdio", "command": py,
                 "args": [os.path.join(ROOT, "mcp", "shop_server.py")]},
    }


# MCP 工具在 SDK 里的名字是 mcp__<服务名>__<工具名>
KB_TOOLS = ["mcp__kb__kb_lookup", "mcp__kb__kb_detail", "mcp__kb__kb_combo",
            "mcp__kb__kb_tables", "mcp__kb__kb_coverage",
            "mcp__kb__kb_pattern", "mcp__kb__kb_size", "mcp__kb__kb_bom",
            "mcp__kb__kb_fit", "mcp__kb__kb_lead"]
# ── 按角色发工具,不是两个角色都给全量 ────────────────────────────────
# 原来 SHOP_TOOLS 一整包同时给了工艺顾问和任务助手,于是任务助手(退款定因 /
# 客户合并 / 售后判责)手里多出 forecast_growth、plan_for_event、get_wearer、
# get_capacity 四个它业务上用不着的工具 —— **而这四个的用法规矩(TL09/TL10/
# TL12/TL13)全在工艺顾问那一侧**,任务助手拿到了工具却拿不到规矩。
#
# 「工具给了,规矩没给」比「工具没给」更危险:模型会用,而且没人告诉它怎么用错。
# 拆解 Accio 时看到它的做法是从 none 起白名单、按角色逐个发权,
# 这条对我们成立 —— 检查见 prompts_check.py 的 P6。
SHOP_TOOLS = [
    # 两个角色都要:客户问「订单到哪了 / 有没有现货 / 上次退货处理了吗」,
    # 后台定因也要靠 get_order 的勾稽异常。售后判责的现场在 get_maintain。
    "mcp__shop__get_order", "mcp__shop__get_stock", "mcp__shop__get_aftersale",
    # 售后判责的现场。只给事实不给结论 —— 结论必须由人确认。
    "mcp__shop__get_maintain",
]

# 只给工艺顾问:着装人、成长推算、场景倒推、工坊产能。
# **同意状态是这几个工具里的硬门** —— 没有有效同意就取不到身体数据、
# 算不出推算,不靠模型自觉。
#
# ⚠️ 加了新 MCP 工具就必须同步加到这里,否则模型看得见却用不了。
# 这一条漏过一次(plan_for_event 挂上了 MCP 却忘了进白名单),
# 所以 skills_check.py 加了结构检查:**白名单必须和 MCP 暴露的完全一致**,
# 靠人记得同步是不行的。
KB_ONLY_TOOLS = [
    "mcp__shop__get_wearer", "mcp__shop__forecast_growth",
    "mcp__shop__plan_for_event",
]

# ── 工坊排产:面对产能,不面对客户 ──────────────────────────────────
# 顾问问「客户什么时候能拿到」,工坊问「这活派给谁、会不会拖」——
# 同一批数据,两种问题。get_capacity 从顾问那边搬过来了:
# 那条规矩(TL13)的原文写的就是「工坊问……」,它本来就该在这儿。
WORKSHOP_TOOLS = [
    "mcp__shop__get_capacity",     # 工种级:瓶颈在哪、消化几天
    "mcp__shop__get_workorder",    # 单件级:在谁手上、会不会拖
    "mcp__kb__kb_lead", "mcp__kb__kb_bom",
    "mcp__kb__kb_pattern", "mcp__kb__kb_size",
]

# 项目自带的 Skill(agentsite/.claude/skills/<名字>/SKILL.md)。
# Skill 管的是**产出物的格式**:报价单会被截图转发,脱离上下文独自存在,
# 所以每一份都得自带完整前提 —— 这种「有固定套路、做错了有代价」的事才该做成 Skill。
SKILLS = ["quote", "growth-plan"]
TASK_TOOLS = ["mcp__task__list_tasks", "mcp__task__get_deposit",
              "mcp__task__get_refund_trace", "mcp__task__get_payment_flow",
              "mcp__task__get_customer"]

# 只给后台运营:会员生命周期判定(八档 + 凭什么 + 有没有被人工覆盖)。
# 这是**台账活** —— 顾问在跟客户说话的时候不该做分群。
# P6 当场拦住了我最初「放进两个角色共用那包」的写法:工具发给了工艺顾问,
# 而管它的规矩 TK08 只写给后台运营 —— **工具给了、规矩没给**。
# 它逼我决定这个工具归谁,而不是默认发给所有人。
TASK_ONLY_TOOLS = [
    "mcp__shop__get_lifecycle", "mcp__shop__get_member_priority",
    # 「这件事业务允不允许做」—— 跑真校验器,不写库。
    # 加它是因为实测发现:没有它时模型会**编一套架构理由**说可以,
    # 而编造建立在真事实上(账户与门店档案确实分层),读起来完全可信。
    "mcp__shop__check_write",
    # 售后判责跑在这个角色上,而**判定表在 kb_tables 里**。
    # 原来没给:get_maintain 的描述明写「判定标准要另外查 kb_tables」,
    # liability_eval 的提示词也明写「再用 kb_tables 取售后争议判定」——
    # 而这个角色根本调不了它。18/18 全过,但**每条判责结论都没有依据来源**,
    # 模型是凭自己对「什么算公平」的理解在判。改公司政策,它不会跟着变。
    "mcp__kb__kb_tables",
    # 待核实队列:哪些格子被问到了却没依据。**只读,回填在后台。**
    # ⚠️ 命名空间跟着 **schema 挂在哪个服务**走,不跟着「它像哪一类」走。
    # 我第一版写成 mcp__kb__(因为它讲的是知识库的事),而它的 schema 在 SHOP_SCHEMAS 里,
    # 于是白名单和 MCP 暴露对不上 —— skills_check 当场抓到,和当年 plan_for_event 同一个坑。
    "mcp__shop__get_review_queue",
]

# ── 提示词:唯一源头在根目录 prompts.py ──────────────────────────────
# 原来这里是两份 64 行 + 18 行的字面量,而 agent/chat.py 里还有**另一份**同角色的
# 提示词(6 条铁律)。同一个事实两个来源,必然漂 —— 而且它漂了:
# 评测跑的是 chat.py 那份,给出的分数评的不是这里跑的产品。
#
# 现在每条铁律声明自己依赖哪个工具,按下面这份工具清单装配。
# **加了工具,相关铁律自动进来;没挂的工具,对应铁律自动不发** ——
# 不会再出现「提示词让模型去调一个它没有的工具」。
sys.path.insert(0, ROOT)
import prompts   # noqa: E402

_ROLE_TOOLS = {
    "kb":       lambda: KB_TOOLS + KB_ONLY_TOOLS + SHOP_TOOLS,
    "workshop": lambda: WORKSHOP_TOOLS,           # 工坊不看订单流水,只看产能和工单
    "task":     lambda: TASK_TOOLS + TASK_ONLY_TOOLS + SHOP_TOOLS,
}

def _tools_for(kind):
    return _ROLE_TOOLS.get(kind, _ROLE_TOOLS["kb"])()


def _have(kind):
    """本进程实际挂上的工具名(去掉 mcp__<服务>__ 前缀),外加能力标记。"""
    names = {t.rsplit("__", 1)[-1] for t in _tools_for(kind)}
    # 工艺顾问这条路径收图(见 _img_block),后台任务助手不收
    return names | ({"图片"} if kind == "kb" else set())

SYS_KB, KB_RULE_IDS = prompts.assemble("kb", _have("kb"))
SYS_WORKSHOP, WORKSHOP_RULE_IDS = prompts.assemble("workshop", _have("workshop"))
SYS_TASK, TASK_RULE_IDS = prompts.assemble("task", _have("task"))
_SYS = {"kb": SYS_KB, "workshop": SYS_WORKSHOP, "task": SYS_TASK}


def _img_block(path):
    """本地图片 → Anthropic 的 image content block(base64)。"""
    import base64, mimetypes
    mt = mimetypes.guess_type(path)[0] or "image/png"
    if mt not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
        raise ValueError(f"{mt} 不是视觉模型收的格式(png/jpeg/gif/webp)—— "
                         "SVG 要先栅格化,见 backend/img.py 的 png()")
    return {"type": "image",
            "source": {"type": "base64", "media_type": mt,
                       "data": base64.standard_b64encode(open(path, "rb").read()).decode()}}


async def _stream_once(prompt, images):
    """带图时走**流式输入**:query() 的 prompt 除了字符串,
    还能收 AsyncIterable[dict],每条是一个 user 消息 —— 图片块只能这么送。"""
    yield {"type": "user",
           "message": {"role": "user",
                       "content": [_img_block(p) for p in images]
                                  + [{"type": "text", "text": prompt}]},
           "parent_tool_use_id": None, "session_id": "vision"}


async def run(kind, prompt, max_turns=12, guard=True, images=None, resume=None,
              provider=None, model_name=None):
    """跑一轮。kind: kb(工艺顾问)/ task(人工任务)。返回文本、轨迹、用量。

    guard=True 时挂上回答体检 hook:交付前检查一遍,不合格**打回重答**。
    提示词里那些「铁律」原本只是祈使句,挂上 hook 才是强制。

    images:本地图片路径列表。**给了图就走流式输入通道** ——
    字符串 prompt 塞不进图片块,这是接识图时唯一需要动的地方。

    resume:上一轮返回的 session_id。**多轮不是把历史拼进 prompt** ——
    那样每轮都要重发全部上下文,又贵又容易被截断,而且工具调用记录会丢。
    CLI 自己存着这条会话的完整记录,给它 session_id 就接着往下走,
    前面几轮的上下文还能命中缓存。返回值里带 session_id,前端存着下轮送回来。
    """
    model = _env(provider, model_name)
    state = {}
    opts = ClaudeAgentOptions(
        hooks=guards.make_hooks(state) if guard else None,
        max_budget_usd=MAX_USD,
        system_prompt=_SYS.get(kind, SYS_KB),
        mcp_servers=mcp_config(),
        allowed_tools=_tools_for(kind),
        # ⚠️ **allowed_tools 不是排他白名单。**
        # 它管的是「哪些工具不用逐次批准」,不是「只有这些工具存在」——
        # 配上 permission_mode="bypassPermissions" 之后,CLI 的内置工具
        # (Bash / Read / Write / Edit / Task / WebFetch …)**一样在场,一样能用**。
        #
        # 这是实跑抓到的:一条查押金单的任务,轨迹里出现了
        #   ['ToolSearch', 'Bash', 'Agent', 'ToolSearch', 'get_deposit', ...]
        # 模型自己去开了 Bash 和子智能体。
        #
        # 这直接打穿了这个项目最硬的一条保证:**工具全部只读,0 个写接口**。
        # 只读的是我们挂的 19 个 MCP 工具,而 Bash 能读能写能删,**它不受这条保证约束**。
        # 更要命的是它一直没被发现 —— DeepSeek 那边的模型只是**碰巧没去用**。
        # 「模型没用」和「模型不能用」是两回事,安全边界不能建在前者上。
        disallowed_tools=[
            "Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "NotebookEdit",
            "Glob", "Grep", "WebFetch", "WebSearch", "Task", "Agent", "ToolSearch",
            "TodoWrite", "SlashCommand", "Artifact", "SendUserFile",
        ],
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",   # 工具全是只读的,不需要逐次批准
        cwd=HERE,
        # ⚠️ 这两行是必须的。不设的话 SDK 会**继承开发机上的 Claude Code 配置** ——
        # 项目根的 .mcp.json 会被自动挂上,和这里声明的重复一套,
        # allowed_tools 白名单也就形同虚设(实测工具名跑成了 mcp__lanxiu-task__*)。
        # 服务要在别的机器上行为一致,配置必须是封闭的。
        strict_mcp_config=True,     # 只用上面 mcp_servers 声明的,忽略文件里的
        # 要用项目自带的 Skill,就必须让 CLI 去读 project 设置 —— setting_sources=[]
        # 的话它连 .claude/skills/ 都不会去看。**只开 project,不开 user 和 local**:
        # user 是开发机上那个人的偏好,local 是没进版本库的临时配置,
        # 服务在别的机器上必须行为一致,那两个一开就不一致了。
        # MCP 的污染由 strict_mcp_config=True 挡住(它只认代码里声明的服务),
        # 所以这里放开 project 是安全的 —— 但**必须有检查盯着**,见 skills_check.py。
        setting_sources=["project"],
        skills=SKILLS,
        resume=resume,          # 见 docstring:多轮靠 CLI 续会话,不靠拼历史
    )
    # 按「一段回答」分开收,不是一路拼下去。
    # 体检打回后模型会重答,而 hook 的反馈是以 user 角色进流的 ——
    # 原来对所有消息都读 content,结果 text 里混进了反馈原文和被打回的那版答案,
    # 客户会看到「Stop hook feedback: ...」。**最终答案取最后一段。**
    turns, traj, usage, cost, res = [], [], {}, None, None
    t0 = time.time()
    _p = _stream_once(prompt, images) if images else prompt
    async for m in query(prompt=_p, options=opts):
        cls = type(m).__name__
        if cls == "AssistantMessage":
            cur = ""
            for b in getattr(m, "content", []) or []:
                bt = type(b).__name__
                if bt == "TextBlock" and getattr(b, "text", ""):
                    cur += b.text
                elif bt == "ToolUseBlock":
                    traj.append({"tool": getattr(b, "name", "?"),
                                 "args": getattr(b, "input", {})})
            if cur.strip(): turns.append(cur)
        elif cls == "ResultMessage":
            usage = getattr(m, "usage", None) or {}
            cost = getattr(m, "total_cost_usd", None)
            res = m
    text = turns[-1] if turns else ""
    # ── 记录仪 ─────────────────────────────────────────────────────────
    # 升代之后这条路径一度**一行日志都没有**:trace.jsonl 停在换架构那天,
    # 而且不报错 —— 文件还在、还有数据,只是日期不动了。
    # 「换了车,仪表盘留在旧车上」是升代最容易漏的一项,补上并加了结构检查防复发。
    ms = (time.time() - t0) * 1000
    real = cost_of(usage, model)
    try:
        sys.path.insert(0, os.path.join(ROOT, "agent"))
        import v1 as _v1
        price = _v1.DEEPSEEK_PRICE.get(model)
        peak = _v1.is_peak()
        if price and peak: price = {k: v * 2 for k, v in price.items()}
    except Exception:
        price, peak = None, False
    trace.record(
        gen="V3", model=model, purpose={"kb": "工艺顾问", "task": "人工任务研判"}.get(kind, kind),
        usage=usage, latency_ms=ms, price=price, peak=peak, cache_on=True,
        cost_est=real,                      # 成本口径只有一处:sdk.cost_of()
        finish_reason=getattr(res, "stop_reason", None),
        turn=getattr(res, "num_turns", None),
        error=(getattr(res, "errors", None) or None) if getattr(res, "is_error", False) else None,
        extra=dict(
            tool_calls=len(traj),
            answer_turns=len(turns),
            guard_blocked=bool(state.get("violations")),
            guard_checks=[v["check"] for v in (state.get("violations") or [])] or None,
            # SDK 自报的两个数一起记下来,但**不当依据用** ——
            # sdk_cost 实测按 Claude 单价算,和 DeepSeek 实价差 24 倍。
            # 记着是为了以后能证明「它确实不准」,不是为了拿它算账。
            sdk_cost_usd=cost, api_ms=getattr(res, "duration_api_ms", None),
            terminal_reason=getattr(res, "terminal_reason", None),
        ))

    return dict(text=text.strip(), trajectory=traj, seconds=round(time.time() - t0, 1),
                session_id=getattr(res, "session_id", None),
                usage=usage, sdk_cost_usd=cost, cost_usd=real, model=model,
                # 被体检打回过几次、因为什么 —— 这两个数要落进研判台账,
                # 它们是「模型有多不听话」的直接度量,比事后抽样评测灵敏得多
                guard_blocked=bool(state.get("violations")),
                guard_violations=state.get("violations") or [],
                tool_calls_seen=len(state.get("calls") or []),
                answer_turns=len(turns), text_all="\n\n".join(turns))


if __name__ == "__main__":
    q = sys.argv[2] if len(sys.argv) > 2 else "香云纱能不能做妆花?"
    k = sys.argv[1] if len(sys.argv) > 1 else "kb"
    r = asyncio.run(run(k, q))
    print(f"问:{q}\n")
    for t in r["trajectory"]:
        print(f"  ↳ {t['tool']}({json.dumps(t['args'],ensure_ascii=False)[:70]})")
    print(f"\n{r['text']}\n")
    if r.get("guard_blocked"):
        print("⚠ 回答体检打回过:")
        for v in r["guard_violations"]: print(f"   · {v['msg']}")
    u = r["usage"] or {}
    print(f"—— {r['seconds']}s · {r['model']} · 实价 ${r['cost_usd']} "
          f"(SDK 按 Claude 单价报 ${r['sdk_cost_usd']},不可用)\n   输入 {u.get('input_tokens')} 其中命中缓存 {u.get('cache_read_input_tokens')} · 输出 {u.get('output_tokens')}")
