#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测「支不支持原生工具调用」的判读(2026-11-06)。不要数据库、不发请求。真调 connections_api.判工具调用。

用例是 11-06 拿正式项目的真连接实测回来的**原话**(钉回来,不是我编的说法):
  ① 带合法工具 + 空 messages → 只抱怨 messages → 支持
  ② 端点把 tools 当成不认的参数 → 不支持(照「乱编参数」那句真回话的格式)
  ③ 判不出来的回话(401 / 500 / 说别的)→ None —— **未知不等于支持**(落库存 null,见 ⑤)
  ④ 只要回话里提到 tools 就不判「支持」(工具定义被挑毛病 ≠ 只是消息空)
  ⑤ **落库存三值**:真调 _真探(只把 curl 换成假回话)—— 第二个请求回一句没见过的话 → 能力里是 null,不是 False
     (11-06 并行会话指出:原来写 `支持 is True`,「没判出来」被压成 False,文案一改就静默降级)
  ⑥ 校验器:探过这一项但没判出来 → MODEL_TOOL_CALLING_UNKNOWN(下一步是看原话 / 重探);没探过这一项的老连接 → 照旧 MODEL_NO_TOOL_CALLING
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
import connections_api as CA  # noqa: E402
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))
import validator as V  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def main():
    支, 说 = CA.判工具调用("400", "messages: at least one message is required")
    ck("① 带合法工具只被拒在空 messages 上(真回话原文)→ 支持,理由里带原话", 支 is True and "messages" in 说, (支, 说))
    支, 说 = CA.判工具调用("400", "tools: Extra inputs are not permitted")
    ck("② 端点把 tools 当成不认的参数(照真回话「tools_bogus: Extra inputs are not permitted」的格式)→ 不支持",
       支 is False, (支, 说))
    ck("③ 判不出来 → None(未知不等于支持):401 / 500 / 说别的",
       CA.判工具调用("401", "invalid x-api-key")[0] is None and CA.判工具调用("500", "")[0] is None
       and CA.判工具调用("400", "max_tokens: must be greater than 0")[0] is None)
    ck("④ 回话里挑了工具定义的毛病(tools.0.custom.name …,真回话原文)→ 不判「支持」",
       CA.判工具调用("400", "tools.0.custom.name: String should match pattern '^[a-zA-Z0-9_-]{1,128}$'")[0] is not True)
    # ⑤
    import subprocess as _sp
    回话们 = []

    class _出:
        def __init__(self, 码, 话):
            self.stdout = __import__("json").dumps({"type": "error", "error": {"type": "invalid_request_error", "message": 话}}) + "\n" + 码

    原run, 原解析 = _sp.run, CA.SR.解析
    try:
        CA.SR.解析 = lambda ref: ({"x-api-key": "假的"}, "env://假")
        剧本 = [_出("400", "messages: at least one message is required"), _出("400", "某个从没见过的新说法")]
        _sp.run = lambda *a, **k: (回话们.append(k.get("input")), 剧本.pop(0))[1]
        实 = CA._真探("http://127.0.0.1:9/假端点", "env://假")
    finally:
        _sp.run, CA.SR.解析 = 原run, 原解析
    ck("⑤ 落库存三值:第二个请求回一句没见过的话 → 能力里是 null(不是 False),原话留在「怎么判的」里",
       "原生工具调用" in 实 and 实["原生工具调用"] is None and "从没见过" in 实["原生工具调用怎么判的"] and len(回话们) == 2,
       (实.get("原生工具调用"), 实.get("原生工具调用怎么判的"), len(回话们)))

    # ⑥
    def 码们(能力):
        return {p["code"] for p in V.校验Agent({"tools": ["t"], "connection_version_id": "cv1"}, 连接能力=lambda cv: 能力)}
    ck("⑥ 探过但没判出来 → MODEL_TOOL_CALLING_UNKNOWN,而且不同时报「不支持」",
       "MODEL_TOOL_CALLING_UNKNOWN" in 码们({"原生工具调用": None, "原生工具调用怎么判的": "x"})
       and "MODEL_NO_TOOL_CALLING" not in 码们({"原生工具调用": None}), 码们({"原生工具调用": None}))
    ck("⑥ 没探过这一项的老连接 / 判出来不支持 → 照旧 MODEL_NO_TOOL_CALLING;支持 → 两个都不报",
       "MODEL_NO_TOOL_CALLING" in 码们({}) and "MODEL_NO_TOOL_CALLING" in 码们({"原生工具调用": False})
       and not ({"MODEL_NO_TOOL_CALLING", "MODEL_TOOL_CALLING_UNKNOWN"} & 码们({"原生工具调用": True})), (码们({}), 码们({"原生工具调用": True})))

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 探测原生工具调用的判读:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
