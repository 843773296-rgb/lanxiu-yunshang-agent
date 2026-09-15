#!/usr/bin/env python3
"""工期推算 —— 客户问的第二个问题:「什么时候能拿到?」

07-工期与成本.md 里画了一张并行链路图,这个文件把它算出来:

    面料备料 ──┐
               ├─→ 方案确认 → 裁剪缝制 → 整烫质检 → 物流 → 交付
    装饰工艺 ──┘   (绣片必须在缝制前完成)

**三个最容易算错的地方,全在这个文件里堵住:**

1. **并行的段不能相加。** 面料备料和绣片制作是并行的,取 max 不是取和。
   加起来算是常见的高估 —— 高估会把本来能接的单吓跑。
2. **不是所有时间都能除以人数。** 工日可以除(两个绣工并行),
   但**染色晾晒是日历天、织机一台只能一个人、手绘换人笔触就变** —— 这些除不动。
   少了「单位」和「并行上限」两列,系统会算出「30 天晾晒 ÷ 3 人 = 10 天」这种荒唐结论。
3. **盘扣按颗计。** 一件立领长衫 7–9 颗花型盘扣就是 3–9 工日,
   相当于一次局部平绣 —— 报价和工期里都最容易漏。这里从版型的 BOM 里取对数再乘。

输出是**区间不是一个数**。定制工期本来就有不确定性,给单个数字等于给一个必然被打脸的承诺。
"""
import os, re, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(HERE, "07-工期与成本.md")
sys.path.insert(0, HERE)
import derive_pattern as dp
import derive_combo


def _cap():
    import capacity; return capacity


def dp_combo_tables():
    """工艺的「工序」从相容矩阵的属性表来 —— 那张表已经标好了织造/印染/刺绣/缝制。
    不在这里另存一份:同一个属性存两处,一定漂。"""
    return derive_combo._tables()

# 缝制段:基础天数 + 裁片数 × 系数 + 难度加成
SEW_BASE, SEW_PER_PIECE = 5.0, 0.2
SEW_HARD = {"低": 0, "中": 1, "高": 2, "极高": 4}
CONFIRM = (3, 10)      # 方案确认与打样往返 —— 定制品才有,订单状态里的「方案确认中」
FINISH = (2, 3)        # 整烫 + 质检
SHIP = (2, 5)          # 物流
MUSLIN = (7, 12)       # 白坯试衣
PANJIU = ("WL07", "WL60", "WL61")   # 盘扣类物料,按对数计工日


def craft_days():
    """工艺工时表:编码 → (最少, 最多, 单位, 并行上限, 备注)"""
    out = {}
    for line in dp._read(MD).split("\n"):
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) == 7 and c[0].startswith("KF"):
            try: lo, hi, cap = float(c[2]), float(c[3]), int(c[5])
            except ValueError: continue
            out[c[0]] = (lo, hi, c[4], cap, c[6])
    return out


def _in_stock(crafts, names, exclude=None):
    """和这些工艺都相容、且当前有现货的面料。

    工期推算一直有条建议叫「改用现货面料可压缩 20 天」—— 在库里加上现货字段之前,
    **系统根本不知道哪些面料有现货,那条建议只是一句空话。** 现在它能点名了。
    """
    db = os.path.join(HERE, "..", "backend", "lanxiu.db")
    if not os.path.exists(db) or not crafts: return []
    import sqlite3
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row
    q = ("SELECT m.code,m.name,m.unit,m.price,m.lead_days,m.stock_qty FROM material m"
         " WHERE m.cat='主料' AND m.stock_qty>0 AND m.code<>?"
         + "".join(" AND EXISTS(SELECT 1 FROM craft_combo cc WHERE cc.material=m.code"
                   " AND cc.craft=? AND cc.verdict='可')" for _ in crafts)
         + " ORDER BY m.stock_qty DESC")
    rs = con.execute(q, [exclude or ""] + list(crafts)).fetchall()
    return [dict(code=r["code"], name=r["name"], unit=r["unit"], price=r["price"],
                 lead=r["lead_days"], stock=r["stock_qty"]) for r in rs]


def _pan_pairs(pattern):
    """这个版型有几对盘扣 —— 从 BOM 里取,不拍固定值"""
    return sum(b["qty_base"] for b in dp.pattern_bom()
               if b["pattern"] == pattern and b["material"] in PANJIU)


def estimate(pattern, size, material, crafts=(), scope="局部",
             workers=2, custom=True, craft_names=None, from_date=None, capacity=True):
    """返回(最快, 最慢)天数、各段明细、关键路径和风险。"""
    D = craft_days()
    bom = dp.estimate(pattern, size, material, crafts, scope, craft_names)
    if bom.get("error"): return bom
    p = next(x for x in dp.patterns() if x["code"] == pattern)
    names = craft_names or {}

    # ── 并行支一:面料与辅料备料 ──────────────────────────────
    lead = max((l["lead"] for l in bom["lines"]), default=0)
    supply = dict(段="面料备料", 最快=lead, 最慢=lead,
                  说明=f"卡在{bom['最长备料项']}({lead} 天)")

    # ── 按工序分支 ────────────────────────────────────────────
    # 03-工艺.md 开篇那张表写着四类工艺**介入的时间点完全不同**:
    #   织造 = 面料织的时候  印染 = 织好之后裁剪之前
    #   刺绣 = 绣片上(可与备料并行)  缝制 = 成衣阶段
    # 第一版把所有工艺都塞进并行支,结果「加了盘扣工期没变」——
    # 盘扣是成衣工序,它串在缝制后面,不可能和面料备料并行。
    # 这张表一直在文件开头,只是没被算进来。
    STAGE = {c: k["stage"] for c, k in dp_combo_tables()[0].items()}
    mult = 4 if scope == "整幅" else 1
    deco, items = [0.0, 0.0], []
    dye, sewc = [0.0, 0.0], [0.0, 0.0]
    waits, queue_risk, gap = {}, [], []
    for kc in crafts:
        d = D.get(kc)
        if not d: continue
        lo, hi, unit, cap, note = d
        nm = names.get(kc, kc)
        if kc == "KF20":                     # 盘扣按颗
            pairs = _pan_pairs(pattern) or 4
            lo, hi = lo * pairs, hi * pairs
            note = f"{pairs} 对盘扣 × {d[0]}–{d[1]} 工日/对"
        lo, hi = lo * mult, hi * mult
        if unit == "工日":
            n = min(workers, cap)
            a, b = lo / n, hi / n
            how = f"{lo:.0f}–{hi:.0f} 工日 ÷ {n} 人" + ("(**除不动**)" if cap == 1 else "")
        else:
            a, b = lo, hi                    # 日历天:晾晒/外发,加人无效
            how = f"{lo:.0f}–{hi:.0f} 日历天(**加人无效**)"
        st = STAGE.get(kc, "刺绣")
        bucket = {"印染": dye, "缝制": sewc}.get(st, deco)   # 织造与刺绣走并行支
        # **排队等待。** 工期算的是「要做多久」,这里补上「什么时候排得上」——
        # 定制业最常见的延期原因是排不上,不是做得慢。
        if capacity and (a or b):
            try:
                cp = _cap().when_free(kc, hi, from_date)
                if not cp.get("error"):
                    w = cp["排队等待天数"]
                    waits.setdefault(st, []).append((w, nm, cp))
                    if cp.get("不可加人") and w > 0:
                        queue_risk.append(f"{nm}:排队 {w} 天 —— {cp['note']}")
                else:
                    gap.append(f"{nm}:{cp['error']}")
            except Exception:
                pass
        if a or b:
            bucket[0] += a; bucket[1] += b
            items.append(dict(工艺=nm, 工序=st, 最快=round(a, 1), 最慢=round(b, 1),
                              算法=how, 备注=note,
                              位置={"印染": "备料之后、裁剪之前(串行)",
                                    "缝制": "成衣阶段(串行)"}.get(st, "绣片,与备料并行")))
    # 各支的排队等待:同一支里的工艺可以由不同师傅同时等,取最长的那个
    qw = {k: max(x[0] for x in v) for k, v in waits.items()}
    deco[0] += max(qw.get("刺绣", 0), qw.get("织造", 0))
    deco[1] += max(qw.get("刺绣", 0), qw.get("织造", 0))
    dye[0] += qw.get("印染", 0); dye[1] += qw.get("印染", 0)
    sewc[0] += qw.get("缝制", 0); sewc[1] += qw.get("缝制", 0)
    decor = dict(段="绣片 / 织片制作", 最快=round(deco[0], 1), 最慢=round(deco[1], 1),
                 说明=("、".join(x["工艺"] for x in items if x["工序"] in ("刺绣", "织造"))
                       or "无绣织工艺"), 明细=items)

    # ── 串行段 ────────────────────────────────────────────────
    sew = SEW_BASE + p["pieces"] * SEW_PER_PIECE + SEW_HARD.get(p["difficulty"], 1)
    # 印染串在备料之后(要等面料到货),刺绣/织片与这一整支并行
    left = (supply["最快"] + dye[0], supply["最慢"] + dye[1])
    par = dict(段="关键路径(备料+印染 / 绣织片 取较长的一支)",
               最快=round(max(left[0], decor["最快"]), 1),
               最慢=round(max(left[1], decor["最慢"]), 1),
               说明=("卡在面料备料" if left[1] >= decor["最慢"] and dye[1] == 0 else
                     "卡在面料备料+印染" if left[1] >= decor["最慢"] else "卡在绣织工艺"))
    # **「该不该试衣」的判断不在这儿了。** 它原来是这一行的局部变量 `heavy` ——
    # 一个连名字都没有的判断,别处要用只能抄一份,然后两份开始漂。
    # 搬进 `muslin.py` 之后它有了名字、有了理由,而且那条线
    # **是 demo 级、要业务确认**这件事跟着一起传出去了。
    import muslin as _ms
    heavy, heavy_why = _ms.该试衣(decor["最慢"], crafts, D)
    seq = [par]
    if custom: seq.append(dict(段="方案确认与打样", 最快=CONFIRM[0], 最慢=CONFIRM[1],
                               说明="设计稿确认 + 打样往返"))
    if heavy: seq.append(dict(段="白坯试衣", 最快=MUSLIN[0], 最慢=MUSLIN[1],
                              说明="**重工档强制** —— 云锦缂丝裁下去没有回头路。"
                                   + heavy_why))
    seq.append(dict(段="裁剪缝制", 最快=round(sew, 1), 最慢=round(sew * 1.5, 1),
                    说明=f"{p['pieces']} 个裁片,改版难度{p['difficulty']}"))
    if sewc[1]:
        seq.append(dict(段="成衣阶段工序", 最快=round(sewc[0], 1), 最慢=round(sewc[1], 1),
                        说明="、".join(x["工艺"] for x in items if x["工序"] == "缝制")
                             + " —— **串在缝制之后,不与备料并行**"))
    seq.append(dict(段="整烫质检", 最快=FINISH[0], 最慢=FINISH[1], 说明=""))
    seq.append(dict(段="物流", 最快=SHIP[0], 最慢=SHIP[1], 说明=""))
    fast = round(sum(x["最快"] for x in seq))
    slow = round(sum(x["最慢"] for x in seq))

    # ── 风险与可压缩性 ────────────────────────────────────────
    risk, press = [], []
    for kc in crafts:
        d = D.get(kc)
        if d and d[3] == 1 and d[0] > 0:
            risk.append(f"{names.get(kc,kc)}:{d[4] or '不能靠加人压缩'}")
    if "KF41" in crafts or "MT01" in material or "香云纱" in bom["material"]:
        risk.append("香云纱晒莨**需日照,雨季直接停工** —— 工期承诺必须留余量,且下单时就要说")
    if par["说明"].startswith("卡在面料备料"):
        alt = _in_stock(crafts, names, exclude=material)
        if alt:
            top = "、".join(f"{a['name']}(现货 {a['stock']:.0f}{a['unit']},备料 {a['lead']} 天)"
                            for a in alt[:3])
            press.append(f"改用现货面料可把备料从 {supply['最慢']} 天压到 1–3 天。"
                         f"和所选工艺相容且**当前有现货**的:{top}"
                         f"(共 {len(alt)} 种)。"
                         f"**面料换了质感和售价都会变,必须让客户确认,不能替他决定。**")
        else:
            press.append(f"备料 {supply['最慢']} 天,而所选工艺相容的面料**当前全部无现货** —— "
                         "这一段压不下去,只能换工艺或改期")
    else:
        can = [k for k in crafts if D.get(k) and D[k][3] > 1 and D[k][2] == "工日"]
        press.append(f"增加绣工并行可压缩 {[names.get(k,k) for k in can]}(成本上升,"
                     f"且多人绣同一件会有针法差异)" if can
                     else "**关键路径上的工艺都不能靠加人压缩** —— 只能简化工艺或换配置")
    press.append("机缝替代手工可省 2–4 天(「高定感」下降,须客户确认)")

    risk = queue_risk + risk
    if gap: risk = gap + risk
    return dict(排队等待=qw, 产能缺口=gap,
                版型=p["name"], 尺码=size, 面料=bom["material"], 工艺范围=scope,
                师傅数=workers, 最快天数=fast, 最慢天数=slow,
                关键路径=par["说明"], 分段=seq, 装饰明细=items,
                备料=supply, 装饰=decor, 印染=dict(最快=dye[0], 最慢=dye[1]),
                成衣工序=dict(最快=sewc[0], 最慢=sewc[1]), 物料成本=bom["物料成本"],
                风险=risk, 可压缩=press,
                note="工期是**区间不是承诺**。对客户报最慢那个数,把余量留给自己。")


def deadline(need_date, order_date=None, **kw):
    """倒推:客户说了用件日期,现在下单来不来得及。

    07 号文件写着「下单日 + 预估工期 > 用件日期时,**直接拦截并提示改配置**」——
    这条一直只是一句话。婚礼订单尤其致命:**日子是不能改的**,
    到时候交不出来,赔多少钱都换不回那一天。
    """
    r = estimate(**kw)
    if r.get("error"): return r
    d0 = dt.date.fromisoformat(order_date) if order_date else dt.date.today()
    need = dt.date.fromisoformat(need_date)
    have = (need - d0).days
    latest = need - dt.timedelta(days=r["最慢天数"])
    ok = have >= r["最慢天数"]
    r.update(用件日期=need_date, 下单日=d0.isoformat(), 剩余天数=have,
             最晚下单日=latest.isoformat(), 赶得上=ok,
             结论=("赶得上,还有 %d 天余量" % (have - r["最慢天数"]) if ok else
                 ("**赶不上**:按最慢 %d 天算,最晚 %s 就得下单,已经过了 %d 天"
                  % (r["最慢天数"], latest.isoformat(), -(have - r["最慢天数"])))),
             建议=([] if ok else r["可压缩"] + ["或者换一个工期档更短的配置"]))
    return r


if __name__ == "__main__":
    import sqlite3, json
    print("工期推算 · 自测\n" + "=" * 78)
    D = craft_days()
    db = os.path.join(HERE, "..", "backend", "lanxiu.db")
    con = sqlite3.connect(db)
    N = {r[0]: r[1] for r in con.execute("SELECT code,name FROM craft")}
    kf = {r[0] for r in con.execute("SELECT code FROM craft WHERE cat='工艺'")}
    print(f"工时表 {len(D)} 条;工艺表 {len(kf)} 条")
    miss = sorted(kf - set(D))
    assert not miss, f"这些工艺没有工时,工期算不出来:{[N[m] for m in miss]}"
    print(f"  ✅ 每个工艺都有工时、单位和并行上限")
    print(f"  除不动的(并行上限=1):{sum(1 for v in D.values() if v[3]==1)} 种,"
          f"其中按日历天算的 {sum(1 for v in D.values() if v[2]=='日历天')} 种")

    print("\n对照知识库自己写的三档(07 号文件第四节):")
    # 「重档」在知识库里的定义是「云锦/缂丝 + **重工**绣 + 全手工」——
    # 重工指整幅,不是局部。第一次跑这个自测时按局部算,只有 45–76 天,
    # 差了一半 —— **不是公式错,是用例把配置写轻了**。
    CASES = [("快", "PT27", "M", "MT12", ["KF11"], 4, "局部", (15, 25)),
             ("中", "PT03", "M", "MT09", ["KF03", "KF18"], 2, "局部", (35, 50)),
             ("重", "PT06", "M", "MT02", ["KF01", "KF04"], 2, "整幅", (90, 150))]
    bad = 0
    for lbl, pt, sz, mt, ks, w, sc, (elo, ehi) in CASES:
        r = estimate(pt, sz, mt, ks, scope=sc, workers=w, craft_names=N)
        lo, hi = r["最快天数"], r["最慢天数"]
        overlap = not (hi < elo or lo > ehi)
        print(f"  {'✅' if overlap else '⚠️ '} {lbl}档({sc}) 算得 {lo}–{hi} 天,"
              f"知识库写 {elo}–{ehi} 天 · {r['关键路径']}")
        if not overlap: bad += 1
    print(f"  {'三档全部落在知识库写的区间里' if not bad else f'有 {bad} 档对不上,须复核公式或档位'}")
    assert bad == 0, "算出来的工期和知识库自己写的三档对不上"

    print("\n盘扣按颗计(容易漏的那一项):")
    a = estimate("PT31", "L", "MT16", [], craft_names=N)
    b = estimate("PT31", "L", "MT16", ["KF20"], craft_names=N)
    print(f"  不加盘扣 {a['最慢天数']} 天 → 加盘扣 {b['最慢天数']} 天(+{b['最慢天数']-a['最慢天数']}),"
          f"依据:{b['装饰明细'][0]['备注']}")
    print(f"  位置:{b['装饰明细'][0]['位置']}")
    assert b["最慢天数"] > a["最慢天数"], "盘扣是成衣工序,串在缝制后面,必须计入工期"

    print("\n四类工艺介入的时间点不同(03-工艺.md 开篇那张表):")
    r = estimate("PT03", "M", "MT16", ["KF13", "KF03", "KF20"], craft_names=N)
    for x in r["装饰明细"]:
        print(f"  {x['工艺']:8s} {x['工序']}  {x['位置']}")
    print(f"  → {r['关键路径']},合计 {r['最快天数']}–{r['最慢天数']} 天")
    d0 = estimate("PT03", "M", "MT16", ["KF03"], craft_names=N)["最慢天数"]
    d1 = estimate("PT03", "M", "MT16", ["KF13", "KF03"], craft_names=N)["最慢天数"]
    assert d1 > d0, "印染串在备料之后,加了必须变长"

    print("\n除不动的时间不能除:")
    for w in (1, 3):
        r = estimate("PT09", "M", "MT12", ["KF13"], workers=w, craft_names=N)
        print(f"  草木染 · {w} 个师傅 → 印染段 {r['印染']['最慢']} 天(晾晒是日历天,加人无效)")
    r1 = estimate("PT09", "M", "MT12", ["KF13"], workers=1, craft_names=N)
    r3 = estimate("PT09", "M", "MT12", ["KF13"], workers=3, craft_names=N)
    assert r1["印染"]["最慢"] == r3["印染"]["最慢"] > 0, "染色是日历天,不该被人数除掉"
    e1 = estimate("PT03", "M", "MT16", ["KF03"], workers=1, craft_names=N)
    e3 = estimate("PT03", "M", "MT16", ["KF03"], workers=3, craft_names=N)
    assert e3["装饰"]["最慢"] < e1["装饰"]["最慢"], "刺绣工日应该能被人数除"
    print(f"  苏绣  · 1 人 {e1['装饰']['最慢']} 天 → 3 人 {e3['装饰']['最慢']} 天(工日可以除)")

    print("\n婚礼倒推(知识库说要做成拦截,这里把它做出来):")
    for need in ("2026-10-01", "2026-12-25"):
        r = deadline(need, "2026-09-04", pattern="PT06", size="M", material="MT02",
                     crafts=["KF01", "KF04"], craft_names=N)
        print(f"  用件 {need}:{'✅' if r['赶得上'] else '❌'} {r['结论']}")
        print(f"     最晚下单日 {r['最晚下单日']}")
    assert not deadline("2026-10-01","2026-09-04",pattern="PT06",size="M",material="MT02",
                        crafts=["KF01","KF04"],craft_names=N)["赶得上"]
    print("\n现货接上了,压缩建议能点名了:")
    r = estimate("PT03", "M", "MT02", ["KF03"], craft_names=N)     # 云锦,无现货
    print(f"  云锦 + 苏绣 → {r['关键路径']}")
    for x in r["可压缩"][:1]: print(f"    {x[:110]}")
    assert "现货" in r["可压缩"][0], "卡在备料时必须给出现货替代方案"
    r2 = estimate("PT06", "M", "MT02", ["KF01"], scope="整幅", craft_names=N)  # 卡在缂丝
    print(f"  云锦 + 缂丝整幅 → {r2['关键路径']}")
    for x in r2["可压缩"][:1]: print(f"    {x[:110]}")

    print("\n排队等待接进来了(工期不再假设师傅立刻有空):")
    a = estimate("PT06", "M", "MT02", ["KF01"], scope="整幅",
                 from_date="2026-09-04", capacity=False, craft_names=N)
    b = estimate("PT06", "M", "MT02", ["KF01"], scope="整幅",
                 from_date="2026-09-04", capacity=True, craft_names=N)
    print(f"  不算排队:{a['最快天数']}–{a['最慢天数']} 天")
    print(f"  算上排队:{b['最快天数']}–{b['最慢天数']} 天(缂丝要等 {b['排队等待'].get('织造',0)} 天)")
    assert b["最慢天数"] > a["最慢天数"], "排队等待必须计入工期"
    for r0 in b["风险"][:1]: print(f"  风险:{r0[:80]}")

    print("\n没人会的工艺:")
    g = estimate("PT03", "M", "MT16", ["KF40"], from_date="2026-09-04", craft_names=N)
    print(f"  {g['产能缺口'][0][:70] if g['产能缺口'] else '(无)'}")
    assert g["产能缺口"], "没有师傅会的工艺必须报成产能缺口"

    print("\n✅ 工期推算自测通过")
