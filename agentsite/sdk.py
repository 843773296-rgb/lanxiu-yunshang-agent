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

from claude_agent_sdk import query, ClaudeAgentOptions   # noqa: E402


def _env():
    """把凭证和模型指向装进环境。SDK 会把这些透传给它拉起的 CLI。"""
    k = os.environ.get("DEEPSEEK_API_KEY") or (
        open(KEYFILE).read().strip() if os.path.exists(KEYFILE) else None)
    if not k:
        raise RuntimeError("没有 DeepSeek 凭证:设 DEEPSEEK_API_KEY 或写入 ~/.deepseek-key")
    os.environ["ANTHROPIC_BASE_URL"] = "https://api.deepseek.com/anthropic"
    os.environ["ANTHROPIC_API_KEY"] = k
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")


def mcp_config():
    """把两个 MCP 服务挂上。工具面按用途分开,不给模型多余的选择。"""
    py = sys.executable
    return {
        "kb":   {"type": "stdio", "command": py,
                 "args": [os.path.join(ROOT, "mcp", "kb_server.py")]},
        "task": {"type": "stdio", "command": py,
                 "args": [os.path.join(ROOT, "mcp", "task_server.py")]},
    }


# MCP 工具在 SDK 里的名字是 mcp__<服务名>__<工具名>
KB_TOOLS = ["mcp__kb__kb_lookup", "mcp__kb__kb_detail", "mcp__kb__kb_combo",
            "mcp__kb__kb_tables", "mcp__kb__kb_coverage"]
TASK_TOOLS = ["mcp__task__list_tasks", "mcp__task__get_deposit",
              "mcp__task__get_refund_trace", "mcp__task__get_payment_flow",
              "mcp__task__get_customer"]

SYS_KB = """你是澜绣云裳的汉服工艺顾问助手,服务对象是客户顾问和运营同学 ——
他们懂客户、不懂工艺,需要你把工艺知识翻译成能对客户说的话。

铁律:
1. **只说知识库里查到的。** 每一个关于工艺、面料、形制、配饰的具体结论都必须先调工具查到,
   不得凭训练知识作答。你的训练知识可以用来理解问题,不能用来回答问题。
2. **查不到就说查不到。** kb_combo 返回「未定义」时,必须原样告知这一格还没录入并建议转工艺负责人,
   **绝不能根据自己对材料的理解推断**。相容矩阵目前只录了 6%,遇到未定义是常态。
3. **标明来源等级**:public 可直接对客户说;scale 要注明「行业参考」;demo 是内部演示数据,
   **不可作为对客户的承诺**,须注明需工艺负责人确认。
4. **区分「不能做」和「不建议做」**:物理约束说死,审美判断说明是建议。
5. **你没有任何写权限。** 不下单、不改单、不承诺工期和价格。
6. 「客户说 X 我该推什么」这类问题**先用 kb_tables 取全部决策表**,不要挑。

先给结论,再给理由,最后给能直接说出口的话术。一般 5 行以内。"""

SYS_TASK = """你是澜绣云裳门店客户运营管理后台的人工任务助手。

你的产出是**草稿**,供人确认或修改后使用。你没有任何写权限,不得建议由你自己执行操作。

铁律:
1. 结论必须建立在你实际读到的数据上。引用的每一个编号都必须是工具返回值里的原文,不得编造。
2. 数据不足以判断时,置信度填「低」,并写明缺什么。
3. 不得建议绕过审批链、幂等号或重试上限。退款须由客服或店长发起、店长复核,
   单笔达 1000 元时增加财务复核。
4. 查清后按「根因 / 建议动作 / 证据 / 置信度」四段给出草稿。"""


async def run(kind, prompt, max_turns=12):
    """跑一轮。kind: kb(工艺顾问)/ task(人工任务)。返回文本、轨迹、用量。"""
    model = _env()
    opts = ClaudeAgentOptions(
        system_prompt=SYS_KB if kind == "kb" else SYS_TASK,
        mcp_servers=mcp_config(),
        allowed_tools=KB_TOOLS if kind == "kb" else TASK_TOOLS,
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",   # 工具全是只读的,不需要逐次批准
        cwd=HERE,
        # ⚠️ 这两行是必须的。不设的话 SDK 会**继承开发机上的 Claude Code 配置** ——
        # 项目根的 .mcp.json 会被自动挂上,和这里声明的重复一套,
        # allowed_tools 白名单也就形同虚设(实测工具名跑成了 mcp__lanxiu-task__*)。
        # 服务要在别的机器上行为一致,配置必须是封闭的。
        strict_mcp_config=True,     # 只用上面 mcp_servers 声明的,忽略文件里的
        setting_sources=[],         # 不读 user / project / local 任何设置文件
    )
    text, traj, usage, cost = "", [], {}, None
    t0 = time.time()
    async for m in query(prompt=prompt, options=opts):
        cls = type(m).__name__
        for b in getattr(m, "content", []) or []:
            bt = type(b).__name__
            if bt == "TextBlock" and getattr(b, "text", ""):
                text += b.text
            elif bt == "ToolUseBlock":
                traj.append({"tool": getattr(b, "name", "?"),
                             "args": getattr(b, "input", {})})
        if cls == "ResultMessage":
            usage = getattr(m, "usage", None) or {}
            cost = getattr(m, "total_cost_usd", None)
    return dict(text=text.strip(), trajectory=traj, seconds=round(time.time() - t0, 1),
                usage=usage, sdk_cost_usd=cost, model=model)


if __name__ == "__main__":
    q = sys.argv[2] if len(sys.argv) > 2 else "香云纱能不能做妆花?"
    k = sys.argv[1] if len(sys.argv) > 1 else "kb"
    r = asyncio.run(run(k, q))
    print(f"问:{q}\n")
    for t in r["trajectory"]:
        print(f"  ↳ {t['tool']}({json.dumps(t['args'],ensure_ascii=False)[:70]})")
    print(f"\n{r['text']}\n")
    print(f"—— {r['seconds']}s · {r['model']} · usage={r['usage']}")
