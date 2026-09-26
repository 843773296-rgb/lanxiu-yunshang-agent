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

# ══════════════════════════════════════════════════════════════════
# 第四条判据:**要和业务时刻比先后的列,不许取「现在」**
# ══════════════════════════════════════════════════════════════════
#
# ⚠️ **这一条和前三条正交,不是它们的补丁。**
#
# 前三条问的都是同一件事:「这个写口用的是不是机器时钟」。
# 而 2026-09-26 并行会话查出来的那一条,写口用的**就是修好的 `当下()`** ——
# 它的**日期**那一半是对的,三条判据全都放行。
#
# 错的是**时刻**那一半:
#
# > `当下()` = 世界日期 + **机器时刻**。业务时刻(包裹到店 15:00、发货 12:00)
# > 是造数**按剧本排的**。**同一天之内,这两种时刻没有可比的先后。**
#
# 实测:重建时真实时间 20:55 → `pkg.created 20:55` 晚于同一条包裹的
# `arrived_at 15:00`,「包裹建档晚于包裹到店」。
#
# **判据的盲区这次不是漏了某种写法,是漏了某种「错」。**
#
# 范围来自 `worldclock.序关系`(那份登记同时喂给数据层的 `查序关系()`)。
# ⚠️ 两个读者共用一份真相源 → **不在清单里的那一对会同时躲过两边**,
# 这正是 `pkg.created` 上次躲过 C4 和平移闸的方式。
# 所以假数据工厂里那条**不针对任何特定列**的基线断言必须留着 ——
# 照出这一次的正是它,而它不读这份清单。
def _两个窗(代码, 起, 尾):
    """返回 (列窗, 现在窗)。

    · **列窗** = 这条 SQL 字符串字面量的内容。列名只可能在这里面 ——
      把它放宽会扫进邻居的字典字面量(server.py 上栽过:
      `{"完成":"finished_at"}` 被当成了同一条语句里的列)。
    · **现在窗** = 列窗 + 紧跟在字符串后面的**参数区**。
      `?` 占位的 SQL 把值写在参数元组里,所以 `_now()` 不在 SQL 里 ——
      只看列窗就永远抓不到它。参数区切到「下一条语句开始」为止。

    切不准就两个都退回原来那段尾巴:**不静默放行**,顶多多报,而多报会被看见。
    """
    收 = -1
    for 界 in ("""""", "'''", chr(34), chr(39)):
        开 = 代码.rfind(界, 0, 起)
        if 开 < 0:
            continue
        c = 代码.find(界, 开 + len(界))
        if 开 < 起 and (c < 0 or 起 < c):
            收 = c if c >= 0 else len(代码)
            break
    if 收 < 0:
        return 尾, 尾
    列窗 = 代码[起:收]
    # 参数区:字符串收尾之后那一段,**切到下一条写语句开始为止**
    参数区 = 代码[收:收 + 400]
    下一条 = re.search(r"(?i)(execute\s*\(|executescript\s*\(|"
                      r"INSERT\s+INTO|UPDATE\s+\w)", 参数区[1:])
    if 下一条:
        参数区 = 参数区[:下一条.start() + 1]
    return 列窗, 列窗 + 参数区


print("\n▸ 第四条判据:要和业务时刻比先后的列,不许取「现在」")
序对 = list(WC.序关系)
# **棘轮方向:只许多不许少。** 两个读者共用这份登记 →
# 「不在清单里的那一对」会同时躲过两边(pkg.created 上次就是这么躲过 C4 和平移闸的)。
# 所以数量下限写死:删掉一对要连这个数字一起改,而改数字会在 review 里被看见。
ck("范围来自 worldclock.序关系(数据层的 查序关系() 读同一份),而且**只许多不许少**",
   len(序对) >= 6, len(序对), f"{len(序对)} 对先后关系")

# ## 判据怎么写才不用豁免名单
#
# 第一版写的是「序关系里的列,写口一律不许取『现在』」—— **太宽了**。
# 它把 `server.py` 里「操作员现在点了开裁」也判成错,而那个动作
# **真的就发生在现在**,没有别的时间可以派生。误报久了人就开始无视判据。
#
# 两种写口的区别不是「哪个文件」,是**手里有没有业务时刻**:
#
#   · `factory_inbox` 那条 INSERT 里 `shipped_at = m["at"]` 就在**同一条语句里**,
#     而 `created` 去取了「现在」—— **它握着业务时刻却没用**;
#   · `server.py` 那条 UPDATE 只设 `cut_at`,没有兄弟业务时刻可派生。
#
# 所以判据是**结构性**的,不需要枚举例外:
#
# > **同一条写语句里已经有一个序关系列取了业务时刻,另一个序关系列却取「现在」→ 红。**
#
# 这条判据还有一个好处:它随着 `序关系` 自动长 —— 加一对关系,
# 新的那两列立刻进入检查范围,不用改这里。
_不许 = set(WC.不许取现在的列())
_现在 = re.compile(r"(当下\(\)|wnow\(\)|_now\(\)|datetime\.now\(\)|"
                  r"datetime\s*\(\s*['\"]now|CURRENT_TIMESTAMP)", re.I)
坏序, 扫序, 命中列 = [], 0, set()
for fn in sorted(os.listdir(HERE)):
    if not fn.endswith(".py") or fn.endswith("_check.py"): continue
    if fn == "seed.py": continue          # 造数用自己的基准日,不读世界时钟
    源 = open(os.path.join(HERE, fn), encoding="utf-8").read()
    代码 = 只留代码(源)
    if 代码 is None:
        坏序.append(f"{fn}:剥注释时解析失败 —— **不当它通过**")
        continue
    for m in _写语句.finditer(代码):
        表, 尾 = m.group(1), m.group(2)
        # ⚠️ **尾巴要切到这条 SQL 字符串的边界,不能用固定长度。**
        # `_写语句` 的尾巴是「后面 400 个字符里不含分号的那一段」——
        # 在 server.py 里它一路扫过了 `UPDATE ordr SET cut_at=wnow()` 那条语句,
        # 把下面那个**字典字面量** `{"完成":"finished_at",…}` 也扫了进来,
        # 于是判据以为「同一条语句同时碰了 cut_at 和 finished_at」。
        #
        # **固定长度的窗口会把邻居扫进来,而扫进来的东西和真在语句里长得一模一样。**
        # 这个仓库记过同一族的教训(固定行窗口把 `return` 挤出了视野)。
        # 这一条判据看的是「同一条语句里有几个序关系列」,所以边界必须是真的边界。
        # **两个窗口,不是一个。** 咬合抓到的:第一版为了消一个误报把窗口收到
        # SQL 字符串里,结果**把真 bug 也关在了外面** ——
        # `_now()` 在**参数元组**里(`?` 占位),不在 SQL 里。
        # 收窄的方向对,位置错了:用一个窗口同时回答两个问题,必然在其中一个上错。
        #   · 「碰了哪几个序关系列」→ 只能从 **SQL 字符串**看(列名在那儿)
        #   · 「有没有取『现在』」→ 得看 **SQL + 紧跟的参数区**(值在那儿)
        列窗, 现在窗 = _两个窗(代码, m.end(1), 尾)
        列们 = [c for (t, c) in _不许
                if t == 表 and re.search(r"\b" + re.escape(c) + r"\b", 列窗)]
        if len(列们) < 2:
            # 一条语句只碰一个序关系列 → 没有「手里握着业务时刻」这回事,
            # 它取「现在」是合法的(真实操作就发生在现在)。
            if 列们:
                扫序 += 1
                命中列 |= {f"{表}.{c}" for c in 列们}
            continue
        扫序 += 1
        命中列 |= {f"{表}.{c}" for c in 列们}
        if not _现在.search(现在窗):
            continue                      # 一个「现在」都没取 → 过
        # 同一条语句里既有序关系列取了「现在」,又有别的序关系列 ——
        # 而那个别的列几乎一定是业务时刻(它是从消息/记录里带过来的)。
        坏序.append(
            f"{fn}:一条写语句同时碰了 {sorted(f'{表}.{c}' for c in 列们)},"
            f"其中有一个取了「现在」—— **同一条语句里已经握着业务时刻了**,"
            f"那个序关系列该从它派生(见 worldclock.序关系)")

ck("**同一条写语句里握着业务时刻,就不许给序关系列取「现在」**"
   "(连世界时钟一起挡 —— 它的时刻那一半是机器的)", not 坏序, 扫序, 坏序[:3])
ck("真的扫到了写这些列的地方(一个都没扫到 = 判据坏了,不是全都对)",
   扫序 >= 2, 扫序, f"涉及 {len(命中列)} 列:{sorted(命中列)[:5]}")

# 数据层:同一份登记的另一个读者。**在库里真的查一遍。**
_db = os.path.join(HERE, "lanxiu.db")
if not os.path.exists(_db):
    ck("库在,能查先后关系", False, 1, f"{_db} 不存在 —— **这不叫通过,叫没查**")
else:
    import sqlite3 as _sq
    _r = WC.查序关系(_sq.connect(_db))
    ck("库里没有时间倒挂的行(早的列不晚于晚的列)", not _r["倒挂"],
       len(序对), _r["倒挂"][:2])
    ck("每一对都真的查到了(查不了 = 清单和库对不上,而表现是「这一项从来没查过」)",
       not _r["查不了"], len(序对), _r["查不了"][:2])

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
if 挂:
    for x in 挂: print("   ·", x)
sys.exit(1 if 挂 else 0)
