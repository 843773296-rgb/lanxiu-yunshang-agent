"""夜跑历史当样本:每道题近 K 晚的通过率 + 95% 置信区间,分「稳定对 / 时对时错 / 稳定错」三档。(2026-11-12,执行手册 W08)

为什么要它:
  「两轮全对才算对」是一把**变严的尺子**,不是估计量 —— 一道 8 成会做对的题,两轮全对的概率只有 64%;
  n=8 的套里 6/8 的 95% 区间是 [0.41, 0.93],那个「75%」本身没信息量。
  而 `agent/nightly/` 里每套已经躺着 10–14 晚、每晚两轮的逐题记录(体检 C 报告 §5.2),从没被当样本用过 ——
  这是零成本的一次提升:立刻能回答「这道题到底几成」和「哪些题是真缺口」。

只读、只报不拦:**不改 60 / 30 / 10 分层和 95 / 85 门槛**(用户拍过的口径),三档只是给人看「该先看哪几道」。
`agent/nightly/` 是并行会话的目录 —— 这里只读,不写。

    python3 agent/nightly_stats.py                 # 全部套,近 7 晚
    python3 agent/nightly_stats.py --晚 14 --套 ops
    python3 agent/nightly_stats.py --md 文件.md    # 写一份 md(夜报可以贴)

判档(Wilson 95% 区间,样本 = 近 K 晚里这道题的**每一轮**):
  稳定对:下界 ≥ 0.75  ·  稳定错:上界 ≤ 0.25  ·  全对 / 全错但区间还宽:「全对(样本少)」「全错(样本少)」
  其余:时对时错  ·  样本 < 4 轮:样本太少,不判
  ⚠️ 门槛按真实样本量定:近 7 晚每题最多 14 轮,14/14 的下界只有 0.78 —— 第一版写「下界 ≥ 0.9」,
  结果 270 道题全判成「时对时错」,连 14 轮全对的也是。**一把永远量不出「稳定」的尺子,和没有尺子一样。**
"""
import glob
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
夜跑目录 = os.path.join(HERE, "nightly")
最少轮数 = 4
档序 = ("稳定对", "全对(样本少)", "时对时错", "全错(样本少)", "稳定错", "样本太少")


def wilson(过, 总, z=1.96):
    if 总 == 0:
        return (0.0, 1.0)
    p = 过 / 总
    分母 = 1 + z * z / 总
    中 = (p + z * z / (2 * 总)) / 分母
    半 = z * math.sqrt(p * (1 - p) / 总 + z * z / (4 * 总 * 总)) / 分母
    return (max(0.0, 中 - 半), min(1.0, 中 + 半))


def 判档(过, 总):
    if 总 < 最少轮数:
        return "样本太少"
    下, 上 = wilson(过, 总)
    if 下 >= 0.75:
        return "稳定对"
    if 上 <= 0.25:
        return "稳定错"
    if 过 == 总:
        return "全对(样本少)"
    if 过 == 0:
        return "全错(样本少)"
    return "时对时错"


def _题号(d):
    for k in ("case", "id", "题号", "cid"):
        if d.get(k):
            return str(d[k])
    return None


def _各轮(d):
    """这一晚这道题的每一轮过没过。有 各轮过 就用它(两轮都看),没有就退回 passed 一轮。"""
    轮 = d.get("各轮过")
    if isinstance(轮, list) and 轮 and all(isinstance(x, bool) for x in 轮):
        return 轮
    if isinstance(d.get("passed"), bool):
        return [d["passed"]]
    return []


def 读一套(路径):
    """→ {题号: {晚: [轮...]}}。同一晚同一题有多行(重跑)取最后一行。"""
    表 = defaultdict(dict)
    for 行 in open(路径, encoding="utf-8"):
        try:
            d = json.loads(行)
        except Exception:
            continue
        题, 晚 = _题号(d), str(d.get("跑于") or "")[:10]
        if not 题 or not 晚:
            continue
        轮 = _各轮(d)
        if 轮:
            表[题][晚] = 轮
    return 表


def 统计(K=7, 只看=None):
    结果 = {}
    for 路径 in sorted(glob.glob(os.path.join(夜跑目录, "agent__*-results.jsonl"))):
        套 = os.path.basename(路径)[len("agent__"):-len("-results.jsonl")]
        if 只看 and 只看 not in 套:
            continue
        表 = 读一套(路径)
        所有晚 = sorted({晚 for 每题 in 表.values() for 晚 in 每题})
        近 = set(所有晚[-K:])
        题们 = []
        for 题, 每题 in 表.items():
            轮 = [x for 晚, r in 每题.items() if 晚 in 近 for x in r]
            过 = sum(轮)
            下, 上 = wilson(过, len(轮))
            题们.append(dict(题=题, 过=过, 总=len(轮), 晚数=sum(1 for 晚 in 每题 if 晚 in 近),
                           率=(过 / len(轮)) if 轮 else None, 下=下, 上=上, 档=判档(过, len(轮))))
        结果[套] = dict(晚=sorted(近), 题=sorted(题们, key=lambda x: (x["率"] if x["率"] is not None else 2, x["题"])))
    return 结果


def 印(结果, K):
    print(f"夜跑历史 · 近 {K} 晚每道题的通过率(Wilson 95% 区间;样本 = 每一轮;只报不拦)")
    合 = defaultdict(int)
    for 套, r in 结果.items():
        档数 = defaultdict(int)
        for x in r["题"]:
            档数[x["档"]] += 1
            合[x["档"]] += 1
        晚 = f"{r['晚'][0]}…{r['晚'][-1]}" if r["晚"] else "无记录"
        print(f"\n▸ {套}({len(r['题'])} 题,{len(r['晚'])} 晚 {晚}):"
              + " · ".join(f"{k} {档数[k]}" for k in 档序 if 档数[k]))
        for x in r["题"]:
            if x["档"] in ("稳定错", "全错(样本少)", "时对时错"):
                # 按档名整个比,别按「名字里有没有错字」—— 「时对时错」里也有错字,原来全被标成 ❌(11-13 夜自己看出来的)
                print(f"    {'❌' if x['档'] in ('稳定错', '全错(样本少)') else '〰️'} {x['题']:<12} {x['过']}/{x['总']} 轮"
                      f"({x['率']:.0%},区间 {x['下']:.0%}–{x['上']:.0%},{x['晚数']} 晚)")
    print("\n合计:" + " · ".join(f"{k} {合[k]}" for k in 档序))
    print("⚠️ 「稳定错」是真缺口的候选,先看原始回答再下结论 —— 也可能是判分器没跟上产品(商机评测 11-04 那次就是)。")


def 写md(结果, K, 路径):
    行 = [f"# 夜跑历史 · 近 {K} 晚逐题通过率", "", "Wilson 95% 区间,样本 = 每一轮;**只报不拦**,不改分层和门槛。", ""]
    for 套, r in 结果.items():
        坏 = [x for x in r["题"] if x["档"] in ("稳定错", "全错(样本少)", "时对时错")]
        行.append(f"## {套}({len(r['题'])} 题,{len(r['晚'])} 晚)")
        if not 坏:
            行.append("没有时对时错或稳定错的题。")
        for x in 坏:
            行.append(f"- {x['档']} · {x['题']} · {x['过']}/{x['总']} 轮({x['率']:.0%},区间 {x['下']:.0%}–{x['上']:.0%})")
        行.append("")
    open(路径, "w", encoding="utf-8").write("\n".join(行))


咬合 = [("判档门槛退回下界 ≥ 0.9(14 轮全对也判不成稳定对)", "判档门槛按真实样本量:14 轮全对算稳定对")]


def _自测():
    """几个钉死的数:防 wilson / 判档被改歪。期望值手算,不从被测函数现算。"""
    坏 = []
    if 判档(14, 14) != "稳定对":
        print("  ❌ 判档门槛按真实样本量:14 轮全对算稳定对")
        坏.append("14/14")
    下, 上 = wilson(6, 8)
    if not (0.40 < 下 < 0.42 and 0.92 < 上 < 0.94):
        坏.append(f"wilson(6,8) 应约 [0.41,0.93],得 [{下:.3f},{上:.3f}]")
    for 过, 总, 期 in ((28, 28, "稳定对"), (14, 14, "稳定对"), (0, 20, "稳定错"), (15, 20, "时对时错"),
                      (3, 3, "样本太少"), (1, 5, "时对时错"), (7, 7, "全对(样本少)"), (0, 4, "全错(样本少)")):
        if 判档(过, 总) != 期:
            坏.append(f"判档({过},{总}) 应为「{期}」,得「{判档(过, 总)}」")
    if _各轮({"各轮过": [True, False], "passed": False}) != [True, False]:
        坏.append("有 各轮过 时应按两轮算")
    if _各轮({"passed": True}) != [True]:
        坏.append("没有 各轮过 时应退回 passed 一轮")
    print("✅ 自测 11 条全过" if not 坏 else "❌ " + ";".join(坏))
    return 1 if 坏 else 0


if __name__ == "__main__":
    a = sys.argv
    if "--自测" in a:
        sys.exit(_自测())
    K = int(a[a.index("--晚") + 1]) if "--晚" in a else 7
    套 = a[a.index("--套") + 1] if "--套" in a else None
    r = 统计(K, 套)
    印(r, K)
    if "--md" in a:
        写md(r, K, a[a.index("--md") + 1])
