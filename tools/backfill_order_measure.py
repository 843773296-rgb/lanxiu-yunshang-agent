#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给每件定制单补一次**下单量体**(绑到订单行)—— 让演示数据守业务 09-22 定的规矩。

业务:「签订订单的时候,会根据定制服装的要求重新进行量体,以这次为准」;
追问后定:**没有下单量体就不许下单**(回头客也一样)。口径在 knowledge/measure.py。

而演示数据里**一张定制单都没有下单量体** —— 推荐尺码、判全定制改成「以哪次为准」
(这件有下单量体就用它,没有就用最近一整次、缺项不拼)之后,
**51% 的件判成「需补量」**:每个人最近那次量体多半只量了几项。
数据违反了业务规矩,规则只能如实报「需补量」—— 那不是规则的问题,是造数据漏了这一步。

怎么补:
  · 每件还没有下单量体的定制单行,在**下单当天**补一次:到店为主、一成上门
  · **量的人过半不是订单顾问**,是同店另一个在职顾问(业务:过半的单接待人和订单顾问不是同一个人)。
    原来一律写订单顾问,代价见下面「谁量这一次」那一段 —— 它把「接待人」这个维度按死了
  · 量全套(body_gen 造的那些项;马面宽度不是人体尺寸,不造)
  · 数值用 body_gen,**和这个人别的量体同一个 key(着装人)**—— 同一个身体,不是另起一个人
  · 三个条件记全(内搭 薄 / 赤足 / 平静呼气)
  · 着装人没定的那一件跳过,**不猜给谁量**(下单量体量的必须是穿这件的人)
确定性:不用随机数,方式按订单行号取余。
"""
import os, sys, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), ROOT]
import body_gen as B
# **反例夹具不补。** 王清和(W10010-2)那一件是故意留着的「量体过期还下了单」——
# 供「超期量体不许下单」和边界审计用。补上一次下单量体,这条规则就没了用例,
# 而且在新规下它**正好也是「没有下单量体就不许下单」的反例**。同一份名单,不另抄。
from fix_order_measure import 夹具着装人集

DB = os.path.join(ROOT, "backend", "lanxiu.db")


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    行 = c.execute("""SELECT i.id, i.wearer_id, o.created, o.advisor_no, o.customer_id, o.shop,
                             w.gender, w.birthday, w.height
                      FROM ordr_item i JOIN ordr o ON o.id=i.order_id
                      LEFT JOIN wearer w ON w.id=i.wearer_id
                      WHERE o.kind='定制品订单'
                        AND NOT EXISTS(SELECT 1 FROM measure_rec m WHERE m.order_item_id=i.id)
                      ORDER BY i.id""").fetchall()
    # ── 谁量这一次 ───────────────────────────────────────────────────
    # ⚠️ **原来一律写订单上的顾问,而业务说的是「过半的单,接待人和订单顾问不是同一个人」。**
    #
    # 代价不是「数据有点偏」。`ordr.recept_by`(接待人)是 `backfill_link` 从
    # **量体 / 白坯 / 预约**三处反推的,而量体占接待证据的九成 ——
    # 量体人一律等于订单顾问,就等于把「接待人」这个维度**按死成订单顾问**:
    # 实测 `measured_by_no` 和 `advisor_no` 71910 条**100% 相同**,
    # 于是「接待人和订单顾问不同」的单从「过半」塌到 **0.3%**(从零建库实测 12/3565)。
    # > 判据问的是「存在不同的人吗」,所以 35/4222 和 2300/4222
    # > **在那个布尔上长得一模一样** —— 塌到 0.8% 它照样绿(见 backend/link_check.py ③.5)。
    #
    # 改法:**同店**另一个在职顾问(跨店是另一个病 —— 旧数据 58% 跨店,已修过一次),
    # 按订单行号取余挑,**确定性,不抽随机数**。
    # ⚠️ 顺带记一笔:杭州湖滨店**只有 1 个在职顾问**,那 879 张单换不出人来 ——
    #    所以这个比例的天花板是 79%,不是 100%。那是编制数据的形状,不在这里修。
    同店顾问 = {}
    for _s in c.execute("SELECT no, shop FROM staff WHERE role='顾问' AND status='启用' "
                        "AND shop IS NOT NULL AND shop<>'' ORDER BY no"):
        同店顾问.setdefault(_s["shop"], []).append(_s["no"])

    补, 跳, 夹, 换人 = 0, 0, 0, 0
    for r in 行:
        if not r["wearer_id"] or not r["created"]:
            跳 += 1; continue
        if r["wearer_id"] in 夹具着装人集:
            夹 += 1; continue
        # 「量体记录不全 · 我方免费改」的判责反例:seed 把那位客户的量体删到 3 项 ——
        # 现实里就是「量体没量完就下了单」,在新规下同样是违规样本。补全了,那条判责规则就没了用例
        # (09-22 重建当场撞上:真值标的是记录不全,规则算出记录完整)。
        if c.execute("SELECT COUNT(*) FROM measure_rec WHERE customer_id=?", (r["customer_id"],)).fetchone()[0] < 4:
            夹 += 1; continue
        # 下单当天、下单前一小时量(时间点只要落在下单那天、早于下单即可)
        t0 = datetime.datetime.strptime(str(r["created"])[:16], "%Y-%m-%d %H:%M")
        at = (t0 - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        体, _ = B.按编码(r["gender"], B.周岁(r["birthday"], at), r["height"], r["wearer_id"])
        方式 = "上门" if r["id"] % 10 == 3 else "到店"
        量体人 = r["advisor_no"]
        别人 = [x for x in 同店顾问.get(r["shop"] or "", []) if x != r["advisor_no"]]
        if 别人 and r["id"] % 10 >= 2:      # 八成的件换人。⚠️ **七成只换出 49.7%**:
            # 杭州湖滨店只有 1 个在职顾问,那 879 张单换不出人来,把天花板压到 79%。
            量体人 = 别人[r["id"] % len(别人)]
            换人 += 1
        for code, v in 体.items():
            c.execute("""INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by_no,measured_at,
                         method,wearer_id,order_item_id,cond_inner,cond_shoe,cond_breath)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (r["customer_id"], "下单量体", code, v, 量体人, at, 方式,
                       r["wearer_id"], r["id"], "薄", "赤足", "平静呼气"))
        补 += 1
    c.commit()
    有 = c.execute("SELECT COUNT(DISTINCT order_item_id) FROM measure_rec WHERE order_item_id IS NOT NULL").fetchone()[0]
    定 = c.execute("SELECT COUNT(*) FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                  "WHERE o.kind='定制品订单'").fetchone()[0]
    print(f"  补了 {补} 件的下单量体;着装人没定、不猜给谁量的 {跳} 件;反例夹具留着不补 {夹} 件")
    print(f"  其中 {换人} 件由**同店另一个在职顾问**量(业务:过半的单接待人不是订单顾问)——"
          f" 这个数直接决定 link_check ③.5 那条棘轮")
    print(f"  现在 {有}/{定} 件定制单有下单量体")


if __name__ == "__main__":
    main()
