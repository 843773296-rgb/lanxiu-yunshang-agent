# -*- coding: utf-8 -*-
"""难题分流 · 默认 Haiku 答,出问题才换 Opus 重答一次(用户 10-25 拍)。真调 agentsite/model_route 的纯函数。
不按事情类型分(用户 10-25:「先不做意图分类,所有意图分类交给 harness 统一调配」)。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model_route as M

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, 数 = [], [0]

咬合 = [
    ("手选了模型也照样分流", "页面手选过模型 → 不分流(手选的优先)"),
    ("环境故障也升级", "环境故障(锁库 / 连不上)→ 不升级,换模型救不了"),
    ("工具报错后自己调成功了也升级", "报错后同一个工具又调成功了(10-25 实测那一轮的样子)→ 不升级"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def main():
    print("难题分流 · 默认 Haiku、出问题换 Opus 重答一次")
    默 = "claude:claude-haiku-5-5"
    ck("用默认模型、没手选 → 分流", M.分流开着吗(默, False, 默) is True)
    ck("页面手选过模型 → 不分流(手选的优先)", M.分流开着吗(默, True, 默) is False)
    ck("用的不是默认(老会话存着 Opus 之类)→ 不分流", M.分流开着吗("claude:claude-sonnet-5-5", False, 默) is False)
    ck("默认本身就是 Opus → 没什么可升的,不分流", M.分流开着吗(M.升级到, False, M.升级到) is False)

    通过 = {"交付检查": {"状态": "通过"}, "工具失败数": 0, "环境故障": []}
    ck("答完、检查通过、没报错 → 不升级", M.该升级吗(通过) == (False, None), M.该升级吗(通过))
    ck("修正后通过 → 不升级(那是正常交付)", M.该升级吗({**通过, "交付检查": {"状态": "修正后通过"}})[0] is False)
    for 态 in ("未通过", "不完整"):
        升, 因 = M.该升级吗({**通过, "交付检查": {"状态": 态}})
        ck(f"交付前检查「{态}」→ 升级,理由写明", 升 and 态 in (因 or ""), 因)
    # 10-25 实测那一轮:先猜参数名被拒三次,取了说明之后三个都调成功了,答案是对的
    实测 = {**通过, "工具失败": ["mcp__knowledge__kb_combo", "mcp__knowledge__kb_lookup", "mcp__knowledge__kb_lookup"],
            "工具成功": ["ToolSearch", "mcp__knowledge__kb_combo", "mcp__knowledge__kb_lookup", "mcp__knowledge__kb_lookup"]}
    ck("报错后同一个工具又调成功了(10-25 实测那一轮的样子)→ 不升级", M.该升级吗(实测) == (False, None), M.该升级吗(实测))
    升, 因 = M.该升级吗({**通过, "工具失败": ["mcp__ops__order_get", "mcp__ops__order_get"], "工具成功": ["mcp__knowledge__kb_lookup"]})
    ck("报错的工具到最后都没调成功 → 升级,理由点名是哪个工具", 升 and "order_get" in (因 or ""), 因)
    ck("没纠正的报错按工具去重(报两次只点名一次)",
       M.没纠正的报错(["a__x", "a__x", "a__y"], ["a__y"]) == ["x"], M.没纠正的报错(["a__x", "a__x", "a__y"], ["a__y"]))
    升, 因 = M.该升级吗(None, 异常="TimeoutError: 卡住")
    ck("第一遍跑崩了 → 升级", 升 and "出错" in (因 or ""), 因)
    ck("环境故障(锁库 / 连不上)→ 不升级,换模型救不了",
       M.该升级吗({**通过, "交付检查": {"状态": "不完整"}, "环境故障": [{"tool": "kb_size"}]})[0] is False)
    ck("撞了花费上限 → 不升级,再跑只会更贵", M.该升级吗({**通过, "交付检查": {"状态": "不完整"}, "budget_hit": True})[0] is False)

    app = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    sdk = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
    ck("接线:/run 按 model_route 判分流和升级、只升级一次;sdk 回传报错和调成功的工具",
       "_mr.分流开着吗(" in app and app.count("_mr.该升级吗(") == 1 and "工具成功=[c.get(\"tool\")" in sdk
       and "fork_session=bool(分叉 and resume)" in sdk)
    print()
    if 坏:
        print(f"{R}❌ 难题分流 {len(坏)} 条不过(验了 {数[0]} 条){D}")
        return 1
    print(f"{G}✅ 难题分流:手选优先、出问题(没纠正过来)才换 Opus 一次、换模型救不了的不升(验了 {数[0]} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
