#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成仓库根目录 README.md = 入口(tools/readme_head.md)+《产品说明》全文(用户 2026-10-20:「把产品文档也放进去,要去除重复内容」)。

为什么拼、不手抄:产品说明有自己的检查(数字对库、版本号)和发飞书的脚本,是那份内容的唯一来源。
抄一份进 README,产品说明下次一改,README 就开始漂 —— 而漂了的 README 是全网第一眼看到的那一页。
去重的做法是**入口只写产品说明里没有的**(研判队列、安全边界分类、门禁与夜跑、跑起来、目录、索引),
产品说明讲过的(谁在用、能做 / 不做、三代对比、四大库、怎么验证、边界)入口不再写,只指过去。

  python3 tools/make_readme.py           # 重新生成
  python3 tools/make_readme.py --check   # 只核对,不一致退出 1(进门禁)
"""
import os
import re
import sys

咬合 = [
    ("产品说明改了没重新生成 README", "README.md 和「入口 + 产品说明」对不上"),
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
头 = os.path.join(ROOT, "tools", "readme_head.md")
产品说明 = os.path.join(ROOT, "澜绣云裳agent-产品说明.md")
README = os.path.join(ROOT, "README.md")


def 生成():
    head = open(头, encoding="utf-8").read().replace("{{VERSION}}", open(os.path.join(ROOT, "VERSION")).read().strip())
    正文 = open(产品说明, encoding="utf-8").read()
    行 = 正文.splitlines()
    if 行 and 行[0].startswith("# "):
        行 = 行[1:]                      # 产品说明自己的大标题换成下面那个「产品说明」
    # 标题整体降一级:README 里它是一节,不是另一篇文档;代码块里的 # 不动
    出, 在代码 = [], False
    for l in 行:
        if l.lstrip().startswith("```"):
            在代码 = not 在代码
        if not 在代码 and re.match(r"#{1,5} ", l):
            l = "#" + l
        出.append(l)
    return (head.rstrip() + "\n\n---\n\n## 产品说明\n\n"
            "> 以下由 `tools/make_readme.py` 从《澜绣云裳agent-产品说明.md》**原样**收进来 —— 要改去改那份,别在这里改。\n"
            + "\n".join(出).rstrip() + "\n")


if __name__ == "__main__":
    新 = 生成()
    if "--check" in sys.argv:
        旧 = open(README, encoding="utf-8").read() if os.path.exists(README) else ""
        if 旧 != 新:
            print("❌ README.md 和「入口 + 产品说明」对不上 —— 有人直接改了 README,或者产品说明 / 入口改了没重新生成。"
                  "跑 python3 tools/make_readme.py")
            sys.exit(1)
        print(f"✅ README.md = 入口 + 产品说明全文,一致({len(新.splitlines())} 行)")
        sys.exit(0)
    open(README, "w", encoding="utf-8").write(新)
    print(f"已生成 README.md({len(新.splitlines())} 行)")
