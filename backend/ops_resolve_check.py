#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判销账的门 · 检查 —— 在库的临时副本上真去攻击,真库不动。

2026-10-12 之前:`/api/ops-resolve` 不查登录、销账人读请求体里的 `handler`(默认「值班同学」),
`ops.resolve` 不写 op_log —— **谁都能销账、署名随便填、销完查不出是谁**(用户拍「修,排在页面两步之前」)。

门分两层,两层都要验:
  · 接口层:身份只从登录态取(`_me(self)`),没登录 401,请求体里的 handler 不读
  · `ops.resolve`:没身份拒、角色不对拒;成功 / 被拒**都写 op_log**
  · **两段确认**(用户 2026-10-13 拍):复核只认第一段(退款 / 合并都是店长),办结只认第二段 ——
    第二段那半在 `ops_close_check` 验;这里验「第二段的人不能来做第一段」
"""
import os, re, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agent")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


咬合 = [
    ("能销吗 不查角色", "拿错角色销账 → 拒"),
    ("两段不分:复核那一段也认第二段的角色", "两段确认:财务不能做复核那一段(复核只认店长)"),
    ("resolve 成功不写 op_log", "对的角色销账 → 成功,op_log 查得到是谁"),
    ("接口层改回读请求体里的 handler", "接口层:身份只从登录态取"),
    ("销账上报不看是不是本库", "副本上的销账不往真投递箱里排"),
    ("改判不查根因在不在预存选项里", "改判的根因不在预存选项里 → 拒"),
    ("改判的处理方式又认页面传上来的", "改判成功,处理方式是预存的那一条(页面传的不作数)"),
    ("改判选项把人工改判回流的也算进去", "人工改判回流的根因不会变成选项"),
    ("同一根因两种处理时随便挑一个", "同一根因标注了两种处理 → 这个根因不进选项(不替人挑)"),
]

print("研判销账的门 · 检查(库的临时副本上跑,真库不动)")
print("=" * 80)
tmp = tempfile.mkdtemp(prefix="opsres-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
import ops, oplog
ops.DB = oplog.DB = db
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
import feedback_report as FB
_箱前 = open(FB.箱, encoding="utf-8").read() if os.path.exists(FB.箱) else ""


def 一条(类型):
    """**自己造**要攻击的那条研判,不用库里碰上的。

    2026-10-13 数据工厂查出:CI 上没有模型凭据,`seed_triage_samples` 那一步不造样本、也不算失败
    → CI 上 triage 表恒为空 → 这条检查本地绿、CI 必红(「空集合上什么都成立」报得对,但永远过不去)。
    所以不管库里有没有现成的,一律在副本上走正门 `ops.save_triage` 造一条 —— 本地和 CI 走同一条路。
    `save_triage` 只吃文本和轨迹,不碰模型。"""
    t = c.execute("SELECT id FROM task WHERE type=? ORDER BY id LIMIT 1", (类型,)).fetchone()
    if not t:
        return None
    tid = ops.save_triage(t["id"], "检查", "检查", "根因:检查造的\n建议动作:检查造的\n证据:无", [])
    return {"id": tid}


def 员工(角色):
    r = c.execute("SELECT no, name, role FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1", (角色,)).fetchone()
    return dict(r) if r else None


def 日志(tid):
    return c.execute("SELECT actor, allowed, code, reason FROM op_log WHERE machine='triage' AND target=? "
                     "ORDER BY rowid DESC LIMIT 1", (f"triage#{tid}",)).fetchone()


def 拒了吗(f):
    try:
        f(); return False
    except PermissionError:
        return True


财, 判 = 一条("财务人工任务"), 一条("售后判责")
ck("造得出待复核的财务任务和售后判责来攻击(库里有这两类任务;空集合上什么都成立)", bool(财 and 判), (财, 判))
顾问, 店长, 财务, 售后 = 员工("顾问"), 员工("店长"), 员工("财务"), 员工("售后")
if 财 and 判 and 顾问 and 店长 and 财务 and 售后:
    t1, t2 = 财["id"], 判["id"]
    ck("不给身份销账 → 拒,op_log 记下", 拒了吗(lambda: ops.resolve(t1, "已采纳", None))
       and (日志(t1) or {})["code"] == "NO_IDENTITY")
    ck("拿错角色销账 → 拒(顾问销财务任务)", 拒了吗(lambda: ops.resolve(t1, "已采纳", 顾问))
       and 日志(t1)["code"] == "ROLE" and 日志(t1)["allowed"] == 0)
    ck("店长销售后判责 → 拒(10-11:只归售后)", 拒了吗(lambda: ops.resolve(t2, "已采纳", 店长)))
    ck("被拒之后研判状态没变(还是待复核)",
       c.execute("SELECT status FROM triage WHERE id=?", (t1,)).fetchone()[0] == "待复核")
    ck("两段确认:财务不能做复核那一段(复核只认店长)", 拒了吗(lambda: ops.resolve(t1, "已采纳", 财务))
       and 日志(t1)["code"] == "ROLE")
    r = ops.resolve(t1, "已采纳", 店长, note="检查")
    lg = 日志(t1)
    ck("对的角色销账 → 成功,op_log 查得到是谁", r.get("decision") == "已采纳" and lg["allowed"] == 1
       and lg["code"] == "RESOLVE" and 店长["no"] in lg["actor"], dict(lg) if lg else None)
    ck("署名就是登录的那个人(不是「值班同学」)",
       店长["no"] in (c.execute("SELECT handler FROM triage WHERE id=?", (t1,)).fetchone()[0] or ""))
    ck("售后销售后判责 → 成功", ops.resolve(t2, "已采纳", 售后).get("decision") == "已采纳")
    # ── 改判只能选预存的根因(用户 2026-10-16 拍「预先存好研判内容,选择就行了」)──
    选 = ops.改判选项("BP-01")
    ck("退款那一类有预存根因可选(从建库标注现取)", len(选) >= 2 and all(o["action"] for o in 选), 选)
    c.execute("INSERT INTO truth(case_id,breakpoint,root_cause,expected_action,src) VALUES(?,?,?,?,?)",
              ("检查-回流", "BP-01", "检查造的人工根因", "检查造的处理", "人工改判")); c.commit()
    ck("人工改判回流的根因不会变成选项", "检查造的人工根因" not in [o["root_cause"] for o in ops.改判选项("BP-01")])
    矛 = 选[-1]["root_cause"] if 选 else None
    if 矛:
        c.execute("INSERT INTO truth(case_id,breakpoint,root_cause,expected_action,src) VALUES(?,?,?,?,?)",
                  ("检查-矛盾", "BP-01", 矛, "和原处理相反的处理", "建库标注")); c.commit()
    ck("同一根因标注了两种处理 → 这个根因不进选项(不替人挑)",
       bool(矛) and 矛 not in [o["root_cause"] for o in ops.改判选项("BP-01")], 矛)
    if 矛:
        c.execute("DELETE FROM truth WHERE case_id='检查-矛盾'"); c.commit()
    财2 = c.execute("SELECT id FROM task WHERE type='财务人工任务' ORDER BY id LIMIT 1 OFFSET 1").fetchone()
    if 财2 and 选:
        t3 = ops.save_triage(财2[0], "BP-01", None, "根因:检查造的\n建议动作:检查造的\n证据:无", [])
        try:
            ops.resolve(t3, "已改判", 店长, root_cause="店长随手写的根因", action="随手写", 来源="检查"); 拒 = None
        except ValueError as e:
            拒 = str(e)
        ck("改判的根因不在预存选项里 → 拒", bool(拒) and 日志(t3)["code"] == "BAD_ROOT_CAUSE"
           and c.execute("SELECT status FROM triage WHERE id=?", (t3,)).fetchone()[0] == "待复核", 拒)
        r = ops.resolve(t3, "已改判", 店长, root_cause=选[0]["root_cause"], action="页面上乱写的处理", 来源="检查")
        行 = c.execute("SELECT status, human_root_cause, human_action FROM triage WHERE id=?", (t3,)).fetchone()
        ck("改判成功,处理方式是预存的那一条(页面传的不作数)",
           行["status"] == "已改判" and 行["human_root_cause"] == 选[0]["root_cause"]
           and 行["human_action"] == 选[0]["action"], dict(行))
        t4 = ops.save_triage(财2[0], "没有预存的断点", None, "根因:检查造的\n建议动作:检查造的\n证据:无", [])
        try:
            ops.resolve(t4, "已改判", 店长, root_cause=选[0]["root_cause"], 来源="检查"); 拒 = None
        except ValueError as e:
            拒 = str(e)
        ck("没有预存根因的那一类 → 改判拒(指去升级),不让人随手写", bool(拒) and "升级" in 拒
           and 日志(t4)["code"] == "NO_OPTIONS", 拒)
    else:
        ck("库里有第二条财务任务来验改判 —— 没有就没验,不算通过", False)
    页 = open(os.path.join(ROOT, "agentsite", "web", "queue.html"), encoding="utf-8").read()
    ck("研判弹窗的根因是下拉选择,不是手填框", '<select id="hrc"' in 页 and 'type="text" id="hrc"' not in 页)
    import rating_write as RW
    ck("评价差评跟「关差评」用同一份名单(不另抄)",
       all(ops.能销吗("评价差评", x)[0] for x in RW.能关差评的角色) and not ops.能销吗("评价差评", "顾问")[0])
    ck("没登记谁能销的类型 → 拒,不猜", not ops.能销吗("没见过的类型", "总部运营")[0])
c.close()
shutil.rmtree(tmp, ignore_errors=True)
_箱后 = open(FB.箱, encoding="utf-8").read() if os.path.exists(FB.箱) else ""
ck("副本上的销账不往真投递箱里排(只有本库上的才上报)", _箱前 == _箱后,
   f"真投递箱多了 {_箱后.count(chr(10)) - _箱前.count(chr(10))} 行")

# 接口层 ①:取身份那一步**真调用**(数据工厂 10-12 指出:`_me` 只看 handler.headers 的 cookie,
# 不依赖 socket / 服务,造一个只有 headers 的假 handler 就能真调)—— 比查字符串强一个量级
import server as SV, auth as AU, secrets as _sec, datetime as _dt


class 假手柄:
    def __init__(s, ck): s.headers = {"cookie": ck}


_tok = _sec.token_urlsafe(16)
AU._SESS[_tok] = dict(no="CHK-SM", name="检查店长", role="店长", shop="SH001", at=_dt.datetime.now())
try:
    ck("接口层:不带登录凭证 → 认不出人(_me 真调用返回 None)", SV._me(假手柄("")) is None
       and SV._me(假手柄("lx_token=乱填的")) is None)
    ck("接口层:带真凭证 → 认出是谁(_me 真调用),不读请求体里的自称",
       (SV._me(假手柄(f"lx_token={_tok}")) or {}).get("no") == "CHK-SM")
finally:
    AU._SESS.pop(_tok, None)

# 接口层 ②:那三行有没有把 _me 的结果交给 resolve —— ⚠️ **这一条只验了文本**(路由分支里的代码判据调不到;
# 要真验得起服务发请求,按规矩不进门禁)。取身份和判角色两半都被真调过了,残渣只剩这三行
# 接口层:身份只从登录态取
src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
m = re.search(r'if p=="/api/ops-resolve":(.*?)\n        if p==', src, re.S)
段 = m.group(1) if m else ""
ck("接口层:身份只从登录态取(_me),没登录 401,不读请求体里的 handler",
   bool(段) and "_me(self)" in 段 and "401" in 段 and 'body.get("handler")' not in 段, 段[:200])

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 研判销账的门都对(验了 {n} 条){D}")
