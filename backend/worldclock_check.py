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

# ── 第二条判据:**模块的时间源不许是机器时钟** ────────────────────
#
# 并行会话 2026-09-26 指出第一条判据的盲区,而他指对了:
# 第一条扫的是「**谁直接写那几列**」,而 `pickup_write` 把时间算好之后
# **传给 `factory_inbox.记事件()`** 去写 —— 算时间的和写那一列的不是同一个模块,
# 按写入扫的检查看不见它。它因此漏掉了第七个写口(124 条日期错的订单事件)。
#
# 顺着这句话换一头想:**真正的缺陷不是「谁写那一列」,是「这个模块的时间源是机器时钟」。**
# 一个模块只要有个 `_now()` 返回机器时间,它写到哪儿、传给谁都会出错 ——
# 而「模块有没有一个机器时钟的时间源」**扫得到,而且比扫写入简单**。
#
# 换这一头之后当场又多抓到两个(ops.py / repair_write.py),它们都不直接写清单里的列。
时间源名 = re.compile(r"^\s*def\s+(_?now|_?today|当下|今天|_?业务今天|_?世界今天)\s*\(")
# 这些文件的时间源**本来就该是机器时钟**,逐个写明理由。
时间源豁免 = {
    "worldclock.py": "它就是那个换算的地方 —— 世界按天平移,一天之内的钟点是真的,"
                     "所以 `当下()` 必须读机器的时刻。这里不用机器时钟就没人能用世界时钟",
    "auth.py": "会话创建/过期记的是真实世界的事(见下面 豁免 里的同一条理由)",
}
时间源上限 = 2          # **写死**(不是 len(...))—— 见下面棘轮那段

# ── 第三条判据:**SQL 字符串里的时间函数也是机器时钟** ──────────────
#
# 并行会话 2026-09-26 从**格式**上认出第十个:那 49 条 `ordr.updated` 带**秒**
# (`%H:%M:%S`),而所有 `_now()` 都是 `%H:%M` —— **带秒的只有 SQL 里的
# `datetime('now','localtime')` 产生得出来**。`backend/server.py` 有 16 处。
#
# 前两条判据都扫不到它:
#   · 第一条扫「谁直接写那几列」—— 它确实直接写,但写在 SQL 字符串里,
#     而第一条找的是表名+列名同现,SQL 里正好同现…… 却**没有机器时钟的函数调用**可匹配
#     (`datetime('now')` 不长得像 `datetime.now()`)。
#   · 第二条扫 `def _now/...` 的函数体 —— 这里**压根没有 _now()**,时间写在 SQL 里。
#
# **判据的盲区不是漏了某个文件,是漏了某种「时间的写法」。**
#
# 粒度按**站点**,不按文件:`server.py` 里 `edit_log.ts` 那一处是**该**用机器时钟的
# (编辑台账记真实世界)。放行靠这个仓库已有的标注惯例 —— 同行或上一行写
# `真实时钟`,并说明为什么。文件级豁免会把同一个文件里该管的那十几处一起放掉。
_SQL机器时钟 = re.compile(r"datetime\s*\(\s*['\"]now['\"]|date\s*\(\s*['\"]now['\"]|CURRENT_TIMESTAMP",
                        re.I)
_真实时钟标 = re.compile(r"真实时钟")

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
                None, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            要涂.append(t)                      # 独立成句的字符串 = docstring
        # ⚠️ **NL 不算「前一个 token」。** NL 是**非逻辑换行**:空行,以及
        # **括号内的换行**。而隐式字符串拼接正好长这样:
        #
        #     c.execute("INSERT INTO op_log(...)"
        #               " VALUES(datetime('now'),?)")
        #
        # 第二段字符串前面是 NL,把 NL 算进「docstring 的前驱」的话,
        # **它会被当成 docstring 涂白** —— 于是所有多行 SQL 都在判据的视野之外,
        # 不只是这一条新判据,前两条也一样瞎。
        # 2026-09-26 查第十个时踩到:判据扫出 0 处,而原文里明明有 3 处。
        # 真正的 docstring 前驱是 NEWLINE(逻辑换行)/ INDENT / DEDENT / 文件开头。
        if t.type not in (tokenize.COMMENT, tokenize.NL):
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

# ── 第二条判据:模块的时间源 ────────────────────────────────────────
坏源, 扫源, 源们 = [], 0, []
for fn in sorted(os.listdir(HERE)):
    if not fn.endswith(".py") or fn.endswith("_check.py"): continue
    if fn == "seed.py": continue          # 造数用自己的基准日 T(确定性)
    代码 = 只留代码(open(os.path.join(HERE, fn), encoding="utf-8").read())
    if 代码 is None:
        坏源.append(f"{fn}:剥注释时解析失败 —— **不当它通过**"); continue
    行 = 代码.splitlines()
    for i, l in enumerate(行):
        m = 时间源名.match(l)
        if not m: continue
        扫源 += 1
        源们.append(f"{fn}::{m.group(1)}")
        # ⚠️ **不能用固定行数的窗口。** 第一版扫 `def` 之后 16 行,
        # 而 `ops.now()` 的 docstring 有十几行 —— **我自己写的那段解释
        # 把 `return` 挤出了窗口**,于是把它改回机器时钟,检查照样绿。
        # 咬合抓到的。固定窗口的判据会随着注释变长而悄悄失效,
        # 而失效时和通过长得一模一样。
        # 现在扫到**下一个同级或更外层的 def/class** 为止 —— 那才是函数体。
        缩 = len(l) - len(l.lstrip())
        尾 = len(行)
        for k in range(i + 1, len(行)):
            x = 行[k]
            if not x.strip(): continue
            c2 = len(x) - len(x.lstrip())
            if c2 <= 缩 and re.match(r"\s*(def|class)\s", x):
                尾 = k; break
        体 = "\n".join(行[i:尾])
        if _机器时钟.search(体) and fn not in 时间源豁免:
            坏源.append(f"{fn}:{i+1} def {m.group(1)}() 返回机器时钟")

ck("**模块的时间源不许是机器时钟**(它写到哪儿、传给谁都会出错)",
   not 坏源, 扫源, 坏源[:3])
ck("真的扫到了时间源(一个都没扫到 = 判据坏了,不是全都对)", 扫源 >= 6, 扫源, 源们[:6])
ck(f"时间源豁免不许囤积(上限 {时间源上限})", len(时间源豁免) <= 时间源上限,
   len(时间源豁免), sorted(时间源豁免))
幽2 = [k for k in 时间源豁免 if not os.path.exists(os.path.join(HERE, k))]
ck("时间源豁免指向的文件都还在", not 幽2, len(时间源豁免), 幽2)

# ── 第三条判据:SQL 字符串里的时间函数 ──────────────────────────────
坏SQL, 扫SQL, 放行 = [], 0, 0
for 目录 in (HERE, os.path.join(ROOT, "tools"), os.path.join(ROOT, "knowledge"),
            os.path.join(ROOT, "mcp"), os.path.join(ROOT, "agentsite")):
    if not os.path.isdir(目录): continue
    for fn in sorted(os.listdir(目录)):
        if not fn.endswith(".py"): continue
        if fn.endswith("_check.py") or fn == "worldclock_check.py": continue
        路 = os.path.join(目录, fn)
        原 = open(路, encoding="utf-8").read()
        代码 = 只留代码(原)
        if 代码 is None: continue
        原行, 码行 = 原.splitlines(), 代码.splitlines()
        for i, l in enumerate(码行):
            if not _SQL机器时钟.search(l): continue
            扫SQL += 1
            # 同行或**前三行**有「真实时钟」标注 → 放行。
            # ⚠️ 标注写在注释里,而 `代码` 已经把注释涂白了 —— 所以必须看**原文**。
            # 涂白是**同长度替换**(不删行),所以行号一一对应,`原行[i]` 就是同一行。
            # 第一版只看前两行,而这里的标注是两行注释 + 一行代码,差一行 —— 于是不放行。
            窗 = "\n".join(原行[max(0, i - 3):i + 1])
            if _真实时钟标.search(窗):
                放行 += 1; continue
            坏SQL.append(f"{os.path.relpath(路, ROOT)}:{i+1} {l.strip()[:60]}")

ck("**SQL 字符串里的时间函数也不许是机器时钟**(它绕过前两条判据)",
   not 坏SQL, 扫SQL, 坏SQL[:3])
ck("真的扫到了 SQL 里的时间函数(一个都没扫到 = 判据坏了)", 扫SQL >= 2, 扫SQL,
   f"其中 {放行} 处带「真实时钟」标注放行")
无理由 = [k for k, v in 豁免.items() if len((v or "").strip()) < 10]
ck("每条豁免都写了理由", not 无理由, len(豁免), 无理由)
幽灵 = [k for k in 豁免 if not os.path.exists(os.path.join(HERE, k))]
ck("豁免指向的文件都还在(指向已删文件的豁免是一条永远生效的后门)", not 幽灵,
   len(豁免), 幽灵)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
if 挂:
    for x in 挂: print("   ·", x)
sys.exit(1 if 挂 else 0)
