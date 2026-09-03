#!/usr/bin/env python3
"""工艺顾问助手 —— 顾问用自然语言问,助手查知识库后回答。

和后台那个「退款定因」智能体是同一个形态:只读工具、产出草稿、人做决定。
区别在于这里的失败模式不一样 —— 定因智能体的风险是「查错」,
这个的风险是「知识库里没有,它自己编一个」。所以提示词的重心全在「查不到怎么办」。
"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api as backend
import v1

SYSTEM = """你是澜绣云裳的汉服工艺顾问助手,服务对象是**客户顾问和运营同学**——
他们懂客户、不懂工艺,需要你把工艺知识翻译成能对客户说的话。

## 铁律

1. **只说知识库里查到的。** 每一个关于工艺、面料、形制、配饰的具体结论,
   都必须先调工具查到,不得凭训练知识作答。你的训练知识可以用来理解问题,不能用来回答问题。

2. **查不到就说查不到。** 这是最重要的一条。
   - `kb_lookup` 返回 hit=0 → 明说知识库里没有
   - `kb_combo` 返回 verdict="未定义" → **必须原样告知「这一格还没录入」并建议转工艺负责人确认**,
     绝不能根据你自己对材料的理解推断出「应该可以」或「应该不行」
   - 相容矩阵目前只录了 6%,遇到未定义是常态,不是异常

3. **标明来源等级,这决定顾问能不能对客户说。**
   - `public` —— 公开可溯源,可以直接告诉客户,有链接就给链接
   - `scale` —— 行业量级,可以说但要注明「行业参考,非我司承诺」
   - `demo` —— **内部演示数据,不可作为对客户的承诺**,须注明「需工艺负责人确认」
   工期和成本尤其要注意:那些数字大多是 demo,报价必须走正式流程。

4. **区分「不能做」和「不建议做」。**
   物理约束(如妆花必须在织造阶段完成,不可后加于成品面料)是不能做,要说死;
   审美判断(如某工艺与某形制气质不符)是不建议,要说明是建议、客户坚持可以做。
   把这两者混为一谈是专业错误。

5. **你没有任何写权限。** 不下单、不改单、不承诺工期和价格。
   涉及这些时,产出的是给顾问的话术草稿,由顾问决定怎么用。

6. **「客户说 X,我该推什么」这类问题,先用 `kb_tables` 查决策表。**
   顾问最常问的不是「缂丝是什么」,而是「客人说要仙气飘飘的,我推什么」。
   这类答案在决策表里(客户原话对照、选料决策、配饰形制搭配、工期档位、售后争议判定),
   不在单条工艺条目里。**用 `kb_lookup` 搜「仙气」当然搜不到 —— 那是关键词,不是工艺名。**

## 回答风格

顾问在客户面前等着用,所以:**先给结论,再给理由,最后给可以直接说出口的话术。**
不要写小作文。一般 5 行以内。涉及具体条目时带上编码(如 KF02 妆花)方便顾问复查。"""


def tools():
    return v1._tools("kb")


def ask(question, history=None, max_turns=8):
    """问一句,返回 (答案文本, 轨迹, 用量)。history 为 [(role, content)] 列表。"""
    pv = v1.provider()
    msgs = []
    for role, content in (history or []):
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": question})

    tin = tout = tcache = 0; calls = 0; traj = []; t0 = time.time(); answer = ""
    for _ in range(max_turns):
        resp = v1.call(pv, dict(model=pv["model"], max_tokens=1500, system=SYSTEM,
                                tools=tools(), messages=msgs),
                       purpose="工艺顾问", turn=len(traj) + 1)
        if "error" in resp:
            raise RuntimeError(json.dumps(resp["error"], ensure_ascii=False)[:300])
        calls += 1
        u = resp.get("usage", {})
        tin += u.get("input_tokens", 0); tout += u.get("output_tokens", 0)
        tcache += u.get("cache_read_input_tokens", 0)
        msgs.append({"role": "assistant", "content": resp["content"]})
        txt = "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text").strip()
        if txt: answer = txt
        if resp.get("stop_reason") != "tool_use": break
        results = []
        for blk in resp["content"]:
            if blk.get("type") != "tool_use": continue
            try:
                out = v1._dispatch("kb", blk["name"], blk["input"])
            except Exception as e:
                out = {"error": str(e)}
            traj.append(dict(tool=blk["name"], args=blk["input"],
                             brief=_brief(blk["name"], out)))
            results.append({"type": "tool_result", "tool_use_id": blk["id"],
                            "content": json.dumps(out, ensure_ascii=False)})
        msgs.append({"role": "user", "content": results})

    p = pv["price"]
    cost = (tin * p["inp"] + tcache * p["cache"] + tout * p["out"]) / 1_000_000
    return dict(answer=answer, trajectory=traj, calls=calls, seconds=round(time.time() - t0, 1),
                input=tin, output=tout, cost_local=round(cost, 6), model=pv["model"],
                messages=[m for m in msgs if isinstance(m.get("content"), str)])


def _brief(name, out):
    """把工具返回压成一句人看得懂的话,给页面显示用。"""
    if isinstance(out, dict):
        if out.get("hit") == 0: return "查不到"
        if "hit" in out: return f"命中 {out['hit']} 条"
        if "verdict" in out: return f"{out.get('craft','')}×{out.get('material','')} → {out['verdict']}"
        if "完成度" in out: return f"矩阵完成度 {out['完成度']},未定义 {out['未定义']} 格"
        if "error" in out: return out["error"][:40]
        if "name" in out: return f"{out.get('code','')} {out['name']}"
    return "已返回"


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "香云纱能不能做妆花?"
    r = ask(q)
    print(f"问:{q}\n")
    for t in r["trajectory"]:
        print(f"  ↳ {t['tool']}({json.dumps(t['args'],ensure_ascii=False)}) → {t['brief']}")
    print(f"\n{r['answer']}\n")
    print(f"—— {r['calls']} 次调用 · {r['seconds']}s · ${r['cost_local']:.4f} · {r['model']}")
