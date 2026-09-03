#!/usr/bin/env python3
"""商品库一致性检查。

核心一条:**商品库不能上架一个配置页随后会拒绝的组合。**
定制品对外提供「可选面料 × 可选工艺」,如果其中任一对在相容矩阵里是「不可」,
客户就会在配置页被拦下 —— 商品库和约束层自相矛盾,而客户看到的是「你们这也不行那也不行」。
"""
import os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
def q(sql, *a): return [dict(r) for r in c.execute(sql, a)]

name2code = {r["name"]: r["code"] for r in q("SELECT code,name FROM craft")}
combo = {(r["craft"], r["material"]): (r["verdict"], r["reason"])
         for r in q("SELECT * FROM craft_combo")}
prods = {r["spu"]: r for r in q("SELECT * FROM product")}
cats = {r["code"] for r in q("SELECT code FROM category")}
bad, warn = [], []

# ① 定制品不得提供「不可」组合
for pc in q("SELECT * FROM product_custom"):
    p = prods.get(pc["spu"])
    if not p: bad.append(f"{pc['spu']} 有定制扩展但没有商品主记录"); continue
    mts = [x for x in (pc["mt_opts"] or "").split(",") if x]
    kfs = [x for x in (pc["kf_opts"] or "").split(",") if x]
    for m in mts:
        for k in kfs:
            v, why = combo.get((name2code.get(k), name2code.get(m)), (None, None))
            if v == "不可":
                bad.append(f"{p['name']}({p['status']}) 提供了不可组合 {k} × {m} —— {why}")
    if p["status"] == "已上架" and not mts:
        bad.append(f"{p['name']} 已上架但一个可选面料都没有")
    if not mts and p["status"] != "已下架":
        bad.append(f"{p['name']} 无可选面料却不是已下架")

# ② 定制品必须有量体模版(和 save_product 的规则一致)
for p in prods.values():
    if p["kind"] == "定制品" and not p["template"]:
        bad.append(f"{p['name']} 是定制品但没关联量体模版")
    if p["category"] and p["category"] not in cats:
        bad.append(f"{p['name']} 的品类 {p['category']} 不存在")

# ③ 定制品都要有 product_custom 扩展
missing = [p["name"] for p in prods.values() if p["kind"] == "定制品"
           and not q("SELECT 1 FROM product_custom WHERE spu=?", p["spu"])]
for m in missing: warn.append(f"{m} 是定制品但没有可选项配置(product_custom)")

# ④ 已上架标品至少要有一个启用且有库存的 SKU
for p in prods.values():
    if p["kind"] != "标品" or p["status"] != "已上架": continue
    sks = q("SELECT * FROM sku WHERE spu=?", p["spu"])
    if not any(s["status"] == "启用" for s in sks):
        bad.append(f"{p['name']} 已上架但没有一个启用的 SKU")
    elif not any(s["status"] == "启用" and s["stock"] > 0 for s in sks):
        warn.append(f"{p['name']} 已上架但全部 SKU 零库存")
    for s in sks:
        if s["locked"] > s["stock"]:
            bad.append(f"{s['code']} 锁定 {s['locked']} > 库存 {s['stock']}")

print("商品库一致性检查\n" + "=" * 70)
print(f"商品 {len(prods)}(标品 {sum(1 for p in prods.values() if p['kind']=='标品')} / "
      f"定制品 {sum(1 for p in prods.values() if p['kind']=='定制品')}) · "
      f"SKU {q('SELECT COUNT(*) n FROM sku')[0]['n']} · 相容矩阵 {len(combo)} 格")
for w in warn: print(f"  ⚠️  {w}")
if bad:
    for b in bad: print(f"  ❌ {b}")
    print(f"\n❌ {len(bad)} 处不一致 —— 商品库会卖出配置页拒绝的组合")
    sys.exit(1)
print(f"\n✅ 没有商品提供相容矩阵判为「不可」的组合")
