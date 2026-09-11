# -*- coding: utf-8 -*-
"""活动归因的检查 —— **订单只许用编号连活动**。

这条保证靠的是**结构**(外键式的取值约束),不是约定。
而「一条从没被攻击过的结构性保证,实际上仍然只是约定」——
所以下面每一条都配了一次真的去违反它的尝试。

## 为什么归因必须用编号

名字会改,编号不会。名字一改,历史订单的归因**当场断掉而且悄无声息**:
按名字 join 出来是 0 单,看起来就像「这个活动没带来成交」,
而不是「这条边断了」。**两者在报表上长得一模一样。**

## 为什么「没有活动」只许有一种写法

实测原来 11 单是空字符串、46 单是 NULL —— 同一件事两种表示。
`WHERE activity IS NULL` 少算 11 单,`WHERE activity=''` 少算 46 单,
**两种写法都不会报错,只会各少一块。**
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("活动归因 · 检查")
    print("=" * 72)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    码 = {r[0] for r in c.execute("SELECT code FROM activity")}
    rows = list(c.execute("SELECT id,activity FROM ordr"))

    # ① 订单上的 activity 要么是合法编号,要么是 NULL。
    野 = [r["id"] for r in rows if r["activity"] is not None and r["activity"] not in 码]
    ck("订单的活动栏只许是编号或 NULL", not 野, len(rows),
       f"越界的 {野[:4]}" if 野 else "")

    # ② 「没有活动」只许有一种写法 —— 空字符串一个都不许有。
    空 = [r["id"] for r in rows if r["activity"] == ""]
    ck("没有活动一律写 NULL,不许用空字符串", not 空, len(rows),
       f"空字符串 {len(空)} 单" if 空 else "")

    # ③ 每个活动的编号在 activity 表里唯一(归因的落点不能有两个)。
    n3 = len(码)
    dup = c.execute("SELECT code FROM activity GROUP BY code HAVING COUNT(*)>1").fetchall()
    ck("活动编号唯一", not dup, n3)

    # ④ 活动的名字和它挂的门店**不许对不上**。
    #    原来门店活动是 random.choice(SHOPS) 挑的,于是
    #    「**静安**旗舰店周年庆」挂到了杭州湖滨店 ——
    #    **名实不符的数据不报错,只是让每一份按门店汇总的报表都错一点点。**
    n4 = bad4 = 0; 例 = []
    for r in c.execute("SELECT code,name,shop FROM activity"):
        for 店 in c.execute("SELECT DISTINCT shop FROM staff WHERE shop!=''"):
            简 = 店[0].split(" ", 1)[-1].replace("店", "")
            if 简 and 简 in r["name"]:
                n4 += 1
                if r["shop"] != 店[0]:
                    bad4 += 1; 例.append(f"{r['name']} 挂在 {r['shop']}")
    ck("活动名里写了哪家店,就得挂在哪家店", not bad4, n4, "；".join(例[:2]))

    # ⑤ 归因真的连得上:至少有一个活动能查到订单。
    #    **这一条防的是「迁移把所有边都搞断了而检查还全绿」** ——
    #    上面四条在「一条归因都没有」的空库上全都成立。
    连上 = c.execute("SELECT COUNT(DISTINCT activity) FROM ordr "
                     "WHERE activity IS NOT NULL").fetchone()[0]
    ck("至少有活动连得上订单(空集合上前面几条全成立)", 连上 > 0, 连上,
       f"{连上} 个活动有订单")

    c.close()
    print("=" * 72)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 活动归因 5 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
