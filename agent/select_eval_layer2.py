#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具选择评测**第二层** —— 「候选集里有」不等于「模型会调」。

## 第一层量完了什么,还剩什么没量

第一层(`select_eval.py`)量的是**筛选器给没给**:必需工具在不在候选集里。
纯集合运算,不花钱,秒级。它说:不筛选和按角色都 21/21,关键词 54%,路由器 87%。

> **但候选集里有那个工具,只说明模型有机会调对,它仍然可能不调。**

这一份量那个「仍然」。而真正要回答的是**答得对不对**,不是调得对不对 ——
一个工具选错了而蒙对答案的回答,在成本上和选对一样贵;
而一个工具都给对了却答错的,筛选器不背这个锅。

## 为什么用 `tool_eval` 那 22 题

两个留出集里**只有它带内容判据**(`must` / `forbid` / 可调用的判据函数),
`tool_routing` 那 11 题只有期望工具。所以能回答「答得对不对」的只有这 22 题。

而且它的判分器(`tool_eval.judge`)是现成的、三轴的(轨迹 / 内容 / 体检)——
**不自己写一套**:两份判分器会在谁都没改它的那天开始给出不同结论。

## 两臂:同提示词,只差工具面

    基线臂   `all` 角色挂的 77 个       —— 现状之一(全能助手)
    筛选臂   路由器给那道题选的那几个    —— 平均 1.4 个

收窄靠 `agent/knobs.py` 的「工具」旋钮(类型「工具子集」),
它守着**只许收窄不许放宽**:白名单外的工具当场抛。

⚠️ **两臂都用 `all` 角色,这是故意的** —— 为了控制变量:同一套提示词、同一个池子,
唯一的差别是工具子集。
代价:`tool_eval` 平时跑的是 `kb`(工艺顾问)角色,所以**这里的基线分数和
它历史上的成绩单不可比**。两臂之间可比,那才是这一份要的。

⚠️ **旋钮只收窄工具定义,不收窄提示词。** 收窄之后提示词里仍带着那些
不在场的工具的规矩。所以这一份量到的「省了多少」是**下限**:
真正的筛选还能省掉对应的那条规矩。

## 这一份花钱

22 题 × 2 臂 = 44 次**完整 agent 跑**(不是单次调用)。
一律用 Claude(业务 09-15 拍板),而且**必须显式指定模型**。
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
sys.path.insert(0, os.path.join(HERE, "..", "agentsite"))

方案号 = "_第二层临时"          # 每道题重写同一个方案文件(单线程,够用)


def 路由器选的():
    """读路由器探针的结果 → {题号: [工具名]}。**核对探针哈希**。"""
    import hashlib
    p = os.path.join(HERE, "..", ".feynman", "router-probe.json")
    if not os.path.exists(p):
        print("❌ 没有路由器探针结果。先跑 agent/router_probe.py"); sys.exit(1)
    d = json.load(open(p, encoding="utf-8"))
    当前 = "router_probe@" + hashlib.sha256(
        open(os.path.join(HERE, "router_probe.py"), encoding="utf-8")
        .read().encode()).hexdigest()[:12]
    if d.get("探针版本") != 当前:
        print(f"❌ **探针对不上,不跑。**\n     结果里记的 {d.get('探针版本')}\n"
              f"     现在的     {当前}\n"
              f"   路由器的选择要和产生它的那一版探针对上 —— "
              f"否则这一轮量的是「上一版路由器选的工具」,"
              f"而它在成绩单上和刚跑的长得一模一样。")
        sys.exit(1)
    return {x["题"]: x["给的"] for x in d["配置"]["开"]
            if not x.get("挂了") and x["题"].startswith("T")}


def 写方案(工具们):
    """把工具子集写进旋钮方案文件。`None` = 删掉方案(= 不收窄)。"""
    import knobs
    os.makedirs(knobs.目录, exist_ok=True)
    f = os.path.join(knobs.目录, f"{方案号}.json")
    if 工具们 is None:
        if os.path.exists(f): os.remove(f)
        return
    json.dump({"旋钮": {"工具": list(工具们)},
               "_这是什么": "select_eval_layer2 每道题重写的临时方案,不是人配的"},
              open(f, "w", encoding="utf-8"), ensure_ascii=False)


def 跑一臂(名, 题们, 模型, 选的=None, 角色="all"):
    """`选的=None` → 基线臂(不收窄)。否则按题收窄。"""
    import asyncio
    import sdk
    import importlib.util
    _s = importlib.util.spec_from_file_location(
        "agent_tool_eval", os.path.join(HERE, "tool_eval.py"))
    TE = importlib.util.module_from_spec(_s); _s.loader.exec_module(TE)

    行 = []
    print(f"\n【{名}】")
    for cid, q, need, must, forbid in 题们:
        if 选的 is not None:
            子 = 选的.get(cid) or []
            if not 子:
                # ⚠️ **不静默退回全量。** 路由器一个都没给的题,
                # 真实情况下走的是「无结果回退」那条路,不是「给全部」。
                print(f"  {cid:5s} ⏭  路由器一个工具都没给 —— **不退回全量**,这题记成「筛选给不出」")
                行.append(dict(题=cid, 过=False, 为什么=["筛选给不出:路由器一个工具都没给"],
                              跳过=True)); continue
            写方案(子)
            os.environ["LANXIU_PROMPT_CANDIDATE"] = 方案号
        else:
            写方案(None)
            os.environ.pop("LANXIU_PROMPT_CANDIDATE", None)
        t0 = time.time()
        try:
            r = asyncio.run(sdk.run(角色, q, max_turns=14, model_name=模型))
        except Exception as e:
            print(f"  {cid:5s} ❌ 跑挂了:{type(e).__name__}: {str(e)[:60]}")
            行.append(dict(题=cid, 过=False, 为什么=[f"跑挂了:{type(e).__name__}"],
                          挂了=True)); continue
        names = [t["tool"] for t in r["trajectory"]]
        ok, why = TE.judge(cid, r["text"], names, r.get("guard_violations"))
        行.append(dict(题=cid, 过=ok, 为什么=why,
                      调了=",".join(n.split("__")[-1] for n in names),
                      # ⚠️ **存答案原文。** `tool_eval` 的文件头写着这条规矩,
                      # 而我写这一份时抄了它的跑法、**没抄这条规矩**:
                      # > 不存的话,失败了只能重跑才知道它到底说了什么 ——
                      # > 而重跑要花钱,还不一定复现。
                      # 代价当天就付了:改 T04/T07 的判据时想拿真实说法验,
                      # 而上一轮的原文**一个字都没留**。
                      # > 一份只记「过没过」的评测结果,和一份记了原文的,
                      # > 在成绩单上长得一模一样 —— 而诊断只能靠后者。
                      原文=r.get("text") or "",
                      成本=r.get("cost_usd") or 0, ms=int((time.time()-t0)*1000),
                      轮=r.get("answer_turns"), usage=r.get("usage") or {}))
        print(f"  {cid:5s} {'✅' if ok else '❌'} {len(names)}调 "
              f"{int((time.time()-t0)*1000):5d}ms ${r.get('cost_usd') or 0:.4f}"
              f"  {'' if ok else why[0][:60]}")
    写方案(None)
    os.environ.pop("LANXIU_PROMPT_CANDIDATE", None)
    return 行


def 热一次(模型, 角色="all"):
    """先空跑一次把提示词缓存焐热 —— **不计入任何成绩**。

    ## 为什么必须有这一步

    试水时撞到:基线臂第一题 `cache_creation_input_tokens` = **140598**
    (缓存写比读贵一个量级),而它之后每一题都是读缓存。
    于是基线 T01 花 $0.1919、T02 花 $0.0362 —— **同一臂同一套工具,差 5 倍**。

    而筛选臂跑在基线之后,缓存已经热了。那一轮报出「省 71%」——

    > **跑在后面的那一臂,天生占便宜。**
    > 而「筛选省了钱」和「它跑在第二位」**在成本数字上长得一模一样**。

    去掉第一题重算:基线 $0.0362 vs 筛选 $0.0346 —— **只省 4%**,不是 71%。

    所以:① 开跑前焐一次 ② 两臂**交错**跑(不是跑完一臂再跑另一臂)
    ③ 汇总**同时报「含第一题」和「去掉第一题」**两个数。
    """
    import asyncio
    import sdk
    try:
        asyncio.run(sdk.run(角色, "你好", max_turns=1, model_name=模型))
        print("  (已焐热提示词缓存 —— 这一次不计成绩)")
    except Exception as e:
        print(f"  ⚠️ 焐热那一次挂了({type(e).__name__})—— "
              f"**第一题的成本会偏高**,汇总里「去掉第一题」那一列才可比")


def 汇总(名, 行):
    好 = [x for x in 行 if not x.get("挂了")]
    过 = sum(1 for x in 好 if x["过"])
    钱 = [x.get("成本") or 0 for x in 好 if not x.get("跳过")]
    跳 = sum(1 for x in 好 if x.get("跳过"))
    # ⚠️ **同时报「去掉第一题」** —— 第一题可能在写缓存(贵一个量级),
    # 而那一笔跟筛选有没有用毫无关系
    钱2 = 钱[1:] if len(钱) > 1 else 钱
    return dict(臂=名, 过=过, 共=len(好), 跳过=跳,
                单条成本=(sum(钱)/len(钱) if 钱 else None),
                去掉第一题单条=(sum(钱2)/len(钱2) if 钱2 else None),
                总成本=sum(钱),
                调用数=[len((x.get("调了") or "").split(",")) if x.get("调了") else 0
                      for x in 好])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--模型", required=True,
                    help="**必填** —— 不指定时默认取决于用哪种凭证,两张表不可比")
    ap.add_argument("--只跑", type=int, default=0, help="只跑前 N 题(试水)")
    ap.add_argument("--臂", choices=("两个", "基线", "筛选"), default="两个")
    a = ap.parse_args()
    os.environ.setdefault("LANXIU_PROVIDER", "claude")

    import importlib.util
    _s = importlib.util.spec_from_file_location(
        "agent_tool_eval", os.path.join(HERE, "tool_eval.py"))
    TE = importlib.util.module_from_spec(_s); _s.loader.exec_module(TE)
    题们 = [c for c in TE.CASES]
    if a.只跑: 题们 = 题们[:a.只跑]
    选 = 路由器选的()
    少 = [c[0] for c in 题们 if c[0] not in 选]
    if 少:
        print(f"❌ 这几题路由器探针里没有:{少} —— 先把探针跑全(agent/router_probe.py)")
        sys.exit(1)

    print(f"工具选择评测 · 第二层(真跑模型,比答对数和成本)")
    print(f"  模型 {a.模型} · {len(题们)} 题 · 判分器 tool_eval.judge(三轴)")
    print(f"  ⚠️ 两臂都用 `all` 角色(控制变量)—— **和 tool_eval 历史成绩单不可比**,"
          f"两臂之间可比")
    print("=" * 96)

    热一次(a.模型)

    # ── 跑两轮(接 `agent/rounds.py`)────────────────────────────────────
    #
    # ⚠️ **调模型的评测只跑一轮,那个数是一次抽样不是结论。**
    # 这一份今天就撞过一次活的:试水时「省 71%」,交错 + 焐热之后变成 **12%** ——
    # 同一份代码,跑法不同,差 6 倍。
    # 那次救我的是「缓存冷热」这个具体怀疑,而**跑两轮是不需要怀疑就能发现它的办法**:
    # 两轮差得离谱,你自然会去查。
    #
    # 这个项目记着:V1 和 V3 连跑两轮各掉一题,**而且掉的不是同一题** ——
    # 单轮那张表写的 6/6/6 读起来像「三代持平」,而那是三次抛硬币都正面。
    #
    # ⚠️ **一轮 = 两臂都跑完。** 只跑一臂不构成一轮:这一份要的是「两臂的差」,
    # 而差值的抖动比任何一臂自己的抖动都重要。
    结果 = {}

    def 跑一轮():
        基, 筛 = [], []
        if a.臂 == "两个":
            # **交错跑**:一题基线、一题筛选,而不是跑完一臂再跑另一臂。
            # 顺着跑的话第二臂一路吃热缓存 —— 那笔便宜跟筛选无关。
            for c in 题们:
                基 += 跑一臂("基线", [c], a.模型)
                筛 += 跑一臂("筛选", [c], a.模型, 选的=选)
        elif a.臂 == "基线":
            基 = 跑一臂("基线:全量 77 个", 题们, a.模型)
        else:
            筛 = 跑一臂("筛选:路由器选的", 题们, a.模型, 选的=选)
        结果["基线:全量 77 个"] = 基
        结果["筛选:路由器选的(均 1.4 个)"] = 筛
        # 交给 rounds 的是**两臂合起来**的行,每行带上是哪一臂 ——
        # 这样「某一题在某一臂上翻面」才看得出来
        return ([dict(x, id=f"基线·{x['题']}", passed=x["过"],
                      why=x.get("为什么")) for x in 基]
                + [dict(x, id=f"筛选·{x['题']}", passed=x["过"],
                        why=x.get("为什么")) for x in 筛])

    import rounds
    import evalrec

    def 写(路径, 行们):
        """**唯一一处写结果文件的地方。**

        ⚠️ 第一版这里只写「逐轮的行」,而主程序末尾**又写了一次同一个路径**
        (汇总 + 逐题)—— 于是 rounds 存的逐轮数据被覆盖掉了,
        而文件看起来完全正常(它有 模型/汇总/逐题 三个键)。

        > **两处写同一个文件,后写的那次悄悄吃掉前一次** ——
        > 而一个少了逐轮数据的结果文件,和一个完整的,在目录里长得一模一样。

        ⚠️⚠️ 这个 bug 我**一小时前刚在 `router_probe.py` 里修过一次**,
        然后在这个文件里又写了一遍。当时只问了「这个文件里还有没有」,
        **没问「我还有哪几个脚本是这个形状的」** —— 那一问才是规则修复。
        (查过了:`chat_eval` / `tool_eval` 也有两处 `json.dump`,
         但它们写的是**不同文件**(旋钮方案 ≠ 结果),不是同病。)

        只跑了一部分题时**不写** —— 由 rounds 判;这里只负责盖章 + 写全。
        """
        _章 = evalrec.盖章()
        json.dump({"模型": a.模型,
                   "逐轮": [dict(r, **_章) for r in 行们],
                   "汇总": [汇总(k, v) for k, v in 结果.items()],
                   "逐题": 结果},
                  open(路径, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    最后, 多轮 = rounds.跑并收尾(
        跑一轮, 名="工具筛选第二层", 键="id", 写=写,
        结果文件=os.path.join(HERE, "..", ".feynman", "select-eval-第二层.json"),
        全集数=len(TE.CASES) * (2 if a.臂 == "两个" else 1),
        本轮数=len(题们) * (2 if a.臂 == "两个" else 1))

    print("\n" + "=" * 96)
    汇 = [汇总(k, v) for k, v in 结果.items()]
    print(f"{'臂':30s} {'答对':>10s} {'单条成本':>11s} "
          f"{'去掉第一题':>11s} {'筛选给不出':>10s}")
    print("-" * 80)
    for s in 汇:
        分 = f"{s['过']}/{s['共']}"
        单 = ("$%.4f" % s["单条成本"]) if s["单条成本"] else "—"
        总 = "$%.4f" % s["总成本"]
        单2 = ("$%.4f" % s["去掉第一题单条"]) if s["去掉第一题单条"] else "—"
        print(f"{s['臂']:30s} {分:>10s} {单:>11s} {单2:>11s} {s['跳过']:>10d}")
    print("-" * 80)
    if len(汇) == 2:
        a0, a1 = 汇
        print(f"\n  答对数:{a0['过']} → {a1['过']}(差 {a1['过']-a0['过']:+d})")
        for 标, 键 in (("含第一题", "单条成本"), ("**去掉第一题**", "去掉第一题单条")):
            if a0[键] and a1[键]:
                省 = 1 - a1[键]/a0[键]
                print(f"  单条成本({标}):${a0[键]:.4f} → ${a1[键]:.4f}"
                      f"(省 {100*省:.0f}%)")
        print(f"  ⚠️ **以「去掉第一题」那一行为准** —— 第一题可能在写缓存"
              f"(贵一个量级),而那一笔跟筛选有没有用毫无关系。")
        print(f"\n  ⚠️ **两个数一起读。** 成本降了而答对数掉了,那不叫改进 ——")
        print(f"     而这正是筛选最容易出假收益的地方:少挂工具成本一定降。")
        print(f"  ⚠️ 这个「省」是**下限**:旋钮只收窄工具定义,"
              f"不收窄提示词里对应的那条规矩。")
    # ⚠️ **这里不再写文件** —— 上面 `写()` 已经写全了(逐轮 + 汇总 + 逐题)。
    # 第一版在这儿又写一次同一个路径,把 rounds 存的逐轮数据覆盖掉了。
    out = os.path.join(HERE, "..", ".feynman", "select-eval-第二层.json")
    print(f"\n明细 → {os.path.relpath(out, os.path.join(HERE, '..'))}"
          f"(**由 `写()` 一次写全,这儿不重复写**)")
