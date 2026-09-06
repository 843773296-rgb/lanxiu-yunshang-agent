#!/usr/bin/env python3
"""页面内联 JS 的语法检查 —— 补上一直缺的那一道。

## 为什么非要有

合并两份前端时踩过:`let FILTER` 被声明了两次。
**`let` 重复声明是语法错,不是运行时错** —— 浏览器**整个 script 一行都不执行**,
于是 CSS 照常渲染出框架,而所有数据加载全没发生。
页面看起来「打开了,只是没数据」,而不是「报错了」。

当时项目里已有的三道前端检查全部没抓到它:

    ui_audit      正则找死控件 —— 不解析 JS
    id 交叉核对    正则比对 #id —— 不解析 JS
    字段核对      比对接口返回 —— 不解析 JS

**三道检查都在用正则看代码,没有一道真的把它当代码解析。**

## 为什么用 node 而不是自己写解析器

语法这件事只有真解析器说了算。node 是开发机和 CI runner 都自带的,
所以这里直接调 `node --check`。

**找不到 node 就直接失败,不静默跳过** ——
一道会安静跳过的检查,和没有这道检查是一回事。
"""
import os, re, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

if not shutil.which("node"):
    print("❌ 找不到 node —— 页面内联 JS 就没法做语法检查。", file=sys.stderr)
    print("   这道检查不静默跳过:装 node,或者明确把这一项从 check.sh 里摘掉。", file=sys.stderr)
    sys.exit(1)

print("页面内联 JS · 语法检查\n" + "=" * 68)
bad, n = [], 0
for fn in sorted(os.listdir(WEB)):
    if not fn.endswith(".html"): continue
    src = open(os.path.join(WEB, fn), encoding="utf-8").read()
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S)
    if not blocks:
        print(f"  ·  {fn:22s} 没有内联脚本"); continue
    for i, js in enumerate(blocks):
        n += 1
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(js); tmp = f.name
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        os.unlink(tmp)
        if r.returncode:
            err = [l for l in r.stderr.splitlines() if "Error" in l or "^" in l][:2]
            bad.append((fn, i, " / ".join(x.strip() for x in err)))
            print(f"  ❌ {fn:22s} 第 {i+1} 段:{err[0] if err else '语法错'}")
        else:
            print(f"  ✅ {fn:22s} 第 {i+1} 段 {len(js.splitlines()):>4} 行")

print("\n" + "=" * 68)
if bad:
    print(f"❌ {len(bad)} 段有语法错 —— **浏览器会整段不执行**:框架照常渲染,数据一个都不加载。")
    for f, i, e in bad: print(f"   · {f} 第 {i+1} 段:{e}")
    sys.exit(1)
print(f"✅ {n} 段内联脚本语法均正常")
