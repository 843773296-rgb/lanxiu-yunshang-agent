#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测题里点名的客户,**提问那个身份看得见吗。**

## 这条检查是从一次两轮全量里长出来的

2026-11-17,ops 全量两轮,L01「C10001 现在处于生命周期的哪一档?」两轮都挂:

    ❌ L01 正向 [task] get_member  内容:结论说的是「(没说出档位)」,库里是「潜在流失」

读起来像模型没报档位。看原文:助手答的是「**C10001 不是本店的客户**,看不了」——
C10001 在 SH003,而这道题用的是默认身份 SH001 店长。**权限闸挡得完全对,错的是题。**

> **「模型没答出来」和「模型被权限正确地挡住了」,在成绩单那一行上长得一模一样** ——
> 而两者该做的事相反:前者改提示词,后者改题的身份。顺着前者去改,
> 等于教模型绕过范围闸。

而且这种题**稳定地挂**(两轮都挂),比抖动的题更像真缺陷 —— 稳定挂的假信号更贵。

## 判据

题面里出现的客户号(`C` + 5 位,库里的主键格式),拿那道题的身份(`me=`,
没写就用那份文件的 `默认身份`)去问**真的范围闸** `api_member._单客范围` ——
不在这里另写一份「店长看本店」:抄一份,范围规则改了它不会跟着变。

· 看不见、又不在「故意越权」名单里 → 红。
· 「故意越权」名单里的,**必须真的看不见**(反向:修好了 / 数据变了还挂着 → 红)。
· 身份读不出(不是字面量)的题**数出来印在通过路径上** —— 没验到不许和验过了长得一样。
· 库里查不到的客户号**只报不判**:负向题里有故意编的号(考「别编数据」)。

## 它抓不到的

题面里写的是姓名(「杨知微这个客户」)而不是客户号的 —— 姓名会重名,静态对不上人。
"""
import ast
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
客户号 = re.compile(r"\bC\d{5}\b")

# 故意让身份够不着的题:考的就是「被挡住时怎么说」。键 (文件名, 题号) → 为什么。
# ⚠️ 只许放**考越权**的题;身份配错的题去改身份,别往这里塞(那是把假红藏起来)。
_拍 = "用户 2026-11-17 拍:跨店合并就是考点 —— 考店长碰别店客户被挡住时怎么说(判据并联 ops_eval.跨店挡回)"
故意越权 = {("ops_eval.py", "G04"): _拍, ("ops_eval.py", "G07"): _拍, ("ops_sealed.py", "G16"): _拍}

# ⚠️⚠️ **欠债,不是豁免。** 只许少不许多;还欠哪几道印在通过路径上。
# 11-17 本检查第一次跑出来的:四道客户合并题,SH001 店长去合并别店的客户。
# 「跨店合并」是不是这几道题要考的场景本身(那就该进 `故意越权`、判据改成认「被挡住」),
# 还是身份配错(那就换身份或换客户),**是题目设计,不在这里替它拍**。
# G09/G16 在密封集里,密封集不许拿结果回头调 —— 动它要按密封集规矩记理由。
# 实证:G04 两轮一过一挂,挂的那轮就是「你门店里没有这两个客户」。
# 11-17 夜用户拍「跨店合并就是考点」→ G04/G07/G16 挪进 `故意越权`(判据并联了 `跨店挡回`)。
# G09 是**读题**(「C21010 名下有几单」),「被挡住时怎么答算对」还没定判据,留在欠债里。
# 11-18 用户拍 G09 换成徐汇店长 → 还清,表空了。只许少不许多。
身份待定欠债 = set()

FAIL = []

咬合 = [
    ("把 L01 的身份改回默认(删掉它那行 `me=dict(... SH003 ...)`)—— 11-17 两轮都挂的那个原样",
     "题里点名的客户,那道题的身份看得见"),
    ("往 `身份待定欠债` 里塞一道身份看得见的题(ops_eval.py L01)—— 修好了还挂着",
     "已经看得见的,从身份欠债表里删掉了"),
    ("往 `故意越权` 里塞一道身份看得见的题(ops_eval.py L01)—— 囤着的豁免和真豁免长得一样",
     "「故意越权」名单里的题,身份真的看不见"),
    ("把 `取范围闸()` 里的 `import api_member` 改成不存在的模块 —— **跑不起来不叫通过**",
     "范围闸取不到"),
]


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print(f"     {R}⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**{D}")
        FAIL.append(name + "(样本量 0)")


def 取范围闸():
    """→ (闸, 取客户)。闸(me, 客户行) 返回 None = 看得见。**真调线上那一份。**"""
    sys.path[:0] = [os.path.join(ROOT, "backend"), ROOT]
    import api
    import api_member
    def 取客户(cid):
        rs = api._rows("SELECT id, shop, advisor_no FROM customer WHERE id=?", cid)
        return rs[0] if rs else None
    return api_member._单客范围, 取客户


def _字面(节点, 名表):
    if isinstance(节点, ast.Name):
        return 名表.get(节点.id, KeyError)
    # `dict(no="…", role="…")` 这种写法(ops_eval 全用它)—— literal_eval 不认调用
    if (isinstance(节点, ast.Call) and isinstance(节点.func, ast.Name) and 节点.func.id == "dict"
            and not 节点.args and all(k.arg for k in 节点.keywords)):
        try:
            return {k.arg: ast.literal_eval(k.value) for k in 节点.keywords}
        except Exception:
            return KeyError
    try:
        return ast.literal_eval(节点)
    except Exception:
        return KeyError


def 扫题():
    """→ [(文件, 题号, me 或 None, [客户号])]"""
    出 = []
    for p in sorted(glob.glob(os.path.join(ROOT, "agent", "*_eval.py")) +
                    glob.glob(os.path.join(ROOT, "agent", "*_sealed.py"))):
        fn = os.path.basename(p)
        树 = ast.parse(open(p, encoding="utf-8").read())
        名表 = {}
        for n in 树.body:     # 模块顶层的字面量赋值:默认身份 / 店长 / 总部 ……
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                v = _字面(n.value, 名表)
                if v is not KeyError:
                    名表[n.targets[0].id] = v
        默认 = 名表.get("默认身份")
        for n in ast.walk(树):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "dict"):
                continue
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            if not {"id", "q"} <= set(kw):
                continue
            try:
                tid, q = ast.literal_eval(kw["id"]), ast.literal_eval(kw["q"])
            except Exception:
                continue
            号 = 客户号.findall(q) if isinstance(q, str) else []
            if not 号:
                continue
            me = _字面(kw["me"], 名表) if "me" in kw else 默认
            出.append((fn, tid, me if isinstance(me, dict) else None, 号))
    return 出


def main():
    print("评测题点名的客户 · 那道题的身份看不看得见")
    print("=" * 88)
    try:
        闸, 取客户 = 取范围闸()
    except Exception as e:
        print(f"  {R}❌ 范围闸取不到:{type(e).__name__}: {str(e)[:70]} —— 这条检查什么都没验{D}")
        return 1

    题 = 扫题()
    没身份 = [(fn, t) for fn, t, me, _ in 题 if me is None]
    验, 越, 查无, 豁免实况, 欠实况 = 0, [], [], {}, {}
    for fn, tid, me, 号 in 题:
        if me is None:
            continue
        for cid in 号:
            行 = 取客户(cid)
            if 行 is None:
                查无.append((fn, tid, cid)); continue
            验 += 1
            拒 = 闸(me, dict(行))
            if (fn, tid) in 身份待定欠债:
                欠实况[(fn, tid)] = 欠实况.get((fn, tid), False) or bool(拒)
            elif (fn, tid) in 故意越权:
                豁免实况[(fn, tid)] = 豁免实况.get((fn, tid), False) or bool(拒)
            elif 拒:
                越.append((fn, tid, cid, 行["shop"], f"{me.get('role')}·{me.get('shop') or me.get('no')}"))

    ck("题里点名的客户,那道题的身份看得见", not 越, 验,
       "" if not 越 else f"{len(越)} 处看不见 —— 模型被权限**正确地**挡住,成绩单却记成它没答好")
    for fn, tid, cid, shop, who in 越[:10]:
        print(f"       · {fn} {tid}:{cid} 在 {shop},身份是 {who}")
    if len(越) > 10:
        print(f"       …… 上面只印了 10 处,**一共 {len(越)} 处**")

    假豁免 = sorted(k for k in 故意越权 if not 豁免实况.get(k))
    ck("「故意越权」名单里的题,身份真的看不见", not 假豁免, len(故意越权) or 1,
       "" if not 假豁免 else f"这几道其实看得见(或题没了),从名单里删掉:{假豁免}")

    还清了 = sorted(k for k in 身份待定欠债 if not 欠实况.get(k))
    ck("已经看得见的,从身份欠债表里删掉了", not 还清了, len(身份待定欠债) or 1,
       "" if not 还清了 else f"这几道已经对上了(或题没了),删掉:{还清了}")
    剩 = sorted(k for k in 身份待定欠债 if 欠实况.get(k))
    if 剩:
        print(f"  {Y}ℹ️ 还欠 **{len(剩)} 道**(身份看不见点名的客户,是不是故意要题目设计来定):"
              f"{'、'.join(f'{a} {b}' for a, b in 剩)}{D}")
    if 没身份:
        print(f"  {Y}ℹ️ {len(没身份)} 道题身份静态读不出,这条没验到:"
              f"{'、'.join(f'{a} {b}' for a, b in 没身份[:6])}{D}")
    if 查无:
        print(f"  {Y}ℹ️ {len(查无)} 处客户号库里没有(只报不判,负向题里有故意编的):"
              f"{'、'.join(f'{a} {b} {c}' for a, b, c in 查无[:6])}{D}")
    print("  ℹ 抓不到:题面写姓名不写客户号的(重名,静态对不上人);题面是 f-string 现算的(静态读不出)")
    print("=" * 88)
    if FAIL:
        print(f"{R}❌ {len(FAIL)} 处不符合预期{D}")
        for f in FAIL:
            print(f"   · {f}")
        return 1
    print(f"{G}✅ 评测题点名的客户都在提问身份的范围里{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
