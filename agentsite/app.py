#!/usr/bin/env python3
"""澜绣云裳 · 智能体工作站 —— 独立于后台的站点,内核是 Claude Agent SDK。

和后台(8760)的关系:
  · 数据仍归后台。本站**不碰数据库**,`/api/*` 一律反向代理到后台。
    这样既是独立服务,又不会出现两份数据。
  · 后台只留一个入口链接指过来。
  · 智能体不再走后台那个手写循环,改由 Agent SDK 驱动,工具通过 MCP 挂载。
"""
import asyncio, json, os, sys, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.environ.get("LANXIU_BACKEND", "http://127.0.0.1:8760")
PORT = int(os.environ.get("AGENTSITE_PORT", "8770"))
PAGES = {"/": "index.html", "/chat": "chat.html", "/scheme": "scheme.html",
         "/workbench": "workbench.html", "/acceptance": "acceptance.html"}

sys.path.insert(0, HERE)
import sdk


def _u(s):
    """BaseHTTPRequestHandler 按 latin-1 解路径,中文要修回来"""
    try: return s.encode("latin-1").decode("utf-8")
    except Exception: return s


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, ctype="application/json; charset=utf-8", code=200):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def _proxy(self, method="GET", payload=None):
        """/api/* 与 /img/* 反代到后台 —— 本站不直接读库"""
        url = BACKEND + self.path
        req = urllib.request.Request(url, method=method, data=payload,
                                     headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self._send(r.read(), r.headers.get("content-type", "application/json"), r.status)
        except urllib.error.HTTPError as e:
            self._send(e.read(), e.headers.get("content-type", "application/json"), e.code)
        except Exception as e:
            self._send({"error": f"后台({BACKEND})连不上:{e}。先启动 backend/server.py"}, code=502)

    def do_GET(self):
        p = _u(unquote(urlparse(self.path).path))
        if p in PAGES:
            f = os.path.join(HERE, "web", PAGES[p])
            if not os.path.exists(f): return self._send({"error": f"缺页面 {PAGES[p]}"}, code=404)
            self._send(open(f, "rb").read(), "text/html; charset=utf-8"); return
        if p.startswith("/api/") or p.startswith("/img/"): return self._proxy("GET")
        if p == "/health":
            return self._send({"ok": True, "backend": BACKEND, "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")})
        self._send({"error": "no route"}, code=404)

    def do_POST(self):
        p = _u(unquote(urlparse(self.path).path))
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if p == "/run":
            try: body = json.loads(raw or b"{}")
            except Exception: return self._send({"error": "请求体不是 JSON"}, code=400)
            kind = body.get("kind") or "kb"
            prompt = (body.get("prompt") or "").strip()
            if not prompt: return self._send({"error": "问题是空的"}, code=400)
            try:
                r = asyncio.run(sdk.run(kind, prompt))
                return self._send(r)
            except Exception as e:
                return self._send({"error": f"{type(e).__name__}: {e}"[:400]}, code=500)
        if p == "/run-task":
            # 智能体工作台:本站跑智能体(Agent SDK),判分和标注答案交给后台 ——
            # 数据的家在后台,不在这边复制一份判分逻辑。
            try: body = json.loads(raw or b"{}")
            except Exception: return self._send({"error": "请求体不是 JSON"}, code=400)
            tid = body.get("task_id")
            try:
                tasks = json.loads(urllib.request.urlopen(BACKEND + "/api/agent-tasks", timeout=30).read())["rows"]
            except Exception as e:
                return self._send({"error": f"后台连不上:{e}"}, code=502)
            t = next((x for x in tasks if x["id"] == tid), None)
            if not t: return self._send({"error": "任务不存在"}, code=404)
            if t["bp"] == "BP-01":
                case = t["ref"]
                prompt = (f"任务类型:财务人工任务\n押金单号:{t['ref']}\n\n"
                          "这笔押金退款已连续失败并转入人工处理。请查清失败的根本原因,"
                          "给出建议的处理动作,并列出支撑结论的证据。")
            else:
                a, b2 = t["ref"].split("|"); case = t["id"][1:]
                prompt = (f"任务类型:客户合并确认\n两条疑似重复的客户档案:{a} 和 {b2}\n\n"
                          "请判断是否为同一客户,给出合并或不合并的建议,并逐项列出比对依据。")
            try:
                r = asyncio.run(sdk.run("task", prompt))
            except Exception as e:
                return self._send({"error": f"{type(e).__name__}: {e}"[:400]}, code=500)
            r.update(task_id=tid, case=case, bp=t["bp"], prompt=prompt)
            try:
                jr = urllib.request.Request(BACKEND + "/api/judge", method="POST",
                        data=json.dumps({"case": case, "text": r["text"]}).encode(),
                        headers={"content-type": "application/json"})
                r.update(json.loads(urllib.request.urlopen(jr, timeout=30).read()))
            except Exception as e:
                r["judge"] = f"判分失败:{e}"
            return self._send(r)
        if p.startswith("/api/"): return self._proxy("POST", raw)
        self._send({"error": "no route"}, code=404)


if __name__ == "__main__":
    print(f"澜绣云裳 · 智能体工作站  http://127.0.0.1:{PORT}")
    print(f"  后台数据源:{BACKEND}(本站不直接读库,/api/* 反代过去)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
