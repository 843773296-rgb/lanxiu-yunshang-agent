#!/usr/bin/env python3
"""标品交付告知 · 起草只印对得上的、记已告知不是签收、同一单只记一次、范围跟身份走(用户 2026-11-15 拍三条)。

库副本上先补齐迁移(第 2 条给 delivery_notice 加「已告知」四列),再真调 api.draft_delivery_notice / record_delivery_notice。

    python3 backend/delivery_notice_check.py
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
import api  # noqa: E402
import delivery_notice_write  # noqa: E402,F401  —— 先 import 写口,再切副本(写口的 DB 才会被改到)
import check_copy  # noqa: E402
import delivery_notice as D  # noqa: E402
import migrate  # noqa: E402

db = check_copy.用副本("dnotice-")
G, R, Dd = "\033[32m", "\033[31m", "\033[0m"
坏 = []

咬合 = [
    ("把第 3 条(纱罗)的排除词去掉", "香云纱不算纱罗、麻纱和真丝袜不误认"),
    ("去掉「同一单记过就不覆盖」", "同一单只记一次,第二次不覆盖"),
    ("记已告知时不再按身份限范围", "顾问记不了不归他的单"),
    ("记已告知时顺手把签收时间也写上", "记已告知不动签收"),
]


def ck(名, ok, 话=""):
    print(f"  {G + '✅' if ok else R + '❌'}{Dd} {名}" + (f"  {话}" if 话 else ""))
    if not ok:
        坏.append(名)


print("标品交付告知")
# ① 认词:只印对得上的
认 = {n: [h[0] for h in D.对上(n)] for n in ("香云纱 立领长衫", "「澄江」麻纱唐制圆领襕袍", "真丝袜 两双装",
                                              "「杭罗清透」宋制对襟短衫", "「霜序」织金缎明制立领长衫", "手工盘金 云肩绣片")}
ck("香云纱不算纱罗、麻纱和真丝袜不误认", 认["香云纱 立领长衫"] == [2] and 认["「澄江」麻纱唐制圆领襕袍"] == []
   and 认["真丝袜 两双装"] == [], f"{认}")
ck("杭罗→第 3 条、织金→第 4 条、手工盘金→第 4 + 6 条", 认["「杭罗清透」宋制对襟短衫"] == [3]
   and 认["「霜序」织金缎明制立领长衫"] == [4] and 认["手工盘金 云肩绣片"] == [4, 6], f"{认}")
稿 = D.起草([{"名": "「竹节棉」童款交领襦裙"}])
ck("一条都对不上就不出文字,不硬凑", 稿["适用"] == [] and 稿["文字"] is None and 稿["没对上的商品"])

# ② 副本补齐迁移,第 2 条加的列在
c = sqlite3.connect(db)
migrate.补齐(c, 说=lambda *_: None)
列 = {r[1] for r in c.execute("PRAGMA table_info(delivery_notice)")}
ck("副本补齐迁移后 delivery_notice 有「已告知」四列", {"notified_at", "notified_by", "notified_channel", "notified_items"} <= 列)

# 挑一张已交付、商品对得上告知项、还没记过的标品单
名单 = c.execute("SELECT o.id, o.shop, o.advisor_no, o.customer_id FROM ordr o WHERE o.kind='标品订单' AND o.status IN ('完成','已发货','待完成') "
               "AND o.id NOT IN (SELECT order_id FROM delivery_notice) ORDER BY o.id").fetchall()
目标 = next((r for r in 名单 if any(D.对上(n[0]) for n in c.execute("SELECT name FROM ordr_item WHERE order_id=?", (r[0],)))), None)
api.whoami = lambda: {"role": "总部运营", "no": "U001", "name": "检查", "shop": None}
api._need_me = api.whoami
oid = 目标[0]
草 = api.draft_delivery_notice(oid)
ck("起草:列出对得上的条目、每条有依据、给出文字", 草.get("适用") and all(x["依据"] for x in 草["适用"]) and 草.get("文字"),
   f"{[x['编号'] for x in 草.get('适用', [])]}")
ck("起草不写库", c.execute("SELECT COUNT(*) FROM delivery_notice WHERE order_id=?", (oid,)).fetchone()[0] == 0)
ck("渠道不在名单里被拒", api.record_delivery_notice(oid, "飞鸽").get("code") == "BAD_CHANNEL")
r = api.record_delivery_notice(oid, "微信")
行 = c.execute("SELECT notified_at, notified_by, notified_channel, notified_items, signed_at FROM delivery_notice WHERE order_id=?", (oid,)).fetchone()
ck("记已告知写进去了(时间 / 人 / 渠道 / 条目)", r.get("ok") and 行 and 行[0] and 行[1] == "U001" and 行[2] == "微信" and 行[3], f"{r.get('code')} {行}")
ck("记已告知不动签收", 行 is not None and 行[4] is None, f"signed_at={行[4] if 行 else '—'}")
r2 = api.record_delivery_notice(oid, "电话")
行2 = c.execute("SELECT notified_channel FROM delivery_notice WHERE order_id=?", (oid,)).fetchone()
ck("同一单只记一次,第二次不覆盖", r2.get("code") == "DONE" and 行2[0] == "微信", f"{r2.get('code')} {行2}")
ck("操作台账记了一笔", c.execute("SELECT COUNT(*) FROM op_log WHERE target=? AND code='DELIVERY_NOTIFIED'", (oid,)).fetchone()[0] == 1)

# ③ 拒绝:没交付 / 定制单 / 不归他的单
未交 = c.execute("SELECT id FROM ordr WHERE kind='标品订单' AND status NOT IN ('完成','已发货','待完成','取消') LIMIT 1").fetchone()
if 未交:
    ck("还没交付的单记不了", api.record_delivery_notice(未交[0], "微信").get("code") == "NOT_DELIVERED")
定 = c.execute("SELECT id FROM ordr WHERE kind='定制品订单' AND status='完成' LIMIT 1").fetchone()
ck("定制单不走这个口", api.record_delivery_notice(定[0], "微信").get("code") == "NOT_STANDARD")
别 = next(r for r in 名单[1:] if r[0] != oid)
旁 = c.execute("SELECT no FROM staff WHERE role='顾问' AND no NOT IN (?, COALESCE((SELECT advisor_no FROM customer WHERE id=?),'')) LIMIT 1",
              (别[2] or "", 别[3])).fetchone()
api.whoami = lambda: {"role": "顾问", "no": 旁[0], "name": "旁人", "shop": None}
api._need_me = api.whoami
e = api.record_delivery_notice(别[0], "微信")
ck("顾问记不了不归他的单", e.get("code") == "OUT_OF_SCOPE", f"{e.get('code')}")

print()
print(f"{G}✅ 标品交付告知全过{Dd}" if not 坏 else f"{R}❌ 标品交付告知 {len(坏)} 条不过:{坏}{Dd}")
sys.exit(1 if 坏 else 0)
