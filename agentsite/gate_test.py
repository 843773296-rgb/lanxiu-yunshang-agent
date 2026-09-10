# -*- coding: utf-8 -*-
"""写工具那几道闸的逐例测试。

抄的是 Accio 的一条**纪律**,不是代码:它 28 个 Hook 源码 20102 行,
对应 28 个测试文件 22805 行 —— **测试比实现还多**。
一个「拦截层」写到这个份上,说明他们吃过亏:
**拦错了和不拦,后果都不可见** —— 该拦没拦,库里多一条错数据,看起来正常;
不该拦却拦了,用户以为是模型不听话,而实际是闸判错了。

这里逐例标真值。判据贴着「什么才算对」,不贴着「我以为它会怎么写」。
"""
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
    ck("复合请求用批量", g.pre_tool_verdict(B, {"items": []}, "把这三条都派了", [], []), False)

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

    print("\n\033[1m▸ 非 MCP 工具一律拦(这条最硬)\033[0m")
    print("  " + "=" * 78)
    for t in ("Bash", "Write", "Read", "Task", "WebFetch"):
        ck(f"{t}", g.pre_tool_verdict(t, {}, "随便", [], []), True)
    ck("读工具不受写闸管", g.pre_tool_verdict("mcp__shop__my_tasks", {}, "把这三条都派了", [],
       [att("assign_task", A1, ok=True)]), False)

    print("\n\033[1m▸ 指纹:参数不同就该是不同的一次\033[0m")
    print("  " + "=" * 78)
    k1, k2 = g._arg_key("assign_task", A1), g._arg_key("assign_task", A2)
    ck("不同参数指纹不同", None if k1 != k2 else "撞了", False)
    k3 = g._arg_key("assign_task", dict(reversed(list(A1.items()))))
    ck("键顺序不影响指纹", None if k1 == k3 else "顺序一变就认不出", False,)

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
