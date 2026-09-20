#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打版库自检:每个版型都出得了图、图上的数就是库里的数、页面指的是这件衣服自己的版型。

    python3 backend/draft_check.py

**为什么要验「图上的数 = 库里的数」**:打版图是车间照着裁布的纸。
图画错了不会报错,它只会画出一张看着很对的图 —— 而错在哪只有裁完才知道。
所以这里不验「图画得好不好看」(验不了),只验能机器判的三件事:
出得来、数对得上、指的是对的那个版型。
"""
import os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "tools", "patterndraw")]
import draft as _draft

DB = os.path.join(HERE, "lanxiu.db")

# 咬合记录:左边「改坏了什么」,右边「该红的是哪一条」。可重放的规格在 tools/bite_specs.json。
# 三处都打**结构**不打数值 —— 数值会随数据漂,漂了之后咬合失效的样子和通过一模一样。
咬合 = [
    ("商品页的打版图写死一个版型(不跟着这件商品自己的版型走)", "商品页指的是自己的版型"),
    ("查不到的版型不明说查不到(dict(None) 抛 TypeError)", "查不到的版型要报错"),
    ("标题栏不印规格(图上看不到这一号型到底是多少)", "图上印的规格就是库里的数"),
    ("素面款也按哈希挑一个纹样画上去(图和口径各说各的)", "图上画的花按口径层来"),
]
失败 = []


def 报(名, ok, 说明=""):
    print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
    if not ok:
        失败.append(名)


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    print("打版库")

    # ① 登记了裁片的版型,一个都不许画不出来
    版型 = [r["code"] for r in c.execute(
        "SELECT DISTINCT p.code FROM pattern p JOIN pattern_piece pp ON pp.pattern=p.code ORDER BY p.code")]
    报("样本量", len(版型) >= 60, f"{len(版型)} 个登记了裁片的版型")   # 空集合上什么都成立
    坏 = []
    for pt in 版型:
        sizes = [r["size"] for r in c.execute(
            "SELECT DISTINCT size FROM size_spec WHERE pattern=?", (pt,))]
        try:
            svg, _, _ = _draft.render(pt, "M" if "M" in sizes else (sizes[0] if sizes else "M"))
            if "<svg" not in svg or len(svg) < 2000:
                坏.append(f"{pt} 图是空的")
        except Exception as e:
            坏.append(f"{pt}:{e}")
    报("每个版型都出得了图", not 坏, "、".join(坏[:3]) or f"{len(版型)} 个全过")

    # ② 图上印的规格必须就是库里的数 —— 不是重算一遍,是拿图和库对
    错 = []
    for pt in ("PT04", "PT09", "PT03"):
        sp = {r["item"]: r["value"] for r in c.execute(
            "SELECT item,value FROM size_spec WHERE pattern=? AND size='M'", (pt,))}
        if not sp:
            continue
        svg, _, _ = _draft.render(pt, "M")
        文 = re.sub(r"<[^>]+>", " ", svg)
        for item, v in sp.items():
            if f"{item} {v:g}" not in 文 and f"{v:g}" not in 文:
                错.append(f"{pt} 的「{item}={v:g}」没印在图上")
    报("图上印的规格就是库里的数", not 错, "、".join(错[:3]) or "抽查 3 个版型的每一条规格")

    # ③ 号型从库里读,不是写死 S/M/L —— 童装是 110–150,写死就少一半
    童 = [r["code"] for r in c.execute(
        "SELECT p.code FROM pattern p JOIN xingzhi x ON x.code=p.xz WHERE x.name LIKE '童款%'")]
    if 童:
        sizes = [r["size"] for r in c.execute(
            "SELECT DISTINCT size FROM size_spec WHERE pattern=?", (童[0],))]
        import server
        d = server.product_detail([r["spu"] for r in c.execute(
            "SELECT spu FROM product WHERE pattern=?", (童[0],))][0])
        报("童装号型按库里给", d["draft"] and set(d["draft"]["sizes"]) == set(sizes),
           f"{童[0]}:{'/'.join(sizes)}")

    # ④ 页面给的打版图,必须是这件商品自己挂的版型(指错了比没有更糟)
    import server
    坏指 = []
    for r in c.execute("SELECT spu,pattern FROM product WHERE pattern IS NOT NULL AND pattern!='' "
                       "ORDER BY spu LIMIT 40"):
        d = server.product_detail(r["spu"])
        if d.get("draft") and (d["draft"]["pattern"] != r["pattern"]
                               or any(f"/pattern/{r['pattern']}-" not in u for u in d["draft"]["url"].values())):
            坏指.append(r["spu"])
    报("商品页指的是自己的版型", not 坏指, "、".join(坏指[:3]) or "抽查 40 件")

    # ⑤ 图上画的花 = 口径层判的花(**不是各算各的**)
    # 原来打版图按款号哈希挑纹样、商品图也按哈希挑,库里又没有这一维 ——
    # 三处各说各的,而三处不会并排出现,没人发现。
    sys.path.insert(0, os.path.join(ROOT, "knowledge"))
    import motif as _m
    错纹 = []
    for r in c.execute("""SELECT p.spu,p.name,pc.mt_opts,pc.kf_opts FROM product p
                          LEFT JOIN product_custom pc ON pc.spu=p.spu
                          WHERE p.pattern IS NOT NULL AND p.pattern!='' ORDER BY p.spu LIMIT 60"""):
        纹, 源, _ = _m.推(r["name"], r["mt_opts"] or "", r["kf_opts"] or "")
        画 = _draft._纹样种(r["spu"], r["name"], r["mt_opts"] or "", r["kf_opts"] or "")
        if 纹 == "无纹样" and 画 is not None:
            错纹.append(f"{r['name']}:口径判素面,图上却画了{画}")
        if 源 != _m.待核 and 纹 != "无纹样" and 画 is None:
            错纹.append(f"{r['name']}:口径判{纹},图上一朵花都没有")
    报("图上画的花按口径层来", not 错纹, "、".join(错纹[:2]) or "抽查 60 件")

    # ⑥ 不存在的版型必须明确报错,不许画一张空图糊弄过去
    # 报错还要**报得清楚**:ValueError 且话里带着那个编码。
    # 随便抛个 TypeError 也算「报错了」,但看的人不知道是版型不存在还是程序坏了。
    try:
        _draft.render("PT99999", "M")
        报("查不到的版型要报错", False, "居然画出来了")
    except ValueError as e:
        报("查不到的版型要报错", "PT99999" in str(e), str(e)[:40])
    except Exception as e:
        报("查不到的版型要报错", False, f"报的是 {type(e).__name__},没说清是版型不存在")

    print(("❌ 打版库 %d 条不过" % len(失败)) if 失败 else "✅ 打版库全过")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
