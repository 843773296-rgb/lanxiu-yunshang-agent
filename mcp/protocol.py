#!/usr/bin/env python3
"""最小 MCP stdio 服务端 —— 纯标准库,不引任何依赖。

协议是 JSON-RPC 2.0 走 stdin/stdout,方法就这几个:
  initialize / notifications/initialized / ping / tools/list / tools/call

协议版本与字段结构是从本机已装的官方 SDK
(@modelcontextprotocol/sdk/dist/esm/types.js)里核实的,不是凭印象写的:
  LATEST_PROTOCOL_VERSION = '2025-11-25'
  SUPPORTED = ['2025-11-25','2025-06-18','2025-03-26','2024-11-05','2024-10-07']
  tools/list  → {"tools":[{name, description, inputSchema}]}   inputSchema 根必须是 type:"object"
  tools/call  → {"content":[{"type":"text","text":...}], "isError":bool}

⚠️ **stdout 只能有 JSON-RPC。** 任何 print / 日志都必须走 stderr ——
   往 stdout 打一行调试信息,客户端就会解析失败,而且报错信息完全看不出是这个原因。
"""
import json, sys, traceback

LATEST = "2025-11-25"
SUPPORTED = [LATEST, "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07"]


def log(*a):
    """日志一律走 stderr"""
    print(*a, file=sys.stderr, flush=True)


class Server:
    def __init__(self, name, version, tools):
        """tools: [(name, description, input_schema, fn), ...]"""
        self.name, self.version = name, version
        self.tools = {t[0]: t for t in tools}

    # ── JSON-RPC ────────────────────────────────────────────────
    def _ok(self, rid, result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def _err(self, rid, code, msg):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}

    def handle(self, req):
        m, rid, p = req.get("method"), req.get("id"), req.get("params") or {}

        if m == "initialize":
            want = p.get("protocolVersion")
            return self._ok(rid, {
                "protocolVersion": want if want in SUPPORTED else LATEST,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": self.version},
            })
        if m in ("notifications/initialized", "initialized"):
            return None                                   # 通知,不回
        if m == "ping":
            return self._ok(rid, {})
        if m == "tools/list":
            return self._ok(rid, {"tools": [
                {"name": n, "description": d, "inputSchema": s}
                for n, d, s, _ in self.tools.values()]})
        if m == "tools/call":
            nm = p.get("name"); args = p.get("arguments") or {}
            t = self.tools.get(nm)
            if not t:
                return self._ok(rid, {"content": [{"type": "text",
                    "text": f"没有名为 {nm} 的工具。可用:{list(self.tools)}"}], "isError": True})
            try:
                out = t[3](**args)
                return self._ok(rid, {"content": [{"type": "text",
                    "text": json.dumps(out, ensure_ascii=False, indent=1)}], "isError": False})
            except TypeError as e:
                return self._ok(rid, {"content": [{"type": "text",
                    "text": f"参数不对:{e}"}], "isError": True})
            except Exception as e:
                log("工具执行失败", nm, traceback.format_exc())
                return self._ok(rid, {"content": [{"type": "text",
                    "text": f"{type(e).__name__}: {e}"}], "isError": True})
        if rid is None:
            return None                                   # 未知通知,忽略
        return self._err(rid, -32601, f"未实现的方法 {m}")

    def run(self):
        log(f"[{self.name}] 就绪,{len(self.tools)} 个工具")
        for line in sys.stdin:
            line = line.strip()
            if not line: continue
            try:
                req = json.loads(line)
            except Exception:
                log("收到非 JSON:", line[:120]); continue
            for r in ([req] if isinstance(req, dict) else req):
                resp = self.handle(r)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
