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

# ── ① 班次模板 ────────────────────────────────────────────────
# 按天排不按小时:按小时店长不会填,而预约本来就是按时段来的。
班次 = [
    ("S1", "早班", "10:00", "16:00"),
    ("S2", "晚班", "16:00", "22:00"),
    ("S3", "全天", "10:00", "22:00"),
    ("S0", "休息", None, None),
]
班次表 = {c: (n, a, b) for c, n, a, b in 班次}

草稿, 已发布 = "草稿", "已发布"


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
def 在班吗(staff_no, 日期, db=DB):
    """返回 (能不能派, 码, 人话)。

    **「不能派」有四种原因,不能合成一个** —— 它们的下一步动作不同:
        UNSCHEDULED 还没排  → 催店长排班,**不是这个人没空**
        DRAFT       草稿    → 等发布,别用
        OFF         已发布休息 → 确实没空
        LEAVE       请假    → 没空,**而且已派的单要重新分配**
    """
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        请 = c.execute("""select * from leave_req where staff_no=? and status='已批准'
                          and d_from<=? and d_to>=? limit 1""", (staff_no, 日期, 日期)).fetchone()
        if 请:
            return False, "LEAVE", (f"{日期} 请假中({请['kind'] or '事假'})—— "
                                    f"**已经派给他的单要重新分配**")
        r = c.execute("select * from roster where staff_no=? and d=?", (staff_no, 日期)).fetchone()
        if not r:
            # **这一条是整套机制的命根子**:没有记录 = 还没排,不等于没空
            return False, "UNSCHEDULED", (
                f"{日期} 还没排班 —— **这不是「他没空」,是「排班还没出来」**;"
                f"拿它当没空,会在店长还没排的时候给出一份看起来正常的推荐")
        if r["status"] != 已发布:
            return False, "DRAFT", f"{日期} 的排班还是草稿,**店长随时会改** —— 等发布"
        if r["shift"] == "S0":
            return False, "OFF", f"{日期} 已发布为休息"
        名, a, b = 班次表.get(r["shift"], ("?", None, None))
        return True, "ON", f"{日期} {名}({a}–{b})"


def 时段在班(staff_no, 起, 止, db=DB):
    """预约时段落在他的班次里吗。起/止是 'YYYY-MM-DD HH:MM'。"""
    日期 = 起[:10]
    ok, 码, why = 在班吗(staff_no, 日期, db)
    if not ok:
        return False, 码, why
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("select * from roster where staff_no=? and d=?", (staff_no, 日期)).fetchone()
    名, a, b = 班次表.get(r["shift"], ("?", None, None))
    if not a:
        return False, "OFF", f"{日期} 休息"
    h起, h止 = 起[11:16], 止[11:16]
    if h起 >= a and h止 <= b:
        return True, "ON", f"{日期} {名}({a}–{b}),预约 {h起}–{h止} 落在班内"
    return False, "OUT_OF_SHIFT", (f"{日期} 他是{名}({a}–{b}),而预约是 {h起}–{h止} —— "
                                   f"**在班 ≠ 那个点有空**")


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
