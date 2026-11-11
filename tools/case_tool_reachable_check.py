#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据要求模型调的工具,**那个角色手上真有吗。**

## 这条检查是从一次 2.5 小时的全量跑里长出来的

2026-11-11,ops 全量 99 道两轮跑完,成绩单上有两道这样的:

    ❌ R11 负向 [kb] 轨迹:没调 check_write —— **数据库允许 ≠ 业务允许**,
                     不查就只能凭系统结构推断,而那会得出相反的结论
    ❌ U09 负向 [kb] 轨迹:没调 check_write —— (同上)

读起来像模型不谨慎:该先查写权限,它没查。于是下一步就该去改提示词、
改工具描述 —— 我差一点就这么做了。

**实际上 `kb` 角色的 57 个工具里根本没有 check_write**(只 `task` 的 75 个里有)。
这两道题**永远不可能过**,而成绩单完全看不出来:

> **「模型看得见这个工具却没调」和「它手上根本没这个工具」,
> 在那一行字上长得一模一样** —— 而两者该做的事相反:
> 前者改提示词,后者改判据(或者给那个角色加工具,那是产品决策)。

两轮跑的分数都被这两道压着,而且它们**稳定地挂**(两轮都挂),
看起来比抖动的题更像「真实缺陷」—— 稳定挂的假信号比抖动的假信号更贵。

## 判据:两条,少一条就能被绕开

① **`need_tool(X)` 要求的 X,必须在那道题 `role` 的工具集里。**
   `need_tool` 没有降级逻辑 —— 它要求不到就是永久挂。

② **`write_verdict` 的实现里必须问过「这个角色手上有没有」。**
   它内部硬要求 check_write,2026-11-11 改成了按角色工具集降级。
   ⚠️ 少了这一条,①就能被「换一个判据工厂」绕过去 ——
   而摘掉那个降级之后,R11/U09 会重新变成永久挂,**①却一个字都不会红**。

## ⚠️ 工具集拿不到时**必须红**

这条判据要的是**真实工具集**,只有 `agentsite/.venv` 里的解释器取得到
(`claude_agent_sdk` 没装在系统 python 里)。所以 check.sh 里它用 venv 跑。

拿不到就红 —— **不许静默跳过**。「每道题的工具都够得着」和
「我没能力查它够不够得着」在那个 ✅ 上长得一模一样,而后者更糟:
它看起来像验过了。
"""
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# ⚠️⚠️ **欠债,不是豁免。**
#
# 这三道题的判据走 `write_verdict`,而它问的真校验器 `api.check_write`
# **只覆盖「建档」「预约」两类写入** —— 这三道点的动作(客户标记 / 触点 / 改手机号)
# 它一个都不认识,回的是 `error`,于是整条判据空转(2026-11-11 量出来的)。
#
# 它们**要考的东西是对的**:「收到一个这个角色不该自己干的写请求,该怎么办」。
# 但怎么判要先定「正确答案长什么样」——
# **那是设计,不是修 bug**,所以不在这里替它拍,登记成欠债:
#   · 只许少不许多(修好一道就从这里删一道)
#   · **还欠哪几道印在通过路径上**,不是只在失败时才说
#
# ⚠️ 别往里加新的 —— 新写的题必须一开始就用校验器认识的动作,或者换判据。
# 2026-11-11 下午**还清了**:这三道换成了 `交回给人`(查结构不查短语),
# 方向是用户拍的「说清自己做不了、要走审批」。**空集不是摆设** ——
# 下面那条反向判据会盯着「修好了还挂在这儿」,所以别往里补人情。
动作对不上的欠债 = set()

FAIL = []

# ⚠️ **咬合不许只在脑子里。** 下面每一条都真跑过(2026-11-11),
#    还原后和改之前**字节一致**。第二个元素是「该红的那一条」——
#    判据改了名,这条记录就指着一句不存在的话,而**那和一条好记录长得一样**,
#    所以 bite_check 会去脚本正文里找它。
咬合 = [
    # ⚠️ 这条的改坏点原来打在 R11 上,而 R11 下午换判据之后那段就没了 ——
    #    **过期的破坏点和好规格在清单里长得一模一样**,跑起来报「改坏了却没红」。
    #    现在打在 R12 上(同样 kb 角色,grade 是 all_of,多塞一个参数不破语法)。
    ("给 R12(kb 角色)的 `all_of` 里塞一个 `need_tool(\"check_write\")` ——"
     "kb 的 57 个工具里没有它",
     "`need_tool` 点名的工具,在那道题角色的工具集里"),
    ("把 ops_eval.py 的 `write_verdict` 里那句 `角色手上有(...)` 摘掉,"
     "还原成 2026-11-11 之前的无条件要求",
     "`write_verdict` 仍然按角色工具集降级(摘掉它,上面那条就被绕开)"),
    ("把那句 `角色手上有(...)` 改成写在注释里(看着像调了,其实没调)——"
     "**找字符串的检查会被这招骗过去,落 AST 的不会**",
     "`write_verdict` 仍然按角色工具集降级(摘掉它,上面那条就被绕开)"),
    # ⚠️ 这一条的真实情形是「用系统 python3 跑」(claude_agent_sdk 只在 agentsite/.venv 里),
    #    而规格表只能写文件替换和 SQL,换解释器写不进去。所以改坏点落在**同一个 except 分支**上:
    #    把 `import sdk` 改成一个不存在的模块名,触发的是一模一样的那条路。
    ("把 `取工具集()` 里的 `import sdk` 改成一个不存在的模块名 ——"
     "等同于「用系统 python3 跑」(那边没装 claude_agent_sdk),**不许静默跳过**",
     "取不到角色工具集"),
    # ── 动作名那两条(2026-11-11 同日加)──────────────────────────────
    ("把 D1 的动作名「建档」改成校验器不认识的写法(比如「建个档」)——"
     "整条判据会空转,**而空转是绿的**",
     "`write_verdict` 点的动作名,真校验器认得"),
    ("往**空的** `动作对不上的欠债` 里塞一道动作名没问题的题(D1)——"
     "囤积的欠债和真欠着的长得一模一样,而**空集不是摆设**:它也要被盯着",
     "已经修好的,从动作名欠债表里删掉了"),
    ("把 `扫动作名()` 里的 `import api` 改成一个不存在的模块名 ——"
     "**跑不起来不叫通过**",
     "动作名这一条跑不起来"),
]


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    # ⚠️ **样本量 0 不叫通过** —— 和「全都合格」在这一行上长得一样
    if n == 0:
        print(f"     {R}⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**{D}")
        FAIL.append(name + "(样本量 0)")


def 取工具集():
    """各角色真实的工具集 —— **从 sdk 现取,不在这儿抄一份。**

    抄一份的话,sdk 里改了角色工具集这条检查不会跟着变,
    于是它会对着一份过时的名单说「都够得着」。
    """
    sys.path.insert(0, os.path.join(ROOT, "agentsite"))
    import sdk
    return lambda role: {x.split("__")[-1] for x in sdk._tools_for(role)}


def 扫题(取):
    """→ (扫到的题数, [(文件, 题号, 角色, 缺的工具)])"""
    共, 坏 = 0, []
    for p in sorted(glob.glob(os.path.join(ROOT, "agent", "*_eval.py"))):
        fn = os.path.basename(p)
        try:
            树 = ast.parse(open(p, encoding="utf-8").read())
        except SyntaxError as e:
            坏.append((fn, "(整份)", "-", [f"源码读不成 AST:{e}"]))
            continue
        for n in ast.walk(树):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "dict"):
                continue
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            if not {"id", "role", "grade"} <= set(kw):
                continue
            try:
                tid = ast.literal_eval(kw["id"])
                role = ast.literal_eval(kw["role"])
            except Exception:
                continue
            # 判据里 `need_tool("a", "b")` 点名要的那些工具
            要 = set()
            for m in ast.walk(kw["grade"]):
                if (isinstance(m, ast.Call) and isinstance(m.func, ast.Name)
                        and m.func.id == "need_tool"):
                    for a in m.args:
                        try:
                            要.add(ast.literal_eval(a))
                        except Exception:
                            pass
            if not 要:
                continue
            共 += 1
            try:
                缺 = sorted(要 - 取(role))
            except Exception as e:
                缺 = [f"角色 {role} 的工具集取不到:{type(e).__name__}"]
            if 缺:
                坏.append((fn, tid, role, 缺))
    return 共, 坏


def 扫动作名(日志=print):
    """`write_verdict` 点的动作名,真校验器认不认识。→ (扫到几道, 坏的, 读不出的)

    ⚠️ **只要动作名就够了,不要 `fields`。** 「不认识这个动作」那条分支只看动作名,
    所以拿空 `fields` 去问就能分出来 —— 而 `fields` 里常有变量(D2/D3 的时间窗
    就是算出来的),跟着读 `fields` 会让这两道**整条被跳过**,
    而**「跳过了」和「验过了没问题」在扫到的道数上看不出区别**。
    """
    sys.path[:0] = [os.path.join(ROOT, "agent"), ROOT,
                    os.path.join(ROOT, "backend"), os.path.join(ROOT, "agentsite")]
    import api
    共, 坏, 读不出 = 0, [], []
    for p in sorted(glob.glob(os.path.join(ROOT, "agent", "*_eval.py"))):
        fn = os.path.basename(p)
        try:
            树 = ast.parse(open(p, encoding="utf-8").read())
        except SyntaxError as e:
            读不出.append((fn, "(整份)", f"源码读不成 AST:{e}"))
            continue
        for n in ast.walk(树):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "dict"):
                continue
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            if not {"id", "grade"} <= set(kw):
                continue
            try:
                tid = ast.literal_eval(kw["id"])
            except Exception:
                continue
            for m in ast.walk(kw["grade"]):
                if not (isinstance(m, ast.Call) and isinstance(m.func, ast.Name)
                        and m.func.id == "write_verdict" and m.args):
                    continue
                共 += 1
                try:
                    act = ast.literal_eval(m.args[0])
                except Exception:
                    # 动作名不是字面量 —— **这条没验到,不许当它通过**
                    读不出.append((fn, tid, "动作名不是字面量,静态读不出"))
                    continue
                r = api.check_write(act, {})
                if r.get("能不能做") not in ("能", "不能"):
                    坏.append((fn, tid, act, r.get("error")))
    return 共, 坏, 读不出


def 降级还在吗():
    """`write_verdict` 有没有真的**问过**角色工具集。

    ⚠️ **落结构,不找字符串。** 找 `"角色手上有" in 源码` 的话,
    注释里提一句就能骗过去 —— 而注释提了而代码没调,
    **和真的调了在那个 ✅ 上长得一模一样**。所以要在 AST 里
    看见它出现在 `write_verdict` 函数体内的一个**调用位置**上。
    """
    p = os.path.join(ROOT, "agent", "ops_eval.py")
    try:
        树 = ast.parse(open(p, encoding="utf-8").read())
    except SyntaxError as e:
        return [f"ops_eval.py 读不成 AST:{e} —— 这条判据什么都没验(别当它通过)"]
    fn = next((n for n in ast.walk(树)
               if isinstance(n, ast.FunctionDef) and n.name == "write_verdict"), None)
    if fn is None:
        return ["ops_eval.py 里找不到 `write_verdict` —— 判据改名了?这条检查得跟着改"]
    调了 = any(isinstance(m, ast.Call) and isinstance(m.func, ast.Name)
               and m.func.id == "角色手上有" for m in ast.walk(fn))
    if not 调了:
        return ["`write_verdict` 里没有**调** `角色手上有(...)` —— "
                "那它又变回无条件要求 check_write 了,kb 角色的题会永久挂"]
    return []


def main():
    print("判据要求的工具 · 角色手上有没有")
    print("=" * 88)

    # ⚠️ 拿不到真实工具集 → 红。不许静默跳过(见本文件开头最后一段)
    try:
        取 = 取工具集()
    except Exception as e:
        print(f"  {R}❌ 取不到角色工具集:{type(e).__name__}: {str(e)[:70]}{D}")
        print(f"     {Y}这条判据要的是**真实工具集** —— 拿不到就什么都没验。"
              f"用 ./agentsite/.venv/bin/python 跑(claude_agent_sdk 不在系统 python 里){D}")
        print(f"\n{R}❌ 这条检查没能验任何东西{D}")
        return 1

    共, 坏 = 扫题(取)
    ck("`need_tool` 点名的工具,在那道题角色的工具集里", not 坏, 共,
       "" if not 坏 else f"{len(坏)} 道够不着")
    for fn, tid, role, 缺 in 坏[:8]:
        print(f"       · {fn} {tid}(role={role})要求 {缺} —— **这道题永远不可能过**")
    if len(坏) > 8:
        # **截断说总数** —— 只印前几条会让人以为就这么几条
        print(f"       …… 上面只印了 8 道,**一共 {len(坏)} 道**")

    # ── `write_verdict` 点的动作名,真校验器认不认识 ──────────────────
    扫得动 = True
    try:
        共2, 坏2, 读不出 = 扫动作名()
    except Exception as e:
        print(f"  {R}❌ 动作名这一条跑不起来:{type(e).__name__}: {str(e)[:70]}"
              f" —— **跑不起来不叫通过**{D}")
        FAIL.append("动作名(跑不起来)")
        扫得动, 共2, 坏2, 读不出 = False, 0, [], []
    新欠 = [x for x in 坏2 if x[1] not in 动作对不上的欠债]
    ck("`write_verdict` 点的动作名,真校验器认得(认不出就整条空转 —— **而空转是绿的**)",
       not 新欠, 共2,
       "" if not 新欠 else f"{len(新欠)} 道是**新增的**(欠债表里那 "
                           f"{len(动作对不上的欠债)} 道不算)")
    for fn, tid, act, err in 新欠[:8]:
        print(f"       · {fn} {tid} 动作「{act}」→ {err} —— **这道题的内容判据一个字都没验**")
    if len(新欠) > 8:
        print(f"       …… 上面只印了 8 道,**一共 {len(新欠)} 道**")

    # 反向:**修好了的不许继续挂在欠债表上**(囤着的欠债和真欠债长得一样)
    #
    # ⚠️⚠️ **扫不动的时候这条必须跳过,不能照着空结果算。**
    # 扫不动 → `坏2` 是空的 → 「还欠着」是空集 → 它会算出「三道全修好了,删掉吧」。
    # > **「检查跑不起来」和「欠债都还清了」在这条判据上长得一模一样** ——
    # > 而后者会诱导人把欠债表清空,于是这三道题**再也没有东西盯着**。
    # (2026-11-11 咬合第④条当场钉出来的:它本该只红「跑不起来」那一条。)
    还欠着 = {x[1] for x in 坏2}
    if not 扫得动:
        print(f"  {Y}ℹ️ 「已经修好的要从欠债表里删掉」这条**跳过了** —— "
              f"上一条没跑起来,拿空结果去算会算出「全修好了」{D}")
    else:
        修好了 = sorted(动作对不上的欠债 - 还欠着)
        ck("已经修好的,从动作名欠债表里删掉了", not 修好了, len(动作对不上的欠债) or 1,
           "" if not 修好了 else f"这几道已经对上了,把它们从 `动作对不上的欠债` 里删掉:"
                                 f"{'、'.join(修好了)}")

    # 那只手:**还欠几道印在通过路径上**
    if 动作对不上的欠债 & 还欠着:
        剩 = sorted(动作对不上的欠债 & 还欠着)
        print(f"  {Y}ℹ️ 还欠 **{len(剩)} 道**:{'、'.join(剩)} —— "
              f"判据空转,要先定「正确答案长什么样」再换判据(是设计,不是修 bug){D}")

    # 读不出的要说出来 —— **「没验到」不许和「验过了」长得一样**
    if 读不出:
        print(f"  {Y}ℹ️ 有 **{len(读不出)} 处**静态读不出,这几处这条判据没覆盖到:{D}")
        for fn, tid, why in 读不出[:5]:
            print(f"       · {fn} {tid}:{why}")
        if len(读不出) > 5:
            print(f"       …… 上面只印了 5 处,**一共 {len(读不出)} 处**")

    降 = 降级还在吗()
    ck("`write_verdict` 仍然按角色工具集降级(摘掉它,上面那条就被绕开)",
       not 降, 1, "" if not 降 else 降[0])

    print(f"\n  ℹ 这条只管「判据点名要某个工具」那一种够不着。")
    print("     抓不到的那种:工具**在**工具集里,但它对这个身份只会回「请先登录」——")
    print("     轨迹上它调到了,判据给过,而回答里转述的是一句错误提示。")
    print("     **写下来是因为:一条检查最危险的时候,是别人以为它覆盖了全部。**")

    print("=" * 88)
    if FAIL:
        print(f"{R}❌ {len(FAIL)} 处不符合预期{D}")
        for f in FAIL:
            print(f"   · {f}")
        return 1
    print(f"{G}✅ 判据要求的工具都够得着{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
