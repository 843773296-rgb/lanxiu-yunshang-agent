"""从 backend/api.py 拆出来的「api_pattern」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api
import datetime as _dt
import worldclock as _wc


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
        if not api._rows("SELECT no FROM artisan WHERE no=? OR name=?", who, who):
            st = api._rows("SELECT no,name,role FROM staff WHERE no=? OR name=?", who, who)
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
    rs = api._rows(sql + " ORDER BY w.due_date", *args)
    today = _wc.今天().isoformat()
    out = []
    for r in rs:
        d = dict(r)
        # **交期是否已经过了**,而不是让模型自己拿今天去比 ——
        # 模型不知道今天几号,靠它算这个必错,而且错得很自然。
        d["已逾期"] = bool(d.get("due_date") and d["due_date"] < today and d["status"] == "在制")
        d["剩余天数"] = ((_dt.date.fromisoformat(d["due_date"]) - _wc.今天()).days
                     if d.get("due_date") else None)
        out.append(d)
    if not out:
        return {"hit": 0, "note": "没有符合条件的在制工单,不要凭印象回答"}
    if overdue: out = [x for x in out if x["已逾期"]]
    late = [x["id"] for x in out if x["已逾期"]]
    return {"hit": len(out), "rows": [api._nz(x) for x in out[:30]],
            "已逾期工单": late,
            "note": "「剩余天数」为负说明已经过了交期。**逾期工单要先说,不要埋在列表里。**"
                    "一个师傅手上的在制件数超过 wip_limit,说明他已经排满,再派活只会更晚。"}

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
        rs = api._rows("SELECT pattern, COUNT(*) 片数, "
                   "SUM(CASE WHEN ratio_src='版师' THEN 1 ELSE 0 END) 已核, "
                   "GROUP_CONCAT(DISTINCT ratio_src) 来源 "
                   "FROM pattern_piece WHERE ratio IS NOT NULL GROUP BY pattern")
        nm = {r["code"]: r["name"] for r in api._rows("SELECT code,name FROM pattern")}
        for r in rs:
            r["版型"] = nm.get(r["pattern"], r["pattern"])
        待 = sum(1 for r in rs if r["已核"] < r["片数"])
        return {"hit": len(rs), "rows": rs,
                "note": f"**{待} 个版型还没核完**。传 pattern 看某一个的明细。"
                        f"核过的标 `版师`,**不会被重新估算覆盖**。"}
    p = api._rows("SELECT code,name,fabric_base FROM pattern WHERE code=? OR name=?",
              pattern, pattern)
    if not p:
        return {"error": f"没有版型「{pattern}」—— 这个工具认版型编码(PT06)和全名"}
    p = p[0]
    rs = api._rows("SELECT name,qty,ratio,ratio_src,note FROM pattern_piece "
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
    总片 = api._rows("SELECT COUNT(*) n FROM pattern_piece WHERE ratio IS NOT NULL")[0]["n"]
    # 数的是登记行数(裁片**种类**数),不是要裁几块 —— 一片 qty=2 在表里也只有一行
    已核 = api._rows("SELECT COUNT(*) n FROM pattern_piece WHERE ratio_src='版师'")[0]["n"]
    全核完 = api._rows(
        # 数的是登记行数(裁片**种类**数),不是要裁几块 —— 一片 qty=2 在表里也只有一行
        "SELECT COUNT(*) n FROM (SELECT pattern FROM pattern_piece "
        "GROUP BY pattern HAVING SUM(CASE WHEN ratio_src='版师' THEN 0 ELSE 1 END)=0)")[0]["n"]
    # **影响面**:挂的商品数 + 已出过货的订单行数。两个都算,因为它们答的不是同一个问题
    # (商品多 = 以后会一直用;订单行多 = 已经在按这个数备料了)。
    先核 = api._rows(
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
    活.append(api._nz({
        "事": "裁片用料占比",
        "进度": f"{已核}/{总片} 片已核,{全核完}/{api._rows('SELECT COUNT(DISTINCT pattern) n FROM pattern_piece')[0]['n']} 个版型全核完",
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
    活.append(api._nz({
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
    参考 = api._rows("SELECT pattern, item, COUNT(*) n, MAX(caveat) why FROM size_spec "
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
    无版 = api._rows(
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
    等改版 = api._rows(
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
    活.append(api._nz({
        "事": "在等改版的单(着装人有体型特征)",
        "进度": f"{len(等改版)} 条 —— "
                f"库里共 {api._rows('SELECT COUNT(DISTINCT wearer_id) n FROM body_feature')[0]['n']}"
                f" 位着装人有体型特征,其中这些落在还没走完的单上",
        "明细": [f"{r['order_id']} · {r['wearer_id']}({r['feature']})· "
                 f"{r['pattern_name'] or '未挂版型'} · {r['status']}"
                 for r in 等改版] or None,
        "状态": ("**一条都没有** —— 是真没有,不是没扫到(扫的是全部未完结的单)"
                 if not 等改版 else None),
        "怎么核": "`kb_fit(客户, 版型, 着装人)` 看逐项差值和关键尺寸覆盖。"
                  "改哪儿、改多少:`kb_fit` 返回的「改版量」是**行业资料参考量(衬衫的数)**,"
                  "汉服要试穿验证,**最终由版师定** —— 不要当成定数",
    }))

    out["谁在看"] = (api.whoami() or {}).get("name") or "(没登录)"
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
    pats = api._rows("SELECT code,name FROM pattern ORDER BY code")
    片 = {}
    for r in api._rows("SELECT pattern,name FROM pattern_piece"):
        片.setdefault(r["pattern"], []).append(r["name"])
    格子, 疑点 = 0, []
    for p in pats:
        rs = api._rows("SELECT size,item,value FROM size_spec WHERE pattern=?", p["code"])
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
        # ⚠️ **把「这条核过没有」和档差表并排给出来。**
        # 少了这一栏,版师看到的是一张 12 行的档差表 —— 而「核过的」和「没人核过的」
        # 在那张表上长得一模一样,于是他每次都得从头核一遍,或者干脆都当核过的。
        核况 = _档差核况()
        return api._nz({
            "扫了": f"{r['扫了']} 个版型 / {r['格子']} 条尺码",
            "档差规则": _g.档差(),
            "这 12 条核过没有": 核况["逐条"],
            "核过的 / 没人核过的 / 核过但失效的": 核况["小结"],
            "有疑点的版型": r["疑点"] or None,
            "note": (f"要核的是上面那 {len(_g.档差())} 条档差和各版型的基码,"
                     f"**不是 {r['格子']} 个数** —— 尺码表是推出来的,"
                     f"改一条档差对全部码生效。"
                     + ("  这一轮**一个疑点都没有**:档差处处对得上 —— "
                        "**这不叫没查,是查过了**(扫了全部 "
                        f"{r['格子']} 条)。" if not r["疑点"] else "")),
        })
    p = api._rows("SELECT code,name,sizes,version FROM pattern WHERE code=? OR name=?",
              pattern, pattern)
    if not p:
        return {"error": f"没有版型「{pattern}」(认版型编码 PT04,也认全名「明制马面裙·标准」)"}
    p = p[0]
    片 = [r["name"] for r in api._rows("SELECT name FROM pattern_piece WHERE pattern=?", p["code"])]
    参考 = _g.参考项(片)
    rs = api._rows("SELECT size,item,value FROM size_spec WHERE pattern=?", p["code"])
    tbl = {}
    for r in rs: tbl.setdefault(r["size"], {})[r["item"]] = r["value"]
    明细 = []
    for 部位, d in sorted(_g.核档(tbl, set(参考)).items()):
        基 = tbl.get("M", {}).get(部位)
        rng = _g.覆盖范围(基, 部位, list(tbl)) if 基 is not None else None
        明细.append(api._nz({
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
    _v = api._rows("SELECT version FROM pattern WHERE code=?", p["code"])
    return api._nz({
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

def _档差核况():
    """那 12 条档差各自核过没有、核过的还算不算数。**判定走 `grading.核过还算数吗`,这里只取数。**

    (项目第 9 节①:谁负责判定,谁就不该同时负责取数。)
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import grading as _g
    表 = _g.档差()
    记 = {}
    try:
        记 = {r["item"]: r for r in api._rows(
            "SELECT item, verdict, value_at_check, propose, why, checked_by, checked_at "
            "FROM grade_diff_check")}
    except Exception:
        # 表还没建(CI 从零、或者这个口还没被用过)——
        # **「一条核过记录都没有」和「表不存在」要给出同一句人话**,
        # 但都不能说成「核过了」
        记 = {}
    # ⚠️ **四个桶要加得起来等于 12** —— 第一版「说不对」那一档没计数,
    # 于是小结里 核过+没核+失效 < 12,而**少掉的那几条看不出来**:
    # 读的人会以为剩下的都在前三类里。所以下面最后断言一次。
    逐条, 核过, 没核, 失效, 说不对 = {}, 0, 0, 0, 0
    for 项, 现值 in sorted(表.items()):
        r = 记.get(项)
        if not r:
            逐条[项] = f"{现值} —— **没人核过**(机器推的规则,没有人签过字)"
            没核 += 1
            continue
        算, 话 = _g.核过还算数吗(r["value_at_check"], 现值)
        if r["verdict"] == _g.不对:
            逐条[项] = (f"{现值} —— ⚠️ **版师核过说这条不对**,建议 {r['propose']}"
                        f"(核于 {r['checked_at']},{r['checked_by']}):{r['why']}。"
                        f"**md 还没改,库里所有码用的还是 {现值}**")
            说不对 += 1
        elif 算:
            逐条[项] = (f"{现值} —— ✅ 版师核过({r['checked_at']},{r['checked_by']}):{r['why']}")
            核过 += 1
        else:
            逐条[项] = (f"{现值} —— ⚠️ **核过但已失效**:{话}"
                        f"(原核于 {r['checked_at']},{r['checked_by']})")
            失效 += 1
    assert 核过 + 没核 + 失效 + 说不对 == len(表), (
        f"四个桶加起来 {核过 + 没核 + 失效 + 说不对} ≠ 档差 {len(表)} 条 —— "
        f"**有档差落在任何一类之外**,而小结里看不出来")
    return {"逐条": 逐条,
            "小结": (f"核过且还算数 {核过} 条 / 没人核过 {没核} 条 / "
                     f"核过但失效 {失效} 条 / 版师说不对 {说不对} 条 / 共 {len(表)} 条。"
                     + ("**一条都没人核过** —— 这 12 条全是机器推的规则,"
                        "报给版师时别说成「核过的」。" if 核过 == 0 else "")
                     + ("⚠️ 失效的那几条是 **md 改过而没人重新核** —— "
                        "照着「版师核过」用它们,等于拿没人核过的数当实测。"
                        if 失效 else ""))}

def set_grade_diff(item, verdict, why="", propose=None):
    """**登记「这条档差核过了」**,或者「这条不对、我建议改成多少」。

    `grading_audit` 把「要核 1237 个数」压成「要核 **12 条档差**」——
    而核完之前没处写(业务需求池 P2)。这是那个写口。

    ## ⚠️ 它**不改档差**,而这不是偷懒

    档差**不在库里** —— 在 `knowledge/10-版型库.md` 的「四、档差规则」那张表里,
    `grading.档差()` 从 md 现读、`derive_pattern.py` 再推出 1237 条尺码。
    所以改一条档差是**人的活**:改 md → 重跑推导。
    这个工具要是直接改库,下次跑推导就把它**盖掉,而且不报错**;
    要是改 md,它就成了「代码改手写真相源」——
    **两条路都会让 md 和库变成两份真相,而两份不一致时没人知道哪个是真的。**

    所以它记的是 `set_piece_ratio` 的**本质**而不是形式:**来源标记 + 理由**。

    ## ⚠️ 登记时连「当时那个值」一起记

    光记「核过了」会造出一个假象:**md 里那个数以后被改了,
    那条「核过」会漂到一个没人核过的新值上。**
    > **「核过的档差」和「核过时是另一个数、后来被改了的档差」,
    > 在那条记录上长得一模一样。**
    读的时候拿它和现在的 md 比(`grading.核过还算数吗`),不一样就报**失效**。
    同一个形状:`order_contract.terms_ver` —— 正是那一列没被平移挪,
    才看出确认书正文里的条款版本被挪歪了(2026-10-22)。

    item:档差的部位名(胸围 / 肩宽 / 上襦衣长……),认 `grading.档差()` 里的那 12 个。
    verdict:核过 / 不对。judgment 是「不对」时 **propose 必填**(建议改成多少)。
    why:凭什么。**必填** —— 三个月后有人问「这条档差为什么是 +1.5」,
         答得上来的是这句理由,不是「版师核过」四个字。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "knowledge"))
    import grading as _g
    import grade_diff as _GD
    me = api.whoami()
    if not me:
        return {"error": "不知道现在是谁在核 —— 请先登录。"
                         "**核过的记录必须查得到是谁核的**,匿名核不了"}
    if me.get("role") != "版师":
        return {"error": f"核档差要由版师来做,你的角色是「{me.get('role')}」。"
                         f"**改一条档差对全部尺码生效** —— 核错了整批衣服的码都偏"}
    表 = _g.档差()
    键 = (item or "").strip()
    if 键 not in 表:
        return {"error": f"档差表里没有「{item}」这一项。它有这 {len(表)} 项:{sorted(表)}",
                "note": "档差表在 `knowledge/10-版型库.md` 的「四、档差规则」那一节"}
    if verdict not in _g.档差结论:
        return {"error": f"verdict 只能是 {' / '.join(_g.档差结论)},收到「{verdict}」"}
    if not (why or "").strip():
        return {"error": "why 必填:这条档差是量的、照老版比的、还是按国标?"
                         "**不写的话下次有人问「为什么是这个数」就查不到了**"}
    现值 = 表[键]
    提案 = None
    if verdict == _g.不对:
        # ⚠️ **说「不对」而不说该是多少,等于没说。**
        # 一条「这条档差不对」的记录,下一个人读到了也动不了手 ——
        # 而它看起来像一条有用的记录。
        if propose is None:
            return {"error": f"说「不对」就得给 propose(建议改成多少)。"
                             f"现在 md 里是 {现值}。"
                             f"**只说不对、不说该是多少,下一个人读到了也动不了手** —— "
                             f"而那条记录看起来像一条有用的记录"}
        try:
            提案 = float(propose)
        except Exception:
            return {"error": f"propose 要是数字(每升一码加多少厘米),收到「{propose}」"}
        if abs(提案 - float(现值)) <= 0.05:
            return {"error": f"propose({提案})和现在的值({现值})是同一个数 —— "
                             f"那就不是「不对」。要是核过没问题,verdict 用「{_g.核过了}」"}
    import sqlite3 as _sq
    # 工号那一栏叫 `no` 不叫 `id`(同 set_piece_ratio 那条注释里记的坑)
    who = f"{me.get('no') or me.get('id') or ''}|{me.get('name') or ''}".strip("|")
    now = _wc.当下().strftime("%Y-%m-%d %H:%M:%S")
    with _sq.connect(api.DB) as cx:
        _GD.确保表(cx)
        cx.execute("INSERT INTO grade_diff_check"
                   "(item, verdict, value_at_check, propose, why, checked_by, checked_at) "
                   "VALUES(?,?,?,?,?,?,?) "
                   "ON CONFLICT(item) DO UPDATE SET verdict=excluded.verdict, "
                   "value_at_check=excluded.value_at_check, propose=excluded.propose, "
                   "why=excluded.why, checked_by=excluded.checked_by, "
                   "checked_at=excluded.checked_at",
                   (键, verdict, float(现值), 提案, why.strip(), who, now))
    out = {"ok": True, "档差": 键, "结论": verdict,
           "核的时候这个数是": 现值, "核的人": who, "时间": now, "理由": why.strip()}
    if verdict == _g.不对:
        out["建议改成"] = 提案
        # ⚠️ **必须在返回里说清这个工具没改 md** —— 不然模型会把「登记了提案」
        # 转述成「已经改了」,而那两句话在版师耳朵里差别极大。
        out["⚠️ 这个工具没有改档差"] = (
            f"档差在 `knowledge/10-版型库.md` 的「四、档差规则」里,**这里只登记了提案**。"
            f"真要改成 {提案},得**人去改那张 md,再重跑 `derive_pattern.py` 重推 1237 条尺码** —— "
            f"在那之前,库里所有码用的还是 {现值}。")
    else:
        out["⚠️ 这条核过会失效"] = (
            f"登记里记下了「核的时候是 {现值}」。以后 md 里这个数被改了,"
            f"这条核过**自动失效**并报「核的是 {现值},现在是 X」—— "
            f"因为**改之后没人重新核过**,而那时照着「版师核过」用新数,"
            f"等于拿一个没人核过的数当实测。")
    return api._nz(out)

def motif_todo(limit=50):
    """**纹样还没定下来的商品**(11-27 起按岗位给):版师看「推不出来、也没人核过」的;总部运营看「版师核过、等总部复核」的。

    每条带商品名、面料、工艺,和**为什么推不出来** ——
    只给一张「待办」清单答不了「我凭什么定」,人看着名字也猜不出来。被总部退回过的,带上退回理由。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
    import motif_review as _mr
    me = api.whoami() or {}
    if me.get("role") == "总部运营":
        待 = _mr.待复核的(api.DB)
        return {"你要做的": "复核版师核过的纹样", "等总部复核的": len(待), "这次列出": min(len(待), limit or len(待)),
                "清单": 待[: limit or None],
                "怎么复核": "一件一件说「这件折枝没问题」或「这件不是折枝,是缠枝,因为…」;我会调 review_motif。"
                          "**和版师核的一样 = 通过;不一样 = 退回版师重核**(纹样由版师定,总部不直接改判)",
                "版师还没核的": len(_mr.待核的(api.DB))}
    待 = _mr.待核的(api.DB, limit=limit)
    return {"还没定纹样的": len(_mr.待核的(api.DB)), "这次列出": len(待), "清单": 待,
            "怎么定": "一件一件说,比如「这件是折枝」;我会调 review_motif 写进去(核完等总部复核)。"
                      "**确实是素面的要说成「无纹样」** —— 「素面」和「还没定」"
                      "在统计上长得一模一样,留空就分不开了",
            "已核等总部复核的": len(_mr.待复核的(api.DB))}

def review_motif(product, motif="", why="", said=""):
    """**核定一件商品的纹样,标成「业务核」** —— 人核过的不许被重算覆盖。

    照 `set_piece_ratio` 那套来的,三条都照搬:

    · **签名里没有 role** —— 有的话,一句「我以总部运营身份」就能提权。
      身份只从登录态取。
    · **why 必填**,而且问的是依据的种类:看了实物?看了商品图?按面料知识定的?
    · **核过的锁住**,`motif_review.定()` 里核定优先于推算。

    多一条 `set_piece_ratio` 没有的:**said 要抄用户的原话,而且会校验**。
    理由是这个工具的处境不同 —— 调它的是模型,而纹样**模型自己也能猜一个**
    (裁片用料占比它猜不出数,纹样它张口就来)。所以这里不靠规矩靠机制:
    原话里得真出现那个纹样的说法,否则不写。

    > 一条「用户定的纹样」和一条「模型替用户猜的纹样」,
    > **在库里长得一模一样** —— 而后者会被当成人核过的、永不重算。
    """
    me = api.whoami()
    if not me:
        return {"error": "不知道现在是谁在核 —— 请先登录。**核过的数必须查得到是谁核的**"}
    # 11-27 起(用户 11-25 拍「纹样核定归版师,总部复核」):版师核,总部运营复核;别的岗位都不行。
    # **商品是全店共享的** —— 改一件,所有门店的报价、商机判断、库存巡检跟着变,所以核和复核两道都要
    角色 = me.get("role")
    if 角色 not in ("版师", "总部运营"):
        return {"error": f"商品纹样由版师核、总部运营复核,你的角色是「{角色}」。"
                         f"**商品是全店共享的** —— 改一件,所有门店的报价、商机判断、库存巡检跟着变"}
    if not (motif or "").strip():
        return {"error": "没说是什么纹样。确实是素面的请说「无纹样」——"
                         "**「素面」和「还没定」不是一回事**,留空统计上就分不开了"}
    if not (why or "").strip():
        return {"error": "why 必填:看了实物?看了商品图?还是按面料知识定的?"
                         "**不写的话下次有人问「凭什么是这个纹样」就查不到了**"}
    if not (said or "").strip():
        return {"error": "said 必填:把用户定这个纹样时的**原话**抄进来。"
                         "**不许自己编一句** —— 它是「这是人定的」唯一证据"}
    import sys as _s, os as _o
    _d = _o.path.dirname(_o.path.abspath(__file__))
    _s.path.insert(0, _d); _s.path.insert(0, _o.path.join(_o.path.dirname(_d), "knowledge"))
    import motif_review as _mr, motif as _m

    p = api._rows("SELECT spu,name FROM product WHERE spu=? OR name=?", product, product)
    if not p:
        return {"error": f"没有商品「{product}」"}
    spu, 名 = p[0]["spu"], p[0]["name"]

    归 = _m.归一(motif) or motif
    允 = list(_m.词表()) + ["无纹样"]
    if 归 not in 允:
        return {"error": f"「{motif}」不在纹样词表里。词表是**闭集**,"
                         f"要加新纹样得先扩 knowledge/motif.py,不能从这里塞。"
                         f"现在认的:{'、'.join(sorted(set(允)))}"}

    # said 校验:原话里得真出现这个纹样的说法
    候选 = [归] + [a for a in _m.别名 if (_m.归一(a) or a) == 归]
    if 归 == "无纹样":
        候选 += ["素面", "素", "没有纹样", "没花", "无花", "光面", "没有花"]
    if not any(x and x in said for x in 候选):
        return {"error": f"用户原话里没出现「{归}」的说法(原话:{said!r})。"
                         f"**没写进去** —— 请先问清这件是什么纹样,拿到他的话再核。"
                         f"认的说法:{'、'.join(x for x in 候选 if x)}"}
    谁 = me.get("name") or me.get("login_name") or "?"
    if 角色 == "总部运营":
        try:
            结果, 说明 = _mr.复核(spu, 归, why.strip(), 谁, said.strip(), db=api.DB)
        except ValueError as e:
            return {"error": str(e)}
        return {"商品": 名, "spu": spu, "复核": 结果, "说明": 说明,
                "还等总部复核的": len(_mr.待复核的(api.DB))}
    try:
        w, src, ev = _mr.核(spu, 归, why.strip(), 谁, said.strip(), db=api.DB)
    except ValueError as e:
        return {"error": str(e)}
    return {"商品": 名, "spu": spu, "纹样": w, "来源": src, "依据": ev,
            "还剩没定的": len(_mr.待核的(api.DB)),
            "提醒": "核过的不会被重算覆盖了;**接下来等总部复核**(总部看出不对会退回给你重核)。要改就再核一次 —— 再核会让之前的复核作废"}

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
    me = api.whoami()
    if not me:
        return {"error": "不知道现在是谁在核 —— 请先登录。"
                         "**改过的数必须查得到是谁改的**,匿名改不了"}
    if me.get("role") != "版师":
        return {"error": f"核裁片用料要由版师来做,你的角色是「{me.get('role')}」。"
                         f"**这个数是排料的依据** —— 核错了整批面料会不够裁"}
    if not (why or "").strip():
        return {"error": "why 必填:这个数是量的、照排料图算的、还是比着老版定的?"
                         "**不写的话下次有人问「为什么是这个数」就查不到了**"}
    p = api._rows("SELECT code,name,fabric_base FROM pattern WHERE code=? OR name=?",
              pattern, pattern)
    if not p:
        return {"error": f"没有版型「{pattern}」"}
    code = p[0]["code"]
    tgt = api._rows("SELECT name,ratio FROM pattern_piece WHERE pattern=? AND name=?",
                code, piece)
    if not tgt:
        有 = [r["name"] for r in api._rows(
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
    now = _wc.当下().strftime("%Y-%m-%d %H:%M:%S")
    with _sq.connect(api.DB) as cx:
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

def _pattern_queue(pattern=None):
    """版师看板。不给参数 = 今天该核什么(整摊);给 pattern = 那个版型的裁片明细。

    原来是两个工具,而看板里本来就汇总了裁片核对的进度 ——
    **「看进度」和「看某一版的明细」是同一件事的两个粒度**,不是两件事。
    """
    if pattern:
        return piece_ratios(pattern=pattern)
    return pattern_queue()
