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
import json, os, sys, traceback

LATEST = "2025-11-25"
SUPPORTED = [LATEST, "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07"]


def 遮被判那条(out):
    """**正在被判的那条差评,它自己的人工处置痕迹一律抹成 None** —— 每个工具的返回出门前都过这一道。

    启动方(`agentsite/sdk.mcp_config`)把被判的包裹号放进这个服务进程的 env `LANXIU_JUDGING_PKG`;
    没设就原样返回(人在后台复核、顾问聊天,照旧全给)。

    为什么放在这一层、而不是让各个工具自己遮:
    · `service_records` 分不出调用方是人还是模型(模型是以某个员工身份跑的)——
      > 一个「人在复核」和一个「模型在被考」,**在工具的入参上长得一模一样**。
      所以「这一轮在判哪条」只能由**启动方**说,而 env 是模型改不了的(它只能按 schema 调工具)。
    · 放在协议这一层,**每个工具都过** —— `bad_ratings` 那张清单里也有「处理过没有」,
      以后新加一个会带出处置字段的工具,不用记得再遮一次。
    遮法、盲区都在 `knowledge/rating.遮住处置痕迹`,这儿不抄(数据工厂 10-13 建议,用户同日拍的产线路)。
    """
    被判 = (os.environ.get("LANXIU_JUDGING_PKG") or "").strip()
    if not 被判:
        return out
    _k = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")
    if _k not in sys.path:
        sys.path.insert(0, _k)
    import rating as _R
    遮完, 遮了 = _R.遮住处置痕迹(out, 被判)
    if 遮了:
        log(f"[遮蔽] 被判 {被判}:遮了 {len(遮了)} 处")    # 只进 stderr,不进给模型的材料
    return 遮完


def log(*a):
    """日志一律走 stderr"""
    print(*a, file=sys.stderr, flush=True)


class Server:
    def __init__(self, name, version, tools):
        """tools: [(name, description, input_schema, fn), ...]"""
        self.name, self.version = name, version
        self.tools = {t[0]: t for t in tools}
        # ── 按角色只挂这个角色的工具(2026-09-22)──────────────────────────
        # 启动方把这个角色能用的工具名放进 LANXIU_TOOLS(逗号分隔)。不在名单里的
        # **既不列出、也调不了** —— 原来三个服务不分角色整包挂上,按角色的名单只进了
        # allowed_tools,而那不是排他白名单:后台运营调了只发给工坊的「算工期」,还据此作答;
        # 财务(名义 5 个工具)每轮带的工具说明反而比后台运营(41 个)还多。
        # 没设这个变量(自测、直连)就照旧全挂 —— 名单为空串时一个都不挂。
        only = os.environ.get("LANXIU_TOOLS")
        if only is not None:
            keep = {x for x in only.split(",") if x}
            self.tools = {k: v for k, v in self.tools.items() if k in keep}

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
                out = 遮被判那条(t[3](**args))
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
