#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品图检查 —— **每个商品的每种图都要渲染得出来,而且不能全长一样。**

## 为什么要有这条

实测过一次:**80 / 296 个商品的图直接渲染不出来**(ValueError),
而页面上只是图裂了一块 —— **没人会把它当成 bug 报上来**。
根因是 `sku.color` 那一列填的是**面料名**(双宫绸 / 竹节棉 / 苎麻 · 细支),
色表查不到,兜底返回 `hsl(...)` 字符串,而调色函数只认十六进制。

两头都修了(颜色列只放颜色 + 兜底也返回十六进制),
**但修完要有检查守着**,否则下一批生成商品换个字段又会掉进去。

## 第二条:不能全长一样

图能渲染出来 ≠ 图有用。原来剪影是**按品类**画的,16 个叶子品类、13 种剪影,
296 个商品挤在里面 —— 最大的一桶 71 个商品**图完全相同**。
接上形制之后按结构参数生成(基码衣长 / 通袖长 / 胸围 / 裁片 / 领型),
互不相同的主图从 13 种涨到 290 多种。

**「渲染成功」和「看得出是不同的衣服」是两件事**,所以分成两条验。
"""
import os, sys, hashlib, sqlite3, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
import img

FAIL = []


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('让渲染器对所有商品返回同一段固定内容(页面上看着都有图,实际全是同一张)',
     '每个商品的每种图都渲染得出来'),
]

def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row
    prods = [dict(r) for r in c.execute("SELECT spu,name,kind,category FROM product")]
    变体 = ("main", "d1", "d2", "d3", "intro", "sku1")

    坏 = []
    主图 = {}
    for p in prods:
        for v in 变体:
            try:
                s = img.render(p["spu"], v)
            except Exception as e:
                坏.append(f"{p['name'][:20]}[{v}] {type(e).__name__}: {e}"[:70])
                break
            if not s.startswith("<svg") or len(s) < 400:
                坏.append(f"{p['name'][:20]}[{v}] 渲染出来的不像 SVG")
                break
        else:
            主图[p["spu"]] = hashlib.md5(
                img.render(p["spu"], "main").encode()).hexdigest()
    ck("每个商品的每种图都渲染得出来", not 坏, len(prods) * len(变体),
       ("；".join(坏[:2]) if 坏 else
        "**页面上只是图裂了一块,没人会当成 bug 报上来** —— 所以要专门验"))

    # ② 不能全长一样。按「最大的一桶占比」判,不写死数字 ——
    #    写死的阈值在商品扩容那天会一起变绿或一起变红,都不说明问题。
    桶 = collections.Counter(主图.values())
    最大 = 桶.most_common(1)[0][1] if 桶 else 0
    占比 = 最大 / max(1, len(主图))
    ck("主图不能扎堆(最大的一桶不超过一成)", 占比 <= 0.10, len(主图),
       f"互不相同 {len(桶)} 种,最大一桶 {最大} 个({占比*100:.0f}%)"
       + ("" if 占比 <= 0.10 else " —— **按品类画时这里是 71 个(24%)**"))

    # ③ **挂了版型的成衣**要走形制剪影,不该退回品类剪影。
    #    两类不算:
    #      · 配饰和面料部件 —— 它们本来就不该有版型,品类剪影(簪 / 腰封 / 云肩)才对
    #      · **还没定形制的成衣** —— 那是 `pattern_todo` 的账,不是这条的
    #        (**两条检查不该重叠**:重叠的话同一件事会在两个地方红,
    #         而修好一个另一个还在红,人会以为没修对)
    #    但要把待定数报出来 —— **没定形制 ⇒ 图也画不准**,这是那笔账的利息。
    sys.path[:0] = [os.path.dirname(HERE)]
    import fix_order_measure as FX
    退, 待定 = [], []
    for p in prods:
        if FX.顶级品类(c, p["category"]) not in ("女装", "男装", "童装"):
            continue
        pt = c.execute("SELECT pattern FROM product WHERE spu=?",
                       (p["spu"],)).fetchone()[0]
        if not pt:
            待定.append(p["name"][:24]); continue
        if img._shape_by_pattern(c, p["spu"]) is None:
            退.append(p["name"][:24])
    ck("挂了版型的成衣都按形制画", not 退, len(待定) + len(退) +
       sum(1 for p in prods
           if FX.顶级品类(c, p["category"]) in ("女装", "男装", "童装")
           and c.execute("SELECT pattern FROM product WHERE spu=?",
                         (p["spu"],)).fetchone()[0]) - len(退),
       ("；".join(退[:3]) if 退 else
        "品类只有 16 个叶子,形制有 40 多个 —— **形制才是决定衣服长什么样的那一层**"))
    if 待定:
        print(f"     ℹ️ 另有 {len(待定)} 件成衣还没定形制,图只能按品类画:"
              f"{'、'.join(待定[:3])}")
        print(f"        **没定形制 ⇒ 图也画不准** —— 跑 `tools/pattern_todo.py` 看这笔账")

    c.close()
    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 商品图 3 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
