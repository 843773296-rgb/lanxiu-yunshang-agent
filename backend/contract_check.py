#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定制订单确认书(业务 2026-10-10:收预付款要有书面约定)—— 库的临时副本上跑,真库一行不碰。

验:确认下单真的生成了确认书、内容对得上这张单(独立 SQL 取商品和金额)· 条款写着业务拍的四条 ·
**确认书写不进去,确认下单整个回滚**(不许出现「已付全款、没有确认书」)· 别店看不到 · 没确认的单 / 上线前确认的单照实说 ·
页面 / PDF / 规矩都接上了。
"""
import os, re, shutil, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]
import order_write as W, order_contract as OC, contract_terms as T, oplog

咬合 = [
    ("确认书写不进去也照样确认下单(付了全款没有书面约定)", "确认书写不进去 → 确认下单整个回滚,订单还是「待确认」"),
    ("确认书的金额不按这张单取", "确认书里的商品和金额和这张单对得上(独立 SQL)"),
    ("别店也能看确认书", "别店店长看不到"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


print("订单确认书 · 库副本上走一遍")
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(W.DB, db)
W.DB = OC.DB = oplog.DB = db
c = sqlite3.connect(db)
待 = [r for r in c.execute("SELECT id, shop FROM ordr WHERE status='待确认' ORDER BY id").fetchall() if W.过闸(r[0])[0]]
ck("有能确认下单的样本(空集合上什么都成立)", len(待) >= 2, f"{len(待)} 张")
(单1, 店1), (单2, 店2) = 待[0], 待[1]
店长 = dict(no="SM-CHECK", name="店长", role="店长", shop=店1)

r = W.confirm_order({"order_id": 单1}, 店长)
ck("顾客没单独勾「不适用七天无理由」→ 不让确认,也不生成确认书",
   r.get("code") == "NO7_ACK" and not c.execute("SELECT 1 FROM order_contract WHERE order_id=?", (单1,)).fetchone()
   and c.execute("SELECT status FROM ordr WHERE id=?", (单1,)).fetchone()[0] == "待确认", str(r)[:120])
r = W.confirm_order({"order_id": 单1, "no7day_ack": True}, 店长)
ck("确认下单成功,返回里带确认书链接和下载", r.get("ok") and r.get("订单确认书") == f"/contract?order={单1}"
   and r.get("确认书下载") == f"/contract.pdf?order={单1}", str(r)[:160])
文 = OC.取(店长, 单1, db=db)
期望 = c.execute("SELECT i.name, COALESCE(i.total, i.price * COALESCE(i.qty,1), 0) FROM ordr_item i WHERE i.order_id=?",
                 (单1,)).fetchall()
合计 = c.execute("SELECT amount FROM ordr WHERE id=?", (单1,)).fetchone()[0]
ck("确认书里的商品和金额和这张单对得上(独立 SQL)",
   bool(期望) and all(名 in 文.get("body", "") and f"{额:,.2f}" in 文["body"] for 名, 额 in 期望)
   and f"合计 {合计:,.2f} 元" in 文["body"], (文.get("body") or str(文))[:200])
ck("条款写着业务 10-10 拍的四条,不出现固定违约比例,记下条款版本",
   all(w in 文["body"] for w in ("随时可以决定不做", "重做", "利息", "不适用七天无理由退货"))
   and not re.search(r"\d+\s*%", 文["body"]) and 文.get("条款版本") == T.版本)
勾 = c.execute("SELECT no7_ack_at, no7_ack_by FROM order_contract WHERE order_id=?", (单1,)).fetchone()
ck("记下顾客勾选的时间和账号,并写进确认书正文",
   勾 and 勾[0] and 勾[1] == 店长["no"] and 勾[0] in 文["body"] and 店长["no"] in 文["body"], 勾)
ck("一张单一份:同一张单不会再生成第二份", c.execute("SELECT COUNT(*) FROM order_contract WHERE order_id=?", (单1,)).fetchone()[0] == 1)

# 确认书写不进去 → 整个回滚
原 = OC.生成
def _坏(*a, **k): raise RuntimeError("确认书写不进去(检查注入)")
OC.生成 = _坏
try:
    r2 = W.confirm_order({"order_id": 单2, "no7day_ack": True}, dict(店长, shop=店2))
    状态 = None
except Exception as e:
    r2 = dict(ok=False, error=str(e))
finally:
    OC.生成 = 原
状态 = c.execute("SELECT status, paid_at FROM ordr WHERE id=?", (单2,)).fetchone()
ck("确认书写不进去 → 确认下单整个回滚,订单还是「待确认」", not r2.get("ok") and 状态[0] == "待确认" and not 状态[1], f"{r2} / {状态}")

别店 = [s for (s,) in c.execute("SELECT DISTINCT shop FROM ordr WHERE shop IS NOT NULL") if s != 店1][0]
ck("别店店长看不到", "error" in OC.取(dict(no="X", name="别店", role="店长", shop=别店), 单1, db=db))
ck("总部看得到", "body" in OC.取(dict(no="HQ", name="总部", role="总部运营", shop=None), 单1, db=db))
旧 = c.execute("SELECT id, shop FROM ordr WHERE paid_at IS NOT NULL AND id NOT IN (SELECT order_id FROM order_contract) LIMIT 1").fetchone()
ck("上线前就确认的单:照实说没有确认书、为什么", "上线" in OC.取(dict(no="HQ", name="总部", role="总部运营"), 旧[0], db=db).get("error", ""))

# 页面 / PDF / 规矩
src = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8").read()
ck("页面和下载都接上了(/contract、/contract.pdf、/api/contract/)",
   '"/contract": "contract.html"' in src("agentsite", "app.py") and 'p == "/contract.pdf"' in src("agentsite", "app.py")
   and 'p.startswith("/api/contract/")' in src("backend", "server.py"))
sys.path.insert(0, os.path.join(ROOT, "agentsite"))
import report_pdf
页 = report_pdf.确认书离线页(dict(文, body=文["body"] + "\n\n</script> 也不能截断"))
ck("PDF 离线页:数据塞进去了、</script> 被转义", "window.__DOC__" in 页 and "</script> 也不能截断" not in 页)
import prompts
ck("确认下单的规矩要求把确认书链接给出来", any("confirm_order" in r_.needs and "订单确认书" in r_.text for r_ in prompts.ALL_RULES))

c.close()
shutil.rmtree(tmp, ignore_errors=True)
print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 订单确认书都对(验了 {n} 条){D}")
