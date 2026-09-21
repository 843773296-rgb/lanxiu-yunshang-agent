# -*- coding: utf-8 -*-
"""客户旅程 + W 型归因的检查。

归因算法的输入是「这个客户经过了哪些触点」。而**触点本来就在库里,散在五张表**:
预约 / 跟进 / 日程 / 量体 / 下单。这个模块把它们连成线 —— **不是造数据,是归一**。

⚠️ **两个最容易出的错:**

**① 量体不去重。** 一次量体十几个测量项各一行,不去重的话
量体会以 10:1 淹没其他触点,而「量体贡献最大」**只是因为它行数最多** ——
那不是发现,是计数方式。

**② 没有触点的单,算出来大家都是 0。**
「算出来大家都是 0」和「压根没有触点」长得一模一样 ——
所以算不出来就返回空,不编一个分配出来。
"""
import os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import touchpoint as T, credit as C

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad = 0

咬合 = [
    ('把量体的去重去掉(一次量体的十几条测量项各算一个触点)',
     '量体按「一次」算不按「一条」算'),
]


def ck(t, got, want, extra=""):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {t:44s} 判为 {str(got):14s} 应为 {want}{extra}")


def main():
    global bad
    c = sqlite3.connect(T.DB); c.row_factory = sqlite3.Row
    print("\n\033[1m▸ 客户旅程 · 触点散在五张表,连成线才是归因的输入\033[0m")
    print("  " + "=" * 80)

    有旅程, 分布 = T.统计()
    ck("有客户走得出完整旅程", 有旅程 > 0, True, f"  ← {有旅程} 人有触点;长度分布 {分布}")
    if 有旅程 == 0:
        return 1

    # ① 量体去重 —— **一次量体是一个触点,不是十几个**
    r = c.execute("""select customer_id, substr(measured_at,1,10) d, count(*) n
                     from measure_rec group by 1,2 having n>5 limit 1""").fetchone()
    if r:
        旅 = T.客户旅程(r["customer_id"])
        当天量体 = [x for x in 旅 if x["类型"] == "量体" and x["时间"][:10] == r["d"]]
        ck("量体按「一次」算不按「一条」算", len(当天量体) < r["n"], True,
           f"  ← 那天有 {r['n']} 条测量记录,合成 {len(当天量体)} 个触点")

    # ② 时间有序 —— **旅程乱序的话,「首触」就不是第一个人**
    cid = c.execute("select customer_id from appointment limit 1").fetchone()["customer_id"]
    旅 = T.客户旅程(cid)
    有序 = all(旅[i]["时间"] <= 旅[i+1]["时间"] for i in range(len(旅)-1)) if len(旅) > 1 else True
    ck("旅程按时间排好序", 有序, True, "  ← 乱序的话「首次接触」会挑错人")

    # ③ 「这一单之前」不许把单子之后的触点算进来
    单 = c.execute("select id, created from ordr where kind<>'标品订单' order by id limit 1").fetchone()
    _, 之前 = T.这一单之前(单["id"])
    晚的 = [x for x in 之前 if x["时间"] > 单["created"]]
    ck("「这一单之前」真的只有之前的", len(晚的), 0,
       "  ← 把成交之后的触点算进归因,**等于拿结果解释原因**")

    print("\n\033[1m▸ W 型归因 · 用真实触点算(不是造的)\033[0m")
    print("  " + "=" * 80)
    分 = C.W型归因(单["id"])
    ck("算得出分配", len(分) > 0, True, f"  ← {len(分)} 个人参与")
    if 分:
        总 = round(sum(p for _, p, _ in 分), 1)
        ck("影响力加起来是 100", 总, 100.0,
           "  ← W 型是把 100 分给参与者,**不是零和的那种收入分成**")
        print(f"     举例 {单['id'][-8:]}:" +
              " · ".join(f"{w}={p}%({role})" for w, p, role in 分[:3]))

    # ④ 没有触点的单 → **返回空,不编**
    空 = C.W型归因("NO_SUCH_ORDER")
    ck("没有触点的单返回空", 空, [],
       "  ← **「算出来大家都是 0」和「压根没有触点」长得一模一样**")

    print(f"\n  {Y}⚠ 前提{D}:这些触点是**造数据造出来的旅程** —— 一步不落、太干净。")
    print(f"     真实客户会绕弯、中断、问一半消失。")
    print(f"     **这里证明的是「算法跑得通」,不是「算得准」。**")
    print(f"     而且 30/30/30/10 这组权重是**行业惯例,不是算出来的** ——")
    print(f"     换成 40/20/30/10 排序就可能变,**而两种算出来的数都叫「影响力」**。")

    print()
    if bad:
        print(f"{R}❌ 客户旅程 {bad} 处不符合预期{D}")
        return 1
    print(f"{G}✅ 客户旅程 / W 型归因全部符合预期{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
