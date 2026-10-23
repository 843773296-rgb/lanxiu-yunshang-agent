# -*- coding: utf-8 -*-
"""技能使用埋点 —— **没有这个数据,「该不该再加一个技能」永远只能靠感觉答。**

抄自 Accio 的 skill-feedback。它的做法是两层:

    明细  SKILL_FEEDBACK_LOG.jsonl   追加写,只留最近 200 条
    聚合  SKILL_USAGE_STATS.json     **从明细重新算出来**,不是边写边累加

第二条是关键:**聚合值必须是明细的函数**。边写边累加的话,
写坏一次就永远差着,而且差多少查不出来 —— 你手上只有一个数,
没有第二个来源能对账。从明细重算就永远对得上,代价只是每次多算一遍
(200 条,可以忽略)。

这和这个项目里那条「真值必须是最终数据的函数」是同一条。
"""
import json, os, datetime, collections

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "evals", "skill_usage.jsonl")
MAX_LINES = 200


def record(skill, prompt, role=None, tools=None, seconds=None, ok=True, 被拦=None, 撞预算=None):
    """记一轮。skill=None / [] 表示这一轮没触发任何技能。

    **没触发也要记。** 只记触发的话,分母就没了 ——
    「触发了 12 次」这个数单独看毫无意义,要和「一共问了多少次」比才有。

    ⚠️ 10-23 改(外部《MCP 与 Skill 现状核查》4.3 指出,核过属实):
    · `skill` 可以是一串 —— 原来调用方用 next() 只取第一个,**一轮调了两个技能只记一个**。
      `skills` 存全部;`skill` 仍存第一个,给只认它的老读法(AI 管理平台同步)兜底。
    · `被拦`:执行闸拦下的那几个(第三方技能会被拦)。**「模型想调」和「真加载了」是两件事** ——
      原来只记想调的,被拦的也算进了「触发了」。
    · `撞预算` 单独一栏。原来 `ok = not 撞预算`,读起来像「技能成功了」,其实只说明没花超钱。
      `ok` 现在 = 没撞预算 **且** 没有被拦的;它仍然**不证明业务结果对** —— 那要看评测。
    """
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    全 = [x for x in (skill if isinstance(skill, (list, tuple)) else [skill]) if x]
    拦 = [x for x in (被拦 or []) if x]
    row = dict(ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               skill=(全[0] if 全 else None), skills=全 or None, 被拦=拦 or None,
               撞预算=bool(撞预算) if 撞预算 is not None else None,
               prompt=(prompt or "")[:120], role=role,
               tools=len(tools or []), seconds=seconds,
               ok=bool(ok) and not 撞预算 and not 拦)
    lines = []
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
    lines.append(json.dumps(row, ensure_ascii=False) + "\n")
    with open(LOG, "w", encoding="utf-8") as f:
        f.writelines(lines[-MAX_LINES:])
    return row



def 记一轮(traj, prompt, role=None, seconds=None, 撞预算=None):
    """从这一轮的轨迹里挑出**每一次** Skill 调用记下(原来 sdk 用 next() 只取第一个)。

    被拦没被拦**问执行闸本身**(guards.pre_tool_verdict),不在这里照着样子另判一遍 ——
    另判一遍的话,闸改了这里不跟,统计就会说一个被拦的技能「用了」。
    """
    import guards as _gd
    调 = [t for t in (traj or []) if (t.get("tool") or "") == "Skill"]
    def 名(t):
        a = t.get("args") or {}
        return str(a.get("skill") or a.get("command") or "?").strip().lstrip("/")
    return record([名(t) for t in 调], prompt, role=role, tools=traj, seconds=seconds,
                  被拦=[名(t) for t in 调 if _gd.pre_tool_verdict("Skill", t.get("args") or {})],
                  撞预算=撞预算)


def stats():
    """从明细**重新算**聚合。不是边写边累加 —— 累加值写坏一次就永远差着。"""
    if not os.path.exists(LOG):
        return dict(说明="还没有任何记录", 总轮次=0)
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()]
    n = len(rows)
    def _全(r): return r.get("skills") or ([r["skill"]] if r.get("skill") else [])
    hit = [r for r in rows if _全(r)]
    # 一轮两个技能记两次;**被拦下的不算「用了」**,另列
    by = collections.Counter(x for r in hit for x in _全(r) if x not in (r.get("被拦") or []))
    拦 = collections.Counter(x for r in rows for x in (r.get("被拦") or []))
    import statistics
    def _avg(xs): return round(statistics.mean(xs), 1) if xs else None
    return dict(
        总轮次=n, 触发了技能=len(hit),
        触发率=f"{len(hit)*100//n if n else 0}%",
        各技能=dict(by),
        被拦下的=dict(拦) or None,
        # **一次都没触发过的技能要单独列。** 它不出现在计数里,
        # 所以最容易被当成「用得少」而不是「从来没用过」——
        # 后者是描述有问题,前者可能只是场景少。
        从未触发的=[s for s in _declared() if s not in by] or None,
        平均耗时秒=_avg([r["seconds"] for r in rows if r.get("seconds")]),
        最近=[dict(时间=r["ts"][5:16], 技能=r.get("skill") or "(无)",
                  问的=r["prompt"][:34]) for r in rows[-8:]])


def _declared():
    """默认上场的技能 —— 从 skills_own 读,**不在这儿抄一份**。

    ⚠️ 原来是拿正则去 sdk.py 里找 `SKILLS = [...]` 字面量。sdk 后来改成
    `SKILLS = skills_for("own")`(现算),正则从此一个都匹配不上,返回空 ——
    于是「从未触发的」**永远是空**,看着像「每个技能都用过」(外部核查 10-22 指出,10-23 修)。
    > 一张「没有从未触发的」和一张「根本没去比」的表,长得一模一样。
    读模块而不是 import sdk:这个文件要能在系统 python3 上跑,sdk 要 claude_agent_sdk。
    """
    import skills_own as _own
    return list(_own.OURS)

if __name__ == "__main__":
    import sys
    if "--reset" in sys.argv:
        open(LOG, "w").close(); print("清空了"); sys.exit()
    s = stats()
    print(f"\n\033[1m技能使用统计\033[0m")
    print("=" * 66)
    print(f"  总轮次 {s['总轮次']} · 触发了技能 {s.get('触发了技能', 0)} 次 · 触发率 {s.get('触发率')}")
    for k, v in (s.get("各技能") or {}).items():
        print(f"    {k:16s} {v} 次")
    if s.get("从未触发的"):
        print(f"  \033[33m从未触发过的:{s['从未触发的']}\033[0m")
        print(f"    一次都没触发和「用得少」不是一回事 —— 前者多半是描述有问题。")
    print(f"  平均耗时 {s.get('平均耗时秒')} 秒")
    print("\n  最近几轮:")
    for r in s.get("最近", []):
        print(f"    {r['时间']}  {r['技能']:14s} {r['问的']}")
