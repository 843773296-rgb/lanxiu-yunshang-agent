#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 · 每种都真跑一遍(执行手册 W25,拍板 16:店长以上免审、留记录;2026-11-17)

## 为什么要有这个
2026-10 月那次冒烟揪出两条导出 SQL 按早就不存在的列写的(`advisor` / `obj`),整个导出功能一跑就崩 ——
而 route_check 只静态查「路由在」,**没有任何检查调用过导出**。页面上「导出所选」又是浏览器里拼的,后端只记一笔。
拍板 16 说的三件事(店长以上才能导 / 手机号不出门 / 每次进操作日志)在这之前没有一条被验过。
> 一个「导出功能在」和一个「导出功能一跑就崩」,在路由表上长得一模一样。

## 查什么
· 登记的每一种导出在库副本上真跑一遍:不崩、有表头、至少 1 行(客户 / 订单 / 工单 / 日志 / 预约 / 员工 / 商品这几张表库里总有)
· 任何一种导出的内容里**没有完整手机号**(11 位、1 开头)
· 每跑一种,操作日志多一行 code=EXPORT
· 店长导客户 / 预约,只导得出本店的行
· HTTP 口:顾问 → 403 EXPORT_ROLE 并记一笔拒绝;店长 → 200,拿到的是文件
在库的临时副本上跑,真库不动。
"""
import csv as _csv
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

咬合 = [
    ("导出函数里不再写操作日志", "每导一种,操作日志多一行 EXPORT"),
    ("客户导出把手机尾号那一列换成完整手机号", "内容里没有完整手机号"),   # 判据名是按种类拼的,预期红只写公共那半
    ("GET /api/export/ 入口不再核店长以上", "顾问走 HTTP 导出 → 403 EXPORT_ROLE"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:160]) if extra else ''}")
    if not ok: FAIL.append(name)


def run(T):
    import auth, api, oplog, tasks, server
    for m in (auth, api, oplog, tasks, server): m.DB = T
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row
    kinds = list(server._EXPORT)
    ck("登记的导出至少 7 种(客户 / 订单 / 工单 / 日志 / 预约 / 员工 / 商品)", len(kinds) >= 7, kinds)
    before = c.execute("SELECT COUNT(*) FROM op_log WHERE code='EXPORT'").fetchone()[0]
    手机 = re.compile(r"(?<!\d)1\d{10}(?!\d)")
    for k in kinds:
        text = server.export_csv(k, None, actor="导出检查", 本店=None)
        lines = text.strip().split("\n")
        ck(f"{k} · 真跑不崩、有表头、至少 1 行", len(lines) >= 2 and not text.startswith("错误") and "," in lines[0], lines[0][:80])
        m = 手机.search(text)
        ck(f"{k} · 内容里没有完整手机号", m is None, m.group(0) if m else "")
    after = c.execute("SELECT COUNT(*) FROM op_log WHERE code='EXPORT'").fetchone()[0]
    ck("每导一种,操作日志多一行 EXPORT", after - before == len(kinds), (before, after, len(kinds)))
    店长 = c.execute("SELECT no,name,shop FROM staff WHERE role='店长' AND status='启用' AND shop!='' ORDER BY no LIMIT 1").fetchone()
    顾问 = c.execute("SELECT no FROM staff WHERE role='顾问' AND status='启用' ORDER BY no LIMIT 1").fetchone()
    ck("样本:一位店长、一位顾问", bool(店长 and 顾问))
    if not (店长 and 顾问):
        return
    for k, 列 in (("customers", "门店"), ("appointments", "门店")):
        text = server.export_csv(k, None, actor="导出检查", 本店=店长["shop"])
        rows_ = list(_csv.reader(io.StringIO(text)))
        hdr = rows_[0] if rows_ else []
        i = hdr.index(列) if 列 in hdr else -1
        vals = {r[i] for r in rows_[1:] if len(r) > i} if i >= 0 else set()
        ck(f"{k} · 店长只导得出本店的行", i >= 0 and bool(vals) and vals <= {店长["shop"]}, (len(rows_) - 1, sorted(vals)[:3]))
    from authgate_check import 打GET   # 复用那条检查的假 handler:真走 do_GET
    tok, _ = auth.login(顾问["no"], "lanxiu@2026")
    ck("前提:顾问能用演示口令登录", bool(tok))
    拒前 = c.execute("SELECT COUNT(*) FROM op_log WHERE code='EXPORT_ROLE'").fetchone()[0]
    码, 回 = 打GET("/api/export/customers", cookie=f"lx_token={tok}")
    ck("顾问走 HTTP 导出 → 403 EXPORT_ROLE", 码 == 403 and isinstance(回, dict) and 回.get("code") == "EXPORT_ROLE", (码, str(回)[:80]))
    拒后 = c.execute("SELECT COUNT(*) FROM op_log WHERE code='EXPORT_ROLE'").fetchone()[0]
    ck("被拒也记了一笔", 拒后 == 拒前 + 1, (拒前, 拒后))
    tok2, _ = auth.login(店长["no"], "lanxiu@2026")
    码, 回 = 打GET("/api/export/staff", cookie=f"lx_token={tok2}")
    ck("店长走 HTTP 导员工 → 200,拿到的是文件不是 JSON", 码 == 200 and not isinstance(回, dict), (码, str(回)[:60]))


def main():
    print("导出 · 每种真跑一遍(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="exp-")
    T = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.path.join(HERE, "lanxiu.db"), T)
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 导出 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        return 1
    print(f"\033[32m✅ 导出 {N[0]} 条全过\033[0m —— 每种都真跑、没有完整手机号、每次进操作日志、店长只导本店、顾问 403")
    return 0


if __name__ == "__main__":
    sys.exit(main())
