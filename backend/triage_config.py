#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判设置:草稿 → 试运行 → 发布 → 退回(研判队列未做项第 5 项第二步 · 用户 2026-10-19 拍)。

用户拍的范围:
  · 开放三样 —— **时限**(各类工单多久算超时)、**批量条数**(「研判 N 条」一次最多几条)、
    **提示词版本**(在开发登记并验证过的版本之间切换;提示词正文仍由开发改);
  · **角色权限一律不开放**(谁能复核 / 办结)—— 一次误配就能让一个人走完「两个人把关」;
  · **只有开发能发布**:总部运营在页面上改草稿、试运行,发布 / 退回由开发用 `tools/triage_config.py` 执行。

生效规则(方案选项 A 原文「新任务绑定当时发布的版本,进行中的不受影响」):
  · 时限:一张工单用**它建单那一刻**已经生效的那一版 —— 发布之前建的单照旧,不会一发布就成片「超时」;
  · 批量条数、提示词版本:用**当下**生效的那一版(一次研判是一次性的动作,没有「进行中」)。
  · 没发布过任何一版 → 用代码里的默认值(`ops.SLA_HOURS` / 10 条 / 代码当前的提示词)。

时间一律用**世界时间**(`ops.now()`):工单的建单时间是世界时间,要和它比就得同一种钟;
这两列都是整列日期,`shift_world` 会自动跟着挪,「发布在建单之前还是之后」平移后不变。

历史只增不改:发布是把一份草稿标成已发布;退回 = 把上一版的内容**再发布一次**(新记一行,写明退回到哪一版)。
"""
import json
import os
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

可编辑角色 = ("总部运营",)
批量默认上限 = 10
批量可选 = range(1, 21)          # 一次最多 20 条:再多一批就要跑十几分钟,而执行线程一次只跑一条
时限可选 = range(1, 24 * 30 + 1)  # 1 小时 ~ 30 天
# 占位单号 —— 和 ops.研判提示词版本 用的是同一组,模板里的这几个串在渲染时换回真单号
占位 = ("§甲§|§乙§", "T§单号§")


def _now():
    import ops
    return ops.now().strftime("%Y-%m-%d %H:%M:%S")


def _连(db=None):
    import ops
    c = sqlite3.connect(db or ops.DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def 确保表(c):
    c.execute("""CREATE TABLE IF NOT EXISTS triage_config(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT NOT NULL,          -- 草稿 / 已发布 / 作废
        payload TEXT NOT NULL,         -- {"时限":{类型:小时}, "批量上限":n, "提示词版本":{类型:指纹}}
        note TEXT,
        created TEXT, created_by TEXT,
        tried_at TEXT, tried_by TEXT, tried_report TEXT,
        published_at TEXT, published_by TEXT,
        rollback_of INTEGER,
        snapshot TEXT)                 -- 发布那一刻**完整的**一份配置(草稿只存改了的那几项)""")
    if "snapshot" not in {r[1] for r in c.execute("PRAGMA table_info(triage_config)")}:
        c.execute("ALTER TABLE triage_config ADD COLUMN snapshot TEXT")   # 10-19 当天先建过一版没有这列的表
    c.execute("""CREATE TABLE IF NOT EXISTS triage_prompt(
        fp TEXT PRIMARY KEY,           -- ops.研判提示词版本 那个 12 位指纹
        task_type TEXT NOT NULL,
        template TEXT NOT NULL,        -- 用占位单号渲染出来的全文 —— 渲染时把占位换回真单号
        created TEXT,
        verified INTEGER DEFAULT 0,    -- 开发跑过评测、确认能用 → 1;没验证的版本运营选不了
        verified_note TEXT)""")


# ── 提示词版本登记 ───────────────────────────────────────────────────────
def 当前代码版本(task_type):
    """→ (指纹, 模板全文)。真调 `ops.研判提示词`,不另抄一份模板。"""
    import ops, hashlib
    _, _, 词 = ops.研判提示词(task_type, *占位)
    return hashlib.sha256(词.encode("utf-8")).hexdigest()[:12], 词


def 登记当前版本(db=None, 验证=None):
    """把代码里现在的三类提示词登记进版本表(已有的不动)。→ {类型: 指纹}。
    `验证=(说明)` 时顺带标成已验证 —— 只有开发跑过评测之后才这么用。"""
    import ops
    出 = {}
    with closing(_连(db)) as c, c:
        确保表(c)
        for 类 in ops.断点:
            fp, 词 = 当前代码版本(类)
            c.execute("INSERT OR IGNORE INTO triage_prompt(fp,task_type,template,created) VALUES(?,?,?,?)",
                      (fp, 类, 词, _now()))
            if 验证:
                c.execute("UPDATE triage_prompt SET verified=1, verified_note=? WHERE fp=?", (验证, fp))
            出[类] = fp
    return 出


def 版本们(db=None):
    with closing(_连(db)) as c:
        确保表(c)
        return [dict(r) for r in c.execute(
            "SELECT fp, task_type, created, verified, verified_note FROM triage_prompt ORDER BY task_type, created")]


def 渲染(fp, task_type, ref, task_id, db=None):
    """按登记的那一版生成提示词:把模板里的占位换回真单号。→ 全文;没登记 / 类型不符 → 抛错。"""
    with closing(_连(db)) as c:
        确保表(c)
        r = c.execute("SELECT task_type, template FROM triage_prompt WHERE fp=?", (fp,)).fetchone()
    if not r:
        raise ValueError(f"提示词版本 {fp} 没登记")
    if r["task_type"] != task_type:
        raise ValueError(f"提示词版本 {fp} 是「{r['task_type']}」的,不是「{task_type}」的")
    词 = r["template"]
    if "|" in str(ref):
        甲, 乙 = str(ref).split("|", 1)
        词 = 词.replace(占位[0], str(ref)).replace("§甲§", 甲).replace("§乙§", 乙)
    else:
        词 = 词.replace(占位[0], str(ref))
    return 词.replace("§单号§", str(task_id)[1:]).replace(占位[1], str(task_id))


# ── 生效 ─────────────────────────────────────────────────────────────────
def _已发布(c):
    确保表(c)
    return [dict(r, payload=json.loads(r["payload"])) for r in c.execute(
        "SELECT * FROM triage_config WHERE status='已发布' ORDER BY published_at, id")]


def 默认():
    import ops
    return {"时限": dict(ops.SLA_HOURS), "批量上限": 批量默认上限, "提示词版本": {}}


def _合(底, 改):
    """底(一份完整配置)+ 改(草稿里改了的那几项)→ 新的一份完整配置。"""
    出 = {"时限": dict(底["时限"]), "批量上限": 底["批量上限"], "提示词版本": dict(底["提示词版本"])}
    出["时限"].update((改 or {}).get("时限") or {})
    if (改 or {}).get("批量上限"):
        出["批量上限"] = int(改["批量上限"])
    出["提示词版本"].update((改 or {}).get("提示词版本") or {})
    return 出


def _快照(r):
    """一版已发布的完整配置。⚠️ 用发布时存下的快照,**不用草稿里那几项去叠** —— 叠的话退回到
    「第一版之前」时没东西可叠,时限停在被撤下那一版(10-19 写检查时当场踩到)。"""
    return json.loads(r["snapshot"]) if r.get("snapshot") else _合(默认(), r["payload"])


def 生效(当下=None, db=None):
    """→ (这一刻生效的那一份完整配置, 版本号或 None)。没发布过 → 代码默认值。"""
    当下 = 当下 or _now()
    with closing(_连(db)) as c:
        版 = [r for r in _已发布(c) if r["published_at"] <= 当下]
    return (_快照(版[-1]), 版[-1]["id"]) if 版 else (默认(), None)


def 时限查询器(db=None):
    """给 `ops.queue()` 用:一次读完发布历史,返回 f(类型, 建单时刻) → 小时。不逐张工单查库。"""
    import ops
    with closing(_连(db)) as c:
        历史 = [(r["published_at"], _快照(r)["时限"]) for r in _已发布(c)]
    def f(task_type, 建单):
        时 = ops.SLA_HOURS
        for 发布于, 表 in 历史:              # 按发布时间升序:最后一个 <= 建单 的那一版说了算
            if 发布于 <= (建单 or ""):
                时 = 表
        return 时.get(task_type, ops.DEFAULT_SLA)
    return f


# ── 草稿 / 试运行(总部运营,页面上)────────────────────────────────────────
def _校验(payload, c):
    import ops
    p = dict(payload or {})
    错 = []
    时 = p.get("时限") or {}
    for 类, h in 时.items():
        if 类 not in ops.SLA_HOURS:
            错.append(f"「{类}」不是研判队列里的工单类型")
        elif not (isinstance(h, int) and h in 时限可选):
            错.append(f"「{类}」的时限 {h} 不对 —— 要 1 到 {时限可选[-1]} 之间的整数小时")
    n = p.get("批量上限")
    if n is not None and not (isinstance(n, int) and n in 批量可选):
        错.append(f"批量上限 {n} 不对 —— 要 1 到 {批量可选[-1]} 之间的整数")
    for 类, fp in (p.get("提示词版本") or {}).items():
        r = c.execute("SELECT task_type, verified FROM triage_prompt WHERE fp=?", (fp,)).fetchone()
        if not r:
            错.append(f"提示词版本 {fp} 没登记")
        elif r["task_type"] != 类:
            错.append(f"提示词版本 {fp} 是「{r['task_type']}」的,不能用在「{类}」")
        elif not r["verified"]:
            错.append(f"提示词版本 {fp} 还没验证过 —— 开发跑过评测、标了已验证才能选")
    多 = set(p) - {"时限", "批量上限", "提示词版本"}
    if 多:
        错.append(f"这些不开放配置:{sorted(多)}(用户 10-19 拍:只开放时限 / 批量条数 / 提示词版本,角色权限一律不开放)")
    return 错


def _要编辑权(me):
    me = me or {}
    if not me.get("no"):
        raise PermissionError("没有身份 —— 要登录")
    if me.get("role") not in 可编辑角色:
        raise PermissionError(f"研判设置只有 {' / '.join(可编辑角色)} 能改,你是「{me.get('role')}」")


def 草拟(payload, me, note=None, db=None):
    """新建一份草稿。→ {ok, id} 或 {ok:False, 错:[…]}。"""
    from oplog import log_op
    _要编辑权(me)
    with closing(_连(db)) as c, c:
        确保表(c)
        错 = _校验(payload, c)
        if 错:
            return dict(ok=False, 错=错)
        rid = c.execute("INSERT INTO triage_config(status,payload,note,created,created_by) VALUES('草稿',?,?,?,?)",
                        (json.dumps(payload, ensure_ascii=False), (note or "").strip() or None, _now(),
                         f"{me.get('name')}({me['no']})")).lastrowid
    log_op(f"{me.get('name')}({me['no']})", "triage_config", f"配置#{rid}", "—", "草稿", True, "CFG_DRAFT",
           (note or "")[:120], {"payload": payload})
    return dict(ok=True, id=rid)


def 试运行(cfg_id, me, db=None):
    """不改任何东西,算出「发布之后会怎样」并记下来。**没试运行过的发布不了。** → 报告。"""
    import ops
    from oplog import log_op
    _要编辑权(me)
    当前, _ = 生效(db=db)
    with closing(_连(db)) as c, c:
        确保表(c)
        r = c.execute("SELECT * FROM triage_config WHERE id=?", (cfg_id,)).fetchone()
        if not r or r["status"] != "草稿":
            return dict(ok=False, 错=[f"配置#{cfg_id} 不是草稿"])
        p = json.loads(r["payload"])
        错 = _校验(p, c)
        if 错:
            return dict(ok=False, 错=错)
        报 = []
        for 类, h in (p.get("时限") or {}).items():
            旧 = 当前["时限"].get(类, ops.DEFAULT_SLA)
            if h != 旧:
                在办 = c.execute("SELECT COUNT(*) FROM task WHERE type=? AND status NOT IN ('已关闭','已处理')",
                                (类,)).fetchone()[0]
                报.append(f"「{类}」时限 {旧} → {h} 小时:现在在办的 {在办} 条**不受影响**(按它们建单时的那一版算),"
                          f"发布之后新建的才按 {h} 小时")
        if p.get("批量上限") and p["批量上限"] != 当前["批量上限"]:
            报.append(f"「研判 N 条」一次最多 {当前['批量上限']} → {p['批量上限']} 条")
        for 类, fp in (p.get("提示词版本") or {}).items():
            旧 = 当前["提示词版本"].get(类) or 当前代码版本(类)[0]
            if fp != 旧:
                报.append(f"「{类}」提示词 {旧} → {fp}:发布之后新跑的研判用新版,已有的研判不重跑;每条研判记着自己用的版本")
        if not 报:
            报.append("和现在生效的那一版没有区别 —— 发布了也不会有任何变化")
        c.execute("UPDATE triage_config SET tried_at=?, tried_by=?, tried_report=? WHERE id=?",
                  (_now(), f"{me.get('name')}({me['no']})", "\n".join(报), cfg_id))
    log_op(f"{me.get('name')}({me['no']})", "triage_config", f"配置#{cfg_id}", "草稿", "草稿", True, "CFG_TRY",
           "试运行", {"报告": 报})
    return dict(ok=True, 报告=报, 发布方法=f"发布要找开发执行:python3 tools/triage_config.py 发布 {cfg_id} --by <开发名字>")


# ── 发布 / 退回(只有开发,经 tools/triage_config.py)──────────────────────
def 发布(cfg_id, 开发, db=None):
    from oplog import log_op
    if not (开发 or "").strip():
        raise PermissionError("发布要写明是哪位开发 —— 只有开发能发布(用户 10-19 拍)")
    with closing(_连(db)) as c, c:
        确保表(c)
        r = c.execute("SELECT * FROM triage_config WHERE id=?", (cfg_id,)).fetchone()
        if not r or r["status"] != "草稿":
            return dict(ok=False, reason=f"配置#{cfg_id} 不是草稿")
        if not r["tried_at"]:
            return dict(ok=False, reason=f"配置#{cfg_id} 还没试运行 —— 先在页面上点「试运行」看清会发生什么")
        错 = _校验(json.loads(r["payload"]), c)          # 试运行之后版本可能被撤了验证
        if 错:
            return dict(ok=False, reason=";".join(错))
        全 = _合(生效(db=db)[0], json.loads(r["payload"]))
        c.execute("UPDATE triage_config SET status='已发布', published_at=?, published_by=?, snapshot=? WHERE id=?",
                  (_now(), 开发.strip(), json.dumps(全, ensure_ascii=False), cfg_id))
    log_op(开发.strip(), "triage_config", f"配置#{cfg_id}", "草稿", "已发布", True, "CFG_PUBLISH", "发布", {})
    return dict(ok=True, reason=f"配置#{cfg_id} 已发布")


def 退回上一版(开发, db=None):
    """把「现在生效那一版之前的那一版」再发布一次(新记一行)。没有上一版 → 退回到默认值(空配置)。"""
    from oplog import log_op
    if not (开发 or "").strip():
        raise PermissionError("退回要写明是哪位开发")
    with closing(_连(db)) as c, c:
        版 = _已发布(c)
        if not 版:
            return dict(ok=False, reason="还没有发布过任何一版,没东西可退")
        上 = _快照(版[-2]) if len(版) >= 2 else 默认()       # 上一版的**完整**配置;没有更早的 → 代码默认值
        rid = c.execute("INSERT INTO triage_config(status,payload,note,created,created_by,tried_at,tried_by,"
                        "published_at,published_by,rollback_of,snapshot) VALUES('已发布',?,?,?,?,?,?,?,?,?,?)",
                        (json.dumps(上, ensure_ascii=False), f"退回:撤下配置#{版[-1]['id']}", _now(), 开发.strip(),
                         _now(), 开发.strip(), _now(), 开发.strip(), 版[-1]["id"],
                         json.dumps(上, ensure_ascii=False))).lastrowid
    log_op(开发.strip(), "triage_config", f"配置#{rid}", f"配置#{版[-1]['id']}", "已发布", True, "CFG_ROLLBACK",
           f"退回上一版(撤下配置#{版[-1]['id']})", {})
    return dict(ok=True, id=rid, reason=f"已退回:撤下配置#{版[-1]['id']},现在生效的是它之前那一版"
                                        + ("" if len(版) >= 2 else "(没有更早的,回到代码默认值)"))


def 概览(db=None):
    """页面用:现在生效什么、历史、草稿、可选的提示词版本。"""
    当前, 号 = 生效(db=db)
    with closing(_连(db)) as c:
        确保表(c)
        历史 = [dict(r, payload=json.loads(r["payload"])) for r in c.execute(
            "SELECT * FROM triage_config ORDER BY id DESC LIMIT 30")]
    import ops
    return dict(生效=当前, 生效版本=号, 历史=历史, 提示词版本=版本们(db),
                代码当前版本={类: 当前代码版本(类)[0] for 类 in ops.断点},
                可编辑角色=list(可编辑角色), 批量可选=[批量可选[0], 批量可选[-1]], 时限可选=[时限可选[0], 时限可选[-1]])
