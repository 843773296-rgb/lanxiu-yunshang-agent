#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改动影响面 —— **动手之前问一句「这一改会破坏什么」。**

## 为什么是这个形状,而不是一份 plan.md 模板

读 Anthropic 那篇《AI-Native SDLC Playbook》时,Build 阶段的核心动作是
「先进 Plan Mode,列出准备改哪些文件、可能影响什么、要跑哪些测试,
**工程师接受之前不许改代码**」。

这个项目照抄一份 `plan.md` 模板是没用的 —— 它会变成第三份漂着的文档。
**真正有价值的是那一问:「这一改会破坏什么?」** 而它可以机械回答。

## 证据:2026-09-15 一天翻车四次,每一次这一问都能挡住

    把 seed 的真值标注改成调口径模块   → 破坏了**故意的双实现**,跑红三条检查。
                                       那段注释明写着「独立解析出来的另一套」,**我没读**
    咬合测试把 239 个技能删了          → 源和目标变成同一个路径,rmtree 删的是真目录
    给评测题补了个工具查不了的单号     → 造出一道无解的题
    把判据从 162 改成 152              → **往危险的那一侧放宽**:让判分器开始接受报短的工期

四次的共同点:**我改的时候只看这句话读着顺不顺,没看它连着什么。**

## 它报三样

**① 你这次碰到的「⚠️ 警示段落」。** 这个项目里有 21 处写着
「不许 / 别在这儿 / 故意 / 不要」的段落 —— 它们是前人(或前几个小时的我)
用一次事故换来的。**改到它附近而没读它,是这些事故复发的主要方式。**

**② 覆盖这些文件的检查有哪几条。** 改完至少要跑它们
(`check.sh` 会全跑,但**知道哪几条该红**和「全绿就完事」是两回事)。

**③ 这次改动有没有删东西。** 删除是不可逆的那一类,单独拎出来。

用法:

    python3 tools/impact.py           # 看工作区还没提交的改动
    python3 tools/impact.py HEAD~3    # 看最近三次提交动了什么
"""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
警示 = re.compile(r"⚠️?.{0,40}(不许|别在|别去|故意|不要|千万|永远不)")

# ⚠️ 这份记录我第一次写错过:右边那句写的是「这次碰到的警示段落」,
# 而脚本里那句是「**这次碰到 {n} 处警示段落**」——**差在那个占位符上**,
# `bite_check` 当场抓住(它要求「预期红的那一条」真的在脚本里出现过)。
# **一份写错了的咬合记录,和没有记录一样没用** —— 它指的那句话不存在。
咬合 = [
    ("把找警示段落的正则改窄(只留「千万」)",
     "找得到的警示段落"),
    ("把某个文件里的 ⚠️ 警示行删掉,再改它附近",
     "处警示段落 —— 改之前先把它们读一遍"),
]


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                          text=True).stdout


def 改动(base=None):
    """返回 {文件: [(起, 止), …]} —— 改动落在哪些行区间。"""
    args = ["diff", "-U0"] + ([base] if base else [])
    out, cur, res = _git(*args), None, {}
    for line in out.split("\n"):
        if line.startswith("+++ b/"):
            cur = line[6:]; res.setdefault(cur, [])
        elif line.startswith("@@") and cur:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                a = int(m.group(1)); n = int(m.group(2) or 1)
                res[cur].append((a, a + max(n, 1) - 1))
    return {k: v for k, v in res.items() if k.endswith((".py", ".md", ".sh"))}


def 覆盖(path):
    """check.sh 里哪几条检查跑到了这个文件。

    分三档,**因为「没直接点名」和「没人管」是两件事**:

      直接   check.sh 那一行里就写着这个文件
      间接   有检查 import 它(顺着 import 找一层)
      全局   `backend/seed.py` 这种 —— 没有任何一条直接点名,
             **而所有检查都跑在它生成的库上**

    ⚠️ 第一版只认「直接点名」,于是给 `seed.py` 打出
    「**覆盖它的检查:一条都没有 —— 改坏了不会有任何地方报**」——
    **吓人且不准**。那正是今天反复说的那种错:
    **一个判据只看它看得见的那一维,然后把「我没看到」说成「没有」。**
    """
    sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    base = os.path.basename(path)
    直接, 间接 = [], []
    脚本 = []
    for line in sh.split("\n"):
        if not line.startswith("run "): continue
        m = re.search(r'run "([^"]+)"', line)
        名 = m.group(1) if m else line[:40]
        if path in line or base in line: 直接.append(名); continue
        脚本 += [(名, x) for x in re.findall(r"([\w/]+\.py)", line)]
    # 顺着 import 找一层
    mod = base[:-3] if base.endswith(".py") else None
    if mod:
        for 名, sp in 脚本:
            f = os.path.join(ROOT, sp)
            if not os.path.isfile(f): continue
            try: t = open(f, encoding="utf-8").read()
            except Exception: continue
            if re.search(rf"\bimport +{re.escape(mod)}\b|\bfrom +{re.escape(mod)} +import", t):
                间接.append(名)
    if 直接 or 间接:
        return [f"{x}(直接)" for x in 直接] + [f"{x}(间接)" for x in dict.fromkeys(间接)]
    # 数据生成器:没人点名,但所有检查都跑在它生成的库上
    if base in ("seed.py",) or path.startswith("knowledge/derive_"):
        return ["**全员** —— 它生成的是所有检查跑的那个库,改坏了哪一条先红说不准"]
    return []


def 自检():
    """**这个工具自己会不会变瞎。**

    它靠一个正则去找「⚠️ + 不许/别在/故意」的警示段落。
    而正则会因为措辞变化而漏 —— **漏的那天它照样输出一份干净的报告**,
    而那正是它该报警的时候。

    所以钉一个下限:全库里找得到的警示段落不许少于这个数。
    (和来源欠账、咬合欠账一样:**钉住,只许涨不许掉**。)
    """
    import glob
    n = 0
    for p in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
        if ".venv" in p or "/.claude/" in p: continue
        try: t = open(p, encoding="utf-8").read()
        except Exception: continue
        n += sum(1 for line in t.split("\n") if 警示.search(line))
    return n


# 全库警示段落的**下限** —— 2026-09-15 扫出来 21 处。
# 少于这个数,多半是正则漏了(措辞变了),不是警示真的被删了 ——
# **而漏的那天它照样输出一份干净的报告。**
警示下限 = 21


def main():
    if "--selftest" in sys.argv:
        n = 自检()
        ok = n >= 警示下限
        print(f"  {'✅' if ok else '❌'} 找得到的警示段落 {n} 处(下限 {警示下限})")
        if not ok:
            print("     **正则多半漏了** —— 措辞一变它就找不着,")
            print("     而漏的那天它照样输出一份干净的报告,那正是该报警的时候。")
            return 1
        print("     **钉住下限,只许涨不许掉** —— 和来源欠账、咬合欠账同一个办法")
        return 0
    base = sys.argv[1] if len(sys.argv) > 1 else None
    ch = 改动(base)
    print("改动影响面 —— **动手之前问一句「这一改会破坏什么」**")
    print("=" * 88)
    if not ch:
        print("  工作区没有改动。(看历史:python3 tools/impact.py HEAD~3)")
        return 0

    print(f"\n【碰到的文件】{len(ch)} 个\n")
    警 = 删 = 0
    for f, spans in sorted(ch.items()):
        p = os.path.join(ROOT, f)
        cov = 覆盖(f)
        print(f"  {f}")
        print(f"      覆盖它的检查:"
              f"{('、'.join(cov[:3]) + ('…' if len(cov) > 3 else '')) if cov else '**一条都没有** —— 改坏了不会有任何地方报'}")
        if not os.path.isfile(p): 
            print("      **这个文件没了(删除?)** —— 删除是不可逆的那一类"); 删 += 1; continue
        lines = open(p, encoding="utf-8").read().split("\n")
        # 改动行附近 12 行内的警示段落
        碰 = []
        for a, b in spans:
            for i in range(max(0, a - 12), min(len(lines), b + 12)):
                if 警示.search(lines[i]) and lines[i] not in 碰:
                    碰.append(lines[i])
        if 碰:
            警 += len(碰)
            print(f"      ⚠️ **这次碰到 {len(碰)} 处警示段落 —— 改之前先把它们读一遍**:")
            for x in 碰[:4]:
                print(f"         {x.strip()[:84]}")

    d = _git("diff", "--numstat", *( [base] if base else [] ))
    删行 = sum(int(x.split("\t")[1]) for x in d.strip().split("\n")
               if x and x.split("\t")[1].isdigit())
    print(f"\n【删掉的行】{删行} 行")
    if 删行 > 200:
        print("      ⚠️ **删得不少。** 删除是不可逆的那一类 —— "
              "确认每一段都是有意删的,不是顺手清掉的")

    print("\n" + "=" * 88)
    print(f"  碰到 {警} 处警示段落。**它们是前人用一次事故换来的** ——")
    print("  这个项目 2026-09-15 一天翻车四次,每一次「这一改会破坏什么」都能挡住,")
    print("  而四次的共同点是:**只看了这句话读着顺不顺,没看它连着什么。**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
