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

def data_fp(db=None):
    db = db or os.path.join(ROOT, "backend", "lanxiu.db")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = {}
    for t in _TABLES:
        try: out[t] = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        except sqlite3.Error: out[t] = None
    c.close()
    return {"hash": _h(out), "counts": out}

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
            diff = [f"{t}:{ca.get(t)}→{cb.get(t)}" for t in ca if ca.get(t) != cb.get(t)]
            out.append(f"  ✗ 数据变了 —— {', '.join(diff) or '(聚合相同但哈希不同)'}")
        else:
            out.append(f"  ✗ {k}变了 —— {va} → {vb}")
    for k in ("提示词", "判分器", "题目", "数据", "模型"):
        if k not in changed and k in fa: out.append(f"  ✓ {k}没变")
    out.append("")
    if not changed:
        thr = max(NOISE.values())
        out.append(f"**四维全都没变,分差 {sb-sa:+d} 只能是噪声或模型自身随机性。**"
                   + (f"(噪声阈值 ±{thr},这个差值在阈值内)" if abs(sb-sa) <= thr
                      else f"(超过噪声阈值 ±{thr},值得重复跑几遍确认)"))
    elif len(changed) == 1:
        out.append(f"**只有「{changed[0]}」这一维变了** —— 分差可以归到它头上,"
                   "但仍要确认差值超过噪声阈值。")
    else:
        out.append(f"**同时变了 {len(changed)} 维({'、'.join(changed)})—— 归不了因。**\n"
                   "  一次只动一维,这是评测能说明问题的前提。")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "归因":
        for l in attribute(sys.argv[2], sys.argv[3]): print(l)
    else:
        import api
        s = snapshot(judge_src=(os.path.join(HERE, "chat_eval.py"),))
        print(json.dumps(s, ensure_ascii=False, indent=2))
