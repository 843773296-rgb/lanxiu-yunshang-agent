#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自测有没有进门禁 —— **一份没进 check.sh 的自测,和一份不存在的自测,在绿勾上长得一模一样。**

2026-10-03 管理后台会话报的:它写的两份判分器对照(20 条、23 条)都忘了注册,而门禁全绿。
顺着一扫,**`agent/factory_eval_judgetest.py`(工厂回传判分器 37 条)从写好那天起就没进过门禁** ——
它守的那套评测,判分器改坏了也没人知道。

扫这些名字:`*_check.py` / `*_judgetest.py` / `*_test.py`(agent / agentsite / backend / knowledge / tools)。
每一份要么出现在 check.sh 里,要么在下面的豁免名单里**写清为什么不进**。
豁免名单只许少不许多的意思是:新写的自测默认必须进门禁,要豁免得来这里写一行理由,review 时看得见。
"""
import glob, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"

# 不进门禁的,每一份写清为什么。**「忘了」不是理由。**
豁免 = {
    "backend/asr_check.py": "要真跑 whisper(CI 上没有),依赖外部状态的检查进门禁会变成随机拦路;人手跑",
    "backend/advisor_ref_check.py": "已退役:它查「顾问名字缓存有没有漂」,而名字列 a35fa7e 全库删了,没有对象可查"
                                    "(advisor_name_check 头注释写着「真正该撤的是它」)",
}

# ── 咬合记录 ──────────────────────────────────────────────────────────
咬合 = [
    ("从 check.sh 里删掉一份判分器对照的那一行", "每一份自测都进了门禁"),
]


def main():
    门禁 = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    扫 = []
    for d in ("agent", "agentsite", "backend", "knowledge", "tools"):
        for pat in ("*_check.py", "*_judgetest.py", "*_test.py"):
            扫 += [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, d, pat))]
    扫 = sorted(set(扫))
    漏 = [f for f in 扫 if f not in 门禁 and f not in 豁免]
    陈 = [f for f in 豁免 if not os.path.exists(os.path.join(ROOT, f)) or f in 门禁]
    坏 = 0
    if not 扫:
        print(f"  {R}❌{D} 一份自测都没扫到 —— 没扫到东西,不是通过"); return 1
    if 漏:
        坏 += 1
        print(f"  {R}❌ 每一份自测都进了门禁(验了 {len(扫)} 份){D}  没进的 {len(漏)} 份:{'、'.join(漏)} —— "
              f"在 check.sh 里加一行 run,或者在豁免名单里写清为什么不进")
    else:
        print(f"  {G}✅{D} 每一份自测都进了门禁(验了 {len(扫)} 份,豁免 {len(豁免)} 份各有理由)")
    if 陈:
        坏 += 1
        print(f"  {R}❌ 豁免名单里没有过期的{D}  {'、'.join(陈)} —— 文件没了或者已经进了门禁,把它从豁免里删掉")
    else:
        print(f"  {G}✅{D} 豁免名单里没有过期的(验了 {len(豁免)} 份)")
    return 1 if 坏 else 0


if __name__ == "__main__":
    sys.exit(main())
