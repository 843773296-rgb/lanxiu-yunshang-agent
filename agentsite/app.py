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
from urllib.parse import urlparse, unquote, quote, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.environ.get("LANXIU_BACKEND", "http://127.0.0.1:8760")
PORT = int(os.environ.get("AGENTSITE_PORT", "8770"))
# 首页是值班台,不是导航页 —— 打开就该看见「今天还剩多少件」。
# 新工作站(单壳多屏 + 右侧智能体 + 「?」教学层)。
# 旧的分页仍在原路径上,没删 —— 它们还是 ui_audit 的扫描对象,也方便对照。
# 首页是**一个通用对话助手**,不是导航页也不是多屏工作台。
# 之前那版单壳多屏(值班台/研判队列/面料学堂/着装人/健康 + 「?」教学层)
# 整体挪到 /panels 保住了 —— 里面的教学内容是攒出来的,不能因为换个形态就丢。
PAGES = {"/": "station.html", # 登录与任务:登录态是**后台**发的 session cookie,本站只转发不解读
         "/login": "login.html", "/tasks": "tasks.html",
         # /m 是**客户**用的(手机端自助预约,不登录);/pad 是顾问在平板上看单子的
         "/m": "m.html", "/pad": "pad.html",
         "/fabric": "fabric.html", "/duty": "duty.html", "/queue": "queue.html",
         "/scheme": "scheme.html",
         # 研判设置(用户 10-19 拍):总部运营改时限 / 批量条数 / 提示词版本的草稿、试运行;发布找开发
         "/triage-settings": "triage-settings.html",
         # 研判质量看板(用户 10-19 拍:总部看全部、店长看本店)
         "/triage-board": "triage-board.html",
         # 存过的经营报告:/report 列表,/report?id=RPT… 直达那一份(用户 10-10:确认后要给个链接能直达)
         "/report": "report.html",
         # 定制订单确认书(业务 10-10:收预付款要有书面约定)—— 确认下单时生成,从任务 / chat 给的链接直达
         "/contract": "contract.html",
         # 着装人的身体生命周期 —— 和会员生命周期(新客/沉默/流失)不是一回事
         "/wearers": "wearers.html",
         # ⚠️ 2026-09-28:`/workbench` `/acceptance` `/health` `/ai` `/debug` `/experiments`
         # 这六页**删掉了**,替代品在管理后台(见下面 `已搬走`)。删的过程写在 nav.py。
         # ── 业务后台并进来(用户 2026-09-25 定:真合成一个平台)──────────────
         # 它原来是 :8760 上的一张单页,靠 `/api/*` 取数;而本站**已经把 /api 和 /img
         # 双向反代过去了(cookie 也转)**,所以整套页面搬到这个端口上不用改一行 ——
         # 这也是「合成一个」能当天做完的原因:两个服务不合,**门面合成一个**。
         # ⚠️ 页面文件仍然住在 backend/web/ —— **不拷一份过来**:
         # 拷一份的那天起,两份就开始漂,而漂了不会报错。
         "/ops": "../../backend/web/index.html"}
# ── 搬走了的六页:**留一层「去哪了」,不是 404** ──────────────────────────
#
# 2026-09-28 用户拍的:删页面,但旧地址保留一层提示,两三周后再把这层也撤掉。
# 理由是门店同学里有人把这些地址收藏了,而 **404 只会让人以为系统坏了** ——
# 它不区分「这个功能搬走了」和「这个站出故障了」,而这两件事下一步完全不同。
#
# ⚠️ 状态码用 **410 Gone,不是 200**:410 的意思正是「这个资源曾经在,被有意移除了」。
# 用 200 的话,对**任何机器**来说搬走的页和还在的页长得一模一样 ——
# 而这个项目反复在做的就是别让两件事长得一样。人看到的是同一段话,机器分得开。
#
# 到期撤掉这层的时候,连这个字典一起删。
已搬走 = {
    "/workbench":   ("单条试跑",     "#/tryout"),
    "/acceptance":  ("回归验收",     "#/evals"),
    "/health":      ("智能体健康",   "#/health"),
    "/debug":       ("调试后台",     "#/traces"),
    "/experiments": ("实验对比",     "#/compare"),
    "/ai":          ("AI 调控中心",  "#/traces"),
}
AI模块页 = {f"/ai/{k}" for k in
           ("runs", "cost", "tools", "guards", "skills", "evals", "ops",
            "prompts", "retrieval", "finetune")}
搬走于 = "2026-09-28"
后台地址 = os.environ.get("LANXIU_ADMIN_URL") or "澜绣云裳 AI 管理后台"


def 搬走了的页(路径):
    """旧地址的提示页。返回 (html 字节, 410)。"""
    名, 去 = 已搬走[路径]
    return (f"""<!doctype html><meta charset="utf-8"><title>{名} 已搬家</title>
<style>body{{font-family:-apple-system,"PingFang SC",sans-serif;max-width:640px;
margin:14vh auto;padding:0 24px;color:#2b2b2b;line-height:1.9}}
h1{{font-size:20px;margin:0 0 18px}} code{{background:#f4f2ee;padding:2px 6px;border-radius:3px}}
.q{{color:#8a8a8a;font-size:13px;margin-top:28px;border-top:1px solid #e8e5e0;padding-top:14px}}</style>
<h1>「{名}」已经搬到 AI 管理后台</h1>
<p>这个页面 <code>{路径}</code> 在 {搬走于} 从工作台移走了 ——
<b>不是坏了</b>,是换了地方。</p>
<p>新位置:{后台地址} 的 <code>{去}</code></p>
<p>工作台从现在起<b>只放门店每天要用的业务功能</b>(对话 / 值班 / 研判 /
面料学堂 / 方案 / 着装人 / 后台运营);调 AI 的那一摊整体在管理后台。</p>
<p class="q">这段提示是临时的,过两三周会撤掉。把新地址存一下。</p>""".encode(), 410)

sys.path.insert(0, HERE)
import sdk, sessions


def _u(s):
    """BaseHTTPRequestHandler 按 latin-1 解路径,中文要修回来"""
    try: return s.encode("latin-1").decode("utf-8")
    except Exception: return s


# 不用登录也能开的页:登录页本身、顾客的手机端预约(客户不登录)
免登录页 = ("/login", "/m")


def _登录状态(handler):
    """→ "已登录" / "没登录" / "连不上"。和 `_who` 的区别:**连不上不算没登录**。"""
    ck = handler.headers.get("cookie")
    if not ck or "lx_token=" not in ck:
        return "没登录"
    try:
        req = urllib.request.Request(BACKEND + "/api/me", headers={"cookie": ck})
        with urllib.request.urlopen(req, timeout=10) as r:
            return "已登录" if json.loads(r.read()).get("no") else "没登录"
    except urllib.error.HTTPError as e:
        return "没登录" if e.code == 401 else "连不上"
    except Exception:
        return "连不上"


def _运行版本():
    """这个进程**启动时**的版本号 + 提交号 —— 页面右下角显示的是「正在跑的这一版」,不是仓库里最新的那一版
    (拉了新代码没重启服务时,两者不一样,而那正是出问题时要分清的)。"""
    根 = os.path.dirname(HERE)
    try:
        v = open(os.path.join(根, "VERSION"), encoding="utf-8").read().strip()
    except Exception:
        v = "?"
    try:
        import subprocess as _sp
        h = _sp.run(["git", "rev-parse", "--short", "HEAD"], cwd=根, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        h = ""
    return v, h or "?"


运行版本 = _运行版本()


def _注入版本(html):
    """右下角一行小字:v1.2.0 · 提交号(用户 2026-10-19 拍「发布版本号做」)。不挡点击。"""
    v, h = 运行版本
    块 = (f'<div id="__版本" title="正在运行的版本(服务启动时读的)" style="position:fixed;right:8px;bottom:6px;'
          f'font:11px/1.4 ui-monospace,Menlo,monospace;color:#8a8a8a;opacity:.75;pointer-events:none;z-index:1">'
          f'v{v} · {h}</div>')
    i = html.lower().rfind("</body>")
    return html[:i] + 块 + html[i:] if i >= 0 else html + 块


def _注入登录守卫(html):
    """把 web/_auth_guard.js 放到页面最前面(doctype / charset 之后)—— 页面自己的脚本跑之前就得包好 fetch。"""
    js = open(os.path.join(HERE, "web", "_auth_guard.js"), encoding="utf-8").read()
    块 = "<script>" + js + "</script>"
    m = re.search(r'<meta charset="?utf-8"?>', html, re.I) or re.search(r"<!doctype html>", html, re.I)
    return html[:m.end()] + 块 + html[m.end():] if m else 块 + html


def _记原文访问(me, tid, 行, 因):
    """看原文的每一次请求(放行的、被拒的)记一行:谁、什么角色和门店、看的哪一轮、结果。证据中心 10-25。"""
    import time
    try:
        p = os.path.join(os.path.dirname(HERE), ".feynman", "raw-access.jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"时间": time.strftime("%Y-%m-%d %H:%M:%S"), "谁": (me or {}).get("no"),
                                "姓名": (me or {}).get("name"), "角色": (me or {}).get("role"),
                                "门店": (me or {}).get("shop"), "trace": tid, "放行": bool(行),
                                "理由": 因 or None}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _who(handler):
    """现在是谁在跟智能体说话 —— 从**后台的会话**换出来,不信前端说自己是谁。

    智能体的工具要按这个人的身份取数(顾问只看得到自己的任务)。
    身份来自签发方(后台的 session),不来自使用方 —— 否则一句
    「我以店长身份执行」就能提权。
    """
    ck = handler.headers.get("cookie")
    if not ck: return None
    try:
        req = urllib.request.Request(BACKEND + "/api/me", headers={"cookie": ck})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        return d if d.get("no") else None
    except Exception:
        return None


# ── 单条试运行的结果暂存 ──────────────────────────────────────────
# 两边各跑一次真模型,一共四十秒上下 —— **同步返回会把浏览器挂住**,
# 所以开线程跑、拿号轮询。存在进程内就够了:它是「刚刚那一次」的结果,
# 不是要留档的东西(要留档的走「跑验证集 → 记一次」那条路,那边才有来路)。
_试跑结果 = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, ctype="application/json; charset=utf-8", code=200):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def _proxy(self, method="GET", payload=None):
        """/api/* 与 /img/* 反代到后台 —— 本站不直接读库

        **cookie 必须双向转**:登录态是后台发的 session cookie,
        反代不转的话,浏览器的 cookie 到不了后台(每次都是新访客),
        后台的 set-cookie 也回不到浏览器(登录成功了但存不下来)。
        少转一个方向都是「登录看着成功、下一个请求就没登录」。
        """
        url = BACKEND + self.path
        h = {"content-type": "application/json"}
        ck = self.headers.get("cookie")
        if ck: h["cookie"] = ck
        req = urllib.request.Request(url, method=method, data=payload, headers=h)

        def _back(r, body, code):
            sc = r.headers.get_all("set-cookie") or []
            self.send_response(code)
            self.send_header("content-type", r.headers.get("content-type", "application/json"))
            for v in sc: self.send_header("set-cookie", v)
            self.send_header("content-length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _back(r, r.read(), r.status)
        except urllib.error.HTTPError as e:
            _back(e, e.read(), e.code)
        except Exception as e:
            self._send({"error": f"后台({BACKEND})连不上:{e}。先启动 backend/server.py"}, code=502)

    def do_GET(self):
        p = _u(unquote(urlparse(self.path).path))
        # 搬走的六页(含 /ai 底下那十个模块页)—— 给一句「去哪了」,不给 404。
        # ⚠️ **按模块名逐个列,不用 `startswith("/ai/")`**:后者会把
        # `/ai/rules` 这种**数据口**也吞掉(`/ai/export-finetune` 当初就差点这样被误删)。
        # 「前缀匹配」在这里是个陷阱 —— 页面路径和数据口挤在同一个前缀下。
        _旧 = p if p in 已搬走 else ("/ai" if p in AI模块页 else None)
        if _旧:
            体, 码 = 搬走了的页(_旧)
            return self._send(体, "text/html; charset=utf-8", code=码)
        if p in PAGES:
            f = os.path.normpath(os.path.join(HERE, "web", PAGES[p]))
            if not os.path.exists(f): return self._send({"error": f"缺页面 {PAGES[p]}"}, code=404)
            # 登录失效 → 刷新 / 打开任何一页都直接去登录页(用户 2026-10-19)。
            # ⚠️ 只在**确定没登录**时跳;后台连不上时照常给页面 —— 「后台没起」不是「没登录」,
            #    跳去登录页只会让人以为是自己的问题(登录页那时候也登不进去)。
            if p not in 免登录页 and _登录状态(self) == "没登录":
                self.send_response(302)
                self.send_header("location", "/login?back=" + quote(self.path, safe=""))
                self.send_header("content-length", "0"); self.end_headers(); return
            html = open(f, encoding="utf-8").read()
            # 配色、导航、表格样式只有一份(web/_shell.txt),页面里写 <!--SHELL--> 占位。
            # 抄五份的结果一定是改了四份漏一份 —— 和知识库不许存两遍是同一条理由。
            if "<!--SHELL-->" in html:
                html = html.replace("<!--SHELL-->", open(
                    os.path.join(HERE, "web", "_shell.txt"), encoding="utf-8").read())
            # 导航由 nav.py 现渲染 —— **单一来源**,页面里不许各写一份
            if "<!--NAV-->" in html:
                import nav as _nav
                html = html.replace("<!--NAV-->", _nav.顶栏html(当前=p))
            if p not in 免登录页:
                html = _注入登录守卫(html)
            html = _注入版本(html)
            self._send(html.encode(), "text/html; charset=utf-8"); return
        if p.startswith("/api/") or p.startswith("/img/"): return self._proxy("GET")
        if p == "/report.pdf":
            # 报告导出 PDF(用户 10-10)。**先拿店长自己的 cookie 向后台取这一份** ——
            # 范围规则还是 report_doc.取 那一个函数,取不到(没登录 / 别店的)就到此为止,不出 PDF
            import report_pdf as _rp
            rid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
            h = {"cookie": self.headers.get("cookie") or ""}
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        BACKEND + "/api/report/" + quote(rid), headers=h), timeout=30) as r:
                    报告 = json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.send_response(302)
                    self.send_header("location", "/login?back=" + quote(self.path))
                    self.end_headers(); return
                return self._send(json.loads(e.read() or b"{}") or {"error": f"取不到 {rid}"}, code=e.code)
            b, 原因 = _rp.出PDF(报告)
            if not b: return self._send({"error": 原因}, code=503)
            名 = _rp.文件名(报告)
            self.send_response(200)
            self.send_header("content-type", "application/pdf")
            # 中文文件名走 RFC 5987(filename*),旧浏览器退回 ASCII 那个
            self.send_header("content-disposition",
                             f"attachment; filename=\"report-{quote(str(报告.get('id')))}.pdf\"; filename*=UTF-8''{quote(名)}")
            self.send_header("content-length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if p == "/contract.pdf":
            # 订单确认书下载 —— 和报告 PDF 同一套:先拿登录人自己的 cookie 向后台取,取不到不出
            import report_pdf as _rp
            oid = (parse_qs(urlparse(self.path).query).get("order") or [""])[0]
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        BACKEND + "/api/contract/" + quote(oid), headers={"cookie": self.headers.get("cookie") or ""}),
                        timeout=30) as r:
                    文档 = json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.send_response(302); self.send_header("location", "/login?back=" + quote(self.path))
                    self.end_headers(); return
                return self._send(json.loads(e.read() or b"{}") or {"error": f"取不到 {oid}"}, code=e.code)
            b, 原因 = _rp.出PDF(None, 页=_rp.确认书离线页(文档))
            if not b: return self._send({"error": 原因}, code=503)
            名 = f"澜绣云裳-订单确认书-{文档.get('订单号')}.pdf"
            self.send_response(200)
            self.send_header("content-type", "application/pdf")
            self.send_header("content-disposition",
                             f"attachment; filename=\"contract-{quote(str(文档.get('订单号')))}.pdf\"; filename*=UTF-8''{quote(名)}")
            self.send_header("content-length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if p == "/md.js":
            # 对话页和报告页共用的 Markdown 渲染 —— 一份文件,两页都从这儿取
            return self._send(open(os.path.join(HERE, "web", "_md.js"), "rb").read(),
                              "application/javascript; charset=utf-8")
        if p == "/roles":
            # 角色清单由 sdk 出 —— 名字、职责、工具数、规矩数都在那儿,页面不许抄
            return self._send({"rows": sdk.roles()})
        if p == "/skillsets":
            # 技能分档清单。**从 sdk 出,页面不许抄一份** ——
            # 抄一份的话加一档要改两处,而漏改的那处不会报错,只会少一个选项。
            return self._send({"rows": [
                {"id": k, "name": sdk.SKILL_SET_DESC[k], "n": len(sdk.skills_for(k))}
                for k in ("own", "all", "none")], "default": "own"})
        if p == "/models":
            # 清单由 sdk 从**单价表**长出来,页面不许自己写死一份
            return self._send({"rows": sdk.models(), "default": sdk.网站默认模型()})
        if p == "/nav":
            # 导航清单的**唯一来源**。station 那一页布局特殊、不挂横向顶栏,
            # 它从这儿取同一份清单渲染左栏入口 —— 而不是自己手写一份。
            import nav as _nav
            return self._send({"rows": [dict(路=a, 名=b, 说=c) for a, b, c in _nav.顶栏]})
        # 导出微调训练数据 —— **2026-09-29 删了**,能力归管理后台 `GET /datasets/{id}/export`。
        # 删之前核过一件事:那边的闸遇到「声明了需要脱敏」的数据集会拒绝(脱敏器还没选型),
        # 而澜绣的对话全是真单号 —— 所以**眼下全项目没有一处能导出脱敏后的训练集**。
        # 用户拍的:照删,脱敏规则留在 `aihub.脱敏` 当选型候选。
        # 旧地址给 410 + 去处,不给 404 —— 和六页同一条理由:404 不区分「搬走了」和「站坏了」。
        # 两三周后连同 `已搬走` 一起删。
        if p.startswith("/ai/export-finetune"):
            return self._send({"error": "导出训练数据已搬到管理后台:GET /datasets/{id}/export",
                               "注意": "那边声明了需要脱敏的数据集,在脱敏器选型之前会被拒绝"},
                              code=410)
        if p == "/ai/rules":
            # 77 条规矩的清单 —— 页面上要能挑、能看现在的正文。
            # **不在页面里抄一份** :唯一来源是 prompts.py。
            try:
                import sys as _s
                _s.path.insert(0, os.path.dirname(HERE))
                import prompts as _pr
                rs = {r.id: r for _, r in _pr.all_rules(unique=True)}
                return self._send({"rows": [
                    dict(id=k, 正文=v.text.strip(), 挂在=list(v.needs) or ["所有角色"],
                         管=list(getattr(v, "管", ())), 类型=v.scope)
                    for k, v in sorted(rs.items())]})
            except Exception as e:
                return self._send({"error": f"{type(e).__name__}: {e}"}, code=500)
        if p == "/ai/tryone":
            # 列这一套现在有哪几道题。**每次都重挑夹具** —— 题面里的单号是现挑的,
            # 写死的 id 会被一次合理的数据变更打断。
            try:
                import sys as _s
                _s.path.insert(0, os.path.join(os.path.dirname(HERE), "agent"))
                import tryone as _t
                套 = (parse_qs(urlparse(self.path).query).get("套") or ["workshop"])[0]
                return self._send(dict(套表=_t.套表, **_t.列题(套)))
            except Exception as e:
                return self._send({"error": f"{type(e).__name__}: {e}"}, code=500)
        if p == "/ai/tryone-result":
            号 = (parse_qs(urlparse(self.path).query).get("号") or [""])[0]
            r = _试跑结果.get(号)
            if r is None: return self._send({"状态": "没这个号"}, code=404)
            return self._send(r)
        if p == "/ai/knobs":
            # 旋钮表**从 knobs.py 现读**,不在这儿抄一份 ——
            # 页面上的旋钮和后端真正读的旋钮必须是同一张表,
            # 抄一份出来就会漂,而漂了之后页面上那个就是假旋钮。
            try:
                import sys as _s
                _s.path.insert(0, os.path.join(os.path.dirname(HERE), "agent"))
                import knobs as _kn
                出 = [{k: v for k, v in x.items()} for x in _kn.旋钮表]
                工具 = {}
                try:
                    import sdk as _sdk
                    for 角 in ("all", "kb", "task", "workshop", "finance"):
                        工具[角] = [t.rsplit("__", 1)[-1] for t in _sdk._tools_for(角)]
                except Exception as e:
                    工具 = {"_取不到": f"{type(e).__name__}: {e}"}
                return self._send({"旋钮": 出, "工具": 工具, "落点核对": _kn.落点核对()})
            except Exception as e:
                return self._send({"error": f"{type(e).__name__}: {e}"}, code=500)
        if p.startswith("/exp/"):
            # 实验对比的数据口。版本来自 **git**(一次提交 = 一次跑的存档),
            # 所以这里不碰库、也不另存一份历史 —— 两份历史一定会漂。
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(HERE), "agent"))
                import compare as _cp
                q = {k: unquote(v) for k, v in
                     (x.split("=", 1) for x in (urlparse(self.path).query or "").split("&") if "=" in x)}
                if p == "/exp/suites":
                    out = []
                    for x in _cp.套们():
                        n = len(_cp._git("log", "--format=%H", "--", x["文件"]).strip().splitlines())
                        out.append(dict(x, 版本数=n))
                    return self._send({"rows": sorted(out, key=lambda r: -r["版本数"])})
                if p == "/exp/versions":
                    return self._send({"rows": _cp.版本们(q.get("suite", ""))})
                if p == "/exp/compare":
                    r = _cp.比(q.get("suite", ""), q.get("a", ""), q.get("b", ""))
                    # 结论那一句的解释也从模块出,**页面不许自己抄一份**
                    r["结论说"] = _cp.结论说.get(r.get("结论"), "")
                    return self._send(r)
                return self._send({"error": "no route"}, code=404)
            except Exception as e:
                return self._send({"error": f"{type(e).__name__}: {e}"}, code=500)
        if p.startswith("/spans"):
            # 调试后台的数据口。**读文件,不入库** —— 这份日志是运行时产物,
            # 进库就得跟着做迁移和备份,而它本来就是随时可以删的。
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(HERE), "agent"))
                import spans as _sp
                q = dict(qp.split("=", 1) for qp in (urlparse(self.path).query or "").split("&") if "=" in qp)
                tid = unquote(q.get("trace", ""))
                # 谁能看(2026-10-24 实测:原来不登录就给 200,登录后谁都能看全公司的)—— 判定在 sessions.能看执行记录吗
                import sessions as _ss
                _me = _who(self)
                if p == "/spans/raw":
                    # **原文**(没截断、没打码):权限比执行记录严(sessions.能看原文吗),每次请求都记一笔 ——
                    # 被拒的也记(谁试过看什么,本身就是要留的证据)。用户 10-25 拍「1+2 都要」
                    rows = (_sp.读().get(tid) or []) if tid else []
                    根 = next((x for x in rows if not x.get("parent_span_id")), {})
                    行, 码, 因 = _ss.能看原文吗(_me, 会话号=根.get("会话号"))
                    _记原文访问(_me, tid, 行, 因)
                    if not tid:
                        return self._send({"error": "要给 trace"}, code=400)
                    if not 行:
                        return self._send({"error": 因}, code=码)
                    条, 说明 = _sp.读原文(tid)
                    return self._send({"trace": tid, "条目": 条, "说明": 说明,
                                       "提醒": "sha256 只说明这条存下以后没被改过,不证明采集完整"})
                if not tid:
                    行, 码, 因 = _ss.能看执行记录吗(_me, 列全部=True)
                    if not 行:
                        return self._send({"error": 因}, code=码)
                棵 = _sp.读(限=int(q.get("limit", "40")) if not tid else None)
                if tid:
                    rows = 棵.get(tid) or []
                    根 = next((x for x in rows if not x.get("parent_span_id")), rows[0] if rows else {})
                    行, 码, 因 = _ss.能看执行记录吗(_me, 会话号=根.get("会话号"))
                    if not 行:
                        return self._send({"error": 因}, code=码)
                    # 这一轮每次工具调用实际读了哪些库表(证据中心第五个工作包):工具服务进程里在库这一层观测到的
                    try:
                        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))
                        import db_observe as _dbo
                        库表 = _dbo.读(tid)
                    except Exception:
                        库表 = None
                    try:
                        import skill_states as _ks
                        技能 = _ks.分类(rows)
                    except Exception:
                        技能 = None
                    return self._send({"trace": tid, "spans": rows, "库表": 库表, "技能": 技能,
                                       "账": _sp.一棵的账(rows) if rows else None})
                out = []
                for k, v in 棵.items():
                    根 = next((x for x in v if not x.get("parent_span_id")), v[0])
                    a = 根.get("attr") or {}
                    out.append(dict(trace=k, ts=根.get("ts"), 角色=根.get("角色"),
                                    模型=根.get("模型"), status=根.get("status"),
                                    问=a.get("lanxiu.prompt_chars"),
                                    拦=a.get("lanxiu.guard.blocked"), **_sp.一棵的账(v)))
                return self._send({"rows": list(reversed(out))})
            except Exception as e:
                return self._send({"error": f"{type(e).__name__}: {e}"}, code=500)
        if p == "/healthz":
            return self._send({"ok": True, "backend": BACKEND, "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")})
        self._send({"error": "no route"}, code=404)

    def do_POST(self):
        p = _u(unquote(urlparse(self.path).path))
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if p == "/api/rate-rag":
            # 顾问在聊天框里点了 1-5(业务 2026-10-08 拍:问完直接评,使用者来评)
            try: body = json.loads(raw or b"{}")
            except Exception: return self._send({"error": "请求体不是 JSON"}, code=400)
            rid = (body.get("试跑id") or "").strip()
            分 = body.get("评分")
            if not rid:
                return self._send({"error": "没有 `试跑id` —— 这一轮没查知识库,没东西可评"},
                                  code=400)
            if not isinstance(分, int) or not (1 <= 分 <= 5):
                return self._send({"error": f"评分要是 1-5,给的是 {分!r}"}, code=400)
            r = _评一次检索(rid, 分, body.get("评语"))
            if r.get("ok"):
                # 门店这边留一份分数(知识问题的复验要挑低分,外部复审第 4 节 E)。正本仍在管理后台;
                # 留不下**不装作留下了**,也不把已经评成功的分说成没评上
                try:
                    m = _post_回体("/api/kb-rag-record", {"op": "评分", "试跑id": rid, "评分": 分},
                                  cookie=self.headers.get("cookie"))
                    if not m.get("ok"): r["门店留档"] = m.get("reason") or "没留下"
                except Exception as e:
                    r["门店留档"] = f"没留下:后台连不上({type(e).__name__})"
            return self._send(r, code=(200 if r.get("ok") else 502))
        if p == "/run":
            try: body = json.loads(raw or b"{}")
            except Exception: return self._send({"error": "请求体不是 JSON"}, code=400)
            kind = body.get("kind") or "kb"
            prompt = (body.get("prompt") or "").strip()
            if not prompt: return self._send({"error": "问题是空的"}, code=400)
            # model:"供应商:模型名",来自 /models。不给就走环境变量里的默认。
            # **不传模型时,用网站自己的默认** —— 而不是让它掉到 _env 的脚本默认上。
            # 这两个原来是两个来源:/models 说默认是 claude:sonnet-5,
            # 而不传 model 时实际跑的是 deepseek。**界面说一套、实际做一套**,
            # 而且不会报错 —— 你以为在用订阅,其实在按量计费。
            prov = mdl = None
            mid = (body.get("model") or "").strip() or sdk.网站默认模型()
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
                mv = mdl or (sdk.网站默认模型().split(":",1)[1])
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
                me = _who(self)
                # **没登录不许调智能体**(用户 10-23 拍「先修复」)。原来这里 me=None 照样往下跑 ——
                # 页面有登录守卫,可接口没有:不带 cookie 直接 POST /run 就能问,工具按「没有身份」取数。
                # 读客户数据要登录那条规矩(10-23)守住了页面和后台接口,唯独漏了这个入口。
                if not me:
                    return self._send({"error": "没登录 —— 先登录再问(智能体按你的工号取数)",
                                       "code": "NO_LOGIN"}, code=401)
                # **续聊要核对归属**:session_id 是前端送上来的,身份判得再对,
                # 也挡不住「换一条别人已经判过的历史接着说」——
                # 隔离是按「这轮取什么数」做的,而历史是上一轮就取好的。
                sid_in = body.get("session") or None
                ok_s, why_s = sessions.check(sid_in, me)
                if not ok_s:
                    return self._send({"error": why_s, "code": "SESSION_NOT_YOURS"}, code=403)
                # ── 难题分流(用户 10-25 拍,算法见 model_route.py)── 只在用默认模型、页面没手选过时开:
                # 先 Haiku 跑,出问题 → 换 Opus 重答一次。**不按事情类型分**:意图分类交给 harness 统一调配(用户 10-25)
                import model_route as _mr
                分流 = _mr.分流开着吗(mid, bool(body.get("model_picked")), sdk.网站默认模型())
                跑 = lambda pv, md, **kw: asyncio.run(sdk.run(kind, prompt, resume=sid_in,
                                            provider=pv, model_name=md, images=imgs or None,
                                            me=me, skills=body.get("skills"),
                                            effort=body.get("effort"), **kw))
                with RUNLOCK:
                    if not 分流:
                        r = 跑(prov, mdl)
                        r["路由"] = {"分流": False, "答的": mid}
                    else:
                        r0, 错0 = None, None
                        try:
                            # 分叉:Haiku 这一遍要是被换掉,原会话里不留它半截的痕迹
                            r0 = 跑(prov, mdl, 分叉=True)
                        except Exception as e:
                            错0 = f"{type(e).__name__}: {e}"
                        升, 因 = _mr.该升级吗(r0, 错0)
                        if not 升:
                            r = r0
                            r["路由"] = {"分流": True, "答的": mid, "升级": False}
                        else:
                            up_pv, up_md = _mr.升级到.split(":", 1)
                            r = 跑(up_pv, up_md, 根属性={"lanxiu.route.upgraded": True,
                                                       "lanxiu.route.reason": 因,
                                                       "lanxiu.route.from_model": mid,
                                                       "lanxiu.route.from_trace": (r0 or {}).get("trace_id")})
                            r["路由"] = {"分流": True, "答的": _mr.升级到, "升级": True, "理由": 因,
                                        "先试的": mid, "先试trace": (r0 or {}).get("trace_id"),
                                        "先试花费": (r0 or {}).get("cost_usd")}
                sessions.own(r.get("session_id"), me)
                _记知识检索(r, self.headers.get("cookie"))
                return self._send(r)
            except Exception as e:
                # 跑到一半抛了:根补一条「中断 + 为什么」,trace 号回给页面 —— 失败的那条点得开执行记录,
                # 看得到断之前已经调了哪些工具(证据中心 P0 记录恢复,10-25)
                轮 = getattr(sdk, "最近一轮", None) or (None, None)
                try:
                    import spans as _sp
                    _sp.记中断(轮[0], 轮[1], f"{type(e).__name__}: {e}")
                except Exception:
                    pass
                return self._send({"error": f"{type(e).__name__}: {e}"[:400], "trace_id": 轮[0]}, code=500)
            finally:
                if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True)
        if p == "/ai/candidate":
            # 提示词候选的**写口**:新建 / 存正文 / 采纳 / 跑验证集。
            # ⚠️ **判定一条都不在这儿重写** —— 全部转给 tools/prompt_candidate.py,
            # 那边守着三条硬规矩(找不到候选当场抛 / 只在显式指定时生效 /
            # 没验证记录不许采纳 + 采纳时核对源头还是不是当初那一版)。
            # 页面只是入口,不是第二套规矩。
            try: body = json.loads(raw or b"{}")
            except Exception: return self._send({"error": "请求体不是 JSON"}, code=400)
            try:
                import sys as _s, json as _j, subprocess as _sp
                _s.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
                _s.path.insert(0, os.path.dirname(HERE))
                import prompt_candidate as _pc
                动 = body.get("动作")
                号 = (body.get("号") or "").strip()
                if 动 == "新建":
                    改 = [x for x in (body.get("改") or []) if x]
                    旋 = body.get("旋钮") or {}
                    if not 号 or (not 改 and not 旋):
                        return self._send({"error": "要给方案起个号,并且至少改一条规矩**或**拧一个旋钮"})
                    if os.path.exists(os.path.join(_pc.目录, f"{号}.json")):
                        return self._send({"error": f"候选 {号} 已经有了 —— 换个号,"
                                                    f"别覆盖(覆盖会把之前的验证记录一起抹掉)"})
                    _pc.新建(号, 改, body.get("为什么") or "", 旋钮=旋)
                    return self._send({"ok": True, "号": 号})
                if 动 == "存旋钮":
                    # ⚠️ 校验**在这儿做,而且失败就返回错误** —— 不清洗、不过滤。
                    # 把一个非法旋钮悄悄改成合法的,跑出来的那一轮就不是你配的那一轮了。
                    import sys as _s2
                    _s2.path.insert(0, os.path.join(os.path.dirname(HERE), "agent"))
                    import knobs as _kn
                    d = _pc._读(号)
                    可用 = None
                    try:
                        import sdk as _sdk
                        可用 = _sdk._tools_for(body.get("角色") or "all")
                        可用 = [t.rsplit("__", 1)[-1] for t in 可用]
                    except Exception: pass
                    try:
                        干净, 松, 话 = _kn.校验(body.get("旋钮") or {}, 可用)
                    except ValueError as e:
                        return self._send({"error": str(e)})
                    d["旋钮"] = 干净
                    _pc._写(号, d)
                    return self._send({"ok": True, "旋钮": 干净, "松": 松, "说明": 话,
                                       "note": ("这个方案里有**放松约束**的旋钮 —— "
                                                "可以拿它跑实验,但不许采纳成新默认。") if 松 else ""})
                if 动 == "存正文":
                    d = _pc._读(号)
                    正 = body.get("正文") or {}
                    动过 = [k for k, v in 正.items() if k in (d.get("改") or {})]
                    for k in 动过: d["改"][k] = v if (v := 正[k]) else d["改"][k]
                    _pc._写(号, d)
                    return self._send({"ok": True, "改了": 动过})
                if 动 == "采纳":
                    改了 = _pc.采纳(号)
                    return self._send({"ok": True, "落回": 改了,
                                       "note": "已经写回 prompts.py。**跑一遍门禁再提交** —— "
                                               "提示词有结构检查(按工具装配、编号唯一、"
                                               "定义了的规矩都要被装上)。"})
                if 动 == "试跑一条":
                    # ⚠️ 开线程跑,**立刻返回一个号** —— 页面拿号轮询。
                    import sys as _s3, threading as _th, uuid as _uu
                    _s3.path.insert(0, os.path.join(os.path.dirname(HERE), "agent"))
                    import tryone as _t
                    套, 题号 = body.get("套") or "workshop", body.get("题号") or ""
                    跑号 = _uu.uuid4().hex[:8]
                    _试跑结果[跑号] = {"状态": "跑着", "题号": 题号}
                    def _干(跑号=跑号, 套=套, 题号=题号, 方案=号):
                        # **一律走 Claude**(月租,不额外花钱)—— 这是业务拍过板的,
                        # 不是技术偏好。见 CLAUDE.md 第 4 节。
                        os.environ["LANXIU_PROVIDER"] = "claude"
                        try:
                            r = _t.试跑(套, 题号, 方案 or None)
                            r["状态"] = "好了"
                        except Exception as e:
                            r = {"状态": "崩了", "error": f"{type(e).__name__}: {e}"}
                        _试跑结果[跑号] = r
                    _th.Thread(target=_干, daemon=True).start()
                    return self._send({"ok": True, "跑号": 跑号,
                                       "note": "两边各跑一次真模型,四十秒上下。"
                                               "**跑完看的是差异,不是分数。**"})
                if 动 == "跑验证集":
                    套 = body.get("套") or "agent/factory_eval.py"
                    环 = dict(os.environ, LANXIU_PROMPT_CANDIDATE=号, LANXIU_PROVIDER="claude")
                    日 = os.path.join(os.path.dirname(HERE), ".feynman", f"验证-{号}.log")
                    os.makedirs(os.path.dirname(日), exist_ok=True)
                    f = open(日, "w", encoding="utf-8")
                    _sp.Popen([os.path.join(os.path.dirname(HERE), "agentsite", ".venv", "bin", "python"),
                               os.path.join(os.path.dirname(HERE), 套)],
                              cwd=os.path.dirname(HERE), env=环, stdout=f, stderr=f)
                    return self._send({"ok": True, "在跑": 套, "日志": 日,
                                       "note": "**跑在后台**(要调真模型,几分钟)。跑完回来点「记一次」——"
                                               "记的时候会把那次的模型和代码版本一起存下,"
                                               "**分数要追得到是哪一版跑的**。"})
                if 动 == "记一次":
                    d = _pc.记一次(号, body.get("结果文件") or "")
                    return self._send({"ok": True, "验证": d.get("验证")})
                return self._send({"error": f"不认识的动作:{动}"})
            except SystemExit as e:
                # prompt_candidate 用 sys.exit 拒绝 —— 那句话就是拒绝的理由,原样给页面
                return self._send({"ok": False, "error": str(e)})
            except Exception as e:
                return self._send({"error": f"{type(e).__name__}: {e}"}, code=500)
        if p in ("/run-triage", "/run-batch"):
            # 平台的主循环:从积压队列里取任务 → 跑智能体 → **结果落后台的库**。
            # 它和「单条试跑」的区别只有一句话:那个跑完显示就没了,这个跑完留在队列里等人销账。
            # (单条试跑那条路 2026-09-28 移交管理后台 `#/tryout`,本站的 /run-task 已删。)
            try: body = json.loads(raw or b"{}")
            except Exception: return self._send({"error": "请求体不是 JSON"}, code=400)
            ids = body.get("task_ids") or ([body["task_id"]] if body.get("task_id") else [])
            if not ids:
                # 不传就从队列里自动取:超时的排在前面,取几条由 n 决定(默认 3,别一口气烧钱)
                try:
                    q = json.loads(urllib.request.urlopen(
                        BACKEND + "/api/ops-queue?state=" + quote("未研判"), timeout=30).read())["rows"]
                except Exception as e:
                    # **「超时」和「连不上」要分开说。** 后台(server.py)是单线程的:它正忙着处理别的长请求时,
                    # 取队列要排队,30 秒没轮到就超时 —— 那时它是**在忙**,不是**连不上**。
                    # 10-14 数据工厂拿到「后台连不上:timed out」,而单独取队列 6 毫秒就回 —— 差点照着这句去查 8760 挂没挂。
                    慢 = isinstance(e, TimeoutError) or "timed out" in str(e)
                    return self._send({"error": ("取研判队列时后台 30 秒没回:它一次只处理一个请求,多半正忙着别的,"
                                                 "稍后再点一次;**不是连不上,也不是研判跑挂了**。" if 慢 else
                                                 f"取研判队列时连不上后台(8760 可能没起):{e}")}, code=502)
                # ⚠️ **跳过没有 AI 研判分支的**(2026-10-15)。
                # 「未研判」档里超时的排最前,而超时的最前面恰好全是评价差评 ——
                # 差评的 AI 辅助按业务 2026-10-10 拍板默认关闭(由店长人工确认)。
                # 于是不管用户在哪个档点「研判 3 条」,取到的都是跑不了的那几条,
                # 跑完只得到一句「按设计不跑」。用户 2026-10-14 为此报过「点研判没反应」。
                # > 一个「研判 3 条」和一个「这 3 条一条都跑不了」,在按钮上长得一模一样。
                # 📌 `能跑AI研判` 这个字段**由后台和真正跑的那处用同一份判定算出来**,
                #    这里不按类型自己猜 —— 猜的话,哪天差评的 AI 辅助打开了这里还会拦着。
                # 转人工了的也跳过(用户 10-18 拍:超时 / 失败给「转人工」,转了就不再被自动挑去烧钱)
                try: _转 = set(_post("/api/triage-run-worker", {"op": "handed"}).get("ids") or [])
                except Exception: _转 = set()
                _能跑 = [x for x in q if x.get("能跑AI研判") and x["task_id"] not in _转]
                # 一次最多几条:研判设置里配的(用户 10-19 拍开放给总部运营改),页面填多了也按上限截
                _上限 = _tr_cfg().生效()[0]["批量上限"]
                ids = [x["task_id"] for x in _能跑[: max(1, min(int(body.get("n") or 3), _上限))]]
                if not ids and q:
                    from collections import Counter as _C
                    _类 = "、".join(f"{k} {v} 条" for k, v in _C(x["type"] for x in q).most_common(3))
                    return self._send({"ok": True, "done": [], "note":
                        f"未研判的 {len(q)} 条里没有一条有 AI 研判分支,所以这次一条都没跑 —— "
                        f"不是跑挂了。它们是:{_类}。差评由店长人工确认(业务 2026-10-10 拍),"
                        f"要单独跑某一条请在列表里点开它。"})
            if not ids: return self._send({"ok": True, "done": [], "note": "队列里没有未研判的工单"})
            # ⚠️ **不在这个请求里跑了**(用户 10-18 拍「自建运行记录」)。原来逐条同步跑完才返回:
            # N 条要等几分钟、刷新就丢、两个窗口各点一次就跑两遍。现在只登记、当场返回批次号,
            # 执行线程在后台逐条跑,页面按批次号轮询 /api/triage-run。
            # 身份照转 cookie —— 后台按登录的人记下「谁点的」,站上不解读身份。
            try:
                r = _post("/api/triage-run-submit", {"task_ids": ids}, cookie=self.headers.get("cookie"))
            except urllib.error.HTTPError as e:
                try: msg = json.loads(e.read()).get("error")
                except Exception: msg = str(e)
                return self._send({"error": msg or f"提交研判失败({e.code})"}, code=e.code)
            except Exception as e:
                return self._send({"error": f"提交研判时连不上后台:{e}"}, code=502)
            return self._send({"ok": True, "batch": r.get("batch"), "runs": r.get("runs") or [],
                               "执行线程在吗": _执行线程["活着"]})
        if p.startswith("/api/"): return self._proxy("POST", raw)
        self._send({"error": "no route"}, code=404)

    @staticmethod
    def _triage_one(tid, run_id=None):
        """跑一条并落库。抛异常由调用方收集 —— 批量里一条挂掉不该拖垮整批。
        给了 run_id 就沿途写阶段(取数 → 调模型 → 落库),调模型超过 `单条超时秒` 抛 TimeoutError。"""
        import time as _t
        # 从 ops 队列取。**别改成只列「待处理」的那种取法** ——
        # 一条工单研判过一次就变「待复核」,再想重跑就找不到了。
        # (原来这儿对比的是后台 /api/agent-tasks,那个接口 2026-09-28 随
        #  单条试跑页一起删了;留着一条指向不存在接口的注释比没注释更误导。)
        q = json.loads(urllib.request.urlopen(
            BACKEND + "/api/ops-queue", timeout=30).read())["rows"]
        t = next((x for x in q if x["task_id"] == tid), None)
        # 研判队列 10-15 起只放 AI 能跑的 —— 找不到的多半是不走 AI 的(差评),它们在值班台
        if not t: raise ValueError(f"研判队列里没有 {tid}(不走 AI 的类型,比如差评,在值班台「差评待店长确认」)")
        # **已结束的不重跑**(10-15 外部核查指出、实测属实:「未研判」档 180 条里 166 条早已关单,
        # 自动挑单只看研判状态、不看 done)。重跑 = 白花钱,而且新草稿会盖在一件已经办完的事上。
        # 「待复核」照样能重跑(那条还没结论)—— 这里只拦**结束了**的。
        if t.get("done"):
            raise ValueError(f"{tid} 已经结束({t.get('凭什么销账') or '已销账'}),不重跑 —— 结论不对的话在详情里点「重开」(已办结的开更正工单)")
        # 升级出去的也不重跑(10-17 起「已升级」不算结束、仍在待办里):新草稿会盖在接收人正要看的那条上
        if t.get("state") == "已升级":
            raise ValueError(f"{tid} 已升级给{(t.get('升级') or {}).get('去向') or '上一级'},等接收人接单 / 退回,不重跑")
        # 断点号和提示词**从后台的 ops 取,这边不留第二份** ——
        # 2026-10-11 抽过去的,因为配方新加的「造 triage 样本」那一步也要用它。
        # 两份提示词的后果不是「不一致」,是**样本在替另一句话打分**。
        # 类型没登记时它当场抛,带着为什么(差评的 AI 辅助默认关闭) ——
        # 原来这里是 `.get(类型, "BP-02")`,差评会掉进客户合并分支崩掉。
        _ops_bp = _ops_mod()
        bp, case, prompt = _ops_bp.研判提示词(t["type"], t["ref"], t["task_id"])
        # 用哪版提示词:研判设置里发布了别的版本就用那一版(开发登记、验证过的;用户 10-19 拍),
        # 没发布过就用代码当前这一版。渲染出来的正文和代码直接生成的逐字一致(triage_config_check 验)
        _用 = _tr_cfg().生效()[0]["提示词版本"].get(t["type"])
        研判版 = _ops_bp.研判提示词版本(t["type"])
        if _用 and _用 != 研判版:
            prompt, 研判版 = _tr_cfg().渲染(_用, t["type"], t["ref"], t["task_id"]), _用
        # 版本 = 研判提示词模板 + 智能体系统提示词(装配后的正文)各一个指纹;模型另有一列。
        # 换了任何一段,新研判的版本号就变 —— 配置回退、版本对比都靠它分开新旧(未做项第 5 项第一步)
        import hashlib as _hl
        版 = f"研判:{研判版}·系统:{_hl.sha256(sdk.SYS_TRIAGE.encode('utf-8')).hexdigest()[:12]}"
        t = dict(id=t["task_id"], ref=t["ref"], bp=bp)
        t0 = _t.time()
        if run_id: _阶段(run_id, "调模型")
        try:
            r = asyncio.run(asyncio.wait_for(sdk.run("triage", prompt), 单条超时秒))
        except asyncio.TimeoutError:
            raise TimeoutError(f"调模型超过 {单条超时秒 // 60} 分钟没出结果(平时约 30 秒)—— 没有落草稿,可以转人工")
        if run_id: _阶段(run_id, "落库")
        ms = int((_t.time() - t0) * 1000)
        saved = _post("/api/ops-triage", dict(
            task_id=tid, bp=t["bp"], case=case, text=r["text"],
            trajectory=r["trajectory"], cost=r.get("cost_usd"),   # 实价,不是 SDK 报的那个
            usage=r.get("usage"), latency_ms=ms, model=r.get("model"),
            guard_blocked=r.get("guard_blocked"),
            guard_violations=r.get("guard_violations"),
            交付检查=r.get("交付检查"), 未通过草稿=r.get("未通过草稿"),
            answer_turns=r.get("answer_turns"),
            # ⚠️ 这一条 2026-09-28 补。`sdk.run()` 一直返回 trace_id,
            # 而这里**从来没往后台传** —— 库里每条研判都答不出它是哪一次调用的产物。
            # 缺了它,A3 的判读回流挂不到具体调用上(见 backend/seed.py 那一列的注释)。
            trace_id=r.get("trace_id"),
            prompt_ver=版))
        row = saved.get("row") or {}
        return dict(task_id=tid, triage_id=saved.get("triage_id"),
                    root_cause=row.get("ai_root_cause"), confidence=row.get("ai_confidence"),
                    tools=row.get("tool_calls"), cost=r.get("cost_usd"), seconds=r["seconds"],
                    guard_blocked=r.get("guard_blocked"),
                    guard=[v["msg"] for v in (r.get("guard_violations") or [])])


# ══════════════════════════════════════════════════════════════════════
# 顾问给这一次检索打分(业务 2026-10-08 拍:**chat 问完直接评,使用者来评**)
#
# ⚠️ **为什么要在这儿转一道,而不是让浏览器直接打管理后台:**
#   · 浏览器只跟自己这个站说话 —— 不然要配跨域、要把管理后台的身份头发到前端;
#   · 打分要 `If-Match`(管理后台那边两个人同时评会静默覆盖),
#     而 revision 要先读一次详情才拿得到 —— **那是两步,不该让前端记得做**。
#     > 一个「带了 If-Match」和一个「忘了带」,在前端代码上长得几乎一样,
#     > 而后者会让后到的那个人静默盖掉前一个人的分。
#
# ⚠️ **低于 3 分不在这儿判。** 这里只负责把分数送过去 ——
# 「低于 3 分算问题、要打开分析」是**管理后台那一侧的事**(业务拍的:
# 管理后台只做展示)。在两边都写一遍阈值,它们迟早分叉。
_后台基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
_后台项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
_后台身份 = os.environ.get("AIMC_USER", "U001")


def _评一次检索(试跑id, 分, 评语=None):
    """给一次检索试跑打分。返回 `{ok, …}` 或 `{error, 怎么办}`。

    ⚠️ 失败**不装作成功** —— 评分点了没生效,而界面上显示成功,
    那比点不动糟:顾问以为自己反馈过了。
    """
    import urllib.error
    基 = f"{_后台基址}/api/v1/projects/{_后台项目}/retrieval-runs/{试跑id}"
    头 = {"content-type": "application/json", "X-Dev-User": _后台身份}
    try:
        # ① 先读详情拿 revision(打分要用它做 If-Match)
        q = urllib.request.Request(基, headers={"X-Dev-User": _后台身份})
        d = json.loads(urllib.request.urlopen(q, timeout=20).read())
        rev = d.get("revision")
        if rev is None:
            return {"error": "管理后台没给 revision,打不了分",
                    "怎么办": "这条试跑记录可能不存在了 —— 刷新再问一次"}
        # ② 带着 revision 打分
        体 = json.dumps({"评分": int(分), "评语": (评语 or "")},
                        ensure_ascii=False).encode()
        w = urllib.request.Request(基 + "/rating", method="PATCH", data=体,
                                   headers={**头, "If-Match": str(rev)})
        return {"ok": True, **json.loads(urllib.request.urlopen(w, timeout=20).read())}
    except urllib.error.HTTPError as e:
        try:
            错 = json.loads(e.read())
        except Exception:
            错 = {}
        if e.code == 409:
            # 别人刚评过同一条 —— 说清楚,别让人以为是自己点错了
            return {"error": "这条刚被别人评过了",
                    "怎么办": "刷新一下看看别人评了几分,再决定要不要改"}
        return {"error": f"打分没成功({e.code}):{错.get('message') or ''}"[:160],
                "怎么办": (错.get("advice") or "")[:200] or "过一会儿再试"}
    except Exception as e:
        # ⚠️ 管理后台没起的时候就是这一支。**照实说** ——
        # 业务拍的那条「这条路断了就说出来」在这儿也成立。
        return {"error": f"连不上管理后台({_后台基址})",
                "怎么办": "管理后台没起的话,这个分数记不下来 —— "
                        "起法:`管理后台/tools/dev.sh`。"
                        f"({type(e).__name__})"}


def 知识检索记录们(r):
    """这一轮里 kb_rag 的**真返回值**(轨迹上挂的,不是模型复述的)→ 门店检索记录要的那几样。
    零命中也有 `试跑id`(外部复审第 4 节 E)—— 所以不按 hit 过滤。"""
    出 = []
    for x in (r or {}).get("trajectory") or []:
        t = x.get("result") if isinstance(x, dict) else None
        if str((x or {}).get("tool") or "").split("__")[-1] != "kb_rag" or not isinstance(t, dict):
            continue
        if not t.get("试跑id"):
            continue
        出.append({"试跑id": t["试跑id"], "问的是": t.get("问的是"), "hit": t.get("hit") or 0,
                  "出处们": [e.get("出处") for e in (t.get("证据们") or []) if isinstance(e, dict)],
                  "知识库": t.get("知识库")})
    return 出


def _post_回体(path, payload, cookie=None):
    """同 `_post`,但 4xx 也把后台的回体读回来(没登录 / 被拒要照实说原因,不说成「连不上」)。"""
    try:
        return _post(path, payload, timeout=10, cookie=cookie)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"ok": False, "reason": f"后台回了 {e.code}"}


def _记知识检索(r, cookie):
    """跑完一轮,把这轮的知识检索记进门店检索记录(提问人 = 登录的人,后台按 cookie 判)。
    记不下**不拖垮这一轮回答**,但在返回里说出来 —— 一条没记下的检索和一条没发生的,在问题清单上长得一样。"""
    记 = 知识检索记录们(r)
    if not 记:
        return
    try:
        m = _post_回体("/api/kb-rag-record", {"op": "记录", "记录们": 记}, cookie=cookie)
        if not m.get("ok"):
            r["知识检索留档"] = m.get("reason") or "没记下"
    except Exception as e:
        r["知识检索留档"] = f"没记下:后台连不上({type(e).__name__})"


def _tr_cfg():
    """研判设置(backend/triage_config.py)。和 `_ops_mod` 同一个理由直接 import:同机同仓,不另抄一份。"""
    _ops_mod()
    import triage_config as _c
    return _c


def _ops_mod():
    """后台的 ops 模块。**提示词和断点号只有那一份** —— 站上不抄。

    站和后台在同一台机器、同一个仓库,所以直接 import;跨机部署时这里
    要换成走 HTTP 问后台要提示词,**但不许在这边复制一份**。
    """
    import sys as _s, os as _o
    _b = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "backend")
    if _b not in _s.path:
        _s.path.insert(0, _b)
    import ops as _o2
    return _o2


def _post(path, payload, timeout=60, cookie=None):
    h = {"content-type": "application/json"}
    if cookie: h["cookie"] = cookie
    r = urllib.request.Request(BACKEND + path, method="POST",
                               data=json.dumps(payload, ensure_ascii=False).encode(), headers=h)
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())


# ══════════════════════════════════════════════════════════════════════
# 研判执行线程(用户 2026-10-18 拍:在智能运维平台自建运行记录、单条超时 2 分钟)
#
# 记录在后台的库里(`backend/triage_run.py`),这边只领活、写阶段、收尾 —— 站上照旧不留库。
# 两条线程:一条只报心跳(调模型那 2 分钟里也要报,不然会被当成死了),一条逐条领活跑。
# ⚠️ 起来先收一遍「上一个进程跑到一半的」→ 中断;**排队的不动,接着领** —— 这就是「刷新 / 重启不丢」。
# ⚠️ 一次只跑一条:后台是单线程的,并发跑只会让每条都更慢(10-15 长请求拖垮过一次整站)。
# 超时和心跳的数**只在 triage_run 里有一份**(后台判「心跳断了」也用它),这边不抄
_ops_mod()                    # 把 backend/ 放进 sys.path
import triage_run as _tr
单条超时秒, _心跳间隔 = _tr.单条超时秒, _tr.心跳间隔秒
_执行线程 = {"活着": False}


def _阶段(run_id, stage):
    try: _post("/api/triage-run-worker", {"op": "stage", "run_id": run_id, "stage": stage}, timeout=30)
    except Exception: pass        # 写阶段失败不该让这一条白跑;收尾那一下会再写


def _心跳循环():
    import time as _t
    while True:
        try:
            _post("/api/triage-run-worker", {"op": "beat", "pid": os.getpid()}, timeout=10)
            _执行线程["活着"] = True
        except Exception:
            _执行线程["活着"] = False
        _t.sleep(_心跳间隔)


def _执行循环():
    import time as _t
    while True:
        try:
            _post("/api/triage-run-worker", {"op": "recover"}, timeout=30)
            break
        except Exception:
            _t.sleep(5)           # 后台还没起,等它
    while True:
        try:
            run = _post("/api/triage-run-worker", {"op": "claim"}, timeout=30).get("run")
        except Exception:
            _t.sleep(5); continue
        if not run:
            _t.sleep(2); continue
        结果, 号, 价, 错 = "完成", None, None, None
        try:
            d = H._triage_one(run["task_id"], run_id=run["run_id"])
            号, 价 = d.get("triage_id"), d.get("cost")
        except TimeoutError as e:
            结果, 错 = "超时", str(e)
        except Exception as e:
            结果, 错 = "失败", f"{type(e).__name__}: {e}"
        for _ in range(3):        # 收尾一定要写上 —— 写不上这条就会挂在「落库」,直到心跳断了被标中断
            try:
                _post("/api/triage-run-worker", {"op": "finish", "run_id": run["run_id"], "result": 结果,
                                                 "triage_id": 号, "cost": 价, "error": 错}, timeout=30)
                break
            except Exception:
                _t.sleep(3)


def _起执行线程():
    import threading
    threading.Thread(target=_心跳循环, daemon=True, name="研判心跳").start()
    threading.Thread(target=_执行循环, daemon=True, name="研判执行").start()


if __name__ == "__main__":
    print(f"澜绣云裳 · 智能运维平台  http://127.0.0.1:{PORT}")
    print(f"  后台数据源:{BACKEND}(本站不直接读库,/api/* 反代过去)")
    _起执行线程()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
