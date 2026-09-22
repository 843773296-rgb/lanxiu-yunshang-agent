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
    if not rs:
        # ⚠️ **指路,别指到死路上。**
        # 原来这句只说「查不到,不要凭印象回答」—— 而实测它就到此为止了:
        # 问「真丝褙子怎么洗怎么存」,它 `kb_lookup` 查了三次「养护」「清洗」「真丝」,
        # 然后答「知识库里查不到」。**而那些话就写在 09-养护与售后.md 的正文里。**
        #
        # 这条工具查的是**结构化条目**(名字、别名、简介),正文根本不在它的扫描范围里。
        # 「查不到」于是被读成了「知识库里没有」——**两件事**。
        # 和 guards 里那条教训同一个形状:**拦一个动作的时候,得确认自己指的那条路真的通。**
        return {"hit": 0,
                "note": f"**结构化条目里**查不到「{keyword or cat or src}」。"
                        f"不要凭印象回答 —— 但也别就此打住:"
                        f"**怎么洗、怎么存、为什么这么做这类话在正文里,不在条目里**,"
                        f"用 `kb_read` 先看目录(比如 `kb_read(\"09\")` 是养护与售后)。",
                "正文有这几篇": {k: v[1] for k, v in KB_DOCS.items()}}
    return {"hit":len(rs),"rows":[_nz(_with_source(_with_material(r))) for r in rs[:12]]}

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

def _with_source(d):
    """给每一条知识贴上**来源等级 + 对客口径 + 溯源状态**。

    2026-09-15 加。原来返回里只有一个 `src_type`,而那三个字**不够**:

      · 只给档位  —— 读的人以为标着 `public` 就有出处。
        实测 29 条 public 里 **15 条连出处的名字都没有**,scale 32 条里 31 条没有。
        **一个标着「公开可查、可溯源」却给不出出处的条目,比标着 demo 更糟**:
        标 demo 的没人敢拿去承诺,标 public 的顾问会照着它对客户说。
      · 只给出处  —— 读的人不知道这一条能不能对外说。

    **我不替它编出处,也不替它降档**(降档是说另一个方向的假话)。
    做的是第三件事:**让它自己说出来** —— 「标着可溯源,但库里没有出处」
    跟着这一条一起被读到,模型没法再把它当成有出处的知识往外说。
    **补出处是人的活,不许假装有出处是代码的活。**
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import source as _src
    d = dict(d)
    档 = d.pop("src_type", None)
    if not 档: return d
    d.update(_src.标注(档, d.get("src_name"), d.get("src_url")))
    d.pop("src_name", None); d.pop("src_url", None)
    return d


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
    sql = ("SELECT id,name,lifecycle,idle_days,orders_12m,amount_12m,last_interact,advisor_no "
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
               "assign_batch", "dispatch_batch",
               # 版师核裁片用料占比。**登记在这儿不是形式** —— 进了这张表才会被
               # `isolation_check`(从会话取身份、入参里没有身份字段)、
               # `guards.pre_tool_verdict`(一轮只写一次、同参数不许重试)、
               # `funnel`(漏斗记它走了写路径)一起管住。
               # 上一版它没进来,于是它是**唯一一个没人管的写口**,
               # 而边界审计只能靠名字里有没有 `set_` 猜它存在。
               "set_piece_ratio",
               # 白坯试衣(业务 09-22):登记试衣 / 补签(顾问、店长),开裁(版师,过白坯那道闸)
               "record_fitting", "start_cutting",
               # 量体录入(业务 09-22):按次登记,可绑订单行作下单量体
               "record_measure",
               # 交付签收(业务 09-22):到店代收 / 取件方式 / 不合身、核验 6 位码签收、顾问追认完成
               "record_pickup", "verify_fit_code", "ratify_complete",
               # 下单(业务 09-22):先开单停在待确认 → 量下单量体绑到那一件 → 确认下单(过闸,即已付款)
               "open_order", "confirm_order")


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
                "负责人": r.get("assignee_name") or r.get("advisor_no"),
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
        k = r.get("assignee_name") or r.get("advisor_no") or "(没有负责人)"
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
               # ⚠️ **按工号隔离,不按名字。**
               # 原来是 `advisor=?` 配 `me["name"]` —— **两个同名顾问会看到
               # 彼此的订单**。那不是显示问题,是**越权**。
               # 名字列 2026-09-16 全库删除,这个风险**结构性消失**。
               o_where, o_args = ("shop=? AND advisor_no=?",
                                  [me.get("shop"), me.get("no")])
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
        # ⚠️ **这条警告比别的都难发现,因为它不在任何一个数上。**
        # 每个 ROI 都算得对、每个分母都是真的,只是**归因归错了对象**,
        # 而归错的那个对象(渠道)在这张表上根本不出现。
        # 现算,不是背一句话 —— 种子数据一改它就该跟着变。
        **({"⚠️ 活动和渠道完全共线": _活动渠道共线()}
           if _活动渠道共线() else {}),
        口径=dict(成本=f"默认「{av.默认成本口径}」(实际记了账的,含待开票)",
                 成交=f"默认「{av.默认成交口径}」—— 投入产出要用真到账的钱,"
                     f"应收里有一部分永远收不回来",
                 排除="取消的单既不算收入也不占分母")))


def _活动渠道共线():
    """活动和下单渠道是不是一一对应。**现算,不背。**

    `seed.py` 里 `SRC[i % 4]` 和 `ACT[i % 4]` 同一个周期,于是每个活动
    恰好对应一个渠道 —— **按活动分组和按渠道分组变成了同一件事**。

    返回一句话;不共线就返回 None(那时候这条警告不该出现)。
    """
    模拟 = {r["order_id"] for r in _rows("SELECT order_id FROM sim_batch")}
    对 = {}
    for r in _rows("SELECT id, COALESCE(activity,'(无)') a, source FROM ordr"):
        if r["id"] in 模拟: continue          # 模拟单一律没绑活动,不参与判断
        对.setdefault(r["a"], set()).add(r["source"])
    if not 对: return None
    一对一 = all(len(v) == 1 for v in 对.values()) and \
             len({next(iter(v)) for v in 对.values()}) == len(对)
    if not 一对一: return None
    配 = "、".join(f"{k}↔{next(iter(v))}" for k, v in sorted(对.items()))
    return (f"**每个活动恰好对应一个渠道,一一对应没有例外**({配})—— "
            f"所以**按活动分组 ≡ 按渠道分组**,"
            f"「这个活动效果好」和「这个渠道转化好」在这批数据上**分不开**。"
            f"⚠️ 这条比别的警告难发现,因为**它不在任何一个数上**:"
            f"每个 ROI 都算得对、每个分母都是真的,只是**归因归错了对象**,"
            f"而归错的那个对象在这张表上根本不出现。"
            f"详见 `channel_compare`。")


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


def piece_ratios(pattern=None):
    """**裁片用料占比** —— 版师核对用的那张表。

    每条带**来源**,三种可信度不许混为一谈:

        估算   机器按几何估的,没人看过
        复核   规则核过一遍(同形制变体结构一致、量纲常识、和 BOM 交叉验),
               **但这个数本身没人核过**
        版师   人核过数
        BOM    BOM 里明写的用量(内衬走这条)

    还给出**这个占比折成多少米**(× `fabric_base`),因为版师判断的是米数,
    不是百分比 —— 「袖片 15.7%」看不出对不对,「袖片 0.63 米」一眼就知道。
    """
    if not pattern:
        rs = _rows("SELECT pattern, COUNT(*) 片数, "
                   "SUM(CASE WHEN ratio_src='版师' THEN 1 ELSE 0 END) 已核, "
                   "GROUP_CONCAT(DISTINCT ratio_src) 来源 "
                   "FROM pattern_piece WHERE ratio IS NOT NULL GROUP BY pattern")
        nm = {r["code"]: r["name"] for r in _rows("SELECT code,name FROM pattern")}
        for r in rs:
            r["版型"] = nm.get(r["pattern"], r["pattern"])
        待 = sum(1 for r in rs if r["已核"] < r["片数"])
        return {"hit": len(rs), "rows": rs,
                "note": f"**{待} 个版型还没核完**。传 pattern 看某一个的明细。"
                        f"核过的标 `版师`,**不会被重新估算覆盖**。"}
    p = _rows("SELECT code,name,fabric_base FROM pattern WHERE code=? OR name=?",
              pattern, pattern)
    if not p:
        return {"error": f"没有版型「{pattern}」—— 这个工具认版型编码(PT06)和全名"}
    p = p[0]
    rs = _rows("SELECT name,qty,ratio,ratio_src,note FROM pattern_piece "
               "WHERE pattern=? ORDER BY ratio DESC", p["code"])
    fb = p["fabric_base"] or 0
    for r in rs:
        r["折合米数"] = round((r["ratio"] or 0) * fb, 3)
    合 = round(sum(r["ratio"] or 0 for r in rs), 4)
    return {"hit": len(rs), "版型": p["name"], "整件用料米": fb, "rows": rs,
            "占比之和": 合,
            "note": "**版师要判的是米数,不是百分比。** "
                    "占比之和必须 = 1(用可信的整件用料 × 估算的相对占比,"
                    "比两个都估要稳)。改一条用 `set_piece_ratio`,"
                    "**改完这一片就标「版师」,不会再被估算覆盖**。"
                    + ("" if abs(合 - 1) < 0.01 else
                       f" ⚠️ 现在之和是 {合},不等于 1,这本身就是个问题")}


def recovery_queue(kind=None, today=None):
    """**未成交挽回清单** —— 下了单没付钱的、约了没来的,各压着多少钱、压了多久。

    库里压着两笔**算得出金额的流失**,而在这个工具之前**没有任何东西在看它们**:
    它们在表上只是一个状态,没有一个动作。

    ## ⚠️ 这个工具只出清单,**不发任何东西**

    发短信、发微信、打电话是**对外动作**。agent 给的是「该跟谁、凭什么、
    什么顺序」,**按不按、怎么按是人的决定** —— 这是这个项目的硬规矩。

    ## 它不划「超时」那条线

    定制品和标品的合理等待期本来就不一样(定制品要等方案确认、
    要等客户和家里商量一件几万块的衣服)。**编一个数出来,
    会把正常的单子也算成流失** —— 而那种错不报错,只会让顾问去催一个该等的客户。

    所以**只排序不划线**:按「金额 × 停留天数」排,让看的人自己决定从哪儿切。

    ## 三种未成行不许混成一类

    「已取消」是客户**主动说了不来**、「爽约」是**没说就没来**、
    「已过期」是**系统判的**。同一套话术发给后两种会很唐突 ——
    爽约的要先确认人没事,过期的客户自己可能都不知道有这条预约。

    kind: 不传给两摊都要;传「待付款」或「预约」只要一摊。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import recovery as _rc
    今天 = today or _dt.date.today().isoformat()
    out = {"今天": 今天, "口径": _rc.口径说明()}

    if kind in (None, "待付款"):
        rs = _rows("SELECT o.id, o.kind, o.payable, o.created, o.source, "
                   "  o.customer_id, c.name cname, o.advisor_no "
                   "FROM ordr o LEFT JOIN customer c ON c.id=o.customer_id "
                   "WHERE o.status='待付款'")
        单 = []
        for r in rs:
            d = _rc.停留(r["created"], 今天)
            单.append(_nz({
                "订单": r["id"], "客户": f"{r['customer_id']} {r['cname'] or ''}".strip(),
                "品类": r["kind"], "渠道": r["source"], "顾问工号": r["advisor_no"],
                "金额": r["payable"], "压了几天": d,
                "紧要度": _rc.紧要度(r["payable"], d),
            }))
        单.sort(key=lambda x: -(x.get("紧要度") or 0))
        out["待付款"] = {
            "笔数": len(单),
            "压着的钱": round(sum(x.get("金额") or 0 for x in 单), 2),
            "明细": 单,
            "note": "按**金额 × 停留天数**排 —— 只看金额会把「5 万压两天」"
                    "排在「500 压两个月」前面,而后者多半已经黄了;"
                    "只看天数会把小单排在真金白银前面。",
        }

    if kind in (None, "预约"):
        摊 = {}
        for st, (是什么, 该做什么) in _rc.未成行.items():
            rs = _rows("SELECT a.id, a.customer_id, c.name cname, a.start_ts, "
                       "  a.shop, a.advisor_no FROM appointment a "
                       "LEFT JOIN customer c ON c.id=a.customer_id "
                       "WHERE a.status=? ORDER BY a.start_ts DESC", st)
            摊[st] = {
                "笔数": len(rs), "是什么": 是什么, "该做什么": 该做什么,
                "最近几条": [{"预约": r["id"],
                              "客户": f"{r['customer_id']} {r['cname'] or ''}".strip(),
                              "原定": r["start_ts"], "门店": r["shop"],
                              "顾问工号": r["advisor_no"],
                              "过了几天": _rc.停留(r["start_ts"], 今天)}
                             for r in rs[:5]],
            }
        到店 = _rows("SELECT COUNT(*) n FROM appointment "
                     "WHERE status IN ('已到店','已完成')")[0]["n"]
        out["预约未成行"] = _nz({
            "合计": sum(v["笔数"] for v in 摊.values()),
            "而真正到店的": 到店,
            "分开看": 摊,
            "note": "**三种不许混成一类** —— 已取消是客户主动说了不来,"
                    "爽约是没说就没来(**先确认人没事**),"
                    "已过期是系统判的(客户自己可能都不知道有这条预约)。"
                    "同一套话术发给后两种会很唐突。",
        })

    out["⚠️ 这个工具不发任何东西"] = (
        "发短信 / 发微信 / 打电话是**对外动作**,不在 agent 这儿。"
        "这里给的是「该跟谁、凭什么、什么顺序」,**按不按、怎么按是人的决定**。")
    return _nz(out)
def stock_alert(scope=None):
    """**库存预警 —— 哪些要断了、哪些看着有货其实发不出、哪些在压货。**

    805 个 SKU 全有库存数、60 条库存流水,而在这个工具之前
    **没有任何东西会说「这个要断了」** —— 只能等客户问了再去查。

    ## ⚠️ 可售天数现在**算不出来**,这个工具会直说

    intent 里写死了要给可售天数而不只是件数。做到这一步才发现:**给不了。**

        有销量的 SKU    **71 / 805**
        这 71 个各卖几件 **全部恰好 1 件**
        订单跨度        **17 天**

    销售速度要么是 0,要么是同一个数。这样的数据算出来的可售天数
    **不是指标,是装饰**,而**一个编出来的天数会让采购按它去补货**。

    所以这里报「算不出,缺的是销量样本和时间跨度」,
    **不换个算法凑一个数,也不偷偷退回成件数阈值** ——
    这个项目为「抓不到 ≠ 零」栽过好几次。

    ## 「在手」和「可用」是两个数

    `stock` 是在手,`locked` 是已被订单占用。客户问「还有货吗」要的是
    **可用 = 在手 − 已占用**。实测 **20 个 SKU 在手有货但全被占用** ——
    只报在手会说有货,而实际一件都发不出,客户白等。

    ## 没有补货点,也不自动补货

    补多少、什么时候补是**采购的决定**。而且补货点 = 补货周期内的销量 + 安全库存,
    前者算不出、后者要业务定「缺货一次的代价」——**两样都没有,任何一个数都是编的**。

    scope: 不传给全部;传「发不出」「断货」「快没了」「卖不动」只要一档。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import stockalert as _sa

    # 统计区间直接从订单数据来 —— **不写死,也不取今天**:
    # 写死的话数据长出来了这儿还是旧数;取今天的话跨度会随时间白白变长,
    # 而那不代表多了销量。
    # ⚠️ **区间也要用同一套过滤。** 分子(销量)只数卖掉了的,
    # 分母(天数)却数所有订单的话,一张一年前的取消单就会把跨度拉长 ——
    # 速度被稀释、可售天数偏大、该报的不报。**分子分母的口径必须是同一套。**
    日 = [x["created"][:10] for x in _rows(
        "SELECT o.created, o.status, o.refund_status FROM ordr o "
        "WHERE o.created IS NOT NULL")
        if _sa.卖掉了(x["status"], x["refund_status"])[0]]
    起, 止 = (min(日) if 日 else ""), (max(日) if 日 else "")
    跨天 = 0
    if 起 and 止:
        跨天 = (_dt.date.fromisoformat(止) - _dt.date.fromisoformat(起)).days + 1

    # **笔数和件数分开取。** 件数决定速度多大,笔数决定这个速度**能不能算** ——
    # 一单卖 10 件也还是一个点,而一个点画不出一条斜率。
    #
    # ⚠️ **要带上订单状态。** 第一版没带,于是取消的单、还没付钱的单
    # 全被算成卖出去了 —— 「下过单」和「卖掉了」长得一模一样。
    # 哪些算,在 `stockalert.卖掉了()` 里,不在这儿拍。
    卖过, 没算 = {}, {}
    for r in _rows("SELECT i.sku, i.qty, o.status, o.refund_status "
                   "FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                   "WHERE i.sku IS NOT NULL AND i.sku<>''"):
        算, 为啥 = _sa.卖掉了(r["status"], r["refund_status"])
        if not 算:
            # 归组的键要带上退款 —— 一行「待完成」因为退了款不算销量,
            # 按状态归组会显示成「待完成不算销量」,而那是假的:
            # **不算的理由是退款,不是状态。**
            k = (r["status"] + " · 已退款") if (r["refund_status"] or "") == "已退款" \
                else r["status"]
            没算.setdefault(k, [0, 为啥])[0] += 1
            continue
        a = 卖过.setdefault(r["sku"], [0, 0])
        a[0] += 1
        a[1] += r["qty"] or 0
    卖过 = {k: tuple(v) for k, v in 卖过.items()}

    rs = _rows("SELECT s.code, s.spu, s.spec, s.color, s.size, s.price, "
               "  s.stock, s.locked, s.status, p.name pname, p.status pstatus, "
               "  COALESCE(p.on_shelf_at, p.created) shelf "
               "FROM sku s LEFT JOIN product p ON p.spu=s.spu")

    摊 = {}
    停用 = 0
    for r in rs:
        # **停用的 SKU 不进预警。** 它不该有货可卖,库存为 0 是正常状态,
        # 报出来就是每天 8 条噪音 —— 而**误报比漏报贵**:
        # 一条误报会让采购去补一个已经下架的款。
        if r["status"] == "停用":
            停用 += 1
            continue
        笔, 件 = 卖过.get(r["code"], (0, 0))
        档位, 话 = _sa.档(r["stock"], r["locked"], 件)
        # **分母是这个 SKU 自己能卖的那段**,不是全局跨度 ——
        # 一个 6 月才上架的 SKU 按「2 月到 9 月」除,速度会被稀释、该报的不报。
        窗, 窗起, 窗说 = _sa.可卖窗口(r["shelf"], 起, 止)
        天, 为什么 = _sa.可售天数(r["stock"], r["locked"], 笔, 件, 窗)
        if 天 is None and 窗 is None and 窗说:
            为什么 = 窗说
        摊.setdefault(档位, []).append(_nz({
            "SKU": r["code"], "商品": r["pname"], "规格": r["spec"],
            "颜色": r["color"], "尺码": r["size"], "价格": r["price"],
            "在手": r["stock"], "已占用": r["locked"],
            "可用": _sa.可用(r["stock"], r["locked"]),
            "卖过几笔": 笔, "卖过几件": 件,
            "能卖了几天": 窗, "上架": (r["shelf"] or "")[:10] or None,
            "可售天数": 天 if 天 is not None else 为什么,
            # **数字一样而分量完全不同**:「12 天(上架 20 天、3 笔)」
            # 和「12 天(上架 300 天、90 笔)」不该被一样地信。
            "这个天数按多少数据算的": (f"{窗} 天里 {笔} 笔" if 天 is not None else None),
            # **0 天要说清它是真的 0。** 同一个 0,一个来自「不知道」、
            # 一个来自「已经卖空了」—— 在表上长得一模一样。
            "这个 0 是什么意思": ("**已经卖空了,不是「算不出」** —— "
                                  "它卖得动,而现在一件都发不出"
                                  if 天 == 0 else None),
            "⚠️": 窗说 if (窗说 and 窗 is not None) else None,
            "说明": 话,
        }))

    能算 = sum(1 for k in 摊 for x in 摊[k]
               if not isinstance(x.get("可售天数"), str))
    要哪些 = [scope] if scope in 摊 else ["发不出", "断货", "快没了", "卖不动"]
    out = {
        "统计区间": f"{起} → {止}(共 {跨天} 天)" if 跨天 else "**没有订单数据**",
        "在算的 SKU": len(rs) - 停用,
        "（停用的 {} 个不算）".format(停用): "停用的 SKU 本来就不该有货可卖,"
                                            "库存 0 是正常状态,报出来只是噪音",
    }
    档说明 = {
        "发不出": "**在手有货,但全被订单占用了** —— 库存表上看着有货,实际一件发不出。"
                  "这一档最要紧:它是唯一一种「看起来没问题」的缺货。",
        "断货": "在手和可用都是 0",
        "快没了": f"可用 ≤ {_sa.快没了_件数} 件,**而且它卖得动**。"
                  f"这条件数线是**业务 2026-09-22 定的**(后台库存列表页用的是同一个数)。"
                  "档内按可售天数从急到缓排 —— 「可用 2 件、能撑 60 天」比「可用 5 件、能撑 3 天」缓得多;"
                  "**「低于几天算该补」那条线仍是补货点,补货点是采购的决定**,这里不替它划。",
        "卖不动": "有货,而**一件都没卖过** —— 这不是缺货风险,是压货",
    }
    def _排(x):
        """**按可售天数排,算不出的排后面。**

        这一档原来按可用件数排。可售天数算得出之后,件数就不该再当序了 ——
        「可用 2 件、能撑 60 天」和「可用 4 件、能撑 3 天」,后者急得多。
        算不出的排在后面、按可用件数排,**不和算得出的混在一起比**。
        """
        d = x.get("可售天数")
        return (0, d) if isinstance(d, (int, float)) else (1, x.get("可用") or 0)

    for k in 要哪些:
        lst = sorted(摊.get(k, []), key=_排)
        out[k] = _nz({
            "个数": len(lst),
            "是什么": 档说明.get(k),
            "明细": lst[:30],
            **({"（只列了前 30 个）": f"共 {len(lst)} 个"} if len(lst) > 30 else {}),
        })

    out["⚠️ 为什么没有可售天数"] = (
        f"有销量的只有 {len(卖过)}/{len(rs) - 停用} 个 SKU,"
        f"而且**最多的一个也只有 {max((v[0] for v in 卖过.values()), default=0)} 笔**"
        f"(一笔画不出速度:「每 18 天卖 1 件」和「碰巧卖了 1 件」数据上一样),"
        f"订单只跨 {跨天} 天(而且每个 SKU 按**自己上架后**那段算,只会更短)。这样算出来的可售天数**不是指标,是装饰** —— "
        "而一个编出来的天数会让采购按它去补货。"
        "**缺的是:每个 SKU 有过若干笔销售、订单跨度够长。**"
        "在那之前这里只报算得出的事实,不凑数。")
    out["算进销量的"] = {
        "订单行": sum(v[0] for v in 卖过.values()),
        "有销量的 SKU": len(卖过),
        # ⚠️ **不许拿明细去数这个。** 明细每档只列前 30,而且「够」那一档
        # 根本不进明细 —— 数出来永远偏小。这个数扫的是全部 SKU。
        # 同一个病之前犯过一次(拿明细行数和口径对账,咬合咬不住)。
        "算得出可售天数的 SKU": 能算,
        "note": "**只数卖掉了的** —— 取消 / 待付款 / 已退款都不算。"
                "这个总数不受明细截断影响,检查拿它和口径对账。",
    }
    if 没算:
        # **不许静默丢掉。** 白名单的代价就是「少算了什么看不见」——
        # 「抓不到」和「零」不是一回事,这个项目为它栽过好几次。
        out["没算进销量的订单行"] = {
            "合计": sum(v[0] for v in 没算.values()),
            "分开看": {k: f"{v[0]} 行 —— {v[1]}" for k, v in sorted(没算.items())},
            "note": "**「下过单」和「卖掉了」是两件事。** 这些行不算销量,"
                    "但列在这儿 —— 少算了什么要看得见。",
        }
    out["⚠️ 这个工具不补货"] = (
        "补多少、什么时候补是**采购的决定**。"
        "而且补货点要销量数据和「缺货一次的代价」撑着,两样现在都没有。")
    out["面料不在这儿"] = ("这个工具只看成品 SKU。面料库存(135 种,4 种没现货)"
                          "影响的是**定制品工期**,是另一摊。")
    return _nz(out)


def pattern_queue():
    """**版师的排队看板 —— 「今天该我核什么」。**

    这个工具解决的不是「算不出来」,是「**没有入口**」:
    版师进来只能问某一个版型的某一件事,而他手上到底有多少活、
    哪一件最该先做,系统一个字都没说。**没有入口的能力等于没做。**

    ## 排序有依据,不按编号

    一张 86 行的清单等于没排队。这里按**影响面**排:
    这个版型下面挂着多少商品、多少订单行已经用它出过货 ——
    **核一个 PT06(7 个商品、5 条订单行)和核一个没人用的版型,价值差一个数量级。**

    ## 空和零要分开

    每一摊都报「总数 / 已完成 / 还剩」。一摊显示 0 的时候要说得出
    是「**做完了**」还是「**一条都没扫到**」—— 这两种在看板上长得一模一样,
    而它们该触发的动作正好相反。
    """
    out, 活 = {}, []

    # ── ① 裁片用料占比 ────────────────────────────────────────────────
    # 数的是登记行数(裁片**种类**数),不是要裁几块 —— 一片 qty=2 在表里也只有一行
    总片 = _rows("SELECT COUNT(*) n FROM pattern_piece WHERE ratio IS NOT NULL")[0]["n"]
    # 数的是登记行数(裁片**种类**数),不是要裁几块 —— 一片 qty=2 在表里也只有一行
    已核 = _rows("SELECT COUNT(*) n FROM pattern_piece WHERE ratio_src='版师'")[0]["n"]
    全核完 = _rows(
        # 数的是登记行数(裁片**种类**数),不是要裁几块 —— 一片 qty=2 在表里也只有一行
        "SELECT COUNT(*) n FROM (SELECT pattern FROM pattern_piece "
        "GROUP BY pattern HAVING SUM(CASE WHEN ratio_src='版师' THEN 0 ELSE 1 END)=0)")[0]["n"]
    # **影响面**:挂的商品数 + 已出过货的订单行数。两个都算,因为它们答的不是同一个问题
    # (商品多 = 以后会一直用;订单行多 = 已经在按这个数备料了)。
    先核 = _rows(
        "SELECT pp.pattern, pt.name, "
        "  COUNT(DISTINCT pp.name) 片数, "
        "  SUM(CASE WHEN pp.ratio_src='版师' THEN 1 ELSE 0 END) 已核, "
        "  (SELECT COUNT(*) FROM product p WHERE p.pattern=pp.pattern) 商品数, "
        "  (SELECT COUNT(*) FROM ordr_item oi JOIN product p2 ON p2.spu=oi.spu "
        "   WHERE p2.pattern=pp.pattern) 订单行 "
        "FROM pattern_piece pp JOIN pattern pt ON pt.code=pp.pattern "
        "GROUP BY pp.pattern, pt.name "
        "HAVING 已核 < 片数 "
        "ORDER BY 商品数 DESC, 订单行 DESC, pp.pattern LIMIT 8")
    活.append(_nz({
        "事": "裁片用料占比",
        "进度": f"{已核}/{总片} 片已核,{全核完}/{_rows('SELECT COUNT(DISTINCT pattern) n FROM pattern_piece')[0]['n']} 个版型全核完",
        "状态": ("**一条都还没核**" if 已核 == 0 else None),
        "建议先核": [dict(版型=r["pattern"], 名称=r["name"],
                          进度=f"{r['已核']}/{r['片数']}",
                          影响=f"挂 {r['商品数']} 个商品、{r['订单行']} 条订单行已按这个数备料")
                     for r in 先核],
        "怎么核": "`piece_ratios(版型)` 看明细和折合米数,`set_piece_ratio(...)` 改一片",
    }))

    # ── ② 推档疑点 ────────────────────────────────────────────────────
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import grading as _g
    疑 = _grading_scan()
    活.append(_nz({
        "事": "推档自检",
        "进度": f"{疑['扫了']} 个版型、{疑['格子']} 条尺码全部扫过",
        # 看板上只给**一行摘要**,细节去 grading_audit 看 ——
        # 同一段 60 字的解释在四个版型下各贴一遍,这一屏就只剩它了。
        "有疑点的版型": [f"{r['版型']} {r['名称']}:"
                         f"{r['疑点'][0].split('——')[0].strip()}"
                         + (f"(共 {len(r['疑点'])} 类)" if len(r["疑点"]) > 1 else "")
                         for r in 疑["疑点"][:8]] or None,
        "状态": ("档差处处对得上 —— **这不叫没查,是查过了**" if not 疑["疑点"] else None),
        "怎么核": "`grading_audit(版型)` 看逐部位的档差;"
                  f"**要核的是那 {len(_g.档差())} 条档差,不是 {疑['格子']} 个数**",
    }))

    # ── ③ 推得出但不作数的格子 ────────────────────────────────────────
    参考 = _rows("SELECT pattern, item, COUNT(*) n, MAX(caveat) why FROM size_spec "
                 "WHERE caveat IS NOT NULL GROUP BY pattern, item ORDER BY pattern")
    if 参考:
        # **按理由分组。** 上一版这里是一张平铺的清单加一句「为什么」——
        # 而清单里其实混着**两件不同的事**(马面裙的褶位、童款的身高码),
        # 那句「为什么」只解释了其中一件,另一件被它的解释盖住了。
        # 「一列承载两件事」这个坑,这一轮已经撞到第六次。
        组 = {}
        for r in 参考:
            组.setdefault(r["why"], []).append(f"{r['pattern']}·{r['item']}({r['n']} 个码)")
        活.append({
            "事": "推得出但不作数的尺码",
            "进度": f"{sum(r['n'] for r in 参考)} 格,分布在 "
                    f"{len({r['pattern'] for r in 参考})} 个版型、{len(组)} 种原因",
            "分组": [{"为什么": why, "哪些": lst} for why, lst in 组.items()],
            "note": "**这两组的性质不一样**:褶位那组是**常设提醒**(每次出货都要重排,"
                    "不是核一次就完了);童款那组是**缺一张档差表**(补上就能重推)。"
                    "混在一张清单上会让人以为是同一件事。",
        })

    # ── ④ 没有版型的定制品 ────────────────────────────────────────────
    无版 = _rows(
        "SELECT p.spu, p.name, p.category FROM product_custom pc "
        "JOIN product p ON p.spu=pc.spu "
        "WHERE p.pattern IS NULL OR p.pattern=''")
    if 无版:
        活.append({
            "事": "配置页上架了、但没有版型的定制品",
            "进度": f"{len(无版)} 个",
            "明细": [f"{r['name']}({r['spu']})" for r in 无版],
            "note": "规则说「没有版型就裁不出来,不能在配置页上架,须先请版师建版」。"
                    "但这几个看名字像**配饰**(云肩 / 团扇 / 香囊 / 腰封),"
                    "**配饰可能本来就不需要版型** —— "
                    "**要版师确认一次:是真不需要,还是漏建了。**"
                    "⚠️ 「确认不需要」这件事目前**没有地方记**,确认完它还会再出现在这张单上。",
        })

    # ── ⑤ 在等改版的单 ────────────────────────────────────────────────
    #
    # 系统里三处写着「推荐尺码最终由版师定」,而版师**看不到有谁在等他定**。
    # 这一摊把那件事接上:**有体型特征的着装人**(那是「直接全定制」的硬条件)
    # 落在**还没走完的单**上。
    #
    # ⚠️ **这里只给尺寸和体型,不给手机号、不给金额。**
    # 版师需要知道「这个人身上有什么要改版的地方」,不需要知道他花了多少钱 ——
    # 而多给的字段会被用(这个项目在 allowed_tools 上栽过)。
    # 这条边界有检查盯着:`pattern_role_check` 会把版师的**每一个工具**
    # 真跑一遍,扫返回里有没有手机号形状的串或金额字段。
    等改版 = _rows(
        "SELECT oi.order_id, oi.wearer_id, oi.name item, o.status, p.pattern, "
        "  pt.name pattern_name, "
        "  (SELECT GROUP_CONCAT(feature,'、') FROM body_feature b "
        "   WHERE b.wearer_id=oi.wearer_id) feature "
        "FROM ordr_item oi JOIN ordr o ON o.id=oi.order_id "
        "LEFT JOIN product p ON p.spu=oi.spu "
        "LEFT JOIN pattern pt ON pt.code=p.pattern "
        "WHERE oi.wearer_id IS NOT NULL AND o.status NOT IN ('完成','取消') "
        "  AND EXISTS(SELECT 1 FROM body_feature b WHERE b.wearer_id=oi.wearer_id) "
        "ORDER BY oi.order_id")
    活.append(_nz({
        "事": "在等改版的单(着装人有体型特征)",
        "进度": f"{len(等改版)} 条 —— "
                f"库里共 {_rows('SELECT COUNT(DISTINCT wearer_id) n FROM body_feature')[0]['n']}"
                f" 位着装人有体型特征,其中这些落在还没走完的单上",
        "明细": [f"{r['order_id']} · {r['wearer_id']}({r['feature']})· "
                 f"{r['pattern_name'] or '未挂版型'} · {r['status']}"
                 for r in 等改版] or None,
        "状态": ("**一条都没有** —— 是真没有,不是没扫到(扫的是全部未完结的单)"
                 if not 等改版 else None),
        "怎么核": "`kb_fit(客户, 版型, 着装人)` 看逐项差值和关键尺寸覆盖。"
                  "⚠️ **具体改哪儿、改多少不在知识库里** —— "
                  "系统能说的到「要出专属版」为止,不要替版师给数",
    }))

    out["谁在看"] = (whoami() or {}).get("name") or "(没登录)"
    out["该核的活"] = 活
    out["note"] = ("每一摊都报了「总数 / 已完成 / 还剩」—— "
                   "**「做完了」和「一条都没扫到」在看板上长得一模一样**,"
                   "而它们该触发的动作正好相反。"
                   "排序按**影响面**(挂多少商品、多少订单行已经按这个数备料),"
                   "不按编号 —— 一张 86 行的清单等于没排队。")
    return out


def _grading_scan():
    """把全部版型的推档扫一遍。**给 pattern_queue 和 grading_audit 共用一个口径。**"""
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import grading as _g
    pats = _rows("SELECT code,name FROM pattern ORDER BY code")
    片 = {}
    for r in _rows("SELECT pattern,name FROM pattern_piece"):
        片.setdefault(r["pattern"], []).append(r["name"])
    格子, 疑点 = 0, []
    for p in pats:
        rs = _rows("SELECT size,item,value FROM size_spec WHERE pattern=?", p["code"])
        格子 += len(rs)
        tbl = {}
        for r in rs: tbl.setdefault(r["size"], {})[r["item"]] = r["value"]
        参考 = set(_g.参考项(片.get(p["code"], [])))
        bad = []
        for 部位, d in _g.核档(tbl, 参考).items():
            # **顺序有意义。** 「算不出来」要排在「算出来不对」前面 ——
            # 童款那四个版型第一次扫出来报的是「实际 [] ≠ 规则 4.0」,
            # 看着像档差错了,实际是**一个码都比不了**(身高码不在序号表里)。
            # **红错理由比不红更费事**:照着那条去查档差是白费功夫。
            if d["算不出来"]:
                bad.append(f"{部位}:**算不出档差** —— {d['算不出来的原因']}")
            elif not d["有规则"]:
                bad.append(f"{部位}:**没有档差规则**,只能按基码出")
            elif not d["处处相等"]:
                bad.append(f"{部位}:相邻码的差不一致 {d['实际档差']}")
            elif not d["和规则一致"]:
                bad.append(f"{部位}:实际 {d['实际档差']} ≠ 规则 {d['规则档差']}")
        for sz, v in tbl.items():
            bad += [f"{sz} 码:{x}" for x in _g.体检(v, 参考)]
        # **同一个理由不要说四遍。** 一条 40 个字的解释乘以 4 个部位,
        # 会把这一屏挤满,而看的人以为是四个不同的问题。按理由归并:
        # 「上襦衣长 / 胸围 / 裙腰围 / 裙长:算不出档差 —— <理由说一次>」
        if bad:
            合 , 序 = {}, []
            for line in bad:
                部位, _, 理由 = line.partition(":")
                if 理由 not in 合: 合[理由] = []; 序.append(理由)
                合[理由].append(部位)
            疑点.append(dict(版型=p["code"], 名称=p["name"],
                             疑点=[f"{' / '.join(合[r])}:{r}" for r in 序][:4]))
    return dict(扫了=len(pats), 格子=格子, 疑点=疑点)


def grading_audit(pattern=None):
    """**推档自检 —— 把「要核 1237 个数」压成「要核 12 条档差」。**

    `size_spec` 那 1237 条全是推出来的(基码值 + 档差 × 尺码序号)。
    让版师逐条核是不现实的,而他真正该核的只有两样:**基码表**和**那 12 条档差**。

    不传 pattern 给全局:扫了多少、哪几个版型有疑点。
    传 pattern 给这一个版型的逐部位明细:实际档差、规则档差、覆盖范围、量纲体检。

    ## 判据零误报,因为它是定义性的

    「相邻码之间的差处处相等,而且等于档差表里那个数」——
    这是推档的**定义**,不是一个「看起来合理」的阈值。
    上一次栽在阈值上:裁片占比第一版把「单片 > 60%」一律当异常,
    而马面裙的裙片占 90% 本来就正常。**一刀切的阈值会把对的判成错的**,
    而那种误报比漏报贵:它会让人去改一个本来对的数。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import grading as _g
    if not pattern:
        r = _grading_scan()
        return _nz({
            "扫了": f"{r['扫了']} 个版型 / {r['格子']} 条尺码",
            "档差规则": _g.档差(),
            "有疑点的版型": r["疑点"] or None,
            "note": (f"要核的是上面那 {len(_g.档差())} 条档差和各版型的基码,"
                     f"**不是 {r['格子']} 个数** —— 尺码表是推出来的,"
                     f"改一条档差对全部码生效。"
                     + ("  这一轮**一个疑点都没有**:档差处处对得上 —— "
                        "**这不叫没查,是查过了**(扫了全部 "
                        f"{r['格子']} 条)。" if not r["疑点"] else "")),
        })
    p = _rows("SELECT code,name,sizes,version FROM pattern WHERE code=? OR name=?",
              pattern, pattern)
    if not p:
        return {"error": f"没有版型「{pattern}」(认版型编码 PT04,也认全名「明制马面裙·标准」)"}
    p = p[0]
    片 = [r["name"] for r in _rows("SELECT name FROM pattern_piece WHERE pattern=?", p["code"])]
    参考 = _g.参考项(片)
    rs = _rows("SELECT size,item,value FROM size_spec WHERE pattern=?", p["code"])
    tbl = {}
    for r in rs: tbl.setdefault(r["size"], {})[r["item"]] = r["value"]
    明细 = []
    for 部位, d in sorted(_g.核档(tbl, set(参考)).items()):
        基 = tbl.get("M", {}).get(部位)
        rng = _g.覆盖范围(基, 部位, list(tbl)) if 基 is not None else None
        明细.append(_nz({
            "部位": 部位,
            "基码(M)": 基,
            "实际档差": (d["实际档差"][0] if len(d["实际档差"]) == 1 else d["实际档差"]),
            "规则档差": d["规则档差"],
            "对不对": ("⚠️ 算不出档差 —— " + (d["算不出来的原因"] or "")
                       if d["算不出来"] else
                       "✅ 和规则一致" if d["和规则一致"] else
                       "⚠️ 没有档差规则,只能按基码出" if not d["有规则"] else
                       "❌ 和规则对不上"),
            "覆盖范围": (f"{rng[0]}–{rng[1]}cm" if rng else None),
            "⚠️ 推得出但不作数": 参考.get(部位),
        }))
    体 = {sz: _g.体检(v, set(参考)) for sz, v in tbl.items()}
    体 = {k: v for k, v in 体.items() if v}
    _v = _rows("SELECT version FROM pattern WHERE code=?", p["code"])
    return _nz({
        "版型": f"{p['code']} {p['name']}",
        "版本": f"v{(_v[0]['version'] if _v else 1)}",
        "尺码": p["sizes"],
        "逐部位": 明细,
        "量纲体检": 体 or None,
        "note": (f"这个版型有 {len(明细)} 个部位、{len(rs)} 条尺码,"
                 f"**要核的是上面 {len(明细)} 行的「基码 + 档差」两个数,不是 {len(rs)} 个**。"
                 + ("  量纲体检全过(值为正、领围小于胸围、马面宽小于腰围)——"
                    "**扫了全部 " + str(len(tbl)) + " 个码,不是没扫**。" if not 体 else "")),
    })


def set_piece_ratio(pattern, piece, ratio, why=""):
    """**改一片的用料占比,并标成「版师核过」。**

    这是版师手上**唯一一个会改数据的工具** —— 版型、商品、订单都动不了。

    ⚠️ 改一片之后,**同一个版型的其余片会按比例重新归一**,让总和回到 1 ——
    否则总和不是 1,分摊出来的米数就和整件用料对不上。
    **而已经标「版师」的片不参与重新归一** —— 人核过的数不许被自动调。

    所以:**先核大片,再核小片**。反过来的话,先核的小片会被后面的归一挤动……
    不会,因为标过「版师」的就锁住了。这条写在这儿是提醒顺序不影响结果。

    ## 身份从会话取,**不收身份参数**

    和别的写工具一样(`WRITE_TOOLS`,`isolation_check` 逐个验):
    签名里没有 role / actor —— 有的话,一句「我以版师身份」就能提权。
    而且**必须写 why**:这一列存下来是为了回答三个月后那句
    「袖片为什么是 0.22」。只标一个「版师核过」答不了它 ——
    那只说了「有人核过」,没说是谁、凭什么。
    """
    me = whoami()
    if not me:
        return {"error": "不知道现在是谁在核 —— 请先登录。"
                         "**改过的数必须查得到是谁改的**,匿名改不了"}
    if me.get("role") != "版师":
        return {"error": f"核裁片用料要由版师来做,你的角色是「{me.get('role')}」。"
                         f"**这个数是排料的依据** —— 核错了整批面料会不够裁"}
    if not (why or "").strip():
        return {"error": "why 必填:这个数是量的、照排料图算的、还是比着老版定的?"
                         "**不写的话下次有人问「为什么是这个数」就查不到了**"}
    p = _rows("SELECT code,name,fabric_base FROM pattern WHERE code=? OR name=?",
              pattern, pattern)
    if not p:
        return {"error": f"没有版型「{pattern}」"}
    code = p[0]["code"]
    tgt = _rows("SELECT name,ratio FROM pattern_piece WHERE pattern=? AND name=?",
                code, piece)
    if not tgt:
        有 = [r["name"] for r in _rows(
            "SELECT name FROM pattern_piece WHERE pattern=?", code)]
        return {"error": f"版型 {code} 没有「{piece}」这个裁片。它有:{有}"}
    try:
        ratio = float(ratio)
    except Exception:
        return {"error": "占比要是数字,0–1 之间(0.25 表示 25%)"}
    if not (0 < ratio < 1):
        return {"error": f"占比要在 0 和 1 之间,收到 {ratio}。"
                         f"**一片占满整件(1)或者不占布(0)都不成立**"}
    旧 = tgt[0]["ratio"]
    import sqlite3 as _sq, datetime as _dt
    # **工号那一栏叫 `no`,不叫 `id`。** 第一版写的是 `me.get('id')` ——
    # 后台的 `/api/me` 只发 `no`,于是这一栏在真实登录下**永远是空的**,
    # 存进去的只有姓名。而 `pattern_role_check` 当时是绿的,
    # 因为**我在夹具里同时喂了 `no` 和 `id`** —— 夹具比真实情况更宽容,
    # 于是检查测的是一个现实中不存在的入参形状。
    # **夹具喂出来的绿,和真的绿长得一模一样。**
    who = f"{me.get('no') or me.get('id') or ''}|{me.get('name') or ''}".strip("|")
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _sq.connect(DB) as cx:
        cx.execute("UPDATE pattern_piece SET ratio=?, ratio_src='版师', "
                   "ratio_by=?, ratio_at=?, ratio_why=? "
                   "WHERE pattern=? AND name=?",
                   (ratio, who, now, why.strip(), code, piece))
        # 其余**没被版师核过的**片按比例重新归一
        剩 = cx.execute(
            "SELECT name, ratio FROM pattern_piece "
            "WHERE pattern=? AND name!=? AND COALESCE(ratio_src,'')!='版师'",
            (code, piece)).fetchall()
        锁 = cx.execute(
            "SELECT COALESCE(SUM(ratio),0) FROM pattern_piece "
            "WHERE pattern=? AND ratio_src='版师'", (code,)).fetchone()[0] or 0
        余 = 1.0 - 锁
        老和 = sum((r[1] or 0) for r in 剩) or 1.0
        if 余 <= 0 and 剩:
            return {"error": f"改不了:这个版型已经核过的片加起来是 {round(锁,4)},"
                             f"**再加这一片就超过 1 了**。先把别的片调小"}
        for nm2, r2 in 剩:
            cx.execute("UPDATE pattern_piece SET ratio=? WHERE pattern=? AND name=?",
                       (round((r2 or 0) / 老和 * 余, 6), code, nm2))
    fb = p[0]["fabric_base"] or 0
    return {"ok": True, "版型": p[0]["name"], "裁片": piece,
            "改前": 旧, "改后": ratio,
            "折合米数": f"{round((旧 or 0)*fb,3)} → {round(ratio*fb,3)} 米",
            "核的人": who, "核的时刻": now, "理由": why.strip(),
            "note": f"已标「版师」,**不会再被估算覆盖**。"
                    f"同版型其余**没核过**的片已按比例重新归一,总和仍是 1;"
                    f"**已核过的片没动** —— 人核过的数不许被自动调。"
                    f" 这一笔记在 pattern_piece 上:{who} / {now} / 理由:{why.strip()}"}


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
                "负责人": r.get("assignee_name") or r.get("advisor_no"),
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


def record_fitting(order_id, item, adjust="", signed=False, round=None, note=""):
    """**登记一轮白坯试衣**(真的写进去)。顾问 / 店长,只能登记本店订单。

    陪同人就是登录的人 —— **不收工号参数**,收了就能替别人登记一次自己没陪的试衣。
    `round` 不给是新的一轮;给已有轮次且 signed=True 是**补签**(签字不许撤销)。

    ⚠️ **动手之前先跟用户对一遍**:哪张单、哪一件、改了哪几处、客户签没签。
    签字是责任转移点 —— 记成「签了」而客户其实没签,出尺寸争议时门店会拿着一张不存在的底牌。
    """
    import fitting_write as fw
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在登记 —— 请先登录")
    r = fw.record(dict(order_id=order_id, item=item, adjust=adjust, signed=signed,
                       round=round, note=note), me)
    if r.get("ok"): _agent_log(me, r.get("code", "FIT"), r.get("reason", ""))
    return r


def record_pickup(order_id, action, mode=None, tracking_no=None, issue=None,
                  matches_record=None, other_defect=None, our_fault=None):
    """**交付签收的三个动作**(真的写进去):到店代收 / 取件方式 / 不合身。顾问 / 店长,只能动本店的单。

    action  「到店代收」—— 工厂发到店,这一单到了(只认已发货的定制单)
            「取件方式」—— mode = 到店取 / 转寄;转寄要 tracking_no(物流单号)
            「不合身」  —— 顾客试了不合身,**不算签收**,订单不动;issue 写清哪里不合身。
                          matches_record / other_defect / our_fault 是**查出来的事实**,不知道就别填 ——
                          填了会影响判责建议,而建议最后由人确认
    """
    import pickup_write as pw
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在操作 —— 请先登录")
    d = dict(order_id=order_id, mode=mode, tracking_no=tracking_no, issue=issue,
             matches_record=matches_record, other_defect=other_defect, our_fault=our_fault)
    fn = {"到店代收": pw.arrive, "取件方式": pw.set_mode, "不合身": pw.not_fit}.get((action or "").strip())
    if not fn:
        return dict(ok=False, code="BAD_ACTION", reason="action 只认「到店代收 / 取件方式 / 不合身」")
    r = fn(d, me)
    if r.get("ok"): _agent_log(me, r.get("code", "PICKUP"), r.get("reason", ""))
    return r


def verify_fit_code(order_id, code):
    """**核验顾客给的 6 位码 = 签收**(真的写进去):订单「已发货 → 待完成」。顾问 / 店长,本店的单。

    码是顾客在手机上点「试穿合身」拿到的,**只能是顾客给的、用户说出来的那一个** —— 不许编、不许猜。
    """
    import pickup_write as pw
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在核验 —— 请先登录")
    r = pw.verify(dict(order_id=order_id, code=code), me)
    if r.get("ok"): _agent_log(me, "SIGN", r.get("reason", ""))
    return r


def ratify_complete(order_id, reason):
    """**顾问追认完成**(真的写进去):签收满 15 天顾客还没确认,写理由把「待完成」推成「完成」。"""
    import pickup_write as pw
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在追认 —— 请先登录")
    r = pw.ratify(dict(order_id=order_id, reason=reason), me)
    if r.get("ok"): _agent_log(me, "RATIFY", r.get("reason", ""))
    return r


def start_cutting(order_id):
    """**开裁**:把一张定制单从「待生产」推进到「生产中」(真的写进去)。只有版师能开。

    **过不了白坯试衣那道闸就拒绝**(业务 09-22):单里有一件该试没试、试了没签字、
    或判不了该不该试而又没试过,整单不许裁。拒绝时会列出是哪几件、缺什么。

    ⚠️ **动手之前先跟用户确认单号** —— 开裁不可逆,裁下去就没有回头路。
    """
    import fitting_write as fw
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在开裁 —— 请先登录")
    r = fw.start_cutting(dict(order_id=order_id), me)
    if r.get("ok"): _agent_log(me, "CUT", r.get("reason", ""))
    return r


def open_order(customer_id, items):
    """**开一张定制单**(真的写进去),停在「待确认」。顾问 / 店长,只给本店客户开。

    items  [{"spu" 或 "sku": ..., "wearer_id": 给谁做, "qty": 件数}] —— 每一件都要指明给谁做,
           下单量体量的必须是穿这件的人(业务 09-22)。
    开完**还没生效**:下一步给每一件量下单量体并绑上(record_measure 带 order_id + item),再 confirm_order。
    ⚠️ 动手前先跟用户对一遍:哪位客户、哪几件、每件给谁做。
    """
    import order_write as ow
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在开单 —— 请先登录")
    r = ow.open_order(dict(customer_id=customer_id, items=items), me)
    if r.get("ok"): _agent_log(me, "OPEN", r.get("reason", ""))
    return r


def confirm_order(order_id):
    """**确认下单**(真的写进去):待确认 → 待审核。定制单确认即已付款(业务 09-22)。

    **逐件过闸**:每一件都要有绑在它上面的、开单之后量的、够做这件衣服的下单量体;
    有一件不过整单拒绝,返回里列出是哪几件、缺什么。
    ⚠️ 动手前先跟用户确认单号 —— 确认之后就进审核、算已付款。
    """
    import order_write as ow
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在确认 —— 请先登录")
    r = ow.confirm_order(dict(order_id=order_id), me)
    if r.get("ok"): _agent_log(me, "CONFIRM", r.get("reason", ""))
    return r


def record_measure(wearer_id, values, method, inner, shoe, breath, order_id=None, item=None):
    """**登记一次量体**(真的写进去)。顾问 / 店长,只能录本店客户;量体人就是登录的人。

    values  {量体项名: 数值},如 {"胸围": 86, "腰围": 68}
    method  到店 / 上门(业务 09-22 不准远程)
    inner / shoe / breath  内搭 / 鞋 / 呼吸 —— **缺一件就等于没量**
    order_id + item  给了就是这一件的**下单量体**:签单时按这件重新量,这一件以它为准

    ⚠️ **动手前先跟用户对一遍**:给谁量的(着装人)、哪几项多少、到店还是上门、三个条件、
    是不是某一件的下单量体。尺寸录错了,衣服就按错的做。
    """
    import measure_write as mw
    try: me = _need_me()
    except _NoIdentity: return dict(error="不知道现在是谁在录 —— 请先登录")
    r = mw.record(dict(wearer_id=wearer_id, values=values, method=method, inner=inner, shoe=shoe,
                       breath=breath, order_id=order_id, item=item), me)
    if r.get("ok"): _agent_log(me, "MEASURE", r.get("reason", ""))
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


KB_DOCS = {
    "01": ("01-形制.md", "形制:朝代、款式、怎么配"),
    "02": ("02-面料.md", "面料:特性、适合什么、怎么洗"),
    "03": ("03-工艺.md", "工艺:织造/刺绣/印染/缝制四类,什么时候能加"),
    "04": ("04-配饰.md", "配饰:什么形制配什么"),
    "05": ("05-颜色.md", "颜色:配色与忌讳"),
    "06": ("06-相容矩阵.md", "相容矩阵:什么工艺能上什么面料,以及为什么"),
    "07": ("07-工期与成本.md", "工期与成本:怎么估、什么会拖"),
    "08": ("08-量体与版型.md", "量体与版型:量哪些、怎么判档"),
    "09": ("09-养护与售后.md", "养护与售后:怎么洗、怎么存、争议怎么判"),
    "10": ("10-版型库.md", "版型库:裁片、尺码、档差、放松量"),
    "11": ("11-物料与BOM.md", "物料与 BOM:用量、损耗、备料"),
    "12": ("12-成长与生命周期.md", "成长与生命周期:孩子长多快、什么时候复量"),
}


def _kb_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge")


def _kb_file(doc):
    """把「09」「养护」「09-养护与售后.md」都解析成同一个文件。

    ⚠️ **不接受调用方给的路径**,只在上面那张写死的表里挑。
    接受路径的话这就是一个 `Read` 工具了 —— 而这个项目最硬的一条主张是
    「挂给模型的工具只能读业务数据」。`boundary_audit` 拿 `../CLAUDE.md`
    和 `/etc/passwd` 攻击过这里。
    """
    k = (doc or "").strip()
    if k in KB_DOCS: return KB_DOCS[k]
    for code, (fn, desc) in KB_DOCS.items():
        if k == fn or k.lstrip("0") == code.lstrip("0"): return (fn, desc)
    hit = [(fn, d) for fn, d in KB_DOCS.values() if k and (k in fn or k in d)]
    if len(hit) == 1: return hit[0]
    return None


def kb_read(doc=None, section=None):
    """**读知识库原文** —— 表里没有、只能在正文里的那些话。

    库里已经有推导出来的**结构化**数据(尺码、用量、相容),`kb_tables` 也放了 9 张表。
    漏的是**正文**:怎么洗、怎么存、为什么这么做、客户问「为什么这么贵」时怎么答。
    那些话原来只在 md 里,模型一个字都读不到 —— 于是它只能凭训练知识讲,
    而 TL01 明写着不许。

    ## 先给目录,再给正文

    不传 `section` 给这一篇的**小节目录**;传了给那一节的正文。
    **不许一次吐整篇** —— 版型库那篇 961 行,一次给出去会把上下文淹掉,
    而淹掉的后果不是报错,是**后面真正该看的东西被挤出去了**。

    ## 来源标记跟着正文走

    md 里的 `public` / `scale` / `demo` 是**行内标**的,取一节就要把这一节里
    出现过的标记一起带出来,并按**最低那一档**给对客口径 ——
    和分部位报价「按最贵的料报」是同一个方向:**偏错的代价不对称**。
    """
    import sys as _s
    _s.path.insert(0, _kb_dir())
    import source as _src
    f = _kb_file(doc)
    if not f:
        return {"error": f"没有「{doc}」这一篇",
                "有这几篇": {k: v[1] for k, v in KB_DOCS.items()}}
    fn, desc = f
    path = os.path.join(_kb_dir(), fn)
    if not os.path.isfile(path):
        return {"error": f"{fn} 不在 —— **不要凭印象补**,先确认知识库是不是缺文件"}
    txt = open(path, encoding="utf-8").read()
    # 按二级标题切;一级标题(#)当成篇首
    节, 当前 = [], {"标题": "(篇首)", "行": []}
    for line in txt.split("\n"):
        if line.startswith("## "):
            节.append(当前); 当前 = {"标题": line[3:].strip(), "行": []}
        else:
            当前["行"].append(line)
    节.append(当前)
    节 = [x for x in 节 if any(l.strip() for l in x["行"])]

    def 档(块):
        """这一块里出现过哪些来源标记 —— **按最低那一档给口径**。"""
        有 = [g for g in ("demo", "scale", "public") if f"`{g}`" in 块]
        低 = 有[0] if 有 else None
        return 有, 低

    if not section:
        return _nz({
            "篇": f"{fn} —— {desc}",
            # ⚠️ **标记常常写在小节标题上**(`## 三、交付时必须书面告知的六条 `demo``),
            # 第一版只扫正文行,于是三节带着 demo 标的小节全报「没有标记」——
            # 而「没有标记」会被读成「这节不是演示数据」,**正好读反**。
            "小节": [{"标题": x["标题"], "行数": len(x["行"]),
                      "来源标记": 档(x["标题"] + "\n" + "\n".join(x["行"]))[0] or None}
                     for x in 节],
            "note": "传 `section`(小节标题,写一部分也认)取正文。"
                    "**不给整篇** —— 一次吐几百行会把后面真正该看的挤出去。",
        })
    k = section.strip()
    命中 = [x for x in 节 if k == x["标题"]] or \
           [x for x in 节 if k in x["标题"]]
    if not 命中:
        return {"error": f"「{fn}」里没有「{section}」这一节",
                "有这几节": [x["标题"] for x in 节]}
    if len(命中) > 1:
        return {"error": f"「{section}」对应多节,说具体点",
                "对应": [x["标题"] for x in 命中]}
    x = 命中[0]
    body = "\n".join(x["行"]).strip()
    MAX = 6000
    截 = len(body) > MAX
    有, 低 = 档(x["标题"] + "\n" + body)     # 标题上的标记也算(见上)
    out = {"篇": fn, "小节": x["标题"], "正文": body[:MAX]}
    if 截:
        out["⚠️ 截断"] = (f"这一节 {len(body)} 字,只给了前 {MAX} 字。"
                          "要后面的部分,指定更细的小节(三级标题)")
    if 低:
        out.update(_src.标注(低))
        out["这一节出现的来源标记"] = 有
        out["note"] = ("**按最低那一档说话** —— 一节里混着几档时,"
                       "对客户的口径取最保守的那个。")
    else:
        out["note"] = ("这一节正文里**没有来源标记** —— 不代表它可靠,"
                       "代表没人标过。对客户引用前先确认。")
    return _nz(out)


def kb_detail(code):
    """按编码取某一条的完整内容"""
    r=_rows("SELECT * FROM craft WHERE code=?",code)
    if not r: return {"error":f"没有编码 {code} 这一条"}
    return _nz(_with_source(_with_material(r[0])))

def _resolve(x, cat):
    """把「云锦」「MT02」都解析成同一条。模型不知道编码,让它猜编码是工具设计的错误 ——
    实测过:它会拿着猜错的编码得到一个关于完全不同组合的答案,然后自信地讲出来。"""
    x=(x or "").strip()
    if not x: return None,"空值"
    r=_rows("SELECT code,name,cat FROM craft WHERE code=? AND cat=?",x.upper(),cat)
    if r: return r[0],None
    r=_rows("SELECT code,name,cat FROM craft WHERE cat=? AND (name=? OR alias=?)",cat,x,x)
    if r: return r[0],None
    # **别名是顿号分隔的多值,不能按整列相等比。**
    # 上面那句 `alias=?` 只有在别名恰好只有一个时才成立:
    # 「立领袄」能命中(XZ04 的别名就这一个),而「圆领袍」命不中 ——
    # XZ09 的别名是「圆领袍、常服袍」,整列不等于其中任何一个。
    # 于是它掉进下面的模糊分支,撞上「明制圆领袍」和「童款圆领袍」两条,
    # 报「对应多条」——**而它本来是一个明确声明的别名,不该是模糊匹配**。
    # **一个明确声明的别名要赢过模糊包含。**
    r=[q for q in _rows("SELECT code,name,alias,cat FROM craft WHERE cat=?",cat)
       if x in [a.strip() for a in (q["alias"] or "").split("、") if a.strip()]]
    if len(r)==1: return {k:r[0][k] for k in ("code","name","cat")},None
    if len(r)>1:
        return None,(f"「{x}」是这几条的别名:{[q['name'] for q in r]} —— "
                     f"请用形制全名或编码")
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
    # **这一单是从哪条方案来的。** 顾问问「这单当初定的是什么工艺」时,
    # 答案在方案上,不在订单行上 —— 订单行只有 SKU 和金额。
    _sc = _rows("SELECT * FROM scheme WHERE id=?", o.get("scheme_id")) \
        if o.get("scheme_id") else []
    if _sc:
        with _c() as _cc:
            o["来自方案"] = _scheme_ref.展开(_cc, _sc[0])
    elif o.get("kind") == "定制品订单":
        # **定制单没挂方案,是一条要报出来的事,不是沉默。**
        # 这类单的配置只存在于订单行和人的记忆里,查不到当初为什么这么定。
        o["来自方案"] = None
        o["方案缺口"] = "这是定制单,但没有关联方案 —— 当初的配置依据查不到"
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
            "门店":o["shop"],"顾问工号":o["advisor_no"],"来源":o["source"],"配送":o["delivery"],
            "金额":dict(商品额=g,运费=f,订单额=a,应付=o["payable"],已收=o["received"],
                       退款状态=o["refund_status"]),
            "时间线":dict(tl),"订单行":items,"售后":af,
            # ⚠️ 这个 return **重新拼了一个 dict**,往 `o` 上挂字段是挂不进来的 ——
            # 写成功了、也不报错,只是没人看得见。第一版就是这么丢掉的。
            "来自方案":o.get("来自方案"),
            **({"方案缺口": o["方案缺口"]} if o.get("方案缺口") else {}),
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


import importlib.util as _ilu, os as _os
_sr_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                         "knowledge", "scheme_ref.py")
_sr_spec = _ilu.spec_from_file_location("scheme_ref", _sr_path)
_scheme_ref = _ilu.module_from_spec(_sr_spec); _sr_spec.loader.exec_module(_scheme_ref)


def get_scheme(scheme_id=None, customer=None, status=None):
    """查方案。**方案是「一件事」的单位** —— 客户这次想做的这件衣服。

    为什么是**资源型**工具(跟表走,和 get_order 一个形状),不是动词工具:
    2026-09-18 业务定的规矩 —— MCP 跟表走跟 API 走,场景该由 Skill 编排。
    所以这里只有「取」,没有 lock_scheme / convert_to_order 这类动作;
    状态流转是 scheme.status 的值变化,走已有的写接口。

    ⚠️ **代号一律翻成中文再返回。** 库里存的是 XZ04 / MT02 / KF02,
    直接给模型看,它要么念代号给客户听,要么自己猜一个名字 ——
    **而猜错了看起来和猜对了一模一样**。翻不出来的保留原代号并标出来,
    不是静默丢掉:查不到本身就是要报的事。
    """
    if not (scheme_id or customer or status):
        return {"error": "要么给方案号,要么给客户号/姓名,要么给状态"}

    # 代号翻中文的口径在 knowledge/scheme_ref.py,**工具只取数不定口径**。
    # 我第一版把它写在这里了 —— 而 seed.py 的注释早就写着「见 knowledge/scheme_ref.py」,
    # 只是那个文件一直没建。**先 grep 一遍它是不是已经有人安排过**,这个项目撞过七次。
    def 展开(r):
        with _c() as c:
            return _scheme_ref.展开(c, r)

    if scheme_id:
        rs = _rows("SELECT * FROM scheme WHERE id=?", scheme_id)
        if not rs:
            return {"error": f"没有方案 {scheme_id}"}
        d = 展开(rs[0])
        cu = _rows("SELECT name FROM customer WHERE id=?", rs[0]["customer_id"])
        d["客户"] = cu[0]["name"] if cu else None
        # 同一客户还有哪些方案 —— **并行是常态**,不告诉模型它就会以为只有这一条
        兄弟 = _rows("SELECT id,name,status FROM scheme WHERE customer_id=? AND id<>?"
                    " ORDER BY updated DESC", rs[0]["customer_id"], scheme_id)
        d["该客户的其他方案"] = 兄弟
        # 这条方案下过哪些单。**空列表和「还没下单」是同一件事,要说出来** ——
        # 不返回这个字段的话,「查过了没有」和「根本没查」在答复里长得一样。
        单 = _rows("SELECT id,kind,status,amount,created FROM ordr WHERE scheme_id=?"
                  " ORDER BY created", scheme_id)
        d["由这条方案下的订单"] = 单
        if not 单:
            d["下单情况"] = ("这条方案还没有下过单。"
                          + ("**已锁定不等于已下单** —— 客户拍过板,单还没开。"
                             if d["状态"] == "已锁定" else ""))
        # **把「已锁定几条」直接算好摆出来。** 业务 2026-09-18 定了可以多条同时锁,
        # 于是「锁定那条」不再是一个能消歧的说法。让模型自己去数兄弟列表里有几条锁定,
        # 是把一个**它很容易数错、而且数错了看不出来**的活交给它。
        锁 = _scheme_ref.已锁定的(兄弟) + \
            ([{"id": d["方案号"], "name": d["名称"], "status": "已锁定"}]
             if d["状态"] == "已锁定" else [])
        d["该客户已锁定的方案数"] = len(锁)
        if len(锁) > 1:
            d["⚠️消歧提示"] = (f"该客户有 {len(锁)} 条方案同时处于已锁定"
                             f"({'、'.join(x['id'] for x in 锁)})。"
                             "**「锁定那条」指代不明,必须问清方案号再推进。**")
        d["note"] = ("方案是「一件事」的单位:报价、下单、试衣都挂在它上面。"
                     "同一客户可以并行多条,**且可以多条同时处于已锁定** —— "
                     "推进前先确认说的是哪一个方案号,不要靠状态猜。")
        return d

    sql = "SELECT * FROM scheme WHERE 1=1"
    args = []
    if customer:
        cs = _rows("SELECT id,name FROM customer WHERE id=? OR name=?", customer, customer)
        if not cs:
            return {"error": f"没有客户「{customer}」"}
        sql += " AND customer_id=?"
        args.append(cs[0]["id"])
    if status:
        sql += " AND status=?"
        args.append(status)
    rs = _rows(sql + " ORDER BY updated DESC", *args)
    return {"hit": len(rs), "schemes": [展开(r) for r in rs],
            "note": "要看某一条的明细,拿方案号再调一次。"
                    "**同一客户并行多条是常态** —— 客户说「那个方案」时先问清是哪一条。"}


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
    import leadtime
    return leadtime.记住(("工艺名",), lambda: {r["code"]: r["name"] for r in _rows("SELECT code,name FROM craft")})


def kb_pattern(xz=None):
    """版型库 —— 一个形制有哪些版型、分几个裁片、出哪些码。

    ⚠️ **入参既收形制名,也收版型编码和版型名。**
    原来只收形制名,于是顾问按日常说法问「PT04 马面裙推荐什么码」「PT06 立领长衫
    M 码要多久」,工具一律回「知识库里没有叫「PT04」的形制」——
    **而 PT04 就在这张表里,是「明制马面裙·标准」**。

    这不是模型的问题:实测它老老实实说「查不到这个编码,请确认」并要求补参数,
    **没有编一个** —— 那正是对的行为。问题是
    **工具的入参维度和人说话的维度对不上**:
    顾问嘴里说的是版型编码和变体名(「阔褶马面裙」),工具只吃形制名。
    一套工具评测里有 4 条栽在这上面。
    """
    q="SELECT * FROM pattern"; a=()
    if xz:
        # ① 先当版型编码 / 版型全名试(PT04、明制马面裙·标准)
        直 = _rows("SELECT * FROM pattern WHERE code=? OR name=?", xz, xz)
        # ② 再试变体名倒过来写:「阔褶马面裙」↔「明制马面裙·阔褶」
        if not 直:
            直 = [r for r in _rows("SELECT * FROM pattern")
                  if "·" in (r["name"] or "")
                  and r["name"].split("·")[-1] in xz
                  and any(w in xz for w in r["name"].split("·")[0][-3:])]
        if 直:
            # 命中具体版型时,**仍然把同形制的都列出来** ——
            # 问 PT04 的人多半也想知道同形制还有别的版型可挑(PT05 阔褶)。
            # 只返回一条会让「有没有别的选择」这个问题永远问不出来。
            q += " WHERE xz=?"; a = (直[0]["xz"],)
        else:
            k,e=_resolve(xz,"形制")
            if e:
                # 报错也要说清**这个工具认什么** —— 否则模型只能反复猜入参。
                return {"error": e + "(这个工具也认**版型编码**如 PT04 和"
                                    "**版型全名**如「明制马面裙·标准」)"}
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
        # **版本要说出来。** 一个版号不带改动记录等于没有,所以连最近那条一起给。
        _rv=_rows("SELECT version,changed_at,what,why FROM pattern_rev "
                  "WHERE pattern=? ORDER BY version DESC LIMIT 1", r["code"])
        r["版本"]=f"v{r.get('version') or 1}" + (
            f"({_rv[0]['what']},{_rv[0]['changed_at']}:{_rv[0]['why']})" if _rv else "")
    return {"hit":len(rs),"rows":rs,
            "note":"difficulty=改版难度。「极高」的(马面裙)腰围错了等于重做,不能放缝头改。"}


def kb_size(pattern, size=None):
    """某版型的成衣尺码表。**这是成衣尺寸,不是人体尺寸**,两者之差是放松量。"""
    p=_rows("SELECT * FROM pattern WHERE code=? OR name=?",pattern,pattern)
    if not p: return {"error":f"没有版型「{pattern}」,可先用 kb_pattern 查这个形制有哪些版型"}
    p=p[0]
    rs=_rows("SELECT size,item,value,caveat FROM size_spec WHERE pattern=?",p["code"])
    if size: rs=[r for r in rs if r["size"]==size]
    if not rs:
        return {"error":f"{p['name']} 没有 {size} 码,只有 {p['sizes']}",
                "note":"尺码不存在不是缺货,是这个版型裁不出来。"}
    out, 参考 = {}, {}
    for r in rs:
        # **推得出不等于作数** —— 但这个标记**不许贴在值上**。
        #
        # 第一版把它写成 `"72.0(仅供参考)"`,当场炸了两处:
        # 钉死的锚点对不上(手抄 72.0 vs 算出 '72.0(仅供参考)'),
        # 以及 kb_fit 拿它去减放松量时 `str - float` 直接 TypeError。
        # **这正是这个项目反复撞的「一列承载两件事」** —— 我一边在别处修它,
        # 一边在这儿又犯了一次:一个数值字段同时装了数值和它的可信度。
        # 现在数值还是数值,标记单独一栏。
        out.setdefault(r["size"],{})[r["item"]] = r["value"]
        if r["caveat"]: 参考[r["item"]] = r["caveat"]
    res = {"版型":p["name"],"尺码表":out,"量体模版":p["tpl"],
           "note":"成衣尺寸。推荐尺码要拿客户量体值比对后由版师定,系统只给建议。"}
    if 参考:
        res["⚠️ 这几项推得出但不作数"] = sorted(参考)
        res["为什么"] = 参考
        res["note"] += ("  ⚠️ 上面「推得出但不作数」列出的项**不能直接拿去下单或裁剪**,"
                        "必须由版师按实际尺寸重新处理 —— "
                        "**在尺码表里它们和别的数长得一模一样**,所以单独列一栏。")
    return res


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
    # ⚠️ **量体按着装人取,取最近一次,只认顾问亲自量的**(2026-09-22 修)。
    # 原来按 customer_id 取:一条档案下 2–4 个人的量体混进一个字典、后写的覆盖先写的 ——
    # 孩子会拿到妈妈的腰围;方式也是按客户 LIMIT 1 取的。161 个客户名下有多人量体。
    # 体型特征那一半早就按着装人取了(见下),量体这一半当时漏了。
    _wid0 = wearer or (_rows("""SELECT a.self_wearer_id w FROM customer k
                               JOIN account a ON a.id=k.account_id WHERE k.id=?""", cu["id"])
                       or [{}])[0].get("w")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","knowledge"))
    ms, mth, _依据 = _以哪次为准(_wid0)          # 最近一整次亲自量的,缺项不拼(业务 09-22)
    mth = mth or "到店"
    if not ms:
        return {"error":f"{cu['name']}" + (f"(着装人 {_wid0})" if _wid0 else "") + " 没有顾问亲自量的量体记录",
                "档位":"需补量",
                "note":"没量过体就不能推荐尺码,**不要按身高体重猜**;远程量的尺寸业务不认(09-22)。"}
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
    _sx = (_rows("SELECT gender FROM wearer WHERE id=?", _wid) or [{}])[0].get("gender") if _wid else None
    out=fitting.recommend(ms,p["code"],p["sizes"].split(","),specs,p["xz"],mth,fs,sex=_sx)
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
#   ③ 量体记录全不全、是不是顾问亲自量的 —— 尺寸类判责全看这个
#   ④ 交付时有没有书面告知过 —— 特性类判责全看这个
def _量体完整性(customer_id, 已有):
    """这位客户的量体**全不全** —— 门槛在 `knowledge/liability.py`,这里只取数。

    判责的返修判定表里「记录完整 / 记录不全」是两条不同的结论
    (一条客方收费改,一条我方免费改),而工具原来只给一个「条数」——
    **3 项和 23 项在返回里长得一模一样**,模型没有任何办法判断全不全。

    ⚠️ 我第一版自己发明了口径(拿量体模板的必填项数比),算出来是「完整」,
    **而真值说不全** —— 差点让工具带着模型自信地答错。
    真正的门槛(4 项)当时只活在 `seed.py` 的真值生成里,
    知识库和口径模块一个字都没有。**现在它只有一个来源。**
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import liability as _lb
    齐, 话 = _lb.量体完整(已有)
    return {"完整性": 话}


def _以哪次为准(wearer_id, order_item_id=None):
    """这个人(这一件)以哪一次量体为准 —— 口径在 knowledge/measure.以哪次为准(业务 09-22)。
    返回 ({量体项: 值}, 方式, 一句话);没有就 ({}, None, 为什么)。

    **给了订单行:只认绑在这一件上的下单量体,没有就是没有** —— 业务 09-22:「每一个订单都需要有
    绑定的下单量体数据」。不退回用别的场次:退回去的话,一张违规的单会拿着别的尺寸照常判档、照常过闸,
    **违规就被盖住了**(第一版这么写过,当场被业务纠正)。
    没给订单行(还没下单,顾问拿某个人先看看穿什么码):取最近一整次亲自量的,**缺项不从更早的场次拼**。
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge"))
    import measure as _ms
    记 = [dict(着装人=r["wearer_id"], 时间=r["measured_at"], 量体人=r["measured_by_no"], 方式=r["method"],
              项=r["name"], 值=r["value"], 订单行=r["order_item_id"])
         for r in _rows("SELECT r.wearer_id, r.measured_at, r.measured_by_no, r.method, r.value, "
                        "r.order_item_id, i.name FROM measure_rec r JOIN measure_item i ON i.code=r.item "
                        "WHERE r.wearer_id=?", wearer_id)] if wearer_id else []
    场 = _ms.场次(记)
    s, 话 = (_ms.以哪次为准(场, 订单行=order_item_id) if order_item_id is not None
             else _ms.以哪次为准(场))
    return ((s or {}).get("值们") or {}), (s or {}).get("方式"), 话


def _亲量档位(wearer_id, pattern_code, order_item_id=None):
    """这个人穿这个版型,按**顾问亲自量**的尺寸判出的档位(标准码 / 调号 / 全定制)。

    只认到店 / 上门量体 —— 业务 09-22 明令不准远程量体,远程量的尺寸不算数
    (和接待的定义同一个口径,`knowledge/linkage.亲自服务的量体方式`)。
    每个量体项取最近一次。**量不到就返回 None**,不按身高体重猜 ——
    「不知道体型标不标准」和「体型标准」是两件事,前者要让必试判成「判不了」。
    """
    if not wearer_id or not pattern_code:
        return None
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge"))
    import fitting
    值们, 方式, _ = _以哪次为准(wearer_id, order_item_id)
    if not 值们:
        return None
    ms = {k: (v, 方式) for k, v in 值们.items()}
    p = _rows("SELECT code,xz,sizes FROM pattern WHERE code=?", pattern_code)
    if not p or not p[0]["sizes"]:
        return None
    p = p[0]
    specs = {}
    for r in _rows("SELECT size,item,value FROM size_spec WHERE pattern=?", p["code"]):
        specs.setdefault(r["size"], {})[r["item"]] = r["value"]
    fs = [r["feature"] for r in _rows("SELECT feature FROM body_feature WHERE wearer_id=?", wearer_id)]
    mth = next(iter(ms.values()))[1]
    _sx = (_rows("SELECT gender FROM wearer WHERE id=?", wearer_id) or [{}])[0].get("gender")
    out = fitting.recommend({k: v[0] for k, v in ms.items()}, p["code"], p["sizes"].split(","),
                            specs, p["xz"], mth, fs, sex=_sx)
    return out.get("档位")


def _白坯试衣(order_id, item_name, order_status, item_id=None, 假设未开裁=False):
    """这一单的白坯试衣现场。**只给事实,不给判责结论。**

    ⚠️ 和量体记录那一栏是同一条教训:**不许只给一个数让人自己去推。**
    「有没有试衣记录」这一个事实推不出判责方向 —— 还要知道
    **这一单该不该试**、**开没开裁**。三样缺一样,结论就可能反。

    这里把三样一起算完,归到 `muslin.状态` 的某一种;
    **算不出来就说算不出**,不给一个看起来很确定的默认值。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import muslin as _mu
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import seed_fitting as _sf

    # 有行号就按行号取 —— 一家人订同款时同名商品不止一件,按名字取会串到别人那件上
    it = (_rows("SELECT i.id, i.name, i.spu, i.wearer_id, p.pattern FROM ordr_item i "
                "LEFT JOIN product p ON p.spu=i.spu WHERE i.id=? AND i.order_id=?", item_id, order_id)
          if item_id else
          _rows("SELECT i.id, i.name, i.spu, i.wearer_id, p.pattern FROM ordr_item i "
                "LEFT JOIN product p ON p.spu=i.spu "
                "WHERE i.order_id=? AND i.name=?", order_id, item_name))
    if not it:
        return {"note": "订单行里没有同名商品,查不到试衣记录"}
    item = it[0]

    # 该不该试 —— **跑真的工期推算**,不在这儿另判一遍
    import leadtime as _ltb
    mt = _ltb.记住(("带幅宽的料",), lambda: {r["name"]: r["code"] for r in
          _rows("SELECT code,name FROM material WHERE width_cm IS NOT NULL")})
    kfm = _ltb.记住(("工艺名→码",), lambda: {r["name"]: r["code"] for r in _rows("SELECT code,name FROM craft")})
    ch = _rows("SELECT kind,material,part FROM item_part_choice WHERE item_id=? "
               "ORDER BY id", item["id"])
    ks = sorted({kfm[x["material"]] for x in ch
                 if x["kind"] == "工艺" and x["material"] in kfm})
    fab = [x for x in ch if x["kind"] == "面料" and x["material"] in mt]
    主 = next((x for x in fab if x["part"] in ("主身", "整件")), fab[0] if fab else None)
    if not item["pattern"] or not 主:
        该 = None
        why = ("**判不了该不该试衣** —— 这个商品没挂版型"
               if not item["pattern"] else "**判不了** —— 没有带幅宽的主料")
    else:
        scope = "整幅" if any(w in (item["name"] or "")
                              for w in ("重工", "婚服", "满工")) else "局部"
        # 按**下单那天**算(用户 2026-09-19 定)—— 不传的话工期推算取今天,
        # 判责现场里的「凭什么」会一天变一天,跌破门槛那天结论就翻
        _od = (_rows("SELECT created FROM ordr WHERE id=?", order_id) or [{}])[0].get("created")
        该, why = _mu.按配置判(item["pattern"], mt[主["material"]], ks, scope,
                               None, _names(), on=_od)

    # ── 业务 09-22:三类必试(重工 / 全定制 / 婚服),新规挂在「开裁」这个动作上 ──
    重工, 重工_为什么 = 该, why
    开裁 = False if 假设未开裁 else _sf.开裁了吗(order_status)
    系统开裁 = bool((_rows("SELECT cut_at FROM ordr WHERE id=?", order_id) or [{}])[0].get("cut_at"))
    新规 = _mu.适用新规(开裁, 系统开裁)
    档位 = _亲量档位(item["wearer_id"], item["pattern"], item["id"]) if 新规 else None
    _场合 = _rows("SELECT scene FROM product_scene WHERE spu=?", item["spu"]) if item["spu"] else []
    婚服 = (any(r["scene"] == "SC-OCC-03" for r in _场合) if _场合 else None) if 新规 else None
    if 新规 is None:
        该, why, 中 = None, "**判不了** —— 不知道这一单开没开裁,也就不知道按新规还是旧规判", []
    else:
        该, why, 中 = _mu.必试(重工, 档位, 婚服, 新规)
        if 重工_为什么 and "重工" in 中: why += ";重工:" + 重工_为什么

    recs = _rows("SELECT * FROM fitting WHERE item_id=? ORDER BY round", item["id"])
    签 = any(r["signed"] for r in recs)
    st = _mu.归档(该, 开裁, bool(recs), 签)

    return _nz({
        "该不该做白坯试衣": 该, "凭什么": why,
        "属于哪几类": 中 or None,
        "按哪套规矩": (None if 新规 is None else
                       "新规(业务 09-22:重工 / 全定制 / 婚服)" if 新规 else
                       "旧规(系统接管开裁之前就裁了,只看重工 —— 不追溯)"),
        "量体判出的档位": 档位,
        "是不是婚服": 婚服,
        "订单开没开裁": 开裁,
        "有几条试衣记录": len(recs),
        "客户签字了吗": 签 if recs else None,
        "记录": [{"第几轮": r["round"], "时间": r["ts"], "陪同工号": r["advisor_no"],
                  "门店": r["shop"], "改了哪几处": r["adjust"],
                  "签了吗": bool(r["signed"]), "签字时间": r["signed_at"],
                  "备注": r["note"]} for r in recs] or None,
        "归到哪一档": st,
        "这一档是什么": (_mu.状态.get(st) or (None, None))[0],
        "在判责里算什么": (_mu.状态.get(st) or (None, None))[1],
        "⚠️": ("**算不出这一单归哪一档** —— 缺的是上面那几项里的某一个。"
                "**不许挑一个默认值**:默认「没开裁」会把「该试没试」判成不判责,"
                "默认「开裁了」会把「还没到时候」判成我方 —— 两个方向都错。"
                if st is None else None),
    })



def fitting_queue(order=None):
    """**白坯试衣看板** —— 哪些单该试、试了没有、签没签字。

    知识库那句话分量很重:**白坯试衣是重工订单唯一的后悔药** ——
    云锦缂丝一旦裁下去就没有回头路,几百块的白坯能挡掉几万块的返工。

    而在这个工具之前系统只做到了一半:**工期里算了 7–12 天,
    而试没试、谁陪的、客户签没签,一条记录都没有** ——
    没有入口的能力等于没做。

    ## ⚠️ 最要紧的那一档是「该试没试」

    它不是「还没轮到」,是**已经开裁了而没有任何试衣记录** ——
    白坯试衣排在裁剪之前,裁下去就没有回头路。
    这一档在售后判尺寸争议时**往我方判**(09-养护与售后.md 第五节新加的一行):
    流程没走到,是我们的。

    ## ⚠️ 签字这一栏是这里最值钱的东西

    行业里试穿确认是**责任转移点**。而我们判尺寸争议原来**只有量体记录一张底牌**。

        量体记录说的是  「**我们**量得对不对」
        试衣签字说的是  「**他本人穿过**并且认可了」

    **「没有试衣记录」和「有记录但没签字」不是一回事** —— 前者是流程没走,
    后者是流程走了确认没拿到,判责方向相反。所以两者分开报,
    **不许拿「查不到记录」当成「没签字」。**

    ## 「哪些款该试」:业务 2026-09-22 定了三类,重工的门槛也确认了

    必试 = 重工 / 全定制 / 婚服,命中任一即必试(`muslin.范围_依据`)。
    知识库原本只写了「重工款强烈建议做」,没有数;工期推算推出来的两个门槛
    (装饰最慢 25 天 / 单项工艺起步 12 天)业务 09-22 确认不改(`muslin.门槛_依据`)。
    每一条结论都带着「凭什么该试」出去。

    order: 不传给全部;传订单号只看那一单。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import muslin as _mu
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import seed_fitting as _sf

    w, a = "", []
    if order:
        w = " AND o.id=?"; a = [order]
    rs = _rows("SELECT i.id,i.order_id,i.name,i.wearer_id,o.status,o.advisor_no,"
               "  o.shop,c.name cname,o.customer_id "
               "FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
               "LEFT JOIN customer c ON c.id=o.customer_id "
               "WHERE o.kind='定制品订单'" + w + " ORDER BY i.id", *a)
    摊 = {}
    # 三千多件逐件推工期 —— 放进「一次查看」的记忆范围:相容矩阵、工时表、现货、
    # 师傅名单、某一天的队在这一次里不会变,不必每件重查(结果一样,只是不重复查)
    import leadtime as _ltb
    with _ltb.批量():
        _fs = [(r, _白坯试衣(r["order_id"], r["name"], r["status"])) for r in rs]
    for r, f in _fs:
        st = f.get("归到哪一档")
        if st == "不必试" and not order:
            continue          # 不必试的不进看板 —— 一张 47 行的清单等于没排队
        摊.setdefault(st or "**算不出**", []).append(_nz({
            "订单": r["order_id"], "订单行": r["id"],
            "客户": f"{r['customer_id']} {r['cname'] or ''}".strip(),
            "着装人": r["wearer_id"], "商品": r["name"],
            "订单状态": r["status"], "顾问工号": r["advisor_no"], "门店": r["shop"],
            "凭什么该试": f.get("凭什么"),
            "试衣记录": f.get("记录"),
            "客户签字了吗": f.get("客户签字了吗"),
            "在判责里算什么": f.get("在判责里算什么"),
            "⚠️": f.get("⚠️"),
        }))

    次序 = ["该试没试", "已试未签", "还没到时候", "已试已签", "不必试", "**算不出**"]
    out = {"看的是": "定制品订单行(白坯是给**某一个人**试的,所以挂在行上不挂在单上)"}
    for k in 次序:
        if k not in 摊: continue
        out[k] = {
            "件数": len(摊[k]),
            "是什么": (_mu.状态.get(k) or ("算不出这一单归哪一档",))[0],
            "在判责里算什么": (_mu.状态.get(k) or (None, None))[1],
            "明细": 摊[k],
        }
    # **已经越过线的,单独点出来。** 「该试没试」这一档里凡是已经开裁的,
    # 都是**已经发生的违规**,不是待办。
    越线 = [x for x in 摊.get("该试没试", [])]
    if 越线:
        out["⚠️ 已经越过这道线的"] = {
            "件数": len(越线),
            "是什么": "**该做白坯试衣而没做,却已经开裁了。** "
                      "白坯排在裁剪之前 —— 裁下去就没有回头路,"
                      "这几单的后悔药已经吃不到了",
            "现在能做什么": "**不是补一场试衣**(已经裁了),"
                            "而是知道这几单出尺寸争议时**责任在我方** —— "
                            "流程没走到。提前准备,别等客户找上门",
            "明细": [x["商品"] for x in 越线],
        }
    # ── 开裁那道闸(业务 09-22 起真的会拦)────────────────────────────
    # 原来这里写的是「这道闸现在拦不住任何东西」—— 系统里没有写口会把订单推进裁剪。
    # 现在开裁走 start_cutting / 后台改状态,两条路都过订单状态机上的同一道闸。
    if not order:
        import fitting_write as _fw
        待 = {"可以": [], "不可以": [], "判不了": []}
        for o in _rows("SELECT id FROM ordr WHERE kind='定制品订单' AND status='待生产' ORDER BY id"):
            g, w, _ = _fw.过闸(o["id"])
            待.setdefault(g, []).append({"订单": o["id"], "为什么": w})
        out["待开裁的单"] = {
            "是什么": "「待生产」的定制单现在能不能开裁 —— **该试的要试过、而且客户签了字**才许裁(业务 09-22)",
            **{k: {"单数": len(v), "明细": v} for k, v in 待.items() if v},
        }
    out["开裁这道闸"] = (
        "**会拦**:定制单从「待生产」进「生产中」(开裁),不管从后台点还是由版师在助手里开,"
        "都过订单状态机上的同一道闸 —— 单里有一件该试没试、试了没签字、或判不了该不该试而又没试过,**整单不许裁**(判不了的先试一轮并签字就能裁)。"
        "裁剪按单排,裁一半等于把没过闸那件也推上裁床。")
    out["哪些款必须试"] = _mu.范围_依据
    out["⚠️ 重工那条的门槛"] = _mu.门槛_依据
    out["⚠️ 「没记录」和「没签字」不是一回事"] = (
        "**该试没试**是流程没走(判**我方**),**已试未签**是流程走了确认没拿到"
        "(回落到量体记录)。两者在一张表上都是「没有签字」,而判责方向相反 —— "
        "**不许拿「查不到记录」当成「没签字」。**")
    out["这个工具不改任何东西"] = (
        "约试衣、催签字是**人的动作**。这里只说「该跟哪一单、凭什么」。"
        "登记试衣和签字用 record_fitting(顾问 / 店长),开裁用 start_cutting(版师)。")
    return _nz(out)



def channel_compare(include_sim=False):
    """**多渠道表现对比** —— 四个下单渠道各自什么样。

    ## ⚠️ 先说结论:**这个库上的渠道差异不能当结论**

    这不是「数据少」,是**这一列是怎么填上去的**:

        种子的 46 单    `SRC[i % 4]` —— **按订单序号轮着发的**
        模拟的 3826 单  按固定权重独立抽,和金额、状态、客户**全无关**

    两种机制都让 `source` 和别的一切**统计独立**,所以任何
    「哪个渠道客单价高 / 退款多 / 付款慢」的差异,**都是这两个机制的产物**。

    而它和真的渠道差异**在表上长得一模一样** —— 都是一张四行的表,
    每行一个百分比。所以这里做的不是「不给数」,是**把数和它的来路一起给**。

    ## ⚠️ 还有一件顺带查出来的:**渠道和活动 100% 共线**

    `seed.py` 里 `SRC[i % 4]` 和 `ACT[i % 4]` 同一个周期,
    于是每个渠道恰好对应一个活动,**一一对应没有例外**。
    「这个渠道转化好」和「这个活动效果好」在这批数据上**分不开** ——
    而 `activity_roi` 已经在用活动归因算 ROI,它的警告里**没有这一条**。

    ## 客服代下单**不是渠道**,单独列

    它是人工补录,背后可能是电话、微信、门店。

    include_sim: 默认 False(只看种子的 46 单)。
                 传 True 会把 3826 单模拟订单也算进来 —— **它们的渠道是抽出来的**,
                 算进来只会让那张表看起来更可信,而不会更真。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import channel as _ch

    模拟 = {r["order_id"] for r in _rows("SELECT order_id FROM sim_batch")}
    rs = _rows("SELECT id, source, kind, status, payable, received, refund_status, "
               "  created, paid_at, activity, customer_id FROM ordr")
    用 = [r for r in rs if include_sim or r["id"] not in 模拟]

    摊 = {}
    for r in 用:
        摊.setdefault(r["source"] or "(没记渠道)", []).append(r)

    售后 = {r["order_id"]: r["n"] for r in _rows(
        "SELECT order_id, COUNT(*) n FROM maintain GROUP BY order_id")}

    渠道, 另列 = {}, {}
    for 名, os_ in sorted(摊.items(), key=lambda x: -len(x[1])):
        n = len(os_)
        待付 = sum(1 for x in os_ if x["status"] == "待付款")
        退 = sum(1 for x in os_ if (x["refund_status"] or "") in ("已退款", "退款中"))
        修 = sum(1 for x in os_ if x["id"] in 售后)
        实收 = sum(x["received"] or 0 for x in os_)
        成 = [x for x in os_ if x["status"] not in ("待确认", "待付款", "取消")]
        d = _nz({
            "单量": n,
            "客单价(按实收)": (round(实收 / len(成), 2) if 成 else None),
            "实收合计": round(实收, 2),
            "待付款": _ch.比率(待付, n, "下单")[0],
            "退款(含退款中)": _ch.比率(退, n, "下单")[0],
            "有售后工单": _ch.比率(修, n, "下单")[0],
            "绑的活动": sorted({x["activity"] or "(无)" for x in os_}),
        })
        能, 为什么 = _ch.可比吗(名)
        if 能: 渠道[名] = d
        else:
            d["⚠️ 这不是一个渠道"] = 为什么
            另列[名] = d

    out = {
        "算的是": (f"全部 {len(用)} 单(**含 {len(模拟)} 单模拟订单**)"
                   if include_sim else
                   f"{len(用)} 单 —— **只算种子订单**,"
                   f"{len(模拟)} 单模拟订单的渠道是抽出来的,算进来只会让表看起来更可信"),
        "⚠️ 这张表不能用来比渠道": _ch.不能比_为什么,
        "⚠️ 渠道和活动 100% 共线": _ch.共线,
        "四个渠道": 渠道,
        "不算渠道的": 另列,
    }
    # **把共线现算一遍,不是背一句话。** 种子数据一改,这里就该跟着变。
    对 = {}
    for 名, os_ in 摊.items():
        acts = {x["activity"] or "(无)" for x in os_}
        对[名] = sorted(acts)
    一对一 = all(len(v) == 1 for v in 对.values()) and \
             len({v[0] for v in 对.values()}) == len(对)
    out["共线现算的结果"] = {
        "每个渠道绑了哪些活动": 对,
        "是不是一一对应": 一对一,
        "note": ("**是** —— 按渠道分组和按活动分组在这批数据上是同一件事"
                 if 一对一 else "不是一一对应了,共线那条警告可以重新评估"),
    }
    out["不给渠道排名"] = (
        "**11 单的样本排不出名次,排了会被当成结论去调预算。** "
        "每个比率后面都带着「一单值多少个百分点」—— "
        "看的人自己就知道该不该拿它去动钱。")
    out["怎么才能真的比"] = (
        "要让渠道这一列**携带信息**:渠道得由客户**实际从哪儿下单**决定,"
        "而不是按序号轮发或按权重抽。在那之前,这里给的是**事实(单量、实收)**,"
        "**不是渠道的表现**。")
    return _nz(out)


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
             "报修时间": m["created"], "门店": m["shop"], "顾问工号": m["advisor_no"],
             "订单": (o[0] if o else {"error": "订单查不到"}),
             "这件的配置": (dict(形制=it[0]["xz"], 可选面料=it[0]["mt_opts"],
                            可选工艺=it[0]["kf_opts"], 商品备注=it[0]["remark"])
                        if it else {"note": "订单行里没有同名商品"}),
             # ⚠️ **只给「条数 3」判不出全不全,而判责恰恰看这个。**
             #
             # 2026-09-15 真跑逮到:MW73031 的真值是「尺寸偏差 · **记录不全** ·
             # 我方免费改」,而模型读到「量体记录:3 条、到店量」之后写的是
             # 「**数据完整且可信度高**」,顺理成章判成了**客方收费改** ——
             # 责任判反、钱收反。
             #
             # **这不是模型的错,也不是判据的错:它没有办法知道该有多少项。**
             # 3 项和 23 项在返回里长得一模一样(都只是一个数),
             # 而「全不全」要拿它和量体模板的必填项数去比。
             #
             # 和这个项目反复撞的是同一件事:**不许让人(或模型)自己去推**,
             # 该算的在工具里算完 —— 「空表和量过但都是 0 在纸上长得一样」
             # 说的也是这件事。
             "量体记录": _nz({"条数": n_item, "方式": [x["method"] for x in ms],
                       # 业务 09-22:不准远程量体,判责表里「远程 → 按合同分担」那一行也删了。
                       # 这里只报「是不是都是顾问亲自量的」—— 不是的话那条记录本身就违规,要人看
                       "都是顾问亲自量的": all(x["method"] in ("到店", "上门") for x in ms) if ms else None,
                       **_量体完整性(m["customer_id"], n_item)}),
             # 代码要翻成名称。原来只给「N1,N2,N3」,模型看得见却看不懂 ——
             # 它会说「需要人工查出 N1-N6 具体条目」,**而那正是它该自己拿到的东西**。
             "交付告知签收": (dict(已告知条目=[NOTICE_NAME.get(x, x)
                                          for x in (nt[0]["items"] or "").split(",") if x],
                             签收时间=nt[0]["signed_at"], 渠道=nt[0]["channel"]) if nt else None),
             # ⚠️ **判尺寸争议的第二张底牌,而且比量体记录硬。**
             # 量体记录说的是「我们量得对不对」,试衣签字说的是
             # 「**他本人穿过并且认可了**」—— 两句话在判责时的分量完全不同。
             "白坯试衣": _白坯试衣(m["order_id"], m["item"],
                                   (o[0]["status"] if o else None)),
             "该客户历史维修次数": hist}
        out.append(d)
    return {"hit": len(rows), "工单": out,
            "怎么用": "**这里只有事实,没有结论。** 判责要另外调 kb_tables 取「售后争议判定」,"
                    "并对照 09-养护与售后.md 第五节的返修判定表。"
                    "「交付告知签收」为 null 表示**没有书面告知记录** —— "
                    "特性类问题(起球/色差/掉色/勾丝)在这种情况下按「我方,让步处理」;"
                    "尺寸类问题**先看「白坯试衣」**:已试已签 → 客方收费改"
                    "(他本人穿过并认可了,**压过量体记录**);"
                    "该试没试 → **我方**免费改(流程没走到)。"
                    "试了没签或不必试,才回落到「量体记录」完不完整。"
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
    r_lo = fitting.recommend(lo_ms, pr["code"], szs, specs, pr["xz"], sex=w.get("gender"))
    r_hi = fitting.recommend(hi_ms, pr["code"], szs, specs, pr["xz"], sex=w.get("gender"))
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
 {"name":"get_tasks","description":"**查任务 —— 四种问法一个口。** 不给参数=我自己的活;给 task_id=某一条的详情;scope=\"待分配\"=待分配池(客户约了时间但没自动派出去的,每条带 agent 的人选建议和依据,**建议不是决定**,要店长确认);scope=\"团队\" 或给 assignee=按人看(带每人在办件数、最近到期、在办明细,还会列出手上没活的人)。\n\n**范围跟身份走,隔离在查询层不在界面**:顾问只看得到派给自己的(知道单号也看不到别人的),店长看本店,总部看全部。⚠️ **「你看不到他的活」和「他没有活」是两回事**,返回里会分开说。status 可选只看某一档(有效/完结/取消/无效)。",
  "input_schema":{"type":"object","properties":{
    "task_id":{"type":"string","description":"任务号,如 SC7029。给了就只看这一条。"},
    "scope":{"type":"string","enum":["我的","团队","待分配"],"description":"看谁的。不传=我的。"},
    "assignee":{"type":"string","description":"只看这一个人,工号或姓名(等同 scope=团队 再筛一个人)"},
    "status":{"type":"string","description":"只看这一档:有效 / 完结 / 取消 / 无效。不传看全部。"}},
   "required":[]}},
 {"name":"get_member","description":"**查会员分层 —— 等级和生命周期一次给全。** 给 customer(客户号或姓名)返回这个人的**会员等级档**(凭什么、离下一档还差多少)和**生命周期档**(八档中的哪一档、凭什么、有没有人工覆盖);给 lifecycle 列这一档里有哪些人;再加 rank=true 按 **RFM 三维**排出「先联系谁」。\n\n⚠️ **这是两套各答各的判定,不要互相推导**:会员等级看的是滚动 12 个月的实付或完成单数(满足任一条即可,**不是「且」**,依据取客户档案上的 12 个月快照字段、**不是去订单表现算**);生命周期看的是多久没来,判定口径**全是含端边界**(第 90 天算活跃、第 91 天进休眠、第 181 天进潜在流失、第 366 天才算流失;实付满 15000 **含端**计高价值)—— 这些不要心算,直接看返回值。\n\n多条命中时**必须把命中列表一起说出来**,只报结论运营无从判断算得对不对。出现「提醒」字段说明库里存的值和按今天重算的不一致,照实说,不要替它选一个。**RFM 是相对分,只在返回的这一批人内部可比** —— 排序解决的是「先打给谁」,不是「谁更值钱」。**这是判定和排序,不是预测。**\n\n⚠️ 按姓名查会重名 —— 命中不止一个时不给等级明细,会明说要客户号。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号(如 C10001)或姓名。姓名可能重名,重名时要改用客户号。"},
    "lifecycle":{"type":"string","description":"按档位筛,如「潜在流失」「休眠」"},
    "rank":{"type":"boolean","description":"true=在这一档里按 RFM 排出先联系谁"},
    "limit":{"type":"number","description":"排序时返回前几名,默认 10,最多 40"}},
   "required":[]}},
 {"name":"task_types","description":"九种任务类型的**数据规范**:每种挂哪张单据(客户号/订单号/维保单号/售后单号/不挂)、谁能派、完成时要不要传现场照。**起草派任务之前先调这个** —— 类型决定了要填什么,填错会被拒。",
  "input_schema":{"type":"object","properties":{},"required":[]}},
 {"name":"week_grid","description":"**日程占用的格子**(读的是任务/预约,**不是排班表**):一周里每个顾问哪天什么时段已经被占了、哪几天一条日程都没有、待分配还有几条。**排班之前必须先看这个** —— 不看就排,排出来的东西和正常任务长得一模一样,直到那天两个人同时约在一个时段。只有店长看得到。\n\n⚠️ **问「这一周的班排了没有」「某某那天上不上班」要用 `on_shift`**,不是这个。这里的「没有日程」只表示那个时段没被占,**不表示他那天上班**。",
  "input_schema":{"type":"object","properties":{
    "start":{"type":"string","description":"从哪天起,YYYY-MM-DD,默认今天"},
    "days":{"type":"number","description":"看几天,默认 7,最多 14"}},"required":[]}},
 {"name":"conversion_rate","description":"**成交率:两个数,一个是业务要的,一个不是。**\n\n⚠️ 2026-09-22 之前这个工具说「算不了」—— **那是因为「接待」被定义错了**(只认「预约到店」,全库 7 条)。业务说清之后(**到店/上门量体、白坯试衣、预约到店都是接待;远程量体不算**),**3403/3542 张定制单追得到是哪次接待**。\n\n**① 按接待人算** —— 每次接待后面有没有跟着成交。算得出,**但业务明说过这样算不对**:「成交率是长期一对一营销的结果,不能因为某一次就算在某人身上」;而且四成以上的单(返回里有现算的比例),**接待人和订单顾问不是同一个人**。\n\n**② 按归因算(业务要的那个)** —— 按影响力分成汇总。已按业务 09-22 定的口径给出:**按客户算不按接待次数**(门店 = 成交客户 ÷ 亲自接待过的客户;顾问 = W 型份额之和 ÷ 他亲自接待过的客户),多张单算 1 个成交客户,**暂不分周期**。\n\n⚠️ **两个数都像成交率,而它们回答的是不同的问题** —— 报数必须说清是哪一个。⚠️ **绝对不要自己拿订单数除一除编一个率**。⚠️ 现在的挂接是**下单前最近一次**接待,「取最近一次」是**默认不是业务拍的**。",
  "input_schema":{"type":"object","properties":{
    "shop":{"type":"string","description":"只看某个门店。不给就按你的身份来(店长看本店,总部看全部)。"},
    "mode":{"type":"string","enum":["同期","队列"],"description":"统计周期口径。不给=不分周期(全部数据)。**长周期生意看队列**:同期会把「这个月接待、下个月下单」的客户算成没成交。"},
    "month":{"type":"string","description":"哪个月,YYYY-MM。给了 mode 才用;不给就是当月(可能还没满 N 天,率偏低)。"},
    "n_days":{"type":"number","description":"队列口径的 N:首次接待后几天内下单算成交。默认 90(覆盖约八成成交);可改 30/60。"}},"required":[]}},
 {"name":"customer_history","description":"**这个客户之前谁接触过、做了什么** —— 五张表(预约/跟进/日程/量体/下单)里的触点连成按时间排的一条线。顾问打电话之前看一眼:上次是谁跟的、聊到哪儿了。\n\n⚠️ **一次量体是一次触点,不是十几次。** 一个客户一次量体会产生十几行记录(每个测量项一条),已按「日期+经手人」去重,备注里写着「14 个测量项」——**别说成接触了 14 次**。不去重的话量体会以 10:1 淹没其他触点,**而「他主要是来量体的」只是因为那张表行数最多**。\n\n⚠️ **线上没有不等于没联系过** —— 只包含系统里有记录的接触,微信/电话没录进来的不在里面。\n\n⚠️ 「没有触点」有三种,下一步不同:`NO_TOUCH` 库里一条过程都没有(**不是没人管他**,是没记过)· `ONLY_ORDER` 只有下单这一个点 · `NO_OWNER` 有触点但都没记经手人(**数据缺口**)。**重名时只给候选不给明细** —— 给错人的接触史比不给更糟。范围跟身份走:顾问看自己名下的,店长看本店。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号(如 C10001)或姓名。姓名重名时会要你改用客户号。"},
    "limit":{"type":"number","description":"最多列几个触点,默认 30,最多 100"}},"required":["customer"]}},
 {"name":"deal_credit","description":"**这一单谁有贡献,贡献多少。** 给 order 看某一单(还会按 W 型归因算一次影响力);给 staff 看某个人;都不给看范围内的概况。\n\n⚠️ **要害:两种分成不是一回事,不许相加也不许互相比较。**\n· **收入分成** 加起来**必须 100** —— 那是分钱(算提成)\n· **影响力分成** **可以超过 100** —— 那是记贡献,不是零和的\n一单可以同时是「收入:张三 70 + 李四 30」和「影响力:张三 100 + 李四 60 + 店长 40」。两者在库里长得一模一样(都是「某人 + 某个百分比」),所以**分两栏返回**。看到影响力加起来 200% **不要当成错误**。\n\n⚠️ **这不是成交率** —— 这一版只记录不算率(算率还缺「订单追得到哪次接待」,3511 张定制单标着「未接入」)。\n\n⚠️ 三种来源要分开:`人工填` / `规则算` / `算法算`(算法算必带版本)——三者算出来都是一个百分比,**可信度完全不同**。W 型的 30/30/30/10 是**行业惯例不是算出来的**,而且现在的旅程是造的,**证明的是算法跑得通,不是算得准**。\n\n⚠️ 「算不出来」不是「没有贡献」;「一条记录都没有」是**没记过归因**,不是没人有贡献。",
  "input_schema":{"type":"object","properties":{
    "order":{"type":"string","description":"订单号。给了会附带按 W 型归因算一次。"},
    "staff":{"type":"string","description":"工号或姓名,只看这个人的。"},
    "limit":{"type":"number","description":"每一栏最多几条,默认 20,最多 100"}},"required":[]}},
 {"name":"on_shift","description":"**谁哪天上班,以及那个人那个时候能不能接。** 读的是**排班表**(上不上班、什么班次),**不是日程占用** —— 谁那个时段被任务占了要用 `week_grid`。 给 staff(+date,+at 如 \"15:00\")= 看这一个人;只给 date 或什么都不给 = 看本店未来几天的排班概况。\n\n⚠️ 这个工具存在的全部理由,是把「不上班」的**五种**分开,它们下一步完全不同:\n· `UNSCHEDULED` **还没排** —— **这不是「他没空」,是「排班还没出来」**,要去催店长排。⚠️ 别因为下周没记录就说「下周大家都有空」,那份推荐看起来完全正常而它建立在「还没排」上。\n· `DRAFT` 草稿 —— 店长还在调,**按它派的单会挂在错的人身上**,要等发布。\n· `OFF` 已发布休息 —— 确实没空。\n· `LEAVE` 请假 —— 没空,**而且已经派给他的单要重新分配**(请假是盖掉排班,排班表上他仍写着上班)。\n· `OUT_OF_SHIFT` **他这天上班但不在这个点**(早班的人接不了晚上的预约)。\n\n返回值里「还没排班的日子」单列出来 —— 混在「不上班」里店长就看不见自己漏排了哪几天。范围跟身份走:店长/顾问看本店,总部看全部;**「员工表里没这个人」和「不在你的门店」都不是「他没空」**。",
  "input_schema":{"type":"object","properties":{
    "staff":{"type":"string","description":"工号或姓名。给了就只看这一个人。"},
    "date":{"type":"string","description":"哪天,YYYY-MM-DD。不给就是今天。"},
    "at":{"type":"string","description":"几点,如 15:00。给了会判这个时段落不落在他的班里。"},
    "days":{"type":"number","description":"概况看几天,默认 7,最多 14"}},"required":[]}},
 {"name":"revive_list","description":"**这些客户现在该不该联系,以及联系他说什么。**\n\n⚠️ **问「通话里有没有生意」用 `call_opportunity`**(那个看的是逐字稿里客户提过什么偏好);这个看的是**该不该打这通电话**(由头/硬门槛)。两个问题都像「哪些客户值得跟进」,**给的是完全不同的两份名单**。 回答的是两件事:**为什么是他,为什么是现在**。\n\n⚠️ **没有由头的不进名单 —— 哪怕他闲置 300 天。** 名单里每条都带「为什么是现在」(往年同期 / 生日临近 / 上一单该回访 / 维保没办完 / 断了自己的节奏),**报名单时必须带上** —— 只给一串名字,顾问打过去不知道说什么。\n\n⚠️ **「断了节奏」是相对他自己的**:一个每季度买一次的人闲置 200 天是异常,一个一年买一次的人闲置 200 天很正常。别说成「超过 X 天没买」。\n\n⚠️ 返回值里「这几个门槛是拍的」那一栏**是真的没有依据**(断节奏倍数/刚联系过/刚下过单),等真实数据校准 —— 别替它编理由。\n\n没进名单的五种,下一步完全不同:`JUST_BOUGHT` 刚买完 · `AFTERSALE` **先办售后** · `RECENT_CONTACT` 防骚扰 · `NO_REASON` 买过但眼下没由头 · `NOT_YET` **从没下过单**(归拉新不归促活)。**「该联系 0 个」不等于这些客户都不行。** 范围跟身份走:顾问看自己名下的,店长看本店,总部看全部。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号或姓名。给了就只看这一个人,并单列他的判断。"},
    "limit":{"type":"number","description":"名单最多返回几条,默认 20,最多 100"}},"required":[]}},
 {"name":"call_opportunity","description":"**这些通话里有没有值得跟进的生意。** 它看的是**通话逐字稿**里客户提过什么偏好。\n\n⚠️ **问「今天该联系谁」用 `revive_list`**(那个回答的是「为什么是他、为什么是现在」);这个回答的是「他说过想要什么,而店里现在有」。两个问题都像「哪些客户值得跟进」,**给的是完全不同的两份名单**。 两种用法,代价差一个数量级:\n\n**不给 customer** = 清单,**只跑规则层**(免费、确定)。它只看「客户说了什么偏好 + 店里有没有对得上的货」,**分不出「想要」和「随口一提」** —— 实测 24 条里误报 7 条(约三成)。⚠️ **返回的是候选不是结论**,报给顾问时必须把这句话一起说,否则他会照着一个个打过去。\n\n**给了 customer**(客户号或姓名)= 这一个人深判,规则层 + 模型层,模型只回答一个问题:真想要还是随口一提。⚠️ **不要对整张清单逐个深判** —— 每条都是一次模型调用。\n\n⚠️ 「有逐字稿的通话」是 0,意思是这个范围里**根本没有录音**,不是「查过了没商机」——**「没有商机」和「没东西可判」是两回事**。\n\n四种「不是商机」的下一步不同:`NO_DIMENSION` 这通电话没话可跟进 · `NO_STOCK` 想要的现在给不了 · `JUST_MENTIONED` 随口一提 · `NO_CUSTOMER_LINE` **逐字稿里说话人没标**(数据问题,不是这个客户没戏)。范围跟身份走:顾问看自己名下的,店长看本店,总部看全部。",
  "input_schema":{"type":"object","properties":{
    "customer":{"type":"string","description":"客户号(如 C10001)或姓名。给了就深判这一个人(会调模型);不给就列候选清单。"},
    "limit":{"type":"number","description":"清单最多返回几条,默认 20,最多 100"}},"required":[]}},
 {"name":"ownerless_list","description":"**谁实际上没人管** —— **顾问问「我名下的客户有没有问题」也用这个**(会自动只看他名下那一份)。 —— 注意「有归属顾问」和「有人管」不是一回事:一个停用的顾问名下还挂着客户,顾问字段**非空**,任何按「有没有顾问」筛的写法都查不出他们。\n\n返回五种码,**分开的全部理由是下一步不同**:`LEFT` 顾问已停用(店长重新指人)· `NONE` 还没归属(等分配)· `CROSS_SHOP` 顾问不在客户门店(转店还是转人)· `NO_SUCH` 工号员工表里没有(**数据要修**)· `NO_SHOP` 档案没填门店,**判不了跨没跨店**(数据要修)。⚠️ 后两种是数据问题不是业务问题,**对着它们建议「重新分配客户」是答错了**。⚠️ `NO_SHOP` 是「判不了」,不是「确认过没问题」。\n\n`NEVER_TOUCHED` 归属人在系统里**没有一条经手记录**(⚠️ 这**不等于他没跟过** —— 微信电话没录进来就查不到;下一步是去确认是哪一种)。\n\n**只查不改** —— 改不改归属是店长的动作,这个工具不写任何一行。范围跟身份走:店长看本店,总部看全部,**顾问看自己名下那一份**(⚠️ 按定义他名下不会有 NONE/NO_SUCH/LEFT,所以**多半是空的**;空清单只说明「查了哪几类」那几类没有,**不等于一切正常**)(返回值里写着「看的范围」是哪一段,**合计 0 不等于全店都有人管**)。code 可只看某一种码。另附「待确立归属」:到店接待完成、但归属还没确立的人数(业务定:归属在首次到店接待完成时确立)。",
  "input_schema":{"type":"object","properties":{
    "code":{"type":"string","description":"只看某一种或几种码,逗号分隔,如 LEFT,NO_SUCH。不给看全部。"},
    "limit":{"type":"number","description":"清单最多返回几条,默认 50,最多 200"}},"required":[]}},
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
 {"name":"stock_alert","description":"**库存预警** —— 哪些 SKU 要断了、哪些**看着有货其实一件都发不出**(在手有货但全被订单占用)、哪些在压货。805 个 SKU 全有库存数而在这之前没有任何工具会说「这个要断了」。⚠️ **在手 ≠ 可用**:客户问「还有货吗」要的是 **可用 = 在手 − 已占用**,只报在手会让客户白等。⚠️ **它给不出可售天数,而且会直说给不出**:全库有销量的只有 71/797 个 SKU、每个只有一笔、订单只跨 18 天,**一笔销售画不出速度** —— 这时候任何一个可售天数都是编的,而编出来的数会让采购按它去补货。**不许把「算不出」说成 0 天,也不许退回成「低于 N 件就预警」假装算得出。** ⚠️ **这个工具不补货**:补多少、什么时候补是采购的决定。⚠️ 只看成品 SKU,**面料库存是另一摊**。","input_schema":{"type":"object","properties":{"scope":{"type":"string","description":"发不出 / 断货 / 快没了 / 卖不动;不传则全给"}}}},
 {"name":"fitting_queue","description":"**白坯试衣看板** —— 哪些定制单该做白坯试衣、试了没有、客户签没签字。白坯试衣是**定制单唯一的后悔药**(云锦缂丝裁下去没有回头路,几百块的白坯挡掉几万块返工),而在这个工具之前系统只做到一半:工期里算了 7–12 天,试没试、谁陪的、签没签一条记录都没有。⚠️ **最要紧的一档是「该试没试」**:不是还没轮到,是**已经开裁了而没有任何试衣记录** —— 这一档在判尺寸争议时**往我方判**(流程没走到,是我们的)。⚠️ **「没有试衣记录」和「有记录但没签字」不是一回事**:前者是流程没走(我方),后者是流程走了确认没拿到(回落到量体记录),**判责方向相反** —— 不许拿「查不到记录」当成「没签字」。⚠️ **签字是责任转移点**:量体记录说的是「我们量得对不对」,试衣签字说的是「**他本人穿过并且认可了**」,后者压过前者、也压过「远程量体」。**哪些款必须试(业务 09-22 定)**:重工、全定制(顾问亲自量的尺寸判出)、婚服(商品挂了「婚礼婚服」场合标签)三类命中任一即必试;没命中但有一类判不了 → 判不了,**不当成不必试**;重工的两个门槛(装饰工序最慢 ≥25 天 / 单项工艺起步 ≥12 天)业务 09-22 确认。**开裁这道闸会拦**:该试的要试过、而且客户签了字,整单才许开裁 —— 看板里「待开裁的单」列出每张待生产单能不能裁、卡在哪。⚠️ **这个工具不改任何东西**:约试衣、催签字是人的动作。","input_schema":{"type":"object","properties":{"order":{"type":"string","description":"订单号;不传则看全部"}}}},
 {"name":"record_pickup","description":"**交付签收的三个动作(真的写进去)**:action=「到店代收」(工厂发到店,顾问代收,只认已发货的定制单)/「取件方式」(mode=到店取 或 转寄;**转寄要 tracking_no**,业务 09-22:顾问先邀约顾客到店取,实在来不了才转寄)/「不合身」(顾客试了不合身 → **不算签收**,订单状态不动,转返修;issue 写清哪里不合身)。只能动本店的单,经手人就是你自己(不收工号)。「不合身」时 matches_record(成衣和订单留存数据对得上吗)、other_defect(有没有别的瑕疵)、our_fault(查出来是「导购」或「打版」的问题)都是**查出来的事实,不知道就别填** —— 返回的判责建议(对得上且无别的瑕疵 → 顾客承担、收费;导购 / 打版问题 → 企业承担、免费)**不是结论,由售后负责人确认**。⚠️ 动手前先跟用户对一遍单号和动作。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"action":{"type":"string","enum":["到店代收","取件方式","不合身"]},"mode":{"type":"string","enum":["到店取","转寄"]},"tracking_no":{"type":"string"},"issue":{"type":"string"},"matches_record":{"type":"boolean"},"other_defect":{"type":"boolean"},"our_fault":{"type":"string","enum":["导购","打版"]}},"required":["order_id","action"]}},
 {"name":"verify_fit_code","description":"**核验顾客给的 6 位码 = 签收(真的写进去)**:通过后订单「已发货 → 待完成」。业务 09-22:**签收 = 顾客确认试穿合身** —— 顾客在手机上点「试穿合身」拿到 6 位码交给导购,导购输入核验;到店取和转寄都走这个码。**码只能是用户这句话里说出来的那一个,不许编、不许猜、不许「先填个试试」** —— 输错会记次数,5 次作废。完成之后要**顾客自己确认**,顾客一直不确认,签收满 15 天顾问才能写理由追认(ratify_complete)。⚠️ 动手前先跟用户对一遍单号和码。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"code":{"type":"string","description":"顾客给的 6 位码,原样照抄用户说的"}},"required":["order_id","code"]}},
 {"name":"ratify_complete","description":"**顾问追认完成(真的写进去)**:签收满 15 天顾客还没在手机上确认完成,顾问写理由(比如「已电话联系,顾客表示没问题」)把订单「待完成 → 完成」。**不满 15 天不行、没写理由不行** —— 业务 09-22:完成由顾客确认,追认是兜底,不是替顾客点。⚠️ 动手前先跟用户确认理由是真的联系过。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"reason":{"type":"string"}},"required":["order_id","reason"]}},
 {"name":"open_order","description":"**开一张定制单(真的写进去)**,停在「待确认」—— 还没生效。顾问或店长用,只给本店客户开。items 每一件写 spu(或 sku)、wearer_id(**给谁做,必填** —— 下单量体量的必须是穿这件的人)、qty。只开定制单,标品流程不变。开完的**下一步**:给每一件量下单量体并绑到这一件(record_measure 带 order_id + item),再 confirm_order。⚠️ 动手前先跟用户对一遍:哪位客户、哪几件、每件给谁做。","input_schema":{"type":"object","properties":{"customer_id":{"type":"string"},"items":{"type":"array","items":{"type":"object","properties":{"spu":{"type":"string"},"sku":{"type":"string"},"wearer_id":{"type":"string"},"qty":{"type":"integer"}}}}},"required":["customer_id","items"]}},
 {"name":"confirm_order","description":"**确认下单(真的写进去)**:待确认 → 待审核。业务 09-22:**定制单确认即已付款**,不走「待付款」。**逐件过闸**:每一件都要有绑在它上面的、开单之后量的、够做这件衣服的下单量体;有一件不过就整单拒绝,返回里列出是哪几件、缺什么(没有下单量体 / 早于开单 / 缺哪几项 / 着装人没定)。被拒了**不要换个说法再试**,把缺什么告诉用户,去量、去绑。⚠️ 动手前先跟用户确认单号。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"]}},
 {"name":"record_measure","description":"**登记一次量体(真的写进去)**。顾问或店长用,只能录本店客户的着装人;量体人就是你自己(不收工号)。wearer_id 是着装人编号(W 开头,客户号 C 开头的不是)。values 形如 {\"胸围\":86,\"腰围\":68}。method 只认「到店 / 上门」—— 业务 09-22 **不准远程量体**。inner(内搭:无/薄/厚/单层内衣)、shoe(鞋:赤足/平底/高跟)、breath(呼吸:平静呼气)**三个都必填,缺一件就等于没量**。数值超出人体合理范围会被拒(多半是单位或小数点录错),**不替你改**。**下单量体**:签单时按这件衣服重新量,给 order_id + item(订单行号或商品名),这一件就以这次为准;业务 09-22 定了**没有下单量体就不许下单**。要先有「身体数据」同意(未满 14 岁还要监护人同意)。⚠️ 动手前先跟用户对一遍:给谁量的、哪几项多少、到店还是上门、三个条件、是不是某一件的下单量体 —— 尺寸录错,衣服就按错的做。","input_schema":{"type":"object","properties":{"wearer_id":{"type":"string"},"values":{"type":"object","description":"{量体项名: 数值}"},"method":{"type":"string","enum":["到店","上门"]},"inner":{"type":"string"},"shoe":{"type":"string"},"breath":{"type":"string"},"order_id":{"type":"string","description":"只在下单量体时给"},"item":{"type":"string","description":"订单行号或商品名,只在下单量体时给"}},"required":["wearer_id","values","method","inner","shoe","breath"]}},
 {"name":"record_fitting","description":"**登记一轮白坯试衣(真的写进去)**。顾问或店长用,只能登记本店订单;陪同人就是你自己(不收工号)。item 填订单行号或商品名(一张单里同名多件时必须给行号)。adjust 写这一轮改了哪几处(没改写「无需调整」,不许空);signed 客户当场签字就填 true。**补签**:客户后来才签,给 round(已有的轮次号)并 signed=true;**签字不能撤销**。⚠️ 客户没签字之前,这一件所在的整张单**不许开裁**(业务 09-22)。⚠️ **动手前先跟用户对一遍**哪张单、哪一件、改了什么、签没签 —— 签字是责任转移点,记错了等于给门店一张不存在的底牌。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"},"item":{"type":"string","description":"订单行号或商品名"},"adjust":{"type":"string","description":"这一轮改了哪几处;没改写「无需调整」"},"signed":{"type":"boolean","description":"客户签字了吗"},"round":{"type":"integer","description":"只在补签时给:要补签的那一轮"},"note":{"type":"string"}},"required":["order_id","item"]}},
 {"name":"start_cutting","description":"**开裁(真的写进去)**:把一张定制单从「待生产」推进到「生产中」。只有版师能用。**要先过白坯试衣这道闸**(业务 09-22):单里每一件该试的都试过、而且客户签了字,才许开裁;有一件没过就整单拒绝,返回里列出是哪几件、缺什么(没试 / 没签 / 判不了该不该试又没试过 —— 判不了的先试一轮并签字就能裁)。被拒时**不要换个说法再试**,把卡在哪告诉用户,让顾问去约试衣或补签。⚠️ **开裁不可逆**,动手前先跟用户确认单号。","input_schema":{"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"]}},
 {"name":"channel_compare","description":"**多渠道表现对比** —— 四个下单渠道(微信小程序/官网/门店 Pad/客服代下单)各自的单量、客单价、待付款占比、退款率、售后率。⚠️ **这张表不能用来比渠道,而它和真的渠道对比长得一模一样。** 原因不是数据少,是这一列怎么填上去的:种子订单是**按订单序号轮着发的**(`SRC[i % 4]`),模拟订单是**按固定权重独立抽的**,两种机制都让渠道和金额、状态、客户**统计独立** —— 任何渠道间差异都是这两个机制的产物,**不是渠道的表现**。⚠️ **渠道和活动 100% 共线**:每个渠道恰好对应一个活动,一一对应没有例外,所以「这个渠道转化好」和「这个活动效果好」在这批数据上**分不开**(这条同时影响 activity_roi)。⚠️ **客服代下单不是一个渠道**,是人工补录,背后可能是电话/微信/门店 —— 当渠道分析会得出假结论。⚠️ **不给渠道排名**:11 单的样本排不出名次,排了会被当成结论去调预算;每个比率后面都带着「**一单值多少个百分点**」。","input_schema":{"type":"object","properties":{"include_sim":{"type":"boolean","description":"是否把 3826 单模拟订单也算进来。默认 false —— 它们的渠道是抽出来的,算进来只会让表看起来更可信,不会更真"}}}},
 {"name":"recovery_queue","description":"**未成交挽回清单** —— 下了单没付钱的、约了没来的,各压着多少钱、压了多久、该按什么顺序跟。不传参数给两摊都要;传「待付款」或「预约」只要一摊。⚠️ **这个工具只出清单,不发任何东西** —— 发短信/微信/打电话是对外动作,按不按、怎么按是人的决定。⚠️ **它不划「超时」那条线**:定制品和标品的合理等待期本来就不一样,编一个数会把正常的单子算成流失。只排序不划线,按**金额 × 停留天数**排。⚠️ **三种未成行不许混成一类**:已取消是客户主动说了不来、爽约是没说就没来(**先确认人没事**)、已过期是系统判的(客户自己可能都不知道有这条预约)。","input_schema":{"type":"object","properties":{"kind":{"type":"string","description":"待付款 或 预约;不传则两摊都给"}}}},
 {"name":"pattern_queue","description":"**版师的排队看板 —— 「今天该我核什么」。**不用传任何参数。把版师手上的活一次列全:裁片用料占比的进度(并按**影响面**排出先核哪几个 —— 挂多少商品、多少订单行已经按这个数备料)、推档有疑点的版型、「推得出但不作数」的尺码格子、配置页上架了却没有版型的定制品。**每一摊都报「总数 / 已完成 / 还剩」** —— 一摊显示 0 的时候要说得出是「做完了」还是「一条都没扫到」。版师进来第一句话就该调它。\n\n**传 pattern(认编码 PT06 和全名)就转看那一个版型的裁片用料占比明细**,每条带来源:`估算`(机器估的没人看过)/ `复核`(规则核过但这个数没人核过)/ `版师`(人核过数)/ `BOM`(明写的用量)——**三种可信度不许混为一谈**。还给出占比折合多少米:**版师判断的是米数不是百分比**,「袖片 15.7%」看不出对不对,「袖片 0.63 米」一眼就知道。","input_schema":{"type":"object","properties":{"pattern":{"type":"string","description":"版型编码或全名。不传=看板(今天该核什么);传了=那一版的裁片明细。"}}}},
 {"name":"grading_audit","description":"**推档自检 —— 把「要核 1237 个数」压成「要核 12 条档差」。**尺码表全部是推出来的(基码值 + 档差 × 尺码序号),版师真正该核的只有基码和那 12 条档差。不传 pattern 给全局(扫了多少、哪几个版型有疑点、档差规则是什么);传 pattern 给这一个版型的逐部位明细:实际档差 / 规则档差 / **覆盖范围**(这个版型能做多大的人)/ 量纲体检 / 哪几项「推得出但不作数」。**判据是定义性的,不是阈值** —— 相邻码的差必须处处相等且等于档差表,不一致就是真的有一格不对。","input_schema":{"type":"object","properties":{"pattern":{"type":"string","description":"版型编码或全名,不传则给全局"}}}},
 {"name":"set_piece_ratio","description":"**改一片的用料占比,并标成「版师核过」**。改完这一片就锁住,不会再被估算覆盖;同版型其余**没核过**的片按比例重新归一,让总和回到 1,而**已核过的片不动** —— 人核过的数不许被自动调。ratio 填 0–1 之间的小数(0.25 = 25%)。**why 要写** —— 不写的话下次有人问「这个数为什么是这样」就查不到了。","input_schema":{"type":"object","properties":{"pattern":{"type":"string"},"piece":{"type":"string","description":"裁片名,如「袖片」"},"ratio":{"type":"number"},"why":{"type":"string","description":"为什么改成这个数"}},"required":["pattern","piece","ratio"]}},
 {"name":"my_workorders","description":"**我手上的工单**。工匠看自己的,工坊管事看本坊,总部运营看全部 —— 范围跟身份走。带**在制上限**和当前在制数:接不接得下一件,这两个数说了算,不用猜(上限是工艺约束 —— 手工活同时开太多件每件都慢,而且染色、绣线批次会串味)。逾期的排在最前。status 可选,写「在制/待开工/已完成」等。",
  "input_schema":{"type":"object","properties":{
    "status":{"type":"string","description":"只看某个状态的,不给就是全部"}},"required":[]}},
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
 {"name":"get_scheme","description":"查方案。**方案是「一件事」的单位** —— 客户这次想做的这件衣服(形制/面料/工艺/颜色/配饰/版型都挂在它上面),有自己的生命周期:草稿 → 已保存 → 已锁定 → 已失效。三种问法:给 scheme_id 返回单条明细(并附上该客户的其他方案);给 customer(客户号或姓名)列这个客户的全部方案;给 status 按状态筛。⚠️ **同一个客户并行多条方案是常态** —— 客户或顾问说「那个方案」「刚才那套」时,**先调这个工具看清楚有几条,不要默认只有一条就往下推进**。推进(报价、下单、排产)之前必须确认说的是哪一个方案号。",
  "input_schema":{"type":"object","properties":{
    "scheme_id":{"type":"string","description":"方案号,形如 SC2601"},
    "customer":{"type":"string","description":"客户号或姓名。不知道方案号时先用这个列清单。"},
    "status":{"type":"string","description":"按状态筛:草稿 / 已保存 / 已锁定 / 已失效"}},"required":[]}},
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
 {"name":"get_maintain","description":"查售后维修工单的**现场**。客户说「衣服起球了 / 开线了 / 尺寸不对」时用。返回这件是什么(形制/可选面料/可选工艺)、客户报的问题、**量体记录全不全、是不是顾问亲自量的**(业务 09-22 不准远程量体)、**交付时有没有书面告知签收**、以及该客户历史维修次数。\n\n**这个工具只给事实,不给判责结论** —— 判定表要另外调 kb_tables 取「售后争议判定」,并对照 09-养护与售后.md 第五节。两条关键判据:①「交付告知签收」为 null 表示**没有书面告知记录**,特性类问题(起球/色差/掉色/勾丝)在这种情况下按「我方,让步处理」,已告知则「无责,解释 + 提供保养服务」;② 尺寸类问题看量体记录完不完整、是不是**远程**量的(远程按合同分担)。\n\n**结论必须由人确认后执行,你只出草稿。** 不要直接对客户承诺免费返修或赔付金额。",
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


# ═══════════════════════════════════════════════════════════════════════
# 合并后的查询口 —— **一个业务对象一个工具,靠参数分,不靠工具名分**
#
# 2026-09-19。官方那条判据:**「如果一个人类工程师都说不准某个场景该用
# 哪个工具,AI 不可能做得更好」**。下面这三处原来是 9 个工具,而它们
# 各自族内查的是同一摊数据、只是换了筛选条件 —— 那不是「工具多」,
# 是**一件事被切成了好几件**。
#
# ⚠️ **合并的是「agent 看得见的工具面」,不是删实现。** 下面每一支都
# 原样调用老函数:权限判定、脱敏、边界口径全在那些函数里,已经被
# 门禁和咬合验过。重写一份等于把验过的东西作废重来。
# ═══════════════════════════════════════════════════════════════════════

def get_tasks(task_id=None, scope=None, assignee=None, status=None):
    """查任务。**四种问法一个口**,给不同参数即可。

    task_id → 某一条的详情;scope="待分配" → 待分配池(店长可见);
    scope="团队" 或给 assignee → 按人看;都不给 → 我自己的。

    范围隔离没有因为合并而变松:每一支仍然走原来那个函数,
    而所有读任务的地方都走 `tasks.visible_scope` 一处判定。
    """
    if task_id:
        return get_task(task_id)
    s = (scope or "").strip()
    if s in ("待分配", "待分配池", "pool"):
        return dispatch_pool()
    if s in ("团队", "全店", "team") or assignee:
        return team_tasks(assignee=assignee, status=status)
    return my_tasks(status=status)


def get_member(customer=None, lifecycle=None, rank=False, limit=None):
    """查会员分层。**会员等级和生命周期是两套判定**,问一个客户时一次给全 ——
    原来要调两次才拼得出「这个客户值不值得跟」。

    customer → 这个人的等级档 + 生命周期档;
    lifecycle → 这一档里有哪些人;再加 rank=true → 这一档里先联系谁(RFM 排序)。
    """
    if lifecycle and rank:
        return get_member_priority(lifecycle=lifecycle, limit=limit)
    if customer:
        lc = get_lifecycle(customer=customer)
        if lc.get("error"):
            return lc
        rs = lc.get("rows") or []
        # ⚠️ **命中一个和命中多个必须长得不一样。**
        #    按姓名查是会重名的(库里「蔡青梧」就命中 3 个)。
        #    默默取第一个的话,等级明细会安静地挂在错的人身上,
        #    而**挂对了和挂错了在返回里一模一样**。
        if len(rs) != 1:
            return {**lc, "note": (lc.get("note") or "") +
                    f" ⚠️ 这个说法命中 {len(rs)} 个客户,没法给等级明细 —— 给客户号(如 C10001)才行。"}
        return {"客户": rs[0].get("name"), "客户号": rs[0].get("id"),
                "会员等级": member_level(rs[0]["id"]),
                "生命周期": rs[0],
                "note": "会员等级看的是滚动 12 个月的钱和单数;生命周期看的是多久没来。"
                        "**两套判定各答各的**,不要互相推导。"}
    if lifecycle:
        return get_lifecycle(lifecycle=lifecycle)
    return {"error": "要么给 customer(某个人),要么给 lifecycle(某一档)"}


def _pattern_queue(pattern=None):
    """版师看板。不给参数 = 今天该核什么(整摊);给 pattern = 那个版型的裁片明细。

    原来是两个工具,而看板里本来就汇总了裁片核对的进度 ——
    **「看进度」和「看某一版的明细」是同一件事的两个粒度**,不是两件事。
    """
    if pattern:
        return piece_ratios(pattern=pattern)
    return pattern_queue()


def conversion_rate(shop=None, mode=None, month=None, n_days=None):
    """**成交率:两种算法,一个是你要的,一个不是。**

    ⚠️ 2026-09-22 之前这个工具说「算不了」—— **那是因为「接待」被定义错了**:
    只认「预约到店」(全库 7 条)。业务说清之后(量体/白坯试衣/预约到店都是接待),
    **3542 张定制单 100% 追得到是哪次接待**。
    (**09-22 再定:远程量体不算** —— 排除之后是 3403/3542,139 张没有合规接待)

    但**追得到接待 ≠ 知道谁促成的**,所以有两个数:

        按接待人算    每次接待后面有没有跟着成交。**算得出,但业务说过这样算不对**
                      ——「成交率是长期一对一营销的结果,不能因为某一次就算在某人身上」
        按归因算      按影响力分成汇总。**这才是业务要的**,但现在只覆盖一小部分单

    两个数都像成交率,**而它们回答的是不同的问题**。
    """
    me = whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import sqlite3 as _sq
    口径 = _口径_linkage()
    con = _sq.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        店 = shop or (None if me.get("role") == "总部运营" else (me.get("shop") or None))
        范围 = "全部门店" if not 店 else f"{店}"
        w, a = ["o.kind='定制品订单'"], []
        if 店:
            w.append("cu.shop = ?"); a.append(店)
        单 = [dict(r) for r in con.execute(
            "SELECT o.id, o.appt_src, o.recept_by, o.advisor_no FROM ordr o "
            "JOIN customer cu ON cu.id=o.customer_id WHERE " + " AND ".join(w), a)]
        # 按接待人:他做的接待场次里,有几次后面跟了成交
        按人 = {}
        for r in con.execute("""
            with 场 as (select distinct customer_id, substr(measured_at,1,10) d,
                               measured_by_no who from measure_rec
                        union select distinct o.customer_id, substr(f.ts,1,10), f.advisor_no
                              from fitting f join ordr o on o.id=f.order_id),
                 成 as (select recept_by who, recept_at d, customer_id
                        from ordr where appt_src='接待关联')
            select s.name, s.shop, count(*) 接待, sum(case when exists(
                     select 1 from 成 where 成.who=场.who and 成.d=场.d
                       and 成.customer_id=场.customer_id) then 1 else 0 end) 成交
            from 场 join staff s on s.no=场.who
            where s.role='顾问' group by 场.who order by 接待 desc"""):
            if 店 and r["shop"] != 店:
                continue
            按人[r["name"]] = {"接待次数": r["接待"], "促成": r["成交"],
                              "按接待人算的率": f"{100*r['成交']/r['接待']:.0f}%" if r["接待"] else "—"}
        有归因 = con.execute(
            "SELECT count(DISTINCT order_id) FROM deal_credit WHERE method='W型归因 v1·全量'"
        ).fetchone()[0]
        # ── 业务 09-22 拍板的口径:**按客户算,不按接待次数** ──────────
        # 亲自接待 = 到店/上门量体、白坯试衣、预约到店(远程量体不算)
        接 = {}   # 工号 → {客户}
        for who, cid in con.execute("""
            select measured_by_no, customer_id from measure_rec where method in ('到店','上门')
            union select f.advisor_no, o.customer_id from fitting f join ordr o on o.id=f.order_id
            union select advisor_no, customer_id from appointment where status in ('已到店','已完成')"""):
            if who and cid:
                接.setdefault(who, set()).add(cid)
        各单 = {}  # 客户 → [{工号: pct}] 每张定制单一条
        for oid, cid, who, pct in con.execute("""
            select d.order_id, o.customer_id, d.staff_no, d.pct from deal_credit d
            join ordr o on o.id=d.order_id where d.method='W型归因 v1·全量'"""):
            各单.setdefault(cid, {}).setdefault(oid, {})[who] = pct
        人 = {r["no"]: (r["name"], r["shop"]) for r in con.execute(
            "select no, name, shop from staff where role='顾问'")}
        # 分期口径要带日期的明细
        接待列表 = [(c, d, w) for c, d, w in con.execute("""
            select customer_id, substr(measured_at,1,10), measured_by_no from measure_rec
              where method in ('到店','上门')
            union select o.customer_id, substr(f.ts,1,10), f.advisor_no
              from fitting f join ordr o on o.id=f.order_id
            union select customer_id, substr(start_ts,1,10), advisor_no from appointment
              where status in ('已到店','已完成')""") if c and d and w]
        _单 = {}
        for oid, cid, d, who, pct in con.execute("""
            select d.order_id, o.customer_id, substr(o.created,1,10), d.staff_no, d.pct
            from deal_credit d join ordr o on o.id=d.order_id
            where d.method='W型归因 v1·全量'"""):
            _单.setdefault(oid, [cid, d, {}])[2][who] = pct
        订单列表 = [tuple(v) for v in _单.values()]
    finally:
        con.close()
    if not 单:
        return {"看的范围": 范围, "能不能算": False,
                "为什么": "这个范围里一张定制单都没有 —— **没东西可算,不是率低**"}
    可用 = sum(1 for o in 单 if o["appt_src"] == "接待关联")
    import attribution as _归
    份额 = {cid: _归.客户份额(list(d.values())) for cid, d in 各单.items()}
    店客户 = set().union(*[v for k, v in 接.items()
                          if k in 人 and (not 店 or 人[k][1] == 店)]) if 接 else set()
    店率, 店说 = _归.成交率(sum(1 for c in 店客户 if 份额.get(c)), len(店客户))
    顾问率 = {}
    for no, cs in 接.items():
        if no not in 人 or (店 and 人[no][1] != 店):
            continue
        # **分子只算他亲自接待过的那些客户** —— 否则一个只打过一通跟进电话的客户
        # 也进了分子而不在分母里,率就可能超过 100%(上一版就栽在这)。
        x = sum(份额.get(c, {}).get(no, 0) for c in cs)
        r, _ = _归.成交率(x, len(cs))
        顾问率[人[no][0]] = {"亲自接待过的客户": len(cs), "归因成交份额": round(x, 1),
                          "成交率": f"{100*r:.0f}%" if r is not None else "—"}
    业务口径 = {
        "门店成交率": (f"{100*店率:.0f}%" if 店率 is not None else "—"),
        "门店怎么算的": 店说.replace("个亲自接待过的客户", "个亲自接待过的客户里成交的"),
        "顾问成交率": dict(sorted(顾问率.items(), key=lambda kv: -kv[1]["亲自接待过的客户"])),
        "口径": ("业务 09-22 定:**按客户算,不按接待次数**。门店 = 成交客户数 ÷ 亲自接待过的客户数;"
                "顾问 = 他在成交客户上的 W 型份额之和 ÷ 他亲自接待过的客户数。"
                "一个客户下多张单只算 1 个成交客户;远程量体不算接待。"),
        "⚠️ 没定的两处(先用行业默认)": "**不分周期**(全部数据);**多张单算 1 个成交客户**",
        "⚠️ 前提": "W 型 30/30/30/10 是惯例不是算出来的;**触点和订单都是造的数据**,"
                    "这个数证明口径跑得通,不是真实成交率",
    }
    if mode:
        import seed as _seed
        N = int(n_days or _归.默认N)
        月 = month or _seed.TODAY[:7]
        店接待 = [x for x in 接待列表 if x[2] in 人 and (not 店 or 人[x[2]][1] == 店)]
        try:
            结 = _归.分期成交率(店接待, 订单列表, mode, 月, _seed.TODAY, N)
        except ValueError as e:
            return dict(error=str(e))
        a, b = 结["门店"]
        业务口径 = {
            "口径": f"{mode}口径 · {月}" + (f" · N={N} 天" if mode == "队列" else ""),
            "门店成交率": f"{100*a/b:.0f}%" if b else "—",
            "门店怎么算的": (f"{a} ÷ {b} —— " + (
                f"{月} 被亲自接待过的客户里,当月下了定制单的" if mode == "同期" else
                f"首次亲自接待在 {月} 的客户里,{N} 天内下了定制单的")),
            "顾问成交率": {人[w][0]: {"分母客户": n, "归因成交份额": round(x, 1),
                                    "成交率": f"{100*x/n:.0f}%" if n else "—"}
                         for w, (x, n) in sorted(结["顾问"].items(), key=lambda kv: -kv[1][1])},
            "同期和队列的区别": ("同期:这个月接待、下个月才下单的客户,这个月算没成交 —— "
                              "**长周期生意会被系统性压低**。队列:按首次接待归月,看 N 天内成没成。"),
        }
        if 结["未成熟"]:
            业务口径["⚠️ 这一批还没到 N 天"] = ("有客户首次接待到今天还不满 N 天 —— **率会偏低**,"
                                            "那不是没成交,是还没到时候。看已经满 N 天的月份更准。")
        if mode == "队列" and not n_days:
            业务口径["N 为什么是 90"] = ("**业务 09-22 确认**。行业惯例让 N 覆盖约八成最终成交(P80);演示数据里 "
                                        "30 天只覆盖 52%,90 天覆盖 77%。**真实数据来了要重定**。")
    能, 说 = 口径.能不能算成交率(可用, len(单))
    不同人 = sum(1 for o in 单
                if o["appt_src"] == "接待关联" and (o["recept_by"] or "") != (o["advisor_no"] or ""))
    return {
        "看的范围": 范围,
        "定制单": len(单),
        "追得到接待的": 可用,
        "能不能算": 能,
        "为什么": 说,
        "① 按接待人算": 按人,
        "⚠️ 但这个数业务说过不对": (
            "业务 2026-09-20 原话:**「成交率毕竟是一个长期一对一营销的结果,"
            "不能因为某一次就算在某人身上」**。"
            f"而且 {不同人}/{可用} 的单,**接待人和订单上的顾问不是同一个人** —— "
            "按接待人算,等于把这些单算在只接待过一次的人头上。"),
        "② 按归因算(业务要的那个)": 业务口径,
        "⚠️ 最要紧的一句": (
            "**两个数都像成交率,而它们回答的是不同的问题。** "
            "①问「这次接待成没成」,②问「这个人对这些成交贡献了多少」—— "
            "业务要的是②。报数时必须说清是哪一个。"),
    }


def _口径_linkage():
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(
        _o.path.abspath(__file__))), "knowledge"))
    import linkage
    return linkage


def customer_history(customer=None, limit=30):
    """**这个客户之前谁接触过、做了什么** —— 按时间排的一条线。

    五张表里的触点(预约 / 跟进 / 日程 / 量体 / 下单)本来是散着的,
    这里把它们连起来。顾问打电话之前看一眼:上次是谁跟的、聊到哪儿了。

    ⚠️ **一次量体是一次触点,不是十几次。** 一个客户一次量体会产生十几行记录
    (每个测量项一条),去重的口径在 `knowledge/journey.去重`。
    不去重的话,量体会以 10:1 淹没其他触点 ——
    **而「他主要是来量体的」只是因为那张表行数最多。**
    """
    me = whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    if not customer:
        return dict(error="要给一个客户号或姓名 —— 这个工具看的是**一个人**的经过")
    import touchpoint as _tp
    import sqlite3 as _sq
    con = _sq.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        cs = [dict(r) for r in con.execute(
            "SELECT id,name,shop,advisor_no FROM customer WHERE id=? OR name=?",
            (customer, customer))]
    finally:
        con.close()
    if not cs:
        return dict(error=f"没有这个客户「{customer}」—— **这是数据问题,不是他没来过**")
    if len(cs) > 1:
        # **重名的时候不给明细** —— 给错人的接触史比不给更糟
        return {"error": f"「{customer}」命中 {len(cs)} 个客户,要改用客户号",
                "候选": [{"客户号": c["id"], "门店": c["shop"]} for c in cs[:5]]}
    c0 = cs[0]
    if me.get("role") in MANAGER_ROLES:
        if me.get("role") != "总部运营" and me.get("shop") and c0["shop"] != me["shop"]:
            return dict(error=f"{c0['name']} 在 {c0['shop']},不在你的门店")
    elif (c0.get("advisor_no") or "") != (me.get("no") or "?"):
        return dict(error=f"{c0['name']} 不在你名下 —— **这不是他没有接触记录**")

    旅 = _tp.客户旅程(c0["id"])
    能算, 码, 说 = _口径_journey().够不够算(旅)
    n = max(1, min(int(limit or 30), 100))
    近 = 旅[-1] if 旅 else None
    return {
        "客户": f"{c0['name']}({c0['id']})",
        "触点数": len(旅),
        "最近一次": ({"什么时候": 近.get("时间"), "干了什么": 近.get("类型"),
                     "谁": 近.get("经手人"), "备注": 近.get("备注")} if 近 else None),
        "按时间": [{"时间": x.get("时间"), "类型": x.get("类型"),
                   "谁": x.get("经手人"), "备注": x.get("备注")} for x in 旅[:n]],
        "还有": max(0, len(旅) - n),
        "够不够算归因": {"能不能": 能算, "码": 码, "为什么": 说,
                       "下一步": _口径_journey().下一步.get(码, "")},
        "⚠️": ("**一次量体是一次触点,不是十几次**(已按 日期+经手人 去重)。"
               "⚠️ 这条线只包含**系统里有记录的**接触 —— "
               "微信、电话没录进来的不在里面,**「线上没有」不等于「没联系过」**。"),
    }


def _口径_journey():
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(
        _o.path.abspath(__file__))), "knowledge"))
    import journey
    return journey


def deal_credit(order=None, staff=None, limit=20):
    """**这一单谁有贡献,贡献多少。**

    ⚠️ 这个工具的全部要害是:**两种分成不是一回事,不许相加也不许互相比较。**

        收入分成    加起来**必须 100** —— 那是分钱(算提成)
        影响力分成  **可以超过 100** —— 那是记贡献,不是零和的

    一单 10 万可以同时是「收入:张三 70 + 李四 30」和
    「影响力:张三 100 + 李四 60 + 店长 40」。两者在库里长得一模一样,
    都是「某人 + 某个百分比」。

    ⚠️ **这一版只记录,不算成交率。** 算率要先有「订单追得到哪次接待」
    (3511 张定制单还标着「未接入」)和足够的触点数据。
    """
    me = whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import credit as _cd
    import sqlite3 as _sq
    con = _sq.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        # 范围跟身份走:顾问只看自己参与的,店长看本店的人,总部看全部。
        if me.get("role") in MANAGER_ROLES:
            if me.get("role") != "总部运营" and me.get("shop"):
                人 = [r["no"] for r in con.execute(
                    "SELECT no FROM staff WHERE shop=?", (me["shop"],))]
                范围 = f"{me.get('shop')}(你的门店)"
            else:
                人, 范围 = None, "全部门店"
        else:
            人, 范围 = [me.get("no") or "?"], "你自己参与的单"
        if staff:
            r = con.execute("SELECT no FROM staff WHERE no=? OR name=?",
                            (staff, staff)).fetchone()
            if not r:
                return {"看的范围": 范围,
                        "error": f"员工表里没有「{staff}」—— **这是数据问题**"}
            if 人 is not None and r["no"] not in 人:
                return {"看的范围": 范围,
                        "error": f"「{staff}」不在你的范围里 —— **这不是他没有贡献**"}
            人 = [r["no"]]
        where, args = [], []
        if 人 is not None:
            where.append(f"staff_no IN ({','.join('?' * len(人))})"); args += 人
        if order:
            where.append("order_id = ?"); args.append(order)
        rows = [dict(x) for x in con.execute(
            "SELECT * FROM deal_credit" + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY order_id, kind, pct DESC", args)]
    finally:
        con.close()
    if not rows:
        return {"看的范围": 范围, "合计": 0,
                "说明": ("这个范围里一条归因记录都没有。"
                         "⚠️ **「没有贡献」和「没记过归因」不是一回事** —— 现在是后者。")}

    两种 = {_cd.收入分成: [], _cd.影响力分成: []}
    来源计 = {}
    for r in rows:
        两种.setdefault(r["kind"], []).append(r)
        来源计[r["source"]] = 来源计.get(r["source"], 0) + 1
    n = max(1, min(int(limit or 20), 100))
    out = {
        "看的范围": 范围,
        "记录数": len(rows),
        # **两种分开摆,而且各自带一句它是什么** —— 摆在一起就会被加起来。
        "收入分成(总和必须=100,这是分钱)":
            [{"单": r["order_id"], "谁": r["staff_no"], "角色": r["role"],
              "占比": r["pct"], "来源": r["source"], "算法": r["method"]}
             for r in 两种[_cd.收入分成][:n]],
        "影响力分成(可以超过100,这是记贡献)":
            [{"单": r["order_id"], "谁": r["staff_no"], "角色": r["role"],
              "占比": r["pct"], "来源": r["source"], "算法": r["method"]}
             for r in 两种[_cd.影响力分成][:n]],
        "每种分成是什么": _cd._口径.下一步,
        # **三种来源要分得开** —— 人填的、规则给的、算法算的,算出来都是一个百分比。
        "按来源": 来源计,
        "⚠️": ("**两种分成不许相加,也不许互相比较。** 一个是分钱(必须 100),"
               "一个是记贡献(可以超 100)。"
               "⚠️ **这不是成交率** —— 算率还缺「订单追得到哪次接待」那条链路。"),
    }
    if order:
        try:
            w = _cd.W型归因(order)
        except Exception as e:
            w = None
            out["W型算不出来"] = f"{type(e).__name__}"
        if w:
            out["W型归因算出来的影响力"] = [
                {"谁": a, "占比": b, "在哪几个节点": c} for a, b, c in w]
            out["W型的前提"] = ("30/30/30/10 是**行业惯例,不是算出来的** —— "
                               "换成 40/20/30/10 排序就可能变,所以入库要写明版本。"
                               "⚠️ **造出来的旅程算出的分配,不能当成真实贡献。**")
        elif w == []:
            # **「算出来大家都是 0」和「压根没有触点」长得一模一样** —— 分开说
            out["W型归因算出来的影响力"] = "这一单**没有可用的触点**,算不出来 —— 不是大家都没贡献"
    异常 = _cd.收入分成对不对()
    if 异常:
        out["⚠️ 收入分成加起来不是 100 的单"] = 异常[:10]
        out["还有几单不对"] = max(0, len(异常) - 10)
    return out


def on_shift(staff=None, date=None, at=None, days=7):
    """**谁哪天上班,以及那个人那个时候能不能接。** 读的是**排班表**(上不上班、什么班次),**不是日程占用** —— 谁那个时段被任务占了要用 `week_grid`。

    ⚠️ 这个工具存在的全部理由,是把「不上班」的**五种**分开:

        未排        店长还没排到这一天 —— **这不是「他没空」,是「排班还没出来」**
        草稿        店长还在调,随时会变 —— 按它派的单会挂在错的人身上
        已发布休息  确实没空
        请假        没空,**而且已经派给他的单要重新分配**
        不在时段    他这天上班,但不在这个点(早班的人接不了晚上的预约)

    **「查不到记录」只能表示「还没排」。** 拿它当没空,会在店长还没排下周班的时候,
    给出一份「所有人下周都有空」的推荐 —— **而那个结论看起来完全正常**。
    """
    me = whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import roster as _rs, datetime as _dt
    import sqlite3 as _sq
    店 = None if me.get("role") == "总部运营" else (me.get("shop") or "")
    范围 = "全部门店" if 店 is None else f"{店}(你的门店)"

    # ── 某个人某一天(或某个时段)能不能接 ──────────────────────
    if staff:
        con = _sq.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = _sq.Row
        try:
            r = con.execute("SELECT no,name,role,shop,status FROM staff WHERE no=? OR name=?",
                            (staff, staff)).fetchone()
        finally:
            con.close()
        if not r:
            # **「查无此人」和「他没空」不是一回事** —— 前者是数据问题。
            return {"看的范围": 范围,
                    "error": f"员工表里没有「{staff}」—— **这是数据问题,不是他没空**"}
        # **范围跟身份走** —— 上面那句「看的范围」说的是本店,
        # 而查人这一支原来不看门店,店长能查到别的店的人。
        # **返回值上写着「你的门店」,实际却跨了店** —— 两者长得一样。
        if 店 is not None and (r["shop"] or "") != 店:
            return {"看的范围": 范围,
                    "error": f"{r['name']} 在 {r['shop'] or '(没填门店)'},不在你的门店 —— "
                             f"**这不是他没空,是你看不到他的排班**"}
        d = date or _rs._世界的今天()          # 它返回的是字符串,不是 date
        if at:
            起 = f"{d} {at}"
            止 = f"{d} {at}"
            # 只给一个点的时候,按一小时算 —— 预约本来就是按时段
            try:
                h, m = at.split(":")
                止 = f"{d} {int(h)+1:02d}:{m}"
            except Exception:
                pass
            ok, 码, why = _rs.时段在班(r["no"], 起, 止)
        else:
            ok, 码, why = _rs.在班吗(r["no"], d)
        return {"看的范围": 范围, "谁": f"{r['name']}({r['no']})", "哪天": d,
                "能不能接": ok, "码": 码, "为什么": why,
                "下一步": _rs._口径.下一步.get(码, "")}

    # ── 一段时间的排班概况 ────────────────────────────────────
    d0 = _dt.date.fromisoformat(date or _rs._世界的今天())
    n = max(1, min(int(days or 7), 14))
    con = _sq.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        people = [dict(x) for x in con.execute(
            "SELECT no,name FROM staff WHERE role='顾问' AND status='启用'"
            + ("" if 店 is None else " AND shop=?"), () if 店 is None else (店,))]
    finally:
        con.close()
    每天 = []
    未排的天 = []
    for i in range(n):
        d = (d0 + _dt.timedelta(days=i)).isoformat()
        计 = {}
        在班 = []
        for p in people:
            ok, 码, _ = _rs.在班吗(p["no"], d)
            计[码] = 计.get(码, 0) + 1
            if ok:
                在班.append(p["name"])
        每天.append({"日期": d, "按码": 计, "在班的": 在班})
        if 计.get("UNSCHEDULED"):
            未排的天.append(d)
    return {
        "看的范围": 范围,
        "看了几个顾问": len(people),
        "看了几天": n,
        "每天": 每天,
        # **这一栏要单独摆出来。** 「还没排」混在「不上班」里,
        # 店长就看不见自己漏排了哪几天。
        "⚠️ 还没排班的日子": 未排的天,
        "每种码该做什么": _rs._口径.下一步,
    }


def revive_list(customer=None, limit=20):
    """**这些客户现在该不该联系,以及联系他说什么。**

    ⚠️ 这个工具回答的是「**为什么是他,为什么是现在**」两件事。
    只按闲置天数筛的名单,顾问拿到也不知道说什么,打过去就是尬聊 ——
    **所以没有由头的不进名单,哪怕他闲置 300 天。**

    ⚠️ **三个门槛是拍的,不是算出来的**(断节奏倍数 / 刚联系过 / 刚下过单)。
    返回值里会把它们列出来 —— **一个拍脑袋的门槛和一个有出处的门槛,
    在数字上长得一模一样**,不标出来的话下游会把它当成结论。
    """
    me = whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import revive as _rv
    import sqlite3 as _sq
    today = _rv._today()
    con = _sq.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        where, args = [], []
        if me.get("role") in MANAGER_ROLES:
            if me.get("role") != "总部运营" and me.get("shop"):
                where.append("shop = ?"); args.append(me["shop"])
            范围 = "全部门店" if me.get("role") == "总部运营" else f"{me.get('shop')}(你的门店)"
        else:
            where.append("advisor_no = ?"); args.append(me.get("no") or "?")
            范围 = "你名下的客户"
        if customer:
            where.append("(id = ? OR name = ?)"); args += [customer, customer]
        cs = [dict(r) for r in con.execute(
            "SELECT * FROM customer" + (" WHERE " + " AND ".join(where) if where else ""), args)]
    finally:
        con.close()
    if not cs:
        return {"看的范围": 范围, "合计": 0,
                "说明": "这个范围里没有客户" + ("(或者这个客户不在你的范围里)" if customer else "")}

    待校准 = {k: getattr(_rv._口径, k) for k in _rv._口径.待校准}
    要促, 不促 = [], {}
    for c in cs:
        判, 码, why = _rv.should_revive(c, today)
        if 判:
            要促.append({"客户": c.get("name"), "客户号": c.get("id"),
                         "由头": 码, "为什么是现在": why})
        else:
            不促[码] = 不促.get(码, 0) + 1
    n = max(1, min(int(limit or 20), 100))
    out = {
        "看的范围": 范围,
        "看了几个客户": len(cs),
        "该联系的": len(要促),
        "名单": 要促[:n],
        "还有": max(0, len(要促) - n),
        # **不促的也要说清是哪一种** —— 「现在不是时候」和「这人没由头」
        # 和「他还没热过」,下一步完全不同,而它们都是「不在名单里」。
        "没进名单的": 不促,
        "没进名单的该做什么": {c: _rv._口径.下一步[c] for c in sorted(不促) if c in _rv._口径.下一步},
        "⚠️ 这几个门槛是拍的": 待校准,
    }
    if customer and len(cs) == 1:
        判, 码, why = _rv.should_revive(cs[0], today)
        out["这一个人"] = {"客户": cs[0].get("name"), "该不该联系": 判, "码": 码,
                          "理由": why, "下一步": _rv._口径.下一步.get(码, "")}
    return out


def call_opportunity(customer=None, limit=20):
    """**这些通话里有没有值得跟进的生意。**

    两种用法,**代价差一个数量级**,所以刻意分开:

        不给 customer  → 清单。**只跑规则层**(免费、确定),给的是**候选**
        给了 customer  → 这一个人深判。规则层 + 模型层,模型只回答一个问题:
                         **客户是真想要,还是随口一提**

    为什么清单不跑模型:一条逐字稿一次模型调用,清单动辄几十条。
    而规则层的天花板已经量出来了 —— 24 条里误报 7 条,**全是同一个形状**:
    「齐胸襦裙听起来不错啊,但是呢,我先不急着定」——有维度词、店里有货,
    规则判商机,而他只是随口一提。

    ⚠️ 所以清单里**约三成是随口一提**。这个数必须跟着清单一起给出去 ——
    **一份没说明白的候选清单,和一份确认过的商机清单长得一模一样**,
    顾问会照着它一个个打过去。
    """
    me = whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import opportunity as _op
    import sqlite3 as _sq
    con = _sq.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        # 范围跟身份走:顾问只看自己名下的客户,店长看本店,总部看全部。
        # **和 get_tasks / ownerless_list 同一套规矩**,不在这儿自己另写一份。
        where, args = [], []
        if me.get("role") in MANAGER_ROLES:
            if me.get("role") != "总部运营" and me.get("shop"):
                where.append("cu.shop = ?"); args.append(me["shop"])
            范围 = "全部门店" if me.get("role") == "总部运营" else f"{me.get('shop')}(你的门店)"
        else:
            where.append("cu.advisor_no = ?"); args.append(me.get("no") or "?")
            范围 = "你名下的客户"
        if customer:
            where.append("(cu.id = ? OR cu.name = ?)"); args += [customer, customer]
        rs = [dict(r) for r in con.execute(
            "SELECT t.audio_id, t.text, cu.id cid, cu.name cname, cu.shop "
            "FROM call_transcript t JOIN call_audio a ON a.id = t.audio_id "
            "JOIN customer cu ON cu.id = a.customer_id"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY a.created DESC", args)]
    finally:
        con.close()
    if not rs:
        return {"看的范围": 范围, "合计": 0,
                "说明": ("这个范围里一条**有逐字稿的通话**都没有。"
                         "⚠️ **「没有商机」和「没有录音」不是一回事** —— "
                         "现在是后者:没东西可判。")}

    if customer:
        # 深判:一个人,连模型一起跑
        出 = []
        for r in rs[:3]:          # 最多三通,再多就该让人自己听了
            try:
                判, 码, why = _op.判断_带模型(r["text"])
            except Exception as e:
                # **「跑崩了」和「判成不是商机」长得一模一样** —— 分开报
                出.append({"通话": r["audio_id"], "结果": "判不了",
                           "为什么": f"模型这一层没跑通:{type(e).__name__}"})
                continue
            出.append({"通话": r["audio_id"], "是商机": 判,
                       "码": 码 if not 判 else "有商机",
                       "理由": why,
                       "下一步": _op._口径.下一步.get(码 if not 判 else "有商机", "")})
        return {"看的范围": 范围, "客户": f"{rs[0]['cname']}({rs[0]['cid']})",
                "通话数": len(rs), "判了": len(出), "结果": 出,
                "怎么判的": "规则层看客户说了什么偏好、店里有没有货;"
                            "模型层只回答一个问题:真想要还是随口一提。"}

    # 清单:只跑规则层
    候选, 没进的 = [], {}
    for r in rs:
        判, 码, why = _op.判断(r["text"])
        if 判:
            候选.append({"客户": r["cname"], "客户号": r["cid"],
                         "通话": r["audio_id"], "维度": 码, "理由": why})
        else:
            # **「没进清单」的原因要给出去。**
            # 只给通过的那些,等于把「为什么这几通没进」变成一个答不上来的问题 ——
            # 而管这个工具的规矩(TL34)讲的正是这四种码的下一步各不相同。
            # **规矩引用一个角色拿不到的字段,模型只能自己编。**
            没进的[码] = 没进的.get(码, 0) + 1
    n = max(1, min(int(limit or 20), 100))
    return {
        "看的范围": 范围,
        "有逐字稿的通话": len(rs),
        "规则层筛出的候选": len(候选),
        "候选": 候选[:n],
        "还有": max(0, len(候选) - n),
        "没进候选的": 没进的,
        "没进候选的该做什么": {c: _op._口径.下一步[c] for c in sorted(没进的)},
        "⚠️ 这是候选不是结论": (
            "这一层只看「客户提到了什么 + 店里有没有货」,**分不出想要和随口一提**。"
            f"实测 24 条里误报 7 条(约三成)。要确认某一个人,"
            f"用 call_opportunity(customer=\"客户号\") —— 那一步会调模型判「真想要还是提一句」。"),
    }


def ownerless_list(code=None, limit=50):
    """**谁实际上没人管** —— 归属字段非空不等于有人在管。

    口径在 `knowledge/owner.py`,取数在 `backend/ownership.py`,
    这里只做三件事:**取身份、按身份限范围、把「下一步」一起给出去**。

    ⚠️ **这个工具一行都不写。** 业务定的边界:agent 只给参谋。
    「这个客户的归属顾问已离职」是一个事实,摆出来;改不改是店长的动作 ——
    他可能想等交接、想指给特定的人,也可能这个客户马上要复购不宜此时换人。
    """
    me = whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import ownership as _own
    # 2026-09-21:**顾问也能看了,看的是自己名下那一份**。
    # 原来只给店长和总部 —— 而「我名下的客户有没有问题」是顾问天天要问的。
    全部 = _own.明细(查经手=True)
    # 范围跟身份走:顾问看自己名下的,店长看本店,总部看全部。
    if me.get("role") in MANAGER_ROLES:
        店 = None if me.get("role") == "总部运营" else (me.get("shop") or "")
        行 = [r for r in 全部 if 店 is None or (r.get("门店") or "") == 店]
        范围 = "全部门店" if 店 is None else f"{店}(你的门店)"
    else:
        # 顾问那一份:**只有他名下的**。
        # ⚠️ 他自己名下的客户,按定义不会出现 NONE / NO_SUCH / LEFT
        # (归属就是他,而他在职)—— 所以他这份清单**多半是空的**,
        # 而「空」必须说清**查了哪几类**,不能说成「一切正常」。
        行 = [r for r in 全部 if (r.get("归属工号") or "") == (me.get("no") or "?")]
        店, 范围 = "", "你名下的客户"       # 店 留空:顾问那一份不按门店筛,按归属人筛
    if code:
        码集 = {c.strip().upper() for c in str(code).replace("，", ",").split(",") if c.strip()}
        行 = [r for r in 行 if r["码"] in 码集]
    按码 = {}
    for r in 行:
        按码[r["码"]] = 按码.get(r["码"], 0) + 1
    n = max(1, min(int(limit or 50), 200))
    if me.get("role") in MANAGER_ROLES:
        待 = [d for d in _own.待确立()
              if 店 is None or (d.get("门店") or "") == 店]
    else:
        # 顾问那一份:**按接待人是不是他**筛,不按门店 —— 同一家店好几个顾问。
        待 = [d for d in _own.待确立()
              if (d.get("接待人") or "") == (me.get("no") or "?")]
    out = {
        "看的范围": 范围,
        "合计": len(行),
        "按码": 按码,
        # **每种码的下一步都摆出来** —— 分成几种码的全部理由就是动作不同,
        # 只报码的话,读的人还得自己去翻这几个字母是什么意思。
        "每种码该做什么": {c: _own._口径.下一步[c] for c in sorted(按码)},
        "清单": [{"客户号": r["id"], "姓名": r["name"], "门店": r.get("门店"),
                  "码": r["码"], "说法": r["说法"], "下一步": r["下一步"]} for r in 行[:n]],
        "还有": max(0, len(行) - n),
        "待确立归属": len(待),
        "⚠️": "这个工具**只查不改**。归属要不要动、动给谁,是店长的业务动作。",
    }
    if not 行:
        # **「没查到」和「没有问题」要分开。**
        # 空清单不许说成「一切正常」—— 它只说明**这几类问题**没有。
        out["查了哪几类"] = list(_own._口径.下一步)
        out["⚠️ 空清单是什么意思"] = (
            "**只说明上面那几类问题你名下没有**,不等于客户都跟得好 —— "
            "「他最近该不该联系」用 revive_list,「他之前谁接触过」用 customer_history。")
    return out


TOOLS.update({"get_tasks":get_tasks,"get_member":get_member,
              # ⚠️ 老名字**留在 TOOLS 里**(边界审计和隔离检查按 TOOLS 逐个跑),
              #    但已经从 SHOP_SCHEMAS 下架 —— **TOOLS 是实现登记册,
              #    SCHEMAS 才是 agent 看得见的工具面**,要降的是后者。
              "get_scheme":get_scheme,"get_order":get_order,"get_stock":get_stock,"get_aftersale":get_aftersale,
              "get_capacity":get_capacity,
              "get_wearer":get_wearer,"forecast_growth":forecast_growth,
              "plan_for_event":plan_for_event,"get_maintain":get_maintain,
              "get_workorder":get_workorder,
              "get_lifecycle":get_lifecycle,
              "get_member_priority":get_member_priority,
              "check_write":check_write,
              "my_tasks":my_tasks,"task_types":task_types,"dispatch_pool":dispatch_pool,
              "team_tasks":team_tasks,"monthly_review":monthly_review,"member_level":member_level,"points_ledger":points_ledger,"approval_queue":approval_queue,"activity_roi":activity_roi,"can_order":can_order,"my_workorders":my_workorders,"piece_ratios":piece_ratios,"set_piece_ratio":set_piece_ratio,"pattern_queue":_pattern_queue,"recovery_queue":recovery_queue,"stock_alert":stock_alert,"fitting_queue":fitting_queue,"record_fitting":record_fitting,"record_measure":record_measure,"open_order":open_order,"confirm_order":confirm_order,"record_pickup":record_pickup,"verify_fit_code":verify_fit_code,"ratify_complete":ratify_complete,"start_cutting":start_cutting,"channel_compare":channel_compare,"grading_audit":grading_audit,"apply_adjust":apply_adjust,"decide_approval":decide_approval,"appt_funnel":appt_funnel,"week_grid":week_grid,"assign_batch":assign_batch,"dispatch_batch":dispatch_batch,"get_task":get_task,"assign_task":assign_task,"dispatch_task":dispatch_task,"reassign_task":reassign_task,"finish_task":finish_task,
              "get_review_queue":get_review_queue,
              "ownerless_list":ownerless_list,
              "call_opportunity":call_opportunity,
              "revive_list":revive_list,
              "on_shift":on_shift,
              "deal_credit":deal_credit,
              "customer_history":customer_history,
              "conversion_rate":conversion_rate})
TOOLS.update({"kb_lookup":kb_lookup,"kb_detail":kb_detail,"kb_tables":kb_tables,"kb_read":kb_read,
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
 {"name":"kb_read","description":"**读知识库原文** —— 表里查不到、只在正文里的那些话:怎么洗怎么存、为什么这么做、客户问「为什么这么贵」时怎么答。**先不传 section 拿这一篇的小节目录,再指定小节取正文** —— 不给整篇,一次几百行会把后面真正该看的挤出去。doc 认编号(09)、文件名、或主题词(养护)。返回带**来源等级**:一节里混着几档时按**最低那一档**给对客口径;**正文里没有标记不代表它可靠,代表没人标过**。","input_schema":{"type":"object","properties":{"doc":{"type":"string","description":"篇:01–12 的编号、文件名、或主题词(如「养护」「版型库」)"},"section":{"type":"string","description":"小节标题(写一部分也认)。不传则给这一篇的小节目录"}}}},
 {"name":"kb_tables","description":"取全部决策表(6 张共 30 行:客户原话对照、选料决策、配饰形制搭配、配色易错、工期档位、售后争议判定)。顾问问「客户说了 X,我该推什么/避开什么/怎么处理」这类问题时**优先用这个**,而不是 kb_lookup。**直接不带参数调用即可**,取全部比挑一张更可靠。",
  "input_schema":{"type":"object","properties":{"topic":{"type":"string","description":"通常不要传。全部决策表合计只有 30 行,一次全取更可靠 —— 传了 topic 反而容易取错表。"}},"required":[]}},
 # kb_coverage(相容矩阵完成度)2026-09-22 从模型可见的工具里拿掉:矩阵早已 2025 格全有结论,
 # 这个数对顾问回答任何问题都没用,只是每轮多带一段说明(能力盘点)。函数留着 —— prompts_check 直接调它数格子。
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
