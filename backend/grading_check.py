#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推档的检查 —— **1237 条尺码,要核的是 12 条档差和一张基码表。**

## 这套检查守的三件事

**① 档差处处对得上。** 这条判据是**定义性**的:推档就是「基码 + 档差 × 序号」,
所以相邻码的差必须处处相等、且等于档差表里那个数。不一致就是真有一格不对。

⚠️ **故意不设阈值。** 上一次栽在阈值上:裁片占比第一版把「单片 > 60%」
一律当异常,而马面裙的裙片占 90% 本来就正常。
**一刀切的阈值会把对的判成错的**,而那种误报比漏报贵 ——
它会让人去改一个本来对的数。

**② 「推得出」不等于「作数」,而这件事必须在表上看得见。**
马面裙的腰围推得出来(基码 + 4×序号),但褶位是从腰围反推排布的,
腰围一变褶位要重排。那一格只是下单参考 ——
**而在 `size_spec` 里它和一个能直接用的数长得一模一样。**

**③ 认不出来的尺码不许被当成 M。**
童款用身高码(110/120/130/140),一个都不在序号表里。
原来那行 `SIZE_NO.get(sz, 0)` 把它们全算成 0,于是**四个码推出同一组数** ——
110 码和 140 码的孩子拿到同一张尺码表,**而且从来没报过错**。
`.get(键, 默认值)` 是最安静的一种失败:它把「查不到」变成一个看起来正常的数。

## 特例按结构判,不按版型编码

md 里那条特例写的是「PT04 / PT05」,而库里有 **5 个**马面裙
(后来加的 PT76–78 改良马面裙也有褶裥片)。按编码写死的话,
后三个会**静默地**被当成能用的数。所以判据是
「**裁片里有褶裥片 ⇒ 腰围只是下单参考**」—— 编码会漏,结构不会。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]

# ── 咬合记录 ────────────────────────────────────────────────────────────
# 左边:**改坏了什么**(具体到那一行怎么改)。右边:**预期红的那一条**。
# 两样都要 —— 只写「测过了」和没写是一回事,而咬合本身也会失效
# (这个项目栽过四次:注入没进视野 / 破坏点不可观测 / 用了已知占位符 / 攻击跑不起来)。
咬合 = [
    ("把 grading.py 的关键词「褶裥」窄回「褶裥片」(等价于 PT23 没被标上)",
     "有褶裥片的版型,腰围一个不漏地标了「仅供参考」"),
    ("把 grading.序号() 改回 .get(x, 0)",
     "`序号()` 认不出来时返回 None 而不是 0"),
    ("直接改库:把 PT01 的 L 码胸围改成 103,且不标 caveat",
     "每条尺码要么档差对得上,要么在表上标着「不作数」"),
    ("monkeypatch pattern_queue,把「建议先核」里的「影响」那一栏拿掉",
     "建议先核的按影响面排序,而且说得出影响是什么"),
    ("抹掉一条订单行的 pattern_version",
     "挂着版型的订单行都记了下单时的版本"),
    ("把回填的 pattern_version_src 全置空",
     "回填的快照标着是回填的"),
    ("删掉 PT04 的 pattern_rev 那一行",
     "每个版型都有改动记录"),
]

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("推档 · 检查")
    print("=" * 84)
    import grading as g, api
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row

    # ── ① 档差表本身:md 里读得出来,而且和推档那边用的是同一套 ──────
    表 = g.档差()
    ck("档差表读得出来", len(表) >= 10, len(表), f"{len(表)} 条:{sorted(表)}")

    import derive_pattern as dp
    差 = {k: v for k, v in dp.SIZE_NO.items() if k in g.尺码序号}
    ck("推档和核档用同一套尺码序号",
       all(g.尺码序号.get(k) == v for k, v in 差.items()), len(差),
       "两边各存一份的话,改一边就开始漂 —— 而漂了不报错,只是推出来的数不对")

    # ── ② 每一条尺码都能被档差解释,或者被明确标成「不作数」──────────
    片 = {}
    for r in c.execute("SELECT pattern,name FROM pattern_piece"):
        片.setdefault(r["pattern"], []).append(r["name"])
    pats = c.execute("SELECT code,name FROM pattern ORDER BY code").fetchall()
    没解释, 格子 = [], 0
    for p in pats:
        rs = c.execute("SELECT size,item,value,caveat FROM size_spec WHERE pattern=?",
                       (p["code"],)).fetchall()
        格子 += len(rs)
        tbl, 标了 = {}, {}
        for r in rs:
            tbl.setdefault(r["size"], {})[r["item"]] = r["value"]
            if r["caveat"]: 标了[r["item"]] = True
        参考 = set(g.参考项(片.get(p["code"], [])))
        for 部位, d in g.核档(tbl, 参考).items():
            坏 = d["算不出来"] or not d["有规则"] or not d["和规则一致"]
            # **算不出来 / 对不上 的那一格,必须在表上标出来。**
            # 不标的话它和一个能直接用的数长得一模一样 —— 这正是这套检查的主题。
            if 坏 and not 标了.get(部位):
                没解释.append(f"{p['code']}·{部位}:"
                             + ("算不出档差" if d["算不出来"] else
                                "没有档差规则" if not d["有规则"] else
                                f"实际 {d['实际档差']} ≠ 规则 {d['规则档差']}")
                             + ",**而且没有在表上标「仅供参考」**")
    ck("每条尺码要么档差对得上,要么在表上标着「不作数」", not 没解释, 格子,
       "；".join(没解释[:3]) if 没解释 else
       "**推得出 ≠ 作数** —— 不标的话它和一个能直接用的数长得一模一样")

    # ── ③ 特例按结构判:五个马面裙一个都不许漏 ────────────────────────
    褶 = {r["pattern"] for r in c.execute(
        "SELECT DISTINCT pattern FROM pattern_piece WHERE name LIKE '%褶裥%'")}
    标腰 = {r["pattern"] for r in c.execute(
        "SELECT DISTINCT pattern FROM size_spec WHERE item='腰围' AND caveat IS NOT NULL")}
    有腰 = {r["pattern"] for r in c.execute(
        "SELECT DISTINCT pattern FROM size_spec WHERE item='腰围'")}
    漏 = sorted((褶 & 有腰) - 标腰)
    ck("有褶裥片的版型,腰围一个不漏地标了「仅供参考」", not 漏, len(褶 & 有腰),
       f"漏了 {漏}" if 漏 else
       f"{sorted(褶 & 有腰)} —— **md 里那条特例只写了 PT04/PT05,而库里有 "
       f"{len(褶 & 有腰)} 个**;按编码写死会静默漏掉后加的")

    # ── ④ 认不出来的尺码不许被当成 M ──────────────────────────────────
    未知 = [r["code"] for r in pats
            if any(g.序号(s) is None for s in
                   (c.execute("SELECT sizes FROM pattern WHERE code=?",
                              (r["code"],)).fetchone()[0] or "").split(","))]
    没标 = []
    for code in 未知:
        n = c.execute("SELECT COUNT(*) FROM size_spec WHERE pattern=? AND caveat IS NULL",
                      (code,)).fetchone()[0]
        if n: 没标.append(f"{code} 有 {n} 格没标")
    ck("尺码体系认不出来的版型,整张尺码表都标着「不作数」", not 没标, len(未知),
       "；".join(没标[:3]) if 没标 else
       f"{未知} 用身高码 —— **`.get(尺码, 0)` 会把它们全算成 M,"
       f"四个码推出同一组数,而且不报错**")
    ck("`序号()` 认不出来时返回 None 而不是 0", g.序号("110") is None, 1,
       "" if g.序号("110") is None else "**又回到 .get(x, 0) 了**")

    # ── ⑤ 工具两个方向都要对 ──────────────────────────────────────────
    全局 = api.grading_audit()
    ck("不传版型给全局:报得出扫了多少", "86" in str(全局.get("扫了", "")), 1,
       str(全局.get("扫了")))
    一个 = api.grading_audit("PT04")
    ck("传版型给明细:逐部位带基码、档差、覆盖范围",
       bool(一个.get("逐部位")) and all(
           "覆盖范围" in r for r in 一个["逐部位"]), len(一个.get("逐部位") or []))
    ck("明细里把「推得出但不作数」标了出来",
       any("不作数" in k for r in 一个["逐部位"] for k in r), len(一个["逐部位"]),
       "PT04 的腰围 —— **不标的话它和裙长、马面宽长得一模一样**")
    错 = api.grading_audit("这个版型不存在")
    ck("查不到的版型要说查不到,不许兜底给一张空表", bool(错.get("error")), 1,
       错.get("error", "")[:40])

    # ── ⑥ 看板:每一摊都要报样本量,而且排序有依据 ────────────────────
    q = api.pattern_queue()
    摊 = q.get("该核的活") or []
    ck("看板每一摊都报了进度(总数/已完成)",
       all("进度" in x for x in 摊), len(摊),
       f"{len(摊)} 摊:{[x['事'] for x in 摊]}")
    # **一摊为 0 的时候必须说得出是「做完了」还是「没扫到」。**
    # 空集合上所有性质都成立 —— 这是这个项目写在规矩里的一条。
    空 = [x for x in 摊 if str(x.get("进度", "")).startswith("0 ")]
    哑 = [x["事"] for x in 空 if not x.get("状态")]
    ck("数为 0 的那一摊要说清是「做完了」还是「没扫到」", not 哑, len(摊),
       f"没说清的 {哑}" if 哑 else
       f"{len(空)} 摊是 0 —— 「做完了」和「一条都没扫到」该触发的动作正好相反")
    占比摊 = next((x for x in 摊 if x["事"] == "裁片用料占比"), None)
    先 = (占比摊 or {}).get("建议先核") or []
    # ⚠️ **消息本身不许假设被检查的东西是对的。**
    # 第一版写的是 `先[0]["影响"]` —— 咬合时把「影响」这一栏拿掉,
    # 检查确实红了,但红的方式是 **KeyError 栈** 而不是一句判据。
    # 退出码对、理由没了:照着栈去查会查到检查脚本自己身上。
    缺 = [x for x in 先 if "影响" not in x]
    ck("建议先核的按影响面排序,而且说得出影响是什么", bool(先) and not 缺, len(先),
       (f"有 {len(缺)} 条没说影响是什么 —— **排了序但说不出凭什么排**" if 缺 else
        先[0].get("影响") if 先 else
        "一条都没有 —— **一张 86 行的清单等于没排队**"))
    ck("「推得出但不作数」按原因分了组",
       any(len(x.get("分组") or []) >= 2 for x in 摊), len(摊),
       "两组性质不同(褶位是常设提醒,童款是缺一张表)—— "
       "混在一张清单上会让人以为是同一件事")

    # ── ⑦ 版型版本:立着的字段必须有人读,而且回填的不许假装是记的 ──────
    #
    # **一份没被引用的主数据 = 一份不存在的主数据**(这个项目的老主题)。
    # 所以这里验的不是「有没有这个字段」,是「**它有没有被用到**」:
    #   ⓐ 每个版型都有一条改动记录 —— 一个版号不带「v1 和 v2 差在哪」等于没有
    #   ⓑ 挂着版型的订单行都有版本快照
    #   ⓒ 回填的那些**标着是回填的** —— 回填一个看起来正常的数而不说它是回填的,
    #      就是在撒谎,和「估算不许长得像实测」同一条
    #   ⓓ 工艺文档(车间照着裁的那张纸)真的把它印出来了
    n7 = c.execute("SELECT COUNT(*) FROM pattern").fetchone()[0]
    无记录 = [r["code"] for r in c.execute(
        "SELECT code FROM pattern WHERE code NOT IN (SELECT pattern FROM pattern_rev)")]
    ck("每个版型都有改动记录", not 无记录, n7,
       f"没记录的 {无记录[:3]}" if 无记录 else
       "**一个版号不带「v1 和 v2 差在哪」等于没有**")

    该有 = c.execute(
        "SELECT COUNT(*) FROM ordr_item oi JOIN product p ON p.spu=oi.spu "
        "WHERE p.pattern IS NOT NULL AND p.pattern!=''").fetchone()[0]
    缺 = c.execute(
        "SELECT COUNT(*) FROM ordr_item oi JOIN product p ON p.spu=oi.spu "
        "WHERE p.pattern IS NOT NULL AND p.pattern!='' "
        "  AND oi.pattern_version IS NULL").fetchone()[0]
    ck("挂着版型的订单行都记了下单时的版本", not 缺, 该有,
       f"缺 {缺} 条" if 缺 else
       "**快照不是现算** —— 版型改过之后,现算给的是今天那一版")

    假装 = c.execute(
        "SELECT COUNT(*) FROM ordr_item WHERE pattern_version IS NOT NULL "
        "  AND (pattern_version_src IS NULL OR pattern_version_src='')").fetchone()[0]
    ck("回填的快照标着是回填的", not 假装, 该有,
       f"{假装} 条没标来源" if 假装 else
       "**回填一个看起来正常的数而不说它是回填的,就是在撒谎**")

    import importlib.util as _iu
    sp = _iu.spec_from_file_location("srv", os.path.join(HERE, "server.py"))
    srv = _iu.module_from_spec(sp); sp.loader.exec_module(srv)
    oid = c.execute(
        "SELECT oi.order_id FROM ordr_item oi JOIN product p ON p.spu=oi.spu "
        "WHERE p.pattern IS NOT NULL AND p.pattern!='' LIMIT 1").fetchone()[0]
    doc = srv.craft_doc(oid)
    印 = [it for it in (doc.get("items") or []) if (it.get("pattern") or {}).get("下单时的版本")]
    ck("工艺文档把版本印出来了", bool(印), len(doc.get("items") or []),
       f"{印[0]['pattern']['编码']} {印[0]['pattern']['下单时的版本']}" if 印 else
       "**车间照着这张纸裁** —— 纸上不写版本,改过版之后没人看得出来")

    print()
    if FAIL:
        print(f"\033[31m❌ 推档 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print("\033[32m✅ 推档全部符合预期\033[0m")
    print(f"    {格子} 条尺码,要核的是 {len(表)} 条档差 —— "
          f"算不出来的那些**在表上标着**,不会和能用的数混在一起。")


if __name__ == "__main__":
    main()
