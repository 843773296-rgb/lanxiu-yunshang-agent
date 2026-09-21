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

跑一次约 25 条 × **2 遍** × 30 秒 ≈ 25 分钟。用 Claude(订阅内,边际成本为零)。
**默认跑两遍**,报告会说清轮间抖了几条 —— 单跑一遍的数是一次抽样,不是结论。
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


async def _one(sdk, prompt, me, sset="own"):
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
    r = await sdk.run("all", prompt, provider=prov, model_name=mdl, me=me, skills=sset)
    return _skill_of(r.get("trajectory")), r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="只跑某一条")
    ap.add_argument("--save", help="把结果存成一版基线")
    ap.add_argument("--diff", help="和某版基线对比")
    ap.add_argument("--set", default="own",
                    help="用哪一档技能:own(自己的三个,默认)/ all(239 个)/ none。"
                         "**这一栏会记进结果文件** —— 不记的话,两次结果没法比:"
                         "分不清是改动的效果还是换了档")
    ap.add_argument("--retry", type=int, default=2,
                    help="跑崩了重试几次。**崩了不算答错了** —— 重试完还崩的单独计,不进准确率")
    # ⚠️ **默认 2,不是 1。**(2026-09-22 改。原来默认 1。)
    # 这个脚本此前**已经有**逐条重复 + wobbly + 对照组底噪 —— 机制比别的评测都细,
    # 但默认关着。于是它日常吐出来的永远是一个**单次抽样的准确率**,
    # 而报告上没有任何一个字说它只跑了一遍。
    #
    # > **一个默认关着的能力,和一个没有的能力,在报告上长得一模一样。**
    #
    # 代价是跑一次从 ~12 分钟变成 ~25 分钟。用 Claude 订阅内,边际成本为零;
    # 而一个不知道自己是不是抛硬币的数,省下的那 12 分钟会在下游赔回来。
    ap.add_argument("--repeat", type=int, default=2,
                    help="每条跑几遍(默认 2)。**单跑一次是有噪声的** —— "
                         "同一个问法两次结果可能不一样,分不清「改坏了」和「抖了一下」。"
                         "要图快可以 --repeat 1,那时 rounds.报() 会明说不能下结论")
    a = ap.parse_args()

    spec = json.load(open(CASES, encoding="utf-8"))
    cases = [c for c in spec["cases"] if not a.only or c["id"] == a.only]

    import sdk
    # 身份:排班/团队类问法要店长才答得了,否则会因为「你没这个权限」而不触发 ——
    # **那种不触发是权限挡的,不是描述不好**,混在一起测就分不清谁的责任。
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    me = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}

    import importlib as _il; _mid = _il.import_module("sdk").default_model_id()
    print(f"\n\033[1m技能触发评测 · {len(cases)} 条 · 模型 {_mid} · "
          f"技能档 {a.set}({len(_il.import_module('sdk').skills_for(a.set))} 个)\033[0m")
    print("=" * 88)
    rows, t0 = [], time.time()
    # 每一遍就是一轮 —— 攒成 rounds.py 要的形状 `[{用例: 过没过}, ...]`。
    # 逐条重复和「跑两轮」量的是同一件事,只是交错着跑;
    # 攒起来就能直接问那个问题:**这个差会不会被抖动淹掉。**
    轮数 = max(1, a.repeat)
    多轮 = [{} for _ in range(轮数)]
    轮因 = [{} for _ in range(轮数)]
    for c in cases:
        want = c.get("expect")
        # 跑 N 遍,**记下每一遍的结果** —— 稳定性本身是个要看的东西:
        # 一个「有时触发有时不触发」的技能,比稳定不触发更难查,
        # 因为它偶尔会给你一个「已经好了」的假象。
        got_all, 崩, 每遍 = [], [], []
        for _ in range(轮数):
            # ⚠️ **跑崩了不算答错了。** 2026-09-19 那次跑批暴露的:
            # 连着五条抛 ResultError(之后自己恢复,明显是瞬时故障),
            # 而它们被当成「触发结果」记进了准确率 ——
            # 期望不触发的记成**误触发**,期望触发的记成**漏触发**。
            # **「跑崩了」和「答错了」在准确率里长得一模一样。**
            #
            # 现在:崩了先重试;重试还崩就**单独记一类,不进准确率分母**,
            # 并在汇总里明说有几条没测到。**没测到不叫通过,也不叫失败。**
            g1 = None
            for _t in range(a.retry + 1):
                try:
                    g1, _r = asyncio.run(_run_with_identity(sdk, c["prompt"], me, a.set))
                    break
                except Exception as e:
                    g1 = f"ERR:{type(e).__name__}"
            每遍.append(g1)
            (崩 if str(g1).startswith("ERR:") else got_all).append(g1)

        # ── 把这一条的每一遍记进对应那一轮 ────────────────────────────
        # ⚠️ 崩掉的那一遍在两个地方待遇**不同,而且都是对的**:
        #   准确率里 → **剔除**(不然把环境问题算成能力,2026-09-19 就是这么错的)
        #   抖动报告里 → **留着记成没过**,理由写「跑挂了」
        #     (rounds.py 有专门的「跑挂」一类)。剔掉的话,
        #     「这一轮根本没跑完」会从抖动视图里**安静消失**,
        #     那条用例看上去就成了「稳定地挂着」。
        #
        # 失败理由一律标 **轨迹类**,这不是偷懒 —— 是**结构上就只能是它**:
        # `_skill_of()` 读的是工具调用的入参,**这把尺子根本不看模型说了什么**。
        # 所以这里的翻面永远不可能是「判据太吃措辞」,只能是模型这次行为变了。
        # 该改的是**技能描述**,不是判据。
        for _i, _g in enumerate(每遍):
            if str(_g).startswith("ERR:"):
                多轮[_i][c["id"]] = False
                轮因[_i][c["id"]] = [f"跑挂了:{_g}"]
                continue
            多轮[_i][c["id"]] = (_g == want)
            if _g != want:
                轮因[_i][c["id"]] = [
                    f"轨迹:该触发 {want or '(不触发)'},实际 {_g or '(无)'}"]

        if not got_all:
            print(f"  {R}✗{D} #{c['id']:<3} {c['prompt'][:30]:<32} "
                  f"{R}{len(崩)} 遍全崩({崩[0]}),这条没测到{D}")
            rows.append(dict(id=c["id"], prompt=c["prompt"], want=want, got=崩[0],
                             ok=None, kind="没测到", hits=0, runs=0, wobbly=False,
                             崩=len(崩)))
            continue
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

    没测到 = [x for x in rows if x["kind"] == "没测到"]
    rows_真 = [x for x in rows if x["kind"] != "没测到"]
    ok_n = sum(1 for x in rows_真 if x["ok"])
    miss = [x for x in rows if x["kind"] == "漏触发"]
    over = [x for x in rows if x["kind"] == "误触发"]
    wrong = [x for x in rows if x["kind"] == "触发错了技能"]
    print("=" * 88)
    if 没测到:
        print(f"  {R}没测到 {[x['id'] for x in 没测到]}{D} —— 重试完仍然抛异常,"
              f"**不进准确率分母**。没测到不叫通过,也不叫失败")
    print(f"  准确率 {ok_n}/{len(rows_真)}  ·  漏触发 {len(miss)}  ·  误触发 {len(over)}  ·  触发错技能 {len(wrong)}")
    print(f"  用时 {time.time()-t0:.0f} 秒")
    if miss:
        print(f"\n  {Y}漏触发的{D}(该走流程没走 —— 用户拿到的是随口答的东西):")
        for x in miss: print(f"    #{x['id']} 「{x['prompt'][:34]}」应触发 {x['want']}")
    if over:
        print(f"\n  {Y}误触发的{D}(随口一问,拿回来一份三段式文档):")
        for x in over: print(f"    #{x['id']} 「{x['prompt'][:34]}」不该触发,却触发了 {x['got']}")

    # ── 跑了几轮、抖了几条、能不能下结论 ──────────────────────────────
    # 上面那行准确率是**最后一轮**的数。它自己说不出是不是抛硬币,
    # 所以这里交给 agent/rounds.py 来说。
    sys.path.append(os.path.join(ROOT, "agent"))
    import rounds
    # 基线:`--diff` 指的那一版。⚠️ **不可比的基线不许交出去。**
    # 这和识图评测那条(图指纹对不上就不给基线)是**同一类**,不是同一处 ——
    # 那边是「图换了」,这边是「技能档换了 / 只跑了一部分用例」。
    # 交出去的话,rounds 会一本正经地算一个「版本差」,
    # 而那个差是换档换出来的,**和一个真的版本差长得一模一样**。
    基线, 基线来路 = None, None
    if a.diff:
        _p = os.path.join(RUNS, f"{a.diff}.json")
        if os.path.exists(_p):
            _b = json.load(open(_p, encoding="utf-8"))
            _档 = _b.get("技能档")
            _量过 = {x["id"] for x in _b.get("明细", []) if x.get("kind") != "没测到"}
            _n = len(_量过)
            _现 = {c["id"] for c in cases}
            _缺, _多 = _现 - _量过, _量过 - _现
            if _档 and _档 != a.set:
                print(f"  ℹ️ 基线 {a.diff} 是 {_档} 档跑的,这次是 {a.set} 档 —— "
                      f"**不拿它比**(换档的差和版本差长得一样)")
            elif len(cases) != len(spec["cases"]):
                print(f"  ℹ️ 这次只跑了 {len(cases)}/{len(spec['cases'])} 条 —— "
                      f"**不拿基线比**(分母都不一样)")
            elif _缺 or _多:
                # 实测撞到:`baseline.json` 是**用例还只有 15 条**的时候存的,
                # 而现在有 25 条。两个分母相减出来的「版本差」毫无意义,
                # 而它**和一个真的版本差长得一模一样**。
                # 题加了是好事,但**加题那一刻,所有老基线就到期了**
                # (`agentsite/evals/runs/` 里十份,一份都对不上现在的 25 条)。
                #
                # 判据比的是**哪几条**,不是**几条** —— 只比数量的话,
                # 「删一条又加一条」会正好对上,而那是两套完全不同的题。
                # 缺了 / 多了**分开报**:缺了是老基线没量过,多了是题被删过,
                # 两件事接下来要查的地方不一样。
                print(f"  ℹ️ 基线 {a.diff} 和现在的用例对不上,**不拿它比** —— "
                      + (f"它没量过 {len(_缺)} 条(#{'、#'.join(map(str, sorted(_缺)[:6]))}"
                         + (f" ……还有 {len(_缺)-6} 条" if len(_缺) > 6 else "") + ")"
                         if _缺 else "")
                      + ("；" if _缺 and _多 else "")
                      + (f"它量过但现在没有的 {len(_多)} 条" if _多 else ""))
            elif _n:
                基线 = sum(1 for x in _b.get("明细", []) if x.get("ok"))
                基线来路 = _b.get("来路")      # 老文件没有 → rounds 会拒收,这是对的
                print(f"  (基线取自 {a.diff}:{基线}/{_n})")
    rounds.报(多轮, 基线通过数=基线, 名="技能触发", 原因=轮因, 基线来路=基线来路)

    os.makedirs(RUNS, exist_ok=True)
    if a.save:
        p = os.path.join(RUNS, f"{a.save}.json")
        # **存基线时盖上来路**(供应商/模型/代码)—— 此前这一套自己拼 json、
        # 不走 evalrec,于是 `runs/*.json` 十份里**没有一份记着是谁跑的**。
        # 没来路的基线,rounds.报() 现在会拒收,而那是对的:
        # DeepSeek 跑的和 Claude 跑的,在这个文件里长得一模一样。
        import evalrec as _er
        json.dump(dict(准确率=f"{ok_n}/{len(rows_真)}", 技能档=a.set,
                       来路=_er.盖章(), 重复遍数=轮数,
                       没测到=[x["id"] for x in 没测到],
                       明细=rows, 技能哈希=_hashes()),
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n  已存基线:{p}")
    if a.diff:
        p = os.path.join(RUNS, f"{a.diff}.json")
        if not os.path.exists(p):
            print(f"\n  {R}没有基线 {a.diff}{D}"); return
        base = json.load(open(p, encoding="utf-8"))
        old = {x["id"]: x for x in base["明细"]}
        oldh, newh = base.get("技能哈希") or {}, _hashes()
        print(f"\n  \033[1m和基线 {a.diff} 对比\033[0m")
        # ⚠️ **老基线可能根本没记技能哈希**(`技能哈希` 是后来才加的字段)。
        # 那时 `oldh` 是空字典,于是每一个技能的哈希都「对不上」,
        # **236 个技能全被算成改过** —— 对照组当场清零,判断只好说「没有对照组」。
        #
        # 而它印出来的那句话是「这期间每份技能都改过」,**那是编的**:
        # 真相是「不知道哪些改过」。两句话的下一步动作相反 ——
        # 一个是「下次留一份不动的」,另一个是「这个基线做不了对照,换一版」。
        # (2026-09-22 接多轮时顺手撞到,`--diff baseline` 一跑就刷了半屏技能名。)
        if not oldh:
            改了的技能 = None
            print(f"    {Y}这期间改过的技能:**不知道** —— 基线 {a.diff} 没记技能哈希"
                  f"(那时还没开始记)。{D}"
                  f"\n      **这不等于「一个都没改」,也不等于「全改了」** ——"
                  f"下面分不出对照组,读不出效果。要对照请换一版记了哈希的基线")
        else:
            改了的技能 = {k for k, v in newh.items() if oldh.get(k) != v}
            _ks = sorted(改了的技能)
            print(f"    这期间改过的技能:"
                  + (f"{len(_ks)} 个 —— " + "、".join(_ks[:8])
                     + (f"  ……**还有 {len(_ks)-8} 个**" if len(_ks) > 8 else "")
                     if _ks else "(一个都没改)"))
        _ob = base.get("技能档")
        if _ob and _ob != a.set:
            print(f"    {R}⚠ 两次用的技能档不同({_ob} → {a.set})—— "
                  f"差异里混着「换了档」和「改了技能」两件事,读不出单独的效果。{D}")
        stat = {}

        # **按「这条用例的技能改没改」分两组。**
        # 没改的那组是**对照组** —— 它的变化量就是噪声。
        # 没有对照组的话,任何一条变化都会被读成「我这次改动的效果」,
        # 而实测:文件一个字没动的技能,用例照样 ±1/3 地抖。
        def _grp(x):
            want = next((c.get("expect") for c in spec["cases"] if c["id"] == x["id"]), None)
            return "改动组" if want in (改了的技能 or ()) else "对照组"

        if 改了的技能 is None:
            # **分不了组就别硬分。** 全丢进「对照组」会得出一句
            # 「对照组动了 N 条,这就是噪声底噪」—— 那是**把可能的真效果说成噪声**,
            # 和上面那句「每份技能都改过」错得一样离谱,只是方向相反。
            好 = [x for x in rows if x["ok"] and not old.get(x["id"], {}).get("ok")]
            坏 = [x for x in rows if not x["ok"] and old.get(x["id"], {}).get("ok")]
            print(f"\n    \033[1m整体\033[0m({len(rows)} 条)· 修好 {len(好)} · 变坏 {len(坏)}")
            for x in 坏: print(f"      {R}↓{D} #{x['id']} 「{x['prompt'][:28]}」原来对,现在 {x['kind']}")
            for x in 好: print(f"      {G}↑{D} #{x['id']} 「{x['prompt'][:28]}」原来错,现在对了")
            print(f"\n    \033[1m判断\033[0m\n      {Y}**读不出效果** —— 基线没记技能哈希,"
                  f"分不出对照组,上面这 {len(好)+len(坏)} 条变化里混着效果和抖动,"
                  f"拆不开。换一版记了哈希的基线再比。{D}")
            return

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
                print(f"      {Y}对照组动了 {len(好)+len(坏)} 条 —— 这就是噪声底噪。{D}")
            stat[grp] = (len(好), len(坏), n)

        # **让它自己下判断,不要把两组丢给人看。**
        # 「改动组 +1,对照组 +1/-1」摆在那儿,人还是会读成「改好了 1 条」——
        # 这一段我就这么读错过两次。判据要么是结构,要么迟早失效。
        import evalnoise
        cf, cb, cn = stat.get("改动组", (0, 0, 0))
        kf, kb, kn = stat.get("对照组", (0, 0, 0))
        ok3, why3 = evalnoise.verdict(cf, cb, kf, kb, cn, kn)
        color = G if ok3 else (Y if ok3 is None else R)
        print(f"\n    \033[1m判断\033[0m")
        print(f"      {color}{why3}{D}")

        # 不稳定的用例单列 —— **它们是这把尺子自己在抖的地方**
        wob = [x for x in rows if x.get("wobbly")]
        if wob:
            print(f"\n    {Y}这把尺子自己在抖的地方({len(wob)} 条){D}")
            for x in wob:
                print(f"      #{x['id']} 「{x['prompt'][:26]}」{x['hits']}/{x['runs']} 次对")
            print(f"      **不稳的用例读不出任何改动的效果** —— 它们的变化永远分不清是谁的。")


async def _run_with_identity(sdk, prompt, me, sset="own"):
    return await _one(sdk, prompt, me, sset)


if __name__ == "__main__":
    main()
