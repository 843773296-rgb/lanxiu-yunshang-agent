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
-- 哪条待办任务是哪条商机的哪一种提醒(回捞 / 满足确认 / 偏好回捞)。
-- 不靠解析任务描述认 —— 描述是给人看的,改一个字就认不出来了
CREATE TABLE IF NOT EXISTS opportunity_task(
  schedule_id TEXT PRIMARY KEY,            -- schedule.id
  opp_id  TEXT NOT NULL,
  kind    TEXT NOT NULL,
  detail  TEXT,                        -- JSON:对上了什么 / 哪张单哪一件 / 哪几条偏好
  created TEXT NOT NULL,
  answer  TEXT, answered_by TEXT, answered_at TEXT);
-- 客户偏好(业务 一·7:买了蓝色算满足想要红色,**同时把红色加进客户偏好**)。
-- **只有顾问在「满足确认」里点了「满足了」才写**,每条带当初那句原话;上新时还能再推一遍。
-- 客户说不要了 → 作废(留着行、写清谁作废的为什么),不删
CREATE TABLE IF NOT EXISTS customer_pref(
  id INTEGER PRIMARY KEY,
  customer_id TEXT NOT NULL,
  dim TEXT NOT NULL, val TEXT NOT NULL,
  quote TEXT NOT NULL,                 -- 当初那句原话
  opp_id TEXT NOT NULL,                -- 从哪条商机来的
  call_id TEXT NOT NULL,
  confirmed_by TEXT NOT NULL,          -- 哪个顾问点的头
  created TEXT NOT NULL,
  retired_at TEXT, retired_by TEXT, retired_reason TEXT);
-- 购买偏好回捞(用户 2026-10-10:「只买红的 → 上新红色就是商机」,方案 B)。
-- **不和 opportunity_recall 混一张表**:那张表的每一行都指得回客户在电话里说的原话、商机都是「搁置等供给」,
-- 好几条检查按这个读;推断出来的偏好没有原话,混进去就得放宽那几条检查。冷却和上限两张表**合着算**
CREATE TABLE IF NOT EXISTS buy_pref_recall(
  opp_id      TEXT NOT NULL,          -- 推出来就开一条「待确认」商机(来源 购买偏好),顾问点头才算
  customer_id TEXT NOT NULL,
  spu         TEXT NOT NULL,
  matched     TEXT NOT NULL,          -- {"颜色": 色系}
  basis       TEXT NOT NULL,          -- 依据:近 24 个月买过几件、几件是这个色系、和店里一般客人比
  ratio       REAL NOT NULL,          -- 倍数(她的比例 ÷ 全店比例)
  created     TEXT NOT NULL);
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
              # 「等什么」只属于「搁置等供给」:离开这个状态就清掉(10-10 数据工厂抓到:搁置 → 已关闭
              # 时 wait_for 还挂着,于是一条已关闭的商机看起来还在等货 —— 以前红不了,因为没有从搁置关掉的数据)
              " close_reason=COALESCE(?, close_reason),"
              " wait_for=CASE WHEN ?='搁置等供给' THEN COALESCE(?, wait_for) ELSE NULL END,"
              " scheme_id=COALESCE(?, scheme_id),"
              " confirmed_by=CASE WHEN ?='跟进中' AND confirmed_by IS NULL THEN ? ELSE confirmed_by END,"
              " confirmed_at=CASE WHEN ?='跟进中' AND confirmed_at IS NULL THEN ? ELSE confirmed_at END"
              " WHERE id=?",
              (到, 时间, 关闭原因, 到, json.dumps(等什么, ensure_ascii=False) if 等什么 else None, 方案,
               到, 经手人, 到, 时间, oid))
    if 方案:
        c.execute("UPDATE scheme SET opportunity_id=? WHERE id=?", (oid, 方案))
    return True, f"{oid} → {到}"


# ── 商机提醒任务(用户 2026-10-03 定:进顾问的待办,和店长派的活在同一个清单)──────────
def _派提醒(c, oid, kind, note, 今天, detail=None):
    """给这条商机的归属顾问派一条「商机提醒」。**同一条商机同一种提醒,没做完不重复派**。
    归属顾问不在职 → 不指派(进待分配池,店长看得到),不猜一个人。返回任务号或 None。"""
    import datetime as _dt
    if c.execute("SELECT 1 FROM opportunity_task ot JOIN schedule s ON s.id=ot.schedule_id "
                 "WHERE ot.opp_id=? AND ot.kind=? AND s.status='有效'", (oid, kind)).fetchone():
        return None
    r = c.execute("SELECT o.customer_id, cu.shop, cu.advisor_no FROM opportunity o JOIN customer cu ON cu.id=o.customer_id "
                  "WHERE o.id=?", (oid,)).fetchone()
    if not r:
        return None
    cid, shop, adv = r
    在职 = adv and c.execute("SELECT 1 FROM staff WHERE no=? AND status='启用'", (adv,)).fetchone()
    n = c.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
    sid = f"SC{7000 + n + 1}"
    while c.execute("SELECT 1 FROM schedule WHERE id=?", (sid,)).fetchone():
        n += 1; sid = f"SC{7000 + n + 1}"
    止 = 今天 + _dt.timedelta(days=K.提醒期限天)
    c.execute("INSERT INTO schedule(id, type, advisor_no, customer_id, start_ts, end_ts, status, shop, "
              "assignee_no, assigned_by, assigned_at, note, ref_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (sid, "商机提醒", adv if 在职 else None, cid, f"{今天} 09:00", f"{止} 18:00", "有效", shop,
               adv if 在职 else None, "SYS" if 在职 else None, f"{今天} 09:00" if 在职 else None, note, cid))
    c.execute("INSERT INTO opportunity_task(schedule_id, opp_id, kind, detail, created) VALUES(?,?,?,?,?)",
              (sid, oid, kind, json.dumps(detail or {}, ensure_ascii=False), str(今天)))
    return sid


def 可选结论(c, schedule_id):
    """这条任务完成时能选哪几个结论。不是商机提醒 → None。"""
    r = c.execute("SELECT kind FROM opportunity_task WHERE schedule_id=?", (schedule_id,)).fetchone()
    return list(K.提醒结论[r[0]]) if r else None


def 满足扫描(c, 今天):
    """跟进中 / 搁置的商机,客户之后下的单里有一件「认得出是这件事」的 → 派「满足确认」给顾问。
    **只提示,不改状态**(规则判 + 顾问点头)。同一张单只问一次。返回派出去的任务号。"""
    出 = []
    for oid, cid, created in c.execute("SELECT id, customer_id, created FROM opportunity "
                                       "WHERE status IN ('跟进中','搁置等供给') ORDER BY id").fetchall():
        诉求 = c.execute("SELECT dim, val, quote FROM opportunity_need WHERE opp_id=?", (oid,)).fetchall()
        if not 诉求:
            continue
        问过 = {json.loads(d or "{}").get("订单") for (d,) in c.execute(
            "SELECT detail FROM opportunity_task WHERE opp_id=? AND kind='满足确认'", (oid,))}
        认件 = [(d, v) for d, v, _ in 诉求 if d in K.认件维度]
        for oid_r, spu, sku in c.execute(
                "SELECT r.id, i.spu, i.sku FROM ordr r JOIN ordr_item i ON i.order_id=r.id "
                "WHERE r.customer_id=? AND r.created>=? AND r.status NOT IN ('取消','待付款') "
                "ORDER BY r.created, i.id", (cid, created)).fetchall():
            if oid_r in 问过:
                continue
            if 认件:
                中 = any(满足吗(c, spu, d, v)[0] for d, v in 认件)
            else:
                cat = (c.execute("SELECT category FROM product WHERE spu=?", (spu,)).fetchone() or [""])[0] or ""
                中 = cat[:3] in K.成衣品类
            if not 中:
                continue
            对上, 没对上 = [], []
            for d, v, q in 诉求:
                if d == "颜色":      # 颜色看**买的那一件**的颜色,不看这款有没有别的颜色
                    ok = bool(sku and c.execute("SELECT 1 FROM sku s JOIN color_family f ON f.color=s.color "
                                                "WHERE s.code=? AND f.family=?", (sku, v)).fetchone())
                else:
                    ok = 满足吗(c, spu, d, v)[0]
                (对上 if ok else 没对上).append({"维度": d, "值": v})
            名 = (c.execute("SELECT name FROM product WHERE spu=?", (spu,)).fetchone() or [spu])[0]
            note = (f"客户 {cid} 下单买了「{名}」—— 当初的商机{'对上了 ' + '、'.join(x['值'] for x in 对上) if 对上 else ''}"
                    f"{(';没对上 ' + '、'.join(x['值'] for x in 没对上)) if 没对上 else ''}。"
                    f"这条商机算满足了吗?选「满足了」会把没对上的记进客户偏好,上新时再推")
            t = _派提醒(c, oid, "满足确认", note, 今天,
                        dict(订单=oid_r, 商品=spu, sku=sku, 对上=对上, 没对上=没对上))
            if t:
                出.append(t)
            break          # 一条商机一次只问一张单
    return 出


def 按结论处理(c, schedule_id, 结论, 经手人, 总结, 时间):
    """顾问完成「商机提醒」时选的结论 → 商机怎么走。返回 (成没成, 一句人话)。**结论不在那一种提醒的清单里就不动**。"""
    r = c.execute("SELECT opp_id, kind, detail FROM opportunity_task WHERE schedule_id=?", (schedule_id,)).fetchone()
    if not r:
        return False, f"{schedule_id} 不是商机提醒"
    oid, kind, detail = r
    表 = K.提醒结论[kind]
    if 结论 not in 表:
        return False, f"「{kind}」要选一个结论:{' / '.join(表)}"
    去 = 表[结论]
    d = json.loads(detail or "{}")
    话 = f"{oid}:{结论}"
    if 去 in ("跟进中", "已关闭", "已成交"):
        cur = c.execute("SELECT status FROM opportunity WHERE id=?", (oid,)).fetchone()[0]
        if not (去 == "跟进中" and cur == "跟进中"):
            ok, 话 = 改状态(c, oid, 去, 时间, 经手人=经手人,
                           关闭原因=(f"顾问回访:{总结}" if 去 == "已关闭" else None))
            if not ok:
                return False, 话
        if 去 == "已成交":
            n = 0
            for x in d.get("没对上") or []:
                q = c.execute("SELECT quote, call_id FROM opportunity_need WHERE opp_id=? AND dim=? AND val=? LIMIT 1",
                              (oid, x["维度"], x["值"])).fetchone()
                if q:          # 指不回原话的不进偏好
                    c.execute("INSERT INTO customer_pref(customer_id, dim, val, quote, opp_id, call_id, confirmed_by, created)"
                              " SELECT customer_id, ?, ?, ?, ?, ?, ?, ? FROM opportunity WHERE id=?",
                              (x["维度"], x["值"], q[0], oid, q[1], 经手人, str(时间)[:10], oid))
                    n += 1
            话 += f";{n} 条没对上的诉求记进了客户偏好" if n else ""
    elif 去 == "新开":
        prefs = c.execute("SELECT id, customer_id, dim, val, quote, call_id FROM customer_pref WHERE id IN (%s)"
                          % ",".join("?" * len(d.get("偏好") or [0])), tuple(d.get("偏好") or [0])).fetchall()
        if not prefs:
            return False, "这条提醒指的偏好已经不在了"
        新 = f"OP-P{prefs[0][0]}-{str(时间)[:10].replace('-', '')}"
        c.execute("INSERT INTO opportunity(id, customer_id, source, call_id, status, next_step, advisor_no, "
                  "confirmed_by, confirmed_at, created, updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (新, prefs[0][1], "历史诉求", prefs[0][5], "跟进中", f"上新 {d.get('新品')} 对上了客户偏好",
                   经手人, 经手人, 时间, 时间, 时间))
        for _, _, dim, val, quote, call in prefs:
            c.execute("INSERT INTO opportunity_need(opp_id, dim, val, quote, call_id) VALUES(?,?,?,?,?)",
                      (新, dim, val, quote, call))
        话 = f"按客户偏好新开商机 {新}(跟进中)"
    elif 去 == "偏好作废":
        c.execute("UPDATE customer_pref SET retired_at=?, retired_by=?, retired_reason=? WHERE id IN (%s)"
                  % ",".join("?" * len(d.get("偏好") or [0])),
                  (str(时间)[:10], 经手人, 总结, *(d.get("偏好") or [0])))
        话 = "客户说不要了 —— 这几条偏好作废,以后上新不再推"
    c.execute("UPDATE opportunity_task SET answer=?, answered_by=?, answered_at=? WHERE schedule_id=?",
              (结论, 经手人, str(时间), schedule_id))
    return True, 话


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


def _上次推送(c, cust):
    """冷却按「这位客户上一次被推是哪天」算 —— **两种回捞合着算**:电话里说过的和购买推断的,
    同一个人 90 天内只被推一次,不因为来源不同就推两遍。"""
    a = c.execute("SELECT MAX(created) FROM opportunity_recall WHERE customer_id=?", (cust,)).fetchone()[0]
    b = c.execute("SELECT MAX(created) FROM buy_pref_recall WHERE customer_id=?", (cust,)).fetchone()[0] \
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='buy_pref_recall'").fetchone() else None
    return max([x for x in (a, b) if x] or [None])


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
        上次 = _上次推送(c, cust)
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
                名 = (c.execute("SELECT name FROM product WHERE spu=?", (spu,)).fetchone() or [spu])[0]
                _派提醒(c, oid, "回捞",
                       f"上新「{名}」({spu})对上了客户等的「{'、'.join(f'{k}={v}' for k, v in 等.items())}」—— "
                       f"当初原话:「{原[0]}」。联系她看看,做完选结论", 今天,
                       dict(新品=spu, 对上=等, 原话=原[0]))
                break
    # ── 偏好回捞:成交过、没对上的那几条(业务 一·7「可以把买过的客户再推一遍」)── 同样四个闸
    for cust, oid, ids, dims, created in c.execute(
            "SELECT customer_id, opp_id, group_concat(id), group_concat(dim || '=' || val, '|'), MIN(created) "
            "FROM customer_pref WHERE retired_at IS NULL GROUP BY customer_id, opp_id ORDER BY MIN(created) DESC").fetchall():
        if len(出) >= K.回捞_单次上限:
            break
        if not K.在时效内(d(created), 今天) or cust in 本次客户:
            continue
        上次 = _上次推送(c, cust)
        if K.冷却中(d(上次) if 上次 else None, 今天):
            continue
        等 = dict(x.split("=", 1) for x in dims.split("|"))
        for spu in 新品们:
            if all(满足吗(c, spu, k, v)[0] for k, v in 等.items()):
                原 = c.execute("SELECT quote FROM customer_pref WHERE id=?", (int(ids.split(",")[0]),)).fetchone()[0]
                c.execute("INSERT INTO opportunity_recall(opp_id, customer_id, spu, matched, quote, created) "
                          "VALUES(?,?,?,?,?,?)", (oid, cust, spu, json.dumps(等, ensure_ascii=False), 原, 今天.isoformat()))
                出.append(dict(商机=oid, 客户=cust, 新品=spu, 对上了=等, 原话=原, 依据="客户偏好(成交过、当时没对上)"))
                本次客户.add(cust)
                名 = (c.execute("SELECT name FROM product WHERE spu=?", (spu,)).fetchone() or [spu])[0]
                _派提醒(c, oid, "偏好回捞",
                       f"上新「{名}」({spu})对上了客户的偏好「{'、'.join(f'{k}={v}' for k, v in 等.items())}」"
                       f"(她买过,但当时没买到这个)—— 原话:「{原}」", 今天,
                       dict(新品=spu, 对上=等, 原话=原, 偏好=[int(x) for x in ids.split(",")]))
                break
    # ── 购买偏好回捞(用户 10-10,方案 B):**排在最后** —— 名额先给电话里亲口说过的 ──
    if len(出) < K.回捞_单次上限:
        出 += 购买偏好回捞(c, 新品们, 今天, 本次客户, min(K.购买推断_单次上限, K.回捞_单次上限 - len(出)))
    return 出


def 购买偏好回捞(c, 新品们, 今天, 已推=None, 名额=None):
    """上新了这几款 → 从购买记录归纳出喜好、对得上新款的客户(用户 10-10)。

    喜好 = 把她近 24 个月买过的衣服交给**商品归纳**(knowledge/traits.py)得出的「规律」——
    颜色、纹样、面料、工艺、形制都算,判法是方案 B(比全店买过的东西明显多)。新款对上她任意一条规律就推。
    每推一位:开一条「待确认」商机(来源 购买偏好)、记 buy_pref_recall、给归属顾问派「购买偏好回捞」提醒。
    **推断不直接算商机** —— 顾问联系后点「客户想看」才转跟进中(和「模型给判断,人点头才算」同一条规矩)。
    闸:和回捞共用 90 天冷却、单次 50 条;**不同意营销触达 / 注销中 / 已注销的不推**(没有账户的也不推:查不到同意)。
    """
    import purchase_pref as P, traits as T, product_summary as PS
    c.executescript(DDL)
    名额 = K.购买推断_单次上限 if 名额 is None else min(名额, K.购买推断_单次上限)
    已推 = set(已推 or ())
    if 名额 <= 0 or not 新品们:
        return []
    起, 止 = P.窗口起点(今天).isoformat(), 今天.isoformat()
    表 = PS.属性表(c)
    新属 = {spu: {d: [v for v, _ in 表[spu]["属性"][d]] for d in T.维度们} for spu in 新品们 if spu in 表}
    if not 新属:
        return []
    对照 = PS.全店买过的占比(c, 起, 止, 表)
    色系 = dict(c.execute("SELECT color, family FROM color_family"))
    每人 = {}
    for cust, spu, col, iid in c.execute(
            "SELECT o.customer_id, i.spu, s.color, i.id FROM ordr o JOIN ordr_item i ON i.order_id=o.id "
            "LEFT JOIN sku s ON s.code=i.sku WHERE o.customer_id IS NOT NULL AND substr(o.created,1,10) BETWEEN ? AND ? "
            "AND o.status NOT IN ('取消','已取消','待付款')", (起, 止)):
        if spu in 表:
            # 她买的那一件:颜色按 SKU,定制品按下单时真选的料 / 工艺 / 颜色(和商品归纳同一个函数,不另写一套)
            每人.setdefault(cust, []).append(PS.买的那件(c, 表, 色系, iid, spu, col))
    候选 = []
    for cust, 件们 in 每人.items():
        if cust in 已推 or len(件们) < T.最少件数:
            continue
        规 = T.归纳(件们, 对照)["规律"]
        if not 规:
            continue
        for spu, 属 in 新属.items():
            中 = P.对上的规律(规, 属)
            if 中:
                候选.append((中[0]["件数"], 中[0]["倍数"], cust, spu, 中))
                break                       # 一个人一次上新只推一款
    # 名额不够时谁先:**证据多的先**(对上那条规律的件数),同样多再看倍数 ——
    # 只按倍数排的话,只买过 3 件、碰巧 2 件棉麻的人(20 倍)会排在买了 9 件、6 件红的老客前面
    候选.sort(key=lambda t: (-t[0], -t[1], t[2]))
    出 = []
    for _, _, cust, spu, 中 in 候选:
        if len(出) >= 名额:
            break
        能 = c.execute("SELECT a.status, a.marketing_consent FROM customer cu JOIN account a ON a.id=cu.account_id "
                       "WHERE cu.id=?", (cust,)).fetchone()
        if not 能 or 能[0] in ("注销中", "已注销") or not 能[1]:
            continue
        上次 = _上次推送(c, cust)
        if K.冷却中(_dt_日(上次) if 上次 else None, 今天):
            continue
        oid = f"OP-B{cust}-{今天.strftime('%Y%m%d')}"
        if c.execute("SELECT 1 FROM opportunity WHERE id=?", (oid,)).fetchone():
            continue
        依据 = ";".join(T.一句话(x) for x in 中) + f"(近 {P.回看月数} 个月她买过的东西,和全店买过的比)"
        对上 = {}
        for x in 中:
            对上.setdefault(x["维度"], x["值"])
        时间 = 今天.isoformat()
        adv = c.execute("SELECT advisor_no FROM customer WHERE id=?", (cust,)).fetchone()
        c.execute("INSERT INTO opportunity(id, customer_id, source, status, next_step, advisor_no, created, updated) "
                  "VALUES(?,?,?,?,?,?,?,?)", (oid, cust, "购买偏好", K.起始状态,
                                              "上新对上了她的购买规律(" + "、".join(f"{k}{v}" for k, v in 对上.items())
                                              + ")—— 联系确认", adv[0] if adv else None, 时间, 时间))
        c.execute("INSERT INTO buy_pref_recall(opp_id, customer_id, spu, matched, basis, ratio, created) VALUES(?,?,?,?,?,?,?)",
                  (oid, cust, spu, json.dumps(对上, ensure_ascii=False), 依据, 中[0]["倍数"], 时间))
        名 = (c.execute("SELECT name FROM product WHERE spu=?", (spu,)).fetchone() or [spu])[0]
        _派提醒(c, oid, "购买偏好回捞",
               f"上新「{名}」({spu})对上了她的购买规律 —— {依据}。这是按购买记录归纳的,不是她说过的;"
               f"联系问问她要不要看,做完选结论", 今天, dict(新品=spu, 对上=对上, 依据=依据, 倍数=中[0]["倍数"]))
        出.append(dict(商机=oid, 客户=cust, 新品=spu, 对上了=对上, 原话=依据, 依据="购买记录归纳(方案 B)"))
    return 出


def _dt_日(x):
    import datetime as _dt
    return _dt.date.fromisoformat(str(x)[:10])


def 推断提醒收口(c, 今天):
    """**购买推断**派出去的提醒,过了期限没人答 → 自动收口(用户 2026-10-10 定):
    提醒取消(写明原因,不算逾期)、那条「待确认」商机关掉(写明「推断的提醒没人答」)。
    **只管机器推断的**:客户亲口说过的那两种提醒不动 —— 那是她要的东西,没人答就该一直挂着逾期让店长看见。
    谁来调:每天跑一次(每日上新那一步,数据工厂接)。返回收掉的任务号。"""
    出 = []
    for sid, oid in c.execute(
            "SELECT s.id, t.opp_id FROM opportunity_task t JOIN schedule s ON s.id=t.schedule_id "
            "WHERE t.kind='购买偏好回捞' AND t.answer IS NULL AND s.status='有效' AND substr(s.end_ts,1,10) < ?",
            (今天.isoformat(),)).fetchall():
        c.execute("UPDATE schedule SET status='取消', cancel_reason=? WHERE id=?",
                  ("按购买记录推断的提醒,过了期限没人答 —— 自动收口(用户 10-10 定),不算逾期", sid))
        c.execute("UPDATE opportunity_task SET answer=?, answered_by=?, answered_at=? WHERE schedule_id=?",
                  ("自动收口", "SYS", 今天.isoformat(), sid))
        st = c.execute("SELECT status FROM opportunity WHERE id=?", (oid,)).fetchone()
        if st and st[0] == K.起始状态:
            改状态(c, oid, "已关闭", 今天.isoformat(), 经手人="SYS",
                   关闭原因="按购买记录推断的商机,提醒过期没人答 —— 自动收口(不是客户说不要)")
        出.append(sid)
    return 出
