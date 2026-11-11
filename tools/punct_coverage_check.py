#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判分器对照集有没有接上「标点不变量」—— **棘轮,不是地板。**

## 为什么有这条检查

2026-11-11:`agent/textmatch.py` 的 `STOP`(小句边界字符表)里**没有全角逗号** ——
中文里最常用的那个标点。于是否定的作用域跨过逗号,把前一小句的否定算到后一小句上。
线上守卫因此**漏拦了 6 类**,而守卫那 175 条用例**一直全绿**:

> **因为它们的逗号全是半角的。** 全文全角逗号 0 个。
> 守卫在一种真实数据里根本不会出现的标点形态上验过,然后所有人以为它守住了。

量过:31 份 judgetest 的字符串字面量里,半角逗号 **2052** 个、全角 **18** 个(0.9%)。
**判分规则在真实数据标点上的行为,从来没被对照集验过。**

修法是一份公共派生器 `agent/punct_invariant.py`:把用例文本里的半角逗号换成全角,
判定必须不变。各家 judgetest 一行就能接上。

## 为什么这条检查不要求「全部接完」

28 份还没接。要求全接会立刻红一片,而红一片的检查会被人关掉 ——
**所以这里只守两件**:① 已经接上的**不许变少**(棘轮);② **还剩几份看得见**。

⚠️ 项目里有两个阈值正是因为「没人回来看它」而躺了两个月
(交接门禁写死 80% 却从没触发过、影响面下限 21 而实际 336)。那条教训是:

> 判据不是「这个数多老」,是**「有没有东西在推它」** —— 而且那只手的输出得看得见。

所以这个文件里的 `已接下限` **就是那个要被推的数**:接上一份就该把它加一。
下面每次跑都会把「实际接了几份」和「下限是几」一起印出来,
实际比下限高就当场印出该改成几 —— **提示印在通过路径上,不是只在失败时才说。**
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# ⚠️ **棘轮:接上一份就把这个数加一。** 别往下调 —— 往下调就等于把这条检查关掉。
#    2026-11-11 立:guards_test(131 条用例) / ops_eval_judgetest(219) / tool_eval_judgetest(37)
已接下限 = 21     # 11-11 夜:15→21(其间并行会话和我陆续接上的,含工坊报工 workshop 11 条);实数以本检查印的为准
                  # 11-11 下午:+negative(**出事那个判断就是它守的**,试纸钉出越权被放过)
                  # 11-11 傍晚:+talk、fitting、rating、store_report、refund_sets(19/10/31/25/13 条)
                  #            —— 走 textmatch 的我那 5 份**全接完了**,剩下 5 份是并行会话的。
                  #            ⚠️ 这一轮做了**对照实验**(内存里把全角逗号从 `textmatch.STOP`
                  #            摘掉,不动磁盘):**只有 talk 当场红**,另外四份一条都不变。
                  #            查清了原因,而它改变了「钉不出」这件事的含义 ——
                  #            见下面「两个粒度」那一段。
                  #            +member、+role(试纸:role 钉出**答对被判挂**的误报;
                  #            member 钉不出 —— 当前用例没覆盖到,接入只防未来,**如实记**)
                  #            +report:⚠️ **接上当场就红** —— 判据模式串里写死了
                  #            半角逗号(`「对,」`),真实全角输入下**顺着错误前提答的回答被放过**。
                  #            这是**第五类**:和「小句边界表缺全角」根因不同,修那张表治不了它
                  # 11-11 午后:+liability、growth、vision(17 / 21 / 13 条)——
                  #            ⚠️ 这三份**试纸钉不出**:把 `textmatch.STOP` 的全角逗号去掉,
                  #            它们的判定一条都不变。而**同一张试纸在同一轮里对
                  #            role / negative 当场钉出来了**(role:答对被判挂;
                  #            negative:真的越权被放过)—— 所以「钉不出」是真的钉不出,
                  #            不是试纸失效。**这三份接入防的是未来,不是发现了当下的 bug。**
                  #            > 「试纸钉不出」和「试纸本身失效」,在那个 ✅ 上长得一模一样 ——
                  #            > 分开它们的唯一办法是**同一轮里打一个已知会钉出的对照**。

# ⚠️ 咬合:前两条 2026-11-11 真跑过(各红在棘轮那条、还原后字节一致);
#    后两条是同一天补齐记录时跑的。
咬合 = [
    ("把某一份已接的 judgetest 里 `_pi.查(...)` 整段摘掉",
     "**棘轮只许涨**。谁把它摘了?"),
    ("只留 `import punct_invariant` 而把 `_pi.查(...)` 删掉 ——"
     "**import 了而没调,和没 import 在那个 import 行上长得一样**,而前者更糟",
     "**棘轮只许涨**。谁把它摘了?"),
    ("把 `扫判分器对照()` 里的目录改成不存在的(扫到 0 份)",
     "一份判分器对照都没扫到 —— 没扫到东西,不是通过"),
    ("往 `豁免` 里加一份**已经接上**的 judgetest(豁免名单囤积)",
     "豁免名单该清了"),
]

# 没有中文回答文本可换的,在这里写清理由(只许少不许多 —— 新加的默认必须接)
豁免 = {
    # "xxx_judgetest.py": "这一份只验结构/数字,用例里没有模型回答的中文句子",
}


def 扫判分器对照():
    """找出所有判分器对照集 —— `agent/*judgetest*.py` 和 `agentsite/*_test.py`。"""
    出 = []
    for 目录, 模式 in (("agent", r".*judgetest.*\.py$"),
                       ("agentsite", r".*_test\.py$")):
        d = os.path.join(ROOT, 目录)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if re.match(模式, f):
                出.append(os.path.join(目录, f))
    return 出


def 接了吗(相对路径):
    """这一份有没有真的**调**派生器 —— 不是只 import 了。

    ⚠️ 只查 `import punct_invariant` 是不够的:import 了而没调,
    和没 import **在那个 import 行上长得一样**,而前者更糟 ——
    它看起来像接好了。所以要同时看见那个调用。
    """
    try:
        with open(os.path.join(ROOT, 相对路径), encoding="utf-8") as f:
            t = f.read()
    except OSError:
        return False
    有 = "punct_invariant" in t
    # 调用长相:`_pi.查(` / `punct_invariant.查(`(别只认一种别名)
    调 = re.search(r"(?:punct_invariant|_pi|pi)\s*\.\s*查\s*\(", t) is not None
    return 有 and 调


def 走标点表吗(相对路径):
    """这一份对照集**守的那个判分器**,走不走 `textmatch`(那张小句边界表)。

    ⚠️ **这决定了优先级,不是装饰。** 2026-11-11 那个 bug 的病灶就在
    `textmatch.STOP` 里 —— 判分器不走它的话,换个逗号本来就不该有差别;
    走它的那些才是**真正的风险面**。

    ## ⚠️⚠️ 两个粒度 —— 「走 textmatch」还不够细(2026-11-11 查实)

    `textmatch` 有**两套**小句边界,源码 360 行自己写着:

        in_clause / negated   **逗号级**,用 `STOP`(含全角逗号「,」、顿号「、」)
        in_sentence / _句     **句号级**,用 `HARD = "。!?!?\n\r"` —— **一个逗号都没有**

    **标点不变量这张试纸换的是逗号,所以它只对「逗号级」的判据钉得出东西。**
    当天实测:talk(走 `negated`)当场红;refund_sets 三处全是 `in_sentence`、
    rating 用自己的句号级 `_句()`、fitting 用 `re.split("(?<=[。!!\n])")`、
    store_report 只用 `mentions` —— **四份一条都不变**。

    > **「这张试纸钉不出它」和「这个判据对标点安全」是两件事。**
    > 钉不出只说明:**这张试纸换的那个标点,不在这个判据的边界表里。**

    ⚠️ **那为什么句号级的也要接?** 防的是**粒度被人悄悄改掉** ——
    哪天有人把一处从 `in_sentence` 改成 `in_clause`(或反过来),这条试纸会红。
    所以这条检查**不按粒度放宽**「该接」的判定:句号级的照旧该接。
    ⚠️ 也**别**因为这段话就去把某一份从「风险面」里摘出来 ——
    摘的那一刻,「它是句号级所以安全」和「它改成逗号级了而没人看见」就又长得一样了。

    > **「还剩 30 份」和「还剩 16 份有风险的 + 14 份风险低的」,
    > 在那个计数上长得一样** —— 而前者没法排优先级,于是谁都不知道先接哪个。

    (实测:`negative` 走它,试纸一钉就红 —— 在 bug 状态下一个**真的越权**的回答
     会被判成「内容对」。所以这个分级不是理论上的。)

    ⚠️⚠️ **这一段只影响打印,不产生任何判定 —— 所以咬合守不住它。**
    把下面那两个 `return None` 改成 `return False`(认不出就当低风险),
    **不会有任何东西变红**,而那 3 份会从视野里消失。
    没为它加判定是故意的:要求「对照集的名字必须能对上被测文件」是个
    过紧的约束(命名本来就该自由)。**写下来是因为:
    一条检查最危险的时候,是别人以为它覆盖了全部。**
    """
    m = os.path.basename(相对路径)
    for 尾 in ("_judgetest.py", "_test.py"):
        if m.endswith(尾):
            被测 = m[: -len(尾)]
            break
    else:
        return None                      # 认不出名字 —— **不猜**,返回「不知道」
    for d in ("agent", "agentsite", "backend"):
        f = os.path.join(ROOT, d, f"{被测}.py")
        if os.path.exists(f):
            try:
                t = open(f, encoding="utf-8").read()
            except OSError:
                return None
            return ("import textmatch" in t) or ("textmatch as tm" in t)
    return None                          # 找不到被测文件 —— 同样不猜


def main():
    print("判分器对照 · 标点不变量接入情况")
    print("=" * 88)
    全 = 扫判分器对照()
    坏 = 0

    # ⚠️ **样本量 0 要红** —— 「都接上了」和「一份都没扫到」在输出上长得一样
    if not 全:
        print(f"  {R}❌ 一份判分器对照都没扫到 —— 没扫到东西,不是通过{D}")
        return 1

    接了 = [f for f in 全 if 接了吗(f)]
    没接 = [f for f in 全 if f not in 接了 and os.path.basename(f) not in 豁免]

    print(f"  扫到 {len(全)} 份判分器对照,其中**真的调了派生器**的 {len(接了)} 份"
          f"(豁免 {len(豁免)} 份)")

    # ① 棘轮:已接的不许变少
    if len(接了) < 已接下限:
        坏 += 1
        print(f"  {R}❌ 接上派生器的从 {已接下限} 份掉到了 {len(接了)} 份 —— "
              f"**棘轮只许涨**。谁把它摘了?{D}")
        for f in sorted(set(全) - set(接了)):
            if os.path.basename(f) not in 豁免:
                print(f"       · {f}")
    else:
        print(f"  {G}✅ 接上派生器的没变少(下限 {已接下限},现在 {len(接了)} 份){D}")

    # ② 那只手:实际比下限高就当场说该改成几 —— **印在通过路径上**
    if len(接了) > 已接下限:
        print(f"  {Y}ℹ️ 已经接到 {len(接了)} 份了 —— "
              f"把本文件的 `已接下限` 改成 {len(接了)}{D}"
              f"(不改的话,下次有人摘掉 {len(接了) - 已接下限} 份也不会红)")

    # ③ 还剩几份看得见(**截断要说总数** —— 11-11 刚修过同一个病)
    if 没接:
        # **带风险分级**:走 textmatch 的才是真正可能有那个 bug 的
        险 = [f for f in 没接 if 走标点表吗(f) is True]
        低 = [f for f in 没接 if 走标点表吗(f) is False]
        未知 = [f for f in 没接 if 走标点表吗(f) is None]
        print(f"  {Y}ℹ️ 还有 **{len(没接)} 份**没接(这条检查不要求全接,"
              f"但别让它从视野里消失):其中**走 `textmatch` 的 {len(险)} 份**"
              f"(真正的风险面,先接这些)、不走的 {len(低)} 份"
              + (f"、认不出被测文件的 {len(未知)} 份(**不猜**)" if 未知 else "") + D)
        for f in 险[:8]:
            print(f"       ⚠️ {f}(走 textmatch)")
        if len(险) > 8:
            print(f"       …… 上面只印了 8 份**有风险的**,这一类**一共 {len(险)} 份**")
        if 未知:
            for f in 未知[:3]:
                print(f"       ? {f} —— 找不到它守的那个判分器,**没当成低风险**")
    else:
        print(f"  {G}✅ 全部都接上了 —— 可以把这条检查收成「只许全接」{D}")

    # ④ 豁免名单不许囤积:写了理由的文件得真的存在,而且不许已经接上了还挂在豁免里
    陈 = [f for f in 豁免
          if not os.path.exists(os.path.join(ROOT, "agent", f))
          and not os.path.exists(os.path.join(ROOT, "agentsite", f))]
    已接却仍豁免 = [os.path.basename(f) for f in 接了 if os.path.basename(f) in 豁免]
    if 陈 or 已接却仍豁免:
        坏 += 1
        print(f"  {R}❌ 豁免名单该清了{D}"
              f"{'  已经不存在的:' + '、'.join(陈) if 陈 else ''}"
              f"{'  已经接上却还挂着豁免的:' + '、'.join(已接却仍豁免) if 已接却仍豁免 else ''}")

    print("=" * 88)
    if 坏:
        print(f"{R}❌ 标点不变量接入 {坏} 处不符合预期{D}")
        return 1
    print(f"{G}✅ 标点不变量接入符合预期{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
