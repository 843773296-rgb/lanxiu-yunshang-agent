#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把订单上的活动**名字**换成**编号**,并把「没有活动」统一成 NULL。

## 为什么不直接重灌库

`seed.py` 是确定性的,重灌一次就全对了 —— 但会**抹掉 42 条真实旅程**
(`tools/run_journey.py` 走真实写接口造的)和整本 `op_log`。
那些是跑出来的,不是种出来的,重灌拿不回来。

所以改成原地迁移,并且 `seed.py` 也同步改好 —— **两条路都要对**:
老库迁移一次,新库一开始就是对的。只改一边的话,
下一个人 reseed 之后会得到一个和线上不一样的库,而且不会有任何提示。

## 这次迁移的三件事

  ① `ordr.activity` 存名字 → 存编号
     名字会改,编号不会。名字一改,历史归因**当场断掉而且悄无声息** ——
     按名字 join 出来是 0 单,看起来就像「这个活动没带来成交」。

  ② 空字符串 → NULL
     「没有活动」有两种写法(实测 '' 11 单、NULL 46 单),
     查询时漏掉一种就少算一批。**同一件事只许有一种表示。**

  ③ 门店活动挂错店
     「**静安**旗舰店周年庆」挂在杭州湖滨店 —— seed 里写的是 random.choice。
     名实不符的数据不报错,只是让每一份按门店汇总的报表都错一点点。

默认 dry-run,`--go` 才真的改。
"""
import os, sqlite3, sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "lanxiu.db")


def main():
    go = "--go" in sys.argv
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    名2码 = {r["name"]: r["code"] for r in c.execute("SELECT code,name FROM activity")}
    码 = set(名2码.values())

    plan, 认不出 = [], []
    for r in c.execute("SELECT id,activity FROM ordr"):
        v = r["activity"]
        if v is None: continue
        if v in 码: continue                      # 已经是编号了
        if not str(v).strip():
            plan.append((r["id"], v, None)); continue
        if v in 名2码:
            plan.append((r["id"], v, 名2码[v])); continue
        认不出.append((r["id"], v))

    print(f"{'真跑' if go else 'dry-run(加 --go 才真改)'}")
    print(f"  要改 {len(plan)} 单")
    import collections
    for (frm, to), n in collections.Counter((p[1], p[2]) for p in plan).most_common():
        print(f"    {frm!r:<22} → {to!r:<10} {n:>3} 单")
    if 认不出:
        # **认不出的一律不动。** 猜一个编号,等于凭空造了一条归因,
        # 而它会一直躺在报表里,没人知道它是猜的。
        print(f"  ⚠️ 认不出的 {len(认不出)} 单,**一个都不动**:{认不出[:5]}")

    # ③ 门店活动挂错店 —— 「**静安**旗舰店周年庆」被挂到了杭州湖滨店。
    #    原因是 seed 里写的是 `random.choice(SHOPS)`。
    #    **名实不符的数据不报错,只是让每一份按门店汇总的报表都错一点点。**
    店 = [r[0] for r in c.execute("SELECT DISTINCT shop FROM staff WHERE shop!=''")]
    挂错 = []
    for r in c.execute("SELECT code,name,shop FROM activity WHERE kind='门店'"):
        for sh in 店:
            简 = sh.split(" ", 1)[-1].replace("店", "")
            if 简 and 简 in r["name"] and r["shop"] != sh:
                挂错.append((r["code"], r["name"], r["shop"], sh))
    if 挂错:
        print(f"  活动挂错门店 {len(挂错)} 个:")
        for code, nm, old, new in 挂错:
            print(f"    {code} {nm}:{old} → {new}")

    if go and 挂错:
        for code, _, _, new in 挂错:
            c.execute("UPDATE activity SET shop=? WHERE code=?", (new, code))
        c.commit()

    if go and plan:
        for oid, _, to in plan:
            c.execute("UPDATE ordr SET activity=? WHERE id=?", (to, oid))
        c.commit()
        print("  已提交")
    c.close()
    return 1 if 认不出 else 0


if __name__ == "__main__":
    sys.exit(main())
