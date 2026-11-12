# -*- coding: utf-8 -*-
"""客户预约 → 任务单 → 自动派单。

这条链上的业务事实只有一句话:
    **客户在手机上预约,单子要落到「该负责的那个人」手上。**

难的是「派不出去」的那几种情况。派不出去有四种,长得完全不一样:

    没绑顾问        —— 这个客户从来没人跟进过
    绑的人离职了     —— 人走了,客户没走
    绑的人不在本店   —— 客户换了门店消费,老顾问管不到
    绑的编号查无此人 —— 数据本身坏了

四种都可以「随便找个在职顾问派了」,派完看板上一片绿:每张单都有人负责。
但那个「负责人」是猜出来的,而**猜出来的负责人和真的负责人在库里长得一模一样**。
所以这里的兜底方向是反的:派不出去就**不派**,显式落进待分配池,由店长决定。
宁可看板上挂着 3 张没人认领的单,也不要 3 张挂着错人的单。
"""
from contextlib import closing   # ← 连接要显式关:sqlite3 的 with 只管事务,不关连接(2026-10-29)
import sqlite3, os, datetime

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")


def _rows(sql, *a):
    with closing(sqlite3.connect(DB)) as c, c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


# ── 归属顾问 → 员工 ────────────────────────────────────────────────
#
# ⚠️ **这里原来是一座「两套编号之间的桥」,2026-09-16 拆了。**
#
# 档案里存的曾经是 `"A01 林岚"` 这种显示串,而员工表的主键是工号 ——
# 同一个人两套编号,只能**靠名字连**。那个函数因此要:
#   · 容忍三种写法(`A01 林岚` / `A01` / `林岚`)
#   · 处理「**两个人同名**」——「有两个叫这名字的」和「没有这个人」
#     在派单上后果一样,都不知道派给谁
#
# **那一整套复杂度,全是因为档案里存的是名字。**
# 名字列删掉之后档案里存的就是工号,这座桥不需要了 —— 一次查表就完。
def staff_of_advisor(advisor_no):
    """按工号取员工。取不到返回 None(**不猜**)。"""
    r = _rows("SELECT no,name,role,shop,status,hired_at,updated_by,updated,login_name,fail_count,locked_until,last_login,adv_code,shop_code FROM staff WHERE no=?", (advisor_no or "").strip())  # 列名写死:staff 带 pwd_*,星号会把哈希和盐带出来(backend/staff_cred_check.py 盯着)
    return r[0] if r else None


# ── 派单决策(纯函数,不写库,可以单独测)──────────────────────────
def route(cust):
    """决定这个客户的预约该派给谁。

    返回 (assignee_no 或 None, code, 人话理由)。
    **None 不是失败** —— 是「这张单需要人来分」,是一个正常的结果。
    """
    adv = (cust.get("advisor_no") or "").strip()
    if not adv:
        return None, "NO_BIND", "这个客户还没有归属顾问,单子进待分配池"

    st = staff_of_advisor(adv)
    if not st:
        # ⚠️ **这条现在几乎不该发生** —— 档案里存的是工号,而工号来自员工表。
        # 留着它是因为「几乎不该」和「不可能」是两件事:
        # 员工被删、库被手工改过,都会走到这儿。
        return None, "BAD_BIND", (f"档案写的归属顾问工号是「{adv}」,"
                                  f"而员工表里没有这个人 —— **数据要修**,单子先进待分配池")

    if st.get("status") != "启用":
        return None, "LEFT", (f"归属顾问 {st['name']} 已{st.get('status')},"
                              f"**离职不会把客户一起带走** —— 单子进待分配池,由店长重新指人")

    if cust.get("shop") and st.get("shop") and cust["shop"] != st["shop"]:
        return None, "CROSS_SHOP", (f"客户在 {cust['shop']},归属顾问 {st['name']} 在 {st['shop']} —— "
                                    f"跨店派不了,单子进 {cust['shop']} 的待分配池")

    return st["no"], "BOUND", f"已自动派给归属顾问 {st['name']}"


# ── 客户点名了谁 · 预约渠道(W21,用户 11-12 拍第十二条)─────────────────
#
# **点名 ≠ 派单。** 点名只是记下客户的意愿;派给谁仍由 suggest_why 算、店长确认 ——
# book() 文档里那条「请求里说了不算派给谁」不变。点名在派单建议里是**同层最强**的依据
# (排在接触史前面),不做加权打分(09-20 拍的「分层排序、不做加权总分」)。
#
# 三态单独一列,因为「工号空」同时可能是「没点」和「不详」:
#     点名  客户说了要谁            没点  问过了,谁都行            不详  没问 / 没说清
# 库上有 CHECK 挡非法值(tools/migrate_appt_columns.py / seed.py);这里是写入口那一道,
# 两道叠加 —— 库那道挡的是绕开写入口的写。
点名三态 = ("点名", "没点", "不详")
渠道最长 = 20


def 校验点名(shop, d, 对外=False):
    """写预约前校验「点名谁 / 点名三态 / 渠道」三个可选字段。

    → (ok, code, reason, 列值)。列值是 {named_advisor_no, named_state, channel},直接写库。

    · 三态只认 点名 / 没点 / 不详;没给三态时:给了工号 → 点名,都没给 → 不详(**没问就是不详,不猜成没点**)
    · 点名了却没给人、给了人却说没点 → 拒(自相矛盾,不替他挑一边)
    · 点名的工号必须是**这家店的在职顾问**,否则拒并说清是哪一种
    · `对外=True`(顾客自助预约那个不登录的口):拒的理由不分「离职 / 别的店 / 查无此人」——
      分开说等于让匿名请求逐个试出谁在哪家店上班
    """
    no = str(d.get("named_advisor_no") or "").strip()
    st = str(d.get("named_state") or "").strip()
    ch = str(d.get("channel") or "").strip() or None
    if st and st not in 点名三态:
        return False, "BAD_NAMED_STATE", f"「客户点名了没有」只认 {' / '.join(点名三态)},收到的是「{st}」", None
    if not st:
        st = "点名" if no else "不详"
    if st == "点名" and not no:
        return False, "NAMED_NO_ADVISOR", "选了「点名」但没说点的是谁 —— 填上那位顾问,或改成「没点 / 不详」", None
    if st != "点名" and no:
        return False, "NAMED_STATE_CONFLICT", f"填了点名的顾问,三态却是「{st}」—— 两者对不上,改一边", None
    if ch and len(ch) > 渠道最长:
        return False, "BAD_CHANNEL", f"预约渠道太长了(最多 {渠道最长} 个字)", None
    if no:
        import shop_key as _SK
        with closing(sqlite3.connect(DB)) as c:
            c.row_factory = sqlite3.Row
            r = c.execute("SELECT no,name,role,status,shop FROM staff WHERE no=?", (no,)).fetchone()
            _片, _参 = _SK.门店条件(c, shop) if shop else ("", [])
            本店 = bool(r) and bool(_片) and c.execute(
                f"SELECT 1 FROM staff WHERE no=? AND {_片}", (no, *_参)).fetchone() is not None
        if not (r and r["role"] == "顾问" and r["status"] == "启用" and 本店):
            if 对外:
                why = "点名的顾问不是这家店的在职顾问,换一位或者不点名"
            elif not r:
                why = f"点名的工号「{no}」员工表里没有"
            elif r["role"] != "顾问":
                why = f"点名的 {r['name']} 是{r['role']},不是顾问"
            elif r["status"] != "启用":
                why = f"点名的 {r['name']} 已{r['status']} —— 不在职的人接不了待"
            else:
                why = f"点名的 {r['name']} 在 {r['shop']},不是这家店({shop or '未填门店'})的顾问"
            return False, "BAD_NAMED_ADVISOR", why, None
    return True, "OK", "", dict(named_advisor_no=no or None, named_state=st, channel=ch)


# ── 手机端自助预约 ──────────────────────────────────────────────────
MAX_PENDING = 3          # 同一个手机号最多挂 3 张没做完的预约
OPEN_HOUR = (10, 21)     # 门店营业时间,预约只能落在这个区间


def _now():
    """**世界的当下**,不是机器的当下。

    ⚠️ 这里原来是 `datetime.datetime.now()`。后果不是「差一天」那么简单:
    它写出来的 `schedule.assigned_at` 落在**机器**的今天,而演示世界停在别的日子;
    然后每日平移把这条记录**跟着往后挪** —— 于是它落到世界的未来,
    而且**平移每跑一次就多推一天,永远不会自愈**。
    2026-09-26 被门禁 C4 抓到(SC7002 的派单时间跑到了 09-27)。
    """
    import worldclock
    return worldclock.当下()


def book(d):
    """客户在手机上自助预约。

    **这是系统里唯一一个不需要登录的写接口** —— 客户没有员工账号,
    要求他登录就等于要求他先注册,而人是不会为了约个量体去注册的。
    代价是这个口子对外敞着,所以它自己得带三道闸:
      ① 手机号格式 + 时间必须在营业时间内、不能是过去
      ② 同一个号最多挂 3 张未完成的预约(挡住连点和刷单)
      ③ **它只能建预约,建不了别的**;派给谁由 route() 定,请求里说了不算

    ③ 最要紧:如果让请求体带 advisor,那随便谁都能把单子塞进任意顾问的列表里。

    请求可以带「点名谁 / 点名三态 / 渠道」(W21)—— **点名只记意愿,不改派单**:
    派给谁照旧由 route() 定、落池的由 suggest_why 出建议、店长确认。点名的人必须是本店在职顾问。
    """
    phone = "".join(ch for ch in (d.get("phone") or "") if ch.isdigit())
    if len(phone) != 11 or not phone.startswith("1"):
        return dict(ok=False, code="BAD_PHONE", reason="手机号填 11 位")

    when = (d.get("when") or "").replace("T", " ").strip()
    try:
        t = datetime.datetime.fromisoformat(when)
    except ValueError:
        return dict(ok=False, code="BAD_TIME", reason="到店时间没填对")
    if t < _now():
        return dict(ok=False, code="PAST", reason="到店时间已经过去了,换一个")
    if not (OPEN_HOUR[0] <= t.hour < OPEN_HOUR[1]):
        return dict(ok=False, code="CLOSED",
                    reason=f"门店 {OPEN_HOUR[0]}:00–{OPEN_HOUR[1]}:00 营业,这个点没人接待")

    hits = _rows("SELECT * FROM customer WHERE phone=? AND archived=0 ORDER BY created", phone)
    if not hits:
        return dict(ok=False, code="NO_CUSTOMER",
                    reason="这个手机号还不是我们的客户。第一次来请到店建档,"
                           "或让顾问替你登记 —— 自助预约暂时只对老客开放")
    if len(hits) > 1:
        # **一个手机号对应多条在用档案。** 库里现在有 16 个这样的号 ——
        # 那正是「客户合并」要处理的场景(同一个人在两家店各建了一次档)。
        #
        # 上一版直接取 `[0]`,后果不是报错,是**单子落到另一条档案的顾问手上** ——
        # 跨店、错人,而客户那头看起来一切正常,直到当天有人问「谁来接待我」。
        # **「查到一条」和「查到多条只取了第一条」返回的东西长得一模一样。**
        #
        # 兜底方向:不猜。取**最早建档**的那条(主档口径和客户合并一致:
        # 「保留下单记录较早的那条为主档」),但**把这件事说出来**并记进台账,
        # 让店里知道这个号该合并了。
        cust = hits[0]
        _flag_dup(phone, hits)
    else:
        cust = hits[0]

    pend = _rows("SELECT id FROM schedule WHERE customer_id=? AND type='客户预约' AND status='有效'",
                 cust["id"])
    if len(pend) >= MAX_PENDING:
        return dict(ok=False, code="TOO_MANY",
                    reason=f"你还有 {len(pend)} 个预约没完成,先完成或取消一个再约")

    ok_n, code_n, why_n, 点名列 = 校验点名(cust.get("shop"), d, 对外=True)
    if not ok_n:
        return dict(ok=False, code=code_n, reason=why_n)
    if not 点名列["channel"]:
        点名列["channel"] = "手机端自助"      # 这个口子本身就是一个渠道,不填也知道

    need = (d.get("need") or "").strip() or "到店咨询"
    assignee, code, why = route(cust)

    end = t + datetime.timedelta(hours=1)
    n = _rows("SELECT COUNT(*) c FROM appointment")[0]["c"]
    aid = f"AP{_now():%y%m%d}{n + 1:04d}"
    m = _rows("SELECT COUNT(*) c FROM schedule")[0]["c"]
    sid = f"SC{7000 + m + 1}"
    # ⚠️ **工号也要写。** 原来这两条 INSERT **只写名字不写工号** ——
    # 而名字是 `staff` 的副本,工号才是引用。
    # 这条路径在门禁里没被走过(门禁跑的是静态种子数据),
    # 所以 `advisor_ref_check` 一直绿着,而它每建一条预约就产出一行
    # **有名字没工号**的记录。删掉名字列的话,那一行就彻底没有顾问了。
    adv_no = cust.get("advisor_no") if code == "BOUND" else None

    with closing(sqlite3.connect(DB)) as c, c:
        # 预约单(客户视角:我约了几点)
        import shop_key as _SK          # 门店码的唯一入口
        c.execute("INSERT INTO appointment(id,customer_id,shop,shop_code,advisor_no,"
                  "start_ts,end_ts,status,named_advisor_no,named_state,channel) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (aid, cust["id"], cust.get("shop"), _SK.码(c, cust.get("shop")), adv_no,
                   t.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"), "待确认",
                   点名列["named_advisor_no"], 点名列["named_state"], 点名列["channel"]))
        # 任务单(门店视角:谁去接待)—— **两张表是两个视角,不是冗余**:
        # 客户取消预约,任务单要留痕说明为什么白排了一小时。
        c.execute("""INSERT INTO schedule(id,type,advisor_no,customer_id,
                     start_ts,end_ts,
                     status,shop,shop_code,assignee_no,assigned_by,assigned_at,note)
                     VALUES(?,'预约到店',?,?,?,?, '有效',?,?,?,?,?,?)""",
                  (sid, adv_no, cust["id"],
                   t.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"),
                   cust.get("shop"), _SK.码(c, cust.get("shop")), assignee,
                   "SYS" if assignee else None,          # 派单人是系统,不是某个人
                   _now().strftime("%Y-%m-%d %H:%M") if assignee else None,
                   f"{need}(客户 {cust['name']} 手机端自助预约 {aid})"))
    return dict(ok=True, code=code, appt=aid, task=sid,
                customer=cust["name"], shop=cust.get("shop"),
                assigned=bool(assignee), reason=why,
                when=t.strftime("%Y-%m-%d %H:%M"))


def _flag_dup(phone, hits):
    """一个号多条档案 —— 记一笔,让它能被看见。

    **不报错、不拦下单**:客户没做错任何事,不该因为门店的档案没合并而约不上。
    但也不能不吭声 —— 不吭声的话这个号会一直派给同一条档案的顾问,
    而另一条档案上的历史(量体、订单、偏好)永远用不上。
    """
    try:
        from oplog import log_op
        log_op("SYS", "customer", hits[0]["id"], "—", "—", True, "DUP_PHONE",
               f"手机号 {phone[:3]}****{phone[-4:]} 有 {len(hits)} 条在用档案:"
               f"{[h['id'] + '/' + (h.get('shop') or '') for h in hits]};"
               f"本次按最早建档的 {hits[0]['id']} 派单 —— **这个号该走客户合并**",
               {"phone_tail": phone[-4:], "ids": [h["id"] for h in hits]})
    except Exception as e:
        # 预约照常放行(客户没做错事),但**台账写不进这件事不能也不吭声** —— 原来这里是 `pass`,
        # 和上面「不能不吭声」那句本意正相反(10-19 数据工厂核出来的)。至少落进服务日志
        import sys as _s
        print(f"⚠️ 一号多档没记进台账({type(e).__name__}: {e}):{[h['id'] for h in hits]} 该走客户合并",
              file=_s.stderr)


def unassigned(shop=None):
    """待分配池:落了单但没派出去的预约任务。

    **这个池子必须是店长首页就能看见的东西。** 它要是藏在二级页面里,
    就和没有一样 —— 待分配池的价值全在「有人每天扫一眼」。
    """
    import tasktypes as _tt
    sql = ("SELECT s.*, c.name customer_name, c.phone, c.advisor_no bind FROM schedule s "
           "LEFT JOIN customer c ON c.id=s.customer_id "
           "WHERE s.assignee_no IS NULL AND s.status='有效' "
           # 客户族有四种类型,不能只认「预约到店」。
           # 而且类型清单要从 tasktypes 取 —— 这里写死一份就是第二个来源。
           "AND s.type IN (%s)" % ",".join("?" * len(_tt.CUSTOMER_TYPES)))
    a = list(_tt.CUSTOMER_TYPES)
    if shop:
        # 按门店码筛 —— 改过名之后按串筛会「一条待分派都没有」,而那看着像活都派完了
        import shop_key as _SK
        with closing(sqlite3.connect(DB)) as _c, _c:
            _片, _参 = _SK.门店条件(_c, shop, "s")
        if _片:
            sql += f" AND {_片}"; a.extend(_参)
    out = _rows(sql + " ORDER BY s.start_ts", *a)
    # 每条现算一个建议。**现算不存库** —— 存下来的建议会变味(人离职了、
    # 负载变了),而且从存下到店长确认之间,库里那张单看起来已经有人负责了。
    for r in out:
        r["建议"], r["提不出的原因"] = suggest_why(r)
    return out


# ── agent 建议:算得出「谁最合适」,但算出来的不是决定 ────────────────
def _busy(no, start, end):
    """这个顾问在这个时间段上有没有别的活。"""
    if not (start and end): return []
    return _rows("SELECT id,start_ts,end_ts,note FROM schedule "
                 "WHERE assignee_no=? AND status='有效' "
                 "AND start_ts < ? AND end_ts > ?", no, end, start)


# 派单任务(schedule)对上预约(appointment):**按 客户号 + 开始时间(到分钟)对**。
#
# 为什么不用 schedule.ref_id:客户族任务的 ref_id **按类型约定装客户号**(tasktypes.REF_SOURCE
# 那张表:「类型决定它是哪种单」),往里写预约号会让 resolve_ref 解不出客户;而库里现存 38 条
# 「预约到店」的 ref_id 全是空的。不新加一列,因为用户这次只拍了三列。
# book() 两张表的客户号和开始时间是**同一个变量**写进去的,所以这条路对新单是精确的;
# 只认还在走的预约(取消 / 过期 / 爽约 / 已完成的不算)—— 库里历史预约有 367 组「同客户同时刻」重复,
# 全落在已完成那些里,活着的这几态里 0 组。对上多条而点名不一致时**不猜**,当作没点名并说出来。
活着的预约态 = ("待确认", "已预约", "已到店")


def 任务的点名(task):
    """→ (点名 dict 或 None, 说明或 None)。点名 dict = {appt, no, name}。只有三态是「点名」才返回 dict。"""
    cid, start = task.get("customer_id"), task.get("start_ts")
    if not (cid and start):
        return None, None
    try:
        rs = _rows("SELECT a.id,a.named_state,a.named_advisor_no,s.name FROM appointment a "
                   "LEFT JOIN staff s ON s.no=a.named_advisor_no "
                   "WHERE a.customer_id=? AND substr(a.start_ts,1,16)=substr(?,1,16) "
                   f"AND a.status IN ({','.join('?' * len(活着的预约态))})", cid, start, *活着的预约态)
    except sqlite3.OperationalError as e:
        if "named_" not in str(e):
            raise
        # 库还没跑 tools/migrate_appt_columns.py —— 店长首页的待分配池不能因此整页挂掉
        return None, "库里还没有点名列(迁移没跑),这次没按点名排"
    点 = {(r["named_advisor_no"], r["name"]) for r in rs if r["named_state"] == "点名" and r["named_advisor_no"]}
    if not 点:
        return None, None
    if len(点) > 1:
        return None, (f"这个时段对上了 {len(rs)} 条预约、点名的人不一致"
                      f"({'、'.join(n or k for k, n in sorted(点))})—— 不猜,这次没按点名排")
    no, name = 点.pop()
    return dict(appt=[r["id"] for r in rs if r["named_advisor_no"] == no][0], no=no, name=name or no), None


新人保底条数 = 2          # 建议值(台账第十五条),试点后按数据调
新人天数 = 90


def _新人保底(pool, start):
    """→ {工号: 本周已有新客数} —— 只含「入职不满三个月且本周新客 < 保底条数」的人。
    新客 = 这条日程的客户在它之前没有任何日程(谁接待的都算);周按任务开始那天算,没时段按世界今天。"""
    import datetime as _dt, worldclock as _wc
    今 = _wc.今天()
    d = _dt.date.fromisoformat(start[:10]) if start else 今
    周一 = d - _dt.timedelta(days=d.weekday())
    下周一 = 周一 + _dt.timedelta(days=7)
    出 = {}
    for p in pool:
        r = _rows("SELECT hired_at FROM staff WHERE no=?", p["no"])
        入职 = (r[0]["hired_at"] if r else None) or ""
        try:
            新人 = (今 - _dt.date.fromisoformat(入职[:10])).days < 新人天数
        except ValueError:
            新人 = False
        if not 新人:
            continue
        k = _rows("SELECT COUNT(*) c FROM schedule s WHERE s.assignee_no=? AND s.customer_id IS NOT NULL "
                  "AND s.start_ts >= ? AND s.start_ts < ? AND NOT EXISTS (SELECT 1 FROM schedule q "
                  "WHERE q.customer_id=s.customer_id AND q.start_ts < s.start_ts)",
                  p["no"], 周一.isoformat(), 下周一.isoformat())[0]["c"]
        if k < 新人保底条数:
            出[p["no"]] = k
    return 出


def suggest(task):
    """给一张没派出去的客户任务提一个人选 —— 提不出返回 None。要知道**为什么**提不出,用 suggest_why。"""
    return suggest_why(task)[0]


def _排班过滤(pool, shop, start, end):
    """排班层的硬过滤(用户 11-11 夜:派单要查在不在班,和店长排班一起做)。
    → (留下的人, 排除了谁及原因, 整周没发布时的原因或 None)。没有时段的任务不过滤(判不了)。

    · 那一周本店排班**没发布**(没排 / 只有草稿)→ 不出推荐(用户拍:提示先排班,店长可手动指定)
    · 那个时段不在班(休息 / 请假 / 早班的人晚上 / 草稿)→ 出局,这是 D2「时段有空」硬条件的另一半
    · 那天被预留给点名的客户了 → 出局
    """
    if not start:
        return pool, {}, None
    import roster as _R, datetime as _dt
    d = _dt.date.fromisoformat(start[:10])
    周一 = (d - _dt.timedelta(days=d.weekday())).isoformat()
    发了, _ = _R.一周排了吗(shop, 周一, db=DB)      # 显式带库:roster 的默认 db 在定义时就定死了
    if not 发了:
        return [], {}, (f"{周一} 那一周本店的排班还没发布(没排或只有草稿)—— 不出推荐:"
                        f"按没发布的排班推荐,店长一改,单就挂在错的人身上。请先把那周的班排好发布;"
                        f"急的话可以手动指定一个人")
    留, 出局 = [], {}
    for p in pool:
        ok, 码, why = _R.时段在班(p["no"], start, end or start, db=DB)
        if not ok:
            出局[p["no"]] = why; continue
        占, why2 = _R.时段被预留了吗(p["no"], start, db=DB)
        if 占:
            出局[p["no"]] = why2; continue
        留.append(p)
    return 留, 出局, None


def suggest_why(task):
    """给一张没派出去的客户任务提一个人选,**并且说清楚凭什么**。→ (建议 dict 或 None, 提不出的原因)

    依据按强弱排,强的先用 —— 强弱不是修辞,是「店长凭这条能不能一眼点头」:

      ① 这个客户以前谁接待过     —— 客户认识他,他也知道上次聊到哪儿。最强。
      ② 那个时间段谁有空         —— 排除硬冲突。这条是**否决项**,不是加分项。
      ③ 谁手上的活最少           —— 只在前两条分不出时用。它公平,但和这个客户无关。

    **建议不写库。** 写库的话,从 agent 写下到店长点确认之间,这张单看起来
    已经有人负责了,而实际上没有任何人看过它。而且存下来的建议会变味:
    顾问离职了、负载变了,昨天的建议今天就是错的。所以每次现算,
    确认那一刻再算一次,把「建议谁 / 店长选了谁」一起记进台账。

    返回 None 表示**提不出建议** —— 这是一个正常结果,不是错误。
    店里没有在职顾问时硬凑一个人出来,比说「提不出」有害得多。
    """
    shop = task.get("shop")
    # 按门店码筛 —— 改过名之后按串筛会「店里没有在职顾问」,
    # 而那条路返回的是「提不出建议」:**一个正常结果**,所以没人会发现它坏了。
    import shop_key as _SK
    with closing(sqlite3.connect(DB)) as _c, _c:
        _片, _参 = _SK.门店条件(_c, shop)
    pool = _rows(f"SELECT no,name,adv_code FROM staff "
                 f"WHERE role='顾问' AND status='启用' AND {_片 or '1=0'} ORDER BY no", *_参)
    if not pool:
        return None, "这个门店没有在职顾问可派"

    cid = task.get("customer_id")
    start, end = task.get("start_ts"), task.get("end_ts")
    # 排班层先过:**不在班的人不进候选**(D2「时段有空」是硬条件,排班是它的另一半)
    在职池 = {p["no"] for p in pool}
    pool, 不在班, 没发布 = _排班过滤(pool, shop, start, end)
    if 没发布:
        return None, 没发布
    if not pool:
        名 = {r["no"]: r["name"] for r in _rows("SELECT no,name FROM staff")}
        return None, ("那个时段本店没有在班的顾问 —— " +
                      ";".join(f"{名.get(k, k)}:{v}" for k, v in list(不在班.items())[:5]))

    # ① 接触史:这个客户以前被谁服务过(日程 + 跟进都算)
    seen = {}
    if cid:
        for r in _rows("SELECT assignee_no no,COUNT(*) n FROM schedule "
                       "WHERE customer_id=? AND assignee_no IS NOT NULL GROUP BY assignee_no", cid):
            seen[r["no"]] = seen.get(r["no"], 0) + r["n"]

    # ② 时段冲突:有冲突的直接出局
    free, clash = [], {}
    for p in pool:
        b = _busy(p["no"], start, end)
        (clash.setdefault(p["no"], b) if b else None)
        if not b: free.append(p)
    cands = free or pool          # 全都冲突时不弃权,但要在理由里说出来

    # ⓪ 客户点名(W21,用户 11-12 拍):点名的人在班、没被预留、那个时段没别的活 → **同层最强,直接推荐他**;
    #    没空 → 调 roster.点名的人没空 拿业务定的三步给人看(**不替客户选**:换人还是改时间由客户定),
    #    下面照常排出来的人选是「换人接待」时的备选。不做加权:点名只是排序键最前面那一位。
    点名, 点名说明 = 任务的点名(task)
    点名可派 = None
    if 点名:
        if any(p["no"] == 点名["no"] for p in free):
            点名可派 = 点名["no"]
            点名.update(可派=True)
        else:
            import roster as _R
            # 排班层不在班 → 不传原因,让 roster 自己判(码带 OUT_OF_SHIFT / OFF 之类);
            # 在班却出局的(那天被预留给别的客户)、有别的活、不在本店了 → 原因在排班层之外,传进去
            if 点名["no"] in 不在班:
                没空因 = (None if not _R.时段在班(点名["no"], start, end or start, db=DB)[0]
                        else 不在班[点名["no"]])
            else:
                没空因 = (("那个时段已经有别的安排(" + "、".join(b["id"] for b in clash.get(点名["no"], [])) + ")"
                        if clash.get(点名["no"]) else None)
                    or (None if 点名["no"] in 在职池 else "已不是本店在职顾问"))
            能, 码, 三步 = _R.点名的人没空(dict(id=cid), 点名["no"], start, end or start,
                                       db=DB, 没空的原因=没空因)
            点名.update(可派=False, 码=码, 三步=三步)

    # ③ 负载:手上还有几件没做完
    load = {p["no"]: _rows("SELECT COUNT(*) c FROM schedule "
                           "WHERE assignee_no=? AND status='有效'", p["no"])[0]["c"]
            for p in pool}

    # ④ 新人保底(用户 11-12 拍,台账第十五条):**只在新客单上**(这个客户谁都没接触过)起作用 ——
    #    入职不满三个月、本周新客还不到「保底条数」的顾问,排到同层最前。有接触史的单照旧谁接待过给谁,
    #    不改 09-20 拍的「分层排序、不做加权总分」。保底条数 2 是**建议值**,试点后按数据调。
    保底 = _新人保底(pool, start) if not (seen or 点名可派) else {}

    def rank(p):
        return (0 if p["no"] == 点名可派 else 1, -seen.get(p["no"], 0), 0 if p["no"] in 保底 else 1,
                load[p["no"]], p["no"])

    cands = sorted(cands, key=rank)
    pick = cands[0]

    why = []
    n = seen.get(pick["no"], 0)
    if 点名 and 点名["可派"] and pick["no"] == 点名["no"]:
        why.append(f"客户点名了 {点名['name']}(预约 {点名['appt']}),他那个时段在班、没有别的安排 —— 直接推荐他")
    elif 点名:
        why.append(f"⚠️ 客户点名了 {点名['name']},但他那个时段没空 —— 按下面三步跟客户谈;"
                   f"这里推荐的是「换人接待」时的人选,**不替客户决定**")
    if 点名说明:
        why.append(点名说明)
    if pick["no"] in 保底:
        why.append(f"新人保底:{pick['name']} 入职不满三个月,本周新客才 {保底[pick['no']]} 条(保底每周 {新人保底条数} 条,建议值)")
    if n:
        why.append(f"这个客户以前由 {pick['name']} 接待过 {n} 次 —— 他知道上次聊到哪儿")
    elif pick["no"] != 点名可派:
        why.append(f"这个客户没有接触史,{pick['name']} 手上活最少({load[pick['no']]} 件在办)")
    if 不在班:
        名 = {r["no"]: r["name"] for r in _rows("SELECT no,name FROM staff")}
        why.append("不在班、已排除:" + "、".join(名.get(k, k) for k in 不在班))
    if not free:
        why.append("⚠️ 这个时间段**在班的顾问都有别的活**,选出来的这位也冲突,请确认能不能挪")
    elif clash:
        who = [p["name"] for p in pool if clash.get(p["no"])]
        why.append(f"{'、'.join(who)} 在这个时间段已经有别的安排,已排除")
    if len(cands) > 1 and rank(cands[0])[:3] == rank(cands[1])[:3]:
        why.append(f"⚠️ {pick['name']} 和 {cands[1]['name']} 依据完全一样 —— "
                   f"**这一条是按工号先后挑的,不是算出来的**,请你来定")

    return dict(no=pick["no"], name=pick["name"], why=why,
                点名=点名,
                不在班={k: v for k, v in 不在班.items()},
                load=load[pick["no"]], history=n,
                alts=[dict(no=p["no"], name=p["name"], load=load[p["no"]],
                           history=seen.get(p["no"], 0),
                           busy=bool(clash.get(p["no"]))) for p in cands[1:4]]), None
