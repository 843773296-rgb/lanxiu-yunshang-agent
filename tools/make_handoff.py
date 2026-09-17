#!/usr/bin/env python3
"""生成 / 刷新 HANDOFF.md —— 上下文满了之后,接手的那个会话先读它。

## 为什么单独有这份文档

项目里已经有两份文档,但它们都答不了「**现在在做什么**」:

    CLAUDE.md    不变的约定和地雷        —— 很少失效
    项目日志.md   已完成的(从 git 生成)  —— 不会失效
    HANDOFF.md   **正在进行的**          —— 每天都失效

只有第三份会失效,所以它必须**能自动刷新**,而且要**短到接手的人真的会读**。
写成第二份项目介绍就白写了 —— 重复的文档一定不同步。

## 哪些自动、哪些手写

自动区(`<!--AUTO-->` 之间)每次重新生成:git 状态、检查结果、服务、计数。
**这些一律不许手写** —— 手写就会和真实状态漂,而交接文档漂了比没有更糟:
接手的人会照着一个假状态往下做。

手写区**原样保留**,只有人知道:为什么在做这个、下一步第一个动作、
以及**试过什么、为什么放弃**。

最后那条是交接里最容易丢、也最贵的一项:
**「做了什么」在 git 里躺着,「否决过什么」只在脑子里。**
上下文一满就没了,下一个会话大概率把同一条死路再走一遍。
"""
import os, re, subprocess, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "HANDOFF.md")
A0, A1 = "<!--AUTO-->", "<!--/AUTO-->"

# 手写区必填的段。缺一段就不算一份能用的交接。
REQUIRED = ["## 一句话:现在在做什么",
            "## 上一次停在哪",
            "## 没做完的 —— 下一步第一个动作",
            "## 别重做:试过并否决的"]
PLACEHOLDER = "(待填)"


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把交接文档里「别重做:试过并否决的」那一段标题换掉(必填的一段从此认不出来)',
     '缺段落'),
]

def sh(cmd, default=""):
    try:
        return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True,
                              text=True, timeout=60).stdout.strip() or default
    except Exception:
        return default


def auto_block():
    n_py = sh("git ls-files '*.py' | wc -l").strip()
    n_line = sh("git ls-files '*.py' | xargs wc -l | tail -1").split()
    n_line = n_line[0] if n_line else "?"
    commits = sh("git log --oneline -5 --format='%h %s'")
    dirty = sh("git status --porcelain")
    branch = sh("git rev-parse --abbrev-ref HEAD", "?")
    head = sh("git log -1 --format='%h · %ad · %s' --date=short", "?")
    n_check = sh("grep -c '^run ' check.sh", "?")
    ports = []
    for p, name in (("8760", "管理后台"), ("8770", "智能运维平台")):
        code = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 3 http://127.0.0.1:{p}/", "000")
        ports.append(f"{name} :{p} → {'在跑 ' + code if code == '200' else '没起来'}")
    L = [A0,
         f"> 自动区,由 `python3 tools/make_handoff.py` 生成于 "
         f"{datetime.datetime.now():%Y-%m-%d %H:%M}。**不要手改这一段。**",
         "",
         "| 项 | 值 |", "|---|---|",
         f"| 分支 | `{branch}` |",
         f"| 最新提交 | {head} |",
         f"| 代码量 | {n_py} 个 Python 文件 / {n_line} 行(不含 .venv) |",
         f"| 验收 | `./check.sh` 共 {n_check} 项 —— **接手第一件事就是跑它** |",
         f"| 服务 | {' · '.join(ports)} |",
         "",
         "**未提交的改动:**", ""]
    if dirty:
        L.append("```")
        L += dirty.splitlines()[:20]
        L.append("```")
        L.append("⚠️ 工作区不干净。**先搞清楚这些改动是什么再往下做** ——"
                 "上一个会话可能是被打断的,而不是做完了。")
    else:
        L.append("干净 —— 上一个会话的东西都提交了。")
    L += ["", "**最近 5 次提交:**", "", "```", commits, "```", A1]
    return "\n".join(L)


TEMPLATE = f"""# 交接文档

> 上下文满了、换会话、隔几天回来 —— **先读这一份**,再读 `CLAUDE.md`。
> 这份只装「正在进行的」;不变的约定和地雷在 `CLAUDE.md`,
> 已经完成的在 `项目日志.md`(从 git 生成)。

## 接手先做这三件事

1. 读完这一页(两分钟)
2. 跑 `./check.sh` —— 绿了才说明你接到的是一个完好的状态
3. 看下面「没做完的」第一个动作,直接开始

{REQUIRED[0]}

{PLACEHOLDER}

{REQUIRED[1]}

{PLACEHOLDER}

{REQUIRED[2]}

{PLACEHOLDER}

{REQUIRED[3]}

> **这一段是交接里最贵的。** 「做了什么」在 git 里躺着,
> 「试过什么、为什么放弃」只在上一个会话的脑子里 ——
> 不写下来,下一个会话大概率把同一条死路再走一遍。

{PLACEHOLDER}

## 当前状态(自动)

{{AUTO}}
"""


def refresh():
    if os.path.exists(DOC):
        old = open(DOC, encoding="utf-8").read()
        if A0 in old and A1 in old:
            new = re.sub(re.escape(A0) + r".*?" + re.escape(A1), lambda m: auto_block(),
                         old, flags=re.S)
        else:
            new = old.rstrip() + "\n\n## 当前状态(自动)\n\n" + auto_block() + "\n"
    else:
        new = TEMPLATE.replace("{AUTO}", auto_block())
    open(DOC, "w", encoding="utf-8").write(new)
    return new


def check():
    """不查「内容对不对」—— 那只有人知道。查的是「这份交接能不能用」。"""
    if not os.path.exists(DOC):
        return ["没有 HANDOFF.md —— 跑 `python3 tools/make_handoff.py`"]
    t = open(DOC, encoding="utf-8").read()
    bad = [f"缺段落「{h}」" for h in REQUIRED if h not in t]
    for h in REQUIRED:
        if h in t:
            body = t.split(h, 1)[1].split("\n## ", 1)[0]
            if PLACEHOLDER in body or not body.strip():
                bad.append(f"「{h}」还是空的 —— **一份「下一步」为空的交接等于没交接**")
    if A0 not in t or A1 not in t:
        bad.append("自动区标记不见了 —— 状态那一段会烂掉")
    return bad


if __name__ == "__main__":
    if "--check" in sys.argv:
        bad = check()
        print("交接文档 · 可用性检查\n" + "=" * 72)
        for b in bad: print(f"  ❌ {b}")
        if not bad:
            print(f"  ✅ HANDOFF.md 四段必填齐全,自动区完好")
            print("     (只查「能不能用」,内容对不对只有人知道)")
        sys.exit(1 if bad else 0)
    refresh()
    print(f"已刷新 {DOC}")
    for b in check(): print(f"  ⚠ {b}")
