#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重开 / 更正 · 检查(研判队列未做项第 3 项 · 用户 2026-10-19 拍)—— 库副本上自造工单,从复核走到重开、更正。

要守的:
  · 复核那一岗或总部运营能重开,别的岗位不行;要写原因;
  · 重开 → 回到待复核、旧结论进操作台账留档、工单回到待处理、**建单时间不动**(计时接着算);
  · 已办结的不重开,开更正工单:新单同类型、挂着原单号,原单和回执不动;
  · 改判候选跟着撤;已并入评测集的那条从 truth 撤下。
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("已办结的也能重开", "已办结的不重开(返回 CLOSED),回执不动"),
    ("重开把建单时间重置成现在", "重开 → 待复核、旧结论清掉、工单回待处理、建单时间不动(计时接着算)"),
    ("重开时不撤已并入评测集的改判", "已并入评测集的改判,重开时从 truth 撤下"),
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


print("重开 / 更正 · 检查")
print("=" * 80)

import ops, oplog, relabel as RL

tmp = tempfile.mkdtemp(prefix="reopen-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
ops.DB = oplog.DB = db
c = sqlite3.connect(db)
人 = lambda role: c.execute("SELECT no, name, role FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1",
                            (role,)).fetchone()
店长, 总部, 售后, 财务 = 人("店长"), 人("总部运营"), 人("售后"), 人("财务")
完 = c.execute("SELECT id FROM maintain WHERE status='已完成' ORDER BY id LIMIT 1").fetchone()
造 = {"T-检查-重开-甲": ("财务人工任务", "P-甲"), "T-检查-重开-乙": ("售后判责", 完[0] if 完 else None),
      "T-检查-重开-丙": ("财务人工任务", "P-丙"), "T-检查-重开-丁": ("财务人工任务", "P-丁")}
for tid, (ty, ref) in 造.items():
    c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
              (tid, ty, ref, "待处理", "2026-01-01 10:00:00", "检查"))
c.commit(); c.close()
查 = lambda sql, *a: sqlite3.connect(db).execute(sql, a).fetchone()
选 = ops.改判选项("BP-01")

if not (店长 and 总部 and 售后 and 财务 and 完 and 选):
    ck("库里有店长 / 总部运营 / 售后 / 财务、一张已完成的维保单、BP-01 预存根因 —— 没有就没验,不算通过", False)
else:
    长, 部, 后, 财 = (dict(zip(("no", "name", "role"), x)) for x in (店长, 总部, 售后, 财务))
    研 = {tid: ops.save_triage(tid, "BP-01" if 造[tid][0] == "财务人工任务" else "BP-03", f"检查-重开-{i}",
                               "根因:检查造的\n建议动作:检查\n证据:无", []) for i, tid in enumerate(造)}

    # 甲:采纳 → 重开
    ops.resolve(研["T-检查-重开-甲"], "已采纳", 长, 来源="检查")
    e = 抛(lambda: ops.重开(研["T-检查-重开-甲"], 长, "", 来源="检查"))
    ck("没写原因不能重开", isinstance(e, ValueError) and 查("SELECT status FROM triage WHERE id=?", 研["T-检查-重开-甲"])[0] == "已采纳", e)
    e = 抛(lambda: ops.重开(研["T-检查-重开-甲"], 财, "财务觉得不对", 来源="检查"))
    ck("不是复核那一岗(财务管的是办结那一段)不能重开", isinstance(e, PermissionError), e)
    r = ops.重开(研["T-检查-重开-甲"], 长, "顾客补来了渠道回单,原判不对", 来源="检查")
    行 = 查("SELECT status, human_root_cause, handler, reopen_count, reopen_note FROM triage WHERE id=?", 研["T-检查-重开-甲"])
    单 = 查("SELECT status, created FROM task WHERE id=?", "T-检查-重开-甲")
    ck("重开 → 待复核、旧结论清掉、工单回待处理、建单时间不动(计时接着算)",
       r.get("ok") and 行[0] == "待复核" and 行[1] is None and 行[2] is None and 行[3] == 1
       and 单 == ("待处理", "2026-01-01 10:00:00"), (r, 行, 单))
    留 = 查("SELECT ctx FROM op_log WHERE code='REOPEN' AND target=? ORDER BY rowid DESC LIMIT 1", f"triage#{研['T-检查-重开-甲']}")
    ck("旧结论进操作台账留档(状态和复核人都在)", 留 and json.loads(留[0]).get("旧结论", {}).get("status") == "已采纳"
       and 长["no"] in (json.loads(留[0])["旧结论"].get("handler") or ""), 留)
    ck("队列那一行标出重开过几次", next((x for x in ops.queue() if x["task_id"] == "T-检查-重开-甲"), {}).get("重开次数") == 1)
    ck("待复核的不能再重开", ops.重开(研["T-检查-重开-甲"], 长, "再来一次", 来源="检查").get("code") == "BAD_STATE")

    # 乙:售后采纳 → 办结 → 重开被拒 → 开更正工单(总部运营也能开)
    ops.resolve(研["T-检查-重开-乙"], "已采纳", 后, 来源="检查")
    ops.办结(研["T-检查-重开-乙"], 完[0], 后, 来源="检查")
    r = ops.重开(研["T-检查-重开-乙"], 后, "判错了", 来源="检查")
    ck("已办结的不重开(返回 CLOSED),回执不动", r.get("code") == "CLOSED"
       and 查("SELECT receipt FROM triage WHERE id=?", 研["T-检查-重开-乙"])[0] == 完[0], r)
    ck("没办结的不开更正工单(直接重开)", ops.开更正工单(研["T-检查-重开-甲"], 长, "x", 来源="检查").get("code") == "NOT_CLOSED")
    r = ops.开更正工单(研["T-检查-重开-乙"], 部, "责任判给了顾客,其实是面料问题", 来源="检查")
    新 = 查("SELECT type, ref_id, status, summary FROM task WHERE id=?", r.get("task_id") or "")
    ck("开更正工单:同类型、同单据、待处理,摘要挂着原单号;原单不动",
       r.get("ok") and 新 and 新[:3] == ("售后判责", 完[0], "待处理") and "T-检查-重开-乙" in 新[3]
       and 查("SELECT status FROM triage WHERE id=?", 研["T-检查-重开-乙"])[0] == "已采纳", (r, 新))
    ck("再开一张编号递增,不撞号", ops.开更正工单(研["T-检查-重开-乙"], 部, "再更正", 来源="检查").get("task_id", "").endswith("更正2"))

    # 丙:改判候选待审核 → 重开 → 候选撤回
    ops.resolve(研["T-检查-重开-丙"], "已改判", 长, root_cause=选[0]["root_cause"], 来源="检查")
    ops.重开(研["T-检查-重开-丙"], 长, "改判也判错了", 来源="检查")
    ck("改判候选跟着撤(待审核 → 已撤回)", 查("SELECT relabel_review FROM triage WHERE id=?", 研["T-检查-重开-丙"])[0] == "已撤回")

    # 丁:改判 → 采用 → 并入 truth → 重开(总部运营)→ 从 truth 撤下
    ops.resolve(研["T-检查-重开-丁"], "已改判", 长, root_cause=选[0]["root_cause"], 来源="检查")
    RL.审核(研["T-检查-重开-丁"], 部, True, db=db, 来源="检查")
    RL.并入(db=db, 演练=False)
    在 = 查("SELECT src FROM truth WHERE case_id=?", "检查-重开-3")
    r = ops.重开(研["T-检查-重开-丁"], 部, "并入后发现是错的", 来源="检查")
    ck("已并入评测集的改判,重开时从 truth 撤下", 在 == ("人工改判",) and r.get("撤下评测") is True
       and 查("SELECT src FROM truth WHERE case_id=?", "检查-重开-3") is None
       and 查("SELECT into_eval FROM triage WHERE id=?", 研["T-检查-重开-丁"])[0] == 0, (在, r))
shutil.rmtree(tmp, ignore_errors=True)

页 = open(os.path.join(ROOT, "agentsite", "web", "queue.html"), encoding="utf-8").read()
ck("页面:有结论的研判给「重开」/「开更正工单」,走 /api/ops-reopen", "function 重开块(" in 页
   and "${done ? 重开块(x, d)" in 页 and '"/api/ops-reopen"' in 页)
源 = open(os.path.join(HERE, "ops.py"), encoding="utf-8").read()
ck("防覆盖那句提示不再说「这个入口还没有」", "这个入口还没有\")" not in 源)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 重开 / 更正:谁能重开、旧结论留档、计时不重置、已办结开更正工单、改判跟着撤(验了 {n} 条){D}")
