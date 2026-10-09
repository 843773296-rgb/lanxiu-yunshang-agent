#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""factory_chase「要人看的回传·条数」是总数,不是 LIMIT(2026-10-09)。

原来是 len(明细),明细 LIMIT 50 —— 超过 50 条就报 50。现在库里只有个位数,洞看不见;
同一个洞 10-08 在 get_member 上真撞过(「休眠 40 个」实际 1395)。
所以这里**在副本上造到 60 条以上**,让截断真的发生,再拿独立 SQL 对总数。
不碰真库。
"""
import os, shutil, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
import api, factory_inbox

咬合 = [
    ("factory_chase 的回传条数退回 len(明细)(被 LIMIT 50 截住)", "条数 = 独立 SQL 数出来的总数"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


print("工厂回传 · 条数不被 LIMIT 截住(副本上造 60+ 条)")
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(api.DB, db)
api.DB = factory_inbox.DB = db
c = sqlite3.connect(db)
单 = [r[0] for r in c.execute("SELECT id FROM ordr ORDER BY id LIMIT 60")]
c.executemany("INSERT INTO factory_msg(msg_id,order_id,event,at,factory,result,reason) VALUES(?,?,?,?,?,?,?)",
              [(f"BITECNT{i:03d}", o, "完工", "2026-01-01 10:00", "测试工厂", "挂异常", "咬合造的")
               for i, o in enumerate(单)])
c.commit()
期望 = c.execute("SELECT COUNT(*) FROM factory_msg WHERE result IN ('挂异常','拒收','暂存')").fetchone()[0]
c.close()

with api.as_user(dict(no="HQ0001", name="总部", role="总部运营", shop=None)):
    r = api.factory_chase()["要人看的回传"]
ck("造出来的样本确实超过 50(否则验不到截断)", 期望 > 50, f"只有 {期望}")
ck("条数 = 独立 SQL 数出来的总数", r.get("条数") == 期望, f"工具 {r.get('条数')} / SQL {期望}")
ck("明细最多列 50 条", len(r.get("明细") or []) <= 50, str(len(r.get("明细") or [])))
ck("截了就明说", 期望 <= 50 or "截断" in r, str(list(r)))
shutil.rmtree(tmp, ignore_errors=True)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 回传条数是总数(验了 {n} 条){D}")
