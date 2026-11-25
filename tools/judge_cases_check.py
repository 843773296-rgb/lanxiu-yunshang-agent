#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对照用例条数 · 32 个判分器统一机读出口,PRD 的数和现算一致

## 为什么要有这个

`tools/doc_numbers_check.py` 末尾那条 TODO 躺了两个月:「十个判分器各自打印自己的条数,格式互不相同……
拿正则去刮只能刮到一半 —— **而刮到一半会被报成『全部通过』**,比不刮更糟」。于是 PRD 里 13 行
「离线对照用例 N 条(xxx)」一直是 9 月写的数(知识问答 20、工具使用 23、工坊与任务 90……),
而对照集早就长到 31 / 43 / 408 条 —— 文档没错在「写了」,错在**没有任何东西会在它过期时变红**。
包三「钱与数字」第一件(用户 2026-11-25 拍):先给对照集一个统一出口,再让文档的数靠它现算。

## 查什么

① check.sh 里点名的每一个 `agent/*_judgetest.py` 跑一遍,**只认** `agent/judgecount.出口` 打印的那一行
   `[cases] 名=… 总=… 过=… 挂=…`(格式在那个模块里只定义一次):没有这一行 → 红(「没出口」不是「0 条」);
   总=0 → 红(样本量 0 的对照集什么都没验);退出码非 0 → 红(挂了的对照集不计数)。
② PRD 里每一行「离线对照用例 N 条(标签)」:标签要能对上某个出口的 名,N 要等于那个出口现算的 总 ——
   对不上就红,并把该改成几写出来。**期望值不是从文档里抄的**,是对照集此刻真跑出来的。
③ 名 不许重复(两个对照集报同一个名,文档就不知道该对哪个)。

期望值的来路:对照集自己(被测的是「文档的数」,不是对照集,所以不算同源)。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))
import judgecount as JC   # noqa: E402

G, R, D = "\033[32m", "\033[31m", "\033[0m"
PRD = "澜绣云裳agent-产品需求文档.md"
# PRD 里的写法是全角括号:「离线对照用例 20 条(知识问答)」;半角也认,免得改成半角就从视野里消失。
# 一行里可能接着写「+ 27 条(角色边界)」(没再重复「离线对照用例」四个字),所以先认行、再在行里找每一处「N 条(标签)」
行式 = re.compile(r"(\d+)\s*条[（(]([^）)]+)[）)]")
行标 = "离线对照用例"
每个超时秒 = 180


def 判分器清单(check_sh):
    return sorted(set(re.findall(r"agent/[a-z_]*judgetest[a-z_]*\.py", check_sh)))


def 文档里的数(prd文本):
    """→ [(行号, 数, 标签)]。一行里可能有两处(「90 条(工坊与任务)+ 27 条(角色边界)」)。"""
    出 = []
    for i, 行 in enumerate(prd文本.splitlines(), 1):
        if 行标 not in 行:
            continue
        for m in 行式.finditer(行):
            出.append((i, int(m.group(1)), m.group(2).strip()))
    return 出


def 查(结果, prd文本):
    """纯函数。结果 = {文件: (退出码, 输出文本)};→ (bad, 验了几个, 名→总)。"""
    bad, 计 = [], {}
    for 文件, (rc, 出) in sorted(结果.items()):
        d = JC.解析(出)
        if d is None:
            bad.append(f"没有机读出口:{文件} —— 在它知道过 / 挂各几条之后调一次 judgecount.出口(名, 过, 挂)")
            continue
        if d["总"] <= 0:
            bad.append(f"样本量 0:{文件} 的出口说一条都没验 —— 这不是通过")
        if rc != 0:
            bad.append(f"判分器自己红了:{文件} 退出码 {rc},它的 {d['总']} 条不计数")
        if d["名"] in 计:
            bad.append(f"名重复:「{d['名']}」被 {计[d['名']][1]} 和 {文件} 都用了 —— 文档不知道该对哪个")
        计[d["名"]] = (d["总"], 文件)
    for 行号, 数, 标签 in 文档里的数(prd文本):
        if 标签 not in 计:
            bad.append(f"PRD 第 {行号} 行标签「{标签}」没有对应判分器出口 —— 要么改标签,要么给那个对照集的出口起这个名")
        elif 计[标签][0] != 数:
            bad.append(f"PRD 第 {行号} 行「{标签}」写 {数} 条,现算 {计[标签][0]} 条 —— 和现算不一致,把文档里的数改成 {计[标签][0]}")
    return bad, len(结果), {k: v[0] for k, v in 计.items()}


def 自测():
    """人造夹具:全对的不该红;逐个弄坏,红的必须是指定那条。"""
    bad = []
    好 = {"agent/a_judgetest.py": (0, "人话\n[cases] 名=甲 总=3 过=3 挂=0\n"),
          "agent/b_judgetest.py": (0, "[cases] 名=乙 总=5 过=4 挂=1\n")}
    文 = "| **指标** | 离线对照用例 3 条（甲） |\n| **验收** | 离线对照用例 5 条（乙）全部通过 |\n"
    b, n, 计 = 查(好, 文)
    if b or n != 2 or 计 != {"甲": 3, "乙": 5}: bad.append(f"自测:全对的夹具不该红:{b} {计}")
    b, n, _ = 查({}, 文)
    if n != 0: bad.append("自测:空样本该报 0 个")
    坏 = dict(好); 坏["agent/a_judgetest.py"] = (0, "人话,没有机读行\n")
    b, _, _ = 查(坏, 文)
    if not (len(b) >= 1 and "没有机读出口" in b[0]): bad.append(f"自测:删了出口行该红在「没有机读出口」:{b}")
    b, _, _ = 查(好, 文.replace("3 条（甲）", "4 条（甲）"))
    if not (len(b) == 1 and "和现算不一致" in b[0] and "改成 3" in b[0]): bad.append(f"自测:文档数字错了该红在「和现算不一致」且说清改成几:{b}")
    b, _, _ = 查(好, 文 + "| 离线对照用例 9 条（丙） |\n")
    if not (len(b) == 1 and "没有对应判分器出口" in b[0]): bad.append(f"自测:标签对不上该红:{b}")
    坏 = dict(好); 坏["agent/b_judgetest.py"] = (1, "[cases] 名=乙 总=5 过=4 挂=1\n")
    b, _, _ = 查(坏, 文)
    if not any("判分器自己红了" in x for x in b): bad.append(f"自测:退出码非 0 该红:{b}")
    坏 = dict(好); 坏["agent/b_judgetest.py"] = (0, "[cases] 名=乙 总=0 过=0 挂=0\n")
    b, _, _ = 查(坏, 文)
    if not any("样本量 0" in x for x in b): bad.append(f"自测:总=0 该红:{b}")
    坏 = dict(好); 坏["agent/b_judgetest.py"] = (0, "[cases] 名=甲 总=5 过=5 挂=0\n")
    b, _, _ = 查(坏, 文)
    if not any("名重复" in x for x in b): bad.append(f"自测:名重复该红:{b}")
    if 文档里的数("离线对照用例 90 条（工坊与任务）+ 27 条（角色边界）") != [(1, 90, "工坊与任务"), (1, 27, "角色边界")]:
        bad.append("自测:一行两处要都取到")
    return bad


def 取样本():
    """真跑 check.sh 点名的每个判分器(约半分钟),收它们的输出;读 PRD。"""
    check_sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    结果 = {}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for f in 判分器清单(check_sh):
        try:
            p = subprocess.run([sys.executable, f], cwd=ROOT, capture_output=True, text=True, timeout=每个超时秒, env=env)
            结果[f] = (p.returncode, (p.stdout or "") + "\n" + (p.stderr or ""))
        except subprocess.TimeoutExpired:
            结果[f] = (124, "")
    prd = open(os.path.join(ROOT, PRD), encoding="utf-8").read()
    return 结果, prd


# ── 咬合记录(规格在 tools/bite_specs.json,bite_run 能重放)────────────────
咬合 = [
    ("从一个判分器里删掉 judgecount.出口 那一行(它又回到只打人话)", "没有机读出口"),
    ("把 PRD 里一行「离线对照用例 N 条(标签)」的 N 改成别的数", "和现算不一致"),
]


def main():
    print("对照用例条数 · 32 个判分器统一机读出口,PRD 的数和现算一致\n" + "=" * 72)
    bad = 自测()
    if bad:
        for b in bad: print(f"  {R}❌ {b}{D}")
        print(f"{R}❌ 自测没过,真跑不算数{D}"); return 1
    结果, prd = 取样本()
    bad, n, 计 = 查(结果, prd)
    总 = sum(计.values())
    print(f"  验了 {n} 个判分器对照集,机读出口合计 {总} 条;PRD 里 {len(文档里的数(prd))} 处写了条数;自测过")
    for 名, 数 in sorted(计.items(), key=lambda kv: -kv[1]):
        print(f"    {名} {数}")
    if n == 0:
        print(f"{R}❌ 一个都没验到 —— 不是「都对」,是没东西可验{D}"); return 1
    for b in bad: print(f"  {R}❌ {b}{D}")
    if bad:
        print(f"{R}❌ {len(bad)} 处不符合预期{D}"); return 1
    print(f"{G}✅ {n} 个判分器都有机读出口(合计 {总} 条对照),PRD 里 {len(文档里的数(prd))} 处条数和现算一致{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
