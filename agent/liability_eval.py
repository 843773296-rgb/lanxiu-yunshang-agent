#!/usr/bin/env python3
"""售后判责评测 —— 补上那笔明知故犯的债。

## 为什么这套非做不可

第 7 版报告刚写完一句话:「**为一个风险装了六道锁,不等于量过那个风险有多大。**」
然后这一轮做售后判责,加了第 17 条体检 —— **又没建模型评测**。
同一笔账,一轮之后自己又欠了一次。所以这套是还债。

## 判责比别的场景更该测,理由有三条

1. **每一条结论都对着钱。** 「我方,免费返修」被顾问原样念给客户,
   等于商家已经认了责,而**认责没有回退键**。
2. **判据藏在现场里,不在问题描述里。** 同样是「面料起球」,
   交付时**有没有书面告知签收**,结论一个是「无责」一个是「我方让步」——
   模型要是不去看那个字段,两边都能编得很像样。
3. **规则只有 7 行,所以答错不能赖「太难」。** 表就在知识库里,
   查一下就有 —— 答错只可能是没查,或者查了不用。

## 三个轴

    轨迹  有没有去看现场(get_maintain)、有没有查判定表(kb_tables)
    内容  责任归谁说对没有 · 有没有给依据 · **有没有编赔付金额**
    体检  guards 有没有打回(g17 管的就是「判责结论当承诺发出去」)

## 用例怎么来的

从 `truth` 表里 BP-03 的**人工标注**取,每种判责结论各取一条,六种全覆盖。
标注和 `knowledge/liability.py` 的推导是两条独立实现,
`backend/liability_check.py` 每次对账 —— 所以这份答案不是被测系统自己算出来的。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "backend"),
                os.path.join(HERE, "..", "agentsite")]
import api, truthdb
import textmatch as tm

# 责任方 → 答案里必须出现的说法 / 必须给出的处理
WHO = {
    "我方": ("我方", "我们的责任", "本店责任", "商家责任", "由我方", "我方承担"),
    "客方": ("客方", "客户责任", "客户承担", "使用不当", "由客户"),
    "无责": ("无责", "不属于质量问题", "属正常特性", "不构成质量问题", "非质量问题"),
    "分担": ("分担", "按合同", "双方"),
}
VERDICT = {
    "工艺瑕疵 · 我方免费返修":         ("我方", ("免费返修", "免费修", "无偿返修", "无偿"), ("工艺瑕疵", "脱线", "开线", "拉链")),
    "尺寸偏差 · 记录完整 · 客方收费改": ("客方", ("收费改", "收费"), ("量体记录", "记录完整", "到店")),
    "尺寸偏差 · 记录不全 · 我方免费改": ("我方", ("免费改", "免费", "无偿改", "无偿"), ("量体记录", "记录不全", "缺失", "没有量体")),
    "远程量体偏差 · 按合同分担":        ("分担", ("分担", "合同"), ("远程", "视频")),
    # ── 2026-09-15 新加的两行(白坯试衣)────────────────────────────
    # ⚠️ **这两条现在出不了题**,因为这套题的对象是从 truth 表现挑的,
    # 而这两行**还没有任何真值标注**。写在这儿是为了:
    # 业务一旦补上用例和真值,题目**自动就有了**,不用有人记得回来改这里。
    #
    # 不自己补真值的理由:真值是**故意的第二套实现**,
    # 自己写等于和自己对账 —— 那样的 100% 什么也证明不了。
    # 在那之前,模型对「该试没试 vs 已试未签」的区分由
    # `ops_eval` 的 M1–M3 盯着(那三道不依赖 truth)。
    "尺寸偏差 · 试衣已签字 · 客方收费改":
        ("客方", ("收费", "付费", "客户承担"), ("试衣", "白坯", "签字")),
    "尺寸偏差 · 该试没试 · 我方免费改":
        ("我方", ("免费改", "免费", "无偿改", "无偿"), ("试衣", "白坯", "没做", "没试")),
    "特性类已告知 · 无责解释":          ("无责", ("解释", "保养", "不返修"), ("告知", "签收")),
    "特性类未告知 · 我方让步":          ("我方", ("让步", "补偿", "协商"), ("告知", "签收", "没有")),
}
# 判责草稿里**不该出现**的:**自己编的赔付金额**。赔多少是人定的,不是模型定的。
#
# ⚠️ 第一版写成「出现任何金额就算编」,结果 4/6 全是误报 ——
# 模型引用的是**订单金额**(「原订单价格 4956 元」「单笔 13723.4 元需财务复核」),
# 那是**证据**,不是承诺。**第四次栽在「提到没提到 vs 做了没做」上。**
#
# 改成:金额**不等于订单金额**、且落在赔付语境里,才算编。
MONEY = re.compile(r"(?:¥|￥)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:元|块钱)")
PAYOUT = ("赔", "补偿", "退款", "代金", "优惠券", "折扣")


def _made_up_money(text, order_amount):
    """找「自己编的赔付金额」。引用订单金额不算。"""
    for m in MONEY.finditer(text or ""):
        raw = (m.group(1) or m.group(2) or "").replace(",", "")
        try: v = float(raw)
        except ValueError: continue
        if order_amount is not None and abs(v - order_amount) < 0.5:
            continue                      # 就是订单金额,属于引用证据
        seg = tm.in_sentence(text, m.group(0), PAYOUT)
        if seg: return m.group(0)
    return None



# ── 夹具的前提 ────────────────────────────────────────────────────────
# 这套题的对象**全部从 truth 表现挑**(六种判责结论各取一条),不写死单号。
# 真值和数据对不上的时候,`judgetest` 那条「两条实现来自同一份文档」会红。
前提 = []          # **明说不依赖任何对象的状态** —— 不是忘了写

def cases():
    """每种判责结论取一条,六种全覆盖。答案取自人工标注,不是被测系统算的。"""
    rows = truthdb.rows("""SELECT case_id, root_cause, note FROM truth
                           WHERE breakpoint='BP-03' ORDER BY case_id""")
    seen, out = set(), []
    for r in rows:
        if r["root_cause"] in seen or r["root_cause"] not in VERDICT: continue
        seen.add(r["root_cause"]); out.append(r)
    return out


CASES = cases()

PROMPT = ("任务类型:售后判责\n维修工单号:{mid}\n\n"
          "客户报修,需要判定责任归属并给出处理方式。"
          "先用 get_maintain 查现场,再用 kb_tables 取「售后争议判定」,"
          "对照 09-养护与售后.md 第五节的返修判定表给结论。\n"
          "按「根因 / 建议动作 / 证据 / 置信度」四段输出,每段单独起一行。")


def judge(case, text, traj, guard_violations=None):
    """三轴打分。**纯函数,离线可测。**"""
    who, acts, evid = VERDICT[case["root_cause"]]
    t, bad = text or "", []
    names = " ".join(x.split("__")[-1] for x in (traj or []))

    if "get_maintain" not in names:
        bad.append("轨迹:没查现场(get_maintain)—— 判据藏在现场里,不在问题描述里")
    # **判据来源**这一轴是补票买的:原来只查了现场、没查判定表,于是 18/18 全过,
    # 而那个角色根本没有 kb_tables —— 每条结论都是模型凭自己对「什么算公平」的
    # 理解得出的。判分器太松,满分成绩单就是假的。
    if "kb_tables" not in names:
        bad.append("轨迹:没取判定表(kb_tables)—— 凭理解判责,公司改了标准它不会跟着变")
    if not tm.mentions(t, WHO[who]):
        bad.append(f"内容:没说清责任归谁(应为「{who}」)")
    if not tm.mentions(t, acts):
        bad.append(f"内容:没给出处理方式(应含 {acts[0]})")
    if not tm.mentions(t, evid):
        bad.append(f"内容:没给判据(该提到 {evid[0]} 这类现场事实,不能只给结论)")
    amt = None
    w = api.get_maintain(maintain_id=case["case_id"]).get("工单") or []
    if w: amt = (w[0].get("订单") or {}).get("amount")
    got = _made_up_money(t, amt)
    if got:
        bad.append(f"内容:**编了赔付金额「{got}」** —— 赔多少是人定的,不是模型定的"
                   f"(订单金额 {amt} 属于引用证据,不算)")
    for v in (guard_violations or []):
        bad.append(f"体检:{v['check']} {v['msg'][:40]}")
    return (not bad), bad


if __name__ == "__main__":
    import asyncio, json, time
    import sdk
    only = [a for a in sys.argv[1:] if a.startswith("MW")]
    todo = [c for c in CASES if not only or c["case_id"] in only]
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5") \
        if os.environ.get("LANXIU_PROVIDER", "").lower() == "claude" \
        else os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    print(f"售后判责评测 · {len(todo)} 题(六种判责结论全覆盖)· 模型 {model}")
    print("=" * 104)

    def 跑一轮():
        """返回 (每题过没过, 每题的失败理由, 这一轮的明细, 这一轮花了多少)。"""
        cost, rows = 0.0, []
        for c in todo:
            t0 = time.time()
            try:
                r = asyncio.run(sdk.run("task", PROMPT.format(mid=c["case_id"]),
                                        max_turns=14))
            except Exception as ex:
                # **跑挂了不算答错了** —— rounds.py 有专门的「跑挂」一类,
                # 先看是不是环境问题,别当能力波动。
                rows.append(dict(case=c["case_id"], truth=c["root_cause"], passed=False,
                                 why=[f"跑挂了:{type(ex).__name__}: {ex}"], tools="",
                                 cost=0, text="", guard=[]))
                print(f"  ❌ {c['case_id']} {c['root_cause']:30s} "
                      f"跑挂了:{type(ex).__name__}")
                continue
            names = [x["tool"] for x in r["trajectory"]]
            ok, why = judge(c, r["text"], names, r.get("guard_violations"))
            cost += r.get("cost_usd") or 0
            rows.append(dict(case=c["case_id"], truth=c["root_cause"], passed=ok, why=why,
                             tools=",".join(n.split("__")[-1] for n in names),
                             cost=r.get("cost_usd") or 0, text=r["text"],
                             guard=r.get("guard_violations") or []))
            print(f"  {'✅' if ok else '❌'} {c['case_id']} {c['root_cause']:30s} "
                  f"{len(names)}调 {time.time()-t0:5.1f}s ${r.get('cost_usd') or 0:.4f}"
                  f"  {'' if ok else why[0][:44]}")
            for w in (why[1:] if not ok else []): print(f"        {w[:92]}")
        return ({r["case"]: r["passed"] for r in rows},
                {r["case"]: r.get("why") or [] for r in rows},
                rows, cost)

    # **跑两轮,报轮间抖动** —— 见 agent/rounds.py。
    # 这一套的翻面尤其要分清两类:「没调 kb_tables」是**轨迹类**(模型这次没去查判定表,
    # 该改提示词),「没说清责任归谁」多半是**内容类**(判据吃措辞)——
    # 而合成一个「抖动 N 题」看不出区别,两边该改的地方相反。
    import rounds
    轮数 = 1 if os.environ.get("LANXIU_一轮") else 2
    多, 因, 明细, 花费 = [], [], None, 0.0
    for _i in range(轮数):
        if 轮数 > 1: print(f"  【第 {_i + 1} 轮】")
        过, why, rows, c = 跑一轮()
        多.append(过); 因.append(why); 明细 = rows; 花费 += c
    ok_n = sum(1 for v in 多[-1].values() if v)
    cost, rows = 花费, 明细

    print("=" * 104)
    print(f"通过 {ok_n}/{len(todo)}  |  总花费 ${cost:.4f}")

    # 基线取 git 里上一版结果。**不可比的基线不许交给判官** ——
    # 交出去的话它会算出一个「版本差」,而那个差可能是换题/换模型换出来的。
    基线, 基线来路 = None, None
    try:
        import subprocess as _sp
        _t = _sp.run(["git", "show", "HEAD:agent/liability-eval-results.jsonl"],
                     capture_output=True, text=True, cwd=os.path.dirname(HERE)).stdout
        _b = [json.loads(l) for l in _t.splitlines() if l.strip()]
        _量过 = {x.get("case") for x in _b}
        _现 = {c["case_id"] for c in todo}
        if not _b:
            pass
        elif len(todo) < len(CASES):
            print(f"  ℹ️ 这次只跑了 {len(todo)}/{len(CASES)} 题 —— "
                  f"**不拿基线比**(分母都不一样)")
        elif _量过 != _现:
            # ⚠️ 这一套的题**是从 truth 表现挑的**(六种判责结论各取一条),
            # 业务补一条标注就会多一道题、换一个单号。
            # 比的是**哪几道**不是**几道**:换掉一道又补一道会正好对上。
            print(f"  ℹ️ 基线和现在的题对不上,**不拿它比** —— "
                  f"没量过 {sorted(_现 - _量过) or '(无)'}；"
                  f"量过但现在没有的 {sorted(_量过 - _现) or '(无)'}")
        else:
            基线 = sum(1 for x in _b if x.get("passed"))
            基线来路 = {k: _b[0].get(k) for k in ("供应商", "模型", "代码")}
            print(f"  (基线取自 git 里上一版结果:{基线}/{len(_b)})")
    except Exception:
        pass
    rounds.报(多, 基线通过数=基线, 名="售后判责", 原因=因, 基线来路=基线来路)

    out = os.path.join(HERE, "liability-eval-results.jsonl")
    # **每条记录盖上是谁跑的** —— 见 agent/evalrec.py。
    # 原来不盖,于是 DeepSeek 的数覆盖了 Claude 的基线而没人看得出来。
    import evalrec
    # ⚠️ **只跑了一部分题时不许覆盖结果文件。**(同一个形状的第三处。)
    # 「跑一部分」和「跑全部」写的是同一个文件,而文件上一点看不出区别。
    if len(todo) < len(CASES):
        print(f"⚠️ 这次只跑了 {len(todo)}/{len(CASES)} 题,**不写结果文件** —— "
              f"部分结果覆盖完整基线之后,文件上看不出来。要更新基线请跑全部。")
    else:
        evalrec.dump(out, rows)
        print(f"明细写到 {out}")
    sys.exit(0 if ok_n == len(todo) else 1)
