# -*- coding: utf-8 -*-
"""聊天接管的技能登记 · 两边一致(2026-10-24,用户拍「默认关;打开时聊天站改走工作流」)。

管理后台 `workflows_api.可接管技能` 登记「哪些技能能被工作流接管」,澜绣聊天站 `agentsite/skills_own.OURS`
是自有技能的真名单。两边对不上的后果:
  · 管理后台登记了一个聊天站没有的技能 → 拨开了接管开关,聊天站永远碰不到这件事,**看着接管了,其实什么都没变**
  · 聊天站新加了自有技能而管理后台没登记 → 这件事想接管也选不到
两种都不报错,所以要一条判据盯着。只读源码,不 import(管理后台那边要 sqlalchemy)。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("管理后台登记了一个聊天站没有的技能", "管理后台登记的可接管技能,聊天站都真有"),
]


def _读字面量(路径, 名):
    树 = ast.parse(open(路径, encoding="utf-8").read())
    for 节 in ast.walk(树):
        if isinstance(节, ast.Assign) and any(getattr(t, "id", None) == 名 for t in 节.targets):
            return ast.literal_eval(节.value)
    raise SystemExit(f"{路径} 里找不到 {名} 的字面量 —— 这条判据读不到东西,不算通过")


def main():
    print("聊天接管的技能登记 · 管理后台和聊天站两边一致")
    后台 = set(_读字面量(os.path.join(ROOT, "管理后台", "services", "api", "app", "workflows_api.py"), "可接管技能"))
    自有 = set(_读字面量(os.path.join(ROOT, "agentsite", "skills_own.py"), "OURS"))
    坏 = 0
    多 = sorted(后台 - 自有)
    少 = sorted(自有 - 后台)
    print(f"  管理后台登记 {len(后台)} 个 · 聊天站自有 {len(自有)} 个")
    if not 后台 or not 自有:
        print(f"  {R}❌ 有一边是空的 —— 没东西可比,不算通过{D}"); return 1
    print(f"  {R + '❌' + D if 多 else G + '✅' + D} 管理后台登记的可接管技能,聊天站都真有"
          + (f"  多出来的:{多}" if 多 else ""))
    print(f"  {R + '❌' + D if 少 else G + '✅' + D} 聊天站的自有技能,管理后台都登记了"
          + (f"  漏登记:{少}" if 少 else ""))
    坏 = len(多) + len(少)
    print()
    if 坏:
        print(f"{R}❌ 两边对不上 {坏} 个{D}")
        return 1
    print(f"{G}✅ 两边一致({len(后台)} 个技能都能被接管、都真存在){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
