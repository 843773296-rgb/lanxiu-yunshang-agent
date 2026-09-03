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

# ④ 时间戳顺序:付款 ≤ 审核 ≤ 生产 ≤ 发货 ≤ 完成
ORDER = ["paid_at","audit_at","produced_at","shipped_at","finished_at"]
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
print("\n✅ 状态映射、金额勾稽、时间顺序、等级门槛、积分行为、绑定关系 全部一致")
