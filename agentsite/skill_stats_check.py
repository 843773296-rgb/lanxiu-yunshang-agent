# -*- coding: utf-8 -*-
"""Skill 使用统计的四处毛病(外部《MCP 与 Skill 现状核查》4.3 指出,10-23 核过属实并修)。

    ① 「从未触发的」永远是空 —— 正则去 sdk.py 找一个早已不存在的字面量
    ② 一轮调了两个技能只记第一个 —— 调用方用 next()
    ③ 页面写着「全部 239 个、自己写的三个」—— 现在是 243、7
    ④ 「成功」= 没撞预算 —— 被执行闸拦下的技能也算成功、也算「用了」

判据在**临时明细文件**上造它要验的那几种形状,不读真日志(真日志里有什么是碰巧的)。
用法:./agentsite/.venv/bin/python agentsite/skill_stats_check.py   (不调模型、不读库)
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import skill_stats as SS, skills_own as OWN, guards

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏 = 0

咬合 = [
    ("把 _declared 改回读 sdk.py 里的 SKILLS 字面量", "从未触发的:列得出来,而且就是自有清单里没被用过的那几个"),
    ("记一轮 只挑第一个 Skill 调用(退回 next())", "一轮两个技能:两个都记上"),
    ("被拦的也算进「用了」", "被执行闸拦下的:不算用了,另列"),
]


def ck(名, ok, 细=""):
    global 坏
    if not ok: 坏 += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {名}{'  ' + 细 if 细 else ''}")


def main():
    print("\n\033[1m▸ Skill 使用统计 · 在临时明细上造形状\033[0m")
    d = tempfile.mkdtemp(prefix="skill-stats-")
    SS.LOG = os.path.join(d, "skill_usage.jsonl")
    第三方 = "multi-platform-inventory-warning"
    ck("前提:执行闸放行自有、拦第三方", guards.pre_tool_verdict("Skill", {"skill": "quote"}) is None
       and bool(guards.pre_tool_verdict("Skill", {"skill": 第三方})))

    # 走 sdk 真用的那个入口(记一轮),喂轨迹,不直接喂技能名 —— 「从轨迹里挑」本身也要被验到
    def 调(n): return {"tool": "Skill", "args": {"skill": n}}
    读 = {"tool": "mcp__knowledge__kb_read", "args": {}}
    SS.记一轮([读], "随便问问")
    SS.记一轮([调("quote"), 读, 调("growth-plan")], "报个价顺便看看明年能不能穿")
    SS.记一轮([调("quote"), 调(第三方)], "报价 + 查淘宝库存")
    SS.记一轮([调("call-notes")], "整理通话", 撞预算=True)
    s = SS.stats()

    各 = s.get("各技能") or {}
    ck("一轮两个技能:两个都记上", 各.get("growth-plan") == 1 and 各.get("quote") == 2, f"各技能 {各}")
    ck("被执行闸拦下的:不算用了,另列", 第三方 not in 各 and (s.get("被拦下的") or {}).get(第三方) == 1,
       f"各技能 {各} · 被拦下的 {s.get('被拦下的')}")
    rows = [__import__("json").loads(l) for l in open(SS.LOG, encoding="utf-8") if l.strip()]
    ck("「成功」不再只是没撞预算:有被拦的、撞了预算的都不算成功",
       rows[1]["ok"] is True and rows[2]["ok"] is False and rows[3]["ok"] is False,
       f"ok 依次 {[r['ok'] for r in rows]}")
    ck("老读法兜底:skill 字段仍是第一个", rows[1]["skill"] == "quote" and rows[0]["skill"] is None)
    未 = s.get("从未触发的") or []
    应 = [x for x in OWN.OURS if x not in ("quote", "growth-plan", "call-notes")]
    ck("从未触发的:列得出来,而且就是自有清单里没被用过的那几个", sorted(未) == sorted(应),
       f"列出 {未} · 应为 {应}")
    ck("触发率的分母包括没触发的那一轮", s.get("总轮次") == 4 and s.get("触发了技能") == 3,
       f"总轮次 {s.get('总轮次')} 触发了 {s.get('触发了技能')}")

    try:
        import sdk
        全 = sdk._all_skills(); 自 = [x for x in 全 if OWN.is_ours(x)]
        说 = sdk.SKILL_SET_DESC
        ck("技能集合的说明是现算的数(不是写死的 239 / 3)",
           f"全部 {len(全)} 个" in 说["all"] and f"自己写的 {len(自)} 个" in 说["own"]
           and f"已放行的 {len(sdk.skills_for('own'))} 个" in 说["own"],
           f"all={说['all'][:30]} own={说['own'][:20]}")
    except ImportError as e:
        ck("技能集合的说明是现算的数(不是写死的 239 / 3)", False, f"sdk 导不进来:{e} —— 要用 venv 的 python 跑")

    print()
    if 坏:
        print(f"{R}❌ Skill 使用统计 {坏} 处不符合预期{D}"); return 1
    print(f"{G}✅ Skill 使用统计符合预期{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
