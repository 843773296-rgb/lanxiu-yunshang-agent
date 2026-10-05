# -*- coding: utf-8 -*-
"""流失预警取数的对账 + 覆盖报告。

判定口径的逐例真值在 `knowledge/churn.py` 的 68 条自测里,**这里不重复**。
这里只验**取数层特有的四类错** —— 它们都有同一个性质:
**错了不报错,只是名单全歪**。

## ① 列名写错一个字,名单照样跑得出来

`revive.py` 2026-09-20 真栽过:订单状态按「已完成」写而库里是「完成」,
23499 张完成单被判成「在做」。
> 「状态值写错了」和「这个客户真的有单在做」,**在判断结果里长得一模一样**。

而这边更隐蔽:口径吃的键**逐字就是表的列名**,读错一个键
`sqlite3.Row` 不会报错 —— 2026-10-05 就是这么栽的:
读成另一个键名、静静返回 None,**23216 条历史的档位全成了字符串 "None"**,
而当时所有检查都是绿的。

## ② 参数抄了一份而不是转发

> 一句写在注释里的「要共用」,和一处真共用了的,**在那段注释上长得一模一样**。

所以这里用 `is` 断言,不比值 —— 比值的话抄一份出来也相等。

## ③ 连接其实是可写的

> 一个只读连接和一个可写连接,**在查询结果上长得一模一样** ——
> 直到某天有人往取数层加了一行 UPDATE。

所以这里真往那个连接上写一次,**写得进去就是错**。

## ④ 一条永远不触发的分支

> 一条永远不触发的分支,和一条正确的分支,**在通过率上长得一模一样**。

所以报**每个码在当前库上有几个样本** —— **没有样本不叫通过,叫没测到**。
⚠️ 这一段**只报不拦**:库里有没有样本是造数的事,不是代码错误。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge"))
import slipping
import churn

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
坏 = []


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。三关缺一关这条记录就不算数:
# 对照先绿 / 改坏要红 / **红的必须是点名那一条**。
咬合 = [
    ("把要查的列名写成库里不存在的(比如 idle 写成 idle_day)",
     "要查的每一列都真实存在"),
    ("把活跃度轴在取数层抄一份,而不是从口径模块转发",
     "参数是转发的,不是抄的"),
    ("把只读连接换成普通连接(取数层就能写库了)",
     "取数用的连接是只读的"),
]


def ck(说, 得, want, 附=""):
    if 得 != want:
        坏.append(f"{说}:要 {want!r},得 {得!r}")
    print(f"  {G + '✅' + D if 得 == want else R + '❌' + D} {说:46s} {得!r}{附}")


def main():
    print("\033[1m▸ 流失预警取数 · 对账\033[0m")
    print("  " + "=" * 76)

    # ① 列名:**拿库里的实际列对账**,不是看代码里写了什么
    真列 = {r[1] for r in sqlite3.connect(slipping.DB)
            .execute("PRAGMA table_info(lifecycle_history)")}
    缺 = [c for c in slipping.列 if c not in 真列]
    ck("要查的每一列都真实存在", 缺, [],
       f"  ← 表里有 {len(真列)} 列,要查 {len(slipping.列)} 列")

    # 反向也验一次:**库里多出来的列要被看见**。
    # 新加一列判定依据而取数层没跟上,名单照样跑得出来 ——
    # 口径会拿一个 None 去判,而那个 None 不报错。
    没取的 = sorted(真列 - set(slipping.列) - {"source", "note", "created"})
    ck("没有漏掉新加的判定依据列", 没取的, [],
       "  ← 新加一列而取数层没跟上,口径会拿 None 去判而不报错")

    # ② 参数:**用 is**,比值的话抄一份出来也相等
    ck("参数是转发的,不是抄的",
       all(getattr(slipping, k) is getattr(churn, k)
           for k in ("活跃度轴", "价值标签", "严重", "下一步")), True,
       "  ← 比的是同一个对象,不是同一个值")

    # ③ 连接真的是只读的 —— **往它上面写一次**
    con = slipping._只读()
    try:
        con.execute("CREATE TABLE _写得进去吗(x INT)")
        写进去了 = True
    except sqlite3.OperationalError:
        写进去了 = False
    finally:
        con.close()
    ck("取数用的连接是只读的", 写进去了, False, "  ← 真往它上面写了一次")

    # ④ 取数和判定接得上:自己拼一遍 == 一个人的判断()
    有历史 = next(iter(slipping.查历史()), None)
    if 有历史 is None:
        print(f"  {Y}⏸{D} 库里一条档位历史都没有 —— **不适用,不是通过**")
    else:
        手拼 = churn.判(slipping.查历史([有历史])[有历史])
        ck("一个人的判断() 和手拼的一样",
           slipping.一个人的判断(有历史)["码"], 手拼["码"],
           f"  ← 样本 {有历史}")
        ck("查不到历史的客户不在返回值里",
           slipping.查历史(["这个客户号不存在"]), {},
           "  ← 「查不到」和「没在流失」是两件事")
        ck("而单独问他时给的是 NO_HISTORY",
           slipping.一个人的判断("这个客户号不存在")["码"], "NO_HISTORY")
        ck("给空名单不等于给 None(不许退化成查全部)",
           slipping.查历史([]), {})

    # ── 覆盖报告:**没有样本不叫通过,叫没测到** ────────────────────
    print()
    print("\033[1m▸ 流失预警 · 覆盖报告(没有样本不叫通过,叫没测到)\033[0m")
    print("  " + "=" * 76)
    from collections import Counter
    数 = Counter()
    严重数 = Counter()
    for cid, hs in slipping.查历史().items():
        w = churn.判(hs)
        数[w["码"]] += 1
        if w["要不要预警"]:
            严重数[w["严重程度"]] += 1
    总 = sum(数.values())
    if not 总:
        print(f"  {Y}⏸{D} 库里没有档位历史 —— C 方案的前提还不在")
    else:
        print(f"  {总} 个有历史的客户 → 要预警 {sum(严重数.values())} 人 "
              f"(高 {严重数['高']} / 中 {严重数['中']} / 低 {严重数['低']})")
        缺 = [k for k in churn.下一步 if 数[k] == 0]
        for k in churn.下一步:
            mark = f"{Y}⚠ 库里没有样本{D}" if 数[k] == 0 else ""
            print(f"     {k:14s} {数[k]:>6}  {mark}")
        if 缺:
            print(f"\n  {Y}⚠{D} 这几支在当前库上**一次都没触发**:{'、'.join(缺)}")
            print("     它们在 churn.py 的 68 条自测里是对的,"
                  "但**库里没有真实样本** ——")
            print("     **一条永远不触发的分支,和一条正确的分支,"
                  "在通过率上长得一模一样。**")
            print("     NO_HISTORY 恒空是因为造数给每个客户都造了 5 条历史;")
            print("     NEVER_BOUGHT 恒空是因为只给有单的客户造了历史。")

        # ── 「有多可惜」那三支分别有几个样本 ──────────────────
        # ⚠️ **这一段是 2026-10-05 真跑工具时才想到要加的。**
        # 当时全库 2649 条预警里,「曾经是忠诚而现在这个标签没了」是 **0 条** ——
        # 而 `MKT-10-03` 整节讲的就是那个情形,自测里也有一条(用的是 fixture)。
        # > 一支「fixture 里验过」的分支,和一支「真数据上跑过」的,
        # > **在自测的通过数上长得一模一样。**
        # 根因在造数:价值标签看的是近 12 个月实付/单数,而造出来的历史里
        # 这两个数每条都一样,只有闲置天数在变 ——
        # 真实业务里它们会随老订单滚出 12 个月窗口而衰减。
        可惜 = Counter()
        for cid, hs in slipping.查历史().items():
            w = churn.判(hs)
            if w["要不要预警"]:
                可惜["现在仍然是" if w["现在还是"] else
                     "曾经是但现在没了" if w["曾经是"] else "没有价值标签"] += 1
        print()
        print("  「有多可惜」这三支:")
        for k in ("现在仍然是", "曾经是但现在没了", "没有价值标签"):
            print(f"     {k:16s} {可惜[k]:>6}  "
                  f"{Y + '⚠ 库里没有样本' + D if not 可惜[k] else ''}")
        if not 可惜["曾经是但现在没了"]:
            print("     ⚠️ **「曾经是但现在没了」是 MKT-10-03 整节在讲的那个情形** ——")
            print("        造数没模拟「近 12 个月金额随老订单滚出窗口而衰减」,")
            print("        所以这一支在真数据上**一次都没跑过**(自测里用的是 fixture)。")
            print("        交数据工坊:见 fakedata/交数据工坊_营销SOP的数据缺口_20261004.md")

        # ⚠️ 这一条**只报不拦**,理由写在下面
        不符 = [r["customer_id"] for r in sqlite3.connect(slipping.DB).execute(
            """select h.customer_id from lifecycle_history h
               join customer c on c.id = h.customer_id
               where h.as_of = (select max(as_of) from lifecycle_history
                                 where customer_id = h.customer_id)
                 and h.lifecycle <> c.lifecycle""")]
        print()
        if 不符:
            print(f"  {Y}⚠{D} 历史最后一条和 `customer.lifecycle` "
                  f"对不上的有 {len(不符)} 个")
            print("     **不拦** —— 人工调整(`manual_lc`)本来就会让当前档位"
                  "偏离重算值,所以不等 ≠ 错。要查的是**有没有对应的 manual 记录**。")
        else:
            print("  ✅ 历史最后一条都等于 `customer.lifecycle`(0 个对不上)")

    print()
    if 坏:
        print(f"{R}❌ 流失预警取数 {len(坏)} 处不符合预期{D}")
        for b in 坏:
            print(f"    ❌ {b}")
        return 1
    print(f"{G}✅ 流失预警取数全部符合预期{D}")
    print("    判定口径的逐例真值在 knowledge/churn.py 的 74 条自测里 —— "
          "这里只验取数层特有的那四类错。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
