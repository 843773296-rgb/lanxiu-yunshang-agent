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
审查 = os.path.join(HERE, "..", "agentsite", "third_party_review.json")
MAX_REF = 2_000_000          # 单个参考文件超过 2MB 就不搬


def 自有():
    """自有技能名单只认 skills_own.OURS 一处(原来这里写死三个,后来自有加到十三个,这里一直没跟)。"""
    import importlib.util as u
    sp = u.spec_from_file_location("skills_own", os.path.join(HERE, "..", "agentsite", "skills_own.py"))
    m = u.module_from_spec(sp); sp.loader.exec_module(m)
    return set(m.OURS)


def 不适用():
    """2026-11-17(用户 11-12 拍,业务拍板 十):审查判「不适用」的不再装 —— 它们归档在仓外
    ~/Desktop/accio-拆解/skills-archived-20261117/,要用拷回来。审查文件读不到就一个都不跳,但要说出来。"""
    if not os.path.exists(审查):
        print("  ⚠ 读不到 third_party_review.json,审查判不适用的这次没跳过 —— 装完是全量"); return set()
    d = json.load(open(审查, encoding="utf-8"))
    return {k for k, v in d.items() if v.get("分类") == "不适用"}


def main():
    OURS, 跳 = 自有(), 不适用()
    found, seen, 跳过了 = {}, collections.Counter(), 0
    for d, _, fs in os.walk(SRC):
        if "SKILL.md" not in fs:
            continue
        name = os.path.basename(d)
        seen[name] += 1
        if name in OURS or name in found:
            continue
        if name in 跳:
            跳过了 += 1; continue
        found[name] = d
    print(f"审查判不适用、没装的:{跳过了} 个(名单 {len(跳)} 个)")

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
