#!/usr/bin/env python3
"""RFM 评分 —— 回答「同一档里谁更该先动」,**不是**第二套分档。

## 为什么不做成分档

`knowledge/lifecycle.py` 的八档已经把 R/F/M 三维都覆盖了:
R → 活跃 / 休眠 / 潜在流失 / 流失,F → 忠诚(4 单跨 2 季),M → 高价值(12 月满 15000)。

再做一套 RFM 分档,就是给同一批客户贴**第二个标签**,而且两套必然打架 ——
C10001 在八档里是「潜在流失」,按经典 RFM 分段会是「Champion」。
**同一个事实两个来源,必然漂**,而这次漂的是「这个客户重不重要」,后果直接到营销动作。

所以这里只出**分数**,不出标签:
  · 八档答「这个客户处在什么阶段」—— 一个互斥标签,有优先级
  · RFM 答「同一档的 16 个人里,我先联系谁」—— 三个分数,可排序
八档答不了后者,因为档内没有排序;而运营每天要做的正是后者。

## 分数是**相对**的,这决定了怎么验它

五分位打分取决于整个客户群的分布 —— 数据一变,同一个人的分数就会变。
所以**逐例真值在这里不成立**(标了第二天就过期),要验的是**性质**:

  ① 同值必须同分 —— 两个 idle_days 都是 200 的客户,R 分不能一个 2 一个 3
  ② 单调不能反   —— idle 越大 R 分不能越高
  ③ 分布不许塌   —— 至少用到 3 个分档,全挤在一档等于没打分
  ④ 排序必须确定 —— 合计分相同时有明确的次序规则,不能每次跑不一样

检查在 `backend/rfm_check.py`。这和逐例真值不是一回事,**别把两者混为一谈**:
绝对判定(八档)逐例标,相对指标(RFM)验性质。
"""

BUCKETS = 5          # 五分位。分档数改了,历史分数就不可比 —— 改之前想清楚。


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把五分位改成七分位(分数越出 1–5 的范围)',
     '分数落在 1–5'),
]

def _score(values, smaller_is_better=False):
    """把一列数值打成 1–BUCKETS 分。返回 {原值: 分数}。

    smaller_is_better=True 表示**值越小分越高**(R 用这个:多久没来,越短越好)。

    ⚠️ 这个参数一开始叫 `reverse` 并且直接传给了 `sorted()`,方向正好反了 ——
    最久没来的客户拿了 R=5。自测的单调性当场抓到。
    **参数名含糊(reverse 到底反的是排序还是分数?)是这类错的温床。**

    **同值同分**是硬要求,所以按「去重后的值」分桶,不按人头分桶 ——
    按人头分会把两个 idle_days 都是 200 的客户切到不同桶里,
    而运营看到「一样的数据,分数不一样」只会得出「这系统不准」这个结论,
    而且他是对的。
    """
    # 高分给排在前面的:值大越好就降序,值小越好就升序
    uniq = sorted(set(values), reverse=not smaller_is_better)
    if not uniq: return {}
    if len(uniq) == 1: return {uniq[0]: BUCKETS}      # 只有一个取值,谈不上分档
    out = {}
    for i, v in enumerate(uniq):
        # 分数从高到低铺:排在前面(reverse 决定"前面"是大还是小)的拿高分。
        # 边界含端:用 floor 分桶,最后一个值兜到 1 分。
        out[v] = max(1, BUCKETS - (i * BUCKETS) // len(uniq))
    return out


def score(rows):
    """给一批客户打 R/F/M 分。

    rows: [{id, idle_days, orders_12m, amount_12m, ...}]
    返回同样的列表,每条多出 R/F/M/RFM 合计 和「先联系顺序」。

    **分数只在这一批人内部可比。** 传进来的是「潜在流失这 16 人」,
    出来的就是这 16 人之间的排序;换一批人,同一个人的分数会变 ——
    这是相对指标的本性,不是 bug,但必须说清楚,否则运营会拿两批的分数直接比。
    """
    rows = [dict(r) for r in rows]
    if not rows: return []
    rs = _score([r.get("idle_days", 0) for r in rows], smaller_is_better=True)
    fs = _score([r.get("orders_12m", 0) for r in rows])
    ms = _score([r.get("amount_12m", 0) for r in rows])
    for r in rows:
        r["R"] = rs.get(r.get("idle_days", 0), 1)
        r["F"] = fs.get(r.get("orders_12m", 0), 1)
        r["M"] = ms.get(r.get("amount_12m", 0), 1)
        r["RFM"] = r["R"] + r["F"] + r["M"]
    # 排序必须**确定**:合计分降序 → 实付金额降序 → 闲置天数升序 → id 升序。
    #
    # ⚠️ 同分时要回到**原始值**,不能拿分数再排一次 ——
    # 分桶本来就压缩了信息,同分是常态(五档装七种取值,最好的两档必然并列)。
    # 第一版写成「合计分 → M 分 → R 分 → id」,而同分的人 M 分 R 分也一样,
    # 排序直接退化成按 id 排:客观最好的那个客户掉到第三。自测抓到的。
    #
    # 最后的 id 是压舱的:前面全同的两个人也必须每次跑出同一次序,
    # 否则运营今天看到的名单和明天不一样,而数据一个字没变。
    rows.sort(key=lambda r: (-r["RFM"], -r.get("amount_12m", 0),
                             r.get("idle_days", 0), str(r.get("id", ""))))
    for i, r in enumerate(rows, 1):
        r["先联系顺序"] = i
    return rows


def explain(r):
    """一句话说清这个分怎么来的 —— 只给结论,运营没法判断该不该信。"""
    return (f"R{r['R']}(距上次互动 {r.get('idle_days')} 天)"
            f" · F{r['F']}(近 12 月 {r.get('orders_12m')} 单)"
            f" · M{r['M']}(近 12 月实付 {r.get('amount_12m'):.0f} 元)"
            f" → 合计 {r['RFM']}")


if __name__ == "__main__":
    def ck(name, ok):
        print(f"  {'✅' if ok else '❌'} {name}")
        assert ok, name
    people = [dict(id=f"C{i}", idle_days=d, orders_12m=o, amount_12m=a)
              for i, (d, o, a) in enumerate(
                  [(10, 5, 30000), (10, 5, 30000), (200, 1, 2000), (50, 3, 12000),
                   (400, 0, 0), (30, 4, 20000), (300, 2, 8000), (5, 8, 41000)])]
    out = score(people)
    by = {r["id"]: r for r in out}
    ck("同值同分(两个 idle=10 的 R 分相同)", by["C0"]["R"] == by["C1"]["R"])
    ck("单调:idle 越大 R 分不越高",
       all(by[a]["R"] >= by[b]["R"] for a, b in [("C7", "C0"), ("C0", "C3"), ("C3", "C6"), ("C6", "C4")]))
    ck("分数落在 1–5", all(1 <= r[k] <= 5 for r in out for k in "RFM"))
    ck("分布没塌(R 至少用到 3 档)", len({r["R"] for r in out}) >= 3)
    ck("排序确定(跑两遍一样)",
       [r["id"] for r in score(people)] == [r["id"] for r in score(list(reversed(people)))])
    ck("最活跃最高频的排第一", out[0]["id"] == "C7")
    print("\n✅ RFM 评分自测通过")
