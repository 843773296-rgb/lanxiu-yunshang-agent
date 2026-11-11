# -*- coding: utf-8 -*-
"""店长排班的写入口:排(草稿)/ 改 / 发布。判定口径在 knowledge/shift.py,这里只取数和落地。

用户 2026-11-11 夜原话:「开始店长排班的项目工作,也需要跟派单时查在不在班一起做,两个有关联性」。
当场拍的四条(一张卡):连上最多 6 天 / 改已发布的班撞上已派的单 → 照发、自动建改派任务 /
那周没发布时派单不出推荐、可手动指定 / 后台页面和聊天都能排。

## 🔑 草稿和已发布**分两行存**,不是一行改状态

店长改一个已经发布的班,**在他点发布之前,员工看到的、派单用的,都还是原来那个**。
如果把那一行直接改成「草稿」,那个人那天就从「已发布上班」变成「草稿」——
派单立刻把他当成不可派,而店长只是在调,还没决定。
所以:同一个人同一天**最多一行已发布 + 一行草稿**;发布时草稿顶掉已发布。
查在不在班(roster.查排班事实)优先取已发布那行 —— 草稿只在从没发布过的日子起作用(码 DRAFT)。
「一人一天最多一行已发布、一行草稿」由 roster_check 验(库里没有唯一约束,见 roster.建表 的注释)。

## 发布 = 两段:先预览,再确认

预览列出三样:**违规**(拦,不许发布)、**提示**(不拦,比如有人整周没排)、**受影响的单**
(发布后那天做不了的、已经派出去的活)。有受影响的单时,第一次调发布只回预览、不写;
店长看过、带上「确认受影响」再调一次才写 —— 写的同时给店长逐条建「待改派」任务。
聊天里这一步就是确认卡;后台页面上是发布前弹出的那张清单。
"""
import datetime
import os
import sqlite3
import sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
import shift as K     # noqa: E402

DB = os.path.join(HERE, "lanxiu.db")
# 排谁:**本店在职顾问**。和 week_grid / 派单可派的人是同一拨 —— 店长自己不进排班表
# (现有 280 行全是顾问;店长要不要也排,业务没说,先不扩)。
可排角色 = ("顾问",)


def _周一(d):
    x = datetime.date.fromisoformat(str(d)[:10])
    return x - datetime.timedelta(days=x.weekday())


def _七天(周一):
    m = _周一(周一)
    return [(m + datetime.timedelta(days=i)).isoformat() for i in range(7)]


def _我(c, 工号):
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT no, name, role, status, shop FROM staff WHERE no=?", (工号,)).fetchone()
    return dict(r) if r else None


def _本店可排(c, 店):
    import shop_key as SK
    片, 参 = SK.门店条件(c, 店)
    if not 片:
        return []
    q = ",".join("?" * len(可排角色))
    return [dict(r) for r in c.execute(
        f"SELECT no, name, role, shop FROM staff WHERE status='启用' AND role IN ({q}) AND {片} ORDER BY no",
        (*可排角色, *参)).fetchall()]


def _行们(c, 工号们, 日们):
    """→ {(工号, 日期): {"已发布": 班次码或 None, "草稿": 班次码或 None}}"""
    if not 工号们 or not 日们:
        return {}
    q1, q2 = ",".join("?" * len(工号们)), ",".join("?" * len(日们))
    出 = {}
    for no, d, s, st in c.execute(f"SELECT staff_no, d, shift, status FROM roster WHERE staff_no IN ({q1}) AND d IN ({q2})",
                                  (*工号们, *日们)).fetchall():
        出.setdefault((no, d), {"已发布": None, "草稿": None})[st] = s
    return 出


def _请假(c, 工号们, 日们):
    """→ {(工号, 日期): 种类}。只认已批准的。"""
    出 = {}
    if not 工号们 or not 日们:
        return 出
    q = ",".join("?" * len(工号们))
    for no, a, b, k in c.execute(f"SELECT staff_no, d_from, d_to, kind FROM leave_req WHERE status='已批准' "
                                 f"AND staff_no IN ({q}) AND d_to>=? AND d_from<=?",
                                 (*工号们, min(日们), max(日们))).fetchall():
        for d in 日们:
            if a <= d <= b:
                出[(no, d)] = k or "事假"
    return 出


def _权限(c, 操作人工号):
    """(我 dict, 错误) —— 判定在口径模块。"""
    我 = _我(c, 操作人工号)
    ok, why = K.判排班权(我)
    return (我, None) if ok else (None, why)


# ── 读:一周的排班表(页面和聊天共用)──────────────────────────────────
def 周表(操作人工号, 周一, db=None):
    """本店一周:每人每天 {已发布, 草稿, 请假};加上这周发布了没有、有几处没发布的改动。
    顾问也能看(只读);只有店长能写。"""
    db = db or DB      # 运行时现取:默认值写成 DB 会在 def 那一刻捏死真库(tools/db_switchable_check.py)
    with closing(sqlite3.connect(db)) as c:
        我 = _我(c, 操作人工号)
        if not 我:
            return dict(error="这个工号员工表里没有 —— 这是数据问题,不是权限问题")
        日们 = _七天(周一)
        人们 = _本店可排(c, 我["shop"])
        行 = _行们(c, [p["no"] for p in 人们], 日们)
        请 = _请假(c, [p["no"] for p in 人们], 日们)
    格 = []
    改动 = 0
    for p in 人们:
        天们 = []
        for d in 日们:
            x = 行.get((p["no"], d), {"已发布": None, "草稿": None})
            if x["草稿"] is not None:
                改动 += 1
            天们.append(dict(日期=d, 已发布=x["已发布"], 草稿=x["草稿"], 请假=请.get((p["no"], d))))
        格.append(dict(工号=p["no"], 姓名=p["name"], 天=天们))
    已发布格 = sum(1 for p in 格 for t in p["天"] if t["已发布"])
    return dict(门店=我["shop"], 周一=日们[0], 周日=日们[-1], 日期=日们,
                班次=[dict(码=c_, 名=n, 起=a, 止=b) for c_, n, a, b in K.班次],
                人=格, 这周发布了吗=已发布格 > 0, 已发布格数=已发布格, 没发布的改动=改动,
                能排吗=K.判排班权(我)[0])


# ── 写:草稿 ─────────────────────────────────────────────────────────
def 写草稿(操作人工号, 条目们, 今天, db=None):
    """条目们 = [{"工号": …, "日期": "YYYY-MM-DD", "班次": "S1"}…] → dict。

    **全过才写,一条不过整批不写**(和 assign_batch 同一条规矩:写一半的排班表比没写更难收拾)。
    写的是草稿:员工看不到、派单不用;发布之前随便改。和已发布一样的条目直接丢掉草稿(没有改动)。
    """
    db = db or DB      # 运行时现取:默认值写成 DB 会在 def 那一刻捏死真库(tools/db_switchable_check.py)
    with closing(sqlite3.connect(db)) as c, c:
        我, 错 = _权限(c, 操作人工号)
        if 错:
            return dict(ok=False, error=错)
        人们 = {p["no"]: p for p in _本店可排(c, 我["shop"])}
        名到号 = {}
        for p in 人们.values():
            名到号.setdefault(p["name"], []).append(p["no"])
        坏, 计划 = [], []
        for i, it in enumerate(条目们 or [], 1):
            谁 = str(it.get("工号") or it.get("staff_no") or it.get("姓名") or "").strip()
            no = 谁 if 谁 in 人们 else (名到号.get(谁, [None])[0] if len(名到号.get(谁, [])) == 1 else None)
            d = str(it.get("日期") or it.get("d") or "").strip()
            s = str(it.get("班次") or it.get("shift") or "").strip()
            s = {n: c_ for c_, n, _, _ in K.班次}.get(s, s)     # 「早班」也认
            if not no:
                坏.append(f"第 {i} 条:「{谁}」不是本店在职顾问(可排:{'、'.join(p['name'] for p in 人们.values()) or '没有'})")
                continue
            try:
                datetime.date.fromisoformat(d)
            except ValueError:
                坏.append(f"第 {i} 条:日期「{d}」认不出,要 YYYY-MM-DD"); continue
            if d < str(今天)[:10]:
                坏.append(f"第 {i} 条:{d} 已经过去了 —— 过去的班不改(要改考勤是另一件事)"); continue
            if s not in K.班次表:
                坏.append(f"第 {i} 条:班次「{s}」不认识,只有 " + " / ".join(f"{n}({c_})" for c_, n, _, _ in K.班次)); continue
            计划.append((no, d, s))
        重 = {}
        for no, d, s in 计划:
            重.setdefault((no, d), []).append(s)
        for (no, d), ss in 重.items():
            if len(ss) > 1:
                坏.append(f"{人们[no]['name']} {d} 这一批里排了 {len(ss)} 次({'/'.join(ss)})—— 一人一天一个班次")
        if 坏:
            return dict(ok=False, error="有条目不对,**整批没写**", 不对的=坏)
        行 = _行们(c, list({x[0] for x in 计划}), list({x[1] for x in 计划}))
        写了, 没变 = 0, 0
        now = f"{今天} 00:00" if len(str(今天)) == 10 else str(今天)
        for no, d, s in 计划:
            x = 行.get((no, d), {"已发布": None, "草稿": None})
            c.execute("DELETE FROM roster WHERE staff_no=? AND d=? AND status=?", (no, d, K.草稿))
            if x["已发布"] == s:
                没变 += 1            # 和已发布一样 = 没有改动,不留草稿
                continue
            import shop_key as SK
            c.execute("INSERT INTO roster(staff_no, d, shift, shop, shop_code, status, created_by, created) "
                      "VALUES(?,?,?,?,?,?,?,?)", (no, d, s, 人们[no]["shop"], SK.码(c, 人们[no]["shop"]),
                                                K.草稿, 我["no"], now))
            写了 += 1
    return dict(ok=True, 写了=写了, 和已发布一样没留草稿=没变,
                说明="写的是**草稿**:员工看不到、派单不用;店长点「发布」才生效")


# ── 发布:预览 + 确认 ────────────────────────────────────────────────
def _hhmm(ts):
    return str(ts or "")[11:16]


def 发布预览(操作人工号, 周一, db=None):
    """只读。→ dict(违规, 提示, 受影响, 草稿格数, 能发布)。"""
    db = db or DB      # 运行时现取:默认值写成 DB 会在 def 那一刻捏死真库(tools/db_switchable_check.py)
    with closing(sqlite3.connect(db)) as c:
        我, 错 = _权限(c, 操作人工号)
        if 错:
            return dict(ok=False, error=错)
        日们 = _七天(周一)
        # 连上 6 天是滚动算的:要把前后各 6 天的已发布也拿进来
        前 = [(_周一(周一) - datetime.timedelta(days=i)).isoformat() for i in range(6, 0, -1)]
        后 = [(_周一(周一) + datetime.timedelta(days=7 + i)).isoformat() for i in range(6)]
        人们 = _本店可排(c, 我["shop"])
        号们 = [p["no"] for p in 人们]
        行 = _行们(c, 号们, 前 + 日们 + 后)
        违规, 提示, 受影响 = [], [], []
        草稿格 = 0
        for p in 人们:
            发布后 = {}
            for d in 前 + 日们 + 后:
                x = 行.get((p["no"], d))
                if not x:
                    continue
                if d in 日们 and x["草稿"] is not None:
                    发布后[d] = x["草稿"]; 草稿格 += 1
                elif x["已发布"] is not None:
                    发布后[d] = x["已发布"]
            本周 = [发布后[d] for d in 日们 if d in 发布后]
            if not 本周:
                提示.append(f"{p['name']} 这一周一天都没排 —— 发布后派单会说他「还没排班」")
                continue
            够, 话 = K.一周休够吗(本周)
            if not 够:
                违规.append(f"{p['name']}:{话}(没排的日子不算休息,休息要排成「休息」)")
            for a, b, n in K.连上超限(发布后):
                if b >= 日们[0] and a <= 日们[-1]:      # 只报和这一周沾边的那段
                    违规.append(f"{p['name']}:{a} 到 {b} 连上 {n} 天,最多连上 {K.最多连上几天} 天")
            if len(本周) < 7:
                提示.append(f"{p['name']} 这一周有 {7 - len(本周)} 天没排")
            # 受影响的单:这一周里有草稿的那几天,发布后那天做不了的已派任务
            for d in 日们:
                x = 行.get((p["no"], d))
                if not x or x["草稿"] is None:
                    continue
                for tid, typ, a_, b_, note in c.execute(
                        "SELECT id, type, start_ts, end_ts, note FROM schedule WHERE assignee_no=? AND status='有效' "
                        "AND substr(start_ts,1,10)=? ORDER BY start_ts", (p["no"], d)).fetchall():
                    撞, 为什么 = K.撞了吗(x["草稿"], typ, _hhmm(a_), _hhmm(b_) or _hhmm(a_))
                    if 撞:
                        受影响.append(dict(任务号=tid, 类型=typ, 谁=p["name"], 工号=p["no"], 日期=d,
                                        时段=f"{_hhmm(a_)}–{_hhmm(b_)}", 内容=(note or "")[:60],
                                        原来=K.班次表.get(x["已发布"], ("没排",))[0] if x["已发布"] else "没排",
                                        改成=K.班次表[x["草稿"]][0], 为什么=为什么))
    return dict(ok=True, 门店=我["shop"], 周一=日们[0], 周日=日们[-1], 草稿格数=草稿格,
                违规=违规, 提示=提示, 受影响=受影响, 能发布=(草稿格 > 0 and not 违规))


def 发布(操作人工号, 周一, 今天, 确认受影响=False, db=None):
    """发布本店这一周的草稿。有违规 → 拒;有受影响的单而没确认 → 只回预览不写;
    确认了 → 草稿顶掉已发布,并给店长逐条建「待改派」任务(用户 11-11 夜拍「照发,自动建改派任务」)。"""
    db = db or DB      # 运行时现取:默认值写成 DB 会在 def 那一刻捏死真库(tools/db_switchable_check.py)
    预 = 发布预览(操作人工号, 周一, db)
    if not 预.get("ok"):
        return 预
    if not 预["草稿格数"]:
        return dict(ok=False, error="这一周没有没发布的改动 —— 没有可发布的", **{k: 预[k] for k in ("周一", "周日")})
    if 预["违规"]:
        return {**预, "ok": False, "error": "有违反排班规则的地方,**没发布**"}
    if 预["受影响"] and not 确认受影响:
        return {**预, "ok": False, "需要确认": True,
                "error": f"发布后有 {len(预['受影响'])} 张已派的单那天做不了 —— 店长看过这张清单、确认后再发布;"
                         f"确认发布会给你逐条建「待改派」任务"}
    日们 = _七天(周一)
    now = f"{今天} 09:00" if len(str(今天)) == 10 else str(今天)
    import shop_key as SK
    with closing(sqlite3.connect(db)) as c, c:
        我 = _我(c, 操作人工号)
        号们 = [p["no"] for p in _本店可排(c, 我["shop"])]
        q1, q2 = ",".join("?" * len(号们)), ",".join("?" * len(日们))
        草稿们 = c.execute(f"SELECT id, staff_no, d FROM roster WHERE status=? AND staff_no IN ({q1}) AND d IN ({q2})",
                         (K.草稿, *号们, *日们)).fetchall()
        for rid, no, d in 草稿们:
            c.execute("DELETE FROM roster WHERE staff_no=? AND d=? AND status=?", (no, d, K.已发布))
            c.execute("UPDATE roster SET status=?, published_by=?, published_at=? WHERE id=?",
                      (K.已发布, 我["no"], now, rid))
        改派 = []
        for x in 预["受影响"]:
            n = c.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
            sid = f"SC{9000 + n + 1}"
            while c.execute("SELECT 1 FROM schedule WHERE id=?", (sid,)).fetchone():
                n += 1; sid = f"SC{9000 + n + 1}"
            说明 = (f"【待改派】{x['谁']} {x['日期']} 的班从「{x['原来']}」改成「{x['改成']}」,"
                  f"派给他的 {x['任务号']}({x['类型']} {x['时段']} {x['内容']})那天做不了({x['为什么']})—— "
                  f"请改派给那天在班的人,或和客户改时间。")
            c.execute("INSERT INTO schedule(id, type, advisor_no, start_ts, end_ts, status, shop, shop_code, "
                      "assignee_no, assigned_by, assigned_at, note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (sid, "待改派", 我["no"], f"{今天} 09:00", f"{x['日期']} 09:00", "有效", 我["shop"],
                       SK.码(c, 我["shop"]), 我["no"], "SYS", now, 说明))
            改派.append(dict(任务号=sid, 为了=x["任务号"]))
    出 = dict(ok=True, 发布了=len(草稿们), 周一=日们[0], 周日=日们[-1], 待改派任务=改派, 提示=预["提示"])
    try:
        from oplog import log_op
        log_op(我["name"], "roster", f"{我['shop']} {日们[0]}", "草稿", "已发布", True, "ROSTER_PUBLISH",
               f"{我['name']} 发布了 {日们[0]} 那一周的排班({len(草稿们)} 格);待改派 {len(改派)} 条",
               {"受影响": [x["任务号"] for x in 预["受影响"]]}, db=(None if db == DB else db))
    except Exception:       # noqa: BLE001  —— 日志写不进不回滚已发布的排班,但要让人看见
        出["日志"] = "操作日志没写进去"
    return 出
