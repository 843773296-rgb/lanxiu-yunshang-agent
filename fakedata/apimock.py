#!/usr/bin/env python3
"""自测用的接口靶子 —— 壳是假的,**校验和响应约定都照着项目真实那一份**。

⚠️ 一开始这个靶子的响应是我自己拍的(`{"error": ...}` / `{"id": ...}`),
而 `backend/server.py` 里真实的写接口返回的是 `{ok, code, id, reason}`。
**靶子是我造的、规格也是我写的,两者一致证明不了规格对** —— 那是个自我确认的闭环。
真实现补上之后照着改的,顺带发现驱动会把每一次业务拒绝记成成功。

`backend/rules.py` 里的 `validate_customer` / `validate_appointment` 是纯函数,
这里只读地 import 进来用。所以自测验的不是我编的规则,是产品真实在用的规则。

为什么不去打真正跑着的那个服务(:8760):
它写的是 `backend/lanxiu.db` —— 四个数据检查的真值源,不能碰(闸门也拦着)。
而且 check.sh 不该依赖一个得先手动起起来的服务。
"""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "backend"))
import rules as _rules       # 只读引用:产品真正的写入校验


class Store:
    def __init__(self): self.customer, self.appointment, self.n = [], [], 0
    def nid(self, p): self.n += 1; return f"{p}{self.n:05d}"


def _make_handler(store):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, doc, code=200):
            b = json.dumps(doc, ensure_ascii=False).encode()
            self.send_response(code); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            try: body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send({"ok": False, "code": "BAD_JSON", "reason": "请求体不是 JSON"}, 400)
            p = self.path

            if p == "/api/customer-create":
                ok, code, reason, _s = _rules.validate_customer(body, store.customer)
                if not ok: return self._send({"ok": False, "code": code, "reason": reason})
                rid = store.nid("SVR-C")
                store.customer.append(dict(body, id=rid))
                return self._send({"ok": True, "code": "CREATE", "id": rid,
                                   "reason": f"已建档 {rid}"})

            if p == "/api/customer-delete":
                store.customer = [c for c in store.customer if c["id"] != body.get("id")]
                return self._send({"ok": True, "code": "DELETE"})

            if p == "/api/appt-create":
                if not any(c["id"] == body.get("customer_id") for c in store.customer):
                    return self._send({"ok": False, "code": "NO_CUSTOMER",
                                       "reason": f'客户 {body.get("customer_id")} 不存在'})
                d = {"way": body.get("way") or "到店量体",
                     "start": body.get("start"), "end": body.get("end")}
                ok, code, reason = _rules.validate_appointment(d)
                if not ok: return self._send({"ok": False, "code": code, "reason": reason})
                rid = store.nid("SVR-AP")
                store.appointment.append(dict(body, id=rid))
                return self._send({"ok": True, "code": "CREATE", "id": rid,
                                   "reason": f"已建预约 {rid}"})

            if p == "/api/appt-delete":
                store.appointment = [a for a in store.appointment if a["id"] != body.get("id")]
                return self._send({"ok": True, "code": "DELETE"})

            return self._send({"ok": False, "code": "NO_ROUTE",
                               "reason": f"没有这个路由: {p}"}, 404)
    return H


def serve(port=0):
    """起在后台线程上。返回 (base_url, store, 关掉它的函数)。port=0 让系统挑空端口。"""
    store = Store()
    srv = HTTPServer(("127.0.0.1", port), _make_handler(store))
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    return f"http://127.0.0.1:{srv.server_address[1]}", store, srv.shutdown


SPEC = {
    "base": "",     # 由调用方填真实端口
    "endpoints": {
        "customer": {
            "create": {"method": "POST", "path": "/api/customer-create",
                       "fields": {"name": "name", "phone": "phone", "shop": "shop"},
                       "id_path": "id", "ok_field": "ok"},
            "delete": {"method": "POST", "path": "/api/customer-delete", "id_field": "id"},
        },
        "appointment": {
            "create": {"method": "POST", "path": "/api/appt-create",
                       # customer_id 是外键:驱动会把方案里的假 id 翻译成服务端真实 id
                       "fields": {"customer_id": "customer_id", "shop": "shop",
                                  "start": "start_ts", "end": "end_ts"},
                       "id_path": "id", "ok_field": "ok"},
            "delete": {"method": "POST", "path": "/api/appt-delete", "id_field": "id"},
        },
    },
}
