#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新检查脚手架(执行手册 W32,2026-11-17):一条检查要同时落四处,少一处就是「写了 ≠ 在跑」。

    python3 tools/new_check_scaffold.py tools/xxx_check.py --标题 "门禁里那行的标题" [--干跑]

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

# 模板放在旁边的 .tmpl 里,不写在这个 .py 里:charset_fullwidth_check 扫所有 .py 赋值右侧的字串,
# 模板里 ANSI 色码的「[」会和后文某个「]」被拼成一个字符集,报「缺全角」(11-17 第四轮门禁 41→42 就是它)。
# 模板不是正则,搬出 .py 比给检查开豁免干净 —— 豁免会囤积。
骨架 = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "new_check_scaffold.tmpl"), encoding="utf-8").read()


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
