#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布版本号对账(用户 2026-10-19 拍「发布版本号做」)。

为什么要它:需求文档从 2026-09-18 起写着 V1.0,版本记录表里 09-19 加了一行 V1.1,
**标题却一直没跟着改** —— 一千多次提交之后还挂着 V1.0,没有任何东西会因此报红。
版本号只记在仓库根目录 `VERSION`;这里盯住「凡是写版本号的地方,都和它对得上」:
  · VERSION 是 主.次.修;
  · 需求文档:标题、「文档版本」那一格、版本记录表里有这一版的行;产品说明的版本行;
  · 发布记录里有这一版那一节(「改了什么」从 git 生成,见 tools/release.py);
  · 页面右下角真的注入了版本号;发布命令参数拼错拒跑。
⚠️ 不验 git tag:CI 的检出默认不带 tag,验了就是「本地绿、CI 红」。tag 由 `release.py 打标签` 在门禁之后打。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("需求文档标题的版本号没跟着升", "需求文档:标题、「文档版本」那一格、版本记录表都是这一版"),
    ("页面不显示版本号", "页面右下角显示正在运行的版本号(所有页面都过这一处)"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


def 读(名):
    return open(os.path.join(ROOT, 名), encoding="utf-8").read()


print("发布版本号对账")
print("=" * 80)
v = 读("VERSION").strip() if os.path.exists(os.path.join(ROOT, "VERSION")) else ""
ck("VERSION 是 主.次.修", bool(re.fullmatch(r"\d+\.\d+\.\d+", v)), repr(v))
主次 = ".".join(v.split(".")[:2]) if v else "?"
需 = 读("澜绣云裳agent-产品需求文档.md")
ck("需求文档:标题、「文档版本」那一格、版本记录表都是这一版",
   需.splitlines()[0].endswith(f"_V{主次}") and f"| 文档版本 | V{主次} |" in 需
   and re.search(rf"^\| V{re.escape(主次)} \| \d{{4}}-\d\d-\d\d \|", 需, re.M) is not None,
   (需.splitlines()[0], 主次))
说 = 读("澜绣云裳agent-产品说明.md")
ck("产品说明的版本行是这一版", f"> 版本:V{主次} " in 说)
记 = 读("澜绣云裳agent-发布记录.md") if os.path.exists(os.path.join(ROOT, "澜绣云裳agent-发布记录.md")) else ""
ck("发布记录里有这一版那一节,而且在最上面", re.search(r"^## v(\S+) ", 记, re.M) is not None
   and re.search(r"^## v(\S+) ", 记, re.M).group(1) == v, v)
站 = 读("agentsite/app.py")
ck("页面右下角显示正在运行的版本号(所有页面都过这一处)",
   "            html = _注入版本(html)\n" in 站 and "def _运行版本():" in 站)
p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release.py"), "准备", "1.9"],
                   capture_output=True, text=True)
ck("发布命令参数不对拒跑(不会悄悄改 VERSION)", p.returncode != 0 and 读("VERSION").strip() == v)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 版本号 v{v}:VERSION、需求文档、产品说明、发布记录、页面对得上(验了 {n} 条){D}")
