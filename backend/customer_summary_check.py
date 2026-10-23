#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户业务摘要 · 检查(复审第 4 节 A,用户 10-23 拍)。

**在自己造的形状上验,不靠库里碰巧有什么**(CLAUDE.md 第 8 节:一条判据红不红如果取决于环境里碰巧有什么数据,
它就不是在验代码)。所以这里在内存库里造一位客户,三个来源各放几条、完成的和开着的混着放、
到期日故意和编号顺序反着排、跟进记录里故意写一句「答应客户……」,然后**真调** `customer_summary.摘要`。

验的事:
  - 三个来源(商机的下一步 / 日程 / 商机任务)都进来,每条标了来源
  - 按到期排,没到期日的排最后
  - 已完成的不进(完结 / 已完成 / 取消的日程、完结的商机任务、终态商机的下一步)
  - 商机任务也是一条日程,只按「商机任务」列一次,不在「日程」里再列
  - 承诺栏不编造:跟进里写了「答应」,承诺栏照样是「没有结构化记录」、条目为空、那句话不出现在摘要里
  - 负责人换手:没有变更记录就明说查不到;有就列出来
  - 方案和订单按方案号连上,别的客户的东西不进
  - 样本量为 0 时报「没东西可验」,而不是绿
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("完结的商机任务也列进下一步(去掉状态过滤)", "已完成的不进:完结的商机任务"),
    ("下一步不排序", "按到期排"),
    ("商机任务不从日程里排除(同一条列两遍)", "商机任务只列一次"),
    ("终态商机的下一步也列进来", "已完成的不进:已关闭商机的下一步"),
    ("承诺栏编出一条", "承诺栏不编造"),
    ("样本为 0 也判通过", "样本量为 0 时报「没东西可验」"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:260]}" if 附 and not ok else ""))


def 判定(下一步们):
    """这份检查自己的样本量闸:一条下一步都没有 → 「没东西可验」,不是「通过」。"""
    if not 下一步们:
        return "没东西可验"
    return "有样本"


import customer_summary as CS  # noqa: E402

SCHEMA = """
CREATE TABLE customer(id TEXT PRIMARY KEY, name TEXT, advisor_no TEXT, shop TEXT);
CREATE TABLE staff(no TEXT PRIMARY KEY, name TEXT, adv_code TEXT);
CREATE TABLE opportunity(id TEXT PRIMARY KEY, customer_id TEXT, source TEXT, call_id TEXT, status TEXT,
  budget TEXT, next_step TEXT, close_reason TEXT, wait_for TEXT, scheme_id TEXT, advisor_no TEXT,
  confirmed_by TEXT, confirmed_at TEXT, created TEXT, updated TEXT);
CREATE TABLE opportunity_need(opp_id TEXT, dim TEXT, val TEXT, quote TEXT, call_id TEXT);
CREATE TABLE opportunity_task(schedule_id TEXT PRIMARY KEY, opp_id TEXT, kind TEXT, detail TEXT, created TEXT,
  answer TEXT, answered_by TEXT, answered_at TEXT);
CREATE TABLE schedule(id TEXT PRIMARY KEY, type TEXT, advisor_no TEXT, customer_id TEXT, start_ts TEXT, end_ts TEXT,
  status TEXT, summary TEXT, cancel_reason TEXT, shop TEXT, assignee_no TEXT, assigned_by TEXT, assigned_at TEXT,
  note TEXT, activity_code TEXT, ref_id TEXT, reassigned_from TEXT, reassign_reason TEXT, reassigned_at TEXT);
CREATE TABLE scheme(id TEXT PRIMARY KEY, customer_id TEXT, name TEXT, status TEXT, xz TEXT, mt TEXT, kf TEXT,
  color TEXT, ps TEXT, pattern TEXT, advisor_no TEXT, note TEXT, created TEXT, updated TEXT, opportunity_id TEXT);
CREATE TABLE ordr(id TEXT PRIMARY KEY, customer_id TEXT, status TEXT, amount REAL, created TEXT, scheme_id TEXT);
CREATE TABLE cust_owner_log(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT, frm TEXT, too TEXT,
  action TEXT, basis TEXT, actor TEXT, ts TEXT);
CREATE TABLE followup(id TEXT, customer_id TEXT, ts TEXT, content TEXT);
CREATE TABLE xingzhi(code TEXT, name TEXT); CREATE TABLE material(code TEXT, name TEXT);
CREATE TABLE craft(code TEXT, name TEXT);   CREATE TABLE pattern(code TEXT, name TEXT);
"""

承诺原话 = "答应客户十一月五号前把绣样照片发过去,另外免费改一次腰围"


def 造库():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    x = c.executemany
    x("INSERT INTO customer(id,name,advisor_no,shop) VALUES(?,?,?,?)", [("CX1", "甲", "S01", "一店"), ("CX2", "乙", "S02", "一店"),
                                              ("CX3", "丙", "S02", "一店")])
    x("INSERT INTO staff(no,name,adv_code) VALUES(?,?,?)", [("S01", "林岚", "A01"), ("S02", "陆微", "A02")])
    x("INSERT INTO xingzhi(code,name) VALUES(?,?)", [("XZ01", "马面裙")]); x("INSERT INTO material(code,name) VALUES(?,?)", [("MT01", "云锦")])
    x("INSERT INTO craft(code,name) VALUES(?,?)", [("KF01", "平绣")]); x("INSERT INTO pattern(code,name) VALUES(?,?)", [("PT01", "马面裙·标准")])
    # 商机:一条开着(跟进中)、一条搁置(不是终态)、一条已关闭(终态,下一步不该进)、一条开着但没写下一步
    o = lambda i, cid, st, nx: (i, cid, "沟通发现", "TS-1", st, None, nx, None, None, None, "S01", None, None,
                                "2026-10-01", "2026-10-01")
    x("INSERT INTO opportunity(id,customer_id,source,call_id,status,budget,next_step,close_reason,"
      "wait_for,scheme_id,advisor_no,confirmed_by,confirmed_at,created,updated) VALUES(" + ",".join("?" * 15) + ")", [
        o("OP-A", "CX1", "跟进中", "约她来店看面料"),
        o("OP-B", "CX1", "搁置等供给", "等红色云锦到货再联系"),
        o("OP-C", "CX1", "已关闭", "【不该出现】已关闭商机的下一步"),
        o("OP-D", "CX1", "跟进中", ""),
        o("OP-X", "CX2", "跟进中", "【不该出现】别的客户的商机"),
    ])
    x("INSERT INTO opportunity_need(opp_id,dim,val,quote,call_id) VALUES(?,?,?,?,?)", [
        ("OP-A", "颜色", "红", "我想要那种正红的,喜庆一点", "TS-1"),
        ("OP-X", "颜色", "蓝", "【不该出现】别的客户的原话", "TS-9")])
    # 日程:编号顺序和到期顺序故意反着(SC09 最早,SC01 最晚)
    s = lambda i, cid, st, t0, t1, note, typ="电话回电": (i, typ, "S01", cid, t0, t1, st, None, None, "一店", "S01",
                                                       None, None, note, None, None, None, None, None)
    x("INSERT INTO schedule(id,type,advisor_no,customer_id,start_ts,end_ts,status,summary,"
      "cancel_reason,shop,assignee_no,assigned_by,assigned_at,note,activity_code,ref_id,reassigned_from,"
      "reassign_reason,reassigned_at) VALUES(" + ",".join("?" * 19) + ")", [
        s("SC01", "CX1", "有效", "2026-11-20 10:00", "2026-11-20 11:00", "回访量体结果"),
        s("SC05", "CX1", "有效", "2026-10-10 10:00", None, "确认取件时间"),        # 没有结束时间 → 用开始时间
        s("SC09", "CX1", "有效", "2026-09-01 09:00", "2026-09-01 10:00", "电话确认尺码"),
        s("SC02", "CX1", "完结", "2026-08-01 09:00", "2026-08-01 10:00", "【不该出现】完结的日程"),
        s("SC03", "CX1", "已完成", "2026-08-02 09:00", "2026-08-02 10:00", "【不该出现】已完成的到店"),
        s("SC04", "CX1", "取消", "2026-08-03 09:00", "2026-08-03 10:00", "【不该出现】取消的日程"),
        s("SC07", "CX1", "有效", "2026-10-30 09:00", "2026-10-30 18:00", "上新对上了,联系她看看", "商机提醒"),
        s("SC08", "CX1", "完结", "2026-10-02 09:00", "2026-10-02 18:00", "【不该出现】完结的商机任务", "商机提醒"),
        s("SC99", "CX2", "有效", "2026-09-01 09:00", "2026-09-01 10:00", "【不该出现】别的客户的日程"),
    ])
    x("INSERT INTO opportunity_task(schedule_id,opp_id,kind,detail,created,answer,answered_by,answered_at) VALUES(?,?,?,?,?,?,?,?)", [
        ("SC07", "OP-B", "回捞", None, "2026-10-20", None, None, None),
        ("SC08", "OP-A", "回捞", None, "2026-10-01", "已联系", "S01", "2026-10-02")])
    x("INSERT INTO scheme(id,customer_id,name,status,xz,mt,kf,color,ps,pattern,advisor_no,note,"
      "created,updated,opportunity_id) VALUES(" + ",".join("?" * 15) + ")", [
        ("FA1", "CX1", "红马面", "已锁定", "XZ01", "MT01", "KF01", "红", "云肩", "PT01", "S01", None,
         "2026-10-05", "2026-10-06", "OP-A"),
        ("FA9", "CX2", "【不该出现】别人的方案", "草稿", None, None, None, None, None, None, "S02", None,
         "2026-10-05", "2026-10-05", None)])
    x("INSERT INTO ordr(id,customer_id,status,amount,created,scheme_id) VALUES(?,?,?,?,?,?)", [("O1", "CX1", "待生产", 3200, "2026-10-07", "FA1"),
                                              ("O2", "CX1", "已完成", 800, "2026-09-01", None),
                                              ("O9", "CX2", "待生产", 999, "2026-10-07", "FA9")])
    x("INSERT INTO cust_owner_log(customer_id,frm,too,action,basis,actor,ts) VALUES(?,?,?,?,?,?,?)",
      [("CX2", "S01", "S02", "转移", "顾问离职", "店长", "2026-09-01")])
    x("INSERT INTO followup(id,customer_id,ts,content) VALUES(?,?,?,?)", [("F1", "CX1", "2026-10-06", 承诺原话)])
    return c


print("客户业务摘要 · 检查(在自造形状上真调 customer_summary.摘要)")
print("=" * 80)
c = 造库()
s = CS.摘要(c, "CX1", "2026-10-23")
步 = s["下一步"]
关联 = [x["关联"] for x in 步]
文 = json.dumps(s, ensure_ascii=False)

print(f"  样本:下一步 {len(步)} 条 · 需求原话 {len(s['需求原话'])} 条 · 方案 {len(s['方案'])} 个")
ck("样本量够(自造的 6 条下一步都在)—— 不够就是没验到,不算通过", 判定(步) == "有样本" and len(步) == 6, 关联)

# ── 三个来源 ──
来 = {x["来源"] for x in 步}
ck("三个来源都进来(商机的下一步 / 日程 / 商机任务)", 来 == set(CS.来源), sorted(来))
ck("每条都标了来源,而且是三种之一", all(x.get("来源") in CS.来源 for x in 步), 步)
ck("商机的下一步:开着的和搁置的都进(OP-A / OP-B),没写下一步的不进(OP-D)",
   sorted(x["关联"] for x in 步 if x["来源"] == "商机的下一步") == ["OP-A", "OP-B"], 关联)
ck("商机任务只列一次:SC07 只以「商机任务」出现,不在「日程」里再列",
   [x["来源"] for x in 步 if x["关联"] == "SC07"] == ["商机任务"], [(x["来源"], x["关联"]) for x in 步])

# ── 按到期排 ──
有期 = [x["到期"] for x in 步 if x["到期"]]
ck("按到期排:有到期日的升序,没到期日的排在最后",
   有期 == sorted(有期) and [x["到期"] is None for x in 步] == sorted(x["到期"] is None for x in 步)
   and 关联[:4] == ["SC09", "SC05", "SC07", "SC01"], [(x["关联"], x["到期"]) for x in 步])
ck("日程没有结束时间时,到期取开始时间(SC05)",
   next(x["到期"] for x in 步 if x["关联"] == "SC05") == "2026-10-10 10:00")
ck("已过到期日按传进来的「今天」标(SC09、SC05 过了,SC01 没过)",
   {x["关联"]: x["已过到期日"] for x in 步 if x["关联"] in ("SC09", "SC05", "SC01")}
   == {"SC09": True, "SC05": True, "SC01": False}, [(x["关联"], x["已过到期日"]) for x in 步])

# ── 已完成的不进 ──
ck("已完成的不进:完结 / 已完成 / 取消的日程", not ({"SC02", "SC03", "SC04"} & set(关联)), 关联)
ck("已完成的不进:完结的商机任务", "SC08" not in 关联, 关联)
ck("已完成的不进:已关闭商机的下一步", "OP-C" not in 关联, 关联)
ck("别的客户的东西一样都不进(商机 / 日程 / 原话 / 方案)", "不该出现" not in 文,
   [x for x in 文.split('"') if "不该出现" in x])

# ── 承诺栏 ──
承 = s["承诺"]
ck("承诺栏不编造:跟进里写了「答应……」,承诺栏仍是没有结构化记录、条目为空、那句话不进摘要",
   承.get("有结构化记录") is False and 承.get("条目") == [] and "没有结构化记录" in (承.get("说明") or "")
   and 承诺原话 not in 文 and "绣样照片" not in 文, 承)

# ── 负责人 ──
p = s["负责人"]
ck("负责人取档案上的顾问,名字按工号现取", p["工号"] == "S01" and p["名字"] == "林岚", p)
ck("没有换手记录就明说查不到,不推", p["换手记录"] == [] and "查不到" in p["换手说明"], p)
p2 = CS.摘要(c, "CX2")["负责人"]
ck("有换手记录就列出来", len(p2["换手记录"]) == 1 and "1 条" in p2["换手说明"], p2)

# ── 需求原话 / 方案和订单 ──
ck("需求原话逐字带出来,带上商机和通话", s["需求原话"] == [dict(商机="OP-A", 商机状态="跟进中", 维度="颜色", 值="红",
                                            原话="我想要那种正红的,喜庆一点", 通话="TS-1")], s["需求原话"])
fa = s["方案"][0] if s["方案"] else {}
ck("方案按方案号连上订单(O1 进,没挂方案的 O2 不挂在方案下),编码翻成中文",
   len(s["方案"]) == 1 and [o["id"] for o in fa.get("订单", [])] == ["O1"] and fa.get("形制") == "马面裙"
   and fa.get("来自商机") == "OP-A", fa)

# ── 边界 ──
ck("客户不存在 → None(不是一张空摘要)", CS.摘要(c, "CX-无") is None)
空 = CS.摘要(c, "CX3")
ck("样本量为 0 时报「没东西可验」,而不是绿(一位什么都没有的客户)",
   空 is not None and 空["下一步"] == [] and 判定(空["下一步"]) == "没东西可验", 空 and 空["下一步"])

# ── 接上了:详情接口带出来、页面用它(任挑一位客户就行 —— 这里验的是接线,不是数据)──
_库 = os.path.join(HERE, "lanxiu.db")
_r = sqlite3.connect(_库).execute("SELECT id FROM customer ORDER BY id LIMIT 1").fetchone() if os.path.exists(_库) else None
if not _r:
    ck("库里至少有一位客户,好验详情接口的接线 —— 没有就没验,不算通过", False)
else:
    import server as SV
    _d = SV.customer_detail(_r[0])
    _z = _d.get("业务摘要") or {}
    ck("客户详情接口带上业务摘要(承诺栏是「没有结构化记录」)",
       _z.get("客户") == _r[0] and (_z.get("承诺") or {}).get("有结构化记录") is False, list(_d.keys()))
页 = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
ck("页面客户详情顶部渲染业务摘要卡", "${bizSummaryCard(d.业务摘要)}" in 页 and "function bizSummaryCard(" in 页)

print()
if 坏:
    print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 客户业务摘要:三个来源都列、标来源、按到期排、完成的不进、承诺不编造(验了 {n} 条){D}")
