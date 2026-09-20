#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造排班数据。

⚠️ **每个状态都要有样本,否则那些分支永远测不到。**
今天在别处踩过两次同形的:无主客户 0 条(分配逻辑永不触发)、
往年同期 0 条(那一支永不触发)——**而检查全绿**。

所以这里**故意**造出五种状态:

    已发布-上班   最近三周
    已发布-休息   每周至少一天(合规:每周至少休一天)
    草稿          下下周(店长排了还没发)
    未排          再往后 —— **表里没有那几天的行**
    请假          两条已批准的

确定性:班次按 (顾问序号 + 第几天) 算,**不用随机**
(SQL 的 RANDOM() 不受 Python 种子管,今天并行会话刚为这个排查了半天)。
"""
import os, sqlite3, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")
from seed import TODAY
import roster as R

排班来源 = "system"


def main():
    c = sqlite3.connect(DB)
    R.建表(c)
    c.execute("delete from roster where created_by=?", (排班来源,))
    c.execute("delete from leave_req where id like 'LV-%'")

    today = datetime.date.fromisoformat(TODAY)
    本周一 = today - datetime.timedelta(days=today.weekday())
    顾问 = [(r[0], r[1]) for r in c.execute(
        "select no, shop from staff where role='顾问' and status='启用' order by no")]

    n发布, n草稿, n休 = 0, 0, 0
    for i, (no, shop) in enumerate(顾问):
        # 已发布:上上周、上周、本周、下周(4 周)
        for w in (-2, -1, 0, 1):
            for d in range(7):
                日 = 本周一 + datetime.timedelta(weeks=w, days=d)
                # 确定性轮班:每人固定休一天(按序号错开),其余早/晚/全天轮
                休哪天 = i % 7
                if d == 休哪天:
                    班 = "S0"; n休 += 1
                else:
                    班 = ("S1", "S2", "S3")[(i + d) % 3]
                c.execute("""insert or replace into roster
                             (staff_no,d,shift,shop,status,created_by,created,published_by,published_at)
                             values(?,?,?,?,?,?,?,?,?)""",
                          (no, 日.isoformat(), 班, shop, R.已发布, 排班来源, TODAY,
                           "60000001", TODAY))
                n发布 += 1
        # 草稿:下下周(店长排了还没发布)
        for d in range(7):
            日 = 本周一 + datetime.timedelta(weeks=2, days=d)
            班 = "S0" if d == (i % 7) else ("S1", "S2", "S3")[(i + d) % 3]
            c.execute("""insert or replace into roster
                         (staff_no,d,shift,shop,status,created_by,created)
                         values(?,?,?,?,?,?,?)""",
                      (no, 日.isoformat(), 班, shop, R.草稿, 排班来源, TODAY))
            n草稿 += 1
        # 再往后**不排** —— 那就是「未排」,表里没有那些行

    # 请假两条(已批准),盖在已发布的班上
    if len(顾问) >= 2:
        for k, (no, _) in enumerate(顾问[:2]):
            起 = (本周一 + datetime.timedelta(days=2 + k)).isoformat()
            止 = (本周一 + datetime.timedelta(days=3 + k)).isoformat()
            c.execute("""insert into leave_req(id,staff_no,d_from,d_to,kind,reason,status,
                                               applied_at,decided_by,decided_at)
                         values(?,?,?,?,?,?,?,?,?,?)""",
                      (f"LV-{k+1:03d}", no, 起, 止, "事假", "家里有事", "已批准",
                       TODAY, "60000001", TODAY))
    c.commit()

    # ── 自己证明干了活 + 五种状态都有样本 ──────────────────────
    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    已发布 = q("select count(*) from roster where status=?", R.已发布)
    草 = q("select count(*) from roster where status=?", R.草稿)
    休 = q("select count(*) from roster where shift='S0' and status=?", R.已发布)
    假 = q("select count(*) from leave_req where status='已批准'")

    缺 = []
    if 已发布 == 0: 缺.append("已发布-上班")
    if 休 == 0: 缺.append("已发布-休息")
    if 草 == 0: 缺.append("草稿")
    if 假 == 0: 缺.append("请假")
    # 「未排」也要有样本:未来某天必须查不到行
    远 = (本周一 + datetime.timedelta(weeks=4)).isoformat()
    if q("select count(*) from roster where d=?", 远) != 0:
        缺.append("未排(排太满了,没有留出查不到的日子)")
    if 缺:
        sys.exit(f"❌ 这几种状态没有样本:{缺} —— **没有样本的分支永远测不到,而检查会全绿**")

    # 合规:每人每周至少休一天
    坏 = q(f"""select count(*) from (
                 select staff_no, strftime('%W', d) w, sum(shift='S0') s
                 from roster where status=? group by staff_no, w having s=0)""", R.已发布)
    if 坏:
        sys.exit(f"❌ 有 {坏} 个「人×周」一天没休 —— 每周至少休一天")

    print(f"  排班:已发布 {已发布} 天(含休息 {休} 天)、草稿 {草} 天、请假 {假} 条")
    print(f"  **五种状态都有样本**(含「未排」—— {远} 之后故意不排)")
    c.close()


if __name__ == "__main__":
    main()
