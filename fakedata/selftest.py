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
    create table ordr(id text primary key, cust_id text, amount real, status text,
                      created text, paid_at text, shipped_at text, cancelled_at text,
                      prd_status text);
    create table item(id integer primary key, ordr text, sku text, qty int);
    create table note(body text);                       -- 没有主键:该被跳过
    """)
    custs = [(f"C{i:04d}", f"客{i}", "杭州", "2024-01-%02d" % (i % 28 + 1), f"1380000{i:04d}")
             for i in range(60)]
    c.executemany("insert into cust values(?,?,?,?,?)", custs)
    # 引用形状故意做成长尾:一半客户零订单,少数客户很多单
    ordrs, k = [], 0
    ST = ["待付款", "已付款", "已发货", "已完成", "已取消"]
    for i, (cid, *_r) in enumerate(custs):
        n = 0 if i % 2 == 0 else (1 if i % 3 else 12)
        for _ in range(n):
            k += 1
            st = ST[k % len(ST)]
            cr = "2024-06-%02d" % (k % 28 + 1)
            ordrs.append((f"O{k:05d}", cid, 100.0 + k, st, cr,
                          cr if st in ("已付款", "已发货", "已完成") else None,
                          cr if st in ("已发货", "已完成") else None,
                          cr if st == "已取消" else None,
                          # **故意种一个跨列依赖**:只有发出去的订单才可能「已生产」。
                          # 于是「待付款 × 已生产」在源数据里一次都不出现 ——
                          # 这就是禁配检测该抓到的东西,而独立抽样必然会造出它。
                          "已生产" if st in ("已发货", "已完成") else "待生产"))
    c.executemany("insert into ordr values(?,?,?,?,?,?,?,?,?)", ordrs)
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
    kinds = {n for n, v in G.EDGE_TEXT if v in texts}
    ck(len(kinds) >= 5,
       f"边界值按种类铺开,不是靠概率赌(命中 {len(kinds)}/{len(G.EDGE_TEXT)} 种)",
       f"只出现了 {kinds}")
    ck(sum(1 for t in texts if t in [v for _n, v in G.EDGE_TEXT]) <= len(texts) // 3,
       "边界值不能喧宾夺主(占比不超过三分之一)")

    print("\n【列与列之间 · 跨状态机一致性】")
    jt = facts["tables"]["ordr"].get("joint")
    ck(bool(jt) and {"status", "prd_status"} <= set(jt[0]["columns"]),
       "status 和 prd_status 被认成相关列,一起进联合分布",
       str(jt[0]["columns"]) if jt else "没识别出联合分布")
    cand = {(p["a值"], p["b值"]) for p in (jt[0]["禁配候选"] if jt else [])}
    ck(("待付款", "已生产") in cand or ("已生产", "待付款") in cand,
       "抓到「待付款 × 已生产」这个从没出现过的组合", str(sorted(cand))[:120])
    pj = P.build(facts, scale=1.0)
    mj, _mm = G.generate(pj, conn)
    srcpairs = {tuple(r) for r in conn.q("select status, prd_status from ordr")}
    novel = {(r["status"], r["prd_status"]) for r in mj["ordr"]} - srcpairs
    ck(not novel, "造出来的组合全都在源库出现过(联合抽样,不是逐列独立抽)",
       f"造出了源库没有的组合 {sorted(novel)[:3]}")
    ck(not any(r["status"] == "待付款" and r["prd_status"] == "已生产" for r in mj["ordr"]),
       "一条「待付款却已生产」都没造出来")

    print("\n【模型层 · 全部离线,一次模型都不调】")
    import infer_llm as I
    FSM = {"table": "ordr", "column": "status", "start": ["待付款"],
           "transitions": [["待付款", "已付款"], ["待付款", "已取消"], ["已付款", "已发货"],
                           ["已付款", "已取消"], ["已发货", "已完成"]],
           "terminal": ["已完成", "已取消"],
           "timestamps": {"已付款": "paid_at", "已发货": "shipped_at", "已取消": "cancelled_at"},
           "reason": "夹具"}
    ck(sorted(P.dominators(["待付款"], FSM["transitions"], "已取消")) == ["已取消", "待付款"],
       "支配点:「已取消」不要求有付款时间(可以从待付款直接取消)",
       "用可达性算会错误地要求它有 paid_at")
    ck("已付款" in P.dominators(["待付款"], FSM["transitions"], "已完成"),
       "支配点:「已完成」必须经过已付款")

    raw = {"relations": [
              {"table": "ordr", "column": "cust_id", "verdict": "confirm", "reason": "x"},
              {"table": "没这张表", "column": "a", "verdict": "reject", "reason": "x"},
              {"table": "ordr", "column": "cust_id", "verdict": "乱写", "reason": "x"}],
           "columns": [
              {"table": "cust", "column": "city", "semantic": "city", "reason": "x"},
              {"table": "cust", "column": "city", "semantic": "身份证号", "reason": "x"}],
           "forbidden": [
              {"table": "ordr", "a_column": "status", "a_value": "待付款",
               "b_column": "prd_status", "b_value": "已生产",
               "verdict": "real", "reason": "没付款不可能已生产"},
              {"table": "ordr", "a_column": "status", "a_value": "根本没这个状态",
               "b_column": "prd_status", "b_value": "已生产",
               "verdict": "real", "reason": "对不存在的取值下禁令"},
              {"table": "ordr", "a_column": "status", "a_value": "已付款",
               "b_column": "prd_status", "b_value": "待生产",
               "verdict": "乱写", "reason": "x"}],
           "state_machines": [
              dict(FSM),
              dict(FSM, column="status", timestamps={"已付款": "paid_at", "已发货": "paid_at"}),
              dict(FSM, timestamps={"待付款": "created", "已付款": "paid_at"}),
              dict(FSM, transitions=FSM["transitions"] + [["已完成", "已退款"]]),
              # 第二个状态机,来抢 ordr.shipped_at —— 同表同列只能有一个主人
              {"table": "ordr", "column": "prd_status", "start": ["待生产"],
               "transitions": [["待生产", "已生产"]], "terminal": ["已生产"],
               "timestamps": {"已生产": "shipped_at"}, "reason": "夹具"}]}
    good, drop = I.validate(raw, facts, P.build(facts, scale=1.0))
    txt = " | ".join(drop)
    ck(len(good["relations"]) == 1, "编出来的表名被丢掉", str(good["relations"]))
    ck(all(r["verdict"] in ("confirm", "reject", "retarget") for r in good["relations"]),
       "不认识的 verdict 被丢掉")
    ck(len(good["columns"]) == 1 and good["columns"][0]["semantic"] == "city",
       "生成器不认识的语义被丢掉(模型可以随便编一个词)")
    ck("库里没有的状态" in txt, "编出来的状态值被丢掉(它会当场违反枚举断言)", txt[:120])
    ck("被多个状态共用" in txt, "一个时间戳列被两个状态共用 → 整列剔除(否则断言自相矛盾)", txt[:120])
    ck("诞生时刻" in txt, "created 被当成状态时间戳 → 剔除(它是锚点,不是某个状态的产物)", txt[:120])
    ck(any("一列只能有一个主人" in d for d in drop),
       "跨状态机抢同一列被挡下(不变量的作用域是「表」,不是「状态机」)", txt[:160])
    ck(not any(m["column"] == "prd_status" and m.get("timestamps")
               for m in good["state_machines"]),
       "被抢的那个状态机,时间戳映射已清空")
    for m in good["state_machines"]:
        ck("created" not in (m.get("timestamps") or {}).values(),
           "过完校验的状态机里不会再有 created 当状态戳")
        break

    ck(len(good["forbidden"]) == 1 and good["forbidden"][0]["a_value"] == "待付款",
       "禁配:对**库里不存在的取值**下禁令要被丢掉(那是一条永远为真的检查)",
       str([f.get("a_value") for f in good["forbidden"]]))
    ck("永远为真" in txt, "而且要说明白为什么丢", txt[:120])

    f4 = D.discover(conn, sc)
    f4, _lg = P.apply_overlay(f4, {"relations": [], "columns": [], "state_machines": [],
                                   "forbidden": [good["forbidden"][0]]})
    p4 = P.build(f4, scale=1.0)
    fb = [a for a in p4["assertions"] if a["类"] == "禁配"]
    ck(len(fb) == 1, f"确认过的禁配变成断言({len(fb)} 条)")
    ck(conn.q(fb[0]["sql"])[0][0] == 0, "这条断言在源数据上是 0(它本来就是这么推出来的)")

    print("\n【状态机落到数据上】")
    f2 = D.discover(conn, sc)
    f2, applied = P.apply_overlay(f2, {"relations": [], "columns": [], "state_machines": [FSM]})
    ck(any("状态机" in x for x in applied), "overlay 盖到事实层")
    p3 = P.build(f2, scale=1.0)
    fas = [a for a in p3["assertions"] if a["类"] == "状态机"]
    ck(len(fas) >= 6, f"派生了状态机断言({len(fas)} 条)")
    m3, _man3 = G.generate(p3, conn)
    bad = []
    for row in m3["ordr"]:
        st = row["status"]
        must = P.dominators(FSM["start"], FSM["transitions"], st) & set(FSM["timestamps"])
        for stt, col in FSM["timestamps"].items():
            if stt in must and not row.get(col):   bad.append(f"{st} 缺 {col}")
            if stt not in must and row.get(col):   bad.append(f"{st} 多了 {col}")
    ck(not bad, "造出来的每一行:状态和时间戳都对得上(没有「已发货但没付款」)",
       "; ".join(sorted(set(bad))[:4]))
    ck(all(row.get("created") for row in m3["ordr"]),
       "每张订单都有下单时间(created 不会被状态机置空)")
    ck(all(not row.get(c) or str(row[c]) >= str(row["created"])
           for row in m3["ordr"] for c in ("paid_at", "shipped_at", "cancelled_at")),
       "所有 *_at 都不早于 created(全表统一的时间原点)")

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

    own = os.path.join(ROOT, "backend", "lanxiu.db")
    _spell = [own, "backend/lanxiu.db", "./backend/lanxiu.db",
              "backend/../backend/lanxiu.db", "sqlite://backend/lanxiu.db", "sqlite://" + own]
    _leak = []
    for _v in _spell:
        try: guard.check_target(_v, "test", write=True); _leak.append(_v)
        except guard.Refused: pass
    ck(not _leak, f"仓库自己的库禁止写入 —— **{len(_spell)} 种拼法全都拦住**"
                  "(它是四个数据检查的真值源)", f"放行了 {_leak}")
    try: guard.check_target(own, "test", write=False); ck(True, "但允许只读采样(出方案不写库)")
    except guard.Refused as e: ck(False, "只读采样不该被拦", str(e)[:80])

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
