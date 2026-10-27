#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测来路章上写的,和这一轮真正用的必须是同一个 —— **供应商**和**库**两样。

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

# ===== 第二样:章上的库,必须是**这一轮真正在读的那个库** =====
# 和上面那一节同形:章上写的和真实用的不是同一个,而**两者在结果文件里长得一模一样**。
# 这里开的是**真 sqlite 库**(临时目录),所以顺带验到了一件手写用例验不到的事:
# `build_logic_n` 从库里读回来是**字符串**(`db_build` 写 str(n),world_meta.v 是 TEXT 列)。
import sqlite3, tempfile

def _造库(fp):
    p = os.path.join(tempfile.mkdtemp(), "lanxiu.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE world_meta(k TEXT PRIMARY KEY, v TEXT)")
    c.executemany("INSERT INTO world_meta(k, v) VALUES(?, ?)",
                  [("build_commit", "c-" + fp), ("build_at", "2026-10-27T00:00:00"),
                   ("build_logic_fp", fp), ("build_logic_n", "12")])   # str,和真库一样
    c.commit(); c.close()
    return p

def _章上的fp():
    evalrec._库章缓存.clear()        # 缓存按库路径存,清掉是为了让这几步各读一次
    return (evalrec._库章() or {}).get("build_logic_fp")

甲, 乙 = _造库("FPJIA"), _造库("FPYI")
import api as _api
_原DB, _原env = _api.DB, os.environ.get("LANXIU_DB")
库案 = []
try:
    os.environ["LANXIU_DB"] = 甲
    库案.append(("LANXIU_DB 指甲库 → 章上是甲", _章上的fp(), "FPJIA"))

    os.environ["LANXIU_DB"] = 乙
    库案.append(("同进程换成乙库 → 章跟着变(缓存按库路径分开,不许串)", _章上的fp(), "FPYI"))

    # **顺序这一条是重点**:真评测切库走 env(agent/triage_sets.py),
    # 而改 api.DB 的是门禁判据(它们不盖章)。api.DB 的初值就是默认路径,
    # 所以「改过」和「没改过」在值上分不出 —— 拿它去压一个显式的环境变量,
    # 结果就是真正切了库的那条路被盖上默认库的指纹。
    _api.DB = 甲
    os.environ["LANXIU_DB"] = 乙
    库案.append(("env 指乙 + api.DB 指甲 → 章上是乙(显式的那条赢)", _章上的fp(), "FPYI"))

    os.environ.pop("LANXIU_DB", None)
    _api.DB = 甲
    库案.append(("没设 env → 退回 api.DB(指甲)", _章上的fp(), "FPJIA"))
finally:
    _api.DB = _原DB
    os.environ.pop("LANXIU_DB", None)
    if _原env is not None:
        os.environ["LANXIU_DB"] = _原env
    evalrec._库章缓存.clear()

for 名, 得, 应 in 库案:
    n += 1
    ok = 得 == 应
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}:章上={得} · 应为={应}")
    if not ok:
        bad.append(名)

if n == 0:
    print(f"{R}❌ 一种情形都没验{D}"); sys.exit(1)
if bad:
    print(f"{R}❌ {len(bad)} 种情形下章和实际发请求的不是同一家 —— 结果文件上的来路是假的{D}")
    sys.exit(1)
print(f"{G}✅ 来路章对得上真实:供应商 = 两处发请求的那家,库 = 这一轮真正在读的那个"
      f"(共验了 {n} 种情形,库那几条开的是真 sqlite){D}")
