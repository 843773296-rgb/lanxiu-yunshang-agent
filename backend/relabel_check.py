#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改判先审核,再进评测集 · 检查(研判队列未做项第 4 项 · 用户 2026-10-19 拍:总部运营审)。

库副本上自造工单,从改判走到审核、并入。要守的:
  · 改判**不当场写 truth**,只记成待审核的候选;
  · 只有总部运营能审,改判人自己审不了;驳回要写理由;
  · 采用了也还不进 truth —— 并入那一步才写;演练不写;
  · 并入时那一单已有建库标注且不一致 → 不覆盖,列出来;
  · 页面不再说那句不成立的「回归时会单独统计通过率」。
"""
from contextlib import closing   # ← 连接要显式关:sqlite3 的 with 只管事务,不关连接(2026-10-29)
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("改判又当场写进 truth", "改判只进候选:truth 里没有这一单,研判记成待审核"),
    ("改判人能审自己的改判", "改判人自己审不了(要第二个人把关)"),
    ("并入时覆盖建库标注", "并入时那一单已有建库标注且不一致 → 不覆盖,列进冲突"),
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


print("改判先审核,再进评测集 · 检查")
print("=" * 80)

import ops, oplog, relabel as RL

tmp = tempfile.mkdtemp(prefix="relabel-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
ops.DB = oplog.DB = db
c = sqlite3.connect(db)
# 副本里先把主库上真实的改判候选清掉 —— 并入数的是全表的「已采用」,主库有人真审过的话会被数进来
RL.确保列(c); c.execute("UPDATE triage SET relabel_review=NULL WHERE relabel_review IS NOT NULL")
人 = lambda role: c.execute("SELECT no, name, role FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1",
                            (role,)).fetchone()
店长, 总部 = 人("店长"), 人("总部运营")
造 = ["T-检查-改判-甲", "T-检查-改判-乙"]
for tid in 造:
    c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
              (tid, "财务人工任务", f"P-{tid}", "待处理", "2026-01-01 10:00:00", "检查"))
c.commit(); c.close()
真值 = lambda case: sqlite3.connect(db).execute("SELECT root_cause, src FROM truth WHERE case_id=?", (case,)).fetchone()
行 = lambda tid: sqlite3.connect(db).execute("SELECT relabel_review, into_eval FROM triage WHERE id=?", (tid,)).fetchone()
选 = ops.改判选项("BP-01")

if not (店长 and 总部 and len(选) >= 2):
    ck("库里有店长、总部运营,BP-01 有至少两个预存根因 —— 没有就没验,不算通过", False, (店长, 总部, len(选)))
else:
    长 = dict(zip(("no", "name", "role"), 店长))
    部 = dict(zip(("no", "name", "role"), 总部))
    case = {tid: f"检查-改判-{i}" for i, tid in enumerate(造)}
    研 = {tid: ops.save_triage(tid, "BP-01", case[tid], "根因:检查造的\n建议动作:检查\n证据:无", []) for tid in 造}

    r = ops.resolve(研["T-检查-改判-甲"], "已改判", 长, root_cause=选[0]["root_cause"], 来源="检查")
    ck("改判只进候选:truth 里没有这一单,研判记成待审核",
       真值(case["T-检查-改判-甲"]) is None and 行(研["T-检查-改判-甲"])[0] == "待审核"
       and r.get("进候选待审核") is True and r.get("回流评测集") is False, (真值(case["T-检查-改判-甲"]), r))
    ck("「改判待审」档能单独筛出来", "T-检查-改判-甲" in {x["task_id"] for x in ops.queue("改判待审")})

    e = 抛(lambda: RL.审核(研["T-检查-改判-甲"], 长, True, db=db, 来源="检查"))
    ck("不是总部运营审不了", isinstance(e, PermissionError), e)
    with closing(sqlite3.connect(db)) as cx, cx:          # 假装是这位总部运营自己改判的
        cx.execute("UPDATE triage SET relabel_by_no=? WHERE id=?", (部["no"], 研["T-检查-改判-甲"]))
    e = 抛(lambda: RL.审核(研["T-检查-改判-甲"], 部, True, db=db, 来源="检查"))
    ck("改判人自己审不了(要第二个人把关)", isinstance(e, PermissionError) and 行(研["T-检查-改判-甲"])[0] == "待审核", e)
    with closing(sqlite3.connect(db)) as cx, cx:
        cx.execute("UPDATE triage SET relabel_by_no=? WHERE id=?", (长["no"], 研["T-检查-改判-甲"]))
    e = 抛(lambda: RL.审核(研["T-检查-改判-甲"], 部, False, "", db=db, 来源="检查"))
    ck("驳回不写理由被拒", isinstance(e, ValueError) and 行(研["T-检查-改判-甲"])[0] == "待审核", e)
    r = RL.审核(研["T-检查-改判-甲"], 部, True, db=db, 来源="检查")
    ck("总部运营采用 → 已采用,但 truth 里**还没有**(要等并入)",
       r.get("ok") and 行(研["T-检查-改判-甲"])[0] == "已采用" and 真值(case["T-检查-改判-甲"]) is None, r)
    ck("采用过的不能再审一遍", RL.审核(研["T-检查-改判-甲"], 部, False, "反悔", db=db, 来源="检查").get("ok") is False)

    # 乙:采用之后、并入之前,那一单有了建库标注(和改判不一致)
    ops.resolve(研["T-检查-改判-乙"], "已改判", 长, root_cause=选[0]["root_cause"], 来源="检查")
    RL.审核(研["T-检查-改判-乙"], 部, True, db=db, 来源="检查")
    with closing(sqlite3.connect(db)) as cx, cx:
        cx.execute("INSERT INTO truth(case_id,breakpoint,root_cause,expected_action,src) VALUES(?,?,?,?,'建库标注')",
                   (case["T-检查-改判-乙"], "BP-01", 选[1]["root_cause"], "检查"))

    演 = RL.并入(db=db, 演练=True)
    ck("并入演练:报出会并几条,但不写", 演["条数"] == 1 and 真值(case["T-检查-改判-甲"]) is None, 演)
    写 = RL.并入(db=db, 演练=False)
    ck("并入:已采用的写进 truth(标人工改判),研判标已并入、进了评测集",
       真值(case["T-检查-改判-甲"]) == (选[0]["root_cause"], "人工改判")
       and 行(研["T-检查-改判-甲"]) == ("已并入", 1), (真值(case["T-检查-改判-甲"]), 行(研["T-检查-改判-甲"])))
    ck("并入时那一单已有建库标注且不一致 → 不覆盖,列进冲突",
       真值(case["T-检查-改判-乙"]) == (选[1]["root_cause"], "建库标注")
       and [x["triage_id"] for x in 写["冲突"]] == [研["T-检查-改判-乙"]], (真值(case["T-检查-改判-乙"]), 写))
shutil.rmtree(tmp, ignore_errors=True)

页 = open(os.path.join(ROOT, "agentsite", "web", "queue.html"), encoding="utf-8").read()
ck("页面不再说那句不成立的「回归时会单独统计通过率」", "回归时会单独统计通过率" not in 页 and "不会直接进评测集" in 页)
ck("页面:改判候选有采用 / 驳回,走 /api/ops-relabel-review", "function 改判审核块(" in 页
   and '"/api/ops-relabel-review"' in 页 and 'data-s="改判待审"' in 页)
p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "merge_relabels.py"), "--写人"],
                   capture_output=True, text=True)
ck("并入脚本:参数拼错拒跑(不会悄悄按演练或写入跑)", p.returncode != 0 and "不认识" in (p.stderr + p.stdout), p.returncode)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 改判先审核:进候选、总部运营审、不能自审、并入才进评测集、不覆盖建库标注(验了 {n} 条){D}")
