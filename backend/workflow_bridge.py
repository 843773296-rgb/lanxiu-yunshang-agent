# -*- coding: utf-8 -*-
"""AI 管理后台的工作流来要的两件事 —— **用澜绣自己的函数执行**(2026-10-24,音频整理全流程)。

管理后台绝不碰澜绣的库:它的工作流跑到「取转写」「写跟进」时只在它那边记一张桥请求、挂起;
`tools/supervise_sync.py` 每轮把待执行的单拉回来,交给这里执行,再回执。和产出打回同一个形状。

    取转写(call_id)                       → 这通录音的转写原文(人工校对过的以校对后为准)
    写跟进(参数, 幂等键, 谁)               → 客户档案里一条正式跟进(server.create_followup 那条正门)

## 写跟进的三道闸(用户 10-24 拍「核对即定稿,直接写跟进」)

① **同一个幂等键只写一条**:管理后台那边一次挂起一张单,但回执可能没送到、下一轮又拉到同一张 ——
   重试写出第二条跟进,而跟进是只增不改的流水,写错了删不掉。键记在台账 ctx 里,写之前先查。
② **录音必须是这个客户的**:单上同时带着通话号和客户号,两个对不上就拒 ——
   把 A 客户电话里的需求记到 B 客户名下,比不记更糟(B 的顾问会照着去联系)。
③ 客户必须存在、内容不能空(create_followup 自己那两道)。

「核对过没有」由管理后台那一侧的执行闸守(runtime/桥闸.py:只认人工节点的批准),
这里不重复判 —— 这边看不到那次运行,硬判只能信单子上写的字,而单子上的字谁都能写。
"""
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")


def _连(db):
    c = sqlite3.connect(db or DB)
    c.row_factory = sqlite3.Row
    return c


def _失败(code, 消息, 建议=None):
    return {"失败": {"code": code, "消息": 消息, **({"建议": 建议} if 建议 else {})}}


def 取转写(参数, db=None):
    """→ {"输出": {...}} 或 {"失败": {...}}"""
    cid = str((参数 or {}).get("call_id") or "").strip()
    if not cid:
        return _失败("MISSING", "没给通话号")
    c = _连(db)
    try:
        a = c.execute("SELECT id, customer_id, seconds, channel, status, fail_reason FROM call_audio WHERE id=?",
                      (cid,)).fetchone()
        if not a:
            return _失败("CALL_NOT_FOUND", f"没有 {cid} 这通录音", "核一下通话号")
        t = c.execute("SELECT text, edited_by FROM call_transcript WHERE audio_id=?", (cid,)).fetchone()
        if not t:
            # 排队 / 转写中 / 失败 —— 说清是哪一种,别一律写「没有转写」
            st = a["status"] or "没有转写"
            return _失败("NO_TRANSCRIPT", f"{cid} 还没有转写稿(状态:{st}"
                         + (f",{a['fail_reason']}" if a["fail_reason"] else "") + ")",
                         "等转写完成再跑;失败的要先在录音页重新转写")
        adv = c.execute("SELECT advisor_no FROM customer WHERE id=?", (a["customer_id"],)).fetchone()
        return {"输出": {"text": t["text"], "call_id": cid, "customer_id": a["customer_id"],
                       "顾问": adv["advisor_no"] if adv else None, "时长秒": a["seconds"],
                       "人工改过": bool(t["edited_by"])}}
    finally:
        c.close()


def _写过的(幂等键, db):
    c = _连(db)
    try:
        for r in c.execute("SELECT target, ctx FROM op_log WHERE machine='followup' AND code='CREATE' "
                           "AND ctx LIKE ? ORDER BY id DESC", (f"%{幂等键}%",)):
            try:
                if json.loads(r["ctx"] or "{}").get("幂等键") == 幂等键:
                    return r["target"]
            except ValueError:
                continue
        return None
    finally:
        c.close()


def 写跟进(参数, 幂等键, 谁, db=None, 办事人=None, 工号=None):
    """→ {"输出": {跟进号, customer_id, 是新写的, 结果}} 或 {"失败": {...}}

    办事人 / 工号(2026-10-24 账号绑定,用户拍「一对一绑定」):管理后台里批准核对的那个账号,和他绑定的澜绣工号。
    **台账以这位员工的名义记,管理后台账号一起记上**;没绑定就不写 —— 不拿服务身份顶替
    (顶替写出来的跟进在台账上和本人写的长得一样,而「谁做的」正是台账要回答的)。"""
    参数 = 参数 or {}
    if not 幂等键:
        return _失败("NO_IDEMPOTENCY_KEY", "写跟进的单子没带幂等键 —— 不写,重试会写出第二条")
    老 = _写过的(幂等键, db)
    if 老:
        return {"输出": {"跟进号": 老, "customer_id": 参数.get("customer_id"), "是新写的": False,
                       "结果": f"这张单已经写过跟进 {老}(没写第二条)"}}
    客户, 内容, 通话 = (str(参数.get(k) or "").strip() for k in ("customer_id", "内容", "call_id"))
    if not (客户 and 内容):
        return _失败("MISSING", "客户号和跟进内容都必填")
    c = _连(db)
    try:
        if 通话:
            a = c.execute("SELECT customer_id FROM call_audio WHERE id=?", (通话,)).fetchone()
            if not a:
                return _失败("CALL_NOT_FOUND", f"没有 {通话} 这通录音")
            if a["customer_id"] != 客户:
                return _失败("CALL_CUSTOMER_MISMATCH",
                           f"{通话} 是客户 {a['customer_id']} 的录音,单子上写的是 {客户} —— 不记到别人名下",
                           "在管理后台重新发起一次,客户号填这通录音的客户")
    finally:
        c.close()
    # ⚠️ 写走 server 的正门,它用**它自己模块里的 DB**,不认这里的 db 参数。
    # 要在副本上跑(检查 / 咬合),先 import 本模块和 server / oplog,再 check_copy.用副本 ——
    # 它把已加载模块的 DB 一次全指过去;顺序反了就是往真库写(CLAUDE.md「检查切库前先 import 写口」)
    if not 工号:
        return _失败("NOT_BOUND", f"批准核对的账号「{办事人 or '?'}」没有绑定澜绣员工 —— 不以服务身份顶替,没写",
                   "请管理员在管理后台「成员与权限」里给他绑上澜绣工号,再重新发起一次")
    with _连(db) as c2:
        员 = c2.execute("SELECT name, status FROM staff WHERE no=?", (str(工号),)).fetchone()
    if not 员 or 员["status"] != "启用":
        return _失败("STAFF_NOT_FOUND", f"绑定的澜绣工号 {工号} " + ("不存在" if not 员 else f"状态是「{员['status']}」") + ",没写",
                   "请管理员在管理后台改绑")
    import server
    with _连(db) as c2:
        顾 = c2.execute("SELECT advisor_no FROM customer WHERE id=?", (客户,)).fetchone()
    # 跟进记在这位客户的顾问名下(和页面上顾问自己记的一样)—— 客户没有顾问就留空,不编一个
    r = server.create_followup({"customer_id": 客户, "content": 内容, "channel": "电话",
                                "advisor_no": 顾["advisor_no"] if 顾 else None},
                               actor=f"{员['name']}({工号})· 管理后台 {办事人 or 谁} 工作流核对后",
                               ctx={"幂等键": 幂等键, "通话": 通话 or None, "来自": "工作流",
                                    "管理后台账号": 办事人, "澜绣工号": 工号})
    if not r.get("ok"):
        return _失败(r.get("code") or "WRITE_FAILED", r.get("reason") or "没写成")
    return {"输出": {"跟进号": r["id"], "customer_id": 客户, "是新写的": True,
                   "结果": f"已写跟进 {r['id']}"}}


# ── 业务工具:照名单调澜绣现成的函数(2026-10-24,六条业务工作流要的能力)──────────────────
# 和聊天站调的是**同一个函数**(api.TOOLS),以绑定员工的身份(api.as_user)—— 权限判定和人在页面上点一样,
# 不因为是工作流来要的就多一分权。名单和管理后台 runtime/桥工具.py 那一份对不对得上,由 tools/bridge_tools_check.py 盯着。
业务工具 = (
    "store_report", "list_reports", "call_opportunity", "get_customer", "customer_history", "get_stock",
    "get_order", "order_log", "get_workorder", "factory_chase", "delay_pending",
    "bad_ratings", "service_records", "get_aftersale", "get_maintain", "revive_list", "churn_watch", "stock_alert",
    "save_report", "confirm_report", "assign_task", "create_repair", "decide_repair", "close_bad_rating",
)


def 员工身份(工号, db=None):
    """澜绣工号 → 和登录时一样的身份(auth.login 那四样);不存在 / 停用 → None。"""
    if not 工号:
        return None
    c = _连(db)
    try:
        r = c.execute("SELECT no, name, role, shop, status FROM staff WHERE no=?", (str(工号),)).fetchone()
    finally:
        c.close()
    if not r or r["status"] != "启用":
        return None
    return {"no": r["no"], "name": r["name"], "role": r["role"], "shop": r["shop"]}


def _桥账(幂等键, db=None):
    """这张单在台账里记过什么:(开始过吗, 完成时存下的结果 或 None)。"""
    c = _连(db)
    try:
        rs = c.execute("SELECT code, ctx FROM op_log WHERE machine='bridge' AND target=? ORDER BY id",
                       (幂等键,)).fetchall()
    finally:
        c.close()
    开始 = any(r["code"] == "START" for r in rs)
    完成 = [json.loads(r["ctx"] or "{}").get("结果") for r in rs if r["code"] == "DONE"]
    失败了 = sum(r["code"] == "FAIL" for r in rs) >= sum(r["code"] == "START" for r in rs) and 开始
    return 开始 and not 失败了, (完成[-1] if 完成 else None)


def 数据指纹(数据):
    """规范 JSON(键排序)的 sha256 前 16 位。只在「同一个工具、同一组参数」之间比才有意义。"""
    import hashlib
    return hashlib.sha256(json.dumps(数据, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def 调业务工具(名, 参数, 幂等键, 办事人=None, 工号=None, db=None):
    """→ {"输出": {"数据": 工具返回, ...}} 或 {"失败": {...}}

    **写的那几个**(api.WRITE_TOOLS 里的)多两道:
      · 没幂等键不执行
      · 执行前在台账记一笔 START、做完记 DONE(带结果)。重来时见 DONE → 回原来的结果、不再做一遍;
        **见 START 没有 DONE → 不重做,报 IN_DOUBT**:上一次可能写了一半(进程死在写完和记账之间),
        盲目重做可能派出第二条任务 —— 这种情形交给人去核,而不是猜
    核对过没有由管理后台那一侧的桥闸守(只认人工节点的批准);这里只管「以谁的身份、做不做第二遍」。"""
    import api
    if 名 not in 业务工具 or 名 not in api.TOOLS:
        return _失败("UNKNOWN_TOOL", f"澜绣桥不接「{名}」")
    me = 员工身份(工号, db)
    if not me:
        return _失败("NOT_BOUND", f"管理后台账号「{办事人 or '?'}」没有绑定可用的澜绣员工"
                     + (f"(工号 {工号} 不存在或已停用)" if 工号 else "") + " —— 不以服务身份顶替,没执行",
                     "请管理员在管理后台「成员与权限」里绑上澜绣工号,再重新发起一次")
    写 = 名 in api.WRITE_TOOLS
    if 写:
        if not 幂等键:
            return _失败("NO_IDEMPOTENCY_KEY", f"「{名}」会写库,单子没带幂等键 —— 不执行,重试会做第二遍")
        开始过, 旧 = _桥账(幂等键, db)
        if 旧 is not None:
            return {"输出": {"数据": 旧, "是新执行的": False, "结果": f"这张单已经执行过「{名}」(没做第二遍)"}}
        if 开始过:
            return _失败("IN_DOUBT", f"「{名}」上一次开始执行了但没记下结果 —— 可能写了一半,不重做",
                       "请到澜绣后台核实这一步有没有生效,再决定要不要在管理后台重新发起")
    import oplog
    账人 = f"{me['name']}({me['no']})· 管理后台 {办事人 or '?'} 工作流"
    if 写:
        oplog.log_op(账人, "bridge", 幂等键, "—", 名, True, "START", f"工作流来要「{名}」",
                     {"工具": 名, "参数": 参数, "管理后台账号": 办事人, "澜绣工号": me["no"]})
    try:
        with api.as_user(me):
            r = api.TOOLS[名](**(参数 or {}))
    except TypeError as e:
        if 写:
            oplog.log_op(账人, "bridge", 幂等键, 名, "—", False, "FAIL", f"参数不对:{e}", {"工具": 名})
        return _失败("BAD_ARGS", f"「{名}」的参数不对:{e}"[:200], "回管理后台检查这一步的参数配置")
    except Exception as e:
        # 不记 FAIL:异常可能发生在写进去之后 —— 留着 START,下一次重来会报 IN_DOUBT 让人核
        return _失败("BRIDGE_CRASHED", f"{type(e).__name__}: {e}"[:200])
    # 工具拒绝有两种写法:`{"error": …}`(多数读工具)和 `{"ok": False, "code", "reason"}`(写口走 tasks 那套判定)。
    # ⚠️ 只认前一种的话,被拒的派任务会被当成成功、记下 DONE —— 下次重来就回「已经执行过」(10-24 检查当场抓到)
    拒 = isinstance(r, dict) and (r.get("error") or r.get("ok") is False)
    if 拒:
        因 = r.get("error") or r.get("reason") or r.get("code") or "被拒"
        if 写:
            oplog.log_op(账人, "bridge", 幂等键, 名, "—", False, "FAIL", str(因)[:200], {"工具": 名, "返回": r})
        return _失败("TOOL_REFUSED", f"「{名}」没做:{因}"[:300], r.get("code") if r.get("code") else None)
    if 写:
        oplog.log_op(账人, "bridge", 幂等键, 名, "done", True, "DONE", f"工作流「{名}」执行完",
                     {"工具": 名, "结果": r})
    出 = {"数据": r, "是新执行的": True, "结果": f"已执行「{名}」"}
    if not 写:
        # 指纹(10-24 经营报告,用户拍「比对指纹,变了就重写」):同样的数据 → 同样的指纹。工作流在保存前再取一次,
        # 两次指纹不同就说明核对期间数据变了 —— 正文照旧存的话,正文和保存时冻结的取数包对不上,而且不报错
        出["指纹"] = 数据指纹(r)
    return {"输出": 出}


def 订单交付风险(参数, 办事人=None, 工号=None, db=None):
    """**这一笔**订单的交付风险(六条第三条,用户 10-25 拍「全用规则分档,模型只写建议」)。

    以绑定员工的身份调 api.get_order(范围和页面上一样),从它的「工厂回传 → 进度」里取承诺完工日、
    该不该催、演示世界的今天 —— **只取这一单的**(「该催工厂」那个工具给的是全店,拼进来就把别的单的风险算到这单头上);
    分档在 knowledge/delivery_risk.py(口径模块,不取数、不取日期)。临近天数默认 3,工作流可传。"""
    import api, sys as _s
    _s.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
    import delivery_risk as _dr
    oid = str((参数 or {}).get("order_id") or "").strip()
    if not oid:
        return _失败("MISSING", "没给订单号")
    me = 员工身份(工号, db)
    if not me:
        return _失败("NOT_BOUND", f"管理后台账号「{办事人 or '?'}」没有绑定可用的澜绣员工 —— 不以服务身份顶替,没查",
                   "请管理员在管理后台「成员与权限」里绑上澜绣工号")
    with api.as_user(me):
        o = api.get_order(order_id=oid)
    if not isinstance(o, dict) or o.get("error"):
        return _失败("TOOL_REFUSED", f"查不到订单 {oid}:{(o or {}).get('error') if isinstance(o, dict) else o}")
    进 = ((o.get("工厂回传") or {}).get("进度") or {})
    from seed import TODAY
    今天 = 进.get("截至(演示世界的今天)") or TODAY
    临近 = int((参数 or {}).get("临近天数") or 3)
    风险 = _dr.分档(o.get("类型"), o.get("PRD状态"), 进.get("承诺完工日"), 进.get("该不该催") == "该催",
                  今天, 临近, 进.get("为什么"))
    数据 = {"订单号": oid, "客户": o.get("客户"), "类型": o.get("类型"), "状态": o.get("PRD状态"),
            "页面状态": o.get("页面状态"), "承诺完工日": 进.get("承诺完工日"), "今天": 今天, "临近天数": 临近,
            "风险": 风险, "要跟踪吗": 风险["档"] in _dr.要跟踪的档, "订单": o}
    return {"输出": {"数据": 数据, "指纹": 数据指纹(数据), "是新执行的": True,
                   "结果": f"{oid}:{风险['档']}"}}


回访类型 = "电话回电"          # 方案文档「按 task_types 现有类型,不新建」;商机提醒带着「是哪条商机」的语义,召回没有
回访类们 = ("电话回电", "商机提醒")   # 「同一客户已有未完成的回访任务」认这两种(都是顾问打给这位客户)


def _归属(cids, db=None):
    """客户号 → {归属顾问工号, 姓名, 在职吗, 已有未完成回访任务};直接读库(这几样没有哪个工具一次给全)。"""
    if not cids:
        return {}
    c = _连(db)
    try:
        问 = ",".join("?" * len(cids))
        客 = {r["id"]: dict(r) for r in c.execute(
            f"SELECT c.id, c.advisor_no, s.name, s.status FROM customer c LEFT JOIN staff s ON s.no=c.advisor_no "
            f"WHERE c.id IN ({问})", list(cids))}
        已有 = {}
        for r in c.execute(f"SELECT id, customer_id, type, end_ts FROM schedule WHERE status='有效' "
                           f"AND type IN ({','.join('?' * len(回访类们))}) AND customer_id IN ({问})",
                           list(回访类们) + list(cids)):
            已有.setdefault(r["customer_id"], []).append(f"{r['id']}({r['type']},截止 {r['end_ts']})")
    finally:
        c.close()
    return {cid: {"归属顾问工号": (客.get(cid) or {}).get("advisor_no"), "归属顾问": (客.get(cid) or {}).get("name"),
                  "归属顾问在职": (客.get(cid) or {}).get("status") == "启用",
                  "已有未完成回访任务": 已有.get(cid, [])} for cid in cids}


def 交叉(促页, 流页, 问流失, 问促活, n):
    """「客户召回」技能第二步的交叉,**逐人核实**版 → (名单, 在流失等由头, 截掉几个)。不取数:两页名单和两个
    「单独问一个人」的函数由调用方给(检查拿自造的两页和假的问法真调这一份)。

    促页:revive_list 的「名单」;流页:churn_watch 的「名单」({严重程度: [...]});
    问流失(客户号) → churn_watch(customer=…) 的「这一个人」;问促活(客户号) → revive_list(customer=…) 的「这一个人」。"""
    名单, 等由头 = [], []
    for p in 促页:
        一 = 问流失(p["客户号"])
        名单.append({**p, "同时在流失预警里": bool(一.get("在不在往下走")),
                   "流失严重程度": 一.get("严重程度") if 一.get("在不在往下走") else None})
    已列 = {p["客户号"] for p in 名单}
    for 等, 们 in 流页.items():
        for w in 们:
            if w["客户号"] in 已列:
                continue
            一 = 问促活(w["客户号"])
            if 一.get("该不该联系"):
                # 促活那一页没列到他,但他其实有由头 —— 两份都在,进名单(交叉的意义就在这里)
                名单.append({"客户": w["客户"], "客户号": w["客户号"], "由头": 一.get("码"),
                           "为什么是现在": 一.get("理由"), "同时在流失预警里": True, "流失严重程度": 等})
                已列.add(w["客户号"])
            else:
                等由头.append({"客户": w["客户"], "客户号": w["客户号"], "严重程度": 等,
                            "走到哪一步": w.get("走到哪一步"), "眼下为什么不打": 一.get("理由")})
    档 = {"高": 0, "中": 1, "低": 2}
    名单.sort(key=lambda p: (not p["同时在流失预警里"], 档.get(p["流失严重程度"], 3)))   # 稳定排序:同组保持促活原序
    # 两份都在的排前面再截 —— 被挤出去的(只在促活的)要报出来,不然「促活还有没列出的」少算了他们
    return 名单[:n], 等由头, max(0, len(名单) - n)


def 召回名单(参数, 办事人=None, 工号=None, db=None):
    """**有由头的回访名单**(六条第五条,10-25)。交叉规则**复用**澜绣「客户召回」技能第二步,不新造口径:
    两份都在 → 排前面、标流失严重程度;只在促活 → 照常列;只在流失 → 单列「在流失、等由头」。

    ⚠️ 两份名单一次最多给 100 个(真库促活 1483、预警 483),**拿不到全集** —— 拿两页去交叉,
    一个人不在另一页里不代表他不在另一份名单里。所以**逐人核实**:列出的每个人单独问一次流失预警,
    流失页上的每个人单独问一次促活。范围和权限跟着绑定员工走(顾问看自己名下、店长看本店)。"""
    import api
    me = 员工身份(工号, db)
    if not me:
        return _失败("NOT_BOUND", f"管理后台账号「{办事人 or '?'}」没有绑定可用的澜绣员工 —— 不以服务身份顶替,没查",
                   "请管理员在管理后台「成员与权限」里绑上澜绣工号")
    n = max(1, min(int((参数 or {}).get("上限") or 20), 100))
    with api.as_user(me):
        促 = api.revive_list(limit=n)
        流 = api.churn_watch(limit=n)
        for r in (促, 流):
            if isinstance(r, dict) and r.get("error"):
                return _失败("TOOL_REFUSED", f"取名单没取到:{r['error']}")
        名单, 等由头, 截掉 = 交叉(促.get("名单") or [], 流.get("名单") or {},
                            lambda cid: (api.churn_watch(customer=cid) or {}).get("这一个人") or {},
                            lambda cid: (api.revive_list(customer=cid) or {}).get("这一个人") or {}, n)
    归 = _归属([p["客户号"] for p in 名单], db)
    for p in 名单:
        p.update(归.get(p["客户号"], {}))
    行 = [f"{p['客户号']} {p.get('客户') or ''} · 由头 {p.get('由头')}"
          + (f" · 同时在流失预警里(严重程度 {p['流失严重程度']})" if p.get("同时在流失预警里") else "")
          + f" · 归属顾问 {p.get('归属顾问') or '没有'}" + ("" if p.get("归属顾问在职") else "(不在职 → 转店长分配)")
          + (f" · 已有未完成回访 {'、'.join(p['已有未完成回访任务'])}" if p.get("已有未完成回访任务") else "")
          + f"\n    为什么是现在:{p.get('为什么是现在') or ''}" for p in 名单]
    行 += ["", f"在流失、等由头(眼下没由头,先不打){len(等由头)} 个:"] + [
        f"{w['客户号']} {w.get('客户') or ''} · 严重程度 {w['严重程度']} · {w.get('走到哪一步') or ''}" for w in 等由头]
    数据 = {"看的范围": 促.get("看的范围"), "名单文字": "\n".join(行), "截至": str(__import__("worldclock").今天())[:10], "上限": n,
            "该联系的(促活口径)": 促.get("该联系的"), "列出": len(名单), "促活还有没列出的": 促.get("还有"),
            "交叉后挤出这一页的": 截掉,
            "名单": 名单, "在流失、等由头": 等由头, "流失预警还有没列出的": 流.get("还有"),
            "没进名单的": 促.get("没进名单的"), "没进名单的该做什么": 促.get("没进名单的该做什么"),
            "⚠️ 这几个门槛是拍的": 促.get("⚠️ 这几个门槛是拍的"),
            "交叉口径": "复用澜绣「客户召回」技能第二步;逐人核实,不拿两页名单交叉"}
    return {"输出": {"数据": 数据, "指纹": 数据指纹(数据), "是新执行的": True,
                   "结果": f"{数据['看的范围']}:该联系 {促.get('该联系的')} 个,列出 {len(名单)} 个,"
                           f"在流失等由头 {len(等由头)} 个"}}


def 派回访任务(参数, 幂等键, 办事人=None, 工号=None, db=None):
    """店长勾了的人 → 每人一条「电话回电」给**客户的归属顾问**(方案文档:负责人默认归属顾问,无归属的转店长分配)。

    参数:客户号们(逗号分隔或列表)、截止(YYYY-MM-DD[ HH:MM])、名单(召回名单那一步的「名单」)、话术(可选,模型逐人写的)。
    **逐人跳过、不整批失败**:不在名单里 / 归属顾问离职或没有 / 已有未完成回访任务 / 派之前再核一次已经没由头了 → 跳过并写明。
    ⚠️ 不用 assign_batch:它把「同一个人在重叠时段被排两件事」当冲突,而回访任务的起止是「从现在到截止」的一段窗口,
    跟顾问手上任何一条有效任务都会重叠 —— 一用就整批被拒。
    每个人单独一笔台账(幂等键:客户号):重来时做过的不再做,开始了没记结果的报「待核实」不重做。"""
    import api
    p = 参数 or {}
    if not 幂等键:
        return _失败("NO_IDEMPOTENCY_KEY", "派回访任务会写库,单子没带幂等键 —— 不执行,重试会派第二遍")
    me = 员工身份(工号, db)
    if not me:
        return _失败("NOT_BOUND", f"管理后台账号「{办事人 or '?'}」没有绑定可用的澜绣员工 —— 不以服务身份顶替,没派",
                   "请管理员在管理后台「成员与权限」里绑上澜绣工号")
    要 = p.get("客户号们")
    要 = [x.strip() for x in (要 if isinstance(要, list) else str(要 or "").replace(",", ",").split(",")) if str(x).strip()]
    要 = list(dict.fromkeys(要))
    if not 要:
        return _失败("MISSING", "没勾要派的客户号")
    截止 = str(p.get("截止") or "").replace("T", " ").strip()
    if len(截止) == 10:
        截止 += " 18:00"
    名单 = {x["客户号"]: x for x in (p.get("名单") or []) if isinstance(x, dict) and x.get("客户号")}
    if not 名单:
        return _失败("MISSING", "没拿到召回名单 —— 不知道哪些客户号是这次核过的,一个都没派")
    话术 = {x.get("客户号"): x for x in (p.get("话术") or []) if isinstance(x, dict)}
    归 = _归属([c for c in 要 if c in 名单], db)
    import oplog
    账人 = f"{me['name']}({me['no']})· 管理后台 {办事人 or '?'} 工作流"
    派了, 跳过 = [], []
    for cid in 要:
        if cid not in 名单:
            跳过.append(f"{cid}:不在这次的召回名单里,没派")
            continue
        # 台账先查:重来时那条「未完成的回访任务」正是这张单上次派的 —— 先判它的话,会报成「已有别人派的」
        键 = f"{幂等键}:{cid}"
        开始过, 旧 = _桥账(键, db)
        if 旧 is not None:
            派了.append(f"{cid}:{旧.get('reason') or '已派过'}(这张单之前已经派过,没派第二遍)")
            continue
        if 开始过:
            跳过.append(f"{cid}:上一次开始派了但没记下结果 —— 可能派了一半,没重做,请到澜绣核实")
            continue
        g = 归.get(cid) or {}
        if not g.get("归属顾问工号") or not g.get("归属顾问在职"):
            跳过.append(f"{cid}:" + (f"归属顾问 {g.get('归属顾问') or g.get('归属顾问工号')} 已不在职"
                                      if g.get("归属顾问工号") else "没有归属顾问") + " —— 转店长分配,没派")
            continue
        if g.get("已有未完成回访任务"):
            跳过.append(f"{cid}:已有未完成的回访任务 {'、'.join(g['已有未完成回访任务'])},没再派")
            continue
        with api.as_user(me):
            一 = (api.revive_list(customer=cid) or {}).get("这一个人") or {}
        if not 一.get("该不该联系"):
            跳过.append(f"{cid}:派之前再核一次,眼下已经不该联系了({一.get('码') or '查不到'}:{一.get('理由') or ''})—— 没派")
            continue
        人 = 名单[cid]
        说 = (话术.get(cid) or {}).get("开口说什么")
        note = f"老客召回 · {人.get('客户') or cid}:{人.get('由头')} —— {人.get('为什么是现在') or ''}" + (f"。开口:{说}" if 说 else "")
        oplog.log_op(账人, "bridge", 键, "—", "派回访任务", True, "START", f"工作流派回访 {cid}",
                     {"工具": "派回访任务", "客户号": cid, "管理后台账号": 办事人, "澜绣工号": me["no"]})
        try:
            with api.as_user(me):
                r = api.assign_task(type=回访类型, assignee=g["归属顾问工号"], note=note[:500], end=截止, ref_id=cid)
        except Exception as e:
            跳过.append(f"{cid}:派的时候出错({type(e).__name__}),没记结果 —— 请到澜绣核实")
            continue                         # 不记 FAIL:异常可能在写进去之后,留着 START 下次报待核实
        if isinstance(r, dict) and (r.get("error") or r.get("ok") is False):
            因 = r.get("error") or r.get("reason") or r.get("code")
            oplog.log_op(账人, "bridge", 键, "派回访任务", "—", False, "FAIL", str(因)[:200], {"返回": r})
            跳过.append(f"{cid}:澜绣没派 —— {因}")
            continue
        oplog.log_op(账人, "bridge", 键, "派回访任务", "done", True, "DONE", f"派回访 {cid}", {"结果": r})
        派了.append(f"{cid}:派给 {g['归属顾问']}(截止 {截止})")
    return {"输出": {"数据": {"派了": 派了, "跳过": 跳过}, "是新执行的": True,
                   "结果": f"派了 {len(派了)} 条回访" + (f",跳过 {len(跳过)} 个:" + ";".join(跳过) if 跳过 else "")}}


def 补货预警(参数, 办事人=None, 工号=None, db=None):
    """**这一个 SKU** 现在在哪一档、要不要派补货跟进(六条第六条,10-25)。档由澜绣现成的库存预警口径判
    (knowledge/stockalert.py,经 alert_dispatch.sku档 —— 和库存预警页、预警派单同一把尺),不新造。
    可派的只有 发不出 / 断货 / 快没了;卖不动(压货)/ 够 → 不派补货。带上同一 SKU 还没办完的补货跟进。"""
    import api, alert_dispatch as _ad
    sku = str((参数 or {}).get("sku") or "").strip()
    if not sku:
        return _失败("MISSING", "没给 SKU")
    me = 员工身份(工号, db)
    if not me:
        return _失败("NOT_BOUND", f"管理后台账号「{办事人 or '?'}」没有绑定可用的澜绣员工 —— 不以服务身份顶替,没查",
                   "请管理员在管理后台「成员与权限」里绑上澜绣工号")
    c = _连(db)
    try:
        档, 话 = _ad.sku档(c, sku)
        已有 = [f"{r['id']}(截止 {r['end_ts']})" for r in c.execute(
            "SELECT id, end_ts FROM schedule WHERE type='补货跟进' AND status='有效' AND ref_id=?", (sku,))]
    finally:
        c.close()
    if 档 is None:
        return _失败("TOOL_REFUSED", f"{sku}:{话}")
    with api.as_user(me):
        库存 = api.get_stock(sku=sku)
    可派 = 档 in _ad.可派档
    数据 = {"SKU": sku, "档": 档, "依据": 话, "可派补货吗": 可派, "已有未完成补货跟进": 已有,
            "要派吗": 可派 and not 已有, "库存": 库存,
            "说明": ("压货:只出处理建议(调拨 / 活动),不派补货" if 档 == "卖不动" else
                   "库存够,不用补" if 档 == "够" else
                   f"已有没办完的补货跟进 {'、'.join(已有)},不重复派" if 已有 else "可以派补货跟进")}
    return {"输出": {"数据": 数据, "指纹": 数据指纹(数据), "是新执行的": True, "结果": f"{sku}:{档} —— {数据['说明']}"}}


def 派补货跟进(参数, 幂等键, 办事人=None, 工号=None, db=None):
    """店长 / 总部确认后派「补货跟进」。**直接走澜绣现成的预警派单**(alert_dispatch.派):档位当场重算、
    不在预警里的不派、同一件事没办完不重派(写的那个事务里再判)、只派给店长 / 总部运营 —— 一条都不在这里另写。
    这一层只加:绑定员工身份、台账 START / DONE(重来不派第二条,开始了没结果报待核实)。"""
    import alert_dispatch as _ad, oplog
    p = 参数 or {}
    if not 幂等键:
        return _失败("NO_IDEMPOTENCY_KEY", "派补货跟进会写库,单子没带幂等键 —— 不执行,重试会派第二遍")
    me = 员工身份(工号, db)
    if not me:
        return _失败("NOT_BOUND", f"管理后台账号「{办事人 or '?'}」没有绑定可用的澜绣员工 —— 不以服务身份顶替,没派",
                   "请管理员在管理后台「成员与权限」里绑上澜绣工号")
    开始过, 旧 = _桥账(幂等键, db)
    if 旧 is not None:
        return {"输出": {"数据": 旧, "是新执行的": False, "结果": f"这张单已经派过补货跟进(没派第二遍)"}}
    if 开始过:
        return _失败("IN_DOUBT", "上一次开始派了但没记下结果 —— 可能派了一半,不重做", "请到澜绣核实有没有这条补货跟进")
    截止 = str(p.get("截止") or "").replace("T", " ").strip()
    if len(截止) == 10:
        截止 += " 18:00"
    账人 = f"{me['name']}({me['no']})· 管理后台 {办事人 or '?'} 工作流"
    oplog.log_op(账人, "bridge", 幂等键, "—", "派补货跟进", True, "START", f"工作流派补货跟进 {p.get('sku')}",
                 {"工具": "派补货跟进", "参数": p, "管理后台账号": 办事人, "澜绣工号": me["no"]})
    r = _ad.派({"kind": "库存预警", "obj": p.get("sku"), "assignee_no": p.get("负责人"), "end": 截止,
               "note": p.get("note")}, me)
    if not r.get("ok"):
        oplog.log_op(账人, "bridge", 幂等键, "派补货跟进", "—", False, "FAIL", str(r.get("reason"))[:200], {"返回": r})
        return _失败("TOOL_REFUSED", f"澜绣没派:{r.get('reason')}"[:300], r.get("code"))
    oplog.log_op(账人, "bridge", 幂等键, "派补货跟进", "done", True, "DONE", f"派补货跟进 {p.get('sku')}", {"结果": r})
    return {"输出": {"数据": r, "是新执行的": True, "结果": f"已派补货跟进:{r.get('reason') or ''}"[:300]}}


def 差评研判(参数, 办事人=None, 工号=None, db=None):
    """**这一条差评**的事实 + 判责建议(六条第四条,10-25)。判责**复用**澜绣现成的返修判定表(knowledge/liability.py),
    归不到表里任何一类就写「判定表没覆盖,交店长判」,不硬套。只取这一单的服务记录和售后,不混同一客户别的单。
    看得到哪些差评跟着绑定员工(和差评清单同一个范围:店长 / 售后,本店)。"""
    import api, rating_write as _rw, sys as _s
    _s.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
    import liability as _lb
    pkg = str((参数 or {}).get("pkg") or "").strip()
    if not pkg:
        return _失败("MISSING", "没给差评的包裹号")
    me = 员工身份(工号, db)
    if not me:
        return _失败("NOT_BOUND", f"管理后台账号「{办事人 or '?'}」没有绑定可用的澜绣员工 —— 不以服务身份顶替,没查",
                   "请管理员在管理后台「成员与权限」里绑上澜绣工号")
    if me["role"] not in _rw.能关差评的角色:
        return _失败("TOOL_REFUSED", f"差评归 {' / '.join(_rw.能关差评的角色)} 跟,绑定的员工是「{me['role']}」")
    c = _连(db)
    try:
        r = c.execute("""SELECT t.id 工单, t.status 状态, r.pkg_id 包裹, r.order_id 订单, r.star 星, r.note 顾客说,
                                r.rated_at 评于, o.shop 门店, k.name 客户
                           FROM task t JOIN rating r ON r.task_id=t.id LEFT JOIN ordr o ON o.id=r.order_id
                           LEFT JOIN customer k ON k.id=r.customer_id
                          WHERE t.type='评价差评' AND r.pkg_id=?""", (pkg,)).fetchone()
    finally:
        c.close()
    if not r:
        return _失败("TOOL_REFUSED", f"没有包裹 {pkg} 的差评")
    差 = dict(r)
    if me["role"] not in ("总部运营",) and me.get("shop") and 差.get("门店") != me["shop"]:
        return _失败("TOOL_REFUSED", f"这条差评是「{差.get('门店')}」的,不在你的范围里")
    with api.as_user(me):
        服务 = api.service_records(pkg=pkg)
        售后 = api.get_aftersale(order_id=差["订单"]) if 差.get("订单") else None
    判 = _lb.judge(差.get("顾客说") or "")
    数据 = {"差评": 差, "服务记录": 服务, "售后": 售后,
            "判责建议": {k: 判.get(k) for k in ("归类", "责任", "处理", "规则行", "依据", "判得出")},
            "说明": ("判定表能判:" + str(判.get("依据")) if 判.get("判得出")
                   else "判定表没覆盖这一类(或缺判它要的事实)—— 交店长判,不硬套最近的一行"),
            "已处理": 差.get("状态") != "待处理",
            "金额授权": f"我方出钱 ≤{_lb.授权档[0]} 店长定;{_lb.授权档[0]}–{_lb.授权档[1]} 报总部;>{_lb.授权档[1]} 走专项"}
    return {"输出": {"数据": 数据, "指纹": 数据指纹(数据), "是新执行的": True,
                   "结果": f"差评 {pkg}({差.get('星')} 星):" + 数据["说明"]}}


def 差评处置(参数, 幂等键, 办事人=None, 工号=None, db=None):
    """店长定了之后办:**返修**(建返修单 → 店长判责)或**说明后关闭**(关差评)。全走澜绣现成的写口和它们的闸。

    用户 10-25 拍「停下报总部,不写」:判给企业(我方出钱)而预估费用超过店长权限 → **什么都不写**,
    报「要报总部」,由总部在澜绣里办。出钱的关闭方式(退款)要第二个人批,流程不经手钱 → 也不写,回澜绣办。"""
    import api, oplog, sys as _s
    _s.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
    import liability as _lb, rating as _rt
    # 店长在核对页填的那几样整包传进来(「店长定的」= 人工节点的整个输出):选填的字段没填就不在里面 ——
    # 逐个绑定的话,一个没填的字段就让整次运行失败
    p = {**((参数 or {}).get("店长定的") or {}), **{k: v for k, v in (参数 or {}).items() if k != "店长定的"}}
    if not 幂等键:
        return _失败("NO_IDEMPOTENCY_KEY", "差评处置会写库,单子没带幂等键 —— 不执行,重试会做第二遍")
    me = 员工身份(工号, db)
    if not me:
        return _失败("NOT_BOUND", f"管理后台账号「{办事人 or '?'}」没有绑定可用的澜绣员工 —— 不以服务身份顶替,没办",
                   "请管理员在管理后台「成员与权限」里绑上澜绣工号")
    处置 = str(p.get("处置") or "").strip()
    pkg = str(p.get("pkg") or "").strip()
    if 处置 not in ("返修", "说明后关闭"):
        return _失败("BAD_ARGS", f"处置只能是「返修」或「说明后关闭」,填的是「{处置}」")
    if 处置 == "返修":
        责任 = str(p.get("责任方") or "").strip()
        if 责任 not in ("企业", "顾客"):
            return _失败("BAD_ARGS", f"返修要写责任方(企业 / 顾客),填的是「{责任}」")
        try:
            费 = float(p.get("预估费用") or 0)
        except (TypeError, ValueError):
            return _失败("BAD_ARGS", f"预估费用不是数:{p.get('预估费用')}")
        if 责任 == "企业":
            谁, 话 = _lb.谁能拍板(费)
            if 谁 != "店长":
                # 停下是**这一档该有的结局**,不是出错 —— 回成功、写明「没写」,运行不标失败
                return {"输出": {"数据": {"写了": False, "停在": "OVER_AUTHORITY", "谁能拍板": 谁}, "是新执行的": False,
                               "结果": f"{话} —— 流程到这里停下,没建返修单、没关差评;请报总部在澜绣里办"}}
    else:
        方式 = str(p.get("关闭方式") or "").strip()
        if 方式 in _rt.出钱的处理方式:
            return {"输出": {"数据": {"写了": False, "停在": "MONEY_NOT_IN_FLOW"}, "是新执行的": False,
                           "结果": f"「{方式}」要出钱,得第二个人批 —— 流程不经手钱,没关差评;请回澜绣差评页办"}}
    开始过, 旧 = _桥账(幂等键, db)
    if 旧 is not None:
        return {"输出": {"数据": 旧, "是新执行的": False, "结果": "这张单已经办过(没做第二遍)"}}
    if 开始过:
        return _失败("IN_DOUBT", "上一次开始办了但没记下结果 —— 可能做了一半,不重做", "请到澜绣核实返修单 / 差评状态")
    账人 = f"{me['name']}({me['no']})· 管理后台 {办事人 or '?'} 工作流"
    oplog.log_op(账人, "bridge", 幂等键, "—", "差评处置", True, "START", f"工作流差评处置 {pkg}:{处置}",
                 {"工具": "差评处置", "参数": p, "管理后台账号": 办事人, "澜绣工号": me["no"]})
    拒 = lambda r: isinstance(r, dict) and (r.get("error") or r.get("ok") is False)
    因 = lambda r: r.get("error") or r.get("reason") or r.get("code")
    with api.as_user(me):
        if 处置 == "返修":
            c = _连(db)
            try:
                行 = c.execute("SELECT order_id, note FROM rating WHERE pkg_id=?", (pkg,)).fetchone()
            finally:
                c.close()
            if not 行:
                oplog.log_op(账人, "bridge", 幂等键, "差评处置", "—", False, "FAIL", "没有这条差评", {})
                return _失败("TOOL_REFUSED", f"没有包裹 {pkg} 的差评")
            建 = api.create_repair(order_id=行["order_id"], issue=p.get("问题") or 行["note"] or "差评返修")
            if 拒(建):
                oplog.log_op(账人, "bridge", 幂等键, "差评处置", "—", False, "FAIL", str(因(建))[:200], {"返回": 建})
                return _失败("TOOL_REFUSED", f"返修单没建成:{因(建)}"[:300])
            判 = api.decide_repair(maintain_id=建["返修单"], liable=责任, plan="返修", fee_est=费 or None,
                                  customer_agreed=bool(p.get("顾客同意凭据")) or None, agree_note=p.get("顾客同意凭据"))
            结果 = {"返修单": 建["返修单"], "建单": 建, "判责": 判}
            话 = (f"建了返修单 {建['返修单']}," + (f"判责没过:{因(判)} —— 返修单停在「待确认」,请店长在澜绣补齐再判"
                                                if 拒(判) else f"判给{责任},{判.get('reason') or '已判'}"))
        else:
            r = api.close_bad_rating(pkg=pkg, note=p.get("说明") or "", way=p.get("关闭方式") or "只回访")
            if 拒(r):
                oplog.log_op(账人, "bridge", 幂等键, "差评处置", "—", False, "FAIL", str(因(r))[:200], {"返回": r})
                return _失败("TOOL_REFUSED", f"差评没关:{因(r)}"[:300])
            结果, 话 = {"关闭": r}, f"差评 {pkg} 已关闭({p.get('关闭方式') or '只回访'})"
    oplog.log_op(账人, "bridge", 幂等键, "差评处置", "done", True, "DONE", 话[:200], {"结果": 结果})
    return {"输出": {"数据": 结果, "是新执行的": True, "结果": 话[:300]}}


# 桥专门做的几样(不在 api.TOOLS 里的):两边名单对账时和业务工具合在一起算
专用工具 = ("取转写", "写跟进", "订单交付风险", "召回名单", "派回访任务", "补货预警", "派补货跟进", "差评研判", "差评处置")

执行表 = {"取转写": lambda 单, 谁, db=None: 取转写(单.get("参数"), db=db),
          "写跟进": lambda 单, 谁, db=None: 写跟进(单.get("参数"), 单.get("幂等键"), 谁, db=db,
                                                 办事人=单.get("办事人"), 工号=单.get("办事人澜绣工号"))}
执行表["订单交付风险"] = lambda 单, 谁, db=None: 订单交付风险(单.get("参数"), 办事人=单.get("办事人"),
                                                            工号=单.get("办事人澜绣工号"), db=db)
执行表["召回名单"] = lambda 单, 谁, db=None: 召回名单(单.get("参数"), 办事人=单.get("办事人"),
                                                    工号=单.get("办事人澜绣工号"), db=db)
执行表["派回访任务"] = lambda 单, 谁, db=None: 派回访任务(单.get("参数"), 单.get("幂等键"), 办事人=单.get("办事人"),
                                                      工号=单.get("办事人澜绣工号"), db=db)
执行表["补货预警"] = lambda 单, 谁, db=None: 补货预警(单.get("参数"), 办事人=单.get("办事人"),
                                                    工号=单.get("办事人澜绣工号"), db=db)
执行表["派补货跟进"] = lambda 单, 谁, db=None: 派补货跟进(单.get("参数"), 单.get("幂等键"), 办事人=单.get("办事人"),
                                                      工号=单.get("办事人澜绣工号"), db=db)
执行表["差评研判"] = lambda 单, 谁, db=None: 差评研判(单.get("参数"), 办事人=单.get("办事人"),
                                                    工号=单.get("办事人澜绣工号"), db=db)
执行表["差评处置"] = lambda 单, 谁, db=None: 差评处置(单.get("参数"), 单.get("幂等键"), 办事人=单.get("办事人"),
                                                    工号=单.get("办事人澜绣工号"), db=db)
执行表.update({名: (lambda 名: lambda 单, 谁, db=None: 调业务工具(
    名, 单.get("参数"), 单.get("幂等键"), 办事人=单.get("办事人"), 工号=单.get("办事人澜绣工号"), db=db))(名)
    for 名 in 业务工具})


def 执行(单, 谁="AI 管理平台", db=None):
    """管理后台拉来的一张单 → (回执结果, 输出, 失败)。认不出的工具一律不执行。"""
    fn = 执行表.get(单.get("工具"))
    if not fn:
        return "执行失败", None, {"code": "UNKNOWN_TOOL", "消息": f"澜绣不认识「{单.get('工具')}」"}
    try:
        r = fn(单, 谁, db=db)
    except Exception as e:
        return "执行失败", None, {"code": "BRIDGE_CRASHED", "消息": f"{type(e).__name__}: {e}"[:200]}
    if "失败" in r:
        return "执行失败", None, r["失败"]
    return "已执行", r["输出"], None
