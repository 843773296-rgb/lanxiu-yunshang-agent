"""从 backend/api.py 拆出来的「api_order」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api
import sqlite3, os, json, sys, re, subprocess
import datetime as _dt
import worldclock as _wc


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

    me = api.whoami()
    if not me: return dict(error="不知道现在是谁在看 —— 请先登录")
    cid = (customer_id or "").strip()
    if not api._rows2("SELECT 1 FROM customer WHERE id=?", cid):
        return dict(error=f"没有客户 {cid} —— **查无此人**,不是「这人不能下单」")
    today = _wc.今天().isoformat()

    if not og.需要量体吗(kind):
        k, why = og.能不能下单(kind, None, None, None)
        return api._nz(dict(结论=k, 理由=why, 订单类型=kind))

    ws = api._rows("SELECT id,name,gender,birthday FROM wearer "
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
        return api._nz(dict(结论=k, 理由=why, 订单类型=kind,
                        名下有谁=[f"{x['name']}({x['id']})" for x in ws] or None,
                        怎么办=("把 wearer_id 一起传进来再问一次。"
                               "**别让我替你挑** —— 定制是照着尺寸裁的")
                        if ws else "这个客户名下没有在用的着装人,先建档"))

    m = api._rows("SELECT measured_at,tpl FROM measure_rec WHERE wearer_id=? "
              "AND measured_at<=? ORDER BY measured_at DESC LIMIT 1", w["id"], today + " 23:59")
    last = m[0]["measured_at"] if m else None
    exp = None
    if last and w["birthday"] and w["gender"]:
        try:
            exp = gr.measure_expired(w["gender"], w["birthday"], last[:10], today)
        except Exception:
            exp = None
    k, why = og.能不能下单(kind, w["name"], last, exp)
    return api._nz(dict(
        结论=k, 理由=why, 订单类型=kind,
        着装人=f"{w['name']}({w['id']})",
        最近量体=last,
        复量口径=(f"{exp['已过天数']}/{exp['允许天数']} 天 · {exp['原因']}") if exp else None,
        名下有谁=[f"{x['name']}({x['id']})" for x in ws] if len(ws) > 1 else None,
        提醒=("「有个旧尺寸总比没有强」正是返工的来源 —— "
              "超期就要求复量,别将就") if k == "不可以" else None))

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

    scope: 不传给**概览**(四档的个数 + 每档最急的 5 个);传「发不出」「断货」「快没了」「卖不动」只要一档,明细给前 30。
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
    日 = [x["created"][:10] for x in api._rows(
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
    逐日 = {}          # sku → {日期: 件数} —— 补货点要日销量的波动,压货要最后一次卖出是哪天
    for r in api._rows("SELECT i.sku, i.qty, o.status, o.refund_status, substr(o.created,1,10) d "
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
        if r["d"]:
            dd = 逐日.setdefault(r["sku"], {})
            dd[r["d"]] = dd.get(r["d"], 0) + (r["qty"] or 0)
    卖过 = {k: tuple(v) for k, v in 卖过.items()}
    # 交期取这个 SKU 的供应商登记的天数 —— 不写死;没登记的,补货点就明说算不出
    交期 = {r["code"]: r["lead_days"] for r in api._rows(
        "SELECT s.code, sp.lead_days FROM sku s LEFT JOIN supplier sp ON sp.code=s.supplier_code")}

    rs = api._rows("SELECT s.code, s.spu, s.spec, s.color, s.size, s.price, "
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
        # 补货点:窗口里每天卖了几件(没卖的天记 0,要算进波动)
        补, 补说 = None, None
        if 窗 and 窗起:
            d0 = _dt.date.fromisoformat(窗起[:10])
            dd = 逐日.get(r["code"], {})
            序 = [dd.get((d0 + _dt.timedelta(days=k)).isoformat(), 0) for k in range(窗)]
            补, 补说 = _sa.补货点(序, 交期.get(r["code"]))
        # 压货:从**数据的最后一天**往回数多少天没卖出过一件(从没卖过的,从上架日算)
        末 = max(逐日.get(r["code"], {}) or [None]) if 逐日.get(r["code"]) else (r["shelf"] or "")[:10]
        没卖 = ((_dt.date.fromisoformat(止) - _dt.date.fromisoformat(末)).days
                if (末 and 止 and 末 <= 止) else None)
        压, 压说 = _sa.压货(没卖) if _sa.可用(r["stock"], r["locked"]) > 0 else (None, None)
        摊.setdefault(档位, []).append(api._nz({
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
            "补货点": 补 if 补 is not None else 补说,
            "补货点怎么算的": 补说 if 补 is not None else None,
            "该补了": (("是 —— 可用 {} 件 ≤ 补货点 {} 件".format(_sa.可用(r["stock"], r["locked"]), 补))
                      if (补 is not None and _sa.可用(r["stock"], r["locked"]) <= 补) else None),
            "压货": 压, "压货说明": 压说,
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
                  "**该不该补看补货点**(见「到了补货点的」那一栏,可用件数多于 5 的也在里面)。",
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

    # 不传 scope = **概览**:每档只列最急的 5 个(用户 2026-10-25 拍)。原来四档各 30 条全给,约 6 万字,
    # 超过 SDK 单次返回上限 —— 每轮先撞一次「exceeds maximum allowed tokens」,模型再一档一档重取(那轮多调了 3 次)。
    # 要整档清单就传 scope,照旧给前 30。**个数**扫的是全部 SKU,不受明细条数影响。
    列 = 30 if scope in 摊 else 5
    for k in 要哪些:
        lst = sorted(摊.get(k, []), key=_排)
        out[k] = api._nz({
            "个数": len(lst),
            "是什么": 档说明.get(k),
            "明细": lst[:列],
            **({f"（只列了前 {列} 个）": f"共 {len(lst)} 个"
                + ("" if scope in 摊 else f";要这一档的完整清单(前 30)传 scope=「{k}」")} if len(lst) > 列 else {}),
        })

    # ⚠️ 原来这里**固定**输出一句「为什么没有可售天数 —— 是装饰不是指标」,写于全库只有 71 个 SKU
    # 各卖 1 件的时候。数据长到一整年之后它还在说,**而同一个工具已经在给出可售天数了**。
    # 改成按现状说:算得出多少、算不出的为什么。**一句写死的结论,会比它描述的数据活得久。**
    out["可售天数算得出多少"] = (
        f"{能算}/{len(rs) - 停用} 个 SKU 算得出(统计区间 {跨天} 天,每个 SKU 按**自己上架后**那段算)。"
        "其余的**算不出**:一件没卖过、或只卖过一笔 —— 一笔画不出速度,照实说算不出,不凑数。")
    到点 = [x for k in 摊 for x in 摊[k] if x.get("该补了")]
    out["到了补货点的"] = api._nz({
        "个数": len(到点),
        "是什么": (f"可用 ≤ 补货点。补货点 = 交期内平均销量 + 安全库存(缺货容忍 {_sa.服务水平:.0%},"
                  f"{_sa.服务水平_来源});交期取供应商登记的天数。"
                  "**它回答「什么时候该补」,补多少件仍是采购的决定。**"),
        "明细": sorted(到点, key=lambda x: (x["可用"] - x["补货点"]))[:列],
        **({f"（只列了前 {列} 个）": f"共 {len(到点)} 个"} if len(到点) > 列 else {}),
    })
    压 = {}
    for k in 摊:
        for x in 摊[k]:
            if x.get("压货"):
                压.setdefault(x["压货"], []).append(x)
    out["压货"] = api._nz({
        "是什么": "按多少天没卖出过一件分档(" + " / ".join(f"≥{d} 天{n}" for d, n in _sa.压货档) +
                  f";{_sa.压货档_来源})。天数从数据的最后一天往回数。**只提醒,不自动改价。**",
        "怎么处理": "**业务还没定**(清仓能不能打折、谁来决定处理方式 —— 问题列在 15-电商运营.md 第三节)。"
                    "不许建议打折:「不让价」业务 09-24 定过,标品线是不是例外还没定",
        **{n: f"{len(压.get(n, []))} 个" + (":" + "、".join(f"{x['商品']}({x['规格']})" for x in 压[n][:5])
                                           + (f" ……还有 {len(压[n]) - 5} 个" if len(压[n]) > 5 else "")
                                           if 压.get(n) else "")
           for _, n in _sa.压货档},
    })
    out["口径出处"] = ("缺货容忍、压货档是业务 09-29 拍的,唯一来源是 15-电商运营.md 第一节"
                       "(kb_read 15 可读);那一篇第二节是行业做法(参考,不是我们的规矩)")
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
    out["⚠️ 补多少件不归这个工具"] = (
        "补货点回答「什么时候该补」;**补多少件、找谁补是采购的决定**,这里不给订货量。")
    out["面料不在这儿"] = ("这个工具只看成品 SKU。面料库存(135 种,4 种没现货)"
                          "影响的是**定制品工期**,是另一摊。")
    return api._nz(out)

def record_fitting(order_id, item, adjust="", signed=False, round=None, note=""):
    """**登记一轮白坯试衣**(真的写进去)。顾问 / 店长,只能登记本店订单。

    陪同人就是登录的人 —— **不收工号参数**,收了就能替别人登记一次自己没陪的试衣。
    `round` 不给是新的一轮;给已有轮次且 signed=True 是**补签**(签字不许撤销)。

    ⚠️ **动手之前先跟用户对一遍**:哪张单、哪一件、改了哪几处、客户签没签。
    签字是责任转移点 —— 记成「签了」而客户其实没签,出尺寸争议时门店会拿着一张不存在的底牌。
    """
    import fitting_write as fw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在登记 —— 请先登录")
    r = fw.record(dict(order_id=order_id, item=item, adjust=adjust, signed=signed,
                       round=round, note=note), me)
    if r.get("ok"): api._agent_log(me, r.get("code", "FIT"), r.get("reason", ""))
    return r

def record_pickup(order_id, action, mode=None, tracking_no=None, issue=None,
                  matches_record=None, other_defect=None, our_fault=None, pkg=None, item=None):
    """**交付签收的三个动作**(真的写进去):到店代收 / 取件方式 / 不合身。顾问 / 店长,只能动本店的单。

    action  「到店代收」—— 工厂发到店,这一单到了(只认已发货的定制单)
            「取件方式」—— mode = 到店取 / 转寄;转寄要 tracking_no(物流单号)
            「不合身」  —— 顾客试了某一件不合身,**那一件不算签收**,留店转返修;issue 写清哪里不合身。
                          item 指哪一件(包裹里不止一件时必须给,不替用户挑)。
                          matches_record / other_defect / our_fault 是**查出来的事实**,不知道就别填 ——
                          填了会影响判责建议,而建议最后由人确认
    """
    import pickup_write as pw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在操作 —— 请先登录")
    d = dict(order_id=order_id, mode=mode, tracking_no=tracking_no, issue=issue,
             matches_record=matches_record, other_defect=other_defect, our_fault=our_fault,
             pkg=pkg, item=item)
    fn = {"到店代收": pw.arrive, "取件方式": pw.set_mode, "不合身": pw.not_fit}.get((action or "").strip())
    if not fn:
        return dict(ok=False, code="BAD_ACTION", reason="action 只认「到店代收 / 取件方式 / 不合身」")
    r = fn(d, me)
    if r.get("ok"): api._agent_log(me, r.get("code", "PICKUP"), r.get("reason", ""))
    return r

def verify_fit_code(order_id, code, pkg=None):
    """**核验顾客给的 6 位码 = 签收**(真的写进去):订单「已发货 → 待完成」。顾问 / 店长,本店的单。

    码是顾客在手机上点「试穿合身」拿到的,**只能是顾客给的、用户说出来的那一个** —— 不许编、不许猜。
    """
    import pickup_write as pw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在核验 —— 请先登录")
    r = pw.verify(dict(order_id=order_id, code=code, pkg=pkg), me)
    if r.get("ok"): api._agent_log(me, "SIGN", r.get("reason", ""))
    return r

def ratify_complete(order_id, reason):
    """**顾问追认完成**(真的写进去):签收满 15 天顾客还没确认,写理由把「待完成」推成「完成」。"""
    import pickup_write as pw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在追认 —— 请先登录")
    r = pw.ratify(dict(order_id=order_id, reason=reason), me)
    if r.get("ok"): api._agent_log(me, "RATIFY", r.get("reason", ""))
    return r

def start_cutting(order_id):
    """**开裁**:把一张定制单从「待生产」推进到「生产中」(真的写进去)。只有版师能开。

    **过不了白坯试衣那道闸就拒绝**(业务 09-22):单里有一件该试没试、试了没签字、
    或判不了该不该试而又没试过,整单不许裁。拒绝时会列出是哪几件、缺什么。

    ⚠️ **动手之前先跟用户确认单号** —— 开裁不可逆,裁下去就没有回头路。
    """
    import fitting_write as fw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在开裁 —— 请先登录")
    r = fw.start_cutting(dict(order_id=order_id), me)
    if r.get("ok"): api._agent_log(me, "CUT", r.get("reason", ""))
    return r

def open_order(customer_id, items, delivery=None, scheme_id=None):
    """**开一张定制单**(真的写进去),停在「待确认」。顾问 / 店长,只给本店客户开。

    items  [{"spu" 或 "sku": ..., "wearer_id": 给谁做, "qty": 件数}] —— 每一件都要指明给谁做,
           下单量体量的必须是穿这件的人(业务 09-22)。
    开完**还没生效**:下一步给每一件量下单量体并绑上(record_measure 带 order_id + item),再 confirm_order。
    delivery  配送到店(默认,不收运费)/ 配送到客户(按客户省份查运费表;算不出来就不开单)。
    scheme_id 照着哪套方案开的(可选):给了就挂上,之后按方案查得到这张单;方案得是这位客户的、已保存或已锁定。
    ⚠️ 动手前先跟用户对一遍:哪位客户、哪几件、每件给谁做、到店取还是寄到家。
    """
    import order_write as ow
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在开单 —— 请先登录")
    r = ow.open_order(dict(customer_id=customer_id, items=items, delivery=delivery, scheme_id=scheme_id), me)
    if r.get("ok"): api._agent_log(me, "OPEN", r.get("reason", ""))
    return r

def confirm_order(order_id, no7day_ack=False):
    """**确认下单**(真的写进去):待确认 → 待审核。定制单确认即已付款(业务 09-22)。

    no7day_ack  顾客本人已单独确认「本单定制品不适用七天无理由退货」(业务 10-10 晚)——
                不默认、只认 true;没确认就拒绝,时间和账号写进订单确认书。

    **逐件过闸**:每一件都要有绑在它上面的、开单之后量的、够做这件衣服的下单量体;
    有一件不过整单拒绝,返回里列出是哪几件、缺什么。
    ⚠️ 动手前先跟用户确认单号 —— 确认之后就进审核、算已付款。
    """
    import order_write as ow
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在确认 —— 请先登录")
    r = ow.confirm_order(dict(order_id=order_id, no7day_ack=no7day_ack), me)
    if r.get("ok"): api._agent_log(me, "CONFIRM", r.get("reason", ""))
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
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在录 —— 请先登录")
    r = mw.record(dict(wearer_id=wearer_id, values=values, method=method, inner=inner, shoe=shoe,
                       breath=breath, order_id=order_id, item=item), me)
    if r.get("ok"): api._agent_log(me, "MEASURE", r.get("reason", ""))
    return r

def get_order(order_id=None, customer=None):
    """订单全链路。**金额勾稽当场自检**,对不上的直接在返回里标出来 ——
    藏着不说,顾问就会拿一个错的数字去跟客户对账。"""
    if not (order_id or customer):
        return {"error": "要么给订单号,要么给客户号/姓名"}
    if customer and not order_id:
        人们, 并注 = api._认客户(customer)
        if not 人们: return {"error":f"没有客户「{customer}」"}
        人 = 人们[0]
        ph, ids = api._在(人["关联"])
        # 软合并(10-14):关联档的订单一起列,每一单带着它挂在哪条档案上 —— **不相加成一个总额**
        rs=api._rows("SELECT id,customer_id 档案,kind,status,prd_status,amount,received,refund_status,created"
                 f" FROM ordr WHERE customer_id IN ({ph}) ORDER BY created DESC",*ids)
        d={"客户":人["name"],"hit":len(rs),"orders":rs,
           "note":"这是该客户的订单清单;要看某一单的明细,拿 id 再调一次。"}
        if len(人["关联"])>1:
            d["关联档案"]=人["关联"]
            d["⚠合并"]=(并注 or f"{人['id']} 名下并入了 {'、'.join(人['关联'][1:])}(同一个人)")+ \
                       " —— 清单里每单的「档案」列写着它原来挂在哪条档案上;**金额别替他加总**,积分 / 等级各档案各算"
        return d
    o=api._rows("SELECT * FROM ordr WHERE id=?",order_id)
    if not o: return {"error":f"没有订单 {order_id}"}
    o=o[0]
    cu=api._rows("SELECT name,phone FROM customer WHERE id=?",o["customer_id"])
    # **这一单是从哪条方案来的。** 顾问问「这单当初定的是什么工艺」时,
    # 答案在方案上,不在订单行上 —— 订单行只有 SKU 和金额。
    _sc = api._rows("SELECT * FROM scheme WHERE id=?", o.get("scheme_id")) \
        if o.get("scheme_id") else []
    if _sc:
        with api._c() as _cc:
            o["来自方案"] = api._scheme_ref.展开(_cc, _sc[0])
    elif o.get("kind") == "定制品订单":
        # **定制单没挂方案,是一条要报出来的事,不是沉默。**
        # 这类单的配置只存在于订单行和人的记忆里,查不到当初为什么这么定。
        o["来自方案"] = None
        o["方案缺口"] = "这是定制单,但没有关联方案 —— 当初的配置依据查不到"
    items=api._rows("SELECT sku,name,tag,price,qty,spu,base_amount,custom_amount,total"
                " FROM ordr_item WHERE order_id=?",order_id)
    af=api._rows("SELECT id,kind,status,reason,amount,created FROM aftersale WHERE order_id=?",order_id)
    # 勾稽自检
    bad=[]
    g,f,a=o["goods_amount"] or 0,o["freight"] or 0,o["amount"] or 0
    # ⚠️ **定制单的订单额 = 商品额(基础款价)+ 定制加价 + 运费**,定制加价记在订单行的 custom_amount 上。
    # 原来只比「商品额 + 运费 = 订单额」,于是 **3542 张定制单张张报「勾稽异常」** —— 2026-09-22 签收评测里
    # 模型读到这句就停下来让店长先核金额,正常的到店代收、转寄都做不下去。标品没有定制加价,式子不变。
    cu_=round(sum(x["custom_amount"] or 0 for x in items),2)
    if abs(g+cu_+f-a)>0.01:
        bad.append(f"商品额 {g} + 定制加价 {cu_} + 运费 {f} ≠ 订单额 {a}" if cu_ else f"商品额 {g} + 运费 {f} ≠ 订单额 {a}")
    it=round(sum(x["total"] or 0 for x in items),2)
    if items and abs(it-(g+cu_))>0.01: bad.append(f"订单行合计 {it} ≠ 商品额 {g}" + (f" + 定制加价 {cu_}" if cu_ else ""))
    if (o["received"] or 0)>(o["payable"] or 0)+0.01:
        bad.append(f"已收 {o['received']} > 应付 {o['payable']}")
    tl=[(k,o[k]) for k in ("created","paid_at","audit_at","produced_at","shipped_at",
                           "finished_at","cancelled_at") if o[k]]
    for (k1,v1),(k2,v2) in zip(tl,tl[1:]):
        if v2<v1: bad.append(f"时间倒挂:{k2}({v2}) 早于 {k1}({v1})")
    return {"订单":o["id"],"客户":(cu[0]["name"] if cu else o["customer_id"]),
            "类型":o["kind"],"页面状态":o["status"],"PRD状态":o["prd_status"],
            "状态口径":"页面按设计稿 10 档,PRD 按状态机 6 档,两套并存且有显式映射",
            **({"状态说明": api._定制状态说明[o["status"]]}
               if o["kind"] == "定制品订单" and o["status"] in api._定制状态说明 else {}),
            "门店":o["shop"],"顾问工号":o["advisor_no"],"来源":o["source"],"配送":o["delivery"],
            "金额":dict(商品额=g,运费=f,订单额=a,应付=o["payable"],已收=o["received"],
                       退款状态=o["refund_status"]),
            "时间线":dict(tl),"订单行":items,"售后":af,
            # ⚠️ 这个 return **重新拼了一个 dict**,往 `o` 上挂字段是挂不进来的 ——
            # 写成功了、也不报错,只是没人看得见。第一版就是这么丢掉的。
            "来自方案":o.get("来自方案"),
            **({"方案缺口": o["方案缺口"]} if o.get("方案缺口") else {}),
            "勾稽异常":bad,
            # 生产 / 发货只认工厂回传(业务 09-22)—— 回传了什么、收没收、被拒的为什么,一并带出来
            **({"工厂回传": _工厂回传(o["id"])} if o["kind"]=="定制品订单" else {}),
            "note":("勾稽有异常,**先核对再答复客户**" if bad else "金额与时间线勾稽一致")}

def _工厂回传(oid):
    """回传记录 + **按演示世界的今天算好的进度**。
    09-22 评测:这里原来只给记录,模型拿机器的真实日期去算「晚了多久」,说成「过期一个月」(实际 3 天)——
    **日期差由这里算好给它,不让它自己拿今天去减。**"""
    import factory_inbox as _fi, factory_feed as _K, datetime as _d
    from seed import TODAY
    记 = _fi.回传记录(oid, db=api.DB)
    with api._c() as c:
        o = c.execute("SELECT status, cut_at, audit_at FROM ordr WHERE id=?", (oid,)).fetchone()
    接 = next((r for r in 记 if r["回传"] == "接单" and r["处理"] == "收下"), None)
    要催, 为什么 = _K.该催(o[0] if o else None, 接["承诺完工日"] if 接 else None, bool(接),
                        (o[1] or o[2]) if o else None, TODAY)
    进度 = {"截至(演示世界的今天)": TODAY, "该不该催": "该催" if 要催 else "不用催"}
    if 为什么: 进度["为什么"] = 为什么
    if 接 and 接["承诺完工日"]:
        差 = (_d.date.fromisoformat(TODAY) - _d.date.fromisoformat(str(接["承诺完工日"])[:10])).days
        进度["承诺完工日"] = 接["承诺完工日"]
        进度["离承诺完工日"] = (f"已经过了 {差} 天" if 差 > 0 else f"还有 {-差} 天" if 差 < 0 else "就是今天")
    return {"进度": 进度, "记录": 记}

def get_stock(spu=None, sku=None, material=None, craft=None):
    """现货。三种问法:某商品有没有货 / 某面料有多少米 / **这个工艺有哪些现货面料可选**。

    第三种是工期推算那条「改用现货面料可压缩 20 天」真正落地的地方 ——
    在此之前系统根本不知道哪些面料有现货,那条建议只是一句空话。
    """
    if sku:
        r=api._rows("SELECT code,spu,spec,color,size,price,stock,locked,status FROM sku WHERE code=?",sku)
        if not r: return {"error":f"没有 SKU {sku}"}
        d=r[0]; d["可用"]=(d["stock"] or 0)-(d["locked"] or 0)
        return d
    if spu:
        p=api._rows("SELECT spu,name,kind,status FROM product WHERE spu=? OR name=?",spu,spu)
        if not p: return {"error":f"没有商品「{spu}」"}
        rs=api._rows("SELECT code,spec,color,size,stock,locked,status FROM sku WHERE spu=?",p[0]["spu"])
        for x in rs: x["可用"]=(x["stock"] or 0)-(x["locked"] or 0)
        tot=sum(x["可用"] for x in rs)
        return dict(p[0],skus=rs,可用合计=tot,
                    note=("**全部零库存** —— 现货答不了,要走定制或补货" if tot<=0 else ""))
    if material:
        m,e=api._resolve(material,"材质")
        if e: return {"error":e}
        r=api._rows("SELECT code,name,unit,price,lead_days,stock_qty FROM material WHERE code=?",m["code"])
        if not r: return {"error":f"{m['name']} 不在物料表里"}
        d=r[0]; d["有现货"]=(d["stock_qty"] or 0)>0
        d["note"]=(f"现货 {d['stock_qty']} {d['unit']},可省掉 {d['lead_days']} 天备料"
                   if d["有现货"] else f"**无现货**,须备料 {d['lead_days']} 天")
        return d
    if craft:
        k,e=api._resolve(craft,"工艺")
        if e: return {"error":e}
        rs=api._rows("SELECT m.code,m.name,m.price,m.lead_days,m.stock_qty,cc.verdict,cc.rule"
                 " FROM material m JOIN craft_combo cc ON cc.material=m.code"
                 " WHERE m.cat='主料' AND cc.craft=? AND cc.verdict='可' AND m.stock_qty>0"
                 " ORDER BY m.stock_qty DESC",k["code"])
        return {"工艺":k["name"],"hit":len(rs),"现货且相容的面料":rs,
                "note":"按现货量排序。换成这里的面料可以把备料压到 1–3 天;"
                       "**但面料换了,质感与售价都会变,必须让客户确认**,不能替他决定。"}
    return {"error": "要给 spu / sku / material / craft 其中之一"}

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
         for r in api._rows("SELECT r.wearer_id, r.measured_at, r.measured_by_no, r.method, r.value, "
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
    p = api._rows("SELECT code,xz,sizes FROM pattern WHERE code=?", pattern_code)
    if not p or not p[0]["sizes"]:
        return None
    p = p[0]
    specs = {}
    for r in api._rows("SELECT size,item,value FROM size_spec WHERE pattern=?", p["code"]):
        specs.setdefault(r["size"], {})[r["item"]] = r["value"]
    fs = [r["feature"] for r in api._rows("SELECT feature FROM body_feature WHERE wearer_id=?", wearer_id)]
    mth = next(iter(ms.values()))[1]
    _sx = (api._rows("SELECT gender FROM wearer WHERE id=?", wearer_id) or [{}])[0].get("gender")
    out = fitting.recommend({k: v[0] for k, v in ms.items()}, p["code"], p["sizes"].split(","),
                            specs, p["xz"], mth, fs, sex=_sx)
    return out.get("档位")

def _白坯试衣_预取(件们):
    """**一次把一批订单行要的那几样取齐** —— 给 `_白坯试衣(预取=…)` 用。

    为什么要有它:`_白坯试衣` 原来每件自己查 6 条(订单行 / 配件 / 下单日 /
    开裁时刻 / 场合标签 / 试衣记录),而看板一次要算三千多件,
    一份经营报告因此背上约两万条查询。
    **每条只要 0.6 毫秒 —— 慢的不是查询,是条数。**
    (2026-10-19 剖析:`fitting_queue` 一次 148.8 秒,这 6 条占 91%;
    看板页面本身要等 21 秒,门禁只是第一个喊疼的地方。)

    ⚠️⚠️ **这里只搬「取数」,一个判定都不做。** 该不该试 / 开没开裁 / 试没试
    仍然只在 `_白坯试衣` 里判那一份 —— 预取给出来的东西必须和它自己查出来的
    **逐字一样**。否则就是同一套规矩的第二套实现,
    而**两份实现不一致的时候,各自看都是对的**(这个项目栽过)。
    所以排序也要照抄:配件按 `id`(下面挑主料取的是第一条)、
    试衣按 `round`(输出里「第几轮」按这个顺序列)。

    ⚠️ **不用 `IN (…)`**:参数个数有上限,而上限随 SQLite 的编译选项变
    (本机 32766,老版本是 999)—— 三千个 id 在这台机器上跑得过、换一台就报错,
    而那种错**只在数据长大之后才出现**。整表取回来再分组就没有这个问题:
    配件 2.5 万行、订单 2.7 万行、试衣 340 行、场合 553 行,四条查询。
    """
    件 = {r["id"]: r for r in 件们}
    配件, 试衣, 场合 = {}, {}, {}
    for r in api._rows("SELECT item_id,kind,material,part FROM item_part_choice "
                   "ORDER BY item_id, id"):
        配件.setdefault(r["item_id"], []).append(r)
    for r in api._rows("SELECT * FROM fitting ORDER BY item_id, round"):
        试衣.setdefault(r["item_id"], []).append(r)
    for r in api._rows("SELECT spu,scene FROM product_scene ORDER BY spu"):
        场合.setdefault(r["spu"], []).append(r)
    单 = {r["id"]: r for r in api._rows("SELECT id,created,cut_at FROM ordr")}
    return {"件": 件, "配件": 配件, "试衣": 试衣, "场合": 场合, "单": 单}

def _白坯试衣(order_id, item_name, order_status, item_id=None, 假设未开裁=False,
             预取=None):
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
    if 预取 is not None and item_id is not None:
        _预件 = (预取.get("件") or {}).get(item_id)
        it = [_预件] if _预件 else []
    else:
        # 没给预取就照原样自己查 —— 这条路还在被跑到:
        # `fitting_write.过闸` 一次只看一张单,它不走批量(2026-10-19 剖析:252 次)。
        it = (api._rows("SELECT i.id, i.name, i.spu, i.wearer_id, p.pattern FROM ordr_item i "
                    "LEFT JOIN product p ON p.spu=i.spu WHERE i.id=? AND i.order_id=?",
                    item_id, order_id)
              if item_id else
              api._rows("SELECT i.id, i.name, i.spu, i.wearer_id, p.pattern FROM ordr_item i "
                    "LEFT JOIN product p ON p.spu=i.spu "
                    "WHERE i.order_id=? AND i.name=?", order_id, item_name))
    if not it:
        return {"note": "订单行里没有同名商品,查不到试衣记录"}
    item = it[0]

    # 该不该试 —— **跑真的工期推算**,不在这儿另判一遍
    import leadtime as _ltb
    mt = _ltb.记住(("带幅宽的料",), lambda: {r["name"]: r["code"] for r in
          api._rows("SELECT code,name FROM material WHERE width_cm IS NOT NULL")})
    kfm = _ltb.记住(("工艺名→码",), lambda: {r["name"]: r["code"] for r in api._rows("SELECT code,name FROM craft")})
    ch = ((预取["配件"].get(item["id"]) or []) if 预取 is not None else
          api._rows("SELECT kind,material,part FROM item_part_choice WHERE item_id=? "
                "ORDER BY id", item["id"]))
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
        # ⚠️ 用 `.get`,不是 `[...]`:取不到那张单时原来给的是 None,
        #    而 KeyError 会**当场崩**。崩和 None 在这里是两种完全不同的行为。
        _od = ((预取["单"].get(order_id) or {}).get("created") if 预取 is not None else
               (api._rows("SELECT created FROM ordr WHERE id=?", order_id) or [{}])[0].get("created"))
        该, why = _mu.按配置判(item["pattern"], mt[主["material"]], ks, scope,
                               None, api._names(), on=_od)

    # ── 业务 09-22:三类必试(重工 / 全定制 / 婚服),新规挂在「开裁」这个动作上 ──
    重工, 重工_为什么 = 该, why
    开裁 = False if 假设未开裁 else _sf.开裁了吗(order_status)
    系统开裁 = bool((预取["单"].get(order_id) or {}).get("cut_at") if 预取 is not None else
                    (api._rows("SELECT cut_at FROM ordr WHERE id=?", order_id) or [{}])[0].get("cut_at"))
    新规 = _mu.适用新规(开裁, 系统开裁)
    档位 = _亲量档位(item["wearer_id"], item["pattern"], item["id"]) if 新规 else None
    _场合 = ((预取["场合"].get(item["spu"]) or []) if 预取 is not None else
             api._rows("SELECT scene FROM product_scene WHERE spu=?", item["spu"])) if item["spu"] else []
    婚服 = (any(r["scene"] == "SC-OCC-03" for r in _场合) if _场合 else None) if 新规 else None
    if 新规 is None:
        该, why, 中 = None, "**判不了** —— 不知道这一单开没开裁,也就不知道按新规还是旧规判", []
    else:
        该, why, 中 = _mu.必试(重工, 档位, 婚服, 新规)
        if 重工_为什么 and "重工" in 中: why += ";重工:" + 重工_为什么

    recs = ((预取["试衣"].get(item["id"]) or []) if 预取 is not None else
            api._rows("SELECT * FROM fitting WHERE item_id=? ORDER BY round", item["id"]))
    签 = any(r["signed"] for r in recs)
    st = _mu.归档(该, 开裁, bool(recs), 签)

    return api._nz({
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

def order_log(order_id=None):
    """**这张单发生过什么** —— 状态变化、每条工厂回传(含被拒收和作废的)、人工回退、延期、按件签收,
    按时间排成一条。业务 09-23:「每个订单都会有独立日志」。只读。"""
    import factory_inbox as _fi
    me = api.whoami()
    if not me:
        return {"error": "没有登录身份"}
    oid = (order_id or "").strip()
    o = api._rows("SELECT id, shop, status, kind FROM ordr WHERE id=?", oid)
    if not o:
        return {"error": f"没有订单 {oid}"}
    if me.get("role") != "总部运营" and o[0]["shop"] != me.get("shop"):
        return {"error": f"这张单在「{o[0]['shop']}」,只能看本店的"}
    _fi.ensure()
    return {"订单": oid, "现在是": o[0]["status"], "日志": _fi.订单日志(oid, db=api.DB),
            "包裹": _fi.包裹们(oid, db=api.DB),
            "note": "**被拒收、被作废的回传也在里面** —— 只留成功的,出了事最想知道的那几条恰好都不在。"}

def delay_pending():
    """**工厂延期了、还没告诉顾客的单。** 通知完用 mark_delay_told 记一下。只读。"""
    import factory_inbox as _fi
    me = api.whoami()
    if not me:
        return {"error": "没有登录身份"}
    _fi.ensure()
    shop = None if me.get("role") == "总部运营" else me.get("shop")
    rs = _fi.待通知清单(shop, db=api.DB)
    for x in rs:
        x["是你的"] = x.get("advisor_no") == me.get("no")
    return {"范围": shop or "全部门店", "条数": len(rs), "明细": rs,
            "note": "**联系顾客是对外动作,由人做** —— 这里给的是「该跟哪几单、原定什么时候、延到什么时候」。"
                    "通知完记得用 mark_delay_told 标一下,不标的话这份清单只进不出。"}

def mark_delay_told(delay_id=None):
    """(写)顾问通知完顾客,标一下。"""
    import factory_inbox as _fi
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在标记 —— 请先登录")
    return _fi.标记已通知(delay_id, me, db=api.DB)

def rollback_order(order_id=None, cause=None, note=None):
    """(写)**人工回退**:工厂发错件 / 到店发现要返工。只有店长能点,必须写清为什么。"""
    import factory_inbox as _fi
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在回退 —— 请先登录")
    return _fi.人工回退((order_id or "").strip(), (cause or "").strip(), (note or "").strip(), me, db=api.DB)

def factory_chase():
    """**该催工厂的单 + 要人看的工厂回传。** 生产和发货只认工厂回传(业务 09-22),门店不推 ——
    门店能做的是**知道哪几单该去催**:开工超过 3 天工厂没回接单(单可能没发过去),
    或过了工厂承诺的完工日还没完工(该先告诉顾客会晚)。

    范围:总部运营看全部,其余只看本店。「今天」按演示世界的今天(seed.TODAY),和判超期同一天。
    口径在 knowledge/factory_feed.py,收件箱在 backend/factory_inbox.py。
    """
    import factory_inbox as _fi
    from seed import TODAY
    me = api.whoami()
    if not me:
        return {"error": "没有登录身份,不知道看哪家店"}
    shop = None if me.get("role") == "总部运营" else me.get("shop")
    _fi.ensure()
    催 = _fi.该催清单(TODAY, shop)
    with api._c() as c:
        for x in 催:
            接 = c.execute("SELECT factory, promise_date FROM factory_msg WHERE order_id=? AND event='接单' "
                          "AND result='收下' LIMIT 1", (x["订单"],)).fetchone()
            x["生产方"], x["承诺完工日"] = (接[0], 接[1]) if 接 else (None, None)
            x["是你的"] = x["顾问"] == me.get("no")
        # ⚠️ 「条数」原来是 len(看) —— 而明细被 LIMIT 50 截住,超过 50 条就会报成 50。
        # 和 get_lifecycle 那次「休眠 40 个、实际 1395」同一个洞(2026-10-08 用户撞到的):
        # 「截断了」和「一共就这么多」在返回里长得一模一样。总数单独数一遍
        _片, _参 = api._门店条件(shop, "o", c)      # 按门店码;复用手上这条只读连接
        从 = (" FROM factory_msg f LEFT JOIN ordr o ON o.id=f.order_id WHERE f.result IN ('挂异常','拒收','暂存')"
             + (f" AND {_片}" if _片 else ""))
        参 = tuple(_参)
        看总 = c.execute("SELECT COUNT(*)" + 从, 参).fetchone()[0]
        看 = [dict(zip(("订单", "回传", "生产方", "工厂报的时间", "处理", "为什么"), r)) for r in c.execute(
            "SELECT f.order_id, f.event, f.factory, f.at, f.result, f.reason" + 从
            + " ORDER BY f.at DESC LIMIT 50", 参)]
    return {"截至": TODAY, "范围": shop or "全部门店",
            "该催": {"单数": len(催), "明细": 催},
            "要人看的回传": {"条数": 看总, "列出": len(看), "明细": 看,
                        **({"截断": f"一共 {看总} 条,只列了最近 {len(看)} 条 —— **报条数用「条数」,不要数明细**"}
                           if 看总 > len(看) else {})},
            "note": "生产和发货只认工厂回传,**门店和后台都不能手动推状态**。该催的是**对外动作**(联系工厂、"
                    "告诉顾客会晚),由人去做;挂异常 / 拒收的回传照「为什么」去跟工厂核,别替工厂补数据。"}

def _订单标签(行, 顾问号):
    """这一单对这个顾问是哪一种。顾问之外的角色返回空 —— **不编一个标签出来**。"""
    # 判定在 `knowledge/order_scope.标`,**这儿不再写一份**。
    import order_scope as _范
    return _范.标(角色=_范.顾问 if 顾问号 else None, 工号=顾问号,
                单的顾问=行.get("顾问"), 客户归属顾问=行.get("客户归属顾问"))

def orders_by_date(direction=None, days=7, field="下单", limit=50,
                   月份=None, 起=None, 止=None, month=None, start=None, end=None):
    """**按时间段列订单** —— 「下周有哪些单要交付」「上周下了多少单」这类问法。

    ⚠️ **「下一周」是歧义的,这个工具不替人猜**(业务 2026-09-24 定):

        往后 7 天   今天到 7 天后   —— 「下周要交付的」「接下来一周要发的货」
        往前 7 天   7 天前到今天   —— 「最近一周下了多少单」「这一周做了多少生意」

    两种读法的单子几乎没有交集,而猜错的表现是**给出一份看起来很正常的清单**,
    没有任何地方会提示这不是他要的那一批。所以 direction 不给就返回「判不了」,
    **并且把两种读法各有多少单一起给出来** —— 让人一眼就能选,而不是被空手打回。

    field 决定查哪一列(下单 / 完工 / 发货 / 交付)。四列是四份不同的单子:
    同一张单「下单」在上个月、「交付」在下周。默认按下单日,**并且在返回里说清用的是哪一列**。

    范围跟身份走:顾问只看自己的,店长看本店,总部运营看全部。
    「今天」用这家店的今天(seed.TODAY ← 库里的 world_meta),不是机器时钟。
    """
    from seed import TODAY
    import datetime as _dt
    # ⚠️ 2026-10-08 用户在页面上问「九月有哪些订单已完成」,模型答「这个工具只能往前数 N 天,框不出 9 月 1–30 日」——
    # **函数早就会按月 / 按起止日期查(10-06 加的),给模型看的 schema 里一个字没写**,它只看得见 direction / days。
    # 而 schema 的属性名**必须是 ASCII**(API 校验 ^[a-zA-Z0-9_.-]{1,64}$),中文参数名进不了 schema ——
    # 所以对外是 month / start / end,进来后照旧走 月份 / 起 / 止 那条路
    月份 = 月份 if 月份 is not None else month
    起 = 起 if 起 is not None else start
    止 = 止 if 止 is not None else end
    me = api.whoami()
    if not me:
        return {"error": "没有登录身份,不知道看哪家店"}
    if field not in api._订单日期列:
        return {"error": f"field 只能是 {'/'.join(api._订单日期列)},你给的是「{field}」",
                "说明": {k: v[1] for k, v in api._订单日期列.items()}}
    col, 释 = api._订单日期列[field]
    今 = _dt.date.fromisoformat(TODAY)
    天 = max(1, min(int(days or 7), 366))

    条, args, 范围话, 顾问号 = api._订单范围(me)

    def 数(起, 止):
        with api._c() as c:
            return c.execute(
                f'SELECT COUNT(*) FROM ordr o '
                f'LEFT JOIN customer cu ON cu.id=o.customer_id '
                f'WHERE o."{col}" IS NOT NULL AND o."{col}">=? AND o."{col}"<=?{条}',
                (起.isoformat(), 止.isoformat() + " 23:59:59", *args)).fetchone()[0]

    # ── 绝对区间那条路(业务 2026-10-06 要的「一月全部订单」)──────────
    #
    # ⚠️ **「一月」在中文里是歧义的**,和这个工具本来就在拦的「下一周」同一个形状:
    #     今年 1 月        2026-01-01 ~ 2026-01-31
    #     最近一个月      今天往前 30 天
    # 两份单子几乎没有交集。所以调用方把「一月」原样传进来时**不猜** ——
    # 认出他说的是几月,然后把两种读法各有多少单摆出来,让他挑。
    绝对 = None
    if 月份 is not None:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", str(月份).strip())
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            if not 1 <= mo <= 12:
                return {"error": f"月份里的月是 {mo} —— 得在 1 和 12 之间"}
            起日 = _dt.date(y, mo, 1)
            末 = _dt.date(y + (mo == 12), (mo % 12) + 1, 1) - _dt.timedelta(days=1)
            绝对 = (起日, 末, f"{y} 年 {mo} 月")
        else:
            # 认不出 ISO —— 看看是不是「一月」「1月」这类说法
            原 = str(月份).strip().rstrip("月份 ")
            mo = api._中文月.get(原) or (int(原) if 原.isdigit() and 1 <= int(原) <= 12 else None)
            if not mo:
                return {"error": f"月份要写成 `YYYY-MM`(比如 `2026-01`),你给的是「{月份}」",
                        "note": "**不替你解析自然语言** —— 解析错的那次,"
                                "清单看起来完全正常"}
            今年起 = _dt.date(今.year, mo, 1)
            今年末 = _dt.date(今.year + (mo == 12), (mo % 12) + 1, 1) - _dt.timedelta(days=1)
            return {"判不了": f"「{月份}」有两种读法,**这两份单子几乎没有交集**",
                    "今天": TODAY, "按哪一列": f"{field}({col}:{释})",
                    "候选": [
                        {"参数": {"month": f"{今.year}-{mo:02d}"},
                         "含义": f"{今.year} 年 {mo} 月({今年起} ~ {今年末})",
                         "有多少单": 数(今年起, 今年末)},
                        {"参数": {"direction": "往前", "days": 30},
                         "含义": f"最近一个月({今 - _dt.timedelta(days=30)} ~ {今})",
                         "有多少单": 数(今 - _dt.timedelta(days=30), 今)}],
                    "note": "**不替你挑一个** —— 定下来再调一次。"
                            "(和 direction 那条歧义同一个道理)"}
    elif 起 is not None or 止 is not None:
        if not (起 and 止):
            return {"error": "`起` 和 `止` 要一起给 —— **只给一头的区间没有意义**,"
                             "而它会被当成「从那天到今天」或者「从头到那天」,两种差很远"}
        try:
            起日, 末 = _dt.date.fromisoformat(str(起)), _dt.date.fromisoformat(str(止))
        except ValueError:
            return {"error": f"`起`/`止` 要写成 `YYYY-MM-DD`,你给的是「{起}」/「{止}」"}
        if 末 < 起日:
            return {"error": f"`止`({末})比 `起`({起日})还早 —— **不替你调换顺序**,"
                             f"调换之后那份清单看起来完全正常"}
        绝对 = (起日, 末, f"{起日} ~ {末}")

    if 绝对 and direction is not None:
        return {"error": "**绝对区间和相对天数同时给了,说不清要哪个** —— "
                         f"你给了 {绝对[2]},又给了 direction={direction!r}。"
                         "去掉一个再调一次"}

    往后起, 往后止 = 今, 今 + _dt.timedelta(days=天)
    往前起, 往前止 = 今 - _dt.timedelta(days=天), 今
    # ⚠️ **这条歧义只在相对模式下成立。** 给了绝对区间(月份 / 起+止)时
    # 根本没有「往哪边数」这件事 —— 第一版漏了 `not 绝对`,于是
    # `月份="2026-01"` 也被这条拦下来,表现是「它不认我给的月份」,
    # 而实际上是另一条检查先开了口。
    # > 一个「参数没传对」的报错,和一个「另一条检查先拦住了」的,
    # > **在那句「判不了」上长得一模一样。**
    if not 绝对 and direction not in ("往后", "往前", "future", "past"):
        return {"判不了": f"「{天} 天」要往哪边数,没说清 —— 这两种读法的单子几乎没有交集",
                "今天": TODAY, "按哪一列": f"{field}({col}:{释})",
                "候选": [
                    {"direction": "往后", "含义": f"{往后起} ~ {往后止}(今天到 {天} 天后)",
                     "有多少单": 数(往后起, 往后止)},
                    {"direction": "往前", "含义": f"{往前起} ~ {往前止}({天} 天前到今天)",
                     "有多少单": 数(往前起, 往前止)}],
                "note": "**不替你挑一个** —— 猜错的表现是给出一份看起来很正常的清单,"
                        "而没有任何地方会提示这不是你要的那一批。把 direction 定下来再调一次。"}
    if 绝对:
        起, 止, 区间话 = 绝对
        升序 = True
    else:
        往后 = direction in ("往后", "future")
        起, 止 = (往后起, 往后止) if 往后 else (往前起, 往前止)
        区间话 = f"{起} ~ {止}"
        升序 = 往后

    n = max(1, min(int(limit or 50), 200))
    with api._c() as c:
        # 总数**先单独数** —— 不是 len(卡片)。
        # > 一份「只给了前 20 张卡片」的结果,和一份「这段时间就只有 20 单」的,
        # > **在屏幕上长得一模一样** —— 除非把总数写在上面。
        总数 = 数(起, 止)
        列 = ("订单", "客户号", "客户", "类型", "状态", "金额", "门店", "顾问",
             "客户归属顾问", "日期")
        rs = [dict(zip(列, r)) for r in c.execute(
            f'SELECT o.id, o.customer_id, cu.name, o.kind, o.status, o.amount, '
            f'       o.shop, o.advisor_no, cu.advisor_no, o."{col}" '
            f'  FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id '
            f' WHERE o."{col}" IS NOT NULL AND o."{col}">=? AND o."{col}"<=?{条} '
            f' ORDER BY o."{col}" {"ASC" if 升序 else "DESC"} LIMIT ?',
            (起.isoformat(), 止.isoformat() + " 23:59:59", *args, n))]
        # 顾问那一档:两个数**分开报**(业务 2026-10-06 拍的)
        分项 = None
        if 顾问号:
            一 = lambda 片: c.execute(
                f'SELECT COUNT(*) FROM ordr o '
                f'LEFT JOIN customer cu ON cu.id=o.customer_id '
                f'WHERE o."{col}" IS NOT NULL AND o."{col}">=? AND o."{col}"<=? AND {片}',
                (起.isoformat(), 止.isoformat() + " 23:59:59")).fetchone()[0]
            分项 = {
                "我名下客户的": 一(f"cu.advisor_no='{顾问号}'"),
                "我经手下的": 一(f"o.advisor_no='{顾问号}'"),
                "两者重叠": 一(f"cu.advisor_no='{顾问号}' AND o.advisor_no='{顾问号}'"),
            }

    for r in rs:
        r["标"] = _订单标签(r, 顾问号)
        # ⚠️ 客户归属顾问**只用来算标签,不往外报** —— 卡片上不需要它,
        # 而多报一列别人的归属关系没有用处只有风险。
        r.pop("客户归属顾问", None)

    出 = {"今天": TODAY, "区间": 区间话, "按哪一列": f"{field}({col}:{释})",
         "范围": 范围话, "总数": 总数, "卡片数": len(rs), "卡片": rs,
         # ⚠️ **这一栏必须在。** 它是「只给了前 n 张」和「总共就这么多」的唯一区别。
         "还有": max(0, 总数 - len(rs)),
         "note": f"按「{field}」这一列排的。同一张单「下单」和「交付」差着好几周,"
                 f"要的是另一头就换 field 再调一次。"}
    if not 绝对:
        出["方向"] = "往后" if 升序 else "往前"
    if 分项:
        出["两个数分开看"] = 分项
        出["⚠️ 为什么分开"] = (
            "「我的客户的单」和「我做的单」是两件事,混成一个数**业绩就说不清了** ——"
            "而混之前和混之后,那个总数长得一模一样。每张卡片上的 `标` 说明它是哪一种")
    if 总数 > len(rs):
        出["⚠️ 没给全"] = (f"这段时间一共 {总数} 单,这里只给了前 {len(rs)} 张卡片。"
                       f"**别把 {len(rs)} 当成这段时间的单数** —— 要更多就加大 limit"
                       f"(最多 200),要对账就看「总数」那一栏")
    return 出

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
    # ⚠️ 多取 `i.spu` 和 `p.pattern` 是给预取用的 —— `_白坯试衣` 原来自己查这一行,
    #    现在这一行就是它要的那一行,**别让它再去查一遍**。
    rs = api._rows("SELECT i.id,i.order_id,i.name,i.wearer_id,o.status,o.advisor_no,"
               "  o.shop,c.name cname,o.customer_id,i.spu,p.pattern "
               "FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
               "LEFT JOIN customer c ON c.id=o.customer_id "
               "LEFT JOIN product p ON p.spu=i.spu "
               "WHERE o.kind='定制品订单'" + w + " ORDER BY i.id", *a)
    摊 = {}
    # 三千多件逐件推工期 —— 放进「一次查看」的记忆范围:相容矩阵、工时表、现货、
    # 师傅名单、某一天的队在这一次里不会变,不必每件重查(结果一样,只是不重复查)
    import leadtime as _ltb
    # ⚠️ **按行号传,不按商品名传。** `_白坯试衣` 的注释早就写着「按名字取会串到
    #    别人那件上」(一家人订同款时同一张单里会有两件同名),而这里原来传的正是名字 ——
    #    于是那种单会把其中一件**算两遍**,另一件的试衣记录根本没被看。
    #    今天库里 115 组同名**全在标品单**、而这里只看定制单,所以**现在碰巧不触发**;
    #    批量化天然按行号取,顺手把这个坑关掉(改前改后输出逐字节比过,一件没变)。
    with _ltb.批量():
        _预 = _白坯试衣_预取(rs)
        _fs = [(r, _白坯试衣(r["order_id"], r["name"], r["status"],
                            item_id=r["id"], 预取=_预)) for r in rs]
    for r, f in _fs:
        st = f.get("归到哪一档")
        if st == "不必试" and not order:
            continue          # 不必试的不进看板 —— 一张 47 行的清单等于没排队
        摊.setdefault(st or "**算不出**", []).append(api._nz({
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
        for o in api._rows("SELECT id FROM ordr WHERE kind='定制品订单' AND status='待生产' ORDER BY id"):
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
    return api._nz(out)

# ── 分部位选料:可选什么 / 这一单选了什么(2026-11-15,用户清单第六条;体检:2606 条可选料 + 24411 条已选,零工具)──
def _部位模块():
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import part as _part
    return _part

def part_options(product):
    """**这一款每个部位能选什么**(只读)—— 面料 / 工艺各自的可选项、加价、可选颜色,和这个部位吃多少料。

    ⚠️ 部位是**客户看得见的地方**(领口 / 袖 / 裙),不是版房的裁片 —— 归并规则在 knowledge/part.py,是推断不是事实。
    ⚠️ 加价是**这一项比基础款多收的钱**,不是这一项的总价;同一部位的面料和工艺要相容(查 kb_combo,和部位无关)。
    ⚠️ 用料米数要连「来源」一起说:版师没核过的是估的,拿去报价会报偏(同商品页)。
    """
    _part = _部位模块()
    q = str(product or "").strip()
    if not q:
        return {"error": "要给款式:商品编号(spu)或款名"}
    候 = api._rows("SELECT spu, name, kind, pattern FROM product WHERE spu=?", q) or \
        api._rows("SELECT spu, name, kind, pattern FROM product WHERE name LIKE ? ORDER BY spu LIMIT 21", f"%{q}%")
    if not 候:
        return {"error": f"没有「{q}」这一款", "说明": "查不到就说查不到,别拿名字像的款顶上"}
    if len(候) > 1:
        return {"hit": len(候), "候选": [dict(spu=r["spu"], 款名=r["name"], 类=r["kind"]) for r in 候[:20]],
                "说明": "名字对上不止一款 —— **把候选列给人选**,别替他挑;20 条以上只列前 20"}
    p = 候[0]
    行 = api._rows("SELECT kind, part, material, addon, colors, sort FROM part_option WHERE spu=? ORDER BY sort, kind, material",
              p["spu"])
    if not 行:
        return {"spu": p["spu"], "款名": p["name"], "类": p["kind"], "部位": [],
                "说明": ("这一款**没有分部位选料**" + ("(标品不分部位,规格就是 SKU)" if p["kind"] == "标品" else
                        "(定制品却没登记可选料 —— 这是数据缺口,不是「什么都能选」)"))}
    按 = {}
    for r in 行:
        按.setdefault(r["part"], {"面料": [], "工艺": []}).setdefault(r["kind"], []).append(
            dict(名=r["material"], 加价=r["addon"], 可选颜色=[x for x in (r["colors"] or "").split("、") if x]))
    c = api._c()
    出 = []
    for b in [x for x in _part.部位顺序 if x in 按] + [x for x in 按 if x not in _part.部位顺序]:
        米, 源 = _part.部位用料(c, p["pattern"], b) if p["pattern"] else (None, None)
        出.append(dict(部位=b, 可选面料=按[b].get("面料", []), 可选工艺=按[b].get("工艺", []), 用料米=米, 用料来源=源))
    return {"spu": p["spu"], "款名": p["name"], "类": p["kind"], "部位": 出,
            "报价口径": _part.报价口径,
            "说明": "加价是比基础款多收的钱,不是这一项的总价;同一部位的面料和工艺要相容(kb_combo 查,和部位无关);用料米数带着来源,估的别当实测"}

def order_parts(order_id):
    """**这一单每个部位实际选了什么**(只读)—— 并核三件事:选的料在不在这款的可选范围里、面料和工艺相不相容、
    各项加价加起来对不对得上订单行上的「定制部件金额」。范围跟身份走(同 get_order)。

    ⚠️ 三项核对都是**查表对账**,对不上就照实列出来 —— 不替人判是录错了还是另有约定。
    """
    me = api.whoami()
    if not me:
        return {"error": "没登录,看不了订单"}
    where, args, 范围话, _ = api._订单范围(me)
    单 = api._rows("SELECT o.id, o.kind, o.status FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id WHERE o.id=?" + where,
              order_id, *args)
    if not 单:
        有 = api._rows("SELECT 1 FROM ordr WHERE id=?", order_id)
        return {"error": (f"订单 {order_id} 不在你能看的范围里({范围话})" if 有 else f"没有订单 {order_id}")}
    件们 = api._rows("SELECT id, spu, name, custom_amount FROM ordr_item WHERE order_id=? ORDER BY id", order_id)
    相容 = {(r["k"], r["m"]): r["verdict"] for r in api._rows(
        "SELECT ck.name k, cm.name m, cc.verdict FROM craft_combo cc JOIN craft ck ON ck.code=cc.craft "
        "JOIN craft cm ON cm.code=cc.material")}
    出 = []
    for it in 件们:
        选 = api._rows("SELECT kind, part, material, color, amount, note FROM item_part_choice WHERE item_id=? ORDER BY id", it["id"])
        可 = {(r["part"], r["kind"], r["material"]) for r in api._rows(
            "SELECT part, kind, material FROM part_option WHERE spu=?", it["spu"])}
        部位 = {}
        for r in 选:
            部位.setdefault(r["part"], []).append(r)
        核 = []
        for r in 选:
            if 可 and (r["part"], r["kind"], r["material"]) not in 可:
                核.append(f"{r['part']} 的{r['kind']}「{r['material']}」不在这款的可选范围里")
        for b, rs in 部位.items():
            面 = [r["material"] for r in rs if r["kind"] == "面料"]
            工 = [r["material"] for r in rs if r["kind"] == "工艺"]
            for k in 工:
                for m in 面:
                    v = 相容.get((k, m))
                    if v is None:
                        核.append(f"{b}:{k} × {m} 相容矩阵里没这一格(未定义,要转工艺负责人确认)")
                    elif v != "可":
                        核.append(f"{b}:{k} × {m} 相容判定是「{v}」")
        合计 = round(sum(r["amount"] or 0 for r in 选), 2)
        额 = it["custom_amount"]
        if 选 and 额 is not None and abs((额 or 0) - 合计) > 0.005:
            核.append(f"各项加价合计 ¥{合计:g},订单行上的定制部件金额是 ¥{额:g} —— 对不上")
        出.append(dict(明细=it["id"], 款=it["name"], spu=it["spu"],
                      选了=[dict(部位=r["part"], 类=r["kind"], 选=r["material"], 颜色=r["color"] or None, 加价=r["amount"]) for r in 选],
                      加价合计=合计, 定制部件金额=额, 核对=核 or ["三项都对得上"],
                      说明=None if 选 else "这一行没有分部位选料记录(标品,或定制品漏记 —— 漏记的话车间打印不出部位和料)"))
    return {"订单": order_id, "类": 单[0]["kind"], "状态": 单[0]["status"], "范围": 范围话, "明细": 出,
            "说明": "核对是查表对账:对不上照实说,不替人判是录错了还是另有约定"}

# ── 标品交付告知(2026-11-15,用户清单第六条 + 下午拍的三条:只印相关项 / 聊天和订单页两处 / 发 = 记已告知)──
def draft_delivery_notice(order_id):
    """**起草一份标品交付告知**(只读)—— 这单商品对上「交付时必须书面告知的六条」里的哪几条,每条凭商品名里的哪个词;
    给出一段顾问复制去发的文字。**不记任何东西**:顾问发完、明说「发了 / 记一下」才调 record_delivery_notice。"""
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import delivery_notice as _dn
    me = api.whoami()
    if not me:
        return {"error": "没登录,看不了订单"}
    where, args, 范围话, _ = api._订单范围(me)
    o = api._rows("SELECT o.id, o.kind, o.status FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id WHERE o.id=?" + where,
              order_id, *args)
    if not o:
        有 = api._rows("SELECT 1 FROM ordr WHERE id=?", order_id)
        return {"error": (f"订单 {order_id} 不在你能看的范围里({范围话})" if 有 else f"没有订单 {order_id}")}
    o = o[0]
    if o["kind"] != "标品订单":
        return {"error": "定制单的交付告知走交付卡签收,这里只起草标品的"}
    名们 = [dict(名=r["name"]) for r in api._rows("SELECT name FROM ordr_item WHERE order_id=? ORDER BY id", order_id)]
    稿 = _dn.起草(名们, 顾问名=me.get("name"))
    已 = api._rows("SELECT d.notified_at, d.notified_by, s.name notified_by_name, d.notified_channel, d.notified_items "
              "FROM delivery_notice d LEFT JOIN staff s ON s.no=d.notified_by WHERE d.order_id=?", order_id) \
        if "notified_at" in {r["name"] for r in api._rows("PRAGMA table_info(delivery_notice)")} else []
    稿.update(订单=order_id, 状态=o["status"], 范围=范围话,
             已记过=(dict(已[0]) if 已 and 已[0]["notified_at"] else None),
             下一步=("这单已经记过已告知了" if 已 and 已[0]["notified_at"] else
                   "把「文字」复制给顾客;**发完、用户明说了再调 record_delivery_notice 记下**,没发别记" if 稿["适用"] else
                   "没有要告知的项,不用发"))
    return 稿

def record_delivery_notice(order_id, channel=None):
    """(写)**记下「交付告知已经发给顾客了」** —— 只在用户明说「发了 / 记一下」时调。告知了哪几条由起草现算,不收条目。
    **这不是顾客签收**:签收另记,售后判责读签收。"""
    import delivery_notice_write as _dw
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在记 —— 请先登录")
    where, args, _, _ = api._订单范围(me)
    r = _dw.记已告知((order_id or "").strip(), channel, me, where, args, db=api.DB)
    if r.get("ok"):
        api._agent_log(me, "DELIVERY_NOTIFIED", r.get("reason", "") or order_id)
    return r

def _签收日期(order_id):
    """这一单什么时候签收的 —— 按件签收之后取**最后一件**合身的时间,没有就退回订单级那一行。"""
    r = api._rows("SELECT MAX(fit_at) t FROM pickup_item WHERE order_id=? AND fit_result='合身'", order_id)
    return (r[0]["t"] if r else None) or (
        (api._rows("SELECT fit_at FROM pickup WHERE order_id=?", order_id) or [{}])[0].get("fit_at"))
