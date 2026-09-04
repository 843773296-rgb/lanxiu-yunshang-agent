#!/usr/bin/env python3
"""澜绣云裳 · 门店业务数据 MCP 服务

订单、现货、售后 —— 顾问和值班同学天天要查的三样。

为什么单独起一个服务而不是塞进 kb 或 task:
  · kb 是**知识**(工艺、版型、BOM、工期),不随一笔生意变
  · task 是**人工任务**,只服务工单研判
  · shop 是**今天发生了什么**,顾问和值班两边都要用
三种数据的更新节奏和责任人都不一样,混在一个服务里,以后想单独收权限就来不及了。

工具实现复用 backend/api.py,不复制一份逻辑。**全部只读。**
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import api
from protocol import Server

TOOLS = [(s["name"], s["description"], s["input_schema"], api.TOOLS[s["name"]])
         for s in api.SHOP_SCHEMAS]

if __name__ == "__main__":
    Server("lanxiu-shop", "1.0.0", TOOLS).run()
