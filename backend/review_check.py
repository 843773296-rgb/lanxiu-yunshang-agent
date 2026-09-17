# -*- coding: utf-8 -*-
"""月度复盘的验法。

**这里验的是性质,不是逐例真值** —— 复盘里大半是相对指标(完成率、采纳率、
中位工期),它们随人群和时间变。给它们逐例标真值,**第二天就会过期,
而且过期时不报错,只会开始误报**(CLAUDE.md 第 9 节 ③)。

绝对判定只有一条:**逾期**。它有明确的边界(截止时间过了没有),
所以那一条逐例标真值,而且专挑边界 —— 截止就是今天、昨天、已完结。

每条都报「验了多少个」。**空集合上所有性质都成立** —— 样本量为 0 要红,
否则「什么都没验」和「验过了没问题」在输出上长得一模一样。
"""
import os, sys, json, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import api, tasks as tk
import knowledge.review as rv

MGR = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}
ADV = {"no": "60000002", "name": "林岚", "role": "顾问", "shop": "SH001 静安旗舰店"}
FAIL = []


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「已完结的不算逾期」那道判定去掉(做晚了和还没做混成一类)',
     '完结 ≤ 总数,逾期不含已完结'),
]

def ck(name, ok, n, msg=""):
    FAIL.append(name) if not ok else None
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if n == 0:
        print(f"     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        if name not in FAIL: FAIL.append(name + "(样本量 0)")


def months():
    with sqlite3.connect(api.DB) as c:
        return [r[0] for r in c.execute(
            f"SELECT DISTINCT substr({rv.归月字段},1,7) FROM schedule ORDER BY 1") if r[0]]


def main():
    print("月度复盘 · 性质检查")
    print("=" * 72)
    ms = months()

    # ① 确定性:同一批数据算两次必须一模一样。
    #    复盘里有中位数、有排序、有 dict 聚合 —— 任何一处依赖了遍历顺序,
    #    两次就会不一样,而**不一样的那次照样是个合理的数**,肉眼看不出来。
    same = 0
    for m in ms:
        with api.as_user(MGR):
            a = json.dumps(api.monthly_review(m), ensure_ascii=False, sort_keys=True)
            b = json.dumps(api.monthly_review(m), ensure_ascii=False, sort_keys=True)
        same += (a == b)
    ck("同一批数据算两次结果一样", same == len(ms), len(ms))

    # ② 分母为零不给比率。**这是这项能力的立身之本**,单独验。
    txt, val = rv.rate(0, 0, "分派")
    ok2 = val is None and "无从谈起" in txt
    txt2, val2 = rv.rate(1, 4, "分派")
    ok2 = ok2 and val2 == 0.25 and "25%" in txt2
    ck("分母为零给一句话不给 0,分母非零照常算", ok2, 2, f"{txt} / {txt2}")

    # ③ 加总对得上:完结数 ≤ 总数,逾期的一条都不许是已完结的。
    #    **逾期和完结互斥是定义决定的** —— 混进来说明口径被绕过了。
    n3 = bad3 = 0
    with api.as_user(MGR):
        for m in ms:
            d = api.monthly_review(m)
            t = d.get("任务") or {}
            if not t.get("总数"): continue
            n3 += 1
            if t.get("完结", 0) > t["总数"]: bad3 += 1
            if (t.get("逾期") or 0) > t["总数"] - t.get("完结", 0): bad3 += 1
    ck("完结 ≤ 总数,逾期不含已完结", bad3 == 0, n3)

    # ④ 月份切分不重不漏:各月任务数之和 = 该 scope 下的全部任务数。
    #    **漏一个月不会报错**,只会让某个月的活凭空消失。
    with api.as_user(MGR):
        tot = sum((api.monthly_review(m).get("任务") or {}).get("总数", 0) for m in ms)
    with sqlite3.connect(api.DB) as c:
        real = c.execute("SELECT COUNT(*) FROM schedule WHERE shop=?", (MGR["shop"],)).fetchone()[0]
    ck("各月加起来等于全部", tot == real, len(ms), f"各月合计 {tot} / 库里 {real}")

    # ⑤ 隔离:顾问看到的不能多于店长,而且拿不到「逾期都在谁身上」那张榜。
    #    **这一条是结构性的**,不是约定 —— 两份报表拿同一个月对着比。
    n5 = leak = 0
    for m in ms:
        with api.as_user(MGR): dm = api.monthly_review(m)
        with api.as_user(ADV): da = api.monthly_review(m)
        n5 += 1
        if (da.get("任务") or {}).get("总数", 0) > (dm.get("任务") or {}).get("总数", 0):
            leak += 1
        if (da.get("任务") or {}).get("逾期都在谁身上"):
            leak += 1
    ck("顾问看到的不多于店长,且拿不到逐人榜", leak == 0, n5)

    # ⑥ 逾期判定的边界 —— **这一条是绝对判定,逐例标真值,专挑边界**。
    today = "2026-09-11"
    cases = [("有效", "2026-09-10 18:00", True,  "昨天截止、还挂着 → 逾期"),
             ("有效", "2026-09-11 18:00", False, "今天截止 → **还没到**,不算逾期"),
             ("有效", "2026-09-12 09:00", False, "明天截止 → 不算"),
             ("完结", "2026-01-01 09:00", False, "做完了 → 再晚也不算逾期,那是历史"),
             ("取消", "2026-01-01 09:00", False, "取消的不算"),
             ("有效", None,               False, "没写截止时间 → 判不了,不许猜成逾期")]
    bad6 = [c[3] for c in cases if rv.逾期判定(c[0], c[1], today) != c[2]]
    ck("逾期的边界", not bad6, len(cases), ("挂了:" + "；".join(bad6)) if bad6 else "")

    # ⑦ 局部性:改一条任务的状态,只该动它所在那个月的那几项。
    #    **一处改动搅动全表**,说明某个数是跨月算的而口径没写明。
    m7 = next((m for m in ms if (lambda d: d.get("任务", {}).get("总数"))(
        _as(MGR, m))), None)
    n7 = 0; ok7 = True
    if m7:
        with sqlite3.connect(api.DB) as c:
            row = c.execute("SELECT id,status FROM schedule WHERE substr(end_ts,1,7)=? "
                            "AND shop=? AND status='完结' LIMIT 1", (m7, MGR["shop"])).fetchone()
        if row:
            other = [x for x in ms if x != m7]
            before = {x: _as(MGR, x).get("任务", {}).get("完结") for x in other}
            with sqlite3.connect(api.DB) as c:
                c.execute("UPDATE schedule SET status='有效' WHERE id=?", (row[0],))
            try:
                after = {x: _as(MGR, x).get("任务", {}).get("完结") for x in other}
                n7 = len(other); ok7 = before == after
            finally:
                with sqlite3.connect(api.DB) as c:
                    c.execute("UPDATE schedule SET status=? WHERE id=?", (row[1], row[0]))
    ck("改一个月的数据不影响别的月", ok7, n7)

    print("=" * 72)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print(f"✅ 月度复盘 7 条性质全过(扫了 {len(ms)} 个月)")
    return 0


def _as(who, m):
    with api.as_user(who):
        return api.monthly_review(m)


if __name__ == "__main__":
    sys.exit(main())
