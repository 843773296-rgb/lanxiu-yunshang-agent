# -*- coding: utf-8 -*-
"""技能三态 · 能用 / 请求了 / 加载了 / 被拦或失败分得开(证据中心 P1,需求文档 3.2)。真调 agentsite/skill_states.分类。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import skill_states as K

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, 数 = [], [0]

咬合 = [
    ("被守卫拦下的技能也记成已加载", "被拦下的技能 → 「被拦」,带拦截原话,不算加载"),
    ("没请求的技能也算进请求", "能用但没请求的 → 只出现在「没用上的」,不出现在请求里"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def 技(名, 回, 状态="unset", 版本="abc123"):
    a = {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "Skill", "lanxiu.skill.name": 名, "lanxiu.skill.sha256": 版本}
    if 回 is not None:
        a["gen_ai.tool.call.result"] = 回
    return {"span_id": 名, "parent_span_id": "r", "status": 状态, "attr": a}


def main():
    print("技能三态 · 能用 / 请求 / 加载 / 被拦")
    根 = {"span_id": "r", "parent_span_id": None, "attr": {"lanxiu.skills.available": ["store-report", "customer-recall", "quote", "roster"]}}
    k = K.分类([根, 技("store-report", "Launching skill: store-report"),
               技("customer-recall", "技能「customer-recall」现在的状态是「已停用」,没有放行,已拦下。", "error"),
               技("quote", "Error: skill file broken", "error"), 技("roster", None)])
    状 = {x["技能"]: x for x in k["请求"]}
    ck("正常加载 → 「已加载」,带请求那一刻的版本哈希", 状["store-report"]["状态"] == "已加载" and 状["store-report"]["版本"] == "abc123", 状.get("store-report"))
    ck("被拦下的技能 → 「被拦」,带拦截原话,不算加载", 状["customer-recall"]["状态"] == "被拦" and "没有放行" in (状["customer-recall"]["理由"] or ""), 状.get("customer-recall"))
    ck("出错但不是拦截 → 「加载失败」,带原因", 状["quote"]["状态"] == "加载失败" and "broken" in (状["quote"]["理由"] or ""), 状.get("quote"))
    ck("请求了却没有回执 → 「没有回执」(不猜成功或失败)", 状["roster"]["状态"] == "没有回执", 状.get("roster"))
    k2 = K.分类([根, 技("store-report", "Launching skill: store-report")])
    ck("能用但没请求的 → 只出现在「没用上的」,不出现在请求里", [x["技能"] for x in k2["请求"]] == ["store-report"]
       and set(k2["没用上的"]) == {"customer-recall", "quote", "roster"}, k2)
    ck("说明里写清「加载了不等于业务做成」", "业务" in k2["说明"] and "不单独判定" in k2["说明"])
    老 = K.分类([{"span_id": "r", "parent_span_id": None, "attr": {}}])
    ck("老记录没有可用清单 → 照实说没记,不当成「一个都不能用」", 老["可用"] == [] and "没记" in 老["说明"], 老)
    sdk = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
    app = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    ck("接线:根上记可用技能、Skill 调用记名字和版本哈希、/spans 回技能三态",
       '"lanxiu.skills.available": sorted(skills_for(skills))' in sdk and '"lanxiu.skill.sha256"' in sdk and "_ks.分类(rows)" in app)
    print()
    if 坏:
        print(f"{R}❌ 技能三态 {len(坏)} 条不过(验了 {数[0]} 条){D}")
        return 1
    print(f"{G}✅ 技能三态:能用 / 请求 / 加载 / 被拦 / 失败 / 没回执分得开,不重判历史(验了 {数[0]} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
