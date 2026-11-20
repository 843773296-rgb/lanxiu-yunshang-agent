#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「代码执行」最小版(三期 3-4,11-20 夜)—— 沙箱真攻击 + 校验 / 执行器接线。不起服务、不碰库。

## 四条真攻击(规划 3-4 验收:都必须被沙箱拦下才算做完)
  ① 读环境变量 → 空(没有密钥类的键);② 读密钥文件(~/.deepseek-key)→ 拦;③ 发请求 → 拦;④ 死循环 → 限时杀掉
  再加:写文件 → 拦;起进程 → 拦;吃内存 → 杀;返回类型不对 → 这一步失败;正常算数 → 过
## 接线
  ⑤ 校验器:没写代码 / 没声明结果 / 上限超 5 秒 64 MB / 变量名不合法 → 阻断;配对了 → 没有 CODE_ 阻断;dsl 登记成已实现(菜单里不再置灰)
  ⑥ 执行器:开始 → 代码 → 结束 真跑一遍,结果给下游;代码抛错 → 这一步失败、错误码 CODE_RAISED
⚠️ 沙箱只有 macOS 的 sandbox-exec:没有的机器(CI 的 Linux)真跑那几条**不验、明说**,只验纯逻辑和校验 —— 这不算通过,是没验;
   执行器那条在没沙箱的机器上验「拒跑 CODE_SANDBOX_UNAVAILABLE,不退回裸 exec」。
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
import 代码执行 as C  # noqa: E402
import dsl as DS  # noqa: E402
import validator as V  # noqa: E402
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402

过, 挂, 没验 = [], [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:260] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


有沙箱, 为什么没 = C.沙箱可用()
出 = {"type": "object", "properties": {"和": {"type": "integer"}, "话": {"type": "string"}}, "required": ["和"]}


def 跑(code, 输入=None, schema=出, 秒=2):
    try:
        return "ok", C.跑({"code": code, "output_schema": schema, "sub_limits": {"timeout_seconds": 秒, "memory_mb": 64}}, 输入 or {})
    except C.代码失败 as e:
        return e.code, e.消息


print("▸ 沙箱真攻击" + ("" if 有沙箱 else f"(⏸ 这台机器没沙箱:{为什么没} —— 下面几条**没验,不算通过**)"))
if 有沙箱:
    r = 跑("import os\ndef main():\n    return {'和': len(os.environ), '话': ','.join(sorted(os.environ))}", 秒=3)
    ck("① 环境变量里没有任何密钥 / 令牌类的键(不是「少」,是一个敏感键都没有)", r[0] == "ok" and not any(w in r[1]["话"].lower() for w in ("key", "token", "secret", "anthropic", "deepseek", "home")), 1, r)
    r = 跑("import os\ndef main():\n    return {'和': len(open(os.path.expanduser('~/.deepseek-key')).read())}")
    ck("② 读密钥文件 → CODE_SANDBOX_DENIED", r[0] == "CODE_SANDBOX_DENIED", 1, r)
    r = 跑("import urllib.request\ndef main():\n    urllib.request.urlopen('http://127.0.0.1:8801/api/healthz', timeout=2); return {'和': 1}")
    ck("③ 发请求 → CODE_SANDBOX_DENIED", r[0] == "CODE_SANDBOX_DENIED", 1, r)
    r = 跑("def main():\n    while True: pass", 秒=1)
    ck("④ 死循环 → CODE_TIMEOUT(限时杀掉)", r[0] == "CODE_TIMEOUT", 1, r)
    r = 跑("import time\ndef main():\n    time.sleep(9); return {'和': 1}", 秒=1)
    ck("睡着不算 CPU 也会被墙钟超时杀掉", r[0] == "CODE_TIMEOUT", 1, r)
    r = 跑("def main():\n    open('/tmp/aimc_code_attack_e2e', 'w').write('x'); return {'和': 1}")
    ck("写文件 → CODE_SANDBOX_DENIED,文件没写出去", r[0] == "CODE_SANDBOX_DENIED" and not os.path.exists("/tmp/aimc_code_attack_e2e"), 1, r)
    r = 跑("import subprocess\ndef main():\n    return {'和': subprocess.run(['/usr/bin/id'], capture_output=True).returncode}")
    ck("起进程 → CODE_SANDBOX_DENIED", r[0] == "CODE_SANDBOX_DENIED", 1, r)
    r = 跑("def main():\n    x = bytearray(300 * 1024 * 1024); return {'和': len(x)}", 秒=4)
    ck("吃 300 MB → CODE_MEMORY 杀掉", r[0] == "CODE_MEMORY", 1, r)
    r = 跑("def main(a, b):\n    return {'和': a + b, '话': f'{a}+{b}'}", {"a": 1, "b": 2})
    ck("正常算数 → 结果按声明给出", r == ("ok", {"和": 3, "话": "1+2"}), 1, r)
    r = 跑("def main(a, b):\n    return {'和': 'x'}", {"a": 1, "b": 2})
    ck("返回类型不对 → CODE_OUTPUT_TYPE(不悄悄转)", r[0] == "CODE_OUTPUT_TYPE", 1, r)
    r = 跑("def main(a, b):\n    return {'和': a, '多出来的': 1}", {"a": 1, "b": 2})
    ck("没声明的键丢掉(不往下游塞没声明的东西)", r[0] == "ok" and "多出来的" not in r[1], 1, r)
    r = 跑("def main():\n    raise ValueError('坏了')")
    ck("代码抛错 → CODE_RAISED,消息里有那一行", r[0] == "CODE_RAISED" and "坏了" in r[1], 1, r)
else:
    for 名 in ("① 环境变量", "② 读密钥文件", "③ 发请求", "④ 死循环", "写文件", "起进程", "吃内存", "正常算数", "类型不对", "抛错"):
        print(f"  ⏸ {名}(没验:{为什么没})")
        没验.append(名)

print("▸ 纯逻辑:配置问题 / 核输出")
好 = {"code": "def main():\n    return {}", "output_schema": 出, "sub_limits": {"timeout_seconds": 5, "memory_mb": 64}, "input_mapping": {"a": {"source": "input", "pointer": "/a"}}}
ck("配对了 → 没问题", C.配置问题(好) == [], 1, C.配置问题(好))
ck("没写代码 → CODE_EMPTY", any(x[0] == "CODE_EMPTY" for x in C.配置问题({**好, "code": "  "})), 1)
ck("没声明结果 → CODE_NO_OUTPUT", any(x[0] == "CODE_NO_OUTPUT" for x in C.配置问题({**好, "output_schema": {}})), 1)
ck("限时 9 秒 / 内存 128 → CODE_LIMIT(上限只许往下配)", sum(1 for x in C.配置问题({**好, "sub_limits": {"timeout_seconds": 9, "memory_mb": 128}}) if x[0] == "CODE_LIMIT") == 2, 2)
ck("变量名「1a」→ CODE_INPUT_NAME", any(x[0] == "CODE_INPUT_NAME" for x in C.配置问题({**好, "input_mapping": {"1a": {}}})), 1)
ck("只 Python → CODE_LANGUAGE", any(x[0] == "CODE_LANGUAGE" for x in C.配置问题({**好, "language": "javascript"})), 1)
干净, 问 = C.核输出(出, {"和": 1, "话": None, "x": 2})
ck("核输出:None 当没给、没声明的丢、必填在 → 过", 干净 == {"和": 1} and 问 == [], 1, (干净, 问))
干净, 问 = C.核输出(出, {"话": "x"})
ck("核输出:缺必填 → 点名", 问 and "和" in 问[0], 1, 问)

print("▸ ⑤ 登记与校验器接线")
ck("dsl 登记成已实现(可用节点里有「代码执行」)", any(n["中文"] == "代码执行" for n in DS.可用节点()), len(DS.节点表))
入参 = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}
文 = {"type": "object", "properties": {"text": {"type": "string"}}}


def 图(code配置):
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文, "nodes": [
        {"id": "start", "type": "start", "config": {"start_mode": "用户输入", "input_schema": 入参}},
        {"id": "算", "type": "code", "name": "算一下", "config": code配置},
        {"id": "end", "type": "end", "config": {"output_schema": 文, "bindings": {"text": {"source": "node", "node_id": "算", "pointer": "/话"}}}}],
        "edges": [{"source": "start", "target": "算", "port": "success"}, {"source": "算", "target": "end", "port": "success"}]}


映射 = {"a": {"source": "input", "pointer": "/a"}, "b": {"source": "input", "pointer": "/b"}}
好配 = {"language": "python", "code": "def main(a, b):\n    return {'和': a + b, '话': f'{a}+{b}'}", "input_mapping": 映射, "output_schema": 出, "sub_limits": {"timeout_seconds": 3, "memory_mb": 64}}
校 = lambda g: V.校验(g, 依赖存在=lambda 种类, i: True)  # noqa: E731
码们 = lambda ps, 级=None: [p["code"] for p in ps if 级 is None or p["级别"] == 级]  # noqa: E731
问 = 校(图(好配))
ck("配对了 → 没有 CODE_ / NODE_NOT_IMPLEMENTED 阻断", not any(c.startswith("CODE_") or c == "NODE_NOT_IMPLEMENTED" for c in 码们(问, V.阻断)), 1, 码们(问))
ck("没声明结果 → 阻断 CODE_NO_OUTPUT", "CODE_NO_OUTPUT" in 码们(校(图({**好配, "output_schema": {"type": "object", "properties": {}}})), V.阻断), 1)
ck("限时 9 秒 → 阻断 CODE_LIMIT", "CODE_LIMIT" in 码们(校(图({**好配, "sub_limits": {"timeout_seconds": 9}})), V.阻断), 1)
问 = 校(图({**好配, "code": ""}))
ck("没写代码 → 阻断(必填那条 NODE_MISSING_CONFIG 报,CODE_EMPTY 不重复报)", "NODE_MISSING_CONFIG" in 码们(问, V.阻断) and "CODE_EMPTY" not in 码们(问), 1, 码们(问))

print("▸ ⑥ 执行器接线")
计划 = CP.编译(图(好配), 依赖存在=lambda 种类, i: True)
r = RN.跑一张图(计划, {"a": 2, "b": 5}, 适配器={}, 记事=lambda k, v: None, run_id="code1")
if 有沙箱:
    ck("开始 → 代码 → 结束 跑成,代码算的「2+5」交给下游", r.get("执行状态") == "succeeded" and (r.get("输出") or {}).get("text") == "2+5", 1, (r.get("执行状态"), r.get("输出"), r.get("完成原因")))
    计划2 = CP.编译(图({**好配, "code": "def main(a, b):\n    raise RuntimeError('算不了')"}), 依赖存在=lambda 种类, i: True)
    r2 = RN.跑一张图(计划2, {"a": 2, "b": 5}, 适配器={}, 记事=lambda k, v: None, run_id="code2")
    步 = {s["node_id"]: s for s in r2.get("步骤") or []}
    ck("代码抛错 → 这一步 failed、错误码 CODE_RAISED、整条 failed", r2.get("执行状态") == "failed" and (步.get("算") or {}).get("error_code") == "CODE_RAISED", 1, (r2.get("执行状态"), {k: (v.get("status"), v.get("error_code")) for k, v in 步.items()}))
else:
    步 = {s["node_id"]: s for s in r.get("步骤") or []}
    ck("没沙箱的机器:这一步失败 CODE_SANDBOX_UNAVAILABLE,**不退回裸 exec**", r.get("执行状态") == "failed" and (步.get("算") or {}).get("error_code") == "CODE_SANDBOX_UNAVAILABLE", 1, (r.get("执行状态"), {k: (v.get("status"), v.get("error_code")) for k, v in 步.items()}))

print()
if 挂:
    print(f"❌ {len(挂)} 条没过:{挂}")
    sys.exit(1)
print(f"✅ {len(过)} 条全过" + (f";⏸ {len(没验)} 条没验(这台机器没沙箱,不算通过)" if 没验 else ""))
