# -*- coding: utf-8 -*-
"""长期没人接触的客户 → 先知会原导购、再释放到本店公海(用户 2026-11-12 拍,台账第十四条;第二十九条:和跨店转移两条都生效)。

判定口径在 knowledge/ownership_protection.该放吗(第 173 天起知会、知会满 7 天且过第 180 天才放、没知会过的不直接放),
**这里只取数和落地**,不再抄一份天数。

「接触」算哪些(和跨店保护期的「维护」同一口径,外加两样):
  · 本店的订单(付款日 / 下单日)· 原导购的跟进记录(followup)· 原导购完结的任务 · 本店的预约(已到店 / 已完成 / **已预约**)
  · 已预约算接触:客户约好了下周来,不能这周被收走 —— 约在未来的日子会让「已过天数」为负,自然不动
  · 全都没有 → 退回建档日
按**账户**判(一个账户只归一位导购,用户 10-26 拍):同户几条档案的接触合在一起算,放就整户放。

「已知会日」不另建表 —— 就是派给原导购的那条「公海知会」任务的日子。通知和任务是同一条记录,不会分叉。

落地(`执行()`,默认不调;命令行要 `--写`):
  · 知会 → 给原导购派一条「公海知会」任务(点「知道了」就完成;7 天内联系并登记跟进,最后接触日刷新,自然不放)
  · 释放 → 整户 advisor_no 置空(公海 = 没有导购,ownership.py 文件头:结构本来允许为空)
           + 归属变更日志记「进公海 / 长期没接触释放」+ 给本店店长派一条「公海指派」任务
⚠️ 和 backend/ownership.py「agent 只给参谋、不自动改数据」(09-20)的关系:那条管的是**智能体**;
   这条是用户 11-12 拍的**系统规则**(有天数、有知会、有日志),不经过模型。

    python3 backend/ownership_release.py            # 只看:今天会知会谁、释放谁
    python3 backend/ownership_release.py --写 --店 店名   # 真写一家店(要锁:./tools/gate_lock.sh);用户 11-13 拍先一家店试
    python3 backend/ownership_release.py --写 --全部门店  # 试点过了再全部门店(不点名店又不写这个 → 拒写)
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge")]
import ownership_protection as OP     # noqa: E402

知会类型 = "公海知会"
指派类型 = "公海指派"
释放依据 = "长期没接触释放"


def _日们(c, sql, *a):
    return [r[0] for r in c.execute(sql, a).fetchall() if r[0]]


def 最后接触(c, 同户, 店, 导购, 建档):
    """→ (日期 或 None, 来自哪一类)。"""
    q = ",".join("?" * len(同户))
    订单 = _日们(c, f"SELECT COALESCE(paid_at, created) FROM ordr WHERE customer_id IN ({q}) AND shop=?", *同户, 店)
    跟进 = []
    if 导购:
        跟进 = _日们(c, f"SELECT ts FROM followup WHERE customer_id IN ({q}) AND advisor_no=?", *同户, 导购)
        跟进 += _日们(c, f"SELECT COALESCE(end_ts, start_ts) FROM schedule WHERE customer_id IN ({q}) AND advisor_no=? "
                        f"AND status IN ('完结','已完成') AND type NOT IN (?,?)", *同户, 导购, 知会类型, 指派类型)
    到店 = _日们(c, f"SELECT start_ts FROM appointment WHERE customer_id IN ({q}) AND shop=? "
                  f"AND status IN ('已到店','已完成','已预约')", *同户, 店)
    return OP.最后维护日(订单, 跟进, 到店, 建档)


def 已知会日(c, 同户):
    q = ",".join("?" * len(同户))
    r = c.execute(f"SELECT MAX(start_ts) FROM schedule WHERE type=? AND customer_id IN ({q})", (知会类型, *同户)).fetchone()
    return r[0] if r and r[0] else None


def 扫描(c, 今天, 只这家店=None):
    """→ [dict(客户, 同户, 店, 导购, 最后接触, 来自, 已知会日, 动作, 已过天数, 理由)]。只读。每个账户一行。
    只这家店:给了就只扫档案在这家店的客户(用户 11-13 拍「公海首跑先挑一家店试」)。"""
    出, 见过 = [], set()
    条件, 参 = "", ()
    if 只这家店:
        条件, 参 = " AND shop=?", (只这家店,)
    for cid, 店, 导购, 建档 in c.execute(
            "SELECT id, shop, advisor_no, created FROM customer "
            "WHERE advisor_no IS NOT NULL AND advisor_no<>''" + 条件 + " ORDER BY id", 参).fetchall():
        if cid in 见过:
            continue
        r = 判一户(c, cid, 今天, (店, 导购, 建档))
        见过.update(r["同户"])
        出.append(r)
    return 出


def 判一户(c, cid, 今天, 档=None):
    """一个客户(连同户)今天该不动 / 知会 / 释放。扫描和检查共用这一份。"""
    import account_owner as AO
    店, 导购, 建档 = 档 or c.execute("SELECT shop, advisor_no, created FROM customer WHERE id=?", (cid,)).fetchone()
    同户 = AO.同户档案(c, [cid]) or [cid]
    维, 来自 = 最后接触(c, 同户, 店, 导购, 建档)
    知 = 已知会日(c, 同户)
    判 = OP.该放吗(维, 今天, 知)
    return dict(客户=cid, 同户=同户, 店=店, 导购=导购, 最后接触=str(维) if 维 else None, 来自=来自, 已知会日=知, **判)


def _派(c, 类型, 给谁, 客户, 店, 说明, 今天):
    import ownership_transfer as OT
    return OT._派知会(c, 给谁, 客户, 店, 说明, 今天, 类型=类型)


def 执行(c, 今天, 操作人="系统", 行们=None, 只这家店=None):
    """在调用方给的连接 / 事务里写。→ dict(知会=[任务号…], 释放=[客户…], 指派任务=[…])。
    只这家店:给了就连调用方传进来的行们也再按店筛一遍 —— 「先一家店试」不靠调用方记得筛。"""
    import ownership_transfer as OT
    行们 = 扫描(c, 今天, 只这家店) if 行们 is None else 行们
    if 只这家店:
        行们 = [r for r in 行们 if r.get("店") == 只这家店]
    结果 = dict(知会=[], 释放=[], 指派任务=[])
    for r in 行们:
        if r["动作"] == "知会":
            sid = _派(c, 知会类型, r["导购"], r["客户"], r["店"],
                     f"【公海知会】客户 {r['客户']}(同户 {len(r['同户'])} 条档案)最后一次接触是 {r['最后接触']}({r['来自']}),"
                     f"已过 {r['已过天数']} 天。{OP.知会提前天} 天内联系并登记跟进就继续归你;否则释放到本店公海,由店长指派。点「知道了」即完成。",
                     今天)
            if sid:
                结果["知会"].append(sid)
        elif r["动作"] == "释放":
            q = ",".join("?" * len(r["同户"]))
            c.execute(f"UPDATE customer SET advisor_no=NULL WHERE id IN ({q})", r["同户"])
            c.execute(f"UPDATE appointment SET advisor_no=NULL WHERE customer_id IN ({q}) AND status='已预约'", r["同户"])
            for i in r["同户"]:
                c.execute("INSERT INTO cust_owner_log(customer_id,frm,too,action,basis,actor,ts) VALUES(?,?,?,?,?,?,?)",
                          (i, r["导购"], None, "进公海", 释放依据, 操作人, str(今天)[:10]))
            结果["释放"].append(r["客户"])
            sid = _派(c, 指派类型, OT._店长(c, r["店"]), r["客户"], r["店"],
                     f"【公海指派】客户 {r['客户']}(同户 {len(r['同户'])} 条档案)原导购 {r['导购']},最后接触 {r['最后接触']},"
                     f"{r['已知会日']} 知会后 {OP.知会提前天} 天没有新接触,已释放到本店公海 —— 请指派一位导购。", 今天)
            if sid:
                结果["指派任务"].append(sid)
    return 结果


def _印(行们):
    数 = Counter(r["动作"] for r in 行们)
    print(f"共 {len(行们)} 个账户(有导购的):" + " · ".join(f"{k} {数[k]}" for k in ("不动", "知会", "释放")))
    for r in [x for x in 行们 if x["动作"] != "不动"][:20]:
        print(f"  {r['动作']} {r['客户']}({r['店']} / {r['导购']}):{r['理由']}")
    多 = sum(1 for x in 行们 if x["动作"] != "不动") - 20
    if 多 > 0:
        print(f"  …还有 {多} 条没印")


if __name__ == "__main__":
    import sqlite3
    from contextlib import closing
    import worldclock
    今天 = worldclock.今天()
    db = os.environ.get("LANXIU_DB") or os.path.join(HERE, "lanxiu.db")
    店 = sys.argv[sys.argv.index("--店") + 1] if "--店" in sys.argv and sys.argv.index("--店") + 1 < len(sys.argv) else None
    全部 = "--全部门店" in sys.argv
    with closing(sqlite3.connect(db, timeout=30)) as c:
        行们 = 扫描(c, 今天, 店)
        print(f"今天(世界时钟)= {今天}" + (f" · 只看 {店}" if 店 else ""))
        _印(行们)
        if not 店:
            按店 = Counter(r["店"] for r in 行们 if r["动作"] != "不动")
            print("按门店(要动的):" + " · ".join(f"{k} {v}" for k, v in 按店.most_common()))
        if "--写" in sys.argv:
            # 用户 11-13 拍「公海首跑先挑一家店试」:真写必须点名一家店;要全部门店得明说 --全部门店
            if not 店 and not 全部:
                print("❌ 没写:真写要点名一家店(--店 店名);试点过了要全部门店一起跑,明写 --全部门店")
                sys.exit(2)
            if 店 and not 行们:
                print(f"❌ 没写:{店} 一户都没扫到 —— 店名对吗?")
                sys.exit(2)
            with c:
                r = 执行(c, 今天, 行们=行们, 只这家店=店)
            print(f"已写:知会 {len(r['知会'])} 条 · 释放 {len(r['释放'])} 户 · 指派任务 {len(r['指派任务'])} 条")
        else:
            print("(只看没写。真写加 --写,先拿锁)")
