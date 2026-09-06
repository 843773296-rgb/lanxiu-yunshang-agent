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

def _cap_like(v, n):
    """跟生成器一样按列长度截断,才好对得上 —— 超长边界值进 varchar(52) 就是 52 个字。"""
    return v[:n] if len(v) > n else v

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
    """把 SQLite 的表结构和数据搬进 MySQL。**故意不建外键**,但**注释要带过去** ——
    不然 MySQL 那条读 COLUMN_COMMENT 的路径一行都没被跑到,
    等于把「元信息里最值钱的那部分」留在了未验证状态。"""
    sc_conn = sqlite3.connect(src_path)
    ddl = {t: (r[0] or "") for t, r in
           ((t, sc_conn.execute("select sql from sqlite_master where name=?", (t,)).fetchone()
              or ("",)) for t in tables)}
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
            cmt = S._sqlite_comments(ddl.get(t, "")).get(name, "")
            # NOT NULL 原样带过来 —— 断言层要靠它派生「不可为空」的检查
            cols.append(f'`{name}` {mt}' + (" not null" if notnull and not ispk else "")
                        + (" comment '%s'" % cmt.replace("'", "''")[:255] if cmt else ""))
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
    if ncomment == 0:
        print("  ❌ 一个注释都没读到 —— COLUMN_COMMENT 这条路没被验证到")
    else:
        for t in sc.tables.values():
            for c in t.columns:
                if c.comment: print(f"    例:{t.name}.{c.name} → {c.comment[:60]}"); break
            else: continue
            break
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

    print("\n【6/7 取证】造出来的东西在真 MySQL 里长什么样")
    mode = my.q("select @@sql_mode")[0][0]
    strict = "STRICT" in mode
    print(f'  sql_mode 含 STRICT: {strict}  ← 不严格的话「超长被拒」这条根本没被考验')
    pre = pl["marker"]["prefix"]
    ev = []
    # 边界值有几种真的活着落进了 MySQL —— 严格模式 + varchar 长度 + 字符集,三关都过了才算
    names = [r[0] for r in my.q(
        f"select `name` from `customer` where `id` like '{pre}%' and `name` is not null")]
    # 列长必须从 information_schema 现查。第一版写死 52,而 `customer.name` 其实是
    # varchar(44) —— 超长边界值明明活着落库了(实测最长 44),却被判成「没出现」。
    # **测量口径和被测对象对不上,量出来的是测量误差,不是事实。**
    nlen = my.q("select character_maximum_length from information_schema.columns "
                "where table_schema=%s and table_name='customer' and column_name='name'",
                (my.db,))[0][0] or 255
    alive = {n for n, v in G.EDGE_TEXT if _cap_like(v, int(nlen)) in names}
    ev.append((f"边界值活着落库的种类(共 {len(G.EDGE_TEXT)} 种)",
               f"{len(alive)} 种 —— {'、'.join(sorted(alive))}"))
    # emoji 真的存进去了吗(utf8mb4 路径)
    r = my.q(f"select count(*) from `customer` where `id` like '{pre}%' "
             f"and `name` like '%\U0001F9F5%'")
    ev.append(("emoji 名字存活", r[0][0]))
    # 超长文本
    r = my.q(f"select max(char_length(`name`)) from `customer` where `id` like '{pre}%'")
    ev.append(("最长姓名字符数", r[0][0]))
    # 前后空格没被 MySQL 悄悄吃掉(varchar 存尾空格是会被比较忽略的经典坑)
    r = my.q(f"select count(*) from `customer` where `id` like '{pre}%' "
             f"and `name` <> trim(`name`)")
    ev.append(("带前后空格的姓名", r[0][0]))
    # 金额长尾:p50 和 max 差几倍
    r = my.q(f"select min(`amount`), avg(`amount`), max(`amount`) from `ordr` "
             f"where `id` like '{pre}%'")
    if r and r[0][0] is not None:
        lo, av, hi = r[0]
        ev.append(("订单金额 min / 均值 / max(长尾看 max÷均值)",
                   f"{lo:.0f} / {av:.0f} / {hi:.0f}  (max 是均值的 {hi/av:.1f} 倍)"))
    # 引用形状:多少客户零订单
    r = my.q(f"select sum(c=0), sum(c between 1 and 3), sum(c>10) from "
             f"(select cu.`id`, count(o.`id`) c from `customer` cu "
             f"left join `ordr` o on o.`customer_id`=cu.`id` "
             f"where cu.`id` like '{pre}%' group by cu.`id`) x")
    if r: ev.append(("客户订单数分布 0 / 1-3 / >10", " / ".join(str(v) for v in r[0])))
    for k, v in ev: print(f"    {k}: {v}")
    emoji_ok = ev[1][1] > 0
    # 时间线:方案自动派生的断言只查「不倒挂」,这里直接看一眼真实取值
    r = my.q(f"select count(*) from `ordr` where `id` like '{pre}%' "
             f"and `paid_at` is not null and `created` is not null and `paid_at` >= `created`")
    t = my.q(f"select count(*) from `ordr` where `id` like '{pre}%' "
             f"and `paid_at` is not null and `created` is not null")
    print(f"    付款时间不早于下单时间: {r[0][0]}/{t[0][0]}")

    print("\n【7/7 回滚】照 manifest 删")
    doc = {"顺序": pl["order"],
           "表": {t: {"pk": m["pk"], "主键": m["values"]} for t, m in man.items()}}
    removed = L.rollback(my, doc, dry=False, log=lambda *x: None)
    my.commit()
    back = L.run_assertions(my, pl)
    clean = all(back.get(k) == before.get(k) for k in before)
    print(f"  删除 {removed} 行 → 断言回到基线 {'✅' if clean else '❌'}")

    ok = (not worse) and clean and not skipped and strict and emoji_ok
    print("\n" + "=" * 66)
    print("MySQL 实跑:" + ("✅ 整条链通了" if ok else "❌ 有问题,见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
