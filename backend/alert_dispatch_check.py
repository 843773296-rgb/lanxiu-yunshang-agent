#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预警 → 任务 · 检查(复审第 4 节 D,用户 2026-10-23 拍)。

验五件事,**全在库副本上真派**,接口回 ok 不算数,回读 schedule / alert_task 那一行才算:
  ① 同一件事上一条没办完不重派(返回明确理由),请求体里塞一个假超期日期也绕不过去
  ② 同一次超期办完了 → 可以再派(用户 10-23 拍);工厂又延期又超期(承诺日变了)→ 也可以再派
  ③ 库存预警:「补货跟进」不挂客户也能派,但只能派给店长 / 总部运营(派给顾问、改派给顾问、
     从通用派单口派、批量派都拒)
  ④ 顾问派不了;别家店的店长派不了本店的单
  ⑤ 派出去的任务记了来源(订单号 + 超期日期 / SKU + 档位);页面每行显示「已跟进:谁 / 哪条」
另打 HTTP 层(假 handler,身份只从 Cookie 换):没登录拒、顾问拒、请求体自报身份不算数。

**夹具自己造**(一张生产中、超期的定制单;一个发不出的 SKU),不靠库里碰巧有该催的单 ——
CI 从零建库,该催清单有几条取决于造数,判据不能跟着它红不红。
"""
import datetime as _dt
import io
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("防重复派不看「还有没办完的」(只看同一个键办完没有)", "同一张单再派一次:上一条没办完 → 拒(ALERT_OPEN)"),
    ("同一档库存办完了也放行(不看键办没办完)", "同一档办完了 → 再派拒(ALERT_DONE)"),
    ("工厂催办办完了仍按键拒(退回 10-23 拍板前)", "同一次超期已经办完 → 可以再派(用户 10-23 拍)"),
    ("补货跟进能派给谁不按类型来(退回只派顾问的那个池子)", "补货跟进派给店长自己 → 派出去了"),
    ("改派不按类型取可派的人(补货跟进能改派给顾问)", "补货跟进改派给顾问 → 拒"),
    ("从预警派单的 HTTP 口不取会话身份(谁都能派)", "HTTP:没登录 → 拒(NO_LOGIN),一行没写"),
    ("key_date 不校验形状(什么都往里写)", "key_date 只收 YYYY-MM-DD 或空"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


print("预警 → 任务 · 没办完不重派 / 延期又超期可再派 / 补货跟进只派店长和总部")
print("=" * 80)
# **先 import 所有会写库的模块,再切库** —— 之后才 import 的写口会写真库
import oplog, tasks as TK, tasktypes as TT, alert_dispatch as AD, factory_inbox as FI, api, server, auth  # noqa: E401
import files  # noqa: F401  —— assign_task 里懒加载,先加载才改得到它的 DB
import check_copy
db = check_copy.用副本("alert-dispatch-")
真 = os.path.realpath(check_copy.真库)
没切 = [m.__name__ for m in (oplog, TK, AD, FI, api) if os.path.realpath(m.DB) == 真]
ck("写口模块都已指向库副本(不写真库)", not 没切, 没切)
if 没切:
    sys.exit(1)

from seed import TODAY
今 = _dt.date.fromisoformat(str(TODAY)[:10])
止 = f"{今 + _dt.timedelta(days=2)} 18:00"


def q(sql, *a):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row
    r = [dict(x) for x in c.execute(sql, a)]
    c.close()
    return r


def x(sql, *a):
    c = sqlite3.connect(db); c.execute(sql, a); c.commit(); c.close()


# ── 夹具 ────────────────────────────────────────────────────────────
店 = q("SELECT shop FROM staff WHERE role='店长' AND status='启用' AND shop IN "
      "(SELECT shop FROM staff WHERE role='顾问' AND status='启用') ORDER BY shop LIMIT 1")
别店 = q("SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用' AND shop<>? LIMIT 1",
        店[0]["shop"] if 店 else "")
if not 店 or not 别店:
    ck("夹具:至少两家店有店长、其中一家有顾问 —— 没有就没验,不算通过", False)
    sys.exit(1)
店 = 店[0]["shop"]
店长 = q("SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用' AND shop=? LIMIT 1", 店)[0]
顾问 = q("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop=? LIMIT 1", 店)[0]
总部 = q("SELECT no,name,role,shop FROM staff WHERE role='总部运营' AND status='启用' ORDER BY no LIMIT 1")[0]
别店 = 别店[0]

单 = q("SELECT id FROM ordr WHERE kind='定制品订单' AND shop=? ORDER BY id LIMIT 1", 店)[0]["id"]
FI.ensure()
x("UPDATE ordr SET status='生产中' WHERE id=?", 单)
x("DELETE FROM factory_msg WHERE order_id=?", 单)
x("DELETE FROM factory_delay WHERE order_id=?", 单)
x("UPDATE schedule SET status='取消' WHERE ref_id=? AND status='有效'", 单)
承诺1 = str(今 - _dt.timedelta(days=6))
x("INSERT INTO factory_msg(msg_id, order_id, event, at, promise_date, factory, result) "
  "VALUES('AD-CHK-1', ?, '接单', ?, ?, '检查工厂', '收下')", 单, f"{今 - _dt.timedelta(days=20)} 10:00", 承诺1)

# SKU2 要**卖过**的(快没了那一档要「卖得动」)—— 从现算的档位里挑「够 / 快没了」的,这两档一定卖过
_c0 = AD._c(); _档 = AD.全部sku档(_c0); _c0.close()
卖过的 = sorted(k for k, v in _档.items() if v in ("够", "快没了"))
SKU = q("SELECT code FROM sku WHERE status='启用' AND code NOT IN (%s) ORDER BY code LIMIT 1"
        % ",".join("?" * len(卖过的[:1])), *卖过的[:1])[0]["code"] if 卖过的 else None
if not 卖过的 or not SKU:
    ck("夹具:库里至少有一个卖过的 SKU —— 没有就验不到「快没了」那一档,不算通过", False)
    sys.exit(1)
SKU2 = 卖过的[0]
x("UPDATE sku SET stock=3, locked=3 WHERE code=?", SKU)        # 在手有货、全被占用 → 发不出
x("UPDATE sku SET stock=0, locked=0 WHERE code=?", SKU2)       # 断货
x("UPDATE schedule SET status='取消' WHERE ref_id IN (?,?) AND status='有效'", SKU, SKU2)


def 任务数(ref):
    return q("SELECT COUNT(*) n FROM schedule WHERE ref_id=?", ref)[0]["n"]


def 完成(sid, who):
    return TK.finish_task(dict(id=sid, summary="检查:已跟进完毕"), who)


# ── ① 工厂催办:派 / 没办完不重派 ────────────────────────────────────
print("\n▸ 工厂催办")
r1 = AD.派(dict(kind="工厂催办", obj=单, assignee_no=顾问["no"], end=止), 店长)
s1 = r1.get("id")
行1 = q("SELECT * FROM schedule WHERE id=?", s1)
源1 = q("SELECT * FROM alert_task WHERE schedule_id=?", s1)
ck("店长从该催的一行派给本店顾问 → 派出去了,类型是订单跟踪、挂这张单",
   r1.get("ok") and 行1 and 行1[0]["type"] == "订单跟踪" and 行1[0]["ref_id"] == 单
   and 行1[0]["assignee_no"] == 顾问["no"], r1)
ck("任务记了来源:订单号 + 超期日期(= 承诺完工日)",
   源1 and 源1[0]["kind"] == "工厂催办" and 源1[0]["obj"] == 单 and 源1[0]["key_date"] == 承诺1
   and 源1[0]["key_tag"] == "超期", 源1)

前 = 任务数(单)
r2 = AD.派(dict(kind="工厂催办", obj=单, assignee_no=顾问["no"], end=止, key_date="2099-01-01"), 店长)
ck("同一张单再派一次:上一条没办完 → 拒(ALERT_OPEN)",
   not r2.get("ok") and r2.get("code") == "ALERT_OPEN" and r2.get("上一条") == s1 and 任务数(单) == 前, r2)
ck("拒绝理由说清是哪一条没办完", s1 in (r2.get("reason") or ""), r2.get("reason"))

页 = server.factory_feed_page({}, 店长)
行 = [y for y in 页["chase"] if y["订单"] == 单]
ck("工厂回传页这一行显示「已跟进:谁 / 哪条任务」",
   行 and (行[0].get("跟进") or {}).get("任务") == s1 and 行[0]["跟进"].get("谁") == 顾问["name"]
   and 行[0]["跟进"].get("状态") == "有效", 行 and 行[0].get("跟进"))
ck("店长看页面:能派、可派的人是本店顾问",
   页["派单"]["能派"] and {p["no"] for p in 页["派单"]["可派"]} ==
   {r["no"] for r in q("SELECT no FROM staff WHERE role='顾问' AND status='启用' AND shop=?", 店)}, 页["派单"])

# ── ② 办完了能再派(用户 10-23 拍);延期后又超期也能再派 ────────────────
f1 = 完成(s1, 顾问)
r3 = AD.派(dict(kind="工厂催办", obj=单, assignee_no=顾问["no"], end=止), 店长)
ck("同一次超期已经办完 → 可以再派(用户 10-23 拍)",
   f1.get("ok") and r3.get("ok") and r3.get("id") and r3.get("id") != s1, (f1, r3))
f3 = 完成(r3.get("id"), 顾问) if r3.get("ok") else {}

承诺2 = str(今 - _dt.timedelta(days=1))
x("INSERT INTO factory_delay(order_id, msg_id, old_promise, new_promise, reason, at) "
  "VALUES(?, 'AD-CHK-2', ?, ?, '检查:工厂延期', ?)", 单, 承诺1, 承诺2, f"{今 - _dt.timedelta(days=4)} 09:00")
r4 = AD.派(dict(kind="工厂催办", obj=单, assignee_no=顾问["no"], end=止), 店长)
源4 = q("SELECT * FROM alert_task WHERE schedule_id=?", r4.get("id") or "")
ck("工厂延期后又超期(承诺日变了)→ 算新的一件,可以再派",
   r4.get("ok") and 源4 and 源4[0]["key_date"] == 承诺2, r4)
页 = server.factory_feed_page({}, 店长)
行 = [y for y in 页["chase"] if y["订单"] == 单]
ck("页面上显示的是最近那一条(新超期日)",
   行 and (行[0].get("跟进") or {}).get("任务") == r4.get("id") and 行[0]["跟进"].get("键") == 承诺2,
   行 and 行[0].get("跟进"))

# ── ④ 谁能派 ───────────────────────────────────────────────────────
print("\n▸ 谁能派")
前 = 任务数(单)
r5 = AD.派(dict(kind="工厂催办", obj=单, assignee_no=顾问["no"], end=止), 顾问)
ck("顾问派不了(WRONG_ROLE),一行没写", not r5.get("ok") and r5.get("code") == "WRONG_ROLE" and 任务数(单) == 前, r5)
r6 = AD.派(dict(kind="工厂催办", obj=单, assignee_no=顾问["no"], end=止), 别店)
ck("别家店的店长派不了这张单(不在他看得到的该催清单里)",
   not r6.get("ok") and r6.get("code") == "NOT_ALERTING" and 任务数(单) == 前, r6)
页顾 = server.factory_feed_page({}, 顾问)
ck("顾问看页面:没有派单按钮(能派=否)", 页顾["派单"]["能派"] is False, 页顾["派单"])

# ── ③ 库存预警:补货跟进 ────────────────────────────────────────────
print("\n▸ 库存预警 · 补货跟进")
ck("补货跟进是运营族、挂 SKU、不手填客户、只派店长和总部",
   TT.family("补货跟进") == "运营" and TT.ref_of("补货跟进") == "sku" and not TT.needs_customer("补货跟进")
   and set(TT.可派角色("补货跟进")) == {"店长", "总部运营"} and TT.属于大类("补货跟进"), TT.info("补货跟进"))
前 = 任务数(SKU)
r7 = AD.派(dict(kind="库存预警", obj=SKU, assignee_no=顾问["no"], end=止), 店长)
ck("补货跟进派给顾问 → 拒(NOT_YOURS),一行没写",
   not r7.get("ok") and r7.get("code") == "NOT_YOURS" and 任务数(SKU) == 前, r7)
r8 = AD.派(dict(kind="库存预警", obj=SKU, assignee_no=店长["no"], end=止), 店长)
s8 = r8.get("id")
行8 = q("SELECT * FROM schedule WHERE id=?", s8 or "")
源8 = q("SELECT * FROM alert_task WHERE schedule_id=?", s8 or "")
ck("补货跟进派给店长自己 → 派出去了", r8.get("ok") and 行8, r8)
ck("不挂客户:任务上客户为空、挂的是 SKU 号、门店是接活的人那家",
   行8 and 行8[0]["customer_id"] is None and 行8[0]["ref_id"] == SKU and 行8[0]["type"] == "补货跟进"
   and 行8[0]["shop"] == 店, 行8)
ck("任务记了来源:SKU + 预警档位(发不出)", 源8 and 源8[0]["obj"] == SKU and 源8[0]["key_tag"] == "发不出"
   and 源8[0]["key_date"] is None, 源8)
r9 = AD.派(dict(kind="库存预警", obj=SKU, assignee_no=店长["no"], end=止), 店长)
ck("同一个 SKU 上一条没办完 → 拒(ALERT_OPEN)", not r9.get("ok") and r9.get("code") == "ALERT_OPEN", r9)
r10 = TK.reassign(dict(id=s8 or "", assignee_no=顾问["no"], reason="检查:试着改派给顾问"), 店长)
ck("补货跟进改派给顾问 → 拒", not r10.get("ok") and r10.get("code") == "NOT_YOURS"
   and q("SELECT assignee_no FROM schedule WHERE id=?", s8 or "")[0]["assignee_no"] == 店长["no"], r10)
r11 = TK.assign_task(dict(type="补货跟进", assignee_no=店长["no"], ref_id=SKU2, note="绕开预警", end=止), 店长)
ck("从通用派单口派补货跟进 → 拒(FROM_ALERT_ONLY)",
   not r11.get("ok") and r11.get("code") == "FROM_ALERT_ONLY" and 任务数(SKU2) == 0, r11)
r12 = TK.assign_batch([dict(type="补货跟进", assignee=店长["no"], ref_id=SKU2, note="批量绕开",
                            start=f"{今} 09:00", end=止)], 店长)
ck("批量派补货跟进 → 整批拒", not r12.get("ok") and 任务数(SKU2) == 0, r12)
f8 = 完成(s8 or "", 店长)
r13 = AD.派(dict(kind="库存预警", obj=SKU, assignee_no=店长["no"], end=止), 店长)
ck("同一档办完了 → 再派拒(ALERT_DONE)", f8.get("ok") and r13.get("code") == "ALERT_DONE", (f8, r13))
x("UPDATE sku SET stock=0, locked=0 WHERE code=?", SKU)
r14 = AD.派(dict(kind="库存预警", obj=SKU, assignee_no=店长["no"], end=止), 店长)
ck("档位变了(发不出 → 断货)算新的一件 → 可以再派", r14.get("ok")
   and q("SELECT key_tag FROM alert_task WHERE schedule_id=?", r14.get("id") or "")[0]["key_tag"] == "断货", r14)
r15 = AD.派(dict(kind="库存预警", obj=SKU2, assignee_no=总部["no"], end=止), 店长)
ck("店长不能往上派给总部运营", not r15.get("ok") and r15.get("code") == "NOT_YOURS", r15)
r16 = AD.派(dict(kind="库存预警", obj=SKU2, assignee_no=总部["no"], end=止), 总部)
ck("总部运营派给总部运营 → 派出去了", r16.get("ok"), r16)
够 = q("SELECT code FROM sku WHERE status='启用' AND code NOT IN (?,?) ORDER BY code LIMIT 1", SKU, SKU2)[0]["code"]
x("UPDATE sku SET stock=100, locked=0 WHERE code=?", 够)   # 可用 100:够 / 卖不动,都不是缺货
r17 = AD.派(dict(kind="库存预警", obj=够, assignee_no=总部["no"], end=止), 总部)
ck("可用充足的 SKU 不在缺货预警里 → 不从这里派", r17.get("code") == "NOT_ALERTING" and 任务数(够) == 0, r17)
库页 = server.stock_list({"q": [SKU]}, 店长)
行 = [y for y in 库页["rows"] if y["code"] == SKU]
ck("库存页这一行显示档位和「已跟进」", 行 and 行[0]["档位"] == "断货" and 行[0]["可派"]
   and (行[0].get("跟进") or {}).get("任务") == r14.get("id"), 行)
ck("库存页:店长可派的人只有店长 / 总部运营里他管得到的",
   库页["派单"]["能派"] and {p["role"] for p in 库页["派单"]["可派"]} == {"店长"}, 库页["派单"])

# ── HTTP 层:身份只从 Cookie 换 ─────────────────────────────────────
print("\n▸ HTTP 层(假 handler 直接调 do_POST / do_GET)")


class 假请求:
    def __init__(self, path, body=None, tok=None):
        self.path = path
        raw = json.dumps(body or {}, ensure_ascii=False).encode()
        self.headers = {"content-length": str(len(raw))}
        if tok:
            self.headers["cookie"] = f"lx_token={tok}"
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.码, self.回 = None, None
    def send_response(self, code, *a): self.码 = code
    def send_header(self, *a): pass
    def end_headers(self): pass
    def log_message(self, *a): pass


def 打(方法, path, body=None, tok=None):
    h = 假请求(path, body, tok)
    def _send(obj, code=200):
        h.码, h.回 = code, obj
    h._send = _send
    getattr(server.H, 方法)(h)
    return h.码, h.回 or {}


def 会话(人):
    tok = f"alert-dispatch-check-{人['no']}"
    with auth._LOCK:
        auth._SESS[tok] = dict(人, at=_dt.datetime.now())
    return tok


t店, t顾 = 会话(店长), 会话(顾问)
try:
    x("UPDATE sku SET stock=2, locked=0 WHERE code=?", SKU2)   # 第三个形状:快没了(另起一件,不和上面混)
    x("UPDATE schedule SET status='完结' WHERE ref_id=? AND status='有效'", SKU2)
    前 = 任务数(SKU2)
    _, 回 = 打("do_POST", "/api/alert-dispatch",
              dict(kind="库存预警", obj=SKU2, assignee_no=店长["no"], end=止, role="店长", actor=店长["name"]))
    ck("HTTP:没登录 → 拒(NO_LOGIN),一行没写(请求体里自报店长不算数)",
       回.get("code") == "NO_LOGIN" and 任务数(SKU2) == 前, 回)
    _, 回 = 打("do_POST", "/api/alert-dispatch",
              dict(kind="库存预警", obj=SKU2, assignee_no=店长["no"], end=止, role="店长"), t顾)
    ck("HTTP:顾问登录(请求体自称店长)→ 拒(WRONG_ROLE)", 回.get("code") == "WRONG_ROLE" and 任务数(SKU2) == 前, 回)
    _, 回 = 打("do_POST", "/api/alert-dispatch",
              dict(kind="库存预警", obj=SKU2, assignee_no=店长["no"], end=止, key_tag="发不出"), t店)
    ck("HTTP:店长登录 → 派出去了,档位按服务端现算(快没了,不是请求体里写的)",
       回.get("ok") and q("SELECT key_tag FROM alert_task WHERE schedule_id=?", 回.get("id") or "")[0]["key_tag"] == "快没了"
       and q("SELECT assigned_by FROM schedule WHERE id=?", 回.get("id") or "")[0]["assigned_by"] == 店长["no"], 回)
    _, 页 = 打("do_GET", "/api/factory-feed", None, t店)
    _, 页顾 = 打("do_GET", "/api/factory-feed", None, t顾)
    ck("HTTP:工厂回传页按会话给「能不能派」(店长能 / 顾问不能)",
       页.get("派单", {}).get("能派") is True and 页顾.get("派单", {}).get("能派") is False,
       (页.get("派单"), 页顾.get("派单")))
finally:
    with auth._LOCK:
        for t in (t店, t顾):
            auth._SESS.pop(t, None)

# ── key_date 只收日期或空(数据工厂 10-23):混进一个 "-" 平移就把这一列判成「混着日期」、凌晨拒跑 ──
import sqlite3 as _sq3
_c = _sq3.connect(":memory:")
_拒 = []
for _坏值 in ("-", "N/A", "2026-Q4", "2026-09-24 完工"):
    try:
        AD.记来源(_c, f"CHK-{_坏值}", dict(kind="工厂催办", obj="CHK", key_date=_坏值, key_tag="超期"), "2026-10-23 10:00")
    except ValueError:
        _拒.append(_坏值)
try:
    AD.记来源(_c, "CHK-OK", dict(kind="工厂催办", obj="CHK", key_date="2026-09-24", key_tag="超期"), "2026-10-23 10:00")
    AD.记来源(_c, "CHK-NULL", dict(kind="补货跟进", obj="CHK", key_date=None, key_tag="断货"), "2026-10-23 10:00")
    _好 = True
except ValueError:
    _好 = False
ck("key_date 只收 YYYY-MM-DD 或空:「-」「N/A」这类拒写,日期和空照收", len(_拒) == 4 and _好, (_拒, _好))

print()
if 坏:
    print(f"{R}❌ {len(坏)}/{n} 条不符合预期{D}:" + ";".join(坏))
    sys.exit(1)
print(f"{G}✅ {n} 条全过(库副本上真派,回读库里那一行){D}")
