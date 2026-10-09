#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经营报告的保存与确认(save_report / confirm_report / list_reports)—— 在库的**临时副本**上跑,真库一行不碰。

按用户 2026-10-09 定的走一遍:存草稿(每存一版、冻结取数包)→ 再存一版 → 只能确认最新那一版 →
确认后不能再确认 → 再存是新的一版、指回被替代的那一版;再钉几种该拒的:顾问存、别店店长确认 / 看、
空正文、报告期对不上、必选缺了确认。最后验**冻结**:存完往副本里加一张单,存下的数不变、现取的变了。
"""
import json, os, shutil, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]
import api, report_doc, oplog

咬合 = [
    ("确认不看是不是最新那一版", "旧版确认不了(只能确认最新那一版)"),
    ("保存时不冻结取数包(存的是现查的)", "冻结:存完加一张单,存下的下单数不变"),
    ("别店店长也能确认", "别店店长确认不了"),
    ("必选缺了也能确认", "必选指标缺了确认不了"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


print("经营报告保存 / 确认 · 库副本上走一遍")
真库 = api.DB
c0 = sqlite3.connect(真库)
report_doc.建表(c0); c0.commit()
真库前 = c0.execute("SELECT COUNT(*) FROM store_report_doc").fetchone()[0]
c0.close()

tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(真库, db)
api.DB = report_doc.DB = oplog.DB = db
c = sqlite3.connect(db)
店, 别店 = [r[0] for r in c.execute("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 2")]
店长 = dict(no="SM-CHECK", name="店长", role="店长", shop=店)
别店长 = dict(no="SM-OTHER", name="别店店长", role="店长", shop=别店)
顾问 = dict(no="AD-CHECK", name="顾问", role="顾问", shop=店)
正文 = "## 上周经营周报\n下单与营收见取数包。"

with api.as_user(店长):
    r1 = api.save_report(body=正文, kind="周")
    r2 = api.save_report(body=正文 + "(改了一句)", kind="周", report_id=r1.get("报告号"))
    旧 = api.confirm_report(r1.get("报告号"))
    新 = api.confirm_report(r2.get("报告号"))
    再 = api.confirm_report(r2.get("报告号"))
    r3 = api.save_report(body=正文 + "(确认后又改)", kind="周", report_id=r2.get("报告号"))
    空 = api.save_report(body="  ", kind="周")
    错期 = api.save_report(body=正文, kind="月", report_id=r3.get("报告号"))
    单 = api.list_reports(report_id=r2.get("报告号"))
    列 = api.list_reports(kind="周")
ck("存草稿:成功、第 1 版、状态草稿", r1.get("ok") and r1.get("第几版") == 1 and r1.get("状态") == "草稿", str(r1)[:120])
ck("再存同一期:第 2 版(旧版不覆盖)", r2.get("ok") and r2.get("第几版") == 2, str(r2)[:120])
ck("旧版确认不了(只能确认最新那一版)", 旧.get("code") == "NOT_LATEST", str(旧)[:120])
ck("最新版能确认", 新.get("ok") and 新.get("状态") == "已确认", str(新)[:120])
ck("确认过的不能再确认", 再.get("code") == "ALREADY", str(再)[:120])
ck("确认后再存:第 3 版,指回被替代的那一版", r3.get("第几版") == 3 and r3.get("替代") == r2.get("报告号"), str(r3)[:120])
ck("空正文存不了", 空.get("code") == "EMPTY")
ck("接在别的报告期后面存 → 拒", 错期.get("code") == "PERIOD_MISMATCH", str(错期)[:120])
ck("看单份:正文就是存的那一份、状态已确认", 单.get("body") == 正文 + "(改了一句)" and 单.get("status") == "已确认", str(单)[:120])
ck("列表:每一期只列最新那一版、带版本数",
   any(x["id"] == r3.get("报告号") and x["版本数"] == 3 for x in 列.get("报告") or [])
   and not any(x["id"] in (r1.get("报告号"), r2.get("报告号")) for x in 列.get("报告") or []), str(列)[:160])

with api.as_user(顾问):
    ck("顾问存不了", api.save_report(body=正文).get("code") == "NOT_MANAGER")
with api.as_user(别店长):
    ck("别店店长确认不了", api.confirm_report(r3.get("报告号")).get("code") == "NOT_FOUND")
    ck("别店店长看不到", "error" in api.list_reports(report_id=r3.get("报告号"))
       and not any(x["id"] == r3.get("报告号") for x in api.list_reports().get("报告") or []))

# 必选缺了:直接拿一个「能不能确认 = False」的取数包存,再确认
with api.as_user(店长):
    包 = api.store_report(kind="日")
包["能不能确认"], 包["必选缺了的"] = False, ["营收"]
缺 = report_doc.保存(店长, 包, 正文, db=db)
ck("必选指标缺了确认不了", report_doc.确认(店长, 缺.get("报告号"), db=db).get("code") == "MISSING_REQUIRED")

# 冻结:存完往副本里加一张这一期的单 —— 存下的下单数不变,现取的 +1
with api.as_user(店长):
    存下 = api.list_reports(report_id=r3.get("报告号"))["pack"]["期内"]["订单"]["值"]["下单"]
    起 = api.list_reports(report_id=r3.get("报告号"))["period_start"]
    样 = c.execute("SELECT * FROM ordr WHERE shop=? LIMIT 1", (店,)).fetchone()
    cols = [x[1] for x in c.execute("PRAGMA table_info(ordr)")]
    行 = dict(zip(cols, 样)); 行.update(id="FREEZE-CHECK-1", created=起 + " 12:00:00")
    c.execute(f"INSERT INTO ordr({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [行[k] for k in cols]); c.commit()
    现取 = api.store_report(kind="周")["期内"]["订单"]["值"]["下单"]
    再看 = api.list_reports(report_id=r3.get("报告号"))["pack"]["期内"]["订单"]["值"]["下单"]
ck("冻结:存完加一张单,存下的下单数不变", 再看 == 存下 and 现取 == 存下 + 1, f"存下 {存下} / 再看 {再看} / 现取 {现取}")

c.close()
shutil.rmtree(tmp, ignore_errors=True)
c0 = sqlite3.connect(真库)
ck("真库一行没碰", c0.execute("SELECT COUNT(*) FROM store_report_doc").fetchone()[0] == 真库前)
c0.close()

import prompts
for t in ("save_report", "confirm_report", "list_reports"):
    ck(f"{t} 有管它的规矩", any(t in r_.needs for r_ in prompts.ALL_RULES))
ck("两个写工具都登记在 WRITE_TOOLS", {"save_report", "confirm_report"} <= set(api.WRITE_TOOLS))

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 报告保存 / 确认都对(验了 {n} 条){D}")
