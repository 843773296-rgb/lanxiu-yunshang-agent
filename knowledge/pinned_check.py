#!/usr/bin/env python3
"""钉死的锚点 —— 专门用来抓「同源谬误」。

## 这个文件为什么存在

项目里绝大多数检查的**期望值都是从被测对象里算出来的**:

    tool_eval.py 的锚点:      K["m_waist"] = api.kb_size("PT04","M")[...]["腰围"]
    guards_test.py 的 fixture: BOM = api.kb_bom("PT04","M","云锦",["盘金绣"])
    parity.py:                 比 MCP 和直连两条通道 —— 但它们共用一份实现

这么设计是有理由的:**锚点跟着数据走,评测就不会烂在原地**。
代价是它买到了「抗数据漂移」,同时**抗不住实现错误** ——
`api.py` 算错了,锚点跟着错,所有检查照样绿。

这个坑有个名字:**同源谬误**(拿被测对象生成期望值)。

## 所以这个文件里的每一个数,都是人从 md 里读出来手抄的

**它们故意不现算。** 抄错了会红,实现错了也会红 —— 这正是要的。
每条都注明了在哪份 md 的哪一节能核对,任何人拿着文档就能验。

## 红了怎么办(重要)

**不要自动对齐。** 红了只有两种可能,两种都得人看一眼:

  · 实现错了 —— 那正是这个检查存在的意义
  · 知识库改了,而这里忘了同步 —— 那也是该知道的事

把这里的数字改成系统算出来的值,等于把这个检查关掉。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))


def _api():
    import api; return api


# ── 手抄的锚点 ──────────────────────────────────────────────────────────
# (名字, 期望值, md 出处, 人怎么核对, 系统怎么算)
def PINNED():
    api = _api()
    import leadtime, fitting

    def combo():
        r = api.kb_combo("妆花", "纱")
        return (r.get("verdict"), r.get("rule"))

    def pt05_sizes():
        rs = api.kb_pattern("明制马面裙")["rows"]
        p = next(x for x in rs if x["code"] == "PT05")
        return ",".join(p["尺码"])

    def yunjin():
        r = api._rows("SELECT width_cm,price,loss_rate,lead_days FROM material WHERE code='MT02'")[0]
        return (r["width_cm"], r["price"], round(r["loss_rate"] * 100), r["lead_days"])

    def kesi_cap():
        return leadtime.craft_days()["KF01"][3]        # 并行上限

    def waist(sz):
        return api.kb_size("PT04", sz)["尺码表"][sz]["腰围"]

    def waist_body():
        """成衣腰围减去放松量 = 该穿这件的人体腰围"""
        allow = fitting.ease()["腰围"][1]
        return round(api.kb_size("PT04", "M")["尺码表"]["M"]["腰围"] - allow, 1)

    return [
     dict(name="PT04 基码(M)腰围", want=72.0, got=lambda: waist("M"),
          src="10-版型库.md 三、基码成衣尺寸",
          how="表里直接写着 `| PT04 | 腰围 | 72 |`;M 是基码,不加档差"),
     dict(name="PT04 L 码腰围(推档)", want=76.0, got=lambda: waist("L"),
          src="10-版型库.md 三 + 四",
          how="基码 72 + 档差(腰围 +4)× 序号 1 = 76 —— 这条同时验推档规则"),
     dict(name="PT04 S 码腰围(推档)", want=68.0, got=lambda: waist("S"),
          src="10-版型库.md 三 + 四",
          how="72 + 4 ×(−1)= 68"),
     dict(name="妆花 × 纱", want=("不可", "R2"), got=combo,
          src="06-相容矩阵.md 五、属性与推导规则",
          how="属性表:妆花 工序=织造、成片=否 → 命中 R2「织造不成片 → 不可」"),
     dict(name="PT05 阔褶马面裙的尺码序列", want="M,L,XL", got=pt05_sizes,
          src="10-版型库.md 一、版型主数据",
          how="表里那一行写的就是 M,L,XL —— **没有 S**,褶量在 S 码上排不开"),
     dict(name="云锦 幅宽/单价/损耗%/备料天", want=(75.0, 1800.0, 18, 22), got=yunjin,
          src="11-物料与BOM.md 一、主料(面料)",
          how="`| MT02 | 75 | 1800 | 18% | 22 |` 一行四个数照抄"),
     dict(name="缂丝的并行上限", want=1, got=kesi_cap,
          src="07-工期与成本.md 三、工艺工日",
          how="表里那一行的「并行上限」列是 1 —— 一台织机只能一个人织"),
     dict(name="PT04 M 码对应的人体腰围", want=70.0, got=waist_body,
          src="10-版型库.md 三 + 六(放松量表)",
          how="成衣 72 − 放松量 2 = 70;放松量表「腰围 | 围度 | 2」"),
    ]


def verify():
    """返回不一致的清单。空 = 全对。"""
    bad = []
    for p in PINNED():
        try:
            got = p["got"]()
        except Exception as e:
            bad.append((p, f"算不出来:{type(e).__name__}: {e}")); continue
        if got != p["want"]:
            bad.append((p, f"手抄 {p['want']!r} vs 系统算出 {got!r}"))
    return bad


if __name__ == "__main__":
    print("钉死的锚点 · 同源谬误检查\n" + "=" * 82)
    print("这些数字是**人从 md 里读出来手抄的**,故意不现算 ——")
    print("现算的锚点抓不到实现错误,因为实现错了它跟着错。\n")
    ps = PINNED()
    bad = verify()
    baddict = {id(p): why for p, why in bad}
    for p in ps:
        ok = id(p) not in baddict
        print(f"  {'✅' if ok else '❌'} {p['name']:26s} 期望 {p['want']!r}")
        print(f"      出处 {p['src']} —— {p['how']}")
        if not ok: print(f"      ⚠ {baddict[id(p)]}")
    print("\n" + "=" * 82)
    if bad:
        print(f"❌ {len(bad)} 条对不上。**不要把这里的数字改成系统算出来的** ——")
        print("   要么实现错了(这正是这个检查的意义),要么知识库改了这里忘了同步。")
        print("   两种都得人看一眼再决定改哪边。")
        sys.exit(1)
    print(f"✅ {len(ps)} 条手抄锚点与系统算出的结果一致")
