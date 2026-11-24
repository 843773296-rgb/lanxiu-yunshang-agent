"""从 backend/api.py 拆出来的「api_wearer」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api
import sqlite3, os, json, sys, re, subprocess
import worldclock as _wc


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
        with api._c() as c:
            return api._scheme_ref.展开(c, r)

    if scheme_id:
        rs = api._rows("SELECT * FROM scheme WHERE id=?", scheme_id)
        if not rs:
            return {"error": f"没有方案 {scheme_id}"}
        d = 展开(rs[0])
        cu = api._rows("SELECT name FROM customer WHERE id=?", rs[0]["customer_id"])
        d["客户"] = cu[0]["name"] if cu else None
        # 同一客户还有哪些方案 —— **并行是常态**,不告诉模型它就会以为只有这一条
        兄弟 = api._rows("SELECT id,name,status FROM scheme WHERE customer_id=? AND id<>?"
                    " ORDER BY updated DESC", rs[0]["customer_id"], scheme_id)
        d["该客户的其他方案"] = 兄弟
        # 这条方案下过哪些单。**空列表和「还没下单」是同一件事,要说出来** ——
        # 不返回这个字段的话,「查过了没有」和「根本没查」在答复里长得一样。
        单 = api._rows("SELECT id,kind,status,amount,created FROM ordr WHERE scheme_id=?"
                  " ORDER BY created", scheme_id)
        d["由这条方案下的订单"] = 单
        if not 单:
            d["下单情况"] = ("这条方案还没有下过单。"
                          + ("**已锁定不等于已下单** —— 客户拍过板,单还没开。"
                             if d["状态"] == "已锁定" else ""))
        # **把「已锁定几条」直接算好摆出来。** 业务 2026-09-18 定了可以多条同时锁,
        # 于是「锁定那条」不再是一个能消歧的说法。让模型自己去数兄弟列表里有几条锁定,
        # 是把一个**它很容易数错、而且数错了看不出来**的活交给它。
        锁 = api._scheme_ref.已锁定的(兄弟) + \
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
        人们, _ = api._认客户(customer)
        if not 人们:
            return {"error": f"没有客户「{customer}」"}
        ph, ids = api._在(人们[0]["关联"])          # 软合并:关联档的方案一起列
        sql += f" AND customer_id IN ({ph})"
        args += ids
    if status:
        sql += " AND status=?"
        args.append(status)
    rs = api._rows(sql + " ORDER BY updated DESC", *args)
    return {"hit": len(rs), "schemes": [展开(r) for r in rs],
            "note": "要看某一条的明细,拿方案号再调一次。"
                    "**同一客户并行多条是常态** —— 客户说「那个方案」时先问清是哪一条。"}

def get_capacity(craft=None, workdays=None, from_date=None):
    """产能排期。不传 craft 就是全工坊负载概览(瓶颈在哪个工种)。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","knowledge"))
    import capacity as cap
    if not craft:
        # 日期由这一层给世界的今天 (10-15:口径模块不许自己取日期 —— 不传它就落到**机器的今天**,平移没跑成的那天会和别处差一天)
        return cap.overview(from_date or _wc.今天().isoformat())
    k,e=api._resolve(craft,"工艺")
    if e: return {"error":e}
    r=cap.when_free(k["code"], float(workdays or 10), from_date or _wc.今天().isoformat())
    if not r.get("error"): r["工艺"]=k["name"]
    return r

def fit_customers(本店=None):
    """量过体的客户 —— 只有这些人能算推荐尺码。

    `本店`:按门店划范围(用户 10-23 拍;11-11 补齐)。None = 不限(跨店角色 / 内部调用);
    否则只列这家店的客户 —— 由 HTTP 口按登录身份给,不收前端传的门店。"""
    片, 参 = "1=1", []
    if 本店 is not None:
        import shop_key as _SK, contextlib as _cl
        with _cl.closing(api._c()) as _x:
            片, 参 = _SK.门店条件(_x, 本店, "c")
        片 = 片 or "0"
    return {"rows": api._rows(
        "SELECT c.id,c.name,MAX(r.method) method,COUNT(DISTINCT r.item) items,"
        " MIN(r.tpl) tpl_code,"
        # 体型特征挂**着装人**。这里按「该客户档案下的着装人」聚合 ——
        # 用于列表概览;真正推尺码时必须**指定是谁**,见 kb_fit。
        " (SELECT GROUP_CONCAT(feature,'、') FROM body_feature b"
        "  JOIN wearer w ON w.id=b.wearer_id WHERE w.customer_id=c.id) feature"
        " FROM customer c JOIN measure_rec r ON r.customer_id=c.id"
        f" WHERE {片}"
        " GROUP BY c.id,c.name ORDER BY c.name", *参)}

def 本店范围(me):
    """登录的人能看哪家店的客户 → None 表示跨店(全部),否则是那一家店的名字。

    口径只有一条:`跨店角色`(总部运营 / 售后)看全部,其余角色只看自己那家店。
    客户读接口、方案页的客户搜索都调这一个函数 —— **同一个「本店」,两处各写一套,迟早对不上**。
    ⚠️ 返回空串(登录的人没挂门店)时,怎么处置由调用方定:客户搜索按「只看空店」收紧(搜不到任何人),
    客户读接口沿用它原来的写法(空串不加门店条件)—— 那一处不是这次改的,没动它的口径。"""
    me = me or {}
    # 「系统」= 内部调用的显式身份(api.系统身份,11-24):读得全,但**只在这一处**认它,写口的闸不认
    return None if (me.get("role") in api.跨店角色 or me.get("role") == api.系统身份["role"]) else (me.get("shop") or "")

def search_fit_customers(q, me, 每页=None, 页=1):
    """方案页用:按姓名 / 手机尾号 / 客户号搜**量过体**的客户,只搜得到登录的人那家店的(跨店角色除外)。

    原来方案页一次把 5155 位量过体的客户全拉下来平铺成下拉框 —— 不分门店、也没法搜。
    人群口径和 `fit_customers` 一样(有量体记录的才列,没量过体推不了码)。
    返回里**不给完整手机号**,只给尾号 —— 顾问拿尾号跟客户对一下就够了。"""
    每页 = 每页 or api.方案搜客户_每页
    try:
        页 = max(1, int(页 or 1))
    except (TypeError, ValueError):
        页 = 1
    q = (q or "").strip()
    if not q:
        return dict(rows=[], 共=0, 说明="输入姓名、手机尾号或客户号来搜")
    范围 = 本店范围(me)
    条件, 参 = ["c.name LIKE ?", "UPPER(c.id)=UPPER(?)"], [f"%{q}%", q]
    if q.isdigit() and len(q) >= api.方案搜客户_尾号最少位数:
        条件.append("c.phone LIKE ?"); 参.append(f"%{q}")
    where = "(" + " OR ".join(条件) + ")"
    if 范围 is not None:
        # 按门店码筛。`本店范围()` 给空串(登录的人没挂门店)时按「搜不到任何人」收紧 ——
        # 原来写 `c.shop=''` 也是 0 行,`1=0` 只是把它写明白,口径没动
        _片, _参 = api._门店条件(范围, "c")
        where += f" AND {_片 or '1=0'}"; 参.extend(_参)
    base = (" FROM customer c WHERE " + where +
            " AND EXISTS(SELECT 1 FROM measure_rec r WHERE r.customer_id=c.id)")
    共 = api._rows("SELECT COUNT(*) n" + base, *参)[0]["n"]
    rs = api._rows(
        "SELECT c.id, c.name, c.shop, SUBSTR(c.phone,-4) 尾号,"
        " (SELECT MAX(r.method) FROM measure_rec r WHERE r.customer_id=c.id) method,"
        " (SELECT COUNT(DISTINCT r.item) FROM measure_rec r WHERE r.customer_id=c.id) items,"
        " (SELECT MIN(r.tpl) FROM measure_rec r WHERE r.customer_id=c.id) tpl_code"
        + base + " ORDER BY (UPPER(c.id)=UPPER(?)) DESC, (c.name=?) DESC, c.name, c.id LIMIT ? OFFSET ?",
        *参, q, q, 每页, (页 - 1) * 每页)
    共页 = max(1, -(-共 // 每页))
    return dict(rows=rs, 共=共, 每页=每页, 页=页, 共页=共页,
                说明=("只列量过体的客户" + ("" if 范围 is None else f",只搜 {范围 or '(你没挂门店)'} 的")
                      + (f";命中 {共} 位,第 {页} / {共页} 页" if 共 > 每页 else "")))

def _名下着装人(customer_id):
    """这条客户档案所属**账户**名下在用的着装人(按 id 排)。

    `kb_fit` 判「判不了」用的候选、方案页让顾问点选的列表,都是这一份 —— 不各写一条查询。
    粒度按账户(身份绑 account,见 CLAUDE.md),和 `kb_fit` 一直用的一致。"""
    return api._rows("""SELECT w.id, w.name, w.relation, w.gender, w.birthday FROM wearer w
                      JOIN customer k ON k.account_id = w.account_id
                     WHERE k.id=? AND w.status='在用' ORDER BY w.id""", customer_id)

def scheme_wearers(customer, me):
    """方案页选定客户后,列出他名下的着装人,让顾问**明确点选一个**(复审第 4 节 B)。

    风险在卡片上写着:选错着装人 = 拿另一个人的尺寸去裁,报表上看不出来。
    所以这里只列、**不标默认**;页面也不替顾问预选第一个。范围和客户搜索同一条(`本店范围`)。"""
    人们, _ = api._认客户(customer)
    if not 人们:
        return dict(error=f"没有客户「{customer}」", code="NO_CUSTOMER")
    cid = 人们[0]["id"]
    范围 = 本店范围(me)
    if 范围 is not None:
        店 = (api._rows("SELECT shop FROM customer WHERE id=?", cid) or [{}])[0].get("shop")
        if 店 != 范围:
            return dict(error=f"这位客户不是本店的(你是 {范围 or '没挂门店'}),看不了", code="OTHER_SHOP")
    本人 = api.本人着装人(cid)
    out = []
    for w in _名下着装人(cid):
        ms, mth, _ = api._以哪次为准(w["id"])
        out.append(dict(w, 本人=(w["id"] == 本人), 量过体=bool(ms), 量体方式=mth))
    return dict(customer=cid, rows=out,
                说明="点选这件衣服穿在谁身上 —— 尺码按选中的那个人出;不替你预选")

def kb_fit(customer, pattern, wearer=None):
    """拿量体记录比对版型尺码表,给出推荐尺码和档位(标准码 / 调号 / 全定制)。

    **wearer 才是正确的粒度** —— 一个账户下几个人,尺寸和体型各不相同。
    只给 customer 时,退回到该账户的「本人」。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","knowledge"))
    import fitting
    人们, _ = api._认客户(customer)          # 软合并:副档号认成主档
    if not 人们: return {"error":f"没有客户「{customer}」"}
    cu=dict(id=人们[0]["id"], name=人们[0]["name"])
    p=api._rows("SELECT code,name,xz,sizes,tpl FROM pattern WHERE code=? OR name=?",pattern,pattern)
    if not p: return {"error":f"没有版型「{pattern}」"}
    p=p[0]
    # ⚠️ **量体按着装人取,取最近一次,只认顾问亲自量的**(2026-09-22 修)。
    # 原来按 customer_id 取:一条档案下 2–4 个人的量体混进一个字典、后写的覆盖先写的 ——
    # 孩子会拿到妈妈的腰围;方式也是按客户 LIMIT 1 取的。161 个客户名下有多人量体。
    # 体型特征那一半早就按着装人取了(见下),量体这一半当时漏了。
    _本人 = api.本人着装人(cu["id"])

    # ── 不知道给谁做就不猜(2026-10-15 业务拍,对齐 can_order) ────────────────
    #
    # ⚠️ 原来不传 `wearer` 就**退到账户「本人」并照常出码** —— 不报错、不提示。
    # 实测同一个客户同一个版型:本人 **L / 调号**,名下第二个着装人 **S / 标准码** ——
    # 差两档尺码、差一个档位,而返回里「客户」两次写的是同一个名字,**看不出这是谁的码**。
    #
    # 而同一条业务红线上,`can_order` 的做法是相反的 —— 它的描述自己写着:
    # 「**判不了不等于可以** —— 客户名下多个着装人而没传 wearer_id 时返回『判不了』
    # 并列出候选,**不替你挑一个**:挑错的话这一单会拿着另一个人的尺寸去裁剪,
    # 而报表上完全正常」。**两个工具两种做法,而 `kb_fit` 是更前置的那个**。
    #
    # 📌 只在**不止一人量过体**时判不了:只有本人量过的话退到本人是唯一选择,
    #    不存在猜错。「量过体」的口径用 `_以哪次为准` 现算 ——
    #    和下面真正推码用的是同一个函数,不再写一份「算不算量过」的判定。
    # ⚠️ 名下有谁按**账户**算(和这个函数一直用的粒度一致,也和 CLAUDE.md
    #    「身份绑 account,不绑 customer」一致)。`can_order` 按的是 **customer**,
    #    两者在少数跨店重复建档的客户上算出来不一样 ——
    #    这一点没统一,业务没拍过,**别静默改它**。
    # ⚠️ 给了着装人,就必须是**这个客户账户名下**的(10-23 方案页接着装人时补的)。
    # 原来不验:传一个别人家的着装人,量体照取、体型照取,返回里「客户」写的却是这位客户 ——
    # 方案页把着装人 id 交给前端去发,前端发什么都会照单推码,那就是「拿另一个人的尺寸去裁」。
    # 按账户核(不限在用),和下面的候选同一粒度。
    if wearer and not api._rows("""SELECT 1 FROM wearer w JOIN customer k ON k.account_id = w.account_id
                                WHERE k.id=? AND w.id=?""", cu["id"], wearer):
        return dict(error=f"着装人 {wearer} 不在「{cu['name']}」名下 —— 不推码", 档位="判不了",
                    note="选错着装人 = 拿另一个人的尺寸去裁;先从这位客户名下重新点选")
    if not wearer:
        _候选 = _名下着装人(cu["id"])
        _量过 = [x for x in _候选 if (api._以哪次为准(x["id"])[0])]
        if len(_量过) > 1:
            return dict(
                档位="判不了",
                理由=(f"「{cu['name']}」这个账户名下有 {len(_量过)} 人量过体,"
                    f"尺寸和体型各不相同 —— **没指定给谁做就不推码**"),
                客户=cu["name"],
                版型=p["name"],
                量过体的有谁=[f"{x['name']}({x['id']},{x['relation']})" for x in _量过],
                怎么办=("把 wearer 一起传进来再问一次。**别让我替你挑** —— "
                     "定制是照着尺寸裁的,挑错了这一单会拿着另一个人的尺寸去裁剪,"
                     "而报表上完全正常"),
                note="**判不了不等于可以**,也不等于需补量 —— 量体记录是全的,"
                     "缺的是「这件衣服穿在谁身上」。")
    _wid0 = wearer or _本人
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","knowledge"))
    ms, mth, _依据 = api._以哪次为准(_wid0)          # 最近一整次亲自量的,缺项不拼(业务 09-22)
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
    _wid = wearer or _本人        # 和上面同一份,不再重查一遍
    fs=[r["feature"] for r in api._rows("SELECT feature FROM body_feature WHERE wearer_id=?", _wid)]
    specs={}
    for r in api._rows("SELECT size,item,value FROM size_spec WHERE pattern=?",p["code"]):
        specs.setdefault(r["size"],{})[r["item"]]=r["value"]
    _sx = (api._rows("SELECT gender FROM wearer WHERE id=?", _wid) or [{}])[0].get("gender") if _wid else None
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
    p=api._rows("SELECT code FROM pattern WHERE code=? OR name=?",pattern,pattern)
    if not p: return {"error":f"没有版型「{pattern}」"}
    m,e=api._resolve(material,"材质")
    if e: return {"error":e}
    kcs=[]
    for k in (crafts or []):
        r,e2=api._resolve(k,"工艺")
        if e2: return {"error":e2}
        kcs.append(r["code"])
    kw=dict(pattern=p[0]["code"], size=size, material=m["code"], crafts=kcs,
            scope=scope, workers=int(workers or 2), craft_names=api._names(),
            from_date=from_date or _wc.今天().isoformat())   # 产能排队从哪天起算:世界的今天(10-15)
    # 下单日不传就给世界的今天 (10-15:口径模块不许自己取日期 —— 不传它就落到**机器的今天**,平移没跑成的那天会和别处差一天)
    return lt.deadline(need_date, from_date or _wc.今天().isoformat(), **kw) if need_date else lt.estimate(**kw)

def _consent_ok(wearer_id, scope="身体数据"):
    r = api._rows("""SELECT 1 FROM consent WHERE wearer_id=? AND scope=? AND revoked_at IS NULL""",
              wearer_id, scope)
    return bool(r)

def _wearer(wid):
    r = api._rows("SELECT * FROM wearer WHERE id=?", wid)
    return r[0] if r else None

def _mask(phone):
    """手机号对外一律脱敏。顾问要的是「认得出是哪个号」,不是号本身。"""
    # 用户 11-22 拍:手机前三后四、固话前三后三,和页面同一个口径(只在 backend/mask.电话 写一次)
    p = (phone or "").strip()
    if len(p) < 7:
        return "—"
    import mask as _mk
    return _mk.电话(p)

def _account(aid):
    """账户的对外视图。**列名写死,不用星号** —— 星号会把 pwd_* 带出来,
    而 _rows 那道锁会当场抛异常。这里主动只取该给的四列。

    login_name 本身也是登录凭据,所以只回答「有没有自设」,不回答「叫什么」。
    """
    if not aid: return None
    # 列名写死,不用星号 —— 星号会把 pwd_* 带出来,_rows 那道锁会当场抛异常
    r = api._rows("SELECT id, phone, login_name, status, created, last_login, contact_pref, "
              "default_addr, home_shop, tos_version, privacy_version, marketing_consent, "
              "closed_at, purge_at, locked_until FROM account WHERE id=?", aid)
    if not r: return None
    a = r[0]
    n = api._rows("SELECT count(*) n FROM wearer WHERE account_id=?", aid)[0]["n"]
    docs = api._rows("SELECT count(*) n FROM customer WHERE account_id=?", aid)[0]["n"]
    stale = [x for x, cur, col in (("服务条款", api.TOS_NOW, "tos_version"),
                                   ("隐私政策", api.PRIVACY_NOW, "privacy_version"))
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
            f"{'、'.join(stale)}已改版(当前 {api.TOS_NOW} / {api.PRIVACY_NOW},"
            f"账户是 {a['tos_version']} / {a['privacy_version']})。"
            "**改了条款而没重新取得同意,等于没同意** —— 下单前请客户在小程序上重新确认。")
    if api.ACCT_ACTION.get(a["status"]):
        d["该怎么办"] = api.ACCT_ACTION[a["status"]]
    if a["status"] == "锁定":
        d["解锁时间"] = a["locked_until"]
    if a["status"] in ("注销中", "已注销"):
        d["注销申请于"] = a["closed_at"]; d["数据清除于"] = a["purge_at"]
    return d

def get_wearer(customer=None, wearer_id=None, account=None):
    """着装人档案:一个账号下都有谁、各自量体到什么时候、哪些该复量了。"""
    import growth
    from datetime import date
    today = _wc.今天()  # 世界的今天(world_meta),不写死 —— 2026-10-01 写死的 08-31 让量体过期判反了
    if wearer_id:
        ws = [w for w in [_wearer(wearer_id)] if w]
    elif account:
        # 手机号是账户主标识,所以直接支持拿手机号查 —— 顾问手边只有手机号的时候最常见
        ws = api._rows("""SELECT w.* FROM wearer w JOIN account a ON a.id=w.account_id
                      WHERE a.id=? OR a.phone=? OR a.login_name=? ORDER BY w.id""",
                   account, account, account)
    elif customer:
        ws = api._rows("""SELECT w.* FROM wearer w JOIN customer c ON c.id=w.customer_id
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
        recs = api._rows("""SELECT item,value,measured_at,method FROM measure_rec
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
    today = _wc.今天()  # 世界的今天(world_meta),不写死 —— 2026-10-01 写死的 08-31 让量体过期判反了
    w = _wearer(wearer_id)
    if not w: return {"error": f"着装人 {wearer_id} 不存在"}
    if not _consent_ok(w["id"]):
        return {"error": "没有有效的身体数据同意,不能推算", "着装人": w["name"]}
    age = growth.age_at(w["birthday"], today) if w["birthday"] else None
    if age is not None and age < 14 and not _consent_ok(w["id"], "未成年人"):
        return {"error": "不满十四周岁,缺少监护人同意,不能推算", "着装人": w["name"]}
    h = api._rows("""SELECT value,measured_at FROM measure_rec WHERE wearer_id=? AND item='MI01'
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
    r["话术"] = growth.sales_line(w["name"], r["长高"], 5.0, r.get("区间")) if r["长高"] > 0 else None
    g = api._rows("""SELECT item,value FROM measure_rec WHERE wearer_id=? AND item IN ('MI03','MI04')
                 ORDER BY measured_at DESC""", wearer_id)
    if g and r["长高"] > 0:
        r["围度"] = {"MI03": "胸围", "MI04": "腰围"}
        r["围度区间"] = {{"MI03": "胸围", "MI04": "腰围"}[x["item"]]:
                        growth.girth_band(x["value"], h[0]["value"], r["预测身高"])
                        for x in g}
        r.pop("围度")
    return r

def _换商品建议(age, gender, 穿那天身高, size):
    """离下单还远时推荐换商品,两种都给(业务 2026-09-22):
    ① 先推**尺寸宽容的定制款** —— 现在下单也不怕长个;② 家长不想定制,再推**现货标品**,按穿那天推算的尺码挑。"""
    child = age is not None and age < 14
    xz = api.TOLERANT_XZ_CHILD if child else api.TOLERANT_XZ_ADULT
    q = ",".join("?" * len(xz))
    定制 = api._rows(f"""SELECT p.spu, p.name, pt.name 版型 FROM product p JOIN pattern pt ON pt.code=p.pattern
                    WHERE p.kind='定制品' AND p.status<>'下架' AND pt.xz IN ({q}) ORDER BY p.spu LIMIT 3""", *xz)
    if child:
        # 童装现货按身高分档(110 / 120 / …),取不小于穿那天身高的最近一档
        档 = str(min(150, max(110, -(-int(穿那天身高) // 10) * 10))) if 穿那天身高 else None
        现货 = api._rows("""SELECT p.spu, p.name, s.size 尺码, SUM(s.stock - COALESCE(s.locked,0)) 可售 FROM product p
                      JOIN sku s ON s.spu=p.spu WHERE p.kind='标品' AND p.gender='童' AND s.size=?
                      AND s.stock - COALESCE(s.locked,0) > 0 GROUP BY p.spu ORDER BY 可售 DESC LIMIT 3""", 档) if 档 else []
    else:
        现货 = api._rows("""SELECT p.spu, p.name, s.size 尺码, SUM(s.stock - COALESCE(s.locked,0)) 可售 FROM product p
                      JOIN sku s ON s.spu=p.spu WHERE p.kind='标品' AND p.gender IN (?, '通用') AND s.size=?
                      AND s.stock - COALESCE(s.locked,0) > 0 GROUP BY p.spu ORDER BY 可售 DESC LIMIT 3""", gender or "女", size) if size else []
    return {"先推 · 尺寸宽容的定制款": 定制 or "没有合适的在售款",
            "家长不想定制 · 现货标品": 现货 or "这个尺码现在没有现货",
            "为什么": "离下单还远,现在定制要拿更旧的量体推更长的跨度;宽容款现在做不怕长个,现货不存在量体过期"}

def plan_for_event(wearer_id, event_date, pattern, material,
                   crafts=None, scope="局部", today=None):
    """场景倒推:为某个日子做一件衣服,什么时候复量、什么时候下单、按多高做。"""
    import growth
    from datetime import date, timedelta
    today = date.fromisoformat(today) if today else _wc.今天()  # 世界的今天(world_meta),不写死 —— 2026-10-01 写死的 08-31 让量体过期判反了
    # 日子没给 / 写错格式:原来直接 TypeError / ValueError 崩掉(/api/wearer-plan 不带参数就 500)。
    # 说清楚要什么格式,不崩(11-11 按门店划范围那一轮顺手查出)
    try:
        ev = date.fromisoformat(event_date)
    except (TypeError, ValueError):
        return {"error": f"用件日期要写成 YYYY-MM-DD,现在是「{event_date}」" if event_date else "要给用件日期(YYYY-MM-DD)"}
    if ev <= today: return {"error": "用件日期已经过了"}

    w = _wearer(wearer_id)
    if not w: return {"error": f"着装人 {wearer_id} 不存在"}
    if not _consent_ok(w["id"]):
        return {"error": "没有有效的身体数据同意,不能推算", "着装人": w["name"]}
    age = growth.age_at(w["birthday"], today) if w["birthday"] else None
    if age is not None and age < 14 and not _consent_ok(w["id"], "未成年人"):
        return {"error": "不满十四周岁,缺少监护人同意,不能推算", "着装人": w["name"]}

    ms = {r["name"]: r["value"] for r in api._rows(
        "SELECT i.name,r.value,r.measured_at FROM measure_rec r"
        " JOIN measure_item i ON i.code=r.item WHERE r.wearer_id=?"
        " ORDER BY r.measured_at", wearer_id)}
    if "身高" not in ms: return {"error": "没量过身高,先约量体", "着装人": w["name"]}
    mdate = api._rows("SELECT max(measured_at) a FROM measure_rec WHERE wearer_id=?",
                  wearer_id)[0]["a"][:10]

    # ① 穿的那天该按多高做 —— **不是今天的身高**
    fc = growth.forecast(w["gender"], w["birthday"], ms["身高"], mdate, ev.isoformat())
    ratio = fc["预测身高"] / ms["身高"]

    # 长度类按身高比例缩放给点估计;围度类只给区间(md 第四节)
    lo_ms, hi_ms = {}, {}
    for k, v in ms.items():
        if k in api.GIRTH:
            b = growth.girth_band(v, ms["身高"], fc["预测身高"])["区间"]
            lo_ms[k], hi_ms[k] = b
        else:
            lo_ms[k] = hi_ms[k] = round(v * ratio, 1)

    pr = api._rows("SELECT code,name,xz,sizes FROM pattern WHERE code=? OR name=?", pattern, pattern)
    if not pr: return {"error": f"没有版型「{pattern}」"}
    pr = pr[0]
    specs = {}
    for r in api._rows("SELECT size,item,value FROM size_spec WHERE pattern=?", pr["code"]):
        specs.setdefault(r["size"], {})[r["item"]] = r["value"]
    import fitting
    szs = pr["sizes"].split(",")
    r_lo = fitting.recommend(lo_ms, pr["code"], szs, specs, pr["xz"], sex=w.get("gender"))
    r_hi = fitting.recommend(hi_ms, pr["code"], szs, specs, pr["xz"], sex=w.get("gender"))
    size_lo, size_hi = r_lo.get("推荐尺码"), r_hi.get("推荐尺码")
    span = size_lo != size_hi
    size = size_hi if span else size_lo    # 跨码时按大的做,靠折边收回来

    # ② / ③ / ④ 三个日期
    ship = ev - timedelta(days=api.FIT_BUFFER)
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
    换商品 = None
    if (latest - today).days > api.FAR_DAYS:
        # 原来是劝「现在不要下单」—— 业务 2026-09-22 改成**推荐换商品**,两种都给(附录 A-24)
        换商品 = _换商品建议(age, w.get("gender"), fc["预测身高"], size)
        warn.append(f"离最晚下单日还有 {(latest - today).days} 天 —— 现在定制这一款,"
                    f"要拿更旧的量体推更长的跨度,误差更大。**推荐换商品**:先推尺寸宽容的定制款,"
                    f"不想定制就推现货标品(见「换商品建议」);坚持要这一款,就等到 {remeasure} 前后复量再下")
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
            "限定": fc["限定"], "提醒": warn, "换商品建议": 换商品,
            "说明": "选码用的是**穿那天的预测身高**,不是今天的身高。"
                    "答案是一个窗口不是一个日期:早下单误差大,晚下单排不上。"}
