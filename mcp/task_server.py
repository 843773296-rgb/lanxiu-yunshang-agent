#!/usr/bin/env python3
"""澜绣云裳 · 人工任务 MCP 服务

暴露 5 个只读工具,供查押金退款失败的原因与客户档案。
**全部只读,没有任何写接口** —— 产出是给人看的判断依据,不是代替人操作。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import api
from protocol import Server

TOOLS = [(s["name"], s["description"], s["input_schema"], api.TOOLS[s["name"]])
         for s in api.SCHEMAS]

if __name__ == "__main__":
    Server("lanxiu-task", "1.0.0", TOOLS).run()
