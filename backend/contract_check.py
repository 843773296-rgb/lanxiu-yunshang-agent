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
    ("让每日平移把条款版本号也当日期挪掉(顾客手里那份印着一个没发布过的版本)",
     "每日平移:正文里的日期跟着挪,条款版本号原样不动"),
    ("让正文里印的版本和 terms_ver 那一列分岔(正文印死一个别的版本号)",
     "顾客看到的版本 = 系统记的版本(正文里印的 == terms_ver 这一列)"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
Y = "\033[33m"        # 库况那一行用它 —— 黄色表示「只报不拦」
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


print("订单确认书 · 库副本上走一遍")
import contract_terms as _K      # 生效日从条款那边现取,不手抄
真库 = W.DB          # 下面那条库况要读它 —— 这一行之后 W.DB 就指向副本了
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

# ── 每日平移:正文里的日期要挪,**条款版本号不许挪** ───────────────────
#
# 2026-10-22 发现的真问题:`order_contract.body` 登记在「文字里也挪」
# (正文里的确认日期必须跟着挪,不挪就和订单的确认日期自相矛盾)——
# 而「**条款版本** 2026-10-10.2」也被当成日期挪了。10-23 库里 56 份正文
# 印的是 `2026-10-18.2`,**这个版本从来没发布过**;而同一行的 `terms_ver` 列
# 登记在「文字里不挪」所以是对的。
# > **查库的人看到的是对的,拿着那份文件的顾客看到的是假的。**
# > 而正文和 terms_ver 不一致这件事,没有任何东西会报出来。
#
# ⚠️ 这条判据**真去挪一遍**(调 `shift_world._挪文字`),不读代码判断 ——
# 「平移不挪版本号」是一句关于行为的话,只有真挪一次才知道。
sys.path.insert(0, os.path.join(ROOT, "tools"))
import shift_world as _SW
挪过 = _SW._挪文字(文["body"], 7)
日期挪了 = 文["body"].count("2026") > 0 and 挪过 != 文["body"]
版本没动 = f"**条款版本** {T.版本}" in 挪过
确认日期还在原地 = f"**确认日期** {文['body'].split('**确认日期** ')[1][:10]}" in 挪过 \
    if "**确认日期** " in 文["body"] else False
# ── 正文里印的版本,必须等于 terms_ver 那一列 ─────────────────────────
#
# ⚠️ **这条比上面那条更根本。** 上面那条验的是「平移这个机制不挪版本号」,
# 而这一条验的是**结果**:同一份确认书上,**顾客看到的版本**(正文里印的)
# 和**系统记的版本**(`terms_ver` 列)必须是同一个。
# 10-22 那次就是这两样分了岔:列是对的 `2026-10-10.2`、正文印着 `2026-10-18.2`,
# 而**没有任何一条检查在看这件事** —— 两边分别看都正常。
# 下一个把它们弄分岔的机制可能不是平移(可能是重渲染、可能是某次迁移),
# 这一条不管机制,只管结果。
#
# ⚠️ **判据自己造那份确认书**(就是上面刚生成的那一份),不看库里碰巧有多少份 ——
# 2026-10-21 CI 连红两次的教训:判据红不红不许取决于环境里有什么数据。
# 库里现存那些对不对,下面另开一行**只打印、不判红**。
那一串 = f"**条款版本** {文['条款版本']}"
ck("顾客看到的版本 = 系统记的版本(正文里印的 == terms_ver 这一列)",
   那一串 in 文["body"] and 文["条款版本"] == T.版本,
   f"terms_ver 这一列={文.get('条款版本')}、代码里={T.版本}、"
   f"正文里找不找得到「{那一串}」={那一串 in 文['body']} —— "
   f"**两边分别看都正常,只有并排放才看得出分岔**")

ck("每日平移:正文里的日期跟着挪,条款版本号原样不动",
   日期挪了 and 版本没动 and not 确认日期还在原地,
   f"挪了={日期挪了} 版本没动={版本没动} 确认日期没挪={确认日期还在原地} —— "
   f"版本号长得像日期(`{T.版本}`),而它后面紧跟着 `.数字`,平移靠这个结构认出它;"
   f"**按列豁免不行** —— 同一列里确认日期必须挪")

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

# 库里**现存**那些一致不一致 —— **只打印,不判红**(上面那条验的是代码,这一行报的是库况)。
# 10-22 的事故就在这个数上:56 份全都不一致,而没有任何东西报出来。
真c = sqlite3.connect(f"file:{真库}?mode=ro", uri=True)
try:
    总, 对上 = 真c.execute(
        "SELECT COUNT(*), SUM(CASE WHEN body LIKE '%条款版本** '||terms_ver||'%' THEN 1 ELSE 0 END)"
        " FROM order_contract").fetchone()
except sqlite3.Error:
    总, 对上 = 0, 0
真c.close()
print(f"  {Y}📖 库况{D} 真库 {总} 份确认书,正文里印的版本和 terms_ver 对得上的 **{对上 or 0}** 份"
      + ("" if (对上 or 0) == 总 else
         f" —— **{总 - (对上 or 0)} 份分岔了**。平移把版本号当日期挪过一次(2026-10-22),"
         f"修法:`python3 tools/backfill_contracts.py --重渲染`(默认只报不写)"))

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
# ── 库况:这个库上还有几张缺确认书 —— **只打印,不判红** ──────────────────
#
# ⚠️ **为什么这一条不判红**,想清楚了再改:
#
# 确认书的规矩是「`confirm_order` 时在同一事务里生成」(业务 2026-10-10),
# 而**代码层面已经守住了** —— 上面那条「确认书写不进去 → 确认下单整个回滚」
# 就是结构保证:走正门确认的单不可能没有确认书。
#
# 真库上「缺几张」量的是**另一件事**:这个库里有多少单是在规矩生效前确认的。
# 而演示世界**每天平移一天**,于是原本 10-09 确认的老单,明天就变成 10-10 之后 ——
# **自动落进「规矩生效后」这个范围,而它被确认的那一刻规矩确实还没生效**。
# 实测:真库(停在 10-15)范围内 56 张、缺 0 张;平移到 10-16 的副本上
# 范围内 63 张、缺 7 张。写死日期做成判据的话,它会一天比一天红,
# 而每天多出来的那几条**没有一条是谁做错了**。
#
# > 一个「正门被绕过了」和一个「平移把老单挪进了这个范围」,
# > **在「缺几张」这个数上长得一模一样** —— 而只有前者该红。
#
# 所以这里只报数。要补就手工跑 `python3 tools/backfill_contracts.py --写`
# (它走 `order_contract.生成()` 那个正门函数,幂等,不碰规矩生效前的单)。
_c真 = sqlite3.connect(f"file:{真库}?mode=ro", uri=True)
_范围 = _c真.execute(
    """SELECT count(*) FROM ordr WHERE kind='定制品订单'
       AND paid_at IS NOT NULL AND paid_at >= ?""", (_K.生效日,)).fetchone()[0]
_缺 = _c真.execute(
    """SELECT count(*) FROM ordr o WHERE o.kind='定制品订单'
       AND o.paid_at IS NOT NULL AND o.paid_at >= ?
       AND NOT EXISTS(SELECT 1 FROM order_contract k WHERE k.order_id=o.id)""",
    (_K.生效日,)).fetchone()[0]
_份 = _c真.execute("SELECT count(*) FROM order_contract").fetchone()[0]
_c真.close()
print(f"  {Y}📖 库况{D} 这个库上 {_份} 份确认书;规矩生效日之后已确认的定制单 {_范围} 张,"
      f"其中缺确认书 {_缺} 张"
      + ("" if not _缺 else
         f" —— **只报不拦**:多半是平移把规矩生效前的老单挪进了这个范围"
         f"(它们确认那天规矩还没生效)。要补跑 `python3 tools/backfill_contracts.py --写`"))

shutil.rmtree(tmp, ignore_errors=True)
print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 订单确认书都对(验了 {n} 条){D}")
