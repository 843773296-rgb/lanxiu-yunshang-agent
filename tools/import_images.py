#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把外面出好的商品图收进系统:核名字 → 收进图片目录 → 报覆盖率。

    python3 tools/import_images.py <图片文件夹>            # 核完就收
    python3 tools/import_images.py <图片文件夹> --dry      # 只核不收

**先核名字再收**。名字对不上的图收进去是**静默失效** —— 文件在那儿,页面还是老样子,
而「收错了名字」和「还没出这张图」在页面上长得一模一样。所以这里对每个文件都判:
认识的收、不认识的报出来,并且**报出它像哪一个**(多半是少打了一段编号)。

收到 `backend/static/img/`(gitignore,不进版本库 —— 图是二进制,而且会一批批地换)。
系统那边的规则是「有生成图就用生成图,没有就用现画的示意图」,所以出一批能用一批,
没出图的商品不会开天窗。
"""
import os, re, shutil, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "backend", "lanxiu.db")
目的地 = os.path.join(ROOT, "backend", "static", "img")
图位 = ("main", "intro", "d1", "d2", "d3") + tuple(f"sku{i}" for i in range(1, 20))
可收 = (".png", ".jpg", ".jpeg", ".webp")


def 认(名, spus):
    """文件名 → (spu, 图位)。认不出来返回 (None, 像谁)"""
    stem, ext = os.path.splitext(os.path.basename(名))
    if ext.lower() not in 可收:
        return None, f"不是图片({ext or '没有扩展名'})"
    spu, _, v = stem.rpartition("-")
    if spu in spus and v in 图位:
        return (spu, v), None
    # 报出它像哪一个 —— **少打前缀是最常见的**(`100617682-main` 少了 `lxys_`),
    # 直接说破比「无法识别」有用得多
    if spu not in spus:
        近 = [s for s in spus if s.endswith(spu) or spu.endswith(s)]
        return None, f"没有这个商品编号「{spu}」" + (f",是不是指 {近[0]}?" if 近 else "")
    return None, f"图位「{v}」不认识(应为 {'/'.join(图位[:5])} 或 skuN)"


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    dry = "--dry" in sys.argv
    if not src or not os.path.isdir(src):
        raise SystemExit("用法:python3 tools/import_images.py <图片文件夹> [--dry]")
    c = sqlite3.connect(DB)
    spus = {r[0] for r in c.execute("SELECT spu FROM product")}
    名字 = {r[0]: r[1] for r in c.execute("SELECT spu,name FROM product")}

    收, 坏 = [], []
    for 根, _, fs in os.walk(src):
        for f in sorted(fs):
            if f.startswith("."):
                continue
            key, why = 认(f, spus)
            (收 if key else 坏).append((os.path.join(根, f), key or why, f))
    print(f"扫到 {len(收) + len(坏)} 个文件:认得出 {len(收)} 个,认不出 {len(坏)} 个")
    for path, why, f in 坏[:20]:
        print(f"  ⚠️ {f} —— {why}")
    if len(坏) > 20:
        print(f"  …… 还有 {len(坏) - 20} 个")

    if not dry:
        os.makedirs(目的地, exist_ok=True)
        for path, (spu, v), f in 收:
            ext = os.path.splitext(f)[1].lower()
            shutil.copy2(path, os.path.join(目的地, f"{spu}-{v}{ext}"))
        print(f"✅ 收进 {目的地}" if 收 else "没有可收的")
        # **收完当场登记进交付图清单。** 原来收和登记是两步,2026-09-22 第五批只做了第一步,
        # 门禁「目录里没有未登记的图」红了 218 张,是另一个会话重建后跑门禁才撞上的。
        # 图不进版本库,清单是「这张图存在过、内容是这个」的唯一记录 —— 漏登记的那批,
        # 一旦目录丢了就无从核对。一步做完,就没有「收了忘登记」这个中间态。
        if 收:
            import subprocess
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "delivered_images.py"), "登记"],
                           check=True)

    # 覆盖率:按商品算,不按张数 —— **一个商品缺一张,它的详情页就是混搭的**
    有 = {}
    for _, (spu, v), _ in 收:
        有.setdefault(spu, set()).add(v)
    已存 = {}
    if os.path.isdir(目的地):
        for f in os.listdir(目的地):
            s, _, v = os.path.splitext(f)[0].rpartition("-")
            if s in spus:
                已存.setdefault(s, set()).add(v)
    # **一套该有几张,按商品自己算** —— 配饰和面料部件没有背面图(平铺的东西没有背面),
    # 出图清单本来就只给它们 主图 + 两张细节。拿服装那套标准去量,
    # **它们会永远显示「缺 d3、intro」** —— 而那不是缺,是本来就不该有。
    # 「还没出」和「不需要」长得一样的话,这份覆盖率报告就没法用来判断还差多少。
    有版型 = {r[0] for r in c.execute(
        "SELECT spu FROM product WHERE pattern IS NOT NULL AND pattern!=''")}

    def 该有(spu):
        return {"main", "intro", "d1", "d2", "d3"} if spu in 有版型 else {"main", "d1", "d2"}

    全 = {s: 已存.get(s, set()) | 有.get(s, set()) for s in set(已存) | set(有)}
    齐 = [s for s, vs in 全.items() if 该有(s) <= vs]
    缺的 = {s: 该有(s) - vs for s, vs in 全.items() if s not in 齐}
    print(f"\n覆盖:{len(全)}/{len(spus)} 款有图,其中 {len(齐)} 款整套齐了、{len(缺的)} 款还缺图")
    for s, miss in list(缺的.items())[:5]:
        print(f"  · {名字.get(s, s)} 缺 {'、'.join(sorted(miss))}")
    print(f"  (配饰 / 面料部件一套是 3 张:主图 + 两张细节;服装是 5 张,多背面和领袖结构)")


if __name__ == "__main__":
    main()
