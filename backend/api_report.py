"""从 backend/api.py 拆出来的「api_report」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api
import sqlite3, os, json, sys, re, subprocess
import shop_key as _SK                                         # noqa: E402  门店关联键的唯一来源
import datetime as _dt
import worldclock as _wc


def monthly_review(month=None, week=None, start=None, end=None):
    """**月度复盘**:这个月做完了多少、几条逾期、逾期都在谁身上、改派了几次、
    agent 的派单建议采纳率、待分配积压、订单走完一轮要多久。

    month 写 `2026-09`,不给就是当月。范围跟身份走:顾问只看自己的,店长看本店。

    ⚠️ **分母为零时不给比率,给一句话** —— 「没发生过」和「发生了但都是零」
    是两件事,而它们在一张报表上长得一模一样。
    """
    import tasks as _tk, datetime, json as _js, statistics as _st
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import knowledge.review as rv

    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    today = _wc.今天().isoformat()
    m = (month or today[:7]).strip()
    if start and end:
        区起, 区止 = str(start)[:10], str(end)[:10]
        m, week = f"{区起} ~ {区止}", "区间"
    elif week:
        # 周报用(用户 10-09:业务周 = 周一到周日)。归周的钟和归月**同一个**(rv.归月字段),只是区间换成一周
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge"))
        import weekly as _wk
        try:
            _一, _日 = _wk.周起止(week)
        except ValueError:
            return dict(error=f"week 要写成那一周里任意一天 `YYYY-MM-DD`,收到「{week}」")
        区起, 区止, m = _一.isoformat(), _日.isoformat(), f"{_一} ~ {_日}(业务周,周一到周日)"
    elif not re.fullmatch(r"\d{4}-\d{2}", m):
        return dict(error=f"月份写成 2026-09 这样,收到「{month}」")
    else:
        区起, 区止 = m + "-01", m + "-31"

    where, args, scope = _tk.visible_scope(me)
    ts_ = api._rows(f"SELECT s.*, st.name assignee_name FROM schedule s "
                f"LEFT JOIN staff st ON st.no=s.assignee_no "
                f"WHERE {where} AND substr(s.{rv.归月字段},1,10) BETWEEN ? AND ?", *(args + [区起, 区止]))

    out = dict(**({"区间": m} if week else {"月份": m}), 范围=scope,
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
        out["任务"] = dict(总数=0, 说明=f"{m} " + ("这一周" if week else "这个月") + ",你看得到的范围里没有任务到期")

    # 动作:从台账里取,但**按它动的那条任务归月**,和上面同一个钟。
    ids = {r["id"] for r in ts_}
    logs = api._rows("SELECT code,target,reason,ctx,ts FROM op_log WHERE code IN "
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
    live = {r[0] for r in api._rows2("SELECT id FROM schedule")}
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

    pool = len(api._rows(f"SELECT s.id FROM schedule s WHERE {where} "
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
        ap = api._rows("SELECT a.*, c.shop cshop FROM approval a "
                   "LEFT JOIN customer c ON c.id=a.target "
                   "WHERE substr(a.applied_at,1,10) BETWEEN ? AND ?", 区起, 区止)
        if me.get("role") != "总部运营":
            ap = [x for x in ap if (x.get("cshop") or "") == me.get("shop")]
        if ap:
            agent = [x for x in ap if _by_agent(x["id"])]
            done = [x for x in agent if x["status"] in ("已通过", "已驳回")]
            passed = [x for x in done if x["status"] == "已通过"]
            txt, _ = rv.rate(len(passed), len(done), "智能体提的审批")
            out["审批"] = api._nz(dict(
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
    for o in api._rows(f"SELECT created,finished_at FROM ordr WHERE status='完成' "
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
    return api._nz(out)

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

    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    today = _wc.今天().isoformat()
    for lbl, v in (("since", since), ("until", until)):
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v).strip()):
            return dict(error=f"{lbl} 写成 2026-08-01 这样,收到「{v}」")

    where, args, scope = _tk.visible_appt_scope(me)
    sql = f"SELECT a.* FROM appointment a WHERE {where}"
    if since: sql += " AND a.start_ts>=?"; args = args + [since]
    if until: sql += " AND a.start_ts<=?"; args = args + [until + " 23:59"]
    rs = api._rows(sql, *args)

    # **还没到点的整条不进分母** —— 既不是到店也不是流失,它只是还没发生。
    未到 = [r for r in rs if af.未到点(r.get("start_ts"), today)]
    rs = [r for r in rs if r not in 未到]
    if not rs:
        return api._nz(dict(范围=scope,
                        说明="这个范围里没有已经到时间的预约" +
                             (f"(还有 {len(未到)} 条在未来,不算进漏斗)" if 未到 else ""),
                        还没到时间的=len(未到) or None))

    总 = len(rs)
    确认了 = [r for r in rs if r.get("status") not in af.没确认]
    到店 = [r for r in rs if r.get("status") in af.到店了]

    # 后两环:按「同一个客户、预约之后」连 —— **没有外键,是估的**。
    #
    # ⚠️ **两条分组查询,不是逐条到店各查两次。** 原来是后者,而 `_rows2`
    # **每次调用新开一个数据库连接**(见它自己那一行)。70 条到店的时候
    # 是 140 次连库、眨眼就过;2026-10-11 接待触点进配方之后到店变成 1.7 万条,
    # 同一段代码变成 **3.5 万次连库**,而 `funnel_check` 要跑六遍 ——
    # 实测单条检查 99% CPU 跑过 3 分半,直奔门禁那 600 秒超时。
    #
    # > 一段「数据少时快得看不出问题」的代码,和一段没有这个问题的,
    # > **在小库上长得一模一样** —— 只有真实数据量能把它们分开。
    #
    # 判断没有变:**「存在一条 `measured_at >= t0` 的记录」等价于
    # 「`MAX(measured_at) >= t0`」**(都是字符串比较,NULL 被 MAX 忽略,
    # 和原来 `measured_at>=?` 遇 NULL 为假一致;查不到这个人 → 取到 ""
    # → 任何日期都比它大 → 和原来「没有记录」一样是不计)。
    cids = {r["customer_id"] for r in 到店 if r.get("customer_id")}
    最近量体 = dict(api._rows2("SELECT customer_id, MAX(measured_at) FROM measure_rec "
                         "WHERE customer_id IS NOT NULL GROUP BY customer_id"))
    最近下单 = dict(api._rows2("SELECT customer_id, MAX(created) FROM ordr "
                         "WHERE customer_id IS NOT NULL GROUP BY customer_id"))
    量了 = 下单了 = 0
    for r in 到店:
        cid, t0 = r.get("customer_id"), r.get("start_ts")
        if not cid or not t0: continue
        if (最近量体.get(cid) or "") >= t0[:10]: 量了 += 1
        if (最近下单.get(cid) or "") >= t0[:10]: 下单了 += 1

    各环 = [("约了", 总), ("确认了", len(确认了)), ("到店", len(到店))]
    表 = []
    for i, (名, n) in enumerate(各环):
        row = dict(环节=名, 人次=n)
        if 名 == "到店":
            # 到店的**客户数**(去重):同一个人这一期来两次,人次 2、客户数 1(V1.1:接待客户数要按周期重新去重,
            # 日报的数不能直接加成周报)。没挂客户号的到店不进客户数 —— 照实给出有几条没挂
            row["客户数"] = len(api._按人(cids))     # 按人数:同一个人两条档案只算一次(10-14 拍)
            没挂 = sum(1 for r in 到店 if not r.get("customer_id"))
            if 没挂:
                row["没挂客户号的到店"] = 没挂
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
    return api._nz(out)

def _by_agent(approval_id):
    """这张审批单是不是经智能体提的。

    判据是台账里那条 APPLY 记录的 `by_agent` 标记 —— **不是猜的**。
    工具层(`api.apply_adjust`)只有智能体走得到,页面走的是另一条路,
    所以标记打在写的时候,不在事后推断。
    """
    import json as _js
    for r in api._rows2("SELECT ctx FROM op_log WHERE code='APPLY' AND target=?", approval_id):
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

    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    if me.get("role") not in _tk.MANAGER_ROLES and me.get("role") != "总部运营":
        return dict(error=f"活动投入产出是管理视角,你的角色是「{me.get('role')}」—— "
                          f"这个得问店长")

    where, args = ("1=1", [])
    if code: where, args = ("code=?", [code.strip()])
    elif me.get("role") != "总部运营":
        # 店长只看得到本店的活动 + 全渠道的。本店按门店**码**筛,而「全渠道」那一支只能按串 ——
        # 它不是门店、没有码(`activity.shop` 里真有「全渠道」这个值)。
        # ⚠️ **算不出本店不等于看全部**:那时只剩全渠道那一支。
        # (原来写的是 `shop=NULL`,永不成立,效果一样 —— 这里只是把它写明白,没放宽。)
        _片, _参 = api._门店条件(me.get("shop"))
        _渠片, _渠参 = api._门店条件(_SK.全渠道)      # 认不出 → 按串比,这正是它该走的路
        where, args = ((f"({_片} OR {_渠片})", list(_参) + list(_渠参)) if _片
                       else (_渠片, list(_渠参)))
    acts = api._rows(f"SELECT code,name,kind,status,start_d,end_d,shop,budget "
                 f"FROM activity WHERE {where} ORDER BY start_d DESC", *args)
    if not acts:
        return dict(说明=f"没有找到活动{('(' + code + ')') if code else ''}")

    out = []
    for a in acts:
        # 成本三个口径
        cs = api._rows("SELECT amount,note FROM activity_cost WHERE activity=?", a["code"])
        已发生 = sum(x["amount"] or 0 for x in cs)
        已开票 = sum(x["amount"] or 0 for x in cs if (x["note"] or "") == "已开票")
        # 成交:先按归因取单,再分期内期外,取消的一律排除
        os_ = api._rows("SELECT id,customer_id,status,payable,received,created FROM ordr "
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
        row = api._nz(dict(
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
    return api._nz(dict(
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
    模拟 = {r["order_id"] for r in api._rows("SELECT order_id FROM sim_batch")}
    对 = {}
    for r in api._rows("SELECT id, COALESCE(activity,'(无)') a, source FROM ordr"):
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

def sales_rank(month=None, start=None, end=None, by="商品", metric="件数", kind=None,
               field="下单", limit=10):
    """**商品销量排行** —— 「九月卖得最好的商品是什么」「这个月哪个品类卖得多」。

    2026-10-09 用户在 chat 里问「九月订单中销量最好的商品」,模型答「查不了」——
    它手上只有按订单列的工具(orders_by_date 只到订单一层、不含商品行),
    要排商品就得逐单 get_order,1487 单不现实。**数据一直都在**(ordr_item 每行有 SPU 和件数),
    缺的只是一个按商品汇总的入口。

    口径**不在这里另拍**:
      · 哪些行算卖掉了 —— `knowledge/stockalert.卖掉了()`(库存预警的销量也是它,同一把尺)
      · 能看哪些单 —— `_订单范围()`(总部全部 / 店长本店 / 顾问名下∪经手)
      · 归到哪个月 —— 默认按**下单日**;`field` 可换成 完工 / 发货 / 交付(和 orders_by_date 同一张表)
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import stockalert as _sa
    me = api.whoami()
    if not me:
        return {"error": "没有登录身份,不知道看哪家店"}
    if field not in api._订单日期列:
        return {"error": f"field 只能是 {' / '.join(api._订单日期列)}", "按哪一列":
                {k: v[1] for k, v in api._订单日期列.items()}}
    列 = api._订单日期列[field][0]
    # 区间:month 或 start+end,**不替人解析「九月」** —— 和 orders_by_date 同一条理由
    if month is not None:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", str(month).strip())
        if not m or not 1 <= int(m.group(2)) <= 12:
            return {"error": f"month 要写成 `YYYY-MM`(比如 `2026-09`),你给的是「{month}」 ——"
                             "「九月」是今年九月还是最近一个月,**不替你猜**"}
        y, mo = int(m.group(1)), int(m.group(2))
        起日 = _dt.date(y, mo, 1)
        止日 = (_dt.date(y + (mo == 12), mo % 12 + 1, 1) - _dt.timedelta(days=1))
    elif start or end:
        if not (start and end):
            return {"error": "start 和 end 要一起给"}
        try:
            起日, 止日 = _dt.date.fromisoformat(str(start)), _dt.date.fromisoformat(str(end))
        except ValueError:
            return {"error": f"start/end 要写成 `YYYY-MM-DD`,你给的是「{start}」/「{end}」"}
        if 止日 < 起日:
            return {"error": f"end({止日})比 start({起日})还早 —— 不替你调换"}
    else:
        return {"error": "要给时间段:month=`YYYY-MM`,或 start + end"}
    键 = {"商品": "i.spu", "SKU": "i.sku", "品类": "p.category"}.get(by)
    if not 键:
        return {"error": "by 只能是 商品 / SKU / 品类"}
    if metric not in ("件数", "金额", "单数"):
        return {"error": "metric 只能是 件数 / 金额 / 单数"}
    if kind not in (None, "", "标品", "定制品"):
        return {"error": "kind 只能是 标品 / 定制品,不给就是都算"}
    limit = max(1, min(int(limit or 10), 50))

    where, args, 范围话, _ = api._订单范围(me)
    sql = (f"SELECT {键} k, i.order_id, i.qty, i.total, i.name iname, i.tag, o.status, o.refund_status, "
           "p.name pname, p.category cat, cg.name catname FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
           "LEFT JOIN customer cu ON cu.id=o.customer_id LEFT JOIN product p ON p.spu=i.spu "
           "LEFT JOIN category cg ON cg.code=p.category "
           f"WHERE o.{列} IS NOT NULL AND o.{列} >= ? AND o.{列} <= ?" + where
           + (" AND i.tag=?" if kind else ""))
    行 = api._rows(sql, 起日.isoformat(), 止日.isoformat() + " 23:59:59", *args, *([kind] if kind else []))
    汇, 没算, 总件, 总额, 总单 = {}, {}, 0, 0.0, set()
    for r in 行:
        算, 为啥 = _sa.卖掉了(r["status"], r["refund_status"])
        if not 算:
            k = (r["status"] + " · 已退款") if (r["refund_status"] or "") == "已退款" else r["status"]
            没算.setdefault(k, [0, 为啥])[0] += 1
            continue
        # 按品类汇总时「名称」就是品类名 —— 只给编码(C020101)店长看不懂
        名 = (r["catname"] or r["cat"]) if by == "品类" else (r["pname"] or r["iname"])
        a = 汇.setdefault(r["k"] or "(未登记)", {"名称": 名, "品类": r["catname"] or r["cat"],
                                               "类型": r["tag"] if by != "品类" else None,
                                               "件数": 0, "金额": 0.0, "单": set()})
        a["件数"] += r["qty"] or 0
        a["金额"] += r["total"] or 0
        a["单"].add(r["order_id"])
        总件 += r["qty"] or 0; 总额 += r["total"] or 0; 总单.add(r["order_id"])
    for a in 汇.values():
        a["单数"] = len(a.pop("单")); a["金额"] = round(a["金额"], 2)
    # 排序要确定:同值再按另两项、最后按编码 —— 不然同一个问题问两次,并列的几个顺序会变
    次 = [x for x in ("件数", "金额", "单数") if x != metric]
    排 = sorted(汇.items(), key=lambda kv: (-kv[1][metric], -kv[1][次[0]], -kv[1][次[1]], str(kv[0])))
    榜 = [dict(名次=i + 1, 编码=k, **v,
               占比=f"{(v[metric] / {'件数': 总件, '金额': 总额, '单数': len(总单)}[metric] * 100):.1f}%"
               if {'件数': 总件, '金额': 总额, '单数': len(总单)}[metric] else "—")
          for i, (k, v) in enumerate(排[:limit])]
    out = {"区间": f"{起日} ~ {止日}", "按哪一列": f"{field}({api._订单日期列[field][1]})",
           "范围": 范围话, "排名依据": metric, "按什么汇总": by + (f" · 只看{kind}" if kind else ""),
           "合计": {"件数": 总件, "金额": round(总额, 2), "单数": len(总单), f"上榜的{by}一共": len(汇)},
           "榜单": 榜}
    # **三种排法的第一名都给出来,不让模型自己推。** 2026-10-09 真跑:只按件数查了一次,
    # 模型从件数前十里挑了金额最大的,说「按金额排也是它第一」—— 错的:本店按金额第一
    # 是一款只卖 25 件的云锦大衫,它根本不在件数前十里。
    # > 一个「件数前十里金额最高的」和一个「按金额的第一」,在「也是它第一」这句话上长得一模一样。
    # 规矩里写了「顺带说按金额的第一」,可模型没再查一次 —— 所以答案放进返回值,照念就行
    if 汇:
        out["各排法的第一"] = {m: {"名称": v["名称"], "编码": k, m: v[m]}
                         for m in ("件数", "金额", "单数")
                         for k, v in [min(汇.items(), key=lambda kv: (-kv[1][m], str(kv[0])))]}
    # 边界并列要说出来:第 N 名和第 N+1 名同值,「前 N」就不是唯一的
    if len(排) > limit and 排[limit - 1][1][metric] == 排[limit][1][metric]:
        out["并列"] = (f"第 {limit} 名和第 {limit + 1} 名的{metric}一样({排[limit][1][metric]}),"
                     f"**前 {limit} 名不唯一** —— 报的时候要说出来")
    if 没算:
        # 数的是**订单行**(一单可以有好几行),不是单数 —— 10-09 真跑时模型把「128 行」说成了「128 单」
        out["没算进销量的订单行"] = {k: {"行数": v[0], "为什么": v[1]} for k, v in 没算.items()}
        out["没算进销量的订单行"]["注意"] = "这里数的是订单行(一单可以有好几行),不是单数 —— 报的时候说「行」"
    if not 汇:
        out["note"] = "这段时间在你的范围里没有卖掉的商品行 —— 是**没有**,不是查不到"
    else:
        out["note"] = ("「销量」默认按**件数**(一单买 3 件算 3);金额是订单行实收合计。"
                       "**定制品每单都是一件、单价高,和标品混排时按件数它几乎上不了榜、按金额又会霸榜** ——"
                       "问「卖得最好」没说按什么时,先按件数答,再照「各排法的第一」说按金额是谁 ——"
                       "**不要从榜单里自己推**(榜单是按一种排法截的前几名,另一种的第一常常不在里面)。"
                       "取消、待付款、已退款的行不算销量(口径同库存预警)。")
    return out

def weekly_revenue(week=None, start=None, end=None):
    """**按周营收 = 实收减退款**(周报用,用户 2026-10-09 拍板)。

    口径在 knowledge/weekly.py:业务周 = 周一到周日;实收按**付款日**归周,退款按**退款日**归周
    (不是下单日)。范围随身份走(同 orders_by_date:总部全部 / 店长本店 / 顾问名下∪经手)。
    ⚠️ 库里没有单独的「退款完成时间」,退款日用售后单的最后更新时间**近似** —— 返回值里明写。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import weekly as _wk
    from seed import TODAY
    me = api.whoami()
    if not me:
        return {"error": "没有登录身份,不知道看哪家店"}
    try:
        if start or end:
            # 日报 / 月报用同一个口径,只换时间窗(报告期在 knowledge/weekly.报告期)
            一, 日 = _dt.date.fromisoformat(str(start)), _dt.date.fromisoformat(str(end))
        else:
            一, 日 = _wk.周起止(week) if week else _wk.上一完整周(TODAY)
    except (ValueError, TypeError):
        return {"error": f"week 要写成这一周里任意一天 `YYYY-MM-DD`(或 start + end 一起给),你给的是「{week or start}」;不给就是上一个完整周"}
    if 一 > _dt.date.fromisoformat(TODAY):
        return {"error": f"{一} 那一周还没到(今天 {TODAY})"}
    where, args, 范围话, _ = api._订单范围(me)
    起, 止 = 一.isoformat(), 日.isoformat() + " 23:59:59"
    收 = [(r["d"], r["received"]) for r in api._rows(
        "SELECT substr(o.paid_at,1,10) d, o.received FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id "
        "WHERE o.paid_at IS NOT NULL AND o.paid_at >= ? AND o.paid_at <= ?" + where, 起, 止, *args)]
    退 = [(r["d"], r["amount"]) for r in api._rows(
        "SELECT substr(a.updated,1,10) d, a.amount FROM aftersale a JOIN ordr o ON o.id=a.order_id "
        "LEFT JOIN customer cu ON cu.id=o.customer_id "
        f"WHERE a.kind IN ({','.join('?' * len(_wk.退款类))}) AND a.status=? "
        "AND a.updated >= ? AND a.updated <= ?" + where,
        *_wk.退款类, _wk.退款完成, 起, 止, *args)]
    # 口径的说法跟着统计期走(11-23):日报 / 月报也调这里(start+end),原来一律写「这一周…归周」,
    # 单日日报两份都把「本周」原话抄了进去 —— 指引要在模型下笔那一刻就是对的,不靠它自己改写
    if not (start or end):
        期, 归, 邻 = "这一周", "归周", "相邻一周"
    elif 一 == 日:
        期, 归, 邻 = "当天", "归日", "相邻一天"
    else:
        期, 归, 邻 = "这段时间", "归到各自那一天", "区间外"
    out = {("区间" if (start or end) else "业务周"): f"{一} ~ {日}" + ("" if (start or end) else f"({_wk.周名})"),
           "范围": 范围话, **_wk.营收(收, 退),
           "口径": f"营收 = {期}实际收到的钱 − {期}退出去的钱;实收按付款日、退款按退款日{归}(业务 2026-10-09 定)",
           "⚠️ 近似": f"库里没有单独的「退款完成时间」,退款日用售后单最后更新时间近似 —— 个别退款可能被归到{邻}",
           "不算在内": "预约押金(可退的押金,不是营收)、还没付款的单、退款中还没走完的"}
    if 日 >= _dt.date.fromisoformat(TODAY):
        out["⚠️ 这一周还没过完" if not (start or end) else "⚠️ 区间还没过完"] = f"今天 {TODAY},数字截到今天"
    return out

def store_report(kind=None, date=None):
    """**门店经营报告的取数包** —— 日报 / 周报 / 月报共用(用户 2026-10-09:三种都要)。

    只取数、不写文字:每一项都带**出处**(哪个查询、什么参数)和**口径**,让写报告的那一步只能照着说。
    三种报告只差时间窗(knowledge/weekly.报告期):日 = 那一天,周 = 周一到周日,月 = 自然月;
    不给 date 就是上一个**完整**的那一期(昨天 / 上周 / 上个月)。
    两类数分开放,**不许混**:
      期内    这一期里发生了多少(订单、销量、营收、到店、评价、进入休眠、任务、成交率)
      存量    截至今天还压着多少(待付款、该催工厂、延期没通知、白坯、库存、差评待跟、流失预警)
    > 一个「本周新增 11 单该催」和一个「截至今天压着 11 单该催」,在报告里长得一模一样 —— 而后者才是真的。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import weekly as _wk
    from seed import TODAY
    me = api.whoami()
    if not me:
        return {"error": "没有登录身份,不知道看哪家店"}
    if me.get("role") not in api.MANAGER_ROLES:
        return {"error": "经营报告给店长 / 总部看(首版只做店长经营报告,方案 1.2)"}
    # 报告模板(复审第 4 节 C,用户 10-23 拍):只管显示(章节、显示 / 隐藏、默认期间),**不碰下面任何一个数的算法**。
    # 当时生效的那一版整份放进取数包 —— 存报告时随取数包一起冻结,打开旧报告按冻结的那一版显示
    import report_template as _rt
    # ⚠️ 给它**门店码**,不给显示串。模板里存的是编码,而 `staff.shop` 这一列存的是
    # 「SH001 静安旗舰店」这种显示串 —— **门店一改名,这个串就再也算不出码了**
    # (名字已经对不上 `shop` 表了),于是那家店的专用模板 / 试运行会**静默掉回「默认」**。
    # 码从 staff 行上取:第一阶段回填的那 5 万行就是为了这一下。取不到就退回原来的串
    # (比不上的话走默认,和改之前一样,不更差)。
    _本店 = me.get("shop") if me.get("role") != "总部运营" else None
    if _本店:
        with api._c() as _c5:
            _r5 = _c5.execute("SELECT shop_code FROM staff WHERE no=?", (me.get("no"),)).fetchone()
        _本店 = (_r5[0] if _r5 and _r5[0] else None) or _本店
    _模板 = _rt.冻结用(_本店, db=api.DB)
    kind = kind or _模板["默认期间"]
    try:
        起, 止, 名 = _wk.报告期(kind, date, TODAY)
    except ValueError as e:
        return {"error": f"{e};date 写成那一期里任意一天 `YYYY-MM-DD`,不给就是上一个完整的那一期"}
    今 = _dt.date.fromisoformat(TODAY)
    if 起 > 今:
        return {"error": f"{名}还没到(今天 {TODAY})"}
    a, b = 起.isoformat(), min(止, 今).isoformat()
    缺口 = []

    def 项(值, 出处, 口径=None, **另):
        return {"值": 值, "出处": 出处, **({"口径": 口径} if 口径 else {}), **另}

    def 万(x):
        # **换算好给出去,不让写报告那一步自己换** —— 10-09 真跑日报把 668997 元写成「669 万元」
        return None if x is None else f"{x / 10000:.1f} 万元"

    期内 = {}
    # ① 订单:四个日期列各是一份单子
    单 = {}
    for f in ("下单", "完工", "交付"):
        r = api.orders_by_date(field=f, start=a, end=b, limit=1)
        单[f] = r.get("总数") if "error" not in r else None
    期内["订单"] = 项(单, f"orders_by_date(start={a}, end={b}, field=下单/完工/交付)",
                    "单位:单(不是件)。四个日期列是四份不同的单子:同一张单可能这一期下单、下一期交付")
    # ② 销量
    r = sales_rank(start=a, end=b, limit=5)
    if "error" in r:
        缺口.append(f"销量:{r['error']}")
    else:
        期内["销量"] = 项({"合计": r["合计"], "前五(按件数)": [
                            {k: x[k] for k in ("名次", "名称", "件数", "金额")} for x in r["榜单"]],
                         "各排法的第一": r.get("各排法的第一")},
                        f"sales_rank(start={a}, end={b})", "取消 / 待付款 / 已退款不算销量;金额是订单行实收合计,不是营收")
    # ③ 营收
    r = weekly_revenue(start=a, end=b)
    if "error" in r:
        缺口.append(f"营收:{r['error']}")
    else:
        期内["营收"] = 项({k: r[k] for k in ("实收", "退款", "营收")}, f"weekly_revenue(start={a}, end={b})",
                        r["口径"], 近似=r.get("⚠️ 近似"),
                        写成万={k: 万(r[k]) for k in ("实收", "退款", "营收")})
    # ④ 进店客流 = 实际预约到店(用户 10-09 定)
    r = api.TOOLS["appt_funnel"](since=a, until=b)
    到 = next((x.get("人次") for x in r.get("漏斗") or [] if x.get("环节") == "到店"), None)
    # ⚠️ 这一期一条已到时间的预约都没有时,漏斗不给「到店」那一环、只回一句「没有已经到时间的预约」——
    # 那是**「有数据、结果是 0」**,不是「取不到」(10-09 CI 从零建库,日报那一天恰好没预约,被算成了缺口)。
    # > 「这一天没人约」和「漏斗查不了」在「没有到店那一环」上长得一模一样 —— 分开它们的是 error 字段。
    # ⚠️ 判据贴**结构**(没有 error、也没有「漏斗」这个键),不贴那句中文说明 —— 漏斗那边改一次措辞,
    # 贴文字的判法会静默把 0 算回「取不到」,而两边代码各自看都对(数据工厂 10-09 提醒)
    if 到 is None and "error" not in r and "漏斗" not in r:
        到 = 0
    elif 到 is None:
        缺口.append(f"进店客流:{r.get('error') or '预约漏斗里没找到「到店」那一环'}")
    期内["进店客流"] = 项(到, f"appt_funnel(since={a}, until={b})",
                      "用实际预约到店人数(用户 2026-10-09 定),不另造客流数据;工具注明部分关联可能高估。单位:**人次**",
                      漏斗=r.get("漏斗"), 一句话=r.get("先看这一句"))
    # ④b 到店客户数(去重,V1.1)—— 和上面同一个漏斗、同一个「到店」口径,只是按客户去重
    客 = next((x.get("客户数") for x in r.get("漏斗") or [] if x.get("环节") == "到店"), None)
    期内["到店客户数"] = 项(0 if 到 == 0 else 客, f"appt_funnel(since={a}, until={b}) 的「到店」按客户去重",
                         "单位:**人**(同一个客户这一期来几次都算 1)。**这一期重新去重** —— 不能拿日报的数加成周报")
    # ④c 售后新建 / 结案(V1.1)—— 两个数各用自己的事件时间:新建按建单日,结案按办结那天
    _店 = me.get("shop") if me.get("role") != "总部运营" else None
    _w = " AND COALESCE(a.shop, o.shop)=?" if _店 else ""
    _p = [_店] if _店 else []
    新建 = api._rows2("SELECT a.kind, COUNT(*) n FROM aftersale a LEFT JOIN ordr o ON o.id=a.order_id "
                  f"WHERE substr(a.created,1,10) BETWEEN ? AND ?{_w} GROUP BY a.kind", a, b, *_p)
    结案 = api._rows2("SELECT a.kind, COUNT(*) n FROM aftersale a LEFT JOIN ordr o ON o.id=a.order_id "
                  f"WHERE a.status IN ('已完成','已关闭','已拒绝') AND substr(a.updated,1,10) BETWEEN ? AND ?{_w} "
                  "GROUP BY a.kind", a, b, *_p)
    期内["售后"] = 项({"新建": sum(x[1] for x in 新建), "结案": sum(x[1] for x in 结案),
                      "新建按类型": {x[0]: x[1] for x in 新建}, "结案按类型": {x[0]: x[1] for x in 结案}},
                     f"aftersale(start={a}, end={b})",
                     "新建按建单日、结案按办结那天(已完成 / 已关闭 / 已拒绝,用最后更新日近似)—— 两个数**各算各的**,"
                     "不是同一批单;单位:单")
    # ⑤ 评价
    r = api.rating_overview(start=a, end=b)
    期内["评价"] = 项({k: r.get(k) for k in ("条数", "平均", "差评几条", "差评占比")},
                    f"rating_overview(start={a}, end={b})",
                    "≤3 星算差评(业务 09-27);签收当场评的,衡量交付体验,系统性偏高,不进顾问考核")
    # ⑥ 进入休眠 / 潜在流失(按最后互动推算)
    入 = {}
    for 档 in ("休眠", "潜在流失"):
        r = api.lifecycle_entered(档, start=a, end=b, shop=None if me.get("role") == "总部运营" else me.get("shop"))
        入[档] = r.get("人数") if "error" not in r else None
    期内["进入休眠"] = 项(入, f"lifecycle_entered(start={a}, end={b})",
                      "进入日 = 最后一次有效互动 + 91 / 181 天;是推算不是换档记录,回来过的人不在里面")
    # ⑦ 任务
    r = monthly_review(start=a, end=b)
    期内["任务"] = 项(r.get("任务"), f"monthly_review(start={a}, end={b})", "按截止时间归期;逾期按今天判",
                    改派=r.get("改派"))
    # ⑧ 成交率:周 = 最近 4 周滚动(用户 10-09 选);月 = 当月同期;日 = 不报
    if kind == "周":
        r = api.conversion_rate(week=a)
        期内["成交率"] = 项({"门店": r.get("门店成交率"), "怎么算": r.get("门店怎么算的"),
                          "顾问(按归因成交排)": r.get("顾问成交率(按归因成交排)")},
                         f"conversion_rate(week={a})", r.get("口径"), 偏低=r.get("⚠️ 已知偏低"))
    elif kind == "月":
        r = api.conversion_rate(mode="同期", month=a[:7])
        期内["成交率"] = 项({"门店": r.get("门店成交率"), "怎么算": r.get("门店怎么算的"),
                          "顾问": r.get("顾问成交率")}, f"conversion_rate(mode=同期, month={a[:7]})", r.get("口径"))
    # 这一种报告**结构上**取不到的项(日报的成交率):值置空、口径写理由。清单只在模块级 `报告期取不到` 写一次 ——
    # 报告模板也读它(那种报告里取不到的不许标必选,不然每一期都确认不了),两边不会对不上
    for _名, _因 in api.报告期取不到.get(kind, {}).items():
        期内[_名] = 项(None, "—", _因)

    # ── 环比(用户 2026-10-09:周报、月报比**销量和订单量**,日报先不比)
    # 上一期 = 紧挨着的上一个完整周 / 上一个自然月。比例由**程序算好**再给出去,不让写报告那一步自己除。
    # ⚠️ 本期还没过完时**不比** —— 「这个月才过 9 天」和完整的上个月比,会出一个假的下跌(V1.1 第 4.2 节:部分周期比较默认关闭)
    环比 = None
    if kind in ("周", "月"):
        if 止 > 今:
            环比 = {"说明": "本期还没过完,不和完整的上一期比(会出假的下跌)"}
        else:
            上起, 上止 = ((起 - _dt.timedelta(days=7), 止 - _dt.timedelta(days=7)) if kind == "周"
                         else _wk.月起止(起 - _dt.timedelta(days=1)))
            pa, pb = 上起.isoformat(), 上止.isoformat()
            上单 = api.orders_by_date(field="下单", start=pa, end=pb, limit=1).get("总数")
            上件 = (sales_rank(start=pa, end=pb, limit=1).get("合计") or {}).get("件数")
            本单 = 单.get("下单")
            本件 = ((期内.get("销量") or {}).get("值") or {}).get("合计", {}).get("件数")

            def 比(本, 上):
                if 本 is None or 上 is None:
                    return {"本期": 本, "上期": 上, "环比": None, "说明": "有一期取不到,不比"}
                if 上 == 0:
                    return {"本期": 本, "上期": 上, "环比": None, "说明": "上期为 0,算不出比例"}
                return {"本期": 本, "上期": 上, "环比": f"{(本 - 上) / 上 * 100:+.1f}%"}
            环比 = {"上一期": f"{pa} ~ {pb}", "订单量(下单数)": 比(本单, 上单), "销量(卖掉的件数)": 比(本件, 上件),
                    "出处": f"orders_by_date / sales_rank(start={pa}, end={pb})",
                    "口径": "环比 = (本期 − 上期) ÷ 上期;" + ("上一期 = 上一个完整周" if kind == "周" else
                                                         f"上一期 = 上个自然月(本月 {(止 - 起).days + 1} 天,"
                                                         f"上月 {(上止 - 上起).days + 1} 天,天数不同,比的是总量)")}

    # ── 必选 / 可选(用户 2026-10-09:下单数和营收必选,其余可选、默认全选)
    必选 = ("订单", "营收")
    for k, v in 期内.items():
        v["必选"] = k in 必选
    必缺 = [k for k in 必选 if k not in 期内 or 期内[k].get("值") in (None, {})
            or (k == "订单" and (期内[k]["值"] or {}).get("下单") is None)]

    # ── 存量:截至今天
    存 = {}
    r = api.TOOLS["recovery_queue"]()
    存["待付款"] = 项({"笔数": (r.get("待付款") or {}).get("笔数"), "压着的钱": (r.get("待付款") or {}).get("压着的钱")},
                    "recovery_queue()", "单位:笔 / 元", 写成万={"压着的钱": 万((r.get("待付款") or {}).get("压着的钱"))})
    存["约了没来"] = 项((r.get("预约未成行") or {}).get("合计"), "recovery_queue()",
                    "单位:人次(一条预约算一次,不是单)。已取消 / 爽约 / 已过期三种,下一步不同")
    r = api.factory_chase()
    存["该催工厂"] = 项({"单数": (r.get("该催") or {}).get("单数"), "要人看的回传": (r.get("要人看的回传") or {}).get("条数")},
                     "factory_chase()")
    r = api.TOOLS["delay_pending"]()
    存["延期没告诉顾客"] = 项(r.get("条数"), "delay_pending()")
    r = api.TOOLS["fitting_queue"]()
    存["白坯试衣"] = 项({"该试没试": (r.get("该试没试") or {}).get("件数"), "已试未签": (r.get("已试未签") or {}).get("件数"),
                       "已开裁却没试": (r.get("⚠️ 已经越过这道线的") or {}).get("件数")}, "fitting_queue()")
    r = api.TOOLS["stock_alert"]()
    存["库存"] = 项({k: (r.get(k) or {}).get("个数") for k in ("发不出", "断货", "快没了", "卖不动")}, "stock_alert()",
                  "发不出 = 在手有货但全被订单占用(最要紧);断货 = 在手和可用都是 0;快没了 = 可用 ≤ 5 件且卖得动;"
                  "卖不动 = 有货而**一件都没卖过**(不是「90 天没卖」—— 10-09 真跑时被写成了这个)。"
                  "单位:**个 SKU**(商品规格),不是件")
    r = api.TOOLS["bad_ratings"](status="待处理")
    存["差评待跟"] = 项(r.get("条数"), "bad_ratings(status=待处理)", "关单必须写处理记录")
    r = api.TOOLS["churn_watch"]()
    存["流失预警"] = 项({"该预警的": r.get("该预警的"), "按严重程度": r.get("按严重程度")}, "churn_watch()",
                     "预警不是名单 —— 要不要现在联系另看 revive_list")

    # ── 并排读时要说清的(用户 2026-10-12 试周报后定:做进取数包,不只写在规矩里)──────────
    # 规矩里写了「成交率标最近 4 周」「对不上的照抄口径解释」,真跑 4 轮只有 2 轮 / 1 轮做到 ——
    # **写在提示词里的是约定,做进数据里的才是结构**:模型照抄取数包,现成的话就漏不掉
    # ── 被报告模板隐藏的指标:**整项拿掉**(用户 10-23 选 A)—— 期内 / 存量 / 环比 / 取不到的 / 上期行动里都不留它的数,
    # 只在「报告模板」里留「隐藏的」名单。写正文的那一步**结构上**写不出它(原来只靠一句「不写进正文」的说明,是约定)。
    # 锁定必选(订单、营收)永远在 —— 模板校验不许隐藏它们,这里再兜一道。
    # 统计口径一行没动:隐藏只决定交不交出去,不决定怎么算(⚠️ 并排读那几句在这之后算,用的是拿掉之后的)
    _藏 = [k for k in _模板.get("隐藏的") or [] if k not in 必选]
    for k in _藏:
        期内.pop(k, None)
        存.pop(k, None)
    if 环比:
        for 键, 名 in api._环比指标.items():
            if 名 in _藏:
                环比.pop(键, None)
    缺口 = [x for x in 缺口 if not any(str(x).startswith(k + ":") for k in _藏)]
    并排 = []
    if "成交率" in 期内 and 期内["成交率"].get("值") is not None and kind == "周":
        并排.append("成交率是**最近 4 周滚动**算的(门店和顾问排名都是),不是这一周 —— "
                   "它旁边的「进店客流」「到店客户」是这一周的;两个窗口不同,写报告时成交率每出现一次都标「最近 4 周」")
    _单 = ((期内.get("订单") or {}).get("值") or {}).get("下单")
    _销 = (((期内.get("销量") or {}).get("值") or {}).get("合计") or {}).get("单数")
    if _单 is not None and _销 is not None and _单 != _销:
        并排.append(f"下单 {_单} 单 ≠ 销量里 {_销} 个订单:下单按下单日数单子(含待付款、取消的),"
                   f"销量不算取消 / 待付款 / 已退款 —— 两个数并排时把这句写上")
    上期行动 = _上期行动(kind, 起, me.get("shop"), 期内, 存, TODAY)
    for a in 上期行动.get("行动") or []:
        if a.get("盯的那一项") in _藏:
            a["上期的数"] = a["这期的数"] = None
            a["说明"] = "盯的这一项被报告模板隐藏了,数不给"
    return {"报告": 名, "种类": kind, "区间": f"{a} ~ {b}" + ("(这一期还没过完,截到今天)" if 止 > 今 else ""),
            "范围": me.get("shop") or "全部门店", "截至": TODAY,
            "时区": "中国时间(按演示世界的日期;用户 2026-10-09 定)",
            # 规则版本留底(V1.1):这份数是按哪一版口径取的、写报告的规矩是哪一版 —— 存进报告就冻结,
            # 三个月后规矩改了,还查得到当时是照什么写的
            "规则版本": _报告规则版本(),
            "期内": 期内, **({"环比": 环比} if 环比 else {}), "存量(截至今天)": 存, "取不到的": 缺口,
            "并排读时要说清的": 并排, "上期定的行动": 上期行动,
            "报告模板": _模板,
            # 显式列出来:回看时一项拿不到,是「总部把它隐藏了」还是「这期真没这个数」(那在「取不到的」里),
            # 对店长是两件事 —— 只删键的话两者在包里长得一模一样
            "被隐藏的": list(_藏),
            "必选指标": list(必选), "必选缺了的": 必缺,
            "能不能确认": not 必缺,
            "怎么用": "**只照这份数说**:每一项都有出处;「期内」说这一期发生了多少,「存量」说截至今天还压着多少,"
                     "两类不许混(别把存量说成本期新增)。原因、建议要标成判断,不要写成已安排。"}

def _上期行动(kind, 起, shop, 期内, 存, 今天):
    """**经营复盘的闭环**(用户 2026-10-21 拍「补最小闭环」):上一期报告确认后定下的「经营改进」行动,
    这一期回看 —— 谁负责、做完没有、盯的那一项上期多少 / 这期多少。

    ⚠️ **只摆事实,不下因果。** 「做完了」和「数变好了」同时出现,不等于是这条行动起的作用
    (季节、活动、别的行动都可能);数没变好也不等于行动没用。写报告的那一步照抄这两组数,
    原因要标成判断。所以这里**不给「有效 / 无效」这种字段** —— 给了就会被照抄成结论。
    """
    import json as _j, contextlib as _cl
    上起 = (起 - _dt.timedelta(days=7) if kind == "周" else
           _wk_月起(起) if kind == "月" else 起 - _dt.timedelta(days=1))
    with _cl.closing(api._c()) as c:
        有表 = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE name IN ('store_report_doc','report_action')")}
        if len(有表) < 2:
            return {"条数": 0, "说明": "上一期没有照报告定过行动(还没存过报告,或从没派过「经营改进」)"}
        # 按门店码筛;shop 为空就是不限门店(原来写成 `? IS NULL OR shop=?`,同一个意思)
        _片, _参 = api._门店条件(shop, c=c)
        报 = c.execute("SELECT id, shop, pack FROM store_report_doc"
                       " WHERE kind=? AND period_start=? AND status='已确认' AND rejected_at IS NULL"
                       + (f" AND {_片}" if _片 else "") + " ORDER BY revision",
                       (kind, 上起.isoformat(), *_参)).fetchall()
        出 = []
        for rid, rshop, pack in 报:
            旧 = _j.loads(pack or "{}")
            for sid, metric, st, end, who, note in c.execute(
                    """SELECT a.schedule_id, a.metric, s.status, s.end_ts,
                              COALESCE((SELECT name FROM staff WHERE no=s.assignee_no), s.assignee_no), s.note
                       FROM report_action a JOIN schedule s ON s.id=a.schedule_id
                       WHERE a.report_id=? ORDER BY a.schedule_id""", (rid,)):
                def 值(包, k):
                    for 段 in ("期内", "存量(截至今天)"):
                        if k in (包.get(段) or {}): return (包[段][k] or {}).get("值")
                    return None
                出.append({"任务": sid, "门店": rshop, "照着哪份报告": rid, "做什么": note, "负责人": who,
                          "截止": end, "状态": st,
                          # 任务做完写的是「完结」(早年造数里是「已完成」),两种都算;**取消 / 无效不算做完**
                          "做完了": st in ("完结", "已完成"),
                          "过了截止还没做完": st == "有效" and (end or "")[:10] < 今天,
                          "盯的那一项": metric, "上期的数": 值(旧, metric),
                          "这期的数": 值({"期内": 期内, "存量(截至今天)": 存}, metric)})
    if not 出:
        return {"条数": 0, "说明": f"上一期({上起.isoformat()} 起)确认过的报告里,没有定过「经营改进」行动"}
    return {"条数": len(出), "行动": 出,
            "怎么读": "只摆事实:定了什么、做完没有、盯的那一项上期 / 这期各多少。**做完了和数变了同时出现,"
                     "不等于是这条行动起的作用**(季节、活动、别的行动都可能);写报告时原因一律标成判断"}

def _wk_月起(起):
    """上一个自然月的第一天。"""
    d = 起 - _dt.timedelta(days=1)
    return d.replace(day=1)

def _报告规则版本():
    """取数口径版本 + 写报告 / 存报告那两条规矩(TL67 / TL68)正文的指纹 —— 规矩改一个字,指纹就变。"""
    import hashlib, prompts as _p
    规 = {r.id: r.text for _, r in _p.all_rules(unique=True) if r.id in ("TL67", "TL68")}
    return {"取数口径": api.报告口径版本,
            "规矩指纹": {k: hashlib.sha1(v.encode("utf-8")).hexdigest()[:10] for k, v in sorted(规.items())}}

def save_report(body=None, kind=None, date=None, report_id=None):
    """(写)**把写好的经营报告存成草稿** —— 每存一次是新的一版,保存时冻结当时的取数包。
    口径和规则在 backend/report_doc.py;这里只取身份、取数包。"""
    import report_doc as _rd
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在存 —— 请先登录")
    # trace:这一轮对话的 trace_id(sdk 经 MCP env 传进来)—— AI 管理平台从报告跳回生成它的那一轮
    return _rd.保存(me, store_report(kind=kind, date=date), body, report_id=report_id, db=api.DB,
                    trace=os.environ.get("LANXIU_TRACE") or None)

def confirm_report(report_id=None):
    """(写)**店长确认报告** —— 必选指标缺了不许确认;确认后不能改,要改再存一版。"""
    import report_doc as _rd
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在确认 —— 请先登录")
    return _rd.确认(me, (report_id or "").strip(), db=api.DB)

def get_product_images(spu):
    """按款号列商品图(只读;用户 11-11 拍:版师核料、顾问要能在聊天里看商品图)。
    图一直在系统里(backend/static/img,经 /img/<款号>-<图位>.svg 取),缺的只是这个查询口。
    每一位标明**真图**还是**会现画的示意图** —— 示意图的颜色款式是推出来的,不能当实物核料。"""
    import product_images
    k = str(spu or "").strip()
    if not k:
        return dict(error="要给款号(如 lxys_100007919);只知道名字的话先用 summarize_products 的 keyword 查款号")
    r = api._rows("SELECT spu, name FROM product WHERE spu=?", k)
    if not r:
        候 = api._rows("SELECT spu, name FROM product WHERE name LIKE ? LIMIT 5", f"%{k}%")
        return dict(error=f"没有款号 {k}", 候选=[f"{c['name']}({c['spu']})" for c in 候] or None)
    out = product_images.列图(r[0]["spu"])
    out["款名"] = r[0]["name"]
    return out

def summarize_products(spus=None, keyword=None, category=None, customer=None, limit=40):
    """**商品归纳总结**(用户 2026-10-10):给一套衣服,从颜色、纹样、面料、工艺、形制归纳规律;没有就说没有。
    三种给法:spus(款号列表,逗号分隔也行)/ keyword(商品名里含这个词)/ category(分类编码前缀);
    或者 customer:归纳这位顾客近 24 个月买过的东西(喜好)。口径在 knowledge/traits.py。"""
    import product_summary as _ps, worldclock as _wc
    c = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
    try:
        if customer:
            cid = str(customer).strip()
            人们, 并注 = api._认客户(cid)       # 软合并:副档号认成主档;已并入的同名副档不算重名
            r = [(x["id"], x["name"]) for x in 人们]
            if not r:
                return dict(error=f"没有客户 {cid}")
            if len(r) > 1:
                return dict(error=f"叫「{cid}」的不止一位,请给客户号", 候选=[x[0] for x in r])
            出 = _ps.归纳顾客(c, r[0][0], _wc.今天())
            出["归纳的是"] = f"客户 {r[0][0]} 买过的东西"
            return 出
        lim = max(3, min(int(limit or 40), 80))
        if spus:
            号 = [x.strip() for x in (spus.split(",") if isinstance(spus, str) else spus) if str(x).strip()]
        elif keyword or category:
            sql, a = "SELECT spu FROM product WHERE 1=1", []
            if keyword: sql += " AND name LIKE ?"; a.append(f"%{keyword}%")
            if category: sql += " AND category LIKE ?"; a.append(f"{category}%")
            号 = [x[0] for x in c.execute(sql + " ORDER BY spu", a)]
        else:
            return dict(error="给一套衣服:spus(款号)、keyword(名字里的词)、category(分类编码)三选一,或者 customer")
        一共 = len(号)
        号 = 号[:lim]
        出 = _ps.归纳商品(c, 号)
        出["归纳的是"] = f"{len(号)} 款商品"
        if 一共 > lim:
            出["截断"] = f"一共 {一共} 款,只归纳了前 {lim} 款 —— 结论只对这 {lim} 款成立"
        return 出
    finally:
        c.close()

def list_reports(kind=None, report_id=None, limit=20):
    """存过的经营报告:不给 report_id 就列每一期最新那一版;给了就看那一版的正文和冻结的取数包。"""
    import report_doc as _rd
    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    return _rd.取(me, report_id.strip(), db=api.DB) if report_id else _rd.列(me, kind=kind, limit=limit, db=api.DB)

def report_production(order_id=None, event=None, item=None, tracking_no=None):
    """**(写)自有工坊报工** —— 工匠报自己做的那件,店长报本店。

    业务 2026-09-25 定。1333 张定制单的生产方是自有工坊,而自有工坊没有外部系统
    会推回传 —— 得有活人报。**走的是和外发工厂完全同一个收件箱、同一套判定**:
    去重、乱序暂存、状态推进一个字都没另写。

    ⚠️ **外发工厂的单谁都不许替它报。** 工厂没回传,真相就是「工厂还没报」,
    而不是「我们知道它做完了」——替它报一条,订单往前走了,工厂那边什么都没发生。
    """
    from seed import TODAY
    import factory_inbox as _fi
    me = api.whoami()
    if not me: return {"error": "没有登录身份,不知道你是谁、能报哪些件"}
    if not order_id: return {"error": "要给订单号"}
    if event not in ("完工", "质检通过", "发出"):
        return {"error": "event 只能是 完工 / 质检通过 / 发出",
                "说明": "接单/撤回/更正/延期不是报工 —— 那几样是工厂侧的动作"}
    r = _fi.报工(order_id, event, me, 件=item, 物流单号=tracking_no, 今天=TODAY)
    return {"结论": r["结论"], "理由": r["理由"], "效果": r.get("效果"),
            "note": "报工和工厂回传走同一个收件箱 —— 被拒收/挂异常的也留着痕,"
                    "照「理由」去处理,别换个说法再报一次。"}

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

    模拟 = {r["order_id"] for r in api._rows("SELECT order_id FROM sim_batch")}
    rs = api._rows("SELECT id, source, kind, status, payable, received, refund_status, "
               "  created, paid_at, activity, customer_id FROM ordr")
    用 = [r for r in rs if include_sim or r["id"] not in 模拟]

    摊 = {}
    for r in 用:
        摊.setdefault(r["source"] or "(没记渠道)", []).append(r)

    售后 = {r["order_id"]: r["n"] for r in api._rows(
        "SELECT order_id, COUNT(*) n FROM maintain GROUP BY order_id")}

    渠道, 另列 = {}, {}
    for 名, os_ in sorted(摊.items(), key=lambda x: -len(x[1])):
        n = len(os_)
        待付 = sum(1 for x in os_ if x["status"] == "待付款")
        退 = sum(1 for x in os_ if (x["refund_status"] or "") in ("已退款", "退款中"))
        修 = sum(1 for x in os_ if x["id"] in 售后)
        实收 = sum(x["received"] or 0 for x in os_)
        成 = [x for x in os_ if x["status"] not in ("待确认", "待付款", "取消")]
        d = api._nz({
            "单量": n,
            "客单价(按实收)": (round(实收 / len(成), 2) if 成 else None),
            "实收合计": round(实收, 2),
            "待付款": _ch.比率(待付, n, "下单")[0],
            "退款(含退款中)": _ch.比率(退, n, "下单")[0],
            "有售后工单": _ch.比率(修, n, "下单")[0],
            "绑的活动": sorted({x["activity"] or "(无)" for x in os_}),
        })
        能, 为什么 = _ch.可比吗(名)
        归, 依据 = _ch.归属(名)
        if 归:
            d["获客来源归属"] = f"{归} —— {依据}"
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
    return api._nz(out)

# ── 受欢迎与易损:给版师的打版依据 ──────────────────────────────────
# 业务 2026-09-18 提的:「统计出当月最受欢迎的商品,并分析版型、花型、布料
# 对受欢迎程度的影响,给予打版师打版依据;并统计维保单,判断哪些面料、款式
# 更容易受损」。口径在 `knowledge/popularity.py`,两个参数业务 2026-09-19 拍过
# (榜给前 20 条 + 总数、易损分母下限 30)。**这里只取数、只装配,一个口径都不重算。**
#
# ⚠️⚠️ **和 `sales_rank` 的三处不同,必须写在脸上。**
# 两张都能被说成「这个月什么卖得最多」的榜,而它们答的不是同一个问题:
#
#     范围    `sales_rank` 随身份(总部全部 / 店长本店 / 顾问并集);
#             这里**全量不分店** —— 打版是中心职能。而且 `_订单范围()` 对版师
#             返回 `1=0`(刻意不兜底),**把 sales_rank 给版师只会得到一个永远空的清单**
#             —— 工坊那次 21 位师傅登录进来手上没有 `my_workorders`,同一个病
#     待付款  `sales_rank` 走 `stockalert.卖掉了()`,**不算**;
#             这里走 `popularity.算数的单()`,**算**(钱还没付,但那是一次选择),
#             并且把待付款件数**单独给出来**,让看的人自己决定要不要打折扣
#     维度    `sales_rank` 切 商品 / SKU / 品类;这里切 **形制 / 面料 / 工艺**
#             (`product_custom` 的多值列,一件商品挂多个面料,**每个都计一次**)
#
# **两张榜的总件数因此必然不一样,而这不是 bug。**
# 不把它写出来的话,版师拿到一个数、店长拿到另一个数,**两个都对**,
# 而没有任何人说得清差在哪 —— 所以两个工具的返回里都带着「另一把尺是谁」。
def _受欢迎取数(月=None):
    """受欢迎 / 易损两个工具的取数口。**全库只有这一份。**

    `backend/popularity_check.py` 的判据调的也是它 —— 原来判据自己抄了一份
    一样的 SQL。两份 SQL 会漂,而漂了之后**判据验的是它自己那一份、
    工具跑的是另一份**:绿着,却什么都没守住。

    月:`YYYY-MM`,None = 不限月份(易损率一律不限,见 `wear_risk`)。
    """
    where, a = "", []
    if 月:
        where, a = " AND substr(o.created,1,7)=?", [月]
    # ⚠️ **带上 `p.kind` 和 `p.on_shelf_at`,这两列都是后来补的,各自修掉一个假说法:**
    #   · `kind` —— 标品**本来就没有**形制 / 面料 / 工艺(那是定制品的属性组)。
    #     少了这一列的话,「标品没有面料」和「定制品漏登记面料」
    #     **在维度分布表上长得一模一样**,而两者的修法完全不同
    #     (前者什么都不用做,后者要去补 2 条)。第一版就把 138 个标品
    #     报成了「漏登记」,照着它去补齐是白费功夫。
    #   · `on_shelf_at` —— **上架日是有的**,在 `product` 上,不在 `product_custom` 上。
    #     第一版只查了 `product_custom` 就断言「库里没有上架日这一列」,
    #     于是改报「首次售出日」—— 一个凭空降级的口径。**查一张表就下的结论。**
    行 = api._rows("SELECT i.spu, i.name, i.qty, i.total, o.status, o.created,"
               "       p.kind, p.on_shelf_at"
               " FROM ordr_item i JOIN ordr o ON o.id=i.order_id"
               " LEFT JOIN product p ON p.spu=i.spu"
               " WHERE 1=1" + where, *a)
    # 商品 → 形制 / 面料 / 工艺。多值列,逗号分隔。
    维 = {}
    for r in api._rows("SELECT spu, xz, mt_opts, kf_opts FROM product_custom"):
        维[r["spu"]] = {
            "形制": [x.strip() for x in (r["xz"] or "").split(",") if x.strip()],
            "面料": [x.strip() for x in (r["mt_opts"] or "").split(",") if x.strip()],
            "工艺": [x.strip() for x in (r["kf_opts"] or "").split(",") if x.strip()],
        }
    # 维保 → spu,**经 order_item 反查,不按商品名**(名字会重、会改)
    维保行 = api._rows("SELECT i.spu FROM maintain m JOIN ordr_item i ON i.id=m.order_item_id")
    return 行, 维, 维保行

def _种下的提醒(维度词):
    """这条分析会不会正好撞在**造演示数据时种进去的规律**上。

    `fakedata/planted.py` 把每条种下的规律都登记了(种了什么、强度、在哪、
    哪种分析会看到它),而在这两个工具之前**没有任何一个分析口去问过它** ——
    登记表在,消费者是 0。

    > 一条**种下的规律**得出的结论,和一条**真的发现**,在报表上长得一模一样。

    所以这不是免责声明,是这两个工具最要紧的一个返回字段:
    「轻薄丝类最易损」在这个库上是**我们自己种的**(S1,轻薄 ×2.2),
    「这个月谁排第一」是**随机打乱出来的**(S6)。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "fakedata"))
    import planted as _pl
    return _pl.提醒(维度词)

def product_ranking(month=None, dim=None):
    """**当月最受欢迎**(只读)——给版师的打版依据:哪些商品、哪些形制 / 面料 / 工艺卖得多。

    month: `YYYY-MM`,默认**世界的当月**。dim: 形制 / 面料 / 工艺,给了就多返回一张维度分布。

    ## 为什么两张榜并列,不合成一个分数

        件数   卖出去几件    —— 打版的**工作量**跟着它走
        金额   卖出去多少钱  —— 打版的**价值**跟着它走

    一件卖 3 件的重工和一件卖 30 件的常服,按件数排是后者赢、按金额可能是前者。
    合成分数(0.6×件数 + 0.4×金额)看着高级,但**权重是谁定的没人知道**,
    而排名一旦变了,没人说得清是数据变了还是权重变了。**所以不合成。**

    ## ⚠️ 这个库上「谁排第一」是随机的

    商品热度是造数时按 `1/名次^0.9` 种进去的,**而名次是随机打乱的**
    (`fakedata/planted.py` 的 S6)。所以这张榜的**形状**(长尾)是真的,
    **第一名是谁不是** —— 返回里把这句话带出来。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import popularity as _pop

    月 = (month or "").strip() or _wc.今天().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", 月):
        return {"error": f"month 要写成 `YYYY-MM`(比如 `2026-10`),你给的是「{month}」"
                         " —— 「这个月」是哪个月**不替你猜**"}
    if dim is not None and dim not in api._受欢迎维度:
        return {"error": f"dim 只能是 {' / '.join(api._受欢迎维度)},你给的是「{dim}」",
                "note": "商品 / SKU / 品类那三种切法在 `sales_rank` 里(**那把尺不一样**,见返回里的「另一把尺」)"}

    行, 维, _ = _受欢迎取数(月)
    if not 行:
        return {"算的是": f"{月}",
                "⚠️ 这个月一条订单行都没有": "**这不是「都不受欢迎」,是没扫到东西** —— "
                                             "先确认月份对不对(世界的今天是 "
                                             f"{_wc.今天().isoformat()})",
                "订单行": 0}
    榜 = _pop.受欢迎(行)
    件榜, 金榜 = 榜["按件数"], 榜["按金额"]
    总数 = len(件榜)

    out = {
        "算的是": f"{月} · {len(行)} 条订单行 · **全量,不分门店**",
        # ⚠️ **业务 2026-09-19 拍的:给前 20 条 + 总数。**
        # 只给 20 条,看的人不知道这是全部还是冰山一角。
        f"按件数前 {_pop.榜单条数}": 件榜[:_pop.榜单条数],
        f"按金额前 {_pop.榜单条数}": 金榜[:_pop.榜单条数],
        "这个月有销量的商品一共": 总数,
        "榜上给了几条": min(_pop.榜单条数, 总数),
        "总件数": 榜["总件数"],
        "其中待付款件数": 榜["其中待付款件数"],
    }
    if 榜["总件数"]:
        占 = 榜["其中待付款件数"] / 榜["总件数"]
        out["待付款占比"] = f"{占:.1%} —— **钱还没付**。" + (
            "占比不低,要不要把它折掉由看的人定" if 占 >= 0.1 else
            "占比小,折不折掉不影响名次")
    out["两张榜为什么不合成一个分数"] = (
        "件数跟着**工作量**走、金额跟着**价值**走,是两件事。"
        "合成一个分数的话,排名变了没人说得清是数据变了还是权重变了。")

    if dim:
        取 = lambda r, d=dim: 维.get(r.get("spu"), {}).get(d, [])
        分布 = _pop.维度分布(行, 取)
        out[f"按{dim}分布"] = 分布
        合 = sum(x["件数"] for x in 分布)
        out[f"⚠️ 按{dim}各档之和 {合} 大于总件数 {榜['总件数']}"] = (
            f"**这是对的,不是算错了** —— 一件商品可以挂多个{dim}选项,"
            f"它在每个选项下都计一次。**所以不许拿这些数去算百分比占比**:"
            f"分母不是 {榜['总件数']}。")
        # ⚠️⚠️ **进不了这张分布表的商品分两种,而它们的修法完全相反。**
        #   · **标品** —— 本来就没有形制 / 面料 / 工艺这组属性(那是定制品的)。
        #     **什么都不用做**,但必须说出来:否则看的人会以为分母是全部销量。
        #   · **定制品而没登记** —— 这是真缺口,去补。
        # 第一版把两种压成一个数「138 个商品没登记面料」,
        # 而其中 136 个是标品、真缺口只有 2 个 ——
        # > **「它没有这个属性」和「它漏填了这个属性」在那张表上长得一模一样**,
        # > 而照着那个数去补齐,会去补 136 个本来就不该有这一列的商品。
        空的 = [r for r in 行 if r.get("spu") and not 取(r)]
        标品 = sorted({r["spu"] for r in 空的 if (r.get("kind") or "") == "标品"})
        定制漏 = sorted({r["spu"] for r in 空的
                        if (r.get("kind") or "") not in ("标品",)})
        if 标品:
            out[f"⚠️ 另有 {len(标品)} 个**标品**不在这张{dim}分布表里"] = (
                f"**这不是漏登记** —— 标品没有形制 / 面料 / 工艺这组属性,"
                f"它是定制品才有的。所以上面那张表的分母**不是这个月的全部销量**,"
                f"**别拿它算占比**。")
        if 定制漏:
            out[f"⚠️ 有 {len(定制漏)} 个**定制品**没登记{dim}"] = (
                f"**这是真缺口**,它们一件都没进上面那张表 —— "
                f"**「这个{dim}卖得少」和「这件定制品漏填了{dim}」"
                f"在那张表上长得一模一样**。要补的是这几个:{定制漏[:8]}")

    # ── 上架天数:**不拉平,但要报出来** ──────────────────────────
    # 新品自然卖得少。拉平(按「上架后日均」)要假设销量在生命周期里均匀,
    # 而汉服有明显的季节和节日峰(`planted` 的 S3 / S4 就是种的这个),
    # 这个假设不成立。所以不拉平,把上架天数并排放着让版师自己看:
    # 一个上架 15 天卖了 8 件的,和一个上架 200 天卖了 10 件的,**不是一回事**,
    # 而这件事只有把两个数并排放才看得出来。
    #
    # ⚠️ **算不出来的那些给 None,不给 0。** 52 个商品的 `on_shelf_at` 是空的 ——
    # 「今天刚上架」和「不知道什么时候上架的」**在一个 0 上长得一模一样**,
    # 而前者的低销量是正常的、后者根本没有依据可言。
    今 = _wc.今天()
    算不出 = []
    for 条 in 件榜[:_pop.榜单条数] + 金榜[:_pop.榜单条数]:
        d = (next((r.get("on_shelf_at") for r in 行
                   if r.get("spu") == 条["spu"] and r.get("on_shelf_at")), "") or "")[:10]
        if d:
            try:
                条["上架天数"] = (今 - _dt.date.fromisoformat(d)).days
                条["上架日"] = d
                continue
            except ValueError:
                pass
        条["上架天数"] = None
        条["⚠️ 上架天数"] = "**算不出来**(商品表的上架日是空的)—— 不是 0 天"
        算不出.append(条["spu"])
    out["为什么不按上架天数拉平"] = (
        "**不拉平是故意的。** 拉成「上架后日均」要假设销量在生命周期里均匀,"
        "而汉服有明显的季节和节日峰,这个假设不成立。所以把上架天数并排给出来 ——"
        "一个上架 15 天卖 8 件的和一个上架 200 天卖 10 件的不是一回事,"
        "**而这件事只有两个数并排放才看得出来**。")
    if 算不出:
        out[f"⚠️ 榜上有 {len(set(算不出))} 个商品算不出上架天数"] = (
            "商品表的上架日是空的 —— 给的是 **None 不是 0**:"
            "「今天刚上架」和「不知道什么时候上架」在一个 0 上长得一模一样,"
            "而前者的低销量正常、后者没有依据可言。")

    种 = _种下的提醒("受欢迎 排行 热销 " + (dim or ""))
    if 种:
        out["⚠️ 这张榜撞在种下的规律上"] = 种
    out["另一把尺"] = (
        "**`sales_rank` 也排商品,而它和这里不是同一把尺,三处不同:** "
        "① 范围 —— 它随身份(店长只看本店),这里全量;"
        "② 待付款 —— 它不算,这里算(并单独给出占比);"
        "③ 维度 —— 它切商品 / SKU / 品类,这里切形制 / 面料 / 工艺。"
        "**所以两边的总件数不一样,而两个都对** —— 报数的时候说清是哪一把。")
    out["口径说明"] = _pop.口径说明
    return api._nz(out)

def wear_risk(dim="面料"):
    """**易损分析**(只读)——哪些面料 / 形制 / 工艺更容易出维保。dim: 面料 / 形制 / 工艺。

    ## 为什么必须用率,而且必须连分母一起给

    按维保单的**绝对数**排,排出来的是**「哪个面料卖得多」** —— 卖得多自然修得多。
    而率有它自己的陷阱:**分母小的时候率会疯**。卖了 2 件修了 1 件 = 50%,
    这个数毫无意义但看起来触目惊心。所以分母低于 30(业务 2026-09-19 拍)的
    **不给结论**,给「样本不足」——
    **不给一个 0% 让人以为它不容易坏:「没有证据」和「有证据说没问题」是两回事。**

    ## ⚠️ 不接月份参数,这是故意的

    维保**发生在卖出之后**。按月切的话,分母是这个月卖的、分子是这个月修的,
    而这个月修的那些多半是**前几个月卖的** —— 率会系统性偏低,
    **而偏低的率和「这个面料确实结实」长得一模一样**。所以一律全量。

    ## ⚠️ 这个库上的易损结构是**种下去的**

    造数时按行业常识放了倍数(`fakedata/planted.py` 的 S1:轻薄 ×2.2 / 锦缎 ×1.3 /
    棉麻 ×0.45;S2:刺绣 ×1.6)。**方向有依据,大小是编的。**
    所以「轻薄丝类最易损」在这里**不是发现,是我们自己种的** —— 返回里带着这句话。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                                   "..", "knowledge"))
    import popularity as _pop

    if dim not in api._受欢迎维度:
        return {"error": f"dim 只能是 {' / '.join(api._受欢迎维度)},你给的是「{dim}」"}
    行, 维, 维保行 = _受欢迎取数(None)
    if not 行:
        return {"⚠️ 一条订单行都没有": "**这不是「都不易损」,是没扫到东西**", "订单行": 0}
    取 = lambda r, d=dim: 维.get(r.get("spu"), {}).get(d, [])
    率 = _pop.易损率(行, 维保行, 取)
    显 = _pop.差异显著吗(率)

    有 = [x for x in 率 if x["维保率"] is not None]
    out = {
        "算的是": f"全量 {len(行)} 条订单行 · {len(维保行)} 条维保单 · 按{dim}切",
        f"按{dim}的维保率": 率,
        f"有结论的 {len(有)} 档 / 样本不足的 {len(率) - len(有)} 档": (
            f"**样本不足的那些给的是「不给结论」,不是 0%** —— "
            f"销售件数低于 {_pop.易损分母下限} 件(业务 2026-09-19 从 10 提到 30)"
            f"就看不出来。它们排在最后,但**都返回,不隐藏**。"),
        "差异显不显著": 显,
    }
    if not 显.get("显著"):
        out["⚠️ 这批数据不足以支撑「某某更易损」"] = (
            "**排行榜排得出来,而第一名和最后一名的差可能只是噪声。** "
            "报一个不显著的第一名比不报更糟:不报的话版师知道自己没依据,"
            "报了他以为自己有。")
    种 = _种下的提醒(f"{dim} 易损 维保率")
    if 种:
        out["⚠️ 这个结论撞在种下的规律上"] = 种
    out["口径说明"] = _pop.口径说明
    return api._nz(out)

def return_rate(dim="品类", month=None):
    """**标品退货率**(只读)—— 哪些品类 / 商品 / 渠道退得多,退的原因是什么。口径全在 knowledge/returns.py。

    ⚠️ 全公司不分店:标品主要在官网 / 小程序 / 客服代下单,按门店切没有意义(同 product_ranking)。
    ⚠️ month 是**付款月**(按付款日分批),不是退货发生的月 —— 退货发生在付款后 4–10 天,
       按退货月切的话分子分母错位(同 wear_risk 不接月份的理由),按付款月分批就没有这个问题。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import returns as _ret

    if dim not in api._退货维度:
        return {"error": f"dim 只能是 {' / '.join(api._退货维度)},你给的是「{dim}」"}
    if month and not re.fullmatch(r"\d{4}-\d{2}", str(month)):
        return {"error": f"month 要写成 YYYY-MM(付款月),你给的是「{month}」"}
    列 = {"品类": "COALESCE(cg.name, p.category, '(没分类)')", "商品": "COALESCE(p.name, i.spu)",
          "渠道": "COALESCE(o.source, '(没填渠道)')"}[dim]
    限 = " AND substr(o.paid_at,1,7)=?" if month else ""
    a = [month] if month else []
    卖 = api._rows(f"SELECT o.paid_at 付款日, i.qty 件数, {列} 档"
               " FROM ordr_item i JOIN ordr o ON o.id=i.order_id"
               " LEFT JOIN product p ON p.spu=i.spu LEFT JOIN category cg ON cg.code=p.category"
               " WHERE o.kind='标品订单' AND o.paid_at IS NOT NULL AND o.status NOT IN ('取消','待付款')" + 限, *a)
    售 = api._rows(f"SELECT o.paid_at 付款日, a.kind, a.status, a.reason, {列} 档"
               " FROM aftersale a JOIN ordr o ON o.id=a.order_id"
               " JOIN ordr_item i ON i.id=a.order_item_id"
               " LEFT JOIN product p ON p.spu=i.spu LEFT JOIN category cg ON cg.code=p.category"
               " WHERE o.kind='标品订单' AND a.kind IN ('退货退款','换货')" + 限, *a)
    r = _ret.算(卖, 售, _wc.今天(), lambda x: x["档"])
    r.update(维度=dim, 付款月=month or "不限(全部满观察期的)", 范围="全公司标品订单(不分店)")
    if not r["全店"]["卖出件"]:
        r["说明"] = ("这个范围里**没有满观察期的标品卖出**(或者整月都还在 14 天退货期里)—— "
                   "不是退货率 0,是**没东西可算**")
    return r
