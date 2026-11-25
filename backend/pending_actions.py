# -*- coding: utf-8 -*-
"""写操作确认卡 —— 待确认动作的存储与状态流转(用户 2026-11-11 拍)。

## 为什么要有它

原来「动手前先跟用户对一遍」**只写在提示词里**(boundary_audit 记成「约定」):模型不问就写,没有任何东西会拦。
用户 11-11 拍板(一张卡,四问):
  · 聊天里 **29 个写操作全部出卡**,只读不出;新加的写操作没登记就禁止(登记处是 api.WRITE_TOOLS)
    —— **11-25 用户拍分三档**(见下面 `风险档`):高 照旧每次出卡;中 本人点过一次就记住、以后直接做;低 直接做、留「直接执行」卡
  · 审批类(提审批 / 批审批 / 启动流程)也出卡,**点卡就算本人那一步**,不另外再批
  · 卡 **30 分钟**过期;过期了要重新查状态、重新生成
  · 只回一句「好 / 确认」**不算**,必须点卡

## 结构(为什么拦在工具服务那一层)

工具服务(mcp/protocol)是单独的进程,登录身份从 env 进去 —— **模型改得了参数,改不了 env**。
聊天站给工具服务带上 `LANXIU_CONFIRM_STORE`(这份库的路径)时,写工具不执行,只在这里建一条「待确认」;
店员点「确认」→ 聊天站核对是不是本人、过没过期、状态对不对 → 原子领取 → **用同一个工具服务、同一份参数**
再调一次,这一次 env 里带着 `LANXIU_CONFIRMED=<参数指纹>`,指纹对得上才放行。
评测 / V1 / V2 / 自测不带 `LANXIU_CONFIRM_STORE`,行为一字不变。

## 状态

    待确认 → 执行中 → 已成功 / 已失败
           → 已取消(本人点「暂不执行」)
           → 已过期(30 分钟没点;读的时候现算,不靠后台扫)
    终态不原地重跑:要重做就让模型重新生成一张。

纯标准库 sqlite,一个文件;路径由调用方给(聊天站放在 agentsite/state/ 下,不进版本库)。
"""
import hashlib
import json
import os
import sqlite3
import time
import uuid

有效秒 = 30 * 60          # 用户 11-11 拍:30 分钟
# 11-21(复审 P0-01,用户拍):结束不再只有「成功 / 失败」两种 ——
#   已成功   工具回了结果、没报错
#   已失败   工具**明确**报了错(它自己说没做成)
#   未执行   **确定**没碰业务库:找不到工具服务 / 指纹对不上(工具服务自己说「还没有执行」)
#   核对中   **不知道**做没做:120 秒没回、进程没回结果 —— 可能已落库。不记失败、不许重试,页面写「可能已执行,正在核对」,自动转人工
# 「超时」≠「没做」:原来把超时记成已失败,员工看到失败再点一次,就重复派单了。
终态 = ("已成功", "已失败", "未执行", "核对中", "已取消", "已过期", "直接执行")
结束状态们 = ("已成功", "已失败", "未执行", "核对中")

# ── 三档(用户 2026-11-25 拍,包二那张卡:「确认卡分三档」)────────────────────────────────
#   高  碰钱、碰货、对外承诺、不可逆:**每次都出卡**(11-11 的规矩原样保留)
#   中  内部流转、能回头的:**第一次出卡,本人点过确认就记住(按人 × 按工具),以后同一个人用这个工具不再问**;
#       「记住」能撤(卡上有「以后还是先问我」);「同一个人同一份参数 30 分钟内办过」那道闸三档都在,记住了也不会重复派
#   低  草稿、完成标记这类改错了当场能改回来的:**直接做,留一张「直接执行」卡**(谁、什么时候、什么参数,和出过的卡一样能查)
# ⚠️ **不在表里的写工具一律按「高」**(新加的写口默认最严;登记在 api.WRITE_TOOLS 之后再来这里定档)。
# ⚠️ 这张表是**单一来源**:工具服务(mcp/protocol)拦截时查它,页面显示档位也查它。要挪档只改这里。
# 分档理由(我 11-25 按「错了的代价」定的,用户没逐条过;挪档只动这张表):
#   高:开单 / 确认下单 / 回滚(钱、货);开裁 / 报工 / 签收 / 核码 / 追认(货和状态不可逆);返修四步(判责牵涉顾客赔付);
#      关差评 / 确认经营报告 / 记已告知(对外或对上的定论);审批两步;发布排班(影响全店排班);启动流程(会写系统)
#   中:派任务 / 分派 / 改派 / 批量两种 / 建挽回跟进(内部派活,能改派回来);登记量体 / 白坯试衣(登记类,能补一条更正);
#      核裁片占比 / 核档差(版师核一遍的记录)
#   低:保存经营报告草稿、排班草稿(都是草稿,发布另有一步);完成任务(状态能改回)
风险档 = {
    "open_order": "高", "confirm_order": "高", "rollback_order": "高", "start_cutting": "高", "report_production": "高",
    "record_pickup": "高", "verify_fit_code": "高", "ratify_complete": "高",
    "create_repair": "高", "decide_repair": "高", "advance_repair": "高", "verify_repair_return": "高",
    "close_bad_rating": "高", "confirm_report": "高", "mark_delay_told": "高", "record_delivery_notice": "高",
    "apply_adjust": "高", "decide_approval": "高", "shift_publish": "高", "start_workflow": "高",
    "book_appointment": "高", "reschedule_appointment": "高",   # 预约是对客承诺(用户 11-25 拍:高档每次问)
    "assign_task": "中", "dispatch_task": "中", "reassign_task": "中", "assign_batch": "中", "dispatch_batch": "中",
    "recovery_followup": "中", "record_measure": "中", "record_fitting": "中", "set_piece_ratio": "中", "set_grade_diff": "中",
    "save_report": "低", "shift_draft": "低", "finish_task": "低",
}


def 档位(tool):
    """这个写工具属于哪一档;不认识的一律「高」(默认最严 —— 新加的写口没定档就先每次都问)。"""
    return 风险档.get(tool, "高")
摘要字数 = 200           # 结果里单个字串超过它就在卡上截短(完整结果另存一份,带哈希)
摘要项数 = 30

_建表 = """
create table if not exists pending_action (
    id          text primary key,
    tool        text not null,
    domain      text not null,
    args_json   text not null,
    fingerprint text not null,
    asker_no    text not null,
    asker_json  text not null,
    trace       text,
    session     text,
    status      text not null,
    created_at  real not null,
    expires_at  real not null,
    decided_at  real,
    result_json text,
    told        integer not null default 0     -- 预留:下一轮告诉模型结局(11-11 没做,怕干扰意图分类)
);
create index if not exists pa_trace on pending_action(trace);
create index if not exists pa_session on pending_action(session);
-- 11-21(复审 P1-02):完整回执另存一张表 —— 不动老表的列(加列要走迁移目录,tools/migration_check 盯着;这里建一张新表 if not exists 就够)
create table if not exists pending_action_result (
    aid         text primary key,
    result_full text not null,
    sha256      text not null,
    byte_count  integer not null,
    truncated   integer not null default 0
);
-- 11-25(用户拍三档):「中」档本人点过确认就记住 —— 按人 × 按工具;撤了就删行。新表 if not exists,不动老表
create table if not exists confirm_memory (
    asker_no      text not null,
    tool          text not null,
    remembered_at real not null,
    from_aid      text,
    primary key (asker_no, tool)
);
"""


def 参数指纹(tool, args):
    """工具名 + 参数的规范化哈希。确认时只认这个指纹 —— 卡上看到的和执行的必须是同一份。"""
    s = json.dumps({"tool": str(tool), "args": args or {}}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def _连(路径):
    d = os.path.dirname(os.path.abspath(路径))
    os.makedirs(d, exist_ok=True)
    c = sqlite3.connect(路径, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript(_建表)
    return c


def _行(r, 现在=None):
    if r is None:
        return None
    d = dict(r)
    d["args"] = json.loads(d.pop("args_json") or "{}")
    d["asker"] = json.loads(d.pop("asker_json") or "{}")
    d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
    # 11-21:卡上的 result 是**摘要**(永远是合法 JSON);完整结果另存 pending_action_result,这里只带元信息(由 _补元 填),要全文走 取完整结果()
    d.setdefault("result_meta", None)
    if d["status"] == "待确认" and (现在 if 现在 is not None else time.time()) >= d["expires_at"]:
        d["status"] = "已过期"           # 读的时候现算:过期不靠后台扫,也就不会有「该过期而没过期」的窗口
    return d


def 建(路径, tool, domain, args, me, trace=None, session=None, 现在=None):
    """建一张待确认卡 → 卡。同一轮(trace)同一份参数再调一次,拿回同一张(模型重试不多出卡)。"""
    if not (me or {}).get("no"):
        raise PermissionError("没有登录身份 —— 写操作要记是谁发起的,确认时也只认这个人")
    现在 = time.time() if 现在 is None else 现在
    指 = 参数指纹(tool, args)
    办过 = 办过的(路径, tool, args, me, 现在)
    if 办过 is not None:
        return 办过
    c = _连(路径)
    try:
        if trace:
            旧 = c.execute("""select * from pending_action where trace=? and fingerprint=? and status='待确认'
                              order by created_at desc limit 1""", (trace, 指)).fetchone()
            if 旧 is not None and _行(旧, 现在)["status"] == "待确认":
                return _行(旧, 现在)
        aid = "act_" + uuid.uuid4().hex[:12]
        c.execute("""insert into pending_action (id, tool, domain, args_json, fingerprint, asker_no, asker_json,
                         trace, session, status, created_at, expires_at) values (?,?,?,?,?,?,?,?,?,'待确认',?,?)""",
                  (aid, tool, domain, json.dumps(args or {}, ensure_ascii=False), 指, str(me["no"]),
                   json.dumps({k: me.get(k) for k in ("no", "name", "role", "shop")}, ensure_ascii=False),
                   trace, session, 现在, 现在 + 有效秒))
        return _行(c.execute("select * from pending_action where id=?", (aid,)).fetchone(), 现在)
    finally:
        c.close()


def 办过的(路径, tool, args, me, 现在=None):
    """同一个人、同一份参数,30 分钟内已经点卡执行成功过(或「核对中」)→ 那张卡;没有 → None。
    原来写在 建() 里;11-25 拆出来是因为**三档都要先过这道闸**:「中」记住了、「低」直接做,也不许 30 分钟内同参数再来一遍
    (模型下一轮以为没办成又调一次,正是重复派单的入口;11-21 把「核对中」也算进来)。"""
    现在 = time.time() if 现在 is None else 现在
    if not (me or {}).get("no"):
        return None
    c = _连(路径)
    try:
        r = c.execute("""select * from pending_action where asker_no=? and fingerprint=? and status in ('已成功', '核对中', '直接执行')
                         and decided_at>? order by decided_at desc limit 1""",
                      (str(me["no"]), 参数指纹(tool, args), 现在 - 有效秒)).fetchone()
        return _行(r, 现在) if r is not None else None
    finally:
        c.close()


def 要出卡吗(路径, tool, args, me, 现在=None):
    """工具服务拦下一个写操作时问这一句 → ("出卡", None) / ("直接", 档) / ("办过", 卡)。
    · 没有登录身份 → 出卡(建卡那一步会抛「没有登录身份」,不执行 —— 拦住是安全的那一边)
    · 30 分钟内同人同参数办过 → 办过(不执行、不建新卡,把那张卡给模型)
    · 高 → 出卡;中 → 本人记住过这个工具就直接,否则出卡;低 → 直接"""
    if not (me or {}).get("no"):
        return "出卡", None
    办过 = 办过的(路径, tool, args, me, 现在)
    if 办过 is not None:
        return "办过", 办过
    档 = 档位(tool)
    if 档 == "低":
        return "直接", 档
    if 档 == "中" and 记得吗(路径, me, tool):
        return "直接", 档
    return "出卡", None


def 直接执行留痕(路径, tool, domain, args, me, 档, trace=None, session=None, 现在=None):
    """「中(记住过)/ 低」直接执行前先落一张「直接执行」卡 —— 和出过的卡同一张表、同一套查法(本轮卡 / 完整结果都能看到它),
    页面上标着档位和「以后还是先问我」。执行完用 记结果() 把回执写上。"""
    if not (me or {}).get("no"):
        raise PermissionError("没有登录身份 —— 直接执行也要记是谁发起的")
    现在 = time.time() if 现在 is None else 现在
    aid = "act_" + uuid.uuid4().hex[:12]
    c = _连(路径)
    try:
        c.execute("""insert into pending_action (id, tool, domain, args_json, fingerprint, asker_no, asker_json,
                         trace, session, status, created_at, expires_at, decided_at) values (?,?,?,?,?,?,?,?,?,'直接执行',?,?,?)""",
                  (aid, tool, domain, json.dumps(args or {}, ensure_ascii=False), 参数指纹(tool, args), str(me["no"]),
                   json.dumps({k: me.get(k) for k in ("no", "name", "role", "shop")}, ensure_ascii=False),
                   trace, session, 现在, 现在 + 有效秒, 现在))
        return _行(c.execute("select * from pending_action where id=?", (aid,)).fetchone(), 现在)
    finally:
        c.close()


def 记结果(路径, aid, 结果):
    """直接执行那张卡的回执(状态不变,还是「直接执行」;结果摘要上卡、完整另存,和 收尾 同一套存法)。"""
    完整 = json.dumps(结果, ensure_ascii=False, default=str)
    摘要, 截 = 摘要化(json.loads(完整))
    c = _连(路径)
    try:
        n = c.execute("update pending_action set result_json=? where id=? and status='直接执行'",
                      (json.dumps(摘要, ensure_ascii=False), aid)).rowcount
        if n == 1:
            c.execute("insert or replace into pending_action_result (aid, result_full, sha256, byte_count, truncated) values (?,?,?,?,?)",
                      (aid, 完整, hashlib.sha256(完整.encode("utf-8")).hexdigest(), len(完整.encode("utf-8")), 1 if 截 else 0))
    finally:
        c.close()


def 记住(路径, me, tool, from_aid=None, 现在=None):
    """「中」档:本人点过确认 → 记住(按人 × 按工具)。再记一次只刷时间。"""
    if not (me or {}).get("no") or 档位(tool) != "中":
        return False
    c = _连(路径)
    try:
        c.execute("insert or replace into confirm_memory (asker_no, tool, remembered_at, from_aid) values (?,?,?,?)",
                  (str(me["no"]), tool, time.time() if 现在 is None else 现在, from_aid))
        return True
    finally:
        c.close()


def 记得吗(路径, me, tool):
    if not (me or {}).get("no"):
        return False
    c = _连(路径)
    try:
        return c.execute("select 1 from confirm_memory where asker_no=? and tool=?", (str(me["no"]), tool)).fetchone() is not None
    finally:
        c.close()


def 忘掉(路径, me, tool):
    """撤销「记住」→ 这个人用这个工具下次又会先出卡。只能撤自己的。→ 删了几行(0 = 本来就没记)。"""
    if not (me or {}).get("no"):
        return 0
    c = _连(路径)
    try:
        return c.execute("delete from confirm_memory where asker_no=? and tool=?", (str(me["no"]), tool)).rowcount
    finally:
        c.close()


def 记住的(路径, me):
    """这个人记住了哪些工具 → [{tool, remembered_at}]。"""
    if not (me or {}).get("no"):
        return []
    c = _连(路径)
    try:
        return [dict(r) for r in c.execute("select tool, remembered_at from confirm_memory where asker_no=? order by remembered_at desc",
                                           (str(me["no"]),)).fetchall()]
    finally:
        c.close()


def _补元(c, d):
    """卡上带一份完整结果的元信息(字节 / 哈希 / 截过没);没收尾过就 None。"""
    if d is None:
        return d
    m = c.execute("select sha256, byte_count, truncated from pending_action_result where aid=?", (d["id"],)).fetchone()
    d["result_meta"] = {"字节": m["byte_count"], "哈希": m["sha256"], "已截短": bool(m["truncated"])} if m else None
    return d


def 取(路径, aid, 现在=None):
    c = _连(路径)
    try:
        return _补元(c, _行(c.execute("select * from pending_action where id=?", (str(aid or ""),)).fetchone(), 现在))
    finally:
        c.close()


def 本轮的(路径, trace, 现在=None):
    """这一轮生成的卡(给聊天页画)。"""
    if not trace:
        return []
    c = _连(路径)
    try:
        return [_补元(c, _行(r, 现在)) for r in c.execute("select * from pending_action where trace=? order by created_at", (trace,))]
    finally:
        c.close()


def 作废本轮(路径, trace, 现在=None):
    """难题分流换了模型重答时,先试那一遍生成的卡全部作废(那一遍的回答用户看不到,卡也不该留着)。"""
    if not trace:
        return 0
    c = _连(路径)
    try:
        return c.execute("update pending_action set status='已取消', decided_at=? where trace=? and status='待确认'",
                         (time.time() if 现在 is None else 现在, trace)).rowcount
    finally:
        c.close()


def 领取(路径, aid, me, 现在=None):
    """→ (卡, None) 或 (None, (HTTP 码, 为什么))。**原子**:待确认 → 执行中,只成功一次(双击 / 并发只有一个能领到)。
    只认发起人本人;过期、已取消、已执行的都领不到。"""
    现在 = time.time() if 现在 is None else 现在
    if not (me or {}).get("no"):
        return None, (401, "没登录 —— 确认要记是谁点的")
    卡 = 取(路径, aid, 现在)
    # 别人的卡和不存在的卡说同一句话 —— 「有这张卡但不是你的」本身就是信息(同 answer_feedback.能评吗)
    if not 卡 or str(卡["asker_no"]) != str(me["no"]):
        return None, (404, "没有这张确认卡,或者它不是你发起的 —— 只有发起的人能确认")
    if 卡["status"] == "已过期":
        return None, (410, "这张卡已经过期(30 分钟)—— 让助手重新查一遍状态、重新生成")
    if 卡["status"] != "待确认":
        return None, (409, f"这张卡已经是「{卡['status']}」了,不会再执行一次")
    c = _连(路径)
    try:
        n = c.execute("""update pending_action set status='执行中', decided_at=? where id=? and status='待确认'
                         and expires_at>?""", (现在, 卡["id"], 现在)).rowcount
    finally:
        c.close()
    if n != 1:
        return None, (409, "这张卡刚被处理过(可能点了两次)—— 不会再执行一次")
    卡["status"] = "执行中"
    # 11-25 三档:「中」档本人点了确认 → 记住这个人 × 这个工具,以后不再问(高档永远不记;记不记在这里定,不在页面)
    记住(路径, me, 卡["tool"], from_aid=卡["id"], 现在=现在)
    return 卡, None


def 摘要化(值, 深=0):
    """给卡片看的结果:**结构不变、只把长的截短**,所以永远是合法 JSON(复审 P1-02:原来把序列化后的字串直接砍到两万字,读回来解析就炸)。
    → (摘要, 截过没)。字串超 摘要字数 → 开头 + 「…(已截短,共 N 字)」;列表超 摘要项数 → 前几项 + 说明;太深 → 「<…>」。"""
    if isinstance(值, str):
        if len(值) > 摘要字数:
            return 值[:摘要字数] + f"…(已截短,共 {len(值)} 字)", True
        return 值, False
    if 深 >= 8:
        return "<…太深,看完整结果>", True
    if isinstance(值, dict):
        出, 截 = {}, False
        for i, (k, v) in enumerate(值.items()):
            if i >= 60:
                出["__更多__"] = f"…还有 {len(值) - 60} 项,看完整结果"; 截 = True; break
            出[str(k)], t = 摘要化(v, 深 + 1); 截 = 截 or t
        return 出, 截
    if isinstance(值, (list, tuple)):
        出, 截 = [], False
        for v in list(值)[:摘要项数]:
            x, t = 摘要化(v, 深 + 1); 出.append(x); 截 = 截 or t
        if len(值) > 摘要项数:
            出.append(f"…(已截短,共 {len(值)} 项)"); 截 = True
        return 出, 截
    return 值, False


def 收尾(路径, aid, 成功, 结果, 状态=None):
    """执行完了记结果。`状态` 不给就按 成功 布尔定(老调用方不用改);给了只认 结束状态们。
    完整结果原样存 result_full(带 sha256 和字节数),卡上的 result_json 存**摘要**(合法 JSON)—— 两份都在,页面按需要拿。"""
    状态 = 状态 or ("已成功" if 成功 else "已失败")
    if 状态 not in 结束状态们:
        raise ValueError(f"收尾状态只认 {结束状态们},拿到 {状态!r}")
    完整 = json.dumps(结果, ensure_ascii=False, default=str)
    摘要, 截 = 摘要化(json.loads(完整))
    c = _连(路径)
    try:
        n = c.execute("update pending_action set status=?, result_json=? where id=? and status='执行中'",
                      (状态, json.dumps(摘要, ensure_ascii=False), aid)).rowcount
        if n == 1:
            c.execute("insert or replace into pending_action_result (aid, result_full, sha256, byte_count, truncated) values (?,?,?,?,?)",
                      (aid, 完整, hashlib.sha256(完整.encode("utf-8")).hexdigest(), len(完整.encode("utf-8")), 1 if 截 else 0))
    finally:
        c.close()


def 核对回写(路径, aid, 结论, 说明, 处理人=None, 处理时间=None):
    """「核对中」的卡,人工核对出结论后写回(用户 11-25 拍「核对中要回写」):
        已执行 → 已成功;未执行 → 未执行;说不清 → 还是核对中(但把人的说明带上卡,店员看得到有人核过)。
    只动 status 还是「核对中」的卡;结果里加「核对结论 / 核对说明 / 核对人 / 核对时间」,原结果其余字段不动。→ 改了几行。"""
    映 = {"已执行": "已成功", "未执行": "未执行", "说不清": "核对中"}
    if 结论 not in 映:
        raise ValueError(f"核对结论只认 {tuple(映)},拿到 {结论!r}")
    c = _连(路径)
    try:
        r = c.execute("select result_json from pending_action where id=? and status='核对中'", (str(aid),)).fetchone()
        if r is None:
            return 0
        结果 = json.loads(r["result_json"]) if r["result_json"] else {}
        if not isinstance(结果, dict):
            结果 = {"原结果": 结果}
        结果.update({"核对结论": 结论, "核对说明": str(说明 or "")[:1000], "核对人": 处理人, "核对时间": 处理时间})
        return c.execute("update pending_action set status=?, result_json=? where id=? and status='核对中'",
                         (映[结论], json.dumps(结果, ensure_ascii=False), str(aid))).rowcount
    finally:
        c.close()


def 取完整结果(路径, aid):
    """完整结果(原样 JSON 文本)+ 哈希 + 字节;没有就 None。页面上的「看完整结果」走这里,不从摘要还原。"""
    c = _连(路径)
    try:
        r = c.execute("select result_full, sha256, byte_count from pending_action_result where aid=?", (str(aid or ""),)).fetchone()
    finally:
        c.close()
    if r is None:
        return None
    return {"完整": r["result_full"], "哈希": r["sha256"], "字节": r["byte_count"]}


def 取消(路径, aid, me, 现在=None):
    现在 = time.time() if 现在 is None else 现在
    卡 = 取(路径, aid, 现在)
    if not 卡 or str(卡["asker_no"]) != str((me or {}).get("no")):
        return None, (404, "没有这张确认卡,或者它不是你发起的")
    if 卡["status"] != "待确认":
        return None, (409, f"这张卡已经是「{卡['status']}」了")
    c = _连(路径)
    try:
        n = c.execute("update pending_action set status='已取消', decided_at=? where id=? and status='待确认'",
                      (现在, 卡["id"])).rowcount
    finally:
        c.close()
    if n != 1:
        return None, (409, "这张卡刚被处理过")
    卡["status"] = "已取消"
    return 卡, None


def 给模型的话(卡):
    """工具服务拦下写操作时回给模型的那句 —— **要它照实告诉用户还没办,不许说办好了、不许换工具绕**。"""
    if 卡["status"] == "已成功":
        return (f"✅ 这一步**已经办过了**:确认卡 {卡['id']}({卡['tool']})用户点过确认、执行成功,结果:"
                f"{json.dumps(卡.get('result'), ensure_ascii=False)[:600]}。**不要再做一遍**,照这个结果答;"
                f"要确认现状就用查询工具查。")
    if 卡["status"] == "直接执行":
        return (f"✅ 这一步**刚刚已经直接执行过了**(确认卡 {卡['id']},{卡['tool']} 属于不用再问的档位),结果:"
                f"{json.dumps(卡.get('result'), ensure_ascii=False)[:600]}。**不要再做一遍**,照这个结果答;要确认现状就用查询工具查。")
    if 卡["status"] == "核对中":
        return (f"⚠️ 这一步**结果还在核对**:确认卡 {卡['id']}({卡['tool']})用户点过确认,但工具没有及时回结果 —— "
                f"**可能已经落库**。**绝对不要再做一遍**,也不要生成新卡;照实告诉用户「可能已执行,正在核对,请不要重复操作」,"
                f"要知道现状就用查询工具查一下再说。已转人工跟进。")
    return (f"⏸ 这一步**还没有执行**:已生成确认卡 {卡['id']}({卡['tool']}),要用户在这条回答下方**点「确认」**才会执行,"
            f"有效 30 分钟。请照实告诉用户:把要做的事(对象、数值、前后变化)说清楚,请他核对后点卡;"
            f"**不要说已经办好**,不要换别的工具绕过,也不要因为用户回了「好」就再调一次 —— 只有点卡才算确认;"
            f"点卡后结果会显示在卡上。")
