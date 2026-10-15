#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页面 fetch 的每个地址,都得在**对的那个处理器**里有分支

## 这条检查是怎么来的(2026-09-25 真踩到)

新加的三个读接口写进了 `do_POST`,而页面是用 GET 去取的 —— 结果是
**浏览器里那一整块功能加载不出来,后端却完全正常**:
模块能导入、自测全过、JS 语法没问题、检查全绿。

已有的三道前端检查(死控件 / id 引用 / 字段比对)都是正则,`js_check` 只解析语法,
**没有一道会去问「这个地址后端接不接」** —— 更没有一道会问
「接它的是 GET 还是 POST」。

> **路由写错处理器,和路由压根没写,在后端看起来一模一样** ——
> 两种情况下 `do_GET` 里都找不到它。而前端只会拿到一句 `no route`。

这和 CLAUDE.md 第 7 条第 1 项(`allowed_tools` 以为封住了其实没封)是同一个形状:
**「写了」和「写在生效的地方」是两回事。**
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

咬合 = [
    ("把某个 GET 接口的分支从 do_GET 挪到 do_POST", "页面 GET 的地址,do_GET 里都有分支"),
    ("在页面里 fetch 一个后端没有的地址",            "页面 GET 的地址,do_GET 里都有分支"),
    ("把后端 /api/refund-state 挪回 `/api/ops-` 那一段里(有分支、进不去)", "后端接这个地址的分支进得去(外面那层 if 不挡它)"),
]

过, 挂 = [], []
def ck(名, 真, 补=""):
    (过 if 真 else 挂).append(名)
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 else ''}")

src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
iG, iP = src.find("def do_GET(self):"), src.find("def do_POST(self):")
assert 0 < iG < iP, "找不到 do_GET / do_POST,或者顺序变了 —— 这条检查得跟着改"
GET段, POST段 = src[iG:iP], src[iP:]

def 有分支(段, 路):
    """`p == "/x"` / `p in ("/x", "/y")` / `p.startswith("/x")` 都算。

    ⚠️ 第一版只认 `p ==`,于是把 `p in ("/run-triage", "/run-batch")` 判成了漏 ——
    **两条真接得住的路由被报成红**。修的是判据,不是开豁免:
    写成 `in (...)` 和写成 `==` 是同一件事,认不出来是尺子的问题。
    """
    if re.search(r'p\s*==\s*["\']' + re.escape(路) + r'["\']', 段): return True
    for m in re.finditer(r'p\s+in\s*\(([^)]*)\)', 段):
        if re.search(r'["\']' + re.escape(路) + r'["\']', m.group(1)): return True
    for m in re.finditer(r'p\.startswith\(["\']([^"\']+)["\']\)', 段):
        if 路.startswith(m.group(1)): return True
    # PAGES 那张表里的静态页也算(它在 do_GET 里统一发)
    return False

页表 = set(re.findall(r'["\'](/[a-zA-Z0-9/_-]*)["\']\s*:\s*["\'][a-zA-Z0-9_.-]+\.html["\']', src))
页表 |= set(re.findall(r'f"/ai/\{k\}"', src))          # 那一行是批量生成的,单独记

# ── 后端(backend/server.py):`/api/` 走反代到这里。**光有分支不够,还得进得去** ──
后src = open(os.path.join(HERE, "..", "backend", "server.py"), encoding="utf-8").read()
_g, _p = 后src.find("def do_GET(self):"), 后src.find("def do_POST(self):")
assert 0 < _g < _p, "后端找不到 do_GET / do_POST,或者顺序变了 —— 这条检查得跟着改"
后GET段, 后POST段 = 后src[_g:_p], 后src[_p:]


def 有专门分支(段, 路):
    """同 `有分支`,但 `p.startswith("/api/")` / `("/api")` 这种笼统转发不算。
    也认「不经过 p、直接拿解析后的路径比」的写法:后端 /api/me 写的是
    `_u(unquote(urlparse(self.path).path)) == "/api/me"` —— 只认 `p ==` 的话会把它报成没有(第一次跑就误报了)。"""
    if re.search(r'==\s*["\']' + re.escape(路) + r'["\']', 段): return True
    for m in re.finditer(r'p\s+in\s*\(([^)]*)\)', 段):
        if re.search(r'["\']' + re.escape(路) + r'["\']', m.group(1)): return True
    for m in re.finditer(r'p\.startswith\(["\']([^"\']+)["\']\)', 段):
        if m.group(1).rstrip("/") != "/api" and 路.startswith(m.group(1)): return True
    return False


def 进得去(段, 路):
    """找到接这个路径的分支,再往上看**套在它外面**的每一层 `if p…`:这个路径都得过得去。
    只认 `p ==` / `p in (…)` / `p.startswith(…)` 三种外层条件;别的条件(登录、角色)不管 —— 那是运行时的事。"""
    行们 = 段.split("\n")
    for i, l in enumerate(行们):
        if not 有专门分支(l, 路): continue     # 笼统的 startswith("/api/") 不算「接住了」(那样 /api 下全都算过)
        缩 = len(l) - len(l.lstrip())
        通 = True
        for j in range(i - 1, -1, -1):
            u = 行们[j]
            if not u.strip(): continue
            c = len(u) - len(u.lstrip())
            if c >= 缩: continue
            缩 = c
            if re.match(r"\s*def\s", u): break
            if re.match(r"\s*(el)?if\s", u) and re.search(r"\bp\s*(==|in\s*\(|\.startswith\()", u) and not 有分支(u, 路):
                通 = False; break
        if 通: return True
    return False


漏, 错器, 进不去 = [], [], []
查过 = 0
for fn in sorted(os.listdir(WEB)):
    if not fn.endswith(".html"): continue
    t = open(os.path.join(WEB, fn), encoding="utf-8").read()
    for m in re.finditer(r'fetch\(\s*"(/[^"?]*)', t):
        路 = m.group(1)
        # 判断这次 fetch 是不是 POST:看它后面那一小段里有没有 method:"POST"
        尾 = t[m.end():m.end() + 260]
        是POST = 'method:"POST"' in 尾.replace(" ", "") or "method:'POST'" in 尾.replace(" ", "")
        查过 += 1
        段 = POST段 if 是POST else GET段
        另 = GET段 if 是POST else POST段
        if 路.startswith("/api/"):
            # 走反代 —— **要放在「前台有分支就算过」前面**:前台那条笼统的 /api/ 转发会让它先放行(咬合第二次抓到)。
            # **原来到这儿就算过**,而后端到底接不接从没人核(10-15 抓到):
            # /api/refund-state 写进了后端 do_GET 里 `if p.startswith("/api/ops-")` 那一段,
            # 路径不是 ops- 开头永远进不来,弹窗只拿到 not found —— 而这条检查是绿的。
            后段 = 后POST段 if 是POST else 后GET段
            后另 = 后GET段 if 是POST else 后POST段
            # 前台**专门写了这个路径**的分支才算(比如 /run-triage 那种);那条笼统的「/api/ 一律转发」不算 ——
            # 第一版把它也算进去,于是所有 /api/ 都被它放行,后端那层一次没核到(咬合当场抓到)
            if 进得去(后段, 路) or 有专门分支(段, 路): continue
            if 有专门分支(后段, 路):
                进不去.append(f"{fn}:{路} 后端 do_{'POST' if 是POST else 'GET'} 里有分支,但外面那层条件它过不去(进不去)")
            elif 有分支(后另, 路):
                错器.append(f"{fn}:{路} 是用 {'POST' if 是POST else 'GET'} 取的,但后端分支写在 do_{'GET' if 是POST else 'POST'} 里")
            else:
                漏.append(f"{fn}:{路}(前台、后端都没有)")
            continue
        if 有分支(段, 路): continue
        if 路 in 页表: continue
        if 有分支(另, 路):
            错器.append(f"{fn}:{路} 是用 {'POST' if 是POST else 'GET'} 取的,"
                        f"但分支写在 do_{'GET' if 是POST else 'POST'} 里")
        else:
            漏.append(f"{fn}:{路}(两个处理器里都没有)")

# **样本量为 0 要红** —— 空集合上所有性质都成立,
# 「一个 fetch 都没扫到」和「全都对」在输出上长得一模一样。
ck(f"扫到了页面里的 fetch(共 {查过} 处)", 查过 >= 10, 查过)
ck("页面 GET 的地址,do_GET 里都有分支;POST 的在 do_POST 里", not 错器, 错器[:2])
ck("页面 fetch 的地址后端都接得住", not 漏, 漏[:3])
ck("后端接这个地址的分支进得去(外面那层 if 不挡它)", not 进不去, 进不去[:3])

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
sys.exit(1 if 挂 else 0)
