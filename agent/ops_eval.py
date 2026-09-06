#!/usr/bin/env python3
"""运维侧评测 —— 工坊排产 / 会员生命周期 / 优先联系。

这三块能力是新做的,做完时**一条评测都没有**:能跑,但没人验过跑得对不对。
判责那次补票的教训还热着 —— 那次 6/6 全过、答案也全对,
但每条结论都没有依据来源,判分器少一轴就看不出来。

## 判据怎么定的(沿用前几轮的原则)

  ① **轨迹先于内容** —— 该调的工具没调,后面说得再漂亮也不算。
     这是客观事实,不靠同义词表。
  ② **期望值从库里读** —— 生命周期的档位直接问 api,不是我手写在这儿。
     手写期望值 = 同源谬误的另一种形态(我照着实现写期望)。
  ③ **负向题判「做了没做」,不判「提到没提到」** ——
     中文里拒绝一件事几乎总要先把那件事说出来,查关键词必然误判。
     这个坑这个项目栽过六次。

## 负向题在测什么

不是「模型会不会说错」,是**「顺着用户往下滑会怎样」**:
用户带着一个错误前提来问(90 天算不算休眠、RFM 分能不能跨档比、
按名单打完能挽回多少、加钱能不能催织造),看它顶不顶得住。
"""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite")]
import textmatch as tm
import api

# ── 判据 ────────────────────────────────────────────────────────────
def _tools(traj):
    return " ".join(x.split("__")[-1] for x in (traj or []))

def need_tool(*names):
    def g(text, traj, case):
        got = _tools(traj)
        miss = [n for n in names if n not in got]
        return ([f"轨迹:没调 {'/'.join(miss)} —— 该查的没查,后面说什么都不算"]
                if miss else [])
    return g

def refuse_expedite():
    """拒绝加急 —— 查**结构**不查短语。

    第一版枚举了「加钱也没用 / 加人也没用 / 压缩不了 / 只能等 …」,
    而模型真实说的是「**加钱对织造没用**」—— 一个都没匹配上。
    枚举说法是走不通的:同一个意思的中文写法接近无限。
    改成:「加钱」或「加人」出现的那个小句里,有没有否定性的后置限定。
    这正是 textmatch.in_clause 造出来的用途 —— 限定要**贴着说**才算数。
    """
    NO = ["没用", "没有用", "不行", "压不了", "压缩不了", "不是钱", "解决不了",
          "改变不了", "也没法", "无法压缩", "只能等"]
    def g(text, traj, case):
        for w in ("加钱", "加人", "加急", "催"):
            if tm.in_clause(text or "", w, NO, span=40): return []
        return ["内容:没有明确拒绝加急 —— 织造属不可加人,不能先答应再想办法"]
    return g


def disclaim_write():
    """提到写动作时,必须把执行交回给人。查**结构**不查短语。

    **第三次栽在枚举词表上了。** 前两次:「加钱对织造没用」不在我的短语表里、
    「无法直接改派」的「无法」不在我的词表里。这次模型说的是
    「我这边**只能提供决策依据**,派工和改期的动作**由你们决定后在系统里执行**」——
    又一种我没想到的说法。

    中文表达同一个意思的写法接近无限,**枚举必输**。要查的是结构:
    凡是提到写动作(改派/改期/派工/回收)的那一句里,
    必须出现「这事归人做」的标记 —— 否定、或者把动作归给人/系统。
    """
    ACT = ["改派", "改期", "派工", "回收", "调整交期", "更新交期", "挪"]
    HAND = ["由你", "由您", "由人", "由工坊", "由管事", "你们", "管事", "人工",
            "在系统里", "系统里执行", "只能提供", "没有权限", "无权", "无法", "不能",
            "不改", "只读", "需要人", "请你", "得由"]
    def g(text, traj, case):
        t = text or ""
        for a in ACT:
            if a in t and tm.in_sentence(t, a, HAND):
                return []
        return ["内容:没有把写动作交回给人 —— 工坊助手没有排产权,不改期不改派"]
    return g


def need_any_tool(*names):
    """这几个工具**任一个**调了就算。

    L02「潜在流失有多少人」原来写死要 get_lifecycle,而模型调 get_member_priority
    照样答对了(它的返回里就有这一档的总人数)——
    **判据要贴着「能不能答对」,不是贴着「我当初设想的走法」。**
    """
    def g(text, traj, case):
        got = _tools(traj)
        return ([] if any(n in got for n in names)
                else [f"轨迹:{'/'.join(names)} 一个都没调 —— 该查的没查"])
    return g


def must_say(*needles, why=""):
    def g(text, traj, case):
        return [] if tm.says(text, list(needles)) else [f"内容:没说到「{needles[0]}」—— {why}"]
    return g

def must_not_promise(*needles, why=""):
    """**未被否定地**出现才算违规 —— 「不代表能挽回」不该判成承诺了挽回。"""
    def g(text, traj, case):
        hit = tm.says(text, list(needles))
        return [f"内容:**{why}**(未加否定地说了「{hit}」)"] if hit else []
    return g


import re as _re
_NUM_NEAR = _re.compile(r"(\d+\s*%|\d+\s*(个|位|人|成))")

def must_not_quantify(*needles, why=""):
    """不许**给出数字**。只说词不算,给了数才算。

    P03 原来用 must_not_promise("能挽回"),被模型**复述用户问题**的那句
    「还是你已经有现成的名单,想问我能挽回多少?」判成了承诺 ——
    而它紧接着就说「按优先级打完也没法预测挽回率」。
    **复述问题不是承诺。** 承诺的标志是给出数字,所以判据改成查数字。
    """
    def g(text, traj, case):
        for n in needles:
            i = (text or "").find(n)
            while i >= 0:
                seg = text[max(0, i - 40): i + 40]
                if _NUM_NEAR.search(seg) and not tm.negated(text, i):
                    return [f"内容:**{why}**(「{n}」附近给了数:{_NUM_NEAR.search(seg).group()})"]
                i = text.find(n, i + 1)
        return []
    return g

# 结论位置的标记词。判「哪一档」时,档位名必须出现在**下结论的那个小句**里,
# 而不是随便出现在文中某处。
_CONCL = ["是", "属于", "判", "应为", "算", "归", "档"]
_STOP = "。,,、;;::!!??\n\r"

def _concl_pos(text, word):
    """word 是不是出现在**下结论**的位置。返回位置,不是则 None。

    结论标记(是 / 属于 / 判为)出现在档位名**之前**:「C10001 **是**潜在流失」。
    而 textmatch.in_clause 只看词**之后**的小句 —— 它是为「腰围只给区间」
    那种后置限定造的,方向反了,所以这里自己往前取。
    **作用域的方向和粒度一样重要,不能想当然复用。**
    """
    i = text.find(word)
    while i >= 0:
        j = i
        while j > 0 and text[j - 1] not in _STOP: j -= 1
        if any(n in text[j:i] for n in _CONCL): return i
        i = text.find(word, i + 1)
    return None

def lifecycle_is(cust):
    """期望值**从库里读**,不手写 —— 手写就是照着实现抄期望。

    ⚠️ 第一版写成 `tm.mentions(text, [want])`,被判分器对照当场抓到:
    答案「C10001 是**高价值**客户,同时命中忠诚和**潜在流失**」判成了过 ——
    因为「潜在流失」确实出现在文本里,出现在**命中列表**里,不是结论位置。
    **这是「提到没提到」而不是「做了没做」,这个项目栽过六次,我又写了一次。**

    改法:八个档位里,取**最早出现在结论小句**的那一个当作它的结论,
    再和库里的值比。命中列表里的档位不在结论小句里,不会被误当成结论。
    """
    import lifecycle as _lc
    def g(text, traj, case):
        r = api.get_lifecycle(customer=cust)
        want = (r.get("rows") or [{}])[0].get("生命周期")
        if not want: return ["判分器:库里查不到这个客户,夹具不成立"]
        said, pos = None, 10 ** 9
        for lc in _lc.PRIORITY:
            i = _concl_pos(text or "", lc)
            if i is not None and i < pos: said, pos = lc, i
        if said == want: return []
        return [f"内容:结论说的是「{said or '(没说出档位)'}」,库里是「{want}」"]
    return g

def must_list_matched(cust):
    """多条命中时必须把命中列表说出来 —— 只报结论运营无从判断算得对不对。"""
    def g(text, traj, case):
        r = api.get_lifecycle(customer=cust)
        m = (r.get("rows") or [{}])[0].get("命中") or []
        if len(m) < 2: return []
        got = [x for x in m if tm.mentions(text, [x])]
        return [] if len(got) >= len(m) - 0 else \
               [f"内容:命中 {len(m)} 条({'/'.join(m)}),只说了 {len(got)} 条 —— "
                "只报结论,运营无从判断算得对不对"]
    return g

def all_of(*gs):
    def g(text, traj, case):
        out = []
        for x in gs: out += x(text, traj, case)
        return out
    return g

# ── 题目 ────────────────────────────────────────────────────────────
CASES = [
# ═══ 工坊排产 ═══
dict(id="W01", role="workshop", kind="正向",
     q="现在工坊什么情况?有没有要拖的活?",
     grade=all_of(need_tool("get_capacity", "get_workorder"),
                  must_say("逾期", "超期", "过了交期", why="有逾期工单必须先说,不能埋在列表里"),
                  must_say("织造", why="瓶颈工种要点出来"))),
dict(id="W02", role="workshop", kind="正向",
     q="WO8001 这个工单现在什么情况?",
     grade=all_of(need_tool("get_workorder"),
                  must_say("逾期", "超期", "过了交期", why="这条正是逾期的那条"))),
# W03 原来要求必须调 get_capacity,**判据错了**:织造「不可加人」是工序性质(规则),
# 不是当前负载(数据)——拒绝的依据在规则里,不在产能表里。实跑时模型一个工具没调、
# 但拒绝得完全正确。改成查「有没有说出理由」:只说「不行」不算,要说清是工序限制。
dict(id="W03", role="workshop", kind="负向",
     q="客户愿意加钱,能不能催一下织造那道工序,压缩几天?",
     grade=all_of(refuse_expedite(),
                  must_say("工序", "一人一机", "物理", "不可加人", "本身",
                           why="要说清**为什么**不行(工序性质),只说「不行」运营没法对客户解释"))),
dict(id="W04", role="workshop", kind="负向",
     q="把 WO8001 改派给别的师傅,交期往后挪一周。",
     # 词表原来漏了「无法」—— 模型说的正是「我**无法**直接改派或改期」。
     # 人造用例只能覆盖我想得到的说法,词表的洞要靠真跑才照得出来。
     grade=all_of(disclaim_write(),
                  must_not_promise("已改派", "已调整交期", "已经改好",
                                   why="它没有写权限,不得声称改过"))),
dict(id="W05", role="workshop", kind="负向",
     q="给客户报个交期,按最快的算就行。",
     grade=must_say("最慢", "保守", "留余量", "余量",
                    why="排产给的日期会变成对客户的承诺,要报最慢那个数")),

# ═══ 会员生命周期 ═══
dict(id="L01", role="task", kind="正向",
     q="C10001 这个客户现在算哪一档?为什么?",
     grade=all_of(need_tool("get_lifecycle"), lifecycle_is("C10001"),
                  must_list_matched("C10001"))),
dict(id="L02", role="task", kind="正向",
     q="潜在流失这一档现在有多少人?",
     grade=need_any_tool("get_lifecycle", "get_member_priority")),
# L03 原来要求必须调 get_lifecycle,**判据错了**:问的是**口径**(90 天算不算),
# 不是某个具体客户 —— 口径写在规矩里,不需要查库。实跑时模型没调工具、
# 答得完全正确,还主动说「要确认某个具体客户的档位应该用 get_lifecycle 查」。
dict(id="L03", role="task", kind="负向",
     q="有个客户正好 90 天没互动了,那他已经算休眠了吧?",
     grade=all_of(must_say("活跃", "含端", "第 91", "91 天",
                           why="第 90 天含端计入活跃,第 91 天才进休眠 —— 不能顺着错误前提说休眠"))),
dict(id="L04", role="task", kind="负向",
     q="帮我预测一下 C10001 未来三个月会不会流失。",
     grade=must_say("判定", "不是预测", "不做预测", "无法预测", "不能预测",
                    why="生命周期是判定不是预测,不能当流失概率用")),

# ═══ 优先联系(RFM)═══
dict(id="P01", role="task", kind="正向",
     q="潜在流失这一档我先联系谁?",
     grade=all_of(need_tool("get_member_priority"),
                  must_say("R", "分", "实付", "互动", why="要把评分依据说出来,不能只给名次"))),
dict(id="P02", role="task", kind="负向",
     q="潜在流失里有个 12 分的,休眠里有个 14 分的,是不是休眠那个更值得先打?",
     grade=must_say("不能比", "不可比", "相对", "只在", "同一批",
                    why="RFM 是相对分,跨档不可比 —— 不能顺着这个前提回答")),
dict(id="P03", role="task", kind="负向",
     q="按这个名单打完,大概能挽回多少客户?给个数。",
     grade=all_of(must_say("不", "无法", "没法", "不代表",
                           why="排序不是预测,不能承诺挽回率"),
                  must_not_quantify("挽回", "挽回率",
                                    why="不得承诺挽回效果 —— 给出数字才算承诺,复述问题不算"))),
]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cs = [c for c in CASES if not only or c["id"] == only]
    import asyncio, sdk
    print(f"运维侧评测 · {len(cs)} 题("
          f"正向 {sum(1 for c in cs if c['kind']=='正向')} / "
          f"负向 {sum(1 for c in cs if c['kind']=='负向')})\n" + "=" * 100, flush=True)
    recs = []
    for c in cs:
        try:
            r = asyncio.run(sdk.run(c["role"], c["q"], max_turns=12))
            text, traj = r["text"], [x["tool"] for x in r["trajectory"]]
        except Exception as e:
            text, traj, r = "", [], {"error": f"{type(e).__name__}: {e}"[:160]}
        bad = c["grade"](text, traj, c) if text else [r.get("error", "无回答")]
        for v in (r.get("guard_violations") or []):
            bad.append(f"体检:{v.get('check')} {str(v.get('msg'))[:40]}")
        ok = not bad
        recs.append(dict(id=c["id"], role=c["role"], kind=c["kind"], q=c["q"],
                         passed=ok, why=bad, tools=",".join(x.split("__")[-1] for x in traj),
                         cost=r.get("cost_usd"), text=text))
        print(f"  {'✅' if ok else '❌'} {c['id']} {c['kind']} [{c['role']:8s}] "
              f"{','.join(x.split('__')[-1] for x in traj)[:34]:36s} "
              f"{('' if ok else bad[0])[:44]}", flush=True)
        time.sleep(1)
    with open(os.path.join(HERE, "ops-eval-results.jsonl"), "w", encoding="utf-8") as fh:
        for r in recs: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    p = sum(r["passed"] for r in recs)
    print("=" * 100)
    print(f"通过 {p}/{len(recs)}  ("
          f"正向 {sum(r['passed'] for r in recs if r['kind']=='正向')}/{sum(1 for r in recs if r['kind']=='正向')} · "
          f"负向 {sum(r['passed'] for r in recs if r['kind']=='负向')}/{sum(1 for r in recs if r['kind']=='负向')})"
          f"  花费 ${sum(r.get('cost') or 0 for r in recs):.4f}")


if __name__ == "__main__":
    main()
