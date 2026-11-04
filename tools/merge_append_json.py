#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只会往末尾追加的 JSON 列表,冲突时按**三方**合 —— 而且一边删过就拒绝合并。

## 为什么要这个工具

`tools/bite_specs.json` 这类文件是「只追加的台账」:两个会话各自在末尾加几条,
git 必然报冲突。而手工解它的后果很特别:

> 文件语法完好、JSON 解析通过、git 不报任何错,而**几条规格消失了** ——
> 那几个脚本里的 `咬合 = [...]` 散文记录还在,看上去一切照旧。
> **一份丢了几条的台账,和一份完整的,在「合并成功」上长得一模一样。**

2026-11-04 两个会话同一天各往 `bite_specs.json` 追加(7 条 / 1 条),于是有了这一份。

## ⚠️⚠️ 这个工具唯一值钱的地方:**一边删过就拒绝,不自动合**

朴素写法是「取并集」。而取并集会把对方**故意删掉**的条目**复活** ——
复活之后 `bite_check` 报的「欠债处数」会**涨**,而涨正好是人期待看到的方向。

> 一次把删除撤销了的合并,和一次正确的合并,
> **在「条数涨了」这件事上长得一模一样。**

而这个仓库里「删掉一条」是**正当且常见**的动作:咬合欠债表的规矩就是
「修好了必须从表上删掉」(`make-a-check-that-holds` 第 ⑥ 条,反向检查)。
所以删除绝不能被静默撤销。

它只处理「两边都只做了追加」那一种;别的情形把那几条打印出来让人自己判。
**「我判不了」和「合好了」必须分开** —— 和门禁那条「判定不过 N 条 · 崩了 N 条」是同一条规矩。

用法(在冲突状态下跑):

    python3 tools/merge_append_json.py tools/bite_specs.json
"""
import json
import subprocess
import sys


class 没冲突(Exception):
    """git 只有阶段 0 —— 这不是出错,是「这个文件不用解」。两件事要分开说。"""


class 不是纯追加(Exception):
    """有一边删掉或改掉了已有条目 → 我判不了,不许取并集。"""


def 键(x):
    """条目的身份。⚠️ `sort_keys=True` 不能省 —— 两边写的字段顺序不同时,
    少了它同一条会被当成两条,于是「合完多了几条」而没人觉得怪。"""
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def 三方合(base, ours, theirs):
    """纯函数 → (合出来的, 我加的, 他加的);任一边删改过则抛 不是纯追加。"""
    b = {键(x) for x in base}
    我删的 = b - {键(x) for x in ours}
    他删的 = b - {键(x) for x in theirs}
    if 我删的 or 他删的:
        raise 不是纯追加(我删的, 他删的)
    我加的 = [x for x in ours if 键(x) not in b]
    已 = b | {键(x) for x in 我加的}
    他加的 = [x for x in theirs if 键(x) not in 已]
    return list(base) + 我加的 + 他加的, 我加的, 他加的


def 阶段(路径, 号):
    """取冲突三方之一:1=base 2=ours 3=theirs。"""
    r = subprocess.run(["git", "show", f":{号}:{路径}"], capture_output=True)
    if r.returncode != 0:
        err = r.stderr.decode()
        if "stage" in err:
            raise 没冲突(路径)
        raise SystemExit(f"取不到阶段 {号}(1=base 2=ours 3=theirs):{err[:200]}")
    return json.loads(r.stdout.decode("utf-8"))


def main(argv):
    路 = argv[1] if len(argv) > 1 else "tools/bite_specs.json"
    try:
        base, ours, theirs = (阶段(路, n) for n in (1, 2, 3))
    except 没冲突:
        print(f"ℹ️ {路} **没有冲突**,不用解 —— 这不是出错。")
        print("   (git 自己合掉了。但自动合掉**不等于**合对了:"
              "少了元素 git 一个字都不会说,所以照样跑一次对账。)")
        return 0
    try:
        出, 我加的, 他加的 = 三方合(base, ours, theirs)
    except 不是纯追加 as e:
        我删的, 他删的 = e.args
        print("❌ **不是纯追加,我判不了** —— 有一边删掉或改掉了已有条目。")
        for 名, s in (("我方删/改", 我删的), ("对方删/改", 他删的)):
            for x in sorted(s)[:5]:
                print(f"   {名}:{x[:140]}")
        print("   手工确认那几条该不该留,再解。")
        print("   ⚠️ **别取并集** —— 那会把故意删掉的条目复活,"
              "而复活之后欠债数会「涨」,正好是看起来对的方向。")
        return 2
    with open(路, "w", encoding="utf-8") as h:
        json.dump(出, h, ensure_ascii=False, indent=1)
    print(f"✅ 三方合并:base {len(base)} + 我加 {len(我加的)} + 他加 {len(他加的)}"
          f" = {len(出)} 条,两边的追加都留着")
    for 谁, xs in (("我", 我加的), ("他", 他加的)):
        for x in xs:
            print(f"   {谁}:{x.get('script', '?')}  预期红 {str(x.get('预期红', ''))[:40]}")
    print("   ⚠️ 解完必须跑一次对账(bite_specs 跑 `python3 tools/bite_check.py`)——"
          "git 不报错只说明语法通了,JSON 少了元素它一个字都不会说")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
