# -*- coding: utf-8 -*-
"""退款执行的写口 —— 财务重新发起、登记已退、登记仍失败(用户 2026-10-15 拍)。

## 为什么要有它

研判队列的闭环是「进队列 → 研判 → 店长复核 → **财务执行** → 回执核验 → 办结」。
数据工厂 10-15 查出:**第五步在系统里没有写的地方** —— 回执核验要押金单是「已退」,
而能把一笔退款失败改成已退的,只有后台通用改状态那一下:**任何登录的人点一下就成「已退」,
什么凭据都不要**。那样的「已退」拿去办结,办结也就成了凭空点出来的。

## 最怕的是重复退款

三种真实情况,处理完全不同(数据工厂造的 DQ9001-9003 正好各一种):

  渠道超时、钱其实已经退了   → **不许再发**,财务向渠道核实后直接「登记已退」(带渠道退款流水号)
  原支付渠道已注销           → 线下转账等方式退,退完「登记已退」(方式写清)
  商户余额不足               → 补足后「重新发起」,渠道结果回来再登记

所以「重新发起」必须先说清上次是哪一种:「确实没退成」才能发;
「核实其实已退」不发新请求 —— 紧接着登记已退。闸在状态机上(fsm 的 bk-deposit),这里不自己判。

## 谁能做

退押金复核(2026-10-16):店长;≥1000 再加财务;发起人不能复核自己发起的。其余步骤**只有财务**。身份由调用方从会话给(接口层),这里不读请求体里的角色。
**不进智能体的工具表** —— 动钱的事,AI 出建议、人签字、财务执行。

## 凭据

「已退」必须带**渠道退款流水号**,存进 `refund_trace.refund_no`;
**同一个流水号不许出现在两笔单上**(唯一索引,结构上做不到,不靠这里查一遍)。
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
sys.path.insert(0, HERE)
from oplog import log_op

财务 = "财务"
店长 = "店长"
方式们 = ("原渠道退回", "渠道核实其实已退", "线下转账", "其他(写明)")
上次们 = ("确实没退成", "核实其实已退")

咬合 = []   # 由 refund_write_check.py 守


def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    建表(c)
    return c


def 建表(c):
    """refund_trace 补 refund_no 列 + **唯一索引**(同一流水号不许登记到两笔单上)。"""
    if "refund_no" not in {r[1] for r in c.execute("PRAGMA table_info(refund_trace)")}:
        c.execute("ALTER TABLE refund_trace ADD COLUMN refund_no TEXT")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_refund_no ON refund_trace(refund_no) "
              "WHERE refund_no IS NOT NULL")
    # 退押金的发起和复核(用户 2026-10-16 拍「真的两个人点」):一行一个人一步,
    # 同一笔同一步只能有一行 —— 两个店长同时点复核,后到的撞唯一约束
    c.execute("""CREATE TABLE IF NOT EXISTS refund_approval(deposit_id TEXT, step TEXT, by_no TEXT,
                 by_name TEXT, by_role TEXT, ts TEXT, note TEXT, UNIQUE(deposit_id, step))""")


def _now():
    """世界的当下 —— refund_trace.ts 会被平移,必须用世界时钟。"""
    import worldclock
    return worldclock.当下().strftime("%Y-%m-%d %H:%M")


def _deny(me, did, code, reason):
    log_op((me or {}).get("name") or "未登录", "bk-deposit", did or "—", "—", "—", False, code,
           reason[:200], {"role": (me or {}).get("role"), "no": (me or {}).get("no")})
    return dict(ok=False, code=code, reason=reason)


def _单(c, did):
    r = c.execute("SELECT * FROM deposit WHERE id=?", (did,)).fetchone()
    末 = c.execute("SELECT MAX(attempt) n, MAX(ts) t FROM refund_trace WHERE deposit_id=?", (did,)).fetchone()
    return r, (末["n"] or 0), 末["t"]


def _时刻(末时刻):
    """登记的时刻**不许早于上一次尝试** —— 演示世界的「今天」是一整天已经过完的数据(数据工厂 10-15 栽过:
    报修时间早于订单完成)。早于就拒,不替人编一个时间。"""
    t = _now()
    # 只拒**早于**:时刻只到分钟,同一分钟里先重发、再登记结果是正常的(第一版写成 <=,检查第一次跑就抓到)
    if 末时刻 and t < str(末时刻)[:16]:
        return None, f"现在({t})早于上一次退款尝试({str(末时刻)[:16]}),先后对不上 —— 不登记,免得记出一条倒着走的退款轨迹"
    return t, None


def _走(c, did, frm, to, ctx):
    import fsm
    ok, code, why = fsm.check("bk-deposit", frm, to, ctx)
    if not ok:
        return False, code, why
    n = c.execute("UPDATE deposit SET status=?, updated=? WHERE id=? AND status=?",
                  (to, ctx["_ts"], did, frm)).rowcount
    if n != 1:
        return False, "RACE", "这笔押金的状态刚被别人改了,请刷新再看"
    return True, "OK", ""


def 重新发起(deposit_id, me, 上次, 渠道="微信支付"):
    """退款失败 → 退款处理中。**上次 必须是「确实没退成」**(核实其实已退的走 登记已退)。"""
    me = me or {}
    if me.get("role") != 财务:
        return _deny(me, deposit_id, "WRONG_ROLE", f"只有财务能重新发起退款,你是「{me.get('role') or '未登录'}」")
    if 上次 != "确实没退成":
        return _deny(me, deposit_id, "NEED_VERIFY",
                     "重新发起前要先向渠道核实:上次**确实没退成**才能再发 —— 渠道超时而钱已到账的,别重发,直接「登记已退」")
    with _c() as c:
        d, n, 末 = _单(c, deposit_id)
        if not d:
            return _deny(me, deposit_id, "NO_DEPOSIT", f"没有押金单 {deposit_id}")
        t, 错 = _时刻(末)
        if 错:
            return _deny(me, deposit_id, "TIME_ORDER", 错)
        幂等 = f"IDEM-{deposit_id}-R{n + 1}"
        ok, code, why = _走(c, deposit_id, d["status"], "退款处理中",
                           dict(role=me.get("role"), 上次=上次, idem_key=幂等, retries=n, amount=d["amount"], _ts=t))
        if not ok:
            c.rollback()
            return _deny(me, deposit_id, code, why)
        c.execute("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key) "
                  "VALUES(?,?,?,?,?,'PENDING',?,?)",
                  (deposit_id, n + 1, t, 渠道, d["amount"], f"财务 {me.get('name')} 重新发起(已核实上次确实没退成)", 幂等))
    log_op(me.get("name"), "bk-deposit", deposit_id, d["status"], "退款处理中", True, "REFUND_RETRY",
           f"财务重新发起,第 {n + 1} 次,幂等号 {幂等}", {"role": me.get("role"), "no": me.get("no")})
    return dict(ok=True, 押金单=deposit_id, 状态="退款处理中", 第几次=n + 1, 幂等号=幂等,
                说明="演示世界没有真实渠道:请求已记为处理中。渠道结果回来后用「登记已退」或「登记仍失败」登记。")


def 登记已退(deposit_id, me, 退款流水号, 方式, 备注=""):
    """→ 已退,必带渠道退款流水号。

    从「退款处理中」来:正常的结果回来了。
    从「退款失败」来:**核实其实已退**(渠道超时而钱已到账)或线下退完 —— 同一个事务里先过
    「退款失败 → 退款处理中」(带 上次=核实其实已退,**不发新请求**),再进「已退」。不新加状态机的边
    (状态机来自标准答案集,不为了方便改它)。"""
    me = me or {}
    no = str(退款流水号 or "").strip()
    if me.get("role") != 财务:
        return _deny(me, deposit_id, "WRONG_ROLE", f"只有财务能登记已退,你是「{me.get('role') or '未登录'}」")
    if not no:
        return _deny(me, deposit_id, "NEED_REFUND_NO", "登记已退必须填渠道退款流水号")
    if 方式 not in 方式们:
        return _deny(me, deposit_id, "BAD_WAY", f"怎么退的只能是 {方式们} 之一")
    if 方式 == "其他(写明)" and not str(备注 or "").strip():
        return _deny(me, deposit_id, "BAD_WAY", "选了「其他」就要写明是怎么退的")
    c = _c()
    try:
        d, n, 末 = _单(c, deposit_id)
        if not d:
            return _deny(me, deposit_id, "NO_DEPOSIT", f"没有押金单 {deposit_id}")
        if c.execute("SELECT 1 FROM refund_trace WHERE refund_no=?", (no,)).fetchone():
            return _deny(me, deposit_id, "DUP_REFUND_NO", f"流水号 {no} 已经登记在别的退款上 —— 一笔流水不能证明两笔退款")
        t, 错 = _时刻(末)
        if 错:
            return _deny(me, deposit_id, "TIME_ORDER", 错)
        原 = d["status"]
        if 原 == "退款失败":
            ok, code, why = _走(c, deposit_id, "退款失败", "退款处理中",
                               dict(role=me.get("role"), 上次="核实其实已退", idem_key=f"IDEM-{deposit_id}-核实",
                                    retries=n, amount=d["amount"], _ts=t))
            if not ok:
                c.rollback(); return _deny(me, deposit_id, code, why)
        elif 原 != "退款处理中":
            return _deny(me, deposit_id, "BAD_FROM", f"押金单 {deposit_id} 现在是「{原}」,只有「退款处理中」或「退款失败」能登记已退")
        ok, code, why = _走(c, deposit_id, "退款处理中", "已退",
                           dict(role=me.get("role"), 退款流水号=no, amount=d["amount"], _ts=t))
        if not ok:
            c.rollback(); return _deny(me, deposit_id, code, why)
        try:
            c.execute("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key,refund_no) "
                      "VALUES(?,?,?,?,?,'SUCCESS',?,?,?)",
                      (deposit_id, n + 1, t, 方式, d["amount"],
                       f"财务 {me.get('name')} 登记已退({方式}){(' · ' + 备注) if 备注 else ''}"[:200],
                       f"IDEM-{deposit_id}-登记", no))
        except sqlite3.IntegrityError:
            # 两人同时用同一个流水号:上面那一查都没查到,唯一索引在这儿拦住后到的那个
            c.rollback()
            return _deny(me, deposit_id, "DUP_REFUND_NO", f"流水号 {no} 刚被登记在别的退款上")
        c.commit()
    finally:
        c.close()
    log_op(me.get("name"), "bk-deposit", deposit_id, 原, "已退", True, "REFUND_DONE",
           f"财务登记已退({方式}),渠道退款流水号 {no}", {"role": me.get("role"), "no": me.get("no")})
    return dict(ok=True, 押金单=deposit_id, 状态="已退", 从=原, 退款流水号=no, 方式=方式,
                说明="已退。研判队列里这一单现在可以用押金单号当回执办结了。")


def 登记仍失败(deposit_id, me, 原因):
    """退款处理中 → 退款失败,必写原因(渠道回来的错)。"""
    me = me or {}
    if me.get("role") != 财务:
        return _deny(me, deposit_id, "WRONG_ROLE", f"只有财务能登记退款结果,你是「{me.get('role') or '未登录'}」")
    if not str(原因 or "").strip():
        return _deny(me, deposit_id, "NEED_REASON", "登记仍失败要写渠道回来的原因")
    with _c() as c:
        d, n, 末 = _单(c, deposit_id)
        if not d:
            return _deny(me, deposit_id, "NO_DEPOSIT", f"没有押金单 {deposit_id}")
        t, 错 = _时刻(末)
        if 错:
            return _deny(me, deposit_id, "TIME_ORDER", 错)
        ok, code, why = _走(c, deposit_id, d["status"], "退款失败", dict(role=me.get("role"), _ts=t))
        if not ok:
            c.rollback()
            return _deny(me, deposit_id, code, why)
        c.execute("UPDATE refund_trace SET resp_code='FAIL', resp_msg=? WHERE deposit_id=? AND attempt=? AND resp_code='PENDING'",
                  (f"财务 {me.get('name')} 登记仍失败:{原因}"[:200], deposit_id, n))
    log_op(me.get("name"), "bk-deposit", deposit_id, "退款处理中", "退款失败", True, "REFUND_FAIL",
           f"财务登记仍失败:{原因}"[:200], {"role": me.get("role"), "no": me.get("no")})
    return dict(ok=True, 押金单=deposit_id, 状态="退款失败", 说明="已登记仍失败。")


def 记发起(c, deposit_id, me, ts, note=""):
    """「已付 → 退款审批中」成功那一刻记下发起人(server.transit 在同一个事务里调)。
    复核时拿它比:**发起人不能复核自己发起的那一笔**。"""
    c.execute("INSERT OR REPLACE INTO refund_approval(deposit_id,step,by_no,by_name,by_role,ts,note) "
              "VALUES(?,?,?,?,?,?,?)", (deposit_id, "发起", me.get("no"), me.get("name"), me.get("role"), ts, note or ""))


def _复核情况(c, deposit_id):
    """{步: 工号} —— 状态机的 店长复核 / 财务复核 只从这里现算,请求体里写的一概不认。"""
    return {r["step"]: r["by_no"] for r in c.execute(
        "SELECT step, by_no FROM refund_approval WHERE deposit_id=?", (deposit_id,))}


def 复核(deposit_id, me, 意见="", 结论="通过"):
    """退押金复核(用户 2026-10-16 拍「真的两个人点」)。

    店长点一次;单笔 ≥1000 财务再点一次;**发起人不能复核自己发起的,同一个人不能占两步**。
    最后一个该点的人点完,在同一个事务里进「退款处理中」并记一条处理中的退款请求 ——
    「都点完才真正退款」,中间没有谁能单独把钱送出去。
    结论=驳回:回到「已付」(钱没动),已有的复核记录清掉,要退得重新发起。"""
    me = me or {}
    步 = {店长: "店长复核", 财务: "财务复核"}.get(me.get("role"))
    if not 步:
        return _deny(me, deposit_id, "WRONG_ROLE", f"退押金复核只有店长、财务能做,你是「{me.get('role') or '未登录'}」")
    if 结论 not in ("通过", "驳回"):
        return _deny(me, deposit_id, "BAD_VERDICT", "复核结论只能是「通过」或「驳回」")
    if 结论 == "驳回" and not str(意见 or "").strip():
        return _deny(me, deposit_id, "NEED_REASON", "驳回要写理由")
    c = _c()
    try:
        d, n, 末 = _单(c, deposit_id)
        if not d:
            return _deny(me, deposit_id, "NO_DEPOSIT", f"没有押金单 {deposit_id}")
        if d["status"] != "退款审批中":
            return _deny(me, deposit_id, "BAD_FROM", f"押金单 {deposit_id} 现在是「{d['status']}」,只有「退款审批中」要复核")
        已 = _复核情况(c, deposit_id)
        要财务 = (d["amount"] or 0) >= 1000
        if 步 == "财务复核" and not 要财务:
            return _deny(me, deposit_id, "NOT_NEEDED", f"这笔 ¥{d['amount']:,.2f} 不到 1000,不需要财务复核,店长复核就够")
        if 已.get(步):
            return _deny(me, deposit_id, "ALREADY", f"这笔的{步}已经有人做过了")
        if 已.get("发起") and 已["发起"] == me.get("no"):
            return _deny(me, deposit_id, "SELF_APPROVE", "这笔是你发起的,不能自己复核 —— 钱要出门就要两个人")
        if me.get("no") in {v for k, v in 已.items() if k != "发起"}:
            return _deny(me, deposit_id, "SELF_APPROVE", "你已经复核过这笔的另一步,同一个人不能占两步")
        t = _now()
        if 结论 == "驳回":
            n1 = c.execute("UPDATE deposit SET status='已付', updated=? WHERE id=? AND status='退款审批中'",
                           (t, deposit_id)).rowcount
            if n1 != 1:
                c.rollback(); return _deny(me, deposit_id, "RACE", "这笔押金的状态刚被别人改了,请刷新再看")
            c.execute("DELETE FROM refund_approval WHERE deposit_id=?", (deposit_id,))
            c.commit()
            log_op(me.get("name"), "bk-deposit", deposit_id, "退款审批中", "已付", True, "REFUND_REJECT",
                   f"{步}驳回:{意见}"[:200], {"role": me.get("role"), "no": me.get("no")})
            return dict(ok=True, 押金单=deposit_id, 状态="已付", reason="已驳回,押金回到「已付」,要退得重新发起。")
        try:
            c.execute("INSERT INTO refund_approval(deposit_id,step,by_no,by_name,by_role,ts,note) VALUES(?,?,?,?,?,?,?)",
                      (deposit_id, 步, me.get("no"), me.get("name"), me.get("role"), t, 意见 or ""))
        except sqlite3.IntegrityError:
            c.rollback(); return _deny(me, deposit_id, "ALREADY", f"这笔的{步}刚被别人做了")
        已[步] = me.get("no")
        齐 = 已.get("店长复核") and (已.get("财务复核") or not 要财务)
        状态 = "退款审批中"
        if 齐:
            幂等 = f"IDEM-{deposit_id}-A"
            ok, code, why = _走(c, deposit_id, "退款审批中", "退款处理中",
                               dict(店长复核=已.get("店长复核"), 财务复核=已.get("财务复核"), idem_key=幂等,
                                    retries=n, amount=d["amount"], _ts=t))
            if not ok:
                c.rollback(); return _deny(me, deposit_id, code, why)
            c.execute("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key) "
                      "VALUES(?,?,?,?,?,'PENDING',?,?)",
                      (deposit_id, n + 1, t, "微信支付", d["amount"], "复核齐了,发起退款", 幂等))
            状态 = "退款处理中"
        c.commit()
    finally:
        c.close()
    log_op(me.get("name"), "bk-deposit", deposit_id, "退款审批中", 状态, True, "REFUND_APPROVE",
           f"{步}通过{(':' + 意见) if 意见 else ''}"[:200], {"role": me.get("role"), "no": me.get("no")})
    还差 = [] if 齐 else (["店长复核"] if not 已.get("店长复核") else []) + (["财务复核"] if 要财务 and not 已.get("财务复核") else [])
    return dict(ok=True, 押金单=deposit_id, 状态=状态, 还差=还差,
                reason="复核齐了,已发起退款(演示世界没有真实渠道,结果回来由财务登记)。" if 齐
                else f"已记下{步},还差:{'、'.join(还差)}。")


def 看(deposit_id):
    """押金单现在什么状态、退款轨迹 —— 只读,给研判弹窗的「退款处理」那一块用。"""
    with _c() as c:
        d = c.execute("SELECT id, customer_id, amount, status, updated FROM deposit WHERE id=?", (deposit_id,)).fetchone()
        if not d:
            return dict(error=f"没有押金单 {deposit_id}")
        tr = [dict(r) for r in c.execute(
            "SELECT attempt, ts, channel, resp_code, resp_msg, refund_no FROM refund_trace "
            "WHERE deposit_id=? ORDER BY attempt", (deposit_id,))]
        批 = [dict(r) for r in c.execute(
            "SELECT step, by_name, by_role, ts, note FROM refund_approval WHERE deposit_id=? ORDER BY ts", (deposit_id,))]
    return dict(押金单=d["id"], 金额=d["amount"], 状态=d["status"], 轨迹=tr, 复核=批,
                能做={"退款审批中": ["复核"], "退款失败": ["重新发起", "登记已退"],
                     "退款处理中": ["登记已退", "登记仍失败"]}.get(d["status"], []),
                方式们=list(方式们))

