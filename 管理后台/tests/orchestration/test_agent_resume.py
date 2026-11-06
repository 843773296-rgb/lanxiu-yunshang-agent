#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent 断点续跑(2026-11-06;用户拍「走桥,给 Agent 加断点续跑」)。不要数据库、不发请求。

真跑 agent_loop.跑一个agent + tool_gateway;工具适配器抛 `要等`(和 worker 里接澜绣桥的那一支同一个形状),
断点**过一遍 JSON**(证明存得进 resume_snapshot),再带着回执续跑。判据落在**独立记录**上(工具真被调几次、模型真被问几次)。

  ① 只读工具要等桥 → 挂起、带断点和载荷;挂起期间不再问模型;续跑后模型拿到回执、交卷 → succeeded;工具只调一次
  ② 一次回复里两个调用、第一个挂起 → 续跑后第二个接着执行,回传顺序 = 调用顺序
  ③ 批准过的写工具要等桥 → 挂起时账本「已提交」;续跑后「成功」、**不再过网关、不写第二次**
  ④ 桥那边执行失败 → 模型收到「被拒」(BRIDGE_FAILED),账本记失败,不伪造成功
  ⑤ 回合数接着数、不清零:上限 1 回合,续跑后不再问模型 → 按回合用完停
  ⑥ 走真翻译层(真模型.Agent模型 + 工具协议):断点存过再取,续跑那一次请求照样合法(tool_use 都有回)
  ⑦ 网关对「要等」原样放行:不记待核实、不当成执行出错
"""
import json
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
for p in (("services", "api", "app", "runtime"), ("services", "api", "app", "contract"), ("services", "api", "app")):
    sys.path.insert(0, os.path.join(根, *p))
import agent_loop as A  # noqa: E402
import dsl as DS  # noqa: E402
import tool_gateway as G  # noqa: E402
import 真模型 as ZM  # noqa: E402
import 工具协议 as TP  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


召回 = {"name": "召回名单", "model_description": "查该回访的客户", "adapter": "桥", "side_effect_type": DS.只读,
       "input_schema": {"type": "object", "properties": {"顾问": {"type": "string"}}, "required": ["顾问"]}}
库存 = {"name": "补货预警", "model_description": "查一个 SKU 的档", "adapter": "桥", "side_effect_type": DS.只读,
       "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}}
派 = {"name": "派回访任务", "model_description": "派一条回访", "adapter": "桥", "side_effect_type": DS.写入,
     "input_schema": {"type": "object", "properties": {"客户": {"type": "string"}}, "required": ["客户"]},
     "confirmation_policy": {"谁批": "店长"}, "idempotency_strategy": {"键": "logical_action_id"},
     "external_status_lookup": {"supported": True}}
目录 = {"召回名单": 召回, "补货预警": 库存, "派回访任务": 派}
范围 = {"paths": [], "hosts": [], "ids": []}
配置 = {"instructions": "按工具查到的说", "task_template": "列出该回访的客户",
        "tools": ["召回名单", "补货预警", "派回访任务"], "limits": {"max_model_turns": 5, "max_tool_attempts": 6},
        "output_schema": {"type": "object", "properties": {"名单": {"type": "array"}}, "required": ["名单"]}}


class 脚本模型:
    def __init__(self, 回答们):
        self.回答们, self.被调, self.看到 = list(回答们), 0, []

    def __call__(self, 消息们, 工具定义们):
        self.被调 += 1
        self.看到.append(json.loads(json.dumps(消息们, ensure_ascii=False, default=str)))
        if not self.回答们:
            raise AssertionError("脚本用完了,模型又被调了一次")
        return dict(self.回答们.pop(0), usage={"input_tokens": 1, "output_tokens": 1})


class 桥:
    """独立记录:真被「交给桥」几次、交了什么。"""

    def __init__(self):
        self.交过 = []

    def __call__(self, 参):
        self.交过.append(参)
        raise G.要等({"工具": "?", "参数": 参})


def 调(i, 名, 参):
    return {"id": i, "name": 名, "arguments": 参}


交卷 = {"finish": {"名单": ["C10001"]}}


def 跑(模型, *, 恢复=None, 配置改=None, 账本=None, 批准=None, b=None):
    事件 = []
    b = b or 桥()
    r = A.跑一个agent(dict(配置, **(配置改 or {})), {"顾问": "林岚"}, 适配器={"model": 模型, "桥": b},
                    工具目录=目录, 有效范围=范围, 账本=账本, 记事=lambda k, v: 事件.append((k, v)),
                    批准查询=批准, run_id="rs1", 恢复=恢复)
    return r, 事件, b


def 存取(r):
    """断点过一遍 JSON —— worker 把它写进 resume_snapshot(jsonb),取出来就是这个样子。"""
    return json.loads(json.dumps(r["检查点"], ensure_ascii=False, default=str))


def main():
    # ①
    m = 脚本模型([{"tool_calls": [调("c1", "召回名单", {"顾问": "林岚"})]}, 交卷])
    r1, ev1, b = 跑(m)
    ck("① 只读工具要等桥 → 挂起(waiting_external),带断点和等的是哪个工具、什么参数",
       r1["execution_status"] == "waiting_external" and r1["等待"]["载荷"]["参数"] == {"顾问": "林岚"}
       and r1["检查点"]["第几个"] == 0, (r1["execution_status"], r1.get("等待")))
    ck("① 挂起期间不再问模型(只问了 1 次)、真交给桥 1 次", m.被调 == 1 and len(b.交过) == 1, (m.被调, b.交过))
    点 = 存取(r1)
    r2, ev2, b2 = 跑(m, 恢复={"检查点": 点, "结果": {"客户": ["C10001"]}})
    最后 = m.看到[-1]
    ck("① 续跑:模型拿到回执(工具结果里有 C10001)、交卷 → succeeded;桥一次没再调",
       r2["execution_status"] == "succeeded" and r2["output"] == {"名单": ["C10001"]} and b2.交过 == []
       and 最后[-1]["role"] == "tool" and "C10001" in json.dumps(最后[-1], ensure_ascii=False), (r2["execution_status"], 最后[-1:]))
    ck("① 续跑记一笔「从断点接着」、回执记一笔", any(k == "agent.resumed" for k, _ in ev2)
       and any(k == "tool.receipt_applied" for k, _ in ev2), [k for k, _ in ev2][:6])

    # ②
    m = 脚本模型([{"tool_calls": [调("c1", "召回名单", {"顾问": "林岚"}), 调("c2", "补货预警", {"sku": "S1"})]}, 交卷])
    r1, _, b = 跑(m)
    第二 = 桥()
    r2, _, b2 = 跑(m, 恢复={"检查点": 存取(r1), "结果": {"客户": ["C1"]}}, b=第二)
    回 = m.看到[-1][-1]["content"]
    ck("② 一次两个调用、第一个挂起 → 只交了第一个;续跑后第二个接着交给桥(又挂起在第 2 个)",
       len(b.交过) == 1 and r2["execution_status"] == "waiting_external" and r2["检查点"]["第几个"] == 1
       and 第二.交过 == [{"sku": "S1"}], (b.交过, 第二.交过, r2.get("检查点", {}).get("第几个")))
    r3, _, _ = 跑(m, 恢复={"检查点": 存取(r2), "结果": {"档": "快没了"}})
    回 = m.看到[-1][-1]["content"]
    ck("② 两个都回执之后模型才被问下一轮,回传顺序 = 调用顺序(c1、c2)",
       r3["execution_status"] == "succeeded" and [x["tool_call_id"] for x in 回] == ["c1", "c2"] and m.被调 == 2, 回)

    # ③ + ⑦
    账 = G.内存账本()
    m = 脚本模型([{"tool_calls": [调("c1", "派回访任务", {"客户": "C10001"})]}, 交卷])
    批 = lambda 调, 摘: {"参数摘要": 摘, "批准人": "店长", "过期了吗": False}  # noqa: E731
    r1, ev1, b = 跑(m, 账本=账, 批准=批)
    条 = list(账.条目.values())
    ck("③ 批准过的写工具要等桥 → 挂起,账本停在「已提交」(不是失败、不是待核实)",
       r1["execution_status"] == "waiting_external" and 条 and 条[0]["状态"] == "submitted", 条)
    ck("⑦ 网关对「要等」原样放行:没记 tool.error、没标待核实,记了 tool.waiting_external",
       not any(k == "tool.error" for k, _ in ev1) and any(k == "tool.waiting_external" for k, _ in ev1)
       and r1["等待"]["载荷"].get("动作id"), [k for k, _ in ev1])
    r2, _, b2 = 跑(m, 账本=账, 批准=批, 恢复={"检查点": 存取(r1), "结果": {"任务": "tk9"}})
    ck("③ 续跑:账本「成功」、结果是回执;桥没再调(**不写第二次**)",
       r2["execution_status"] == "succeeded" and list(账.条目.values())[0]["状态"] == "succeeded"
       and list(账.条目.values())[0]["结果"] == {"任务": "tk9"} and b2.交过 == [], list(账.条目.values()))

    # ④
    账 = G.内存账本()
    m = 脚本模型([{"tool_calls": [调("c1", "派回访任务", {"客户": "C10001"})]}, 交卷])
    r1, _, _ = 跑(m, 账本=账, 批准=批)
    r2, _, _ = 跑(m, 账本=账, 批准=批, 恢复={"检查点": 存取(r1), "结果": {"失败": {"code": "客户不存在"}}})
    回 = m.看到[-1][-1]["content"][0]
    ck("④ 桥那边执行失败 → 模型收到「被拒」(BRIDGE_FAILED、带原因),账本记失败,不伪造成功",
       回.get("rejected", {}).get("code") == "BRIDGE_FAILED" and "客户不存在" in 回["rejected"]["reason"]
       and list(账.条目.values())[0]["状态"] == "failed", (回, list(账.条目.values())))

    # ⑤
    # 多备一句交卷:回合要是被清零,模型会被多问一次并交卷成功 —— 这一条要看得见那种错法,不能让剧本用完先崩
    m = 脚本模型([{"tool_calls": [调("c1", "召回名单", {"顾问": "林岚"})]}, 交卷])
    r1, _, _ = 跑(m, 配置改={"limits": {"max_model_turns": 1, "max_tool_attempts": 6}})
    r2, _, _ = 跑(m, 配置改={"limits": {"max_model_turns": 1, "max_tool_attempts": 6}},
                恢复={"检查点": 存取(r1), "结果": {"客户": []}})
    ck("⑤ 回合数接着数(上限 1):续跑后不再问模型 → 按回合用完停(incomplete / max_turns)",
       r2["execution_status"] == "incomplete" and r2["completion_reason"] == "max_turns" and m.被调 == 1
       and r2["usage"]["模型回合"] == 1, (r2["execution_status"], r2["completion_reason"], m.被调))

    # ⑥
    请求们, 剧本 = [], [
        {"content": [{"type": "tool_use", "id": "tu_1", "name": "t1", "input": {"p1": "林岚"}}], "usage": {}},
        {"content": [{"type": "tool_use", "id": "tu_2", "name": TP.交结果, "input": {"p1": ["C1"]}}], "usage": {}}]

    def 发(**k):
        请求们.append(k["消息们"])
        return 剧本.pop(0)
    模 = ZM.Agent模型({}, 输出Schema=配置["output_schema"], 发=发)
    r1, _, _ = 跑(模)
    r2, _, _ = 跑(模, 恢复={"检查点": 存取(r1), "结果": {"客户": ["C1"]}})
    续那次 = 请求们[-1]
    要 = {x["id"] for m_ in 续那次 if m_["role"] == "assistant" for x in m_["content"] if x.get("type") == "tool_use"}
    有 = {x.get("tool_use_id") for m_ in 续那次 if m_["role"] == "user" for x in m_["content"] if x.get("type") == "tool_result"}
    ck("⑥ 走真翻译层:断点存过再取,续跑那次请求里 tool_use 都有对应的 tool_result、工具名参数名都是代号",
       r2["execution_status"] == "succeeded" and 要 == {"tu_1"} and 要 <= 有
       and any(x.get("input") == {"p1": "林岚"} for m_ in 续那次 for x in m_["content"] if x.get("type") == "tool_use"),
       (r2["execution_status"], 要, 有))

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ Agent 断点续跑:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
