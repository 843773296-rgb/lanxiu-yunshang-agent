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
    ("把纹样来源那段元数据从图里去掉(模拟漏标 —— 不许当成已核)", "每张图都声明了纹样来源"),
    ("把「推导」并进「已核」(猜出来的当成业务确认过的)", "图上标的来源就是口径判的那一档"),
    ("图例里不再写明结构线是「按比例画的示意」(示意图和定稿图在纸上长得一样)",
     "上衣画了结构线,并写明是示意"),
    ("商品页不再标图的来源(真图和示意图在页面上长得都挺正常)", "商品页标出图的来源"),
    ("去掉某处 count(pattern_piece) 旁边的「数的是登记行数」(一行当成一块)",
     "数裁片的地方都表过态"),
    ("把某个成人款的商品名改成「童款…」(四个信号打架,而图会照成人画)",
     "童装 / 成人的四个信号不打架"),
    ("把钉住表里某一款的颜色改掉(图还是旧颜色,数据已经换了)", "钉住的颜色没被挪动"),
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

    # ⑥ 每张图都要**显式声明纹样来源**,四档之一,**不许缺省**
    #
    # 图例是给人看的,挡不住读数据的程序:拿这批图去跑识图评测,量到的可能是
    # **占位纹样的识别率**,而报告上写的是「纹样识别准确率」—— 两者在报告上长得一样。
    # 所以标记要放在程序读得到的地方(SVG 的 <metadata>),而且**缺省必须是错误**:
    # 「这张图没有占位标记」和「这张图的占位标记漏了」,不标出来就长得一模一样。
    # (设计来自负责设计稿那条线的会话。)
    import re as _re
    四档 = {"已核", "推导", "占位", "无纹样"}
    缺, 错档 = [], []
    for pt in 版型[:40]:
        sizes = [r["size"] for r in c.execute(
            "SELECT DISTINCT size FROM size_spec WHERE pattern=?", (pt,))]
        svg, _, _ = _draft.render(pt, "M" if "M" in sizes else (sizes[0] if sizes else "M"))
        m = _re.search(r'<motif ([^>]*)/>', svg)
        if not m:
            缺.append(pt)
            continue
        g = dict(_re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        if g.get("provenance") not in 四档:
            错档.append(f"{pt}:{g.get('provenance')!r}")
    报("每张图都声明了纹样来源", not 缺 and not 错档,
       (f"没有声明的:{'、'.join(缺[:3])}" if 缺 else "") + ("；" if 缺 and 错档 else "")
       + (f"档不认识:{'、'.join(错档[:2])}" if 错档 else "")
       or f"抽查 {min(40, len(版型))} 个版型,四档(已核/推导/占位/无纹样)都在")

    # 「推导」不许并进「已核」:按面料猜出来的和业务确认过的,图上长得一模一样
    一致 = []
    for r in c.execute("""SELECT p.spu,p.name,p.pattern,pc.mt_opts,pc.kf_opts FROM product p
                          LEFT JOIN product_custom pc ON pc.spu=p.spu
                          WHERE p.pattern IS NOT NULL AND p.pattern!='' ORDER BY p.spu LIMIT 30"""):
        # **号型要按这个版型现读** —— 童装是 110–150,拿 M 去要会得到「缺号型数据」,
        # 而那是检查自己写错了参数,不是被测的东西有问题
        _sz = [x["size"] for x in c.execute(
            "SELECT DISTINCT size FROM size_spec WHERE pattern=?", (r["pattern"],))]
        if not _sz:
            continue
        svg, _, _ = _draft.render(r["spu"], "M" if "M" in _sz else _sz[0])
        g = dict(_re.findall(r'(\w+)="([^"]*)"', _re.search(r'<motif ([^>]*)/>', svg).group(1)))
        纹, 源, _ = _m.推(r["name"], r["mt_opts"] or "", r["kf_opts"] or "")
        应 = {"商品名": "已核", "面料推导": "推导", "工艺推导": "推导",
             "素面料": "无纹样", "待业务核": "占位"}[源]
        if g.get("provenance") != 应:
            一致.append(f"{r['name']}:图上标 {g.get('provenance')},口径判 {应}")
    报("图上标的来源就是口径判的那一档", not 一致, "、".join(一致[:2]) or "抽查 30 件")

    # ⑥bis 上衣类必须画出结构线 —— **不画的话前片和后片在纸上长得一模一样**
    # 只验「有没有画」和「标没标明是示意」,不验画得好不好(那验不了,得版师看)。
    缺结构 = []
    for pt in [x for x in 版型 if x not in ("PT04", "PT05")][:25]:
        名 = {r["name"] for r in c.execute("SELECT name FROM pattern_piece WHERE pattern=?", (pt,))}
        if not any(n.endswith("前片") for n in 名):
            continue
        sizes = [r["size"] for r in c.execute("SELECT DISTINCT size FROM size_spec WHERE pattern=?", (pt,))]
        svg, _, _ = _draft.render(pt, "M" if "M" in sizes else (sizes[0] if sizes else "M"))
        if "前领窝" not in svg or "肩线" not in svg:
            缺结构.append(pt)
        if "版师要重画" not in svg:
            缺结构.append(f"{pt}(没写明结构线是示意)")
    报("上衣画了结构线,并写明是示意", not 缺结构, "、".join(缺结构[:3]) or
       "抽查到的上衣类版型都画了领窝 / 肩线,且图例写明「按比例画的示意,版师要重画」")

    # ⑥ter 商品图的来源必须在页面上分得开
    # 真图和示意图在页面上长得都挺正常,不标的话半年后有人翻几页、看到的都是图,
    # 会以为「商品图做完了」—— 而实际是 25/296。**「没做」和「做了」要在界面上分得开。**
    import server as _srv
    有, 总 = _srv.真图覆盖()
    报("样本量:商品数", 总 >= 100, f"{总} 款")
    页 = open(os.path.join(ROOT, "backend", "web", "index.html"), encoding="utf-8").read()
    报("商品页标出图的来源", "效果示意" in 页 and "img_src" in 页,
       f"详情页按 img_src 标「效果示意 · AI 生成 / 现画」;列表页显示覆盖率 {有}/{总}")
    d1 = _srv.product_detail([r["spu"] for r in c.execute(
        "SELECT spu FROM product ORDER BY spu")][0])
    报("接口给得出图的来源", d1.get("img_src") in ("生成图", "示意图"), str(d1.get("img_src")))
    # **AI 生成的图也要标** —— 它不是实物照片。两种都标,只是标的话不同
    # ⚠️ 判据要绑**真正显示出来的那段文字**,不能只搜关键词 ——
    # 第一版搜「AI 生成」,而 tooltip 里也有这四个字:把标签内容删空,检查照样绿。
    # 咬合当场抓到。这和正则剥 docstring 把 SQL 一起剥了是同一个形状:**搜索范围盖过了被测的东西**。
    报("两种来源都标,不是只标没出图的",
       ">效果示意 · AI 生成<" in 页 and ">效果示意 · 现画<" in 页,
       "生成图标「效果示意 · AI 生成」,没出图的标「效果示意 · 现画」—— 判的是标签本身,不是 title 里的说明")

    # ⑥quater 数裁片不许用 count(*) —— **一行不等于一块**
    #
    # `pattern_piece` 一行登记一种裁片,而 `qty` 是这种裁片要裁几块(前片 qty=2,左右各一)。
    # 按行数算用料,前片会被算成一片。这一族今天在另一条线上也出现过:
    # 量体一次十几个测量项各一行,按行数算的话量体以 10:1 淹没其他触点 ——
    # **「一行」和「一次 / 一块」在计数上长得一样,而差出来的倍数不固定**(10:1 和 2:1)。
    # 倍数不固定最要命:固定的话错了还能等比换算回来,不固定就只能逐条重算。
    #
    # 判据是静态的:凡是 count(*) 到这张表,要么改 sum(qty),
    # 要么在同一行或上一行写明「数的是登记行数」——**逼调用方表态,而不是替他猜**。
    标记 = "数的是登记行数"
    漏标 = []
    for 根, _, fs in os.walk(ROOT):
        if any(x in 根 for x in (".git", "__pycache__", ".venv", "node_modules")):
            continue
        for f in fs:
            if not f.endswith(".py"):
                continue
            路 = os.path.join(根, f)
            try:
                行 = open(路, encoding="utf-8").read().splitlines()
            except Exception:
                continue
            for i, l in enumerate(行):
                if "pattern_piece" not in l or not re.search(r"COUNT\s*\(\s*\*?\s*\)", l, re.I):
                    continue
                # ⚠️ **只看本行和上一行,不看下一行。**
                # 第一版把下一行也算进来,于是**隔壁那条的标注替这条背了书**:
                # 把某一行的标注删掉,检查照样绿(下面那行的标注被当成了它的)。
                # 咬合当场抓到 —— 判据的窗口开大一格,就能漏掉整类破坏。
                近 = (行[i - 1] if i else "") + " " + 行[i]
                if 标记 in 近 or re.search(r"SUM\s*\(\s*qty", 近, re.I):
                    continue
                漏标.append(f"{os.path.relpath(路, ROOT)}:{i+1}")
    报("数裁片的地方都表过态(count 行数 / sum 块数)", not 漏标,
       "、".join(漏标[:3]) + " —— 加 `# 数的是登记行数` 或改用 SUM(qty)"
       if 漏标 else "扫了全仓 .py:count(*) 到 pattern_piece 的都写明了数的是行数")

    # ⑥quinquies 大人还是小孩:四个信号必须一致,打架的要报出来
    # 用户出图时发现的:「竹节」童款交领襦裙 —— 名字说童款,而性别字段、挂的版型、号型
    # 三处都说成人。出图清单原来只看形制名,**静默判成成人比例**。
    # 三比一也是矛盾:真正的问题是这条数据错了,**不该由出图清单替业务投票**。
    打架 = []
    for r in c.execute("""SELECT p.spu, p.name, p.gender, p.pattern, x.name AS xz FROM product p
                          LEFT JOIN pattern pt ON pt.code=p.pattern
                          LEFT JOIN xingzhi x ON x.code=pt.xz"""):
        号 = [z[0] for z in c.execute(
            "SELECT DISTINCT size FROM size_spec WHERE pattern=?", (r["pattern"],))] if r["pattern"] else []
        信号 = {"形制": "童款" in (r["xz"] or ""), "性别": (r["gender"] or "") == "童",
              "名字": "童款" in r["name"], "号型": any(z[:1].isdigit() for z in 号)}
        if r["pattern"] and len(set(信号.values())) > 1:
            打架.append(f"{r['name']}({'、'.join(k for k, v in 信号.items() if v)}说童装)")
    报("童装 / 成人的四个信号不打架", not 打架,
       "；".join(打架[:2]) + " —— **这不是出图的问题,是库里的数据错了**,要业务核"
       if 打架 else "形制 / 性别 / 名字 / 号型 四处口径一致")

    # ⑥sexies 已经出过图的款,颜色必须钉住
    # 2026-09-21:为修两款童装的形制改了两行 seed,**38 款里 22 款换了颜色**,
    # 其中 6 款用户已经照旧颜色出好了图 —— 因为颜色原来按**插入序号**算,改一行就整体挪位。
    # 图一旦交付,**图上的颜色就是事实**:数据要跟着图走,不是反过来。
    # 而对不上的时候**页面上看不出来** —— 客户看到的是图,系统按数据发货。
    import json as _json
    钉文件 = os.path.join(HERE, "图色钉住.json")
    钉 = _json.load(open(钉文件, encoding="utf-8"))["钉住"] if os.path.exists(钉文件) else {}
    有图 = {f.rpartition("-")[0] for f in os.listdir(os.path.join(HERE, "static", "img"))
           if f.endswith(("-main.png", "-main.jpg", "-main.jpeg", "-main.webp"))}         if os.path.isdir(os.path.join(HERE, "static", "img")) else set()
    # ⚠️ **「这台机器上没有图」不是不合格。** 图不进版本库(二进制、一批批换),
    # 所以 CI 和新克隆上一张都没有 —— 第一版把「样本量 0」判成红,当场把 CI 弄红了。
    # 但也不能默默跳过:**「验过了」和「没东西可验」要能分开**,所以照实打印。
    if 有图:
        报("出过图的款都钉了颜色", not sorted(有图 - set(钉)),
           "、".join(sorted(有图 - set(钉))[:3]) or
           f"{len(有图)} 款有图,都在钉住表里。**新收一批图之后要补钉**,"
           "否则下次改 seed 可能把它们的颜色挪走")
    else:
        print(f"     ℹ️ 这台机器上没有商品图(CI / 新克隆都是这样),"
              f"「出过图的款都钉了颜色」这一条**没东西可验**;"
              f"钉住表里 {len(钉)} 条仍会逐条和库里对")
    import img as _img
    错色 = []
    for spu, 应 in 钉.items():
        r = c.execute("SELECT color FROM sku WHERE spu=? ORDER BY code LIMIT 1", (spu,)).fetchone()
        # **口径只有一份**:页面显示什么颜色由 img.商品颜色 说了算。
        # 原来这里抄了一份同样的规则,两份分家时检查会说绿、页面是另一个色。
        实 = _img.商品颜色(spu, r["color"] if r else None)
        if 实 != 应:
            错色.append(f"{spu}:钉的是{应},库里是{实}")
    报("钉住的颜色没被挪动", not 错色, "；".join(错色[:3]) or f"{len(钉)} 款逐个对过")

    # ⑦ 不存在的版型必须明确报错,不许画一张空图糊弄过去
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
