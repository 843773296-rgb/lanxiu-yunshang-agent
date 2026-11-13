# -*- coding: utf-8 -*-
"""长期没人接触的客户 → 先知会原导购、再释放到本店公海(用户 2026-11-12 拍,台账第十四条;第二十九条:和跨店转移两条都生效)。

判定口径在 knowledge/ownership_protection.该放吗(第 173 天起知会、知会满 7 天且过第 180 天才放、没知会过的不直接放),
**这里只取数和落地**,不再抄一份天数。

「接触」算哪些(和跨店保护期的「维护」同一口径,外加两样):
  · 本店的订单(付款日 / 下单日)· 原导购的跟进记录(followup)· 原导购完结的任务 · 本店的预约(已到店 / 已完成 / **已预约**)
  · 已预约算接触:客户约好了下周来,不能这周被收走 —— 约在未来的日子会让「已过天数」为负,自然不动
  · 全都没有 → 退回建档日
按**账户**判(一个账户只归一位导购,用户 10-26 拍):同户几条档案的接触合在一起算,放就整户放。

「已知会日」记在 pool_notice(一户一行:哪天知会的、挂在哪条清单任务上)。
⚠️ 11-13 改:原来「不另建表 —— 就是那条一户一条的公海知会任务的日子」;用户 11-13 拍第三十九条「**每位顾问每次只收一条清单**」
   (首跑一人收了 160–190 条,待办被刷屏),一条任务对多户,日子就得另记。读的时候两边取最晚:
   pool_notice + 合并前留下的一户一条旧任务(`--合并旧知会` 跑完就没有旧的了)。

落地(`执行()`,默认不调;命令行要 `--写`):
  · 知会 → 每位原导购这次只派**一条**「公海知会」清单任务(列出他名下这次要知会的每一户;点「知道了」就完成),
           每户在 pool_notice 记一行;7 天内联系并登记跟进,最后接触日刷新,自然不放
  · 释放 → 整户 advisor_no 置空(公海 = 没有导购,ownership.py 文件头:结构本来允许为空)
           + 归属变更日志记「进公海 / 长期没接触释放」+ 给本店店长派一条「公海指派」任务
⚠️ 和 backend/ownership.py「agent 只给参谋、不自动改数据」(09-20)的关系:那条管的是**智能体**;
   这条是用户 11-12 拍的**系统规则**(有天数、有知会、有日志),不经过模型。

    python3 backend/ownership_release.py            # 只看:今天会知会谁、释放谁
    python3 backend/ownership_release.py --写 --店 店名   # 真写一家店(要锁:./tools/gate_lock.sh);用户 11-13 拍先一家店试
    python3 backend/ownership_release.py --写 --全部门店  # 试点过了再全部门店(不点名店又不写这个 → 拒写)
    python3 backend/ownership_release.py --合并旧知会       # 只看:一户一条的旧知会会合成几条清单
    python3 backend/ownership_release.py --合并旧知会 --写  # 真合并(要锁)
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


知会表DDL = """CREATE TABLE IF NOT EXISTS pool_notice(
  customer_id TEXT NOT NULL,      -- 账户里扫描到的那条档案(读的时候按同户全部档案查)
  advisor_no  TEXT,               -- 知会给谁(原导购)
  shop        TEXT,
  noticed_on  TEXT NOT NULL,      -- 知会日 YYYY-MM-DD(满 7 天才放,口径在 knowledge/ownership_protection)
  schedule_id TEXT,               -- 那条清单任务(一条任务对多户)
  PRIMARY KEY (customer_id, noticed_on))"""


def 建表(c):
    c.execute(知会表DDL)


def 已知会日(c, 同户):
    """→ 'YYYY-MM-DD' 或 None。pool_notice 和合并前的一户一条旧任务取最晚的那天。表还没建(从没写过)= 没知会过。"""
    q = ",".join("?" * len(同户))
    日们 = []
    r = c.execute(f"SELECT MAX(start_ts) FROM schedule WHERE type=? AND customer_id IN ({q})", (知会类型, *同户)).fetchone()
    if r and r[0]:
        日们.append(str(r[0])[:10])
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pool_notice'").fetchone():
        r = c.execute(f"SELECT MAX(noticed_on) FROM pool_notice WHERE customer_id IN ({q})", 同户).fetchone()
        if r and r[0]:
            日们.append(str(r[0])[:10])
    return max(日们) if 日们 else None


def 清单说明(户们, 今天):
    """一位导购这次要知会的那几户 → 清单任务的说明。户们:[dict(客户, 同户, 最后接触, 来自, 已过天数)]。"""
    行 = [f"{x['客户']}(最后接触 {x['最后接触']} · {x['来自']} · 已过 {x['已过天数']} 天"
         + (f" · 同户 {len(x['同户'])} 条档案" if len(x["同户"]) > 1 else "") + ")" for x in 户们]
    return (f"【公海知会】你名下 {len(户们)} 户客户长期没接触,快要释放到本店公海。{OP.知会提前天} 天内联系并登记跟进的,"
            f"继续归你;没联系的会释放到公海、由店长指派。点「知道了」即完成。名单:" + ";".join(行))


def _派清单(c, 导购, 店, 户们, 今天):
    """给一位导购派一条清单任务,每户记一行 pool_notice → 任务号(没派成 = None,pool_notice 也不记:没通知到就不算知会)。"""
    sid = _派(c, 知会类型, 导购, None, 店, 清单说明(户们, 今天), 今天)
    if sid:
        for x in 户们:
            c.execute("INSERT OR IGNORE INTO pool_notice(customer_id, advisor_no, shop, noticed_on, schedule_id) VALUES(?,?,?,?,?)",
                      (x["客户"], 导购, 店, str(今天)[:10], sid))
    return sid


def 扫描(c, 今天, 只这家店=None):
    """→ [dict(客户, 同户, 店, 导购, 最后接触, 来自, 已知会日, 动作, 已过天数, 理由)]。只读。每个账户一行。
    只这家店:给了就只扫档案在这家店的客户(用户 11-13 拍「公海首跑先挑一家店试」)。"""
    出, 见过 = [], set()
    # 受保护客户(评测夹具 + 评测真值依赖的客户)不扫:11-13 静安首跑给其中 12 户发了知会,
    # fixture_intact_check 当场红 ——「名下 0 单 0 触点」是那批夹具存在的意义,一条任务就把它们的边界打穿
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
    import order_mix as _OM
    保护 = set(_OM.受保护客户(c))
    条件, 参 = "", ()
    if 只这家店:
        条件, 参 = " AND shop=?", (只这家店,)
    for cid, 店, 导购, 建档 in c.execute(
            "SELECT id, shop, advisor_no, created FROM customer "
            "WHERE advisor_no IS NOT NULL AND advisor_no<>''" + 条件 + " ORDER BY id", 参).fetchall():
        if cid in 见过 or cid in 保护:
            continue
        r = 判一户(c, cid, 今天, (店, 导购, 建档))
        if 保护.intersection(r["同户"]):
            见过.update(r["同户"])
            continue
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
    结果 = dict(知会=[], 释放=[], 指派任务=[], 知会户数=0)
    建表(c)
    # 知会:每位导购(按店分开)这次只派一条清单任务(用户 11-13 拍第三十九条)
    分组 = {}
    for r in 行们:
        if r["动作"] == "知会":
            分组.setdefault((r["导购"], r["店"]), []).append(r)
    for (导购, 店), 户们 in sorted(分组.items()):
        sid = _派清单(c, 导购, 店, 户们, 今天)
        if sid:
            结果["知会"].append(sid)
            结果["知会户数"] += len(户们)
    for r in 行们:
        if r["动作"] == "释放":
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


def 合并旧知会(c, 写=False):
    """一户一条的旧「公海知会」任务(11-13 首跑留下的)→ 每位导购每个知会日一条清单任务 + pool_notice 每户一行;删旧任务。
    → dict(旧条数, 新条数, 明细=[(导购, 店, 日, 户数)])。写=False 只算不动。日子照旧(满 7 天从原知会日算,不因合并重新计时)。
    已经点了「知道了」的旧任务也合:合并只改「通知长什么样」,不改「哪天通知过」。"""
    旧 = c.execute("SELECT id, assignee_no, shop, substr(start_ts,1,10), customer_id FROM schedule "
                  "WHERE type=? AND customer_id IS NOT NULL ORDER BY assignee_no, start_ts, customer_id", (知会类型,)).fetchall()
    组 = {}
    for sid, 导购, 店, 日, cid in 旧:
        组.setdefault((导购, 店, 日), []).append((sid, cid))
    明细 = [(k[0], k[1], k[2], len(v)) for k, v in sorted(组.items())]
    if not 写:
        return dict(旧条数=len(旧), 新条数=len(组), 明细=明细)
    import ownership_transfer as OT
    建表(c)
    for (导购, 店, 日), 项 in sorted(组.items()):
        户们 = []
        for _, cid in 项:
            r = 判一户(c, cid, 日)          # 按原知会日重算一遍说明里的天数(和当时发出去的一致)
            户们.append(dict(r, 客户=cid))
        新 = _派(c, 知会类型, 导购, None, 店, 清单说明(户们, 日), 日)
        for sid, cid in 项:
            c.execute("INSERT OR IGNORE INTO pool_notice(customer_id, advisor_no, shop, noticed_on, schedule_id) VALUES(?,?,?,?,?)",
                      (cid, 导购, 店, 日, 新))
            c.execute("DELETE FROM schedule WHERE id=? AND type=?", (sid, 知会类型))
    return dict(旧条数=len(旧), 新条数=len(组), 明细=明细)


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
        if "--合并旧知会" in sys.argv:
            写 = "--写" in sys.argv
            if 写:
                with c:
                    m = 合并旧知会(c, 写=True)
            else:
                m = 合并旧知会(c)
            print(f"一户一条的旧知会 {m['旧条数']} 条 → 每人每天一条清单 {m['新条数']} 条" + ("(已合并)" if 写 else "(只看没动;真合并加 --写,先拿锁)"))
            for 导购, 店, 日, n in m["明细"][:30]:
                print(f"  {导购}({店})· {日} 知会的 {n} 户")
            sys.exit(0)
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
            print(f"已写:知会清单 {len(r['知会'])} 条(共 {r['知会户数']} 户)· 释放 {len(r['释放'])} 户 · 指派任务 {len(r['指派任务'])} 条")
        else:
            print("(只看没写。真写加 --写,先拿锁)")
