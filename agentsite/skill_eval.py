# -*- coding: utf-8 -*-
"""技能触发的评测台架 —— **技能描述是可测量的,不是随手写的说明文字。**

抄自 Accio 的 skill-creator(它有 9 个脚本 + 3 个打分子代理干这件事),
拿的是**做法**,不是代码。核心只有一句:

    描述写完不算完,要用一组真实问法测它触发得准不准,
    改完再测一遍,**看得见改进**。

## 触发错有两个方向,后果完全不同

    漏触发  该走流程的没走 —— 用户拿到一个随口答的报价,
            而报价单是会被转发给客户、脱离上下文独自存在的东西。
    误触发  不该走的走了 —— 用户随口问一句,拿回来一份三段式报价单。

Accio 的实测结论是**漏触发是主要失败模式**,所以他们要求技能描述写得
「推销」一点。这份评测就是用来验证那个判断在我们这儿成不成立的 ——
**别人的经验也要在自己的数据上验一遍**,不然就是换了个来源的想当然。

## 用法

    ./agentsite/.venv/bin/python agentsite/skill_eval.py            # 全跑
    ./agentsite/.venv/bin/python agentsite/skill_eval.py --only 8   # 只跑一条
    ./agentsite/.venv/bin/python agentsite/skill_eval.py --save v1  # 存一版基线
    ./agentsite/.venv/bin/python agentsite/skill_eval.py --diff v1  # 和基线比

跑一次约 15 条 × 30 秒。用 Claude(订阅内,边际成本为零)。
"""
import argparse, asyncio, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)

CASES = os.path.join(HERE, "evals", "skill_trigger.json")
RUNS = os.path.join(HERE, "evals", "runs")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def _hashes():
    """当前每份技能的哈希 —— 存进结果文件,对比时才分得清哪些改过。"""
    import hashlib
    d = os.path.join(HERE, ".claude", "skills")
    out = {}
    for n in sorted(os.listdir(d)):
        f = os.path.join(d, n, "SKILL.md")
        if os.path.exists(f):
            out[n] = hashlib.sha256(open(f, "rb").read()).hexdigest()[:12]
    return out


def _skill_of(traj):
    """从轨迹里读出**触发了哪个技能**。没触发返回 None。

    读的是工具调用的入参,不是模型说的话 —— 模型可能说「我用排班流程」
    而实际没调 Skill,那种情况下**它只是在描述,没有真的走流程**。
    """
    for t in traj or []:
        if (t.get("tool") or "") == "Skill":
            return ((t.get("args") or {}).get("skill") or "?")
    return None


async def _one(sdk, prompt, me):
    # **身份要真传进去。** 排班/团队类问法要店长才答得了,
    # 匿名跑的话它会因为「你没这个权限」而不触发 ——
    # 那种不触发是权限挡的,不是描述不好,混在一起测就分不清是谁的责任。
    # **必须和产品跑同一个配置。** 上一版为了快,设了 max_turns=6、guard=False,
    # 而且没指定模型 —— sdk._env 在不给模型时回落到 **Haiku**,
    # 而网站默认是 **Sonnet 5**。于是评测测的是一个用户根本不会碰到的东西:
    # 同一句「给张女士出个报价单」,评测里 0/3 不触发,真实路径上一次就触发了。
    # **评测不跑产品的配置,量出来的数字和产品没关系** ——
    # 而它看起来和真数字一模一样。
    import importlib
    _sdk = importlib.import_module("sdk")
    prov, mdl = _sdk.default_model_id().split(":", 1)
    r = await sdk.run("all", prompt, provider=prov, model_name=mdl, me=me)
    return _skill_of(r.get("trajectory")), r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="只跑某一条")
    ap.add_argument("--save", help="把结果存成一版基线")
    ap.add_argument("--diff", help="和某版基线对比")
    ap.add_argument("--repeat", type=int, default=1,
                    help="每条跑几遍。**单跑一次是有噪声的** —— "
                         "同一个问法两次结果可能不一样,分不清「改坏了」和「抖了一下」")
    a = ap.parse_args()

    spec = json.load(open(CASES, encoding="utf-8"))
    cases = [c for c in spec["cases"] if not a.only or c["id"] == a.only]

    import sdk
    # 身份:排班/团队类问法要店长才答得了,否则会因为「你没这个权限」而不触发 ——
    # **那种不触发是权限挡的,不是描述不好**,混在一起测就分不清谁的责任。
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    me = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}

    import importlib as _il; _mid = _il.import_module("sdk").default_model_id()
    print(f"\n\033[1m技能触发评测 · {len(cases)} 条 · 模型 {_mid}(和网站默认同一个)\033[0m")
    print("=" * 88)
    rows, t0 = [], time.time()
    for c in cases:
        want = c.get("expect")
        # 跑 N 遍,**记下每一遍的结果** —— 稳定性本身是个要看的东西:
        # 一个「有时触发有时不触发」的技能,比稳定不触发更难查,
        # 因为它偶尔会给你一个「已经好了」的假象。
        got_all = []
        for _ in range(max(1, a.repeat)):
            try:
                g1, _r = asyncio.run(_run_with_identity(sdk, c["prompt"], me))
            except Exception as e:
                g1 = f"ERR:{type(e).__name__}"
            got_all.append(g1)
        hits = sum(1 for x in got_all if x == want)
        got = got_all[0] if len(set(got_all)) == 1 else f"{got_all[0]}?{len(set(got_all))}种"
        ok = (hits == len(got_all))
        wobbly = 0 < hits < len(got_all)
        # 两种错分开记 —— 后果不一样,不能揉成一个准确率
        g0 = got_all[0]
        kind = "对" if ok else ("不稳定" if wobbly else
                                ("漏触发" if want and not g0 else
                                 ("误触发" if g0 and not want else "触发错了技能")))
        mark = f"{G}✅{D}" if ok else (f"{Y}〜{D}" if wobbly else f"{R}❌{D}")
        tail = f"{hits}/{len(got_all)} 次对" if a.repeat > 1 else (kind if not ok else "")
        print(f"  {mark} #{c['id']:<3} {c['prompt'][:30]:<32} 触发={str(got or '(无)'):<12} "
              f"应为={str(want or '(无)'):<12} {tail}")
        if wobbly:
            print(f"       {Y}不稳定{D}:{got_all} —— **偶尔触发比从不触发更难查**,"
                  f"它会给你「已经好了」的假象")
        elif not ok:
            print(f"       {c['why']}")
        rows.append(dict(id=c["id"], prompt=c["prompt"], want=want, got=got, ok=ok,
                         kind=kind, hits=hits, runs=len(got_all), wobbly=wobbly))

    ok_n = sum(1 for x in rows if x["ok"])
    miss = [x for x in rows if x["kind"] == "漏触发"]
    over = [x for x in rows if x["kind"] == "误触发"]
    wrong = [x for x in rows if x["kind"] == "触发错了技能"]
    print("=" * 88)
    print(f"  准确率 {ok_n}/{len(rows)}  ·  漏触发 {len(miss)}  ·  误触发 {len(over)}  ·  触发错技能 {len(wrong)}")
    print(f"  用时 {time.time()-t0:.0f} 秒")
    if miss:
        print(f"\n  {Y}漏触发的{D}(该走流程没走 —— 用户拿到的是随口答的东西):")
        for x in miss: print(f"    #{x['id']} 「{x['prompt'][:34]}」应触发 {x['want']}")
    if over:
        print(f"\n  {Y}误触发的{D}(随口一问,拿回来一份三段式文档):")
        for x in over: print(f"    #{x['id']} 「{x['prompt'][:34]}」不该触发,却触发了 {x['got']}")

    os.makedirs(RUNS, exist_ok=True)
    if a.save:
        p = os.path.join(RUNS, f"{a.save}.json")
        json.dump(dict(准确率=f"{ok_n}/{len(rows)}", 明细=rows, 技能哈希=_hashes()),
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n  已存基线:{p}")
    if a.diff:
        p = os.path.join(RUNS, f"{a.diff}.json")
        if not os.path.exists(p):
            print(f"\n  {R}没有基线 {a.diff}{D}"); return
        base = json.load(open(p, encoding="utf-8"))
        old = {x["id"]: x for x in base["明细"]}
        oldh, newh = base.get("技能哈希") or {}, _hashes()
        改了的技能 = {k for k, v in newh.items() if oldh.get(k) != v}
        print(f"\n  \033[1m和基线 {a.diff} 对比\033[0m")
        print(f"    这期间改过的技能:{sorted(改了的技能) or '(一个都没改)'}")

        # **按「这条用例的技能改没改」分两组。**
        # 没改的那组是**对照组** —— 它的变化量就是噪声。
        # 没有对照组的话,任何一条变化都会被读成「我这次改动的效果」,
        # 而实测:文件一个字没动的技能,用例照样 ±1/3 地抖。
        def _grp(x):
            want = next((c.get("expect") for c in spec["cases"] if c["id"] == x["id"]), None)
            return "改动组" if want in 改了的技能 else "对照组"

        for grp in ("改动组", "对照组"):
            好 = [x for x in rows if _grp(x) == grp and x["ok"] and not old.get(x["id"], {}).get("ok")]
            坏 = [x for x in rows if _grp(x) == grp and not x["ok"] and old.get(x["id"], {}).get("ok")]
            n = len([x for x in rows if _grp(x) == grp])
            tag = "" if grp == "改动组" else "  ← **这组是噪声,不是效果**"
            print(f"\n    \033[1m{grp}\033[0m({n} 条){tag}")
            print(f"      修好 {len(好)} · 变坏 {len(坏)}")
            for x in 坏: print(f"      {R}↓{D} #{x['id']} 「{x['prompt'][:28]}」原来对,现在 {x['kind']}")
            for x in 好: print(f"      {G}↑{D} #{x['id']} 「{x['prompt'][:28]}」原来错,现在对了")
            if grp == "对照组" and (好 or 坏):
                print(f"      {Y}对照组动了 {len(好)+len(坏)} 条 —— 这就是噪声底噪。"
                      f"改动组里小于这个量的变化都读不出效果。{D}")


async def _run_with_identity(sdk, prompt, me):
    return await _one(sdk, prompt, me)


if __name__ == "__main__":
    main()
