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

# 提示词的唯一源头在根目录 prompts.py。
# 这里原来有**另一份**同角色的提示词(6 条铁律),而 agentsite/sdk.py 里是 14 条。
# 后来加的规矩(kb_bom 是成本不是售价、kb_fit 不许猜码、版型裁不出来 …)
# 只进了那一份 —— 而这条路径(后台 8760 的 /api/chat)在线上一样在跑,
# **评测跑的还是这一份**,于是评出来的分不代表产品。
#
# 现在按**本进程实际挂了哪些工具**装配:kb_* 十个工具能装上 10 条,
# 需要 get_wearer / get_order / 图片的那几条自动不发 —— 这条路径确实没有那些工具,
# 发了等于让模型去承诺一件它做不到的事。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import prompts

_SYS = None
def system():
    """按当前工具集装配,只算一次。"""
    global _SYS
    if _SYS is None:
        _SYS = prompts.assemble("kb", {t["name"] for t in tools()})
    return _SYS


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
        resp = v1.call(pv, dict(model=pv["model"], max_tokens=pv.get("max_tokens", 1500), system=system()[0],
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

    p = v1.price_now(pv)               # 分时定价:高峰 ×2
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
