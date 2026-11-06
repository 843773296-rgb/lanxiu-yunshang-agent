#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent Loop ↔ Anthropic Messages 工具调用协议的**翻译**(2026-11-06;用户拍「现在就把执行器做出来」)。

不发请求、不碰库 —— 纯翻译,离线可测。发请求在 `真模型.对话一轮`,拼起来在 `真模型.Agent模型`。

## 两边各说各的

agent_loop 的内部说法(`agent_loop.跑一个agent`):
    消息们 = [{"role": "system", "content": 指令},
             {"role": "user", "content": {"任务": …, "输入": …}},
             {"role": "assistant", "content": 响应 / 候选 / 文字},
             {"role": "tool", "content": [{"tool_call_id", "name", "result" | "rejected"}]}, …]
    响应 = {"tool_calls": [{"id", "name", "arguments"}]} | {"finish": 候选} | {"clarification": 问} | {"text": 文}

Anthropic Messages:system 单独一个字段;assistant 发 `tool_use` 块,下一条 user **必须**逐个回 `tool_result`(按 id)。

## 三个要点

① **工具名换代号。** Anthropic 只收 `^[a-zA-Z0-9_-]{1,64}$`,而这个项目的工具名是中文(召回名单 / 派回访任务 …)。
  代号**只活在这一层**:发出去之前换、收回来立刻翻回中文名,再交给 agent_loop → 工具网关。
  判据、提示词、白名单看到的永远是中文名 —— 不会冒出同一个工具的第二个名字。
  代号按工具定义的顺序给(t1、t2 …),同一个 Agent 每一轮的工具清单同序,所以每轮同一套代号;
  模型回了一个**表里没有的代号** → 原样交出去,网关按「没授权的工具」拒(不猜它想调哪个)。

② **「完成」是一个交结果的工具**(`submit_result`),参数格式就是 Agent 版本的 output_schema。
  模型交的结果天然是结构化的 —— 不从一段话里抠 JSON(那是「拿关键词判成段的话」的同一族错)。
  同一次回复里既交结果又调别的工具 → **只认工具调用**,交结果那一块丢掉(agent_loop 本来就先看 tool_calls),
  下一轮重组时也不带它 —— 否则那个 tool_use 没有对应的 tool_result,下一次请求会被接口拒。

④ **参数名也换代号**(11-06 真接口当场打回:`input_schema.properties` 的键也只收 `^[a-zA-Z0-9_.-]{1,64}$`,
  而参数名是中文「顾问」「名单」—— 离线假接口只查了工具名,14 条全绿;那条真报错已钉回 test_agent_protocol)。
  一层层换(嵌套对象 / 数组里的对象也换),说明里写上中文原名;收回来按同一张表一层层还原。合法的英文键不动。

③ **assistant 那一轮按内部说法重组,不留原始块。** 核验没过的候选结论重组成一段文字(不是 tool_use),
  所以它后面跟的「没通过核验」可以是普通 user 消息。
"""
import json as _json
import re as _re

_合法键 = _re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")

交结果 = "submit_result"
问人 = "ask_human"


def _文(x):
    return x if isinstance(x, str) else _json.dumps(x, ensure_ascii=False, default=str)


def 代号表(工具定义们):
    """→ {代号: 原名}。按清单顺序给,每轮同序就同号。"""
    return {f"t{i}": (t.get("name") or "") for i, t in enumerate(工具定义们 or [], 1)}


def _换键(schema):
    """→ (发出去的 schema, 回表)。回表 = {"键": {代号: (原名, 子回表)}, "项": 子回表};不合法的键换成 p1、p2 …"""
    if not isinstance(schema, dict):
        return schema, {}
    新, 回 = dict(schema), {}
    if isinstance(schema.get("properties"), dict):
        已有 = {k for k in schema["properties"] if _合法键.match(k)}
        属, 键回, n = {}, {}, 0
        for k, v in schema["properties"].items():
            子, 子回 = _换键(v)
            if _合法键.match(k):
                代 = k
            else:
                n += 1
                while f"p{n}" in 已有:
                    n += 1
                代 = f"p{n}"
                子 = dict(子) if isinstance(子, dict) else {"description": str(子)}
                子["description"] = f"「{k}」" + (("—— " + 子["description"]) if 子.get("description") else "")
            属[代] = 子
            键回[代] = (k, 子回)
        新["properties"] = 属
        回["键"] = 键回
        if isinstance(schema.get("required"), list):
            正 = {原: 代 for 代, (原, _) in 键回.items()}
            新["required"] = [正.get(k, k) for k in schema["required"]]
    if isinstance(schema.get("items"), dict):
        新["items"], 回["项"] = _换键(schema["items"])
    return 新, 回


def _还(值, 回):
    """收回来:代号 → 原名,一层层。"""
    if not 回:
        return 值
    if isinstance(值, dict) and 回.get("键"):
        return {(回["键"][k][0] if k in 回["键"] else k): _还(v, 回["键"][k][1] if k in 回["键"] else {})
                for k, v in 值.items()}
    if isinstance(值, list) and 回.get("项"):
        return [_还(v, 回["项"]) for v in 值]
    return 值


def _换(值, 回):
    """发出去(重组历史里的工具参数):原名 → 代号,一层层。"""
    if not 回:
        return 值
    if isinstance(值, dict) and 回.get("键"):
        正 = {原: (代, 子) for 代, (原, 子) in 回["键"].items()}
        return {(正[k][0] if k in 正 else k): _换(v, 正[k][1] if k in 正 else {}) for k, v in 值.items()}
    if isinstance(值, list) and 回.get("项"):
        return [_换(v, 回["项"]) for v in 值]
    return 值


def _对象schema(s):
    """Anthropic 的 input_schema 必须是 object。→ (schema, 要不要拆包)。"""
    if isinstance(s, dict) and s.get("type") == "object":
        return s, False
    if not s:
        return {"type": "object"}, False
    return {"type": "object", "properties": {"result": s}, "required": ["result"]}, True


class 代号们(dict):
    """{工具代号: 原名},外加 `.键表` = {工具代号 / 交结果: 参数的回表}。"""
    键表 = None


def 工具们(工具定义们, 输出Schema):
    """→ (发给 Anthropic 的 tools, 代号们, 交结果要不要拆包)。工具名和参数名都换成代号。"""
    号 = 代号们(代号表(工具定义们))
    号.键表 = {}
    出 = []
    for (代, 名), t in zip(号.items(), 工具定义们 or []):
        sch, 号.键表[代] = _换键(_对象schema(t.get("input_schema"))[0])
        出.append({"name": 代,
                   "description": f"「{名}」" + (("—— " + t["description"]) if t.get("description") else ""),
                   "input_schema": sch})
    s, 拆 = _对象schema(输出Schema)
    s, 号.键表[交结果] = _换键(s)
    出.append({"name": 交结果,
               "description": "任务做完时调用,参数就是最终结果。**只有这一步算交卷**;"
                              "只写一段话不算完成,也不会被执行。",
               "input_schema": s})
    出.append({"name": 问人,
               "description": "缺了没法自己查到的信息、必须问人时调用。参数写清要问什么。",
               "input_schema": {"type": "object", "properties": {"question": {"type": "string", "description": "要问人的问题"}},
                                "required": ["question"]}})
    return 出, 号, 拆


def 消息们(内部消息们, 号):
    """内部消息 → (system, Anthropic messages)。连续同角色的合成一条。"""
    回号 = {名: 代 for 代, 名 in 号.items()}
    系统, 出 = "", []

    def 加(角色, 块们):
        if 出 and 出[-1]["role"] == 角色:
            出[-1]["content"].extend(块们)
        else:
            出.append({"role": 角色, "content": list(块们)})

    for m in 内部消息们 or []:
        r, c = m.get("role"), m.get("content")
        if r == "system":
            系统 = _文(c or "")
        elif r == "user":
            加("user", [{"type": "text", "text": _文(c)}])
        elif r == "assistant":
            if isinstance(c, dict) and c.get("tool_calls"):
                块 = [{"type": "text", "text": c["text"]}] if c.get("text") else []
                块 += [{"type": "tool_use", "id": t.get("id"), "name": 回号.get(t.get("name"), t.get("name")),
                       "input": _换(t.get("arguments") or {}, (getattr(号, "键表", None) or {}).get(
                           回号.get(t.get("name"), t.get("name")), {}))} for t in c["tool_calls"]]
                加("assistant", 块)
            else:
                # 核验没过的候选结论 / 一段文字 —— 重组成文字(不是 tool_use),后面跟普通 user 消息就合法
                加("assistant", [{"type": "text", "text": _文(c if c is not None else "")}])
        elif r == "tool":
            加("user", [{"type": "tool_result", "tool_use_id": x.get("tool_call_id"),
                         "content": _文(x.get("result") if "rejected" not in x else {"被拒": x["rejected"]}),
                         **({"is_error": True} if "rejected" in x else {})} for x in (c or [])])
    return 系统, 出


def 解析(回复, 号, 拆包=False):
    """Anthropic 的回复 → agent_loop 的响应。按**正式的块类型**认,不解析自由文本(附录 A-4)。"""
    块们 = (回复 or {}).get("content") or []
    文 = "".join(b.get("text") or "" for b in 块们 if isinstance(b, dict) and b.get("type") == "text")
    调们, 交, 问 = [], None, None
    for b in 块们:
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        n, 参 = b.get("name"), b.get("input") or {}
        参 = _还(参, (getattr(号, "键表", None) or {}).get(n, {}))
        if n == 交结果:
            交 = (参.get("result") if 拆包 and isinstance(参, dict) else 参)
        elif n == 问人:
            问 = (参 or {}).get("question") or _文(参)
        else:
            # 表里没有的代号原样交出去 —— 网关按没授权拒,不猜
            调们.append({"id": b.get("id"), "name": 号.get(n, n), "arguments": 参})
    if 调们:
        出 = {"tool_calls": 调们}
        if 文:
            出["text"] = 文
    elif 交 is not None:
        出 = {"finish": 交}
    elif 问:
        出 = {"clarification": 问}
    else:
        出 = {"text": 文}
    u = (回复 or {}).get("usage") or {}
    出["usage"] = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                  "cache_read_tokens": u.get("cache_read_input_tokens"),
                  "cache_write_tokens": u.get("cache_creation_input_tokens")}
    return 出
