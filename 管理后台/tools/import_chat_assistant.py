#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把聊天站代码里那一份助手配置导进后台,当基线版本(用户 2026-10-28 拍「聊天助手配置页分两步」)。

## 为什么要用聊天站的环境跑

基线必须是**聊天站真在用的那一份**:开头提示词、这个角色挂的工具、按工具装上的规矩、默认模型。
这些只有 `agentsite/sdk.py` + 根目录 `prompts.py` 知道,而 sdk 要 `claude_agent_sdk`。
所以这里**调它们自己的代码**(`prompts.assemble` / `sdk._tools_for` / `sdk._have`),
不在后台照样子再写一份 —— 照样子写的那份和真的那份,在导进去的那一刻就可能已经不一样。

## 后台会再对一遍

后台按它导入的规矩(`import_lanxiu_prompts.py` 那 7x 条)把「装上哪几条」推算一遍,
和这里真装配出的比 —— 对不上就拒导(RULE_PICK_MISMATCH),多半是规矩改了没重导。

## 不做什么

- 不碰聊天站:只读代码、不改任何东西。**第 1 步聊天站还不读后台**
- 内容没变就什么都不动(后台按内容哈希判),反复跑不出噪音版本

跑:`./agentsite/.venv/bin/python 管理后台/tools/import_chat_assistant.py [--角色 task] [--看]`
"""
import argparse
import json
import os
import subprocess
import sys

这 = os.path.dirname(os.path.abspath(__file__))
仓 = os.path.dirname(os.path.dirname(这))
G, R, D = "\033[32m", "\033[31m", "\033[0m"
显示名 = {"task": "店长助手"}       # 界面上那个角色叫「后台运营」,店里人叫它店长助手


def 快照(角色):
    sys.path[:0] = [os.path.join(仓, "agentsite"), 仓, os.path.join(仓, "backend")]
    import prompts
    import sdk
    import api
    工具 = list(sdk._tools_for(角色))
    have = sdk._have(角色)
    文本, 装上 = prompts.assemble(角色, have)
    head, rules, foot = prompts.ROLES[角色]
    写 = {str(t).rsplit("__", 1)[-1] for t in api.WRITE_TOOLS}
    名 = {t.rsplit("__", 1)[-1] for t in 工具}
    meta = sdk.ROLE_META.get(角色) or {}
    return {
        "角色键": 角色, "名称": 显示名.get(角色, meta.get("name") or 角色),
        "用途": f"聊天站「{meta.get('name', 角色)}」角色 —— {meta.get('desc', '')}",
        "开头": head, "结尾": foot,
        "工具": [{"名": t, "写": t.rsplit("__", 1)[-1] in 写} for t in 工具],
        # have 里不是工具名的那几个(比如「图片」)是能力标记,挑规矩时要算上
        "能力标记": sorted(set(have) - 名),
        "模型": sdk.网站默认模型(), "可选模型": [m["id"] for m in sdk.models()],
        "规矩池": [r.id for r in rules], "装上的规矩": list(装上),
        "提示词全文": 文本,
        "技能": list(sdk.skills_for("own")),
    }


def _后台(a, 方法, 路, 体=None):
    r = subprocess.run(["curl", "-sS", "-m", "30", "-w", "\n%{http_code}", "-X", 方法,
                        f"{a.基址}/api/v1/projects/{a.项目}{路}", "-H", f"X-Dev-User: {a.谁}",
                        "-H", "content-type: application/json"] + (["--data-binary", "@-"] if 体 is not None else []),
                       input=(json.dumps(体, ensure_ascii=False) if 体 is not None else None), capture_output=True, text=True)
    正文, _, 码 = r.stdout.rpartition("\n")
    try:
        return 码, json.loads(正文) if 正文 else {}
    except ValueError:
        return 码, {"原文": (正文 or r.stderr)[:400]}


def 技能那一支(a):
    """--只同步技能 / --核对技能(用户 11-11:路由点名「库存巡检 / 活动复盘 / 经营数诊断」被拦,
    因为后台的技能清单是导入那天拍的快照,而聊天站按 Skill 管理现算 —— 补一次不解决漂移,所以还要能核)。"""
    sys.path[:0] = [os.path.join(仓, "agentsite"), 仓, os.path.join(仓, "backend")]
    import sdk
    现算 = list(sdk.skills_for("own"))
    if not 现算:
        print(f"  {R}❌ 聊天站现算的放行技能一个都没有 —— 是没算出来,不是「助手没有技能」{D}")
        return 1
    if a.核对技能:
        码, pv = _后台(a, "GET", f"/chat-assistants/by-role/{a.角色}/production")
        if 码 != "200":
            print(f"  {R}❌ 拉不到生产版(HTTP {码 or '连不上'})—— 没核,不是核过了{D}")
            return 1
        记的 = pv.get("技能") or pv.get("skill_snapshot")
        if 记的 is None:
            print(f"  {R}❌ 生产版返回里没有技能清单这一项 —— 没核,不是核过了{D}")
            return 1
        多, 少 = sorted(set(现算) - set(记的)), sorted(set(记的) - set(现算))
        print(f"▸ 「{a.角色}」技能清单:聊天站现算 {len(现算)} 个 · 后台生产版 v{pv.get('版本号')} 记着 {len(记的)} 个")
        if 多 or 少:
            print(f"  {R}❌ 对不上 —— 聊天站有而后台没记:{多 or '无'};后台记着而聊天站不放行:{少 or '无'}{D}")
            print("     路由点名「后台没记」的那几个会被拦下;修法:--只同步技能 → 出版本 → 上生产")
            return 1
        print(f"  {G}✅ 一致{D}")
        return 0
    码, l = _后台(a, "GET", "/chat-assistants")
    助手 = next((x for x in (l.get("items") or []) if x.get("角色键") == a.角色), None)
    if 码 != "200" or not 助手:
        print(f"  {R}❌ 找不到「{a.角色}」的聊天助手(HTTP {码 or '连不上'}){D}")
        return 1
    码, d = _后台(a, "POST", f"/chat-assistants/{助手['id']}/skills-sync", {"技能": 现算})
    if 码 != "200":
        print(f"  {R}❌ 后台拒了(HTTP {码 or '连不上'}):{str(d)[:600]}{D}")
        return 1
    print(f"  {G}✅ {'草稿技能清单已换' if d.get('动了吗') else '和草稿一样,没动'}:{len(d['技能'])} 个"
          f"{' · 多了 ' + str(d.get('多了')) if d.get('多了') else ''}{' · 少了 ' + str(d.get('少了')) if d.get('少了') else ''}{D}")
    print(f"  ⚠️ {d.get('note')}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--角色", default="task")
    ap.add_argument("--项目", default="project_lanxiu")
    ap.add_argument("--基址", default="http://127.0.0.1:8801")
    ap.add_argument("--谁", default="U001")
    ap.add_argument("--看", action="store_true", help="只打印快照,不推")
    ap.add_argument("--只同步技能", action="store_true",
                    help="只把聊天站现算的放行技能推给后台草稿(别的配置不碰);导入会整份换草稿,丢掉挑好的术语 / 意图 / 路由")
    ap.add_argument("--核对技能", action="store_true",
                    help="只比:后台生产版记的技能清单 vs 聊天站现算的放行技能,对不上退 1(不改任何东西)")
    a = ap.parse_args()
    if a.只同步技能 or a.核对技能:
        return 技能那一支(a)
    s = 快照(a.角色)
    print(f"▸ 聊天站「{a.角色}」:工具 {len(s['工具'])} 个(写 {sum(t['写'] for t in s['工具'])})· "
          f"规矩池 {len(s['规矩池'])} 条、装上 {len(s['装上的规矩'])} 条 · 提示词 {len(s['提示词全文'])} 字 · "
          f"默认模型 {s['模型']} · 放行技能 {len(s['技能'])} 个")
    if a.看:
        print(json.dumps(s, ensure_ascii=False, indent=1)[:3000])
        return 0
    r = subprocess.run(["curl", "-sS", "-m", "30", "-w", "\n%{http_code}", "-X", "POST",
                        f"{a.基址}/api/v1/projects/{a.项目}/chat-assistants/import",
                        "-H", f"X-Dev-User: {a.谁}", "-H", "content-type: application/json",
                        "--data-binary", "@-"],
                       input=json.dumps(s, ensure_ascii=False), capture_output=True, text=True)
    体, _, 码 = r.stdout.rpartition("\n")
    if 码 not in ("200", "201"):
        print(f"  {R}❌ 后台拒了(HTTP {码 or '连不上'}):{(体 or r.stderr)[:800]}{D}")
        return 1
    d = json.loads(体)
    print(f"  {G}✅ {d['版本']} · {'新出了一版' if d['动了吗'] else '内容没变,什么都没动'}"
          f"{' · ' + d['草稿'] if d.get('草稿') else ''}{D}")
    print(f"  ⚠️ {d['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
