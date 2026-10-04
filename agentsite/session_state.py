# -*- coding: utf-8 -*-
"""**会话的业务状态跨请求恢复** —— 外部审阅 2026-10-03 §4.2。

`sdk.run` 每次都 `state = {}`。续聊传了 CLI 的 session id,历史还在,
但 hook 记的**当前方案、按号取过的单据(锚点)、待处理的压缩标记**全在那个字典里,下一轮就没了 ——
「结构化恢复」这条承诺不成立。CLI 历史可能还在、模型也不一定答错,但兜底没了。

## 只恢复跨轮的那几样,不整包回灌

    跨轮(恢复)   当前方案 · 锚点 · 刚压缩过(待消费的压缩提醒)
    本轮(重置)   calls · 违规 · 修正次数 · 答案检查 · 生效工具 · prompt · 注入原文 …

整包回灌的话,上一轮的违规会算到这一轮、预算计数会累加、上一轮的工具调用会冒充这一轮查过。

## 先验归属和当前权限,再加载

存的时候记下所有者的工号、角色、门店。加载时三样都要对得上:
工号不同 → 别人的会话;**角色或门店变了 → 不恢复**(旧历史里有按旧权限取到的数据,
sessions.check 也会拒续聊)。

## 会变的数据执行前重查

方案可能已经被删、被改状态。恢复「当前方案」时重查一次:不在了就不带回来,并留一句说明。
状态、金额照工具现查为准 —— 这里只恢复**引用**(方案号),不把旧状态当最新事实。

## 并发:版本号

同一个会话两个请求交错写,后写的如果基于旧版本,**不覆盖**(返回冲突),不悄悄盖掉更新的状态。
"""
import json, os, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, ".session_state.db")       # 和 .sessions.json 放在一起,重启还在
业务库 = os.path.join(HERE, "..", "backend", "lanxiu.db")

跨轮键 = ("当前方案", "锚点", "刚压缩过")

DDL = """CREATE TABLE IF NOT EXISTS session_state(
  sid       TEXT PRIMARY KEY,        -- SDK 的 session id
  owner_no  TEXT NOT NULL, owner_role TEXT, owner_shop TEXT,
  data      TEXT NOT NULL,           -- 只有跨轮键,JSON
  version   INTEGER NOT NULL,
  updated   TEXT NOT NULL)"""


def _连(path=None):
    c = sqlite3.connect(path or PATH)
    c.execute(DDL)
    return c


def 加载(sid, me, path=None, 业务库路径=None):
    """返回 (要并进 state 的 dict, 版本, 说明列表)。不恢复时返回 ({}, None, [为什么])。"""
    if not sid or not (me or {}).get("no"):
        return {}, None, []
    c = _连(path)
    try:
        r = c.execute("SELECT owner_no, owner_role, owner_shop, data, version FROM session_state WHERE sid=?",
                      (str(sid),)).fetchone()
    finally:
        c.close()
    if not r:
        return {}, None, []
    no, role, shop, data, ver = r
    if str(no) != str(me["no"]):
        return {}, None, ["这条会话的业务状态是别人的,不恢复"]
    if (role or "") != (me.get("role") or "") or (shop or "") != (me.get("shop") or ""):
        return {}, None, [f"你的角色 / 门店变了(原来 {role}·{shop or '—'}),上一轮的业务状态不恢复"]
    d = {k: v for k, v in json.loads(data or "{}").items() if k in 跨轮键}
    说 = []
    当 = d.get("当前方案")
    if 当:
        try:
            b = sqlite3.connect(f"file:{业务库路径 or 业务库}?mode=ro", uri=True)
            有 = b.execute("SELECT status FROM scheme WHERE id=?", (当.get("号"),)).fetchone()
            b.close()
        except sqlite3.Error:
            有 = None
        if not 有:
            d.pop("当前方案")
            说.append(f"上一轮在谈的方案 {当.get('号')} 已经不在了,没有带回来")
        else:
            当["状态"] = 有[0]          # 状态以现在库里的为准,不用旧的
    return d, ver, 说


def 保存(sid, me, state, 基于版本=None, path=None):
    """把跨轮键存下来。返回 (成没成, 说明)。**基于的版本不是最新 → 不覆盖**。"""
    if not sid or not (me or {}).get("no"):
        return False, "没有会话号或身份,不存"
    d = {k: state[k] for k in 跨轮键 if state.get(k) not in (None, {}, [])}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c = _连(path)
    try:
        with c:
            cur = c.execute("SELECT version, owner_no FROM session_state WHERE sid=?", (str(sid),)).fetchone()
            if cur is None:
                c.execute("INSERT INTO session_state(sid, owner_no, owner_role, owner_shop, data, version, updated)"
                          " VALUES(?,?,?,?,?,?,?)", (str(sid), str(me["no"]), me.get("role"), me.get("shop"),
                                                      json.dumps(d, ensure_ascii=False), 1, now))
                return True, "新存"
            if str(cur[1]) != str(me["no"]):
                return False, "这条会话是别人的,不存"
            if 基于版本 is not None and cur[0] != 基于版本:
                return False, f"会话状态在别处更新过(现在是第 {cur[0]} 版,这一轮基于第 {基于版本} 版),不覆盖"
            c.execute("UPDATE session_state SET data=?, version=version+1, updated=?, owner_role=?, owner_shop=? "
                      "WHERE sid=?", (json.dumps(d, ensure_ascii=False), now, me.get("role"), me.get("shop"), str(sid)))
            return True, f"第 {cur[0] + 1} 版"
    finally:
        c.close()
