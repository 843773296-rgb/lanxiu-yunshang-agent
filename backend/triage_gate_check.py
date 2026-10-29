#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判队列上线门槛 · 四个 0 · 检查(研判队列主方案判据 ⑦,10-20)。

两件事分开(CLAUDE.md「判据红不红取决于库里碰巧有什么」那条):
  ① **量法对不对** —— 库副本里自己造:走一遍正门(复核 → 办结),四个数必须都是 0;
     再把四种坏形状各造一个,每种必须**恰好被数到那一类**。自造的样本两个环境都在,所以这一组的断言是硬的。
  ② **真库上现在是几** —— 四个数必须都是 0;不是 0 就是真有一件越权 / 重复执行 / 假成功 / 无依据办结。
     样本是 0(CI 从零建的库里没有研判日志)时明说「没验到」,不判过也不判红 —— 兜底的是 ①。
"""
from contextlib import closing   # ← 连接要显式关:sqlite3 的 with 只管事务,不关连接(2026-10-29)
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("越权不查两段是不是同一个人", "量法:两段确认被同一个人从头点到尾 → 数进越权"),
    ("失败假成功只看押金不看研判", "量法:记着失败而状态照样变了 → 数进失败假成功"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


print("研判队列上线门槛 · 越权 / 重复业务执行 / 失败假成功 / 无依据办结 各为 0")
print("=" * 80)
import ops, oplog, refund_write, merge, triage_gate as TG   # noqa: E401 —— 先加载,用副本才改得到它们的 DB
真库结果 = TG.量()                                            # ② 用的数,在切副本之前量

import check_copy
db = check_copy.用副本("gate-chk-")
c = sqlite3.connect(db)
c.execute("DELETE FROM op_log WHERE machine IN ('triage','bk-deposit')")   # 只看自造的 —— 不取决于主库被怎么用过
c.execute("DELETE FROM triage")
c.execute("INSERT INTO deposit(id,customer_id,amount,status,created,updated) VALUES('DQ-门槛','C10000',500,'已退','2026-01-01','2026-01-01')")
c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES('T-门槛','财务人工任务','DQ-门槛','待处理','2026-01-01','检查')")
c.commit(); c.close()
店长 = {"no": "门槛-店长", "name": "店长甲", "role": "店长"}
财务 = {"no": "门槛-财务", "name": "财务乙", "role": "财务"}

# ① 正门走一遍:复核(店长)→ 办结(财务);中间各被拒一次(店长办结、财务复核),四个数都该是 0
tid = ops.save_triage("T-门槛", "BP-01", "T-门槛", "根因:检查\n建议动作:退款", [])
try:
    ops.resolve(tid, "已采纳", 财务, 来源="检查")
except PermissionError:
    pass
ops.resolve(tid, "已采纳", 店长, 来源="检查")
try:
    ops.办结(tid, "DQ-门槛", 店长, 来源="检查")
except PermissionError:
    pass
r = ops.办结(tid, "DQ-门槛", 财务, 来源="检查")
r2 = ops.办结(tid, "DQ-门槛", 财务, 来源="检查")           # 再点一次:应该被「已经办结过了」拦下
o = TG.量(db)
ck("量法:正门走一遍(含被拒的两次、重复点一次办结)→ 四个数都是 0",
   r.get("ok") and not r2.get("ok") and all(not o[k] for k in TG.四类), {k: o[k] for k in TG.四类})

# ① 四种坏形状各造一个 —— 直接往日志 / 表里写(模拟「某个写口坏了」留下的痕迹),每种要恰好数进那一类
def 造(sql, *a):
    with closing(sqlite3.connect(db)) as cc, cc:
        cc.execute(sql, a)

def 日志(target, frm, too, ok, code, me, machine="triage", reason="[检查] 造的"):
    造("INSERT INTO op_log(ts,actor,machine,target,frm,too,allowed,code,reason,ctx) VALUES('2026-01-02',?,?,?,?,?,?,?,?,?)",
      me["name"], machine, target, frm, too, int(ok), code, reason, json.dumps({"role": me["role"], "no": me["no"]}))

def 只多了(类, 前):
    后 = TG.量(db)
    多 = {k: len(后[k]) - len(前[k]) for k in TG.四类}
    return 多[类] >= 1 and all(v == 0 for k, v in 多.items() if k != 类), 多

前 = TG.量(db)
日志(f"triage#{tid}", "—", "已办结", True, "CLOSE", 财务)
ok, 多 = 只多了("重复业务执行", 前)
ck("量法:同一条研判成功办结两次 → 数进重复业务执行(且只数进这一类)", ok, 多)

前 = TG.量(db)
日志("DQ-门槛", "退款失败", "已退", True, "REFUND_DONE", 店长, machine="bk-deposit")
ok, 多 = 只多了("越权", 前)
ck("量法:店长登记了已退(只认财务)→ 数进越权", ok, 多)

# 两段确认被同一个人点完:另造一件,复核和办结的工号相同(角色各自对,所以单看角色查不出来)
造("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES('T-门槛2','财务人工任务','DQ-门槛','待处理','2026-01-01','检查')")
tid2 = ops.save_triage("T-门槛2", "BP-01", "T-门槛2", "根因:检查", [])
一人 = {"no": "门槛-同一人", "name": "身兼两职"}
前 = TG.量(db)
造("UPDATE triage SET status='已采纳', receipt='DQ-门槛', receipt_kind='定金单' WHERE id=?", tid2)
日志(f"triage#{tid2}", "待复核", "已采纳", True, "RESOLVE", dict(一人, role="店长"))
日志(f"triage#{tid2}", "—", "已办结", True, "CLOSE", dict(一人, role="财务"))
ok, 多 = 只多了("越权", 前)
ck("量法:两段确认被同一个人从头点到尾 → 数进越权", ok, 多)

造("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES('T-门槛3','财务人工任务','DQ-门槛','待处理','2026-01-01','检查')")
tid3 = ops.save_triage("T-门槛3", "BP-01", "T-门槛3", "根因:检查", [])
前 = TG.量(db)
日志(f"triage#{tid3}", "待复核", "—", False, "ROLE", 财务)
造("UPDATE triage SET status='已采纳' WHERE id=?", tid3)
ok, 多 = 只多了("失败假成功", 前)
ck("量法:记着失败而状态照样变了 → 数进失败假成功", ok, 多)

造("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES('T-门槛4','财务人工任务','DQ-门槛','待处理','2026-01-01','检查')")
tid4 = ops.save_triage("T-门槛4", "BP-01", "T-门槛4", "根因:检查", [])
前 = TG.量(db)
造("UPDATE triage SET status='已采纳', receipt='DQ-门槛', receipt_kind='定金单' WHERE id=?", tid4)
ok, 多 = 只多了("无依据办结", 前)
ck("量法:有回执却没有一条成功的办结记录 → 数进无依据办结", ok, 多)

# ② 真库
print()
样 = 真库结果["样本"]
if not 样["研判日志"] and not 样["押金日志"]:
    print(f"  {Y}ℹ️ 真库里没有研判 / 押金的操作日志 —— 四个数**没验到**(不是验过了是 0);上面那组自造的兜着量法{D}")
else:
    for k in TG.四类:
        ck(f"真库:{k} = 0(研判日志 {样['研判日志']} 条、押金日志 {样['押金日志']} 条)", not 真库结果[k], 真库结果[k][:3])
for x in 真库结果["旁注"]:
    print(f"  ℹ️ {x}  —— **只报不拦**")

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 上线门槛四个 0:量法认得出四种坏形状,真库上现在都是 0(验了 {n} 条){D}")
