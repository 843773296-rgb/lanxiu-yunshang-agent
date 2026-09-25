#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调参旋钮 · 结构检查

**这套检查守的就一件事:页面上的旋钮不许是假的。**

「假旋钮」= 界面上能拧、后端不读。它比没有这个功能糟得多 ——
拖动它回答不会有任何变化,而人会以为自己在调,于是把问题往错的方向查。
`sdk.py` 里为这件事写过一整段(为什么不放温度滑块),这个文件是把那段话做成闸。
"""
import os, sys, re
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "agentsite")]
import knobs as K

# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏什么」,右边「预期红的那一条」。
咬合 = [
    ("把某个旋钮的落点改成一个不存在的名字",
     "个旋钮的落点都搜得到(防假旋钮)"),
    ("让 校验() 把白名单外的工具过滤掉而不是抛",
     "**放宽**到白名单外 → 当场抛(不是过滤掉)"),
    ("让 校验() 静默忽略认不出的旋钮名",
     "**拼错/不存在的旋钮名 → 抛**(静默退回默认 = 分数差归错因)"),
    ("把 sdk.run() 里套旋钮的那几行挪到 opts 构造之后",
     "旋钮在 ClaudeAgentOptions 构造**之前**生效(之后套 = 假旋钮)"),
    ("去掉工具名的短名/全名归一(_短)",
     "给短名、白名单是全名 → 认得出(不误判成放宽)"),
]

过, 挂 = [], []
def ck(名, 真, 补=""):
    (过 if 真 else 挂).append(名)
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:120]) if 补 else ''}")

# ── ① 落点:每个旋钮都真的接上了 ────────────────────────────────────
坏 = K.落点核对()
ck(f"{len(K.旋钮表)} 个旋钮的落点都搜得到(防假旋钮)", not 坏, 坏)
ck("旋钮数 ≥ 5(只有一个能拧就不叫调参)", len(K.旋钮表) >= 5)
ck("每个旋钮都写了人话说明", all(len(k.get("说明", "")) > 20 for k in K.旋钮表))

# ── ② 只许收窄 ──────────────────────────────────────────────────────
可用 = ["mcp__shop__get_order", "mcp__kb__fabric"]
try:
    K.校验({"工具": ["mcp__shop__get_order"]}, 可用); r = True
except Exception as e: r = False; print("   ", e)
ck("收窄到子集 → 放行", r)

try:
    K.校验({"工具": ["mcp__shop__get_order", "mcp__danger__rm"]}, 可用); r = False
except ValueError: r = True
ck("**放宽**到白名单外 → 当场抛(不是过滤掉)", r)

try:
    K.校验({"工具": []}, 可用); r = False
except ValueError: r = True
ck("收窄成空集 → 抛(一个工具都不给,它只能靠编)", r)

# ── ②b 短名 ↔ 全名(2026-09-25 真踩到的 bug)──────────────────────────
# 页面存短名、SDK 要全名。不统一的话:方案存下来能过,**一真跑就被判成
# 「放宽白名单」当场抛**,而报错读起来像是你配错了工具。
全名 = ["mcp__shop__get_order", "mcp__kb__fabric", "mcp__kb__lead_time"]
干净, _, _ = K.校验({"工具": ["get_order", "fabric"]}, 全名)
ck("给短名、白名单是全名 → 认得出(不误判成放宽)", 干净["工具"] == ["get_order", "fabric"], 干净)
干净2, _, _ = K.校验({"工具": ["mcp__shop__get_order"]}, 全名)
ck("**给全名也认得**,而且存进方案时统一成短名", 干净2["工具"] == ["get_order"], 干净2)
import json as _js, os as _os
_os.makedirs(K.目录, exist_ok=True)
_f = _os.path.join(K.目录, "_自测.json")
_js.dump({"号": "_自测", "旋钮": {"工具": ["get_order", "fabric"]}},
         open(_f, "w", encoding="utf-8"), ensure_ascii=False)
新, _ = K.应用({"effort": None, "max_turns": 12, "model_name": None, "guard": True},
              号="_自测", 可用工具=全名)
ck("传给 SDK 的**换回全名**(调用方不用自己记得换)",
   新["_工具收窄"] == ["mcp__shop__get_order", "mcp__kb__fabric"], 新.get("_工具收窄"))
_os.remove(_f)

# ── ③ 认不出的旋钮名不许静默吞掉 ────────────────────────────────────
try:
    K.校验({"temperature": 0.7}); r = False
except ValueError: r = True
ck("**拼错/不存在的旋钮名 → 抛**(静默退回默认 = 分数差归错因)", r)
# ⚠️ 这一条点名 temperature 是有意的:这条路径根本不传采样参数,
# 页面上如果冒出一个温度旋钮,它一定是假的 —— 在这里就该被拦下来。

# ── ④ 取值范围 ──────────────────────────────────────────────────────
for 坏值, 名 in [({"effort": "很深"}, "effort 认不出的档"),
                ({"max_turns": 0}, "max_turns 越界"),
                ({"max_turns": 999}, "max_turns 越界(大)"),
                ({"体检": "yes"}, "开关给了字符串")]:
    try: K.校验(坏值); r = False
    except (ValueError, TypeError): r = True
    ck(f"{名} → 抛", r)

# ── ⑤ 松标记 ────────────────────────────────────────────────────────
_, 松1, _ = K.校验({"effort": "high"})
_, 松2, _ = K.校验({"体检": False})
ck("收紧类旋钮不打松标记", not 松1)
ck("**关掉体检打上松标记**(可以试,不可以采纳)", 松2)

# ── ⑥ 和默认一样的不记 ──────────────────────────────────────────────
干净, _, _ = K.校验({"effort": "medium", "max_turns": 12})
ck("和默认一样的旋钮不落进方案(方案里只留真动过的)", 干净 == {}, 干净)

# ── ⑦ 应用时不许吃掉调用方的显式传参 ────────────────────────────────
参 = dict(effort="max", max_turns=3, model_name="X", guard=True)
新, 话 = K.应用(参, 号="")          # 没指定方案
ck("**没指定方案时原样返回**(不许拿旋钮表的默认去盖调用方传的值)", 新 == 参, 新)

# ── ⑧ sdk 里旋钮必须在 opts 构造之前生效 ────────────────────────────
src = open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
i旋 = src.find("_kn.应用(")
iopt = src.find("opts = ClaudeAgentOptions(")
ck("旋钮在 ClaudeAgentOptions 构造**之前**生效(之后套 = 假旋钮)",
   0 < i旋 < iopt, f"旋钮@{i旋} opts@{iopt}")
ck("工具白名单那行读的是收窄后的值", "_收窄 or _tools_for(kind)" in src)
ck("hook 那行接了注日期旋钮", "注日期=_注日期" in src)
ck("拧过的旋钮进记录仪(不记就归不了因)", "lanxiu.knobs" in src)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
sys.exit(1 if 挂 else 0)
