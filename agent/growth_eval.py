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


def _n(x):
    """142.3 → ('142.3','142')  —— 模型可能只写整数"""
    return (f"{x:g}", f"{int(round(x))}")


# (编号, 盯的风险, 问题, need 轨迹, must 内容组, forbid 内容)
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
  [("人工", "版师", "分歧", "差得", "两个口径", "不一致")],
  []),

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
    print("=" * 104)
    print(f"通过 {ok_n}/{len(todo)} = {ok_n/max(len(todo),1)*100:.0f}%  |  总花费 ${cost:.4f}")
    # **存答案原文。** 不存的话,失败了只能重跑才知道它说了什么,而重跑要花钱、还不一定复现。
    out = os.path.join(HERE, "growth-eval-results.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"明细写到 {out}")
    sys.exit(0 if ok_n == len(todo) else 1)
