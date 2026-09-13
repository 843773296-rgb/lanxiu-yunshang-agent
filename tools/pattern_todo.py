#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""待定版型清单 —— 哪些成衣还没挂版型,候选是谁,**挂错了差多少钱**。

    python3 tools/pattern_todo.py             列出待定的
    python3 tools/pattern_todo.py <spu> <PT>  挂上(只有总部运营能挂,见下)

## 为什么要显示「挂错了差多少钱」

候选版型之间的差别不是抽象的:「宋制直领长衫·标准」用料基准 4.4 米、
「加长」5.06 米、「改良通勤」3.78 米 —— **最大差 1.28 米**。
按云锦 1800 元/米算,**挂错一档差 2300 元**,而且是每一单都差。

只列出「候选:PT55 / PT56 / PT57」的话,看的人没有依据挑;
**把用料和料费差摆出来,挑错的代价就变成看得见的** ——
这和报价那条「给客户报交期要报最慢那个数」是同一个想法:
**让代价出现在决定的那一刻,而不是出现在事后。**

## 为什么是总部运营挂,不是店长

商品是**全国一份的主数据**。店长能挂的话,同一个 SPU 在静安店挂 PT55、
在徐汇店挂 PT57,于是同一件衣服在两家店报出不同的价,而报表上完全正常。
门店该定的是**这一单用哪个变体**(客户身高体型不同),
而「形制 + 性别」由总部定死。

这条权限在 `server.save_product` 里(只认总部运营),
`boundary_audit` 有两刀在攻击它。
"""
import os, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "backend"), ROOT]
DB = os.path.join(ROOT, "backend", "lanxiu.db")
import fix_order_measure as FX
import fix_product_pattern as FPP
import knowledge.order_gate as OG


def 待定(c):
    """要补版型的成衣。**配饰和面料部件不算** —— 它们不按版型做。"""
    out = []
    for r in c.execute("SELECT spu,name,category,gender,kind,base_price FROM product "
                       "WHERE pattern IS NULL ORDER BY kind DESC,name"):
        顶 = FX.顶级品类(c, r["category"])
        if 顶 not in ("女装", "男装", "童装"):
            continue
        out.append((dict(r), 顶))
    return out


def 候选(c, 商品名, 性别):
    """**只给同形制的候选。** 形制认不出就说认不出,不列一堆无关的版型 ——
    列一堆等于把「我不知道」伪装成「你自己挑」。
    """
    z, why = FPP.匹配形制(c, 商品名)
    if not z:
        return (None, [], why)
    cand = [dict(r) for r in c.execute(
        "SELECT code,name,gender,tpl,fabric_base,fabric_step,sizes,difficulty "
        "FROM pattern WHERE xz=? ORDER BY code", (z["code"],))]
    if 性别 in ("男", "女", "童"):
        同性 = [p for p in cand if p["gender"] == 性别]
        if 同性: cand = 同性
    return (z, cand, why)


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    if len(sys.argv) >= 3:
        spu, pt = sys.argv[1], sys.argv[2]
        import server as sv
        r = c.execute("SELECT name,base_price,kind,category FROM product WHERE spu=?",
                      (spu,)).fetchone()
        if not r:
            print(f"没有商品 {spu}"); return 1
        p = c.execute("SELECT code,xz,tpl FROM pattern WHERE code=?", (pt,)).fetchone()
        if not p:
            print(f"没有版型 {pt}"); return 1
        # **走 save_product,不直接 UPDATE** —— 权限、校验都在那儿,
        # 绕过去就等于给自己开了一道后门。
        print(f"要挂:{r['name']} → {pt}")
        print("⚠️ 这一步要**总部运营**身份。试一下店长:")
        rr = sv.save_product({"spu": spu, "name": r["name"], "kind": r["kind"],
                              "base_price": r["base_price"], "category": r["category"],
                              "pattern": pt}, role="店长")
        print(f"   店长 → {rr.get('code')}: {str(rr.get('reason'))[:70]}")
        print("   用总部运营身份在后台页面上做,或者 role='总部运营' 调 save_product")
        return 0

    rows = 待定(c)
    print(f"待定版型的成衣:{len(rows)} 个")
    print("=" * 96)
    能挑 = 认不出 = 0
    for r, 顶 in rows:
        z, cand, why = 候选(c, r["name"], r["gender"])
        print(f"\n  {r['name']}")
        print(f"    {顶} · {r['kind']} · ¥{r['base_price']:.0f} · gender={r['gender']}"
              f" · spu={r['spu']}")
        if not z:
            认不出 += 1
            print(f"    ⚠️ **{why}** —— 候选列不出来。"
                  f"要么商品名里加上形制词,要么人工指定")
            continue
        if not cand:
            认不出 += 1
            print(f"    ⚠️ 形制 {z['code']} {z['name']} 下没有 {r['gender']} 的版型")
            continue
        能挑 += 1
        print(f"    形制:{z['code']} {z['name']}    候选 {len(cand)} 个:")
        base = min(p["fabric_base"] or 0 for p in cand)
        for p in cand:
            米 = p["fabric_base"] or 0
            差 = 米 - base
            print(f"      {p['code']} {p['name']:<20} 用料 {米:>5.2f} 米"
                  f"{('  (比最省的多 %.2f 米)' % 差) if 差 > 0.01 else '  ← 最省':<24}"
                  f" 模板 {p['tpl']} · 尺码 {p['sizes']} · 难度 {p['difficulty']}")
        if len(cand) > 1:
            跨 = max(p["fabric_base"] or 0 for p in cand) - base
            # 拿这个商品的主料估个价 —— 没有主料就用均价
            mp = c.execute("SELECT AVG(price) FROM material WHERE cat='主料'").fetchone()[0] or 0
            print(f"      → **挑错一档,每单差 {跨:.2f} 米料**;按主料均价 "
                  f"{mp:.0f} 元/米算,约 **{跨 * mp:.0f} 元/单**")
    print("\n" + "=" * 96)
    print(f"  能列出候选的 {能挑} 个,连形制都认不出的 {认不出} 个")
    if 认不出 and not 能挑:
        # **这个结果本身就是结论,不是「工具没用」。**
        # 22 个全部认不出,而看名字就知道原因:它们说的形制
        # (宋制夏衫、明制交领短袄、唐制大袖披衫、男装圆领常服袍)
        # 在 40 个形制里**根本没有** —— 不是匹配不上,是**没录进知识库**。
        print()
        print(f"  ⚠️ **{认不出} 个全都认不出,这说明要拍的不是「挂哪个版型」。**")
        print(f"     它们说的形制(夏衫 / 交领短袄 / 大袖披衫 / 圆领常服袍…)")
        print(f"     在 `01-形制.md` 的 40 个形制里**根本没有**。")
        print(f"     所以真正的问题是:**这些形制我们做不做?**")
        print(f"       做 → 录进 `01-形制.md`(连**关键尺寸**一起写),"
              f"再建版型,商品自动就挂上了")
        print(f"       不做 → 这些商品该下架,而不是硬挂一个不对的版型")
        print(f"     **硬挂一个的代价**:用料、工期、量体项全跟着错,"
              f"而报表上完全正常。")
    print(f"  挂法:`python3 tools/pattern_todo.py <spu> <PT编码>`")
    print(f"  ⚠️ **挂版型是总部运营的事,不是店长** —— 商品是全国一份的主数据,")
    print(f"     门店各挂一份会让同一件衣服在两家店报出不同的价。")
    print(f"     门店该定的是这一单用哪个变体(客户身高体型不同)。")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
