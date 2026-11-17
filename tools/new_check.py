#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新检查脚手架(执行手册 W32,2026-11-17):一条检查要同时落四处,少一处就是「写了 ≠ 在跑」。

    python3 tools/new_check.py tools/xxx_check.py --标题 "门禁里那行的标题" [--干跑]

它做的事(每一件都对应一次栽过的事):
  ① 生成 `tools/xxx_check.py` 骨架 —— 先报样本量、0 条就红、自测先过再真跑、模块级 `咬合 = [...]` 清单
     (CLAUDE.md 第 8 节:样本量为 0 要红;「没东西可验」和「验过了」分开;新检查必须做咬合)
  ② 往 `check.sh` 最后一条单行 `run` 后面追加一行 `run "标题" python3 <路径>`
     (10-28 连红三次:根 tools/ 新检查不挂 check.sh,selftest_registry 让 CI 红)
  ③ 打印一条 `tools/bite_specs.json` 规格的**样子**让你填 —— 不自动追加:规格里的 old/new 必须是真代码片段,
     空壳会让 bite_check 当场红「要改的那段找不到」,而留空壳等于欠账
  ④ 跑一遍生成的骨架(自测要绿)和 `tools/selftest_registry_check.py`(确认登记进去了)

文件名必须以 `_check.py` / `_test.py` / `_judgetest.py` 结尾 —— selftest_registry 只认这几种,别的名字它看不见,
看不见就不会替你盯「有没有进门禁」。
"""
import os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

骨架 = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""{标题}

## 为什么要有这个
(写逼出这条检查的那次翻车:哪天、什么症状、为什么现有检查没抓到。没有翻车史的检查往往是没人会回来看的检查)

## 查什么
(判据落结构不枚举词;期望值从哪来 —— 别从被测系统本身算,同源谬误)
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, R, D = "\\033[32m", "\\033[31m", "\\033[0m"


def 查(样本):
    """纯函数:输入从外面喂,自测好喂假的。回 (bad 列表, 验了几个)。"""
    bad = []
    for x in 样本:
        pass  # TODO 判据
    return bad, len(样本)


def 自测():
    """人造夹具:一个全对的不该红;逐个弄坏,红的必须是指定那条(咬合三关里的第三关)。"""
    bad = []
    b, n = 查([])
    if n != 0: bad.append("自测:空样本该报 0 个")
    # TODO: 好样本 → []; 坏样本 → 红且消息含指定字样
    return bad


def 取样本():
    """TODO: 从仓库 / 库里现读要验的东西。"""
    return []


# ── 咬合记录(规格在 tools/bite_specs.json,bite_run 能重放)────────────────
咬合 = [
    ("TODO 改坏了什么(最窄的那一刀,砍在判据够得着的地方)", "TODO 预期红的字面量(要在本文件里原样找得到)"),
]


def main():
    print("{标题}\\n" + "=" * 72)
    bad = 自测()
    if bad:
        for b in bad: print(f"  {{R}}❌ {{b}}{{D}}")
        print(f"{{R}}❌ 自测没过,真跑不算数{{D}}"); return 1
    样本 = 取样本()
    bad, n = 查(样本)
    print(f"  验了 {{n}} 个;自测过")
    if n == 0:
        print(f"{{R}}❌ 一个都没验到 —— 不是「都对」,是没东西可验{{D}}"); return 1
    for b in bad: print(f"  {{R}}❌ {{b}}{{D}}")
    if bad:
        print(f"{{R}}❌ {{len(bad)}} 处不符合预期{{D}}"); return 1
    print(f"{{G}}✅ TODO 一句话说清验住了什么{{D}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def 追加门禁行(路径, 标题, 干跑):
    sh = os.path.join(ROOT, "check.sh")
    行们 = open(sh, encoding="utf-8").read().split("\n")
    if any(路径 in l for l in 行们):
        print(f"  check.sh 里已经有 {路径},不重复加"); return
    # 最后一条**单行**的 run(多行的 bash -c 块在尾部,别插进它中间)
    idx = max(i for i, l in enumerate(行们) if l.startswith('run "') and not l.rstrip().endswith("'") and "bash -c" not in l)
    新 = f'run "{标题}" python3 {路径}'
    行们.insert(idx + 1, 新)
    if 干跑: print(f"  (干跑)会在 check.sh 第 {idx + 2} 行插入:{新}"); return
    open(sh, "w", encoding="utf-8").write("\n".join(行们))
    print(f"  check.sh 第 {idx + 2} 行加了:{新}")


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        print(__doc__); return 2
    路径 = a[0]; 干跑 = "--干跑" in a
    标题 = a[a.index("--标题") + 1] if "--标题" in a else os.path.splitext(os.path.basename(路径))[0]
    if not re.search(r"_(check|test|judgetest)\.py$", 路径):
        print(f"❌ 文件名要以 _check.py / _test.py / _judgetest.py 结尾(selftest_registry 只认这几种):{路径}"); return 1
    绝 = os.path.join(ROOT, 路径)
    if os.path.exists(绝):
        print(f"❌ {路径} 已经存在,不覆盖"); return 1
    if 干跑:
        print(f"  (干跑)会生成 {路径}({骨架.count(chr(10))} 行骨架)")
    else:
        os.makedirs(os.path.dirname(绝), exist_ok=True)
        open(绝, "w", encoding="utf-8").write(骨架.format(标题=标题)); os.chmod(绝, 0o755)
        print(f"  生成 {路径}")
    追加门禁行(路径, 标题, 干跑)
    print("  往 tools/bite_specs.json 里**手填**一条(old/new 要是真代码片段,bite_run --only 能重放):")
    print('   {"script": "%s", "改坏": "<最窄的那一刀>", "file": [{"path": "%s", "old": "<原片段>", "new": "<改坏后>"}], "预期红": "<骨架里原样找得到的字面量>"}' % (路径, 路径))
    if 干跑: return 0
    print("  跑骨架(自测要绿;真跑会红在「一个都没验到」—— 那是对的,样本还没取):")
    r = subprocess.run([sys.executable, 绝], cwd=ROOT, capture_output=True, text=True)
    print("   " + (r.stdout.strip().split("\n")[-1] if r.stdout.strip() else r.stderr.strip()[-200:]))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "selftest_registry_check.py")], cwd=ROOT, capture_output=True, text=True)
    print("  selftest_registry:" + ("✅ 登记进去了" if r.returncode == 0 else "❌ " + r.stdout.strip().split("\n")[-1]))
    print(f"  下一步:填判据 → 填规格 → `python3 tools/bite_run.py --only {路径}` → `git add {路径}`(--only 不带未跟踪的)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
