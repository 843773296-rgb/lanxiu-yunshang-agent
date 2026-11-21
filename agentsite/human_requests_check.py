# -*- coding: utf-8 -*-
"""聊天站人工待办 · 以谁的身份 / 四种点不了分开说 / 按钮和版本原样透传(四期 4-1 聊天站一半,11-22)。

**走真入口**:真起聊天站的 `app.H`(只把 `_who` 换成按测试头认人),再起一个假管理后台记下每个进来的请求 ——
所以验到的是「页面打 /api/human-request… → app.py 路由 → human_requests.py → 管理后台」整根线,不是只验纯函数。
假管理后台的四种错误照 管理后台/services/api/app/human_api.py 与 deps.py 的真 code 造(NO_MEMBERSHIP / NOT_FOUND /
CANNOT_DECIDE / REVISION_CONFLICT)。不碰真库、不连 8801。
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, 数 = [], [0]

咬合 = [
    ("决定时把 X-Dev-User 换成服务账号", "决定以**绑定账号**的身份发出(不是服务账号 U001)"),
    ("409 CANNOT_DECIDE 和 REVISION_CONFLICT 说成同一句", "409 CANNOT_DECIDE(已过期)→ 说「已经结束、不能再处理」,不说成别人刚改过"),
    ("决定不带页面给的 revision(改成代理自己重读)", "决定带的是**页面看到的那一版** revision(过期版本照样送去让后台拦)"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {附}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


收到 = []
前 = "/api/v1/projects/project_lanxiu"


def _错(code, msg, adv):
    return {"code": code, "message": msg, "advice": adv, "field_errors": {}, "retryable": False, "trace_id": None}


class 假后台(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _回(self, code, body):
        b = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _记(self, 体=None):
        收到.append({"方法": self.command, "路径": self.path, "身份": self.headers.get("X-Dev-User"),
                   "幂等": self.headers.get("Idempotency-Key"), "体": 体})

    def do_GET(self):
        self._记()
        p, 谁 = self.path, self.headers.get("X-Dev-User")
        if p == 前 + "/staff-bindings":
            return self._回(200, {"items": [{"账号": "UB1", "澜绣工号": "60000002"},
                                           {"账号": "UNOMEM", "澜绣工号": "60000009"}]})
        if 谁 == "UNOMEM":
            return self._回(404, _错("NO_MEMBERSHIP", "这个项目下没有你的成员记录", "请管理员登记"))
        if p.startswith(前 + "/human-requests?"):
            return self._回(200, {"items": [{"id": "HR_OK", "kind": "核对", "status": "pending", "门店": "SH001",
                                            "还能处理吗": True, "expires_at": "2026-11-23T10:00:00"}],
                                 "我的门店": "SH001", "total": 1})
        if p == 前 + "/human-requests/HR_OK":
            return self._回(200, {"请求": {"id": "HR_OK", "kind": "核对", "status": "pending", "revision": 3},
                                 "你能处理吗": True, "门店": "SH001", "允许编辑的字段": ["备注"],
                                 "证据": {"截止时间": "2026-11-23T10:00:00"},
                                 "核对材料": {"转写": "客户说要改袖长", "__表单": {"说明": "核对转写",
                                     "字段": [{"name": "备注", "title": "备注", "type": "text"}],
                                     "按钮": [{"id": "转人工复核", "文字": "转人工复核"}, {"id": "通过", "文字": "通过"}]}}})
        if p == 前 + "/human-requests/HR_EXP":
            return self._回(200, {"请求": {"id": "HR_EXP", "kind": "核对", "status": "expired", "revision": 1},
                                 "你能处理吗": False, "为什么": "已过期", "核对材料": {"__表单": {"说明": "x", "按钮": [{"id": "通过"}]}}})
        return self._回(404, _错("NOT_FOUND", "没有这条待办", "回待办列表重新进入"))

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        体 = json.loads(self.rfile.read(n) or b"{}")
        self._记(体)
        p = self.path
        if p == 前 + "/human-requests/HR_OK/decisions":
            return self._回(201, {"待办id": "HR_OK", "记了吗": True, "decision": 体.get("decision"),
                                 "当前状态": "approved", "新的 revision": 4, "处理人": self.headers.get("X-Dev-User")})
        if p == 前 + "/human-requests/HR_EXP/decisions":
            return self._回(409, _错("CANNOT_DECIDE", "已过期", "已过期 —— 这条请求不能再处理"))
        if p == 前 + "/human-requests/HR_STALE/decisions":
            return self._回(409, _错("REVISION_CONFLICT", "这条请求已经被改过了", "另一个审批者已经处理过了"))
        return self._回(404, _错("NOT_FOUND", "没有这条待办", "回待办列表重新进入"))


def _起(H):
    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


def main():
    print("聊天站人工待办 · 真入口(app.H)+ 假管理后台")
    后台, 后台址 = _起(假后台)
    import human_requests as HR
    HR.基址 = 后台址
    import app
    人们 = {"lin": {"no": "60000002", "name": "林岚", "role": "店长", "shop": "SH001"},
          "nobind": {"no": "60000077", "name": "没绑", "role": "顾问", "shop": "SH001"},
          "nomem": {"no": "60000009", "name": "没成员", "role": "店长", "shop": "SH001"}}
    app._who = lambda h: 人们.get(h.headers.get("X-Test-Who") or "")
    站, 站址 = _起(app.H)

    def 打(方法, 路径, 谁=None, 体=None):
        h = {"X-Test-Who": 谁} if 谁 else {}
        data = None
        if 体 is not None:
            data = json.dumps(体, ensure_ascii=False).encode(); h["content-type"] = "application/json"
        q = urllib.request.Request(站址 + 路径, data=data, method=方法, headers=h)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with op.open(q, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    try:
        码, d = 打("GET", "/api/human-requests")
        ck("没登录 → 401,不去管理后台", 码 == 401 and not any("human-requests" in x["路径"] for x in 收到), (码, d))
        收到.clear()
        码, d = 打("GET", "/api/human-requests", "nobind")
        ck("工号没绑定 → 403 NOT_BOUND、叫他去后台待办处理;**没拿服务账号去取待办**",
           码 == 403 and d.get("code") == "NOT_BOUND" and "后台" in d.get("怎么办", "")
           and not any("human-requests" in x["路径"] for x in 收到), (码, d, 收到))
        收到.clear()
        码, d = 打("GET", "/api/human-requests", "lin")
        取 = [x for x in 收到 if "human-requests" in x["路径"]]
        ck("列表 → 以绑定账号 UB1 去取、带 mine=true", 码 == 200 and 取 and 取[0]["身份"] == "UB1" and "mine=true" in 取[0]["路径"], (码, 取))
        ck("列表 → 每条带 id / 门店,响应带我的门店", d.get("items") and d["items"][0]["id"] == "HR_OK" and d.get("我的门店") == "SH001", d)
        收到.clear()
        码, d = 打("GET", "/api/human-requests?status=expired", "lin")
        ck("已过期那一页 → 带 status=expired、不带 mine", 码 == 200 and any("status=expired" in x["路径"] and "mine" not in x["路径"] for x in 收到), 收到)

        码, d = 打("GET", "/api/human-request?id=HR_OK", "lin")
        ck("详情 → 表单说明 / 字段 / 按钮原样,已填内容不含 __表单,revision 带出",
           码 == 200 and d.get("revision") == 3 and [b["id"] for b in d["表单"]["按钮"]] == ["转人工复核", "通过"]
           and d["表单"]["字段"][0]["name"] == "备注" and "__表单" not in d.get("已填", {}) and d["已填"].get("转写") and d.get("能处理吗") is True, d)
        码, d = 打("GET", "/api/human-request?id=HR_EXP", "lin")
        ck("已过期的详情 → 能处理吗=false(页面只读、不画按钮),说明还在", 码 == 200 and d.get("能处理吗") is False and d.get("表单"), d)

        码, d = 打("GET", "/api/human-request?id=HR_GONE", "lin")
        ck("404 NOT_FOUND → 说「不在你店里或已经没了」", 码 == 404 and d.get("code") == "NOT_FOUND" and "店" in d.get("error", ""), (码, d))
        码, d2 = 打("GET", "/api/human-request?id=HR_OK", "nomem")
        ck("404 NO_MEMBERSHIP → 说「绑定账号没登记进项目」、叫找管理员(和 NOT_FOUND 不是同一句)",
           码 == 404 and d2.get("code") == "NO_MEMBERSHIP" and "管理员" in d2.get("怎么办", "") and d2.get("error") != d.get("error"), (码, d2))

        收到.clear()
        码, d = 打("POST", "/api/human-request/decide", "lin",
                 {"id": "HR_OK", "decision": "转人工复核", "revision": 3, "edits": {"备注": "袖长 +1"}, "key": "K1"})
        发 = [x for x in 收到 if x["方法"] == "POST"]
        ck("决定以**绑定账号**的身份发出(不是服务账号 U001)", 发 and 发[0]["身份"] == "UB1", 发)
        ck("按钮 id 原样透传(decision=转人工复核)、edits 原样", 发 and 发[0]["体"]["decision"] == "转人工复核" and 发[0]["体"]["edits"] == {"备注": "袖长 +1"}, 发)
        ck("幂等键带上:工号 + 单号 + 页面键", 发 and 发[0]["幂等"] == "chat:60000002:HR_OK:K1", 发)
        ck("办成 → ok、当前状态、处理人", 码 == 200 and d.get("ok") and d.get("当前状态") == "approved" and d.get("处理人") == "UB1", (码, d))

        收到.clear()
        码, d = 打("POST", "/api/human-request/decide", "lin", {"id": "HR_STALE", "decision": "通过", "revision": 2, "key": "K2"})
        发 = [x for x in 收到 if x["方法"] == "POST"]
        ck("决定带的是**页面看到的那一版** revision(过期版本照样送去让后台拦)",
           发 and 发[0]["体"]["request_revision"] == 2 and not any(x["方法"] == "GET" and "/human-requests/" in x["路径"] for x in 收到), 收到)
        ck("409 REVISION_CONFLICT → 说「别人刚处理过」、叫刷新", 码 == 409 and d.get("code") == "REVISION_CONFLICT" and "刷新" in d.get("怎么办", ""), (码, d))
        码, d3 = 打("POST", "/api/human-request/decide", "lin", {"id": "HR_EXP", "decision": "通过", "revision": 1, "key": "K3"})
        ck("409 CANNOT_DECIDE(已过期)→ 说「已经结束、不能再处理」,不说成别人刚改过",
           码 == 409 and d3.get("code") == "CANNOT_DECIDE" and "不能再处理" in d3.get("error", "") and d3.get("error") != d.get("error"), (码, d3))

        收到.clear()
        码, d = 打("POST", "/api/human-request/decide", "lin", {"id": "HR_OK", "decision": "通过", "key": "K4"})
        ck("不带 revision → 400、**不发**给管理后台", 码 == 400 and "revision" in d.get("error", "") and not any(x["方法"] == "POST" for x in 收到), (码, d))
        码, d = 打("POST", "/api/human-request/decide", "nobind", {"id": "HR_OK", "decision": "通过", "revision": 3, "key": "K5"})
        ck("没绑定的人点决定 → 403 NOT_BOUND,不发", 码 == 403 and d.get("code") == "NOT_BOUND" and not any(x["方法"] == "POST" for x in 收到), (码, d))
    finally:
        站.shutdown(); 后台.shutdown()
    # 页面:按钮 / 只读两态都由「能处理吗」决定,决定带 revision 和 key
    src = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
    段 = src[src.index("async function 开一张待办"):src.index("/* 店长复核样本")]
    ck("页面:能处理吗=false 不画按钮、提交带 revision + key", "d.能处理吗 ?" in 段 and "revision: d.revision" in 段 and "key: 键" in 段)
    print()
    if 坏:
        print(f"{R}❌ 聊天站人工待办 {len(坏)} 条不过(验了 {数[0]} 条){D}")
        return 1
    print(f"{G}✅ 聊天站人工待办:以绑定账号办、四种点不了分开说、按钮 / 版本 / 幂等键原样透传(验了 {数[0]} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
