#!/usr/bin/env python3
"""模型判定的稳定性 —— 同一份输入跑几遍,哪些结论是稳的,哪些每次都变。

**不进 check.sh**:它要真调模型、要花几分钟。人手动跑那一类。

## 为什么必须量这个

overlay(模型层的判定)会被**盖到事实层**,影响整批数据:
否决一条关系,拓扑顺序、环的位置、断言的组成全跟着变。
而这个工具的核心说法是「**做一次,跑一万次**」—— 它成立的前提是那"一次"是个**结论**。

如果同一份输入跑两遍给出相反的判定,那你复用的就不是结论,是**一次抽样**。
差别在于:结论可以复用,抽样不能。

我在做模型层时**看见过**这件事(`customer.phone → account.phone` 有时否决有时确认),
也在报告里写过 —— 但**从没量过**。没量过的东西不算知道。

## 判据只能是「跑多遍看一致率」

这类问题读代码看不出来,提示词写得再清楚也保证不了。
唯一的办法是把同一份输入送 N 次,逐条比对。

## ⚠️ 这个测量自己的样本量也不够 —— 实测两轮给了两个数

  第一轮:每次都一样 **46%**,关系判定 **0 条**翻转
  第二轮:每次都一样 **73%**,关系判定 **1 条**翻转(`customer.phone`)

同一件事,两次量出两个数。而我在第一轮据此下过结论「关系判定全部稳定」——
第二轮它就翻了。**用一个 N=3 的测量去判断别人稳不稳定,而这个测量自己不稳定。**

所以:**N=3 只能算粗筛,不是定论**。要更可信就加 N(代价是线性的模型调用)。
报告里必须带上 N,别只报百分比 —— 一个不带样本量的一致率,和「0 条违规」是同一类东西。

## 量完之后要做什么

不是去追求 100% 稳定(做不到),而是**把不稳定的标出来**:
「这条判定 3 次里变了 2 次 —— 别信它,人来定」。
和覆盖率是同一个动作:**把一个看不见的不确定,变成一件写在纸面上的事。**
"""
import collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def _fingerprint(ov):
    """把一次判定拍平成「条目 → 结论」,好逐条比对。"""
    fp = {}
    for r in ov.get("relations", []):
        fp[("关系", r["table"], r["column"])] = r["verdict"]
    for c in ov.get("columns", []):
        fp[("列语义", c["table"], c["column"])] = c["semantic"]
    for m in ov.get("state_machines", []):
        # 状态机比的是「转移集合」,不是逐字比理由
        fp[("状态机", m["table"], m["column"])] = tuple(sorted(map(tuple, m["transitions"])))
    for f in ov.get("forbidden", []):
        fp[("禁配", f["table"], f"{f['a_column']}={f['a_value']}×"
                                f"{f['b_column']}={f['b_value']}")] = f["verdict"]
    return fp


def run(n=3, scale=0.2, model=None, log=print):
    import schema as S, discover as D, plan as P, infer_llm as I
    conn = S.connect(os.path.join(ROOT, "backend", "lanxiu.db"))
    facts = D.discover(conn, conn.reflect())
    pl = P.build(facts, scale=scale)
    fps, metas, overlays = [], [], []
    for i in range(n):
        log(f"  第 {i + 1}/{n} 次…")
        good, dropped, meta = I.infer(facts, pl, model=model, log=lambda *a: None)
        fps.append(_fingerprint(good)); metas.append(meta); overlays.append(good)

    keys = set().union(*[set(f) for f in fps])
    stable, flip, sometimes = [], [], []
    for k in sorted(keys, key=str):
        vals = [f.get(k) for f in fps]
        seen = set(vals)
        if len(seen) == 1 and None not in seen: stable.append((k, vals[0]))
        elif None in seen and len(seen) == 2: sometimes.append((k, vals))   # 有时候压根不提
        else: flip.append((k, vals))
    return {"次数": n, "条目": len(keys), "稳定": stable, "翻转": flip,
            "时有时无": sometimes, "元信息": metas, "各次判定": overlays,
            "指纹": fps}


def consensus(res):   # 保留给老调用;真正的实现已收进 infer_llm.infer_n

    """把 N 次判定合成一份**共识 overlay**:只留每次都一样的,其余进「待人确认」。

    **不是追求稳定,是把不稳定标出来。** 做法分两档,依据是「这条判定错了会怎样」:

      · **禁配** —— 判成 real 会变成一条**永久的检查**。
        错一条,以后每一批数据都误报。所以**要求全票**,差一票就不采信。
      · **列语义 / 状态机** —— 错了只是数据不像,不会污染检查。
        同样只留全票的,但落选的进「待确认」清单,而不是当作不存在 ——
        **它们是真的判不准,不是没判过**,这两件事得分开。

    关系判定实测 3 次全稳,不做特殊处理。
    """
    n, fps = res["次数"], res["指纹"]
    unanimous = {k for k, _v in res["稳定"]}
    base = res["各次判定"][0]
    out = {"relations": base.get("relations", []), "columns": [], "state_machines": [],
           "forbidden": []}
    unstable = []
    for c in base.get("columns", []):
        (out["columns"] if ("列语义", c["table"], c["column"]) in unanimous
         else unstable).append(c if ("列语义", c["table"], c["column"]) in unanimous
                               else {"类": "列语义", "在": f'{c["table"]}.{c["column"]}',
                                     "各次": [f.get(("列语义", c["table"], c["column"]))
                                              for f in fps]})
    for m in base.get("state_machines", []):
        k = ("状态机", m["table"], m["column"])
        if k in unanimous: out["state_machines"].append(m)
        else: unstable.append({"类": "状态机", "在": f'{m["table"]}.{m["column"]}',
                               "各次": [("%d 条转移" % len(f[k])) if f.get(k) else "(没提)"
                                        for f in fps]})
    for f_ in base.get("forbidden", []):
        k = ("禁配", f_["table"],
             f'{f_["a_column"]}={f_["a_value"]}×{f_["b_column"]}={f_["b_value"]}')
        if k in unanimous: out["forbidden"].append(f_)
        elif f_["verdict"] == "real":
            unstable.append({"类": "禁配(要变成永久检查,所以要求全票)", "在": k[2],
                             "各次": [f.get(k) for f in fps]})
    return out, unstable


def report(res, log=print):
    n, tot = res["次数"], res["条目"]
    st, fl, so = len(res["稳定"]), len(res["翻转"]), len(res["时有时无"])
    log(f"\n同一份输入跑 {n} 遍 · 一共出现过 {tot} 条判定")
    log(f"  每次都一样      {st:>3} 条  ({st * 100 // max(tot, 1)}%)")
    log(f"  **结论翻转**    {fl:>3} 条  ← 这些不能当结论用")
    log(f"  **时有时无**    {so:>3} 条  ← 有几次压根没提,漏判不报错")
    by = collections.Counter(k[0] for k, _v in res["翻转"] + res["时有时无"])
    if by: log(f"  不稳定的分布:{dict(by)}")
    for title, items in (("结论翻转", res["翻转"]), ("时有时无", res["时有时无"])):
        if not items: continue
        log(f"\n=== {title} ===")
        for k, vals in items[:12]:
            log(f"  {k[0]} {k[1]}.{k[2]}")
            log(f"     {n} 次:{[str(v)[:26] if v is not None else '(没提)' for v in vals]}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    res = run(n=n)
    report(res)
    ov, unstable = consensus(res)
    print(f"\n=== 共识 overlay(只留 {res['次数']}/{res['次数']} 全票的)===")
    print(f"  关系 {len(ov['relations'])} · 列语义 {len(ov['columns'])} · "
          f"状态机 {len(ov['state_machines'])} · 禁配 {len(ov['forbidden'])}")
    print(f"  **待人确认 {len(unstable)} 条**(模型每次答得不一样 —— 是判不准,不是没判过)")
    for u in unstable[:6]:
        print(f"    {u['类']} {u['在']}:{u['各次']}")

    out = os.path.join(ROOT, ".fakedata", "stability.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"次数": res["次数"],
                   "翻转": [[list(map(str, k)), v] for k, v in res["翻转"]],
                   "时有时无": [[list(map(str, k)), v] for k, v in res["时有时无"]],
                   "稳定条数": len(res["稳定"]),
                   "共识overlay": ov, "待人确认": unstable}, f, ensure_ascii=False, indent=1)
    print(f"\n明细 → {out}")
