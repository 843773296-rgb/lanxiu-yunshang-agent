#!/usr/bin/env python3
"""澜绣云裳 · 工艺知识库 MCP 服务

暴露 5 个只读工具,供顾问查汉服工艺、面料、形制、配饰与相容矩阵。
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
