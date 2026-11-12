# -*- coding: utf-8 -*-
"""问题单(2026-11-12)。口径照《意见收集与能力持续改进 PRD》(10-24)§4.2 / §5.2 / §7.1 / §7.2。

## 意见单和问题单是两件事

意见是**用的人说的话**(谁、哪一轮、觉得哪里不对);问题单是**要修的那件事**(根因、方案、验收、版本)。
多条意见并进同一张问题单(opinions.issue_id),原意见保留 —— PRD §5.1「已关联问题:跟随问题单显示进度,允许重新归并」。

## 流转只有一张表

状态、根因类别、流转、哪些动作要写说明 / 要带什么字段 —— 全在 `issue_flow.py`。
这里按它判「这一步能不能做」(不在表里的 409),详情里「能做的动作」也从它算,页面照接口给的画按钮。
库 CHECK 也从它拼(models.py)。**别在这里另抄一份。**

## 这次没做的(写清楚,别当成做了)

- **关闭的「完成证据」是一段文字。** PRD §4.3 要求「修复版本已实际生效、原案例与回归通过」—— 绑真的发布版本 /
  验证记录(只接受同项目实际存在的)是下一步的事。现在库 CHECK 只钉「关闭必须有处理说明 + 完成证据」。
- **处理时限可空,不算超时。** 几天算超时是 PRD §10 的决策项(平台负责人「处理期限」),没拍;这里不替业务定数。
- **权限暂用「受理意见」**(总部运营那拨人,和意见受理同一个能力)。PRD §10 的负责人分工(业务 / 平台 / 质量 / 发布
  各管哪一步)没拍 —— 拍了之后验证 / 发布那几步大概要换成各自的能力。
- 重复单:主问题关闭后「同步处理说明」(PRD §5.2)没做;观察条件「时间 + 有效样本量」没做(要 §4.3 的发布记录)。
- 建单没有提交幂等键:从一条意见建时,意见的 revision 防得住重复(第二次 409);不挂意见直接建的,双击会建两张。
"""
import datetime as _dt
import json as _json
import uuid as _uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import issue_flow as F

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
上海 = ZoneInfo("Asia/Shanghai")

# 请求体里的名字 → 列。PATCH 能改的就这些;处理说明 / 完成证据 / 搁置理由 / 主问题只能由对应的那一步写
可改字段 = {
    "标题": "title", "业务影响": "impact_note", "复现条件": "repro_note", "根因类别": "root_cause_type",
    "根因核实": "root_cause_status", "方案": "solution_note", "验收标准": "acceptance_note", "目标版本": "target_version",
    "依赖": "dependency_note", "负责人": "owner", "处理时限": "due_date",
}
日期字段 = ("处理时限",)
短字段上限 = {"标题": 200, "目标版本": 100, "负责人": 100}
长文上限 = 2000
说明最长 = 1000
根因字段 = ("根因类别", "根因核实")     # PRD §4.2「人工可以调整,调整理由入日志」—— 改这两样要写说明


def _字(体, k):
    v = 体.get(k)
    return (str(v).strip() or None) if v is not None else None


def _今天():
    return _dt.datetime.now(上海).date()


def 校验字段(体, 新建=False):
    """→ (列: 值, 坏字段)。纯函数;只看请求体里**给了**的键(PATCH 只改给了的)。空串 = 清空。"""
    出, 坏 = {}, {}
    for k, 列 in 可改字段.items():
        if k not in 体:
            continue
        v = _字(体, k)
        if k in 日期字段 and v:
            try:
                v = _dt.date.fromisoformat(v)
            except ValueError:
                坏[k] = "要写成 2026-12-01 这样的日期"
                continue
        elif v and len(v) > 短字段上限.get(k, 长文上限):
            坏[k] = f"最多 {短字段上限.get(k, 长文上限)} 字"
            continue
        出[列] = v
    if "root_cause_type" in 出 and 出["root_cause_type"] and 出["root_cause_type"] not in F.根因类别们:
        坏["根因类别"] = f"只收 {list(F.根因类别们)}(PRD §4.2 那 9 类)"
    if "root_cause_status" in 出:
        if not 出["root_cause_status"]:
            坏["根因核实"] = f"不能空,只收 {list(F.核实状态们)}"
        elif 出["root_cause_status"] not in F.核实状态们:
            坏["根因核实"] = f"只收 {list(F.核实状态们)} —— 两者分开记(PRD §4.2)"
    if 新建:
        if not 出.get("title"):
            坏["标题"] = "要写一句这是什么问题 —— 清单里只看得到这一句"
        出.setdefault("root_cause_status", "原因待核实")
    elif "title" in 出 and not 出["title"]:
        坏["标题"] = "标题不能清空"
    return 出, 坏


def _读体(体):
    return 体 if isinstance(体, dict) else None


async def _json体(request):
    try:
        return _读体(await request.json())
    except Exception:
        return None


def _项目组织(c, project_id):
    org = c.execute(text("select organization_id from projects where id=:p"), {"p": project_id}).scalar()
    if not org:
        raise _错(404, "NOT_FOUND", "没有这个项目", "确认项目号")
    return org


def _记一步(c, org, project_id, me, issue_id, 动作, 从, 到, 说明, 变化=None):
    c.execute(text("""insert into issue_events (id, organization_id, project_id, created_at, created_by,
                          issue_id, action_code, from_status, to_status, note, change_snapshot)
                      values (:i, :o, :p, now(), :u, :iss, :a, :f, :t, :n, cast(:ch as jsonb))"""),
              {"i": f"ie_{_uuid.uuid4().hex[:12]}", "o": org, "p": project_id, "u": me.user_id, "iss": issue_id,
               "a": 动作, "f": 从, "t": 到, "n": 说明,
               "ch": _json.dumps(变化, ensure_ascii=False, default=str) if 变化 else None})


def _给人看(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


# ── 建单 ────────────────────────────────────────────────────────────────
@router.post(前缀 + "/issues", status_code=201)
async def 建问题单(project_id: str, request: Request, me: 身份 = Depends(要权限("受理意见"))):
    """`{标题, 业务影响?, 复现条件?, 根因类别?, 根因核实?, 方案?, 验收标准?, 目标版本?, 依赖?, 负责人?, 处理时限?,
        来自意见?, 意见revision?, 说明?}`。

    带「来自意见」= 从一条**核实中**的意见直接建并关联:意见走一步「关联问题」(核实中 → 已关联问题),
    两边的时间线各记一行,同一个事务;要带那条意见详情里的 revision(意见revision),对不上 409。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验字段(体, 新建=True)
    if 出.get("root_cause_status") == "原因已证实" and not 出.get("root_cause_type"):
        坏["根因核实"] = "没分根因类别就不能说「原因已证实」—— 证实的是哪一类?"
    来自 = _字(体, "来自意见")
    说明 = _字(体, "说明")
    if 来自 and 体.get("意见revision") is None:
        坏["意见revision"] = "从意见建要带那条意见详情里的 revision —— 两个人同时处理同一条意见,后到的不许覆盖"
    if 说明 and len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if 坏:
        raise _错(422, "VALIDATION", "问题单的字段不合格", "见字段错误", field_errors=坏)
    iid = f"is_{_uuid.uuid4().hex[:12]}"
    with 事务() as c:
        org = _项目组织(c, project_id)
        列 = ["title", "root_cause_status"] + [k for k in 出 if k not in ("title", "root_cause_status")]
        c.execute(text(f"""insert into issues (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                               status, reopen_count, {", ".join(列)})
                           values (:i, :o, :p, now(), :u, now(), 1, '待分析', 0, {", ".join(":c_" + k for k in 列)})"""),
                  {"i": iid, "o": org, "p": project_id, "u": me.user_id, **{"c_" + k: 出[k] for k in 列}})
        _记一步(c, org, project_id, me, iid, "新建", None, "待分析", 说明,
                {"来自意见": 来自} if 来自 else None)
        意见结果 = None
        if 来自:
            import opinions_api as _OP
            意见结果 = _OP.关联到问题单(c, project_id, me, 来自, str(体.get("意见revision")), iid, 说明)
    return {"id": iid, "状态": "待分析", "revision": 1, "关联的意见": 意见结果,
            "note": "建好了,在「待分析」。" + ("那条意见已经转「已关联问题」,详情里跟着这张单显示进度" if 来自 else "")}


# ── 清单 ────────────────────────────────────────────────────────────────
@router.get(前缀 + "/issues")
def 问题单清单(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
          status: str = Query(None), root_cause: str = Query(None),
          limit: int = Query(30, ge=1, le=200), page: int = Query(1, ge=1)):
    """按状态 / 根因类别筛。没关的排前面(已验证关闭 / 已重复 沉底),同一档里最近动过的在前。"""
    坏 = {}
    if status and status not in F.状态们:
        坏["status"] = f"只收 {list(F.状态们)}"
    if root_cause and root_cause not in F.根因类别们 + ("未分类",):
        坏["root_cause"] = f"只收 {list(F.根因类别们) + ['未分类']}"
    if 坏:
        raise _错(422, "VALIDATION", "筛选条件不合格", "见字段错误", field_errors=坏)
    条件 = "i.project_id=:p and i.archived_at is null"
    参 = {"p": project_id, "lim": limit, "off": (page - 1) * limit}
    if status:
        条件 += " and i.status=:st"; 参["st"] = status
    if root_cause == "未分类":
        条件 += " and i.root_cause_type is null"
    elif root_cause:
        条件 += " and i.root_cause_type=:rc"; 参["rc"] = root_cause
    with 连接() as c:
        rs = c.execute(text(f"""
            select count(*) over () 全量, i.*,
                   (select count(*) from opinions o where o.project_id=i.project_id and o.issue_id=i.id) 意见数
              from issues i where {条件}
             order by (i.status in ('已验证关闭', '已重复')) asc, i.updated_at desc, i.id desc
             limit :lim offset :off"""), 参).mappings().all()
        汇总 = c.execute(text("""select status, count(*) n from issues where project_id=:p and archived_at is null
                                group by 1"""), {"p": project_id}).mappings().all()
    出 = [{"id": x["id"], "标题": x["title"], "状态": x["status"], "根因类别": x["root_cause_type"],
          "根因核实": x["root_cause_status"], "负责人": x["owner"], "处理时限": _给人看(x["due_date"]),
          "目标版本": x["target_version"], "关联意见数": int(x["意见数"]), "重开次数": x["reopen_count"],
          "指向主问题": x["duplicate_of_issue_id"], "最近更新": _给人看(x["updated_at"]), "revision": x["revision"]}
         for x in rs]
    from workflows_api import 分页信封
    return {"items": 出, **分页信封(rs, page, limit), "汇总": [dict(x) for x in 汇总],
            # 页面的筛选条照这两样画,不另抄一份
            "可选状态": list(F.状态们), "可选根因类别": list(F.根因类别们) + ["未分类"],
            "note": ("**已解决只算「已验证关闭」** —— 已搁置不算(PRD §5.2);处理时限过了**不标超时**:"
                     "几天算超时 PRD §10 待定")}


# ── 详情 ────────────────────────────────────────────────────────────────
def _能做的动作(状态):
    return [{"动作": a, "到": 到, "要写说明": a in F.要说明的动作, "要的字段": list(F.动作要的字段.get(a, ()))}
            for a, 到 in F.能做的动作(状态)]


@router.get(前缀 + "/issues/{issue_id}")
def 问题单详情(project_id: str, issue_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """一张问题单 + 时间线(老的在前)+ 这一步能做的动作 + 关联的意见 + 重复关系。流转 / 改字段要带的 revision 从这里拿。"""
    with 连接() as c:
        x = c.execute(text("select * from issues where project_id=:p and id=:i"),
                      {"p": project_id, "i": issue_id}).mappings().first()
        if not x:
            raise _错(404, "NOT_FOUND", "没有这张问题单", "回清单重新进")
        线 = c.execute(text("""select created_at, created_by, action_code, from_status, to_status, note, change_snapshot
                                from issue_events where project_id=:p and issue_id=:i order by created_at, id"""),
                       {"p": project_id, "i": issue_id}).mappings().all()
        意见 = c.execute(text("""select id, status, verdict, problem_type, note, chat_trace_ref, asker_snapshot, asker_staff_code
                                  from opinions where project_id=:p and issue_id=:i order by created_at, id"""),
                        {"p": project_id, "i": issue_id}).mappings().all()
        重复的 = c.execute(text("""select i.id, i.title, (select count(*) from opinions o
                                     where o.project_id=i.project_id and o.issue_id=i.id) 意见数
                                    from issues i where i.project_id=:p and i.duplicate_of_issue_id=:i order by i.created_at, i.id"""),
                          {"p": project_id, "i": issue_id}).mappings().all()
        # PRD §5.2「重复问题:保留来源及独立受影响问答数」—— 主问题这边把重复单那几条意见挂的问答一起数,按聊天站那一轮去重
        受影响 = c.execute(text("""select count(distinct chat_trace_ref) from opinions
                                    where project_id=:p and chat_trace_ref is not null and issue_id in (
                                      select cast(:i as text) union all select id from issues where project_id=:p and duplicate_of_issue_id=:i)"""),
                          {"p": project_id, "i": issue_id}).scalar()
        主 = (c.execute(text("select id, title, status from issues where project_id=:p and id=:m"),
                       {"p": project_id, "m": x["duplicate_of_issue_id"]}).mappings().first()
             if x["duplicate_of_issue_id"] else None)
    return {"id": x["id"], "标题": x["title"], "状态": x["status"], "已解决": x["status"] in F.算已解决的状态,
            "业务影响": x["impact_note"], "复现条件": x["repro_note"], "根因类别": x["root_cause_type"],
            "根因核实": x["root_cause_status"], "方案": x["solution_note"], "验收标准": x["acceptance_note"],
            "目标版本": x["target_version"], "依赖": x["dependency_note"], "负责人": x["owner"],
            "处理时限": _给人看(x["due_date"]), "完成证据": x["completion_evidence_note"], "处理说明": x["resolution_note"],
            "搁置理由": x["shelve_reason"], "重新评估日期": _给人看(x["reevaluate_date"]),
            "最近一次关闭": _给人看(x["last_closed_at"]), "重开次数": x["reopen_count"],
            "主问题": ({"id": 主["id"], "标题": 主["title"], "状态": 主["status"]} if 主 else None),
            "重复指向它的": [{"id": r["id"], "标题": r["title"], "关联意见数": int(r["意见数"])} for r in 重复的],
            "受影响问答数": int(受影响 or 0),
            "建单时间": _给人看(x["created_at"]), "最近更新": _给人看(x["updated_at"]), "revision": x["revision"],
            "能改字段": x["status"] not in F.不许改字段的状态,
            "可选根因类别": list(F.根因类别们), "可选核实状态": list(F.核实状态们),
            "能做的动作": _能做的动作(x["status"]),
            "关联的意见": [{"id": o["id"], "状态": o["status"], "评价": o["verdict"], "问题类型": o["problem_type"],
                        "说明": o["note"], "聊天站trace": o["chat_trace_ref"],
                        "提问人": o["asker_snapshot"] or {"工号": o["asker_staff_code"]}} for o in 意见],
            "时间线": [{"时间": _给人看(e["created_at"]), "谁": e["created_by"], "动作": e["action_code"],
                      "从": e["from_status"], "到": e["to_status"], "说明": e["note"], "变化": e["change_snapshot"]}
                     for e in 线],
            "note": ("完成证据现在是一段文字 —— 绑真实发布版本 / 验证记录(PRD §4.3)还没做;"
                     "处理时限过了不标超时(几天算超时 PRD §10 待定)")}


def _锁一张(c, project_id, issue_id, if_match):
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把这张问题单详情里的 revision 放进 If-Match 头")
    x = c.execute(text("select * from issues where project_id=:p and id=:i for update"),
                  {"p": project_id, "i": issue_id}).mappings().first()
    if not x:
        raise _错(404, "NOT_FOUND", "没有这张问题单", "回清单重新进")
    if str(x["revision"]) != str(if_match).strip('"'):
        raise _错(409, "REVISION_CONFLICT", "这张问题单刚被别人改过", "刷新看一眼最新状态再处理")
    return x


# ── 改字段 ──────────────────────────────────────────────────────────────
@router.patch(前缀 + "/issues/{issue_id}")
async def 改问题单(project_id: str, issue_id: str, request: Request,
              if_match: str = Header(default=None, alias="If-Match"),
              me: 身份 = Depends(要权限("受理意见"))):
    """改标题 / 业务影响 / 复现 / 根因 / 方案 / 验收 / 目标版本 / 依赖 / 负责人 / 处理时限:只改给了的键,带 If-Match。
    **改根因类别或核实状态要写说明**(PRD §4.2「调整理由入日志」);每次改动在时间线记一行「改字段」,带前后值。
    已验证关闭 / 已重复 的不许改(要改先「关闭后复发」,重复的去改主问题)。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验字段(体)
    说明 = _字(体, "说明")
    if 说明 and len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if not 出 and not 坏:
        坏["字段"] = f"一个能改的字段都没给 —— 能改的:{list(可改字段)}"
    if 坏:
        raise _错(422, "VALIDATION", "问题单的字段不合格", "见字段错误", field_errors=坏)
    with 事务() as c:
        x = _锁一张(c, project_id, issue_id, if_match)
        if x["status"] in F.不许改字段的状态:
            raise _错(409, "TRANSITION_NOT_ALLOWED", f"「{x['status']}」的问题单不能改字段",
                      "已关闭的要改先「关闭后复发」重开;重复的去改它指向的主问题")
        变化 = {中: [_给人看(x[列]), _给人看(出[列])] for 中, 列 in 可改字段.items() if 列 in 出 and x[列] != 出[列]}
        if not 变化:
            raise _错(422, "VALIDATION", "给的值和现在一样,没有要改的", "改了再保存", field_errors={"字段": "没有变化"})
        if any(k in 变化 for k in 根因字段) and not 说明:
            raise _错(422, "VALIDATION", "改根因要写说明", "PRD §4.2:人工调整分类,调整理由入日志",
                      field_errors={"说明": "改根因类别 / 核实状态时必填"})
        后类别 = 出.get("root_cause_type", x["root_cause_type"])
        后核实 = 出.get("root_cause_status", x["root_cause_status"])
        if 后核实 == "原因已证实" and not 后类别:
            raise _错(422, "VALIDATION", "没分根因类别就不能说「原因已证实」", "先选是哪一类",
                      field_errors={"根因核实": "要先有根因类别"})
        设 = ", ".join(f"{列}=:c_{列}" for 列 in 出)
        r = c.execute(text(f"""update issues set {设}, revision=revision+1, updated_at=now()
                                where project_id=:p and id=:i returning revision"""),
                      {"p": project_id, "i": issue_id, **{"c_" + k: v for k, v in 出.items()}}).mappings().first()
        _记一步(c, x["organization_id"], project_id, me, issue_id, "改字段", x["status"], x["status"], 说明, 变化)
    return {"id": issue_id, "revision": r["revision"], "改了": list(变化)}


# ── 流转 ────────────────────────────────────────────────────────────────
@router.post(前缀 + "/issues/{issue_id}/actions")
async def 问题单一步(project_id: str, issue_id: str, request: Request,
                if_match: str = Header(default=None, alias="If-Match"),
                me: 身份 = Depends(要权限("受理意见"))):
    """`{动作, 说明?, 重新评估日期?, 主问题?, 处理说明?, 完成证据?}`,带 If-Match。流转照 issue_flow.流转(PRD §5.2),
    不在表里的 409;要写说明 / 要带字段的缺了 422。每一步追加一行时间线(带这一步改了的字段前后值)。

    - 暂不处理 → 已搁置:说明 = 理由,还要重新评估日期(不早于今天)。不计已解决
    - 标为重复 → 已重复:主问题要是同项目、不是自己、本身不是重复单;这张单关联的意见**留在这张单上**(保留来源)
    - 关闭 → 已验证关闭:处理说明 + 完成证据必填(⚠️ 证据现在是文字,版本 / 验证记录的真绑定是 PRD §4.3,没做)
    - 发布失败:留在待发布,记一条(说明里写错误)
    - 关闭后复发 → 处理中:重开次数 +1,**上一次关闭的说明 / 证据 / 时刻都不清**,时间线里那行「关闭」也还在"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    动作, 说明 = _字(体, "动作"), _字(体, "说明")
    for k in ("说明", "处理说明", "完成证据"):
        v = _字(体, k)
        if v and len(v) > (说明最长 if k == "说明" else 长文上限):
            raise _错(422, "VALIDATION", f"{k}太长", "写短一点", field_errors={k: f"最多 {说明最长 if k == '说明' else 长文上限} 字"})
    with 事务() as c:
        x = _锁一张(c, project_id, issue_id, if_match)
        能 = F.流转.get(x["status"], {})
        if 动作 not in 能:
            raise _错(409, "TRANSITION_NOT_ALLOWED", f"「{x['status']}」的问题单不能「{动作}」",
                      f"这一步能做的:{list(能) or '没有(已是终态)'}", field_errors={"动作": f"只收 {list(能)}"})
        坏 = {}
        if 动作 in F.要说明的动作 and not 说明:
            坏["说明"] = "这一步要写为什么" + ("(搁置的理由)" if 动作 == "暂不处理" else "")
        for k in F.动作要的字段.get(动作, ()):
            if not _字(体, k):
                坏[k] = "必填"
        if 坏:
            raise _错(422, "VALIDATION", f"「{动作}」缺东西", "见字段错误", field_errors=坏)
        到 = 能[动作]
        设, 参, 变化 = {}, {}, {}
        if 动作 == "暂不处理":
            try:
                日 = _dt.date.fromisoformat(_字(体, "重新评估日期"))
            except ValueError:
                raise _错(422, "VALIDATION", "重新评估日期格式不对", "写成 2026-12-01 这样",
                          field_errors={"重新评估日期": "要是日期"})
            if 日 < _今天():
                raise _错(422, "VALIDATION", "重新评估日期早于今天", "搁置要约一个将来再看的日子",
                          field_errors={"重新评估日期": "不能早于今天"})
            设 = {"shelve_reason": 说明, "reevaluate_date": 日}
        elif 动作 == "重新评估":
            # 回待分析:搁置的理由 / 日期清掉(当时那行「暂不处理」的变化里记着)
            设 = {"shelve_reason": None, "reevaluate_date": None}
        elif 动作 == "标为重复":
            主id = _字(体, "主问题")
            if 主id == issue_id:
                raise _错(422, "VALIDATION", "不能指向自己", "选另一张问题单", field_errors={"主问题": "不能是自己"})
            主 = c.execute(text("select id, status, duplicate_of_issue_id from issues where project_id=:p and id=:m"),
                          {"p": project_id, "m": 主id}).mappings().first()
            if not 主:
                raise _错(422, "VALIDATION", "这个项目里没有这张主问题单", "确认编号(只能指向同一个项目里的)",
                          field_errors={"主问题": "不存在"})
            if 主["status"] == "已重复":
                raise _错(422, "VALIDATION", f"「{主id}」自己就是重复单(指向 {主['duplicate_of_issue_id']})",
                          "直接指向它的主问题,不串成链", field_errors={"主问题": "本身是重复单"})
            指它 = c.execute(text("select count(*) from issues where project_id=:p and duplicate_of_issue_id=:i"),
                            {"p": project_id, "i": issue_id}).scalar()
            if 指它:
                raise _错(409, "HAS_DUPLICATES", f"已经有 {指它} 张重复单指向这张 —— 它再标成重复会串成链",
                          "让另一张标成这张的重复,或者先把这张当主问题处理完")
            设 = {"duplicate_of_issue_id": 主id}
        elif 动作 == "关闭":
            设 = {"resolution_note": _字(体, "处理说明"), "completion_evidence_note": _字(体, "完成证据")}
            参["关"] = True
        elif 动作 == "关闭后复发":
            变化["上一次关闭"] = {"时刻": _给人看(x["last_closed_at"]), "处理说明": x["resolution_note"],
                            "完成证据": x["completion_evidence_note"]}
            参["重开"] = True
        中文 = {"shelve_reason": "搁置理由", "reevaluate_date": "重新评估日期", "duplicate_of_issue_id": "主问题",
              "resolution_note": "处理说明", "completion_evidence_note": "完成证据"}
        for 列, v in 设.items():
            if x[列] != v:
                变化[中文[列]] = [_给人看(x[列]), _给人看(v)]
        额外 = "".join(f", {列}=:c_{列}" for 列 in 设)
        if 参.get("关"):
            额外 += ", last_closed_at=now()"
        if 参.get("重开"):
            额外 += ", reopen_count=reopen_count+1"
        r = c.execute(text(f"""update issues set status=:t, revision=revision+1, updated_at=now(){额外}
                                where project_id=:p and id=:i returning revision"""),
                      {"t": 到, "p": project_id, "i": issue_id, **{"c_" + k: v for k, v in 设.items()}}).mappings().first()
        _记一步(c, x["organization_id"], project_id, me, issue_id, 动作, x["status"], 到, 说明, 变化 or None)
    return {"id": issue_id, "从": x["status"], "到": 到, "revision": r["revision"],
            "note": {"发布失败": "留在待发布,这次失败记在时间线上;关联的意见不会被告知「已修复」",
                     "暂不处理": "已搁置 —— 不计已解决;到了重新评估日期要有人回来看(提醒这次没做)",
                     "关闭后复发": "重开回处理中;上一次关闭的记录都还在"}.get(动作, "记在时间线上了")}
