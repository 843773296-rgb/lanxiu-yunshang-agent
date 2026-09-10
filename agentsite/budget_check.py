# -*- coding: utf-8 -*-
"""花费闸的自查:**阈值要够聊几轮,而且撞线时要说人话。**

这个闸出过一次事:上限 $0.60、单轮 SDK 计价 $0.24,聊到第三轮就被掐,
而报错原样甩出 `ResultError: ... exit code 1` —— 用户既不知道是预算,
也不知道该怎么办。**一个说不清自己为什么拦你的闸,和随机失败没区别。**

会再犯的原因很具体:**每加一个工具、每加一条铁律,单轮成本就涨一点**,
而阈值是个常数。涨到某一天,三轮又变成两轮。所以这里把单轮的固定开销
量出来,阈值不够聊 N 轮就报警 —— 让它在变坏的那一刻就红,而不是等用户撞上。
"""
import os, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad = 0

# 实测锚点(2026-09-10,一次「本店顾问任务清单」,单轮 + 一次工具调用):
#   SDK 自报 $0.2426 / 真实 $0.0028。**这是量出来的,不是估的。**
# 单轮成本大头是每轮重发的固定开销:系统提示词 + 工具 schema。
MEASURED_PER_TURN_USD = 0.243
MIN_TURNS = 8          # 至少要够一条会话聊 8 轮 —— 少于这个数,人会频繁莫名被掐


def ck(title, got, want, extra=""):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {title:46s} {str(got):16s} 应为 {want}{extra}")


def main():
    global bad
    import prompts, api
    print("\n\033[1m▸ 每轮要重发多少东西\033[0m")
    print("  " + "=" * 76)
    txt, _ = prompts.assemble("all", {r.needs[0] for _, r in prompts.all_rules() if r.needs})
    sch = json.dumps(api.SHOP_SCHEMAS, ensure_ascii=False)
    tok = (len(txt) + len(sch)) // 2
    print(f"  ·  系统提示词 {len(txt)} 字符 · 工具 schema {len(sch)} 字符 "
          f"→ 每轮固定重发约 {tok} token")
    print(f"  ·  实测单轮 SDK 计价 ${MEASURED_PER_TURN_USD}(真实 $0.0028,差 86 倍)")

    print("\n\033[1m▸ 阈值够聊几轮\033[0m")
    print("  " + "=" * 76)
    os.environ.pop("LANXIU_MAX_USD", None)
    sys.path.insert(0, HERE)
    try:
        import sdk
    except ModuleNotFoundError as e:
        print(f"  ·  跳过(要用 agentsite/.venv 的解释器):{e}")
        return
    for pv in ("claude", "deepseek"):
        cap = sdk._max_usd(pv)
        turns = int(cap / MEASURED_PER_TURN_USD)
        ck(f"{pv} 的上限 ${cap:g} 够聊 {turns} 轮",
           "够" if turns >= MIN_TURNS else f"只够 {turns} 轮", "够",
           f"  ← 至少要 {MIN_TURNS} 轮")

    print("\n\033[1m▸ 撞线时说不说得清\033[0m")
    print("  " + "=" * 76)
    import inspect
    src = inspect.getsource(sdk.run)
    ck("接住了预算异常", "接了" if "maximum budget" in src else "没接", "接了",
       "  ← 不接就冒成 ResultError,用户不知道发生了什么")
    ck("只吞预算这一种异常", "是" if "raise" in src.split("maximum budget")[1][:200] else "全吞了", "是",
       "  ← 全吞的话真故障也会被说成「预算到了」,比原来的报错更难查")
    for word in ("累计", "新建会话", "LANXIU_MAX_USD"):
        ck(f"提示里说了「{word}」", "说了" if word in src else "没说", "说了")

    print()
    if bad:
        print(f"{R}❌ 花费闸 {bad} 处不符合预期{D}")
        print("   每加一个工具、每加一条铁律,单轮成本就涨一点,而阈值是常数 ——")
        print("   涨到某一天,能聊的轮数就悄悄变少了。")
        sys.exit(1)
    print(f"{G}✅ 花费闸设置合理,撞线时说得清{D}")


if __name__ == "__main__":
    main()
