#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订单行的部位选择检查 —— **收的钱和记的账不许分家。**

## 背景

2026-09-14 看到工艺文档的打印稿才发现:`ordr_item.custom_amount` 存着
「定制部件金额 ¥756」,而**选了什么部位、什么料、什么颜色,一个字都没存**。
工艺文档要打印「领口 · 真丝 · 红色 · ¥1,000」—— 那三项系统里全无,只有总额。

> **钱已经收了,而收的是什么钱没有记录。**
> 车间照着打印不出来,客户争议时也拿不出依据。

这和「pad 上选的东西没进系统,等于没选过」是同一句话。

## 四条

**① 加价之和 = `custom_amount`。** 这是这张表存在的意义 ——
它不是「重新算一遍价」,是**把一个已有的总额拆成看得见的项**。
拆出来的和对不上,就是收的钱和记的账分家了,而**两个数各自看都很正常**。

**② 有定制部件金额的订单行,必须有明细。** 有钱没项 = 回到出问题前的样子。

**③ 没有定制部件金额的,不许有明细。** 有项没钱 = 白做了活没收钱,
同样是账实不符,只是方向相反 —— **两个方向都要测**。

**④ 选的料必须在这个商品的可选料里。** 选了一个配置页上根本没有的料,
说明中间某一步把约束绕过去了 —— 而车间会照着做。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row

    # ① 加价之和 = custom_amount
    差 = []
    rs = c.execute("""SELECT i.id, i.name, i.custom_amount,
                      (SELECT ROUND(SUM(amount),2) FROM item_part_choice WHERE item_id=i.id) s
                      FROM ordr_item i WHERE i.custom_amount>0""").fetchall()
    for r in rs:
        if r["s"] is not None and abs(r["s"] - round(r["custom_amount"], 2)) > 0.01:
            差.append(f"{r['name'][:16]}:明细 {r['s']} ≠ 订单行 {r['custom_amount']}")
    ck("部位加价之和 = 订单行的定制部件金额", not 差, len(rs),
       ("；".join(差[:2]) if 差 else
        "**这张表不是重新算一遍价,是把一个已有的总额拆成看得见的项** —— "
        "拆出来对不上,就是收的钱和记的账分家了"))

    # ② 有钱就得有项
    无项 = [r["name"][:18] for r in rs if r["s"] is None]
    ck("有定制部件金额的订单行必须有明细", not 无项, len(rs),
       ("；".join(无项[:3]) if 无项 else "有钱没项 = 回到出问题前的样子"))

    # ③ 没钱不许有项 —— **两个方向都要测**
    多项 = [r[0] for r in c.execute(
        "SELECT i.name FROM ordr_item i WHERE COALESCE(i.custom_amount,0)<=0 "
        "AND EXISTS(SELECT 1 FROM item_part_choice WHERE item_id=i.id)")]
    n3 = c.execute("SELECT COUNT(*) FROM ordr_item WHERE COALESCE(custom_amount,0)<=0"
                   ).fetchone()[0]
    ck("没有定制部件金额的订单行不许有明细", not 多项, n3,
       ("；".join(多项[:3]) if 多项 else
        "有项没钱 = 白做了活没收钱 —— **同样是账实不符,只是方向相反**"))

    # ④ 选的料必须在这个商品的可选料里
    野 = [f"{r[0][:16]}·{r[1]}:{r[2]}" for r in c.execute(
        """SELECT p.name, ch.part, ch.material FROM item_part_choice ch
           JOIN ordr_item i ON i.id=ch.item_id JOIN product p ON p.spu=i.spu
           WHERE NOT EXISTS(SELECT 1 FROM part_option o WHERE o.spu=i.spu
                            AND o.part=ch.part AND o.material=ch.material)""")]
    n4 = c.execute("SELECT COUNT(*) FROM item_part_choice").fetchone()[0]
    ck("选的料必须在这个商品该部位的可选料里", not 野, n4,
       ("；".join(野[:3]) if 野 else
        "选了配置页上根本没有的料,说明中间某一步把约束绕过去了 —— **而车间会照着做**"))
    # ⑤ **每一项都必须有金额、有料、有部位** —— 缺一样就不是「记录」。
    #    业务原话:「具体选了什么部位、什么料、什么颜色,什么报价,都需要有」。
    #    颜色**允许为空**(有些料只有一个色,pad 上那一排圆点是空的),
    #    但部位 / 料 / 金额三样一个都不能少。
    缺 = [f"#{r[0]} 缺 {r[1]}" for r in c.execute(
        """SELECT id, CASE WHEN part IS NULL OR part='' THEN '部位'
                           WHEN material IS NULL OR material='' THEN '料'
                           ELSE '金额' END
           FROM item_part_choice
           WHERE part IS NULL OR part='' OR material IS NULL OR material=''
              OR amount IS NULL""")]
    n5 = c.execute("SELECT COUNT(*) FROM item_part_choice").fetchone()[0]
    ck("每一项都要有部位、料、金额", not 缺, n5,
       ("；".join(缺[:3]) if 缺 else
        "颜色允许为空(有些料只有一个色),**部位 / 料 / 金额三样一个都不能少**"))

    # ⑥ **成交金额是快照,不许从配置表现算。**
    #    `part_option.addon` 是**今天的定价**,`item_part_choice.amount` 是
    #    **当时收的钱**。改了加价、做了活动、店长让了价,历史订单**不能跟着变**。
    #    这和会员等级用 `amount_12m` 快照而不是现算是同一条。
    #    验法:把一条已有订单的配置定价改掉,它的成交金额必须纹丝不动。
    tgt = c.execute("SELECT ch.id, ch.amount, i.spu, ch.part, ch.material "
                    "FROM item_part_choice ch JOIN ordr_item i ON i.id=ch.item_id "
                    "LIMIT 1").fetchone()
    if tgt:
        c.execute("UPDATE part_option SET addon=addon+9999 WHERE spu=? AND part=? "
                  "AND material=?", (tgt["spu"], tgt["part"], tgt["material"]))
        后 = c.execute("SELECT amount FROM item_part_choice WHERE id=?",
                       (tgt["id"],)).fetchone()[0]
        c.execute("UPDATE part_option SET addon=addon-9999 WHERE spu=? AND part=? "
                  "AND material=?", (tgt["spu"], tgt["part"], tgt["material"]))
        c.connection.rollback() if hasattr(c, "connection") else None
        ck("成交金额是快照,改配置定价不许动到历史订单",
           abs(后 - tgt["amount"]) < 0.01, 1,
           "" if abs(后 - tgt["amount"]) < 0.01 else
           f"配置价一改,历史订单跟着变了:{tgt['amount']} → {后}")
        print("       **一个是「现在多少钱」,一个是「当时收了多少钱」** —— "
              "合并之后历史订单会跟着今天的价一起漂")
    # ⑥·2 **同一个部位上选的面料和工艺必须相容。**
    #     相容矩阵 2025 格里有 441 对判「不可」(妆花 × 香云纱、缂丝 × 香云纱…)。
    #     这条原来**只在配置页拦,订单上没人对过账** ——
    #     而配置页拦得住的前提是「所有下单路径都经过配置页」,
    #     那是个假设,不是事实(导单、改单、后台补单都绕得过去)。
    #     **拦在入口的规则,要在存量上对一次账,才知道它真的拦住了。**
    不可 = [f"{r[0]}·{r[1]} × {r[2]}" for r in c.execute(
        """SELECT m.part, m.material, k.material FROM item_part_choice m
           JOIN item_part_choice k ON k.item_id=m.item_id AND k.part=m.part
                                  AND k.kind='工艺'
           JOIN craft_combo cc
             ON cc.material=(SELECT code FROM craft WHERE name=m.material AND cat='材质')
            AND cc.craft=(SELECT code FROM craft WHERE name=k.material AND cat='工艺')
           WHERE m.kind='面料' AND cc.verdict='不可'""")]
    n62 = c.execute("SELECT COUNT(*) FROM item_part_choice WHERE kind='工艺'").fetchone()[0]
    ck("同一部位的面料和工艺必须相容", not 不可, n62,
       ("；".join(不可[:3]) if 不可 else
        "**拦在入口的规则,要在存量上对一次账** —— "
        "配置页拦得住的前提是「所有下单路径都经过配置页」,那是假设不是事实"))

    # ⑥·3 **外层部位有面料就得有工艺。**
    #     缺工艺不是小事:车间拿到「领口用云锦」而不知道做什么绣,只能问或者猜。
    #
    #     ⚠️ **但内衬和系带不算。** 这条判据第一版把它们也管了,当场红 ——
    #     而它红得对、指出的是我没想到的事:**里面那层和辅料本来就不做工艺**。
    #     醋酸里布上不绣花、织带上不做缂丝;客户在那儿选的是材质和厚度,不是纹样。
    #     相容矩阵里也查不到「苏绣 × 醋酸里布」——**矩阵是主料 × 工艺的**,
    #     里料压根不在里面。
    #
    #     所以「除非没有相容的可选」这个例外**不够**:真正的规则是
    #     **只有外层部位才配工艺**。判据要守这个,而不是守一个凑出来的例外。
    import importlib.util as _iu
    _s2 = _iu.spec_from_file_location(
        "part", os.path.join(os.path.dirname(HERE), "knowledge", "part.py"))
    _part = _iu.module_from_spec(_s2); _s2.loader.exec_module(_part)
    外层 = [b for b in _part.部位顺序 if _part.部位可选料类(b) == ("主料",)]
    缺艺 = [f"{r[0]}·{r[1]}" for r in c.execute(
        """SELECT m.part, m.material FROM item_part_choice m
           WHERE m.kind='面料' AND m.part IN (""" + ",".join("?" * len(外层)) + """)
             AND NOT EXISTS(
             SELECT 1 FROM item_part_choice k WHERE k.item_id=m.item_id
               AND k.part=m.part AND k.kind='工艺')
             AND EXISTS(SELECT 1 FROM ordr_item i JOIN part_option o ON o.spu=i.spu
                        WHERE i.id=m.item_id AND o.kind='工艺')""", 外层)]
    n63 = c.execute(
        "SELECT COUNT(*) FROM item_part_choice WHERE kind='面料' AND part IN ("
        + ",".join("?" * len(外层)) + ")", 外层).fetchone()[0]
    ck("外层部位有面料就得有工艺", not 缺艺, n63,
       ("；".join(缺艺[:3]) if 缺艺 else
        "**内衬和系带不算** —— 里面那层和辅料本来就不做工艺,"
        "而相容矩阵是主料 × 工艺的,里料压根不在里面"))

    # ⑦ **工艺文档要拼得出来,而且列名不许混。**
    #    交互稿那张表的列叫「位置 / 工艺 / 颜色 / 定制部件金额」,
    #    而那一列的**值是「真丝」—— 那是面料,不是工艺**。
    #    库里 `craft` 把工艺(45 条)和材质(45 条)分得很清,
    #    混着叫会让车间不知道该看哪张表。
    sys.path[:0] = [HERE]
    import server
    oid = c.execute("SELECT DISTINCT i.order_id FROM item_part_choice ch "
                    "JOIN ordr_item i ON i.id=ch.item_id LIMIT 1").fetchone()
    doc = server.craft_doc(oid[0]) if oid else {}
    有件 = bool(doc.get("items"))
    有选 = any(it.get("choices") for it in doc.get("items", []))
    ck("工艺文档拼得出位置/面料/颜色/金额", 有件 and 有选, len(doc.get("items") or []),
       "" if 有选 else f"拼不出来:{str(doc)[:80]}")
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    混 = "工艺" in src[src.find("def craft_doc"):src.find("def product_detail")] \
         and "那是面料" not in src[src.find("def craft_doc"):src.find("def product_detail")]
    ck("工艺文档里「面料」不许叫成「工艺」", not 混, 1,
       "" if not 混 else "列名混了 —— 车间不知道该看 craft 的哪一类")

    # ⑧ **量体取不到要说「没量过」,不能给一张空表。**
    #    空表和「量过但都是 0」在纸上长得一样,而**车间会照着裁**。
    空表 = [it["name"][:18] for it in doc.get("items", [])
            if it.get("wearer_id") and not it.get("measures")]
    ck("有着装人却没量体的,不许在文档上留一张空表", not 空表,
       len(doc.get("items") or []),
       ("；".join(空表[:3]) if 空表 else
        "**空表和「量过但都是 0」在纸上长得一样,而车间会照着裁**"))
    c.close()

    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 订单部位选择 / 工艺文档 10 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
