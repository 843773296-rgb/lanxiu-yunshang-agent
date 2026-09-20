#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建可复现 —— **同一份代码建两次库,数据必须一模一样**。

    python3 tools/determinism_check.py            # 只扫「会造成不可复现」的写法(秒级,进门禁)
    python3 tools/determinism_check.py --真建两次   # 真跑两遍重建再逐行比(约 2 分钟,手动)

## 为什么要有这条

2026-09-20 查出来的:同一份代码重建两次,**订单总数、客户数、维保数全都一样,
而 3500 张订单的状态、金额、归属人都不同**。根子是 `run_journey` 挑客户用了
SQL 的 `ORDER BY RANDOM()` —— 它不受 Python 的种子管。

代价不是「数据有点抖」,是**评测和门禁失去意义**:
CI 上一条判「哪几档维保率值得注意」的检查间歇变红,而最紧的一档离阈值只有 0.9%,
数据一抖就翻面。**判据对着一个会动的东西量,红绿就不再有意义。**

> 比「两个状态长得一样」更狠一层:这是**同一个状态量两次不一样**,
> 连「重复测一遍」这个兜底都失效了。

## 这里扫的是**写法**,不是结果

真跑两遍要两分钟,进不了门禁(门禁得快)。所以门禁里扫的是几种
**已知会造成不可复现的写法**,每一种都在这个项目里真的出现过:

  · SQL 的 `ORDER BY RANDOM()` / `RANDOM()` —— 不受 Python 种子管
  · 造数据的脚本里用**全局 random 却没有 seed** —— 每次跑都不一样
  · 拿**机器的今天**当基准(`date.today()` / `datetime.now()`)——
    今天每过一天就变一次,而这个项目的世界有自己固定的「今天」

⚠️ **扫写法抓不到全部。** 一条 `ORDER BY` 漏掉、一个 set 的遍历顺序被当成稳定的,
这里都看不见 —— 所以留了 `--真建两次`,改完造数据的脚本要手动跑一次。
"""
import os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, R, D = "\033[32m", "\033[31m", "\033[0m"

def 造数据的步骤():
    """**从 `rebuild.sh` 里现读,不在这儿手抄一份。**

    手抄的话,别人往流水线末尾加一步(比如回填某个维度),这份清单不会跟着变 ——
    于是**新加的那一步不受这条检查管**,而检查照样报绿。
    「扫过了没问题」和「根本没扫它」在输出上长得一模一样,这个项目栽过好几次。
    """
    sh = open(os.path.join(ROOT, "tools", "rebuild.sh"), encoding="utf-8").read()
    m = re.search(r'for STEP in (.+?); do', sh, re.S)
    if not m:
        raise SystemExit("❌ 读不出 rebuild.sh 里的步骤清单 —— "
                         "**这条检查的覆盖面就是从那里来的**,读不到就不许假装扫过了")
    out = []
    for 段 in re.findall(r'"([^"]+)"', m.group(1)):
        f = 段.split()[0]                     # "tools/run_journey.py 42" → 去掉参数
        if f.endswith(".py") and os.path.isfile(os.path.join(ROOT, f)):
            out.append(f)
    return out


造数据 = 造数据的步骤()

咬合 = [
    ("在造数据的脚本里写回一句 SQL 的 ORDER BY RANDOM()", "SQL 里不许用 RANDOM() 抽样"),
    ("把 run_journey 的 random.seed(SEED) 去掉", "造数据的脚本都设了种子"),
    ("把 rebuild.sh 里的步骤清单读法改坏(扫不到任何脚本)", "读不出 rebuild.sh 里的步骤清单"),
]

失败 = []
放行 = []
# 行末写上它 = 这一行确实要用真实时钟 / 随机,并且**写清为什么**。
# 豁免不是关掉检查:每次跑都会把豁免了哪几行打出来,让它保持可见。
豁免标记 = "# 真实时钟:"


def 剥文档字符串(src):
    """只把 docstring 那几行清空,别的原样留着(SQL 也写在三引号里,不能一起剥)"""
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    行 = src.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        一 = body[0]
        if isinstance(一, ast.Expr) and isinstance(一.value, ast.Constant) and isinstance(一.value.value, str):
            for i in range(一.lineno - 1, (一.end_lineno or 一.lineno)):
                if i < len(行):
                    行[i] = ""
    return "\n".join(行)


def 报(名, ok, 说明=""):
    print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
    if not ok:
        失败.append(名)


def 扫():
    print("重建可复现 · 扫写法")
    坏 = []
    无种子 = []
    用今天 = []
    for f in 造数据:
        p = os.path.join(ROOT, f)
        if not os.path.isfile(p):
            continue
        t = open(p, encoding="utf-8").read()
        # **注释和文档字符串里写着反面教材**(「不许用 ORDER BY RANDOM」这句话本身),
        # 不剥掉的话这条检查会抓自己 —— 和 scan_secrets 当年「规则文件匹配自己」同一个坑。
        #
        # ⚠️ 用正则剥三引号会**连 SQL 一起剥掉**(查询语句也写在三引号里),
        # 于是这条检查当场变瞎:手动把 ORDER BY RANDOM() 写回去,它照样绿。
        # 咬合当场抓到。改成按语法树只剥**文档字符串**(模块 / 函数 / 类的第一条语句)。
        码 = 剥文档字符串(t)
        码 = "\n".join(l for l in 码.splitlines() if not l.lstrip().startswith("#"))
        # 一行末尾写了豁免标记的,按豁免算 —— 但**豁免要能被看见**,见下面的打印
        豁免 = [l for l in 码.splitlines() if 豁免标记 in l]
        码 = "\n".join(l for l in 码.splitlines() if 豁免标记 not in l)
        for l in 豁免:
            放行.append(f"{f}:{l.strip()[:60]}")
        if re.search(r"ORDER\s+BY\s+RANDOM\s*\(", 码, re.I):
            坏.append(f)
        # 用了全局 random.xxx( 就必须有 random.seed / Random(种子)
        用全局 = re.search(r"(?<![\w.])random\.(?!seed|Random)\w+\(", 码)
        有种子 = re.search(r"random\.seed\(|random\.Random\(", 码)
        if 用全局 and not 有种子:
            无种子.append(f)
        if re.search(r"date\.today\(\)|datetime\.now\(\)", 码):
            用今天.append(f)

    # **先报覆盖面**:扫了哪几个脚本。样本量为 0 时所有性质自动成立 ——
    # 「都合规」和「一个都没扫到」必须分得开。
    报("扫到的步骤和 rebuild.sh 一致", len(造数据) >= 5,
       f"{len(造数据)} 步:{'、'.join(os.path.basename(x) for x in 造数据)}")
    报("SQL 里不许用 RANDOM() 抽样", not 坏,
       "、".join(坏) if 坏 else f"扫了 {len(造数据)} 个造数据脚本 —— "
       "SQLite 的 RANDOM() **不受 Python 种子管**,抽样要先定序再用带种子的 rng 抽")
    报("造数据的脚本都设了种子", not 无种子,
       "、".join(无种子) if 无种子 else "用到随机的都设了种子")
    if 放行:
        print(f"     ℹ️ 豁免 {len(放行)} 行(写明了为什么要用真实时钟):")
        for x in 放行:
            print(f"        {x}")
    报("不拿机器的今天当基准", not 用今天,
       ("、".join(用今天) + " —— 世界的『今天』写在 seed.py 的 TODAY,"
        "拿机器的今天会让同一份代码今天和明天造出不同的数据") if 用今天 else
       "基准日都取自 seed.py 的 TODAY")


def 真建两次():
    import sqlite3, shutil, tempfile
    print("\n重建两次,逐表比对(约 2 分钟)")
    db = os.path.join(ROOT, "backend", "lanxiu.db")
    快照 = []
    for i in (1, 2):
        r = subprocess.run([os.path.join(ROOT, "tools", "rebuild.sh")],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            报(f"第 {i} 次重建", False, r.stdout[-300:])
            return
        f = tempfile.mktemp(suffix=f"-{i}.db")
        shutil.copy2(db, f)
        快照.append(f)
    A, B = (sqlite3.connect(x) for x in 快照)
    表 = [r[0] for r in A.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    差 = []
    for t in 表:
        if t == "truth":
            continue
        try:
            a = A.execute(f"SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(t.* AS TEXT))),0) FROM (SELECT * FROM {t}) t")
        except Exception:
            a = None
        na = A.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        nb = B.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        if na != nb:
            差.append(f"{t}:行数 {na} vs {nb}")
            continue
        ha = A.execute(f"SELECT group_concat(x) FROM (SELECT quote(t.rowid)||quote(t.*) x FROM {t} t ORDER BY t.rowid)").fetchone()[0]
        hb = B.execute(f"SELECT group_concat(x) FROM (SELECT quote(t.rowid)||quote(t.*) x FROM {t} t ORDER BY t.rowid)").fetchone()[0]
        if ha != hb:
            差.append(f"{t}:行数一样({na})而内容不同 —— **总数相同最容易掩盖内容不同**")
    报("两次重建逐表一致", not 差, "；".join(差[:4]) if 差 else f"{len(表)} 张表全一致")


def main():
    扫()
    if "--真建两次" in sys.argv:
        真建两次()
    print((f"{R}❌ 重建可复现 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 重建可复现{D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
