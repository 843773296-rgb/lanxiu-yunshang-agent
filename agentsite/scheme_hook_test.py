#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「当前方案」注入 · 离线自测 —— 不调模型,一分钱不花。

## 这是「一件事」那条线里,真正属于 Agent Loop 的那一处

顾问刚问完报价,接着说「那就按这个下单吧」—— **agent 不知道「这个」指哪一份**。
原来它只能从对话文本里猜,而猜错和猜对**在答复里长得一模一样**,
直到它按错误的配置下了单。

修法不是让模型记得更牢,是**把方案号放进 harness 留给我们的 `state` 里**:

    PostToolUse   按号取过一份方案 → 记进 state["当前方案"]
    UserPrompt    下一轮开头把它注回去

**为什么不靠模型自己记**:自动压缩压的是「读起来连贯」,不是「标识不丢」。
压完之后模型很可能仍然记得「在聊一套唐制襦裙」,却**丢掉了 SC2601 这个号** ——
而这两种状态在对话里长得一模一样。

## 最要紧的一条:**列清单不算「取过」**

业务 2026-09-18 定了「一个客户可以多条方案同时锁定」,
所以「锁定那条」不是唯一标识,消歧只能靠方案号。

如果列了一遍清单就顺手把第一条当成「当前方案」,
等于**把刚堵死的那条捷径从后门放回来** —— 而且更隐蔽:
模型没挑,是 hook 替它挑的,**而 hook 不出现在对话里,没人看得见它挑过**。

下面第 ② 条专门钉这个。
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import api

FAIL = []


def 跑(fn, *a):
    # Python 3.14 起 `get_event_loop()` 在没有运行中的循环时直接抛错,
    # 不再自动建一个 —— 用 `asyncio.run` 每次现开一个。
    return asyncio.run(fn(*a))


def 造hook(state):
    """只取我们要测的那两个 hook,不碰 SDK —— `make_hooks` 里要 import
    `claude_agent_sdk`,而那个只装在 venv 里。这里把两段逻辑单独复刻是不行的
    (那就成了第二份实现),所以改成:直接调 `make_hooks`,拿不到就跳过并**报红**。"""
    import guards
    return guards.make_hooks(state)


def ck(name, ok, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}{'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)


def main():
    print("「当前方案」注入 · 离线自测(不调模型)")
    print("=" * 80)
    try:
        import guards
    except Exception as e:
        print(f"❌ 连 guards 都导不进来:{e}")
        return 1

    # 真实取一份方案,不手写返回结构 —— 接口结构改了这里要一起红
    单 = api.get_scheme(scheme_id=_一个方案号())
    if not 单 or 单.get("error"):
        print(f"❌ 取不到样本方案:{单}")
        return 1

    state = {}
    hooks = 造hook(state)
    on_prompt = hooks["UserPromptSubmit"][0].hooks[0]
    post_tool = hooks["PostToolUse"][0].hooks[0]

    # ── ① 按号取过单条 → 下一轮注进去 ────────────────────────────
    跑(post_tool, {"tool_name": "mcp__shop__get_scheme",
                  "tool_input": {"scheme_id": 单["方案号"]},
                  "tool_response": 单}, None, None)
    有没有记 = state.get("当前方案", {}).get("号") == 单["方案号"]
    r = 跑(on_prompt, {"prompt": "就按这个下单吧"}, None, None)
    注入 = (r.get("hookSpecificOutput") or {}).get("additionalContext", "")
    ck("① 按号取过一份方案之后,下一轮把方案号注回去",
       有没有记 and 单["方案号"] in 注入,
       f"注入里带上了 {单['方案号']}" if 有没有记 and 单["方案号"] in 注入 else
       f"记了 {有没有记};注入片段:{注入[-120:]}")

    # ── ② 列清单**不算**取过 ─────────────────────────────────────
    #    这是这套自测最要紧的一条,理由见文件头。
    state2 = {}
    hooks2 = 造hook(state2)
    清单 = api.get_scheme(customer=单["客户号"])
    跑(hooks2["PostToolUse"][0].hooks[0],
       {"tool_name": "mcp__shop__get_scheme",
        "tool_input": {"customer": 单["客户号"]},
        "tool_response": 清单}, None, None)
    r2 = 跑(hooks2["UserPromptSubmit"][0].hooks[0], {"prompt": "就按那个下单"}, None, None)
    注2 = (r2.get("hookSpecificOutput") or {}).get("additionalContext", "")
    ck("② 列清单不算「取过」,不许替模型挑一条",
       "当前方案" not in state2 and "本次会话里已经明确取过" not in 注2,
       f"清单里有 {清单.get('hit')} 条;state 里 {'记了' if '当前方案' in state2 else '没记'}"
       + (" —— **hook 替模型挑了一条,而 hook 不出现在对话里,没人看得见它挑过**"
          if "当前方案" in state2 else ""))

    # ── ③ 没取过方案时,不许凭空注入 ──────────────────────────────
    state3 = {}
    r3 = 跑(造hook(state3)["UserPromptSubmit"][0].hooks[0],
           {"prompt": "今天有什么活"}, None, None)
    注3 = (r3.get("hookSpecificOutput") or {}).get("additionalContext", "")
    ck("③ 没取过方案时不注入方案号", "本次会话里已经明确取过" not in 注3,
       "一轮都没查过方案却报出一个号,那是**凭空造出来的上下文**")

    # ── ④ 注入里必须写明「推进前仍要确认」 ───────────────────────
    #    注入的是**提示**不是**结论**。少了这句,模型会把它当成已确认,
    #    而「这个」到底指哪一份,最终得由人点头。
    ck("④ 注入里带着「推进前仍要把号说出来让人确认」",
       "确认" in 注入 and "以客户说的为准" in 注入,
       "注入的是提示不是结论 —— 少了这句,模型会把 hook 的记忆当成人的确认")

    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 「当前方案」注入 4 条全过")
    return 0


def _一个方案号():
    """**按性质挑,不写死编号。** 写死的 id 会被一次合理的数据变更打断,
    而打断时这里只会说「取不到样本」,像是功能坏了。"""
    r = api._rows("SELECT id FROM scheme WHERE status='已锁定' ORDER BY id LIMIT 1")
    return r[0]["id"] if r else None


咬合 = [
    ('把 on_prompt 里注入当前方案那一段去掉', '① 按号取过一份方案之后'),
    ('让 post_tool 列清单时也记「当前方案」(替模型挑第一条)', '② 列清单不算「取过」'),
]

if __name__ == "__main__":
    sys.exit(main())
