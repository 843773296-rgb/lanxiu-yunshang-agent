# -*- coding: utf-8 -*-
"""把「A04 陆微」这种存名字的字段,补上指向工号的引用。

## 为什么这是个问题

**九张表**存着 `A04 陆微` 这样的字符串,约 2160 行。名字一改 ——
结婚改姓、录错一个字、把「陆微」写成「陸微」—— **所有历史记录当场断掉,
而且悄无声息**:按名字 join 出来是空,看起来像「这条记录没有顾问」。

这和「订单靠活动名连活动」是同一个病,前几天刚修过一次。

## `schedule` 已经把结论摆在那儿了

它**同时**有 `advisor`(名字)和 `assignee_no`(工号),而
`tasks.visible_scope`(数据隔离的唯一判定处)用的是工号。
那个 `advisor` 是纯副本 —— **而「一个人两套编号」这个 bug 就是从这儿来的**。

## 这一版做到哪一步,以及为什么不一次做完

    ① 每张表加 `*_no`,从名字回填 —— **引用建起来**
    ② 加检查:名字和工号**必须始终一致** —— 漂了当场红
    ③ 隔离相关的代码路径改读工号 —— 错在这儿最贵

名字列**暂时留着**,因为 38 个页面在显示它。但它现在是
**有检查盯着的缓存**,不是第二份真相 —— 这是关键区别:
一个被钉住的副本,和一个自由漂移的副本,是两件事。

彻底删掉名字列要等页面改成 join staff 取名字,那是另一摊活。
**留着不写清楚才危险** —— 所以写在这儿。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))

# (表, 存名字的列, 要加的引用列)
#
# ⚠️ **这张映射表漏过三张,而漏掉的那几张恰恰是没人盯着的。**
#
# 2026-09-15 扫了一遍:库里有 `advisor` 这一列的是**九张表**,
# 而这里只列了六张(加 `measure_rec.measured_by` 共七条)——
# `customer`(106 行,「这个客户归谁跟」)、`delivery_notice`、`scheme`
# **从来没建过引用**,也就从来没进过 `advisor_ref_check` 的视野。
#
# 三个数没有一个对得上:文档写「七张表」、映射里六张、真实需要九张。
# **而我们以为这笔债被盯着** —— 其实最大的那一张(客户归谁跟)
# 从来没进过账本。
#
# 教训和今天反复撞的是同一条:**一份手写的清单会过期,而过期时不报错。**
# 这里没法完全现算(哪一列是「名字」要人判),但至少
# `advisor_ref_check` 现在会去比对「库里有 advisor 列的表」和这张映射,
# 少一张就红。
映射 = [("schedule", "advisor", "advisor_no"),
        ("ordr", "advisor", "advisor_no"),
        ("appointment", "advisor", "advisor_no"),
        ("maintain", "advisor", "advisor_no"),
        ("aftersale", "advisor", "advisor_no"),
        ("followup", "advisor", "advisor_no"),
        ("measure_rec", "measured_by", "measured_by_no"),
        # ↓ 2026-09-15 补上的三张,原来一直在外面
        ("customer", "advisor", "advisor_no"),
        ("delivery_notice", "advisor", "advisor_no"),
        ("scheme", "advisor", "advisor_no")]


def 解析(tag, 花名册, 全员=None):
    """把「A04 陆微」拆成工号。返回 (工号 或 None, 理由)。

    **两段都要对得上** —— 编号对而名字不对,说明这条记录是名字改之前写的,
    或者有人手抄错了。**这时候不许只认编号** :
    认编号会把一条明显对不上的记录静静地接受掉,而那正是要发现的东西。
    """
    if not tag:
        return (None, "空值")
    s = str(tag).strip()
    # ⚠️ **同一列里混过两种格式。** `measure_rec.measured_by` 有的存
    # 「A07 白鹭」、有的直接存工号「60000008」(总部运营,不在顾问花名册里)——
    # 后者是我前两天补着装人量体时写进去的。
    #
    # **格式混着比统一存名字更糟**:存名字至少查询写一遍就行;
    # 混着的话任何一种写法都会漏掉另一批,而两种都不报错
    # (按「编号 名字」解析漏 280 行,按工号解析漏 1568 行)。
    if 全员 and s in 全员:
        return (s, f"本来就是工号 {s}({全员[s]})")
    parts = s.split(None, 1)
    if len(parts) == 2:
        code, name = parts[0], parts[1].strip()
        hit = 花名册.get(code)
        if not hit:
            return (None, f"顾问编号 {code} 不在花名册里")
        if hit["name"] != name:
            return (None, f"{code} 在花名册里是「{hit['name']}」,记录里写的是「{name}」"
                          f" —— **两段对不上,不许只认编号**")
        return (hit["no"], f"{code} → 工号 {hit['no']}")
    # 只有名字,没有编号
    byname = {v["name"]: v for v in 花名册.values()}
    hit = byname.get(s)
    if hit:
        return (hit["no"], f"按名字「{s}」→ 工号 {hit['no']}")
    return (None, f"「{s}」既不是「编号 名字」也不是花名册里的名字")


def link(conn, verbose=True):
    """加引用列并回填。返回 (连上几行, 连不上几行)。"""
    conn.row_factory = sqlite3.Row
    c = conn
    花名册 = {r["adv_code"]: dict(r) for r in c.execute(
        "SELECT no,name,adv_code FROM staff WHERE adv_code IS NOT NULL")}
    # 全员(不只顾问)—— 量体可以是总部的人做的
    全员 = {r["no"]: r["name"] for r in c.execute("SELECT no,name FROM staff")}
    连 = 空 = 0
    坏 = []
    for t, 名列, 号列 in 映射:
        cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})")]
        if 名列 not in cols:
            continue
        if 号列 not in cols:
            c.execute(f"ALTER TABLE {t} ADD COLUMN {号列} TEXT")
        for r in c.execute(f"SELECT rowid AS rid,{名列} AS tag FROM {t} "
                           f"WHERE {名列} IS NOT NULL").fetchall():
            no, why = 解析(r["tag"], 花名册, 全员)
            if no:
                c.execute(f"UPDATE {t} SET {号列}=? WHERE rowid=?", (no, r["rid"]))
                连 += 1
            else:
                空 += 1
                if len(坏) < 4: 坏.append((t, r["tag"], why))
    if verbose:
        print(f"  [顾问引用] 连上 {连} 行,连不上 {空} 行")
        for t, tag, why in 坏:
            print(f"     ⚠️ {t}:「{tag}」—— {why}")
        if 空:
            print(f"     **连不上的留空,不猜** —— 猜一个顾问会把业绩、"
                  f"提成和隔离范围一起算错")
    return 连, 空


if __name__ == "__main__":
    cn = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    link(cn); cn.commit(); cn.close()
