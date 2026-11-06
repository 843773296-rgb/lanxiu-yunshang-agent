#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测「支不支持原生工具调用」的判读(2026-11-06)。不要数据库、不发请求。真调 connections_api.判工具调用。

用例是 11-06 拿正式项目的真连接实测回来的**原话**(钉回来,不是我编的说法):
  ① 带合法工具 + 空 messages → 只抱怨 messages → 支持
  ② 端点把 tools 当成不认的参数 → 不支持(照「乱编参数」那句真回话的格式)
  ③ 判不出来的回话(401 / 500 / 说别的)→ None —— **未知不等于支持**(探测落库时记成 False)
  ④ 只要回话里提到 tools 就不判「支持」(工具定义被挑毛病 ≠ 只是消息空)
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
import connections_api as CA  # noqa: E402

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
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 探测原生工具调用的判读:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
