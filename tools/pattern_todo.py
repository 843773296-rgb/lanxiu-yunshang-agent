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
    xzs = [dict(r) for r in c.execute("SELECT code,name,alias,key_sizes FROM xingzhi")]
    # **按「要拍的是哪一种决定」分组,不按商品排**。
    # 第一版按商品名排,22 条一模一样的「认不出」铺了一屏,
    # 只能给出一句笼统的「这些形制我们做不做」——
    # 而那 22 条里其实混着四种决定,有一半根本不用业务拍。
    组 = {k: [] for k in FPP.档位}
    for r, 顶 in rows:
        # **先查库里记没记**,再谈按名字推 —— 传 spu 进去就走 `product_custom.xz`。
        # 不传的话这个工具会把 11 个「库里早就写着形制」的商品当成待猜的,
        # 而且会猜错 7 个。
        d = FPP.拍板分档(c, r["name"], 顶, xzs, spu=r["spu"])
        组[d["档位"]].append((r, 顶, d))

    说明 = {
        "库里已记": ("不用拍 —— **配置表里早就写着形制**",
                   "`product_custom.xz` 这一列每个定制品都填着形制名。"
                   "**推出来的会错,记着的不会** —— 按名字推这 11 个会错 7 个"),
        "不该有版型": ("这些压根不该出现在这张表上",
                   "⚠️ **「不需要版型」和「还没定版型」在库里是同一个状态**"
                   "(`pattern IS NULL`)—— 分不清的两种状态,"
                   "合并之后一定按更糟的那个被理解"),
        # ⚠️ 原来这档写的是「不用拍,照着挂就行」——**说过头了**。
        # 确定的只是**形制**,下面还有两种情况仍要人看一眼:
        #   ① 形制下有多个变体(标准 / 加长 / 改良通勤),还得挑一个
        #   ② 🧩多件商品 —— 挂上去会**原样重演**「抹胸套装只挂了抹胸」那个坑
        "确定":     ("形制已经确定 —— 但看一眼变体和多件标记",
                   "商品名里写明了形制;下面标了「要挑变体」或「🧩多件」的,"
                   "还不能直接挂"),
        "要选一个":  ("**要业务拍**:几个形制都对得上,看实物定",
                   "挂错的代价在下面的用料差里"),
        "省了区分项": ("**要业务拍**:商品名省掉的正好是区分项",
                   "省掉的那几个字(门襟 / 腰线)决定裁片和量体项 —— "
                   "猜对了没奖励,猜错了用料工期量体全错,而报表上完全正常"),
        "表里没有":  ("**要业务拍**:这个形制我们到底做不做",
                   "做 → 录进 `01-形制.md`(连**关键尺寸**一起写)再建版型,"
                   "商品自动就挂上了;不做 → 该下架,而不是硬挂一个不对的"),
    }
    print(f"待定版型的成衣:{len(rows)} 个 —— **分成 "
          f"{sum(1 for k in 组 if 组[k])} 种决定**")
    print("=" * 96)
    mp = c.execute("SELECT AVG(price) FROM material WHERE cat='主料'").fetchone()[0] or 0
    for k in FPP.档位:
        if not 组[k]:
            continue
        题, 尾 = 说明[k]
        print(f"\n【{k}】{len(组[k])} 个 —— {题}")
        print(f"  {尾}")
        for r, 顶, d in sorted(组[k], key=lambda x: -x[0]["base_price"]):
            标 = ("  🧩多件" if d["多件"] else "") + \
                 (f"  ⚠️{'/'.join(d['尺寸空'])} 关键尺寸是空的" if d["尺寸空"] else "")
            if k == "确定" and d["候选"]:
                变 = [dict(x) for x in c.execute(
                    "SELECT code,name,gender FROM pattern WHERE xz=?",
                    (d["候选"][0]["code"],))]
                同 = [p for p in 变 if p["gender"] == r["gender"]] or 变
                点名 = [p for p in 同 if p["name"].split("·")[-1] in r["name"]]
                if len(同) == 1:
                    标 += f"  ✓ 变体唯一 {同[0]['code']}"
                elif len(点名) == 1:
                    # 商品名点明了变体(「百迭**长版**」→ PT34 百迭裙·长版)
                    标 += f"  ✓ 商品名点明了变体 {点名[0]['code']} {点名[0]['name']}"
                else:
                    标 += f"  ⚠️ 要挑变体({len(同)} 个)"
            print(f"\n    ¥{r['base_price']:>6.0f}  {r['name']}{标}")
            print(f"            {顶}·{r['kind']}·{r['spu']}   {d['提示']}")
            for z in d["候选"]:
                cand = [dict(x) for x in c.execute(
                    "SELECT code,name,gender,fabric_base FROM pattern WHERE xz=? "
                    "ORDER BY code", (z["code"],))]
                同 = [p for p in cand if p["gender"] == r["gender"]] or cand
                料 = [p["fabric_base"] or 0 for p in 同]
                跨 = (max(料) - min(料)) if 料 else 0
                print(f"            {z['code']} {z['name']:<16} "
                      f"关键尺寸:{z['key_sizes'] or '**空的**':<24} "
                      f"版型 {len(同)} 个"
                      + (f",用料 {min(料):.2f}–{max(料):.2f} 米" if 料 else ""))
            if len(d["候选"]) > 1:
                # **把挑错的代价摆在决定的那一刻**,而不是事后。
                全 = [p["fabric_base"] or 0 for z in d["候选"] for p in c.execute(
                    "SELECT fabric_base FROM pattern WHERE xz=?", (z["code"],))]
                if 全 and max(全) - min(全) > 0.01:
                    跨 = max(全) - min(全)
                    print(f"            → **挑错一个形制,每单差 {跨:.2f} 米料**;"
                          f"按主料均价 {mp:.0f} 元/米,约 **{跨 * mp:.0f} 元/单**")
    打架 = [(r["name"], d["提示"]) for lst in 组.values() for r, _, d in lst
            if d["档位"] == "库里已记" and "打架" not in d["提示"] and "而商品名" in d["提示"]]
    需拍 = sum(len(组[k]) for k in ("要选一个", "省了区分项", "表里没有"))
    print("\n" + "=" * 96)
    if 打架:
        print(f"  ⚠️ 有 {len(打架)} 个**商品名和配置表说的不是同一件衣服**:")
        for n, why in 打架:
            print(f"       {n}")
            print(f"         {why}")
        print(f"     卖场页面按名字理解、车间按配置表下料 —— "
              f"**两边看的不是同一件**。以配置表为准,名字该改。")
    print(f"  {len(rows)} 个里:**{len(组['库里已记'])} 个库里已记 + "
          f"{len(组['确定'])} 个按名字能确定**,**{需拍} 个要业务拍**"
          + (f",{len(组['不该有版型'])} 个不该在表上" if 组["不该有版型"] else ""))
    空 = sorted({z for _, _, d in sum(组.values(), []) for z in d["尺寸空"]})
    if 空:
        print(f"  ⚠️ 候选里有 {len(空)} 个形制的**关键尺寸是空的**:{'、'.join(空)}")
        print(f"     挂上去等于**假旋钮** —— 形制在表里,可它不说要量什么,"
              f"量体项就是空的")
    多件 = [r["name"] for lst in 组.values() for r, _, d in lst if d["多件"]]
    if 多件:
        print(f"  🧩 有 {len(多件)} 个是**多件商品**(套装 / 亲子),"
              f"而 `product.pattern` 是**单值**:")
        for n in 多件:
            print(f"       {n}")
        print(f"     库里已经踩过一次:「乔其叠纱」宋制抹胸套装挂的是 "
              f"PT17 宋制抹胸·标准 ——")
        print(f"     **只挂了抹胸,套装里的裙子没有版型**,"
              f"而报表上这个商品「版型已定」")
    print(f"\n  挂法:`python3 tools/pattern_todo.py <spu> <PT编码>`")
    print(f"  ⚠️ **挂版型是总部运营的事,不是店长** —— 商品是全国一份的主数据,")
    print(f"     门店各挂一份会让同一件衣服在两家店报出不同的价。")
    print(f"     门店该定的是这一单用哪个变体(客户身高体型不同)。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
