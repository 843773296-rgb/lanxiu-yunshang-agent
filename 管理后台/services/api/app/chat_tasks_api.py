# -*- coding: utf-8 -*-
"""员工定时 agent 任务(11-22;用户拍七条,方案《澜绣云裳agent-员工定时agent任务方案-20261122》,台账第九十条)。

员工在聊天站用一句话建任务;后台调度;到点走内部通道让聊天站的助手**以他的身份、只读工具**跑一遍(或只提醒);
结果存进 chat_task_runs = 站内收件箱(飞书送达是三期)。

    GET    /chat-tasks?staff_code=|store_id=      列表(聊天站按工号 / 店长按门店 / 后台页面看全项目)
    POST   /chat-tasks                            建:{staff_code, title, instruction, task_mode(跑|提醒), role_key?, 规则{周期,时刻,周几?,几号?,表达式?}, store_id?, deliver_policy?, source_ref?}
    PATCH  /chat-tasks/{id}                       改(If-Match revision):title / instruction / task_mode / role_key / 规则 / status(启用|停用)/ note / deliver_policy
    POST   /chat-tasks/{id}/archive               归档
    POST   /chat-tasks/{id}/run-now               立即跑一次(排一条 手动 的运行,worker 下一分钟执行;不算一期)
    GET    /chat-tasks/{id}/runs                  这条任务的执行记录
    GET    /chat-task-inbox?staff_code=           站内收件箱:未读数 + 最近的结果
    POST   /chat-task-runs/{rid}/read             标已读

调度(worker 每分钟调 `员工任务扫一遍`):① 到点的任务排一条 定时 运行(期键唯一,一期一次;上一期还在跑就跳过并记原因;**不补漏期**)
② 把 排队 的运行逐条执行:跑 → POST 聊天站 /internal/chat(带 任务id / 澜绣工号 / 角色键 / 问题);提醒 → 直接生成一句。
失败不自动重试,连续 失败阈值 期 → 自动停用并给一条说明;聊天站说这人不在职(NO_STAFF)→ 立刻停用。
频率规则和 workflow_schedules 同一套(runtime/定时.py),不另写。
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime"))

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

import 定时 as T
from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
跑, 提醒 = "跑", "提醒"
模式们 = (跑, 提醒)
启用, 停用 = "启用", "停用"
排队, 进行中, 跑了, 失败, 跳过, 已提醒, 系统 = "排队", "进行中", "跑了", "失败", "跳过", "提醒", "系统"
定时, 手动 = "定时", "手动"
失败阈值 = 3          # 连续失败几期自动停用(方案第 7 节:建议值,拍脑袋的 —— 用户没拍)
默认角色 = "all"       # 聊天站的「澜绣云裳助手」(全能力只读);模板按钮可以指别的角色键
聊天站最多秒 = 240
_模板 = {   # 聊天站「我的定时」页的三个模板按钮(用户拍 ④):点了把一句话 / 频率 / 角色填好,能改
    "商机探索": {"title": "商机探索", "instruction": "看最近 7 天通话里的商机,和店里现有的货、新品对一遍,列出能跟进的客户、为什么、建议怎么开口",
             "规则": {"周期": "日", "时刻": "09:00"}, "role_key": "all"},
    "库存盘点": {"title": "库存盘点", "instruction": "看本店库存预警和补货建议,列出该补的品类、数量依据和风险",
             "规则": {"周期": "周", "时刻": "09:00", "周几": [0]}, "role_key": "all"},   # 周几 0 = 周一(runtime/定时.py 的约定)
    "客户回访提醒": {"title": "客户回访提醒", "instruction": "列出本周该回访的客户和由头(生命周期档、上次联系、待办),按先后排",
               "规则": {"周期": "周", "时刻": "09:30", "周几": [0]}, "role_key": "all"},
}


def _规则(r):
    return {"周期": r["cadence"], "时刻": r["fire_time"], "时区": r["timezone"], **(r["cadence_detail"] or {})}


def _细节(规则):
    return {k: 规则[k] for k in ("周几", "几号", "表达式") if k in 规则}


def _行(r, 现在=None):
    d = dict(r)
    d.pop("全量", None)
    for k in ("cadence_detail", "deliver_policy"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    规则 = _规则(d)
    if 规则.get("周期") == 一次:
        t = _一次时刻(规则.get("时刻"))
        d["频率说明"] = "一次:" + (t.astimezone().strftime("%m-%d %H:%M") if t else "时刻认不出")
        d["接下来几次"] = [t.isoformat()] if (t and d.get("status") == 启用 and t > (现在 or datetime.now(timezone.utc))) else []
        return d
    try:
        d["频率说明"] = T.说法(规则)
        # T.接下来几次 回的是 (执行时刻, 统计起, 统计止) 三元组 —— 第一版当成时刻直接 .isoformat(),抛 AttributeError 被下面兜住,
        # 列表上「频率说明」就成了「规则认不出」(第十六轮 e2e 抓到);这里只要执行时刻
        d["接下来几次"] = [x[0].isoformat() for x in T.接下来几次(规则, 现在 or datetime.now(timezone.utc), 3)] if d.get("status") == 启用 else []
    except Exception as e:  # noqa: BLE001 —— 老行规则坏了也要能列出来,说清
        d["频率说明"] = f"规则认不出:{type(e).__name__}"
        d["接下来几次"] = []
    return d


def _审计(c, me, action, target, reason=None):
    from workflows_api import _审计 as _a
    _a(c, me, action, target, reason=reason)


def _锁任务(c, project_id, tid, 工号=None, 门店=None):
    """聊天站代员工调时带 ?staff_code=(本人)和 / 或 ?store_id=(店长代管本店):**是他的、或在他店里**才认,否则 404,不泄露别人有这条。
    后台页面(管理员)两个都不带。用户拍 ⑦:员工自建自管;店长能看本店所有人的并能停。"""
    r = c.execute(text("select * from chat_tasks where project_id=:p and id=:i for update"), {"p": project_id, "i": tid}).mappings().first()
    if not r or r["archived_at"]:
        raise _错(404, "NOT_FOUND", "没有这条定时任务(或已归档)", "回「我的定时」列表")
    if 工号 or 门店:
        是本人 = bool(工号) and r["staff_code"] == 工号
        在本店 = bool(门店) and (r["store_id"] or "").upper() == 门店.upper()
        if not (是本人 or 在本店):
            raise _错(404, "NOT_FOUND", "没有这条定时任务(或已归档,或不是你的 / 不在你店里)", "回「我的定时」列表")
    return r


def _要IfMatch(if_match):
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把列表里这条任务的 revision 放进 If-Match 头")
    try:
        return int(str(if_match).strip('"'))
    except ValueError:
        raise _错(409, "IF_MATCH_REQUIRED", "If-Match 不是一个 revision 数字", "列表接口每条都给了 `revision`")


一次 = "一次"   # 一次性任务(店长派任务自动建的截止前提醒,用户拍 ⑥):时刻是一个绝对时刻(ISO),到点排一条就自动停用;不在 runtime/定时.py 的周期里


def _一次时刻(文):
    """ISO 时刻字串 → 带时区的 datetime;没带时区按 Asia/Shanghai。认不出 → None。"""
    try:
        t = datetime.fromisoformat(str(文).replace("Z", "+00:00").replace(" ", "T"))
    except Exception:  # noqa: BLE001
        return None
    if t.tzinfo is None:
        from zoneinfo import ZoneInfo
        t = t.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return t


def _核规则(体规则):
    if not isinstance(体规则, dict) or not 体规则.get("周期"):
        raise _错(422, "VALIDATION", "要给 规则 {周期, 时刻, 周几? / 几号? / 表达式?}", "照「定时触发器」那套:日 / 周 / 月 / 时 / cron / 一次", field_errors={"规则": "必填"})
    if 体规则.get("周期") == 一次:
        t = _一次时刻(体规则.get("时刻"))
        if not t:
            raise _错(422, "SCHEDULE_RULE_INVALID", "一次性任务的时刻要是 ISO 时刻(2026-11-22T17:00:00+08:00)", "改成合法的时刻再提", field_errors={"规则": "时刻认不出"})
        return {"周期": 一次, "时刻": t.isoformat(), "时区": 体规则.get("时区") or "Asia/Shanghai"}
    try:
        return T.校验规则({**体规则, "时区": 体规则.get("时区") or "Asia/Shanghai"})
    except Exception as e:  # noqa: BLE001
        raise _错(422, "SCHEDULE_RULE_INVALID", f"频率规则不对:{e}", "改成合法的规则再提", field_errors={"规则": str(e)[:200]})


# ── 列表 / 建 / 改 / 归档 ───────────────────────────────────────────────────────────
@router.get(前缀 + "/chat-task-templates")
def 模板们(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    出 = []
    for 名, t in _模板.items():
        规则 = T.校验规则({**t["规则"], "时区": "Asia/Shanghai"})
        出.append({"名": 名, **t, "频率说明": T.说法(规则)})
    return {"items": 出, "角色键默认": 默认角色, "note": "点模板只是填好,保存前都能改"}


@router.get(前缀 + "/chat-tasks")
def 任务列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
         staff_code: str = Query(None), store_id: str = Query(None), status: str = Query(None),
         limit: int = Query(50, ge=1, le=200), page: int = Query(1, ge=1)):
    if status is not None and status not in (启用, 停用):
        raise _错(422, "VALIDATION", "status 只能是 启用 / 停用", "去掉 status 看全部", field_errors={"status": "不认识"})
    现在 = datetime.now(timezone.utc)
    with 连接() as c:
        rs = c.execute(text("""
            select count(*) over () 全量, t.*,
                   (select count(*) from chat_task_runs r where r.project_id=t.project_id and r.chat_task_id=t.id and r.status in ('跑了','提醒')) 成功次数,
                   (select max(r.ended_at) from chat_task_runs r where r.project_id=t.project_id and r.chat_task_id=t.id and r.status in ('跑了','提醒')) 上次成功,
                   (select r.status from chat_task_runs r where r.project_id=t.project_id and r.chat_task_id=t.id order by r.created_at desc limit 1) 上次结果
              from chat_tasks t
             where t.project_id=:p and t.archived_at is null
               and (cast(:sc as text) is null or t.staff_code = cast(:sc as text))
               and (cast(:st as text) is null or upper(coalesce(t.store_id,'')) = upper(cast(:st as text)))
               and (cast(:s as text) is null or t.status = cast(:s as text))
             order by t.created_at desc, t.id desc
             limit :n offset :o"""), {"p": project_id, "sc": staff_code, "st": store_id, "s": status, "n": limit, "o": (page - 1) * limit}).mappings().all()
    from workflows_api import 分页信封
    return {"items": [_行(r, 现在) for r in rs], **分页信封(rs, page, limit),
            "note": "到点由后台调度,「跑」真调模型(进门店月上限);「提醒」只生成一句。连续 %d 期失败自动停用" % 失败阈值}


@router.post(前缀 + "/chat-tasks", status_code=201)
async def 建任务(project_id: str, request: Request, me: 身份 = Depends(要权限("运行评测"))):
    体 = await request.json()
    if not isinstance(体, dict):
        raise _错(422, "VALIDATION", "体要是对象", "检查入参再提一次(规格要求每个错误都带下一步)")
    工号 = str(体.get("staff_code") or "").strip()
    标题 = str(体.get("title") or "").strip()
    一句 = str(体.get("instruction") or "").strip()
    模式 = 体.get("task_mode") or 跑
    角色 = str(体.get("role_key") or 默认角色).strip()
    错 = {}
    if not 工号: 错["staff_code"] = "必填:这条任务是谁的(澜绣工号)"
    if not 标题: 错["title"] = "必填"
    if not 一句: 错["instruction"] = "必填:一句话说清到点让助手做什么"
    if len(一句) > 2000: 错["instruction"] = "太长(上限 2000 字)"
    if 模式 not in 模式们: 错["task_mode"] = f"只能是 {' / '.join(模式们)}"
    if 错:
        raise _错(422, "VALIDATION", "任务缺字段", "补上再提", field_errors=错)
    规则 = _核规则(体.get("规则"))
    tid = f"ct_{uuid.uuid4().hex[:12]}"
    现在 = datetime.now(timezone.utc)
    来源 = (str(体.get("source_ref") or "").strip() or None)
    with 事务() as c:
        if 来源:
            # 同一来源(比如店长派的同一条任务)只建一条:澜绣那边的同步每 30 秒跑一轮,重放不许重建
            已 = c.execute(text("select * from chat_tasks where project_id=:p and staff_code=:sc and source_ref=:src and archived_at is null"),
                          {"p": project_id, "sc": 工号, "src": 来源}).mappings().first()
            if 已:
                d = _行(已, 现在); d["提示"] = "同一来源已经有一条,没重建"; d["已有"] = True
                return d
        c.execute(text("""insert into chat_tasks (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                              staff_code, store_id, title, instruction, task_mode, role_key, cadence, cadence_detail, fire_time, timezone,
                              schedule_enabled, armed_at, deliver_policy, source_ref, status, fail_count, note)
                          values (:i,:o,:p, now(), :u, now(), 1, :sc, :st, :t, :ins, :m, :r, :c, cast(:cd as jsonb), :ft, :tz,
                                  true, now(), cast(:dp as jsonb), :src, :s, 0, :n)"""),
                  {"i": tid, "o": me.org_id, "p": project_id, "u": me.user_id, "sc": 工号, "st": (str(体.get("store_id") or "").strip().upper() or None),
                   "t": 标题, "ins": 一句, "m": 模式, "r": 角色, "c": 规则["周期"], "cd": json.dumps(_细节(规则), ensure_ascii=False),
                   "ft": 规则.get("时刻") or "", "tz": 规则.get("时区") or "Asia/Shanghai",
                   "dp": json.dumps(体.get("deliver_policy") or {"站内": True, "飞书": True}, ensure_ascii=False),
                   "src": (str(体.get("source_ref") or "").strip() or None), "s": 启用, "n": (str(体.get("note") or "").strip() or None)})
        _审计(c, me, "chat_task.switch", {"chat_task_id": tid, "staff_code": 工号, "enabled": True, "动作": "建"})
        r = c.execute(text("select * from chat_tasks where project_id=:p and id=:i"), {"p": project_id, "i": tid}).mappings().first()
    d = _行(r, 现在)
    d["提示"] = f"已建:{d['频率说明']},到点{'让助手跑一遍' if 模式 == 跑 else '提醒你'};结果在「我的定时」里"
    return d


@router.patch(前缀 + "/chat-tasks/{tid}")
async def 改任务(project_id: str, tid: str, request: Request, me: 身份 = Depends(要权限("运行评测")),
             if_match: str = Header(default=None, alias="If-Match"), staff_code: str = Query(None), store_id: str = Query(None)):
    rev = _要IfMatch(if_match)
    体 = await request.json()
    可改 = {"title", "instruction", "task_mode", "role_key", "规则", "status", "note", "deliver_policy"}
    if not isinstance(体, dict) or not (set(体) & 可改):
        raise _错(422, "VALIDATION", f"体里要有 {sorted(可改)} 至少一项", "只传要改的字段")
    if "status" in 体 and 体["status"] not in (启用, 停用):
        raise _错(422, "VALIDATION", "status 只能是 启用 / 停用", "归档走 /archive", field_errors={"status": "不认识"})
    if "task_mode" in 体 and 体["task_mode"] not in 模式们:
        raise _错(422, "VALIDATION", f"task_mode 只能是 {' / '.join(模式们)}", "", field_errors={"task_mode": "不认识"})
    规则 = _核规则(体["规则"]) if "规则" in 体 else None
    with 事务() as c:
        老 = _锁任务(c, project_id, tid, staff_code, store_id)
        if int(老["revision"] or 0) != rev:
            raise _错(409, "CONFLICT", f"这条任务已经被改过(现在是 revision {老['revision']})", "刷新后再改", field_errors={"If-Match": str(老["revision"])})
        新 = {"t": str(体.get("title", 老["title"])).strip() or 老["title"], "ins": str(体.get("instruction", 老["instruction"])).strip() or 老["instruction"],
             "m": 体.get("task_mode", 老["task_mode"]), "r": 体.get("role_key", 老["role_key"]) or 默认角色, "s": 体.get("status", 老["status"]),
             "n": (str(体["note"]).strip() or None) if "note" in 体 else 老["note"],
             "dp": json.dumps(体["deliver_policy"] if "deliver_policy" in 体 else (老["deliver_policy"] or {}), ensure_ascii=False),
             "c": 规则["周期"] if 规则 else 老["cadence"], "cd": json.dumps(_细节(规则) if 规则 else (老["cadence_detail"] or {}), ensure_ascii=False),
             "ft": (规则.get("时刻") or "") if 规则 else 老["fire_time"], "tz": (规则.get("时区") or "Asia/Shanghai") if 规则 else 老["timezone"]}
        开关变了 = 新["s"] != 老["status"]
        c.execute(text("""update chat_tasks set title=:t, instruction=:ins, task_mode=:m, role_key=:r, status=:s, note=:n, deliver_policy=cast(:dp as jsonb),
                                 cadence=:c, cadence_detail=cast(:cd as jsonb), fire_time=:ft, timezone=:tz,
                                 schedule_enabled = (:s = '启用'), fail_count = case when :s = '启用' and :s <> status then 0 else fail_count end,
                                 armed_at = case when :s = '启用' and :s <> status then now() else armed_at end,
                                 revision=revision+1, updated_at=now()
                           where project_id=:p and id=:i"""), {**新, "p": project_id, "i": tid})
        目标 = {"chat_task_id": tid, "staff_code": 老["staff_code"], "enabled": 新["s"] == 启用, "改了": sorted(set(体) & 可改), "谁改的": me.user_id,
              "代改": 体.get("代改") or None}
        if 开关变了:   # 开关登记(tools/switch_registry_check 认的是字面量动作名,不认条件表达式)
            _审计(c, me, "chat_task.switch", 目标)
        else:
            _审计(c, me, "chat_task.update", 目标)
        r = c.execute(text("select * from chat_tasks where project_id=:p and id=:i"), {"p": project_id, "i": tid}).mappings().first()
    return _行(r)


@router.post(前缀 + "/chat-tasks/{tid}/archive")
def 归档任务(project_id: str, tid: str, me: 身份 = Depends(要权限("运行评测")), if_match: str = Header(default=None, alias="If-Match"),
         staff_code: str = Query(None), store_id: str = Query(None)):
    rev = _要IfMatch(if_match)
    with 事务() as c:
        老 = _锁任务(c, project_id, tid, staff_code, store_id)
        if int(老["revision"] or 0) != rev:
            raise _错(409, "CONFLICT", f"这条任务已经被改过(现在是 revision {老['revision']})", "刷新后再归档")
        c.execute(text("""update chat_tasks set archived_at=now(), status=:s, schedule_enabled=false, revision=revision+1, updated_at=now()
                           where project_id=:p and id=:i"""), {"s": 停用, "p": project_id, "i": tid})
        _审计(c, me, "chat_task.switch", {"chat_task_id": tid, "staff_code": 老["staff_code"], "enabled": False, "动作": "归档"})
    return {"id": tid, "归档了": True}


@router.post(前缀 + "/chat-tasks/{tid}/run-now", status_code=202)
def 立即跑一次(project_id: str, tid: str, me: 身份 = Depends(要权限("运行评测")), staff_code: str = Query(None), store_id: str = Query(None)):
    """排一条「手动」运行,worker 下一分钟执行(一轮聊天 20~90 秒,接口不等它)。不算一期、不改 last_period_start。"""
    现在 = datetime.now(timezone.utc)
    with 事务() as c:
        t = _锁任务(c, project_id, tid, staff_code, store_id)
        在跑 = c.execute(text("select id from chat_task_runs where project_id=:p and chat_task_id=:t and status in ('排队','进行中') limit 1"),
                       {"p": project_id, "t": tid}).first()
        if 在跑:
            raise _错(409, "CHAT_TASK_BUSY", "这条任务已经有一次在排队 / 进行中", "等它跑完再点", field_errors={"run_id": 在跑[0]})
        rid = _排一条(c, me.org_id, project_id, t, f"manual:{现在.strftime('%Y%m%dT%H%M%S')}", 手动, me.user_id)
    return {"run_id": rid, "status": 排队, "note": "已排队,后台下一分钟执行;结果出来在「我的定时」里"}


@router.get(前缀 + "/chat-tasks/{tid}/runs")
def 执行记录(project_id: str, tid: str, me: 身份 = Depends(要权限("查看有权配置")), limit: int = Query(30, ge=1, le=200), staff_code: str = Query(None)):
    with 连接() as c:
        if not c.execute(text("select 1 from chat_tasks where project_id=:p and id=:i and (cast(:sc as text) is null or staff_code = cast(:sc as text))"),
                         {"p": project_id, "i": tid, "sc": staff_code}).first():
            raise _错(404, "NOT_FOUND", "没有这条定时任务(或不是你的)", "回列表")
        rs = c.execute(text("""select id, chat_task_id, period_key, kind, status, trace_id, answer_text, cost_amount, amount_known, started_at, ended_at,
                                      cast(error_detail as text) error_detail, inbox_at, read_at, feishu_at, cast(feishu_detail as text) feishu_detail, created_at
                                 from chat_task_runs where project_id=:p and chat_task_id=:t order by created_at desc limit :n"""),
                       {"p": project_id, "t": tid, "n": limit}).mappings().all()
    return {"items": [_跑行(r) for r in rs], "总数": len(rs)}


def _跑行(r):
    d = dict(r)
    for k in ("error_detail", "feishu_detail"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    if d.get("cost_amount") is not None:
        d["cost_amount"] = float(d["cost_amount"])
    return d


@router.get(前缀 + "/chat-task-inbox")
def 收件箱(project_id: str, me: 身份 = Depends(要权限("查看有权配置")), staff_code: str = Query(...), limit: int = Query(20, ge=1, le=100)):
    with 连接() as c:
        未读 = c.execute(text("""select count(*) from chat_task_runs r join chat_tasks t on t.project_id=r.project_id and t.id=r.chat_task_id
                                 where r.project_id=:p and t.staff_code=:sc and r.inbox_at is not null and r.read_at is null"""), {"p": project_id, "sc": staff_code}).scalar()
        rs = c.execute(text("""select r.id, r.chat_task_id, t.title, r.kind, r.status, r.answer_text, r.trace_id, r.cost_amount, r.ended_at, r.inbox_at, r.read_at,
                                      cast(r.error_detail as text) error_detail
                                 from chat_task_runs r join chat_tasks t on t.project_id=r.project_id and t.id=r.chat_task_id
                                where r.project_id=:p and t.staff_code=:sc and r.inbox_at is not null
                                order by r.inbox_at desc limit :n"""), {"p": project_id, "sc": staff_code, "n": limit}).mappings().all()
    return {"未读": int(未读 or 0), "items": [_跑行(r) for r in rs]}


@router.post(前缀 + "/chat-task-runs/{rid}/read")
def 标已读(project_id: str, rid: str, me: 身份 = Depends(要权限("运行评测")), staff_code: str = Query(...)):
    with 事务() as c:
        n = c.execute(text("""update chat_task_runs r set read_at = coalesce(r.read_at, now()) from chat_tasks t
                               where t.project_id=r.project_id and t.id=r.chat_task_id and r.project_id=:p and r.id=:i and t.staff_code=:sc"""),
                      {"p": project_id, "i": rid, "sc": staff_code}).rowcount
    if not n:
        raise _错(404, "NOT_FOUND", "没有这条结果(或不是你的)", "检查入参再提一次(规格要求每个错误都带下一步)")
    return {"id": rid, "已读": True}


# ── 调度与执行(worker 每分钟调)──────────────────────────────────────────────────
def _排一条(c, org, project_id, t, 期键, 种类, 谁):
    rid = f"ctr_{uuid.uuid4().hex[:12]}"
    c.execute(text("""insert into chat_task_runs (id, organization_id, project_id, created_at, created_by, updated_at, revision, chat_task_id, period_key, kind, status)
                      values (:i,:o,:p, now(), :u, now(), 1, :t, :k, :kind, :s)"""),
              {"i": rid, "o": org, "p": project_id, "u": 谁, "t": t["id"], "k": 期键, "kind": 种类, "s": 排队})
    return rid


def _系统身份(c, project_id):
    """调度和自动停用用的替身(和 workflows_api._停定时 一样走 system)。"""
    class _S:  # noqa: D401
        user_id, org_id = "system", None
    s = _S()
    s.project_id = project_id
    s.org_id = c.execute(text("select organization_id from projects where id=:p"), {"p": project_id}).scalar()
    return s


def 排到点的(c, 现在):
    """① 到点的任务各排一条 定时 运行。→ 话。"""
    话 = []
    rs = c.execute(text("""select * from chat_tasks where schedule_enabled and archived_at is null and status=:s for update skip locked"""),
                   {"s": 启用}).mappings().all()
    for t in rs:
        if t["cadence"] == 一次:
            # 一次性(店长派任务的提醒):到点排一条、立刻自动停用;没到点跳过
            时 = _一次时刻(t["fire_time"])
            if not 时 or 现在 < 时:
                continue
            c.execute(text("""insert into chat_task_runs (id, organization_id, project_id, created_at, created_by, updated_at, revision, chat_task_id, period_key, kind, status)
                              values (:i,:o,:p, now(), 'system', now(), 1, :t, :k, :kind, :s) on conflict do nothing"""),
                      {"i": f"ctr_{uuid.uuid4().hex[:12]}", "o": t["organization_id"], "p": t["project_id"], "t": t["id"], "k": f"once:{t['id']}", "kind": 定时, "s": 排队})
            c.execute(text("""update chat_tasks set status=:s, schedule_enabled=false, last_period_start=:o, note=coalesce(note,'') || :n, revision=revision+1, updated_at=now()
                               where project_id=:p and id=:i"""),
                      {"s": 停用, "o": 时, "n": "(一次性,到点已排,自动停用)", "p": t["project_id"], "i": t["id"]})
            _审计(c, _系统身份(c, t["project_id"]), "chat_task.switch", {"chat_task_id": t["id"], "staff_code": t["staff_code"], "enabled": False, "动作": "一次性到点,自动停用"})
            话.append(f"{t['id']}:一次性到点,排了并停用")
            continue
        try:
            规则 = T.校验规则(_规则(t))
            判 = T.该发起吗(规则, 现在, 上次统计起=t["last_period_start"], 设定于=t["armed_at"])
        except Exception as e:  # noqa: BLE001 —— 一条规则坏了别拖住别的
            话.append(f"{t['id']}:规则认不出({type(e).__name__}),跳过")
            continue
        if not 判["发起"]:
            continue
        _, 起, 止 = 判["发起"]
        期键 = T.期键(t["id"], 规则, 起)
        在跑 = c.execute(text("select id, period_key from chat_task_runs where project_id=:p and chat_task_id=:t and status in ('排队','进行中') limit 1"),
                       {"p": t["project_id"], "t": t["id"]}).first()
        if 在跑:
            rid = f"ctr_{uuid.uuid4().hex[:12]}"
            c.execute(text("""insert into chat_task_runs (id, organization_id, project_id, created_at, created_by, updated_at, revision, chat_task_id, period_key, kind, status,
                                  started_at, ended_at, error_detail, inbox_at)
                              values (:i,:o,:p, now(), 'system', now(), 1, :t, :k, :kind, :s, now(), now(), cast(:e as jsonb), now())
                              on conflict do nothing"""),
                      {"i": rid, "o": t["organization_id"], "p": t["project_id"], "t": t["id"], "k": 期键, "kind": 定时, "s": 跳过,
                       "e": json.dumps({"为什么": f"上一期还没跑完(运行 {在跑[0]},期 {在跑[1]}),这一期跳过;不自动补"}, ensure_ascii=False)})
            话.append(f"{t['id']}:上一期没跑完,这一期跳过")
        else:
            c.execute(text("""insert into chat_task_runs (id, organization_id, project_id, created_at, created_by, updated_at, revision, chat_task_id, period_key, kind, status)
                              values (:i,:o,:p, now(), 'system', now(), 1, :t, :k, :kind, :s) on conflict do nothing"""),
                      {"i": f"ctr_{uuid.uuid4().hex[:12]}", "o": t["organization_id"], "p": t["project_id"], "t": t["id"], "k": 期键, "kind": 定时, "s": 排队})
            话.append(f"{t['id']}:排了 {起}~{止}")
        c.execute(text("update chat_tasks set last_period_start=:o, updated_at=now() where project_id=:p and id=:i"),
                  {"o": 起, "p": t["project_id"], "i": t["id"]})
    return 话


def _问聊天站(体):
    from open_api import _问聊天站 as _q
    return _q(体)


def _提示词(t, 现在):
    本地 = 现在.astimezone()
    return (f"【定时任务】这是我({t['staff_code']})设的定时任务「{t['title']}」,现在是 {本地.strftime('%Y-%m-%d %H:%M')}。"
            f"请按下面的要求做,只读、不要做任何写操作;结果直接给我看,写清依据和取不到的部分:\n{t['instruction']}")


def _停用(c, t, 为什么):
    c.execute(text("""update chat_tasks set status=:s, schedule_enabled=false, note=:n, revision=revision+1, updated_at=now() where project_id=:p and id=:i"""),
              {"s": 停用, "n": 为什么[:400], "p": t["project_id"], "i": t["id"]})
    _审计(c, _系统身份(c, t["project_id"]), "chat_task.switch", {"chat_task_id": t["id"], "staff_code": t["staff_code"], "enabled": False, "动作": "自动停用"}, reason=为什么[:200])
    c.execute(text("""insert into chat_task_runs (id, organization_id, project_id, created_at, created_by, updated_at, revision, chat_task_id, period_key, kind, status,
                          answer_text, started_at, ended_at, inbox_at)
                      values (:i,:o,:p, now(), 'system', now(), 1, :t, :k, :kind, :s, :a, now(), now(), now())"""),
              {"i": f"ctr_{uuid.uuid4().hex[:12]}", "o": t["organization_id"], "p": t["project_id"], "t": t["id"],
               "k": f"system:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}", "kind": 系统, "s": 已提醒,
               "a": f"这条定时任务已自动停用:{为什么}。改好后在「我的定时」里重新打开。"})


def 执行排队的(现在, 最多=3):
    """② 逐条执行 排队 的运行(每条自己一个事务:先占成 进行中,再调聊天站,最后写结果 —— 一轮聊天几十秒,不在锁里等)。→ 话。"""
    话 = []
    for _ in range(最多):
        with 事务() as c:
            r = c.execute(text("""select r.*, t.staff_code, t.title, t.instruction, t.task_mode, t.role_key, t.fail_count, t.organization_id org
                                     from chat_task_runs r join chat_tasks t on t.project_id=r.project_id and t.id=r.chat_task_id
                                    where r.status=:s order by r.created_at limit 1 for update of r skip locked"""), {"s": 排队}).mappings().first()
            if not r:
                break
            c.execute(text("update chat_task_runs set status=:s, started_at=now(), updated_at=now() where project_id=:p and id=:i"),
                      {"s": 进行中, "p": r["project_id"], "i": r["id"]})
        t = {"id": r["chat_task_id"], "project_id": r["project_id"], "organization_id": r["org"], "staff_code": r["staff_code"], "title": r["title"],
             "instruction": r["instruction"], "task_mode": r["task_mode"], "role_key": r["role_key"], "fail_count": r["fail_count"]}
        if t["task_mode"] == 提醒:
            结 = {"status": 已提醒, "answer_text": f"到点了:{t['title']}\n{t['instruction']}", "trace_id": None, "cost": None, "err": None}
        else:
            码, d = _问聊天站({"角色键": t["role_key"] or 默认角色, "问题": _提示词(t, 现在), "澜绣工号": t["staff_code"], "任务id": t["id"], "会话": None})
            if str(码) == "200" and isinstance(d, dict) and d.get("回答"):
                结 = {"status": 跑了, "answer_text": d["回答"], "trace_id": d.get("trace_id"), "cost": d.get("花费usd"), "err": None}
            else:
                结 = {"status": 失败, "answer_text": None, "trace_id": (d or {}).get("trace_id") if isinstance(d, dict) else None, "cost": None,
                     "err": {"http": 码, "回": (d if isinstance(d, dict) else {"error": str(d)[:200]})}}
        with 事务() as c:
            c.execute(text("""update chat_task_runs set status=:s, answer_text=:a, trace_id=:tr, cost_amount=:cost, amount_known=:known, ended_at=now(),
                                     error_detail=cast(:e as jsonb), inbox_at=now(), updated_at=now(), revision=revision+1 where project_id=:p and id=:i"""),
                      {"s": 结["status"], "a": 结["answer_text"], "tr": 结["trace_id"], "cost": 结["cost"], "known": 结["cost"] is not None,
                       "e": json.dumps(结["err"], ensure_ascii=False) if 结["err"] else None, "p": r["project_id"], "i": r["id"]})
            if 结["status"] == 失败:
                n = c.execute(text("update chat_tasks set fail_count=coalesce(fail_count,0)+1, updated_at=now() where project_id=:p and id=:i returning fail_count"),
                              {"p": r["project_id"], "i": t["id"]}).scalar()
                码 = str((结["err"] or {}).get("http"))
                回 = (结["err"] or {}).get("回") or {}
                if 码 == "403" and (回.get("code") == "NO_STAFF"):
                    _停用(c, t, "聊天站说这个工号已不在职 / 查不到,不能再以他的身份跑")
                elif int(n or 0) >= 失败阈值:
                    _停用(c, t, f"连续 {失败阈值} 期失败(最近一次:{str(回.get('error') or 回)[:120]})")
            else:
                c.execute(text("update chat_tasks set fail_count=0, last_run_id=:r, updated_at=now() where project_id=:p and id=:i"),
                          {"r": r["id"], "p": r["project_id"], "i": t["id"]})
        话.append(f"{t['id']}/{r['kind']}:{结['status']}")
    return 话


def 员工任务扫一遍(现在=None):
    """worker 每分钟调。扫挂了只少一期,不带走 worker(调用方包了 try)。"""
    现在 = 现在 or datetime.now(timezone.utc)
    with 事务() as c:
        话 = 排到点的(c, 现在)
    话 += 执行排队的(现在)
    return 话
