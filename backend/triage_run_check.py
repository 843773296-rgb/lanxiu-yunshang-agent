#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判运行记录 · 检查(研判队列未做项第 2 项 · 用户 2026-10-18 拍:自建运行记录、单条超时 2 分钟)。

库副本上真调 `triage_run`,页面那两个纯函数用 node 真跑。要守的:
  · 同一工单同时只有一条在跑 —— 再点返回同一个运行号;库里唯一索引兜底(两个窗口同时插也插不进第二条);
  · 执行线程按先来后到领;排队的看得到「前面还有几条」;
  · 心跳断了 → 跑到一半的标「中断」,**排队的不动**(执行线程回来接着领);心跳在 → 不动;
  · 已经被标中断的,迟到的收尾不覆盖;
  · 失败 / 超时 / 中断才能转人工,转了就不再被自动挑;要身份;
  · 站上不再在请求里同步跑;调模型有超时;页面把超时显示成失败而不是成功。

⚠️ 没验到的:真的让模型跑超过 2 分钟、看 `asyncio.wait_for` 把它掐掉 —— 那要起 8760 + 真 SDK,
   不进门禁(依赖外部状态的检查放进门禁会变成随机拦路)。这里只验「超时那条路接上了」。
"""
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    # 「提交时不查有没有在跑的」不单列:唯一索引会接住、落回返回旧那条 —— 两层是故意的,拆一层看不出来
    ("库里不建「同一工单只许一条在跑」的唯一索引", "库里兜底:同一工单插第二条在跑的 → 唯一索引拒绝(两个窗口同时插也插不进)"),
    ("心跳断了连排队的也标中断", "心跳断了:跑到一半的标中断,排队的不动"),
    ("页面把超时算成跑完了", "页面:超时 / 中断进失败那一栏,提示是 bad 不是 ok"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


def 抛(f):
    try:
        f(); return None
    except Exception as e:                   # noqa: BLE001
        return e


print("研判运行记录 · 检查")
print("=" * 80)

import triage_run as T

ck("单条超时是用户拍的 2 分钟(手抄的常数,不现算)", T.单条超时秒 == 120, T.单条超时秒)

tmp = tempfile.mkdtemp(prefix="trun-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
me = {"no": "W-检查", "name": "检查", "role": "店长"}
状态 = lambda rid: sqlite3.connect(db).execute("SELECT status FROM triage_run WHERE id=?", (rid,)).fetchone()[0]

a = T.提交(["T-甲", "T-乙", "T-丙"], me, db=db)
号 = {r["task_id"]: r["run_id"] for r in a["runs"]}
ck("提交三条 → 三个运行号、都在排队、批次号当场给出", a.get("batch") and len(号) == 3
   and all(状态(x) == "排队" for x in 号.values()), a)
b = T.提交(["T-甲", "T-丁"], me, db=db)
ck("同一工单再提交 → 返回同一个运行号,不另起一条",
   b["runs"][0]["run_id"] == 号["T-甲"] and b["runs"][0]["复用"] is True and b["runs"][1]["复用"] is False, b)
号["T-丁"] = b["runs"][1]["run_id"]
_c = sqlite3.connect(db)
e = 抛(lambda: _c.execute("INSERT INTO triage_run(batch,task_id,status) VALUES('x','T-乙','排队')"))
_c.rollback(); _c.close()        # 撞索引那一下开了个写事务,不收会锁住后面每一步
ck("库里兜底:同一工单插第二条在跑的 → 唯一索引拒绝(两个窗口同时插也插不进)",
   isinstance(e, sqlite3.IntegrityError), e)

q = T.查运行([号["T-丙"]], db=db)
ck("排队的看得到前面还有几条(丙前面有甲、乙)", q["runs"] and q["runs"][0]["前面还有几条"] == 2, q)

领 = T.领一条(db=db)
ck("执行线程按先来后到领 → 先领到甲,甲进「取数」", 领 and 领["task_id"] == "T-甲" and 状态(号["T-甲"]) == "取数", 领)
T.标阶段(号["T-甲"], "调模型", db=db)

# 心跳:没有 / 新鲜 / 断了
ck("从没报过心跳 → 执行线程不在", not T.执行线程在吗(sqlite3.connect(db)))
T.心跳(4242, db=db)
ck("心跳新鲜 → 不收中断,跑到一半的照旧", T.收中断(db=db) == 0 and 状态(号["T-甲"]) == "调模型")
with sqlite3.connect(db) as c:
    c.execute("UPDATE triage_worker SET beat=?", ((dt.datetime.now() - dt.timedelta(seconds=T.心跳断了秒 + 5))
                                                  .strftime("%Y-%m-%d %H:%M:%S"),))
收 = T.收中断(db=db)
ck("心跳断了:跑到一半的标中断,排队的不动",
   收 == 1 and 状态(号["T-甲"]) == "中断" and 状态(号["T-乙"]) == "排队" and 状态(号["T-丙"]) == "排队", (收, 状态(号["T-乙"])))
ck("迟到的收尾不覆盖已经中断的(那时结果已经没人等了)",
   T.收尾(号["T-甲"], "完成", 99, 0.01, db=db) == 0 and 状态(号["T-甲"]) == "中断")
ck("中断之后同一工单能重新提交(不再被「在跑」挡住)", T.提交(["T-甲"], me, db=db)["runs"][0]["复用"] is False)

乙 = T.领一条(db=db)
T.收尾(乙["run_id"], "超时", error="调模型超过 2 分钟", db=db)
ck("超时收尾 → 状态「超时」、原因留着", 状态(号["T-乙"]) == "超时"
   and "2 分钟" in (sqlite3.connect(db).execute("SELECT error FROM triage_run WHERE id=?", (号["T-乙"],)).fetchone()[0] or ""))
丙 = T.领一条(db=db)
T.收尾(丙["run_id"], "完成", triage_id=7, cost=0.02, db=db)
ck("完成的不能转人工", T.转人工(号["T-丙"], me, db=db).get("ok") is False)
ck("没身份不能转人工", isinstance(抛(lambda: T.转人工(号["T-乙"], {}, db=db)), PermissionError))
r = T.转人工(号["T-乙"], me, db=db)
ck("超时的转人工 → 记下谁转的,此后不再被自动挑", r.get("ok") and "T-乙" in T.转人工的工单(db=db)
   and "T-丙" not in T.转人工的工单(db=db), r)
T.提交(["T-乙"], me, db=db)
ck("转人工之后又被人单独点了一次 → 最近一次不是转人工,自动挑单不再跳过它", "T-乙" not in T.转人工的工单(db=db))
shutil.rmtree(tmp, ignore_errors=True)

# ── 站上和页面 ─────────────────────────────────────────────────────────
站 = open(os.path.join(ROOT, "agentsite", "app.py"), encoding="utf-8").read()
跑批段 = 站[站.index('if p in ("/run-triage", "/run-batch"):'):站.index("def _triage_one")]
ck("站上不再在请求里同步跑(/run-batch 只登记、当场返回批次号)",
   "_triage_one(" not in 跑批段 and "/api/triage-run-submit" in 跑批段, "跑批段里还在调 _triage_one")
ck("调模型套了超时,超时值取 triage_run 那一份", "asyncio.wait_for(sdk.run(" in 站 and "_tr.单条超时秒" in 站)
ck("执行线程起来先收「上一个进程跑到一半的」,还报心跳", '"op": "recover"' in 站 and '"op": "beat"' in 站
   and "_起执行线程()" in 站)
ck("自动挑单跳过转人工的", '"op": "handed"' in 跑批段 and 'x["task_id"] not in _转' in 跑批段)

页 = open(os.path.join(ROOT, "agentsite", "web", "queue.html"), encoding="utf-8").read()


def 抽(名):
    m = re.search(r"function %s\(.*?\n\}" % re.escape(名), 页, re.S)
    return m.group(0) if m else ""


js = "\n".join(['const esc=s=>(s??"").toString();', 抽("批量提示文"), 抽("软化"), 抽("运行汇总"), 抽("运行进度文"), """
const runs=[{task_id:"A",status:"完成",cost:0.01,triage_id:1},{task_id:"B",status:"超时",error:"调模型超过 2 分钟"},
            {task_id:"C",status:"中断",error:"执行线程没在跑"}];
const r=运行汇总(runs), t=批量提示文(r, r.done.length, "未研判");
const p1=运行进度文([{task_id:"A",status:"调模型"},{task_id:"B",status:"排队",前面还有几条:1}], true);
const p2=运行进度文([{task_id:"B",status:"排队",前面还有几条:3}], false);
const p3=运行进度文([{task_id:"B",status:"排队",前面还有几条:3}], true);
console.log(JSON.stringify({done:r.done.length, failed:r.failed.length, 级:t.级, 文:t.文, p1, p2, p3}));
"""])
f = os.path.join(tempfile.mkdtemp(prefix="trun-js-"), "t.js")
open(f, "w", encoding="utf-8").write(js)
跑 = subprocess.run(["node", f], capture_output=True, text=True)
try:
    o = json.loads(跑.stdout.strip())
except Exception:
    o = {}
ck("页面:超时 / 中断进失败那一栏,提示是 bad 不是 ok", o.get("done") == 1 and o.get("failed") == 2 and o.get("级") == "bad",
   跑.stderr[:200] or o)
ck("页面:进度说出谁在哪一步;只有排队时说「你前面还有几条」",
   "A 在调模型" in (o.get("p1") or {}).get("文", "") and "前面还有 3 条" in (o.get("p3") or {}).get("文", ""), o)
ck("页面:执行线程不在时照实说,不显示成在跑", (o.get("p2") or {}).get("级") == "bad"
   and "执行线程没在跑" in (o.get("p2") or {}).get("文", ""), o.get("p2"))
ck("页面:运行号存下来,刷新后接着跟", "读运行号()" in 页 and "跟运行(上次)" in 页)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 研判运行记录:不重复跑、看得到排到哪、断了标中断、排队的接着跑、超时可转人工(验了 {n} 条){D}")
