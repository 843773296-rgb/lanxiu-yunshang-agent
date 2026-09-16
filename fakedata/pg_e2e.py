#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PostgreSQL 端到端真跑 —— **不进 check.sh**,因为要人手起一个实例。

和 `mysql_e2e.py` 是同一件事的另一种方言:把 SQLite 靶子库镜像过去,
然后整条链走一遍(反射 → 挖关系 → 出方案 → 灌 → 自检 → 回滚)。

## 为什么非要真跑一次

加方言的诱惑是「代码看着对就行」。而这个工具的每一次方言 bug 都是**真跑才炸的**:

    MySQL 那次:`params or None` —— 空元组会让驱动对 SQL 做一次 % 格式化,
               于是任何含 `%` 的 SQL(比如 `like 'SYN-%'`)当场炸。
               而自动派生的断言里不含 %,**离线自测一辈子碰不到**。

**没跑过就是没跑过。** 所以这份脚本的存在本身就是那句「实跑验证过」的依据。

    createdb fakedata_test
    python3 fakedata/pg_e2e.py postgres:///fakedata_test
"""
import os, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import schema as S, discover as D, plan as P, gen as G, guard, load as L

TABLES = ["shop", "staff", "customer", "product", "sku", "ordr", "ordr_item"]


def _lit(s):
    """PG 字面量:单引号翻倍。

    ⚠️ **`COMMENT ON` 不支持参数绑定。** 它是 PG 的工具命令(utility statement),
    占位符会被原样当成语法错:`... is $1` → syntax error at or near "$1"。
    所以注释只能内联进 SQL,自己转义。

    这个洞**离线自测一辈子碰不到** —— 和 MySQL 那次一模一样:
    那次是空元组触发驱动对 SQL 做 % 格式化,于是含 % 的 SQL 当场炸。
    **每种方言的坑都是真跑才炸的**,这就是 e2e 脚本存在的理由。
    """
    return "'" + str(s).replace("'", "''") + "'"


def _pg_type(col_type, is_pk):
    """SQLite 类型 → PG 类型。

    比 MySQL 那边简单一件事:**PG 的 text 能直接做主键**,不用退回 varchar(n)。
    (MySQL 不给 TEXT 建索引,所以那边主键必须转成 varchar。)
    """
    t = (col_type or "TEXT").upper()
    if "INT" in t:
        return "bigint"
    if any(k in t for k in ("REAL", "FLOA", "DOUB", "NUMERIC", "DEC")):
        return "double precision"
    return "text"


def mirror(src_path, pg, tables, log=print):
    """把 SQLite 的结构和数据搬进 PG。**注释要带过去** ——
    不然 PG 那条读 `pg_description` 的路径一行都没被跑到,
    等于把「元信息里最值钱的那部分」留在未验证状态。"""
    sc_conn = sqlite3.connect(src_path)
    ddl = {t: (r[0] or "") for t, r in
           ((t, sc_conn.execute("select sql from sqlite_master where name=?", (t,)).fetchone()
             or ("",)) for t in tables)}
    made = []
    for t in tables:
        info = list(sc_conn.execute(f'PRAGMA table_info("{t}")'))
        if not info:
            log(f"  跳过 {t}(源库没有)")
            continue
        uniq = set()
        for _s, idx, u, *_r in sc_conn.execute(f'PRAGMA index_list("{t}")'):
            if u:
                cs = [r[2] for r in sc_conn.execute(f'PRAGMA index_info("{idx}")')]
                if len(cs) == 1:
                    uniq.add(cs[0])
        cols, pk, 注释 = [], [r[1] for r in info if r[5]], []
        for _cid, name, ctype, notnull, _d, ispk in info:
            cols.append(f'"{name}" {_pg_type(ctype, bool(ispk))}'
                        + (" not null" if notnull and not ispk else ""))
            cmt = S._sqlite_comments(ddl.get(t, "")).get(name, "")
            if cmt:
                注释.append((name, cmt))
        if pk:
            cols.append("primary key (" + ", ".join(f'"{c}"' for c in pk) + ")")
        for u in uniq:
            if u not in pk:
                cols.append(f'unique ("{u}")')
        pg.exec(f'drop table if exists "{t}" cascade')
        pg.exec(f'create table "{t}" (' + ", ".join(cols) + ")")
        for name, cmt in 注释:
            pg.exec(f'comment on column "{t}"."{name}" is {_lit(cmt[:255])}')
        names = [r[1] for r in info]
        rows = list(sc_conn.execute(
            "select " + ", ".join(f'"{n}"' for n in names) + f' from "{t}"'))
        if rows:
            sql = (f'insert into "{t}" (' + ", ".join(f'"{n}"' for n in names) +
                   ") values (" + ", ".join(["%s"] * len(names)) + ")")
            for i in range(0, len(rows), 500):
                pg.many(sql, rows[i:i + 500])
        pg.commit()
        made.append(t)
        log(f"  {t}: {len(rows)} 行 / {len(names)} 列" + (f" / {len(注释)} 条注释" if 注释 else ""))
    sc_conn.close()
    return made


def main():
    if len(sys.argv) < 2:
        raise SystemExit("用法: python3 fakedata/pg_e2e.py postgres:///fakedata_test")
    dsn = sys.argv[1]
    print(guard.check_target(dsn, "test", write=True))
    src = os.path.join(ROOT, "backend", "lanxiu.db")
    if not os.path.exists(src):
        raise SystemExit(f"源库不在:{src}(先跑 backend/seed.py)")

    pg = S.connect(dsn)
    print(f"\n【镜像】{os.path.basename(src)} → {pg.label}")
    tables = mirror(src, pg, TABLES)

    print("\n【反射】")
    sc = pg.reflect()
    有注释 = sum(1 for t in sc.tables.values() for c in t.columns if c.comment)
    明写外键 = sum(len(t.declared_fks) for t in sc.tables.values())
    print(f"  {len(sc.tables)} 张表 / {sum(len(t.columns) for t in sc.tables.values())} 列 / "
          f"{有注释} 条注释 / {明写外键} 个明写外键")
    if not 有注释:
        raise SystemExit("❌ 一条注释都没读到 —— 那条 pg_description 的路径等于没验过")

    print("\n【挖关系】")
    t0 = time.time()
    facts = D.discover(pg, sc, tables)
    nfk = sum(len(tf["fks"]) for tf in facts["tables"].values())
    print(f"  挖出 {nfk} 条关系({time.time() - t0:.1f}s)")

    print("\n【出方案 → 灌 → 自检 → 回滚】")
    pl = P.build(facts, scale=0.1, tables=tables)
    before = L.run_assertions(pg, pl)
    made, man = G.generate(pl, pg)
    n, _s = L.load(pg, pl, made, dry=False, log=lambda *x: None)
    L.fill_deferred(pg, pl, made, dry=False, log=lambda *x: None)
    pg.commit()
    after = L.run_assertions(pg, pl)
    worse, pre, _sk = L.compare(before, after, pl)
    print(f"  灌入 {n} 行 · 断言 {len(pl['assertions'])} 条 · "
          f"本来就脏 {len(pre)} · **我弄脏的 {len(worse)}**")
    for k, b, a, note in worse[:5]:
        print(f"    ✗ {k}: {b} → {a}" + (f"  [{note}]" if note else ""))

    doc = {"顺序": pl["order"],
           "表": {t: {"pk": m["pk"], "主键": m["values"]} for t, m in man.items()}}
    删 = L.rollback(pg, doc, dry=False, log=lambda *x: None)
    pg.commit()
    back = L.run_assertions(pg, pl)
    净 = all(back.get(k) == before.get(k) for k in before)
    print(f"  回滚删掉 {删} 行 · 断言逐条回到基线:{'✅' if 净 else '❌'}")

    ok = (not worse) and 净 and 有注释 and n > 0
    print(f"\n{'✅ PostgreSQL 端到端跑通' if ok else '❌ 有没过的环节,看上面'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
