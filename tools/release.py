#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布版本号(用户 2026-10-19 拍「发布版本号做」)。

原来:git 里一个 tag 都没有,代码只有提交号;需求文档和产品说明从 2026-09-18 起一直写着 V1.0,
之后一千多次提交、几十项功能,版本号一次没动 —— **「V1.0」已经名不副实,而且没有任何东西会因此报红**。

现在:
  · 版本号**只记一处**:仓库根目录的 `VERSION`(形如 1.1.0)。文档、页面都从它读或被 `tools/version_check.py` 对账;
  · 「这一版改了什么」**从 git 现生成**,不手写 —— 写进 `澜绣云裳agent-发布记录.md`(最新的在最上面);
  · 打 tag 放在门禁绿了、提交推送之后,所以 tag 指着的那个提交一定过过门禁。

两步(之间要跑门禁、提交推送):

    python3 tools/release.py 准备 1.2.0 --说明 "<这一版一句话>"   # 改 VERSION、在发布记录顶上加一节
    ./check.sh && git commit … && git push                          # 照常
    python3 tools/release.py 打标签                                   # 给 HEAD 打 v<VERSION>,推到远程

参数拼错一律拒跑。
"""
import datetime as dt
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
版本文件 = os.path.join(ROOT, "VERSION")
记录文件 = os.path.join(ROOT, "澜绣云裳agent-发布记录.md")
# 第一次打 tag 之前,上一版没有 tag。需求文档的版本记录里:V1.0 = 2026-09-18 首版基线,V1.1 = 2026-09-19 工具合并 ——
# 两版都没打过 tag。所以第一次发布从 V1.1 之后那天起算(按日期近似,发布记录里照实写明)
上一版 = "V1.1(2026-09-19,没打过标签,按日期从 2026-09-20 起算)"
上一版起点 = "2026-09-20"
格式 = re.compile(r"^\d+\.\d+\.\d+$")


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def 当前版本():
    return open(版本文件, encoding="utf-8").read().strip() if os.path.exists(版本文件) else None


def 上一个标签():
    tags = [t for t in _git("tag", "--list", "v*", "--sort=-v:refname").splitlines() if t]
    return tags[0] if tags else None


def 改了什么(自=None):
    """→ [(日期, [(短号, 第一行说明)…])…],按日期倒序。自 = 上一个 tag;没有就从上一版那天起。"""
    范围 = [f"{自}..HEAD"] if 自 else ["--since", 上一版起点, "HEAD"]
    行 = _git("log", *范围, "--format=%h\t%ad\t%s", "--date=short").splitlines()
    按天 = {}
    for l in 行:
        h, d, s = l.split("\t", 2)
        按天.setdefault(d, []).append((h, s))
    return sorted(按天.items(), reverse=True)


def 准备(新, 说明):
    if not 格式.match(新):
        sys.exit(f"版本号要写成 主.次.修(如 1.2.0),给的是「{新}」")
    旧 = 当前版本()
    if 旧 and tuple(map(int, 新.split("."))) <= tuple(map(int, 旧.split("."))):
        sys.exit(f"新版本 {新} 不比现在的 {旧} 大 —— 版本号只许往上走")
    if not (说明 or "").strip():
        sys.exit("要写 --说明:这一版一句话说清是什么")
    自 = 上一个标签()
    天 = 改了什么(自)
    n = sum(len(v) for _, v in 天)
    节 = [f"## v{新} · {dt.date.today().isoformat()}\n",       # 真实时钟:发布日是人哪天发的,不是演示世界里的日子
          f"**{说明.strip()}**\n",
          f"> 从 {自 or 上一版} 到这一版,共 {n} 次提交。下面按日期列每次提交的第一行 —— "
          "**由 `tools/release.py` 从 git 生成,不手写**;要看「为什么」去项目日志或 `git show <提交号>`。\n"]
    for d, 列 in 天:
        节.append(f"\n<details><summary>{d} · {len(列)} 次</summary>\n\n" + "\n".join(f"- `{h}` {s}" for h, s in 列)
                 + "\n\n</details>\n")
    头 = ("# 澜绣云裳agent · 发布记录\n\n"
          "> 每一版一节,**最新的在最上面**。版本号只记在仓库根目录的 `VERSION`;"
          "页面右下角显示的就是它(和正在跑的提交号)。\n")
    旧文 = open(记录文件, encoding="utf-8").read() if os.path.exists(记录文件) else 头
    if f"## v{新} " in 旧文:
        sys.exit(f"发布记录里已经有 v{新} 那一节了")
    正文 = 旧文.split("\n## ", 1)
    新文 = 正文[0].rstrip() + "\n\n" + "\n".join(节) + ("\n## " + 正文[1] if len(正文) > 1 else "")
    open(记录文件, "w", encoding="utf-8").write(新文)
    open(版本文件, "w", encoding="utf-8").write(新 + "\n")
    print(f"VERSION {旧 or '(无)'} → {新};发布记录加了 v{新} 一节({n} 次提交)。"
          f"\n下一步:改需求文档 / 产品说明里的版本号(version_check 会盯)→ 门禁 → 提交推送 → `release.py 打标签`")


def 打标签():
    v = 当前版本()
    if not v:
        sys.exit("没有 VERSION 文件")
    if _git("status", "--porcelain", "--", "VERSION", os.path.basename(记录文件)):
        sys.exit("VERSION 或发布记录还没提交 —— 先跑门禁、提交推送,再打标签(tag 要指着过过门禁的那个提交)")
    if f"v{v}" in _git("tag", "--list").splitlines():
        sys.exit(f"v{v} 已经打过了")
    _git("tag", "-a", f"v{v}", "-m", f"澜绣云裳agent v{v}")
    _git("push", "origin", f"v{v}")
    print(f"打了 v{v} → {_git('rev-parse', '--short', 'HEAD')},已推到远程")


a = sys.argv[1:]
if len(a) == 4 and a[0] == "准备" and "--说明" in a[1:3]:
    i = a.index("--说明")
    准备(a[3 if i == 1 else 1], a[i + 1])
elif a == ["打标签"]:
    打标签()
else:
    sys.exit(f"不认识的用法:{a}\n" + (__doc__ or ""))
