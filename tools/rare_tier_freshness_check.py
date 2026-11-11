# -*- coding: utf-8 -*-
"""罕见层(长尾场景)多久没跑了 —— 超过闸天数就红。

## 为什么有这条检查(用户 2026-11-11 拍)

用户问「长尾场景应该会需要时间节点的吧,长尾多久了一定要跑一次,这个得定」。
定下来的是**两个数**,不是一个:
  · **节奏**:每周跑一次(挂夜跑)
  · **失效闸**:**14 天**没跑就在门禁里红 —— 这一条比节奏更重要,
    因为它让「没跑」变得**可见**。

### 这条闸守的是什么

罕见题的题面大多依赖**当时的库状态** —— 一道「面料停产换料」的题,
半年后库里那个面料可能已经被清掉了;题还在、判据还在、门禁还绿,
**而它测的东西已经没了**。

> **一道罕见题「一直绿」和一道罕见题「已经测不到东西了」,
> 在那个绿勾上长得一模一样。**

夜跑悄悄挂了三周也是同一个形状 —— 没有这条闸,「三周没跑」不会有任何东西说出来。

### 为什么闸(14 天)比节奏(7 天)松一档

一次夜跑失败不该立刻红(**误报比漏报贵** —— 一条爱误报的检查会被人拆掉),
但**连续两周没跑必须红**。

### ⚠️ 这条闸会随时间自己变红,那是故意的

结果文件是提交进仓库的,`跑于` 不会自己更新。所以**到期之后 CI 也会红** ——
那正是它的意图:让「很久没跑」变成一件不能绕过的事。
底下的失败输出里写明了**怎么让它重新变绿**(跑一轮评测),不是只喊一句红。
"""
import io, json, os, sys, glob, datetime

闸天数 = 14          # 用户 2026-11-11 拍。节奏是每周,闸比节奏松一档
这一层 = "罕见"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "knowledge")]
import eval_tier as T                                        # noqa: E402

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
_前缀 = lambda s: "".join(c for c in str(s) if c.isalpha())[:3]


def 套名(路径):
    """`agent/ops-eval-results.jsonl` → `ops`(分层表里用的那个套名)。"""
    b = os.path.basename(路径)
    for 尾 in ("-eval-results.jsonl", "-results.jsonl"):
        if b.endswith(尾):
            return b[: -len(尾)]
    return b


def 扫(根=None):
    """→ dict(文件数, 记录数, 罕见题 {(套,id): 跑于}, 读不动的)"""
    根 = 根 or ROOT
    罕见, 读不动, 记录数, 文件数 = {}, [], 0, 0
    for p in sorted(glob.glob(os.path.join(根, "agent", "*-results.jsonl"))):
        套 = 套名(p)
        if not T.认得这套吗(套):
            continue
        文件数 += 1
        try:
            for l in io.open(p, encoding="utf-8"):
                if not l.strip():
                    continue
                r = json.loads(l)
                记录数 += 1
                tid = r.get("id") or r.get("题")
                跑于 = r.get("跑于")
                if not tid or not 跑于:
                    continue
                # ⚠️ **判层用 `eval_tier.层()`,不在这里枚举题号前缀。**
                #    枚举的话,六个新业务面接进来时这条闸会**静默漏掉它们** ——
                #    而「罕见层很新鲜」和「罕见层那几道我根本没认出来」
                #    在那个绿勾上长得一模一样。
                if T.层(套, tid) == 这一层:
                    k = (套, str(tid))
                    if 跑于 > 罕见.get(k, ""):
                        罕见[k] = 跑于
        except Exception as e:
            读不动.append((os.path.relpath(p, 根), f"{type(e).__name__}: {e}"))
    return dict(文件数=文件数, 记录数=记录数, 罕见=罕见, 读不动=读不动)


def 几天前(跑于, 现在=None):
    现在 = 现在 or datetime.datetime.now()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return (现在 - datetime.datetime.strptime(str(跑于), f)).days
        except ValueError:
            continue
    return None      # 认不出的格式 → 调用方按「认不出」处理,**不当成新鲜**


def 自测():
    """→ 坏掉的条数。每条钉着一次真会犯的错。"""
    坏 = []
    now = datetime.datetime(2026, 11, 11, 12, 0, 0)
    # ① 天数算得对(三种格式都要认)
    for s, 期 in (("2026-11-11 11:00:00", 0), ("2026-10-28 12:00:00", 14),
                  ("2026-11-04", 7), ("2026-10-01 00:00", 41)):
        得 = 几天前(s, now)
        if 得 != 期:
            坏.append(f"几天前({s!r}) 得到 {得},该是 {期}")
    # ② **认不出的格式返回 None,不许当成新鲜**
    #    「刚跑过」和「这个时间戳我读不懂」在一个 0 上长得一模一样
    if 几天前("上周三", now) is not None:
        坏.append("认不出的时间格式必须返回 None —— 当成 0 天就等于「读不懂=刚跑过」")
    # ③ 套名从文件名剥得对
    for p, 期 in (("agent/ops-eval-results.jsonl", "ops"),
                  ("agent/refund_sets-results.jsonl", "refund_sets")):
        if 套名(p) != 期:
            坏.append(f"套名({p!r}) 得到 {套名(p)!r},该是 {期!r}")
    # ④ **反向**:刚跑过的不许报过期(误报比漏报贵)
    if 几天前("2026-11-11 11:00:00", now) > 闸天数:
        坏.append("刚跑过的不许算过期")
    return 坏


# ⚠️ 咬合:每条改坏一处,**红的必须是指定那一条**
咬合 = [
    # ⚠️ 这两条都**在副本上手跑验过能红**才写进来。
    #    第一版想打在「判层改成枚举题号前缀」和「几天前() 认不出返回 0」上,
    #    两个都**打不中**:ops 的罕见题正好就是 T / C 前缀,枚举它们结果一样;
    #    而眼下所有 `跑于` 格式都认得出,改掉容错行为也不变。
    #    > **一个「改坏了没红」和一个「这个改坏点在当下的数据上观察不到」,
    #    > 在那句「改坏了却没红」上长得一模一样。**
    ("把判层那一步关掉(`if T.层(套, tid) == 这一层:` 改成永假)",
     "一道罕见层的题都没找到"),
    ("把 `闸天数` 从 14 改成 -1(闸形同不存在,任何时间都算过期)",
     "道罕见层的题超过"),
]


if __name__ == "__main__":
    if "--自测" in sys.argv:
        print("罕见层时效闸 · 咬合")
        坏 = 自测()
        for x in 坏:
            print(f"  ✗ {x}")
        print(f"{'❌ ' + str(len(坏)) + ' 条不过' if 坏 else '✅ 每一条都咬得动'}")
        sys.exit(1 if 坏 else 0)

    r = 扫()
    坏 = []
    print("=" * 88)
    print(f"  样本量:扫了 {r['文件数']} 个结果文件、{r['记录数']} 条记录"
          f" → 认出 {len(r['罕见'])} 道**{这一层}层**的题(闸 {闸天数} 天)")
    for p, e in r["读不动"]:
        print(f"{Y}     ⚠️ 读不动 {p}:{e}{D}")

    # ⚠️ 「没东西可验」必须和「验过了」分开 —— 这是项目第八条要素
    if not r["罕见"]:
        print(f"{R}  ❌ **一道罕见层的题都没找到 —— 这不叫通过,这叫没测到东西**{D}")
        print(f"     先查:① 结果文件里的 `id` 还是那个形状吗"
              f" ② `knowledge/17-评测集频率分层.md` 里罕见层那几行还在吗"
              f" ③ 套名从文件名剥对了吗")
        sys.exit(1)

    过期, 认不出, 最新 = [], [], None
    for (套, tid), 跑于 in sorted(r["罕见"].items()):
        d = 几天前(跑于)
        if d is None:
            认不出.append((套, tid, 跑于)); continue
        if 最新 is None or d < 最新:
            最新 = d
        if d > 闸天数:
            过期.append((套, tid, 跑于, d))

    if 认不出:
        坏.append(f"{len(认不出)} 道题的 `跑于` 格式认不出 —— **不当成新鲜**,按红处理")
    if 过期:
        坏.append(f"{len(过期)} 道罕见层的题超过 {闸天数} 天没跑")

    print(f"  {'❌' if 坏 else '✅'} 罕见层最近一次跑:{最新} 天前"
          f"(最旧的那道 {max((d for *_, d in 过期), default=最新)} 天前)")
    印 = 8
    for 套, tid, 跑于, d in 过期[:印]:
        print(f"       · {套}/{tid}  跑于 {跑于}({d} 天前)")
    if len(过期) > 印:
        print(f"       …… 上面只印了 {印} 道,**一共 {len(过期)} 道**")
    for 套, tid, 跑于 in 认不出[:印]:
        print(f"       · {套}/{tid}  `跑于` = {跑于!r} —— 认不出这个格式")
    print("=" * 88)
    for x in 坏:
        print(f"{R}❌ {x}{D}")
    if 坏:
        print(f"{Y}   → 怎么让它重新变绿:**跑一轮罕见层的评测**,结果落盘后 `跑于` 就新了。"
              f"\n     ⚠️ 一律用 Claude 且显式指定模型:"
              f"`LANXIU_PROVIDER=claude ANTHROPIC_MODEL=claude-haiku-4-5`"
              f"(换模型会让基线不可比)。"
              f"\n     ⚠️ **不要为了让这条变绿去改 `跑于` 字段** —— 那是把温度计调一下。{D}")
    else:
        print(f"{G}✅ 罕见层时效符合预期{D}")
    sys.exit(1 if 坏 else 0)
