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
# ❹ 那条检查要读 `knowledge/fitting.py` —— 关键尺寸的**第二个来源**在它手里
sys.path[:0] = [os.path.join(os.path.dirname(HERE), "knowledge")]
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

    # ⓿ **`xingzhi` 是 `craft`(cat='形制')的结构化投影,必须和它一致。**
    #
    # 两张表都从 `01-形制.md` 派生。我建 `xingzhi` 的时候没先查,
    # **等于在讲「同一个事实两个来源必然漂」的下一步自己造了一个第二来源。**
    # 留着它是因为 `craft.detail` 把关键尺寸拍平在一个字符串里,SQL 校不了;
    # 而投影必须被钉住 —— **一个不被检查的投影,和一个第二来源没有区别。**
    ca = {r["code"]: r["name"] for r in c.execute(
        "SELECT code,name FROM craft WHERE cat='形制'")}
    xi = {r["code"]: r["name"] for r in c.execute("SELECT code,name FROM xingzhi")}
    差码 = (set(ca) ^ set(xi))
    差名 = {k for k in set(ca) & set(xi) if ca[k] != xi[k]}
    ck("形制投影和 craft(cat=形制)完全一致", not (差码 or 差名), len(ca),
       f"编码差 {sorted(差码)[:3]} / 名字差 {sorted(差名)[:3]}" if (差码 or 差名)
       else "两张表同源,一致靠检查而不是靠运气")

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

    # ❹ **关键尺寸有两个来源,必须说一样的话。**
    #    `01-形制.md` 的「- **关键尺寸**:」小点 → `xingzhi.key_sizes`(这张表)
    #    `08-量体与版型.md` 第二节的表格 → `fitting.key_sizes()`(推荐尺码在用)
    #    补 XZ41 宋制上襦 的时候才发现有第二处:只往 01 里写,`fitting.py` 当场断言失败
    #    (「这些形制没写关键尺寸,它们的推荐尺码全是瞎判的」)。那条断言拦住了「漏写」,
    #    **但它只验两边都有,不验两边说的一样** —— 一边写「胸围、肩宽、衣长」
    #    另一边写「胸围、腰围」,两个检查都绿,而推荐尺码按后者判、
    #    量体模板按前者校验,谁都不知道它们已经分家了。
    #    **同一个事实两个来源必然漂;删不掉的副本要变成被钉住的缓存。**
    import fitting as _ft
    两处 = _ft.key_sizes()
    不一致 = []
    for code, name, _al, ks, _st in c.execute(
            "SELECT code,name,alias,key_sizes,src_type FROM xingzhi ORDER BY code"):
        甲 = [x for x in (ks or "").split("、") if x]
        乙 = 两处.get(code)
        if 乙 is None:
            不一致.append(f"{code} {name}:08-量体与版型.md 里没有这一行")
        # **按集合比,不按顺序比** —— 关键尺寸是一组要量的项,
        # 谁先谁后不承载任何信息。按顺序比会把「08 写成腰围、肩宽、通袖长」
        # 和「01 写成肩宽、通袖长、腰围」判成不一致,那是**判据比事实还严**。
        elif {x.split("(")[0] for x in 甲} != {x.split("(")[0] for x in 乙}:
            不一致.append(f"{code} {name}:01 写「{'、'.join(甲)}」/ "
                        f"08 写「{'、'.join(乙)}」")
    ck("两处关键尺寸说的是同一件事", not 不一致, len(两处),
       ("、".join(不一致[:2]) if 不一致
        else "01-形制.md 和 08-量体与版型.md 各存了一份 —— 一致靠检查,不靠记性"))

    c.close()
    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 形制与量体模板 5 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
