#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判队列「没走正门关的」· 检查 —— 库副本上自造形状 + 真库只读棘轮。

用户 2026-10-14 拍:队列里那批「工单关了、没走过研判」的按「**没走正门关的**」收起,**计数亮着不藏成 0**。
(原话是「把 166 条清掉」;核过之后定的是按事实判 —— 有没有一条**真实的**正门关单记录 —— 而不是按形状或时间。)

要守的:
  · 凭据要**真实**:走正门清理演示数据的那种(reason 带演示清理标记)**不算**复核 ——
    「有人复核了这条」和「有人清理了这条」在「有审计记录」上长得一模一样;
  · 研判过的、真走正门关的,不进这一档;
  · **只许少不许多**:这一档涨了就是正门又被绕过了(基线 166,2026-10-14)。
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0
基线 = 166        # 2026-10-14:全是造数直接写库造的;将来补了研判 / 真复核,这个数只会少

咬合 = [
    ("正门凭据不看 reason(演示清理也算复核)", "走正门清理演示数据的那种不算(reason 带演示清理标记)"),
    ("没走正门不查正门凭据", "真走正门关的不进这一档"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


print("研判队列「没走正门关的」· 检查")
print("=" * 80)

# ── 真库(只读):棘轮 + 计数亮着 ─────────────────────────────────────
import ops, oplog, rating as RT
真 = ops.backlog()["没走正门关的"]
print(f"     ℹ️ 真库里「没走正门关的」现在 {真} 条(基线 {基线})")
ck(f"只许少不许多:没走正门关的 {真} ≤ 基线 {基线}(涨了 = 正门又被绕过了)", 真 <= 基线, 真)

# ── 库副本:自造四种形状 ──────────────────────────────────────────────
tmp = tempfile.mkdtemp(prefix="qclosed-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
ops.DB = oplog.DB = db
c = sqlite3.connect(db)
造 = {}
for 名 in ("无凭据", "真正门", "清理正门", "研判过"):
    tid = f"T-检查-{名}"
    c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
              (tid, "评价差评", f"P-检查-{名}", "已关闭", "2026-01-01 10:00:00", "检查"))
    造[名] = tid
c.commit(); c.close()
from oplog import log_op
log_op("检查", "task", 造["真正门"], "待处理", "已关闭", True, "BAD_RATING_CLOSED", "只回访:电话回访过,顾客接受", {})
log_op("检查", "task", 造["清理正门"], "待处理", "已关闭", True, "BAD_RATING_CLOSED",
       f"只回访:{RT.演示清理标记}(检查造的),非真实复核", {})
ops.save_triage(造["研判过"], "BP-差评", "检查", "根因:检查", [])
行 = {x["task_id"]: x for x in ops.queue() if x["task_id"] in 造.values()}
ck("没研判、也查不到正门凭据 → 没走正门", 行[造["无凭据"]]["没走正门"] is True)
ck("真走正门关的不进这一档", 行[造["真正门"]]["没走正门"] is False)
ck("走正门清理演示数据的那种不算(reason 带演示清理标记)", 行[造["清理正门"]]["没走正门"] is True)
ck("研判过的不进这一档", 行[造["研判过"]]["没走正门"] is False)
ck("计数和逐行标记对得上", ops.backlog()["没走正门关的"] == sum(1 for x in ops.queue() if x.get("没走正门")))
shutil.rmtree(tmp, ignore_errors=True)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 没走正门关的:凭据要真实、只许少不许多(验了 {n} 条){D}")
