#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按业务规则填两组字段:订单的预约来路、顾问的入职日期。

## P18(业务 2026-09-20):**定制品必须有预约才能做,标品全部不用**

这条规则一下子把「26587 单全是未接入」变成了两类:

    定制品  **应该**有预约 → 现在还没挂上,标「未接入」(诚实的「不知道」)
    标品    本来就不用     → 标「无预约」(确认过的事实)

**分开之后,成交率的分母才有意义** —— 标品那批本来就不该进分母,
而定制品那批是**真正的数据缺口**。
不分开的话两者都是空,**看起来一样,而处理方式相反**。

## P8(业务 2026-09-20):**新人需要保底单,入职时间由数据工厂补充**

没有入职日期就判断不出谁是新人,「新人保底派单」那条规则做不了
(防马太效应:成交率高的人客户越来越多,新人永远接不到单)。

确定性:按工号序号推入职日期,**不用随机**。
"""
import os, sqlite3, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")
from seed import TODAY


def main():
    c = sqlite3.connect(DB)

    # ── P18:按 kind 定预约来路 ───────────────────────────────
    # ⚠️ `ordr.kind` 的值是「标品订单」「定制品订单」——**不是**「标品」「定制品」
    # (那是 `product.kind`)。第一版按后者写,**一单都没匹配上,而 update 不报错**,
    # 26587 单原样停在「未接入」。**「规则没生效」和「规则生效了但结果就是这样」长得一样** ——
    # 是自检里那条「标品必须标无预约」把它抓出来的。
    c.execute("update ordr set appt_src='无预约' where kind='标品订单'")
    c.execute("update ordr set appt_src='未接入' where kind<>'标品订单' "
              "and (appt_id is null or appt_id='')")
    c.execute("update ordr set appt_src='已关联' where appt_id is not null and appt_id<>''")

    # ── P8:顾问入职日期 ──────────────────────────────────────
    # 按工号顺序铺开:老员工早、新人晚。**最后两个顾问设成半年内入职**,
    # 否则「新人」这一档**一个样本都没有** —— 那条规则就永远测不到。
    today = datetime.date.fromisoformat(TODAY)
    # ⚠️ **按角色分别铺开**,不按全员。
    # 第一版按全员工号顺序铺,而顾问的工号都在前面 —— 结果**一个新人顾问都没有**,
    # 「新人保底派单」那条规则就永远测不到。自检当场抓到了。
    #
    # **「所有顾问都是老员工」和「我没造出新人样本」在库里长得一模一样。**
    for 角色 in [r[0] for r in c.execute("select distinct role from staff")]:
        同角色 = [r[0] for r in c.execute(
            "select no from staff where role=? order by no", (角色,))]
        n = len(同角色)
        for i, no in enumerate(同角色):
            # 同一角色内:第一个 6 年前,最后一个 2 个月前(新人),中间线性铺开
            天 = int(6 * 365 - i * (6 * 365 - 60) / max(n - 1, 1)) if n > 1 else 3 * 365
            c.execute("update staff set hired_at=? where no=?",
                      ((today - datetime.timedelta(days=天)).isoformat(), no))
    c.commit()

    # ── 自己证明干了活 ───────────────────────────────────────
    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    分布 = dict(c.execute("select appt_src, count(*) from ordr group by 1").fetchall())
    坏 = q("select count(*) from ordr where kind='标品订单' and appt_src<>'无预约'")
    坏2 = q("select count(*) from ordr where kind<>'标品订单' and appt_src='无预约'")
    if 坏 or 坏2:
        sys.exit(f"❌ 规则没落实:标品标错 {坏} 单、定制品被标成无预约 {坏2} 单")

    空职 = q("select count(*) from staff where hired_at is null or hired_at=''")
    if 空职:
        sys.exit(f"❌ 还有 {空职} 个员工没有入职日期 —— **空不等于「入职很久」**")

    半年内 = q("select count(*) from staff where role='顾问' and hired_at>=?",
               (today - datetime.timedelta(days=180)).isoformat())
    if 半年内 == 0:
        sys.exit("❌ 一个「半年内入职」的顾问都没有 —— "
                 "**「新人保底派单」那条规则就永远测不到,而检查会全绿**")

    print(f"  订单预约来路:{分布}")
    print(f"  顾问入职日期:{q('select count(*) from staff')} 人全部填了;其中半年内入职的顾问 {半年内} 人(新人样本)")
    c.close()


if __name__ == "__main__":
    main()
