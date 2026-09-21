#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""截断的报告要说「还有几条」—— **截断的和完整的长得一模一样。**

    python3 tools/truncation_check.py          # 门禁:新增的一律红
    python3 tools/truncation_check.py --登记     # 把现状写进欠债表(只在第一次用)

## 这条是怎么来的

2026-09-21。`determinism_check --真建两次` 报「两次重建逐表一致」不过,
列出 4 张表。我照着修完 4 张,再跑一遍,`staff` **又冒出来**。

于是我把它误诊成「同类的列没登记全」,还照着这个错根因加了一条门禁 ——
那条在 `ts` 这种通用列名上当场误报 4 条,只好撤掉。

真相是那一行写的是 `"；".join(差[:4])`:**只显示前 4 条,而且不说还有几条**。
按表名排序 account < op_log < schedule < schedule_file < **staff**,
staff 正好第 5 个,被截掉了。

> 报告截断不会报错,也不会变形 —— **它只是少说了几句,而看的人不知道少了**。
> 代价不是少看几条,是**照着它下的结论全错**:我以为修完了,于是去找别的解释,
> 然后基于那个错解释做了一条会误报的检查。

## 判据:报告函数里截断一个「问题清单」,附近必须交代还有几条

只盯 `报(...)` / `ck(...)` / `print(...)` 里形如 `"…".join(清单[:N])` 的写法,
而且被截的得是**函数里算出来的变量**(模块级常量不算 —— 那是提示文案里
列几个例子,不是问题清单)。附近两行里有「还有 / 共 / ……」就算交代过了。

**不做大规模改写**:全仓一次扫出 62 处,分布在 24 个文件里。
62 次手改本身就会出错,而且会和并行会话抢文件。所以用**棘轮**:

    现存的 → 写进欠债表,不拦门禁
    新增的 → 红
    修好的 → **必须从欠债表里删掉**(反向检查)

反向那一半不能省。没有它,欠债表会慢慢囤积一堆早就修好的条目,
而**囤积的欠债和真欠债长得一模一样** —— 这是今天第三次用到同一条道理了。
"""
import ast, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
欠债表 = os.path.join(ROOT, "tools", "截断欠债.json")
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("在任意一个检查脚本里新写一处 `\"；\".join(坏[:3])` 且不说还有几条",
     "没有新增的静默截断"),
    ("把欠债表里某一条指向一个已经改好的位置", "欠债表里的都还欠着"),
]

跳过目录 = {".git", "__pycache__", ".venv", "node_modules", ".fakedata", "static"}
报告函数 = {"报", "ck", "报告", "print"}


def 扫():
    """返回 {相对路径: {被截的变量名, ...}}。

    ⚠️ **记的是「文件 + 变量名」,不是行号。** 行号会被上面插一行注释打乱,
    于是欠债表天天在变,而变动里看不出哪条是真的新增 —— 一份天天变的欠债表
    没人会看。变量名跟着那段逻辑走,稳得多。
    """
    出 = {}
    for d, ds, fs in os.walk(ROOT):
        ds[:] = [x for x in ds if x not in 跳过目录 and not x.startswith(".")]
        for f in fs:
            if not f.endswith(".py"):
                continue
            p = os.path.join(d, f)
            try:
                src = open(p, encoding="utf-8").read()
                树 = ast.parse(src)
            except Exception:
                continue
            行 = src.splitlines()
            顶层 = {t.id for n in 树.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)}
            for n in ast.walk(树):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in 报告函数):
                    continue
                for sub in ast.walk(n):
                    if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "join" and sub.args):
                        continue
                    a = sub.args[0]
                    if not (isinstance(a, ast.Subscript) and isinstance(a.slice, ast.Slice)
                            and a.slice.lower is None
                            and isinstance(a.slice.upper, ast.Constant)
                            and isinstance(a.slice.upper.value, int)):
                        continue
                    if not isinstance(a.value, ast.Name):
                        continue
                    名 = a.value.id
                    # 模块级常量 / 全大写 = 提示文案里举几个例子,不是问题清单
                    if 名 in 顶层 or 名.isupper():
                        continue
                    窗 = " ".join(行[max(0, n.lineno - 2):(n.end_lineno or n.lineno) + 1])
                    if any(x in 窗 for x in ("还有", "…", "共 ")):
                        continue
                    出.setdefault(os.path.relpath(p, ROOT), set()).add(名)
    return {k: sorted(v) for k, v in sorted(出.items())}


def 读欠债():
    if not os.path.isfile(欠债表):
        return {}
    return json.load(open(欠债表, encoding="utf-8")).get("欠着的", {})


def main():
    现 = 扫()
    if "--登记" in sys.argv:
        json.dump({"说明": __doc__.split("##")[0].strip(),
                   "怎么还": "在那一处加一句「……还有 N 条(共 M)」,然后把这一条从下面删掉。"
                             "**删不删由这个检查强制** —— 修好了还留着,它会红。",
                   "登记于": "2026-09-21",
                   "欠着的": 现},
                  open(欠债表, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"登记 {sum(len(v) for v in 现.values())} 处 / {len(现)} 个文件 → {欠债表}")
        return 0

    欠 = 读欠债()
    失败 = []

    def ck(ok, 名, 说明=""):
        print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
        if not ok:
            失败.append(名)

    print("截断的报告要说「还有几条」")
    n现 = sum(len(v) for v in 现.values())
    n欠 = sum(len(v) for v in 欠.values())
    # 样本量:一处都没扫到时,下面两条自动成立
    ck(n现 + n欠 > 0 or True, "扫到的报告点", f"现存 {n现} 处 / {len(现)} 个文件")

    新增 = []
    for f, ns in 现.items():
        for x in ns:
            if x not in (欠.get(f) or []):
                新增.append(f"{f}:{x}")
    ck(not 新增, "没有新增的静默截断",
       "、".join(新增[:4]) + (f"  ……**还有 {len(新增) - 4} 处**(共 {len(新增)})"
                             if len(新增) > 4 else "")
       + " —— 截断问题清单时要说还有几条,不然照着它下的结论会错"
       if 新增 else f"欠债表里 {n欠} 处,一处没多")

    # 反向:修好了就得从欠债表里删掉,不然欠债表会囤积
    好了 = []
    for f, ns in 欠.items():
        for x in ns:
            if x not in (现.get(f) or []):
                好了.append(f"{f}:{x}")
    ck(not 好了, "欠债表里的都还欠着",
       "、".join(好了[:4]) + (f"  ……**还有 {len(好了) - 4} 处**(共 {len(好了)})"
                             if len(好了) > 4 else "")
       + " —— **已经改好了,该从欠债表里删掉**。囤积的欠债和真欠债长得一模一样"
       if 好了 else f"{n欠} 处都还欠着")

    if n欠:
        print(f"     ℹ️ 欠着 {n欠} 处({len(欠)} 个文件)—— 不拦门禁,但**只许少不许多**。"
              f"还法:在那一处加一句「……还有 N 条(共 M)」,再从 {os.path.basename(欠债表)} 里删掉")
    print((f"{R}❌ 静默截断 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 截断都交代了还有几条{D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
