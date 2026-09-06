#!/usr/bin/env python3
"""假数据工厂 · 自测。接进 check.sh。

## 为什么要自己造一个「已知真相」的小库

拿 lanxiu.db 测推断层有个根本问题:**没人知道正确答案是什么。**
挖出 59 条关系,对了几条?不知道 —— 库里一条外键都没明写。
在没有真相的数据上测,只能测「没崩」,测不出「对不对」。

所以这里先手搭一个小库,**关系是我埋进去的,所以我知道全部答案**:
  · 该挖出来的:`ordr.cust_id → cust.id`(有命名线索)、`item.ordr → ordr.id`(无 _id 后缀)
  · **不该**挖出来的:`item.qty` —— 小整数,值域天然落在任何自增主键里,是经典误报
这样召回和误报两头都量得出来。

## 咬合:每一条检查都要能红

「没红过的检查等于没有」。改坏 → 确认变红 → 改回来。
本文件里的断言全部是双向的:该找到的没找到要红,不该找到的找到了也要红。
"""
import os, sys, shutil, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import schema as S, discover as D, plan as P, gen as G, guard, load as L

FAIL = []
def ck(cond, name, detail=""):
    if cond: print(f"  ✓ {name}")
    else:    print(f"  ✗ {name}  {detail}"); FAIL.append(name)


def build_known_db(path):
    """手搭一个已知真相的小库。**一条外键都不明写** —— 复现真实业务库的样子。"""
    c = sqlite3.connect(path)
    c.executescript("""
    create table cust(id text primary key, name text, city text, created text, phone text unique);
    create table ordr(id text primary key, cust_id text, amount real, status text, created text);
    create table item(id integer primary key, ordr text, sku text, qty int);
    create table note(body text);                       -- 没有主键:该被跳过
    """)
    custs = [(f"C{i:04d}", f"客{i}", "杭州", "2024-01-%02d" % (i % 28 + 1), f"1380000{i:04d}")
             for i in range(60)]
    c.executemany("insert into cust values(?,?,?,?,?)", custs)
    # 引用形状故意做成长尾:一半客户零订单,少数客户很多单
    ordrs, k = [], 0
    for i, (cid, *_r) in enumerate(custs):
        n = 0 if i % 2 == 0 else (1 if i % 3 else 12)
        for _ in range(n):
            k += 1
            ordrs.append((f"O{k:05d}", cid, 100.0 + k, "已完成" if k % 3 else "待付款",
                          "2024-06-%02d" % (k % 28 + 1)))
    c.executemany("insert into ordr values(?,?,?,?,?)", ordrs)
    items = [(None, o[0], f"SKU{j%7}", (j % 5) + 1)
             for j, o in enumerate(ordrs) for _ in (0,)]
    c.executemany("insert into item values(?,?,?,?)", items)
    c.commit(); c.close()
    return len(custs), len(ordrs), len(items)


def main():
    tmpd = tempfile.mkdtemp()
    known = os.path.join(tmpd, "known_test.db")
    nc, no, ni = build_known_db(known)
    conn = S.connect(known); sc = conn.reflect()
    facts = D.discover(conn, sc)
    fks = {(t, k["column"]): k for t, tf in facts["tables"].items() for k in tf["fks"]}

    print("【推断层 · 在已知真相的库上】")
    ck(sum(len(t.declared_fks) for t in sc.tables.values()) == 0,
       "靶子库确实一条外键都没明写(不然这个测试没意义)")
    ck(("ordr", "cust_id") in fks and fks[("ordr", "cust_id")]["table"] == "cust",
       "挖出 ordr.cust_id → cust(有命名线索)")
    ck(("item", "ordr") in fks and fks[("item", "ordr")]["table"] == "ordr",
       "挖出 item.ordr → ordr(**列名里没有 _id**,只认后缀的做法会全漏)")
    ck(("item", "qty") not in fks,
       "不把 item.qty 当外键(小整数落在自增主键值域里,是经典误报)",
       f'误判成了 {fks.get(("item","qty"),{}).get("table")}')
    ck(("cust", "created") not in fks and
       facts["tables"]["cust"]["columns"]["created"].get("semantic") == "date",
       "日期列认成日期,不被枚举判定抢走")
    sh = fks[("ordr", "cust_id")].get("shape") or {}
    ck(sh.get("0", 0) > 0.4, "量出「一半客户零订单」这个形状", f"实测 0 桶 ={sh.get('0')}")

    print("\n【方案层】")
    pl = P.build(facts, scale=1.0)
    ck(pl["tables"]["note"].get("skip"), "没有主键的表被跳过(灌得进去但删不掉)")
    o = pl["order"]
    bad = [(t, cn) for t, tp in pl["tables"].items() for cn, g in tp["columns"].items()
           if g["gen"] == "fk" and not g.get("deferred") and g["table"] in o
           and g["table"] != t and o.index(g["table"]) > o.index(t)]
    ck(not bad, "拓扑顺序:非两阶段的外键,父表一定排在子表前面", str(bad[:3]))
    ck(any(a["类"] == "孤儿" for a in pl["assertions"]), "派生了孤儿引用断言")
    ck(any(a["类"] == "枚举" for a in pl["assertions"]), "派生了枚举取值断言")

    print("\n【生成器】")
    a1, _m = G.generate(pl, conn); a2, _m2 = G.generate(pl, conn)
    ck(all(a1[t] == a2[t] for t in a1), "同种子两次生成完全一致(bug 才复现得了)")
    pl2 = P.build(facts, seed=pl["seed"] + 1, scale=1.0)
    b1, _ = G.generate(pl2, conn)
    ck(a1["cust"] != b1["cust"], "换种子必须换数据(否则种子是摆设)")
    # 种子隔离:方案里去掉一张表,其余表的数据不该跟着变
    sub = P.build(facts, scale=1.0, tables=["cust", "ordr"])
    c1, _ = G.generate(sub, conn)
    ck([r["name"] for r in c1["cust"]] == [r["name"] for r in a1["cust"]],
       "增删表不影响其它表的数据(每列单独播种,不是全局 rng)")
    leak = sum(1 for t, tp in pl["tables"].items() for cn, g in tp["columns"].items()
               if g["gen"] == "fk" and not g.get("deferred") and g["table"] in a1
               for r in a1[t] if r.get(cn) is not None
               and r[cn] not in {x.get(g["column"]) for x in a1[g["table"]]})
    ck(leak == 0, "外键值全部指向本次生成的数据,不悄悄挂到库里已有的行上", f"漏 {leak}")
    texts = [r["name"] for r in a1["cust"]]
    ck(any(len(t) > 40 or "🧵" in t or t != t.strip() for t in texts),
       "文本列掺进了边界值(超长/emoji/前后空格)——正常路径谁都测得到,炸的是这些")

    print("\n【安全闸门】")
    for tgt, env, should in [("shop.db", "生产", False), ("shop.db", "", False),
                             ("mysql://u@h/shop_prod", "dev", False),
                             ("mysql://u@h/proddb", "dev", False),
                             ("/data/线上/a.db", "dev", False),
                             ("mysql://u@h/delivery_dev", "dev", True),
                             ("backend/lanxiu.db", "test", True)]:
        try: guard.check_target(tgt, env); got = True
        except guard.Refused: got = False
        ck(got == should, f"闸门 {tgt!r}/{env!r} → {'放行' if should else '拒绝'}")

    print("\n【端到端 · 灌入/自检/回滚(临时副本,不碰本体)】")
    src = os.path.join(ROOT, "backend", "lanxiu.db")
    if os.path.exists(src):
        cp = os.path.join(tmpd, "e2e_test.db"); shutil.copy(src, cp)
        cn2 = S.connect(cp)
        f2 = D.discover(cn2, cn2.reflect())
        p2 = P.build(f2, scale=0.05)
        made, man = G.generate(p2, cn2)
        before = L.run_assertions(cn2, p2)
        n, _s = L.load(cn2, p2, made, dry=False, log=lambda *x: None)
        L.fill_deferred(cn2, p2, made, dry=False, log=lambda *x: None)
        cn2.commit()
        worse, pre, _sk = L.compare(before, L.run_assertions(cn2, p2), p2)
        ck(n > 0, f"灌进去了 {n} 行")
        ck(not worse, "自己造的数据没弄脏任何一条断言",
           "; ".join(f"{k}:{b}→{a}" for k, b, a, _n in worse[:4]))
        doc = {"顺序": p2["order"],
               "表": {t: {"pk": m["pk"], "主键": m["values"]} for t, m in man.items()}}
        L.rollback(cn2, doc, dry=False, log=lambda *x: None); cn2.commit()
        back = L.run_assertions(cn2, p2)
        ck(all(back.get(k) == before.get(k) for k in before),
           "照 manifest 回滚后,断言逐条回到基线(清得干净)")
    else:
        print("  (跳过:backend/lanxiu.db 不在)")

    print(f"\n假数据工厂自测:{'全部通过' if not FAIL else str(len(FAIL)) + ' 项失败'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
