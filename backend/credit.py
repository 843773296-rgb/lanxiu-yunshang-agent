# -*- coding: utf-8 -*-
"""成交归因的记录结构:谁对这一单有贡献,贡献多少。

业务 2026-09-20 的判断:
> **成交率毕竟是一个长期一对一营销的结果,不能因为某一次就算在某人身上。**

这句话推翻了「按接待人算」这个简化 —— 它在业内叫**归因(attribution)**,
和广告归因是同一类问题:一个结果由多方共同促成,每一方的贡献怎么分。

## 🔑 两种分成,必须彻底分开

CRM 里(Salesforce 的 Opportunity Splits)这是两张不同的东西:

    收入分成  Revenue Split   —— **加起来必须 100%**。用来算提成,是**分蛋糕**
    影响力分成 Overlay Split  —— **可以超过 100%**。用来记贡献,**不是零和的**

一单 10 万可以同时是:
    收入   张三 70% · 李四 30%          (加起来 100%,这是钱)
    影响力 张三 100% · 李四 60% · 店长 40%  (加起来 200%,这是贡献)

**混在一起就全错了** —— 而它们在库里长得一模一样:都是「某人 + 某个百分比」。
所以 `kind` 是必填,而且两种的校验规则**相反**:
一种总和必须 100,另一种**不许**强制 100。

**你要的「成交率」属于影响力那一类** —— 它衡量能力,不是分钱。

## 🔑 「人填的」和「算法算的」也要分开

现在没有客户旅程数据(跟进 24 条、沟通记录 0 条),所以贡献只能人填或按规则给。
将来有了触点数据,可以上 W 型归因,再往后触点够了可以上 Shapley。

**三者算出来都是一个百分比,长得一模一样。** 所以 `source` 必填:
人工填 / 规则算 / 算法算(将来还要记是哪个算法、哪一版)。

不分开的后果:换了归因算法之后,**老数据和新数据混在一张表里,
而谁也说不清某一条是哪种算法的结果** —— 那时候整张表就废了。

## ⚠️ 这一版**只记录,不算率**

算成交率要先有:① 订单能追到哪次接待(P18,现在断着)
② 触点数据(现在几乎没有)。两样都不到位,算出来的率没有意义。
**先把结构立住** —— 它是 W 型和 Shapley 的共同前提,两条路都要用它。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
# 判定口径在 knowledge/attribution.py,这里只取数和写库。
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
import attribution as _口径

# 下面这几个是**转发不是抄件** —— 两份常量会各自漂,而漂了照样跑得出数。
收入分成, 影响力分成 = _口径.收入分成, _口径.影响力分成
角色, 来源 = _口径.角色, _口径.来源


def 建表(c):
    c.execute("""create table if not exists deal_credit(
                   id INTEGER primary key autoincrement,
                   order_id TEXT not null references ordr(id),
                   staff_no TEXT not null references staff(no),
                   kind     TEXT not null,     -- 收入分成(总和=100) / 影响力分成(不限)
                   role     TEXT not null,     -- 首次接待/量体/方案确认/成交/售后
                   pct      REAL not null,
                   source   TEXT not null,     -- 人工填/规则算/算法算
                   method   TEXT,              -- 算法名+版本(source=算法算 时必填)
                   basis    TEXT,
                   created  TEXT not null)""")


def 记一笔(order_id, staff_no, kind, role, pct, source, method=None, basis=None,
          ts=None, db=DB, conn=None):
    """conn 传进来就复用它 —— 批量灌数据时外层已经持着连接,
    再开一个会 `database is locked`(SQLite 不允许两个写连接)。"""
    坏 = _口径.校验一笔(kind, role, source, pct, method)
    if 坏:
        raise ValueError(坏)
    import datetime
    ts = ts or datetime.date.today().isoformat()
    行 = (order_id, staff_no, kind, role, pct, source, method, basis, ts)
    SQL = """insert into deal_credit
             (order_id,staff_no,kind,role,pct,source,method,basis,created)
             values(?,?,?,?,?,?,?,?,?)"""
    if conn is not None:
        建表(conn); conn.execute(SQL, 行); return
    with sqlite3.connect(db) as c:
        建表(c); c.execute(SQL, 行)


def 收入分成对不对(db=DB):
    """每一单的**收入分成**加起来必须是 100 —— 那是分蛋糕,不能多也不能少。

    返回不等于 100 的那些单。**影响力分成不在这条规则里**(口径在
    `knowledge/attribution.总和该不该管`)—— 拿同一条规则去查它,
    会把一整批本来就该超 100 的记录判成错的。
    """
    assert _口径.总和该不该管(收入分成) and not _口径.总和该不该管(影响力分成)
    with sqlite3.connect(db) as c:
        return [(r[0], round(r[1], 2)) for r in c.execute(
            """select order_id, sum(pct) s from deal_credit where kind=?
               group by order_id having abs(s-100) > 0.01""", (收入分成,))]


def 一单的贡献(order_id, db=DB):
    """这一单谁参与了、各占多少。**两种分成分开列**。"""
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(
            "select * from deal_credit where order_id=? order by kind, pct desc", (order_id,))]
    出 = {收入分成: [], 影响力分成: []}
    for r in rows:
        出.setdefault(r["kind"], []).append(r)
    return 出


if __name__ == "__main__":
    with sqlite3.connect(DB) as c:
        建表(c)
        n = c.execute("select count(*) from deal_credit").fetchone()[0]
    print(f"归因记录表已建,现有 {n} 条")
    print(f"两种分成:{收入分成}(总和=100,分钱) · {影响力分成}(不限,记贡献)")


# ══════════════════════════════════════════════════════════════════
# W 型归因:用真实触点算每个人的影响力
# ══════════════════════════════════════════════════════════════════
#
# B2B 销售的标准模型,三个关键节点各 30%,其余触点平分 10%:
#
#     首次触达  30%   —— 第一个碰到这个客户的人
#     关键节点  30%   —— 定制业务里对应**量体**(后面所有事都建立在那组数据上)
#     成交      30%   —— 促成下单的人
#     其余      10%   —— 中间的跟进、日程,平分
#
# ⚠️ **这个 30/30/30/10 是行业惯例,不是算出来的。**
# 换成 40/20/30/10 排序就可能变 —— 而两种算出来的数都叫「影响力」。
# 所以入库时 `method` 必须写明「W型归因 v1」,换了参数就是另一个版本。
#
# ⚠️ **造的旅程算出来的分配,不能当成真实贡献。**
# 真实客户会绕弯、中断,而造出来的旅程一步不落。
# 这个函数证明的是「算法跑得通」,不是「算得准」。

W型权重 = _口径.W型权重          # 转发,不抄
关键节点类型 = _口径.关键节点类型


def W型归因(order_id, db=DB):
    """算这一单里每个人的影响力 —— **算法在 `knowledge/attribution.W型分配`**,
    这里只把触点旅程取出来。"""
    sys.path.insert(0, HERE)
    import touchpoint as T
    cid, 旅 = T.这一单之前(order_id, db=db)
    return _口径.W型分配(旅)
