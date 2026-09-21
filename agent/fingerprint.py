#!/usr/bin/env python3
"""评测指纹 —— 让「分数变了」这件事**可归因**。

## 为什么要有

这周真实发生的一次:工艺顾问 20 题从 20/20 掉到 17/20。手上只有分数,
分不清是五种原因里的哪一种 —— 提示词改了 / 模型换了 / 判分器改了 /
种子数据重建了 / 就是噪声。**这五种对应五套完全不同的改法。**
最后是靠三轮消融(每个变体跑三遍)才排除掉,花的时间远超记指纹的成本。

拆 Accio 时看到它的 `intent-plan-telemetry.js` 写着同一件事:

> 上线后如果只看到「intent plan 还是很少」,无法区分五种完全不同的原因……
> 这五种对应五套不同的改法,靠观察一个指标区分不了。
> 所以先把候选漏斗打出来,再决定要不要做闭环。

**先能归因,再谈优化。** 这个模块只做归因,不改任何执行行为。

## 四个指纹

  提示词  装配后的正文 + 装上的规则编号 —— 改一个字都会变
  判分器  评测脚本的源码 —— 判据松紧变了就会变
  题目    题号 + 题面 —— 换题当然会影响分数,得和判分器分开记
  数据    被测数据的行数与聚合 —— 重建种子会变

模型和供应商直接记原文,不用哈希。

用法:
    python3 agent/fingerprint.py                 # 打印当前四个指纹
    python3 agent/fingerprint.py 归因 A.jsonl B.jsonl   # 比两次评测,说哪一维变了
"""
import hashlib, json, os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend")]

def _h(x):
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)
                          .encode("utf-8")).hexdigest()[:12]

def prompt_fp(role, have):
    import prompts
    txt, ids = prompts.assemble(role, have)
    return {"hash": _h(txt), "rules": ids, "chars": len(txt)}

def source_fp(*paths):
    """源码指纹。**不剥注释** —— 注释改了不影响行为,但也不该悄悄变;
    宁可多报一次「判分器变了」,也不要漏报一次真的改动。"""
    return _h([open(p, encoding="utf-8").read() for p in paths])

def cases_fp(cases):
    return {"hash": _h([(c["id"], c["q"]) for c in cases]), "n": len(cases)}

# 被测数据里真正会影响答案的那几张表。加表要有理由 ——
# 记太多会让指纹对无关改动敏感,报一堆假的「数据变了」。
_TABLES = ["craft", "craft_combo", "kb_table", "material", "pattern",
           "measure_rec", "wearer", "account", "maintain", "ordr"]

def _table_fp(c, t):
    """一张表的**内容**指纹,不只是行数。

    2026-09-20 外部审阅指出:原来这里只取 `COUNT(*)`。
    **行数没变、内容改了,指纹一模一样** —— 而那恰恰是评测分数最常见的
    那一类数据改动:一条工艺描述改了两个字、一个量体值订正了、
    一张单的状态被回填了。行数一个都不会动。

    🔑 这两种情况在 COUNT 上长得一样,可下一步该查的东西正好相反:

        数据真没变   → 去查提示词、判分器、模型,或者认成噪声
        数据改了     → 去查数据,前面那几维都别动

    归因工具报错方向的代价,比不做归因更大 —— 它会让人**朝着反方向找**。

    ⚠️ 按 rowid 排序取:不加 ORDER BY 的 SELECT 不保证顺序,
    那样同一份数据可能算出两个哈希,**变成一个会误报的检查**。
    """
    try:
        cur = c.execute(f"SELECT * FROM {t} ORDER BY rowid")
        rows = cur.fetchall()
    except sqlite3.Error:
        # WITHOUT ROWID 的表没有 rowid。不能退回「不排序」——
        # 那等于用顺序的偶然稳定冒充确定性。按行内容自己排,慢一点但是定的。
        cur = c.execute(f"SELECT * FROM {t}")
        rows = sorted(cur.fetchall(), key=lambda r: json.dumps(r, default=str, sort_keys=True))
    cols = [d[0] for d in cur.description]
    h = hashlib.sha256()
    h.update(("\x1f".join(cols)).encode("utf-8"))   # 加一列、改列名也算变
    for row in rows:
        h.update(json.dumps(row, ensure_ascii=False, default=str).encode("utf-8"))
        h.update(b"\x1e")
    return len(rows), h.hexdigest()[:12]


def data_fp(db=None, tables=None):
    db = db or os.path.join(ROOT, "backend", "lanxiu.db")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    counts, 内容 = {}, {}
    for t in (tables or _TABLES):
        try:
            counts[t], 内容[t] = _table_fp(c, t)
        except sqlite3.Error:
            # 表不存在和表是空的,**在 counts 里都会是个不吓人的值** ——
            # 所以缺表记 None,空表记 0,两者不许混成一个。
            counts[t], 内容[t] = None, None
    c.close()
    return {"hash": _h([counts, 内容]), "counts": counts, "内容": 内容}

def snapshot(role="kb", have=None, judge_src=(), cases=None, model=None, provider=None):
    import api
    have = have or {t["name"] for t in api.KB_SCHEMAS}
    # 模型和供应商永远一起动 —— 拆成两维会把一次改动报成「同时变了 2 维,归不了因」。
    # **维度要按「能不能单独改」来切,不是按字段数。**
    s = {"提示词": prompt_fp(role, have), "数据": data_fp(),
         "模型": f"{provider or '默认'} / {model or '?'}"}
    if judge_src: s["判分器"] = source_fp(*judge_src)
    if cases is not None: s["题目"] = cases_fp(cases)
    return s


# ── 归因 ────────────────────────────────────────────────────────────
# **单跑一遍的差值不构成结论。** 消融里实测过:同一份提示词、同一个模型,
# 6 道负向题两次跑分差 2。所以低于噪声阈值的分差只能说「测不出来」。
NOISE = {"负向": 2, "正向": 1}

def attribute(a, b):
    """a、b 是两个结果文件(jsonl)。返回人话的归因结论。"""
    def load(p):
        recs = [json.loads(l) for l in open(p, encoding="utf-8")]
        head = next((r for r in recs if r.get("_fingerprint")), None)
        rows = [r for r in recs if not r.get("_fingerprint")]
        return head, rows
    ha, ra = load(a); hb, rb = load(b)
    out = []
    不可比 = []   # 「这一维比不了」既不是「变了」也不是「没变」,得单独有个地方放
    sa, sb = sum(r.get("passed") for r in ra), sum(r.get("passed") for r in rb)
    out.append(f"分数:{sa}/{len(ra)}  →  {sb}/{len(rb)}   差 {sb-sa:+d}")
    if not ha or not hb:
        out.append("⚠ 至少一份结果没有指纹(是加指纹之前跑的),**无法归因** —— "
                   "这正是要记指纹的理由。")
        return out
    fa, fb = ha["_fingerprint"], hb["_fingerprint"]
    changed = []
    for k in ("提示词", "判分器", "题目", "数据", "模型"):
        va, vb = fa.get(k), fb.get(k)
        if va == vb: continue
        changed.append(k)
        if k == "提示词":
            ida, idb = set(va.get("rules") or []), set(vb.get("rules") or [])
            d = (f"规则 +{sorted(idb-ida)} −{sorted(ida-idb)}" if ida != idb
                 else f"规则没变,正文变了({va.get('chars')} → {vb.get('chars')} 字)")
            out.append(f"  ✗ 提示词变了 —— {d}")
        elif k == "数据":
            ca, cb = va.get("counts") or {}, vb.get("counts") or {}
            na, nb = va.get("内容"), vb.get("内容")
            if na is None or nb is None:
                # 一边是加内容指纹之前跑的。**「比不了」不许说成「变了」** ——
                # 说「变了」会把人支去查数据,而实际上根本不知道数据动没动。
                changed.remove(k); 不可比.append(k)
                out.append("  ? 数据这一维**比不了** —— 有一份是 2026-09-21 加内容指纹"
                           "之前跑的,那时候只记了行数。重跑一次才有得比。")
                continue
            行 = [f"{t}:{ca.get(t)}→{cb.get(t)}" for t in ca if ca.get(t) != cb.get(t)]
            改 = [t for t in (na or {}) if t in (nb or {}) and na[t] != nb[t] and ca.get(t) == cb.get(t)]
            说 = 行 + ([f"{'、'.join(改)} 行数没变但内容改了"] if 改 else [])
            out.append(f"  ✗ 数据变了 —— {', '.join(说) or '(说不出是哪张表)'}")
        else:
            out.append(f"  ✗ {k}变了 —— {va} → {vb}")
    for k in ("提示词", "判分器", "题目", "数据", "模型"):
        if k not in changed and k in fa: out.append(f"  ✓ {k}没变")
    out.append("")
    if 不可比 and not changed:
        # ⚠️ 不能说「全都没变所以是噪声」——**「没变」和「不知道变没变」不是一回事**,
        # 说成前者会让人把一次真实的数据改动记成噪声,然后再也不查了。
        out.append(f"**其余几维都没变,但「{'、'.join(不可比)}」这一维比不了 —— 归不了因。**\n"
                   f"  分差 {sb-sa:+d} 现在还不能算到噪声头上。把两次都用现在的代码重跑一遍才有结论。")
    elif not changed:
        thr = max(NOISE.values())
        out.append(f"**四维全都没变,分差 {sb-sa:+d} 只能是噪声或模型自身随机性。**"
                   + (f"(噪声阈值 ±{thr},这个差值在阈值内)" if abs(sb-sa) <= thr
                      else f"(超过噪声阈值 ±{thr},值得重复跑几遍确认)"))
    elif len(changed) == 1 and not 不可比:
        out.append(f"**只有「{changed[0]}」这一维变了** —— 分差可以归到它头上,"
                   "但仍要确认差值超过噪声阈值。")
    elif 不可比:
        out.append(f"**变了 {len(changed)} 维({'、'.join(changed)}),另有 {len(不可比)} 维比不了 —— 归不了因。**")
    else:
        out.append(f"**同时变了 {len(changed)} 维({'、'.join(changed)})—— 归不了因。**\n"
                   "  一次只动一维,这是评测能说明问题的前提。")
    return out


# ── 自测 ────────────────────────────────────────────────────────────
# **指纹是用来归因的,它自己报错方向比不报更糟** —— 它会让人朝反方向找。
# 所以这几条不是「测一下有没有崩」,而是钉住「什么必须让指纹变、什么必须不变」。
def selftest():
    import tempfile, shutil
    G, R, D = "\033[32m", "\033[31m", "\033[0m"
    bad = []
    d = tempfile.mkdtemp(prefix="fp-")
    try:
        db = os.path.join(d, "t.db")
        def 建(值):
            if os.path.exists(db): os.remove(db)
            c = sqlite3.connect(db)
            c.execute("CREATE TABLE craft(id INTEGER PRIMARY KEY, name TEXT, note TEXT)")
            c.executemany("INSERT INTO craft VALUES(?,?,?)", 值); c.commit(); c.close()
        基 = [(1, "盘扣", "手工"), (2, "缂丝", "通经断纬"), (3, "苏绣", "双面")]
        建(基); a = data_fp(db, ["craft"])
        建(基); b = data_fp(db, ["craft"])
        if a["hash"] != b["hash"]:
            bad.append("同一份数据算两次,指纹不一样 —— **那它会天天误报「数据变了」**")

        # 🔑 就是这一条:**行数不变,内容改了**。原来只数 COUNT(*),这里一定漏。
        建([(1, "盘扣", "手工"), (2, "缂丝", "通经断纬!改了两个字"), (3, "苏绣", "双面")])
        if data_fp(db, ["craft"])["hash"] == a["hash"]:
            bad.append("改了一个字段的值(行数没变),指纹居然一样 —— **归因会说「数据没变」**")

        建(基 + [(4, "打籽绣", "颗粒")])
        if data_fp(db, ["craft"])["hash"] == a["hash"]:
            bad.append("加了一行,指纹一样")

        建(基)
        c = sqlite3.connect(db); c.execute("ALTER TABLE craft RENAME COLUMN note TO memo")
        c.commit(); c.close()
        if data_fp(db, ["craft"])["hash"] == a["hash"]:
            bad.append("列改名了,指纹一样 —— 同样的值换了含义,下游读出来的东西会变")

        # **「表不存在」和「表是空的」必须分得开** —— 两者该做的事相反:
        # 前者是库没建全(去看首次启动那条路),后者是真的没数据。
        建([])
        空 = data_fp(db, ["craft", "根本没有这张表"])
        if 空["counts"]["craft"] != 0:
            bad.append("空表没记成 0")
        if 空["counts"]["根本没有这张表"] is not None:
            bad.append("缺的表没记成 None —— 它会和空表混成一个")

        # 归因:一边是加内容指纹之前跑的 → 必须说「比不了」,不许说「没变」也不许说「变了」
        老 = {"提示词": {"hash": "x", "rules": [], "chars": 1}, "模型": "m",
              "数据": {"hash": "old", "counts": {"craft": 3}}}
        新 = {"提示词": {"hash": "x", "rules": [], "chars": 1}, "模型": "m",
              "数据": data_fp(db, ["craft"])}
        f1, f2 = os.path.join(d, "a.jsonl"), os.path.join(d, "b.jsonl")
        for f, fp in ((f1, 老), (f2, 新)):
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"_fingerprint": fp}, ensure_ascii=False) + "\n")
                fh.write(json.dumps({"id": 1, "passed": 1}, ensure_ascii=False) + "\n")
        文 = "\n".join(attribute(f1, f2))
        if "比不了" not in 文:
            bad.append("和加内容指纹之前的结果比,没说「比不了」")
        if "只能是噪声" in 文 or "数据变了" in 文:
            bad.append("和加内容指纹之前的结果比,居然给了结论 —— **「不知道」被说成了「没变」或「变了」**")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if bad:
        print(f"{R}❌ 指纹自测 {len(bad)} 条不过{D}")
        for b in bad: print(f"    ❌ {b}")
        return 1
    print(f"{G}✅ 指纹自测 7 条全过 —— 行数没变但内容改了,指纹也会变{D}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    if len(sys.argv) > 1 and sys.argv[1] == "归因":
        for l in attribute(sys.argv[2], sys.argv[3]): print(l)
    else:
        import api
        s = snapshot(judge_src=(os.path.join(HERE, "chat_eval.py"),))
        print(json.dumps(s, ensure_ascii=False, indent=2))
