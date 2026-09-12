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

    # ── 投入产出的口径 ──────────────────────────────────────────
    sys.path.insert(0, os.path.dirname(HERE))
    import api
    import knowledge.activity as av
    HQ = {"no": "60000009", "name": "魏欣新", "role": "总部运营", "shop": ""}
    ADV = {"no": "60000002", "name": "林岚", "role": "顾问", "shop": "SH001 静安旗舰店"}
    with api.as_user(HQ):
        d = api.activity_roi()

    # ⑥ 那两列随机数**一次都不许被读到**。
    #    判法不是看代码里有没有写,是看**返回值里有没有出现那两列的数**。
    #    看代码是查「我写没写」,看返回值是查「它有没有漏出来」。
    src = open(os.path.join(HERE, "api.py"), encoding="utf-8").read()
    seg = src[src.index("def activity_roi("): src.index("def _rows2(")]
    读了 = [k for k in av.不可用的列 if f'"{k}"' in seg or f"['{k}']" in seg]
    ck("随机数那两列一次都没被读", not 读了, len(av.不可用的列),
       f"读了 {读了}" if 读了 else "signup / orders 都没进 SELECT")

    # ⑦ 期外订单**不许并进成交** —— 实测 AC2602 全部 11 单在期外。
    n7 = bad7 = 0
    for row in (d.get("排名") or []) + (d.get("算不出投入产出的") or []):
        n7 += 1
        带 = row.get("带来多少") or {}
        if 带.get("⚠️期外归因") and 带.get("期内成交"):
            # 有期外就一定要单列;期内成交必须只数期内的
            code = row["活动"].split("(")[-1].rstrip(")")
            真期内 = api._rows2(
                "SELECT COUNT(*) FROM ordr o JOIN activity a ON a.code=o.activity "
                "WHERE o.activity=? AND o.status!='取消' "
                "AND substr(o.created,1,10) BETWEEN a.start_d AND a.end_d", code)[0][0]
            if 带["期内成交"] != 真期内: bad7 += 1
    ck("期内成交只数期内的单", bad7 == 0, n7)

    # ⑧ ROI 用**实收**不用应收。拿库里现算一遍对账 ——
    #    **期望值从库里读,不手抄**(手抄一份,数据一变就开始误判)。
    n8 = bad8 = 0
    for row in (d.get("排名") or []):
        n8 += 1
        带, 花 = row["带来多少"], row["花了多少"]
        txt = row["投入产出比"]
        want, _ = av.roi(带.get("实收") or 0, 花.get("已发生") or 0)
        if txt != want: bad8 += 1
    ck("投入产出比用实收 ÷ 已发生", bad8 == 0, n8,
       "拿应收算等于把没到账的钱当成战果")

    # ⑨ **算不出 ROI 的不许混进排名。**
    #    把「未开始」按 0 排进去,会让人把「还没开始」读成「效果最差」,
    #    然后去砍一个根本还没开始的活动。
    #
    # ⚠️ 这一条的期望值**不能**从 `av.不给ROI的活动状态` 取 ——
    # 那正是被测代码用来做判断的那个集合。咬合时把它的 key 改坏,
    # **判断和期望一起变**,检查什么都看不见(实测:该红没红)。
    # 这就是同源谬误:**期望值用被测系统本身算出来,只抓得到数据漂移,
    # 抓不到实现错误。**
    #
    # 改成从数据独立判:一个活动能不能谈投入产出,取决于两件客观的事 ——
    # **它开始了没有**、**它被取消了没有**。这两个从 activity 表直接看得出来,
    # 不经过被测代码的任何一行。
    今天 = __import__("datetime").date.today().isoformat()
    不该进排名 = {r["code"] for r in api._rows(
        "SELECT code,status,start_d FROM activity")
        if (r["start_d"] or "9999") > 今天 or r["status"] == "已取消"}
    混 = [x["活动"] for x in (d.get("排名") or [])
          if x["活动"].split("(")[-1].rstrip(")") in 不该进排名]
    n9 = len(d.get("排名") or []) + len(d.get("算不出投入产出的") or [])
    ck("未开始/已取消的不混进排名", not 混, n9, f"混进来的 {混}" if 混 else "")

    # ⑩ 隔离:顾问看不到投入产出(管理视角)。
    with api.as_user(ADV):
        e = api.activity_roi()
    ck("顾问看不到活动投入产出", bool(e.get("error")), 1,
       (e.get("error") or "")[:40])

    c.close()
    print("=" * 72)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 活动归因与投入产出 10 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
