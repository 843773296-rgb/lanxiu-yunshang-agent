#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首页指标 · 名称、范围和取数对得上 · 检查(10-19 外部复审 3.2)。

复审看到的:「Top 失败原因」里排着 SUCCESS;「等待复核 4 / 已核验 0 / 已合并 0 / 规则数 14」写死在页面里;
「财务人工任务 / 客户合并确认」按类型全量取,已处理的也算待处理;「当日 / 较昨日」取的是最后两个有记录的日子。
在库副本上自造这几种形状去调 `server.workbench()` —— 红不红不取决于主库被怎么用过。
"""
import datetime as dt, os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("失败原因又不排除 SUCCESS", "「失败原因」不含成功的那条"),
    ("待处理按类型全量取(不看结束没)", "待处理只算没结束的:新开一件 +1,关掉 -1"),
    ("较昨日又拿最后两个有记录的日子比", "昨天没有记录 → 不给「较昨日」,也不拿更早的一天冒充"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


print("首页指标 · 名称、范围和取数对得上")
print("=" * 80)
import oplog, ops, server as SV, worldclock   # noqa: E401 —— 先加载,用副本才改得到它们的 DB
import check_copy
db = check_copy.用副本("workbench-")
今 = worldclock.今天(); 昨 = 今 - dt.timedelta(days=1); 前 = 今 - dt.timedelta(days=2)

def 写(sql, *a):
    with sqlite3.connect(db) as c:
        c.execute(sql, a)

# ── 失败原因 + 今天 / 昨天:清空退款轨迹,自造「今天 2 条(1 条成功)、前天 1 条、昨天没有」──
写("DELETE FROM refund_trace")
for d, code in ((今, "TIMEOUT"), (今, "SUCCESS"), (前, "TIMEOUT")):
    写("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key) VALUES(?,?,?,?,?,?,?,?)",
      "DQ-检查", 1, f"{d.isoformat()} 10:00:00", "微信支付", 100, code, "检查", f"IDEM-{code}-{d}")
w = SV.workbench()
ck("「失败原因」不含成功的那条", w["codes"] and all(c["c"] != "SUCCESS" for c in w["codes"]), w["codes"])
m = {x["label"]: x for x in w["metrics"]}
ck("「今日」取的是世界的今天(今天 2 条)", m.get("退款尝试(今日)", {}).get("value") == "2", m.get("退款尝试(今日)"))
ck("昨天没有记录 → 不给「较昨日」,也不拿更早的一天冒充",
   m["退款尝试(今日)"].get("trend") is None and "昨天没有记录" in (m["退款尝试(今日)"].get("sub") or ""), m["退款尝试(今日)"])
写("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key) VALUES(?,?,?,?,?,?,?,?)",
  "DQ-检查", 2, f"{昨.isoformat()} 10:00:00", "微信支付", 100, "TIMEOUT", "检查", "IDEM-昨")
m = {x["label"]: x for x in SV.workbench()["metrics"]}
ck("昨天有 1 条、今天 2 条 → 较昨日 +100%", m["退款尝试(今日)"].get("trend") == 100.0, m["退款尝试(今日)"])

# ── 待处理只算没结束的(和研判队列同一口径)──
前件 = len(SV.workbench()["finance"])
写("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES('T-首页检查','财务人工任务','DQ-检查','待处理',?,'检查')",
  f"{今.isoformat()} 09:00:00")
开后 = len(SV.workbench()["finance"])
写("UPDATE task SET status='已关闭' WHERE id='T-首页检查'")
关后 = len(SV.workbench()["finance"])
ck("待处理只算没结束的:新开一件 +1,关掉 -1", (开后, 关后) == (前件 + 1, 前件), (前件, 开后, 关后))
w = SV.workbench()
队 = [x for x in ops.queue() if not x["done"]]
ck("首页的待处理件数、等待复核数,和研判队列里没结束的那些逐项对得上",
   len(w["finance"]) == sum(1 for x in 队 if x["type"] == "财务人工任务")
   and len(w["merge"]) == sum(1 for x in 队 if x["type"] == "客户合并确认")
   and w["pend"]["finance"]["待复核"] == sum(1 for x in 队 if x["type"] == "财务人工任务" and x["state"] == "待复核"),
   (len(w["finance"]), len(w["merge"]), w["pend"]))

# ── 页面上不再写死数 ──
页 = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
写死 = re.findall(r'\["(等待复核|已核验|已合并|规则数)",\s*\d+', 页)
ck("待处理卡片的细项都从数据来,页面里不写死数", not 写死 and "W.pend.finance.待复核" in 页 and "W.状态机数" in 页, 写死)

print()
if 坏:
    print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 首页指标:失败原因不含成功、今天昨天按日历、待处理和研判队列同一口径、页面不写死数(验了 {n} 条){D}")
