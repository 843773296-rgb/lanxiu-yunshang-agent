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
  · 用内置 `hash()` / `__hash__()` 去派生取值 —— **`str` 的哈希每个进程都不一样**
    (PYTHONHASHSEED 默认随机)。2026-09-21 抓到一个真的:
    `seed.py` 用 `abs(hash(sku编码))` 造供应商编码,**每重建一次 659 个 SKU 全换一批**,
    而没有任何东西报错。和同一天那起「22 款商品换颜色」是同一个根因。
    ⚠️ 这一条是**比对两次重建**才发现的,上面三条扫写法的规则一条都碰不到它 ——
    扫写法只抓得到你已经知道的那几种写法。

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
    ("在造数据的脚本里拿内置 hash() 去派生一个取值", "造数据的脚本不用内置 hash()"),
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
    用哈希 = []
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
        # Python 的时钟,和 **SQL 里的时钟** —— 后者原来一条都没扫。
        # `backend/oplog.py` 写的是 `datetime('now','localtime')`,
        # 扫 Python 那两个词一辈子也碰不到它。
        if re.search(r"date\.today\(\)|datetime\.now\(\)"
                     r"|datetime\s*\(\s*'now'|CURRENT_TIMESTAMP", 码, re.I):
            用今天.append(f)
        # 内置 hash():**每个进程给的值都不一样**。`hashlib.sha256(...)` 是稳的,
        # 所以只抓前面没有 `hashlib.`/`_hashlib.` 的那个 `hash(`。
        if re.search(r"(?<![\w.])hash\(|(?<!_)\.__hash__\(", 码):
            用哈希.append(f)

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
    报("造数据的脚本不用内置 hash()", not 用哈希,
       ("、".join(用哈希) + " —— **`str` 的内置哈希每个进程都不一样**"
        "(PYTHONHASHSEED 默认随机),重建一次换一批值,而不会报错。"
        "要稳定摘要就用 `hashlib.sha256(x.encode())`") if 用哈希 else
       "取值没有从内置 hash() 派生")
    报("不拿机器的今天当基准", not 用今天,
       ("、".join(用今天) + " —— 世界的『今天』写在 seed.py 的 TODAY,"
        "拿机器的今天会让同一份代码今天和明天造出不同的数据") if 用今天 else
       "基准日都取自 seed.py 的 TODAY")


# ── 登记在案:这几列按设计**每次重建都该不一样** ──────────────────────
#
# 写成显式登记,不是「差异少就忽略」—— 后者会把新冒出来的漂移一起放过,
# 而且**谁都不知道曾经放过了什么**。每次跑都会把它们打出来。
每次都该变 = {
    "account": {
        "列": ("pwd_salt", "pwd_hash"),
        "为什么": "每个账户一把独立的随机盐,是**安全属性**:"
                  "盐固定下来,一张彩虹表就能同时打穿所有账户。"
                  "demo 数据也不例外 —— 这份代码是会被人照抄的",
    },
    "staff": {
        "列": ("pwd_salt", "pwd_hash"),
        "为什么": "同 account —— 员工账号也是一账户一盐。"
                  "⚠️ 这条是**第二次比对才补上的**:第一次只登记了 account,"
                  "而 staff 的盐在同一次重建里也在变。"
                  "**「同一类问题有几处」这件事,一处一处修是看不出来的**",
    },
    "op_log": {
        "列": ("ts",),
        "为什么": "操作台账记的是「这条操作**实际发生**的时刻」,"
                  "而造库时那个时刻就是造库的时刻。"
                  "把它钉成假时间,台账就不再是台账了",
    },
}


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
    import hashlib
    A, B = (sqlite3.connect(x) for x in 快照)
    表 = [r[0] for r in A.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    def 指纹(c, t, 跳过=()):
        """逐行算摘要。

        ⚠️ **别用 `quote(t.*)`** —— 那不是合法的 SQLite 语法,一跑就
        `near "*": syntax error`。这一段原来就是那么写的,于是
        `--真建两次` **一次都没成功跑起来过**:它既没红过也没绿过,只是抛异常,
        而它被标着「手动跑」,所以没人发现。2026-09-21 真去跑的时候才知道。

        > 那天它要是能跑,`seed.py` 里那个 `abs(hash(sku编码))`
        > (每重建一次 659 个 SKU 的供应商编码全换一批)**早就被抓到了**。

        代价:逐行读比 SQL 聚合慢。但这条本来就是「手动跑、约两分钟」的那一类,
        **慢一点换它真的能跑**,划算。
        """
        列 = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        取 = [i for i, x in enumerate(列) if x not in 跳过]
        h = hashlib.sha256()
        n = 0
        for row in c.execute(f'SELECT * FROM "{t}"'):
            h.update(repr(tuple(row[i] for i in 取)).encode())
            n += 1
        return n, h.hexdigest()[:16]

    差, 比过, 放过 = [], 0, []
    for t in 表:
        if t == "truth":
            continue
        # **登记过的豁免**:这几列按设计每次重建都该不一样。
        # 写成显式登记而不是「差异少就忽略」—— 后者会把新冒出来的漂移一起放过。
        免 = 每次都该变.get(t)
        if 免:
            放过.append(f"{t}.{'/'.join(免['列'])}")
        try:
            na, ha = 指纹(A, t, 免["列"] if 免 else ())
            nb, hb = 指纹(B, t, 免["列"] if 免 else ())
        except sqlite3.Error as e:
            差.append(f"{t}:读不了({e})")
            continue
        比过 += 1
        if na != nb:
            差.append(f"{t}:行数 {na} vs {nb}")
        elif ha != hb:
            差.append(f"{t}:行数一样({na})而内容不同 —— **总数相同最容易掩盖内容不同**")
    # 先报样本量:一张表都没比到时,「全一致」是空话
    报("真的比到了表", 比过 >= 20, f"{比过} 张表逐行比过")
    报("两次重建逐表一致", not 差, "；".join(差[:4]) if 差 else
       f"{比过} 张表全一致(其中 {len(放过)} 张跳过了登记在案的列)")
    # **豁免要一直看得见。** 一条没人再看的豁免和一个没修的 bug 长得一样。
    for t, 免 in sorted(每次都该变.items()):
        print(f"     ℹ️ 跳过 {t}.{'/'.join(免['列'])} —— {免['为什么']}")
    多余 = [t for t in 每次都该变 if t not in 表]
    报("登记的豁免都还指着存在的表", not 多余,
       "、".join(多余) + " —— 表没了,这条登记该删" if 多余 else
       f"{len(每次都该变)} 条登记都对得上")


def main():
    扫()
    if "--真建两次" in sys.argv:
        真建两次()
    print((f"{R}❌ 重建可复现 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 重建可复现{D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
