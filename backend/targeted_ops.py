#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定向运营:给生命周期某一档里选中的客户,各派一条跟进任务给他的归属导购。

来路:用户 2026-11-14 拍(台账第四十七条)「批量建跟进任务」——
只总部发起、要填运营目的、**只是内部任务,系统不直接联系客户**、一次最多 200 人。

## 为什么不自己往 schedule 里写

派任务的规矩(类型认不认识、能派给谁、描述和截止时间必填、挂的客户从单据带出)
全在 `tasks.assign_task` 里 —— 这里**逐个调它**,不重写一份。重写的那份迟早和它漂开:
它哪天加一道闸,这条批量路就成了绕过那道闸的后门。

## 跳过,而不是整批拒

和排班(`assign_batch` 全过才写)不同:排班是「一周一个决定」,半途失败难收拾;
定向运营是两百个各自独立的跟进,一位客户的导购离职了,不该让另外 199 位也不派。
所以**跳过并逐个说清为什么**:没有在职的归属导购 / 已经有一条同类任务没办完(防一个客户被连派两条)。
跳过的那几位在返回里列出来 —— 「派了 180 条」而不说另外 20 条去哪了,和派漏了长得一样。
"""
import os, sqlite3
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")

上限 = 200
可选类型 = ("电话回电", "上门沟通")      # 客户类、要人去做的两种;到店 / 接待是客户自己来了才有的


def 发起(d, me):
    import tasks as _tk
    from oplog import log_op
    谁 = (me or {}).get("name") or "?"; 角色 = (me or {}).get("role")
    ids = [str(x).strip() for x in (d.get("ids") or []) if str(x).strip()]
    档 = str(d.get("tier") or "").strip()
    def 拒(码, 为何):
        log_op(谁, "targeted-ops", 档 or "?", "发起", "拒绝", False, 码, 为何, {"role": 角色, "n": len(ids)})
        return dict(ok=False, code=码, reason=为何)
    if 角色 != "总部运营":
        return 拒("WRONG_ROLE", f"定向运营只有总部运营能发起,当前角色:{角色 or '未知'}")
    if not ids: return 拒("EMPTY", "先勾选要运营的客户")
    if len(set(ids)) > 上限: return 拒("TOO_MANY", f"一次最多 {上限} 人,你选了 {len(set(ids))} 人 —— 分几批发")
    类型 = d.get("type") or ""
    if 类型 not in 可选类型: return 拒("BAD_TYPE", f"跟进方式只能是 {' / '.join(可选类型)}")
    目的 = str(d.get("note") or "").strip()
    if len(目的) < 4: return 拒("NEED_NOTE", "运营目的必填,至少 4 个字 —— 导购收到任务要知道这一轮为什么找客户")
    截止 = str(d.get("end") or "").strip()
    if not 截止: return 拒("NEED_END", "截止时间必填")
    派了, 跳过 = [], []
    with closing(sqlite3.connect(DB)) as c:
        for cid in dict.fromkeys(ids):
            r = c.execute("SELECT c.advisor_no, s.status, s.role FROM customer c LEFT JOIN staff s ON s.no=c.advisor_no "
                          "WHERE c.id=?", (cid,)).fetchone()
            if not r:
                跳过.append(dict(客户=cid, 为什么="没有这位客户")); continue
            if not r[0] or r[1] != "启用" or r[2] != "顾问":
                跳过.append(dict(客户=cid, 为什么="没有在职的归属导购 —— 先做客户转移再运营")); continue
            if c.execute("SELECT 1 FROM schedule WHERE customer_id=? AND type=? AND status='有效'", (cid, 类型)).fetchone():
                跳过.append(dict(客户=cid, 为什么=f"已经有一条「{类型}」没办完")); continue
            res = _tk.assign_task({"type": 类型, "assignee_no": r[0], "customer_id": cid,
                                   "note": f"【定向运营 · {档 or '未注明档位'}】{目的}", "end": 截止}, me)
            (派了 if res.get("ok") else 跳过).append(
                dict(客户=cid, 任务=res.get("id")) if res.get("ok") else dict(客户=cid, 为什么=res.get("reason") or res.get("code")))
    log_op(谁, "targeted-ops", 档 or "?", "发起", "已派", True, "DISPATCH",
           f"{类型} · {目的} · 派了 {len(派了)} 条,跳过 {len(跳过)} 位", {"role": 角色, "n": len(ids)})
    return dict(ok=bool(派了), code="DISPATCH" if 派了 else "NONE", 派了=派了, 跳过=跳过,
                reason=f"派了 {len(派了)} 条跟进任务" + (f",跳过 {len(跳过)} 位(原因逐个列在结果里)" if 跳过 else ""))
