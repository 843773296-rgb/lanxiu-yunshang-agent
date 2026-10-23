#!/usr/bin/env python3
"""把仓库里写死的 `mcp__kb|task|shop__工具` 换成按领域的新全名(intent/mcp-domains.md)。

    python3 tools/mcp_rename.py          只报会改哪些文件、各几处(不写)
    python3 tools/mcp_rename.py --做     真改

**历史不改写**:评测结果(*.jsonl)、夜跑存档、记录仪、项目日志、跑过的轨迹快照 ——
那是「当时调的是哪个」,改了就查不回来。读历史时过一下 `domains.新名()` 就能对上。
认不出的工具名**不动、报出来**(不在这里猜它该归哪)。
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import domains

旧 = re.compile(r"mcp__(kb|task|shop)__([A-Za-z_][A-Za-z0-9_]*)")
后缀 = (".py", ".mjs", ".js", ".json", ".md", ".html", ".sh", ".txt")
不碰目录 = (".git", ".venv", "node_modules", "__pycache__", "agent/nightly", "agentsite/evals/runs",
            ".feynman", "agent/onetime-deepseek-20260915", "backend/static", "backend/uploads")
不碰文件 = ("澜绣云裳agent-项目日志.md", "intent/mcp-domains.md", "HANDOFF.md")


def 扫():
    改, 认不出 = {}, {}
    for d, ds, fs in os.walk(ROOT):
        rel = os.path.relpath(d, ROOT)
        if any(rel == x or rel.startswith(x + os.sep) for x in 不碰目录):
            ds[:] = []; continue
        for f in fs:
            p = os.path.join(d, f); r = os.path.relpath(p, ROOT)
            if not f.endswith(后缀) or f.endswith(".jsonl") or r in 不碰文件:
                continue
            try:
                s = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            n = 0
            def 换(m):
                nonlocal n
                短 = m.group(2)
                if 短 not in domains.归属:
                    认不出.setdefault(r, set()).add(m.group(0)); return m.group(0)
                n += 1
                return domains.全名(短)
            t = 旧.sub(换, s)
            if n:
                改[r] = (n, t)
    return 改, 认不出


if __name__ == "__main__":
    改, 认不出 = 扫()
    for r, (n, _) in sorted(改.items(), key=lambda x: -x[1][0]):
        print(f"  {n:4d}  {r}")
    print(f"\n共 {sum(n for n, _ in 改.values())} 处 / {len(改)} 个文件")
    if 认不出:
        print("\n⚠️ 认不出的(没动):")
        for r, xs in sorted(认不出.items()):
            print(f"  {r}: {sorted(xs)[:5]}")
    if "--做" in sys.argv:
        for r, (_, t) in 改.items():
            open(os.path.join(ROOT, r), "w", encoding="utf-8").write(t)
        print("✅ 改完了")
