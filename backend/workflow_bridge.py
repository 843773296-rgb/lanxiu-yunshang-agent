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


执行表 = {"取转写": lambda 单, 谁, db=None: 取转写(单.get("参数"), db=db),
          "写跟进": lambda 单, 谁, db=None: 写跟进(单.get("参数"), 单.get("幂等键"), 谁, db=db,
                                                 办事人=单.get("办事人"), 工号=单.get("办事人澜绣工号"))}


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
