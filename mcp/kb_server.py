#!/usr/bin/env python3

⚠️ 2026-10-23 起 **V3(agentsite)不再用这个入口**,改走 mcp/domain_server.py(按 8 个业务领域起服务)。
这个入口留给 V1 / V2 的 MCP 通道(agent/v1.py USE_MCP=1、mcp/parity.py)—— 三代对比的条件不动。
"""澜绣云裳 · 工艺知识库 MCP 服务

暴露的工具由 backend/api.py 的 KB_SCHEMAS 决定,这里不再写死数量 ——
工艺 / 面料 / 形制 / 配饰 / 相容矩阵,加上版型库与 BOM(算料算钱)。
工具实现直接复用 backend/api.py —— 不复制一份逻辑。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import api
from protocol import Server

TOOLS = [(s["name"], s["description"], s["input_schema"], api.TOOLS[s["name"]])
         for s in api.KB_SCHEMAS]

if __name__ == "__main__":
    Server("lanxiu-kb", "1.0.0", TOOLS).run()
