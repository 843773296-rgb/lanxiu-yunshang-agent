"""从 backend/api.py 拆出来的「api_approval」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api
from contextlib import closing   # ← 连接要显式关:sqlite3 的 with 只管事务,不关连接(2026-10-29)
import sqlite3, os, json, sys, re, subprocess
import shop_key as _SK                                         # noqa: E402  门店关联键的唯一来源
import worldclock as _wc


def approval_queue(status=None, kind=None):
    """**审批队列**:等级调整 / 积分调整 / 客户转移,谁申请的、什么理由、批了没有。

    这三种动作的共同点是 **它们都绕过了某条本该自动成立的规则** ——
    自动算出来的等级不用审批,人手改的才要。**审批管的是例外,不是日常。**

    status 写「待审批 / 已通过 / 已驳回 / 已撤回」,不给就是全部。
    """
    m = api._mem()
    where, args = ["1=1"], []
    if status: where.append("a.status=?"); args.append(status.strip())
    if kind: where.append("a.kind=?"); args.append(kind.strip())
    rows = api._rows(f"SELECT a.*, s1.name applier, s2.name decider FROM approval a "
                 f"LEFT JOIN staff s1 ON s1.no=a.applied_by "
                 f"LEFT JOIN staff s2 ON s2.no=a.decided_by "
                 f"WHERE {' AND '.join(where)} ORDER BY a.applied_at DESC", *args)
    import json as _js
    out = []
    for r in rows:
        try: pl = _js.loads(r["payload"] or "{}")
        except Exception: pl = {"原文": r["payload"]}
        out.append(api._nz(dict(单号=r["id"], 类型=r["kind"], 对象=r["target"],
                            要改成什么=pl, 状态=r["status"],
                            申请人=r["applier"] or r["applied_by"], 申请时间=r["applied_at"],
                            审批人=r["decider"] or r["decided_by"], 审批时间=r["decided_at"],
                            批注=r["note"],
                            为什么要审批=m.要审批的.get(r["kind"]))))
    待 = len([x for x in out if x.get("状态") == "待审批"])
    return api._nz(dict(条数=len(out), 待审批=待 or None,
                    谁能批=f"「待审批 → 已通过/已驳回」这两步只有 **{m.审批角色}** 能走",
                    清单=out or None,
                    说明=None if out else "这个筛选条件下一条审批单都没有"))

def _认顾问(值, c):
    """工号 / 姓名 / 「短号 姓名」→ staff 行。**认不出或重名都不猜**,回 (None, 为什么)。"""
    v = str(值 or "").strip()
    if not v:
        return None, "没说转给谁"
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT no, name, role, shop, status FROM staff WHERE no=?", (v,)).fetchall()
    if not r:
        名 = v.split()[-1]
        r = c.execute("SELECT no, name, role, shop, status FROM staff WHERE name=?", (名,)).fetchall()
    if not r:
        return None, f"员工表里没有「{v}」"
    if len(r) > 1:
        return None, f"「{v}」重名 {len(r)} 个,要给工号(" + "、".join(f"{x['no']} {x['shop']}" for x in r) + ")"
    return dict(r[0]), None

def 转移核对(target, payload):
    """一张客户转移单的事实,**按库现算**:客户们、接手顾问、门店、是不是「本店转移」。

    本店转移 = 客户全在同一家店、接手的人也在这家店而且在职。**不看谁在问** ——「这个人能不能批」另在 能批转移吗。
    """
    pl = payload if isinstance(payload, dict) else {}
    with api._cl_closing(api._c()) as c:
        c.row_factory = sqlite3.Row
        客户们, 问题 = [], []
        import account_owner as _AO   # 一个账户只归一位导购(10-26):同户的档案一起转,单子上也列出来
        for cid in _AO.同户档案(c, [x.strip() for x in str(target or "").split("|") if x.strip()]):
            r = c.execute("SELECT id, name, shop, shop_code, advisor_no FROM customer WHERE id=?", (cid,)).fetchone()
            if not r:
                问题.append(f"没有客户 {cid}"); continue
            码 = r["shop_code"] or _SK.码(c, r["shop"])
            客户们.append(dict(客户号=r["id"], 姓名=r["name"], 门店=r["shop"], 店码=码,
                               原顾问=api._员工称呼(r["advisor_no"]) if r["advisor_no"] else "没有归属顾问",
                               原顾问工号=r["advisor_no"]))
        接, 为何 = _认顾问(pl.get("to_advisor_no") or pl.get("to_advisor"), c)
        if 接 is None:
            问题.append(为何)
        else:
            接["店码"] = _SK.码(c, 接["shop"])
            if (接.get("status") or "启用") != "启用":
                问题.append(f"{接['name']} 已{接['status']},不能接客户")
    店码们 = {x["店码"] for x in 客户们}
    if len(店码们) > 1:
        问题.append("这几位客户不在同一家店 —— 一张单只转一家店的客户")
    店码 = next(iter(店码们)) if len(店码们) == 1 else None
    if 接 and 店码 and 接["店码"] != 店码:
        问题.append(f"{接['name']} 在 {接['shop']},客户在别的店 —— 接手的人要和客户同一家店")
    本店 = bool(客户们) and 接 is not None and not 问题 and 店码 is not None
    return dict(客户们=客户们, 接手=接, 店码=店码, 本店转移=本店, 问题=问题)

def 能批转移吗(me, 核):
    """→ (能不能批, 为什么)。总部运营 / 售后照旧都能批;店长只能批**自己那家店**的本店转移(用户 10-25 拍)。
    这里只给页面和智能体一个预判;**真正的判定在 fsm.check**,它认的是 ctx["本店转移"](由 审批上下文 算)。"""
    if not me:
        return False, "没登录"
    if me.get("role") == "总部运营":
        return True, "总部运营可以批所有审批单"
    if me.get("role") != "店长":
        return False, f"「{me.get('role')}」不能批审批单 —— 本店的客户转移店长能批,其余只有总部运营能批"
    if not 核.get("本店转移"):
        return False, "这张单不是本店转移(" + ";".join(核.get("问题") or ["客户或接手的人不在同一家店"]) + ")—— 要总部运营批"
    with api._cl_closing(api._c()) as c:
        我店 = _SK.码(c, me.get("shop")) if me.get("shop") else None
    if 我店 != 核.get("店码"):
        return False, "这几位客户不在你的门店 —— 要那家店的店长或总部运营批"
    return True, "本店的客户转移,店长可以批"

def 审批上下文(me, a):
    """给 fsm.check 的 ctx。店长批本店转移时 ctx["本店转移"]=True(**已经核过是他那家店**);其余一律 False。"""
    ctx = {"role": (me or {}).get("role"), "kind": a.get("kind"), "本店转移": False}
    if a.get("kind") == "客户转移" and ctx["role"] == "店长":
        try: pl = json.loads(a.get("payload") or "{}")
        except Exception: pl = {}
        ctx["本店转移"] = 能批转移吗(me, 转移核对(a.get("target"), pl))[0]
    return ctx

def 审批生效(c, a):
    """批准之后**真的改**。→ 一句改了什么。和审批中心原来那段是同一件事,搬到这里两边共用。

    客户转移写的是**工号**(名字是 staff 的副本、会漂);未完成的预约跟着迁。认不出接手的人就**不改、照实说**,不猜。
    """
    try: pl = json.loads(a.get("payload") or "{}")
    except Exception: pl = {}
    if a.get("kind") == "等级调整":
        c.execute("UPDATE customer SET level=? WHERE id=?", (pl.get("to"), a["target"]))
        return f"已将 {a['target']} 等级调整为「{pl.get('to')}」"
    if a.get("kind") == "积分调整":
        return f"已为 {a['target']} 调整积分 {pl.get('delta')}"
    if a.get("kind") == "客户转移":
        接, 为何 = _认顾问(pl.get("to_advisor_no") or pl.get("to_advisor"), c)
        if 接 is None:
            return f"⚠️ 单子批了,但没转:{为何} —— 认不出接手的人就不改,请重新提一张写清工号的单"
        import account_owner as _AO   # 整户转:同一账户下的档案一起走(10-26 用户拍:一个账户只归一位导购)
        ids = _AO.改导购(c, [x.strip() for x in (a["target"] or "").split("|") if x.strip()], 接["no"])
        return f"已将 {len(ids)} 条客户档案(连同同户的)转至 {接['name']}({接['no']}),未完成的预约一起迁过去"
    return ""

def apply_adjust(kind, target, payload, reason):
    """**提一张审批单**(等级调整 / 积分调整 / 客户转移)——**只是申请,不生效**。

    这三件事的共同点是**它们都绕过了某条本该自动成立的规则**,
    所以一律走审批,不许直接改。提单本身不改任何业务数据。

    `payload` 写要改成什么,比如等级调整写 `{"from":"金卡","to":"黑金"}`,
    积分调整写 `{"delta":5000}`。`reason` 必填 —— **没有理由的申请,
    审批的人只能靠猜,而猜出来的「同意」等于没审**。
    """
    import datetime, json as _js, oplog
    m = api._mem()
    me = api.whoami()
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in ("店长", "店长助理", "总部运营"):
        oplog.log_op(me.get("name") or "未登录", "approval", target or "—", "—", "—",
                     False, "WRONG_ROLE", f"角色 {me.get('role')} 不能提审批单", {})
        return dict(ok=False, code="WRONG_ROLE",
                    reason=f"提审批单须由店长及以上操作,你的角色是「{me.get('role')}」")
    kind = (kind or "").strip()
    if kind not in m.要审批的:
        return dict(ok=False, code="BAD_KIND",
                    reason=f"只受理这三种:{list(m.要审批的)};收到「{kind}」")
    tgt = (tgt0 := (target or "").strip())
    if not tgt:
        return dict(ok=False, code="NEED_TARGET", reason="要改谁?对象必填")
    # 客户转移可以是多个,用 | 隔开;其余必须是一个真实存在的客户
    for one in tgt.split("|"):
        if not api._rows2("SELECT 1 FROM customer WHERE id=?", one.strip()):
            return dict(ok=False, code="NO_CUSTOMER",
                        reason=f"没有客户 {one.strip()} —— **查无此人**,不是「这人没资格」")
    why = (reason or "").strip()
    if len(why) < 4:
        return dict(ok=False, code="NEED_REASON",
                    reason="理由必填 —— **没有理由的申请,审批的人只能靠猜**,"
                           "而猜出来的「同意」等于没审")
    if isinstance(payload, str):
        try: payload = _js.loads(payload)
        except Exception: payload = {"原文": payload}
    if not isinstance(payload, dict) or not payload:
        return dict(ok=False, code="NEED_PAYLOAD", reason="要改成什么?payload 必填")
    核 = None
    if kind == "客户转移":
        # 建单前就按库核一遍(10-25):别等批的那一刻才发现转给了一个停用的人、或者客户根本不在本店
        核 = 转移核对(tgt, payload)
        if api.本店范围(me) is not None:
            with api._cl_closing(api._c()) as _x:
                我店 = _SK.码(_x, api.本店范围(me)) if api.本店范围(me) else None
            别店 = [x["客户号"] for x in 核["客户们"] if x["店码"] != 我店]
            if 别店:
                return dict(ok=False, code="NOT_MY_SHOP", 范围="本店",
                            reason=f"{'、'.join(别店)} 不在你的门店,转不了 —— 跨店的转移找总部运营提")
        if 核["问题"]:
            return dict(ok=False, code="BAD_TRANSFER", reason=";".join(核["问题"]),
                        客户们=核["客户们"] or None)
        已经是 = [x["客户号"] for x in 核["客户们"] if x["原顾问工号"] == 核["接手"]["no"]]
        if len(已经是) == len(核["客户们"]):
            return dict(ok=False, code="NOTHING_TO_DO",
                        reason=f"这几位的归属顾问已经是 {核['接手']['name']},不用转")
        payload = {**payload, "to_advisor_no": 核["接手"]["no"], "to_advisor": 核["接手"]["name"]}

    pre = {"等级调整": "AP-LV", "积分调整": "AP-PT", "客户转移": "AP-TR"}[kind]
    n = len(api._rows2("SELECT id FROM approval WHERE id LIKE ?", pre + "-%")) + 1
    aid = f"{pre}-{n:03d}"
    while api._rows2("SELECT 1 FROM approval WHERE id=?", aid):
        n += 1; aid = f"{pre}-{n:03d}"
    now = _wc.当下().strftime("%Y-%m-%d %H:%M")
    payload = dict(payload); payload["reason"] = why
    with closing(sqlite3.connect(api.DB)) as c, c:
        c.execute("INSERT INTO approval(id,kind,target,payload,status,applied_by,applied_at)"
                  " VALUES(?,?,?,?,'待审批',?,?)",
                  (aid, kind, tgt, _js.dumps(payload, ensure_ascii=False),
                   me.get("no"), now))
    oplog.log_op(me.get("name"), "approval", aid, "—", "待审批", True, "APPLY",
                 f"{me.get('name')}({me.get('role')})提了一张{kind}:{tgt} —— {why}"[:120],
                 {"kind": kind, "payload": payload, "by_agent": True})
    if kind == "客户转移":
        能, 为何 = 能批转移吗(me, 核)
        return dict(ok=True, code="APPLY", 单号=aid, 状态="待审批",
                    reason=f"已提交 {aid}(客户转移)。**这只是申请,还没生效** —— 批准之后客户才会转过去。"
                           f"{'你自己就能批(本店转移)' if 能 else '要' + ('那家店的店长或' if 核['本店转移'] else '') + '总部运营批'}",
                    # 卡片:聊天页照这个画,**数据来自这张单和库,不是模型复述**(sdk 结构化回前端)
                    卡片=dict(类型="客户转移", 单号=aid, 状态="待审批", 门店=(核["客户们"][0]["门店"] if 核["客户们"] else None),
                              客户们=[{k: x[k] for k in ("客户号", "姓名", "原顾问")} for x in 核["客户们"]],
                              转给=api._员工称呼(核["接手"]["no"]), 转给工号=核["接手"]["no"], 理由=why,
                              我能批=能, 为什么=为何))
    return dict(ok=True, code="APPLY", 单号=aid, 状态="待审批",
                reason=f"已提交 {aid}({kind}·{tgt})。**这只是申请,还没生效** —— "
                       f"「待审批 → 已通过/已驳回」这一步只有 **{m.审批角色}** 能走")

def decide_approval(approval_id, agree, note):
    """**批一张审批单**:同意或驳回。

    角色判定**不在这儿写** —— 走 `fsm.check("bk-approval", ...)`,
    那边 `APPROVAL_ROLE` 是唯一判定处。两处各判一次,总有一处会判松,
    而判松的那处**看起来完全正常**。

    `note` 必填,同意和驳回都要。驳回不写理由,申请人不知道该补什么;
    **同意不写理由,出事之后没人说得清当时看了什么**。
    """
    import fsm, oplog, json as _js
    m = api._mem()
    me = api.whoami()
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    aid = (approval_id or "").strip()
    r = api._rows("SELECT * FROM approval WHERE id=?", aid)
    if not r: return dict(ok=False, code="NO_APPROVAL", reason=f"没有审批单 {aid}")
    a = r[0]
    to = "已通过" if agree else "已驳回"
    ok, code, why = fsm.check("bk-approval", a["status"], to, 审批上下文(me, a))
    if not ok:
        oplog.log_op(me.get("name"), "approval", aid, a["status"], to, False, code, why[:120],
                     {"role": me.get("role")})
        return dict(ok=False, code=code, reason=why)
    txt = (note or "").strip()
    if len(txt) < 4:
        return dict(ok=False, code="NEED_NOTE",
                    reason="批注必填 —— 驳回不写理由,申请人不知道该补什么;"
                           "**同意不写理由,出事之后没人说得清当时看了什么**")
    now = _wc.当下().strftime("%Y-%m-%d %H:%M")
    改了 = ""
    with closing(sqlite3.connect(api.DB)) as c, c:
        c.execute("UPDATE approval SET status=?,decided_by=?,decided_at=?,note=? WHERE id=?",
                  (to, me.get("no"), now, txt, aid))
        # 批准即生效(用户 10-25 拍)—— 和审批中心同一段;同一个事务里,改单和改档要么都成要么都不成
        if agree:
            改了 = 审批生效(c, a)
    try: pl = _js.loads(a["payload"] or "{}")
    except Exception: pl = {}
    oplog.log_op(me.get("name"), "approval", aid, a["status"], to, True, "DECIDE",
                 f"{me.get('name')}({me.get('role')}){'通过' if agree else '驳回'}了 "
                 f"{aid}({a['kind']}·{a['target']}):{txt}"[:120],
                 {"kind": a["kind"], "agree": bool(agree),
                  "applied_by": a["applied_by"], "payload": pl})
    return dict(ok=True, code="DECIDE", 单号=aid, 状态=to, 改了=改了 or None,
                reason=f"{aid} 已{'通过' if agree else '驳回'}。" + (改了 or ("没有改任何业务数据" if agree else "")))
