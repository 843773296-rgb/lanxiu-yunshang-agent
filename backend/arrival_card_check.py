#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上新待办卡片(用户 2026-10-10)—— 在库的**临时副本**上跑,真库一行不碰。

验:谁看得到哪几张(顾问 = 指派给自己的、店长 = 本店、别的顾问 0 张)· 电话地址打码 · 30 天窗口的两边 ·
任务做完卡片照弹(用户定:暂时不消失)· 看完整号码给真号、留痕、越权被拒 · 建议写一次不重写、
模型答歪退回规则模板并照实标 · 上新正门真的会绑商机、派提醒、写建议。
期望值一律从副本里**独立 SQL** 现读,不调被测函数算期望(同源谬误)。
"""
import datetime as dt, json, os, re, shutil, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]
import api, arrival_card as AC, oplog

咬合 = [
    ("别的顾问也能看到不是派给自己的卡片", "别的顾问一张都看不到"),
    ("卡片上直接给完整手机号", "卡片上的电话打码、地址里没有门牌数字"),
    ("看完整号码不记台账", "看完整号码:记了一笔台账"),
    ("任务做完卡片就不弹了(用户要的是暂时不消失)", "任务做完了卡片照弹"),
    ("模型答歪了也照收", "模型答歪 → 退回规则模板,来源照实标「规则」"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


print("上新待办卡片 · 库副本上走一遍")
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(api.DB, db)
oplog.DB = db
c = sqlite3.connect(db)

# 期望值:独立 SQL。回捞提醒 = opportunity_task.kind 回捞 / 偏好回捞,挂着 opportunity_recall
行 = c.execute("SELECT s.id, s.assignee_no, s.shop, r.created, r.customer_id FROM opportunity_task ot "
               "JOIN schedule s ON s.id=ot.schedule_id JOIN opportunity_recall r ON r.opp_id=ot.opp_id "
               "AND r.spu=json_extract(ot.detail,'$.新品') WHERE ot.kind IN ('回捞','偏好回捞')").fetchall()
ck("有回捞提醒样本(空集合上什么都成立)", len(行) > 0, "opportunity_recall 是空的 —— 先跑 tools/backfill_opportunity.py")
今天 = max(dt.date.fromisoformat(r[3][:10]) for r in 行) if 行 else dt.date.today()
顾问们 = {}
for sid, 派, 店, *_ in 行:
    if 派:
        顾问们.setdefault(派, set()).add(sid)
某顾问, 他的 = next(iter(顾问们.items())) if 顾问们 else (None, set())
店 = next(r[2] for r in 行 if r[1] == 某顾问) if 某顾问 else None
别人 = c.execute("SELECT no FROM staff WHERE role='顾问' AND no NOT IN (%s) LIMIT 1" %
                 ",".join("?" * len(顾问们)), list(顾问们)).fetchone()[0] if 顾问们 else None

顾 = AC.卡片(dict(no=某顾问, name="顾问", role="顾问", shop=店), db=db, 今天=今天)
ck("顾问看到的就是指派给自己的那几张", {k["任务号"] for k in 顾["卡片"]} == 他的, f"{[k['任务号'] for k in 顾['卡片']]} / 应为 {他的}")
ck("别的顾问一张都看不到", AC.卡片(dict(no=别人, name="别人", role="顾问", shop=店), db=db, 今天=今天)["张数"] == 0)
长 = AC.卡片(dict(no="SM-X", name="店长", role="店长", shop=店), db=db, 今天=今天)
ck("店长看到本店的全部", {k["任务号"] for k in 长["卡片"]} == {r[0] for r in 行 if r[2] == 店})

k0 = 顾["卡片"][0] if 顾["卡片"] else {}
真 = c.execute("SELECT phone, addr FROM customer WHERE id=?", ((k0.get("顾客") or {}).get("客户号"),)).fetchone() or ("", "")
ck("卡片上的电话打码、地址里没有门牌数字",
   bool(k0) and k0["顾客"]["电话"] != 真[0] and "****" in k0["顾客"]["电话"] and not re.search(r"\d", k0["顾客"]["地址"]),
   str(k0.get("顾客")))
ck("卡片带齐:留言(原话)、建议、新款(名称 / 价格 / 颜色 / 尺码 / 图)",
   bool(k0) and k0["留言"]["当初原话"] and "正文" in k0["建议"]
   and all(k0["新款"].get(x) not in (None, "") for x in ("名称", "价格", "图")) and isinstance(k0["新款"].get("颜色"), list))

# 30 天窗口的两边 —— 期望常数从用户原话手抄(「上新后 30 天内」),不读被测模块
绑 = dt.date.fromisoformat(next(r[3] for r in 行 if r[0] in 他的)[:10]) if 他的 else 今天
me = dict(no=某顾问, name="顾问", role="顾问", shop=店)
在 = {k["任务号"] for k in AC.卡片(me, db=db, 今天=绑 + dt.timedelta(days=29))["卡片"]}
外 = {k["任务号"] for k in AC.卡片(me, db=db, 今天=绑 + dt.timedelta(days=30))["卡片"]}
ck("上新第 30 天还弹", bool(在 & 他的), str(在))
ck("上新第 31 天不弹了", not (外 & {r[0] for r in 行 if r[3][:10] == 绑.isoformat()}), str(外))

# 任务做完照弹(用户:暂时不消失,面试要展示)
c.execute("UPDATE schedule SET status='完成' WHERE id=?", (k0.get("任务号"),)); c.commit()
ck("任务做完了卡片照弹", k0.get("任务号") in {k["任务号"] for k in AC.卡片(me, db=db, 今天=今天)["卡片"]})

# 看完整号码
前 = c.execute("SELECT COUNT(*) FROM op_log WHERE code='REVEAL_CONTACT'").fetchone()[0]
全 = AC.看完整联系方式(me, k0.get("任务号"), db=db, 今天=今天)
ck("看完整号码:给的是库里的真号和真地址", 全.get("电话") == 真[0] and 全.get("地址") == 真[1], str(全)[:100])
后 = c.execute("SELECT COUNT(*), MAX(actor) FROM op_log WHERE code='REVEAL_CONTACT'").fetchone()
ck("看完整号码:记了一笔台账", 后[0] == 前 + 1 and 后[1] == 某顾问, f"{前} → {后}")
拒 = AC.看完整联系方式(dict(no=别人, name="别人", role="顾问", shop=店), k0.get("任务号"), db=db, 今天=今天)
ck("别的顾问点看完整号码 → 拒,且拒绝也留痕", "电话" not in 拒 and
   c.execute("SELECT COUNT(*) FROM op_log WHERE code='REVEAL_CONTACT' AND allowed=0 AND actor=?", (别人,)).fetchone()[0] == 1)

# 建议:写一次、不重写;模型答歪退回规则
oid, spu = c.execute("SELECT opp_id, spu FROM opportunity_recall LIMIT 1").fetchone()
c.execute("DELETE FROM recall_advice"); c.commit()
歪 = AC.写建议(c, oid, spu, call=lambda 材料: {"content": [{"type": "text", "text": "好"}]}); c.commit()
ck("模型答歪 → 退回规则模板,来源照实标「规则」", 歪[1] == "规则" and "1." in (歪[0] or ""), str(歪))
再 = AC.写建议(c, oid, spu, call=lambda 材料: {"content": [{"type": "text", "text": "1. 甲甲甲甲甲甲甲甲甲甲\n2. 乙乙乙乙乙乙乙乙乙\n3. 丙丙丙"}]})
ck("建议写过一次就不重写(绑定那一刻写一次)", 再 == 歪, str(再))
材 = []
c.execute("DELETE FROM recall_advice"); c.commit()
好 = AC.写建议(c, oid, spu, call=lambda 材料: (材.append(材料), {"content": [{"type": "text",
           "text": "1. 先提她当初说的话,告诉她上了新款\n2. 推一个她提过的颜色\n3. 先问还需不需要"}]})[1]); c.commit()
ck("模型答对形状 → 收下,来源「模型」", 好[1] == "模型", str(好))
姓名 = c.execute("SELECT name FROM customer WHERE id=(SELECT customer_id FROM opportunity_recall WHERE opp_id=? LIMIT 1)",
                 (oid,)).fetchone()[0]
ck("发给模型的材料里没有客户全名和电话", bool(材) and 姓名 not in 材[0] and not re.search(r"1[3-9]\d{9}", 材[0]), 材[0][:120] if 材 else "")

# 上新正门:挂上架 → 回捞 → 派提醒 → 写建议(90 天冷却之后,让一条搁置商机再被同一款唤醒一次)
oid2, spu2, 绑2 = c.execute("SELECT opp_id, spu, created FROM opportunity_recall r WHERE EXISTS "
                           "(SELECT 1 FROM opportunity o WHERE o.id=r.opp_id AND o.status='搁置等供给') LIMIT 1").fetchone()
以后 = dt.date.fromisoformat(绑2[:10]) + dt.timedelta(days=95)
c.execute("UPDATE product SET status='下架' WHERE spu=?", (spu2,)); c.commit()
出 = AC.上新([spu2], 今天=以后, db=db, call=lambda 材料: {"content": [{"type": "text", "text": "x"}]})
c2 = sqlite3.connect(db)
ck("上新正门:挂上架、上架日是上新那天", c2.execute("SELECT status, on_shelf_at FROM product WHERE spu=?", (spu2,)).fetchone()
   == ("上架", 以后.isoformat()))
ck("上新正门:绑上了等它的商机、派了提醒", any(x["商机"] == oid2 for x in 出["绑上"]) and c2.execute(
   "SELECT COUNT(*) FROM opportunity_recall WHERE opp_id=? AND created=?", (oid2, 以后.isoformat())).fetchone()[0] == 1, str(出)[:120])
ck("上新正门:每条新绑定都写了建议", c2.execute(
   "SELECT COUNT(*) FROM opportunity_recall r LEFT JOIN recall_advice a ON a.opp_id=r.opp_id AND a.spu=r.spu "
   "WHERE a.opp_id IS NULL").fetchone()[0] == 0)
# 已经上架的再传一次:上架日不许被改写成今天(数据工厂 10-10 提醒),并原样告诉调用方
老 = c2.execute("SELECT spu, on_shelf_at FROM product WHERE status='上架' AND spu<>? AND on_shelf_at IS NOT NULL LIMIT 1",
                (spu2,)).fetchone()
再 = AC.上新([老[0]], 今天=以后 + dt.timedelta(days=1), db=db, call=lambda 材料: {"content": []})
ck("已经上架的老款再上一次:上架日不变,并报「本来就在架」",
   c2.execute("SELECT on_shelf_at FROM product WHERE spu=?", (老[0],)).fetchone()[0] == 老[1]
   and 再["本来就在架"] == [老[0]] and 再["上了"] == [], str(再)[:120])
c2.close()

# 页面和口子
src = open(os.path.join(ROOT, "agentsite", "web", "station.html"), encoding="utf-8").read()
srv = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
ck("对话页登录后就取卡片", "loadMe().then(loadArrival)" in src and '"/api/arrival-cards"' in src)
ck("卡片能手动关(用户:暂时不消失,手动关)", '#arrival .x' in src and '$("#arrival").hidden = true' in src)
ck("后台口子在:取卡片 / 看完整号码", '"/api/arrival-cards"' in srv and '"/api/reveal-contact"' in srv)

c.close()
shutil.rmtree(tmp, ignore_errors=True)
print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 上新待办卡片都对(验了 {n} 条){D}")
