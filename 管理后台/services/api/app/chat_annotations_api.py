# -*- coding: utf-8 -*-
"""标注回复(11-21;用户 10-27 拍第 7 条,11-21 拍三条口径)—— 后台这一半。

日志里某一轮聊天站问答,点「标注」写一条**标准答案**;项目总开关打开后,聊天站对新问题先问模型
「和哪条标注是同一个意思」,命中就直接回标注答案(那一半在 agentsite,这里只管存、管、给清单、记命中)。

    GET    /chat-annotations                列表(?status=;提问原文按「查看敏感输入」授权,没有的只给长度)
    GET    /chat-annotations/active         给聊天站:总开关开着时所有「启用」的标注(全文);关着就空清单 + 开关=false
    POST   /chat-annotations                标一轮问答:体 {trace_id, standard_answer, note?}。提问 / 角色 / 调过的工具都从那一轮 trace 取,不接受调用方给
    PATCH  /chat-annotations/{id}           改答案 / 备注 / 启用停用(要 If-Match revision)
    POST   /chat-annotations/{id}/archive   归档(列表里不再出现、聊天站不再拿到;行留着当证据)
    PUT    /chat-annotations/switch         项目总开关(登记在 开关们,工作台「开关」那块看得到谁什么时候拨的)
    POST   /chat-annotations/{id}/hits      聊天站上报一次命中(hit_count + 1、last_hit_at)

三条口径(用户 11-21 拍):
  ① **哪些问答不许标 —— 按那一轮调过的工具自动判**(`可标注吗`):只调了知识类只读工具(backend/domains.py knowledge 领域里 kb_ 开头那些)
     或一个工具都没调的才能标;调过取数(查客户 / 订单 / 库存 / 任务…)或任何写工具的 → 422,原因里列出工具名。
     ToolSearch / Skill 是元工具不算;**认不出的工具按实时处理**(宁可少标)。
  ② **谁能标**:「改 Prompt/知识候选」权限 —— 标注答案和改规矩是一回事。另外要看得到提问原文(查看敏感输入),看不到原文的人标不了。
  ③ **怎么生效**:projects.chat_annotation_enabled 总开关默认关;开了后保存即生效,不走冻结 / 审核;每次命中记一笔;能单条停用。
"""
import importlib.util
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
启用, 停用 = "启用", "停用"
状态们 = (启用, 停用)
元工具 = frozenset({"ToolSearch", "Skill"})   # 聊天站的「找工具 / 用技能」,本身不取业务数据
_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


def _载领域():
    """从 backend/domains.py 读工具归属表(**唯一来源**,不抄一份);仓库布局不在(单独部署管理后台)时退到最小集,并标明。"""
    p = os.path.join(_根, "backend", "domains.py")
    try:
        spec = importlib.util.spec_from_file_location("_lanxiu_domains", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return dict(m.领域), True
    except Exception:
        return {"knowledge": ("kb_lookup", "kb_detail", "kb_combo", "kb_rag", "kb_read", "kb_tables",
                              "kb_pattern", "kb_size", "kb_lead", "kb_bom")}, False


领域, 领域表来自仓库 = _载领域()
# 知识类只读 = knowledge 领域里 kb_ 开头的。knowledge 里还有 set_piece_ratio / set_grade_diff(写)、pattern_queue / get_review_queue /
# grading_audit / motif_todo / review_motif(队列 / 待办,随时间变)—— 它们不是「知识」,按实时处理
知识类只读 = frozenset(t for t in 领域.get("knowledge", ()) if t.startswith("kb_"))
已知工具 = frozenset(t for ts in 领域.values() for t in ts)


def _工具短名(名):
    return str(名 or "").split("__")[-1].strip()


def 可标注吗(工具们):
    """按那一轮调过的工具判「这题是不是实时数据」→ (可以, 原因或 None)。规则只写这一处:runs_api 的「标注」块和 POST 都调它。"""
    取数或写, 不认识 = [], []
    for 名 in 工具们 or ():
        n = _工具短名(名)
        if not n or n in 元工具 or n in 知识类只读:
            continue
        (取数或写 if n in 已知工具 else 不认识).append(n)
    if not 取数或写 and not 不认识:
        return True, None
    原因 = []
    if 取数或写:
        原因.append("这一轮调过取数 / 写工具:" + "、".join(dict.fromkeys(取数或写))
                  + " —— 答案跟着数据变,标成固定答案会盖掉实时数据(用户 10-27 拍「实时数据的问题不许走标注」)")
    if 不认识:
        原因.append("认不出的工具:" + "、".join(dict.fromkeys(不认识)) + " —— 认不出就按实时处理")
    return False, ";".join(原因)


def _读json(s):
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except Exception:
        return None


def 问答与工具(步们):
    """从一轮的 span 行(stage / parent_span_id / 入 / 出)里取 提问 / 角色 / 回答 / 调过的工具 / 原文到期了吗。
    根步骤 = 没有父步骤、stage 以 invoke_agent 开头(聊天站推送的形状,见 runs_api.导入执行记录)。"""
    提问 = 角色 = 回答 = None
    到期 = False
    工具们 = []
    for s in 步们:
        stage = str(s["stage"] or "")
        if stage.startswith("execute_tool "):
            工具们.append(stage.split(" ", 1)[1].strip())
            continue
        if 提问 is None and s.get("parent_span_id") is None and stage.startswith("invoke_agent"):
            入 = _读json(s.get("入"))
            出 = _读json(s.get("出"))
            if isinstance(入, dict) and "到期删除" in 入:
                到期 = True
            elif isinstance(入, dict):
                提问 = 入.get("提问")
                角色 = 入.get("角色") or (stage.split(" ", 1)[1].strip() if " " in stage else None)
            if isinstance(出, dict):
                回答 = 出.get("回答")
    return {"提问": 提问, "角色": 角色, "回答": 回答, "工具们": 工具们, "原文到期了吗": 到期}


def _读步们(c, project_id, trace_id):
    return c.execute(text("""select id, parent_span_id, stage, cast(input_ref as text) 入, cast(output_ref as text) 出
                               from spans where project_id=:p and trace_id=:t order by started_at, id"""),
                     {"p": project_id, "t": trace_id}).mappings().all()


def _已有(c, project_id, trace_id):
    return c.execute(text("""select id, status, standard_answer, note, revision, hit_count, updated_at, created_by, archived_at
                               from chat_annotations where project_id=:p and trace_id=:t"""),
                     {"p": project_id, "t": trace_id}).mappings().first()


def 标注块(c, project_id, trace_id, me, 步们):
    """运行详情里的「标注」块:能不能标、为什么、调过哪些工具、已经标过的那条、这个人有没有权限。规则和 POST 同一份。"""
    q = 问答与工具(步们)
    已 = _已有(c, project_id, trace_id)
    可以, 原因 = 可标注吗(q["工具们"])
    if q["原文到期了吗"]:
        可以, 原因 = False, "这一轮的提问原文已到期删除(聊天站原文只留 30 天),标不了"
    elif q["提问"] is None:
        可以, 原因 = False, "这一轮没有提问记录(不是聊天站的一轮,或推送时没带提问)"
    有权 = bool(me.能("改 Prompt/知识候选")) and bool(me.看得到原文吗())
    out = {"可以吗": 可以, "原因": 原因, "调过的工具": q["工具们"], "角色": q["角色"], "有权标吗": 有权,
           "没权的原因": (None if 有权 else "要「改 Prompt/知识候选」权限,而且要看得到提问原文(查看敏感输入)"),
           "已有": None}
    if 已 and not 已["archived_at"]:
        out["已有"] = {k: 已[k] for k in ("id", "status", "standard_answer", "note", "revision", "hit_count", "updated_at", "created_by")}
    return out


def _开关(c, project_id):
    r = c.execute(text("select coalesce(chat_annotation_enabled, false) v from projects where id=:p"), {"p": project_id}).first()
    return bool(r and r[0])


def _行(r, 看得到原文):
    d = dict(r)
    if not 看得到原文:
        d["提问长度"] = len(d.get("question") or "")
        d["question"] = None
        d["原文要授权"] = "提问原文要「查看敏感输入/独立测试答案」授权,这里只给长度"
    d["tools_used"] = _读json(d.get("tools_used")) if isinstance(d.get("tools_used"), str) else d.get("tools_used")
    return d


@router.get(前缀 + "/chat-annotations")
def 标注列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
         status: str = Query(None), limit: int = Query(50, ge=1, le=200), page: int = Query(1, ge=1)):
    if status is not None and status not in 状态们:
        raise _错(422, "VALIDATION", f"status 只能是 {' / '.join(状态们)}", "去掉 status 看全部", field_errors={"status": "不认识"})
    看 = me.看得到原文吗()
    with 连接() as c:
        rs = c.execute(text("""
            select count(*) over () 全量, id, project_id, trace_id, assistant_role, question, standard_answer, note,
                   cast(tools_used as text) tools_used, status, hit_count, last_hit_at, revision, created_by, created_at, updated_at
              from chat_annotations
             where project_id=:p and archived_at is null and (cast(:s as text) is null or status = cast(:s as text))
             order by updated_at desc nulls last, created_at desc, id desc
             limit :n offset :o"""), {"p": project_id, "s": status, "n": limit, "o": (page - 1) * limit}).mappings().all()
        开 = _开关(c, project_id)
    出 = []
    for r in rs:
        d = _行(r, 看); d.pop("全量", None); 出.append(d)
    from workflows_api import 分页信封
    return {"items": 出, **分页信封(rs, page, limit), "开关": 开, "看得到原文吗": 看,
            "note": ("**总开关关着,这些标注一条都不会生效**" if not 开 else "总开关开着:「启用」的标注聊天站都会拿去比对")
                    + ";命中数由聊天站上报,不是这里算的"}


@router.get(前缀 + "/chat-annotations/active")
def 启用中的标注(project_id: str, me: 身份 = Depends(要权限("运行评测"))):
    """给聊天站用:开着才给;给的是**全文**(机器比对要原文),所以权限用聊天站推执行记录那一档(运行评测),不是「查看有权配置」。"""
    with 连接() as c:
        开 = _开关(c, project_id)
        rs = [] if not 开 else c.execute(text("""
            select id, trace_id, assistant_role, question, standard_answer, revision
              from chat_annotations where project_id=:p and archived_at is null and status=:s
             order by created_at, id"""), {"p": project_id, "s": 启用}).mappings().all()
    return {"开关": 开, "items": [dict(r) for r in rs], "总数": len(rs),
            "note": "命中后请 POST /chat-annotations/{id}/hits 记一笔;实时数据的问题在标注时就已拦住,这份清单里没有"}


@router.put(前缀 + "/chat-annotations/switch")
async def 拨总开关(project_id: str, request: Request, me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    体 = await request.json()
    v = 体.get("enabled") if isinstance(体, dict) else None
    if not isinstance(v, bool):
        raise _错(422, "VALIDATION", "体要是 {\"enabled\": true | false}", "布尔值,不是字串", field_errors={"enabled": "必填布尔"})
    from workflows_api import _审计
    with 事务() as c:
        老 = _开关(c, project_id)
        c.execute(text("update projects set chat_annotation_enabled = :v where id=:p"), {"v": v, "p": project_id})
        _审计(c, me, "chat_annotation.switch", {"enabled": v, "原来": 老})
        n = c.execute(text("select count(*) from chat_annotations where project_id=:p and archived_at is null and status=:s"),
                      {"p": project_id, "s": 启用}).scalar()
    return {"开关": v, "原来": 老, "启用中的标注": int(n or 0),
            "note": ("打开了:聊天站对每个新问题先比对这 %d 条标注,命中直接回标注答案" % int(n or 0)) if v
                    else "关了:聊天站不再拿标注答案回话,标注都留着"}


@router.post(前缀 + "/chat-annotations", status_code=201)
async def 标一轮问答(project_id: str, request: Request, me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    if not me.看得到原文吗():
        raise _错(403, "FORBIDDEN", "看不到提问原文的人不能标注",
                  "要「查看敏感输入/独立测试答案」这条专项授权 —— 标注是对着那句原话写答案,看不到原话标不准")
    体 = await request.json()
    if not isinstance(体, dict):
        raise _错(422, "VALIDATION", "体要是对象", "{trace_id, standard_answer, note?}")
    tid = str(体.get("trace_id") or "").strip()
    答 = str(体.get("standard_answer") or "").strip()
    备 = (str(体.get("note")).strip() or None) if 体.get("note") is not None else None
    错 = {}
    if not tid: 错["trace_id"] = "必填:要标的那一轮运行记录 id"
    if not 答: 错["standard_answer"] = "必填:标准答案不能空"
    if len(答) > 20000: 错["standard_answer"] = "太长(上限 20000 字)"
    if 错:
        raise _错(422, "VALIDATION", "标注缺字段", "补上再提", field_errors=错)
    from workflows_api import _审计
    with 事务() as c:
        t = c.execute(text("select id, entry_kind from traces where project_id=:p and id=:i"), {"p": project_id, "i": tid}).mappings().first()
        if not t:
            raise _错(404, "NOT_FOUND", "没有这条运行记录", "回运行记录列表重新进入")   # 不泄露别的项目有没有这个 id
        q = 问答与工具(_读步们(c, project_id, tid))
        if q["原文到期了吗"]:
            raise _错(422, "CHAT_ANNOTATION_EXPIRED", "这一轮的提问原文已到期删除,标不了", "聊天站原文只留 30 天;找最近的一轮同类问题标")
        if q["提问"] is None:
            raise _错(422, "CHAT_ANNOTATION_NO_QUESTION", "这一轮没有提问记录", "只有聊天站推过来、带提问的那种运行记录能标")
        可以, 原因 = 可标注吗(q["工具们"])
        if not 可以:
            raise _错(422, "CHAT_ANNOTATION_REALTIME", "这题是实时数据的问题,不许标", 原因,
                      field_errors={"trace_id": "调过的工具:" + "、".join(q["工具们"])})
        已 = _已有(c, project_id, tid)
        if 已 and not 已["archived_at"]:
            raise _错(409, "CHAT_ANNOTATION_EXISTS", "这一轮已经标过了", f"去改那一条(id={已['id']}),一轮只能标一条",
                      field_errors={"trace_id": 已["id"]})
        if 已:   # 归档过的:同一轮再标 = 把那条起回来(唯一键钉着,不另起一行)
            c.execute(text("""update chat_annotations set standard_answer=:a, note=:n, status=:s, archived_at=null,
                                     revision=coalesce(revision,0)+1, updated_at=now(), tools_used=cast(:tu as jsonb),
                                     question=:q, assistant_role=:r
                               where project_id=:p and id=:i"""),
                      {"a": 答, "n": 备, "s": 启用, "tu": json.dumps(q["工具们"], ensure_ascii=False), "q": q["提问"], "r": q["角色"],
                       "p": project_id, "i": 已["id"]})
            aid = 已["id"]
        else:
            aid = f"ann_{uuid.uuid4().hex[:12]}"
            c.execute(text("""insert into chat_annotations (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                                     trace_id, assistant_role, question, standard_answer, note, tools_used, status, hit_count)
                              values (:i,:o,:p, now(), :u, now(), 1, :t, :r, :q, :a, :n, cast(:tu as jsonb), :s, 0)"""),
                      {"i": aid, "o": me.org_id, "p": project_id, "u": me.user_id, "t": tid, "r": q["角色"], "q": q["提问"], "a": 答, "n": 备,
                       "tu": json.dumps(q["工具们"], ensure_ascii=False), "s": 启用})
        _审计(c, me, "chat_annotation.create", {"annotation_id": aid, "trace_id": tid, "tools_used": q["工具们"], "重新启用了归档的吗": bool(已)})
        r = c.execute(text("""select id, project_id, trace_id, assistant_role, question, standard_answer, note, cast(tools_used as text) tools_used,
                                     status, hit_count, last_hit_at, revision, created_by, created_at, updated_at
                                from chat_annotations where project_id=:p and id=:i"""), {"p": project_id, "i": aid}).mappings().first()
        开 = _开关(c, project_id)
    d = _行(r, True)
    d["开关"] = 开
    d["note"] = ("已存。**项目总开关还没开**,聊天站暂时不会用它 —— 到「标注回复」页打开" if not 开
                 else "已存并生效:聊天站对新问题会先比对它")
    return d


def _要IfMatch(if_match):
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把列表里这条标注的 revision 放进 If-Match 头 —— 两个人同时改,后到的不许静默覆盖")
    try:
        return int(str(if_match).strip('"'))
    except ValueError:
        raise _错(409, "IF_MATCH_REQUIRED", "If-Match 不是一个 revision 数字", "列表接口每条都给了 `revision`,原样放进 If-Match 头")


def _锁(c, project_id, aid):
    r = c.execute(text("""select id, trace_id, status, standard_answer, note, revision, archived_at
                            from chat_annotations where project_id=:p and id=:i for update"""), {"p": project_id, "i": aid}).mappings().first()
    if not r or r["archived_at"]:
        raise _错(404, "NOT_FOUND", "没有这条标注(或已归档)", "回「标注回复」列表")
    return r


@router.patch(前缀 + "/chat-annotations/{aid}")
async def 改标注(project_id: str, aid: str, request: Request, me: 身份 = Depends(要权限("改 Prompt/知识候选")),
             if_match: str = Header(default=None, alias="If-Match")):
    rev = _要IfMatch(if_match)
    体 = await request.json()
    if not isinstance(体, dict) or not (set(体) & {"standard_answer", "note", "status"}):
        raise _错(422, "VALIDATION", "体里要有 standard_answer / note / status 至少一项", "只传要改的字段")
    if "status" in 体 and 体["status"] not in 状态们:
        raise _错(422, "VALIDATION", f"status 只能是 {' / '.join(状态们)}", "归档走 POST /chat-annotations/{id}/archive", field_errors={"status": "不认识"})
    if "standard_answer" in 体 and not str(体["standard_answer"] or "").strip():
        raise _错(422, "VALIDATION", "标准答案不能改成空", "要让它不生效就 status=停用", field_errors={"standard_answer": "空"})
    from workflows_api import _审计
    with 事务() as c:
        老 = _锁(c, project_id, aid)
        if int(老["revision"] or 0) != rev:
            raise _错(409, "CONFLICT", f"这条标注已经被改过(现在是 revision {老['revision']})", "刷新后再改",
                      field_errors={"If-Match": str(老["revision"])})
        新 = {"a": str(体.get("standard_answer", 老["standard_answer"])).strip(),
             "n": (str(体["note"]).strip() or None) if "note" in 体 and 体["note"] is not None else (None if "note" in 体 else 老["note"]),
             "s": 体.get("status", 老["status"])}
        c.execute(text("""update chat_annotations set standard_answer=:a, note=:n, status=:s, revision=revision+1, updated_at=now()
                           where project_id=:p and id=:i"""), {**新, "p": project_id, "i": aid})
        _审计(c, me, "chat_annotation.update", {"annotation_id": aid, "改了": sorted(set(体) & {"standard_answer", "note", "status"}),
                                                "status": 新["s"]})
    return {"id": aid, "revision": rev + 1, "status": 新["s"], "note": "已改,保存即生效(总开关开着的话)"}


@router.post(前缀 + "/chat-annotations/{aid}/archive")
def 归档标注(project_id: str, aid: str, me: 身份 = Depends(要权限("改 Prompt/知识候选")),
          if_match: str = Header(default=None, alias="If-Match")):
    rev = _要IfMatch(if_match)
    from workflows_api import _审计
    with 事务() as c:
        老 = _锁(c, project_id, aid)
        if int(老["revision"] or 0) != rev:
            raise _错(409, "CONFLICT", f"这条标注已经被改过(现在是 revision {老['revision']})", "刷新后再归档")
        c.execute(text("""update chat_annotations set archived_at=now(), status=:s, revision=revision+1, updated_at=now()
                           where project_id=:p and id=:i"""), {"s": 停用, "p": project_id, "i": aid})
        _审计(c, me, "chat_annotation.archive", {"annotation_id": aid, "trace_id": 老["trace_id"]})
    return {"id": aid, "归档了": True, "note": "列表里不再出现、聊天站不再拿到;同一轮再标会把它起回来"}


@router.post(前缀 + "/chat-annotations/{aid}/hits")
async def 记一次命中(project_id: str, aid: str, request: Request, me: 身份 = Depends(要权限("运行评测"))):
    """聊天站命中一条标注后上报。不审计(量大),只加计数;停用 / 归档的也 404 —— 聊天站拿到的清单本来就不该有它。"""
    try:
        体 = await request.json()
    except Exception:
        体 = {}
    with 事务() as c:
        n = c.execute(text("""update chat_annotations set hit_count = coalesce(hit_count,0)+1, last_hit_at=now()
                               where project_id=:p and id=:i and archived_at is null and status=:s
                           returning hit_count"""), {"p": project_id, "i": aid, "s": 启用}).first()
    if not n:
        raise _错(404, "NOT_FOUND", "没有这条启用中的标注", "重新拉 /chat-annotations/active 清单")
    return {"id": aid, "hit_count": int(n[0]), "trace_id": (体 or {}).get("trace_id")}
