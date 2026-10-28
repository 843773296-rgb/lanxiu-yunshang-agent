#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每个技能的放行真相 —— **四列一起给,因为少一列就会说反话**。

    ./agentsite/.venv/bin/python tools/skill_gate_status.py          # 人看的表
    ./agentsite/.venv/bin/python tools/skill_gate_status.py --json   # 给管理后台取的

## 为什么非得四列一起

2026-10-27 栽的:三个技能(经营诊断 / 活动复盘 / 库存巡检)**两天没挂上**,
而门禁全绿、功能测试全绿、没有任何东西会红。我查 `skill_cfg` 看到**空表**,
得出「表里没有 = 放行,所以不是状态闸」—— 那句话**对自有技能成立,
对第三方的恰好相反**:

    skill_registry.状态()  库里读不到 → 退回 `默认状态(name)`
    sdk.py:637            没登记过的默认:**自有 = 已发布、第三方 = 待审查**

> 一条「表里没它所以放行」和一条「表里没它所以待审查」,
> **在「skill_cfg 是空表」这个事实上长得一模一样** —— 默认值藏在代码里,不在表里。

所以这个口给四列,**少任何一列都会让人读反**:

    在目录里吗   仓库里有这个技能的文件夹吗(有 ≠ 会被挂上)
    自有吗       is_ours —— **它决定默认值往哪边倒**
    放行吗       skill_registry.放行吗(状态 ∈ 试运行/已发布)
    真挂上了吗   sdk.skills_for('own') 里有没有它 ← **模型真正收到的那份名单**

⚠️ 「在目录里」和「真挂上了」是两件事,而这正是 10-27 那个 bug 的形状:
**目录里 13 个,挂上去 10 个。**
> 一个「这个技能在仓库里」和一个「这一轮真的挂给了模型」,
> **在查目录的结果上长得一模一样。**

## 这个口只读

不改任何状态。要放行一个技能得去 Skill 管理后台 ——
那是业务动作,不该有脚本能顺手做掉。
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "agentsite"), os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)


def 看一眼():
    """→ {"技能": [...四列...], "⚠️ 怎么读": ...}。**读不到就说读不到,不猜。**"""
    出 = {"技能": [], "⚠️ 怎么读": [
        "「在目录里」≠「真挂上了」—— 10-27 那次目录 13 个、挂上去 10 个",
        "默认值**分来源反着定**:自有 = 已发布、第三方 = 待审查(sdk.py:637)",
        "所以只看「放行吗」会对第三方说反话 —— 四列一起读",
    ]}
    try:
        import sdk, skills_own as own, guards
    except Exception as e:
        出["读不到"] = (f"import 失败({e})—— 这个口要用 agentsite 的 venv:"
                        f"`./agentsite/.venv/bin/python tools/skill_gate_status.py`")
        return 出
    目录 = sorted(sdk._all_skills()) if hasattr(sdk, "_all_skills") else []
    try:
        挂了 = set(sdk.skills_for("own"))
    except Exception as e:
        出["读不到"] = f"skills_for('own') 失败({e})"
        return 出
    reg = guards._skill_registry()
    for n in 目录:
        自 = None
        try:
            自 = bool(own.is_ours(n))
        except Exception:
            pass
        放 = 状 = None
        try:
            放 = bool(reg.放行吗(n))
            状 = reg.状态(n) if hasattr(reg, "状态") else None
        except Exception:
            pass
        出["技能"].append({"技能": n, "在目录里": True, "自有吗": 自,
                           "放行吗": 放, "状态": 状, "真挂上了": n in 挂了,
                           # 默认值从哪来 —— 这一列是为了让人不必去读代码
                           "没登记时的默认": ("已发布(自有)" if 自 else "待审查(第三方)")})
    挂而不在目录 = sorted(挂了 - set(目录))
    出["小结"] = {"目录里": len(目录), "真挂上了": len(挂了),
                  "在目录里却没挂上": [x["技能"] for x in 出["技能"] if not x["真挂上了"]],
                  # ⚠️ 这一项正常必须是空的;不空说明挂载清单和目录对不上
                  "⚠️ 挂了却不在目录里": 挂而不在目录}
    return 出


def main():
    r = 看一眼()
    if "--json" in sys.argv[1:]:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 1 if r.get("读不到") else 0
    if r.get("读不到"):
        print(f"❌ {r['读不到']}")
        return 1
    G, R, D, Y = "\033[32m", "\033[31m", "\033[0m", "\033[33m"
    print(f"技能放行真相 · 目录里 {r['小结']['目录里']} 个 · "
          f"真挂给模型 {r['小结']['真挂上了']} 个")
    print(f"  {'技能':30} {'自有':5} {'放行':5} {'真挂上':6} 状态 / 没登记时的默认")
    for x in r["技能"]:
        挂 = (G + "是" + D) if x["真挂上了"] else (R + "**没挂**" + D)
        print(f"  {x['技能']:30} {str(x['自有吗']):5} {str(x['放行吗']):5} {挂:6} "
              f"{x['状态'] or '(库里没登记)'} / {x['没登记时的默认']}")
    没挂 = r["小结"]["在目录里却没挂上"]
    if 没挂:
        print(f"\n{Y}⚠️ 在目录里却没挂给模型的 {len(没挂)} 个:{'、'.join(没挂)}{D}")
        print(f"   **它们按设计就不该触发** —— 要让它们上场,去 Skill 管理后台放行(业务动作)")
    if r["小结"]["⚠️ 挂了却不在目录里"]:
        print(f"{R}❌ 挂了却不在目录里:{r['小结']['⚠️ 挂了却不在目录里']} —— "
              f"挂载清单和目录对不上{D}")
        return 1
    for 句 in r["⚠️ 怎么读"]:
        print(f"   · {句}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
