# -*- coding: utf-8 -*-
"""evalnoise 的逐例测试。**判断「读不读得出」这件事本身要能被测**,
否则它只是换了个地方的想当然。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evalnoise import verdict, stability

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad = 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「没有对照组就不下判断」那一支关掉(算不出底噪也照样给结论)',
     '没有对照组 → 不下判断'),
]

def ck(title, got, want):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {title:52s} {str(got):6s} 应为 {want}")


def main():
    print("\n\033[1m▸ 一次改动读不读得出效果\033[0m")
    print("  " + "=" * 78)
    # 真实案例:改动组 +1/-0,对照组 +1/-1 —— 净变化 1,噪声 2,读不出
    ck("改动+1 而噪声动了2 → 读不出", verdict(1, 0, 1, 1, 5, 10)[0], False)
    ck("改动+3 而噪声动了1 → 读得出", verdict(3, 0, 1, 0, 5, 10)[0], True)
    ck("改动-3 而噪声动了1 → 读得出(变差)", verdict(0, 3, 1, 0, 5, 10)[0], True)
    ck("改动一修一坏净0 → 读不出", verdict(2, 2, 0, 0, 5, 10)[0], False)
    ck("没有对照组 → 不下判断", verdict(3, 0, 0, 0, 5, 0)[0], None)
    ck("改动组是空的 → 不下判断", verdict(0, 0, 1, 1, 0, 10)[0], None)
    # **噪声为 0 时也要能读出** —— 不能因为对照组没动就永远说读不出
    ck("噪声0 而改动+1 → 读得出", verdict(1, 0, 0, 0, 5, 10)[0], True)

    print("\n\033[1m▸ 尺子自己稳不稳\033[0m")
    print("  " + "=" * 78)
    ck("三遍一致 → 稳", stability(["a", "a", "a"])[0], True)
    ck("三遍两种 → 不稳", stability(["a", None, "a"])[0], False)
    ck("只跑两遍 → 量不出", stability(["a", "a"])[0], None)
    ck("只跑一遍 → 量不出", stability(["a"])[0], None)
    ck("没数据 → 量不出", stability([])[0], None)
    # 说法里必须点出「拿它量别人分不清是谁的」
    ck("不稳时说清后果", "分不清是别人的还是它的" in stability(["a", None, "a"])[1], True)

    print()
    if bad:
        print(f"{R}❌ {bad} 处不符合预期{D}"); sys.exit(1)
    print(f"{G}✅ 读不读得出效果的判据本身,逐例符合预期{D}")
    print("    **把噪声读成效果,这一段犯了两次** —— 所以这个判断得能被测。")


if __name__ == "__main__":
    main()
