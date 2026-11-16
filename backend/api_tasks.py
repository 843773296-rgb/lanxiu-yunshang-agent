"""从 backend/api.py 拆出来的「api_tasks」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api
import worldclock as _wc


def my_tasks(status=None):
    """看**我的任务**。顾问只看得到派给自己的,店长看本店全部。

    **A 顾问不会在这里看到 B 顾问的活** —— 隔离在查询层,不在界面上。
    范围由 tasks.visible_scope 一处判定,所有读任务的地方都走它。
    """
    import tasks as _tk, tasktypes as tt
    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在问 —— 请先登录")
    d = _tk.my_tasks(me, status)
    if d.get("error"): return d
    out = [api._nz({"任务号": r["id"], "类型": tt.norm(r.get("type")),
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
    return api._nz(dict(我是=f"{me['name']}·{me['role']}", 范围=d["scope"],
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
    me = api.whoami()
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
        return api._nz({"任务号": r["id"], "类型": tt.norm(r.get("type")), "状态": r.get("status"),
                    "内容": r.get("note"), "结束": r.get("end_ts"),
                    "挂的单据": r.get("ref_id"), "客户": r.get("customer_id")})

    out = []
    for k, v in sorted(by.items(), key=lambda kv: -len([x for x in kv[1] if x.get("status") == "有效"])):
        live = [x for x in v if x.get("status") == "有效"]
        out.append(api._nz({"顾问": k, "在办": len(live), "全部": len(v),
                        "最近到期": min([x.get("end_ts") for x in live if x.get("end_ts")], default=None),
                        # **每人只列在办的**,历史记录列出来会把清单撑爆,
                        # 而撑爆之后就得截断,截断是静默的。
                        "在办明细": [one(x) for x in live]}))
    idle = [p["name"] for p in _tk.my_staff(me) if p["name"] not in by] if         me.get("role") in _tk.MANAGER_ROLES else []
    return api._nz(dict(范围=d["scope"], 人数=len(out), 团队=out,
                    手上没活的=idle or None,
                    待分配=len([r for r in rs if not r.get("assignee_no") and r.get("status") == "有效"]) or None))

def week_grid(start=None, days=7):
    """**一周的排班格子**:每个顾问哪天什么时段已经占了、哪些时段空着。

    排班之前必须先看这个 —— 不看就排,排出来的东西**和正常任务长得一模一样**,
    直到那天两个人同时约在一个时段。

    返回按人 × 天的占用情况,以及每天没人覆盖的营业时段。
    """
    import datetime, tasks as _tk
    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在排 —— 请先登录")
    if me.get("role") not in _tk.MANAGER_ROLES:
        return dict(error=f"排班是店长的活,你是「{me.get('role')}」。"
                          f"你自己的日程用 my_tasks 看")
    try:
        d0 = (datetime.date.fromisoformat(start) if start else _wc.今天())
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
        people.append(api._nz({"顾问": p["name"], "工号": p["no"],
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
    return api._nz(dict(区间=f"{d0} 起 {days} 天", 营业时间=f"{OPEN_H}:00–{CLOSE_H}:00",
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
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在排 —— 请先登录")
    if me.get("role") not in tasks.MANAGER_ROLES:
        return dict(error=f"排班须由店长及以上操作,你是「{me.get('role')}」")
    r = tasks.assign_batch(items, me)
    if r.get("ok"): api._agent_log(me, "BATCH", r.get("reason", ""))
    return r

def dispatch_batch(items):
    """**一次把待分配池里的几条单分出去**(真的写进去)。全过才写,一条不过整批不写。

    items:[{task_id, assignee?}]。不给 assignee 就采纳 dispatch_pool 里那条建议。
    「把待分配的都派了」用这个 —— assign_batch 是**新建**任务的,派不了已存在的单。
    """
    import tasks
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在分 —— 请先登录")
    if me.get("role") not in tasks.MANAGER_ROLES:
        return dict(error=f"分派须由店长及以上操作,你是「{me.get('role')}」")
    r = tasks.dispatch_batch(items, me)
    if r.get("ok"): api._agent_log(me, "BATCH_DISPATCH", r.get("reason", ""))
    return r

def my_workorders(status=None):
    """**我手上的工单** —— 工匠看自己的,工坊管事看本坊,总部看全部。

    带在制上限(`wip_limit`)和当前在制数:**接不接得下一件,这两个数说了算**,
    不用猜。逾期的排在最前。
    """
    import tasks as _tk
    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    where, args, scope = _tk.visible_wo_scope(me)
    sql = (f"SELECT w.*, a.name aname, a.trade, a.wip_limit, a.workshop "
           f"FROM workorder w LEFT JOIN artisan a ON a.no=w.artisan WHERE {where}")
    if status: sql += " AND w.status=?"; args = args + [status.strip()]
    rows = api._rows(sql + " ORDER BY w.due_date", *args)
    if not rows:
        return api._nz(dict(范围=scope, 说明="这个范围里没有工单" +
                        (f"(状态={status})" if status else "")))
    today = _wc.今天().isoformat()
    逾期 = [r for r in rows if (r.get("due_date") or "9999") < today
            and r.get("status") in ("在制", "待开工")]
    在制 = [r for r in rows if r.get("status") == "在制"]
    out = dict(
        范围=scope, 工单数=len(rows),
        先看这几件=(f"**{len(逾期)} 条逾期**" if 逾期 else "没有逾期"),
        在制=len(在制),
        清单=[api._nz(dict(工单=r["id"], 工序=r.get("craft"), 订单=r.get("ref"),
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
    return api._nz(out)

def get_task(task_id):
    """看**一条任务**的详情。看不到别人的 —— 知道单号也看不到。

    单条查询最容易漏掉隔离:列表过滤了,详情按 id 直接取,
    于是知道单号就能看别人的活。这个洞不会报错,只会安静地漏。
    """
    import tasks as _tk, tasktypes as tt
    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在问 —— 请先登录")
    r = _tk.get_task((task_id or "").strip(), me)
    if not r:
        return dict(error=f"没有 {task_id} 这条任务,或者它不在你看得到的范围里")
    return api._nz({"任务号": r["id"], "类型": tt.norm(r.get("type")), "状态": r.get("status"),
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
    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在问 —— 请先登录")
    if me.get("role") not in api.MANAGER_ROLES:
        return dict(说明="待分配由店长处理,你是顾问,这里看不到东西", 条数=0, 任务=[])
    import booking
    rs = booking.unassigned(None if me["role"] == "总部运营" else me.get("shop"))
    out = []
    for r in rs:
        sg = r.get("建议")
        out.append(api._nz({"任务号": r["id"], "客户": r.get("customer_name"),
                        "类型": r.get("type"), "开始": r.get("start_ts"),
                        "内容": r.get("note"),
                        "为什么没自动派": (f"档案里的归属顾问是「{r.get('bind')}」,"
                                          f"但他已离职或不在本店" if r.get("bind")
                                          else "这个客户没有归属顾问"),
                        "建议人选": (sg or {}).get("name"),
                        "建议工号": (sg or {}).get("no"),
                        "建议依据": (sg or {}).get("why") or ([r.get("提不出的原因")] if r.get("提不出的原因") else None),
                        "备选": [f"{a['name']}(在办 {a['load']})" for a in (sg or {}).get("alts", [])]}))
    return dict(条数=len(out), 说明="**建议不是决定** —— 要店长确认才算派出去", 待分配=out)

def assign_task(type, assignee, note, end, start=None, ref_id=None, activity_code=None, metric=None):
    """**派一条任务**(真的写进去)。只有店长及以上能派,只能派给本店在职顾问。

    type 见 task_types();ref_id 填什么由类型决定
    (客户相关填客户号;订单跟踪填订单号;维保填维保单号;售后填售后单号;
    经营改进填报告号、并用 metric 点名盯报告里的哪一项;团建培训和日常运维不填)。
    assignee 写工号或姓名。时间 `YYYY-MM-DD HH:MM`。

    **动手之前先跟用户把人、时间、内容对一遍** —— 派错了和派对了在库里长得
    一模一样,等发现的时候顾问已经去做了。
    """
    import tasks
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在派 —— 请先登录")
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
    r = tasks.assign_task(api._nz(dict(type=type, assignee_no=hit[0]["no"], note=note, end=end,
                                   start=start, ref_id=ref_id, activity_code=activity_code, metric=metric)), me)
    if r.get("ok"): api._agent_log(me, "ASSIGN", r.get("reason", ""))
    return r

def dispatch_task(task_id, assignee=None):
    """**把待分配池里的单分出去**(真的写进去)。不给 assignee 就采纳 agent 自己的建议。

    只能分**还没派出去的**单 —— 已经派给别人的要改派,那是另一个动作:
    悄悄换掉负责人会让原来那个人的列表凭空少一行。
    """
    import tasks, booking
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在分 —— 请先登录")
    # **权限先判,再解析人名。** 反过来的话,顾问调这个会收到
    # 「找不到周叙」—— 而真因是「你没这个权限」。
    # 顾问看到「找不到」会去核对名字拼写,那条路是死的。
    # **错误信息要指向原因,不是指向症状。**
    if me.get("role") not in tasks.MANAGER_ROLES:
        return dict(error=f"这个动作须由店长及以上操作,你是「{me.get('role')}」")
    to = (assignee or "").strip()
    if not to:
        t = api._rows("SELECT * FROM schedule WHERE id=?", (task_id or "").strip())
        if not t: return dict(error=f"没有任务 {task_id}")
        sg, 为什么 = booking.suggest_why(t[0])
        if not sg:
            # 原因要照实说:「排班没发布」「那个时段没人在班」和「店里没顾问」下一步完全不同(11-11 夜)
            return dict(error=f"提不出建议:{为什么} —— **硬凑一个人出来比说「提不出」有害得多**;"
                              f"要派的话请点名派给谁")
        to = sg["no"]
    else:
        pool = tasks.my_staff(me)
        hit = [p for p in pool if p["no"] == to] or [p for p in pool if p["name"] == to]
        if len(hit) != 1:
            return dict(error=f"找不到「{to}」或有重名",
                        可派的人=[f"{p['name']}({p['no']})" for p in pool])
        to = hit[0]["no"]
    r = tasks.dispatch(dict(id=task_id, assignee_no=to), me)
    if r.get("ok"):
        api._agent_log(me, "DISPATCH", r.get("reason", ""))
        if assignee:
            # 手动指定放行(用户 11-11 夜:排班没发布时不出推荐,店长可手动指定),但不在班要说一声
            try:
                import roster as _R
                t = api._rows("SELECT start_ts,end_ts FROM schedule WHERE id=?", (task_id or "").strip())
                if t and t[0].get("start_ts"):
                    ok, _, why = _R.时段在班(to, t[0]["start_ts"], t[0].get("end_ts") or t[0]["start_ts"])
                    if not ok:
                        r["排班提醒"] = f"派是派了,但按排班 {why}"
            except Exception:       # noqa: BLE001 —— 提醒取不到不影响已经派出去的单
                pass
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
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在改派 —— 请先登录")
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
    if r.get("ok"): api._agent_log(me, "REASSIGN", r.get("reason", ""))
    return r

def finish_task(task_id, summary, conclusion=None):
    """**把任务标记完成**(真的写进去)。日程总结必填。

    **只能完成派给自己的** —— 谁做的谁点完成,别人代点等于台账上写了
    一件没发生的事。需要现场照的类型(上门沟通/团建培训/日常运维/维保/售后)
    要先在页面上传照片,这里传不了图。
    """
    import tasks
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁 —— 请先登录")
    r = tasks.finish_task(dict(id=task_id, summary=summary, conclusion=conclusion), me)
    if r.get("ok"): api._agent_log(me, "FINISH", r.get("reason", ""))
    return r

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
