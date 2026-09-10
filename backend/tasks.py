# -*- coding: utf-8 -*-
"""排任务:谁能派、能派给谁、谁能看、谁能完成。

**这一份被两个入口共用**:HTTP 接口(人在页面上点)和 MCP 工具(智能体代人做)。
抄两份的后果不是「两处不一致」,是「其中一处的权限先被改松」——
而松掉的那一份不会报错,只会悄悄多出一批别人代点的完结记录。

## 数据隔离

  顾问   只看得到派给**自己**的任务。**A 顾问不该知道 B 顾问在做什么** ——
         这不是界面上少显示几行,是查询层面就不给。
         界面少显示可以被改 URL 绕过去,查询不给才是真的没有。
  店长   看得到**本店**全部,因为他要排班、要知道谁忙谁闲。
  总部   看全部。

隔离的判定只有一处 —— visible_scope()。每个读任务的地方都走它,
而不是各自写一段 WHERE:各写一段的话,新加一个查询就会漏一处,
**漏掉的那一处不会报错,只会多给出几行不该看见的数据**。
"""
import os, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
from oplog import log_op

MANAGER_ROLES = ("店长", "总部运营")


def rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def visible_scope(me):
    """这个人能看到哪些任务 —— 返回 (WHERE 片段, 参数, 人话说明)。

    **所有读任务的地方都必须走这里。** 各处自己拼 WHERE 的话,
    新加一个查询就漏一处,而漏掉的那处不会报错,只会多给出几行。
    """
    if not me:
        return "1=0", [], "没登录,什么都看不到"
    if me.get("role") == "总部运营":
        return "1=1", [], "全部门店(你是总部运营)"
    if me.get("role") in MANAGER_ROLES:
        return "s.shop=?", [me.get("shop")], f"{me.get('shop')}(你是店长,看得到全店)"
    # 顾问除了自己名下的,还看得见**曾经是自己、后来被改派走的**那些。
    # 不给看的话,他的列表会凭空少一行 —— 他不会去问「我那条活呢」,
    # 他会以为自己记错了。这不是放宽隔离:那条活本来就是他的,他早知道。
    return ("(s.assignee_no=? OR s.reassigned_from=?)", [me["no"], me["no"]],
            "派给你的任务(含被改派走的)")




def _deny(me, code, reason, key="—"):
    """拒绝一次越权,**并且记进台账**。

    只记成功的日志等于没有审计:出事之后要查的从来不是「谁做成了什么」,
    而是「谁反复试着做不该做的事」。所以拒绝走这个函数,不许直接 return。
    """
    log_op((me or {}).get("name") or "未登录", "schedule", key, "—", "—", False, code,
           reason[:120], {"role": (me or {}).get("role")})
    return dict(ok=False, code=code, reason=reason)



def my_staff(me):
    """当前登录的人**能派给谁**。店长 → 本店顾问;总部运营 → 全部顾问。

    这个函数就是权限②的实现 —— 让「能派给谁」变成一个查询,
    而不是派的时候再判一次(判两遍就会有一遍是旧的)。
    """
    if not me or me.get("role") not in MANAGER_ROLES: return []
    if me["role"] == "总部运营":
        return rows("SELECT no,name,role,shop,adv_code FROM staff WHERE role='顾问' AND status='启用' ORDER BY no")
    return rows("SELECT no,name,role,shop,adv_code FROM staff "
                "WHERE role='顾问' AND status='启用' AND shop=? ORDER BY no", me.get("shop"))


def assign_task(d, me):
    """店长派一条任务。任务清单的字段:类型 / 顾问 / 起止时间 / 绑定活动 / 描述 / 附件。

    类型决定了两件事,所以它必须先填:
      · **客户相关**(预约到店/电话回电/上门沟通/接待任务)必须挂一个客户 ——
        不挂客户的「电话回电」是回给谁?这种单派下去顾问只能来问。
      · **店铺运营**(团建培训/日常运维/订单跟踪/维保任务/售后任务)不挂客户,
        而且只能店长派:谁该轮培训、谁家里有事,这些依据不在库里。
    """
    import datetime, tasktypes as tt
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in MANAGER_ROLES:
        return _deny(me, "WRONG_ROLE",
                     f"排任务须由店长及以上操作,你的角色是「{me['role']}」")

    kind = tt.norm(d.get("type") or "")
    ti = tt.info(kind)
    if not ti:
        return dict(ok=False, code="BAD_TYPE",
                    reason=f"任务类型「{d.get('type') or '(空)'}」不认识;"
                           f"可选:{'、'.join(tt.CUSTOMER_TYPES + tt.OPS_TYPES)}")

    to = (d.get("assignee_no") or "").strip()
    allowed = {x["no"]: x for x in my_staff(me)}
    if to not in allowed:
        return _deny(me, "NOT_YOURS",
                     f"只能派给**{me.get('shop') or '你管辖'}**的在职顾问;"
                     f"可派的人:{[x['name'] for x in allowed.values()] or '(没有)'}", to)

    # 数据规范由**类型**说了算:挂哪种单据、单据上的客户是谁,都从这里出。
    # customer_id 一律**不收**请求里的 —— 它是从单据带出来的结果,不是输入。
    ref_kind = ti["ref"]
    ref_id = (d.get("ref_id") or d.get("customer_id") or "").strip() or None
    ok0, cid, ref_shop, ref_desc = tt.resolve_ref(ref_kind, ref_id, rows)
    if not ok0:
        return dict(ok=False, code="BAD_REF", reason=f"「{kind}」:{ref_desc}")
    if not ref_kind and ref_id:
        return dict(ok=False, code="NO_NEED_REF",
                    reason=f"「{kind}」是店内自己的事,不挂任何单据。你填了 {ref_id} —— "
                           f"要么换成挂单据的类型,要么把它去掉")

    note = (d.get("note") or d.get("title") or "").strip()
    if not note: return dict(ok=False, code="NEED_NOTE", reason="日程描述必填 —— 写清楚这件事要做什么")

    st = (d.get("start") or "").replace("T", " ").strip()
    en = (d.get("end") or d.get("due") or "").replace("T", " ").strip()
    if not en: return dict(ok=False, code="NEED_END", reason="结束时间必填 —— 没有截止时间的任务不会被做")
    if not st: st = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        t0 = datetime.datetime.fromisoformat(st); t1 = datetime.datetime.fromisoformat(en)
    except ValueError:
        return dict(ok=False, code="BAD_TIME", reason=f"时间格式不对({st} / {en})")
    if t1 <= t0:
        return dict(ok=False, code="BAD_RANGE",
                    reason=f"结束时间({en})不在开始时间({st})之后")

    ac = (d.get("activity_code") or "").strip() or None
    if ac and not rows("SELECT code FROM activity WHERE code=?", ac):
        return dict(ok=False, code="NO_ACTIVITY", reason=f"没有活动 {ac}")

    n = rows("SELECT COUNT(*) c FROM schedule")[0]["c"]
    sid = f"SC{7000 + n + 1}"
    him = allowed[to]
    with sqlite3.connect(DB) as c:
        c.execute("""INSERT INTO schedule(id,type,advisor,customer_id,start_ts,end_ts,status,
                     shop,assignee_no,assigned_by,assigned_at,note,activity_code,ref_id)
                     VALUES(?,?,?,?,?,?, '有效',?,?,?,?,?,?,?)""",
                  (sid, kind, f"{him.get('adv_code') or ''} {him['name']}".strip(), cid,
                   st, en, him.get("shop"), to, me["no"],
                   datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), note, ac, ref_id))

    # 派单附件 —— 存不下的**逐张回报**,不要笼统说「部分失败」。
    import files as _f
    saved, failed = 0, []
    for it in (d.get("files") or [])[:_f.MAX_PER_TASK]:
        ok2, why2 = _f.save(sid, "派单", (it or {}).get("name"), (it or {}).get("data"), me["name"])
        if ok2: saved += 1
        else: failed.append(why2)

    log_op(me["name"], "schedule", sid, "—", "有效", True, "ASSIGN",
           (f"{me['name']}({me['role']})派给 {him['name']}:[{kind}] {note[:36]};"
            + (f"挂 {ref_desc};" if ref_desc else "")
            + f"{st} → {en}"
            + (f";活动 {ac}" if ac else "")
            + (f";附件 {saved} 张" if saved else "")),
           {"role": me["role"], "assignee": to, "type": kind,
            "ref": ref_id, "customer": cid})
    return dict(ok=True, code="ASSIGN", id=sid, 类型=kind, 附件=saved, 挂着=ref_desc or None,
                reason=(f"已派给 **{him['name']}**({kind}),{st} → {en}。"
                        + (f"这条挂着 {ref_desc}。" if ref_desc else "")
                        + "他登录后会在「我的任务」里看到。"
                        + (f" 附件 {saved} 张。" if saved else "")
                        + (f" 有 {len(failed)} 张没存下:{failed[0]}" if failed else "")))


def dispatch(d, me):
    """把**待分配池里已经存在的**预约单派给某个顾问。

    和 assign_task 的区别不是「新建 vs 修改」,是责任来源不同:
    assign_task 是店长凭空派一件事,dispatch 是客户已经约了、系统没认出该给谁。
    所以这里多一条限制:**只能派还没派出去的单**。
    已经派给小张的单要改派给小李,那是「改派」—— 得让小张知道他的活被拿走了,
    是另一个动作、另一条台账。悄悄换掉 assignee_no 会让小张的列表凭空少一行。
    """
    import datetime
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in MANAGER_ROLES:
        return _deny(me, "WRONG_ROLE", f"分派预约须由店长及以上操作,你的角色是「{me['role']}」")
    sid = (d.get("id") or "").strip()
    rs = rows("SELECT * FROM schedule WHERE id=?", sid)
    if not rs: return dict(ok=False, code="NO_TASK", reason=f"没有任务 {sid}")
    t = rs[0]
    if t.get("assignee_no"):
        who = rows("SELECT name FROM staff WHERE no=?", t["assignee_no"])
        return _deny(me, "ALREADY", f"这单已经派给 {who[0]['name'] if who else t['assignee_no']} 了;"
                                    f"要换人得走改派,不能直接覆盖", sid)
    if me["role"] != "总部运营" and t.get("shop") != me.get("shop"):
        return _deny(me, "NOT_YOURS", f"这单属于 {t.get('shop')},不在你管辖范围", sid)
    to = (d.get("assignee_no") or "").strip()
    allowed = {x["no"]: x for x in my_staff(me)}
    if to not in allowed:
        return _deny(me, "NOT_YOURS", f"只能派给本店在职顾问;可派的人:"
                                      f"{[x['name'] for x in allowed.values()] or '(没有)'}", sid)
    him = allowed[to]
    # **建议必须在写库之前算。**
    # 上一版写在 UPDATE 后面,结果是:派给苏彧 → 苏彧负载 +1 → 重算时他不再是最优 →
    # 台账记成「建议林岚,店长改派苏彧」。**采纳被记成了改派,而且每次都记反。**
    # 判据要在被判的那个状态下取,取晚了就是在给已经变过的世界打分。
    # 重算是对的(不信前端报上来的建议),错的只是重算的时机。
    import booking as _bk
    sg = _bk.suggest(t)
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE schedule SET assignee_no=?,assigned_by=?,assigned_at=?,advisor=? WHERE id=?",
                  (to, me["no"], datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                   f"{him.get('adv_code') or ''} {him['name']}".strip(), sid))
    adopted = bool(sg and sg["no"] == to)
    tail = ("(采纳了建议)" if adopted else
            (f"(agent 建议 {sg['name']},店长改派 {him['name']})" if sg else "(agent 没提出建议)"))
    log_op(me["name"], "schedule", sid, "待分配", him["name"], True, "DISPATCH",
           f"{me['name']}({me['role']})把待分配的 {sid} 分给 {him['name']}{tail}",
           {"role": me["role"], "assignee": to,
            "suggested": (sg or {}).get("no"), "adopted": adopted})
    return dict(ok=True, code="DISPATCH", 采纳建议=adopted,
                reason=f"已分给 **{him['name']}**,他的 pad 上就能看到了" +
                       ("" if adopted or not sg else f"(agent 建议的是 {sg['name']},已记下这次改派)"))


def assign_batch(items, me):
    """一次排一批任务(排班用)。**全过才写,一条不过就整批不写。**

    为什么要有批量,而不是循环调 assign_task:

      ① **一周的排班是一个决定,不是七个决定。** 半途失败留下三条已排、
         四条没排,比整批失败难收拾得多 —— 你得先搞清楚哪三条排进去了。
      ② **有些冲突只有整体看才发现**:同一个人被排了两个重叠时段。
         一条一条排的话,前四条都合法,第五条才撞上第二条 ——
         而那时前四条已经落库了。
      ③ 一次调用 = 一次写,**和「一次只做一件」那条闸不矛盾**:
         排一次班本来就是一件事。

    返回 (ok, 明细)。失败时明细里逐条说清哪条为什么不行 ——
    「批量失败」四个字会让人把七条挨个试一遍。
    """
    import datetime, tasktypes as tt, sqlite3 as _sq
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in MANAGER_ROLES:
        return _deny(me, "WRONG_ROLE", f"排班须由店长及以上操作,你的角色是「{me['role']}」")
    if not isinstance(items, list) or not items:
        return dict(ok=False, code="EMPTY", reason="没有要排的内容")
    if len(items) > 20:
        return dict(ok=False, code="TOO_MANY",
                    reason=f"一次最多排 20 条,你给了 {len(items)} 条 —— "
                           f"排得太多一眼看不完,看不完的批量等于没审")

    allowed = {x["no"]: x for x in my_staff(me)}
    by_name = {x["name"]: x for x in allowed.values()}
    plan, bad = [], []

    for i, it in enumerate(items, 1):
        it = it or {}
        tag = f"第 {i} 条"
        kind = tt.norm(it.get("type") or "")
        ti = tt.info(kind)
        if not ti: bad.append(f"{tag}:类型「{it.get('type')}」不认识"); continue
        who = str(it.get("assignee") or it.get("assignee_no") or "").strip()
        him = allowed.get(who) or by_name.get(who)
        if not him: bad.append(f"{tag}:派给谁没写对(「{who}」不在可派的人里)"); continue
        note = (it.get("note") or "").strip()
        if not note: bad.append(f"{tag}:日程描述必填"); continue
        st = (it.get("start") or "").replace("T", " ").strip()
        en = (it.get("end") or "").replace("T", " ").strip()
        if not (st and en): bad.append(f"{tag}:开始和结束时间都要填"); continue
        try:
            t0 = datetime.datetime.fromisoformat(st); t1 = datetime.datetime.fromisoformat(en)
        except ValueError:
            bad.append(f"{tag}:时间格式不对({st} / {en}),要 YYYY-MM-DD HH:MM"); continue
        if t1 <= t0: bad.append(f"{tag}:结束({en})不在开始({st})之后"); continue
        ok0, cid, _sh, ref_desc = tt.resolve_ref(ti["ref"], it.get("ref_id"), rows)
        if not ok0: bad.append(f"{tag}:{ref_desc}"); continue
        if not ti["ref"] and it.get("ref_id"):
            bad.append(f"{tag}:「{kind}」不挂单据,但给了 {it.get('ref_id')}"); continue
        plan.append(dict(i=i, kind=kind, him=him, note=note, t0=t0, t1=t1,
                         cid=cid, ref_id=it.get("ref_id"), ref_desc=ref_desc,
                         activity=(it.get("activity_code") or "").strip() or None))

    # ── 只有整体看才发现的冲突:批内自撞 ─────────────────────────────
    for a in plan:
        for b in plan:
            if a["i"] >= b["i"] or a["him"]["no"] != b["him"]["no"]: continue
            if a["t0"] < b["t1"] and b["t0"] < a["t1"]:
                bad.append(f"第 {a['i']} 条和第 {b['i']} 条撞了:{a['him']['name']} "
                           f"在 {max(a['t0'], b['t0']):%m-%d %H:%M} 前后被排了两件事")
    # 和已有任务撞
    for a in plan:
        busy = rows("SELECT id FROM schedule WHERE assignee_no=? AND status='有效' "
                    "AND start_ts < ? AND end_ts > ?",
                    a["him"]["no"], a["t1"].strftime("%Y-%m-%d %H:%M"),
                    a["t0"].strftime("%Y-%m-%d %H:%M"))
        if busy:
            bad.append(f"第 {a['i']} 条撞上已有任务:{a['him']['name']} 那个时段已经有 "
                       f"{busy[0]['id']}")

    if bad:
        return dict(ok=False, code="BATCH_REJECT", 逐条=bad,
                    reason=f"这批 {len(items)} 条里有 {len(bad)} 处不行,**整批都没写** —— "
                           f"半途失败留下几条已排几条没排,比整批失败难收拾得多。"
                           f"改好再排一次。")

    n = rows("SELECT COUNT(*) c FROM schedule")[0]["c"]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    made = []
    with _sq.connect(DB) as c:
        for k, a in enumerate(plan, 1):
            sid = f"SC{7000 + n + k}"
            c.execute("""INSERT INTO schedule(id,type,advisor,customer_id,start_ts,end_ts,status,
                         shop,assignee_no,assigned_by,assigned_at,note,activity_code,ref_id)
                         VALUES(?,?,?,?,?,?, '有效',?,?,?,?,?,?,?)""",
                      (sid, a["kind"],
                       f"{a['him'].get('adv_code') or ''} {a['him']['name']}".strip(), a["cid"],
                       a["t0"].strftime("%Y-%m-%d %H:%M"), a["t1"].strftime("%Y-%m-%d %H:%M"),
                       a["him"].get("shop"), a["him"]["no"], me["no"], now,
                       a["note"], a["activity"], a["ref_id"]))
            made.append(dict(任务号=sid, 类型=a["kind"], 派给=a["him"]["name"],
                             时间=f"{a['t0']:%m-%d %H:%M}–{a['t1']:%H:%M}", 内容=a["note"]))
    log_op(me["name"], "schedule", f"{made[0]['任务号']}…{made[-1]['任务号']}", "—", "有效",
           True, "BATCH_ASSIGN",
           f"{me['name']}({me['role']})一次排了 {len(made)} 条:"
           + "、".join(f"{m['派给']}{m['时间']}" for m in made[:6])
           + ("…" if len(made) > 6 else ""),
           {"role": me["role"], "count": len(made)})
    return dict(ok=True, code="BATCH_ASSIGN", 条数=len(made), 明细=made,
                reason=f"一次排了 **{len(made)} 条**,都写进去了。"
                       f"每个人的 pad 上各自只看得到自己那几条。")


def my_tasks(me, status=None):
    """看任务。范围由 visible_scope 一处判定 —— **顾问只看得到派给自己的**。

    这是**查询层面**的隔离,不是界面上少显示几行:
    界面少显示可以被改请求绕过去,查询不给才是真的没有。
    """
    if not me: return dict(error="请先登录")
    where, args, scope = visible_scope(me)
    sql = ("SELECT s.*, st.name assignee_name FROM schedule s "
           "LEFT JOIN staff st ON st.no=s.assignee_no WHERE " + where)
    if status: sql += " AND s.status=?"; args = args + [status]
    rs = rows(sql + " ORDER BY (s.status='有效') DESC, s.end_ts", *args)
    import files as _fl
    for r in rs:
        fs = _fl.listing(r["id"])
        if fs: r["附件"] = fs
        src = r.get("assigned_by") or ""
        # 三种情况,三种说法 —— 挤成一种就丢信息:
        #   SYS      系统按归属顾问自动派的     → 说清楚是自动派的
        #   工号      某个店长派的               → 说是谁
        #   空        历史排班,本来就不是谁派的 → **不要这个字段**
        if src == "SYS":
            r["派任务的人"] = "系统自动派单(按归属顾问)"
        elif src:
            by = rows("SELECT name,role FROM staff WHERE no=?", src)
            r["派任务的人"] = (f"{by[0]['name']}({by[0]['role']})" if by
                            else f"工号 {src}(员工表里查不到这个人)")
    return dict(scope=scope, hit=len(rs), rows=rs)


def reassign(d, me):
    """**改派**:把一条已经派出去的任务转给另一个人。

    和 dispatch 的区别不是「改 vs 新建」,是**有人的活被拿走了**:
      · dispatch 分的是没人管的单,谁也没损失
      · reassign 是从小张手上拿走给小李 —— 小张的列表会少一行

    所以这里多三条 dispatch 没有的:
      ① **理由必填** —— 把人的活拿走要给个说法。没有说法的改派,
         在小张眼里和「我的活莫名其妙没了」没区别
      ② **原负责人留档** —— 他还看得见这条,看得见是谁拿走的、为什么
      ③ **只能改有效的** —— 已完结的改派没有意义,只会把台账搅浑
    """
    import datetime
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    if me.get("role") not in MANAGER_ROLES:
        return _deny(me, "WRONG_ROLE", f"改派须由店长及以上操作,你的角色是「{me['role']}」")
    sid = (d.get("id") or "").strip()
    rs = rows("SELECT * FROM schedule WHERE id=?", sid)
    if not rs: return dict(ok=False, code="NO_TASK", reason=f"没有任务 {sid}")
    t = rs[0]
    if not t.get("assignee_no"):
        return dict(ok=False, code="NOT_ASSIGNED",
                    reason=f"{sid} 还没派给任何人,这是**分派**不是改派 —— 用 dispatch")
    if t.get("status") != "有效":
        return dict(ok=False, code="BAD_STATE",
                    reason=f"{sid} 当前是「{t['status']}」,改派已完结的任务没有意义,"
                           f"只会把台账搅浑")
    if me["role"] != "总部运营" and t.get("shop") != me.get("shop"):
        return _deny(me, "NOT_YOURS", f"{sid} 属于 {t.get('shop')},不在你管辖范围", sid)

    to = (d.get("assignee_no") or "").strip()
    allowed = {x["no"]: x for x in my_staff(me)}
    if to not in allowed:
        return _deny(me, "NOT_YOURS",
                     f"只能改派给**{me.get('shop') or '你管辖'}**的在职顾问;"
                     f"可派的人:{[x['name'] for x in allowed.values()] or '(没有)'}", sid)
    if to == t["assignee_no"]:
        return dict(ok=False, code="SAME_PERSON",
                    reason="新负责人和原来是同一个人 —— 这条不用改派")

    why = (d.get("reason") or "").strip()
    if len(why) < 4:
        return dict(ok=False, code="NEED_REASON",
                    reason="改派理由必填 —— **把人的活拿走要给个说法**。"
                           "没有说法的改派,在原负责人眼里和「我的活莫名其妙没了」没区别")

    old = rows("SELECT name FROM staff WHERE no=?", t["assignee_no"])
    old_name = old[0]["name"] if old else t["assignee_no"]
    him = allowed[to]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE schedule SET assignee_no=?,advisor=?,assigned_by=?,assigned_at=?,"
                  "reassigned_from=?,reassign_reason=?,reassigned_at=? WHERE id=?",
                  (to, f"{him.get('adv_code') or ''} {him['name']}".strip(), me["no"], now,
                   t["assignee_no"], why, now, sid))
    log_op(me["name"], "schedule", sid, old_name, him["name"], True, "REASSIGN",
           f"{me['name']}({me['role']})把 {sid} 从 {old_name} 改派给 {him['name']};理由:{why[:50]}",
           {"role": me["role"], "from": t["assignee_no"], "to": to, "reason": why})
    return dict(ok=True, code="REASSIGN", id=sid, 原负责人=old_name, 新负责人=him["name"],
                reason=f"{sid} 已从 **{old_name}** 改派给 **{him['name']}**。"
                       f"{old_name} 那边仍然看得见这条,标着是你改派的和理由 —— "
                       f"**不让他的列表凭空少一行**。")


def get_task(tid, me):
    """看一条任务的详情 —— **同样走 visible_scope**。

    单条查询最容易漏掉隔离:列表做了过滤,详情页直接按 id 取,
    于是**知道单号就能看别人的任务**。这类洞不会报错,只会安静地漏。
    """
    if not me: return None
    where, args, _ = visible_scope(me)
    r = rows("SELECT s.*, st.name assignee_name FROM schedule s "
             "LEFT JOIN staff st ON st.no=s.assignee_no "
             "WHERE s.id=? AND " + where, tid, *args)
    return r[0] if r else None


def finish_task(d, me):
    """完成任务:提交**日程总结**,该传图的还要传总结附件。

    **只能完成派给自己的**;店长也不能替顾问点完成。
    总结必填 —— 一条只写「完结」的任务,过两个月谁也说不出当时发生了什么,
    等于没有台账。
    """
    import tasktypes as tt, files as _f
    if not me: return dict(ok=False, code="NO_LOGIN", reason="请先登录")
    sid = (d.get("id") or "").strip()
    rs = rows("SELECT * FROM schedule WHERE id=?", sid)
    if not rs: return dict(ok=False, code="NO_TASK", reason=f"没有任务 {sid}")
    t = rs[0]
    if t.get("assignee_no") != me["no"]:
        return _deny(me, "NOT_MINE",
                     "**只能完成派给自己的任务** —— 谁做的谁点完成,"
                     "别人代点等于台账上写了一件没发生的事", sid)
    if t.get("status") != "有效":
        return dict(ok=False, code="BAD_STATE", reason=f"这条任务当前是「{t['status']}」,不能完成")

    summary = (d.get("summary") or "").strip()
    if len(summary) < 4:
        return dict(ok=False, code="NEED_SUMMARY",
                    reason="日程总结必填,写清楚做了什么、结果如何 —— "
                           "只写「完结」的任务,过两个月谁也说不出当时发生了什么")

    # 先存附件再改状态。**顺序反了会出现「已完结但图没传上」** ——
    # 而任务一旦完结,顾问就没有入口再补图了。
    kind_ok, msgs = 0, []
    for it in (d.get("files") or [])[:_f.MAX_PER_TASK]:
        ok2, why2 = _f.save(sid, "总结", (it or {}).get("name"), (it or {}).get("data"), me["name"])
        if ok2: kind_ok += 1
        else: msgs.append(why2)
    have = len(_f.listing(sid, "总结"))
    if tt.needs_photo(t.get("type")) and have == 0:
        return dict(ok=False, code="NEED_PHOTO",
                    reason=f"「{tt.norm(t.get('type'))}」完成时要传现场照"
                           + (f";这次这 {len(msgs)} 张没存下:{msgs[0]}" if msgs else ""))

    with sqlite3.connect(DB) as c:
        c.execute("UPDATE schedule SET status='完结',summary=? WHERE id=?", (summary, sid))
    log_op(me["name"], "schedule", sid, "有效", "完结", True, "FINISH",
           f"{me['name']} 完成[{tt.norm(t.get('type'))}]:{summary[:40]}"
           + (f";总结附件 {have} 张" if have else ""), {"role": me["role"]})
    return dict(ok=True, code="FINISH", 总结附件=have,
                reason=f"任务 {sid} 已完结" + (f",总结附件 {have} 张" if have else "")
                       + (f"。有 {len(msgs)} 张没存下:{msgs[0]}" if msgs else ""))


