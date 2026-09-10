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
import json, os, re, shutil, sqlite3, sys, tempfile

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
    create table cust(id text primary key, name text, city text, created text, phone text unique,
                      login text unique);
    create table ordr(id text primary key, cust_id text, amount real, status text,
                      created text, paid_at text, shipped_at text, cancelled_at text,
                      prd_status text);
    create table item(id integer primary key, ordr text, sku text, qty int);
    create table note(body text);                       -- 没有主键:该被跳过
    """)
    # `login` 的取值**恰好等于主键** —— 值重叠 100%,推断层会把它认成外键。
    # 而它在 schema 里明写着 UNIQUE。这正是真实撞车的形状:
    # 一个明写的约束,被一个推断出来的结论盖掉。
    custs = [(f"C{i:04d}", f"客{i}", "杭州", "2024-01-%02d" % (i % 28 + 1), f"1380000{i:04d}",
              f"C{i:04d}") for i in range(60)]
    c.executemany("insert into cust(id,name,city,created,phone,login) values(?,?,?,?,?,?)", custs)
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
    # **别写死用哪个池。** 池是跟着源库文字选的,检查写死中文池的话,
    # 靶子库的文字构成一变(我加了个 ASCII 列)这条就红,而工具一点毛病没有。
    # 检查要验的是「铺开了」,不是「铺的是中文那一套」。
    pool = G._EDGE_ZH if facts.get("中文库", True) else G._EDGE_EN
    kinds = {n for n, v in pool if v in texts}
    ck(len(kinds) >= 5,
       f"边界值按种类铺开,不是靠概率赌(命中 {len(kinds)}/{len(pool)} 种,"
       f"{'中文' if facts.get('中文库', True) else '西文'}池)",
       f"只出现了 {kinds}")
    ck(sum(1 for t in texts if t in [v for _n, v in pool]) <= len(texts) // 3,
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

    print("\n【schema 明写的约束,压过推断出来的结论】")
    gl = P.build(facts, scale=1.0, tables=["cust"])["tables"]["cust"]["columns"]["login"]
    ck("取值恰好相等" in (gl.get("需确认") or ""),
       "唯一列被推成外键时,**把怀疑说出来** —— 不崩不等于推对了",
       str(gl.get("需确认"))[:90])
    ck(gl.get("unique") is True,
       "外键的生成策略要**带上 schema 的事实**(唯一/可空)—— "
       "第一版外键分支自己造了份精简规格,把它们丢了", str(gl)[:110])
    pu = P.build(facts, scale=1.0, tables=["cust"])
    mu, _mu = G.generate(pu, conn)
    lv = [r.get("login") for r in mu["cust"] if r.get("login") is not None]
    ck(len(lv) == len(set(lv)), f"唯一列造出来不重复({len(lv)} 个值)", str(lv[:4]))
    ex = {r[0] for r in conn.q("select login from cust where login is not null")}
    ck(not (set(lv) & ex),
       "而且和**库里已有的**不重 —— 只在自己这批里去重是不够的")
    try:
        cu = S.connect(os.path.join(tmpd, "known_test.db"))
        L.load(cu, pu, mu, dry=False, log=lambda *x: None); cu.commit(); cu.close()
        ck(True, "真灌进一张已经有数据的表,不触发 UNIQUE 冲突")
    except Exception as e:
        ck(False, "真灌进一张已经有数据的表,不触发 UNIQUE 冲突", f"{type(e).__name__}: {e}")

    print("\n【灌入前:列对不上要当场抛,不许静默补 NULL】")
    p7 = P.build(facts, scale=1.0, tables=["cust"])
    m7, _m7 = G.generate(p7, conn)
    ck(not (set(p7["tables"]["cust"]["columns"]) - set(m7["cust"][0])),
       "正常情况下,方案声明的每一列生成器都产出了")
    broken = [dict(r) for r in m7["cust"]]
    for r in broken: r.pop("city", None)      # 模拟生成器漏了一列
    # 只认 SystemExit + 说清是哪几列。**别的异常算失败** ——
    # 拆掉这道检查之后真实的表现是 KeyError,那也叫"抛了",但它:
    #   ① 说不清是哪一列出的事  ② 会把整个自测带走,后面十几项一条都跑不到
    # 所以这里必须自己接住,让它变成**一条红线**而不是一次崩溃。
    # 一个检查崩掉会顺手关掉它后面的所有检查,这比它自己不准更糟。
    try:
        # dry=True 不写任何东西,但列的检查在拼 SQL 之前 —— **预演就该发现它**
        L.load(conn, p7, {"cust": broken}, dry=True, log=lambda *x: None)
        ck(False, "少一列要当场抛(不能静默丢成 NULL)", "没抛,静默丢了")
    except SystemExit as e:
        ck("city" in str(e), "少一列当场抛,并且指名道姓说是哪几列", str(e)[:90])
    except Exception as e:
        ck(False, "少一列要当场抛(不能静默丢成 NULL)",
           f"抛的是 {type(e).__name__}: {e} —— 说不清哪一列,而且会把整个自测带走")

    print("\n【流式生成 · 省内存不能改变结果】")
    import sqlite3 as _sq
    def _fill(path, use_sink):
        shutil.copy(os.path.join(ROOT, "backend", "lanxiu.db"), path)
        c2 = S.connect(path)
        f5 = D.discover(c2, c2.reflect())
        p5 = P.build(f5, scale=0.3)
        if use_sink:
            m5, mn5 = G.generate(p5, c2, sink=L.sink_for(c2, p5))
        else:
            m5, mn5 = G.generate(p5, c2)
            L.load(c2, p5, m5, dry=False, log=lambda *x: None)
        L.fill_deferred(c2, p5, m5, dry=False, log=lambda *x: None)
        c2.commit()
        pre = p5["marker"]["prefix"]
        dump = {}
        for t in p5["order"]:
            tp = p5["tables"][t]
            if tp.get("skip") or not tp["pk"]: continue
            cols = ", ".join(f'"{c}"' for c in tp["columns"])
            dump[t] = c2.q(f'select {cols} from "{t}" where "{tp["pk"][0]}" like \'{pre}%\' '
                           f'order by "{tp["pk"][0]}"')
        c2.close()
        return dump, mn5
    d_mem, mn_mem = _fill(os.path.join(tmpd, "nostream_test.db"), False)
    d_str, mn_str = _fill(os.path.join(tmpd, "stream_test.db"), True)
    diff = [t for t in d_mem if d_mem[t] != d_str.get(t)]
    ck(not diff, "流式和全内存灌进去的数据**逐行完全一样**(省内存不能改变结果)",
       f"这些表不一致: {diff[:4]}")
    ck({t: m["values"] for t, m in mn_mem.items()} ==
       {t: m["values"] for t, m in mn_str.items()},
       "两条路径的 manifest 也一样(回滚依据不能因为省内存而变)")

    print("\n【接口入口 · 靶子是假的,校验是项目真正那一份】")
    import apimock, apidrive, datetime as _dt
    f6 = D.discover(conn, sc) if False else None      # 用主库那份 facts
    src = os.path.join(ROOT, "backend", "lanxiu.db")
    if os.path.exists(src):
        cp6 = os.path.join(tmpd, "api_test.db"); shutil.copy(src, cp6)
        c6 = S.connect(cp6); f6 = D.discover(c6, c6.reflect())
        DRIVEN = ["customer", "appointment"]
        p6 = P.build(f6, scale=0.2, tables=DRIVEN)
        m6, _mm = G.generate(p6, c6)

        # 成败判定:照**真实接口的响应约定** `{ok, code, id, reason}` 验
        REAL_FAIL = {"ok": False, "code": "DUP_PHONE", "reason": "手机号完全相同"}
        REAL_OK = {"ok": True, "code": "CREATE", "id": "C10086", "reason": "已建档"}
        ck(apidrive.outcome(REAL_FAIL, 200, {"ok_field": "ok"})[0] == "rejected",
           "业务拒绝(HTTP 200 + ok:false)判成拒绝")
        ck(apidrive.outcome(REAL_OK, 200, {"ok_field": "ok"})[0] == "ok", "成功判成成功")
        ck(apidrive.outcome(REAL_FAIL, 200, {})[0] != "ok",
           "**规格没说清怎么判成败时,绝不能算成功** —— 真实接口没有 error 字段,"
           "旧的兜底会把每一次业务拒绝记成成功,而拒绝清单正是这条路唯一不可替代的产出")
        ck(apidrive.outcome({"whatever": 1}, 200, {})[0] == "unknown",
           "判不出来的记成「不确定」,不塞进任何一边")

        # 规格校验:三类写错的规格都要被挡下
        base6, store6, stop6 = apimock.serve()
        spec6 = json.loads(json.dumps(apimock.SPEC)); spec6["base"] = base6
        ck(not apidrive.check_spec(spec6, p6), "正确的规格能通过校验",
           str(apidrive.check_spec(spec6, p6))[:120])
        bad6 = json.loads(json.dumps(spec6))
        bad6["endpoints"]["customer"]["create"]["fields"]["name"] = "根本没这列"
        ck(apidrive.check_spec(bad6, p6), "字段映到不存在的列 → 挡下")
        bad7 = json.loads(json.dumps(spec6)); bad7["base"] = "127.0.0.1:8760"
        ck(apidrive.check_spec(bad7, p6), "base 不是 http(s):// → 挡下")

        # **全局环判定污染局部**:拿整库方案来驱动,必须被挡下
        pall = P.build(f6, scale=0.2)
        defer = [1 for t in DRIVEN for g in pall["tables"][t]["columns"].values()
                 if g.get("gen") == "fk" and g.get("deferred") and g.get("table") in DRIVEN]
        if defer:
            ck(apidrive.check_spec(spec6, pall),
               "整库方案里被判成「两阶段」的外键 → 挡下(接口这条路没有回填)")

        # **显式种两条必被拒的**,不靠边界值的运气。
        # 第一版指望「造出来的数据里碰巧有空名字」,scale 小的时候一条都没有,
        # 检查就空过去了 —— 和「夹具写死 id」是同一类毛病:**用例的存在与否交给了偶然**。
        if len(m6["customer"]) >= 3:
            m6["customer"][0]["name"] = ""                       # 姓名必填
            m6["customer"][2]["phone"] = m6["customer"][1]["phone"]   # 手机号重复

        # 把预约时间挪到未来,才验得了 id 翻译(不然全被「必须提前预约」挡掉)
        fut = _dt.datetime.now() + _dt.timedelta(days=3)
        for r in m6["appointment"]:
            r["start_ts"] = fut.strftime("%Y-%m-%d %H:%M:%S")
            r["end_ts"] = (fut + _dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        d6 = apidrive.Driver(spec6, dry=False, log=lambda *a: None)
        rep6 = d6.run(p6, m6)
        ck(rep6["成功"] > 0, f'接口造出了数据(成功 {rep6["成功"]} 条)')
        ck(all(str(c["id"]).startswith("SVR-C") for c in store6.customer),
           "落到服务端的是**服务端分配的 id**,不是我们方案里那个假 id")
        ck(store6.appointment and all(a["customer_id"].startswith("SVR-C")
                                      for a in store6.appointment),
           "子表的外键被翻译成了服务端真实 id(翻译一断,引用会静默指错)",
           str([a.get("customer_id") for a in store6.appointment][:3]))
        says = " | ".join(r["接口说"] for r in rep6["规则"])
        ck("必填" in says, "接口拒了「姓名为空」——库里这列可空,业务不允许", says[:120])
        ck("完全相同" in says, "接口拒了「手机号重复」——库里这列不唯一,业务不允许", says[:120])
        ck(len(rep6["规则"]) == 2 and sum(r["撞了几次"] for r in rep6["规则"]) == 2,
           "拒绝按错误归类:2 条拒绝归成 2 类规则", str(rep6["规则"])[:140])
        ck(all(not re.search(r"PRD N", r["接口说"]) for r in rep6["规则"]),
           "报告展示的是错误**原文**,不是用来分组的归一化形式")

        # ---- 差集清单:按错误码归类 + 削到最小请求体 ----
        # 再种两条同码但**文案不同**的拒绝(文案里带被撞客户的名字)
        if len(m6["customer"]) >= 8:
            m6["customer"][4]["phone"] = m6["customer"][3]["phone"]
            m6["customer"][5]["phone"] = m6["customer"][1]["phone"]
            m6["customer"][6]["advisor"] = "已离职 张三"   # 删掉这个字段请求就会成功
        # **d7 要一个干净的靶子。** 第一版让它打 d6 已经灌满的那个 ——
        # 于是每一行的手机号都先撞 DUP_PHONE,根本走不到后面的规则。
        # 检查因此一直是 0,而 0 看起来像"这条路径不存在",不像"我把路堵住了"。
        base7, store7, stop7 = apimock.serve()
        spec7 = json.loads(json.dumps(spec6)); spec7["base"] = base7
        d7 = apidrive.Driver(spec7, dry=False, log=lambda *a: None)
        # 留一批没发过的当定向构造的基线
        bases7 = [d7.payload_of("customer", r, p6, set())[0] for r in m6["customer"][-4:]]
        m6b = dict(m6); m6b["customer"] = m6["customer"][:-4]
        d7.run(p6, m6b)
        dup = [r for r in d7.rejected if r.get("码") == "DUP_PHONE"]
        ck(len(dup) >= 2 and len({r["错误"] for r in dup}) >= 2,
           "种出了同码但文案不同的拒绝(文案里带被撞客户的名字)", f"只有 {len(dup)} 条")
        rep7 = d7.report()
        codes = [r["码"] for r in rep7["规则"]]
        ck(len(codes) == len(set(codes)),
           "**按错误码归类,不按文案** —— 文案带 id 和人名,同一条规则每次都不一样",
           str(codes))
        ck(sum(1 for r in rep7["规则"] if r["码"] == "DUP_PHONE") == 1,
           f"{len(dup)} 条同码拒绝归成 1 条规则")

        # 种一条「顾问不在职」——它的最小化会把 advisor 删掉,而删掉之后请求**会成功**,
        # 于是探测本身在库里留下一条记录。这正是要验的那条路径。
        before_min = len(d7.created)
        calls = d7.minimize(p6)
        minted = len(d7.created) - before_min
        rep7 = d7.report()
        # **别用 next(...) 找规则。** 找不到时抛 StopIteration,把整个自测带走 ——
        # 而崩溃和"没跑过"在输出上分不开。这个坑在这个文件里踩到第三次了:
        # **测试代码里任何「假定它一定存在」的写法(next / [0] / 直接下标),
        # 在被测对象坏掉时都会变成崩溃。测试代码要比被测代码更防御。**
        def rule_of(code):
            return next((r for r in rep7["规则"] if r.get("码") == code), None)
        rule = rule_of("DUP_PHONE")
        ck(rule is not None, "报告里能按码找到 DUP_PHONE 这条规则",
           str([r.get("码") for r in rep7["规则"]])[:120])
        mb = (rule or {}).get("最小请求体")
        ck(rule is not None and mb is not None and len(mb) <= len(rule["例子"]),
           f"削出了最小请求体({len((rule or {}).get('例子') or {})} 字段 → "
           f"{len(mb or {})} 字段,{calls} 次请求)")
        ck("phone" in (mb or {}) and "name" in (mb or {}),
           "**削最小要保持同一个错误码**:少了 name 会变成 NEED_NAME,那是另一条规则,"
           "所以 name 不能删", str(mb))
        need = rule_of("NEED_NAME")
        if need:
            ck("name" in (need["库这边"] or {}),
               "「库这边」覆盖整个字段面,连被削掉的 name 也在 —— "
               "而「库里 name 可空」正是这条差集的另一半", str(need["库这边"]))
            ck(need["库这边"]["name"]["可空"] is True,
               "而且它如实说了:库里这一列**可空**,业务却必填")
        # ---- 定向构造:为撞不到的码反推数据 ----
        # **单开一个干净靶子。** 同一次运行不能既撞到 DUP_PHONE(前面那几条归类/削最小
        # 的检查要它),又把 DUP_PHONE 留给定向构造当目标 —— 两个需求互斥。
        # 挤在一个靶子上的结果是:要么前面几条挂,要么「归因正确」那条空过。
        import probe as PR
        base9, store9, stop9 = apimock.serve()
        spec9 = json.loads(json.dumps(spec6)); spec9["base"] = base9
        d9 = apidrive.Driver(spec9, dry=False, log=lambda *a: None)
        m9 = dict(m6); m9["customer"] = m6["customer"][7:-4]   # 不含种过重复的那几行
        spare9 = [d9.payload_of("customer", r, p6, set())[0] for r in m6["customer"][-4:]]
        d9.run(p6, m9)
        cov_b = d9.coverage()
        pres = PR.probe(d9, p6, {t: c.get("没撞到") or [] for t, c in cov_b.items()},
                        {"customer": spare9}, budget=120)
        got = pres["撞出来的"]
        ck("NEED_REVIEW" in got,
           "**定向构造撞出了随机数据永远撞不到的那条**(姓名相似+尾号相同+同门店)—— "
           "随机数据之间没有关系,加到一百万条也一样", str(sorted(got)))
        ck(got.get("NEED_REVIEW", {}).get("算子") == "仿冒近似重复",
           "而且是「仿冒」这个算子撞出来的 —— 它需要一个**参照物**",
           str(got.get("NEED_REVIEW")))
        ck("DUP_PHONE" in got, "DUP_PHONE 确实进了探测目标(不然下面那条是空过的)",
           str(sorted(got)))
        ck(got.get("DUP_PHONE", {}).get("算子") in ("抄已有", "仿冒近似重复"),
           "**归因正确**:重复类规则只能由「抄已有 / 仿冒」触发 —— "
           "探测之间不隔离的话,前一个变异建成的记录会让后一个撞上重复,"
           "于是「缺某个选填字段」被记成触发重复的算子",
           str(got.get("DUP_PHONE")))
        ck(not any(v.get("归因存疑") for v in got.values()),
           "没有归因存疑的条目(未变异的基线自己不触发这些码)",
           str({k: v.get("归因存疑") for k, v in got.items() if v.get("归因存疑")}))
        # 上下文字段 + 成对组合
        ck("role" in (spec9["endpoints"]["appointment"]["create"].get("const_fields") or {}),
           "规格支持**上下文字段**(role/actor/幂等键)—— 它们不对应任何列,"
           "只用列映射表达不了")
        b9 = d9.payload_of("appointment", m6["appointment"][0], p6, set())[0]
        ck(b9.get("role") == "顾问", "上下文字段真的进了请求体", str(b9)[:100])
        alt = PR.op_alt_value({"role": "顾问"}, "role", None, {"role": ["店长"]})
        ck(alt == {"role": "店长"},
           "「换合法取值」算子:同一份数据换个身份,会落到另一条规则上")
        ck(pres["每张表"]["customer"]["试了"] > 5,
           f'每张表试了几次要报出来({pres["每张表"]})—— '
           "「试了 2 次没戏」和「试了 30 次确实撞不到」不是一回事")
        # 成对组合:BACKFILL_LIMIT 要「role=店长」**且**「超过 7 天前」,单改一处只会落到别的码
        real_c = [v for (pt, _k), v in d9.idmap.items() if pt == "customer"]
        ab = []
        for r in m6["appointment"][:4]:
            b = d9.payload_of("appointment", r, p6, set())[0]
            if real_c: b["customer_id"] = real_c[0]
            b["start"] = (_dt.datetime.now() + _dt.timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")
            b["end"] = (_dt.datetime.now() + _dt.timedelta(days=4, hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            ab.append(b)
        pres2 = PR.probe(d9, p6, {"appointment": ["BACKFILL_LIMIT"]},
                         {"appointment": ab}, budget=200)
        bl = pres2["撞出来的"].get("BACKFILL_LIMIT")
        ck(bl is not None,
           "**成对组合**撞出了要两个条件同时成立的规则(role=店长 且 超过 7 天前)",
           str(pres2)[:160])
        ck(bl and "+" in bl["算子"],
           f'而且如实报出是组合出来的:{bl["算子"] if bl else "—"} 改 {bl["改的字段"] if bl else "—"}')

        bad_base = PR.probe(d9, p6, {"customer": ["NEED_REVIEW"]},
                            {"customer": [{"name": "", "phone": "x"}]}, budget=10)
        ck(bad_base["跳过的表"].get("customer"),
           "基线本身就被拒时,拒绝出结论(基线不干净,归因就是假的)",
           str(bad_base))
        d9.rollback(); stop9()

        # ---- 覆盖率:这批数据撞到了多少条已知规则 ----
        cov = d7.coverage()
        ck("customer" in cov and cov["customer"].get("全集"),
           "规格声明了业务码全集,覆盖率才度量得出来", str(cov)[:120])
        ck(isinstance(cov["customer"].get("没撞到"), list),
           "**没撞到的也要列出来** —— 清单里每一条都是真的,所以它看起来是完整的;"
           "缺的那些不留痕迹")
        ck("NEED_REVIEW" in cov["customer"]["没撞到"],
           "随机数据天然撞不到「相似性」类规则(姓名相似+尾号相同+同门店)—— "
           "如实报出来,不假装覆盖全了", str(cov["customer"]))
        nodecl = json.loads(json.dumps(spec7))
        nodecl["endpoints"]["customer"].pop("codes")
        d8 = apidrive.Driver(nodecl, dry=True, log=lambda *a: None)
        c8 = d8.coverage()
        ck(c8["customer"]["全集"] is None and "无法度量" in c8["customer"]["说明"],
           "规格没声明全集时,明说**覆盖率无法度量**,不默默让人以为这就是全部",
           str(c8["customer"])[:120])

        # **削最小会真的发请求**,某个变体建成了就在库里留了一条 ——
        # 所以它必须被记进回滚清单。第一版这条写成了 `len(...) >= 0`,永远成立,
        # 等于没有。**这是我第二次写出永远为真的检查了,专门记在这。**
        d7.rollback(); d6.rollback(); stop7()
        ck(minted > 0,
           f"削最小过程中确实有变体**建成**了({minted} 条)—— 这条路径真的走到了,"
           "不是绿在没走到上", "一条都没建成,那下面那条检查是空的")
        ck(len(store6.customer) == 0 and len(store6.appointment) == 0
           and len(store7.customer) == 0 and len(store7.appointment) == 0,
           "两个驱动都回滚后靶子清零 —— 削最小时建成的变体也被删掉了(探测也是写入)",
           f"还剩 {len(store6.customer)}/{len(store7.customer)} 客户")
        n6, cant6 = 0, {}
        # 靶子会拒绝删除「名下还有预约」的客户 —— 只有**先孩子后父亲**才删得干净。
        # 顺序错了的表现是删不掉,而不是"删掉了但没人知道顺序对不对"。
        ck(len(store6.customer) == 0,
           "回滚必须先孩子后父亲:靶子拒绝删「名下还有预约」的客户,顺序错了就会剩下客户删不掉")

        # 没有删除接口的表:必须如实说删不掉,不许假装成功
        nod = json.loads(json.dumps(spec6)); nod["endpoints"]["customer"].pop("delete")
        ck(apidrive.rollbackable(nod, DRIVEN) == ["customer"],
           "没声明删除接口的表要被点名(灌得进去但删不掉,比灌不进去糟)")
        stop6()
    else:
        print("  (跳过:backend/lanxiu.db 不在)")

    print("\n【接手体检 · 门面那条命令】")
    import checkup as CK
    kp = os.path.join(tmpd, "known_test.db")
    rk = CK.checkup(kp, "test", log=lambda *a: None)
    ck(rk["表"]["总数"] >= 4 and rk["关系"]["挖出来"] > 0,
       f'体检读得出表和关系(表 {rk["表"]["总数"]} 张 / 关系 {rk["关系"]["挖出来"]} 条)')
    ck(0 < rk["认出率"]["百分比"] <= 1, f'认出率带分母({rk["认出率"]["认出语义"]}'
       f'/{rk["认出率"]["列总数"]})')
    # 靶子库在后面那一节才建 —— 这里自己建一份,别依赖执行顺序。
    # (第一版直接引用,当场 SystemExit 把整个自测带走 ——
    #  **检查之间的隐性顺序依赖,坏起来是崩溃不是红线**,这个坑今天第三次了。)
    import generalize as GEN2
    gp2 = os.path.join(tmpd, "checkup_gen_test.db")
    if not os.path.exists(gp2): GEN2.build_db(gp2)
    rg = CK.checkup(gp2, "test", log=lambda *a: None)
    ck(rg["关系"]["库里明写"] == 3,
       "明写的外键**按边去重**再数 —— 同一条关系常被声明两次(列级+表级),"
       "不去重会报成「明写 4 → 挖出 3」,读起来像少了一条",
       f'报了 {rg["关系"]["库里明写"]} 条')
    try:
        CK.checkup(kp, "生产", log=lambda *a: None); ck(False, "体检也要过闸门")
    except guard.Refused: ck(True, "体检虽然只读,也要显式声明环境(闸门照拦)")

    print("\n【起草接口规格 · 静态扒 + 模型只补语义(离线,不调模型)】")
    import specdraft as SD
    sv = os.path.join(ROOT, "backend", "server.py")
    rl = os.path.join(ROOT, "backend", "rules.py")
    if os.path.exists(sv):
        sc9 = SD.scan_service(sv, rl)
        ck(len(sc9["routes"]) > 20, f'静态扒出路由 {len(sc9["routes"])} 条')
        cc = next((r for r in sc9["routes"] if r["handler"] == "create_customer"), None)
        ck(cc and "name" in cc["读的请求字段"] and "customer" in cc["写的表"],
           "扒得出「读哪些请求字段 / 写哪张表」——这些是事实,不该让模型猜", str(cc)[:110])
        ck(cc and "id" in cc["成功返回的字段"],
           "成功返回的字段要抓**整个 dict**,不是一行里的第一个(第一版只抓到 code)",
           str(cc and cc["成功返回的字段"]))
        ck("NEED_REVIEW" in (sc9["校验器分函数"].get("validate_customer") or []),
           "校验器的失败码按**函数**收集 —— 全塞给每个端点会诱导它乱选码")
        tb9 = SD.table_columns(S.connect(os.path.join(ROOT, "backend", "lanxiu.db")))
        # **送出去的候选码要按端点收窄**,不能把全部失败码塞给每一个。
        # (上一条检查测的是「扒出来分没分函数」,而真正会出错的是「送出去时怎么给」——
        #  咬合时发现破坏后者不会红:**检查和破坏点测的不是同一件事。**)
        pay9 = SD.build_payload(sc9, tb9)
        cce = next((e for e in pay9["写接口"] if e["handler"] == "create_customer"), None)
        ck(cce and "NEED_NAME" in cce["可能的业务码"],
           "建客户那条,候选码里有它真会撞上的 NEED_NAME")
        ck(cce and not ({"TOO_BIG", "BAD_HEADER", "TOO_MANY"} & set(cce["可能的业务码"])),
           "而**不含**导入/附件校验器的码 —— 它根本不调那些校验器。"
           "清单里有,模型就以为可选,那不是它编的,是我诱导的",
           str(cce and cce["可能的业务码"]))
        # 校验层:五类都要挡下
        raw9 = {"endpoints": [
            {"handler": "create_customer", "table": "customer", "is_create": True,
             "fields": {"name": "name", "phone": "phone", "根本不读的字段": "shop",
                        "addr": "没这列"},
             "context_fields": ["name"], "unique_fields": ["phone"],
             "codes": ["NEED_NAME", "根本不存在的码"]},
            {"handler": "查无此函数", "table": "customer", "is_create": True, "fields": {}},
            {"handler": "save_block", "table": "page_block", "is_create": False,
             "reason": "是编辑不是新建"}]}
        sp9, dr9 = SD.validate(raw9, sc9, tb9)
        txt9 = " | ".join(dr9)
        ck("customer" in sp9["endpoints"], "正常那条留下来了", str(list(sp9["endpoints"])))
        ck("不在真实路由表" in txt9, "编出来的 handler → 丢")
        ck("接口根本不读这个字段" in txt9, "接口根本不读的字段 → 丢")
        ck("列不存在" in txt9, "映到不存在的列 → 丢")
        ck("源码里没出现过" in txt9, "编出来的业务码 → 丢")
        ck("不是新建接口" in txt9,
           "模型自己判为「不是新建」的 → 按**结构化字段**过滤,不靠它在自然语言里说")
        ck(sp9["endpoints"]["customer"]["create"]["path"] == "/api/customer-create",
           "**路径是我自己查回去的,不问模型** —— 少问一个已知字段就少一处填错的地方")
        ck("name" not in (sp9["endpoints"]["customer"]["create"].get("const_fields") or {}),
           "明明是列的字段,不许当上下文字段")

    print("\n【泛化 · 换一套命名约定还认不认得出】")
    import generalize as GEN
    gp = os.path.join(tmpd, "generalize_test.db")
    GEN.build_db(gp)
    cg = S.connect(gp); fg = D.discover(cg, cg.reflect())
    pg = P.build(fg, scale=1.0)
    po = pg["tables"]["purchase_order"]["columns"]
    ck(sum(len(t.declared_fks) for t in cg.reflect().tables.values()) > 0
       and any(g["gen"] == "fk" for g in po.values()),
       "**明写外键**这条路也走得通(澜绣云裳那边是 0 个,这条以前从没被走过)")
    ck(not fg.get("中文库"), "认出这是个西文库(数据池要跟着源库的文字走)")
    ck(po["amount_cents"]["gen"] == "money" and po["amount_cents"].get("kind") == "int",
       "`amount_cents` 认成钱,但记住了它是整数列")
    ck(po.get("order_no", {}).get("编号格式", {}).get("前缀") == "PO",
       "编号格式学的是源库的(PO-…),不是自己拍一个前缀",
       str(po.get("order_no", {}).get("编号格式")))
    seqg = pg["tables"]["purchase_order"].get("时间序") or []
    ck(any(o["先"] == "created_at" and o["后"] == "placed_at" for o in seqg),
       "从源库**统计**出时间先后,而不是靠写死的列名表", str(seqg)[:120])

    mg, _mg = G.generate(pg, cg)
    ck(all(isinstance(r["amount_cents"], int) for r in mg["purchase_order"]),
       "整数金额列造出来的是整数(SQLite 宽容,MySQL 会截断)",
       str([r["amount_cents"] for r in mg["purchase_order"][:3]]))
    ck(all(re.match(r"^PO-\d{6}$", str(r["order_no"])) for r in mg["purchase_order"]),
       "编号照源库格式造", str([r["order_no"] for r in mg["purchase_order"][:3]]))
    edge_vals = {v for _n, v in G._EDGE_EN} | {v for _n, v in G._EDGE_ZH}
    ordinary = [str(r["display_name"]) for r in mg["account"]
                if str(r["display_name"]) not in edge_vals]
    ck(ordinary and not any("\u4e00" <= ch <= "\u9fff" for x in ordinary for ch in x),
       "西文库里的普通姓名不会是中文", str(ordinary[:3]))
    injected = [str(r["display_name"]) for r in mg["account"]
                if str(r["display_name"]) in {v for _n, v in G._EDGE_EN}]
    ck(injected and not any(x in {v for _n, v in G._EDGE_ZH} - {v for _n, v in G._EDGE_EN}
                            for x in injected),
       "边界值也跟着语言走(「  John  」而不是「  张三  」)", str(injected[:3]))
    ck(any("汉服" in x or "🧵" in x for x in injected),
       "但**非拉丁字符**那一条两种库都保留 —— 在西文系统里它是正当的字符集测试",
       str(injected[:4]))
    badseq = [(r["created_at"], r["placed_at"]) for r in mg["purchase_order"]
              if r.get("created_at") and r.get("placed_at")
              and str(r["placed_at"]) < str(r["created_at"])]
    ck(not badseq, "统计出来的先后真的落到数据上了(created_at ≤ placed_at)",
       str(badseq[:2]))
    # 建档时间列**不能写死名字**:这个库叫 created_at
    ck(D.creation_col(list(po), {c: g["gen"] for c, g in po.items()}) == "created_at",
       "建档时间那一列是**推**出来的(这个库叫 created_at,不叫 created)")
    cg.close()

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
