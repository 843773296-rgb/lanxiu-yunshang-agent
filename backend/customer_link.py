#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顾客一次性链接 —— 顾客怎么证明「我是本人」(用户 2026-11-14 拍,台账第四十四条)。

导购给某一单发一条链接(短信 / 微信由导购自己转,系统不替他发),**只能用一次、7 天过期**。
顾客点开链接能做的只有链接上写明的那一件事:
    签收确认   定制单「待完成 → 完成」(「系统不能替顾客签」那条的前提:得是顾客自己点)
    追评       穿过之后的那句话(不带星,不改原来的评分;规则在 knowledge/rating.能不能追评)

## 为什么不是原来的「订单号 + 手机后四位」

后四位只有一万种,订单号又印在小票上 —— 拿到小票的人试几次就进去了,而且**试错不留痕**。
链接的令牌是 32 字节随机数(secrets.token_urlsafe),猜中的概率可以当成零;
**库里只存它的 SHA-256**,库被拷走也拿不到能用的链接(和试穿合身码只存哈希同一个理由)。

## 四条规矩,每条对着一个坏法

  · **只能用一次**:用的时候先「占」(UPDATE … WHERE used_at IS NULL,看改了几行),
    两个人同时点,只有一个占得到;事情没办成(比如订单状态不对)就把占位还回去,链接还能再用 ——
    否则顾客点一下遇到「还没到时候」,链接就废了,还得再找导购要
  · **7 天过期**:按**真实时钟**算 —— 链接是真实世界里的凭证,不跟着演示世界平移
    (这几列登记在 tools/shift_world.py 的「整列日期不挪」)
  · **同一单同一件事只留一条有效的**:重发会把旧的作废 —— 发错了人,重发一条旧的就不能用了
  · **对外只说一句话**:令牌不存在 / 过期 / 用过 / 作废,回顾客的都是同一句「链接已失效」——
    分开说等于告诉试的人「这个令牌存在过」。分别是什么记在操作台账里,导购查得到
"""
import hashlib, os, secrets, sqlite3, datetime as dt
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")

有效天数 = 7
用途们 = ("签收确认", "追评")
失效话 = "链接已失效(过期、用过或已重发)—— 请联系您的导购重新发一条"

DDL = """CREATE TABLE IF NOT EXISTS customer_link(
  token_hash TEXT PRIMARY KEY,     -- 令牌的 SHA-256;明文只在发出那一刻出现一次
  purpose    TEXT NOT NULL,        -- 签收确认 / 追评
  order_id   TEXT NOT NULL,
  pkg_id     TEXT,                 -- 追评按包裹(一个包裹追评一次);签收确认为空
  created_by TEXT NOT NULL,        -- 发链接的员工工号
  created_at TEXT NOT NULL,        -- 真实时钟(见文件头)
  expires_at TEXT NOT NULL,
  used_at    TEXT,
  void_at    TEXT)"""


def 建表(c):
    c.execute(DDL)


def _现在():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _指纹(token):
    return hashlib.sha256(str(token or "").encode()).hexdigest()


def _连():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def 发(d, me):
    """导购给一单发链接。→ dict(ok, 链接=/c/<令牌>, 有效到, …)。令牌明文**只在这里返回一次**。"""
    from oplog import log_op
    import shop_key as _SK
    谁 = (me or {}).get("name") or "?"; 角色 = (me or {}).get("role")
    oid = str(d.get("order_id") or "").strip(); 用途 = d.get("purpose") or ""
    def 拒(码, 为何):
        log_op(谁, "customer-link", oid or "?", "发链接", "拒绝", False, 码, 为何, {"role": 角色, "用途": 用途})
        return dict(ok=False, code=码, reason=为何)
    if not me: return 拒("NO_LOGIN", "请先登录")
    if 用途 not in 用途们: return 拒("BAD_PURPOSE", f"链接只能用来 {' / '.join(用途们)}")
    with closing(_连()) as c, c:
        建表(c)
        o = c.execute("SELECT id, status, kind, shop, shop_code FROM ordr WHERE id=?", (oid,)).fetchone()
        if not o: return 拒("NO_ORDER", f"没有订单 {oid}")
        if 角色 != "总部运营":
            我店 = _SK.码(c, me.get("shop"))
            if not 我店 or 我店 != (o["shop_code"] or _SK.码(c, o["shop"])):
                return 拒("OTHER_SHOP", "只能给本店的订单发链接")
        pkg = None
        if 用途 == "签收确认":
            if o["status"] != "待完成":
                return 拒("NOT_READY", f"这一单现在是「{o['status']}」—— 签收(试穿合身)之后、待完成时才发确认链接")
        else:
            pkg = str(d.get("pkg_id") or "").strip() or None
            评 = c.execute("SELECT pkg_id, followup_note FROM rating WHERE order_id=?" + (" AND pkg_id=?" if pkg else ""),
                          (oid, pkg) if pkg else (oid,)).fetchall()
            if not 评: return 拒("NO_RATING", "这一单还没有顾客评价 —— 追评是评价之后、穿过再说的那句话")
            if len(评) > 1 and not pkg:
                return 拒("WHICH_PKG", "这一单评过不止一个包裹,请选一个:" + "、".join(r["pkg_id"] for r in 评))
            if 评[0]["followup_note"]: return 拒("DONE", "这个包裹已经追评过了")
            pkg = 评[0]["pkg_id"]
            import rating_write as _rw
            能, 为何 = _rw.追评闸(pkg)          # 和顾客提交时同一道闸:别发一条注定用不了的链接
            if not 能: return 拒("CANNOT_FOLLOWUP", 为何)
        现 = _现在()
        # 同一单同一件事只留一条有效的:旧的未用链接作废
        废 = c.execute("UPDATE customer_link SET void_at=? WHERE order_id=? AND purpose=? AND COALESCE(pkg_id,'')=? "
                      "AND used_at IS NULL AND void_at IS NULL", (现, oid, 用途, pkg or "")).rowcount
        token = secrets.token_urlsafe(32)
        到 = (dt.datetime.now() + dt.timedelta(days=有效天数)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO customer_link(token_hash,purpose,order_id,pkg_id,created_by,created_at,expires_at) "
                  "VALUES(?,?,?,?,?,?,?)", (_指纹(token), 用途, oid, pkg, me.get("no"), 现, 到))
    log_op(谁, "customer-link", oid, "发链接", 用途, True, "ISSUE",
           f"{用途}{' · ' + pkg if pkg else ''} · 有效到 {到}" + (f" · 作废旧链接 {废} 条" if 废 else ""), {"role": 角色})
    return dict(ok=True, code="ISSUE", 链接=f"/c/{token}", 有效到=到, 用途=用途, 作废旧链接=废,
                reason=f"链接已生成,{有效天数} 天内有效、只能用一次 —— 由您转给顾客(系统不替您发)"
                       + (f";之前那条已作废" if 废 else ""))


def _找(c, token):
    """→ (行, 为什么不能用)。为什么只进台账,不回给顾客。"""
    r = c.execute("SELECT * FROM customer_link WHERE token_hash=?", (_指纹(token),)).fetchone()
    if not r: return None, "没有这个令牌"
    if r["void_at"]: return None, "已作废(重发过)"
    if r["used_at"]: return None, "已用过"
    if r["expires_at"] <= _现在(): return None, "已过期"
    return r, None


def 看(token):
    """顾客点开链接:这条链接是干什么的(不改任何东西)。"""
    with closing(_连()) as c, c:
        建表(c)
        r, 为何 = _找(c, token)
        if not r: return dict(ok=False, code="INVALID", reason=失效话)
        o = c.execute("SELECT id, kind, status FROM ordr WHERE id=?", (r["order_id"],)).fetchone()
    return dict(ok=True, 用途=r["purpose"], 订单尾号=str(r["order_id"])[-6:], 有效到=r["expires_at"],
                订单状态=o["status"] if o else None)


def 用(token, d):
    """顾客在链接页上办那一件事。先占位、再办;没办成就把占位还回去。"""
    from oplog import log_op
    with closing(_连()) as c, c:
        建表(c)
        r, 为何 = _找(c, token)
        if not r:
            log_op("顾客", "customer-link", "?", "用链接", "拒绝", False, "INVALID", 为何, {})
            return dict(ok=False, code="INVALID", reason=失效话)
        现 = _现在()
        占 = c.execute("UPDATE customer_link SET used_at=? WHERE token_hash=? AND used_at IS NULL AND void_at IS NULL "
                      "AND expires_at>?", (现, r["token_hash"], 现)).rowcount
    if 占 != 1:
        log_op("顾客", "customer-link", r["order_id"], "用链接", "拒绝", False, "RACE", "同时有人用了这条链接", {})
        return dict(ok=False, code="INVALID", reason=失效话)
    try:
        if r["purpose"] == "签收确认":
            import pickup_write as _pw
            res = _pw.顾客确认完成(r["order_id"], 来源="一次性链接")
        else:
            import rating_write as _rw
            res = _rw.顾客追评(r["pkg_id"], d.get("note"))
    except Exception as e:      # noqa: BLE001 —— 办的时候崩了也要把占位还回去
        res = dict(ok=False, code="ERROR", reason=f"没办成:{type(e).__name__}")
    if not res.get("ok"):
        with closing(_连()) as c, c:
            c.execute("UPDATE customer_link SET used_at=NULL WHERE token_hash=? AND used_at=?", (r["token_hash"], 现))
    log_op("顾客", "customer-link", r["order_id"], "用链接", r["purpose"], bool(res.get("ok")), res.get("code") or "?",
           (res.get("reason") or "")[:120] + ("" if res.get("ok") else "(占位已还,链接还能用)"), {})
    return res
