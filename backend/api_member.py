"""从 backend/api.py 拆出来的「api_member」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api
import sqlite3, os, json, sys, re, subprocess
import datetime as _dt
import worldclock as _wc


def get_lifecycle(customer=None, lifecycle=None, 范围=None):
    """查会员生命周期判定:这个客户属于哪一档、**凭什么**、有没有被人工覆盖。

    口径在 knowledge/lifecycle.py,这里只取数和包装 ——
    判定逻辑不写在工具里,否则又是一份手抄件。
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "knowledge"))
    import lifecycle as _lc
    where, args = [], []
    _并注 = None
    if customer:
        # 软合并(10-14):给的是副档号 → 认成主档;**按档统计的数(某档多少人)不在这儿动** —— 那是第 4 批,
        # 而且造数 / 统计共用的底层查询加过滤会让取行集悄悄变(intent/customer-soft-merge.md 那条坑)
        _人, _并注 = api._认客户(customer)
        if len(_人) == 1:
            where.append("id=?"); args.append(_人[0]["id"])
        else:
            where.append("(id=? OR name=?)"); args += [customer, customer]
    if lifecycle: where.append("lifecycle=?"); args.append(lifecycle)
    if not customer:
        where.append(api._人头())        # 某档多少人:按人数(已并入别人的档案不另算一个人)
        if 范围 and 范围[0]:
            where.append(范围[0]); args += 范围[1]      # 名单范围(get_member 传进来,10-26)
    sql = ("SELECT id,name,lifecycle,order_cnt,idle_days,amount_12m,orders_12m,"
           "quarters_12m,first_order,manual_lc,manual_at,last_interact FROM customer")
    if where: sql += " WHERE " + " AND ".join(where)
    # ⚠️ 2026-10-08 用户在页面上问「九月进入休眠的有多少」,模型答「休眠命中 40 个」——
    # **40 是 LIMIT,不是人数**(按库里存的档,休眠有 1395 条)。返回的 hit 原来是 len(rows),被 LIMIT 截在 40,
    # 而「截断了」和「一共就这么多」在返回里长得一模一样。总数单独数一遍,截了要明说
    总 = api._rows("SELECT COUNT(*) n FROM customer" + (" WHERE " + " AND ".join(where) if where else ""), *args)[0]["n"]
    rs = api._rows(sql + " ORDER BY id LIMIT 40", *args)
    if not rs:
        return {"hit": 0, "note": "查不到这个客户,不要凭印象回答",
                "现有档位": _lc.PRIORITY}
    out = []
    for r in rs:
        d = dict(r)
        # 天数由**这一层**算好再交给口径 —— 口径不管今天几号,
        # 否则同一批数据在不同时刻算出不同结果,真值对账没法复现。
        def _ago(iso):
            return ((_wc.今天() - _dt.date.fromisoformat(iso)).days
                    if iso else None)
        v = _lc.decide(dict(d, days_since_first_order=_ago(d.get("first_order")),
                            days_since_manual=_ago(d.get("manual_at"))))
        d.update(v)
        # 库里存的是每日重算的结果,这里是**按今天**重算的 —— 不一致要说出来,
        # 不要默默用其中一个:那说明这条记录还没被今天的重算刷过。
        if d.get("lifecycle") and d["lifecycle"] != v["生命周期"]:
            d["提醒"] = (f"库里存的是「{d['lifecycle']}」,按今天重算是「{v['生命周期']}」——"
                       "说明这条还没被今天的重算刷到,**以哪个为准要问运营**")
        out.append(api._nz(d))
    return {"hit": 总, "列出": len(out),
            **({"截断": f"一共 {总} 个,只列了前 {len(out)} 个 —— **报人数用 hit,不要数 rows**"} if 总 > len(out) else {}),
            "rows": out,
            "优先级": _lc.PRIORITY, "判定条件": _lc.RULES,
            "note": "「命中」列出全部命中的条件,「生命周期」是按优先级取的那一个。"
                    "**多条命中时要把命中列表说出来** —— 只报结论,运营无从判断算得对不对。"}

def lifecycle_entered(lifecycle, month=None, week=None, start=None, end=None, shop=None, 范围=None):
    """**某个月进入某一档的客户** —— 「九月 / 本月进入休眠的有多少」(业务 2026-10-08)。

    系统**没记换档历史**,只知道「现在在哪一档」。按无互动天数判的三档(休眠 / 潜在流失 / 流失)
    推得出来:进入那天 = 最后一次有效互动 + 91 / 181 / 366 天 —— 口径在 knowledge/lifecycle.py 的
    `进入日()`,这里只取数、按月筛。**「今天」用业务世界的今天**(seed.TODAY),还没到的那几天不算进入。
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "knowledge"))
    import lifecycle as _lc
    from seed import TODAY
    if lifecycle not in _lc.进入天数:
        return {"error": f"「{lifecycle}」推不出哪天进的 —— 只有按无互动天数判的三档能推:{list(_lc.进入天数)}。"
                         "其余几档(新客 / 高价值 / 忠诚…)系统没记换档历史,**照实说查不了,别凭印象估**"}
    今 = _dt.date.fromisoformat(TODAY)
    if start and end:
        起, 末 = _dt.date.fromisoformat(str(start)), _dt.date.fromisoformat(str(end))
        区间名, week = f"{起} ~ {末}", "区间"
        if 起 > 今:
            return {"error": f"{区间名}还没到(业务今天是 {TODAY})"}
    elif week:
        # 周报用(用户 10-09:业务周 = 周一到周日)—— 周的切法在 knowledge/weekly.py
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge"))
        import weekly as _wk
        try:
            起, 末 = _wk.周起止(week)
        except ValueError:
            return {"error": f"entered_week 要写成那一周里任意一天 `YYYY-MM-DD`,你给的是「{week}」"}
        区间名 = f"{起} ~ {末}(业务周,周一到周日)"
        if 起 > 今:
            return {"error": f"{区间名}还没到(业务今天是 {TODAY}),没有人「已经进入」"}
    else:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", str(month or "").strip())
        if not m or not 1 <= int(m.group(2)) <= 12:
            return {"error": f"entered_month 要写成 YYYY-MM(「本月」就是 {TODAY[:7]}),你给的是「{month}」",
                    "note": "**不替你解析自然语言** —— 解析错的那次,人数看起来完全正常"}
        y, mo = int(m.group(1)), int(m.group(2))
        起 = _dt.date(y, mo, 1)
        末 = _dt.date(y + (mo == 12), (mo % 12) + 1, 1) - _dt.timedelta(days=1)
        区间名 = f"{y} 年 {mo} 月"
        if 起 > 今:
            return {"error": f"{y} 年 {mo} 月还没到(业务今天是 {TODAY}),没有人「已经进入」"}
    截 = min(末, 今)
    天 = _lc.进入天数[lifecycle]
    # shop:门店报告只看本店(store_report 传进来);不给就是全部 —— 原来这里不分店,模型问本店时报的是全公司
    _片, _参 = api._门店条件(shop)      # 按门店码,不按显示串
    _范片, _范参 = (范围[0], 范围[1]) if 范围 and 范围[0] else ("", [])    # 名单范围(get_member 传进来,10-26)
    rs = api._rows("SELECT id,name,lifecycle,last_interact,idle_days FROM customer "
               "WHERE last_interact IS NOT NULL AND date(last_interact) BETWEEN ? AND ?"
               + f" AND {api._人头()}"      # 按人数,归主档所在店(10-14 拍)
               + (f" AND {_片}" if _片 else "") + (f" AND {_范片}" if _范片 else "") + " ORDER BY last_interact",
               (起 - _dt.timedelta(days=天)).isoformat(), (截 - _dt.timedelta(days=天)).isoformat(), *_参, *_范参)
    out = []
    for r in rs:
        d = dict(r)
        日 = _lc.进入日(d["last_interact"], lifecycle)       # 口径只有一份:再过一遍,不在这儿手算第二套
        if 起 <= 日 <= 截:
            d["进入日"] = 日.isoformat()
            out.append(api._nz(d))
    return {"档位": lifecycle, ("区间" if week else "月份"): 区间名,
            "按什么算": f"进入{lifecycle}那天 = 最后一次有效互动 + {天} 天(和判档的含端边界同一套)",
            "算到哪天": f"{起} ~ {截}" + (("(这一周" if week else "(这个月") + "还没过完,只算到业务今天)" if 截 < 末 else ""),
            "人数": len(out), "rows": out[:40],
            "note": ("**这是推算,不是换档记录** —— 系统没记过谁哪天换的档。推不出来的一类要照实告诉用户:"
                     "这个月进过这一档、后来又有互动回去了的人,最后互动日变了,不会出现在这里;"
                     "人工调过档的(30 天优先期)也按口径算,不看人工。")
                    + (f" rows 只列了前 40 个,人数以「人数」为准。" if len(out) > 40 else "")}

def get_member_priority(lifecycle=None, limit=10, 范围=None):
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
    sql += f" WHERE {api._人头()}"           # 按人数(10-14 拍)
    if lifecycle: sql += " AND lifecycle=?"; args.append(lifecycle)
    if 范围 and 范围[0]:
        sql += f" AND {范围[0]}"; args += 范围[1]      # 名单范围(get_member 传进来,10-26)
    rs = api._rows(sql, *args)
    if not rs:
        return {"hit": 0, "note": "这一档一个人都没有,不要凭印象回答"}
    ranked = _rfm.score(rs)[: max(1, min(int(limit or 10), 40))]
    for r in ranked: r["评分依据"] = _rfm.explain(r)
    return {"hit": len(rs), "档位": lifecycle or "全部", "rows": [api._nz(r) for r in ranked],
            "note": "**RFM 是相对分,只在这一批人内部可比** —— 不要拿两个档位的分数直接比，"
                    "也不要说「他 RFM 12 分所以是优质客户」。"
                    "排序解决的是「先打给谁」,不是「谁更值钱」。"
                    "**这是排序不是预测**,不代表联系了就能挽回。"}

def _mem():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import knowledge.member as _m
    return _m

def _levels():
    return api._rows("SELECT code,name,amount,orders,sort,need_points,note,point_rule "
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
    r = api._rows("SELECT id,name,level,amount_12m,orders_12m,paid_amount,order_cnt,points "
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
    return api._nz(out)

def points_ledger(customer_id, limit=20):
    """**积分流水和对账。**

    ⚠️ 余额是「同一个事实两个来源」:既能从 `balance` 字段读,也能从流水累加。
    **必然漂** —— 这本账修过一次(中间余额被 max(0,...) 截断过),
    修完 0 处断点。但**对账不能取消**:只要两个来源都还在,就有再漂的可能。
    所以这里照旧两个都给、照旧对账,正常情况下应该报「0 处」。
    """
    m = _mem()
    cid = (customer_id or "").strip()
    if not api._rows2("SELECT 1 FROM customer WHERE id=?", cid):
        return dict(error=f"没有客户 {cid} —— **查无此人**")
    rows = api._rows("SELECT behavior,delta,balance,reason,actor,ts FROM points_log "
                 "WHERE customer_id=? ORDER BY ts,rowid", cid)
    if not rows:
        return dict(客户=cid, 说明="这个客户没有积分流水(0 条)—— "
                                  "**不是余额为零,是一笔都没发生过**")
    bad = m.积分对账(rows)
    档案上的 = (api._rows("SELECT points FROM customer WHERE id=?", cid) or [{}])[0].get("points")
    return api._nz(dict(
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

def _单客范围(me, c):
    """看**某一个客户**的明细,这个人够不够得着 → None(能看)或拒绝的 dict。c 要有 id / shop / advisor_no。

    顾问只看自己名下的;店长看本店;总部运营看全部(用户 2026-10-26 拍「收紧,和另外两个一致」)。
    服务记录(customer_history)和会员(get_member)共用这一份 —— 原来 get_member 不判,
    别店、别人名下的客户照样给出名字、等级、积分和归属顾问(并行会话 10-26 查到)。
    **拒绝时只说客户号,不带姓名 / 门店** —— 一句「看不了」里带着名字,就已经漏了一样。"""
    if me.get("role") in api.MANAGER_ROLES:
        if me.get("role") != "总部运营" and me.get("shop") and c["shop"] != me["shop"]:
            return dict(error=f"{c['id']} 不在你的门店,看不了 —— 跨店看客户只有总部运营可以", 范围="本店")
        return None
    if (c.get("advisor_no") or "") != (me.get("no") or "?"):
        return dict(error=f"{c['id']} 不在你名下,看不了 —— **这不是他没有记录**;要看请找店长", 范围="名下")
    return None

def _名单范围(me):
    """按档**列名单 / 数人数**时,这个人能看哪一批 → (SQL 片段, 参数, 说法)。和 _单客范围 同一套口径:
    顾问 = 自己名下;店长 = 本店(按门店码,和门店报告同一个 _门店条件);总部运营 = 全公司(片段为空)。
    用户 10-26 拍「也收,和单个客户一致」—— 原来谁问都列全公司的名字和人数。
    **只在模型的工具入口(get_member)上收**;报告 / 检查 / 评测直接调底层函数时不传,口径不变。"""
    if me.get("role") in api.MANAGER_ROLES:
        if me.get("role") == "总部运营" or not me.get("shop"):
            return "", [], "全公司"
        片, 参 = api._门店条件(me["shop"])
        return 片, list(参), f"本店({me['shop']})"
    return "advisor_no=?", [me.get("no") or "?"], "你名下"

def get_member(customer=None, lifecycle=None, rank=False, limit=None, entered_month=None, entered_week=None):
    """查会员分层。**会员等级和生命周期是两套判定**,问一个客户时一次给全 ——
    原来要调两次才拼得出「这个客户值不值得跟」。

    customer → 这个人的等级档 + 生命周期档;
    lifecycle → 这一档里有哪些人;再加 rank=true → 这一档里先联系谁(RFM 排序)。
    """
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    if not customer and lifecycle:
        范围 = _名单范围(me)
        if entered_week:
            r = lifecycle_entered(lifecycle, week=entered_week, 范围=范围)
        elif entered_month:
            r = lifecycle_entered(lifecycle, entered_month, 范围=范围)
        elif rank:
            r = get_member_priority(lifecycle=lifecycle, limit=limit, 范围=范围)
        else:
            r = get_lifecycle(lifecycle=lifecycle, 范围=范围)
        # 人数和名单都只算这个人看得到的那一批 —— 回答时要说清是「你名下 / 本店」的数,不是全公司
        return {**r, "范围": 范围[2]} if isinstance(r, dict) and "error" not in r else r
    if customer:
        lc = get_lifecycle(customer=customer)
        if lc.get("error"):
            return lc
        rs = lc.get("rows") or []
        # 范围闸(10-26):先按人逐个判,够不着的**连名字都不留在返回里**(重名时 rows 里也会带别店的人)
        if rs:
            档 = {r["id"]: r for r in api._rows("SELECT id, shop, advisor_no FROM customer WHERE id IN (%s)"
                                           % ",".join("?" * len(rs)), *[r["id"] for r in rs])}
            拒们 = {r["id"]: _单客范围(me, 档.get(r["id"]) or {"id": r["id"], "shop": None, "advisor_no": None}) for r in rs}
            rs = [r for r in rs if not 拒们[r["id"]]]
            if not rs:
                拒 = next(iter(拒们.values()))
                return 拒 if len(拒们) == 1 else dict(error=f"「{customer}」命中的客户都不在你的范围里,看不了", 范围=拒["范围"])
            lc = {**lc, "rows": rs, "hit": len(rs)}
        # ⚠️ **命中一个和命中多个必须长得不一样。**
        #    按姓名查是会重名的(库里「蔡青梧」就命中 3 个)。
        #    默默取第一个的话,等级明细会安静地挂在错的人身上,
        #    而**挂对了和挂错了在返回里一模一样**。
        if len(rs) != 1:
            return {**lc, "note": (lc.get("note") or "") +
                    f" ⚠️ 这个说法命中 {len(rs)} 个客户,没法给等级明细 —— 给客户号(如 C10001)才行。"}
        _顾 = (api._rows("SELECT advisor_no FROM customer WHERE id=?", rs[0]["id"]) or [{}])[0].get("advisor_no")
        return {"客户": rs[0].get("name"), "客户号": rs[0].get("id"),
                # 归属顾问(用户 10-25 拍带名字):派回访任务时要知道派给谁 —— 那一轮模型没查到就去问用户了
                "归属顾问": ({"工号": _顾, "是谁": api._员工称呼(_顾) or "(工号在员工表里查不到)"} if _顾 else "没有归属顾问"),
                "会员等级": member_level(rs[0]["id"]),
                "生命周期": rs[0],
                "note": "会员等级看的是滚动 12 个月的钱和单数;生命周期看的是多久没来。"
                        "**两套判定各答各的**,不要互相推导。"}
    return {"error": "要么给 customer(某个人),要么给 lifecycle(某一档)"}

def conversion_rate(shop=None, mode=None, month=None, n_days=None, week=None):
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
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import sqlite3 as _sq
    口径 = _口径_linkage()
    con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True); con.row_factory = _sq.Row
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
    if week:
        # 周报:「最近 4 周滚动」(用户 2026-10-09 选)—— 截到报告周的周日、往前 28 天,同期口径。
        # 周的切法在 knowledge/weekly.py,区间成交率在 knowledge/attribution.py,这里只取数
        import seed as _seed
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge"))
        import weekly as _wk
        try:
            _一, _日 = _wk.周起止(week)
        except ValueError:
            return dict(error=f"week 要写成那一周里任意一天 `YYYY-MM-DD`,你给的是「{week}」")
        起 = (_一 - _dt.timedelta(days=21)).isoformat()
        止 = min(_日, _dt.date.fromisoformat(_seed.TODAY)).isoformat()
        店接待 = [x for x in 接待列表 if x[2] in 人 and (not 店 or 人[x[2]][1] == 店)]
        结 = _归.区间成交率(店接待, 订单列表, 起, 止)
        a, b = 结["门店"]
        return {"看的范围": 范围,
                "口径": f"最近 4 周滚动 · {起} ~ {止}(截到报告周的周日;同期口径:这 28 天里亲自接待过的客户,"
                        "这 28 天里下了定制单的算成交)",
                "门店成交率": f"{100*a/b:.0f}%" if b else "—",
                "门店怎么算的": f"{a} ÷ {b}",
                "顾问成交率(按归因成交排)": [
                    {"顾问": 人[w][0], "分母客户": n, "归因成交份额": round(x, 1),
                     "成交率": f"{100*x/n:.0f}%" if n else "—"}
                    for w, (x, n) in sorted(结["顾问"].items(), key=lambda kv: (-kv[1][0], kv[0])) if w in 人],
                "⚠️ 已知偏低": "这 28 天里接待、28 天之后才下单的,这里算没成交 —— 和月度同期口径同一个偏差;"
                               "滚动看的是趋势,不要拿它和别家的成交率比绝对值",
                "⚠️ 前提": "W 型 30/30/30/10 是惯例不是算出来的;**触点和订单都是造的数据**"}
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
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    if not customer:
        return dict(error="要给一个客户号或姓名 —— 这个工具看的是**一个人**的经过")
    import touchpoint as _tp
    import sqlite3 as _sq
    con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        # 软合并(10-14):副档号认成主档;已并入的同名副档不算重名
        cs = [dict(con.execute("SELECT id,name,shop,advisor_no FROM customer WHERE id=?", (x["id"],)).fetchone())
              for x in api._认客户(customer)[0]]
    finally:
        con.close()
    if not cs:
        return dict(error=f"没有这个客户「{customer}」—— **这是数据问题,不是他没来过**")
    if len(cs) > 1:
        # **重名的时候不给明细** —— 给错人的接触史比不给更糟
        return {"error": f"「{customer}」命中 {len(cs)} 个客户,要改用客户号",
                "候选": [{"客户号": c["id"], "门店": c["shop"]} for c in cs[:5]]}
    c0 = cs[0]
    拒 = _单客范围(me, c0)
    if 拒:
        return 拒

    旅 = _tp.客户旅程(c0["id"])
    能算, 码, 说 = _口径_journey().够不够算(旅)
    n = max(1, min(int(limit or 30), 100))
    近 = 旅[-1] if 旅 else None
    return {
        "客户": f"{c0['name']}({c0['id']})",
        "触点数": len(旅),
        # 「谁」是工号(原样留着),「是谁」是姓名和岗位(用户 10-25 拍)。⚠️ 这是**这一次的经手人**,不是归属顾问 —— 归属顾问看 get_member
        "最近一次": ({"什么时候": 近.get("时间"), "干了什么": 近.get("类型"),
                     "谁": 近.get("经手人"), "是谁": api._员工称呼(近.get("经手人")), "备注": 近.get("备注")} if 近 else None),
        "按时间": [{"时间": x.get("时间"), "类型": x.get("类型"),
                   "谁": x.get("经手人"), "是谁": api._员工称呼(x.get("经手人")), "备注": x.get("备注")} for x in 旅[:n]],
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
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import credit as _cd
    import sqlite3 as _sq
    con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        # 范围跟身份走:顾问只看自己参与的,店长看本店的人,总部看全部。
        if me.get("role") in api.MANAGER_ROLES:
            if me.get("role") != "总部运营" and me.get("shop"):
                # 按门店码筛;`staff.shop` 里有 12 个工坊名,认不出的值退回按串比
                _片, _参 = api._门店条件(me["shop"], c=con)
                人 = [r["no"] for r in con.execute(
                    f"SELECT no FROM staff WHERE {_片 or '1=0'}", tuple(_参))]
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

def revive_list(customer=None, limit=20):
    """**这些客户现在该不该联系,以及联系他说什么。**

    ⚠️ 这个工具回答的是「**为什么是他,为什么是现在**」两件事。
    只按闲置天数筛的名单,顾问拿到也不知道说什么,打过去就是尬聊 ——
    **所以没有由头的不进名单,哪怕他闲置 300 天。**

    ⚠️ **三个门槛是拍的,不是算出来的**(断节奏倍数 / 刚联系过 / 刚下过单)。
    返回值里会把它们列出来 —— **一个拍脑袋的门槛和一个有出处的门槛,
    在数字上长得一模一样**,不标出来的话下游会把它当成结论。
    """
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    # ⚠️ 10-09 运营评测 R02 真跑:顾问问「我今天该联系哪些客户」,模型把**她自己的名字**(程萦)
    # 当 customer 传进来 → 名下客户里没人叫程萦 → 合计 0 → 模型答「查不到你名下的客户」(其实该联系的有 716 个)。
    # > 一个「名下真的没有客户」和一个「把自己的名字当成了客户」,在「合计 0」上长得一模一样。
    # 所以填的是提问人自己时**明说**,不静静地返回空
    if customer and str(customer).strip() in {me.get("name"), me.get("no")} - {None, ""}:
        return dict(error=f"customer 填的是你自己({customer}),不是客户 —— "
                          "要看你名下全部该联系的客户,**不传 customer** 再调一次")
    import revive as _rv
    import sqlite3 as _sq
    today = _rv._today()
    con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        # 按人数(10-14 拍):已并入别人的档案不另算一个人;不给 customer 时才过滤(问某一个人照常认)
        where, args = ([] if customer else [api._人头()]), []
        if me.get("role") in api.MANAGER_ROLES:
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

def churn_watch(customer=None, limit=20):
    """**这些客户是不是在往下走,以及走到哪一步了。**

    ⚠️ 它回答的是「**她在不在流失**」,不是「**今天该联系谁**」——
    后者用 `revive_list`(那个看的是有没有由头)。**两个都要过**:
    预警高而没由头,该做的是**等由头**,不是硬打。

    ⚠️ **走到哪一步**和**有多可惜**是两个数,不合成一个分数 ——
    合成之后顾问就反驳不了了:他可以说「她本来就不算忠诚」推翻可惜程度,
    但推不翻「她 120 天没来」。
    """
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import slipping as _sl
    import sqlite3 as _sq
    con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        # 按人数(10-14 拍):已并入别人的档案不另算一个人;不给 customer 时才过滤(问某一个人照常认)
        where, args = ([] if customer else [api._人头()]), []
        if me.get("role") in api.MANAGER_ROLES:
            if me.get("role") != "总部运营" and me.get("shop"):
                where.append("shop = ?"); args.append(me["shop"])
            范围 = "全部门店" if me.get("role") == "总部运营" else f"{me.get('shop')}(你的门店)"
        else:
            where.append("advisor_no = ?"); args.append(me.get("no") or "?")
            范围 = "你名下的客户"
        if customer:
            where.append("(id = ? OR name = ?)"); args += [customer, customer]
        cs = {r["id"]: dict(r) for r in con.execute(
            "SELECT id,name,lifecycle FROM customer"
            + (" WHERE " + " AND ".join(where) if where else ""), args)}
        if not cs:
            return {"看的范围": 范围, "合计": 0,
                    "说明": "这个范围里没有客户"
                            + ("(或者这个客户不在你的范围里)" if customer else "")}
        历史 = _sl.查历史(list(cs), con)
    finally:
        con.close()

    预警们, 没进 = [], {}
    for cid in cs:
        hs = 历史.get(cid)
        w = _sl._口径.判(hs or [])
        if w["要不要预警"]:
            末 = hs[-1]
            预警们.append({
                "客户": cs[cid].get("name"), "客户号": cid,
                "严重程度": w["严重程度"], "要不要预警": True,
                "走到哪一步": f"{w['最好时是']} → {w['到']}(退了 {w['退了几步']} 步)",
                # ⚠️ **「曾经是」和「现在仍然是」要在这一列里就分开。**
                # 只写「忠诚、高价值」的话,顾问看不出标签还在不在 ——
                # 而他照「您以前是我们的忠诚客户」说出去就错了。
                "有多可惜": (
                    "现在仍然是 " + "、".join(w["现在还是"]) if w["现在还是"]
                    else "曾经是 " + "、".join(w["曾经是"]) + "(现在这个标签没了)"
                    if w["曾经是"] else "没有价值标签"),
                "怎么退的": ("一次判定之间就退了多步" if w["单步最大退幅"] >= 2
                            else "一步一步退下来的"),
                "为什么这么说": w["话"],
                # RFM 要的三个事实:**取她最后一条历史里的**,不现算 ——
                # 现算的是「今天」,而这条预警说的是那一条历史那一天
                "idle_days": 末["idle_days"], "orders_12m": 末["orders_12m"],
                "amount_12m": 末["amount_12m"], "id": cid,
            })
        else:
            没进[w["码"]] = 没进.get(w["码"], 0) + 1

    分组 = _sl._口径.排名(预警们)
    n = max(1, min(int(limit or 20), 100))
    剩 = n
    名单 = {}
    for 等 in ("高", "中", "低"):
        if 等 in 分组 and 剩 > 0:
            名单[等] = [{k: v for k, v in r.items()
                        if k not in ("id", "idle_days", "orders_12m",
                                     "amount_12m", "要不要预警", "R", "F", "M", "RFM")}
                       for r in 分组[等][:剩]]
            剩 -= len(名单[等])
    出 = {
        "看的范围": 范围,
        "看了几个客户": len(cs),
        # ⚠️ **这一行必须在**:没有档位历史的人,系统**说不出她在不在动** ——
        # 而「预警 0 个」会被读成「没人在流失」。
        "其中有档位历史的": len(历史),
        "没有档位历史的": len(cs) - len(历史),
        "⚠️ 没有档位历史是什么意思": (
            "**说不出她在不在动**,不是「没在流失」—— 她只有当前档位,没有第二个时间点"
            if len(cs) - len(历史) else "这个范围里每个人都有档位历史"),
        "该预警的": len(预警们),
        "按严重程度": {k: len(v) for k, v in 分组.items()},
        "名单": 名单,
        "还有": max(0, len(预警们) - sum(len(v) for v in 名单.values())),
        "没进预警的": 没进,
        "没进预警的该做什么": {c: _sl.下一步[c] for c in sorted(没进) if c in _sl.下一步},
        "⚠️ 预警不是名单": (
            "要不要**现在**联系,用 `revive_list` 另查(看有没有由头)—— "
            "预警高而没由头,该做的是等由头,不是硬打"),
        "⚠️ 排序只在同一档内部": (
            "RFM 是五分位,分数只在同一批人里可比 —— "
            "**不许拿高危的分数和低危的比大小**"),
    }
    if customer and len(cs) == 1:
        cid = next(iter(cs))
        w = _sl._口径.判(历史.get(cid) or [])
        出["这一个人"] = {
            "客户": cs[cid].get("name"), "在不在往下走": w["要不要预警"],
            "码": w["码"], "严重程度": w["严重程度"], "理由": w["话"],
            "下一步": _sl.下一步.get(w["码"], ""),
            "她最好的时候": w.get("最好时是"), "那是哪天": w.get("最好那天"),
            "曾经是": w.get("曾经是"), "现在还是": w.get("现在还是"),
        }
    return 出

def call_opportunity(customer=None, limit=20, call=None):
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
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import opportunity as _op
    import sqlite3 as _sq
    con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        # 范围跟身份走:顾问只看自己名下的客户,店长看本店,总部看全部。
        # **和 get_tasks / ownerless_list 同一套规矩**,不在这儿自己另写一份。
        where, args = [], []
        if me.get("role") in api.MANAGER_ROLES:
            if me.get("role") != "总部运营" and me.get("shop"):
                where.append("cu.shop = ?"); args.append(me["shop"])
            范围 = "全部门店" if me.get("role") == "总部运营" else f"{me.get('shop')}(你的门店)"
        else:
            where.append("cu.advisor_no = ?"); args.append(me.get("no") or "?")
            范围 = "你名下的客户"
        if customer:
            where.append("(cu.id = ? OR cu.name = ?)"); args += [customer, customer]
        if call:
            where.append("t.audio_id = ?"); args.append(call)
        rs = [dict(r) for r in con.execute(
            "SELECT t.audio_id, t.text, a.created, t.speaker_src, t.fixes, a.channel, cu.id cid, cu.name cname, cu.shop "
            "FROM call_transcript t JOIN call_audio a ON a.id = t.audio_id "
            "JOIN customer cu ON cu.id = a.customer_id"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY a.created DESC", args)]
    finally:
        con.close()
    if call:
        # 整理一通:**不调模型** —— 读原文、做研判的是调用方(技能)自己。
        # 「找不到」和「不归你看」分不开时一律说找不到范围内的,别泄露别人名下有这通
        if not rs:
            return {"看的范围": 范围, "通话": call,
                    "说明": f"你能看的范围里没有通话 {call}(通话号写错了,或者这位客户不归你看)"}
        return _整理一通(rs[0], 范围)
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

def _ko_obj():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge"))
    import oppo_obj
    return oppo_obj

def _场合词表():
    import sqlite3 as _sq
    con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True)
    try:
        return con.execute("SELECT name FROM sys_code WHERE category='场合' AND status='启用' ORDER BY code").fetchall()
    finally:
        con.close()

def _分人说明(src):
    """「声道分的」和「模型猜的」在逐字稿里长得一模一样 —— 都是「客户:……」。来路必须跟着原文走。"""
    if src == "声道":
        return "按录音声道分的(双声道:顾问、客户各一边),可信"
    if src == "模型":
        return ("**模型按内容分的**(单声道,上门 / 到店)—— 可能把顾问的话标成客户的。"
                "列诉求时在总结里写明「说话人是模型分的,请顾问核对原话是不是客户说的」")
    if src and src.startswith("未分"):
        return f"**没分出说话人**({src})—— 分不清哪句是客户说的,判不了商机,照实说"
    return "逐字稿自带说话人标注(演示数据)"

def _纠错说明(fixes):
    """原文里哪几个词是纠错改过的 —— 改过的稿和原稿长得一模一样,不说的话原话的来路就断了。"""
    if not fixes:
        return "没纠过(演示数据,或者纠错之前的老录音)"
    try:
        f = json.loads(fixes)
    except Exception:
        return "纠错记录读不出来"
    if f.get("没纠"):
        return f"纠错没跑通({f['没纠']}),原文是转写原样 —— 行业词可能是同音错字(缂丝写成克斯)"
    对 = lambda x: (x["原"], x["改"]) if isinstance(x, dict) else tuple(x[:2])
    改 = [对(x) for x in (f.get("改") or [])]
    议 = [对(x) for x in (f.get("建议") or []) if not (isinstance(x, dict) and x.get("处理"))]
    话 = []
    if 改:
        话.append("原文里这几处是按**人工核验过的词对**自动改的:" + "、".join(f"{a}→{b}" for a, b in 改))
    if 议:
        # 10-04 起没核验的只作建议、不改原文(外部审阅 §4.4,用户定)—— 原文里还是错字
        话.append("这几处**可能是同音错字、还没人核对**(原文没改):" + "、".join(f"{a}(可能是{b})" for a, b in 议)
                 + " —— 不要替顾问认定,引用原话照原文抄")
    if f.get("已恢复原稿"):
        话.append("顾问把这通恢复成了转写原稿")
    return ";".join(话) or "纠过,没有要改的"

def _整理一通(r, 范围):
    """一通通话的原料:原文、客户提到的偏好、对得上的在架商品、客户名下的方案 / 订单号。

    **只给编号和事实,不给结论**:是不是商机、下一步做什么,由读原文的那一方判。
    规则层的判断也一起给 —— 但标明它**分不出想要和随口一提**。
    """
    import opportunity as _op, opportunity_store as _st, sqlite3 as _sq
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge"))
    import oppo as _ko
    判, 码, why = _op.判断(r["text"])
    客户话 = _ko.客户说的(r["text"])
    con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True)
    try:
        提到 = []
        for 词, 维度, _ in _op.命中维度(客户话):
            货 = _st.对得上的在架(con, 维度, 词, 5)
            提到.append({"维度": 维度, "值": 词, "对得上的在架商品": [
                {"商品": spu, "名称": 名, "依据": 依} for spu, 名, 依 in 货],
                "共几款": _op.现在有货(维度, 词)})
        # **客户要的是「月白色的马面裙」,不是「月白色的」和「马面裙」各一件** ——
        # 各维度分开列,列出来的白色款全不是马面裙。所以先给几条同时对得上的
        条件 = [(x["维度"], x["值"]) for x in 提到]
        全中 = []
        if len(条件) > 1:
            for spu, 名 in con.execute("SELECT spu, name FROM product WHERE status='上架' ORDER BY spu").fetchall():
                if all(_st.满足吗(con, spu, 维, 值)[0] for 维, 值 in 条件):
                    全中.append({"商品": spu, "名称": 名})
        方案 = [{"方案": i, "状态": st} for i, st in con.execute(
            "SELECT id, status FROM scheme WHERE customer_id=? ORDER BY id", (r["cid"],))]
        订单 = [{"订单": i, "状态": st, "下单": (cr or "")[:10]} for i, st, cr in con.execute(
            "SELECT id, status, created FROM ordr WHERE customer_id=? ORDER BY created DESC LIMIT 5", (r["cid"],))]
        单数 = con.execute("SELECT COUNT(*) FROM ordr WHERE customer_id=?", (r["cid"],)).fetchone()[0]
    finally:
        con.close()
    return {
        "看的范围": 范围, "通话": r["audio_id"], "通话时间": (r.get("created") or "")[:16],
        "客户": f"{r['cname']}({r['cid']})",
        # 单列客户号(11-18):被接管的「录音跟进」工作流要 call_id + customer_id,模型手上常常只有通话号 ——
        # 夹在「姓名(号)」里它取不准,两轮评测都反问用户要客户号
        "客户号": r["cid"],
        "沟通方式": r.get("channel") or "—",
        "说话人怎么分的": _分人说明(r.get("speaker_src")),
        "同音纠错": _纠错说明(r.get("fixes")),
        "原文": r["text"],
        # 逐行编号(11-27):列诉求时**引行号**(只许引「是客户」那几行),不用再抄原话 —— 见 call-notes 技能第三步
        "逐行": _ko.逐行(r["text"]),
        "客户提到的": 提到,
        "几条全都对得上的在架商品": (全中[:5] if len(提到) > 1 else "只提到一个偏好,看上面那一栏"),
        "全都对得上的共几款": (len(全中) if len(提到) > 1 else None),
        "规则层判断": {"是商机": 判, "码": 码, "理由": why,
                     "⚠️": "规则层分不出「想要」和「随口一提」(实测约三成误报)—— 读原文自己判"},
        "这位客户名下": {"方案": 方案, "最近的订单": 订单, "订单共几张": 单数},
        "怎么用": "原话从「原文」里**客户说的那几行**逐字抄(一句话抄一句,不跨行拼、不删字);"
                 "下一步只指向这里给的编号(商品 / 方案 / 订单)。"
                 "「对得上的在架商品」每个偏好最多列 5 款,「共几款」是全部。",
        # 规矩跟着数据走:技能第一次全量真跑,模型自己发明了「气质」「风格」「活动日期」当维度 ——
        # 只写在技能说明里不够,返回值里直接给可选值
        "诉求维度只能用": list(_ko_obj().诉求维度),
        "场合只能写": [n for (n,) in _场合词表()],
    }

def ownerless_list(code=None, limit=50):
    """**谁实际上没人管** —— 归属字段非空不等于有人在管。

    口径在 `knowledge/owner.py`,取数在 `backend/ownership.py`,
    这里只做三件事:**取身份、按身份限范围、把「下一步」一起给出去**。

    ⚠️ **这个工具一行都不写。** 业务定的边界:agent 只给参谋。
    「这个客户的归属顾问已离职」是一个事实,摆出来;改不改是店长的动作 ——
    他可能想等交接、想指给特定的人,也可能这个客户马上要复购不宜此时换人。
    """
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import ownership as _own
    # 2026-09-21:**顾问也能看了,看的是自己名下那一份**。
    # 原来只给店长和总部 —— 而「我名下的客户有没有问题」是顾问天天要问的。
    全部 = _own.明细(查经手=True)
    # 范围跟身份走:顾问看自己名下的,店长看本店,总部看全部。
    if me.get("role") in api.MANAGER_ROLES:
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
    if me.get("role") in api.MANAGER_ROLES:
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
