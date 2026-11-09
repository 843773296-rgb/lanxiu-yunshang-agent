#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell 脚本里「不加花括号的变量紧跟中文」· 检查(不调模型、不碰库、不碰锁)

## 为什么要这条检查

2026-11-09 全项目评测快照起跑前,新写的 `snapshot_check.py` 第一次跑就崩在一个
`UnicodeDecodeError` 上。顺着查下去,根因是 `tools/gate_lock.sh` 里这么一行:

    echo "   ……去问一声,或者手工 rm -rf $LOCK_DIR。" >&2

`$LOCK_DIR` 后面**紧跟一个中文句号**。shell 解析变量名时,把那个句号的
**第一个字节**(`。` 是三字节字符)也吃进了变量名,于是它去展开一个根本不存在的
变量 —— **展开成空**,而那个字符剩下的两个字节原样吐了出来。

**一行代码同时坏两样,而两样都安静:**

  ① **路径没了。** 那句话本来要告诉人「去 `rm -rf <哪个目录>`」,
     实际印出来的是「`rm -rf `」 —— 后面什么都没有。
     一句**告诉人去删东西、却没说删哪个**的提示,比不印更糟。
  ② **那段输出不再是合法 UTF-8。** 下游任何拿 `text=True` 捕获它的 Python
     **当场抛 UnicodeDecodeError**。全项目快照的调度器正是这么捕获的,
     而这一行只在「**等锁超时**」这条罕见路径上出现 ——
     平时没人碰到,27 套连跑的那一夜会碰上 27 次,
     表现是**整夜全丢 + 一个看不出和锁有任何关系的 traceback**。

> 一个「等锁超时了,这一套末尾重试」和一个「整个调度在解一个字节时崩死」,
> **在那一夜什么都没产出这件事上长得一模一样** —— 而前者第二天还有数据。

## 这条检查管两件

  ① **试纸**:真跑一次那个写法,证明这个陷阱**今天还在**。
     不判红 —— 哪天 shell 或 locale 变了、这个坑没了,那是好事,不是错误;
     但它得**说出来**,因为那时这条检查就该退休,而不是继续当摆设。
  ② **扫描**:库里跟踪的所有 shell 脚本,非注释行里不许出现「`$变量`
     紧跟多字节字符」。要紧跟就写 `${变量}`。

⚠️ 为什么扫**结构**而不是去找「`$LOCK_DIR。`」这一处:
   同样的写法在任何脚本、任何变量名上都会犯,而中文标点有一大把
   (。,、;:「」()—— 还有汉字本身)。**枚举必输**,所以判据查的是
   「`$名字` 后面紧跟的那个字符是不是多字节」这个形状。
"""
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# 不加花括号的 $VAR,紧跟一个非 ASCII 字符。`${VAR}` 和 `$1` / `$?` / `$$` 不在内。
坏写法 = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*(?=[^\x00-\x7f])")

# 咬合 —— 改坏的是什么、该红的是哪一条。(可执行的在 tools/bite_specs.json)
# ⚠️ 这条咬合的破坏点就是**把 2026-11-09 修掉的那个 bug 原样放回去** ——
#    拿「逼出这条判据的那次翻车」当试纸:扫不到它,就说明判据的视野漏了。
咬合 = [
    ("把 gate_lock.sh 等锁超时那行提示里的变量花括号去掉(即 2026-11-09 修掉的那个写法)——"
     "shell 把中文句号的首字节吃进变量名:提示里的路径变成空,那段 stderr 不再是合法 UTF-8,"
     "而全项目快照的调度器按文本捕获它会当场崩死整夜",
     "非注释行有"),
]

print("shell 脚本 · 变量紧跟中文(不加花括号会把首字节吃进变量名)")
print()

# ── ① 试纸:这个陷阱今天还在吗 ────────────────────────────────────────
# ⚠️ 用一条**和被检查代码同形**的小命令真跑一次,不靠「我记得 shell 是这样的」。
# ⚠️ **这里故意不传 `text=` / `errors=` —— 要的就是原始字节。**
# 给了任何一个,subprocess 就按文本模式解码,而这条判据要看的恰恰是
# 「那段输出能不能解成 UTF-8」—— 解码过一遍再看就永远是合法的,判据等于白写。
试 = subprocess.run(
    ["bash", "-c", 'X=/tmp/claude-shell-quote-probe; printf "%s" "手工 rm -rf $X。"'],
    capture_output=True)
吞了 = b"/tmp/claude-shell-quote-probe" not in 试.stdout
不合法 = False
try:
    试.stdout.decode("utf-8")
except UnicodeDecodeError:
    不合法 = True

if 吞了:
    print(f"  {G}✅{D} 试纸:这个陷阱今天还在 —— `$X。` 把变量吞掉了"
          f"{',而且吐出了非法 UTF-8' if 不合法 else ''}")
    print(f"       实际吐出:{试.stdout!r}")
else:
    print(f"  {Y}ℹ️{D} 试纸:**这台机器上这个写法没出错**(变量照样展开了)。")
    print(f"       实际吐出:{试.stdout!r}")
    print(f"       这不是错误,是好事。但判据**保留** —— 换一个 shell / locale 仍会犯,")
    print(f"       而真出事的是别人机器上的那一次。若哪天到处都不犯了,这条检查该退休,")
    print(f"       **而退休要由人决定,不该由它自己悄悄变成摆设**。")

print()

# ── ② 扫描 ───────────────────────────────────────────────────────────
# ⚠️⚠️ **自己遍历目录,不用 `git ls-files`。** 2026-11-09 第一版用的是 git,
# 而咬合在**工作区副本**上重放 —— 那个副本不是 git 仓库,于是列不出文件、判红,
# 咬合第一关当场报「对照就是红的,这条咬合证明不了任何事」。
#
# > 一条判据,如果它红不红取决于**环境里碰巧有什么**,那它不是在验代码。
#
# 那不只是咬合的事:任何非 git 环境(解包出来的目录、CI 的某些阶段)都会让它红,
# 而红的理由跟被检查的代码一点关系都没有 —— 照着那条红去查 shell 写法是白费功夫。
# (队友在 CI 上连红四次的 `queue_view_check` 是同一个形状,修法也一样:
#  判据自己造出它要验的东西,别指望环境。)
# 换成遍历还顺带多守一块:**新写的、还没 `git add` 的脚本也会被扫到**。
跳过 = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache",
       ".feynman", "venv", ".mypy_cache", ".ruff_cache"}
脚本们 = []
for 根, 子, 文 in os.walk(ROOT):
    子[:] = [d for d in 子 if d not in 跳过 and not d.startswith(".worktrees")]
    for f in 文:
        if f.endswith((".sh", ".bash", ".zsh")):
            脚本们.append(os.path.relpath(os.path.join(根, f), ROOT))
脚本们.sort()
命中, 注释里, 行数 = [], [], 0
for f in 脚本们:
    p = os.path.join(ROOT, f)
    if not os.path.exists(p):           # 别人刚删掉、索引还没更新
        continue
    for i, line in enumerate(io.open(p, encoding="utf-8", errors="replace"), 1):
        行数 += 1
        for m in 坏写法.finditer(line):
            (注释里 if line.lstrip().startswith("#") else 命中).append((f, i, m.group(0)))

# **先报样本量** —— 空集合上「一处都没有」自动成立,而那和「扫过了」不是一件事。
print(f"  扫了 {len(脚本们)} 个 shell 脚本 / {行数} 行(遍历目录,含还没入库的)")
if not 脚本们:
    print(f"  {R}❌ 一个 shell 脚本都没扫到 —— 是没扫到东西,不是都通过{D}")
    sys.exit(1)

if 注释里:
    print(f"  {Y}ℹ️{D} 注释里还有 {len(注释里)} 处(不影响运行,**没判红**):"
          + "、".join(f"{f}:{i}" for f, i, _ in 注释里[:6])
          + (f" …… 还有 {len(注释里) - 6} 处" if len(注释里) > 6 else ""))

if 命中:
    print()
    print(f"  {R}❌ 非注释行有 {len(命中)} 处「$变量紧跟多字节字符」{D}")
    for f, i, v in 命中[:20]:
        print(f"       {f}:{i}  —— `{v}` 后面紧跟中文,写成 `${{{v[1:]}}}` 就好")
    if len(命中) > 20:
        print(f"       …… 还有 {len(命中) - 20} 处(**没列完,不是只有这 20 处**)")
    print(f"  {R}   后果两样,都安静:提示里的路径变成空;那段输出不是合法 UTF-8,"
          f"下游拿 text=True 捕获它会当场崩{D}")
    sys.exit(1)

print(f"  {G}✅{D} 非注释行一处都没有")
print()
print(f"{G}✅ shell 变量写法:{len(脚本们)} 个脚本里没有「$变量紧跟中文」"
      f"(它会把路径悄悄变成空,还会让那段输出不是合法 UTF-8 —— "
      f"**而两样都只在罕见路径上暴露**){D}")
