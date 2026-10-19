#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把总部运营「已采用」的改判并入评测集(truth)—— 换考卷时由维护者跑(用户 2026-10-19 拍「改判先审核」)。

    python3 tools/merge_relabels.py            # 演练:只报会并入几条、有没有和建库标注冲突的
    python3 tools/merge_relabels.py --写入      # 真写

⚠️ 真写之后 truth 变了,`backend/example_pool_check.py` 的「冻结切分 = 按规则现切」会红 ——
   **这是故意的**:并一批 = 换了考卷 = 新分界点。照那条检查的提示重切,并在 PRD 附录 C 记一笔分界点,
   之后的分数不能和以前直接比。别为了让它绿去改那条检查。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import relabel  # noqa: E402

写 = "--写入" in sys.argv[1:] or "--write" in sys.argv[1:]
不认识 = [a for a in sys.argv[1:] if a not in ("--写入", "--write")]
if 不认识:
    sys.exit(f"不认识的参数 {不认识} —— 只有 --写入(拼错了不会悄悄按演练或写入跑)")
r = relabel.并入(演练=not 写)
print(f"{'写入' if 写 else '演练'}:已采用的改判 {r['条数']} 条" + (f"(triage {r['triage_ids']})" if r["条数"] else ""))
for x in r["冲突"]:
    print(f"  ⚠️ 不并:case {x['case_id']} 已有标注「{x['已有']}」,改判是「{x['改判']}」—— 留给人裁(triage#{x['triage_id']})")
if 写 and r["条数"]:
    print("  → truth 变了:跑 backend/example_pool_check.py,照它的提示重切,在 PRD 附录 C 记一个新分界点")
