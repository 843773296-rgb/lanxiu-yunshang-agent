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

漏, 错器 = [], []
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
        if 有分支(段, 路): continue
        if 路.startswith("/api/"): continue          # 走反代,后端那边接
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

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
sys.exit(1 if 挂 else 0)
