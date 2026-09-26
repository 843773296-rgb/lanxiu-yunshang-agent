#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写「已经发生的事」的时间时,不许用机器时钟

## 这条检查是怎么来的(2026-09-26)

`backend/booking.py` 的 `_now()` 是 `datetime.datetime.now()` —— **机器时钟**。
它写出来的 `schedule.assigned_at` 落在机器的今天,而演示世界停在别的日子。
然后每日平移把这条记录**跟着往后挪一天**,它就落到了世界的未来。

> **这个 bug 不会自愈:平移每跑一次,它就往未来多推一天。**
> 而第二天的红看起来和今天一模一样,于是真正的原因会被当成「数据又漂了」。

门禁 C4 抓的是**症状**(有记录在未来)。这条抓**原因**:
一个文件如果既写「已发生的事」的时间列、又只有机器时钟,它迟早造出那种记录。

## 范围:只管「已发生的事」那几对(表, 列)

`tools/shift_world.py` 的列清单是**运行时从库里按值发现**的(它自己写着
「看值不看名」),文件里没有全量静态清单可读 —— 硬凑一份就是第二处表示,而它会漂。
所以范围来自 `worldclock.已发生的时间列`,和 C4 同一份。

## 判据:表名和列名出现在**同一条写语句**里

⚠️ 第一版拿**裸列名**去匹配整个文件文本,于是 `ts` / `note` / `db` 全中
(`db` 是个变量名),21 个文件被报成坏的。
**判据「恰好长这样」而不是按含义** —— 这正是这个仓库记了一整页的那类错,
而我在一条专门防这类错的检查里又犯了一次。

## 不是所有 `datetime.now()` 都该换

会话过期、审计时间戳、耗时统计记的是**真实世界**发生的事,本来就该用机器时钟。
判据是「这一列会不会被平移」,不是「这个函数叫什么」。
拿不准的写进 `豁免` 并说明理由;**棘轮**锁住条数,豁免不许悄悄囤积。
"""
import io, os, re, sys, tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import worldclock as WC

咬合 = [
    ("把 booking.py 的 _now() 改回 datetime.datetime.now()", "写「已发生的事」那几列时用世界时钟"),
    ("往豁免里多加一条",                                      "豁免不许囤积"),
    ("把豁免的理由清空",                                      "每条豁免都写了理由"),
    ("往豁免里写一个不存在的文件名",                          "豁免指向的文件都还在"),
]

_机器时钟 = re.compile(r"datetime\.now\(\)|datetime\.datetime\.now\(\)|"
                      r"date\.today\(\)|datetime\.date\.today\(\)")


def 只留代码(源):
    """把注释和文档字符串**涂成空白**,其余原文一字不动。

    ⚠️ 两个坑,都是咬合抓到的:

    ① **第一版匹配整个文件文本**(含注释)。于是把 `booking._now()` 改回机器时钟后
       它照样通过 —— 那个函数的 docstring 里写着「worldclock」。
       **一个只在注释里提到世界时钟的文件被判成了合格。**

    ② 第二版改成「把 token 用换行拼起来」。结果 `datetime.datetime.now()` 变成
       `datetime\n.\ndatetime\n.\nnow\n(\n)` —— **正则再也匹配不上**,
       于是机器时钟一个都检测不到,检查又变成了永远绿。
       拼接会毁掉表达式:**判据要在原文上跑**。

    所以这里保留原文,只把要忽略的 token 的那一段换成同长度的空格。
    """
    行 = 源.splitlines(keepends=True)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(源).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # 解析不了就**说出来**,不静默退回整文本匹配 ——
        # 退回去的话,这条检查会在解析失败的文件上悄悄变松
        return None
    要涂 = []
    上一个 = None
    for t in toks:
        if t.type == tokenize.COMMENT:
            要涂.append(t)
        elif t.type == tokenize.STRING and 上一个 in (
                None, tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT):
            要涂.append(t)                      # 独立成句的字符串 = docstring
        if t.type not in (tokenize.COMMENT,):
            上一个 = t.type
    for t in 要涂:
        (r1, c1), (r2, c2) = t.start, t.end
        for r in range(r1, r2 + 1):
            if r - 1 >= len(行): break
            L = 行[r - 1]
            a = c1 if r == r1 else 0
            b = c2 if r == r2 else len(L.rstrip("\n"))
            尾 = "\n" if L.endswith("\n") else ""
            体 = L.rstrip("\n")
            行[r - 1] = (体[:a] + " " * max(0, b - a) + 体[b:]) + 尾
    return "".join(行)


# 「表名」后面 400 字以内出现「列名」→ 算这条语句写了这一列。
#
# ⚠️ **尾部用不消耗的前向查找 `(?=...)`。** 第一版把尾部写成普通分组,
# 于是第一条匹配的 400 字窗口**把后面那条 INSERT 吞掉了** ——
# `finditer` 从它结尾继续,再也看不到第二条语句。
# 实测:`backend/booking.py` 里有两条 INSERT(appointment 和 schedule),
# 判据只认出了第一条,而**要查的恰好是第二条**。咬合抓到的。
# 世界时钟的写法(用了这几种之一就算过)
_世界时钟 = re.compile(r"worldclock|seed\.TODAY|_业务今天|world_today")

_写语句 = re.compile(
    r"(?:INSERT\s+INTO|insert\s+into|UPDATE|update)\s+[\"'`]?(\w+)(?=([^;]{0,400}))", re.S)

豁免 = {
    "auth.py": "会话创建/过期记的是**真实世界**的事:一个演示世界里「昨天」登录的会话,"
               "在真实时间里已经过期了。用世界时钟反而会让会话永不过期",
}
# ⚠️ **棘轮的上界必须写死。** 第一版写的是 `上限 = len(豁免)` ——
# 加一条豁免,上限跟着涨,**这条检查永远不可能红**。
# 又是同源谬误:约束的上界从被约束的东西本身算出来。咬合当场抓到。
# 要加豁免就得连这个数字一起改,而改数字会在 review 里被看见。
上限 = 1

过, 挂 = [], []
def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:200] if 补 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        挂.append(名 + "(样本量 0)")


对们 = list(WC.已发生的时间列)
ck("范围来自 worldclock.已发生的时间列(和 C4 同一份,不在这儿抄第二份)",
   len(对们) >= 8, len(对们), f"{len(对们)} 对(表, 列)")

坏, 扫过, 查到的对 = [], 0, set()
for fn in sorted(os.listdir(HERE)):
    if not fn.endswith(".py") or fn.endswith("_check.py"): continue
    if fn == "seed.py":
        # seed 造数用自己的基准日 T(确定性),**不读也不该读世界时钟**
        continue
    源 = open(os.path.join(HERE, fn), encoding="utf-8").read()
    代码 = 只留代码(源)
    if 代码 is None:
        坏.append(f"{fn}:剥注释时解析失败 —— **不当它通过**(说不清就不放行)")
        continue
    t = 代码
    命中 = set()
    for m in _写语句.finditer(t):
        表, 尾 = m.group(1), m.group(2)
        for tb, col, cn, _pk in 对们:
            if 表 == tb and re.search(r"\b" + re.escape(col) + r"\b", 尾):
                命中.add(f"{tb}.{col}({cn})")
    if not 命中: continue
    扫过 += 1
    查到的对 |= 命中
    if fn in 豁免: continue
    if not _机器时钟.search(t): continue          # 压根没用机器时钟
    if _世界时钟.search(t): continue              # 用了世界时钟就算过
    坏.append(f"{fn}:写 {sorted(命中)[:3]} 却只用机器时钟")

ck("写「已发生的事」那几列时用世界时钟(否则平移把记录推到未来,而且不会自愈)",
   not 坏, 扫过, 坏[:3])
# **样本量要报出来**:如果一个写这些列的文件都没扫到,说明判据坏了,不是「全都对」
ck("真的扫到了写这些列的地方(一个都没扫到 = 判据坏了,不是全都对)",
   扫过 >= 3, 扫过, f"涉及 {len(查到的对)} 对:{sorted(查到的对)[:4]}")

ck(f"豁免不许囤积(上限 {上限},要加就得连这行一起改)", len(豁免) <= 上限, len(豁免),
   sorted(豁免))
无理由 = [k for k, v in 豁免.items() if len((v or "").strip()) < 10]
ck("每条豁免都写了理由", not 无理由, len(豁免), 无理由)
幽灵 = [k for k in 豁免 if not os.path.exists(os.path.join(HERE, k))]
ck("豁免指向的文件都还在(指向已删文件的豁免是一条永远生效的后门)", not 幽灵,
   len(豁免), 幽灵)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
if 挂:
    for x in 挂: print("   ·", x)
sys.exit(1 if 挂 else 0)
