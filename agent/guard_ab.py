#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回答体检 A/B:同一份代码、同一批题,只差「工具结果读不读得到」(501c9ed 修的那处)。

旧臂 = 把 guards._unwrap 换回只认 {"content":[…]} 的样子 —— 真服务里工具结果对体检规则是 {}。
新臂 = 现在的样子。两臂按题交替跑,先后顺序每题轮换(免得后跑的那臂白吃热缓存)。
题:growth_eval 8 + tool_eval 24,判分用各自的 judge。要真调模型,不进 check.sh。
结果写 .feynman/guard-ab.json(不碰两套评测自己的结果文件)。
"""
import asyncio, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "agentsite"), os.path.join(HERE, "..", "backend")]
import guards, sdk, evalrec
import growth_eval as G, tool_eval as T

新_unwrap = guards._unwrap
def 旧_unwrap(resp):
    if isinstance(resp, dict):
        cont = resp.get("content")
        if isinstance(cont, list) and cont and isinstance(cont[0], dict):
            t = cont[0].get("text")
            if t:
                try: return json.loads(t)
                except Exception: return t
        return resp
    return resp

角色 = {"T12": "workshop", "T13": "workshop"}
题 = [("growth", c[0], c[2], "kb", G.judge) for c in G.CASES] + \
     [("tool", c[0], c[1], 角色.get(c[0], "kb"), T.judge) for c in T.CASES]
only = [a for a in sys.argv[1:] if a[:1] in "GT"]
if only: 题 = [x for x in 题 if x[1] in only]
OUT = os.path.join(HERE, "..", ".feynman", os.environ.get("AB_OUT", "guard-ab.json"))
rows = []

def 跑(臂, 套, cid, q, kind, judge):
    guards._unwrap = 新_unwrap if 臂 == "新" else 旧_unwrap
    t0 = time.time()
    try:
        r = asyncio.run(sdk.run(kind, q, max_turns=14))
    except Exception as e:
        return dict(臂=臂, 套=套, case=cid, 崩=f"{type(e).__name__}: {e}")
    names = [t["tool"] for t in r["trajectory"]]
    ok, why = judge(cid, r["text"], names, r.get("guard_violations"))
    return dict(臂=臂, 套=套, case=cid, passed=ok, why=why, tools=[n.split("__")[-1] for n in names],
                打回=len(r.get("guard_violations") or []),
                违规=[v.get("check") for v in r.get("guard_violations") or []],
                违规原话=[v.get("msg") for v in r.get("guard_violations") or []],
                草稿=r.get("未通过草稿"), 检查记录=r.get("交付检查"),
                交付=(r.get("交付检查") or {}).get("状态") if isinstance(r.get("交付检查"), dict) else r.get("交付检查"),
                cost=r.get("cost_usd") or 0, 秒=round(time.time() - t0, 1), text=r["text"])

print(f"体检 A/B · {len(题)} 题 × 2 臂 · 模型 {evalrec.模型()}")
for i, (套, cid, q, kind, judge) in enumerate(题):
    for 臂 in (("新", "旧") if i % 2 == 0 else ("旧", "新")):
        x = 跑(臂, 套, cid, q, kind, judge); rows.append(x)
        print(f"[{cid}] {臂} " + (f"崩 {x['崩'][:60]}" if "崩" in x else
              f"{'✅' if x['passed'] else '❌'} 打回{x['打回']} {x['违规']} 交付={x['交付']} {x['秒']}s"), flush=True)
        json.dump(dict(章=evalrec.盖章(), rows=rows), open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def 汇(臂):
    xs = [r for r in rows if r["臂"] == 臂 and "崩" not in r]
    return len(xs), sum(r["passed"] for r in xs), sum(1 for r in xs if r["打回"]), sum(r["cost"] for r in xs)
print("=" * 80)
for 臂 in ("旧", "新"):
    n, p, b, c = 汇(臂)
    print(f"{臂}臂:判对 {p}/{n} · 被打回过的题 {b}/{n} · ${c:.3f}")
