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
print()
if bad:
    print(f"❌ {bad} 处不一致"); sys.exit(1)
print("✅ 知识库与 craft 表一致")
