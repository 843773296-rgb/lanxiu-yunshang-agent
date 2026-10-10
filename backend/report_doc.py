#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经营报告的保存与确认(日报 / 周报 / 月报;用户 2026-10-09:三种都要;10-10 定:只保存、不自动发送)。

    保存   店长把 chat 写好的报告存成**草稿**;每存一次是**新的一版**(revision),旧版不覆盖
    确认   店长核过以后点确认;**必选指标缺了不许确认**(取数包里的「能不能确认」)
    确认后 不能改 —— 要改就再存一版(supersedes 指回被替代的那一版),历史留着

⚠️ 保存时把**当时的取数包冻结**存进 pack —— 报告里的数是那一刻的数,
之后数据再变(每天上新、补录),这份报告不跟着漂。
> 一份「当时就是这个数」的报告和一份「打开时现算」的报告,在页面上长得一模一样 ——
> 而后者会让三个月前确认过的周报,今天打开数字变了。

身份从登录会话来,入参里没有身份字段(同其余写口)。范围:店长本店、总部全部;顾问 / 工坊不碰。
时间用**世界的今天**(worldclock),和报告期同一个钟。
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge")]
DB = os.path.join(HERE, "lanxiu.db")

DDL = """
CREATE TABLE IF NOT EXISTS store_report_doc(
  id TEXT PRIMARY KEY,          -- RPT + 自增序号;**一版一行**,旧版不覆盖
  shop TEXT NOT NULL,           -- 哪家店的报告(总部看全部时也必须落到一家店)
  kind TEXT NOT NULL,           -- 日 / 周 / 月
  period_start TEXT NOT NULL,   -- 报告期起止(含两端,YYYY-MM-DD)
  period_end TEXT NOT NULL,
  revision INTEGER NOT NULL,    -- 同一家店、同一种、同一期的第几版
  status TEXT NOT NULL,         -- 草稿 / 已确认
  body TEXT NOT NULL,           -- 报告正文(chat 写的、店长改过的)
  pack TEXT NOT NULL,           -- 保存那一刻冻结的取数包(JSON)—— 数字以它为准
  supersedes TEXT,              -- 确认后再改:新的一版指回被替代的那一版
  created_at TEXT NOT NULL, created_by TEXT NOT NULL,
  confirmed_at TEXT, confirmed_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_rptdoc_key ON store_report_doc(shop, kind, period_start, revision);
"""
# 后加的列(10-10 产出监督):建表语句不改 —— 老库里表已经在,CREATE IF NOT EXISTS 不会补列;
# 补列走 ALTER,有就跳过。**只写一处**:CI 从零建和本地老库走的是同一段
后加列 = [
    ("trace_id", "TEXT"),        # 生成这一版的那一轮对话(sdk 的 trace_id,经 MCP env 的 LANXIU_TRACE 传进来)
    ("rejected_at", "TEXT"),     # AI 管理平台打回:什么时候、谁、为什么 —— 打回的那一版不许确认
    ("rejected_by", "TEXT"),
    ("reject_reason", "TEXT"),
]

管理角色 = ("店长", "总部运营")
正文上限 = 20000
# 页面地址(用户 10-10:确认后要给个链接能直达)。**站内相对路径** —— 对话页和报告页同一个站,
# 写死主机和端口的话换一台机器 / 换个端口就是一条死链,而死链在回复里和活链长得一样
全部报告 = "/report"


def 链接(report_id):
    return f"{全部报告}?id={report_id}"


def 下载(report_id):
    """PDF 下载地址(用户 10-10:chat 里要能直接下 PDF)。出 PDF 在 agentsite/report_pdf.py"""
    return f"{全部报告}.pdf?id={report_id}"


def 建表(c=None, db=None):
    own = c is None
    c = c or sqlite3.connect(db or DB)
    c.executescript(DDL)
    有 = {r[1] for r in c.execute("PRAGMA table_info(store_report_doc)")}
    for 列, 型 in 后加列:
        if 列 not in 有:
            c.execute(f"ALTER TABLE store_report_doc ADD COLUMN {列} {型}")
    if own:
        c.commit(); c.close()


def _今天():
    import worldclock
    return worldclock.今天().isoformat()


def _记(actor, target, code, ok, reason, ctx):
    try:
        import oplog
        oplog.log_op(actor, None, target, None, None, ok, code, reason, ctx)
    except Exception:
        pass        # 台账写不进不挡业务 —— 但业务结果照实返回


def _能管(me, shop):
    if me.get("role") not in 管理角色:
        return False
    return me.get("role") == "总部运营" or me.get("shop") == shop


def 保存(me, pack, body, report_id=None, db=None, trace=None):
    """存一版草稿。pack 是 api.store_report 刚取的取数包(由调用方传进来,本模块不取数)。"""
    if me.get("role") not in 管理角色:
        return dict(ok=False, code="NOT_MANAGER", reason="经营报告只有店长 / 总部能保存")
    body = (body or "").strip()
    if not body:
        return dict(ok=False, code="EMPTY", reason="正文是空的 —— 先让我写好、你看过再存")
    if len(body) > 正文上限:
        return dict(ok=False, code="TOO_LONG", reason=f"正文超过 {正文上限} 字")
    if "error" in pack:
        return dict(ok=False, code="NO_PACK", reason=f"取数包取不到:{pack['error']}")
    shop = me.get("shop") if me.get("role") != "总部运营" else pack.get("范围")
    if not shop or shop == "全部门店":
        return dict(ok=False, code="NO_SHOP", reason="报告要落到一家店 —— 总部存报告时先说明是哪家店的")
    起, 止 = pack["区间"][:10], pack["区间"][13:23]
    c = sqlite3.connect(db or DB)
    try:
        建表(c)
        前 = None
        if report_id:
            前 = c.execute("SELECT id,shop,kind,period_start,status FROM store_report_doc WHERE id=?",
                          (report_id,)).fetchone()
            if not 前 or not _能管(me, 前[1]):
                return dict(ok=False, code="NOT_FOUND", reason=f"没有 {report_id} 这份报告,或者它不在你的范围里")
            if (前[2], 前[3]) != (pack["种类"], 起):
                return dict(ok=False, code="PERIOD_MISMATCH",
                            reason=f"{report_id} 是 {前[3]} 的{前[2]}报,这次取的是 {起} 的{pack['种类']}报 —— "
                                   "换了报告期就是另一份报告,不要接在它后面存")
        版 = (c.execute("SELECT MAX(revision) FROM store_report_doc WHERE shop=? AND kind=? AND period_start=?",
                       (shop, pack["种类"], 起)).fetchone()[0] or 0) + 1
        上一版已确认 = c.execute("SELECT id FROM store_report_doc WHERE shop=? AND kind=? AND period_start=? "
                            "AND status='已确认' ORDER BY revision DESC LIMIT 1", (shop, pack["种类"], 起)).fetchone()
        序 = (c.execute("SELECT COUNT(*) FROM store_report_doc").fetchone()[0] or 0) + 1
        rid = f"RPT{序:06d}"
        while c.execute("SELECT 1 FROM store_report_doc WHERE id=?", (rid,)).fetchone():
            序 += 1; rid = f"RPT{序:06d}"
        c.execute("INSERT INTO store_report_doc(id,shop,kind,period_start,period_end,revision,status,body,pack,"
                  "supersedes,created_at,created_by,trace_id) VALUES(?,?,?,?,?,?,'草稿',?,?,?,?,?,?)",
                  (rid, shop, pack["种类"], 起, 止, 版, body, json.dumps(pack, ensure_ascii=False, default=str),
                   上一版已确认[0] if 上一版已确认 else None, _今天(), me.get("no"), trace))
        c.commit()
    finally:
        c.close()
    上报监督(rid, shop, pack, body, 版, trace)
    _记(me.get("no"), rid, "REPORT_SAVE", True, f"{pack['报告']} 第 {版} 版", {"kind": pack["种类"], "start": 起})
    return dict(ok=True, 报告号=rid, 第几版=版, 状态="草稿", 报告=pack["报告"], 门店=shop,
                **({"替代": 上一版已确认[0]} if 上一版已确认 else {}),
                能不能确认=pack.get("能不能确认"), 必选缺了的=pack.get("必选缺了的"), 链接=链接(rid), 下载=下载(rid),
                note="存的是草稿,数字冻结在保存这一刻。**确认要店长明说**,不要替他点。")


def 确认(me, report_id, db=None):
    c = sqlite3.connect(db or DB)
    try:
        建表(c)
        r = c.execute("SELECT id,shop,kind,period_start,revision,status,pack FROM store_report_doc WHERE id=?",
                      (report_id,)).fetchone()
        if not r or not _能管(me, r[1]):
            return dict(ok=False, code="NOT_FOUND", reason=f"没有 {report_id} 这份报告,或者它不在你的范围里")
        if r[5] == "已确认":
            return dict(ok=False, code="ALREADY", reason=f"{report_id} 已经确认过了;要改就再存一版")
        最新 = c.execute("SELECT MAX(revision) FROM store_report_doc WHERE shop=? AND kind=? AND period_start=?",
                        (r[1], r[2], r[3])).fetchone()[0]
        if r[4] != 最新:
            return dict(ok=False, code="NOT_LATEST",
                        reason=f"{report_id} 是第 {r[4]} 版,这一期最新的是第 {最新} 版 —— 确认最新那一版")
        pack = json.loads(r[6])
        打回 = c.execute("SELECT rejected_at, reject_reason FROM store_report_doc WHERE id=?", (report_id,)).fetchone()
        if 打回 and 打回[0]:
            return dict(ok=False, code="REJECTED",
                        reason=f"这一版被 AI 管理平台打回了(理由:{打回[1]})—— 打回的版本不许确认;"
                               "请重新生成、给店长看过再存一版")
        if not pack.get("能不能确认"):
            return dict(ok=False, code="MISSING_REQUIRED",
                        reason=f"必选指标缺了:{pack.get('必选缺了的')} —— 缺了不许确认(用户 10-09 定:下单数和营收必选)")
        c.execute("UPDATE store_report_doc SET status='已确认', confirmed_at=?, confirmed_by=? WHERE id=?",
                  (_今天(), me.get("no"), report_id))
        c.commit()
    finally:
        c.close()
    _记(me.get("no"), report_id, "REPORT_CONFIRM", True, "确认", {})
    return dict(ok=True, 报告号=report_id, 状态="已确认", 链接=链接(report_id), 下载=下载(report_id),
                note="确认后不能改;要改就再存一版,这一版留作历史。**不自动发送给任何人**(用户 10-10 定:只保存)。")


def 列(me, kind=None, limit=20, db=None):
    if me.get("role") not in 管理角色:
        return dict(error="经营报告只给店长 / 总部看")
    c = sqlite3.connect(db or DB); c.row_factory = sqlite3.Row
    try:
        建表(c)
        where, args = ["1=1"], []
        if me.get("role") != "总部运营":
            where.append("shop=?"); args.append(me.get("shop"))
        if kind:
            where.append("kind=?"); args.append(kind)
        # 每一期只列最新那一版(历史版本数一起给)
        sql = ("SELECT d.id,d.shop,d.kind,d.period_start,d.period_end,d.revision,d.status,d.created_at,d.confirmed_at, "
               "d.rejected_at,d.reject_reason, "
               "(SELECT COUNT(*) FROM store_report_doc x WHERE x.shop=d.shop AND x.kind=d.kind "
               "AND x.period_start=d.period_start) 版本数 FROM store_report_doc d WHERE " + " AND ".join(where) +
               " AND d.revision=(SELECT MAX(revision) FROM store_report_doc y WHERE y.shop=d.shop AND y.kind=d.kind "
               "AND y.period_start=d.period_start)")
        rs = [dict(r) for r in c.execute(sql + " ORDER BY d.period_start DESC, d.kind", args)]
    finally:
        c.close()
    for r in rs:
        r["链接"], r["下载"] = 链接(r["id"]), 下载(r["id"])
    lim = max(1, min(int(limit or 20), 100))
    return {"份数": len(rs), "列出": min(len(rs), lim), "报告": rs[:lim], "全部报告": 全部报告,
            **({"截断": f"一共 {len(rs)} 份,只列了 {lim} 份"} if len(rs) > lim else {})}


# ── 产出监督(用户 10-10:AI 管理平台「能看 + 能打回」)──────────────────────
def 上报监督(rid, shop, pack, body, 版, trace):
    """存下一版就推一份给管理后台:输入 = 冻结的取数包,规矩 = 管写报告和存报告的那两条,输出 = 正文。
    **不抛**(A2:上报出任何事都不许影响业务)。"""
    try:
        import sys as _s
        _s.path.insert(0, os.path.join(os.path.dirname(HERE), "agent"))
        _s.path.insert(0, os.path.dirname(HERE))
        import artifact_report as AR, prompts as _p
        规 = [dict(编号=r.id, 正文=r.text.strip()) for _, r in _p.all_rules(unique=True) if r.id in ("TL67", "TL68")]
        AR.排队(外部id=f"报告:{rid}", 类型="报告", 版本=版, 标题=f"{shop} · {pack.get('种类', '')}报 · {str(pack.get('区间', ''))[:23]}",
               输入=pack, 输出=body, 规则=规, 门店=shop, 世界日期=_今天(), 生成方式="对话", 外部trace=trace)
    except Exception:
        pass


def 打回(report_id, 谁, 理由, db=None):
    """执行 AI 管理平台拉回来的打回:**只标记,不改正文、不删** —— 打回的那一版留作历史,
    确认被拦住,店长那边看得到理由,要重新生成再存一版。返回 (ok, 说明)。"""
    c = sqlite3.connect(db or DB)
    try:
        建表(c)
        r = c.execute("SELECT id, rejected_at FROM store_report_doc WHERE id=?", (report_id,)).fetchone()
        if not r:
            return False, f"没有 {report_id} 这份报告"
        if r[1]:
            return True, "这一版之前已经被打回过"
        c.execute("UPDATE store_report_doc SET rejected_at=?, rejected_by=?, reject_reason=? WHERE id=?",
                  (_今天(), 谁, 理由, report_id))
        c.commit()
    finally:
        c.close()
    _记(谁, report_id, "REPORT_REJECT", True, f"AI 管理平台打回:{理由}", {})
    return True, "已标记打回:这一版不许确认,店长那边显示理由"


def 取(me, report_id, db=None):
    c = sqlite3.connect(db or DB); c.row_factory = sqlite3.Row
    try:
        建表(c)
        r = c.execute("SELECT * FROM store_report_doc WHERE id=?", (report_id,)).fetchone()
    finally:
        c.close()
    if not r or not _能管(me, r["shop"]):
        return dict(error=f"没有 {report_id} 这份报告,或者它不在你的范围里")
    d = dict(r); d["pack"] = json.loads(d["pack"]); d["链接"], d["下载"] = 链接(report_id), 下载(report_id)
    return d
