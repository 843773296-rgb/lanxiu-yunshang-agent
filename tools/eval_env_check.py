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
    ("残留的 PID 文件也当成在跑", "PID 文件:进程活着 → 在用;文件在但进程早没了(崩了留下的)→ 不算;没文件 → 不算"),
    ("夜跑拉起管理后台之后不关", "夜跑:开跑前先确保管理后台在,跑完把自己拉起来的关掉,报告顶上写明这一晚的状态"),
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
# 管理后台夜跑前拉起来(用户 10-20 拍「要」)—— 门禁里不真拉(CI 上没有它要的库,只会白等 60 秒),只核结构
跑 = 夜[夜.index("def _跑("):]                  # 10-20 起开跑之后的事在 _跑() 里(main 只管 PID 文件)
_位 = [跑.find(x) for x in ("确保管理后台()", "for 名, 参数 in 套们:", "关掉(后台进程)")]
ck("夜跑:开跑前先确保管理后台在,跑完把自己拉起来的关掉,报告顶上写明这一晚的状态",
   -1 not in _位 and _位 == sorted(_位) and "管理后台(全文检索 kb_rag 要用):{后台状态}" in 跑, _位)
ck("夜跑:拉起来的进程自成一组(收尾整组关,不留 Worker / uvicorn),launchd 里没有 USER 也能拼库地址",
   "start_new_session=True" in 夜 and 'env.setdefault("USER", getpass.getuser())' in 夜 and "os.killpg(进程.pid" in 夜)
# 「谁在用库」改用 PID 文件判(10-20):原来 pgrep -f 匹配整条命令行,查占用的诊断命令自己就触发了闸
import tempfile as _tf
_d = _tf.mkdtemp(prefix="pid-")
活, 残, 无 = (os.path.join(_d, x) for x in ("活", "残", "无"))
open(活, "w").write(f"{os.getpid()}\n"); open(残, "w").write("999999\n")
ck("PID 文件:进程活着 → 在用;文件在但进程早没了(崩了留下的)→ 不算;没文件 → 不算",
   ne.活着(活) is True and ne.活着(残) is False and ne.活着(无) is False)
_用 = 夜[夜.index("def 有人在用():"):夜.index("def 清单(")]
ck("有人在用():不再按名字搜 bite_run;门禁只认真正以「bash ./check.sh」开头的进程",
   '"pgrep", "-f", "bite_run"' not in _用 and "活着(重放PID)" in _用 and "^(/bin/)?(ba)?sh" in _用)
ck("PID 文件放在真库所在的目录(两个检出共用;.feynman 各有一份,放那里互相看不见)",
   'PID目录 = os.path.dirname(os.path.realpath(os.path.join(ROOT, "backend", "lanxiu.db")))' in 夜)
_主 = 夜[夜.index("def main():"):夜.index("def _跑(")]
ck("夜跑开跑写自己的 PID 文件,结束(含崩溃)在 finally 里删", "open(夜跑PID, \"w\")" in _主 and "finally:" in _主
   and "os.remove(夜跑PID)" in _主)
api = open(os.path.join(ROOT, "backend", "api.py"), encoding="utf-8").read()
ck("kb_rag 那头用的也是 AIMC_BASE(两边地址不许各写一份)", '_后台基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")' in api)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 环境没验成和模型答错分得开(验了 {n} 条){D}")
