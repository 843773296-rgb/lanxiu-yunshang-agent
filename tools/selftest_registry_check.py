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
    "backend/lifecycle_sync_check.py": "暂缓进门禁(2026-10-09):现在 2769 个客户存的档位和重算对不上,根因在造数脚本"
                                       "(fakedata/mkt_sop_seed.py 算闲置不算下单),已交数据工厂修;修好那天删掉这行、接进 check.sh",
}

# ── 咬合记录 ──────────────────────────────────────────────────────────
咬合 = [
    ("从 check.sh 里删掉一份判分器对照的那一行", "每一份自测都进了门禁"),
    # ⚠️ **2026-10-04 补的第二条,因为第一条只覆盖了仓库的一半** ——
    # 那时这条检查只读 `check.sh`、只扫顶层五个目录(见 main() 里那段)。
    # 扩了视野(148 → 180 份)之后,这一关在**管理后台那半边**也验过了。
    # 实测:删掉 Makefile 里那一行 → 报「**没进的 1 份:
    # 管理后台/tests/orchestration/test_policy_resolve.py**」——
    # 恰好点名那一份,**不是 32 份**(32 份是匹配写错时的样子:
    # 拿 `管理后台/tests/...` 去比 Makefile 里的 `tests/...`)。
    # 第三关(红的必须是点名那一条)在这儿是靠「漏的份数 == 1」验的。
    ("从 管理后台/Makefile 里删掉 test_policy_resolve 那一行", "没进的"),
]


def main():
    # ⚠️ **门禁不只是 check.sh。** 管理后台那半边的测试注册在它自己的
    # `管理后台/Makefile` 里(`make test-orchestration`),而这条检查
    # 2026-10-04 之前**只读 check.sh、只扫顶层五个目录** ——
    # 于是 `管理后台/tests/orchestration/` 下 20 份测试
    # **从来没被它看过**,而它一直在打绿勾。
    # > 一份它**没扫**的测试,和一份它扫了并确认注册的,
    # > **在那个 ✅ 上长得一模一样。**
    # (和同一天发现的 `runlog_check` 盲区是同一个形状:
    #  判据自己只长在仓库的一半上。)
    门禁 = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    for 另一份 in ("管理后台/Makefile",):
        _p = os.path.join(ROOT, 另一份)
        if os.path.exists(_p):
            门禁 += "\n" + open(_p, encoding="utf-8").read()
    扫 = []
    for d in ("agent", "agentsite", "backend", "knowledge", "tools",
              # ⚠️ 这一个是**带子目录**的 —— 上面五个是顶层 glob,
              # 而管理后台的测试全在 tests/orchestration 下面。
              "管理后台/tools", "管理后台/tests/orchestration"):
        for pat in ("*_check.py", "*_judgetest.py", "*_test.py", "test_*.py"):
            扫 += [os.path.relpath(p, ROOT)
                  for p in glob.glob(os.path.join(ROOT, d, pat))]
    扫 = sorted(set(扫))
    # ⚠️ **匹配不能只比全名。** `管理后台/Makefile` 里写的是
    # `tests/orchestration/xxx.py`(相对它自己的目录),而扫出来的是
    # `管理后台/tests/orchestration/xxx.py` —— 第一版就这么比,
    # 于是 32 份全报「没进门禁」,而它们**全都注册了**。
    # 也**不能退到 basename 比**:那样两个目录下的同名文件会互相放行,
    # 而「另一个目录里那份注册了」和「这一份注册了」长得一模一样。
    def _进了(f):
        if f in 门禁:
            return True
        for 前缀 in ("管理后台/",):
            if f.startswith(前缀) and f[len(前缀):] in 门禁:
                return True
        return False

    漏 = [f for f in 扫 if not _进了(f) and f not in 豁免]
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
