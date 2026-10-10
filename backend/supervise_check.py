#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产出监督 · 澜绣这一半(用户 10-10:AI 管理平台「能看 + 能打回」)—— 库的临时副本 + 临时投递箱,真库一行不碰。

验:报告 / 建议存下就进投递箱,载荷里有输入、规矩、输出、生成它的那一轮 · 输入里没有完整手机号 ·
同一版只排一次 · 打回的报告不许确认、店长看得到理由 · 打回的建议旧版连同理由留作样本、带着理由重写一版 ·
同步工具按外部id 分派到对的执行函数 · trace_id 真的从 sdk 走到了工具子进程和调模型入口。
"""
import json, os, re, shutil, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agent"), os.path.join(ROOT, "tools")]
import api, report_doc, arrival_card as AC, oplog, artifact_report as AR

咬合 = [
    ("被打回的报告照样能确认", "打回的那一版确认不了(REJECTED)"),
    ("打回建议时把旧版直接删了(样本没了)", "打回建议:旧版连同理由留在 recall_advice_log"),
    ("重写时不把打回理由给模型", "重写时模型拿到了上一版和打回理由"),
    # 预期红指向「发送前那一道」:真实的输入(取数包 / 建议材料)本来就不带手机号,另一条在真数据上看不见这处破坏(咬合 10-10 抓到)
    ("产出上报把完整手机号带出门", "发送前还有一道:手机号到了出门那一刻也会被打码"),
    ("存报告不记是哪一轮对话", "报告存下了生成它的那一轮(trace_id)"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


print("产出监督 · 澜绣这一半 · 库副本 + 临时投递箱")
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(api.DB, db)
api.DB = report_doc.DB = AC.DB = oplog.DB = db
AR.箱, AR.确, AR.伤 = (os.path.join(tmp, x) for x in ("outbox.jsonl", "acked.jsonl", "err.jsonl"))
c = sqlite3.connect(db)
report_doc.建表(c); c.execute("DELETE FROM store_report_doc"); c.commit()
店 = c.execute("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
店长 = dict(no="SM-CHECK", name="店长", role="店长", shop=店)


def 箱里():
    return [json.loads(l) for l in open(AR.箱, encoding="utf-8")] if os.path.exists(AR.箱) else []


# ── 报告 ──
os.environ["LANXIU_TRACE"] = "tr-check-0001"
with api.as_user(店长):
    r = api.save_report(body="## 上周周报\n下单与营收见取数包。", kind="周")
os.environ.pop("LANXIU_TRACE", None)
ck("报告存下了生成它的那一轮(trace_id)",
   c.execute("SELECT trace_id FROM store_report_doc WHERE id=?", (r.get("报告号"),)).fetchone() == ("tr-check-0001",))
报 = [x for x in 箱里() if x["载荷"]["类型"] == "报告"]
载 = 报[-1]["载荷"] if 报 else {}
ck("报告进了产出投递箱:输入 = 冻结的取数包、规矩 = TL67 / TL68、输出 = 正文、带这一轮",
   bool(载) and 载["外部id"] == f"报告:{r.get('报告号')}" and "期内" in (载.get("输入") or {})
   and {x["编号"] for x in 载.get("规则") or []} == {"TL67", "TL68"} and 载["输出"].startswith("## 上周周报")
   and 载["外部trace"] == "tr-check-0001", str(载)[:160])
ck("载荷过得了发送前的自检", 载 and not AR.缺什么(载), str(AR.缺什么(载) if 载 else "没载荷"))
AR.排队(**{k: 载[k] for k in ("外部id", "类型", "版本", "标题", "输入", "输出", "规则")})
ck("同一版只排一次(键由外部id + 版本算出)", len([x for x in 箱里() if x["载荷"]["外部id"] == 载.get("外部id")]) == 1)

ok, 说 = report_doc.打回(r.get("报告号"), "审核员(AI 管理平台)", "营收没写退款口径")
with api.as_user(店长):
    确 = api.confirm_report(r.get("报告号"))
    看 = api.list_reports(report_id=r.get("报告号"))
    列 = api.list_reports(kind="周")
ck("打回的那一版确认不了(REJECTED)", 确.get("code") == "REJECTED" and "营收没写退款口径" in 确.get("reason", ""), str(确)[:120])
ck("店长看得到打回理由(单份和列表都带)", 看.get("reject_reason") == "营收没写退款口径"
   and any(x.get("rejected_at") for x in 列.get("报告") or []))
ck("同一版再打回一次不重复记", report_doc.打回(r.get("报告号"), "审核员", "再来一次")[0] and
   c.execute("SELECT reject_reason FROM store_report_doc WHERE id=?", (r.get("报告号"),)).fetchone()[0] == "营收没写退款口径")
with api.as_user(店长):
    r2 = api.save_report(body="## 上周周报(改)\n营收 = 实收 − 退款。", kind="周", report_id=r.get("报告号"))
    ck("重新存的新版能确认", api.confirm_report(r2.get("报告号")).get("ok") is True)

# ── 建议 ──
oid, spu = c.execute("SELECT opp_id, spu FROM opportunity_recall LIMIT 1").fetchone()
AC.建表(c); c.execute("DELETE FROM recall_advice"); c.execute("DELETE FROM recall_advice_log"); c.commit()
材 = []


def 假模型(材料):
    材.append(材料)
    return {"content": [{"type": "text", "text": f"1. 第{len(材)}版开口\n2. 推她提过的颜色\n3. 先问还需不需要"}]}


AC.写建议(c, oid, spu, call=假模型); c.commit()
建 = [x for x in 箱里() if x["载荷"]["类型"] == "建议"]
ck("建议进了产出投递箱:第 1 版、有输入和提示词", bool(建) and 建[-1]["载荷"]["版本"] == 1
   and 建[-1]["载荷"]["规则"] and 建[-1]["载荷"]["输入"], str(建[-1]["载荷"] if 建 else "")[:160])
真号 = c.execute("SELECT phone FROM customer WHERE id=(SELECT customer_id FROM opportunity_recall WHERE opp_id=? LIMIT 1)",
                 (oid,)).fetchone()[0]
ck("上报的输入里没有完整手机号", all(not re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", json.dumps(x["载荷"]["输入"], ensure_ascii=False))
                                    for x in 箱里()))
ck("发送前还有一道:手机号到了出门那一刻也会被打码",
   "1380000" not in json.dumps(AR.组载荷(外部id="x", 类型="建议", 版本=1, 标题="t", 输入={"电话": "13800001234"},
                                        输出="o", 规则=[{"编号": 1, "正文": "z"}])["输入"], ensure_ascii=False))
ok, 说, 新 = AC.打回重写(oid, spu, "审核员(AI 管理平台)", "不要写价格", db=db, call=假模型)
c2 = sqlite3.connect(db)
ck("打回建议:旧版连同理由留在 recall_advice_log",
   c2.execute("SELECT version, text, reject_reason FROM recall_advice_log WHERE opp_id=? AND spu=?", (oid, spu)).fetchall()
   == [(1, "1. 第1版开口\n2. 推她提过的颜色\n3. 先问还需不需要", "不要写价格")])
ck("打回建议:现行的是第 2 版", ok and 新 == 2 and
   c2.execute("SELECT version, text FROM recall_advice WHERE opp_id=? AND spu=?", (oid, spu)).fetchone()[0] == 2)
ck("重写时模型拿到了上一版和打回理由", len(材) == 2 and "不要写价格" in 材[1] and "第1版开口" in 材[1], (材[-1] if 材 else "")[-120:])
ck("第 2 版也进了投递箱(管理后台上看得到新版)",
   any(x["载荷"]["外部id"] == f"建议:{oid}:{spu}" and x["载荷"]["版本"] == 2 for x in 箱里()))
c2.close()

# ── 同步工具:按外部id 分派 ──
import supervise_sync as SS
结1 = SS.执行({"外部id": f"报告:{r2.get('报告号')}", "理由": "测试", "created_by": "审核员"})
结2 = SS.执行({"外部id": "随便什么", "理由": "x"})
ck("同步:报告的打回分派到报告那边", 结1[0] == "已标记", str(结1))
ck("同步:认不出的外部id → 执行失败(不静默当成功)", 结2[0] == "执行失败", str(结2))

# ── trace_id 真的走通了 ──
sdk_src = open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
ck("sdk:这一轮的 trace_id 先定,进工具子进程的 env,树用同一个",
   "mcp_servers=mcp_config(me, kind, 名单=工具, trace=_tid)" in sdk_src and "tid=_tid)" in sdk_src
   and '"LANXIU_TRACE": trace' in sdk_src)
v1_src = open(os.path.join(ROOT, "agent", "v1.py"), encoding="utf-8").read()
ck("调模型入口把 extra(调用号)交给记录仪", "extra=extra,**kw" in v1_src)

c.close()
shutil.rmtree(tmp, ignore_errors=True)
print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 产出监督澜绣这一半都对(验了 {n} 条){D}")
