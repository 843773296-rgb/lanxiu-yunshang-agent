#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节点级超时 / 重试真生效(11-15,工作流一期第一件;执行手册 W30)。

## 为什么要这份
三个字段(`timeout_seconds` / `retryable_errors` / `max_retries`)DSL 收、校验器查、面板能填,
**执行器一处不读**(11-12 体检查实)—— 一个「配了重试三次,可它没重试」的流程,在面板上和一个
真会重试的长得一模一样。这份自测只打执行器:适配器是假的,数它被调了几次。

## 判据
  ① 没配三件套 → 调一次,成功,attempt=1(老流程行为不变)
  ② 白名单里的失败 → 重试到成功:调了 3 次、运行成功、那一步 attempt=3、两条 node.retry 事件
  ③ 失败码不在白名单 → **不重试**:调 1 次、运行失败、code 原样
  ④ 重试用完还失败 → 调 max_retries+1 次、运行失败、attempt 记真实次数
  ⑤ 超时:适配器睡过头 → TIMEOUT;把 TIMEOUT 放进白名单且第二次不睡 → 第二次成
  ⑥ 适配器抛别种异常 → ADAPTER_ERROR,不在白名单就不重试
  ⑦ 模型调用计数按真实次数算(重试过的每一次都花了钱)
"""
import os
import sys
import time

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:220] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


文 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}


def 图(**三件):
    cfg = {"connection_version_id": "cv1", "prompt_version_id": "p1", "output_schema": 文,
           "bindings": {"问": {"source": "input", "pointer": "/问"}}, **三件}
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文,
            "nodes": [{"id": "start", "type": "start", "config": {"input_schema": {
                          "type": "object", "properties": {"问": {"type": "string"}}, "required": ["问"]}}},
                      {"id": "llm", "type": "llm", "config": cfg},
                      {"id": "end", "type": "end", "config": {"output_schema": 文, "bindings": {
                          "text": {"source": "node", "node_id": "llm", "pointer": "/text"}}}}],
            "edges": [{"source": "start", "target": "llm", "port": "success"},
                      {"source": "llm", "target": "end", "port": "success"}]}


def 跑(g, 剧本):
    """剧本:每次调用做什么 —— ("ok", 文本) / ("fail", code) / ("sleep", 秒) / ("boom", 异常类)。多出来的调用一律 ok。"""
    计 = {"n": 0}
    事件 = []

    def 模型(cfg, 实参):
        i = 计["n"]
        计["n"] += 1
        动, 值 = 剧本[i] if i < len(剧本) else ("ok", "成")
        if 动 == "fail":
            raise RN.节点失败(值, f"假失败 {值}", "无")
        if 动 == "sleep":
            time.sleep(值)
            return {"text": "睡醒了", "execution_mode": "mock"}
        if 动 == "boom":
            raise 值("假异常")
        return {"text": 值, "execution_mode": "mock"}
    r = RN.跑一张图(CP.编译(g, 依赖存在=lambda 种类, i: True), {"问": "你好"}, 适配器={"llm": 模型},
                  记事=lambda 名, 载: 事件.append((名, 载)), run_id="r")
    步 = [s for s in r["步骤"] if s["node_id"] == "llm"]
    return r, 计["n"], (步[-1] if 步 else {}), 事件


print("▸ ① 没配三件套:老行为不变")
r, n, 步, 事 = 跑(图(), [("ok", "成")])
ck("调一次就成,attempt=1", r["执行状态"] == "succeeded" and n == 1 and 步.get("attempt") == 1, 1, (r["执行状态"], n, 步.get("attempt")))
ck("执行键里的 attempt 段也是 1", str(步.get("execution_key", "")).endswith(":1"), 1, 步.get("execution_key"))

print("▸ ② 白名单里的失败 → 重试到成功")
r, n, 步, 事 = 跑(图(max_retries=3, retryable_errors=["RATE_LIMIT"]), [("fail", "RATE_LIMIT"), ("fail", "RATE_LIMIT"), ("ok", "第三次")])
ck("调了 3 次、运行成功", r["执行状态"] == "succeeded" and n == 3, 1, (r["执行状态"], n))
ck("那一步 attempt=3,执行键尾段 :3", 步.get("attempt") == 3 and str(步.get("execution_key", "")).endswith(":3"), 1, 步)
重试事件 = [载 for 名, 载 in 事 if 名 == "node.retry"]
ck("两条 node.retry 事件,各带 attempt / code", len(重试事件) == 2 and [x["attempt"] for x in 重试事件] == [1, 2]
   and all(x["code"] == "RATE_LIMIT" for x in 重试事件), len(重试事件), 重试事件)
ck("⑦ 模型调用计数按真实次数算(3)", r["用量"]["模型调用"] == 3, 1, r["用量"])

print("▸ ③ 失败码不在白名单 → 不重试")
r, n, 步, 事 = 跑(图(max_retries=3, retryable_errors=["RATE_LIMIT"]), [("fail", "BAD_JSON"), ("ok", "本不该到这")])
ck("只调 1 次、运行失败、code 原样", r["执行状态"] == "failed" and n == 1 and 步.get("error_code") == "BAD_JSON", 1, (r["执行状态"], n, 步.get("error_code")))
ck("没有 node.retry 事件", not [1 for 名, _ in 事 if 名 == "node.retry"], 1)

print("▸ ④ 重试用完还失败")
r, n, 步, 事 = 跑(图(max_retries=2, retryable_errors=["RATE_LIMIT"]), [("fail", "RATE_LIMIT")] * 5)
ck("调 max_retries+1=3 次、失败、attempt=3", r["执行状态"] == "failed" and n == 3 and 步.get("attempt") == 3 and 步.get("error_code") == "RATE_LIMIT",
   1, (r["执行状态"], n, 步.get("attempt"), 步.get("error_code")))
ck("max_retries=0 等于不重试", 跑(图(max_retries=0, retryable_errors=["RATE_LIMIT"]), [("fail", "RATE_LIMIT")] * 3)[1] == 1, 1)

print("▸ ⑤ 超时")
t0 = time.time()
r, n, 步, 事 = 跑(图(timeout_seconds=0.3), [("sleep", 1.5)])
用时 = time.time() - t0
ck("睡过头 → TIMEOUT,运行失败,而且没等它睡完", r["执行状态"] == "failed" and 步.get("error_code") == "TIMEOUT" and 用时 < 1.2, 1,
   (r["执行状态"], 步.get("error_code"), round(用时, 2)))
r, n, 步, 事 = 跑(图(timeout_seconds=0.3, max_retries=1, retryable_errors=["TIMEOUT"]), [("sleep", 1.5), ("ok", "第二次")])
ck("TIMEOUT 在白名单里 → 第二次成,attempt=2", r["执行状态"] == "succeeded" and n == 2 and 步.get("attempt") == 2, 1, (r["执行状态"], n, 步.get("attempt")))
r, n, 步, 事 = 跑(图(timeout_seconds=5), [("ok", "快")])
ck("没超时的照常成(超时值只是上限)", r["执行状态"] == "succeeded" and n == 1, 1)
r, n, 步, 事 = 跑(图(timeout_seconds="不是数"), [("ok", "快")])
ck("超时值不是数 → 当没配,不崩", r["执行状态"] == "succeeded" and n == 1, 1, r["执行状态"])

print("▸ ⑥ 适配器抛别种异常")
r, n, 步, 事 = 跑(图(max_retries=2, retryable_errors=["RATE_LIMIT"]), [("boom", ConnectionError)])
ck("算 ADAPTER_ERROR,不在白名单就不重试", r["执行状态"] == "failed" and n == 1 and 步.get("error_code") == "ADAPTER_ERROR", 1, (n, 步.get("error_code")))
r, n, 步, 事 = 跑(图(max_retries=2, retryable_errors=["ADAPTER_ERROR"]), [("boom", ConnectionError), ("ok", "好了")])
ck("ADAPTER_ERROR 写进白名单就会重试", r["执行状态"] == "succeeded" and n == 2, 1, (r["执行状态"], n))

print()
if 挂:
    print(f"\033[31m❌ 节点级超时 / 重试 {len(挂)} 条不过:{'；'.join(挂)}\033[0m")
    sys.exit(1)
print(f"\033[32m✅ 节点级超时 / 重试 {len(过)} 条全过\033[0m —— 三个字段从「面板能填、执行器不读」变成真生效;"
      f"超时是等不到就算失败(不是掐断那次调用),写在 runner._限时 的说明里")
