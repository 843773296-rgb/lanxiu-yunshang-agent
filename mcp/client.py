#!/usr/bin/env python3
"""最小 MCP stdio 客户端 —— 纯标准库。

用途:让现有的两个智能体**可以改从 MCP 取工具,而循环代码一个字不改**。
所以它必须做到两件事:
  · 提供和 `api.SCHEMAS` / `api.KB_SCHEMAS` 完全同形的工具定义
  · `call()` 返回 **dict**(不是 MCP 的文本内容),这样循环里那句
    `json.dumps(out, ensure_ascii=False)` 原样可用

进程是**懒启动、长驻、复用**的 —— 每次调用都拉一个子进程会慢到没法评测。

身份(11-24,体检 / fc 查出的两个坑):
  · 原来 Popen 不传 env,子进程的 LANXIU_ME **继承父进程环境** —— 父进程里 `api.as_user(...)` 的 contextvar 身份过不去,
    而父进程环境里若碰巧留着别人的 LANXIU_ME,子进程就顶着那个人的身份取数;
  · 池按 kind 复用:就算起进程时带了身份,**第二个身份也复用第一个的进程 = 串身份**,而串了不会报错。
  现在:起进程时 env 显式带 `api.whoami(认系统=True)` 的身份(没有就把继承来的 LANXIU_ME 删掉,不让它顶别人的),
  池键 = (kind, 身份工号) —— 换一个人就是另一条进程。
"""
import atexit, json, os, subprocess, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
SERVERS = {"kb": "kb_server.py", "task": "task_server.py", "shop": "shop_server.py"}
_POOL = {}
_LOCK = threading.Lock()


def _当前身份():
    """起子进程那一刻的身份:api.whoami(认系统=True)(contextvar 或本进程环境变量)。拿不到 api 就当没身份。"""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))
        import api as _api
        return _api.whoami(认系统=True)
    except Exception:
        return None


class MCPClient:
    def __init__(self, script, me=None):
        env = {k: v for k, v in os.environ.items() if k != "LANXIU_ME"}   # 不继承别人的身份
        if me:
            env["LANXIU_ME"] = json.dumps(me, ensure_ascii=False)
        self.me = me
        self.p = subprocess.Popen(
            [sys.executable, os.path.join(HERE, script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, env=env)
        self.n = 0
        self._rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                 "clientInfo": {"name": "lanxiu-agent", "version": "1.0.0"}})
        self._notify("notifications/initialized", {})
        self.tools = self._rpc("tools/list")["tools"]

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n"); self.p.stdin.flush()

    def _notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _rpc(self, method, params=None):
        self.n += 1
        m = {"jsonrpc": "2.0", "id": self.n, "method": method}
        if params is not None: m["params"] = params
        self._send(m)
        line = self.p.stdout.readline()
        if not line: raise RuntimeError(f"MCP 服务无响应({method})")
        r = json.loads(line)
        if "error" in r: raise RuntimeError(f"MCP 错误 {r['error']}")
        return r.get("result", {})

    def schemas(self):
        """转成和 api.SCHEMAS 同形的结构 —— 循环那边看不出区别"""
        return [{"name": t["name"], "description": t.get("description", ""),
                 "input_schema": t["inputSchema"]} for t in self.tools]

    def call(self, name, **kw):
        """返回 dict,和直连时 api.TOOLS[name](**kw) 的返回同形"""
        r = self._rpc("tools/call", {"name": name, "arguments": kw})
        txt = "".join(c.get("text", "") for c in (r.get("content") or []))
        if r.get("isError"): return {"error": txt}
        try: return json.loads(txt)
        except Exception: return {"text": txt}

    def close(self):
        try: self.p.stdin.close(); self.p.wait(timeout=3)
        except Exception: self.p.kill()


def get(kind):
    """懒启动 + 复用。kind: kb / task / shop。**按 (kind, 身份) 复用** —— 不同的人各自一条进程,串不了身份。"""
    me = _当前身份()
    键 = (kind, (me or {}).get("no") or "")
    with _LOCK:
        if 键 not in _POOL:
            _POOL[键] = MCPClient(SERVERS[kind], me=me)
        return _POOL[键]


def enabled():
    return os.environ.get("USE_MCP") == "1"


@atexit.register
def _cleanup():
    for c in _POOL.values():
        try: c.close()
        except Exception: pass


if __name__ == "__main__":
    for k in SERVERS:
        c = get(k)
        print(f"{k}: {len(c.schemas())} 个工具 → {[t['name'] for t in c.schemas()]}")
    print()
    print("kb_combo(妆花, 香云纱) =", get("kb").call("kb_combo", craft="妆花", material="香云纱"))
    print("get_deposit(D2000)    =", get("task").call("get_deposit", deposit_id="D2000"))
