#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流执行器里的 Agent 步骤(2026-11-06)。不要数据库。真调 compiler.编译 + runner.跑一张图,Agent 适配器是假的(只验执行器这一层)。

为什么单独一份:e2e(test_agent_step_flow)打的服务和常驻 worker 跑的是**主检出**的代码,咬合在副本里改坏 runner 打不准;
执行器是纯的(适配器从外面给),这一层的咬合放这里。

  ① Agent 步骤拿到的输入按 input_mapping 现取、任务按 task_binding(字面量原样 / 引用现取)、带着父流程剩余回合
  ② Agent 适配器抛 需要等待 → 整张图挂起,检查点的等待载荷里带着 Agent 自己的检查点
  ③ 恢复:**回执交回 Agent 适配器**(带检查点),不当成这一步的输出;Agent 交卷的那份才是这一步的输出、结束节点拿到它
  ④ 挂起前那一段 + 恢复后那一段用掉的回合都计入父流程(§6.1 子任务消耗计入父任务额度)
  ⑤ 恢复时不重跑开始节点、Agent 适配器只被调了两次(挂起前 1、恢复后 1)
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "contract"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


入 = {"type": "object", "required": ["顾问"], "properties": {"顾问": {"type": "string"}}}
出 = {"type": "object", "required": ["名单"], "properties": {"名单": {"type": "array"}}}
图 = {"definition_schema_version": "1", "kind": "workflow", "input_schema": 入, "output_schema": 出,
      "nodes": [{"id": "start", "type": "start", "config": {"input_schema": 入}},
                {"id": "a1", "type": "agent", "config": {"agent_version_id": "agv_x", "task_binding": "列出该回访的客户",
                                                         "input_mapping": {"顾问": {"source": "input", "pointer": "/顾问"}},
                                                         "sub_limits": {"max_model_turns": 4}}},
                {"id": "finish", "type": "end", "config": {"bindings": {"名单": {"source": "node", "node_id": "a1", "pointer": "/名单"}},
                                                          "output_schema": 出}}],
      "edges": [{"port": "success", "source": "start", "target": "a1"}, {"port": "success", "source": "a1", "target": "finish"}]}


class 假Agent:
    def __init__(self):
        self.收到 = []

    def __call__(self, cfg, 包):
        self.收到.append(包)
        if not 包.get("续"):
            raise RN.需要等待("external", {"工具": "召回名单", "参数": {"上限": 5},
                                          "agent检查点": {"回合": 1, "工具尝试": 1, "记号": "第一段"},
                                          "本段用量": {"模型回合": 1, "工具尝试": 1}})
        return {"名单": ["C1"] + 包["续"]["结果"]["客户"], "本段用量": {"模型回合": 1, "工具尝试": 0}}


def main():
    计划 = CP.编译(图, 依赖存在=lambda 种类, i: True)
    a = 假Agent()
    r1 = RN.跑一张图(计划, {"顾问": "林岚"}, 适配器={"agent": a}, run_id="as1", 上限={"max_model_turns": 10})
    包 = a.收到[0] if a.收到 else {}
    ck("① Agent 拿到的输入按 input_mapping 现取、任务是 task_binding 的字面量、带着父流程剩余回合(10)",
       包.get("输入") == {"顾问": "林岚"} and 包.get("任务") == "列出该回访的客户" and 包.get("父流程剩余回合") == 10
       and 包.get("node_id") == "a1", 包)
    点 = r1.get("检查点") or {}
    ck("② 适配器要等 → 整张图挂起,等待载荷里带着 Agent 自己的检查点",
       r1["执行状态"] == "waiting_external" and 点.get("从") == "a1"
       and ((点.get("等待") or {}).get("载荷") or {}).get("agent检查点", {}).get("记号") == "第一段", (r1["执行状态"], 点.get("等待")))
    r2 = RN.跑一张图(计划, {"顾问": "林岚"}, 适配器={"agent": a}, run_id="as1", 上限={"max_model_turns": 10},
                   恢复={**点, "结果": {"客户": ["IT-C9"]}})
    续 = (a.收到[1] if len(a.收到) > 1 else {}).get("续") or {}
    ck("③ 恢复:回执交回 Agent 适配器(带它自己的检查点),而不是当成这一步的输出",
       续.get("结果") == {"客户": ["IT-C9"]} and (续.get("检查点") or {}).get("记号") == "第一段", 续)
    ck("③ Agent 交卷的那份才是这一步的输出,结束节点拿到它 → 整条 succeeded",
       r2["执行状态"] == "succeeded" and (r2.get("输出") or {}).get("名单") == ["C1", "IT-C9"], (r2["执行状态"], r2.get("输出")))
    ck("④ 挂起前一段 + 恢复后一段的回合都计入父流程(1 + 1 = 2)", (r2.get("用量") or {}).get("模型调用") == 2, r2.get("用量"))
    ck("⑤ Agent 适配器一共只被调了两次(挂起前 1、恢复后 1)", len(a.收到) == 2, len(a.收到))
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 执行器里的 Agent 步骤:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
