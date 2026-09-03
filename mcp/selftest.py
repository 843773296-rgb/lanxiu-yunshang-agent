#!/usr/bin/env python3
"""MCP 连通性自测 —— 不调模型,把 server 当子进程起来走一遍完整握手。

查六件事:
  ① initialize 能协商出协议版本
  ② tools/list 列得出工具,且 inputSchema 根是 type:"object"(MCP 硬要求)
  ③ tools/call 用真实参数能拿到结果
  ④ tools/call 用错参数返回 isError,而不是把服务端搞挂
  ⑤ 未知工具名有明确错误
  ⑥ **stdout 里没有非 JSON 的脏东西** —— 往 stdout 打一行日志,客户端就解析失败,
     而且报错完全看不出是这个原因。这是 MCP 最经典的坑,必须查。
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = [
    ("mcp/kb_server.py",   "lanxiu-kb",   5,
     ("kb_combo", {"craft": "妆花", "material": "香云纱"}, "不可"),
     ("kb_combo", {"craft": 123}, None)),
    ("mcp/task_server.py", "lanxiu-task", 5,
     ("get_deposit", {"deposit_id": "D2000"}, "D2000"),
     ("get_deposit", {}, None)),
]


class Client:
    def __init__(self, script):
        self.p = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "..", script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1)
        self.n = 0
        self.raw = []

    def call(self, method, params=None, notify=False):
        self.n += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None: msg["params"] = params
        if not notify: msg["id"] = self.n
        self.p.stdin.write(json.dumps(msg) + "\n"); self.p.stdin.flush()
        if notify: return None
        line = self.p.stdout.readline()
        self.raw.append(line)
        return json.loads(line)

    def close(self):
        try: self.p.stdin.close(); self.p.wait(timeout=3)
        except Exception: self.p.kill()
        return self.p.stderr.read()


bad = 0
print("MCP 连通性自测\n" + "=" * 74)
for script, want_name, want_n, (gt, ga, expect), (bt, ba, _) in CASES:
    print(f"\n▸ {script}")
    c = Client(script)
    try:
        r = c.call("initialize", {"protocolVersion": "2025-11-25",
                                  "capabilities": {}, "clientInfo": {"name": "selftest", "version": "0"}})
        info = r.get("result", {})
        ok1 = info.get("serverInfo", {}).get("name") == want_name and info.get("protocolVersion")
        print(f"  {'✅' if ok1 else '❌'} ① initialize → {info.get('serverInfo',{}).get('name')} "
              f"/ 协议 {info.get('protocolVersion')}")
        bad += 0 if ok1 else 1

        c.call("notifications/initialized", {}, notify=True)

        r = c.call("tools/list")
        tools = r.get("result", {}).get("tools", [])
        shapes_ok = all(t.get("inputSchema", {}).get("type") == "object" for t in tools)
        ok2 = len(tools) == want_n and shapes_ok
        print(f"  {'✅' if ok2 else '❌'} ② tools/list → {len(tools)} 个(期望 {want_n})"
              f",inputSchema 根均为 object:{shapes_ok}")
        print(f"       {', '.join(t['name'] for t in tools)}")
        bad += 0 if ok2 else 1

        r = c.call("tools/call", {"name": gt, "arguments": ga})
        res = r.get("result", {})
        txt = (res.get("content") or [{}])[0].get("text", "")
        ok3 = not res.get("isError") and (expect in txt)
        print(f"  {'✅' if ok3 else '❌'} ③ tools/call {gt}({ga}) → 含「{expect}」:{expect in txt}")
        bad += 0 if ok3 else 1

        r = c.call("tools/call", {"name": bt, "arguments": ba})
        res = r.get("result", {})
        ok4 = bool(res.get("isError"))
        print(f"  {'✅' if ok4 else '❌'} ④ 错参数 → isError={res.get('isError')} "
              f"「{(res.get('content') or [{}])[0].get('text','')[:40]}」")
        bad += 0 if ok4 else 1

        r = c.call("tools/call", {"name": "no_such_tool", "arguments": {}})
        ok5 = bool(r.get("result", {}).get("isError"))
        print(f"  {'✅' if ok5 else '❌'} ⑤ 未知工具 → isError={ok5}")
        bad += 0 if ok5 else 1

        ok6 = all(l.strip().startswith("{") for l in c.raw if l.strip())
        print(f"  {'✅' if ok6 else '❌'} ⑥ stdout 全是 JSON,没有日志污染")
        bad += 0 if ok6 else 1
    finally:
        err = c.close()
        if err.strip():
            print(f"       (stderr:{err.strip().splitlines()[0][:60]})")

print("\n" + "=" * 74)
if bad:
    print(f"❌ {bad} 项不通过"); sys.exit(1)
print("✅ 两个 MCP 服务全部连通")
