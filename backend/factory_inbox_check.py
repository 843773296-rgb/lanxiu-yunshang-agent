#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工厂回传接收写口的检查 —— 在库的**临时副本**上跑,真库一行都不碰(同 order_write_check)。

钉的几件事:
    活写口   拿一张工厂还没回过任何消息的生产中订单,亲手按乱序、缺单号、重发的顺序喂回传,
             看它暂存、放行、拒收、只记一次;生产 / 发货时间记的是工厂报的时间
    闸       后台直接把定制单「生产中→已生产」→ 被状态机拦下(FACTORY_GATE),只认回传
    该催     工厂没回接单的单在该催清单里;回了就出来
    数据     过了生产的定制单,每一步都有收下的回传撑着;模拟工厂那一批每条都和它记的预期对得上
    不外露   模拟工厂那一侧的表(相当于答案)不出现在任何工具 / 接口代码里
"""
import os, sys, shutil, sqlite3, tempfile, glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

咬合 = [
    ("把订单状态机上的工厂回传闸去掉(生产中→已生产不再看有没有回传)", "后台直接改「生产中→已生产」被拦(只认工厂回传)"),
    ("让接收写口不再回头放行暂存的回传", "完工到了 → 暂存的质检通过被放行,订单到待发货"),
    ("生产时间记成收到消息的时间,不记工厂报的时间", "生产时间记的是工厂报的时间"),
    ("接收写口不再把接单方传给口径", "接单的是检查厂,别家报完工 → 挂异常,订单不动"),
    ("查订单只给回传记录,不给算好的进度", "查订单带出按今天算好的「离承诺完工日已经过了几天」"),
]

FAIL, N = [], [0]
今天 = "2026-08-31"


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:140]) if extra else ''}")
    if not ok: FAIL.append(name)


def main():
    print("工厂回传接收写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    数据(os.path.join(HERE, "lanxiu.db"))
    tmp = tempfile.mkdtemp(prefix="fact-")
    T = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.path.join(HERE, "lanxiu.db"), T)
    try:
        活写口(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    不外露()
    print()
    if FAIL:
        print(f"\033[31m❌ 工厂回传 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 工厂回传 {N[0]} 条全过\033[0m —— 只认回传、乱序能放行、重发只记一次、该催的都在")


def 数据(D):
    c = sqlite3.connect(D)
    # 过了生产的定制单,每一步都有收下的回传撑着(状态在哪一档 → 要有哪几步)
    要 = {"已生产": ("完工",), "待发货": ("完工", "质检通过"), "已发货": ("完工", "质检通过", "发出"),
         "待完成": ("完工", "质检通过", "发出"), "完成": ("完工", "质检通过", "发出")}
    n = 缺 = 0; 例 = []
    for oid, st in c.execute("SELECT id, status FROM ordr WHERE kind='定制品订单' AND status IN "
                             "('已生产','待发货','已发货','待完成','完成')"):
        n += 1
        有 = {r[0] for r in c.execute("SELECT event FROM factory_msg WHERE order_id=? AND result='收下'", (oid,))}
        少 = [e for e in 要[st] if e not in 有]
        if 少:
            缺 += 1
            if len(例) < 3: 例.append((oid[-6:], st, 少))
    ck("过了生产的定制单,每一步都有收下的工厂回传撑着", n > 0 and not 缺, f"验了 {n} 张;缺的 {缺} 张 {例}")
    无号 = c.execute("SELECT COUNT(*) FROM factory_msg WHERE event='发出' AND result='收下' "
                    "AND COALESCE(tracking_no,'')=''").fetchone()[0]
    ck("收下的发出回传都带物流单号", 无号 == 0, 无号)
    tot, bad = c.execute("SELECT COUNT(*), SUM(CASE WHEN expect NOT LIKE '%→%' AND expect!='该催' "
                         "AND got!=expect THEN 1 ELSE 0 END) FROM factory_outbox").fetchone()
    ck("模拟工厂那一批每条都和它记的预期对得上", tot and not bad, f"{tot} 条,对不上 {bad or 0}")
    毛病 = {r[0] for r in c.execute("SELECT DISTINCT flaw FROM factory_outbox WHERE flaw!=''")}
    少 = {"重复发", "换号重发", "乱序:质检先到", "发出没单号", "未来时间", "时间倒挂", "查无此单", "已取消的单", "别家报完工", "车间在制却报完工"} - 毛病
    ck("十种毛病每种都有样本(没样本那一支等于没测)", not 少, 少 or "")
    # 查订单带出按演示世界今天算好的进度 —— 09-22 评测:原来只给记录,模型拿机器日期算成「过期一个月」(实际 3 天)
    import api
    过 = c.execute("SELECT order_id, promise_date FROM factory_msg WHERE event='接单' AND result='收下' "
                  "AND promise_date < ? AND order_id IN (SELECT id FROM ordr WHERE status='生产中') LIMIT 1",
                  (今天,)).fetchone()
    if 过:
        import datetime as _d
        差 = (_d.date.fromisoformat(今天) - _d.date.fromisoformat(过[1][:10])).days
        进 = (api.get_order(过[0]).get("工厂回传") or {}).get("进度") or {}
        ck("查订单带出按今天算好的「离承诺完工日已经过了几天」", 进.get("离承诺完工日") == f"已经过了 {差} 天", 进)
    c.close()


def 活写口(T):
    import factory_inbox as fi, server, oplog
    for m in (fi, server, oplog): m.DB = T
    c = sqlite3.connect(T)
    # 按性质挑:一张工厂还没回过任何消息、开工超过 3 天的生产中定制单
    r = c.execute("""SELECT o.id, COALESCE(o.cut_at, o.audit_at) FROM ordr o
                     WHERE o.kind='定制品订单' AND o.status='生产中'
                       AND NOT EXISTS(SELECT 1 FROM factory_msg f WHERE f.order_id=o.id)
                       AND julianday(?) - julianday(COALESCE(o.cut_at, o.audit_at)) > 5
                     ORDER BY o.id LIMIT 1""", (今天,)).fetchone()
    ck("有一张工厂还没回过消息的生产中定制单", bool(r))
    if not r: return
    oid, 开 = r
    别 = c.execute("""SELECT o.id FROM ordr o WHERE o.kind='定制品订单' AND o.status='生产中' AND o.id!=?
                      AND NOT EXISTS(SELECT 1 FROM factory_msg f WHERE f.order_id=o.id AND f.result='收下'
                                     AND f.event='完工') ORDER BY o.id LIMIT 1""", (oid,)).fetchone()
    ck("没回接单、开工超过 3 天 → 在该催清单里", oid in {x["订单"] for x in fi.该催清单(今天)})
    if 别:
        x = server.transit("bk-order", 别[0], "已生产", {"by": "检查"}, actor="检查")
        ck("后台直接改「生产中→已生产」被拦(只认工厂回传)", x.get("code") == "FACTORY_GATE", x.get("reason"))

    M = lambda 号, 事, t, **k: dict(消息号=号, 订单号=oid, 事件=事, 时间=t, 工厂="检查厂", **k)
    ck("接单 → 收下,订单不动", fi.收(M("C1", "接单", "2026-08-20 09:00", 承诺完工日="2026-09-20"), 今天)["结论"] == "收下"
       and c.execute("SELECT status FROM ordr WHERE id=?", (oid,)).fetchone()[0] == "生产中")
    ck("回了接单、没过承诺日 → 不在该催清单里", oid not in {x["订单"] for x in fi.该催清单(今天)})
    # 谁接的单谁报(自有工坊和外发工厂都有,业务 09-22)
    ck("接单的是检查厂,别家报完工 → 挂异常,订单不动",
       fi.收(dict(M("Cx", "完工", "2026-08-27 10:00"), 工厂="别家厂"), 今天)["结论"] == "挂异常"
       and c.execute("SELECT status FROM ordr WHERE id=?", (oid,)).fetchone()[0] == "生产中")
    ck("质检通过比完工先到 → 暂存", fi.收(M("C2", "质检通过", "2026-08-29 10:00"), 今天)["结论"] == "暂存")
    ck("完工早于开工 → 拒收(时间倒挂)",
       fi.收(M("C0", "完工", "2020-01-01 10:00"), 今天)["结论"] == "拒收")
    r = fi.收(M("C3", "完工", "2026-08-28 15:00"), 今天)
    st = c.execute("SELECT status, produced_at FROM ordr WHERE id=?", (oid,)).fetchone()
    ck("完工到了 → 暂存的质检通过被放行,订单到待发货", r["结论"] == "收下" and st[0] == "待发货", st)
    ck("生产时间记的是工厂报的时间", str(st[1]).startswith("2026-08-28 15:00"), st[1])
    ck("同一个消息号再发 → 重复", fi.收(M("C3", "完工", "2026-08-28 15:00"), 今天)["结论"] == "重复")
    ck("同一步换个号再发 → 重复", fi.收(M("C3b", "完工", "2026-08-28 15:00"), 今天)["结论"] == "重复")
    ck("发出没带物流单号 → 拒收", fi.收(M("C4", "发出", "2026-08-30 10:00"), 今天)["结论"] == "拒收")
    ck("发出时间晚于今天 → 拒收", fi.收(M("C5", "发出", "2026-09-05 10:00", 物流单号="SF1"), 今天)["结论"] == "拒收")
    r = fi.收(M("C6", "发出", "2026-08-30 10:00", 物流单号="SF123"), 今天)
    st = c.execute("SELECT status, shipped_at FROM ordr WHERE id=?", (oid,)).fetchone()
    ck("发出带物流单号 → 订单到已发货,发货时间是工厂报的", r["结论"] == "收下" and st[0] == "已发货"
       and str(st[1]).startswith("2026-08-30 10:00"), st)
    ck("收件箱每条都留底(拒收的也在)",
       c.execute("SELECT COUNT(*) FROM factory_msg WHERE order_id=?", (oid,)).fetchone()[0] == 9)
    c.close()


def 不外露():
    # 模拟工厂那一侧的表相当于答案 —— 和 truth 表同一条规矩
    碰 = [p for p in glob.glob(os.path.join(ROOT, "backend", "*.py")) + glob.glob(os.path.join(ROOT, "mcp", "*.py"))
          + glob.glob(os.path.join(ROOT, "agentsite", "*.py"))
          if not p.endswith("_check.py") and "factory_outbox" in open(p, encoding="utf-8").read()]
    ck("模拟工厂的预期表不出现在任何工具 / 接口代码里", not 碰, [os.path.basename(p) for p in 碰])


if __name__ == "__main__":
    main()
