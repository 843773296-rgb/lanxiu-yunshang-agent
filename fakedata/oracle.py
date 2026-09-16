#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""试灌 —— **拿项目自己的检查当裁判**,红了就二分定位是哪张表干的。

## 为什么要这一层

工具原来只会从**数据的统计规律**里猜规矩:这一列像日期、那两列总是一起变。
而一个成熟项目早就把规矩写成了**检查脚本** —— 那是比统计强得多的规矩来源,
因为它是人一条一条写下来的,还带着「为什么」。

实测的账单就在隔壁:给库存预警造模拟销量时,我读了十几个检查脚本才知道
「付款不能早于下单」「已经发生的事不能在未来」这些规矩。就算这样,
「**有在办业务的账户不得注销**」还是漏了 —— 灌完跑检查才被抓到。
**那一条从来就不在数据的统计规律里,它只在检查脚本里。**

## 三层,一层比一层可信

    ① 基线跑两遍     先确认**这把尺子自己不抖** —— 抖的尺子会把噪音记到你头上
    ② 只报变差的     本来就红的不算你造成的(和灌完自检同一条原则)
    ③ 二分定位       砍掉一半表再灌一次,看那条检查还红不红

**第三层是这个模块的全部价值。** 从报错文字里找表名是**猜**:
中文报错经常根本不提表名(「冷静期存在的意义正是等这些事了结」里一个表名都没有),
而这个项目在「靠字面猜」上栽过七次以上。所以文字线索只当提示、只标成猜,
**结论一律由重灌得出**:去掉它就绿、加回来就红,这才是证据。

二分用的是 delta debugging(ddmin):不只试「前一半 / 后一半」,
还要试「**去掉这一块剩下的**」—— 否则「两张表凑在一起才触发」的情况会被报成
「谁都不是」,而那正是最需要人看的一类。

## 前提:回滚必须干净

每试一次都要把这一批删干净,否则第二次的结果里混着第一次的残留。
这条前提不是假设,它有一个专门的自测钉着(「照 manifest 回滚后断言逐条回到基线」)——
接口驱动那条路就栽在这上面:探针之间互相污染,归因全错。

## 不做什么

- **不自动改方案。** 定位到「是 `ordr` 这张表」之后,该加什么约束是人的判断:
  可能是某一列的取值范围,也可能是这张表根本不该在这批里。**工具给证据,不替人拍板。**
- **不定位到列。** 表级二分是可靠的(整表不灌 = 干净的对照),
  列级要靠「把某列换成既有值」来做对照,而那本身可能触发别的规矩。想清楚之前不做。
- **不跑全套门禁。** `check.sh` 一轮几分钟,二分要跑十几轮。
  传给它的应该是**几条跑得快的检查**,而不是整套。
"""
import copy, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import gen as G, load as L, schema as S


class 检查结果:
    __slots__ = ("cmd", "exit", "bad", "out", "秒")

    def __init__(self, cmd, exit_, bad, out, 秒):
        self.cmd, self.exit, self.bad, self.out, self.秒 = cmd, exit_, bad, out, 秒

    def 红了(self):
        return self.exit != 0 or bool(self.bad)


_BAD = re.compile(r"[❌✗]|\bFAIL|失败|不符合预期|没守住")
# 行里的数字会随数据量变,而变的那一部分正是我们要看的 —— 所以**不归一化数字**。
# 但时间戳、耗时这类每次都不同的要抹掉,否则两次基线永远不一致。
_NOISE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?|\d+\.\d+ ?(s|秒|ms)")


def run_check(cmd, root=ROOT, timeout=600, env=None):
    """跑一条检查。**stdout 和 stderr 一起收** —— 报错常常只在 stderr 里。

    `env`:额外的环境变量。**这是让裁判对准被灌的那个库的唯一办法** ——
    检查脚本大多把库路径写死,能覆盖的项目才用得上这个参数。
    """
    t0 = time.time()
    p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True,
                       timeout=timeout,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **(env or {})))
    out = (p.stdout or "") + (p.stderr or "")
    bad = [_NOISE.sub("", l).strip() for l in out.splitlines() if _BAD.search(l)]
    return 检查结果(cmd, p.returncode, bad, out, round(time.time() - t0, 1))


def run_all(cmds, root=ROOT, log=lambda *a: None, env=None):
    res = {}
    for c in cmds:
        r = run_check(c, root, env=env)
        res[c] = r
        log(f"    {'❌' if r.红了() else '✅'} {c}  ({r.秒}s)")
    return res


def baseline(cmds, root=ROOT, twice=True, log=lambda *a: None, env=None):
    """基线。**默认跑两遍** —— 两遍不一致的检查不能当裁判,它会把噪音记到你头上。

    返回 (基线, 不稳的那几条)。不稳的会被踢出裁判席,而且要说出来。
    """
    log("  基线(第 1 遍)")
    a = run_all(cmds, root, log, env)
    if not twice:
        return a, []
    log("  基线(第 2 遍,验尺子自己稳不稳)")
    b = run_all(cmds, root, log, env)
    抖 = [c for c in cmds if a[c].exit != b[c].exit or a[c].bad != b[c].bad]
    return b, 抖


def 变差(before, after):
    """只报变差的:本来就红的不算。返回 [(检查, 新增的行, 原来退出码, 现在退出码)]"""
    out = []
    for c, aft in after.items():
        bef = before.get(c)
        if bef is None:
            continue
        新增 = [l for l in aft.bad if l not in bef.bad]
        if aft.exit != bef.exit or 新增:
            out.append((c, 新增, bef.exit, aft.exit))
    return out


def 文字线索(新增行, tables):
    """从报错文字里找表名 —— **这是猜**,只当提示,不当结论。"""
    txt = " ".join(新增行)
    return [t for t in tables if re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", txt)]


def 对准自检(目标, cmds, root=ROOT, env=None, log=lambda *a: None):
    """**把库藏起来,看裁判还说不说「一切正常」。**

    这道自检防的是整套结论里最坏的一种错:裁判读的是**另一个库**。
    那时它永远绿,而「绿」会被读成「这批数据没问题」——
    **一把对着别处量的尺子,和一把好尺子,输出一模一样。**

    这不是假想:实测这个项目 60 个文件把库路径写死,一个都不支持覆盖。
    所以对着副本灌、拿这些检查当裁判,结论全是错的,而且看起来完全正常。

    只对 sqlite 文件目标做得了 —— 把文件挪走,跑一遍,再挪回来。
    挪不动(MySQL 之类)就如实说「验不了」,**不假装验过**。
    """
    kind, addr = S.normalize_target(目标)
    if kind != "sqlite" or not os.path.exists(addr):
        log(f"  ⚠️ 对准自检:验不了(目标不是本地 sqlite 文件)—— **没验过,不是验过了**")
        return None
    hidden = addr + ".aimcheck-hidden"
    os.rename(addr, hidden)
    try:
        对不准 = [c for c in cmds if not run_check(c, root, env=env).红了()]
    finally:
        os.rename(hidden, addr)
    return 对不准


# ── 试灌一批,再删干净 ────────────────────────────────────────────────
def _subplan(plan, keep):
    """只灌 keep 里的表。其余标成 skip —— **整表不灌是干净的对照**。"""
    pl = copy.deepcopy(plan)
    for t, tp in pl["tables"].items():
        if t not in keep:
            tp["skip"] = "试灌:这一轮不灌它(二分定位用)"
    return pl


def 灌一批(conn, plan, keep):
    pl = _subplan(plan, keep)
    made, man = G.generate(pl, conn)
    try:
        L.load(conn, pl, made, dry=False, log=lambda *a: None)
        L.fill_deferred(conn, pl, made, dry=False, log=lambda *a: None)
    except Exception as e:
        # 主键撞车有两种来路,而**数据库只会说「UNIQUE 约束失败」**,
        # 看不出是哪一种。两种的处理办法完全不同,所以这里把话说清楚。
        if "UNIQUE" in str(e) or "Duplicate" in str(e):
            raise SystemExit(
                f"❌ 灌不进去:主键已经在库里了({e})\n"
                f"   两种可能,处理办法不同:\n"
                f"   · **上一批没删干净**(试灌中途断了)→ 拿 .fakedata 里的 manifest 回滚\n"
                f"   · **同一个种子灌过两次** → 换 --seed,同一个种子生成的主键是同一批\n"
                f"   试灌每一轮都会自己删干净,所以正常情况下碰不到这条。")
        raise
    conn.commit()
    doc = {"顺序": pl["order"],
           "表": {t: {"pk": m["pk"], "主键": m["values"]} for t, m in man.items()}}
    return doc, sum(len(v) for v in made.values())


def 删干净(conn, doc):
    L.rollback(conn, doc, dry=False, log=lambda *a: None)
    conn.commit()


def ddmin(test, items, log=lambda *a: None):
    """delta debugging:缩到**最小的那组**。

    `test(子集)` 返回「这条检查还红不红」。
    只试前后两半是不够的:**两张表凑在一起才触发**的情况,两半各自都不红,
    那时要试「去掉这一块剩下的」,否则会报成「谁都不是」。
    """
    items = list(items)
    n = 2
    while len(items) >= 2:
        chunk = max(1, len(items) // n)
        块 = [items[i:i + chunk] for i in range(0, len(items), chunk)]
        命中 = None
        for ch in 块:                       # ① 某一块自己就能触发
            if test(ch):
                命中 = ch; break
        if 命中 is not None:
            items, n = 命中, 2
            log(f"      缩到 {len(items)} 张:{items[:6]}")
            continue
        for ch in 块:                       # ② 去掉这一块,剩下的还触发
            rest = [x for x in items if x not in ch]
            if rest and test(rest):
                命中 = rest; break
        if 命中 is not None:
            items, n = 命中, max(n - 1, 2)
            log(f"      去掉一块后仍红,缩到 {len(items)} 张")
            continue
        if n >= len(items):
            break
        n = min(2 * n, len(items))
    return items


def 定位(conn, plan, cmd, base, root=ROOT, log=lambda *a: None, 上限=24, env=None):
    """二分定位:这条检查是被哪几张表弄红的。返回 (最小表组, 试了几次)"""
    候选 = [t for t in plan["order"] if not plan["tables"][t].get("skip")]
    次数 = [0]

    def test(keep):
        if 次数[0] >= 上限:
            return False
        次数[0] += 1
        doc, n = 灌一批(conn, plan, keep)
        try:
            r = run_check(cmd, root, env=env)
            红 = bool([l for l in r.bad if l not in base.bad]) or r.exit != base.exit
        finally:
            删干净(conn, doc)
        log(f"      试 {len(keep)} 张表 / {n} 行 → {'仍然红' if 红 else '绿'}")
        return 红

    最小 = ddmin(test, 候选, log)
    return 最小, 次数[0]


def 试灌(conn, plan, cmds, root=ROOT, log=print, 定位上限=24, 基线两遍=True,
         env=None, 目标=None):
    """整条闭环:基线 → 整批灌 → 只报变差的 → 逐条二分定位 → 删干净。

    **返回报告,不改方案** —— 该加什么约束是人的判断。
    """
    报告 = {"检查": cmds, "不稳的": [], "对不准的": [], "变差的": [], "干净": True}
    log("拿项目自己的检查当裁判")
    if 目标:
        对不准 = 对准自检(目标, cmds, root, env, log)
        if 对不准:
            报告["对不准的"] = 对不准
            log(f"  ⚠️ **这 {len(对不准)} 条读的不是这个库**(把库藏起来它照样说一切正常),已踢出裁判席:")
            for c in 对不准:
                log(f"     · {c}")
            cmds = [c for c in cmds if c not in 对不准]
            if not cmds:
                log("  没有对得准的检查 —— **一把对着别处量的尺子,和一把好尺子输出一模一样**。\n"
                    "  要么让检查能指定库(环境变量/参数),要么把这批灌到它真正读的那个库(而那通常不该)。")
                return 报告
    base, 抖 = baseline(cmds, root, twice=基线两遍, log=log, env=env)
    if 抖:
        报告["不稳的"] = 抖
        log(f"  ⚠️ **这 {len(抖)} 条自己就不稳,已踢出裁判席**(两遍结果不一样):")
        for c in 抖:
            log(f"     · {c}")
        cmds = [c for c in cmds if c not in 抖]
        if not cmds:
            log("  没有能当裁判的检查了 —— **一把抖的尺子比没有尺子更糟**")
            return 报告
    keep = [t for t in plan["order"] if not plan["tables"][t].get("skip")]
    log(f"\n整批试灌:{len(keep)} 张表")
    doc, n = 灌一批(conn, plan, keep)
    try:
        after = run_all(cmds, root, log, env)
    finally:
        删干净(conn, doc)
    worse = 变差(base, after)
    log(f"  灌了 {n} 行,已删干净")
    if not worse:
        log("\n✅ 项目自己的检查一条都没被这批数据弄红"
            f"(裁判 {len(cmds)} 条 —— **绿有两种:守住了和没走到,所以这里报的是裁判条数**)")
        return 报告
    报告["干净"] = False
    log(f"\n❌ 被这批数据弄红 {len(worse)} 条,逐条定位")
    for cmd, 新增, e0, e1 in worse:
        log(f"\n  ▸ {cmd}(退出码 {e0} → {e1})")
        for l in 新增[:4]:
            log(f"     {l[:110]}")
        猜 = 文字线索(新增, keep)
        log(f"     文字线索(**猜**):{猜 or '报错里一个表名都没有'}")
        最小, 次数 = 定位(conn, plan, cmd, base[cmd], root, log, 定位上限, env)
        证 = 最小 if 次数 < 定位上限 else None
        if 证 is not None and len(最小) < len(keep):
            log(f"     **二分定位(证据,试了 {次数} 次):{最小}** —— 去掉它就绿,加回来就红")
        elif 证 is not None:
            log(f"     二分缩不下去:{len(最小)} 张表一起才触发,或者这条检查对行数本身敏感")
        else:
            log(f"     ⚠️ 试满了 {定位上限} 次还没缩完 —— 只能说「缩到这里」,不是结论")
        报告["变差的"].append({"检查": cmd, "新增的行": 新增[:6], "文字线索(猜)": 猜,
                              "二分定位(证)": 最小, "试了几次": 次数,
                              "到上限了": 证 is None})
    log("\n下一步是**人的判断**:这几张表是该加约束,还是本来就不该进这批。工具不替你拍。")
    return 报告


def 写报告(path, 报告):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(报告, f, ensure_ascii=False, indent=1)
    return path
