#!/usr/bin/env python3
"""澜绣云裳 · 智能运维平台 —— 独立于后台的站点,内核是 Claude Agent SDK。

和后台(8760)的关系:
  · 数据仍归后台。本站**不碰数据库**,`/api/*` 一律反向代理到后台。
    这样既是独立服务,又不会出现两份数据。
  · 后台只留一个入口链接指过来。
  · 智能体不再走后台那个手写循环,改由 Agent SDK 驱动,工具通过 MCP 挂载。
"""
import asyncio, json, os, re, shutil, sys, threading, urllib.request, urllib.error

# 见 /run 里的注释:切供应商是改进程环境变量,多线程会串味,所以跑模型这段串行
RUNLOCK = threading.Lock()

# 上传的图:**四张封顶、每张 6MB 封顶、只收视觉模型认的四种格式**。
# 不设上限的话,一次粘几十张就能把内存和账单一起打穿 ——
# 而这条路径是浏览器直连的,不是内部脚本。
MAX_IMGS, MAX_BYTES = 4, 6 * 1024 * 1024
_MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg",
             "image/gif": ".gif", "image/webp": ".webp"}


def _save_images(items):
    """data URL 列表 → 临时文件路径列表。返回 (paths, tmpdir)。"""
    import base64, binascii, tempfile
    if len(items) > MAX_IMGS:
        raise ValueError(f"一次最多 {MAX_IMGS} 张图,收到 {len(items)} 张")
    d = tempfile.mkdtemp(prefix="lanxiu-img-")
    out = []
    for i, s0 in enumerate(items):
        m = re.match(r"^data:([\w/+-]+);base64,(.+)$", s0 or "", re.S)
        if not m: raise ValueError(f"第 {i+1} 张不是 data URL")
        mt = m.group(1)
        if mt not in _MIME_EXT:
            raise ValueError(f"第 {i+1} 张是 {mt} —— 只收 png / jpeg / gif / webp")
        try: blob = base64.b64decode(m.group(2), validate=True)
        except (binascii.Error, ValueError): raise ValueError(f"第 {i+1} 张解不开")
        if len(blob) > MAX_BYTES:
            raise ValueError(f"第 {i+1} 张 {len(blob)//1024//1024}MB,超过 {MAX_BYTES//1024//1024}MB")
        fp = os.path.join(d, f"{i}{_MIME_EXT[mt]}")
        with open(fp, "wb") as fh: fh.write(blob)
        out.append(fp)
    return out, d
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote, quote

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.environ.get("LANXIU_BACKEND", "http://127.0.0.1:8760")
PORT = int(os.environ.get("AGENTSITE_PORT", "8770"))
# 首页是值班台,不是导航页 —— 打开就该看见「今天还剩多少件」。
# 新工作站(单壳多屏 + 右侧智能体 + 「?」教学层)。
# 旧的分页仍在原路径上,没删 —— 它们还是 ui_audit 的扫描对象,也方便对照。
# 首页是**一个通用对话助手**,不是导航页也不是多屏工作台。
# 之前那版单壳多屏(值班台/研判队列/面料学堂/着装人/健康 + 「?」教学层)
# 整体挪到 /panels 保住了 —— 里面的教学内容是攒出来的,不能因为换个形态就丢。
PAGES = {"/": "station.html", "/panels": "panels.html",
         "/duty": "duty.html", "/queue": "queue.html", "/health": "health.html",
         "/chat": "chat.html", "/scheme": "scheme.html",
         "/workbench": "workbench.html", "/acceptance": "acceptance.html",
         # 着装人的身体生命周期 —— 和会员生命周期(新客/沉默/流失)不是一回事
         "/wearers": "wearers.html"}

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
            html = open(f, encoding="utf-8").read()
            # 配色、导航、表格样式只有一份(web/_shell.txt),页面里写 <!--SHELL--> 占位。
            # 抄五份的结果一定是改了四份漏一份 —— 和知识库不许存两遍是同一条理由。
            if "<!--SHELL-->" in html:
                html = html.replace("<!--SHELL-->", open(
                    os.path.join(HERE, "web", "_shell.txt"), encoding="utf-8").read())
            self._send(html.encode(), "text/html; charset=utf-8"); return
        if p.startswith("/api/") or p.startswith("/img/"): return self._proxy("GET")
        if p == "/models":
            # 清单由 sdk 从**单价表**长出来,页面不许自己写死一份
            return self._send({"rows": sdk.models(), "default": sdk.default_model_id()})
        if p == "/healthz":
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
            # model:"供应商:模型名",来自 /models。不给就走环境变量里的默认。
            prov = mdl = None
            mid = (body.get("model") or "").strip()
            if mid:
                if mid not in {m["id"] for m in sdk.models()}:
                    return self._send({"error": f"没有这个模型:{mid}"}, code=400)
                prov, mdl = mid.split(":", 1)
            # images:data URL 列表。sdk.run 收的是**本地文件路径**,
            # 所以这里落成临时文件,跑完删掉 —— 图不留在服务器上。
            imgs, tmpdir, ierr = [], None, None
            raw_imgs = body.get("images") or []
            if raw_imgs:
                pv = prov or ("claude" if os.environ.get("LANXIU_PROVIDER","").lower()=="claude"
                              else "deepseek")
                mv = mdl or (sdk.default_model_id().split(":",1)[1])
                if not sdk.sees_images(pv, mv):
                    return self._send({"error": f"{mv} 看不了图 —— "
                                       "换成 Claude 任一款,或 deepseek-v4-flash-vision-exp"}, code=400)
                try: imgs, tmpdir = _save_images(raw_imgs)
                except ValueError as e: ierr = str(e)
                if ierr: return self._send({"error": ierr}, code=400)
            # session:上一轮返回的会话号。前端每条会话存一个,续着问就带上。
            try:
                # **必须串行。** sdk._env 是改进程环境变量(ANTHROPIC_BASE_URL / API_KEY)
                # 来切供应商的,而这是个多线程服务 —— 两个请求同时进来,
                # 后一个会把前一个的凭证改掉,前一个就带着 DeepSeek 的 base_url 去打 Claude。
                # 本机单人用,串行的代价可以接受;串味的代价不能接受。
                with RUNLOCK:
                    r = asyncio.run(sdk.run(kind, prompt, resume=body.get("session") or None,
                                            provider=prov, model_name=mdl, images=imgs or None))
                return self._send(r)
            except Exception as e:
                return self._send({"error": f"{type(e).__name__}: {e}"[:400]}, code=500)
            finally:
                if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True)
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
        if p in ("/run-triage", "/run-batch"):
            # 平台的主循环:从积压队列里取任务 → 跑智能体 → **结果落后台的库**。
            # 和 /run-task(展示件)的区别只有一句话:那个跑完显示就没了,这个跑完留在队列里等人销账。
            try: body = json.loads(raw or b"{}")
            except Exception: return self._send({"error": "请求体不是 JSON"}, code=400)
            ids = body.get("task_ids") or ([body["task_id"]] if body.get("task_id") else [])
            if not ids:
                # 不传就从队列里自动取:超时的排在前面,取几条由 n 决定(默认 3,别一口气烧钱)
                try:
                    q = json.loads(urllib.request.urlopen(
                        BACKEND + "/api/ops-queue?state=" + quote("未研判"), timeout=30).read())["rows"]
                except Exception as e:
                    return self._send({"error": f"后台连不上:{e}"}, code=502)
                ids = [x["task_id"] for x in q[: int(body.get("n") or 3)]]
            if not ids: return self._send({"ok": True, "done": [], "note": "队列里没有未研判的工单"})
            out, errs = [], []
            for tid in ids:
                try: out.append(self._triage_one(tid))
                except Exception as e: errs.append({"task_id": tid, "error": f"{type(e).__name__}: {e}"[:200]})
            return self._send({"ok": not errs, "done": out, "failed": errs,
                               "cost": round(sum(x.get("cost") or 0 for x in out), 4)})
        if p.startswith("/api/"): return self._proxy("POST", raw)
        self._send({"error": "no route"}, code=404)

    def _triage_one(self, tid):
        """跑一条并落库。抛异常由调用方收集 —— 批量里一条挂掉不该拖垮整批。"""
        import time as _t
        # 从 ops 队列取,不从 /api/agent-tasks 取 —— 后者只列「待处理」,
        # 一条工单研判过一次就变「待复核」,再想重跑就找不到了。
        q = json.loads(urllib.request.urlopen(
            BACKEND + "/api/ops-queue", timeout=30).read())["rows"]
        t = next((x for x in q if x["task_id"] == tid), None)
        if not t: raise ValueError(f"队列里没有 {tid}")
        t = dict(id=t["task_id"], ref=t["ref"],
                 bp={"财务人工任务": "BP-01", "客户合并确认": "BP-02",
                     "售后判责": "BP-03"}.get(t["type"], "BP-02"))
        if t["bp"] == "BP-03":
            case = t["ref"]
            prompt = (f"任务类型:售后判责\n维修工单号:{t['ref']}\n\n"
                      "客户报修,需要判定责任归属并给出处理方式。"
                      "先用 get_maintain 查现场,再用 kb_tables 取「售后争议判定」,"
                      "对照 09-养护与售后.md 第五节的返修判定表给结论。\n"
                      "两条硬规矩:①「交付告知签收」为 null 就是**没有书面告知**,"
                      "特性类问题在这种情况下按「我方,让步处理」;"
                      "② **你只出草稿,不对客户承诺任何金额或返修结果** —— "
                      "结论必须由店长/客服确认后执行。\n"
                      "按「根因 / 建议动作 / 证据 / 置信度」四段输出,每段单独起一行。")
        elif t["bp"] == "BP-01":
            case = t["ref"]
            prompt = (f"任务类型:财务人工任务\n押金单号:{t['ref']}\n\n"
                      "这笔押金退款已连续失败并转入人工处理。请查清失败的根本原因,"
                      "给出建议的处理动作,并列出支撑结论的证据。"
                      "按「根因 / 建议动作 / 证据 / 置信度」四段输出,每段单独起一行。")
        else:
            a, b2 = t["ref"].split("|"); case = t["id"][1:]
            prompt = (f"任务类型:客户合并确认\n两条疑似重复的客户档案:{a} 和 {b2}\n\n"
                      "请判断是否为同一客户,给出合并或不合并的建议,并逐项列出比对依据。"
                      "按「根因 / 建议动作 / 证据 / 置信度」四段输出,每段单独起一行。")
        t0 = _t.time()
        r = asyncio.run(sdk.run("task", prompt))
        ms = int((_t.time() - t0) * 1000)
        saved = _post("/api/ops-triage", dict(
            task_id=tid, bp=t["bp"], case=case, text=r["text"],
            trajectory=r["trajectory"], cost=r.get("cost_usd"),   # 实价,不是 SDK 报的那个
            usage=r.get("usage"), latency_ms=ms, model=r.get("model"),
            guard_blocked=r.get("guard_blocked"),
            guard_violations=r.get("guard_violations"),
            answer_turns=r.get("answer_turns")))
        row = saved.get("row") or {}
        return dict(task_id=tid, triage_id=saved.get("triage_id"),
                    root_cause=row.get("ai_root_cause"), confidence=row.get("ai_confidence"),
                    tools=row.get("tool_calls"), cost=r.get("cost_usd"), seconds=r["seconds"],
                    guard_blocked=r.get("guard_blocked"),
                    guard=[v["msg"] for v in (r.get("guard_violations") or [])])


def _post(path, payload, timeout=60):
    r = urllib.request.Request(BACKEND + path, method="POST",
                               data=json.dumps(payload, ensure_ascii=False).encode(),
                               headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())


if __name__ == "__main__":
    print(f"澜绣云裳 · 智能运维平台  http://127.0.0.1:{PORT}")
    print(f"  后台数据源:{BACKEND}(本站不直接读库,/api/* 反代过去)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
