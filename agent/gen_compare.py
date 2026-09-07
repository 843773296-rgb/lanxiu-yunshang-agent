#!/usr/bin/env python3
"""三代横向对比 —— 同一批工单,V1 / V2 / V3 各跑一遍。

**这个对比只有手上同时留着三套实现的人做得了。**
大多数项目升代时把旧的删了,从此只能引用别人的数字 ——
而别人的数字是别人的任务、别人的模型、别人的提示词。

控制的变量:同一批工单、同一个模型(DeepSeek v4-pro)、同一套工具、同一份真值。
不控制的:三代各自的提示词和流程(那正是要比的东西)。

⚠️ 要花钱。默认 6 条工单,大约 $0.12。加 -n 改数量。
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "agentsite"))
import api, v1, v2


def pick(n):
    """挑一批工单:两类各一半,保证两条流程都被覆盖。"""
    a = api._rows("SELECT * FROM task WHERE type='财务人工任务' ORDER BY id")[: (n + 1) // 2]
    b = api._rows("SELECT * FROM task WHERE type='客户合并确认' ORDER BY id")[: n // 2]
    return a + b


def case_of(t):
    return t["ref_id"] if t["type"] == "财务人工任务" else t["id"][1:]


def run_v1(t, pv):
    if t["type"] == "财务人工任务":
        p, purpose = v1.BP01.format(ref=t["ref_id"]), "退款定因"
    else:
        a, b = t["ref_id"].split("|")
        p, purpose = v1.BP02.format(a=a, b=b), "客户合并"
    t0 = time.time()
    r = v1.run_case(pv, p, purpose=purpose)
    # **判 V1 要判它的 finding,不是自由文本。**
    # 第一版优先取了 text,结果 6 条只判对 1 条 —— 而 V1 的历史成绩是 18/20。
    # 数字反常得离谱时,先怀疑测量:eval.py 判的一直是 submit_finding 的结构化结果,
    # 自由文本只是模型顺手说的话。**换了读的东西,就不是同一把尺子了。**
    f = r.get("finding")
    return dict(text=json.dumps(f, ensure_ascii=False) if f else (r.get("text") or ""),
                calls=len(r.get("trajectory") or []) + 1, sec=round(time.time() - t0, 1),
                protocol=bool(f))


def run_v2(t):
    t0 = time.time()
    r = v2.run_task(t["id"], use_llm=True)
    return dict(text=r["text"], calls=r["llm_calls"], sec=round(time.time() - t0, 1),
                rule=r["rule_decided"], root=r["root_cause"])


def run_v3(t):
    import asyncio, sdk
    if t["type"] == "财务人工任务":
        p = (f"任务类型:财务人工任务\n押金单号:{t['ref_id']}\n\n"
             "这笔押金退款已连续失败并转入人工处理。请查清失败的根本原因,"
             "给出建议的处理动作,并列出支撑结论的证据。"
             "按「根因 / 建议动作 / 证据 / 置信度」四段输出,每段单独起一行。")
    else:
        a, b = t["ref_id"].split("|")
        # 判定标准写在 SYS_TASK 里(sdk.py),这里不重复 ——
        # **三代必须拿到同一份标准,否则比的是「谁知道规则」不是架构**
        p = (f"任务类型:客户合并确认\n两条疑似重复的客户档案:{a} 和 {b}\n\n"
             "请判断是否为同一客户,给出合并或不合并的建议,并逐项列出比对依据。"
             "按「根因 / 建议动作 / 证据 / 置信度」四段输出,每段单独起一行。")
    t0 = time.time()
    r = asyncio.run(sdk.run("task", p))
    return dict(text=r["text"], calls=len(r["trajectory"]), sec=round(time.time() - t0, 1))


def judge(text, truth):
    """**三代用同一把尺子** —— 直接复用 eval.py 里那个判分器。

    换尺子比就白比了:它对措辞敏感,而三代的措辞本来就不一样。
    这个判分器自己有 18 条对照用例在 check.sh 里守着,可以信。
    """
    import eval as _ev
    return _ev.hit(text, truth["root_cause"], truth["case_id"])[0]


if __name__ == "__main__":
    n = 6
    if "-n" in sys.argv: n = int(sys.argv[sys.argv.index("-n") + 1])
    gens = [g for g in ("V1", "V2", "V3") if f"--only-{g.lower()}" not in sys.argv] \
        if any(a.startswith("--only") for a in sys.argv) else ["V1", "V2", "V3"]
    tasks = pick(n)
    import truthdb
    truths = truthdb.by_case()   # 评测侧自己的只读连接,不借工具层
    pv = v1.provider()
    # **这一轮的成本**要单独算:记录仪里的「累计均价」会被历史稀释,
    # 于是两次对比表之间根本不可比 —— V1 从 $0.021 变成 $0.0065,
    # 可能只是后来跑了很多便宜调用,不是任何东西变好了。
    # 记下开跑前的行数,跑完只统计新增的那几行。
    import trace as _t0
    _base = sum(1 for _ in open(_t0.LOG, encoding="utf-8")) if os.path.exists(_t0.LOG) else 0
    print(f"三代横向对比 · {len(tasks)} 条工单 · 模型 {pv['model']}")
    print("=" * 92)
    res = {g: dict(ok=0, calls=0, sec=0.0, n=0) for g in gens}
    for t in tasks:
        c = case_of(t); tr = truths.get(c)
        line = f"  {t['id']:10s}"
        for g in gens:
            try:
                r = {"V1": lambda: run_v1(t, pv), "V2": lambda: run_v2(t),
                     "V3": lambda: run_v3(t)}[g]()
            except Exception as e:
                line += f"  {g} 挂({type(e).__name__})"; continue
            hit = judge(r["text"], tr) if tr else None
            d = res[g]; d["n"] += 1; d["calls"] += r["calls"]; d["sec"] += r["sec"]
            d["ok"] += bool(hit)
            mark = "" if r.get("protocol", True) else "⚠协议"
            line += f"  {g}{'✅' if hit else '❌'}{r['calls']}调/{r['sec']:.0f}s{mark}"
        print(line)

    print("=" * 92)
    # 成本从记录仪里取 —— 三代都记在同一个文件、同一套字段,这时候就用上了
    import trace as _t, json as _j
    by = _t.summary()["by_gen"]
    # 只读本轮新增的那些记录,按代汇总 —— 这才是可以跨版本比的那个数
    _new = []
    if os.path.exists(_t.LOG):
        with open(_t.LOG, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= _base:
                    try: _new.append(_j.loads(line))
                    except Exception: pass
    run_cost = {}
    for r in _new:
        run_cost[r.get("gen", "V1")] = run_cost.get(r.get("gen", "V1"), 0) + (r.get("cost_est") or 0)
    print(f"  {'代':4s}{'判对':>7s}{'模型调用/条':>13s}{'耗时/条':>10s}"
          f"{'本轮/条':>12s}{'累计均价/次':>13s}")
    for g in gens:
        d = res[g]
        if not d["n"]: continue
        print(f"  {g:4s}{d['ok']}/{d['n']:<5d}{d['calls']/d['n']:>12.1f}"
              f"{d['sec']/d['n']:>9.1f}s  ${run_cost.get(g, 0)/d['n']:>9.5f}"
              f"  ${by.get(g,{}).get('均价',0):>10.5f}")
    print("\n  **「本轮/条」才是跨版本能比的那个数**(这一轮实际花了多少 ÷ 条数)。")
    print("  「累计均价/次」是记录仪里该代**全部历史调用**的单次均价 ——")
    print("  它会被后来的调用稀释,**两次对比表之间不可比**,只能看「一次调用多贵」。")
    print("  另:三代的提示词和流程本来就不同,这不是控制变量实验。")
