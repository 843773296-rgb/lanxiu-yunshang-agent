#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只追加的 JSON 台账三方合并 · 判据。

守的是 `tools/merge_append_json.py`,而它唯一值钱的地方是
**一边删过就拒绝合并**(取并集会把故意删掉的条目复活,而复活之后
对账报的欠债数会「涨」—— 正好是人期待看到的方向)。

⚠️ **不许只验纯函数。** 2026-11-04 当天刚栽过:给 `tools/impact.py` 写的四条用例
全打在纯函数上,而把入口里**调用它那一支**关掉,四条照旧全对、自测全绿。
所以下面 ⑦⑧ 真造一个 git 冲突、真调 `main()` —— 那一关才是接线。
(这条教训在 CLAUDE.md 第 8 节「咬合本身也会失效」里是第六种形状。)
"""
import contextlib
import io as _io
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge_append_json import 三方合, 不是纯追加, 键, main as 入口  # noqa: E402


def 跑入口(目, 文件):
    """在 目 里跑一遍入口,**把它自己的输出吃掉** → 退出码。

    ⚠️ 不吃掉的话,⑧ 这条反向用例会让被测工具印一个 `❌ 不是纯追加`,
       而那是**预期行为**。项目自己写着「判绿看退出码,别数输出里的 ❌」——
       这里就别去造一个会骗到那条规矩的 ❌:
       一个「反向用例里工具正确拒绝」的 ❌,和一个「这条检查挂了」的 ❌,
       在门禁日志里长得一模一样。
    """
    老 = os.getcwd()
    吞 = _io.StringIO()
    try:
        os.chdir(目)
        with contextlib.redirect_stdout(吞):
            return 入口(["x", 文件])
    finally:
        os.chdir(老)

G, R, D = "\033[32m", "\033[31m", "\033[0m"


def _git(目, *a):
    return subprocess.run(["git", *a], cwd=目, capture_output=True, text=True)


def _写(目, xs):
    with open(os.path.join(目, "台账.json"), "w", encoding="utf-8") as h:
        json.dump(xs, h, ensure_ascii=False, indent=1)


def _读(目):
    return json.load(open(os.path.join(目, "台账.json"), encoding="utf-8"))


def 造冲突(目, 我, 他):
    """在一个一次性仓库里造出真冲突 → 成了吗。

    ⚠️ 台账写成**一行**(indent 由 _写 给,但这里刻意把条目挤在少数行上)——
       目的是让两边的改动落在同一块,git 必然冲突。
       要是写得很松散,git 可能自己合掉,那样**这一关就没验到接线**,
       而「git 自己合掉了」和「我的工具合对了」在结果上长得一模一样。
    """
    base = [{"script": f"s{i}.py", "预期红": f"r{i}"} for i in range(2)]
    for a in (("init", "-q", "."), ("config", "user.email", "t@t"),
              ("config", "user.name", "t")):
        _git(目, *a)
    with open(os.path.join(目, "台账.json"), "w", encoding="utf-8") as h:
        json.dump(base, h, ensure_ascii=False)        # 一行,逼出冲突
    _git(目, "add", "-A")
    _git(目, "commit", "-qm", "base")
    _git(目, "branch", "他")
    with open(os.path.join(目, "台账.json"), "w", encoding="utf-8") as h:
        json.dump(我(base), h, ensure_ascii=False)
    _git(目, "commit", "-qam", "我")
    _git(目, "checkout", "-q", "他")
    with open(os.path.join(目, "台账.json"), "w", encoding="utf-8") as h:
        json.dump(他(base), h, ensure_ascii=False)
    _git(目, "commit", "-qam", "他")
    _git(目, "checkout", "-q", "-")
    r = _git(目, "merge", "他")
    return "CONFLICT" in (r.stdout + r.stderr)


def main():
    过, 挂 = 0, []

    def ck(编, 行不行, 说, 详=""):
        nonlocal 过
        if 行不行:
            过 += 1
            print(f"  {G}✅{D} {编} {说}")
        else:
            挂.append(f"{编} {说}")
            print(f"  {R}❌{D} {编} {说}" + (f"\n        {详}" if 详 else ""))

    print("\n  只追加的 JSON 台账 · 三方合并(前六条纯函数,⑦⑧ 真造 git 冲突验接线)")
    B = [{"s": 1}, {"s": 2}]

    出, 我, 他 = 三方合(B, B + [{"s": 3}], B + [{"s": 4}])
    ck("①", [x["s"] for x in 出] == [1, 2, 3, 4] and len(我) == 1 and len(他) == 1,
       "两边各追加一条 → 都留着,base 顺序不变")

    出, _, _ = 三方合(B, B + [{"s": 9}], B + [{"s": 9}])
    ck("②", [x["s"] for x in 出] == [1, 2, 9],
       "**反向** · 两边加了同一条 → 只留一份(不许重复)")

    for 编, 名, o, t in (("③", "我方删", [{"s": 1}], B),
                         ("④", "对方删(base 删了一条、我方照旧追加)",
                          B + [{"s": 7}], [{"s": 1}])):
        try:
            三方合(B, o, t)
            ck(编, False, f"**反向** · {名} → 该拒绝,**却合了**(取并集会把删掉的复活)")
        except 不是纯追加:
            ck(编, True, f"**反向** · {名} → 拒绝合并(不许静默复活)")

    出, _, _ = 三方合(B, B, B)
    ck("⑤", [x["s"] for x in 出] == [1, 2], "两边都没动 → 原样")

    ck("⑥", 键({"a": 1, "b": 2}) == 键({"b": 2, "a": 1}),
       "**反向** · 字段顺序不同的同一条算**一条**(少了 sort_keys 会合完多出几条,"
       "而多出来没人觉得怪)")

    # ── ⑦⑧ 接线:真造 git 冲突,真调入口 ──────────────────────────────
    目 = tempfile.mkdtemp(prefix="maj-")
    try:
        成 = 造冲突(目, lambda b: b + [{"script": "我的.py", "预期红": "我"}],
                   lambda b: b + [{"script": "他的.py", "预期红": "他"}])
        if not 成:
            ck("⑦", False, "造不出 git 冲突 —— **这一关没验到接线**"
                           "(git 自己合掉了,而那和「我的工具合对了」结果上一样)")
        else:
            rc = 跑入口(目, "台账.json")
            得 = [x["script"] for x in _读(目)]
            ck("⑦", rc == 0 and 得 == ["s0.py", "s1.py", "我的.py", "他的.py"],
               "**接线** · 真造 git 冲突、真调入口 → 两边的追加都在,base 顺序不变",
               f"退出码 {rc},合出来 {得}")
    finally:
        subprocess.run(["rm", "-rf", 目])

    目 = tempfile.mkdtemp(prefix="maj-")
    try:
        成 = 造冲突(目, lambda b: b + [{"script": "我的.py", "预期红": "我"}],
                   lambda b: [b[0]] + [{"script": "他的.py", "预期红": "他"}])
        if not 成:
            ck("⑧", False, "造不出带删除的 git 冲突 —— **这一关没验到接线**")
        else:
            rc = 跑入口(目, "台账.json")
            ck("⑧", rc == 2,
               "**接线 + 反向** · 真冲突里对方删过一条 → 入口退非零拒绝,不自动合",
               f"退出码 {rc}(该是 2)")
    finally:
        subprocess.run(["rm", "-rf", 目])

    print(f"\n  {'❌' if 挂 else '✅'} 只追加台账三方合并 {过} 条过"
          + (f",{len(挂)} 条没过:{挂[:3]}" if 挂 else ""))
    return 1 if 挂 else 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
# ⚠️ 必须是**二元组** —— tools/bite_check.py 只认两个元素的。
# 2026-11-04 实测过三关(对照先绿 · 改坏后红 · 红的正是点名那一条)。
咬合 = [
    ("把「一边删过就拒绝」那一支关掉(`if 我删的 or 他删的:` → `if False and ...`)—— "
     "行为上看起来更能干(什么冲突都合得了),而它会把故意删掉的条目复活",
     # ⚠️ 预期红必须是**源码里真有的那个字面串**。这里 ③④ 的文案是 f-string 拼的
     #    (`f"**反向** · {名} → ..."`),所以不能写「**反向** · 我方删」——
     #    那个串在源码里不存在,bite_check 会报「预期红的那一条在脚本里找不到」。
     #    今天第二次踩这个(上一次在 backend/check_copy_check.py 写了带圈号的)。
     # ⚠️⚠️ 而且要写**失败时**那一句,不是通过时那一句 —— ③④ 这两条的通过文案
     #    (「拒绝合并(不许静默复活)」)和失败文案是 try/except 两个分支里的
     #    两个不同字符串。第一版我写了通过那句,`bite_check` **照样放行**
     #    (它只验「这句话在脚本里存在」,分不出通过文案和失败文案),
     #    而真改坏一次才发现「红了,但红的不是那一条」。
     #    > 一条写了通过文案的咬合记录,和一条写对了的,在对账那一关上长得一模一样。
     "该拒绝,**却合了**"),   # 实测连带红 ③④⑧ 一起(一处真坏了本来就牵动几条)
    # ⚠️⚠️ **这一条是整组里最该留的。** 实测:六条纯函数用例**全部照旧通过**,
    #    只有 ⑧ 那条接线用例红了。也就是说没有 ⑧,「把入口偷偷换成取并集」
    #    这件事**完全不可见** —— 而取并集正是这个工具存在的反面。
    ("把入口里调用三方合那一句换成直接取并集(接线那一关,纯函数照旧全对)",
     "**接线 + 反向**"),     # 实测只红这一条
    ("把 `键()` 的 sort_keys 去掉(字段顺序不同的同一条会被当成两条)",
     "字段顺序不同的同一条算**一条**"),   # 实测只红这一条
]

if __name__ == "__main__":
    sys.exit(main())
