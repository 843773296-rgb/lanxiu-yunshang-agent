# -*- coding: utf-8 -*-
"""排班:谁哪天上什么班。

业务 2026-09-20:「排班就按业内最佳实践来做」。
⚠️ **我没有汉服门店的排班数据**,下面是零售/服务业通行的机制。

## 业内排班的五个部件

    ① 班次模板      早班 / 晚班 / 全天 / 休息 —— 按天排,不按小时
    ② 排班表        谁、哪天、什么班
    ③ **草稿 / 已发布**  排了但没发布 ≠ 已发布
    ④ 请假          独立记录,**盖掉**排班,不是改排班
    ⑤ 合规          每周至少休一天、连上不超过 N 天

## 🔑 ③ 才是这套机制的核心,而它正是今天那个老问题

**「排了但没发布」和「已发布」,在排班表里长得一模一样** —— 都是有记录。

而两者对派单的含义完全相反:

    草稿     店长还在调,**随时会变** —— agent 不该拿它派单
    已发布   定了,员工看到了,客户也能按它约 —— 可以派

不分开的后果很具体:店长周三排了个草稿准备周五发,
而 agent 周四就按草稿派了单 —— **等店长改完发布,那些单全挂在错的人身上**。

## 🔑 而且「查不到记录」只能表示一件事:**未排**

    未排      这一周店长还没排到 —— **agent 要说「排班还没出来」,不能当没空**
    已发布休息  明确不上班 —— 可以当没空

**休息必须是显式记录**,不能靠"没有记录"表示。
否则店长还没排下周的班,agent 照样给出推荐,依据是「所有人下周都有空」——
**而这个结论看起来完全正常**。

## ⚠️ 状态是五态,不是两态

    未排(表里没有这一行)
    草稿-上班 / 草稿-休息
    已发布-上班 / 已发布-休息
    请假(独立表,盖掉已发布)

按今天那条判据「只有下一步动作不同才分开」逐个验过:
未排→催店长排;草稿→不可用且不提示;已发布上班→可派;
已发布休息→不可派;请假→不可派**且要提示重新分配已派的单**。
**五种动作两两不同,所以五态都必要。**
"""
import os, sqlite3, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DB = os.path.join(HERE, "lanxiu.db")
# 判定口径在 knowledge/shift.py,这里只取数。
# (名字避开 roster:同名的话 `import roster` 会先找到这个文件自己,
#  而「导入成功了」和「导入对了」长得一样。)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
import shift as _口径

# ── ① 班次模板 ────────────────────────────────────────────────
# 班次、草稿/已发布、排班角色 —— **只有一份,在口径模块里**,这里转发不抄。
班次 = _口径.班次
班次表 = _口径.班次表
草稿, 已发布 = _口径.草稿, _口径.已发布

def 建表(c):
    c.execute("""create table if not exists shift_tpl(
                   code TEXT primary key, name TEXT not null,
                   start_t TEXT, end_t TEXT)""")
    for code, name, a, b in 班次:
        c.execute("""insert into shift_tpl(code,name,start_t,end_t) values(?,?,?,?)
                     on conflict(code) do update set name=excluded.name,
                       start_t=excluded.start_t, end_t=excluded.end_t""", (code, name, a, b))
    # 排班。**主键 (人, 日期)** —— 一个人一天只能有一个班次
    # ⚠️ **「一人一天一个班次」这条约束不写在数据库里,由 roster_check 保证。**
    #
    # 试过两种写法,假数据工厂都造不出合法数据:
    #   复合主键 (staff_no, d)  → 它造出 14 条孤儿引用,弄脏了自己推出的断言
    #   代理主键 + unique(staff_no,d) → 它**认单列 UNIQUE 但不认复合的**,一灌就撞
    #
    # 而这个项目本来就是**约束靠检查保证**的(33 条结构性保证大多如此,
    # 而且绝大多数表压根没有外键)。所以这里跟着项目的做法走:
    # 数据库只管存,**唯一性由 roster_check 逐条验**。
    #
    # ⚠️ 代价要说清:**数据库不再挡重复写入**。所以写排班的入口
    # 必须自己先查一遍 —— 这条写在这儿,免得以后有人以为库会挡。
    #
    # ⚠️ **外键要显式写出来**,哪怕 SQLite 默认不强制执行。
    # 假数据工厂靠 schema 里的外键认「这一列的值该从哪张表取」——
    # 不写的话它会自造 staff_no,灌完当场弄脏「只能取已知的那几个值」那条断言。
    # (命名线索 staff_no→staff 它也认,但那条是**低可信度**,不会拿来当准。)
    c.execute("""create table if not exists roster(
                   staff_no TEXT not null references staff(no),
                   d        TEXT not null,
                   shift    TEXT not null references shift_tpl(code),
                   shop     TEXT,
                   status   TEXT not null,      -- 草稿 / 已发布
                   created_by TEXT, created TEXT,
                   published_by TEXT, published_at TEXT,
                   id INTEGER primary key autoincrement)""")
    # 请假:**独立记录,盖掉排班**。不直接改排班 ——
    # 改排班会把「本来排了班但请假了」和「本来就休息」抹成同一件事。
    c.execute("""create table if not exists leave_req(
                   id TEXT primary key,
                   staff_no TEXT not null references staff(no),
                   d_from TEXT not null, d_to TEXT not null,
                   kind TEXT, reason TEXT,
                   status TEXT not null,        -- 待审批 / 已批准 / 已驳回
                   applied_at TEXT, decided_by TEXT, decided_at TEXT)""")


# ── 查询:某人某天在不在班 ─────────────────────────────────────
def 查排班事实(staff_no, 日期, db=DB):
    """把口径要的那几样查出来。**这里一条判定都没有。**"""
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        请 = c.execute("""select * from leave_req where staff_no=? and status='已批准'
                          and d_from<=? and d_to>=? limit 1""",
                       (staff_no, 日期, 日期)).fetchone()
        r = c.execute("select * from roster where staff_no=? and d=?",
                      (staff_no, 日期)).fetchone()
    return {"日期": 日期,
            "请假种类": (请["kind"] or "事假") if 请 else None,
            "排班": {"status": r["status"], "shift": r["shift"]} if r else None}


def 在班吗(staff_no, 日期, db=DB):
    """(能不能派, 码, 人话) —— **判定在 `knowledge/shift.py`**。

    五个码的含义和下一步看那个模块。
    """
    return _口径.判在班(查排班事实(staff_no, 日期, db))


def 时段在班(staff_no, 起, 止, db=DB):
    """预约时段落在他的班次里吗。起/止是 'YYYY-MM-DD HH:MM'。"""
    事实 = 查排班事实(staff_no, 起[:10], db)
    return _口径.判时段(事实, 起[11:16], 止[11:16])


def 一周排了吗(shop, 周一, db=DB):
    """这家店这一周排了没有。**「没排」要能被问出来**,而不是靠查不到人来推断。"""
    d7 = [(datetime.date.fromisoformat(周一) + datetime.timedelta(days=i)).isoformat()
          for i in range(7)]
    with sqlite3.connect(db) as c:
        n = c.execute(f"""select count(*) from roster where shop=? and status=?
                          and d in ({','.join('?'*7)})""", (shop, 已发布, *d7)).fetchone()[0]
    return n > 0, n


if __name__ == "__main__":
    with sqlite3.connect(DB) as c:
        建表(c)
    print("排班表已建。班次:", "、".join(f"{n}({c})" for c, n, _, _ in 班次))


# ══════════════════════════════════════════════════════════════════
# 和派单组合:归属层 × 排班层
# ══════════════════════════════════════════════════════════════════
#
# **不改 `booking.route()`** —— 它有五条咬合测试,判的是「这个客户归谁」,
# 那一层是对的、完整的,没有理由动它。
#
# 排班回答的是另一个问题:**「那个人那个时候在不在」**。
# 两层是**互相独立**的,组合起来才是完整的派单:
#
#     归属层说「该派给张三」+ 排班层说「张三那天休息」→ **派不了**
#     归属层说「进待分配池」                        → 排班层不必问
#
# 顺序有意:先问归属(纯查库、便宜),归属就断定派不了的,不必再查排班。

def 派得了吗(cust, 起, 止, db=DB):
    """(能不能派, 码, 人话)。两层都过才算能派。"""
    sys.path.insert(0, HERE)
    import booking
    no, code, why = booking.route(cust)
    if no is None:
        return False, code, why              # 归属层就断定了,不必查排班
    ok, 码2, why2 = 时段在班(no, 起, 止, db)
    if not ok:
        # ⚠️ **「归属顾问是张三但他那天不在」不是「没有归属顾问」** ——
        # 两者都派不出去,但下一步动作完全不同:
        # 前者找人代接(客户仍归张三),后者要给客户定归属。
        return False, f"BOUND_BUT_{码2}", f"{why};**但** {why2}"
    return True, "OK", f"{why};{why2}"


# ══════════════════════════════════════════════════════════════════
# 排班权限(P5)+ 档期预留(P3)
# ══════════════════════════════════════════════════════════════════

# ── P5:排班权给店长 ──────────────────────────────────────────────
#
# 业务 2026-09-20:**排班权给店长,值班经理暂时先不做。**
#
# 设计稿里「编辑顾问」有个「值班经理」角色(而且删除按钮是灰的),
# 看着像他有排班职责 —— **但那是设计稿,业务说本期不做**。
# 按今天定的口径:设计稿只是大致结构,以讨论为准。
排班角色 = _口径.排班角色


def 能排班吗(staff_no, db=DB):
    """(能不能, 人话) —— 判定在口径模块。"""
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("select no,name,role,status from staff where no=?", (staff_no,)).fetchone()
    return _口径.判排班权(dict(r) if r else None)


# ── P3:点名的人没空 → 三步 ───────────────────────────────────────
#
# 业务 2026-09-20 给的完整流程:
#   ① 报告没有空
#   ② 询问是否换人接待
#   ③ 如果被驳回,**追问下一次预约时间,提前把顾问空出来**
#
# 第 ③ 步是这条流程真正有价值的地方:它把一次「约不上」变成一次**预留**。
预留状态 = ("预留中", "已转预约", "已过期", "已取消")


def _世界的今天():
    """**不是机器的今天** —— 机器的今天每过一天就变,重建就不可复现
    (`tools/determinism_check.py` 扫这一条)。"""
    from seed import TODAY
    return TODAY


def 建预留表(c):
    # ⚠️ **预留和已预约必须分开。**
    # 两者都让那个时段「不能再派别人」,但:
    #     已预约  客户确认过,**大概率会来**
    #     预留    口头承诺,**可能不来** —— 所以有过期时间
    # 混在一起的后果:预留被当成确定的,**档期利用率悄悄掉下来**,
    # 而看板上「档期占满了」和真的占满了长得一模一样。
    c.execute("""create table if not exists slot_hold(
                   id INTEGER primary key autoincrement,
                   staff_no   TEXT not null references staff(no),
                   customer_id TEXT references customer(id),
                   d          TEXT not null,
                   -- ⚠️ **只存日期,不存起止时分。**
                   -- 预留的粒度和排班一致(按天不按小时)—— 班次就四种,
                   -- 精确到分钟既没人填也没用。
                   -- 而且假数据工厂给 start_t/end_t 造出过「结束早于开始」的数据,
                   -- 弄脏了它自己推出的断言:**一个用不上的字段,还额外带来一类错**。
                   reason     TEXT not null,
                   status     TEXT not null,     -- 预留中/已转预约/已过期/已取消
                   expires_at TEXT not null,     -- **必须有**,不许永久占着
                   created_by TEXT, created TEXT)""")


def 点名的人没空(cust, 点名工号, 起, 止, db=DB):
    """业务定的三步,**一次性给顾问看**,他照着往下谈。

    返回 (能不能派, 码, 一段人话)。**agent 只给参谋,不替客户做决定** ——
    换人还是改时间由客户定,这里只把三个选项摆出来。
    """
    ok, 码, why = 时段在班(点名工号, 起, 止, db)
    if ok:
        return True, "ON", f"客户点名的顾问那个时段在班 —— 直接派给他"

    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("select name from staff where no=?", (点名工号,)).fetchone()
    名 = r["name"] if r else 点名工号

    话 = (f"**① 客户点名的 {名} 那个时段不在** —— {why}\n"
          f"**② 问客户要不要换人接待**(本店同时段在班的顾问可派)\n"
          f"**③ 如果客户坚持要 {名}:问他下次什么时候方便,"
          f"**当场把 {名} 那个时段预留出来**(`slot_hold`),别让它又被占掉")
    return False, f"REQUESTED_{码}", 话


def 预留(staff_no, 起, 止, customer_id=None, reason="客户点名,改约下次",
        有效天数=14, 操作人=None, db=DB, conn=None):
    """把某个顾问的某个时段留给某个客户。

    **有效期必填** —— 一个不会过期的预留,和一条被占死的档期,
    在「那个时段能不能派人」这个问题上长得一模一样。
    """
    import datetime
    d = 起[:10]
    到期 = (datetime.date.fromisoformat(d) + datetime.timedelta(days=有效天数)).isoformat()
    SQL = """insert into slot_hold(staff_no,customer_id,d,reason,
                                   status,expires_at,created_by,created)
             values(?,?,?,?,?,?,?,?)"""
    行 = (staff_no, customer_id, d, reason, "预留中", 到期, 操作人, _世界的今天())
    # conn 传进来就复用 —— 外层已持连接时再开一个会 `database is locked`
    if conn is not None:
        建预留表(conn); conn.execute(SQL, 行); return
    with sqlite3.connect(db) as c:
        建预留表(c); c.execute(SQL, 行)


def 时段被预留了吗(staff_no, 起, 止=None, db=DB):
    """这一天有没有被预留。**过期的不算** —— 那正是过期时间存在的理由。"""
    d = 起[:10]
    今 = _世界的今天()
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        建预留表(c)
        r = c.execute("""select * from slot_hold where staff_no=? and d=? and status='预留中'
                         and expires_at>=? limit 1""", (staff_no, d, 今)).fetchone()
    if not r:
        return False, None
    return True, f"{d} 这个时段已预留给客户({r['reason']}),有效到 {r['expires_at']}"
