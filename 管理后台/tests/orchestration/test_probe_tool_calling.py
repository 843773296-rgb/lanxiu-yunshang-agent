#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测「支不支持原生工具调用」(2026-11-06;用户拍「改成真发一次请求」)。不要数据库、不发请求。真调 connections_api。

判法:真发一句话 + 一个 ping 工具 + 强制要求调它,看回包里**有没有 tool_use 块**(协议结构,不看文案)。
11-06 拿正式项目的真连接实跑过一次:回包里有调用 ping 的 tool_use 块 → 判「支持」(658 输入 / 16 输出 token)。

  ① 2xx 且有调用 ping 的 tool_use 块(真接口回包的形状)→ 支持
  ② 2xx 但没有 tool_use(强制要求调都不调)→ 不支持;4xx 点名 tools / tool_choice 是不认的参数 → 不支持
  ③ 判不出来(401 / 500 / 没见过的回话)→ None —— **未知不等于支持**(落库存 null,见 ⑤)
  ④ **不看文案**:2xx 回包里文字写「我调用了 ping」但没有 tool_use 块 → 不支持(文字不算结构)
  ⑤ 落库存三值:真调 _真探(只把 curl 换成假回包)—— 第二个请求回 500 → 能力里是 null,不是 False;真生成的用量交给调用方记账
  ⑥ 校验器:探过这一项但没判出来 → MODEL_TOOL_CALLING_UNKNOWN;没探过这一项的老连接 → 照旧 MODEL_NO_TOOL_CALLING
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
    真回包 = {"id": "msg_x", "type": "message", "role": "assistant", "model": "claude-haiku-4-5", "stop_reason": "tool_use",
             "content": [{"type": "tool_use", "id": "toolu_x", "name": "ping", "input": {}}],
             "usage": {"input_tokens": 658, "output_tokens": 16}}
    支, 说 = CA.判工具调用("200", 真回包)
    ck("① 2xx 且有调用 ping 的 tool_use 块 → 支持,理由说明按结构判", 支 is True and "tool_use" in 说, (支, 说))
    ck("② 2xx 没有 tool_use / 4xx 点名 tools 是不认的参数 → 不支持",
       CA.判工具调用("200", {"content": [{"type": "text", "text": "好的"}]})[0] is False
       and CA.判工具调用("400", {"error": {"message": "tools: Extra inputs are not permitted"}})[0] is False
       and CA.判工具调用("400", {"error": {"message": "tool_choice: Extra inputs are not permitted"}})[0] is False)
    ck("③ 判不出来 → None(未知不等于支持):401 / 500 / 没见过的 400",
       CA.判工具调用("401", {"error": {"message": "invalid x-api-key"}})[0] is None
       and CA.判工具调用("500", "")[0] is None
       and CA.判工具调用("400", {"error": {"message": "某个新说法"}})[0] is None)
    ck("④ 不看文案:文字里写「我调用了 ping 工具」、没有 tool_use 块 → 不支持",
       CA.判工具调用("200", {"content": [{"type": "text", "text": "我调用了 ping 工具,tool_use 完成"}]})[0] is False)
    # ⑤
    import subprocess as _sp
    回话们 = []

    class _出:
        def __init__(self, 码, 话):
            self.stdout = __import__("json").dumps({"type": "error", "error": {"type": "invalid_request_error", "message": 话}}) + "\n" + 码

    原run, 原解析 = _sp.run, CA.SR.解析
    try:
        CA.SR.解析 = lambda ref: ({"x-api-key": "假的"}, "env://假")
        剧本 = [_出("400", "messages: at least one message is required"), _出("500", "Overloaded,某个从没见过的新说法")]
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
