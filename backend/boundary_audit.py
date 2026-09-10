#!/usr/bin/env python3
"""边界审计 —— 这个项目对外说过的每条保证,到底靠什么成立?

## 为什么要有这个文件

这个项目做到今天,累了很多「保证」:工具全部只读、真值表不外泄、
预算封顶、无同意取不到身体数据、成长方案必须带区间……

但**从来没有一份清单说明每条保证靠什么成立**。而它们其实分三类:

  结构  做不到 —— 试了会失败(只读连接、运行时拦截、Hook 拦下)
  检查  做得到,但提交前会被抓 —— 一道测试守着(guards / pinned / scan)
  约定  只是「不该做」—— 提示词里写着,**没有任何东西会失败**

三类在平时长得一模一样,**直到换个人、换个模型、隔三个月**。
这个项目已经被这件事咬过三次:

  ① 「工具全部只读」曾经是破的 —— allowed_tools 不是排他白名单,
     内置 Bash 一直在场,只是 DeepSeek **碰巧**没去用
  ② 新工具挂了 MCP 却没进白名单 —— 靠**人记得**同步两个文件
  ③ 密钥扫描规则连着三次匹配自己 —— 靠**人记得**加排除项

一件事出三次就不是运气,是系统性缺口:**这些边界都建立在
「会记得做对」上,而不是「做错了会失败」上。**

## 这个文件怎么保证自己不烂

**静态文档会烂,可执行的不会。**
所以「结构」类的每一条,下面都有一段代码**真的去攻击它一次** ——
攻击成功就是边界破了,当场红。

一条声称「靠结构」却从没被攻击过的保证,**实际上仍然只是约定**。
"""
import os, sys, sqlite3, re, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite"),
                os.path.join(ROOT, "agent")]
import api, ops, guards

SDK_SRC = open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()


def _must_fail(fn, *exc):
    """攻击必须失败。成功了 = 边界破了。"""
    try:
        r = fn()
    except exc or (Exception,):
        return True, "被拦下"
    return False, f"**攻击成功,边界是破的**(返回 {str(r)[:60]})"


def _consent_off(wid, scope=None):
    c = sqlite3.connect(api.DB)
    q = "UPDATE consent SET revoked_at='2026-08-01' WHERE wearer_id=?" + (
        " AND scope=?" if scope else "")
    c.execute(q, (wid, scope) if scope else (wid,)); c.commit(); c.close()


def _consent_on(wid):
    c = sqlite3.connect(api.DB)
    c.execute("UPDATE consent SET revoked_at=NULL WHERE wearer_id=?", (wid,))
    c.commit(); c.close()


# ── 结构类:攻击必须失败 ────────────────────────────────────────────────
def a_insert_schedule():
    """绕开 tasks.py,拿只读连接直接塞一条任务进去。"""
    return api._rows("INSERT INTO schedule(id,type,status) VALUES('SC-HACK','日常运维','有效')")


def a_write_role_param():
    """给写工具传身份参数试图提权 —— 签名里没有,应该直接 TypeError。"""
    import inspect
    for n in api.WRITE_TOOLS:
        sig = inspect.signature(inspect.unwrap(api.TOOLS[n]))
        for bad in ("role", "actor", "operator", "as_user", "me"):
            if bad in sig.parameters:
                return f"{n} 的入参里居然有 {bad} —— 一句「我以店长身份」就能提权"
    raise TypeError("写工具的签名里没有身份参数(这正是期望的)")


def _verdict(name, reads=(), writes=()):
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "agentsite"))
    import guards as _g
    return _g.pre_tool_verdict(name, {}, state_reads=list(reads), state_writes=list(writes))


def a_double_write():
    """一轮里连着写两次 —— 第二次必须被拦。"""
    W = "mcp__shop__assign_task"
    v = _verdict(W, reads=["mcp__shop__task_types"], writes=[W])
    if not v: return "同一轮里连着写第二次居然放行了"
    raise PermissionError(v)


def a_blind_assign():
    """没调 task_types 就派任务 —— 必须被拦。"""
    v = _verdict("mcp__shop__assign_task", reads=[], writes=[])
    if not v: return "没查类型就派任务居然放行了"
    raise PermissionError(v)


def a_write():
    return api._rows("UPDATE customer SET name='被改了' WHERE id='C10000'")

def a_truth_from():   return api._rows("SELECT * FROM truth")
def a_truth_join():   return api._rows("SELECT t.id FROM task t JOIN truth u ON u.case_id=t.id")
def a_truth_case():   return api._rows("select ROOT_CAUSE from TRUTH limit 1")

def a_cred_direct(): return api._rows("SELECT pwd_hash FROM account")
def a_cred_case():   return api._rows("select PWD_SALT from ACCOUNT")
def a_cred_star():   return api._rows("SELECT * FROM account")
def a_cred_alias():  return api._rows(
    "select a.* from account a join wearer w on w.account_id=a.id")
def a_cred_sub():    return api._rows(
    "SELECT p AS x FROM (SELECT pwd_hash p FROM account) t")


_PH = __import__("re").compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def a_phone_leak():
    """把每个工具都调一遍,只要返回里出现完整手机号就算破了。

    **这条以前是「约定」** —— `_mask()` 全项目只被调用一次,
    「对外一律脱敏」全靠工具作者记得。现在包在工具出口上,
    **新加的工具默认就是脱敏的**。
    """
    import json as _j
    hit = []
    for name, fn in api.TOOLS.items():
        for args in ({}, {"customer": "C10001"}, {"status": "待确认"},
                     {"customer_id": "C10000"}, {"account": "C10001"}):
            try: r = fn(**args)
            except Exception: continue
            m = _PH.search(_j.dumps(r, ensure_ascii=False, default=str))
            if m: hit.append(f"{name} → {m.group()}")
    if hit: return "工具返回里出现完整手机号:" + "; ".join(hit[:3])
    raise PermissionError(f"{len(api.TOOLS)} 个工具的返回全部脱敏")


def a_bash():
    v = guards.pre_tool_verdict("Bash", {"command": "ls"})
    if v: raise PermissionError(v)
    return "Bash 放行了"

def a_task():
    v = guards.pre_tool_verdict("Task", {})
    if v: raise PermissionError(v)
    return "Task 放行了"

def a_consent_body():
    _consent_off("W10010-2")
    try:
        r = api.forecast_growth("W10010-2")
        if r.get("error"): raise PermissionError(r["error"])
        return r
    finally: _consent_on("W10010-2")

def a_consent_minor():
    _consent_off("W10010-2", "未成年人")
    try:
        r = api.forecast_growth("W10010-2")
        if r.get("error"): raise PermissionError(r["error"])
        return r
    finally: _consent_on("W10010-2")

def a_expired_order():
    b = ops.order_block("W10010-2")
    if not b["放行"]: raise PermissionError(b["原因"])
    return b

def a_whitelist():
    for ns, sch in (("kb", api.KB_SCHEMAS), ("shop", api.SHOP_SCHEMAS), ("task", api.SCHEMAS)):
        white = set(re.findall(r'"mcp__%s__(\w+)"' % ns, SDK_SRC))
        real = {x["name"] for x in sch}
        if white != real:
            # 约定:返回 = 攻击成功 = 边界破了;抛异常 = 被拦下 = 边界完好
            return f"{ns} 白名单与 MCP 暴露不一致:{sorted(white ^ real)}"
    raise PermissionError("白名单与 MCP 暴露完全一致")

def a_budget():
    if "max_budget_usd=MAX_USD" not in SDK_SRC: return "没传预算上限"
    raise PermissionError("预算上限已传入 options")

def a_disallowed():
    miss = [t for t in ("Bash", "Write", "Edit", "Read", "Task", "WebFetch")
            if f'"{t}"' not in SDK_SRC]
    if miss: return f"disallowed_tools 漏了 {miss}"
    raise PermissionError("危险内置工具已在 disallowed_tools 里点名")

def a_strict_mcp():
    if "strict_mcp_config=True" not in SDK_SRC: return "没开 strict_mcp_config"
    declared = set(json.load(open(os.path.join(ROOT, ".mcp.json")))["mcpServers"])
    code = set(re.findall(r'"(kb|shop|task)":\s*\{', SDK_SRC)) or {"kb", "shop", "task"}
    if declared & code: return f".mcp.json 的服务名和代码声明重合:{declared & code}"
    raise PermissionError(f".mcp.json 声明的 {sorted(declared)} 全被忽略,只认代码里的")


def a_workorder_ro():
    """get_workorder 只读 —— 拿它的返回去改交期,改不动。"""
    import api
    r = api.get_workorder(workorder_id="WO8001")
    if not (r.get("rows")): raise PermissionError("没有可攻击的工单(夹具不成立)")
    try:
        api._rows("UPDATE workorder SET due_date='2099-01-01' WHERE id=?", "WO8001")
    except Exception:
        raise PermissionError("连接开成 mode=ro,改交期直接抛 —— 不是碰巧没人写 UPDATE")
    return "居然写进去了"


def a_lifecycle_no_manual():
    """生命周期是**算法型状态机**,不接受手工流转 —— 工具层给不出改档的路径。"""
    import api
    if any("lifecycle" in n and ("set" in n or "update" in n) for n in api.TOOLS):
        return "工具层出现了改生命周期的接口"
    r = api.get_lifecycle(customer="C10001")
    if not r.get("rows"): raise PermissionError("查不到客户(夹具不成立)")
    row = r["rows"][0]
    if "系统重算值" not in row:
        return "返回里没有「系统重算值」—— 人工覆盖和重算值分不开,就没法判断哪个在生效"
    raise PermissionError("工具层没有任何改档接口,且人工覆盖与系统重算值分开返回")


def a_rfm_cross_group():
    """RFM 是**相对分**:同一个人在不同人群里分数不同 —— 这是设计,不是 bug。
    审计这一条是为了钉住「跨档比较无意义」这个事实是**可验证的**,不只是提示词说说。"""
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(ROOT, "knowledge"))
    import rfm as _rfm
    import api
    a = {r["id"]: r for r in _rfm.score(api._rows(
        "SELECT id,idle_days,orders_12m,amount_12m FROM customer WHERE lifecycle='潜在流失'"))}
    b = {r["id"]: r for r in _rfm.score(api._rows(
        "SELECT id,idle_days,orders_12m,amount_12m FROM customer"))}
    both = [k for k in a if k in b and a[k]["RFM"] != b[k]["RFM"]]
    if not both:
        return "同一个人在两个人群里分数完全一样 —— 那它就不是相对分,跨档比较的禁令没有依据"
    raise PermissionError(
        f"同一个人换个人群分数就变({both[0]}: 档内 {a[both[0]]['RFM']} vs 全量 {b[both[0]]['RFM']})"
        " —— **跨档比较无意义是可验证的事实,不是提示词的一句话**")


def a_check_write_noop():
    """check_write 名字里带 write,必须证明它**真的不写** ——
    跑一次「校验通过」的建档,库里的行数一行都不能多。
    (校验通过那条更要紧:被拒的当然不会写,通过的才是危险的那一半。)"""
    import api, sqlite3
    n0 = api._rows("SELECT count(*) c FROM customer")[0]["c"]
    r = api.check_write("建档", {"name": "边界审计·勿动", "phone": "13800009999",
                                 "shop": "SH001 静安旗舰店"})
    if r.get("能不能做") != "能":
        raise PermissionError(f"这次校验没通过({r.get('编码')}),换个夹具才测得到「通过也不写」")
    n1 = api._rows("SELECT count(*) c FROM customer")[0]["c"]
    if n1 != n0: return f"校验通过后库里多了 {n1-n0} 行 —— 它在写库"
    raise PermissionError("validate_* 是纯函数,校验通过也一行没写")


def a_default_allow_visible():
    """「默认放行」必须在返回里自己说出来 —— 不能和「人工确认过」长得一样。

    2025 格里有 1274 格的依据是 `—`:**只是没命中任何禁止规则**,没有人验证过。
    它们的 verdict 全是「可」。不标出来的话,它和 16 格打样确认过的在返回里
    完全一致,而模型只能照着「可」讲给客户听。

    **兜底方向选错,未知就会被打扮成已知** —— 这里未知被默认算成了「可以做」。
    """
    import api
    r = api._rows("SELECT craft,material FROM craft_combo WHERE (rule IS NULL OR rule='—') LIMIT 1")
    if not r: raise PermissionError("库里没有无依据的格子了(那也很好)")
    kb = api._rows("SELECT name FROM craft WHERE code=?", r[0]["craft"])[0]["name"]
    mb = api._rows("SELECT name FROM craft WHERE code=?", r[0]["material"])[0]["name"]
    d = api.kb_combo(craft=kb, material=mb)
    if d.get("verdict") != "待核实":
        return (f"无依据的格子仍然给了结论({d.get('verdict')!r})—— "
                "「没查到禁止」和「确认可以」是两回事")
    if "不给结论" not in (d.get("依据等级") or ""):
        return "verdict 改了但依据等级没说清为什么"
    raise PermissionError("无依据的格子**不给结论**,verdict 返回「待核实」并记入队列 —— "
                          "偏错的代价不对称:说「可以」赔工期料钱,说「待核实」多打个电话")


def a_review_readonly():
    """待核实队列:模型**看得见,填不了**。

    回流这件事天然要写。如果让模型的工具去写,「工具层一个写接口都没有」
    那条保证当场就破 —— 而它是靠 mode=ro 连接结构性成立的,不是靠自觉。
    所以拆成两半:记一笔走**日志文件**(旁路),回填走**后台**(那边本来有写权限)。
    这里攻击的正是这条边界。
    """
    import api
    # ① 工具层不许出现任何能改矩阵的接口
    bad = [n for n in api.TOOLS if any(w in n for w in ("resolve", "fill", "update", "set_"))]
    if bad: return f"工具层出现了疑似写接口:{bad}"
    # ② 队列工具真的只读:调一次,矩阵里那一格一个字都不能变
    q = api.get_review_queue(top=1)
    row = (q.get("rows") or [None])[0]
    if row:
        before = api._rows("SELECT verdict,rule FROM craft_combo WHERE craft=? AND material=?",
                           row["craft"], row["material"])
        api.get_review_queue(top=1)
        after = api._rows("SELECT verdict,rule FROM craft_combo WHERE craft=? AND material=?",
                          row["craft"], row["material"])
        if before != after: return "看一眼队列就把矩阵改了"
    # ③ 拿工具层的连接去回填,必须抛
    try:
        api._rows("UPDATE craft_combo SET rule='人工确认' WHERE craft='KF01'")
    except Exception:
        raise PermissionError("工具层没有回填接口,而且拿它的连接去 UPDATE 直接抛 —— "
                              "回填只能走后台 /api/combo-resolve(要工艺负责人及以上 + 必须写理由)")
    return "工具层的连接居然能改矩阵"


STRUCT = [
 # ⚠️ 这条原来叫「工具层一个写接口都没有」。加了 assign_task / dispatch_task /
 # finish_task 之后那个名字就**变成假的了**,而测试照样通过 ——
 # 它测的一直是「读连接不能写」,不是「没有写接口」。
 # **一条断言正确、名字过时的检查,比没有检查更危险**:它每次都绿,
 # 而看的人以为绿的是名字上那件事。改保证的时候要回来改名字。
 ("工具层的读连接写不了库", "backend/api.py 开篇铁律 —— 读一律走 mode=ro 连接",
  a_write, "拿工具层的连接去 UPDATE 一条客户记录",
  "连接开成 mode=ro —— **写操作直接抛错,不是碰巧没人写 INSERT**。"
  "要写只能走 tasks.py 那条明路,那条路上有身份判定和台账"),
 ("写只能走明路 —— 读连接连 INSERT 都不行", "backend/api.py _rows / backend/tasks.py",
  a_insert_schedule, "拿工具层的读连接直接 INSERT 一条任务",
  "绕开 tasks.py 就等于绕开身份判定和台账 —— **结构上不给这条路**"),
 ("写工具不收身份参数", "backend/api.py WRITE_TOOLS / isolation_check",
  a_write_role_param, "给写工具传一个 role='店长' 参数试图提权",
  "签名里根本没有这个参数 —— **提权不是被拒绝,是无从表达**。"
  "有这个参数的话,一句「我以店长身份执行」就成立了"),
 ("一轮只写一次", "agentsite/guards.py pre_tool_verdict 写工具的闸",
  a_double_write, "同一轮里连着调两次 assign_task",
  "第二次被 PreToolUse 拦下 —— 提示词里那条「一次只做一件」只是祈使句,"
  "**hook 才是强制**。连着写好几条,其中一条参数猜错的话,几条都已经落库了"),
 ("没查类型不许派任务", "agentsite/guards.py pre_tool_verdict",
  a_blind_assign, "不调 task_types 直接调 assign_task",
  "被拦 —— 类型决定挂哪张单据、完成时要不要传图。**没查就派**,"
  "派出去的东西和正常任务长得一模一样,错了也看不出来"),
 ("待核实队列:模型看得见,填不了", "backend/api.py get_review_queue / server.py resolve_combo",
  a_review_readonly, "在工具层找回填接口;调一次队列看矩阵变没变;拿工具层连接去 UPDATE",
  "回流拆成两半 —— **记一笔走日志文件(旁路),回填走后台**。"
  "让模型去写待办,只读保证当场就破"),
 ("无依据的格子不给结论", "backend/api.py _combo_caveat",
  a_default_allow_visible, "随便取一格 rule='—' 的组合,看它还给不给结论",
  "verdict 返回「待核实」并记入待办队列 —— **1274 格(63%)属于这一类**"),
 ("check_write 只校验不写库", "backend/api.py check_write 文档 / 工具描述「不写库」",
  a_check_write_noop, "跑一次**校验会通过**的建档,数客户表行数有没有变",
  "validate_* 是纯函数 —— **被拒的当然不写,通过的才是危险那一半**,这里测的正是后者"),
 ("在制工单只读 —— 不能改期不改派", "prompts.py 铁律 TW05 / 工具描述「这个工具只读」",
  a_workorder_ro, "拿工具层的连接把 WO8001 的交期改到 2099 年",
  "同 mode=ro 那条锁 —— 工坊角色**结构上就改不了**排产,不靠它自觉"),
 ("生命周期不接受手工流转", "后台 PRD 6.1「算法型状态机」/ 铁律 TK08",
  a_lifecycle_no_manual, "在工具层找一个能改档位的接口;并检查人工覆盖有没有和重算值混在一起",
  "工具层没有改档接口;且「人工覆盖生效」与「系统重算值」**分开返回** —— "
  "混在一起的话,没人分得清眼前这个档是算出来的还是人改的"),
 ("RFM 跨档比较无意义", "prompts.py 铁律 TK09 / knowledge/rfm.py 模块开篇",
  a_rfm_cross_group, "把同一个客户放进「档内」和「全量」两个人群各打一次分,看分数变不变",
  "**分数真的会变** —— 这条禁令有可验证的事实撑着,不是提示词的一句话"),
 ("truth 表不经工具层暴露 · 直查", "backend/api.py 开篇铁律",
  a_truth_from, "SELECT * FROM truth", "任何提到 truth 的 SQL 一律拒绝执行"),
 ("truth 表不经工具层暴露 · JOIN 绕过", "同上",
  a_truth_join, "写成 JOIN truth,绕开只认 FROM 的旧检查",
  "**这一条原来是破的** —— 旧检查是 `re.findall(r'FROM\\s+(\\w+)')`,只认 FROM;"
  "而 ops.py 里就是 JOIN 写法。改成运行时按语句内容拦"),
 ("truth 表不经工具层暴露 · 大小写", "同上",
  a_truth_case, "select … from TRUTH", "正则带 re.I,不看大小写"),
 ("账户凭据不经工具层暴露 · 直查", "backend/api.py 锁三 / 个保法敏感信息",
  a_cred_direct, "SELECT pwd_hash FROM account",
  "语句文本命中 pwd_ 就快速失败"),
 ("账户凭据不经工具层暴露 · 大小写", "同上", a_cred_case, "select PWD_SALT from ACCOUNT",
  "正则带 re.I"),
 ("账户凭据不经工具层暴露 · 星号", "同上", a_cred_star, "SELECT * FROM account",
  "**查的是返回的列名,不是语句写法** —— 星号会把 pwd_* 带出来"),
 ("账户凭据不经工具层暴露 · 别名星号", "同上", a_cred_alias,
  "select a.* from account a join wearer w …",
  "**这条第一版是破的** —— 当时只正则匹配 `select * from account`,"
  "带别名就绕过去了。改成查结果列名,与写法无关"),
 ("账户凭据不经工具层暴露 · 子查询改名", "同上", a_cred_sub,
  "SELECT p AS x FROM (SELECT pwd_hash p FROM account) t",
  "两道锁各管一段:这条被语句文本那道接住"),
 ("对外一律脱敏手机号", "数据规范 F3",
  a_phone_leak, "把 23 个工具全调一遍,搜返回里的完整手机号",
  "**包在工具出口上,不是每个函数各自记得** —— "
  "库里是真的,离开工具那一刻才脱敏;内部对账照常拿真号。"
  "⚠️ **诚实说明:现存的 23 个工具本来就没有一个会吐真号** —— "
  "这层包装防的是**未来新加的工具**。所以它的咬合方式是"
  "「临时加一个会吐真号的工具,看包装拦不拦得住」,"
  "而不是「拆掉包装看漏不漏」(现在拆了也不漏)"),
 ("模型不能执行命令", "prompts.py 铁律 TL05「你没有任何写权限」",
  a_bash, "让 PreToolUse 判定 Bash 工具", "非 mcp__ 开头的工具一律拦下(Hook 运行时)"),
 ("模型不能开子智能体", "同上", a_task, "让 PreToolUse 判定 Task 工具", "同上"),
 ("配置层也点名封了内置工具", "sdk.py disallowed_tools",
  a_disallowed, "检查危险工具是否都在 disallowed_tools 里",
  "**双锁**:配置一道 + Hook 一道。配置会被人改错,Hook 是兜底"),
 ("无有效同意 → 取不到身体数据", "12-成长与生命周期.md 第七节 / 个保法 28 条",
  a_consent_body, "撤销身体数据同意后调推算", "工具层硬门,不靠模型自觉"),
 ("不满 14 周岁缺监护人同意 → 不能推算", "同上 / 个保法 31 条",
  a_consent_minor, "只撤未成年人同意后调推算", "工具层硬门"),
 ("量体超期 → 下单被拦", "12-成长与生命周期.md 第五节",
  a_expired_order, "拿一个量体已过期的孩子走下单前拦截", "ops.order_block 规则直出"),
 ("白名单与 MCP 暴露完全一致", "skills_check.py",
  a_whitelist, "比对两边集合", "**这一条漏过一次**(新工具挂了 MCP 没进白名单)"),
 ("单次会话预算封顶", "sdk.py MAX_USD",
  a_budget, "检查 max_budget_usd 是否传进 options", "SDK 层强制,超了直接停"),
 ("MCP 只认代码里声明的服务", "sdk.py strict_mcp_config",
  a_strict_mcp, "比对 .mcp.json 与代码声明的服务名",
  "两边名字完全不同 —— 名字对不上,正好**证明** .mcp.json 真的被忽略了"),
]

# ── 检查类:结构上做得到,但有一道检查会在提交前抓住 ────────────────────
CHECKED = [
 ("回答必须带区间 / 限定 / 复量 / 转人工", "guards g10–g15",
  "43 条正反用例(该拦 21 / 不该拦 22),`agentsite/guards_test.py`"),
 ("报价单免责必须齐全", "guards g9", "同上,含「需评估」「需补量」「香云纱雨季」三种触发"),
 ("成长方案六段必须齐全", "guards g15", "Skill 定格式,Hook 保证格式被遵守"),
 ("密钥不进仓库", "tools/scan_secrets.sh", "push 前跑;规则文件自身排除"),
 ("知识 md 与库一致", "derive_combo.py / derive_pattern.py", "2025 格 + 1181 条尺码逐条对账"),
 ("锚点不来自被测系统(防同源谬误)", "pinned_check.py", "13 条手抄常数,故意不现算"),
 ("不得建议绕过审批链 / 幂等号 / 重试上限", "guards g16",
  "**本次审计补的锁** —— 原来只有提示词守着,而这条涉及钱:"
  "幂等号复用会重复退款,跳过审批会绕开双人复核,两者都不可逆"),
]

# ── 约定类:只有提示词说,没有任何东西会失败 ────────────────────────────
CONVENTION = [
 # 这一条是**新补的,而且是主动认领的**:它以前根本没被记下来,
 # 因为我从没声称过它是保证 —— 但「没写下来的约定,和结构锁在平时长得一模一样」。
 ("智能体调工具时没有身份", "backend/api.py check_write 文档",
  "MCP 工具跑在 CLI 拉起的**子进程**里,拿不到后台的登录会话 —— "
  "所以 check_write 答的永远是「**如果是**这个角色」,不是「**你**这个人」。"
  "真执行那一关在后台写接口上(role 从会话取,已是结构),"
  "但**智能体这一侧的角色是调用方说了算**。要补成结构,得把会话身份透传进 MCP 子进程。"),
 ("只说知识库里查到的,不得凭训练知识作答", "prompts.py 铁律 TL01",
  "g1 只抓「报了数字却没调工具」——**换个不带数字的说法就漏**,"
  "比如「云锦这种料子一般比较厚重」"),
 ("区分「不能做」和「不建议做」", "prompts.py 铁律 TL04", "没有任何检查"),
 ("换面料必须让客户确认,不能替他决定", "prompts.py 铁律 TL11", "没有任何检查"),
 ("demo 级来源不可作为对客户的承诺", "prompts.py 铁律 TL03",
  "g1 查了来源标注,但没查「拿 demo 数据做承诺」"),
]


def run():
    print("边界审计 —— 每条保证靠什么成立\n" + "=" * 92)
    bad = []
    print(f"\n【结构】做不到 —— 下面每一条都**真的攻击了一次**,攻击必须失败({len(STRUCT)} 条)\n")
    for name, src, atk, how, why in STRUCT:
        ok, msg = _must_fail(atk)
        if not ok: bad.append((name, msg))
        print(f"  {'✅' if ok else '❌'} {name}")
        print(f"      攻击:{how} → {msg}")
        print(f"      靠什么:{why}")
        print(f"      出处:{src}")
    print(f"\n【检查】做得到,但提交前会被抓({len(CHECKED)} 条)\n")
    for name, by, ev in CHECKED:
        print(f"  ◆ {name}\n      守它的:{by} —— {ev}")
    print(f"\n【约定】**没有任何东西会失败**({len(CONVENTION)} 条)\n")
    for name, src, gap in CONVENTION:
        print(f"  ⚠ {name}\n      只有:{src}\n      缺口:{gap}")

    print("\n" + "=" * 92)
    print(f"  结构 {len(STRUCT)} · 检查 {len(CHECKED)} · 约定 {len(CONVENTION)}")
    print("  **约定类不是错误,是已知风险。** 但它必须被写下来 ——")
    print("  没写下来的约定,和结构锁在平时长得一模一样,直到有一天不一样。")
    if bad:
        print(f"\n❌ {len(bad)} 条声称靠结构的保证,攻击成功了:")
        for n, m in bad: print(f"   · {n}:{m}")
        return 1
    print(f"\n✅ {len(STRUCT)} 条结构性保证全部扛住了攻击")
    return 0


def to_md():
    """把同一份数据投影成 Markdown。**不手写第二份** —— 两张表一定漂。"""
    L = ["# 安全边界审计",
         "",
         "> 由 `backend/boundary_audit.py --md` 生成,不要手改。",
         "> 数据只有一份,这份文档是它的投影 —— 手写第二份就一定会漂。",
         "",
         "## 为什么做这次审计",
         "",
         "这个项目累了很多「保证」,但**从来没有一份清单说明每条保证靠什么成立**。",
         "而它们其实分三类,平时长得一模一样,**直到换个人、换个模型、隔三个月**:",
         "",
         "| 类别 | 意思 | 违反时会怎样 |",
         "|---|---|---|",
         "| **结构** | 做不到 | 试了就失败 |",
         "| **检查** | 做得到,但提交前会被抓 | 检查变红,人来看 |",
         "| **约定** | 只是「不该做」 | **什么都不会发生** |",
         "",
         "触发这次审计的是三件事,形状完全一样:",
         "",
         "1. 「工具全部只读」曾经是破的 —— 内置 Bash 一直在场,只是当时那个模型**碰巧**没去用",
         "2. 新工具挂了 MCP 却没进白名单 —— 靠**人记得**同步两个文件",
         "3. 密钥扫描规则连着三次匹配自己 —— 靠**人记得**加排除项",
         "",
         "一件事出三次就不是运气,是系统性缺口:",
         "**这些边界都建立在「会记得做对」上,而不是「做错了会失败」上。**",
         "",
         "## 这份清单怎么保证自己不烂",
         "",
         "静态文档会烂,可执行的不会。",
         "下面「结构」类的每一条,`boundary_audit.py` 里都有一段代码**真的去攻击它一次** ——",
         "攻击成功就当场红,`check.sh` 每次都跑。",
         "",
         "**一条声称「靠结构」却从没被攻击过的保证,实际上仍然只是约定。**",
         "",
         f"## 一、结构 —— 做不到({len(STRUCT)} 条)",
         "",
         "| 保证 | 怎么攻击它 | 靠什么挡住 |",
         "|---|---|---|"]
    for name, src, atk, how, why in STRUCT:
        L.append(f"| **{name}** | {how} | {why} |")
    L += ["",
          f"## 二、检查 —— 做得到,但提交前会被抓({len(CHECKED)} 条)",
          "",
          "| 保证 | 守它的 | 怎么守 |", "|---|---|---|"]
    for name, by, ev in CHECKED:
        L.append(f"| {name} | `{by}` | {ev} |")
    L += ["",
          f"## 三、约定 —— 没有任何东西会失败({len(CONVENTION)} 条)",
          "",
          "**这一节不是错误清单,是已知风险清单。**",
          "写下来的目的不是消灭它们 —— 有些确实不值得为它写检查 ——",
          "而是让它们**不再冒充结构锁**。",
          "",
          "| 保证 | 只有 | 缺口在哪 |", "|---|---|---|"]
    for name, src, gap in CONVENTION:
        L.append(f"| {name} | {src} | {gap} |")
    L += ["",
          "## 这次审计改了什么",
          "",
          "| 原来 | 现在 |",
          "|---|---|",
          "| 工具层「没人写 INSERT」 | 连接开成只读,**写操作直接抛错** |",
          "| truth 表靠一行只认 `FROM` 的正则 | 运行时按语句内容拦,**JOIN / 大小写都拦得住** |",
          "| PreToolUse 判定藏在 async hook 里,离线测不到 | 抽成纯函数,审计可以直接攻击它 |",
          "| 「不得绕过审批链」只有提示词 | 补了一道体检 —— **这条涉及钱** |",
          "| 没有清单 | 这份清单,而且它是可执行的 |",
          "",
          "## 一句话",
          "",
          "**安全不是「我们不会那么做」,是「那么做会失败」。**",
          "",
          "剩下那几条约定不是失败,是**明知道的欠账**。",
          "欠账写在账本上和不写在账本上,是两回事。"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    if "--md" in sys.argv:
        print(to_md(), end=""); sys.exit(0)
    sys.exit(run())
