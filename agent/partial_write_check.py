#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑一部分题,却把完整基线覆盖掉 —— **文件上一点看不出区别。**

    python3 agent/partial_write_check.py          # 门禁
    python3 agent/partial_write_check.py --登记    # 把现状写进欠债表(只在第一次用)

## 这条是怎么来的

同一个形状,**三个月里在三个文件上各发作一次**,而每次都是单独修的:

  1. 2026-09-21 `growth_eval.py G05` —— 跑一题,把 8 条基线覆盖成 1 条。**我自己踩的。**
  2. 2026-09-21 `vision_eval.py`  —— 同样有 `only` 过滤、同样无条件写文件(修 ① 时没看它)
  3. 2026-09-22 `liability_eval.py` —— 还在(修 ② 时也没看它)

三次的根因一模一样:

    脚本能只跑一部分(`only` / `--only`),而写结果文件那一步**不问跑了多少**。

> **「跑一部分」和「跑全部」写的是同一个文件,而文件上一点看不出区别。**

再往上一层,它和 CLAUDE.md 记着的那次事故是同一个形状 ——
那次是 DeepSeek 的数覆盖了六份 Claude 的结果。覆盖本身不报错、不变形,
只是少了几条,而**下一个人拿它当基线**。

## 为什么值得做成检查,而不是「下次注意」

因为前两次我都「注意」了 —— 修完第一处,我以为修完了。
**修一处不等于修一类**,而「已经修完了」和「只修了一处」在当时看起来完全一样:
两次跑门禁都是绿的。

## 判据(落结构,不枚举词)

两件事同时成立才算欠债:

  · **能只跑一部分** —— 有个变量是从 `sys.argv` / argparse 的 `--only` 流出来的
  · **写结果文件这一步,跟「跑了多少」毫无关系** —— 那个变量的数据流
    走不到 `evalrec.dump(...)` / `json.dump(..., open(...,"w"))`

⚠️ **判据不是「外面有没有一层 if」。** 第一版那么写,当场把 `ops_eval` 误报了 ——
它解决了,只是**用了另一种写法**。实际有三种合法形状,而且都对:

    ① 部分时**不写**              growth / vision / liability
    ② 部分时**写到另一个文件**    ops_eval(`...partial.jsonl`)
    ③ 部分时**写进指纹里**        chat_eval(`cases=cs` 进 fingerprint,
                                  覆盖了也看得出来)

所以判据只问一句:**「跑了一部分」这件事,能不能走到写文件那一步。**

## 这个检查看不见什么

**它分不出上面那三种,也分不出「深思熟虑」和「碰巧连上了」。**
数据流通了就算过 —— 一个把子集变量顺手塞进某个无关字段的脚本,这里照样绿。

它也不看**判得对不对**:`if len(todo) < 0:` 这种假守卫,这里过。
运行时那句「⚠️ 这次只跑了 N/M 题,不写结果文件」才是真把关 ——
这条管「接没接」,那句管「接了对不对」。
"""
import ast, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
欠债表 = os.path.join(ROOT, "agent", "部分覆盖欠债.json")
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("把 liability_eval 里 `if len(todo) < len(CASES):` 那层守卫去掉",
     "没有新增的「跑一部分却覆盖全量」"),
    ("在欠债表里留一条已经加了守卫的评测", "欠债表里的都还欠着"),
]

不算 = {"evalrec.py", "rounds.py", "rounds_check.py", "partial_write_check.py"}


def _写结果的调用(树):
    """找「把这一轮结果写进文件」的调用。返回节点列表。"""
    出 = []
    for n in ast.walk(树):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        # evalrec.dump(...) / json.dump(..., open(..., "w"))
        if isinstance(f, ast.Attribute) and f.attr == "dump":
            if isinstance(f.value, ast.Name) and f.value.id in ("evalrec", "_er"):
                出.append(n)
            elif isinstance(f.value, ast.Name) and f.value.id in ("json", "_js"):
                # 只算真的写文件的那种:第二个参数是 open(...)
                if len(n.args) >= 2 and isinstance(n.args[1], ast.Call) \
                   and isinstance(n.args[1].func, ast.Name) \
                   and n.args[1].func.id == "open":
                    出.append(n)
    return 出


def _名字们(节点):
    """一段表达式里引用到的名字,含 `a.only` 这种点号路径。"""
    出 = set()
    for x in ast.walk(节点):
        if isinstance(x, ast.Name):
            出.add(x.id)
        elif isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name):
            出.add(f"{x.value.id}.{x.attr}")
    return 出


def _筛选名(树):
    """「这一轮只跑了一部分」这件事,存在哪几个名字里 —— 顺着数据流传播。

    源头两种:
      · 读 `sys.argv` 的赋值(`only = [a for a in sys.argv[1:] ...]`)
      · argparse 里那个**表示「只跑某几条」的参数**,取 `<解析结果>.<参数名>`

    ⚠️ **这里认得出的源头是有限的**,而认不出会变成**漏报**(安静地少一行)。
    argparse 那一支靠参数名里带 `only` 认 —— 名字是从这个文件自己的
    `add_argument("--only")` 字面量里读出来的,不是我这儿写死的词表;
    但换个名字(`--pick` / `--subset`)就认不出了。
    知道这条限制,比假装它没有强。
    """
    污 = set()
    # 源头 ①:直接读 argv
    for n in ast.walk(树):
        if isinstance(n, ast.Assign) and any(
                isinstance(x, ast.Attribute) and x.attr == "argv"
                for x in ast.walk(n.value)):
            for t in n.targets:
                污 |= _名字们(t)
    # 源头 ②:argparse 里名字带 only 的参数 → `<parse_args 的结果>.<名>`
    只跑的参数 = set()
    for n in ast.walk(树):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
           and n.func.attr == "add_argument":
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                   and "only" in a.value.lower():
                    只跑的参数.add(a.value.lstrip("-").replace("-", "_"))
    if 只跑的参数:
        for n in ast.walk(树):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
               and isinstance(n.value.func, ast.Attribute) \
               and n.value.func.attr == "parse_args":
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        污 |= {f"{t.id}.{p}" for p in 只跑的参数}
    # 传播:引用了污点的赋值,自己也变成污点(跑到不动为止)
    for _ in range(8):
        新 = set(污)
        for n in ast.walk(树):
            if isinstance(n, ast.Assign) and (_名字们(n.value) & 污):
                for t in n.targets:
                    新 |= _名字们(t)
        if 新 == 污:
            break
        污 = 新
    return 污


def _跑了多少影响到了它(树, 目标, 污):
    """写这一步,**受不受「这轮跑了多少」影响**。

    ⚠️ 判据**不是**「外面有没有一层 if」。2026-09-22 第一版就是那么写的,
    当场把 `ops_eval` 误报成欠债 —— 而它其实解决了,只是**用了另一种写法**:
    跑一部分时写到 `...partial.jsonl`,基线那个文件根本不碰。

    > **合法的第二种写法,和没解决,在「有没有那层 if」上长得一模一样。**

    所以判据改成数据流:**「跑了一部分」这件事,得能走到写文件这一步** ——
    走进条件里(不写 / 换个分支),或者走进路径里(写到别处),两条都算数。
    """
    # ① 包着它的 if,条件里提到了污点
    for n in ast.walk(树):
        if isinstance(n, ast.If) and (_名字们(n.test) & 污):
            if any(x is 目标 for x in ast.walk(n)):
                return True
    # ② 写调用自己的参数里提到了污点(比如输出路径是按跑没跑全算出来的)
    return bool(_名字们(目标) & 污)


def 欠着吗(src):
    """(欠不欠, 为什么, 守着没有)。**认不出来就说认不出来**,不硬塞。

    第三位是**结构上**的「守着」,给样本量那行计数用。
    ⚠️ 原来那行是拿提示文案 `'len() 守卫' in 说` 数的 —— 判据换了说法,
    它**静默归零**(报「写得有守卫的 0 个」,实际 5 个)。
    计数和提示文案绑在一起,改一句话就漂:**数东西要数结构,不数文案。**
    """
    try:
        树 = ast.parse(src)
    except SyntaxError as e:
        return False, f"语法解析不了({e.__class__.__name__})—— **这不叫通过**", False
    # ⚠️ 「能只跑一部分」的判据就是 `_筛选名()` 找不找得到污点源 ——
    # **不能只看 `sys.argv` 出现过没有**。第一版那么写,把 `scheme_eval` 里的
    # `if "--run" not in sys.argv:` 当成了子集筛选,而那是一道**闸**
    # (不加 --run 就不跑),压根不能只跑几题。
    # **一道闸和一个筛选,在「有没有读 argv」上长得一模一样。**
    污 = _筛选名(树)
    if not 污:
        return False, "不能只跑一部分(argv 没有流进任何变量)", False
    # 交给共用收尾 `rounds.跑并收尾(...)` 写的:守卫在它里面(有咬合),
    # 这里只查一件事 —— **`本轮数` 真的接到了筛选变量上**。
    # 传一个写死的数进去(`本轮数=6`),守卫就形同虚设,而调用看上去一模一样。
    for n in ast.walk(树):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
           and isinstance(n.func.value, ast.Name) and n.func.value.id == "rounds" \
           and n.func.attr == "跑并收尾":
            本 = next((k.value for k in n.keywords if k.arg == "本轮数"), None)
            if 本 is None or not (_名字们(本) & 污):
                return True, ("交给 rounds.跑并收尾 写,但 `本轮数` **没接到筛选变量上**"
                              f"(第 {n.lineno} 行)—— 部分跑时守卫不会触发"), False
            return False, "写结果交给 rounds.跑并收尾(守卫在里面,本轮数接着筛选变量)", True
    写 = _写结果的调用(树)
    if not 写:
        return False, "不写结果文件", False
    没守的 = [n for n in 写 if not _跑了多少影响到了它(树, n, 污)]
    if not 没守的:
        return False, f"{len(写)} 处写调用都受「跑了多少」影响", True
    return True, (f"能只跑一部分,而 {len(没守的)}/{len(写)} 处写结果文件的调用"
                  f"**跟「跑了多少」完全无关**(第 {没守的[0].lineno} 行)"), False


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
            src = open(os.path.join(p, f), encoding="utf-8").read()
            欠, 说, 守 = 欠着吗(src)
            出.append((f"{d}/{f}", 欠, 说, 守))
    return 出


def main():
    现 = 评测们()
    欠的 = sorted(f for f, 欠, _, _守 in 现 if 欠)

    if "--登记" in sys.argv:
        json.dump({"说明": "能只跑一部分题、却无条件覆盖结果文件的评测。"
                           "**只许少不许多**;加了守卫就从这里删一条,"
                           "删不删由 agent/partial_write_check.py 强制。",
                   "怎么还": "写结果文件那一步包一层 "
                             "`if len(todo) < len(CASES): 明说不写 else: 写`。"
                             "参考 agent/growth_eval.py 结尾。",
                   "登记于": "2026-09-22", "欠着的": 欠的},
                  open(欠债表, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"登记 {len(欠的)} 个 → {欠债表}")
        return 0

    欠 = (json.load(open(欠债表, encoding="utf-8")).get("欠着的", [])
          if os.path.isfile(欠债表) else [])
    失败 = []

    def ck(ok, 名, 说明=""):
        print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
        if not ok:
            失败.append(名)

    print("跑一部分却覆盖全量")
    # 样本量先报 —— 一个都没扫到时,下面两条自动成立
    ck(len(现) >= 5, "扫到的评测脚本",
       f"{len(现)} 个,其中能只跑一部分且**写得有守卫**的 "
       f"{sum(1 for *_, 守 in 现 if 守)} 个")

    新增 = [f for f in 欠的 if f not in 欠]
    ck(not 新增, "没有新增的「跑一部分却覆盖全量」",
       "、".join(新增[:4]) + (f"  ……**还有 {len(新增) - 4} 个**(共 {len(新增)})"
                             if len(新增) > 4 else "")
       + " —— 跑一部分把完整基线覆盖掉,**文件上看不出区别**。"
         "写文件那步包一层 `if len(todo) < len(CASES)`,参考 agent/growth_eval.py"
       if 新增 else f"欠债表里 {len(欠)} 个,一个没多")

    好了 = [f for f in 欠 if f not in 欠的]
    ck(not 好了, "欠债表里的都还欠着",
       "、".join(好了[:4]) + (f"  ……**还有 {len(好了) - 4} 个**(共 {len(好了)})"
                             if len(好了) > 4 else "")
       + " —— **已经加上守卫了,该从欠债表里删掉**。囤积的欠债和真欠债长得一模一样"
       if 好了 else f"{len(欠)} 个都还欠着")

    if 欠:
        print(f"     ℹ️ 欠着 {len(欠)} 个 —— 不拦门禁,但**只许少不许多**:"
              f"{'、'.join(os.path.basename(x) for x in 欠[:6])}"
              + (f" …… 还有 {len(欠) - 6} 个" if len(欠) > 6 else ""))
    print((f"{R}❌ 部分覆盖 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 部分覆盖{D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
