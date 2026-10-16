#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把被 AI 根因覆盖掉的 `task.summary` 还原成**造数当时那个值**。默认只报不写。

    python3 tools/restore_task_summary.py          # 只报
    python3 tools/restore_task_summary.py --写      # 真写(要共享库的窗口)

## 为什么要还原

`backend/ops.py:682`(`save_triage`)落库那一刻把**模型自己那段根因**截 60 字写进了
`task.summary`。后果有三层,一层比一层深:

1. **页面**:研判队列每行显示的就是 summary —— 于是看队列的人读到的「这条工单是怎么回事」
   其实是「AI 当时怎么说的」,而那句话可能是错的(`TDQ9001` 这条就是),旁边没有任何标记
   说这是 AI 说的、还没人复核。
2. **工单原本的事由被盖掉了** —— 售后判责那 12 条原本写的是「商品 · 报修问题」。
3. 🔺 **下一轮会读到上一轮的答案**:研判跑的角色是后台运营(`sdk.run("task", …)`),
   它挂着 `list_tasks`,而那是 `SELECT *` —— summary 跟着出来。于是**同一条工单重跑研判时,
   模型看得到自己上一轮的结论**,第二轮不是独立的一轮,
   而 CLAUDE.md 那条「连跑两轮」的意义被它抵掉一半。

停写归研判队列线(它改 `ops.py` 682 / 709);**还原归造数线**,所以是这个脚本。

## 哪些是 AI 写的:有干净的判法,不猜

    summary == 最新那条 triage 的 ai_root_cause 前 60 字      → 是它写的
    summary == "(未解析出根因)"                               → 也是它写的(那一行的兜底)

实测:库里有研判的工单**一共 54 条,54 条全是它写的**,没有一条还留着原值。
而原值**没有任何地方留痕**(`save_triage` 不写 `op_log`,查过 0 行),
所以只能按造数当时那条公式重算 —— 分两种:

    42 条  原值就是 **NULL**(财务 24 + 财务 TDQ 2 + 客户合并 TMERGE 16 —— 三处造数都插的 None)
    12 条  售后判责:`item · issue`,**而这两样是 `maintain` 表上还在的列**

## ⚠️ 公式只有一份:`seed.工单摘要_售后()`

造数和还原**调同一个函数**。手拼第二份的后果不是报错 ——
> 还原出来的 summary 和新造的长得**不一样**,而两边分别看都正常。

这正是这个仓库反复撞的那个形状(确认书补单那次:手写 INSERT 会让条款版本成为第二份实现)。
所以这个脚本**不许**自己写 `f"{item} · {issue}"`;那个函数没了就当场抛,不退回手拼。
"""
import argparse, os, sqlite3, sys

这里 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(这里)
sys.path[:0] = [os.path.join(根, "backend"), os.path.join(根, "knowledge"), 根]

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def 公式_售后():
    """售后判责那条摘要的**唯一**来源。"""
    import seed
    f = getattr(seed, "工单摘要_售后", None)
    assert f, ("`backend/seed.py` 里没有 `工单摘要_售后()` —— 造数那条公式还没提成函数。"
               "**不要在这儿手拼一份**:手拼的话还原出来的和新造的长得不一样,而两边分别看都正常。")
    return f


def 要还原的(c):
    """(工单号, 类型, 现在的 summary, 该还原成什么)。该还原成什么 = None 或 那条公式算出来的。"""
    摘要 = 公式_售后()
    出 = []
    for r in c.execute("""
            SELECT t.id, t.type, t.summary,
                   (SELECT x.ai_root_cause FROM triage x WHERE x.task_id=t.id
                     ORDER BY x.id DESC LIMIT 1) 根因,
                   m.item, m.issue
            FROM task t
            LEFT JOIN maintain m ON m.id = t.ref_id AND t.type='售后判责'
            WHERE EXISTS(SELECT 1 FROM triage x WHERE x.task_id=t.id)
              AND t.summary IS NOT NULL"""):
        tid, 类型, 现在, 根因, item, issue = r
        是它写的 = (现在 == "(未解析出根因)") or bool(根因 and 现在 == 根因[:60])
        if not 是它写的:
            continue
        if 类型 == "售后判责":
            if not (item and issue):
                出.append((tid, 类型, 现在, "**还原不了**"))      # 维保单没了 → 报出来,不猜
                continue
            出.append((tid, 类型, 现在, 摘要(item, issue)))
        else:
            出.append((tid, 类型, 现在, None))
    return 出


def 跑(库, 真写):
    c = sqlite3.connect(库)
    单 = 要还原的(c)
    坏 = [x for x in 单 if x[3] == "**还原不了**"]
    好 = [x for x in 单 if x[3] != "**还原不了**"]
    print(f"库:{库}")
    print(f"被 AI 根因覆盖的工单 **{len(单)} 条**;能还原 {len(好)}、还原不了 {len(坏)}")
    from collections import Counter
    for k, v in sorted(Counter(f"{t} → {'空' if s is None else '那条公式'}"
                               for _, t, _, s in 好).items()):
        print(f"   {v:3d}  {k}")
    for tid, 类型, 现在, _ in 坏:
        print(f"   {R}✗{D} {tid}({类型}):维保单查不到,**不猜一个** —— 要人看")
    print("\n抽三条看看:")
    for tid, 类型, 现在, 新 in 好[:3]:
        print(f"   {tid} {类型}\n     现在:{str(现在)[:56]!r}\n     还原:{新!r}")
    if 真写:
        for tid, _, _, 新 in 好:
            c.execute("UPDATE task SET summary=? WHERE id=?", (新, tid))
        c.commit()
    c.close()
    print()
    if 真写:
        print(f"{G}✅ 已还原 {len(好)} 条{D}")
    else:
        print(f"{Y}📌 这是只报,一个字都没写。确认后加 `--写`(要共享库的窗口){D}")
    return len(好), len(坏)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--库", default=os.path.join(根, "backend", "lanxiu.db"))
    ap.add_argument("--写", action="store_true")
    a = ap.parse_args()
    print("还原被 AI 根因覆盖的工单摘要 —— 公式只有 `seed.工单摘要_售后()` 一份")
    print("=" * 72)
    好, 坏 = 跑(a.库, a.写)
    raise SystemExit(0)
