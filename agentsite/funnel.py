# -*- coding: utf-8 -*-
"""影子埋点:**只观测,不改行为。**

抄自 Accio 的 intent-plan-telemetry.js。它开头那段是整批代码里论证最清楚的一处:

    上线后如果只看到「plan 还是很少」,无法区分五种完全不同的原因 ——
    复合 query 本身少 / gate 没命中 / gate 命中但模型没补 plan /
    请求走的是主 Agent 直连没有注册入口 / plan 有了但 outcome 没被应用。
    **这五种对应五套不同的改法,靠观察一个指标区分不了。**

我刚做的「复合请求必须用 assign_batch」那条闸有一模一样的问题。
它要是从来不触发,我分不清是:

    ① 用户根本没提过复合请求
    ② 我的正则没命中(判据太紧)
    ③ 命中了,但模型本来就用的 batch(闸没必要)
    ④ 拦下来了,但模型没改成 batch(拦了也没用)
    ⑤ 模型压根没走写路径(问题在别处)

**五种对应五套改法。** 所以先把漏斗打出来,再决定要不要动那条闸。

## 四条设计约束(照抄他们的,每条都有理由)

1. **绝不改变执行行为** —— 只写记录、只输出日志,不拦不改不参与判定。
2. **每个事件即时落一行,轮末再落一条汇总行,两者都要。**
   汇总行的价值在终态(一次就能看分布),但**单轮会话永远等不到汇总** ——
   用户问一次拿到结果就走。而那恰恰是最需要观测的样本。
   他们的日报把「单轮会话无法 flush」列为 P0:
   **拿不到数据不是因为链路没跑,是因为没人写下来。**
3. **超限后落一行 truncated 说明,不静默丢** ——
   否则读数的人会把「被截断」当成「没发生」。
4. **全程不抛异常** —— 埋点失败不能影响业务链路。
"""
import json, os, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "evals", "funnel.jsonl")
EVENT_BUDGET = 40          # 一轮最多落 40 行事件;超了落一行 truncated,不静默丢
MAX_LINES = 800


def _write(row):
    """落一行。**任何异常都吞掉** —— 埋点坏了不能让业务跟着坏。"""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        lines = []
        if os.path.exists(LOG):
            lines = [l for l in open(LOG, encoding="utf-8") if l.strip()]
        lines.append(json.dumps(row, ensure_ascii=False) + "\n")
        with open(LOG, "w", encoding="utf-8") as f:
            f.writelines(lines[-MAX_LINES:])
    except Exception:
        pass


def event(state, kind, **kw):
    """记一个事件。state 是这一轮的共享字典。"""
    try:
        n = state.get("_funnel_n", 0)
        if n > EVENT_BUDGET:
            return
        if n == EVENT_BUDGET:
            state["_funnel_n"] = n + 1
            _write(dict(t="event", kind="truncated",
                        说明=f"这一轮事件超过 {EVENT_BUDGET} 条,后面的没记 —— "
                             f"**这行是为了让你知道被截断了**,而不是以为没发生",
                        ts=datetime.datetime.now().strftime("%H:%M:%S")))
            return
        state["_funnel_n"] = n + 1
        _write(dict(t="event", kind=kind,
                    ts=datetime.datetime.now().strftime("%H:%M:%S"), **kw))
    except Exception:
        pass


def turn(state, prompt, traj, me=None):
    """轮末汇总一行。**和逐事件行两者都要**,缺一不可。"""
    try:
        import guards
        names = [(t.get("tool") or "").rsplit("__", 1)[-1] for t in (traj or [])]
        # 写工具清单**从 api.WRITE_TOOLS 取,不在这儿抄一份**。
        # 抄一份的下场刚发生过:加了 dispatch_batch,guards 那边跟上了、这边没跟上,
        # 于是漏斗报「走写路径 0」而实际写了 —— **而且不报错**。
        # 这是同一个病的第三次(前两次:白名单漏工具、边界攻击用旧格式)。
        import sys as _s, os as _o
        _s.path.insert(0, _o.path.join(HERE, "..", "backend"))
        import api as _api
        WR = set(_api.WRITE_TOOLS)
        writes = [n for n in names if n in WR]
        _write(dict(
            t="turn", ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            角色=(me or {}).get("role"),
            问的=(prompt if isinstance(prompt, str) else "(带图)")[:80],
            # ① 这句话像不像复合请求(按闸的判据)
            像复合请求=guards._looks_compound(prompt if isinstance(prompt, str) else ""),
            # ② 走没走写路径 —— 没走的话前面那条判断的对错无从谈起
            走了写路径=bool(writes),
            用了批量=bool({"assign_batch", "dispatch_batch"} & set(names)),
            单条写次数=len([n for n in writes if n != "assign_batch"]),
            # ③ 闸拦了几次、拦的是什么
            被拦次数=len(state.get("_funnel_blocks") or []),
            拦的理由=[b[:40] for b in (state.get("_funnel_blocks") or [])[:3]] or None,
            触发的技能=next((( (t.get("args") or {}).get("skill"))
                          for t in (traj or []) if (t.get("tool") or "") == "Skill"), None),
            工具数=len(names)))
    except Exception:
        pass


def report():
    """看漏斗。**分开数那五种情况** —— 一个总数区分不了它们。"""
    if not os.path.exists(LOG):
        return dict(说明="还没有记录")
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()]
    turns = [r for r in rows if r.get("t") == "turn"]
    if not turns:
        return dict(说明="还没有完整的轮次记录")
    像复合 = [r for r in turns if r.get("像复合请求")]
    写路径 = [r for r in turns if r.get("走了写路径")]
    复合且写 = [r for r in 像复合 if r.get("走了写路径")]
    return dict(
        总轮次=len(turns),
        走了写路径=len(写路径),
        像复合请求=len(像复合),
        既像复合又走了写路径=len(复合且写),
        # 这四个数分别对应四种改法 ——
        # 都是 0 的话,说明「复合请求要用批量」这条闸目前一次都没派上用场
        其中直接用了批量=len([r for r in 复合且写 if r.get("用了批量")]),
        其中被拦过=len([r for r in 复合且写 if r.get("被拦次数")]),
        拦了之后改用批量=len([r for r in 复合且写 if r.get("被拦次数") and r.get("用了批量")]),
        不像复合却走了批量=len([r for r in 写路径 if not r.get("像复合请求") and r.get("用了批量")]),
        技能触发=len([r for r in turns if r.get("触发的技能")]),
        最近=[dict(时间=r["ts"][5:16], 问的=r["问的"][:30],
                  像复合=r.get("像复合请求"), 写=r.get("走了写路径"),
                  批量=r.get("用了批量"), 拦=r.get("被拦次数"))
             for r in turns[-8:]])


if __name__ == "__main__":
    r = report()
    print("\n\033[1m复合请求漏斗(影子观测,不改行为)\033[0m")
    print("=" * 74)
    if r.get("说明"):
        print("  " + r["说明"]); raise SystemExit
    print(f"  总轮次 {r['总轮次']} → 走写路径 {r['走了写路径']} → 像复合请求 {r['像复合请求']} "
          f"→ 既像复合又写 {r['既像复合又走了写路径']}")
    print()
    print(f"    其中直接用了批量   {r['其中直接用了批量']}   ← 闸没必要")
    print(f"    其中被拦过         {r['其中被拦过']}   ← 闸起了作用")
    print(f"      拦了之后改用批量 {r['拦了之后改用批量']}   ← **拦了有没有用,看这个**")
    print(f"    不像复合却用批量   {r['不像复合却走了批量']}   ← 判据太紧,漏了")
    print(f"    技能触发           {r['技能触发']}")
    print()
    print("  **四个数对应四套改法** —— 一个总数区分不了它们:")
    print("    都是 0 → 这条闸一次没派上用场,先别改判据,先看有没有人提复合请求")
    print("    被拦多但没改成批量 → 拦了也没用,提示词说得不够清楚")
    print("    不像复合却用批量 → 判据太紧,该放宽")
    print("\n  最近几轮:")
    for x in r["最近"]:
        print(f"    {x['时间']}  {x['问的']:<32} 复合={str(x['像复合']):5s} "
              f"写={str(x['写']):5s} 批量={str(x['批量']):5s} 拦={x['拦']}")
