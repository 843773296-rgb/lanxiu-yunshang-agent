#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""差评研判的产线路 —— **接通,默认不开**(用户 2026-10-13 拍「做产线那条路」)。

一条差评怎么判:
  ① 提示词从 `backend/ops.差评研判提示词` 取(处理方式从 `rating.处理方式` 现拼,不抄)
  ② 以**一个真员工的身份**跑 —— `service_records` 只给店长 / 售后看,没身份就取不到材料
  ③ 跑的时候告诉工具服务「这一轮在判哪条」(`被判包裹`)—— 三个工具服务出门前
     把**它自己**的人工处置抹成 None(`mcp/protocol.遮被判那条`)。模型改不了这件事
  ④ 记下**这一轮到底调没调 service_records** —— 产线上材料是模型自己取的,
     「取不取」本身就是要量的东西(数据工厂探针是替它取好塞进去的,那个数是上限)

⚠️ **这里没有开关** —— 开关在调用方:产线入口(app.py 的批量研判)**不调这里**,
照旧走 `ops.研判提示词` 不带 `开差评`、当场说「默认关闭」。
这个模块现在只给**评测走产线路**用;启用要过四道闸、用户拍板。
"""
import asyncio, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

取材料的工具 = "service_records"


def 取了材料吗(轨迹):
    """这一轮有没有调过取材料那个工具。MCP 工具名带前缀(mcp__service__service_records),按结尾认。"""
    return any(str((s or {}).get("tool") or "").split("__")[-1] == 取材料的工具 for s in (轨迹 or []))


def 版本记(轨迹):
    import ops
    return f"{ops.差评研判版本} | 这一轮{'调了' if 取了材料吗(轨迹) else '**没调**'} {取材料的工具}"


def 出钱转人工(结果):
    """**出钱的档位,结构上交给人判**(用户 2026-10-21 拍)。→ (转不转人工, 提到了哪几个)。

    诱导卷 2×2 实测(现行 / 候选 TK16-先定档 各两轮,同一批 80 道):出钱违规两版**都是 3 条**,
    而且每轮冒出来的不是同一批题 —— 约 2% 的随机发生率,改提示词压不到零,零容忍那条线靠规矩守不住。
    所以不再指望模型自觉:**回答里只要出现「部分退款 / 全额退款」,不管它是在建议还是在否定,
    这一条就转人工、AI 不给档位**。不去分辨「建议」和「否定」—— 那要枚举措辞,而枚举必输
    (读判定的段首层就在「讲规则时提到全额退款」上读错过一次)。宁可多转:实测平时(不带诱导)只有 2% 会转,
    带诱导时 24% —— 那些本来就是有争议的单。漏判出钱不可逆,多转一条只是多一个人看一眼。"""
    import rating as R
    文 = str((结果 or {}).get("answer") or (结果 or {}).get("text") or "")
    提到 = [w for w in R.出钱的处理方式 if w in 文]
    return bool(提到), 提到


def 跑一条(task_id, ref, me, provider=None, model_name=None, 诱导前提=None):
    """判一条差评,**不落库** —— 返回 (断点号, case_id, sdk 结果, 版本记)。落不落、落到哪个库由调用方定。

    me  跑的身份 {no, name, role},必须是能看服务记录的角色(店长 / 售后)。
    诱导前提  只给诱导卷用(2026-10-20):原样接在提示词后面,措辞和探针一样(「处理人补了一句」),
             话术一律从 `agent/triage_sets.诱导` 取 —— 这里不收自由文本以外的东西,也不改提示词别处。
    """
    import ops, sdk
    if not (me and me.get("no") and me.get("role")):
        raise PermissionError("判差评要以一个真员工的身份跑 —— service_records 没身份取不到材料")
    bp, case, prompt = ops.研判提示词("评价差评", ref, task_id, 开差评=True)
    if 诱导前提:
        prompt += f"\n\n（处理人补了一句)：{诱导前提}"
    r = asyncio.run(sdk.run("task", prompt, me=me, 被判包裹=ref,
                            provider=provider, model_name=model_name))
    r["出钱转人工"], r["提到的出钱方式"] = 出钱转人工(r)     # 用的人必须先看这一项:为真就不许展示 AI 的档位
    return bp, case, r, 版本记(r.get("trajectory"))
