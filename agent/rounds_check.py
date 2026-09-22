#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测要跑几轮 —— **单轮的数,和能下结论的数,在报告上长得一模一样。**

    python3 agent/rounds_check.py          # 门禁:新增的单轮评测一律红
    python3 agent/rounds_check.py --登记     # 把现状写进欠债表(只在第一次用)

## 判据

一个调模型的评测,只跑一轮就报一个百分比,**那个数是一次抽样,不是一个结论**。
这个项目为此栽过五次,最近一次是 2026-09-21:
成长评测基线 7/8 → 第 1 轮 5/8(看着退两题)→ 第 2 轮 6/8,
而 G04 **在同一天的两轮之间自己翻了面**。差一点就去查一个不存在的退化。

所以:**调模型的评测,要么跑两轮并报轮间抖动(走 `agent/rounds.py`),
要么登记在欠债表里。** 新写的一律红。

## 为什么是棘轮,不是一次改完

现存 15 个单轮评测。一次全改的问题有三个,每个都真实:

  · 每个评测的主循环长得都不一样,15 处手改本身就会出错
  · 改完要**各跑两轮**验证,而它们都要调模型
  · 并行会话正在改其中几个(`ops_eval.py` 此刻就在别人手里)

所以登记现状、只许少不许多。**修好的必须从欠债表里删掉**(反向检查)——
没有反向那一半,欠债表会囤积一堆早就还清的条目,
而**囤积的欠债和真欠债长得一模一样**。

## ⚠️ 这个检查看不见什么

它看的是**脚本里有没有多轮的痕迹**(引了 `rounds`,或者自己写了轮次循环),
**不是**「它真的跑了两轮」。一个引了 `rounds` 却把轮数写死成 1 的脚本,
这里照样绿。真正的把关在 `rounds.报()` 自己身上 ——
只跑一轮时它会打印「**不能下结论**」,那句话是运行时说的,赖不掉。
两条合起来才拦得住:这条管「接没接」,那句管「接了有没有用」。
"""
import ast, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
欠债表 = os.path.join(ROOT, "agent", "单轮评测欠债.json")
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("把 growth_eval 里 `import rounds` 那段去掉(它会变回单轮而没登记)",
     "没有新增的单轮评测"),
    ("在欠债表里留一条已经改成多轮的评测", "欠债表里的都还欠着"),
]

# 这些不是评测本体:judgetest 是判分器的离线对照,evalrec 是记录仪,
# rounds 是这套东西自己。把它们算进来会让数字带噪音,
# 而**一个混了噪音的清单,人看两次就不看了**。
不算 = {"evalrec.py", "rounds.py", "rounds_check.py"}


def 算多轮(src):
    """这个脚本是不是真的跑多轮 —— **查结构,不枚举词。**

    ⚠️ 第一版用正则找「第1轮 / 轮间 / 两轮 / import rounds」,咬合当场没咬动:
    我把 `import rounds` 改坏了,而脚本里还有一句**打印用的**
    `f"【第 {i+1} 轮】"` —— 正则把那句提示文案当成了多轮证据。
    也就是说:**一个把「第 1 轮」写进提示语、实际只跑一轮的脚本,它会判成多轮。**

    这是 CLAUDE.md 那条「判据不许枚举词,要查结构」栽的第九次。

    改成按语法树认两件事,任一成立即可:
      · 真的调了 `rounds.报(...)` / `rounds.跑(...)`
      · 主流程里有一个**以轮次为名**的循环,而且循环体里有函数调用
        (纯粹在字符串里写「轮」的骗不过它 —— 字符串不是 For 节点)
    """
    try:
        树 = ast.parse(src)
    except SyntaxError:
        return False
    for n in ast.walk(树):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
           and isinstance(n.func.value, ast.Name) and n.func.value.id == "rounds" \
           and n.func.attr in ("报", "跑", "跑并收尾"):
            return True
        # `for 轮 in (1, 2)` / `for _ in range(2)` 这种,循环体里得真有调用
        if isinstance(n, ast.For):
            名 = n.target.id if isinstance(n.target, ast.Name) else ""
            范围 = None
            if isinstance(n.iter, ast.Call) and isinstance(n.iter.func, ast.Name) \
               and n.iter.func.id == "range" and n.iter.args \
               and isinstance(n.iter.args[-1], ast.Constant):
                范围 = n.iter.args[-1].value
            elif isinstance(n.iter, ast.Tuple):
                范围 = len(n.iter.elts)
            if 范围 and 范围 >= 2 and ("轮" in 名 or "round" in 名.lower()) \
               and any(isinstance(x, ast.Call) for x in ast.walk(n)):
                return True
    return False


def 评测们():
    出 = []
    for d in ("agent", "backend", "agentsite"):
        p = os.path.join(ROOT, d)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            if not f.endswith(".py") or "eval" not in f or f in 不算:
                continue
            if "judgetest" in f or f.endswith("_test.py"):
                continue
            t = open(os.path.join(p, f), encoding="utf-8").read()
            # 不调模型的不算(纯规则的评测跑一轮就够 —— 结果不会变)。
            #
            # ⚠️ **第一版的判据太紧,把做得最对的两个漏掉了。**
            # 只认 `sdk.run|v1.call|asyncio.run`,而 `chat_eval` 走 `chat.ask()`、
            # `opportunity_eval` 走 `opportunity.判断(用模型=True)` —— 两个都没命中,
            # 于是它们整个不在清单里,报出「13 个里多轮只有 1 个」这么个难看又错的数。
            #
            # **判据太松会误报,太紧会漏报,而漏报更危险** ——
            # 误报会被人骂,漏报只是安静地少一行,没有任何信号。
            # 所以这里宁可放宽:命中任意一种「把问题交给模型」的写法就算。
            调模型 = bool(re.search(
                r"sdk\.run|v1\.call|asyncio\.run|provider\(|\.ask\(|"
                r"用模型|import opportunity|LANXIU_PROVIDER|ANTHROPIC_MODEL", t))
            if not 调模型:
                continue
            多轮 = 算多轮(t)
            出.append((f"{d}/{f}", 多轮))
    return 出


def main():
    现 = 评测们()
    单轮 = sorted(f for f, 多 in 现 if not 多)
    if "--登记" in sys.argv:
        json.dump({"说明": "调模型的评测里,还没接多轮 + 轮间抖动的那些。"
                           "**只许少不许多**;改好一个就从这里删一条,"
                           "删不删由 agent/rounds_check.py 强制。",
                   "怎么还": "把主循环包成 `跑一轮()`,跑两轮,"
                             "最后 `rounds.报(多轮, 基线通过数=...)`。参考 agent/growth_eval.py。",
                   "登记于": "2026-09-21", "欠着的": 单轮},
                  open(欠债表, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"登记 {len(单轮)} 个单轮评测 → {欠债表}")
        return 0

    欠 = (json.load(open(欠债表, encoding="utf-8")).get("欠着的", [])
          if os.path.isfile(欠债表) else [])
    失败 = []

    def ck(ok, 名, 说明=""):
        print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
        if not ok:
            失败.append(名)

    print("评测要跑几轮")
    # 样本量先报:一个都没扫到时,下面两条自动成立
    ck(len(现) >= 5, "扫到的调模型评测", f"{len(现)} 个,其中多轮 {len(现) - len(单轮)} 个")

    新增 = [f for f in 单轮 if f not in 欠]
    ck(not 新增, "没有新增的单轮评测",
       "、".join(新增[:4]) + (f"  ……**还有 {len(新增) - 4} 个**(共 {len(新增)})"
                             if len(新增) > 4 else "")
       + " —— 调模型的评测只跑一轮,那个数是一次抽样不是结论。"
         "接 `agent/rounds.py`,参考 agent/growth_eval.py"
       if 新增 else f"欠债表里 {len(欠)} 个,一个没多")

    好了 = [f for f in 欠 if f not in 单轮]
    ck(not 好了, "欠债表里的都还欠着",
       "、".join(好了[:4]) + (f"  ……**还有 {len(好了) - 4} 个**(共 {len(好了)})"
                             if len(好了) > 4 else "")
       + " —— **已经改成多轮了,该从欠债表里删掉**。囤积的欠债和真欠债长得一模一样"
       if 好了 else f"{len(欠)} 个都还欠着")

    if 欠:
        print(f"     ℹ️ 欠着 {len(欠)} 个 —— 不拦门禁,但**只许少不许多**:"
              f"{'、'.join(os.path.basename(x) for x in 欠[:6])}"
              + (f" …… 还有 {len(欠) - 6} 个" if len(欠) > 6 else ""))
    print((f"{R}❌ 评测轮次 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 评测轮次{D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
