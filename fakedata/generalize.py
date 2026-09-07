#!/usr/bin/env python3
"""泛化体检 —— 这工具到底是通用的,还是只在澜绣云裳这一个库上通用?

**不进 check.sh 的重活部分**;但它产出的「认出率」本身是个产品功能:
**接一个新系统之前,先告诉你它读懂了多少。**

## 为什么必须做这件事

这个工具从第一天起的说法就是「对任何系统提供假数据」,
而到今天为止它只在**一个** schema 上验证过。
和「只在一种数据库上验证过的方言层等于没有方言层」是同一类问题 ——
只不过这次跨的不是数据库,是**命名约定和建模风格**。

代码里确实攒了一堆对那个库的隐含假设:
写死的 `"created"`(不是 `created_at`)、写死的时间线列名表、中文数据池、
`_at` 后缀约定……在另一种风格的库上,这些会**静默失效** ——
不报错,只是那几层修正一条都不生效,而数据看起来还是"有数据"。

## 靶子:处处相反

| | 澜绣云裳 | 这个靶子 |
|---|---|---|
| 命名 | 中文业务名 + 缩写(`ordr` / `xz`) | 英文蛇形(`purchase_order`) |
| 主键 | 文本编号(`C10001`) | 整数自增 |
| 外键 | **一个都没声明** | **全部显式声明** |
| 时间列 | `created` / `paid_at` | `created_at` / `placed_at` |
| 金额 | REAL 元 | INTEGER **分** |
| 枚举 | 中文(`待付款`) | 英文(`pending`) |

这不是为了刁难,是真实世界里另一半系统就长这样。
"""
import json, os, sqlite3, sys, tempfile, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schema as S, discover as D, plan as P, gen as G, load as L

DDL = """
create table account(
  id integer primary key autoincrement,
  email text not null unique,
  display_name text not null,
  signup_date text not null,
  country_code text,
  status text not null default 'active'
);
create table purchase_order(
  id integer primary key autoincrement,
  account_id integer not null references account(id),
  order_no text not null unique,
  amount_cents integer not null,
  currency text not null default 'USD',
  status text not null default 'pending',
  created_at text not null,
  placed_at text,
  shipped_at text,
  updated_at text,
  foreign key(account_id) references account(id)
);
create table order_line(
  id integer primary key autoincrement,
  order_id integer not null references purchase_order(id),
  sku_code text not null,
  qty integer not null,
  unit_price_cents integer not null
);
create table support_ticket(
  id integer primary key autoincrement,
  account_id integer references account(id),
  subject text not null,
  severity text not null,
  opened_at text not null,
  closed_at text
);
"""

STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled"]


def build_db(path):
    c = sqlite3.connect(path)
    c.executescript(DDL)
    accs = [(i, f"user{i}@example.com", f"User {i}",
             "2025-%02d-%02d" % (i % 12 + 1, i % 28 + 1),
             ["US", "GB", "DE", "JP"][i % 4],
             "active" if i % 7 else "suspended") for i in range(1, 121)]
    c.executemany("insert into account values(?,?,?,?,?,?)", accs)
    orders, k = [], 0
    for i, a in enumerate(accs):
        n = 0 if i % 2 == 0 else (1 if i % 3 else 9)
        for _ in range(n):
            k += 1
            st = STATUSES[k % len(STATUSES)]
            # 时间戳要**真的递增**。第一版三个时间戳取值完全相同,
            # 于是 a≤b 和 b≤a 同时成立,统计推不出任何先后 ——
            # 靶子造得不真实,照出来的就不是工具的问题。
            import datetime as _dt
            t0 = _dt.datetime(2026, k % 9 + 1, k % 28 + 1, 9, k % 60)
            f = "%Y-%m-%d %H:%M:%S"
            placed = t0 + _dt.timedelta(hours=2 + k % 20)
            shipped = placed + _dt.timedelta(days=1 + k % 5)
            orders.append((k, a[0], f"PO-{k:06d}", 1000 + k * 137, "USD", st,
                           t0.strftime(f),
                           placed.strftime(f) if st != "pending" else None,
                           shipped.strftime(f) if st in ("shipped", "delivered") else None,
                           (shipped + _dt.timedelta(days=1)).strftime(f)))
    c.executemany("insert into purchase_order values(?,?,?,?,?,?,?,?,?,?)", orders)
    lines = [(j + 1, o[0], f"SKU-{j % 40:03d}", (j % 5) + 1, 300 + j)
             for j, o in enumerate(orders)]
    c.executemany("insert into order_line values(?,?,?,?,?)", lines)
    tix = [(t + 1, accs[t % len(accs)][0], f"Issue about order {t}",
            ["low", "normal", "high"][t % 3],
            "2026-0%d-1%d 10:00:00" % (t % 8 + 1, t % 9), None if t % 3 else
            "2026-0%d-2%d 10:00:00" % (t % 8 + 1, t % 9)) for t in range(90)]
    c.executemany("insert into support_ticket values(?,?,?,?,?,?)", tix)
    c.commit(); c.close()
    return len(accs), len(orders), len(lines), len(tix)


GENERIC = ("text", "number", "small_int")     # 没认出语义,只能造随机值


def report(facts, plan):
    """认出率:每一列到底被认成了什么。**这是给用户看的「我读懂了多少」。**"""
    kinds = collections.Counter()
    unknown = []
    for tn, tp in plan["tables"].items():
        for cn, g in tp["columns"].items():
            k = g["gen"]
            kinds[k] += 1
            if k in GENERIC:
                unknown.append(f"{tn}.{cn}")
    total = sum(kinds.values())
    known = total - sum(kinds[k] for k in GENERIC)
    return {"列数": total, "认出语义": known, "只能造随机值": total - known,
            "认出率": round(known / max(total, 1), 3),
            "分布": dict(kinds.most_common()), "没认出的": unknown}


def main():
    tmp = os.path.join(tempfile.mkdtemp(), "generalize_test.db")
    na, no, nl, nt = build_db(tmp)
    print(f"靶子:account {na} / purchase_order {no} / order_line {nl} / support_ticket {nt}")
    conn = S.connect(tmp)
    sc = conn.reflect()
    decl = sum(len(t.declared_fks) for t in sc.tables.values())
    print(f"\n【反射】{len(sc.tables)} 张表 · **明写外键 {decl} 个**"
          f"(澜绣云裳那边是 0 —— 这条路以前从没被走过)")
    facts = D.discover(conn, sc)
    fks = [(t, k) for t, tf in facts["tables"].items() for k in tf["fks"]]
    print(f"【推断】外键 {len(fks)} 条,来源:"
          f"{dict(collections.Counter(k['source'] for _t, k in fks))}")

    pl = P.build(facts, scale=1.0)
    rep = report(facts, pl)
    print(f"\n【认出率】{rep['认出语义']}/{rep['列数']} = {rep['认出率']:.0%}")
    print(f"  分布: {rep['分布']}")
    print(f"  没认出(只能造随机值): {rep['没认出的']}")

    made, man = G.generate(pl, conn)
    before = L.run_assertions(conn, pl)
    L.load(conn, pl, made, dry=False, log=lambda *a: None)
    L.fill_deferred(conn, pl, made, dry=False, log=lambda *a: None)
    conn.commit()
    worse, pre, _s = L.compare(before, L.run_assertions(conn, pl), pl)
    seq = [(t, o) for t, tp in pl["tables"].items() for o in (tp.get("时间序") or [])]
    print(f"\n【时间序】从源库统计出 {len(seq)} 条先后约束(不是写死的列名表)")
    for t, o in seq[:6]: print(f"    {t}: {o['先']} ≤ {o['后']}  (源库 {o['样本']} 行无一倒挂)")
    print(f"\n【灌入】{sum(len(v) for v in made.values())} 行 · 断言 {len(pl['assertions'])} 条"
          f" · 本来就脏 {len(pre)} · **我弄脏的 {len(worse)}**")
    for k, b, a, _n in worse[:8]: print(f"    ✗ {k}: {b} → {a}")

    print("\n【抽样看看像不像】")
    for r in made["purchase_order"][:4]:
        print("   ", {k: r.get(k) for k in
                      ("order_no", "amount_cents", "status", "created_at",
                       "placed_at", "shipped_at")})
    for r in made["account"][:2]:
        print("   ", {k: r.get(k) for k in ("email", "display_name", "signup_date", "country_code")})
    return 0 if not worse else 1


if __name__ == "__main__":
    sys.exit(main())
