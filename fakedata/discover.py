#!/usr/bin/env python3
"""推断层 —— 把 schema **没说**的事挖出来。

## 这一层解决的问题

反射层跑完,澜绣云裳这个库给出的答案是:58 张表,**0 个外键**。
一个纯 schema 驱动的造数工具(SQLAlchemy + Faker 那条路)看到的就是这个 ——
于是它会造出 58 堆互不相干的孤儿数据,看着有数据,一个 join 都跑不通。

真实业务库长的就是这样。所以关系必须**挖**出来,而不是读出来。

## 怎么挖:命名靠不住,值重叠才靠得住

两种线索,单用哪个都会翻车:

  · **命名**:`ordr_item.ordr_id → ordr`。快,但误报多 ——
    `customer.shop` 看起来该指向 shop 表,也可能只是个门店名字符串。
  · **值重叠**:采样这一列的去重值,看是不是另一张表主键的**子集**。
    准,但单用会误报 —— `archived` 只有 0/1,而某张表的主键正好也有 0 和 1。

所以两个一起用:值重叠做**判定**,命名做**加分和消歧**(一列同时像指向两张表时,名字说了算)。

## 一个实现上的关键选择:先建索引,再逐列比

朴素写法是「每列 × 每张表」各跑一次 SQL 去比,566 列 × 58 表 = 三万多次查询。
这里改成:先把 58 张表的主键值各读一次进内存(58 次查询),
再把每列的采样值读一次(566 次查询),**比对全在内存里做**。
查询数从三万降到六百,而且顺带能发现**命名上毫无线索**的关系 ——
朴素写法为了省查询必须先用命名筛候选,于是永远发现不了它们。

## 空表怎么办

推断的原料是**数据**。一张空表什么也挖不出来。
这不是 bug,是这个方法的边界:所以每条结论都带 `confidence`,
空表上的结论只能来自命名,标成「低」。要它变高,得给一个有数据的库当样本源
—— 开发库、预发库都行,但**只读结构和聚合,不读行**(见 guard.py)。
"""
import os, re, sys, json, collections

SAMPLE   = 800    # 每列采样多少个去重值
KEYCAP   = 60000  # 每张表最多读多少主键值进内存
MIN_OVER = 0.90   # 值重叠判定阈值

# ---------- 语义类型:列名线索 ----------
NAME_HINTS = [
    (r"(^|_)(phone|mobile|tel)(_|$)",            "cn_mobile"),
    (r"(^|_)(email|mail)(_|$)",                  "email"),
    (r"(^|_)(name|display_name|nick)(_|$)",      "cn_name"),
    (r"(amount|price|fee|cost|paid|money|sum|total)", "money"),
    (r"(^|_)(province)(_|$)",                    "province"),
    (r"(^|_)(city)(_|$)",                        "city"),
    (r"(^|_)(district)(_|$)",                    "district"),
    (r"(addr|address)",                          "address"),
    (r"(^|_)(birthday|birth|dob)(_|$)",          "date"),
    (r"(_at$|_time$|created|updated|^ts$)",      "datetime"),
    (r"(_date$|^date$|^day$)",                   "date"),
    (r"(remark|note|desc|comment|content)",      "long_text"),
    (r"(^|_)(cnt|count|qty|num)(_|$)",           "small_int"),
    (r"(^|_)(rate|ratio|pct|percent)(_|$)",      "percent"),
]
# ---------- 语义类型:值形状线索(比列名可靠,优先) ----------
VALUE_SHAPES = [
    (re.compile(r"^1[3-9]\d{9}$"),                        "cn_mobile"),
    (re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I),   "email"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"),                  "date"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"),    "datetime"),
    (re.compile(r"^(https?://|/)\S+$"),                   "url"),
    (re.compile(r"^[\[{].*[\]}]$", re.S),                 "json"),
    (re.compile(r"^[A-Z]{1,8}[-_]?\d{3,}$"),              "coded_id"),
]

def _shape(vals):
    """值形状要**压倒性一致**才认(≥90%),不然一列自由文本里混进两个日期就被判成日期列。"""
    strs = [str(v) for v in vals if v is not None and str(v) != ""]
    if len(strs) < 3: return None
    for rx, kind in VALUE_SHAPES:
        if sum(1 for s in strs if rx.match(s)) / len(strs) >= 0.9: return kind
    return None

def _name_hint(col):
    for rx, kind in NAME_HINTS:
        if re.search(rx, col.lower()): return kind
    return None

def _pct(sorted_nums, p):
    if not sorted_nums: return None
    i = min(len(sorted_nums) - 1, int(round(p * (len(sorted_nums) - 1))))
    return sorted_nums[i]


def _key_index(conn, schema):
    """把每张表「可以被别人引用的值」读进内存:主键 + 单列唯一键。

    为什么唯一键也算:`customer.shop` 存的很可能是门店**名字**而不是 id。
    只认主键的话,这类关系一条都挖不出来。
    """
    idx = {}
    for t in schema.tables.values():
        keycols = list(t.pk) + [c.name for c in t.columns if c.unique and c.name not in t.pk]
        for kc in keycols:
            try:
                vals = {r[0] for r in conn.q(
                    f"select {conn.ident(kc)} from {conn.ident(t.name)} "
                    f"where {conn.ident(kc)} is not null limit {KEYCAP}")}
            except Exception:
                continue
            if len(vals) < 2: continue
            ints = [v for v in vals if isinstance(v, int) and not isinstance(v, bool)]
            dense = (len(ints) == len(vals) and len(vals) >= 5
                     and (max(ints) - min(ints) + 1) <= len(vals) * 1.5)
            idx[(t.name, kc)] = {"vals": vals, "dense_int": dense,
                                 "n": len(vals), "max": max(ints) if ints else None}
    return idx


def _sample(conn, t, c):
    try:
        return [r[0] for r in conn.q(
            f"select distinct {conn.ident(c.name)} from {conn.ident(t.name)} "
            f"where {conn.ident(c.name)} is not null limit {SAMPLE}")]
    except Exception:
        return []


def _fk_candidates(tname, col, vals, keyidx):
    """值重叠判定 + 命名加分。返回按分数排序的候选。"""
    if len(vals) < 3: return []
    vs = set(vals)
    out = []
    for (ktab, kcol), meta in keyidx.items():
        keys = meta["vals"]
        if ktab == tname and kcol == col: continue          # 自己指自己那一列,无意义
        hit = len(vs & keys)
        over = hit / len(vs)
        if over < MIN_OVER: continue
        # 命名线索:列名里出现目标表名(ordr_id→ordr / shop→shop),或列名==目标键名
        cl, kt = col.lower(), ktab.lower()
        named = (kt in cl) or (cl.rstrip("_id") == kt) or (cl == kcol.lower() and kcol != "id")
        # ---- 反误报三条 ----
        # (a) 值太少,可能是枚举/布尔碰巧撞上
        if not named and len(vs) < 5: continue
        if not named and all(isinstance(v, int) and 0 <= v <= 3 for v in vs): continue
        # (b) **自增整数主键是小整数的天然超集**。
        #     `tpl_item.sort` 的值是 1,2,3...,而 `measure_rec.id` 也是 1..N ——
        #     重叠 100%,却毫无关系。这不是阈值调得不够高能解决的:
        #     排序号、数量、库存、工期天数,值域天生落在任何自增主键里面。
        #     所以对稠密整数键:**没有命名线索就一律不认**。
        if meta["dense_int"] and not named: continue
        # (c) 即使有命名线索,小整数指向大表也要打折 ——
        #     真外键的取值会散布在父表键域里,不会全挤在最前面几个。
        if meta["dense_int"] and meta["max"] and meta["n"] >= 50:
            cmax = max((v for v in vs if isinstance(v, int)), default=0)
            if cmax < meta["max"] * 0.1: continue
        out.append({"table": ktab, "column": kcol, "overlap": round(over, 3),
                    "named": named, "score": round(over + (0.5 if named else 0)
                                                   + min(len(keys), 5000) / 100000, 4)})
    return sorted(out, key=lambda d: -d["score"])


def _shape_of_fk(conn, child, ccol, parent, pcol):
    """引用密度 —— 「一个父亲平均几个孩子」的**形状**,不是平均数。

    为什么形状比总量重要:只有形状对了,才测得出
      · N+1 查询(重度用户页面会不会慢)
      · 空状态(零订单用户的页面长什么样)
      · 分页(50+ 条会不会翻页错)
    均匀分布的假数据,这三类问题一个都测不出来 —— 而它们恰恰是线上最常见的三类。
    """
    try:
        per = [r[0] for r in conn.q(
            f"select count(*) from {conn.ident(child)} "
            f"where {conn.ident(ccol)} is not null group by {conn.ident(ccol)}")]
        total_parents = conn.q(f"select count(distinct {conn.ident(pcol)}) "
                               f"from {conn.ident(parent)}")[0][0]
    except Exception:
        return None
    zero = max(0, total_parents - len(per))
    buckets = {"0": zero, "1-3": 0, "4-10": 0, "11-50": 0, "50+": 0}
    for n in per:
        k = "1-3" if n <= 3 else "4-10" if n <= 10 else "11-50" if n <= 50 else "50+"
        buckets[k] += 1
    tot = sum(buckets.values()) or 1
    return {k: round(v / tot, 3) for k, v in buckets.items()}


def discover(conn, schema, tables=None, verbose=False):
    """返回「观察到的事实」——不是方案,是造方案的原料。"""
    keyidx = _key_index(conn, schema)
    names = tables or sorted(schema.tables)
    facts = {"source": schema.label, "dialect": schema.dialect, "tables": {}}

    for tn in names:
        t = schema.tables[tn]
        tf = {"rows": t.rows, "pk": t.pk, "columns": {}, "fks": []}
        for c in t.columns:
            vals = _sample(conn, t, c) if t.rows else []
            try:
                nulls = conn.q(f"select count(*) from {conn.ident(tn)} "
                               f"where {conn.ident(c.name)} is null")[0][0] if t.rows else 0
            except Exception:
                nulls = 0
            cf = {"type": c.type_raw, "kind": c.kind, "nullable": c.nullable,
                  "pk": c.pk, "unique": c.unique, "comment": c.comment,
                  "distinct": len(vals),
                  "null_rate": round(nulls / t.rows, 3) if t.rows else None,
                  "confidence": "高" if t.rows >= 20 else "中" if t.rows else "低"}

            # 语义类型:值形状 > 列名 > 类型
            cf["semantic"] = _shape(vals) or _name_hint(c.name) or c.kind

            # 枚举:取值少、占比低,才算枚举而不是自由文本
            # 日期不能当枚举。小表上「去重值 ≤ 24 且占比低」这条对日期列也成立,
            # 于是 `created` 被判成枚举,生成时从旧值里随机抽 —— 时间线全乱。
            # 判据本身没错,错在**没有排除已经认出语义的列**:
            # 形状认出来是日期,就不该再让一条统计规则把它盖掉。
            if cf["semantic"] not in ("date", "datetime") \
               and c.kind in ("text", "int") and t.rows >= 10 and 1 < len(vals) <= 24 \
               and len(vals) / max(t.rows, 1) <= 0.3 and not c.unique:
                freq = dict(conn.q(
                    f"select {conn.ident(c.name)}, count(*) from {conn.ident(tn)} "
                    f"where {conn.ident(c.name)} is not null "
                    f"group by 1 order by 2 desc limit 24"))
                s = sum(freq.values()) or 1
                cf["semantic"] = "enum"
                cf["enum"] = {str(k): round(v / s, 3) for k, v in freq.items()}

            # 数值分布:分位数,不是平均值 —— 金额是长尾,平均值骗人
            if c.kind in ("int", "real") and vals:
                nums = sorted(v for v in vals if isinstance(v, (int, float)))
                if nums:
                    cf["range"] = {"min": nums[0], "p50": _pct(nums, .5),
                                   "p90": _pct(nums, .9), "max": nums[-1]}
            # 日期/时间也要量范围 —— 否则生日会被造在最近两年,
            # 一个「儿童成长推算」功能拿这种数据测,等于没测。
            # 这是「结构像」和「分布像」的分界:类型对不等于值域对。
            if cf["semantic"] in ("date", "datetime") and vals:
                ss = sorted(str(v) for v in vals if v)
                if ss: cf["range"] = {"min": ss[0], "max": ss[-1]}
            # 文本长度:UI 撑不撑得爆,看的是 max 不是 p50
            if c.kind == "text" and vals:
                ls = sorted(len(str(v)) for v in vals)
                cf["len"] = {"p50": _pct(ls, .5), "max": ls[-1]}

            tf["columns"][c.name] = cf

            # 外键:先认库里明写的,没有再挖
            declared = [(fc, ft, fcol) for fc, ft, fcol in t.declared_fks if fc == c.name]
            if declared:
                _, ft, fcol = declared[0]
                tf["fks"].append({"column": c.name, "table": ft, "column_ref": fcol,
                                  "source": "明写", "overlap": 1.0, "confidence": "高"})
                cf["semantic"] = "fk"
            elif not c.pk and vals:
                cands = _fk_candidates(tn, c.name, vals, keyidx)
                if cands:
                    best = cands[0]
                    tf["fks"].append({
                        "column": c.name, "table": best["table"], "column_ref": best["column"],
                        "source": "命名+值重叠" if best["named"] else "值重叠",
                        "overlap": best["overlap"],
                        "confidence": "高" if best["named"] and best["overlap"] >= 0.99
                                      else "中" if best["named"] or best["overlap"] >= 0.99 else "低",
                        "alternatives": [f'{a["table"]}.{a["column"]}' for a in cands[1:3]]})
                    # 外键列上的枚举事实必须清掉。它是在认出外键**之前**统计的,
                    # 留着会派生出「只能取这 13 个已知值」的断言 ——
                    # 而外键的合法取值是父表的**全部**主键,不是采样时碰巧见过的那几个。
                    # 一条过时的事实,比没有事实更坏:它会伪装成检查失败。
                    cf["semantic"] = "fk"; cf.pop("enum", None)
        facts["tables"][tn] = tf

    # 形状:只给高/中可信度的外键算,低可信度的不值得为它多跑查询
    for tn, tf in facts["tables"].items():
        for fk in tf["fks"]:
            if fk["confidence"] != "低":
                sh = _shape_of_fk(conn, tn, fk["column"], fk["table"], fk["column_ref"])
                if sh: fk["shape"] = sh
    return facts


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import schema as S
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tgt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "backend", "lanxiu.db")
    conn = S.connect(tgt); sc = conn.reflect()
    f = discover(conn, sc)
    fks = [(t, k) for t, tf in f["tables"].items() for k in tf["fks"]]
    print(f'{f["source"]}: 明写外键 0 个 → 挖出 {len(fks)} 条表关系')
    for lvl in ("高", "中", "低"):
        n = sum(1 for _t, k in fks if k["confidence"] == lvl)
        print(f"  可信度{lvl}: {n}")
    print("\n=== 抽 12 条看看 ===")
    for t, k in sorted(fks, key=lambda x: -{"高": 3, "中": 2, "低": 1}[x[1]["confidence"]])[:12]:
        sh = k.get("shape")
        shs = ("  形状 " + " ".join(f'{a}:{b:.0%}' for a, b in sh.items() if b)) if sh else ""
        print(f'  [{k["confidence"]}] {t}.{k["column"]} → {k["table"]}.{k["column_ref"]}'
              f'  重叠{k["overlap"]:.0%} ({k["source"]}){shs}')
