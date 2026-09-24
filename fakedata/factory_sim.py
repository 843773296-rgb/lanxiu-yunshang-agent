# -*- coding: utf-8 -*-
"""模拟工厂 —— **扮演外部供应链系统**,按真实节奏往我们这边发生产 / 发货回传。

业务 2026-09-22:「已生产」「发货」是工厂回传的数据,走供应链系统。现在没接真系统,由它来扮演。
**它和我们的接收写口(backend/factory_inbox.py)只隔着一条消息** —— 它不许碰订单表,
只读订单表来决定「工厂那边这张单做到哪了」,产出的只有消息。将来接真系统,拿掉这一份就行。

## 发什么

  历史回传(历史回传())   已经过了生产的单 —— 当年工厂发过的那几条,干净的,时间对得上订单自己记的
  今天这一批(今日回传()) 生产中的单 —— 按开工时间和承诺工期,该接单的接单、该完工的完工……

## 故意混进去的毛病(只在今天这一批)

真实的供应链消息不会干净。每一条毛病都**记下预期该怎么处理**,检查逐条对:

    重复发          同一个消息号发两次                → 第二条 重复
    换号重发        同一步换个消息号再发              → 第二条 重复
    乱序            质检通过比完工先到                → 当场 暂存,完工到了再放行 —— 预期写「暂存→收下」
    发出没单号      发出不带物流单号                  → 拒收
    未来时间        时间晚于今天                      → 拒收
    时间倒挂        完工早于开工                      → 拒收
    查无此单        订单号录错了                      → 挂异常
    已取消的单      工厂还在做一张取消了的单          → 挂异常
    别家报完工      接单的是甲家,报完工的是乙家        → 挂异常(谁接的单谁报)
    车间在制却报完工 车间工单还没做完就报完工         → 挂异常
    件不属于这张单  报的订单行号不是这张单的          → 拒收
    该回没回        开工好几天连接单都没回 / 过了承诺日还没完工 → 不发消息,该催清单里要有它

**预期是它自己记的,不是调接收写口算的** —— 调写口算预期就是同源谬误:写口错了,预期跟着错。

确定性:按订单号的稳定哈希挑,不用随机数,重建多少次都是同一批。
"""
import hashlib, datetime as dt

# 两个数**业务 2026-09-23 确认**(原为提议值):承诺工期 28–42 天(和库里历史单「审核到完工」平均 33 天对得上)、
# 回执宽限 3 天(开工 3 天没回接单就该催)
工期天 = (28, 42)
回执宽限天 = 3


def _h(*a):
    return int(hashlib.sha256(("factory:" + ":".join(map(str, a))).encode()).hexdigest()[:8], 16)


def _t(s):
    return dt.datetime.strptime(str(s)[:16], "%Y-%m-%d %H:%M")


def _s(t):
    return t.strftime("%Y-%m-%d %H:%M")


def _工厂(oid):
    """谁做这张单。**自有工坊和外发工厂都有**(业务 09-22)—— 约四成自有工坊做,其余外发三家。"""
    return ("自有工坊", "自有工坊", "苏州绣坊", "杭州成衣坊", "南通缝制厂")[_h(oid, "厂") % 5]


def _单号(oid):
    return f"SF{_h(oid, '物流') % 10**10:010d}"


def 历史回传(c):
    """已经过了生产的定制单 —— 把工厂当年发过的回传补出来(干净的)。返回消息列表。"""
    out = []
    for o in c.execute("""SELECT id, status, cut_at, audit_at, produced_at, shipped_at FROM ordr
                          WHERE kind='定制品订单' AND produced_at IS NOT NULL
                            AND status IN ('已生产','待发货','已发货','待完成','完成')"""):
        oid, 开 = o[0], _t(o[2] or o[3] or o[4])
        完 = _t(o[4])
        if 开 > 完:
            开 = 完 - dt.timedelta(days=30)
        接 = min(开 + dt.timedelta(hours=20), 完)
        out.append(dict(消息号=f"H{oid}-接", 订单号=oid, 事件="接单", 时间=_s(接), 工厂=_工厂(oid),
                        承诺完工日=_s(开 + dt.timedelta(days=工期天[1]))[:10]))
        out.append(dict(消息号=f"H{oid}-完", 订单号=oid, 事件="完工", 时间=_s(完), 工厂=_工厂(oid)))
        if o[1] != "已生产":
            发 = _t(o[5]) if o[5] else None
            质 = 完 + dt.timedelta(hours=18)
            if 发 and 质 > 发:
                质 = 完 + (发 - 完) / 2
            out.append(dict(消息号=f"H{oid}-质", 订单号=oid, 事件="质检通过", 时间=_s(质), 工厂=_工厂(oid)))
            if 发:
                # **多件的老单也拆成两个包裹**(业务 09-23 之后分批发货是常态)——
                # 演示库原来只有 1 张分批单,页面夹具、写口检查、签收评测题全挂在它一张上,
                # 任何一次动到它两边一起红,而红出来的理由指不到真凶(2026-09-24 实测过一次)。
                件们 = [r[0] for r in c.execute("SELECT id FROM ordr_item WHERE order_id=? ORDER BY id", (oid,))]
                if len(件们) >= 2:
                    半 = len(件们) // 2
                    # ⚠️ 两个包裹**不能共用一个快递单号** —— 转寄的老单订单级只有一个单号,
                    # 直接沿用会造出现实里不存在的数据(并行会话提醒)。第二个按包裹派生。
                    out.append(dict(消息号=f"H{oid}-发1", 订单号=oid, 事件="发出", 时间=_s(发), 工厂=_工厂(oid),
                                    物流单号=_单号(oid), 件=件们[:半]))
                    out.append(dict(消息号=f"H{oid}-发2", 订单号=oid, 事件="发出",
                                    时间=_s(发 + dt.timedelta(hours=6)), 工厂=_工厂(oid),
                                    物流单号=_单号(oid) + "-2", 件=件们[半:]))
                else:
                    out.append(dict(消息号=f"H{oid}-发", 订单号=oid, 事件="发出", 时间=_s(发), 工厂=_工厂(oid),
                                    物流单号=_单号(oid)))
    return out


def 今日回传(c, 今天, 上限=None):
    """生产中的单 —— 工厂这一批该发的回传,混进故意的毛病。
    返回 [(消息, 毛病, 预期)] —— 预期是「该催」的那几条**不发**(消息里只有订单号):工厂该回没回,该催清单里要有它。"""
    今 = _t(str(今天)[:10] + " 18:00")
    out, 植过没单号 = [], False
    单们 = c.execute("""SELECT id, cut_at, audit_at FROM ordr WHERE kind='定制品订单' AND status='生产中'
                        AND (cut_at IS NOT NULL OR audit_at IS NOT NULL) ORDER BY id""").fetchall()
    在制 = {r[0]: r[1] for r in c.execute("SELECT ref, MAX(due_date) FROM workorder WHERE status='在制' "
                                          "AND ref IS NOT NULL GROUP BY ref")}
    for o in 单们[:上限] if 上限 else 单们:
        oid, 开 = o[0], _t(o[1] or o[2])
        h = _h(oid) % 100
        开工天 = (今 - 开).days
        if h < 6:                                    # 6%:工厂一直没回接单
            if 开工天 > 回执宽限天:
                out.append((dict(订单号=oid), "该回没回:没接单", "该催"))
            continue
        工期 = 工期天[0] + _h(oid, "期") % (工期天[1] - 工期天[0] + 1)
        承诺 = 开 + dt.timedelta(days=工期)
        # **车间里还有在制的工单,工厂就不会报完工**(绣片、手绘这些自有工坊的活没交,衣服缝不完)——
        # 第一版没看这个,3 张单工厂报了完工、车间工单还在制(order_gate_check ⑥ 当场红)。
        # 承诺日往后排到工单截止之后,今天这一批不发完工
        if 在制.get(oid):
            承诺 = max(承诺, _t(在制[oid] + " 18:00") + dt.timedelta(days=7), 今 + dt.timedelta(days=7))
        接 = 开 + dt.timedelta(hours=20)
        if 接 > 今:
            continue
        out.append((dict(消息号=f"T{oid}-接", 订单号=oid, 事件="接单", 时间=_s(接), 工厂=_工厂(oid),
                         承诺完工日=_s(承诺)[:10]), "", "收下"))
        if 承诺 - dt.timedelta(days=4) > 今:
            continue                                  # 还没到完工的时候
        if h < 16:                                    # 10%:过了承诺日还没完工
            if 承诺 < 今:
                out.append((dict(订单号=oid), "该回没回:过了承诺日", "该催"))
            continue
        完 = min(承诺 - dt.timedelta(days=_h(oid, "早") % 4), 今 - dt.timedelta(hours=30))
        完消息 = dict(消息号=f"T{oid}-完", 订单号=oid, 事件="完工", 时间=_s(完), 工厂=_工厂(oid))
        质 = 完 + dt.timedelta(hours=20)
        质消息 = dict(消息号=f"T{oid}-质", 订单号=oid, 事件="质检通过", 时间=_s(质), 工厂=_工厂(oid)) \
            if 质 <= 今 and h % 2 == 0 else None
        if 质消息 and h % 10 == 4:                    # 乱序:质检先到
            out += [(质消息, "乱序:质检先到", "暂存→收下"), (完消息, "乱序:完工后到", "收下")]
        else:
            out.append((完消息, "", "收下"))
            if 质消息:
                out.append((质消息, "", "收下"))
        if h % 10 == 6:                               # 重复发同一个号
            out.append((dict(完消息), "重复发", "重复"))
        if h % 10 == 8:                               # 换号重发
            out.append((dict(完消息, 消息号=f"T{oid}-完-重"), "换号重发", "重复"))
        if 质消息:
            发 = 质 + dt.timedelta(hours=6)
            if 发 <= 今 and h % 3 == 0:
                发消息 = dict(消息号=f"T{oid}-发", 订单号=oid, 事件="发出", 时间=_s(发), 工厂=_工厂(oid),
                             物流单号=_单号(oid))
                if not 植过没单号:                    # 发出没带物流单号:第一条发出就植上,保证样本量不为 0
                    植过没单号 = True                  # (按哈希挑的第一版一条都没挑中)
                    out.append((dict(发消息, 物流单号=None), "发出没单号", "拒收"))
                else:
                    out.append((发消息, "", "收下"))
    # ── 不挂在某一张生产中的单上的几种毛病 —— 各造一两条,样本量不为 0 ──
    # **放在这一批的最前面发**:倒挂那条要是排在同一张单正常的完工之后,会先被判成「这一步收过了 → 重复」,
    # 测不到「时间倒挂 → 拒收」这一支
    正常, out = out, []
    if 单们:
        a = 单们[len(单们) // 3][0]
        out.append((dict(消息号=f"X{a}-未来", 订单号=a, 事件="完工", 时间=_s(今 + dt.timedelta(days=5)),
                         工厂=_工厂(a)), "未来时间", "拒收"))
        b = 单们[len(单们) // 2][0]
        b开 = _t(单们[len(单们) // 2][1] or 单们[len(单们) // 2][2])
        out.append((dict(消息号=f"X{b}-倒挂", 订单号=b, 事件="完工", 时间=_s(b开 - dt.timedelta(days=3)),
                         工厂=_工厂(b)), "时间倒挂", "拒收"))
        out.append((dict(消息号="X-查无此单", 订单号="9999999999999999999", 事件="完工",
                         时间=_s(今 - dt.timedelta(days=1)), 工厂="苏州绣坊"), "查无此单", "挂异常"))
    取消 = c.execute("SELECT id FROM ordr WHERE kind='定制品订单' AND status='取消' AND audit_at IS NOT NULL "
                    "ORDER BY id LIMIT 1").fetchone()
    if 取消:
        out.append((dict(消息号=f"X{取消[0]}-取消", 订单号=取消[0], 事件="完工", 时间=_s(今 - dt.timedelta(days=2)),
                         工厂=_工厂(取消[0])), "已取消的单", "挂异常"))
    # ── 要先收下接单才测得到的几种:放在这一批最后 ──
    尾 = []
    # **分批发货**(业务 09-23):挑一张多件的单,先发一件、再发其余 —— 演示库里要有真的两个包裹。
    # ⚠️ 生产中的单**全是单件**(实测),所以从「已生产」里挑:那种单历史回传里已经报过完工,
    # 这里接着报质检和发出即可。挑不到就不造 —— **不硬凑**,检查那头会因为没有活用例而红。
    多件 = c.execute("""SELECT i.order_id, o.status, COUNT(*) n FROM ordr_item i JOIN ordr o ON o.id=i.order_id
                        WHERE o.kind='定制品订单' AND o.status IN ('生产中','已生产')
                        GROUP BY i.order_id HAVING n>=2 ORDER BY o.status DESC, i.order_id LIMIT 1""").fetchone()
    if 多件:
        oid, 状态 = 多件[0], 多件[1]
        件们 = [r[0] for r in c.execute("SELECT id FROM ordr_item WHERE order_id=? ORDER BY id", (oid,))]
        开 = _t(c.execute("SELECT COALESCE(cut_at,audit_at,produced_at) FROM ordr WHERE id=?", (oid,)).fetchone()[0])
        厂 = c.execute("SELECT factory FROM factory_msg WHERE order_id=? AND event='接单' AND result='收下' "
                      "LIMIT 1", (oid,)).fetchone()
        厂 = 厂[0] if 厂 else _工厂(oid)
        t0 = min(开 + dt.timedelta(days=20), 今 - dt.timedelta(days=3))
        步 = ([("完工", 件们)] if 状态 == "生产中" else []) + \
             [("质检通过", 件们[:1]), ("发出", 件们[:1]), ("质检通过", 件们[1:]), ("发出", 件们[1:])]
        if 状态 == "生产中":
            尾.append((dict(消息号=f"B{oid}-接", 订单号=oid, 事件="接单", 时间=_s(开 + dt.timedelta(hours=20)),
                            工厂=厂, 承诺完工日=_s(开 + dt.timedelta(days=30))[:10]), "分批:接单", "收下"))
        第一个发出 = None
        for k, (事, 批) in enumerate(步):
            m = dict(消息号=f"B{oid}-{k}", 订单号=oid, 事件=事, 时间=_s(t0 + dt.timedelta(hours=6 * k)),
                     工厂=厂, 件=批)
            if 事 == "发出":
                m["物流单号"] = _单号(oid) + f"-{k}"
                第一个发出 = 第一个发出 or m["消息号"]
            尾.append((m, f"分批:{事} {len(批)} 件", "收下"))
        # 顺带造一条更正(改快递单号)—— 更正只能改时间和快递单号
        if 第一个发出:
            尾.append((dict(消息号=f"B{oid}-改", 订单号=oid, 事件="更正", 时间=_s(今 - dt.timedelta(days=1)),
                            工厂=厂, 原消息号=第一个发出, 新物流单号=_单号(oid) + "-FIX"), "更正快递单号", "收下"))
    # **撤回**:挑一张刚收下完工的单,工厂撤回那条 —— 订单状态不自动退
    撤 = [m for m, 毛病, e in 正常 if m.get("事件") == "完工" and e == "收下"]
    if 撤:
        m0 = 撤[-1]
        尾.append((dict(消息号=f"X{m0['订单号']}-撤", 订单号=m0["订单号"], 事件="撤回",
                        时间=_s(今 - dt.timedelta(hours=6)), 工厂=m0.get("工厂"), 原消息号=m0["消息号"]),
                   "撤回一条完工", "收下"))
    # **件不属于这张单**:工厂把别家的行号报了过来
    if 单们:
        o0 = 单们[0][0]
        尾.append((dict(消息号=f"X{o0}-外件", 订单号=o0, 事件="完工", 时间=_s(今 - dt.timedelta(days=1)),
                        工厂=_工厂(o0), 件=[99999999]), "件不属于这张单", "拒收"))
    # **整批延期**:挑两张还在生产中、已接单没完工的单
    延 = [m["订单号"] for m, 毛病, e in 正常 if m.get("事件") == "接单" and e == "收下"
         and not any(x.get("订单号") == m["订单号"] and x.get("事件") == "完工" for x, _, _ in 正常)][:2]
    for o in 延:
        尾.append((dict(消息号=f"D{o}-延", 订单号=o, 事件="延期", 时间=_s(今 - dt.timedelta(days=2)),
                        工厂=_工厂(o), 承诺完工日=_s(今 + dt.timedelta(days=12))[:10], 原因="染厂停产检修"),
                   "整批延期", "收下"))
    未完 = [m["订单号"] for m, 毛病, e in 正常 if m.get("事件") == "接单" and e == "收下"
           and not any(x.get("订单号") == m["订单号"] and x.get("事件") == "完工" for x, _, _ in 正常)]
    有工单 = [o for o in 未完 if 在制.get(o)]
    没工单 = [o for o in 未完 if not 在制.get(o)]
    if 没工单:                                         # 别家报这张单的完工
        o = 没工单[0]
        别家 = next(x for x in ("苏州绣坊", "杭州成衣坊", "南通缝制厂", "自有工坊") if x != _工厂(o))
        尾.append((dict(消息号=f"X{o}-别家", 订单号=o, 事件="完工", 时间=_s(今 - dt.timedelta(days=1)), 工厂=别家),
                   "别家报完工", "挂异常"))
    if 有工单:                                         # 车间工单还在制却报完工
        o = 有工单[0]
        尾.append((dict(消息号=f"X{o}-在制", 订单号=o, 事件="完工", 时间=_s(今 - dt.timedelta(days=1)), 工厂=_工厂(o)),
                   "车间在制却报完工", "挂异常"))
    return out + 正常 + 尾
