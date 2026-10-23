# -*- coding: utf-8 -*-
"""经营报告的受控模板(复审第 4 节 C · 用户 2026-10-23 拍「要,做受控模板」)。

## 要解决的事

总部想让周报多看一项、少看一项,或者某几家店的章节不一样 —— 原来章节和指标全写死在代码和提示词里,
没有「已登记指标」清单、没有模板版本,「哪份报告用的哪一版」说不清。

## 管什么、不管什么

  · 管**显示**:章节、每项显示 / 隐藏、必选、默认期间(日 / 周 / 月)、适用门店。
  · **统计公式一行不动** —— 取数包(api.store_report)照旧全取;模板只决定报告里露哪几项、按什么章节排。
  · 指标只能从**已登记指标**里选。清单**由代码现算**(读 api.store_report 的源码,收「期内[...]」「存[...]」
    两种赋值的名字),不手抄 —— 取数包加一项,清单自动多一项;模板写了清单外的名字 → 拒存。
  · 必选:沿用 store_report 里的 `必选 = (...)`(用户 10-09 定:下单数和营收),同样从源码现读。
    这两项在模板里**锁定必选、必须显示**,取消不了。其余项暂不许标必选(要加先找业务拍板,见交接里的选型卡)。

## 三条硬规矩(写口里拦,页面不另判)

  · **只有总部运营能改**,身份从登录会话来;每次保存要写理由
  · **只增不改**:每存一次是新的一版(report_template_ver 一行),旧版留着 —— 报告里冻的是版本行号
  · 一家店最多被一个专用模板认领;「默认」模板永远适用全部门店,改不了适用范围

## 冻结(卡片风险原话:显示 / 隐藏必须在保存那一刻冻结,不能打开时按现行模板现算)

store_report 把**当时生效的那一版**整份放进取数包的「报告模板」;save_report 冻结取数包时它一起冻住。
打开旧报告时 `视图(pack)` 只读包里冻的那一份 —— **不读这张表**。模板上线之前存的报告包里没有它,
就明说「没冻结模板、按原样全部显示」,也不拿现行模板去套。
> 一份「按当时模板显示」的旧报告和一份「按现行模板现算」的,在页面上长得一模一样 ——
> 而后者改一次模板,所有旧报告看到的指标都变了。

「被隐藏」和「取不到」分开标:隐藏 = 模板说不显示(数据有);取不到 = 要显示、但取数包里没有这一项或值为空。
"""
import ast
import json
import os
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
DB = os.path.join(HERE, "lanxiu.db")
_API = os.path.join(HERE, "api.py")

可编辑角色 = ("总部运营",)
期间们 = ("日", "周", "月")
默认模板名 = "默认"
全部门店 = "全部"
_段名 = {"期内": "期内", "存": "存量"}
存量键 = "存量(截至今天)"


# ── 已登记指标:读 api.store_report 的源码现算 ─────────────────────────────
_缓存 = {}


def _解析():
    """→ (指标们 [(名, 段)], 必选 (名…))。按 api.py 的修改时间缓存;解析不出来就抛 —— 清单空了不许当成「没有限制」。"""
    st = os.stat(_API)
    键 = (st.st_mtime_ns, st.st_size)
    if _缓存.get("键") == 键:
        return _缓存["值"]
    树 = ast.parse(open(_API, encoding="utf-8").read())
    fn = next((n for n in 树.body if isinstance(n, ast.FunctionDef) and n.name == "store_report"), None)
    if fn is None:
        raise RuntimeError("api.py 里找不到 store_report —— 已登记指标算不出来")
    指标, 见 = [], set()
    必选 = None
    # ast.walk 是按层走的(嵌在 if 里的赋值排在后面)—— 按源码行号排,清单顺序才和取数包一致
    for n in sorted((x for x in ast.walk(fn) if isinstance(x, ast.Assign)), key=lambda x: x.lineno):
        for t in n.targets:
            if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id in _段名
                    and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str)):
                if t.slice.value not in 见:
                    见.add(t.slice.value)
                    指标.append((t.slice.value, _段名[t.value.id]))
            if (isinstance(t, ast.Name) and t.id == "必选" and isinstance(n.value, ast.Tuple)
                    and all(isinstance(e, ast.Constant) for e in n.value.elts)):
                必选 = tuple(e.value for e in n.value.elts)
    if not 指标:
        raise RuntimeError("store_report 里一项指标都没认出来 —— 清单空了不许当成「随便写」")
    if not 必选:
        raise RuntimeError("store_report 里找不到 `必选 = (...)` —— 锁定必选项算不出来")
    值 = (指标, 必选)
    _缓存.update(键=键, 值=值)
    return 值


def 已登记指标():
    """→ [{名, 段, 必选}]。段 = 期内 / 存量。"""
    指标, 必选 = _解析()
    return [dict(名=n, 段=s, 必选=n in 必选) for n, s in 指标]


def 锁定必选():
    return _解析()[1]


def 默认内容():
    """没存过任何一版时的模板:两节(期内 / 存量),全部显示,必选按 store_report。和模板上线前的报告页一模一样。"""
    指标 = 已登记指标()
    return {"名称": 默认模板名, "适用门店": [全部门店], "默认期间": "周",
            "章节": [{"标题": "本期发生的", "指标": [dict(名=x["名"], 显示=True, 必选=x["必选"]) for x in 指标 if x["段"] == "期内"]},
                     {"标题": "截至今天还压着的", "指标": [dict(名=x["名"], 显示=True, 必选=x["必选"]) for x in 指标 if x["段"] == "存量"]}]}


# ── 表 ───────────────────────────────────────────────────────────────
def _now():
    import ops
    return ops.now().strftime("%Y-%m-%d %H:%M:%S")


def _连(db=None):
    c = sqlite3.connect(db or DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def 确保表(c):
    c.execute("""CREATE TABLE IF NOT EXISTS report_template_ver(
        id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 版本行号:报告里冻的就是它(全表唯一)
        name TEXT NOT NULL,                     -- 模板名(「默认」+ 各家店的专用模板)
        version INTEGER NOT NULL,               -- 这个模板的第几版
        payload TEXT NOT NULL,                  -- 这一版**完整的**模板(JSON)
        why TEXT NOT NULL,                      -- 为什么改(人填)
        by_no TEXT, by_name TEXT,
        at TEXT NOT NULL,                       -- 世界时间
        UNIQUE(name, version))""")


def _各模板最新(c, 建=True):
    if 建:
        确保表(c)
    return [dict(r) for r in c.execute(
        "SELECT v.* FROM report_template_ver v WHERE v.version=(SELECT MAX(version) FROM report_template_ver x "
        "WHERE x.name=v.name) ORDER BY v.name")]


def _门店们(c):
    """→ {门店标识: 店名}。标识用业务数据里的写法「SH001 静安旗舰店」(staff.shop / 订单 / 报告都是这一串),不是裸编码。"""
    try:
        return {f"{r[0]} {r[1]}": r[1] for r in c.execute("SELECT code, name FROM shop ORDER BY code")}
    except sqlite3.Error:
        return {}


# ── 生效 ─────────────────────────────────────────────────────────────
def 生效(shop, db=None):
    """→ 这家店此刻生效的那一版:dict(模板, 版本, 版本号, 内容)。版本号 = 版本行号;代码默认时为 None。
    认领顺序:列了这家店的专用模板 → 「默认」模板 → 代码默认。库读不到时退回代码默认(全部显示,和上线前一样)。"""
    # 只读连接:取数包是读路径,不许顺手建表;表还没建(没人存过模板)→ 走代码默认
    try:
        with closing(sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True, timeout=5)) as c:
            c.row_factory = sqlite3.Row
            行 = _各模板最新(c, 建=False)
    except sqlite3.Error:
        行 = []
    专用 = [r for r in 行 if r["name"] != 默认模板名 and shop in (json.loads(r["payload"]).get("适用门店") or [])]
    默 = [r for r in 行 if r["name"] == 默认模板名]
    r = (专用 or 默 or [None])[0]
    if r is None:
        return dict(模板=默认模板名, 版本=0, 版本号=None, 内容=默认内容())
    return dict(模板=r["name"], 版本=r["version"], 版本号=r["id"], 内容=json.loads(r["payload"]))


def 冻结用(shop, db=None):
    """给 store_report 放进取数包的那一份 —— 存报告时随取数包一起冻结。**只放显示规则,不放日期**
    (取数包那一列登记了每日平移,日期形状的串会被挪)。"""
    g = 生效(shop, db)
    隐 = [x["名"] for 节 in g["内容"]["章节"] for x in 节["指标"] if not x.get("显示", True)]
    return {"模板": g["模板"], "版本": g["版本"], "版本号": g["版本号"],
            "默认期间": g["内容"].get("默认期间", "周"), "章节": g["内容"]["章节"], "隐藏的": 隐,
            "怎么用": "报告按这份模板的章节排;「隐藏的」那几项数据照取、**不写进正文**(总部在报告模板里隐藏了);"
                     "必选项永远显示。模板只管显示,不改任何一个数的算法。"}


def 视图(pack):
    """打开一份存过的报告时怎么显示 —— **只读取数包里冻结的模板**,不读模板表。
    → dict(冻结了模板, 模板, 版本, 说明, 章节=[{标题, 指标=[{名, 段, 状态, 必选, 值, 口径, 出处}]}])
    状态:显示 / 被隐藏 / 取不到。被隐藏优先于取不到(模板说不显示,就不去论它取没取到)。"""
    pack = pack or {}
    t = pack.get("报告模板")
    冻 = bool(t and t.get("章节"))
    章节 = t["章节"] if 冻 else [
        {"标题": "本期发生的", "指标": [dict(名=k, 显示=True, 必选=bool((v or {}).get("必选"))) for k, v in (pack.get("期内") or {}).items()]},
        {"标题": "截至今天还压着的", "指标": [dict(名=k, 显示=True) for k in (pack.get(存量键) or {})]}]
    缺 = [str(x) for x in (pack.get("取不到的") or [])]

    def 找(名):
        for 段, 键 in (("期内", "期内"), ("存量", 存量键)):
            if 名 in (pack.get(键) or {}):
                return 段, pack[键][名]
        return None, None

    def 行(x):
        段, v = 找(x["名"])
        有值 = v is not None and (v.get("值") not in (None, {}, []))
        if not x.get("显示", True):
            状 = "被隐藏"
        elif not 有值:
            状 = "取不到"
        else:
            状 = "显示"
        原因 = next((s for s in 缺 if s.startswith(x["名"] + ":")), None)
        return dict(名=x["名"], 段=段, 状态=状, 必选=bool(x.get("必选")), 值=(v or {}).get("值"),
                    口径=(v or {}).get("口径"), 出处=(v or {}).get("出处"),
                    **({"取不到的原因": 原因} if 状 == "取不到" and 原因 else {}))

    出 = [dict(标题=节["标题"], 指标=[行(x) for x in 节["指标"]]) for 节 in 章节]
    列了 = {x["名"] for 节 in 章节 for x in 节["指标"]}
    漏 = [k for 键 in ("期内", 存量键) for k in (pack.get(键) or {}) if k not in 列了]
    if 漏:
        # 模板存了之后取数包又新加的指标:模板没说隐藏,就照「默认全选」显示,单独一节标出来
        出.append(dict(标题="模板里没列到的(模板存了之后新登记的指标)", 指标=[行(dict(名=k, 显示=True)) for k in 漏]))
    return dict(冻结了模板=冻, 模板=(t or {}).get("模板"), 版本=(t or {}).get("版本"), 版本号=(t or {}).get("版本号"),
                说明=(f"按保存那一刻冻结的模板「{t.get('模板')}」第 {t.get('版本')} 版显示 —— 之后模板再改,这份报告不跟着变"
                      if 冻 else "这份报告存于报告模板上线之前,没有冻结模板 —— 按取数包原样全部显示(不拿现行模板去套)"),
                章节=出)


# ── 读(页面)──────────────────────────────────────────────────────────
def 概览(db=None):
    with closing(_连(db)) as c:
        行 = _各模板最新(c)
        店 = _门店们(c)
    模板们 = [dict(名称=r["name"], 版本=r["version"], 版本号=r["id"], 更新=r["at"], 更新人=r["by_name"],
                理由=r["why"], **{k: v for k, v in json.loads(r["payload"]).items() if k in ("适用门店", "默认期间")})
           for r in 行]
    if not any(r["name"] == 默认模板名 for r in 行):
        模板们.insert(0, dict(名称=默认模板名, 版本=0, 版本号=None, 更新=None, 更新人=None,
                           理由="还没存过 —— 用的是代码默认(全部显示)", 适用门店=[全部门店], 默认期间="周"))
    return dict(模板们=模板们, 已登记指标=已登记指标(), 锁定必选=list(锁定必选()), 期间们=list(期间们),
                门店们=店, 可编辑角色=list(可编辑角色))


def 详情(name, db=None):
    with closing(_连(db)) as c:
        确保表(c)
        版们 = [dict(r, payload=json.loads(r["payload"])) for r in c.execute(
            "SELECT * FROM report_template_ver WHERE name=? ORDER BY version DESC", (name,))]
    if not 版们 and name != 默认模板名:
        return {"error": f"没有这个模板:{name}"}
    return dict(名称=name, 当前=(版们[0]["payload"] if 版们 else 默认内容()), 版本=(版们[0]["version"] if 版们 else 0),
                版本记录=[dict(版本=v["version"], 版本号=v["id"], 理由=v["why"], 谁=v["by_name"], 时间=v["at"], 内容=v["payload"])
                      for v in 版们],
                已登记指标=已登记指标(), 锁定必选=list(锁定必选()), 期间们=list(期间们))


# ── 写 ───────────────────────────────────────────────────────────────
def _闸(me):
    if not me or not me.get("no"):
        return "没登录 —— 改报告模板要登录,署名用登录的人"
    if me.get("role") not in 可编辑角色:
        return f"报告模板只有{'/'.join(可编辑角色)}能改,你是「{me.get('role')}」"
    return None


def 校验(p, c, name):
    """→ 错误列表。名字在不在已登记清单、必选取消没有、适用门店是不是真店、有没有被两个模板认领。"""
    错 = []
    if not isinstance(p, dict):
        return ["模板要是一个对象"]
    多 = set(p) - {"名称", "适用门店", "默认期间", "章节"}
    if 多:
        错.append(f"这些不开放配置:{sorted(多)}(模板只管章节、显示 / 隐藏、必选、默认期间、适用门店)")
    if p.get("默认期间") not in 期间们:
        错.append(f"默认期间只能是 {' / '.join(期间们)},不能是「{p.get('默认期间')}」")
    登 = {x["名"]: x for x in 已登记指标()}
    锁 = 锁定必选()
    章 = p.get("章节")
    if not isinstance(章, list) or not 章:
        错.append("至少要有一个章节")
        章 = []
    见 = {}
    for i, 节 in enumerate(章, 1):
        if not isinstance(节, dict) or not str(节.get("标题") or "").strip():
            错.append(f"第 {i} 个章节没有标题")
            continue
        for x in 节.get("指标") or []:
            n = (x or {}).get("名")
            if n not in 登:
                错.append(f"「{n}」不是已登记的指标 —— 只能从取数包现有的这些里选:{'、'.join(登)}")
                continue
            if n in 见:
                错.append(f"「{n}」出现了两次(「{见[n]}」和「{节['标题']}」)")
            见[n] = 节["标题"]
            if n in 锁:
                if not x.get("必选") or not x.get("显示", True):
                    错.append(f"「{n}」是锁定必选项(用户 10-09 定:下单数和营收必选)—— 不能取消必选、不能隐藏")
            elif x.get("必选"):
                错.append(f"「{n}」不能标必选 —— 现在只有 {'、'.join(锁)} 两项必选;要加必选项先找业务拍板")
    for n in 锁:
        if n not in 见:
            错.append(f"「{n}」是锁定必选项,模板里不能删掉它")
    店 = p.get("适用门店")
    if not isinstance(店, list):
        错.append("适用门店要是一个列表")
        店 = []
    if name == 默认模板名:
        if 店 != [全部门店]:
            错.append(f"「{默认模板名}」模板永远适用全部门店(没被专用模板认领的店都用它),适用门店只能是 [{全部门店}]")
    else:
        真店 = _门店们(c)
        for s in 店:
            if s not in 真店:
                错.append(f"「{s}」不是门店(有:{'、'.join(真店)})")
        for r in _各模板最新(c):
            if r["name"] in (name, 默认模板名):
                continue
            重 = set(店) & set(json.loads(r["payload"]).get("适用门店") or [])
            if 重:
                错.append(f"{'、'.join(sorted(重))} 已经被模板「{r['name']}」认领了 —— 一家店只能用一个专用模板")
    return 错


def 保存(name, payload, 理由, me, db=None):
    """存一版(只增不改)。→ {ok, 版本, 版本号} 或 {ok:False, reason, 错}。"""
    e = _闸(me)
    if e:
        return dict(ok=False, code="NO_AUTH" if not (me or {}).get("no") else "FORBIDDEN", reason=e)
    name = str(name or "").strip()
    if not name or len(name) > 30:
        return dict(ok=False, reason="模板名要写,30 字以内")
    if not (理由 or "").strip():
        return dict(ok=False, reason="改报告模板要写理由 —— 以后有人问「这一版为什么把某项藏了」,答案在这里")
    p = dict(payload or {})
    p["名称"] = name
    with closing(_连(db)) as c:
        确保表(c)
        错 = 校验(p, c, name)
        if 错:
            return dict(ok=False, reason=";".join(错[:3]) + (f" 等 {len(错)} 处" if len(错) > 3 else ""), 错=错)
        版 = (c.execute("SELECT MAX(version) FROM report_template_ver WHERE name=?", (name,)).fetchone()[0] or 0) + 1
        rid = c.execute("INSERT INTO report_template_ver(name,version,payload,why,by_no,by_name,at) VALUES(?,?,?,?,?,?,?)",
                        (name, 版, json.dumps(p, ensure_ascii=False), 理由.strip(), me["no"], me.get("name"), _now())).lastrowid
        c.commit()
    try:
        from oplog import log_op
        log_op(f"{me.get('name')}({me['no']})", "report_template", f"{name}#{版}", f"第 {版 - 1} 版", f"第 {版} 版",
               True, "RPT_TPL_SAVE", 理由.strip()[:120], {"版本号": rid})
    except Exception:
        pass
    return dict(ok=True, 模板=name, 版本=版, 版本号=rid)
