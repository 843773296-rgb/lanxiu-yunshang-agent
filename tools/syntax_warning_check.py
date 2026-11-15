#!/usr/bin/env python3
"""Python 语法警告当红 —— 「只有走到那一行才崩」的那类错,在门禁里编译一遍就看得见。

为什么(2026-11-16 夜跑):排产评测一开跑就崩在一句提示上 ——
两段字符串中间漏了 `+`,Python 把第二段括号读成「调用第一段字符串」。
**编译时它就印了 SyntaxWarning**(Python 3.8 起对「字符串后面跟括号」这种必崩写法预警),
而门禁从没把警告当回事;那一支只在「库里没有过期单」时才走,所以平时的检查一次都没踩到。
一整套夜跑评测因此白跑,分数记成崩溃。

判据:对每个 .py 做一次 compile()(不执行),把这期间所有 SyntaxWarning 收下来 —— 有一条就红。
解析不了(SyntaxError)也红:编不了 = 没验过,不是 0 条。
先报样本量:扫到的文件太少 = 检查自己瞎了(git 失败 / 路径错),不是代码变干净了。

    python3 tools/syntax_warning_check.py
"""
import os
import subprocess
import sys
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R, G, D = "\033[31m", "\033[32m", "\033[0m"

# 咬合记录(规格在 tools/bite_specs.json):改坏的是什么 → 该红的是哪一条
咬合 = [
    ("把排产评测那句提示的 `+` 删回去(11-16 夜跑崩的原样)", "有 Python 语法警告"),
    ("样本下限抬到扫不到的数(检查瞎了要红,不许当成干净)", "只扫到"),
]
样本下限 = 800   # 11-16 实测 1126 个跟踪的 .py;咬合副本走遍历目录,数会少一些但远在这之上


def 文件们(根=ROOT):
    r = subprocess.run(["git", "-C", 根, "-c", "core.quotepath=false", "ls-files", "-z", "--cached", "--others",
                        "--exclude-standard", "*.py"], capture_output=True, text=True)
    fs = [f for f in r.stdout.split("\0") if f] if r.returncode == 0 else []
    if not fs:
        # 咬合重放在不带 .git 的副本上跑,git 列不出 —— 退回遍历目录(否则样本 0,对照组恒红)
        for d, ds, ns in os.walk(根):
            ds[:] = [x for x in ds if x not in (".git", ".venv", "venv", "node_modules", "__pycache__", ".claude")]
            fs += [os.path.relpath(os.path.join(d, n), 根) for n in ns if n.endswith(".py")]
    return sorted(set(fs))


def 扫(根=ROOT):
    见, 警告, 崩 = 0, [], []
    for f in 文件们(根):
        p = os.path.join(根, f)
        try:
            with open(p, encoding="utf-8") as fh:
                src = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        见 += 1
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                compile(src, f, "exec")
            except SyntaxError as e:
                崩.append(f"{f}:{e.lineno} {e.msg}")
        警告 += [f"{f}:{x.lineno} {x.message}" for x in w if issubclass(x.category, SyntaxWarning)]
    return 见, 警告, 崩


def main():
    见, 警告, 崩 = 扫()
    坏 = 0
    print(f"Python 语法警告 · 编译了 {见} 个 .py(不执行)")
    if 见 < 样本下限:
        print(f"  {R}❌ 只扫到 {见} 个(下限 {样本下限})—— 检查自己瞎了,不是代码变干净了{D}"); 坏 += 1
    if 崩:
        print(f"  {R}❌ 编译不了 {len(崩)} 个(编不了 = 没验过):{D}")
        for x in 崩[:10]:
            print(f"     {x}")
        if len(崩) > 10:
            print(f"     …还有 {len(崩) - 10} 条")
        坏 += 1
    if 警告:
        print(f"  {R}❌ 有 Python 语法警告 {len(警告)} 条 —— 这类写法多数走到那一行就崩(漏逗号 / 漏加号最常见):{D}")
        for x in 警告[:10]:
            print(f"     {x}")
        if len(警告) > 10:
            print(f"     …还有 {len(警告) - 10} 条")
        坏 += 1
    else:
        print(f"  {G}✅{D} 没有语法警告(验了 {见} 个)")
    sys.exit(1 if 坏 else 0)


if __name__ == "__main__":
    main()
