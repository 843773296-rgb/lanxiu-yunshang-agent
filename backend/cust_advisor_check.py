#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订单上那一列「客户现在归谁」的检查 —— **两份数据说同一件事,就会漂。**

2026-10-25 加。`ordr.cust_advisor_no` 是从 `customer.advisor_no` 冗余过来的,
为的是让顾问那条范围条件里的 `OR` 落在同一张表上(19–20 ms → 8.22 ms,2.3 倍)。

**冗余的代价不是磁盘,是「两份数据说同一件事」** ——
客户换了顾问而订单上这一列没跟着改,顾问的订单清单就少几条,**而且不报错**。
门店关联键那条线(`shop` 显示串 + `shop_code` 编码)为这个形状花了两天才守住,
而 2026-10-25 早上还红了一次:**每日平移那条路径漏了回填**,
缺口当天隐形、第二天才红。

所以这一列用**触发器**做同步(数据库层保证,「结构」),
而不是在每一处写口后面加 UPDATE(「靠记得」,是「约定」)。
这套检查守三层:

    ① 自造最小库   三个触发器的**行为**对不对 —— 不依赖真库里碰巧有什么
    ② 真库         逐行对账 + 孤儿单单独报
    ③ 源码         那条查询读的是**订单上那一列**,不是跨表那一列;两条流水线都挂着

⚠️ **第①层是必须的。** 第②层在真库上跑,而真库里**不会有**「触发器失效」这种状态
(真有的话第②层就红了)—— 于是「触发器的行为还对不对」在真库上**不可观测**:
把三个触发器全删掉再回填一次,第②层照样全绿。
> 一条在真数据上全绿的判据,和一个什么都不做的触发器,**长得一模一样**。

⚠️ **第③层守的是「改回去不会有任何东西红」那个口。**
把查询从 `o.cust_advisor_no` 改回 `cu.advisor_no`,**结果一模一样、只是慢** ——
所有功能测试都会过,这一列也照旧对得上。**只有源码上看得出来。**
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "tools")]
import add_cust_advisor as _ca            # noqa: E402  触发器 DDL 的唯一来源,不手抄

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

咬合 = [
    # ⚠️ 四条攻击都打在**被守的那个东西**上,没有一条打在判据自己身上。
    ("把「客户换顾问」那个触发器的 DDL 改成只同步未完成的单(照抄 appointment 那边的部分同步)",
     "客户换顾问,他名下的单全部跟着改"),
    # ⚠️ 这一条原来攻的是 dict 的 **key**(改成 `_去掉了_…`)—— 不行:
    # 「三个触发器都在」那条会**先红**,于是红的不是点名这一条。
    # 改成让**行为**错而名字不动:body 填 NULL。
    ("把「新开一单自动填」那个触发器的 body 改成填 NULL(名字还在,行为没了)",
     "新开一单(没写那一列)触发器自动填上"),
    # 这一条守第③层:改回跨表那一列,**结果一样、只是慢**,
    # 所以功能测试全过、逐行对账也全绿 —— 只有源码上看得出来。
    # ⚠️ **左边这句话必须和 bite_specs 里那条的「改坏」一字不差** ——
    # `bite_check` 按它配对。2026-10-25 这一条差了「,功能测试全过」五个字,
    # 欠债涨 1、门禁红在一个跟业务代码毫无关系的地方。**今天第三次踩这个。**
    ("把顾问那条范围条件改回 `cu.advisor_no=?`(跨表 OR,结果一样只是慢,功能测试全过)",
     "顾问那条范围条件读的是订单上那一列"),
    ("把 `--校验` 那一步从 daily_shift.sh 里删掉(触发器哪天没了,当天完全隐形)",
     "每日平移那条路径也体检这一列"),
]

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


# ── ① 自造最小库:三个触发器的行为 ─────────────────────────────────
def 层一():
    print("\n── ① 自造最小库 · 三个触发器的行为(不依赖真库里碰巧有什么)──")
    c = sqlite3.connect(":memory:")
    c.executescript("""
    CREATE TABLE customer(id TEXT PRIMARY KEY, advisor_no TEXT);
    CREATE TABLE ordr(id TEXT PRIMARY KEY, customer_id TEXT, status TEXT,
                      advisor_no TEXT, cust_advisor_no TEXT);
    """)
    for ddl in _ca.触发器.values():          # **DDL 从工具里取,不在这儿抄一份**
        c.executescript(ddl + ";")
    # ⚠️ **具名列。** `insert_shape_check` 盯着这件事:
    # 「列数恰好相等而顺序错了是不报错的」,值会整体挪一格。
    c.executemany("INSERT INTO customer(id, advisor_no) VALUES(?,?)",
                  [("C1", "A001"), ("C2", "A002")])

    # 开单:**不写那一列**,触发器要填上
    for i in range(3):
        # ⚠️ **带上 status,而且让其中一单是「完成」。**
        # 咬合里那条「照抄 appointment 的部分同步」
        # (`AND status NOT IN ('完成','已取消')`)要靠它才攻得进来:
        # 最小库里没有这一列的话,那条攻击会**崩**在 `no such column`,
        # 而「崩了」和「漏了」该触发的动作不同 —— 咬合会报「红的不是那一条」。
        c.execute("INSERT INTO ordr(id, customer_id, status, advisor_no) VALUES(?,?,?,?)",
                  (f"O{i}", "C1", "完成" if i == 0 else "待付款", "B999"))
    填上的 = [r[0] for r in c.execute(
        "SELECT cust_advisor_no FROM ordr WHERE customer_id='C1'")]
    ck("新开一单(没写那一列)触发器自动填上",
       填上的 == ["A001"] * 3, len(填上的),
       f"填出来是 {填上的} —— **开单不填就是一个新缺口**,"
       f"而它只在那个顾问的清单上少几条,不报错" if 填上的 != ["A001"] * 3
       else "三单都填成了客户当前的顾问号")

    # 客户换顾问:名下**全部**订单跟着改(不是只改未完成的)
    c.execute("UPDATE customer SET advisor_no='A777' WHERE id='C1'")
    同步后 = [r[0] for r in c.execute(
        "SELECT cust_advisor_no FROM ordr WHERE customer_id='C1'")]
    ck("客户换顾问,他名下的单全部跟着改",
       同步后 == ["A777"] * 3, len(同步后),
       f"同步后是 {同步后} —— ⚠️ **必须全量**。`appointment` 那边用的是 "
       f"`AND status='已预约'`(只动还没发生的预约),**那是对的,照抄过来就是错的**:"
       f"查询问的是「客户**现在**归谁」、不分订单状态" if 同步后 != ["A777"] * 3
       else "三单全改了(全量同步,不是只改未完成的)")

    # 订单换客户:重算(削峰 / 造数会这么干)
    c.execute("UPDATE ordr SET customer_id='C2' WHERE id='O0'")
    换客户后 = c.execute("SELECT cust_advisor_no FROM ordr WHERE id='O0'").fetchone()[0]
    ck("订单换了客户,那一列重算",
       换客户后 == "A002", 1,
       f"重算成了 {换客户后!r},该是 'A002' —— 削峰(`level_customer_orders.py`)"
       f"和造数(`order_mix.py`)都会改 `ordr.customer_id`"
       if 换客户后 != "A002" else "跟着新客户的顾问号走了")
    c.close()


# ── ② 真库:逐行对账 ──────────────────────────────────────────────
def 层二():
    print("\n── ② 真库 · 逐行对账 ──")
    db = os.path.join(HERE, "lanxiu.db")
    if not os.path.exists(db):
        ck("真库在", False, 0, "没有 backend/lanxiu.db")
        return
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    有列 = "cust_advisor_no" in {r[1] for r in c.execute("PRAGMA table_info(ordr)")}
    ck("ordr 上有那一列", 有列, 1,
       "列不在 —— 跑 `python3 tools/add_cust_advisor.py --建列`" if not 有列 else "在")
    if not 有列:
        c.close()
        return
    缺 = [名 for 名 in _ca.触发器
          if 名 not in {r[0] for r in c.execute(
              "SELECT name FROM sqlite_master WHERE type='trigger'")}]
    ck(f"三个触发器都在(登记 {len(_ca.触发器)} 个)", not 缺, len(_ca.触发器),
       f"这几个不在:{缺} —— **触发器活在库里,而库不进版本库**:"
       f"谁手工重建一次库而没跑 `--建列`,它就没了,"
       f"**而那时数据开始漂、没有任何东西会红**" if 缺 else "开单填 / 换顾问同步 / 换客户重算")

    总 = c.execute("SELECT COUNT(*) FROM ordr o JOIN customer cu ON cu.id=o.customer_id").fetchone()[0]
    ck(f"对得上账的行数够得上验(扫了 {总} 行)", 总 >= 1000, 总,
       f"只扫到 {总} 行 —— **这不是通过,是没扫到东西**(下限 1000 只防空扫)"
       if 总 < 1000 else "下限 1000 只防空扫,不是说该有多少行")
    坏 = c.execute(
        "SELECT o.id, o.cust_advisor_no, cu.advisor_no FROM ordr o "
        "JOIN customer cu ON cu.id=o.customer_id "
        "WHERE o.cust_advisor_no IS NOT cu.advisor_no LIMIT 5").fetchall()
    n坏 = c.execute(
        "SELECT COUNT(*) FROM ordr o JOIN customer cu ON cu.id=o.customer_id "
        "WHERE o.cust_advisor_no IS NOT cu.advisor_no").fetchone()[0]
    ck("每一单那一列都和客户当前的顾问号对得上", not n坏, 总,
       f"{n坏} 行对不上,例:{坏} —— **两份数据说同一件事就会漂,而漂了不报错**。"
       f"先跑 `python3 tools/add_cust_advisor.py --校验` 看是不是触发器没在工作,"
       f"**别只回填一下就算了**" if n坏 else f"{总} 行一行不差")

    # **孤儿单单独报**,不混进对账 —— 混进来的话「触发器漏了」和
    # 「数据里有指向不存在客户的单」会长得一样,而下一步完全不同。
    孤 = c.execute(
        "SELECT COUNT(*) FROM ordr o LEFT JOIN customer cu ON cu.id=o.customer_id "
        "WHERE o.customer_id IS NOT NULL AND cu.id IS NULL").fetchone()[0]
    print(f"     ℹ 另有 {孤} 单的 customer_id 指向不存在的客户 —— "
          f"**那是另一件事**(孤儿单),不在这一列的职责里。"
          f"混进上面那条对账的话,「触发器漏了」和「有孤儿单」会长得一样")
    c.close()


# ── ③ 源码:查询读的是哪一列、流水线挂着没 ───────────────────────
def 层三():
    print("\n── ③ 源码 · 读对了列、挂进了流水线 ──")
    api = open(os.path.join(HERE, "api.py"), encoding="utf-8").read()
    对 = "AND (o.advisor_no=? OR o.cust_advisor_no=?)" in api
    跨表 = "AND (o.advisor_no=? OR cu.advisor_no=?)" in api
    ck("顾问那条范围条件读的是订单上那一列", 对 and not 跨表, 1,
       ("找不到 `o.cust_advisor_no` 那条片段" if not 对 else
        "还留着跨表那条 `cu.advisor_no=?`") +
       " —— ⚠️ **改回跨表那一列,结果一模一样、只是慢**:"
       "所有功能测试都会过,逐行对账也全绿,**只有源码上看得出来**"
       if not (对 and not 跨表) else "`o.cust_advisor_no`,不是跨表那一列")

    rb = open(os.path.join(ROOT, "tools", "rebuild.sh"), encoding="utf-8").read()
    ds = open(os.path.join(ROOT, "tools", "daily_shift.sh"), encoding="utf-8").read()
    # ⚠️ 查的是**那一次调用**,不是「脚本名出现过没有」——
    # 门店码那条判据 2026-10-24 就栽在查脚本名上(加了两个 `--建列` 让名字永远都在)。
    ck("重建流水线里建触发器那一步在(紧跟 seed.py)",
       "add_cust_advisor.py --建列" in rb, 1,
       "`rebuild.sh` 里没有那一步 —— **从零重建出来的库没有触发器**,"
       "而本地库上完全隐形(触发器早就在了)" if "add_cust_advisor.py --建列" not in rb
       else "在")
    ck("重建流水线最后体检了这一列",
       "add_cust_advisor.py --校验" in rb, 1,
       "`rebuild.sh` 最后没有那一步 —— 造数造完没人确认触发器真的在工作"
       if "add_cust_advisor.py --校验" not in rb else "在")
    ck("每日平移那条路径也体检这一列",
       "add_cust_advisor.py --校验" in ds, 1,
       "`daily_shift.sh` 里没有那一步 —— 触发器哪天没了(谁手工重建了库),"
       "**当天完全隐形**,而数据从那一刻开始漂。"
       "⚠️ 2026-10-25 早上门店码那条红就是这个形状:重建流水线有、每日那条没有"
       if "add_cust_advisor.py --校验" not in ds else "在")


def main():
    print("订单上「客户现在归谁」那一列 · 检查")
    print("=" * 84)
    层一()
    层二()
    层三()
    print()
    if FAIL:
        print(f"{Rd}❌ {len(FAIL)} 处不符合预期{D}")
        for x in FAIL:
            print(f"   · {x}")
        return 1
    print(f"{G}✅ 全部符合预期{D}")
    print("    这一列是冗余的,**而冗余的代价不是磁盘,是「两份数据说同一件事」** ——")
    print("    同步由三个触发器保证(结构),不靠每处写口记得加一句(约定)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
