# -*- coding: utf-8 -*-
"""写工具那几道闸的逐例测试。

抄的是 Accio 的一条**纪律**,不是代码:它 28 个 Hook 源码 20102 行,
对应 28 个测试文件 22805 行 —— **测试比实现还多**。
一个「拦截层」写到这个份上,说明他们吃过亏:
**拦错了和不拦,后果都不可见** —— 该拦没拦,库里多一条错数据,看起来正常;
不该拦却拦了,用户以为是模型不听话,而实际是闸判错了。

这里逐例标真值。判据贴着「什么才算对」,不贴着「我以为它会怎么写」。
"""
# ── 咬合记录 ────────────────────────────────────────────────────────────
# 每条都**真把 `agentsite/guards.py` 的判定改坏跑过一次**,确认这里会红。
#
# ⚠️ 这个文件 2026-09-16 之前一直没有咬合记录,而它守的是**写工具的闸** ——
# 坏了的表现是「模型可以连着写好几条」,**而库里全是成功记录,看不出是闸没拦**。
#
# 它测的是纯函数(`pre_tool_verdict`),所以改坏的地方和检查之间没有中间层。
# 这也是当初把判定从 async hook 里抽出来的理由:
# **藏在 hook 里的判定只能靠真跑一次模型才验得到,太贵太慢,于是实际上就没人验。**
咬合 = [
    ("把 guards 里「已经成功过一次」那个分支去掉(succeeded 不再拦)",
     "已经成功过一次"),
    ("把「同参数重试」那个分支去掉(same 不再拦)",
     "一模一样的参数再试"),
    ("把重试上限从 3 改成 99(试了三次也不拦)",
     "试了三次都没成"),
    ("把「写之前先读」表里批量分派的前置改回已下架的 dispatch_pool",
     "「写之前先读」点名的工具都在架上"),
    ("让 MCP 服务端忽略 LANXIU_TOOLS(又整包挂上)",
     "服务端只给名单里的工具"),
]

import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guards as g

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad = 0
W, B = "mcp__shop__assign_task", "mcp__shop__assign_batch"
F, DP = "mcp__shop__finish_task", "mcp__shop__dispatch_task"
READ = ["mcp__shop__task_types"]
A1 = {"type": "日常运维", "assignee": "林岚", "note": "x", "end": "2026-12-31 18:00"}
A2 = {"type": "日常运维", "assignee": "周叙", "note": "y", "end": "2026-12-31 18:00"}


def att(tool, args, ok=None):
    return dict(tool=tool, key=g._arg_key(tool, args), ok=ok)


def ck(title, verdict, want_block, expect_word=None):
    """want_block=True 表示这一次**应该被拦**。expect_word:拦下的理由里该出现的词。"""
    global bad
    blocked = bool(verdict)
    ok = (blocked == want_block)
    if ok and want_block and expect_word:
        ok = expect_word in (verdict or "")
    if not ok: bad += 1
    got = ("拦下" if blocked else "放行")
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {title:44s} {got:4s} 应为 {'拦下' if want_block else '放行'}"
          + (f" · 含「{expect_word}」" if expect_word else ""))
    if not ok and blocked:
        print(f"       实际理由:{(verdict or '')[:70]}")


def main():
    global bad
    print("\n\033[1m▸ 尝试台账 · 「改正重试」和「已经做成」不是一回事\033[0m")
    print("  " + "=" * 78)
    ck("第一次写(已查类型)", g.pre_tool_verdict(W, A1, "派一条", READ, []), False)
    ck("上次被拒,改了参数再来", g.pre_tool_verdict(W, A2, "派一条", READ, [att("assign_task", A1)]), False)
    ck("一模一样的参数再试", g.pre_tool_verdict(W, A1, "派一条", READ, [att("assign_task", A1)]),
       True, "不会有不同结果")
    ck("已经成功过一次", g.pre_tool_verdict(W, A2, "派一条", READ, [att("assign_task", A1, ok=True)]),
       True, "一次只做一件")
    ck("试了三次都没成", g.pre_tool_verdict(W, A2, "派", READ,
       [att("assign_task", {"a": i}) for i in range(3)]), True, "别再猜了")
    ck("换个写工具也算一次", g.pre_tool_verdict(F, {"task_id": "SC1"}, "完成", READ,
       [att("assign_task", A1, ok=True)]), True, "一次只做一件")

    print("\n\033[1m▸ 计划先行 · 复合请求不许一条一条派\033[0m")
    print("  " + "=" * 78)
    for p in ("把这三条都派了", "这几条都派给苏彧", "每天安排一个人盘点", "排下周的班", "批量派一下"):
        ck(f"「{p}」用单条派", g.pre_tool_verdict(W, A1, p, READ, []), True, "assign_batch")
    for p in ("明天让林岚回访 C10001", "给周叙派一条维保", "把 SC7007 改派给林岚"):
        ck(f"「{p}」用单条派", g.pre_tool_verdict(W, A1, p, READ, []), False)
    # **前提要跟着新规矩走。** 加了「排班前先看格子」之后,
    # 这条用例(只测「用批量不该被复合闸拦」)必须带上 week_grid,
    # 否则它测的就变成了另一条规矩 —— 而它会红,红的原因和它想测的东西无关。
    ck("复合请求用批量(已看过格子)",
       g.pre_tool_verdict(B, {"items": []}, "把这三条都派了", ["mcp__shop__week_grid"], []), False)
    # **闸指的那条路必须真的通。**
    # 上一版不管什么动作都让改用 assign_batch,而 assign_batch 是新建任务的,
    # 派不了待分配池里已存在的单 —— 影子埋点抓到:模型被拦之后两条路都没走成,
    # 直接放弃了。拦一个动作的时候,得确认自己指的那条路真的存在、真的能干这件事。
    v = g.pre_tool_verdict(DP, {"task_id": "SC1"}, "把这三条待分配的都派了", READ, [])
    ck("分派类的复合请求指向 dispatch_batch", v, True, "dispatch_batch")
    v = g.pre_tool_verdict(W, A1, "把这三条都派了", READ, [])
    ck("新建类的复合请求指向 assign_batch", v, True, "assign_batch")
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "backend"))
    import api as _api
    for t in ("assign_batch", "dispatch_batch"):
        ck(f"闸指的 {t} 真的存在", None if t in _api.TOOLS else f"{t} 不存在", False,)

    print("\n\033[1m▸ 判据宁可漏,不可宽\033[0m")
    print("  " + "=" * 78)
    # **判宽了天天拦正常的单条派活,人会学会无视这条提示 ——
    #   而被无视的闸和没有闸是一回事。**
    normal = ["帮我派个任务", "让林岚明天去回访", "安排周叙做维保", "派一条上门沟通",
              "给这个客户排个预约", "谁有空接一下这单"]
    over = [p for p in normal if g._looks_compound(p)]
    ck(f"{len(normal)} 句正常单条派活都不误判",
       "误判了:" + str(over) if over else None, False)

    print("\n\033[1m▸ 没查类型不许派\033[0m")
    print("  " + "=" * 78)
    ck("没查 task_types 就派", g.pre_tool_verdict(W, A1, "派一条", [], []), True, "task_types")
    ck("查过了就放行", g.pre_tool_verdict(W, A1, "派一条", READ, []), False)
    ck("完成任务不要求先查", g.pre_tool_verdict(F, {"task_id": "SC1"}, "完成", [], []), False)

    print("\n\033[1m▸ 先看再动:祈使句搬进 hook\033[0m")
    print("  " + "=" * 78)
    # 这两条原来只写在 Skill 正文里。**提示词里的规矩是祈使句,hook 才是强制** ——
    # Accio 的实测结论是这类约束「召回不足」:模型会当成一个大流程顺着执行。
    ck("没看格子就排班", g.pre_tool_verdict(B, {"items": []}, "排下周班", [], []),
       True, "week_grid")
    ck("看过格子再排班", g.pre_tool_verdict(B, {"items": []}, "排下周班",
       ["mcp__shop__week_grid"], []), False)
    ck("没看池子就批量分派", g.pre_tool_verdict("mcp__shop__dispatch_batch", {"items": []},
       "把待分配的都派了", [], []), True, "get_tasks")
    ck("看过池子再分派", g.pre_tool_verdict("mcp__shop__dispatch_batch", {"items": []},
       "把待分配的都派了", ["mcp__shop__get_tasks"], []), False)
    # **单条动作不受这条管** —— 判宽了会天天拦正常的活
    ck("单条派任务不要求先看格子", g.pre_tool_verdict(W, A1, "派一条", READ, []), False)

    print("\n\033[1m▸ 非 MCP 工具一律拦(这条最硬)\033[0m")
    print("  " + "=" * 78)
    for t in ("Bash", "Write", "Read", "Task", "WebFetch"):
        ck(f"{t}", g.pre_tool_verdict(t, {}, "随便", [], []), True)
    ck("读工具不受写闸管", g.pre_tool_verdict("mcp__shop__get_tasks", {}, "把这三条都派了", [],
       [att("assign_task", A1, ok=True)]), False)

    print("\n\033[1m▸ 写工具清单只有一个来源\033[0m")
    print("  " + "=" * 78)
    # 这个病犯过三次:白名单漏工具、边界攻击用旧格式、漏斗清单没跟上。
    # 三次都**不报错**,只是那一处从此把新工具当成不存在。
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "backend"))
    import api as _api, funnel as _fn, inspect as _in
    # ── 「写之前先读」表里点名的工具,必须真的挂在模型能调的架子上 ─────────
    # 09-19 合并工具时 dispatch_pool / member_level / piece_ratios 改了名,前置要求没跟着改,
    # 三个写口从此永远调不成,而这里一直绿 —— 因为以前这里测的也是那几个旧名字。
    架上 = {x["name"] for x in _api.SHOP_SCHEMAS + _api.KB_SCHEMAS + _api.SCHEMAS}
    没在架上 = sorted({n for ns in g.先读.values() for n in ns} - 架上)
    ck("「写之前先读」点名的工具都在架上",
       None if not 没在架上 else f"不在架上:{没在架上}", False,)
    不是写口 = sorted(set(g.先读) - set(_api.WRITE_TOOLS))
    ck("「写之前先读」表的键都是真的写工具",
       None if not 不是写口 else f"不是写工具:{不是写口}", False,)
    # ── 按角色挂工具:每个角色**实际挂上的**正好是它的名单(2026-09-22)──────
    # 原来三个服务不分角色整包挂,名单只进了 allowed_tools(不排他)——模型看得见、调得动别的角色的工具,
    # 每轮还要把全部工具说明带上。这两条守的是「挂上去的」和「名单」是同一个东西,且服务端真的只给名单里的。
    import sdk as _sdk
    差 = []
    for _k in _sdk._ROLE_TOOLS:
        挂 = {f"mcp__{服}__{t}" for 服, cfg in _sdk.mcp_config(None, _k).items()
              for t in cfg["env"].get("LANXIU_TOOLS", "").split(",") if t}
        名单 = {t for t in _sdk._tools_for(_k) if t.startswith("mcp__")}
        if 挂 != 名单: 差.append((_k, sorted(挂 ^ 名单)[:3]))
    ck("每个角色实际挂上的工具 == 它的名单", None if not 差 else f"对不上:{差}", False,)
    _o.environ["LANXIU_TOOLS"] = "get_order"
    try:
        _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "mcp"))
        from protocol import Server as _Srv
        _sv = _Srv("t", "0", [("get_order", "", {"type": "object"}, lambda **a: 1),
                             ("start_cutting", "", {"type": "object"}, lambda **a: 2)])
        _调 = _sv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "start_cutting", "arguments": {}}})
    finally:
        _o.environ.pop("LANXIU_TOOLS", None)
    ck("服务端只给名单里的工具:名单外的列不出、也调不动",
       None if (set(_sv.tools) == {"get_order"} and _调["result"]["isError"]) else f"漏了:{list(_sv.tools)}",
       False,)
    ck("闸的清单来自 api.WRITE_TOOLS",
       None if set(g._write_tools()) == set(_api.WRITE_TOOLS) else "对不上", False,)
    ck("漏斗不再手抄清单",
       None if "WRITE_TOOLS" in _in.getsource(_fn.turn) else "还在手抄", False,)
    src = open(_o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "sdk.py"),
               encoding="utf-8").read()
    miss = [t for t in _api.WRITE_TOOLS if f'"mcp__shop__{t}"' not in src]
    ck("每个写工具都在 sdk 白名单里", str(miss) if miss else None, False,
       "  ← 挂了工具没进白名单,这个坑漏过一次")

    print("\n\033[1m▸ 指纹:参数不同就该是不同的一次\033[0m")
    print("  " + "=" * 78)
    k1, k2 = g._arg_key("assign_task", A1), g._arg_key("assign_task", A2)
    ck("不同参数指纹不同", None if k1 != k2 else "撞了", False)
    k3 = g._arg_key("assign_task", dict(reversed(list(A1.items()))))
    ck("键顺序不影响指纹", None if k1 == k3 else "顺序一变就认不出", False,)

    print("\n\033[1m▸ 凭据类的值:只能是用户说出来的,模型不许自己生成\033[0m")
    print("  " + "=" * 78)
    # 2026-09-24:签收评测抓到模型自己编了一个物流单号(用户只说「帮我转寄」)。
    # 同一个形状扫下来还有两处:**量体的尺寸数值**(编出来的会被拿去裁布)、**返修的预估费用**。
    RM = "mcp__shop__record_measure"
    条件 = dict(inner="薄", shoe="赤足", breath="平静呼气")
    ck("用户报了尺寸 → 放行",
       g.pre_tool_verdict(RM, dict(wearer_id="W1", values={"胸围": 88, "腰围": 72}, **条件),
                          "给 W1 量了胸围 88、腰围 72,薄内搭赤足平静呼气,登记", READ, []), False)
    ck("模型自己编了一个尺寸 → 拦",
       g.pre_tool_verdict(RM, dict(wearer_id="W1", values={"胸围": 88, "腰围": 72}, **条件),
                          "给 W1 量了胸围 88,薄内搭赤足平静呼气,登记", READ, []), True, "没说过")
    ck("小数点写法不同(72.0 对 72)不误拦",
       g.pre_tool_verdict(RM, dict(wearer_id="W1", values={"腰围": 72.0}, **条件),
                          "腰围 72,薄内搭赤足平静呼气", READ, []), False)
    DR = "mcp__shop__decide_repair"
    基 = dict(maintain_id="MT1", liable="顾客", plan="返修", customer_agreed=True,
             agree_note="顾客电话同意 300 元")
    ck("用户报了费用 → 放行",
       g.pre_tool_verdict(DR, dict(基, fee_est=300), "这件判顾客承担,返修,预估 300 元,顾客电话同意 300 元",
                          READ, []), False)
    ck("模型自己估了一个费用 → 拦",
       g.pre_tool_verdict(DR, dict(基, fee_est=500), "这件判顾客承担,返修,顾客电话同意 300 元",
                          READ, []), True, "没说")

    print("\n\033[1m▸ 用件日期按业务上的今天判「在不在将来」\033[0m")
    print("  " + "=" * 78)
    # 09-22:原来按机器的今天判,演示世界的今天(8-31)比机器(9-22)早 —— 9-05 的婚期会被当成过去拦掉
    import datetime as _dt
    from prompts import _TODAY as 业务今天
    后五天 = (_dt.date.fromisoformat(业务今天) + _dt.timedelta(days=5)).isoformat()
    前一天 = (_dt.date.fromisoformat(业务今天) - _dt.timedelta(days=1)).isoformat()
    PF = "mcp__kb__plan_for_event"
    ck(f"业务今天之后 5 天({后五天})的婚期不拦", g.pre_tool_verdict(PF, {"event_date": 后五天, "wearer_id": "W1"},
       "婚礼", READ, []), False)
    ck(f"业务今天前一天({前一天})的婚期拦下", g.pre_tool_verdict(PF, {"event_date": 前一天, "wearer_id": "W1"},
       "婚礼", READ, []), True)

    # ── 转寄的物流单号只能照抄用户的(2026-09-24 评测抓到模型编了一个 SF2321616818)──
    print("\n\033[1m▸ 转寄 · 单号不许编\033[0m")
    print("  " + "=" * 78)
    RP = "mcp__shop__record_pickup"
    寄 = lambda 号: {"order_id": "O1", "action": "取件方式", "mode": "转寄", "tracking_no": 号}
    ck("单号是用户说的 → 放行", g.pre_tool_verdict(RP, 寄("SF1234567890"),
       "顾客来不了,帮我转寄,单号 SF1234567890", READ, []), False)
    ck("单号用户没说过 → 拦下", g.pre_tool_verdict(RP, 寄("SF2321616818"),
       "顾客来不了店里,帮我转寄给她。", READ, []), True, "照抄")
    ck("没给单号 → 拦下", g.pre_tool_verdict(RP, 寄(""), "帮我转寄", READ, []), True, "照抄")
    ck("单号夹了空格、大小写不同 → 放行", g.pre_tool_verdict(RP, 寄("sf 1234 567890"),
       "转寄,单号 SF1234567890", READ, []), False)
    ck("到店取不受这条管", g.pre_tool_verdict(RP, {"order_id": "O1", "action": "取件方式", "mode": "到店取"},
       "顾客到店取", READ, []), False)

    print()
    if bad:
        print(f"{R}❌ 闸有 {bad} 处不符合预期{D}")
        print("   拦错了和不拦,后果都不可见 —— 该拦没拦,库里多一条错数据看起来正常;")
        print("   不该拦却拦了,用户以为是模型不听话,而实际是闸判错了。")
        sys.exit(1)
    print(f"{G}✅ 写工具的闸逐例符合预期{D}")
    print("    「改正参数重试」放行、「一模一样再试」拦下、「已经做成一件」拦下 —— 三种是三件事。")


if __name__ == "__main__":
    main()
