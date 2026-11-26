# -*- coding: utf-8 -*-
"""预约的查 / 约 / 改 —— 聊天工具和旧后台页面**同一份**业务逻辑(包四第一件,用户 2026-11-25 拍)。

## 为什么单独一个模块

旧后台 server.py 里早就有 create_appointment / edit_appointment(台账第四十八条「和新建预约同一套权限」),
但它们用的是 server.py 自己的助手(rows / _insert / log_edit…),聊天工具那边(api.py)import 不了 server。
原来的选项是在 api.py 里再写一份 —— 两份写入路径迟早不一样,而不一样时不会报错(CLAUDE.md 第 7 节)。
所以把规则放这儿,server.py 和 api.py 都来调:时间规则 rules.validate_appointment、点名 booking.校验点名、
门店码 shop_key、台账 oplog.log_op,一个也不另写。

## 口径(落在哪)
- 时间:`rules.validate_appointment`(提前量 / 补录只许店长及以上、7 天内)—— 不在这里重写
- 范围:**门店的人只约 / 改本店客户的预约**,跨店角色(api.跨店角色)看全部 —— 和 api.本店范围 同一口径
- 状态:只有「待确认 / 已预约」能改时间;已到店 / 完成 / 取消 / 过期 / 爽约是已经发生的事
- 停业门店不接新预约(shop_key.停业理由)
- 顾问:新约默认落到**发起人自己**(顾问)或客户的归属顾问(店长代约);指定的顾问必须是这家店在职的
- 每一笔都进 op_log(谁、什么时候、改了什么);改时间还进 edit_log(改前 / 改后)

写口两个都是「高档」确认卡(用户 11-25 拍:预约是对客承诺,每次问);这里不管确认 —— 那在工具服务那一层。
"""
import contextlib
import datetime as _dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

可改的状态 = ("待确认", "已预约")
进行中 = ("待确认", "已预约", "已到店")
默认时长分钟 = 60
字段中文 = {"start_ts": "开始时间", "end_ts": "结束时间", "advisor_no": "顾问"}


DB = None   # 库路径:None = 跟 api.DB(dbpath 单源);检查在副本上跑时把它指过来(appt_ops_write_check 那样),读写同一份


def _api():
    import api
    return api


def _db():
    """读写哪份库。**跟着调用方已经指好的副本走**(11-26 门禁 W2 又让真库多了一条测试预约之后改的):
    检查在副本上跑时,有的只把 server.DB 指过去(write_check / write_smoke / shop_inactive…),有的只把 api.DB 指过去 ——
    原来这里只认 api.DB,于是「业务写副本、预约写真库」。现在:显式 DB > 被改离默认路径的 server.DB / api.DB > 默认真库。"""
    if DB:
        return DB
    import dbpath
    默认 = os.path.realpath(dbpath.路径())
    候选 = []
    if "server" in sys.modules:
        候选.append(getattr(sys.modules["server"], "DB", None))
    候选.append(_api().DB)
    for c in 候选:
        if c and os.path.realpath(c) != 默认:
            return c
    return _api().DB


def _w():
    """写连接(api 那个连接是只读的,写要自己开)。按 _db() 开 —— 和读同一份库,副本上跑检查时不会读真库写副本。"""
    import sqlite3
    c = sqlite3.connect(_db()); c.row_factory = sqlite3.Row
    return c


def _rows(sql, *a):
    import sqlite3
    with contextlib.closing(sqlite3.connect(f"file:{_db()}?mode=ro", uri=True)) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a).fetchall()]


def _now():
    import worldclock
    return worldclock.当下()


def _标准时间(s):
    """'2026-11-28T14:00' / '2026-11-28 14:00' → '2026-11-28 14:00';认不出 → None。"""
    s = str(s or "").replace("T", " ").strip()
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _营业时间外(开始):
    """营业时间的口径只有一份:booking.OPEN_HOUR(顾客自助预约那条匿名口在用)。在外 → 一句拒的话;在内 → None。"""
    import booking
    h = _dt.datetime.fromisoformat(开始).hour
    lo, hi = booking.OPEN_HOUR
    return None if lo <= h < hi else f"门店 {lo}:00–{hi}:00 营业,{开始[-5:]} 没人接待 —— 换一个营业时间内的点"


def _店码(c, shop):
    import shop_key as SK
    return SK.码(c, shop) if shop else None


def _我店码(me):
    """这个人只能看 / 写哪家店(None = 跨店角色,不限)。"""
    api = _api()
    店 = api.本店范围(me)
    if 店 is None:
        return None
    with contextlib.closing(_w()) as c:
        return _店码(c, 店)


def _客户(api, 客户):
    """按客户号或姓名认客户 → (行, 错误串)。重名不猜。"""
    r = _rows("SELECT id, name, shop, shop_code, advisor_no, archived FROM customer WHERE id=?", 客户)
    if r:
        return r[0], None
    人们 = _rows("SELECT id, name, shop, shop_code, advisor_no, archived FROM customer WHERE name=? AND archived=0", 客户)
    if len(人们) == 1:
        return 人们[0], None
    if len(人们) > 1:
        return None, f"「{客户}」命中 {len(人们)} 个客户({', '.join(p['id'] for p in 人们[:5])}),要客户号"
    return None, f"客户 {客户} 不存在(客户号和姓名都没对上)"


def _顾问(api, 谁, 店码):
    """工号 / 姓名 → 这家店在职顾问的工号;认不出 → None(不猜)。"""
    v = str(谁 or "").strip()
    if not v:
        return None
    # 旧后台页面传的是显示串「A01 林岚」(短号 + 姓名)—— 取最后一段当姓名再认(11-26:转调后页面那条路认不出,门禁 W2 抓到)
    if " " in v:
        v = v.split()[-1]
    with contextlib.closing(_w()) as c:
        import shop_key as SK
        片, 参 = SK.门店条件(c, 店码)
        r = c.execute(f"SELECT no FROM staff WHERE (no=? OR name=?) AND role='顾问' AND status='启用' AND {片}",
                      (v, v, *参)).fetchall()
    return r[0][0] if len(r) == 1 else None


def _log(me, aid, 动作, 结果, ok, 码, 话):
    from oplog import log_op
    log_op((me or {}).get("name") or "?", "appointment", aid or "-", 动作, 结果, ok, 码, 话, {"role": (me or {}).get("role")})


def _记编辑(me, aid, 改了):
    """edit_log:和 server.log_edit 同一张表同一形状(改前 / 改后);没改动也记一条,别让「没改」和「没记」长得一样。"""
    api = _api()
    if not 改了:
        改了 = [{"字段": "(无)", "改前": "", "改后": "", "说明": "这次提交没有改动任何字段"}]
    with contextlib.closing(_w()) as c, c:
        c.execute("INSERT INTO edit_log(ts,actor,actor_no,obj,target,title,source,changes)"
                  " VALUES(datetime('now','localtime'),?,?,?,?,?,?,?)",
                  ((me or {}).get("name") or "?", (me or {}).get("no"), "预约", aid, f"编辑预约 {aid}", "聊天助手",
                   json.dumps(改了, ensure_ascii=False)))


# ── 查 ─────────────────────────────────────────────────────────────────────
def 列(me, 客户=None, 日期=None, 顾问=None, 状态=None, 限=20, 预约号=None):
    """本店(跨店角色:全部)的预约。筛客户(号或名)/ 哪一天 / 顾问(工号或名)/ 状态;默认只给进行中的,按开始时间排。
    给了预约号就只查那一条、**不管状态**(11-25 真跑 AP03:要改一条已完成的,默认筛掉了它,模型只能说查不到)。"""
    api = _api()
    if not (me or {}).get("no"):
        return {"error": "没有身份,看不了预约 —— 请先登录"}
    我店 = _我店码(me)
    片, 参 = ("1=1", []) if 我店 is None else ("a.shop_code=?", [我店])
    if 客户:
        行, 错 = _客户(api, 客户)
        if 错:
            return {"error": 错, "范围": "本店" if 我店 else "全部"}
        if 我店 and (行["shop_code"] or "") != 我店:
            return {"error": f"你的门店里没有客户「{客户}」(只查了本店)", "范围": "本店"}
        片 += " AND a.customer_id=?"; 参.append(行["id"])
    if 日期:
        d = _标准时间(日期 if " " in str(日期) or "T" in str(日期) else f"{日期} 00:00")
        if not d:
            return {"error": f"日期「{日期}」认不出,写成 2026-11-28"}
        片 += " AND substr(a.start_ts,1,10)=?"; 参.append(d[:10])
    if 顾问:
        no = _顾问(api, 顾问, 我店) if 我店 else None
        片 += " AND a.advisor_no=?"; 参.append(no or str(顾问))
    if 预约号:
        片 += " AND a.id=?"; 参.append(str(预约号).strip())
    elif 状态:
        片 += " AND a.status=?"; 参.append(状态)
    else:
        片 += f" AND a.status IN ({','.join('?' * len(进行中))})"; 参.extend(进行中)
    rs = _rows(f"""SELECT a.id, a.customer_id, c.name 客户, a.shop, a.advisor_no, s.name 顾问, a.start_ts, a.end_ts, a.status,
                              a.named_state, a.channel
                       FROM appointment a LEFT JOIN customer c ON c.id=a.customer_id LEFT JOIN staff s ON s.no=a.advisor_no
                       WHERE {片} ORDER BY a.start_ts LIMIT ?""", *参, int(限 or 20))
    return {"范围": "本店" if 我店 else "全部", "条数": len(rs), "只给进行中": not 状态 and not 预约号,
            "预约": [{"预约号": r["id"], "客户": r["客户"], "客户号": r["customer_id"], "门店": r["shop"],
                     "顾问": r["顾问"] or r["advisor_no"], "开始": r["start_ts"], "结束": r["end_ts"], "状态": r["status"],
                     "点名": r["named_state"], "渠道": r["channel"]} for r in rs],
            "note": "改时间用 reschedule_appointment(要预约号);取消 / 到店 / 完成在旧后台做,这里不改状态"}


# ── 约 ─────────────────────────────────────────────────────────────────────
def 新建(d, me):
    """帮客户约。d:{客户(号或名), 开始, 结束(可省,默认 +60 分), 方式(默认 到店量体), 顾问(可省), 点名三态 / 点名工号 / 渠道(可省)}。
    → dict(ok, code, reason, id?)。规则都在别处(见模块注释),这里只串起来。"""
    api = _api()
    角色, 谁 = (me or {}).get("role"), (me or {}).get("name") or "?"
    def 拒(码, 为何):
        _log(me, None, "新建", "拒绝", False, 码, 为何)
        return dict(ok=False, code=码, reason=为何)
    if not (me or {}).get("no"):
        return 拒("NO_LOGIN", "没有身份 —— 写预约要记是谁约的,请先登录")
    行, 错 = _客户(api, d.get("客户") or d.get("customer_id") or d.get("customer"))
    if 错:
        return 拒("NO_CUSTOMER", 错)
    if 行.get("archived"):
        return 拒("ARCHIVED", f"客户 {行['id']} 的档案已归档,先在后台恢复再约")
    我店 = _我店码(me)
    店码 = 行["shop_code"] or None
    if 我店 and (店码 or "") != 我店:
        return 拒("OTHER_SHOP", "只能给本店客户约 —— 这位客户的档案不在你的门店,请让他所在门店的顾问来约")
    开始 = _标准时间(d.get("开始") or d.get("start"))
    if not 开始:
        return 拒("BAD_TIME", "开始时间认不出,写成 2026-11-28 14:00")
    结束 = _标准时间(d.get("结束") or d.get("end")) or (_dt.datetime.fromisoformat(开始) + _dt.timedelta(minutes=默认时长分钟)).strftime("%Y-%m-%d %H:%M")
    方式 = d.get("方式") or d.get("way") or "到店量体"
    import rules
    ok, 码, 为何 = rules.validate_appointment({"start": 开始, "end": 结束, "way": 方式}, now=_now(), actor_role=角色)
    if not ok:
        return 拒(码, 为何)
    闭 = _营业时间外(开始)
    if 闭:
        return 拒("CLOSED", 闭)
    with contextlib.closing(_w()) as c:
        import shop_key as SK
        停 = SK.停业理由(c, 行["shop"])
    if 停:
        return 拒("SHOP_INACTIVE", 停)
    import booking
    ok2, 码2, 为何2, 点名列 = booking.校验点名(行["shop"], {"named_advisor_no": d.get("点名工号") or d.get("named_advisor_no"),
                                                       "named_state": d.get("点名三态") or d.get("named_state"),
                                                       "channel": d.get("渠道") or d.get("channel")})
    if not ok2:
        return 拒(码2, 为何2)
    # 顾问:指定了就要是这家店在职的;没指定 → 发起人自己是顾问就是他,否则客户的归属顾问,再没有就空着(店长在待分配池里派)
    adv = None
    指 = d.get("顾问") or d.get("advisor")
    if 指:
        adv = _顾问(api, 指, 店码)
        if not adv:
            return 拒("BAD_ADVISOR", f"「{指}」不是这家店在职的顾问 —— 工号或姓名对一下")
    elif 角色 == "顾问":
        adv = me.get("no")
    else:
        adv = 行.get("advisor_no") or None
    with contextlib.closing(_w()) as c, c:
        n = c.execute("SELECT COUNT(*) FROM appointment").fetchone()[0]
        aid = f"AP{_now():%y%m%d}{n + 1:04d}"
        c.execute("INSERT INTO appointment(id,customer_id,shop,shop_code,advisor_no,start_ts,end_ts,status,named_advisor_no,named_state,channel)"
                  " VALUES(?,?,?,?,?,?,?,'待确认',?,?,?)",
                  (aid, 行["id"], 行["shop"], 店码, adv, 开始, 结束, 点名列["named_advisor_no"], 点名列["named_state"], 点名列["channel"]))
    话 = f"新建预约 {aid},客户 {行['id']},{开始} → {结束}" + (f"(补录:{为何})" if 码 == "BACKFILL" else "")
    _log(me, aid, "新建", "待确认", True, "CREATE", 话)
    return dict(ok=True, code=码 if 码 == "BACKFILL" else "CREATE", id=aid, 客户=行["name"], 门店=行["shop"], 顾问=adv,
                开始=开始, 结束=结束, 状态="待确认",
                reason=f"已建预约 {aid}(状态「待确认」,客户来了在后台点到店)" + (";按补录处理" if 码 == "BACKFILL" else ""))


# ── 改 ─────────────────────────────────────────────────────────────────────
def 编辑(d, me, 记编辑=None):
    """改时间 / 换顾问。d:{预约号, 开始?, 结束?, 顾问?}。只有待确认 / 已预约能改;门店的人只改本店的。
    记编辑:写 edit_log 的回调(server 传它自己的 log_edit;聊天工具不传就用这里的 _记编辑)。"""
    api = _api()
    角色 = (me or {}).get("role")
    aid = str(d.get("预约号") or d.get("id") or d.get("appointment_id") or "").strip()
    def 拒(码, 为何):
        _log(me, aid or "?", "编辑", "拒绝", False, 码, 为何)
        return dict(ok=False, code=码, reason=为何)
    if not (me or {}).get("no"):
        return 拒("NO_LOGIN", "没有身份 —— 改预约要记是谁改的,请先登录")
    a = _rows("SELECT * FROM appointment WHERE id=?", aid)
    if not a:
        return 拒("NO_APPT", f"没有预约 {aid or '(没给预约号)'} —— 先用 list_appointments 查到预约号")
    a = a[0]
    if a["status"] not in 可改的状态:
        return 拒("WRONG_STATE", f"预约已是「{a['status']}」—— 只有 {' / '.join(可改的状态)} 的能改时间;已经发生的事改不了")
    我店 = _我店码(me)
    if 我店 and (a["shop_code"] or "") != 我店:
        return 拒("OTHER_SHOP", "只能改本店的预约 —— 这条预约在别的门店")
    st = _标准时间(d.get("开始") or d.get("start")) or a["start_ts"]
    en = _标准时间(d.get("结束") or d.get("end"))
    if not en:
        # 只给了新开始、没给结束:保持原来的时长
        try:
            长 = _dt.datetime.fromisoformat(a["end_ts"]) - _dt.datetime.fromisoformat(a["start_ts"])
        except Exception:
            长 = _dt.timedelta(minutes=默认时长分钟)
        en = (_dt.datetime.fromisoformat(st) + 长).strftime("%Y-%m-%d %H:%M") if (d.get("开始") or d.get("start")) else a["end_ts"]
    if (st, en) != (a["start_ts"], a["end_ts"]):
        import rules
        ok, 码, 为何 = rules.validate_appointment({"start": st, "end": en, "way": d.get("方式") or d.get("way")}, now=_now(), actor_role=角色)
        if not ok:
            return 拒(码, 为何)
        闭 = _营业时间外(st)
        if 闭:
            return 拒("CLOSED", 闭)
    adv = a["advisor_no"]
    指 = d.get("顾问") or d.get("advisor")
    if 指:
        adv = _顾问(api, 指, a["shop_code"])
        if not adv:
            return 拒("BAD_ADVISOR", f"「{指}」不是这家店在职的顾问")
    新 = dict(start_ts=st, end_ts=en, advisor_no=adv)
    改了 = [{"字段": 字段中文[k], "改前": a[k], "改后": v} for k, v in 新.items() if (a[k] or None) != (v or None)]
    with contextlib.closing(_w()) as c, c:
        c.execute("UPDATE appointment SET start_ts=?,end_ts=?,advisor_no=? WHERE id=?", (st, en, adv, aid))
    _log(me, aid, "编辑", "已保存", True, "UPDATE", "、".join(x["字段"] for x in 改了) or "无改动")
    (记编辑 or _记编辑)(me, aid, 改了)
    return dict(ok=True, code="UPDATE", id=aid, 改了=改了, 原时间=f"{a['start_ts']} → {a['end_ts']}", 新时间=f"{st} → {en}",
                reason=(f"已改:{'、'.join(x['字段'] for x in 改了)}(原 {a['start_ts']} → 现 {st})" if 改了 else "没有改动(也留了一条记录)"))
