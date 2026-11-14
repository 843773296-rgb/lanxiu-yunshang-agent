#!/usr/bin/env python3
"""放宽 `agentsite/guards.py` 的 `对顾客说的那部分()` —— 挑出话术行时,引导行是列表项就顺着列表往上把小标题也带上。

**为什么要用户亲手跑**:这一改让判据**拦得更少** = 放宽。项目规矩:收紧可以直接改,放宽必须用户执行。
(11-14 第一个补丁 g23_告诫小标题_罩列表.py 用户已跑;跑完补用例时照出这是同一处误拦的**第二层**。)

**误拦的样子**:
    **绝不能说的:**
    - 「这款我们一般不讲价」
    - 「双十一说不定会有活动」
    - 「我去问问店长能不能打个折」     ← 引号里 ≥12 字,被挑出来单独判
挑话术时每句只带**上一行**当引导 —— 第三条带上的是第二条,小标题「绝不能说的」被丢掉,
于是第一个补丁那条「小标题罩住列表」根本看不见小标题,这一句又被当成真在许折扣。

**这一改做什么**:原来的「带上一行」**原样保留**;只在那一行本身是列表项(- * • · 1. 1、 (1))时,
继续往上带连续的列表项,直到断处那一行(小标题)也带上。最多 12 项,超过不带(同第一个补丁的上限)。
带上的都是原文里本来就有的行 —— 只是判的时候看得见它们的小标题了。

**代价(说清楚再跑)**:
    · 告诫小标题下面 12 项以内的长话术列表里,夹了一条**真在许折扣**的话,这一支不再拦它(和第一个补丁同一个代价)。
    · 带上来的列表项也会被一起判 —— 不在告诫小标题下的列表,判得**更严**不是更松(对照里有这一条)。

⚠️ 只在锚**正好出现一次**、且第一个补丁已经跑过(`_列表项` 在文件里)时才动手。
改完会把改后的 guards.py 在临时目录里真 import 一次,用 `g23_discount_promise` 跑该放 / 该拦的对照,任何一条不对就不写回。
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile

D = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "agentsite"))
P = os.path.join(D, "guards.py")
旧 = '''        for j in range(k - 1, -1, -1):          # 往上找第一个非空行当引导
            if 行[j].strip(): 要.add(j); break
'''
新 = '''        for j in range(k - 1, -1, -1):          # 往上找第一个非空行当引导
            if 行[j].strip(): 要.add(j); break
        else:
            continue
        # 放宽(用户 11-14 执行 tools/放宽补丁/g23_对客挑话术_带上小标题.py):引导行本身是列表项时,
        # 顺着连续列表项往上,把断处那一行(小标题)也带上,最多 12 项 —— 否则长列表第三条起看不见「绝不能说的」
        i, n = j, 0
        while i >= 0 and 行[i].strip() and _列表项.match(行[i]) and n < 12:
            要.add(i); i -= 1; n += 1
        if n and n < 12 and i >= 0 and 行[i].strip():
            要.add(i)
'''
H = "**绝不能说的:**\n"
该放 = [
    H + "- 「这款我们一般不讲价的」\n- 「双十一说不定会有活动的」\n- 「我去问问店长能不能打个折」",
    H + "- 「这款我们一般不讲价的」\n- 「双十一说不定会有活动的」\n- 「先说好不讲价」\n- 「我去问问店长能不能给您打个九折」",
]
该拦 = [
    "可以这样说:\n- 「这款料子是真丝的,很适合您」\n- 「今天定的话我给您打个九折吧」",               # 小标题不是告诫
    H + "- 「这款不讲价」\n下面是推荐话术:\n- 「这款料子是真丝的,很适合您」\n- 「今天定的话我给您打个九折吧」",  # 列表断了
    H + "".join(f"- 「这是第{n}条介绍面料的话术」\n" for n in range(13)) + "- 「今天定的话我给您打个九折吧」",    # 超过 12 项
    "好的,今天定的话我给您打个九折吧,您看可以吗?",                                                    # 没有小标题
]

s = io.open(P, encoding="utf-8").read()
if "g23_对客挑话术_带上小标题.py):引导行" in s:
    print("ℹ️ 没动手:看起来已经改过了。"); sys.exit(0)
if "_列表项 = re.compile" not in s:
    print("❌ 没动手:第一个补丁(tools/放宽补丁/g23_告诫小标题_罩列表.py)还没跑 —— 这一个要用它定义的 _列表项。"); sys.exit(1)
n = s.count(旧)
if n != 1:
    print(f"❌ 没动手:锚在 {P} 里出现 {n} 次(要正好 1 次)。文件被改过了 —— 让 Claude 重新核一遍再给命令。"); sys.exit(1)
改后 = s.replace(旧, 新)

tmp = tempfile.mkdtemp(prefix="g23试2-")
try:
    for f in os.listdir(D):
        if f.endswith(".py"): shutil.copy2(os.path.join(D, f), tmp)
    io.open(os.path.join(tmp, "guards.py"), "w", encoding="utf-8").write(改后)
    sys.path.insert(0, tmp); sys.path.insert(1, os.path.join(D, "..", "agent")); sys.path.insert(2, os.path.join(D, "..", "backend"))
    spec = importlib.util.spec_from_file_location("guards_改后2", os.path.join(tmp, "guards.py"))
    g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    错 = [f"该放没放:{t[-28:]!r}" for t in 该放 if g.g23_discount_promise(t, []) is not None]
    错 += [f"该拦没拦:{t[-28:]!r}" for t in 该拦 if g.g23_discount_promise(t, []) is None]
finally:
    shutil.rmtree(tmp, ignore_errors=True)
if 错:
    print("❌ 没动手:改后的对照不过 ——"); [print("   ", e) for e in 错]; sys.exit(1)
io.open(P, "w", encoding="utf-8").write(改后)
print("✅ 已放宽:挑话术时引导行是列表项,就顺着列表把小标题也带上(最多 12 项)")
print(f"   对照:该放 {len(该放)} 条全放、该拦 {len(该拦)} 条全拦(用改后的 guards.py 真 import、真调 g23 跑的)")
print("\n接着跑这条验一下(Claude 会接手补用例并提交):\n   python3 agentsite/guards_test.py            # 必须还是绿的")
