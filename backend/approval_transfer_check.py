# -*- coding: utf-8 -*-
"""客户转移审批(用户 2026-10-25):聊天里说一句就建单 · 本店的转移店长也能批 · 批准即生效 · 两个入口同一段代码。

在库的**临时副本**上跑,真库一行都不碰(同 repair_write_check)。真调被测代码:
api.apply_adjust / api.decide_approval(智能体那条路)、server.decide_approval / server.approval_detail
(审批中心和聊天弹窗那条路)、fsm.check(放没放行的唯一判定处)。
身份是**自造**的(挂着真门店串的店长 / 顾问 / 总部运营 dict),期望值从副本库里现读,不写死某个客户。
"""
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

坏, 数 = [], [0]

咬合 = [
    ("状态机不放行店长批本店转移(只认总部运营)", "店长批本店的客户转移 → 通过,客户真的转过去了"),
    ("智能体那条路批了不改档案(批准和执行又分开了)", "店长批本店的客户转移 → 通过,客户真的转过去了"),
    ("建单不核客户在不在本店", "店长给别店的客户建转移单 → 不建(范围:本店)"),
    ("能不能批不看是不是他那家店", "别家店的店长批这张单 → 拒,客户不动"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def main():
    print("客户转移审批 · 建单核对 / 谁能批 / 批准即生效(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="apvtr-")
    T = os.path.join(tmp, "lanxiu.db")
    src = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); dst = sqlite3.connect(T)
    src.backup(dst); src.close(); dst.close()
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if 坏:
        print(f"\033[31m❌ 客户转移审批 {len(坏)} 条不过(验了 {数[0]} 条)\033[0m")
        return 1
    print(f"\033[32m✅ 客户转移审批:建单核对、本店店长能批、批准即生效、两个入口一致(验了 {数[0]} 条)\033[0m")
    return 0


def run(T):
    # ⚠️ 先把要用的模块**全部 import**,再切 DB —— 之后才 import 的写口会写真库(CLAUDE.md 记过这个坑)
    import api, server, oplog, shop_key, merge, fsm
    for m in (api, server, oplog, shop_key, merge):
        m.DB = T
    ck("切库之后,每个会写库的模块都指着副本", all(m.DB == T for m in (api, server, oplog, shop_key, merge)))
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row

    # ── 从副本里现挑:一家有 ≥3 位「顾问在职」客户、又有另一位在职顾问的店 ──
    店 = None
    for s in c.execute("SELECT code, code||' '||name AS 串 FROM shop ORDER BY code"):
        客 = c.execute("""SELECT k.id, k.advisor_no FROM customer k JOIN staff t ON t.no=k.advisor_no
                         WHERE k.shop_code=? AND t.status='启用' AND k.merged_into IS NULL
                           AND (COALESCE(k.account_id,'')='' OR NOT EXISTS (SELECT 1 FROM customer o WHERE o.account_id=k.account_id
                                AND o.id<>k.id AND o.merged_into IS NULL))   -- 单档案的:同户整户转另有一条断言(10-26)
                         ORDER BY k.id LIMIT 3""",
                       (s["code"],)).fetchall()
        if len(客) < 3:
            continue
        接 = c.execute("""SELECT no, name FROM staff WHERE shop=? AND role='顾问' AND status='启用'
                          AND no NOT IN (?,?,?) ORDER BY no LIMIT 1""",
                       (s["串"], 客[0]["advisor_no"], 客[1]["advisor_no"], 客[2]["advisor_no"])).fetchone()
        if 接:
            店 = (s["code"], s["串"], 客, 接); break
    ck("副本里挑得出一家可验的店(样本量不能是 0)", 店 is not None)
    if not 店:
        return
    码, 串, 客, 接 = 店
    别店 = c.execute("SELECT code||' '||name FROM shop WHERE code<>? ORDER BY code LIMIT 1", (码,)).fetchone()[0]
    别店客 = c.execute("SELECT id FROM customer WHERE shop_code<>? AND merged_into IS NULL ORDER BY id LIMIT 1", (码,)).fetchone()[0]
    停用 = c.execute("SELECT no FROM staff WHERE status<>'启用' ORDER BY no LIMIT 1").fetchone()
    店长 = {"no": "ZZ9001", "name": "(自造店长)", "role": "店长", "shop": 串}
    别店长 = {"no": "ZZ9002", "name": "(自造别店店长)", "role": "店长", "shop": 别店}
    顾问 = {"no": "ZZ9003", "name": "(自造顾问)", "role": "顾问", "shop": 串}
    总部 = {"no": "ZZ9004", "name": "(自造总部运营)", "role": "总部运营", "shop": ""}
    顾问号 = lambda cid: c.execute("SELECT advisor_no FROM customer WHERE id=?", (cid,)).fetchone()[0]
    单态 = lambda aid: c.execute("SELECT status FROM approval WHERE id=?", (aid,)).fetchone()[0]

    def 以(me, fn, *a):
        t = api._ME.set(me)
        try:
            return fn(*a)
        finally:
            api._ME.reset(t)

    # ── 建单 ──
    r = 以(顾问, api.apply_adjust, "客户转移", 客[0]["id"], {"to_advisor": 接["no"]}, "顾问离职交接")
    ck("顾问提转移单 → 拒(店长及以上才能提)", r.get("code") == "WRONG_ROLE", r)
    r = 以(店长, api.apply_adjust, "客户转移", 别店客, {"to_advisor": 接["no"]}, "顾问离职交接")
    ck("店长给别店的客户建转移单 → 不建(范围:本店)", r.get("code") == "NOT_MY_SHOP" and r.get("范围") == "本店", r)
    if 停用:
        r = 以(店长, api.apply_adjust, "客户转移", 客[0]["id"], {"to_advisor": 停用["no"]}, "顾问离职交接")
        ck("转给一个已停用的人 → 不建", r.get("code") == "BAD_TRANSFER" and "停用" in r.get("reason", ""), r)
    r = 以(店长, api.apply_adjust, "客户转移", 客[0]["id"], {"to_advisor": "查无此人ZZ"}, "顾问离职交接")
    ck("接手的人员工表里没有 → 不建(不猜一个最像的)", r.get("code") == "BAD_TRANSFER", r)

    前 = {x["id"]: x["advisor_no"] for x in 客}
    r1 = 以(店长, api.apply_adjust, "客户转移", f"{客[0]['id']}|{客[1]['id']}", {"to_advisor": 接["name"]}, "原顾问离职交接")
    卡 = r1.get("卡片") or {}
    ck("店长给本店客户建转移单(按姓名说接手的人)→ 建了,卡片照单子画、标着他自己能批",
       r1.get("ok") and 卡.get("单号") == r1.get("单号") and 卡.get("我能批") is True
       and len(卡.get("客户们") or []) == 2 and 卡.get("转给工号") == 接["no"], r1)
    aid = r1.get("单号")
    # 一个账户只归一位导购(10-26):点名转一条,同户的另一条档案也在单子上
    双 = c.execute("""SELECT k.id, o.id AS 同户 FROM customer k JOIN customer o ON o.account_id=k.account_id AND o.id<>k.id
                     AND o.merged_into IS NULL WHERE k.shop_code=? AND k.merged_into IS NULL AND COALESCE(k.account_id,'')<>''
                     ORDER BY k.id LIMIT 1""", (码,)).fetchone()
    if 双:
        rr = 以(店长, api.apply_adjust, "客户转移", 双["id"], {"to_advisor": 接["no"]}, "同户整户转的断言")
        ck("转一条有同户档案的客户 → 单子上连同户那条一起列出来(整户转)",
           rr.get("ok") and {x.get("客户号") for x in (rr.get("卡片") or {}).get("客户们") or []} >= {双["id"], 双["同户"]}, rr)
    else:
        ck("副本这家店里有同户两条档案的客户可验(样本量不能是 0)", False)
    ck("建单不等于生效:客户归属一个都没动", all(顾问号(k) == 前[k] for k in 前))
    import json
    pl = json.loads(c.execute("SELECT payload FROM approval WHERE id=?", (aid,)).fetchone()[0])
    ck("单子里存的是工号(名字是员工表的副本,会漂)", pl.get("to_advisor_no") == 接["no"], pl)

    # ── 详情弹窗(谁看得到、谁能批)──
    d = server.approval_detail(aid, 店长)
    ck("这家店的店长看详情:看得到、能批", d.get("我能批") is True and not d.get("看不到"), d)
    d = server.approval_detail(aid, 别店长)
    ck("别家店的店长看详情:看不到(和「不存在」同一句话)", d.get("看不到") is True, d)
    d = server.approval_detail("AP-TR-不存在", 店长)
    ck("不存在的单:也是看不到(不当探测器)", d.get("看不到") is True, d)
    d = server.approval_detail(aid, 顾问)
    ck("本店顾问看详情:看得到、不能批", d.get("看不到") is not True and d.get("我能批") is False, d)

    # ── 批不了的人 ──
    r = 以(顾问, api.decide_approval, aid, True, "同意交接")
    ck("顾问批 → 拒,客户不动", not r.get("ok") and all(顾问号(k) == 前[k] for k in 前) and 单态(aid) == "待审批", r)
    r = server.decide_approval(aid, "已通过", "同意交接", actor=别店长["name"], role="店长", me=别店长)
    ck("别家店的店长批这张单 → 拒,客户不动", not r.get("ok") and all(顾问号(k) == 前[k] for k in 前), r)
    r = 以(店长, api.decide_approval, aid, True, "好")
    ck("批注不到 4 个字 → 拒(同意也要写为什么)", r.get("code") == "NEED_NOTE" and 单态(aid) == "待审批", r)

    # ── 本店店长批(智能体那条路)──
    # 自造一条未完成的预约(副本里),不靠库里碰巧有 —— 「迁了 0 条」和「迁对了」在绿勾上长得一样
    样 = c.execute("SELECT * FROM appointment LIMIT 1").fetchone()
    if 样:
        列 = list(样.keys()); 值 = dict(样)
        值.update(id="APT-CHK-1", customer_id=客[0]["id"], advisor_no=前[客[0]["id"]], status="已预约")
        c.execute(f"INSERT INTO appointment({','.join(列)}) VALUES({','.join('?' * len(列))})", [值[k] for k in 列])
        c.commit()
    约 = c.execute("SELECT id FROM appointment WHERE customer_id IN (?,?) AND status='已预约'",
                  (客[0]["id"], 客[1]["id"])).fetchall()
    ck("有未完成的预约可验(样本量不能是 0)", len(约) > 0)
    r = 以(店长, api.decide_approval, aid, True, "原顾问离职,同意交接")
    ck("店长批本店的客户转移 → 通过,客户真的转过去了",
       r.get("ok") and 单态(aid) == "已通过" and 顾问号(客[0]["id"]) == 接["no"] and 顾问号(客[1]["id"]) == 接["no"], r)
    ck(f"未完成的预约跟着迁(这两位有 {len(约)} 条)",
       all(c.execute("SELECT advisor_no FROM appointment WHERE id=?", (x["id"],)).fetchone()[0] == 接["no"] for x in 约))
    ck("单子里没有的客户不动", 顾问号(客[2]["id"]) == 前[客[2]["id"]])
    r = 以(店长, api.decide_approval, aid, True, "再批一次试试")
    ck("已经批过的单再批 → 拒(状态机里没有这条边)", not r.get("ok"), r)

    # ── 审批中心那条路:同一段代码 ──
    r2 = 以(店长, api.apply_adjust, "客户转移", 客[2]["id"], {"to_advisor": 接["no"]}, "原顾问离职交接")
    r = server.decide_approval(r2.get("单号"), "已通过", "原顾问离职,同意", actor=店长["name"], role="店长", me=店长)
    ck("从审批中心批(server.decide_approval)→ 一样真转过去", r.get("ok") and 顾问号(客[2]["id"]) == 接["no"], r)
    行 = [x for x in server.approvals(店长)["risky"]]
    ck("审批中心列表每一行都带「我能批」(页面照它亮按钮)", all("我能批" in x for x in 行))

    # ── 驳回什么都不改 ──
    回 = 前[客[0]["id"]]
    r3 = 以(店长, api.apply_adjust, "客户转移", 客[0]["id"], {"to_advisor": 回}, "转回原顾问")
    if r3.get("ok"):
        r = 以(店长, api.decide_approval, r3["单号"], False, "原顾问已经回来,不用转")
        ck("驳回 → 单子已驳回,客户不动", r.get("ok") and 单态(r3["单号"]) == "已驳回" and 顾问号(客[0]["id"]) == 接["no"], r)
    else:
        ck("驳回那一条建得出单(原顾问在职)", False, r3)

    # ── 其他类型照旧只认总部运营 ──
    lv = c.execute("SELECT id, level FROM customer WHERE shop_code=? AND merged_into IS NULL ORDER BY id LIMIT 1", (码,)).fetchone()
    r4 = 以(店长, api.apply_adjust, "等级调整", lv["id"], {"from": lv["level"], "to": "黑金"}, "大客户特批")
    r = 以(店长, api.decide_approval, r4.get("单号"), True, "同意特批")
    ck("等级调整:店长批 → 拒(放宽只放了本店客户转移)", not r.get("ok") and 单态(r4["单号"]) == "待审批", r)
    r = 以(总部, api.decide_approval, r4.get("单号"), True, "同意特批")
    ck("等级调整:总部运营批 → 通过,等级真的改了(和审批中心一样批准即生效)",
       r.get("ok") and c.execute("SELECT level FROM customer WHERE id=?", (lv["id"],)).fetchone()[0] == "黑金", r)

    # ── HTTP 层(聊天弹窗走的就是这两个接口,经聊天站反代):身份只从登录会话取,不认请求里自报的角色 ──
    import io, json as _j, auth, datetime as _dt
    class 假请求:
        def __init__(self, path, tok=None, body=None):
            self.path = path
            raw = _j.dumps(body or {}).encode()
            self.headers = {"cookie": f"lx_token={tok}" if tok else "", "content-length": str(len(raw) if body is not None else 0)}
            self.rfile = io.BytesIO(raw); self.wfile = io.BytesIO(); self.码, self.回 = None, None
        def send_response(self, code, *a): self.码 = code
        def send_header(self, *a): pass
        def end_headers(self): pass
        def log_message(self, *a): pass
    def 打(path, tok=None, body=None):
        h = 假请求(path, tok, body)
        def _send(obj, code=200): h.码, h.回 = code, obj
        h._send = _send
        (server.H.do_POST if body is not None else server.H.do_GET)(h)
        return h.码, h.回
    def 会话(人):
        tok = f"apv-check-{人['no']}"
        with auth._LOCK: auth._SESS[tok] = dict(人, at=_dt.datetime.now())
        return tok
    r5 = 以(店长, api.apply_adjust, "客户转移", 客[1]["id"], {"to_advisor": 前[客[1]["id"]]}, "转回原顾问")
    a5 = r5.get("单号")
    _, d = 打(f"/api/approval/{a5}")
    ck("HTTP:没登录看详情 → 看不到", (d or {}).get("看不到") is True, d)
    t别 = 会话(别店长)
    _, r = 打("/api/approval-decide", t别, {"id": a5, "to": "已通过", "note": "我是总部运营", "role": "总部运营"})
    ck("HTTP:别店店长在请求里自报「总部运营」批 → 拒(角色只从会话取)",
       not (r or {}).get("ok") and 顾问号(客[1]["id"]) == 接["no"], r)
    t我 = 会话(店长)
    _, r = 打("/api/approval-decide", t我, {"id": a5, "to": "已通过", "note": "好"})
    ck("HTTP:批注太短 → 拒", (r or {}).get("code") == "NEED_NOTE", r)
    _, d = 打(f"/api/approval/{a5}", t我)
    ck("HTTP:本店店长看详情 → 能批", (d or {}).get("我能批") is True, d)
    _, r = 打("/api/approval-decide", t我, {"id": a5, "to": "已通过", "note": "原顾问回来了,同意转回"})
    ck("HTTP:本店店长批 → 通过并真的转回去", (r or {}).get("ok") and 顾问号(客[1]["id"]) == 前[客[1]["id"]], r)
    with auth._LOCK:
        auth._SESS.pop(t别, None); auth._SESS.pop(t我, None)

    # ── 状态机本身:没有「本店转移」这个结论时,店长一律批不了 ──
    ok, code, _ = fsm.check("bk-approval", "待审批", "已通过", {"role": "店长", "kind": "客户转移"})
    ck("状态机:店长 + 客户转移,但调用方没算出「本店转移」→ 拒", not ok and code == "WRONG_ROLE")
    ok, code, _ = fsm.check("bk-approval", "待审批", "已通过", {"role": "店长", "kind": "等级调整", "本店转移": True})
    ck("状态机:「本店转移」只对客户转移有效,塞给等级调整也拒", not ok)
    c.close()


if __name__ == "__main__":
    sys.exit(main())
