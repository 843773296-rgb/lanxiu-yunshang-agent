# -*- coding: utf-8 -*-
"""预警 → 任务:从预警那一行派单,任务上记「来自哪条预警」,同一件事没办完不重派。

复审第 4 节 D(用户 2026-10-23 拍):
  · 先接**工厂催办**:该催工厂的那一页每行显示「已跟进:谁 / 哪条任务」,店长及以上可「从这行派单」
  · **同一张单延期后又超期,算一件新事,可以再派**;**上一条还没办完就不重复派**(返回明确理由)
  · **库存预警开口子**:新类型「补货跟进」不挂客户、挂 SKU,只能派给店长 / 总部运营
  · 不加「暂缓」状态(会改任务状态机)

## 防重复派:照搬商机提醒那一套,不另造

`opportunity_store._派提醒`:**同一条商机同一种提醒,任务还「有效」就不再派**;办完了可以再派。
这里同一个形状,只是「同一件事」的键换成预警自己的:

    工厂催办   订单号 + 超期日期(= 那次的承诺完工日;没回接单的那种没有日期,记「未回接单」)
    库存预警   SKU 号 + 预警档位(发不出 / 断货 / 快没了)

  ① 同一张单 / 同一个 SKU **还有一条没办完的**(同类型、挂着同一个单号、状态「有效」)→ 不派。
     不分键:上一条还没办完,换个日子也还是那一个人在跟这张单
     (手工从通用口派的「订单跟踪」也算 —— 不然页面上派一条、通用口再派一条,同一张单两个人在催)
  ② **同一个键已经办完过** → 不派:那件事办过了。工厂延期后又超期,承诺日变了,键就变了,可以再派;
     库存从「快没了」掉到「断货」,档位变了,也可以再派
  ③ 其余 → 可以派

**预警是服务端现算的,不信页面报上来的键** —— 页面只说「这张单 / 这个 SKU」,
超期日期和档位由这里按同一套口径(`factory_inbox.该催清单` / `stockalert.档`)当场再算一遍;
不在预警里的不让派。信页面的话,改一个日期就能绕过防重复派。

## 来源记在哪

`alert_task` 一张小表(任务号 → 哪类预警、哪个单号、键)。**schedule 不为一种任务加一列** ——
和 report_action / opportunity_task 同一个做法。日期单独一列(`key_date`,整列日期,平移能整列挪),
不和档位混进一个字符串里。
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")

DDL = """CREATE TABLE IF NOT EXISTS alert_task(
  schedule_id TEXT PRIMARY KEY,   -- schedule.id
  kind     TEXT NOT NULL,         -- 工厂催办 / 库存预警 / 挽回
  obj      TEXT NOT NULL,         -- 订单号 / SKU 号 / 客户号(和 schedule.ref_id 同一个)
  key_date TEXT,                  -- 工厂催办:超期的那个承诺完工日(YYYY-MM-DD);其余 NULL
  key_tag  TEXT NOT NULL,         -- 工厂催办:超期 / 未回接单;库存预警:档位(发不出 / 断货 / 快没了);挽回:「待付款 订单号」/「爽约 预约号」…
  created  TEXT NOT NULL)"""

# 预警类 → 派成什么类型的任务
# 「挽回」(业务需求池 D2,用户 11-12 排到下一件):未成交挽回清单上的一行 → 给顾问派一条「电话回电」。
#   挂的是**客户**(电话回电是客户族,规范要挂客户号),所以防重复派的键是客户:
#   这位客户还有一条没办完的电话回电 → 不再派(不管那条是不是从挽回派的 —— 同一个客户两个人在打电话更糟)。
任务类型 = {"工厂催办": "订单跟踪", "库存预警": "补货跟进", "挽回": "电话回电"}
# 库存预警里**哪几档能派补货跟进**:就是 stockalert.档 里表示「缺」的那三档。
# 「卖不动」是压货不是缺货、「够」不是预警 —— 都不是补货的事。不是新门槛,是档位本身的意思
可派档 = ("发不出", "断货", "快没了")


def 建表(c):
    """登记在 tools/ensure_tables.py:第一次有人从预警派单才会建 —— 本地建过就一直在、CI 每次从零。"""
    c.execute(DDL)


def _c():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


# ── 预警现算(不信页面)──────────────────────────────────────────────
def 工厂催办项(order_id, me):
    """这张单现在在不在**这个人看得到的**该催清单里。→ (项 or None, 键日期, 键标签)。
    范围和 api.factory_chase 同一个口径:总部运营看全部,其余只看本店。"""
    import factory_inbox as _fi
    from seed import TODAY
    shop = None if me.get("role") == "总部运营" else me.get("shop")
    for x in _fi.该催清单(TODAY, shop):
        if x["订单"] == order_id:
            if x.get("承诺完工日"):
                return x, str(x["承诺完工日"])[:10], "超期"
            return x, None, "未回接单"
    return None, None, None


def sku档(c, code):
    """一个 SKU 现在在哪一档。口径全在 knowledge/stockalert.py,**这里只取数**:
    在手 / 占用来自 sku 表,卖过几件只数 `卖掉了()` 认的那些(和 api.stock_alert 同一把尺)。
    停用的 SKU 不进预警(同 stock_alert)。→ (档位 or None, 一句话)。"""
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
    import stockalert as _sa
    r = c.execute("SELECT stock, locked, status FROM sku WHERE code=?", (code,)).fetchone()
    if not r:
        return None, f"没有这个 SKU:{code}"
    if r["status"] == "停用":
        return None, "停用的 SKU 不进预警"
    件 = 0
    for x in c.execute("SELECT i.qty, o.status, o.refund_status FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                       "WHERE i.sku=?", (code,)):
        if _sa.卖掉了(x["status"], x["refund_status"])[0]:
            件 += x["qty"] or 0
    return _sa.档(r["stock"], r["locked"], 件)


def 全部sku档(c):
    """整张 sku 表一次算完档位(列表页用,不逐行查)。→ {code: 档位}。口径同 sku档。"""
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
    import stockalert as _sa
    c.row_factory = sqlite3.Row
    卖 = {}
    for x in c.execute("SELECT i.sku, i.qty, o.status, o.refund_status FROM ordr_item i "
                       "JOIN ordr o ON o.id=i.order_id WHERE i.sku IS NOT NULL AND i.sku<>''"):
        if _sa.卖掉了(x["status"], x["refund_status"])[0]:
            卖[x["sku"]] = 卖.get(x["sku"], 0) + (x["qty"] or 0)
    return {r["code"]: (None if r["status"] == "停用" else _sa.档(r["stock"], r["locked"], 卖.get(r["code"], 0))[0])
            for r in c.execute("SELECT code, stock, locked, status FROM sku")}


def 挽回项(号, me):
    """这张单 / 这条预约现在在不在**这个人看得到的**挽回清单里。→ dict 或 None。
    口径和 api.recovery_queue 同一个:待付款的订单、已取消 / 爽约 / 已过期的预约。
    范围:总部运营看全部,其余只看本店(按门店码,改过名也对得上)。"""
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
    import recovery as _rc
    import shop_key as SK
    c = _c()
    try:
        跨店 = me.get("role") == "总部运营"
        本店码 = None if 跨店 else SK.码(c, me.get("shop"))
        def 在范围(店):
            return 跨店 or (店 and SK.码(c, 店) == 本店码)
        o = c.execute("SELECT o.id, o.status, o.created, o.shop, o.customer_id, o.advisor_no, o.payable, c.name, "
                      "c.advisor_no bind FROM ordr o LEFT JOIN customer c ON c.id=o.customer_id WHERE o.id=?",
                      (号,)).fetchone()
        if o:
            if o["status"] != "待付款" or not 在范围(o["shop"]) or not o["customer_id"]:
                return None
            return dict(客户=o["customer_id"], 客户名=o["name"], 标=f"待付款 {o['id']}",
                        日=str(o["created"] or "")[:10] or None, 顾问=o["advisor_no"] or o["bind"],
                        话=f"挽回 · 待付款订单 {o['id']}(应付 {o['payable']}):下了单没付钱 —— 问清卡在哪(价格 / 方案 / 家里商量),"
                           f"不催款不逼单;**这条只是派给你去联系,不是已经联系过**")
        a = c.execute("SELECT a.id, a.status, a.start_ts, a.shop, a.customer_id, a.advisor_no, c.name, c.advisor_no bind "
                      "FROM appointment a LEFT JOIN customer c ON c.id=a.customer_id WHERE a.id=?", (号,)).fetchone()
        if a:
            if a["status"] not in _rc.未成行 or not 在范围(a["shop"]) or not a["customer_id"]:
                return None
            是什么, 该做什么 = _rc.未成行[a["status"]]
            return dict(客户=a["customer_id"], 客户名=a["name"], 标=f"{a['status']} {a['id']}",
                        日=str(a["start_ts"] or "")[:10] or None, 顾问=a["advisor_no"] or a["bind"],
                        话=f"挽回 · 预约 {a['id']}「{a['status']}」({是什么.replace('**', '')}):{该做什么.replace('**', '')}")
        return None
    finally:
        c.close()


# ── 防重复派(在写的那个事务里调)────────────────────────────────────
def 重复吗(c, 来源):
    """→ None(可以派)或 (拒绝码, 人话, 上一条任务号)。来源 = dict(kind, obj, key_date, key_tag)。"""
    建表(c)
    类型 = 任务类型[来源["kind"]]
    开 = c.execute("SELECT s.id, st.name FROM schedule s LEFT JOIN staff st ON st.no=s.assignee_no "
                  "WHERE s.type=? AND s.ref_id=? AND s.status='有效' ORDER BY s.assigned_at DESC LIMIT 1",
                  (类型, 来源["obj"])).fetchone()
    if 开:
        return ("ALERT_OPEN",
                f"{来源['obj']} 上一条「{类型}」{开[0]}(派给 {开[1] or '未指派'})还没办完 —— "
                f"同一件事没办完不重复派;要换人用改派", 开[0])
    同 = c.execute("SELECT a.schedule_id FROM alert_task a JOIN schedule s ON s.id=a.schedule_id "
                  "WHERE a.kind=? AND a.obj=? AND a.key_tag=? AND COALESCE(a.key_date,'')=COALESCE(?,'') "
                  "AND s.status='完结' ORDER BY a.created DESC LIMIT 1",
                  (来源["kind"], 来源["obj"], 来源["key_tag"], 来源.get("key_date"))).fetchone()
    # 工厂催办**办完了就能再派**(用户 2026-10-23 选型卡拍「办完后能再派」):
    # 工厂办完一次仍不交货、也不报延期,正是最需要再催的时候;没办完不重派由上面那条兜着。
    # 库存那一类没问过,照旧 —— 同一档办完了不再派。
    if 同 and 来源["kind"] != "工厂催办":
        话 = (f"{来源['obj']} 在「{来源['key_tag']}」这一档已经由 {同[0]} 跟进办完了 —— "
              "档位变了(比如快没了 → 断货)才算新的一件")
        return ("ALERT_DONE", 话, 同[0])
    return None


def 记来源(c, sid, 来源, 时间):
    # ⚠️ key_date 只许是 YYYY-MM-DD 或 NULL,别的形状**拒写**(数据工厂 10-23 提醒)。
    # 每日平移按「这一列每个值都像日期」把它判成整列日期、和承诺日同一天一起挪 —— 防重复派的键才恒等。
    # 只要混进一个 "-" / "N/A",这一列就掉进「混着日期」,没登记的话凌晨平移直接拒跑,
    # 而那时没人会想到是哪一支写了个 "-"。**把约定做成结构**,不靠后来的人记得。
    import re as _re
    kd = 来源.get("key_date")
    if kd is not None and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(kd)):
        raise ValueError(f"alert_task.key_date 只收 YYYY-MM-DD 或空,拿到的是「{kd}」—— 写进去会让每日平移把这一列判成混着日期")
    建表(c)
    c.execute("INSERT INTO alert_task(schedule_id, kind, obj, key_date, key_tag, created) VALUES(?,?,?,?,?,?)",
              (sid, 来源["kind"], 来源["obj"], 来源.get("key_date"), 来源["key_tag"], 时间))


# ── 已跟进(列表页每行显示)─────────────────────────────────────────
def 跟进情况(kind, objs):
    """{单号: dict(任务, 谁, 状态, 键)} —— 这一类预警,每个单号**最近一条**从预警派出的任务。
    只读;表还没建过(没人从预警派过)就是空。"""
    objs = [o for o in objs if o]
    if not objs:
        return {}
    c = _c()
    try:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='alert_task'").fetchone():
            return {}
        out = {}
        ph = ",".join("?" * len(objs))
        for r in c.execute(f"SELECT a.obj, a.schedule_id, a.key_date, a.key_tag, s.status, st.name "
                           f"FROM alert_task a JOIN schedule s ON s.id=a.schedule_id "
                           f"LEFT JOIN staff st ON st.no=s.assignee_no "
                           f"WHERE a.kind=? AND a.obj IN ({ph}) ORDER BY a.created, a.schedule_id",
                           (kind, *objs)):
            out[r["obj"]] = dict(任务=r["schedule_id"], 谁=r["name"], 状态=r["status"],
                                 键=(r["key_date"] or r["key_tag"]) if kind == "工厂催办" else r["key_tag"])
        return out
    finally:
        c.close()


# ── 写口 ────────────────────────────────────────────────────────────
def 派(d, me):
    """从预警的一行派单。d = {kind: 工厂催办 / 库存预警 / 挽回, obj: 订单号 / SKU / (挽回:订单号或预约号), assignee_no?, end, note?}。

    身份只认登录会话(me),**请求体里的键(超期日期、档位)一概不收** —— 由这里现算。
    权限(店长及以上)、能派给谁、类型的数据规范,全交给 tasks.assign_task,不在这里另写一份。
    """
    import tasks as TK
    if not me:
        return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in TK.MANAGER_ROLES:
        return TK._deny(me, "WRONG_ROLE", f"从预警派单须由店长及以上操作,你的角色是「{me.get('role')}」")
    kind = (d.get("kind") or "").strip()
    obj = (d.get("obj") or "").strip()
    if kind not in 任务类型:
        return dict(ok=False, code="BAD_KIND", reason=f"预警类只能是 {' / '.join(任务类型)}")
    if not obj:
        return dict(ok=False, code="NEED_OBJ", reason="要说是哪张单 / 哪个 SKU")

    if kind == "工厂催办":
        项, 日, 标 = 工厂催办项(obj, me)
        if not 项:
            return dict(ok=False, code="NOT_ALERTING",
                        reason=f"{obj} 现在不在你能看到的「该催工厂」清单里(没超期、已完工,或不是本店的单)—— "
                               "不在预警里的不从这里派;要盯一张单用普通的「订单跟踪」")
        来源 = dict(kind=kind, obj=obj, key_date=日, key_tag=标)
        默认话 = (f"工厂催办 · 订单 {obj}:" + ("过了承诺完工日还没完工 —— 去催工厂,并先告诉顾客可能会晚"
                                              if 标 == "超期" else "开工多日工厂还没回接单 —— 问清单发到了没有"))
    elif kind == "挽回":
        项 = 挽回项(obj, me)
        if not 项:
            return dict(ok=False, code="NOT_ALERTING",
                        reason=f"{obj} 现在不在你能看到的挽回清单里(已经付了 / 预约已经成行 / 不是本店的 / 没有这个号)—— "
                               "不在清单里的不从这里派;要联系一个客户用普通的「电话回电」")
        来源 = dict(kind=kind, obj=项["客户"], key_date=项["日"], key_tag=项["标"])
        默认话 = 项["话"]
        if not d.get("assignee_no"):
            d = dict(d, assignee_no=项["顾问"])     # 默认派给这一单 / 这条预约的顾问;不在本店在职的由 assign_task 拒、点名可派的人
    else:
        c = _c()
        try:
            档, 话 = sku档(c, obj)
        finally:
            c.close()
        if 档 not in 可派档:
            return dict(ok=False, code="NOT_ALERTING",
                        reason=f"{obj} 现在{('是「' + 档 + '」') if 档 else ''}不在要补货的预警里"
                               f"(能派的档:{' / '.join(可派档)})。{话}")
        来源 = dict(kind=kind, obj=obj, key_date=None, key_tag=档)
        默认话 = f"补货跟进 · SKU {obj}:{档} —— {话}"

    note = (d.get("note") or "").strip() or 默认话
    r = TK.assign_task(dict(type=任务类型[kind], assignee_no=d.get("assignee_no"), ref_id=来源["obj"],
                            note=note, end=d.get("end"), start=d.get("start")), me, _来源=来源)
    if r.get("ok"):
        r["来源"] = 来源
    return r


def 默认截止(现在=None):
    """一键建跟进不给截止时的默认值:**当天 18:00;过了 17:00 就落到明天 18:00**。

    11-12 门禁 18:01 跑到这条,写死的「今天 18:00」比开始时间还早,整批「派不了」——
    截止在过去的任务不是「今天要做」,是一条没人能完成的任务。留一小时是让顾问打得完电话。
    `现在` 可传 datetime 或 'YYYY-MM-DD HH:MM'(给判据用);不传取世界的当下。
    """
    import datetime as _dt
    from worldclock import 当下
    now = 现在 if isinstance(现在, _dt.datetime) else (_dt.datetime.fromisoformat(现在) if 现在 else 当下())
    日 = now.date() + _dt.timedelta(days=1 if now.hour >= 17 else 0)
    return f"{日} 18:00"


def 批量挽回(行们, me):
    """未成交挽回清单**一键建跟进**(业务需求池 D2)。行们 = [{号: 订单号或预约号, assignee_no?, end?, note?}…]。

    **逐行各自成败,不是全过才写** —— 和 assign_batch 不一样:排班是一个决定(半截比没排更难收拾),
    而这里每一行是**一位客户的一通电话**,彼此独立;一位客户已经有人在跟,不该挡住另外九位。
    返回每行的结果,并分「建了 / 已经有人在跟 / 不在清单里 / 派不了」报,不混成一个失败数。
    """
    if not 行们:
        return dict(ok=False, code="EMPTY", reason="没给要跟进的行(订单号或预约号)")
    if len(行们) > 30:
        return dict(ok=False, code="TOO_MANY", reason=f"一次最多 30 行,你给了 {len(行们)} 行 —— 分几次建")
    默认止 = 默认截止()
    结果, 分 = [], {"建了": 0, "已经有人在跟": 0, "不在清单里": 0, "派不了": 0}
    for it in 行们:
        号 = str(it.get("号") or it.get("obj") or it.get("订单") or it.get("预约") or "").strip()
        r = 派(dict(kind="挽回", obj=号, assignee_no=it.get("assignee_no") or it.get("assignee"),
                   end=it.get("end") or 默认止, note=it.get("note")), me)
        类 = ("建了" if r.get("ok") else "已经有人在跟" if r.get("code") in ("ALERT_OPEN", "ALERT_DONE")
              else "不在清单里" if r.get("code") == "NOT_ALERTING" else "派不了")
        分[类] += 1
        结果.append(dict(号=号, 结果=类, 任务=r.get("id") or r.get("task_id"), 说明=r.get("reason")))
    return dict(ok=分["建了"] > 0, 分=分, 明细=结果,
                reason=f"建了 {分['建了']} 条跟进;已经有人在跟 {分['已经有人在跟']} 条;不在清单里 {分['不在清单里']} 条;派不了 {分['派不了']} 条"
                       + " —— 这些只是派给顾问去联系,**不是已经联系过客户**")
