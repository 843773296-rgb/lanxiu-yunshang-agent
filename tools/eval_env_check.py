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
# ⚠️ 2026-10-20 加「退步」时这条当场红了 —— **它写死了那两个元组的字面量,
#    而那正是它该干的事**:那两处必须同时改(漏一处,退步的那套要么不算跑完、
#    要么躲过「掉登录改判成没跑成」)。
_组 = '("过", "判红", "退步", "部分没验成(环境)")'
ck("夜跑:这一类也算「全跑完了」,认证失败照样能覆盖它(两处元组必须一致)",
   f'全跑完 = all(r["结果"] in {_组}' in 夜 and f'r["结果"] in {_组}:' in 夜)

# ── 「判定:X」那一行(2026-10-20)——「结果」原来一个字混了四种状态 ────────────
ck("夜跑:读得出 rounds 打的那行判定,四种各认得",
   all(ne.判定(f"  判定:{x}") == x for x in ("退步", "持平", "进步", "没结论")))
ck("夜跑:打不出那一行就说「没打」(不走共用入口的 5 套就是这样,**诚实的降级**)",
   ne.判定("什么都没有") == "没打" and ne.判定("") == "没打")
ck("夜跑:**判定退步而退出码 0 → 报退步,不报过**(十套评测从不以非零退出,"
   "退步原来被报成「过」)",
   ne.归类(0, "  判定:退步") == "退步" and ne.归类(1, "  判定:退步") == "退步")
ck("夜跑:**持平而退出码非 0 照旧算判红** —— 把它摘出来是放宽,"
   "而点名式的名单还没建,先摘就只要了放宽那一半",
   ne.归类(1, "  判定:持平") == "判红" and ne.归类(0, "  判定:持平") == "过")
ck("夜跑:环境和认证失败的优先级在判定行之上(它们说明这一轮压根没测成)",
   ne.归类(75, "  判定:退步") == "部分没验成(环境)"
   and ne.归类(0, "Failed to authenticate\n  判定:退步") == "没跑成(认证失败)")

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
# 夜跑结果自动提交(用户 10-20 拍)—— 评测结果 + 报告 + **压缩过的**运行日志;原样的日志不进;失败不抛
import gzip, shutil, subprocess, tempfile
with tempfile.TemporaryDirectory(prefix="nightly-chk-") as 假根:
    夜目录 = os.path.join(假根, "agent", "nightly"); os.makedirs(夜目录)
    日志 = ('{"t":"turn"}\n' * 2000).encode()
    for 名, 内容 in (("agent__x-eval-results.jsonl", b"{}\n"), ("agentsite__evals__funnel.jsonl", 日志),
                     ("agentsite__evals__withheld.jsonl", 日志), ("别的东西.jsonl", b"{}\n")):
        open(os.path.join(夜目录, 名), "wb").write(内容)
    单 = ne.入库清单(假根)
    压 = os.path.join(夜目录, "agentsite__evals__funnel.jsonl.gz")
    第一次 = open(压, "rb").read() if os.path.exists(压) else b""
    ne.入库清单(假根)
    ck("夜跑入库清单:评测结果 + 压缩过的运行日志;原样的日志、扣下的答案原文(withheld)、别的文件都不进",
       单 == ["agent/nightly/agent__x-eval-results.jsonl", "agent/nightly/agentsite__evals__funnel.jsonl.gz"], 单)
    ck("压缩包解开和原日志一字不差,而且比原文件小", 第一次 and gzip.decompress(第一次) == 日志 and len(第一次) < len(日志) // 5)
    # 看包头,不比两次输出:两次压缩落在同一秒里时,带着时间戳也会一样 —— 那样判据量不到它要守的东西
    ck("压缩包头不记时间戳、不记文件名(内容没变就是同一串字节 —— 不然每晚白多一次改动)",
       第一次[3:8] == b"\0\0\0\0\0" and open(压, "rb").read() == 第一次, 第一次[:10])
_提 = 夜[夜.index("def 提交夜跑结果("):夜.index("def 归类(")]
ck("夜跑:跑完自动提交 —— 文件只从入库清单来,扫过密钥才提交,只提交这几个文件(--only),出错不抛",
   "入库清单(ROOT)" in _提 and _提.index("scan_secrets.sh") < _提.index('"commit", "--only"') and "except Exception" in _提)
ck("夜跑:试跑(--试)不提交", 'if not 试:\n        说(f"结果入库:{提交夜跑结果(报)}")' in 夜)
# 在一个临时空仓库里放真的 .gitignore 问 git —— 咬合副本里没有 .git,直接在 ROOT 问会崩
_忽仓 = tempfile.mkdtemp(prefix="ignore-chk-")
subprocess.run(["git", "init", "-q"], cwd=_忽仓)
shutil.copy(os.path.join(ROOT, ".gitignore"), _忽仓)
def _忽略(路径):
    return subprocess.run(["git", "check-ignore", "-q", "--no-index", 路径], cwd=_忽仓).returncode == 0
ck("忽略列表:原样的运行日志副本(单份 24 MB 还在长)被忽略,压缩包不被忽略",
   _忽略("agent/nightly/agentsite__evals__funnel.jsonl") and not _忽略("agent/nightly/agentsite__evals__funnel.jsonl.gz"))
ck("忽略列表:扣下的答案原文(withheld)原样、压缩包都被忽略 —— 进不了公开仓库",
   _忽略("agent/nightly/agentsite__evals__withheld.jsonl") and _忽略("agent/nightly/agentsite__evals__withheld.jsonl.gz"))
shutil.rmtree(_忽仓, ignore_errors=True)
api = open(os.path.join(ROOT, "backend", "api.py"), encoding="utf-8").read()
ck("kb_rag 那头用的也是 AIMC_BASE(两边地址不许各写一份)", '_后台基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")' in api)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 环境没验成和模型答错分得开(验了 {n} 条){D}")
