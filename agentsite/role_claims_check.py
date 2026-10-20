#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""助手选择页 · 说的和真能做的一致 · 检查(10-19 外部复审 3.4)。

复审看到:页面写着「三个助手」「三个都是只读的」,而助手早就不止三个,手上还挂着下单 / 派任务 / 量体录入这类写工具;
「门店顾问有几个工具、工坊排产有几个」按列表第 1、第 2 个取,列表顺序一变名字和数就对不上。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "agent"), os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("角色清单不报写工具数", "每个助手报出手上会改数据的工具有几个(按写工具名单现算)"),
    ("页面又写回「三个都是只读的」", "页面不再写死「三个助手 / 都是只读」,按每个助手实际的写工具说"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


print("助手选择页 · 说的和真能做的一致")
print("=" * 80)
import sdk, api

写 = set(api.WRITE_TOOLS)
rs = sdk.roles()
对 = [(r["kind"], r.get("writes"), sum(1 for t in sdk._tools_for(r["kind"]) if t.rsplit("__", 1)[-1] in 写)) for r in rs]
ck("每个助手报出手上会改数据的工具有几个(按写工具名单现算)",
   rs and all(w == 真 for _, w, 真 in 对) and any(真 for _, _, 真 in 对), 对)
页 = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
旧话 = [x for x in ("三个都是<b>只读的</b>", "三个角色都是只读的", "三个助手<b>共用") if x in 页]
ck("页面不再写死「三个助手 / 都是只读」,按每个助手实际的写工具说",
   not 旧话 and "r.writes" in 页 and "R.writes" in 页, 旧话)
ck("「门店顾问 / 工坊排产各有几个工具」按身份找,不按列表第几个取",
   not re.search(r"ROLES\[\d\]", 页) and 'r.kind==="kb"' in 页 and 'r.kind==="workshop"' in 页)

print()
if 坏:
    print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 助手选择页:个数、只读与否、工具数都从角色清单现算(验了 {n} 条){D}")
