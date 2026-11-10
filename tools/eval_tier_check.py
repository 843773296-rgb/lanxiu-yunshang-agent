#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测集频率分层 · 判据 —— 盯住「分层这件事会怎么悄悄烂掉」。

口径在 `knowledge/17-评测集频率分层.md`(用户 2026-11-10 拍),
出口在 `knowledge/eval_tier.py`。这里只验**它会不会漂**,不重新定义口径。

## 分层会怎么烂掉(每条判据对着一种)

① **新加了一套题,没人给它打标** —— 那套题的分数照旧进总分,
   但不进任何一层。分层报告看起来完整,**而它漏了一整套**。
② **分层表里留着已经不存在的套 / 场景** —— 豁免和过期条目长得一模一样
   (项目里「豁免名单只许少不许多」那条规矩的同一个形状)。
③ **有人为了凑 60/30/10 去改标签** —— 比例当场好看,而标签开始说假话,
   **报告上照旧印「日常层 96%,达标」**。这条最隐蔽,靠「题数只许涨」的棘轮守:
   比例变好看只认**补题**那一侧,某层题数变少要判红。
④ **某一层空了或只剩几题** —— 空集合上所有性质都成立,
   「什么都没验」和「验过了没问题」在那一行通过率上一模一样。
⑤ **把判出来的频率当成数出来的** —— 这个项目没有真实流量可数
   (查实过:那 800 条是 106 种模板生成的)。所以真相源里**必须留着
   那句「还没拿真实流量对过账」** —— 少了那句话判红,
   因为少了它,这份口径就会被下一个人当成有依据的。

## 为什么棘轮是「题数只许涨」而不是「比例只许靠近」

比例可以靠**删题**变好看:偶发层删掉 30 题,比例立刻靠近 60/30/10,
而评测集**变弱了**。所以基线记的是**每层的题数**,只许涨。
⚠️ 配套的那只手必须看得见:涨了就印「把基线改成 N」,
而且要印在**通过**那条路径上 —— 这个项目踩过「提示被 tail -3 截掉」。
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from knowledge import eval_tier as T          # noqa: E402

基线文件 = os.path.join(HERE, "评测分层基线.json")

# ── 咬合记录 ────────────────────────────────────────────────────────────
# 每一条都对着上面文件头里列的一种烂法。可重放的规格在 tools/bite_specs.json。
咬合 = [
    ("把读题号的字段从三种砍成一种(只读 id)—— 漏掉一半题,而合计数看起来没问题",
     "每一层的题数只许涨不许降"),
    ("把分层表里某一行的层改掉(等于为了凑 60/30/10 改标签)",
     "每一层的题数只许涨不许降"),
    ("把真相源里「还没拿真实流量对过账」那句话删掉",
     "口径里留着「这份频率还没拿真实流量对过账」那句话"),
    ("让 `层()` 对没登记的套默认返回「日常」(漏打标被静默吞掉)",
     "口径模块自测过"),
    ("往分层表里加一行结果文件里不存在的套(囤积的条目)",
     "分层表里点名的套 / 场景都真实存在"),
    ("把 `--登记` 那道「只许涨」的闸改成永不拦(基线能被静默重设下来)",
     "`--登记` 只许涨"),
]


def 登记拦不拦(计, 旧):
    """`(拦不拦, 为什么)` —— 题数比基线低就拦。

    ⚠️ 方向和 `bite_check` 的 `--登记` **相反**:那边是欠债、只许降;
    这边是题数、**只许涨**。方向写反了,这道闸就变成「随便重设」,
    而它看起来照旧是一道闸。
    ⚠️ 第一次登记(基线里没这一层)**放行** —— 否则这道闸自己就起不来。
    """
    降 = {k: (计[k], 旧[k]) for k in T.层名
          if isinstance(旧.get(k), int) and 计[k] < 旧[k]}
    if 降:
        return True, f"{降} 比基线低(左边现在、右边基线)—— 题数变少不是进展"
    return False, ""
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
FAIL = []


def ck(名, 过, n, 说=""):
    print(f"  {'✅' if 过 else '❌'} {名}(验了 {n} 个){'  ' + 说 if 说 else ''}")
    if not 过:
        FAIL.append(名)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(名 + "(样本量 0)")


def 题们():
    """`[(套, 题号)]`,从版本库里的结果文件现读。

    ⚠️ **三种题号字段都要读**(`id` / `case` / `题`)。2026-11-10 第一版
    只读了 `id`,数出 215 题 / 16 套,而真实是 293 题 / 24 套 ——
    **漏了一半,而那个合计数看起来一点问题都没有。**
    """
    出 = set()
    d = os.path.join(ROOT, "agent")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith("-results.jsonl"):
            continue
        套 = re.sub(r"-eval$", "", f[:-len("-results.jsonl")])
        for l in io.open(os.path.join(d, f), encoding="utf-8", errors="replace"):
            l = l.strip()
            if not l:
                continue
            try:
                x = json.loads(l)
            except Exception:
                continue
            if not isinstance(x, dict):
                continue
            for k in ("id", "题号", "case", "题"):
                v = x.get(k)
                if isinstance(v, str) and v.strip():
                    出.add((套, v.strip()))
                    break
    return sorted(出)


def 源码里有而没跑过的():
    """`{套: [没跑过的题号]}` —— 源码里写了、而结果文件里一次都没出现的题。

    ⚠️⚠️ **`{...}` 字面量和 `dict(...)` 调用都要认。** 2026-11-10 第一版只扫了
    `ast.Dict`,而 `pattern_eval.py` 的题是 `dict(id="P01", …)` 写的 ——
    于是它扫出 **0 道**然后报「没问题」,而那一套明明欠着 9 道。
    > 一条「全都跑过了」和一条「一处都没扫到」,**在那句绿字上长得一模一样。**
    (这是我同一天第三次被「扫不到东西却报没问题」咬到,
     每次救回来的都是那句「样本量 0 —— 这不叫通过,这叫没扫到东西」。)
    """
    import ast as _ast
    import glob as _glob
    键 = ("id", "题号", "case", "题")
    出 = {}
    for p in sorted(_glob.glob(os.path.join(ROOT, "agent", "*_eval.py"))):
        套 = os.path.basename(p)[:-len("_eval.py")]
        try:
            t = _ast.parse(io.open(p, encoding="utf-8", errors="replace").read(), p)
        except SyntaxError:
            continue
        源 = set()
        for x in _ast.walk(t):
            if isinstance(x, _ast.Dict):
                for k, v in zip(x.keys, x.values):
                    if (isinstance(k, _ast.Constant) and k.value in 键
                            and isinstance(v, _ast.Constant)
                            and isinstance(v.value, str)):
                        源.add(v.value)
            elif isinstance(x, _ast.Call):
                for kw in x.keywords:
                    if (kw.arg in 键 and isinstance(kw.value, _ast.Constant)
                            and isinstance(kw.value.value, str)):
                        源.add(kw.value.value)
        if not 源:
            continue
        跑 = None
        for f in (f"{套}-eval-results.jsonl", f"{套}-results.jsonl"):
            fp = os.path.join(ROOT, "agent", f)
            if os.path.exists(fp):
                跑 = {i for s, i in 题们() if s == re.sub(r"-eval$", "", 套)}
                break
        if 跑 is None:
            continue              # 这套还没跑过任何一轮 —— 另一件事,不在这条判据里
        缺 = sorted(源 - 跑)
        if 缺:
            出[套] = 缺
    return 出


def main():
    print("评测集频率分层 · 判据")
    print("=" * 96)

    # ── ⓪ 口径模块自己先过 ────────────────────────────────────────────
    坏 = T.自测()
    ck("口径模块自测过(门槛、目标占比、前缀优先、「不打标」和「没登记」分得开)",
       not 坏, len(T.分层表()), "；".join(坏) if 坏 else "口径读得出、互相不矛盾")

    全 = 题们()
    套们 = sorted({s for s, _ in 全})
    print(f"\n  ℹ 版本库里的结果文件:**{len(全)} 题 / {len(套们)} 套**"
          f"(三种题号字段都数了)")

    # ── ① 新加的套不许漏打标 ──────────────────────────────────────────
    没登记 = sorted({s for s in 套们 if not T.认得这套吗(s)})
    ck("每一套真跑过的题集,都在口径里登记过(新加题集漏打标 → 当场红)",
       not 没登记, len(套们),
       f"{没登记} 没登记 —— 要么给它打频率标,要么写进「不打频率标」"
       f"或「不是题集」,**三件事都要写明理由**" if 没登记
       else f"{len(套们)} 套都登记了")

    计, 标外, 范围外, 不认得 = T.分布(全)
    ck("每一道题都落到某一层、或落进「不打标」/「不是题集」(落不下去 → 红)",
       not 不认得, len(全),
       f"{不认得[:4]} 落不下去" if 不认得
       else f"打了标 {sum(计.values())} 题、另一个维度的 {标外} 题、"
            f"不是题集的 {范围外} 条,一道不剩")

    # ── ② 反向检查:分层表里不许留已经不存在的条目 ──────────────────────
    真有的 = set()
    for 套, 题号 in 全:
        m = re.match(r"^([A-Za-z]{1,3})", 题号)
        真有的.add((套, m.group(1).upper() if m else None))
        真有的.add((套, None))
    过期 = sorted(k for k in T.分层表() if k not in 真有的)
    ck("分层表里点名的套 / 场景都真实存在(过期条目 → 红,囤积的和真的长得一样)",
       not 过期, len(T.分层表()),
       f"{过期[:4]} 在结果文件里找不到" if 过期 else f"{len(T.分层表())} 条都对得上")

    # ── ③ 棘轮:每层题数只许涨 ────────────────────────────────────────
    旧 = {}
    if os.path.exists(基线文件):
        try:
            旧 = json.load(io.open(基线文件, encoding="utf-8"))
        except Exception as e:
            print(f"  {Y}⚠️ 基线文件读不了({e})—— 当成第一次登记{D}")
    拦, 为什么 = 登记拦不拦(计, 旧)
    ck("每一层的题数只许涨不许降(**删题也能让比例靠近 60/30/10,而那是把评测集变弱**)",
       not 拦, sum(计.values()),
       为什么 if 拦
       else f"日常 {计['日常']} · 偶发 {计['偶发']} · 罕见 {计['罕见']}"
            + (f"(基线 {[旧.get(k) for k in T.层名]})" if 旧 else "(还没有基线)"))
    涨了 = {k: (计[k], 旧.get(k)) for k in T.层名
            if isinstance(旧.get(k), int) and 计[k] > 旧[k]}
    if 涨了:
        # ⚠️ 这行印在**通过**路径上 —— 推棘轮的那只手必须看得见
        print(f"     {Y}ℹ️ 有层补了题:{涨了} —— "
              f"跑 `python3 tools/eval_tier_check.py --登记` 把基线推上去{D}")

    # ── ④ 目标分布 60/30/10:只报缺口,不判红 ──────────────────────────
    总 = sum(计.values())
    目标 = T.目标占比()
    if 总:
        print(f"\n  ℹ **离目标 60/30/10 还差多少**(用户 2026-11-10 拍的目标):")
        # 分母由「不许再加」的那一层钉住:偶发已经超了,所以总量要按它反推
        需总 = max(int(round(计[k] / 目标[k])) for k in T.层名 if 计[k])
        for k in T.层名:
            该有 = int(round(需总 * 目标[k]))
            print(f"       {k}:{计[k]} 题 / {计[k] * 100 // 总}%"
                  f"(目标 {int(目标[k] * 100)}%)—— 该有 {该有},"
                  + (f"**缺 {该有 - 计[k]}**" if 该有 > 计[k] else "够了,别再加"))
        print(f"       {Y}⚠️ 补缺口只能**加题**,不许改标签去凑 —— "
              f"改标签会让那一层的分数当场失去意义,而报告照旧印「达标」{D}")

    # ── ⑤ 样本量下限(地板) ───────────────────────────────────────────
    下限, 门 = T.样本量下限(), T.门槛()
    不够的 = {k: 计[k] for k in T.层名 if 门.get(k) is not None and 计[k] < 下限}
    ck(f"设了门槛的层,题数都够 {下限} 题(**空集合上所有性质都成立**)",
       not 不够的, len([k for k in T.层名 if 门.get(k) is not None]),
       f"{不够的} 不够 {下限} 题,那一层的通过率说明不了什么" if 不够的
       else "设门槛的层样本量都够")
    无门槛 = [k for k in T.层名 if 门.get(k) is None]
    ck("不设门槛的层,口径里写明了为什么(而不是悄悄不判)",
       all(f"**{k}" in T._读() or k in T._读() for k in 无门槛), len(无门槛) or 1,
       f"{无门槛} 不参与放行判定 —— 口径里写着「样本量不够当门槛」")

    # ── ⑤b 源码里写了题,而那道题从没真跑过 ────────────────────────────
    #
    # 并行会话 2026-11-10 查实:`pattern_eval.py` 源码 21 道,结果文件只有 12 道 ——
    # 后加的 9 道**从 10-07 起一次都没真跑过**。而分层只数结果文件,
    # 所以那 9 道从来没进过任何分层数。
    # > **「源码里写了题」和「那道题真跑过」在分层表上长得一模一样** ——
    # > 这和项目里「我写了检查 ≠ 检查在跑」是同一件事,只是换成了题。
    # 而它更隐蔽:加了题的人会以为覆盖变好了,而那 9 道一分都没贡献。
    #
    # ⚠️ 全项目量过:只有 pattern 一套有这个问题(9 道),其余 14 套源码和结果**完全对得上**。
    # 数字小,所以**直接判红,不走棘轮** —— 棘轮是给「红在一堆既存合法事实上」的那种判据用的。
    _缺跑 = 源码里有而没跑过的()
    ck("源码里写了的题都真跑过(**加了题没跑 = 覆盖一分没涨,而分层表上看不出来**)",
       not _缺跑, sum(len(v) for v in _缺跑.values()) + len(全) and max(1, len(套们)),
       "；".join(f"{k} 欠 {len(v)} 道({'、'.join(v[:4])}"
                 + (f" ……还有 {len(v) - 4} 道" if len(v) > 4 else "") + ")"
                 for k, v in _缺跑.items())
       + " —— 跑一遍那一套就绿(**但别把「跑起来」记成「补题」**:"
       "两件事在题数上都表现为涨,而意义完全不同)" if _缺跑
       else f"{len(套们)} 套的源码题号都在结果文件里出现过")

    # ── ⑥ 诚实声明:这份频率还没拿流量对过账 ──────────────────────────
    文 = T._读()
    # ⚠️ 认**那一句**,不认「对过账」这三个字 —— 后者在这份 md 里还有别的出处,
    # 于是删掉要紧那一句之后判据照旧是绿的(「判据贴着字面而不是含义」的反面:
    # 这里要贴紧那一句,因为要守的就是**那一句话还在不在**)。
    有那句 = "还没拿真实流量对过账" in 文
    ck("口径里留着「这份频率还没拿真实流量对过账」那句话"
       "(**没流量可对账不判红,少了那句话判红**)",
       有那句, 1,
       "留着 —— 将来有真实流量了,拿流量频率和那张表对账" if 有那句
       else "那句话被删了 —— 删掉它,这份判出来的频率就会被当成有依据的")

    # ── ⑦ `--登记` 那道闸,门禁跑不到它 —— 所以在这儿自测一遍 ────────────
    # 少了这几条,那道闸就是「坏了的表现是一切正常」那一类:
    # 直到有人删了题又跑一次 `--登记`,基线当场被重设下来,而没有任何迹象。
    三 = {"日常": 100, "偶发": 50, "罕见": 10}
    闸 = [
        (登记拦不拦({"日常": 99, "偶发": 50, "罕见": 10}, 三)[0] is True, "降了 → 拦"),
        (登记拦不拦({"日常": 101, "偶发": 50, "罕见": 10}, 三)[0] is False, "涨了 → 放行"),
        (登记拦不拦(三, 三)[0] is False, "没变 → 放行"),
        (登记拦不拦(三, {})[0] is False, "第一次登记(没基线)→ 放行"),
        (登记拦不拦(三, {"日常": "坏"})[0] is False, "基线里是脏值 → 不当成数,放行"),
    ]
    ck("`--登记` 只许涨(降了要拦、涨了放行、第一次放行)—— **门禁跑不到那一支**",
       all(ok for ok, _ in 闸), len(闸),
       "；".join(名 for ok, 名 in 闸 if not ok) or "五种情形都对")

    if FAIL:
        print(f"\n{R}❌ 评测集分层 {len(FAIL)} 处不符合预期{D}")
        for f in FAIL:
            print(f"   · {f}")
        return 1
    print(f"\n{G}✅ 评测集分层符合预期{D}")
    return 0


def 登记():
    计 = T.分布(题们())[0]
    旧 = {}
    if os.path.exists(基线文件):
        旧 = json.load(io.open(基线文件, encoding="utf-8"))
    拦, 为什么 = 登记拦不拦(计, 旧)
    if 拦:
        print(f"{R}❌ 不登记:{为什么},这道闸只许涨{D}")
        return 1
    新 = {k: 计[k] for k in T.层名}
    新["更新于"] = __import__("datetime").date.today().isoformat()
    io.open(基线文件, "w", encoding="utf-8").write(
        json.dumps(新, ensure_ascii=False, indent=2) + "\n")
    print(f"{G}✅ 基线已登记:{新}{D}")
    return 0


if __name__ == "__main__":
    sys.exit(登记() if "--登记" in sys.argv else main())
