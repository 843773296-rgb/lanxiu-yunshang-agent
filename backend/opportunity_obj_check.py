#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商机对象 · 检查 —— intent `opportunity-and-call-notes` 判据 ①⑤⑥⑦ 里不调模型的那几条。

`opportunity_check.py` 量的是「判断器认商机认得准不准」;这里查**认出来之后**:

    ① 沟通发现的商机指得回触发它的那次通话(通话真的在库里)
    ② 商机 ↔ 方案互相指得回(和「转过单的方案必须指得回订单」同一个形状)
    ③ 方案草稿必须挂一件具体服饰;商机可以没有(业务否掉了「商机 = 草稿方案」)
    ④ 两种终态分得开:已关闭写了为什么、不带等什么;搁置写了等什么(结构化);**已关闭不许被唤醒**
    ⑤ 每条诉求的原话真的在那通电话的逐字稿里 —— 指不回原话的诉求和瞎猜没区别
    样本量:商机少于 10 条时报「没扫到东西」,不报通过(10 是拍脑袋的,只为不让空表冒充通过)
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]

咬合 = [
    ("口径的诉求维度里删掉「配饰」", "诉求维度 = 业务 D3 定的那 12 个"),
    ("把一条商机触发它的通话号改成库里没有的", "沟通发现的商机都指得回触发它的那次通话"),
    ("把方案那头指回商机的字段清掉", "商机和方案互相指得回"),
    ("把「已关闭」和「搁置等供给」合并成一个「已丢单」", "状态都在口径里"),
    ("把一条诉求的原话换成逐字稿里没有的一句", "每条诉求的原话都在那通电话的逐字稿里"),
    ("让口径允许已关闭的商机被唤醒", "已关闭的商机不许被唤醒"),
    ("往回捞池里塞一条指向已关闭商机的提醒", "回捞出来的都是「搁置等供给」"),
    ("把一条回捞提醒「对上了」的颜色改成新品没有的", "回捞的新品真的满足它等的东西"),
    ("同一客户同一天再推一条", "天内只推一次"),
    ("让回捞不看冷却期", "合成场景:30 天前刚推过的客户不再推"),
    ("让回捞不设单次上限", "合成场景:一次最多唤醒 50 条"),
]
样本下限 = 10
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 闸自测(库):
    """**四个闸在真数据上没被触发过**(只有几条提醒,没有过期的、没有刚推过的、不到 50 条)——
    「没违反」证明不了「会拦」。在库的副本里造一个会触发全部四个闸的场景,跑一次回捞看它拦没拦。"""
    import shutil, tempfile, datetime as _dt, opportunity_store as S, oppo_obj as K
    t = os.path.join(tempfile.mkdtemp(), "t.db"); shutil.copy(库, t)
    c = sqlite3.connect(t)
    今 = _dt.date(2026, 10, 3)                       # 合成场景自己的「今天」,和库、和世界日期无关
    spu = c.execute("SELECT spu FROM product_custom WHERE xz LIKE '%马面裙%' ORDER BY spu LIMIT 1").fetchone()[0]
    c.execute("DELETE FROM opportunity_recall")
    def 造(oid, 客户, 状态, 日):
        c.execute("INSERT INTO opportunity(id, customer_id, source, call_id, status, wait_for, created, updated)"
                  " VALUES(?,?,?,?,?,?,?,?)", (oid, 客户, "沟通发现", "TS-001", 状态, '{"形制": "马面裙"}', 日, 日))
        c.execute("INSERT INTO opportunity_need(opp_id, dim, val, quote, call_id) VALUES(?,?,?,?,?)",
                  (oid, "形制", "马面裙", "想看看马面裙", "TS-001"))
    for i in range(60):
        造(f"Z{i:02d}", f"ZC{i:02d}", "搁置等供给", (今 - _dt.timedelta(days=i)).isoformat())
    造("Z-旧", "ZC-旧", "搁置等供给", (今 - _dt.timedelta(days=400)).isoformat())
    造("Z-关", "ZC-关", "已关闭", 今.isoformat())
    c.execute("INSERT INTO opportunity_recall(opp_id, customer_id, spu, matched, quote, created) VALUES(?,?,?,?,?,?)",
              ("Z00", "ZC00", spu, "{}", "x", (今 - _dt.timedelta(days=30)).isoformat()))
    出 = S.回捞(c, [spu], 今)
    中 = {x["商机"] for x in 出}
    ck("合成场景:一次最多唤醒 50 条", len(出) <= K.回捞_单次上限, len(出), f"唤醒 {len(出)} 条")
    ck("合成场景:13 个月前的诉求不捞", "Z-旧" not in 中, 1)
    ck("合成场景:已关闭的不捞", "Z-关" not in 中, 1)
    ck("合成场景:30 天前刚推过的客户不再推", "Z00" not in 中, 1)
    ck("合成场景:超过上限时按诉求从新到旧取(最新的那条在里面)", "Z01" in 中, 1)
    c.close()


def main():
    import oppo_obj as K
    print("商机对象 · 检查")
    print("=" * 84)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row
    有表 = c.execute("SELECT 1 FROM sqlite_master WHERE name='opportunity'").fetchone()
    os_ = [dict(r) for r in c.execute("SELECT * FROM opportunity")] if 有表 else []
    if len(os_) < 样本下限:
        print(f"  ⚠️ **没扫到东西**:商机只有 {len(os_)} 条(下限 {样本下限})—— 下面几条不算通过")
        FAIL.append(f"商机样本不足 {样本下限} 条")

    通话 = {r[0]: r[1] for r in c.execute(
        "SELECT a.id, t.text FROM call_audio a JOIN call_transcript t ON t.audio_id=a.id")}
    沟 = [o for o in os_ if o["source"] == "沟通发现"]
    断 = [o["id"] for o in 沟 if o["call_id"] not in 通话]
    ck("沟通发现的商机都指得回触发它的那次通话", not 断, len(沟), f"共 {len(断)} 条指不回:{断[:3]}" if 断 else "")

    转 = [o for o in os_ if o["scheme_id"]]
    方 = {r["id"]: r["opportunity_id"] for r in c.execute("SELECT id, opportunity_id FROM scheme")}
    正 = [o["id"] for o in 转 if 方.get(o["scheme_id"]) != o["id"]]
    反 = [s for s, oid in 方.items() if oid and not any(o["id"] == oid and o["scheme_id"] == s for o in os_)]
    ck("商机和方案互相指得回", not 正 and not 反, len(转) + sum(1 for v in 方.values() if v),
       f"商机→方案断 {正[:3]};方案→商机断 {反[:3]}" if (正 or 反) else f"{len(转)} 对")
    错转 = [o["id"] for o in os_ if (o["status"] == "已转方案") != bool(o["scheme_id"])]
    ck("只有「已转方案」的商机挂着方案,而且它一定挂着", not 错转, len(os_), f"共 {len(错转)} 条:{错转[:3]}" if 错转 else "")

    草 = [dict(r) for r in c.execute("SELECT id, xz FROM scheme WHERE status='草稿'")]
    空草 = [s["id"] for s in 草 if not s["xz"]]
    ck("方案草稿都至少挂了一件具体服饰(形制)", not 空草, len(草), f"共 {len(空草)} 条没挂:{空草[:3]}" if 空草 else "")
    无服 = [o["id"] for o in os_ if not c.execute(
        "SELECT 1 FROM opportunity_need WHERE opp_id=? AND dim='形制'", (o["id"],)).fetchone()]
    print(f"  ℹ 没有任何服饰诉求的商机 {len(无服)} 条 —— **这是合法的**(商机可以只是「这个客户可能要买东西」)")

    野 = [f"{o['id']}:{o['status']}" for o in os_ if o["status"] not in K.状态]
    ck("状态都在口径里(已关闭和搁置等供给是两个,不许合并成一个)", not 野, len(os_), f"共 {len(野)} 条:{野[:3]}" if 野 else "")
    关 = [o for o in os_ if o["status"] == "已关闭"]
    搁 = [o for o in os_ if o["status"] == "搁置等供给"]
    坏关 = [o["id"] for o in 关 if not o["close_reason"] or o["wait_for"]]
    ck("已关闭的写了为什么,而且不带「等什么」", not 坏关, len(关), f"共 {len(坏关)} 条:{坏关[:3]}" if 坏关 else "")
    坏搁 = [o["id"] for o in 搁 if not K.搁置理由合格吗(json.loads(o["wait_for"] or "null"))[0]]
    ck("搁置等供给的都写清等什么(结构化,能拿去和上新匹配)", not 坏搁, len(搁), f"共 {len(坏搁)} 条:{坏搁[:3]}" if 坏搁 else "")
    ck("已关闭的商机不许被唤醒", not K.能转吗("已关闭", "跟进中")[0] and K.能转吗("搁置等供给", "跟进中")[0], 2)
    # 已关闭可以从「待确认」直接关(顾问不认这条商机),所以不要求它有点头时间;其余走出待确认的都要有
    未点头 = [o["id"] for o in os_ if o["status"] not in ("待确认", "已关闭") and not o["confirmed_at"]]
    ck("走出「待确认」的(除了直接关掉的)都有顾问点头的时间", not 未点头, len(os_), f"共 {len(未点头)} 条:{未点头[:3]}" if 未点头 else "")

    诉 = [dict(r) for r in c.execute("SELECT opp_id, dim, val, quote, call_id FROM opportunity_need")]
    假 = [f"{x['opp_id']}「{x['quote'][:12]}」" for x in 诉 if not x["quote"] or x["quote"] not in 通话.get(x["call_id"], "")]
    ck("每条诉求的原话都在那通电话的逐字稿里", not 假, len(诉), f"共 {len(假)} 条:{假[:3]}" if 假 else "")
    野维 = [f"{x['opp_id']}:{x['dim']}" for x in 诉 if x["dim"] not in K.诉求维度]
    ck("诉求的维度都是可匹配的维度", not 野维, len(诉), f"共 {len(野维)} 条:{野维[:3]}" if 野维 else "")
    # 期望值**从业务 D3 原文手抄**,不从口径模块读 —— 读口径模块就是拿被测的东西当尺子(同源谬误)。
    # 10-03 之前口径漏了工艺 / 配饰 / 版型,技能真跑时客户要「豆绿色云肩」无处可放
    D3 = {"形制", "面料", "工艺", "颜色", "配饰", "版型", "纹样", "场合", "预算", "工期", "尺码", "性别"}
    差 = (D3 - set(K.诉求维度), set(K.诉求维度) - D3)
    ck("诉求维度 = 业务 D3 定的那 12 个(一个不漏、一个不多)", not (差[0] or 差[1]), len(D3),
       (f"漏了 {sorted(差[0])}" if 差[0] else "") + (f" 多了 {sorted(差[1])}" if 差[1] else ""))

    # ── 回捞池(搁置等供给 × 上新,四个闸是业务 09-20 D6 定的)────────────────
    import datetime as _dt, opportunity_store as S
    d = lambda x: _dt.date.fromisoformat(str(x)[:10])
    回 = [dict(r) for r in c.execute("SELECT * FROM opportunity_recall")] if c.execute(
        "SELECT 1 FROM sqlite_master WHERE name='opportunity_recall'").fetchone() else []
    商 = {o["id"]: o for o in os_}
    非搁 = [f"{x['opp_id']}:{商.get(x['opp_id'], {}).get('status')}" for x in 回
            if 商.get(x["opp_id"], {}).get("status") != "搁置等供给"]
    ck("回捞出来的都是「搁置等供给」(已关闭的一条都不许碰)", not 非搁, len(回), f"共 {len(非搁)} 条:{非搁[:3]}" if 非搁 else "")
    不满足 = [f"{x['opp_id']}←{x['spu']}" for x in 回
              if not all(S.满足吗(c, x["spu"], k, v)[0] for k, v in json.loads(x["matched"]).items())]
    ck("回捞的新品真的满足它等的东西", not 不满足, len(回), f"共 {len(不满足)} 条:{不满足[:3]}" if 不满足 else "")
    假原 = [x["opp_id"] for x in 回 if x["quote"] not in 通话.get(商.get(x["opp_id"], {}).get("call_id"), "")]
    ck("每条回捞提醒都带当初那句原话,而且原话真在逐字稿里", not 假原, len(回), f"共 {len(假原)} 条:{假原[:3]}" if 假原 else "")
    超时 = [x["opp_id"] for x in 回 if x["opp_id"] in 商 and not K.在时效内(d(商[x["opp_id"]]["created"]), d(x["created"]))]
    ck(f"回捞的诉求都在 {K.回捞_时效月数} 个月内", not 超时, len(回), f"共 {len(超时)} 条:{超时[:3]}" if 超时 else "")
    按客 = {}
    for x in 回: 按客.setdefault(x["customer_id"], []).append(d(x["created"]))
    太勤 = [k for k, ds in 按客.items() if any((b - a).days < K.回捞_冷却天数 for a, b in zip(sorted(ds), sorted(ds)[1:]))]
    ck(f"同一客户 {K.回捞_冷却天数} 天内只推一次", not 太勤, len(按客), f"共 {len(太勤)} 个客户:{太勤[:3]}" if 太勤 else "")
    按日 = {}
    for x in 回: 按日[x["created"][:10]] = 按日.get(x["created"][:10], 0) + 1
    超量 = {k: v for k, v in 按日.items() if v > K.回捞_单次上限}
    ck(f"一次上新最多唤醒 {K.回捞_单次上限} 条", not 超量, len(按日), str(超量) if 超量 else "")

    闸自测(os.path.join(HERE, "lanxiu.db"))

    print()
    if FAIL:
        print(f"\033[31m❌ 商机对象 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 商机对象全部符合预期\033[0m({len(os_)} 条商机,{len(诉)} 条诉求)")


if __name__ == "__main__":
    main()
