#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨进程 / 跨日期可复现 —— **同一份方案,换台机器换一天跑,数据必须一模一样。**

    python3 fakedata/repro.py

## 为什么已有的「同种子两次一致」不够

工厂自测里有这么一条:

    a1, _ = G.generate(pl, conn); a2, _ = G.generate(pl, conn)
    ck(all(a1[t] == a2[t] for t in a1), "同种子两次生成完全一致")

它在**同一个进程、同一天**里跑两遍。而有两类不确定性,在这个条件下
**必然答对** —— 也就是说这条检查问了一个它不可能答错的问题:

| 不确定性 | 为什么同进程同天抓不到 |
|---|---|
| `hash()` / `set` 遍历顺序 | 一个进程里 `PYTHONHASHSEED` 是固定的,两遍当然一样 |
| `date.today()` | 同一天跑两遍,今天当然等于今天 |

第二类**当场抓到了一个真的**:`gen._dt` 里 `hi = hi or datetime.date.today()`,
同一个种子今天造的和明天造的**所有日期整体差一天**。工厂宣称「做一次,跑一万次」,
而那一万次里只要跨了一个午夜,数据就不是那批了。

第一类在澜绣云裳真出过事:商品颜色按 `hash(款号)` 取,而 `str` 的哈希
**每个进程都不一样** —— 换个终端跑一次 seed,颜色就换一批。

> **「两次一致」这句话本身不够,要问清楚是哪两次。**
> 同进程同天的两次,和跨进程跨天的两次,验的是完全不同的东西。

## 怎么问

起三个子进程,各自读**同一份方案文件**造一遍,打指纹比:

    A  PYTHONHASHSEED=0      真实日期
    B  PYTHONHASHSEED=12345  真实日期      ← 和 A 比,问的是哈希种子
    C  PYTHONHASHSEED=0      日期改成 2099 ← 和 A 比,问的是机器时钟

三个指纹必须相同。`--看细节` 会把第一处不同的表和列打出来。
"""
import hashlib, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"

# ⚠️ 每条破坏点后面写的是**实测红的那一条**,不是我预期它红的那一条。
# 头两条都是「扫描看不见的写法」——直接写 `date.today()` 会被扫写法那条先抓住,
# 于是实测那两条**永远没被咬过**,而没咬过的检查和守得住的检查长得一模一样。
咬合 = [
    ('把 `_dt` 的 `_锚日()` 换成 `getattr(datetime.date, "to"+"day")()`(扫描看不见)',
     "换一天跑,数据一样"),
    ('让某个取值走 `next(iter({"甲","乙","丙"}))`(集合遍历序,扫描看不见)',
     "换个进程跑,数据一样"),
    ("把 `_dt` 直接改回 `hi = hi or datetime.date.today()`",
     "造数据的路上不取机器时间"),
    ("把去掉日期列上界那几行删掉(实测那条就没东西可看了)",
     "这条检查有东西可看:有一列日期没有上界"),
]

# 行末写上它 = 这一行确实要用真实时钟,并且**写清为什么**。
# 豁免不是关掉检查:每次跑都会把豁免了哪几行打出来,让它保持可见。
豁免标记 = "# 真实时钟:"

# 造数据这条路上的模块。**写明白,别扫整个目录** ——
# 报告生成器(diffreport)、回滚凭据(guard)里的 `now()` 是正当的时间戳,
# 把它们一起报出来,人就会开始忽略这条检查(见 samekey_check:
# 「一个会误报的检查,比没有这个检查更糟」)。
造数据的 = ["gen.py", "plan.py", "load.py", "schema.py", "discover.py"]


# ── 子进程干的活 ────────────────────────────────────────────────────
def _子进程(方案路径, 库路径, 假日期=None):
    sys.path.insert(0, HERE)
    if 假日期:
        import datetime
        真 = datetime.date

        class _假(真):
            @classmethod
            def today(cls):
                return cls(*[int(x) for x in 假日期.split("-")])
        # 打的是 `datetime` 这个**模块对象**上的属性,而 gen / plan 都是
        # `import datetime` 之后再 `datetime.date.today()` —— 它们看到的是同一个对象。
        # (如果哪天有人改成 `from datetime import date`,这个桩就打不着它了,
        #  那时这条检查会静默变瞎 —— 所以下面还有一条扫写法的,两条一起才拦得住。)
        datetime.date = _假
    import schema as S, gen as GEN
    plan = json.load(open(方案路径, encoding="utf-8"))
    conn = S.connect(库路径)
    made, _ = GEN.generate(plan, conn)
    出 = {t: [[f"{k}={v!r}" for k, v in sorted(r.items())] for r in rows]
          for t, rows in made.items()}
    s = json.dumps(出, ensure_ascii=False, sort_keys=True)
    print(json.dumps({"指纹": hashlib.sha256(s.encode()).hexdigest()[:16], "数据": 出},
                     ensure_ascii=False))


def 跑一次(方案路径, 库路径, hashseed, 假日期=None):
    env = dict(os.environ, PYTHONHASHSEED=str(hashseed), PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, os.path.abspath(__file__), "--子进程", 方案路径, 库路径]
    if 假日期:
        cmd += ["--假日期", 假日期]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode:
        raise SystemExit(f"❌ 子进程挂了(hashseed={hashseed}):\n{r.stderr[-800:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── 扫写法 ──────────────────────────────────────────────────────────
def 扫():
    """扫的是**写法**,不是结果。

    跑三个子进程抓得到「这一次确实不一致」,抓不到「这一次碰巧一致」——
    `hash()` 只有在取值真的用到它时才会翻车,一条没走到的分支是沉默的。
    所以两条一起:实测抓现行,扫写法抓潜伏。
    """
    import re
    坏时钟, 坏哈希, 放行 = [], [], []
    for f in 造数据的:
        p = os.path.join(HERE, f)
        if not os.path.isfile(p):
            continue
        码 = _剥文档字符串(open(p, encoding="utf-8").read())
        for i, l in enumerate(码.splitlines(), 1):
            if l.lstrip().startswith("#"):
                continue
            if 豁免标记 in l:
                放行.append(f"{f}:{i} {l.strip()[:70]}")
                continue
            if re.search(r"date\.today\(\)|datetime\.now\(\)", l):
                坏时钟.append(f"{f}:{i}")
            # 内置 hash() 和 .__hash__():**每个进程给的值都不一样**
            if re.search(r"(?<![\w.])hash\(|\.__hash__\(", l):
                坏哈希.append(f"{f}:{i}")
    return 坏时钟, 坏哈希, 放行


def _剥文档字符串(src):
    """只清掉 docstring,别的原样留着。

    ⚠️ 用正则剥三引号会**连 SQL 一起剥**(查询语句也写在三引号里),
    检查会当场变瞎而且照样报绿 —— `tools/determinism_check.py` 栽过,咬合抓到的。
    """
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    行 = src.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        一 = body[0]
        if isinstance(一, ast.Expr) and isinstance(一.value, ast.Constant) \
           and isinstance(一.value.value, str):
            for i in range(一.lineno - 1, (一.end_lineno or 一.lineno)):
                if i < len(行):
                    行[i] = ""
    return "\n".join(行)


# ── 主流程 ──────────────────────────────────────────────────────────
def 第一处不同(a, b):
    for t in sorted(a):
        ra, rb = a.get(t) or [], b.get(t) or []
        if len(ra) != len(rb):
            return f"{t}:行数 {len(ra)} vs {len(rb)}"
        for i, (x, y) in enumerate(zip(ra, rb)):
            if x != y:
                差 = [p for p, q in zip(x, y) if p != q]
                return f"{t} 第 {i+1} 行:{'、'.join(差[:3])}  ←→  " \
                       f"{'、'.join([q for p, q in zip(x, y) if p != q][:3])}"
    return "(数据一样,只有指纹不同?那是打指纹的方式有问题)"


def main():
    失败 = []

    def ck(ok, 名, 说明=""):
        print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
        if not ok:
            失败.append(名)

    print("跨进程 / 跨日期可复现")
    sys.path.insert(0, HERE)
    import selftest as ST, schema as S, discover as DI, plan as P

    d = tempfile.mkdtemp()
    db = os.path.join(d, "known.db")
    ST.build_known_db(db)
    conn = S.connect(db)
    pl = P.build(DI.discover(conn, conn.reflect()), scale=1.0)

    # ⚠️ **必须先把某个日期列的上界拿掉,这条检查才看得见东西。**
    # 靶子库里每个日期列都量到了取值范围,于是 `_dt` 永远拿到显式的 hi,
    # 那句取「今天」的兜底**一次都执行不到** —— 第一版咬合当场证明了这点:
    # 把 `_锚日()` 改回 `date.today()`,实测那条照样绿(扫写法那条红了)。
    #
    # 「没红」既可能是守住了、也可能是它瞎了,而这两种长得一模一样。
    # 所以这里主动造出那条路:真实用法里它也会出现 ——
    # 新表、空表、或者状态机给时间戳挑起点时,都没有范围可量。
    去了上界 = None
    for t, tp in pl["tables"].items():
        for c, g in tp["columns"].items():
            if g.get("gen") in ("date", "datetime") and (g.get("range") or {}).get("max"):
                g["range"] = {}
                去了上界 = f"{t}.{c}"
                break
        if 去了上界:
            break

    方案 = os.path.join(d, "plan.json")
    json.dump(pl, open(方案, "w", encoding="utf-8"), ensure_ascii=False)

    A = 跑一次(方案, db, 0)
    B = 跑一次(方案, db, 12345)
    C = 跑一次(方案, db, 0, 假日期="2099-01-01")

    n行 = sum(len(v) for v in A["数据"].values())
    # 先报样本量:空集合上所有性质都成立
    ck(n行 >= 50, "样本量:比对的行数", f"{n行} 行 / {len(A['数据'])} 张表")

    ck(A["指纹"] == B["指纹"], "换个进程跑,数据一样",
       (第一处不同(A["数据"], B["数据"]) +
        " —— **哈希种子换了就变**:取值里用到了 hash() 或 set 的遍历顺序")
       if A["指纹"] != B["指纹"] else f"两个 PYTHONHASHSEED,指纹都是 {A['指纹']}")

    ck(bool(去了上界), "这条检查有东西可看:有一列日期没有上界",
       f"{去了上界} —— 它会走到「取今天」那条兜底,机器时钟一动它就动"
       if 去了上界 else "**一列都没有**:那么下面那条「换一天跑」是瞎的,不是绿的")
    ck(A["指纹"] == C["指纹"], "换一天跑,数据一样",
       (第一处不同(A["数据"], C["数据"]) +
        " —— **拿了机器的今天**:这批数据每过一天就换一次,"
        "而方案文件上看不出任何变化")
       if A["指纹"] != C["指纹"] else "把机器的日期改到 2099 年,造出来的还是那批")

    坏时钟, 坏哈希, 放行 = 扫()
    ck(True, "扫到的模块", "、".join(造数据的))
    ck(not 坏时钟, "造数据的路上不取机器时间", "、".join(坏时钟[:5]) if 坏时钟 else
       "日期上界取自方案里钉住的「今天」")
    ck(not 坏哈希, "造数据的路上不用内置 hash()", "、".join(坏哈希[:5]) if 坏哈希 else
       "取值一律走 rng_for 的字符串播种(它是稳的,内置 hash() 不是)")
    if 放行:
        print(f"     ℹ️ 豁免 {len(放行)} 行(写明了为什么要用真实时钟):")
        for x in 放行:
            print(f"        {x}")

    print((f"{R}❌ 可复现 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 跨进程 / 跨日期都可复现{D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    if "--子进程" in sys.argv:
        i = sys.argv.index("--子进程")
        假 = sys.argv[sys.argv.index("--假日期") + 1] if "--假日期" in sys.argv else None
        _子进程(sys.argv[i + 1], sys.argv[i + 2], 假)
    else:
        sys.exit(main())
