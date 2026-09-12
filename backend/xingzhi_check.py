# -*- coding: utf-8 -*-
"""形制与量体模板的检查 —— **模板必须覆盖这个形制的关键尺寸。**

`01-形制.md` 每个形制写着「关键尺寸」:

    XZ04 明制立领长衫 → **领围**、肩宽、胸围、腰围、衣长、通袖长
    XZ01 唐制齐胸襦裙 → 胸围、**胸上围**、身高
    XZ05 大袖衫       → **通袖长**(指尖到指尖)、衣长

而量体模板(LT01–LT06)是**整批指派**的。两者对不对得上,原来没有任何地方在验 ——
因为 `pattern.xz` 指向的形制表**根本不存在**(形制只活在 md 里)。

**漏一项关键尺寸的后果不是「少量一个数」**,是这个形制最敏感的那一项没量:
立领对领围 ±1cm 就影响舒适、大袖衫量成袖长而不是通袖长会整件报废
(`measure_item` 自己写着「量错整件报废」)。

## 这条检查的期望值从哪来

从 md 派生的 `xingzhi.key_sizes`,不是我手抄的。
md 改了、推导器重跑,这条检查跟着变 —— 这是这个项目的分层:
**md 是真相源,推导器算结论落库,检查对账。**
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("形制与量体模板 · 检查")
    print("=" * 84)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row

    # ① `pattern.xz` 不许指向形制表里没有的编码。
    孤 = [r[0] for r in c.execute(
        "SELECT DISTINCT xz FROM pattern WHERE xz NOT IN (SELECT code FROM xingzhi)")]
    n1 = c.execute("SELECT COUNT(DISTINCT xz) FROM pattern").fetchone()[0]
    ck("版型引用的形制都存在", not 孤, n1,
       f"孤儿 {孤}" if 孤 else "补这张表之前,xz 是个指向空处的外键")

    # ② **量体模板必须覆盖形制的关键尺寸。**
    名到码 = {r["name"]: r["code"] for r in c.execute("SELECT code,name FROM measure_item")}
    n2 = 0; 缺 = []
    for r in c.execute("""SELECT t.code,t.name pn,t.tpl,z.code xz,z.name zn,z.key_sizes
                          FROM pattern t JOIN xingzhi z ON z.code=t.xz
                          WHERE z.key_sizes IS NOT NULL"""):
        n2 += 1
        有 = {x[0] for x in c.execute("SELECT item FROM tpl_item WHERE tpl=?", (r["tpl"],))}
        for 尺 in r["key_sizes"].split("、"):
            码 = 名到码.get(尺)
            if 码 and 码 not in 有:
                缺.append((r["code"], r["pn"][:14], r["tpl"], 尺))
    ck("量体模板覆盖形制的关键尺寸", not 缺, n2,
       f"漏了 {len(缺)} 处,例:{缺[:3]}" if 缺 else
       "漏一项不是「少量一个数」,是这个形制最敏感的那一项没量")

    # ③ 关键尺寸里写的名字,量体项表里都得有。
    #    **文档里写了而系统里没有的尺寸,永远量不到** ——
    #    这一段里已经撞见三次(头围/腕围/脚长就是这么补出来的)。
    n3 = 野 = 0; 例3 = []
    for r in c.execute("SELECT code,name,key_sizes FROM xingzhi WHERE key_sizes IS NOT NULL"):
        for 尺 in r["key_sizes"].split("、"):
            n3 += 1
            if 尺 not in 名到码:
                野 += 1
                if len(例3) < 5: 例3.append((r["code"], 尺))
    ck("形制里写的关键尺寸,量体项表里都有", 野 == 0, n3,
       f"**文档里有而系统里没有** {例3}" if 野 else "")

    c.close()
    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 形制与量体模板 3 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
