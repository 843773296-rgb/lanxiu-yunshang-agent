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
    ok_n, cost, rows = 0, 0.0, []
    for c in todo:
        t0 = time.time()
        r = asyncio.run(sdk.run("task", PROMPT.format(mid=c["case_id"]), max_turns=14))
        names = [x["tool"] for x in r["trajectory"]]
        ok, why = judge(c, r["text"], names, r.get("guard_violations"))
        ok_n += ok; cost += r.get("cost_usd") or 0
        rows.append(dict(case=c["case_id"], truth=c["root_cause"], passed=ok, why=why,
                         tools=",".join(n.split("__")[-1] for n in names),
                         cost=r.get("cost_usd") or 0, text=r["text"],
                         guard=r.get("guard_violations") or []))
        print(f"  {'✅' if ok else '❌'} {c['case_id']} {c['root_cause']:30s} "
              f"{len(names)}调 {time.time()-t0:5.1f}s ${r.get('cost_usd') or 0:.4f}"
              f"  {'' if ok else why[0][:44]}")
        for w in (why[1:] if not ok else []): print(f"        {w[:92]}")
    print("=" * 104)
    print(f"通过 {ok_n}/{len(todo)}  |  总花费 ${cost:.4f}")
    out = os.path.join(HERE, "liability-eval-results.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"明细写到 {out}")
    sys.exit(0 if ok_n == len(todo) else 1)
