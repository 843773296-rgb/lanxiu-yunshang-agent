#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词规矩里带单位的数(天 / % / 元 / cm),必须在知识库或口径代码里原样找得到。

为什么现在才要:2026-10-08 用户拍板,体检 g1 **认「规矩里原样写着的数」算有出处**
(运维评测 L03「正好 90 天算不算休眠」:首稿「第 91 天才进休眠」完全对,没调工具被打回,
第二稿不敢答了,两轮都整份扣下)。代价是:规矩里的数一旦过期,体检就**替它背书**了 ——
CLAUDE.md 记过一次「提示词里的数字也会过期」(相容矩阵写着 6%,实际 100%,差 16 倍)。

所以这条把规矩里的每个数对一遍知识库(knowledge/*.md、knowledge/*.py)和口径代码(backend/*.py):
**原样找不到就红**。改口径时漏改了提示词,这里当场红,不会等到体检替一个旧数放行。

⚠️ 判法是「原样出现过」,不是「出现在同一件事旁边」—— 「90 天」在知识库里到处都有,
它证明不了提示词里那个 90 天说的是同一件事。这是**下限**,能抓的是「编出来 / 改口径漏改」的那一类,
抓不了「数对、说的不是一件事」。
"""
import glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "agentsite")]
import prompts, guards

G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("把 L03 那条口径「第 91 天才进休眠」改成「第 97 天」(知识库里没有的数)", "原样找不到"),
]

# 豁免:**不是口径**的数。要写理由,理由说不出就别豁免
豁免 = {
    "80%": "TL 里举例用的(「一个人填的 80% 和一个算法算的 80%,可信度完全不同」),不是哪条业务口径",
}


def 规矩里的数():
    txt = "\n".join(r.text for _, r in prompts.all_rules(unique=True))
    for _role, (头, _rs, 尾) in prompts.ROLES.items():
        txt += "\n" + 头 + "\n" + 尾
    片 = set()
    for rx in (guards.RE_DAYS, guards.RE_BODY, guards.RE_MONEY):
        for m in rx.finditer(txt):
            片.add(re.sub(r"\s+", "", m.group(0)))
    return 片


def 源():
    out = ""
    for f in (glob.glob(os.path.join(ROOT, "knowledge", "*.md")) + glob.glob(os.path.join(ROOT, "knowledge", "*.py"))
              + glob.glob(os.path.join(ROOT, "backend", "*.py"))):
        out += re.sub(r"\s+", "", open(f, encoding="utf-8").read())
    return out


def main():
    片, 文 = 规矩里的数(), 源()
    print("提示词规矩里的数 · 对知识库 / 口径代码原样对账")
    if not 片:
        print(f"  {R}❌ 一个带单位的数都没扫到 —— 是没扫到,不是都对得上{D}"); return 1
    没 = sorted(x for x in 片 if x not in 文 and x not in 豁免)
    死豁免 = sorted(x for x in 豁免 if x not in 片)
    print(f"  扫到 {len(片)} 个,豁免 {len(豁免)} 个(都写了理由)")
    if 死豁免:
        print(f"  {R}❌ 豁免里有提示词已经不再出现的数:{死豁免} —— 删掉,别让豁免表攒成死账{D}")
    if 没:
        print(f"  {R}❌ {len(没)} 个在知识库 / 口径代码里原样找不到:{没}{D}")
        print("     体检 g1 认「规矩里原样写着的数」(用户 10-08 拍板)—— 这些数现在会被它直接放行。"
              "改提示词对上知识库,或者改知识库,别加豁免")
    if 没 or 死豁免:
        return 1
    print(f"  {G}✅ 规矩里的数都在知识库 / 口径代码里原样找得到(验了 {len(片)} 个){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
