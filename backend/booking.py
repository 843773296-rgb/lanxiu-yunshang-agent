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
import sqlite3, os, datetime

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")


def _rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


# ── 两套编号之间的桥 ────────────────────────────────────────────────
def staff_of_advisor(advisor):
    """把客户档案里的「归属顾问」换成员工。

    档案里存的历来是 `"A01 林岚"` 这种显示串,员工表的主键是工号 `60000002`。
    **这是同一个人的两套编号**,以前只能靠名字连 —— 名字既不唯一也会改。
    现在花名册上有 adv_code,这个函数是两套编号之间**唯一**的桥。

    容忍三种写法:"A01 林岚" / "A01" / "林岚"。
    容忍不是宽容,是因为库里这三种真的都存在过;但**新写入一律用 A 号**。
    """
    s = (advisor or "").strip()
    if not s: return None
    code = s.split(" ", 1)[0]
    r = _rows("SELECT * FROM staff WHERE adv_code=?", code)
    if r: return r[0]
    # 退化到按姓名 —— 查到**多个同名**就当作查不到。
    # 「有两个人叫这个名字」和「没有人叫这个名字」在派单这件事上后果一样:
    # 都不知道该派给谁。返回一个是瞎猜。
    name = s.split(" ", 1)[-1]
    r = _rows("SELECT * FROM staff WHERE name=? AND role='顾问'", name)
    return r[0] if len(r) == 1 else None


# ── 派单决策(纯函数,不写库,可以单独测)──────────────────────────
def route(cust):
    """决定这个客户的预约该派给谁。

    返回 (assignee_no 或 None, code, 人话理由)。
    **None 不是失败** —— 是「这张单需要人来分」,是一个正常的结果。
    """
    adv = (cust.get("advisor") or "").strip()
    if not adv:
        return None, "NO_BIND", "这个客户还没有归属顾问,单子进待分配池"

    st = staff_of_advisor(adv)
    if not st:
        return None, "BAD_BIND", f"档案写的归属顾问是「{adv}」,但员工表里对不上人 —— 数据要修,单子先进待分配池"

    if st.get("status") != "启用":
        return None, "LEFT", (f"归属顾问 {st['name']} 已{st.get('status')},"
                              f"**离职不会把客户一起带走** —— 单子进待分配池,由店长重新指人")

    if cust.get("shop") and st.get("shop") and cust["shop"] != st["shop"]:
        return None, "CROSS_SHOP", (f"客户在 {cust['shop']},归属顾问 {st['name']} 在 {st['shop']} —— "
                                    f"跨店派不了,单子进 {cust['shop']} 的待分配池")

    return st["no"], "BOUND", f"已自动派给归属顾问 {st['name']}"


# ── 手机端自助预约 ──────────────────────────────────────────────────
MAX_PENDING = 3          # 同一个手机号最多挂 3 张没做完的预约
OPEN_HOUR = (10, 21)     # 门店营业时间,预约只能落在这个区间


def _now(): return datetime.datetime.now()


def book(d):
    """客户在手机上自助预约。

    **这是系统里唯一一个不需要登录的写接口** —— 客户没有员工账号,
    要求他登录就等于要求他先注册,而人是不会为了约个量体去注册的。
    代价是这个口子对外敞着,所以它自己得带三道闸:
      ① 手机号格式 + 时间必须在营业时间内、不能是过去
      ② 同一个号最多挂 3 张未完成的预约(挡住连点和刷单)
      ③ **它只能建预约,建不了别的**;派给谁由 route() 定,请求里说了不算

    ③ 最要紧:如果让请求体带 advisor,那随便谁都能把单子塞进任意顾问的列表里。
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

    need = (d.get("need") or "").strip() or "到店咨询"
    assignee, code, why = route(cust)

    end = t + datetime.timedelta(hours=1)
    n = _rows("SELECT COUNT(*) c FROM appointment")[0]["c"]
    aid = f"AP{_now():%y%m%d}{n + 1:04d}"
    m = _rows("SELECT COUNT(*) c FROM schedule")[0]["c"]
    sid = f"SC{7000 + m + 1}"
    adv_disp = cust.get("advisor") if code == "BOUND" else None

    with sqlite3.connect(DB) as c:
        # 预约单(客户视角:我约了几点)
        c.execute("INSERT INTO appointment(id,customer_id,shop,advisor,start_ts,end_ts,status) "
                  "VALUES(?,?,?,?,?,?,?)",
                  (aid, cust["id"], cust.get("shop"), adv_disp,
                   t.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"), "待确认"))
        # 任务单(门店视角:谁去接待)—— **两张表是两个视角,不是冗余**:
        # 客户取消预约,任务单要留痕说明为什么白排了一小时。
        c.execute("""INSERT INTO schedule(id,type,advisor,customer_id,start_ts,end_ts,
                     status,shop,assignee_no,assigned_by,assigned_at,note)
                     VALUES(?,'预约到店',?,?,?,?, '有效',?,?,?,?,?)""",
                  (sid, adv_disp, cust["id"],
                   t.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"),
                   cust.get("shop"), assignee,
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
    except Exception:
        pass


def unassigned(shop=None):
    """待分配池:落了单但没派出去的预约任务。

    **这个池子必须是店长首页就能看见的东西。** 它要是藏在二级页面里,
    就和没有一样 —— 待分配池的价值全在「有人每天扫一眼」。
    """
    import tasktypes as _tt
    sql = ("SELECT s.*, c.name customer_name, c.phone, c.advisor bind FROM schedule s "
           "LEFT JOIN customer c ON c.id=s.customer_id "
           "WHERE s.assignee_no IS NULL AND s.status='有效' "
           # 客户族有四种类型,不能只认「预约到店」。
           # 而且类型清单要从 tasktypes 取 —— 这里写死一份就是第二个来源。
           "AND s.type IN (%s)" % ",".join("?" * len(_tt.CUSTOMER_TYPES)))
    a = list(_tt.CUSTOMER_TYPES)
    if shop: sql += " AND s.shop=?"; a.append(shop)
    out = _rows(sql + " ORDER BY s.start_ts", *a)
    # 每条现算一个建议。**现算不存库** —— 存下来的建议会变味(人离职了、
    # 负载变了),而且从存下到店长确认之间,库里那张单看起来已经有人负责了。
    for r in out:
        r["建议"] = suggest(r)
    return out


# ── agent 建议:算得出「谁最合适」,但算出来的不是决定 ────────────────
def _busy(no, start, end):
    """这个顾问在这个时间段上有没有别的活。"""
    if not (start and end): return []
    return _rows("SELECT id,start_ts,end_ts,note FROM schedule "
                 "WHERE assignee_no=? AND status='有效' "
                 "AND start_ts < ? AND end_ts > ?", no, end, start)


def suggest(task):
    """给一张没派出去的客户任务提一个人选,**并且说清楚凭什么**。

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
    pool = _rows("SELECT no,name,adv_code FROM staff "
                 "WHERE role='顾问' AND status='启用' AND shop=? ORDER BY no", shop)
    if not pool:
        return None

    cid = task.get("customer_id")
    start, end = task.get("start_ts"), task.get("end_ts")

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

    # ③ 负载:手上还有几件没做完
    load = {p["no"]: _rows("SELECT COUNT(*) c FROM schedule "
                           "WHERE assignee_no=? AND status='有效'", p["no"])[0]["c"]
            for p in pool}

    def rank(p):
        return (-seen.get(p["no"], 0), load[p["no"]], p["no"])

    cands = sorted(cands, key=rank)
    pick = cands[0]

    why = []
    n = seen.get(pick["no"], 0)
    if n:
        why.append(f"这个客户以前由 {pick['name']} 接待过 {n} 次 —— 他知道上次聊到哪儿")
    else:
        why.append(f"这个客户没有接触史,{pick['name']} 手上活最少({load[pick['no']]} 件在办)")
    if not free:
        why.append("⚠️ 这个时间段**所有在职顾问都有别的活**,选出来的这位也冲突,请确认能不能挪")
    elif clash:
        who = [p["name"] for p in pool if clash.get(p["no"])]
        why.append(f"{'、'.join(who)} 在这个时间段已经有别的安排,已排除")
    if len(cands) > 1 and rank(cands[0])[:2] == rank(cands[1])[:2]:
        why.append(f"⚠️ {pick['name']} 和 {cands[1]['name']} 依据完全一样 —— "
                   f"**这一条是按工号先后挑的,不是算出来的**,请你来定")

    return dict(no=pick["no"], name=pick["name"], why=why,
                load=load[pick["no"]], history=n,
                alts=[dict(no=p["no"], name=p["name"], load=load[p["no"]],
                           history=seen.get(p["no"], 0),
                           busy=bool(clash.get(p["no"]))) for p in cands[1:4]])
