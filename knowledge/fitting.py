#!/usr/bin/env python3
"""量体值 → 推荐尺码 / 判定标准码·调号·全定制。

知识库里早就写着这条判断线(08-量体与版型.md 第三节),但它一直只是一句话 ——
没有代码执行它,也没有字段承载「体型特征」这半句。这个文件把它变成能跑的东西。

三条规则,全部来自 md,不在这里另立标准:
  · 关键尺寸与标准码差 ≤2cm → 标准码;2–5cm → 调号;>5cm → 全定制
  · **远程量体公差放宽 1cm**(不是因为量得准,是因为量得不准,严卡会白白把人推进调号)
  · **有明显体型特征 → 直接全定制**,与差值无关

最容易错的一步不是算差值,是**比对基准**:
尺码表是成衣尺寸,量体记录是人体净尺寸,中间差一个放松量。直接相减一定判错。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MD_PT = os.path.join(HERE, "10-版型库.md")
MD_MS = os.path.join(HERE, "08-量体与版型.md")
TOL_FIT, TOL_ADJ, REMOTE_RELAX = 2.0, 5.0, 1.0

# ── 围度放松量按版型基码反推(业务 2026-09-22 定)──────────────────────
#
# 原来围度放松量全局一个数(胸 16 / 腰 2 / 臀 8 / 裙腰 18)。圆领袍、大袖衫这种宽松形制
# 实际放松 30 上下,于是**正常身材一律判成全定制**;童装裙腰也按成人余量算。
# 演示库里约 65% 定制单判成全定制,一半以上是这个原因(另一半是长度,见下)。
#
# 现在:**这个码的成衣尺寸 − 国标同号净体**,就是这个版型在这个码上的放松量 ——
# 宽松款自动得到大余量,贴体款自动得到小余量,不用给每个版型手写一张表。
# 国标净体取 GB/T 1335 的中间体(女 160/84A 系、男 170/88A 系、童按身高码约 0.4×身高+12)。
# 这几个国标数是近似值 —— **业务 2026-09-22 定:直接用这组近似值,不等版师核**(用户拍板;原先写的是「要版师核」)。
# 码名认不出(不是 S–XXL、也不是身高码)就退回原表。
国标净体 = {
    "女": {"S": (80, 64, 86), "M": (84, 68, 90), "L": (88, 72, 94), "XL": (92, 76, 98), "XXL": (96, 80, 102)},
    "男": {"S": (84, 70, 86), "M": (88, 74, 90), "L": (92, 78, 94), "XL": (96, 82, 98), "XXL": (100, 86, 102)},
}
国标_依据 = ("围度放松量 = 这个码的成衣尺寸 − 国标同号净体(GB/T 1335 中间体近似:"
            "女 160/84A、男 170/88A 系,童按身高码 ≈0.4×身高+12)。国标数是近似值,**业务 2026-09-22 定:直接用这组近似值,不等版师核**。")


def 净体(size, sex=None):
    """国标同号净体 {胸围, 腰围, 臀围, 胸上围};认不出的码返回 None(退回原放松量表)。"""
    sz = str(size).strip().upper()
    if sz.isdigit() and 80 <= int(sz) <= 170:            # 童装按身高码
        h = int(sz); c = 0.4 * h + 12
        return {"胸围": c, "腰围": c - 5, "臀围": c + 4, "胸上围": c - 2}
    t = 国标净体.get("男" if sex == "男" else "女", {}).get(sz)
    if not t: return None
    return {"胸围": t[0], "腰围": t[1], "臀围": t[2], "胸上围": t[0] - 4}


# ── 长度只作参考,不判全定制(业务 2026-09-22 定)───────────────────────
# 长度类量的是「客户想要多长」(10-版型库.md 第六节),而**同一个人买不同款,想要的长度本来就不同**
# (褙子衣长 90、长衫 118)。一个人只存一套长度,拿去比所有款,总有几件对不上 ——
# 演示库里平均一人买 4–5 件,长度原因占了全定制的一大半。长度差多了是「改长短」,不是体型问题。
只作参考的长度 = ("通袖长", "衣长", "裙长", "裤长", "袖长")
# ⚠️ 「差多了提示改长短」**这次没做**:一个人只存一套长度,而他买的几件款式想要的长度本来就不同 ——
# 实测门槛取 5cm 时 87% 的件都会带这句、取 10cm 仍有 79%,**一句每件都有的提示等于没有**。
# 要做得等订单上按每一件记「想要的长度」。现在长度仍列在明细里(关键=False),只是不参与判档、不发提示。

# ── 一条**拍过板的决定**,不是待办 ────────────────────────────────────
#
# 系统对体型特征只做一件事:**判成「全定制」**,然后就交给人。
# 「溜肩该把肩斜抬几度、腹凸该在前片放多少」——**这套知识库里没有**,
# 而它正是版师的手艺。
#
# 2026-09-14 业务拍板:**挂着,等版师给** —— 不替它猜。
#
# ⚠️ **这和「还没做」不是一回事,虽然在代码里长得一模一样。**
#   「还没做」是欠着一件事,下一个人该去补;
#   「等版师给」是已经决定不由我们编,下一个人不该去编一套看起来合理的数。
#
# 为什么不编:编出来的那套会**一直被当成真的用**,而错的方式是
# **衣服穿不上,不是报错**。同一条先例在这个项目里已经有两个:
# 会员升档的积分门槛(口径里明写「这条没定义」)、
# 外层部位不细分(「维持可选,客户自己挑」)。
特体修版量 = None
特体修版量_为什么是空的 = (
    "「溜肩加几度、腹凸放多少」是版师的手艺,知识库里没有这张表。"
    "**业务已拍板:挂着等版师给,不替它猜** —— "
    "编一套看起来合理的数出来,它会一直被当成真的用,"
    "而错的方式是衣服穿不上,不是报错。"
    "现在系统能做到的是:**认出这是特体、判成全定制、把特征原样交给版师**。")


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把国标女装 L 码的净体腰围从 72 改成 80(该有的净体整体偏一档)',
     '腰围偏 5cm,但换成 L 码就合上了'),
]

def ease():
    """放松量表:部位 → (类型, 放松量, 对应量体项)。写「—」的表示不比对。"""
    out = {}
    for line in open(MD_PT, encoding="utf-8"):
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) != 5 or c[1] not in ("围度", "长度", "—"): continue
        if c[1] == "—" or c[2] == "—":
            out[c[0]] = (None, None, None, c[4])          # 不比对,但要说明为什么
        else:
            out[c[0]] = (c[1], float(c[2]), c[3], c[4])
    return out


def key_sizes():
    """各形制的关键尺寸 —— 「关键」= 量错了整件报废。来自 08 号文件第二节。"""
    out = {}
    for line in open(MD_MS, encoding="utf-8"):
        m = re.match(r"\|\s*(XZ\d\d)\s+\S+\s*\|\s*(.+?)\s*\|", line.strip())
        if m:
            items = [x.strip().strip("*") for x in re.split(r"[、,]", m.group(2))]
            out[m.group(1)] = [x for x in items if x]
    return out


def recommend(measures, pattern, sizes, specs, xz_code, method="到店", features=(), sex=None):
    """measures: {量体项名: 值};specs: {尺码: {部位: 成衣值}}。返回推荐与逐项明细。"""
    E, K = ease(), key_sizes()
    keys = K.get(xz_code, [])
    tol = TOL_FIT + (REMOTE_RELAX if method == "远程" else 0)
    rows, skipped = [], []

    def target(part, wear, sz=None):
        """成衣尺寸 → 该穿这件衣服的人体尺寸。齐胸襦裙的裙腰围要对胸上围,不是腰围。
        围度的放松量按这个码的国标净体反推(见 `国标净体`);认不出码就用原表。"""
        t = E.get(part)
        if not t or t[0] is None:
            return None, None, (t[3] if t else "放松量表里没有这个部位")
        typ, allow, item, _ = t
        if part == "裙腰围" and xz_code == "XZ01":
            item = "胸上围"                       # 齐胸的裙头系在胸上,不是腰上
        if typ == "围度":
            std = 净体(sz, sex) if sz is not None else None
            if std and item in std:
                return round(std[item], 1), item, None   # 该有的净体就是国标同号净体
        return round(wear - allow, 1), item, None

    per_size = {}
    for sz, parts in specs.items():
        det = []
        for part, wear in parts.items():
            body, item, why = target(part, wear, sz)
            if body is None:
                if sz == list(specs)[0]: skipped.append(dict(部位=part, 原因=why))
                continue
            got = measures.get(item)
            if got is None:
                if sz == list(specs)[0]:
                    skipped.append(dict(部位=part, 原因=f"客户没量过「{item}」"))
                continue
            det.append(dict(部位=part, 量体项=item, 成衣=wear, 应有净体=body,
                            客户=got, 差=round(got - body, 1),
                            关键=item in keys and part not in 只作参考的长度))
        if det: per_size[sz] = det

    if not per_size:
        # 这不是错误,是一个**该被看见的业务状态**:客户量过体,但没量做这件衣服需要的项。
        # 报成 error 的话顾问只会以为系统坏了;报成「需补量」他才知道该请客户回来。
        need = sorted({E[p][2] for p in (list(specs.values())[0] if specs else {})
                       if E.get(p) and E[p][0] is not None})
        return dict(推荐尺码=None, 档位="需补量", 量体方式=method,
                    理由=f"客户的量体模版里没有这件衣服要用的尺寸,还需要量:{'、'.join(need)}",
                    明细=[], 未比对=skipped, 关键尺寸未覆盖=keys,
                    需补量项=need,
                    note="**不要凭现有尺寸猜码** —— 请客户补量,或改用有这些项的量体模版。")

    def score(det):
        # 关键项(长度已除外)优先;没有关键项时比**非长度**的项 —— 大袖衫的关键尺寸只有
        # 通袖长、衣长两项长度,退回「全部项」的话长度又被算进来了
        k = ([abs(d["差"]) for d in det if d["关键"]]
             or [abs(d["差"]) for d in det if d["部位"] not in 只作参考的长度] or [0.0])
        return (max(k), sum(abs(d["差"]) for d in det if d["部位"] not in 只作参考的长度))

    best = min(per_size, key=lambda s: score(per_size[s]))
    det = per_size[best]
    worst = max(det, key=lambda d: (d["关键"], d["部位"] not in 只作参考的长度, abs(d["差"])))
    mx = score(det)[0]

    if features:
        grade, why = "全定制", (f"有体型特征({'、'.join(features)})—— "
                                f"**与差值无关,直接出专属版**")
    elif mx <= tol:
        grade, why = "标准码", (f"关键尺寸最大差 {mx}cm,在 {tol}cm 以内"
                             + ("(远程量体已放宽 1cm)" if method == "远程" else ""))
    elif mx <= TOL_ADJ:
        grade, why = "调号", f"关键尺寸最大差 {mx}cm(在 {tol}–{TOL_ADJ}cm),在标准版上微调「{worst['部位']}」"
    else:
        grade, why = "全定制", f"关键尺寸最大差 {mx}cm,超过 {TOL_ADJ}cm"

    # 关键尺寸里有系统比不了的,必须说出来 —— 别让人以为「系统说标准码」就是全查过了
    unchecked = [k for k in keys if k not in {d["量体项"] for d in det}]
    return dict(推荐尺码=best, 档位=grade, 理由=why, 量体方式=method,
                体型特征=list(features), 最大差=mx, 明细=sorted(
                    det, key=lambda d: (not d["关键"], -abs(d["差"]))),
                未比对=skipped, 关键尺寸未覆盖=unchecked,
                改版量=(特体修版量_为什么是空的 if features else None),
                note="系统只给建议,**最终由版师定**。"
                     + (f"关键尺寸 {unchecked} 系统比不了,须人工确认。" if unchecked else "")
                     + "长度(衣长 / 通袖长 / 裙长 / 裤长 / 袖长)只作参考,不参与判档 —— 按客户想要的长度记。"
                     + ("  ⚠️ 这是特体:系统能说的到「要出专属版」为止,"
                        "**具体改哪儿、改多少不在知识库里**,不要替版师给数。"
                        if features else ""))


if __name__ == "__main__":
    import sqlite3
    db = os.path.join(HERE, "..", "backend", "lanxiu.db")
    print("量体 → 推荐尺码 · 自测\n" + "=" * 76)
    E, K = ease(), key_sizes()
    print(f"放松量表 {len(E)} 个部位(其中不比对 {sum(1 for v in E.values() if v[0] is None)} 个)")
    con0 = sqlite3.connect(db)
    all_xz = {r[0]: r[1] for r in con0.execute("SELECT code,name FROM craft WHERE cat='形制'")}
    miss = [f"{c} {n}" for c, n in all_xz.items() if c not in K]
    print(f"关键尺寸覆盖 {len(K & all_xz.keys() if hasattr(K,'keys') else set(K))}/{len(all_xz)} 个形制")
    # 断言写成「和 craft 表比」而不是「等于 10」——
    # 写死数字的检查在扩容那天会一起变绿或一起变红,都不说明问题。
    assert not miss, f"这些形制没写关键尺寸,它们的推荐尺码全是瞎判的:{miss}"
    assert E["胸围"][1] == 16 and E["马面宽"][0] is None
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row

    # 造三个人:正好合身 / 差一点 / 差很多,验证三档都判得出来
    print("\n三档判定(用构造数据,确保三条分支都跑到):")
    specs = {}
    for r in con.execute("SELECT size,item,value FROM size_spec WHERE pattern='PT04'"):
        specs.setdefault(r["size"], {})[r["item"]] = r["value"]
    # PT04 的应有净体腰围(2026-09-22 起按国标同号净体):S 64 / M 68 / L 72 / XL 76;
    # 裙长只作参考,不参与判档(一个人买不同款,想要的长度本来就不同)
    # 注意**它会先挑最合适的码,再判档位** —— 所以「腰围偏 3cm」不等于「差 3cm」,
    # 换个码可能就合上了。这正是推荐尺码该干的事,别把它当成单纯的公差检查。
    CASES = [
        ({"腰围": 68.0, "裙长": 96.0}, "标准码", "正好是 M 码的净体尺寸"),
        ({"腰围": 73.0, "裙长": 96.0}, "标准码", "腰围偏 5cm,但换成 L 码就合上了 —— 不需要改版"),
        ({"腰围": 70.0, "裙长": 110.0}, "标准码", "裙长比任何一个码都长 —— 长度只作参考,不因此判调号/全定制"),
        ({"腰围": 79.0, "裙长": 96.0},  "调号",  "腰围比最大码还大 3cm —— 在标准版上微调"),
        ({"腰围": 90.0, "裙长": 96.0},  "全定制", "腰围超出全部尺码 14cm"),
    ]
    for m, expect, desc in CASES:
        r = recommend(m, "PT04", None, specs, "XZ03")
        ok = "✅" if r["档位"] == expect else "❌"
        print(f"  {ok} {desc}")
        print(f"      → {r['推荐尺码']} 码 / {r['档位']}  ({r['理由']})")
        assert r["档位"] == expect, f"应判 {expect} 实判 {r['档位']}"
    r = recommend({"腰围": 70.0, "裙长": 96.0}, "PT04", None, specs, "XZ03", features=["溜肩"])
    print(f"  {'✅' if r['档位']=='全定制' else '❌'} 尺寸正好但有溜肩 → {r['档位']}  {r['理由']}")
    assert r["档位"] == "全定制", "有体型特征就必须全定制"
    m = {"腰围": 78.7, "裙长": 96.0}
    a = recommend(m, "PT04", None, specs, "XZ03", method="到店")
    b = recommend(m, "PT04", None, specs, "XZ03", method="远程")
    print(f"  {'✅' if (a['档位'],b['档位'])==('调号','标准码') else '❌'} "
          f"同一组尺寸:到店判「{a['档位']}」,远程判「{b['档位']}」(公差放宽 1cm)")
    assert (a["档位"], b["档位"]) == ("调号", "标准码"), (a["档位"], b["档位"], a["最大差"])

    # ── 宽松款:正常身材不许判全定制(2026-09-22 修的那个病)──────────────
    # PT31 圆领袍 M 码成衣胸围 118;原来全局放松量 16 → 「该有的净体」102 ——
    # 一个胸围 88 的正常男士差 14,判全定制。宽松款的放松量本来就大,按国标 M 码净体 88 比才对。
    sp3 = {}
    for r0 in con.execute("SELECT size,item,value FROM size_spec WHERE pattern='PT31'"):
        sp3.setdefault(r0["size"], {})[r0["item"]] = r0["value"]
    if sp3:
        r = recommend({"胸围": 88.0, "腰围": 74.0, "臀围": 90.0, "肩宽": 44.0, "领围": 37.0,
                       "通袖长": 175.0, "衣长": 105.0}, "PT31", None, sp3, "XZ09", sex="男")
        ok = r["档位"] != "全定制"
        print(f"\n  {'✅' if ok else '❌'} 宽松圆领袍 + 正常身材男士(胸 88)→ {r['推荐尺码']} 码 / {r['档位']}"
              f"  (原来全局放松量会判全定制)")
        assert ok, f"宽松款正常身材又被判成全定制了:{r['理由']}"

    print("\n齐胸襦裙的裙腰围必须对胸上围:")
    sp2 = {}
    for r0 in con.execute("SELECT size,item,value FROM size_spec WHERE pattern='PT01'"):
        sp2.setdefault(r0["size"], {})[r0["item"]] = r0["value"]
    r = recommend({"胸上围": 72.0, "腰围": 68.0, "胸围": 84.0, "通袖长": 180.0, "裙长": 105.0},
                  "PT01", None, sp2, "XZ01")
    hit = [d for d in r["明细"] if d["部位"] == "裙腰围"]
    print(f"  裙腰围 → 量体项「{hit[0]['量体项']}」 {'✅' if hit[0]['量体项']=='胸上围' else '❌ 对错了'}")
    assert hit and hit[0]["量体项"] == "胸上围"

    print("\n拿库里真实的 18 个客户跑一遍:")
    feats = {}
    # 体型特征挂着装人了 —— 这里换算回它所属的门店档案,自测口径不变
    for r0 in con.execute("""SELECT w.customer_id, b.feature FROM body_feature b
                             JOIN wearer w ON w.id = b.wearer_id"""):
        feats.setdefault(r0["customer_id"], []).append(r0["feature"])
    item_nm = {r0["code"]: r0["name"] for r0 in con.execute("SELECT code,name FROM measure_item")}
    dist = {}
    for cid, in con.execute("SELECT DISTINCT customer_id FROM measure_rec"):
        ms = {item_nm[r0["item"]]: r0["value"]
              for r0 in con.execute("SELECT item,value FROM measure_rec WHERE customer_id=?", (cid,))}
        mth = con.execute("SELECT method FROM measure_rec WHERE customer_id=? LIMIT 1", (cid,)).fetchone()[0]
        rr = recommend(ms, "PT04", None, specs, "XZ03", mth, feats.get(cid, []))
        g = rr["档位"]; dist[g] = dist.get(g, 0) + 1
    print("  ", dist)
    # 别写死人数 —— 量体覆盖是会变的(补全那一轮从 18 涨到 95)。
    # **夹具写死数量,迟早被一次合理的数据变更打断。**
    # 这里要断言的其实是「有量体记录的人,一个都没被 recommend 悄悄丢掉」,
    # 所以拿一句独立的 COUNT 去对,而不是拿一个常数去对。
    n = con.execute("SELECT COUNT(DISTINCT customer_id) FROM measure_rec").fetchone()[0]
    assert sum(dist.values()) == n, f"有人没出档位:{sum(dist.values())} / {n}"
    assert "需补量" in dist, "应该有客户因为量体模版不含腰围/裙长而需补量"
    print("   其中「需补量」的是用『上衣用量体』模版的客户 —— 他们没量过腰围和裙长,")
    print("   系统不猜,直接说要补量。")
    print("\n✅ 量体推荐自测通过")
