# -*- coding: utf-8 -*-
"""预约漏斗的验法。

**漏斗几乎全是相对指标,所以主要验性质**(CLAUDE.md 第 9 节 ③)。
逐例标真值的只有一处:**「还没到点」的边界** —— 那是绝对判定,
而且它是这个漏斗最容易错的地方(未来日期在单条记录上完全合法,
只有和「今天」比才看得出来)。

漏斗特有的三条性质,别的报表没有:

  · **嵌套**:后一环的人必定是前一环里的人 —— 所以人数只能递减。
    第一版就栽在这儿(把并列的「量体/下单」串进了链,
    跑出「下单比量体多」),**结构错了会自己露出来,前提是有人去验**。
  · **加总**:漏掉的 + 留下的 = 上一环。流失分了五档(第五档是这条检查逼出来的),五档加起来
    必须正好等于漏掉的那些,**多一条少一条都说明有一档没归进去**。
  · **最窄的一环要按比例找,不是按人数差找** —— 按人数差永远指向第一环。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import api, knowledge.appt_funnel as af

MGR = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}
ADV = {"no": "60000003", "name": "周叙", "role": "顾问", "shop": "SH001 静安旗舰店"}
HQ = {"no": "60000009", "name": "总部", "role": "总部运营", "shop": ""}
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def f(who, **kw):
    with api.as_user(who):
        return api.appt_funnel(**kw)


def main():
    print("预约到店漏斗 · 性质检查")
    print("=" * 72)

    # ① 嵌套:人数只能递减。**后一环比前一环多,是结构错了**。
    n1 = bad1 = 0
    for who in (MGR, HQ):
        d = f(who)
        rows = d.get("漏斗") or []
        n1 += len(rows)
        for i in range(1, len(rows)):
            if rows[i]["人次"] > rows[i - 1]["人次"]: bad1 += 1
    ck("漏斗人数只能递减(后一环比前一环多 = 结构错了)", bad1 == 0, n1)

    # ② 加总:四档流失加起来 = 约了 - 到店。**少归一档不会报错,只会少算**。
    n2 = bad2 = 0; 明细 = ""
    for who in (MGR, HQ):
        d = f(who)
        rows = d.get("漏斗") or []
        if len(rows) < 3: continue
        丢 = sum(v["条数"] for v in (d.get("流失在哪") or {}).values())
        应丢 = rows[0]["人次"] - rows[-1]["人次"]
        n2 += 1
        if 丢 != 应丢:
            bad2 += 1; 明细 = f"四档合计 {丢} ≠ 约了 {rows[0]['人次']} - 到店 {rows[-1]['人次']}"
    ck("流失五档加起来 = 约了 - 到店", bad2 == 0, n2, 明细)

    # ③ 确定性:同一批数据算两次必须一样。
    import json
    n3 = same = 0
    for who in (MGR, HQ, ADV):
        a = json.dumps(f(who), ensure_ascii=False, sort_keys=True)
        b = json.dumps(f(who), ensure_ascii=False, sort_keys=True)
        n3 += 1; same += (a == b)
    ck("同一批数据算两次结果一样", same == n3, n3)

    # ④ 「还没到点」的边界 —— **绝对判定,逐例标真值**。
    today = "2026-09-11"
    cases = [("2026-09-12 09:00", True,  "明天 → 还没到点,不进分母"),
             ("2026-09-11 23:59", False, "今天晚上 → **今天的算已经到点**,进分母"),
             ("2026-09-10 09:00", False, "昨天 → 进分母"),
             (None,               False, "没写时间 → 判不了,不许猜成「还没到」")]
    bad4 = [c[2] for c in cases if af.未到点(c[0], today) != c[1]]
    ck("「还没到点」的边界", not bad4, len(cases), ("挂了:" + "；".join(bad4)) if bad4 else "")

    # ⑤ 最窄的一环按**比例**找,不是按人数差找。
    #
    # 第一版用的是 [100,60,6] 和 [100,20,18] —— 咬合的时候把算法换成
    # 「按人数差找」,检查**没红**。不是检查漏了,是这两组数据
    # **两种算法算出来是同一个答案**,它们根本分不开。
    # 这正是这个项目栽过的那条:挑错破坏点时,「没红」既可能是检查漏了、
    # 也可能是这个改动本来就无害,而**这两种看起来一模一样**。
    #
    # 现在这两组是**故意让两种算法给出不同答案**的:
    #   [1000, 500, 5]  人数差:500 > 495 → 会指向第一环
    #                   比 例:0.50 > 0.01 → **该指向第二环**
    #   [1000, 10, 9]   人数差:990 > 1   → 会指向第一环
    #                   比 例:0.01 < 0.90 → 也指向第一环(这组是反向对照)
    got = af.最窄的一环([("约了", 1000), ("确认了", 500), ("到店", 5)])
    ok5 = "确认了 → 到店" in (got or "")
    got2 = af.最窄的一环([("约了", 1000), ("确认了", 10), ("到店", 9)])
    ok5 = ok5 and "约了 → 确认了" in (got2 or "")
    ck("最窄的一环按比例找不按人数差找", ok5, 2, got)

    # ⑥ 分母为零不给数。
    t1, v1 = af.环节转化(0, 0, "到店"); t2, v2 = af.整体转化(3, 0)
    ck("分母为零给一句话不给 0", v1 is None and v2 is None and "无从谈起" in t1, 2, t1)

    # ⑦ 隔离:顾问看到的不能多于店长,店长不能多于总部。
    a, b, c = f(ADV), f(MGR), f(HQ)
    g = lambda d: ((d.get("漏斗") or [{}])[0] or {}).get("人次", 0)
    ck("顾问 ≤ 店长 ≤ 总部", g(a) <= g(b) <= g(c), 3,
       f"顾问 {g(a)} / 店长 {g(b)} / 总部 {g(c)}")

    # ⑧ 区间筛选真的在起作用:切一半出来,人数必须变少。
    d_all, d_half = f(HQ), f(HQ, since="2026-08-01")
    ck("给了起始日之后人数变少(筛选没被吞掉)", g(d_half) < g(d_all), 2,
       f"全部 {g(d_all)} / 8 月起 {g(d_half)}")

    # ⑨ 说明书外的状态必须被报出来 —— **静默归进「其他」是最糟的处理**。
    #
    # ⚠️ 样本量数的是「**核对了几个状态**」,不是「抓到几个违规」。
    # 第一版数的是违规数,于是咬合时把「待确认」加进状态机定义,
    # 违规数变 0,检查报「样本量 0 —— 没扫到东西」。
    # 可是**一个干净的库违规数本来就该是 0** —— 那样写会把「完全正常」
    # 判成「什么都没验」。**要求违规必须存在的检查,在问题修好那天会开始误报。**
    with sqlite3.connect(api.DB) as cx:
        全部状态 = [r[0] for r in cx.execute("SELECT DISTINCT status FROM appointment") if r[0]]
    野 = [x for x in 全部状态 if x not in af.状态机认的]
    d = f(HQ)
    报了 = set((d.get("说明书里没有这些状态") or {}).get("分布") or {})
    ck("库里超出状态机的状态,一个都不许吞", set(野) <= 报了, len(全部状态),
       f"核对了 {len(全部状态)} 个状态,其中超纲的 {野},报出来的 {sorted(报了)}")

    print("=" * 72)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 预约漏斗 9 条性质全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
