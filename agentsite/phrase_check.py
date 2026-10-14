#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天页「常用语」按钮 · 检查(静态,不起服务)。

    python3 agentsite/phrase_check.py

用户 2026-10-14:「是按钮,点击了直接把文字放进输入框里就行」—— 人核完写结论时用(先做版师样板)。
要守的就两件:**点了只填字、不发送**(发出去的话人就没机会改「___ / PT__」那些空);
常用语和「示例问题」是两回事(示例点了直接发、是问它的;常用语是人自己写结论的),别混成一份。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [("点常用语按钮顺手把消息发出去", "点常用语只填进输入框,不发送"),
        ("把工坊排产的常用语删掉", "有「正常」「异常」两组常用语")]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {附}" if 附 and not ok else ""))


import sdk
# 10-14 用户拍:岗位角色各配一套(写人自己核过 / 看到 / 问到的事);**全能助手不配** —— 用它的人是来问的,
# 三套塞一起 11+12 句又把页面占满。
岗位 = [k for k in sdk.ROLE_META if k != "all"]
ck(f"岗位角色({len(岗位)} 个)都在验(少于 4 个多半是角色改名了,不是都通过)", len(岗位) >= 4, 岗位)
for k in 岗位:
    m = sdk.ROLE_META[k]
    P = m.get("phrases") or {}
    ck(f"{m['name']}有「正常」「异常」两组常用语", bool(P.get("正常")) and bool(P.get("异常")), list(P))
    ck(f"{m['name']}的常用语和示例问题不混(示例是问它的,常用语是人写结论的)",
       not (set(sum(P.values(), [])) & set(m.get("examples") or [])))
ck("全能助手不配常用语(用户 10-14 拍)", not sdk.ROLE_META.get("all", {}).get("phrases"))
页 = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
m = re.search(r"function drawPhrases\(R\)\{(.*?)\nfunction ", 页, re.S)
体 = m.group(1) if m else ""
ck("页面有常用语那一段,而且每次切角色都重画", bool(体) and "drawPhrases(R);" in 页)
点 = 体[体.find("b.onclick"):] if "b.onclick" in 体 else ""
ck("点常用语只填进输入框,不发送", bool(点) and "q.value" in 点 and "ask(" not in 点
   and "#send" not in 点 and ".click()" not in 点, 点[:120])

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 常用语按钮:只填字不发送(验了 {n} 条){D}")
