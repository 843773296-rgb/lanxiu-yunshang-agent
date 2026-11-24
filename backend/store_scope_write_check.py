#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写口按门店划范围 · 检查(在库的**临时副本**上跑,真库一行都不碰,同 content_write_check)。

11-24 全项目体检高危第 2 条:读口 11-11 全按门店划完了,**写口没跟上** —— 通用改状态 `server.transit`、
人工调生命周期 `adjust_lifecycle` 原来谁登录都能改任何一家店的记录(页面看不到别店数据,接口却不拦)。
钉的几件事:
    别店   店长改别店的预约 / 客户生命周期 → NOT_YOUR_SHOP,被拒也进 op_log,表一行没动
    本店   同一个店长改本店的 → **不是** NOT_YOUR_SHOP(状态机还可能因别的原因拒,那是它的事)
    跨店   总部运营改任何店的 → 不是 NOT_YOUR_SHOP;财务只放宽了读,写预约照旧被拦
    押金   **故意不按店划**(两位店长复核的另一位必然来自别店;refund_write 自己管身份)→ 店长改别店押金不是 NOT_YOUR_SHOP
    角色   版师调生命周期 → WRONG_ROLE
    内部   没有 me(内部调用)不在这里拦 —— 身份闸在调用点
"""
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("把 _写口本店 改成永远回 None(谁都算跨店)", "① 店长改别店预约 → NOT_YOUR_SHOP,被拒留痕,预约表没动"),
    ("把 adjust_lifecycle 里的角色闸删掉(谁都能调)", "④ 版师调生命周期 → WRONG_ROLE"),
]
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + str(msg)[:160] if msg and not ok else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    print("写口按门店划范围 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="storew-")
    副本 = os.path.join(tmp, "lanxiu.db")
    import dbpath
    with closing(sqlite3.connect(dbpath.真库())) as 真, closing(sqlite3.connect(副本)) as 副:
        真.backup(副)
    import server, oplog
    server.DB = oplog.DB = 副本
    assert server.DB == 副本 and oplog.DB == 副本, "库没切到副本"

    def q(sql, *a):
        with closing(sqlite3.connect(副本)) as _c:
            _c.row_factory = sqlite3.Row
            return [dict(r) for r in _c.execute(sql, a).fetchall()]

    def 人(role, 店=None, 不是店=None):
        sql = "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用'"
        a = [role]
        if 店:
            sql += " AND shop=?"; a.append(店)
        if 不是店:
            sql += " AND shop<>?"; a.append(不是店)
        r = q(sql + " ORDER BY no LIMIT 1", *a)
        return r[0] if r else None

    拒数 = lambda: q("SELECT COUNT(*) n FROM op_log WHERE allowed=0")[0]["n"]
    店长 = 人("店长")
    ck("身份找得到(一位挂了门店的店长)", bool(店长 and 店长["shop"]), 1, 店长)
    if not (店长 and 店长["shop"]):
        return
    本店 = 店长["shop"]
    别店预约 = q("SELECT id, status, shop FROM appointment WHERE shop IS NOT NULL AND shop<>? ORDER BY id LIMIT 1", 本店)
    本店预约 = q("SELECT id, status, shop FROM appointment WHERE shop=? ORDER BY id LIMIT 1", 本店)
    别店客户 = q("SELECT id, lifecycle, shop FROM customer WHERE shop IS NOT NULL AND shop<>? ORDER BY id LIMIT 1", 本店)
    ck("样本找得到(别店预约 / 本店预约 / 别店客户)", all((别店预约, 本店预约, 别店客户)),
       sum(bool(x) for x in (别店预约, 本店预约, 别店客户)), (本店, bool(别店预约), bool(本店预约), bool(别店客户)))
    if not all((别店预约, 本店预约, 别店客户)):
        return

    print("\n① 店长改别店的")
    前 = q("SELECT id, status FROM appointment WHERE id=?", 别店预约[0]["id"])
    拒前 = 拒数()
    t = server.transit("bk-appt", 别店预约[0]["id"], "取消", {}, 店长["name"], me=店长)
    后 = q("SELECT id, status FROM appointment WHERE id=?", 别店预约[0]["id"])
    ck("① 店长改别店预约 → NOT_YOUR_SHOP,被拒留痕,预约表没动",
       t.get("code") == "NOT_YOUR_SHOP" and 拒数() - 拒前 == 1 and 前 == 后, 1, json.dumps(t, ensure_ascii=False))
    前lc =q("SELECT lifecycle FROM customer WHERE id=?", 别店客户[0]["id"])
    拒前 = 拒数()
    t = server.adjust_lifecycle(别店客户[0]["id"], "流失", "检查", 店长["name"], me=店长)
    ck("① 店长把别店客户手工改生命周期 → NOT_YOUR_SHOP,留痕,客户表没动",
       t.get("code") == "NOT_YOUR_SHOP" and 拒数() - 拒前 == 1 and q("SELECT lifecycle FROM customer WHERE id=?", 别店客户[0]["id"]) == 前lc,
       1, json.dumps(t, ensure_ascii=False))

    print("\n② 店长改本店的 —— 不被门店闸拦(状态机因别的原因拒是它的事)")
    t = server.transit("bk-appt", 本店预约[0]["id"], "取消", {"reason": "检查"}, 店长["name"], me=店长)
    ck("② 店长改本店预约 → 不是 NOT_YOUR_SHOP", t.get("code") != "NOT_YOUR_SHOP", 1, json.dumps(t, ensure_ascii=False))

    print("\n③ 跨店角色 —— 总部运营改任何店的都不被门店闸拦")
    总部 = 人("总部运营")
    ck("身份找得到(总部运营)", bool(总部), 1, 总部)
    if 总部:
        t = server.transit("bk-appt", 别店预约[0]["id"], "取消", {"reason": "检查"}, 总部["name"], me=总部)
        ck("③ 总部运营改别店预约 → 不是 NOT_YOUR_SHOP", t.get("code") != "NOT_YOUR_SHOP", 1, json.dumps(t, ensure_ascii=False))

    财务 = 人("财务")
    ck("身份找得到(财务)", bool(财务), 1, 财务)
    if 财务:
        t = server.transit("bk-appt", 别店预约[0]["id"], "取消", {"reason": "检查"}, 财务["name"], me=财务)
        ck("③ 财务改别店预约 → NOT_YOUR_SHOP(财务只放宽了读,写照旧只本店)", t.get("code") == "NOT_YOUR_SHOP", 1, json.dumps(t, ensure_ascii=False))
    别店押金 = q("""SELECT d.id FROM deposit d JOIN customer c ON c.id=d.customer_id WHERE c.shop IS NOT NULL AND c.shop<>? ORDER BY d.id LIMIT 1""", 本店)
    if 别店押金:
        t = server.transit("bk-deposit", 别店押金[0]["id"], "退款审批中", {}, 店长["name"], me=店长)
        ck("③ 押金故意不按店划:店长改别店客户的押金 → 不是 NOT_YOUR_SHOP(两位店长复核的另一位必然来自别店;身份规则在 refund_write)",
           t.get("code") != "NOT_YOUR_SHOP", 1, json.dumps(t, ensure_ascii=False))

    print("\n④ 角色闸")
    版师 = 人("版师")
    ck("身份找得到(版师)", bool(版师), 1, 版师)
    if 版师:
        拒前 = 拒数()
        t = server.adjust_lifecycle(别店客户[0]["id"], "流失", "检查", 版师["name"], me=版师)
        ck("④ 版师调生命周期 → WRONG_ROLE", t.get("code") == "WRONG_ROLE" and 拒数() - 拒前 == 1, 1, json.dumps(t, ensure_ascii=False))

    print("\n⑤ 内部调用(没有 me)不在这里拦")
    t = server.transit("bk-appt", 别店预约[0]["id"], "取消", {"reason": "检查"}, "内部")
    ck("⑤ 没有会话的内部调用 → 不是 NOT_YOUR_SHOP(身份闸在调用点)", t.get("code") != "NOT_YOUR_SHOP", 1, json.dumps(t, ensure_ascii=False))

    print()
    if FAIL:
        print(f"\033[31m❌ 写口按门店划范围 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL:
            print(f"   · {f}")
        sys.exit(1)
    print("\033[32m✅ 写口按门店划范围 全过\033[0m")


if __name__ == "__main__":
    main()
