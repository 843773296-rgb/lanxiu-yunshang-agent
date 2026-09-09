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

    cust = (_rows("SELECT * FROM customer WHERE phone=? AND archived=0", phone) or [None])[0]
    if not cust:
        return dict(ok=False, code="NO_CUSTOMER",
                    reason="这个手机号还不是我们的客户。第一次来请到店建档,"
                           "或让顾问替你登记 —— 自助预约暂时只对老客开放")

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
                     VALUES(?,'客户预约',?,?,?,?, '有效',?,?,?,?,?)""",
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


def unassigned(shop=None):
    """待分配池:落了单但没派出去的预约任务。

    **这个池子必须是店长首页就能看见的东西。** 它要是藏在二级页面里,
    就和没有一样 —— 待分配池的价值全在「有人每天扫一眼」。
    """
    sql = ("SELECT s.*, c.name customer_name, c.phone, c.advisor bind FROM schedule s "
           "LEFT JOIN customer c ON c.id=s.customer_id "
           "WHERE s.assignee_no IS NULL AND s.status='有效' AND s.type='客户预约'")
    a = []
    if shop: sql += " AND s.shop=?"; a.append(shop)
    return _rows(sql + " ORDER BY s.start_ts", *a)
