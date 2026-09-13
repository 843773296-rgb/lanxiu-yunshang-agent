# -*- coding: utf-8 -*-
"""下单前置规则的两件事:**订单填上着装人** + **量体不许超期**:定制订单下单时,着装人的量体必须在复量周期内。

一份代码,两个调用方:`seed.py` 末尾跑一遍(新库一开始就对),
`tools/migrate_order_measure.py` 对老库跑一遍。
**两条路都得对** —— 只改一边的话,下一个人 reseed 会得到一个不一样的库。

## 为什么原来会生成出违规数据

`seed.py` 里量体日期是 `f"2026-0{6+k%3}-1{k%9} 14:30"` ——
**纯按序号生成,既不看着装人年龄,也不看下单日期**。
于是出现两种坏数据:

    ① 量体比订单还晚(C10026:量体 08-18 14:30,下单同日 09:46)
       —— 这是纯粹的生成器 bug,没有业务含义
    ② 孩子的量体停在半年多以前(王清和 199 天 / 刘星野 272 天,允许 180 天)
       —— 复量周期对未成年是 180 天甚至 120 天,而生成器不知道这回事

## 但**不能全修掉**

`seed.py` 的反例夹具那段写着:
「没有用例的规则可以是错的,而且永远不会被发现 —— **反例在种子数据里是资产**。」

全修完的话,「超期量体不许下单」这条规则**一个用例都没有**,
`order_gate_check` 的锚点会失去它要钉的东西,而检查照样全绿。

所以**留一个,而且是显式留的**:刘星野(11 岁,量体过期 272 天)。
挑他不挑王清和,是因为他超期最狠 —— 边界附近的那个(199/180)
容易被一次无关的数据调整推回合规,**而夹具不该那么脆**。
"""
import os, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import knowledge.growth as G

# **故意留着不修的那些。** 改这里之前先读上面第三段。
#
# ⚠️ 第一版只留了 W10013-2,结果把 W10010-2 修好了 ——
# 而 `boundary_audit.a_expired_order` 写死用的就是 W10010-2。
# **它早就是一个夹具,只是没人声明过。**
# 一个没被声明的资产,和垃圾长得一模一样,下一个人照样会「好心把它补全」。
#
# 所以现在夹具**只有这一处声明**,`boundary_audit` 和 `order_gate_check`
# 都从这儿取 —— 谁要改夹具,改这一行,两边一起跟。
# 只剩一个了。原来还有 W10013-2(刘星野),但她那张单买的是**女款成人装** ——
# 补齐着装人之后,女款正确地匹配到了成年女性,**她本来就不该接那张单**。
# 一个「靠错误匹配才成立」的夹具不是夹具,是另一个 bug。
#
# W10010-2(王清和)是干净的:**童款订单 + 超期量体**,
# 商品性别说得明明白白是给孩子做的,而孩子的量体过期了 199 天。
夹具着装人集 = ("W10010-2",)
夹具着装人 = 夹具着装人集[0]
夹具说明 = "王清和(9 岁)童款订单、量体过期 199 天 —— 供「超期量体不许下单」和边界审计用"


def 挑量体日(下单日, 周期天数, 客户建档日=None):
    """挑一个合规的量体日期。三个约束**同时**要满足:

      · 在下单**之前**
      · 在复量周期**之内**
      · **不早于客户建档日** —— 客户 7 月才建档,量体记录写 4 月,
        那是不可能发生的事。`spec_check` 的 C3 专门管这个,
        实测一次性造出 **56 条**违规。

    第三条是这次栽出来的:我按「下单日往前推周期的三分之一」挑日子,
    完全没看客户是什么时候建的档。**改数据的连带后果,
    往往落在一个和这次改动看起来毫无关系的检查里。**
    """
    d0 = datetime.date.fromisoformat(下单日)
    提前 = max(1, min(周期天数 - 1, 周期天数 // 3))
    d = d0 - datetime.timedelta(days=提前)
    if 客户建档日:
        下界 = datetime.date.fromisoformat(str(客户建档日)[:10])
        if d < 下界:
            # 建档到下单之间取中点;建档当天就下单的话,就用建档当天
            if d0 <= 下界:
                # **建档日晚于下单日 —— 数据本身矛盾,不该在这儿悄悄糊过去。**
                # 糊过去的话会造出一条「量体晚于下单」的记录,
                # 而那正是这次要修的毛病之一。抛出来让人看见。
                raise ValueError(
                    f"客户建档 {下界} 不早于下单 {d0} —— 这两个日期本身就矛盾,"
                    f"挑不出合规的量体日。**先修这两个日期,别在量体上打补丁**")
            d = 下界 + (d0 - 下界) // 2
    return d.isoformat()


def 顶级品类(conn, code):
    """顺着 `category.parent` 爬到顶,返回顶级品类的名字。

    爬而不是截字符串:code 的位数是约定,而 parent 是**结构**。
    截字符串的话,哪天多一级或少一级,截出来的还是个看起来合法的编号。
    """
    if not code: return None
    seen = set()
    cur = code
    while cur and cur not in seen:
        seen.add(cur)
        # **按位置取,不按列名** —— 这个函数会被 row_factory 没设成 Row 的
        # 连接调用(实测就栽了一次:`tuple indices must be integers`)。
        # 一个工具函数不该假设调用方替它配好了 row_factory。
        r = conn.execute("SELECT name,parent FROM category WHERE code=?", (cur,)).fetchone()
        if not r: return None
        名, 父 = r[0], r[1]
        if not 父: return 名
        cur = 父
    return None


def _成年(b, today):
    if not b: return False
    return (datetime.date.fromisoformat(today)
            - datetime.date.fromisoformat(b)).days / 365.25 >= 18


def ensure_wearers(conn, today="2026-09-12", verbose=True):
    """**补齐着装人**:定制行的商品性别在名下找不到人时,给这个客户建一个。

    为什么是补人而不是「挑一个现有的顶上」:
    商品性别说得清清楚楚是童款/男款/女款,而客户名下没有对得上的人 ——
    **这是档案没建全,不是判不了**。真实业务里就是这样:
    太太在系统里,先生和孩子来试穿定做,但没人给他们建档。

    建完的人**要有量体**,而且要落在「下单之前、复量周期之内」——
    定制不能凭空裁,一个没量过体的着装人接不住一张定制单。

    ⚠️ 只补**定制品**行。标品按尺码卖,不需要知道给谁穿。
    """
    import sqlite3 as _sq
    conn.row_factory = _sq.Row
    c = conn
    sys.path.insert(0, os.path.dirname(HERE))
    import knowledge.order_gate as og

    ITEMS = ["MI01", "MI02", "MI03", "MI04", "MI05", "MI06", "MI07",
             "MI08", "MI09", "MI10", "MI11", "MI12", "MI13", "MI14"]
    BASE = {"MI01": 165, "MI02": 52, "MI03": 86, "MI04": 68, "MI05": 92, "MI06": 38,
            "MI07": 56, "MI08": 110, "MI09": 98, "MI10": 34, "MI11": 26, "MI12": 100,
            "MI13": 80, "MI14": 180}
    建 = 0
    需要 = {}          # (客户, 性别) → 最早的那张单的下单日
    for it in c.execute("""SELECT i.order_id, p.gender g, p.category cat,
                                  o.customer_id, o.created
                           FROM ordr_item i JOIN product p ON p.spu=i.spu
                           JOIN ordr o ON o.id=i.order_id
                           WHERE p.kind='定制品' ORDER BY o.created""").fetchall():
        if it["g"] in og.分不出性别的: continue
        ws = [tuple(w) for w in c.execute(
            "SELECT id,name,gender,birthday FROM wearer WHERE customer_id=? "
            "AND status='在用'", (it["customer_id"],))]
        顶 = 顶级品类(c, it["cat"])
        w, _ = og.定位着装人(it["g"], ws, lambda b: _成年(b, today), 顶)
        if w: continue
        if not og.要按人裁吗(顶 or "")[0]: continue      # 配饰/面料不需要人
        # 只有「一个都没有」才补;「两个都对得上」是判不了,补人只会更乱
        cand = [x for x in ws if (not _成年(x[3], today)) if it["g"] == og.童款] or \
               [x for x in ws if _成年(x[3], today) and x[2] == it["g"]]
        if cand: continue
        k = (it["customer_id"], it["g"])
        需要.setdefault(k, it["created"][:10])

    for (cid, g), day in sorted(需要.items()):
        # **取一个库里没有的编号,不要靠「数一数有几个」。**
        # 第一版用 `COUNT(*)` 当后缀,而现有编号不连续
        # (有 W10004-1 和 -2 却没有 -0)—— 当场 UNIQUE 撞车。
        # 和订单号那次是同一个教训:**编号要取没被占的,不是算出来的。**
        n = c.execute("SELECT COUNT(*) FROM wearer WHERE customer_id=?", (cid,)).fetchone()[0]
        while True:
            wid = f"W{cid[1:]}-{n}"
            if not c.execute("SELECT 1 FROM wearer WHERE id=?", (wid,)).fetchone():
                break
            n += 1
        姓 = (c.execute("SELECT name FROM customer WHERE id=?", (cid,)).fetchone()
              or ["某"])[0][:1]
        if g == og.童款:
            # 3–14 岁,按客户号取一个稳定的年龄 —— **不用 random**,
            # 造数据必须可复现,否则两次 seed 出来的库不一样。
            岁 = 3 + (int(cid[1:]) % 12)
            sex = "女" if int(cid[1:]) % 2 else "男"
            bd = (datetime.date.fromisoformat(day)
                  - datetime.timedelta(days=int(岁 * 365.25))).isoformat()
            rel, nm = ("女" if sex == "女" else "子"), f"{姓}小{sex}"
        else:
            岁 = 28 + (int(cid[1:]) % 12)
            sex = g
            bd = (datetime.date.fromisoformat(day)
                  - datetime.timedelta(days=int(岁 * 365.25))).isoformat()
            rel, nm = "配偶", f"{姓}{'先生' if g == '男' else '女士'}"
        h = round(110 + 岁 * 4.2, 1) if 岁 < 18 else (172.0 if g == "男" else 161.0)
        # **account_id 必须跟着客户的账户走。**
        # 第一版传了 None,当场被 `lifecycle_check` 的结构规则拦下:
        # 「身份绑在账户上,不绑门店档案 —— 档案可能有好几条,账户只有一个」。
        # 建数据的时候少填一个外键,**在这张表上看不出问题**,
        # 要到另一个模块的结构检查里才会红。
        acc = (c.execute("SELECT account_id FROM customer WHERE id=?", (cid,)).fetchone()
               or [None])[0]
        c.execute("INSERT INTO wearer(id,customer_id,account_id,name,gender,birthday,"
                  "relation,height,status,created) VALUES(?,?,?,?,?,?,?,?,'在用',?)",
                  (wid, cid, acc, nm, sex, bd, rel, h, day))
        # **同意书要一起建。** 身体数据是敏感个人信息,
        # `lifecycle_check` 有一条结构规则:有身体数据就必须有「身体数据」同意
        # (个保法 28 条);未成年人还要额外一条「未成年人」同意(监护人签)。
        #
        # 这是这一轮第二次栽在「建数据时少填一样」上:
        # 前一次是 `account_id` 传了 None。**在这张表上看不出问题,
        # 要到另一个模块的结构检查里才会红** —— 而报出来的位置
        # 和我改动的位置隔着好几层。
        def _同意(scope, rel):
            n2 = c.execute("SELECT COUNT(*) FROM consent").fetchone()[0]
            while True:
                sid = f"CS{2000 + n2}"
                if not c.execute("SELECT 1 FROM consent WHERE id=?", (sid,)).fetchone():
                    break
                n2 += 1
            c.execute("INSERT INTO consent(id,wearer_id,scope,granted_by,relation,"
                      "channel,granted_at) VALUES(?,?,?,?,?,'门店纸质',?)",
                      (sid, wid, scope, nm if rel == "本人" else 监护人, rel, day))

        监护人 = (c.execute("SELECT name FROM wearer WHERE customer_id=? "
                          "AND relation='本人' LIMIT 1", (cid,)).fetchone()
                  or [nm])[0]
        未成年 = not _成年(bd, today)
        _同意("身体数据", "监护人" if 未成年 else "本人")
        if 未成年:
            _同意("未成年人", "监护人")

        # 量体:落在下单前、复量周期之内的中间位置
        days, _ = G.recheck_cycle(sex, G.age_at(bd, day))
        建档 = (c.execute("SELECT created FROM customer WHERE id=?", (cid,)).fetchone()
                or [None])[0]
        at = 挑量体日(day, days, 建档) + " 14:30"
        for i, item in enumerate(ITEMS):
            v = BASE[item] * (h / 165 if item in ("MI01", "MI08", "MI09", "MI12", "MI14") else 1)
            c.execute("INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by,"
                      "measured_at,method,wearer_id,cond_inner,cond_shoe,cond_breath) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (cid, "MT01", item, round(v + (i % 5) - 2, 1), "60000008",
                       at, "到店", wid, "薄", "赤足", "平静呼气"))
        建 += 1
    if verbose:
        print(f"  [补着装人] 建了 {建} 个(各带 {len(ITEMS)} 项量体,"
              f"落在下单前、复量周期内)")
    return 建


def assign_item_wearers(conn, today="2026-09-12", verbose=True):
    """给**订单行**填着装人 —— 按商品性别定位。

    ## 为什么着装人必须挂在行上

    **一单可以给不止一个人做**:实测 7 单是「两件童款加一件女款」,
    一家三口订同款。着装人挂在订单上,这件事**根本表达不了** ——
    只能挑一个填,而挑谁都不对。

    ## 为什么不能只靠「名下唯一」

    实测 560005 买的是**童装**,却挂在 32 岁的大人身上 ——
    因为那个客户名下只登记了一个着装人,「名下唯一 → 直接填」就填上去了。
    于是复量规则去查大人的量体,而衣服是给孩子做的。
    **规则跑得欢,查的是错的人。**

    所以判据换成:**商品性别自己说得出来是给谁做的**(童 / 男 / 女)。
    通用款分不出,留空。
    """
    import sqlite3 as _sq
    conn.row_factory = _sq.Row
    c = conn
    sys.path.insert(0, os.path.dirname(HERE))
    import knowledge.order_gate as og
    定 = 空 = 0
    # **先清一遍再重填。** 判据换过一次(从「名下唯一/唯一量过体」
    # 换成品类树),而旧判据填进去的行**看起来和新判据填的一模一样** ——
    # 不清就永远留着:配饰行挂着人、女装行挂着旧判据挑的人。
    # 实测就是这样,检查报「对不上」而回填一行都不动(因为它只填空的)。
    c.execute("UPDATE ordr_item SET wearer_id=NULL")
    不用人裁 = 0
    for it in c.execute("""SELECT i.id, p.gender g, p.kind, p.category cat, o.customer_id
                           FROM ordr_item i JOIN product p ON p.spu=i.spu
                           JOIN ordr o ON o.id=i.order_id""").fetchall():
        if it["kind"] != "定制品":
            continue                     # 标品按尺码卖,不需要知道给谁穿
        顶 = 顶级品类(c, it["cat"])
        if not og.要按人裁吗(顶 or "")[0]:
            不用人裁 += 1                 # 配饰/面料部件 —— **不是判不了,是不需要**
            continue
        ws = [tuple(w) for w in c.execute(
            "SELECT id,name,gender,birthday FROM wearer WHERE customer_id=? "
            "AND status='在用'", (it["customer_id"],))]
        w, _ = og.定位着装人(it["g"], ws, lambda b: _成年(b, today), 顶)
        if w:
            c.execute("UPDATE ordr_item SET wearer_id=? WHERE id=?", (w[0], it["id"]))
            定 += 1
        else:
            空 += 1
    if verbose:
        print(f"  [行级着装人] 定了 {定} 行,留空 {空} 行,"
              f"不按人裁的 {不用人裁} 行(配饰/面料部件)"
              f" —— **留空是判不了,不按人裁是不需要,两件事**")
    return 定, 空


def assign_wearers(conn, verbose=True):
    """给订单填「这一单是给谁做的」。**只填能说出理由的,定不了的留空。**

    两档能定:
      ① 客户名下**只有一个**在用着装人 —— 没有别的可能
      ② 多个候选,但**只有一个在下单前量过体** —— 定制不能凭空裁,
         家里只有一个人量过,这单就只能是给他做的

    **两个人都量过的留空**,下单校验会报「判不了」——
    **判不了不等于可以**。猜错的代价不对称:猜对了没人知道,
    猜错了这一单会拿着另一个人的尺寸去裁剪,而报表上完全正常。

    这份逻辑原来只活在迁移脚本里,于是 `seed.py` 生成的新库
    `wearer_id` 全是 NULL —— 规则一条都跑不到,而检查报的是「样本量 0」。
    **老库迁移和新库生成,两条路都要对。**
    """
    import sqlite3 as _sq
    conn.row_factory = _sq.Row
    c = conn
    定, 留空 = 0, 0
    for o in c.execute("SELECT id,customer_id,created,wearer_id FROM ordr").fetchall():
        if o["wearer_id"]:
            continue
        ws = c.execute("SELECT id,name FROM wearer WHERE customer_id=? AND status='在用' "
                       "ORDER BY id", (o["customer_id"],)).fetchall()
        pick = None
        if len(ws) == 1:
            pick = ws[0]["id"]
        elif len(ws) > 1:
            量过 = [w for w in ws if c.execute(
                "SELECT COUNT(*) FROM measure_rec WHERE wearer_id=? AND measured_at<=?",
                (w["id"], o["created"])).fetchone()[0]]
            if len(量过) == 1:
                pick = 量过[0]["id"]
        if pick:
            c.execute("UPDATE ordr SET wearer_id=? WHERE id=?", (pick, o["id"]))
            定 += 1
        else:
            留空 += 1
    if verbose:
        print(f"  [着装人] 定了 {定} 单,留空 {留空} 单"
              f"(定不了的报「判不了」,**判不了不等于可以**)")
    return 定, 留空


def enforce_rows(conn, verbose=True):
    """**按订单行**收一遍:每个被匹配上的着装人,下单前都得有有效的量体。

    `enforce` 管的是订单级,这条管行级 —— 一单可以给不止一个人做。

    实测补齐着装人之后冒出 3 个「被匹配上却一条量体都没有」的人
    (seed 生成的占位配偶,生日全是 1990-05-20)。
    **定制不能凭空裁:被匹配上就必须有量体**,否则这一行落不了地。

    夹具照旧跳过。
    """
    import sqlite3 as _sq
    conn.row_factory = _sq.Row
    c = conn
    ITEMS = ["MI01", "MI02", "MI03", "MI04", "MI05", "MI06", "MI07",
             "MI08", "MI09", "MI10", "MI11", "MI12", "MI13", "MI14"]
    BASE = {"MI01": 165, "MI02": 52, "MI03": 86, "MI04": 68, "MI05": 92, "MI06": 38,
            "MI07": 56, "MI08": 110, "MI09": 98, "MI10": 34, "MI11": 26, "MI12": 100,
            "MI13": 80, "MI14": 180}
    补 = 挪 = 0
    kept = None
    for r in c.execute("""SELECT i.wearer_id, o.created, o.customer_id
                          FROM ordr_item i JOIN ordr o ON o.id=i.order_id
                          JOIN product p ON p.spu=i.spu
                          WHERE p.kind='定制品' AND i.wearer_id IS NOT NULL
                          ORDER BY o.created""").fetchall():
        wid = r["wearer_id"]
        if wid in 夹具着装人集:
            # ⚠️ **夹具的认定搬到了这一层。** 原来它认在 `enforce`(订单级),
            # 而订单级只看 `ordr.wearer_id` —— 亲子装拆成两个 SPU、两行并进同一张单
            # 之后,这张单**合法地有了两个着装人**,订单级正确地判成「判不了」、
            # `wearer_id` 留空,于是整张单被跳过,**夹具凭空消失**。
            #
            # 而这个反例的场景本来就是行级的:「一张单给两个人做,
            # 其中一个的量体过期了」—— 订单级根本表达不了它,
            # 那正是当初把着装人挂到行上的理由。
            # **夹具要挂在它实际存在的那一层。**
            _w = c.execute("SELECT name FROM wearer WHERE id=?", (wid,)).fetchone()
            _m = c.execute("SELECT measured_at FROM measure_rec WHERE wearer_id=? "
                           "AND measured_at<=? ORDER BY measured_at DESC LIMIT 1",
                           (wid, r["created"])).fetchone()
            kept = (_w["name"] if _w else wid,
                    _m["measured_at"][:10] if _m else "无", r["created"][:10])
            continue
        w = c.execute("SELECT id,name,gender,birthday,height FROM wearer WHERE id=?",
                      (wid,)).fetchone()
        if not (w and w["birthday"] and w["gender"]):
            continue
        day = r["created"][:10]
        m = c.execute("SELECT measured_at FROM measure_rec WHERE wearer_id=? "
                      "AND measured_at<=? ORDER BY measured_at DESC LIMIT 1",
                      (wid, r["created"])).fetchone()
        if m:
            exp = G.measure_expired(w["gender"], w["birthday"], m["measured_at"][:10], day)
            if not exp["过期"]:
                continue
        days, _ = G.recheck_cycle(w["gender"], G.age_at(w["birthday"], day))
        建档 = (c.execute("SELECT created FROM customer WHERE id=?",
                          (r["customer_id"],)).fetchone() or [None])[0]
        新 = 挑量体日(day, days, 建档)
        if m:
            旧 = m["measured_at"][:10]
            c.execute("UPDATE measure_rec SET measured_at=? WHERE wearer_id=?",
                      (f"{新} 14:30", wid))
            c.execute("UPDATE growth_forecast SET base_at=? WHERE wearer_id=? AND base_at=?",
                      (新, wid, 旧))
            挪 += 1
        else:
            h = w["height"] or 165.0
            for i, item in enumerate(ITEMS):
                v = BASE[item] * (h / 165 if item in ("MI01", "MI08", "MI09", "MI12", "MI14") else 1)
                c.execute("INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by,"
                          "measured_at,method,wearer_id,cond_inner,cond_shoe,cond_breath) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (r["customer_id"], "MT01", item, round(v + (i % 5) - 2, 1),
                           "60000008", f"{新} 14:30", "到店", wid, "薄", "赤足", "平静呼气"))
            补 += 1
    if verbose:
        print(f"  [行级量体] 补了 {补} 个人的量体,挪了 {挪} 条日期"
              f"(夹具 {夹具着装人集} 跳过)")
    return 补, 挪, kept


def enforce(conn, today=None, verbose=True):
    """把违规的量体日期挪到合规位置。**返回 (修了几条, 留着的夹具)。**

    只挪**日期**,不改测量值 —— 现实里复量拿到的数会变,
    但这里要的是「这条规则有没有在跑」,不是「尺寸准不准」。
    改值会顺带动到版型推档、成长预测那几条链,**改动面越小越好查**。
    """
    conn.row_factory = __import__("sqlite3").Row
    c = conn
    fixed, kept = [], None
    for o in c.execute("SELECT id,created,kind,wearer_id,customer_id FROM ordr "
                       "WHERE wearer_id IS NOT NULL AND kind='定制品订单'").fetchall():
        w = c.execute("SELECT id,name,gender,birthday FROM wearer WHERE id=?",
                      (o["wearer_id"],)).fetchone()
        if not (w and w["birthday"] and w["gender"]):
            continue
        day = o["created"][:10]
        # ⚠️ **和 `order_gate_check` 用同一个比较** —— 取「下单时刻之前」最近的一条,
        # 按**时间戳**比,不按日期比。
        #
        # 第一版按日期写成 `measured_at[:10] < day`(严格早于下单那一天),
        # 于是把 **33 条「当天量体、当天下单」判成了违规** ——
        # 而那恰恰是最正常的流程:顾问上门量完体,客户当场就定了。
        # 一次跑下来改了 33 条日期,**每一条看起来都很有道理**。
        #
        # 教训是老的那条:**同一个判定不许有两套实现。**
        # 检查那边用 `measured_at<=created`,这边用日期比大小,
        # 两边差的就是「当天」这一档,而它正是最常见的一档。
        m = c.execute("SELECT rowid AS rid,measured_at FROM measure_rec WHERE wearer_id=? "
                      "AND measured_at<=? ORDER BY measured_at DESC LIMIT 1",
                      (w["id"], o["created"])).fetchone()
        # 这一条是不是故意留的夹具
        if w["id"] in 夹具着装人集:
            kept = (w["name"], (m["measured_at"][:10] if m else "无"), day)
            continue
        if m:
            exp = G.measure_expired(w["gender"], w["birthday"], m["measured_at"][:10], day)
            if not exp["过期"]:
                continue
        # 没有下单前的量体,或者有但超期了 —— 两种都要挪一条到合规位置。
        m = m or c.execute("SELECT rowid AS rid,measured_at FROM measure_rec "
                           "WHERE wearer_id=? ORDER BY measured_at LIMIT 1",
                           (w["id"],)).fetchone()
        if not m:
            continue
        # 挪到「下单前、周期之内」的中间位置 —— 现实里就是
        # 顾问发现超期、叫客户来复量,然后才下单。
        days, _ = G.recheck_cycle(w["gender"], G.age_at(w["birthday"], day))
        建档 = (c.execute("SELECT created FROM customer WHERE id=?",
                          (o["customer_id"],)).fetchone() or [None])[0]
        新 = 挑量体日(day, days, 建档)
        旧日 = m["measured_at"][:10]
        c.execute("UPDATE measure_rec SET measured_at=? WHERE wearer_id=?",
                  (f"{新} 14:30", w["id"]))
        # **推算留档要跟着走。** `spec_check` 的 G3 要求
        # 「推算留档能追到它依据的那次量体」—— 挪了量体日期不挪留档,
        # 那条链当场断掉,而且断在一个和这次改动**看起来毫无关系**的检查里。
        # 改数据的连带后果,往往比改动本身更难查。
        c.execute("UPDATE growth_forecast SET base_at=? WHERE wearer_id=? AND base_at=?",
                  (新, w["id"], 旧日))
        fixed.append((w["name"], m["measured_at"][:10], 新, day))
    if verbose:
        for nm, old, new, day in fixed:
            print(f"  [修] {nm}:量体 {old} → {new}(下单 {day})")
        if kept:
            print(f"  [留] {kept[0]}:量体 {kept[1]},下单 {kept[2]} —— **反例夹具**,"
                  f"{夹具说明}")
    return len(fixed), kept
