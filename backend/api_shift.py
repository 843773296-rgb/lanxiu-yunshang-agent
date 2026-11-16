"""从 backend/api.py 拆出来的「api_shift」组(拆法见 .wip-glossary/api_split_plan.md)。

共享核心一律走 `api.X`:检查里 `api.DB = 副本` / `api.whoami = …` 要打得到这里的调用。
"""
import api


def on_shift(staff=None, date=None, at=None, days=7):
    """**谁哪天上班,以及那个人那个时候能不能接。** 读的是**排班表**(上不上班、什么班次),**不是日程占用** —— 谁那个时段被任务占了要用 `week_grid`。

    ⚠️ 这个工具存在的全部理由,是把「不上班」的**五种**分开:

        未排        店长还没排到这一天 —— **这不是「他没空」,是「排班还没出来」**
        草稿        店长还在调,随时会变 —— 按它派的单会挂在错的人身上
        已发布休息  确实没空
        请假        没空,**而且已经派给他的单要重新分配**
        不在时段    他这天上班,但不在这个点(早班的人接不了晚上的预约)

    **「查不到记录」只能表示「还没排」。** 拿它当没空,会在店长还没排下周班的时候,
    给出一份「所有人下周都有空」的推荐 —— **而那个结论看起来完全正常**。
    """
    me = api.whoami()
    if not me:
        return dict(error="不知道现在是谁在问 —— 请先登录")
    import roster as _rs, datetime as _dt
    import sqlite3 as _sq
    店 = None if me.get("role") == "总部运营" else (me.get("shop") or "")
    范围 = "全部门店" if 店 is None else f"{店}(你的门店)"

    # ── 某个人某一天(或某个时段)能不能接 ──────────────────────
    if staff:
        con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True); con.row_factory = _sq.Row
        try:
            r = con.execute("SELECT no,name,role,shop,status FROM staff WHERE no=? OR name=?",
                            (staff, staff)).fetchone()
        finally:
            con.close()
        if not r:
            # **「查无此人」和「他没空」不是一回事** —— 前者是数据问题。
            return {"看的范围": 范围,
                    "error": f"员工表里没有「{staff}」—— **这是数据问题,不是他没空**"}
        # **范围跟身份走** —— 上面那句「看的范围」说的是本店,
        # 而查人这一支原来不看门店,店长能查到别的店的人。
        # **返回值上写着「你的门店」,实际却跨了店** —— 两者长得一样。
        if 店 is not None and (r["shop"] or "") != 店:
            return {"看的范围": 范围,
                    "error": f"{r['name']} 在 {r['shop'] or '(没填门店)'},不在你的门店 —— "
                             f"**这不是他没空,是你看不到他的排班**"}
        d = date or _rs._世界的今天()          # 它返回的是字符串,不是 date
        if at:
            起 = f"{d} {at}"
            止 = f"{d} {at}"
            # 只给一个点的时候,按一小时算 —— 预约本来就是按时段
            try:
                h, m = at.split(":")
                止 = f"{d} {int(h)+1:02d}:{m}"
            except Exception:
                pass
            ok, 码, why = _rs.时段在班(r["no"], 起, 止)
        else:
            ok, 码, why = _rs.在班吗(r["no"], d)
        return {"看的范围": 范围, "谁": f"{r['name']}({r['no']})", "哪天": d,
                "能不能接": ok, "码": 码, "为什么": why,
                "下一步": _rs._口径.下一步.get(码, "")}

    # ── 一段时间的排班概况 ────────────────────────────────────
    d0 = _dt.date.fromisoformat(date or _rs._世界的今天())
    n = max(1, min(int(days or 7), 14))
    con = _sq.connect(f"file:{api.DB}?mode=ro", uri=True); con.row_factory = _sq.Row
    try:
        _片, _参 = api._门店条件(店, c=con)      # 按门店码;工坊名认不出时退回按串比
        people = [dict(x) for x in con.execute(
            "SELECT no,name FROM staff WHERE role='顾问' AND status='启用'"
            + ("" if 店 is None else f" AND {_片 or '1=0'}"), tuple(_参))]
    finally:
        con.close()
    每天 = []
    未排的天 = []
    for i in range(n):
        d = (d0 + _dt.timedelta(days=i)).isoformat()
        计 = {}
        在班 = []
        for p in people:
            ok, 码, _ = _rs.在班吗(p["no"], d)
            计[码] = 计.get(码, 0) + 1
            if ok:
                在班.append(p["name"])
        每天.append({"日期": d, "按码": 计, "在班的": 在班})
        if 计.get("UNSCHEDULED"):
            未排的天.append(d)
    return {
        "看的范围": 范围,
        "看了几个顾问": len(people),
        "看了几天": n,
        "每天": 每天,
        # **这一栏要单独摆出来。** 「还没排」混在「不上班」里,
        # 店长就看不见自己漏排了哪几天。
        "⚠️ 还没排班的日子": 未排的天,
        "每种码该做什么": _rs._口径.下一步,
    }

# ── 店长排班(用户 11-11 夜拍:后台页面 + 聊天都能排)────────────────────────
# 排的是**班次**(谁哪天上早班 / 晚班 / 全天 / 休息),**不是任务**(assign_batch 排的是任务 / 日程)。
# 规则全在 backend/roster_write.py(和后台页面同一份):草稿另存、发布才生效;发布拦「每周休一天」
# 「最多连上 6 天」;撞上已派的单要先给店长看清单,确认了才照发并建「待改派」。
def _排班今天():
    import worldclock
    return worldclock.今天().isoformat()

def shift_preview(week=None):
    """(只读)本店一周排班 + 发布预览:每人每天 已发布 / 草稿 / 请假;违规(拦发布)、提示、发布后做不了的已派单。"""
    import roster_write as RW
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在看 —— 请先登录")
    d = RW.周表(me["no"], week or _排班今天(), db=api.DB)
    if d.get("error"):
        return d
    if d.get("能排吗"):
        d["发布预览"] = RW.发布预览(me["no"], d["周一"], db=api.DB)
    return d

def shift_draft(items):
    """(写)把班次写成**草稿**:员工看不到、派单不用,发布才生效。全过才写。只有店长能排。"""
    import roster_write as RW
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在排 —— 请先登录")
    r = RW.写草稿(me["no"], items or [], _排班今天(), db=api.DB)
    if r.get("ok"): api._agent_log(me, "SHIFT_DRAFT", f"写了 {r.get('写了')} 格排班草稿")
    return r

def shift_publish(week, confirm_affected=False):
    """(写)发布本店这一周的排班草稿。有违规不发;有撞单而 confirm_affected 不是 true 时只回清单不写。"""
    import roster_write as RW
    try: me = api._need_me()
    except api._NoIdentity: return dict(error="不知道现在是谁在发布 —— 请先登录")
    r = RW.发布(me["no"], week or _排班今天(), _排班今天(), 确认受影响=bool(confirm_affected), db=api.DB)
    if r.get("ok"): api._agent_log(me, "SHIFT_PUBLISH", f"发布了 {r.get('周一')} 那一周排班 {r.get('发布了')} 格")
    return r
