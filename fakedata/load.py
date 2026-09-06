#!/usr/bin/env python3
"""灌入 · 自检 · 回滚。

## 两阶段灌入

拓扑排序解决「先有父亲才有孩子」,但环解决不了:账户指向本人着装人,着装人又指向账户。
所以环上那条边先留空插进去,全部插完再 UPDATE 回填。

第一阶段插的是「不完整但合法」的行 —— 前提是那一列**可空**。
断边时优先挑可空的边,原因就在这:不可空的边只能先造个临时值,那是真脏。

## 自检为什么要跑两遍

断言是对**整张表**查的,而测试库里通常已经有别人的数据。
灌完直接跑断言,查出 3 条孤儿引用 —— 是你造的,还是本来就有的?分不清。

所以灌之前先跑一遍存下**基线**,灌完再跑一遍,**只报变差的那些**。
这样「本来就脏」和「我弄脏的」彻底分开。
没有基线的检查会在老库上一片红,红到没人看 —— 那和没有检查是一回事。

## 回滚照 manifest 删

不按前缀模糊匹配、不按时间戳猜。删数据这件事上,「大概是这些」不成立。
删的顺序是灌入顺序**倒过来** —— 先删孩子再删父亲,不然孤儿引用是你自己造的。
"""
import os, sys, json

BATCH = 500

def _insert_sql(conn, tname, cols):
    ph = ", ".join([conn.ph] * len(cols))
    return (f'insert into {conn.ident(tname)} '
            f'({", ".join(conn.ident(c) for c in cols)}) values ({ph})')

def load(conn, plan, made, dry=True, log=print):
    """第一阶段:按拓扑顺序插行,成环的外键列留空。返回 (插入行数, 用到的 SQL 样例)。"""
    total, sample = 0, None
    for tname in plan["order"]:
        tp = plan["tables"][tname]
        rows = made.get(tname) or []
        if not rows or tp.get("skip"): continue
        cols = [c for c in tp["columns"] if c in rows[0]]
        sql = _insert_sql(conn, tname, cols)
        if sample is None: sample = (sql, [rows[0][c] for c in cols])
        if dry:
            total += len(rows); continue
        buf = []
        for r in rows:
            buf.append(tuple(r.get(c) for c in cols))
            if len(buf) >= BATCH:
                conn.many(sql, buf); buf = []
        if buf: conn.many(sql, buf)
        total += len(rows)
        log(f"  {tname}: +{len(rows)}")
    return total, sample


def fill_deferred(conn, plan, made, dry=True, log=print):
    """第二阶段:回填成环时留空的外键列。"""
    import gen as G
    n = 0
    for d in plan["deferred_fks"]:
        t, c = d["table"], d["column"]
        g = plan["tables"][t]["columns"][c]
        parent, pcol = g["table"], g["column"]
        pv = [x.get(pcol) for x in (made.get(parent) or []) if x.get(pcol) is not None]
        rows = made.get(t) or []
        if not pv or not rows: continue
        r = G.rng_for(plan["seed"], t, c, "回填")
        pool = G._fk_pool(g.get("shape"), pv, len(rows), r)
        pk = plan["tables"][t]["pk"][0]
        if not dry:
            sql = (f'update {conn.ident(t)} set {conn.ident(c)}={conn.ph} '
                   f'where {conn.ident(pk)}={conn.ph}')
            conn.many(sql, [(pool[i], rows[i][pk]) for i in range(len(rows))])
        n += len(rows)
        log(f"  回填 {t}.{c} → {parent}.{pcol}: {len(rows)} 行")
    return n


def run_assertions(conn, plan):
    """跑一遍断言。返回 {断言名: 查出来几行}。跑不动的记成 None(表不存在等)。"""
    res = {}
    for a in plan["assertions"]:
        try:
            res[a["名"]] = conn.q(a["sql"])[0][0]
        except Exception as e:
            res[a["名"]] = None
    return res


def compare(before, after, plan):
    """只报**变差**的。绝对值一片红没有信息量,增量才有。"""
    worse, preexisting, skipped = [], [], []
    idx = {a["名"]: a for a in plan["assertions"]}
    for k, v in after.items():
        b = before.get(k)
        if v is None: skipped.append(k); continue
        if b is None: b = 0
        if v > b:     worse.append((k, b, v, idx[k].get("需确认")))
        elif v > 0:   preexisting.append((k, v))
    return worse, preexisting, skipped


def rollback(conn, doc, dry=True, log=print):
    """照 manifest 删。顺序倒过来:先孩子后父亲。"""
    n = 0
    for tname in reversed(doc["顺序"]):
        m = doc["表"].get(tname)
        if not m or not m["主键"]: continue
        pk, vals = m["pk"], m["主键"]
        for i in range(0, len(vals), BATCH):
            chunk = vals[i:i + BATCH]
            ph = ", ".join([conn.ph] * len(chunk))
            sql = f'delete from {conn.ident(tname)} where {conn.ident(pk)} in ({ph})'
            if not dry: conn.exec(sql, tuple(chunk))
        n += len(vals)
        log(f"  {tname}: -{len(vals)}")
    return n


if __name__ == "__main__":
    # 端到端自测跑在临时副本上,绝不碰 backend/lanxiu.db 本体
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import shutil, tempfile, schema as S, discover as D, plan as P, gen as G
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, "backend", "lanxiu.db")
    tmp = os.path.join(tempfile.mkdtemp(), "test_copy.db")
    shutil.copy(src, tmp)
    conn = S.connect(tmp)
    f = D.discover(conn, conn.reflect())
    pl = P.build(f, scale=0.05)
    made, man = G.generate(pl, conn)

    before = run_assertions(conn, pl)
    n, _s = load(conn, pl, made, dry=False, log=lambda *a: None)
    fill_deferred(conn, pl, made, dry=False, log=lambda *a: None)
    conn.commit()
    after = run_assertions(conn, pl)
    worse, pre, skip = compare(before, after, pl)
    print(f"灌入 {n} 行 / 断言 {len(pl['assertions'])} 条")
    print(f"  本来就脏: {len(pre)} 条    我弄脏的: {len(worse)} 条")
    for k, b, a_, note in worse[:12]:
        print(f"    ✗ {k}: {b} → {a_}" + (f"  [{note}]" if note else ""))

    doc = {"顺序": pl["order"], "表": {t: {"pk": m["pk"], "主键": m["values"]}
                                       for t, m in man.items()}}
    removed = rollback(conn, doc, dry=False, log=lambda *a: None)
    conn.commit()
    back = run_assertions(conn, pl)
    clean = all(back.get(k) == before.get(k) for k in before)
    print(f"回滚 {removed} 行 → 断言回到基线: {'✅' if clean else '❌'}")
