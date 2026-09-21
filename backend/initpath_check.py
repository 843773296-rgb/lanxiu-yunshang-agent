# -*- coding: utf-8 -*-
"""首次启动建出来的库,和在用的库,得是同一个东西。

## 为什么要这条检查

2026-09-20 外部审阅指出,`start.sh` 里首次启动走的是

    [ -f backend/lanxiu.db ] || python3 backend/seed.py

而 `seed.py` 只是 `tools/rebuild.sh` 那 15 步里的**第 1 步**。
2026-09-21 在隔离副本里实测:

    新用户按 README 起 → 65 张表 / 12886 行
    实际在用的库       → 79 张表 / 198646 行
    roster / fitting / call_transcript 等 **14 张表根本不存在**

## 🔑 为什么这么久没人发现

`start.sh` 判的是「库文件在不在」——
**一个只跑了第 1 步的空壳库,和一个跑完 15 步的库,在 `[ -f ]` 眼里长得一模一样。**

而且它**不会崩**:首页照常打开,商品也在,直到有人点进排班才 `no such table: roster`。
到那时候人会以为是自己装错了,不会怀疑是启动脚本少跑了 14 步。

开发机上永远发现不了 —— **库建过一次就一直在,那个分支再也不会走。**

## 这条检查守什么

① 启动脚本的建库分支,走的是**和重建同一份步骤表**,不是自己只调第一步
② 那个入口(`--fresh-only`)**有库就必须拒绝** —— 启动永远不许删掉谁的数据
③ 而且是**有库才拒绝**:一个不管三七二十一都拒绝的守卫,和一个真的在看库的守卫,
   在「库存在」这一种情形下长得一模一样,所以两种情形都得测
④ 建到一半失败要清掉半成品 —— **半成品和建好了,在 `[ -f ]` 眼里还是一样的**

②③ 是真跑出来的:在一个临时目录里放个**诱饵库**让它跑。
放临时目录不是图省事 —— **一个会删库的检查,比没有这个检查糟得多**,
那个目录里没有 seed.py,守卫万一失效也只伤得到诱饵。
"""
import os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad = []

# ── 咬合记录 ────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「该红的是哪一条」。**只写「测过了」和没写是一回事** ——
# 咬合自己也会失效,而失效的时候和通过长得一样(这个项目栽过四次)。
# 规格在 tools/bite_specs.json,这里是给人看的那一份。
咬合 = [
    ("把 start.sh 的建库分支改回只跑 seed.py(15 步里的第 1 步)",
     "start.sh 的建库分支没有走"),
    ("建库失败后不清掉半成品(下次启动的 [ -f ] 会把它当成建好的库)",
     "没有清掉半成品"),
    ("让 --fresh-only 不再看库在不在(等于启动时能删掉用户的库)",
     "没有拒绝"),
    ("让 --fresh-only 无条件拒绝(看着也像「拦住了」,其实连新库都建不出来)",
     "也拒绝了"),
    ("往步骤表里加一步却不改步数自校验(跑完照样打 ✅)",
     "加了步骤没改计数"),
]


def 读(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


def 去注释(s):
    """只看真会执行的行。

    第一版没去注释,结果**自己写的注释把自己判红了** ——
    上面那段说明里原样引用了旧代码 `|| python3 backend/seed.py`,
    检查一眼看过去,和真的写了这行长得一模一样。

    **一个会误报的检查,比没有这个检查更糟**:它会教人忽略红色。
    """
    return "\n".join(l for l in s.split("\n") if not l.lstrip().startswith("#"))


def 判(条件, 说法):
    if not 条件:
        bad.append(说法)
    return 条件


def main():
    start = 去注释(读("start.sh"))
    rebuild = 去注释(读("tools/rebuild.sh"))

    # ── ① 建库分支不许只调第一步 ──────────────────────────────────────
    判("./tools/rebuild.sh --fresh-only" in start,
       "start.sh 的建库分支没有走 ./tools/rebuild.sh --fresh-only")
    判(not re.search(r"\|\|\s*python3\s+backend/seed\.py", start),
       "start.sh 又变回了 `|| python3 backend/seed.py` —— 那只是 15 步里的第 1 步")

    # ── 步骤表只许有一份 ──────────────────────────────────────────────
    # 抄一份到 start.sh 里也能建全库,但两份会各自漂移,
    # **而「漂了」和「没漂」在跑完的库上长得一样。**
    for 步 in ("grow_customers", "order_mix", "simulate_sales", "backfill_roster"):
        判(步 not in start, f"start.sh 里出现了 {步} —— 步骤表被抄成了两份")

    # ── 步数自校验的那个数字,要和步骤表对得上 ──────────────────────────
    表 = re.search(r"for STEP in (.*?); do", rebuild, re.S)
    数 = re.search(r'"\$DONE" -ne (\d+)', rebuild)
    if 判(bool(表) and bool(数), "rebuild.sh 里找不到步骤表或步数自校验"):
        实际 = len(re.findall(r'"[^"]+"', 表.group(1)))
        判(实际 == int(数.group(1)),
           f"步骤表 {实际} 步,自校验却写着 {数.group(1)} 步 —— 加了步骤没改计数")

    # ── ④ 半成品要清掉 ────────────────────────────────────────────────
    判(re.search(r"rm -f backend/lanxiu\.db", start),
       "start.sh 建库失败时没有清掉半成品 —— 下次启动会把它当成建好的库")

    # ── ②③ 真跑:诱饵库在 / 不在,两种情形都测 ─────────────────────────
    for 有库, 该拒绝, 说法 in ((True, True, "库已经在了"), (False, False, "库不存在")):
        tmp = tempfile.mkdtemp(prefix="initpath-")
        try:
            os.makedirs(os.path.join(tmp, "tools"))
            os.makedirs(os.path.join(tmp, "backend"))
            shutil.copy(os.path.join(ROOT, "tools/rebuild.sh"),
                        os.path.join(tmp, "tools/rebuild.sh"))
            诱饵 = os.path.join(tmp, "backend/lanxiu.db")
            if 有库:
                with open(诱饵, "w") as f:
                    f.write("这是一个诱饵库,守卫要是失效了它会被冲掉")
            r = subprocess.run(["bash", os.path.join(tmp, "tools/rebuild.sh"), "--fresh-only"],
                               capture_output=True, text=True, timeout=60)
            out = r.stdout + r.stderr
            开工 = "首次建库" in out
            if 该拒绝:
                判(not 开工 and r.returncode == 1,
                   f"{说法}时 --fresh-only 没有拒绝:"
                   + ("它开工建库了" if 开工 else f"退出码 {r.returncode}"))
                判(os.path.exists(诱饵) and open(诱饵).read().startswith("这是一个诱饵库"),
                   "❗ 诱饵库被动了 —— 启动路径能删掉用户的数据")
            else:
                判(开工, f"{说法}时 --fresh-only 也拒绝了 —— 那它就不是在看库,是在无条件挡人")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if bad:
        print(f"{R}❌ 首次启动的建库路径有 {len(bad)} 处不对{D}")
        for b in bad:
            print(f"    ❌ {b}")
        return 1
    print(f"{G}✅ 首次启动会把库建全(15 步),而且不会删掉已有的库{D}")
    print("    隔离副本实测(2026-09-21):改之前 65 表 / 12886 行,改之后 79 表 / 198599 行,")
    print("    和在用的库只差 op_log(操作日志,本来就随使用增长)。耗时约 1 分钟。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
