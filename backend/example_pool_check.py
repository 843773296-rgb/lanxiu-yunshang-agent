#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判示例库 · 检查 —— 隔离和覆盖面,都做成判据,不靠记得(用户 2026-10-16 拍方案 B、一期只覆盖有余量的根因)。

最怕的两种失效,**在分数上都长得像「模型变强了」**:
  · 评测读到了示例池里的单 —— 模型见过答案,分数虚高
  · 切分切走了一整类根因 —— 难的那类不考了,总分照样出、而且更高
所以这里盯:冻结和现切一致 / 两边不相交 / 评测的根因覆盖面一类不少 / 挑示例永不挑自己、只从示例池挑 /
产品研判默认不带示例 / 走产品研判提示词带示例的评测只许用评测那一份 / 示例段不带手机号。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("挑示例时不排除这一单自己", "挑示例永不挑这一单自己"),
    ("挑示例不限示例池(评测那份也能被挑出来)", "挑出来的示例全在示例池里"),
    ("切分不分层(只有一条的根因也切进示例池)", "评测的根因覆盖面一类不少"),
    ("产品研判默认带上示例", "产品研判默认不带示例"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))


print("研判示例库 · 检查")
print("=" * 80)
import example_pool as E, ops

冻 = E.冻结的()
现 = E.切()
池, 评 = 冻["示例池"], 冻["评测"]
ck("冻结的切分和按规则现切一致(标注变了要重切 = 新分界点,不许悄悄漂)",
   池 == 现["示例池"] and 评 == 现["评测"], (len(池), len(现["示例池"]), len(评), len(现["评测"])))
ck("示例池和评测都不是空的(空集合上什么都成立)", len(池) > 0 and len(评) > 0, (len(池), len(评)))
池ids, 评ids = {x["case_id"] for x in 池}, {x["case_id"] for x in 评}
ck("示例池和评测不相交", not (池ids & 评ids), sorted(池ids & 评ids))
全类 = {(x["bp"], x["根因"]) for x in 池 + 评}
评类 = {(x["bp"], x["根因"]) for x in 评}
现评类 = {(x["bp"], x["根因"]) for x in 现["评测"]}
# 冻结的和**按规则现切的**都要查:只查冻结文件的话,规则被改坏了这条看不出来(重切那天才暴露)
ck("评测的根因覆盖面一类不少", 全类 == 评类 == 现评类, sorted((全类 - 评类) | (全类 - 现评类)))

# 挑:对每一张有标注的单都挑一次
自己, 越界, 跨类 = [], [], []
池类 = {x["case_id"]: x["bp"] for x in 池}
for x in 池 + 评:
    for y in E.挑(x["bp"], x["case_id"]):
        if y["case_id"] == x["case_id"]:
            自己.append(x["case_id"])
        if y["case_id"] not in 池ids:
            越界.append((x["case_id"], y["case_id"]))
        if 池类.get(y["case_id"], x["bp"]) != x["bp"]:
            跨类.append((x["case_id"], y["case_id"]))
ck("挑示例永不挑这一单自己", not 自己, 自己[:5])
ck("挑出来的示例全在示例池里", not 越界, 越界[:5])
ck("挑出来的示例和这一单是同一类工单", not 跨类, 跨类[:5])
ck("每次最多 3 条", all(len(E.挑(x["bp"], x["case_id"])) <= 3 for x in 评))

# 提示词
样 = [("财务人工任务", "D2001", "TD2001"), ("售后判责", "MW73020", "TMW73020")]
ck("产品研判默认不带示例", all("参考示例" not in ops.研判提示词(t, r, tid)[2] for t, r, tid in 样))
ck("开了才带示例", all("参考示例" in ops.研判提示词(t, r, tid, 带示例=True)[2] for t, r, tid in 样))
段 = "".join(E.示例段(x["bp"], x["case_id"])[0] for x in 评[:15])
ck("示例段不带手机号", not re.search(r"1[3-9]\d{9}", 段))
ck("示例段不放 AI 的草稿(只放人认定的根因 / 处理 / 依据)", "ai_text" not in 段 and "草稿全文" not in 段)

# 谁在带示例跑:只许在白名单文件里开,而且那里必须用评测那一份
开的 = []
for 根, _, 文件们 in os.walk(ROOT):
    if any(p in 根 for p in (".git", "nightly", ".wip", "node_modules", ".venv")):
        continue
    for f in 文件们:
        if f.endswith(".py") and f not in ("example_pool_check.py",):
            p = os.path.join(根, f)
            try:
                t = open(p, encoding="utf-8").read()
            except Exception:
                continue
            # 认「带示例=」后面不是 False 的调用(变量传进去的也算),def 那一行的默认值不算
            if any(re.search(r"带示例\s*=\s*(?!False\b)", 行) and not 行.lstrip().startswith("def ")
                   for 行 in t.splitlines()):
                开的.append((os.path.relpath(p, ROOT), "评测ids" in t))
ck("凡是带示例跑研判的地方,题都从「评测」那一份取(否则模型会见到答案)", all(ok for _, ok in 开的), 开的)
ck("找得到带示例跑研判的地方(对比脚本那一处;一处都找不到说明扫描失灵了)", any("example_ab.py" in p for p, _ in 开的), 开的)

import json
退 = json.load(open(os.path.join(ROOT, "agent", "refund-sets.json"), encoding="utf-8"))
ck("退款三题的押金单不在示例池里", not ({t["押金单"] for t in 退.get("题", [])} & 池ids))

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 示例库隔离与覆盖面都对:示例池 {len(池)} 条 / 评测 {len(评)} 条,根因 {len(评类)} 类一类不少(验了 {n} 条){D}")
