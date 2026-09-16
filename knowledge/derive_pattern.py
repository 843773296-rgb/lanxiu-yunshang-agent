#!/usr/bin/env python3
"""版型库 + BOM 库 —— 从 10-版型库.md / 11-物料与BOM.md 解析,推出尺码表与物料清单。

和相容矩阵一个套路:**md 里只写基码和规则,别的推出来。**
写死的表改一处只对一处,写下来的规则改一处对全部。

这里推两样东西:
  1. 推档 —— 12 个版型 × 各自尺码 × 各部位成衣尺寸
  2. 算料 —— 版型 + 尺码 + 面料 + 所选工艺 → 完整物料清单与成本
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MD_PT = os.path.join(HERE, "10-版型库.md")
MD_BOM = os.path.join(HERE, "11-物料与BOM.md")
SIZE_NO = {"S": -1, "M": 0, "均码": 0, "L": 1, "XL": 2}
BASE_WIDTH = 114.0          # 版型的基础用布按这个幅宽标定
PACKAGING = ["WL17", "WL18", "WL19", "WL20"]


_CACHE = {}


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('从库里删掉一种工艺(推导出来的 BOM 引用一个不存在的工艺)',
     '与 craft / measure_tpl 对不上'),
]

def _memo(fn):
    """md 只读一次、只解析一次。

    seed 时要给两百多个商品算 BOM 定价,每次重读并重新解析两个 md 文件会慢到不可接受。
    这些函数都是**纯函数**(输入只有 md 文件),缓存是安全的;
    md 改了要重新跑进程 —— 而 seed 本来就是一次性进程。
    """
    def wrap(*a):
        k = (fn.__name__, a)
        if k not in _CACHE: _CACHE[k] = fn(*a)
        return _CACHE[k]
    wrap.__name__ = fn.__name__
    wrap.__doc__ = fn.__doc__
    return wrap


@_memo
def _read(path):
    return open(path, encoding="utf-8").read()


def _tbl(txt, ncol, first):
    """把 md 里以 first 开头、有 ncol 列的表格行切出来"""
    out = []
    for line in txt.split("\n"):
        l = line.strip()
        if not l.startswith("| " + first): continue
        c = [x.strip() for x in l.strip("|").split("|")]
        if len(c) == ncol: out.append(c)
    return out


def _num(x, default=None):
    x = (x or "").replace("%", "").strip()
    if x in ("", "—", "-"): return default
    try: return float(x)
    except ValueError: return default


# ── 一、版型 ────────────────────────────────────────────────────────────
@_memo
def patterns():
    t = _read(MD_PT)
    out = []
    for c in _tbl(t, 10, "PT"):
        out.append(dict(code=c[0], name=c[1], xz=c[2], gender=c[3], tpl=c[4],
                        pieces=int(c[5]), fabric_base=float(c[6]), fabric_step=float(c[7]),
                        sizes=[s.strip() for s in c[8].split(",")], difficulty=c[9].strip("*")))
    return out


@_memo
def pieces():
    t = _read(MD_PT)
    return [dict(pattern=c[0], name=c[1], qty=int(c[2]), note=c[3])
            for c in _tbl(t, 4, "PT") if c[2].isdigit()]


@_memo
def _base_specs():
    t = _read(MD_PT)
    out = {}
    for c in _tbl(t, 3, "PT"):
        v = _num(c[2])
        if v is not None: out.setdefault(c[0], {})[c[1]] = v
    return out


@_memo
def _steps():
    t = _read(MD_PT)
    out = {}
    for line in t.split("\n"):
        m = re.match(r"\|\s*([一-龥]+)\s*\|\s*\+([\d.]+)\s*\|", line.strip())
        if m: out[m.group(1)] = float(m.group(2))
    return out


def size_specs():
    """推档 —— 基码值 + 档差 × 尺码序号。返回 (版型, 尺码, 部位, 值, 仅供参考的理由)

    第五个字段是 2026-09-14 加的。**推得出不等于作数**:
    马面裙的腰围推得出来,但褶位要重排,那一格只是下单参考 ——
    而在表里它和一个能直接用的数**长得一模一样**。
    标不标出来,是「版师看一眼就知道」和「版师得记得有这回事」的差别。

    判据按**裁片结构**取(有褶裥片 ⇒ 腰围只是参考),不按版型编码 ——
    md 里那条特例写的是「PT04 / PT05」,而库里有 5 个马面裙。
    """
    import grading as _g
    base, step, out = _base_specs(), _steps(), []
    片 = {}
    for pc in pieces():
        片.setdefault(pc["pattern"], []).append(pc["name"])
    for p in patterns():
        参考 = _g.参考项(片.get(p["code"], []))
        # **尺码体系认不出来的,整个版型的尺码都标成「推得出但不作数」。**
        # 童款用身高码(110/120/130/140),而 SIZE_NO 里一个都没有 ——
        # 原来 `.get(sz, 0)` 把它们全算成 M,于是四个码推出**同一组数**,
        # 而且没有任何地方会报。`.get(键, 0)` 是最安静的一种失败:
        # 它把「查不到」变成一个看起来完全正常的数。
        体系 = _g.尺码体系未定义(p["sizes"])
        for sz in p["sizes"]:
            n = _g.序号(sz)
            if n is None:
                print(f"⚠ 尺码「{sz}」不在档差序号表里,{p['code']} 只能按基码出 —— "
                      f"已标「仅供参考」", file=sys.stderr)
                n = 0
            for item, v in base.get(p["code"], {}).items():
                d = step.get(item)
                if d is None:
                    print(f"⚠ 「{item}」没有档差规则,{p['code']} 只能按基码出", file=sys.stderr)
                    d = 0
                out.append((p["code"], sz, item, round(v + d * n, 1),
                            参考.get(item) or 体系))
    return out


# ── 二、物料 ────────────────────────────────────────────────────────────
def materials(craft_names=None):
    return _materials(tuple(sorted((craft_names or {}).items())))


@_memo
def _materials(pairs):
    craft_names = dict(pairs)
    """主料的名称从 craft 表来(不在 BOM 文件里重写一遍),辅料在本文件里定义。"""
    t = _read(MD_BOM)
    out = []
    for c in _tbl(t, 5, "MT"):
        nm = (craft_names or {}).get(c[0], c[0])
        out.append(dict(code=c[0], name=nm, cat="主料", spec=f"幅宽 {c[1]}cm",
                        width_cm=float(c[1]), unit="米", price=float(c[2]),
                        loss=_num(c[3]) / 100, lead=int(c[4]), ref_craft=c[0]))
    for c in _tbl(t, 8, "WL"):
        out.append(dict(code=c[0], name=c[1], cat=c[2], spec=c[3], width_cm=None,
                        unit=c[4], price=float(c[5]), loss=_num(c[6]) / 100,
                        lead=int(c[7]), ref_craft=None))
    return out


@_memo
def pattern_bom():
    t = _read(MD_BOM)
    return [dict(pattern=c[0], material=c[1], qty_base=float(c[2]),
                 qty_step=_num(c[3], 0.0), unit=c[4], note=c[5])
            for c in _tbl(t, 6, "PT")]


@_memo
def craft_bom():
    t = _read(MD_BOM)
    return [dict(craft=c[0], material=c[1], qty=float(c[2]), unit=c[3], note=c[4])
            for c in _tbl(t, 5, "KF")]


# ── 三、算料 ────────────────────────────────────────────────────────────
def estimate(pattern_code, size, material_code, craft_codes=(), scope="局部",
             craft_names=None):
    """给一个配置,算出完整物料清单、成本和备料周期。

    这是 BOM 库存在的理由:相容矩阵回答「能不能做」,这里回答「要多少料、多少钱、多久备齐」。
    """
    p = next((x for x in patterns() if x["code"] == pattern_code), None)
    if not p: return {"error": f"没有版型 {pattern_code}"}
    if size not in p["sizes"]:
        return {"error": f"{p['name']} 没有 {size} 码,只有 {'/'.join(p['sizes'])}",
                "note": "尺码不存在不是缺货,是这个版型裁不出来 —— 见 10-版型库.md"}
    mats = {m["code"]: m for m in materials(craft_names)}
    fab = mats.get(material_code)
    if not fab: return {"error": f"没有物料 {material_code}"}
    n = SIZE_NO.get(size, 0)
    lines, warn = [], []

    def add(code, qty, why):
        m = mats.get(code)
        if not m:
            warn.append(f"物料 {code} 不在物料表里,已跳过"); return
        real = round(qty * (1 + m["loss"]), 3)
        lines.append(dict(code=code, name=m["name"], cat=m["cat"], unit=m["unit"],
                          net=round(qty, 3), loss=f"{m['loss']*100:.0f}%", qty=real,
                          price=m["price"], amount=round(real * m["price"], 2),
                          lead=m["lead"], why=why))

    # 主面料:先按尺码推净用量,再按幅宽折算,最后加损耗
    net = p["fabric_base"] + p["fabric_step"] * n
    conv = net * (BASE_WIDTH / fab["width_cm"])
    add(material_code, conv,
        f"{p['name']} {size} 码净用 {net:.2f}m;{fab['name']}幅宽 {fab['width_cm']:.0f}cm,"
        f"折算 {conv:.2f}m" + ("(**幅宽窄,比标定多用 %.0f%%**)" % ((conv/net-1)*100)
                              if conv > net * 1.05 else ""))
    for b in pattern_bom():
        if b["pattern"] != pattern_code: continue
        add(b["material"], b["qty_base"] + b["qty_step"] * n, f"版型固定辅料:{b['note'] or b['material']}")
    mult = 4 if scope == "整幅" else 1
    for kc in craft_codes:
        hit = [x for x in craft_bom() if x["craft"] == kc]
        if not hit: continue
        for x in hit:
            nm = (craft_names or {}).get(kc, kc)
            add(x["material"], x["qty"] * mult, f"工艺 {nm}({scope}){'' if not x['note'] else ':'+x['note']}")
    for w in PACKAGING:
        add(w, 1, "包装")

    total = round(sum(l["amount"] for l in lines), 2)
    return dict(pattern=p["name"], size=size, material=fab["name"], scope=scope,
                lines=lines, 物料成本=total,
                备料天=max((l["lead"] for l in lines), default=0),
                最长备料项=max(lines, key=lambda l: l["lead"])["name"] if lines else None,
                warn=warn,
                note="物料成本不含工时、版房分摊、门店成本与税,**不是报价**")


def craft_names_from_db():
    """主料和工艺的名字从 craft 表取,BOM 文件里只写编码 —— 不让同一个名字存两遍。"""
    db = os.path.join(HERE, "..", "backend", "lanxiu.db")
    if not os.path.exists(db): return {}
    import sqlite3
    return {r[0]: r[1] for r in sqlite3.connect(db).execute("SELECT code,name FROM craft")}


if __name__ == "__main__":
    print("版型库 + BOM 库 · 自测\n" + "=" * 74)
    NAMES = craft_names_from_db()
    ps, pcs, ss = patterns(), pieces(), size_specs()
    ms, pb, cb = materials(NAMES), pattern_bom(), craft_bom()
    print(f"版型 {len(ps)} · 裁片 {len(pcs)} · 推档出尺码尺寸 {len(ss)} 条")
    print(f"物料 {len(ms)}(主料 {sum(1 for m in ms if m['cat']=='主料')} / "
          f"辅料包装 {sum(1 for m in ms if m['cat']!='主料')})"
          f" · 版型用料 {len(pb)} 条 · 工艺附加用料 {len(cb)} 条")

    # 每个版型的每个尺码都要有尺寸,一个都不能少
    need = sum(len(p["sizes"]) * len(_base_specs().get(p["code"], {})) for p in ps)
    assert len(ss) == need, f"推档条数对不上:{len(ss)} vs 应有 {need}"
    # 裁片数要和主数据里写的对上 —— 这是最容易漂的一个数
    cnt = {}
    for x in pcs: cnt[x["pattern"]] = cnt.get(x["pattern"], 0) + x["qty"]
    bad = [(p["code"], p["pieces"], cnt.get(p["code"], 0)) for p in ps
           if cnt.get(p["code"], 0) != p["pieces"]]
    if bad:
        print("\n❌ 裁片数与主数据对不上:")
        for c, a, b in bad: print(f"   {c}  主数据写 {a} 片,裁片表加起来 {b} 片")
        sys.exit(1)
    print("  ✅ 12 个版型的裁片数与主数据一致")
    # BOM 里引用的物料必须存在
    known = {m["code"] for m in ms}
    # 括号不能省:「-」比「|」结合得紧,写成 A|B|C-known 会变成 A|B|(C-known),
    # 检查就空跑了。这个项目在 or/and 上栽过同一类跟头。
    miss = sorted(({b["material"] for b in pb} | {x["material"] for x in cb}
                   | set(PACKAGING)) - known)
    assert not miss, f"BOM 引用了不存在的物料:{miss}"
    print("  ✅ BOM 引用的物料全部存在")

    print("\n同一件马面裙,换面料的差别:")
    print(f"  {'面料':<12s}{'用布':>8s}  {'物料成本':>10s}  备料周期")
    for mc in ("MT12", "MT01", "MT04", "MT02"):
        r = estimate("PT04", "M", mc, ["KF11"], craft_names=NAMES)
        f = r["lines"][0]
        print(f"  {r['material']:<14s}{f['qty']:>6.2f}m  ¥{r['物料成本']:>9.2f}  "
              f"{r['备料天']:>2d}天 · 卡在{r['最长备料项']}")
    print("\n同一件云锦马面裙,换工艺的差别:")
    for kfs, lbl in ((["KF11"], "平绣"), (["KF03"], "苏绣"), (["KF04"], "盘金绣")):
        r = estimate("PT04", "M", "MT02", kfs, craft_names=NAMES)
        print(f"  {lbl:8s} ¥{r['物料成本']:>8.2f}")
    print("\n裁不出来的尺码要说清楚:")
    print("  ", estimate("PT05", "S", "MT12", craft_names=NAMES)["error"])

    # ── 和数据库对账 ──────────────────────────────────────────────────
    db = os.path.join(HERE, "..", "backend", "lanxiu.db")
    if os.path.exists(db):
        import sqlite3
        con = sqlite3.connect(db); con.row_factory = sqlite3.Row
        xz = {r["code"]: r["name"] for r in con.execute("SELECT code,name FROM craft WHERE cat='形制'")}
        mt = {r["code"] for r in con.execute("SELECT code FROM craft WHERE cat='材质'")}
        kf = {r["code"]: r["name"] for r in con.execute("SELECT code,name FROM craft WHERE cat='工艺'")}
        tpl = {r["code"] for r in con.execute("SELECT code FROM measure_tpl")}
        bad = []
        # ① 每个形制都得有版型 —— 没版型就裁不出来,却能在配置页上被选中
        have = {p["xz"] for p in ps}
        for code, nm in xz.items():
            if code not in have: bad.append(f"形制 {code} {nm} 没有任何版型")
        # ② 版型引用的形制和量体模版必须存在
        for p in ps:
            if p["xz"] not in xz: bad.append(f"{p['code']} 引用了不存在的形制 {p['xz']}")
            if p["tpl"] not in tpl: bad.append(f"{p['code']} 引用了不存在的量体模版 {p['tpl']}")
        # ③ 每种面料都得有 BOM 参数,否则算不出料
        for code in sorted(mt):
            if code not in {m["code"] for m in ms}:
                bad.append(f"材质 {code} 没有幅宽/单价/损耗,kb_bom 算不了")
        # ④ 工艺附加用料引用的工艺必须存在
        for x in cb:
            if x["craft"] not in kf: bad.append(f"工艺附加用料引用了不存在的工艺 {x['craft']}")
        print()
        if bad:
            print("❌ 与 craft / measure_tpl 对不上:")
            for b in bad: print("   ", b)
            sys.exit(1)
        covered = {x["craft"] for x in cb}
        print(f"  ✅ {len(xz)} 个形制都有版型 · {len(mt)} 种面料都有 BOM 参数 · "
              f"量体模版引用有效")
        print(f"  工艺附加用料覆盖 {len(covered)}/{len(kf)} 种工艺;"
              f"其余{[kf[k] for k in kf if k not in covered]}只产生工时不产生物料")

    print("\n✅ 版型库与 BOM 库自测通过")
