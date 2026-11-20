"""从 backend/api.py 拆出来的「api_aftersale」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api
import sqlite3, os, json, sys, re, subprocess
import datetime as _dt
import worldclock as _wc


def recovery_followup(items):
    """(写)未成交挽回清单**一键建跟进**(业务需求池 D2,用户 11-12 排到下一件)。
    items = [{号: 订单号或预约号, assignee?, end?, note?}…]:每一行给顾问派一条「电话回电」,默认派给这一单的顾问。
    逐行各自成败(每行是一位客户的一通电话);同一位客户还有没办完的电话回电就不重复派。只有店长及以上能建。
    ⚠️ 这只是**派给人去联系**,不是已经联系过客户;发短信 / 打电话仍是人的事。"""
    import alert_dispatch as AD
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在派 —— 请先登录")
    r = AD.批量挽回(items or [], me)
    if (r.get("分") or {}).get("建了"): api._agent_log(me, "RECOVERY_FOLLOWUP", r.get("reason", ""))
    return r

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
    今天 = today or _wc.今天().isoformat()
    out = {"今天": 今天, "口径": _rc.口径说明()}

    if kind in (None, "待付款"):
        rs = api._rows("SELECT o.id, o.kind, o.payable, o.created, o.source, "
                   "  o.customer_id, c.name cname, o.advisor_no "
                   "FROM ordr o LEFT JOIN customer c ON c.id=o.customer_id "
                   "WHERE o.status='待付款'")
        单 = []
        for r in rs:
            d = _rc.停留(r["created"], 今天)
            单.append(api._nz({
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
            rs = api._rows("SELECT a.id, a.customer_id, c.name cname, a.start_ts, "
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
        到店 = api._rows("SELECT COUNT(*) n FROM appointment "
                     "WHERE status IN ('已到店','已完成')")[0]["n"]
        out["预约未成行"] = api._nz({
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
    return api._nz(out)

def bad_ratings(status="待处理"):
    """**差评清单** —— 签收后顾客给了 ≤3 星、要人跟的那些。只有店长看得到。

    业务 2026-09-27:差评**自动进待处理清单**(就是 `task` 表,`type='评价差评'`),
    **归店长跟,不进顾问考核**。所以顾问这里看不到东西 ——
    给顾问看只会让他以为该自己去处理,而这件事业务明确交给店长了。
    """
    import rating as _R          # 评价口径:差评线、是差评()、这个星级能说明什么()
    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在问 —— 请先登录")
    # ⚠️ **能看的角色不在这儿手写,从写口那张表现取。**
    # 业务 2026-10-11 定了「售后确认结案」,于是售后**关得了却看不到** ——
    # 而「看不到」和「没有差评」在返回里长得一模一样(条数=0、差评=[])。
    # 手写一份清单的话,下次写口加了角色这儿不会跟着变 —— 那正是「两份名单会漂」。
    import rating_write as _rw
    能看 = tuple(dict.fromkeys(api.MANAGER_ROLES + _rw.能关差评的角色))
    if me.get("role") not in 能看:
        return dict(说明=f"差评归 {' / '.join(_rw.能关差评的角色)} 跟,你是「{me.get('role')}」,"
                        f"这里看不到东西 —— 业务 2026-09-27 + 2026-10-11",
                    条数=0, 差评=[])
    # 售后不属于某一家店(判责是工艺判断、差评跨店),所以它和总部运营一样看全量
    本店 = None if me["role"] in api.跨店角色 else me.get("shop")
    sql = ("""SELECT t.id 工单, t.status 状态, r.pkg_id 包裹, r.order_id 订单, r.star 星,
                     r.note 顾客说, r.rated_at 评于, r.star_before 原来几星,
                     r.handled_at 处理于, r.handle_note 处理记录, o.shop 门店,
                     k.name 客户, r.star_ontime 准时, r.star_fit 合身, r.star_service 导购,
                     r.star_package 包装, r.tags 标签, r.anonymous 匿名, r.followup_note 追评,
                     r.followup_at 追评于
                FROM task t JOIN rating r ON r.task_id=t.id
                LEFT JOIN ordr o ON o.id=r.order_id
                LEFT JOIN customer k ON k.id=r.customer_id
               WHERE t.type='评价差评'""" + ("" if status in (None, "全部") else " AND t.status=?"))
    a = () if status in (None, "全部") else (status,)
    rs = api._rows(sql + " ORDER BY r.rated_at DESC LIMIT 60", *a)
    if 本店: rs = [x for x in rs if x.get("门店") == 本店]
    import json as _json
    for x in rs:
        if x.get("原来几星") is not None:
            x["⚠️ 顾客改过"] = f"原来 {x['原来几星']} 星,后来改成 {x['星']} 星 —— **清单不撤**"
        # 分项 / 标签 / 追评(11-12 接):**没评的分项不出现**(没评 ≠ 0 星);标签是顾客点的原词
        分 = {k: x.pop(k) for k in ("准时", "合身", "导购", "包装")}
        分 = {k: v for k, v in 分.items() if v is not None}
        if 分: x["分项"] = 分
        try:
            if x.get("标签"): x["标签"] = _json.loads(x["标签"])
        except ValueError:
            pass
        if x.get("匿名"):
            x["匿名"] = "顾客选了匿名 —— **只对外不露名,店长照样看得到是谁**,照常跟进"
        else:
            x.pop("匿名", None)
        if x.get("追评"):
            x["追评"] = f"{x['追评']}(穿过之后说的,不带星、不改原来的星级)"
    return api._nz(dict(条数=len(rs), 按什么算差评=f"≤{_R.差评线} 星(业务 2026-09-27 定,不是常见的 ≤2)",
                    关掉要什么="**必须写处理记录** —— 「看过了」不算处理完",
                    差评=rs))

def _挡住不该给的(出, 路径="返回"):
    """**查返回的键名,不查我写了什么 SQL。**

    研判刻意不看消费总额 / 会员等级 / 身体数据(`knowledge/rating.不许出现的字段`)。
    「我没写那句 SQL」是约定 —— 换个写法(`select *`、别名、子查询)就绕过去了;
    **查键名是结构**。这个项目的凭据红线就是这么守住的(`api._rows` 查返回的列名),
    同一个手法搬过来。

    ⚠️ **抛,不静默删。** 静默删掉那一列的话,加字段的人不会收到任何信号,
    而「这一列被悄悄滤掉了」和「这一列本来就没查」在返回上长得一模一样。
    """
    import rating as _R
    if isinstance(出, dict):
        for k, v in 出.items():
            名 = str(k)
            for 禁 in _R.不许出现的字段:
                if 禁 in 名:
                    raise AssertionError(
                        f"❌ {路径}.{名} 命中刻意排除的字段「{禁}」 —— "
                        f"差评研判不许看消费总额 / 会员等级 / 身体数据"
                        f"(理由在 knowledge/rating.研判刻意不看的:"
                        f"按客户价值差别对待一旦被模型学会,**在建议文本上看不出来**)")
            _挡住不该给的(v, f"{路径}.{名}")
    elif isinstance(出, (list, tuple)):
        for i, v in enumerate(出):
            _挡住不该给的(v, f"{路径}[{i}]")
    return 出

def service_records(pkg=None, order_id=None):
    """**这一单允许查看的服务记录(只读)** —— 判差评用的第三样材料。

    方案 V2.0 的闸一要三样材料:评价本体(`bad_ratings` 有)、关联包裹/订单(同一个工具有)、
    **允许查看的服务记录** —— 这一样 2026-10-12 之前**既没有工具,也没有定义「允许」的范围**。

    给什么、为什么给,全在 `knowledge/rating.服务记录范围()`,**这儿不抄一份**。
    现在是三类(都限定在**这一张订单 / 这一个客户**):交付与签收 · 返修与售后 · 这个客户历史上的差评。

    ⚠️ **刻意不给**消费总额 / 会员等级 / 身体数据。而这一条不是靠「我没写那句 SQL」——
    返回在出门前过一道 `_挡住不该给的`,**按键名拦**,命中就当场抛。
    > 多给一个字段**不会让任何检查变红**,而「按客户价值差别对待」一旦被模型学会,
    > **在建议文本上看不出来**:同样一句「建议全额退款」,看过消费总额的那一次
    > 和没看过的长得一模一样。

    📌 **这份范围是开发按方案拟的,业务还没拍过** —— 返回里带着这句话,照着说。
    """
    import rating as _R, rating_write as _rw
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在查 —— 请先登录")
    能看 = tuple(dict.fromkeys(api.MANAGER_ROLES + _rw.能关差评的角色))
    if me.get("role") not in 能看:
        return dict(说明=f"服务记录只给 {' / '.join(能看)} 看(判差评用)—— 你是「{me.get('role')}」",
                    条数=0)
    pid = str(pkg or "").strip() or None
    oid = str(order_id or "").strip() or None
    if not pid and not oid:
        return dict(error="要给 pkg(包裹号)或 order_id(订单号)—— **不替你挑一张**")

    # `_c()` 开的是**只读**连接(`mode=ro`),row_factory 它自己设好 ——
    # 一个只读工具就该走只读连接,这样「它会不会写」不靠自觉
    with api._c() as c:
        if pid and not oid:
            r = c.execute("SELECT order_id, customer_id FROM rating WHERE pkg_id=?", (pid,)).fetchone()
            if not r:
                r = c.execute("SELECT order_id, NULL customer_id FROM pkg WHERE pkg_id=?", (pid,)).fetchone()
            if not r:
                return dict(error=f"查不到包裹 {pid} —— 是「没有这个包裹」,不是「没有服务记录」")
            oid = r["order_id"]
        单 = c.execute("SELECT id, customer_id, shop, status, created FROM ordr WHERE id=?", (oid,)).fetchone()
        if not 单:
            return dict(error=f"查不到订单 {oid} —— 是「没有这张单」,不是「没有服务记录」")
        # 店长只看本店(和 bad_ratings 同一条隔离口径);售后和总部跨店
        if me["role"] not in api.跨店角色 and (单["shop"] or "") != (me.get("shop") or ""):
            return dict(说明=f"订单 {oid} 不在你的门店 —— 和「A 顾问看不到 B 顾问的活」同一条口径",
                        条数=0)
        cid = 单["customer_id"]
        客 = c.execute("SELECT name FROM customer WHERE id=?", (cid,)).fetchone()

        包 = [dict(x) for x in c.execute(
            "SELECT pkg_id 包裹, tracking_no 物流单号, shipped_at 发出, arrived_at 到店, status 状态 "
            "FROM pkg WHERE order_id=? ORDER BY COALESCE(shipped_at,created)", (oid,))]
        签 = [dict(x) for x in c.execute(
            "SELECT arrived_at 到店, received_by 门店谁收的, mode 取件方式, forwarded_at 转寄于, "
            "fit_result 试穿结果, fit_at 试穿于, fit_verified_by 核码的人, "
            "complete_at 完成于, complete_by 完成人, ratify_note 追认理由 "
            "FROM pickup WHERE order_id=?", (oid,))]
        修 = [dict(x) for x in c.execute(
            "SELECT m.id 返修单, m.item 哪一件, m.status 状态, m.issue 客户报的问题, m.created 报于, "
            "d.liable 判给谁, d.plan 怎么修, d.fee_est 预估费用, d.customer_agreed_at 顾客同意于 "
            "FROM maintain m LEFT JOIN maintain_decision d ON d.maintain_id=m.id "
            "WHERE m.order_id=? ORDER BY m.created", (oid,))]
        售 = [dict(x) for x in c.execute(
            "SELECT id 售后单, kind 类型, status 状态, reason 原因, amount 金额, created 建于 "
            "FROM aftersale WHERE order_id=? ORDER BY created", (oid,))]
        史 = [dict(x) for x in c.execute(
            "SELECT pkg_id 包裹, order_id 订单, star 星, note 顾客说, rated_at 评于, "
            "handle_way 处理方式, handle_note 处理记录, handled_at 处理于, handle_approved_by 批准人 "
            "FROM rating WHERE customer_id=? AND star<=? ORDER BY rated_at DESC",
            (cid, _R.差评线)) ] if cid else []

    能, 不, 要紧 = _R.服务记录范围()
    出 = {
        "这一单": dict(订单=oid, 门店=单["shop"], 状态=单["status"],
                      客户=(客["name"] if 客 else None), 客户号=cid),
        "交付与签收": dict(包裹=包, 签收=签,
                          说明=("没有签收记录 —— 是「还没走到签收」,不是「签收没问题」"
                                if not 签 else None)),
        "返修与售后": dict(返修=修, 售后单=售,
                          说明=("这一单没有返修 / 售后记录"
                                if not 修 and not 售 else None),
                          判责=("⚠️ `maintain_decision` 全库 0 行 —— **判责结论这一项库里没有数据**。"
                                "「判给谁 / 花了多少」查出来是空的,那是**没录过**,不是「没有责任」"
                                if not [x for x in 修 if x.get("判给谁")] else None)),
        "这个客户历史上的差评": dict(条数=len(史), 明细=史,
                                    说明=("这个客户只有这一条差评 —— 第一次和第三次,补救力度本来就该不同"
                                          if len(史) <= 1 else None)),
        "口径": dict(能看=[f"{名}:{理由}" for 名, 理由 in 能],
                    刻意不看=[f"{名} —— {理由}" for 名, 理由 in 不],
                    要紧=要紧),
    }
    return _挡住不该给的(出)

def close_bad_rating(pkg, note, way, approved_by=None, amount=None):
    """**关掉一张差评工单(真的写进去)** —— 店长 / 售后,只能关自己看得到的那些。

    ⚠️ **2026-10-12 之前这个动作没有入口。** 写口 `rating_write.close_bad_rating`
    从写好那天起,全仓只有**它自己的检查**调它 —— 不在这张工具表里、不在页面上、
    不在模型手里。而 `bad_ratings` 的描述一直在对模型说「关掉一条必须写处理记录」,
    于是模型**被告知有这个动作、却拿不到门**。
    > **一个写口和一个没有入口的写口,在代码里长得一模一样** ——
    > 都是一个带判定、带审计、带回归测试的函数。差别只在有没有人走得到它。
    库里那 201 条「已关闭」的差评就是这么来的:**直接写的库,正门一次没走过**
    (`op_log` 里 `BAD_RATING_CLOSED` 0 条),而那批数据的处理人**全是顾问工号**
    —— 一个这个写口会当场拒掉的角色。

    way   处理方式,**只认登记过的那几种** —— 名单在 `knowledge/rating.处理方式`,
          判定在 `knowledge/rating.处理方式能不能用`。
          ⚠️⚠️ **这儿原来抄了一份五种的名单,而上一行就写着「这儿不抄」。**
          2026-10-13「免运费」进枚举那天,抄的那份没跟上 ——
          > 一条写着「我不抄」的注释,和一份真的没抄的代码,在那一行上长得一模一样。
          **所以现在这儿一个方式名都不写**:要知道有哪几种,去读那个元组。
          ⚠️ 2026-10-12 用户拍掉了「优惠券」(业务 09-24「不让价,只让东西」,
          送券是变相让价);2026-10-13 加进了「免运费」(运费表做完之后它第一次算得出金额)。
    approved_by  **出钱的那几种必须有批准人**(业务 2026-10-11「钱要出门就要两个人」),
          而且**批准人不能是处理人自己**;不出钱的那几种不要填。
          ⚠️ 原来写的是「出钱的两种 / 不出钱的三种」—— **那两个数字会跟着枚举漂**。
    amount  **这次退了多少钱**。2026-10-14 加(用户拍)。口径在
          `knowledge/rating.要填金额吗` / `这笔要谁批`,**这儿不写数字也不写角色名**:
            · 「部分退款」**必填**,而且不能超过这一单的订单额
            · 「全额退款」**不要填** —— 金额就是订单额,系统现算
            · 不出钱的那几种填了会**被拒**(填了说明理解错了,而静默忽略
              会让你以为记上了、账上却什么都没有)
          ⚠️ **超过一条线的要上升一级批**(线和角色都在 `knowledge/rating.py`:
          `退款上升一级的线` / `上升一级要谁批`)。这条线在它之前
          **早就拍过却没有落点** —— 系统只记「部分退款 / 全额退款」这个词、不记金额,
          于是判不出要谁批。**规则定了却没有字段承载它,等于没定。**
          ⚠️ 订单额和批准人角色都**从库里现读**,传进来的值不作数 ——
          一个把金额填小的请求就能绕过那条线,而记录上看起来一切正常。
    note  处理记录 —— 「看过了」不算处理完(判定在 `knowledge/rating.待办能不能关`)。

    ⚠️ **动手前先跟用户对一遍**:哪一张、怎么处理的、出不出钱、**退多少**、谁批的。
    关掉之后工单不在待处理清单里了,但**顾客那条评价不撤** ——
    撤掉就看不出「差评被处理好了」和「从来没有差评」的区别。
    """
    import rating_write as rw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在关这张差评 —— 请先登录")
    r = rw.close_bad_rating(dict(pkg=pkg, note=note, way=way,
                                 approved_by=approved_by, amount=amount), me)
    if r.get("ok"):
        api._agent_log(me, "BAD_RATING_CLOSED", r.get("reason", "") or f"{pkg} / {way}")
    return r

def rating_overview(days=30, week=None, start=None, end=None):
    """**评价概况**:最近多少天、多少条、平均几星、差评几条。只有店长看得到。

    ⚠️ **返回里必须带上「这个数不能说明什么」** —— 这不是客套话,是这个指标的性质:
    业务定了「签收当场就请评价」,于是顾客是在**店里、导购面前、衣服还没穿过**时评的。
    所以它衡量的是**交付体验**,而且**系统性偏高**。
    把它读成「衣服质量」或者「95% 的人满意」都是错的,而这种错在数字上看不出来 ——
    4.8 分长得和任何别的 4.8 分一模一样。口径在 `knowledge/rating.这个星级能说明什么()`。
    """
    import rating as _R
    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在问 —— 请先登录")
    # ⚠️ 和 `bad_ratings` 同一条口径,**从写口那张表现取**:业务 2026-10-11
    # 「售后确认结案」之后,售后要判「是不是老问题」就得看得到概况 ——
    # 原来写死 `MANAGER_ROLES`,于是它**关得了却看不到**。
    # 📌 **把售后放进来是开发定的、业务没拍过**:业务 09-27 那句「只给店长看」
    #    是在说**别进顾问考核**,没说过售后。标在这儿,免得半年后被当成业务拍的。
    import rating_write as _rw2
    if me.get("role") not in tuple(dict.fromkeys(api.MANAGER_ROLES + _rw2.能关差评的角色)):
        return dict(说明="评价概况给店长 / 售后 / 总部看(业务 2026-09-27:不进顾问考核)", 条数=0)
    # 售后不属于某一家店 —— 和总部一样看全量
    本店 = None if me["role"] in api.跨店角色 else me.get("shop")
    # `days=0` 是「只看今天」,不是「没传」—— 原来写 `int(days or 30)`,传 0 会悄悄变成 30 天
    起 = (_wc.今天() - _dt.timedelta(days=int(30 if days is None else days))).isoformat()
    止 = "9999-12-31"
    # 周报要「某一周」的评价(用户 10-09:业务周 = 周一到周日)—— 给了 week 就按那一周的起止,
    # 不再是「最近 N 天」。周的切法在 knowledge/weekly.py,这里不再写一份
    if week:
        import sys as _s, os as _o
        _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
        import weekly as _wk
        try:
            一, 日 = _wk.周起止(week)
        except ValueError:
            return dict(error=f"week 要写成那一周里任意一天 `YYYY-MM-DD`,你给的是「{week}」")
        起, 止 = 一.isoformat(), 日.isoformat()
    elif start and end:
        起, 止 = str(start)[:10], str(end)[:10]
    rs = api._rows("""SELECT r.star, r.rated_at, o.shop FROM rating r
                  LEFT JOIN ordr o ON o.id=r.order_id
                  WHERE substr(r.rated_at,1,10)>=? AND substr(r.rated_at,1,10)<=?""", 起, 止)
    if 本店: rs = [x for x in rs if x.get("shop") == 本店]
    if not rs:
        return dict(说明=(f"{起} ~ {止} 这段时间" if (week or start) else f"最近 {days} 天") + "这里没有评价记录 —— "
                        "**「没有评价」和「评价都很好」是两件事**,别当成后者", 条数=0,
                    起=起)
    星们 = [x["star"] for x in rs if x["star"] is not None]
    差 = [x for x in 星们 if _R.是差评(x)]
    能说, 不能说 = _R.这个星级能说明什么()

    # ── ⚠️ 一个整体平均答不出店长真正要问的两个问题 ────────────────────────
    # 2026-09-28 补:原来这里只返回「平均 4.4」。
    # 而 `knowledge/rating.这个星级能说明什么()` 的「能说」第二条**明写着**:
    #     「不同门店 / 不同时间段的交付体验互相比(同一个偏差,比较仍然成立)」
    # 口径承诺了能比门店、能比时间段,工具却只给一个数 ——
    # **口径说这个数能干的事,工具恰好不让干。** 这种不一致不报错:
    # 4.4 这个数字本身完全合法,只是它把 4.7 / 4.5 / 4.2 三家店压成了一个。
    #
    # 为什么「整体偏高」不影响这两个切分:当面评的偏差对三家店**同向**,
    # 比较时大部分抵掉;所以「和行业基线比」不行,「门店之间比」可以。
    # 这正是口径里那句「同一个偏差,比较仍然成立」的意思。
    def _一组(组内):
        星 = [x["star"] for x in 组内 if x["star"] is not None]
        if not 星: return dict(条数=0, 平均=None, 说明="这一组没有带星级的评价")
        坏 = [x for x in 星 if _R.是差评(x)]
        return dict(条数=len(星), 平均=round(sum(星) / len(星), 2),
                    差评几条=len(坏), 差评占比=f"{len(坏)/len(星):.0%}")

    # ⚠️ **每个分组的平均后面必须跟着条数,而且不许只报平均。**
    # 「8 条评价算出来的 4.2」和「600 条算出来的 4.2」在数字上一模一样,
    # 但前者说明不了任何事。这里不设「至少几条才报」的阈值 ——
    # 阈值得从量出来的分布定,不是我拍一个;所以改成**把条数摆在旁边**,
    # 让看的人自己看见分母。
    门店们 = sorted({(x.get("shop") or "(挂不上门店)") for x in rs})
    按门店 = {k: _一组([x for x in rs if (x.get("shop") or "(挂不上门店)") == k])
             for k in 门店们}
    月们 = sorted({str(x["rated_at"])[:7] for x in rs if x.get("rated_at")})
    按月 = {k: _一组([x for x in rs if str(x.get("rated_at"))[:7] == k]) for k in 月们}

    out = dict(起=起, 窗口=(f"{起} ~ {止}(业务周,周一到周日)" if week else f"{起} ~ {止}" if start else f"最近 {int((30 if days is None else days))} 天"), 条数=len(rs),
               平均=round(sum(星们) / len(星们), 2),
               各星几条={f"{n}星": sum(1 for x in 星们 if x == n) for n in range(5, 0, -1)},
               差评几条=len(差), 差评占比=f"{len(差)/len(星们):.0%}")

    # 店长只看得到本店,那个「按门店」就只有一行 —— 一行的分组不是分组,给句话。
    if len(门店们) > 1:
        out["按门店"] = 按门店
        高 = max(按门店.items(), key=lambda kv: kv[1]["平均"] or 0)
        低 = min(按门店.items(), key=lambda kv: kv[1]["平均"] or 9)
        out["门店最高最低"] = (f"{高[0]} {高[1]['平均']}({高[1]['条数']} 条)  vs  "
                           f"{低[0]} {低[1]['平均']}({低[1]['条数']} 条)")
    else:
        out["按门店"] = f"只看得到「{门店们[0]}」一家 —— 跨店比较要总部运营的身份"

    # ⚠️ 和 monthly_review 同一条规矩:**算不出来的时候给一句话,不给数。**
    # 窗口里不满两个自然月,「趋势」这个词就没有内容;硬报一个只有一个月的
    # 「趋势」,读的人会当成「没变化」,而真相是「这个窗口压根看不出变化」。
    if len(月们) >= 2:
        out["按月"] = 按月
        # ── ⚠️ 趋势不能拿窗口两头那两个月直接相减 ────────────────────────
        # 2026-09-28 第一次真跑就撞上:窗口 120 天从 05-31 起,于是「2026-05」
        # **只进来了一天**(7 条,平均 4.71)。拿它当起点,总部口径的趋势算出
        # **-0.08 下降**,而业务拍的形状是三个月上升 —— **趋势的符号被一个
        # 噪声点决定了**,静安同期是 +0.17。两个方向相反的答案都来自同一段数据。
        #
        # 这里不设「至少几条才算」的阈值(那个数我拍不了),改成**结构判据**:
        #   前端残月 —— 这个月的 1 号早于窗口起点 ⇒ 是窗口切出来的人工产物,剔掉
        #   当月     —— 这个月还没走完 ⇒ 不参与趋势,但**单独报**,店长要看的就是它
        # 两头剔的理由**不是同一条**:前者是「这段数据不完整且原因在我们的取数」,
        # 后者是「这段数据不完整而且还会继续长」。合成一条规则就会把当月也吞掉。
        import calendar as _cal
        def _月末(ym):
            y, m = int(ym[:4]), int(ym[5:7])
            return f"{ym}-{_cal.monthrange(y, m)[1]:02d}"
        今 = _wc.今天().isoformat()
        完整月 = [k for k in 月们 if f"{k}-01" >= 起 and _月末(k) <= 今]
        残 = [k for k in 月们 if k not in 完整月]
        if len(完整月) >= 2:
            头, 尾 = 按月[完整月[0]], 按月[完整月[-1]]
            out["趋势_只看完整月"] = (
                f"{完整月[0]} {头['平均']}({头['条数']} 条) → "
                f"{完整月[-1]} {尾['平均']}({尾['条数']} 条) "
                f"({尾['平均'] - 头['平均']:+.2f})")
        else:
            out["趋势_只看完整月"] = (
                f"窗口里只有 {len(完整月)} 个走完的自然月,**算不出趋势** —— "
                "把 days 放大(比如 120)")
        if 残:
            out["没算进趋势的月份"] = {
                k: (f"{按月[k]['条数']} 条 · 平均 {按月[k]['平均']} —— "
                    + ("**本月还没走完**,这个数还会变(要看的就是它,但别当趋势的终点)"
                       if _月末(k) > 今 else
                       f"窗口从 {起} 才开始,这个月只进来了一部分 —— **不能当趋势的起点**"))
                for k in 残}
    else:
        out["按月"] = (f"这个窗口({int((30 if days is None else days))} 天)只落在 {月们[0] if 月们 else '同一个月'},"
                     "**看不出趋势** —— 要看趋势把 days 放大(比如 120)")

    out["怎么读这份表"] = ["每个平均后面都有条数 —— **条数小的那个平均别当结论**",
                      "门店之间、月份之间可以比;和外部评分基线不能比(偏差只在内部抵掉)"]
    out["这个数能说明什么"] = 能说
    out["这个数不能说明什么"] = 不能说
    return out

def create_repair(order_id, issue, item=None):
    """**新建返修单**(真的写进去),停在「待确认」等店长判责。顾问 / 店长,本店的单。
    一张单有好几件而没说哪一件,返回「哪一件?」—— 不替用户挑。"""
    import repair_write as rw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在报修 —— 请先登录")
    r = rw.create(dict(order_id=order_id, item=item, issue=issue), me)
    if r.get("ok"): api._agent_log(me, "REPAIR_NEW", r.get("reason", ""))
    return r

def decide_repair(maintain_id, liable, plan, fee_est=None, customer_agreed=None, agree_note=None,
                  approved_by=None, approve_note=None):
    """**店长判责**(真的写进去):谁承担(顾客 / 企业)、返修还是重做;判给顾客的要录预估费用,判给企业的要填我方预估成本(决定谁有权批),
    记顾客同意要写凭据。判完了才进「待入库」。**只有店长能判**(业务 09-22)。"""
    import repair_write as rw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在判责 —— 请先登录")
    r = rw.decide(dict(maintain_id=maintain_id, liable=liable, plan=plan, fee_est=fee_est,
                       customer_agreed=customer_agreed, agree_note=agree_note,
                       approved_by=approved_by, approve_note=approve_note), me)
    if r.get("ok"): api._agent_log(me, r.get("code", "REPAIR_DECIDE"), r.get("reason", ""))
    return r

def advance_repair(maintain_id):
    """**推进返修单一档**(真的写进去):待入库 → 待处理 → 处理中 → 待签收。完成要顾客输码,这里不给。"""
    import repair_write as rw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在推进 —— 请先登录")
    r = rw.advance(dict(maintain_id=maintain_id), me)
    if r.get("ok"): api._agent_log(me, "REPAIR_STEP", r.get("reason", ""))
    return r

def verify_repair_return(maintain_id, code):
    """**返修件回店签收**(真的写进去):输入顾客给的 6 位码,通过 → 已完成。码只能是用户说出来的那一个。"""
    import repair_write as rw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在核验 —— 请先登录")
    r = rw.verify_return(dict(maintain_id=maintain_id, code=code), me)
    if r.get("ok"): api._agent_log(me, "REPAIR_DONE", r.get("reason", ""))
    return r

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
            api._rows("SELECT craft,material FROM craft_combo WHERE rule='人工确认'")}
    q = _cr.queue(top=int(top or 15), resolved=done)
    if not q:
        return {"hit": 0, "note": "队列是空的 —— 还没有人问到没依据的格子,"
                                  "或者问到的都已经核实回填了"}
    return {"hit": len(q), "rows": [api._nz(r) for r in q],
            "note": "按**被问次数**排,最常被问的最该先核。"
                    "核完一格用后台的「核实回填」写回去,那一格就从队列里消失。"
                    "**这个队列只说「谁被问了」,不说「答案是什么」** —— 答案要人去打样。"}

def get_aftersale(order_id=None, customer=None, status=None):
    """售后记录。判责依据在 kb_tables 的「售后争议判定」表里,这里只给事实。"""
    q="SELECT a.*,c.name cust FROM aftersale a LEFT JOIN customer c ON c.id=a.customer_id WHERE 1=1"
    args=[]
    if order_id: q+=" AND a.order_id=?"; args.append(order_id)
    if customer:
        人们, _ = api._认客户(customer)
        if not 人们: return {"error":f"没有客户「{customer}」"}
        ph, ids = api._在(人们[0]["关联"])          # 软合并:关联档的售后一起列
        q+=f" AND a.customer_id IN ({ph})"; args+=ids
    if status: q+=" AND a.status=?"; args.append(status)
    rs=api._rows(q+" ORDER BY a.created DESC",*args)
    if not rs:
        return {"hit":0,"note":"没有匹配的售后单。**查不到就说查不到**,不要推测客户提过什么。"}
    ext=sorted({r["ext_system"] for r in rs if r["ext_system"]})
    return {"hit":len(rs),"rows":rs,"外部系统":ext,
            "note":"判责标准见 kb_tables 的「售后争议判定」表,这里只提供事实,不下结论。",
            "⚠退款流水":"**售后退款和押金退款是两条流水,不要混。** "
                       "本系统只存押金退款的渠道明细(get_refund_trace / get_payment_flow,按押金单号查);"
                       "售后退款的渠道明细在" + ("、".join(ext) if ext else "外部系统") +
                       "里,**这里查不到,要如实告诉客户去哪查,不要拿押金流水冒充**。"}

def cancel_fee(order_id=None, material_cost=None):
    """**顾客完工前不做了,扣多少、退多少**(只读,业务 2026-10-10 晚:工钱按工单工日折钱)。

    口径在 knowledge/cancel_fee.py:已完成的工单全算、做到一半的按已过天数折(不超过工日)、没开工的不扣,
    普通 300 / 非遗级 800 元一工日;**扣的总额不超过已付**。逐道工序列明细,给顾客确认用。
    material_cost  门店按采购单核过的料的成本价 —— **只填用户说出来的数**;不给就只算工钱,并说清料费另算。
    **只算不退**:真退款走退款流程。
    """
    import sqlite3 as _sq, worldclock as _wc
    if api._GROWTH_DIR not in sys.path: sys.path.insert(0, api._GROWTH_DIR)
    import cancel_fee as _cf
    me = api.whoami()
    if not me:
        return {"error": "没有登录身份"}
    oid = (order_id or "").strip()
    o = api._rows("SELECT id, shop, status, kind FROM ordr WHERE id=?", oid)
    if not o:
        return {"error": f"没有订单 {oid}"}
    o = o[0]
    if me.get("role") != "总部运营" and o["shop"] != me.get("shop"):
        return {"error": f"这张单在「{o['shop']}」,只能看本店的"}
    if o["kind"] != "定制品订单":
        return {"error": f"订单 {oid} 是{o['kind'] or '标品订单'} —— 这里只算定制单完工前不做了扣多少;标品走退换货规则"}
    if o["status"] in ("待确认", "待付款"):
        return {"订单": oid, "现在是": o["status"], "结论": "还没确认下单 / 没付款,直接取消就行,不扣钱"}
    if o["status"] in ("取消", "已取消", "已关闭"):
        return {"订单": oid, "现在是": o["status"], "结论": "这张单已经取消了"}
    if o["status"] in ("已生产", "待发货", "已发货", "待完成", "完成", "已完成"):   # 已生产 / 待发货 = 已完工、还没交付
        return {"订单": oid, "现在是": o["status"],
                "结论": "已经完工交付,不属于「完工前不做了」—— 按确认书「已完工、交付前」那一档是全额;质量问题走返修 / 重做 / 退款"}
    料 = 0.0
    if material_cost not in (None, ""):
        try:
            料 = float(material_cost)
        except (TypeError, ValueError):
            return {"error": f"料费「{material_cost}」不是数"}
        if 料 < 0:
            return {"error": "料费不能是负数"}
    c = _sq.connect(f"file:{api.DB}?mode=ro", uri=True)
    try:
        r = _cf.从库(c, oid, _wc.今天(), 料费=料)
    finally:
        c.close()
    if r.get("error"):
        return r
    r["现在是"] = o["status"]
    r["料费说明"] = ("料费按用户给的数算" if material_cost not in (None, "") else
                 "**料费没算** —— 料的成本价由门店按采购单核,核好告诉我再算一次;现在的「扣」只是工钱")
    r["note"] = "只算不退:顾客看过逐道明细、确认了,再走退款流程。单价是成本口径,只给顾客看这张单的明细,不单独报「一工日多少钱」"
    return r

def get_maintain(maintain_id=None, customer=None, status=None):
    """售后维修工单的现场。**只给事实,判责结论要另外查判定表。**"""
    where, args = [], []
    if maintain_id: where.append("m.id=?"); args.append(maintain_id)
    if customer: where.append("(m.customer_id=? OR c.name=?)"); args += [customer, customer]
    if status: where.append("m.status=?"); args.append(status)
    rows = api._rows("SELECT m.*, c.name cname FROM maintain m "
                 "LEFT JOIN customer c ON c.id=m.customer_id"
                 + (" WHERE " + " AND ".join(where) if where else "")
                 + " ORDER BY m.created DESC", *args)
    if not rows: return {"hit": 0, "error": "查不到这样的维修工单"}
    out = []
    for m in rows[:12]:
        o = api._rows("SELECT id,kind,status,amount,created FROM ordr WHERE id=?", m["order_id"])
        it = api._rows("SELECT oi.spu, oi.name, p.remark, pc.xz, pc.mt_opts, pc.kf_opts "
                   "FROM ordr_item oi LEFT JOIN product p ON p.spu=oi.spu "
                   "LEFT JOIN product_custom pc ON pc.spu=oi.spu "
                   "WHERE oi.order_id=? AND oi.name=?", m["order_id"], m["item"])
        nt = api._rows("SELECT * FROM delivery_notice WHERE order_id=?", m["order_id"])
        # ⚠️ **量体只认这一件的下单量体,按着装人取**(业务 09-22:订单以下单量体为准)。
        # 原来按客户号数条数 —— 一家几口的尺寸全算进来,孩子的单拿着妈妈量过的条数判「记录完整」;
        # 而且下单之后又量过的也混在里面。没绑下单量体就是**判不了**,不拿别的量体顶:
        # 判责取决于「成衣和留存数据对不对得上」,拿错一次量体就是收错了人的钱。
        _it = api._rows("SELECT wearer_id FROM ordr_item WHERE id=?", m.get("order_item_id")) \
            if m.get("order_item_id") else []
        if _it and _it[0]["wearer_id"]:
            _值, _方式, _话 = api._以哪次为准(_it[0]["wearer_id"], m["order_item_id"])
        else:
            _值, _方式, _话 = {}, None, ("这张返修单**没挂到订单里的哪一件**,核对不了下单量体" if not _it
                                         else "这一件**没定给谁做**,核对不了下单量体")
        ms = [{"method": _方式}] if _方式 else []
        n_item = len(_值)
        hist = api._rows("SELECT count(*) n FROM maintain WHERE customer_id=? AND id<>?",
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
             "量体记录": api._nz({"条数": n_item, "方式": [x["method"] for x in ms],
                       # 业务 09-22:不准远程量体,判责表里「远程 → 按合同分担」那一行也删了。
                       # 这里只报「是不是都是顾问亲自量的」—— 不是的话那条记录本身就违规,要人看
                       "都是顾问亲自量的": all(x["method"] in ("到店", "上门") for x in ms) if ms else None,
                       "以哪次为准": _话,
                       # 挂到了哪一件、定了给谁做,却**没有下单量体** —— 那就是记录缺失(0 项),
                       # 按判定表「量体记录缺失」那一行走(我方:没按规矩量);**不拿别的场次顶**。
                       # 连哪一件 / 给谁做都不知道,才是真的判不了。
                       **(api._量体完整性(m["customer_id"], n_item) if (_值 or (_it and _it[0]["wearer_id"]))
                          else {"完整性": "判不了 —— " + _话})}),
             # 代码要翻成名称。原来只给「N1,N2,N3」,模型看得见却看不懂 ——
             # 它会说「需要人工查出 N1-N6 具体条目」,**而那正是它该自己拿到的东西**。
             "交付告知签收": (dict(已告知条目=[api.NOTICE_NAME.get(x, x)
                                          for x in (nt[0]["items"] or "").split(",") if x],
                             签收时间=nt[0]["signed_at"], 渠道=nt[0]["channel"]) if nt else None),
             # ⚠️ **判尺寸争议的第二张底牌,而且比量体记录硬。**
             # 量体记录说的是「我们量得对不对」,试衣签字说的是
             # 「**他本人穿过并且认可了**」—— 两句话在判责时的分量完全不同。
             "白坯试衣": api._白坯试衣(m["order_id"], m["item"],
                                   (o[0]["status"] if o else None)),
             # ── 业务 2026-09-24 加的两个事实 ──────────────────────────────
             # **实测差**:顾问量的成衣和量体的差({"腰围": 4})。超公差 → 我方免费返修,
             # 而且**这一支排在「签收已确认合身」前面**;**没量就是没量**,不填不等于在公差内。
             "实测尺寸差": json.loads(m["尺寸差"]) if m.get("尺寸差") else None,
             "公差表": {"领围": 1.0, "胸围": 1.5, "腰围": 1.5, "衣长": 2.0, "裙长": 2.0, "通袖长": 2.0},
             # **签收日期 + 今天**:证据不全时按 6 个月举证时间窗判(6 个月内默认我方)。
             # 今天用**演示世界的今天**,不用机器时钟 —— 09-23 栽过一次。
             "签收日期": api._签收日期(m["order_id"]),
             "今天": api._seed_today(),
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
