#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""咬合执行器 —— 把「我测过了」变成一条**下次还能再跑一遍**的规格。

## 为什么要有这个

`tools/bite_check.py` 已经要求每个检查脚本写一份 `咬合 = [...]` 记录:
左边「改坏了什么」,右边「预期红的是哪一条」。但那是**散文** ——
散文不会在回归的时候自己变红。记录写完那一刻是真的,半年后代码改了,
它还是那句话,而**「仍然成立的记录」和「已经失效的记录」长得一模一样**。

这个脚本把同一件事写成可执行的规格(`tools/bite_specs.json`),随时能重放。

## 一条咬合必须过三关,少一关就不算

1. **对照要绿**:不动任何东西,脚本跑出来是通过的。
   ⚠️ 这一关最容易省,而省掉它就会出现这个项目栽过的那种事 ——
   **攻击自己跑不起来,于是任何异常都被读成「被拦下」**。
   本来就红的脚本,改坏之后还是红的,证明不了任何事。
2. **改坏之后要红**:退出码非 0。
3. **红的是那一条**:输出里带 ❌ 的那些行中,有一行含着规格写的「预期红」。
   只看退出码不够 —— 一个脚本可能因为**完全不相干的另一条**红了,
   而「我的攻击被抓到了」和「它为别的事红了」同样长得一模一样。

## 在副本里做,不碰主工作区

常有并行会话在同一个仓库上干活。在原地改坏再改回来,中间那一瞬别人可能正好读到、
甚至提交。所以每次都在 `$TMPDIR` 下的副本里做。
⚠️ 副本必须带上库(`backend/lanxiu.db`,gitignored),否则脚本读不到数据 ——
而「读不到数据」和「数据有问题」在报告里也长得一样。

## 用法

    python3 tools/bite_run.py                 # 跑全部规格
    python3 tools/bite_run.py --only role_check    # 只跑名字里带这个的
    python3 tools/bite_run.py --list          # 只列不跑
"""
import argparse, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPECS = os.path.join(HERE, "bite_specs.json")

# 副本里**不**带的东西。
# ⚠️ 这里原来是白名单(列出要拷哪些),2026-09-17 改成黑名单。
# 起因:白名单漏了根目录的 `.mcp.json`,于是 `boundary_audit` 在副本里对照就是红的 ——
# 而「副本漏了文件」和「代码真的坏了」在报告里长得一模一样。
# **白名单会静默漏掉新加的文件,黑名单不会。**
不带 = {".git", ".venv", "__pycache__", ".pytest_cache", ".DS_Store", "node_modules"}


def 建副本(dst):
    if os.path.isdir(dst): shutil.rmtree(dst)
    os.makedirs(dst)
    for name in sorted(os.listdir(ROOT)):
        if name in 不带: continue
        src = os.path.join(ROOT, name)
        d = os.path.join(dst, name)
        if os.path.isdir(src):
            shutil.copytree(src, d, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".git", ".venv"), symlinks=True)
        else:
            shutil.copy2(src, d)
    for venv in ("agentsite/.venv", ".venv"):
        real = os.path.join(ROOT, venv)
        if not os.path.isdir(real): continue
        link = os.path.join(dst, venv)
        if os.path.isdir(link) and not os.path.islink(link):
            shutil.rmtree(link)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if not os.path.exists(link):
            os.symlink(real, link)
    if not os.path.exists(os.path.join(dst, "backend", "lanxiu.db")):
        raise SystemExit("❌ 副本里没有 backend/lanxiu.db —— 拷贝漏了库,跑出来的全是环境问题")
    return dst


def 门禁怎么跑(script):
    """从 check.sh 里取这个脚本的原样命令。

    ⚠️ **不要自己拼 `python3 <脚本>`。** 门禁里有些步骤用的是 `agentsite/.venv/bin/python`，
    有些带 `--selftest` 参数。用另一种姿势去跑，验的就不是门禁验的那个东西 ——
    这个项目已经栽过一次同族的事：副本测试没软链 venv，7 项「失败」全是环境问题，
    和真的数据问题混在同一张报告里。
    """
    sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    for line in sh.split("\n"):
        if not line.startswith("run "): continue
        if script not in line: continue
        # run "标题" cmd args...   —— 标题带引号，去掉它之后剩下的就是命令
        rest = line[4:].strip()
        if rest.startswith('"'):
            rest = rest[rest.index('"', 1) + 1:]
        parts = rest.split()
        if parts: return parts
    return [sys.executable, script]


def 跑(sand, script):
    cmd = 门禁怎么跑(script)
    p = subprocess.run(cmd, cwd=sand, capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


def 改文件(sand, path, old, new):
    f = os.path.join(sand, path)
    s = open(f, encoding="utf-8").read()
    if old not in s:
        return f"要改的那段在 {path} 里找不到 —— **注入没进检查的视野,这条规格本身是坏的**"
    open(f, "w", encoding="utf-8").write(s.replace(old, new, 1))
    return None


def 改库(sand, sqls):
    import sqlite3
    c = sqlite3.connect(os.path.join(sand, "backend", "lanxiu.db"))
    动 = 0
    try:
        for q in sqls:
            动 += c.execute(q).rowcount
        c.commit()
    finally:
        c.close()
    # ⚠️ 影响 0 行的 UPDATE/DELETE 不报错,而「改坏了」和「什么都没改」
    #    在后面的结果里长得一模一样 —— 必须在这里拦住。
    if 动 <= 0:
        return "SQL 影响 0 行 —— **什么都没改坏**,后面就算红了也跟这条规格无关"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--specs", default=SPECS)
    # 探测模式:只改坏、把实际红的那几条打出来,用来写「预期红」。
    # 对照绿那一关照走 —— 所以打出来的红,必然是这次破坏造成的。
    ap.add_argument("--discover", action="store_true")
    a = ap.parse_args()

    specs = json.load(open(a.specs, encoding="utf-8")) if os.path.exists(a.specs) else []
    if a.only:
        specs = [s for s in specs if a.only in s["script"] or a.only in s.get("改坏", "")]
    if a.list:
        for s in specs: print(f"  {s['script']:<42} {s['改坏']}")
        print(f"共 {len(specs)} 条")
        return 0

    if not specs:
        print("没有规格可跑"); return 1

    base = tempfile.mkdtemp(prefix="bite-")
    pristine = 建副本(os.path.join(base, "pristine"))
    print(f"副本:{base}")
    print("=" * 96)

    对照 = {}
    红 = []
    for i, s in enumerate(specs, 1):
        script, expect = s["script"], s["预期红"]
        work = os.path.join(base, "work")
        if os.path.isdir(work): shutil.rmtree(work)
        shutil.copytree(pristine, work)

        # ① 对照要绿
        if script not in 对照:
            rc0, out0 = 跑(work, script)
            对照[script] = (rc0, out0)
        rc0, out0 = 对照[script]
        if rc0 != 0:
            print(f"  ❌ [{i}/{len(specs)}] {script}  **对照就是红的** —— 这条咬合证明不了任何事")
            红.append(s); continue

        # ② 改坏
        err = None
        if s.get("sql"):   err = 改库(work, s["sql"])
        if not err and s.get("file"):
            for f in s["file"]:
                err = 改文件(work, f["path"], f["old"], f["new"])
                if err: break
        if err:
            print(f"  ❌ [{i}/{len(specs)}] {script}  {err}")
            红.append(s); continue

        # ③ 红的必须是那一条
        rc, out = 跑(work, script)
        # 红有两种长相:自己打 ❌ 的,和直接 assert 抛出来的。
        # 只认前者的话,用 assert 的脚本会被判成「红的不是那一条」——
        # 而那是**判据贴着字面(找 ❌ 这个符号)而不是含义(这一条失败了)**。
        def 是红行(l):
            # 失败的写法不止一种:❌ / ✗ / assert 抛出 / 「失败」二字。
            # 只认某一个符号,就是**判据贴着字面而不是含义** —— 这道执行器自己栽过两次:
            # 先是只认 ❌(用 assert 的脚本判不出),再是漏了 ✗(fakedata 那套用的是它)。
            return any(k in l for k in ("❌", "✗", "AssertionError", "Error:"))
        命中 = [l for l in out.split("\n") if 是红行(l) and expect in l]
        if a.discover:
            reds = [l.strip() for l in out.split("\n") if 是红行(l)][:3]
            print(f"  🔍 [{i}/{len(specs)}] {script}  rc={rc}  {s['改坏']}")
            for l in reds: print(f"       红:{l[:120]}")
            if rc == 0: print("       ⚠️ 改坏了却没红 —— 这处破坏检查看不见"); 红.append(s)
            continue
        if rc == 0:
            print(f"  ❌ [{i}/{len(specs)}] {script}  改坏了却**没红** —— 检查看不见这处破坏")
            红.append(s)
        elif not 命中:
            别的 = [l.strip() for l in out.split("\n") if 是红行(l)][:2]
            print(f"  ❌ [{i}/{len(specs)}] {script}  红了,但**红的不是那一条**")
            print(f"       预期:{expect}")
            for l in 别的: print(f"       实际:{l[:110]}")
            红.append(s)
        else:
            print(f"  ✅ [{i}/{len(specs)}] {script}  {s['改坏']}")

    print("=" * 96)
    shutil.rmtree(base, ignore_errors=True)
    if 红:
        print(f"❌ {len(红)}/{len(specs)} 条咬合规格没过 —— **这些检查没被证明过**")
        return 1
    print(f"✅ {len(specs)} 条咬合规格全过(每条都验了:对照绿 → 改坏 → 红的是那一条)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
