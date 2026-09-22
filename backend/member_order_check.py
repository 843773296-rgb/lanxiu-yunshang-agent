#!/usr/bin/env python3
"""会员与订单一致性检查。

订单状态有一条跨文档冲突(答案集里的差集 D):
  PRD / 状态机 fe-order 是 6 个状态,设计稿订单列表是 10 个页签。
两个口径都存(status / prd_status),这里查**映射有没有走偏** ——
不然页面和状态机各说各话,而且不会有人发现。
"""
import os, sqlite3, sys
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")
c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把一张已付款订单的顾问工号改成不存在的人(这单的业绩没人认领)',
     '导购业绩合计 ≠ 全库已付款未关闭的实收'),
    ('把一张订单的商品总额抬高 9 万(和各订单行之和对不上)',
     '≠ 各行基本金额之和'),
]

def q(sql, *a): return [dict(r) for r in c.execute(sql, a)]

ST2PRD = {"待付款":"待付款","待审核":"方案确认中","待生产":"方案确认中","生产中":"方案确认中",
          "已生产":"待发货","待发货":"待发货","已发货":"待收货","待完成":"待收货",
          "完成":"已完成","取消":"已关闭"}
bad, warn = [], []

# ① 订单:两套状态的映射必须一致
for o in q("SELECT id,kind,status,prd_status FROM ordr"):
    want = ST2PRD.get(o["status"])
    if want is None:
        bad.append(f"订单 {o['id']} 的状态「{o['status']}」不在设计稿的 10 个页签里")
    elif o["prd_status"] != want:
        bad.append(f"订单 {o['id']} 状态映射错位:设计稿「{o['status']}」应映射到「{want}」,"
                   f"实为「{o['prd_status']}」")

# ② 订单行必须指向真实商品
for r in q("""SELECT DISTINCT spu FROM ordr_item WHERE spu IS NOT NULL
              AND spu NOT IN (SELECT spu FROM product)"""):
    bad.append(f"订单行引用了不存在的商品 {r['spu']}")

# ③ 金额:合计 = 商品总额 + 定制部件 + 运费(设计稿「基本金额/定制部件金额/合计总价」)
for o in q("SELECT id,amount,goods_amount,freight FROM ordr"):
    items = q("SELECT base_amount,custom_amount,total FROM ordr_item WHERE order_id=?", o["id"])
    if not items: bad.append(f"订单 {o['id']} 没有订单行"); continue
    gsum = round(sum(i["base_amount"] or 0 for i in items), 2)
    tsum = round(sum(i["total"] or 0 for i in items), 2)
    if abs(gsum - (o["goods_amount"] or 0)) > 0.01:
        bad.append(f"订单 {o['id']} 商品总额 {o['goods_amount']} ≠ 各行基本金额之和 {gsum}")
    if abs(round(tsum + (o["freight"] or 0), 2) - (o["amount"] or 0)) > 0.01:
        bad.append(f"订单 {o['id']} 合计 {o['amount']} ≠ 各行合计 {tsum} + 运费 {o['freight']}")
    for i in items:
        if abs(round((i["base_amount"] or 0) + (i["custom_amount"] or 0), 2) - (i["total"] or 0)) > 0.01:
            bad.append(f"订单 {o['id']} 某行 基本+定制部件 ≠ 合计")

# ④ 时间戳顺序:**下单** ≤ 付款 ≤ 审核 ≤ 生产 ≤ 发货 ≤ 完成
#
# `created` 原来不在这条序列里,于是「付款早于下单」**35/35 条一直没被发现** ——
# 检查从第二个环节才开始查,第一个环节缺位就等于没查。
# **一条链上少查一环,那一环就会长年错着。**
ORDER = ["created","paid_at","audit_at","produced_at","shipped_at","finished_at"]
for o in q("SELECT id,%s FROM ordr" % ",".join(ORDER)):
    seq = [(k, o[k]) for k in ORDER if o[k]]
    for (k1,v1),(k2,v2) in zip(seq, seq[1:]):
        if v1 > v2: bad.append(f"订单 {o['id']} 时间倒挂:{k1}={v1} 晚于 {k2}={v2}")

# ⑤ 会员等级必须由 level_cfg 的门槛算出(滚动 12 个月,任一满足)
lv = q("SELECT name,amount,orders,sort FROM level_cfg WHERE status='启用' ORDER BY sort DESC")
for m in q("SELECT id,name,level,amount_12m,orders_12m FROM customer"):
    want = next((l["name"] for l in lv
                 if (m["amount_12m"] or 0) >= l["amount"] or (m["orders_12m"] or 0) >= l["orders"]),
                lv[-1]["name"])
    if m["level"] != want:
        bad.append(f"会员 {m['name']} 等级「{m['level']}」与门槛不符,按规则应为「{want}」"
                   f"(12 个月实付 {m['amount_12m']} / {m['orders_12m']} 单)")

# ⑥ 积分流水的行为必须在设计稿「积分行为」六种之内
BEH = {"账户调加","账户调减","积分消费","积分返还","确认款样","完成定购"}
for r in q("SELECT DISTINCT behavior FROM points_log"):
    if r["behavior"] not in BEH:
        bad.append(f"积分流水出现设计稿之外的行为「{r['behavior']}」")

# ⑦ 绑定关系必须指向真实客户
for r in q("""SELECT DISTINCT target_id FROM member_bind WHERE target_id IS NOT NULL
              AND target_id NOT IN (SELECT id FROM customer)"""):
    bad.append(f"绑定关系指向不存在的客户 {r['target_id']}")
for r in q("SELECT id,inviter FROM customer WHERE inviter IS NOT NULL"):
    if not q("SELECT 1 FROM customer WHERE id=?", r["inviter"]):
        bad.append(f"{r['id']} 的邀请人 {r['inviter']} 不存在")
    if r["inviter"] == r["id"]:
        bad.append(f"{r['id']} 把自己设成了邀请人")

# ── 合并工单的两条档案:数据不能和真值自相矛盾 ────────────────────────
# **这条是被模型抓出来的,不是想出来的。**
# 跑三代对比时 V1 和 V3 都把「同一客户跨店重复建档」判成了「不同人」,
# 理由是「性别 男/女 矛盾、地址字符串相同但省市区不同(河北衡水 vs 广东广州)」——
# **它们推理没错,是种子数据自相矛盾**(客户信息按下标分配,而一对的 id 相邻)。
#
# 教训:模型答错时先检查真值和数据。而这条检查本该早就有 ——
# 一份「真值说是同一人、数据说不是」的用例,考的不是模型,是运气。
for t in q("SELECT id,ref_id FROM task WHERE type='客户合并确认'"):
    a, b = t["ref_id"].split("|")
    ra = q("SELECT * FROM customer WHERE id=?", a)
    rb = q("SELECT * FROM customer WHERE id=?", b)
    tr = q("SELECT root_cause FROM truth WHERE case_id=?", t["id"][1:])
    if not (ra and rb and tr): continue
    ra, rb, rc = ra[0], rb[0], tr[0]["root_cause"]
    if rc == "同一客户跨店重复建档":
        for f in ("gender", "province", "city"):
            if ra[f] != rb[f]:
                bad.append(f"{t['id']} 真值是「同一人」,但 {f} 不同({ra[f]} / {rb[f]})"
                           f" —— 数据和真值自相矛盾,模型判「不同人」反而是对的")
        if ra["addr"] == rb["addr"] and (ra["city"] != rb["city"]):
            bad.append(f"{t['id']} 地址字符串相同却不在同一个城市 —— 数据自相矛盾")
    else:
        if (ra["province"], ra["city"]) == (rb["province"], rb["city"]) and ra["addr"] != rb["addr"]:
            warn.append(f"{t['id']} 真值是「不同人」,但两条在同一城市 —— 证据偏弱")

# ── 维修工单:「这条记录属于谁」必须从关联对象取,不能靠下标碰 ──────────
# 这条也是查出来的:21/21 条维修工单的客户号和它所属订单的客户对不上,
# 因为种子里写的是 `cust[(i+7)%len(cust)]` —— **按下标凑关联**。
# 和上面那 8 对合并档案是同一类错,只是换了张表。
#
# 下标凑出来的关联在小数据上看不出来,数据一多就全错,**而且不会报错** ——
# 它只会让「售后判责」这类跨表推理拿到一个自相矛盾的现场。
for r in q("""SELECT m.id, m.customer_id mc, o.customer_id oc, m.item, m.order_id
              FROM maintain m JOIN ordr o ON o.id = m.order_id"""):
    if r["mc"] != r["oc"]:
        bad.append(f"维修工单 {r['id']} 的客户 {r['mc']} 与订单 {r['order_id']} 的客户 "
                   f"{r['oc']} 不一致 —— 判责要跨表看现场,现场自相矛盾就没法判")
for r in q("SELECT id, order_id, item FROM maintain"):
    names = [x["name"] for x in q("SELECT name FROM ordr_item WHERE order_id=?", r["order_id"])]
    if names and r["item"] not in names:
        bad.append(f"维修工单 {r['id']} 修的是「{r['item']}」,但订单里没有这件商品")

# ⑤ 售后链条的时间顺序:下单 → 交付签收 → 报修
#
# 这三条是**模型在跑判责评测时抓出来的**,不是想出来的:
# 它读到「报修 2026-08-10,订单创建 2026-08-11」,直接拒绝判责,
# 理由是「这在逻辑上不可能,数据链路已破损」—— **它是对的**。
#
# 模型是这个项目里最好的数据审计员:它逐字读现场,
# 而且**没有「我知道这是 demo 数据」这个心理豁免**。
for r in q("""SELECT m.id, m.created mc, o.created oc, o.id oid
              FROM maintain m JOIN ordr o ON o.id = m.order_id WHERE m.created < o.created"""):
    bad.append(f"维修工单 {r['id']} 报修({r['mc']})早于订单创建({r['oc']})—— 衣服还没下单就来报修")
for r in q("""SELECT d.order_id, d.signed_at, o.created FROM delivery_notice d
              JOIN ordr o ON o.id = d.order_id WHERE d.signed_at < o.created"""):
    bad.append(f"订单 {r['order_id']} 交付签收({r['signed_at']})早于下单({r['created']})")
for r in q("""SELECT m.id, m.created mc, d.signed_at sa FROM maintain m
              JOIN delivery_notice d ON d.order_id = m.order_id WHERE m.created < d.signed_at"""):
    bad.append(f"维修工单 {r['id']} 报修({r['mc']})早于交付签收({r['sa']})")

# ⑨ 导购业绩页的合计 = 全库「已付款、没关闭」订单的实收(2026-09-22 加)
#    原来页面按 PRD 口径的状态名筛 status 列(存的是设计稿口径),只对上一个名字,
#    全库只数到 130 单 / 48.8 万,真实约 2.5 万单 / 1.45 亿 —— **没有任何检查守着,所以没人发现**。
#    这里直接调页面用的那个函数,对全库总数:状态名写错、钱取错列、单子挂到不存在的顾问,都会红。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as _srv
_页 = _srv.guide_perf({})["rows"]
_页单, _页钱 = sum(r["orders"] for r in _页), round(sum(r["amount"] for r in _页), 2)
_库 = q("""SELECT COUNT(*) n, ROUND(COALESCE(SUM(received),0),2) amt FROM ordr
          WHERE prd_status NOT IN ('待付款','已关闭')""")[0]
if (_页单, _页钱) != (_库["n"], _库["amt"]):
    bad.append(f"导购业绩合计 ≠ 全库已付款未关闭的实收:页面 {_页单} 单 / {_页钱},"
               f"库里 {_库['n']} 单 / {_库['amt']} —— 状态名、金额列或顾问归属有一处对不上")

print("会员与订单一致性检查\n" + "=" * 68)
print(f"订单 {q('SELECT COUNT(*) n FROM ordr')[0]['n']} · 订单行 {q('SELECT COUNT(*) n FROM ordr_item')[0]['n']}"
      f" · 会员 {q('SELECT COUNT(*) n FROM customer')[0]['n']}"
      f" · 积分流水 {q('SELECT COUNT(*) n FROM points_log')[0]['n']}"
      f" · 绑定 {q('SELECT COUNT(*) n FROM member_bind')[0]['n']}")
for w in warn: print(f"  ⚠️  {w}")
if bad:
    for b in bad[:20]: print(f"  ❌ {b}")
    if len(bad) > 20: print(f"  … 另有 {len(bad)-20} 条")
    print(f"\n❌ {len(bad)} 处不一致"); sys.exit(1)
print(f"\n✅ 状态映射、金额勾稽、时间顺序、等级门槛、积分行为、绑定关系、导购业绩合计({_页单} 单)全部一致")
