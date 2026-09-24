#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验对比 —— 同一套题,两个版本并排比,并且**先判这个对比成不成立**。

## 为什么要有这一页

调完提示词、换完模型描述之后,人只会问一句:「好了还是坏了?」
而这个项目为「拿两个数直接相减」栽过五次(见 agent/rounds.py 开头那份清单),
最贵的一次是**单轮 7/8 → 5/8 被当成退步**,回头查一个根本不存在的退化。

所以这一页不是「把两个分数放一起」。它要先回答三个前置问题:

    ① 这两次是**同一个模型、同一个供应商**跑的吗?       不是 → 比的是模型,不是你的改动
    ② 版本之间的差,比**轮内抖动**大吗?                  不大 → 说明不了任何事
    ③ 翻面的那几题,是**判据吃措辞**还是**行为真变了**?  两者的修法相反

**这三条的判词不在这里重写一遍** —— 全部调 `agent/rounds.py` 和 `agent/evalrec.py`,
把它们打印的原话收进来照搬。一段逻辑有两份拷贝,就注定有一份是漏的
(rounds 自己的注释里记着:同一段在四个评测里各抄了一遍,每抄一遍都漏过东西)。

## 两个版本从哪来:git,不另起一套存档

评测结果文件(`agent/*-results.jsonl`)**只存最新一次** —— 每跑一次就覆盖。
但它们是进版本库的,所以**历史全在 git 里**:一次提交 = 一次跑的存档,
而且每行自带来路(供应商 / 模型 / 代码 / 跑于)。

不另建一个 runs/ 目录的理由:再建一个存档,就有两份历史,
而**两份历史一定会漂**;git 那份还顺带带着「这一版代码是什么」——
那正是归因要用的东西。

## 它看得出什么、看不出什么

看得出:哪几题从过变挂、从挂变过,各自的原话和轨迹;这个差值有没有被抖动淹掉。
**看不出**:真实通过率是多少(那要几十轮)。所以这里只说方向,不说置信区间 ——
一个报了置信区间的两轮结果,比一个只说「比不了」的更危险。
"""
import ast, glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import rounds as _rd          # noqa: E402  抖动、分类、报(判词的唯一源头)

咬合 = [
    ("把「供应商/模型不同就拒收」那一支去掉", "换了模型就不许比"),
    ("把「抖动 ≥ 版本差」那一支去掉", "抖动淹掉版本差时要说比不了"),
    ("比较时把两边题号不一样这件事咽下去(只比交集不吭声)", "题集不一样要说出来"),
    ("把翻面按原因分类去掉(轨迹类和内容类混成一堆)", "翻面要按原因分开"),
    ("把「只跑了一轮」当成能下结论", "只跑一轮不许下结论"),
]


# ── 读:一个版本的结果 ────────────────────────────────────────────
def _真(v):
    """结果文件里的值有时是 True,有时是字符串 "True" —— 两种都要认。

    ⚠️ 这不是洁癖:一个把 "False" 当成真的比较页,**会把退步报成持平**,
    而页面上看不出任何异常(非空字符串在 Python 里就是真)。
    """
    if isinstance(v, bool): return v
    if isinstance(v, str):
        try: return bool(ast.literal_eval(v))
        except Exception: return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


def _列(v):
    if isinstance(v, list): return v
    if isinstance(v, str):
        try:
            x = ast.literal_eval(v)
            return x if isinstance(x, list) else []
        except Exception: return []
    return []


# 题号字段名各套不一样:多数是 `id`,判责那套是 `case`,识图那套是 `spu`。
# ⚠️ **写死 `id` 会在换一套题时当场 KeyError**(2026-09-24 踩到);
# 更糟的是如果我当初写的是 `r.get("id")`,它会**静默地把所有题都当成同一题**,
# 而页面上看起来只是「这套题只有一道」。所以:认得出就用,认不出就明说不能比。
题号候选 = ("id", "case", "spu", "题", "q")


def 题号键(rows):
    """这套结果用哪个字段当题号。认不出返回 None(**不猜**)。"""
    if not rows: return None
    for k in 题号候选:
        vs = [r.get(k) for r in rows]
        if all(v is not None for v in vs) and len(set(map(str, vs))) == len(rows):
            return k                      # 必须**每行都有且互不相同**,否则不是题号
    return None


def 能不能比这套(rows):
    """这份结果文件的形状撑不撑得起「逐题对比」。返回 (行不行, 为什么)。"""
    if not rows: return False, "这个版本里没有结果行"
    if not any("passed" in r for r in rows):
        return False, ("这份结果不是「逐题过/挂」的形状(没有 passed 列)—— "
                       "比如野外巡检记的是一致性,不是对错,**换一套题比**")
    if not 题号键(rows):
        return False, (f"认不出哪个字段是题号(找过 {'、'.join(题号候选)})—— "
                       "**不猜**:猜错会把所有题当成同一题,而页面上只显示成「这套只有一道题」")
    return True, ""


def 规整(rows):
    出 = []
    for r in rows:
        d = dict(r)
        d["过"] = _真(r.get("passed"))
        d["各轮"] = [_真(x) for x in _列(r.get("各轮过"))] or [d["过"]]
        d["理由"] = _列(r.get("why"))
        出.append(d)
    return 出


def 套们():
    """有哪些评测套可以比。**排除 partial**(没跑完的那半份不许当一个版本)。"""
    出 = []
    for p in sorted(glob.glob(os.path.join(ROOT, "agent", "*results*.jsonl"))):
        rel = os.path.relpath(p, ROOT)
        if ".partial." in rel: continue
        出.append(dict(套=os.path.basename(p).replace("-results.jsonl", "")
                       .replace("-results", "").replace(".jsonl", ""), 文件=rel))
    return 出


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                          text=True, timeout=30).stdout


def 版本们(文件, 限=12):
    """这套题的历次跑分 = 这个文件的历次提交。最新在前。"""
    出 = []
    log = _git("log", f"-{限}", "--format=%H\t%ad\t%s", "--date=format:%Y-%m-%d %H:%M",
               "--", 文件)
    for line in log.strip().splitlines():
        sha, 日期, 题 = (line.split("\t", 2) + ["", ""])[:3]
        rows = 读版本(文件, sha)
        if not rows: continue
        出.append(dict(sha=sha, 短=sha[:7], 提交日期=日期, 提交信息=题, **摘要(rows)))
    return 出


def 读版本(文件, sha=None):
    try:
        t = _git("show", f"{sha}:{文件}") if sha else \
            open(os.path.join(ROOT, 文件), encoding="utf-8").read()
    except Exception:
        return []
    rows = []
    for line in t.splitlines():
        line = line.strip()
        if not line: continue
        try: rows.append(json.loads(line))
        except Exception: pass
    return 规整(rows)


def 摘要(rows):
    n = len(rows)
    键 = 题号键(rows)
    过 = sum(1 for r in rows if r["过"])
    轮 = max((len(r["各轮"]) for r in rows), default=1)
    翻, 各轮 = 轮内抖动(rows, 键)
    def 一(k): 
        v = {str(r.get(k)) for r in rows if r.get(k) is not None}
        return next(iter(v)) if len(v) == 1 else ("、".join(sorted(v)[:2]) + "…" if v else None)
    return dict(题数=n, 过=过, 轮数=轮, 轮内翻面=len(翻), 各轮过=各轮, 题号字段=键,
                模型=一("模型"), 供应商=一("供应商"), 代码=一("代码"), 跑于=一("跑于"))


def 轮内抖动(rows, 键=None):
    """**同一次跑的两轮之间**有几题翻面 —— 这是「差多少才算数」的尺子。"""
    k = 键 or 题号键(rows)
    if not k: return [], [sum(1 for r in rows if r["过"])]
    轮 = max((len(r["各轮"]) for r in rows), default=1)
    多 = [{r[k]: (r["各轮"][i] if i < len(r["各轮"]) else r["过"]) for r in rows}
          for i in range(轮)]
    return _rd.抖动(多)


# ── 这个对比成不成立 ─────────────────────────────────────────────
# ⚠️ **不能拿 rounds.报() 的返回值当「可比」用。** 它返回的是「这一批稳不稳」
# (`not 翻`),不是「这两版能不能比」—— 2026-09-24 当场踩到:基线因为换了模型
# 被明确拒收,而 报() 照样返回 True(因为这一批没翻面)。
# **两个含义共用一个返回值,就迟早有一次接错。**
#
# 所以这里按三条原语自己判,每条都向拥有它的模块要:
#   · 来路能不能比        → evalrec.基线能不能比(它的口径:供应商/模型必须同,代码本来就该不同)
#   · 跑了几轮            → rounds 的规矩:只跑一轮不能下结论
#   · 版本差顶不顶得过抖动 → rounds 的规矩(这一条这里有一份拷贝,**用自测钉住**:
#     下面的自测会拿 报() 打印的原话和这里的结论对一遍,哪天 rounds 改了口径,这里当场红)
结论说 = {
    "单轮":     "只跑了一轮 —— 不能下结论(这个项目为此栽过五次)",
    "来路不明": "基线没说是谁跑的 —— 不拿它比",
    "换了模型": "供应商/模型换了 —— 比的是模型,不是你的改动",
    "没变化":   "两轮逐题一致、和基线一模一样 —— **没测出差别**,不是「证明了没差别」",
    "被淹":     "轮间抖动 ≥ 版本差 —— 这个对比说明不了任何事",
    "有意义":   "版本差大于轮间抖动 —— 有意义(样本小,只能说方向)",
}


def 判可比(摘A, 摘B, 多B):
    翻, 各轮 = _rd.抖动(多B)
    if len(多B) < 2:                       return False, "单轮"
    if not 摘A.get("模型") or not 摘A.get("供应商"): return False, "来路不明"
    try:
        import evalrec
        能, _说 = evalrec.基线能不能比(
            {"供应商": 摘A["供应商"], "模型": 摘A["模型"], "代码": 摘A["代码"]},
            {"供应商": 摘B["供应商"], "模型": 摘B["模型"], "代码": 摘B["代码"]})
    except Exception:
        能 = False                          # 判不了就**不叫可比**,不假装判过
    if not 能:                              return False, "换了模型"
    版本差, 轮间差 = abs(各轮[-1] - 摘A["过"]), len(翻)
    if 轮间差 == 0 and 版本差 == 0:          return True, "没变化"
    if 轮间差 >= 版本差:                     return False, "被淹"
    return True, "有意义"


# ── 比 ───────────────────────────────────────────────────────────
def 比(文件, shaA, shaB):
    """A 是**旧的那版(基线)**,B 是新的。返回结构化结果 + 判词原话。"""
    A, B = 读版本(文件, shaA), 读版本(文件, shaB)
    if not A or not B:
        return dict(错="有一边读不出来(这个提交里没有这份结果文件)")
    for 边, rows in (("旧版", A), ("新版", B)):
        行, why = 能不能比这套(rows)
        if not 行: return dict(错=f"{边}:{why}")
    kA, kB = 题号键(A), 题号键(B)
    if kA != kB:
        return dict(错=f"两边的题号字段不一样(旧版用 {kA}、新版用 {kB})—— "
                      f"**题号换过名,这两份对不起来**,得先说清哪个题号对应哪个")
    甲, 乙 = {r[kA]: r for r in A}, {r[kB]: r for r in B}
    共 = [k for k in 乙 if k in 甲]
    只甲, 只乙 = [k for k in 甲 if k not in 乙], [k for k in 乙 if k not in 甲]

    逐题 = []
    for k in sorted(共, key=str):
        a, b = 甲[k], 乙[k]
        向 = "一致" if a["过"] == b["过"] else ("变好" if b["过"] else "变坏")
        逐题.append(dict(id=k, 题面=b.get("q") or a.get("q"),
                        A过=a["过"], B过=b["过"], 变化=向,
                        A轮=a["各轮"], B轮=b["各轮"],
                        A理由=a["理由"], B理由=b["理由"],
                        A工具=a.get("tools"), B工具=b.get("tools"),
                        类=_rd.分类((a["理由"] if a["过"] is False else []) + b["理由"])
                          if 向 != "一致" else None))
    变坏 = [x for x in 逐题 if x["变化"] == "变坏"]
    变好 = [x for x in 逐题 if x["变化"] == "变好"]

    # ── 判词:**全部由 rounds.报 出**,这里一个字都不自己写 ──────────
    词 = []
    def 收(s): 词.append(re.sub(r"\033\[\d+m", "", str(s)))
    摘A, 摘B = 摘要(A), 摘要(B)
    多B = [{r[kB]: (r["各轮"][i] if i < len(r["各轮"]) else r["过"]) for r in B}
           for i in range(max((len(r["各轮"]) for r in B), default=1))]
    原因B = [{r[kB]: r["理由"] for r in B} for _ in 多B]
    _rd.报(多B, 基线通过数=摘A["过"], 名=os.path.basename(文件), 日志=收, 原因=原因B,
           基线来路={"供应商": 摘A["供应商"], "模型": 摘A["模型"], "代码": 摘A["代码"]},
           本轮来路={"供应商": 摘B["供应商"], "模型": 摘B["模型"], "代码": 摘B["代码"]})
    可比, 结论 = 判可比(摘A, 摘B, 多B)
    # 题集对不上要**说出来**:只比交集而不吭声,等于悄悄换了分母
    if 只甲 or 只乙:
        词.insert(0, f"  ⚠ **两边题集不一样**:旧版多 {len(只甲)} 题{只甲[:4]}、"
                     f"新版多 {len(只乙)} 题{只乙[:4]} —— 下面只比两边都有的 {len(共)} 题,"
                     f"**分数别直接相减**")
    return dict(文件=文件, A=dict(sha=shaA, **摘A), B=dict(sha=shaB, **摘B),
                共有=len(共), 只甲=只甲, 只乙=只乙,
                逐题=逐题, 变好=[x["id"] for x in 变好], 变坏=[x["id"] for x in 变坏],
                可比=bool(可比), 结论=结论, 判词=词)


# ── 自测 ─────────────────────────────────────────────────────────
def _造(ids, 过, 轮=None, 模型="claude-haiku-4-5", 供应商="claude", 代码="aaa", 理由=None):
    return [dict(id=i, q=f"题 {i}", passed=str(过.get(i, True)),
                 各轮过=str((轮 or {}).get(i, [过.get(i, True)] * 2)),
                 why=str((理由 or {}).get(i, [])),
                 模型=模型, 供应商=供应商, 代码=代码, 跑于="2026-09-24 10:00")
            for i in ids]


def _自测():
    过, 挂 = [], []
    def ck(名, 真, 补=""):
        (过 if 真 else 挂).append(名)
        print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")

    ids = [f"Q{i:02d}" for i in range(1, 9)]
    import tempfile
    d = tempfile.mkdtemp()
    def 存(name, rows):
        p = os.path.join(d, name)
        open(p, "w", encoding="utf-8").write(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
        return p
    # 用一个假的读版本:直接读文件(不走 git)
    真读 = globals()["读版本"]
    def 假读(文件, sha=None): 
        return 规整([json.loads(l) for l in open(文件 if sha is None else sha,
                                                 encoding="utf-8") if l.strip()])
    globals()["读版本"] = lambda 文件, sha=None: 假读(sha or 文件)

    # ① 字符串 "False" 不许被当成真
    ck("结果文件里的字符串 False 判成假", _真("False") is False and _真("True") is True)

    # ② 换了模型 → 拒收
    a = 存("a.jsonl", _造(ids, {}, 模型="claude-haiku-4-5"))
    b = 存("b.jsonl", _造(ids, {"Q01": False}, 模型="deepseek-v4-pro", 供应商="deepseek"))
    r = 比("x", a, b)
    ck("换了模型就不许比",
       (not r["可比"]) and r["结论"] == "换了模型"
       and any("不拿它当基线" in w for w in r["判词"]),
       (r["结论"], [w for w in r["判词"] if "基线" in w][:1]))

    # ③ 抖动 ≥ 版本差 → 说明不了
    a = 存("a2.jsonl", _造(ids, {}))
    b = 存("b2.jsonl", _造(ids, {"Q01": False}, 轮={"Q01": [True, False], "Q02": [False, True]}))
    r = 比("x", a, b)
    ck("抖动淹掉版本差时要说比不了",
       (not r["可比"]) and r["结论"] == "被淹"
       and any("说明不了任何事" in w for w in r["判词"]),
       (r["结论"], [w for w in r["判词"] if "说明不了" in w][:1]))

    # ④ 没抖也没变 → 「没有变化可报」,不许说「说明不了任何事」
    a = 存("a3.jsonl", _造(ids, {}))
    b = 存("b3.jsonl", _造(ids, {}, 代码="bbb"))
    r = 比("x", a, b)
    ck("没抖也没变要说「没有变化可报」",
       r["结论"] == "没变化" and any("没有变化可报" in w for w in r["判词"])
       and not any("说明不了任何事" in w for w in r["判词"]), r["结论"])

    # ⑤ 题集不一样要说出来(而不是悄悄只比交集)
    a = 存("a4.jsonl", _造(ids, {}))
    b = 存("b4.jsonl", _造(ids + ["Q09", "Q10"], {}))
    r = 比("x", a, b)
    ck("题集不一样要说出来", any("题集不一样" in w for w in r["判词"]) and r["共有"] == 8,
       [w for w in r["判词"] if "题集" in w][:1])

    # ⑥ 翻面要按原因分开(轨迹类 vs 内容类,修法相反)
    a = 存("a5.jsonl", _造(ids, {}))
    b = 存("b5.jsonl", _造(ids, {"Q01": False, "Q02": False},
                          轮={"Q01": [False, False], "Q02": [False, False]},
                          理由={"Q01": ["轨迹:实际调了 [无]"], "Q02": ["内容:没提到 统计"]}))
    r = 比("x", a, b)
    类 = {x["id"]: x["类"] for x in r["逐题"] if x["变化"] == "变坏"}
    ck("翻面要按原因分开", 类.get("Q01") == "轨迹" and 类.get("Q02") == "内容", 类)

    # ⑦ 只跑一轮 → 不能下结论
    a = 存("a6.jsonl", _造(ids, {}))
    b = 存("b6.jsonl", _造(ids, {}, 轮={i: [True] for i in ids}))
    r = 比("x", a, b)
    ck("只跑一轮不许下结论",
       (not r["可比"]) and r["结论"] == "单轮"
       and any("只跑了一轮" in w for w in r["判词"]),
       (r["结论"], [w for w in r["判词"] if "一轮" in w][:1]))
    # 版本差顶得过抖动 → 「有意义」,而且 rounds 也得同意
    a = 存("a8.jsonl", _造(ids, {i: False for i in ids[:4]}))
    b = 存("b8.jsonl", _造(ids, {}))
    r = 比("x", a, b)
    ck("版本差顶过抖动时两边都说有意义",
       r["可比"] and r["结论"] == "有意义"
       and any("这个对比有意义" in w for w in r["判词"]),
       (r["结论"], [w for w in r["判词"] if "有意义" in w][:1]))

    # ⑧ 变好/变坏要分得出来
    a = 存("a7.jsonl", _造(ids, {"Q01": False}))
    b = 存("b7.jsonl", _造(ids, {"Q02": False}))
    r = 比("x", a, b)
    ck("变好和变坏分得开", r["变好"] == ["Q01"] and r["变坏"] == ["Q02"],
       (r["变好"], r["变坏"]))

    # ⑨ 题号字段换成 case(判责那套)也认得出来
    def _造case(ids):
        return [dict(case=i, passed="True", 各轮过="[True, True]", why="[]",
                     模型="claude-haiku-4-5", 供应商="claude", 代码="aaa") for i in ids]
    a = 存("a9.jsonl", _造case(ids)); b = 存("b9.jsonl", _造case(ids))
    r = 比("x", a, b)
    ck("题号字段是 case 也比得了", not r.get("错") and r["共有"] == 8, r.get("错"))

    # ⑩ 认不出题号就**明说**,不猜(猜错会把所有题当成同一题)
    a = 存("a10.jsonl", [dict(passed="True", why="[]", 模型="m", 供应商="c", 代码="a")] * 3)
    r = 比("x", a, a)
    ck("认不出题号就明说,不猜", "认不出哪个字段是题号" in (r.get("错") or ""), r.get("错"))

    # ⑪ 不是「逐题过/挂」形状的(野外巡检那种)要拒收,不许当成全挂
    a = 存("a11.jsonl", [dict(q=f"问{i}", runs=3, 一致=True) for i in range(4)])
    r = 比("x", a, a)
    ck("不是逐题过/挂的形状要拒收", "不是「逐题过/挂」的形状" in (r.get("错") or ""), r.get("错"))

    globals()["读版本"] = 真读
    print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv: sys.exit(_自测())
    套 = 套们()
    if len(sys.argv) < 2:
        print("有这些套可以比(带 git 历史的版本数):")
        for s in 套:
            n = len(_git("log", "--format=%H", "--", s["文件"]).strip().splitlines())
            print(f"  {s['套']:18s} {n:>3} 个版本   {s['文件']}")
        print("\n用法:python3 agent/compare.py <套名> [旧版sha 新版sha]")
        raise SystemExit
    名 = sys.argv[1]
    s = next((x for x in 套 if x["套"] == 名), None)
    if not s: print(f"没有这套:{名}"); raise SystemExit(1)
    vs = 版本们(s["文件"])
    if len(sys.argv) >= 4:
        r = 比(s["文件"], sys.argv[2], sys.argv[3])
    else:
        if len(vs) < 2: print("只有一个版本,比不了"); raise SystemExit
        r = 比(s["文件"], vs[1]["sha"], vs[0]["sha"])
    if r.get("错"): print(r["错"]); raise SystemExit(1)
    print(f"{r['文件']}  旧 {r['A']['sha'][:7]} → 新 {r['B']['sha'][:7]}")
    print(f"  旧:{r['A']['过']}/{r['A']['题数']} · {r['A']['模型']} · 代码 {r['A']['代码']} · {r['A']['跑于']}")
    print(f"  新:{r['B']['过']}/{r['B']['题数']} · {r['B']['模型']} · 代码 {r['B']['代码']} · {r['B']['跑于']}")
    print(f"  变好 {r['变好']}  变坏 {r['变坏']}")
    for w in r["判词"]: print(w)
