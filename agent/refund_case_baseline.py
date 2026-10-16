#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**出事时的基准** —— 三条退款题的题面材料,遮完之后必须和它逐处对得上。

    python3 agent/refund_case_baseline.py            # 比一遍(默认)
    python3 agent/refund_case_baseline.py --冻       # 重新冻结(改了遮蔽口径之后才做)
    python3 agent/refund_case_baseline.py --看       # 只打印现在遮完长什么样

## 这个文件是用户 2026-10-16 加的那条要求

用户在「现取 + 遮蔽」和「另造一条专供评测的押金单」里选了前者,
**而且是看过这句代价之后选的**:「漏遮一处就送分,而且分数变好看没人查」。
所以要求是:

> 拿 `DQ9001` **出事时的样子**做基准,每次遮完都把「遮后看到的」和基准比一遍,
> **有一处对不上就红**。闭环以后再多写一张表、遮蔽没跟上,检查会红,
> 分数不会悄悄变好看。

## 它和遮蔽函数是**两件事**,不是一件事的两半

`knowledge/refund_replay.遮住处置痕迹` 按「这条记录带着这个押金单号」认,
**认不出的一处也不遮,而它不会报错**(和差评那边同一个盲区)。

基准不依赖它认得全:**认不出的记录会出现在遮后的材料里,而基准里没有它 → 红。**
> 遮蔽回答「遮掉了什么」,基准回答「**还有没有没遮到的**」。
> 只有后者能答出「闭环以后新写的那张表漏了没有」—— 因为它**不需要先知道有那张表**。

## 为什么基准里存的是 `T+0 12:46` 而不是 `2026-10-16 12:46`

`tools/shift_world.py` 每天 05:10 把整个世界平移到当天。存绝对日期的话,
**第二天整份基准都对不上** —— 而那是**假红**;假红几次之后这条判据会被人关掉,
然后真的漏遮那天它已经不在了。所以日期一律换成「离世界今天几天」(`refund_replay.归一化`)。

⚠️ 这件事**在副本上真验过**(见 `refund_case_check.py` 第三关):
把副本平移一天,基准照样对得上。不是「应该没问题」。

## 还有一处:**模型够不着的那些,要有东西保证它够不着**

闭环还往 `task.summary` 里写了**模型自己那段错判原文**(`backend/ops.py:682`)——
「渠道在 12:46 连续超时…是系统级渠道故障」。那正是这道题的**错答案**。
它现在够不着(财务角色没挂 `list_tasks`),而「够不着」是**一个名单的当前取值**,
不是一条结构约束 —— 名单改一行它就够得着了,而那一轮的分会变好看。
所以这里**扫财务角色挂的每个工具的源码**,有谁读 `task` / `triage` 表就红。
"""
import argparse, io, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
           os.path.join(ROOT, "mcp"), os.path.join(ROOT, "agentsite")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
import refund_replay as RR
基准文件 = os.path.join(HERE, "refund-case-baseline.json")

# 三条题各自的押金单 —— **从造数脚本那边现取**(它从库里现扫号,不写死)
def 三条单(dbp):
    """按 `退款真因` 的顺序取三笔单。顺序要稳:基准是按单号存的。"""
    c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    r = [x[0] for x in c.execute(
        "SELECT ref_id FROM task WHERE type='财务人工任务' AND ref_id LIKE 'DQ9%' "
        "ORDER BY ref_id LIMIT 3")]
    c.close()
    return r


# 研判真跑时模型用的**角色** —— `agentsite/app.py` 里那一行 `sdk.run("task", prompt)`。
#
# ⚠️⚠️ 2026-10-16 实测:我第一版盯的是**财务**角色(FINANCE_TOOLS,只读账的五个工具),
# 而研判根本不是以财务身份跑的,是**后台运营**。两者差在要紧的地方:
# 后台运营挂着 `list_tasks`,而 `list_tasks` 是 `SELECT *` —— **`summary` 那一列跟着出来**,
# 里面是闭环写进去的 **AI 自己那段错判原文**(`backend/ops.py:682`),也就是这道题的**错答案**。
# > 一个「我核过模型够不着」和一个「我核的是另一个角色」,**在那个 ✅ 上长得一模一样。**
# 所以角色名**在这儿写一次**,并且 `refund_case_check` 盯着 app.py 那一行有没有变。
研判角色 = "task"
研判真跑在 = ("agentsite/app.py", 'sdk.run("task", prompt)')

# 这笔押金单的痕迹可能从哪些表里漏出来。**一张表都不许漏**:
# 判据拿它扫「挂给研判的工具里谁读了这几张表」,扫出来的必须都在下面那份取法登记里。
痕迹在这几张表 = ("task", "triage", "deposit", "refund_trace", "payment_flow")


def _sdk源码名单():
    """把 `agentsite/sdk.py` 里**模块级的字面量名单**全读出来 → {名字: [工具名]}。

    不 `import sdk`:那个文件 `import claude_agent_sdk`,**要 agentsite 的 venv**。
    而这条判据要**无条件进门禁** —— 依赖外部环境的检查会变成随机拦路,
    而「有条件跑」的代价今天刚付过一次(`js_smoke.js` 红了多久都没人知道)。
    """
    import ast
    src = io.open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
    树 = ast.parse(src)
    名单 = {}
    for node in 树.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                getattr(node.targets[0], "id", None):
            try:
                v = ast.literal_eval(node.value)
            except Exception:
                continue
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                名单[node.targets[0].id] = v
    return 名单, 树


def 研判挂的工具():
    """**研判那一轮模型真正挂着的工具** —— 从 `ROLE_TOOLS[研判角色]` 那个 lambda 现解。

    那一行长这样:`"task": lambda: TASK_TOOLS + TASK_ONLY_TOOLS + SHOP_TOOLS`,
    所以这里把 lambda 体里引用的几份名单加起来。

    解不出来就**抛异常**,不返回空名单 —— 空名单会让下面每一关都「通过」,
    而那正是这个项目反复栽的那个形状。
    """
    import ast
    名单, 树 = _sdk源码名单()
    for node in ast.walk(树):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if getattr(k, "value", None) != 研判角色 or not isinstance(v, ast.Lambda):
                continue
            出 = []
            for n in ast.walk(v.body):
                if isinstance(n, ast.Name):
                    if n.id not in 名单:
                        raise AssertionError(
                            f"{研判角色} 角色的工具名单里有一份解不出来的:{n.id} —— "
                            f"覆盖面已经不是这条判据以为的那个")
                    出 += 名单[n.id]
            if 出:
                return 出
    raise AssertionError(f"agentsite/sdk.py 里找不到 {研判角色} 角色的工具名单 —— "
                         f"角色换了名字或名单换了地方,这条判据的覆盖面失效")


def 财务挂的工具():
    """财务角色挂的工具名单 —— **从 `agentsite/sdk.py` 的那份清单现取**。

    ⚠️ 为什么不 `import sdk`:那个文件 `import claude_agent_sdk`,
    **要 agentsite 的 venv 才起得来**。而这条判据要**无条件进门禁** ——
    依赖外部环境的检查进门禁会变成随机拦路,而「有条件跑」的那几条
    今天刚证明过它的代价:`js_smoke.js` 红了多久都没人知道。
    所以这里按**源码里的字面量**读(`ast.literal_eval`),不执行那个模块。

    盲区:名单要是改成**算出来的**(不再是字面量),这里会抛异常 ——
    **抛异常比静默读到空名单好**:空名单会让下面每一关都「通过」。
    """
    import ast
    src = io.open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "FINANCE_TOOLS" for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise AssertionError("agentsite/sdk.py 里找不到 FINANCE_TOOLS 这份名单 —— "
                         "名单换了地方,这条判据的覆盖面已经不是它以为的那个")


def _这笔单的工单(单号):
    """`list_tasks` 里属于这笔单的那一行 —— **只留这一行**。

    整份任务表有两百多条,全存进基准会把它变成一份随库变动的清单(每天假红);
    而要盯的只有「**这笔单的痕迹有没有漏出来**」。
    """
    import api
    return [x for x in api.list_tasks(task_type=RR.工单类型, status=api.看全部任务)
            if x.get("ref_id") == 单号]


# ── 取法登记:**基准盯着的每个工具,在这儿说清「这笔单的那部分怎么取」** ──────
#
# ⚠️ 为什么是一份显式登记,而不是「凡带 deposit_id 的就取」:
# 第一版就是那么写的,于是 `list_tasks` **不在视野里** —— 它不带 deposit_id,
# 而它恰恰是把 AI 错判原文带出来的那一个。
# > 一个「全都比过了」和一个「我只比了我认识的那几个」,**在那个 ✅ 上长得一模一样。**
# 现在反过来:判据扫「挂给研判的工具里谁读了那几张表」,**扫出来的不在这份登记里就红** ——
# 漏登记不再是「静默少比一处」,是一条红。
怎么取 = {
    "get_deposit":      lambda 单: __import__("api").get_deposit(单),
    "get_refund_trace": lambda 单: __import__("api").get_refund_trace(单),
    "get_payment_flow": lambda 单: __import__("api").get_payment_flow(单),
    "list_tasks":       _这笔单的工单,
}


# ── 豁免:**读了那几张表、但带不出这笔单** —— 一条一个理由,而且理由要**还成立** ───────
#
# 这个项目的规矩:豁免名单本身要有判据盯着(`tools/selftest_registry_check.py`
# 那条「豁免名单里没有过期的」)。所以每条豁免带一个**现在还成立吗**的查法,
# 过期了就红 —— 而不是靠谁记得回来删。
def _差评类型():
    """差评那个工单类型名 —— 从 `api.TASK_TYPES` 里认,不手抄字符串。"""
    import api
    return next(t for t in api.TASK_TYPES if "差评" in t)


不用盯的 = {
    "bad_ratings": (
        "它只列差评那一类工单(店长的差评清单),而三条退款题是「{工单类型}」—— "
        "两个类型不相交,它带不出这笔单的任何痕迹;而且它要店长身份,基准取不到它的返回。",
        lambda: _差评类型() in __import__("inspect").getsource(
            getattr(__import__("api"), "bad_ratings"))),
}


def 过期的豁免():
    """哪几条豁免**已经不成立了**。空的才算过。"""
    出 = []
    for 名, (理由, 还成立吗) in 不用盯的.items():
        try:
            ok = bool(还成立吗())
        except Exception as e:
            ok = False
            理由 = f"{理由}(而这条豁免自己的查法崩了:{type(e).__name__}: {e})"
        if not ok:
            出.append((名, 理由))
    return 出


def 读哪几张表(名):
    """这个工具的源码里读了 `痕迹在这几张表` 里的哪几张。返回 (读了哪几张, 扫到源码没有)。

    盲区:只扫这个函数**自己的**源码,不跟进它调的 helper。
    """
    import inspect
    import api
    fn = getattr(api, 名, None)
    if fn is None:
        return (), False
    try:
        src = inspect.getsource(fn)
    except Exception:
        return (), False
    return tuple(t for t in 痕迹在这几张表
                 if __import__("re").search(rf"(FROM|JOIN)\s+{t}\b", src, __import__("re").I)), True


def 没盯着的():
    """挂给研判的工具里,**能带出这笔单痕迹、而基准没盯着**的那些。

    返回 (没盯着的, 扫不到源码的)。两样都要报得出来 ——
    「一个都没有」和「一个都没扫到」在空列表上长得一模一样。
    """
    漏, 没扫到 = [], []
    for 全名 in 研判挂的工具():
        名 = 全名.split("__")[-1]
        表, 扫到 = 读哪几张表(名)
        if not 扫到:
            没扫到.append(名)
            continue
        if 表 and 名 not in 怎么取 and 名 not in 不用盯的:
            漏.append((名, 表))
    return 漏, 没扫到


def 遮完的样子(单号, dbp):
    """走**模型真正走的那一层**(协议层出门那一道),不是直接调 api。

    ⚠️ 这一条是差评那边用一个错换来的:直接调 `api.*` 核遮蔽,返回「遮了 0 处」——
    而遮蔽挂在**协议层出门那一道**,api 那一层不管 env 设不设都原样返回。
    > 一个「遮蔽没生效」和一个「我核的那一层根本不经过遮蔽」,在那个 0 上长得一模一样。
    """
    import api
    import protocol as _proto
    import worldclock as W
    原 = os.environ.get("LANXIU_JUDGING_DEPOSIT")
    出 = {}
    try:
        os.environ["LANXIU_JUDGING_DEPOSIT"] = 单号
        for 名, 取 in sorted(怎么取.items()):
            生 = 取(单号)
            出[名] = _proto.遮被判那笔押金(json.loads(json.dumps(生, ensure_ascii=False)))
    finally:
        if 原 is None:
            os.environ.pop("LANXIU_JUDGING_DEPOSIT", None)
        else:
            os.environ["LANXIU_JUDGING_DEPOSIT"] = 原
    c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    出["出事于"] = RR.出事于(c, 单号)
    c.close()
    return RR.归一化(出, W.今天())


def 视图(dbp=None):
    import api
    dbp = dbp or api.DB
    return {"单": {s: 遮完的样子(s, dbp) for s in 三条单(dbp)}}


# ── 比对 ───────────────────────────────────────────────────────────────
def 比(活, 基):
    """逐处比。返回一串人话的差异,**空的才算过**。

    不用 `==` 一句话判完:那样只能说「不一样」,而要红的时候得答出
    **是哪一处** —— 否则下一个人只能把基准重冻一遍了事,
    而重冻一遍正好把漏遮的那一处变成新基准。
    """
    出 = []

    def 走(a, b, 路):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k not in b:
                    出.append(f"{路}.{k}:**基准里没有这一处**,现在多出来 {json.dumps(a[k], ensure_ascii=False)[:80]}")
                elif k not in a:
                    出.append(f"{路}.{k}:基准里有、现在没了")
                else:
                    走(a[k], b[k], f"{路}.{k}")
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                出.append(f"{路}:条数 基准 {len(b)} → 现在 {len(a)}")
            for i in range(min(len(a), len(b))):
                走(a[i], b[i], f"{路}[{i}]")
            return
        if a != b:
            出.append(f"{路}:基准 {json.dumps(b, ensure_ascii=False)} → 现在 {json.dumps(a, ensure_ascii=False)}")

    走(活, 基, "")
    return 出


def 读基准():
    if not os.path.exists(基准文件):
        return None
    return json.load(io.open(基准文件, encoding="utf-8"))


def 冻(dbp=None):
    import datetime as _dt
    d = 视图(dbp)
    d["冻于"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    d["说明"] = ("三条退款研判题的题面材料 —— **遮完之后出事时的样子**。"
                 "日期是「离世界今天几天」(T±n),因为这个世界每天 05:10 整体平移。"
                 "遮后和这份对不上就红:多出来的那一处就是**漏遮**,而漏遮会让分数变好看。")
    io.open(基准文件, "w", encoding="utf-8").write(
        json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True))
    return d


# ── 模型够不着的那些,扫一遍源码 ─────────────────────────────────────────
def 够得着工单表吗():
    """财务角色挂的工具里,有谁读 `task` / `triage` 表 —— 有就是个送分口。

    ⚠️ **盲区写在这儿**:它扫的是那个函数自己的源码,
    **不跟进它调的别的函数** —— 一个工具靠 helper 读 task 表,这里扫不出来。
    返回 (够得着的, 扫不到源码的) —— 后者要报得出来,
    「一个都没有」和「一个都没扫到」在空列表上长得一模一样。
    """
    import api
    坏, 没扫到 = [], []
    for 全名 in 财务挂的工具():
        名 = 全名.split("__")[-1]
        fn = getattr(api, 名, None)
        try:
            src = inspect.getsource(fn)
        except Exception:
            没扫到.append(名)
            continue
        if re.search(r"FROM\s+task\b|FROM\s+triage\b|JOIN\s+task\b|JOIN\s+triage\b",
                     src, re.I):
            坏.append(名)
    return 坏, 没扫到


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--冻", action="store_true")
    ap.add_argument("--看", action="store_true")
    ap.add_argument("--库", default=None)
    a = ap.parse_args()
    if getattr(a, "冻"):
        d = 冻(a.库)
        print(f"{G}已冻结{D} {基准文件} —— {len(d['单'])} 笔单")
        raise SystemExit(0)
    活 = 视图(a.库)
    if getattr(a, "看"):
        print(json.dumps(活, ensure_ascii=False, indent=1))
        raise SystemExit(0)
    基 = 读基准()
    if 基 is None:
        print(f"{R}❌ 还没有基准文件 —— 先 `--冻`{D}")
        raise SystemExit(1)
    差 = 比(活["单"], 基["单"])
    for x in 差:
        print(f"  {R}✗{D} {x}")
    print(("✅ 遮后的材料和出事时的基准逐处对得上" if not 差
           else f"{R}❌ {len(差)} 处对不上{D}"))
    raise SystemExit(1 if 差 else 0)
