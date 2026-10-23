#!/usr/bin/env python3
"""澜绣云裳 · 按业务领域起的 MCP 服务(用户 2026-10-23 拍「全部拆」,intent/mcp-domains.md)。

    python3 mcp/domain_server.py <领域>      领域见 backend/domains.py:
        knowledge / customer / commerce / fulfillment / finance / service / work / analytics

**八个领域一个入口**:哪个工具归哪个领域只在 `backend/domains.py` 写一次,
这里照它挑;工具实现、写入判定、角色名单收窄(LANXIU_TOOLS)、出门遮挡,全是原来那一套,一行没复制。
原来的 kb_server / task_server / shop_server 三个入口按「数据从哪来」分,
shop 一个装了 79 个工具 —— 看前缀说不出它是哪个岗位、什么风险的动作。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import api, domains
from protocol import Server


def 工具(领域):
    if 领域 not in domains.领域:
        raise SystemExit(f"认不出领域「{领域}」—— 只有 {' / '.join(domains.领域)}")
    要 = set(domains.领域[领域])
    return [(s["name"], s["description"], s["input_schema"], api.TOOLS[s["name"]])
            for s in api.SCHEMAS + api.SHOP_SCHEMAS + api.KB_SCHEMAS if s["name"] in 要]


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else ""
    Server(f"lanxiu-{d}", "1.0.0", 工具(d)).run()
