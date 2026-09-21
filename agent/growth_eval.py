#!/usr/bin/env python3
"""成长推算评测 —— 问的不是「系统坏没坏」,是「**模型行不行**」。

## 为什么单独要这一套

生命周期这块原来有 6 条回答体检(g10–g15),但**一条模型评测都没有**。
两者问的问题完全不同:

    检查(guards_test)  人写的正反用例,不调模型 —— 「规则本身对不对」
    评测(这个文件)    真调模型 —— 「**模型真上手时会不会犯那个错**」

**为一个风险装了六道锁,不等于量过那个风险有多大。**
锁可能拦住了 100%,也可能模型压根不会犯、六道锁全是白装的 ——
不测就永远不知道自己在防一个多大的东西。

## 三个轴(和 tool_eval 同一把尺子)

    轨迹  该调的工具调了没(比如问孩子却没去查着装人)
    内容  该说的说了没(区间端点、复量、转人工)、不该说的说了没
    体检  guards 有没有打回 —— **体检不是加分项,是负分项**

## 每道题盯一个具体风险

不是「随便问几句看它答得好不好」。每一道都对着一个**已知会出事的地方**:
区间被吞掉、拿家长尺寸算孩子、过期记录接着用、两个口径打架时自己挑一边。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "backend"),
                os.path.join(HERE, "..", "knowledge"),
                os.path.join(HERE, "..", "agentsite")]
import api
import textmatch as tm

RE_THOUSAND = re.compile(r"(?<=\d),(?=\d{3}\b)")


def _norm(t):
    return RE_THOUSAND.sub("", t or "")


def hit(text, group, negation=False):
    """must 类不查否定,forbid 类才查 —— 和 tool_eval 同一条规矩。"""
    for src in (text or "", _norm(text)):
        w = tm.says(src, group) if negation else tm.mentions(src, group)
        if w: return w
    return None


# ── 锚点:从库里现算 ────────────────────────────────────────────────────
# 现算的好处是数据变了跟着变,代价是实现错了锚点跟着错(同源谬误)——
# 所以 __main__ 里跑之前先验 pinned_check 那 13 条手抄常数。
def A():
    d = {}
    for wid in ("W10004-2", "W10007-2", "W10010-2", "W10013-2",
                "W10016-2", "W10019-2", "W10001-2"):
        w = api.get_wearer(wearer_id=wid)["着装人"][0]
        f = api.forecast_growth(wid, months=12)
        d[wid] = dict(name=w["姓名"], h=w.get("最近身高"),
                      expired=(w.get("量体是否过期") or {}).get("过期"),
                      pred=f["预测身高"], lo=f["区间"][0], hi=f["区间"][1],
                      spurt=f["跨突增期"],
                      conflict=(f.get("靶身高校验") or {}).get("需人工确认"))
    return d


K = A()


# ── 夹具的**前提**必须成立,否则那道题测不到东西 ────────────────────────
#
# 这套题的每一道都挑了一个**带特定状态**的孩子:
# 「过期记录接着用」挑的是量体已过期的,「跨突增期」挑的是明年要窜个儿的,
# 「靶身高冲突」挑的是预测和父母身高对不上的。
#
# ⚠️ **而状态会漂。** 哪天有人给那个孩子补一次量体,「过期」那道题
# 就**静默变成永远通过** —— 模型不再警告过期是**正确的**,而判据要的就是那个警告。
#
# **一道测不到东西的题,和一道通过的题,在成绩单上长得一模一样。**
# 这比「永远失败」危险得多:永远失败至少会有人来查。
#
# (同一个病在 member_eval 上发作过一次:题面写死的客户号,
#  那个客户后来一条积分流水都没有了,而判据还说「他有 2 处余额对不上」。)
前提 = [
    ("W10016-2", "expired", True,  "「过期记录接着用」那道题要一个**量体已过期**的孩子"),
    ("W10010-2", "expired", True,  "「过期 + 突增」那道题同样要过期"),
    ("W10019-2", "spurt",   True,  "「跨突增期」那道题要一个明年要窜个儿的孩子"),
    ("W10019-2", "conflict", True, "「靶身高冲突」那道题要预测和父母身高对不上的"),
    ("W10004-2", "expired", False, "「正常预测」那道题要一个**量体没过期**的,"
                                   "否则模型会去讲过期,而这道题不测那个"),
]
_坏 = [f"{w}.{k} 现在是 {K[w][k]},而 {说明}"
       for w, k, 应, 说明 in 前提 if K.get(w, {}).get(k) is not 应]
if _坏:
    print("❌ **夹具的前提不成立了,这套题测不到它想测的东西**:")
    for x in _坏: print("   ·", x)
    print("   → 换一个符合条件的孩子,或者把那道题删掉。"
          "**不许就这么跑** —— 跑出来的分是假的。")
    sys.exit(1)



def _n(x):
    """142.3 → ('142.3','142')  —— 模型可能只写整数"""
    return (f"{x:g}", f"{int(round(x))}")


# (编号, 盯的风险, 问题, need 轨迹, must 内容组, forbid 内容)
def _G03现状():
    """现读:这个孩子的两个口径到底打不打架。**不写死,从口径模块算。**

    读的是**状态**(打不打架),不是**答案**(该说什么)——
    同源谬误防的是后者(期望值由被测系统算);前者只能这么读,
    而「数据变了而判据不变」正是这道题连挂两轮的原因。
    """
    try:
        import sqlite3
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
        import growth as _g
        c = sqlite3.connect(os.path.join(os.path.dirname(HERE), "backend", "lanxiu.db"))
        c.row_factory = sqlite3.Row
        w = c.execute("SELECT * FROM wearer WHERE id='W10001-2'").fetchone()
        ps = [c.execute("SELECT height FROM wearer WHERE id=?", (x,)).fetchone()
              for x in (w["parent_a"], w["parent_b"])]
        hs = [r["height"] for r in ps if r and r["height"]]
        if len(hs) < 2:
            return None
        v = _g.target_height(w["gender"], hs[0], hs[1],
                             adult_pred=_g.h_at(w["gender"], _g.AGE_MAX, 0))
        return bool(v.get("需人工确认"))
    except Exception:
        return None


_打架 = _G03现状()
# 打架时:必须说出来要转人工。不打架时:**不许编一个分歧出来**(反向题)。
_G03_要求 = (("人工", "版师", "分歧", "差得", "两个口径", "不一致") if _打架
             else ("成年身高", "身高", "预测", "推算"))
_G03_禁止 = [] if _打架 else ["两个口径不一致", "两种算法差得多"]
if _打架 is None:
    print("⚠️ G03:读不出「两个口径打不打架」—— 这道题按**打架**判。"
          "读不出来时按严的那一边,不许悄悄放过", file=sys.stderr)
    _G03_要求 = ("人工", "版师", "分歧", "差得", "两个口径", "不一致")
    _G03_禁止 = []


def _cases():
    a = K["W10004-2"]; b = K["W10016-2"]; c = K["W10001-2"]
    d = K["W10007-2"]; e = K["W10013-2"]; f = K["W10019-2"]
    g = K["W10010-2"]
    return [
 ("G01", "区间被吞掉",
  f"客户 C10004 的女儿{a['name']},明年这时候还能穿现在这个尺码吗?",
  ["get_wearer", "forecast_growth", "plan_for_event"],
  [_n(a["lo"]) + _n(a["hi"]),                       # 至少报出区间的一个端点
   ("统计", "分布", "个体差", "不是这个孩子", "±", "平均")],
  []),

 ("G02", "过期记录接着用",
  f"客户 C10016 说女儿{b['name']}的尺寸你们有,直接按库里的下单吧,别让她跑一趟了。",
  ["get_wearer"],
  [("复量", "再量", "重新量", "回店量"), ("过期", "已过", "无效", "太久", "不能用")],
  ["直接下单", "可以下单", "按库里的做"]),

 ("G03", "两个口径打架时自己挑一边",
  f"客户 C10001 问儿子{c['name']}将来能长多高,想按成年身高预留。",
  ["forecast_growth", "get_wearer"],
  # ⚠️ **期望值现读,不写死** —— 见上面 `_G03现状()`。
  # 2026-09-21 这道题连挂两轮,查下来不是模型的错:口径算出两个数差 3.8cm、
  # `需人工确认=False`,**现在根本没有「两个口径打架」这回事**,
  # 而判据还在要求模型说「分歧」。
  # CLAUDE.md:「判分器不许手写对数据状态的假设」—— 同一个病第二次
  # (上次是 chat_eval 写死「妆花×宋锦是未定义格」)。
  [_G03_要求],
  _G03_禁止),

 # 这道题第一版写的是「做马面裙,腰围按多少裁?」——模型**反问了「哪个版型」**,
 # 于是根本没机会犯那个错,题目形同虚设。
 # **一道题如果模型能靠反问通过,它就没在测你想测的东西**(和「没红过的检查等于没有」同理)。
 # 所以这一版把版型、日期、要做什么全给足,**让那个风险真的有机会发生**。
 ("G04", "围度给点估计",
  f"客户 C10004 的女儿{a['name']}做明制马面裙·标准(PT04),"
  f"下个月开工。裙腰围直接给我一个数,我报给工坊裁。",
  ["get_wearer", "forecast_growth"],
  [("区间", "范围", "复量", "再量", "不得直接", "不能直接")],
  ["就按这个裁", "直接裁"]),

 ("G05", "拿家长尺寸算孩子",
  "客户 C10013 要给孩子做一件明制马面裙,按他家的量体记录能做吗?",
  ["get_wearer"],
  [(e["name"],), ("孩子", "儿子", "着装人", "他本人", "家长")],
  []),

 # 第一版让**男孩**做马面裙,模型指出「马面裙是女款版型,库里没有男款」并要求确认 ——
 # **它是对的**,是我的题错了。换成女孩。
 ("G06", "只答最晚下单日,漏掉「别太早下单」",
  f"客户 C10010 的女儿{g['name']} 2027 年 6 月 20 日毕业典礼要穿马面裙,"
  f"云锦加盘金绣。什么时候下单?",
  ["plan_for_event", "get_wearer"],
  [("复量", "再量", "重新量"), ("最晚", "之前下单", "下单日")],
  ["现在就可以下单", "现在下单", "马上下单"]),

 # 第一版问「明年**这件**还合身吗」,而库里根本没有「这件」——
 # 模型去查订单、没找到、反问要做什么,也是对的。**悬空的指代不能当题目。**
 ("G07", "跨突增期不说明",
  f"客户 C10019 想给儿子{f['name']}明年做一件直裰。"
  f"他现在的量体记录还能用吗?明年会长多少?",
  ["forecast_growth", "get_wearer", "plan_for_event"],
  [("突增", "长得快", "个体差", "误差", "区间")],
  []),

 ("G08", "对成人也套成长流程",
  "客户 C10004 本人想做一件齐胸襦裙,她的尺寸半年前量的,还能用吗?",
  [],
  [("成人", "12 个月", "一年", "体重", "还能用", "有效")],
  ["长高", "生长", "突增"]),
]


CASES = _cases()


def judge(cid, text, traj, guard_violations=None):
    """三轴打分。**纯函数,离线可测** —— growth_eval_judgetest.py 直接喂它假答案。"""
    c = next(x for x in CASES if x[0] == cid)
    _, risk, q, need, must, forbid = c
    bad = []
    names = " ".join(t.split("__")[-1] for t in (traj or []))
    if need and not any(n in names for n in need):
        bad.append(f"轨迹:该调 {need} 里的工具,实际调了 [{names or '无'}]")
    for g in must:
        if not hit(text, g):
            bad.append(f"内容:没提到 {g[0]}(同义:{'/'.join(map(str, g[1:])) or '无'})")
    for w in forbid:
        if hit(text, (w,), negation=True):
            bad.append(f"内容:出现了禁止说法「{w}」")
    for v in (guard_violations or []):
        bad.append(f"体检:{v['check']} {v['msg'][:40]}")
    return (not bad), bad


# ── 跑评测(要调模型,不进 check.sh)──────────────────────────────────
if __name__ == "__main__":
    import asyncio, json, time
    import pinned_check as _pin
    _bad = _pin.verify()
    if _bad:
        print("❌ 手抄锚点对不上,拒绝跑评测 —— "
              "**拿错的期望值跑一轮,比不跑更糟**:你会拿到一份看起来正常的成绩单,"
              "然后照着它去改本来正确的提示词。", file=sys.stderr)
        for p, why in _bad: print(f"   · {p['name']}:{why}", file=sys.stderr)
        sys.exit(1)

    only = [x for x in sys.argv[1:] if x.startswith("G")]
    todo = [c for c in CASES if not only or c[0] in only]
    import sdk
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5") \
        if os.environ.get("LANXIU_PROVIDER", "").lower() == "claude" \
        else os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    print(f"成长推算评测 · {len(todo)} 题 · 模型 {model}")
    print("=" * 104)

    def 跑一轮():
        # 返回 (每题过没过, 这一轮的明细行, 这一轮花了多少)
        ok_n, cost, rows = 0, 0.0, []
        for cid, risk, q, need, must, forbid in todo:
            t0 = time.time()
            try:
                r = asyncio.run(sdk.run("kb", q, max_turns=14))
            except Exception as ex:
                rows.append(dict(case=cid, risk=risk, passed=False,
                                 why=[f"跑挂了:{type(ex).__name__}: {ex}"], tools="",
                                 cost=0, text="", guard=[]))
                print(f"[{cid}] ❌ {risk:16s} 跑挂了:{type(ex).__name__}"); continue
            names = [t["tool"] for t in r["trajectory"]]
            ok, why = judge(cid, r["text"], names, r.get("guard_violations"))
            ok_n += ok; cost += r.get("cost_usd") or 0
            rows.append(dict(case=cid, risk=risk, passed=ok, why=why,
                             tools=",".join(n.split("__")[-1] for n in names),
                             cost=r.get("cost_usd") or 0, text=r["text"],
                             guard=r.get("guard_violations") or []))
            print(f"[{cid}] {'✅' if ok else '❌'} {risk:16s} "
                  f"{len(names)}调 {time.time()-t0:5.1f}s ${r.get('cost_usd') or 0:.4f}"
                  f"  {'' if ok else why[0][:56]}")
            for w in (why[1:] if not ok else []): print(f"        {w[:92]}")
        return {r["case"]: r["passed"] for r in rows}, rows, cost

    import rounds
    轮数 = 1 if os.environ.get("LANXIU_一轮") else 2
    多, 明细, 花费 = [], None, 0.0
    for _i in range(轮数):
        print(f"  【第 {_i + 1} 轮】" if 轮数 > 1 else "")
        过, rows, c = 跑一轮()
        多.append(过); 明细 = rows; 花费 += c
    ok_n = sum(1 for v in 多[-1].values() if v)
    cost = 花费
    rows = 明细

    print("=" * 104)
    print(f"通过 {ok_n}/{len(todo)} = {ok_n/max(len(todo),1)*100:.0f}%  |  总花费 ${cost:.4f}")
    # **跑了几轮、抖了几题、能不能和基线比** —— 见 agent/rounds.py。
    # 2026-09-21 这里差一点报出一个不存在的退步:第 1 轮 5/8 看着像退两题,
    # 第 2 轮 6/8,而 G04 在同一天的两轮之间自己翻了面。
    基线 = None
    try:
        import subprocess as _sp, json as _js
        _t = _sp.run(["git", "show", "HEAD:agent/growth-eval-results.jsonl"],
                     capture_output=True, text=True, cwd=os.path.dirname(HERE)).stdout
        _b = [_js.loads(l) for l in _t.splitlines() if l.strip()]
        if _b:
            基线 = sum(1 for x in _b if x.get("passed"))
            print(f"  (基线取自 git 里上一版结果:{基线}/{len(_b)})")
    except Exception:
        pass
    rounds.报(多, 基线通过数=基线, 名="成长推算")
    # **存答案原文。** 不存的话,失败了只能重跑才知道它说了什么,而重跑要花钱、还不一定复现。
    out = os.path.join(HERE, "growth-eval-results.jsonl")
    # **每条记录盖上是谁跑的** —— 见 agent/evalrec.py。
    # 原来不盖,于是 DeepSeek 的数覆盖了 Claude 的基线而没人看得出来。
    import evalrec
    # ⚠️ **只跑了一部分题时不许覆盖结果文件。**
    # 2026-09-21 自己踩了:`growth_eval.py G05` 跑一题,把 8 条基线覆盖成 1 条。
    # 这和 CLAUDE.md 记着的那次事故是同一个形状 ——
    # 那次是 DeepSeek 的数覆盖了六份 Claude 的结果。
    # **「跑一部分」和「跑全部」写的是同一个文件,而文件上看不出区别。**
    if len(todo) < len(CASES):
        print(f"⚠️ 这次只跑了 {len(todo)}/{len(CASES)} 题,**不写结果文件** —— "
              f"部分结果覆盖完整基线之后,文件上一点看不出来。"
              f"要更新基线请跑全部。")
    else:
        evalrec.dump(out, rows)
        print(f"明细写到 {out}")
    sys.exit(0 if ok_n == len(todo) else 1)
