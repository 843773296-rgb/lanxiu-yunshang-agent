#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑一条**完整的客户旅程**:预约 → 上门 → 量体 → 量体数据 → 订单 → 订单完成。

## 为什么不是「插几行数据」

插行只保证表里有东西,不保证**这些东西彼此对得上**。
走真实代码路径的数据,是被同一套校验挡过一遍的 ——
所以它既是数据,也是一次端到端验证:哪一环走不通,当场就知道。

## 哪些环走了真路径,哪些是直插

这条链上**有两环根本没有写入路径**:量体和订单。
系统里能读它们,但没有任何东西能创建它们。

    ✅ 真路径   预约  booking.book()        —— 客户手机端那条,带三道闸
    ✅ 真路径   派单  route() / dispatch()  —— 有归属顾问自动派,没有则落池
    ✅ 真路径   上门  tasks.assign_task()   —— 走类型规范、时段冲突检查
    ✅ 真路径   完成  tasks.finish_task()   —— 只能本人完成、总结必填
    ⚠️ 直插     量体  没有写接口
    ⚠️ 直插     订单  没有写接口
    ✅ 真路径   推进  transit("bk-order")   —— 一档一档走状态机,跳档会被拒

**直插的那三环不受任何业务规则约束** —— 这正是这个脚本要暴露的:
它们现在只能靠人手工保证一致,而手工保证的东西迟早会不一致。
脚本最后会把这份「哪些有保护、哪些没有」列出来。

用法:
    python3 tools/run_journey.py            跑 3 条
    python3 tools/run_journey.py 5          跑 5 条
    python3 tools/run_journey.py --dry      只看会发生什么,不写库
"""
import os, sys, json, random, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, ROOT)
DB = os.path.join(ROOT, "backend", "lanxiu.db")

G, R, Y, B, D = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"

# 基准日:**从 seed.py 读,不在这儿抄一份**。
# idle_days 的口径是「建库那天的快照」,spec_check 的 C5 也从同一处读 ——
# 两边各抄一份的话,改了种子的基准日,造数据和检查就会在不同的日子上比。
import re as _re
try:
    _BASE_DAY = _re.search(r'TODAY\s*=\s*"(\d{4}-\d{2}-\d{2})"',
                           open(os.path.join(ROOT, "backend", "seed.py"),
                                encoding="utf-8").read()).group(1)
except Exception:
    _BASE_DAY = "2026-08-31"
REAL, RAW = f"{G}真路径{D}", f"{Y}直插{D}"


def q(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def ex(sql, *a):
    with sqlite3.connect(DB) as c:
        c.execute(sql, a)


def pick_customers(n):
    """挑能安全跑旅程的客户。

    **四类**必须排除,每一类都栽过:

    · **反例夹具**(E-* 共 14 个)—— 种子里写着「⚠️ 不许补全」。
      我第一版挑到了 E-A4-01「人工调整 15 天前」,给它加了一笔订单、
      改了累计金额和最近互动 —— **而它的 last_interact 正是生命周期真值的依据**。
    · **客户合并用例**(C21* 共 32 个,对应 15 条 BP-02 真值)——
      那 16 对是「疑似重复档案」,改它们的字段会动到评测答案。
    · **被评测引用的客户** —— 这一类最难看见:它们**不是夹具**,就是普通客户,
      但某条评测用例的真值依赖它们身上的某个事实。
      栽过一次:C10017 原来只有 3 项量体记录(「记录不全」),
      我给他补了 5 项完整的 —— **售后判责那条用例的真值当场翻了**
      (「记录不全 · 我方免费改」变成规则算出的「客方 · 收费改」)。
      夹具和普通数据之间有边,**而那条边从客户这一侧看不见**。
      现在把四种引用都排掉:售后判责的维保单、客户合并、押金退款、truth 表提到的。
    · **一号多档**(库里有 16 个)—— book() 按手机号找人,
      多条时取最早建档那条,所以脚本挑的那条不一定是最后下单的那条,
      跑出来的数据会自相矛盾。这个 bug 已修(会记台账),但脚本仍然避开它们,
      **因为这里要的是干净数据,不是再验一次那个 bug**。

    **夹具被污染时不会报错** —— 它只是让某条评测下次给出一个不同的答案,
    而没人会想到去查是三周前一个造数据的脚本动的。
    """
    return q("""SELECT c.id,c.name,c.phone,c.shop,c.advisor FROM customer c
                WHERE c.archived=0 AND c.phone NOT LIKE 'DELETED%'
                  AND c.name<>'已注销用户'
                  AND c.id NOT LIKE 'E-%'          -- 反例夹具
                  AND c.id NOT LIKE 'C21%'         -- 客户合并用例
                  -- 被评测引用的:动它们身上的事实,会翻掉某条用例的真值
                  AND c.id NOT IN (SELECT customer_id FROM maintain
                                   WHERE id IN (SELECT ref_id FROM task WHERE type='售后判责'))
                  AND c.id NOT IN (SELECT customer_id FROM deposit
                                   WHERE id IN (SELECT ref_id FROM task WHERE type='财务人工任务'))
                  AND c.id NOT IN (SELECT customer_id FROM aftersale)
                  AND (SELECT COUNT(*) FROM customer d
                       WHERE d.phone=c.phone AND d.archived=0) = 1   -- 一号一档
                  AND (SELECT COUNT(*) FROM schedule s
                       WHERE s.customer_id=c.id AND s.type='预约到店' AND s.status='有效') = 0
                ORDER BY RANDOM() LIMIT ?""", n)


def pick_repeat(n):
    """**回头客**:已经走过一趟、现在手上没有在办预约的。

    加这条是因为一次性客户池会用完(31 个跑完就没了),而现实里
    **回头客本来就该有多次预约和多次订单** —— 一个只有一次消费的客户库,
    RFM 的 F(频次)这一维永远分不出层来。

    安全前提和 pick_customers 一样(排掉夹具/评测引用/一号多档),
    额外要求:上一趟的订单已经走到终态 —— **一个客户不该同时有两张在制的定制单**,
    那在现实里也不成立(版师手上一件一件做)。
    """
    return q("""SELECT c.id,c.name,c.phone,c.shop,c.advisor FROM customer c
                WHERE c.archived=0 AND c.phone NOT LIKE 'DELETED%'
                  AND c.name<>'已注销用户'
                  AND c.id NOT LIKE 'E-%' AND c.id NOT LIKE 'C21%'
                  AND c.id NOT IN (SELECT customer_id FROM maintain
                                   WHERE id IN (SELECT ref_id FROM task WHERE type='售后判责'))
                  AND c.id NOT IN (SELECT customer_id FROM deposit
                                   WHERE id IN (SELECT ref_id FROM task WHERE type='财务人工任务'))
                  AND c.id NOT IN (SELECT customer_id FROM aftersale)
                  AND (SELECT COUNT(*) FROM customer d
                       WHERE d.phone=c.phone AND d.archived=0) = 1
                  AND (SELECT COUNT(*) FROM schedule s
                       WHERE s.customer_id=c.id AND s.type='预约到店' AND s.status='有效') = 0
                  -- 走过一趟(量体记录连着上门任务的那种)
                  AND EXISTS (SELECT 1 FROM measure_rec m
                              WHERE m.customer_id=c.id AND m.schedule_id IS NOT NULL)
                  -- 上一趟的单已经收尾 —— 不该同时有两张在制的定制单
                  AND NOT EXISTS (SELECT 1 FROM ordr o WHERE o.customer_id=c.id
                                  AND o.status NOT IN ('完成','取消'))
                ORDER BY RANDOM() LIMIT ?""", n)


def journey(cust, dry=False):
    """走完一条。任何一步炸了都**说清楚炸在哪**,不让整批停下来。

    上一版没有这层:第 31 条订单号撞了,`UNIQUE constraint failed` 直接掀了整个进程,
    前 30 条的结果一行没打印,而库里留着半条旅程(量体写了、订单没写、时间没挪回过去)。
    **一个造数据的脚本崩在半路,留下的是看起来正常的残缺数据。**
    """
    try:
        return _journey(cust, dry)
    except Exception as e:
        return [("✗ 崩了", f"{R}异常{D}",
                 f"{type(e).__name__}: {e}  —— **这一条可能留了半截在库里**,"
                 f"跑 spec_check 看有没有孤儿")], None


def _journey(cust, dry=False):
    """走完一条。返回每一环的结果。"""
    import booking, tasks, tasktypes as tt
    steps = []
    now = datetime.datetime.now()

    # ── ① 预约(真路径:客户手机端那条)────────────────────────────
    #
    # **整条旅程往过去排,不往未来排。**
    # 第一版从今天往后排(预约 +2~9 天、上门再 +1、订单再走 30~45 天),
    # 于是整条链全在未来:客户「已经上门量过体」而那天还没到,
    # 订单「已完成」而完成日在 11 月。C4 检查当场抓到 248 条未来时间。
    #
    # 这不是时间戳填错,是**方向反了** ——
    # 一条「已完成」的旅程,它的每一步本来就都发生过了。
    #
    # 但 book() 会拒绝过去的时间(那是对的:客户不能预约昨天)。
    # 所以:**预约按未来下单,拿到单号之后把整条链的时间改写到过去** ——
    # 走的还是真路径,只是把这条旅程挪到它本来该在的时间上。
    # 往前挪多少 —— **不能挪到客户建档之前**。
    # 第一版固定挪 50~120 天,结果有客户是今年才建的档,预约被挪到了建档之前,
    # C3(任何记录不早于所属对象的创建时间)当场抓到 8 条。
    # **「往过去挪」有个下界,而这个下界因客户而异。**
    _created = q("SELECT created FROM customer WHERE id=?", cust["id"])[0]["created"]
    try:
        _room = (datetime.date.today() - datetime.date.fromisoformat(_created[:10])).days - 20
    except Exception:
        _room = 120
    span = random.randint(30, max(31, min(120, _room)))   # 这条旅程发生在多少天前
    when = (now + datetime.timedelta(days=random.randint(2, 9))).replace(
        hour=random.choice([10, 11, 14, 15, 16]), minute=0, second=0, microsecond=0)
    shift = datetime.timedelta(days=span + 9)   # 事后整体往前挪这么多
    if dry:
        steps.append(("① 预约", REAL, f"会调 booking.book({cust['phone']}, {when:%m-%d %H:%M})"))
        return steps, None
    r = booking.book(dict(phone=cust["phone"], when=when.strftime("%Y-%m-%dT%H:%M"),
                          need="到店量体 · 定制"))
    if not r.get("ok"):
        steps.append(("① 预约", REAL, f"{R}被拒{D}:{r.get('reason','')[:60]}"))
        return steps, None
    appt, task = r["appt"], r["task"]
    who = "自动派给归属顾问" if r["assigned"] else f"{Y}落待分配池{D}({r['code']})"
    steps.append(("① 预约", REAL, f"{appt} / 任务 {task} · {who}"))

    # ── ② 没派出去的先分派(真路径)─────────────────────────────
    t = q("SELECT * FROM schedule WHERE id=?", task)[0]
    if not t.get("assignee_no"):
        sg = booking.suggest(t)
        if not sg:
            steps.append(("② 分派", REAL, f"{R}提不出建议{D} —— 这个门店没有在职顾问"))
            return steps, None
        mgr = q("SELECT no,name,role,shop FROM staff WHERE role='店长' AND shop=?", t["shop"])
        if not mgr:
            steps.append(("② 分派", REAL, f"{R}{t['shop']} 没有店长{D}"))
            return steps, None
        r2 = tasks.dispatch(dict(id=task, assignee_no=sg["no"]), mgr[0])
        if not r2.get("ok"):
            steps.append(("② 分派", REAL, f"{R}{r2.get('reason','')[:50]}{D}"))
            return steps, None
        steps.append(("② 分派", REAL, f"{mgr[0]['name']}(店长)分给 {sg['name']} · {sg['why'][0][:34]}"))
        t = q("SELECT * FROM schedule WHERE id=?", task)[0]
    adv = q("SELECT no,name,role,shop,adv_code FROM staff WHERE no=?", t["assignee_no"])[0]

    # ── ③ 上门沟通(真路径:走类型规范和时段冲突)──────────────────
    mgr = q("SELECT no,name,role,shop FROM staff WHERE role='店长' AND shop=?", t["shop"])
    v_start = when + datetime.timedelta(days=1)
    v_end = v_start + datetime.timedelta(hours=2)
    r3 = tasks.assign_task(dict(
        type="上门沟通", assignee_no=adv["no"], ref_id=cust["id"],
        note=f"上门为 {cust['name']} 量体,带样布和版型册",
        start=v_start.strftime("%Y-%m-%d %H:%M"), end=v_end.strftime("%Y-%m-%d %H:%M")),
        mgr[0] if mgr else None)
    if not r3.get("ok"):
        steps.append(("③ 上门", REAL, f"{R}{r3.get('reason','')[:60]}{D}"))
        return steps, None
    visit = r3["id"]
    steps.append(("③ 上门", REAL, f"{visit} 派给 {adv['name']} · {v_start:%m-%d %H:%M}"))

    # ── ④ 量体数据(⚠️ 直插:没有写接口)────────────────────────
    w = q("SELECT id,name,height FROM wearer WHERE customer_id=? ORDER BY id LIMIT 1", cust["id"])
    wid = w[0]["id"] if w else None
    tpl = random.choice(["LT01", "LT02", "LT03"])
    items = q("SELECT code,name,unit FROM measure_item WHERE status='启用' AND required=1 ORDER BY sort")
    base = dict(MI01=random.uniform(158, 178), MI02=random.uniform(48, 72),
                MI03=random.uniform(82, 98), MI04=random.uniform(66, 84),
                MI05=random.uniform(88, 102))
    mt = (v_start + datetime.timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M")
    n_item = 0
    for it in items:
        val = round(base.get(it["code"], random.uniform(30, 60)), 1)
        ex("""INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by,measured_at,
              method,wearer_id,cond_inner,cond_shoe,cond_breath,schedule_id)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
           cust["id"], tpl, it["code"], val,
           f"{adv.get('adv_code') or ''} {adv['name']}".strip(), mt,
           "上门", wid, "单层内衣", "赤足", "平静呼气", visit)
        n_item += 1
    steps.append(("④ 量体", RAW, f"{tpl} · {n_item} 项 · {adv['name']} 上门量 · 着装人 {wid or '(无)'}"))

    # ── ⑤ 上门任务完成(真路径:只能本人完成、总结必填、该传图的要传)────
    # 第一版没传图,三条全被拦:「上门沟通完成时要传现场照」。
    # **那是规矩在正常工作** —— 上门这种事本身留下了可看的痕迹,不传图完不了。
    # 脚本得像真顾问那样传一张,而不是把规矩绕过去。
    import files as _f, base64 as _b64, server as _srv0
    png = "data:image/png;base64," + _b64.b64encode(
        bytes.fromhex("89504e470d0a1a0a") + b"visit" * 24).decode()
    ok_img, why_img = _f.save(visit, "总结", "上门现场.png", png, adv["name"])
    r5 = tasks.finish_task(dict(
        id=visit,
        summary=f"已上门量体,{n_item} 项齐全,客户确认按 {tpl} 模板做,现场选定面料"), adv)
    steps.append(("⑤ 完成上门", REAL,
                  (f"✅ 传了现场照,任务完结" if r5.get("ok")
                   else R + str(r5.get("reason") or r5.get("error"))[:44] + D)))
    # 「顺带收尾预约」已经搬进 finish_task 了(见那里的注释)——
    # 脚本侧补等于只在造数据时对,真人走一遍还是会留一条。
    if r5.get("ok") and r5.get("顺带收尾"):
        steps.append(("⑥ 收尾预约", REAL, f"{r5['顺带收尾']} → 完结(finish_task 自动)"))
    if not r5.get("ok"):
        steps.append(("⑦ 下单", RAW, f"{Y}跳过{D} —— 上门任务没完成,不该下单"))
        return steps, None

    # ── 下单前置校验:**走统一口径,不在这儿自己写一遍** ──────────────
    # 这条判断原来只写在这个脚本里(「脚本自己不许造出这种数据」),
    # 于是系统允许、脚本不许 —— **两套规矩**,而系统那套才是真的。
    # 现在口径在 `knowledge/order_gate.py`,`api.can_order` 和这里共用它。
    #
    # ⚠️ 真正该拦的不是「有没有上门任务」,是**这个着装人的量体在不在有效期**。
    # 按「必须有上门任务」拦会误伤每一个老客户(回头客用的是几个月前的数据)。
    import api as _api
    with _api.as_user(adv):
        gate = _api.can_order(cust["id"], "定制品订单", wid or None)
    if gate.get("结论") != "可以":
        steps.append(("⑦ 下单", REAL,
                      f"{Y}拦下{D} —— {gate.get('结论')}:{str(gate.get('理由'))[:60]}"))
        return steps, None

    # ── ⑥ 下单(⚠️ 直插:没有写接口,也没有状态机)────────────────
    # 订单号:**取一个库里没有的**,不要靠随机撞运气。
    # 上一版是 random.randint 取 4 位后缀,跑到第 31 条时撞上已有的单号 ——
    # `UNIQUE constraint failed`,而且**整个脚本当场崩掉,半条旅程留在库里**
    # (量体写了、订单没写,时间也没挪回过去)。
    # 一个造数据的脚本崩在半路,留下的是**看起来正常的残缺数据**。
    _used = {r["id"] for r in q("SELECT id FROM ordr")}
    oid = None
    for _ in range(500):
        cand = str(random.randint(6488012719714560000, 6488012719714569999))
        if cand not in _used:
            oid = cand; break
    if not oid:
        steps.append(("⑦ 下单", RAW, f"{R}订单号取不到没被占的 —— 号段用满了{D}"))
        return steps, None
    # sku 表的主键叫 code 不叫 sku,商品名在 product 表里 —— **列名以表为准**,
    # 这个项目在「列名靠猜」上栽过(appt_at vs start_ts)
    sk = q("""SELECT s.code,s.spu,s.price,s.spec,p.name FROM sku s
              LEFT JOIN product p ON p.spu=s.spu
              WHERE s.status='启用' ORDER BY RANDOM() LIMIT 1""")
    sku = sk[0] if sk else dict(code="SKU0001", name="定制汉服", price=4800.0, spu="SPU001", spec="")
    custom = round(random.uniform(600, 2400), 2)
    amt = round((sku["price"] or 4800) + custom, 2)
    created = (v_start + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    # **两套状态口径有固定映射**(设计稿 10 档 ↔ PRD 状态机),
    # 而 goods_amount 是**基本金额之和,不含定制加价** ——
    # 第一版两处都填错了,被 member_order_check 当场抓到。
    # 我在脚本里写过「订单这一环没有任何规则挡着」,那句话是错的:
    # **没有写接口保护,不等于没有任何东西检查。** 对账检查一直在管。
    ST2PRD = {"待付款": "待付款", "待审核": "方案确认中", "待生产": "方案确认中",
              "生产中": "方案确认中", "已生产": "待发货", "待发货": "待发货",
              "已发货": "待收货", "待完成": "待收货", "完成": "已完成", "取消": "已关闭"}
    ex("""INSERT INTO ordr(id,customer_id,kind,status,advisor,shop,source,delivery,
          amount,payable,created,updated,prd_status,goods_amount,freight,received,
          refund_status,paid_at)
          VALUES(?,?,'定制品订单','待付款',?,?,'门店Pad','配送到店',?,?,?,?,?,?,0,?,'未退款',?)""",
       oid, cust["id"], f"{adv.get('adv_code') or ''} {adv['name']}".strip(), cust["shop"],
       amt, amt, created, created, ST2PRD["待付款"], sku["price"], amt, created)
    ex("""INSERT INTO ordr_item(order_id,sku,name,tag,price,qty,spu,base_amount,
          custom_amount,total) VALUES(?,?,?,'定制',?,1,?,?,?,?)""",
       oid, sku["code"], (sku.get("name") or "定制汉服") + (f"·{sku.get('spec')}" if sku.get("spec") else ""),
       sku["price"], sku["spu"], sku["price"], custom, amt)
    steps.append(("⑦ 下单", RAW, f"{oid[-6:]}… · {sku['name']} · ¥{amt}(定制加价 ¥{custom})"))

    # ── ⑦ 订单推进到完成(真路径:一档一档走状态机)──────────────────
    # 上一版直接 UPDATE 到终态,中间七档全跳过 —— 而**跳过的档在库里看不出来**,
    # 一张单子从「待生产」一步到「完成」和正常走完九档,最终长得一模一样。
    # 现在走 transit(),每一步都过状态机、都留台账。
    #
    # 装上状态机之后第一步就抓到我自己写错的东西:下单时我把初始状态填成了「待生产」,
    # 而定制品的链路第一档是「待付款」。**之前没有状态机的时候,这张单从一开始
    # 就跳过了两档,而没有任何东西说得出来** —— 状态机不只拦「往后跳」,
    # 还拦「起点就不对」,而起点不对在库里完全看不出来。
    import server as _srv
    PATH = ["待审核", "待生产", "生产中", "已生产", "待发货", "已发货", "待完成", "完成"]
    day = 0
    for st in PATH:
        day += random.randint(2, 6)
        rr = _srv.transit("bk-order", oid, st, {"by": "旅程脚本"})
        if not rr.get("ok"):
            steps.append(("⑧ 推进", REAL, f"{R}卡在 {st}:{rr.get('reason','')[:40]}{D}"))
            return steps, None
    # 时间戳按剧本回填 —— transit 落的是「现在」,而这条旅程是有时间线的
    done = (v_start + datetime.timedelta(days=day)).strftime("%Y-%m-%d %H:%M")
    ex("""UPDATE ordr SET updated=?,produced_at=?,shipped_at=?,finished_at=? WHERE id=?""",
       done, (v_start + datetime.timedelta(days=day - 12)).strftime("%Y-%m-%d %H:%M"),
       (v_start + datetime.timedelta(days=day - 6)).strftime("%Y-%m-%d %H:%M"), done, oid)
    # ── 客户档案跟着动:三个字段必须一起对 ──────────────────────────
    # 第一版只更了 order_cnt / paid_amount / last_interact,栽了两处:
    #
    # ① **last_interact 填成了订单完成日,而那是一个月后的未来日期** ——
    #    库里出现了「上次联系客户是下个月」,而没有任何检查抓到它。
    #    互动的时间点是**上门那天**(人真的见了面),不是订单完成那天。
    # ② **idle_days 和 lifecycle 没跟着重算** —— 于是一个刚上门量过体的客户
    #    同时挂着「流失、380 天没互动」。**三个字段互相矛盾,而没人报错。**
    #
    # 生命周期的判定口径在 knowledge/lifecycle.py,这里**调它,不自己写一遍** ——
    # 自己写就是第二份口径,而两份口径迟早不一致。
    import knowledge.lifecycle as _lc  # noqa
    inter = v_start.date()                      # 互动 = 上门那天
    idle = max(0, (datetime.date.today() - inter).days)   # 这个值稍后会按基准日重算
    row = q("SELECT * FROM customer WHERE id=?", cust["id"])[0]
    nr = dict(row, order_cnt=(row["order_cnt"] or 0) + 1,
              paid_amount=round((row["paid_amount"] or 0) + amt, 2),
              amount_12m=round((row["amount_12m"] or 0) + amt, 2),
              orders_12m=(row["orders_12m"] or 0) + 1, idle_days=idle)
    lc, matched = _lc.decide(nr)["生命周期"], None
    try:
        d2 = _lc.decide(nr); lc, matched = d2["生命周期"], "/".join(d2.get("命中", []) or [])
    except Exception:
        pass
    # **会员等级也得跟着重算。** 又是同一个病的另一种形态:
    # 我加了订单金额,而等级是**从金额派生的** —— 不重算的话,
    # 一个 12 个月实付 3 万的客户还挂着「金卡」,而门槛表写着 3 万是黑金。
    # 门槛**从 level_cfg 读,不在这儿抄一份** —— 抄一份的话,
    # 运营改了门槛,造出来的数据就和对账检查对不上,而红的会是「数据错」。
    lvs = q("SELECT name,amount,orders,sort FROM level_cfg WHERE status='启用' ORDER BY sort DESC")
    level = lvs[-1]["name"] if lvs else "普通"
    for L in lvs:                      # 从高到低,任一满足即取
        if nr["amount_12m"] >= (L["amount"] or 0) or nr["orders_12m"] >= (L["orders"] or 0):
            level = L["name"]; break
    ex("""UPDATE customer SET order_cnt=?, paid_amount=?, amount_12m=?, orders_12m=?,
          last_interact=?, idle_days=?, lifecycle=?, level=?, matched=COALESCE(?,matched)
          WHERE id=?""",
       nr["order_cnt"], nr["paid_amount"], nr["amount_12m"], nr["orders_12m"],
       inter.isoformat(), idle, lc, level, matched or None, cust["id"])
    # ── 把整条旅程挪到过去 ─────────────────────────────────────────
    # book() 不收过去的时间(对的),所以先按未来下单、再整体前移。
    # **每一张表都要挪** —— 漏一张就成了「预约在三个月前、量体在下个月」。
    # **挪移要保证终点在过去,不是起点。**
    # 订单本身要走 30~45 天:起点挪到 33 天前,终点就还在未来 5 天 ——
    # C4 抓到过一条(8-09 下单、走 38 天、落到 9-16)。
    # 我盯着开头,而约束在结尾。
    _end = datetime.datetime.strptime(done, "%Y-%m-%d %H:%M")
    _need = (_end.date() - datetime.date.today()).days + 3     # 终点至少要落到 3 天前
    if _need > shift.days:
        shift = datetime.timedelta(days=_need)
    # 但也不能挪过客户建档 —— 两个下界取严的那个
    if shift.days > (_room + 9):
        shift = datetime.timedelta(days=max(1, _room + 9))
    _sh = f"-{shift.days} days"
    for _t, _cols, _key in (
            ("appointment", ("start_ts", "end_ts", "checkin_ts"), f"id='{appt}'"),
            ("schedule", ("start_ts", "end_ts", "assigned_at"), f"id IN ('{task}','{visit}')"),
            ("measure_rec", ("measured_at",), f"schedule_id='{visit}'"),
            ("schedule_file", ("uploaded_at",), f"schedule_id='{visit}'"),
            ("ordr", ("created", "updated", "paid_at", "audit_at", "produced_at",
                      "shipped_at", "finished_at"), f"id='{oid}'")):
        sets = ", ".join(f"{c2}=datetime({c2}, '{_sh}')" for c2 in _cols)
        ex(f"UPDATE {_t} SET {sets} WHERE {_key}")
    # 客户那三个字段也跟着挪,并按挪后的日期重算闲置天数
    inter2 = inter - shift
    # **idle_days 要按基准日算,不是按今天。**
    # 它是「建库那天的快照」这个口径(见 spec_check 的 C5)——
    # 我按今天算,和检查按基准日比,永远差 11 天。
    # 口径不统一时,两边各自都说得通,而对不上的时候不知道该改哪边。
    try:
        _base = datetime.date.fromisoformat(_BASE_DAY)
    except Exception:
        _base = datetime.date.today()
    idle2 = max(0, (_base - inter2).days)
    nr2 = dict(nr, idle_days=idle2)
    lc2 = _lc.decide(nr2)["生命周期"]
    ex("UPDATE customer SET last_interact=?, idle_days=?, lifecycle=? WHERE id=?",
       inter2.isoformat(), idle2, lc2, cust["id"])
    done2 = (datetime.datetime.strptime(done, "%Y-%m-%d %H:%M") - shift).strftime("%Y-%m-%d")

    steps.append(("⑧ 推进到完成", REAL, f"走完 {len(PATH)} 档 · {done2} 完成"
                                      f"({span} 天前的一单)· 客户累计 +1 单 ¥{amt} · "
                                      f"生命周期 → {lc2} · 等级 → {level}"))
    return steps, dict(客户=cust["id"], 预约=appt, 预约任务=task, 上门任务=visit,
                       量体项=n_item, 订单=oid, 金额=amt)


def main():
    n = 3
    dry = "--dry" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit(): n = int(a)
    custs = pick_customers(n)
    if len(custs) < n:
        # 一次性客户不够了就补回头客 —— **说清楚补了几个**,
        # 不说的话下次看数据的人会以为这批全是新客
        more = pick_repeat(n - len(custs))
        if more:
            print(f"  一次性客户只剩 {len(custs)} 个,补 {len(more)} 个**回头客**"
                  f"(已走过一趟、上一单已收尾)")
            custs = custs + more
    if not custs:
        print(f"{R}挑不出客户{D} —— 可能都有在办预约了(那是 book() 的频次闸,是对的)")
        return
    print(f"\n{B}跑 {len(custs)} 条完整旅程{D}"
          f"{'(试跑,不写库)' if dry else ''}")
    print("=" * 86)
    done = []
    for c in custs:
        print(f"\n{B}▸ {c['name']}({c['id']}) · {c['shop']} · 归属 {c['advisor']}{D}")
        steps, out = journey(c, dry)
        for name, kind, txt in steps:
            print(f"    {kind}  {name:10s} {txt}")
        if out: done.append(out)

    if dry: return
    print("\n" + "=" * 86)
    print(f"{B}跑完 {len(done)}/{len(custs)} 条{D}")
    for o in done:
        print(f"  {o['客户']} → 预约 {o['预约']} → 上门 {o['上门任务']} → "
              f"量体 {o['量体项']} 项 → 订单 …{o['订单'][-6:]} ¥{o['金额']}")

    print(f"\n{B}这条链上哪些有保护、哪些没有{D}")
    print("  " + "-" * 82)
    print(f"  {G}✅ 有业务规则挡着{D}  预约(手机号/营业时间/频次)· 派单(归属/离职/跨店)")
    print(f"                     上门(类型规范/时段冲突/权限)· 完成(本人/总结必填)")
    print(f"  {Y}⚠️ 直插,没有任何规则{D}  量体 · 下单 · 订单完成")
    print()
    print(f"  {Y}但「没有写接口保护」不等于「没有任何东西检查」{D} —— 我一开始把这两件事混成了一句。")
    print("    实际上 backend/member_order_check.py 一直在对账,而且当场抓到了我造的两处错:")
    print("      · 订单两套状态口径的映射填反了(设计稿「完成」要映射到「已完成」)")
    print("      · goods_amount 填成了含定制加价的总额,而它的口径是**基本金额之和**")
    print()
    print(f"  {Y}真正缺的是这些{D}:")
    print("    · 量体的人是不是真去上门的那个人 —— 现在靠 task_id 连上了,但没有检查盯着")
    print("    · 订单能不能从「待生产」直接跳「完成」—— 没有状态机拦,中间几档可以跳过")
    print("    · 上门任务没完成能不能下单 —— 没有东西拦(这个脚本自己不许,但系统允许)")
    print(f"  **对账检查抓得到「填错了」,抓不到「顺序错了」** —— 后者要状态机。")


if __name__ == "__main__":
    main()
