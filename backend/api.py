#!/usr/bin/env python3
"""只读数据接口 —— 这就是 agent 的工具层。

铁律:truth 表绝不通过任何接口暴露。评测比对在 agent 之外做。
"""
import sqlite3, os, json, sys, re
import datetime as _dt
DB=os.path.join(os.path.dirname(os.path.abspath(__file__)),"lanxiu.db")

# ── 两道结构锁 ──────────────────────────────────────────────────────────
# 这两条原来都是**约定**:靠「这里没人写 INSERT」和「这里没人 JOIN truth」守着。
# 边界审计的结论是:**靠人不写的边界不是边界** —— 换个人、隔三个月就会破,
# 而且破了不会报错,只会安静地多一个写接口 / 多一条泄漏路径。
#
# 锁一:连接开成只读。任何写操作直接抛 OperationalError,而不是碰巧没人写。
# 锁二:任何提到 truth 的 SQL 一律拒绝执行 —— **不看语句形状**。
#       原来的检查是 `re.findall(r'FROM\s+(\w+)', 源码)`,只认 `FROM truth`;
#       写成 `JOIN truth u ON …` 就完全查不到(ops.py 里正是这么写的)。
#       静态扫源码永远追不上语句写法,所以改成运行时拦。
_TRUTH = re.compile(r"\btruth\b", re.I)
# 锁三:**凭据字段和 truth 表同等对待。**
# 密码哈希与盐拿到手就能离线爆破,所以工具层连读都不许读 ——
# 不是「模型不该查」,是「查了会抛异常」。
# 顺带禁掉 `SELECT * FROM account`:星号会把 pwd_* 一起带出来,
# **一个没写清楚的星号,就能把前面两道锁绕过去。**
# 语句文本只是**快速失败**;真正的锁在下面「查返回的列名」——
# `select a.* from account a join …` 这种带别名的星号,正则永远追不完。
# **别枚举语句形状,去看结果长什么样** —— truth 那次已经教过一遍了。
_CRED = re.compile(r"pwd_(hash|salt|algo)", re.I)

def _c():
    c=sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory=sqlite3.Row; return c

_CRED_MSG = ("账户凭据(密码哈希 / 盐)**不允许经工具层访问** —— 拿到哈希和盐就能离线爆破。\n"
             "查账户请把列名写清楚(id / phone / login_name / status),对外只给脱敏手机号。\n"
             "见 backend/boundary_audit.py。")

def _rows(sql,*a):
    if _CRED.search(sql): raise PermissionError(_CRED_MSG)
    if _TRUTH.search(sql):
        raise PermissionError(
            "truth 是评测答案表,**不允许经工具层访问**(任何语句形状都不行)。"
            "评测比对在 agent 之外做 —— 见 backend/boundary_audit.py 第 2 条。")
    with _c() as c:
        cur = c.execute(sql, a)
        cols = [d[0].lower() for d in (cur.description or [])]
        # **与语句写法无关的那道锁**:结果里只要出现凭据列,就不给。
        # 星号、别名星号、子查询、以后新加的写法,全在这一关。
        if any(x.startswith("pwd_") for x in cols): raise PermissionError(_CRED_MSG)
        return [dict(r) for r in cur]

def list_tasks(task_type=None, status="待处理"):
    """列出人工任务。type: 财务人工任务 / 客户合并确认"""
    if task_type: return _rows("SELECT * FROM task WHERE type=? AND status=?",task_type,status)
    return _rows("SELECT * FROM task WHERE status=?",status)

def get_deposit(deposit_id):
    """押金单:金额、状态、幂等号、关联预约"""
    r=_rows("SELECT * FROM deposit WHERE id=?",deposit_id)
    return r[0] if r else {"error":f"押金单 {deposit_id} 不存在"}

def get_refund_trace(deposit_id):
    """退款尝试轨迹:每次重试的时间、渠道、请求金额、返回码、幂等号"""
    r=_rows("SELECT attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key FROM refund_trace WHERE deposit_id=? ORDER BY attempt",deposit_id)
    return r if r else {"error":f"押金单 {deposit_id} 无退款轨迹"}

def get_payment_flow(deposit_id):
    """支付流水:in=收款 out=退款,含渠道流水号与最终状态"""
    r=_rows("SELECT id,direction,amount,channel,channel_serial,status,ts FROM payment_flow WHERE deposit_id=?",deposit_id)
    return r if r else {"error":f"押金单 {deposit_id} 无支付流水"}

def get_customer(customer_id):
    """客户档案。敏感字段按后台规则脱敏:手机号中间四位、地址门牌号"""
    r=_rows("SELECT * FROM customer WHERE id=?",customer_id)
    if not r: return {"error":f"客户 {customer_id} 不存在"}
    d=r[0]
    p=d.get("phone") or ""
    d["phone"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p
    return d

TOOLS={"list_tasks":list_tasks,"get_deposit":get_deposit,"get_refund_trace":get_refund_trace,
       "get_payment_flow":get_payment_flow,"get_customer":get_customer}

SCHEMAS=[
 {"name":"list_tasks","description":"列出待处理的人工任务。task_type 可选:财务人工任务、客户合并确认",
  "input_schema":{"type":"object","properties":{"task_type":{"type":"string"}},"required":[]}},
 {"name":"get_deposit","description":"读取押金单:金额、当前状态、幂等号、关联预约号",
  "input_schema":{"type":"object","properties":{"deposit_id":{"type":"string"}},"required":["deposit_id"]}},
 {"name":"get_refund_trace","description":"读取退款尝试轨迹,含每次重试的返回码、请求金额和幂等号",
  "input_schema":{"type":"object","properties":{"deposit_id":{"type":"string"}},"required":["deposit_id"]}},
 {"name":"get_payment_flow","description":"读取支付流水,direction=in 为收款,out 为退款,含渠道流水号与最终状态",
  "input_schema":{"type":"object","properties":{"deposit_id":{"type":"string"}},"required":["deposit_id"]}},
 {"name":"get_customer","description":"读取客户档案(手机号与地址已脱敏)",
  "input_schema":{"type":"object","properties":{"customer_id":{"type":"string"}},"required":["customer_id"]}},
]

# ── 工艺知识库工具(只读)──────────────────────────────────────────
def kb_lookup(keyword=None, cat=None, src=None):
    """按关键词/分类/来源等级查工艺知识。cat: 形制/材质/工艺/配饰;src: public/scale/demo"""
    rs=_rows("SELECT code,name,cat,alias,brief,fit,lead_days,cost_level,src_type,src_url FROM craft ORDER BY code")
    if cat: rs=[r for r in rs if r["cat"]==cat]
    if src: rs=[r for r in rs if r["src_type"]==src]
    if keyword:
        k=keyword.strip()
        rs=[r for r in rs if any(k in str(r.get(f) or "") for f in ("name","alias","brief","fit","code"))]
    if not rs: return {"hit":0,"note":f"知识库里查不到「{keyword or cat or src}」,不要凭印象回答"}
    return {"hit":len(rs),"rows":[_nz(_with_material(r)) for r in rs[:12]]}

# 面料的**物理参数**(备料天/现货/单价/损耗/幅宽)家在 material 表,不在知识库条目里。
# craft.lead_days 对**工艺**条目有值(工期档位),对**材质**条目一律为空。
# 原来 kb_detail 直接把这个空值返回去,模型如实回答「知识库里还没有录入」——
# 而 material 表里明明写着 12 天,kb_lead 和 get_stock 也都能查到。
# **工具说了假话,模型没错。** 换模型对照时露出来的:同一个问题,
# 一个模型走 kb_lead 答「12 天」,另一个走 kb_detail 答「未录入」。
_MAT_FIELDS = ("备料天", "现货", "单价", "计价单位", "损耗率", "幅宽cm")

def _nz(d):
    """**值为空的字段整个去掉,不要发给模型。**

    `null` 和「没有这个字段」对人是一回事,对模型完全不是:
    看到 `cost_level: null`,它会如实回答「成本档位知识库里还没录入」——
    可成本档位本来就只对**工艺**条目有,形制/材质根本没有这一项。
    「未录入」和「不适用」被同一个 null 表达了,而它只能照着字面说。

    少一个字段,模型不会去提它;给一个空字段,模型一定会提它。"""
    return {k: v for k, v in dict(d).items() if v not in (None, "")}

def _with_material(d):
    """材质条目补上物理参数。**同一个事实只留一个字段** —— 空的那个要拿掉,
    留着它就等于给模型两个矛盾的来源,而它没法判断该信哪个。"""
    if (d.get("cat") or "") != "材质": return d
    m=_rows("SELECT price,unit,loss_rate,lead_days,stock_qty,width_cm FROM material WHERE code=?",
            d.get("code"))
    d=dict(d)
    if m:
        d.update(备料天=m[0]["lead_days"], 现货=m[0]["stock_qty"], 单价=m[0]["price"],
                 计价单位=m[0]["unit"], 损耗率=m[0]["loss_rate"], 幅宽cm=m[0]["width_cm"])
        d.pop("lead_days", None)
    return d

def get_workorder(workorder_id=None, artisan=None, status=None, ref=None, overdue=None):
    """查在制工单:这件活在谁手上、到哪一步、会不会拖。

    get_capacity 给的是**工种级**聚合(瓶颈在哪、消化天数),
    答不了「这一件现在什么情况」。排产的人两个都要:
    先看瓶颈决定接不接,再看单件决定怎么调。
    """
    where, args = [], []
    if workorder_id: where.append("w.id=?"); args.append(workorder_id)
    if artisan:
        # **「查无此人」和「这人没活」必须分开说。**
        # 这个工具查的是**工坊师傅**的在制工单。拿一个顾问的名字来查,
        # 返回 0 条 —— 而 0 条会被读成「他手头没有没做完的活」。
        # 实测栽过:顾问问「周叙手上还有几件活」,模型调这个工具查到 0 条,
        # 答「他手头没有没做完的活」—— 周叙是顾问,有 4 条任务在身,
        # 他只是**不在师傅表里**。**空结果不等于没有,只等于这里查不到。**
        who = (artisan or "").strip()
        if not _rows("SELECT no FROM artisan WHERE no=? OR name=?", who, who):
            st = _rows("SELECT no,name,role FROM staff WHERE no=? OR name=?", who, who)
            hint = (f"「{who}」是{st[0]['role']},不是工坊师傅。"
                    f"这个工具只看得到工坊在制工单,看不到{st[0]['role']}的任务。"
                    if st else f"工坊师傅里没有「{who}」这个人。")
            return dict(error=hint + " **这不等于他没有活** —— 只是这个工具查不到。"
                               "顾问的任务用 my_tasks(只看得到自己的)或问店长。")
        where.append("(a.no=? OR a.name=?)"); args += [artisan, artisan]
    if status:       where.append("w.status=?"); args.append(status)
    if ref:          where.append("w.ref=?"); args.append(ref)
    sql = ("SELECT w.id,w.craft,w.ref,w.workdays,w.start_date,w.due_date,w.status,w.note,"
           "a.no artisan_no,a.name artisan,a.trade,a.workshop,a.wip_limit,c.name craft_name "
           "FROM workorder w LEFT JOIN artisan a ON a.no=w.artisan "
           "LEFT JOIN craft c ON c.code=w.craft")
    if where: sql += " WHERE " + " AND ".join(where)
    rs = _rows(sql + " ORDER BY w.due_date", *args)
    today = _dt.date.today().isoformat()
    out = []
    for r in rs:
        d = dict(r)
        # **交期是否已经过了**,而不是让模型自己拿今天去比 ——
        # 模型不知道今天几号,靠它算这个必错,而且错得很自然。
        d["已逾期"] = bool(d.get("due_date") and d["due_date"] < today and d["status"] == "在制")
        d["剩余天数"] = ((_dt.date.fromisoformat(d["due_date"]) - _dt.date.today()).days
                     if d.get("due_date") else None)
        out.append(d)
    if not out:
        return {"hit": 0, "note": "没有符合条件的在制工单,不要凭印象回答"}
    if overdue: out = [x for x in out if x["已逾期"]]
    late = [x["id"] for x in out if x["已逾期"]]
    return {"hit": len(out), "rows": [_nz(x) for x in out[:30]],
            "已逾期工单": late,
            "note": "「剩余天数」为负说明已经过了交期。**逾期工单要先说,不要埋在列表里。**"
                    "一个师傅手上的在制件数超过 wip_limit,说明他已经排满,再派活只会更晚。"}


def get_lifecycle(customer=None, lifecycle=None):
    """查会员生命周期判定:这个客户属于哪一档、**凭什么**、有没有被人工覆盖。

    口径在 knowledge/lifecycle.py,这里只取数和包装 ——
    判定逻辑不写在工具里,否则又是一份手抄件。
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "knowledge"))
    import lifecycle as _lc
    where, args = [], []
    if customer:  where.append("(id=? OR name=?)"); args += [customer, customer]
    if lifecycle: where.append("lifecycle=?"); args.append(lifecycle)
    sql = ("SELECT id,name,lifecycle,order_cnt,idle_days,amount_12m,orders_12m,"
           "quarters_12m,first_order,manual_lc,manual_at,last_interact FROM customer")
    if where: sql += " WHERE " + " AND ".join(where)
    rs = _rows(sql + " ORDER BY id LIMIT 40", *args)
    if not rs:
        return {"hit": 0, "note": "查不到这个客户,不要凭印象回答",
                "现有档位": _lc.PRIORITY}
    out = []
    for r in rs:
        d = dict(r)
        # 天数由**这一层**算好再交给口径 —— 口径不管今天几号,
        # 否则同一批数据在不同时刻算出不同结果,真值对账没法复现。
        def _ago(iso):
            return ((_dt.date.today() - _dt.date.fromisoformat(iso)).days
                    if iso else None)
        v = _lc.decide(dict(d, days_since_first_order=_ago(d.get("first_order")),
                            days_since_manual=_ago(d.get("manual_at"))))
        d.update(v)
        # 库里存的是每日重算的结果,这里是**按今天**重算的 —— 不一致要说出来,
        # 不要默默用其中一个:那说明这条记录还没被今天的重算刷过。
        if d.get("lifecycle") and d["lifecycle"] != v["生命周期"]:
            d["提醒"] = (f"库里存的是「{d['lifecycle']}」,按今天重算是「{v['生命周期']}」——"
                       "说明这条还没被今天的重算刷到,**以哪个为准要问运营**")
        out.append(_nz(d))
    return {"hit": len(out), "rows": out,
            "优先级": _lc.PRIORITY, "判定条件": _lc.RULES,
            "note": "「命中」列出全部命中的条件,「生命周期」是按优先级取的那一个。"
                    "**多条命中时要把命中列表说出来** —— 只报结论,运营无从判断算得对不对。"}


def get_member_priority(lifecycle=None, limit=10):
    """同一档里**先联系谁**。给一个生命周期档位,按 RFM 排出优先次序。

    八档答「这个客户处在什么阶段」,答不了「潜在流失这 16 个人我先打给谁」——
    档内没有排序,而运营每天要做的正是后者。

    口径在 knowledge/rfm.py。**分数只在传进来的这一批人内部可比** ——
    换一批人同一个人的分数会变,这是相对指标的本性。
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "knowledge"))
    import rfm as _rfm, lifecycle as _lc
    if lifecycle and lifecycle not in _lc.PRIORITY:
        return {"error": f"没有「{lifecycle}」这一档", "现有档位": _lc.PRIORITY}
    sql = ("SELECT id,name,lifecycle,idle_days,orders_12m,amount_12m,last_interact,advisor "
           "FROM customer")
    args = []
    if lifecycle: sql += " WHERE lifecycle=?"; args.append(lifecycle)
    rs = _rows(sql, *args)
    if not rs:
        return {"hit": 0, "note": "这一档一个人都没有,不要凭印象回答"}
    ranked = _rfm.score(rs)[: max(1, min(int(limit or 10), 40))]
    for r in ranked: r["评分依据"] = _rfm.explain(r)
    return {"hit": len(rs), "档位": lifecycle or "全部", "rows": [_nz(r) for r in ranked],
            "note": "**RFM 是相对分,只在这一批人内部可比** —— 不要拿两个档位的分数直接比，"
                    "也不要说「他 RFM 12 分所以是优质客户」。"
                    "排序解决的是「先打给谁」,不是「谁更值钱」。"
                    "**这是排序不是预测**,不代表联系了就能挽回。"}


# ── 「现在是谁在用这个工具」 ─────────────────────────────────────────
# 智能体的工具跑在**独立子进程**里,拿不到 HTTP 会话。身份由启动它的那一方
# 通过环境变量传进来(见 agentsite/sdk.py 的 mcp_config)。
#
# **为什么不让模型自己说自己是谁**:那就成了「我以店长身份执行」——
# 一句话就能提权。身份必须来自签发方,不能来自使用方。
# 这条和 check_write 里「授权主张 vs 查询条件」是同一条:
#   工具**按谁的身份取数**,是授权主张,只能来自会话;
#   「假如是店长,允不允许」,是查询条件,可以由参数给。
import contextvars as _cv
_ME = _cv.ContextVar("lanxiu_me", default=None)


def whoami():
    """当前操作人。没有身份时返回 None —— **不许兜底成某个默认角色**。

    两个来源,按优先级:
      ① contextvar —— 同进程内调用(比如服务端重跑一遍起草工具)
      ② 环境变量   —— MCP 子进程,由启动它的那一方注入
    用 contextvar 而不是全局变量:**两个请求同时进来不会互相串身份**,
    而串了不会报错 —— 甲的问题用乙的身份取数,答出来完全正常。
    """
    v = _ME.get()
    if v: return v
    import json as _js
    raw = os.environ.get("LANXIU_ME") or ""
    if not raw: return None
    try: return _js.loads(raw)
    except Exception: return None


class as_user:
    """`with api.as_user(me): ...` —— 在这段代码里,工具以这个人的身份取数。"""
    def __init__(self, me): self.me, self.tok = me, None
    def __enter__(self): self.tok = _ME.set(self.me); return self
    def __exit__(self, *a): _ME.reset(self.tok); return False


# 起草工具的名字 → 函数。**服务端重跑用这张表** ——
# 从轨迹里拿到模型调用起草工具时的入参,原样重跑一遍拿到草稿,
# 而不是去解析模型说了什么。模型可能把参数复述错,入参不会。
# 顺带一个好处:确认卡是**点的时候现算的**,不是两分钟前存下来的 ——
# 期间那位顾问被派了别的活,卡上的撞车提醒会跟着变。
# 会改数据的工具。**列在这儿是给检查用的** —— isolation_check 逐个确认
# 它们都从会话取身份、都走 tasks.py 那一套判定,不会因为「是智能体调的」而放宽。
WRITE_TOOLS = ("apply_adjust", "decide_approval","assign_task", "dispatch_task", "reassign_task", "finish_task",
               "assign_batch", "dispatch_batch")


MANAGER_ROLES = ("店长", "总部运营")


def my_tasks(status=None):
    """看**我的任务**。顾问只看得到派给自己的,店长看本店全部。

    **A 顾问不会在这里看到 B 顾问的活** —— 隔离在查询层,不在界面上。
    范围由 tasks.visible_scope 一处判定,所有读任务的地方都走它。
    """
    import tasks as _tk, tasktypes as tt
    me = whoami()
    if not me: return dict(error="不知道现在是谁在问 —— 请先登录")
    d = _tk.my_tasks(me, status)
    if d.get("error"): return d
    out = [_nz({"任务号": r["id"], "类型": tt.norm(r.get("type")),
                "状态": r.get("status"), "内容": r.get("note"),
                "开始": r.get("start_ts"), "结束": r.get("end_ts"),
                "负责人": r.get("assignee_name") or r.get("advisor"),
                "挂的单据": r.get("ref_id"), "客户": r.get("customer_id"),
                "绑定活动": r.get("activity_code"), "总结": r.get("summary"),
                "附件数": len(r.get("附件") or []) or None,
                "派任务的人": r.get("派任务的人"),
                # 被改派走的必须**看得出来**。只显示「负责人:林岚」的话,
                # 原负责人会以为是自己记错了 —— 那比少一行还糟。
                "改派": (f"这条原来是你的,{r.get('reassigned_at','')} 被改派给 "
                        f"{r.get('assignee_name')};理由:{r.get('reassign_reason')}"
                        if r.get("reassigned_from") == me["no"] else
                        (f"{r.get('reassigned_at','')} 从别人那儿改派过来;"
                         f"理由:{r.get('reassign_reason')}"
                         if r.get("reassigned_from") else None))})
           for r in d["rows"]]
    # **截断要说出来。** 原来直接 out[:40],多的部分无声消失 ——
    # 40 条以内看不出问题,超了它会给出一个看起来完整的答案,而少了一批。
    # 静默截断是最难发现的一类错:结果本身没有任何异常。
    LIMIT = 40
    shown, more = out[:LIMIT], max(0, len(out) - LIMIT)
    return _nz(dict(我是=f"{me['name']}·{me['role']}", 范围=d["scope"],
                    条数=len(out), 已列出=len(shown), 任务=shown,
                    还有没列出的=(f"{more} 条没列出来 —— 加 status 参数缩小范围,"
                                  f"或用 team_tasks 按人看" if more else None)))


def team_tasks(assignee=None, status=None):
    """**本店每个顾问手上各有什么活** —— 店长看团队用这个,不是 my_tasks。

    给 assignee(工号或姓名)就只看那一个人。不给就按人分组,
    带上每个人的在办件数和最近到期时间。

    顾问调这个只会看到自己 —— **隔离在查询层**,不是这里少显示几行。
    """
    import tasks as _tk, tasktypes as tt
    me = whoami()
    if not me: return dict(error="不知道现在是谁在问 —— 请先登录")
    d = _tk.my_tasks(me, status)
    if d.get("error"): return d
    rs = d["rows"]

    who = (assignee or "").strip()
    if who:
        pool = _tk.rows("SELECT no,name FROM staff WHERE no=? OR name=?", who, who)
        if len(pool) != 1:
            return dict(error=(f"找不到「{who}」" if not pool else f"有 {len(pool)} 个人叫「{who}」,请给工号"))
        rs = [r for r in rs if r.get("assignee_no") == pool[0]["no"]]
        if not rs:
            # **「他没活」和「你看不到他的活」要分开说。**
            # 顾问问同事,拿到空列表会读成「他没活」—— 那是隔离挡的,不是真没有。
            if me.get("role") not in _tk.MANAGER_ROLES and pool[0]["no"] != me["no"]:
                return dict(error=f"你只看得到派给自己的任务,{pool[0]['name']} 的看不到 —— "
                                  f"**这不等于他没有活**。要看全店得问店长。")
            return dict(范围=d["scope"], 说明=f"{pool[0]['name']} 名下没有符合条件的任务", 条数=0, 任务=[])

    by = {}
    for r in rs:
        k = r.get("assignee_name") or r.get("advisor") or "(没有负责人)"
        by.setdefault(k, []).append(r)

    def one(r):
        return _nz({"任务号": r["id"], "类型": tt.norm(r.get("type")), "状态": r.get("status"),
                    "内容": r.get("note"), "结束": r.get("end_ts"),
                    "挂的单据": r.get("ref_id"), "客户": r.get("customer_id")})

    out = []
    for k, v in sorted(by.items(), key=lambda kv: -len([x for x in kv[1] if x.get("status") == "有效"])):
        live = [x for x in v if x.get("status") == "有效"]
        out.append(_nz({"顾问": k, "在办": len(live), "全部": len(v),
                        "最近到期": min([x.get("end_ts") for x in live if x.get("end_ts")], default=None),
                        # **每人只列在办的**,历史记录列出来会把清单撑爆,
                        # 而撑爆之后就得截断,截断是静默的。
                        "在办明细": [one(x) for x in live]}))
    idle = [p["name"] for p in _tk.my_staff(me) if p["name"] not in by] if         me.get("role") in _tk.MANAGER_ROLES else []
    return _nz(dict(范围=d["scope"], 人数=len(out), 团队=out,
                    手上没活的=idle or None,
                    待分配=len([r for r in rs if not r.get("assignee_no") and r.get("status") == "有效"]) or None))


def week_grid(start=None, days=7):
    """**一周的排班格子**:每个顾问哪天什么时段已经占了、哪些时段空着。

    排班之前必须先看这个 —— 不看就排,排出来的东西**和正常任务长得一模一样**,
    直到那天两个人同时约在一个时段。

    返回按人 × 天的占用情况,以及每天没人覆盖的营业时段。
    """
    import datetime, tasks as _tk
    me = whoami()
    if not me: return dict(error="不知道现在是谁在排 —— 请先登录")
    if me.get("role") not in _tk.MANAGER_ROLES:
        return dict(error=f"排班是店长的活,你是「{me.get('role')}」。"
                          f"你自己的日程用 my_tasks 看")
    try:
        d0 = (datetime.date.fromisoformat(start) if start else datetime.date.today())
    except ValueError:
        return dict(error=f"起始日期「{start}」格式不对,要 YYYY-MM-DD")
    days = max(1, min(int(days or 7), 14))
    d1 = d0 + datetime.timedelta(days=days)

    staff = _tk.my_staff(me)
    rs = _tk.rows("SELECT id,assignee_no,type,note,start_ts,end_ts FROM schedule "
                  "WHERE status='有效' AND start_ts < ? AND end_ts > ? "
                  "AND assignee_no IS NOT NULL ORDER BY start_ts",
                  d1.isoformat() + " 00:00", d0.isoformat() + " 00:00")
    OPEN_H, CLOSE_H = 10, 21          # 和 booking.OPEN_HOUR 一个口径

    people = []
    for p in staff:
        mine = [r for r in rs if r["assignee_no"] == p["no"]]
        byday = {}
        for r in mine:
            day = (r["start_ts"] or "")[:10]
            byday.setdefault(day, []).append(
                f"{(r['start_ts'] or '')[11:16]}–{(r['end_ts'] or '')[11:16]} "
                f"{r['type']}({r['id']})")
        people.append(_nz({"顾问": p["name"], "工号": p["no"],
                           "这段时间在办": len(mine),
                           "按天": byday or None}))

    # 每天有多少人有安排 —— **没人覆盖的那天要单独说**,
    # 它不会出现在任何一个人的列表里,所以最容易被漏掉。
    naked = []
    for k in range(days):
        day = (d0 + datetime.timedelta(days=k)).isoformat()
        cover = {r["assignee_no"] for r in rs if (r["start_ts"] or "").startswith(day)}
        if not cover:
            naked.append(day)
    return _nz(dict(区间=f"{d0} 起 {days} 天", 营业时间=f"{OPEN_H}:00–{CLOSE_H}:00",
                    可排的人=[p["name"] for p in staff],
                    每人=people,
                    完全没人排班的日子=naked or None,
                    待分配=len(__import__("booking").unassigned(
                        None if me["role"] == "总部运营" else me.get("shop"))) or None))


def assign_batch(items):
    """**一次排一批任务**(排班用,真的写进去)。**全过才写,一条不过就整批不写。**

    items 是一个列表,每条:{type, assignee, note, start, end, ref_id?, activity_code?}。
    一次最多 20 条。

    为什么用批量而不是连着调 assign_task:
      ① 一周的排班**是一个决定,不是七个决定**。半途失败留下三条已排四条没排,
         比整批失败难收拾得多 —— 你得先搞清楚哪三条排进去了。
      ② **有些冲突只有整体看才发现**:同一个人被排了两个重叠时段。
         一条一条排,前四条都合法,第五条才撞上第二条,而那时前四条已经落库。

    ⚠️ 排之前先 `week_grid()` 看现有占用,并把整张表念给用户确认。
    """
    import tasks
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在排 —— 请先登录")
    if me.get("role") not in tasks.MANAGER_ROLES:
        return dict(error=f"排班须由店长及以上操作,你是「{me.get('role')}」")
    r = tasks.assign_batch(items, me)
    if r.get("ok"): _agent_log(me, "BATCH", r.get("reason", ""))
    return r


def dispatch_batch(items):
    """**一次把待分配池里的几条单分出去**(真的写进去)。全过才写,一条不过整批不写。

    items:[{task_id, assignee?}]。不给 assignee 就采纳 dispatch_pool 里那条建议。
    「把待分配的都派了」用这个 —— assign_batch 是**新建**任务的,派不了已存在的单。
    """
    import tasks
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在分 —— 请先登录")
    if me.get("role") not in tasks.MANAGER_ROLES:
        return dict(error=f"分派须由店长及以上操作,你是「{me.get('role')}」")
    r = tasks.dispatch_batch(items, me)
    if r.get("ok"): _agent_log(me, "BATCH_DISPATCH", r.get("reason", ""))
    return r


def monthly_review(month=None):
    """**月度复盘**:这个月做完了多少、几条逾期、逾期都在谁身上、改派了几次、
    agent 的派单建议采纳率、待分配积压、订单走完一轮要多久。

    month 写 `2026-09`,不给就是当月。范围跟身份走:顾问只看自己的,店长看本店。

    ⚠️ **分母为零时不给比率,给一句话** —— 「没发生过」和「发生了但都是零」
    是两件事,而它们在一张报表上长得一模一样。
    """
    import tasks as _tk, datetime, json as _js, statistics as _st
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import knowledge.review as rv

    me = whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    today = _dt.date.today().isoformat()
    m = (month or today[:7]).strip()
    if not re.fullmatch(r"\d{4}-\d{2}", m):
        return dict(error=f"月份写成 2026-09 这样,收到「{month}」")

    where, args, scope = _tk.visible_scope(me)
    ts_ = _rows(f"SELECT s.*, st.name assignee_name FROM schedule s "
                f"LEFT JOIN staff st ON st.no=s.assignee_no "
                f"WHERE {where} AND substr(s.{rv.归月字段},1,7)=?", *(args + [m]))

    out = dict(月份=m, 范围=scope,
               口径=f"任务按**{rv.归月字段_人话}**归月;"
                    f"改派/分派这些动作,**按它动的那条任务归月** —— "
                    f"台账记的是操作发生的墙上时间,和业务时间不是一个钟,"
                    f"照墙上时间筛会筛出空集")

    mgr_view = (me.get("role") in _tk.MANAGER_ROLES or me.get("role") == "总部运营")
    if ts_:
        done = [r for r in ts_ if r.get("status") == "完结"]
        od = [r for r in ts_ if rv.逾期判定(r.get("status"), r.get("end_ts"), today)]
        by_person = {}
        for r in od:
            k = r.get("assignee_name") or "(没有负责人)"
            by_person[k] = by_person.get(k, 0) + 1
        done_txt, _ = rv.rate(len(done), len(ts_), "任务")
        # **「逾期都在谁身上」只给店长及以上。**
        # 它是管理信号(一个人欠 5 条 和 5 个人各欠 1 条是两个问题),
        # 而顾问的可见范围里本来就会出现别人的名字 ——
        # 被改派走的那条单子还挂在他列表里,现在的负责人是另一个人。
        # 单看一条是知情权,**汇总成一张「谁在拖」的榜,就是越界了**。
        mgr = mgr_view
        out["任务"] = dict(总数=len(ts_), 完结=len(done), 完成率=done_txt,
                          **({"逾期": len(od)} if mgr else
                             {"你看得到的逾期": len(od),
                              "说明": "含被改派走、但仍留在你列表里的那些 —— "
                                      "它们现在的负责人是别人"}),
                          逾期都在谁身上=(by_person or None) if mgr else None,
                          你的逾期=None if mgr else len(
                              [r for r in od if r.get("assignee_no") == me.get("no")]),
                          逾期口径=f"截止时间已过、状态仍是「有效」,按**今天 {today}** 判 —— "
                                   f"问的是「现在还有几条客户在等」,不是「当月月底欠着几条」")
    else:
        out["任务"] = dict(总数=0, 说明=f"{m} 这个月,你看得到的范围里没有任务到期")

    # 动作:从台账里取,但**按它动的那条任务归月**,和上面同一个钟。
    ids = {r["id"] for r in ts_}
    logs = _rows("SELECT code,target,reason,ctx,ts FROM op_log WHERE code IN "
                 "('REASSIGN','DISPATCH','ASSIGN','AGENT_REASSIGN','AGENT_DISPATCH','AGENT_ASSIGN')")
    mine = [l for l in logs if l["target"] in ids]
    reas = [l for l in mine if l["code"] == "REASSIGN"]
    disp = [l for l in mine if l["code"] == "DISPATCH"]
    agent = [l for l in mine if (l["code"] or "").startswith("AGENT_")]
    adopted = sum(1 for l in disp
                  if (_js.loads(l["ctx"] or "{}") or {}).get("adopted"))

    out["改派"] = dict(次数=len(reas),
                      涉及几条单子=len({l["target"] for l in reas}),
                      理由=[(_js.loads(l["ctx"] or "{}") or {}).get("reason")
                           for l in reas][:5] or None,
                      提示="同一条单子来回改派,说明的多半是排班问题,不是人的问题"
                           if len(reas) > len({l["target"] for l in reas}) else None)
    ad_txt, _ = rv.rate(adopted, len(disp), "分派")
    out["分派"] = dict(次数=len(disp), 采纳agent建议=ad_txt)
    out["智能体代做"] = len(agent) or None

    # 台账里对不上的动作 —— **不许静默丢掉,但要分清是哪一种**。
    # 第一版把这两种混成一句,于是 6 条「没记下动的是哪条」被报成
    # 「单子已经不在库里」,听起来像数据丢了 —— **报错了理由的告警,
    # 比不报更费事**:照着它去查会去查错的地方。
    live = {r[0] for r in _rows2("SELECT id FROM schedule")}
    noname = [l for l in logs if not (l["target"] or "").strip()
              or (l["target"] or "").strip() in ("-", "—")]
    gone = [l for l in logs if l not in noname and l["target"] not in live]
    if noname:
        out["没记下动的是哪条"] = (
            f"{len(noname)} 条动作台账里没填单号(多是 AGENT_* 那类「智能体代做」的记录)"
            f" —— 挂不回任何一个月,**所以不计入上面的数**;要能按月复盘,这些得补上单号")
    if gone:
        out["指向的单子已经不在了"] = (
            f"{len(gone)} 条动作指向的单子在库里找不到了(多半是重新灌过数据或从备份恢复过)"
            f" —— 台账是流水、不跟着库换,所以会对不上")

    pool = len(_rows(f"SELECT s.id FROM schedule s WHERE {where} "
                     f"AND s.assignee_no IS NULL AND s.status='有效'", *args))
    out["待分配积压"] = pool or None

    # ── 审批 ──────────────────────────────────────────────────────
    # **这一段才是「AI 到底有没有用」的直接度量。**
    # 上一版把「agent 建议采纳率」放在「分派」那一栏,而待分配池一直是空的,
    # 一次分派都没发生过 —— 那个指标永远没有分母。
    # 审批不一样:**它天生就是「智能体提议 → 人拍板」的结构**,
    # 提了几单、人通过了几单,直接就是采纳率。
    #
    # 按 `applied_at` 归月。和 op_log 不同,审批单的申请时间**就是它的业务时间**,
    # 不存在「墙钟和业务时间两个钟」的问题。
    if mgr_view:
        ap = _rows("SELECT a.*, c.shop cshop FROM approval a "
                   "LEFT JOIN customer c ON c.id=a.target "
                   "WHERE substr(a.applied_at,1,7)=?", m)
        if me.get("role") != "总部运营":
            ap = [x for x in ap if (x.get("cshop") or "") == me.get("shop")]
        if ap:
            agent = [x for x in ap if _by_agent(x["id"])]
            done = [x for x in agent if x["status"] in ("已通过", "已驳回")]
            passed = [x for x in done if x["status"] == "已通过"]
            txt, _ = rv.rate(len(passed), len(done), "智能体提的审批")
            out["审批"] = _nz(dict(
                本月提了=len(ap),
                其中智能体提的=len(agent) or None,
                还挂着没批的=len([x for x in ap if x["status"] == "待审批"]) or None,
                智能体提的通过率=txt,
                这个数是什么=("**智能体提议、人拍板** —— 提了几单、人通过了几单,"
                             "直接就是「它的建议有没有被采纳」。"
                             "比「分派采纳率」可靠,因为那条路一次都没发生过"),
                按什么归月="审批单的申请时间(它就是业务时间,不像操作台账是墙钟)"))

    # 订单工期 —— 和任务分开归月:订单按**完成时间**归月(那是它走完一轮的时刻)
    o_where, o_args = ("1=1", [])
    if me.get("role") != "总部运营":
        o_where, o_args = ("shop=?", [me.get("shop")])
        if me.get("role") not in _tk.MANAGER_ROLES:
            o_where, o_args = ("shop=? AND advisor=?", [me.get("shop"), me.get("name")])
    spans = []
    for o in _rows(f"SELECT created,finished_at FROM ordr WHERE status='完成' "
                   f"AND finished_at IS NOT NULL AND substr(finished_at,1,7)=? AND {o_where}",
                   *([m] + o_args)):
        try:
            spans.append((_dt.date.fromisoformat(o["finished_at"][:10])
                          - _dt.date.fromisoformat(o["created"][:10])).days)
        except Exception:
            pass
    out["订单工期"] = (f"{len(spans)} 单走完,中位 {int(_st.median(spans))} 天"
                      f"(最快 {min(spans)} / 最慢 {max(spans)})" if spans
                      else f"{m} 没有订单走完,工期无从谈起")

    out["先看这几件"] = rv.摘要(dict(
        逾期数=len([r for r in ts_ if rv.逾期判定(r.get("status"), r.get("end_ts"), today)]),
        待分配=pool, 改派次数=len(reas)))
    out["说明"] = ("**分母为零的地方不给比率,给一句话** —— "
                  "「没发生过」和「发生了但都是零」是两件事")
    return _nz(out)


def appt_funnel(since=None, until=None):
    """**预约到店转化漏斗**:约了多少 → 我们确认了多少 → 真到店多少 →
    量了体多少 → 下单多少,以及**流失分四种**(待确认烂掉 / 客户取消 /
    爽约 / 已过期),每种给出该怎么办。

    `since` / `until` 写 `2026-08-01`,不给就是全部。范围跟身份走:
    顾问只看派给自己的预约,店长看本店。

    ⚠️ 报两种转化率:**环节转化率**(÷ 上一环,看哪一环漏得最狠)和
    **整体转化率**(÷ 总预约,看一百个最后剩几个)。只看一个会答错另一个问题。
    ⚠️ 最后两环(量体 / 下单)**和预约之间没有外键**,是按「同一个客户、
    预约之后」连的,**会高估**。
    """
    import tasks as _tk
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import knowledge.appt_funnel as af

    me = whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    today = _dt.date.today().isoformat()
    for lbl, v in (("since", since), ("until", until)):
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v).strip()):
            return dict(error=f"{lbl} 写成 2026-08-01 这样,收到「{v}」")

    where, args, scope = _tk.visible_appt_scope(me)
    sql = f"SELECT a.* FROM appointment a WHERE {where}"
    if since: sql += " AND a.start_ts>=?"; args = args + [since]
    if until: sql += " AND a.start_ts<=?"; args = args + [until + " 23:59"]
    rs = _rows(sql, *args)

    # **还没到点的整条不进分母** —— 既不是到店也不是流失,它只是还没发生。
    未到 = [r for r in rs if af.未到点(r.get("start_ts"), today)]
    rs = [r for r in rs if r not in 未到]
    if not rs:
        return _nz(dict(范围=scope,
                        说明="这个范围里没有已经到时间的预约" +
                             (f"(还有 {len(未到)} 条在未来,不算进漏斗)" if 未到 else ""),
                        还没到时间的=len(未到) or None))

    总 = len(rs)
    确认了 = [r for r in rs if r.get("status") not in af.没确认]
    到店 = [r for r in rs if r.get("status") in af.到店了]

    # 后两环:按「同一个客户、预约之后」连 —— **没有外键,是估的**。
    cids = {r["customer_id"] for r in 到店 if r.get("customer_id")}
    量了 = 下单了 = 0
    for r in 到店:
        cid, t0 = r.get("customer_id"), r.get("start_ts")
        if not cid or not t0: continue
        if _rows2("SELECT 1 FROM measure_rec WHERE customer_id=? AND measured_at>=? LIMIT 1",
                  cid, t0[:10]): 量了 += 1
        if _rows2("SELECT 1 FROM ordr WHERE customer_id=? AND created>=? LIMIT 1",
                  cid, t0[:10]): 下单了 += 1

    各环 = [("约了", 总), ("确认了", len(确认了)), ("到店", len(到店))]
    表 = []
    for i, (名, n) in enumerate(各环):
        row = dict(环节=名, 人次=n)
        if i:
            row["这一环漏了多少"] = af.环节转化(n, 各环[i-1][1], 名)[0]
            row["从头算剩多少"] = af.整体转化(n, 总, 名)[0]
        表.append(row)

    # 到店**之后**发生了什么 —— **并列的两件事,各自除以「到店」**,不串成链。
    之后 = []
    for 名, n in (("这次新量了体", 量了), ("之后下了单", 下单了)):
        之后.append(dict(项=名, 人次=n,
                        占到店的=af.环节转化(n, len(到店), 名)[0],
                        说明=next(x[2] for x in af.到店之后 if x[0] == 名),
                        估的="和预约之间**没有外键**,按「同一个客户、预约当天之后」连,会高估"))

    # 流失分四种 —— **合成一个总数,看完不知道该干什么**。
    丢 = {}
    for st, (是什么, 怎么办) in af.流失分类.items():
        n = len([r for r in rs if r.get("status") == st])
        if n: 丢[st] = dict(条数=n, 是什么=是什么, 该怎么办=怎么办)

    out = dict(
        范围=scope,
        区间=f"{since or '不限'} ~ {until or '不限'}",
        先看这一句=af.最窄的一环(各环) or "算不出最窄的一环(有环节人数为 0)",
        漏斗=表,
        到店之后=之后,
        流失在哪=丢 or None,
        还没到时间的=(f"{len(未到)} 条预约还在未来 —— **没进分母**,"
                    f"它既不是到店也不是流失") if 未到 else None,
    )

    # 说明书里没有的状态 —— **不许静默归进「其他」**。
    野 = {}
    for r in rs:
        st = r.get("status")
        if st and st not in af.状态机认的:
            野[st] = 野.get(st, 0) + 1
    if 野:
        out["说明书里没有这些状态"] = dict(
            分布=野,
            这是什么=("状态机(bk-appt)认的只有 " + "、".join(af.状态机认的) +
                    " —— 库里出现了别的,要么是说明书漏了这一档,要么是数据漂了。"
                    "**两种都得有人看一眼**,所以单独列出来,不并进「其他」"))
    return _nz(out)


def _mem():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import knowledge.member as _m
    return _m


def _levels():
    return _rows("SELECT code,name,amount,orders,sort,need_points,note,point_rule "
                 "FROM level_cfg WHERE status='启用' ORDER BY sort")


def member_level(customer_id):
    """**这个客户是哪一档会员、凭什么、离下一档还差多少。**

    门槛按 `level_cfg`,是**滚动 12 个月**的实付或完成单数,满足**任一条**即可。

    ⚠️ 依据取的是客户档案上的 12 个月快照字段,**不是去订单表现算** ——
    库里的订单只是个样本(49 笔完成、涉及 33 人,而客户有 106 个),
    现算会把大多数人算成「0 单 0 元」。
    """
    m = _mem()
    cid = (customer_id or "").strip()
    r = _rows("SELECT id,name,level,amount_12m,orders_12m,paid_amount,order_cnt,points "
              "FROM customer WHERE id=?", cid)
    if not r:
        return dict(error=f"没有客户 {cid} —— **查无此人**,不是「这人没等级」")
    c = r[0]
    cfg = _levels()
    算 = m.判档(c["amount_12m"], c["orders_12m"], cfg)
    g = next((x for x in cfg if x["name"] == c["level"]), None)
    out = dict(
        客户=f"{c['name']}({c['id']})",
        当前等级=c["level"],
        依据=dict(窗口=m.窗口,
                 这段时间实付=c["amount_12m"], 这段时间完成单数=c["orders_12m"],
                 门槛=(f"实付 ≥{g['amount']:.0f} **或** 完成 ≥{g['orders']} 单"
                       if g and (g["amount"] or g["orders"]) else "无门槛(默认档)")),
        按规则现算=算,
        规则与库里一致=(算 == c["level"]),
        离升档还差=m.离下一档(c["amount_12m"], c["orders_12m"], c["level"], cfg),
        积分=c["points"],
        提醒=None if 算 == c["level"] else
             f"⚠️ 库里存的是「{c['level']}」,按门槛算是「{算}」—— "
             f"**多半是人工调过档**,查一下有没有对应的审批单",
        口径说明=("**不要拿「累计实付」算等级** —— 累计算出来 106 个人里能对上 96 个,"
                 "看起来就是对的,但那 10 个错的不会有任何地方报错"))
    return _nz(out)


def points_ledger(customer_id, limit=20):
    """**积分流水和对账。**

    ⚠️ 余额是「同一个事实两个来源」:既能从 `balance` 字段读,也能从流水累加。
    **必然漂** —— 这本账修过一次(中间余额被 max(0,...) 截断过),
    修完 0 处断点。但**对账不能取消**:只要两个来源都还在,就有再漂的可能。
    所以这里照旧两个都给、照旧对账,正常情况下应该报「0 处」。
    """
    m = _mem()
    cid = (customer_id or "").strip()
    if not _rows2("SELECT 1 FROM customer WHERE id=?", cid):
        return dict(error=f"没有客户 {cid} —— **查无此人**")
    rows = _rows("SELECT behavior,delta,balance,reason,actor,ts FROM points_log "
                 "WHERE customer_id=? ORDER BY ts,rowid", cid)
    if not rows:
        return dict(客户=cid, 说明="这个客户没有积分流水(0 条)—— "
                                  "**不是余额为零,是一笔都没发生过**")
    bad = m.积分对账(rows)
    档案上的 = (_rows("SELECT points FROM customer WHERE id=?", cid) or [{}])[0].get("points")
    return _nz(dict(
        客户=cid,
        档案上写的余额=档案上的,
        流水最后一条的余额=rows[-1]["balance"],
        按流水累加=sum(r["delta"] or 0 for r in rows),
        流水条数=len(rows),
        对不上的地方=([dict(上一条余额=b[0], 本次增减=b[1], 表上写的=b[2],
                          应该是=(b[0] or 0) + (b[1] or 0), 行为=b[3], 时间=b[4])
                      for b in bad[:5]] or None),
        对不上几处=len(bad) or None,
        最近流水=[dict(时间=r["ts"], 行为=r["behavior"], 增减=r["delta"],
                     余额=r["balance"], 原因=r["reason"], 经办=r["actor"])
                for r in rows[-int(limit or 20):]],
        说明=("**余额字段和流水累加对不上时,这里不替你选一个** —— "
              "哪个是对的取决于是谁写错了,那得查经办记录" if bad else None)))


def approval_queue(status=None, kind=None):
    """**审批队列**:等级调整 / 积分调整 / 客户转移,谁申请的、什么理由、批了没有。

    这三种动作的共同点是 **它们都绕过了某条本该自动成立的规则** ——
    自动算出来的等级不用审批,人手改的才要。**审批管的是例外,不是日常。**

    status 写「待审批 / 已通过 / 已驳回 / 已撤回」,不给就是全部。
    """
    m = _mem()
    where, args = ["1=1"], []
    if status: where.append("a.status=?"); args.append(status.strip())
    if kind: where.append("a.kind=?"); args.append(kind.strip())
    rows = _rows(f"SELECT a.*, s1.name applier, s2.name decider FROM approval a "
                 f"LEFT JOIN staff s1 ON s1.no=a.applied_by "
                 f"LEFT JOIN staff s2 ON s2.no=a.decided_by "
                 f"WHERE {' AND '.join(where)} ORDER BY a.applied_at DESC", *args)
    import json as _js
    out = []
    for r in rows:
        try: pl = _js.loads(r["payload"] or "{}")
        except Exception: pl = {"原文": r["payload"]}
        out.append(_nz(dict(单号=r["id"], 类型=r["kind"], 对象=r["target"],
                            要改成什么=pl, 状态=r["status"],
                            申请人=r["applier"] or r["applied_by"], 申请时间=r["applied_at"],
                            审批人=r["decider"] or r["decided_by"], 审批时间=r["decided_at"],
                            批注=r["note"],
                            为什么要审批=m.要审批的.get(r["kind"]))))
    待 = len([x for x in out if x.get("状态") == "待审批"])
    return _nz(dict(条数=len(out), 待审批=待 or None,
                    谁能批=f"「待审批 → 已通过/已驳回」这两步只有 **{m.审批角色}** 能走",
                    清单=out or None,
                    说明=None if out else "这个筛选条件下一条审批单都没有"))


def apply_adjust(kind, target, payload, reason):
    """**提一张审批单**(等级调整 / 积分调整 / 客户转移)——**只是申请,不生效**。

    这三件事的共同点是**它们都绕过了某条本该自动成立的规则**,
    所以一律走审批,不许直接改。提单本身不改任何业务数据。

    `payload` 写要改成什么,比如等级调整写 `{"from":"金卡","to":"黑金"}`,
    积分调整写 `{"delta":5000}`。`reason` 必填 —— **没有理由的申请,
    审批的人只能靠猜,而猜出来的「同意」等于没审**。
    """
    import datetime, json as _js, oplog
    m = _mem()
    me = whoami()
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in ("店长", "店长助理", "总部运营"):
        oplog.log_op(me.get("name") or "未登录", "approval", target or "—", "—", "—",
                     False, "WRONG_ROLE", f"角色 {me.get('role')} 不能提审批单", {})
        return dict(ok=False, code="WRONG_ROLE",
                    reason=f"提审批单须由店长及以上操作,你的角色是「{me.get('role')}」")
    kind = (kind or "").strip()
    if kind not in m.要审批的:
        return dict(ok=False, code="BAD_KIND",
                    reason=f"只受理这三种:{list(m.要审批的)};收到「{kind}」")
    tgt = (tgt0 := (target or "").strip())
    if not tgt:
        return dict(ok=False, code="NEED_TARGET", reason="要改谁?对象必填")
    # 客户转移可以是多个,用 | 隔开;其余必须是一个真实存在的客户
    for one in tgt.split("|"):
        if not _rows2("SELECT 1 FROM customer WHERE id=?", one.strip()):
            return dict(ok=False, code="NO_CUSTOMER",
                        reason=f"没有客户 {one.strip()} —— **查无此人**,不是「这人没资格」")
    why = (reason or "").strip()
    if len(why) < 4:
        return dict(ok=False, code="NEED_REASON",
                    reason="理由必填 —— **没有理由的申请,审批的人只能靠猜**,"
                           "而猜出来的「同意」等于没审")
    if isinstance(payload, str):
        try: payload = _js.loads(payload)
        except Exception: payload = {"原文": payload}
    if not isinstance(payload, dict) or not payload:
        return dict(ok=False, code="NEED_PAYLOAD", reason="要改成什么?payload 必填")

    pre = {"等级调整": "AP-LV", "积分调整": "AP-PT", "客户转移": "AP-TR"}[kind]
    n = len(_rows2("SELECT id FROM approval WHERE id LIKE ?", pre + "-%")) + 1
    aid = f"{pre}-{n:03d}"
    while _rows2("SELECT 1 FROM approval WHERE id=?", aid):
        n += 1; aid = f"{pre}-{n:03d}"
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = dict(payload); payload["reason"] = why
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO approval(id,kind,target,payload,status,applied_by,applied_at)"
                  " VALUES(?,?,?,?,'待审批',?,?)",
                  (aid, kind, tgt, _js.dumps(payload, ensure_ascii=False),
                   me.get("no"), now))
    oplog.log_op(me.get("name"), "approval", aid, "—", "待审批", True, "APPLY",
                 f"{me.get('name')}({me.get('role')})提了一张{kind}:{tgt} —— {why}"[:120],
                 {"kind": kind, "payload": payload, "by_agent": True})
    return dict(ok=True, code="APPLY", 单号=aid, 状态="待审批",
                reason=f"已提交 {aid}({kind}·{tgt})。**这只是申请,还没生效** —— "
                       f"「待审批 → 已通过/已驳回」这一步只有 **{m.审批角色}** 能走")


def decide_approval(approval_id, agree, note):
    """**批一张审批单**:同意或驳回。

    角色判定**不在这儿写** —— 走 `fsm.check("bk-approval", ...)`,
    那边 `APPROVAL_ROLE` 是唯一判定处。两处各判一次,总有一处会判松,
    而判松的那处**看起来完全正常**。

    `note` 必填,同意和驳回都要。驳回不写理由,申请人不知道该补什么;
    **同意不写理由,出事之后没人说得清当时看了什么**。
    """
    import fsm, oplog, json as _js
    m = _mem()
    me = whoami()
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    aid = (approval_id or "").strip()
    r = _rows("SELECT * FROM approval WHERE id=?", aid)
    if not r: return dict(ok=False, code="NO_APPROVAL", reason=f"没有审批单 {aid}")
    a = r[0]
    to = "已通过" if agree else "已驳回"
    ok, code, why = fsm.check("bk-approval", a["status"], to, {"role": me.get("role")})
    if not ok:
        oplog.log_op(me.get("name"), "approval", aid, a["status"], to, False, code, why[:120],
                     {"role": me.get("role")})
        return dict(ok=False, code=code, reason=why)
    txt = (note or "").strip()
    if len(txt) < 4:
        return dict(ok=False, code="NEED_NOTE",
                    reason="批注必填 —— 驳回不写理由,申请人不知道该补什么;"
                           "**同意不写理由,出事之后没人说得清当时看了什么**")
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE approval SET status=?,decided_by=?,decided_at=?,note=? WHERE id=?",
                  (to, me.get("no"), now, txt, aid))
    try: pl = _js.loads(a["payload"] or "{}")
    except Exception: pl = {}
    oplog.log_op(me.get("name"), "approval", aid, a["status"], to, True, "DECIDE",
                 f"{me.get('name')}({me.get('role')}){'通过' if agree else '驳回'}了 "
                 f"{aid}({a['kind']}·{a['target']}):{txt}"[:120],
                 {"kind": a["kind"], "agree": bool(agree),
                  "applied_by": a["applied_by"], "payload": pl})
    return dict(ok=True, code="DECIDE", 单号=aid, 状态=to,
                reason=f"{aid} 已{'通过' if agree else '驳回'}。"
                       f"⚠️ **审批只改审批单的状态,没有替你去改客户档案** —— "
                       f"实际调整要走各自的业务动作。这是有意的:"
                       f"批准和执行分开,才查得出「谁批的」和「谁做的」")


def _by_agent(approval_id):
    """这张审批单是不是经智能体提的。

    判据是台账里那条 APPLY 记录的 `by_agent` 标记 —— **不是猜的**。
    工具层(`api.apply_adjust`)只有智能体走得到,页面走的是另一条路,
    所以标记打在写的时候,不在事后推断。
    """
    import json as _js
    for r in _rows2("SELECT ctx FROM op_log WHERE code='APPLY' AND target=?", approval_id):
        try:
            if (_js.loads(r[0] or "{}") or {}).get("by_agent"): return True
        except Exception:
            pass
    return False


def activity_roi(code=None):
    """**活动投入产出**:花了多少、带来多少成交、投入产出比、单均获客成本。

    不给 code 就是全部活动的排名;给了就看那一个的明细。

    ⚠️ 三件事在别的报表里看不到,这里都会说:
    · **活动表上的「报名 / 成交」两列是随机数**,和订单表毫无关系 —— 一律不读
    · **归因期外的订单分开报**,不并进成交(实测有活动 100% 的订单在期外)
    · **成本和成交各有三个口径**(预算/已发生/已开票、应收/实收/完成),
      默认用「已发生」和「实收」,但三个都给
    """
    import tasks as _tk
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import knowledge.activity as av

    me = whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    if me.get("role") not in _tk.MANAGER_ROLES and me.get("role") != "总部运营":
        return dict(error=f"活动投入产出是管理视角,你的角色是「{me.get('role')}」—— "
                          f"这个得问店长")

    where, args = ("1=1", [])
    if code: where, args = ("code=?", [code.strip()])
    elif me.get("role") != "总部运营":
        # 店长只看得到本店的活动 + 全渠道的
        where, args = ("(shop=? OR shop='全渠道')", [me.get("shop")])
    acts = _rows(f"SELECT code,name,kind,status,start_d,end_d,shop,budget "
                 f"FROM activity WHERE {where} ORDER BY start_d DESC", *args)
    if not acts:
        return dict(说明=f"没有找到活动{('(' + code + ')') if code else ''}")

    out = []
    for a in acts:
        # 成本三个口径
        cs = _rows("SELECT amount,note FROM activity_cost WHERE activity=?", a["code"])
        已发生 = sum(x["amount"] or 0 for x in cs)
        已开票 = sum(x["amount"] or 0 for x in cs if (x["note"] or "") == "已开票")
        # 成交:先按归因取单,再分期内期外,取消的一律排除
        os_ = _rows("SELECT id,customer_id,status,payable,received,created FROM ordr "
                    "WHERE activity=?", a["code"])
        有效 = [o for o in os_ if o["status"] not in av.不算成交的状态]
        取消 = len(os_) - len(有效)
        期内 = [o for o in 有效 if av.在活动期内(o["created"], a["start_d"], a["end_d"])]
        期外 = [o for o in 有效 if not av.在活动期内(o["created"], a["start_d"], a["end_d"])]
        实收 = sum(o["received"] or 0 for o in 期内)
        应收 = sum(o["payable"] or 0 for o in 期内)
        完成 = len([o for o in 期内 if o["status"] == "完成"])

        给, why = av.该不该给ROI(a["status"])
        roi_txt, roi_v = av.roi(实收, 已发生) if 给 else (f"「{a['status']}」不给 —— {why}", None)
        row = _nz(dict(
            活动=f"{a['name']}({a['code']})",     # **名字带编号** —— 名字给人看,编号给系统连
            类型=a["kind"], 状态=a["status"],
            活动期=f"{a['start_d']} ~ {a['end_d']}", 范围=a["shop"],
            先看这一句=av.一句话(a["name"], a["status"], 实收, 已发生,
                              len(期外), len(有效)),
            花了多少=dict(预算=round(a["budget"] or 0),
                        已发生=round(已发生), 已开票=round(已开票),
                        待开票=round(已发生 - 已开票) or None,
                        用了预算的=f"{已发生 / a['budget'] * 100:.0f}%" if a["budget"] else None),
            带来多少=dict(期内成交=len(期内),
                        实收=round(实收), 应收=round(应收),
                        走完的单=完成,
                        取消的=取消 or None,
                        **({"⚠️期外归因": f"{len(期外)} 单创建时间不在活动期内,"
                                         f"**没并进上面的成交** —— 要么归因错了,"
                                         f"要么活动日期错了,两种都得有人看一眼"}
                           if 期外 else {})),
            投入产出比=roi_txt,
            单均获客成本=av.单均(已发生, len(期内), "单均成本")[0],
            单均成交=av.单均(实收, len(期内), "单均成交")[0],
            _roi=roi_v))
        out.append(row)

    # 排名:**只排算得出 ROI 的**。算不出的单独列,不许当 0 排在最后 ——
    # 那会把「还没开始」和「效果最差」画上等号。
    有分 = sorted([x for x in out if x.get("_roi") is not None],
                  key=lambda x: -x["_roi"])
    没分 = [x for x in out if x.get("_roi") is None]
    for x in out: x.pop("_roi", None)
    return _nz(dict(
        活动数=len(out),
        排名=[dict(名次=i + 1, **x) for i, x in enumerate(有分)] or None,
        算不出投入产出的=没分 or None,
        这两列不能用={k: v for k, v in av.不可用的列.items()},
        口径=dict(成本=f"默认「{av.默认成本口径}」(实际记了账的,含待开票)",
                 成交=f"默认「{av.默认成交口径}」—— 投入产出要用真到账的钱,"
                     f"应收里有一部分永远收不回来",
                 排除="取消的单既不算收入也不占分母")))


def can_order(customer_id, kind="定制品订单", wearer_id=None):
    """**下单之前先问一句:这单能下吗?**

    定制订单要有**这个着装人**下单前的量体,而且不能超期。
    超期的记录**不是「参考值」,是「无效值」**(`12-成长与生命周期.md` 第五节)。

    结论有**三种**,不是两种:
      · 可以    前置齐了
      · 不可以  明确缺什么(没量体 / 超期)
      · **判不了** 不知道这一单是给谁做的 —— **判不了不等于可以**

    不传 wearer_id 时:客户名下只有一个在用着装人就用他;
    多个的话返回「判不了」并列出候选,**不替你挑一个** ——
    挑错的话这一单会拿着另一个人的尺寸去裁剪,而报表上完全正常。
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import knowledge.order_gate as og
    import knowledge.growth as gr

    me = whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    cid = (customer_id or "").strip()
    if not _rows2("SELECT 1 FROM customer WHERE id=?", cid):
        return dict(error=f"没有客户 {cid} —— **查无此人**,不是「这人不能下单」")
    today = _dt.date.today().isoformat()

    if not og.需要量体吗(kind):
        k, why = og.能不能下单(kind, None, None, None)
        return _nz(dict(结论=k, 理由=why, 订单类型=kind))

    ws = _rows("SELECT id,name,gender,birthday FROM wearer "
               "WHERE customer_id=? AND status='在用' ORDER BY id", cid)
    w = None
    if wearer_id:
        w = next((x for x in ws if x["id"] == (wearer_id or "").strip()), None)
        if not w:
            return dict(结论="判不了",
                        理由=f"着装人 {wearer_id} 不在 {cid} 名下(或已停用)",
                        名下有谁=[f"{x['name']}({x['id']})" for x in ws] or None)
    elif len(ws) == 1:
        w = ws[0]
    if not w:
        k, why = og.能不能下单(kind, None, None, None)
        return _nz(dict(结论=k, 理由=why, 订单类型=kind,
                        名下有谁=[f"{x['name']}({x['id']})" for x in ws] or None,
                        怎么办=("把 wearer_id 一起传进来再问一次。"
                               "**别让我替你挑** —— 定制是照着尺寸裁的")
                        if ws else "这个客户名下没有在用的着装人,先建档"))

    m = _rows("SELECT measured_at,tpl FROM measure_rec WHERE wearer_id=? "
              "AND measured_at<=? ORDER BY measured_at DESC LIMIT 1", w["id"], today + " 23:59")
    last = m[0]["measured_at"] if m else None
    exp = None
    if last and w["birthday"] and w["gender"]:
        try:
            exp = gr.measure_expired(w["gender"], w["birthday"], last[:10], today)
        except Exception:
            exp = None
    k, why = og.能不能下单(kind, w["name"], last, exp)
    return _nz(dict(
        结论=k, 理由=why, 订单类型=kind,
        着装人=f"{w['name']}({w['id']})",
        最近量体=last,
        复量口径=(f"{exp['已过天数']}/{exp['允许天数']} 天 · {exp['原因']}") if exp else None,
        名下有谁=[f"{x['name']}({x['id']})" for x in ws] if len(ws) > 1 else None,
        提醒=("「有个旧尺寸总比没有强」正是返工的来源 —— "
              "超期就要求复量,别将就") if k == "不可以" else None))


def my_workorders(status=None):
    """**我手上的工单** —— 工匠看自己的,工坊管事看本坊,总部看全部。

    带在制上限(`wip_limit`)和当前在制数:**接不接得下一件,这两个数说了算**,
    不用猜。逾期的排在最前。
    """
    import tasks as _tk
    me = whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    where, args, scope = _tk.visible_wo_scope(me)
    sql = (f"SELECT w.*, a.name aname, a.trade, a.wip_limit, a.workshop "
           f"FROM workorder w LEFT JOIN artisan a ON a.no=w.artisan WHERE {where}")
    if status: sql += " AND w.status=?"; args = args + [status.strip()]
    rows = _rows(sql + " ORDER BY w.due_date", *args)
    if not rows:
        return _nz(dict(范围=scope, 说明="这个范围里没有工单" +
                        (f"(状态={status})" if status else "")))
    today = _dt.date.today().isoformat()
    逾期 = [r for r in rows if (r.get("due_date") or "9999") < today
            and r.get("status") in ("在制", "待开工")]
    在制 = [r for r in rows if r.get("status") == "在制"]
    out = dict(
        范围=scope, 工单数=len(rows),
        先看这几件=(f"**{len(逾期)} 条逾期**" if 逾期 else "没有逾期"),
        在制=len(在制),
        清单=[_nz(dict(工单=r["id"], 工序=r.get("craft"), 订单=r.get("ref"),
                      师傅=f"{r.get('aname')}({r.get('artisan')})",
                      工种=r.get("trade"), 工坊=r.get("workshop"),
                      工期=f"{r.get('workdays')} 天",
                      开工=r.get("start_date"), 交期=r.get("due_date"),
                      状态=r.get("status"),
                      逾期=("**已过交期**" if (r.get("due_date") or "9999") < today
                            and r.get("status") in ("在制", "待开工") else None),
                      备注=r.get("note")))
              for r in rows[:30]])
    # 在制上限:接不接得下一件,这两个数说了算
    if me.get("role") == "工匠" and rows:
        lim = rows[0].get("wip_limit")
        if lim:
            out["还接不接得下"] = (
                f"在制 {len(在制)} / 上限 {lim} —— "
                + ("**满了,别再接**" if len(在制) >= lim else f"还能接 {lim - len(在制)} 件"))
            out["为什么有上限"] = ("手工活同时开太多件,每件都慢,而且**串味**"
                                  "(染色、绣线批次混起来)—— 上限是工艺约束,不是懒")
    return _nz(out)


def _rows2(sql, *a):
    """只取一列的裸元组 —— `_rows` 会过列名黑名单,这里只要 id,不必走那一遍。"""
    with sqlite3.connect(DB) as c:
        return c.execute(sql, a).fetchall()


def get_task(task_id):
    """看**一条任务**的详情。看不到别人的 —— 知道单号也看不到。

    单条查询最容易漏掉隔离:列表过滤了,详情按 id 直接取,
    于是知道单号就能看别人的活。这个洞不会报错,只会安静地漏。
    """
    import tasks as _tk, tasktypes as tt
    me = whoami()
    if not me: return dict(error="不知道现在是谁在问 —— 请先登录")
    r = _tk.get_task((task_id or "").strip(), me)
    if not r:
        return dict(error=f"没有 {task_id} 这条任务,或者它不在你看得到的范围里")
    return _nz({"任务号": r["id"], "类型": tt.norm(r.get("type")), "状态": r.get("status"),
                "内容": r.get("note"), "开始": r.get("start_ts"), "结束": r.get("end_ts"),
                "负责人": r.get("assignee_name") or r.get("advisor"),
                "挂的单据": r.get("ref_id"), "客户": r.get("customer_id"),
                "绑定活动": r.get("activity_code"), "总结": r.get("summary")})


def task_types():
    """九种任务类型,以及每种的数据规范:挂哪张单据、谁能派、完成时要不要传现场照。

    **派任务前先看这个** —— 类型决定了要填什么,填错了会被拒。
    """
    import tasktypes as tt
    return dict(说明="族决定谁派,ref 决定挂哪张单据 —— 这是两件事",
                类型=[{"名称": i["name"], "族": i["family"],
                      "要填": i["ref_label"] or "不挂单据",
                      "举例": i["ref_eg"] or "—",
                      "谁能派": "店长" if i["route"] == "manager" else "有归属顾问就自动派,没有则 agent 建议+店长确认",
                      "完成要传现场照": i["needs_photo"], "说明": i["desc"]}
                     for i in tt.BY_NAME.values()])


def dispatch_pool():
    """待分配池:客户已经约了,但系统没能自动派单的任务 —— **带 agent 的人选建议和依据**。

    只有店长看得到。顾问不负责分活,给他看只会让他以为该自己认领。
    """
    me = whoami()
    if not me: return dict(error="不知道现在是谁在问 —— 请先登录")
    if me.get("role") not in MANAGER_ROLES:
        return dict(说明="待分配由店长处理,你是顾问,这里看不到东西", 条数=0, 任务=[])
    import booking
    rs = booking.unassigned(None if me["role"] == "总部运营" else me.get("shop"))
    out = []
    for r in rs:
        sg = r.get("建议")
        out.append(_nz({"任务号": r["id"], "客户": r.get("customer_name"),
                        "类型": r.get("type"), "开始": r.get("start_ts"),
                        "内容": r.get("note"),
                        "为什么没自动派": (f"档案里的归属顾问是「{r.get('bind')}」,"
                                          f"但他已离职或不在本店" if r.get("bind")
                                          else "这个客户没有归属顾问"),
                        "建议人选": (sg or {}).get("name"),
                        "建议工号": (sg or {}).get("no"),
                        "建议依据": (sg or {}).get("why"),
                        "备选": [f"{a['name']}(在办 {a['load']})" for a in (sg or {}).get("alts", [])]}))
    return dict(条数=len(out), 说明="**建议不是决定** —— 要店长确认才算派出去", 待分配=out)


# ── 写工具:智能体代人执行 ────────────────────────────────────────
# 这几个是**真的写库**。安全不靠「不给写」,靠三条:
#
#   ① 身份来自签发方   —— 会话里的工号,不是模型说自己是谁。
#                        一句「我以店长身份执行」不能提权。
#   ② 权限和人一样      —— 走 tasks.py 里同一套判定,**和页面上点是同一份代码**。
#                        智能体不会因为「是智能体」而多一分权,也不会少一分。
#   ③ 每一笔都留痕      —— 台账里记着是智能体代谁做的,
#                        以后要查「这条是人点的还是它自己派的」查得出来。
#
# **顾问之间的隔离由 tasks.visible_scope 一处判定**,写工具也吃这一条:
# 顾问只能完成派给自己的,店长只能派给本店的人。
def _need_me():
    me = whoami()
    if not me: raise _NoIdentity()
    return me


class _NoIdentity(Exception): pass


def _agent_log(me, code, text):
    """台账里标明这一笔是**智能体代做**的。

    不标的话,人点的和它自己做的在台账上一模一样 ——
    出事之后想知道「这条是谁的主意」就查不出来了。
    """
    from oplog import log_op as _lg
    _lg(me["name"], "agent", "-", "—", "—", True, "AGENT_" + code,
        f"智能体代 {me['name']}({me['role']})执行:{text[:90]}", {"role": me.get("role")})


def assign_task(type, assignee, note, end, start=None, ref_id=None, activity_code=None):
    """**派一条任务**(真的写进去)。只有店长及以上能派,只能派给本店在职顾问。

    type 见 task_types();ref_id 填什么由类型决定
    (客户相关填客户号;订单跟踪填订单号;维保填维保单号;售后填售后单号;
    团建培训和日常运维不填)。assignee 写工号或姓名。时间 `YYYY-MM-DD HH:MM`。

    **动手之前先跟用户把人、时间、内容对一遍** —— 派错了和派对了在库里长得
    一模一样,等发现的时候顾问已经去做了。
    """
    import tasks
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在派 —— 请先登录")
    # **权限先判,再解析人名。** 反过来的话,顾问调这个会收到
    # 「找不到周叙」—— 而真因是「你没这个权限」。
    # 顾问看到「找不到」会去核对名字拼写,那条路是死的。
    # **错误信息要指向原因,不是指向症状。**
    if me.get("role") not in tasks.MANAGER_ROLES:
        return dict(error=f"这个动作须由店长及以上操作,你是「{me.get('role')}」")
    # 收件人写姓名的,先换成工号;**同名认不出就报错,不猜**
    who = (assignee or "").strip()
    pool = tasks.my_staff(me)
    hit = [p for p in pool if p["no"] == who] or [p for p in pool if p["name"] == who]
    if len(hit) != 1:
        return dict(error=(f"找不到「{who}」" if not hit else f"有 {len(hit)} 个人叫「{who}」,请给工号"),
                    可派的人=[f"{p['name']}({p['no']})" for p in pool])
    r = tasks.assign_task(_nz(dict(type=type, assignee_no=hit[0]["no"], note=note, end=end,
                                   start=start, ref_id=ref_id, activity_code=activity_code)), me)
    if r.get("ok"): _agent_log(me, "ASSIGN", r.get("reason", ""))
    return r


def dispatch_task(task_id, assignee=None):
    """**把待分配池里的单分出去**(真的写进去)。不给 assignee 就采纳 agent 自己的建议。

    只能分**还没派出去的**单 —— 已经派给别人的要改派,那是另一个动作:
    悄悄换掉负责人会让原来那个人的列表凭空少一行。
    """
    import tasks, booking
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在分 —— 请先登录")
    # **权限先判,再解析人名。** 反过来的话,顾问调这个会收到
    # 「找不到周叙」—— 而真因是「你没这个权限」。
    # 顾问看到「找不到」会去核对名字拼写,那条路是死的。
    # **错误信息要指向原因,不是指向症状。**
    if me.get("role") not in tasks.MANAGER_ROLES:
        return dict(error=f"这个动作须由店长及以上操作,你是「{me.get('role')}」")
    to = (assignee or "").strip()
    if not to:
        t = _rows("SELECT * FROM schedule WHERE id=?", (task_id or "").strip())
        if not t: return dict(error=f"没有任务 {task_id}")
        sg = booking.suggest(t[0])
        if not sg:
            return dict(error="这个门店没有在职顾问可派,也提不出建议 —— "
                              "**硬凑一个人出来比说「提不出」有害得多**")
        to = sg["no"]
    else:
        pool = tasks.my_staff(me)
        hit = [p for p in pool if p["no"] == to] or [p for p in pool if p["name"] == to]
        if len(hit) != 1:
            return dict(error=f"找不到「{to}」或有重名",
                        可派的人=[f"{p['name']}({p['no']})" for p in pool])
        to = hit[0]["no"]
    r = tasks.dispatch(dict(id=task_id, assignee_no=to), me)
    if r.get("ok"): _agent_log(me, "DISPATCH", r.get("reason", ""))
    return r


def reassign_task(task_id, assignee, reason):
    """**改派**:把一条已经派出去的任务转给另一个人(真的写进去)。

    和 dispatch_task 的区别是**有人的活被拿走了** ——
    dispatch 分的是没人管的单,谁也没损失;改派是从小张手上拿走给小李。

    所以理由必填。原负责人那边仍然看得见这条,标着是谁改派的、为什么 ——
    **不让他的列表凭空少一行**。

    ⚠️ 动手之前先问清楚:为什么要改派、原负责人知不知道。
    """
    import tasks
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在改派 —— 请先登录")
    # **权限先判,再解析人名。** 反过来的话,顾问调这个会收到
    # 「找不到周叙」—— 而真因是「你没这个权限」。
    # 顾问看到「找不到」会去核对名字拼写,那条路是死的。
    # **错误信息要指向原因,不是指向症状。**
    if me.get("role") not in tasks.MANAGER_ROLES:
        return dict(error=f"这个动作须由店长及以上操作,你是「{me.get('role')}」")
    who = (assignee or "").strip()
    pool = tasks.my_staff(me)
    hit = [p for p in pool if p["no"] == who] or [p for p in pool if p["name"] == who]
    if len(hit) != 1:
        return dict(error=(f"找不到「{who}」" if not hit else f"有 {len(hit)} 个人叫「{who}」,请给工号"),
                    可派的人=[f"{p['name']}({p['no']})" for p in pool])
    r = tasks.reassign(dict(id=task_id, assignee_no=hit[0]["no"], reason=reason), me)
    if r.get("ok"): _agent_log(me, "REASSIGN", r.get("reason", ""))
    return r


def finish_task(task_id, summary):
    """**把任务标记完成**(真的写进去)。日程总结必填。

    **只能完成派给自己的** —— 谁做的谁点完成,别人代点等于台账上写了
    一件没发生的事。需要现场照的类型(上门沟通/团建培训/日常运维/维保/售后)
    要先在页面上传照片,这里传不了图。
    """
    import tasks
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁 —— 请先登录")
    r = tasks.finish_task(dict(id=task_id, summary=summary), me)
    if r.get("ok"): _agent_log(me, "FINISH", r.get("reason", ""))
    return r


def check_write(action, fields=None):
    """**这件事业务允不允许做** —— 不写库,只跑一遍真正的校验器。

    为什么要有它:顾问问「客户姓名还没问到,能不能先建档回头补」,
    实测智能体答「**可以的,系统设计就是这么打的**」,还编了一套
    account/customer 分层的架构理由 —— 而 rules.validate_customer 返回的是
    `NEED_NAME 客户姓名必填`。它一个工具都没调,因为**没有任何工具能告诉它业务规则**。

    编造建立在真事实上(账户与门店档案确实分层),所以读起来完全可信,最难抓。

    ## 为什么是「跑校验器」而不是「把规则写进提示词」

    把规则抄进提示词就是第二份手抄件,业务改了规则、提示词不会跟着改。
    这里直接调 backend/rules.py —— **和真实写接口用的是同一个函数**,
    所以「工具说不行」和「真去建会被拒」永远是同一件事。

    ## fields 里的 role 是**查询参数,不是授权主张**

    这个区分很重要,而且它决定了 role 该不该从会话取:

      · **写接口**(create_appointment / resolve_combo)的 role 是**授权主张** ——
        「我以店长身份执行」。它必须从服务端会话取,否则谁都能自称店长。
      · **check_write 的 role 是查询条件** —— 「**如果是**店长,允不允许?」
        它不执行任何动作,所以传谁都无害;而且顾问问「店长能不能补录」是个
        完全正当的问题,必须答得了。

    所以这个工具照旧收 role,而且**默认按最低权限(顾问)算** ——
    不传就按最保守的答,免得给出一个「你其实做不到」的乐观回答。

    ⚠️ **已知约定(不是结构)**:智能体调工具时**没有身份** ——
    MCP 工具跑在 CLI 拉起的子进程里,拿不到后台的登录会话。
    所以 check_write 答的永远是「如果是这个角色」,不是「你这个人」。
    真要执行,还得本人**确实**有那个角色,那一关在写接口上,由会话把着。
    这条写进了边界审计的**约定**类,不冒充结构。

    ## 它不写库

    validate_* 都是纯函数,只读现有客户做重复判定。见边界审计「check_write 不写库」。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import rules as _r
    d = dict(fields or {})
    # **说清楚是按哪个角色算的,以及这个角色是谁给的。**
    # 智能体调工具时没有身份(见 docstring 里那条约定),所以它答的永远是
    # 「如果是这个角色」。不在返回里标出来的话,「如果是店长就能」和「你现在能」
    # 在输出上分不开 —— 而后者是承诺,前者只是查规则。
    _given = (d.pop("role", None) or "").strip()
    role = _given or "顾问"
    _how = (f"{role}(你指定的角色 —— 这是「**如果是**{role}」的查询,"
            f"不代表提问的人就是{role})" if _given
            else "顾问(没指定,**按最低权限算**)")
    act = (action or "").strip()
    if act in ("建档", "新建客户", "customer", "create_customer"):
        ex = _rows("SELECT id,name,phone,shop,birthday,addr FROM customer")
        ok, code, why, sus = _r.validate_customer(d, ex, actor_role=role)
        out = {"能不能做": "能" if ok else "不能", "编码": code, "理由": why or "校验通过",
               "以什么角色判的": _how}
        if sus:
            out["疑似重复"] = [dict(id=x["id"], name=x["name"], shop=x.get("shop")) for x in sus]
            out["该怎么办"] = "转店长确认后再建档 —— 系统不替人做这个判断"
        return _nz(out)
    if act in ("预约", "补录预约", "appointment", "create_appointment"):
        ok, code, why = _r.validate_appointment(d, actor_role=role)
        return _nz({"能不能做": "能" if ok else "不能", "编码": code,
                    "理由": why or "校验通过", "以什么角色判的": _how})
    return {"error": f"不认识的动作「{action}」", "支持": ["建档", "预约"],
            "note": "只覆盖这两类写入的业务规则;别的动作请走后台审批链"}


def get_review_queue(top=15):
    """看**待核实队列**:哪些组合被问到了却没有依据,按被问次数排。

    队列是「被真正问到」才进的 —— 所以它同时回答了一个运营真正关心的问题:
    **在还没验证过的那 1274 格里,顾问实际会撞上哪几十格。**
    核实工作量由真实需求决定,不由矩阵大小决定。

    这个工具**只读队列**。核实回填在后台做(`/api/combo-resolve`),不在工具层 ——
    「工具层一个写接口都没有」那条保证不能为了方便就破。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import combo_review as _cr
    done = {(r["craft"], r["material"]) for r in
            _rows("SELECT craft,material FROM craft_combo WHERE rule='人工确认'")}
    q = _cr.queue(top=int(top or 15), resolved=done)
    if not q:
        return {"hit": 0, "note": "队列是空的 —— 还没有人问到没依据的格子,"
                                  "或者问到的都已经核实回填了"}
    return {"hit": len(q), "rows": [_nz(r) for r in q],
            "note": "按**被问次数**排,最常被问的最该先核。"
                    "核完一格用后台的「核实回填」写回去,那一格就从队列里消失。"
                    "**这个队列只说「谁被问了」,不说「答案是什么」** —— 答案要人去打样。"}


def kb_detail(code):
    """按编码取某一条的完整内容"""
    r=_rows("SELECT * FROM craft WHERE code=?",code)
    if not r: return {"error":f"没有编码 {code} 这一条"}
    return _nz(_with_material(r[0]))

def _resolve(x, cat):
    """把「云锦」「MT02」都解析成同一条。模型不知道编码,让它猜编码是工具设计的错误 ——
    实测过:它会拿着猜错的编码得到一个关于完全不同组合的答案,然后自信地讲出来。"""
    x=(x or "").strip()
    if not x: return None,"空值"
    r=_rows("SELECT code,name,cat FROM craft WHERE code=? AND cat=?",x.upper(),cat)
    if r: return r[0],None
    r=_rows("SELECT code,name,cat FROM craft WHERE cat=? AND (name=? OR alias=?)",cat,x,x)
    if r: return r[0],None
    r=[q for q in _rows("SELECT code,name,alias,cat FROM craft WHERE cat=?",cat)
       if x in (q["name"] or "") or x in (q["alias"] or "") or (q["name"] or "") in x]
    if len(r)==1: return r[0],None
    if len(r)>1:
        return None,f"「{x}」在{cat}里对应多条:{[q['name'] for q in r]},请用更精确的名称或编码"
    names=[q["name"] for q in _rows("SELECT name FROM craft WHERE cat=?",cat)]
    return None,f"知识库里没有叫「{x}」的{cat}。现有{cat}:{names}"

def _combo_caveat(d):
    """给相容判定加**依据等级**;没有依据的那一档,**不再给结论**。

    ## 这里改过两版,第二版是产品决策的结果

    第一版:`rule='—'` 的 1274 格返回「可以」,只是多标一句「默认放行,没有依据」。
    第二版(现在):**这一档不给结论了**,verdict 改成「待核实」,并记一笔待办。

    改的理由是**偏错的代价不对称**:说「可以」结果做不出来,赔的是工期、料钱和客户;
    说「待核实」最多是多打一个电话。而这 1274 格**没有任何人验证过** ——
    它们只是「没命中任何禁止规则」,和「确认可以」完全是两回事。

    ## 但光不给结论会把风险赶到看不见的地方

    顾问常问的组合里有 30% 落在这一档。每问三次就有一次「待核实」,
    顾问不会真的每三次去找一次工艺负责人 —— 他会开始凭经验答,
    **风险从系统里被赶到人身上,而且从此看不见**。

    所以配了回流:**被真正问到的那一格记一笔进待办**(见 combo_review.py),
    运营核实后回填。待办量由真实需求决定,而不是由矩阵大小决定。

    ## 记一笔是「旁路」,不是模型在写

    追加的是日志文件,不碰业务库 —— 「工具层一个写接口都没有」那条保证不受影响。
    """
    ru=(d.get("rule") or "").strip()
    if d.get("verdict")=="未定义": return d
    d=dict(d)
    if ru=="人工确认":
        d["依据等级"]="人工确认 —— 打样验证过,可以直接说"
    elif ru.startswith("R"):
        d["依据等级"]=f"规则推导({ru})—— 从成文通则推出,**这一格没有单独打样验证**"
    else:
        # **不给结论。** 原来的 verdict(多半是「可」)挪到旁边留痕,不作为答案。
        d["原始默认值"]=d.get("verdict")
        d["verdict"]="待核实"
        d["依据等级"]=("**没有依据,不给结论** —— 这一格只是没命中任何禁止规则,"
                     "没有任何人验证过。「没查到禁止」和「确认可以」是两回事。")
        d["该怎么办"]=("如实告诉顾问这一格**还没核实过**,不要说可以也不要说不可以;"
                     "已经自动记入待核实队列,工艺负责人核完会回填。"
                     "客户急着要答复的话,建议换一个已确认的工艺或面料。")
        try:
            import combo_review as _cr
            _cr.record_ask(d.get("craft_code") or d.get("craft"),
                           d.get("material_code") or d.get("material"),
                           craft_name=d.get("craft"), material_name=d.get("material"))
        except Exception:
            pass      # 记不上待办不能影响回答本身 —— 旁路不是主路
    return d

def kb_combo(craft, material):
    """查某工艺能不能用在某面料上。工艺名/面料名或编码都接受。返回 可/需评估/不可/未定义。"""
    k,e1=_resolve(craft,"工艺")
    m,e2=_resolve(material,"材质")
    if e1: return {"error":e1}
    if e2: return {"error":e2}
    craft_code, material_code = k["code"], m["code"]
    r=_rows("SELECT verdict,reason,src_type,rule FROM craft_combo WHERE craft=? AND material=?",
            craft_code,material_code)
    if not r:
        return {"craft":k["name"],"material":m["name"],
                "resolved":f"{k['code']} {k['name']} × {m['code']} {m['name']}","verdict":"未定义",
                "note":"这一格组合约束尚未录入。**必须如实告知查不到,并建议转工艺负责人确认**,"
                       "不得自行推断可或不可。","src_type":None}
    d=r[0]; d.update(craft=k["name"],material=m["name"],
                     craft_code=k["code"], material_code=m["code"],
                     resolved=f"{k['code']} {k['name']} × {m['code']} {m['name']}")
    return _nz(_combo_caveat(d))

def kb_tables(topic=None):
    """决策表 —— 「客户说 X 该推什么」这类问题的答案在这里,不在条目里。"""
    rs=_rows("SELECT * FROM kb_table ORDER BY topic")
    if topic: rs=[r for r in rs if topic in r["topic"]]
    if not rs:
        return {"hit":0,"available":[r["topic"] for r in _rows("SELECT topic FROM kb_table")],
                "note":"没有这个主题的决策表,看 available 里有哪些"}
    out=[]
    for r in rs:
        out.append(dict(topic=r["topic"], head=json.loads(r["head"]),
                        rows=json.loads(r["rows"]), src=r["src_file"], src_type="demo"))
    return {"hit":len(out),"tables":out}

def kb_coverage():
    """相容矩阵的完成度 —— 让「没有数据」成为一个看得见的状态"""
    ks=_rows("SELECT code FROM craft WHERE cat='工艺'"); ms=_rows("SELECT code FROM craft WHERE cat='材质'")
    n=_rows("SELECT COUNT(*) c FROM craft_combo")[0]["c"]
    tot=len(ks)*len(ms)
    # **三类分开数。** 原来把「不是人工确认的」一律算作「规则推导」——
    # 而其中 1274 格的 rule 是 `—`,**根本没有依据**,是「没命中任何禁止规则 → 默认可」。
    # 把它们报成「规则推导」是在美化:一个没人验证过的结论被说成有依据的。
    # 兜底方向选错,未知就会被打扮成已知 —— 这里未知被默认算成了「可以做」。
    by={"人工确认":0,"规则推导":0,"默认放行(无依据)":0}
    for r in _rows("SELECT rule,COUNT(*) c FROM craft_combo GROUP BY rule"):
        ru=(r["rule"] or "").strip()
        k=("人工确认" if ru=="人工确认" else
           "规则推导" if ru.startswith("R") else "默认放行(无依据)")
        by[k]+=r["c"]
    return {"工艺数":len(ks),"材质数":len(ms),"总格数":tot,"已定义":n,"未定义":tot-n,
            "完成度":f"{n/tot*100:.0f}%","来源":by,
            "note":"**「默认放行(无依据)」不等于验证过** —— 那是「没命中任何禁止规则」"
                   "的兜底结果,没有人打样确认过。对客户说这类结论必须带上这句限定。"
                   f"所有「不可」和「需评估」都有依据;而「可」里有 {by['默认放行(无依据)']} 格是默认放行。"}


# ── 门店业务数据(shop 服务)—— 顾问和值班同学天天要查的三样 ────────────
def get_order(order_id=None, customer=None):
    """订单全链路。**金额勾稽当场自检**,对不上的直接在返回里标出来 ——
    藏着不说,顾问就会拿一个错的数字去跟客户对账。"""
    if not (order_id or customer):
        return {"error": "要么给订单号,要么给客户号/姓名"}
    if customer and not order_id:
        cs=_rows("SELECT id,name FROM customer WHERE id=? OR name=?",customer,customer)
        if not cs: return {"error":f"没有客户「{customer}」"}
        rs=_rows("SELECT id,kind,status,prd_status,amount,received,refund_status,created"
                 " FROM ordr WHERE customer_id=? ORDER BY created DESC",cs[0]["id"])
        return {"客户":cs[0]["name"],"hit":len(rs),"orders":rs,
                "note":"这是该客户的订单清单;要看某一单的明细,拿 id 再调一次。"}
    o=_rows("SELECT * FROM ordr WHERE id=?",order_id)
    if not o: return {"error":f"没有订单 {order_id}"}
    o=o[0]
    cu=_rows("SELECT name,phone FROM customer WHERE id=?",o["customer_id"])
    items=_rows("SELECT sku,name,tag,price,qty,spu,base_amount,custom_amount,total"
                " FROM ordr_item WHERE order_id=?",order_id)
    af=_rows("SELECT id,kind,status,reason,amount,created FROM aftersale WHERE order_id=?",order_id)
    # 勾稽自检
    bad=[]
    g,f,a=o["goods_amount"] or 0,o["freight"] or 0,o["amount"] or 0
    if abs(g+f-a)>0.01: bad.append(f"商品额 {g} + 运费 {f} ≠ 订单额 {a}")
    it=round(sum(x["total"] or 0 for x in items),2)
    if items and abs(it-g)>0.01: bad.append(f"订单行合计 {it} ≠ 商品额 {g}")
    if (o["received"] or 0)>(o["payable"] or 0)+0.01:
        bad.append(f"已收 {o['received']} > 应付 {o['payable']}")
    tl=[(k,o[k]) for k in ("created","paid_at","audit_at","produced_at","shipped_at",
                           "finished_at","cancelled_at") if o[k]]
    for (k1,v1),(k2,v2) in zip(tl,tl[1:]):
        if v2<v1: bad.append(f"时间倒挂:{k2}({v2}) 早于 {k1}({v1})")
    return {"订单":o["id"],"客户":(cu[0]["name"] if cu else o["customer_id"]),
            "类型":o["kind"],"页面状态":o["status"],"PRD状态":o["prd_status"],
            "状态口径":"页面按设计稿 10 档,PRD 按状态机 6 档,两套并存且有显式映射",
            "门店":o["shop"],"顾问":o["advisor"],"来源":o["source"],"配送":o["delivery"],
            "金额":dict(商品额=g,运费=f,订单额=a,应付=o["payable"],已收=o["received"],
                       退款状态=o["refund_status"]),
            "时间线":dict(tl),"订单行":items,"售后":af,
            "勾稽异常":bad,
            "note":("勾稽有异常,**先核对再答复客户**" if bad else "金额与时间线勾稽一致")}


def get_stock(spu=None, sku=None, material=None, craft=None):
    """现货。三种问法:某商品有没有货 / 某面料有多少米 / **这个工艺有哪些现货面料可选**。

    第三种是工期推算那条「改用现货面料可压缩 20 天」真正落地的地方 ——
    在此之前系统根本不知道哪些面料有现货,那条建议只是一句空话。
    """
    if sku:
        r=_rows("SELECT code,spu,spec,color,size,price,stock,locked,status FROM sku WHERE code=?",sku)
        if not r: return {"error":f"没有 SKU {sku}"}
        d=r[0]; d["可用"]=(d["stock"] or 0)-(d["locked"] or 0)
        return d
    if spu:
        p=_rows("SELECT spu,name,kind,status FROM product WHERE spu=? OR name=?",spu,spu)
        if not p: return {"error":f"没有商品「{spu}」"}
        rs=_rows("SELECT code,spec,color,size,stock,locked,status FROM sku WHERE spu=?",p[0]["spu"])
        for x in rs: x["可用"]=(x["stock"] or 0)-(x["locked"] or 0)
        tot=sum(x["可用"] for x in rs)
        return dict(p[0],skus=rs,可用合计=tot,
                    note=("**全部零库存** —— 现货答不了,要走定制或补货" if tot<=0 else ""))
    if material:
        m,e=_resolve(material,"材质")
        if e: return {"error":e}
        r=_rows("SELECT code,name,unit,price,lead_days,stock_qty FROM material WHERE code=?",m["code"])
        if not r: return {"error":f"{m['name']} 不在物料表里"}
        d=r[0]; d["有现货"]=(d["stock_qty"] or 0)>0
        d["note"]=(f"现货 {d['stock_qty']} {d['unit']},可省掉 {d['lead_days']} 天备料"
                   if d["有现货"] else f"**无现货**,须备料 {d['lead_days']} 天")
        return d
    if craft:
        k,e=_resolve(craft,"工艺")
        if e: return {"error":e}
        rs=_rows("SELECT m.code,m.name,m.price,m.lead_days,m.stock_qty,cc.verdict,cc.rule"
                 " FROM material m JOIN craft_combo cc ON cc.material=m.code"
                 " WHERE m.cat='主料' AND cc.craft=? AND cc.verdict='可' AND m.stock_qty>0"
                 " ORDER BY m.stock_qty DESC",k["code"])
        return {"工艺":k["name"],"hit":len(rs),"现货且相容的面料":rs,
                "note":"按现货量排序。换成这里的面料可以把备料压到 1–3 天;"
                       "**但面料换了,质感与售价都会变,必须让客户确认**,不能替他决定。"}
    return {"error": "要给 spu / sku / material / craft 其中之一"}


def get_aftersale(order_id=None, customer=None, status=None):
    """售后记录。判责依据在 kb_tables 的「售后争议判定」表里,这里只给事实。"""
    q="SELECT a.*,c.name cust FROM aftersale a LEFT JOIN customer c ON c.id=a.customer_id WHERE 1=1"
    args=[]
    if order_id: q+=" AND a.order_id=?"; args.append(order_id)
    if customer:
        cs=_rows("SELECT id FROM customer WHERE id=? OR name=?",customer,customer)
        if not cs: return {"error":f"没有客户「{customer}」"}
        q+=" AND a.customer_id=?"; args.append(cs[0]["id"])
    if status: q+=" AND a.status=?"; args.append(status)
    rs=_rows(q+" ORDER BY a.created DESC",*args)
    if not rs:
        return {"hit":0,"note":"没有匹配的售后单。**查不到就说查不到**,不要推测客户提过什么。"}
    ext=sorted({r["ext_system"] for r in rs if r["ext_system"]})
    return {"hit":len(rs),"rows":rs,"外部系统":ext,
            "note":"判责标准见 kb_tables 的「售后争议判定」表,这里只提供事实,不下结论。",
            "⚠退款流水":"**售后退款和押金退款是两条流水,不要混。** "
                       "本系统只存押金退款的渠道明细(get_refund_trace / get_payment_flow,按押金单号查);"
                       "售后退款的渠道明细在" + ("、".join(ext) if ext else "外部系统") +
                       "里,**这里查不到,要如实告诉客户去哪查,不要拿押金流水冒充**。"}


def get_capacity(craft=None, workdays=None, from_date=None):
    """产能排期。不传 craft 就是全工坊负载概览(瓶颈在哪个工种)。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","knowledge"))
    import capacity as cap
    if not craft:
        return cap.overview(from_date)
    k,e=_resolve(craft,"工艺")
    if e: return {"error":e}
    r=cap.when_free(k["code"], float(workdays or 10), from_date)
    if not r.get("error"): r["工艺"]=k["name"]
    return r


def _names():
    return {r["code"]: r["name"] for r in _rows("SELECT code,name FROM craft")}


def kb_pattern(xz=None):
    """版型库 —— 一个形制有哪些版型、分几个裁片、出哪些码。"""
    q="SELECT * FROM pattern"; a=()
    if xz:
        k,e=_resolve(xz,"形制")
        if e: return {"error":e}
        q+=" WHERE xz=?"; a=(k["code"],)
    rs=_rows(q+" ORDER BY code",*a)
    if not rs:
        return {"hit":0,"note":f"「{xz}」这个形制还没有版型。**没有版型就裁不出来**,"
                              "不能在配置页上架,须先请版师建版。"}
    nm=_names()
    for r in rs:
        r["形制"]=nm.get(r["xz"],r["xz"])
        r["裁片"]=[dict(名称=p["name"],数量=p["qty"],说明=p["note"])
                  for p in _rows("SELECT * FROM pattern_piece WHERE pattern=?",r["code"])]
        r["尺码"]=r.pop("sizes").split(",")
    return {"hit":len(rs),"rows":rs,
            "note":"difficulty=改版难度。「极高」的(马面裙)腰围错了等于重做,不能放缝头改。"}


def kb_size(pattern, size=None):
    """某版型的成衣尺码表。**这是成衣尺寸,不是人体尺寸**,两者之差是放松量。"""
    p=_rows("SELECT * FROM pattern WHERE code=? OR name=?",pattern,pattern)
    if not p: return {"error":f"没有版型「{pattern}」,可先用 kb_pattern 查这个形制有哪些版型"}
    p=p[0]
    rs=_rows("SELECT size,item,value FROM size_spec WHERE pattern=?",p["code"])
    if size: rs=[r for r in rs if r["size"]==size]
    if not rs:
        return {"error":f"{p['name']} 没有 {size} 码,只有 {p['sizes']}",
                "note":"尺码不存在不是缺货,是这个版型裁不出来。"}
    out={}
    for r in rs: out.setdefault(r["size"],{})[r["item"]]=r["value"]
    return {"版型":p["name"],"尺码表":out,"量体模版":p["tpl"],
            "note":"成衣尺寸。推荐尺码要拿客户量体值比对后由版师定,系统只给建议。"}


def kb_bom(pattern, size, material, crafts=None, scope="局部"):
    """算料算钱 —— 这个配置要用哪些物料、各多少、物料成本多少、多久备齐。

    相容矩阵回答「能不能做」,这个回答「要多少料、多少钱、多久备齐」。
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","knowledge"))
    import derive_pattern as dp
    p=_rows("SELECT code FROM pattern WHERE code=? OR name=?",pattern,pattern)
    if not p: return {"error":f"没有版型「{pattern}」"}
    m,e=_resolve(material,"材质")
    if e: return {"error":e}
    kcs=[]
    for k in (crafts or []):
        r,e2=_resolve(k,"工艺")
        if e2: return {"error":e2}
        kcs.append(r["code"])
    return dp.estimate(p[0]["code"], size, m["code"], kcs, scope, craft_names=_names())


def fit_customers():
    """量过体的客户 —— 只有这些人能算推荐尺码。"""
    return {"rows": _rows(
        "SELECT c.id,c.name,MAX(r.method) method,COUNT(DISTINCT r.item) items,"
        " MIN(r.tpl) tpl_code,"
        # 体型特征挂**着装人**。这里按「该客户档案下的着装人」聚合 ——
        # 用于列表概览;真正推尺码时必须**指定是谁**,见 kb_fit。
        " (SELECT GROUP_CONCAT(feature,'、') FROM body_feature b"
        "  JOIN wearer w ON w.id=b.wearer_id WHERE w.customer_id=c.id) feature"
        " FROM customer c JOIN measure_rec r ON r.customer_id=c.id"
        " GROUP BY c.id,c.name ORDER BY c.name")}


def kb_fit(customer, pattern, wearer=None):
    """拿量体记录比对版型尺码表,给出推荐尺码和档位(标准码 / 调号 / 全定制)。

    **wearer 才是正确的粒度** —— 一个账户下几个人,尺寸和体型各不相同。
    只给 customer 时,退回到该账户的「本人」。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","knowledge"))
    import fitting
    cs=_rows("SELECT id,name FROM customer WHERE id=? OR name=?",customer,customer)
    if not cs: return {"error":f"没有客户「{customer}」"}
    cu=cs[0]
    p=_rows("SELECT code,name,xz,sizes,tpl FROM pattern WHERE code=? OR name=?",pattern,pattern)
    if not p: return {"error":f"没有版型「{pattern}」"}
    p=p[0]
    ms={r["name"]:r["value"] for r in _rows(
        "SELECT i.name,r.value FROM measure_rec r JOIN measure_item i ON i.code=r.item"
        " WHERE r.customer_id=?",cu["id"])}
    if not ms:
        return {"error":f"{cu['name']} 没有量体记录","档位":"需补量",
                "note":"没量过体就不能推荐尺码,**不要按身高体重猜**。"}
    mth=(_rows("SELECT method FROM measure_rec WHERE customer_id=? LIMIT 1",cu["id"]) or
         [{"method":"到店"}])[0]["method"]
    # ⚠️ **体型特征必须按着装人取,不能按客户档案取。**
    # 原来读的是 customer_id,而一条档案下可能有 3 个人 ——
    # 妈妈的「溜肩」会被算到 3 岁儿子头上,而规则是「有明显体型特征即全定制」,
    # 于是孩子被直接推成全定制:**加价又加工期**。
    # 没指定着装人时,退回到该账户的「本人」—— 而不是把全家的特征并起来。
    _wid = wearer or _rows("""SELECT a.self_wearer_id w FROM customer k
                              JOIN account a ON a.id=k.account_id WHERE k.id=?""", cu["id"])
    _wid = wearer if wearer else (_wid[0]["w"] if _wid else None)
    fs=[r["feature"] for r in _rows("SELECT feature FROM body_feature WHERE wearer_id=?", _wid)]
    specs={}
    for r in _rows("SELECT size,item,value FROM size_spec WHERE pattern=?",p["code"]):
        specs.setdefault(r["size"],{})[r["item"]]=r["value"]
    out=fitting.recommend(ms,p["code"],p["sizes"].split(","),specs,p["xz"],mth,fs)
    out.update(客户=cu["name"],版型=p["name"])
    return out


def _lt():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","knowledge"))
    import leadtime; return leadtime


def kb_lead(pattern, size, material, crafts=None, scope="局部", workers=2,
            need_date=None, from_date=None):
    """算工期。给了 need_date 就顺便倒推来不来得及。"""
    lt=_lt()
    p=_rows("SELECT code FROM pattern WHERE code=? OR name=?",pattern,pattern)
    if not p: return {"error":f"没有版型「{pattern}」"}
    m,e=_resolve(material,"材质")
    if e: return {"error":e}
    kcs=[]
    for k in (crafts or []):
        r,e2=_resolve(k,"工艺")
        if e2: return {"error":e2}
        kcs.append(r["code"])
    kw=dict(pattern=p[0]["code"], size=size, material=m["code"], crafts=kcs,
            scope=scope, workers=int(workers or 2), craft_names=_names(),
            from_date=from_date)
    return lt.deadline(need_date, None, **kw) if need_date else lt.estimate(**kw)


# ── 着装人与成长推算 ────────────────────────────────────────────────────
# 这两个工具是**只读**的,而且**同意状态是硬门**:没有有效同意就拿不到身体数据,
# 也算不出推算 —— 不是「模型应该守规矩」,是「不守也拿不到」。
# 这个区别在本项目里付过学费:一条靠约定守着的边界,换个模型就破了。
_GROWTH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")
if _GROWTH_DIR not in sys.path: sys.path.insert(0, _GROWTH_DIR)

def _consent_ok(wearer_id, scope="身体数据"):
    r = _rows("""SELECT 1 FROM consent WHERE wearer_id=? AND scope=? AND revoked_at IS NULL""",
              wearer_id, scope)
    return bool(r)

def _wearer(wid):
    r = _rows("SELECT * FROM wearer WHERE id=?", wid)
    return r[0] if r else None


def _mask(phone):
    """手机号对外一律脱敏。顾问要的是「认得出是哪个号」,不是号本身。"""
    p = (phone or "").strip()
    return f"{p[:3]}****{p[-4:]}" if len(p) >= 7 else "—"


# 当前生效的协议版本。**字段有值不等于同意有效** ——
# 条款改版之后,旧版本的同意就该重新取,而这件事没人比对就永远不会发生。
TOS_NOW, PRIVACY_NOW = "v2.3", "v1.5"
# 账户状态 → 顾问该怎么办。**状态是给行动看的,不是给人看的。**
ACCT_ACTION = {
    "正常":   None,
    "锁定":   "账户已锁定(连续输错密码)。**不要在电话里帮客户改密码或绕过锁定** —— "
              "让客户自助解锁,或按门店流程走身份核验。",
    "注销中": "客户已申请注销,正在冷静期。**不要推进新订单、不要做营销触达**;"
              "如果还有在办的单,先问清楚是要撤回注销还是把单收尾。",
    "已注销": "账户已注销,**个人数据已删除**。查不到尺寸、偏好、着装人是正常的 —— "
              "不要凭印象补,也不要让客户「报一下就行」。要下单请重新注册。",
}


def _account(aid):
    """账户的对外视图。**列名写死,不用星号** —— 星号会把 pwd_* 带出来,
    而 _rows 那道锁会当场抛异常。这里主动只取该给的四列。

    login_name 本身也是登录凭据,所以只回答「有没有自设」,不回答「叫什么」。
    """
    if not aid: return None
    # 列名写死,不用星号 —— 星号会把 pwd_* 带出来,_rows 那道锁会当场抛异常
    r = _rows("SELECT id, phone, login_name, status, created, last_login, contact_pref, "
              "default_addr, home_shop, tos_version, privacy_version, marketing_consent, "
              "closed_at, purge_at, locked_until FROM account WHERE id=?", aid)
    if not r: return None
    a = r[0]
    n = _rows("SELECT count(*) n FROM wearer WHERE account_id=?", aid)[0]["n"]
    docs = _rows("SELECT count(*) n FROM customer WHERE account_id=?", aid)[0]["n"]
    stale = [x for x, cur, col in (("服务条款", TOS_NOW, "tos_version"),
                                   ("隐私政策", PRIVACY_NOW, "privacy_version"))
             if (a[col] or "") != cur]
    d = {"账户": a["id"], "手机号": _mask(a["phone"]),
         "已自设账号密码": bool(a["login_name"]),
         "状态": a["status"], "注册于": a["created"], "最近登录": a["last_login"],
         "该账户下着装人": n, "关联门店档案": docs,
         # 这几样是**给行动用的**,不是摆着看的
         "联系方式偏好": a["contact_pref"],
         "默认地址": a["default_addr"], "常用门店": a["home_shop"],
         "营销触达同意": bool(a["marketing_consent"])}
    if stale:
        d["协议需重新取得同意"] = (
            f"{'、'.join(stale)}已改版(当前 {TOS_NOW} / {PRIVACY_NOW},"
            f"账户是 {a['tos_version']} / {a['privacy_version']})。"
            "**改了条款而没重新取得同意,等于没同意** —— 下单前请客户在小程序上重新确认。")
    if ACCT_ACTION.get(a["status"]):
        d["该怎么办"] = ACCT_ACTION[a["status"]]
    if a["status"] == "锁定":
        d["解锁时间"] = a["locked_until"]
    if a["status"] in ("注销中", "已注销"):
        d["注销申请于"] = a["closed_at"]; d["数据清除于"] = a["purge_at"]
    return d

def get_wearer(customer=None, wearer_id=None, account=None):
    """着装人档案:一个账号下都有谁、各自量体到什么时候、哪些该复量了。"""
    import growth
    from datetime import date
    today = date(2026, 8, 31)
    if wearer_id:
        ws = [w for w in [_wearer(wearer_id)] if w]
    elif account:
        # 手机号是账户主标识,所以直接支持拿手机号查 —— 顾问手边只有手机号的时候最常见
        ws = _rows("""SELECT w.* FROM wearer w JOIN account a ON a.id=w.account_id
                      WHERE a.id=? OR a.phone=? OR a.login_name=? ORDER BY w.id""",
                   account, account, account)
    elif customer:
        ws = _rows("""SELECT w.* FROM wearer w JOIN customer c ON c.id=w.customer_id
                      WHERE w.customer_id=? OR c.name=? ORDER BY w.id""", customer, customer)
    else:
        return {"error": "给 account(手机号 / 账户号)、customer(客户号或姓名)"
                         "或 wearer_id 其中之一"}
    if not ws: return {"error": "查不到这个着装人", "hit": 0}
    out = []
    for w in ws:
        ok = _consent_ok(w["id"])
        d = {"着装人": w["id"], "姓名": w["name"], "性别": w["gender"],
             "关系": w["relation"], "生日": w["birthday"],
             # **身份绑账户,不绑门店档案** —— 同一个人在不同店建过档就是两条档案,
             # 而账户只有一个。「关联门店档案 > 1」正是客户合并要处理的那种情况。
             "账户": _account(w.get("account_id")),
             "年龄": round(growth.age_at(w["birthday"], today), 1) if w["birthday"] else None,
             "身体数据同意": "有效" if ok else "**缺失或已撤回**"}
        if not ok:
            d["量体"] = "无法提供 —— 没有有效的身体数据同意"
            out.append(d); continue
        recs = _rows("""SELECT item,value,measured_at,method FROM measure_rec
                        WHERE wearer_id=? ORDER BY measured_at DESC""", w["id"])
        d["量体项数"] = len(recs)
        h = next((r for r in recs if r["item"] == "MI01"), None)
        if h:
            e = growth.measure_expired(w["gender"], w["birthday"], h["measured_at"][:10], today)
            d["最近身高"] = h["value"]
            d["量体日"] = h["measured_at"][:10]
            d["量体是否过期"] = e
        if w["parent_a"]:
            ps = [_wearer(w["parent_a"]), _wearer(w["parent_b"])]
            d["父母身高"] = [p["height"] for p in ps if p]
        out.append(d)
    return {"hit": len(out), "着装人": out,
            "提示": "「量体是否过期」为真时,**下单前必须拦下要求复量** —— 超期的记录不是参考值,是无效值。"}

def forecast_growth(wearer_id, target_date=None, months=12):
    """推算某着装人到某天的身高与留量建议。**不给围度点估计。**"""
    import growth
    from datetime import date, timedelta
    today = date(2026, 8, 31)
    w = _wearer(wearer_id)
    if not w: return {"error": f"着装人 {wearer_id} 不存在"}
    if not _consent_ok(w["id"]):
        return {"error": "没有有效的身体数据同意,不能推算", "着装人": w["name"]}
    age = growth.age_at(w["birthday"], today) if w["birthday"] else None
    if age is not None and age < 14 and not _consent_ok(w["id"], "未成年人"):
        return {"error": "不满十四周岁,缺少监护人同意,不能推算", "着装人": w["name"]}
    h = _rows("""SELECT value,measured_at FROM measure_rec WHERE wearer_id=? AND item='MI01'
                 ORDER BY measured_at DESC LIMIT 1""", wearer_id)
    if not h: return {"error": "这个着装人没量过身高,无法推算", "着装人": w["name"]}
    tgt = target_date or (today + timedelta(days=int(30.4 * months))).isoformat()
    par = None
    if w["parent_a"]:
        ps = [_wearer(w["parent_a"]), _wearer(w["parent_b"])]
        hs = [p["height"] for p in ps if p and p["height"]]
        if len(hs) == 2: par = tuple(hs)
    r = growth.forecast(w["gender"], w["birthday"], h[0]["value"], h[0]["measured_at"][:10],
                        tgt, parents=par)
    r["着装人"] = w["name"]
    r["留成长量"] = growth.allowance(r["长高"])
    r["话术"] = growth.sales_line(w["name"], r["长高"], 5.0) if r["长高"] > 0 else None
    g = _rows("""SELECT item,value FROM measure_rec WHERE wearer_id=? AND item IN ('MI03','MI04')
                 ORDER BY measured_at DESC""", wearer_id)
    if g and r["长高"] > 0:
        r["围度"] = {"MI03": "胸围", "MI04": "腰围"}
        r["围度区间"] = {{"MI03": "胸围", "MI04": "腰围"}[x["item"]]:
                        growth.girth_band(x["value"], h[0]["value"], r["预测身高"])
                        for x in g}
        r.pop("围度")
    return r

# ── 售后判责的现场 ──────────────────────────────────────────────────────
# **这个工具只给事实,不给判责结论** —— 和 get_aftersale 是同一条规矩。
# 判定表在 kb_tables 的「售后争议判定」和 09-养护与售后.md 第五节,要另外查。
#
# 09 那份文档第六节自己写着这个能力该长什么样:
# 「助手查记录、给判据、拟话术;**人做决定**」—— 涉及退换和赔付,结论必须由人给。
# 所以工具的职责边界就是「把现场摆全」,摆全之后判给谁,是人的事。
#
# 现场包括四样,少一样就判不了:
#   ① 这件是什么(面料 / 工艺 / 什么时候交付的)
#   ② 客户报的问题是什么
#   ③ 量体记录全不全、是到店还是远程 —— 尺寸类判责全看这个
#   ④ 交付时有没有书面告知过 —— 特性类判责全看这个
def get_maintain(maintain_id=None, customer=None, status=None):
    """售后维修工单的现场。**只给事实,判责结论要另外查判定表。**"""
    where, args = [], []
    if maintain_id: where.append("m.id=?"); args.append(maintain_id)
    if customer: where.append("(m.customer_id=? OR c.name=?)"); args += [customer, customer]
    if status: where.append("m.status=?"); args.append(status)
    rows = _rows("SELECT m.*, c.name cname FROM maintain m "
                 "LEFT JOIN customer c ON c.id=m.customer_id"
                 + (" WHERE " + " AND ".join(where) if where else "")
                 + " ORDER BY m.created DESC", *args)
    if not rows: return {"hit": 0, "error": "查不到这样的维修工单"}
    out = []
    for m in rows[:12]:
        o = _rows("SELECT id,kind,status,amount,created FROM ordr WHERE id=?", m["order_id"])
        it = _rows("SELECT oi.spu, oi.name, p.remark, pc.xz, pc.mt_opts, pc.kf_opts "
                   "FROM ordr_item oi LEFT JOIN product p ON p.spu=oi.spu "
                   "LEFT JOIN product_custom pc ON pc.spu=oi.spu "
                   "WHERE oi.order_id=? AND oi.name=?", m["order_id"], m["item"])
        nt = _rows("SELECT * FROM delivery_notice WHERE order_id=?", m["order_id"])
        ms = _rows("SELECT DISTINCT method FROM measure_rec WHERE customer_id=?", m["customer_id"])
        n_item = _rows("SELECT count(*) n FROM measure_rec WHERE customer_id=?",
                       m["customer_id"])[0]["n"]
        hist = _rows("SELECT count(*) n FROM maintain WHERE customer_id=? AND id<>?",
                     m["customer_id"], m["id"])[0]["n"]
        d = {"工单": m["id"], "状态": m["status"], "客户": f"{m['customer_id']} {m['cname'] or ''}".strip(),
             "商品": m["item"], "客户报的问题": m["issue"],
             "报修时间": m["created"], "门店": m["shop"], "顾问": m["advisor"],
             "订单": (o[0] if o else {"error": "订单查不到"}),
             "这件的配置": (dict(形制=it[0]["xz"], 可选面料=it[0]["mt_opts"],
                            可选工艺=it[0]["kf_opts"], 商品备注=it[0]["remark"])
                        if it else {"note": "订单行里没有同名商品"}),
             "量体记录": {"条数": n_item, "方式": [x["method"] for x in ms],
                       "是否远程": any(x["method"] == "远程" for x in ms)},
             # 代码要翻成名称。原来只给「N1,N2,N3」,模型看得见却看不懂 ——
             # 它会说「需要人工查出 N1-N6 具体条目」,**而那正是它该自己拿到的东西**。
             "交付告知签收": (dict(已告知条目=[NOTICE_NAME.get(x, x)
                                          for x in (nt[0]["items"] or "").split(",") if x],
                             签收时间=nt[0]["signed_at"], 渠道=nt[0]["channel"]) if nt else None),
             "该客户历史维修次数": hist}
        out.append(d)
    return {"hit": len(rows), "工单": out,
            "怎么用": "**这里只有事实,没有结论。** 判责要另外调 kb_tables 取「售后争议判定」,"
                    "并对照 09-养护与售后.md 第五节的返修判定表。"
                    "「交付告知签收」为 null 表示**没有书面告知记录** —— "
                    "特性类问题(起球/色差/掉色/勾丝)在这种情况下按「我方,让步处理」;"
                    "尺寸类问题看「量体记录」完不完整、是不是远程量的。"
                    "**结论必须由人确认后执行,你只出草稿。**"}

# ── 场景倒推 ────────────────────────────────────────────────────────────
# 「明年六月毕业礼要穿」这句话,拆开是四个互相咬着的约束:
#   ① 选码要用**穿的那天**的身高,不是下单那天的
#   ② 下单太晚 → 排不上产能,做不出来
#   ③ 下单太早 → 用的量体更旧、推算跨度更长,**误差更大**
#   ④ 下单前必须有**没过期**的量体记录
# 所以答案不是一个日期,是**一个窗口**:什么时候约复量、什么时候下单。
# 只回答「最晚哪天下单」是把 ③ 漏了 —— 而 ③ 恰恰是童装做小了的主因。
# 交付告知的六条(见 09-养护与售后.md 第三节)。库里存代码,对外给名称 ——
# 判责时「有没有告知过色差」这种问题,看代码是答不了的。
NOTICE_NAME = {"N1": "N1 面料特性", "N2": "N2 色差与掉色", "N3": "N3 手工痕迹",
               "N4": "N4 洗护方式", "N5": "N5 尺寸容差", "N6": "N6 工期与延期"}

GIRTH = {"胸围", "腰围", "臀围", "领围", "胸上围", "臂围"}
FIT_BUFFER = 7      # 交付到穿之间留的试穿与小改天数

def plan_for_event(wearer_id, event_date, pattern, material,
                   crafts=None, scope="局部", today=None):
    """场景倒推:为某个日子做一件衣服,什么时候复量、什么时候下单、按多高做。"""
    import growth
    from datetime import date, timedelta
    today = date.fromisoformat(today) if today else date(2026, 8, 31)
    ev = date.fromisoformat(event_date)
    if ev <= today: return {"error": "用件日期已经过了"}

    w = _wearer(wearer_id)
    if not w: return {"error": f"着装人 {wearer_id} 不存在"}
    if not _consent_ok(w["id"]):
        return {"error": "没有有效的身体数据同意,不能推算", "着装人": w["name"]}
    age = growth.age_at(w["birthday"], today) if w["birthday"] else None
    if age is not None and age < 14 and not _consent_ok(w["id"], "未成年人"):
        return {"error": "不满十四周岁,缺少监护人同意,不能推算", "着装人": w["name"]}

    ms = {r["name"]: r["value"] for r in _rows(
        "SELECT i.name,r.value,r.measured_at FROM measure_rec r"
        " JOIN measure_item i ON i.code=r.item WHERE r.wearer_id=?"
        " ORDER BY r.measured_at", wearer_id)}
    if "身高" not in ms: return {"error": "没量过身高,先约量体", "着装人": w["name"]}
    mdate = _rows("SELECT max(measured_at) a FROM measure_rec WHERE wearer_id=?",
                  wearer_id)[0]["a"][:10]

    # ① 穿的那天该按多高做 —— **不是今天的身高**
    fc = growth.forecast(w["gender"], w["birthday"], ms["身高"], mdate, ev.isoformat())
    ratio = fc["预测身高"] / ms["身高"]

    # 长度类按身高比例缩放给点估计;围度类只给区间(md 第四节)
    lo_ms, hi_ms = {}, {}
    for k, v in ms.items():
        if k in GIRTH:
            b = growth.girth_band(v, ms["身高"], fc["预测身高"])["区间"]
            lo_ms[k], hi_ms[k] = b
        else:
            lo_ms[k] = hi_ms[k] = round(v * ratio, 1)

    pr = _rows("SELECT code,name,xz,sizes FROM pattern WHERE code=? OR name=?", pattern, pattern)
    if not pr: return {"error": f"没有版型「{pattern}」"}
    pr = pr[0]
    specs = {}
    for r in _rows("SELECT size,item,value FROM size_spec WHERE pattern=?", pr["code"]):
        specs.setdefault(r["size"], {})[r["item"]] = r["value"]
    import fitting
    szs = pr["sizes"].split(",")
    r_lo = fitting.recommend(lo_ms, pr["code"], szs, specs, pr["xz"])
    r_hi = fitting.recommend(hi_ms, pr["code"], szs, specs, pr["xz"])
    size_lo, size_hi = r_lo.get("推荐尺码"), r_hi.get("推荐尺码")
    span = size_lo != size_hi
    size = size_hi if span else size_lo    # 跨码时按大的做,靠折边收回来

    # ② / ③ / ④ 三个日期
    ship = ev - timedelta(days=FIT_BUFFER)
    lead = kb_lead(pr["code"], size or szs[-1], material, crafts or [], scope,
                   need_date=ship.isoformat(), from_date=today.isoformat())
    if lead.get("error"): return lead
    latest = date.fromisoformat(lead["最晚下单日"])
    remeasure = latest - timedelta(days=3)      # 量完就下单,记录最新
    e = growth.measure_expired(w["gender"], w["birthday"], mdate, today)

    warn = []
    if latest < today:
        warn.append(f"**赶不上** —— 最晚 {latest} 就得下单,今天已经 {today}")
    if span:
        warn.append(f"围度区间跨了 {size_lo}/{size_hi} 两个码 —— **按大的 {size} 做,"
                    f"裙长留 5cm 折边**,小了没法救,大了能收")
    if e["过期"]:
        warn.append(f"现有量体已过 {e['已过天数']} 天(上限 {e['允许天数']}),"
                    f"**这次推算是拿一份无效记录做的,只能当参考**")
    if (latest - today).days > 60:
        warn.append(f"离最晚下单日还有 {(latest - today).days} 天 —— "
                    f"**现在不要下单**:早下单等于用更旧的量体、推更长的跨度,误差更大。"
                    f"等到 {remeasure} 前后复量再下")
    if fc["跨突增期"]:
        warn.append("这段跨过突增窗口,身高区间已放宽近一倍,**务必按上限留折边**")

    return {"着装人": w["name"], "用件日期": event_date, "场合": None,
            "现在": today.isoformat(), "上次量体": mdate,
            "现有身高": ms["身高"], "穿那天预测身高": fc["预测身高"], "身高区间": fc["区间"],
            "推荐尺码": size, "尺码是否跨档": span, "区间下限码": size_lo, "区间上限码": size_hi,
            "交付日": ship.isoformat(), "最晚下单日": lead["最晚下单日"],
            "建议复量日": remeasure.isoformat(),
            "工期最快": lead.get("最快天数"), "工期最慢": lead.get("最慢天数"),
            "赶得上": lead.get("赶得上"),
            "留成长量": growth.allowance(fc["长高"]),
            "限定": fc["限定"], "提醒": warn,
            "说明": "选码用的是**穿那天的预测身高**,不是今天的身高。"
                    "答案是一个窗口不是一个日期:早下单误差大,晚下单排不上。"}

SHOP_SCHEMAS=[
 {"name":"my_tasks","description":"看**我自己的任务**。顾问只看得到派给自己的,店长看本店全部 —— 这是数据隔离,不是界面上少显示几行。可用 status 只看某一档(有效/完结/取消/无效)。问「我今天有什么事」「张三手上几件活」先调这个。",
  "input_schema":{"type":"object","properties":{
    "status":{"type":"string","description":"只看这一档:有效 / 完结 / 取消 / 无效。不传看全部。"}},"required":[]}},
 {"name":"task_types","description":"九种任务类型的**数据规范**:每种挂哪张单据(客户号/订单号/维保单号/售后单号/不挂)、谁能派、完成时要不要传现场照。**起草派任务之前先调这个** —— 类型决定了要填什么,填错会被拒。",
  "input_schema":{"type":"object","properties":{},"required":[]}},
 {"name":"dispatch_pool","description":"**待分配池**:客户已经约了时间、但系统没能自动派单的任务。每条都带 agent 的人选建议和依据(接触史 / 时段冲突 / 负载)。只有店长看得到。**建议不是决定** —— 要店长确认才算派出去。",
  "input_schema":{"type":"object","properties":{},"required":[]}},
 {"name":"team_tasks","description":"**本店每个顾问手上各有什么活** —— 店长看团队用这个。按人分组,带每个人的在办件数、最近到期时间和在办明细,还会列出手上没活的人和待分配的条数。给 assignee(工号或姓名)就只看那一个人。⚠️ 顾问调这个只看得到自己 —— 隔离在查询层。**「你看不到他的活」和「他没有活」是两回事**,工具会分开说。",
  "input_schema":{"type":"object","properties":{
    "assignee":{"type":"string","description":"只看这一个人,工号或姓名。不给则按人分组列全店。"},
    "status":{"type":"string","description":"只看这一档:有效 / 完结 / 取消 / 无效。不传看全部。"}},
   "required":[]}},
 {"name":"week_grid","description":"**排班用的格子**:一周里每个顾问哪天什么时段已经占了、哪几天完全没人排班、待分配还有几条。**排班之前必须先看这个** —— 不看就排,排出来的东西和正常任务长得一模一样,直到那天两个人同时约在一个时段。只有店长看得到。",
  "input_schema":{"type":"object","properties":{
    "start":{"type":"string","description":"从哪天起,YYYY-MM-DD,默认今天"},
    "days":{"type":"number","description":"看几天,默认 7,最多 14"}},"required":[]}},
 {"name":"assign_batch","description":"**一次排一批任务**(排班用,真的写进去)。items 是列表,每条 {type, assignee, note, start, end, ref_id?, activity_code?},一次最多 20 条。**全过才写,一条不过就整批不写** —— 半途失败留下几条已排几条没排,比整批失败难收拾得多。而且它会检查**只有整体看才发现的冲突**:同一个人被排了两个重叠时段。⚠️ 排之前先 week_grid() 看现有占用,并把整张表念给用户确认。",
  "input_schema":{"type":"object","properties":{
    "items":{"type":"array","description":"要排的任务列表",
      "items":{"type":"object","properties":{
        "type":{"type":"string","description":"任务类型,见 task_types()"},
        "assignee":{"type":"string","description":"派给谁,工号或姓名"},
        "note":{"type":"string","description":"日程描述"},
        "start":{"type":"string","description":"开始 YYYY-MM-DD HH:MM"},
        "end":{"type":"string","description":"结束 YYYY-MM-DD HH:MM"},
        "ref_id":{"type":"string","description":"挂的单据号,类型要求时才填"},
        "activity_code":{"type":"string","description":"绑定活动,可不填"}},
        "required":["type","assignee","note","start","end"]}}},
   "required":["items"]}},
 {"name":"dispatch_batch","description":"**一次把待分配池里的几条单分出去**(真的写进去)。items 是 [{task_id, assignee?}],不给 assignee 就采纳 dispatch_pool 给的建议,一次最多 20 条。**全过才写,一条不过整批不写。** 用户说「把待分配的都派了」「这几条都分下去」时用这个 —— assign_batch 是**新建**任务的,派不了已经存在的单。",
  "input_schema":{"type":"object","properties":{
    "items":{"type":"array","description":"要分派的单",
      "items":{"type":"object","properties":{
        "task_id":{"type":"string","description":"任务号,如 SC7032"},
        "assignee":{"type":"string","description":"分给谁。不给则采纳建议。"}},
        "required":["task_id"]}}},
   "required":["items"]}},
 {"name":"monthly_review","description":"**月度复盘**:这个月做完了多少、几条逾期、逾期都在谁身上、改派几次和理由、**agent 的派单建议采纳率**、智能体代做了几笔、待分配积压、订单走完一轮要多久。month 写 `2026-09`,不给就是当月。按**截止时间**归月(复盘看的是「这个月该做完的做完了没有」)。范围跟身份走:顾问只看自己的,店长看本店。⚠️ **分母为零的地方不给比率,给一句话** —— 「没发生过分派」和「分派了但一次没采纳」是两件事。",
  "input_schema":{"type":"object","properties":{
    "month":{"type":"string","description":"哪个月,写 2026-09。不给就是当月。"}},"required":[]}},
 {"name":"appt_funnel","description":"**预约到店转化漏斗**:约了多少 → 我们确认了多少 → 真到店多少 → 量体多少 → 下单多少;以及**流失分四种**(待确认烂掉 / 客户取消 / 爽约 / 已过期),每种带一句该怎么办。since/until 写 2026-08-01,不给就是全部。范围跟身份走。⚠️ 报**两种**转化率:环节转化率(÷上一环,看哪一环漏得最狠)和整体转化率(÷总预约,看一百个最后剩几个)——只报一个会答错另一个问题。⚠️ 最后两环(量体/下单)和预约之间**没有外键**,按「同一个客户、预约之后」连,**会高估**。",
  "input_schema":{"type":"object","properties":{
    "since":{"type":"string","description":"起始日,写 2026-08-01。不给就是不限。"},
    "until":{"type":"string","description":"截止日,写 2026-08-31。不给就是不限。"}},"required":[]}},
 {"name":"member_level","description":"**这个客户是哪一档会员、凭什么、离下一档还差多少。** 门槛按 level_cfg,是**滚动 12 个月**的实付或完成单数,满足**任一条**即可(不是「且」)。⚠️ 依据取客户档案上的 12 个月快照字段,**不是去订单表现算** —— 订单表只是个样本,现算会把大多数人算成 0 单 0 元。⚠️ **不要拿「累计实付」算等级**:累计算 106 个人里能对上 96 个,看起来就是对的,但那 10 个错的不会有任何地方报错。库里存的档和按门槛算的不一致时会给提醒 —— 那多半是人工调过档。",
  "input_schema":{"type":"object","properties":{
    "customer_id":{"type":"string","description":"客户号,如 C10001"}},"required":["customer_id"]}},
 {"name":"points_ledger","description":"**积分流水和对账。** ⚠️ 余额是「同一个事实两个来源」:既能从 balance 字段读,也能从流水累加,**必然漂**(这本账修过一次:中间余额曾被截断,现已重算为 0 处断点)。**对账不能取消** —— 只要两个来源都在就可能再漂。所以两个都给、照旧对账;真出现断点时**不替你选一个**,哪个对取决于是谁写错了。",
  "input_schema":{"type":"object","properties":{
    "customer_id":{"type":"string","description":"客户号,如 C10001"},
    "limit":{"type":"integer","description":"最近几条流水,默认 20"}},"required":["customer_id"]}},
 {"name":"approval_queue","description":"**审批队列**:等级调整 / 积分调整 / 客户转移,谁申请的、什么理由、批了没有。这三种的共同点是**它们都绕过了某条本该自动成立的规则** —— 自动算出来的等级不用审批,人手改的才要。**审批管的是例外,不是日常。** 「待审批 → 已通过/已驳回」这两步只有总部运营能走。",
  "input_schema":{"type":"object","properties":{
    "status":{"type":"string","description":"待审批 / 已通过 / 已驳回 / 已撤回,不给就是全部"},
    "kind":{"type":"string","description":"等级调整 / 积分调整 / 客户转移,不给就是全部"}},"required":[]}},
 {"name":"apply_adjust","description":"**提一张审批单**(等级调整 / 积分调整 / 客户转移)—— ⚠️ **只是申请,不生效**。这三件事都绕过了某条本该自动成立的规则,所以一律走审批。理由必填:**没有理由的申请,审批的人只能靠猜,而猜出来的「同意」等于没审**。店长及以上才能提。",
  "input_schema":{"type":"object","properties":{
    "kind":{"type":"string","description":"等级调整 / 积分调整 / 客户转移"},
    "target":{"type":"string","description":"客户号;客户转移可多个,用 | 隔开"},
    "payload":{"type":"object","description":"要改成什么,如 {\"from\":\"金卡\",\"to\":\"黑金\"} 或 {\"delta\":5000}"},
    "reason":{"type":"string","description":"为什么要改。必填,至少 4 个字"}},
   "required":["kind","target","payload","reason"]}},
 {"name":"decide_approval","description":"**批一张审批单**:同意或驳回。「待审批 → 已通过/已驳回」这一步**只有总部运营能走**(角色判定在状态机里,不在这个工具里)。批注必填,同意和驳回都要 —— 驳回不写理由申请人不知道该补什么,**同意不写理由出事之后没人说得清当时看了什么**。⚠️ 审批**只改审批单的状态**,不会替你去改客户档案 —— 批准和执行分开,才查得出「谁批的」和「谁做的」。",
  "input_schema":{"type":"object","properties":{
    "approval_id":{"type":"string","description":"审批单号,如 AP-LV-001"},
    "agree":{"type":"boolean","description":"true=通过,false=驳回"},
    "note":{"type":"string","description":"批注。必填,至少 4 个字"}},
   "required":["approval_id","agree","note"]}},
 {"name":"activity_roi","description":"**活动投入产出**:花了多少、带来多少成交、投入产出比、单均获客成本。不给 code 就是全部活动的排名,给了就看那一个。⚠️ 三件事别处看不到:① **活动表上的「报名/成交」两列是随机数**,和订单表毫无关系,一律不读也不许引用;② **归因期外的订单分开报,不并进成交** —— 实测有活动 100% 的订单创建于活动期外,要么归因错了要么活动日期错了;③ 成本和成交**各有三个口径**(预算/已发生/已开票、应收/实收/完成),默认「已发生」和「实收」,三个都给。算不出 ROI 的(未开始、已取消)**单独列,不当 0 排最后** —— 那会把「还没开始」和「效果最差」画等号。管理视角,顾问看不到。",
  "input_schema":{"type":"object","properties":{
    "code":{"type":"string","description":"活动编号,如 AC2601。不给就是全部活动的排名。"}},"required":[]}},
 {"name":"can_order","description":"**下单之前先问一句:这单能下吗?** 定制订单要有**这个着装人**下单前的量体,而且不能超期 —— 超期的记录**不是「参考值」,是「无效值」**(复量周期:成人 12 个月、3–12 岁 6 个月、突增期 4 个月、0–3 岁 3 个月)。结论有**三种**:可以 / 不可以 / **判不了**。⚠️ **判不了不等于可以** —— 客户名下多个着装人而没传 wearer_id 时返回「判不了」并列出候选,**不替你挑一个**:挑错的话这一单会拿着另一个人的尺寸去裁剪,而报表上完全正常。标品订单是现货成衣,不受这条管。",
  "input_schema":{"type":"object","properties":{
    "customer_id":{"type":"string","description":"客户号,如 C10010"},
    "kind":{"type":"string","description":"定制品订单 / 标品订单,默认定制品订单"},
    "wearer_id":{"type":"string","description":"着装人编号(W 开头)。客户名下不止一个人时必传。"}},
   "required":["customer_id"]}},
 {"name":"my_workorders","description":"**我手上的工单**。工匠看自己的,工坊管事看本坊,总部运营看全部 —— 范围跟身份走。带**在制上限**和当前在制数:接不接得下一件,这两个数说了算,不用猜(上限是工艺约束 —— 手工活同时开太多件每件都慢,而且染色、绣线批次会串味)。逾期的排在最前。status 可选,写「在制/待开工/已完成」等。",
  "input_schema":{"type":"object","properties":{
    "status":{"type":"string","description":"只看某个状态的,不给就是全部"}},"required":[]}},
 {"name":"get_task","description":"看**一条任务**的详情。看不到别人的 —— 知道单号也看不到:顾问只能看派给自己的,店长能看本店的。",
  "input_schema":{"type":"object","properties":{
    "task_id":{"type":"string","description":"任务号,如 SC7029"}},"required":["task_id"]}},
 {"name":"assign_task","description":"**派一条任务**(真的写进去,立即生效)。只有店长及以上能派,只能派给本店在职顾问。type 见 task_types();ref_id 填什么由类型决定;assignee 写工号或姓名。⚠️ **动手之前先跟用户把人、时间、内容对一遍** —— 派错了和派对了在库里长得一模一样,等发现的时候顾问已经去做了。用户没说清派给谁就问,别挑一个「看起来合理」的人。",
  "input_schema":{"type":"object","properties":{
    "type":{"type":"string","description":"任务类型,九种之一,见 task_types()"},
    "assignee":{"type":"string","description":"派给谁,工号或姓名"},
    "note":{"type":"string","description":"日程描述:这件事要做什么"},
    "end":{"type":"string","description":"结束时间 YYYY-MM-DD HH:MM"},
    "start":{"type":"string","description":"开始时间,不给则用现在"},
    "ref_id":{"type":"string","description":"挂的单据号。客户相关填客户号;订单跟踪填订单号;维保填维保单号;售后填售后单号;团建培训和日常运维不填。"},
    "activity_code":{"type":"string","description":"绑定活动编码,可不填"}},
   "required":["type","assignee","note","end"]}},
 {"name":"dispatch_task","description":"**把待分配池里的单分出去**(真的写进去)。不给 assignee 就采纳 dispatch_pool 里那条建议。只能分**还没派出去的**单 —— 已经派给别人的要改派是另一个动作,悄悄换掉负责人会让原来那个人的列表凭空少一行。",
  "input_schema":{"type":"object","properties":{
    "task_id":{"type":"string","description":"任务号,如 SC7029"},
    "assignee":{"type":"string","description":"分给谁,工号或姓名。不给则采纳建议。"}},
   "required":["task_id"]}},
 {"name":"reassign_task","description":"**改派**:把一条已经派出去的任务转给另一个人(真的写进去)。和 dispatch_task 的区别是**有人的活被拿走了** —— dispatch 分的是没人管的单,改派是从小张手上拿走给小李。所以 reason 必填,而且原负责人仍然看得见这条(标着是谁改派的、为什么),**不让他的列表凭空少一行**。只能改「有效」的任务。⚠️ 动手之前先问清楚为什么要改、原负责人知不知道。",
  "input_schema":{"type":"object","properties":{
    "task_id":{"type":"string","description":"任务号,如 SC7029"},
    "assignee":{"type":"string","description":"改派给谁,工号或姓名"},
    "reason":{"type":"string","description":"为什么改派。**必填** —— 把人的活拿走要给个说法"}},
   "required":["task_id","assignee","reason"]}},
 {"name":"finish_task","description":"**把任务标记完成**(真的写进去)。日程总结必填。**只能完成派给自己的** —— 别人代点等于台账上写了一件没发生的事。需要现场照的类型要先在页面上传照片,这里传不了图。",
  "input_schema":{"type":"object","properties":{
    "task_id":{"type":"string","description":"任务号"},
    "summary":{"type":"string","description":"日程总结:做了什么、结果如何"}},
   "required":["task_id","summary"]}},
 {"name":"get_order","description":"查订单。给 order_id 返回单条全链路(双口径状态、金额勾稽、时间线、订单行、关联售后);给 customer(客户号或姓名)返回该客户的订单清单。**返回里的「勾稽异常」不为空时,必须先核对再答复客户**,不要直接把金额念给客户听。注意状态有两套口径:页面按设计稿 10 档、PRD 按状态机 6 档,对客户说页面口径。",
  "input_schema":{"type":"object","properties":{
    "order_id":{"type":"string","description":"订单号"},
    "customer":{"type":"string","description":"客户号或姓名。不知道订单号时先用这个列清单。"}},"required":[]}},
 {"name":"get_stock","description":"查现货。四种问法,给其中一个参数即可:sku=某个具体规格;spu=某个商品的全部规格;material=某种面料还有多少米;**craft=这个工艺有哪些面料是现货且相容的**。最后一种用于回答「能不能快一点」——换现货面料可以把备料从十几二十天压到 1–3 天,但**面料换了质感和售价都会变,必须让客户确认,不能替他决定**。",
  "input_schema":{"type":"object","properties":{
    "sku":{"type":"string"},"spu":{"type":"string","description":"商品编码或名称"},
    "material":{"type":"string","description":"面料名称,直接写中文"},
    "craft":{"type":"string","description":"工艺名称。用来找「现货且能做这个工艺」的面料。"}},
   "required":[]}},
 {"name":"get_capacity","description":"查工坊产能排期。**不传 craft 就是全工坊负载概览**(每个工种几人、在制多少、手上的活要消化几天、瓶颈在哪);传 craft 则返回这个工艺**最早什么时候能排上**、谁来做、要做到几号、有几位师傅可选。两条要点:①返回 `不可加人=true` 时,说明会这个工艺的师傅只有一位或都是一人一机(缂丝、妆花、手绘、顾绣、发绣),**排满了就只能等,加钱也没用**;②返回 error 说没有师傅会做时,那**不是排期问题是产能缺口**,只能外发或者不接这个单。注意 kb_lead 已经自动把排队等待算进工期了,这个工具是给工坊排产用的,不必为了算工期再调一次。",
  "input_schema":{"type":"object","properties":{
    "craft":{"type":"string","description":"工艺名称,直接写中文。不传则返回全工坊概览。"},
    "workdays":{"type":"number","description":"这活需要多少工日,默认 10"},
    "from_date":{"type":"string","description":"从哪天起算,YYYY-MM-DD,默认今天"}},"required":[]}},
 {"name":"get_workorder","description":"查**在制工单**:这件活在谁手上、做到哪一步、会不会拖。可按工单号、师傅(工号或姓名)、状态、订单号筛;传 `overdue=true` 只看已逾期的。\n\n**和 get_capacity 分工**:get_capacity 给工种级的负载和瓶颈(接不接得下),get_workorder 给单件的去向和进度(这一件怎么办)。排产两个都要。\n\n返回里「剩余天数」为负说明已经过了交期,**逾期的要先说,不要埋在列表里**;一个师傅在制件数超过他的 wip_limit,说明已经排满,再派活只会更晚。**这个工具只读,不能改期不能改派。**",
  "input_schema":{"type":"object","properties":{
    "workorder_id":{"type":"string","description":"工单号,如 WO8001"},
    "artisan":{"type":"string","description":"师傅工号或姓名"},
    "status":{"type":"string","description":"在制 / 已完成"},
    "ref":{"type":"string","description":"订单号"},
    "overdue":{"type":"boolean","description":"只看已逾期的"}},"required":[]}},
 {"name":"get_lifecycle","description":"查会员生命周期判定:某个客户属于八档中的哪一档(潜在/新客/活跃/高价值/忠诚/休眠/潜在流失/流失)、**凭什么判成这一档**、有没有被人工覆盖。也可按档位列人。\n\n**判定口径全是含端边界**:第 90 天算活跃、第 91 天进休眠、第 180 天仍休眠、第 181 天进潜在流失、第 365 天仍潜在流失、第 366 天才算流失;实付满 15000 **含端**计高价值。这些不要自己心算,直接看返回值。\n\n返回里「命中」是**全部**命中的条件,「生命周期」是按优先级取的那一个 —— **多条命中时必须把命中列表一起说出来**,只报结论运营无从判断算得对不对(实测四分之三的潜在流失客户同时命中多个条件)。出现「提醒」字段说明库里存的值和按今天重算的不一致,照实说,不要替它选一个。\n\n**这是判定不是预测**,不要拿它当流失概率用。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号或姓名"},
    "lifecycle":{"type":"string","description":"按档位筛,如「潜在流失」"}},"required":[]}},
 {"name":"get_member_priority","description":"回答「**同一档里先联系谁**」。给一个生命周期档位(如「潜在流失」),按 RFM 三维打分并排出优先次序,返回每个人的 R/F/M 分、合计分和**评分依据**。\n\n生命周期八档答的是「这个客户处在什么阶段」,答不了「潜在流失这 16 个人我先打给谁」—— 档内没有排序,而这正是运营每天要做的决定。\n\n**RFM 是相对分,只在返回的这一批人内部可比。** 不要拿两个档位的分数直接比,也不要说「他 RFM 12 分所以是优质客户」——换一批人同一个人的分数就变了。排序解决的是「先打给谁」,不是「谁更值钱」。\n\n**这是排序不是预测**,不代表联系了就能挽回。回答时把「评分依据」一起说出来,只给名次运营无从判断该不该信。",
  "input_schema":{"type":"object","properties":{
    "lifecycle":{"type":"string","description":"生命周期档位,如「潜在流失」「休眠」。不传则对全部客户排。"},
    "limit":{"type":"number","description":"返回前几名,默认 10,最多 40"}},"required":[]}},
 {"name":"check_write","description":"问「**这件事业务允不允许做**」时用它。它会拿真正的校验器跑一遍,返回能不能做、错误码和理由。**不写库**。\n\n支持两类:`建档`(新建客户)和 `预约`(含补录)。fields 传要写的字段,再加一个 `role`(顾问 / 店长 / 总部运营)——**权限判定看角色**,比如「预约时间早于当前,仅店长及以上可补录」。\n\n**role 是查询条件,不是授权**:它回答的是「**如果是**这个角色,允不允许」,不是「你能不能」。所以顾问问「店长能不能补录」是正当的,你要答得了。不传 role 就按**最低权限(顾问)**算 —— 免得给出一个「你其实做不到」的乐观回答。**真要执行还得本人确实有那个角色,那一关在后台写接口上。**\n\n**顾问问「能不能先建档回头补姓名」「能不能把上周的到店补录成预约」这类问题,必须调这个,不许凭系统结构推断。** 数据库允许和业务允许是两回事:`customer.name` 在库里可空,而业务规则是姓名必填 —— 只看表结构会得出完全相反的结论。\n\n返回里出现「疑似重复」时,**要把那几条列给人看** —— 那条规则是「转店长确认」,不是「不能建」,而店长得看见凭什么。",
  "input_schema":{"type":"object","properties":{
    "action":{"type":"string","description":"建档 或 预约"},
    "fields":{"type":"object","description":"要写的字段,如 {name,phone,shop} 或 {start,end,way};另可传 role"}},
   "required":["action"]}},
 {"name":"get_review_queue","description":"看**待核实队列**:哪些工艺×面料组合被顾问问到了、却没有任何依据,按被问次数排序。\n\n背景:相容矩阵里有 1274 格只是「没命中任何禁止规则」,没有人验证过 —— 现在这类不给结论,而是记进这个队列。**队列是「被真正问到」才进的**,所以它回答的是运营真正关心的问题:那 1274 格里顾问实际会撞上哪几十格,核实工作量由真实需求决定。\n\n返回里「被问次数」最高的最该先核。**这个队列只说「谁被问了」,不说「答案是什么」** —— 答案要工艺负责人去打样,不能推断。核实回填在后台做,不是这个工具能做的。",
  "input_schema":{"type":"object","properties":{
    "top":{"type":"number","description":"返回前几条,默认 15"}},"required":[]}},
 {"name":"get_aftersale","description":"查售后记录(退货/换货/退款/维修),可按订单号、客户或状态筛。退款类会带上退款轨迹。**这个工具只给事实,不给判责结论** —— 判责标准在 kb_tables 的「售后争议判定」表里,要另外查。查不到就如实说查不到,不要推测客户提过什么。",
  "input_schema":{"type":"object","properties":{
    "order_id":{"type":"string"},"customer":{"type":"string","description":"客户号或姓名"},
    "status":{"type":"string","description":"如「退款失败」「审批同意」"}},"required":[]}},
 {"name":"get_wearer","description":"查着装人档案 —— **衣服穿在谁身上**,和「谁付钱」是两回事。**身份绑在账户上**(账户以手机号为主标识,一个账户可以有多个着装人),不绑门店档案 —— 同一个人在不同店建过档就是两条档案。返回里「账户.关联门店档案」大于 1 时,说明这个人有多条门店档案,那正是客户合并要处理的情况。**手机号一律脱敏返回,账号密码任何情况下都拿不到。**妈妈给女儿买汉服时,付款人、收货人、量体对象是三个人。给 customer(客户号或姓名)返回这个账号下的全部着装人(本人/配偶/子/女),给 wearer_id 查单个。返回里的「量体是否过期」为真时,**下单前必须拦下要求复量** —— 超期的量体记录不是参考值,是无效值,「有个旧尺寸总比没有强」正是童装返工的来源。没有有效身体数据同意的着装人,量体数据一律取不到。",
  "input_schema":{"type":"object","properties":{
    "account":{"type":"string","description":"**手机号**(账户主标识,最常用)、账户号或自设账号"},
    "customer":{"type":"string","description":"门店客户号或姓名"},
    "wearer_id":{"type":"string","description":"着装人编号,如 W10001-2"}},"required":[]}},
 {"name":"get_maintain","description":"查售后维修工单的**现场**。客户说「衣服起球了 / 开线了 / 尺寸不对」时用。返回这件是什么(形制/可选面料/可选工艺)、客户报的问题、**量体记录全不全、是到店还是远程量的**、**交付时有没有书面告知签收**、以及该客户历史维修次数。\n\n**这个工具只给事实,不给判责结论** —— 判定表要另外调 kb_tables 取「售后争议判定」,并对照 09-养护与售后.md 第五节。两条关键判据:①「交付告知签收」为 null 表示**没有书面告知记录**,特性类问题(起球/色差/掉色/勾丝)在这种情况下按「我方,让步处理」,已告知则「无责,解释 + 提供保养服务」;② 尺寸类问题看量体记录完不完整、是不是**远程**量的(远程按合同分担)。\n\n**结论必须由人确认后执行,你只出草稿。** 不要直接对客户承诺免费返修或赔付金额。",
  "input_schema":{"type":"object","properties":{
    "maintain_id":{"type":"string","description":"维修工单号,如 MW73020"},
    "customer":{"type":"string","description":"客户号或姓名"},
    "status":{"type":"string","description":"如「待确认」「处理中」"}},"required":[]}},
 {"name":"plan_for_event","description":"场景倒推 —— 客户说「明年六月毕业礼要穿」时用这个。它把四个互相咬着的约束一次算完:①选码用**穿的那天**的预测身高,不是今天的;②下单太晚排不上产能;③**下单太早也不行** —— 用的量体更旧、推算跨度更长,误差更大;④下单前必须有没过期的量体。所以返回的是一个**窗口**:建议复量日 + 最晚下单日,不是单个日期。「尺码是否跨档」为真时说明围度区间横跨两个码,**按大的做并留折边** —— 小了没法救,大了能收。返回的「提醒」和「限定」必须一并说给客户。",
  "input_schema":{"type":"object","properties":{
    "wearer_id":{"type":"string","description":"着装人编号"},
    "event_date":{"type":"string","description":"要穿的那天,YYYY-MM-DD"},
    "pattern":{"type":"string","description":"版型编码或名称"},
    "material":{"type":"string","description":"面料名称"},
    "crafts":{"type":"array","items":{"type":"string"},"description":"工艺名称列表"},
    "scope":{"type":"string","description":"局部 / 整幅,默认局部"}},
   "required":["wearer_id","event_date","pattern","material"]}},
 {"name":"forecast_growth","description":"推算某个着装人到未来某天的身高,并给留成长量建议。主要用于**小孩** —— 定制工期 30–150 天,成人这段时间不变,小孩能长 1–2.5cm,而童装档差只有 4–6cm。**必须把返回里的「区间」和「限定」一起说给客户**,只报一个点估计等于骗人:推的是统计分布不是这个孩子,个体差 ±5cm 是常态,青春期突增的起始时间个体差可达 2–3 年。**围度只给区间不给点估计,任何情况下不得用推算围度直接下单裁剪。**「靶身高校验.需人工确认」为真时说明遗传身高和推算差得多,**转人工,不要自己挑一边**。",
  "input_schema":{"type":"object","properties":{
    "wearer_id":{"type":"string","description":"着装人编号,先用 get_wearer 查出来"},
    "target_date":{"type":"string","description":"推到哪天,YYYY-MM-DD。不传则按 months 算"},
    "months":{"type":"number","description":"往后推几个月,默认 12"}},"required":["wearer_id"]}},
]

# ── F3:出工具的那一刻,一律脱敏 ────────────────────────────────────────
# **位置很关键**:不能放在 _rows(数据访问层)—— 内部的数据体检要拿真手机号
# 做归户对账,脱敏了就查不了。放在**工具出口**:库里是真的,
# **离开工具的那一刻**才脱敏。
#
# 这样任何新加的工具**默认就是脱敏的** —— 不靠作者记得写 _mask()。
# 在此之前 _mask 全项目只被调用一次,「对外一律脱敏」是一句**约定**,不是结构。
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def _mask_out(o, depth=0):
    """递归把返回值里的手机号脱敏。字符串里夹着的也认。"""
    if depth > 8: return o
    if isinstance(o, str): return _PHONE.sub(lambda m: _mask(m.group()), o)
    if isinstance(o, dict): return {k: _mask_out(v, depth + 1) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_mask_out(v, depth + 1) for v in o]
    return o


def _masked(fn):
    def wrap(*a, **kw): return _mask_out(fn(*a, **kw))
    wrap.__name__, wrap.__doc__ = fn.__name__, fn.__doc__
    # **把原函数挂上去。** 不挂的话,任何想看这个工具真实实现的检查
    # (比如 isolation_check 查「写工具有没有从会话取身份」)看到的都是
    # 这三行包装器 —— 它会报「没取身份」,而实际取了。
    # 检查看错了对象,结论就是错的,而且错得很像真的。
    wrap.__wrapped__ = fn
    return wrap


TOOLS.update({"get_order":get_order,"get_stock":get_stock,"get_aftersale":get_aftersale,
              "get_capacity":get_capacity,
              "get_wearer":get_wearer,"forecast_growth":forecast_growth,
              "plan_for_event":plan_for_event,"get_maintain":get_maintain,
              "get_workorder":get_workorder,
              "get_lifecycle":get_lifecycle,
              "get_member_priority":get_member_priority,
              "check_write":check_write,
              "my_tasks":my_tasks,"task_types":task_types,"dispatch_pool":dispatch_pool,
              "team_tasks":team_tasks,"monthly_review":monthly_review,"member_level":member_level,"points_ledger":points_ledger,"approval_queue":approval_queue,"activity_roi":activity_roi,"can_order":can_order,"my_workorders":my_workorders,"apply_adjust":apply_adjust,"decide_approval":decide_approval,"appt_funnel":appt_funnel,"week_grid":week_grid,"assign_batch":assign_batch,"dispatch_batch":dispatch_batch,"get_task":get_task,"assign_task":assign_task,"dispatch_task":dispatch_task,"reassign_task":reassign_task,"finish_task":finish_task,
              "get_review_queue":get_review_queue})
TOOLS.update({"kb_lookup":kb_lookup,"kb_detail":kb_detail,"kb_tables":kb_tables,
              "kb_combo":kb_combo,"kb_coverage":kb_coverage,
              "kb_pattern":kb_pattern,"kb_size":kb_size,"kb_bom":kb_bom,
              "kb_fit":kb_fit,"kb_lead":kb_lead})
# **统一包一层** —— 放在这里而不是每个函数上,是为了「新加工具自动生效」。
# 漏包一个就等于开了个口子,而漏包是**不会报错**的。
#
# ⚠️ **原地改写,不要重新绑定 `TOOLS = {...}`。**
# 重新绑定的话,任何在这一行之前 `from api import TOOLS` 的模块
# 会一直拿着**没包装的那份**,脱敏静默失效。
# (这处是项目里的重复定义检查抓出来的 —— 它抓到的不只是命名冲突,
#  是一个真实的绑定时序隐患。)
for _k in list(TOOLS): TOOLS[_k] = _masked(TOOLS[_k])

KB_SCHEMAS=[
 {"name":"kb_lookup","description":"按关键词查工艺知识库。也可按分类(形制/材质/工艺/配饰)或来源等级(public/scale/demo)筛选。查不到会明确返回 hit=0。",
  "input_schema":{"type":"object","properties":{
    "keyword":{"type":"string","description":"关键词,如「香云纱」「盘金」「金线」"},
    "cat":{"type":"string","enum":["形制","材质","工艺","配饰"]},
    "src":{"type":"string","enum":["public","scale","demo"]}},"required":[]}},
 {"name":"kb_detail","description":"按编码取一条知识的完整内容(含出处链接)。编码形如 KF01 / MT01 / XZ01 / PS01。",
  "input_schema":{"type":"object","properties":{"code":{"type":"string"}},"required":["code"]}},
 {"name":"kb_combo","description":"查某工艺能否用于某面料。**工艺名和面料名直接写中文即可**(如「妆花」「云锦」),不必也不要猜编码 —— 名字对不上会明确报错并列出现有选项。返回「可/需评估/不可」、理由,以及 rule 字段(依据的规则号,或「人工确认」)—— 判「不可」时请把依据一并告诉用户;该组合未录入时返回「未定义」;返回里的 resolved 字段是实际解析到的那一对,回答前请核对它和用户问的是不是同一对。",
  "input_schema":{"type":"object","properties":{
    "craft":{"type":"string","description":"工艺名称或编码,如「妆花」或 KF02。**直接写名称即可,不要猜编码。**"},
    "material":{"type":"string","description":"面料名称或编码,如「云锦」或 MT02。**直接写名称即可,不要猜编码。**"}},
   "required":["craft","material"]}},
 {"name":"kb_tables","description":"取全部决策表(6 张共 30 行:客户原话对照、选料决策、配饰形制搭配、配色易错、工期档位、售后争议判定)。顾问问「客户说了 X,我该推什么/避开什么/怎么处理」这类问题时**优先用这个**,而不是 kb_lookup。**直接不带参数调用即可**,取全部比挑一张更可靠。",
  "input_schema":{"type":"object","properties":{"topic":{"type":"string","description":"通常不要传。全部决策表合计只有 30 行,一次全取更可靠 —— 传了 topic 反而容易取错表。"}},"required":[]}},
 {"name":"kb_coverage","description":"查相容矩阵的完成度(共多少格、已定义多少、未定义多少)。",
  "input_schema":{"type":"object","properties":{},"required":[]}},
 {"name":"kb_pattern","description":"查版型库:某个形制有哪些版型、每个版型分几个裁片、能出哪些尺码、改版难度多高。**客户问「这个能不能改尺寸/能不能做小码」时用这个。**某个尺码不在列表里,意味着这个版型裁不出来,不是缺货。",
  "input_schema":{"type":"object","properties":{
    "xz":{"type":"string","description":"形制名称或编码,如「明制马面裙」或 XZ03。不传则列出全部版型。"}},"required":[]}},
 {"name":"kb_size","description":"查某版型的成衣尺码表(各部位厘米数)。**返回的是成衣尺寸不是人体尺寸**,和客户量体值之间差一个放松量,不能直接比。推荐尺码最终由版师定。",
  "input_schema":{"type":"object","properties":{
    "pattern":{"type":"string","description":"版型名称或编码,如「明制马面裙·标准」或 PT04"},
    "size":{"type":"string","description":"只看某一个码,如 M。不传则返回全部码。"}},"required":["pattern"]}},
 {"name":"kb_fit","description":"拿客户的量体记录比对版型尺码表,给出**推荐尺码**和**档位**(标准码 / 调号 / 全定制 / 需补量)。返回逐项差值,标出哪几项是这个形制的关键尺寸。三条铁律:①系统只给建议,**最终由版师定**;②档位是「需补量」时**绝不能按身高体重猜码**,要请客户补量;③返回里的「关键尺寸未覆盖」列出的项系统比不了(比如马面宽没有对应量体项),必须告诉用户这几项还需人工确认,不能让人以为已经全查过了。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户姓名或客户号"},
    "pattern":{"type":"string","description":"版型名称或编码,如「明制马面裙·标准」或 PT04。不知道有哪些版型时先用 kb_pattern 查。"}},
   "required":["customer","pattern"]}},
 {"name":"kb_lead","description":"算工期:给定版型 + 尺码 + 面料 + 工艺,返回**最快到最慢的天数区间**、每一段花多久、**关键路径卡在哪一环**、有哪些风险、哪些环节加钱能压缩。**已经把工坊的排队等待算进去了**(师傅手上压着活,新单要排队),不必再单独查产能。传了 need_date(用件日期,YYYY-MM-DD)还会倒推最晚下单日并判断来不来得及。三条铁律:①**对客户报最慢那个数**,余量留给自己,绝不能报最快的;②「关键路径」告诉你加钱只对哪一环有用 —— 不在关键路径上的环节压缩了也没用;③返回的「风险」里凡是提到**不能靠加人压缩**(织造、染色晾晒、手绘顾绣发绣)的,加急要求必须当场拒绝,不要先答应再想办法。",
  "input_schema":{"type":"object","properties":{
    "pattern":{"type":"string","description":"版型名称或编码"},
    "size":{"type":"string","description":"尺码,如 M"},
    "material":{"type":"string","description":"面料名称,直接写中文"},
    "crafts":{"type":"array","items":{"type":"string"},"description":"所选工艺名称列表"},
    "scope":{"type":"string","enum":["局部","整幅"],"description":"整幅按局部的 4 倍估,默认局部"},
    "workers":{"type":"integer","description":"安排几个师傅并行,默认 2。注意染色、织造、手绘这些除不动。"},
    "from_date":{"type":"string","description":"从哪天起算,YYYY-MM-DD。不传按今天。"},
    "need_date":{"type":"string","description":"客户的用件日期 YYYY-MM-DD。婚礼、写真这类**日子不能改**的场合必须传,系统会倒推最晚下单日。"}},
   "required":["pattern","size","material"]}},
 {"name":"kb_bom","description":"算料算钱:给定版型 + 尺码 + 面料 + 所选工艺,返回完整物料清单(每项的净用量、损耗、实际用量、单价、金额)、物料成本合计、备料周期和卡在哪个物料上。**客户问「多少钱」「要等多久」时用这个。** 注意:返回的是**物料成本,不是售价** —— 不含工时、门店成本与税,**绝不能把这个数当报价告诉客户**。",
  "input_schema":{"type":"object","properties":{
    "pattern":{"type":"string","description":"版型名称或编码"},
    "size":{"type":"string","description":"尺码,如 M"},
    "material":{"type":"string","description":"面料名称,如「云锦」。直接写名称,不要猜编码。"},
    "crafts":{"type":"array","items":{"type":"string"},"description":"所选工艺名称列表,如 [\"盘金绣\"]"},
    "scope":{"type":"string","enum":["局部","整幅"],"description":"工艺做局部还是整幅,整幅按局部的 4 倍估。默认局部。"}},
   "required":["pattern","size","material"]}},
]
