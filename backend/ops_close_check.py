#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判「已办结」· 检查 —— 在库的临时副本上跑,真库不动。

用户 2026-10-13 拍:**已办结要凭业务回执,回执 = 按类型各认一种系统单号**
(定金单 / 维保单 / 差评按处理方式认售后单或维保单;客户合并现在进不了 —— 系统里没有执行合并)。

要守的不是「能不能标成已办结」,是**「凭一张没走完的单、或别人家的单,标不成」** ——
一个凭空点出来的已办结,和一个真办完的,在队列上长得一模一样。

⚠️ **要攻击的形状全部自己造**(save_triage 走正门 + 在副本上摆单据状态),不读库里碰上的:
CI 上没有模型凭据、triage 表恒空 —— 靠碰上的样本,这条检查在 CI 上永远验不到
(10-13 销账那条就是这么本地绿、CI 红的)。
"""
import os, re, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agent")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("回执不查单据状态(没退成的定金也认)", "定金还没退成 → 办结不了"),
    ("差评回执不查是不是同一张订单", "差评:别的订单的售后单 → 办结不了"),
    ("办结时把复核结论改写成「已办结」", "办结后复核结论不变(还是已采纳),回执另记"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


print("研判已办结 · 检查(库的临时副本上跑,真库不动)")
print("=" * 80)
tmp = tempfile.mkdtemp(prefix="opsclose-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
import ops, oplog
ops.DB = oplog.DB = db
c = sqlite3.connect(db); c.row_factory = sqlite3.Row


def 员工(角色):
    r = c.execute("SELECT no, name, role FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1", (角色,)).fetchone()
    return dict(r) if r else None


def 任务(类型):
    return c.execute("SELECT id, ref_id FROM task WHERE type=? ORDER BY id LIMIT 1", (类型,)).fetchone()


def 造采纳(类型, 谁):
    """自己造一条研判并按对的角色采纳 → 返回 triage id。"""
    t = 任务(类型)
    if not t:
        return None, None
    tid = ops.save_triage(t["id"], "检查", "检查", "根因:检查造的\n建议动作:检查造的\n证据:无", [])
    ops.resolve(tid, "已采纳", 谁, 来源="检查")
    return tid, t


def 拒了吗(f):
    try:
        f(); return False
    except PermissionError:
        return True


def 状态(tid):
    return c.execute("SELECT status, receipt, receipt_kind FROM triage WHERE id=?", (tid,)).fetchone()


店长, 财务, 售后, 顾问, 总部 = 员工("店长"), 员工("财务"), 员工("售后"), 员工("顾问"), 员工("总部运营")
ck("库里有这几种在职员工(空集合上什么都成立)", all((店长, 财务, 售后, 顾问, 总部)))
ck("对照表盖住了差评处理方式枚举的每一档(新加一档要人定认什么单)", ops.回执对照没漏() == [], ops.回执对照没漏())

# ── 财务人工任务:认定金单,状态「已退」──────────────────────────────
tid, t = 造采纳("财务人工任务", 财务)
ck("造得出一条已采纳的财务任务研判", bool(tid))
if tid:
    dep = t["ref_id"]
    ck("不给身份办结 → 拒", 拒了吗(lambda: ops.办结(tid, dep, None)))
    ck("拿错角色办结 → 拒(顾问办财务任务)", 拒了吗(lambda: ops.办结(tid, dep, 顾问)))
    c.execute("UPDATE deposit SET status='退款失败' WHERE id=?", (dep,)); c.commit()
    r = ops.办结(tid, dep, 财务)
    ck("定金还没退成 → 办结不了", r.get("code") == "NO_RECEIPT" and not 状态(tid)["receipt"], r)
    c.execute("UPDATE deposit SET status='已退' WHERE id=?", (dep,)); c.commit()
    r = ops.办结(tid, "D-别人家的", 财务)
    ck("回执单号不是这件事挂的那笔定金 → 办结不了", r.get("code") == "NO_RECEIPT", r)
    r = ops.办结(tid, dep, 财务)
    s = 状态(tid)
    ck("定金已退 + 单号对 → 已办结", r.get("ok") and s["receipt"] == dep and s["receipt_kind"] == "定金单", r)
    ck("办结后复核结论不变(还是已采纳),回执另记", s["status"] == "已采纳", dict(s))
    lg = c.execute("SELECT actor, allowed, code FROM op_log WHERE machine='triage' AND target=? "
                   "ORDER BY rowid DESC LIMIT 1", (f"triage#{tid}",)).fetchone()
    ck("办结写进 op_log,查得到是谁", lg and lg["code"] == "CLOSE" and lg["allowed"] == 1
       and 财务["no"] in lg["actor"], dict(lg) if lg else None)
    ck("同一条再办结 → 拒(不重复记)", ops.办结(tid, dep, 财务).get("code") == "ALREADY")
    行 = [x for x in ops.queue() if x.get("triage_id") == tid]
    ck("队列上看得见「已办结」和回执", 行 and 行[0]["已办结"] and dep in (行[0]["回执"] or ""), 行)

# ── 待复核的不能办结 ──────────────────────────────────────────────
t2 = 任务("财务人工任务")
if t2:
    tid2 = ops.save_triage(t2["id"], "检查", "检查", "根因:检查造的", [])
    ck("待复核的研判 → 先复核,不能直接办结", ops.办结(tid2, t2["ref_id"], 财务).get("code") == "BAD_STATE")

# ── 售后判责:认维保单,状态「已完成」──────────────────────────────
tid, t = 造采纳("售后判责", 售后)
ck("造得出一条已采纳的售后判责研判", bool(tid))
if tid:
    mw = t["ref_id"]
    c.execute("UPDATE maintain SET status='处理中' WHERE id=?", (mw,)); c.commit()
    ck("维保单还在处理中 → 办结不了", ops.办结(tid, mw, 售后).get("code") == "NO_RECEIPT")
    c.execute("UPDATE maintain SET status='已完成' WHERE id=?", (mw,)); c.commit()
    ck("维保单已完成 → 已办结", ops.办结(tid, mw, 售后).get("ok"))

# ── 评价差评:按处理方式认单,而且必须是同一张订单的 ──────────────────
tid, t = 造采纳("评价差评", 店长)
ck("造得出一条已采纳的差评研判", bool(tid))
if tid:
    pkg = t["ref_id"]
    单 = c.execute("SELECT order_id FROM rating WHERE pkg_id=?", (pkg,)).fetchone()
    ck("这条差评挂得上订单", bool(单 and 单[0]))
    oid = 单[0] if 单 else None
    c.execute("INSERT INTO aftersale(id, kind, order_id, status) VALUES('CHK-AS-同单','退货退款',?,'已完成')", (oid,))
    c.execute("INSERT INTO aftersale(id, kind, order_id, status) VALUES('CHK-AS-别单','退货退款','CHK-别的订单','已完成')")
    c.execute("INSERT INTO maintain(id, order_id, status) VALUES('CHK-MW-同单',?,'已完成')", (oid,))
    c.execute("UPDATE rating SET handle_way='免运费' WHERE pkg_id=?", (pkg,)); c.commit()
    ck("差评处理方式是免运费 → 没有对应单据,停在已采纳",
       ops.办结(tid, "CHK-AS-同单", 店长).get("code") == "NO_RECEIPT")
    c.execute("UPDATE rating SET handle_way='部分退款' WHERE pkg_id=?", (pkg,)); c.commit()
    ck("差评:别的订单的售后单 → 办结不了", ops.办结(tid, "CHK-AS-别单", 店长).get("code") == "NO_RECEIPT")
    ck("差评退款却拿维保单当回执 → 办结不了", ops.办结(tid, "CHK-MW-同单", 店长).get("code") == "NO_RECEIPT")
    r = ops.办结(tid, "CHK-AS-同单", 店长)
    ck("差评退款 + 同一张订单的已完成售后单 → 已办结", r.get("ok") and r.get("回执类型") == "售后单", r)

# ── 客户合并:系统里没有执行合并,现在一条都办结不了 ──────────────────
tid, t = 造采纳("客户合并确认", 总部)
if tid:
    r = ops.办结(tid, "随便什么单号", 总部)
    ck("客户合并确认 → 现在进不了已办结(执行合并还没做)", r.get("code") == "NO_RECEIPT"
       and "执行合并" in r.get("reason", ""), r)
c.close()
shutil.rmtree(tmp, ignore_errors=True)

# ── 接口层:身份只从登录态取(⚠️ 只验了文本,同 ops_resolve_check 那条)──────
src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
m = re.search(r'if p=="/api/ops-close":(.*?)\n        if p==', src, re.S)
段 = m.group(1) if m else ""
ck("接口层:办结身份只从登录态取(_me),没登录 401", bool(段) and "_me(self)" in 段 and "401" in 段
   and "handler" not in 段, 段[:200])

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 已办结只认真走完的回执(验了 {n} 条){D}")
