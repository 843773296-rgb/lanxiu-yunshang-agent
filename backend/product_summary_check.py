#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品归纳总结 + 购买喜好推荐(用户 2026-10-10)—— 库的临时副本上跑,真库一行不碰。

验:归纳一批商品出得了规律、每条带说法、认不出的报在覆盖里 · 没规律时明说没有(件数不够 / 太分散两种)·
工具三种给法 + 给客户 · 上新时按购买规律推人:推的每一位**独立 SQL 复核**她真买过 ≥2 件那个颜色 ·
没营销同意 / 注销的不推 · 单次 ≤50 · 冷却(同一天再上一次不重复推)· 推断出的是「待确认」商机 ·
顾问答「想看 / 不要」商机走对 · 推断的绑定不混进「电话里说过的」那张表 · 卡片标得出「购买推断」。
"""
import datetime as dt, json, os, shutil, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]
import api, product_summary as PS, opportunity_store as S, arrival_card as AC, oplog, traits as T

咬合 = [
    ("没规律时编一条出来(把共性当规律)", "全是无纹样但在架本来就多 → 只进共性,不进规律"),
    ("推荐不看营销同意", "推的每一位都同意营销触达、账户没注销"),
    ("推断的绑定混进「电话里说过的」那张表", "推断的绑定不进 opportunity_recall(那张表只放电话里说过的)"),
    ("同一位客户 90 天内被推两次(冷却没合着算)", "冷却:5 天后再上新一次,推过的人不再推"),
    ("顾客的颜色按这款所有颜色算,不按她买的那件", "只买过蓝色那件(那款另有红色)的人,上新红色不推她"),
    ("购买推断不单独限量(一次推 50 人)", "推了人,而且单次不超过 5(用户 10-10:购买推断每次最多 5 人)"),
    ("自动收口把客户说过的提醒也收了", "客户亲口说过的那两种提醒不被收口"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


print("商品归纳总结 + 购买喜好推荐 · 库副本上走一遍")
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(api.DB, db)
api.DB = AC.DB = oplog.DB = db
c = sqlite3.connect(db)
S.建表(c); AC.建表(c); c.commit()
今 = dt.date(2026, 10, 10)

# ── 归纳一批商品 ──
云锦 = [r[0] for r in c.execute("SELECT spu FROM product WHERE name LIKE '%云锦%' ORDER BY spu LIMIT 5")]
r = PS.归纳商品(c, 云锦)
ck("名字里都带云锦的 5 款 → 面料「云锦」是规律,带现成的说法",
   any(x["维度"] == "面料" and x["值"] == "云锦" and "件里" in x["说法"] for x in r["规律"]), str(r["规律"])[:160])
ck("覆盖按「认得出几件 / 一共几件」报,和明细对得上",
   all(r["覆盖"][d] == f"{sum(1 for m in r['明细'] if m[d])}/{len(r['明细'])} 件认得出" for d in T.维度们), str(r["覆盖"]))
香 = PS.归纳商品(c, [x[0] for x in c.execute("SELECT spu FROM product WHERE name LIKE '%香云纱%' LIMIT 3")])["明细"]
认 = [[v.split("(")[0] for v in m["面料"]] for m in 香]
ck("「香云纱」不被认成「纱」", bool(香) and all("香云纱" in x and "纱" not in x for x in 认), str(认))
少 = PS.归纳商品(c, 云锦[:2])
ck("只给 2 款 → 明说没有发现规律(样本太少)", not 少["规律"] and "样本太少" in 少["结论"], 少["结论"])
# 太分散:挑一组五个维度两两都不同的款
表 = PS.属性表(c)
散, 用过 = [], {d: set() for d in T.维度们}
for spu, v in sorted(表.items()):
    值 = {d: {x for x, _ in v["属性"][d]} for d in T.维度们}
    if all(值[d] for d in ("颜色", "面料", "形制")) and all(not (值[d] & 用过[d]) for d in T.维度们):
        散.append(spu); [用过[d].update(值[d]) for d in T.维度们]
    if len(散) >= 5:
        break
r散 = PS.归纳商品(c, 散)
ck("五个维度两两不同的几款(至少 3 款,够数)→ 明说没有发现规律(太分散)", len(散) >= 3 and not r散["规律"] and "分散" in r散["结论"],
   f"{len(散)} 款 / {r散['结论']}")
基 = {"纹样": {"无纹样": .7}}
r共 = T.归纳([{"纹样": ["无纹样"]}] * 4, 基)
ck("全是无纹样但在架本来就多 → 只进共性,不进规律", not r共["规律"] and r共["共性"], str(r共))

# ── 工具 ──
with api.as_user(dict(no="60000001", name="店长", role="店长", shop="SH001 静安旗舰店")):
    t1 = api.summarize_products(keyword="马面裙", limit=10)
    t2 = api.summarize_products(spus=",".join(云锦))
    t3 = api.summarize_products()
    cust = c.execute("SELECT customer_id FROM ordr GROUP BY customer_id HAVING COUNT(*) >= 6 LIMIT 1").fetchone()[0]
    t4 = api.summarize_products(customer=cust)
ck("工具:按关键词给 → 归纳了、超过上限会说截断", "结论" in t1 and (t1.get("截断") or "") .startswith("一共") if
   c.execute("SELECT COUNT(*) FROM product WHERE name LIKE '%马面裙%'").fetchone()[0] > 10 else "结论" in t1, str(t1)[:120])
ck("工具:按款号给,和直接归纳同一个结论", t2["结论"] == r["结论"] and len(t2["规律"]) == len(r["规律"]))
ck("工具:什么都没给 → 报错说清三种给法", "error" in t3)
ck("工具:给客户 → 归纳她买过的(对照组是全店买过的)", t4.get("对照组", "").startswith("全店") and t4.get("明细") is not None, str(t4)[:120])

# ── 购买喜好推荐 ──
红款 = c.execute("SELECT s.spu FROM sku s JOIN color_family f ON f.color=s.color JOIN product p ON p.spu=s.spu "
                 "WHERE f.family='红' AND p.kind='标品' ORDER BY s.spu LIMIT 1").fetchone()[0]
回前 = c.execute("SELECT COUNT(*) FROM opportunity_recall").fetchone()[0]
出 = S.购买偏好回捞(c, [红款], 今); c.commit()
ck("推了人,而且单次不超过 5(用户 10-10:购买推断每次最多 5 人)", 0 < len(出) <= 5, str(len(出)))
起 = (今 - dt.timedelta(days=round(24 * 365.25 / 12))).isoformat()
错色 = []
for x in 出:
    if "颜色" in x["对上了"]:
        k = c.execute("SELECT COUNT(*) FROM ordr o JOIN ordr_item i ON i.order_id=o.id JOIN sku s ON s.code=i.sku "
                      "JOIN color_family f ON f.color=s.color WHERE o.customer_id=? AND f.family=? "
                      "AND substr(o.created,1,10) BETWEEN ? AND ? AND o.status NOT IN ('取消','已取消','待付款')",
                      (x["客户"], x["对上了"]["颜色"], 起, 今.isoformat())).fetchone()[0]
        if k < 2:
            错色.append((x["客户"], x["对上了"]["颜色"], k))
ck("推的每一位:独立 SQL 复核她真买过 ≥2 件那个色系", not 错色 and any("颜色" in x["对上了"] for x in 出), str(错色[:3]))
不该 = [x["客户"] for x in 出 if not c.execute(
    "SELECT 1 FROM customer cu JOIN account a ON a.id=cu.account_id WHERE cu.id=? AND a.marketing_consent=1 "
    "AND a.status NOT IN ('注销中','已注销')", (x["客户"],)).fetchone()]
ck("推的每一位都同意营销触达、账户没注销", not 不该, str(不该[:3]))
商 = c.execute("SELECT DISTINCT source, status FROM opportunity WHERE id IN (%s)" % ",".join("?" * len(出)),
               [x["商机"] for x in 出]).fetchall()
ck("推出来的是「待确认」商机,来源「购买偏好」", 商 == [("购买偏好", "待确认")], str(商))
ck("推断的绑定不进 opportunity_recall(那张表只放电话里说过的)",
   c.execute("SELECT COUNT(*) FROM opportunity_recall").fetchone()[0] == 回前
   and c.execute("SELECT COUNT(*) FROM buy_pref_recall").fetchone()[0] == len(出))
# 5 天后再上新一次(**不用同一天**:同一天的商机号 OP-B客户-日期 撞号会先挡住,冷却就测不到 —— 咬合 10-10 抓到)
再 = S.购买偏好回捞(c, [红款], 今 + dt.timedelta(days=5)); c.commit()
ck("冷却:5 天后再上新一次,推过的人不再推", not ({x["客户"] for x in 再} & {x["客户"] for x in 出}), str(len(再)))
# 颜色按她买的那件(咬合 10-10 抓到:真数据里推出来的 5 个人碰巧都没有「买蓝那件、款里另有红」,这条看不见)——
# 造一位:同一款(既有红 SKU 又有蓝 SKU)买了 3 次,每次都是蓝的;上新一款红的,**只让她一个人参选**
双色 = c.execute("SELECT s1.spu, s1.code FROM sku s1 JOIN color_family f1 ON f1.color=s1.color AND f1.family='蓝' "
                 "WHERE EXISTS (SELECT 1 FROM sku s2 JOIN color_family f2 ON f2.color=s2.color AND f2.family='红' "
                 "WHERE s2.spu=s1.spu) ORDER BY s1.spu LIMIT 1").fetchone()
样 = c.execute("SELECT cu.account_id, cu.shop, cu.advisor_no FROM customer cu JOIN account a ON a.id=cu.account_id "
               "WHERE a.marketing_consent=1 AND a.status='正常' LIMIT 1").fetchone()
c.execute("INSERT INTO customer(id, name, shop, advisor_no, account_id, created) VALUES('C-BLUE','只买蓝',?,?,?,?)",
          (样[1], 样[2], 样[0], 今.isoformat()))
for i in range(3):
    c.execute("INSERT INTO ordr(id, customer_id, shop, status, created) VALUES(?,?,?,?,?)",
              (f"O-BLUE-{i}", "C-BLUE", 样[1], "已完成", (今 - dt.timedelta(days=30 + i)).isoformat() + " 10:00:00"))
    c.execute("INSERT INTO ordr_item(order_id, sku, spu, name, qty) VALUES(?,?,?,?,1)", (f"O-BLUE-{i}", 双色[1], 双色[0], "x"))
c.commit()
别人 = {r_[0] for r_ in c.execute("SELECT DISTINCT customer_id FROM ordr WHERE customer_id<>'C-BLUE'")}
蓝 = S.购买偏好回捞(c, [红款], 今 + dt.timedelta(days=200), 已推=别人); c.commit()
ck("只买过蓝色那件(那款另有红色)的人,上新红色不推她", not any(x["客户"] == "C-BLUE" and x["对上了"].get("颜色") == "红" for x in 蓝),
   str([x for x in 蓝 if x["客户"] == "C-BLUE"]))

# 顾问答结论
任务 = [r_[0] for r_ in c.execute("SELECT schedule_id FROM opportunity_task WHERE kind='购买偏好回捞' ORDER BY schedule_id LIMIT 2")]
a1 = S.按结论处理(c, 任务[0], "客户想看,继续跟", "60000001", "想看", 今.isoformat())
a2 = S.按结论处理(c, 任务[1], "客户不要了", "60000001", "不喜欢红", 今.isoformat())
状 = [c.execute("SELECT o.status, o.wait_for FROM opportunity o JOIN opportunity_task t ON t.opp_id=o.id WHERE t.schedule_id=?",
                (t_,)).fetchone() for t_ in 任务]
ck("顾问答「想看」→ 跟进中;答「不要了」→ 已关闭(不带等什么)",
   a1[0] and a2[0] and 状[0][0] == "跟进中" and 状[1] == ("已关闭", None), f"{a1} / {a2} / {状}")
c.commit()
# 自动收口(用户 10-10):推断的提醒过期没人答 → 提醒取消、待确认商机关掉;客户说过的那种不动
收日 = 今 + dt.timedelta(days=10)
剩 = [r_[0] for r_ in c.execute("SELECT t.schedule_id FROM opportunity_task t JOIN schedule s ON s.id=t.schedule_id "
                                "WHERE t.kind='购买偏好回捞' AND t.answer IS NULL AND s.status='有效' AND substr(s.end_ts,1,10) < ?",
                                (收日.isoformat(),))]
# 样本:造一条「电话里说过的」回捞提醒,让它也过期 —— 真库里开着的那种可能是 0 条,空集合上「没被收」恒成立
_o = c.execute("SELECT id FROM opportunity WHERE status='搁置等供给' LIMIT 1").fetchone()
if _o:
    S._派提醒(c, _o[0], "回捞", "检查用:电话里说过的回捞提醒", 今, {"新品": 红款}); c.commit()
说过的前 = c.execute("SELECT COUNT(*) FROM opportunity_task t JOIN schedule s ON s.id=t.schedule_id "
                     "WHERE t.kind IN ('回捞','偏好回捞') AND s.status='有效'").fetchone()[0]
收 = S.推断提醒收口(c, 收日); c.commit()
关 = c.execute("SELECT COUNT(*) FROM opportunity o JOIN opportunity_task t ON t.opp_id=o.id WHERE t.schedule_id IN (%s) "
               "AND o.status='已关闭' AND o.close_reason LIKE '%%没人答%%'" % ",".join("?" * len(剩)), 剩).fetchone()[0] if 剩 else 0
ck("推断的提醒过期没人答 → 提醒取消(不算逾期)、待确认商机关掉并写明原因",
   bool(剩) and set(收) == set(剩) and 关 == len(剩)
   and c.execute("SELECT COUNT(*) FROM schedule WHERE id IN (%s) AND status='取消'" % ",".join("?" * len(剩)), 剩).fetchone()[0] == len(剩),
   f"剩 {len(剩)} / 收 {len(收)} / 关 {关}")
ck("客户亲口说过的那两种提醒不被收口", 说过的前 > 0 and c.execute("SELECT COUNT(*) FROM opportunity_task t JOIN schedule s ON s.id=t.schedule_id "
   "WHERE t.kind IN ('回捞','偏好回捞') AND s.status='有效'").fetchone()[0] == 说过的前)
ck("还没到期的不收", S.推断提醒收口(c, 今) == [])
# 卡片标得出「购买推断」
派给 = c.execute("SELECT s.assignee_no, s.shop FROM opportunity_task t JOIN schedule s ON s.id=t.schedule_id "
                 "WHERE t.kind='购买偏好回捞' AND s.assignee_no IS NOT NULL LIMIT 1").fetchone()
卡 = AC.卡片(dict(no=派给[0], name="顾问", role="顾问", shop=派给[1]), db=db, 今天=今) if 派给 else {"卡片": []}
ck("上新卡片里标得出「购买推断」,依据就是那句说法",
   any(k["留言"]["来源"] == "购买推断" and "件里" in (k["留言"]["当初原话"] or "") for k in 卡["卡片"]), str(卡["卡片"][:1])[:200])

c.close()
shutil.rmtree(tmp, ignore_errors=True)
import prompts
ck("工具有管它的规矩(TL71),版师也挂上了", any("summarize_products" in r_.needs for r_ in prompts.ALL_RULES)
   and "TL71" in {r_.id for r_ in prompts.PATTERN_RULES})
print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 商品归纳总结 + 购买喜好推荐都对(验了 {n} 条){D}")
