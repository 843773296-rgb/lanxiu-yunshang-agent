#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""白坯试衣记录:**建表 + 按真实规则灌数据**。

## 该试衣的是哪几张,是**算出来的**,不是挑的

`intent/muslin-fitting.md` 写死了一条:「**不替它造假数据充数。
现有定制品订单里,该试衣的是哪几张要按真实规则算出来,不是随便挑几张标上。**」

所以这里对 47 条定制品订单行逐条跑 `muslin.按配置判()` ——
它读的是客户在 `item_part_choice` 里**实际选的工艺和面料**,
跑一遍真的工期推算,看它排不排得出「白坯试衣」那一段。

结果:**该试 8 行 / 不必 37 行 / 判不了 2 行**(那 2 行的商品没挂版型,
**留着不猜** —— 云肩和腰封本来就不是一件衣服)。

## 而「试没试、签没签」是**新数据**,这里怎么定的

这一半没有真值可算,是这次新造的。**但不随机撒**,按两条规则:

### ① 到没到试衣那一步,看订单开没开裁

白坯试衣在工期分段里**排在裁剪缝制之前**(见 `muslin.开裁之前`)——
这正是它存在的理由:裁下去就没有回头路。所以进了生产的单,
试衣窗口已经过去了;还没进生产的,**没试不是问题,是时候没到**。

### ② 签没签,**故意让四种状态都有活用例**

这一条是 `seed.py` 用血换来的教训(第 2117 行):

> 量体记录**全是「到店且记录完整」**,于是返修判定表里
> 「记录不全 → 我方免费改」和「远程量体 → 按合同分担」两行**永远命中不了**。

一条永远命中不了的判据,和没有这条判据是一样的 —— 而且它**看起来是有的**。
所以这里明确保证:「已试已签」「已试未签」「该试没试」**每种至少一条**。

⚠️ **这是为覆盖而选,不是为好看而选。** 「该试没试」那一条是往**我方**判的,
造出来对我们不利 —— 而正因如此它才必须存在:
一条只往有利方向走的判据,业务不会信,也不该信。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]

DDL = """
CREATE TABLE IF NOT EXISTS fitting(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  -- **挂在订单行上,不挂在订单上。**
  -- 一单可以给不止一个人做(实测 7 单是两件童款加一件女款,一家三口订同款),
  -- 而白坯是给**某一个人**试的 —— 挂在订单上只能挑一个填,而挑谁都不对。
  item_id INTEGER, order_id TEXT, wearer_id TEXT,
  -- 第几轮。一件衣服可以试不止一次(改完再试)。
  round INT DEFAULT 1,
  ts TEXT,                -- 什么时候试的
  -- 谁陪的。**只存工号**(2026-09-16 名字列全库删除)——
  -- 名字是 `staff` 的副本,页面拿工号现取。
  advisor_no TEXT,
  shop TEXT,
  adjust TEXT,            -- 改了哪几处
  -- ⚠️ **签没签字是这张表最值钱的一列。**
  -- 行业里试穿确认是**责任转移点**:客户签字之后再对尺寸提异议,
  -- 责任大幅偏向客方(09-养护与售后.md 第五节新加的两行)。
  --
  -- 而「没有这条记录」和「有记录但 signed=0」**不是一回事**:
  -- 前者是流程没走,后者是流程走了确认没拿到 —— 判责方向相反。
  -- 所以**不许用「查不到记录」来代替 signed=0**。
  signed INT DEFAULT 0,
  signed_at TEXT,
  note TEXT);
"""


def 该试的行(c):
    """对每条定制品订单行跑真的工期推算,看它该不该做白坯试衣。

    返回 (该试, 不必, 判不了) 三个列表。**判不了的留着,不猜。**
    """
    import muslin
    # 主料要挑**有幅宽**的那个 —— 里布 / 衬 / 线没有幅宽,
    # 那不是数据缺失,是它们本来就没有(135 种物料里 90 种没有)。
    mt = {r["name"]: r["code"] for r in
          c.execute("SELECT code,name FROM material WHERE width_cm IS NOT NULL")}
    kf = {r["name"]: r["code"] for r in c.execute("SELECT code,name FROM craft")}
    names = {r["code"]: r["name"] for r in c.execute("SELECT code,name FROM craft")}
    该, 不必, 判不了 = [], [], []
    for r in c.execute(
            "SELECT i.id,i.order_id,i.name,i.wearer_id,o.status,"
            "  o.advisor_no,o.shop,o.created,p.pattern FROM ordr_item i "
            "JOIN ordr o ON o.id=i.order_id LEFT JOIN product p ON p.spu=i.spu "
            "WHERE o.kind='定制品订单' ORDER BY i.id"):
        ch = list(c.execute("SELECT kind,material,part FROM item_part_choice "
                            "WHERE item_id=? ORDER BY id", (r["id"],)))
        ks = sorted({kf[x["material"]] for x in ch
                     if x["kind"] == "工艺" and x["material"] in kf})
        fab = [x for x in ch if x["kind"] == "面料" and x["material"] in mt]
        主 = next((x for x in fab if x["part"] in ("主身", "整件")),
                  fab[0] if fab else None)
        if not r["pattern"] or not 主:
            判不了.append((dict(r), "没挂版型" if not r["pattern"] else "没有带幅宽的面料"))
            continue
        # 「重工 / 婚服 / 满工」这几个字出现在品名里时,绣的是整幅不是局部。
        # **这是从品名读的,不是猜的** —— 品名里写着的就是商品实际卖的东西。
        scope = "整幅" if any(w in r["name"] for w in ("重工", "婚服", "满工")) else "局部"
        # 按**下单那天**算 —— 试不试是接单时定的(不传的话会取今天,判断随重建那天变)
        a, w = muslin.按配置判(r["pattern"], mt[主["material"]], ks, scope,
                               None, names, on=r["created"])
        if a is None: 判不了.append((dict(r), w))
        elif a: 该.append((dict(r), w))
        else: 不必.append(dict(r))
    return 该, 不必, 判不了


# 开没开裁 —— **由订单状态翻译过来,而 `muslin.归档` 只认「开没开裁」**。
# 白坯试衣排在裁剪缝制之前,所以进了生产就等于窗口过去了。
# ⚠️ 认不出的状态返回 None(不知道),**不默认成「没开裁」** ——
# 那会把一单「该试没试」悄悄判成不判责。
开裁之后 = ("生产中", "已生产", "待发货", "已发货", "待完成", "完成")
开裁之前 = ("待付款", "待审核", "待生产", "取消")


def 开裁了吗(status):
    if status in 开裁之后: return True
    if status in 开裁之前: return False
    return None


def main(apply=True):
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row
    c.executescript(DDL)
    该, 不必, 判不了 = 该试的行(c)
    print(f"定制品订单行 {len(该) + len(不必) + len(判不了)} 条:"
          f"**该试 {len(该)}** / 不必 {len(不必)} / 判不了 {len(判不了)}")
    for r, w in 判不了:
        print(f"    判不了 item{r['id']:>3} {r['name'][:24]} —— {w[:30]}")

    开了 = [(r, w) for r, w in 该 if 开裁了吗(r["status"])]
    没开 = [(r, w) for r, w in 该 if 开裁了吗(r["status"]) is False]
    print(f"\n  其中**已经开裁**的 {len(开了)} 条(试衣窗口已过)、"
          f"还没开裁的 {len(没开)} 条(没试不是问题,时候没到)")

    # ⚠️ **为覆盖而选,不是为好看而选。** 保证三种状态都有活用例:
    #   已开裁的第 1 条 → **该试没试**(往我方判,对我们不利 —— 正因如此才必须有)
    #   已开裁的第 2 条 → **已试未签**(流程走了,确认没拿到)
    #   其余已开裁的   → **已试已签**(责任转移点成立)
    c.execute("DELETE FROM fitting")
    rows = []
    for i, (r, _w) in enumerate(sorted(开了, key=lambda x: x[0]["id"])):
        if i == 0:
            continue   # 该试没试:**不建记录** —— 这正是它和「已试未签」的区别
        签 = (i != 1)
        日 = (r["created"] or "2026-08-01")[:10]
        rows.append((r["id"], r["order_id"], r["wearer_id"], 1,
                     f"{日} 14:00", r["advisor_no"], r["shop"],
                     "袖长 -1.5cm、腰围 +2cm" if 签 else "肩宽待定,客户要回去想想",
                     1 if 签 else 0, f"{日} 15:30" if 签 else None,
                     "客户到店试穿白坯,当场确认合身并签字" if 签
                     else "**试了但没签字** —— 客户说回去和家里商量"))
    c.executemany(
        "INSERT INTO fitting(item_id,order_id,wearer_id,round,ts,advisor_no,"
        "  shop,adjust,signed,signed_at,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
    if apply: c.commit()

    import muslin
    print(f"\n  灌了 {len(rows)} 条试衣记录。四种状态的覆盖:")
    for r, _w in sorted(该, key=lambda x: x[0]["id"]):
        f = c.execute("SELECT signed FROM fitting WHERE item_id=?", (r["id"],)).fetchone()
        st = muslin.归档(True, 开裁了吗(r["status"]), bool(f), bool(f and f["signed"]))
        print(f"    item{r['id']:>3} [{r['status']:4s}] {st or '**判不了**':6s} "
              f"{r['name'][:26]}")
    有 = {muslin.归档(True, 开裁了吗(r["status"]),
                      bool(c.execute("SELECT 1 FROM fitting WHERE item_id=?",
                                     (r["id"],)).fetchone()),
                      bool(c.execute("SELECT signed FROM fitting WHERE item_id=? "
                                     "AND signed=1", (r["id"],)).fetchone()))
           for r, _ in 该}
    print(f"\n  覆盖到的状态:{sorted(x for x in 有 if x)}")
    缺 = {"该试没试", "已试未签", "已试已签"} - 有
    if 缺:
        print(f"  ❌ **没覆盖到:{sorted(缺)}** —— 一条永远命中不了的判据"
              f"和没有这条判据是一样的,而且它看起来是有的")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
