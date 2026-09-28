#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shell 脚本体检:**bash 不接受中文变量名**。

## 为什么要这条检查

这个坑 2026-09-28 之前已经踩过三次:

    tools/fetch_model.sh          `模型目录=...` → syntax error
    .github/workflows/check.yml   `红=0` / `exit $红` → 退出码 **255**
    tools/gen_fresh.sh            `产物=(...)` → syntax error

第二次那回的形状最值得记:**它在全绿的时候完全看不出来** ——
`红=0` 被当成命令(`command not found`,只吐到 stderr),`$红` 展开成空,
`exit` 拿不到数字于是退 255。每条测试都退 0,job 却是红的,
而**红的理由完全指错方向**(报的是「参数不是数字」)。

## ⚠️ 为什么本地发现不了

**本地是 zsh,CI 和 `#!/usr/bin/env bash` 跑的是 bash** ——
而 **zsh 允许中文变量名**。
> 「本地能跑」和「CI 能跑」的差别可以只是一个 shell。

(同一族的另一次:CI 第一步声称「零依赖」,而本地 venv 里有 sqlalchemy。
 那次也是靠 `tools/check_zero_dep.py` 变成能在本地跑的判据。)

## 判据:**问 bash,不自己写词法**

`bash -n` 只做语法检查、**不执行**任何命令。这比自己写正则强得多:
自己写的话要认出赋值、数组、`for` 变量、`${}` 展开…… 而漏一种就不报,
**漏掉的那一种正好是下次踩的那一种**。
(同一条理由让 `tools/sql_lint.py` 去问 SQLAlchemy 而不是自己写正则 ——
 第一版自己写,17 处里 15 处是误报。)

⚠️ `bash -n` 抓不到「`红=0` 被当成命令」那一种(它语法合法)。
所以另加一条**静态扫描**:赋值号左边出现非 ASCII 就报。
两条一起才盖得住 —— 一条管语法,一条管那个**语法合法而语义全错**的形状。
"""
import os
import re
import subprocess
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
仓库根 = os.path.dirname(根)
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 要查的文件():
    出 = []
    for base in (根, os.path.join(仓库根, ".github")):
        for dp, dn, fn in os.walk(base):
            dn[:] = [x for x in dn if x not in
                     (".venv", "__pycache__", "node_modules", ".git", ".models")]
            for f in fn:
                if f.endswith((".sh", ".bash", ".yml", ".yaml")):
                    出.append(os.path.join(dp, f))
    return sorted(出)


# 赋值号左边的名字。`^` 或分隔符之后,到 `=` 为止,中间没有空格。
# ⚠️ 只看**像赋值**的那一段 —— `[ "$x" = y ]` 里的 `=` 两边有空格,不算。
_赋值 = re.compile(r"(?:^|[;&|(]|\bfor\s+|\bdo\s+)\s*([^\s;&|()=\"']+)=(?!=)", re.M)
_中文 = re.compile(r"[^\x00-\x7f]")


def _剥引号(行):
    """把引号里的内容换成等长空格。**赋值只可能在引号外面。**

    ⚠️ 第一版没剥,于是 `check.sh` 里一句
    `run "预约漏斗(后一环比前一环多=结构错)" python3 …` 被报成
    「变量名 `后一环比前一环多` 含非 ASCII」——**不该报却报了**。

    而「宽到把明显无关的东西也报进来」**比漏报更糟**:
    它会让人开始整体忽略这条检查。
    (`tools/sql_lint.py` 第一版就是这么错的:17 处里 15 处误报。)
    """
    出, 引 = [], None
    for ch in 行:
        if 引 is None and ch in "\"'":
            引 = ch
            出.append(" ")
        elif 引 is not None and ch == 引:
            引 = None
            出.append(" ")
        else:
            出.append(" " if 引 is not None else ch)
    return "".join(出)


def 查中文变量名(路, 文):
    坏 = []
    for i, 行 in enumerate(文.split("\n"), 1):
        裸 = _剥引号(行.split("#", 1)[0])      # 注释和引号里随便写中文
        if "=" not in 裸:
            continue
        for m in _赋值.finditer(裸):
            名 = m.group(1)
            if _中文.search(名):
                坏.append((i, 名, 行.strip()[:80]))
    return 坏


def main():
    文件们 = 要查的文件()
    ck(f"扫到 {len(文件们)} 个 shell / workflow 文件", len(文件们) >= 3,
       [os.path.relpath(x, 仓库根) for x in 文件们][:6])
    if not 文件们:
        print("  ❌ 一个都没扫到 —— **空清单会让这个检查永远绿**")
        return 1

    硬错 = []
    for 路 in 文件们:
        文 = open(路, encoding="utf-8", errors="replace").read()
        相对 = os.path.relpath(路, 仓库根)
        # ── ① 中文变量名(bash 当场 syntax error,或者更坏:当成命令)──────
        for i, 名, 行 in 查中文变量名(路, 文):
            硬错.append((相对, i,
                         f"变量名 `{名}` 含非 ASCII —— **bash 不接受**。"
                         f"要么 syntax error,要么被当成命令(只吐 stderr)而 `$名` "
                         f"展开成空 —— 后者在全绿时完全看不出来。本地 zsh 允许,CI 不允许"))
        # ── ② 真的让 bash 过一遍语法(.sh 才有意义)──────────────────
        if 路.endswith((".sh", ".bash")):
            r = subprocess.run(["bash", "-n", 路], capture_output=True, text=True)
            if r.returncode != 0:
                硬错.append((相对, 0,
                             f"`bash -n` 过不了:{(r.stderr or '').strip()[:160]}"))

    if 硬错:
        print(f"\n  ❌ {len(硬错)} 处**硬错**:")
        for 相对, i, 说 in 硬错:
            print(f"     {相对}:{i}  {说}")
    else:
        ck("没有中文变量名,而且每个 .sh 都过了 `bash -n`", True)

    # ── 咬合:**这个检查自己得能咬** ──────────────────────────────
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        坏文 = "#!/usr/bin/env bash\n红=0\nfor x in a; do 数=1; done\nexit $红\n"
        p = os.path.join(d, "坏.sh")
        open(p, "w", encoding="utf-8").write(坏文)
        抓到 = [名 for _, 名, _ in 查中文变量名(p, 坏文)]
        ck("咬合:`红=0` 和 `for` 里的 `数=1` 都抓得到",
           set(抓到) == {"红", "数"}, 抓到)
        好文 = ('#!/usr/bin/env bash\nrc=0\nA=(x y)\n'
                '[ "$rc" = 0 ] && echo 中文值没问题\n# 注释里的 中文=1 不算\n'
                # ⚠️ 这一行是真实误报抄回来的:`check.sh` 里的说明文字
                # 带着 `后一环比前一环多=结构错`,被第一版报成中文变量名。
                'run "预约漏斗(后一环比前一环多=结构错)" python3 x.py\n')
        open(p, "w", encoding="utf-8").write(好文)
        ck("对照:正常脚本**不报**(值是中文、注释里有中文、`[ = ]` 比较都不算)",
           查中文变量名(p, 好文) == [], 查中文变量名(p, 好文))

    print(f"\n{'✅' if not (挂 or 硬错) else '❌'} 过 {len(过)} / 挂 {len(挂)} / 硬错 {len(硬错)}")
    return 1 if (挂 or 硬错) else 0


if __name__ == "__main__":
    sys.exit(main())
