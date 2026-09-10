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


def record(skill, prompt, role=None, tools=None, seconds=None, ok=True):
    """记一次技能触发。skill=None 表示这一轮没触发任何技能。

    **没触发也要记。** 只记触发的话,分母就没了 ——
    「触发了 12 次」这个数单独看毫无意义,要和「一共问了多少次」比才有。
    """
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    row = dict(ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               skill=skill, prompt=(prompt or "")[:120], role=role,
               tools=len(tools or []), seconds=seconds, ok=bool(ok))
    lines = []
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
    lines.append(json.dumps(row, ensure_ascii=False) + "\n")
    with open(LOG, "w", encoding="utf-8") as f:
        f.writelines(lines[-MAX_LINES:])
    return row


def stats():
    """从明细**重新算**聚合。不是边写边累加 —— 累加值写坏一次就永远差着。"""
    if not os.path.exists(LOG):
        return dict(说明="还没有任何记录", 总轮次=0)
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()]
    n = len(rows)
    hit = [r for r in rows if r.get("skill")]
    by = collections.Counter(r["skill"] for r in hit)
    import statistics
    def _avg(xs): return round(statistics.mean(xs), 1) if xs else None
    return dict(
        总轮次=n, 触发了技能=len(hit),
        触发率=f"{len(hit)*100//n if n else 0}%",
        各技能=dict(by),
        # **一次都没触发过的技能要单独列。** 它不出现在计数里,
        # 所以最容易被当成「用得少」而不是「从来没用过」——
        # 后者是描述有问题,前者可能只是场景少。
        从未触发的=[s for s in _declared() if s not in by] or None,
        平均耗时秒=_avg([r["seconds"] for r in rows if r.get("seconds")]),
        最近=[dict(时间=r["ts"][5:16], 技能=r.get("skill") or "(无)",
                  问的=r["prompt"][:34]) for r in rows[-8:]])


def _declared():
    """代码里声明了哪些技能 —— 从 sdk 读,**不在这儿抄一份**。"""
    import re
    src = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
    m = re.search(r"^SKILLS = \[(.*?)\]", src, re.M)
    return [x.strip().strip('"\'') for x in m.group(1).split(",")] if m else []


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
