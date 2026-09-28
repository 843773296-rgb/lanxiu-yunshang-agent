#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 那一步声称「零依赖,纯标准库」—— **在本地真跑一遍,不信那句话**。

## 为什么要这个检查

`.github/workflows/check.yml` 有一步叫「编排层四组(零依赖,纯标准库)」,
它**故意**什么都不装(快、不用等 pip)。而那个性质在这个检查之前
**只是一句注释** —— 没有任何东西验证它。

2026-09-27 它真的红了两次:`test_ingest.py` 被加进那一步,
而它 import 的 `knowledge/ingest.py` 需要 sqlalchemy。
⚠️ **本地是绿的** —— 本地 `make test-orchestration` 用 `.venv`,里面有 sqlalchemy。

> 「本地能跑」和「CI 能跑」的差别可以只是一个装了的包。
> (同一族的上一次:本地 zsh 允许中文变量名,CI 的 bash 不允许。)

## 判据:用**系统 python3** 跑,而不是分析 import

系统 `python3` 没装 sqlalchemy(装的东西都在 `.venv` 里),
所以「用它能跑通」就等价于「只用了标准库 + 仓库内的模块」。

⚠️ **不去静态分析 import**:那要跟着传递依赖走,而漏一层**不报错** ——
漏掉的那一层正好就是会在 CI 里炸的那一层。真跑一遍是没有缝的。

## 清单从 CI 配置里读,**不在这里抄第二份**

抄一份的坏法是它会漂:CI 加了一组而这里没加,于是这个检查
**对新加的那一组不生效**,而它照样报「全过」。
(`tools/progress_report.py` 里那份手抄的 handler 清单踩过同一个坑。)
"""
import os
import re
import subprocess
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CI = os.path.join(os.path.dirname(根), ".github", "workflows", "check.yml")
# 系统 python3(不是 .venv 里那个)—— **它没装 sqlalchemy,这正是判据要的**
系统python = os.environ.get("ZERODEP_PYTHON", "/usr/local/bin/python3")

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 读CI里的清单():
    """从 check.yml 里那个 `for t in …; do` 抠出测试名。

    ⚠️ 抠不出来就**当场失败**,不返回空清单 ——
    空清单会让这个检查「全过」,而那正是它要防的那件事。
    """
    if not os.path.exists(CI):
        return None, f"找不到 CI 配置:{CI}"
    s = open(CI, encoding="utf-8").read()
    m = re.search(r"for\s+t\s+in\s+((?:[^\n;]*\\\s*\n)*[^\n;]*);\s*do", s)
    if not m:
        return None, ("CI 配置里找不到那个 `for t in …; do` —— "
                      "**它可能被改写成别的形状了**。这个检查的清单从那里读,"
                      "读不到就等于没有清单,所以当场失败而不是「全过」")
    名们 = [x for x in re.split(r"\s+", m.group(1).replace("\\", " ")) if x.strip()]
    return 名们, ""


def main():
    print("▸ 「零依赖」真的零依赖吗 —— 用系统 python3 把 CI 那一步跑一遍")
    if not os.path.exists(系统python):
        print(f"  ❌ 找不到系统 python3({系统python})—— "
              f"用 ZERODEP_PYTHON 指一个**没装 sqlalchemy** 的解释器。"
              f"\n     ⚠️ 这不叫跳过:跳过和通过在输出上长得一样,所以退非 0")
        return 1
    名们, 为什么 = 读CI里的清单()
    if 名们 is None:
        print(f"  ❌ {为什么}")
        return 1
    ck(f"从 CI 配置里读到 {len(名们)} 组(不在这里抄第二份 —— 抄的会漂)",
       len(名们) >= 5, 名们)

    # 先证明这个解释器**真的**没有 sqlalchemy,否则整个判据是空的
    r = subprocess.run([系统python, "-c", "import sqlalchemy"],
                       capture_output=True, text=True)
    ck("这个解释器**确实没装 sqlalchemy** —— 否则这个检查什么也证明不了",
       r.returncode != 0, (r.stderr or "").strip().split("\n")[-1][:80])

    PP = ":".join(sorted({
        os.path.abspath(dp) for dp, dn, fn in os.walk(根)
        if ".venv" not in dp and "__pycache__" not in dp
        and any(f.endswith(".py") for f in fn)}))
    环境 = dict(os.environ, PYTHONPATH=PP, PYTHONDONTWRITEBYTECODE="1")
    for 名 in 名们:
        路 = os.path.join(根, "tests", "orchestration", f"{名}.py")
        if not os.path.exists(路):
            ck(f"{名}:CI 清单里有它而文件不存在", False, 路)
            continue
        r = subprocess.run([系统python, 路], capture_output=True, text=True,
                           cwd=根, env=环境, timeout=600)
        if r.returncode == 0:
            ck(f"{名} 在纯标准库下跑通", True)
        else:
            末 = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
            ck(f"{名} 在纯标准库下**跑不通** —— CI 那一步会红,而本地 venv 里是绿的",
               False, 末[-1] if 末 else f"退出码 {r.returncode}")

    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
