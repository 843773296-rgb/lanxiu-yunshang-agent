#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判「在等顾客」· 检查 —— 在库的临时副本上跑,真库不动。

用户 2026-10-13 拍:等顾客回话**不停表**,但可以标「在等顾客」(写清等什么、留痕),
超时率**报两个数**:全部的、剔除在等顾客的。

要守的是两头:
  · 标了之后**「已超时」照算**(不停表)—— 否则标一下就能把超时藏起来;
  · 「剔除在等顾客」那个数**真的少了这一件** —— 否则标了等于没标,员工照样替顾客的拖延背锅。
以及:没写等什么不收、没身份 / 角色不对拒、销过账的不能标、成功被拒都留痕。

⚠️ 要验的形状**自己造**(副本上把一件事摆成「没销账、已超时」),不靠库里碰上的。
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agent")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("标了在等顾客就停表(已超时里剔掉它)", "标了之后「已超时」照算(不停表)"),
    ("剔除在等顾客的数不剔(和全部的一样)", "「剔除在等顾客」那个数真的少了这一件"),
    ("没写等什么也收", "没写等什么 → 不收"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


print("研判「在等顾客」· 检查(库的临时副本上跑,真库不动)")
print("=" * 80)
tmp = tempfile.mkdtemp(prefix="opswait-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
import ops, oplog
ops.DB = oplog.DB = db
c = sqlite3.connect(db); c.row_factory = sqlite3.Row


def 员工(角色):
    r = c.execute("SELECT no, name, role FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1", (角色,)).fetchone()
    return dict(r) if r else None


def 拒了吗(f):
    try:
        f(); return False
    except PermissionError:
        return True


店长, 财务, 顾问 = 员工("店长"), 员工("财务"), 员工("顾问")
t = c.execute("SELECT id FROM task WHERE type='财务人工任务' ORDER BY id LIMIT 1").fetchone()
ck("库里有财务人工任务和这几种在职员工(空集合上什么都成立)", bool(t and 店长 and 财务 and 顾问))
if t and 店长 and 财务 and 顾问:
    tid = t["id"]
    # 摆成「没销账、已超时」:研判清掉、工单开着、建单时间推到很久以前
    c.execute("DELETE FROM triage WHERE task_id=?", (tid,))
    c.execute("UPDATE task SET status='待处理', created='2000-01-01 00:00:00' WHERE id=?", (tid,)); c.commit()
    前 = ops.backlog()
    行 = [x for x in ops.queue() if x["task_id"] == tid]
    ck("自造的这件事:没销账、已超时", 行 and not 行[0]["done"] and 行[0]["level"] == "已超时", 行)
    ck("没写等什么 → 不收", ops.标等顾客(tid, "", 店长).get("code") == "NO_REASON")
    ck("不给身份 → 拒", 拒了吗(lambda: ops.标等顾客(tid, "等顾客寄回衣服", None)))
    ck("角色不对 → 拒(顾问标财务任务)", 拒了吗(lambda: ops.标等顾客(tid, "等顾客寄回衣服", 顾问)))
    r = ops.标等顾客(tid, "等顾客确认退款账户", 财务)
    ck("两段里任一段的人都能标(财务是办结那一段)", r.get("ok"), r)
    后 = ops.backlog()
    ck("标了之后「已超时」照算(不停表)", 后["已超时"] == 前["已超时"], (前["已超时"], 后["已超时"]))
    ck("「剔除在等顾客」那个数真的少了这一件",
       后["已超时_剔除在等顾客"] == 前["已超时_剔除在等顾客"] - 1, (前["已超时_剔除在等顾客"], 后["已超时_剔除在等顾客"]))
    ck("在等顾客的件数报出来了", 后["在等顾客"] == 前["在等顾客"] + 1)
    行 = [x for x in ops.queue() if x["task_id"] == tid]
    ck("队列上看得见等什么、谁标的", 行 and "等顾客确认退款账户" in (行[0]["在等顾客"] or "")
       and 财务["no"] in (行[0]["在等顾客"] or ""), 行 and 行[0]["在等顾客"])
    lg = c.execute("SELECT actor, allowed, code FROM op_log WHERE machine='task' AND target=? "
                   "ORDER BY rowid DESC LIMIT 1", (tid,)).fetchone()
    ck("标记写进 op_log,查得到是谁", lg and lg["code"] == "WAIT" and lg["allowed"] == 1 and 财务["no"] in lg["actor"],
       dict(lg) if lg else None)
    r = ops.标等顾客(tid, None, 店长, 取消=True)
    ck("能取消,取消后两个数回到原样", r.get("ok") and ops.backlog()["已超时_剔除在等顾客"] == 前["已超时_剔除在等顾客"], r)
    c.execute("UPDATE task SET status='已关闭' WHERE id=?", (tid,)); c.commit()
    ck("销过账的不能再标在等顾客", ops.标等顾客(tid, "等顾客寄回衣服", 店长).get("code") == "DONE")
c.close()
shutil.rmtree(tmp, ignore_errors=True)

# 接口层:身份只从登录态取(⚠️ 只验了文本,同 ops_resolve_check / ops_close_check 那条)
import re
src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
m = re.search(r'if p=="/api/ops-wait":(.*?)\n        if p==', src, re.S)
段 = m.group(1) if m else ""
ck("接口层:标在等顾客的身份只从登录态取(_me),没登录 401", bool(段) and "_me(self)" in 段 and "401" in 段
   and "handler" not in 段, 段[:200])

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 在等顾客:不停表、另报剔除数、要写等什么(验了 {n} 条){D}")
