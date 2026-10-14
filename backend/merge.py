#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户**软合并** —— 用户 2026-10-14 拍(三案里选「软合并」,并把现有硬合并改成它)。

    并入(a, b, me)     两条档案合成一个人:建档较晚的那条标 merged_into = 较早那条
    撤销(副档, me)     恢复独立
    主档(cid)          顺着 merged_into 找到最终那条(没并过就是自己)
    关联档(cid)        主档 + 并进它的所有档案(查 A 时连 B 一起查,用这个)

## 为什么是软的

现有 `server.merge_transit` 原来是硬合并:三张表改指主档、拿较新那条覆盖主档的手机号地址、副档归档。
**撤不回**;**只搬了 3 张表**(订单、14.5 万行量体、积分、评价都没动,合完一半在 A 一半挂 B);
研判队列不认它。软合并**一行数据都不搬**,只在副档上记一个 merged_into —— 撤销就是把它清空。

## 只关联,不累计

产品文档原规则:「保留最早客户编号;订单和积分只建立关联、不重复累计」。
会员等级按档案上存的 `amount_12m` 判档,积分余额是**各自一条链** —— 硬加会算错。
所以这里只回答「哪几条档案是同一个人」,**不替调用方相加任何数**。

## 谁能并

两段确认的第二段(10-13 拍):**店长认人 → 总部运营执行**。这里只认总部运营;成功 / 被拒都写 op_log。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
if HERE not in sys.path:
    sys.path.insert(0, HERE)

能执行合并的角色 = ("总部运营",)      # 10-13 两段确认:合并的执行段只认总部运营


def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    return c


def _有列(c):
    return "merged_into" in {r[1] for r in c.execute("PRAGMA table_info(customer)")}


def _确保列(c):
    if "merged_into" not in {r[1] for r in c.execute("PRAGMA table_info(customer)")}:
        c.execute("ALTER TABLE customer ADD COLUMN merged_into TEXT")


def 确保列():
    """老库补 merged_into 列(新建的库 seed 里就有)。读路径在 SELECT 这一列之前调一次。"""
    with _c() as c:
        _确保列(c)


def 关联档摘要(主, c=None):
    """主档之外每条关联档的订单数 / 金额 / 积分 —— **各列各的,不相加**(只关联不累计)。"""
    own = c is None
    c = c or _c()
    try:
        out = []
        for x in 关联档(主, c)[1:]:
            r = c.execute("SELECT id, name, shop, created, points, level FROM customer WHERE id=?", (x,)).fetchone()
            单 = c.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM ordr WHERE customer_id=?", (x,)).fetchone()
            out.append(dict(id=r["id"], name=r["name"], shop=r["shop"], 建档=r["created"], 积分=r["points"],
                            会员等级=r["level"], 订单数=单[0], 订单金额=round(单[1] or 0, 2)))
        return out
    finally:
        if own: c.close()


def 主档(cid, c=None):
    """顺着 merged_into 走到底。没并过就是自己;查不到这条档案返回 None。
    防环:走过的不再走(正常写口造不出环,但库是可以被手改的)。"""
    own = c is None
    c = c or _c()
    try:
        # **读路径不写库**:老库没这一列 = 谁都没并过(工具层的连接是只读的,ALTER 会炸)
        if not _有列(c):
            return cid if c.execute("SELECT 1 FROM customer WHERE id=?", (cid,)).fetchone() else None
        走过, 当前 = set(), cid
        while True:
            r = c.execute("SELECT id, merged_into FROM customer WHERE id=?", (当前,)).fetchone()
            if not r:
                return None if 当前 == cid else 当前
            if not r["merged_into"] or r["merged_into"] in 走过:
                return r["id"]
            走过.add(r["id"]); 当前 = r["merged_into"]
    finally:
        if own: c.close()


def 关联档(cid, c=None):
    """主档 + 并进它的所有档案(含多层),主档排第一。查一个人的订单 / 量体 / 评价时用这个 id 清单。"""
    own = c is None
    c = c or _c()
    try:
        根 = 主档(cid, c)
        if not 根:
            return []
        out, 待 = [根], [根]
        if not _有列(c):
            return out
        while 待:
            x = 待.pop()
            for r in c.execute("SELECT id FROM customer WHERE merged_into=? ORDER BY id", (x,)):
                if r["id"] not in out:
                    out.append(r["id"]); 待.append(r["id"])
        return out
    finally:
        if own: c.close()


def _记(me, target, frm, to, ok, code, 话, 来源):
    from oplog import log_op
    谁 = f"{(me or {}).get('name') or '?'}({(me or {}).get('no') or '?'})"
    log_op(谁, "customer-merge", target, frm, to, ok, code, f"[{来源}] {话}"[:200],
           {"role": (me or {}).get("role"), "no": (me or {}).get("no")})


def 并入(a, b, me, 来源="页面"):
    """把 a、b 两条档案合成一个人。**保留建档最早的那条**当主档(产品文档原规则),另一条标 merged_into。
    返回 dict(ok, code, 主档, 副档, reason)。没身份 / 角色不对抛 PermissionError。"""
    me = me or {}
    if not (me.get("no") and me.get("role")):
        _记(me, f"{a}|{b}", "—", "—", False, "NO_IDENTITY", "没有身份", 来源)
        raise PermissionError("没有身份 —— 合并要登录,署名用登录的人")
    if me.get("role") not in 能执行合并的角色:
        话 = f"客户合并的执行只能由 {' / '.join(能执行合并的角色)} 做(两段确认:店长认人 → 总部运营执行),你是「{me.get('role')}」"
        _记(me, f"{a}|{b}", "—", "—", False, "ROLE", 话, 来源)
        raise PermissionError(话)
    with _c() as c:
        _确保列(c)
        行 = {r["id"]: dict(r) for r in c.execute(
            "SELECT id, created, merged_into FROM customer WHERE id IN (?,?)", (a, b))}
        def 拒(code, 话):
            _记(me, f"{a}|{b}", "—", "—", False, code, 话, 来源)
            return dict(ok=False, code=code, reason=话)
        if a == b:
            return 拒("SAME", "两条是同一个档案号")
        缺 = [x for x in (a, b) if x not in 行]
        if 缺:
            return 拒("NO_CUSTOMER", f"没有档案 {'、'.join(缺)}")
        ra, rb = 主档(a, c), 主档(b, c)
        if ra == rb:
            return 拒("ALREADY", f"{a} 和 {b} 已经是同一个人了(主档都是 {ra})")
        # 两边若各自已是别人的副档,合的是它们的主档 —— 人是同一个人,档案树并成一棵
        候 = {x: dict(c.execute("SELECT id, created FROM customer WHERE id=?", (x,)).fetchone()) for x in (ra, rb)}
        主, 副 = sorted((ra, rb), key=lambda x: ((候[x]["created"] or "9999"), x))
        c.execute("UPDATE customer SET merged_into=? WHERE id=?", (主, 副))
    话 = f"{副} 并入 {主}(保留建档最早的 {主});数据一行没搬,订单 / 积分只关联不累计,能撤"
    _记(me, f"{主}<-{副}", "独立", "已并入", True, "MERGE", 话, 来源)
    return dict(ok=True, code="MERGE", 主档=主, 副档=副, reason=话)


def 撤销(副档, me, 来源="页面"):
    """把一条已并入的档案恢复独立。只撤这一层(并进它的档案仍跟着它)。"""
    me = me or {}
    if not (me.get("no") and me.get("role")):
        _记(me, 副档, "—", "—", False, "NO_IDENTITY", "没有身份", 来源)
        raise PermissionError("没有身份 —— 撤销合并要登录")
    if me.get("role") not in 能执行合并的角色:
        话 = f"撤销合并只能由 {' / '.join(能执行合并的角色)} 做,你是「{me.get('role')}」"
        _记(me, 副档, "—", "—", False, "ROLE", 话, 来源)
        raise PermissionError(话)
    with _c() as c:
        _确保列(c)
        r = c.execute("SELECT merged_into FROM customer WHERE id=?", (副档,)).fetchone()
        if not r or not r["merged_into"]:
            话 = f"{副档} 没有并入任何档案" if r else f"没有档案 {副档}"
            _记(me, 副档, "—", "—", False, "NOT_MERGED", 话, 来源)
            return dict(ok=False, code="NOT_MERGED", reason=话)
        原主 = r["merged_into"]
        c.execute("UPDATE customer SET merged_into=NULL WHERE id=?", (副档,))
    话 = f"{副档} 从 {原主} 拆回独立"
    _记(me, f"{原主}<-{副档}", "已并入", "独立", True, "UNMERGE", 话, 来源)
    return dict(ok=True, code="UNMERGE", 原主档=原主, reason=话)


def 合并过吗(a, b):
    """研判办结用的回执:a、b 现在是不是同一个人(主档相同)。"""
    with _c() as c:
        ra, rb = 主档(a, c), 主档(b, c)
    return bool(ra and rb and ra == rb)
