#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent Loop 接真模型的工具调用协议(2026-11-06;用户拍「现在就把执行器做出来」)。不要数据库、不发请求。

**真跑 agent_loop.跑一个agent + 真模型.Agent模型 + 工具协议 + 工具网关**,只把「发出去」那一下换成按剧本回复的假接口。
每一次请求都按 Anthropic 的硬规矩查一遍(红了就是那一轮请求会被接口拒):
工具名只许 [a-zA-Z0-9_-]、assistant 发的每个 tool_use 在下一条 user 里都有同 id 的 tool_result、角色一来一回。

  ① 正常循环:模型用代号调中文名工具 → 网关按**中文名**执行(独立记录为证)→ 结果按 id 回传 → 交结果 → succeeded
  ② 代号只活在这一层:发出去的工具名全是代号、说明里带中文名;agent_loop / 网关看到的全是中文名
  ③ 模型回了一个表里没有的代号 → 网关按没授权拒,不执行;拒的那条回传带 is_error
  ④ 没批准就调写工具 → 网关拒;同一次回复里又交了结果 → 只认工具调用,下一次请求里**没有落单的 tool_use**
  ⑤ 只说一段话 → 不执行(agent_loop 记「只是计划」)、下一轮照常
  ⑥ 交的结果过不了核验 → 下一轮请求里那份候选是一段文字(不是 tool_use),请求照样合法
  ⑦ output_schema 不是 object → 交结果工具包一层 result,收回来拆开
  ⑧ 用量原样带回(input / output / 缓存),execution_mode 标 live
"""
import os
import re
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
for p in (("services", "api", "app", "runtime"), ("services", "api", "app", "contract"), ("services", "api", "app")):
    sys.path.insert(0, os.path.join(根, *p))
import agent_loop as A  # noqa: E402
import dsl as DS  # noqa: E402
import 真模型 as ZM  # noqa: E402
import 工具协议 as TP  # noqa: E402

过, 挂 = [], []
全部接口 = []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


召回 = {"name": "召回名单", "model_description": "按顾问查该回访的客户", "adapter": "Mock召回",
       "side_effect_type": DS.只读,
       "input_schema": {"type": "object", "properties": {"顾问": {"type": "string"}}, "required": ["顾问"]}}
派任务 = {"name": "派回访任务", "model_description": "给顾问派一条回访任务", "adapter": "Mock派任务",
        "side_effect_type": DS.写入,
        "input_schema": {"type": "object", "properties": {"客户": {"type": "string"}}, "required": ["客户"]},
        "confirmation_policy": {"谁批": "店长"}}
目录 = {"召回名单": 召回, "派回访任务": 派任务}
范围 = {"paths": [], "hosts": [], "ids": []}
配置 = {"instructions": "只按工具查到的说。", "task_template": "列出该回访的客户",
        "tools": ["召回名单", "派回访任务"], "limits": {"max_model_turns": 5, "max_tool_attempts": 6},
        "output_schema": {"type": "object", "properties": {"名单": {"type": "array", "items": {"type": "string"}}},
                          "required": ["名单"]}}


def 块(*bs, u=(11, 22)):
    return {"content": list(bs), "model": "claude-haiku-4-5", "stop_reason": "tool_use",
            "usage": {"input_tokens": u[0], "output_tokens": u[1], "cache_read_input_tokens": 3}}


def 用(i, 名, 参):
    return {"type": "tool_use", "id": i, "name": 名, "input": 参}


def 字(t):
    return {"type": "text", "text": t}


class 假接口:
    """按剧本回;记下每一次请求,并逐次按 Anthropic 的硬规矩查。"""

    def __init__(self, 剧本):
        self.剧本, self.请求们, self.违规 = list(剧本), [], []

    def __call__(self, *, 连接, 系统, 消息们, 工具们, 参数=None):
        self.请求们.append({"系统": 系统, "消息们": 消息们, "工具们": 工具们})
        for t in 工具们:
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", t["name"]):
                self.违规.append(f"工具名不合法:{t['name']!r}")
            if (t.get("input_schema") or {}).get("type") != "object":
                self.违规.append(f"input_schema 不是 object:{t['name']}")
            # 11-06 真接口当场打回的那一条(钉回来):参数名也只收这个格式,而参数名是中文
            def _键们(x):
                if isinstance(x, dict):
                    for k, v in (x.get("properties") or {}).items():
                        yield k
                        yield from _键们(v)
                    yield from _键们(x.get("items"))
            坏键 = [k for k in _键们(t.get("input_schema")) if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", k)]
            if 坏键:
                self.违规.append(f"参数名不合法({t['name']}):{坏键}")
        if not 消息们 or 消息们[0]["role"] != "user":
            self.违规.append("第一条不是 user")
        for a, b in zip(消息们, 消息们[1:]):
            if a["role"] == b["role"]:
                self.违规.append(f"连着两条 {a['role']}")
        for k, m in enumerate(消息们):
            if m["role"] != "assistant":
                continue
            要 = {x["id"] for x in m["content"] if x.get("type") == "tool_use"}
            if not 要:
                continue
            下 = 消息们[k + 1] if k + 1 < len(消息们) else None
            有 = {x.get("tool_use_id") for x in (下 or {}).get("content", []) if x.get("type") == "tool_result"}
            if 要 - 有:
                self.违规.append(f"tool_use 落单(下一条没有对应的 tool_result):{sorted(要 - 有)}")
        if not self.剧本:
            raise AssertionError("剧本用完了,模型又被调了一次")
        return self.剧本.pop(0)


def 跑(剧本, *, 配置改=None, 批准=None):
    接口 = 假接口(剧本)
    全部接口.append(接口)
    记录, 事件 = [], []
    r = A.跑一个agent(
        dict(配置, **(配置改 or {})), {"顾问": "林岚"},
        适配器={"model": ZM.Agent模型({"endpoint": "x", "secret_ref": "env://X"},
                                     输出Schema=dict(配置, **(配置改 or {}))["output_schema"], 发=接口),
                "Mock召回": lambda 参: (记录.append(("召回名单", 参)), {"客户": ["C10001", "C10002"]})[1],
                "Mock派任务": lambda 参: (记录.append(("派回访任务", 参)), {"任务": "tk1"})[1]},
        工具目录=目录, 有效范围=范围, 记事=lambda 种, 载: 事件.append((种, 载)),
        批准查询=批准, run_id="ap1")
    return r, 接口, 记录, 事件


def main():
    # ① + ② + ⑧
    r, 接口, 记录, 事件 = 跑([
        块(字("先查一下"), 用("tu_1", "t1", {"p1": "林岚"})),
        块(用("tu_2", TP.交结果, {"p1": ["C10001", "C10002"]})),
    ])
    ck("① 正常循环:用代号调中文名工具 → 网关按中文名执行一次 → 交结果 → succeeded",
       r["execution_status"] == "succeeded" and 记录 == [("召回名单", {"顾问": "林岚"})]
       and r["output"] == {"名单": ["C10001", "C10002"]}, (r["execution_status"], 记录, r["output"], r["validation_results"]))
    第二次 = 接口.请求们[1]["消息们"]
    回传 = [x for m in 第二次 if m["role"] == "user" for x in m["content"] if x.get("type") == "tool_result"]
    ck("① 工具结果按 id 回传(tool_use_id = 模型给的那个 id、内容里有工具真返回的客户)",
       len(回传) == 1 and 回传[0]["tool_use_id"] == "tu_1" and "C10001" in 回传[0]["content"], 回传)
    名们 = [t["name"] for t in 接口.请求们[0]["工具们"]]
    ck("② 发出去的工具名全是代号(t1、t2 + 交结果 + 问人),中文名只在说明里",
       名们 == ["t1", "t2", TP.交结果, TP.问人] and "「召回名单」" in 接口.请求们[0]["工具们"][0]["description"], 名们)
    ck("② 系统提示单独一个字段,不混进消息", 接口.请求们[0]["系统"] == 配置["instructions"], 接口.请求们[0]["系统"])
    回放 = [x for m in 第二次 if m["role"] == "assistant" for x in m["content"] if x.get("type") == "tool_use"]
    ck("② 下一轮重组的 assistant 那条用回代号 —— 工具名和参数名都是(t1 / p1,不是中文)",
       [x["name"] for x in 回放] == ["t1"] and 回放[0]["input"] == {"p1": "林岚"}, 回放)
    参数说明 = 接口.请求们[0]["工具们"][0]["input_schema"]["properties"]
    ck("④ 参数名换成代号、说明里写着中文原名;模型回的代号参数还原成中文键交给网关(工具真收到「顾问」)",
       list(参数说明) == ["p1"] and "「顾问」" in 参数说明["p1"]["description"] and 记录 == [("召回名单", {"顾问": "林岚"})], (参数说明, 记录))
    用量们 = [载["用量"] for 种, 载 in 事件 if 种 == "model.response"]
    ck("⑧ 用量原样带回(input / output / 缓存读)", 用量们 and 用量们[0]["input_tokens"] == 11
       and 用量们[0]["output_tokens"] == 22 and 用量们[0]["cache_read_tokens"] == 3, 用量们)

    # ③
    r, 接口, 记录, 事件 = 跑([
        块(用("tu_1", "t9", {"x": 1})),
        块(用("tu_2", TP.交结果, {"p1": []})),
    ])
    拒 = [x for m in 接口.请求们[1]["消息们"] for x in m["content"] if x.get("type") == "tool_result"]
    ck("③ 表里没有的代号 → 网关拒、不执行,拒的那条回传带 is_error",
       记录 == [] and 拒 and 拒[0].get("is_error") is True and any(种 == "tool.rejected" for 种, _ in 事件), (记录, 拒))

    # ④
    r, 接口, 记录, 事件 = 跑([
        块(用("tu_1", "t2", {"p1": "C10001"}), 用("tu_x", TP.交结果, {"p1": ["C10001"]})),
        块(用("tu_2", TP.交结果, {"p1": ["C10001"]})),
    ])
    ck("④ 没批准调写工具 → 网关拒、一次没写", 记录 == [] and any(种 == "tool.rejected" for 种, _ in 事件), 记录)
    ck("④ 同一次回复里又交了结果 → 只认工具调用,下一次请求没有落单的 tool_use(交结果那块丢掉)",
       not any("tu_x" == x.get("id") for m in 接口.请求们[1]["消息们"] for x in m["content"]) and not 接口.违规, 接口.违规)

    # ⑤
    r, 接口, 记录, 事件 = 跑([块(字("我打算先查召回名单")), 块(用("tu_2", TP.交结果, {"p1": []}))])
    ck("⑤ 只说一段话 → 不执行、记「只是计划」,下一轮照常交卷",
       记录 == [] and any(种 == "model.plan_only" for 种, _ in 事件) and r["execution_status"] == "succeeded", r["execution_status"])

    # ⑥
    r, 接口, 记录, 事件 = 跑([块(用("tu_1", TP.交结果, {"别的": 1})), 块(用("tu_2", TP.交结果, {"p1": ["C1"]}))])
    第二次 = 接口.请求们[1]["消息们"]
    ck("⑥ 交的结果没过核验 → 下一轮那份候选是一段文字、后面跟「没通过核验」,请求合法",
       r["execution_status"] == "succeeded" and not 接口.违规
       and any(m["role"] == "assistant" and m["content"][0].get("type") == "text" for m in 第二次)
       and "没通过核验" in str(第二次[-1]), (接口.违规, 第二次[-2:]))

    # ⑦
    工具们, _, 拆 = TP.工具们([], {"type": "array", "items": {"type": "string"}})
    交 = [t for t in 工具们 if t["name"] == TP.交结果][0]
    ck("⑦ output_schema 不是 object → 交结果包一层 result,收回来拆开",
       拆 and 交["input_schema"]["type"] == "object" and "result" in 交["input_schema"]["properties"]
       and TP.解析(块(用("i", TP.交结果, {"result": ["a"]})), {}, 拆) ["finish"] == ["a"], 交)

    # 每一次请求的硬规矩
    违规们 = [v for x in 全部接口 for v in x.违规]
    ck(f"每一次请求都合法(工具名、角色一来一回、tool_use 都有回)—— 上面各段合计 {sum(len(x.请求们) for x in 全部接口)} 次请求",
       not 违规们 and sum(len(x.请求们) for x in 全部接口) >= 10, 违规们)
    ck("⑧ Agent模型 标 execution_mode=live、带实际型号",
       ZM.Agent模型({}, 发=lambda **k: 块(字("hi")))([{"role": "user", "content": "x"}], [])["execution_mode"] == "live")

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ Agent 工具调用协议:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
