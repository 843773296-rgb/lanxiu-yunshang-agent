#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经营报告导出 PDF(用户 10-10:chat 里要有下载入口,日报 / 周报 / 月报直接下 PDF)。

## 怎么出的

**拿报告页本身去打印**,不另写一套 PDF 排版:
`report.html` + 共用的 Markdown 渲染(`_md.js`)+ 这一份报告的数据,拼成一张**自带数据的离线页**,
交给本机 Chrome 的无界面模式 `--print-to-pdf`。

- 为什么不用 Python 的 PDF 库:项目是纯标准库(只有 agentsite 例外),
  中文 PDF 还得自带字体;**而且那是第二套排版** —— 页面上改了版式、PDF 没跟着改,两份就漂了。
- 为什么拼离线页而不是让 Chrome 去开 `/report?id=…`:无界面的 Chrome 没有店长的登录 cookie,
  开出来是登录页。**权限在这一步之前就判完了**(数据是拿店长自己的 cookie 向后台取的),
  离线页里只有他本来就看得到的那一份。

## 代价(说清楚)

- **依赖运行服务那台机器上装着 Chrome**。找不到就明说「这台机器没有 Chrome,导不了 PDF」,
  不静默给一份空文件 —— 页面上的「打开报告」照样能用,浏览器自己也能打印。
- Chrome 无界面模式打完 PDF **常常不自己退出**(10-10 实测:文件 3 秒就写好了,进程挂了两分钟)。
  所以这里不等进程结束,**等文件写完、大小不再变**就收,然后把进程关掉。
"""
import json, os, shutil, subprocess, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

_候选 = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser")


def 找浏览器():
    p = os.environ.get("LANXIU_CHROME")
    if p:
        return p if os.path.exists(p) or shutil.which(p) else None
    for c in _候选:
        if os.path.isabs(c) and os.path.exists(c):
            return c
        if not os.path.isabs(c) and shutil.which(c):
            return shutil.which(c)
    return None


def 离线页(报告):
    """报告页 + 共用渲染 + 这一份数据 → 一张不需要登录、不需要联网的页。"""
    html = open(os.path.join(WEB, "report.html"), encoding="utf-8").read()
    md = open(os.path.join(WEB, "_md.js"), encoding="utf-8").read()
    html = html.replace('<nav class="sitenav"><!--NAV--></nav>', "")
    html = html.replace('<script src="/md.js"></script>', "<script>\n" + md + "\n</script>")
    # 数据塞进页里;「</」转义,否则正文里出现 </script> 就把脚本截断了
    数据 = json.dumps(报告, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("<script>\n/* 存过的经营报告", f"<script>window.__REPORT__ = {数据};</script>\n<script>\n/* 存过的经营报告", 1)
    return html


def 确认书离线页(文档):
    """订单确认书 → 自带数据的离线页(和报告同一个做法:拿页面本身去打,不另写排版)。"""
    html = open(os.path.join(WEB, "contract.html"), encoding="utf-8").read()
    md = open(os.path.join(WEB, "_md.js"), encoding="utf-8").read()
    html = html.replace('<nav class="sitenav"><!--NAV--></nav>', "")
    html = html.replace('<script src="/md.js"></script>', "<script>\n" + md + "\n</script>")
    数据 = json.dumps(文档, ensure_ascii=False).replace("</", "<\\/")
    return html.replace("<script>\n/* 定制订单确认书", f"<script>window.__DOC__ = {数据};</script>\n<script>\n/* 定制订单确认书", 1)


def 文件名(报告):
    种 = {"日": "日报", "周": "周报", "月": "月报"}.get(报告.get("kind"), "报告")
    店 = str(报告.get("shop") or "").split(" ")[-1]
    态 = "" if 报告.get("status") == "已确认" else "-草稿"
    return f"澜绣云裳-{店}-{种}-{报告.get('period_start')}-第{报告.get('revision')}版{态}.pdf"


def 渲染后的页(报告, 限时=60):
    """离线页交给无界面 Chrome 跑完脚本,返回渲染后的 DOM —— 检查用:看正文和冻结的数**真画上了**。
    ⚠️ `--dump-dom` 和打 PDF 一样,**吐完不退出**(10-10 门禁里等满 90 秒超时):读到 `</html>` 就收,再关进程。"""
    import threading
    浏览器 = 找浏览器()
    if not 浏览器:
        return None
    d = tempfile.mkdtemp(prefix="lanxiu-dom-")
    try:
        页 = os.path.join(d, "report.html")
        open(页, "w", encoding="utf-8").write(离线页(报告))
        proc = subprocess.Popen([浏览器, "--headless=new", "--disable-gpu", "--no-first-run", "--virtual-time-budget=5000",
                                 f"--user-data-dir={os.path.join(d, 'profile')}", "--dump-dom", "file://" + 页],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        块, 完 = [], threading.Event()

        def 读():
            for 行 in iter(proc.stdout.readline, b""):
                块.append(行)
                if b"</html>" in 行:
                    break
            完.set()
        threading.Thread(target=读, daemon=True).start()
        完.wait(限时)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        return b"".join(块).decode("utf-8", "replace")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def 出PDF(报告, 限时=60, 页=None):
    """返回 (pdf 字节, None) 或 (None, 原因)。页:现成的离线页 HTML(确认书用);不给就拿报告拼。"""
    浏览器 = 找浏览器()
    if not 浏览器:
        return None, "这台机器上没有 Chrome,导不了 PDF —— 先用「打开报告」看,或在浏览器里打印"
    现成 = 页
    d = tempfile.mkdtemp(prefix="lanxiu-pdf-")
    try:
        页, 出 = os.path.join(d, "report.html"), os.path.join(d, "report.pdf")
        open(页, "w", encoding="utf-8").write(现成 if 现成 else 离线页(报告))
        # 单独的用户目录:不碰用户自己正在用的 Chrome,也不和它抢同一个配置锁
        proc = subprocess.Popen([浏览器, "--headless=new", "--disable-gpu", "--no-first-run",
                                 "--no-pdf-header-footer", "--virtual-time-budget=5000",
                                 f"--user-data-dir={os.path.join(d, 'profile')}",
                                 f"--print-to-pdf={出}", "file://" + 页],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            起, 上次 = time.time(), -1
            while time.time() - 起 < 限时:
                time.sleep(0.5)
                大小 = os.path.getsize(出) if os.path.exists(出) else -1
                if 大小 > 0 and 大小 == 上次:
                    break                    # 连着两次一样大 = 写完了
                if 大小 <= 0 and proc.poll() is not None:
                    return None, "Chrome 退出了但没出 PDF"
                上次 = 大小
            else:
                return None, f"{限时} 秒内没出 PDF"
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
        b = open(出, "rb").read()
        return (b, None) if b.startswith(b"%PDF") else (None, "出来的不是 PDF")
    finally:
        shutil.rmtree(d, ignore_errors=True)
