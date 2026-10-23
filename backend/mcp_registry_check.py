# -*- coding: utf-8 -*-
"""MCP 服务与工具管理:开关真管得住模型那一侧、只有总部运营能改(用户 2026-10-23 拍「做,带配置」)。

**在库副本上真改开关,再真起一个领域服务进程**(mcp/domain_server.py,env LANXIU_DB 指副本)去列、去调 ——
不在这里照着规则另判一遍。开关要是只写进库、协议层不读,「页面上停用了」和「模型真调不动」就是两件事,
而它们在页面上长得一模一样。超时没法让真工具变慢,用协议层的 Server 挂一个会睡的假工具验。

写口打 HTTP 层(server.do_POST,假 handler):身份只从登录会话来。
用法:python3 backend/mcp_registry_check.py   (不调模型;写的是库副本)
"""
import datetime as _dt, io, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE]
# ⚠️ 写口模块**先 import 再切库** —— 用副本只改已经加载的模块
import mcp_registry as R, server, auth, oplog   # noqa: F401
import check_copy
副本 = check_copy.用副本("mcp-reg-")
sys.path.append(os.path.join(ROOT, "mcp"))
import protocol

G, Rd, D = "\033[32m", "\033[31m", "\033[0m"
坏 = 0

咬合 = [
    ("协议层 tools/list 不看开关(停用的照样列出来)", "停用 get_stock:真起的商品服务里列不出"),
    ("协议层 tools/call 不看开关(停用的照样调得动)", "停用 get_stock:真起的商品服务里调不动"),
    ("改开关不查角色(谁都能改)", "顾问改开关:拒"),
    ("限流不数(到了上限照样放)", "限流 1 次/分钟:同一个服务里第二次被拒"),
]


def ck(名, ok, 细=""):
    global 坏
    if not ok: 坏 += 1
    print(f"  {G+'✅'+D if ok else Rd+'❌'+D} {名}{'  ' + 细 if 细 else ''}")


class 假请求:
    def __init__(self, path, body, tok=None):
        self.path = path
        self._b = json.dumps(body, ensure_ascii=False).encode()
        self.headers = {"content-length": str(len(self._b))}
        if tok: self.headers["cookie"] = f"lx_token={tok}"
        self.rfile, self.wfile = io.BytesIO(self._b), io.BytesIO()
    def send_response(self, *a): pass
    def send_header(self, *a): pass
    def end_headers(self): pass
    def log_message(self, *a): pass


def 打(body, tok=None):
    h = 假请求("/api/mcp-tool-save", body, tok); 回 = {}
    def _send(obj, code=200): 回.update(码=code, 体=obj)
    h._send = _send
    server.H.do_POST(h)
    return 回.get("码"), 回.get("体") or {}


def 会话(role):
    r = server.rows("SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' LIMIT 1", role)
    if not r: return None
    tok = f"mcp-reg-{role}"
    with auth._LOCK: auth._SESS[tok] = dict(r[0], at=_dt.datetime.now())
    return tok


def 起服务(领域, 请求们):
    """真起一个领域服务(读副本),发一串 JSON-RPC,收回每个 id 的结果。"""
    env = dict(os.environ, LANXIU_DB=副本)
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "chk", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}] + 请求们
    p = subprocess.run([sys.executable, os.path.join(ROOT, "mcp", "domain_server.py"), 领域],
                       input="\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\n",
                       capture_output=True, text=True, timeout=60, env=env, cwd=ROOT)
    return {r.get("id"): r.get("result") for r in map(json.loads, filter(str.strip, p.stdout.splitlines()))}


def main():
    print("\n\033[1m▸ MCP 服务与工具管理 · 在库副本上改开关,真起服务去列、去调\033[0m")
    if os.path.realpath(R.DB) != os.path.realpath(副本) or os.path.realpath(oplog.DB) != os.path.realpath(副本):
        print(f"  {Rd}❌ 写口没切到副本 —— 不跑,免得写真库{D}"); return 1
    tH, tG = 会话("总部运营"), 会话("顾问")
    if not (tH and tG):
        print(f"  {Rd}❌ 库里找不到在职的总部运营 / 顾问 —— 没东西可验{D}"); return 1

    ck("默认:没登记过的工具全部启用、不限时不限流", R.配置(副本) == {})
    码, 体 = 打({"name": "get_stock", "enabled": False, "why": "x"})
    ck("没登录改开关:拒(401)", 码 == 401, f"回了 {码}")
    码, 体 = 打({"name": "get_stock", "enabled": False, "why": "x"}, tG)
    ck("顾问改开关:拒", not 体.get("ok") and "总部运营" in (体.get("reason") or ""), f"{体}")
    码, 体 = 打({"name": "get_stock", "enabled": False, "why": ""}, tH)
    ck("不写理由:拒", not 体.get("ok") and "理由" in (体.get("reason") or ""), f"{体}")
    码, 体 = 打({"name": "get_stock", "enabled": True, "timeout": 99999, "why": "x"}, tH)
    ck("超时超出范围:拒", not 体.get("ok") and "之间" in (体.get("reason") or ""), f"{体}")

    码, 体 = 打({"name": "get_stock", "enabled": False, "why": "检查里停一下"}, tH)
    ck("总部运营停用 get_stock:存得进、记了改动", 体.get("ok") and R.改动记录("get_stock", 副本), f"{体}")
    回 = 起服务("commerce", [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                             "params": {"name": "get_stock", "arguments": {"material": "棉麻"}}},
                            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "get_order", "arguments": {}}}])
    列 = [t["name"] for t in ((回.get(1) or {}).get("tools") or [])]
    ck("停用 get_stock:真起的商品服务里列不出", 列 and "get_stock" not in 列 and "get_order" in 列, f"列出 {len(列)} 个")
    调 = 回.get(2) or {}
    ck("停用 get_stock:真起的商品服务里调不动", 调.get("isError") and "已在后台停用" in json.dumps(调, ensure_ascii=False),
       json.dumps(调, ensure_ascii=False)[:90])
    ck("别的工具不受影响", (回.get(3) or {}).get("content") is not None)

    打({"name": "kb_combo", "enabled": True, "rate": 1, "why": "检查里限一下"}, tH)
    调 = {"name": "kb_combo", "arguments": {"craft": "妆花", "material": "香云纱"}}
    回 = 起服务("knowledge", [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": 调},
                             {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": 调}])
    ck("限流 1 次/分钟:同一个服务里第二次被拒", not (回.get(1) or {}).get("isError")
       and (回.get(2) or {}).get("isError") and "上限" in json.dumps(回.get(2), ensure_ascii=False))

    # 超时:真工具没法变慢 —— 在协议层挂一个会睡的假工具,把配置塞进它每 5 秒读一次的那份缓存
    sv = protocol.Server("t", "0", [("睡", "", {"type": "object", "properties": {}}, lambda: time.sleep(3) or {"x": 1})])
    protocol._配.update(值={"睡": {"启用": True, "超时": 1, "限流": None}}, 时=time.time())
    t0 = time.time()
    r = sv.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "睡", "arguments": {}}})["result"]
    ck("超时 1 秒:不等那个睡 3 秒的工具,1 秒左右就返回错误", r.get("isError") and time.time() - t0 < 2.5
       and "秒没回" in json.dumps(r, ensure_ascii=False), f"{time.time() - t0:.1f}s")

    with auth._LOCK:
        for t in (tH, tG): auth._SESS.pop(t, None)
    print()
    if 坏:
        print(f"{Rd}❌ MCP 管理 {坏} 处不符合预期{D}"); return 1
    print(f"{G}✅ MCP 管理:开关在真起的服务里生效,只有总部运营能改{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
