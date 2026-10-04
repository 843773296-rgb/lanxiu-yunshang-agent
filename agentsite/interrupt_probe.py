#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**这条入口到底停不停得下来** —— 规格 §6.2 要的那个「超时测试」。

## 规格原话

> 「当前入口使用 `query()`。若所安装版本无法提供需要的主动中断控制,
> 应评估迁到可中断的客户端形式……**先做一个超时测试证明可停止,再扩展**。
> **不得在文档里假定 `query()` 有不存在的中断方法。**」

静态那一半已经量过了(2026-10-04,本机实装 `claude-agent-sdk 0.2.152`):

    query()            → 返回异步迭代器,**上面没有任何可调的中断方法**
    ClaudeSDKClient    → 有 `interrupt()`,还有 `stop_task(task_id)`

而静态只能证明「**有这个方法**」。**有方法不等于它真的停得下来** ——
这个项目为同一个形状栽过一串:`allowed_tools` 不是排他白名单 ·
`.pyc` 的「防止产生」≠「防止使用」· 规矩写在提示词里 ≠ 结构上拦住。

> **一个调了 `interrupt()` 而它其实没停的实现,和一个真停了的,
> 在那句「已请求停止」上长得一模一样。**

规格 §8 自己点了这件事:「操作进行中显示请求状态,**等执行器回执后
才更新为已停止/已恢复**」、「**不能把仍在运行的线程换个名称后
当作已经停止**」。

## 所以判据不是「没抛异常」,也不是「迭代器返回了」

「停止」在这个产品里的业务含义只有一条(规格 §1 第 3 条):

> 「到达上限后,**服务端不再发起新的受限调用**。」

所以要量的是:**中断之后,工具还被调了几次。必须是 0。**

一个「迭代结束了而工具还在后台接着跑」的停止,和一个真停了的,
在那个「已停止」上也长得一样 —— 所以工具调用记的是**单调时钟的时刻**,
中断之后的那些会被单独数出来。

## 两种「这一轮作废」,它们都不是通过

① **工具一次都没被调** → 分母为 0。
   这一轮什么都没证明,而「一次都没调」和「调了但中断后没再调」
   在那个 `0` 上长得一模一样。

② **中断发出时它已经自己答完了** → 那它的「停」跟 `interrupt()` 无关。
   > 一个「因为中断才停的」,和一个「本来就要停了的」,
   > **在那个「停了」上长得一模一样。**
   所以中断是在**第 N 次工具调用正在进行时**发出的 —— 那一刻模型
   必然还在跑;而如果没能发出,这一轮就作废,不记成通过。

## 它不做什么

- **不进 `check.sh`。** 它要真调模型、要登录态,依赖外部状态的检查
  放进门禁会变成随机拦路(CLAUDE.md §8)。它由人手动跑。
- **不证明 `query()` 入口能停。** 恰恰相反:静态那一栏就是用来
  说明那条入口**没有**中断方法的。要停就得迁到客户端形式。
- **不量超时上限对不对。** 它只证明「停得下来」这件机制成立;
  期限数值、预算账本是 P0-C 的事。

## 跑

    LANXIU_PROVIDER=claude ./agentsite/.venv/bin/python agentsite/interrupt_probe.py

**必须用 venv 的 python**(要 SDK),**而且模型是写死并印出来的** ——
不指定时默认模型取决于用哪种凭证,同一条命令在另一台机器上
跑的是另一个模型,而报告上完全看不出来(CLAUDE.md §3)。
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claude_agent_sdk as S

# ⚠️ **写死并印出来。** 见 CLAUDE.md §3:不指定模型时,默认值取决于凭证种类
# (API key → opus;钥匙串登录态 → haiku),而表格上看不出是谁算出来的。
# 这里测的是中断**机制**,不是模型能力,所以挑快的那个。
模型 = "claude-haiku-4-5"

工具耗时 = 1.5      # 每次工具调用故意慢一点,好让中断落在「正在进行」里
触发在第几次 = 2    # 第 2 次工具调用时发中断 —— 那一刻它一定还在跑
硬超时 = 90         # 探针自己的兜底:中断后永不结束也得报出来,不许挂死


class 作废(Exception):
    """这一轮证明不了任何事。**不是通过,也不是失败。**"""


async def 跑一轮(发中断=True):
    调用记录 = []        # [(第几次, 单调时刻)]
    中断时刻 = [None]
    中断报错 = [None]
    消息们 = []
    客户端 = [None]

    @S.tool("slow_lookup", "按编号查一条库存记录(故意慢)",
            {"n": {"type": "integer", "description": "记录编号"}})
    async def slow_lookup(args):
        调用记录.append((len(调用记录) + 1, time.monotonic()))
        if 发中断 and len(调用记录) == 触发在第几次:
            # ⚠️ **不在工具里 await interrupt** —— 工具还没把结果交回去,
            # 在这儿等控制消息的回执有互锁风险。调度成一个独立任务,
            # 这样中断确实落在「第 N 次调用正在进行」的那个窗口里。
            asyncio.create_task(_发中断())
        await asyncio.sleep(工具耗时)
        return {"content": [{"type": "text",
                             "text": f"编号 {args['n']}:库存 7 匹,产地苏州"}]}

    async def _发中断():
        await asyncio.sleep(0.2)
        try:
            中断时刻[0] = time.monotonic()
            await 客户端[0].interrupt()
        except Exception as e:
            # ⚠️ 中断自己抛了 → **这个版本不支持**,要明说,
            # 不能让它和「中断发出去了而没效果」混成一句。
            中断报错[0] = f"{type(e).__name__}: {e}"

    服务 = S.create_sdk_mcp_server("probe", tools=[slow_lookup])
    opts = S.ClaudeAgentOptions(
        model=模型,
        mcp_servers={"probe": 服务},
        allowed_tools=["mcp__probe__slow_lookup"],
        # ⚠️ 双锁 —— `allowed_tools` **不是排他白名单**(CLAUDE.md §7 第 1 项:
        # 本项目最严重的一次事故)。配上 bypassPermissions 之后内置工具一直都在。
        disallowed_tools=["Bash", "BashOutput", "KillShell", "Read", "Write",
                          "Edit", "NotebookEdit", "Glob", "Grep", "WebFetch",
                          "WebSearch", "Task", "Agent", "ToolSearch",
                          "TodoWrite", "SlashCommand"],
        permission_mode="bypassPermissions",
        max_turns=12,
        # cwd 不能在项目里 —— 否则 CLI 会往上找到 CLAUDE.md
        # 并把整份工程手册塞进系统提示词(sdk.py 里踩过)。
        cwd="/tmp",
        system_prompt="你是库存助手。用户给几个编号,你就逐个调用 slow_lookup 查,"
                      "**一次查一个**,全部查完再汇总。",
    )

    任务 = "请逐个查这六个编号的库存并汇总:101、102、103、104、105、106。"
    起 = time.monotonic()
    async with S.ClaudeSDKClient(options=opts) as c:
        客户端[0] = c
        await c.query(任务)
        try:
            async def _收():
                async for m in c.receive_response():
                    消息们.append(type(m).__name__)
            await asyncio.wait_for(_收(), timeout=硬超时)
            挂死 = False
        except asyncio.TimeoutError:
            挂死 = True
    结束 = time.monotonic()

    return dict(调用记录=调用记录, 中断时刻=中断时刻[0], 中断报错=中断报错[0],
                消息们=消息们, 挂死=挂死, 起=起, 结束=结束)


def 判(r, 基线次数):
    """返回 (退出码, 行们)。**作废单独一档,不混进通过或失败。**

    ⚠️ `基线次数` 是**同一个任务不发中断时**工具被调了几次 —— 咬合的第 ① 关。
    > 一个「**因为中断**才只调了 N 次」的,和一个「它**本来就只调** N 次」的,
    > **在那个 N 上长得一模一样。**
    没有这个对照,「中断之后 0 次新调用」证明不了截断发生过。
    """
    行 = []
    记 = r["调用记录"]
    行.append(f"  工具被调了 {len(记)} 次;中断{'发出了' if r['中断时刻'] else '**没发出**'}")

    # ── 作废 ①:分母为 0 ──────────────────────────────────────────
    if not 记:
        行.append("  ⏸ **这一轮作废:工具一次都没被调** —— 分母为 0。")
        行.append("     「一次都没调」和「调了但中断后没再调」,"
                  "在那个 `0` 上长得一模一样。")
        行.append("     多半是模型没去用工具。重跑,或把任务写得更必须用工具。")
        return 2, 行

    # ── 中断自己抛了 → 这个版本不支持,**和「没效果」要分开说** ──────
    if r["中断报错"]:
        行.append(f"  ❌ `interrupt()` 自己抛了:{r['中断报错']}")
        行.append("     这是「**这个版本不支持主动中断**」,"
                  "不是「中断了但没效果」—— 两者的下一步完全不同。")
        return 1, 行

    # ── 作废 ②:中断没发出(工具调用次数没到触发点) ─────────────────
    if r["中断时刻"] is None:
        行.append(f"  ⏸ **这一轮作废:中断没发出** —— 工具只被调了 {len(记)} 次,"
                  f"没到第 {触发在第几次} 次的触发点。")
        行.append("     而这一轮它**自己结束了**,那个「停了」跟 `interrupt()` 无关:")
        行.append("     > 一个「因为中断才停的」,和一个「本来就要停了的」,"
                  "在那个「停了」上长得一模一样。")
        return 2, 行

    # ── 第 ① 关:对照组本来会调更多次吗 ───────────────────────────
    if 基线次数 is None:
        行.append("  ⏸ **这一轮作废:没跑对照组。** 「中断之后 0 次新调用」"
                  "不带对照是证明不了截断的。")
        return 2, 行
    if 基线次数 <= 触发在第几次:
        行.append(f"  ⏸ **这一轮作废:对照组本来就只调了 {基线次数} 次**"
                  f"(触发点是第 {触发在第几次} 次)。")
        行.append("     > 一个「因为中断才只调这么多」的,和一个「本来就只调这么多」的,"
                  "在那个次数上长得一模一样。")
        行.append("     把任务写成必须多次调用,或把触发点提前,再跑。")
        return 2, 行
    行.append(f"  对照组(同任务不发中断)一共调了 **{基线次数}** 次 —— "
              f"所以「停在第 {触发在第几次} 次」确实是被截断的,不是它本来就这样")

    # ── 真判据:中断之后还调了几次工具 ────────────────────────────
    中断后 = [n for n, t in 记 if t > r["中断时刻"]]
    行.append(f"  中断发在第 {触发在第几次} 次调用进行中;"
              f"中断之后工具又被调了 **{len(中断后)}** 次"
              + (f"(第 {中断后} 次)" if 中断后 else ""))

    if r["挂死"]:
        行.append(f"  ❌ **中断之后 {硬超时} 秒内迭代没有结束** —— "
                  f"这不叫停了,叫没停。")
        行.append("     规格 §8:「不能把仍在运行的线程换个名称后当作已经停止」。")
        return 1, 行

    if 中断后:
        行.append("  ❌ **中断之后它又发起了新的工具调用。**")
        行.append("     规格 §1 第 3 条:停止的含义是「服务端**不再发起新的受限调用**」——")
        行.append("     只让迭代器返回而工具还在跑,和真停了,"
                  "在那个「已停止」上长得一模一样。")
        return 1, 行

    用了 = r["结束"] - r["中断时刻"]
    行.append(f"  ✅ **停得下来**:中断之后 0 次新工具调用,"
              f"迭代在 {用了:.1f} 秒内结束。")
    行.append(f"     收到的消息序列:{' → '.join(r['消息们'][-4:])}")
    行.append("  ⚠️ 这证明的是**机制成立**(可中断的客户端形式停得下来),")
    行.append("     **不是** `query()` 能停 —— 见下面静态那一栏。")
    行.append("  ⚠️ 也**不证明外部副作用被撤销**。规格 §6.4:"
              "超时/中断只代表停止等待和停止新调度,")
    行.append("     已经发出去的那一次,结果仍须核实(C21 / C23 验这件事)。")
    return 0, 行


def 静态():
    """`query()` 到底有没有中断方法 —— 规格:**不得假定它有**。"""
    有客户端中断 = hasattr(S.ClaudeSDKClient, "interrupt")
    有stop_task = hasattr(S.ClaudeSDKClient, "stop_task")
    # `query` 是个函数,返回异步生成器 —— 生成器上没有业务级中断方法。
    # 只能 `aclose()`,而那是**调用方放弃读取**,不是告诉执行器停下来。
    query可中断 = any(hasattr(S.query, k) for k in ("interrupt", "stop", "cancel"))
    ver = getattr(S, "__version__", "?")
    return [
        f"  本机实装:claude-agent-sdk **{ver}**"
        f"(⚠️ 依赖文件只声明最低版本,规格 §6.2:不能据此推断机器装的版本)",
        f"  {'❌' if query可中断 else '⏸'} `query()` 上有可调的中断方法:"
        f"**{'有' if query可中断 else '没有'}** —— "
        f"它返回异步迭代器,只能 `aclose()`,而那是**调用方放弃读取**,"
        f"不是告诉执行器停下来",
        f"  {'✅' if 有客户端中断 else '❌'} `ClaudeSDKClient.interrupt()`:"
        f"{'有' if 有客户端中断 else '没有'}",
        f"  {'✅' if 有stop_task else '⏸'} `ClaudeSDKClient.stop_task(task_id)`:"
        f"{'有' if 有stop_task else '没有'}",
        "  → 结论:**现在这条入口(`query()`)停不下来**;要停就得迁到客户端形式。",
        "    而规格明写「先做一个超时测试证明可停止,再扩展」—— 下面就是那个测试。",
    ]


def main():
    print("这条入口停不停得下来(规格 §6.2 要的超时测试)")
    print("=" * 92)
    print(f"  模型写死为 **{模型}**"
          f"(不写死的话,同一条命令在另一台机器上跑的是另一个模型)")
    print("\n▸ 静态:方法在不在")
    for l in 静态():
        print(l)

    if "--static-only" in sys.argv:
        print("\n  ⏸ 只跑了静态那一半。**有方法不等于它真的停得下来** ——")
        print("     去掉 `--static-only` 才会真发一次中断。")
        return 2

    # ── 第 ① 关:对照先跑 ───────────────────────────────────────
    # ⚠️ 顺序是**对照在前**。先跑中断那轮再补对照的话,
    # 「对照本来就只调 2 次」这件事会在已经看到 ✅ 之后才发现 ——
    # 而那时候人已经相信那个 ✅ 了。
    print("\n▸ 对照组:同一个任务,**不发中断**,看它本来会调几次")
    try:
        基 = asyncio.run(跑一轮(发中断=False))
    except Exception as e:
        print(f"  ❌ 对照组跑不起来:{type(e).__name__}: {e}")
        return 1
    基线次数 = len(基["调用记录"])
    print(f"  工具被调了 **{基线次数}** 次"
          + (f";消息序列尾部:{' → '.join(基['消息们'][-3:])}" if 基["消息们"] else ""))
    if 基["挂死"]:
        print(f"  ⏸ 对照组自己就超过了 {硬超时} 秒 —— 这一轮作废,"
              f"**「它本来就跑不完」和「中断让它停了」长得一样**")
        return 2

    print(f"\n▸ 真跑:第 {触发在第几次} 次工具调用进行中发 `interrupt()`")
    try:
        r = asyncio.run(跑一轮(发中断=True))
    except Exception as e:
        print(f"  ❌ 这一轮跑不起来:{type(e).__name__}: {e}")
        print("     ⚠️ **这不是「停不下来」** —— 跑不起来和停不下来是两件事。"
              "先看是不是没有登录态 / 模型名不对。")
        return 1
    码, 行 = 判(r, 基线次数)
    for l in 行:
        print(l)

    print("\n" + "=" * 92)
    print({0: "  ✅ 停得下来(机制成立)",
           1: "  ❌ 停不下来 —— 别在规格里写它能停",
           2: "  ⏸ **这一轮作废,不是通过** —— 什么都没证明,重跑"}[码])
    print("  ⚠️ 这条探针**不进 check.sh**:要真调模型和登录态,"
          "依赖外部状态的检查放进门禁会变成随机拦路。")
    return 码


if __name__ == "__main__":
    sys.exit(main())
