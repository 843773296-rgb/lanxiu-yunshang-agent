#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单条试运行 —— **挑一道题,拿默认跑一遍、拿方案跑一遍,左右摆着看。**

## 为什么要有它

改完旋钮只能跑整套题的话,一次要几分钟。而**调优的手感来自快速来回**:
拧一下 → 看这一题变没变 → 再拧。几分钟一轮,你没法真的在调,只能在等。

## ⚠️ 它能回答什么,不能回答什么

**能**:这一改让回答**长什么样**不一样了 —— 少查了一个工具、话说得更短、
       原来问的那句话不问了。这些是**看得见的差异**,看一眼就知道。

**不能**:「哪个更好」。一条题各跑一次,两边的差异里**混着模型自己的抖动** ——
       这个项目实测过:同一个提交、同一个模型、同一批题连跑两轮,
       V1 和 V3 各掉一题,而且掉的不是同一题。**那是三次抛硬币。**

所以这里的产物一律叫「差异」,不叫「分数」,也不出结论。
要下结论走 `跑验证集` + `记一次` + 并排比分那条路 —— 那边有轮间抖动兜底。

> **这个项目为「拿单轮结果下结论」栽过三次**(评测跑的模型和产品不一致、
> 单跑一次断定描述改坏了、13/15 就说装 236 个技能没影响)。
> 试运行做得越顺手,越要把这句话贴在结果旁边。

## 两条实现上的纪律

① **题目现挑,不写死。** id 会被一次合理的数据变更打断,日期会被时间打断。
② **两边跑同一道题的同一份夹具。** 挑一次,两边共用 —— 分别挑会挑到不同的单,
   而那样跑出来的差异里还混着「两张单本来就不一样」。
"""
import os, sys, json, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite")]

# 套件表:共享 `挑()/题(x)` 那个形状的几套。**不在这儿抄题面** —— 现调现取。
套表 = [
    dict(键="workshop", 名="自有工坊报工", 模块="workshop_eval"),
    dict(键="factory",  名="工厂回传",     模块="factory_eval"),
    dict(键="measure",  名="量体录入",     模块="measure_eval"),
]
_按键 = {s["键"]: s for s in 套表}


def _取模块(套):
    if 套 not in _按键:
        raise ValueError(f"没有这一套:{套} —— 现有 {list(_按键)}")
    return __import__(_按键[套]["模块"])


def _摘(x):
    """夹具摘要:订单给单号,人给「工号 姓名」。

    ⚠️ **页面上一定要看得见这一轮挑到的是哪张单、哪个人。**
    夹具是现挑的(不许写死),那就意味着两次试跑可能挑到不同的单 ——
    看不见的话,你会把「换了一张单」当成「旋钮起了作用」。
    """
    出 = {}
    for k, v in (x or {}).items():
        if isinstance(v, dict):
            出[k] = v.get("id") or (f"{v.get('no','')} {v.get('name','')}".strip() or str(v)[:40])
        else:
            出[k] = v
    return 出


def 列题(套):
    """现挑一份夹具,列出这一套现在有哪几道题。**每次调都重挑** —— 夹具不许写死。"""
    M = _取模块(套)
    x = M.挑()
    if not x:
        return dict(题=[], 夹具=None,
                    error="挑不到夹具 —— **挑不到就不跑**(硬造一份出来,跑的就不是真数据了)")
    题 = [dict(id=c["id"], kind=c["kind"], q=c["q"], 期望=c.get("期望", ""),
               身份=c.get("身份", ""), role=c.get("role", ""))
          for c in M.题(x)]
    # 夹具的样子也回给页面:**你得看得见这一轮挑到的是哪张单**,
    # 否则两次试跑挑到不同的单,而你以为是旋钮起了作用。
    return dict(题=题, 夹具=_摘(x))


def _跑一边(M, c, 方案号):
    """跑一边(默认 or 方案),跑完把库还原。返回这一边的全部可看的东西。"""
    import asyncio, sdk
    环原 = os.environ.get("LANXIU_PROMPT_CANDIDATE")
    if 方案号: os.environ["LANXIU_PROMPT_CANDIDATE"] = 方案号
    else: os.environ.pop("LANXIU_PROMPT_CANDIDATE", None)
    前 = M.拍() if hasattr(M, "拍") else None
    t0 = time.time()
    try:
        r = asyncio.run(sdk.run(c["role"], c["q"], max_turns=10, me=c["me"]))
        text = r["text"]
        轨 = [dict(工具=t["tool"], 入参=t.get("input"), 回=str(t.get("result"))[:400])
              for t in r["trajectory"]]
        用量 = dict(调用=r.get("calls"), 成本=r.get("cost_usd"), 模型=r.get("model"))
        挂 = None
    except Exception as e:
        text, 轨, 用量, 挂 = "", [], {}, f"{type(e).__name__}: {e}"
    秒 = round(time.time() - t0, 1)
    # ── 还原,并且**验还原干净了** ────────────────────────────────
    # 评测写真库不还原这件事栽过一次:两轮挑到不同的单,而报告看起来正常。
    还原话 = ""
    if 前 is not None:
        M.还原(前)
        坏 = M.还原干净了吗(前) if hasattr(M, "还原干净了吗") else None
        还原话 = f"⚠️ **还原没干净**:{坏}" if 坏 else "库已还原到跑之前的样子"
    # 判据照样跑一遍 —— 但它是**这一次**的结果,不是分数
    why = []
    if not 挂:
        try: why = [w for j in c["judge"] for w in j(text, [t["工具"] for t in 轨], None)]
        except Exception as e: why = [f"(判据自己出错了:{type(e).__name__}: {e})"]
    if 环原 is None: os.environ.pop("LANXIU_PROMPT_CANDIDATE", None)
    else: os.environ["LANXIU_PROMPT_CANDIDATE"] = 环原
    return dict(回答=text, 轨迹=轨, 用量=用量, 秒=秒, 挂=挂,
                这次过了=(not why and not 挂), 判据说=why, 还原=还原话)


def 试跑(套, 题号, 方案号):
    """同一道题,默认跑一遍、方案跑一遍。**两边用同一份夹具。**"""
    M = _取模块(套)
    x = M.挑()
    if not x: return dict(error="挑不到夹具 —— 挑不到就不跑")
    CASES = M.题(x)
    c = next((y for y in CASES if y["id"] == 题号), None)
    if not c: return dict(error=f"这一套里没有 {题号} —— 现有 {[y['id'] for y in CASES]}")

    import knobs
    try: 旋, 松, 旋话 = knobs.校验(knobs.读(方案号))
    except Exception as e: return dict(error=f"方案的旋钮不合法:{e}")

    左 = _跑一边(M, c, None)          # 默认
    右 = _跑一边(M, c, 方案号)        # 方案

    # ── 差异:只报**看得见的**,不报「谁更好」 ──────────────────
    左工 = [t["工具"] for t in 左["轨迹"]]
    右工 = [t["工具"] for t in 右["轨迹"]]
    差 = []
    if 左工 != 右工:
        少 = [t for t in 左工 if t not in 右工]; 多 = [t for t in 右工 if t not in 左工]
        差.append("查的工具不一样了" + (f"(少查:{'、'.join(少)})" if 少 else "")
                  + (f"(多查:{'、'.join(多)})" if 多 else ""))
    if abs(len(左["回答"]) - len(右["回答"])) > max(40, 0.2 * max(1, len(左["回答"]))):
        差.append(f"回答长短差了不少({len(左['回答'])} 字 → {len(右['回答'])} 字)")
    if 左["这次过了"] != 右["这次过了"]:
        差.append(f"**这一次**的判据结果翻了面({'过' if 左['这次过了'] else '挂'}"
                  f" → {'过' if 右['这次过了'] else '挂'})—— "
                  f"⚠️ 一条题各跑一次,翻面可能只是抖动,**不能当成改动的效果**")
    c左, c右 = 左["用量"].get("成本"), 右["用量"].get("成本")
    if c左 and c右 and abs(c右 - c左) / max(c左, 1e-9) > 0.15:
        差.append(f"这一条的成本差了 {round((c右-c左)/c左*100)}%(${c左:.4f} → ${c右:.4f})")
    if not 差: 差.append("两边看不出明显差别 —— 可能这道题拧不动它,换一道再看")

    return dict(题=dict(id=c["id"], kind=c["kind"], q=c["q"], 期望=c.get("期望", ""),
                        身份=c.get("身份", "")),
                夹具=_摘(x),
                旋钮=旋, 旋钮说=旋话, 松=松,
                左=左, 右=右, 差异=差,
                判词="**这是差异,不是分数。** 一条题各跑一次,两边的差别里混着模型自己的抖动 —— "
                     "这个项目实测过:同一个提交、同一批题连跑两轮,各掉一题而且不是同一题。"
                     "要下结论,走「跑验证集 → 记一次 → 并排比分」那条路,那边有轮间抖动兜底。")


if __name__ == "__main__":
    套 = sys.argv[1] if len(sys.argv) > 1 else "workshop"
    if len(sys.argv) <= 2:
        print(json.dumps(列题(套), ensure_ascii=False, indent=2)); sys.exit(0)
    print(json.dumps(试跑(套, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None),
                     ensure_ascii=False, indent=2))
