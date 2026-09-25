#!/usr/bin/env python3
"""知识库一致性检查。

三件事:
  ① md 里的编码和后台 craft 表对不对得上
  ② 每个条目有没有来源标注(public / scale / demo)
  ③ 同一条知识在两处的来源等级一不一致
不做「打印一句 ✅ 就完事」—— 任一不符退出码非 0。
"""
import os, re, sqlite3, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")
# 解析只有一份 —— 用 kb.py,不再自己写一套正则(两套解析必然打架)
sys.path.insert(0, HERE)
import kb

# 未带来源标注的标题:kb.py 的正则要求必须有标注,所以这里单独扫一遍找漏网的
LOOSE = re.compile(r"^###\s+((?:XZ|MT|KF|PS|SE)\d{2})\s+(.+?)\s*$", re.M)
TIERED = re.compile(r"^###\s+((?:XZ|MT|KF|PS|SE)\d{2})\s+(.+?)\s+`(?:public|scale|demo)`\s*$", re.M)
notier = []
for fn in sorted(f for f in os.listdir(HERE) if f.endswith(".md")):
    txt = open(os.path.join(HERE, fn), encoding="utf-8").read()
    tiered = {m[0] for m in TIERED.findall(txt)}
    for code, name in LOOSE.findall(txt):
        if code not in tiered: notier.append((code, name.strip(), fn))

entries = {r[0]: (r[1], r[9], "") for r in kb.load()}

db = {}
if os.path.exists(DB):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    db = {r["code"]: (r["name"], r["src_type"]) for r in c.execute("SELECT code,name,src_type FROM craft")}

only_md = sorted(set(entries) - set(db))
only_db = sorted(set(db) - set(entries))
name_bad, tier_bad = [], []
for code in sorted(set(entries) & set(db)):
    mn, mt, _ = entries[code]; dn, dt = db[code]
    if mn != dn: name_bad.append((code, mn, dn))
    if mt != dt: tier_bad.append((code, mt, dt))

print(f"知识库 {len([f for f in os.listdir(HERE) if f.endswith('.md')])} 个文件 · "
      f"{len(entries)} 个条目 · craft 表 {len(db)} 条")
print("  按前缀:", dict(collections.Counter(k[:2] for k in entries)))
print("  按来源:", dict(collections.Counter(v[1] for v in entries.values())))
print()
bad = 0
if only_db:
    bad += len(only_db); print(f"❌ 表里有、文档里没有({len(only_db)}) —— 知识库不完整:")
    for c_ in only_db: print(f"     {c_} {db[c_][0]}")
if name_bad:
    bad += len(name_bad); print(f"❌ 名称不一致({len(name_bad)}):")
    for c_, m, d in name_bad: print(f"     {c_} 文档「{m}」 vs 表「{d}」")
if tier_bad:
    bad += len(tier_bad); print(f"❌ 来源等级不一致({len(tier_bad)}) —— 以文档为准,须回改 seed.py:")
    for c_, m, d in tier_bad: print(f"     {c_} 文档 {m} vs 表 {d}")
if notier:
    bad += len(notier); print(f"❌ 缺来源标注({len(notier)}) —— 每条知识都必须标 public/scale/demo:")
    for c_, n, f in notier: print(f"     {c_} {n}  ({f})")
if only_md:
    print(f"ℹ️  文档里有、表里还没有({len(only_md)}) —— 待入库,不算错:")
    print("     " + " ".join(only_md))
# ── 决策表:md 里的表格,和库里 kb_table 那份对得上吗 ──────────────────
# ⚠️ **这一条是补票买的。** 2026-09-24 给「返修判定」那张表加了第四列「来路」,
# md 改了、`liability.py` 也跟着改了,但**库里那份是播种时定死的** ——
# 于是 `kb_tables` 送给模型的一直是三列的旧表,**来路那一列模型一天都没看到**。
# 09-25 真跑评测才发现:模型照旧口径把「签收已确认合身」判成客方收费,
# 而那时新加的公差优先那句话还没送到它眼前。
# **md 是唯一源头,而「唯一源头」只有在派生数据跟着重灌时才成立。**
import json as _json
try:
    import kb as _kb2
    _md = {t_: (h, r) for t_, h, r, _f in _kb2.tables()}
    _cur = conn.execute("SELECT topic, head, rows FROM kb_table").fetchall() \
        if "conn" in dir() else None
except Exception as _e:
    _md, _cur = None, None
if _md is None:
    print("⚠️ 决策表这一条没跑起来 —— 当成没验,不当成通过")
    bad += 1
else:
    import sqlite3 as _s3, os as _os
    _c = _s3.connect(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                   "..", "backend", "lanxiu.db"))
    _db = {r[0]: (_json.loads(r[1]), _json.loads(r[2]))
           for r in _c.execute("SELECT topic, head, rows FROM kb_table")}
    _c.close()
    _差 = []
    for t_ in sorted(set(_md) | set(_db)):
        if t_ not in _db: _差.append(f"{t_}:md 里有,库里没有")
        elif t_ not in _md: _差.append(f"{t_}:库里有,md 里没有")
        elif list(_md[t_][0]) != list(_db[t_][0]):
            _差.append(f"{t_}:表头对不上(md {_md[t_][0]} vs 库 {_db[t_][0]})")
        elif [list(x) for x in _md[t_][1]] != [list(x) for x in _db[t_][1]]:
            _差.append(f"{t_}:行内容对不上(md {len(_md[t_][1])} 行 / 库 {len(_db[t_][1])} 行)")
    print(f"  {'✅' if not _差 else '❌'} 决策表和 md 对得上(验了 {len(_md)} 张)"
          f"{'' if not _差 else ' —— md 改了而派生表没重灌,模型看到的还是旧表'}")
    for x in _差[:4]: print(f"     {x}")
    bad += len(_差)

print()
if bad:
    print(f"❌ {bad} 处不一致"); sys.exit(1)
print("✅ 知识库与 craft 表一致,决策表也和 md 对得上")

# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把库里一种工艺改名(知识库里写的和 craft 表对不上)',
     '名称不一致'),
    ('给 09 md 的返修判定表加一行(md 改了而派生表没重灌)',
     '决策表和 md 对得上'),
]
