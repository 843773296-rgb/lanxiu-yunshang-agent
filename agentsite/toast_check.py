#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判队列页 · 提交之后要有看得见的成功 / 失败反馈(用户 2026-10-19:「点击后反馈好弱」)。

原来提交改判 / 升级之后,反馈只是按钮旁一行灰色小字,失败也是灰的 —— 人点完不知道成没成。
现在页面顶上弹一条:成功绿色 3.5 秒消失,失败红色停 10 秒、原样写后端给的理由。要守的:
  · `弹()` 真跑:成功 / 失败两种样式分得开,失败带着那句理由;
  · **页面里每一处提交失败的分支(`r.ok===false`)都弹红** —— 以后新加一个按钮忘了接,这里当场红;
  · 采纳 / 改判 / 升级、接单 / 退回 成功了都弹绿,而且话说得出是哪一种。
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("失败也弹成绿色", "弹():失败是红色、写着「没成」和后端给的理由"),
    ("新加的提交失败分支没接提示条", "页面里每一处提交失败的分支都弹红(以后新加按钮忘了接,这里当场红)"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))


print("研判队列页 · 提交之后的成功 / 失败反馈")
print("=" * 80)
页 = open(os.path.join(HERE, "web", "queue.html"), encoding="utf-8").read()
m = re.search(r"let _弹计时=null;\nfunction 弹\(.*?\n\}", 页, re.S)
js = r"""
const esc=s=>(s??"").toString();
const 元 = {className:"", innerHTML:"", querySelector:()=>({}), };
const $ = s => s==="#toast" ? 元 : null;
global.setTimeout = () => 0; global.clearTimeout = () => {};
""" + (m.group(0) if m else "") + r"""
弹("这条已由工号 60000008 接下升级,只能由接单人复核", "bad");
const 败 = {cls: 元.className, html: 元.innerHTML};
弹("已改判 —— 进了候选", "ok");
const 成 = {cls: 元.className, html: 元.innerHTML};
console.log(JSON.stringify({败, 成}));
"""
f = os.path.join(tempfile.mkdtemp(prefix="toast-"), "t.js")
open(f, "w", encoding="utf-8").write(js)
r = subprocess.run(["node", f], capture_output=True, text=True)
try:
    o = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    o = {}
ck("弹():失败是红色、写着「没成」和后端给的理由", (o.get("败") or {}).get("cls") == "bad"
   and "没成" in o["败"]["html"] and "只能由接单人复核" in o["败"]["html"], r.stderr[-200:] or o)
ck("弹():成功是绿色、写着「成功」", (o.get("成") or {}).get("cls") == "ok" and "成功" in o["成"]["html"], o)

# 每一处「提交失败」的分支都弹红:找出所有含 r.ok===false 的那一行,看同一行里有没有 弹( 或走 提示(…,"bad")
失败行 = [l.strip() for l in 页.splitlines() if "r.ok===false" in l.replace(" ", "")]
漏 = [l[:90] for l in 失败行 if "弹(" not in l and '"bad")' not in l and "失败=" not in l.replace(" ", "")]
ck(f"页面里每一处提交失败的分支都弹红(以后新加按钮忘了接,这里当场红)(扫到 {len(失败行)} 处)",
   len(失败行) >= 5 and not 漏, 漏 or f"只扫到 {len(失败行)} 处")
ck("「失败=…」那种写法(退款块)紧跟着的失败分支也弹红", 'if(失败){ 说("没成:"+(r.error||r.reason||"")); 弹(' in 页)
ck("采纳 / 改判 / 升级成功都弹绿,话说得出是哪一种",
   '"已升级 —— 交给接收岗位' in 页 and '"已改判" + (r.进候选待审核' in 页 and "弹(成, \"ok\")" in 页)
ck("接单 / 退回成功弹绿", '$("#msg").textContent=r.reason||action; 弹(r.reason||action, "ok");' in 页)
ck("必填没填(根因 / 升级原因 / 退回理由)也弹红,不只在角落写一行",
   页.count('弹("改判要先选一个根因", "bad")') == 1 and "弹(\"升级要写原因" in 页 and '弹("退回要写理由", "bad")' in 页)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 提交反馈:成功绿 / 失败红带理由,每一处失败分支都接上了(验了 {n} 条){D}")
