#!/usr/bin/env python3
"""放宽 `agentsite/guards.py` 的 `_有告诫()` —— 「不要说的话」小标题下面的**连续列表项**都算在告诫里,不只前两行。

**为什么要用户亲手跑**:这一改让判据**拦得更少** = 放宽。项目规矩:收紧可以直接改,放宽必须用户执行。
(11-08 eureka-fc 提过这一处,当时的补丁丢了;11-14 按原意重备。)

**误拦的样子**:模型写
    **绝不能说的:**
    - 「这款我们一般不讲价」
    - 「双十一说不定会有活动」
    - 「我去问问店长能不能打个折」     ← 第 3 条起,小标题已经在「前两行」之外
小标题只罩得住下面两条,第三条开始被当成真在许折扣、整段打回。

**这一改做什么**:原来的「整句 + 前两行」**原样保留**,只在它们都没命中时多走一步 ——
当前这一行是列表项(- * • · 1. 1、 (1))时,往上数连续的列表项,**列表一断就停**,
断处那一行(小标题)里有告诫词才算。最多往上数 12 项,超过就不算(防一个告诫罩住整篇)。

**代价(说清楚再跑)**:
    · 告诫小标题下面 12 项以内的列表里,如果夹了一条**真在许折扣**的话,这一支不再拦它;
    · 列表中间插一行普通文字就断开 —— 断开之后的列表项照旧严判(对照里有这一条)。

⚠️ 只在锚**正好出现一次**时才动手;锚不唯一或已变,什么都不改、报错退出。
改完会把改后的 guards.py 在临时目录里真 import 一次,跑该罩 / 该不罩的对照,任何一条不对就不写回。
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile

D = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "agentsite"))
P = os.path.join(D, "guards.py")
旧 = '''    前 = [x for x in text[:i].splitlines() if x.strip()][-3:-1]
    return any(w in x for x in 前 for w in 告诫)
'''
新 = '''    行们 = [x for x in text[:i].splitlines() if x.strip()]
    前 = 行们[-3:-1]
    if any(w in x for x in 前 for w in 告诫): return True
    # 放宽(用户 11-14 执行 tools/放宽补丁/g23_告诫小标题_罩列表.py):告诫小标题下面是**连续列表项**时,
    # 一直罩到列表断为止(最多 12 项)。中间插一行普通文字就断 —— 断开后的列表项照旧严判
    if not 行们 or not _列表项.match(行们[-1]): return False
    k, n = len(行们) - 2, 0
    while k >= 0 and _列表项.match(行们[k]) and n < 12:
        k -= 1; n += 1
    return k >= 0 and n < 12 and any(w in 行们[k] for w in 告诫)


_列表项 = re.compile(r"^\\s*(?:[-*•·]\\s|\\d+[.．、)）]|[（(]\\d+[)）])")   # 符号后面要有空格:「**绝不能说的:**」的星号是加粗不是列表
'''
H = "**绝不能说的:**\n"
该罩 = [   # (文本, 违规词) —— 改后必须算告诫
    (H + "- 「这款不讲价」\n- 「双十一说不定有活动」\n- 「我去问问店长能不能打个折」", "打个折"),
    (H + "1. 不讲价\n2. 有活动\n3. 给您打个九折", "九折"),
    (H + "- a\n- b\n- c\n- d\n- e\n- 「给您打个九折」", "九折"),
]
该不罩 = [  # 改后仍不算告诫(照旧严判)
    (H + "- a\n- b\n- c\n下面是我建议的说法:\n- 今天给您打个九折", "九折"),            # 列表断了
    (H + "".join(f"- 第{n}条\n" for n in range(13)) + "- 给您打个九折", "九折"),         # 超过 12 项
    ("好的,这边给您打个九折。", "九折"),                                                  # 没有小标题
    (H + "- a\n- b\n- c\n\n今天给您打个九折", "九折"),   # 当前行不是列表项
    ("**绝不能说的:**\n**下面是推荐话术:**\n- a\n- b\n- c\n- 给您打个九折", "九折"),  # 加粗的第二个小标题不当列表项
]

s = io.open(P, encoding="utf-8").read()
if "_列表项 = re.compile" in s:
    print("ℹ️ 没动手:看起来已经改过了。"); sys.exit(0)
n = s.count(旧)
if n != 1:
    print(f"❌ 没动手:锚在 {P} 里出现 {n} 次(要正好 1 次)。文件被改过了 —— 让 Claude 重新核一遍再给命令。"); sys.exit(1)
改后 = s.replace(旧, 新)

tmp = tempfile.mkdtemp(prefix="g23试-")
try:
    for f in os.listdir(D):
        if f.endswith(".py"): shutil.copy2(os.path.join(D, f), tmp)
    io.open(os.path.join(tmp, "guards.py"), "w", encoding="utf-8").write(改后)
    sys.path.insert(0, tmp); sys.path.insert(1, os.path.join(D, "..", "agent"))   # guards 要 import agent/textmatch
    spec = importlib.util.spec_from_file_location("guards_改后", os.path.join(tmp, "guards.py"))
    g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    错 = []
    for t, w in 该罩:
        if not g._有告诫(t, t.rindex(w)): 错.append(f"该罩没罩:{t[-30:]!r}")
    for t, w in 该不罩:
        if g._有告诫(t, t.rindex(w)): 错.append(f"不该罩却罩了:{t[-30:]!r}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
if 错:
    print("❌ 没动手:改后的对照不过 ——"); [print("   ", e) for e in 错]; sys.exit(1)
io.open(P, "w", encoding="utf-8").write(改后)
print("✅ 已放宽:告诫小标题下面的连续列表项(最多 12 项)都算告诫")
print(f"   对照:该罩 {len(该罩)} 条全罩、该不罩 {len(该不罩)} 条全不罩(用改后的 guards.py 真 import 跑的)")
print("\n接着跑这条验一下(Claude 会接手补用例并提交):\n   python3 agentsite/guards_test.py            # 必须还是绿的")
