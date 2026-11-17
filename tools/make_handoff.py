#!/usr/bin/env python3
"""生成 / 刷新 HANDOFF.md —— 上下文满了之后,接手的那个会话先读它。

## 为什么单独有这份文档

项目里已经有两份文档,但它们都答不了「**现在在做什么**」:

    CLAUDE.md    不变的约定和地雷        —— 很少失效
    澜绣云裳agent-项目日志.md   已完成的(从 git 生成)  —— 不会失效
    HANDOFF.md   **正在进行的**          —— 每天都失效

只有第三份会失效,所以它必须**能自动刷新**,而且要**短到接手的人真的会读**。
写成第二份项目介绍就白写了 —— 重复的文档一定不同步。

## 哪些自动、哪些手写

自动区(`<!--AUTO-->` 之间)每次重新生成:git 状态、检查结果、服务、计数。
**这些一律不许手写** —— 手写就会和真实状态漂,而交接文档漂了比没有更糟:
接手的人会照着一个假状态往下做。

手写区**原样保留**,只有人知道:为什么在做这个、下一步第一个动作、
以及**试过什么、为什么放弃**。

最后那条是交接里最容易丢、也最贵的一项:
**「做了什么」在 git 里躺着,「否决过什么」只在脑子里。**
上下文一满就没了,下一个会话大概率把同一条死路再走一遍。
"""
import os, re, subprocess, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "HANDOFF.md")
A0, A1 = "<!--AUTO-->", "<!--/AUTO-->"

# 手写区必填的段。缺一段就不算一份能用的交接。
REQUIRED = ["## 一句话:现在在做什么",
            "## 上一次停在哪",
            "## 没做完的 —— 下一步第一个动作",
            "## 别重做:试过并否决的"]
PLACEHOLDER = "(待填)"


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把交接文档里「别重做:试过并否决的」那一段标题换掉(必填的一段从此认不出来)',
     '缺段落'),
    # 2026-10-17:必填段重复过一次,而判据只认「有没有」——
    # 那条「把标题换掉」的咬合当场失效(换掉第一个,第二个顶上)。
    # ⚠️ 预期红要挑**字面量**那一段:判据的消息头是 f-string(「出现了 {n} 次」),
    #    写成「出现了 2 次」在脚本正文里找不到,`bite_check` 当场红。
    ('在交接文档里再插一段同名的「别重做:试过并否决的」(两份内容共用一个标题)',
     '内容落在后面那段里等于白写'),
    # 2026-11-17(W34 归档):没日期的「### 1. 未验证的预判」这种子节要跟着上面有日期的父节一起搬;
    # 攻击把继承那一句砍掉(`or 上一个` 去掉),子节就留在手写区、父节走了 —— 两边都读不懂
    ('归档切分不再让没日期的子节跟着父节走(砍掉 `or 上一个`)',
     '没日期的子节要跟着上面的父节走'),
]

def sh(cmd, default=""):
    try:
        return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True,
                              text=True, timeout=60).stdout.strip() or default
    except Exception:
        return default


def auto_block():
    # ⚠️ 这两个数是 `git ls-files` 列出来的。列不出来时它返空,`wc -l` 就是 0 ——
    # 而 **0 会被原样写进自动区**,看起来像一个真数。
    # 自动区的规矩是「一律不许手写,手写会漂」,而这是另一种漂法:
    # > 一个「这个仓库有 0 个 py 文件」和一个「列文件那步失败了」,
    # > **在自动区那一行上长得一模一样** —— 而接手的人会照着一个假状态往下做。
    # 失效路径是真的:不在 git 仓库里跑、git 坏了、或者在一个排除了 .git 的
    # 副本里跑(`bite_run` 造的副本就排除 .git)。2026-11-03 同一天,
    # `scan_secrets.sh`(假绿)和另一条新判据都栽在这同一个调用上。
    n_py = sh("git ls-files '*.py' | wc -l").strip()
    n_line = sh("git ls-files '*.py' | xargs wc -l | tail -1").split()
    n_line = n_line[0] if n_line else "?"
    if n_py in ("0", ""):
        n_py = n_line = "?(git ls-files 列不出文件 —— **不是真的 0 个**)"
    commits = sh("git log --oneline -5 --format='%h %s'")
    dirty = sh("git status --porcelain")
    branch = sh("git rev-parse --abbrev-ref HEAD", "?")
    head = sh("git log -1 --format='%h · %ad · %s' --date=short", "?")
    n_check = sh("grep -c '^run ' check.sh", "?")
    ports = []
    # ⚠️⚠️ **判据是「答不答得出来」,不是「这个路径返不返 200」—— 2026-11-04 改。**
    #    原来写 `code == '200'`,于是 2026-11-03 把 **8770 报成了「没起来」**,
    #    而那天页面冒烟 14 页全跑通 —— 服务活得很好,只是根路径不返 200。
    #    我还照着那个假状态跟用户说「会有几条报不适用」,后来才更正。
    #    > 「服务活着吗」和「这个路径返 200 吗」是**两个问题**,
    #    > 而它们在那句「没起来」上长得一模一样。
    #
    #    判据照 `tools/com.lanxiu.health.plist` 那个健康哨来(它一直是对的):
    #      **< 500 就算答得出来** —— 404 / 401 / 302 都是业务答复,
    #      只有 5xx 和连不上(curl 失败 → 000)才是答不出来。
    for p, name in (("8760", "管理后台"), ("8770", "智能运维平台")):
        code = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 3 http://127.0.0.1:{p}/", "000")
        活 = code.isdigit() and 0 < int(code) < 500
        ports.append(f"{name} :{p} → "
                     + (f"在跑 {code}" if 活
                        else ("答不出来 " + code if code.isdigit() and int(code) >= 500
                              else "连不上(没起来)")))
    L = [A0,
         f"> 自动区,由 `python3 tools/make_handoff.py` 生成于 "
         f"{datetime.datetime.now():%Y-%m-%d %H:%M}。**不要手改这一段。**",
         "",
         "| 项 | 值 |", "|---|---|",
         f"| 分支 | `{branch}` |",
         f"| 最新提交 | {head} |",
         f"| 代码量 | {n_py} 个 Python 文件 / {n_line} 行(不含 .venv) |",
         f"| 验收 | `./check.sh` 共 {n_check} 项 —— **接手第一件事就是跑它** |",
         f"| 服务 | {' · '.join(ports)} |",
         "",
         "**未提交的改动:**", ""]
    if dirty:
        L.append("```")
        L += dirty.splitlines()[:20]
        L.append("```")
        L.append("⚠️ 工作区不干净。**先搞清楚这些改动是什么再往下做** ——"
                 "上一个会话可能是被打断的,而不是做完了。")
    else:
        L.append("干净 —— 上一个会话的东西都提交了。")
    L += ["", "**最近 5 次提交:**", "", "```", commits, "```", A1]
    return "\n".join(L)


TEMPLATE = f"""# 交接文档

> 上下文满了、换会话、隔几天回来 —— **先读这一份**,再读 `CLAUDE.md`。
> 这份只装「正在进行的」;不变的约定和地雷在 `CLAUDE.md`,
> 已经完成的在 `澜绣云裳agent-项目日志.md`(从 git 生成)。

## 接手先做这三件事

1. 读完这一页(两分钟)
2. 跑 `./check.sh` —— 绿了才说明你接到的是一个完好的状态
3. 看下面「没做完的」第一个动作,直接开始

{REQUIRED[0]}

{PLACEHOLDER}

{REQUIRED[1]}

{PLACEHOLDER}

{REQUIRED[2]}

{PLACEHOLDER}

{REQUIRED[3]}

> **这一段是交接里最贵的。** 「做了什么」在 git 里躺着,
> 「试过什么、为什么放弃」只在上一个会话的脑子里 ——
> 不写下来,下一个会话大概率把同一条死路再走一遍。

{PLACEHOLDER}

## 当前状态(自动)

{{AUTO}}
"""


def refresh():
    if os.path.exists(DOC):
        old = open(DOC, encoding="utf-8").read()
        if A0 in old and A1 in old:
            new = re.sub(re.escape(A0) + r".*?" + re.escape(A1), lambda m: auto_block(),
                         old, flags=re.S)
        else:
            new = old.rstrip() + "\n\n## 当前状态(自动)\n\n" + auto_block() + "\n"
    else:
        new = TEMPLATE.replace("{AUTO}", auto_block())
    open(DOC, "w", encoding="utf-8").write(new)
    return new


def check():
    """不查「内容对不对」—— 那只有人知道。查的是「这份交接能不能用」。"""
    if not os.path.exists(DOC):
        return ["没有 HANDOFF.md —— 跑 `python3 tools/make_handoff.py`"]
    t = open(DOC, encoding="utf-8").read()
    # ⚠️ **必填段要「恰好一次」,不是「有就行」。**
    # 2026-10-17 全量咬合重放逮到:`## 别重做:试过并否决的` 在 HANDOFF.md 里有**两段**
    # (两份不同内容共用一个标题),于是那条咬合(把标题换掉)**改不动它** ——
    # `replace(old, new, 1)` 换掉第一个,第二个顶上,判据照旧说齐全。
    # 而两个同名必填段比缺一段更坏:下面那个 `t.split(h, 1)` 取的是**第一次出现**,
    # 内容落在第二段里判据一个字都没验,**写了等于没写**。
    # > 「有一段」和「有两段」在 `h in t` 眼里长得一模一样。
    bad = []
    for h in REQUIRED:
        n = t.count(h)
        if n == 0:
            bad.append(f"缺段落「{h}」")
        elif n > 1:
            bad.append(f"段落「{h}」出现了 {n} 次 —— 判据只验第一段,"
                       f"内容落在后面那段里等于白写。给它们各自取个说得出区别的标题")
    for h in REQUIRED:
        if h in t:
            body = t.split(h, 1)[1].split("\n## ", 1)[0]
            if PLACEHOLDER in body or not body.strip():
                bad.append(f"「{h}」还是空的 —— **一份「下一步」为空的交接等于没交接**")
    if A0 not in t or A1 not in t:
        bad.append("自动区标记不见了 —— 状态那一段会烂掉")
    # ── 手写区行数上限(用户 2026-11-12 拍「只留最近 3 天 + 四段必填」)────────────────
    # 11-12 归档前 HANDOFF 18614 行、1183 个小节,文首写着「两分钟读完」—— 接手的人读不完,只能信 AI 转述。
    # 归档后手写区 3129 行。这里是**上限**(超了就红:把老小节搬进 docs/交接归档/),
    # 不是「只许降」的棘轮 —— 手写区每天都在长,只许降会天天拦人。
    # ⚠️ 上限要有推它的手:实际远低于上限时印 ℹ️ 提醒把上限往下调(CLAUDE.md 第 8 节)。
    手写区 = t.split(A0, 1)[0] if A0 in t else t
    行数 = 手写区.count("\n")
    if 行数 > 手写区上限行:
        bad.append(f"手写区 {行数} 行,超过上限 {手写区上限行} —— 把 3 天前的小节原样搬进 docs/交接归档/,"
                   f"**别删,别改字**;一份 {行数} 行的交接和一份没有交接,对接手的人是一回事")
    elif 行数 < 手写区上限行 * 0.6:
        print(f"  ℹ️ 手写区 {行数} 行,离上限 {手写区上限行} 很远 —— 可以把 `手写区上限行` 往下调")
    # ── 归档那只手(W34,11-17):上限是闸,这里是推它的手 ── 早于 3 天前的小节还留在手写区就提醒,只报不拦
    # 11-14 那次归档是人手搬的 780 行;人手搬容易改字、漏指针,所以搬的动作做成 `--归档`,这里只负责提醒它该跑了
    try:
        _, 搬, 日期们 = 归档切分(t, datetime.date.today())
        if 日期们:
            print(f"  ℹ️ 手写区里 {len(日期们)} 个小节早于 {归档保留天数} 天前(最早 {min(日期们):%m-%d}、共 {搬.count(chr(10))} 行)"
                  f" —— `python3 tools/make_handoff.py --归档` 一次原样搬进 docs/交接归档/(先加 --干跑 看搬哪些)")
    except Exception as e:                      # 提醒坏了不该把门禁打红 —— 但要说出来
        print(f"  ⚠ 归档提醒没算出来({e!r}),判据本身没受影响")
    bad += 自测()
    return bad


手写区上限行 = 3500     # 2026-11-12 归档后实测 3129;超了就红(搬归档),远低于时 ℹ️ 提醒下调


# ── 归档(W34,2026-11-17)──────────────────────────────────────────────────
# 用户 11-12 拍:手写区只留最近 3 天 + 四段必填,更早的小节**原样**搬进 docs/交接归档/。
# 11-14 第一次是人手搬的(5287f9e9):780 行、按行号切。人手搬的问题不是累,是**没法验「原样」**——
# 搬完谁也说不清有没有少一行、改一个字。所以这里把「切哪些」做成纯函数,自测里守一条不变量:
# **留下的 + 搬走的 = 原来的,一行不多一行不少**。
归档目录 = os.path.join(ROOT, "docs", "交接归档")
归档保留天数 = 3
_日期式 = re.compile(r"(?<!\d)(\d{2})-(\d{2})(?!\d)")     # 标题里的 MM-DD;「2026-11-03」里只认得出 11-03(前面的 26 被 2026 的 0 挡住)


def 节日期(标题, 年):
    """小节标题里最晚的那个 MM-DD(⏱️ 清单标题写的是区间「11-13 20:25 → 11-14 08:25」,按晚的那头算,宁可多留)。没有日期回 None。"""
    ds = []
    for m in _日期式.finditer(标题):
        try:
            ds.append(datetime.date(年, int(m.group(1)), int(m.group(2))))
        except ValueError:
            pass
    return max(ds) if ds else None


def 归档切分(t, 今天, 天数=None):
    """纯函数。手写区顶部(第一个 `## ` 之前)里,日期早于 今天-天数 的 `### ` 小节原样切出。
    返回 (留下的全文, 搬走的文本, [搬走的每个小节的日期])。
    - 没日期的小节(「### 1. 未验证的预判」这种)跟着它上面那个有日期的小节走 —— 它们是子节,分家了两边都读不懂
    - 四段必填和自动区在第一个 `## ` 之后,碰都不碰"""
    天数 = 归档保留天数 if 天数 is None else 天数
    截止 = 今天 - datetime.timedelta(days=天数)
    头, 分, 尾 = t.partition("\n## ")
    块 = re.split(r"(?m)^(?=### )", 头)
    留, 搬, 日期们 = [块[0]], [], []
    上一个 = None
    for 节 in 块[1:]:
        d = 节日期(节.split("\n", 1)[0], 今天.year) or 上一个
        上一个 = d
        if d and d < 截止:
            搬.append(节); 日期们.append(d)
        else:
            留.append(节)
    return "".join(留) + 分 + 尾, "".join(搬), 日期们


def 归档(今天=None, 干跑=False):
    """把早于 归档保留天数 的小节原样搬进 docs/交接归档/,手写区末尾留一行指针。回搬去的文件路径(没搬回 None)。"""
    今天 = 今天 or datetime.date.today()
    t = open(DOC, encoding="utf-8").read()
    新, 搬, 日期们 = 归档切分(t, 今天)
    if not 日期们:
        print(f"  手写区里没有早于 {归档保留天数} 天前的小节,不用归档")
        return None
    a, b = min(日期们), max(日期们)
    名 = f"HANDOFF-归档-{a:%Y-%m-%d}至{b:%m-%d}.md"
    路径 = os.path.join(归档目录, 名)
    k = 2
    while os.path.exists(路径):                  # 同一段日期搬第二次就另起一份,不往旧文件里混(旧文件是搬那天的原样)
        路径 = os.path.join(归档目录, 名[:-3] + f"-{k}.md"); k += 1
    标题们 = [l[4:].strip() for l in 搬.split("\n") if l.startswith("### ")]
    行数 = 搬.count("\n")
    print(f"  要搬 {len(日期们)} 个小节、{行数} 行({a:%m-%d} 至 {b:%m-%d})→ {os.path.relpath(路径, ROOT)}")
    for s in 标题们: print(f"    · {s[:80]}")
    if 干跑:
        print("  (--干跑,没动文件)")
        return None
    # 不变量:留下的 + 搬走的 = 原来的。多一行少一行都不写盘 —— 「原样」要能验,不能靠眼
    assert sorted((新.partition("\n## ")[0] + 搬).split("\n")) == sorted(t.partition("\n## ")[0].split("\n")), "切分丢了行,没写盘"
    os.makedirs(归档目录, exist_ok=True)
    头注 = (f"# HANDOFF 归档({a:%Y-%m-%d} 至 {b:%m-%d} 的手写小节)\n\n"
            f"> {今天} 由 `python3 tools/make_handoff.py --归档` 从 HANDOFF.md 手写区**原样搬出**(没删、没改字;"
            f"切分函数自测守着「留下的 + 搬走的 = 原来的」):手写区只留最近 {归档保留天数} 天 + 四段必填(用户 2026-11-12 拍)。"
            f"搬了 {len(日期们)} 个小节、{行数} 行。\n\n")
    open(路径, "w", encoding="utf-8").write(头注 + 搬.lstrip("\n"))
    指针 = (f"> 📦 {a:%m-%d} 至 {b:%m-%d} 的 {len(日期们)} 个手写小节已原样搬到 `docs/交接归档/{os.path.basename(路径)}`"
            f"({今天:%m-%d},`make_handoff --归档`)\n\n")
    头, 分, 尾 = 新.partition("\n## ")
    open(DOC, "w", encoding="utf-8").write(头.rstrip("\n") + "\n\n" + 指针 + "## " + 尾)
    print(f"  已搬;HANDOFF.md 手写区末尾留了指针。新文件先 `git add`(--only 不带未跟踪的),随下一笔业务提交一起带上")
    return 路径


def 自测():
    """归档切分的对照(门禁 --check 里顺手跑,纯函数、毫秒级)。回 [] 或失败消息。"""
    今天 = datetime.date(2026, 11, 17)
    t = ("> 前言两行\n> 别动\n\n"
         "### ⏱️ 12 小时长任务清单(11-17 09:5x → 21:5x)\n今天的\n"
         "### 🟢 11-13 夜 · 旧的\n旧内容 A\n"
         "### 2. 判据\n没日期的子节,属于上面 11-13 那节\n"
         "### ⏱️ 12 小时长任务清单(11-13 20:25 → 11-14 08:25)\n区间按晚的那头算,11-14 正好卡在边上要留\n"
         "### 📍 2026-11-11 下午 · 更旧的\n旧内容 B\n\n"
         "## 一句话:现在在做什么\n正文\n\n## 别重做:试过并否决的\n正文\n")
    留, 搬, 日期们 = 归档切分(t, 今天, 3)
    bad = []
    if len(日期们) != 3:
        bad.append(f"自测:该搬 3 个小节(11-13、它的子节、11-11),实际搬了 {len(日期们)}")
    if "没日期的子节" not in 搬:
        bad.append("自测:没日期的子节要跟着上面的父节走,它留在了手写区里")
    if "11-14 正好卡在边上" not in 留 or "今天的" not in 留:
        bad.append("自测:边界那天(今天-3)和今天的小节该留下,被搬走了")
    if "2026-11-11" in 留 or "旧内容 A" in 留:
        bad.append("自测:早于 3 天前的小节没搬走")
    if sorted((留.partition("\n## ")[0] + 搬).split("\n")) != sorted(t.partition("\n## ")[0].split("\n")):
        bad.append("自测:留下的 + 搬走的 ≠ 原来的,切分改了字或丢了行")
    if 留.partition("\n## ")[2] != t.partition("\n## ")[2]:
        bad.append("自测:四段必填那一半被归档碰到了")
    if 日期们 and (min(日期们), max(日期们)) != (datetime.date(2026, 11, 11), datetime.date(2026, 11, 13)):
        bad.append(f"自测:搬走的日期范围该是 11-11 至 11-13,实际 {min(日期们):%m-%d} 至 {max(日期们):%m-%d}")
    return bad


日志文件 = "澜绣云裳agent-项目日志.md"


def 日志落后():
    """项目日志落后 HEAD 多少次提交 —— 只报,不判红(每次提交都会落后一次,判红就天天拦人)。"""
    try:
        头 = open(os.path.join(ROOT, 日志文件), encoding="utf-8").read(400)
        m = re.search(r"共 (\d+) 次提交", 头)
        现 = int(sh("git rev-list --count HEAD", "0") or 0)
        return (现 - int(m.group(1))) if m else None
    except OSError:
        return None


def 日志新鲜吗():
    """项目日志头部的「最后更新」日期是不是 ≥ 昨天(执行手册 W29,拍板 19:日志改成每天 06:40 由 launchd 生成并发飞书,
    这里只看它有没有按天在跑)。→ (日期文本 或 None, 新鲜吗)。读不到日期当不新鲜 —— 读不到不是通过。"""
    import datetime as _dt
    try:
        头 = open(os.path.join(ROOT, 日志文件), encoding="utf-8").read(400)
    except OSError:
        return None, False
    m = re.search(r"最后更新 (\d{4}-\d{2}-\d{2})", 头)
    if not m:
        return None, False
    try:
        d = _dt.date.fromisoformat(m.group(1))
    except ValueError:
        return m.group(1), False
    return m.group(1), d >= (_dt.date.today() - _dt.timedelta(days=1))



def 记一笔():
    """告诉交接门禁:这份交接**刚被真的刷过**。

    ⚠️ 为什么需要这一笔:门禁原来拿 `HANDOFF.md` 的 mtime 判「刷过没有」,
       而 `git pull` 也会更新 mtime —— 2026-11-04 实际撞到:并行会话改了交接
       14 行,我 pull 之后门禁就说「本轮已刷新」,**而我并没有刷**。
       > 「文件被动过」和「交接刷过了」,在 mtime 上长得一模一样。

    ⚠️ **路径由 hook 自己算**(`--记一笔` 入口),这边不照样子算一遍 ——
       两边各算一次就是两份会漂的实现。这也是为什么这里宁可起一个子进程。
    ⚠️ 记不下来**不算刷新失败**:门禁没有记号时会退回看 mtime(并说明那不可靠),
       所以这里只提示,不改退出码。
    """
    hook = os.path.join(ROOT, "tools", "hooks", "handoff-gate.mjs")
    if not os.path.isfile(hook):
        return
    try:
        r = subprocess.run(["node", hook, "--记一笔", os.path.abspath(DOC)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            print("  已告诉交接门禁这份交接刚刷过(它判「刷过没有」不再只看文件时间)")
        else:
            print(f"  ⚠ 没记上那一笔(门禁会退回看文件时间):{(r.stderr or r.stdout).strip()[:120]}")
    except Exception as e:
        print(f"  ⚠ 没记上那一笔(门禁会退回看文件时间):{e}")


def 项目日志():
    """刷新交接 = 一个阶段做完 → **顺手重新生成项目日志并发飞书**(用户 2026-10-15 拍,两种里选的「交接时顺手做」)。

    ⚠️ 起因:日志 9-27 之后停了 18 天(794 → 1349 次提交)—— 原料(提交说明)一直在攒,
    而「生成 + 发布」要人想起来手动跑,没有任何东西盯着,过期了没人知道。
    只在**正式刷新**时跑;`--check`(门禁里那一次)绝不发飞书。"""
    r = subprocess.run([sys.executable, "tools/make_log.py"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        print(f"  ⚠ 项目日志没生成成功(交接照样刷新了):{(r.stderr or r.stdout)[-200:]}")
        return
    print("  项目日志已重新生成 —— " + (r.stdout.strip().splitlines() or [""])[-1][:80])
    r = subprocess.run([sys.executable, "tools/feishu_publish.py", 日志文件], cwd=ROOT, capture_output=True, text=True)
    链 = re.search(r"https://\S+", r.stdout or "")
    if r.returncode or not 链:
        print(f"  ⚠ 项目日志没发上飞书(本地已生成,可以手动 python3 tools/feishu_publish.py {日志文件}):"
              f"{(r.stderr or r.stdout)[-200:]}")
    else:
        print(f"  项目日志已发飞书:{链.group(0)}")
    print(f"  📌 {日志文件} 和 HANDOFF.md **随下一次业务提交一起带上**(用户 11-12 拍:不再单开「交接:」提交)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        bad = check()
        print("交接文档 · 可用性检查\n" + "=" * 72)
        for b in bad: print(f"  ❌ {b}")
        if not bad:
            print(f"  ✅ HANDOFF.md 四段必填齐全,自动区完好")
            print("     (只查「能不能用」,内容对不对只有人知道)")
        日, 新 = 日志新鲜吗()
        if not 新:
            # W29(11-16):日志改成每天 06:40 由 launchd 生成(tools/launchd/com.lanxiu.daily-log.plist),这里只盯「昨天以来有没有生成过」。
            # 只报不拦:拦了等于每天早上 06:40 之前门禁都红
            print(f"  ℹ 项目日志最后更新 {日 or '(读不到日期)'},不是昨天以来生成的 —— 每日定时(com.lanxiu.daily-log)没装或没跑;"
                  f"手动:python3 tools/make_log.py --publish。只报不拦")
        落 = 日志落后()
        if 落:
            print(f"  ℹ 项目日志落后 {落} 次提交(每天 06:40 会补上)")
        sys.exit(1 if bad else 0)
    if "--归档" in sys.argv:
        # W34(11-17):把 3 天前的小节原样搬进 docs/交接归档/。先 --干跑 看搬哪些;搬完刷一次自动区
        if 自测():
            print("  ❌ 切分函数自测没过,不搬:" + ";".join(自测())); sys.exit(1)
        p = 归档(干跑="--干跑" in sys.argv)
        if p and A0 in open(DOC, encoding="utf-8").read():
            refresh(); print("  自动区已顺手刷新")
        sys.exit(0)
    refresh()
    print(f"已刷新 {DOC}")
    记一笔()
    for b in check(): print(f"  ⚠ {b}")
    # W29(11-16,拍板 19):刷交接**不再**顺手生成 / 发项目日志 —— 日志改成每天 06:40 由 launchd 跑一次(近 300 次提交里 192 次碰交接,
    # 一刷一发把飞书上的日志刷成流水)。要立刻出一份就加 --带日志;老参数 --不发日志 还收,等于默认
    if "--带日志" in sys.argv:
        项目日志()
    else:
        print("  ℹ 项目日志不随交接生成(每天 06:40 定时生成并发飞书;要现在出一份加 --带日志)")
