#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「加资料」页在**真浏览器**里点一遍(Firefox + Selenium)。

## 为什么非要真浏览器

这一页的三步链路(`走三步()`)**别的测试一条都覆盖不到**:

  · `tests/e2e/test_upload_flow.py` 打的是接口,不经过页面
  · `tests/e2e/page_smoke.js` 只**加载**页面(最小 DOM 桩),它不点按钮 ——
    而且那个桩里没有 `File`、没有 `<input type=file>`、`fetch` 也是假的
  · `test_upload_flow.py` 第 ⑭ 组从 `app.js` 抠字段名和真响应对账 ——
    它挡得住「引了个接口不返回的字段」,**挡不住 JS 真的跑起来会不会炸**

三者合起来仍然留着一个洞:**这段 JS 从来没被真正执行过。**
`FormData` 用错、`await` 漏掉、`files[0]` 拿不到 —— 这些错法在上面三样里
全都看不出来,而它们在界面上的表现是「点了没反应」。

## ⚠️ 为什么是可见窗口,不是 headless

headless 下 Firefox 156 在建会话时卡住,驱动日志里是:

    Prompter: internal dialogs not available in this context.
    Falling back to window prompt.

一个关不掉的模态框。可见窗口没有这个问题。
**代价写清**:这一份会在屏幕上弹一个 Firefox 窗口,所以它
**不进 `make test-e2e`,也不进 CI** —— 单独 `make test-browser`。

## 缺前提怎么办

要 Firefox、要 `selenium`、要 `make dev`。缺哪个都**明确报出来并退非 0** ——
「跳过了」和「通过了」在输出上长得一模一样。
⚠️ `selenium` **不在 `requirements.lock` 里**:它只给这一份用,
而把一个只有本机用得上的浏览器驱动钉进锁文件,会让 CI 也去装它。
"""
import os
import sys
import time

_这里 = os.path.dirname(os.path.abspath(__file__))
_根 = os.path.dirname(os.path.dirname(_这里))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
FIREFOX = os.environ.get("FIREFOX_BIN", "/Applications/Firefox.app/Contents/MacOS/firefox")

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 没法测(为什么):
    print(f"❌ 没东西可测:{为什么}")
    print("   **这不叫跳过** —— 跳过和通过在输出上长得一模一样,所以退非 0")
    sys.exit(1)


try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:
    没法测("没装 selenium —— `./.venv/bin/pip install selenium`。"
          "它**故意不在 requirements.lock 里**:只给这一份用,"
          "钉进锁文件会让 CI 也去装")
if not os.path.exists(FIREFOX):
    没法测(f"找不到 Firefox({FIREFOX})—— 用 FIREFOX_BIN 指一个")

import urllib.error
import urllib.request
try:
    urllib.request.urlopen(基址 + "/api/healthz", timeout=5).read()
except Exception as e:
    没法测(f"连不上 {基址}({e})—— 先 `make dev`")


# ── 准备一份真文件 ────────────────────────────────────────────────
唯一 = str(int(time.time()))[-6:]
好文件 = os.path.join("/tmp", f"浏览器实测-好的-{唯一}.md")
坏文件 = os.path.join("/tmp", f"浏览器实测-GBK-{唯一}.txt")
with open(好文件, "w", encoding="utf-8") as f:
    f.write(f"# 浏览器实测 {唯一}\n\n"
            "这一份是从 Firefox 里真的选进去、真的点了上传的。\n\n"
            "它要证明的不是接口通,是**那段 JS 真的跑起来了**。\n")
with open(坏文件, "wb") as f:
    # ⚠️ **GBK**:用来验「校验没过时页面显示的是理由,不是「请求出错」」
    f.write("这份是 GBK 编码的,服务端严格解码会拒它。".encode("gbk"))

选项 = Options()
# ⚠️ 不用 headless —— 见文件头:Firefox 156 headless 下建会话卡在一个模态框上
#
# ⚠️⚠️ **而那个模态框的根因是系统代理。** 这台机器上跑着一个本地代理
# (`moz-proxy://127.0.0.1:8787`,gost),Firefox 继承了 macOS 的系统代理设置,
# 于是连 `127.0.0.1:8801` 也先要过代理认证 —— 弹出来的是一个要用户名密码的框。
# headless 下没人能关掉它,所以建会话直接卡死;可见窗口下 Marionette 报
# `UnexpectedAlertPresentException`,那句报错才把根因说了出来。
#
# 这和「这台机器 TLS 拦截,脚本里的 HTTP 请求走 curl」是**同一个东西** ——
# `curl` 一直没事,是因为它不读系统代理设置。
#
# 所以这个**一次性 profile 里直接关掉代理**(`network.proxy.type = 0`)。
# 我们打的是 127.0.0.1,本来就不需要代理。
# ⚠️ **不去填那个密码框** —— 一个测试脚本不该碰凭据。
选项.set_preference("network.proxy.type", 0)
# 有些版本会「劫持」localhost 走代理,顺手也关掉
选项.set_preference("network.proxy.allow_hijacking_localhost", False)
# ⚠️ 万一还有别的对话框,让它**当场报错**而不是挂着等 ——
# 「卡住 60 秒然后超时」和「弹了个框」读起来完全不同,而后者才指向根因。
选项.set_capability("unhandledPromptBehavior", "dismiss and notify")
for k, v in {
    "browser.shell.checkDefaultBrowser": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "browser.aboutwelcome.enabled": False,
    "datareporting.policy.dataSubmissionEnabled": False,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "browser.startup.page": 0,
    "signon.rememberSignons": False,
    "app.update.auto": False,
    "browser.tabs.warnOnClose": False,
}.items():
    选项.set_preference(k, v)
选项.binary_location = FIREFOX
服务 = Service(log_output=os.path.join("/tmp", f"gecko-{唯一}.log"))

浏览器 = None
try:
    try:
        浏览器 = webdriver.Firefox(options=选项, service=服务)
    except Exception as e:
        没法测(f"Firefox 起不来:{type(e).__name__} {str(e)[:200]} —— "
              f"驱动日志 /tmp/gecko-{唯一}.log")
    浏览器.set_page_load_timeout(30)
    等 = WebDriverWait(浏览器, 60)

    print("▸ ① 打开「加资料」页")
    浏览器.get(f"{基址}/#/uploads")
    等.until(EC.presence_of_element_located((By.ID, "f")))
    ck("页面加载出来了,标题对", "澜绣云裳" in 浏览器.title, 浏览器.title)
    ck("有文件选择框(`#f`)", bool(浏览器.find_elements(By.ID, "f")))
    ck("有「上传并校验」按钮(`#go`)", bool(浏览器.find_elements(By.ID, "go")))
    # ⚠️ 顺带验一件 page_smoke 验不了的:**控制台没报错**。
    # 一个抛在加载路径里的 JS 错误不会让页面空白,它只让某一块不渲染。
    日志 = []
    try:
        日志 = [x for x in 浏览器.get_log("browser")
              if x.get("level") in ("SEVERE", "ERROR")]
    except Exception:
        日志 = None          # Firefox 不一定支持 get_log —— **不当成「没错误」**
    if 日志 is None:
        print("     (Firefox 不给 console 日志 —— **不当成「没报错」**,"
              "这一条这里测不了)")
    else:
        ck("控制台没有 SEVERE 级错误", not 日志, 日志[:2])

    print("▸ ② 选一个真文件,点上传 —— **这段 JS 从来没被真正执行过**")
    浏览器.find_element(By.ID, "f").send_keys(好文件)
    ck("文件真的进了 input(`files[0]` 拿得到)",
       浏览器.execute_script("return document.getElementById('f').files.length") == 1)
    浏览器.find_element(By.ID, "go").click()

    # 三步是异步的 —— 等「已校验」出现在步骤区里
    def 步骤文():
        return 浏览器.find_element(By.ID, "步").text

    try:
        等.until(lambda _: "已校验" in 步骤文() or "校验没过" in 步骤文())
    except TimeoutException:
        ck("三步跑完(等到出现校验结论)", False, f"60 秒没等到。步骤区现在:{步骤文()[:200]}")
    else:
        文 = 步骤文()
        ck("三步跑完了", True)
        ck("第一步显示拿到地址、状态「待上传」", "待上传" in 文, 文[:60])
        ck("第二步显示字节到了,**而且明说「还不能引用」** —— "
           "进度条到 100% 不等于资料能用",
           "还不能引用" in 文, [l for l in 文.split("\n") if "字节到了" in l][:1])
        ck("第三步显示「已校验 —— 现在才算文件引用」", "已校验" in 文)
        ck("显示了内容哈希(服务端算的)", "sha256" in 文 or "…" in 文, 文[-90:])
        ck("显示了切出几块", "块" in 文, [l for l in 文.split("\n") if "块" in l][:1])

    print("▸ ③ 表格真的刷新了(不用手动刷页面)")
    表 = 浏览器.find_element(By.ID, "表").text
    ck("刚传的文件名出现在表里", os.path.basename(好文件) in 表,
       表.split("\n")[:3])
    ck("表里有「已校验」和「能」", "已校验" in 表 and "能" in 表)

    print("▸ ④ 坏文件:页面要显示**哪条规则没过**,不是「请求出错」")
    浏览器.get(f"{基址}/#/uploads")
    等.until(EC.presence_of_element_located((By.ID, "f")))
    浏览器.find_element(By.ID, "f").send_keys(坏文件)
    浏览器.find_element(By.ID, "go").click()
    try:
        等.until(lambda _: "校验没过" in 步骤文())
    except TimeoutException:
        ck("坏文件走完三步并显示「校验没过」", False, f"步骤区:{步骤文()[:200]}")
    else:
        文 = 步骤文()
        ck("显示「校验没过」", True)
        ck("**点名了没过的规则**(UTF-8 严格解码),不是笼统的「格式错误」",
           "UTF-8" in 文, [l for l in 文.split("\n") if "UTF" in l][:1])
        ck("说清「请求本身是成功的 —— 一个坏文件不是一次失败的请求」",
           "不是一次失败的请求" in 文)
        ck("列出了**查了哪些规则**(报「没过什么」时同时报「查了什么」)",
           "查了这些规则" in 文)
        ck("说清「这是终态」,要重传得再走一遍", "终态" in 文)
        ck("**没有显示成错误块**(错误块是给「请求失败」用的)",
           "出错了" not in 文 and "服务端没给建议" not in 文, 文[:80])

    print("▸ ⑤ 侧栏入口在(不是只有直接敲 URL 才进得去)")
    浏览器.get(f"{基址}/#/kb")
    等.until(EC.presence_of_element_located((By.ID, "side")))
    侧 = 浏览器.find_element(By.ID, "side").text
    ck("侧栏里有「加资料」", "加资料" in 侧, 侧.replace("\n", " / ")[:120])
    链 = [a.get_attribute("href") for a in 浏览器.find_elements(By.CSS_SELECTOR, "#side a")]
    ck("而且它真的链到 #/uploads", any((h or "").endswith("#/uploads") for h in 链))

finally:
    if 浏览器 is not None:
        浏览器.quit()
    for p in (好文件, 坏文件):
        try:
            os.unlink(p)
        except OSError:
            pass

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
