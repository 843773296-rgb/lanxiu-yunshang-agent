#!/usr/bin/env python3
"""相容矩阵推导 —— 21 工艺 × 13 材质 = 273 格,由属性和规则推出。

手写 273 条判断既不可复算也不可审。这里的做法和本项目推导 91 条异常场景、
计算客户生命周期与会员等级一致:**规则写下来,结论就能复算、能对账、能被质疑。**

属性表与规则都在 06-相容矩阵.md 里,这个脚本只是执行它们 —— md 仍是唯一源头。
人工确认过的格子不受规则覆盖,规则只填空白 ——
而那些格子**从 `相容矩阵-人工确认.json` 读**,不写死在代码里(2026-10-23,见下面那段)。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(HERE, "06-相容矩阵.md")

# ── 人工确认过的格子:**从归档文件读,不写死在代码里** ────────────────────
#
# ⚠️⚠️ 2026-10-23(业务需求池 P3)改的,起因是一个**会造成损失的错诊断**:
#
# 后台的「核实回填」(`/api/combo-resolve`)把打样结论写进库的 `craft_combo`,
# 而这 16 格「人工确认」原来**写死在这个脚本的 OVERRIDE 字典里**。
# 于是「人确认过的事实」有两个家,**而只有一个家被推导当真** ——
# 回填一格之后,下面那段落库对账就报
#     「❌ 落库漂移 1 格,md 改过但没重新 seed」
# 而那是**错的诊断**:md 一个字都没改,真相是「有人打样核实了一格」。
# 照着那条诊断去跑 `seed.py`,会把那格人工确认**抹掉** ——
# 那一格回到待核实队列,**而人已经打过样了**(打样是最贵的那种人工)。
# > 它红了,所以不是静默的 —— 比静默好得多。
# > 但**红错理由比不红更费事**,而这一条更糟:**照着它去做会造成损失。**
#
# ⚠️ **单向仍然成立**:归档文件和 md 一样是**手写源、进版本库**,推导只读它;
# 库永远是推导的产物,不是真相源 —— 重建一次库,结论还在文件里。
#
# ⚠️ **读不到就拒跑,不许当成「0 格人工确认」。**
# 当成 0 格的话,这 16 格会被规则重新填一遍,
# **而那个结果看起来完全正常**(273 格全有判定、对账还可能「一致」)——
# 只是 16 格人工打样的判断被规则的猜测替换了,而没有任何东西会说出来。
# ⚠️ **读写归档文件的实现只有一份**:`backend/combo_manual.py`。
# 推导在这头读、后台「核实回填」在那头写 —— 各写一份解析的话,
# 两边对「同一格两条」「结论只能是三种」的判断迟早不一致,
# 而**不一致时没人知道哪边对**(项目规矩:让那段逻辑只剩一份)。
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import combo_manual as _CM


def _读人工确认():
    try:
        _, 格子 = _CM.读()
    except FileNotFoundError:
        sys.exit(f"❌ 找不到 {_CM.档} —— **拒跑**。\n"
                 f"   这份文件是「人工打样确认过的格子」的唯一来源(2026-10-23 从代码里搬出来的)。\n"
                 f"   当成「0 格人工确认」接着推的话,那些格子会被规则重新填一遍,\n"
                 f"   **而那个结果看起来完全正常** —— 只是人打样的判断被规则的猜测换掉了。")
    out = {}
    for g in 格子:
        k = (g["工艺"], g["材质"])
        if k in out:
            sys.exit(f"❌ {_CM.档} 里 {k} 出现了两次 —— **拒跑**:"
                     f"同一格两个结论,而谁赢取决于谁写在后面")
        if g.get("结论") not in _CM.结论们:
            sys.exit(f"❌ {_CM.档} 里 {k} 的结论是「{g.get('结论')}」,"
                     f"只能是 {' / '.join(_CM.结论们)} —— **拒跑**")
        if not (g.get("理由") or "").strip():
            sys.exit(f"❌ {_CM.档} 里 {k} 没有理由 —— **拒跑**:"
                     f"没有理由的「人工确认」和默认放行没区别")
        out[k] = (g["结论"], g["理由"])
    if not out:
        sys.exit(f"❌ {_CM.档} 里一格都没有 —— **拒跑**(空的和没有这份文件是同一种危险)")
    return out


OVERRIDE = _读人工确认()


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「重」这档工艺权重压成 0(重工和无工艺一样重)',
     '落库漂移'),
]

def _tables():
    """从 md 里读两张属性表"""
    txt = open(MD, encoding="utf-8").read()
    kf, mt = {}, {}
    for line in txt.split("\n"):
        if not line.strip().startswith("| KF") and not line.strip().startswith("| MT"):
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if c[0].startswith("KF") and len(c) >= 8:
            kf[c[0]] = dict(name=c[1], stage=c[2], sheet=c[3] == "是", pierce=c[4],
                            weight=c[5], heat=c[6] == "是", light=c[7] == "是",
                            # 「需深底」这一列原来只为灰缬开(当时以为它是拔染);2026-10-02 查实灰缬是**防染**,
                            # 这一列现在全为「否」,R6b 撤销。列留着:真有拔染工艺进来时它还用得上。
                            dark="是" in c[8] if len(c) > 8 else False)
        elif c[0].startswith("MT") and len(c) >= 11:
            mt[c[0]] = dict(name=c[1], tension=c[2], thick=c[3], coated=c[4] == "有",
                            heat_ok=c[5] == "是", ground=c[6], busy=c[7] == "是",
                            dyeable=c[8] == "是", fiber=c[9],
                            builtin=[x for x in c[10].replace("—", "").split(",") if x])
    return kf, mt


W = {"无": 0, "轻": 1, "中": 2, "重": 3}


def judge(k, m):
    """按 06-相容矩阵.md 里那张规则表推。返回 (判定, 理由, 规则号)"""
    st, wt = k["stage"], W.get(k["weight"], 0)
    low = m["tension"] == "低"

    # R0 是全局的,不属于任何一支工序 —— 补进「压褶定型」后才发现
    # 原来那条「印染需高温」把范围划小了。详见 md 里「规则表会随知识增加而重构」。
    if k["heat"] and not m["heat_ok"]:
        return "不可", f"{k['name']}需高温,{m['name']}不耐热会烫坏", "R0"

    if st == "织造":
        if k["name"] in m["builtin"]:
            return "可", f"{m['name']}本身即以{k['name']}织成,天然相容", "R1"
        if not k["sheet"]:
            return "不可", f"{k['name']}是织造技法,须在织造阶段完成,不可后加于成品面料", "R2"
        return "需评估", f"{k['name']}只能做成独立织片再缀合到{m['name']}上,不能整幅后加;须打样", "R3"

    if st == "印染":
        if not m["dyeable"]:
            return "不可", f"{m['name']}已织入纹样或已染整,再染会毁掉原有效果", "R4"
        if m["fiber"] == "化纤":
            return "不可", f"{k['name']}用传统植物染料,上不了{m['name']}这类化学纤维,须改走分散染料的工业工艺", "R5b"
        if m["ground"] == "深" and not k["dark"]:
            return "不可", f"{m['name']}底色深,压不出{k['name']}的染色纹样", "R6"
        return "可", f"{m['name']}为素色可后染底料,适合{k['name']}", "—"

    if st == "刺绣":
        if wt >= 3 and low:
            return "不可", f"{m['name']}组织张力低,{k['name']}较重会造成拉扯变形", "R7"
        if m["coated"]:
            if k["pierce"] == "是":
                return "需评估", f"{m['name']}表面有涂层,针孔会破坏涂层,须打样确认", "R8"
            return "不可", f"{k['name']}靠密集钉固,比针绣更伤{m['name']}的涂层", "R9"
        if wt == 2 and low:
            return "需评估", f"{m['name']}轻薄,{k['name']}只宜小面积,须控制密度", "R10"
        if m["busy"]:
            return "需评估", f"{m['name']}表面已有满纹,加绣须留白设计,否则纹样打架", "R11"
        if m["ground"] == "深":
            return "需评估", f"{m['name']}底色深,浅色绣线会被吃色,须调整配色", "R12"
        return "可", f"{m['name']}适合{k['name']}", "—"

    # 缝制
    if wt >= 3 and low:
        return "不可", f"{m['name']}张力低,{k['name']}有重量,会把布坠变形", "R14"
    if wt >= 1 and m["thick"] == "极薄":
        return "需评估", f"{m['name']}极薄,承不住{k['name']}的重量与拉力,须加衬", "R13"
    return "可", f"{k['name']}属成衣阶段工序,{m['name']}无特殊限制", "—"


def derive():
    kf, mt = _tables()
    rows = []
    for kc, k in kf.items():
        for mc, m in mt.items():
            if (kc, mc) in OVERRIDE:
                v, why = OVERRIDE[(kc, mc)]
                rows.append((kc, mc, v, why, "人工确认"))
            else:
                v, why, rule = judge(k, m)
                rows.append((kc, mc, v, why, rule))
    return rows


if __name__ == "__main__":
    import collections
    kf, mt = _tables()
    rows = derive()
    print(f"工艺 {len(kf)} × 材质 {len(mt)} = {len(rows)} 格")
    print("  判定分布:", dict(collections.Counter(r[2] for r in rows)))
    print("  来源分布:", dict(collections.Counter(r[4] for r in rows)))
    if len(rows) != len(kf) * len(mt):
        print("❌ 格数对不上"); sys.exit(1)
    if any(not r[3] for r in rows):
        print("❌ 有格子没有理由"); sys.exit(1)
    print()
    print("  一致性:")
    bad = 0
    for (kc, mc), (v, why) in OVERRIDE.items():
        rv, rwhy, rule = judge(kf[kc], mt[mc])
        if rv != v:
            bad += 1
            print(f"    ⚠ {kf[kc]['name']} × {mt[mc]['name']}:人工「{v}」 vs 规则[{rule}]「{rv}」")
    print(f"    16 格人工确认中,与规则不一致 {bad} 格(人工优先,规则不覆盖)")
    print()
    print("  规则命中:")
    ALL = ["R0","R1","R2","R3","R4","R5b","R6","R7","R8","R9","R10","R11","R12","R13","R14"]
    hit = collections.Counter(r[4] for r in rows)
    for r in ALL:
        print(f"    {r:4s} {hit.get(r,0):3d}" + ("   ← 0 命中,这条规则从没被验证过" if not hit.get(r) else ""))

    # 落库漂移检查:md 是唯一源头,库里的必须和现推的一样。
    # 不查这一步,md 改了而没重新 seed 时,页面上显示的还是旧结论 —— 而且不报错。
    db = os.path.join(HERE, "..", "backend", "lanxiu.db")
    if os.path.exists(db):
        import sqlite3
        cur = sqlite3.connect(db).execute(
            "SELECT craft,material,verdict,reason,rule FROM craft_combo")
        got = {(a, b): (v, r, u) for a, b, v, r, u in cur}
        want = {(a, b): (v, r, u) for a, b, v, r, u in rows}
        diff = [k for k in want if got.get(k) != want[k]]
        print()
        if got and not diff:
            print(f"  落库一致:数据库里 {len(got)} 格与 md 现推结果逐字段相同")
        elif not got:
            print("  ⚠ 数据库里没有矩阵,需要跑一次 backend/seed.py")
        else:
            print(f"  ❌ 落库漂移 {len(diff)} 格,md 改过但没重新 seed。示例:")
            for k in diff[:5]:
                print(f"     {k}  库里={got.get(k)}  应为={want[k]}")
            sys.exit(1)

    print("\n✅ 273 格全部有判定与理由")
