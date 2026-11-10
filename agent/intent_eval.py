#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意图识别评测 —— **独立测试集**,只用来验收,不许拿来调东西。

用户 2026-11-08 拍的三件:
· 自动上线门槛**只认一套新写的独立题**(老 50 题只用来调意图说明);
· 两轮都「**判对 ≥ 90% 且判不出 ≤ 5%**」才挂店长助手生产(先不开转人工);
· 分类用**最便宜那档**模型。

## ⚠️⚠️ 这套题只有第一次是真的

跑过一轮、分数被人看过之后,**就不许再拿它调任何东西**
(调意图说明、改提示词、改判据都算)。调过一次,它永久降级成验证集 ——
> 一套从没被用来调过方案的题,和一套在夜跑里跑过八遍、
> 而每次有人看了分数的题,**在题面上长得一模一样**。
所以它**不进夜跑、不进全项目快照、不进 `check.sh`**。
要调配置,拿老 50 题去调(`agentsite/evals/skill_trigger.json`)。

## 「判不出」是失败,不是答案

没有任何一道题的期望是「判不出」—— 和业务无关的、信息太少的,期望都是「闲聊/其它」。
所以它单独算一个数,**不混进判对率**:

    判对率    = 判对的 / 真跑到的
    判不出率  = 判不出的 / 真跑到的
    调用失败  = 单独一类,**不进任何分母**(那是环境问题,不是能力)

> 「模型判不出」和「根本没调成」在「这一轮没有意图」上长得一模一样 ——
> 而前者要改意图说明,后者要查网络 / 额度。(这句话 `意图.py` 文件头也写着。)

## 边界题单独报

带「容易混成」那一栏的题,是**两个意图之间**的。意图识别真正的错误来源在这儿:
「上周营收多少」「出个周报」「营收为什么掉了」三句都在说营收,
分别是问一个数 / 经营报告 / 经营数诊断。
分开报才看得出模型在**哪两个意图之间**分不清,而不是只给一个总分。

跑:

    LANXIU_PROVIDER=claude python3 agent/intent_eval.py          # 两轮
    python3 agent/intent_eval.py --只看题                        # 不调模型,只看题集
"""
import argparse
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
题集 = os.path.join(HERE, "intent_cases.json")
配置文件 = os.path.join(HERE, "intent_config.json")
结果文件 = os.path.join(HERE, "intent-eval-results.jsonl")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
# 门槛(用户 2026-11-08 拍)。**两个都要过,而且两轮都要过。**
判对线, 判不出线 = 0.90, 0.05


def 读(p):
    return json.load(io.open(p, encoding="utf-8"))


def 配置指纹(配置):
    """这一轮用的是哪份意图配置 —— **盖进结果文件**。

    为什么必须盖:后台「意图识别」页建好之后,产品跑的是后台那一份,
    而评测可能还在跑这个文件。两边的分数**看起来一样有意义**。
    这个项目为「评测不跑产品的配置」栽过(评测用 Haiku、网站用 Sonnet,
    同一句话评测 0/3 不触发、真实路径一次就触发)。
    """
    s = json.dumps(配置.get("意图"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def 取意图模块():
    """跨检出 import 管理后台的 `意图.py`。

    它**只用标准库**,所以不需要 `管理后台/.venv`(交接里查实过)。
    ⚠️ 真调产品那一份,不在这里重实现一遍分类逻辑 ——
    夹具里重实现的判据只能抓数据漂移,抓不到实现错误(CLAUDE.md 第 7 节第 2 条)。
    """
    import importlib.util
    p = os.path.join(ROOT, "管理后台", "services", "api", "app", "runtime", "意图.py")
    if not os.path.isfile(p):
        sys.exit(f"{R}❌ 找不到 {p} —— 意图模块搬家了,这条评测**不许自己造一份**替代{D}")
    spec = importlib.util.spec_from_file_location("意图", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def 判一道(期望, 结果):
    """→ (对不对, 类别)。类别 ∈ 判对 / 判错 / 判不出 / 调用失败。

    ⚠️ **三件事分开,一件都不许合并**:
      判错   → 改意图说明 / 加例句(模型选了另一个意图)
      判不出 → 调分类阈值、看缺不缺一个意图(模型没法决定)
      调用失败 → 查网络 / 额度(**不进任何分母**)
    合成一个「没判对」,这三件要触发的动作就永久分不开了。
    """
    态 = (结果 or {}).get("态")
    if 态 == "调用失败":
        return None, "调用失败"
    if 态 == "判不出":
        return False, "判不出"
    名 = (结果 or {}).get("意图")
    return (名 == 期望), ("判对" if 名 == 期望 else "判错")


def 报一轮(行们, 日志=print):
    """判对率 / 判不出率 / 边界题,**每个数都连分母**。"""
    真 = [x for x in 行们 if x["类别"] != "调用失败"]
    失 = [x for x in 行们 if x["类别"] == "调用失败"]
    对 = [x for x in 真 if x["类别"] == "判对"]
    不出 = [x for x in 真 if x["类别"] == "判不出"]
    错 = [x for x in 真 if x["类别"] == "判错"]
    if not 真:
        # 空集合上所有性质都成立 —— 一道都没跑到时**不许印一个率**
        日志(f"  {R}❌ 一道都没真跑到({len(失)} 道调用失败)—— "
             f"**这不叫 0%,这叫没测到**{D}")
        return None
    判对率, 判不出率 = len(对) / len(真), len(不出) / len(真)
    日志(f"  判对 {len(对)}/{len(真)} = {判对率*100:.1f}%"
         f"(门槛 ≥{判对线*100:.0f}%){'✅' if 判对率 >= 判对线 else ' ❌'}"
         f"  ·  判不出 {len(不出)}/{len(真)} = {判不出率*100:.1f}%"
         f"(门槛 ≤{判不出线*100:.0f}%){'✅' if 判不出率 <= 判不出线 else ' ❌'}"
         f"  ·  判错 {len(错)}")
    if 失:
        日志(f"  {Y}⚠ {len(失)} 道**调用失败**,不进任何分母 —— "
             f"那是环境问题不是能力。先看是不是认证 / 额度{D}")
    # 边界题分开报 —— 这才看得出在哪两个意图之间分不清
    边 = [x for x in 真 if x.get("容易混成")]
    if 边:
        边对 = [x for x in 边 if x["类别"] == "判对"]
        日志(f"  边界题 {len(边对)}/{len(边)} 对"
             f"({len(边对)/len(边)*100:.0f}%)—— **两个意图之间的题,错在这儿最值钱**")
        混 = {}
        for x in 边:
            if x["类别"] != "判对":
                混.setdefault((x["期望"], x.get("实际") or x["类别"]), []).append(x["id"])
        for (想, 成), ids in sorted(混.items(), key=lambda kv: -len(kv[1]))[:6]:
            日志(f"     · 「{想}」被判成「{成}」{len(ids)} 道:{'、'.join(ids)}")
    if 错:
        日志(f"  {Y}判错的{D}(模型选了另一个意图 → 改意图说明 / 加例句):")
        for x in 错[:8]:
            日志(f"    {x['id']} 「{x['问'][:26]}」想要「{x['期望']}」,判成「{x.get('实际')}」")
        if len(错) > 8:
            日志(f"    …… 还有 {len(错)-8} 道(共 {len(错)})")
    if 不出:
        日志(f"  {Y}判不出的{D}(模型没法决定 → 调阈值 / 看缺不缺一个意图):"
             f"{'、'.join(x['id'] for x in 不出[:10])}")
    return {"判对率": 判对率, "判不出率": 判不出率, "判对": len(对),
            "真跑到": len(真), "判不出": len(不出), "调用失败": len(失)}


def 达标(汇总):
    """两个门槛都过才算达标;`None`(没测到)**不算达标**。"""
    if not 汇总:
        return False
    return (汇总["判对率"] >= 判对线) and (汇总["判不出率"] <= 判不出线)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--只看题", action="store_true", help="不调模型,只看题集长什么样")
    ap.add_argument("--轮", type=int, default=2, help="跑几轮(默认 2 —— 单轮不许下结论)")
    a = ap.parse_args()
    spec, 配置 = 读(题集), 读(配置文件)
    cases = spec["cases"]
    指纹 = 配置指纹(配置)
    print(f"\n\033[1m意图识别评测 · {len(cases)} 道独立题 · "
          f"{len(配置['意图'])} 个意图 · 配置指纹 {指纹}\033[0m")
    print(f"  {Y}⚠️ 这是独立测试集:跑完**不许拿它调任何东西**。"
          f"调配置请用老 50 题(agentsite/evals/skill_trigger.json){D}")
    print("=" * 92)
    边 = [c for c in cases if c.get("容易混成")]
    print(f"  正向 {len(cases)-len(边)} 道 · 边界 {len(边)} 道"
          f"(两个意图之间,**错在这儿最值钱**)")
    if a.只看题:
        for c in cases:
            print(f"    {c['id']} 「{c['问'][:30]}」→ {c['意图']}"
                  + (f"  (容易混成 {c['容易混成']})" if c.get("容易混成") else ""))
        print(f"\n  {Y}📌 `--只看题`,没调模型。{D}")
        return 0

    意图 = 取意图模块()
    坏 = 意图.意图配置问题(配置)
    if 坏:
        print(f"{R}❌ 这份意图配置本身有问题,**先修配置再跑**:{坏}{D}")
        return 2
    import v1
    def 调模型(s, u, 模型):
        return v1.call([{"role": "user", "content": u}], system=s, model=模型)["text"]

    多轮, 每轮汇总 = [], []
    for 轮 in range(max(1, a.轮)):
        print(f"\n  【第 {轮+1} 轮】")
        行们 = []
        for c in cases:
            r = 意图.分类(c["问"], 配置, 调模型)
            对, 类别 = 判一道(c["意图"], r)
            行们.append(dict(id=c["id"], 问=c["问"], 期望=c["意图"],
                             实际=r.get("意图"), 类别=类别, passed=bool(对),
                             why=f"{类别}:想要「{c['意图']}」,得到「{r.get('意图') or 类别}」",
                             容易混成=c.get("容易混成"), 用时ms=r.get("用时ms"),
                             模型=r.get("模型")))
        每轮汇总.append(报一轮(行们, 日志=print))
        多轮.append({x["id"]: x["passed"] for x in 行们})
        末 = 行们

    print("\n" + "=" * 92)
    # ⚠️ **两轮都要达标**(用户拍的)。一轮达标另一轮不达标 → 不算达标,
    #    而「两轮都过」和「平均过了」是两件事:后者会被一轮的好运气抬上去。
    都达标 = all(达标(x) for x in 每轮汇总)
    print(f"  各轮达标:{['达标' if 达标(x) else '不达标' for x in 每轮汇总]}")
    print(f"  {'✅ 两轮都达标' if 都达标 else '❌ **不是两轮都达标**'} —— "
          f"用户 2026-11-08 拍:两轮都「判对 ≥90% 且判不出 ≤5%」才挂生产(先不开转人工)")
    sys.path.append(HERE)
    import rounds
    try:
        import evalrec
        来路 = evalrec.盖章()
    except Exception as e:
        来路 = None
        print(f"  {Y}⚠ 盖不了来路章({type(e).__name__})—— 这一轮的结果不知道是谁跑的{D}")
    rounds.跑并收尾(lambda: 末, 名="意图识别", 结果文件=结果文件,
                   全集数=len(cases), 本轮数=len(cases), 轮数=1,
                   写=lambda p, rs: _写(p, rs, 指纹, 来路))
    return 0 if 都达标 else 1


def _写(p, rs, 指纹, 来路):
    import evalrec
    # ⚠️ 配置指纹和来路一起盖 —— 「这一轮用的是哪份意图配置」必须永远查得到
    evalrec.dump(p, [{"指纹": {"意图配置": 指纹, "来路": 来路}}] + list(rs))


if __name__ == "__main__":
    sys.exit(main())
