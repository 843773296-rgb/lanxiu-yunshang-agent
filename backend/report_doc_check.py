#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经营报告的保存与确认(save_report / confirm_report / list_reports)—— 在库的**临时副本**上跑,真库一行不碰。

按用户 2026-10-09 定的走一遍:存草稿(每存一版、冻结取数包)→ 再存一版 → 只能确认最新那一版 →
确认后不能再确认 → 再存是新的一版、指回被替代的那一版;再钉几种该拒的:顾问存、别店店长确认 / 看、
空正文、报告期对不上、必选缺了确认。最后验**冻结**:存完往副本里加一张单,存下的数不变、现取的变了。
"""
import json, os, shutil, sqlite3, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]
import api, report_doc, oplog

咬合 = [
    ("确认不看是不是最新那一版", "旧版确认不了(只能确认最新那一版)"),
    ("读报告时不用冻结的取数包,现场重新取数(存了也白存)", "冻结:存完加一张单,存下的下单数不变"),
    ("别店店长也能确认", "别店店长确认不了"),
    ("必选缺了也能确认", "必选指标缺了确认不了"),
    ("报告正文没登记进平移(第二天 05:10 平移会当场停)", "平移:这两列都登记在「文字里也挪」"),
    ("确认后不给链接(用户 10-10:确认后要能直达)", "确认返回带链接,指向这一份"),
    ("对话里的链接不渲染成可点的", "对话页:站内链接渲染成可点的"),
    ("PDF 离线页没把数据塞进去(打出来是空白 / 登录页)", "PDF:离线页真渲染出了这份报告的正文和冻结的数"),
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
# 副本上先清空报告表 —— 真库里会有店长真存过的报告(10-10 第一份 RPT000001 就让「第 1 版」这几条红了):
# 下面「第几版」「替代谁」都按从零存起算,有旧报告时版本号整体往后挪,检查红的不是实现而是起点
report_doc.建表(c); c.execute("DELETE FROM store_report_doc"); c.commit()
店, 别店 = [r[0] for r in c.execute("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 2")]
店长 = dict(no="SM-CHECK", name="店长", role="店长", shop=店)
别店长 = dict(no="SM-OTHER", name="别店店长", role="店长", shop=别店)
顾问 = dict(no="AD-CHECK", name="顾问", role="顾问", shop=店)
# 正文要像真报告一样**写着报告期的日期** —— 否则下面「平移扫得到正文这一列」验不到(10-09 第一版正文没日期,扫不到)
with api.as_user(dict(no="SM-CHECK", name="店长", role="店长", shop=店)):
    _区 = api.store_report(kind="周")["区间"][:23]
正文 = f"## 上周经营周报\n**区间:{_区}**\n下单与营收见取数包。"

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
ck("存草稿返回带链接,指向这一份", r1.get("链接") == f"/report?id={r1.get('报告号')}", str(r1.get("链接")))
ck("确认返回带链接,指向这一份", 新.get("链接") == f"/report?id={r2.get('报告号')}", str(新.get("链接")))
ck("看单份 / 列表也带链接", 单.get("链接") == 新.get("链接") and all(x.get("链接") for x in 列.get("报告") or [])
   and 列.get("全部报告") == "/report")
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

# 每日平移:存进报告以后,body / pack 真的被扫成「混着日期」、而且登记在「文字里也挪」——
# 空表时 shift_world 按值扫一列都扫不到,那条登记只触发 ⚠ 提醒、从没被验过(数据工厂 10-09 提醒):
# 「登记对了但还没数据」和「列名登记错了」在那条 ⚠ 上长得一模一样。这里在有数据的副本上验一次
sys.path.insert(0, os.path.join(ROOT, "tools"))
import shift_world as sw
纯, 混 = sw.扫列(c)
混名 = {x if isinstance(x, str) else ".".join(x[:2]) for x in 混}
纯名 = {x if isinstance(x, str) else ".".join(x[:2]) for x in 纯}
ck("平移:报告正文和取数包被扫成「混着日期」的列", {"store_report_doc.body", "store_report_doc.pack"} <= 混名,
   str(sorted(x for x in 混名 if x.startswith("store_report_doc"))))
ck("平移:这两列都登记在「文字里也挪」", {"store_report_doc.body", "store_report_doc.pack"} <= set(sw.文字里也挪))
ck("平移:报告期两列是整列日期(跟着挪)", {"store_report_doc.period_start", "store_report_doc.period_end"} <= 纯名,
   str(sorted(x for x in 纯名 if x.startswith("store_report_doc"))))

c.close()
shutil.rmtree(tmp, ignore_errors=True)
c0 = sqlite3.connect(真库)
ck("真库一行没碰", c0.execute("SELECT COUNT(*) FROM store_report_doc").fetchone()[0] == 真库前)
c0.close()

# 链接点得开:/report 是站上登记过的页面,页面取数走的后台口子在
import re as _re
_app = open(os.path.join(ROOT, "agentsite", "app.py"), encoding="utf-8").read()
_srv = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
ck("链接指向的页面登记在站上(/report → report.html)", '"/report": "report.html"' in _app
   and os.path.exists(os.path.join(ROOT, "agentsite", "web", "report.html")))
ck("报告页取数的后台口子在(/api/reports、/api/report/)", '"/api/reports"' in _srv and '"/api/report/"' in _srv)
# 对话页把 [打开报告](/report?id=…) 渲染成可点的;外链 / javascript: 不变成链接 —— 拿 node 真跑共用渲染
import subprocess as _sp
_js = open(os.path.join(ROOT, "agentsite", "web", "_md.js"), encoding="utf-8").read() + """
const a = md("[打开报告](/report?id=RPT000001)"), b = md("[x](javascript:alert(1))"), c = md("[x](//evil.example/a)");
console.log(JSON.stringify([a, b, c]));"""
try:
    _o = json.loads(_sp.run(["node", "-e", _js], capture_output=True, text=True, timeout=30).stdout or "null")
except Exception as e:
    _o = None
ck("对话页:站内链接渲染成可点的", bool(_o) and '<a href="/report?id=RPT000001" target="_blank" rel="noopener">打开报告</a>' in _o[0], str(_o)[:160])
ck("对话页:外链和 javascript: 不变成链接", bool(_o) and "<a " not in _o[1] and "<a " not in _o[2], str(_o)[:160])
ck("对话页用的就是这份共用渲染(没有另抄一份)", '<script src="/md.js">' in
   open(os.path.join(ROOT, "agentsite", "web", "station.html"), encoding="utf-8").read()
   and "function md(" not in open(os.path.join(ROOT, "agentsite", "web", "station.html"), encoding="utf-8").read())

# PDF(用户 10-10:chat 里要能直接下 PDF)—— 下载地址 + 离线页 + 真出一份
ck("存 / 确认 / 列表都带下载地址", 新.get("下载") == f"/report.pdf?id={r2.get('报告号')}"
   and r1.get("下载") and all(x.get("下载") for x in 列.get("报告") or []))
sys.path.insert(0, os.path.join(ROOT, "agentsite"))
import report_pdf
_份 = dict(单, body=单["body"] + "\n\n正文里写了 </script> 也不能把页截断")
_页 = report_pdf.离线页(_份)
ck("PDF 离线页:共用渲染内联进去、不靠登录取数", '<script src="/md.js">' not in _页 and "window.__REPORT__" in _页
   and "</script> 也不能" not in _页)
ck("PDF 文件名带项目名、门店、种类、期、版本", report_pdf.文件名(_份).startswith("澜绣云裳-")
   and "周报-" in report_pdf.文件名(_份) and report_pdf.文件名(_份).endswith("第2版.pdf"), report_pdf.文件名(_份))
_浏 = report_pdf.找浏览器()
if not _浏:
    ck("PDF:这台机器有 Chrome", False, "没有 Chrome 就导不了 PDF —— 这条不静默跳过(CI 的 ubuntu 自带 google-chrome)")
else:
    # 真跑一遍页面脚本:无界面 Chrome 把离线页渲染完的 DOM 吐出来,看正文和冻结的数真画上了
    _dom = report_pdf.渲染后的页(_份) or ""
    _下单 = str(_份["pack"]["期内"]["订单"]["值"]["下单"])
    ck("PDF:离线页真渲染出了这份报告的正文和冻结的数",
       "上周经营周报" in _dom and "保存那一刻的数" in _dom and _下单 in _dom and "也不能把页截断" in _dom
       and "已确认" in _dom, _dom[-200:])
    _b, _因 = report_pdf.出PDF(_份)
    ck("PDF:真出了一份 PDF", bool(_b) and _b.startswith(b"%PDF") and len(_b) > 5000, str(_因 or len(_b or b"")))
_app2 = open(os.path.join(ROOT, "agentsite", "app.py"), encoding="utf-8").read()
ck("PDF 下载路由先拿店长自己的 cookie 向后台取(范围规则不另写)",
   'p == "/report.pdf"' in _app2 and '"/api/report/" + quote(rid)' in _app2)

import prompts
for t in ("save_report", "confirm_report", "list_reports"):
    ck(f"{t} 有管它的规矩", any(t in r_.needs for r_ in prompts.ALL_RULES))
ck("两个写工具都登记在 WRITE_TOOLS", {"save_report", "confirm_report"} <= set(api.WRITE_TOOLS))

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 报告保存 / 确认都对(验了 {n} 条){D}")
