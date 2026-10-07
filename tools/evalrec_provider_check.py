#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测来路章上的「供应商」,和真正发请求的那两处必须说同一家。

⚠️ 2026-10-07 栽的:`v1.provider()` 和 `agentsite/sdk.py` 09-22 都改成了「没设开关默认 Claude」,
`agent/evalrec.py::供应商()` 没跟着改,还是「找得到 DeepSeek 凭证就记 deepseek」——
本机有 ~/.deepseek-key,于是所有没设开关的评测**实际跑 claude-haiku-4-5,章上写 deepseek-v4-pro**,
每套都打印「供应商不同,不拿它当基线」。同一条判据抄在三处,一处改了另两处不会知道。

做法:几种环境设置下,三处各问一遍,必须一致。**不碰钥匙串、不发请求** ——
Claude 那支塞一个假 ANTHROPIC_API_KEY 让 v1 走环境变量分支;DeepSeek 那支塞假 DEEPSEEK_API_KEY。
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "agent"), os.path.join(ROOT, "agentsite")]
import evalrec, v1, sdk

# 放在 tools/ 不放 agent/:它**不调模型**(只问三处「会选哪家」,不发请求),
# 而 agent/ 下的文件出现 `provider(` 就会被评测轮次检查当成「只跑一轮的模型评测」。
咬合 = [
    ("把 evalrec.供应商() 退回「找得到 DEEPSEEK_API_KEY 就记 deepseek」",
     "没设开关"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
假 = "x" * 40
情形 = [("没设开关", None), ("LANXIU_PROVIDER=claude", "claude"),
        ("LANXIU_PROVIDER=CLAUDE(大写)", "CLAUDE"), ("LANXIU_PROVIDER=deepseek", "deepseek")]
保 = dict(os.environ)
bad, n = [], 0
for 名, 值 in 情形:
    os.environ.clear(); os.environ.update(保)
    for k in ("LANXIU_PROVIDER", "ANTHROPIC_BASE_URL"):
        os.environ.pop(k, None)
    if 值 is not None:
        os.environ["LANXIU_PROVIDER"] = 值
    os.environ["DEEPSEEK_API_KEY"] = 假
    os.environ["ANTHROPIC_API_KEY"] = 假
    章 = evalrec.供应商()
    发 = "deepseek" if v1.provider()["id"] == "deepseek" else "claude"
    os.environ["ANTHROPIC_API_KEY"] = 假
    sdk._env()
    三 = "deepseek" if "deepseek" in os.environ.get("ANTHROPIC_BASE_URL", "") else "claude"
    n += 1
    ok = 章 == 发 == 三
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}:章={章} · v1 发={发} · sdk 发={三}")
    if not ok:
        bad.append(名)
os.environ.clear(); os.environ.update(保)

if n == 0:
    print(f"{R}❌ 一种情形都没验{D}"); sys.exit(1)
if bad:
    print(f"{R}❌ {len(bad)} 种情形下章和实际发请求的不是同一家 —— 结果文件上的来路是假的{D}")
    sys.exit(1)
print(f"{G}✅ 来路章和两处发请求的判据一致(验了 {n} 种开关设置){D}")
