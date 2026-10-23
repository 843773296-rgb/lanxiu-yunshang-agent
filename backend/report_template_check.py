# -*- coding: utf-8 -*-
"""报告模板(复审第 4 节 C,用户 2026-10-23 拍「要,做受控模板」)—— 在库副本上走一遍真写口。

验这几件事(卡片 + 主会话派活时点名的):
  ① 清单外的指标名拒存(已登记清单由代码现算,和真取数包对得上)
  ② 锁定必选项(下单数、营收)取消不了、隐藏不了、删不掉
  ③ 只有总部运营能改:顾问 / 店长改不了;没登录 401(HTTP 层,身份只从登录会话来)
  ④ 改完模板,旧报告仍按**保存那一刻冻结的**那一版显示(卡片风险原话)
  ⑤ 「被隐藏」和「取不到」分开标
  ⑥ 模板只管显示:隐藏一项,其余每一个数不变

10-23 用户在五张选型卡上拍的板(这一轮加的):
  ⑦ 指标登记:每个已登记指标都登记了主题 / 重要度;清单外的名字、指不到的关联都报出来
  ⑧ 每节只放一种:一节混放期内和存量拒存;代码默认按「主题 × 段」分节、节内按重要度
  ⑨ 新指标插位:关联 → 同主题同段按重要度 → 另开一节,带「新增未配」标记,默认显示
  ⑩ 必选可加,缺了拦确认:任何指标能标必选,这种报告取不到的不许;确认那一步必选项取不到就拒,
     **值是 0 照样放行**(取不到 = 取数包里没有这一项、或值是 None)—— 两条都真调 确认() 并回读库里那一行
  ⑪ 隐藏项整项从取数包里拿掉(AI 拿不到它的数)
  ⑫ 草稿 → 试运行 → 发布:草稿不生效、不许跳、试点门店要真店、试点用试运行那一版、新发布顶下旧发布、老库加列默认已发布

**存报告走正门**(api.save_report → report_doc.保存),打开走 report_doc.取 —— 和报告页、PDF 读的是同一个函数;
确认走 api.confirm_report → report_doc.确认。
用法:python3 backend/report_template_check.py   (不调模型;写的是库副本)
"""
import copy, datetime as _dt, io, json, os, sqlite3, sys, tempfile

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
    ("指标登记里删掉一项(任务没登记主题 / 重要度)", "每个已登记指标都登记了主题和重要度(登记表和清单一一对应)"),
    ("校验不查一节里混没混放期内和存量", "一节混放期内和存量:拒存,说清哪一节"),
    ("插位不看关联(关联那一步整个跳过)", "新指标紧挨着关联指标插(到店客户数排在成交率后面)"),
    ("校验不查必选项在这种报告里取不取得到", "日报模板里成交率标必选:拒(这一项日报取不到)"),
    ("确认那一步不看模板里的必选项", "必选项缺失 → 确认被拒,库里那一行仍是草稿"),
    ("确认闸用 `not 值` 判取不到(0 也被判成取不到)", "必选项值为 0 → 确认放行,库里那一行写成已确认"),
    ("存一版直接写成已发布(草稿那一步没了)", "存一版 = 草稿,不生效(取数包里还是代码默认)"),
    ("状态机放开草稿 → 已发布(能跳过试运行)", "草稿不能直接发布(不许跳)"),
    ("发布时不把同一模板的旧发布撤下", "新发布的把旧发布的顶成已撤下(同一模板最多一版已发布)"),
    ("store_report 不再拿掉被隐藏的指标", "隐藏库存之后:取数包里整项没有库存,其余每一个数不变"),
    ("包里不列「被隐藏的」(隐藏和这期没数又混成一种)", "隐藏的在包顶层显式列出(和「取不到的」分开),口径版本号已升"),
    ("试点门店不查适用门店(专用模板能拿任何店试)", "专用模板只在它适用的门店里试运行(试点写了不适用的店:拒)"),
    ("满期的试运行照样生效(读路径不看期限)", "试运行满 30 天自动撤下:满期那一刻起就不生效、打开页面落成已撤下(系统署名)、不能再发布"),
    ("复制为新草稿不落库(只回个 ok)", "撤下的另存成新草稿:新版本号、草稿、内容和原来那版一样;顾问复制不了"),
    ("撤下已发布时不把上一版救回来", "已发布能直接撤下,回到被它顶下来的那一版;再撤就回默认(第 1 版是系统撤的,不救回来)"),
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


def 改态(name, 版, 到, why, tok=None, 店们=None):
    return _打("do_POST", "/api/report-template-status",
              {"name": name, "version": 版, "to": 到, "why": why, "shops": list(店们 or [])}, tok)


def 发布(name, payload, why, tok, 试点):
    """存一版(草稿)→ 试运行(试点一家店)→ 已发布。→ (存的那一版的回包, 发布那一步的回包)"""
    码, 体 = 存模板(name, payload, why, tok)
    if not 体.get("ok"):
        return 体, {}
    改态(name, 体["版本"], "试运行", why + "(试运行)", tok, [试点])
    return 体, 改态(name, 体["版本"], "已发布", why + "(发布)", tok)[1]


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


def 行(rid):
    with sqlite3.connect(副本) as c:
        return c.execute("SELECT status, confirmed_by FROM store_report_doc WHERE id=?", (rid,)).fetchone()


def 改包(rid, 改):
    with sqlite3.connect(副本) as c:
        p = json.loads(c.execute("SELECT pack FROM store_report_doc WHERE id=?", (rid,)).fetchone()[0])
        改(p)
        c.execute("UPDATE store_report_doc SET pack=? WHERE id=?", (json.dumps(p, ensure_ascii=False), rid))


def 位置(视, 名):
    for i, 节 in enumerate(视["章节"]):
        for j, x in enumerate(节["指标"]):
            if x["名"] == 名: return i, j, 节["标题"], x
    return None


def 登记与插位():
    """不碰库的几条:指标登记、默认分节、插位(真调 RT.登记问题 / 默认内容 / 视图)。"""
    # ⑦ 登记
    问 = RT.登记问题()
    登 = RT.已登记指标()
    ck("每个已登记指标都登记了主题和重要度(登记表和清单一一对应)",
       not 问 and len(RT.指标登记) == len(登) and all(x["主题"] and x["重要度"] for x in 登), 问)
    原 = list(RT.指标登记)
    try:
        RT.指标登记.append(("客单价", "销售", "核心", ()))
        ck("登记表里有清单外的名字:报出来", any("客单价" in e and "不在已登记指标清单" in e for e in RT.登记问题()), RT.登记问题())
        RT.指标登记[:] = 原 + [("营收2", "销售", "核心", ("不存在的指标",))]
        ck("关联指向不存在的指标:报出来", any("不存在的指标" in e and "不是已登记的指标" in e for e in RT.登记问题()), RT.登记问题())
        RT.指标登记[:] = [x for x in 原 if x[0] != "库存"]
        ck("取数包里有一项没登记(以后 store_report 新加一项不登记):报出来",
           any("库存" in e and "没在指标登记里登记" in e for e in RT.登记问题()), RT.登记问题())
    finally:
        RT.指标登记[:] = 原

    # ⑧ 默认分节
    默 = RT.默认内容()
    段 = {x["名"]: x for x in 登}
    档 = lambda n: RT.重要度们.index(段[n]["重要度"])
    单一 = all(len({段[x["名"]]["段"] for x in 节["指标"]}) == 1 for 节 in 默["章节"])
    按档 = all([档(x["名"]) for x in 节["指标"]] == sorted(档(x["名"]) for x in 节["指标"]) for 节 in 默["章节"])
    标题 = [节["标题"] for 节 in 默["章节"]]
    ck("代码默认按「主题 × 段」分节(销售 · 本期 / 销售 · 截至今天 …),每节只一种段、节内按重要度、空组合不出节",
       单一 and 按档 and 标题[:2] == ["销售 · 本期", "销售 · 截至今天"] and "交付 · 本期" not in 标题
       and sum(len(节["指标"]) for 节 in 默["章节"]) == len(登), 标题)

    # ⑨ 插位:冻结的模板缺了几项(模板存了之后新登记的),看它们落在哪
    包 = {"期内": {x["名"]: {"值": 1} for x in 登 if x["段"] == "期内"},
          RT.存量键: {x["名"]: {"值": 1} for x in 登 if x["段"] == "存量"}}
    t = RT.默认内容()
    去掉 = {"到店客户数", "售后", "任务", "该催工厂", "延期没告诉顾客", "白坯试衣"}
    for 节 in t["章节"]:
        节["指标"] = [x for x in 节["指标"] if x["名"] not in 去掉]
    t["章节"] = [节 for 节 in t["章节"] if 节["指标"]]
    p = dict(包, 报告模板=dict(模板="默认", 版本=9, 版本号=99, 章节=t["章节"], 隐藏的=[]))
    视 = RT.视图(p)
    成 = 位置(视, "成交率"); 到 = 位置(视, "到店客户数")
    ck("新指标紧挨着关联指标插(到店客户数排在成交率后面)",
       到 and 成 and 到[0] == 成[0] and 到[1] == 成[1] + 1, f"成交率={成 and 成[:3]} 到店客户数={到 and 到[:3]}")
    评 = 位置(视, "评价"); 售 = 位置(视, "售后")
    ck("关联指标段不同就不挨着它(售后关联差评待跟是存量)→ 进同主题同段的节、同档排在已有的后面",
       售 and 评 and 售[2] == "售后口碑 · 本期" and 售[1] == 评[1] + 1, f"售后={售 and 售[:3]} 评价={评 and 评[:3]}")
    交 = [x["名"] for 节 in 视["章节"] if 节["标题"] == "交付 · 截至今天" for x in 节["指标"]]
    ck("同主题同段按重要度插:核心排在常看前面,同档排在已有的后面",
       交 == ["该催工厂", "延期没告诉顾客", "库存", "白坯试衣"], 交)
    任 = 位置(视, "任务")
    ck("没有同主题同段的节:另开一节「运营 · 本期」", 任 and 任[2] == "运营 · 本期", 任 and 任[:3])
    新 = [x for 节 in 视["章节"] for x in 节["指标"] if x.get("新增未配")]
    ck("插进去的几项带「新增未配」标记、默认显示;模板里配过的不带",
       sorted(x["名"] for x in 新) == sorted(去掉) and all(x["状态"] == "显示" for x in 新)
       and sorted(视.get("新增未配") or []) == sorted(去掉), [x["名"] for x in 新])


def 迁移():
    """老库(加状态列之前)里的版本:加列时默认「已发布」,生效规则和加列前一样。在一个临时小库上真调 确保表 / 生效。"""
    d = tempfile.mkdtemp(prefix="rpt-tpl-mig-")
    p = os.path.join(d, "lanxiu.db")
    with sqlite3.connect(p) as c:
        c.execute("""CREATE TABLE report_template_ver(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            version INTEGER NOT NULL, payload TEXT NOT NULL, why TEXT NOT NULL, by_no TEXT, by_name TEXT, at TEXT NOT NULL,
            UNIQUE(name, version))""")
        # 旧版本:按当时的规矩存的(两节、混在一起也没人拦)—— 迁移不许动它的内容
        旧 = {"名称": "默认", "适用门店": ["全部"], "默认期间": "月",
              "章节": [{"标题": "全部", "指标": [{"名": "订单", "显示": True, "必选": True}, {"名": "库存", "显示": False}]}]}
        c.execute("INSERT INTO report_template_ver(name,version,payload,why,by_no,by_name,at) VALUES('默认',1,?,'老版本','X','老总部','2026-10-20 10:00:00')",
                  (json.dumps(旧, ensure_ascii=False),))
    未迁 = RT.生效(None, db=p)
    with sqlite3.connect(p) as c:
        RT.确保表(c); c.commit()
        r = c.execute("SELECT status, payload FROM report_template_ver").fetchone()
    已迁 = RT.生效(None, db=p)
    ck("老库加状态列:旧版本迁移成「已发布」、内容一个字不动(混放的旧版也不改),生效照旧",
       r[0] == "已发布" and json.loads(r[1]) == 旧 and 已迁["版本"] == 1 and 已迁["状态"] == "已发布"
       and 未迁["版本"] == 1, f"{r[0]} 迁移前生效={未迁['版本']} 迁移后={已迁['版本']}")


def main():
    print("\n\033[1m▸ 报告模板 · 在库副本上走真写口、真存报告、真打开、真确认\033[0m")
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
    from seed import TODAY
    今 = _dt.date.fromisoformat(TODAY)

    登记与插位()
    迁移()

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
    with api.as_user(店长):
        日包 = api.store_report(kind="日")
    ck("「日报取不到成交率」是同一份:模板读到的 报告期取不到 和真日报取数包一致(成交率值为空)",
       "成交率" in RT.报告期取不到().get("日", ()) and 日包["期内"]["成交率"]["值"] is None
       and 包["期内"]["成交率"]["值"] is not None, f"{RT.报告期取不到()}")

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
    码, 体 = 存模板("默认", 模板(期间="季"), "按季", tH)
    ck("默认期间只能是 日 / 周 / 月", not 体.get("ok"), f"{体}")

    # ⑧ 一节只放一种
    混 = 模板()
    存节 = next(节 for 节 in 混["章节"] if 节["标题"] == "销售 · 截至今天")
    混["章节"][0]["指标"] += 存节["指标"]; 混["章节"].remove(存节)
    码, 体 = 存模板("默认", 混, "待付款并进销售本期", tH)
    ck("一节混放期内和存量:拒存,说清哪一节",
       not 体.get("ok") and any("销售 · 本期" in e and "混放" in e and "待付款" in e for e in 体.get("错") or []), f"{体}")

    # ⑩ 必选可加(这种报告取不到的不许、必选又隐藏的不许)
    码, 体 = 存模板("默认", 模板(期间="日", 改={"成交率": {"必选": True}}), "日报也要成交率", tH)
    ck("日报模板里成交率标必选:拒(这一项日报取不到)",
       not 体.get("ok") and any("成交率" in e and "日报取不到" in e and "每一期都确认不了" in e for e in 体.get("错") or []), f"{体}")
    码, 体 = 存模板("默认", 模板(隐藏=("评价",), 改={"评价": {"必选": True}}), "评价必选又藏", tH)
    ck("必选又隐藏:拒", not 体.get("ok") and any("评价" in e and "必选又隐藏" in e for e in 体.get("错") or []), f"{体}")
    ck("被拒的那几次一版都没落", RT.详情("默认")["版本"] == 0)
    码, 体 = 存模板("检查必选", 模板(门店=(), 改={"评价": {"必选": True}, "成交率": {"必选": True}}), "周报评价和成交率都必选", tH)
    ck("别的项也能标必选(周报的评价、成交率)", 体.get("ok"), f"{体}")

    # ⑫ 草稿 → 试运行 → 发布
    码, v1 = 存模板("默认", 模板(隐藏=("评价",)), "检查:先藏评价", tH)
    ck("总部运营存第 1 版,状态是草稿", 码 == 200 and v1.get("ok") and v1.get("版本") == 1 and v1.get("状态") == "草稿", f"{码} {v1}")
    with api.as_user(店长):
        草 = api.store_report(kind="周")
    ck("存一版 = 草稿,不生效(取数包里还是代码默认)",
       草["报告模板"]["版本"] == 0 and 草["报告模板"]["状态"] == "代码默认" and "评价" in 草["期内"], f"{草['报告模板']}")
    码, 体 = 改态("默认", 1, "已发布", "直接发", tH)
    ck("草稿不能直接发布(不许跳)", not 体.get("ok") and 体.get("code") == "BAD_STEP", f"{码} {体}")
    码, 体 = 改态("默认", 1, "试运行", "顾问想试", tG, [店])
    ck("顾问改状态:拒(403)", 码 == 403 and not 体.get("ok"), f"{码} {体}")
    码, 体 = 改态("默认", 1, "试运行", " ", tH, [店])
    ck("改状态不写理由:拒", not 体.get("ok") and "理由" in (体.get("reason") or ""), f"{体}")
    码, 体 = 改态("默认", 1, "试运行", "没写试点", tH, [])
    ck("试运行不写试点门店:拒", not 体.get("ok") and "试点" in (体.get("reason") or ""), f"{体}")
    码, 体 = 改态("默认", 1, "试运行", "写个假店", tH, ["SH999 不存在的店"])
    ck("试点门店写假店:拒", not 体.get("ok") and "不是门店" in (体.get("reason") or ""), f"{体}")
    码, 体 = 改态("默认", 1, "试运行", "检查:先在一家店试", tH, [店])
    ck("草稿 → 试运行(试点一家真门店)", 体.get("ok"), f"{体}")
    with api.as_user(店长):
        试 = api.store_report(kind="周")
    with api.as_user(别店长):
        别试 = api.store_report(kind="周")
    ck("试点门店用试运行那一版,别的店照旧(还没有已发布 → 代码默认)",
       试["报告模板"]["版本"] == 1 and 试["报告模板"]["状态"] == "试运行" and 别试["报告模板"]["版本"] == 0,
       f"试点={试['报告模板']['版本']}/{试['报告模板']['状态']} 别店={别试['报告模板']['版本']}")
    码, 体 = 改态("默认", 1, "已发布", "检查:试过了,发布", tH)
    ck("试运行 → 已发布", 体.get("ok"), f"{体}")
    with sqlite3.connect(副本) as c:
        留 = c.execute("SELECT status, trial_shops, trial_why, publish_why, publish_by, publish_at FROM report_template_ver "
                      "WHERE name='默认' AND version=1").fetchone()
    ck("状态留痕:试点门店、试运行 / 发布的理由、谁、什么时候都在这一版那一行",
       留[0] == "已发布" and json.loads(留[1]) == [店] and 留[2] and 留[3] == "检查:试过了,发布" and 留[4] and 留[5], f"{留}")

    # ④ 冻结:v1 隐藏评价 → 存报告 A → v2 改成隐藏库存 → A 照旧、新报告 B 按 v2
    with api.as_user(店长):
        A = api.save_report(body="## 检查周报 A", kind="周")
    v2, 发2 = 发布("默认", 模板(隐藏=("库存",)), "检查:改藏库存", tH, 店)
    ck("再存是第 2 版(只增不改)", v2.get("ok") and v2.get("版本") == 2 and 发2.get("ok"), f"{v2} {发2}")
    with sqlite3.connect(副本) as c:
        状 = dict(c.execute("SELECT version, status FROM report_template_ver WHERE name='默认'").fetchall())
    ck("新发布的把旧发布的顶成已撤下(同一模板最多一版已发布)",
       状.get(1) == "已撤下" and 状.get(2) == "已发布" and 发2.get("顶下来的") == [1], f"{状} {发2}")
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
    库B = 位置(视B, "库存")
    ck("新报告按第 2 版(库存隐藏、评价显示;隐藏项的段从登记里补)",
       视B.get("版本") == 2 and 态(视B, "库存") == "被隐藏" and 态(视B, "评价") == "显示" and 库B and 库B[3]["段"] == "存量",
       f"{视B.get('版本')} 评价={态(视B, '评价')} 库存={态(视B, '库存')}")
    with sqlite3.connect(副本) as c:
        行们 = c.execute("SELECT version, payload FROM report_template_ver WHERE name='默认' ORDER BY version").fetchall()
    ck("版本记录只增不改:第 1 版内容原样留着", len(行们) == 2 and
       any(not x.get("显示", True) and x["名"] == "评价" for 节 in json.loads(行们[0][1])["章节"] for x in 节["指标"]), f"{行们[:1]}")

    # ⑫ 同一模板最多一版试运行;撤下的不能再发布
    码, v3 = 存模板("默认", 模板(隐藏=("售后",)), "检查:第 3 版", tH)
    码, 体 = 改态("默认", 3, "试运行", "检查:试第 3 版", tH, [店])
    码, v4 = 存模板("默认", 模板(隐藏=("任务",)), "检查:第 4 版", tH)
    码, 体4 = 改态("默认", 4, "试运行", "检查:同时再试第 4 版", tH, [别店])
    ck("同一模板同一时刻最多一版试运行", 体.get("ok") and not 体4.get("ok") and "最多一版试运行" in (体4.get("reason") or ""), f"{体} {体4}")
    码, 体 = 改态("默认", 3, "已撤下", "检查:试运行不好,撤下", tH)
    码, 体2 = 改态("默认", 3, "已发布", "撤了又想发", tH)
    ck("试运行可以撤下;撤下的不能再发布", 体.get("ok") and not 体2.get("ok") and 体2.get("code") == "BAD_STEP", f"{体} {体2}")

    # ⑪ 隐藏项整项拿掉,其余数一个不变(现在生效的是第 2 版:隐藏库存)
    with api.as_user(店长):
        包2 = api.store_report(kind="周")
    ck("隐藏库存之后:取数包里整项没有库存,其余每一个数不变",
       "库存" not in 包2["存量(截至今天)"] and "库存" not in 包2["期内"]
       and {k: v.get("值") for k, v in 包2["存量(截至今天)"].items()} == {k: v.get("值") for k, v in 包["存量(截至今天)"].items() if k != "库存"}
       and {k: v.get("值") for k, v in 包2["期内"].items()} == {k: v.get("值") for k, v in 包["期内"].items()}
       and 包2["报告模板"]["隐藏的"] == ["库存"], f"存量={list(包2['存量(截至今天)'])} 隐藏的={包2['报告模板']['隐藏的']}")
    ck("隐藏的在包顶层显式列出(和「取不到的」分开),口径版本号已升",
       包2.get("被隐藏的") == ["库存"] and not any(str(x).startswith("库存") for x in 包2.get("取不到的") or [])
       and (包2.get("规则版本") or {}).get("取数口径") == api.报告口径版本 != "2026.10.21.1",
       f"被隐藏的={包2.get('被隐藏的')} 取不到的={包2.get('取不到的')} 版本={(包2.get('规则版本') or {}).get('取数口径')}")

    # ⑤ 被隐藏 vs 取不到:日报不报成交率(值为空 = 取不到),评价按模板藏
    v5, 发5 = 发布("默认", 模板(隐藏=("评价",)), "检查:日报看两种状态", tH, 店)
    with api.as_user(店长):
        C = api.save_report(body="## 检查日报", kind="日")
        视C = api.list_reports(report_id=C.get("报告号")).get("模板视图") or {}
    ck("日报:隐藏的标「被隐藏」、取不到的标「取不到」,两种分开",
       发5.get("ok") and 态(视C, "评价") == "被隐藏" and 态(视C, "成交率") == "取不到" and 态(视C, "订单") == "显示",
       f"评价={态(视C, '评价')} 成交率={态(视C, '成交率')} {发5}")

    # ④b 模板上线前存的报告:不拿现行模板去套
    # 模板上线前存的包:没有「报告模板」,而且什么都没拿掉(A 存时评价被隐藏、整项拿掉了 —— 补回来才像上线前的包)
    改包(A["报告号"], lambda p: (p.pop("报告模板", None), p["期内"].setdefault("评价", 包["期内"]["评价"])))
    with api.as_user(店长):
        视旧 = api.list_reports(report_id=A["报告号"]).get("模板视图") or {}
    ck("没冻结模板的旧报告:明说、全部显示,不拿现行模板(评价隐藏)去套",
       not 视旧.get("冻结了模板") and 态(视旧, "评价") == "显示" and "上线之前" in (视旧.get("说明") or ""), f"{视旧.get('说明')}")

    # ⑩ 确认闸:模板里标了必选的,取不到不许确认;值是 0 照样放行
    v6, 发6 = 发布("默认", 模板(改={"延期没告诉顾客": {"必选": True}, "成交率": {"必选": True}}),
                  "检查:延期没告诉顾客、成交率必选", tH, 店)
    ck("周报模板把延期没告诉顾客、成交率标成必选并发布", v6.get("ok") and 发6.get("ok"), f"{v6} {发6}")
    with api.as_user(店长):
        Dd = api.save_report(body="## 检查日报(成交率必选)", kind="日")
        确D = api.confirm_report(report_id=Dd.get("报告号"))
    ck("必选项值为 None(日报的成交率)→ 确认被拒,库里那一行仍是草稿",
       not 确D.get("ok") and 确D.get("code") == "TEMPLATE_REQUIRED_MISSING" and "成交率" in (确D.get("必选取不到") or [])
       and 行(Dd["报告号"])[0] == "草稿", f"{确D} {行(Dd.get('报告号'))}")
    with api.as_user(店长):
        E = api.save_report(body="## 检查周报 E", kind="周", date=(今 - _dt.timedelta(days=14)).isoformat())
        F = api.save_report(body="## 检查周报 F", kind="周", date=(今 - _dt.timedelta(days=21)).isoformat())
    def _置零(p): p["存量(截至今天)"]["延期没告诉顾客"]["值"] = 0
    def _删掉(p): p["存量(截至今天)"].pop("延期没告诉顾客")
    改包(E["报告号"], _置零); 改包(F["报告号"], _删掉)
    with api.as_user(店长):
        确E = api.confirm_report(report_id=E["报告号"])
        确F = api.confirm_report(report_id=F["报告号"])
    ck("必选项值为 0 → 确认放行,库里那一行写成已确认",
       确E.get("ok") and 行(E["报告号"]) == ("已确认", 店长["no"]), f"{确E} {行(E['报告号'])}")
    ck("必选项缺失 → 确认被拒,库里那一行仍是草稿",
       not 确F.get("ok") and 确F.get("必选取不到") == ["延期没告诉顾客"] and "延期没告诉顾客" in (确F.get("reason") or "")
       and 行(F["报告号"])[0] == "草稿", f"{确F} {行(F['报告号'])}")
    with api.as_user(店长):
        Gm = api.save_report(body="## 检查月报(旧报告)", kind="月")
    改包(Gm["报告号"], lambda p: (p.pop("报告模板", None), p["存量(截至今天)"].pop("延期没告诉顾客", None)))
    with api.as_user(店长):
        确G = api.confirm_report(report_id=Gm["报告号"])
    ck("没冻结模板的旧报告照旧能确认(模板里的必选不追溯)", 确G.get("ok") and 行(Gm["报告号"])[0] == "已确认", f"{确G}")

    # 适用门店 + 默认期间
    专, 发专 = 发布("检查专用", 模板(隐藏=("售后",), 期间="月", 门店=(店,)), "检查:这家店看月报、不看售后", tH, 店)
    ck("专用模板认领一家店(试运行 → 发布)", 专.get("ok") and 发专.get("ok"), f"{专} {发专}")
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
    默行 = next((t for t in 体.get("模板们") or [] if t["名称"] == "默认"), {})
    ck("登录后能看模板列表、已登记指标(带主题 / 重要度)和每个模板的已发布 / 试运行版本",
       码 == 200 and len(体.get("已登记指标") or []) == len(登) and all(x.get("主题") for x in 体.get("已登记指标") or [])
       and any(t["名称"] == "检查专用" for t in 体.get("模板们") or []) and 默行.get("已发布版本") == 6, f"{码} {默行}")
    with sqlite3.connect(副本) as c:
        几版 = c.execute("SELECT COUNT(*) FROM report_template_ver WHERE name='默认'").fetchone()[0]
    码, 体 = _打("do_GET", "/api/report-template/默认", tok=tG)
    ck("登录后能看一个模板的版本记录(带状态)", 码 == 200 and len(体.get("版本记录") or []) == 几版 >= 6
       and {v["状态"] for v in 体["版本记录"]} >= {"已发布", "已撤下", "草稿"}, f"{码} {len(体.get('版本记录') or [])}/{几版}")

    # ⑬ 用户 10-23 晚拍的四条:试点限适用门店、试运行满期自动撤下、撤下的另存新草稿、已发布能撤且回到上一版
    #    用一个只认领「别店」的新模板,不碰上面那些判据的状态
    名 = "检查拍板"
    码, s1 = 存模板(名, 模板(门店=(别店,)), "检查:拍板四条", tH)
    码, 体 = 改态(名, s1.get("版本"), "试运行", "检查:拿别家店试", tH, [店])
    ck("专用模板只在它适用的门店里试运行(试点写了不适用的店:拒)",
       s1.get("ok") and not 体.get("ok") and "不在模板" in (体.get("reason") or ""), f"{s1} {体}")
    码, 体 = 改态(名, s1.get("版本"), "试运行", "检查:在适用的店试", tH, [别店])
    在试 = RT.生效(别店)
    with sqlite3.connect(副本) as c:     # 把试运行开始时间往回拨 试运行天数+1 天 = 满期
        起 = (RT._世界今天() - _dt.timedelta(days=RT.试运行天数 + 1)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE report_template_ver SET trial_at=? WHERE name=? AND version=?", (起, 名, s1.get("版本")))
    满期 = RT.生效(别店)
    码, 详 = _打("do_GET", f"/api/report-template/{名}", tok=tH)
    v1 = next((v for v in 详.get("版本记录") or [] if v["版本"] == s1.get("版本")), {})
    码, 再发 = 改态(名, s1.get("版本"), "已发布", "检查:满期了还想发", tH)
    # 名字写死 30(咬合按字面认);天数一改这条名字就要跟着改 —— 下面断言里用的是 RT.试运行天数
    ck("试运行满 30 天自动撤下:满期那一刻起就不生效、打开页面落成已撤下(系统署名)、不能再发布",
       体.get("ok") and 在试.get("模板") == 名 and 满期.get("模板") != 名 and v1.get("状态") == "已撤下"
       and any(h.get("谁") == "系统" for h in v1.get("留痕") or []) and not 再发.get("ok"),
       f"在试={在试.get('模板')} 满期={满期.get('模板')} 状态={v1.get('状态')} 再发={再发}")
    码, 复 = _打("do_POST", "/api/report-template-copy", {"name": 名, "version": s1.get("版本"), "why": "再试一次"}, tH)
    码, 顾复 = _打("do_POST", "/api/report-template-copy", {"name": 名, "version": s1.get("版本"), "why": "顾问也想复制"}, tG)
    with sqlite3.connect(副本) as c:
        新 = c.execute("SELECT status, payload FROM report_template_ver WHERE name=? AND version=?", (名, 复.get("版本"))).fetchone()
        旧 = c.execute("SELECT payload FROM report_template_ver WHERE name=? AND version=?", (名, s1.get("版本"))).fetchone()
    ck("撤下的另存成新草稿:新版本号、草稿、内容和原来那版一样;顾问复制不了",
       复.get("ok") and 复.get("版本") == s1.get("版本") + 1 and 新 and 新[0] == "草稿"
       and json.loads(新[1])["章节"] == json.loads(旧[0])["章节"] and not 顾复.get("ok"), f"{复} {顾复}")
    v2 = 复.get("版本")
    改态(名, v2, "试运行", "检查:第 2 版试", tH, [别店]); 改态(名, v2, "已发布", "检查:第 2 版发布", tH)
    码, s3 = 存模板(名, 模板(门店=(别店,), 隐藏=("任务",)), "检查:第 3 版", tH)
    改态(名, s3.get("版本"), "试运行", "检查:第 3 版试", tH, [别店]); 改态(名, s3.get("版本"), "已发布", "检查:第 3 版发布", tH)
    码, 撤3 = 改态(名, s3.get("版本"), "已撤下", "检查:第 3 版有问题,直接撤", tH)
    回到 = RT.生效(别店)
    码, 撤2 = 改态(名, v2, "已撤下", "检查:第 2 版也撤", tH)
    再回 = RT.生效(别店)
    ck("已发布能直接撤下,回到被它顶下来的那一版;再撤就回默认(第 1 版是系统撤的,不救回来)",
       撤3.get("ok") and 回到.get("模板") == 名 and 回到.get("版本") == v2 and 回到.get("状态") == "已发布"
       and 撤2.get("ok") and 再回.get("模板") != 名 and "代码默认" in (撤2.get("回到") or ""),
       f"撤3={撤3} 回到={回到.get('模板')}#{回到.get('版本')} 撤2={撤2} 再回={再回.get('模板')}")

    with auth._LOCK:
        for t in (tH, tG, tM): auth._SESS.pop(t, None)
    print()
    if 坏:
        print(f"{Rd}❌ 报告模板 {坏} 处不符合预期{D}"); return 1
    print(f"{G}✅ 报告模板:清单外拒存、必选取消不了、只有总部运营能改、旧报告按冻结的那一版显示、隐藏和取不到分开;"
          f"登记齐、一节一种、新指标按关联 / 重要度插位、必选取不到拦确认(0 放行)、隐藏项不交给 AI、草稿 → 试运行 → 发布{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
