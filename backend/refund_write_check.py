#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""退款执行写口 · 检查 —— 库副本上自造押金单,把每一道门都真攻击一遍。

用户 2026-10-15 拍「登记退款结果」写口(登记已退 + 系统内重新发起)。
最怕的是**重复退款**(渠道超时而钱已到账,再发一次顾客收两笔)和**没凭据的「已退」**
(研判办结拿它当回执,凭空点出来的已退会让办结也成了凭空点出来的)。
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("重新发起不查「上次是哪种」(超时其实已退的也能再发一次)", "没说清上次是哪种,不许重新发起"),
    ("登记已退不要流水号", "登记已退不填流水号被拒"),
    ("流水号不查重(一笔流水证明两笔退款)", "同一个流水号登记到第二笔被拒"),
    ("通用改状态又能直接点成「已退」", "后台通用改状态点不出「已退」(指向退款写口)"),
    ("复核不看金额(≥1000 也不要财务)", "3000 的单另一位店长复核完还差财务(金额只认库里)"),
    ("复核不比发起人(自己发起自己复核)", "发起人不能复核自己发起的那一笔"),
    ("通用改状态又能把审批中直接点进退款处理中", "后台通用改状态点不过复核(指向退款写口)"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


print("退款执行写口 · 检查")
print("=" * 80)

import refund_write as RW, oplog, ops
import server as S
tmp = tempfile.mkdtemp(prefix="refund-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
_真 = (RW.DB, oplog.DB, ops.DB, S.DB)
RW.DB = oplog.DB = ops.DB = S.DB = db
try:
    c = sqlite3.connect(db)
    财 = c.execute("SELECT no, name, role FROM staff WHERE role='财务' AND status='启用' LIMIT 1").fetchone()
    店 = c.execute("SELECT no, name, role FROM staff WHERE role='店长' AND status='启用' LIMIT 1").fetchone()
    for i in (1, 2, 3, 4):
        did = f"R-检查-{i}"
        c.execute("INSERT INTO deposit(id,customer_id,amount,status,idem_key,created,updated) VALUES(?,?,?,?,?,?,?)",
                  (did, "C10000", 500.0, "退款失败", f"IDEM-{did}", "2026-01-01", "2026-01-01"))
        末 = "2099-01-01 00:00" if i == 4 else "2026-01-01 10:00"     # 第 4 笔:最后一次尝试在「未来」
        for a in (1, 2, 3):
            c.execute("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key) "
                      "VALUES(?,?,?,?,?,?,?,?)", (did, a, 末, "微信支付", 500.0, "TIMEOUT", "渠道响应超时", f"IDEM-{did}"))
    c.commit(); c.close()
    if not (财 and 店):
        ck("库里有在职财务和店长 —— 没有就没验,不算通过", False)
        raise SystemExit
    财务 = dict(no=财[0], name=财[1], role=财[2]); 店长 = dict(no=店[0], name=店[1], role=店[2])
    状态 = lambda d: sqlite3.connect(db).execute("SELECT status FROM deposit WHERE id=?", (d,)).fetchone()[0]
    轨迹 = lambda d: sqlite3.connect(db).execute(
        "SELECT attempt, resp_code, refund_no FROM refund_trace WHERE deposit_id=? ORDER BY attempt", (d,)).fetchall()

    # ── 谁能做 ──
    r = RW.登记已退("R-检查-1", 店长, "WX-检查-0", "原渠道退回")
    ck("店长登记已退被拒(只有财务)", not r["ok"] and r["code"] == "WRONG_ROLE", r)
    r = RW.重新发起("R-检查-1", 店长, "确实没退成")
    ck("店长重新发起被拒(只有财务)", not r["ok"] and r["code"] == "WRONG_ROLE", r)

    # ── 重新发起:先说清上次是哪种 ──
    r = RW.重新发起("R-检查-1", 财务, None)
    ck("没说清上次是哪种,不许重新发起", not r["ok"] and r["code"] == "NEED_VERIFY" and 状态("R-检查-1") == "退款失败", r)
    r = RW.重新发起("R-检查-1", 财务, "确实没退成")
    ck("财务核实「确实没退成」后能重新发起(自动重试满 3 次也不拦财务)",
       r.get("ok") and 状态("R-检查-1") == "退款处理中" and 轨迹("R-检查-1")[-1][:2] == (4, "PENDING"), r)
    r = RW.登记仍失败("R-检查-1", 财务, "商户余额不足")
    ck("登记仍失败:回到退款失败,那一次尝试记成 FAIL",
       r.get("ok") and 状态("R-检查-1") == "退款失败" and 轨迹("R-检查-1")[-1][1] == "FAIL", r)

    # ── 登记已退:必须有流水号,不发新请求 ──
    r = RW.登记已退("R-检查-2", 财务, "", "渠道核实其实已退")
    ck("登记已退不填流水号被拒", not r["ok"] and r["code"] == "NEED_REFUND_NO" and 状态("R-检查-2") == "退款失败", r)
    r = RW.登记已退("R-检查-2", 财务, "WX-检查-1", "渠道核实其实已退")
    t2 = 轨迹("R-检查-2")
    ck("核实其实已退:直接登记已退,带上流水号,**中间没有发新的退款请求**",
       r.get("ok") and 状态("R-检查-2") == "已退" and t2[-1] == (4, "SUCCESS", "WX-检查-1")
       and not any(x[1] == "PENDING" for x in t2), (r, t2))
    r = RW.登记已退("R-检查-3", 财务, "WX-检查-1", "线下转账")
    ck("同一个流水号登记到第二笔被拒", not r["ok"] and r["code"] == "DUP_REFUND_NO" and 状态("R-检查-3") == "退款失败", r)
    r = RW.登记已退("R-检查-2", 财务, "WX-检查-2", "原渠道退回")
    ck("已退的不能再登记一次", not r["ok"] and 状态("R-检查-2") == "已退", r)

    # ── 时间先后 ──
    r = RW.登记已退("R-检查-4", 财务, "WX-检查-4", "原渠道退回")
    ck("登记时刻早于上一次尝试的被拒(不编时间)", not r["ok"] and r["code"] == "TIME_ORDER" and 状态("R-检查-4") == "退款失败", r)

    # ── 通用改状态绕不过去 ──
    r = S.transit("bk-deposit", "R-检查-3", "退款处理中", {"idem_key": "IDEM-x", "上次": "确实没退成"}, actor=财务["name"], me=财务)
    ck("后台通用改状态点不出「已退」(指向退款写口)", not r.get("ok") and r.get("code") == "USE_REFUND_WRITE"
       and 状态("R-检查-3") == "退款失败", r)
    r = S.transit("bk-deposit", "R-检查-3", "退款处理中", {"idem_key": "IDEM-x", "role": "财务", "上次": "确实没退成"},
                  actor=店长["name"], me=店长)
    ck("请求体里自报「财务」不算数(角色从会话取)", not r.get("ok") and 状态("R-检查-3") == "退款失败", r)

    # ── 退押金复核:真的两个人点(用户 10-16 拍)──
    cx = sqlite3.connect(db)
    店长们 = cx.execute("SELECT no, name, role FROM staff WHERE role='店长' AND status='启用' ORDER BY no LIMIT 2").fetchall()
    顾 = cx.execute("SELECT no, name, role FROM staff WHERE role='顾问' AND status='启用' LIMIT 1").fetchone()
    匠 = cx.execute("SELECT no, name, role FROM staff WHERE role='工匠' AND status='启用' LIMIT 1").fetchone()
    for did, amt in (("R-检查-5", 500.0), ("R-检查-6", 3000.0), ("R-检查-7", 500.0)):
        cx.execute("INSERT INTO deposit(id,customer_id,amount,status,idem_key,created,updated) VALUES(?,?,?,?,?,?,?)",
                   (did, "C10000", amt, "已付", f"IDEM-{did}", "2026-01-01", "2026-01-01"))
    cx.commit(); cx.close()
    if not (len(店长们) == 2 and 顾 and 匠):
        ck("库里有两位在职店长、一位顾问、一位工匠 —— 没有就没验,不算通过", False)
    else:
        甲, 乙 = (dict(no=x[0], name=x[1], role=x[2]) for x in 店长们)
        顾问 = dict(no=顾[0], name=顾[1], role=顾[2]); 工匠 = dict(no=匠[0], name=匠[1], role=匠[2])
        r = S.transit("bk-deposit", "R-检查-5", "退款审批中", {"role": "店长"}, actor=工匠["name"], me=工匠)
        ck("工匠发起退押金被拒(请求体自报店长也不算)", not r.get("ok") and 状态("R-检查-5") == "已付", r)
        r = S.transit("bk-deposit", "R-检查-5", "退款审批中", {"approved_by": "店长+财务"}, actor=顾问["name"], me=顾问)
        ck("顾问发起后停在审批中(下拉框里的「店长+财务」不算复核)", r.get("ok") and 状态("R-检查-5") == "退款审批中", r)
        r = S.transit("bk-deposit", "R-检查-5", "退款处理中", {"idem_key": "IDEM-x", "店长复核": 甲["no"]},
                      actor=甲["name"], me=甲)
        ck("后台通用改状态点不过复核(指向退款写口)", not r.get("ok") and r.get("code") == "USE_REFUND_WRITE"
           and 状态("R-检查-5") == "退款审批中", r)
        r = RW.复核("R-检查-5", 甲)
        ck("不到 1000 的,另一位店长复核完就进退款处理中,并记一条处理中的请求",
           r.get("ok") and 状态("R-检查-5") == "退款处理中" and 轨迹("R-检查-5")[-1][1] == "PENDING", r)

        r = S.transit("bk-deposit", "R-检查-6", "退款审批中", {"amount": 0}, actor=甲["name"], me=甲)
        ck("店长也能发起(请求体里的金额 0 不作数)", r.get("ok") and 状态("R-检查-6") == "退款审批中", r)
        r = RW.复核("R-检查-6", 甲)
        ck("发起人不能复核自己发起的那一笔", not r["ok"] and r["code"] == "SELF_APPROVE" and 状态("R-检查-6") == "退款审批中", r)
        r = RW.复核("R-检查-6", 乙)
        ck("3000 的单另一位店长复核完还差财务(金额只认库里)",
           r.get("ok") and 状态("R-检查-6") == "退款审批中" and r.get("还差") == ["财务复核"], r)
        r = RW.复核("R-检查-6", 乙)
        ck("同一步不能点两次", not r["ok"] and r["code"] == "ALREADY", r)
        r = RW.复核("R-检查-6", 财务)
        ck("财务再点,两步齐了才进退款处理中", r.get("ok") and 状态("R-检查-6") == "退款处理中", r)

        S.transit("bk-deposit", "R-检查-7", "退款审批中", {}, actor=顾问["name"], me=顾问)
        r = RW.复核("R-检查-7", 财务)
        ck("不到 1000 的财务不用点(不让财务替店长那一步)", not r["ok"] and r["code"] == "NOT_NEEDED"
           and 状态("R-检查-7") == "退款审批中", r)
        r = RW.复核("R-检查-7", 顾问)
        ck("顾问不能复核", not r["ok"] and r["code"] == "WRONG_ROLE", r)
        r = RW.复核("R-检查-7", 甲, "", "驳回")
        ck("驳回要写理由", not r["ok"] and r["code"] == "NEED_REASON" and 状态("R-检查-7") == "退款审批中", r)
        r = RW.复核("R-检查-7", 甲, "客户改约,不退了", "驳回")
        n批 = sqlite3.connect(db).execute("SELECT COUNT(*) FROM refund_approval WHERE deposit_id='R-检查-7'").fetchone()[0]
        ck("驳回回到已付,复核记录清掉(要退得重新发起)", r.get("ok") and 状态("R-检查-7") == "已付" and n批 == 0, (r, n批))

    # ── 闭环:已退之后,研判办结认它当回执 ──
    cx = sqlite3.connect(db); cx.row_factory = sqlite3.Row
    行, 类, 为什么 = ops.回执行不行(cx, {"type": "财务人工任务", "ref_id": "R-检查-2"}, "R-检查-2")
    cx.close()
    ck("登记已退之后,研判办结认这张押金单当回执", 行, 为什么)

    # ── 审计 ──
    ox = sqlite3.connect(db)
    记 = {r[0] for r in ox.execute("SELECT code FROM op_log WHERE machine='bk-deposit' AND target LIKE 'R-检查-%'")}
    ox.close()
    ck("成功和被拒都留了审计", {"REFUND_RETRY", "REFUND_DONE", "REFUND_FAIL", "WRONG_ROLE", "NEED_REFUND_NO",
                         "REFUND_APPROVE", "SELF_APPROVE", "REFUND_REJECT"} <= 记, sorted(记))
finally:
    RW.DB, oplog.DB, ops.DB, S.DB = _真
    shutil.rmtree(tmp, ignore_errors=True)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 退款执行:复核两个人点、只有财务执行、先核实再重发、已退要流水号且不重复、通用入口绕不过(验了 {n} 条){D}")
