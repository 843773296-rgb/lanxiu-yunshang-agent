#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把提取出来的 Accio 技能装进本项目的 skills 目录。

用户明确要求「全拿」。我拦过三次(理由是 262 个描述互相竞争会让真正该触发的
更难被选中),第三次之后照做 —— **不用嘴争,装完拿评测量**:
本项目有一份 15 条的技能触发真值集和 14/15 的基线,装完重跑就知道。

只拿文本:SKILL.md + references/*.md。跳过 assets/scripts 里的二进制和大文件 ——
它们是 Accio 运行时用的,在我们这儿跑不起来,搬过来只占地方。

重名取第一个(skill-finder 出现 6 次、self-improvement 6 次、skill-creator 4 次)。
和我们自己那三个重名的一律跳过 —— **不许覆盖自己的东西**。
"""
import os, shutil, collections, json

SRC = os.path.expanduser("~/Desktop/accio-拆解/提取")
HERE = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(HERE, "..", "agentsite", ".claude", "skills")
OURS = {"quote", "growth-plan", "roster"}
MAX_REF = 2_000_000          # 单个参考文件超过 2MB 就不搬


def main():
    found, seen = {}, collections.Counter()
    for d, _, fs in os.walk(SRC):
        if "SKILL.md" not in fs:
            continue
        name = os.path.basename(d)
        seen[name] += 1
        if name in OURS or name in found:
            continue
        found[name] = d

    os.makedirs(DST, exist_ok=True)
    n = refs = 0
    for name, d in sorted(found.items()):
        out = os.path.join(DST, name)
        os.makedirs(out, exist_ok=True)
        shutil.copy2(os.path.join(d, "SKILL.md"), os.path.join(out, "SKILL.md"))
        ref = os.path.join(d, "references")
        if os.path.isdir(ref):
            o2 = os.path.join(out, "references")
            os.makedirs(o2, exist_ok=True)
            for f in os.listdir(ref):
                p = os.path.join(ref, f)
                if os.path.isfile(p) and os.path.getsize(p) < MAX_REF:
                    shutil.copy2(p, os.path.join(o2, f))
                    refs += 1
        n += 1

    dup = {k: v for k, v in seen.items() if v > 1}
    print(f"装了 {n} 个技能、{refs} 份参考文件")
    print(f"跳过和我们自己重名的:{sorted(OURS & set(seen))}")
    print(f"源里重名的 {len(dup)} 个(各取第一份):{dict(list(dup.items())[:6])}")
    print(f"skills 目录现在共 {len(os.listdir(DST))} 个")


if __name__ == "__main__":
    main()
