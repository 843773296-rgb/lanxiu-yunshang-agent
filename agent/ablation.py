#!/usr/bin/env python3
"""提示词消融 —— 拿掉一条规矩,看分掉不掉。

## 为什么要有这个

提示词是**加出来**的:每次出问题就补一条,补完没人回头验。于是你手上有一份
十几条的铁律,却没有一条知道它到底在不在起作用。这和「没红过的检查」是同一个病 ——
**没被拿掉验证过的规矩,你不知道它是在守门还是在占地方。**

更坏的一种情况是**加了反而掉分**:合并两份提示词那一次,20 题从 20/20 掉到 17/20,
掉的全是负向题(该拒绝的没拒绝)。多给规矩不等于更听话 ——
规矩之间会抢注意力,一条讲得太具体的会把另一条挤掉。

## 判读的三种结果,不能混

  ✅ 掉分   —— 这条在起作用,留着
  ❓ 不掉分 —— **两种可能**:它是安慰剂,或者**你的用例根本没测它**。
                这两者不能混为一谈,不能凭「不掉分」就删规矩。
  ⚠️ 涨分   —— 它在帮倒忙(通常是抢了别条的注意力)

## 用法
    python3 agent/ablation.py                 # 跑默认的几个变体(只跑负向题)
    python3 agent/ablation.py --all           # 正负向全跑
    python3 agent/ablation.py --repeat 3      # 每个变体重复 3 遍
    python3 agent/ablation.py --only 1,4      # 只跑第 1 和第 4 个变体

## 必须重复跑

第一次跑的时候栽了个跟头,值得写下来:「完全回到合并前」这个变体拿了 4/6,
而**同一份提示词**之前在 git 里记录的成绩是 6/6。同一个模型、同一批题,
两次差 2 分 —— 6 道题跑一遍的差异**根本不足以判断一条规矩有没有用**。

**先确认尺子稳不稳,再拿它量东西。** 单跑一遍的消融结果只能提出假设,不能下结论。
"""
import copy, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "backend"))
import chat, chat_eval, prompts


def assemble_with(drop=(), edits=None):
    """按 chat.py 的真实工具集装配,但去掉 drop 里的条、并按 edits 改写文本。"""
    have = {t["name"] for t in chat.tools()}
    saved = prompts.KB_RULES[:]
    try:
        prompts.KB_RULES[:] = [r for r in saved if r.id not in drop]
        for rid, txt in (edits or {}).items():
            for i, r in enumerate(prompts.KB_RULES):
                if r.id == rid:
                    prompts.KB_RULES[i] = prompts.Rule(r.id, r.needs, txt, r.avoid)
        return prompts.assemble("kb", have)
    finally:
        prompts.KB_RULES[:] = saved


def run_variant(name, sysprompt, cases, rep=1):
    chat._SYS = sysprompt
    hits, detail = 0, []
    for c in cases * rep:
        try: r = chat.ask(c["q"])
        except Exception as e: r = dict(answer="", trajectory=[], error=str(e)[:120])
        ok, why = (c["grade"](r) if r.get("answer") else (False, r.get("error", "无回答")))
        hits += ok; detail.append(dict(id=c["id"], passed=bool(ok), judge=why[:70]))
        print(f"     {'✅' if ok else '❌'} {c['id']}  {why[:56]}", flush=True)
        time.sleep(1.0)
    chat._SYS = None
    return hits, detail


# TL02 的旧措辞 —— 合并之前 chat.py 里那一版,**没有**「rule 字段是依据」那条
TL02_OLD = """
**查不到就说查不到。** 这是最重要的一条。
- `kb_lookup` 返回 hit=0 → 明说知识库里没有
- `kb_combo` 返回 verdict="未定义" → **必须原样告知「这一格还没录入」并建议转工艺负责人确认**,
  绝不能根据你自己对材料的理解推断出「应该可以」或「应该不行」
- 相容矩阵目前只录了 6%,遇到未定义是常态,不是异常
"""

NEW_ON_CHAT = ("TL07", "TL08", "TL12", "TL15")   # 合并时这条路径新拿到的四条

VARIANTS = [
    ("当前(10 条,TL02 含「依据」那条)", lambda: assemble_with()),
    ("TL02 回到旧措辞(去掉「依据」那条)", lambda: assemble_with(edits={"TL02": TL02_OLD})),
    ("去掉新增的四条(TL07/08/12/15)", lambda: assemble_with(drop=NEW_ON_CHAT)),
    ("完全回到合并前(旧 TL02 + 去四条)",
     lambda: assemble_with(drop=NEW_ON_CHAT, edits={"TL02": TL02_OLD})),
]


def _arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    allcases = "--all" in sys.argv
    rep = int(_arg("--repeat", "1"))
    pick = _arg("--only", "")
    vs = [v for i, v in enumerate(VARIANTS, 1)
          if not pick or str(i) in pick.split(",")]
    cases = [c for c in chat_eval.CASES if allcases or c["kind"] == "负向"]
    n = len(cases) * rep
    print(f"提示词消融 · {len(cases)} 题 × {rep} 遍 = {n} 次"
          f"({'正负向全跑' if allcases else '只跑负向'}) · {len(vs)} 个变体\n" + "=" * 88, flush=True)
    out = []
    for name, mk in vs:
        txt, ids = mk()
        print(f"\n▸ {name}   装上 {len(ids)} 条:{' '.join(ids)}", flush=True)
        hits, detail = run_variant(name, (txt, ids), cases, rep)
        # 每题分别看命中几遍 —— 一直挂的和偶尔挂的是两种问题
        per = {}
        for d in detail: per.setdefault(d["id"], []).append(d["passed"])
        print(f"   → {hits}/{n}   " + " ".join(
            f"{k}:{sum(v)}/{len(v)}" for k, v in sorted(per.items())), flush=True)
        out.append(dict(variant=name, rule_ids=ids, hits=hits, n=n,
                        per_case={k: [sum(v), len(v)] for k, v in per.items()}, detail=detail))
    with open(os.path.join(HERE, "ablation-results.jsonl"), "w", encoding="utf-8") as fh:
        for r in out: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n" + "=" * 88)
    for r in out:
        print(f"  {r['hits']}/{r['n']}   {r['variant']}")
        print("           " + " ".join(f"{k}:{a}/{b}" for k, (a, b) in sorted(r["per_case"].items())))
    print("\n  一直挂的 = 真问题;有时挂有时过的 = 噪声,别拿它当消融结论。")
    print("\n  ❓ 不掉分有两种解释:这条是安慰剂,**或者用例没测到它**。")
    print("     别凭「不掉分」就删规矩 —— 那和「没有用例的规则」是同一个病。")


if __name__ == "__main__":
    main()
