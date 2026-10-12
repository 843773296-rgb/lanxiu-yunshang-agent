#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""种子里的随机流不许串台 —— **往花名册里加一个人,只许改 `staff` 那一张表**。

    python3 backend/seed_rng_check.py

## 为什么要有这条

2026-10-11 给 `STAFF` 加了一行售后(`60000022 闻砚之`)。CI 从零建库之后,
**两条和员工毫无关系的判据当场红了**:销量榜的夹具形状、上新卡片的购买推断绑定。

根子是插员工那个循环里的两个 `random.randint` 抽的是**全局那条随机流** ——
每行抽 2 次,多一行就多抽 2 次,于是那之后的**每一次抽样都整体挪一格**。
隔离副本上实测(38 人 vs 39 人,只差那一行):

    account · customer · points_log · schedule · sku · sqlite_sequence · staff · stock_log
    八张表全变,`points_log` 连行数都从 268 变成 269

而订单和订单明细一个字没动 —— 因为它们在插员工**之前**生成。
**于是「改了什么」和「什么变了」在表上完全对不上**,红的地方指不回真因。

> **固定种子保证的是「同一串抽样序列」,不是「同一批数据」。**
> 在种子脚本中间插一行,那之后的数据整体挪位,
> 而两版数据在「它是确定性生成的」这个事实上长得一模一样。

⚠️ **本地一点征兆都没有。** 本地库是增量长出来的(那天只单跑了一个回填补入职日期),
从来没从零建过;CI 每次从零。**这个改动的真实后果只在 CI 里现形** ——
和「本地建过就一直在」是同一个形状。

## 和 `tools/determinism_check.py` 不是一条

那条问的是「**同一份代码建两次,数据一样吗**」(不可复现)。
这条问的是「**改一处,只有该变的变了吗**」(串台)——
这次的数据**完全可复现**,每次建都一样,所以那条一个字都不会报。

## 怎么验的

扰动法:往 `STAFF` 末尾塞一个人,建两次库,逐表比。

两件事必须一起成立,少一件这条检查就是空跑:
  · **扰动真的落进去了** —— `staff` 必须刚好多那一行(不验这个,正则没匹配上时
    两份库一模一样,检查会**以通过收场**)
  · 除 `staff` 之外**没有一张表变**

⚠️ **盐按列排除,不是整张表豁免。** `secrets.token_hex` 不走种子(密码盐必须真随机),
所以 `staff.pwd_salt/pwd_hash` 和 `account.pwd_salt/pwd_hash` 在任何两次建库之间都不同。
整张表豁免的话,`account` 那 17 列业务字段就再也没人盯了。
"""
import hashlib, os, re, shutil, sqlite3, subprocess, sys, tempfile

# 咬合记录(规格在 tools/bite_specs.json,`python3 tools/bite_run.py --only seed_rng_check` 重放)
咬合 = [
    ("把花名册那两个随机数改回抽全局那条流(`random.randint` 而不是 `花名册时间.randint`)",
     "种子里的随机流串台了"),
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# 盐和它派生的哈希不受种子管(`secrets.token_hex`)—— 按列排除,不豁免整张表。
盐列 = {"pwd_salt", "pwd_hash"}
# 塞进去的那个人。工号挑一个**现实里不会用**的,免得和真花名册撞。
诱饵工号 = "60009999"
诱饵行 = f'    ("{诱饵工号}", "随机流诱饵", "顾问",   "SH001",            "A99", "启用"),\n'


def 搭副本(目标, 加人):
    """把仓库软链进一个临时目录,只有 `backend/seed.py` 是实体副本。

    整仓拷一份要几百兆;软链之后 `seed.py` 的 `HERE` 还是指向临时目录
    (`abspath` 不解软链),所以库会建在副本里,**真工作区那份一个字节都不会动**。
    """
    os.makedirs(目标, exist_ok=True)
    for 名 in os.listdir(ROOT):
        if 名 in (".git", "backend"):
            continue
        os.symlink(os.path.join(ROOT, 名), os.path.join(目标, 名))
    bk = os.path.join(目标, "backend")
    os.makedirs(bk)
    for 名 in os.listdir(os.path.join(ROOT, "backend")):
        if 名 in ("seed.py", "lanxiu.db", "__pycache__") or 名.startswith("lanxiu.db"):
            continue
        os.symlink(os.path.join(ROOT, "backend", 名), os.path.join(bk, 名))

    src = open(os.path.join(ROOT, "backend", "seed.py"), encoding="utf-8").read()
    if 加人:
        m = re.search(r"^STAFF = \[.*?^\]\n", src, re.S | re.M)
        if not m:
            raise SystemExit("❌ 在 seed.py 里找不到 STAFF 那个列表 —— "
                             "**扰动放不进去,这条检查就不许假装验过了**")
        src = src[:m.end() - 2] + 诱饵行 + src[m.end() - 2:]
    open(os.path.join(bk, "seed.py"), "w", encoding="utf-8").write(src)
    return bk


def 建(bk):
    环境 = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.join(bk, "seed.py")],
                       capture_output=True, text=True, timeout=300, env=环境, cwd=bk)
    if r.returncode != 0:
        raise SystemExit(f"❌ 副本里建库失败(退出码 {r.returncode}):\n"
                         + (r.stdout + r.stderr)[-1500:])
    return os.path.join(bk, "lanxiu.db")


def 指纹(库):
    """每张表一个指纹,盐那两列先去掉。"""
    c = sqlite3.connect(库)
    出 = {}
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        列 = [r[1] for r in c.execute(f"PRAGMA table_info([{t}])")]
        留 = [x for x in 列 if x not in 盐列]
        if not 留:
            continue
        表达 = ",".join(f"[{x}]" for x in 留)
        行 = sorted(repr(r) for r in c.execute(f"SELECT {表达} FROM [{t}]"))
        出[t] = (len(行), hashlib.md5(repr(行).encode()).hexdigest(), 行)
    c.close()
    return 出


def main():
    工棚 = tempfile.mkdtemp(prefix="seedrng-")
    try:
        甲 = 指纹(建(搭副本(os.path.join(工棚, "甲"), 加人=False)))
        乙 = 指纹(建(搭副本(os.path.join(工棚, "乙"), 加人=True)))
    finally:
        shutil.rmtree(工棚, ignore_errors=True)

    bad = []

    # ── ① 扰动真的落进去了吗 ──────────────────────────────────────────
    # 不验这一条,正则漏了的时候两份库一模一样,下面全绿 —— 而什么都没验。
    甲员工, 乙员工 = set(甲["staff"][2]), set(乙["staff"][2])
    多出来 = 乙员工 - 甲员工
    少掉的 = 甲员工 - 乙员工
    if len(多出来) != 1 or 少掉的:
        bad.append(f"扰动没落到位:乙比甲多 {len(多出来)} 行、少 {len(少掉的)} 行 —— "
                   f"应该刚好多 1 行、少 0 行。**这条检查现在什么都没验**")
    elif 诱饵工号 not in next(iter(多出来)):
        bad.append(f"多出来的那行不是诱饵({诱饵工号}):{next(iter(多出来))[:80]}")

    # ── ② 除 staff 之外,一张表都不许动 ───────────────────────────────
    串台 = []
    for t in sorted(set(甲) | set(乙)):
        if t in ("staff", "sqlite_sequence"):
            continue      # staff 本来就该变;sqlite_sequence 跟着 staff 的自增走
        a, b = 甲.get(t), 乙.get(t)
        if a is None or b is None:
            串台.append(f"{t}(只有一边有这张表)")
        elif a[:2] != b[:2]:
            串台.append(f"{t}(甲 {a[0]} 行/{a[1][:8]} ≠ 乙 {b[0]} 行/{b[1][:8]})")
    if 串台:
        bad.append("加一个员工动了 %d 张**和员工无关**的表 —— 种子里的随机流串台了:\n       "
                   % len(串台) + "\n       ".join(串台)
                   + "\n       → 造数据的那一段要用自己的 `random.Random(...)`,别抽全局那条流")

    # ── ③ 样本量:空集合上什么都成立 ──────────────────────────────────
    比了 = len([t for t in 甲 if t not in ("staff", "sqlite_sequence")])
    if 比了 < 50:
        bad.append(f"只比了 {比了} 张表(应该 50 张以上)—— 是没扫到东西,不是都通过")

    if bad:
        print(f"{R}❌ 种子的随机流有 {len(bad)} 处不对{D}")
        for b in bad:
            print(f"    {R}❌{D} {b}")
        return 1
    print(f"{G}✅ 加一个员工只改了 staff 那一张表(逐表比了 {比了} 张){D}")
    print(f"    {Y}⚠️ 盐和哈希那两列按**列**排除(secrets 不走种子)—— "
          f"不是整张表豁免,account 的业务字段照验{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
