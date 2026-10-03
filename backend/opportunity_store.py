# -*- coding: utf-8 -*-
"""商机对象的存取 —— 建表、从一次通话建商机、改状态、转方案。口径在 `knowledge/oppo_obj.py`。

`backend/opportunity.py` 只回答「这通电话里**有没有**商机」;判断成立之后,
商机要成为一个**有生命周期的对象**(intent `opportunity-and-call-notes` 判据 ①):
来源、预估(客户原话里的预算,可空 —— **不给成单概率**)、下一步、关闭原因、搁置等什么。

两张表:

    opportunity        一条商机。沟通发现的必须指回触发它的那次通话(call_id)
    opportunity_need   一条结构化诉求(维度 + 值),**必须带原话**(quote)和出自哪次通话

方案表加一列 `opportunity_id`:转方案时**两头都记**,和「转过单的方案必须指得回订单」同一个形状。
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
import oppo_obj as K

DDL = """
CREATE TABLE IF NOT EXISTS opportunity(
  id          TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  source      TEXT NOT NULL,          -- 沟通发现 / 历史诉求
  call_id     TEXT,                   -- 触发它的那次通话(call_audio.id);沟通发现的必填
  status      TEXT NOT NULL,          -- 见 oppo_obj.状态
  budget      TEXT,                   -- 客户原话里提到的预算,可空;**不给成单概率**
  next_step   TEXT,
  close_reason TEXT,                  -- 已关闭时:客户为什么不要
  wait_for    TEXT,                   -- 搁置等供给时:等什么,JSON {维度: 值}
  scheme_id   TEXT,                   -- 已转方案时:转成的方案
  advisor_no  TEXT,
  confirmed_by TEXT, confirmed_at TEXT,   -- 顾问点头(业务 D5:模型给判断,人点头才算)
  created     TEXT NOT NULL,
  updated     TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunity_need(
  opp_id  TEXT NOT NULL,
  dim     TEXT NOT NULL,              -- 见 oppo_obj.诉求维度
  val     TEXT NOT NULL,
  quote   TEXT NOT NULL,              -- 原话:逐字稿里客户说的那一句
  call_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunity_recall(
  opp_id      TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  spu         TEXT NOT NULL,          -- 哪件上新对上了
  matched     TEXT NOT NULL,          -- 对上了哪几条,JSON {维度: 值}
  quote       TEXT NOT NULL,          -- 凭什么:当初那句原话
  created     TEXT NOT NULL);         -- 提醒发出的时间(冷却按它算)
"""


def 建表(c):
    c.executescript(DDL)
    列 = {r[1] for r in c.execute("PRAGMA table_info(scheme)")}
    if 列 and "opportunity_id" not in 列:
        c.execute("ALTER TABLE scheme ADD COLUMN opportunity_id TEXT")


def 从通话建(c, call_id, 客户, 顾问, 诉求, 时间, 下一步=None, 预算=None):
    """诉求 = [(维度, 值, 原话)]。原话为空的诉求**不收** —— 指不回原话就不进库。返回商机号。"""
    oid = f"OP-{call_id}"
    c.execute("INSERT INTO opportunity(id, customer_id, source, call_id, status, budget, next_step,"
              " advisor_no, created, updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (oid, 客户, "沟通发现", call_id, K.起始状态, 预算, 下一步, 顾问, 时间, 时间))
    for 维, 值, 原 in 诉求:
        if 原:
            c.execute("INSERT INTO opportunity_need(opp_id, dim, val, quote, call_id) VALUES(?,?,?,?,?)",
                      (oid, 维, 值, 原, call_id))
    return oid


def 从转写建(c, audio_id):
    """一通录音转写完 → 规则层判一遍(免费、不调模型),是商机就建一条「待确认」挂到这通上。

    **只建「待确认」** —— 业务 D5:模型 / 规则给判断,顾问点头才算。规则层约三成是随口一提,
    那正是顾问点头这一步要拦的。说话人没分出来的不建(分不清哪句是客户说的)。
    返回商机号或 None。同一通重复调用不重复建。
    """
    import opportunity as J, oppo as KO
    r = c.execute("SELECT a.customer_id, t.text, t.speaker_src, a.created FROM call_audio a "
                  "JOIN call_transcript t ON t.audio_id=a.id WHERE a.id=?", (audio_id,)).fetchone()
    if not r or (r[2] or "").startswith("未分"):
        return None
    if c.execute("SELECT 1 FROM opportunity WHERE call_id=?", (audio_id,)).fetchone():
        return None
    是, 码, _ = J.判断(r[1], r[0])
    if not 是:
        return None
    行们 = KO.客户说的(r[1]).splitlines()
    诉求 = [(维, 词, K.原话(行们, 词)) for 词, 维, _ in J.命中维度(KO.客户说的(r[1]))]
    顾问 = (c.execute("SELECT advisor_no FROM customer WHERE id=?", (r[0],)).fetchone() or [None])[0]
    return 从通话建(c, audio_id, r[0], 顾问, 诉求, r[3], 下一步=f"按「{码}」去查店里有没有对得上的款")


def 改状态(c, oid, 到, 时间, 经手人=None, 关闭原因=None, 等什么=None, 方案=None):
    """按口径转状态。返回 (成没成, 一句人话)。**不合口径的不写**。"""
    r = c.execute("SELECT status FROM opportunity WHERE id=?", (oid,)).fetchone()
    if not r:
        return False, f"没有商机 {oid}"
    能, 话 = K.能转吗(r[0], 到)
    if not 能:
        return False, 话
    if 到 == "搁置等供给":
        能, 话 = K.搁置理由合格吗(等什么)
        if not 能:
            return False, 话
    if 到 == "已关闭" and not 关闭原因:
        return False, "关掉商机要写为什么(看了不喜欢 / 嫌贵 / 不需要)—— 不然和「当时没货」分不开"
    if 到 == "已转方案" and not 方案:
        return False, "转方案要指明是哪个方案"
    c.execute("UPDATE opportunity SET status=?, updated=?,"
              " close_reason=COALESCE(?, close_reason), wait_for=COALESCE(?, wait_for),"
              " scheme_id=COALESCE(?, scheme_id),"
              " confirmed_by=CASE WHEN ?='跟进中' AND confirmed_by IS NULL THEN ? ELSE confirmed_by END,"
              " confirmed_at=CASE WHEN ?='跟进中' AND confirmed_at IS NULL THEN ? ELSE confirmed_at END"
              " WHERE id=?",
              (到, 时间, 关闭原因, json.dumps(等什么, ensure_ascii=False) if 等什么 else None, 方案,
               到, 经手人, 到, 时间, oid))
    if 方案:
        c.execute("UPDATE scheme SET opportunity_id=? WHERE id=?", (oid, 方案))
    return True, f"{oid} → {到}"


# ── 回捞:搁置等供给 × 上新(四个闸在 oppo_obj,业务 2026-09-20 D6)──────────────
def 满足吗(c, spu, 维度, 值):
    """这件商品满不满足「维度 = 值」这条诉求。返回 (满不满足, 依据)。查法和判断器的「现在有货」同一套。"""
    if 维度 == "颜色":            # 同色系:色系按 color_family
        r = c.execute("SELECT s.color FROM sku s JOIN color_family f ON f.color=s.color "
                      "WHERE s.spu=? AND f.family=? LIMIT 1", (spu, 值)).fetchone()
        return bool(r), (f"有「{r[0]}」(属{值}色系)" if r else "")
    if 维度 == "形制":
        # pattern.xz 存的是形制编码(XZ09),名字在 craft 表 —— 直接 like 编码永远对不上(10-03 查出)
        r = c.execute("SELECT k.name FROM product p JOIN pattern t ON p.pattern=t.code JOIN craft k ON k.code=t.xz "
                      "WHERE p.spu=? AND (k.name LIKE ? OR k.alias LIKE ?)",
                      (spu, f"%{值}%", f"%{值}%")).fetchone() or c.execute(
                      "SELECT xz FROM product_custom WHERE spu=? AND xz LIKE ?", (spu, f"%{值}%")).fetchone()
        return bool(r), (f"形制「{r[0]}」" if r else "")
    if 维度 == "场合":
        # 场合词表是「婚礼婚服」「日常通勤」这种四字词,人说的是「婚礼」「日常」—— 包含就算
        r = c.execute("SELECT k.name FROM product_scene ps JOIN sys_code k ON k.code=ps.scene "
                      "WHERE ps.spu=? AND k.category='场合' AND (k.name=? OR instr(k.name, ?) > 0) LIMIT 1",
                      (spu, 值, 值)).fetchone()
        return bool(r), (f"挂着「{r[0]}」场合" if r else "")
    if 维度 == "配饰":            # 业务 D4:按分类命中 —— 配饰(C04)下哪个分类名出现在「值」里
        r = c.execute("SELECT k.name FROM product p JOIN category k ON k.code=p.category "
                      "WHERE p.spu=? AND p.category LIKE 'C04%' AND instr(?, k.name) > 0", (spu, 值)).fetchone()
        return bool(r), (f"属「{r[0]}」" if r else "")
    if 维度 == "版型":
        r = c.execute("SELECT t.code, t.name FROM product p JOIN pattern t ON p.pattern=t.code "
                      "WHERE p.spu=? AND (t.code=? OR t.name LIKE ?)", (spu, 值, f"%{值}%")).fetchone()
        return bool(r), (f"版型 {r[0]}「{r[1]}」" if r else "")
    # 面料 / 工艺 / 纹样 / 其余:按商品名粗算(和商机判断的「纹样有没有货」同一个粗法)
    r = c.execute("SELECT name FROM product WHERE spu=? AND name LIKE ?", (spu, f"%{值}%")).fetchone()
    return bool(r), (f"商品名里有「{值}」" if r else "")


def 对得上的在架(c, 维度, 值, n=5):
    """在架商品里哪几款满足「维度 = 值」—— 给研判时找下一步推什么。按商品号排,稳定。返回 [(spu, 名称, 依据)]。"""
    出 = []
    for spu, 名 in c.execute("SELECT spu, name FROM product WHERE status='上架' ORDER BY spu").fetchall():
        ok, 依 = 满足吗(c, spu, 维度, 值)
        if ok:
            出.append((spu, 名, 依))
            if len(出) >= n:
                break
    return 出


def 回捞(c, 新品们, 今天):
    """上新了这些商品 → 哪些搁置的商机该唤醒。返回 [提醒],并记进 opportunity_recall。

    四个闸:只捞「搁置等供给」(**已关闭一条都不碰**)· 诉求在 12 个月内 · 同一客户 90 天内只推一次 ·
    一次最多 50 条(按诉求从新到旧)。「等什么」里的每一条都要对上(全满足才算)。
    """
    import datetime as _dt
    d = lambda x: _dt.date.fromisoformat(str(x)[:10])
    候选 = c.execute("SELECT id, customer_id, wait_for, created FROM opportunity "
                     "WHERE status='搁置等供给' ORDER BY created DESC").fetchall()
    出, 本次客户 = [], set()
    for oid, cust, wf, created in 候选:
        if len(出) >= K.回捞_单次上限:
            break
        if not K.在时效内(d(created), 今天) or cust in 本次客户:
            continue
        上次 = c.execute("SELECT MAX(created) FROM opportunity_recall WHERE customer_id=?", (cust,)).fetchone()[0]
        if K.冷却中(d(上次) if 上次 else None, 今天):
            continue
        等 = json.loads(wf or "{}")
        for spu in 新品们:
            结果 = [满足吗(c, spu, k, v) for k, v in 等.items()]
            if 等 and all(ok for ok, _ in 结果):
                原 = c.execute("SELECT quote FROM opportunity_need WHERE opp_id=? AND dim=? AND val=? LIMIT 1",
                               (oid, *next(iter(等.items())))).fetchone()
                if not 原:
                    break            # 指不回原话的诉求不许进回捞池
                c.execute("INSERT INTO opportunity_recall(opp_id, customer_id, spu, matched, quote, created) "
                          "VALUES(?,?,?,?,?,?)", (oid, cust, spu, json.dumps(等, ensure_ascii=False), 原[0],
                                                   今天.isoformat()))
                出.append(dict(商机=oid, 客户=cust, 新品=spu, 对上了=等, 原话=原[0],
                              依据="；".join(y for _, y in 结果)))
                本次客户.add(cust)
                break
    return 出
