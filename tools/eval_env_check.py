#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测里「环境没验成」和「模型答错」分开记(2026-10-20 夜跑逮到)。

那晚管理后台(8801)没起,全文检索 kb_rag 查不了;T07 两轮模型都照规矩说「知识库现在查不了」,
却被判成答错,和真答错的题一起标「判红」—— **一个环境问题和一个模型问题,在「判红」上长得一模一样**。
要守的:
  · 夜跑的 `归类()`:退出码 75 → 「部分没验成(环境)」,1 → 判红,0 → 过;有认证失败 → 没跑成;
  · tool_eval:管理后台不在、而且用到了 kb_rag 又没过的题,才记成「环境没验成」—— 后台在的时候答错照样算挂;
  · tool_eval 的退出码:只有环境没验成的没过 → 75;有任何真挂 → 1。
"""
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("夜跑把 75 也算成判红", "夜跑:退出码 75 → 部分没验成(环境),和判红分开"),
    ("管理后台在也把 kb_rag 的题记成环境", "tool_eval:只有管理后台不在、又用到 kb_rag 的题才记成环境没验成"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


print("评测:环境没验成 ≠ 模型答错")
print("=" * 80)
_s = importlib.util.spec_from_file_location("ne", os.path.join(ROOT, "tools", "nightly_eval.py"))
ne = importlib.util.module_from_spec(_s); _s.loader.exec_module(ne)
ck("夜跑:退出码 75 → 部分没验成(环境),和判红分开",
   ne.归类(75, "") == "部分没验成(环境)" and ne.归类(1, "") == "判红" and ne.归类(0, "") == "过", ne.归类(75, ""))
ck("夜跑:输出里有认证失败,退出码是几都算没跑成",
   ne.归类(0, "API Error: 403 Failed to authenticate") == "没跑成(认证失败)"
   and ne.归类(75, "Failed to authenticate") == "没跑成(认证失败)")
夜 = open(os.path.join(ROOT, "tools", "nightly_eval.py"), encoding="utf-8").read()
ck("夜跑:这一类也算「全跑完了」,认证失败照样能覆盖它",
   '全跑完 = all(r["结果"] in ("过", "判红", "部分没验成(环境)")' in 夜
   and 'r["结果"] in ("过", "判红", "部分没验成(环境)"):' in 夜)

工 = open(os.path.join(ROOT, "agent", "tool_eval.py"), encoding="utf-8").read()
ck("tool_eval:只有管理后台不在、又用到 kb_rag 的题才记成环境没验成",
   re.search(r'环境 = \(not ok\) and \(not 后台在\) and any\(n\.endswith\("kb_rag"\) for n in names\)', 工) is not None)
ck("tool_eval:开跑前真问一次管理后台,地址和 kb_rag 用的是同一个环境变量",
   '"AIMC_BASE", "http://127.0.0.1:8801"' in 工 and '后台在 = _sp.run(["curl"' in 工)
ck("tool_eval:只有环境没验成的没过 → 75;有真挂 → 1", "sys.exit(0 if ok_n == len(todo) else (75 if ok_n + 环境_n == len(todo) else 1))" in 工)
api = open(os.path.join(ROOT, "backend", "api.py"), encoding="utf-8").read()
ck("kb_rag 那头用的也是 AIMC_BASE(两边地址不许各写一份)", '_后台基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")' in api)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 环境没验成和模型答错分得开(验了 {n} 条){D}")
