#!/usr/bin/env python3
"""MySQL 实跑验证 —— 把「代码就位」变成「验证过」。

**不进 check.sh**:它要一个活的 MySQL,而 CI 上没有。这是人手动跑的那一类。

## 为什么要专门搭个靶子

假数据工厂的目标数据库是 MySQL,但仓库自己的库是 SQLite。
只在 SQLite 上跑通,方言层是没有被验证过的 —— 而方言层的 bug 有个共同特征:
**在你测的那种数据库上完全正常。**

所以这里把 lanxiu.db 的一部分表**结构 + 数据**搬进 MySQL,再跑完整条链。
搬的时候故意**不声明外键** —— 复现真实业务库的样子,也让推断层有活干。

## 挑这些表的理由

不是随便挑的,每张都覆盖一类东西:
  账户/客户/着装人 —— 文本主键、唯一手机号、**成环**(账户指本人着装人,着装人指账户)
  订单/订单项/售后 —— 长尾金额、状态枚举、多张表指向同一个父亲
  预约/定金       —— 日期与时间线
  分类           —— **自引用**(上级分类)
  量体项/量体记录 —— 整数主键、非 `_id` 后缀的关联(`measure_rec.item → measure_item.code`)
"""
import os, re, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import schema as S, discover as D, plan as P, gen as G, guard, load as L

TABLES = ["shop", "staff", "account", "customer", "wearer", "category",
          "product", "sku", "ordr", "ordr_item", "aftersale",
          "appointment", "deposit", "measure_item", "measure_rec"]

def _mysql_type(col_type, maxlen, is_pk, unique):
    t = (col_type or "TEXT").upper()
    if "INT" in t:  return "int"
    if any(k in t for k in ("REAL", "FLOA", "DOUB", "NUMERIC", "DEC")): return "double"
    # 主键和唯一键必须是有长度的类型 —— MySQL 不给 TEXT 建索引(除非指定前缀长度)
    if is_pk or unique: return "varchar(96)"
    if maxlen is None:  return "text"
    if maxlen <= 255:   return f"varchar({max(32, min(255, maxlen * 2))})"
    return "text"


def mirror(src_path, my, tables, log=print):
    """把 SQLite 的表结构和数据搬进 MySQL。**故意不建外键。**"""
    sc_conn = sqlite3.connect(src_path)
    made = []
    for t in tables:
        info = list(sc_conn.execute(f'PRAGMA table_info("{t}")'))
        if not info: log(f"  跳过 {t}(源库没有)"); continue
        uniq = set()
        for _s, idx, u, *_r in sc_conn.execute(f'PRAGMA index_list("{t}")'):
            if u:
                cs = [r[2] for r in sc_conn.execute(f'PRAGMA index_info("{idx}")')]
                if len(cs) == 1: uniq.add(cs[0])
        cols, pk = [], [r[1] for r in info if r[5]]
        for _cid, name, ctype, notnull, _d, ispk in info:
            try:
                ml = sc_conn.execute(
                    f'select max(length(cast("{name}" as text))) from "{t}"').fetchone()[0]
            except Exception: ml = None
            mt = _mysql_type(ctype, ml, bool(ispk), name in uniq)
            # NOT NULL 原样带过来 —— 断言层要靠它派生「不可为空」的检查
            cols.append(f'`{name}` {mt}' + (" not null" if notnull and not ispk else ""))
        if pk: cols.append("primary key (" + ", ".join(f"`{c}`" for c in pk) + ")")
        for u in uniq:
            if u not in pk: cols.append(f"unique key `uq_{t}_{u}` (`{u}`)")
        my.exec(f"drop table if exists `{t}`")
        my.exec(f"create table `{t}` (" + ", ".join(cols) +
                ") engine=InnoDB default charset=utf8mb4")
        names = [r[1] for r in info]
        rows = list(sc_conn.execute(
            "select " + ", ".join(f'"{n}"' for n in names) + f' from "{t}"'))
        if rows:
            sql = (f'insert into `{t}` (' + ", ".join(f"`{n}`" for n in names) +
                   ") values (" + ", ".join(["%s"] * len(names)) + ")")
            for i in range(0, len(rows), 500):
                my.many(sql, rows[i:i + 500])
        my.commit()
        made.append(t); log(f"  {t}: {len(rows)} 行 / {len(names)} 列")
    sc_conn.close()
    return made


def main():
    if len(sys.argv) < 2:
        raise SystemExit("用法: python3 fakedata/mysql_e2e.py mysql://user:pass@host:port/db")
    dsn = sys.argv[1]
    print("=" * 66)
    print(guard.check_target(dsn, "test", write=True))
    my = S.connect(dsn)

    print("\n【1/6 搭靶子】把 lanxiu.db 的一部分表搬进 MySQL(**故意不建外键**)")
    made = mirror(os.path.join(ROOT, "backend", "lanxiu.db"), my, TABLES)

    print("\n【2/6 反射】读 information_schema")
    sc = my.reflect()
    ndecl = sum(len(t.declared_fks) for t in sc.tables.values())
    ncomment = sum(1 for t in sc.tables.values() for c in t.columns if c.comment)
    print(f"  {len(sc.tables)} 张表 / {sum(len(t.columns) for t in sc.tables.values())} 列 / "
          f"明写外键 {ndecl} 个 / 带注释的列 {ncomment} 个")
    print(f"  行数样本(必须是真实 count(*),不是 InnoDB 的估算值):")
    for t in list(sc.tables)[:4]: print(f"    {t}: {sc.tables[t].rows}")

    print("\n【3/6 推断】")
    facts = D.discover(my, sc)
    fks = [(t, k) for t, tf in facts["tables"].items() for k in tf["fks"]]
    print(f"  明写 {ndecl} 个 → 挖出 {len(fks)} 条")
    for t, k in fks[:8]:
        print(f'    [{k["confidence"]}] {t}.{k["column"]} → {k["table"]}.{k["column_ref"]} '
              f'重叠{k["overlap"]:.0%}')

    print("\n【4/6 方案 + 生成】")
    pl = P.build(facts, scale=0.3)
    print(f'  灌入顺序 {len(pl["order"])} 张 / 环 {len(pl["deferred_fks"])} 条 / '
          f'断言 {len(pl["assertions"])} 条')
    print(f'  断言 SQL 用的是反引号(MySQL 不认双引号标识符):')
    print(f'    {pl["assertions"][0]["sql"][:110]}')
    made_rows, man = G.generate(pl, my)
    n = sum(len(v) for v in made_rows.values())
    print(f"  生成 {n} 行")

    print("\n【5/6 灌入 + 自检】")
    before = L.run_assertions(my, pl)
    skipped = [k for k, v in before.items() if v is None]
    if skipped:
        print(f"  ⚠️ {len(skipped)} 条断言在 MySQL 上跑不动:")
        for k in skipped[:5]: print(f"     {k}")
    L.load(my, pl, made_rows, dry=False, log=lambda *x: None)
    L.fill_deferred(my, pl, made_rows, dry=False, log=lambda *x: None)
    my.commit()
    worse, pre, _s = L.compare(before, L.run_assertions(my, pl), pl)
    print(f"  灌入 {n} 行 · 断言 {len(pl['assertions'])} 条")
    print(f"  本来就脏 {len(pre)} 条 · 我弄脏的 {len(worse)} 条 "
          + ("✅" if not worse else "❌"))
    for k, b, a, note in worse[:10]:
        print(f"    ✗ {k}: {b} → {a}" + (f"  [{note}]" if note else ""))

    print("\n【6/6 回滚】照 manifest 删")
    doc = {"顺序": pl["order"],
           "表": {t: {"pk": m["pk"], "主键": m["values"]} for t, m in man.items()}}
    removed = L.rollback(my, doc, dry=False, log=lambda *x: None)
    my.commit()
    back = L.run_assertions(my, pl)
    clean = all(back.get(k) == before.get(k) for k in before)
    print(f"  删除 {removed} 行 → 断言回到基线 {'✅' if clean else '❌'}")

    ok = (not worse) and clean and not skipped
    print("\n" + "=" * 66)
    print("MySQL 实跑:" + ("✅ 整条链通了" if ok else "❌ 有问题,见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
