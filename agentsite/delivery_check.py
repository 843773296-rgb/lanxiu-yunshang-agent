#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每一个候选最终答案都检查,最终交付状态和「曾被打回过」分开 —— 外部审阅 2026-10-03 §4.1。

原来 on_stop 打回一次就置 stopped,第二次答案走空返回:**检查器只被调用一次**,
改过的答案仍不合格也会被交出去;记录里只有「曾被打回」,看不出「最终合格」。

六个场景(审阅 §8.2 那张表里属于这里的):首次通过 · 失败后改对 · 连续两次失败 · 检查器出错 ·
Stop 没查到最终那份(SDK 异常出口)· 没跑完(预算掐断)。外加:体检关着、空答案。
**不调模型**:钩子直接喂假答案,检查器换成可控的假检查。
"""
import asyncio, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "agent")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("打回一次之后不再查(on_stop 开头加回 `if state.get('修正次数'): return {}`)", "失败后改对 → 第二份也查了,最终「修正后通过」"),
    ("改的次数不设上限(`>= 最多修正次数` 改成 `>= 99`)", "连续两次失败 → 第二次不再打回"),
    ("未通过的答案照样交出去(交付处理里不换文本)", "未通过的答案不进正常答案字段"),
    ("没跑完也照常判通过(交付判定里去掉 `跑完了` 那一支)", "没跑完(预算掐断)→ 不完整"),
    ("Stop 只读 transcript,不用入参里的 last_assistant_message", "transcript 里还没有最终答案"),
    ("最终违规退回历次全记录(修正后通过也带着打回)", "修正后通过 → 最终违规为空"),
    ("某套评测判分又读回 guard_violations", "评测判分读的是最终违规"),
]

坏 = 0


def ck(名, ok, n, 说明=""):
    global 坏
    if n == 0:
        print(f"  {R}❌{D} {名} —— **没扫到东西**,不是通过"); 坏 += 1; return
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}(验了 {n} 个){'' if ok else '  ' + 说明}")
    坏 += 0 if ok else 1


def main():
    import guards
    真检查, 真读 = guards.check_answer, guards._last_answer
    次 = {"n": 0}

    def 场景(答案们, 判法):
        """答案们:Stop 依次看到的答案;判法(答案) → 违规列表或抛异常。返回 (每次钩子的返回, state)。"""
        state = {}
        hooks = guards.make_hooks(state)
        stop = hooks["Stop"][0].hooks[0]
        次["n"] = 0
        def 假查(text, calls, prompt="", **_):
            次["n"] += 1
            return 判法(text)
        guards.check_answer = 假查
        回 = []
        for a in 答案们:
            guards._last_answer = lambda p, *_, a=a: a
            回.append(asyncio.run(stop({"transcript_path": "x"}, None, None)))
        return 回, state

    坏答 = lambda t: [{"check": "测", "msg": "测:不合格"}] if "坏" in t else []
    try:
        print("\n\033[1m▸ 钩子:每一份候选答案都查\033[0m")
        回, st = 场景(["好答案"], 坏答)
        交 = guards.交付判定(st, "好答案")
        ck("首次通过 → 不打回,最终「通过」", 回 == [{}] and 交["状态"] == "通过" and 次["n"] == 1, 1, str(交))

        回, st = 场景(["坏答案", "好答案"], 坏答)
        钩子查了 = 次["n"]          # **交付判定之前**数:交付判定漏了会补查,混进来就分不出是钩子查的还是兜底查的
        交 = guards.交付判定(st, "好答案")
        ck("失败后改对 → 第二份也查了,最终「修正后通过」", 回[0].get("decision") == "block" and 回[1] == {}
           and 钩子查了 == 2 and not any("补查" in (a.get("来源") or "") for a in st["答案检查"])
           and 交["状态"] == "修正后通过", 1, f"{回} / {交['状态']} / 钩子查了 {钩子查了} 次")
        ck("失败历史不因修正成功而删", len(st.get("violations") or []) == 1
           and [a["结果"] for a in st["答案检查"]] == ["不通过", "通过"], 1, str(st.get("答案检查")))

        回, st = 场景(["坏答案", "还是坏答案"], 坏答)
        ck("连续两次失败 → 第二次不再打回(不无限循环),两份都查了",
           回[0].get("decision") == "block" and 回[1] == {} and 次["n"] == 2, 1, str(回))
        文, 草, 交 = guards.交付处理(st, "还是坏答案")
        ck("连续两次失败 → 最终「未通过」", 交["状态"] == "未通过", 1, str(交["状态"]))
        ck("未通过的答案不进正常答案字段(换成受控说明,草稿另存)", 文 == guards.未通过时的说明 and 草 == "还是坏答案", 1, 文)

        def 崩(t): raise RuntimeError("检查器坏了")
        回, st = 场景(["答案"], 崩)
        ck("检查器出错 → 「未检查」,不当成通过", guards.交付判定(st, "答案")["状态"] == "未检查", 1)

        print("\n\033[1m▸ 交付判定:Stop 没查到 / 没跑完 / 体检关着 / 空答案\033[0m")
        guards.check_answer = lambda text, calls, prompt="", **_: 坏答(text)
        st = {}
        交 = guards.交付判定(st, "坏的最终答案")
        ck("Stop 没触发到最终那份(SDK 异常出口)→ 交付前补查,照样「未通过」",
           交["状态"] == "未通过" and "补查" in (st["答案检查"][-1].get("来源") or ""), 1, str(交))
        ck("没跑完(预算掐断)→ 不完整", guards.交付判定({}, "好答案", 跑完了=False)["状态"] == "不完整", 1)
        ck("体检关着 → 未检查(不能显示成通过)", guards.交付判定({}, "好答案", 体检开着=False)["状态"] == "未检查", 1)
        ck("空答案 → 未检查", guards.交付判定({}, "  ")["状态"] == "未检查", 1)

        print("\n\033[1m▸ Stop 读到的是真答案(真的 _last_answer,不打桩)\033[0m")
        # 10-04 真服务实测:Stop 触发时最终答案**还没写进 transcript**,只在入参 last_assistant_message 里。
        # 只读文件时 Stop 查的一直是空串(哈希 e3b0c442…),「打回 → 改 → 再查」从没走通。
        # 这里造一份「最后一行停在工具调用」的 transcript —— 就是真服务里那个样子
        import json as _j, tempfile as _tf
        tp = os.path.join(_tf.mkdtemp(), "t.jsonl")
        with open(tp, "w", encoding="utf-8") as f:
            f.write(_j.dumps({"type": "user", "message": {"content": "问"}}, ensure_ascii=False) + "\n")
            f.write(_j.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__kb__kb_combo", "input": {}}]}}, ensure_ascii=False) + "\n")
        guards._last_answer = 真读
        state = {}
        stop = guards.make_hooks(state)["Stop"][0].hooks[0]
        guards.check_answer = lambda text, calls, prompt="", **_: 坏答(text)
        回 = asyncio.run(stop({"transcript_path": tp, "last_assistant_message": "坏答案"}, None, None))
        ck("transcript 里还没有最终答案、入参里有 → Stop 查的是那份答案(该打回就打回)",
           回.get("decision") == "block" and state["答案检查"][0]["哈希"] == guards.答案哈希("坏答案"), 1,
           f"钩子返回 {回};查的哈希 {state.get('答案检查')}")

        print("\n\033[1m▸ 评测按最终交付判分(用户 10-04 拍),打回率另记\033[0m")
        guards.check_answer = 真检查
        st = {"violations": [{"check": "g1", "msg": "旧"}, {"check": "g20", "msg": "协议"}, {"check": "g1", "msg": "新"}]}
        ck("修正后通过 → 最终违规为空(打回过不等于答错)",
           guards.最终违规(st, {"状态": "修正后通过", "尝试": [{"失败项": ["g1"]}, {"失败项": []}]}) == [], 1)
        末 = guards.最终违规(st, {"状态": "未通过", "尝试": [{"失败项": ["g1", "g20"]}, {"失败项": ["g1"]}]})
        ck("未通过 → 只带最后那份没过的规则,同一条取最后一次原话", 末 == [{"check": "g1", "msg": "新"}], 1, str(末))
        # 静态:每套评测判分那一步读的是「最终违规」,guard_violations 只许出现在存档那一栏(guard=…)
        import glob, re as _re
        坏处, 扫 = [], 0
        for f in sorted(glob.glob(os.path.join(ROOT, "agent", "*.py"))):
            if f.endswith(("_judgetest.py", "guard_ab.py")): continue
            for n, l in enumerate(open(f, encoding="utf-8"), 1):
                if 'r.get("最终违规")' in l: 扫 += 1
                if 'r.get("guard_violations")' in l and "guard=" not in l:
                    坏处.append(f"{os.path.basename(f)}:{n}")
        ck("评测判分读的是最终违规(guard_violations 只进存档,不进判分)", not 坏处, 扫, f"还在用历次记录判分:{坏处}")

        print("\n\033[1m▸ sdk.run 收尾用的是这一套\033[0m")
        src = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
        ck("sdk.run 收尾调了交付处理,并把交付检查放进返回(静态落点,行为由上面几条验)",
           "guards.交付处理(state, text" in src and "交付检查=交付" in src
           and "最终违规=guards.最终违规(state, 交付)" in src, 1)
    finally:
        guards.check_answer, guards._last_answer = 真检查, 真读

    print()
    if 坏:
        print(f"{R}❌ 交付检查 {坏} 条不过{D}"); return 1
    print(f"{G}✅ 交付检查全部符合预期{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
