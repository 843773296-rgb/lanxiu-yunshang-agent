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
    该回没回        开工好几天连接单都没回 / 过了承诺日还没完工 → 不发消息,该催清单里要有它

**预期是它自己记的,不是调接收写口算的** —— 调写口算预期就是同源谬误:写口错了,预期跟着错。

确定性:按订单号的稳定哈希挑,不用随机数,重建多少次都是同一批。
"""
import hashlib, datetime as dt

工期天 = (28, 42)          # 承诺工期区间(开工 → 完工),和库里历史单「审核到完工」平均 33 天对得上
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
    # ── 要先收下接单才测得到的两种:放在这一批最后 ──
    尾 = []
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
