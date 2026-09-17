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


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把 Claude 的花费上限从 $50 压到 $0.6(聊到第三轮就被掐)',
     '订阅内的比按量计费的松'),
]

def ck(title, got, want, extra=""):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {title:46s} {str(got):16s} 应为 {want}{extra}")


def main():
    global bad
    import prompts, api, skills_own
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
    # **松紧方向**:订阅内的该松(闸只防死循环),按量计费的该紧(闸真的在防花钱)。
    # 这两个一开始设反了 —— 按「让阈值贴近计价口径」定,而真正的判据是钱包。
    ck("订阅内的比按量计费的松",
       "是" if sdk._max_usd("claude") > sdk._max_usd("deepseek") else "反了", "是",
       "  ← Claude 边际成本为零,被掐断比多花钱讨厌;DeepSeek 是真金白银")

    print("\n\033[1m▸ 默认不该花钱\033[0m")
    print("  " + "=" * 76)
    # **网站的默认供应商决定了「随手聊一句」花不花钱。**
    # 原来默认 DeepSeek(按量计费),在浏览器里聊一句花一句 ——
    # 默认值设反的代价不是「不好用」,是每次用都在漏钱,而且没人会注意到。
    did = sdk.default_model_id()
    ck("网站默认走订阅内的那个", "是" if did.startswith("claude:") else f"是 {did}", "是",
       "  ← 默认按量计费的话,随手聊一句就花一句")
    ck("默认不是最弱的那档", "不是" if "haiku" not in did else "haiku", "不是",
       "  ← 免费的前提下用最弱的那个,试出来的效果会低估这套东西的上限")
    # **界面说的默认,必须就是不传模型时真正跑的那个。**
    # 这两个原来是两个来源:/models 说 claude:sonnet-5,不传 model 时实际跑 deepseek。
    # 界面说一套实际做一套,而且不报错 —— 你以为在用订阅,其实在按量计费。
    app_src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    ck("不传模型时走 default_model_id",
       "是" if "sdk.default_model_id()" in app_src.split('body.get("model")')[1][:200] else "没有", "是",
       "  ← 不是的话会掉到脚本默认上,和界面显示的不是同一个")

    # 评测那条路**必须仍然听环境变量** —— 默认一改就会悄悄变成
    # 「拿 Claude 的成绩当 DeepSeek 的成绩」
    os.environ["LANXIU_PROVIDER"] = "deepseek"
    ck("评测路径仍听 LANXIU_PROVIDER",
       "听" if sdk.default_model_id().startswith("deepseek:") else "没听", "听",
       "  ← 不听的话,评测会拿 Claude 的成绩当 DeepSeek 的成绩")
    os.environ.pop("LANXIU_PROVIDER", None)

    print("\n\033[1m▸ 技能分档 · 装着 ≠ 每次都上场\033[0m")
    print("  " + "=" * 76)
    # 实测(2026-09-11,同一条用例、同一个模型、同一份技能文件,每条跑三遍):
    #   --set own(3 个)  「6月毕业典礼那天要穿,现在该做多大」 3/3 触发
    #   --set all(239 个)                                   0/3 不触发
    # **唯一的差别是场上有 3 个还是 239 个。** 干扰是实打实的,不是噪声。
    #
    # 上一轮我说「装 236 个误触发 0、触发率没掉」,那个结论是错的 ——
    # 它建立在一次 13/15 的单轮结果上,而**接近满分的结果最容易被当成结论**。
    ck("默认档是 own", sdk.skills_for(None) == sdk.skills_for("own") and "是" or "不是", "是",
       "  ← 默认 all 的话,每次问话都在和 236 个第三方技能竞争")
    ck("认不出的档退回 own", "own" if sdk.skills_for("乱写的") == sdk.skills_for("own") else "退回别处",
       "own", "  ← 退回 all 的话,写错一个参数就悄悄把 236 个放进竞争,而没人会发现")
    ck("own 里只有我们自己的",
       "是" if all(skills_own.is_ours(x) for x in sdk.skills_for("own")) else "混进别人的", "是")
    ck("none 是真的空", str(len(sdk.skills_for("none"))), "0",
       "  ← 评测要有「没有技能时什么样」这个对照")

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
