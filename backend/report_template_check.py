# -*- coding: utf-8 -*-
"""报告模板(复审第 4 节 C,用户 2026-10-23 拍「要,做受控模板」)—— 在库副本上走一遍真写口。

验六件事(卡片 + 主会话派活时点名的):
  ① 清单外的指标名拒存(已登记清单由代码现算,和真取数包对得上)
  ② 锁定必选项(下单数、营收)取消不了、隐藏不了、删不掉
  ③ 只有总部运营能改:顾问 / 店长改不了;没登录 401(HTTP 层,身份只从登录会话来)
  ④ 改完模板,旧报告仍按**保存那一刻冻结的**那一版显示(卡片风险原话)
  ⑤ 「被隐藏」和「取不到」分开标
  ⑥ 模板只管显示:隐藏一项,取数包里的数一个不变

**存报告走正门**(api.save_report → report_doc.保存),打开走 report_doc.取 —— 和报告页、PDF 读的是同一个函数。
用法:python3 backend/report_template_check.py   (不调模型;写的是库副本)
"""
import datetime as _dt, io, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
# ⚠️ 写口模块**先 import 再切库** —— 用副本只改已经加载的模块;之后才 import 的会写真库
import api, report_doc, report_template as RT, server, auth, oplog, ops, worldclock   # noqa: F401
import check_copy
副本 = check_copy.用副本("rpt-tpl-")

G, Rd, D = "\033[32m", "\033[31m", "\033[0m"
坏 = 0

咬合 = [
    ("校验不查已登记清单(随便写个指标名也存得进)", "清单外的指标名:拒存,而且说清能选哪些"),
    ("锁定必选项的检查拿掉(营收能隐藏)", "锁定必选项隐藏不了(营收)"),
    ("改模板不查角色(谁都能改)", "顾问改模板:拒(403)"),
    ("打开报告时按现行模板现算(不读冻结的那一份)", "改完模板,旧报告仍按冻结的第 1 版显示(评价仍隐藏、库存仍显示)"),
    ("被隐藏的也标成取不到(两种状态混成一种)", "日报:隐藏的标「被隐藏」、取不到的标「取不到」,两种分开"),
]


def ck(名, ok, 细=""):
    global 坏
    if not ok: 坏 += 1
    print(f"  {G+'✅'+D if ok else Rd+'❌'+D} {名}{'' if ok else '  —— ' + str(细)[:300]}")


class 假请求:
    def __init__(self, path, body=None, tok=None):
        self.path = path
        self._b = json.dumps(body or {}, ensure_ascii=False).encode()
        self.headers = {"content-length": str(len(self._b)) if body is not None else "0"}
        if tok: self.headers["cookie"] = f"lx_token={tok}"
        self.rfile, self.wfile = io.BytesIO(self._b), io.BytesIO()
    def send_response(self, *a): pass
    def send_header(self, *a): pass
    def end_headers(self): pass
    def log_message(self, *a): pass


def _打(方法, path, body=None, tok=None):
    from urllib.parse import quote
    h = 假请求(quote(path, safe="/?=&"), body, tok); 回 = {}
    def _send(obj, code=200): 回.update(码=code, 体=obj)
    h._send = _send
    getattr(server.H, 方法)(h)
    return 回.get("码"), 回.get("体") or {}


def 存模板(name, payload, why, tok=None):
    return _打("do_POST", "/api/report-template-save", {"name": name, "payload": payload, "why": why}, tok)


def 会话(role, shop=None):
    sql = "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用'" + (" AND shop=?" if shop else "") + " LIMIT 1"
    r = server.rows(sql, *([role, shop] if shop else [role]))
    if not r: return None, None
    tok = f"rpt-tpl-{role}-{shop or ''}"
    with auth._LOCK: auth._SESS[tok] = dict(r[0], at=_dt.datetime.now())
    return tok, dict(r[0])


def 模板(隐藏=(), 期间="周", 门店=("全部",), 改=None):
    """从代码默认那一份出发,按要求隐藏几项 —— 判据造的样本走的也是同一份已登记清单。"""
    p = RT.默认内容()
    p["默认期间"], p["适用门店"] = 期间, list(门店)
    for 节 in p["章节"]:
        for x in 节["指标"]:
            if x["名"] in 隐藏: x["显示"] = False
            if 改 and x["名"] in 改: x.update(改[x["名"]])
    return p


def 态(视, 名):
    for 节 in 视["章节"]:
        for x in 节["指标"]:
            if x["名"] == 名: return x["状态"]
    return None


def main():
    print("\n\033[1m▸ 报告模板 · 在库副本上走真写口、真存报告、真打开\033[0m")
    for m in (RT, report_doc, oplog, api):
        if os.path.realpath(m.DB) != os.path.realpath(副本):
            print(f"  {Rd}❌ {m.__name__}.DB 没切到副本({m.DB})—— 不跑,免得写真库{D}"); return 1
    c = sqlite3.connect(副本)
    RT.确保表(c); c.execute("DELETE FROM report_template_ver"); report_doc.建表(c); c.commit(); c.close()

    tH, 总部 = 会话("总部运营"); tG, _ = 会话("顾问")
    店 = server.rows("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 2")
    if not (tH and tG and len(店) == 2):
        print(f"  {Rd}❌ 库里找不到在职的总部运营 / 顾问 / 两家有单的店 —— 没东西可验{D}"); return 1
    店, 别店 = 店[0]["shop"], 店[1]["shop"]
    tM, _ = 会话("店长", 店)
    店长 = dict(no="SM-RTPL", name="检查店长", role="店长", shop=店)
    别店长 = dict(no="SM-RTPL2", name="检查别店店长", role="店长", shop=别店)

    # ① 已登记清单:代码现算,和真取数包两头对得上
    登 = [x["名"] for x in RT.已登记指标()]
    with api.as_user(店长):
        包 = api.store_report(kind="周")
    包里 = list((包.get("期内") or {})) + list((包.get("存量(截至今天)") or {}))
    print(f"  📖 已登记指标 {len(登)} 项;这一期真取数包里 {len(包里)} 项")
    ck("已登记清单和真取数包对得上(不手抄,两头一样)", len(登) >= 10 and set(登) == set(包里),
       f"清单多 {set(登) - set(包里)} · 包里多 {set(包里) - set(登)}")
    ck("锁定必选 = 取数包的必选指标(下单数、营收)", list(RT.锁定必选()) == 包.get("必选指标") and "营收" in RT.锁定必选(),
       f"{RT.锁定必选()} vs {包.get('必选指标')}")

    # ③ 身份(HTTP 层)
    码, 体 = _打("do_GET", "/api/report-templates")
    ck("没登录看模板:401", 码 == 401, f"{码}")
    码, 体 = 存模板("默认", 模板(), "x")
    ck("没登录改模板:401", 码 == 401, f"{码} {体}")
    码, 体 = 存模板("默认", 模板(隐藏=("评价",)), "顾问想藏评价", tG)
    ck("顾问改模板:拒(403)", 码 == 403 and not 体.get("ok") and "总部运营" in (体.get("reason") or ""), f"{码} {体}")
    if tM:
        码, 体 = 存模板("默认", 模板(隐藏=("评价",)), "店长想藏评价", tM)
        ck("店长改模板:拒(403)", 码 == 403 and not 体.get("ok"), f"{码} {体}")
    码, 体 = 存模板("默认", 模板(隐藏=("评价",)), "  ", tH)
    ck("不写理由:拒", not 体.get("ok") and "理由" in (体.get("reason") or ""), f"{体}")

    # ① 清单外的名字
    坏模板 = 模板(); 坏模板["章节"][0]["指标"].append({"名": "客单价", "显示": True, "必选": False})
    码, 体 = 存模板("默认", 坏模板, "加个客单价", tH)
    ck("清单外的指标名:拒存,而且说清能选哪些",
       码 == 400 and not 体.get("ok") and any("客单价" in e and "不是已登记" in e and "营收" in e for e in 体.get("错") or []),
       f"{码} {体}")

    # ② 锁定必选
    码, 体 = 存模板("默认", 模板(隐藏=("营收",)), "藏营收", tH)
    ck("锁定必选项隐藏不了(营收)", not 体.get("ok") and any("营收" in e and "锁定必选" in e for e in 体.get("错") or []), f"{体}")
    码, 体 = 存模板("默认", 模板(改={"订单": {"必选": False}}), "订单改可选", tH)
    ck("锁定必选项取消不了必选(订单)", not 体.get("ok") and any("订单" in e for e in 体.get("错") or []), f"{体}")
    删 = 模板(); 删["章节"][0]["指标"] = [x for x in 删["章节"][0]["指标"] if x["名"] != "订单"]
    码, 体 = 存模板("默认", 删, "删掉订单", tH)
    ck("锁定必选项删不掉(订单)", not 体.get("ok") and any("订单" in e and "删掉" in e for e in 体.get("错") or []), f"{体}")
    码, 体 = 存模板("默认", 模板(改={"评价": {"必选": True}}), "评价也必选", tH)
    ck("别的项标不了必选(要加先找业务拍板)", not 体.get("ok") and any("评价" in e and "必选" in e for e in 体.get("错") or []), f"{体}")
    码, 体 = 存模板("默认", 模板(期间="季"), "按季", tH)
    ck("默认期间只能是 日 / 周 / 月", not 体.get("ok"), f"{体}")
    ck("被拒的那几次一版都没落", RT.详情("默认")["版本"] == 0)

    # ④ 冻结:v1 隐藏评价 → 存报告 A → v2 改成隐藏库存 → A 照旧、新报告 B 按 v2
    码, v1 = 存模板("默认", 模板(隐藏=("评价",)), "检查:先藏评价", tH)
    ck("总部运营存第 1 版", 码 == 200 and v1.get("ok") and v1.get("版本") == 1, f"{码} {v1}")
    with api.as_user(店长):
        A = api.save_report(body="## 检查周报 A", kind="周")
    码, v2 = 存模板("默认", 模板(隐藏=("库存",)), "检查:改藏库存", tH)
    ck("再存是第 2 版(只增不改)", v2.get("ok") and v2.get("版本") == 2, f"{v2}")
    with api.as_user(店长):
        B = api.save_report(body="## 检查周报 B", kind="周")
        视A = api.list_reports(report_id=A.get("报告号")).get("模板视图") or {}
        视B = api.list_reports(report_id=B.get("报告号")).get("模板视图") or {}
    ck("报告 A 冻的是第 1 版(版本号也写进了报告那一行)",
       视A.get("冻结了模板") and 视A.get("版本") == 1
       and server.rows("SELECT template_ver FROM store_report_doc WHERE id=?", A.get("报告号"))[0]["template_ver"] == v1.get("版本号"),
       f"{视A.get('版本')} {A}")
    ck("改完模板,旧报告仍按冻结的第 1 版显示(评价仍隐藏、库存仍显示)",
       态(视A, "评价") == "被隐藏" and 态(视A, "库存") == "显示", f"评价={态(视A, '评价')} 库存={态(视A, '库存')}")
    ck("新报告按第 2 版(库存隐藏、评价显示)", 视B.get("版本") == 2 and 态(视B, "库存") == "被隐藏" and 态(视B, "评价") == "显示",
       f"{视B.get('版本')} 评价={态(视B, '评价')} 库存={态(视B, '库存')}")
    with sqlite3.connect(副本) as c:
        行 = c.execute("SELECT version, payload FROM report_template_ver WHERE name='默认' ORDER BY version").fetchall()
    ck("版本记录只增不改:第 1 版内容原样留着", len(行) == 2 and
       any(not x.get("显示", True) and x["名"] == "评价" for 节 in json.loads(行[0][1])["章节"] for x in 节["指标"]), f"{行[:1]}")

    # ⑥ 只管显示:隐藏一项,数一个不变
    with api.as_user(店长):
        包2 = api.store_report(kind="周")
    ck("模板只管显示:隐藏库存之后,取数包里的数一个不变",
       包2["存量(截至今天)"]["库存"]["值"] == 包["存量(截至今天)"]["库存"]["值"]
       and {k: v.get("值") for k, v in 包2["期内"].items()} == {k: v.get("值") for k, v in 包["期内"].items()}
       and 包2["报告模板"]["隐藏的"] == ["库存"])

    # ⑤ 被隐藏 vs 取不到:日报不报成交率(值为空 = 取不到),评价按模板藏
    存模板("默认", 模板(隐藏=("评价",)), "检查:日报看两种状态", tH)
    with api.as_user(店长):
        C = api.save_report(body="## 检查日报", kind="日")
        视C = api.list_reports(report_id=C.get("报告号")).get("模板视图") or {}
    ck("日报:隐藏的标「被隐藏」、取不到的标「取不到」,两种分开",
       态(视C, "评价") == "被隐藏" and 态(视C, "成交率") == "取不到" and 态(视C, "订单") == "显示",
       f"评价={态(视C, '评价')} 成交率={态(视C, '成交率')}")

    # ④b 模板上线前存的报告:不拿现行模板去套
    with sqlite3.connect(副本) as c:
        p = json.loads(c.execute("SELECT pack FROM store_report_doc WHERE id=?", (A["报告号"],)).fetchone()[0])
        p.pop("报告模板", None)
        c.execute("UPDATE store_report_doc SET pack=? WHERE id=?", (json.dumps(p, ensure_ascii=False), A["报告号"]))
    with api.as_user(店长):
        视旧 = api.list_reports(report_id=A["报告号"]).get("模板视图") or {}
    ck("没冻结模板的旧报告:明说、全部显示,不拿现行模板(评价隐藏)去套",
       not 视旧.get("冻结了模板") and 态(视旧, "评价") == "显示" and "上线之前" in (视旧.get("说明") or ""), f"{视旧.get('说明')}")

    # 适用门店 + 默认期间
    码, 体 = 存模板("检查专用", 模板(隐藏=("售后",), 期间="月", 门店=(店,)), "检查:这家店看月报、不看售后", tH)
    ck("专用模板认领一家店", 体.get("ok"), f"{体}")
    码, 体 = 存模板("检查专用2", 模板(门店=(店,)), "抢同一家店", tH)
    ck("一家店不能被两个专用模板认领", not 体.get("ok") and any("认领" in e for e in 体.get("错") or []), f"{体}")
    码, 体 = 存模板("检查专用3", 模板(门店=("不存在的店",)), "瞎写店", tH)
    ck("适用门店写错编码:拒", not 体.get("ok"), f"{体}")
    with api.as_user(店长):
        本 = api.store_report()
    with api.as_user(别店长):
        别 = api.store_report()
    ck("不给 kind:按这家店模板的默认期间(月),别家店照默认模板(周)",
       本.get("种类") == "月" and 本["报告模板"]["模板"] == "检查专用" and 别.get("种类") == "周"
       and 别["报告模板"]["模板"] == "默认", f"{本.get('种类')} {本.get('报告模板', {}).get('模板')} / {别.get('种类')}")

    # HTTP 读口(登录后)
    码, 体 = _打("do_GET", "/api/report-templates", tok=tG)
    ck("登录后能看模板列表和已登记指标", 码 == 200 and len(体.get("已登记指标") or []) == len(登)
       and any(t["名称"] == "检查专用" for t in 体.get("模板们") or []), f"{码}")
    码, 体 = _打("do_GET", "/api/report-template/默认", tok=tG)
    ck("登录后能看一个模板的版本记录", 码 == 200 and len(体.get("版本记录") or []) == 3, f"{码} {len(体.get('版本记录') or [])}")

    with auth._LOCK:
        for t in (tH, tG, tM): auth._SESS.pop(t, None)
    print()
    if 坏:
        print(f"{Rd}❌ 报告模板 {坏} 处不符合预期{D}"); return 1
    print(f"{G}✅ 报告模板:清单外拒存、必选取消不了、只有总部运营能改、旧报告按冻结的那一版显示、隐藏和取不到分开{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
