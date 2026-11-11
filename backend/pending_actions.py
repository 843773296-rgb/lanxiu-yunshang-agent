# -*- coding: utf-8 -*-
"""写操作确认卡 —— 待确认动作的存储与状态流转(用户 2026-11-11 拍)。

## 为什么要有它

原来「动手前先跟用户对一遍」**只写在提示词里**(boundary_audit 记成「约定」):模型不问就写,没有任何东西会拦。
用户 11-11 拍板(一张卡,四问):
  · 聊天里 **29 个写操作全部出卡**,只读不出;新加的写操作没登记就禁止(登记处是 api.WRITE_TOOLS)
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
终态 = ("已成功", "已失败", "已取消", "已过期")

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
    if d["status"] == "待确认" and (现在 if 现在 is not None else time.time()) >= d["expires_at"]:
        d["status"] = "已过期"           # 读的时候现算:过期不靠后台扫,也就不会有「该过期而没过期」的窗口
    return d


def 建(路径, tool, domain, args, me, trace=None, session=None, 现在=None):
    """建一张待确认卡 → 卡。同一轮(trace)同一份参数再调一次,拿回同一张(模型重试不多出卡)。"""
    if not (me or {}).get("no"):
        raise PermissionError("没有登录身份 —— 写操作要记是谁发起的,确认时也只认这个人")
    现在 = time.time() if 现在 is None else 现在
    指 = 参数指纹(tool, args)
    c = _连(路径)
    try:
        # 同一个人、同一份参数,30 分钟内已经点卡执行成功过 → 不再出新卡,拿回那张(模型下一轮以为没办成又调一次)
        办过 = c.execute("""select * from pending_action where asker_no=? and fingerprint=? and status='已成功'
                            and decided_at>? order by decided_at desc limit 1""",
                         (str(me["no"]), 指, 现在 - 有效秒)).fetchone()
        if 办过 is not None:
            return _行(办过, 现在)
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


def 取(路径, aid, 现在=None):
    c = _连(路径)
    try:
        return _行(c.execute("select * from pending_action where id=?", (str(aid or ""),)).fetchone(), 现在)
    finally:
        c.close()


def 本轮的(路径, trace, 现在=None):
    """这一轮生成的卡(给聊天页画)。"""
    if not trace:
        return []
    c = _连(路径)
    try:
        return [_行(r, 现在) for r in c.execute("select * from pending_action where trace=? order by created_at", (trace,))]
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
    return 卡, None


def 收尾(路径, aid, 成功, 结果):
    c = _连(路径)
    try:
        c.execute("update pending_action set status=?, result_json=? where id=? and status='执行中'",
                  ("已成功" if 成功 else "已失败", json.dumps(结果, ensure_ascii=False, default=str)[:20000], aid))
    finally:
        c.close()


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
    return (f"⏸ 这一步**还没有执行**:已生成确认卡 {卡['id']}({卡['tool']}),要用户在这条回答下方**点「确认」**才会执行,"
            f"有效 30 分钟。请照实告诉用户:把要做的事(对象、数值、前后变化)说清楚,请他核对后点卡;"
            f"**不要说已经办好**,不要换别的工具绕过,也不要因为用户回了「好」就再调一次 —— 只有点卡才算确认;"
            f"点卡后结果会显示在卡上。")
