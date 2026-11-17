#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地快门(执行手册 W33 ②,2026-11-17):只跑**覆盖到这次改动**的那几条检查。

    python3 tools/quick_gate.py            # 看工作区改了什么 → 用 tools/impact.py 算覆盖它们的检查 → 只跑那几条
    python3 tools/quick_gate.py --只列      # 只列不跑
    python3 tools/quick_gate.py --自测      # 验「文件 → 检查 → 命令」这条映射本身

它是什么、不是什么:
  · 是写代码时的**快门**:改一个文件,十几秒知道「直接盯着它的那几条」红没红,不用等 434 条跑完
  · **不是门禁**:推之前仍然要 `./tools/ship.sh`(全量跑在 rebase 之后,CLAUDE.md 第 5 节 1.5)。
    快门只跑「直接点名 / import 到 / 读到」三档能算出来的;`backend/seed.py` 这类「所有检查都跑在它建的库上」的改动,
    快门算不出覆盖面,会明说「这几个文件快门看不出来,只能全量」。**没算出来的不等于没影响**
  · 和 `check.sh --跑一条` 的区别:那个只负责跑一条、退出码永远 0;这里自己记每条的退出码、红了退 1

覆盖面怎么算在 tools/impact.py(直接 / 间接 / 读它 / 全局),这里不重写一份。
"""
import os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
不算改动 = {".feynman/tool-eval.json", "agentsite/evals/funnel.jsonl", "agentsite/evals/skill_usage.jsonl"}   # 运行时一直写的三件,谁都不 add
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def 改了哪些():
    def sh(cmd):
        return [l for l in subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout.split("\n") if l.strip()]
    出 = set(sh(["git", "-c", "core.quotepath=false", "diff", "--name-only", "HEAD"]))
    出 |= set(sh(["git", "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard"]))
    return sorted(x for x in 出 - 不算改动 if os.path.exists(os.path.join(ROOT, x)))


def 门禁行们(check_sh):
    """check.sh 里每条单行 run → (标题, 命令)。多行的 bash -c 块不收(快门跑不了半截)。"""
    出 = []
    for line in check_sh.split("\n"):
        m = re.match(r'^run "([^"]+)"\s+(.+?)\s*$', line)
        if m and "bash -c" not in m.group(2):
            出.append((m.group(1), m.group(2)))
    return 出


def 该跑哪些(文件们, 门禁行, 覆盖=None):
    """→ ([(标题, 命令, 因为哪些文件)], 快门看不出来的文件)。纯函数:覆盖() 可注入,自测喂假的。"""
    import impact
    覆盖 = 覆盖 or impact.覆盖
    按标题 = {t: c for t, c in 门禁行}
    选 = {}
    看不出 = []
    for f in 文件们:
        # 文件自己就是一条检查(xxx_check.py / xxx_test.py 在 check.sh 里)→ 直接跑它
        自己 = [(t, c) for t, c in 门禁行 if f in c.split()]
        命中 = list(自己)
        for x in 覆盖(f) or []:
            名 = re.sub(r"\((直接|间接|读它)\)$", "", x)
            if 名 in 按标题 and (名, 按标题[名]) not in 命中:
                命中.append((名, 按标题[名]))
        if not 命中:
            看不出.append(f); continue
        for t, c in 命中:
            选.setdefault((t, c), []).append(f)
    return [(t, c, fs) for (t, c), fs in 选.items()], 看不出


def 自测():
    bad = []
    假门禁 = 'run "甲检查" python3 tools/a_check.py\nrun "乙检查" python3 backend/b_check.py --x\nrun "丙多行" bash -c \'\n  echo 1\'\n'
    行 = 门禁行们(假门禁)
    if [t for t, _ in 行] != ["甲检查", "乙检查"]:
        bad.append(f"自测:单行 run 要全收、bash -c 多行块不收,实际 {[t for t, _ in 行]}")
    假覆盖 = {"backend/x.py": ["乙检查(间接)", "没这条(直接)"], "tools/a_check.py": [], "backend/seed.py": []}.get
    跑, 看不出 = 该跑哪些(["backend/x.py", "tools/a_check.py", "backend/seed.py"], 行, 覆盖=假覆盖)
    标题 = sorted(t for t, _, _ in 跑)
    if 标题 != ["乙检查", "甲检查"]:
        bad.append(f"自测:x.py 该映到乙检查、a_check.py 自己就是甲检查,实际 {标题}")
    if 看不出 != ["backend/seed.py"]:
        bad.append(f"自测:算不出覆盖面的文件要单列(seed.py),实际 {看不出}")
    if any("没这条" in t for t, _, _ in 跑):
        bad.append("自测:覆盖里报了门禁里没有的标题,不该跑它")
    return bad


def main():
    a = sys.argv[1:]
    if "--自测" in a:
        bad = 自测()
        for b in bad: print(f"  {R}❌ {b}{D}")
        print(f"{G}✅ 快门映射自测过{D}" if not bad else f"{R}❌ 快门自测 {len(bad)} 条没过{D}")
        return 1 if bad else 0
    文件 = 改了哪些()
    print(f"本地快门 · 工作区改了 {len(文件)} 个文件" + ("" if 文件 else " —— 没改动,没东西可跑"))
    if not 文件:
        return 0
    门禁 = 门禁行们(open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read())
    跑, 看不出 = 该跑哪些(文件, 门禁)
    for f in 看不出:
        print(f"  {Y}⚠ {f}:快门算不出哪些检查覆盖它(没被直接点名 / import / 读到)—— 这个只能全量{D}")
    print(f"  覆盖到的检查 {len(跑)} 条" + (" —— 只列不跑" if "--只列" in a else ""))
    if "--只列" in a:
        for t, c, fs in 跑: print(f"   · {t}  ← {', '.join(fs)}")
        return 0
    红 = []
    t0 = time.monotonic()
    for t, c, fs in 跑:
        s = time.monotonic()
        try:
            r = subprocess.run(c, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=900)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = 124
        标 = f"{G}✅{D}" if rc == 0 else f"{R}❌ rc={rc}{D}"
        print(f"  {标} {t}  ({time.monotonic() - s:.1f}s ← {', '.join(fs)})")
        if rc != 0:
            红.append((t, c, (r.stdout if rc != 124 else "超时")[-1500:]))
    print(f"\n  共 {len(跑)} 条 · 红 {len(红)} 条 · {time.monotonic() - t0:.0f} 秒;**这是快门,推前仍要 ./tools/ship.sh 全量**")
    for t, c, out in 红:
        print(f"\n{R}── {t} ──{D}\n  $ {c}\n" + "\n".join("  " + l for l in out.strip().split("\n")[-12:]))
    return 1 if 红 else 0


if __name__ == "__main__":
    sys.exit(main())
