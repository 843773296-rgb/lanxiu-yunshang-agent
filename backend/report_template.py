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

「被隐藏」和「取不到」分开标:隐藏 = 模板说不显示(数这一期没交给写报告的 AI);取不到 = 要显示、但取数包里没有这一项或值为空。

## 10-23 用户在五张选型卡上拍的板(这一版落的)

  ① **指标登记**:每个已登记指标在 `指标登记` 里登记主题 / 重要度 / 关联(用户审过)。取数包新加一项不登记 →
     `登记问题()` 非空 → report_template_check 红(过不了门禁)。
  ② **每节只放一种**:一节里不许混放「期内」和「存量」;代码默认按「主题 × 段」分节。库里已有的旧版不动,只在新存时拦。
  ③ **新指标插位**:模板存了之后取数包又新加的指标,默认显示,位置按「关联 → 同主题同段的节按重要度 → 另开一节」,
     带「新增未配」标记,页面上提示总部去配。
  ④ **必选可加,缺了拦确认**:任何已登记指标都能标必选(订单、营收仍锁定);但默认期间里**结构上取不到**的
     (api.报告期取不到,和 store_report 用的是同一份)不许标必选。确认那一步(report_doc.确认)读冻结的模板,
     必选项取不到就拒绝确认 —— 「取不到」= 取数包里没有这一项、或值是 None;0 / 空串 / 空列表都算取到。
  ⑤ **隐藏项不交给 AI**:store_report 把被隐藏的指标整项从取数包里拿掉(期内 / 存量 / 环比都不留),
     只在「报告模板」里留「隐藏的」名单 —— 写正文的那一步**结构上**写不出它(boundary_audit 真攻击)。
  ⑥ **草稿 → 试运行 → 发布**:存一版 = 草稿(不生效);试运行要写试点门店(真门店);不许跳;
     同一模板同一时刻最多一版试运行、一版已发布(新发布的把旧发布的顶成已撤下)。
     生效:这家店在某版试运行的试点里 → 那一版;否则最新已发布;都没有 → 代码默认。
     库里加状态列之前存的版本,加列时默认「已发布」(和加列前的生效规则一样)。
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
import shop_key as _SK                         # 门店关联键的唯一来源

默认模板名 = "默认"
全部门店 = "全部"
_段名 = {"期内": "期内", "存": "存量"}
存量键 = "存量(截至今天)"
段标题 = {"期内": "本期", "存量": "截至今天"}

# ── 指标登记(用户 10-23 审过、按这版生效):名 / 主题 / 重要度 / 关联 ──────────────
# 和 已登记指标() 一一对应 —— 取数包新加一项、这里没登记 → 登记问题() 非空 → report_template_check 红。
# 顺序 = 「同档按登记顺序」的那个顺序。
主题们 = ("销售", "客流", "交付", "售后口碑", "客户", "运营")
重要度们 = ("核心", "常看", "参考")          # 核心 > 常看 > 参考
指标登记 = [
    ("营收", "销售", "核心", ("订单", "销量")),
    ("订单", "销售", "核心", ("营收", "待付款")),
    ("成交率", "销售", "核心", ("到店客户数", "订单")),
    ("销量", "销售", "常看", ("营收", "库存")),
    ("待付款", "销售", "常看", ("订单",)),
    ("到店客户数", "客流", "核心", ("进店客流", "成交率")),
    ("进店客流", "客流", "常看", ("到店客户数",)),
    ("约了没来", "客流", "常看", ("到店客户数",)),
    ("该催工厂", "交付", "核心", ("延期没告诉顾客", "白坯试衣")),
    ("延期没告诉顾客", "交付", "核心", ("该催工厂",)),
    ("白坯试衣", "交付", "常看", ("该催工厂",)),
    ("库存", "交付", "常看", ("销量",)),
    ("差评待跟", "售后口碑", "核心", ("评价", "售后")),
    ("评价", "售后口碑", "常看", ("差评待跟",)),
    ("售后", "售后口碑", "常看", ("差评待跟",)),
    ("流失预警", "客户", "常看", ("进入休眠",)),
    ("进入休眠", "客户", "参考", ("流失预警",)),
    ("任务", "运营", "参考", ()),
]


# ── 已登记指标:读 api.store_report 的源码现算 ─────────────────────────────
_缓存 = {}


def _解析():
    """→ (指标们 [(名, 段)], 必选 (名…), 报告期取不到 {期间: (名…)})。按 api.py 的修改时间缓存;
    解析不出来就抛 —— 清单空了不许当成「没有限制」。"""
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
    # 哪一种报告结构上取不到哪几项:读 api.py 模块级的 `报告期取不到 = {...}` —— store_report 自己也用它置空,
    # 所以「模板说取不到」和「取数包真的取不到」是同一份,不手抄
    取不到 = None
    for n in 树.body:
        if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "报告期取不到" for t in n.targets)):
            取不到 = {k: tuple(v) for k, v in ast.literal_eval(n.value).items()}
    if 取不到 is None:
        raise RuntimeError("api.py 里找不到 `报告期取不到 = {...}` —— 哪种报告取不到哪几项算不出来")
    值 = (指标, 必选, 取不到)
    _缓存.update(键=键, 值=值)
    return 值


def _登():
    return {n: dict(主题=主, 重要度=重, 关联=tuple(关)) for n, 主, 重, 关 in 指标登记}


def 已登记指标():
    """→ [{名, 段, 必选, 主题, 重要度, 关联}]。段 = 期内 / 存量。主题 / 重要度没登记的为 None(登记问题() 会报)。"""
    指标, 必选, _ = _解析()
    登 = _登()
    return [dict(名=n, 段=s, 必选=n in 必选, 主题=(登.get(n) or {}).get("主题"), 重要度=(登.get(n) or {}).get("重要度"),
                 关联=list((登.get(n) or {}).get("关联") or ())) for n, s in 指标]


def 锁定必选():
    return _解析()[1]


def 报告期取不到():
    """→ {期间: (名…)}:这一种报告**结构上**取不到的指标(不是这一期碰巧没数)。和 store_report 置空用的是同一份。"""
    return _解析()[2]


def 登记问题():
    """→ 错误列表:已登记指标里有没登记主题 / 重要度的、登记表里有清单外的名字、关联指向不存在的指标、主题 / 重要度写错。"""
    错 = []
    清单 = [x["名"] for x in 已登记指标()]
    名们 = [n for n, *_ in 指标登记]
    for n in 清单:
        if n not in 名们:
            错.append(f"「{n}」在取数包里(已登记指标),却没在指标登记里登记主题 / 重要度 —— 新加一项指标要一起登记")
    for n in 名们:
        if n not in 清单:
            错.append(f"指标登记里的「{n}」不在已登记指标清单里(取数包没有这一项)")
    重 = sorted({n for n in 名们 if 名们.count(n) > 1})
    if 重:
        错.append(f"指标登记里重复登记了:{'、'.join(重)}")
    for n, 主, 度, 关 in 指标登记:
        if 主 not in 主题们:
            错.append(f"「{n}」的主题「{主}」不在 {' / '.join(主题们)} 里")
        if 度 not in 重要度们:
            错.append(f"「{n}」的重要度「{度}」不在 {' / '.join(重要度们)} 里")
        for a in 关:
            if a not in 名们 or a not in 清单:
                错.append(f"「{n}」关联的「{a}」不是已登记的指标")
    return 错


def 节标题(主题, 段):
    return f"{主题 or '其他'} · {段标题.get(段, 段)}"


def _档(重要度):
    return 重要度们.index(重要度) if 重要度 in 重要度们 else len(重要度们)


def 默认内容():
    """没存过任何一版时的模板:按「主题 × 段」分节(用户 10-23 选「每节只放一种」),标题形如「销售 · 本期」
    「销售 · 截至今天」;节内按重要度、同档按登记顺序;没有指标的组合不出节。全部显示,必选按 store_report。"""
    指标 = 已登记指标()
    序 = {n: i for i, (n, *_) in enumerate(指标登记)}
    组 = [(主, 段) for 主 in 主题们 for 段 in ("期内", "存量")]
    组 += [(None, 段) for 段 in ("期内", "存量")]      # 没登记主题的(登记问题() 会红)也别丢,放最后
    章节 = []
    for 主, 段 in 组:
        项 = sorted((x for x in 指标 if x["主题"] == 主 and x["段"] == 段),
                   key=lambda x: (_档(x["重要度"]), 序.get(x["名"], len(序))))
        if 项:
            章节.append({"标题": 节标题(主, 段), "指标": [dict(名=x["名"], 显示=True, 必选=x["必选"]) for x in 项]})
    return {"名称": 默认模板名, "适用门店": [全部门店], "默认期间": "周", "章节": 章节}


# ── 表 ───────────────────────────────────────────────────────────────
def _now():
    import ops
    return ops.now().strftime("%Y-%m-%d %H:%M:%S")


def _连(db=None):
    c = sqlite3.connect(db or DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


# 每一版的状态(用户 10-23 选「草稿 → 试运行 → 发布」)。不许跳;已发布的只会被同一模板新发布的那一版顶成已撤下
状态们 = ("草稿", "试运行", "已发布", "已撤下")
可走 = {
    "草稿": ("试运行",),
    "试运行": ("已发布", "已撤下"),
    # 已发布可以直接撤下(用户 10-23 拍「允许,回到上一版」):撤下时把被它顶下来的那一版恢复成已发布,没有就回代码默认
    "已发布": ("已撤下",),
    # 撤下的不再回到试运行(用户 10-23 拍「另存新版本」)—— 一个版本只有一段经历;要再试用「复制为新草稿」
    "已撤下": (),
}
# 试运行满这么多天还没发布 → 自动撤下(用户 10-23 拍「到期自动撤下」)。
# 30 天是用户 10-23 定的(「试用期一个月吧」;我最初提的 14 天是拍脑袋的)。试点店到期回到已发布的那一版。
# 判过期按**世界时间**(ops.now)和 trial_at 比 —— trial_at 是整列日期、每日平移跟着挪,两边同一个世界,天数不漂。
试运行天数 = 30
# 后加的列(10-23 状态线):建表语句不改 —— 老库里表已经在,CREATE IF NOT EXISTS 不会补列;补列走 ALTER,有就跳过。
# ⚠️ status 加列时默认「已发布」:加列之前存的版本当时一存就生效,迁移成已发布,生效规则和加列前一样(别丢)。
#    新存的一版写口里**显式**写「草稿」。
# 日期列:trial_at / publish_at / withdraw_at(世界时间,整列日期,和 at 一样);
# 人填的文本:trial_why / publish_why / withdraw_why(和 why 一样是原话);trial_shops 是 JSON 门店标识列表
后加列 = [
    ("status", "TEXT NOT NULL DEFAULT '已发布'"),
    ("trial_shops", "TEXT"),
    ("trial_at", "TEXT"), ("trial_by", "TEXT"), ("trial_why", "TEXT"),
    ("publish_at", "TEXT"), ("publish_by", "TEXT"), ("publish_why", "TEXT"),
    ("withdraw_at", "TEXT"), ("withdraw_by", "TEXT"), ("withdraw_why", "TEXT"),
]


def _店表(c):
    """→ `{显示串: 门店编码}`;**`shop` 表还没建就给空表**(不抛)。

    ⚠️ 容错要写在**取数**上,不是写在判断上。我第一版写的是
    `店表 = _店表(c)` 然后 `if not 店表: return 0` —— 而取那张表本身就会抛:
    `report_template_check` 在一个只建了模板表的**最小库**上跑真写口,当场
    `no such table: shop`。而它在全量门禁里是绿的(那条走的是有 shop 表的库)——
    **同一个脚本在两个库上说法不同**。
    空表时 `_归一` 什么都不改,所以这条退路不会把好数据洗坏。"""
    try:
        return _SK.门店表(c)
    except sqlite3.Error:
        return {}


def _归一(店表, 值):
    """门店标识 → 门店**编码**;认不出的原样返回(「全部」这个常量、工坊、改过名的老串)。

    `店表` 是 `shop_key.门店表(c)`,即 `{显示串: 编码}`。**做成纯函数**(只吃一张表,
    不吃连接)是故意的:判据可以直接喂一张假门店表验它,不用连库。

    ## 为什么模板这一处要自己守

    试点门店和适用门店存在 **JSON 数组**里,`shop_key_check` 那套棘轮扫的是 SQL 字符串里的
    `shop=?`,**扫不到它们**。而改一个门店名之后,坏的不是读路径(存的和传进来的都是老串,
    照旧命中),是另外两处:

      · `改状态` 把老串判成「不是门店」—— 功能当场卡住,这个看得见
      · **「一家店同一时刻只试一版」那条互斥拿字符串比** —— 老串和新串被当成两家店,
        于是同一家店能同时试两版,**而且不报错**

    > **两个指同一家店的标识,在字符串比较上长得不一样。**
    """
    s = str(值).strip()
    return 店表.get(s) or s          # 传进来本来就是编码时,`get` 取不到,原样留着


def _显示(店表, 码):
    """门店编码 → 显示串(给页面看的)。认不出的原样返回。

    ⚠️ 存的是编码,**而页面要给人看店名** —— 少了这一步,后台模板页上门店会变成「SH001」。"""
    s = str(码).strip()
    return next((k for k, v in 店表.items() if v == s), s)


def _迁门店标识(c):
    """**幂等**:把已经存下来的门店标识(显示串)换成门店编码 → 改了几行。

    ⚠️ 它挂在 `确保表()` 里,跟建表 / 补列同一处,**不新开流水线步骤** ——
    今天 CI 为「让生产查询依赖某个流水线步骤已经跑过」红了第三次,这是同一个教训:
    新开一步就会多出「迁移还没跑」这个状态,而那个状态和「迁过了」在查询结果上长得一样。
    现在这张表是空的,所以它平时是个空操作;真有数据的环境第一次写入时就迁掉。"""
    店表 = _店表(c)
    if not 店表:
        return 0                     # 门店表取不到 → 什么都不改(**别拿空口径去改数据**)
    改 = 0
    for r in c.execute("SELECT id, payload, trial_shops FROM report_template_ver").fetchall():
        rid, payload, trial = r[0], r[1], r[2]
        新payload, 新trial = payload, trial
        try:
            p = json.loads(payload or "{}")
            店 = p.get("适用门店")
            if isinstance(店, list):
                归 = [_归一(店表, s) for s in 店]
                if 归 != 店:
                    p["适用门店"] = 归
                    新payload = json.dumps(p, ensure_ascii=False)
        except (ValueError, TypeError):
            pass                     # 存坏了的 JSON 不在这一步处理,原样留着让校验那边去报
        try:
            t = json.loads(trial or "[]")
            if isinstance(t, list):
                归t = [_归一(店表, s) for s in t]
                if 归t != t:
                    新trial = json.dumps(归t, ensure_ascii=False)
        except (ValueError, TypeError):
            pass
        if 新payload != payload or 新trial != trial:
            c.execute("UPDATE report_template_ver SET payload=?, trial_shops=? WHERE id=?",
                      (新payload, 新trial, rid))
            改 += 1
    if 改:
        c.commit()
    return 改


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
    有 = {r[1] for r in c.execute("PRAGMA table_info(report_template_ver)")}
    for 列, 型 in 后加列:
        if 列 not in 有:
            c.execute(f"ALTER TABLE report_template_ver ADD COLUMN {列} {型}")
    _迁门店标识(c)        # 幂等,平时是空操作;**跟补列同一处,就不会有「迁移还没跑」这个状态**


def _行(r):
    """库里一行 → dict;还没补状态列的老库(只读连接补不了)按「已发布」读 —— 和加列时的默认值一致。"""
    d = dict(r)
    d["status"] = d.get("status") or "已发布"
    d["试点"] = json.loads(d.get("trial_shops") or "[]")
    return d


def _全部(c):
    return [_行(r) for r in c.execute("SELECT * FROM report_template_ver ORDER BY name, version")]


def _各模板最新(c, 建=True):
    if 建:
        确保表(c)
    return [_行(r) for r in c.execute(
        "SELECT v.* FROM report_template_ver v WHERE v.version=(SELECT MAX(version) FROM report_template_ver x "
        "WHERE x.name=v.name) ORDER BY v.name")]


def _在用(行们):
    """→ {模板名: dict(发布=那一行或 None, 试运行=那一行或 None)}。同一模板最多各一版;老数据迁移后可能多版已发布,取最新那版。"""
    出 = {}
    for r in 行们:
        d = 出.setdefault(r["name"], {"发布": None, "试运行": None})
        键 = {"已发布": "发布", "试运行": "试运行"}.get(r["status"])
        if 键 and (d[键] is None or r["version"] > d[键]["version"]):
            d[键] = r
    return 出


def _过期(r, 今):
    """这一版是不是试运行满了 试运行天数 还没发布。trial_at 读不出来按没过期(不替人撤)。"""
    if r.get("status") != "试运行" or not r.get("trial_at"):
        return False
    import datetime as _dt
    try:
        起 = _dt.datetime.strptime(str(r["trial_at"])[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return 今 - 起 >= _dt.timedelta(days=试运行天数)


def _世界今天():
    import ops
    return ops.now().replace(tzinfo=None)


def _撤过期(c):
    """把试运行满期的落成「已撤下」(写路径和页面打开时调;读路径 生效() 另按 _过期 现算,不靠这一步落库)。→ 撤下的 [(name, version)]。"""
    今, now, 撤 = _世界今天(), _now(), []
    for r in _全部(c):
        if _过期(r, 今):
            c.execute("UPDATE report_template_ver SET status='已撤下', withdraw_at=?, withdraw_by=?, withdraw_why=? WHERE id=?",
                      (now, "系统", f"试运行满 {试运行天数} 天还没发布,自动撤下(用户 10-23 拍);试点店回到已发布的那一版", r["id"]))
            撤.append((r["name"], r["version"]))
    if 撤:
        c.commit()
        try:
            from oplog import log_op
            for n, v in 撤:
                log_op("系统", "report_template", f"{n}#{v}", "试运行", "已撤下", True, "RPT_TPL_EXPIRE",
                       f"试运行满 {试运行天数} 天自动撤下", {})
        except Exception:
            pass
    return 撤


def _门店们(c):
    """→ {门店标识: 店名}。标识用业务数据里的写法「SH001 静安旗舰店」(staff.shop / 订单 / 报告都是这一串),不是裸编码。"""
    try:
        return {f"{r[0]} {r[1]}": r[1] for r in c.execute("SELECT code, name FROM shop ORDER BY code")}
    except sqlite3.Error:
        return {}


# ── 生效 ─────────────────────────────────────────────────────────────
def 生效(shop, db=None):
    """→ 这家店此刻生效的那一版:dict(模板, 版本, 版本号, 状态, 内容)。版本号 = 版本行号;代码默认时为 None。
    顺序(用户 10-23 拍):这家店在某版**试运行**的试点里 → 那一版;否则**最新已发布**(列了这家店的专用模板 →
    「默认」模板);都没有 → 代码默认。**草稿和已撤下永远不生效。** 库读不到时退回代码默认(全部显示,和上线前一样)。"""
    # 只读连接:取数包是读路径,不许顺手建表 / 补列;表还没建(没人存过模板)→ 走代码默认
    行, 店表 = [], {}
    try:
        with closing(sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True, timeout=5)) as c:
            c.row_factory = sqlite3.Row
            行 = _全部(c)
            店表 = _店表(c)      # {显示串: 编码} —— 下面比门店一律先归一到编码
    except sqlite3.Error:
        pass          # 读不到就走代码默认(和原来一样);`行` / `店表` 保持上面那两个初值
    if shop:
        # 满期的试运行不生效,哪怕还没人打开页面把它落成「已撤下」—— 读路径是只读连接,不靠写来保证
        今 = _世界今天()
        码 = _归一(店表, shop)
        试 = [r for r in 行 if r["status"] == "试运行"
              and 码 in {_归一(店表, s) for s in r["试点"]} and not _过期(r, 今)]
        if 试:
            r = max(试, key=lambda x: x["id"])
            return dict(模板=r["name"], 版本=r["version"], 版本号=r["id"], 状态="试运行", 内容=json.loads(r["payload"]))
    发 = [d["发布"] for _, d in sorted(_在用(行).items()) if d["发布"]]
    专用 = [r for r in 发 if r["name"] != 默认模板名
            and _归一(店表, shop) in {_归一(店表, s) for s in (json.loads(r["payload"]).get("适用门店") or [])}]
    默 = [r for r in 发 if r["name"] == 默认模板名]
    r = (专用 or 默 or [None])[0]
    if r is None:
        return dict(模板=默认模板名, 版本=0, 版本号=None, 状态="代码默认", 内容=默认内容())
    return dict(模板=r["name"], 版本=r["version"], 版本号=r["id"], 状态="已发布", 内容=json.loads(r["payload"]))


def 冻结用(shop, db=None):
    """给 store_report 放进取数包的那一份 —— 存报告时随取数包一起冻结。**只放显示规则,不放日期**
    (取数包那一列登记了每日平移,日期形状的串会被挪)。"""
    g = 生效(shop, db)
    隐 = [x["名"] for 节 in g["内容"]["章节"] for x in 节["指标"] if not x.get("显示", True)]
    return {"模板": g["模板"], "版本": g["版本"], "版本号": g["版本号"], "状态": g["状态"],
            "默认期间": g["内容"].get("默认期间", "周"), "章节": g["内容"]["章节"], "隐藏的": 隐,
            "怎么用": "报告按这份模板的章节排;「隐藏的」那几项总部在报告模板里隐藏了 —— **它们的数已经从这份取数包里拿掉**,"
                     "正文里不要提、也不要去别的工具补取;必选项永远显示。模板只管显示,不改任何一个数的算法。"}


def 视图(pack):
    """打开一份存过的报告时怎么显示 —— **只读取数包里冻结的模板**,不读模板表。
    → dict(冻结了模板, 模板, 版本, 说明, 章节=[{标题, 指标=[{名, 段, 状态, 必选, 值, 口径, 出处, 新增未配?}]}])
    状态:显示 / 被隐藏 / 取不到。被隐藏优先于取不到(模板说不显示,就不去论它取没取到)。
    被隐藏的那几项取数包里已经没有了(store_report 拿掉的),段从已登记清单里补。"""
    pack = pack or {}
    t = pack.get("报告模板")
    冻 = bool(t and t.get("章节"))
    章节 = t["章节"] if 冻 else [
        {"标题": "本期发生的", "指标": [dict(名=k, 显示=True, 必选=bool((v or {}).get("必选"))) for k, v in (pack.get("期内") or {}).items()]},
        {"标题": "截至今天还压着的", "指标": [dict(名=k, 显示=True) for k in (pack.get(存量键) or {})]}]
    缺 = [str(x) for x in (pack.get("取不到的") or [])]
    try:
        登段 = {x["名"]: x["段"] for x in 已登记指标()}
    except Exception:
        登段 = {}

    def 找(名):
        for 段, 键 in (("期内", "期内"), ("存量", 存量键)):
            if 名 in (pack.get(键) or {}):
                return 段, pack[键][名]
        return 登段.get(名), None

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
        # 模板存了之后取数包又新加的指标:模板没说隐藏,就默认显示,按「关联 → 同主题同段按重要度 → 另开一节」插位
        # (用户 10-23 原话:默认展示,显示位置根据重要性 / 指标互相关联的优先级排序)
        插新指标(出, [行(dict(名=k, 显示=True)) for k in 漏])
    return dict(冻结了模板=冻, 模板=(t or {}).get("模板"), 版本=(t or {}).get("版本"), 版本号=(t or {}).get("版本号"),
                状态=(t or {}).get("状态"),
                说明=(f"按保存那一刻冻结的模板「{t.get('模板')}」第 {t.get('版本')} 版显示 —— 之后模板再改,这份报告不跟着变"
                      if 冻 else "这份报告存于报告模板上线之前,没有冻结模板 —— 按取数包原样全部显示(不拿现行模板去套)"),
                新增未配=[x["名"] for 节 in 出 for x in 节["指标"] if x.get("新增未配")],
                章节=出)


def 插新指标(出, 新行们):
    """把模板没列到的指标插进章节(就地改 出)。每一项按顺序找位置:
      ① 它关联的指标在模板某一节里、且那一节的段和它相同 → 紧挨着排在那个关联指标后面
         (多个关联取模板里位置最靠前的那个;同一个关联后面已经插过的,排在它们后面);
      ② 否则找同主题同段的节(按节里已有指标的主题判断,取第一个),按重要度插进去,同档排在已有的后面;
      ③ 都没有才另开一节「<主题> · 本期 / 截至今天」。
    插进去的每一项带 新增未配=True —— 页面上提示「模板里没配过,按重要度自动放的」,让总部知道要去配。"""
    登 = _登()
    主题 = lambda 名: (登.get(名) or {}).get("主题")
    档 = lambda 名: _档((登.get(名) or {}).get("重要度"))
    节段 = lambda 节: {x["段"] for x in 节["指标"] if x.get("段")}
    原位 = {x["名"]: (i, j) for i, 节 in enumerate(出) for j, x in enumerate(节["指标"])}
    for r in 新行们:
        r["新增未配"] = True
        名, 段 = r["名"], r["段"]
        候 = sorted((原位[a], a) for a in (登.get(名) or {}).get("关联", ()) if a in 原位 and 节段(出[原位[a][0]]) == {段})
        if 候:
            (i, _), 锚 = 候[0]            # 节的下标不会变(新开的节只往后加);节内位置按名字现找
            列 = 出[i]["指标"]
            k = next(n for n, x in enumerate(列) if x["名"] == 锚) + 1
            while k < len(列) and 列[k].get("新增未配") and 列[k].get("_锚") == 锚:
                k += 1
            r["_锚"] = 锚
            列.insert(k, r)
            continue
        节 = next((节 for 节 in 出 if 主题(名) and 节段(节) == {段}
                   and any(主题(x["名"]) == 主题(名) for x in 节["指标"])), None)
        if 节 is None:
            标题 = 节标题(主题(名), 段)
            节 = next((节 for 节 in 出 if 节.get("_新开") and 节["标题"] == 标题), None)
            if 节 is None:
                节 = dict(标题=标题, 指标=[], _新开=True)
                出.append(节)
        列 = 节["指标"]
        同 = [n for n, x in enumerate(列) if 主题(x["名"]) == 主题(名)] or list(range(len(列)))
        不弱 = [n for n in 同 if 档(列[n]["名"]) <= 档(名)]
        列.insert((max(不弱) + 1) if 不弱 else (min(同) if 同 else 0), r)
    for 节 in 出:
        节.pop("_新开", None)
        for x in 节["指标"]:
            x.pop("_锚", None)
    return 出


# ── 读(页面)──────────────────────────────────────────────────────────
def _版行(v, 店表=None):
    """一版 → 页面上的一行(含状态与留痕)。

    ⚠️ `店表` 给了就把门店编码转回显示串 —— **库里存的是编码,而页面要给人看店名**。
    不给就原样输出(编码),所以调用方该传。"""
    店表 = 店表 or {}
    内容 = json.loads(v["payload"]) if isinstance(v["payload"], str) else v["payload"]
    if 店表 and isinstance(内容, dict) and isinstance(内容.get("适用门店"), list):
        内容 = dict(内容, 适用门店=[_显示(店表, s) for s in 内容["适用门店"]])
    return dict(版本=v["version"], 版本号=v["id"], 理由=v["why"], 谁=v["by_name"], 时间=v["at"],
                内容=内容,
                状态=v["status"], 试点门店=[_显示(店表, s) for s in v["试点"]] if 店表 else v["试点"],
                留痕=[dict(到=到, 时间=v.get(f"{k}_at"), 谁=v.get(f"{k}_by"), 理由=v.get(f"{k}_why"))
                    for 到, k in (("试运行", "trial"), ("已发布", "publish"), ("已撤下", "withdraw")) if v.get(f"{k}_at")])


def 概览(db=None):
    with closing(_连(db)) as c:
        确保表(c)
        _撤过期(c)
        行 = _各模板最新(c)
        用 = _在用(_全部(c))
        店 = _门店们(c)
        店表 = _店表(c)

    def 在用(n):
        d = 用.get(n) or {}
        发, 试 = d.get("发布"), d.get("试运行")
        return dict(已发布版本=发["version"] if 发 else None, 试运行版本=试["version"] if 试 else None,
                    试点门店=[_显示(店表, s) for s in 试["试点"]] if 试 else [])
    模板们 = [dict(名称=r["name"], 版本=r["version"], 版本号=r["id"], 状态=r["status"], 更新=r["at"], 更新人=r["by_name"],
                理由=r["why"], **在用(r["name"]),
                **{k: ([_显示(店表, s) for s in v] if k == "适用门店" and isinstance(v, list) else v)
                   for k, v in json.loads(r["payload"]).items() if k in ("适用门店", "默认期间")})
           for r in 行]
    if not any(r["name"] == 默认模板名 for r in 行):
        模板们.insert(0, dict(名称=默认模板名, 版本=0, 版本号=None, 状态=None, 更新=None, 更新人=None,
                           理由="还没存过 —— 用的是代码默认(全部显示)", 已发布版本=None, 试运行版本=None, 试点门店=[],
                           适用门店=[全部门店], 默认期间="周"))
    return dict(模板们=模板们, 已登记指标=已登记指标(), 锁定必选=list(锁定必选()), 期间们=list(期间们),
                主题们=list(主题们), 重要度们=list(重要度们), 报告期取不到={k: list(v) for k, v in 报告期取不到().items()},
                门店们=店, 可编辑角色=list(可编辑角色), 状态们=list(状态们), 可走={k: list(v) for k, v in 可走.items()})


def 详情(name, db=None):
    with closing(_连(db)) as c:
        确保表(c)
        _撤过期(c)
        版们 = [_行(r) for r in c.execute(
            "SELECT * FROM report_template_ver WHERE name=? ORDER BY version DESC", (name,))]
        _表 = _店表(c)
    if not 版们 and name != 默认模板名:
        return {"error": f"没有这个模板:{name}"}
    _当前 = json.loads(版们[0]["payload"]) if 版们 else 默认内容()
    if isinstance(_当前.get("适用门店"), list):      # 存的是编码,页面要店名
        _当前 = dict(_当前, 适用门店=[_显示(_表, s) for s in _当前["适用门店"]])
    return dict(名称=name, 当前=_当前, 版本=(版们[0]["version"] if 版们 else 0),
                版本记录=[_版行(v, _表) for v in 版们],
                已登记指标=已登记指标(), 锁定必选=list(锁定必选()), 期间们=list(期间们),
                报告期取不到={k: list(v) for k, v in 报告期取不到().items()},
                状态们=list(状态们), 可走={k: list(v) for k, v in 可走.items()}, 试运行天数=试运行天数)


# ── 写 ───────────────────────────────────────────────────────────────
def _闸(me):
    if not me or not me.get("no"):
        return "没登录 —— 改报告模板要登录,署名用登录的人"
    if me.get("role") not in 可编辑角色:
        return f"报告模板只有{'/'.join(可编辑角色)}能改,你是「{me.get('role')}」"
    return None


def 校验(p, c, name):
    """→ 错误列表。名字在不在已登记清单、必选取消没有、必选项这种报告取不取得到、一节有没有混放期内和存量、
    适用门店是不是真店、有没有被两个模板认领。"""
    错 = []
    if not isinstance(p, dict):
        return ["模板要是一个对象"]
    多 = set(p) - {"名称", "适用门店", "默认期间", "章节"}
    if 多:
        错.append(f"这些不开放配置:{sorted(多)}(模板只管章节、显示 / 隐藏、必选、默认期间、适用门店)")
    期 = p.get("默认期间")
    if 期 not in 期间们:
        错.append(f"默认期间只能是 {' / '.join(期间们)},不能是「{期}」")
    登 = {x["名"]: x for x in 已登记指标()}
    锁 = 锁定必选()
    取不到 = 报告期取不到().get(期, ())
    章 = p.get("章节")
    if not isinstance(章, list) or not 章:
        错.append("至少要有一个章节")
        章 = []
    见 = {}
    for i, 节 in enumerate(章, 1):
        if not isinstance(节, dict) or not str(节.get("标题") or "").strip():
            错.append(f"第 {i} 个章节没有标题")
            continue
        段们 = {}
        for x in 节.get("指标") or []:
            n = (x or {}).get("名")
            if n not in 登:
                错.append(f"「{n}」不是已登记的指标 —— 只能从取数包现有的这些里选:{'、'.join(登)}")
                continue
            if n in 登:
                段们.setdefault(登[n]["段"], []).append(n)
            if n in 见:
                错.append(f"「{n}」出现了两次(「{见[n]}」和「{节['标题']}」)")
            见[n] = 节["标题"]
            if n in 锁:
                if not x.get("必选") or not x.get("显示", True):
                    错.append(f"「{n}」是锁定必选项(用户 10-09 定:下单数和营收必选)—— 不能取消必选、不能隐藏")
            elif x.get("必选"):
                # 用户 10-23 选 B:任何已登记指标都能标必选;但这种报告结构上取不到的不许 —— 不然每一期都确认不了
                if n in 取不到:
                    错.append(f"「{n}」:这一项{期}报取不到,设成必选会导致每一期都确认不了")
                if not x.get("显示", True):
                    错.append(f"「{n}」标了必选又隐藏 —— 隐藏的项不交给写报告的 AI,必选了就每一期都确认不了")
        if len(段们) > 1:
            # 用户 10-23 选「每节只放一种」:一节里混着「这一期发生的」和「截至今天还压着的」,读的人分不清哪个是本期新增
            错.append(f"「{节['标题']}」一节里混放了期内({'、'.join(段们.get('期内', []))})和存量"
                      f"({'、'.join(段们.get('存量', []))})的指标 —— 一节只放一种")
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
        店表 = _店表(c)
        码们 = set(店表.values())
        for s in 店:
            # 在**编码**上比。存的是编码,而页面传来的是显示串,两种都要认得出来
            if _归一(店表, s) not in 码们:
                错.append(f"「{_显示(店表, s)}」不是门店(有:{'、'.join(真店)})")
        # 别的模板的最新一版、在用的已发布 / 试运行那一版,认领的店都算 —— 只看最新版的话,
        # 别人草稿里放掉的店、而它已发布的那一版还认领着,就会被两个专用模板同时认领
        用 = _在用(_全部(c))
        for r in _各模板最新(c):
            if r["name"] in (name, 默认模板名):
                continue
            他 = [r] + [x for x in (用.get(r["name"]) or {}).values() if x]
            # ⚠️ **两边都归一到编码再取交集。** 一边存着老串、一边存着新串时,
            # 直接 `set & set` 会把同一家店当成两家,于是**一家店被两个专用模板同时认领而不报错**
            重 = {_归一(店表, s) for s in 店} & {_归一(店表, s)
                                              for x in 他
                                              for s in (json.loads(x["payload"]).get("适用门店") or [])}
            if 重:
                错.append(f"{'、'.join(sorted(_显示(店表, s) for s in 重))} 已经被模板「{r['name']}」认领了"
                         f" —— 一家店只能用一个专用模板")
    return 错


def 必选取不到(pack):
    """确认闸用(report_doc.确认):→ (冻结了模板, [取不到的必选项名])。
    必选项从**冻结的模板**读(视图(pack));「取不到」= 取数包里没有这一项、或这一项的值是 None / 缺「值」。
    ⚠️ 不用 `not 值` —— 那样会把 0、空串、空列表都判成取不到:这一期新客真的是 0、比率就是 0%,都算取到了。"""
    pack = pack or {}
    视 = 视图(pack)
    if not 视["冻结了模板"]:
        return False, []
    缺 = []
    for 节 in 视["章节"]:
        for x in 节["指标"]:
            if not x.get("必选"):
                continue
            项 = next(((pack.get(键) or {})[x["名"]] for 键 in ("期内", 存量键) if x["名"] in (pack.get(键) or {})), None)
            if not isinstance(项, dict) or "值" not in 项 or 项["值"] is None:
                缺.append(x["名"])
    return True, 缺


def 保存(name, payload, 理由, me, db=None):
    """存一版(只增不改)= **草稿,不生效**。要生效走 改状态:草稿 → 试运行 → 已发布。
    → {ok, 版本, 版本号, 状态} 或 {ok:False, reason, 错}。"""
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
        # 存**编码**(不存显示串)—— 门店改名之后,存编码的那一版照旧对得上,存显示串的对不上了。
        # 「全部」这个常量和认不出的值原样留着(`_归一` 不认识就不动)
        _表 = _店表(c)
        if isinstance(p.get("适用门店"), list):
            p["适用门店"] = [_归一(_表, s) for s in p["适用门店"]]
        错 = 校验(p, c, name)
        if 错:
            return dict(ok=False, reason=";".join(错[:3]) + (f" 等 {len(错)} 处" if len(错) > 3 else ""), 错=错)
        版 = (c.execute("SELECT MAX(version) FROM report_template_ver WHERE name=?", (name,)).fetchone()[0] or 0) + 1
        rid = c.execute("INSERT INTO report_template_ver(name,version,payload,why,by_no,by_name,at,status) "
                        "VALUES(?,?,?,?,?,?,?,'草稿')",
                        (name, 版, json.dumps(p, ensure_ascii=False), 理由.strip(), me["no"], me.get("name"), _now())).lastrowid
        c.commit()
    try:
        from oplog import log_op
        log_op(f"{me.get('name')}({me['no']})", "report_template", f"{name}#{版}", f"第 {版 - 1} 版", f"第 {版} 版(草稿)",
               True, "RPT_TPL_SAVE", 理由.strip()[:120], {"版本号": rid})
    except Exception:
        pass
    return dict(ok=True, 模板=name, 版本=版, 版本号=rid, 状态="草稿",
                note="存的是草稿,还没生效 —— 先试运行(写试点门店),再发布")


def 改状态(name, 版本, 到, 理由, me, 试点门店=None, db=None):
    """改一版的状态(只有总部运营,要写理由,留痕在这一行的 trial_* / publish_* / withdraw_* 和 op_log)。
    草稿 → 试运行(要试点门店,必须是真门店)→ 已发布;试运行也可以撤下。**不许跳。**
    同一模板同一时刻最多一版试运行、一版已发布:新发布的把旧发布的变成已撤下。"""
    e = _闸(me)
    if e:
        return dict(ok=False, code="NO_AUTH" if not (me or {}).get("no") else "FORBIDDEN", reason=e)
    if 到 not in 状态们:
        return dict(ok=False, reason=f"状态只能是 {' / '.join(状态们)}")
    if not (理由 or "").strip():
        return dict(ok=False, reason="改状态要写理由 —— 以后有人问「这一版为什么放出来了 / 为什么撤了」,答案在这里")
    理由 = 理由.strip()
    谁 = f"{me.get('name')}({me['no']})"
    try:
        版本 = int(版本)
    except (TypeError, ValueError):
        return dict(ok=False, reason="版本要是第几版(数字)")
    撤下的 = None
    恢复的 = None
    with closing(_连(db)) as c:
        确保表(c)
        _撤过期(c)          # 先把满期的落下来 —— 满期的试运行不许再发布
        r = c.execute("SELECT * FROM report_template_ver WHERE name=? AND version=?", (name, 版本)).fetchone()
        if not r:
            return dict(ok=False, reason=f"没有模板「{name}」的第 {版本} 版")
        r = _行(r)
        现 = r["status"]
        if 到 not in 可走.get(现, ()):
            return dict(ok=False, code="BAD_STEP",
                        reason=f"「{现}」不能直接到「{到}」,能走的是:{' / '.join(可走.get(现, ())) or '无'}"
                               "(草稿 → 试运行 → 已发布,不许跳)")
        用 = _在用(_全部(c))
        now = _now()
        if 到 in ("试运行", "已发布"):
            # 草稿存的时候校验过;到生效这一步再校一遍 —— 中间别的模板可能认领了同一家店
            错 = 校验(json.loads(r["payload"]), c, name)
            if 错:
                return dict(ok=False, reason=";".join(错[:3]), 错=错)
        if 到 == "试运行":
            真店 = _门店们(c)
            店表 = _店表(c)
            # 页面传来的是显示串,**存进去的是编码** —— 归一在进门这一步做完,后面全在编码上比
            店 = [_归一(店表, s) for s in (试点门店 or []) if str(s).strip()]
            if not 店:
                return dict(ok=False, reason="试运行要写试点门店(哪几家店先用这一版)")
            假 = [s for s in 店 if s not in set(店表.values())]
            if 假:
                return dict(ok=False, reason=f"{'、'.join(_显示(店表, s) for s in 假)} 不是门店(有:{'、'.join(真店)})")
            # 专用模板只在它适用的门店里试(用户 10-23 拍);「默认」适用全部,不受限
            if name != 默认模板名:
                适用 = {_归一(店表, s) for s in (json.loads(r["payload"]).get("适用门店") or [])}
                外 = [s for s in 店 if s not in 适用]
                if 外:
                    return dict(ok=False, reason=f"{'、'.join(_显示(店表, s) for s in 外)} 不在模板「{name}」的适用门店里"
                                                f" —— 专用模板只在它适用的门店里试运行")
            试 = (用.get(name) or {}).get("试运行")
            if 试:
                return dict(ok=False, reason=f"模板「{name}」第 {试['version']} 版已经在试运行 —— 同一模板同一时刻最多一版试运行;"
                                             "先把它发布或撤下")
            for 他名, d in 用.items():
                # ⚠️ **这条互斥是这一笔要修的主角。** 两边都归一到编码:
                # 一边老串一边新串时,直接比字符串会把同一家店当成两家,
                # **于是同一家店同时试两版,而且不报错**
                重 = set(店) & {_归一(店表, s) for s in ((d.get("试运行") or {}).get("试点") or [])}
                if 他名 != name and 重:
                    return dict(ok=False, reason=f"{'、'.join(sorted(_显示(店表, s) for s in 重))} 已经在模板「{他名}」"
                                                f"的试运行里 —— 一家店同一时刻只试一版")
            c.execute("UPDATE report_template_ver SET status='试运行', trial_shops=?, trial_at=?, trial_by=?, trial_why=? "
                      "WHERE id=?", (json.dumps(店, ensure_ascii=False), now, 谁, 理由, r["id"]))
        elif 到 == "已发布":
            旧 = [x for x in _全部(c) if x["name"] == name and x["status"] == "已发布"]
            for x in 旧:
                c.execute("UPDATE report_template_ver SET status='已撤下', withdraw_at=?, withdraw_by=?, withdraw_why=? "
                          "WHERE id=?", (now, 谁, f"第 {版本} 版发布,自动撤下(同一模板同一时刻只有一版已发布)", x["id"]))
            撤下的 = [x["version"] for x in 旧]
            c.execute("UPDATE report_template_ver SET status='已发布', publish_at=?, publish_by=?, publish_why=? WHERE id=?",
                      (now, 谁, 理由, r["id"]))
        else:   # 已撤下(从试运行来;或已发布直接撤 —— 用户 10-23 拍「允许,回到上一版」)
            c.execute("UPDATE report_template_ver SET status='已撤下', withdraw_at=?, withdraw_by=?, withdraw_why=? WHERE id=?",
                      (now, 谁, 理由, r["id"]))
            if 现 == "已发布":
                # 回到「被它顶下来的那一版」—— 按顶下来时写的那句认,不按「上一个版本号」猜:
                # 中间可能有一版是人手撤的,那一版不该被救回来
                前 = c.execute("SELECT * FROM report_template_ver WHERE name=? AND status='已撤下' AND withdraw_why LIKE ? "
                              "ORDER BY version DESC LIMIT 1", (name, f"第 {版本} 版发布,自动撤下%")).fetchone()
                if 前 and not 校验(json.loads(前["payload"]), c, name):
                    c.execute("UPDATE report_template_ver SET status='已发布', withdraw_at=NULL, withdraw_by=NULL, withdraw_why=NULL "
                              "WHERE id=?", (前["id"],))
                    恢复的 = 前["version"]
        c.commit()
    try:
        from oplog import log_op
        log_op(谁, "report_template", f"{name}#{版本}", 现, 到, True, "RPT_TPL_STATUS", 理由[:120],
               {"版本号": r["id"], **({"试点": 试点门店} if 到 == "试运行" else {}), **({"撤下": 撤下的} if 撤下的 else {}),
                **({"恢复": 恢复的} if 恢复的 else {})})
    except Exception:
        pass
    回 = dict(ok=True, 模板=name, 版本=版本, 从=现, 到=到, **({"顶下来的": 撤下的} if 撤下的 else {}))
    if 现 == "已发布" and 到 == "已撤下":
        回["回到"] = f"第 {恢复的} 版" if 恢复的 else "代码默认(之前没有发布过别的版本,或那一版现在通不过校验)"
    return 回


def 复制为草稿(name, 版本, 理由, me, db=None):
    """把某一版的内容另存成新的一版草稿(用户 10-23 拍:撤下的不重试,另存新版本)。走 保存 —— 同一道校验、同一份留痕。"""
    e = _闸(me)
    if e:
        return dict(ok=False, code="NO_AUTH" if not (me or {}).get("no") else "FORBIDDEN", reason=e)
    try:
        版本 = int(版本)
    except (TypeError, ValueError):
        return dict(ok=False, reason="版本要是第几版(数字)")
    with closing(_连(db)) as c:
        确保表(c)
        r = c.execute("SELECT payload FROM report_template_ver WHERE name=? AND version=?", (name, 版本)).fetchone()
    if not r:
        return dict(ok=False, reason=f"没有模板「{name}」的第 {版本} 版")
    return 保存(name, json.loads(r["payload"]), (理由 or "").strip() and f"复制自第 {版本} 版:{理由.strip()}", me, db=db)
