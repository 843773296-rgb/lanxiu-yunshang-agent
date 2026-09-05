#!/usr/bin/env python3
"""从 git 历史生成《项目日志》。

**为什么能这么生成:** 这个项目的提交信息本身就写了「为什么这么改」和「踩了什么坑」,
不是「fix bug」那种。所以日志不用另写一遍 —— 直接把提交信息组织起来就是。

> 反过来说这也是个约束:**提交信息写得敷衍,日志就是敷衍的。**
> 想要好日志,就得在提交的那一刻把话说清楚。

用法:
    python3 tools/make_log.py            # 生成 项目日志.md
    python3 tools/make_log.py --publish  # 生成并发飞书
"""
import os, re, subprocess, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "项目日志.md")
SEP = "\x1e"      # 记录分隔符,用不可见字符,免得撞上正文里的符号


def git(*a):
    return subprocess.run(["git", "-C", ROOT, *a], capture_output=True,
                          text=True, check=True).stdout


def commits():
    raw = git("log", "--reverse", f"--pretty=format:%H{SEP}%ad{SEP}%s{SEP}%b{SEP}",
              "--date=format:%Y-%m-%d %H:%M")
    out = []
    for chunk in raw.split(SEP + "\n"):
        parts = chunk.strip().split(SEP)
        if len(parts) < 3: continue
        h, d, subj = parts[0].strip(), parts[1], parts[2]
        body = parts[3] if len(parts) > 3 else ""
        # 把归属行去掉,它们不是日志内容
        body = re.sub(r"^(Co-Authored-By|Claude-Session|🤖 Generated).*$", "",
                      body, flags=re.M).strip()
        out.append(dict(h=h[:7], date=d, subj=subj, body=body))
    return out


def stats():
    con = None
    db = os.path.join(ROOT, "backend", "lanxiu.db")
    rows = {}
    if os.path.exists(db):
        import sqlite3
        c = sqlite3.connect(db)
        for label, sql in [("商品", "product"), ("SKU", "sku"), ("相容矩阵", "craft_combo"),
                           ("知识条目", "craft"), ("版型", "pattern"), ("推档尺码", "size_spec"),
                           ("物料", "material"), ("师傅", "artisan")]:
            try: rows[label] = c.execute(f"SELECT COUNT(*) FROM {sql}").fetchone()[0]
            except Exception: pass
    py = subprocess.run(["bash", "-c",
                         f"find {ROOT} -name '*.py' -not -path '*/.git/*' "
                         f"-not -path '*/.venv/*' -not -path '*__pycache__*' | wc -l"],
                        capture_output=True, text=True).stdout.strip()
    checks = subprocess.run(["bash", "-c", f"grep -c '^run ' {ROOT}/check.sh"],
                            capture_output=True, text=True).stdout.strip()
    rows["Python 文件"] = py
    rows["check.sh 检查项"] = checks
    return rows


def build():
    cs = commits()
    by_day = collections.OrderedDict()
    for c in cs: by_day.setdefault(c["date"][:10], []).append(c)
    st = stats()

    L = ["# 澜绣云裳智能体 · 项目日志", "",
         f"> 自动生成自 git 历史(共 {len(cs)} 次提交),最后更新 "
         f"{subprocess.run(['date','+%Y-%m-%d %H:%M'],capture_output=True,text=True).stdout.strip()}",
         "> 生成方式:`python3 tools/make_log.py`", "",
         "**这份日志能自动生成,是因为提交信息里写了「为什么这么改」和「踩了什么坑」,"
         "不是「fix bug」那种。** 反过来说也是个约束:提交信息写得敷衍,日志就是敷衍的。", "",
         "---", "", "## 当前规模", "", "| | |", "|---|---|"]
    for k, v in st.items(): L.append(f"| {k} | {v} |")
    L += ["", "---", "", "## 变更记录", ""]
    for day, items in by_day.items():
        L.append(f"### {day}  ·  {len(items)} 次提交")
        L.append("")
        for c in items:
            L.append(f"#### {c['subj']}")
            L.append(f"`{c['h']}` · {c['date'][11:]}")
            L.append("")
            if c["body"]:
                L.append(c["body"])
                L.append("")
        L.append("---")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    md = build()
    open(OUT, "w", encoding="utf-8").write(md)
    print(f"写好 {OUT}  ({len(md.splitlines())} 行 / {len(md)} 字符)")
    if "--publish" in sys.argv:
        sp = "/private/tmp/claude-501/-Users-eureka/ba8cb0f4-e02a-4402-b9bf-3ff3ab966980/scratchpad"
        os.makedirs(sp, exist_ok=True)
        dst = os.path.join(sp, "澜绣云裳agent-项目日志.md")
        open(dst, "w", encoding="utf-8").write(md)
        subprocess.run(["python3", os.path.expanduser(
            "~/Desktop/chatgpt/tools/feishu_publish.py"), dst])
