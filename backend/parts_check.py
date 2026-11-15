#!/usr/bin/env python3
"""分部位选料两个读工具 · part_options / order_parts(用户清单第六条;体检:可选料 2606 + 已选 24411,原来零工具零评测)。

在**库副本**上真调工具,并在副本里故意造三种对不上,验 order_parts 三项核对真的核得出来;再验范围跟身份走。

    python3 backend/parts_check.py
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api  # noqa: E402
import check_copy  # noqa: E402

db = check_copy.用副本("parts-")
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏 = []

咬合 = [
    ("去掉「加价合计 vs 定制部件金额」那一项对账", "加价合计对不上定制部件金额时核得出来"),
    ("去掉「选的料在不在可选范围里」那一项对账", "选的料不在这款的可选范围里时核得出来"),
    ("order_parts 不再按身份限范围(where 片段丢掉)", "顾问看不到不归他的单"),
]


def ck(名, ok, 话=""):
    print(f"  {G + '✅' if ok else R + '❌'}{D} {名}" + (f"  {话}" if 话 else ""))
    if not ok:
        坏.append(名)


print("分部位选料 · part_options / order_parts")
c = sqlite3.connect(db)
spu = c.execute("SELECT spu FROM part_option GROUP BY spu ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]

# ① part_options:部位按顺序、每个部位带用料来源;多款命中给候选;查不到明说
r = api.part_options(spu)
ck("part_options 按商品编号查得到部位,每个部位带可选面料 / 工艺和用料来源",
   bool(r.get("部位")) and all("用料来源" in b and (b["可选面料"] or b["可选工艺"]) for b in r["部位"]),
   f"{r.get('款名')} · {[b['部位'] for b in r.get('部位', [])]}")
import part as _part  # noqa: E402
顺 = [b["部位"] for b in r["部位"] if b["部位"] in _part.部位顺序]
ck("部位按 knowledge/part.py 的顺序排(客户看的是领口→主身→袖→裙,不是库里的插入顺序)",
   顺 == sorted(顺, key=_part.部位顺序.index), f"{顺}")
多 = api.part_options("裙")
ck("名字对上不止一款时返回候选,不替人挑", "候选" in 多 and 多.get("hit", 0) > 1, f"hit={多.get('hit')}")
ck("查不到的款明说查不到", "error" in api.part_options("这款不存在ZZZ"))

# ② order_parts:选一张有选料、而且只有一行明细的单,在副本里造三种对不上
api.whoami = lambda: {"role": "总部运营", "no": "U001", "shop": None}
oid, iid = c.execute("SELECT i.order_id, i.id FROM ordr_item i JOIN item_part_choice p ON p.item_id=i.id "
                     "GROUP BY i.id HAVING COUNT(*) >= 2 ORDER BY i.id LIMIT 1").fetchone()
基 = api.order_parts(oid)
行 = [m for m in 基["明细"] if m["明细"] == iid][0]
ck("原样的单三项都对得上(对照)", 行["核对"] == ["三项都对得上"] or all("需评估" in x for x in 行["核对"]), f"{行['核对'][:2]}")
pid = c.execute("SELECT id FROM item_part_choice WHERE item_id=? ORDER BY id LIMIT 1", (iid,)).fetchone()[0]
c.execute("UPDATE item_part_choice SET amount=COALESCE(amount,0)+100 WHERE id=?", (pid,)); c.commit()
m = [x for x in api.order_parts(oid)["明细"] if x["明细"] == iid][0]
ck("加价合计对不上定制部件金额时核得出来", any("对不上" in x for x in m["核对"]), f"{m['核对'][:2]}")
c.execute("UPDATE item_part_choice SET amount=amount-100, material='不存在的料' WHERE id=?", (pid,)); c.commit()
m = [x for x in api.order_parts(oid)["明细"] if x["明细"] == iid][0]
ck("选的料不在这款的可选范围里时核得出来", any("可选范围" in x for x in m["核对"]), f"{m['核对'][:2]}")

# ③ 范围跟身份走:一个和这张单不沾边的顾问看不到
客, 顾 = c.execute("SELECT o.customer_id, o.advisor_no FROM ordr o WHERE o.id=?", (oid,)).fetchone()
旁人 = c.execute("SELECT no FROM staff WHERE no NOT IN (?, COALESCE((SELECT advisor_no FROM customer WHERE id=?),'')) "
                 "AND role='顾问' LIMIT 1", (顾 or "", 客)).fetchone()
if 旁人:
    api.whoami = lambda: {"role": "顾问", "no": 旁人[0], "shop": None}
    e = api.order_parts(oid)
    ck("顾问看不到不归他的单", "error" in e and "范围" in e["error"], f"{e.get('error', '')[:60]}")
else:
    ck("顾问看不到不归他的单", False, "库里找不到一个不沾边的顾问 —— 没验到,不是通过")
api.whoami = lambda: None
ck("没登录看不了", "error" in api.order_parts(oid))

print()
print(f"{G}✅ 分部位选料两个工具全过{D}" if not 坏 else f"{R}❌ 分部位选料 {len(坏)} 条不过:{坏}{D}")
sys.exit(1 if 坏 else 0)
