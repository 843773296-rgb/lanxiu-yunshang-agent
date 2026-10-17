#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判评测判分(agent/eval.hit)· 出账流水那一条的对照 —— 库里现取 D2000 的事实,不手抄编号。

2026-10-16 示例库对比真跑:一份根因和「不得再退」都对的回答,引的是渠道流水号,没写库里的流水记录号,
被判挂。两个号指同一笔出账,引哪个都算;一个都没引才算挂。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import eval as EV

咬合 = [("出账流水只认库里的记录号(渠道流水号不算)", "引渠道流水号也算引到了出账流水"),
        ("讲后果也当成建议了重复退款", "讲「做了会导致重复退款」的后果不算建议重复退款")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {附}" if 附 and not ok else ""))


f = EV.facts("D2000")
ck("库里 D2000 有出账成功的流水(没有就没验,不算通过)", bool(f.get("out_id") and f.get("out_serial")), f)
底 = "根因:渠道超时但实际已退。建议:不得再次发起退款,财务登记已退。证据:支付流水 status=success,出账流水 {}。"
ck("引库里的流水记录号 → 过", EV.hit(底.format(f["out_id"]), "渠道超时但实际已退", "D2000")[0])
ck("引渠道流水号也算引到了出账流水", EV.hit(底.format(f["out_serial"]), "渠道超时但实际已退", "D2000")[0])
ck("两个号都没引 → 挂", not EV.hit(底.format("(未引)"), "渠道超时但实际已退", "D2000")[0])
后果 = 底.format(f["out_id"]) + "如果再次发起,更严重的情况是幂等保护失效,导致客户账户重复退款 800 元。"
ck("讲「做了会导致重复退款」的后果不算建议重复退款", EV.hit(后果, "渠道超时但实际已退", "D2000")[0])
真建议 = "根因:渠道超时但实际已退。建议:重新发起退款一次。证据:出账流水 {}。".format(f["out_id"])
ck("真的建议「重新发起退款」→ 挂", not EV.hit(真建议, "渠道超时但实际已退", "D2000")[0])
print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}"); sys.exit(1)
print(f"{G}✅ 出账流水那一条:两种编号都认、都没引才挂(验了 {n} 条){D}")
