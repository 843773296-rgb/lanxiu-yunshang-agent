#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上新待办卡片(用户 2026-10-10)。

    导购每次登录 chat,如果**上新 30 天内**的新款和他名下的商机绑上了,直接弹待办卡片:
    关联顾客(姓名、电话、地址、留言)、agent 建议、上新服装信息。

「绑上」不是这里新造的:上新 → `opportunity_store.回捞` 已经会把「搁置等供给」的商机和新款对上、
记进 opportunity_recall、给归属顾问派一条「商机提醒」任务。**这里只做三件事**:

    补建议   绑定那一刻让 agent 写一次建议、存下来(用户定:不在每次登录时现写 —— 不花钱、不每次变)
    卡片     列出这个人该看的卡片
    看完整   电话 / 地址卡片上先打码,点一下才给全号 —— **每点一次记一笔台账**(用户定)

用户另定的两条:
- 「月内上新」= 每一款从**上新那天**起算 30 天(`oppo_obj.上新卡片天`)
- 卡片**暂时不消失**(面试要展示):顾问记了联系结果也照弹;页面上能手动关,下次登录再弹。
  所以卡片里带着任务状态,但**不按状态过滤**。
"""
import datetime as dt, json, os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
import oppo_obj as K

DB = os.path.join(HERE, "lanxiu.db")
本库 = DB      # 只有这个库上写的建议才推给 AI 管理平台(见 artifact_report.是本库)

DDL = """
CREATE TABLE IF NOT EXISTS recall_advice(
  opp_id  TEXT NOT NULL,
  spu     TEXT NOT NULL,
  text    TEXT NOT NULL,           -- 给导购的建议(怎么开口、推哪个色 / 码、要注意什么)
  source  TEXT NOT NULL,           -- 模型 / 规则(模型没跑通时退回规则模板,**照实标**)
  model   TEXT,
  created TEXT NOT NULL,
  PRIMARY KEY(opp_id, spu));
-- 被 AI 管理平台打回的旧版(10-10 产出监督):**挪到这里留着,不删** —— 打回的那一版连同理由
-- 是最有价值的评测样本(人说「这样写不行」),删了就没了
CREATE TABLE IF NOT EXISTS recall_advice_log(
  opp_id TEXT NOT NULL, spu TEXT NOT NULL, version INTEGER NOT NULL,
  text TEXT NOT NULL, source TEXT NOT NULL, model TEXT, created TEXT NOT NULL,
  input TEXT, trace_id TEXT,
  rejected_at TEXT NOT NULL, rejected_by TEXT NOT NULL, reject_reason TEXT NOT NULL);
"""
后加列 = [("version", "INTEGER NOT NULL DEFAULT 1"),   # 第几版(打回重写一次 +1)
         ("input", "TEXT"),                          # 发给模型的材料(监督要看「它是照什么写的」)
         ("trace_id", "TEXT")]                       # 这一次模型调用的号 —— 记录仪和 A1 上报的「外部trace」

回捞类 = ("回捞", "偏好回捞", "购买偏好回捞")
# 两种绑定合成一个来源:电话里说过的(opportunity_recall,quote = 原话)和购买记录推断的
# (buy_pref_recall,用户 10-10,basis = 依据)。卡片、建议、日历都从这里读,**不各写一遍 UNION**
_绑定 = ("(SELECT opp_id, customer_id, spu, matched, quote, created, '说过的' 来源 FROM opportunity_recall "
        "UNION ALL SELECT opp_id, customer_id, spu, matched, basis, created, '购买推断' FROM buy_pref_recall)")


def 建表(c):
    import opportunity_store as _S
    _S.建表(c)            # buy_pref_recall 在那边建 —— 老库里还没有它时,卡片的 UNION 也不能炸
    c.executescript(DDL)
    有 = {r[1] for r in c.execute("PRAGMA table_info(recall_advice)")}
    for 列, 型 in 后加列:
        if 列 not in 有:
            c.execute(f"ALTER TABLE recall_advice ADD COLUMN {列} {型}")


def _今天():
    import worldclock
    return worldclock.今天()


# ── 打码:卡片上先给打码的,点「看完整」才给全的 ──────────────────────────
def 打码电话(p):
    p = (p or "").strip()
    return f"{p[:3]}****{p[-4:]}" if len(p) >= 7 else "—"


def 打码地址(a):
    """省市区和路名留着(导购要知道人在哪个城市、离哪家店近),**门牌号、楼栋、室号**里的数字打掉。"""
    return re.sub(r"\d+", "**", a) if a else "—"


# ── 建议:绑定那一刻写一次 ───────────────────────────────────────────────
建议提示 = """你是汉服定制店的资深导购主管,给一位导购写**联系老客户的建议**。
背景:这位客户之前想要的东西店里当时没有(或没买到),或者她一直偏爱某个颜色,现在上新了一款对得上的。
写 3 条,每条一句,总共不超过 150 字:
1. 怎么开口 —— 材料里有「当初原话」就提她说过的话,让她知道你记得;
   材料里是「购买记录」就**只说她以前常买这个色系**,绝不能说「您说过 / 您提过」(她没说过,说了就是编);
2. 推这一款的哪个颜色 / 尺码 —— **卖点只能用商品名称里出现的词**;面料成分、工艺细节、版型结构、价格、库存、
   优惠、工期,材料里没给的一个字都不要写(说错一个,导购照着说出去就是对客户说假话);
3. 一个要注意的点:客户备注**和这款有关**才提(比如备注说对某种面料敏感、而这款名称里就有这种面料);
   无关就写「先问她现在还需不需要、给谁穿」,不要把备注硬扯到这款上。
只输出这 3 条,不要标题、不要客套。
(10-10 第一版提示词实测:模型给马面裙编了「云肩」、给披帛编了「100% 真丝」、把「对香云纱敏感」扯到妆花褙子上 ——
 三条都是材料里没有的东西,所以这里写死「材料外的一个字都不写」。)"""


def _商品(c, spu):
    r = c.execute("SELECT spu, name, kind, base_price, tag_price, on_shelf_at, img_main, status FROM product WHERE spu=?",
                  (spu,)).fetchone()
    if not r:
        return None
    色 = [x[0] for x in c.execute("SELECT DISTINCT color FROM sku WHERE spu=? AND color IS NOT NULL ORDER BY code", (spu,))]
    码 = [x[0] for x in c.execute("SELECT DISTINCT size FROM sku WHERE spu=? AND size IS NOT NULL ORDER BY code", (spu,))]
    价 = c.execute("SELECT MIN(price), MAX(price), SUM(stock - COALESCE(locked,0)) FROM sku WHERE spu=? AND status='启用'",
                   (spu,)).fetchone()
    return dict(款号=r[0], 名称=r[1], 类型=r[2], 价格=(f"{价[0]:,.0f}" if 价[0] == 价[1] else f"{价[0]:,.0f}–{价[1]:,.0f}")
                if 价[0] is not None else (f"{r[3]:,.0f} 起" if r[3] else "—"),
                颜色=色, 尺码=码, 可卖件数=价[2], 上架日=r[5], 图=r[6] or f"/img/{r[0]}.svg", 状态=r[7])


def _规则建议(客户, 原话, 商品, 对上):
    对 = "、".join(f"{k}{v}" for k, v in 对上.items())
    条 = [f"开口先提她当时说的「{原话[:24]}…」,告诉她店里刚上了{对}的新款「{商品['名称']}」。",
          f"可以先发图给她看,颜色有 {'、'.join(商品['颜色'][:4]) or '—'},价格 {商品['价格']} 元。"]
    条.append(f"注意:{客户['备注']}。" if 客户.get("备注") else "注意:先问她现在还需不需要,不要直接推单。")
    return "\n".join(f"{i}. {x}" for i, x in enumerate(条, 1))


def 写建议(c, opp_id, spu, call=None, 打回=None):
    """给一条绑定写建议并存下。已有就不重写(用户定:绑定那一刻写一次)。返回 (正文, 来源)。

    打回:AI 管理平台打回后重写时传 {"上一版": 正文, "理由": …, "版本": 新版本号} ——
    把被打回的那一版和理由一起给模型,让它知道哪里不行(否则重写一次很可能写出同样的东西)。"""
    建表(c)
    有 = c.execute("SELECT text, source FROM recall_advice WHERE opp_id=? AND spu=?", (opp_id, spu)).fetchone()
    if 有:
        return 有
    r = c.execute(f"SELECT r.customer_id, r.quote, r.matched, r.来源 FROM {_绑定} r WHERE r.opp_id=? AND r.spu=? "
                  "ORDER BY r.created DESC LIMIT 1", (opp_id, spu)).fetchone()
    商品 = _商品(c, spu)
    if not r or not 商品:
        return None, None
    cu = c.execute("SELECT name, lifecycle, level, remark FROM customer WHERE id=?", (r[0],)).fetchone() or ("", "", "", "")
    客户 = dict(姓名=cu[0], 生命周期=cu[1], 等级=cu[2], 备注=cu[3])
    对上 = json.loads(r[2] or "{}")
    依据键 = "当初原话" if r[3] == "说过的" else "购买记录(她没说过,是按买过的推断的;开口别说「您说过」)"
    材料 = json.dumps(dict(客户=dict(客户, 姓名=(客户["姓名"] or "")[:1] + "女士/先生"), **{依据键: r[1]}, 对上了=对上,
                          新款={k: 商品[k] for k in ("名称", "类型", "价格", "颜色", "尺码")}), ensure_ascii=False)
    if 打回:
        材料 += (f"\n\n上一版被 AI 管理平台打回了。上一版:\n{打回['上一版']}\n打回理由:{打回['理由']}\n"
                 "照理由改,不要再犯同样的问题。")
    正文, 来源, 模型 = None, "规则", None
    调用号 = __import__("uuid").uuid4().hex      # 这一次模型调用的号:记录仪 / A1「外部trace」/ 这里存下的是同一个
    try:
        if call is None:
            sys.path.insert(0, os.path.join(HERE, "..", "agent"))
            import v1
            pv = v1.provider()
            resp = v1.call(pv, dict(model=pv["model"], max_tokens=400, system=建议提示,
                                    messages=[{"role": "user", "content": 材料}]),
                           purpose="上新卡片·给导购的建议", gen="工具", retries=2, extra={"trace_id": 调用号})
            模型 = pv["model"]
        else:
            resp = call(材料)
        t = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()
        # 形状对才收:三条、不太长;否则退回规则模板 —— 半截的建议和完整的在卡片上长得一样
        if 2 <= len([x for x in t.splitlines() if x.strip()]) <= 6 and 20 <= len(t) <= 400:
            正文, 来源 = t, "模型"
    except Exception:
        pass
    if not 正文:
        正文, 模型, 调用号 = _规则建议(客户, r[1] or "", 商品, 对上), None, None
    版 = (打回 or {}).get("版本") or 1
    c.execute("INSERT OR IGNORE INTO recall_advice(opp_id, spu, text, source, model, created, version, input, trace_id) "
              "VALUES(?,?,?,?,?,?,?,?,?)", (opp_id, spu, 正文, 来源, 模型, _今天().isoformat(), 版, 材料, 调用号))
    _上报监督(opp_id, spu, 版, 材料, 正文, 来源, 模型, 调用号, 商品, 客户, 库=c)
    return 正文, 来源


def _上报监督(opp_id, spu, 版, 材料, 正文, 来源, 模型, 调用号, 商品, 客户, 库=None):
    """推一份给 AI 管理平台(用户 10-10:能看 + 能打回)。**不抛**。库副本上写的不推。"""
    try:
        sys.path.insert(0, os.path.join(HERE, "..", "agent"))
        import artifact_report as AR
        if 库 is not None and not AR.是本库(库, 本库):
            return
        AR.排队(外部id=f"建议:{opp_id}:{spu}", 类型="建议", 版本=版,
               标题=f"上新建议 · {商品['名称']} → {(客户.get('姓名') or '')[:1]}**",
               输入=json.loads(材料.split("\n\n上一版被")[0]) if 材料.startswith("{") else {"材料": 材料},
               输出=正文, 规则=[dict(编号="上新卡片·建议提示词", 正文=建议提示)],
               世界日期=_今天().isoformat(), 模型=模型, 生成方式=来源, 外部trace=调用号)
    except Exception:
        pass


def 打回重写(opp_id, spu, 谁, 理由, db=None, call=None):
    """执行 AI 管理平台拉回来的打回:旧版连同理由挪进 recall_advice_log(**留作评测样本,不删**),
    带着理由重写一版。返回 (ok, 说明, 新版本)。"""
    c = sqlite3.connect(db or DB)
    try:
        建表(c)
        旧 = c.execute("SELECT text, source, model, created, version, input, trace_id FROM recall_advice "
                       "WHERE opp_id=? AND spu=?", (opp_id, spu)).fetchone()
        if not 旧:
            return False, f"没有 {opp_id} / {spu} 这条建议", None
        c.execute("INSERT INTO recall_advice_log(opp_id, spu, version, text, source, model, created, input, trace_id, "
                  "rejected_at, rejected_by, reject_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (opp_id, spu, 旧[4], 旧[0], 旧[1], 旧[2], 旧[3], 旧[5], 旧[6], _今天().isoformat(), 谁, 理由))
        c.execute("DELETE FROM recall_advice WHERE opp_id=? AND spu=?", (opp_id, spu))
        c.commit()          # 先落下「旧版已挪走」再调模型:模型慢,别压着库锁
        新, 来源 = 写建议(c, opp_id, spu, call=call, 打回=dict(上一版=旧[0], 理由=理由, 版本=旧[4] + 1))
        c.commit()
    finally:
        c.close()
    try:
        import oplog
        oplog.log_op(谁, None, f"{opp_id}:{spu}", 旧[4], 旧[4] + 1, True, "ADVICE_REJECT", f"AI 管理平台打回:{理由}", {})
    except Exception:
        pass
    return True, f"已重写成第 {旧[4] + 1} 版({来源})", 旧[4] + 1


def 补建议(db=None, call=None):
    """所有还没有建议的绑定都写一次。返回写了几条。"""
    c = sqlite3.connect(db or DB)
    try:
        建表(c)
        缺 = c.execute(f"SELECT DISTINCT r.opp_id, r.spu FROM {_绑定} r LEFT JOIN recall_advice a "
                       "ON a.opp_id=r.opp_id AND a.spu=r.spu WHERE a.opp_id IS NULL").fetchall()
        for oid, spu in 缺:
            写建议(c, oid, spu, call=call)
            c.commit()
        return len(缺)
    finally:
        c.close()


def 上新(spus, 今天=None, db=None, call=None):
    """**上新的正门**:把这几款挂上架 → 跑回捞(绑商机、派提醒)→ 给每条新绑定写建议。

    以后谁上新(店长在后台点、每日上新脚本每周放两款)都走这里 ——
    只改 status 不跑回捞的话,新款上去了、等它的客户没人去叫,而页面上什么都不缺。

    ⚠️ **已经上架的不再上一次**(数据工厂 10-10 提醒):不过滤的话,重复传一个老款进来,
    它的上架日会被改写成今天 —— 历史被静默改写,日历把半年前的老款显示成「今天刚上」,页面上什么都不缺。
    调用方的守卫只护得住调用方,所以闸放在这里;跳过的那几款原样返回,让调用方看得见。
    """
    import opportunity_store as S
    今天 = 今天 or _今天()
    c = sqlite3.connect(db or DB)
    try:
        上了, 本来就在架, 没这款 = [], [], []
        for spu in spus:
            r = c.execute("SELECT status FROM product WHERE spu=?", (spu,)).fetchone()
            if not r:
                没这款.append(spu); continue
            if r[0] == "上架":
                本来就在架.append(spu); continue
            c.execute("UPDATE product SET status='上架', on_shelf_at=?, updated=? WHERE spu=? AND status<>'上架'",
                      (今天.isoformat(), 今天.isoformat(), spu))
            上了.append(spu)
        出 = S.回捞(c, 上了, 今天) if 上了 else []
        c.commit()
    finally:
        c.close()
    补建议(db=db, call=call)        # 模型调用放在写库事务外面:模型慢,别让它压着库锁
    return dict(上了=上了, 本来就在架=本来就在架, 没这款=没这款, 绑上=出)


# ── 新品上市日历(用户 10-10:挂在工作台)──────────────────────────────────
def 日历(月=None, db=None, 今天=None):
    """一个月里每天上了 / 计划上哪几款。

    已上 = status 上架、on_shelf_at 落在这个月;计划 = status 待上架、plan_on_shelf 落在这个月。
    「计划上新日」那一列由数据工厂随 50 件新品一起加(10-10 约好的列名 plan_on_shelf);
    **列还没加时照实说「还没有排期」**,不拿别的日期冒充计划。
    每款带「绑上的商机」条数 —— 日历上一眼看得到哪一款上新那天会有人去叫客户。
    """
    今天 = 今天 or _今天()
    年, 月份 = (int(x) for x in (月 or 今天.strftime("%Y-%m")).split("-"))
    起 = dt.date(年, 月份, 1)
    止 = (起.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    c = sqlite3.connect(db or DB)
    try:
        建表(c)
        列 = {r[1] for r in c.execute("PRAGMA table_info(product)")}
        天 = {}

        def 放(d, spu, 名, 种, 状态):
            绑 = c.execute(f"SELECT COUNT(*) FROM {_绑定} WHERE spu=?", (spu,)).fetchone()[0]
            天.setdefault(str(d)[:10], []).append(dict(款号=spu, 名称=名, 类型=种, 状态=状态, 绑上的商机=绑))

        for spu, 名, 种, d in c.execute("SELECT spu, name, kind, substr(on_shelf_at,1,10) FROM product "
                                        "WHERE status='上架' AND substr(on_shelf_at,1,10) BETWEEN ? AND ? ORDER BY on_shelf_at, spu",
                                        (起.isoformat(), 止.isoformat())).fetchall():
            放(d, spu, 名, 种, "已上")
        有排期 = "plan_on_shelf" in 列
        if 有排期:
            for spu, 名, 种, d in c.execute("SELECT spu, name, kind, substr(plan_on_shelf,1,10) FROM product "
                                            "WHERE status='待上架' AND substr(plan_on_shelf,1,10) BETWEEN ? AND ? "
                                            "ORDER BY plan_on_shelf, spu", (起.isoformat(), 止.isoformat())).fetchall():
                放(d, spu, 名, 种, "计划")
        待上架 = c.execute("SELECT COUNT(*) FROM product WHERE status='待上架'").fetchone()[0]
    finally:
        c.close()
    return dict(月=f"{年}-{月份:02d}", 起=起.isoformat(), 止=止.isoformat(), 今天=今天.isoformat(), 天=天,
                已上=sum(1 for v in 天.values() for x in v if x["状态"] == "已上"),
                计划=sum(1 for v in 天.values() for x in v if x["状态"] == "计划"), 待上架总数=待上架,
                **({} if 有排期 else {"说明": "还没有排期:商品表里还没有「计划上新日」(plan_on_shelf)这一列 —— "
                                             "数据工厂造 50 件新品时一起加,加之前日历只显示已经上了的"}))


# ── 卡片 ────────────────────────────────────────────────────────────────
def _可见(me, 指派, 店):
    if me.get("role") == "总部运营":
        return True
    if me.get("role") == "店长":
        return me.get("shop") == 店
    return bool(指派) and me.get("no") == 指派


def _行们(c, 今天, schedule_id=None):
    起 = (今天 - dt.timedelta(days=K.上新卡片天 - 1)).isoformat()
    sql = ("SELECT s.id, s.status, s.assignee_no, s.shop, s.end_ts, ot.opp_id, ot.kind, ot.detail, "
           "r.spu, r.quote, r.matched, r.created, r.customer_id, r.来源 "
           "FROM opportunity_task ot JOIN schedule s ON s.id=ot.schedule_id "
           f"JOIN {_绑定} r ON r.opp_id=ot.opp_id AND r.spu=json_extract(ot.detail,'$.新品') "
           f"WHERE ot.kind IN ({','.join('?' * len(回捞类))}) AND r.created >= ? AND r.created <= ?")
    args = [*回捞类, 起, 今天.isoformat()]
    if schedule_id:
        sql += " AND s.id=?"; args.append(schedule_id)
    return c.execute(sql + " ORDER BY r.created DESC, s.id", args).fetchall()


def 卡片(me, db=None, 今天=None):
    """这个人登录时该弹的卡片。顾问 = 指派给自己的;店长 = 本店的;总部 = 全部。"""
    今天 = 今天 or _今天()
    c = sqlite3.connect(db or DB)
    try:
        建表(c)
        出 = []
        for sid, st, 指派, 店, 止, oid, kind, detail, spu, 原话, 对上, 绑日, cid, 来源 in _行们(c, 今天):
            if not _可见(me, 指派, 店):
                continue
            cu = c.execute("SELECT name, phone, addr, remark, lifecycle, level FROM customer WHERE id=?", (cid,)).fetchone()
            商品 = _商品(c, spu) or dict(款号=spu, 名称="(商品已不在)")
            建 = c.execute("SELECT text, source FROM recall_advice WHERE opp_id=? AND spu=?", (oid, spu)).fetchone()
            # 按「绑上那天」算:和 30 天窗口同一个起点。走上新正门时它就是上架日;
            # 演示数据里有几款很早就上架、上新是模拟出来的,按上架日算会显示「上新第 150 天」而卡片还在弹
            上新日 = dt.date.fromisoformat(绑日[:10])
            出.append(dict(
                任务号=sid, 任务状态=st, 任务期限=str(止)[:10], 商机=oid, 提醒类型=kind,
                顾客=dict(客户号=cid, 姓名=cu[0] if cu else "—", 电话=打码电话(cu[1] if cu else ""),
                         地址=打码地址(cu[2] if cu else ""), 生命周期=cu[4] if cu else None, 等级=cu[5] if cu else None),
                # 来源:「说过的」= 电话里的原话;「购买推断」= 按购买记录推的依据(用户 10-10)—— 页面按它换标题,
                # 不能把推断出来的那句写成「她当初说的」
                留言=dict(当初原话=原话, 来源=来源, 客户备注=cu[3] if cu else None),
                对上了=json.loads(对上 or "{}"),
                建议=dict(正文=建[0], 来源=建[1]) if 建 else dict(正文=None, 来源="还没写(补建议没跑)"),
                新款=商品, 绑定日=绑日,
                上新第几天=(今天 - 上新日).days + 1, 还弹几天=max(0, K.上新卡片天 - (今天 - dt.date.fromisoformat(绑日[:10])).days)))
        return {"张数": len(出), "卡片": 出, "窗口": f"上新 {K.上新卡片天} 天内",
                "说明": "卡片暂时不随任务完成消失(用户 10-10:面试要展示);页面上手动关,下次登录再弹。"}
    finally:
        c.close()


def 看完整联系方式(me, schedule_id, db=None, 今天=None):
    """点「看完整号码」:**只给能看这张卡片的人**,每点一次进操作台账(谁、什么时候、看了哪位客户)。"""
    今天 = 今天 or _今天()
    c = sqlite3.connect(db or DB)
    try:
        行 = _行们(c, 今天, schedule_id=schedule_id)
        if not 行 or not _可见(me, 行[0][2], 行[0][3]):
            ok, 结果 = False, dict(error="这张卡片不在你的范围里,或已经过了上新 30 天")
        else:
            cu = c.execute("SELECT name, phone, addr FROM customer WHERE id=?", (行[0][12],)).fetchone()
            ok, 结果 = True, dict(客户号=行[0][12], 姓名=cu[0], 电话=cu[1], 地址=cu[2],
                                  note="已记入操作台账:谁、什么时候看了这位客户的完整联系方式")
    finally:
        c.close()
    try:
        import oplog
        oplog.log_op(me.get("no"), None, (行[0][12] if 行 else schedule_id), None, None, ok, "REVEAL_CONTACT",
                     f"上新卡片 {schedule_id} 看完整联系方式" + ("" if ok else "(被拒)"),
                     {"schedule_id": schedule_id, "role": me.get("role")})
    except Exception:
        if ok:      # 台账写不进就不给全号 —— 「点了能看、但没留痕」正是用户要防的那件事
            return dict(error="操作台账写不进,这次不给完整号码;请稍后再试")
    return 结果


if __name__ == "__main__":
    # 给现有的绑定补一次建议(绑定那一刻没写上的,比如上线这个功能之前就绑上的那几条)
    print(f"补了 {补建议()} 条建议")
