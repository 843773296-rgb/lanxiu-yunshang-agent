#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""切库要切得动 —— 库路径不许当默认参数值。

## 这条判据是补票买的(2026-11-03,当天刚丢过数据)

并行会话想在**库副本**上重造评价,于是改了造数模块的库路径变量指向副本。
它写进了**真库**:`rating` 1319 → 1264 条,55 条评价没了,
而且丢的那一刻另一个会话正在跑全量门禁,那一轮结果整个作废。

病理是一行 Python 语义:

    DB = os.path.join(ROOT, "backend", "lanxiu.db")   # 模块级
    def 铺(db=DB, 说=print):                           # ← 默认值在 def 执行时就算定了
        c = 连库(db)                                   # ← 连的是参数,不是 DB
    ...
    造数模块.DB = 副本                                 # ← 改不动上面那个 db
    造数模块.铺()                                      # ← 写真库

> 一个「改了库路径变量就会跟着走的写口」,
> 和一个「在 def 那一刻就把当时的库捏在手里的写口」,
> **在 `模块.DB = 副本` 这一行上长得一模一样。**

改法(运行时现取):

    def 铺(db=None, 说=print):
        db = db or DB

## 这条判据和项目里那条老规矩是同一个病的两个形状

老规矩写的是「检查切库前先 import 写口 —— 用副本只改已加载模块的库路径;
之后才 import 的写口会写真库,切完要断言已指副本」。那条管的是 **import 顺序**,
这条管的是 **默认参数绑定**。共同点都是「我改了那个变量,以为写口会跟着走」。

## 为什么判「参数被拿去连库」,不判「变量名叫 DB」

名字靠不住:`tools/order_mix.py` 那个参数叫 `path`。所以顺着数据流走:
**函数体里真的把这个参数拿去连库了,它就是库路径** —— 不管它叫什么。

⚠️ **第一版判据抓不到那次真实故障点,而它看起来在干活。**
第一版找的是「模块级变量直接被拿去连库」(`连库(DB)`),命中 13 处;
而真实代码是 `连库(db)`,`db` 是参数,只有**默认值**才是那个模块级变量 ——
于是出事的那个函数**不在那 13 处里**。
> 一条抓不到那次真实翻车的判据,和一条守住了的判据,
> **在「命中 13 处、看起来在干活」上长得一模一样。**
逮到它的办法是量完之后去核对「那次真实故障点在不在命中列表里」。
**不在 ≠ 已经修好了。** 所以下面 ③ 那一条自检把这件事钉死了。

## 棘轮:现存的登记成欠债,只许少不许多

挂判据那天有 24 处,**不一次改完**:多数是只读查询(改了要逐个验),
而且 `tools/shift_world.py` 当时正在另一个会话手上改 —— 一次性批量改
必然撞车。所以现存的进欠债表、不拦门禁;**新增的红**;
**修好的必须从欠债表删掉**(不删也红,逼人清理 —— 否则欠债表会攒满早就修好的条目,
而囤积的豁免和真豁免长得一模一样)。

欠债表的键用「文件 + 函数名 + 参数名」,**不用行号**:插一行注释行号就全乱了。

## 这条判据**不**验什么(说清楚比假装覆盖好)

· 不验「写之前有没有断言连上的文件是哪个」—— 那要查「有没有调某个函数」,
  是枚举,而且「写了断言」不等于「断言对了」;
· 不验 `模块.DB = X` 这种切库写法本身对不对 —— 切库是正当操作,
  这条只保证切了之后写口**跟得上**;
· 不验运行时真的连上了哪个文件 —— 那要在连库那一刻取 `PRAGMA database_list`,
  不是扫源码扫得出来的。
  ⚠️ **这一条 2026-11-04 补上了,补在别处**:`backend/check_copy_check.py`。
  做法不是「每个写口自己加一句断言」(那就是上面那条说的枚举,而且一个每次都要
  记得加的安全参数等于没有这道防护),是把断言装进那个**唯一的切库口**
  `backend/check_copy.py::用副本` —— 换完模块变量还换**烤死在默认参数里**的那些,
  换完断言两类都不指真库。23 条走「用副本」的检查免费拿到。
  > 一份过期的「不验什么」比没有这段话更糟:它会让人以为这件事已经想清楚了,
  > 而想清楚的结论当时是「验不了」。
"""
import ast
import glob
import io
import os
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# 连库那个调用长什么样 —— 拆成两段,**不写成完整的匹配串**
# (这个文件自己会被别的判据扫,写全了它就命中自己。)
_模块, _函数 = "sqlite3", "connect"

扫哪些 = ("backend/*.py", "agentsite/*.py", "knowledge/*.py", "tools/*.py",
          "agent/*.py", "fakedata/*.py", "tests/**/*.py", "管理后台/**/*.py")

# ── 欠债表(2026-11-03 挂判据那天的现存 24 处)──────────────────────────
# 键 = (相对路径, 函数名, 参数名)。**只许少不许多。**
# 修好一处就把那一行删掉 —— 不删的话下面 ② 会红。
欠债 = {
    ("backend/credit.py", "记一笔", "db"),
    ("backend/credit.py", "收入分成对不对", "db"),
    ("backend/credit.py", "一单的贡献", "db"),
    ("backend/ownership.py", "明细", "db"),
    ("backend/ownership.py", "待确立", "db"),
    ("backend/ownership.py", "记一笔", "db"),
    ("backend/roster.py", "查排班事实", "db"),
    ("backend/roster.py", "一周排了吗", "db"),
    ("backend/roster.py", "能排班吗", "db"),
    ("backend/roster.py", "点名的人没空", "db"),
    ("backend/roster.py", "预留", "db"),
    ("backend/roster.py", "时段被预留了吗", "db"),
    ("backend/simplified.py", "扫库", "db"),
    ("backend/touchpoint.py", "_rows", "db"),
    ("tools/backfill_opportunity.py", "main", "db"),
    ("tools/backfill_rating.py", "只登记", "db"),
    ("tools/backfill_rating.py", "取行集指纹", "db"),
    ("tools/backfill_rating.py", "铺", "db"),
    ("tools/backfill_terms.py", "main", "db"),
    ("tools/clamp_future_done.py", "修", "db"),
    ("tools/clamp_future_done.py", "名字里的年月", "db"),
    ("tools/order_mix.py", "conn", "path"),
    ("tools/realign_report_periods.py", "改", "db"),
    ("tools/shift_world.py", "平移", "db"),
}

# ⚠️ 那次真实翻车的那一处 —— ③ 的自检拿它当试纸。
# 它**现在在欠债表里**(没改代码,只挂了判据),所以这里要的是
# 「判据扫得到它」,不是「它不命中」。
真实故障点 = ("tools/backfill_rating.py", "铺", "db")


def 被拿去连库的名(fn):
    """函数体里 连库(X) 的裸名 X —— **不管它叫 db 还是 path**。"""
    出 = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == _函数 and isinstance(n.func.value, ast.Name)
                and n.func.value.id == _模块 and n.args
                and isinstance(n.args[0], ast.Name)):
            出.add(n.args[0].id)
    return 出


def 带默认值的参数(fn):
    """{参数名: 默认值节点}。⚠️ 位置参数的默认值**靠右对齐**,别错位。"""
    a, 出 = fn.args, {}
    位 = [p.arg for p in (getattr(a, "posonlyargs", []) or []) + a.args]
    ds = list(a.defaults)
    if ds:
        for 名, d in zip(位[len(位) - len(ds):], ds):
            出[名] = d
    for p, d in zip(a.kwonlyargs, a.kw_defaults):
        if d is not None:
            出[p.arg] = d
    return 出


def 扫一遍():
    """→ (命中集合, 扫过的文件数, 拿裸名连过库的函数数, 解析不了的)"""
    命中, 文件数, 连过库的函数, 解析不了 = set(), 0, 0, []
    文件们 = []
    for p in 扫哪些:
        文件们 += glob.glob(os.path.join(ROOT, p), recursive=True)
    for f in sorted(set(文件们)):
        try:
            # ⚠️ 局部按下 SyntaxWarning(某些源文件里有 `\\)` 这类坏转义)。
            # 按下的理由不是「不想看见」,是 **ast.parse 的警告报不出是哪个文件** ——
            # 它印的来源名就是 `<unknown>`,留在门禁输出里只会让人去找一个找不到的东西。
            # 真正该管转义的是别的判据;这里**解析失败照旧往下报**(见 except)。
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                树 = ast.parse(io.open(f, encoding="utf-8").read())
        except (OSError, SyntaxError) as e:
            解析不了.append(f"{os.path.relpath(f, ROOT)}:{type(e).__name__}")
            continue
        文件数 += 1
        # 模块级赋的名字(只认顶层;函数内的局部赋值不算 —— 那种改不着)
        顶层名 = {t.id for n in 树.body if isinstance(n, ast.Assign)
                  for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(树):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            连 = 被拿去连库的名(n)
            if not 连:
                continue
            连过库的函数 += 1
            for 名, d in 带默认值的参数(n).items():
                if 名 in 连 and isinstance(d, ast.Name) and d.id in 顶层名:
                    命中.add((os.path.relpath(f, ROOT), n.name, 名))
    return 命中, 文件数, 连过库的函数, 解析不了


def 几条(xs, 印几条=8):
    """④ 截断要说**还有几条** —— 照着前几条修完再跑「又冒出来」是真栽过的。"""
    xs = sorted(xs)
    行 = [f"        · {f}  def {fn}({参}=…)" for f, fn, 参 in xs[:印几条]]
    if len(xs) > 印几条:
        行.append(f"        …… **还有 {len(xs) - 印几条} 条**(共 {len(xs)} 条,这儿只印了 {印几条} 条)")
    return "\n".join(行)


def main():
    命中, 文件数, 连过库的函数, 解析不了 = 扫一遍()

    # ② 先报样本量 —— 空集合上所有性质都自动成立
    print(f"\n  切库要切得动 · 库路径不许当默认参数 · 扫了 {文件数} 个源文件,"
          f"其中 {连过库的函数} 个函数拿裸名连过库")
    if 解析不了:
        print(f"  {R}⚠️{D} 有 {len(解析不了)} 个文件没解析成,**没扫到**:{解析不了[:5]}")

    坏 = []

    # ③ 判据自检(反向):扫不到东西 = 判据坏了,**不是「全都对」**
    #    试纸用那次真实翻车的那一处:它扫得到,这个判据才算有视野。
    if 连过库的函数 == 0:
        print(f"  {R}❌{D} 判据自检:一个拿裸名连库的函数都没扫到 —— "
              f"**这是判据坏了,不是「全都对」**(匹配的名字漂了 / AST 形状变了)")
        坏.append("判据自检:一个都没扫到")
    elif 真实故障点 not in 命中 and 真实故障点 in 欠债:
        f, fn, 参 = 真实故障点
        print(f"  {R}❌{D} 判据自检:**扫不到那次真实翻车的那一处**"
              f"({f} def {fn}({参}=…))—— 判据的视野漏了。")
        print(f"        第一版就是这么坏的:找「模块级变量直接被拿去连库」,"
              f"命中 13 处、看着在干活,而出事那处不在里面。")
        print(f"        ⚠️ 要是那一处**真的改好了**,把它从欠债表和这张试纸里一起删掉。")
        坏.append("判据自检:扫不到真实故障点")
    else:
        print(f"  {G}✅{D} 判据自检:扫到了 {连过库的函数} 个连库函数,"
              f"而且**扫得到那次真实翻车的那一处** —— 所以下面的结论是有视野的")

    # ③ 失败分类报(两类下一步完全不同)
    新增 = 命中 - 欠债
    已修好 = 欠债 - 命中

    if 新增:
        print(f"  {R}❌{D} 新增了 {len(新增)} 处「库路径当默认参数」:")
        print(几条(新增))
        print(f"        改法:`def f(db=None): db = db or DB` —— **运行时现取**,"
              f"这样 `模块.DB = 副本` 才改得动它")
        坏.append("有新增的")
    else:
        print(f"  {G}✅{D} 没有新增(欠债表里那 {len(欠债)} 处之外,一处都没多)")

    # ⑥ 反向检查:欠债表不许囤积已经修好的条目
    if 已修好:
        print(f"  {R}❌{D} 欠债表里有 {len(已修好)} 处**已经不命中了**,"
              f"但还挂在表上 —— 改好了就从 `欠债` 里删掉(这条是故意逼人清理的):")
        print(几条(已修好))
        坏.append("欠债表囤积了修好的")
    else:
        print(f"  {G}✅{D} 欠债表没囤积({len(欠债)} 处逐个核过,都还成立)")

    if 坏:
        print(f"\n{R}❌ 切库切不动 —— 改了库路径变量,写口照旧写老地方{D}")
        print(f"   2026-11-03 真丢过数据:共享库 rating 1319 → 1264,"
              f"而且丢的那一刻另一个会话正在跑全量门禁,那一轮整个作废")
        return 1

    print(f"\n{G}✅ 切库切得动(扫了 {文件数} 个源文件 / {连过库的函数} 个连库函数;"
          f"欠债 {len(欠债)} 处,只许少不许多){D}")
    # ⚠️ 这一行是**人真会读到**的那一行 —— 文件头改了而这里没改,等于没改。
    print(f"   ⚠️ 它只验**源码形状**;「运行时真的连上了哪个文件」由 "
          f"backend/check_copy_check.py 验(PRAGMA database_list,断言装在唯一的切库口里)")
    return 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「**实测**红的那一条」;可重放的规格在 tools/bite_specs.json。
咬合 = [
    # ⚠️ 右边写的是**实测**红的那一行的措辞,而且要能**唯一定位** ——
    # 这个项目栽过一次:两条判据共用「判据自检:」前缀,bite_run 报
    # 「红了,但红的不是那一条」。所以这里不写「判据自检」四个字就完,写全。
    ("把一处安全写法(`db=None` + 运行时现取)改回「库路径当默认参数值」 —— "
     "行为上无害(`db or DB` 结果一样),但切库就切不动了。可重放规格打在 backend/motif_review.py 的 `读`",
     "处「库路径当默认参数」"),
    ("把欠债表里某一处从表上删掉,而代码没改(于是它变成「新增」)",
     "处「库路径当默认参数」"),
    ("把要匹配的连库函数名改掉(于是一个连库函数都扫不到,而输出会变成「全都对」)",
     "判据自检:一个拿裸名连库的函数都没扫到"),
]

if __name__ == "__main__":
    sys.exit(main())
